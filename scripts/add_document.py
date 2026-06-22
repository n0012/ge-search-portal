#!/usr/bin/env python3
"""Add (or update) documents by writing catalog records into Firestore — the SINGLE
on-ramp to the index. You never call Vertex AI Search directly: reconcile.py (run on
demand, or by the scheduled Cloud Run job) sees the new `pending` record and stages +
imports it.

This is exactly what the upstream replicators do per change — replicate_catalog.py for a
source snapshot, or the DynamoDB->Firestore Lambda for a stream event. add_document.py is
the by-hand version of the same single write.

Minimal record (one JSON object):
  {"document_id": "amgen_8-k_2026-02-03",
   "groups": ["finance"],                       # ACL — required to be visible to anyone
   "source_url": "https://.../doc.htm",         # content pointer: source_url | gcs_uri | content_path
   "title": "...", "company": "amgen", "department": "finance", "doc_type": "8-K"}

Usage:
  python scripts/add_document.py --json '{"document_id":"x","groups":["finance"],"source_url":"..."}'
  python scripts/add_document.py records.jsonl          # one JSON object per line
  # then:  python scripts/reconcile.py
"""
import argparse
import json
import sys

import catalog


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", help="JSONL file of catalog records (one per line)")
    ap.add_argument("--json", help="a single catalog record as inline JSON")
    args = ap.parse_args()

    recs = []
    if args.json:
        recs.append(json.loads(args.json))
    if args.path:
        recs += [json.loads(ln) for ln in open(args.path) if ln.strip()]
    if not recs:
        sys.exit("provide a JSONL file path and/or --json")

    db = catalog.client()
    for r in recs:
        if not r.get("document_id"):
            sys.exit("every record needs a document_id")
        if not (r.get("source_url") or r.get("gcs_uri") or r.get("content_path")):
            sys.exit(f"{r['document_id']}: need a content pointer "
                     "(source_url | gcs_uri | content_path)")
        if not r.get("groups"):
            print(f"  warning: {r['document_id']} has no groups — it will be invisible to all users")
        print(f"  {r['document_id']}: {catalog.upsert(db, r)}")
    print(f"\nupserted {len(recs)} catalog record(s) into Firestore. "
          "Run scripts/reconcile.py (or wait for the scheduled job) to load them into VAIS.")


if __name__ == "__main__":
    main()
