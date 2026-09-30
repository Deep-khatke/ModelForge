# ModelForge — Observability Architecture

## 1. Overview & Core Philosophy

ModelForge's Phase 14 Observability Architecture provides enterprise-grade, zero-cost, local-first telemetry across the entire machine learning and microservices lifecycle. The observability stack answers five fundamental operational questions:

| Question | Observability Pillar | Primary Component | Purpose & Insight |
| :--- | :--- | :--- | :--- |
| **What is happening?** | **Metrics** | Prometheus & kube-state-metrics | Quantitative real-time rates, latencies, resource saturation, and error rates. |
| **What happened?** | **Logs** | Grafana Loki & Promtail | Structured JSON contextual timeline, causal reasoning, stack traces, and forensic analysis. |
| **What is the current state?** | **Dashboards** | Grafana | High-level aggregated views for infrastructure, inference, operational events, and Kubernetes health. |
| **What requires attention?** | **Alerts** | Prometheus Alertmanager | Automated thresholds identifying degraded services, latency spikes, or exhausted capacities. |
| **Which request caused it?** | **Correlation IDs** | `X-Request-ID` Header | Trace token propagated across Frontend $\rightarrow$ Backend $\rightarrow$ Model-Server $\rightarrow$ Logs. |

```
                                  USER BROWSER / CLIENT
                                            │
                                (Generates X-Request-ID)
                                            ▼
                                   FRONTEND (Nginx)
                                 (Port 80 / 5173 LB)
                                            │
                           (Propagates X-Request-ID Header)
                                            ▼
                              MODELFORGE FASTAPI BACKEND
                                  (Port 8000 ClusterIP)
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │                                             │
      (Inference Request with X-Request-ID)                        │
                     ▼                                             ▼
             MODEL-SERVER (K8s)                           MINIO S3 / FIREBASE
            (Port 8000 ClusterIP)                           (Storage / Auth)
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            │
                      EMITTED TELEMETRY (Metrics + Logs)
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     │                                             │
               Metrics Scrape                               Container Stdout
              (/metrics, 5s)                             (CRI JSON Logs in /var/log)
                     │                                             │
                     ▼                                             ▼
                 PROMETHEUS                               PROMTAIL DAEMONSET
            (Port 9090 ClusterIP)                                  │
          [Scrapes App + KubeState]                                │
                     │                                             ▼
                     │                                        GRAFANA LOKI
                     │                                   (Port 3100 ClusterIP)
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            │
                                            ▼
                                     GRAFANA 10.4.0
                                  (Port 3000 ClusterIP)
                                            │
                     ┌──────────────────────┼──────────────────────┐
                     ▼                      ▼                      ▼
               ModelForge             Kubernetes              ML Inference
                Overview            Infrastructure              Telemetry
```

---

## 2. Telemetry Ingestion & Data Flow

### 2.1 Prometheus Metrics Scraping Pipeline
Prometheus operates on a pull-based model configured with a 5-second scrape interval and 4-second timeout:
1. **`modelforge-backend`**: Scrapes `http://modelforge-backend.modelforge.svc.cluster.local:8000/metrics`. Collects HTTP request counts, request latency histograms, error counts, active deployments, and auth failure counters.
2. **`model-server`**: Scrapes `http://model-server.modelforge.svc.cluster.local:8000/metrics`. Collects model prediction counts, latency histograms, error counters, model loading duration, model ready status, and in-flight active requests.
3. **`kube-state-metrics`**: Scrapes `http://kube-state-metrics.modelforge.svc.cluster.local:8080/metrics`. Collects deployment replicas, pod restart counts, container states, and Horizontal Pod Autoscaler (HPA) telemetry (`kube_horizontalpodautoscaler_*`).
4. **`kubernetes-cadvisor`**: Scrapes the Kubernetes node proxy cAdvisor API (`https://kubernetes.default.svc:443/api/v1/nodes/desktop-control-plane/proxy/metrics/cadvisor`) for raw container CPU cores, memory working sets, and network bandwidth.
5. **`prometheus`**: Self-monitoring scrape pool evaluating query latencies, head chunks, and rule evaluation durations.

