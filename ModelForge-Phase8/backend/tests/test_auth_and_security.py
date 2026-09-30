"""
Unit and integration tests for ModelForge Phase 8:
Authentication, Authorization & Audit Security.
"""
from __future__ import annotations

import sys
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def auth_env(tmp_path, monkeypatch):
    """
    Isolated environment with AUTH_ENABLED=true, initial admin bootstrapped,
    and a fresh database.
    """
    db_path = tmp_path / "auth_test.db"
    storage_dir = tmp_path / "auth_storage"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MODEL_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("AUTOSCALING_BACKGROUND_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-32-chars-minimum-length-req")
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "admin@modelforge.local")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "Admin123!")
    monkeypatch.setenv("INITIAL_ADMIN_NAME", "Bootstrap Administrator")
    monkeypatch.setenv("ALLOW_PUBLIC_REGISTRATION", "true")

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            sys.modules.pop(mod_name, None)

    import app.config as config_module
    import app.database as database_module
    import app.models as models_module
    import app.services.auth_service as auth_service_module
    import app.services.audit_service as audit_service_module
    import app.routers.auth as auth_router_module
    import app.routers.users as users_router_module
    import app.routers.audit as audit_router_module
    import app.routers.models as models_router_module
    import app.routers.deployments as deployments_router_module
    import app.routers.autoscaling as autoscaling_router_module
    import app.routers.monitoring as monitoring_router_module
    import app.routers.experiments as experiments_router_module
    import app.main as main_module

    with TestClient(main_module.app) as test_client:
        yield {
            "client": test_client,
            "db_factory": database_module.SessionLocal,
            "models": models_module,
            "auth_service": auth_service_module,
            "audit_service": audit_service_module,
        }


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["access_token"]


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -----------------------------------------------------------------------------
# 1. Cryptographic Security & Token Tests
# -----------------------------------------------------------------------------

def test_password_hashing_and_verification(auth_env):
    auth_service = auth_env["auth_service"]

    pw = "SuperSecurePassword99!"
    hashed = auth_service.hash_password(pw)
    assert hashed != pw
    assert auth_service.verify_password(pw, hashed) is True
    assert auth_service.verify_password("WrongPassword!", hashed) is False


def test_jwt_token_creation_and_decoding(auth_env):
    auth_service = auth_env["auth_service"]

    user_data = {"id": "user-123", "email": "alice@company.com", "role": "OPERATOR"}
    token = auth_service.create_access_token(user_data)
    assert isinstance(token, str)
    assert len(token) > 20

    payload = auth_service.decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert payload["email"] == "alice@company.com"
    assert payload["role"] == "OPERATOR"

    # Corrupt token verification
    bad_payload = auth_service.decode_access_token("corrupted.token.signature", raise_exceptions=False)
    assert bad_payload is None


def test_admin_bootstrap(auth_env):
    client = auth_env["client"]
    db_factory = auth_env["db_factory"]
    models = auth_env["models"]

    # Initial admin was created on startup
    with db_factory() as db:
        admin = db.query(models.User).filter_by(email="admin@modelforge.local").first()
        assert admin is not None
        assert admin.role == "ADMIN"
        assert admin.display_name == "Bootstrap Administrator"
        assert admin.is_active is True

    # Login as bootstrapped admin
    token = _login(client, "admin@modelforge.local", "Admin123!")
    assert token is not None

    # Calling /me with token
    res = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert res.status_code == 200
    assert res.json()["email"] == "admin@modelforge.local"
    assert res.json()["role"] == "ADMIN"


# -----------------------------------------------------------------------------
# 2. Authentication Flow & Security Events
# -----------------------------------------------------------------------------

def test_login_failure_and_audit(auth_env):
    client = auth_env["client"]
    db_factory = auth_env["db_factory"]
    models = auth_env["models"]

    # Invalid password
    bad_res = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@modelforge.local", "password": "WrongPassword!"},
    )
    assert bad_res.status_code == 401
    assert "Invalid email or password" in bad_res.json()["detail"]

    # Check that LOGIN_FAILED was recorded in audit log
    with db_factory() as db:
        evt = (
            db.query(models.AuditEvent)
            .filter_by(action="LOGIN_FAILED")
            .order_by(models.AuditEvent.timestamp.desc())
            .first()
        )
        assert evt is not None
        assert evt.user_email == "admin@modelforge.local"
        assert evt.success is False


def test_public_registration_and_login(auth_env):
    client = auth_env["client"]

    # Register new user
    reg_res = client.post(
        "/api/v1/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "Password123!",
            "display_name": "New Platform User",
        },
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["role"] == "VIEWER"  # Default public role is VIEWER
    assert reg_data["email"] == "newuser@example.com"

    # Login with the newly registered user
    token = _login(client, "newuser@example.com", "Password123!")
    me_res = client.get("/api/v1/auth/me", headers=_auth_header(token))
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "newuser@example.com"
    assert me_res.json()["role"] == "VIEWER"


