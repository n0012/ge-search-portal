#!/usr/bin/env python3
"""Seed the Firestore RBAC graph used by the query-time security trimmer.

Reads:
  seed/personas.yaml   users -> groups
  seed/acl_rules.yaml  document metadata -> group(s)
  _manifest.jsonl      the documents that were fetched (ids + department)

Writes three Firestore collections (idempotent — deterministic doc ids, set()):
  documents        {document_id, title, department, company, research_source}
  document_groups  {document_id, group_id}     (M:N edges; doc-id == "<docid>__<group>")
  group_users      {group_id, user_id}         (M:N edges; doc-id == "<group>__<user>")

Access rule (enforced in the app): a user may see a document iff some group G has an
edge in BOTH document_groups (doc<->G) and group_users (G<->user).

Run where Firestore + creds are available:
  uv run --with pyyaml --with google-cloud-firestore python scripts/04_seed_acls.py
"""
import json
import os
import re
import sys

import yaml
from google.cloud import firestore

from ingestlog import ilog  # per-document ledger (no-op unless BQ_LOGGING=on)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SEED = os.path.join(ROOT, "seed")
MANIFEST = os.path.join(ROOT, "_manifest.jsonl")


def load_env(*keys):
    cfg = {}
    env = os.path.join(ROOT, ".env")
    if os.path.exists(env):
        for line in open(env):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    cfg.update({k: os.environ[k] for k in keys if k in os.environ})
    return cfg


def clean_id(raw):
    return re.sub(r"[^A-Za-z0-9_-]", "_", raw)[:63].strip("_") or "doc"


def main():
    cfg = load_env("PROJECT_ID", "FIRESTORE_DATABASE")
    project = cfg.get("PROJECT_ID")
    if not project or "CHANGEME" in project:
        sys.exit("missing PROJECT_ID (set it in .env)")
    database = cfg.get("FIRESTORE_DATABASE", "(default)") or "(default)"  # literal "(default)"

    personas = yaml.safe_load(open(os.path.join(SEED, "personas.yaml")))
    rules = yaml.safe_load(open(os.path.join(SEED, "acl_rules.yaml")))
    by_dept = rules.get("by_department", {})
    overrides = rules.get("overrides", {})

    db = firestore.Client(project=project, database=database)
    state = {"batch": db.batch(), "ops": 0}

    def put(ref, data):
        state["batch"].set(ref, data)
        state["ops"] += 1
        if state["ops"] >= 400:            # Firestore caps batches at 500 writes
            state["batch"].commit()
            state["batch"], state["ops"] = db.batch(), 0

    n_users = n_docs = n_dg = n_gu = 0

    # group_users edges (+ a users doc for the UI persona switcher)
    for u in personas.get("users", []):
        email = u["email"]
        put(db.collection("users").document(clean_id(email)), {
            "user_id": email, "display_name": u.get("display_name", email),
            "title": u.get("title", ""), "groups": u.get("groups", [])})
        n_users += 1
        for g in u.get("groups", []):
            put(db.collection("group_users").document(clean_id(f"{g}__{email}")),
                {"group_id": g, "user_id": email})
            n_gu += 1

    # documents + document_groups edges, derived from the fetched manifest.
    # If there's no manifest, still seed users/group_users (lets you re-seed just the
    # personas after editing seed/personas.yaml — no re-ingest needed).
    if not os.path.exists(MANIFEST):
        state["batch"].commit()
        print(f"seeded {n_users} users / {n_gu} group_users from personas.yaml "
              f"(no _manifest.jsonl — skipped documents)")
        return
    for line in open(MANIFEST):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        did = clean_id(row["id"])
        put(db.collection("documents").document(did), {
            "document_id": did, "title": row.get("title", ""),
            "department": row.get("department", ""),
            "company": row.get("company", ""),
            "research_source": row.get("research_source", "")})
        n_docs += 1
        groups = overrides.get(row["id"]) or overrides.get(did) \
            or by_dept.get(row.get("department"), [])
        for g in groups:
            put(db.collection("document_groups").document(clean_id(f"{did}__{g}")),
                {"document_id": did, "group_id": g})
            n_dg += 1
        src = row.get("research_source") or row.get("company") or row.get("department") or "doc"
        ilog("acl", src, did, "ok" if groups else "no_groups")

    state["batch"].commit()
    print(f"seeded Firestore '{database}' in {project}:")
    print(f"  users={n_users}  documents={n_docs}  "
          f"document_groups={n_dg}  group_users={n_gu}")


if __name__ == "__main__":
    main()
