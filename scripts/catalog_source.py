"""Pluggable upstream source feeding the Firestore catalog. Selected by env
CATALOG_SOURCE = demo | dynamo | firestore.

  demo      - local JSONL (+ optional delta file); simulates add/modify/delete, no AWS.
  dynamo    - DynamoDB via boto3 (scaffold): scan for initial, Streams for incremental.
  firestore - read the already-populated catalog collection (pure handoff; the upstream
              replicator, e.g. an AWS Lambda, has already written it).

Every source yields the same record shape consumed by catalog_model / catalog.upsert.
"""
import json
import os

import _common as C

DEMO_FILE = os.path.join(C.ROOT, "seed", "catalog_demo.jsonl")
MANIFEST = os.path.join(C.ROOT, "_manifest.jsonl")
SEED = os.path.join(C.ROOT, "seed")
SOURCE_COMPANY = {"deepmind": "alphabet", "google-health": "alphabet", "amgen": "amgen"}


def _read_jsonl(path):
    if not path or not os.path.exists(path):
        return []
    return [json.loads(ln) for ln in open(path) if ln.strip()]


def _clean_id(raw):
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(raw))[:63].strip("_") or "doc"


def _acl_rules():
    try:
        import yaml
        r = yaml.safe_load(open(os.path.join(SEED, "acl_rules.yaml"))) or {}
        return r.get("by_department", {}), r.get("overrides", {})
    except Exception:
        return {"finance": ["finance"], "research": ["research"]}, {}


class DemoCatalogSource:
    """Base snapshot + an optional delta file layered on top (by document_id), so a single
    run can simulate adds, metadata modifications, and tombstones with no AWS."""
    def __init__(self, base=DEMO_FILE, delta=None):
        self.base = base
        self.delta = delta or os.environ.get("CATALOG_DELTA")

    def records(self):
        recs = {r["document_id"]: r for r in _read_jsonl(self.base)}
        for r in _read_jsonl(self.delta):
            recs[r["document_id"]] = {**recs.get(r["document_id"], {}), **r}
        return list(recs.values())


class FirestoreCatalogSource:
    """The catalog is already populated by an independent replicator; just read it."""
    def records(self):
        import catalog
        return catalog.read_all(catalog.client())


class ManifestCatalogSource:
    """Bridge the corpus fetcher (01_fetch_corpus.py) to the catalog: read _manifest.jsonl
    and emit catalog records for docs NOT already in the catalog — purely additive, so it
    models an incremental batch of newly-fetched real documents. ACL groups come from
    seed/acl_rules.yaml (same mapping 04_seed_acls.py uses); content_path points at the
    locally fetched file so reconcile stages it to GCS."""
    META = ("title", "department", "research_source", "research_area", "venue", "year",
            "publish_date", "doc_type", "report_kind", "source_url", "quarter")

    def __init__(self, manifest=MANIFEST):
        self.manifest = manifest

    def records(self):
        import catalog
        known = {r["document_id"] for r in catalog.read_all(catalog.client())}
        by_dept, overrides = _acl_rules()
        out, seen = [], set()
        for row in _read_jsonl(self.manifest):
            did = _clean_id(row.get("id"))
            if did in known or did in seen:
                continue                                   # additive + dedupe within file
            seen.add(did)
            company = row.get("company") or SOURCE_COMPANY.get(
                str(row.get("research_source", "")).lower(), "")
            groups = (overrides.get(row.get("id")) or overrides.get(did)
                      or by_dept.get(row.get("department"), []))
            rec = {"document_id": did, "content_path": row.get("pdf"), "groups": groups,
                   **{k: row[k] for k in self.META if row.get(k)}}
            if company:
                rec["company"] = company
            out.append(rec)
        return out


# Map a DynamoDB item -> our catalog record. Override the attribute names to match the
# Amgen table via env (DYNAMO_* ); these defaults are a sensible starting point.
def _dynamo_map(item):
    g = item.get(os.environ.get("DYNAMO_GROUPS_ATTR", "groups"))
    return {
        "document_id": str(item[os.environ.get("DYNAMO_KEY_ATTR", "id")]),
        "title": item.get("title", ""),
        "company": item.get("company", ""),
        "department": item.get("department", ""),
        "research_source": item.get("research_source", ""),
        "year": item.get("year", ""),
        "doc_type": item.get("doc_type", ""),
        "source_url": item.get(os.environ.get("DYNAMO_URI_ATTR", "source_url"), ""),
        "gcs_uri": item.get("gcs_uri", ""),
        "groups": list(g) if isinstance(g, (list, set, tuple)) else ([g] if g else []),
        # prefer the table's own version attr as the change key; else catalog_model hashes
        "content_hash": str(item.get(os.environ.get("DYNAMO_VERSION_ATTR", "version"), "")) or None,
        "deleted": bool(item.get("deleted", False)),
    }


class DynamoCatalogSource:
    """SCAFFOLD — wired but not exercised in the demo. Scans the table (initial load) and
    unmarshals items to catalog records. Incremental via DynamoDB Streams is a documented
    hook (the Streams->Lambda path can instead write the Firestore catalog directly, in
    which case use CATALOG_SOURCE=firestore here)."""
    def __init__(self, table=None, region=None):
        self.table = table or os.environ.get("DYNAMO_TABLE")
        self.region = region or os.environ.get("AWS_REGION", "us-east-1")
        if not self.table:
            raise SystemExit("DYNAMO_TABLE not set")

    def records(self):
        import boto3  # optional dep; only needed for the dynamo source
        from boto3.dynamodb.types import TypeDeserializer
        ddb = boto3.client("dynamodb", region_name=self.region)
        de = TypeDeserializer()
        out, kwargs = [], {"TableName": self.table}
        while True:
            resp = ddb.scan(**kwargs)
            for raw in resp.get("Items", []):
                out.append(_dynamo_map({k: de.deserialize(v) for k, v in raw.items()}))
            if "LastEvaluatedKey" not in resp:
                return out
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # def stream_records(self, shard_iterator): ...  # TODO: incremental via DynamoDB Streams


def from_env():
    kind = (os.environ.get("CATALOG_SOURCE") or "demo").lower()
    if kind == "demo":
        return DemoCatalogSource()
    if kind == "firestore":
        return FirestoreCatalogSource()
    if kind == "manifest":
        return ManifestCatalogSource()
    if kind == "dynamo":
        return DynamoCatalogSource()
    raise SystemExit(f"unknown CATALOG_SOURCE: {kind}")