### 2.2 Centralized Logging Pipeline (Loki + Promtail)
1. **Log Emission**: Backend and Model-Server containers write structured JSON events directly to `stdout` / `stderr`.
2. **Kubernetes Log Persist**: The container runtime (containerd) wraps stdout lines into CRI-formatted log files under `/var/log/pods/modelforge_<pod>_<uid>/<container>/0.log`.
3. **Promtail Ingestion**: Promtail runs as a DaemonSet with read-only host mounts on `/var/log/pods`. Its pipeline stages:
   - Match containers in namespace `modelforge`.
   - Strip CRI timestamps and stream markers using the `cri` parser.
   - Parse internal JSON fields: `event`, `level`, `service`, `request_id`.
   - Apply dynamic label indexing: `level`, `service`, `event`.
4. **Loki Storage & Querying**: Loki ingests compressed log chunks with a 48-hour local filesystem retention policy (`retention_period: 48h`). Operators query logs via LogQL through Grafana or the HTTP API:
   ```logql
   {namespace="modelforge", service="backend"} |= "req_abc123"
   ```

---

## 3. Metric Cardinality Review & Policy

A critical hazard in production telemetry is **metric label cardinality explosion**, which causes unbounded memory allocation in the Prometheus Time Series Database (TSDB).

### Strict Cardinality Invariants
1. **Never use unbound variables as metric labels**:
   - $\times$ **Forbidden**: `request_id`, `user_id`, `session_token`, `request_payload`, `prediction_output`, `error_message`.
   - $\checkmark$ **Permitted**: `method` (GET, POST), `status` (200, 401, 500), `endpoint` (sanitized base path), `model` (model_id), `replica_id` (finite container name), `error_type` (Exception class name).
2. **Endpoint Sanitization**:
   The backend applies `sanitize_endpoint(path)` before passing routes to Prometheus:
   - Dynamic paths like `/api/v1/models/iris-v1/predict` are sanitized to `/api/v1/models/{model_id}/predict`.
   - High-cardinality query parameters are completely stripped.
3. **Correlation Belongs in Logs**:
   Unique request tokens (`X-Request-ID`) are attached to log metadata, allowing pinpoint investigation without generating tens of thousands of ephemeral metric series.

---

## 4. Structured Logging Standards

All ModelForge microservices utilize Python's `StructuredJsonFormatter` emitting JSON objects to stdout:

```json
{
  "timestamp": "2026-09-30T05:01:02.719499+00:00",
  "level": "INFO",
  "service": "backend",
  "logger": "backend",
  "message": "HTTP request completed",
  "request_id": "req-987654321",
  "event": "http_request",
  "endpoint": "/api/v1/models",
  "method": "GET",
  "status_code": 200,
  "latency_ms": 1.45
}
```

### Sensitive Data Redaction
The logger recursively sanitizes dictionary payloads before serialization:
- Keys matching `password`, `token`, `secret`, `authorization`, `credentials`, or `private_key` are replaced with `"[REDACTED]"`.
- Request and response bodies exceeding 1 KB are truncated to prevent log explosion.

---

## 5. Request Correlation Flow

```
[Client]
   │
   ├─► Sends HTTP Request with 'X-Request-ID: req-777' (or generated by client.js)
   │
[ModelForge Backend Middleware]
   │
   ├─► Captures X-Request-ID (or generates UUID4 if missing)
   ├─► Stores in request.state.request_id
   ├─► Forwards 'X-Request-ID: req-777' to model-server /predict
   │
[Model-Server Middleware]
   │
   ├─► Captures X-Request-ID
   ├─► Executes model inference
   ├─► Emits structured error/success log with "request_id": "req-777"
   ├─► Returns response with 'X-Request-ID: req-777'
   │
[Backend Response]
   │
   ├─► Emits structured access log with "request_id": "req-777", latency_ms, status
   └─► Returns final response to Client with 'X-Request-ID: req-777'
```

