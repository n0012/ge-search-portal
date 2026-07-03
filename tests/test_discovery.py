"""Search request shape + user-event wiring. Needs google-auth (skipped if absent)."""
import json

import pytest

pytest.importorskip("google.auth")
import discovery  # noqa: E402


class _Resp:
    def __init__(self, payload, status_code=200, text=None):
        self._p = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class _FakeSession:
    """Captures POSTed bodies and returns a canned search response."""
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None):  # noqa: A002
        self.calls.append({"url": url, "body": json})
        return _Resp({"results": [
            {"document": {"id": "d1", "structData": {"title": "T", "company": "amgen"}}}
        ]})


@pytest.fixture
def fake(monkeypatch):
    s = _FakeSession()
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "BOOST_RECENT_YEARS", "2025,2026")
    return s


def test_retrieve_sets_quality_knobs_and_boost(fake):
    docs, facets = discovery.retrieve("cell therapy", 10)
    body = fake.calls[0]["body"]
    assert body["queryExpansionSpec"] == {"condition": "AUTO"}
    assert body["spellCorrectionSpec"] == {"mode": "AUTO"}
    # the `fake` fixture forces BOOST_RECENT_YEARS on, so the boost is emitted when set
    assert body["boostSpec"]["conditionBoostSpecs"][0]["condition"] == 'year: ANY("2025", "2026")'
    assert "summarySpec" not in body["contentSearchSpec"]   # retrieve = no summary
    assert docs[0]["documentId"] == "d1" and docs[0]["company"] == "amgen"


def test_retrieve_omits_boost_by_default(monkeypatch):
    # default BOOST_RECENT_YEARS="" -> no boostSpec, so the engine's native ranking stands
    s = _FakeSession()
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "BOOST_RECENT_YEARS", "")
    discovery.retrieve("cell therapy", 10)
    assert "boostSpec" not in s.calls[0]["body"]


def test_retrieve_passes_filter_and_facets(fake):
    discovery.retrieve("q", 5, filter_='company: ANY("amgen")', with_facets=True)
    body = fake.calls[0]["body"]
    assert body["filter"] == 'company: ANY("amgen")'
    assert any(fs["facetKey"]["key"] == "company" for fs in body["facetSpecs"])


def test_answer_with_filter_enables_summary_and_id_filter(fake):
    summary, docs = discovery.answer_with_filter("q", ["a", "b"])
    body = fake.calls[0]["body"]
    assert body["contentSearchSpec"]["summarySpec"]["includeCitations"] is True
    assert body["filter"] == 'id: ANY("a", "b")'


def test_answer_with_filter_empty_ids_noops(fake):
    summary, docs = discovery.answer_with_filter("q", [])
    assert summary == "" and docs == [] and fake.calls == []


def test_search_requests_extractive_segments_when_enabled(fake, monkeypatch):
    monkeypatch.setattr(discovery.config, "RERANK_EXTRACTIVE", True)
    discovery.retrieve("q", 5)
    spec = fake.calls[0]["body"]["contentSearchSpec"]
    assert spec["extractiveContentSpec"]["maxExtractiveSegmentCount"] == 2
    assert spec["extractiveContentSpec"]["returnExtractiveSegmentScore"] is True


def test_search_omits_extractive_when_disabled(fake, monkeypatch):
    monkeypatch.setattr(discovery.config, "RERANK_EXTRACTIVE", False)
    discovery.retrieve("q", 5)
    assert "extractiveContentSpec" not in fake.calls[0]["body"]["contentSearchSpec"]


class _AssistSession:
    """Returns a canned streamAssist payload (JSON array of events) + captures the body."""
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None, headers=None):  # noqa: A002
        self.calls.append({"url": url, "body": json})
        events = [{"answer": {"replies": [{"groundedContent": {
            "content": {"role": "model", "text": "Grounded answer [1]."},
            "textGroundingMetadata": {"references": [{
                "content": "cited chunk text",
                "documentMetadata": {
                    "document": "projects/p/.../documents/d1",
                    "uri": "https://x/d1.pdf", "title": "Doc One"},
            }]},
        }}]}}]
        return _Resp(events)


def test_assist_sets_streamassist_url_filter_and_maps_refs(monkeypatch):
    s = _AssistSession()
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "ASSISTANT_PATH",
                        "projects/p/locations/global/collections/default_collection/"
                        "engines/ge-search-app/assistants/default_assistant")
    text, docs, session = discovery.assist("q", ["a", "b"], 'acl_groups: ANY("finance")')
    body = s.calls[0]["body"]
    assert s.calls[0]["url"].endswith(":streamAssist")
    assert "engines/ge-search-app/assistants/default_assistant" in s.calls[0]["url"]
    assert body["query"]["text"] == "q"
    # the ACL predicate is the filter — doc ids are NOT sent (id isn't filterable on a
    # GE engine; the assistant's search tool fails to ground on it)
    assert body["toolsSpec"]["vertexAiSearchSpec"]["filter"] == 'acl_groups: ANY("finance")'
    assert "id: ANY" not in body["toolsSpec"]["vertexAiSearchSpec"]["filter"]
    assert "session" not in body  # no session passed -> fresh conversation
    assert text == "Grounded answer [1]."
    assert docs == [{"documentId": "d1", "title": "Doc One",
                     "sourceUrl": "https://x/d1.pdf", "snippet": "cited chunk text"}]
    assert len(s.calls) == 1  # grounded on first try -> no retry


