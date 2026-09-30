# ModelForge — Database & Persistence Architecture

This document describes the persistence architecture of ModelForge, including the repository abstraction, hybrid data placement, and readiness for future cloud infrastructure (Phase 9+).

---

## 1. Hybrid Persistence Strategy

ModelForge follows a tiered data architecture designed for cloud scalability, operational performance, and zero unnecessary cloud costs.

```text
                           ModelForge Application Layer
                                        |
     +----------------------------------+----------------------------------+
     |                                  |                                  |
     v                                  v                                  v
+-------------------------+  +-------------------------+  +-------------------------+
|   Cloud Firestore       |  |   Local Storage Layer   |  |   Local Metrics Store   |
|   (Application State)   |  |   (Artifact Store)      |  |   (High-Volume Logs)    |
+-------------------------+  +-------------------------+  +-------------------------+
| - Model metadata        |  | - Trained .joblib files |  | - Per-request latency   |
| - Model version tags    |  | - Serialized estimators |  | - Throughput metrics    |
| - Deployment slots      |  | - Class prediction maps |  | - Operational counters  |
| - Auto-scaling policies |  |                         |  | - Health events         |
| - User profiles & RBAC  |  |                         |  |                         |
| - Immutable audit logs  |  |                         |  |                         |
+-------------------------+  +-------------------------+  +-------------------------+
```

### Architectural Rationale

1. **Firestore for Relational & Document Metadata:**
   - Perfect for model descriptors, deployment state, user roles, and audit events.
   - Low write frequency, high read value across multi-client dashboards.
   - Fits well within the Firebase Spark free plan quota (50k reads/day, 20k writes/day).

2. **Local Storage for Heavy Model Artifacts:**
   - Firestore has a hard **1MB limit per document**. Model artifacts easily reach 10MB to 50MB.
   - Storing binaries in Cloud Storage could trigger paid network egress or plan constraints.
   - Abstracted behind `ModelArtifactStore` ([backend/app/services/storage/interface.py](file:///c:/college/ModelForge-Phase5-source/backend/app/services/storage/interface.py)), so in Phase 11 it can cleanly switch to GCS / S3 buckets without modifying API endpoints.

3. **Local Store for High-Frequency Inference Telemetry:**
   - Every inference request generates a telemetry record (`latency_ms`, `replica_id`, `status`).
   - In benchmark or load-test scenarios with 50-100 RPS, direct Firestore writes would exhaust the 20,000 write/day free tier in under 10 minutes.
   - Retaining `inference_logs` in SQLite / local time-series store provides instant NumPy aggregation (P95, P99) without network latency or cloud charges.

---

## 2. Repository Abstraction Pattern

FastAPI routers interact solely with repository interfaces rather than raw database drivers or ORM sessions:

```text
FastAPI Router
      ↓
Factory Provider (get_model_repository, get_deployment_repository)
      ↓
Repository Interface (IModelRepository, IDeploymentRepository)
      ↓
Concrete Implementation (SQLiteRepository | FirestoreRepository)
```

### Benefits:
- **Zero Lock-In:** The application can run fully offline on SQLite, or fully cloud-backed on Firestore, simply by toggling `DATABASE_BACKEND=sqlite|firestore`.
- **Test Reliability:** The existing test suite runs against SQLite without requiring external Firebase internet connectivity or mocks.
- **Phase 9 Kubernetes Readiness:** Containerized pods can connect to Firestore for shared state, while replica containers mount persistent volumes for model files.
