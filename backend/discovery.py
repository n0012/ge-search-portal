"""Vertex AI Search (Discovery Engine) retrieval over the data store's serving config.

Answer/retrieval calls (ALL hit the GE engine so traffic is covered by the GE subscription):
  retrieve()            -> ranked docs, NO summary (engine :search; we answer after the ACL trim)
  assist()              -> grounded answer + citations via the GE engine assistant (:streamAssist),
                           restricted to an explicit id set (the answer path for every surface)
  answer_with_filter()  -> docs + AI summary via :search summarySpec (legacy, unused)

A `filter` expression (built from UI facets) is applied SERVER-SIDE, so it scopes
retrieval AND summarization before anything else — independent of the ACL trim.
"""
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import google.auth
from google.auth.transport.requests import AuthorizedSession

import config
from core import build_filter, parse_doc  # noqa: F401 (build_filter re-exported)

_session = None


def _sess():
    global _session
    if _session is None:
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _session = AuthorizedSession(creds)
    return _session


# Facets offered to the UI as data filters (separate from the ACL trim).
FACET_FIELDS = ["company", "report_kind", "research_source", "research_area",
                "doc_type", "year"]


def _search(query, page_size, summary=False, filter_="", facet_fields=None):
    url = f"https://{config.DE_HOST}/v1/{config.SERVING_CONFIG}:search"
    body = {
        "query": query,
        "pageSize": page_size,
        "contentSearchSpec": {"snippetSpec": {"returnSnippet": True}},
        # quality knobs (cf. search/create_datastore_and_search.ipynb)
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
    }
    # Ask VAIS for extractive segments (longer answer-bearing passages, with adjacent context)
    # so the reranker and grounding prompt get real passages instead of keyword snippets.
    if config.RERANK_EXTRACTIVE:
        body["contentSearchSpec"]["extractiveContentSpec"] = {
            "maxExtractiveSegmentCount": 2,
            "numPreviousSegments": 1, "numNextSegments": 1,
            "returnExtractiveSegmentScore": True,
        }
    # recency boost (cf. query_level_boosting_filtering_and_facets.ipynb)
    boost_years = [y.strip() for y in config.BOOST_RECENT_YEARS.split(",") if y.strip()]
    if boost_years:
        quoted = ", ".join('"%s"' % y for y in boost_years)
        body["boostSpec"] = {"conditionBoostSpecs": [
            {"condition": f"year: ANY({quoted})", "boost": 0.3}]}
    if filter_:
        body["filter"] = filter_
    if facet_fields:
        body["facetSpecs"] = [{"facetKey": {"key": f}, "limit": 20} for f in facet_fields]
    if summary:
        body["contentSearchSpec"]["summarySpec"] = {
            "summaryResultCount": 5, "includeCitations": True,
            "ignoreAdversarialQuery": True, "ignoreNonSummarySeekingQuery": True,
        }
    return _post_with_retry(url, body)


_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _transient(r):
    """Retry-eligible failures only: server hiccups (5xx/429) and the window where a
    just-declared filterable field (e.g. acl_groups after a schema change) is still
    propagating across serving replicas and yields a 400 "Unsupported field"."""
    if r.status_code in _RETRYABLE_STATUS:
        return True
    if r.status_code == 400:
        try:
            msg = (r.json().get("error", {}) or {}).get("message", "")
        except Exception:
            msg = ""
        return "Unsupported field" in msg
    return False


def _post_with_retry(url, body, max_draws=5, hedge_after=1.2):
    """POST a :search with STAGGERED-HEDGED attempts: fire one request; if it hasn't
    answered within `hedge_after` seconds (or failed transiently), launch another
    identical draw in parallel — first 200 wins, up to `max_draws` total.

    Why hedging instead of serial retry+backoff: during (re)index propagation the
    engine's serving replicas flap INDEPENDENTLY per request (observed live: ~35% of
    identical calls 400/500, and 2-20s latencies, for hours), so serial retries made
    users wait out several bad draws in a row — 12-25s searches. A hedged draw makes
    latency ≈ the fastest good replica, while a healthy backend still costs exactly
    one request. Queries at the GE engine are covered by the per-seat subscription,
    so extra draws add no marginal cost. Only transient failures are hedged (anything
    else raises immediately), and the filter is never weakened, so a draw can't leak.
    Fail-closed: all draws exhausted -> raise."""
    ex = ThreadPoolExecutor(max_workers=max_draws)
    last = None
    try:
        pending = {ex.submit(_sess().post, url, json=body, timeout=60)}
        draws = 1
        while pending or draws < max_draws:
            if not pending:  # every draw so far failed transiently — redraw
                time.sleep(0.2)
                pending.add(ex.submit(_sess().post, url, json=body, timeout=60))
                draws += 1
            done, pending = wait(pending, return_when=FIRST_COMPLETED,
                                 timeout=hedge_after if draws < max_draws else None)
            if not done and draws < max_draws:  # slow draw — hedge with a parallel one
                pending.add(ex.submit(_sess().post, url, json=body, timeout=60))
                draws += 1
                continue
            for f in done:
                try:
                    r = f.result()
                except Exception:
                    continue  # connection-level failure — another draw may still win
                if r.status_code == 200:
                    return r.json()
                last = r
                if not _transient(r):
                    r.raise_for_status()
    finally:
        # don't wait for losing draws — they finish (or time out) in the background
        ex.shutdown(wait=False, cancel_futures=True)
    if last is None:
        raise RuntimeError("engine search failed: no response from any attempt")
    last.raise_for_status()
    return last.json()


