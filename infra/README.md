# Terraform: cloud foundation and worker edge

The foundation has now been extended with a reserved public IP, HTTPS load balancer, worker mTLS, Google CA Service, and boot-time coordinator installation. See DEPLOY.md for the staged apply and demo commands. The original first-milestone notes below explain why the state bucket and private VM were created separately.

The first milestone created a custom VPC, regional subnet, private coordinator VM, VM service account, model-artifact bucket, and SSH firewall rule restricted to IAP. The service account can manage objects in the model-artifact bucket. The later edge stage adds the public load balancer and narrowly scoped certificate-request permission.

## Before applying

1. Confirm that the chosen GCP project has billing enabled and check the trial status. Set a project budget or spend control.
2. Install Terraform and gcloud, then sign in with `gcloud auth login` and `gcloud auth application-default login` from your own terminal. Never commit credential files.
3. Choose an existing project ID, globally unique names for the state and model-artifact buckets, and a region/zone. The examples use `us-east1` and `us-east1-b`.
4. Enable the Compute Engine, IAM, and Cloud Storage APIs in that project. The account applying Terraform needs permission to create the resources and use IAP/OS Login.

## Bootstrap state storage

The GCS backend requires an existing bucket. `bootstrap` uses local state to create that bucket, then `foundation` uses the bucket for remote state. Keep the bootstrap state file backed up securely; it is ignored by Git. Do not destroy this bucket while `foundation` still uses it.

From `infra/bootstrap`:

```powershell
terraform init
terraform fmt -check
terraform validate
terraform plan -var="project_id=YOUR_PROJECT_ID" -var="state_bucket_name=YOUR_GLOBALLY_UNIQUE_BUCKET"
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="state_bucket_name=YOUR_GLOBALLY_UNIQUE_BUCKET"
```

## Create the foundation

From `infra/foundation`:

```powershell
terraform init -backend-config="bucket=YOUR_GLOBALLY_UNIQUE_BUCKET"
terraform fmt -check
terraform validate
terraform plan -var="project_id=YOUR_PROJECT_ID" -var="artifact_bucket_name=YOUR_UNIQUE_ARTIFACT_BUCKET"
terraform apply -var="project_id=YOUR_PROJECT_ID" -var="artifact_bucket_name=YOUR_UNIQUE_ARTIFACT_BUCKET"
```

Review each plan before applying it. Afterward, check the VM in the console: its external IP should be empty. With appropriate IAP and OS Login permissions, connect using:

```powershell
gcloud compute ssh training-coordinator --project YOUR_PROJECT_ID --zone us-east1-b --tunnel-through-iap
```

IAP is for administration. We can use `gcloud compute scp --tunnel-through-iap` to copy the first dummy coordinator, then make deployment repeatable with a startup script and service unit. The private VM will not be able to download arbitrary public packages without an outbound path such as Cloud NAT; Private Google Access covers Google APIs and Cloud Storage. The model-artifact bucket is distinct from the Terraform state bucket. Store checkpoints under distinct round or model-version names; object versioning is not enabled on this bucket.

## Current recovery storage

The dummy coordinator now saves its active round and worker records as one object in the artifact bucket. This is sufficient for the planned two-worker demo.
