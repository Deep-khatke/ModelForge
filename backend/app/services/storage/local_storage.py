"""
Local filesystem implementation of ModelArtifactStore.
Stores artifacts under storage/models/<model_id>/<version_label>/<stored_filename>.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Any

import joblib

from app.config import settings
from app.services.storage.interface import ModelArtifactStore
from app.utils import safe_filename

logger = logging.getLogger(__name__)


class LocalStorageArtifactStore(ModelArtifactStore):
    """Stores model files directly on the local filesystem."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        if base_dir is None:
            self._base_path = settings.model_storage_path
        else:
            self._base_path = Path(base_dir).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def base_path(self) -> Path:
        return self._base_path

    def upload_model(
        self,
        model_id: str,
        version_label: str,
        filename: str,
        contents: bytes,
        user_id: str = "default_user",
    ) -> tuple[str, str, int]:
        version_dir = self._base_path / model_id / version_label
        version_dir.mkdir(parents=True, exist_ok=True)
        stored_name = safe_filename(filename)
        dest_path = version_dir / stored_name
        dest_path.write_bytes(contents)
        file_size = len(contents)
        logger.info("Saved artifact locally: %s (%d bytes)", dest_path, file_size)
        return stored_name, str(dest_path), file_size

    def download_model(self, file_path_or_uri: str) -> bytes:
        p = Path(file_path_or_uri)
        if not p.is_file():
            raise FileNotFoundError(f"Model artifact not found locally at {file_path_or_uri}")
        return p.read_bytes()

    def model_exists(self, file_path_or_uri: str) -> bool:
        return Path(file_path_or_uri).is_file()

    def load_model(self, file_path_or_uri: str) -> Any:
        return joblib.load(file_path_or_uri)

    def delete_model(self, file_path_or_uri: str) -> bool:
        path = Path(file_path_or_uri)
        if path.is_file():
            path.unlink()
            return True
        return False

    def get_model_metadata(self, file_path_or_uri: str) -> dict[str, Any]:
        p = Path(file_path_or_uri)
        if not p.is_file():
            raise FileNotFoundError(f"Model artifact not found locally at {file_path_or_uri}")
        stat = p.stat()
        return {
            "size": stat.st_size,
            "last_modified": datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc).isoformat(),
            "uri": str(p),
            "backend": "local",
        }

    def list_models(self, prefix: str = "") -> list[dict[str, Any]]:
        results = []
        target_dir = self._base_path
        if prefix:
            target_dir = self._base_path / prefix
        if not target_dir.exists():
            return []
        for p in target_dir.rglob("*.joblib"):
            if p.is_file():
                results.append(self.get_model_metadata(str(p)))
        return results


# Default singleton instance
artifact_store = LocalStorageArtifactStore()
