#!/usr/bin/env python3
"""Bootstrap the Firestore `catalog` from the CURRENT VAIS + Firestore state, marking every
existing doc `loaded`, so the catalog-driven pipeline starts in-sync. Demo/dev helper —
stands in for an initial DynamoDB snapshot. Idempotent (deterministic ids, merge).

After this, replicate_catalog.py + reconcile.py only act on real deltas.

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, FIRESTORE_DATABASE.
"""
import collections

from google.cloud import firestore

import _common as C
import catalog
import catalog_model


def main():
    sess = C.de_session()
    docs, tok = [], ""
    while True:
        url = f"https://{C.DE_HOST}/v1/{C.BRANCH}/documents?pageSize=300" + (
            f"&pageToken={tok}" if tok else "")
        j = sess.get(url, headers=C.HDR, timeout=60).json()
        docs += j.get("documents", [])
        tok = j.get("nextPageToken")
        if not tok:
            break

    db = catalog.client()
    groups = collections.defaultdict(list)
    for s in db.collection("document_groups").stream():
        r = s.to_dict() or {}
        if r.get("document_id") and r.get("group_id"):
            groups[r["document_id"]].append(r["group_id"])

    batch, n = db.batch(), 0
    for d in docs:
        sd = dict(d.get("structData", {}) or {})
        sd.pop("acl_groups", None)                         # ACL comes from groups, not struct
        rec = {"document_id": d["id"],
               "gcs_uri": (d.get("content") or {}).get("uri", ""),
               "groups": sorted(groups.get(d["id"], [])),
               **{k: v for k, v in sd.items() if v not in (None, "", [])}}
        h = catalog_model.content_hash(rec)
        batch.set(db.collection(catalog.COLLECTION).document(d["id"]),
                  {**rec, "content_hash": h, "loaded_hash": h, "vais_state": "loaded",
                   "deleted": False, "loaded_at": firestore.SERVER_TIMESTAMP}, merge=True)
        n += 1
        if n % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    print(f"bootstrapped catalog with {n} docs (all vais_state=loaded)")


if __name__ == "__main__":
    main()
