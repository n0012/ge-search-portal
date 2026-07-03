# Optional analytics exports, each behind a flag (deploy-all.sh: --billing-export /
# --logging-export, or set the vars in terraform.tfvars).

# --- BigQuery billing export (enable_billing_export) --------------------------------
# Makes per-SKU cost queryable in BigQuery — e.g. proving no standalone Vertex AI
# Search charges (SKU 93D6-7280-CF05) accrue, i.e. traffic rides the GE subscription.
#
# Terraform provisions the dataset + grants for the billing export service agent, but
# POINTING the billing account at it is Console-only (no API exists): Billing →
# Billing export → BigQuery export → Detailed usage cost → Edit settings → pick this
# project + dataset. One click, once per billing account. Export starts from that
# moment — it does NOT backfill earlier usage.
resource "google_bigquery_dataset" "billing_export" {
  count         = var.enable_billing_export ? 1 : 0
  project       = var.project_id
  dataset_id    = "billing_export"
  friendly_name = "Cloud Billing export (per-SKU usage cost)"
  location      = var.bq_location
  description   = "Receives the Cloud Billing BigQuery export. Enable in Console: Billing → Billing export."
  depends_on    = [google_project_service.apis]
}

# The billing pipeline writes via this Google-managed service agent.
resource "google_bigquery_dataset_iam_member" "billing_export_writer" {
  count      = var.enable_billing_export ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.billing_export[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:billing-export-bigquery@system.gserviceaccount.com"
}

output "billing_export_next_step" {
  value = var.enable_billing_export ? join(" ", [
    "Dataset '${var.project_id}.billing_export' is ready. One-time Console step (no API exists):",
    "Billing → Billing export → BigQuery export → Detailed usage cost → Edit settings →",
    "project '${var.project_id}', dataset 'billing_export'. Export starts from enablement (no backfill).",
  ]) : "(billing export disabled — set enable_billing_export=true)"
}

# --- Cloud Logging export to BigQuery (enable_logging_export) -----------------------
# Streams the app's Cloud Run service + job logs into BigQuery (date-partitioned
# tables per log stream) for SQL over latency, errors, assist events, ingest runs.
resource "google_bigquery_dataset" "app_logs" {
  count         = var.enable_logging_export ? 1 : 0
  project       = var.project_id
  dataset_id    = "ge_search_app_logs"
  friendly_name = "GE Search Portal — Cloud Logging export"
  location      = var.bq_location
  description   = "Cloud Logging sink destination: Cloud Run service + job logs, partitioned tables."
  depends_on    = [google_project_service.apis]
}

resource "google_logging_project_sink" "app_logs" {
  count       = var.enable_logging_export ? 1 : 0
  project     = var.project_id
  name        = "ge-search-app-logs-to-bq"
  destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/${google_bigquery_dataset.app_logs[0].dataset_id}"
  # everything the app emits: the Cloud Run service and both jobs (only ours run here)
  filter                 = "resource.type=(\"cloud_run_revision\" OR \"cloud_run_job\")"
  unique_writer_identity = true

  bigquery_options {
    use_partitioned_tables = true
  }
}

# The sink writes through its own service identity; grant it into the dataset.
resource "google_bigquery_dataset_iam_member" "app_logs_writer" {
  count      = var.enable_logging_export ? 1 : 0
  project    = var.project_id
  dataset_id = google_bigquery_dataset.app_logs[0].dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = google_logging_project_sink.app_logs[0].writer_identity
}
