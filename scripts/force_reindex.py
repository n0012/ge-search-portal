#!/usr/bin/env python3
"""Force VAIS to re-index existing documents so schema/field-config changes take effect.

`documents.patch` updates a field's VALUE but does not always re-run the field-level
indexing that makes a NEWLY-declared filterable field (e.g. acl_groups) usable in a
`filter` expression — only `documents:import` reliably does. This lists every document
and re-imports it in place (reconciliationMode=INCREMENTAL) with its CURRENT structData +
content, which re-indexes it under the latest schema.

One-off remediation for an existing data store after fix_schema.py + sync_metadata.py.
Fresh ingests don't need it (02_make_metadata.py now bakes acl_groups in before import).

Env: PROJECT_ID, LOCATION, DATA_STORE_ID (env or ../.env).
"""
import os
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def cfg(k, d=None):
    if k in os.environ:
        return os.environ[k]
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line.startswith(f"{k}=") and not line.startswith("#"):
                return line.split("=", 1)[1].strip()
    return d


PROJECT = cfg("PROJECT_ID")
LOCATION = cfg("LOCATION", "global")
DS = cfg("DATA_STORE_ID", "ge-search-demo")
HOST = "discoveryengine.googleapis.com" if LOCATION == "global" else f"{LOCATION}-discoveryengine.googleapis.com"
BASE = (f"https://{HOST}/v1/projects/{PROJECT}/locations/{LOCATION}/collections/"
        f"default_collection/dataStores/{DS}/branches/default_branch")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
SESS = AuthorizedSession(_creds)
HDR = {"X-Goog-User-Project": PROJECT}


def list_docs():
    docs, token = [], ""
    while True:
        url = f"{BASE}/documents?pageSize=300" + (f"&pageToken={token}" if token else "")
        r = SESS.get(url, headers=HDR, timeout=60)
        r.raise_for_status()
        j = r.json()
        docs += j.get("documents", [])
        token = j.get("nextPageToken")
        if not token:
            return docs


def poll(op_name):
    url = f"https://{HOST}/v1/{op_name}"
    while True:
        j = SESS.get(url, headers=HDR, timeout=60).json()
        if j.get("done"):
            return j
        time.sleep(10)


def main():
    docs = list_docs()
    records = [{"id": d["id"], "structData": d.get("structData", {}), "content": d["content"]}
               for d in docs if d.get("content", {}).get("uri")]
    print(f"re-importing {len(records)}/{len(docs)} docs (INCREMENTAL) to re-index…")

    for i in range(0, len(records), 100):                 # inlineSource caps at 100/req
        chunk = records[i:i + 100]
        body = {"inlineSource": {"documents": chunk}, "reconciliationMode": "INCREMENTAL"}
        r = SESS.post(f"{BASE}/documents:import", headers=HDR, json=body, timeout=120)
        if r.status_code not in (200, 202):
            raise SystemExit(f"import failed [{r.status_code}]: {r.text[:300]}")
        res = poll(r.json()["name"])
        err = (res.get("error") or {}).get("message")
        print(f"  batch {i//100 + 1}: {'ok' if not err else 'ERROR ' + err}")

    print("done. Re-indexing of the new filterable field may take a few more minutes "
          "to become queryable.")


if __name__ == "__main__":
    main()
