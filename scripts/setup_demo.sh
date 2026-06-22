#!/usr/bin/env bash
# One-shot demo data pipeline: fetch corpus -> build manifest -> stage+import -> seed ACLs.
# Reads config from ../.env (PROJECT_ID, LOCATION, DATA_STORE_ID, GCS_BUCKET).
set -euo pipefail
cd "$(dirname "$0")/.."

LIMIT="${LIMIT:-30}"

echo "==> 1/4 fetch corpus (limit ${LIMIT} per sub-source)"
python3 scripts/01_fetch_corpus.py all --limit "${LIMIT}"

echo "==> 2/4 build VAIS import manifest"
python3 scripts/02_make_metadata.py

echo "==> 3/4 stage to GCS + create data store + import"
python3 scripts/03_stage_import.py

echo "==> 4/4 seed Firestore RBAC graph"
PYBIN=python3
if ! python3 -c "import yaml, google.cloud.firestore" 2>/dev/null; then
  echo "    preparing seed venv (public PyPI)…"
  python3 -m venv .seedvenv
  .seedvenv/bin/pip install --quiet --index-url https://pypi.org/simple pyyaml google-cloud-firestore
  PYBIN=.seedvenv/bin/python
fi
"${PYBIN}" scripts/04_seed_acls.py

echo "Done."
