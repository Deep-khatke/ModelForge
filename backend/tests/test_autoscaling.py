"""
Unit and integration tests for Phase 7: Intelligent Auto-Scaling & Reliability Automation.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone


def _get_db():
    return sys.modules["app.database"].SessionLocal()


def _get_models():
    return sys.modules["app.models"]


def _create_running_deployment(client, fake_joblib_bytes, model_name="as_test_model", replicas=1):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": model_name, "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    deploy_res = client.post(
        "/api/v1/deployments",
        json={"model_id": model_id, "replicas": replicas},
    )
    assert deploy_res.status_code == 201
    return deploy_res.json()


def test_autoscaling_config_defaults_and_validation(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="cfg_model")
    dep_id = dep["id"]

    # 1. Fetch default config
    res = client.get(f"/api/v1/deployments/{dep_id}/autoscaling")
    assert res.status_code == 200
    cfg = res.json()
    assert cfg["deployment_id"] == dep_id
    assert cfg["enabled"] is False
    assert cfg["min_replicas"] == 1
    assert cfg["max_replicas"] >= 1
    assert cfg["target_latency_ms"] > 0
    assert cfg["cooldown_seconds"] > 0

    # 2. Validation error: min_replicas > max_replicas
    bad_res = client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={"min_replicas": 4, "max_replicas": 2},
    )
    assert bad_res.status_code in (400, 422)

    # 3. Validation error: min_replicas < 1
    bad_res2 = client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={"min_replicas": 0},
    )
    assert bad_res2.status_code in (400, 422)

    # 4. Valid update
    update_res = client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 4,
            "target_latency_ms": 150.0,
            "target_throughput_rps": 25.0,
            "scale_up_error_rate_percent": 10.0,
            "scale_down_idle_seconds": 120,
            "cooldown_seconds": 30,
        },
    )
    assert update_res.status_code == 200
    updated = update_res.json()
    assert updated["enabled"] is True
    assert updated["min_replicas"] == 1
    assert updated["max_replicas"] == 4
    assert updated["target_latency_ms"] == 150.0
    assert updated["cooldown_seconds"] == 30

    # Check deployment out reflects autoscaling_enabled
    dep_res = client.get(f"/api/v1/deployments/{dep_id}")
    assert dep_res.status_code == 200
    assert dep_res.json()["autoscaling_enabled"] is True


def test_autoscaling_disabled_evaluation(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="dis_model")
    dep_id = dep["id"]

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    result = eval_res.json()
    assert result["action"] == "NO_ACTION"
    assert "disabled" in result["trigger_reason"].lower()


def test_scale_up_on_high_p95_latency(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="lat_model", replicas=1)
    dep_id = dep["id"]
    models = _get_models()

    # Enable autoscaling with low latency target and 0 cooldown for test
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 3,
            "target_latency_ms": 80.0,
            "cooldown_seconds": 0,
        },
    )

    # Seed telemetry with high latency > 80ms
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        for i in range(10):
            log = models.InferenceLog(
                deployment_id=dep_id,
                model_id=dep["model_id"],
                model_version=dep["version_label"],
                replica_id=f"rep-{i}",
                status="success",
                latency_ms=160.0 + i,
                timestamp=now - timedelta(seconds=i),
            )
            db.add(log)
        db.commit()

    # Trigger evaluation
    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "SCALE_UP"
    assert data["target_replicas"] == 2
    assert "latency" in data["trigger_reason"].lower()

    # Verify deployment replicas updated
    dep_res = client.get(f"/api/v1/deployments/{dep_id}")
    assert dep_res.json()["replicas"] == 2
    assert dep_res.json()["active_replicas"] == 2

    # Verify scaling event was recorded
    events_res = client.get(f"/api/v1/deployments/{dep_id}/scaling-events")
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) >= 1
    latest = events[0]
    assert latest["action"] == "SCALE_UP"
    assert latest["previous_replicas"] == 1
    assert latest["target_replicas"] == 2
    assert latest["success"] is True
    assert "latency" in latest["trigger_reason"].lower()


def test_scale_up_on_high_throughput(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="tps_model", replicas=1)
    dep_id = dep["id"]
    models = _get_models()

    # Target throughput: 2.0 RPS per replica
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 4,
            "target_latency_ms": 1000.0,  # high so latency doesn't trigger
            "target_throughput_rps": 2.0,
            "cooldown_seconds": 0,
        },
    )

    # Seed 60 requests in the last 10 seconds -> 6.0 RPS > 2.0 RPS
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        for i in range(60):
            log = models.InferenceLog(
                deployment_id=dep_id,
                model_id=dep["model_id"],
                model_version=dep["version_label"],
                replica_id="rep-0",
                status="success",
                latency_ms=10.0,
                timestamp=now - timedelta(seconds=i * 0.15),
            )
            db.add(log)
        db.commit()

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "SCALE_UP"
    assert data["target_replicas"] >= 2
    assert "throughput" in data["trigger_reason"].lower()


def test_scale_up_on_error_rate(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="err_model", replicas=1)
    dep_id = dep["id"]
    models = _get_models()

    # Trigger scale up if error rate > 15%
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 3,
            "target_latency_ms": 1000.0,
            "target_throughput_rps": 500.0,
            "scale_up_error_rate_percent": 15.0,
            "cooldown_seconds": 0,
        },
    )

    # Seed 10 requests: 5 success, 5 error -> 50% error rate
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        for i in range(10):
            status = "error" if i % 2 == 0 else "success"
            log = models.InferenceLog(
                deployment_id=dep_id,
                model_id=dep["model_id"],
                model_version=dep["version_label"],
                replica_id="rep-0",
                status=status,
                latency_ms=20.0,
                error_message="Simulated error" if status == "error" else None,
                timestamp=now - timedelta(seconds=i),
            )
            db.add(log)
        db.commit()

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "SCALE_UP"
    assert "error" in data["trigger_reason"].lower()


def test_scale_down_on_idle(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="idle_model", replicas=3)
    dep_id = dep["id"]
    models = _get_models()

    # Scale down if idle > 30 seconds
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 4,
            "scale_down_idle_seconds": 30,
            "cooldown_seconds": 0,
        },
    )

    # Seed a single log from 60 seconds ago -> idle duration is 60s > 30s threshold
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        log = models.InferenceLog(
            deployment_id=dep_id,
            model_id=dep["model_id"],
            model_version=dep["version_label"],
            replica_id="rep-0",
            status="success",
            latency_ms=15.0,
            timestamp=now - timedelta(seconds=60),
        )
        db.add(log)
        db.commit()

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "SCALE_DOWN"
    assert data["target_replicas"] == 2  # Gradual scale down by 1 step
    assert "idle" in data["trigger_reason"].lower()

    # Verify replica count decreased to 2
    dep_res = client.get(f"/api/v1/deployments/{dep_id}")
    assert dep_res.json()["replicas"] == 2


def test_cooldown_period_enforcement(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="cd_model", replicas=1)
    dep_id = dep["id"]
    models = _get_models()

    # Cooldown = 60 seconds
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 4,
            "target_latency_ms": 50.0,
            "cooldown_seconds": 60,
        },
    )

    # Seed high latency logs
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        for i in range(10):
            log = models.InferenceLog(
                deployment_id=dep_id,
                model_id=dep["model_id"],
                model_version=dep["version_label"],
                replica_id="rep-0",
                status="success",
                latency_ms=120.0,
                timestamp=now - timedelta(seconds=i),
            )
            db.add(log)
        db.commit()

    # First evaluation -> scales up 1 -> 2
    res1 = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert res1.status_code == 200
    assert res1.json()["action"] == "SCALE_UP"

    # Immediate second evaluation -> cooldown should block scaling
    res2 = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["action"] == "NO_ACTION"
    assert data2["cooldown_active"] is True
    assert "cooldown" in data2["trigger_reason"].lower()


def test_max_replicas_limit_enforcement(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="max_model", replicas=2)
    dep_id = dep["id"]
    models = _get_models()

    # Max replicas set to 2 (already at max)
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 2,
            "target_latency_ms": 50.0,
            "cooldown_seconds": 0,
        },
    )

    # Seed high latency logs
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        for i in range(10):
            log = models.InferenceLog(
                deployment_id=dep_id,
                model_id=dep["model_id"],
                model_version=dep["version_label"],
                replica_id="rep-0",
                status="success",
                latency_ms=150.0,
                timestamp=now - timedelta(seconds=i),
            )
            db.add(log)
        db.commit()

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "NO_ACTION"
    assert "maximum" in data["trigger_reason"].lower()

    # Replicas remain 2
    dep_res = client.get(f"/api/v1/deployments/{dep_id}")
    assert dep_res.json()["replicas"] == 2


def test_insufficient_telemetry_no_action(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="telemetry_model", replicas=2)
    dep_id = dep["id"]
    models = _get_models()

    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={
            "enabled": True,
            "min_replicas": 1,
            "max_replicas": 4,
            "scale_down_idle_seconds": 300,  # 5 minutes
            "cooldown_seconds": 0,
        },
    )

    # Only 1 request 10 seconds ago (traffic < min_eval_samples and idle < 300s)
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        log = models.InferenceLog(
            deployment_id=dep_id,
            model_id=dep["model_id"],
            model_version=dep["version_label"],
            replica_id="rep-0",
            status="success",
            latency_ms=10.0,
            timestamp=now - timedelta(seconds=10),
        )
        db.add(log)
        db.commit()

    eval_res = client.post(f"/api/v1/deployments/{dep_id}/autoscaling/evaluate")
    assert eval_res.status_code == 200
    data = eval_res.json()
    assert data["action"] == "NO_ACTION"
    assert "insufficient" in data["trigger_reason"].lower()


def test_manual_scale_interoperability(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="manual_model", replicas=1)
    dep_id = dep["id"]

    # Configure autoscaling
    client.put(
        f"/api/v1/deployments/{dep_id}/autoscaling",
        json={"enabled": True, "min_replicas": 1, "max_replicas": 4},
    )

    # Manual scaling call to 3 replicas
    manual_res = client.post(f"/api/v1/deployments/{dep_id}/scale", json={"replicas": 3})
    assert manual_res.status_code == 200
    assert manual_res.json()["active_replicas"] == 3

    # Verify deployment is now at 3 replicas
    dep_res = client.get(f"/api/v1/deployments/{dep_id}")
    assert dep_res.json()["replicas"] == 3


def test_system_evaluate_all_endpoint(client, fake_joblib_bytes):
    dep1 = _create_running_deployment(client, fake_joblib_bytes, model_name="all_model_1", replicas=1)
    dep2 = _create_running_deployment(client, fake_joblib_bytes, model_name="all_model_2", replicas=2)

    # Enable autoscaling on both
    client.put(f"/api/v1/deployments/{dep1['id']}/autoscaling", json={"enabled": True})
    client.put(f"/api/v1/deployments/{dep2['id']}/autoscaling", json={"enabled": True})

    eval_all = client.post("/api/v1/autoscaling/evaluate")
    assert eval_all.status_code == 200
    results = eval_all.json()
    assert isinstance(results, list)
    assert len(results) >= 2


def test_monitoring_alerts_include_scaling_events(client, fake_joblib_bytes):
    dep = _create_running_deployment(client, fake_joblib_bytes, model_name="alert_model", replicas=1)
    dep_id = dep["id"]
    models = _get_models()

    # Record a scaling event manually into DB
    now = datetime.now(timezone.utc)
    with _get_db() as db:
        event = models.ScalingEvent(
            deployment_id=dep_id,
            previous_replicas=1,
            target_replicas=2,
            action="SCALE_UP",
            trigger_reason="high_p95_latency: P95 latency exceeded target",
            observed_p95_latency_ms=150.0,
            success=True,
            timestamp=now,
        )
        db.add(event)
        db.commit()

    # Check alerts endpoint
    alerts_res = client.get("/api/v1/monitoring/alerts")
    assert alerts_res.status_code == 200
    alerts = alerts_res.json()
    scaling_alert = next((a for a in alerts if a.get("alert_type") == "autoscaled_up"), None)
    assert scaling_alert is not None
    assert scaling_alert["deployment_id"] == dep_id
