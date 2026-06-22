"""Best-effort BigQuery logging of searches and feedback (who searched what, when,
and thumbs up/down). Never raises into the request path — logging failures are swallowed.
Tables are created by Terraform (terraform/bq.tf)."""
import datetime
import json

from google.cloud import bigquery

import config

_client = None


def _c():
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.PROJECT_ID)
    return _client


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _insert(table, row):
    if config.BQ_LOGGING != "on":
        return
    try:
        _c().insert_rows_json(f"{config.PROJECT_ID}.{config.BQ_DATASET}.{table}", [row])
    except Exception:
        pass  # logging must never break the request


def log_search(user, query, groups, filters, results, search_id=""):
    _insert("searches", {
        "event_time": _now(),
        "search_id": search_id,
        "user": user,
        "query": query,
        "groups": sorted(groups),
        "filters": json.dumps(filters or {}),
        "result_count": len(results),
        "result_doc_ids": [r.get("documentId") for r in results if r.get("documentId")],
    })


def log_ai_turn(user, groups, feature, *, search_id="", query="", question="",
                document_id="", model_requested="", model_used="", used_search=False,
                result_count=0, latency_ms=0):
    """One row per AI generation turn, correlated to its search via search_id."""
    _insert("ai_turns", {
        "event_time": _now(),
        "search_id": search_id,
        "user": user,
        "groups": sorted(groups or []),
        "feature": feature,                       # answer | ask | doc_qa
        "query": query,
        "question": question,
        "document_id": document_id,
        "model_requested": model_requested or "",
        "model_used": model_used or "",
        "used_search": bool(used_search),
        "result_count": result_count,
        "latency_ms": latency_ms,
    })


def log_feedback(user, query, document_id, title, vote, search_id=""):
    _insert("feedback", {
        "event_time": _now(),
        "search_id": search_id,
        "user": user,
        "query": query,
        "document_id": document_id,
        "title": title,
        "vote": vote,
    })
