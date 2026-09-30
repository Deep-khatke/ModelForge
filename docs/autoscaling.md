# ModelForge — Phase 11: Autoscaling & Resource Management Guide

This document describes the Horizontal Pod Autoscaling (HPA) and resource management architecture of ModelForge, covering both the active local Kubernetes implementation on Docker Desktop and the future production cloud architecture (Google Cloud / GKE, AWS / EKS, and Azure / AKS).

---

## 1. Autoscaling Architecture Overview

ModelForge employs a closed-loop automated scaling pipeline that monitors container compute utilization, queries the Kubernetes Metrics API, and dynamically adjusts the replica count of the inference microservice:

```text
                     INCOMING INFERENCE TRAFFIC
                                 |
                                 v
                       [ Backend Control Plane ]
                                 |
                                 v
                     [ model-server Service:8000 ]
                                 |
             +-------------------+-------------------+
             |                   |                   |
             v                   v                   v
      [ Model Pod 1 ]     [ Model Pod 2 ]     [ Model Pod 3 ]
             \                   |                   /
              +------------------+------------------+
                                 |
                    (Container CPU Utilization)
                                 v
                 [ Kubelet Cadvisor Resource Scrape ]
                                 |
                                 v
                    [ Kubernetes Metrics Server ]
                         (v1beta1.metrics.k8s.io)
                                 |
                                 v
              [ Horizontal Pod Autoscaler (HPA v2) ]
                  Target: 40% CPU Utilization
                  Current: [3% Idle  <--->  77% Load]
                                 |
                                 v
               [ Deployment Controller Scale Action ]
             Under Load: 2 Replicas  --->  4 Replicas
             After Idle: 4 Replicas  --->  2 Replicas
```

---

## 2. Resource Requests and Limits

Every container in ModelForge is provisioned with explicit `requests` and `limits` to guarantee predictable scheduling and resource protection:

| Workload | Container | CPU Request | CPU Limit | Memory Request | Memory Limit | Autoscaling Target |
|---|---|---|---|---|---|:---:|
| `model-server` | `model-server` | `100m` (0.1 core) | `500m` (0.5 core) | `128Mi` | `512Mi` | **Primary HPA Target** |
| `modelforge-backend` | `backend` | `100m` (0.1 core) | `500m` (0.5 core) | `256Mi` | `512Mi` | Control Plane |
| `modelforge-frontend` | `frontend` | `50m` (0.05 core) | `200m` (0.2 core) | `64Mi` | `256Mi` | Web Dashboard |

### Architectural Purpose:
- **Requests (`requests.cpu`, `requests.memory`):** Used by the Kubernetes scheduler (`kube-scheduler`) to determine node placement. Crucially, **HPA calculates percentage utilization against the CPU request** ($Utilization = \frac{CurrentUsage}{RequestedCPU} \times 100\%$). A request of `100m` means a container using `40m` (0.04 cores) reports exactly 40% utilization.
- **Limits (`limits.cpu`, `limits.memory`):** Enforced by Linux cgroups. Limits prevent a single runaway process or memory leak from starving adjacent cluster workloads or overwhelming the developer workstation.

---

## 3. Metrics Server Integration

To drive HPA decisions, Kubernetes requires the Metrics API (`metrics.k8s.io`).

