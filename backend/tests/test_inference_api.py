"""
Unit tests for the real inference API (POST /api/v1/models/{model_id}/predict).
"""
from __future__ import annotations


def test_predict_success(client, fake_joblib_bytes):
    # 1. Upload model
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "classifier", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    assert upload_res.status_code == 201
    model_id = upload_res.json()["id"]

    # 2. Deploy model
    deploy_res = client.post("/api/v1/deployments", json={"model_id": model_id})
    assert deploy_res.status_code == 201
    assert deploy_res.json()["status"] == "running"

    # 3. Call predict with 1D features
    predict_res = client.post(
        f"/api/v1/models/{model_id}/predict",
        json={"features": [0.0, 0.0]},
    )
    assert predict_res.status_code == 200
    data = predict_res.json()
    assert data["model_id"] == model_id
    assert data["model_name"] == "classifier"
    assert data["version"] == "v1"
    assert data["predictions"] == [0]
    assert data["probabilities"] is not None
    assert isinstance(data["inference_time_ms"], (int, float))
    assert data["inference_time_ms"] >= 0


def test_predict_2d_batch(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "batch_classifier", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    client.post("/api/v1/deployments", json={"model_id": model_id})

    predict_res = client.post(
        f"/api/v1/models/{model_id}/predict",
        json={"features": [[0.0, 0.0], [1.0, 1.0]]},
    )
    assert predict_res.status_code == 200
    data = predict_res.json()
    assert data["predictions"] == [0, 1]
    assert len(data["probabilities"]) == 2


def test_predict_missing_model_returns_404(client):
    res = client.post("/api/v1/models/nonexistent/predict", json={"features": [1, 2]})
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_predict_no_running_deployment_returns_400(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "undeployed_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": [0.0, 0.0]})
    assert res.status_code == 400
    assert "running deployment" in res.json()["detail"].lower()


def test_predict_empty_features_returns_400(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "empty_feat_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": []})
    assert res.status_code == 400
    assert "cannot be empty" in res.json()["detail"].lower()


def test_predict_feature_mismatch_returns_400(client, fake_joblib_bytes):
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "mismatch_model", "framework": "sklearn"},
        files={"file": ("model.joblib", fake_joblib_bytes(), "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]
    client.post("/api/v1/deployments", json={"model_id": model_id})

    res = client.post(f"/api/v1/models/{model_id}/predict", json={"features": [1, 2, 3, 4, 5]})
    assert res.status_code == 400
    assert "failed" in res.json()["detail"].lower()
