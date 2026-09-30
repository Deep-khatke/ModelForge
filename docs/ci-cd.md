# ModelForge — Continuous Integration & Continuous Deployment (CI/CD)

## 1. CI/CD Architecture Overview

ModelForge Phase 15 provides an automated, reproducible software delivery pipeline designed to run **locally at $0 cost** while maintaining production-grade delivery guarantees:

```text
+-----------------------------------------------------------------------------------+
|                            DEVELOPER / GIT REPOSITORY                             |
|                           Local Git Branch (main / feature)                       |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|               CONTINUOUS INTEGRATION (CI) PIPELINE (scripts/ci.ps1)               |
|                                                                                   |
|  [Stage 1] Pre-flight & Git Repository Verification                                |
|  [Stage 2] Secret Scanning Gate (git grep credentials detection)                  |
|  [Stage 3] Infrastructure as Code (OpenTofu validate & plan)                      |
|  [Stage 4] Kubernetes Manifest Schema Validation (dry-run client)                 |
|  [Stage 5] Backend Unit & API Integration Tests (pytest: 79 tests)                |
|  [Stage 6] Frontend Production Compilation (npm run build -> dist/index.html)     |
|  [Stage 7] Container Image Build & Version Tagging (Docker build backend/frontend)|
|  [Stage 8] Local Container Registry Delivery (Push localhost:5000)                |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|             CONTINUOUS DEPLOYMENT (CD) PIPELINE (scripts/deploy-local.ps1)        |
|                                                                                   |
|  [Step 1] OpenTofu Infrastructure Reconciliation (tofu apply -auto-approve)       |
|  [Step 2] Containerd Node Registry Mirror Verification                            |
|  [Step 3] Kubernetes Workload Apply (Deployments, Services, NetworkPolicies, HPA) |
|  [Step 4] Rolling Update Rollout Convergence (kubectl rollout status)             |
|  [Step 5] Automated Health Gate Verification:                                     |
|           - Gate 1: Pods Ready Condition (1/1 Running across all pods)            |
|           - Gate 2: Backend Health API (/api/health returns healthy)              |
|           - Gate 3: Software Version API (/api/version returns 1.5.0)             |
|           - Gate 4: Frontend UI Static Availability (HTTP 200)                    |
|           - Gate 5: Live End-to-End ML Inference Pipeline (model-server /predict) |
+-----------------------------------------------------------------------------------+
                                         |
                       +-----------------+-----------------+
                       |                                   |
                Success Gate: 5/5                   Any Gate Failure:
                       |                                   |
                       v                                   v
             DEPLOYMENT SUCCESS                  AUTOMATED ROLLBACK
          (Zero downtime maintained)         (scripts/rollback-local.ps1)
                                             - kubectl rollout undo
                                             - Restores previous revision
                                             - Preserves persistent data
```

---

## 2. Pipeline Execution Commands

### Local CI Pipeline
To run the full 8-stage verification pipeline locally:
```powershell
.\scripts\ci.ps1 -Version 1.5.0
```
Options:
- `-SkipDeploy`: Runs only validation, tests, and builds without updating cluster workloads.
- `-SkipBuild`: Skips Docker image builds when testing manifests or code only.

### Local CD / Deployment Pipeline
To deploy a specific software release to the local cluster:
```powershell
.\scripts\deploy-local.ps1 -Version 1.5.0
```

### Dry-Run Validation Mode
To validate infrastructure and manifest consistency without mutating the cluster:
```powershell
.\scripts\deploy-local.ps1 -DryRun
```

### Automated Rollback Controller
To revert a deployment to its previous stable revision:
```powershell
.\scripts\rollback-local.ps1 -Deployment modelforge-backend
```
Or to roll back all microservices:
```powershell
.\scripts\rollback-local.ps1 -All
```

---

## 3. Image Versioning & Traceability

ModelForge enforces immutable semantic versioning:
- **Major.Minor.Patch (`1.5.0`)**: Traceable release tags corresponding to application code and infrastructure specifications.
- **Git Commit SHA**: In automated environments, images are tagged with short commit SHAs (`modelforge/backend:a1b2c3d`) for source tracing.
- **Rolling Tag (`v1` / `latest`)**: Maintained for backwards compatibility but never relied upon exclusively.

---

## 4. Rollout Safety & Deployment Health Gates

A deployment is never considered successful merely because `kubectl apply` completed. Every release must pass **5 automated health gates**:

1. **Pod Readiness Gate**: All pods in `modelforge` namespace must achieve `1/1 Running` status with readiness probes passing.
2. **Backend Health API Gate**: `GET /api/health` must return HTTP 200 with `{"status":"healthy"}`.
3. **Software Version Endpoint Gate**: `GET /api/version` must return HTTP 200 with `{"version":"1.5.0","phase":"Phase 15: Infrastructure as Code & CI/CD"}`.
4. **Frontend UI Gate**: `GET http://localhost:5173/` must return HTTP 200 with compiled HTML.
5. **Live ML Inference Gate**: End-to-end inference request executed from the backend pod to `model-server:8000/predict` must return valid model predictions (`predictions: [1]`).

If any gate fails, the deployment halts with a non-zero exit code and an automated rollback can be initiated immediately.

---

## 5. Security & Secret Scanning

ModelForge enforces a strict security gate prior to image builds:
- **Automated Secret Scanner**: Scans repository index and tracked files for private keys (`BEGIN RSA PRIVATE KEY`), API keys (`AIzaSy*`), client secrets, and hardcoded credentials.
- **Local Tool Support**: Compatible with open-source scanners including `gitleaks` and `trivy`.
- **Zero Cloud Exposure**: Scanning runs entirely locally without transmitting code to third-party SaaS services.

---

## 6. Future Cloud CI/CD Architecture Mapping

> **Important:** The current ModelForge deployment runs strictly on **local Docker Desktop Kubernetes at $0 cost**. No external cloud accounts or paid services are connected.

When transitioning to enterprise cloud providers, the architecture maps cleanly as follows:

| Component | Local Implementation (Current) | Google Cloud (Future) | AWS (Future) | Microsoft Azure (Future) |
| :--- | :--- | :--- | :--- | :--- |
| **IaC Engine** | OpenTofu v1.12 (Local State) | Terraform / OpenTofu (GCS State) | Terraform (S3 + DynamoDB) | Terraform (Azure Blob State) |
| **Kubernetes** | Docker Desktop K8s | Google Kubernetes Engine (GKE)| Elastic Kubernetes Service (EKS)| Azure Kubernetes Service (AKS) |
| **Container Registry**| Docker Registry (`localhost:5000`)| Artifact Registry (`gcr.io` / `pkg.dev`) | Amazon Elastic Container Registry (ECR) | Azure Container Registry (ACR) |
| **CI Orchestrator** | PowerShell Orchestrator (`ci.ps1`)| Cloud Build / GitHub Actions | AWS CodeBuild / GitHub Actions | Azure Pipelines / GitHub Actions|
| **Secrets Engine** | Kubernetes Secrets / Local `.env` | Secret Manager / Workload Identity | Secrets Manager / IAM Roles (IRSA) | Azure Key Vault / Workload Identity |
| **Object Storage** | MinIO S3 (`localhost:9000`) | Google Cloud Storage (GCS) | Amazon S3 | Azure Blob Storage |
| **Central Observability**| Prometheus, Loki, Grafana | Cloud Monitoring & Cloud Logging | Amazon CloudWatch & Managed Grafana | Azure Monitor & Log Analytics |