### Local Implementation Details:
- **Component:** Kubernetes SIGs Metrics Server (`v0.9.0`), deployed in `kube-system` via [k8s/metrics-server.yaml](file:///c:/college/ModelForge-Phase5-source/k8s/metrics-server.yaml).
- **Cluster Compatibility:** Docker Desktop Kubernetes nodes utilize self-signed kubelet certificates. The Metrics Server is configured with the standard local flag:
  ```yaml
  - --kubelet-insecure-tls
  - --kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname
  - --metric-resolution=15s
  ```
- **Verified Status:**
  ```text
  kubectl top nodes:
  NAME                    CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)
  desktop-control-plane   508m         3%       1265Mi          10%

  kubectl top pods -n modelforge:
  NAME                                   CPU(cores)   MEMORY(bytes)
  model-server-559cdbfcff-6cdbn          3m           113Mi
  model-server-559cdbfcff-xwgmh          3m           108Mi
  modelforge-backend-6c974cdb95-qqvfg    3m           136Mi
  modelforge-frontend-5b5d948d8c-84tx8   1m           15Mi
  ```

---

## 4. Horizontal Pod Autoscaler Specification (`k8s/hpa.yaml`)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: model-server-hpa
  namespace: modelforge
  labels:
    app.kubernetes.io/name: modelforge
    app.kubernetes.io/component: model-server
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: model-server
  minReplicas: 2
  maxReplicas: 5
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 40
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 2
          periodSeconds: 15
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 30
      policies:
        - type: Percent
          value: 50
          periodSeconds: 15
        - type: Pods
          value: 1
          periodSeconds: 15
      selectPolicy: Min
```

### Key Parameters:
1. **Target Metric:** CPU Utilization at `40%`. At idle, replicas consume ~3m (3%). Under concurrent inference load, CPU climbs to 60m–80m (60%–80%), rapidly breaching the 40% threshold.
2. **Bounds (`minReplicas: 2`, `maxReplicas: 5`):** Ensures high availability by maintaining at least 2 warm replicas, while capping maximum resource consumption at 5 replicas to safeguard the developer machine.
3. **Responsive Scale-Up (`stabilizationWindowSeconds: 0`):** Reacts immediately to load spikes by adding up to 2 pods or 100% capacity within 15 seconds.
4. **Controlled Scale-Down (`stabilizationWindowSeconds: 30`):** Prevents flapping by ensuring traffic has subsided before gracefully decommissioning replicas one step at a time.

---

## 5. Controlled Load Testing & Scaling Lifecycle

The complete lifecycle is verified using the automated test suite [backend/scripts/test_phase11_autoscaling.py](file:///c:/college/ModelForge-Phase5-source/backend/scripts/test_phase11_autoscaling.py):

### Execution Steps:
1. **Health Verification:** Verifies backend `/api/health` and confirms pre-load inference with `[[1.0, 2.0]]`.
2. **Initial State:** HPA reports baseline idle utilization: `3% / 40%`, Replicas: `2`.
3. **Load Generation:** Sends concurrent prediction requests across 14 worker threads from within the backend pod for 40 seconds.
4. **Scale-Up Trigger:**
   - Cadvisor scrapes container CPU spike.
   - HPA observes CPU climbing to **77%** (target 40%).
   - HPA calculates desired replicas: $\lceil 2 \times \frac{77}{40} \rceil = 4$.
   - Scale-up event recorded: `New size: 4; reason: cpu resource utilization above target`.
   - Kubernetes launches new pods: `model-server-559cdbfcff-xb6xj` becomes `Ready`.
5. **In-Flight Reliability:** Live inference requests continue executing without error throughout pod initialization. Round-robin load balancing distributes traffic across all newly ready replicas.
6. **Load Termination & Cooldown:** Traffic stops. Container CPU drops back to 3m (3%).
7. **Scale-Down Trigger:**
   - After the 30-second stabilization window, HPA calculates desired replicas = 2.
   - HPA steps down replicas: `New size: 3`, followed by `New size: 2; reason: All metrics below target`.
   - Excess pods enter graceful termination.
8. **Post-Scaling Integrity:** Model prediction re-verified with `100%` accuracy and `<1ms` latency.

---

## 6. Live HPA Events & Evidence

Actual events captured directly from `kubectl describe hpa model-server-hpa -n modelforge`:

```text
Conditions:
  Type            Status  Reason            Message
  ----            ------  ------            -------
  AbleToScale     True    SucceededRescale  the HPA controller was able to update the target scale to 2
  ScalingActive   True    ValidMetricFound  the HPA was able to successfully calculate a replica count from cpu resource utilization
  ScalingLimited  True    TooFewReplicas    the desired replica count is less than the minimum replica count

Events:
  Type    Reason             Age   From                       Message
  ----    ------             ----  ----                       -------
  Normal  SuccessfulRescale  62s   horizontal-pod-autoscaler  New size: 4; reason: cpu resource utilization (percentage of request) above target
  Normal  SuccessfulRescale  17s   horizontal-pod-autoscaler  New size: 3; reason: All metrics below target
  Normal  SuccessfulRescale  1s    horizontal-pod-autoscaler  New size: 2; reason: All metrics below target
```

---

## 7. Cloud Architecture Mapping (GKE, EKS, AKS)

In enterprise cloud deployments, pod autoscaling pairs with node autoscaling:

| Layer | Local Docker Desktop (Phase 11) | Google Cloud (GKE) | Amazon Web Services (EKS) | Microsoft Azure (AKS) |
|---|---|---|---|---|
| **Metrics Source** | In-cluster Metrics Server | Google Cloud Monitoring Metrics Adapter | CloudWatch Container Insights / Metrics Server | Azure Monitor Managed Prometheus |
| **Pod Autoscaling** | HPA v2 (CPU/Memory) | HPA v2 + Custom Cloud Pub/Sub Metrics | HPA v2 + KEDA (Kubernetes Event-driven Autoscaling) | HPA v2 + KEDA |
| **Node Autoscaling** | None (Single fixed node) | GKE Cluster Autoscaler / GKE Autopilot | Karpenter / AWS Cluster Autoscaler | AKS Cluster Autoscaler |
| **Inference Acceleration** | CPU emulation | GKE GPU Node Pools (NVIDIA L4 / T4) | EKS GPU Instances (g5.xlarge) | AKS GPU VM sizes (NCasT4_v3) |
| **Network Security** | kindnet CNI NetworkPolicy | Datapath v2 (Cilium eBPF) | AWS VPC CNI Network Policies / Calico | Azure CNI with Cilium |

---

## 8. Troubleshooting Guide

1. **HPA reports `<unknown>/40%`:**
   - **Cause:** Metrics Server is not deployed or has not completed its first 15-second collection scrape.
   - **Fix:** Verify `kubectl get pods -n kube-system -l k8s-app=metrics-server`. Ensure `--kubelet-insecure-tls` is enabled for local clusters.
2. **Pods do not scale down:**
   - **Cause:** Default Kubernetes HPA scale-down stabilization window is 300 seconds (5 minutes).
   - **Fix:** In `k8s/hpa.yaml`, set `behavior.scaleDown.stabilizationWindowSeconds: 30`.
3. **Pods terminate abruptly:**
   - **Cause:** `terminationGracePeriodSeconds` too short.
   - **Fix:** ModelForge sets `terminationGracePeriodSeconds: 15` on `model-server` to allow in-flight HTTP inference requests to finish before SIGKILL.
