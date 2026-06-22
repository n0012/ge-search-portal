"""Per-document ingestion ledger -> BigQuery `ingestion_log`.

Best-effort and lazy: importing this module pulls only stdlib, and the BigQuery
client is imported only when a write actually happens AND BQ_LOGGING=on. So 01/02
stay runnable locally with no third-party installs. Never raises into the pipeline.

Stages: download (01) -> staged / import (03) -> acl (04).
"""
import datetime
import os

_client = None
_TASK = os.environ.get("CLOUD_RUN_TASK_INDEX")


def _enabled():
    return os.environ.get("BQ_LOGGING", "off").lower() == "on" and os.environ.get("PROJECT_ID")


def _bq():
    global _client
    if _client is None:
        from google.cloud import bigquery  # lazy: only when actually logging
        _client = bigquery.Client(project=os.environ["PROJECT_ID"])
    return _client


def ilog(stage, source, document_id, status, bytes_=None, error=None):
    """Record one document's lifecycle event. No-op unless BQ_LOGGING=on."""
    if not _enabled():
        return
    try:
        ds = os.environ.get("BQ_DATASET", "ge_search_logs")
        row = {
            "event_time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "task": int(_TASK) if (_TASK is not None and _TASK.isdigit()) else None,
            "source": source,
            "document_id": document_id,
            "stage": stage,
            "status": status,
            "bytes": bytes_,
            "error": (error or "")[:1000] or None,
        }
        _bq().insert_rows_json(f"{os.environ['PROJECT_ID']}.{ds}.ingestion_log",
                               [{k: v for k, v in row.items() if v is not None}])
    except Exception:
        pass  # ledger must never break ingestion
