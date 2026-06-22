#!/usr/bin/env python3
"""Sync derived metadata into the VAIS index, in place (no re-download / re-import).

Two things, both via documents.patch?updateMask=structData (same pattern as fix_titles.py):

  1. company rollup   — if a doc has no `company`, derive it from `research_source`
                        (deepmind / google-health -> alphabet, amgen -> amgen). This is
                        what makes the Company facet roll DeepMind + Google Health up
                        under Alphabet.
  2. acl_groups       — mirror the Firestore `document_groups` graph (the source of truth)
                        into the indexed `acl_groups` field, so VAIS can do the security
                        trim + faceting server-side (`acl_groups: ANY(<user groups>)`).

Idempotent: patches only docs whose company/acl_groups actually drift, so it serves as
both the one-time backfill and the ongoing doc->group re-sync. Run fix_schema.py first so
acl_groups is declared filterable.

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, FIRESTORE_DATABASE (env or ../.env).
"""
import os

import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import firestore

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# research_source -> parent company (used only when `company` is absent)
SOURCE_COMPANY = {"deepmind": "alphabet", "google-health": "alphabet", "amgen": "amgen"}


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
DB = cfg("FIRESTORE_DATABASE", "(default)")
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


def firestore_doc_groups(db):
    out = {}
    for d in db.collection("document_groups").stream():
        r = d.to_dict() or {}
        did, gid = r.get("document_id"), r.get("group_id")
        if did and gid:
            out.setdefault(did, set()).add(gid)
    return out


def derive_company(sd):
    if sd.get("company"):
        return None  # already set — never override
    return SOURCE_COMPANY.get((sd.get("research_source") or "").lower())


def prune_orphans(db, vais_ids):
    """Delete Firestore documents / document_groups whose id is no longer in VAIS, so the
    ACL graph stays in lockstep with the index. (Leaves users / group_users untouched.)
    Caller guards against an empty vais_ids set."""
    refs = [s.reference for s in db.collection("documents").stream() if s.id not in vais_ids]
    n_docs = len(refs)
    refs += [s.reference for s in db.collection("document_groups").stream()
             if (s.to_dict() or {}).get("document_id") not in vais_ids]
    for i in range(0, len(refs), 400):                      # Firestore caps batches at 500
        batch = db.batch()
        for ref in refs[i:i + 400]:
            batch.delete(ref)
        batch.commit()
    return {"documents": n_docs, "document_groups": len(refs) - n_docs}


def main():
    db = firestore.Client(project=PROJECT, database=DB)
    fs_groups = firestore_doc_groups(db)
    docs = list_docs()
    print(f"{len(docs)} docs in VAIS; {len(fs_groups)} have document_groups in Firestore")

    patched = company_fixed = acl_set = 0
    for d in docs:
        sd = dict(d.get("structData", {}) or {})
        changed = False

        comp = derive_company(sd)
        if comp:
            sd["company"] = comp
            company_fixed += 1
            changed = True

        want_acl = sorted(fs_groups.get(d["id"], set()))
        if sorted(sd.get("acl_groups", []) or []) != want_acl:
            sd["acl_groups"] = want_acl
            acl_set += 1
            changed = True

        if not changed:
            continue
        r = SESS.patch(f"https://{HOST}/v1/{d['name']}?updateMask=structData",
                       headers=HDR, json={"structData": sd}, timeout=30)
        if r.status_code == 200:
            patched += 1
        else:
            print(f"  patch failed [{r.status_code}] {d['id']}: {r.text[:160]}")

    print(f"patched {patched} docs  (company set: {company_fixed}, acl_groups synced: {acl_set})")

    # keep the ACL graph in lockstep with the index: drop Firestore entries for docs that
    # no longer exist in VAIS. Guarded — never prune if the VAIS listing came back empty.
    vais_ids = {d["id"] for d in docs}
    if vais_ids:
        pruned = prune_orphans(db, vais_ids)
        print(f"pruned {pruned['documents']} orphan documents, "
              f"{pruned['document_groups']} orphan document_groups")
    else:
        print("skipped prune (no VAIS docs listed)")


if __name__ == "__main__":
    main()
