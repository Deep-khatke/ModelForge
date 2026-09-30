"""
Unit & Integration tests for ModelForge Phase 8.5:
Firebase Integration, Database Repositories, Artifact Storage & Migration.
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ["AUTOSCALING_BACKGROUND_ENABLED"] = "false"
os.environ["AUTH_ENABLED"] = "false"

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import joblib
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import Model, ModelVersion, User
from app.services.database.factory import (
    get_audit_repository,
    get_deployment_repository,
    get_model_repository,
    get_user_repository,
    is_firestore_enabled,
)
from app.services.database.sqlite_repository import (
    SQLiteAuditRepository,
    SQLiteDeploymentRepository,
    SQLiteModelRepository,
    SQLiteUserRepository,
)
from app.services.firebase.auth import verify_firebase_id_token
from app.services.firebase.client import (
    get_firebase_credentials_path,
    get_firebase_status,
    is_firebase_available,
)
from app.services.storage.local_storage import LocalStorageArtifactStore
from scripts.migrate_sqlite_to_firebase import MigrationStats, migrate


class DummyModel:
    """Lightweight mock model for artifact serialization tests."""
    def predict(self, X):
        return [1] * len(X)


@pytest.fixture
def db_session(tmp_path):
    """Isolated SQLite session with schema created for repository tests."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    import app.models  # noqa: F401

    db_path = tmp_path / "repo_test.db"
    test_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()


# --- 1. Artifact Storage Abstraction Tests -----------------------------------

def test_local_artifact_store(tmp_path):
    store = LocalStorageArtifactStore(base_dir=tmp_path / "artifacts")
    model = DummyModel()
    buf = io.BytesIO()
    joblib.dump(model, buf)
    model_bytes = buf.getvalue()

    stored_name, path_str, size = store.save_artifact(
        model_id="test_model_1",
        version_label="v1",
        original_filename="classifier.joblib",
        contents=model_bytes,
    )

    assert stored_name == "classifier.joblib"
    assert store.artifact_exists(path_str)
    assert size == len(model_bytes)

    loaded_bytes = store.load_bytes(path_str)
    assert loaded_bytes == model_bytes

    loaded_model = store.load_model(path_str)
    assert hasattr(loaded_model, "predict")

    deleted = store.delete_artifact(path_str)
    assert deleted is True
    assert not store.artifact_exists(path_str)


# --- 2. Repository Abstraction Tests (SQLite) --------------------------------

def test_sqlite_model_repository(db_session):
    repo = SQLiteModelRepository(db_session)
    model_name = "test_fraud_model"
    # Cleanup if exists
    existing = repo.get_model_by_name(model_name)
    if existing:
        repo.delete_model(existing.id)

    model = repo.create_model(model_name)
    assert model.id is not None
    assert model.name == model_name

    version = repo.create_version(
        model_id=model.id,
        version="v1",
        framework="sklearn",
        model_type="LogisticRegression",
        supports_proba=True,
        original_filename="model.joblib",
        stored_filename="model.joblib",
        file_path="/tmp/model.joblib",
        file_size_bytes=1024,
        is_active=True,
    )
    assert version.version == "v1"

    models = repo.list_models()
    assert any(m.id == model.id for m in models)

    fetched = repo.get_model(model.id)
    assert fetched is not None
    assert len(fetched.versions) == 1
    assert fetched.active_version.version == "v1"

    v_fetched = repo.get_version(model.id, "v1")
    assert v_fetched is not None
    assert v_fetched.id == version.id

    # Clean up
    repo.delete_model(model.id)
    assert repo.get_model(model.id) is None


def test_sqlite_deployment_repository(db_session):
    m_repo = SQLiteModelRepository(db_session)
    d_repo = SQLiteDeploymentRepository(db_session)

    m = m_repo.create_model("deploy_test_model")
    v = m_repo.create_version(
        model_id=m.id,
        version="v1",
        framework="sklearn",
        model_type="LogisticRegression",
        supports_proba=False,
        original_filename="m.joblib",
        stored_filename="m.joblib",
        file_path="/tmp/m.joblib",
        file_size_bytes=512,
    )

    d = d_repo.create_deployment(
        model_id=m.id,
        model_version_id=v.id,
        version_label="v1",
        replicas=2,
        endpoint="/api/v1/models/deploy_test_model/predict",
        status="running",
    )
    assert d.id is not None
    assert d.replicas == 2

    d_repo.update_deployment(d.id, replicas=3, scaling_status="scaling_up")
    updated = d_repo.get_deployment(d.id)
    assert updated.replicas == 3
    assert updated.scaling_status == "scaling_up"

    cfg = d_repo.save_autoscaling_config(
        d.id,
        enabled=True,
        min_replicas=1,
        max_replicas=4,
        target_latency_ms=150.0,
    )
    assert cfg.enabled is True
    assert cfg.target_latency_ms == 150.0

    fetched_cfg = d_repo.get_autoscaling_config(d.id)
    assert fetched_cfg is not None
    assert fetched_cfg.max_replicas == 4

    # Cleanup
    d_repo.delete_deployment(d.id)
    m_repo.delete_model(m.id)


