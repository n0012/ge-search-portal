"""Search request shape + user-event wiring. Needs google-auth (skipped if absent)."""
import json

import pytest

pytest.importorskip("google.auth")
import discovery  # noqa: E402


class _Resp:
    def __init__(self, payload, status_code=200):
        self._p = payload
        self.status_code = status_code

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
    assert body["boostSpec"]["conditionBoostSpecs"][0]["condition"] == 'year: ANY("2025", "2026")'
    assert "summarySpec" not in body["contentSearchSpec"]   # retrieve = no summary
    assert docs[0]["documentId"] == "d1" and docs[0]["company"] == "amgen"


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
    # a just-declared filterable field still propagating should be retried, not surfaced
    s = _FlakySession(2)
    monkeypatch.setattr(discovery, "_session", s)
    monkeypatch.setattr(discovery.config, "BOOST_RECENT_YEARS", "")
    monkeypatch.setattr(discovery.time, "sleep", lambda *_: None)  # skip backoff
    docs, _ = discovery.retrieve("q", 5)
    assert s.calls == 3 and docs == []


def test_write_user_event_posts_search_event(fake):
    discovery.write_user_event("search", query="q", document_ids=["d1"], user_id="u@x")
    call = fake.calls[0]
    assert call["url"].endswith("userEvents:write")
    assert call["body"]["eventType"] == "search"
    assert call["body"]["searchInfo"]["searchQuery"] == "q"
    assert call["body"]["documents"] == [{"id": "d1"}]
