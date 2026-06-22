# Cloud Scheduler -> Cloud Run reconcile job, on a cadence. The reconcile job is
# idempotent (hash-keyed delta), so periodic runs only act on real changes.

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = "ge-search-scheduler"
  display_name = "GE Search reconcile scheduler"
}

# Scheduler may trigger (run) the reconcile job.
resource "google_cloud_run_v2_job_iam_member" "scheduler_run" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_job.reconcile.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "reconcile" {
  project   = var.project_id
  region    = var.region
  name      = "ge-search-reconcile"
  schedule  = var.reconcile_schedule # off-:00 to avoid fleet-wide spikes
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/v2/${google_cloud_run_v2_job.reconcile.id}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_project_service.apis]
}
