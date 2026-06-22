resource "google_project_service" "apis" {
  for_each = toset([
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "discoveryengine.googleapis.com",
    "firestore.googleapis.com",
    "run.googleapis.com",
    "cloudbuild.googleapis.com",
    "aiplatform.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "iap.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com", # SignBlob for keyless V4 signed URLs (/api/doc)
    "cloudscheduler.googleapis.com", # triggers the incremental reconcile job on a cadence
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# IAP service agent — granted run.invoker on the Cloud Run service (see run.tf).
resource "google_project_service_identity" "iap_sa" {
  provider   = google-beta
  project    = var.project_id
  service    = "iap.googleapis.com"
  depends_on = [google_project_service.apis]
}

# Vertex AI service agent — needs to read corpus PDFs from GCS for multimodal answers.
resource "google_project_service_identity" "aiplatform_sa" {
  provider   = google-beta
  project    = var.project_id
  service    = "aiplatform.googleapis.com"
  depends_on = [google_project_service.apis]
}

# Give service agents a moment to propagate before IAM bindings reference them.
resource "time_sleep" "wait_service_agents" {
  create_duration = "30s"
  depends_on      = [google_project_service_identity.iap_sa]
}
