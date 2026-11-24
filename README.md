# Fault-Tolerant Distributed Training

A small distributed training system built for a distributed systems course. A coordinator runs on a private Google Cloud VM while workers run on laptops or lab machines. The current worker performs a deterministic dummy task; the ML training step is still being developed.

## How it works

    Worker laptops
        | HTTPS + worker certificate
        v
    Google Cloud load balancer
        |
        v
    Private coordinator VM
        |
        v
    Cloud Storage artifact bucket

The coordinator assigns numbered rounds, accepts worker updates, tracks heartbeats, combines available updates after two results or a deadline, and saves its state to Cloud Storage. A restarted coordinator loads that state and continues. One-time invitations enroll workers for client certificates through Google Certificate Authority Service.

The VM has no public IP. IAP and OS Login provide administrative SSH access. Terraform defines the network, VM, bucket, load balancer, firewall rules, and certificate trust configuration.

## Repository layout

| Path | Purpose |
| --- | --- |
| coordinator/ | HTTP API, round logic, Google API adapters, and service unit |
| worker/ | Dummy worker enrollment and task loop |
| infra/bootstrap/ | Terraform for the remote-state bucket |
| infra/foundation/ | Terraform for the private VM and HTTPS worker edge |
| infra/DEPLOY.md | Staged deployment, worker enrollment, failure demo, and teardown |
| PLAN.md | Project scope and roadmap |

## Current scope

The coordinator and worker code are a runnable prototype, not a trained ML model. The existing private VM foundation has been applied; the new HTTPS edge and managed worker CA still require deployment and a live end-to-end check. The project targets two workers and light training. Cloud Storage holds the coordinator checkpoint and will hold model files; no SQL database is required for this scope.

The system handles a missing worker by completing a round after a deadline. It can recover after a coordinator process or VM restart once the VM is running again. It does not automatically replace a stopped VM or provide zero-downtime coordinator failover.

## Local checks

From the repository root:

    python -m unittest discover -s coordinator -p test_core.py
    terraform -chdir=infra/foundation fmt -check
    terraform -chdir=infra/foundation validate

See [infra/DEPLOY.md](infra/DEPLOY.md) before creating paid cloud resources. Keep Terraform state, credentials, and certificate private keys out of Git.
