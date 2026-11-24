output "coordinator_name" {
  description = "VM name for IAP SSH."
  value       = google_compute_instance.coordinator.name
}

output "coordinator_internal_ip" {
  description = "Private IP; no external VM IP is created."
  value       = google_compute_instance.coordinator.network_interface[0].network_ip
}

output "vpc_name" {
  description = "Custom network created by this foundation."
  value       = google_compute_network.project.name
}

output "artifact_bucket_name" {
  description = "Bucket for model versions, updates, and checkpoints."
  value       = google_storage_bucket.training_artifacts.name
}

output "worker_endpoint_ip" {
  description = "Reserved global IP for the HTTPS worker and enrollment frontends."
  value       = google_compute_global_address.worker_edge.address
}

output "worker_ca_certificate" {
  description = "Public CA certificate to inspect or distribute; no private key is exposed."
  value       = var.enable_edge ? google_privateca_certificate_authority.worker_root[0].pem_ca_certificates[0] : null
}