---

## 6. Dashboards & Visualization (Grafana)

Four dashboards are pre-provisioned via Kubernetes ConfigMaps in Grafana 10.4.0:

1. **Dashboard 1: ModelForge Overview** (`uid: modelforge-overview`):
   - Request throughput rate (`sum(rate(modelforge_http_requests_total[1m]))`)
   - HTTP Error Rate (`sum(rate(modelforge_http_errors_total[1m]))`)
   - P95 and P99 API Latency (`histogram_quantile(0.95/0.99, ... modelforge_http_request_duration_seconds_bucket)`)
   - Active Model Replicas & HPA Desired Replicas
2. **Dashboard 2: Kubernetes Infrastructure** (`uid: modelforge-kubernetes`):
   - Pod CPU Usage in cores (`sum(rate(container_cpu_usage_seconds_total[1m])) by (pod)`)
   - Pod Working Set Memory (`sum(container_memory_working_set_bytes) by (pod)`)
   - Pod Container Restarts (`sum(kube_pod_container_status_restarts_total) by (pod)`)
   - Ready Replicas per Deployment
   - HPA Current vs. Desired autoscaling state
3. **Dashboard 3: ML Inference Telemetry** (`uid: modelforge-ml-inference`):
   - Model Prediction Throughput rate
   - Model Inference P95 / P99 Latency
   - Prediction Errors per Model
   - Model Loaded Status indicator (`modelforge_model_server_loaded_status`)
   - Active in-flight requests gauge
4. **Dashboard 4: Security & Operational Events** (`uid: modelforge-security-operations`):
   - Authentication Failures rate (`sum(rate(modelforge_auth_failures_total[1m]))`)
   - Storage S3 Operations & Errors (`modelforge_storage_operations_total`)
   - Deployment Creation & Termination counters
   - Live Loki log stream filtered for security and error events

---

## 7. Cloud Observability Mapping (Future Reference)

While Phase 14 is 100% locally implemented on Docker Desktop Kubernetes at zero cost, the architecture directly maps to major public cloud observability services:

| Component | Local Implementation | Google Cloud (GCP) | Amazon Web Services (AWS) | Microsoft Azure |
| :--- | :--- | :--- | :--- | :--- |
| **Metrics Collector** | Prometheus v2.51.0 | Google Cloud Managed Service for Prometheus (GMP) | Amazon Managed Service for Prometheus (AMP) | Azure Monitor Managed Service for Prometheus |
| **Log Collector** | Promtail DaemonSet | Fluent Bit / Ops Agent | AWS Distro for OpenTelemetry / Fluent Bit | Azure Monitor Container Insights Agent |
| **Log Storage** | Grafana Loki v2.9.8 | Google Cloud Logging | Amazon CloudWatch Logs | Azure Monitor Logs (Log Analytics Workspace) |
| **Dashboards** | Grafana v10.4.0 | Cloud Monitoring Dashboards / Managed Grafana | Amazon Managed Grafana | Azure Managed Grafana |
| **Alerting** | Prometheus Alert Rules | Cloud Monitoring Alerting Policies | CloudWatch Alarms / EventBridge | Azure Monitor Alert Rules |
| **Correlation** | X-Request-ID Header | Google Cloud Trace (`X-Cloud-Trace-Context`) | AWS X-Ray (`X-Amzn-Trace-Id`) | Azure Application Insights / W3C TraceContext |

---

## 8. Summary

The ModelForge Phase 14 architecture provides robust, production-grade observability with zero external cloud dependencies. By coupling fine-grained metrics with correlated structured logging and pre-provisioned dashboards, operators gain immediate situational awareness into application health, ML performance, and cluster autoscaling.
