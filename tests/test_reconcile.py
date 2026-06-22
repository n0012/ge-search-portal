"""Pure catalog delta logic — the heart of initial-load + incremental sync. No GCP."""
import catalog_model as m


def rec(**kw):
    base = {"document_id": "d", "title": "T", "groups": ["research"]}
    base.update(kw)
    return base


# ---- to_struct --------------------------------------------------------------
def test_to_struct_adds_acl_groups_and_drops_control_and_pointers():
    sd = m.to_struct(rec(company="alphabet", vais_state="loaded",
                         content_hash="x", gcs_uri="gs://b/x.pdf"))
    assert sd["acl_groups"] == ["research"] and sd["company"] == "alphabet"
    for k in ("vais_state", "content_hash", "gcs_uri", "groups", "document_id"):
        assert k not in sd


# ---- hashing ----------------------------------------------------------------
def test_content_hash_changes_with_metadata():
    a, b = m.content_hash(rec(title="A")), m.content_hash(rec(title="B"))
    assert a != b and len(a) == 16


def test_effective_hash_prefers_source_supplied_hash():
    assert m.effective_hash(rec(content_hash="v7")) == "v7"           # e.g. a Dynamo version
    assert m.effective_hash(rec()) == m.content_hash(rec())            # else computed


# ---- plan_delta -------------------------------------------------------------
def test_new_loads_unchanged_skips():
    h = m.content_hash(rec(document_id="u", title="U"))
    new = rec(document_id="n")                                         # never loaded
    loaded = rec(document_id="u", title="U", vais_state="loaded", loaded_hash=h)
    to_load, to_del = m.plan_delta([new, loaded])
    assert [r["document_id"] for r in to_load] == ["n"] and to_del == []


def test_modified_reloads():
    r = rec(document_id="m", title="new title", vais_state="loaded", loaded_hash="stale")
    to_load, _ = m.plan_delta([r])
    assert [r["document_id"] for r in to_load] == ["m"]               # hash drift -> reload


def test_tombstone_deletes_then_is_idempotent():
    _, to_del = m.plan_delta([rec(document_id="x", deleted=True, vais_state="loaded")])
    assert [r["document_id"] for r in to_del] == ["x"]
    tl, td = m.plan_delta([rec(document_id="x", deleted=True, vais_state="deleted")])
    assert tl == [] and td == []                                      # already purged -> noop


def test_empty_catalog_is_safe():
    assert m.plan_delta([]) == ([], [])
