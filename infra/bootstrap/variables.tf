variable "project_id" {
  description = "Existing GCP project ID with billing enabled."
  type        = string
}

variable "region" {
  description = "Region for the Terraform state bucket."
  type        = string
  default     = "us-east1"
}

variable "state_bucket_name" {
  description = "Globally unique name of the Terraform state bucket."
  type        = string
}
