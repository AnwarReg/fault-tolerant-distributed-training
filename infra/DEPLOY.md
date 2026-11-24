# Deployment and demo

This extends the existing private VM foundation. It reserves a public IP, deploys two HTTPS frontends, creates a Google managed worker CA, and installs the dummy coordinator as a systemd service on VM boot.

## Network paths

| Purpose | Path | Gate |
| --- | --- | --- |
| Admin SSH | IAP to VM port 22 | IAM, OS Login, SSH key |
| Worker API | Load balancer port 443 to VM port 8000 | Worker mTLS certificate |
| Enrollment | Load balancer port 8443 to VM port 8001 | One-time token and CSR |
| Admin API | VM loopback port 8002 | IAP SSH session |
| Restart state | GCS artifact bucket | VM service account |

The VM has no external IP. Only Google frontend and health check ranges can reach ports 8000 and 8001. The IP-address server certificate is self-signed because this project has no domain. Workers explicitly trust it. It expires after 30 days.

## Prerequisites

Use the same GCP project and state bucket as the existing foundation. Install Terraform, gcloud, OpenSSL, and Python 3. Sign in with gcloud auth login and gcloud auth application-default login. Enable compute.googleapis.com, iam.googleapis.com, storage.googleapis.com, privateca.googleapis.com, certificatemanager.googleapis.com, and networksecurity.googleapis.com. Your Terraform account must be allowed to create these resources and manage CA pool IAM.

## Stage 1: reserve the IP and configure the VM

Run PowerShell from final_project/infra/foundation. Keep using your own project ID locally.

    $projectId = gcloud config get-value project
    $stateBucket = terraform -chdir=../bootstrap output -raw state_bucket_name
    terraform init -backend-config="bucket=$stateBucket"
    $artifactBucket = terraform output -raw artifact_bucket_name
    terraform fmt -check
    terraform validate
    terraform plan -var="project_id=$projectId" -var="artifact_bucket_name=$artifactBucket" -out=stage1.tfplan
    terraform apply stage1.tfplan
    $edgeIp = terraform output -raw worker_endpoint_ip

Inspect the plan for unexpected VM replacement before applying. If the artifact bucket output cannot be read, use the exact bucket name from your original foundation apply. The startup script installs the bundled Python files and service at VM boot. Apply the metadata update, then restart the VM with:

    gcloud compute instances reset training-coordinator --zone=us-east1-b --project=$projectId

The reset interrupts the current SSH session. Reconnect using IAP and check sudo systemctl status training-coordinator.

## Stage 2: upload the IP server certificate

From the same directory:

    .\create-ip-certificate.ps1 -ProjectId $projectId -IpAddress $edgeIp

The script creates .local/server.crt and .local/server.key and uploads them directly to a Compute Engine SSL certificate resource named training-server-ip. The private key stays out of Terraform state and Git. Never send server.key to a worker. If OpenSSL is not on PATH, invoke it by full path.

## Stage 3: turn on the HTTPS edge and worker CA

    terraform plan -var="project_id=$projectId" -var="artifact_bucket_name=$artifactBucket" -var="enable_edge=true" -var="server_certificate_name=training-server-ip" -out=stage3.tfplan
    terraform apply stage3.tfplan
    gcloud compute instances reset training-coordinator --zone=us-east1-b --project=$projectId

The second reset gives the coordinator its CA pool setting. Wait for both load balancer backend services to become healthy. The endpoints are https://IP on port 443 for workers and https://IP:8443 for enrollment.

## Enroll and run

SSH into the VM through IAP. Create one invitation per worker on the VM:

    curl -sS -X POST http://127.0.0.1:8002/admin/invitations -H 'Content-Type: application/json' -d '{"worker_id":"laptop-a"}'

The reply has a one-time token valid for ten minutes. On a worker laptop, from final_project:

    $edgeIp = terraform -chdir=infra/foundation output -raw worker_endpoint_ip
    python worker/worker.py enroll --url "https://${edgeIp}:8443" --server-cert infra/foundation/.local/server.crt --worker-id laptop-a --token 'PASTE_TOKEN' --cert laptop-a.crt --key laptop-a.key
    python worker/worker.py run --url "https://$edgeIp" --server-cert infra/foundation/.local/server.crt --cert laptop-a.crt --key laptop-a.key --rounds 3 --value 2

Copy only server.crt to Taha's laptop through a secure channel. Create a second invitation for laptop-b, enroll it there, and run with --value 4. Each worker creates its own private key. Keep each worker key private. For the local Docker demo, use the same procedure with unique IDs and mounted individual cert/key files.

The coordinator waits for two updates or 45 seconds, then computes a weighted scalar average. This is a dummy training update, ready for replacement by the ML worker code. On the VM, inspect curl http://127.0.0.1:8002/admin/status and sudo journalctl -u training-coordinator -n 100 --no-pager.

## Failure demo

1. Stop one worker process. The other can still submit. Once 45 seconds have passed, its next task request finishes the round without the missing worker.
2. Restart the stopped worker. Its next request makes it live again. Stale results are rejected.
3. Restart the coordinator VM. systemd starts the app again, and the app reloads state/coordinator.json from the artifact bucket.
4. Compare admin/status before and after. The round and last aggregate should survive.

This is restart recovery with one coordinator, not a zero-downtime coordinator cluster. The dummy worker retries temporary network and 502/503/504 failures, including an interrupted request during VM restart. Worker certificates last seven days; re-enrolling an existing worker ID is not automated yet. The single JSON checkpoint and serialized writes are suitable for this small demo, not a large worker fleet.

## Teardown

Destroy the edge resources with enable_edge=true and the same certificate name, then delete the uploaded SSL certificate. The artifact bucket has force_destroy=false: remove its checkpoint objects deliberately before destroying the foundation. The bootstrap state bucket has prevent_destroy=true and must be handled last.
