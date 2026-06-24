output "service_uri" {
  value       = google_cloud_run_v2_service.app.uri
  description = "Cloud Run URL (access via IAP)."
}

output "data_store_id" {
  value = google_discovery_engine_data_store.ds.data_store_id
}

output "engine_id" {
  value       = google_discovery_engine_search_engine.engine.engine_id
  description = "Gemini Enterprise (Agentspace) app ID (app_type=APP_TYPE_INTRANET); the app queries its serving config (:search) + assistant (:streamAssist) so traffic bills through the GE subscription."
}

output "corpus_bucket" {
  value = "gs://${local.bucket_name}"
}

output "ingest_job" {
  value = google_cloud_run_v2_job.ingest.name
}

output "app_service_account" {
  value = google_service_account.app.email
}

output "ingest_service_account" {
  value = google_service_account.ingest.email
}

output "build_service_account" {
  value = google_service_account.build.email
}
