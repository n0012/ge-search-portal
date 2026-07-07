#!/usr/bin/env python3
"""Stage the corpus to GCS and import it into the (already-created) VAIS data store.

Library + ADC based (google-cloud-storage + Discovery Engine REST with an ADC token)
so it runs unchanged inside the Cloud Run ingest Job *and* locally via gcloud ADC.
The data store itself is created by Terraform; this only uploads + imports (+ a
best-effort facet field-config patch).

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, GCS_BUCKET.
"""
import json
import os
import sys
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage

from ingestlog import ilog  # per-document ledger (no-op unless BQ_LOGGING=on)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORPUS = os.path.join(ROOT, "corpus")
METADATA = os.path.join(ROOT, "metadata.jsonl")

# Declared (indexable + facetable) BEFORE the import below — a field is only filterable/
# facetable for docs indexed AFTER it's declared, so this must precede documents:import.
# Keep in step with the time metadata 02_make_metadata.py derives (period/month/quarter).
FACET_FIELDS = ["company", "department", "research_source", "research_area",
                "doc_type", "report_kind", "year", "quarter", "period", "month",
                "venue", "publish_date"]


def cfg(key, default=None):
    if key in os.environ:
        return os.environ[key]
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith(f"{key}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return default


def main():
    project = cfg("PROJECT_ID")
    location = cfg("LOCATION", "global")
    ds = cfg("DATA_STORE_ID", "ge-search-demo")
    bucket_uri = cfg("GCS_BUCKET")
    for k, v in {"PROJECT_ID": project, "GCS_BUCKET": bucket_uri}.items():
        if not v or "CHANGEME" in v:
            sys.exit(f"missing config: {k}")
    bucket_name = bucket_uri.replace("gs://", "").rstrip("/")
    if not os.path.exists(METADATA):
        sys.exit("metadata.jsonl missing — run 02_make_metadata.py first")

    # Per-task manifest name so parallel Cloud Run Job tasks don't overwrite each
    # other; each task imports its own shard (import is INCREMENTAL).
    shard = os.environ.get("CLOUD_RUN_TASK_INDEX", "0")
    meta_blob = f"metadata-{shard}.jsonl"

    # manifest rows for this shard (id + descriptive source, for the ledger)
    rows = [json.loads(line) for line in open(METADATA) if line.strip()]

    def _src(sd):
        return sd.get("research_source") or sd.get("company") or sd.get("department") or "doc"

    # 1. upload corpus PDFs (skip existing) + this shard's manifest
    gcs = storage.Client(project=project)
    bucket = gcs.bucket(bucket_name)
    n = 0
    for dirpath, _, files in os.walk(CORPUS):
        for fn in files:
            if not fn.lower().endswith((".pdf", ".htm", ".html")):
                continue
            local = os.path.join(dirpath, fn)
            blob_path = os.path.relpath(local, ROOT)  # corpus/.../x.pdf
            blob = bucket.blob(blob_path)
            if not blob.exists():
                blob.upload_from_filename(local)
                n += 1
    bucket.blob(meta_blob).upload_from_filename(METADATA)
    print(f"staged {n} new PDFs + {meta_blob} to gs://{bucket_name}/")
    for row in rows:
        ilog("staged", _src(row.get("structData", {})), row["id"], "ok")

    # auth'd session for Discovery Engine REST
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    sess = AuthorizedSession(creds)
    host = "discoveryengine.googleapis.com" if location == "global" else f"{location}-discoveryengine.googleapis.com"
    base = (f"https://{host}/v1/projects/{project}/locations/{location}"
            f"/collections/default_collection/dataStores/{ds}")

    # 2. declare facet fields (indexable => filterable, dynamicFacetable, retrievable)
    #    in the schema BEFORE import — a field is only filter/facetable for docs indexed
    #    AFTER it is declared, so this must precede documents:import. The v1 Schema is a
    #    jsonSchema STRING (the fieldConfigs API shape is rejected here); patch the config
    #    keywords onto each field, preserving existing props. acl_groups (filter-only) is
    #    declared separately by fix_schema.py.
    schema_name = (f"projects/{project}/locations/{location}/collections/"
                   f"default_collection/dataStores/{ds}/schemas/default_schema")
    schema_url = f"https://{host}/v1/{schema_name}"
    facet_kw = {"indexable": True, "searchable": True,
                "dynamicFacetable": True, "retrievable": True}
    try:
        cur = sess.get(schema_url, timeout=60)
        cur.raise_for_status()
        js = json.loads(cur.json().get("jsonSchema") or "{}")
        js.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        js.setdefault("type", "object")
        props = js.setdefault("properties", {})
        changed = False
        for f in FACET_FIELDS:
            existing = props.get(f) or {}
            want = dict(existing, type=existing.get("type", "string"), **facet_kw)
            if existing != want:
                props[f] = want
                changed = True
        if changed:
            p = sess.patch(schema_url, json={"name": schema_name, "jsonSchema": json.dumps(js)},
                           timeout=60)
            print(f"declare facet fields: [{p.status_code}]")
        else:
            print("declare facet fields: already declared")
    except Exception as e:                                  # best-effort; never block import
        print(f"declare facet fields: skipped ({e})")

    # 3. import documents from the staged manifest (errors captured to GCS per doc)
    err_prefix = f"import-errors/{shard}"
    imp = f"{base}/branches/default_branch/documents:import"
    body = {"reconciliationMode": "INCREMENTAL",
            "gcsSource": {"inputUris": [f"gs://{bucket_name}/{meta_blob}"],
                          "dataSchema": "document"},
            "errorConfig": {"gcsPrefix": f"gs://{bucket_name}/{err_prefix}"}}
    r = sess.post(imp, json=body, timeout=120)
    if r.status_code != 200:
        sys.exit(f"import failed [{r.status_code}]: {r.text}")
    op = r.json().get("name", "")
    print(f"import started: {op}")

    # 4. poll the import LRO so we can ledger per-document import status
    done = False
    if op:
        for _ in range(30):  # up to ~5 min; import keeps indexing server-side after
            time.sleep(10)
            o = sess.get(f"https://{host}/v1/{op}", timeout=30).json()
            if o.get("done"):
                done = True
                break

    # best-effort: failed doc ids come from the import error file(s) in GCS
    failed = {}
    if done:
        ids = {row["id"] for row in rows}
        for blob in gcs.list_blobs(bucket_name, prefix=err_prefix):
            for line in blob.download_as_text().splitlines():
                for did in ids:
                    if did in line and did not in failed:
                        failed[did] = line[:500]
    for row in rows:
        did = row["id"]
        if did in failed:
            ilog("import", _src(row.get("structData", {})), did, "failed", error=failed[did])
        else:
            ilog("import", _src(row.get("structData", {})), did, "ok" if done else "submitted")
    print(f"import {'done' if done else 'submitted'}; {len(failed)} doc error(s)")


if __name__ == "__main__":
    main()
