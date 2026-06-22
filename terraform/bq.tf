# BigQuery logging: who searched what / when, and thumbs up/down feedback.
resource "google_bigquery_dataset" "logs" {
  project    = var.project_id
  dataset_id = "ge_search_logs"
  location   = var.bq_location
  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "searches" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.logs.dataset_id
  table_id            = "searches"
  deletion_protection = false
  schema = jsonencode([
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "search_id", type = "STRING" },        # correlation id (join to ai_turns/feedback)
    { name = "user", type = "STRING" },
    { name = "query", type = "STRING" },
    { name = "groups", type = "STRING", mode = "REPEATED" },
    { name = "filters", type = "STRING" },
    { name = "result_count", type = "INTEGER" },
    { name = "result_doc_ids", type = "STRING", mode = "REPEATED" },
  ])
}

resource "google_bigquery_table" "ingestion_log" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.logs.dataset_id
  table_id            = "ingestion_log"
  deletion_protection = false
  schema = jsonencode([
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "task", type = "INTEGER" },
    { name = "source", type = "STRING" },
    { name = "document_id", type = "STRING" },
    { name = "stage", type = "STRING" },  # download | staged | import | acl
    { name = "status", type = "STRING" }, # ok | skipped_no_pdf | failed | submitted | no_groups
    { name = "bytes", type = "INTEGER" },
    { name = "error", type = "STRING" },
  ])
}

# One row per AI generation turn (summarize / ask-these-docs / per-doc Q&A): which model
# actually ran (incl. failover), whether web search/thinking applied, and latency.
resource "google_bigquery_table" "ai_turns" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.logs.dataset_id
  table_id            = "ai_turns"
  deletion_protection = false
  schema = jsonencode([
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "search_id", type = "STRING" },         # join back to searches/feedback
    { name = "user", type = "STRING" },
    { name = "groups", type = "STRING", mode = "REPEATED" },
    { name = "feature", type = "STRING" },          # answer | ask | doc_qa
    { name = "query", type = "STRING" },
    { name = "question", type = "STRING" },
    { name = "document_id", type = "STRING" },       # doc_qa only
    { name = "model_requested", type = "STRING" },   # what the UI picked ("" = default)
    { name = "model_used", type = "STRING" },        # what actually ran (after failover)
    { name = "used_search", type = "BOOL" },         # Google Search grounding on?
    { name = "result_count", type = "INTEGER" },
    { name = "latency_ms", type = "INTEGER" },
  ])
}

resource "google_bigquery_table" "feedback" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.logs.dataset_id
  table_id            = "feedback"
  deletion_protection = false
  schema = jsonencode([
    { name = "event_time", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "search_id", type = "STRING" },         # join back to searches/ai_turns
    { name = "user", type = "STRING" },
    { name = "query", type = "STRING" },
    { name = "document_id", type = "STRING" },
    { name = "title", type = "STRING" },
    { name = "vote", type = "STRING" },
  ])
}
