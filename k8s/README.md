# ModelForge — Kubernetes Manifests (`k8s/`)

This directory contains cloud-native Kubernetes manifests for orchestrating ModelForge in a dedicated `modelforge` namespace, incorporating Phase 9 workload orchestration, Phase 10 cloud networking architecture, and Phase 11 Horizontal Pod Autoscaling (HPA) & resource management.

---

## 1. Directory Structure

```text
k8s/
├── namespace.yaml                  # Dedicated 'modelforge' namespace
├── configmap.yaml                  # Application configuration (ports, endpoints, settings)
├── secrets.example.yaml            # Example Secret template (do not commit real secrets!)
├── minio-secrets.example.yaml      # MinIO object storage credentials template
├── tls-secret.example.yaml         # Example TLS certificate Secret template for HTTPS
├── storage-pvc.yaml                # Shared model artifact PersistentVolumeClaim (local cache)
├── minio.yaml                      # MinIO S3-compatible Object Storage (Deployment, PVC, Services)
├── registry.yaml                   # Docker Container Registry v2 (Deployment, PVC, Service)
├── backend-deployment.yaml         # FastAPI backend deployment (readiness/liveness probes)
├── backend-service.yaml            # Backend LoadBalancer/ClusterIP service
├── model-server-deployment.yaml    # Inference replica deployment (resource requests/limits)
├── model-server-service.yaml       # Internal ClusterIP service for inference discovery
├── frontend-deployment.yaml        # React frontend deployment
├── frontend-service.yaml           # Frontend LoadBalancer service (port 5173 -> 80)
├── networkpolicy.yaml              # Pod micro-segmentation & traffic isolation policies
├── rbac.yaml                       # Least-privilege ServiceAccounts, Role, and RoleBinding (Phase 13)
├── ingress.yaml                    # Layer 7 host- & path-based routing (modelforge.local)
├── metrics-server.yaml             # Kubernetes Metrics Server for resource telemetry
├── hpa.yaml                        # HorizontalPodAutoscaler for model-server (autoscaling/v2)
└── README.md                       # Manifest guide and runbook
```

---

## 2. Secrets & TLS Setup

1. Copy `secrets.example.yaml` to `secrets.yaml`:
   ```powershell
   cp k8s/secrets.example.yaml k8s/secrets.yaml
   ```
   *(Note: `k8s/secrets.yaml` is registered in `.gitignore` to prevent credential leaks).*

2. Paste your `backend/firebase-credentials.json` content into `k8s/secrets.yaml` under `firebase-credentials.json: |`.

3. Apply secrets:
   ```powershell
   kubectl apply -f k8s/secrets.yaml
   ```

4. *(Optional for HTTPS)* For production or staging TLS termination, provision certificates via `cert-manager` or template `k8s/tls-secret.example.yaml`.

---

## 3. Deployment Runbook (Phases 9 - 12)

Apply manifests in dependency order:

```powershell
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Apply configuration & secrets
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/minio-secrets.yaml

# 3. Apply persistent storage (Phase 12)
kubectl apply -f k8s/storage-pvc.yaml
kubectl apply -f k8s/minio.yaml
kubectl apply -f k8s/registry.yaml

# 4. Deploy workloads & services
kubectl apply -f k8s/backend-deployment.yaml
kubectl apply -f k8s/backend-service.yaml
kubectl apply -f k8s/model-server-deployment.yaml
kubectl apply -f k8s/model-server-service.yaml
kubectl apply -f k8s/frontend-deployment.yaml
kubectl apply -f k8s/frontend-service.yaml

# 5. Apply Network Security Policies (Phases 10, 12)
kubectl apply -f k8s/networkpolicy.yaml

# 6. Apply Ingress Routing (Phase 10)
kubectl apply -f k8s/ingress.yaml

# 7. Deploy Metrics Server (Phase 11)
kubectl apply -f k8s/metrics-server.yaml

# 8. Apply Horizontal Pod Autoscaler (Phase 11)
kubectl apply -f k8s/hpa.yaml

# 9. Apply Kubernetes RBAC & Least-Privilege ServiceAccounts (Phase 13)
kubectl apply -f k8s/rbac.yaml
```

---

## 4. Verification & Testing Commands

### Run Automated Phase 13 Authentication, IAM & Security Suite
From `backend/`:
```powershell
cd backend
.venv\Scripts\python.exe scripts/test_phase13_security.py
```
This automated suite verifies:
1. Valid Bearer Token / Firebase Authentication
2. Missing Authentication Rejection (HTTP 401)
3. Invalid / Malformed Authentication Rejection (HTTP 401)
4. Role-Based Access Control (RBAC 403 Forbidden for unauthorized roles)
5. Resource Ownership & Insecure Direct Object Reference (IDOR) Protection
6. Kubernetes RBAC Least-Privilege (`kubectl auth can-i`)
7. NetworkPolicy Micro-Segmentation (Frontend blocked, Backend allowed)
8. Secrets Management & Repository Credential Hygiene
9. Model Artifact S3 Protection (Anonymous Denied 403)
10. Firebase Admin SDK & Cloud Firestore Connection
11. CORS Origin Restriction
12. Defensive HTTP Security Headers
13. Container & Pod Security Contexts (Non-root, capability drop)
14. Real Model Inference Pipeline Integrity
15. Horizontal Pod Autoscaler (HPA) Telemetry & Health

### Run Automated Phase 12 Storage & Registry Suite
From `backend/`:
```powershell
cd backend
.venv\Scripts\python.exe scripts/test_phase12_storage_registry.py
```

---

## 5. Detailed Documentation
- [docs/phase13-security.md](../docs/phase13-security.md) — Phase 13 Security & IAM Runbook and Verification Report.
- [docs/security-architecture.md](../docs/security-architecture.md) — Comprehensive Security Architecture & Future Cloud Mapping.
- [docs/phase12-storage-registry.md](../docs/phase12-storage-registry.md) — Phase 12 Storage & Registry Runbook.
- [docs/cloud-storage-architecture.md](../docs/cloud-storage-architecture.md) — Complete Cloud Storage & Registry Architecture Mapping.
- [docs/autoscaling.md](../docs/autoscaling.md) — Phase 11 Autoscaling Guide & Cloud Architecture.
- [docs/phase-11-report.md](../docs/phase-11-report.md) — Live verification test evidence for Phase 11.
- [docs/cloud-networking.md](../docs/cloud-networking.md) — Phase 10 Cloud Networking Architecture Guide.
