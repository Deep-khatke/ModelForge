"""Tests for the deployment manager API (deploy, list, stop, health)."""


def _upload(client, file_bytes, model_name="deploy_target"):
    return client.post(
        "/api/v1/models/upload",
        data={"model_name": model_name},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )


def test_deploy_active_version(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes())
    model_id = upload_res.json()["id"]

    res = client.post("/api/v1/deployments", json={"model_id": model_id})
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "running"
    assert body["version_label"] == "v1"
    assert body["endpoint"] == f"/api/v1/models/{model_id}/predict"
    assert body["replicas"] == 1
    assert body["error_message"] is None


def test_deploy_specific_version(client, fake_joblib_bytes):
    file_bytes = fake_joblib_bytes()
    upload_res = _upload(client, file_bytes, "multi_version")
    model_id = upload_res.json()["id"]
    _upload(client, file_bytes, "multi_version")  # creates v2

    res = client.post(
        "/api/v1/deployments", json={"model_id": model_id, "version": "v1", "replicas": 2}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["version_label"] == "v1"
    assert body["replicas"] == 2


def test_redeploy_stops_previous_deployment(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "redeployed")
    model_id = upload_res.json()["id"]

    first = client.post("/api/v1/deployments", json={"model_id": model_id}).json()
    second = client.post("/api/v1/deployments", json={"model_id": model_id}).json()

    assert second["status"] == "running"

    first_after = client.get(f"/api/v1/deployments/{first['id']}").json()
    assert first_after["status"] == "stopped"


def test_deploy_missing_model_returns_404(client):
    res = client.post("/api/v1/deployments", json={"model_id": "does-not-exist"})
    assert res.status_code == 404


def test_deploy_unknown_version_returns_404(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "version_check")
    model_id = upload_res.json()["id"]

    res = client.post("/api/v1/deployments", json={"model_id": model_id, "version": "v99"})
    assert res.status_code == 404


def test_deploy_rejects_zero_replicas(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "replica_check")
    model_id = upload_res.json()["id"]

    res = client.post("/api/v1/deployments", json={"model_id": model_id, "replicas": 0})
    assert res.status_code == 400


def test_list_deployments(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "listed_model")
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    res = client.get("/api/v1/deployments")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["model_name"] == "listed_model"


def test_deployment_health_reflects_status(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "health_check_model")
    model_id = upload_res.json()["id"]
    deployment_id = client.post("/api/v1/deployments", json={"model_id": model_id}).json()["id"]

    res = client.get(f"/api/v1/deployments/{deployment_id}/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}

    client.post(f"/api/v1/deployments/{deployment_id}/stop")
    res = client.get(f"/api/v1/deployments/{deployment_id}/health")
    assert res.json() == {"status": "stopped"}


def test_stop_deployment(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "stoppable")
    model_id = upload_res.json()["id"]
    deployment_id = client.post("/api/v1/deployments", json={"model_id": model_id}).json()["id"]

    res = client.post(f"/api/v1/deployments/{deployment_id}/stop")
    assert res.status_code == 200
    assert res.json()["status"] == "stopped"

    # Stopping an already-stopped deployment is rejected, not silently ok.
    res = client.post(f"/api/v1/deployments/{deployment_id}/stop")
    assert res.status_code == 400


def test_delete_deployment(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "delete_me")
    model_id = upload_res.json()["id"]
    deployment_id = client.post("/api/v1/deployments", json={"model_id": model_id}).json()["id"]

    res = client.delete(f"/api/v1/deployments/{deployment_id}")
    assert res.status_code == 204

    res = client.get(f"/api/v1/deployments/{deployment_id}")
    assert res.status_code == 404


def test_model_deletion_cascades_to_deployments(client, fake_joblib_bytes):
    upload_res = _upload(client, fake_joblib_bytes(), "cascade_delete")
    model_id = upload_res.json()["id"]
    deployment_id = client.post("/api/v1/deployments", json={"model_id": model_id}).json()["id"]

    client.delete(f"/api/v1/models/{model_id}")

    res = client.get(f"/api/v1/deployments/{deployment_id}")
    assert res.status_code == 404
