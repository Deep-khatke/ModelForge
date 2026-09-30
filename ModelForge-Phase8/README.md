# ModelForge

An automated, cloud-ready platform for ML model registration, deployment,
scaling, monitoring, intelligent reliability automation, and enterprise security.

**Phase 8** introduces **Authentication, Authorization & Audit Security**:
secure JWT-based user authentication, role-based access control (RBAC) with `ADMIN`, `OPERATOR`,
and `VIEWER` roles, immutable audit event logging with CSV exports, and administrative user management.
All endpoints support backwards-compatible local development (`AUTH_ENABLED=false`) while providing
full enterprise security guards and non-breaking admin bootstrap when enabled.

---

## Project Structure

```
ModelForge/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI application entrypoint, startup bootstrap & lifespan scheduler
│   │   ├── config.py             # Configuration loaded from environment variables (inc. JWT & auth settings)
│   │   ├── database.py           # SQLAlchemy engine/session (SQLite & PostgreSQL ready)
│   │   ├── dependencies.py       # Auth dependencies: get_current_user, require_roles, dev fallback
│   │   ├── models.py             # ORM models: User, AuditEvent, AutoScalingConfig, ScalingEvent, Deployment, etc.
│   │   ├── schemas.py            # Pydantic request/response schemas (UserOut, TokenResponse, AuditEventOut, etc.)
│   │   ├── container_engine.py   # Docker container manager, health checks & HTTP client
│   │   ├── replica_manager.py    # Multi-replica manager, container scaler & round-robin router
│   │   ├── model_inspector.py    # Loads uploaded artifacts to inspect metadata
│   │   ├── utils.py              # Filename sanitization & version numbering
│   │   ├── routers/
│   │   │   ├── auth.py           # /api/v1/auth endpoints (login, register, logout, me)
│   │   │   ├── users.py          # /api/v1/users admin endpoints (list, create, update, delete)
│   │   │   ├── audit.py          # /api/v1/audit endpoints (query events, CSV export)
│   │   │   ├── models.py         # /api/v1/models endpoints (protected with RBAC & audit logging)
│   │   │   ├── deployments.py    # /api/v1/deployments endpoints (protected with RBAC & audit logging)
│   │   │   ├── autoscaling.py    # /api/v1/deployments/{id}/autoscaling & evaluate endpoints
│   │   │   ├── monitoring.py     # /api/v1/monitoring endpoints
│   │   │   └── experiments.py    # /api/v1/experiments endpoints
│   │   └── services/
│   │       ├── auth_service.py        # Password hashing (bcrypt), JWT creation/decoding, admin bootstrap
│   │       ├── audit_service.py       # Sanitized audit event logging, querying & CSV generator
│   │       ├── autoscaling_service.py # Core auto-scaling engine, telemetry analysis & scheduler
│   │       ├── monitoring_service.py  # Metrics aggregation, alerts & CSV export
│   │       └── experiment_service.py  # Controlled benchmark runner
│   ├── storage/models/           # Model artifacts stored on disk
│   ├── tests/                    # Comprehensive pytest test suite (68 tests)
│   │   └── test_auth_and_security.py # Phase 8 security, RBAC & audit test suite
│   ├── Dockerfile                # Backend container image definition
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/           # React dashboard, LoginModal, UserManagement, AuditLogViewer, etc.
│   │   └── api/client.js         # API client with token storage and Authorization Bearer headers
│   ├── Dockerfile                # Multi-stage production Nginx frontend container
│   ├── nginx.conf                # Nginx reverse proxy configuration
│   └── package.json
├── inference_service/
│   ├── main.py                   # Standalone inference replica microservice (/health, /predict)
│   ├── Dockerfile                # Lightweight, unprivileged replica container image
│   └── requirements.txt
├── docker-compose.yml            # Multi-container orchestration (backend, frontend, replica image, db)
└── README.md
```

---

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** and npm
- **Docker & Docker Compose** (recommended for containerized replicas; optional if running in local fallback mode)

---

## Quickstart with Docker Compose

Start the complete ModelForge stack with one command:

```bash
docker compose up --build
```

This starts:
1. **`inference-image`**: Builds `modelforge-inference:latest` for replica instantiation.
2. **`backend`**: Control plane running at `http://localhost:8000` (interactive API docs at `http://localhost:8000/docs`).
3. **`frontend`**: Web dashboard running at `http://localhost:5173` with Nginx reverse proxy.
4. **`db`**: PostgreSQL 16 database running on port 5432 (ready for production use).

---

## Local Development Setup (Without Docker)

When running locally without Docker or where Docker is unavailable, ModelForge
automatically runs in **backward-compatible local process fallback mode**.

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend Setup

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Dashboard will be live at `http://localhost:5173`.

