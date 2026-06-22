#!/usr/bin/env python3
"""Read-only health report for the catalog-driven pipeline: how many docs are loaded vs
pending vs failed, and whether the Firestore catalog and the VAIS index agree.

Answers "monitor the source, compare to Firestore, see loaded vs new / drift".

Env: PROJECT_ID, LOCATION, DATA_STORE_ID, FIRESTORE_DATABASE.
"""
import collections

import catalog
import loader


def main():
    db = catalog.client()
    records = catalog.read_all(db)
    by_state = collections.Counter(r.get("vais_state", "unknown") for r in records)
    active = {r["document_id"] for r in records
             if not r.get("deleted") and r.get("vais_state") == "loaded"}
    pending = [r["document_id"] for r in records
               if not r.get("deleted") and r.get("vais_state") in ("pending", None)]
    failed = [(r["document_id"], r.get("last_error", "")) for r in records
              if r.get("vais_state") == "failed"]

    vais = loader.existing_ids()

    print(f"catalog: {len(records)} records")
    for s, n in sorted(by_state.items()):
        print(f"   {s:9} {n}")
    print(f"\nVAIS index: {len(vais)} documents")

    in_catalog_not_vais = sorted(active - vais)   # marked loaded but missing from index
    in_vais_not_catalog = sorted(vais - {r['document_id'] for r in records})  # orphan in index
    print(f"\ndrift:")
    print(f"   loaded-in-catalog but missing in VAIS : {len(in_catalog_not_vais)}")
    for x in in_catalog_not_vais[:10]:
        print(f"      - {x}")
    print(f"   in VAIS but not in catalog            : {len(in_vais_not_catalog)}")
    for x in in_vais_not_catalog[:10]:
        print(f"      - {x}")

    if pending:
        print(f"\npending load ({len(pending)}): {pending[:10]}")
    if failed:
        print(f"\nfailed ({len(failed)}):")
        for did, err in failed[:10]:
            print(f"   - {did}: {err[:100]}")

    healthy = not in_catalog_not_vais and not pending and not failed
    print("\nstatus:", "IN SYNC" if healthy else "OUT OF SYNC (run reconcile.py)")


if __name__ == "__main__":
    main()
