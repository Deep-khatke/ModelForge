"""
Unit and integration tests for Phase 5: Monitoring, Observability, Alerting, System Resources, and Performance Experiments.
"""
from __future__ import annotations


def test_monitoring_summary(client, fake_joblib_bytes):
    # Setup model & deployment
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "monitored_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    dep_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
    dep_id = dep_res.json()["id"]

    # Run predictions
    for _ in range(5):
        client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    summary_res = client.get("/api/v1/monitoring/summary?range=1h")
    assert summary_res.status_code == 200
    data = summary_res.json()
    assert data["total_requests"] == 5
    assert data["successful_requests"] == 5
    assert data["failed_requests"] == 0
    assert data["error_rate_percent"] == 0.0
    assert data["average_latency_ms"] >= 0
    assert data["p95_latency_ms"] >= data["average_latency_ms"]
    assert data["active_deployments_count"] >= 1
    assert data["active_replicas_count"] >= 2


def test_deployment_and_model_metrics(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "metrics_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    dep_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 1})
    dep_id = dep_res.json()["id"]

    client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    # Deployment metrics
    d_metrics = client.get(f"/api/v1/monitoring/deployments/{dep_id}?range=1h")
    assert d_metrics.status_code == 200
    d_data = d_metrics.json()
    assert d_data["deployment_id"] == dep_id
    assert d_data["total_requests"] == 1
    assert d_data["average_latency_ms"] >= 0

    # Model metrics
    m_metrics = client.get(f"/api/v1/monitoring/models/{model_id}?range=1h")
    assert m_metrics.status_code == 200
    m_data = m_metrics.json()
    assert m_data["model_id"] == model_id
    assert m_data["total_requests"] == 1


def test_timeseries_metrics(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "ts_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    ts_res = client.get("/api/v1/monitoring/timeseries?range=1h")
    assert ts_res.status_code == 200
    points = ts_res.json()
    assert isinstance(points, list)
    assert len(points) > 0
    assert "average_latency_ms" in points[0]
    assert "p95_latency_ms" in points[0]


def test_replica_metrics_and_paged_recent_requests(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "replica_metrics_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    dep_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
    dep_id = dep_res.json()["id"]
    for _ in range(4):
        assert client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]}).status_code == 200

    replicas = client.get(f"/api/v1/monitoring/deployments/{dep_id}/replicas?range=1h")
    assert replicas.status_code == 200
    replica_data = replicas.json()
    assert len(replica_data) == 2
    assert sum(item["request_count"] for item in replica_data) == 4
    assert {item["status"] for item in replica_data} == {"HEALTHY"}

    recent = client.get(f"/api/v1/monitoring/requests/recent?deployment_id={dep_id}&limit=2")
    assert recent.status_code == 200
    recent_data = recent.json()
    assert len(recent_data["items"]) == 2
    assert recent_data["has_more"] is True
    assert all(item["replica_id"] for item in recent_data["items"])


def test_system_metrics(client):
    sys_res = client.get("/api/v1/monitoring/system")
    assert sys_res.status_code == 200
    data = sys_res.json()
    assert "cpu_percent" in data
    assert "memory_percent" in data


def test_alerts_evaluation(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "alerts_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    alerts_res = client.get("/api/v1/monitoring/alerts?range=1h")
    assert alerts_res.status_code == 200
    assert isinstance(alerts_res.json(), list)


def test_monitoring_csv_export(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "csv_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})

    csv_res = client.get("/api/v1/monitoring/export?range=1h")
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    content = csv_res.text
    assert "deployment_id" in content
    assert "replica_id" in content
    assert "latency_ms" in content


def test_controlled_experiment_run_and_export(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "exp_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    dep_res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 2})
    dep_id = dep_res.json()["id"]

    # Run controlled experiment with 10 requests
    exp_res = client.post(
        "/api/v1/experiments/run",
        json={"deployment_id": dep_id, "requests": 10},
    )
    assert exp_res.status_code == 201
    exp_data = exp_res.json()
    assert exp_data["deployment_id"] == dep_id
    assert exp_data["replica_count"] == 2
    assert exp_data["total_requests"] == 10
    assert exp_data["successful_requests"] == 10
    assert exp_data["p95_latency_ms"] >= 0
    assert exp_data["throughput_rps"] > 0

    # List experiments
    list_res = client.get("/api/v1/experiments")
    assert list_res.status_code == 200
    experiments = list_res.json()
    assert len(experiments) >= 1

    # Export experiments CSV
    csv_res = client.get("/api/v1/experiments/export")
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    csv_text = csv_res.text
    assert "experiment_id" in csv_text
    assert "p95_latency_ms" in csv_text
    assert "throughput_rps" in csv_text
