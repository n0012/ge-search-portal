# Ingestion: initial load + incremental sync (DynamoDB-ready)

The pipeline supports an **initial bulk load** and **ongoing incremental** updates of just
the delta, decoupled from the upstream system of record (Amgen's index lives in **DynamoDB**
on AWS). The decoupling point is a **Firestore `catalog` collection**: an independent
replicator keeps the catalog in step with the source; our reconcile job syncs the catalog
into Vertex AI Search. Our VAIS pipeline never talks to AWS.

```
DynamoDB ──(Streams→Lambda  OR  boto3 poll = replicate_catalog.py)──▶ Firestore `catalog`
                                                  │  content_hash, vais_state, tombstone
                                                  ▼
                       reconcile.py  (Cloud Scheduler → Cloud Run job)  ──▶ VAIS + ACL graph
```

The delta engine is **hash-keyed and idempotent**, so the *same* job does the initial load
(everything `pending`) and steady-state incremental (only new/modified/deleted). Re-running
with no source change is a no-op.

## The `catalog` collection (the contract)

One Firestore doc per source record, id == `document_id` == VAIS id == Dynamo partition key:

| field | who sets it | purpose |
|---|---|---|
| `title, company, department, research_source, year, doc_type, source_url, …` | replicator | metadata → VAIS structData |
| `gcs_uri` / `source_url` / `content_path` | replicator | where to fetch the file |
| `groups` (list) | replicator | ACL → VAIS `acl_groups` + Firestore graph |
| `content_hash`, `deleted` | replicator | change detection / tombstone |
| `vais_state` (`pending\|loaded\|failed\|deleted`), `loaded_hash`, `loaded_at`, `last_error` | **reconcile** | sync state |

Delta rule (`scripts/catalog_model.py::plan_delta`): **load** when not deleted and
(never loaded OR `content_hash != loaded_hash`); **purge** when tombstoned and still present.

## Adding documents — Firestore is the only on-ramp

**To add a document you write ONE record into the Firestore `catalog` collection.** You
never call Vertex AI Search directly. The reconcile job sees the new record
(`vais_state=pending`) and does the rest: stage content → import → set ACL → mark `loaded`.

Minimal record:

```json
{
  "document_id": "amgen_8-k_2026-02-03",
  "groups": ["finance"],                            // ACL — required to be visible
  "source_url": "https://www.sec.gov/.../doc.htm",  // content pointer: source_url | gcs_uri | content_path
  "title": "Amgen 8-K 2026-02-03", "company": "amgen", "department": "finance", "doc_type": "8-K"
}
```

Three ways to write that record — **all converge on the same catalog**, then `reconcile.py`
(or the scheduled Cloud Run job) loads it:

1. **By hand / scripted:** `python scripts/add_document.py --json '{...}'` (or a JSONL file).
2. **From a source snapshot:** `replicate_catalog.py` with `CATALOG_SOURCE=demo|manifest|dynamo`.
3. **Production:** the DynamoDB→Firestore replicator writes the identical record per change.

### How the DynamoDB replication does the same thing

A DynamoDB item insert/update/delete → DynamoDB Stream event → Lambda maps the item to the
**same catalog record shape** and writes it to Firestore (`set` on INSERT/MODIFY,
`deleted:true` on REMOVE). That is identical to `add_document.py` / `replicate_catalog.py` —
only the *trigger* differs. Mapping (see `_dynamo_map` in `catalog_source.py`):

```
DynamoDB item             ->   catalog record
  id (partition key)      ->   document_id
  groups                  ->   groups            (ACL)
  source_url / gcs_uri    ->   content pointer
  version                 ->   content_hash      (change detection)
  REMOVE stream event     ->   deleted: true     (tombstone)
```

So "insert into Firestore" is the universal starting point: a human, a batch job, or the
Lambda all just upsert a catalog record — and the same idempotent reconcile job loads it.

## Components (`scripts/`)