def _facets(js):
    """Parse the search response facets into {field: [{value, count}, ...]} for UI chips."""
    out = {}
    for f in js.get("facets", []) or []:
        vals = [{"value": v.get("value"), "count": v.get("count")}
                for v in f.get("values", []) or []]
        if vals:
            out[f.get("key")] = vals
    return out


_doc = parse_doc  # backwards-compatible alias


def retrieve(query, page_size, filter_="", with_facets=False):
    """Ranked docs (no summary). Returns (docs, facets); facets is {} unless requested.

    NOTE: facet counts reflect the ACL-unaware result set (pre-trim). For a strict
    demo you can hide counts; values still only span the data store, not per-user.
    """
    js = _search(query, page_size, summary=False, filter_=filter_,
                 facet_fields=FACET_FIELDS if with_facets else None)
    docs = [_doc(r) for r in js.get("results", [])]
    return docs, (_facets(js) if with_facets else {})


def rerank(query, docs, top_n=None):
    """Reorder docs with the Discovery Engine semantic Ranking API (cross-encoder).
    Attaches the per-doc relevance score as `rerankScore` (0-1) for optional display.
    Best-effort: disabled, empty, or any error → docs returned unchanged. Emits a one-line
    structured log on success and on failure (the feature is otherwise invisible)."""
    n = top_n or config.RERANK_TOP_N
    if not config.RERANK or not query or len(docs) < 2:
        return docs
    head = docs[:n]
    # Feed the cross-encoder the extractive segment (answer-bearing passage) when available,
    # falling back to the snippet/title. Snippets are short keyword fragments and score low;
    # segments give the reranker fair, directly-relevant input.
    records = [{"id": str(i), "title": d.get("title") or "",
                "content": (d.get("segment") or d.get("snippet") or d.get("title") or "")[:4000]}
               for i, d in enumerate(head)]
    url = (f"https://{config.DE_HOST}/v1/projects/{config.PROJECT_ID}/locations/"
           f"{config.LOCATION}/rankingConfigs/default_ranking_config:rank")
    body = {"model": config.RERANK_MODEL, "query": query, "records": records,
            "ignoreRecordDetailsInResponse": True}
    try:
        r = _sess().post(url, json=body, headers={"X-Goog-User-Project": config.PROJECT_ID},
                         timeout=20)
        r.raise_for_status()
        # ignoreRecordDetailsInResponse=True → each record is just {id, score}
        ranked = [(int(rec["id"]), rec.get("score")) for rec in r.json().get("records", [])
                  if "id" in rec]
    except Exception as e:
        print("rerank skipped: %s: %s" % (type(e).__name__, str(e)[:200]), flush=True)
        return docs
    if not ranked:
        return docs
    order = [i for i, _ in ranked]
    for i, score in ranked:
        if i < len(head) and score is not None:
            head[i]["rerankScore"] = round(float(score), 4)
    seen = set(order)
    out = ([head[i] for i in order if i < len(head)]
           + [d for i, d in enumerate(docs) if i not in seen])
    n_seg = sum(1 for d in head if d.get("segment"))
    print("rerank ok: model=%s in=%d ranked=%d segments=%d/%d top3=%s" % (
        config.RERANK_MODEL, len(head), len(order), n_seg, len(head),
        ",".join("%.3f" % (d.get("rerankScore") or 0) for d in out[:3])), flush=True)
    return out


