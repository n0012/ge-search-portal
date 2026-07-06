"""Pure, dependency-free business logic (no GCP/SDK imports) — unit-testable.

These are the correctness-critical bits: the security-trim intersection, the facet
filter/match, result parsing, and facet tallying.
"""


def build_filter(facets):
    """{company:'amgen', year:['2023','2024']} -> 'company: ANY("amgen") AND year: ANY("2023", "2024")'.

    OR within a field (ANY), AND across fields. Empty/None values are dropped.
    """
    if not facets:
        return ""
    parts = []
    for field, value in facets.items():
        if value in (None, "", [], ()):
            continue
        vals = value if isinstance(value, (list, tuple)) else [value]
        quoted = ", ".join('"%s"' % str(v).replace('"', "") for v in vals)
        parts.append(f"{field}: ANY({quoted})")
    return " AND ".join(parts)


def parse_doc(result):
    """Map a Discovery Engine search result into our flat result shape."""
    d = result.get("document", {}) or {}
    sd = d.get("structData", {}) or {}
    dd = d.get("derivedStructData", {}) or {}
    snippet = next((s.get("snippet", "") for s in (dd.get("snippets") or [])
                    if s.get("snippet")), "")
    # Extractive segments are longer, coherent verbatim passages (not keyword snippets) — far
    # better answer-bearing context for the cross-encoder reranker and the grounding prompt.
    segs = dd.get("extractive_segments") or []
    segment = "\n\n".join(s.get("content", "") for s in segs if s.get("content"))
    return {
        "documentId": d.get("id"),
        "title": sd.get("title") or dd.get("title") or d.get("id"),
        "sourceUrl": sd.get("source_url") or dd.get("link"),
        "gcsUri": dd.get("link"),
        "snippet": snippet,
        "segment": segment,
        "company": sd.get("company"), "department": sd.get("department"),
        "doc_type": sd.get("doc_type"), "report_kind": sd.get("report_kind"),
        "research_source": sd.get("research_source"),
        "research_area": sd.get("research_area"), "venue": sd.get("venue"),
        "year": sd.get("year"), "publish_date": sd.get("publish_date"),
    }


def matches(doc, selected):
    """In-memory facet match: OR within a field, AND across fields."""
    for field, value in selected.items():
        vals = value if isinstance(value, (list, tuple)) else [value]
        if doc.get(field) not in vals:
            return False
    return True


def tally(docs, fields):
    """Count facet values across docs -> {field: [{value, count}, ...]} (sorted)."""
    counts = {}
    for d in docs:
        for f in fields:
            v = d.get(f)
            if v:
                counts.setdefault(f, {})
                counts[f][v] = counts[f].get(v, 0) + 1
    return {f: [{"value": v, "count": c} for v, c in sorted(vals.items())]
            for f, vals in counts.items()}


def build_prompt(query, docs):
    """Grounding prompt for the answer model (text sources + optional attached PDFs)."""
    if not docs:
        return ""
    sources = "\n\n".join(
        f"[{i + 1}] {d.get('title', '')}\n{d.get('segment') or d.get('snippet') or ''}"
        for i, d in enumerate(docs[:8]))
    return ("You are an enterprise search assistant. Using the numbered sources below (and any "
            "attached document pages — read their charts, tables and figures), write a clear, "
            "well-structured answer that synthesizes across the sources, with inline citations "
            "like [1][2]. Be substantive and specific (include figures/dates when present). "
            "Treat 'Google' and 'Alphabet' as the same company. If a specific detail isn't in "
            "the sources, omit it rather than refusing to answer.\n\n"
            f"Sources:\n{sources}\n\nQuestion: {query}\n\nAnswer:")


def build_doc_prompt(question, title, context_text=""):
    """Grounding prompt for single-document Q&A / summarize (one doc only)."""
    ctx = f"\n\nDocument text:\n{context_text[:120000]}" if context_text else ""
    return ('You are answering a question about ONE specific document titled '
            f'"{title}". Ground your answer ONLY in this document — its attached pages '
            "and/or the text below. Be concise and specific (cite figures, dates and names "
            "when present). If the document doesn't address the question, say so plainly "
            "rather than guessing."
            f"{ctx}\n\nQuestion: {question}\n\nAnswer:")


def pdf_uris(docs, max_docs):
    """GCS PDF uris to attach for multimodal reading — top-N docs, gs:// **.pdf** only,
    deduped. Non-PDF docs (e.g. EDGAR HTML filings) are excluded — Gemini can't read
    them as PDFs ('document has no pages')."""
    uris = []
    for d in docs[:max_docs]:
        u = d.get("gcsUri") or ""
        if u.startswith("gs://") and u.lower().endswith(".pdf") and u not in uris:
            uris.append(u)
    return uris


def authorized(results, doc_group_map, user_groups):
    """Security trim: keep a result iff its document_groups intersect the user's groups.

    doc_group_map: {document_id: set(group_id)}. Empty user_groups => no access.
    This is the leak-safety core — must never return a doc the user can't see.
    """
    if not user_groups:
        return []
    ug = set(user_groups)
    return [r for r in results
            if doc_group_map.get(r.get("documentId"), set()) & ug]
