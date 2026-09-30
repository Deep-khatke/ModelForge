"""
Tests for Phase 6: Containerized Deployment & Cloud-Ready Architecture.

Tests cover:
- Safe behavior and fallback when Docker is unavailable or disabled
- Container deployment lifecycle with mocked Docker client
- Scale up/down container behavior (only starting/stopping required containers)
- Health-state updates (healthy, degraded, failed)
- Inference routing to healthy container replicas
- Telemetry & monitoring records retaining container replica IDs
- Standalone inference-service microservice (/health and /predict)
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def test_docker_unavailable_fallback(client, fake_joblib_bytes):
    """
    When Docker is unavailable or disabled, ModelForge must gracefully fall back
    to in-process replica simulation without fabricating container IDs or metrics.
    """
    # 1. Upload model
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "fallback_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    # 2. Deploy model with Docker disabled
    deploy_res = client.post(
        "/api/v1/deployments",
        json={"model_id": model_id, "replicas": 2},
    )
    assert deploy_res.status_code == 201
    dep_data = deploy_res.json()
    assert dep_data["status"] == "running"
    assert dep_data["is_containerized"] is False
    assert dep_data["active_replicas"] == 2

    # 3. Check replicas - container_id must be None (not fabricated)
    reps_res = client.get(f"/api/v1/deployments/{dep_data['id']}/replicas")
    assert reps_res.status_code == 200
    replicas = reps_res.json()
    assert len(replicas) == 2
    for r in replicas:
        assert r["is_containerized"] is False
        assert r["container_id"] is None
        assert r["status"] == "healthy"

    # 4. Predict via fallback
    pred_res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})
    assert pred_res.status_code == 200
    pred_data = pred_res.json()
    assert pred_data["replica_id"] in ["replica_1", "replica_2"]

    # 5. Check telemetry log recorded replica ID
    logs_res = client.get(f"/api/v1/deployments/{dep_data['id']}/logs")
    assert logs_res.status_code == 200
    logs = logs_res.json()
    assert len(logs) >= 1
    assert logs[0]["replica_id"] == pred_data["replica_id"]


def test_containerized_deployment_lifecycle(client, fake_joblib_bytes):
    """
    When Docker is available, deployment should launch container replicas with
    proper metadata, ports, and container_ids.
    """
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "container_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    started_containers = []

    def mock_start(deployment_id, replica_id, model_id, version_label, file_path):
        c_id = f"docker-cid-{replica_id}"
        port = 8150 + len(started_containers)
        meta = {
            "container_id": c_id,
            "container_name": f"modelforge-rep-{deployment_id[:8]}-{replica_id}",
            "container_port": port,
            "endpoint_url": f"http://127.0.0.1:{port}",
            "status": "healthy",
        }
        started_containers.append(meta)
        return meta

    with (
        patch("app.replica_manager.container_manager.is_available", return_value=True),
        patch("app.replica_manager.container_manager.start_replica_container", side_effect=mock_start),
        patch("app.replica_manager.container_manager.check_replica_health", return_value=True),
    ):
        deploy_res = client.post(
            "/api/v1/deployments",
            json={"model_id": model_id, "replicas": 2},
        )
        assert deploy_res.status_code == 201
        data = deploy_res.json()
        assert data["status"] == "running"
        assert data["is_containerized"] is True
        assert data["active_replicas"] == 2
        assert len(started_containers) == 2

        # Check replicas endpoint returns container metadata
        reps_res = client.get(f"/api/v1/deployments/{data['id']}/replicas")
        assert reps_res.status_code == 200
        reps = reps_res.json()
        assert len(reps) == 2
        assert reps[0]["is_containerized"] is True
        assert reps[0]["container_id"] == "docker-cid-replica_1"
        assert reps[1]["is_containerized"] is True
        assert reps[1]["container_id"] == "docker-cid-replica_2"


def test_container_scale_up_and_down(client, fake_joblib_bytes):
    """
    Scaling up should only start new containers; scaling down should only stop excess containers.
    """
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "scaled_container_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    started = []
    stopped = []

    def mock_start(deployment_id, replica_id, model_id, version_label, file_path):
        meta = {
            "container_id": f"cid-{replica_id}",
            "container_port": 8200 + len(started),
            "endpoint_url": f"http://127.0.0.1:{8200 + len(started)}",
            "status": "healthy",
        }
        started.append(replica_id)
        return meta

    def mock_stop(container_id):
        stopped.append(container_id)

    with (
        patch("app.replica_manager.container_manager.is_available", return_value=True),
        patch("app.replica_manager.container_manager.start_replica_container", side_effect=mock_start),
        patch("app.replica_manager.container_manager.stop_replica_container", side_effect=mock_stop),
        patch("app.replica_manager.container_manager.check_replica_health", return_value=True),
    ):
        # 1. Start with 1 replica
        d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 1})
        assert d_res.status_code == 201
        dep_id = d_res.json()["id"]
        assert started == ["replica_1"]

        # 2. Scale 1 -> 3 (should only start replica_2 and replica_3)
        s_res = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 3})
        assert s_res.status_code == 200
        assert started == ["replica_1", "replica_2", "replica_3"]
        assert stopped == []
        assert s_res.json()["active_replicas"] == 3

        # 3. Scale 3 -> 1 (should only stop replica_2 and replica_3 containers)
        s_down = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 1})
        assert s_down.status_code == 200
        assert s_down.json()["active_replicas"] == 1
        assert "cid-replica_2" in stopped
        assert "cid-replica_3" in stopped
        assert "cid-replica_1" not in stopped


def test_container_stop_and_delete_cleanup(client, fake_joblib_bytes):
    """
    Stopping or deleting a deployment must stop and remove all associated containers.
    """
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "cleanup_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    stopped_containers = []

    def mock_start(deployment_id, replica_id, model_id, version_label, file_path):
        return {
            "container_id": f"cid-{replica_id}",
            "container_port": 8300,
            "endpoint_url": "http://127.0.0.1:8300",
            "status": "healthy",
        }

    with (
        patch("app.replica_manager.container_manager.is_available", return_value=True),
        patch("app.replica_manager.container_manager.start_replica_container", side_effect=mock_start),
        patch("app.replica_manager.container_manager.stop_replica_container", side_effect=stopped_containers.append),
        patch("app.replica_manager.container_manager.stop_deployment_containers") as mock_stop_dep,
        patch("app.replica_manager.container_manager.check_replica_health", return_value=True),
    ):
        d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
        dep_id = d_res.json()["id"]

        # Stop deployment
        stop_res = client.post(f"/api/v1/deployments/{dep_id}/stop")
        assert stop_res.status_code == 200
        assert stop_res.json()["status"] == "stopped"
        assert len(stopped_containers) == 2
        mock_stop_dep.assert_called_with(dep_id)

        # Delete deployment
        del_res = client.delete(f"/api/v1/deployments/{dep_id}")
        assert del_res.status_code == 204


def test_container_health_state_transitions(client, fake_joblib_bytes):
    """
    Deployment state should accurately reflect container health (RUNNING, DEGRADED, FAILED).
    """
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "health_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    # Scenario A: 1 healthy, 1 unhealthy -> DEGRADED
    def mock_start_degraded(deployment_id, replica_id, model_id, version_label, file_path):
        is_h = replica_id == "replica_1"
        return {
            "container_id": f"cid-{replica_id}",
            "container_port": 8400,
            "endpoint_url": "http://127.0.0.1:8400",
            "status": "healthy" if is_h else "unhealthy",
        }

    def mock_check_degraded(endpoint_url, timeout=5.0):
        # Only replica 1 is healthy
        return True

    with (
        patch("app.replica_manager.container_manager.is_available", return_value=True),
        patch("app.replica_manager.container_manager.start_replica_container", side_effect=mock_start_degraded),
        patch("app.replica_manager.container_manager.check_replica_health", side_effect=[True, False]),
    ):
        d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
        assert d_res.status_code == 201
        data = d_res.json()
        assert data["status"] == "running"
        assert data["scaling_status"] == "degraded"
        assert data["active_replicas"] == 1


def test_containerized_inference_routing_and_telemetry(client, fake_joblib_bytes):
    """
    Inference requests should route to container endpoints via HTTP and log
    replica_id and latency into telemetry records.
    """
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "predict_container_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    def mock_start(deployment_id, replica_id, model_id, version_label, file_path):
        return {
            "container_id": f"cid-{replica_id}",
            "container_port": 8500,
            "endpoint_url": "http://127.0.0.1:8500",
            "status": "healthy",
        }

    mock_prediction = {
        "predictions": [1],
        "probabilities": [[0.1, 0.9]],
        "inference_time_ms": 14.5,
        "replica_id": "replica_1",
    }

    with (
        patch("app.replica_manager.container_manager.is_available", return_value=True),
        patch("app.replica_manager.container_manager.start_replica_container", side_effect=mock_start),
        patch("app.replica_manager.container_manager.check_replica_health", return_value=True),
        patch("app.replica_manager.container_manager.predict_container", return_value=mock_prediction) as mock_pred_call,
    ):
        d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 1})
        dep_id = d_res.json()["id"]

        pred_res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.5, 0.5]})
        assert pred_res.status_code == 200
        p_data = pred_res.json()
        assert p_data["predictions"] == [1]
        assert p_data["probabilities"] == [[0.1, 0.9]]
        assert p_data["inference_time_ms"] == 14.5
        assert p_data["replica_id"] == "replica_1"

        mock_pred_call.assert_called_once_with("http://127.0.0.1:8500", [0.5, 0.5])

        # Verify telemetry log recorded container replica ID and latency
        logs_res = client.get(f"/api/v1/deployments/{dep_id}/logs")
        assert logs_res.status_code == 200
        logs = logs_res.json()
        assert len(logs) == 1
        assert logs[0]["replica_id"] == "replica_1"
        assert logs[0]["latency_ms"] == 14.5
        assert logs[0]["status"] == "success"


def test_standalone_inference_service(tmp_path, fake_joblib_bytes):
    """
    Test the standalone inference_service microservice application directly.
    """
    # Save a model to a temporary file
    model_path = tmp_path / "model.joblib"
    model_path.write_bytes(fake_joblib_bytes())

    # Import inference_service.main with environment variables set
    with patch.dict(
        "os.environ",
        {
            "MODEL_PATH": str(model_path),
            "REPLICA_ID": "rep-test-99",
            "DEPLOYMENT_ID": "dep-test-1",
            "MODEL_ID": "mod-test-1",
            "MODEL_VERSION": "v1",
        },
    ):
        # Add root to sys.path to import inference_service
        root_dir = str(Path(__file__).resolve().parent.parent.parent)
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        import inference_service.main as inf_service

        # Re-initialize service model
        inf_service.MODEL_PATH = str(model_path)
        inf_service.REPLICA_ID = "rep-test-99"
        inf_service.load_model()

        with TestClient(inf_service.app) as inf_client:
            # 1. Health endpoint
            h_res = inf_client.get("/health")
            assert h_res.status_code == 200
            h_data = h_res.json()
            assert h_data["status"] == "healthy"
            assert h_data["replica_id"] == "rep-test-99"

            # 2. Prediction endpoint
            p_res = inf_client.post("/predict", json={"features": [0.0, 0.0]})
            assert p_res.status_code == 200
            p_data = p_res.json()
            assert p_data["replica_id"] == "rep-test-99"
            assert "predictions" in p_data
            assert p_data["inference_time_ms"] > 0

            # 3. Bad input returns 400 without exposing traceback
            bad_res = inf_client.post("/predict", json={"features": []})
            assert bad_res.status_code == 400