---

## Environment Configuration

All settings are configured via environment variables or a local `.env` file in `backend/`:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./modelforge.db` | Database URL. Supports SQLite (`sqlite:///...`) and PostgreSQL (`postgresql://user:pass@host:5432/db`). |
| `DOCKER_ENABLED` | `false` | Enable real Docker container replicas. When `false`, ModelForge uses local process fallback. |
| `DOCKER_NETWORK` | `modelforge-network` | Docker bridge network to attach inference containers to. |
| `INFERENCE_IMAGE` | `modelforge-inference:latest` | Docker image name for inference replica containers. |
| `MODEL_STORAGE_MOUNT` | `None` | Named Docker volume or host path to mount into replica containers at `/models:ro`. |
| `MODEL_STORAGE_DIR` | `./storage/models` | Local directory for storing model artifacts. |
| `CONTAINER_HEALTHCHECK_TIMEOUT_SEC` | `5.0` | Timeout in seconds for polling container `/health` endpoint. |
| `CONTAINER_PORT_START` | `8100` | Starting port range for container host port binding. |
| `MAX_REPLICAS` | `5` | Maximum number of replicas allowed per deployment. |
| `DEFAULT_REPLICAS` | `1` | Default replica count for new deployments. |
| `AUTOSCALING_BACKGROUND_ENABLED` | `true` | Enable the periodic background auto-scaling evaluation loop. |
| `AUTOSCALING_LOOP_SLEEP_SECONDS` | `10` | Sleep interval in seconds between background scheduler evaluation cycles. |
| `AUTOSCALING_DEFAULT_MIN_REPLICAS` | `1` | Default minimum replica bound for new auto-scaling policies. |
| `AUTOSCALING_DEFAULT_MAX_REPLICAS` | `5` | Default maximum replica bound for new auto-scaling policies. |
| `AUTOSCALING_DEFAULT_TARGET_LATENCY_MS` | `200.0` | Target P95 latency threshold in ms before triggering scale-up. |
| `AUTOSCALING_DEFAULT_TARGET_THROUGHPUT_RPS` | `50.0` | Target throughput capacity threshold (RPS) before triggering scale-up. |
| `AUTOSCALING_DEFAULT_ERROR_RATE_PERCENT` | `10.0` | Error rate percentage threshold before triggering scale-up. |
| `AUTOSCALING_DEFAULT_IDLE_SECONDS` | `120` | Inactivity threshold before triggering scale-down toward minimum replicas. |
| `AUTOSCALING_DEFAULT_COOLDOWN_SECONDS` | `60` | Cooldown period between scaling adjustments to prevent oscillation. |
| `AUTOSCALING_DEFAULT_EVALUATION_INTERVAL` | `30` | Sliding telemetry window duration in seconds for metrics analysis. |
| `ALERT_LATENCY_THRESHOLD_MS` | `500.0` | Latency threshold for triggering in-app operational alerts. |
| `ALERT_ERROR_RATE_THRESHOLD_PERCENT` | `5.0` | Error rate threshold for triggering in-app operational alerts. |
| `MONITORING_RETENTION_DAYS` | `30` | Number of days to retain inference telemetry records. |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Allowed CORS origins for browser dashboard. |

---

## Deploy → Scale → Infer → Auto-Scale Workflow

1. **Register a Model**:
   - Upload a `.joblib` model artifact via dashboard or `POST /api/v1/models/upload`.
   - The artifact is stored safely with automated versioning (`v1`, `v2`).

2. **Deploy Replicas**:
   - Call `POST /api/v1/deployments` with `{"model_id": "...", "replicas": 2}`.
   - If `DOCKER_ENABLED=true`, ModelForge launches isolated containers from `modelforge-inference:latest`, mounting the model storage read-only (`:ro`).
   - If Docker is disabled, ModelForge falls back to local simulation.
   - Health checks verify that replicas are responding before setting status to `running`.

3. **Configure Intelligent Auto-Scaling**:
   - Auto-scaling is **disabled by default** on all deployments to maintain complete operational control.
   - Configure policy parameters via the **Auto-Scaling & Reliability** tab or `PUT /api/v1/deployments/{id}/autoscaling`:
     ```json
     {
       "enabled": true,
       "min_replicas": 1,
       "max_replicas": 4,
       "target_latency_ms": 150.0,
       "target_throughput_rps": 30.0,
       "scale_up_error_rate_percent": 5.0,
       "scale_down_idle_seconds": 90,
       "cooldown_seconds": 45
     }
     ```
   - Auto-scaling immediately respects bounded minimum and maximum replica limits.

