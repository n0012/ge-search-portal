"""Vertex AI Search (Discovery Engine) retrieval over the data store's serving config.

Two calls:
  retrieve()            -> ranked docs, NO summary (we summarize after the ACL trim)
  answer_with_filter()  -> docs + AI summary, restricted to an explicit id set (5a)

A `filter` expression (built from UI facets) is applied SERVER-SIDE, so it scopes
retrieval AND summarization before anything else — independent of the ACL trim.
"""
import time
from concurrent.futures import ThreadPoolExecutor

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


def _post_with_retry(url, body, attempts=3):
    """POST a :search with a small, fail-closed retry. Retries only transient cases —
    server hiccups (5xx/429) and the brief window where a just-declared filterable field
    (e.g. acl_groups after a schema change) is still propagating across serving replicas
    and yields a 400 "Unsupported field". The filter itself is never weakened, so a retry
    can't leak. Anything else raises immediately."""
    last = None
    for attempt in range(attempts):
        r = _sess().post(url, json=body, timeout=60)
        if r.status_code == 200:
            return r.json()
        msg = ""
        try:
            msg = (r.json().get("error", {}) or {}).get("message", "")
        except Exception:
            pass
        transient = r.status_code in _RETRYABLE_STATUS or (
            r.status_code == 400 and "Unsupported field" in msg)
        last = r
        if not transient or attempt == attempts - 1:
            break
        time.sleep(0.6 * (attempt + 1))
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
    records = [{"id": str(i), "title": d.get("title") or "",
                "content": (d.get("snippet") or d.get("title") or "")[:2000]}
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
    print("rerank ok: model=%s in=%d ranked=%d top3=%s" % (
        config.RERANK_MODEL, len(head), len(order),
        ",".join("%.3f" % (d.get("rerankScore") or 0) for d in out[:3])), flush=True)
    return out


def search_faceted(query, page_size, group_ids, selected):
    """Server-side ACL trim + cascading facets in one shot. Returns (docs, facets).

    The security trim is enforced by VAIS via the indexed `acl_groups` field
    (`acl_groups: ANY(<user groups>)`), so this scales to any corpus size — no app-side
    sampling. Cascade is exclude-own-field: a field's own selection is dropped when
    computing ITS facet, so siblings stay visible (true multi-select), while every other
    facet reflects the full current selection.

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

    # recompute each actively-filtered field's facet WITHOUT its own filter (parallel;
    # usually 0-2 fields). Base call already cascaded the rest.
    active = [f for f in selected if f in FACET_FIELDS]
    if active:
        def own_excluded(field):
            f = build_filter({**acl, **{k: v for k, v in selected.items() if k != field}})
            return field, _facets(_search(query, 1, filter_=f, facet_fields=[field])).get(field, [])
        with ThreadPoolExecutor(max_workers=min(4, len(active))) as ex:
            for field, vals in ex.map(own_excluded, active):
                if vals:
                    facets[field] = vals
                else:
                    facets.pop(field, None)
    return docs, facets


def write_user_event(event_type, query=None, document_ids=None, user_id=None):
    """Report an interaction event for VAIS autotuning (learn-to-rank).

    event_type: "search" | "view-item" (we map a result click to view-item).
    Best-effort — never raises into the request path.
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
    try:
        _sess().post(url, json=event, timeout=15)
    except Exception:
        pass


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
