output "state_bucket_name" {
  description = "Use this name to configure the foundation GCS backend."
  value       = google_storage_bucket.terraform_state.name
}