def test_sqlite_user_and_audit_repository(db_session):
    u_repo = SQLiteUserRepository(db_session)
    a_repo = SQLiteAuditRepository(db_session)

    test_email = "tester_repo@modelforge.local"
    existing = u_repo.get_user_by_email(test_email)
    if existing:
        u_repo.delete_user(existing.id)

    user = u_repo.create_user(
        email=test_email,
        display_name="Tester Repo",
        role="OPERATOR",
    )
    assert user.id is not None
    assert user.role == "OPERATOR"

    u_repo.update_user(user.id, role="ADMIN")
    refreshed = u_repo.get_user_by_id(user.id)
    assert refreshed.role == "ADMIN"

    event = a_repo.log_event(
        action="MODEL_TEST_ACTION",
        resource_type="model",
        resource_id="mod_123",
        user_id=user.id,
        user_email=user.email,
        details={"key": "value", "password": "should_be_redacted"},
        success=True,
    )
    assert event is not None
    assert "[REDACTED]" in event.details

    events, total = a_repo.query_events(user_id=user.id, limit=10)
    assert total >= 1
    assert any(e.action == "MODEL_TEST_ACTION" for e in events)

    csv_data = a_repo.export_csv(user_id=user.id)
    assert "Event ID" in csv_data
    assert "MODEL_TEST_ACTION" in csv_data

    # Cleanup
    u_repo.delete_user(user.id)


# --- 3. Repository Factory & Defaults ----------------------------------------

def test_repository_factory_defaults(monkeypatch, db_session):
    monkeypatch.setattr(settings, "database_backend", "sqlite")
    assert is_firestore_enabled() is False
    m_repo = get_model_repository(db_session)
    d_repo = get_deployment_repository(db_session)
    u_repo = get_user_repository(db_session)
    a_repo = get_audit_repository(db_session)

    assert isinstance(m_repo, SQLiteModelRepository)
    assert isinstance(d_repo, SQLiteDeploymentRepository)
    assert isinstance(u_repo, SQLiteUserRepository)
    assert isinstance(a_repo, SQLiteAuditRepository)


# --- 4. Firebase Diagnostics & Error Handling --------------------------------

def test_firebase_diagnostics_endpoint():
    from app.main import app
    with TestClient(app) as test_client:
        res = test_client.get("/api/health/firebase")
        assert res.status_code == 200
        data = res.json()
        assert "initialized" in data
        assert "project_id" in data
        assert "credentials_configured" in data


def test_verify_firebase_token_without_sdk():
    """Verify verify_firebase_id_token raises HTTP 503 when Firebase is not initialized."""
    with pytest.raises(Exception) as exc_info:
        verify_firebase_id_token("invalid-fake-token")
    assert exc_info.value.status_code in (503, 401)


def test_migration_dry_run(tmp_path):
    # Dry run should succeed with code 0 without contacting Firebase
    from sqlalchemy import create_engine
    from app.database import Base
    import app.models  # noqa: F401

    db_path = tmp_path / "migration_test.db"
    db_url = f"sqlite:///{db_path}"
    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    test_engine.dispose()

    exit_code = migrate(sqlite_url=db_url, dry_run=True)
    assert exit_code == 0


if __name__ == "__main__":
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    print("Running setup_test_tables...")
    Base.metadata.create_all(bind=engine)
    print("Testing local artifact store...")
    with tempfile.TemporaryDirectory() as tmp:
        test_local_artifact_store(Path(tmp))

    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "manual_test.db"
        t_engine = create_engine(f"sqlite:///{p}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=t_engine)
        Session = sessionmaker(bind=t_engine, autocommit=False, autoflush=False)
        sess = Session()
        try:
            print("Testing SQLite model repository...")
            test_sqlite_model_repository(sess)
            print("Testing SQLite deployment repository...")
            test_sqlite_deployment_repository(sess)
            print("Testing SQLite user and audit repository...")
            test_sqlite_user_and_audit_repository(sess)
            print("Testing repository factory defaults...")
            settings.database_backend = "sqlite"
            mp = pytest.MonkeyPatch()
            test_repository_factory_defaults(mp, sess)
        finally:
            sess.close()
            t_engine.dispose()

    print("Testing Firebase diagnostics endpoint...")
    test_firebase_diagnostics_endpoint()
    print("Testing verify_firebase_token_without_sdk...")
    test_verify_firebase_token_without_sdk()
    print("Testing migration dry-run...")
    with tempfile.TemporaryDirectory() as tmp:
        test_migration_dry_run(Path(tmp))
    print("\n>>> ALL PHASE 8.5 UNIT & INTEGRATION TESTS PASSED SUCCESSFULLY! <<<")
