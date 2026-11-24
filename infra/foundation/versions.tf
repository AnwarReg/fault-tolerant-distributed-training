terraform {
  required_version = ">= 1.14.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2.0"
    }
  }

  # Set the bucket name at init time after bootstrap creates it.
  backend "gcs" {
    prefix = "final-project/foundation"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}
