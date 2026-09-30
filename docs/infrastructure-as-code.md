# ModelForge — Infrastructure as Code (IaC) Architecture & Runbook

## 1. Overview & Architectural Philosophy

ModelForge Phase 15 introduces declarative, automated, reproducible, and version-controlled infrastructure management using **OpenTofu v1.12.6** and the native Kubernetes provider (`hashicorp/kubernetes ~> 2.35.0`).

### Core Principle: Separation of Concerns
ModelForge intentionally does **not** blindly convert every ephemeral microservice workload manifest into Terraform/OpenTofu HCL. Instead, a strict layered architecture is enforced:

```text
+-----------------------------------------------------------------------+
| LAYER 1: Core Base Infrastructure (Managed by OpenTofu)               |
| - Target Namespace: modelforge                                        |
| - Configuration: modelforge-config (ConfigMap)                        |
| - Persistent Volume Claims: Model storage, MinIO S3, Local Registry   |
| - Identity & IAM: ServiceAccounts (backend, frontend, model-server)    |
| - Access Control: RBAC Role & RoleBinding (modelforge-backend-role)   |
+-----------------------------------------------------------------------+
                                  |
                                  v
+-----------------------------------------------------------------------+
| LAYER 2: Application Workloads & Deployments (Kubernetes Declarative)  |
| - Deployments: modelforge-backend, model-server, modelforge-frontend  |
| - Services: ClusterIP & LoadBalancer networking                       |
| - Network Policies: Micro-segmentation & zero-trust egress/ingress   |
| - Autoscaling: HorizontalPodAutoscaler (HPA target 40% CPU)           |
| - Observability: Prometheus, Loki, Grafana, Promtail                  |
+-----------------------------------------------------------------------+
```

---

## 2. Directory Structure & Files

All IaC code is located in `infra/terraform/`:

```text
infra/terraform/
├── main.tf                    # Core declarative resources (Namespace, PVCs, ConfigMap, SAs, RBAC)
├── variables.tf               # Parameterized variables (cluster context, namespace, storage sizing)
├── outputs.tf                 # Key infrastructure attributes exported for orchestration
├── versions.tf                # OpenTofu version constraints and local state backend
├── terraform.tfvars.example   # Example variable overrides for custom local clusters
├── terraform.tfstate          # Local state file (strictly .gitignored)
└── README.md                  # Quick-start operator runbook
```

### Module Component Summary

| Resource Type | Resource Name | Purpose | Managed By |
| :--- | :--- | :--- | :--- |
| `kubernetes_namespace` | `modelforge` | Isolated platform namespace | OpenTofu |
| `kubernetes_config_map` | `modelforge-config` | Non-sensitive runtime parameters | OpenTofu |
| `kubernetes_persistent_volume_claim` | `modelforge-model-storage-pvc` | Model artifact storage (10Gi) | OpenTofu |
| `kubernetes_persistent_volume_claim` | `minio-pvc` | MinIO S3 object storage (20Gi) | OpenTofu |
| `kubernetes_persistent_volume_claim` | `registry-pvc` | Local container registry (10Gi) | OpenTofu |
| `kubernetes_service_account` | `modelforge-backend` | Workload identity for backend API | OpenTofu |
| `kubernetes_service_account` | `modelforge-model-server` | Workload identity for inference | OpenTofu |
| `kubernetes_service_account` | `modelforge-frontend` | Workload identity for Nginx frontend | OpenTofu |
| `kubernetes_role` | `modelforge-backend-role` | Least-privilege API permissions | OpenTofu |
| `kubernetes_role_binding` | `modelforge-backend-rolebinding`| Binds backend role to SA | OpenTofu |

---

## 3. Local State Management & Security

### Local State Policy
In strict compliance with the **$0-cost, local-first** constraint:
- OpenTofu uses a local state backend (`infra/terraform/terraform.tfstate`).
- Remote backends (Terraform Cloud, AWS S3, GCS, Azure Blob) are **not** used.
- All state files and backup artifacts are strictly excluded from git tracking via root `.gitignore`:
  ```gitignore
  *.tfstate
  *.tfstate.*
  *.tfplan
  .terraform/
  .terraform.lock.hcl
  ```

### Zero Secret Exposure
- No credentials, tokens, or private keys are stored in OpenTofu configuration or state.
- Sensitive credentials (`modelforge-secrets`, `minio-secrets`) are mounted dynamically into Kubernetes Pods from isolated secrets templates.

---

## 4. Drift Detection & Self-Healing Telemetry

Infrastructure drift occurs when cluster resources are modified out-of-band (e.g. manual `kubectl` edits).

### Drift Detection Workflow:
```text
Live Cluster State <------ OpenTofu Refresh State
        |
        v
OpenTofu Plan Engine (Compares Desired HCL vs Actual Cluster State)
        |
        v
Diff Output Generated
   - No Changes: Infrastructure is 100% in sync
   - Drift Detected: OpenTofu details exact resource deltas (+/- /~)
        |
        v
OpenTofu Apply (Self-Healing Reconcile to Desired State)
```

### Execution Example:
```powershell
cd infra/terraform
tofu plan
```
If an out-of-band change occurred (e.g. an operator manually edited `modelforge-config`), `tofu plan` displays:
```text
  ~ resource "kubernetes_config_map" "modelforge_config" {
      ~ data = {
          ~ "LOG_LEVEL" = "DEBUG" -> "INFO"
        }
    }
Plan: 0 to add, 1 to change, 0 to destroy.
```
Running `tofu apply -auto-approve` immediately reconciles the cluster back to the version-controlled state.

---

## 5. Clean-Cluster Reproducibility Procedure

To reproduce the complete ModelForge platform from scratch on a clean Docker Desktop Kubernetes cluster:

1. **Prerequisites Verification:**
   - Docker Desktop running with Kubernetes enabled (`context: docker-desktop`).
   - OpenTofu v1.12+ installed locally.
   - Node containerd registry mirror configured for `localhost:5000`.

2. **Step 1: Initialize Base Infrastructure via OpenTofu:**
   ```powershell
   cd infra/terraform
   tofu init
   tofu apply -auto-approve
   ```

3. **Step 2: Seed Kubernetes Secrets:**
   ```powershell
   kubectl apply -f k8s/secrets.yaml
   kubectl apply -f k8s/minio-secrets.yaml
   ```

4. **Step 3: Deploy Local Storage & Registry Services:**
   ```powershell
   kubectl apply -f k8s/minio.yaml
   kubectl apply -f k8s/registry.yaml
   ```

5. **Step 4: Build & Push Microservice Container Images:**
   ```powershell
   .\scripts\build-images.ps1 -Version 1.5.0
   ```

6. **Step 5: Deploy Application Workloads & Mesh:**
   ```powershell
   .\scripts\deploy-local.ps1 -Version 1.5.0
   ```

7. **Step 6: Deploy Observability & Metrics Stack:**
   ```powershell
   kubectl apply -f k8s/metrics-server.yaml
   kubectl apply -f monitoring/
   ```

8. **Step 7: Automated Verification:**
   ```powershell
   python backend\scripts\test_phase15_iac_cicd.py
   ```