def search_faceted(query, page_size, group_ids, selected, cascade=True):
    """Server-side ACL trim + cascading facets in one shot. Returns (docs, facets).

    The security trim is enforced by VAIS via the indexed `acl_groups` field
    (`acl_groups: ANY(<user groups>)`), so this scales to any corpus size — no app-side
    sampling. Cascade is exclude-own-field: a field's own selection is dropped when
    computing ITS facet, so siblings stay visible (true multi-select), while every other
    facet reflects the full current selection.

    cascade=False skips the per-active-field recompute (an extra engine query per active
    filter) and returns after the single base call — active fields' facet values are then
    own-filtered until the caller patches them via cascade_facets() (how /api/search +
    /api/facets split the work so a filter click renders results immediately).

    group_ids: the user's live Firestore groups. selected: {field: [values]} UI filters.
    """
    if not group_ids:
        return [], {}
    acl = {"acl_groups": sorted(group_ids)}
    full = build_filter({**acl, **selected})
    # overfetch when reranking so the semantic reranker can pull strong docs up from deeper
    # in the native-ranked list, then show the top page_size.
    fetch_n = max(page_size, config.RERANK_TOP_N) if config.RERANK else page_size
    base = _search(query, fetch_n, filter_=full, facet_fields=FACET_FIELDS)
    facets = _facets(base)  # facet counts are corpus-wide for the filter, independent of fetch_n
    docs = [_doc(r) for r in base.get("results", [])]
    docs = rerank(query, docs)[:page_size]  # semantic re-rank BEFORE results/AI see them

    if cascade:
        for field, vals in cascade_facets(query, group_ids, selected).items():
            if vals:
                facets[field] = vals
            else:
                facets.pop(field, None)
    return docs, facets


def cascade_facets(query, group_ids, selected):
    """Recompute each actively-filtered field's facet WITHOUT its own filter (parallel;
    usually 0-2 fields) so sibling values stay visible for multi-select. The base search
    already cascades every non-active field. Returns {field: [{value, count}, ...]},
    with [] when a field matches nothing (caller drops the chip group). Same ACL scope
    as search, so counts can never reveal hidden docs."""
    active = [f for f in selected if f in FACET_FIELDS]
    if not group_ids or not active:
        return {}
    acl = {"acl_groups": sorted(group_ids)}

    def own_excluded(field):
        f = build_filter({**acl, **{k: v for k, v in selected.items() if k != field}})
        return field, _facets(_search(query, 1, filter_=f, facet_fields=[field])).get(field, [])

    with ThreadPoolExecutor(max_workers=min(4, len(active))) as ex:
        return dict(ex.map(own_excluded, active))


def write_user_event(event_type, query=None, document_ids=None, user_id=None):
    """Report an interaction event for VAIS autotuning (learn-to-rank).

    event_type: "search" | "view-item" (we map a result click to view-item).
    Best-effort — never raises into the request path, and fire-and-forget (a daemon
    thread) so it never ADDS latency either: it posts to the same Discovery Engine
    backend as search, so when serving is slow/churning a synchronous call here
    doubled the user-visible latency (up to its full timeout). Losing an occasional
    advisory autotuning signal is fine; returns the Thread for tests to join.
    cf. record_user_events.ipynb.
    """
    event = {
        "eventType": event_type,
        "userPseudoId": user_id or "anonymous",
    }
    if query is not None:
        event["searchInfo"] = {"searchQuery": query}
    if document_ids:
        event["documents"] = [{"id": d} for d in document_ids if d]
    url = (f"https://{config.DE_HOST}/v1/projects/{config.PROJECT_ID}/locations/"
           f"{config.LOCATION}/collections/default_collection/dataStores/"
           f"{config.DATA_STORE_ID}/userEvents:write")

    def _post():
        try:
            _sess().post(url, json=event, timeout=15)
        except Exception:
            pass

    t = threading.Thread(target=_post, daemon=True)
    t.start()
    return t


def get_document(document_id):
    """Fetch one document's metadata: {documentId, title, gcsUri}. None on failure."""
    url = (f"https://{config.DE_HOST}/v1/{config.DATA_STORE_PATH}/branches/"
           f"default_branch/documents/{document_id}")
    try:
        r = _sess().get(url, timeout=30)
        r.raise_for_status()
        j = r.json()
    except Exception:
        return None
    sd = j.get("structData", {}) or {}
    return {"documentId": j.get("id"),
            "title": sd.get("title") or j.get("id"),
            "gcsUri": ((j.get("content") or {}).get("uri")) or None}


def get_content_uri(document_id):
    """Imported GCS uri (content.uri) for signing — None if unavailable."""
    meta = get_document(document_id)
    return meta.get("gcsUri") if meta else None


def answer_with_filter(query, doc_ids, base_filter=""):
    """5a: re-query WITH summary, restricted to the authorized doc ids (+ facet filter)."""
    if not doc_ids:
        return "", []
    id_filter = "id: ANY(" + ", ".join('"%s"' % i for i in doc_ids) + ")"
    filter_ = f"({base_filter}) AND ({id_filter})" if base_filter else id_filter
    js = _search(query, len(doc_ids), summary=True, filter_=filter_)
    summary = (js.get("summary", {}) or {}).get("summaryText", "")
    return summary, [_doc(r) for r in js.get("results", [])]


