"""permissions.trim integration: fetches doc_groups then delegates to core.authorized.
Needs google-cloud-firestore importable (skipped otherwise); no live Firestore."""
import pytest

pytest.importorskip("google.cloud.firestore")
import permissions  # noqa: E402


def test_trim_uses_doc_groups_and_intersects(monkeypatch):
    results = [{"documentId": "a"}, {"documentId": "b"}, {"documentId": "c"}]
    monkeypatch.setattr(permissions, "doc_groups",
                        lambda ids: {"a": {"finance"}, "b": {"research"}, "c": {"finance"}})
    out = permissions.trim(results, {"finance"})
    assert [r["documentId"] for r in out] == ["a", "c"]


def test_trim_empty_groups_returns_nothing(monkeypatch):
    # must not even need a lookup; no access => nothing
    out = permissions.trim([{"documentId": "a"}], set())
    assert out == []
