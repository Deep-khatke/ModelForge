# ModelForge — Phase 14: Cloud Observability & Centralized Logging Runbook

## 1. Executive Summary

Phase 14 delivers a production-grade observability and centralized logging stack for ModelForge, completely running within the local Docker Desktop Kubernetes environment (`namespace: modelforge`) at **zero external cloud cost**.

Key achievements:
- **Application & Model Telemetry**: Full Prometheus instrumentation across FastAPI backend and containerized model-server exposing latency histograms, request rates, error counters, model load times, and in-flight active requests.
- **Centralized Logging**: Grafana Loki log aggregation paired with Promtail DaemonSet log collector capturing CRI-formatted stdout container logs and indexing `service`, `event`, and `level`.
- **Request Correlation**: End-to-end `X-Request-ID` propagation from client/frontend to backend, through model-server inference, and reflected in structured JSON logs.
- **Kubernetes Telemetry**: Integrated `kube-state-metrics` and node `cAdvisor` capturing real-time Pod CPU, memory working set, container restarts, and Horizontal Pod Autoscaler (HPA) state.
- **Grafana Visualization**: 4 pre-provisioned dashboards covering ModelForge Overview, Kubernetes Infrastructure, ML Inference, and Security/Operational Events with dual Prometheus & Loki datasources.
- **Alerting & Recovery**: 9 configured Prometheus alerting rules with automated firing and recovery validation.

---

## 2. Component Inventory & Architecture

| Component | Image | Port | Service Type | Role |
| :--- | :--- | :--- | :--- | :--- |
| **Prometheus** | `prom/prometheus:v2.51.0` | 9090 | ClusterIP | Time-series database, pull metrics scraping, alert rules |
| **Grafana** | `grafana/grafana:10.4.0` | 3000 | ClusterIP | Telemetry dashboards, LogQL query viewer, alerts |
| **Loki** | `grafana/loki:2.9.8` | 3100 | ClusterIP | Multi-tenant log aggregation system with local FS storage |
| **Promtail** | `grafana/promtail:2.9.8` | 9080 | DaemonSet | Log collector streaming `/var/log/pods` to Loki |
| **Kube-State-Metrics** | `registry.k8s.io/kube-state-metrics:v2.10.0` | 8080 | ClusterIP | Kubernetes object metrics (deployments, pods, HPA) |
| **Backend Service** | `172.18.0.5:5000/modelforge/backend:v1` | 8000 | ClusterIP / LB | FastAPI core emitting metrics at `/metrics` & JSON logs |
| **Model Server** | `172.18.0.5:5000/modelforge/inference:v1` | 8000 | ClusterIP | Model inference microservice emitting `/metrics` & JSON logs |

---

## 3. Local Access Guide

Because this is a secure, local-first deployment, monitoring interfaces are intentionally deployed as `ClusterIP` services rather than public LoadBalancers. To access monitoring interfaces from your local workstation:

### 3.1 Grafana Web UI
Port-forward Grafana port 3000:
```powershell
kubectl port-forward -n modelforge svc/grafana 3000:3000
```
- **URL**: `http://localhost:3000`
- **Username**: `admin`
- **Password**: Retrieved securely from Kubernetes Secret:
  ```powershell
  [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String((kubectl get secret grafana-admin-secret -n modelforge -o jsonpath="{.data.admin-password}")))
  ```
  *(Default local dev credential: `ModelForgeLocalMonitoring2026!`)*

### 3.2 Prometheus Web UI
Port-forward Prometheus port 9090:
```powershell
kubectl port-forward -n modelforge svc/prometheus 9090:9090
```
- **URL**: `http://localhost:9090`
- **Status $\rightarrow$ Targets**: View real-time scrape health of all 5 target pools.
- **Alerts**: View real-time alert states (`inactive`, `pending`, `firing`).

### 3.3 Loki API
Port-forward Loki port 3100 (optional for CLI querying):
```powershell
kubectl port-forward -n modelforge svc/loki 3100:3100
```
- **Query Range Endpoint**: `http://localhost:3100/loki/api/v1/query_range?query={service="backend"}`

---

## 4. Operational Dashboards

Grafana automatically loads 4 dashboards from ConfigMap `/etc/grafana/provisioning/dashboards`:

### Dashboard 1 — ModelForge Overview (`modelforge-overview`)
- **Total Requests & Request Rate**: Visualizes incoming HTTP throughput across all endpoints.
- **HTTP Error Rate**: Highlights 4xx and 5xx response frequency.
- **P95 / P99 Latency**: Real-time response time distribution calculated from latency histogram buckets.
- **Active Model Replicas & HPA Desired**: Correlates incoming load with autoscaler replica demand.

### Dashboard 2 — Kubernetes Infrastructure (`modelforge-kubernetes`)
- **Pod CPU Usage (cores)**: Tracks per-pod CPU utilization in real time.
- **Pod Memory Working Set (bytes)**: Monitors container working set memory to detect leaks.
- **Pod Container Restarts**: Immediate visibility into crash loops or OOMKilled events.
- **Ready Replicas per Deployment**: Confirms quorum and readiness across all services.
- **HPA Autoscaling State**: Current vs. Desired replicas managed by `model-server-hpa`.

