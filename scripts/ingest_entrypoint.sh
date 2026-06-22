#!/usr/bin/env sh
# Entrypoint for the ge-search-ingest Cloud Run Job: fetch corpus -> manifest ->
# stage to GCS + import into VAIS -> seed Firestore ACLs -> declare + sync the
# server-side ACL field. Runs from the app image.
set -eu
cd /app

echo "ingest: 1/6 fetch corpus (limit ${INGEST_LIMIT:-30})"
python3 scripts/01_fetch_corpus.py all --limit "${INGEST_LIMIT:-30}"

echo "ingest: 2/6 build VAIS import manifest"
python3 scripts/02_make_metadata.py

echo "ingest: 3/6 stage to GCS + import"
python3 scripts/03_stage_import.py

echo "ingest: 4/6 seed Firestore ACLs"
python3 scripts/04_seed_acls.py

echo "ingest: 5/6 declare acl_groups in the VAIS schema (filterable)"
python3 scripts/fix_schema.py

echo "ingest: 6/6 sync company rollup + acl_groups into the index"
python3 scripts/sync_metadata.py

echo "ingest: done"