4. **Send Inference Traffic & Observe Autoscaling**:
   - Call `POST /api/v1/models/{model_id}/predict` with feature payloads.
   - ModelForge's Round-Robin load balancer routes requests across healthy replicas and records high-precision telemetry.
   - Under load spikes (P95 latency breach, throughput saturation, or error spike), the auto-scaling engine automatically adds replicas.
   - During quiet or idle periods, the engine gradually scales replicas down by 1 step at a time until reaching `min_replicas`.
   - Every scaling action, evaluation reason, observed metrics, and cooldown state is persistently logged in `scaling_events`.

5. **Manual Scaling Interoperability**:
   - Operators can manually override replica counts at any time via `POST /api/v1/deployments/{id}/scale`.
   - Manual scaling updates active containers immediately, respects boundaries, and logs scaling events.

6. **Monitor, Benchmark & Audit**:
   - Inspect real-time status cards, trigger criteria, and historical audit logs in the **Auto-Scaling & Reliability** dashboard.
   - Review live percentiles and per-replica distribution on the **Monitoring & Telemetry** dashboard.
   - Controlled benchmarks in **Performance Experiments** record `autoscaling_enabled` metadata.

7. **Stop / Clean Up**:
   - Stopping (`POST /api/v1/deployments/{id}/stop`) or deleting a deployment automatically halts all containers and disables scaling evaluations.

---

## Authentication, Authorization & RBAC

ModelForge provides enterprise-grade user authentication and Role-Based Access Control (RBAC):

### Permissions Matrix

| Action | ADMIN | OPERATOR | VIEWER |
|---|:---:|:---:|:---:|
| View models, versions, deployments, telemetry | ✅ | ✅ | ✅ |
| Execute model inference (`POST /models/{id}/predict`) | ✅ | ✅ | ✅ |
| Upload models (`POST /models/upload`) | ✅ | ✅ | ❌ |
| Deploy & undeploy models (`POST /deployments`, `POST /stop`) | ✅ | ✅ | ❌ |
| Scale deployment replicas (`POST /deployments/{id}/scale`) | ✅ | ✅ | ❌ |
| Configure auto-scaling (`PUT /deployments/{id}/autoscaling`) | ✅ | ✅ | ❌ |
| Run performance experiments (`POST /experiments/run`) | ✅ | ✅ | ❌ |
| User management (create, update, deactivate, delete) | ✅ | ❌ | ❌ |
| View audit logs & export audit CSV | ✅ | ❌ | ❌ |

### Initial Administrator Bootstrap

When `AUTH_ENABLED=true`, ModelForge automatically bootstraps an initial administrator on startup if no accounts exist:
- **Default Email**: `admin@modelforge.local` (configurable via `INITIAL_ADMIN_EMAIL`)
- **Default Password**: `Admin123!` (configurable via `INITIAL_ADMIN_PASSWORD`)
- **Default Display Name**: `Administrator` (configurable via `INITIAL_ADMIN_NAME`)

### Local Development Compatibility

When `AUTH_ENABLED=false` (default for local prototyping), the API transparently runs in backwards-compatible development mode without requiring authorization headers.

---

## Phase 8 Security & Audit API Reference

| Endpoint | Method | Role | Description |
|---|---|:---:|---|
| `/api/v1/auth/login` | `POST` | Public | Authenticate with email/password; returns JWT bearer token. |
| `/api/v1/auth/register` | `POST` | Public | Register new user account (if `ALLOW_PUBLIC_REGISTRATION=true`). |
| `/api/v1/auth/me` | `GET` | Authenticated | Return currently authenticated user profile and role permissions. |
| `/api/v1/auth/logout` | `POST` | Authenticated | Log session termination and record security audit event. |
| `/api/v1/users` | `GET` | ADMIN | List all registered user accounts. |
| `/api/v1/users` | `POST` | ADMIN | Create new user account with role assignment. |
| `/api/v1/users/{id}` | `GET` | ADMIN | Retrieve single user account details. |
| `/api/v1/users/{id}` | `PUT` | ADMIN | Update user role, active status, display name, or password. |
| `/api/v1/users/{id}` | `DELETE` | ADMIN | Delete user account permanently (prevents self-deletion). |
| `/api/v1/audit/events` | `GET` | ADMIN | Filter & paginate immutable audit trail events. |
| `/api/v1/audit/export` | `GET` | ADMIN | Export audit events as CSV file. |

---

