# ModelForge — Firebase & Cloud-Ready Architecture

## 1. System Overview

In Phase 8.5, ModelForge integrates Firebase as the cloud-backed identity and persistence layer while preparing the application architecture for Phase 9 Kubernetes and deeper cloud infrastructure.

### Architectural Evolution

```text
+-------------------------------------------------------------------------+
|                              React Frontend                             |
|  (Vite SPA + Tailwind CSS + Firebase Web SDK + Local Storage Fallback)  |
+-------------------------------------------------------------------------+
                                   |
         +-------------------------+-------------------------+
         |                                                   |
         v                                                   v
+-------------------------------+             +---------------------------+
|    Firebase Authentication    |             |      FastAPI Backend      |
|  (User Identity, ID Tokens,   |             | (Token verification, RBAC |
|     Password Management)      |             |   lifecycles, scheduler)  |
+-------------------------------+             +---------------------------+
                 |                                          |
                 +----------------- ID Token ---------------+
                                                            |
                                                            v
                                            +-------------------------------+
                                            |     Repository Abstraction    |
                                            | (IModelRepo, IDeploymentRepo) |
                                            +-------------------------------+
                                                            |
                                        +-------------------+-------------------+
                                        |                                       |
                                        v                                       v
                        +-------------------------------+       +-------------------------------+
                        |       Cloud Firestore         |       |      Local Storage Layer      |
                        | (Metadata, Configs, Profiles, |       | (Binary .joblib model files,  |
                        |      Deployments, Audit)      |       |  high-volume inference logs)  |
                        +-------------------------------+       +-------------------------------+
```

---

## 2. Component Responsibility Matrix

| Entity | Destination Layer | Storage Medium | Justification |
|---|---|---|---|
| **User Identity & Passwords** | Firebase Authentication | Google Identity Platform | Eliminates storing plaintext/hashed passwords in our database; industry-standard token-based identity. |
| **User Profiles & Roles** | Firestore | `users/{uid}` | Retains application-specific authorization roles (`ADMIN`, `OPERATOR`, `VIEWER`), display names, and account activity. |
| **Model Metadata** | Firestore | `models/{model_id}` | Logical model groupings, created timestamps, creator attribution. |
| **Model Version Records** | Firestore | `models/{id}/versions/{v_id}` | Version descriptors, framework metadata, file size, class capabilities, and storage paths. |
| **Deployment Records** | Firestore | `deployments/{deployment_id}` | Deployment slots, target replicas, active replica count, container status, and endpoints. |
| **Replica Instances** | Firestore | `deployments/{id}/replicas/{rep_id}` | Runtime state of running containers or local process instances. |
| **Auto-Scaling Policies** | Firestore | `deployments/{id}/autoscaling_config/current` | Configured scaling bounds (min/max), target latency thresholds, cooldown intervals. |
| **Audit Events** | Firestore | `audit_events/{event_id}` | Centralized, append-only security and operational audit trail. |
| **Model Binary Artifacts** | Local Filesystem | `storage/models/...` | Binary files up to 50MB; keeping them in the local artifact store prevents Firestore 1MB document limit violations and avoids cloud storage billing. |
| **Inference Telemetry** | Local Storage (SQLite) | `inference_logs` table | High-frequency telemetry (every single prediction). Keeping this local prevents exceeding the Firebase Spark free plan quota (20,000 writes/day). |

---

## 3. Firestore Data Model

### Collection: `users`
- **Path:** `/users/{uid}`
- **Document ID:** Firebase Auth User UID (`uid`)
- **Fields:**
  - `id`: `string`
  - `email`: `string` (normalized lowercase)
  - `display_name`: `string`
  - `role`: `string` (`"ADMIN" | "OPERATOR" | "VIEWER"`)
  - `is_active`: `boolean`
  - `created_at`: `timestamp`
  - `updated_at`: `timestamp`
  - `last_login_at`: `timestamp | null`

### Collection: `models`
- **Path:** `/models/{model_id}`
- **Document ID:** 12-character hex UUID
- **Fields:**
  - `id`: `string`
  - `name`: `string` (unique logical identifier, e.g. `fraud_detector`)
  - `created_at`: `timestamp`
  - `created_by`: `string | null` (User UID)

