"""
Factory for creating and retrieving the active ModelArtifactStore backend.
"""
from __future__ import annotations

import logging
from typing import Literal

from app.config import settings
from app.services.storage.interface import ModelArtifactStore
from app.services.storage.local_storage import LocalStorageArtifactStore

logger = logging.getLogger(__name__)

_store_instance: ModelArtifactStore | None = None


def get_artifact_store(
    backend_override: Literal["local", "minio", "s3"] | None = None,
) -> ModelArtifactStore:
    """
    Returns the configured ModelArtifactStore singleton.
    Backend selection priority:
    1. backend_override argument if supplied
    2. settings.model_storage_backend ("local", "minio", "s3")
    """
    global _store_instance
    chosen_backend = (backend_override or settings.model_storage_backend).lower()

    if backend_override is not None:
        # Build non-singleton instance for explicit override/tests
        if chosen_backend in ("minio", "s3"):
            from app.services.storage.minio_storage import MinioStorageArtifactStore
            return MinioStorageArtifactStore()
        return LocalStorageArtifactStore()

    if _store_instance is None:
        if chosen_backend in ("minio", "s3"):
            from app.services.storage.minio_storage import MinioStorageArtifactStore
            logger.info("Initializing MinIO / S3 Object Storage backend (endpoint=%s, bucket=%s)",
                        settings.minio_endpoint, settings.minio_bucket)
            _store_instance = MinioStorageArtifactStore()
        else:
            logger.info("Initializing Local Filesystem Storage backend (path=%s)", settings.model_storage_path)
            _store_instance = LocalStorageArtifactStore()

    return _store_instance


def reset_artifact_store() -> None:
    """Reset store singleton (used in test fixtures)."""
    global _store_instance
    _store_instance = None
