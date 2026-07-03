"""FastAPI app: one process serves the API and the built React SPA.

Query-time flow:
  /api/search  1. resolve user (IAP header / demo persona)
               2. user -> groups (Firestore group_users)
               3. retrieve (over-fetch, no summary)
               4. ACL-trim to the user's groups (post-retrieval, app-side)
               5. tally facets + apply UI data filters  (NO LLM — fast/cheap)
  /api/answer  same retrieve+trim, THEN generate over ONLY the trimmed docs (ACL-safe).
               Opt-in: the UI calls it when the AI toggle is on or the user clicks
               "Generate AI answer", so search itself never pays LLM latency/cost.
  /api/doc/{id} ACL-checked redirect to a signed URL for the imported GCS copy.

Access control (RBAC) is enforced here and is NOT user-controllable. Facet filters
only NARROW within what the user may already see.
"""
import os
import time
import uuid

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import bqlog
import config
import discovery
import gcsdoc
import identity
import permissions

app = FastAPI(title="GE Search Portal")


def _user(request):
    u = identity.resolve(request.headers)
    # demo only: GET links (e.g. /api/doc) can't set X-Demo-User, so accept ?u=.
    # In prod (IDENTITY_SOURCE=iap) identity comes from the signed IAP header and this
    # query param is never consulted — so it can't be used to impersonate.
    if not u and config.IDENTITY_SOURCE == "demo":
        u = (request.query_params.get("u") or "").strip()
    return u or _default_user()


def _default_user():
    ps = permissions.personas()
    return ps[0]["email"] if ps else ""


@app.get("/healthz")
def healthz():
    return "ok"


@app.get("/api/me")
def me(request: Request):
    user = _user(request)
    return {"user": user, "groups": sorted(permissions.groups_for_user(user))}


@app.get("/api/config")
def get_config():
    return {
        "dataStoreId": config.DATA_STORE_ID,
        "identitySource": config.IDENTITY_SOURCE,
        "personas": permissions.personas(),       # drives the demo persona switcher
        "facetFields": discovery.FACET_FIELDS,     # which data filters the UI may offer
    }


def _parse_query(body):
    query = (body.get("query") or "").strip()
    page_size = int(body.get("pageSize") or config.PAGE_SIZE)
    selected = {f: v for f, v in (body.get("facets") or {}).items() if v}
    return query, page_size, selected


def _retrieve_trim(query, page_size, selected, user):
    """Shared retrieval + security trim for /api/search and the AI endpoints.

    Returns (groups, available_facets, allowed_docs). The ACL trim and faceting run
    SERVER-SIDE in VAIS via the indexed acl_groups field (scales to any corpus size;
    facets cascade exactly). As defense-in-depth we re-verify the returned page against
    the LIVE Firestore graph — so a doc whose acl_groups drifted out of date is still
    dropped (O(page_size), one Firestore 'in' query).

    Always cascade=False: the own-excluded recompute for active filter fields costs an
    extra engine query per field, the AI endpoints ignore facets entirely, and
    /api/search returns immediately while the UI patches chip counts via /api/facets.
    """
    groups = permissions.groups_for_user(user)
    allowed, available = discovery.search_faceted(query, page_size, sorted(groups),
                                                  selected, cascade=False)
    allowed = permissions.trim(allowed, groups)
    return groups, available, allowed


def _citations(docs):
    return [{"index": i + 1, "title": d["title"], "sourceUrl": d.get("sourceUrl"),
             "snippet": d.get("snippet")} for i, d in enumerate(docs)]


def _answer_meta(text, latency_ms):
    """Provenance shown next to AI answers. The GE assistant does not disclose the
    underlying model or meter tokens back (usage rides the per-seat subscription, not
    per-token billing) — the model is the engine default and tokensEstimated is an
    ESTIMATE from answer length (~4 chars/token), labeled as such in the UI. Never
    treat it as billing data."""
    return {
        "assistant": config.ASSISTANT_ID,
        "model": "engine default (not disclosed by the GE assistant API)",
        "tokensEstimated": (len(text) + 3) // 4 if text else 0,
        "latencyMs": latency_ms,
    }


@app.post("/api/search")
def search(request: Request, body: dict = Body(...)):
    """Fast path: retrieve + ACL-trim + facets. No LLM — the AI answer is opt-in
    (toggle / on-demand button) and served separately by /api/answer."""
    query, page_size, selected = _parse_query(body)
    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400)

    user = _user(request)
    groups, available, allowed = _retrieve_trim(query, page_size, selected, user)

    search_id = uuid.uuid4().hex  # correlation id: ties AI turns + feedback back to this search
    bqlog.log_search(user, query, groups, selected, allowed, search_id=search_id)
    # feed VAIS autotuning (learn-to-rank)
    discovery.write_user_event("search", query=query,
                               document_ids=[d["documentId"] for d in allowed], user_id=user)

    return {
        "user": user,
        "searchId": search_id,
        "results": allowed,
        "citations": _citations(allowed),
        "appliedFilters": selected,
        # filter values come from VAIS metadata, tallied over the ACL-TRIMMED set so
        # counts never reveal documents the user can't see (dynamic + leak-safe).
        "availableFilters": available,
    }


