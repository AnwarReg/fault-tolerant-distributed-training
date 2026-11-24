# Final project plan: fault-tolerant distributed training

## Goal

Build and explain a distributed training system that keeps making progress when workers disappear or slow down. The coordinator runs on a Google Cloud VM; workers run on our laptops and, later, lab machines or Docker containers. Terraform defines the cloud infrastructure. The project should be easy to run, test, observe, and demonstrate.

## What the system does

1. The coordinator publishes a numbered model version and assigns distinct CIFAR-10 data shards to workers.
2. Each worker downloads that version, trains a small CNN for a fixed number of local steps, and uploads its result.
3. The coordinator accepts results for the current round, combines them using a data-size-weighted average, saves a new model version, and starts the next round.
4. Workers poll for assignments and send heartbeats. A worker can leave and later rejoin without stopping the others.

The coordinator owns the round and model version. Cloud Storage holds model files, updates, and the coordinator checkpoint. Taha can build the ML trainer while the infrastructure and API are developed against a dummy worker that returns small placeholder results.

## Target cloud design

```text
Workers on laptops / lab PCs / Docker
           | HTTPS + worker client certificate
           v
Public HTTPS Application Load Balancer (mTLS)
           |
           v
Private Compute Engine coordinator VM (no public IP)
           |                    |
           v                    v
Cloud Storage artifact bucket
model versions, updates, and coordinator checkpoint

Developer SSH -> IAP -> private VM
```

Terraform defines the custom VPC, subnet, firewall rules, service accounts and IAM, bucket, VM, load balancer, certificates and trust configuration. Keep certificate private keys and other secrets out of Git and Terraform state. The VM uses Private Google Access for Google APIs. Add Cloud NAT only if the VM needs outbound access to the public internet, such as downloading packages from public repositories. Use one region and one zone initially; this is coordinator process/VM restart recovery, not zone-level high availability. IAP provides SSH and file-copy access for development and troubleshooting. The VM startup script installs and starts the coordinator on boot.

## Four-week build plan

| Time | Build | Demonstration that proves it works |
| --- | --- | --- |
| Week 1 | Confirm billing/trial and cost controls; bootstrap Terraform state; create custom VPC/subnet, private VM, IAP SSH rule, VM service account, and Cloud Storage bucket. Run a dummy coordinator on the VM. In parallel, Taha develops the small CNN baseline and worker update format. | SSH to the VM through IAP, verify no public VM IP, and run the dummy coordinator's health check on the VM. |
| Week 2 | Add HTTPS load balancer, backend health check, worker mTLS, and a repeatable coordinator deployment. Connect dummy workers from laptops; integrate Taha's real trainer when it is ready. | An authorized dummy worker completes one round through the public endpoint; an unauthorized client is rejected. Then run a real two-worker round if the trainer is ready. |
| Week 3 | Heartbeats, round deadlines, duplicate result handling, worker rejoin, and checkpoint-based coordinator restart. | Kill a worker mid-round, restart it, then restart the coordinator; training resumes without losing the last committed round. |
| Week 4 | Repeatable failure experiments, metrics/logs, clean deployment instructions, architecture diagram, demo video, and results. | Run the same failure schedule twice and report training progress, recovery time, worker dropouts, and model accuracy. |

If time remains: compare sync intervals; reject NaN or extreme updates; add automated rollback; compare with PyTorch DDP/torchft. TinyStories is a stretch goal. Avoid spending the core month on it.

## Engineering rules for a strong portfolio project

- Keep a clear protocol: `register`, `get assignment`, `heartbeat`, `submit result`, `get model version`. Define round IDs and model versions in every message.
- Make result submission safe to retry. An update for an old round or a duplicate submission cannot be applied twice.
- Save a committed checkpoint before announcing the next round. Record enough state to reconstruct the current round after coordinator restart.
- Record worker ID, round ID, model version, timestamps, status, and errors in structured logs. Collect simple metrics for live workers, completed rounds, accuracy, and recovery time.
- Use a fixed data split, random seed, model definition, and training budget in comparisons. Run a single-worker baseline so the distributed result has context.
- Keep cloud creation and teardown documented. Review `terraform plan` before applying. Do not commit credentials, private keys, state files, or large datasets/checkpoints.
- Show a diagram, a short live failure demo, Terraform layout, reproducible commands, measured results, limits, and cost in the final README.

## First implementation milestone

Build the **cloud foundation and a dummy coordinator** while the ML trainer is being developed:

1. Confirm the GCP trial/billing account and create a dedicated project. Set cost controls. Choose one region, one zone, and non-overlapping subnet ranges.
2. Bootstrap a separate, versioned Cloud Storage bucket for Terraform state. Keep this bootstrap step documented because the backend bucket must exist before Terraform can store state there.
3. Write a small Terraform root configuration with pinned provider version, project/region variables, VPC, subnet with Private Google Access, and a private VM. Add only the firewall rule needed for IAP SSH. Give the VM its own service account.
4. Apply it, inspect the resources in GCP, and connect with IAP. Confirm the VM has no external IP. Add the application bucket and the VM's limited bucket permissions.
5. Run a dummy HTTP coordinator with a `/health` endpoint on the VM. Later add `get assignment` and `submit result` endpoints that exchange round IDs and placeholder values. The actual ML model can replace the dummy result without changing the network design.

For the first Terraform change, stop after the VPC, subnet, VM, and IAP access work. Add the load balancer and mTLS only after that foundation is understandable and verifiable. Do not expose the coordinator VM directly to the internet to test the API.

## Terraform study order

1. **Quick refresh:** provider, resource, data, variable, local, output, and module blocks; references, `plan`, and state. You already know much of the AWS equivalent.
2. **GCP identity:** Application Default Credentials for your machine, service accounts for the VM, IAM roles with only required permissions, and service account impersonation.
3. **GCP networking:** project/region/zone, VPC, regional subnet and CIDR, routes, firewall rules, internal/external IPs, load balancer backends and health checks, Private Google Access, Cloud NAT, and IAP. Map each to familiar AWS concepts while noting different behavior.
4. **Modules in depth:** root versus child module; inputs, outputs, module scope, composition, versioning, and what belongs in a module. Build the first few resources in a readable root configuration, then extract a `network` module once its inputs and outputs are clear. Keep the module tree flat.
5. **State:** remote GCS backend, locking, versioning, drift, imports, and why state can contain sensitive values.
6. **TLS and secrets:** server TLS versus worker client certificates, CA and trust store, certificate rotation, secret storage, and why private keys must not enter state or Git.
7. **Quality checks:** `fmt`, `validate`, reviewable `plan`, and a small CI check. Document `apply` and `destroy` separately from automatic CI.

## Cloud cost and teardown

Confirm the trial is actually active and the billing account attached to the intended project before creating resources. Set a low project budget/spend control and inspect the pricing estimate for the load balancer, VM, CA Service, and storage. Budget alert behavior and spend-cap availability should be checked in the account. Use Terraform to destroy temporary resources after experiments, and perform a final billing/resource check at semester end. Preserve exported results and diagrams locally before teardown.
