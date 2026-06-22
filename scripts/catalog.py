"""Firestore `catalog` collection — the contract boundary between the (pluggable) source
replicator and the VAIS reconcile job. Also seeds/prunes the ACL graph
(documents / document_groups) for loaded/deleted docs, keeping it in lockstep.
"""
import re

from google.cloud import firestore

import _common as C
import catalog_model

COLLECTION = "catalog"


def _clean_id(raw):
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:63].strip("_") or "doc"


def read_all(db):
    out = []
    for snap in db.collection(COLLECTION).stream():
        r = snap.to_dict() or {}
        r["document_id"] = r.get("document_id") or snap.id
        out.append(r)
    return out


def upsert(db, record):
    """Replicator entry point: merge a source record into the catalog. Marks vais_state
    `pending` when new or content changed; leaves `loaded` untouched when unchanged; sets
    the tombstone for deletes. Returns the resulting vais_state."""
    doc_id = record["document_id"]
    ref = db.collection(COLLECTION).document(doc_id)
    cur = (ref.get().to_dict() or {})
    h = catalog_model.effective_hash(record)
    data = dict(record)
    data["content_hash"] = h
    data["updated_at"] = firestore.SERVER_TIMESTAMP
    if record.get("deleted"):
        data["deleted"] = True                      # reconcile will purge; keep prior state
        ref.set(data, merge=True)
        return "tombstoned"
    data["deleted"] = False
    unchanged = cur.get("vais_state") == "loaded" and cur.get("loaded_hash") == h
    data["vais_state"] = "loaded" if unchanged else "pending"
    ref.set(data, merge=True)
    return data["vais_state"]


def mark_loaded(db, doc_id, content_hash):
    db.collection(COLLECTION).document(doc_id).set(
        {"vais_state": "loaded", "loaded_hash": content_hash,
         "loaded_at": firestore.SERVER_TIMESTAMP, "last_error": firestore.DELETE_FIELD},
        merge=True)


def mark_failed(db, doc_id, error):
    db.collection(COLLECTION).document(doc_id).set(
        {"vais_state": "failed", "last_error": (error or "")[:500]}, merge=True)


def mark_deleted(db, doc_id):
    db.collection(COLLECTION).document(doc_id).set(
        {"vais_state": "deleted", "deleted": True}, merge=True)


def seed_graph(db, record):
    """Mirror a loaded doc's ACL into the runtime graph (documents + document_groups),
    matching 04_seed_acls.py so the query-time trimmer + VAIS acl_groups agree."""
    doc_id = record["document_id"]
    db.collection("documents").document(doc_id).set({
        "document_id": doc_id, "title": record.get("title", ""),
        "department": record.get("department", ""), "company": record.get("company", ""),
        "research_source": record.get("research_source", "")}, merge=True)
    for g in record.get("groups", []):
        db.collection("document_groups").document(_clean_id(f"{doc_id}__{g}")).set(
            {"document_id": doc_id, "group_id": g}, merge=True)


def prune_graph(db, doc_id):
    """Remove a doc from the ACL graph (documents + all its document_groups edges)."""
    db.collection("documents").document(doc_id).delete()
    for snap in (db.collection("document_groups")
                 .where(filter=firestore.FieldFilter("document_id", "==", doc_id)).stream()):
        snap.reference.delete()


def client():
    return C.firestore_client()
