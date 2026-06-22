# Corpus bucket (staged PDFs + the VAIS import manifest).
resource "google_storage_bucket" "corpus" {
  project                     = var.project_id
  name                        = local.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true
  depends_on                  = [google_project_service.apis]
}

# Let the Vertex AI service agent read corpus PDFs for multimodal answers (gs:// fileData).
resource "google_storage_bucket_iam_member" "vertex_reads_corpus" {
  bucket = google_storage_bucket.corpus.name
  role   = "roles/storage.objectViewer"
  member = google_project_service_identity.aiplatform_sa.member
}

# Firestore (Native) — the RBAC graph (documents / document_groups / group_users).
# ABANDON on destroy: the "(default)" database can't be re-created once it exists, so we
# never delete it (deploy-all.sh imports a pre-existing one). terraform destroy just drops
# it from state; the DB (and its data) survive a destroy/recreate cycle.
resource "google_firestore_database" "default" {
  project         = var.project_id
  name            = "(default)"
  location_id     = var.firestore_location
  type            = "FIRESTORE_NATIVE"
  deletion_policy = "ABANDON"
  depends_on      = [google_project_service.apis]
}

# Artifact Registry for the app/ingest container image.
resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = "ge-search"
  format        = "DOCKER"
  depends_on    = [google_project_service.apis]
}
