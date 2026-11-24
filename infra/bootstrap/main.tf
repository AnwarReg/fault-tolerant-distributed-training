terraform {
  required_version = ">= 1.14.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 8.2.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# This bucket exists before the foundation can use a remote state backend.
resource "google_storage_bucket" "terraform_state" {
  name                        = var.state_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # Losing the backend bucket would also lose the foundation's state history.
  lifecycle {
    prevent_destroy = true
  }
}
