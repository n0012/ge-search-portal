#!/usr/bin/env python3
"""Declare `acl_groups` in the VAIS data-store schema so it can be used as a server-side
ACL filter (`acl_groups: ANY("research")`).

acl_groups is the indexed mirror of the Firestore document_groups graph: a repeated
string of the group ids allowed to see a doc. We mark it indexable (= filterable) only —
NOT searchable (must not affect text relevance), NOT retrievable (don't echo ACLs back to
clients), NOT facetable (it's a security key, not a user-facing facet).

Idempotent: a no-op if acl_groups is already declared the same way.

Env: PROJECT_ID, LOCATION, DATA_STORE_ID  (read from environment or ../.env).
"""
import json
import os  # noqa: F401  (used by cfg via os.environ)

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
SCHEMA = (f"projects/{PROJECT}/locations/{LOCATION}/collections/default_collection/"
          f"dataStores/{DS}/schemas/default_schema")
_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
SESS = AuthorizedSession(_creds)
HDR = {"X-Goog-User-Project": PROJECT}

# filter-only keyword set: indexable => filterable; not searchable (no text-relevance
# impact), not retrievable (don't echo ACLs back), not facetable (it's a security key,
# not a user-facing facet).
ACL_KEYWORDS = {
    "indexable": True,
    "searchable": False,
    "retrievable": False,
    "dynamicFacetable": False,
}


def acl_decl(existing):
    """The declaration for acl_groups, matching the field's shape in the live schema.
    If auto-detection already saw documents, the field is {"type": "array", "items":
    {...}} with the config keywords on `items` — the type can't be altered, so keep the
    array and set the keywords there. On a still-empty schema declare a plain string
    with the keywords inline (repeated values still match ANY() filters)."""
    if (existing or {}).get("type") == "array":
        items = dict(existing.get("items") or {"type": "string"}, **ACL_KEYWORDS)
        return {"type": "array", "items": items}
    return dict({"type": "string"}, **ACL_KEYWORDS)


def main():
    r = SESS.get(f"https://{HOST}/v1/{SCHEMA}", headers=HDR, timeout=60)
    r.raise_for_status()
    # The data store keeps its schema as a jsonSchema STRING; patch it back the same way
    # (sending structSchema would drop the auto-inferred fields). Preserve all existing
    # properties and just add acl_groups.
    schema = json.loads(r.json().get("jsonSchema") or "{}")
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema.setdefault("type", "object")
    props = schema.setdefault("properties", {})

    want = acl_decl(props.get("acl_groups"))
    if props.get("acl_groups") == want:
        print("acl_groups already declared — nothing to do.")
        return

    props["acl_groups"] = want
    body = {"name": SCHEMA, "jsonSchema": json.dumps(schema)}
    p = SESS.patch(f"https://{HOST}/v1/{SCHEMA}", headers=HDR, json=body, timeout=60)
    if p.status_code != 200:
        raise SystemExit(f"schema patch failed [{p.status_code}]: {p.text[:400]}")
    print("acl_groups declared (filterable string, filter-only).")
    print("Note: existing docs become filterable on acl_groups once re-indexed "
          "(sync_metadata.py patches them next).")


if __name__ == "__main__":
    main()