### Dashboard 3 — ML Inference Telemetry (`modelforge-ml-inference`)
- **Prediction Request Throughput**: Real-time inference calls processed by `model-server`.
- **Inference Latency (P50, P95, P99)**: Sub-millisecond inference execution timing inside the container.
- **Inference Error Rate**: Tracks validation errors, dimensionality mismatches, and model load failures.
- **Model Readiness Status**: Binary gauge indicating whether the artifact is loaded in memory.
- **In-Flight Active Requests**: Concurrency gauge tracking currently executing predictions.

### Dashboard 4 — Security & Operational Events (`modelforge-security-operations`)
- **Authentication Failure Rate**: Monitors unauthorized 401 and forbidden 403 spikes.
- **Storage Operations & Failures**: Tracks MinIO object upload/download operations and error counts.
- **Model Deployments Activity**: Real-time counters for deployments initiated and terminated.
- **Correlated Error Logs**: Live stream of structured error logs with matching `request_id`.

---

## 5. Alerting Policies & Runbooks

Prometheus evaluates 9 alert rules every 5 seconds:

| Alert Name | Condition (PromQL) | Duration | Severity | Actionable Runbook |
| :--- | :--- | :--- | :--- | :--- |
| **`HighHttpErrorRate`** | `sum(rate(modelforge_http_errors_total[1m])) > 0` | 5s | Warning | Check Loki for `{service="backend", status_code=~"4..|5.."}`. Verify client auth tokens and route payloads. |
| **`HighInferenceLatency`** | `histogram_quantile(0.95, sum(rate(modelforge_inference_latency_seconds_bucket[1m])) by (le)) > 1.0` | 5s | Warning | Check CPU saturation on `model-server`. If HPA is scaling, verify if replicas need higher CPU resource requests. |
| **`InferenceErrorRateHigh`** | `sum(rate(modelforge_inference_errors_total[1m])) > 0` | 5s | Warning | Query Loki for `{service="model-server", event="prediction_error"}`. Inspect input dimensions and feature formatting. |
| **`BackendUnavailable`** | `up{job="modelforge-backend"} == 0` | 10s | Critical | Check Pod status with `kubectl get pods -l app.kubernetes.io/component=backend`. Inspect container crash logs. |
| **`ModelServerUnavailable`** | `up{job="model-server"} == 0` | 10s | Critical | Check `kubectl describe deployment model-server`. Verify readiness probes and model artifact file mounts. |
| **`PodCrashRestart`** | `sum(increase(kube_pod_container_status_restarts_total{namespace="modelforge"}[5m])) > 0` | 30s | Warning | Run `kubectl describe pod <pod_name>` to inspect termination reasons (e.g., OOMKilled, exit code 137). |
| **`HpaMaxReplicasReached`** | `kube_horizontalpodautoscaler_status_current_replicas >= kube_horizontalpodautoscaler_spec_max_replicas` | 1m | Warning | Model server capacity is exhausted. Consider raising `maxReplicas` or optimizing model inference throughput. |
| **`HighCpuUsage`** | `sum(rate(container_cpu_usage_seconds_total{namespace="modelforge"}[1m])) > 0.8` | 1m | Warning | Container CPU exceeds 80%. Evaluate autoscaling policies or increase container CPU limits. |
| **`HighMemoryUsage`** | `sum(container_memory_working_set_bytes{namespace="modelforge"}) > 3000000000` | 1m | Warning | Namespace memory working set exceeds 3 GB. Investigate memory retention in object storage or cache buffers. |

---

## 6. Centralized Logging & Log Retention

### 6.1 Log Configuration
Microservices write structured JSON records to stdout. The logger automatically redacts credentials, passwords, and sensitive JWT tokens.

- **Log Level**: Controlled via environment variable `LOG_LEVEL` (default: `INFO`). Supports `DEBUG`, `INFO`, `WARNING`, `ERROR`.
- **Log Format**: JSON Lines with fields: `timestamp`, `level`, `service`, `event`, `request_id`, `latency_ms`.

### 6.2 Storage & Retention Policy
Loki is configured with a 48-hour local retention policy (`k8s/monitoring/loki.yaml`):
```yaml
compactor:
  working_directory: /data/loki/boltdb-shipper-compactor
  shared_store: filesystem
  retention_enabled: true
limits_config:
  retention_period: 48h
  max_query_length: 720h
```
This guarantees local disk consumption remains bounded while preserving historical logs for debugging and incident analysis.

---

## 7. Automated Verification Suite

Run the full end-to-end verification suite:
```powershell
python backend/scripts/test_phase14_observability.py
```

The script performs 17 rigorous, real-world tests verifying:
1. Metrics endpoint HTTP 200 response
2. Backend application Prometheus metrics
3. Model server microservice Prometheus metrics
4. Prometheus active target discovery and healthy status
5. Structured JSON logging compliance
6. Loki log ingestion and LogQL querying
7. Request ID correlation across microservices
8. Health and readiness endpoints across all components
9. Real-time ML inference telemetry and latency tracking
10. Error counter metrics and status propagation
11. HPA telemetry via kube-state-metrics
12. Grafana provisioning, datasources, and 4 dashboards
13. Alert detection and firing state transitions
14. Alert auto-recovery after traffic decay
15. Firebase Admin SDK integration regression
16. MinIO S3 and local container registry regression
17. NetworkPolicy micro-segmentation and security context regression
