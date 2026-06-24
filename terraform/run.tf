# --- Cloud Run service (the app), IAP ON ------------------------------------
resource "google_cloud_run_v2_service" "app" {
  project             = var.project_id
  name                = "ge-search-portal"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  iap_enabled         = true
  deletion_protection = false

  template {
    service_account = google_service_account.app.email
    containers {
      image = local.placeholder_image
      ports { container_port = 8080 }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "PROJECT_NUMBER"
        value = data.google_project.this.number
      }
      env {
        name  = "LOCATION"
        value = var.location
      }
      env {
        name  = "DATA_STORE_ID"
        value = var.data_store_id
      }
      env {
        # GE engine: app queries its serving config (:search) + assistant (:streamAssist) so all
        # traffic is covered by the GE subscription (not billed standalone).
        name  = "ENGINE_ID"
        value = google_discovery_engine_search_engine.engine.engine_id
      }
      env {
        name  = "ASSISTANT_ID"
        value = var.assistant_id
      }
      env {
        name  = "PERMISSION_BACKEND"
        value = "firestore"
      }
      env {
        name  = "FIRESTORE_DATABASE"
        value = "(default)"
      }
      env {
        name  = "IDENTITY_SOURCE"
        value = var.identity_source
      }
      env {
        name  = "BQ_LOGGING"
        value = "on"
      }
      env {
        name  = "BQ_DATASET"
        value = google_bigquery_dataset.logs.dataset_id
      }
    }
  }

  # Cloud Build pushes the real image and updates it out-of-band.
  lifecycle {
    ignore_changes = [template[0].containers[0].image]
  }

  depends_on = [google_project_service.apis, google_firestore_database.default,
  google_discovery_engine_search_engine.engine]
}

# IAP service agent invokes the Cloud Run service on the authenticated user's behalf.
resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = google_project_service_identity.iap_sa.member
}

# End users allowed through IAP.
resource "google_iap_web_cloud_run_service_iam_member" "accessor" {
  for_each               = toset(var.iap_members)
  project                = var.project_id
  location               = var.region
  cloud_run_service_name = google_cloud_run_v2_service.app.name
  role                   = "roles/iap.httpsResourceAccessor"
  member                 = each.value
  depends_on             = [time_sleep.wait_service_agents]
}

# --- Cloud Run job (data ingestion) -----------------------------------------
resource "google_cloud_run_v2_job" "ingest" {
  project             = var.project_id
  name                = "ge-search-ingest"
  location            = var.region
  deletion_protection = false

  template {
    task_count  = var.ingest_task_count
    parallelism = var.ingest_parallelism
    template {
      service_account = google_service_account.ingest.email
      timeout         = "3600s"
      max_retries     = 1
      containers {
        image   = local.placeholder_image
        command = ["sh", "/app/scripts/ingest_entrypoint.sh"]
        resources {
          limits = { cpu = "2", memory = "2Gi" }
        }
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "PROJECT_NUMBER"
          value = data.google_project.this.number
        }
        env {
          name  = "LOCATION"
          value = var.location
        }
        env {
          name  = "DATA_STORE_ID"
          value = var.data_store_id
        }
        env {
          name  = "GCS_BUCKET"
          value = "gs://${local.bucket_name}"
        }
        env {
          name  = "FIRESTORE_DATABASE"
          value = "(default)"
        }
        env {
          name  = "INGEST_LIMIT"
          value = var.ingest_limit
        }
        env {
          name  = "EDGAR_FORMS"
          value = var.edgar_forms
        }
        env {
          name  = "BQ_LOGGING"
          value = "on"
        }
        env {
          name  = "BQ_DATASET"
          value = google_bigquery_dataset.logs.dataset_id
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  depends_on = [google_project_service.apis, google_discovery_engine_data_store.ds]
}

# --- Cloud Run job (incremental reconcile: Firestore catalog -> VAIS) --------
# Idempotent: handles both initial load and ongoing deltas. Triggered by Cloud
# Scheduler (scheduler.tf). Reuses the ingest SA (editor + datastore + storage + BQ).
resource "google_cloud_run_v2_job" "reconcile" {
  project             = var.project_id
  name                = "ge-search-reconcile"
  location            = var.region
  deletion_protection = false

  template {
    template {
      service_account = google_service_account.ingest.email
      timeout         = "1800s"
      max_retries     = 1
      containers {
        image   = local.placeholder_image
        command = ["python3", "/app/scripts/reconcile.py"]
        resources { limits = { cpu = "1", memory = "1Gi" } }
        env {
          name  = "PROJECT_ID"
          value = var.project_id
        }
        env {
          name  = "LOCATION"
          value = var.location
        }
        env {
          name  = "DATA_STORE_ID"
          value = var.data_store_id
        }
        env {
          name  = "GCS_BUCKET"
          value = "gs://${local.bucket_name}"
        }
        env {
          name  = "FIRESTORE_DATABASE"
          value = "(default)"
        }
        env {
          name  = "BQ_LOGGING"
          value = "on"
        }
        env {
          name  = "BQ_DATASET"
          value = google_bigquery_dataset.logs.dataset_id
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image]
  }

  depends_on = [google_project_service.apis, google_discovery_engine_data_store.ds]
}