@app.post("/api/facets")
def facets(request: Request, body: dict = Body(...)):
    """Deferred facet cascade for the ACTIVELY-filtered fields (own-filter excluded, so
    sibling values stay pickable for multi-select). /api/search intentionally skips this
    recompute to render results immediately; the UI calls here right after and merges the
    patch into availableFilters (a field mapped to [] means: drop that chip group).
    Same ACL scope as search — counts never reveal documents the user can't see."""
    query, _, selected = _parse_query(body)
    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400)
    user = _user(request)
    groups = permissions.groups_for_user(user)
    # Fail-soft: the patch is cosmetic (chip counts) — a transient engine failure here
    # must never surface as a 500; the UI just keeps the own-filtered counts.
    try:
        patch = discovery.cascade_facets(query, sorted(groups), selected)
    except Exception as e:
        print("facets patch skipped: %s: %s" % (type(e).__name__, str(e)[:160]), flush=True)
        patch = {}
    return {"availableFilters": patch}


@app.post("/api/answer")
def answer(request: Request, body: dict = Body(...)):
    """On-demand AI answer over the SAME ACL-trimmed set as /api/search (re-derived
    server-side so the trim is authoritative — never trusts client-sent docs)."""
    query, page_size, selected = _parse_query(body)
    if not query:
        return JSONResponse({"error": "empty query"}, status_code=400)

    user = _user(request)
    groups, _, allowed = _retrieve_trim(query, page_size, selected, user)
    t0 = time.monotonic()

    # Grounded answer via the GE engine assistant (:streamAssist), scoped to the user's ACL
    # groups + active facet filters (the same enforced predicate as search — `id` is not
    # filterable on a GE engine, so the assistant grounds over the user's accessible slice
    # rather than the exact result page). Covered by the GE subscription and ACL-safe.
    # Surface its grounded references as citations when present, else fall back to the
    # trimmed result set.
    allowed_ids = [d["documentId"] for d in allowed]
    acl_filter = discovery.build_filter({"acl_groups": sorted(groups), **selected})
    # Search queries are usually keywords, which the assistant declines as
    # NON_ASSIST_SEEKING_QUERY_IGNORED — wrap them in an explicit summarization ask.
    summary_q = "Summarize, with specifics, what the accessible documents say about: %s" % query
    # A new result-set answer starts a fresh assistant conversation; the returned session
    # is handed to the client so its "Ask about these documents" follow-ups keep context.
    summary, refs, session = discovery.assist(summary_q, allowed_ids, acl_filter)
    citations = _citations(refs) if refs else _citations(allowed)
    latency_ms = int((time.monotonic() - t0) * 1000)

    bqlog.log_ai_turn(user, groups, "answer", search_id=(body.get("searchId") or ""),
                      query=query, model_requested="", model_used="ge-assist",
                      used_search=False, result_count=len(allowed),
                      latency_ms=latency_ms)
    return {"user": user, "summary": summary, "citations": citations,
            "sessionId": session, "meta": _answer_meta(summary, latency_ms)}


@app.post("/api/ask")
def ask(request: Request, body: dict = Body(...)):
    """Free-form Q&A over the CURRENT result set: same ACL-trimmed docs as /api/search
    (re-derived server-side), answering the user's follow-up `question` rather than
    summarizing. Powers the 'Ask about these documents' box on the answer card."""
    query, page_size, selected = _parse_query(body)
    question = (body.get("question") or "").strip()
    if not query or not question:
        return JSONResponse({"error": "query and question are required"}, status_code=400)

    user = _user(request)
    groups, _, allowed = _retrieve_trim(query, page_size, selected, user)
    t0 = time.monotonic()
    # Follow-up Q&A grounded via the GE engine assistant, scoped to the user's ACL groups
    # + active facet filters (same enforced predicate as the search trim).
    allowed_ids = [d["documentId"] for d in allowed]
    acl_filter = discovery.build_filter({"acl_groups": sorted(groups), **selected})
    # Continue the answer-card conversation when the client passes its sessionId, so
    # follow-ups like "show a trend from these docs" resolve against the prior turns.
    answer_text, refs, session = discovery.assist(question, allowed_ids, acl_filter,
                                                  session=(body.get("sessionId") or None))
    citations = _citations(refs) if refs else _citations(allowed)
    latency_ms = int((time.monotonic() - t0) * 1000)
    discovery.write_user_event("search", query=question,
                               document_ids=allowed_ids, user_id=user)
    bqlog.log_ai_turn(user, groups, "ask", search_id=(body.get("searchId") or ""),
                      query=query, question=question, model_requested="",
                      model_used="ge-assist", used_search=False,
                      result_count=len(allowed), latency_ms=latency_ms)
    return {"user": user, "answer": answer_text, "citations": citations,
            "sessionId": session, "meta": _answer_meta(answer_text, latency_ms)}


