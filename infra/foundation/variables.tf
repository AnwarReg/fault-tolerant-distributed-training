variable "project_id" {
  description = "Existing GCP project ID with billing enabled."
  type        = string
}

variable "artifact_bucket_name" {
  description = "Globally unique name for model versions, updates, and checkpoints."
  type        = string
}

variable "region" {
  description = "Region containing the coordinator subnet."
  type        = string
  default     = "us-east1"
}

variable "zone" {
  description = "Zone containing the coordinator VM."
  type        = string
  default     = "us-east1-b"
}

variable "subnet_cidr" {
  description = "Private IPv4 range for the coordinator subnet."
  type        = string
  default     = "10.42.0.0/24"
}

variable "machine_type" {
  description = "Small VM size for the coordinator; it does not train the model."
  type        = string
  default     = "e2-small"
}

variable "enable_edge" {
  description = "Create the public HTTPS load balancer and worker CA after uploading the IP certificate."
  type        = bool
  default     = false
}

variable "server_certificate_name" {
  description = "Name of the separately uploaded self-managed certificate for the reserved IP."
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_edge || length(var.server_certificate_name) > 0
    error_message = "Set server_certificate_name when enable_edge is true."
  }
}
