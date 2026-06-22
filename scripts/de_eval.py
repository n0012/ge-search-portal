#!/usr/bin/env python3
"""Evaluate the deployed data store + security model against live VAIS + Firestore.

Two checks, run with your own ADC (mirrors what the backend does, no IAP needed):
  A. Retrieval relevance — domain queries should return docs of that department.
  B. Security trim — replicate retrieve→ACL-trim per persona (VAIS + Firestore
     document_groups/group_users) and assert each persona only sees their domain,
     and the other domain is excluded.

Exit code is non-zero if any check fails (CI-usable).

Config from env or .env: PROJECT_ID, LOCATION, DATA_STORE_ID, FIRESTORE_DATABASE.
"""
import json
import os
import sys
import urllib.request

import google.auth
from google.auth.transport.requests import Request
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FINANCE_Q = ["Q4 operating income", "annual report revenue", "earnings results"]
RESEARCH_Q = ["protein structure prediction", "machine learning for clinical care",
              "large language model evaluation"]
# persona email -> expected sole department (from seed/personas.yaml)
PERSONAS = {"dana.finance@example.com": "finance", "riley.research@example.com": "research"}
# a representative query per domain (for the trim test)
DOMAIN_Q = {"finance": "Q4 operating income and total revenue",
            "research": "clinical reasoning with large language models"}


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


PROJECT = cfg("PROJECT_ID")
LOCATION = cfg("LOCATION", "global")
DS = cfg("DATA_STORE_ID", "ge-search-demo")
DB = cfg("FIRESTORE_DATABASE", "(default)")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
_fs = firestore.Client(project=PROJECT, database=DB)


def _token():
    _creds.refresh(Request())
    return _creds.token


def vais(query, n=10):
    host = "discoveryengine.googleapis.com" if LOCATION == "global" else f"{LOCATION}-discoveryengine.googleapis.com"
    url = (f"https://{host}/v1/projects/{PROJECT}/locations/{LOCATION}/collections/"
           f"default_collection/dataStores/{DS}/servingConfigs/default_search:search")
    req = urllib.request.Request(
        url, data=json.dumps({"query": query, "pageSize": n}).encode(), method="POST",
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json",
                 "X-Goog-User-Project": PROJECT})
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read())
    out = []
    for res in js.get("results", []):
        d = res.get("document", {})
        sd = d.get("structData", {}) or {}
        out.append({"id": d.get("id"), "department": sd.get("department"),
                    "title": sd.get("title")})
    return out


def groups_for_user(email):
    q = _fs.collection("group_users").where(filter=FieldFilter("user_id", "==", email))
    return {d.get("group_id") for d in q.stream()}


def doc_groups(ids):
    out = {}
    col = _fs.collection("document_groups")
    for i in range(0, len(ids), 10):
        chunk = ids[i:i + 10]
        for d in col.where(filter=FieldFilter("document_id", "in", chunk)).stream():
            out.setdefault(d.get("document_id"), set()).add(d.get("group_id"))
    return out


def main():
    fails = []
    print(f"Eval: project={PROJECT} data_store={DS}\n" + "=" * 70)

    # sanity: is Firestore seeded?
    seeded = {e: groups_for_user(e) for e in PERSONAS}
    if not any(seeded.values()):
        print("Firestore not seeded yet (group_users empty) — run the ingest job first.")
        sys.exit(2)

    # ---- A. retrieval relevance ----
    print("\nA. Retrieval relevance (top-5 share matching the domain):")
    for dept, queries in (("finance", FINANCE_Q), ("research", RESEARCH_Q)):
        for q in queries:
            res = vais(q, 5)
            if not res:
                fails.append(f"relevance:{q}:no_results")
                print(f"  ✗ {dept:8s} '{q}': no results")
                continue
            match = sum(1 for r in res if r["department"] == dept)
            frac = match / len(res)
            ok = frac >= 0.5
            (print if ok else lambda *a: (print(*a), fails.append(f"relevance:{q}")))(
                f"  {'✓' if ok else '✗'} {dept:8s} '{q}': {match}/{len(res)} {dept}")

    # ---- B. security trim per persona: own domain visible, other domain blocked ----
    def trim(res, ug):
        dg = doc_groups([r["id"] for r in res if r["id"]])
        return [r for r in res if dg.get(r["id"], set()) & ug]

    print("\nB. Security trim per persona (own domain visible, other blocked):")
    for email, dept in PERSONAS.items():
        ug = seeded[email]
        other = "research" if dept == "finance" else "finance"
        own = trim(vais(DOMAIN_Q[dept], 15), ug)
        cross = trim(vais(DOMAIN_Q[other], 15), ug)
        own_depts = {r["department"] for r in own}
        ok = bool(own) and own_depts <= {dept} and not cross
        print(f"  {'✓' if ok else '✗'} {email:26s} own:{len(own)} ({sorted(own_depts) or '∅'})  "
              f"cross-domain leaked:{len(cross)}")
        if not own:
            fails.append(f"trim-own-empty:{email}")
        if own_depts - {dept}:
            fails.append(f"trim-leak:{email}")
        if cross:
            fails.append(f"trim-cross-leak:{email}")

    print("\n" + "=" * 70)
    if fails:
        print(f"FAIL ({len(fails)}): " + "; ".join(fails))
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
