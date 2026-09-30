# ModelForge — Infrastructure as Code (`infra/terraform/`)

This directory provides the reproducible, declarative Infrastructure as Code (IaC) configuration for ModelForge using **OpenTofu** (open-source Terraform alternative) under a local-first, zero-cost architecture targeting Docker Desktop Kubernetes (`docker-desktop`).

---

## 1. IaC Architecture & Scope

Following the principle of **not forcing IaC to blindly duplicate everything**, ModelForge separates infrastructure into two well-defined layers:

```text
┌────────────────────────────────────────────────────────┐
│  Layer 1: Base Platform Infrastructure (OpenTofu)      │
│  - Kubernetes Namespace ('modelforge')                 │
│  - Core ConfigMap ('modelforge-config')                │
│  - PersistentVolumeClaims (models, minio, registry)    │
│  - Least-Privilege ServiceAccounts (IAM)               │
│  - Kubernetes RBAC Role & RoleBinding                  │
│  - Outputs & Environmental Metadata                    │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│  Layer 2: Workload & Runtime Delivery (Kubernetes)     │
│  - Microservice Deployments (Backend, Inference, Web)  │
│  - Horizontal Pod Autoscaler (HPA autoscaling/v2)      │
│  - NetworkPolicies (Micro-segmentation)                │
│  - Ingress Routing & Metrics Server                    │
│  - Monitoring Stack (Prometheus, Loki, Grafana)        │
└────────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout

```text
infra/terraform/
├── versions.tf               # OpenTofu requirement and local state backend definition
├── variables.tf              # Configurable parameters (context, namespace, PVC sizes)
├── main.tf                   # Declared baseline resources (Namespace, ConfigMap, PVCs, RBAC)
├── outputs.tf                # Exported identifiers and endpoints
├── terraform.tfvars.example  # Parameter template for local development
└── README.md                 # IaC guide and operational runbook
```

---

## 3. State Management Policy

1. **Local State**: State is stored locally in `infra/terraform/terraform.tfstate`.
2. **Zero Cloud State**: No connection is made to Terraform Cloud, AWS S3, or Google Cloud Storage.
3. **Sensitive Value Protection**: `terraform.tfstate`, `*.tfplan`, and `.terraform/` are strictly excluded in `.gitignore` to prevent credential exposure.
4. **State Recovery**: State can be safely inspected with `tofu show` or backed up locally.

---

## 4. Operational Runbook

### Step 1: Initialize Provider Plugins
```powershell
cd infra/terraform
tofu init
```

### Step 2: Validate Syntax and Schema
```powershell
tofu validate
```

### Step 3: Inspect Planned Changes
```powershell
tofu plan -var-file=terraform.tfvars.example
```

### Step 4: Apply Infrastructure Safely
```powershell
tofu apply -var-file=terraform.tfvars.example -auto-approve
```

---

## 5. Infrastructure Drift Detection

OpenTofu provides continuous drift detection by reconciling the declared state in code against the live Kubernetes API:

```text
Declared State (main.tf) <───[ tofu plan ]───> Live Cluster State (K8s API)
```

If an operator manually modifies or deletes a resource (e.g., changes a ConfigMap value or adds an unauthorized label):
```powershell
tofu plan
```
OpenTofu will highlight the exact diff (`+` additions, `~` modifications, `-` deletions) without applying any destructive actions.
