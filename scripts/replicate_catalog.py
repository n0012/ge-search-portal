#!/usr/bin/env python3
"""Replicate the upstream source (demo / DynamoDB) into the Firestore `catalog` collection.

This is the *independent process* in the architecture — the GCP-side equivalent of a
DynamoDB-Streams -> Lambda -> Firestore bridge. It only writes the catalog; it does NOT
touch VAIS (that's reconcile.py). Because the catalog schema is the contract, an AWS Lambda
can replace this script entirely by writing the same documents.

Idempotent: catalog.upsert marks records `pending` only when new or content-changed, and
sets the tombstone for deletes; unchanged records stay `loaded`.

Env: CATALOG_SOURCE (demo|dynamo|firestore), PROJECT_ID, FIRESTORE_DATABASE,
     CATALOG_DELTA (demo only, optional), DYNAMO_* (dynamo only).
"""
import collections

import catalog
import catalog_source


def main():
    src = catalog_source.from_env()
    if isinstance(src, catalog_source.FirestoreCatalogSource):
        print("CATALOG_SOURCE=firestore: catalog is populated by an external replicator "
              "(e.g. the DynamoDB-Streams Lambda); nothing to replicate here.")
        return
    db = catalog.client()
    counts = collections.Counter()
    n = 0
    for r in src.records():
        counts[catalog.upsert(db, r)] += 1
        n += 1
    print(f"replicated {n} source records into catalog: {dict(counts)}")


if __name__ == "__main__":
    main()