- **`catalog_source.py`** — pluggable source, chosen by `CATALOG_SOURCE`:
  - `demo` — local JSONL + an optional delta file (`CATALOG_DELTA`); no AWS.
  - `dynamo` — boto3 **scaffold**: scans the table, unmarshals items → catalog records
    (attribute names configurable via `DYNAMO_KEY_ATTR`, `DYNAMO_GROUPS_ATTR`,
    `DYNAMO_URI_ATTR`, `DYNAMO_VERSION_ATTR`). Needs `pip install boto3` + AWS creds.
  - `firestore` — read the already-populated catalog (pure handoff).
- **`replicate_catalog.py`** — upstream replicator: source → catalog upsert (marks `pending`
  on change, sets tombstones). The GCP-side equivalent of a DynamoDB-Streams Lambda.
- **`reconcile.py`** — downstream: catalog → VAIS. Loads new/modified (stage to GCS →
  `documents:import` with `acl_groups` → seed ACL graph), purges tombstoned (delete from
  VAIS → prune graph), writes the BigQuery `ingestion_log` ledger.
- **`catalog_status.py`** — read-only health/drift report (loaded vs pending vs failed;
  catalog-vs-VAIS drift).
- **`gen_demo_catalog.py`** — bootstrap the catalog from current VAIS+Firestore (everything
  `loaded`), so the demo starts in-sync.

## Plugging in DynamoDB

**Option A — Streams→Lambda (real-time, recommended for prod).** Deploy the AWS-side
DynamoDB-Streams → Lambda bridge (see the reference in the design notes) that writes the
**same catalog schema** above into Firestore via the Firebase Admin SDK. Run our reconcile
job with `CATALOG_SOURCE=firestore` (it just reads the catalog). No AWS coupling in GCP.

**Option B — boto3 poller (GCP-side).** Schedule `replicate_catalog.py` with
`CATALOG_SOURCE=dynamo`, `DYNAMO_TABLE=...`, AWS creds (and the `DYNAMO_*_ATTR` mappings),
then `reconcile.py`. Simpler to operate but the poller holds AWS creds.

Either way the contract is identical; only who writes the catalog differs.

## Scheduling & monitoring

- `terraform/scheduler.tf` runs the `ge-search-reconcile` Cloud Run job on
  `var.reconcile_schedule` (default every 15 min, off-:00). For Option B, also schedule
  `replicate_catalog.py`.
- Monitor with `scripts/catalog_status.py` and the BigQuery `ingestion_log` table
  (per-document lifecycle ledger).

## Demo (no AWS)

```sh
cd ge-search-portal
export PROJECT_ID=... LOCATION=global DATA_STORE_ID=ge-search-demo \
       GCS_BUCKET=gs://<corpus-bucket> FIRESTORE_DATABASE="(default)" BQ_LOGGING=on

python3 scripts/gen_demo_catalog.py        # bootstrap catalog from current state (loaded)
python3 scripts/catalog_status.py          # -> all loaded, 0 pending, 0 drift

# ADD a new doc
CATALOG_SOURCE=demo CATALOG_DELTA=seed/catalog_delta_add.jsonl python3 scripts/replicate_catalog.py
python3 scripts/reconcile.py               # stages + imports the new doc into VAIS

# MODIFY it (metadata change -> new hash -> re-import)
CATALOG_SOURCE=demo CATALOG_DELTA=seed/catalog_delta_modify.jsonl python3 scripts/replicate_catalog.py
python3 scripts/reconcile.py

# DELETE it (tombstone -> purge from VAIS + ACL graph); leaves the store clean
CATALOG_SOURCE=demo CATALOG_DELTA=seed/catalog_delta_delete.jsonl python3 scripts/replicate_catalog.py
python3 scripts/reconcile.py
python3 scripts/catalog_status.py          # -> back in sync
```

To go live, deploy (`bash deploy-all.sh ... --steps build`) so the scheduler + reconcile
job pick up the image, and switch `CATALOG_SOURCE` to `firestore` (Option A) or `dynamo`
(Option B).
