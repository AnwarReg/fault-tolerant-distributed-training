# Reserve the public address first; the locally generated server certificate uses it as an IP SAN.
resource "google_compute_global_address" "worker_edge" {
  name = "training-worker-edge"
}

# Only Google's frontend and health probes can reach the two application ports.
resource "google_compute_firewall" "lb_backends" {
  count         = var.enable_edge ? 1 : 0
  name          = "training-allow-lb-backends"
  network       = google_compute_network.project.name
  direction     = "INGRESS"
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
  target_tags   = ["coordinator"]

  allow {
    protocol = "tcp"
    ports    = ["8000", "8001"]
  }
}

# CA Service holds the signing key; Terraform state contains only the public CA certificate.
resource "google_privateca_ca_pool" "workers" {
  count    = var.enable_edge ? 1 : 0
  name     = "training-workers"
  location = var.region
  tier     = "DEVOPS"

  publishing_options {
    publish_ca_cert = true
    publish_crl     = false
  }

  issuance_policy {
    maximum_lifetime = "604800s"
    allowed_issuance_modes {
      allow_csr_based_issuance    = true
      allow_config_based_issuance = false
    }
    baseline_values {
      ca_options {
        is_ca = false
      }
      key_usage {
        base_key_usage {
          digital_signature = true
        }
        extended_key_usage {
          client_auth = true
        }
      }
    }
  }
}

resource "google_privateca_certificate_authority" "worker_root" {
  count                                  = var.enable_edge ? 1 : 0
  pool                                   = google_privateca_ca_pool.workers[0].name
  location                               = var.region
  certificate_authority_id               = "training-worker-root"
  type                                   = "SELF_SIGNED"
  lifetime                               = "31536000s"
  deletion_protection                    = false
  ignore_active_certificates_on_deletion = true
  skip_grace_period                      = true

  config {
    subject_config {
      subject {
        organization = "Distributed Training Project"
        common_name  = "Training Worker Root"
      }
    }
    x509_config {
      ca_options {
        is_ca = true
      }
      key_usage {
        base_key_usage {
          cert_sign = true
          crl_sign  = true
        }
        extended_key_usage {}
      }
    }
  }
  key_spec {
    algorithm = "RSA_PKCS1_4096_SHA256"
  }
}

# The coordinator may issue short-lived worker certificates but cannot administer the CA.
resource "google_privateca_ca_pool_iam_member" "issuer" {
  count   = var.enable_edge ? 1 : 0
  ca_pool = google_privateca_ca_pool.workers[0].id
  role    = "roles/privateca.certificateRequester"
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

data "google_project" "current" {
  count      = var.enable_edge ? 1 : 0
  project_id = var.project_id
}

resource "google_certificate_manager_trust_config" "workers" {
  count    = var.enable_edge ? 1 : 0
  name     = "training-worker-trust"
  location = "global"
  trust_stores {
    trust_anchors {
      pem_certificate = google_privateca_certificate_authority.worker_root[0].pem_ca_certificates[0]
    }
  }
}

resource "google_network_security_server_tls_policy" "workers" {
  count      = var.enable_edge ? 1 : 0
  name       = "training-require-worker-cert"
  location   = "global"
  allow_open = false
  mtls_policy {
    client_validation_mode         = "REJECT_INVALID"
    client_validation_trust_config = "projects/${data.google_project.current[0].number}/locations/global/trustConfigs/${google_certificate_manager_trust_config.workers[0].name}"
  }
}

# One zonal instance group exposes two named ports on the same private VM.
resource "google_compute_instance_group" "coordinator" {
  count     = var.enable_edge ? 1 : 0
  name      = "training-coordinator-backends"
  zone      = var.zone
  instances = [google_compute_instance.coordinator.id]
  named_port {
    name = "worker"
    port = 8000
  }
  named_port {
    name = "enrollment"
    port = 8001
  }
}

resource "google_compute_health_check" "worker" {
  count = var.enable_edge ? 1 : 0
  name  = "training-worker-health"
  http_health_check {
    port         = 8000
    request_path = "/health"
  }
}

resource "google_compute_health_check" "enrollment" {
  count = var.enable_edge ? 1 : 0
  name  = "training-enrollment-health"
  http_health_check {
    port         = 8001
    request_path = "/health"
  }
}

resource "google_compute_backend_service" "worker" {
  count                  = var.enable_edge ? 1 : 0
  name                   = "training-worker-backend"
  protocol               = "HTTP"
  port_name              = "worker"
  load_balancing_scheme  = "EXTERNAL_MANAGED"
  timeout_sec            = 30
  health_checks          = [google_compute_health_check.worker[0].id]
  custom_request_headers = ["X-Worker-Cert-Fingerprint:{client_cert_sha256_fingerprint}"]
  log_config {
    enable      = true
    sample_rate = 1.0
  }
  backend {
    group = google_compute_instance_group.coordinator[0].id
  }
}

resource "google_compute_backend_service" "enrollment" {
  count                 = var.enable_edge ? 1 : 0
  name                  = "training-enrollment-backend"
  protocol              = "HTTP"
  port_name             = "enrollment"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  timeout_sec           = 30
  health_checks         = [google_compute_health_check.enrollment[0].id]
  log_config {
    enable      = true
    sample_rate = 1.0
  }
  backend {
    group = google_compute_instance_group.coordinator[0].id
  }
}

# Separate HTTPS proxies keep the public invitation route reachable before mTLS enrollment.
resource "google_compute_url_map" "worker" {
  count           = var.enable_edge ? 1 : 0
  name            = "training-worker-routes"
  default_service = google_compute_backend_service.worker[0].id
}

resource "google_compute_url_map" "enrollment" {
  count           = var.enable_edge ? 1 : 0
  name            = "training-enrollment-routes"
  default_service = google_compute_backend_service.enrollment[0].id
}

locals {
  server_certificate_url = "projects/${var.project_id}/global/sslCertificates/${var.server_certificate_name}"
}

resource "google_compute_target_https_proxy" "worker" {
  count             = var.enable_edge ? 1 : 0
  name              = "training-worker-https"
  url_map           = google_compute_url_map.worker[0].id
  ssl_certificates  = [local.server_certificate_url]
  server_tls_policy = google_network_security_server_tls_policy.workers[0].id
}

resource "google_compute_target_https_proxy" "enrollment" {
  count            = var.enable_edge ? 1 : 0
  name             = "training-enrollment-https"
  url_map          = google_compute_url_map.enrollment[0].id
  ssl_certificates = [local.server_certificate_url]
}

resource "google_compute_global_forwarding_rule" "worker" {
  count                 = var.enable_edge ? 1 : 0
  name                  = "training-worker-443"
  ip_address            = google_compute_global_address.worker_edge.address
  port_range            = "443"
  target                = google_compute_target_https_proxy.worker[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_compute_global_forwarding_rule" "enrollment" {
  count                 = var.enable_edge ? 1 : 0
  name                  = "training-enrollment-8443"
  ip_address            = google_compute_global_address.worker_edge.address
  port_range            = "8443"
  target                = google_compute_target_https_proxy.enrollment[0].id
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