def test_assist_threads_session(monkeypatch):
    s = _AssistSession()
    monkeypatch.setattr(discovery, "_session", s)
    discovery.assist("q", ["a"], 'acl_groups: ANY("finance")', session="sessions/S1")
    assert s.calls[0]["body"]["session"] == "sessions/S1"


def test_assist_empty_ids_noops(monkeypatch):
    s = _AssistSession()
    monkeypatch.setattr(discovery, "_session", s)
    text, docs, session = discovery.assist("q", [], 'acl_groups: ANY("finance")')
    assert text == "" and docs == [] and session is None and s.calls == []


def test_assist_no_filter_fails_closed(monkeypatch):
    # without an ACL predicate the assistant would search the WHOLE store — never call
    s = _AssistSession()
    monkeypatch.setattr(discovery, "_session", s)
    text, docs, session = discovery.assist("q", ["a"])
    assert text == "" and docs == [] and session is None and s.calls == []


def test_assist_retries_then_suppresses_ungrounded(monkeypatch):
    # zero grounding refs = the assistant's search tool flaked and emitted misleading
    # boilerplate — retry once, and if still ungrounded return EMPTY text (not the
    # boilerplate) so the UI shows an honest "no answer".
    class _NoRefs:
        calls = 0
        def post(self, url, json=None, timeout=None, headers=None):  # noqa: A002
            _NoRefs.calls += 1
            return _Resp([{"answer": {"replies": [{"groundedContent": {
                "content": {"role": "model", "text": "I can't reach the repository; upload a file."}}}]}}])
    monkeypatch.setattr(discovery, "_session", _NoRefs())
    text, docs, _ = discovery.assist("q", ["a"], 'acl_groups: ANY("finance")')
    assert text == "" and docs == [] and _NoRefs.calls == 2  # one retry, then suppressed


def test_assist_parses_sse_data_lines(monkeypatch):
    # tolerate SSE 'data:' framing as well as a JSON array (include a grounding ref so it
    # counts as grounded and the text isn't suppressed)
    sse = ('data: {"answer":{"replies":[{"groundedContent":'
           '{"content":{"role":"model","text":"hello"},'
           '"textGroundingMetadata":{"references":[{"content":"c",'
           '"documentMetadata":{"document":"x/d1","title":"D1","uri":"u"}}]}}}]}}\n')

    class _SSE:
        calls = []

        def post(self, url, json=None, timeout=None, headers=None):  # noqa: A002
            _SSE.calls.append({"url": url, "body": json})
            return _Resp(None, text=sse)

    monkeypatch.setattr(discovery, "_session", _SSE())
    text, docs, session = discovery.assist("q", ["a"], 'acl_groups: ANY("finance")')
    assert text == "hello" and len(docs) == 1


class _FlakySession:
    """Fails the first N posts with the propagation 400, then succeeds."""
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    def post(self, url, json=None, timeout=None):  # noqa: A002
        self.calls += 1
        if self.calls <= self.fail_times:
            return _Resp({"error": {"message": 'Unsupported field "acl_groups" on ":" operator'}},
                         status_code=400)
        return _Resp({"results": []}, status_code=200)


def test_search_retries_transient_unsupported_field(monkeypatch):
    # a just-declared filterable field still propagating should be hedged/retried, not
    # surfaced. FlakySession fails the first 2 draws -> wave 1 (2 attempts) all fail,
    # wave 2 succeeds on its first completion; up to 5 total draws may have been fired.
    s = _FlakySession(2)
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "BOOST_RECENT_YEARS", "")
    monkeypatch.setattr(discovery.time, "sleep", lambda *_: None)  # skip redraw pause
    docs, _ = discovery.retrieve("q", 5)
    # instant fake responses -> failed draws trigger immediate redraws, no hedging:
    # exactly 3 draws (2 transient failures + 1 success)
    assert s.calls == 3 and docs == []


class _RankSession:
    """Captures the ranking request and returns a reversed order."""
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, timeout=None, headers=None):  # noqa: A002
        self.calls.append({"url": url, "body": json})
        n = len(json["records"])
        return _Resp({"records": [{"id": str(i)} for i in reversed(range(n))]})


