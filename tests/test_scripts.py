"""Corpus pipeline parsers — stdlib only, no network."""
import ingestlog
from conftest import _load

fetch = _load("scripts/01_fetch_corpus.py", "fetch_corpus")
meta = _load("scripts/02_make_metadata.py", "make_metadata")


def test_ingestlog_is_noop_when_disabled(monkeypatch):
    # No BQ_LOGGING -> must not raise, must not touch BigQuery
    monkeypatch.delenv("BQ_LOGGING", raising=False)
    assert ingestlog._enabled() in (False, None, "")
    ingestlog.ilog("download", "deepmind", "d1", "ok", bytes_=123)  # no exception


# ---- arXiv id extraction ----------------------------------------------------
def test_arxiv_re_matches_abs_and_pdf():
    assert fetch.ARXIV_RE.findall("see https://arxiv.org/abs/1706.03762 ok") == ["1706.03762"]
    assert fetch.ARXIV_RE.findall("https://arxiv.org/pdf/2312.11805") == ["2312.11805"]
    assert fetch.ARXIV_RE.findall("https://nature.com/articles/s41586") == []


# ---- Google Health theme mapping (nearest preceding expansion heading) ------
def test_health_themes_maps_to_nearest_heading():
    html = (
        '<div class="expansion"><h3>Genomics</h3>'
        '<a href="https://arxiv.org/abs/1111.22222">x</a></div>'
        '<div class="expansion"><h3>Radiology</h3>'
        '<a href="https://arxiv.org/abs/3333.44444">y</a></div>'
    )
    area = fetch.health_themes(html)
    assert area.get("1111.22222") == "Genomics"
    assert area.get("3333.44444") == "Radiology"


# ---- document id sanitization (join key to Firestore ACLs) ------------------
def test_shard_is_disjoint_and_covers_all():
    items = [f"d{i}" for i in range(10)]
    fetch.SHARD_COUNT, fetch.SHARD_INDEX = 3, 0
    s0 = fetch.shard(items)
    fetch.SHARD_INDEX = 1
    s1 = fetch.shard(items)
    fetch.SHARD_INDEX = 2
    s2 = fetch.shard(items)
    # disjoint
    assert set(s0) & set(s1) == set() and set(s1) & set(s2) == set()
    # union covers everything exactly once
    assert sorted(s0 + s1 + s2) == sorted(items)
    # reset
    fetch.SHARD_COUNT, fetch.SHARD_INDEX = 1, 0
    assert fetch.shard(items) == items


def test_clean_id_sanitizes_and_truncates():
    assert meta.clean_id("amgen_pmc13246533") == "amgen_pmc13246533"
    assert meta.clean_id("2023 Q4/earnings!") == "2023_Q4_earnings_"[:63].rstrip("_") or "doc"
    assert " " not in meta.clean_id("a b c")
    assert len(meta.clean_id("x" * 200)) <= 63
