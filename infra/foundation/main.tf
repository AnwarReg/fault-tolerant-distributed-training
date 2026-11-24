# The custom VPC has no inherited default-network SSH rules.
resource "google_compute_network" "project" {
  name                    = "training-vpc"
  auto_create_subnetworks = false
}

# Private Google Access lets the coordinator use Google APIs without a public IP.
resource "google_compute_subnetwork" "coordinator" {
  name                     = "coordinator-subnet"
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.project.id
  private_ip_google_access = true
}

# Only IAP's proxy range may reach SSH on the coordinator VM.
resource "google_compute_firewall" "iap_ssh" {
  name          = "training-allow-iap-ssh"
  network       = google_compute_network.project.name
  direction     = "INGRESS"
  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["coordinator"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

# The VM receives a dedicated identity for its Google Cloud API calls.
resource "google_service_account" "coordinator" {
  account_id   = "training-coordinator"
  display_name = "Distributed training coordinator"
}

# Model versions and checkpoints live outside the VM so they survive its restart.
resource "google_storage_bucket" "training_artifacts" {
  name                        = var.artifact_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false
}

# Grant object access on this bucket only, rather than across the whole project.
resource "google_storage_bucket_iam_member" "coordinator_artifacts" {
  bucket = google_storage_bucket.training_artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.coordinator.email}"
}

# The coordinator only needs CPU and memory, since workers train the model.
resource "google_compute_instance" "coordinator" {
  name         = "training-coordinator"
  machine_type = var.machine_type
  zone         = var.zone
  tags         = ["coordinator"]

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 20
    }
  }

  # Omitting access_config keeps the VM off the public internet.
  network_interface {
    subnetwork = google_compute_subnetwork.coordinator.id
  }

  service_account {
    email  = google_service_account.coordinator.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin = "TRUE"
    startup-script = templatefile("${path.module}/startup.sh.tftpl", {
      app_b64     = filebase64("${path.module}/../../coordinator/app.py")
      core_b64    = filebase64("${path.module}/../../coordinator/core.py")
      gcp_b64     = filebase64("${path.module}/../../coordinator/gcp.py")
      service_b64 = filebase64("${path.module}/../../coordinator/training-coordinator.service")
      bucket      = google_storage_bucket.training_artifacts.name
      ca_pool     = var.enable_edge ? google_privateca_ca_pool.workers[0].id : ""
    })
  }
}