def test_rerank_prefers_segment_over_snippet(monkeypatch):
    s = _RankSession()
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "RERANK", True)
    docs = [{"title": "A", "snippet": "snip a", "segment": "rich a"},
            {"title": "B", "snippet": "snip b"}]  # no segment -> falls back to snippet
    discovery.rerank("q", docs)
    records = s.calls[0]["body"]["records"]
    assert records[0]["content"] == "rich a"
    assert records[1]["content"] == "snip b"


def test_write_user_event_posts_search_event(fake):
    t = discovery.write_user_event("search", query="q", document_ids=["d1"], user_id="u@x")
    t.join(timeout=5)  # fire-and-forget in prod; deterministic in tests
    call = fake.calls[0]
    assert call["url"].endswith("userEvents:write")
    assert call["body"]["eventType"] == "search"
    assert call["body"]["searchInfo"]["searchQuery"] == "q"
    assert call["body"]["documents"] == [{"id": "d1"}]


def test_search_faceted_no_cascade_single_call(fake, monkeypatch):
    # cascade=False must return after ONE engine call even with active filters —
    # /api/search's fast path; /api/facets patches the active fields separately.
    monkeypatch.setattr(discovery.config, "RERANK", False)
    docs, facets = discovery.search_faceted("q", 5, ["finance"], {"year": ["2024"]},
                                            cascade=False)
    assert len(fake.calls) == 1
    assert 'acl_groups: ANY("finance")' in fake.calls[0]["body"]["filter"]
    assert 'year: ANY("2024")' in fake.calls[0]["body"]["filter"]


def test_cascade_facets_excludes_own_filter(fake):
    # each ACTIVE field is recomputed WITHOUT its own filter (siblings stay pickable),
    # while every other selection + the ACL predicate stay applied
    discovery.cascade_facets("q", ["finance"], {"year": ["2024"], "doc_type": ["10-K"]})
    assert len(fake.calls) == 2
    by_field = {c["body"]["facetSpecs"][0]["facetKey"]["key"]: c["body"]["filter"]
                for c in fake.calls}
    assert "year:" not in by_field["year"] and 'doc_type: ANY("10-K")' in by_field["year"]
    assert "doc_type:" not in by_field["doc_type"] and 'year: ANY("2024")' in by_field["doc_type"]
    for f in by_field.values():
        assert 'acl_groups: ANY("finance")' in f


def test_cascade_facets_noop_without_active_or_groups(fake):
    assert discovery.cascade_facets("q", ["finance"], {}) == {}
    assert discovery.cascade_facets("q", [], {"year": ["2024"]}) == {}
    assert fake.calls == []


class _EmptyThenResults:
    """Returns 200-but-empty for the first N calls (the flap's spurious-empty variant),
    then a real result — mirrors a healthy slice behind a flapping replica."""
    def __init__(self, empty_times):
        self.empty_times = empty_times
        self.calls = 0

    def post(self, url, json=None, timeout=None, headers=None):  # noqa: A002
        self.calls += 1
        if self.calls <= self.empty_times:
            return _Resp({"results": []}, status_code=200)
        return _Resp({"results": [{"document": {"id": "d1", "structData": {"title": "T"}}}]},
                     status_code=200)


def test_search_retry_empty_redraws_past_spurious_empty(monkeypatch):
    # base retrieval hedges past 200-but-empty flap responses to a good draw
    s = _EmptyThenResults(2)
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "RERANK", False)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_: None)
    docs, _ = discovery.search_faceted("q", 5, ["finance"], {})
    assert len(docs) == 1 and s.calls >= 3


def test_search_retry_empty_returns_when_genuinely_empty(monkeypatch):
    # a truly empty slice (every draw empty) returns [] after exhausting draws, no raise
    s = _EmptyThenResults(999)
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "RERANK", False)
    monkeypatch.setattr(discovery.time, "sleep", lambda *_: None)
    docs, facets = discovery.search_faceted("q", 5, ["finance"], {})
    assert docs == []


def test_search_faceted_empty_groups_never_queries_engine(monkeypatch):
    # FAIL-CLOSED at the retrieval layer: a user with no groups must get nothing AND
    # the engine must never be queried (so there's no path that could return unfiltered).
    s = _FakeSession()
    monkeypatch.setattr(discovery, "_session", s)
    docs, facets = discovery.search_faceted("q", 5, [], {})
    assert docs == [] and facets == {} and s.calls == []


def test_search_faceted_filter_always_carries_acl(monkeypatch):
    # every engine query for a grouped user must be scoped by acl_groups (never unfiltered)
    s = _FakeSession()
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "RERANK", False)
    discovery.search_faceted("q", 5, ["finance"], {"year": ["2024"]})
    assert s.calls, "expected an engine query"
    for c in s.calls:
        assert 'acl_groups: ANY("finance")' in (c["body"].get("filter") or ""), \
            "an engine query went out without the acl_groups predicate"
