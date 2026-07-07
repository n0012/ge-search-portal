#!/usr/bin/env python3
"""Re-index existing documents so a newly-declared schema field (a new filter/facet)
applies to them. A field is only filter/facetable for docs indexed AFTER it is declared,
so existing docs must be re-indexed once. Two modes — pick by cost:

  --metadata-only  (CHEAP, preferred for pure metadata/facet changes)
      documents.patch each doc's structData in place. Rewrites structData only — NO
      re-fetch, NO re-parse, NO re-embed of content. Caveats: the field becomes queryable
      only after VAIS's background index rebuild converges (can lag minutes–hours), and a
      patch does not always register a newly-FILTERABLE field. Verify it actually filters;
      if it never registers, fall back to the default mode.

  (default)        (HEAVY fallback — RE-EMBEDS content)
      re-import each doc WITH its content (inlineSource, reconciliationMode=INCREMENTAL).
      Reliably re-indexes under the latest schema, but re-processes + re-embeds content —
      a real cost at scale. Use only when --metadata-only doesn't register the field.

One-off remediation for an existing data store after fix_schema.py + sync_metadata.py.
Fresh ingests don't need it — 03_stage_import.py declares FACET_FIELDS (and fix_schema.py
declares acl_groups) in the schema BEFORE import, so fields index correctly from the
first load. NEVER purge-and-reimport a large corpus to add a field (that re-parses AND
re-embeds everything).

Env: PROJECT_ID, LOCATION, DATA_STORE_ID (env or ../.env).
"""
import argparse
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


def reindex_metadata_only(docs):
    """CHEAP: re-write each doc's structData in place via documents.patch. No content
    re-fetch / re-parse / re-embed. May lag, and may not register a newly-FILTERABLE
    field — caller must verify it filters."""
    patched = 0
    for d in docs:
        r = SESS.patch(f"https://{HOST}/v1/{d['name']}?updateMask=structData",
                       headers=HDR, json={"structData": d.get("structData", {})}, timeout=30)
        if r.status_code == 200:
            patched += 1
        else:
            print(f"  patch failed [{r.status_code}] {d['id']}: {r.text[:160]}")
    print(f"patched {patched}/{len(docs)} docs (metadata-only — no re-embed).")
    print("note: the new field becomes queryable only after VAIS's background reindex "
          "converges. VERIFY it filters; if it never registers, re-run WITHOUT "
          "--metadata-only (heavier: re-embeds content).")


def reimport_with_content(docs):
    """HEAVY fallback: re-import each doc WITH content — re-embeds. Reliable but costly."""
    records = [{"id": d["id"], "structData": d.get("structData", {}), "content": d["content"]}
               for d in docs if d.get("content", {}).get("uri")]
    print(f"re-importing {len(records)}/{len(docs)} docs WITH content (re-embeds)…")
    for i in range(0, len(records), 100):                 # inlineSource caps at 100/req
        chunk = records[i:i + 100]
        body = {"inlineSource": {"documents": chunk}, "reconciliationMode": "INCREMENTAL"}
        r = SESS.post(f"{BASE}/documents:import", headers=HDR, json=body, timeout=120)
        if r.status_code not in (200, 202):
            raise SystemExit(f"import failed [{r.status_code}]: {r.text[:300]}")
        res = poll(r.json()["name"])
        err = (res.get("error") or {}).get("message")
        print(f"  batch {i//100 + 1}: {'ok' if not err else 'ERROR ' + err}")
    print("done. The new field may take a few more minutes to become queryable.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metadata-only", action="store_true",
                    help="CHEAP: documents.patch structData in place (no content re-embed). "
                         "Preferred for metadata/facet changes; verify the field filters.")
    args = ap.parse_args()
    docs = list_docs()
    (reindex_metadata_only if args.metadata_only else reimport_with_content)(docs)


if __name__ == "__main__":
    main()
