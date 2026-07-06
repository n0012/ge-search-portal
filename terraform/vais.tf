# Vertex AI Search data store (created empty; the ingest Cloud Run Job imports docs).
# Layout parsing + layout-based chunking improve retrieval/grounding on PDFs.
resource "google_discovery_engine_data_store" "ds" {
  location          = var.location
  data_store_id     = var.data_store_id
  display_name      = "GE Search Demo"
  industry_vertical = "GENERIC"
  content_config    = "CONTENT_REQUIRED"
  # Both: SEARCH for the faceted :search serving config, CHAT for the GE assistant
  # (app_type=APP_TYPE_INTRANET) :streamAssist surface. Must match the live data store so
  # Terraform never force-replaces it.
  solution_types              = ["SOLUTION_TYPE_SEARCH", "SOLUTION_TYPE_CHAT"]
  create_advanced_site_search = false

  document_processing_config {
    default_parsing_config {
      layout_parsing_config {}
    }
    chunking_config {
      layout_based_chunking_config {
        chunk_size                = 500
        include_ancestor_headings = true
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# Gemini Enterprise (Agentspace) app over the data store. CRITICAL for billing: Discovery Engine
# traffic is covered by the GE per-seat subscription ONLY when it queries a GE engine's serving
# config — querying the data store directly (or a non-GE VAIS engine) bills standalone (SKU
# 93D6-7280-CF05). So the app routes BOTH :search and the assistant (:streamAssist) at THIS engine
# (backend/config.py points SERVING_CONFIG + ASSISTANT_PATH here via ENGINE_ID).
#
# app_type = APP_TYPE_INTRANET makes this the **Gemini Enterprise Pro-tier Assistant** app (NOT a
# Dialogflow CX chat engine — no dialogflow.googleapis.com needed). Enterprise tier + the LLM
# add-on provision the assistant; the engine auto-creates `default_search` (faceted search) +
# `default_assistant` (:streamAssist) over the connected data store.
resource "google_discovery_engine_search_engine" "engine" {
  engine_id         = var.engine_id
  collection_id     = "default_collection"
  location          = google_discovery_engine_data_store.ds.location
  display_name      = "GE Search"
  industry_vertical = "GENERIC"
  app_type          = "APP_TYPE_INTRANET"
  data_store_ids    = [google_discovery_engine_data_store.ds.data_store_id]

  search_engine_config {
    search_tier    = "SEARCH_TIER_ENTERPRISE"
    search_add_ons = ["SEARCH_ADD_ON_LLM"]
  }
}