#### Subcollection: `versions`
- **Path:** `/models/{model_id}/versions/{version_id}`
- **Document ID:** 12-character hex UUID
- **Fields:**
  - `id`: `string`
  - `model_id`: `string`
  - `version`: `string` (e.g. `v1`, `v2`)
  - `framework`: `string` (`"sklearn"`)
  - `model_type`: `string | null`
  - `supports_proba`: `boolean`
  - `original_filename`: `string`
  - `stored_filename`: `string`
  - `file_path`: `string` (relative or absolute path in artifact storage)
  - `file_size_bytes`: `integer`
  - `status`: `string` (`"uploaded" | "active"`)
  - `is_active`: `boolean`
  - `created_at`: `timestamp`

### Collection: `deployments`
- **Path:** `/deployments/{deployment_id}`
- **Document ID:** 12-character hex UUID
- **Fields:**
  - `id`: `string`
  - `model_id`: `string`
  - `model_version_id`: `string`
  - `version_label`: `string`
  - `status`: `string` (`"deploying" | "running" | "stopped" | "failed"`)
  - `endpoint`: `string | null`
  - `replicas`: `integer`
  - `active_replicas`: `integer`
  - `scaling_status`: `string` (`"stable" | "scaling_up" | "scaling_down"`)
  - `is_containerized`: `boolean`
  - `error_message`: `string | null`
  - `created_at`: `timestamp`
  - `updated_at`: `timestamp`

#### Subcollection: `replicas`
- **Path:** `/deployments/{deployment_id}/replicas/{replica_id}`
- **Document ID:** 12-character hex UUID
- **Fields:**
  - `id`: `string`
  - `deployment_id`: `string`
  - `replica_id`: `string` (e.g. `replica_1`)
  - `status`: `string` (`"healthy" | "unhealthy"`)
  - `requests_count`: `integer`
  - `total_latency_ms`: `float`
  - `container_id`: `string | null`
  - `container_port`: `integer | null`
  - `endpoint_url`: `string | null`
  - `is_containerized`: `boolean`
  - `created_at`: `timestamp`
  - `updated_at`: `timestamp`

#### Subcollection: `autoscaling_config`
- **Path:** `/deployments/{deployment_id}/autoscaling_config/current`
- **Fields:**
  - `id`: `string`
  - `deployment_id`: `string`
  - `enabled`: `boolean`
  - `min_replicas`: `integer`
  - `max_replicas`: `integer`
  - `target_latency_ms`: `float`
  - `target_throughput_rps`: `float`
  - `scale_up_error_rate_percent`: `float`
  - `scale_down_idle_seconds`: `integer`
  - `cooldown_seconds`: `integer`
  - `evaluation_interval_seconds`: `integer`
  - `last_evaluated_at`: `timestamp | null`
  - `last_scaled_at`: `timestamp | null`
  - `created_at`: `timestamp`
  - `updated_at`: `timestamp`

### Collection: `audit_events`
- **Path:** `/audit_events/{event_id}`
- **Document ID:** 12-character hex UUID
- **Fields:**
  - `id`: `string`
  - `timestamp`: `timestamp`
  - `user_id`: `string | null`
  - `user_email`: `string | null`
  - `action`: `string` (e.g. `"MODEL_UPLOADED"`, `"DEPLOYMENT_SCALED"`)
  - `resource_type`: `string`
  - `resource_id`: `string | null`
  - `details`: `string | null` (JSON-serialized with secrets redacted)
  - `ip_address`: `string | null`
  - `success`: `boolean`

---

## 4. Security & Least Privilege

Firestore Security Rules enforce strict access controls:
1. **Unauthenticated Access:** Completely forbidden across all collections.
2. **Users Collection:** Users can only view and modify their own non-privileged profile data. Only users with role `ADMIN` can view all users, modify roles, or delete users.
3. **Model & Deployment Collections:** Viewers can read; mutations require `OPERATOR` or `ADMIN`.
4. **Audit Trail:** Read-only for `ADMIN`; direct client creation is disabled (`allow write: if false`) because writes occur exclusively via the backend Firebase Admin SDK.