def _doc_page(title, message, status):
    """A small standalone HTML page — this endpoint is opened in a new browser tab,
    so a JSON body would render as broken text."""
    html = (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{title}</title><style>"
        "body{font:16px/1.5 system-ui,sans-serif;color:#1f2933;background:#f7f9fc;"
        "display:grid;place-items:center;min-height:100vh;margin:0}"
        ".card{max-width:30rem;padding:2rem;text-align:center;background:#fff;"
        "border:1px solid #e4e9f0;border-radius:1rem;box-shadow:0 1px 3px rgba(0,0,0,.06)}"
        "h1{font-size:1.15rem;margin:0 0 .5rem}p{color:#52606d;margin:0 0 1.25rem}"
        "a{color:#0b57d0;text-decoration:none;font-weight:600}a:hover{text-decoration:underline}"
        f"</style></head><body><div class=card><h1>{title}</h1><p>{message}</p>"
        "<a href='/'>← Back to search</a></div></body></html>"
    )
    return HTMLResponse(html, status_code=status)


@app.post("/api/doc/qa")
def doc_qa(request: Request, body: dict = Body(...)):
    """Ask a question (or 'summarize') about ONE specific document. ACL-checked, and
    grounded only on that document (multimodal PDF read, or its extracted text)."""
    document_id = (body.get("documentId") or "").strip()
    question = (body.get("question") or "").strip()
    if not document_id or not question:
        return JSONResponse({"error": "documentId and question are required"}, status_code=400)

    user = _user(request)
    groups = permissions.groups_for_user(user)
    if not (permissions.doc_groups([document_id]).get(document_id, set()) & groups):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    meta = discovery.get_document(document_id)
    if not meta:
        return JSONResponse({"error": "document not found"}, status_code=404)

    t0 = time.monotonic()
    # Grounded via the GE engine assistant within the user's ACL scope, steered to THIS
    # document by naming its title in the query (`id` is not filterable on a GE engine, so
    # exact single-doc pinning isn't possible server-side; the ACL predicate still bounds
    # what can ground). Covered by the GE subscription and ACL-safe.
    acl_filter = discovery.build_filter({"acl_groups": sorted(groups)})
    doc_q = 'Using the document titled "%s", answer: %s' % (meta.get("title") or document_id,
                                                            question)
    answer_text, _, session = discovery.assist(doc_q, [document_id], acl_filter,
                                               session=(body.get("sessionId") or None))
    latency_ms = int((time.monotonic() - t0) * 1000)

    discovery.write_user_event("view-item", query=question,
                               document_ids=[document_id], user_id=user)
    bqlog.log_ai_turn(user, groups, "doc_qa", search_id=(body.get("searchId") or ""),
                      question=question, document_id=document_id,
                      model_requested="", model_used="ge-assist",
                      used_search=False, result_count=1,
                      latency_ms=latency_ms)
    return {"documentId": document_id, "title": meta.get("title"), "answer": answer_text,
            "sessionId": session, "meta": _answer_meta(answer_text, latency_ms)}


@app.get("/api/doc/{document_id}")
def doc(document_id: str, request: Request):
    """Redirect to a short-lived signed URL for the document's imported GCS copy.

    ACL-checked: the user must share a group with the document, exactly as in search —
    so this can't be used to reach a file they couldn't retrieve. Returns a friendly
    page (not a GCS error) if access is denied or the imported file no longer exists."""
    user = _user(request)
    groups = permissions.groups_for_user(user)
    doc_grp = permissions.doc_groups([document_id]).get(document_id, set())
    if not (doc_grp & groups):
        return _doc_page("Access denied",
                         "You don't have access to this document under the current persona.",
                         403)
    uri = discovery.get_content_uri(document_id)
    url = gcsdoc.signed_url(uri) if uri else None
    if not url:
        # uri missing, or the imported object was deleted (stale VAIS reference)
        return _doc_page("Document unavailable",
                         "The imported copy of this document is no longer available. "
                         "Try the original web source from the search results.",
                         404)
    return RedirectResponse(url)


@app.post("/api/feedback")
def feedback(request: Request, body: dict = Body(...)):
    user = _user(request)
    doc_id = body.get("documentId", "")
    bqlog.log_feedback(user, body.get("query", ""), doc_id, body.get("title", ""),
                       body.get("vote", ""), search_id=body.get("searchId", ""))
    # an up-vote is a strong relevance signal → report as a view-item event
    if body.get("vote") == "up" and doc_id:
        discovery.write_user_event("view-item", query=body.get("query"),
                                   document_ids=[doc_id], user_id=user)
    return {"ok": True}


# Serve the built frontend (if present) from the same process.
_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="spa")