## Auto-Scaling API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/v1/deployments/{id}/autoscaling` | `GET` | Get current auto-scaling configuration and bounds for a deployment. |
| `/api/v1/deployments/{id}/autoscaling` | `PUT` | Update auto-scaling configuration (enable/disable, thresholds, cooldown). |
| `/api/v1/deployments/{id}/autoscaling/evaluate` | `POST` | Manually trigger an immediate auto-scaling evaluation for a deployment. |
| `/api/v1/deployments/{id}/scaling-events` | `GET` | Retrieve persistent audit history of scaling decisions and triggers. |
| `/api/v1/autoscaling/evaluate` | `POST` | Trigger system-wide evaluation for all active deployments with auto-scaling enabled. |

---

## Reliability & Safety Protections

- **Cooldown Enforcement**: Enforces a configurable cooldown period (default 60s) after any scaling event to eliminate rapid oscillation or flapping.
- **Telemetry Sufficiency Requirement**: Requires at least 3 telemetry samples within the evaluation window before performing statistical scaling decisions, preventing flapping on near-empty metrics.
- **Conservative Scale-Down**: Decreases replicas by 1 step at a time to prevent abrupt capacity drops during transient dips in load.
- **Hard Bounds Clamp**: Replicas never scale below `min_replicas` (minimum 1) or above `max_replicas` (capped at system `MAX_REPLICAS`).
- **Read-Only Model Mounts**: Replica containers mount model files with `:ro` (read-only) mode.
- **Unprivileged Containers**: Inference containers execute under a dedicated unprivileged user (`modelforge`).
- **Sanitized Audit Records**: Passwords, secrets, and raw authentication credentials are automatically scrubbed from all audit event payloads.

---

## Running Automated Tests

Run the full pytest suite from the `backend/` directory:

```bash
cd backend
python -m pytest -v
```

The test suite includes **68 comprehensive automated tests**:
- `tests/test_auth_and_security.py`: Password hashing & verification, JWT issuance & decoding, admin bootstrap, login failure audit, public registration, RBAC role permissions (Admin, Operator, Viewer), user lifecycle (create/update/deactivate/delete/self-deletion guard), audit querying and CSV export, and backwards-compatible unauthenticated fallback mode.
- `tests/test_autoscaling.py`: Auto-scaling configuration defaults, input validation bounds, P95 latency triggers, throughput triggers, error rate triggers, idle scale-down, cooldown enforcement, maximum replica clamping, telemetry sufficiency protection, manual scaling interoperability, system evaluate endpoints, and operational alerts integration.
- `tests/test_container_deployment.py`: Container lifecycle, scale up/down, container health state transitions, HTTP inference routing, and local fallback behavior.
- `tests/test_deployments_api.py`: Deployment lifecycle, stop/delete, redeploy checks.
- `tests/test_scaling_and_replicas.py`: Dynamic scaling, replica bounds, round-robin load testing.
- `tests/test_monitoring_and_experiments.py`: Telemetry calculations, alerts, time-series, CSV exports.
- `tests/test_models_api.py`: Registry, versioning, file validation, deletion cascades.

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Model upload, registry, versioning, dashboard | Completed |
| 2 | Deployment manager: deploy a version, track status/replicas, stop/delete deployments | Completed |
| 3 | Real inference API (`POST /api/v1/models/{model_id}/predict`) with model execution | Completed |
| 4 | Scalable inference: multi-replica management, dynamic scaling, Round-Robin load balancing | Completed |
| 5 | Real request telemetry, monitoring dashboard, analytics, alerts, host resources, experiments | Completed |
| 6 | Containerized Deployment & Cloud-Ready Architecture (Docker Compose, isolated replica containers, real health checks, dynamic container scaling, safe fallback) | Completed |
| 7 | Intelligent Auto-Scaling & Reliability Automation (Real telemetry evaluation, P95 latency/RPS/error/idle triggers, cooldown hysteresis, bounds enforcement, scaling audit history, frontend dashboard) | Completed |
| **8** | **Authentication, Authorization & Audit Security (JWT auth, RBAC: ADMIN/OPERATOR/VIEWER, admin bootstrap, audit logging, CSV export, user management)** | **Completed** |
| 9 | Multi-Model Mesh & Advanced Traffic Splitting (Canary deployments, shadow testing, blue/green rollout automation, cloud storage adapters) | Planned |

---

## Known Local-MVP & Cloud-Readiness Limitations

- **Docker Host Socket Access**: The local Docker Compose setup mounts `/var/run/docker.sock` to enable the control plane to manage replica containers on Docker Engine. For multi-tenant or enterprise cloud deployments, orchestration can transition to Kubernetes (via Kubernetes API / CRDs) or AWS ECS / GCP Cloud Run.
- **Artifact Storage**: Model artifacts are stored on a shared Docker volume / local filesystem. Cloud production should integrate S3 or Google Cloud Storage.

