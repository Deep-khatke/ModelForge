"""
Model Artifact Storage abstraction layer.

Allows ModelForge to store model binary artifacts on local filesystem
or seamlessly switch to cloud object storage (e.g., MinIO, S3, GCS, Azure Blob)
without changing business logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ModelArtifactStore(ABC):
    """Abstract interface for model artifact persistence across storage backends."""

    @abstractmethod
    def upload_model(
        self,
        model_id: str,
        version_label: str,
        filename: str,
        contents: bytes,
        user_id: str = "default_user",
    ) -> tuple[str, str, int]:
        """
        Uploads model bytes into storage.
        Returns tuple of (stored_filename, file_path_or_uri, file_size_bytes).
        """
        pass

    def save_artifact(
        self,
        model_id: str,
        version_label: str,
        original_filename: str,
        contents: bytes,
    ) -> tuple[str, str, int]:
        """Backwards-compatible alias for upload_model."""
        return self.upload_model(
            model_id=model_id,
            version_label=version_label,
            filename=original_filename,
            contents=contents,
        )

    @abstractmethod
    def download_model(self, file_path_or_uri: str) -> bytes:
        """Read artifact raw bytes from path or object URI."""
        pass

    def load_bytes(self, file_path_or_uri: str) -> bytes:
        """Backwards-compatible alias for download_model."""
        return self.download_model(file_path_or_uri)

    @abstractmethod
    def load_model(self, file_path_or_uri: str) -> Any:
        """Deserializes and loads the model into memory (e.g. via joblib)."""
        pass

    @abstractmethod
    def delete_model(self, file_path_or_uri: str) -> bool:
        """Deletes an artifact if it exists. Returns True if deleted."""
        pass

    def delete_artifact(self, file_path_or_uri: str) -> bool:
        """Backwards-compatible alias for delete_model."""
        return self.delete_model(file_path_or_uri)

    @abstractmethod
    def model_exists(self, file_path_or_uri: str) -> bool:
        """Check whether an artifact exists at the given path or URI."""
        pass

    def artifact_exists(self, file_path_or_uri: str) -> bool:
        """Backwards-compatible alias for model_exists."""
        return self.model_exists(file_path_or_uri)

    @abstractmethod
    def get_model_metadata(self, file_path_or_uri: str) -> dict[str, Any]:
        """Retrieve metadata for the artifact (size, last modified, ETag, URI)."""
        pass

    @abstractmethod
    def list_models(self, prefix: str = "") -> list[dict[str, Any]]:
        """List all model artifacts matching prefix."""
        pass
