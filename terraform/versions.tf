terraform {
  required_version = ">= 1.5"
  required_providers {
    google      = { source = "hashicorp/google", version = ">= 5.30" }
    google-beta = { source = "hashicorp/google-beta", version = ">= 5.30" }
  }
  # State in GCS (bucket created by deploy-all.sh before `terraform init`).
  backend "gcs" {
    prefix = "ge-search-portal"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  # user ADC needs a quota project for APIs like discoveryengine
  user_project_override = true
  billing_project       = var.project_id
}

provider "google-beta" {
  project               = var.project_id
  region                = var.region
  user_project_override = true
  billing_project       = var.project_id
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  bucket_name = coalesce(var.bucket_name, "${var.project_id}-ge-search-corpus")
  # Placeholder image; Cloud Build pushes the real one and updates the service/job.
  placeholder_image = "us-docker.pkg.dev/cloudrun/container/hello"
}
