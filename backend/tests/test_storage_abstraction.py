"""
Unit and integration tests for ModelForge Phase 12:
Storage Abstraction Layer, Local Storage, MinIO/S3 Storage, and Factory Switching.
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import joblib
import pytest
from sklearn.linear_model import LogisticRegression

from app.services.storage.factory import get_artifact_store, reset_artifact_store
from app.services.storage.interface import ModelArtifactStore
from app.services.storage.local_storage import LocalStorageArtifactStore
from app.services.storage.minio_storage import MinioStorageArtifactStore


@pytest.fixture
def sample_model_bytes() -> bytes:
    clf = LogisticRegression().fit([[0.0, 1.0], [1.0, 0.0]], [0, 1])
    buf = io.BytesIO()
    joblib.dump(clf, buf)
    buf.seek(0)
    return buf.read()


def test_local_storage_lifecycle(tmp_path: Path, sample_model_bytes: bytes):
    """Verify upload, metadata, exists, download, list, load, and delete on LocalStorage."""
    store = LocalStorageArtifactStore(base_dir=tmp_path)

    # 1. Upload
    filename, uri, size = store.upload_model(
        model_id="test-model-1",
        version_label="v1",
        filename="model.joblib",
        contents=sample_model_bytes,
        user_id="test-user",
    )
    assert filename == "model.joblib"
    assert Path(uri).exists()
    assert size == len(sample_model_bytes)

    # 2. Exists
    assert store.model_exists(uri) is True
    assert store.artifact_exists(uri) is True
    assert store.model_exists(str(tmp_path / "nonexistent.joblib")) is False

    # 3. Metadata
    meta = store.get_model_metadata(uri)
    assert meta["size"] == len(sample_model_bytes)
    assert meta["backend"] == "local"
    assert "last_modified" in meta

    # 4. Download
    downloaded = store.download_model(uri)
    assert downloaded == sample_model_bytes
    assert store.load_bytes(uri) == sample_model_bytes

    # 5. Load model and predict
    loaded = store.load_model(uri)
    assert hasattr(loaded, "predict")
    preds = loaded.predict([[0.0, 1.0]])
    assert preds[0] == 0

    # 6. List models
    models_list = store.list_models()
    assert len(models_list) >= 1
    assert any("model.joblib" in m["uri"] for m in models_list)

    # 7. Delete
    deleted = store.delete_model(uri)
    assert deleted is True
    assert store.model_exists(uri) is False

    # 8. Missing artifact handling
    with pytest.raises(FileNotFoundError):
        store.download_model(uri)

    with pytest.raises(FileNotFoundError):
        store.get_model_metadata(uri)


def test_storage_factory_switching(monkeypatch, tmp_path: Path):
    """Verify backend switching via configuration and runtime override."""
    from app.services.storage.factory import get_artifact_store, reset_artifact_store
    from app.services.storage.local_storage import LocalStorageArtifactStore
    from app.services.storage.minio_storage import MinioStorageArtifactStore

    reset_artifact_store()
    monkeypatch.setenv("MODEL_STORAGE_BACKEND", "local")
    monkeypatch.setenv("MODEL_STORAGE_DIR", str(tmp_path))

    # Test local backend
    store_local = get_artifact_store()
    assert isinstance(store_local, LocalStorageArtifactStore)

    # Test override
    store_override = get_artifact_store(backend_override="local")
    assert isinstance(store_override, LocalStorageArtifactStore)

    reset_artifact_store()
    monkeypatch.setenv("MODEL_STORAGE_BACKEND", "minio")
    with patch("app.services.storage.minio_storage.Minio"):
        store_minio = get_artifact_store(backend_override="minio")
        assert isinstance(store_minio, MinioStorageArtifactStore)

    reset_artifact_store()


def test_minio_storage_unit(tmp_path: Path, sample_model_bytes: bytes):
    """Test MinIO storage adapter logic with mocked Minio client."""
    from app.services.storage.minio_storage import MinioStorageArtifactStore

    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True

    # Setup stat_object mock
    mock_stat = MagicMock()
    mock_stat.size = len(sample_model_bytes)
    mock_stat.etag = "abc123etag"
    mock_stat.last_modified = None
    mock_stat.content_type = "application/octet-stream"
    mock_stat.metadata = {"model_id": "m1"}
    mock_client.stat_object.return_value = mock_stat

    # Setup get_object mock
    mock_resp = MagicMock()
    mock_resp.read.return_value = sample_model_bytes
    mock_client.get_object.return_value = mock_resp

    with patch("app.services.storage.minio_storage.Minio", return_value=mock_client):
        store = MinioStorageArtifactStore(
            endpoint="http://localhost:9000",
            access_key="admin",
            secret_key="secret",
            bucket_name="test-bucket",
            local_cache_dir=tmp_path,
        )

        # 1. Upload
        stored_name, uri, size = store.upload_model(
            model_id="m1",
            version_label="v1",
            filename="clf.joblib",
            contents=sample_model_bytes,
            user_id="user1",
        )
        assert stored_name == "clf.joblib"
        assert uri == "s3://test-bucket/models/m1/v1/clf.joblib"
        assert size == len(sample_model_bytes)
        mock_client.put_object.assert_called_once()

        # 2. Exists
        assert store.model_exists(uri) is True

        # 3. Metadata
        meta = store.get_model_metadata(uri)
        assert meta["size"] == len(sample_model_bytes)
        assert meta["etag"] == "abc123etag"
        assert meta["backend"] == "minio"

        # 4. Download & load model
        downloaded = store.download_model(uri)
        assert downloaded == sample_model_bytes
        loaded = store.load_model(uri)
        assert hasattr(loaded, "predict")

        # 5. Delete
        store.delete_model(uri)
        mock_client.remove_object.assert_called_with("test-bucket", "models/m1/v1/clf.joblib")
