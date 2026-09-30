"""Basic tests for the model registry API (upload, list, version, delete)."""


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "healthy"}


def test_upload_and_list_model(client, fake_joblib_bytes):
    file_bytes = fake_joblib_bytes()

    res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "test_classifier", "framework": "sklearn"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "test_classifier"
    assert len(body["versions"]) == 1
    assert body["versions"][0]["version"] == "v1"
    assert body["versions"][0]["is_active"] is True
    assert body["versions"][0]["model_type"] == "LogisticRegression"

    res = client.get("/api/v1/models")
    assert res.status_code == 200
    models = res.json()
    assert len(models) == 1
    assert models[0]["name"] == "test_classifier"


def test_second_upload_creates_v2(client, fake_joblib_bytes):
    file_bytes = fake_joblib_bytes()

    client.post(
        "/api/v1/models/upload",
        data={"model_name": "iris_model"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )
    res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "iris_model"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )
    assert res.status_code == 201
    versions = [v["version"] for v in res.json()["versions"]]
    assert versions == ["v1", "v2"]


def test_reject_wrong_extension(client, fake_joblib_bytes):
    res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "bad_model"},
        files={"file": ("model.txt", b"not a model", "text/plain")},
    )
    assert res.status_code == 400


def test_reject_invalid_joblib_content(client):
    res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "corrupt_model"},
        files={"file": ("model.joblib", b"this is not a pickle", "application/octet-stream")},
    )
    assert res.status_code == 400


def test_activate_version(client, fake_joblib_bytes):
    file_bytes = fake_joblib_bytes()
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "activatable"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    client.post(
        "/api/v1/models/upload",
        data={"model_name": "activatable"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )

    res = client.post(f"/api/v1/models/{model_id}/versions/v2/activate")
    assert res.status_code == 200
    versions = {v["version"]: v["is_active"] for v in res.json()["versions"]}
    assert versions == {"v1": False, "v2": True}


def test_delete_model(client, fake_joblib_bytes):
    file_bytes = fake_joblib_bytes()
    upload_res = client.post(
        "/api/v1/models/upload",
        data={"model_name": "to_delete"},
        files={"file": ("model.joblib", file_bytes, "application/octet-stream")},
    )
    model_id = upload_res.json()["id"]

    res = client.delete(f"/api/v1/models/{model_id}")
    assert res.status_code == 204

    res = client.get(f"/api/v1/models/{model_id}")
    assert res.status_code == 404
