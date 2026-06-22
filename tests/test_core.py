"""Pure business logic — the security trim, facet filter/match, parsing. No GCP."""
import core


# ---- security trim (the leak-safety core) -----------------------------------
def _docs(*ids):
    return [{"documentId": i} for i in ids]


def test_authorized_keeps_only_intersecting_docs():
    results = _docs("a", "b", "c")
    dg = {"a": {"finance"}, "b": {"research"}, "c": {"finance", "research"}}
    out = core.authorized(results, dg, {"finance"})
    assert [r["documentId"] for r in out] == ["a", "c"]


def test_authorized_empty_user_groups_sees_nothing():
    assert core.authorized(_docs("a", "b"), {"a": {"finance"}}, set()) == []


def test_authorized_doc_with_no_groups_is_hidden():
    # a doc absent from the group map must never leak
    assert core.authorized(_docs("x"), {}, {"finance"}) == []


def test_authorized_research_user_cannot_see_finance_docs():
    dg = {"earnings": {"finance"}, "paper": {"research"}}
    out = core.authorized(_docs("earnings", "paper"), dg, {"research"})
    assert [r["documentId"] for r in out] == ["paper"]


# ---- build_filter -----------------------------------------------------------
def test_build_filter_single_and_multi():
    assert core.build_filter({"company": "amgen"}) == 'company: ANY("amgen")'
    f = core.build_filter({"company": "amgen", "year": ["2023", "2024"]})
    assert f == 'company: ANY("amgen") AND year: ANY("2023", "2024")'


def test_build_filter_drops_empty_and_handles_none():
    assert core.build_filter({}) == ""
    assert core.build_filter({"company": "", "year": []}) == ""


def test_build_filter_composes_acl_and_facets():
    # the security-critical compose used by discovery.search_faceted: ACL group filter
    # AND-ed with the user's selected facets (acl_groups gates what VAIS may return).
    f = core.build_filter({"acl_groups": ["research"], "company": ["alphabet"]})
    assert f == 'acl_groups: ANY("research") AND company: ANY("alphabet")'
    # multiple groups -> OR within the ACL field
    assert core.build_filter({"acl_groups": ["finance", "research"]}) == \
        'acl_groups: ANY("finance", "research")'


# ---- facet match ------------------------------------------------------------
def test_matches_or_within_and_across_fields():
    doc = {"company": "amgen", "year": "2024"}
    assert core.matches(doc, {"company": ["amgen", "alphabet"]})
    assert core.matches(doc, {"company": "amgen", "year": "2024"})
    assert not core.matches(doc, {"company": "alphabet"})
    assert not core.matches(doc, {"company": "amgen", "year": "2023"})


def test_matches_missing_field_fails():
    assert not core.matches({"company": "amgen"}, {"doc_type": "earnings_release"})


# ---- tally ------------------------------------------------------------------
def test_tally_counts_present_fields_only():
    docs = [{"company": "amgen"}, {"company": "amgen"}, {"company": "alphabet"}, {}]
    out = core.tally(docs, ["company", "year"])
    assert out["company"] == [{"value": "alphabet", "count": 1},
                              {"value": "amgen", "count": 2}]
    assert "year" not in out


# ---- parse_doc --------------------------------------------------------------
def test_parse_doc_pulls_struct_and_derived():
    result = {"document": {
        "id": "amgen_pmc1",
        "structData": {"title": "T", "company": "amgen", "source_url": "https://x/p"},
        "derivedStructData": {"link": "gs://b/corpus/x.pdf",
                              "snippets": [{"snippet": ""}, {"snippet": "hit"}]},
    }}
    d = core.parse_doc(result)
    assert d["documentId"] == "amgen_pmc1"
    assert d["title"] == "T"
    assert d["company"] == "amgen"
    assert d["sourceUrl"] == "https://x/p"
    assert d["gcsUri"] == "gs://b/corpus/x.pdf"
    assert d["snippet"] == "hit"


def test_parse_doc_title_falls_back_to_id():
    assert core.parse_doc({"document": {"id": "z"}})["title"] == "z"


# ---- multimodal answer helpers ----------------------------------------------
def test_build_prompt_includes_sources_and_question():
    p = core.build_prompt("what is X?", [{"title": "Doc A", "snippet": "hello"}])
    assert "Doc A" in p and "what is X?" in p and "[1]" in p


def test_pdf_uris_filters_to_gcs_and_caps():
    docs = [
        {"gcsUri": "gs://b/a.pdf"},
        {"gcsUri": "https://x/b.pdf"},   # not gs:// -> dropped
        {"gcsUri": "gs://b/c.pdf"},
        {"gcsUri": "gs://b/d.pdf"},
    ]
    assert core.pdf_uris(docs, 2) == ["gs://b/a.pdf"]  # 2nd is non-gs, capped at 2 scanned
    assert core.pdf_uris(docs, 4) == ["gs://b/a.pdf", "gs://b/c.pdf", "gs://b/d.pdf"]


def test_build_doc_prompt_scopes_to_one_doc():
    p = core.build_doc_prompt("revenue?", "Amgen 10-K", "net sales were $X")
    assert "ONE specific document" in p and "Amgen 10-K" in p
    assert "revenue?" in p and "net sales were $X" in p


def test_build_doc_prompt_without_context_omits_text_block():
    p = core.build_doc_prompt("summarize", "Doc")
    assert "Document text:" not in p and "summarize" in p


def test_pdf_uris_excludes_non_pdf():
    # EDGAR HTML filings must NOT be attached as PDFs (Gemini: "document has no pages")
    docs = [{"gcsUri": "gs://b/amgen_10-k.htm"}, {"gcsUri": "gs://b/paper.pdf"}]
    assert core.pdf_uris(docs, 4) == ["gs://b/paper.pdf"]
