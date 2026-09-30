# ModelForge — Phase 9: Kubernetes Orchestration Guide

This guide describes how to build, deploy, manage, and verify ModelForge in a Kubernetes cluster (Docker Desktop Kubernetes on Windows).

---

## 1. Prerequisites

Before deploying ModelForge to Kubernetes, ensure the following are installed and enabled:

1. **Docker Desktop on Windows**:
   - Docker Engine `v29.x` or higher.
   - Built-in Kubernetes enabled:
     - Open Docker Desktop $\rightarrow$ Settings (⚙️) $\rightarrow$ **Kubernetes** $\rightarrow$ Check **"Enable Kubernetes"** $\rightarrow$ Click **"Apply & restart"**.
2. **`kubectl` CLI**:
   - Verify client version:
     ```powershell
     kubectl version --client
     ```
3. **Cluster Verification**:
   - Ensure the `docker-desktop` context is active:
     ```powershell
     kubectl config current-context
     kubectl get nodes
     ```
     *(The node should report `STATUS: Ready`).*

---

## 2. Container Images

ModelForge uses three container images:
- `modelforge-backend:v1`: FastAPI control plane
- `modelforge-frontend:v1`: React SPA dashboard (Nginx)
- `modelforge-inference:v1`: Microservice inference replica runner

### Build Local Images

Run from the repository root:

```powershell
# 1. Inference replica image
docker build -t modelforge-inference:v1 ./inference_service

# 2. Control plane backend image
docker build -t modelforge-backend:v1 ./backend

# 3. Web frontend image
docker build -t modelforge-frontend:v1 ./frontend
```

*(Because Docker Desktop shares its local image cache with its built-in Kubernetes cluster, you do not need to push images to a remote registry or run an image load command).*

---

## 3. Configuration & Secrets Setup

### 1. Application Configuration (`k8s/configmap.yaml`)
`k8s/configmap.yaml` defines non-sensitive settings:
- `DATABASE_BACKEND`: `firestore`
- `FIREBASE_PROJECT_ID`: `modelforge-d8cd0`
- `GOOGLE_APPLICATION_CREDENTIALS`: `/etc/modelforge/credentials/firebase-credentials.json`
- `MODEL_STORAGE_DIR`: `/app/storage/models`
- `MODEL_SERVER_URL`: `http://model-server.modelforge.svc.cluster.local:8000`

### 2. Kubernetes Secrets (`k8s/secrets.yaml`)
> [!IMPORTANT]
> Never commit `k8s/secrets.yaml` to source control. It is already registered in `.gitignore`.

Create `k8s/secrets.yaml` using `k8s/secrets.example.yaml`:
```powershell
cp k8s/secrets.example.yaml k8s/secrets.yaml
```

Populate the `firebase-credentials.json` key with the content of `backend/firebase-credentials.json`.

---

## 4. Deploying to Kubernetes

Apply manifests in dependency order:

```powershell
# 1. Create the dedicated modelforge namespace
kubectl apply -f k8s/namespace.yaml

# 2. Apply ConfigMap and Secrets
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# 3. Create shared PersistentVolumeClaim for model artifacts
kubectl apply -f k8s/storage-pvc.yaml

# 4. Deploy workloads & services
kubectl apply -f k8s/backend-deployment.yaml
kubectl apply -f k8s/backend-service.yaml
kubectl apply -f k8s/model-server-deployment.yaml
kubectl apply -f k8s/model-server-service.yaml
kubectl apply -f k8s/frontend-deployment.yaml
kubectl apply -f k8s/frontend-service.yaml
```

---

## 5. Verification & Health Probes

### Check Pod Readiness
```powershell
kubectl get pods -n modelforge
```
All Pods (`modelforge-backend-*`, `modelforge-frontend-*`, `model-server-*`) should report:
```text
READY   STATUS    RESTARTS   AGE
1/1     Running   0          30s
```

### Check Services & Port Bindings
```powershell
kubectl get svc -n modelforge
```
Docker Desktop automatically provisions LoadBalancer ports to localhost:
- **Frontend**: `http://localhost:5173`
- **Backend API**: `http://localhost:8000`

---

## 6. Accessing ModelForge from Host Browser

In Docker Desktop Kind clusters, forward the service ports to your host:

```powershell
# In Terminal 1: Forward Backend API
kubectl port-forward svc/backend 8000:8000 -n modelforge

# In Terminal 2: Forward Frontend Dashboard
kubectl port-forward svc/modelforge-frontend 5173:5173 -n modelforge
```

Then access the services:
1. **Dashboard (Web UI)**:
   Open `http://localhost:5173` in your browser.
2. **API Documentation**:
   Open `http://localhost:8000/docs`.
3. **Health Check**:
   ```powershell
   curl http://localhost:8000/api/health
   # Returns: {"status":"healthy"}
   ```
4. **Firebase Cloud Diagnostics**:
   ```powershell
   curl http://localhost:8000/api/health/firebase
   # Returns: {"initialized": true, "project_id": "modelforge-d8cd0", ...}
   ```

---

## 7. Scaling Model Replicas

Scale the inference microservice deployment dynamically:

```powershell
# Scale up to 3 inference pods
kubectl scale deployment model-server -n modelforge --replicas=3

# Observe new pods initializing
kubectl get pods -n modelforge -l app.kubernetes.io/component=model-server
```

Kubernetes automatically load-balances internal traffic across all 3 healthy pods through the `model-server` ClusterIP service.

---

## 8. Logs & Observability

Inspect container output:

```powershell
# Backend logs
kubectl logs -l app.kubernetes.io/component=backend -n modelforge -f

# Model inference server logs
kubectl logs -l app.kubernetes.io/component=model-server -n modelforge -f

# Frontend access logs
kubectl logs -l app.kubernetes.io/component=frontend -n modelforge -f
```

---

## 9. Failure Recovery & Self-Healing Test

To verify Kubernetes self-healing:

```powershell
# 1. Identify a running model-server Pod
kubectl get pods -n modelforge -l app.kubernetes.io/component=model-server

# 2. Delete the pod
kubectl delete pod <pod-name> -n modelforge

# 3. Observe Kubernetes immediately spawn a replacement pod
kubectl get pods -n modelforge -w
```

The Deployment controller notices the missing replica and automatically provisions a healthy replacement Pod.

---

## 10. Rolling Updates & Rollback

### Perform a Rolling Update
```powershell
kubectl rollout restart deployment/modelforge-backend -n modelforge
kubectl rollout status deployment/modelforge-backend -n modelforge
```

### Rollback a Deployment
```powershell
kubectl rollout undo deployment/modelforge-backend -n modelforge
kubectl rollout status deployment/modelforge-backend -n modelforge
```

---

## 11. Teardown / Cleanup

To cleanly remove all ModelForge Kubernetes resources:

```powershell
kubectl delete namespace modelforge
```
*(Removes all Deployments, Services, ConfigMaps, Secrets, and PVCs safely).*
