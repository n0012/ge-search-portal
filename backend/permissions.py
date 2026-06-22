"""Firestore-backed security trimmer (the document / document_group / group_user graph).

A user may see a document iff some group G has an edge in BOTH `group_users`
(G<->user) and `document_groups` (doc<->G).
"""
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

import config
import core

_db = None


def _client():
    global _db
    if _db is None:
        _db = firestore.Client(project=config.PROJECT_ID, database=config.FIRESTORE_DATABASE)
    return _db


def groups_for_user(email):
    if not email:
        return set()
    q = _client().collection("group_users").where(filter=FieldFilter("user_id", "==", email))
    return {d.get("group_id") for d in q.stream()}


def _chunks(xs, n=10):                       # Firestore 'in' allows up to 10 (legacy) / 30
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def doc_groups(doc_ids):
    out = {}
    col = _client().collection("document_groups")
    for chunk in _chunks(list(doc_ids)):
        if not chunk:
            continue
        for d in col.where(filter=FieldFilter("document_id", "in", chunk)).stream():
            out.setdefault(d.get("document_id"), set()).add(d.get("group_id"))
    return out


def trim(results, user_groups):
    """Keep only results whose document_groups intersect the user's groups."""
    if not user_groups:
        return []
    dg = doc_groups([r["documentId"] for r in results if r.get("documentId")])
    return core.authorized(results, dg, user_groups)


def personas():
    out = []
    for snap in _client().collection("users").stream():
        d = snap.to_dict() or {}  # DocumentSnapshot.get() takes no default — use a dict
        out.append({"email": d.get("user_id"), "display_name": d.get("display_name"),
                    "title": d.get("title"), "groups": d.get("groups", [])})
    return out
