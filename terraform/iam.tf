# --- service accounts ---------------------------------------------------------
resource "google_service_account" "app" {
  project      = var.project_id
  account_id   = "ge-search-app"
  display_name = "GE Search Portal (Cloud Run service, read-only)"
}

resource "google_service_account" "ingest" {
  project      = var.project_id
  account_id   = "ge-search-ingest"
  display_name = "GE Search ingest (Cloud Run job, write)"
}

resource "google_service_account" "build" {
  project      = var.project_id
  account_id   = "ge-search-build"
  display_name = "GE Search Cloud Build"
}

# --- app SA: read-only (search + read ACLs + Gemini) --------------------------
resource "google_project_iam_member" "app" {
  for_each = toset([
    "roles/discoveryengine.viewer",
    "roles/datastore.user",
    "roles/aiplatform.user",
    "roles/storage.objectViewer",
    "roles/bigquery.dataEditor",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Narrow grant for the (otherwise read-only) app: report user events for autotuning and
# call the semantic Ranking API — WITHOUT editor (which could modify/delete the data store).
resource "google_project_iam_custom_role" "user_events_writer" {
  project = var.project_id
  role_id = "geSearchUserEventsWriter"
  title   = "GE Search app — user events + assistant"
  permissions = [
    "discoveryengine.userEvents.create",
    "discoveryengine.rankingConfigs.rank",
    # Required to call the GE engine assistant (:assist / :streamAssist); not in viewer.
    "discoveryengine.assistants.assist",
  ]
}

resource "google_project_iam_member" "app_user_events" {
  project = var.project_id
  role    = google_project_iam_custom_role.user_events_writer.id
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Let the app sign GCS V4 signed URLs from a keyless Cloud Run SA: it must be able to
# call IAM SignBlob as itself. Scopes signing to its OWN identity only.
resource "google_service_account_iam_member" "app_sign_self" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.app.email}"
}

# --- ingest SA: write (documents:import needs editor; write GCS + Firestore) --
resource "google_project_iam_member" "ingest" {
  for_each = toset([
    "roles/discoveryengine.editor",
    "roles/datastore.user",
    "roles/storage.objectAdmin",
    "roles/bigquery.dataEditor",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ingest.email}"
}

# --- build SA: push image + deploy service/job --------------------------------
resource "google_project_iam_member" "build" {
  for_each = toset([
    "roles/artifactregistry.writer",
    "roles/run.developer",
    "roles/logging.logWriter",
    "roles/storage.admin",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.build.email}"
}

# build SA must actAs the runtime SAs to deploy the service/job
resource "google_service_account_iam_member" "build_actas_app" {
  service_account_id = google_service_account.app.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.build.email}"
}

resource "google_service_account_iam_member" "build_actas_ingest" {
  service_account_id = google_service_account.ingest.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.build.email}"
}