def _assist_refs_to_docs(references):
    """Map streamAssist grounding references -> our flat citation/doc shape. Each reference's
    parent doc lives under `documentMetadata` ({document, uri, title}); cited chunk text (if any)
    under `content`/`chunkText`. Deduped by document id, order preserved."""
    out, seen = [], set()
    for ref in references or []:
        meta = ref.get("documentMetadata") or {}
        doc_id = (meta.get("document") or "").rsplit("/", 1)[-1] or None
        if doc_id and doc_id in seen:
            continue
        if doc_id:
            seen.add(doc_id)
        out.append({
            "documentId": doc_id,
            "title": meta.get("title") or "",
            "sourceUrl": meta.get("uri"),
            "snippet": ref.get("content") or ref.get("chunkText") or "",
        })
    return out


def _parse_assist_stream(text):
    """streamAssist returns a stream of StreamAssistResponse objects. Tolerate the common wire
    forms: a single JSON array, one JSON object, or SSE 'data:' lines. Returns a list of events."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        js = json.loads(text)
        return js if isinstance(js, list) else [js]
    except Exception:
        pass
    events = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line in ("[", "]", ","):
            continue
        line = line.rstrip(",")
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events


def _assist_once(query, base_filter, session):
    """One :streamAssist call. Returns (text, docs, out_session, n_events). Raises on
    transport/HTTP error so the caller can retry."""
    url = f"https://{config.DE_HOST}/v1/{config.ASSISTANT_PATH}:streamAssist"
    body = {"query": {"text": query},
            "toolsSpec": {"vertexAiSearchSpec": {"filter": base_filter}}}
    if session:
        body["session"] = session
    r = _sess().post(url, json=body, timeout=120)
    r.raise_for_status()
    events = _parse_assist_stream(r.text)
    parts, refs, out_session = [], [], None
    for ev in events:
        si = ev.get("sessionInfo", {}) or {}
        if si.get("session"):
            out_session = si["session"]
        for reply in (ev.get("answer", {}) or {}).get("replies", []) or []:
            gc = reply.get("groundedContent", {}) or {}
            # AssistantContent carries the text directly (`content.text`), not a Gemini-style
            # `parts[]`; `thought: true` chunks are model reasoning, not answer text.
            content = gc.get("content", {}) or {}
            if content.get("text") and not content.get("thought"):
                parts.append(content["text"])
            refs.extend((gc.get("textGroundingMetadata", {}) or {}).get("references", []) or [])
    return "".join(parts), _assist_refs_to_docs(refs), out_session, len(events)


def assist(query, doc_ids, base_filter="", session=None):
    """Grounded answer via the Gemini Enterprise engine assistant (:streamAssist), scoped by
    base_filter — the caller's ACL(+facet) predicate, e.g. 'acl_groups: ANY("finance")'.
    Querying the GE engine keeps the call covered by the GE subscription. Returns
    (answerText, citation_docs, session). Best-effort: errors -> ("", [], None).

    `session` threads the assistant's conversation: pass the value returned by a prior
    call so follow-ups keep context ("a trend from these docs" resolves); None starts a
    fresh conversation. The ACL filter is still sent every turn, so the trim holds.

    Grounding-failure retry: when the assistant's internal search tool flakes (the same
    serving-replica turbulence that hits :search), it grounds ZERO references and emits a
    misleading "I can't reach the repository / upload a file" boilerplate. A healthy call
    grounds ≥1 ref, so we retry once on zero-refs; if it still can't ground, we return
    EMPTY text (not the ungrounded boilerplate — an ungrounded answer is worse than none
    in a grounded-search product) so the UI shows the honest "no answer" state. Callers
    keep their citation fallback.

    doc_ids is the ACL-trimmed page — the anything-to-answer guard and citation fallback.
    It is NOT sent as a filter: `id` isn't filterable on a GE engine (verified live).
    Fail-closed: no docs or no filter -> no call."""
    if not doc_ids or not base_filter:
        return "", [], None
    text, docs, out_session = "", [], None
    for attempt in range(2):  # 1 retry — assist calls are slow, and the flap usually clears
        try:
            text, docs, out_session, nev = _assist_once(query, base_filter, session)
        except Exception as e:
            print("assist error (attempt %d): %s: %s" % (
                attempt + 1, type(e).__name__, str(e)[:160]), flush=True)
            continue
        print("assist ok: ids=%d events=%d refs=%d chars=%d attempt=%d" % (
            len(doc_ids), nev, len(docs), len(text), attempt + 1), flush=True)
        if docs:  # grounded -> good answer
            return text, docs, out_session
        # zero refs = grounding failed (flap / degraded boilerplate); retry once
    # never grounded: suppress the ungrounded text, keep the session for continuity
    return "", docs, out_session
