"""
Shared pytest fixtures for the ModelForge API test suite.

Run with:  pytest -q   (from the backend/ directory, after installing
requirements.txt into your environment)
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    A TestClient wired to a throwaway SQLite DB and storage directory, so
    the test suite never touches real project data (modelforge.db,
    storage/models/).

    Every module that captures state from app.config/app.database (engine,
    Base, ORM classes, routers, the FastAPI app itself) is reloaded, in
    dependency order, so each test gets a fully isolated app instance.
    """
    db_path = tmp_path / "test.db"
    storage_dir = tmp_path / "storage"

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MODEL_STORAGE_DIR", str(storage_dir))
    monkeypatch.setenv("AUTOSCALING_BACKGROUND_ENABLED", "false")
    monkeypatch.setenv("AUTH_ENABLED", "false")

    import sys

    for mod_name in list(sys.modules.keys()):
        if mod_name == "app" or mod_name.startswith("app."):
            sys.modules.pop(mod_name, None)

    import app.config as config_module
    import app.database as database_module
    import app.models as orm_models_module
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
        yield test_client


@pytest.fixture()
def fake_joblib_bytes():
    """Train a tiny, valid scikit-learn model and serialize it in-memory."""
    import io

    import joblib
    from sklearn.linear_model import LogisticRegression

    def _make() -> bytes:
        model = LogisticRegression()
        model.fit([[0, 0], [1, 1]], [0, 1])
        buffer = io.BytesIO()
        joblib.dump(model, buffer)
        return buffer.getvalue()

    return _make
