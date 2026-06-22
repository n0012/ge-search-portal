#!/usr/bin/env python3
"""Reconcile the Firestore `catalog` into VAIS — the downstream half of the pipeline.

Reads the catalog, computes the delta (catalog_model.plan_delta), then:
  load   (new/modified): stage content to GCS -> documents:import INCREMENTAL with
                         structData incl acl_groups -> seed the ACL graph -> mark loaded.
  purge  (tombstoned)  : delete from VAIS -> prune the ACL graph -> mark deleted.
Each event is written to the BigQuery ingestion ledger. Idempotent: the SAME run handles
both the initial load (everything pending) and steady-state incremental (only the delta),
so a Cloud Scheduler can call it on a cadence.

The catalog itself is populated by replicate_catalog.py (or an external Lambda); this job
never talks to AWS.

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, GCS_BUCKET, FIRESTORE_DATABASE, BQ_LOGGING.
"""
import catalog
import catalog_model
import loader
from ingestlog import ilog


def _src(r):
    return r.get("research_source") or r.get("company") or r.get("department") or "doc"


def main():
    db = catalog.client()
    records = catalog.read_all(db)
    to_load, to_delete = catalog_model.plan_delta(records)
    print(f"catalog: {len(records)} records -> {len(to_load)} to load, "
          f"{len(to_delete)} to delete")

    # ---- LOAD (new / modified) ------------------------------------------------
    import_records, staged = [], []
    for r in to_load:
        uri = loader.ensure_staged(r)
        if not uri:
            catalog.mark_failed(db, r["document_id"], "no content (staging failed)")
            ilog("reconcile", _src(r), r["document_id"], "failed", error="no content")
            continue
        import_records.append({"id": r["document_id"],
                               "structData": catalog_model.to_struct(r),
                               "content": {"uri": uri, "mimeType": loader.mime_for(uri)}})
        staged.append(r)

    if import_records:
        ok, errs = loader.import_docs(import_records)
        for r in staged:
            if ok:
                catalog.mark_loaded(db, r["document_id"], catalog_model.effective_hash(r))
                catalog.seed_graph(db, r)
                ilog("reconcile", _src(r), r["document_id"], "loaded")
            else:
                catalog.mark_failed(db, r["document_id"], str(errs)[:400])
                ilog("reconcile", _src(r), r["document_id"], "failed", error=str(errs)[:400])
        print(f"load: {'ok' if ok else 'ERROR ' + str(errs)[:200]} "
              f"({len(import_records)} docs)")

    # ---- PURGE (tombstoned) ---------------------------------------------------
    if to_delete:
        ids = [r["document_id"] for r in to_delete]
        deleted, errs = loader.delete_docs(ids)
        for r in to_delete:
            did = r["document_id"]
            if did in deleted:
                catalog.prune_graph(db, did)
                catalog.mark_deleted(db, did)
                ilog("reconcile", _src(r), did, "deleted")
            else:
                catalog.mark_failed(db, did, errs.get(did, "delete failed"))
                ilog("reconcile", _src(r), did, "failed", error=errs.get(did, ""))
        print(f"purge: {len(deleted)}/{len(ids)} deleted from VAIS + ACL graph")

    if not to_load and not to_delete:
        print("nothing to do — catalog and VAIS are in sync.")


if __name__ == "__main__":
    main()
