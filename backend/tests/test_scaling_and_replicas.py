"""
Unit and integration tests for Phase 4: Scaling, Replica Management, and Round-Robin Load Balancing.
"""
from __future__ import annotations


def test_create_deployment_with_replicas(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "scaled_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    deploy_res = client.post(
        "/api/v1/deployments",
        json={"model_id": model_id, "replicas": 3},
    )
    assert deploy_res.status_code == 201
    data = deploy_res.json()
    assert data["status"] == "running"
    assert data["replicas"] == 3
    assert data["active_replicas"] == 3
    assert data["scaling_status"] == "stable"


def test_scale_up_and_down(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "dyn_scale_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    deploy_res = client.post(
        "/api/v1/deployments",
        json={"model_id": model_id, "replicas": 1},
    )
    dep_id = deploy_res.json()["id"]
    assert deploy_res.json()["active_replicas"] == 1

    # Scale 1 -> 3
    scale3 = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 3})
    assert scale3.status_code == 200
    s3_data = scale3.json()
    assert s3_data["previous_replicas"] == 1
    assert s3_data["requested_replicas"] == 3
    assert s3_data["active_replicas"] == 3
    assert s3_data["scaling_status"] == "stable"

    # Scale 3 -> 2
    scale2 = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 2})
    assert scale2.status_code == 200
    assert scale2.json()["active_replicas"] == 2

    # Scale 2 -> 1
    scale1 = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 1})
    assert scale1.status_code == 200
    assert scale1.json()["active_replicas"] == 1


def test_invalid_replica_count_rejected(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "bounds_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    # Reject 0 replicas on create
    r0 = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 0})
    assert r0.status_code == 400

    # Reject 6 replicas on create
    r6 = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 6})
    assert r6.status_code == 400

    # Create valid deployment
    d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 1})
    dep_id = d_res.json()["id"]

    # Reject scaling to 0
    s0 = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 0})
    assert s0.status_code == 400

    # Reject scaling to 10
    s10 = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 10})
    assert s10.status_code == 400


def test_round_robin_load_balancing(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "rr_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 3})

    replica_sequence = []
    for _ in range(6):
        res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})
        assert res.status_code == 200
        replica_sequence.append(res.json()["replica_id"])

    # Expected Round-Robin distribution: replica_1 -> replica_2 -> replica_3 -> replica_1 -> replica_2 -> replica_3
    assert replica_sequence == [
        "replica_1",
        "replica_2",
        "replica_3",
        "replica_1",
        "replica_2",
        "replica_3",
    ]


def test_get_deployment_replicas_list(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "replica_list_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
    dep_id = d_res.json()["id"]

    # Make 1 prediction so metrics populate
    client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    rep_res = client.get(f"/api/v1/deployments/{dep_id}/replicas")
    assert rep_res.status_code == 200
    reps = rep_res.json()
    assert len(reps) == 2
    assert reps[0]["replica_id"] == "replica_1"
    assert reps[1]["replica_id"] == "replica_2"
    assert reps[0]["status"] == "healthy"
    assert reps[0]["requests_count"] == 1


def test_load_test_endpoint(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "benchmark_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 3})
    dep_id = d_res.json()["id"]

    lt_res = client.post(
        f"/api/v1/deployments/{dep_id}/load-test",
        json={"requests": 15, "features": [0.0, 0.0]},
    )
    assert lt_res.status_code == 200
    data = lt_res.json()
    assert data["total_requests"] == 15
    assert data["successful_requests"] == 15
    assert data["failed_requests"] == 0
    assert data["replicas_used"] == 3
    assert data["throughput_requests_per_second"] > 0
    assert data["replica_distribution"] == {
        "replica_1": 5,
        "replica_2": 5,
        "replica_3": 5,
    }


def test_inference_logs_endpoint(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "logged_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    d_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 1})
    dep_id = d_res.json()["id"]

    client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    log_res = client.get(f"/api/v1/deployments/{dep_id}/logs")
    assert log_res.status_code == 200
    logs = log_res.json()
    assert len(logs) >= 1
    assert logs[0]["deployment_id"] == dep_id
    assert logs[0]["status"] == "success"
    assert logs[0]["replica_id"] == "replica_1"
