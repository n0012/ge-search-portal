#!/usr/bin/env python3
"""Showcase: query the Gemini Enterprise / Vertex AI Search data store directly over the
Discovery Engine API and pretty-print ranked results + the AI summary.

This hits the data store serving config (no ACL trim — that's the app's job); it's for
demoing retrieval quality and confirming the data store is populated.

Usage:
  python3 scripts/de_search.py "what was Q4 operating income?"
  python3 scripts/de_search.py "AlphaFold protein structure" --n 5
  python3 scripts/de_search.py "earnings" --filter 'company: ANY("amgen")'

Config from env or .env: PROJECT_ID, LOCATION (global|us|eu), DATA_STORE_ID.
"""
import argparse
import json
import os
import urllib.error
import urllib.request

import google.auth
from google.auth.transport.requests import Request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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


def _token():
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())
    return creds.token


def search(project, location, ds, query, n, filter_, token):
    host = "discoveryengine.googleapis.com" if location == "global" else f"{location}-discoveryengine.googleapis.com"
    url = (f"https://{host}/v1/projects/{project}/locations/{location}/collections/"
           f"default_collection/dataStores/{ds}/servingConfigs/default_search:search")
    body = {
        "query": query,
        "pageSize": n,
        "queryExpansionSpec": {"condition": "AUTO"},
        "spellCorrectionSpec": {"mode": "AUTO"},
        "contentSearchSpec": {
            "snippetSpec": {"returnSnippet": True},
            "summarySpec": {"summaryResultCount": 5, "includeCitations": True,
                            "ignoreAdversarialQuery": True},
        },
    }
    if filter_:
        body["filter"] = filter_
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "X-Goog-User-Project": project})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--filter", default="")
    args = ap.parse_args()

    project = cfg("PROJECT_ID")
    location = cfg("LOCATION", "global")
    ds = cfg("DATA_STORE_ID", "ge-search-demo")
    js = search(project, location, ds, args.query, args.n, args.filter, _token())

    summary = (js.get("summary", {}) or {}).get("summaryText", "")
    results = js.get("results", [])
    print(f"\nQ: {args.query}" + (f"   [filter: {args.filter}]" if args.filter else ""))
    print("=" * 78)
    if summary:
        print("AI SUMMARY:\n  " + summary.replace("\n", "\n  ") + "\n")
    print(f"TOP {len(results)} RESULTS:")
    for i, res in enumerate(results, 1):
        d = res.get("document", {})
        sd = d.get("structData", {}) or {}
        dd = d.get("derivedStructData", {}) or {}
        snip = next((s.get("snippet", "") for s in (dd.get("snippets") or []) if s.get("snippet")), "")
        tag = " · ".join(filter(None, [sd.get("company"), sd.get("research_source"),
                                       sd.get("doc_type"), sd.get("year")]))
        print(f"  {i}. {sd.get('title') or d.get('id')}")
        print(f"     [{tag}]")
        if snip:
            print(f"     {snip[:160].strip()}…")
    if not results:
        print("  (no results — is the data store populated yet?)")


if __name__ == "__main__":
    main()
