# App Deployment on GKE 

> A from‑scratch, production‑oriented guide to build, scan, sign, and deploy a Flask API to **Google Kubernetes Engine (GKE)** using **Artifact Registry** and **GitHub Actions** with **Workload Identity Federation** (no long‑lived keys). Includes resilience, security, automation, and rollback.

---

## Table of Contents
1. [What You’ll Build](#what-youll-build)
2. [Architecture at a Glance](#architecture-at-a-glance)
3. [Repository Structure](#repository-structure)
4. [Technology Stack](#technology-stack)
5. [End‑to‑End Flow](#end-to-end-flow)
6. [Prerequisites](#prerequisites)
7. [Quickstart (TL;DR)](#quickstart-tldr)
8. [Step-by-Step Setup](#step-by-step-setup)
   - [1) Google Cloud: Project & APIs](#1-google-cloud-project--apis)
   - [2) IAM for CI/CD (Service Account + WIF)](#2-iam-for-cicd-service-account--wif)
   - [3) Artifact Registry](#3-artifact-registry)
   - [4) Create GKE Cluster](#4-create-gke-cluster)
   - [5) Local Build, Tag, Push (optional)](#5-local-build-tag-push-optional)
   - [6) First Deploy to GKE](#6-first-deploy-to-gke)
   - [7) Verify & Test](#7-verify--test)
   - [8) GitHub Actions CI/CD](#8-github-actions-cicd)
9. [Progressive Delivery & Rollback](#progressive-delivery--rollback)
10. [Observability & Metrics](#observability--metrics)
11. [Security Hardening Notes](#security-hardening-notes)
12. [Troubleshooting](#troubleshooting)
13. [Cost Notes](#cost-notes)
14. [Cleanup](#cleanup)
15. [Git Commands](#git-commands)
16. [License](#license)

---

## What You’ll Build
A small **Flask** API packaged as a container and deployed to **GKE** with:
- **Rolling updates** (safe, zero‑downtime by default)
- **Autoscaling** via HPA
- **PDB** to maintain availability during node maintenance
- **NetworkPolicy** to restrict ingress
- **Supply chain security**: Trivy image scan + Cosign keyless signing
- **GitHub Actions** pipeline (Build → Scan → Sign → Deploy)

Endpoints:
- `GET /` → hello JSON
- `POST /enrich` with `{ "transactionId": "123" }` → mock enrichment
- `GET /healthz` → health checks (probes)
- `GET /metrics` → Prometheus metrics

---

## Architecture at a Glance
```
Developer → GitHub (push) ─┐
                          │  Build → Trivy scan → Cosign sign → Deploy
GitHub Actions (OIDC) ─────┼──────────────────────────────────────────────→ GCP
                          │                                           ┌──────────┐
                          │                                           │Artifact  │
                          │                                           │Registry  │
                          │                                           └────┬─────┘
                          │                                                │ (image)
                          │                                            ┌───▼─────┐
                          │           kubectl apply / set image        │  GKE    │
                          └────────────────────────────────────────────►│ cluster │
                                                                       └───┬─────┘
                                                                           │
                                                                       ┌───▼─────────┐
                                                                       │ Deployment  │
                                                                       │  + HPA + PDB│
                                                                       └───┬─────────┘
                                                                           │
                                                                       ┌───▼─────────┐
                                                                       │  Service    │ (LoadBalancer)
                                                                       └─────────────┘
```

---

## Repository Structure
```
.
├─ api.py                      # Flask app (JSON logging + Prometheus)
├─ requirements.txt            # Pinned Python deps
├─ Dockerfile                  # Non-root, slim, Gunicorn
├─ k8s-manifests.yaml          # Deployment, Service, HPA, PDB, NetworkPolicy, SA, NS
├─ .dockerignore               # Trim Docker context
├─ .gitignore                  # Keep repo clean
└─ .github/
   └─ workflows/
      └─ ci-cd-pipeline.yaml   # Build → Scan → Sign → Deploy
```

---

## Technology Stack
- **Google Kubernetes Engine (GKE)** for orchestration
- **Artifact Registry** for container images
- **GitHub Actions** for CI/CD
- **Trivy** for vulnerability scanning
- **Cosign (keyless)** for image signing
- **Flask + Gunicorn** app, **prometheus_client** for metrics

---

## End‑to‑End Flow
1. You push code to `main`.
2. Actions builds a new image, tags with commit SHA, and **pushes** to Artifact Registry.
3. Trivy **scans**; pipeline fails on HIGH/CRITICAL vulns.
4. Cosign **signs** the image using GitHub OIDC (no keys).
5. Pipeline **applies** manifests (idempotent) and **sets** the Deployment image to the new digest.
6. Kubernetes performs a **rolling update**; HPA/PDB ensure resilience.

---

## Prerequisites
- A GCP project with **billing enabled**
- **gcloud** (>= 445) and **kubectl** installed
- **Docker** installed and logged in locally
- GitHub repository for this code

> **Tip**: Authenticate gcloud: `gcloud auth login` and set defaults: `gcloud config set project <PROJECT_ID>`.

---

## Quickstart (TL;DR)
```bash
# 0) Set vars
PROJECT_ID=<YOUR_GCP_PROJECT_ID>
REGION=us-central1
ZONE=us-central1-c
CLUSTER=enrichment-api-cluster
REPO=docker-repo
IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/enrichment-api

# 1) Enable APIs
gcloud services enable container.googleapis.com artifactregistry.googleapis.com

# 2) Create cluster
gcloud container clusters create $CLUSTER --zone $ZONE

# 3) Create Artifact Registry
gcloud artifacts repositories create $REPO --repository-format=docker --location=$REGION

# 4) Build & push (optional if CI will do it)
gcloud auth configure-docker $REGION-docker.pkg.dev
docker build -t $IMAGE:v1.0.0 . && docker push $IMAGE:v1.0.0

# 5) Deploy
kubectl apply -f k8s-manifests.yaml
kubectl set image deploy/enrichment-api -n enrichment enrichment-api=$IMAGE:v1.0.0
kubectl rollout status deploy/enrichment-api -n enrichment

# 6) Test
SVC_IP=$(kubectl get svc enrichment-api -n enrichment -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
curl http://$SVC_IP/
```

---

## Step-by-Step Setup

### 1) Google Cloud: Project & APIs
```bash
gcloud config set project <YOUR_GCP_PROJECT_ID>
gcloud config set compute/zone <YOUR_GCP_ZONE>
gcloud services enable container.googleapis.com artifactregistry.googleapis.com
```

### 2) IAM for CI/CD (Service Account + WIF)
Use **Workload Identity Federation** so GitHub can deploy without storing keys.

1. **Create a service account** (name it `gh-actions-deployer`):
   ```bash
   gcloud iam service-accounts create gh-actions-deployer      --display-name="GitHub Actions deployer"
   ```
2. **Grant minimum roles** (tighten later as needed):
   ```bash
   PROJECT_ID=$(gcloud config get-value project)
   SA=gh-actions-deployer@${PROJECT_ID}.iam.gserviceaccount.com
   gcloud projects add-iam-policy-binding $PROJECT_ID      --member="serviceAccount:$SA" --role="roles/artifactregistry.writer"
   gcloud projects add-iam-policy-binding $PROJECT_ID      --member="serviceAccount:$SA" --role="roles/container.developer"
   gcloud projects add-iam-policy-binding $PROJECT_ID      --member="serviceAccount:$SA" --role="roles/container.clusterViewer"
   gcloud projects add-iam-policy-binding $PROJECT_ID      --member="serviceAccount:$SA" --role="roles/iam.serviceAccountTokenCreator"
   ```
3. **Create a Workload Identity Pool + Provider** (once per org/account):
   ```bash
   POOL="github-pool"
   PROV="github-provider"
   gcloud iam workload-identity-pools create $POOL      --location="global" --display-name="GitHub OIDC Pool"

   gcloud iam workload-identity-pools providers create-oidc $PROV      --location="global" --workload-identity-pool=$POOL      --display-name="GitHub OIDC"      --issuer-uri="https://token.actions.githubusercontent.com"      --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref"
   ```
4. **Allow your repo to impersonate the SA** (replace org/repo):
   ```bash
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
   WIP=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL

   gcloud iam service-accounts add-iam-policy-binding $SA      --role="roles/iam.workloadIdentityUser"      --member="principalSet://$WIP/attribute.repository=<YOUR_GITHUB_ORG>/<YOUR_REPO>"
   ```
5. **Record values for GitHub Secrets**:
   - `GCP_PROJECT_ID` → `$PROJECT_ID`
   - `GCP_SERVICE_ACCOUNT` → `$SA`
   - `GCP_WORKLOAD_IDENTITY_PROVIDER` → `projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/$POOL/providers/$PROV`

> You may scope by `attribute.ref=refs/heads/main` to restrict to main branch only.

### 3) Artifact Registry
```bash
REGION=us-central1
REPO=docker-repo
gcloud artifacts repositories create $REPO   --repository-format=docker --location=$REGION   --description="Docker repository for enrichment-api"

# Configure Docker to push
gcloud auth configure-docker $REGION-docker.pkg.dev
```

### 4) Create GKE Cluster
```bash
ZONE=us-central1-c
CLUSTER=enrichment-api-cluster

# Creates a standard cluster (you can use Autopilot if preferred)
gcloud container clusters create $CLUSTER --zone $ZONE

# Kubeconfig
gcloud container clusters get-credentials $CLUSTER --zone $ZONE
```

### 5) Local Build, Tag, Push (optional)
> CI will do this automatically; do it once manually if you want an initial image.
```bash
PROJECT_ID=$(gcloud config get-value project)
REGION=us-central1
REPO=docker-repo
IMAGE=$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/enrichment-api

docker build -t $IMAGE:v1.0.0 .
docker push $IMAGE:v1.0.0
```

### 6) First Deploy to GKE
- Ensure `k8s-manifests.yaml` is present (namespace, SA, Deployment, Service, HPA, PDB, NetworkPolicy).
- If you built manually, set image to your tag; CI will set it to commit SHA later.

```bash
kubectl apply -f k8s-manifests.yaml
kubectl set image deployment/enrichment-api -n enrichment   enrichment-api=$IMAGE:v1.0.0
kubectl rollout status deployment/enrichment-api -n enrichment
```

### 7) Verify & Test
```bash
# Pods & events
kubectl get pods -n enrichment -o wide
kubectl describe deploy/enrichment-api -n enrichment

# External IP
kubectl get svc enrichment-api -n enrichment
SVC_IP=$(kubectl get svc enrichment-api -n enrichment -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Smoke tests
curl http://$SVC_IP/
curl -X POST http://$SVC_IP/enrich -H 'Content-Type: application/json' -d '{"transactionId":"abc-123"}'
```

### 8) GitHub Actions CI/CD
1. Commit and push this repository.
2. In GitHub → **Settings → Secrets and variables → Actions**, add:
   - `GCP_PROJECT_ID`
   - `GCP_SERVICE_ACCOUNT`
   - `GCP_WORKLOAD_IDENTITY_PROVIDER`
3. Review `.github/workflows/ci-cd-pipeline.yaml` and adjust `REGION/ZONE/CLUSTER` if needed.
4. Push to `main`. The workflow will:
   - Build & push image → `$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/enrichment-api:<SHA>`
   - Trivy scan (fails on HIGH/CRITICAL)
   - Cosign keyless sign (OIDC)
   - `kubectl apply` manifests + `kubectl set image` → rolling update

---

## Progressive Delivery & Rollback
**Rolling updates** are default (surge=1, unavailable=0). To roll back quickly:
```bash
kubectl rollout history deployment/enrichment-api -n enrichment
kubectl rollout undo deployment/enrichment-api -n enrichment --to-revision=<N>
```

For **canary/blue‑green**:
- Introduce a second Deployment (e.g., `enrichment-api-canary`)
- Use GKE Ingress or a service mesh (ASM/Istio) for traffic splitting by weight
- Gate promotion on SLOs/metrics and error budgets

---

## Observability & Metrics
- Prometheus metrics at `GET /metrics` (default registry)
- Add Prometheus (or Managed Service for Prometheus) and scrape via annotations:
  ```yaml
  prometheus.io/scrape: "true"
  prometheus.io/port: "8080"
  prometheus.io/path: "/metrics"
  ```
- Liveness/Readiness probes hit `/healthz`.
- Logs are JSON structured; route to Cloud Logging or your stack.

---

## Security Hardening Notes
- **Non‑root** user; drop Linux caps; **seccomp** RuntimeDefault.
- **Pinned** Python dependencies.
- **Trivy** in CI blocks HIGH/CRITICAL.
- **Cosign keyless** asserts provenance via GitHub OIDC.
- **NetworkPolicy** restricts ingress to app port.
- Consider **Binary Authorization** + **Admission Controls** to enforce signatures in-cluster.
- Scope IAM to least privilege; restrict WIF by `attribute.repository` and `attribute.ref`.

---

## Cost Notes
- GKE clusters, load balancers, and egress traffic incur costs. Use small node pools, Autopilot, or scale to zero by deleting the Service when idle.

---

## Cleanup
```bash
# Delete K8s resources
kubectl delete -f k8s-manifests.yaml --ignore-not-found

# Delete cluster
gcloud container clusters delete enrichment-api-cluster --zone us-central1-c

# Delete Artifact Registry repo (removes images)
gcloud artifacts repositories delete docker-repo --location us-central1
```

---