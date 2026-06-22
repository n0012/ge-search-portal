"""Pure catalog logic — the contract record shape + delta engine. No GCP imports, so the
delta is unit-testable and the same code runs for demo and DynamoDB sources.

A catalog record (one per source document, id == VAIS id == Dynamo partition key):
  identity/facets : document_id, title, company, department, research_source, year,
                    doc_type, source_url, ...        (-> VAIS structData)
  content pointer : gcs_uri (already staged) and/or source_url / content_path (to fetch)
  acl             : groups [..]                       (-> VAIS acl_groups + Firestore graph)
  change detect   : content_hash, deleted             (set by the replicator/source)
  sync state      : vais_state pending|loaded|failed|deleted, loaded_hash, loaded_at,
                    last_error                          (owned by reconcile.py)
"""
import hashlib
import json

# control/sync fields and content pointers are NOT part of the searchable structData
CONTROL = {"content_hash", "deleted", "vais_state", "loaded_hash", "loaded_at",
           "last_error", "updated_at"}
POINTER = {"gcs_uri", "content_path"}
NON_STRUCT = CONTROL | POINTER | {"document_id", "groups"}


def to_struct(record):
    """The VAIS structData for a record: facets + acl_groups (from groups). source_url is
    kept (the result card links to it); control/pointer fields are dropped."""
    sd = {k: v for k, v in record.items()
          if k not in NON_STRUCT and v not in (None, "", [], {})}
    if record.get("groups"):
        sd["acl_groups"] = sorted(record["groups"])
    return sd


def content_hash(record):
    """Deterministic hash of everything that, if changed, requires a VAIS re-import:
    the structData + the content pointer. Used when the source doesn't supply its own
    version/hash."""
    payload = {
        "struct": to_struct(record),
        "gcs_uri": record.get("gcs_uri") or "",
        "source_url": record.get("source_url") or "",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def effective_hash(record):
    """Source-provided content_hash wins (e.g. a Dynamo version attr); else we compute."""
    return record.get("content_hash") or content_hash(record)


def plan_delta(records):
    """The delta engine. Given catalog records, return (to_load, to_delete).

    load   : not deleted AND (never loaded OR content changed since last load)
    delete : tombstoned AND still present in VAIS (vais_state != deleted)
    Idempotent: an unchanged, loaded record falls into neither bucket. This unifies
    initial load (everything pending) and incremental (only the delta).
    """
    to_load, to_delete = [], []
    for r in records:
        if r.get("deleted"):
            if r.get("vais_state") != "deleted":
                to_delete.append(r)
            continue
        if r.get("vais_state") != "loaded" or r.get("loaded_hash") != effective_hash(r):
            to_load.append(r)
    return to_load, to_delete
