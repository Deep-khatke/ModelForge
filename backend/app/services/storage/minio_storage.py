"""
S3-Compatible Object Storage implementation of ModelArtifactStore using MinIO.
Stores artifacts in MinIO bucket 'modelforge-models' under object keys:
  models/<model_id>/<version_label>/<stored_filename>
and maintains a local synchronized runtime cache.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import joblib
import urllib3
from minio import Minio
from minio.error import S3Error

from app.config import settings
from app.services.storage.interface import ModelArtifactStore
from app.utils import safe_filename

logger = logging.getLogger(__name__)


class MinioStorageArtifactStore(ModelArtifactStore):
    """
    S3 / MinIO Object Storage implementation for ModelForge model artifacts.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket_name: str | None = None,
        secure: bool | None = None,
        local_cache_dir: Path | str | None = None,
    ) -> None:
        raw_endpoint = endpoint or settings.minio_endpoint
        # Strip http:// or https:// if provided in endpoint
        parsed = urlparse(raw_endpoint)
        if parsed.netloc:
            self._endpoint = parsed.netloc
            is_secure = parsed.scheme == "https"
        else:
            self._endpoint = raw_endpoint
            is_secure = False

        if secure is not None:
            self._secure = secure
        else:
            self._secure = getattr(settings, "minio_secure", is_secure)

        self._access_key = access_key or settings.minio_access_key
        self._secret_key = secret_key or settings.minio_secret_key
        self._bucket_name = bucket_name or settings.minio_bucket

        if local_cache_dir is None:
            self._local_cache = settings.model_storage_path
        else:
            self._local_cache = Path(local_cache_dir).resolve()
        self._local_cache.mkdir(parents=True, exist_ok=True)

        self._client: Minio | None = None
        self._initialized = False

    def _get_client(self) -> Minio:
        if self._client is None:
            http_client = urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=3.0, read=5.0),
                retries=urllib3.Retry(total=2, connect=2, read=1, backoff_factor=0.2),
            )
            self._client = Minio(
                endpoint=self._endpoint,
                access_key=self._access_key,
                secret_key=self._secret_key,
                secure=self._secure,
                http_client=http_client,
            )
        if not self._initialized:
            self._ensure_bucket()
            self._initialized = True
        return self._client

    def _ensure_bucket(self) -> None:
        try:
            if not self._client.bucket_exists(self._bucket_name):
                logger.info("MinIO bucket '%s' not found. Creating it...", self._bucket_name)
                self._client.make_bucket(self._bucket_name)
                logger.info("MinIO bucket '%s' created successfully.", self._bucket_name)
        except Exception as exc:
            logger.warning("Could not verify/create MinIO bucket '%s': %s", self._bucket_name, exc)

    def _parse_uri_or_path(self, file_path_or_uri: str) -> tuple[str, str]:
        """
        Extracts (bucket, object_key) from an s3:// URI or local file path.
        """
        if file_path_or_uri.startswith("s3://") or file_path_or_uri.startswith("minio://"):
            parts = file_path_or_uri.split("/", 3)
            bucket = parts[2]
            key = parts[3] if len(parts) > 3 else ""
            return bucket, key

        # If it's a local path, map it relative to cache root
        p = Path(file_path_or_uri)
        try:
            rel = p.relative_to(self._local_cache)
            key = f"models/{rel.as_posix()}"
        except ValueError:
            key = f"models/{p.name}"
        return self._bucket_name, key

    def upload_model(
        self,
        model_id: str,
        version_label: str,
        filename: str,
        contents: bytes,
        user_id: str = "default_user",
    ) -> tuple[str, str, int]:
        client = self._get_client()
        stored_name = safe_filename(filename)
        object_key = f"models/{model_id}/{version_label}/{stored_name}"
        file_size = len(contents)

        # 1. Upload to MinIO object storage
        stream = io.BytesIO(contents)
        client.put_object(
            bucket_name=self._bucket_name,
            object_name=object_key,
            data=stream,
            length=file_size,
            content_type="application/octet-stream",
            metadata={
                "model_id": model_id,
                "version": version_label,
                "user_id": user_id,
                "original_filename": filename,
            },
        )
        s3_uri = f"s3://{self._bucket_name}/{object_key}"
        logger.info("Uploaded artifact to MinIO: %s (%d bytes)", s3_uri, file_size)

        # 2. Synchronize local runtime cache so local runners / tools have local disk access
        cache_path = self._local_cache / model_id / version_label / stored_name
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(contents)

        return stored_name, s3_uri, file_size

    def download_model(self, file_path_or_uri: str) -> bytes:
        bucket, key = self._parse_uri_or_path(file_path_or_uri)
        client = self._get_client()
        response = None
        try:
            response = client.get_object(bucket, key)
            data = response.read()
            return data
        except Exception as exc:
            # Fall back to local cache if object storage read fails
            p = Path(file_path_or_uri)
            if p.is_file():
                return p.read_bytes()
            raise FileNotFoundError(f"Failed to retrieve model artifact from MinIO ({bucket}/{key}): {exc}") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def model_exists(self, file_path_or_uri: str) -> bool:
        bucket, key = self._parse_uri_or_path(file_path_or_uri)
        client = self._get_client()
        try:
            client.stat_object(bucket, key)
            return True
        except Exception:
            p = Path(file_path_or_uri)
            return p.is_file()

    def load_model(self, file_path_or_uri: str) -> Any:
        data = self.download_model(file_path_or_uri)
        return joblib.load(io.BytesIO(data))

    def delete_model(self, file_path_or_uri: str) -> bool:
        bucket, key = self._parse_uri_or_path(file_path_or_uri)
        client = self._get_client()
        deleted = False
        try:
            client.remove_object(bucket, key)
            deleted = True
        except Exception as exc:
            logger.warning("MinIO delete error for %s/%s: %s", bucket, key, exc)

        # Clean local cache if present
        p = Path(file_path_or_uri)
        if p.is_file():
            p.unlink()
            deleted = True
        return deleted

    def get_model_metadata(self, file_path_or_uri: str) -> dict[str, Any]:
        bucket, key = self._parse_uri_or_path(file_path_or_uri)
        client = self._get_client()
        try:
            stat = client.stat_object(bucket, key)
            return {
                "size": stat.size,
                "etag": stat.etag,
                "last_modified": stat.last_modified.isoformat() if stat.last_modified else None,
                "content_type": stat.content_type,
                "metadata": stat.metadata,
                "uri": f"s3://{bucket}/{key}",
                "backend": "minio",
            }
        except Exception as exc:
            p = Path(file_path_or_uri)
            if p.is_file():
                st = p.stat()
                return {
                    "size": st.st_size,
                    "etag": None,
                    "last_modified": str(st.st_mtime),
                    "content_type": "application/octet-stream",
                    "uri": str(p),
                    "backend": "local-fallback",
                }
            raise FileNotFoundError(f"Object metadata not found: {exc}") from exc

    def list_models(self, prefix: str = "") -> list[dict[str, Any]]:
        client = self._get_client()
        target_prefix = prefix
        if not target_prefix.startswith("models/") and target_prefix:
            target_prefix = f"models/{target_prefix}"
        elif not target_prefix:
            target_prefix = "models/"

        results = []
        try:
            objects = client.list_objects(self._bucket_name, prefix=target_prefix, recursive=True)
            for obj in objects:
                if not obj.is_dir:
                    results.append({
                        "key": obj.object_name,
                        "size": obj.size,
                        "etag": obj.etag,
                        "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                        "uri": f"s3://{self._bucket_name}/{obj.object_name}",
                        "backend": "minio",
                    })
        except Exception as exc:
            logger.warning("Could not list MinIO objects: %s", exc)
        return results
