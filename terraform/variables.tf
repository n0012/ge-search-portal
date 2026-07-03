variable "project_id" {
  type        = string
  description = "Target GCP project."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, GCS, Artifact Registry."
}

variable "location" {
  type        = string
  default     = "global"
  description = "Discovery Engine collection location: global | us | eu."
}

variable "firestore_location" {
  type        = string
  default     = "nam5"
  description = "Firestore database location."
}

variable "bq_location" {
  type        = string
  default     = "US"
  description = "BigQuery dataset location for search/feedback logs."
}

variable "data_store_id" {
  type    = string
  default = "ge-search-demo"
}

variable "bucket_name" {
  type        = string
  default     = ""
  description = "Corpus bucket name (no gs://). Defaults to <project>-ge-search-corpus."
}

variable "engine_id" {
  type        = string
  default     = "ge-search-app"
  description = "Gemini Enterprise (Agentspace) app ID (app_type=APP_TYPE_INTRANET) over the data store. The app queries THIS engine's serving config for :search and its assistant for :streamAssist, so all traffic bills through the GE per-seat subscription (querying the data store directly bills standalone, SKU 93D6-7280-CF05). Must be a GE engine."
}

variable "assistant_id" {
  type        = string
  default     = "default_assistant"
  description = "Assistant ID under the GE engine used for :streamAssist (auto-created with the GE app)."
}

variable "identity_source" {
  type    = string
  default = "demo"
  # WHOSE identity filters the data (RBAC) — independent of iap_members (who can REACH the
  # site). demo = honor the persona switcher (X-Demo-User), demos only. iap = trust the IAP
  # login so each signed-in user filters their own data (use for real deployments).
  description = "Identity used for ACL filtering: 'demo' (persona switcher) or 'iap' (real IAP login). NOT the same as iap_members."
  validation {
    condition     = contains(["demo", "iap"], var.identity_source)
    error_message = "identity_source must be \"demo\" or \"iap\"."
  }
}

variable "iap_members" {
  type    = list(string)
  default = []
  # Who can REACH the site via IAP (e.g. "user:you@corp.com", "group:team@corp.com",
  # "domain:corp.com"). Empty = fail-closed (nobody) — set this in terraform.tfvars.
  # deploy-all.sh auto-grants the deploying gcloud user when this is left empty, so the
  # operator can always open the site out of the box.
  description = "Principals granted roles/iap.httpsResourceAccessor. Empty = none (set in terraform.tfvars)."
}

variable "ingest_limit" {
  type        = string
  default     = "100"
  description = "Max docs per sub-source PER TASK for the ingest job (richer corpus; raise/lower to taste)."
}

variable "edgar_forms" {
  type        = string
  default     = "10-K,10-Q,8-K"
  description = "SEC EDGAR filing types to ingest (8-K = earnings/current reports)."
}

variable "ingest_task_count" {
  type        = number
  default     = 1
  description = "Cloud Run Job tasks; the corpus is sharded disjointly across them."
}

variable "ingest_parallelism" {
  type        = number
  default     = 1
  description = "How many ingest tasks run concurrently (0 = max)."
}

variable "reconcile_schedule" {
  type        = string
  default     = "8,23,38,53 * * * *" # every 15 min, offset off :00 to avoid fleet spikes
  description = "Cron schedule (UTC) for the incremental reconcile job."
}

variable "enable_billing_export" {
  type        = bool
  default     = false
  description = "Provision a BigQuery dataset (+ billing service-agent grant) for the Cloud Billing per-SKU export. Pointing the billing account at it is a one-time Console step (no API). deploy-all.sh flag: --billing-export."
}

variable "enable_logging_export" {
  type        = bool
  default     = false
  description = "Create a Cloud Logging sink streaming the app's Cloud Run service/job logs into a partitioned BigQuery dataset. deploy-all.sh flag: --logging-export."
}
