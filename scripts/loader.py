"""VAIS + GCS load/delete primitives for the incremental reconcile job.

Inline `documents:import` (INCREMENTAL) is used rather than a GCS metadata file because
reconcile works on small deltas. Mirrors the proven path in force_reindex.py / 03.
"""
import os
import time
import urllib.request

import _common as C

_MIME = {".pdf": "application/pdf", ".htm": "text/html", ".html": "text/html"}


def mime_for(uri):
    return _MIME.get(os.path.splitext(uri)[1].lower(), "application/octet-stream")


def _bucket():
    from google.cloud import storage
    return storage.Client(project=C.PROJECT).bucket(C.GCS_BUCKET)


def upload_file(local_path, blob_path):
    b = _bucket().blob(blob_path)
    b.upload_from_filename(local_path)
    return f"gs://{C.GCS_BUCKET}/{blob_path}"


def ensure_staged(record):
    """Return a gs:// uri for a record's content, staging it if needed.
      gcs_uri set            -> use as-is (already in GCS)
      content_path (local)   -> upload (demo fixtures)
      source_url (http/file) -> download then upload
    Returns None if no content pointer is available."""
    if record.get("gcs_uri"):
        return record["gcs_uri"]
    doc_id = record["document_id"]
    local = record.get("content_path")
    if local and not os.path.isabs(local):
        local = os.path.join(C.ROOT, local)        # demo fixtures are repo-relative
    src = record.get("source_url", "")
    if not local and src:
        ext = os.path.splitext(src)[1].lower() or ".pdf"
        local = os.path.join("/tmp", f"{doc_id}{ext}")
        try:
            urllib.request.urlretrieve(src, local)
        except Exception:
            return None
    if not local or not os.path.exists(local):
        return None
    ext = os.path.splitext(local)[1].lower() or ".bin"
    return upload_file(local, f"corpus/incremental/{doc_id}{ext}")


def import_docs(records):
    """records: [{id, structData, content:{uri, mimeType}}]. INCREMENTAL inline import in
    batches of 100; polls each LRO. Returns (ok, errors:{name->msg})."""
    if not records:
        return True, {}
    sess, errs = C.de_session(), {}
    for i in range(0, len(records), 100):
        body = {"inlineSource": {"documents": records[i:i + 100]},
                "reconciliationMode": "INCREMENTAL"}
        r = sess.post(f"https://{C.DE_HOST}/v1/{C.BRANCH}/documents:import",
                      headers=C.HDR, json=body, timeout=120)
        if r.status_code not in (200, 202):
            errs[f"batch{i}"] = r.text[:300]
            continue
        name = r.json().get("name")
        for _ in range(60):                     # up to ~10 min
            o = sess.get(f"https://{C.DE_HOST}/v1/{name}", headers=C.HDR, timeout=30).json()
            if o.get("done"):
                if o.get("error"):
                    errs[name] = o["error"].get("message", "")
                break
            time.sleep(10)
    return (not errs), errs


def delete_docs(doc_ids):
    """Hard-delete docs from the VAIS branch. Returns (deleted_ids, errors:{id->msg})."""
    sess, ok, errs = C.de_session(), [], {}
    for did in doc_ids:
        r = sess.delete(f"https://{C.DE_HOST}/v1/{C.BRANCH}/documents/{did}",
                        headers=C.HDR, timeout=30)
        if r.status_code in (200, 204) or (r.status_code == 404):  # 404 == already gone
            ok.append(did)
        else:
            errs[did] = r.text[:200]
    return ok, errs


def existing_ids():
    """All document ids currently in the VAIS branch (for drift comparison)."""
    sess, ids, token = C.de_session(), set(), ""
    while True:
        url = f"https://{C.DE_HOST}/v1/{C.BRANCH}/documents?pageSize=300" + (
            f"&pageToken={token}" if token else "")
        j = sess.get(url, headers=C.HDR, timeout=60).json()
        ids |= {d["id"] for d in j.get("documents", [])}
        token = j.get("nextPageToken")
        if not token:
            return ids