# -----------------------------------------------------------------------------
# 3. RBAC (Role-Based Access Control) Enforcement
# -----------------------------------------------------------------------------

def test_rbac_roles_permissions(auth_env, fake_joblib_bytes):
    client = auth_env["client"]

    # 1. Admin logs in and creates an OPERATOR and a VIEWER
    admin_token = _login(client, "admin@modelforge.local", "Admin123!")

    create_op_res = client.post(
        "/api/v1/users",
        headers=_auth_header(admin_token),
        json={
            "email": "operator@modelforge.local",
            "password": "OperatorPass123!",
            "display_name": "DevOps Engineer",
            "role": "OPERATOR",
        },
    )
    assert create_op_res.status_code == 201

    create_viewer_res = client.post(
        "/api/v1/users",
        headers=_auth_header(admin_token),
        json={
            "email": "viewer@modelforge.local",
            "password": "ViewerPass123!",
            "display_name": "Data Analyst",
            "role": "VIEWER",
        },
    )
    assert create_viewer_res.status_code == 201

    op_token = _login(client, "operator@modelforge.local", "OperatorPass123!")
    viewer_token = _login(client, "viewer@modelforge.local", "ViewerPass123!")

    # --- VIEWER Permissions Check ---
    # Viewer can view models
    assert client.get("/api/v1/models", headers=_auth_header(viewer_token)).status_code == 200
    # Viewer can view deployments
    assert client.get("/api/v1/deployments", headers=_auth_header(viewer_token)).status_code == 200
    # Viewer cannot upload model (Forbidden)
    upload_res = client.post(
        "/api/v1/models/upload",
        headers=_auth_header(viewer_token),
        data={"model_name": "viewer_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 403

    # Viewer cannot access User Management (Forbidden)
    assert client.get("/api/v1/users", headers=_auth_header(viewer_token)).status_code == 403

    # Viewer cannot access Audit Logs (Forbidden)
    assert client.get("/api/v1/audit/events", headers=_auth_header(viewer_token)).status_code == 403

    # --- OPERATOR Permissions Check ---
    # Operator can upload model
    op_upload = client.post(
        "/api/v1/models/upload",
        headers=_auth_header(op_token),
        data={"model_name": "op_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert op_upload.status_code == 201
    model_id = op_upload.json()["id"]

    # Operator can create deployment
    dep_res = client.post(
        "/api/v1/deployments",
        headers=_auth_header(op_token),
        json={"model_id": model_id, "replicas": 1},
    )
    assert dep_res.status_code == 201
    dep_id = dep_res.json()["id"]

    # Operator can scale deployment
    scale_res = client.post(
        f"/api/v1/deployments/{dep_id}/scale",
        headers=_auth_header(op_token),
        json={"replicas": 2},
    )
    assert scale_res.status_code == 200

    # Operator can update auto-scaling configuration
    as_res = client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        headers=_auth_header(op_token),
        json={"enabled": True, "min_replicas": 1, "max_replicas": 3},
    )
    assert as_res.status_code == 200

    # Operator can run performance benchmark experiment
    exp_res = client.post(
        "/api/v1/experiments/run",
        headers=_auth_header(op_token),
        json={"deployment_id": dep_id, "requests": 5},
    )
    assert exp_res.status_code == 201

    # Operator CANNOT access user management (Forbidden)
    assert client.get("/api/v1/users", headers=_auth_header(op_token)).status_code == 403

    # Operator CANNOT view audit logs (Forbidden)
    assert client.get("/api/v1/audit/events", headers=_auth_header(op_token)).status_code == 403

    # --- VIEWER can execute inference on the deployed model ---
    inf_res = client.post(
        f"/api/v1/models/{model_id}/predict",
        headers=_auth_header(viewer_token),
        json={"features": [0.5, 0.5]},
    )
    assert inf_res.status_code == 200
    assert "predictions" in inf_res.json()

    # --- ADMIN Permissions Check ---
    # Admin can access user management
    users_res = client.get("/api/v1/users", headers=_auth_header(admin_token))
    assert users_res.status_code == 200
    assert len(users_res.json()) >= 3

    # Admin can access audit logs
    audit_res = client.get("/api/v1/audit/events", headers=_auth_header(admin_token))
    assert audit_res.status_code == 200
    assert audit_res.json()["total"] > 0


# -----------------------------------------------------------------------------
# 4. User Lifecycle Management (Admin Only)
# -----------------------------------------------------------------------------

def test_user_management_lifecycle(auth_env):
    client = auth_env["client"]
    admin_token = _login(client, "admin@modelforge.local", "Admin123!")

    # 1. Create a user
    create_res = client.post(
        "/api/v1/users",
        headers=_auth_header(admin_token),
        json={
            "email": "temp@example.com",
            "password": "Password123!",
            "display_name": "Temporary User",
            "role": "VIEWER",
        },
    )
    assert create_res.status_code == 201
    user_id = create_res.json()["id"]

    # 2. Update user role and display name
    update_res = client.put(
        f"/api/v1/users/{user_id}",
        headers=_auth_header(admin_token),
        json={"role": "OPERATOR", "display_name": "Promoted Operator"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["role"] == "OPERATOR"
    assert update_res.json()["display_name"] == "Promoted Operator"

    # 3. Deactivate user
    deact_res = client.put(
        f"/api/v1/users/{user_id}",
        headers=_auth_header(admin_token),
        json={"is_active": False},
    )
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Deactivated user cannot login
    bad_login = client.post(
        "/api/v1/auth/login",
        json={"email": "temp@example.com", "password": "Password123!"},
    )
    assert bad_login.status_code == 403
    assert "deactivated" in bad_login.json()["detail"].lower()

    # 4. Delete user
    del_res = client.delete(f"/api/v1/users/{user_id}", headers=_auth_header(admin_token))
    assert del_res.status_code == 204

    # Confirm deleted
    get_res = client.get(f"/api/v1/users/{user_id}", headers=_auth_header(admin_token))
    assert get_res.status_code == 404


def test_admin_cannot_delete_self(auth_env):
    client = auth_env["client"]
    admin_token = _login(client, "admin@modelforge.local", "Admin123!")

    # Get admin user ID
    me = client.get("/api/v1/auth/me", headers=_auth_header(admin_token)).json()
    admin_id = me["id"]

    # Attempt delete self
    del_res = client.delete(f"/api/v1/users/{admin_id}", headers=_auth_header(admin_token))
    assert del_res.status_code == 400
    assert "Cannot delete your own account" in del_res.json()["detail"]


# -----------------------------------------------------------------------------
# 5. Audit Logging & Export
# -----------------------------------------------------------------------------

def test_audit_logging_and_export(auth_env, fake_joblib_bytes):
    client = auth_env["client"]
    admin_token = _login(client, "admin@modelforge.local", "Admin123!")

    # Perform mutations that must be audited:
    # a. Upload model
    upload_res = client.post(
        "/api/v1/models/upload",
        headers=_auth_header(admin_token),
        data={"model_name": "audited_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    # b. Deploy model
    dep_res = client.post(
        "/api/v1/deployments",
        headers=_auth_header(admin_token),
        json={"model_id": model_id, "replicas": 1},
    )
    assert dep_res.status_code == 201
    dep_id = dep_res.json()["id"]

    # Query audit events
    audit_res = client.get("/api/v1/audit/events", headers=_auth_header(admin_token))
    assert audit_res.status_code == 200
    events = audit_res.json()["items"]

    actions = [e["action"] for e in events]
    assert "LOGIN_SUCCEEDED" in actions
    assert "MODEL_UPLOADED" in actions
    assert "DEPLOYMENT_CREATED" in actions

    # Filter audit events by action
    filter_res = client.get(
        "/api/v1/audit/events?action=MODEL_UPLOADED",
        headers=_auth_header(admin_token),
    )
    assert filter_res.status_code == 200
    filtered = filter_res.json()["items"]
    assert all(e["action"] == "MODEL_UPLOADED" for e in filtered)

    # Export audit events as CSV
    csv_res = client.get("/api/v1/audit/export", headers=_auth_header(admin_token))
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    csv_text = csv_res.text
    assert "Event ID,Timestamp (UTC),Action,Resource Type,Resource ID" in csv_text
    assert "MODEL_UPLOADED" in csv_text
    assert "DEPLOYMENT_CREATED" in csv_text


# -----------------------------------------------------------------------------
# 6. Backward Compatibility (AUTH_ENABLED=false)
# -----------------------------------------------------------------------------

def test_auth_disabled_fallback_compatibility(client, fake_joblib_bytes):
    """
    When AUTH_ENABLED=false (the standard test environment), all endpoints
    function seamlessly without any Authorization header.
    """
    # 1. Models and uploads work without tokens
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "dev_compat_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    # 2. Deployments work without tokens
    dep_res = client.post(
        "/api/v1/deployments",
        json={"model_id": model_id, "replicas": 1},
    )
    assert dep_res.status_code == 201
    dep_id = dep_res.json()["id"]

    # 3. Scaling works without tokens
    scale_res = client.post(
        f"/api/v1/deployments/{dep_id}/scale",
        json={"replicas": 2},
    )
    assert scale_res.status_code == 200

    # 4. Inference works without tokens
    inf_res = client.post(
        f"/api/v1/models/{model_id}/predict",
        json={"features": [0.1, 0.2]},
    )
    assert inf_res.status_code == 200

    # 5. /me endpoint returns dev admin fallback
    me_res = client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["role"] == "ADMIN"
