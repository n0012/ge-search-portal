# Vertex AI Search data store (created empty; the ingest Cloud Run Job imports docs).
# Layout parsing + layout-based chunking improve retrieval/grounding on PDFs.
resource "google_discovery_engine_data_store" "ds" {
  location                    = var.location
  data_store_id               = var.data_store_id
  display_name                = "GE Search Demo"
  industry_vertical           = "GENERIC"
  content_config              = "CONTENT_REQUIRED"
  solution_types              = ["SOLUTION_TYPE_SEARCH"]
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
