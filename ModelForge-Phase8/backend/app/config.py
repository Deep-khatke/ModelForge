"""
Centralized application configuration.

All configurable values are read from environment variables (optionally
loaded from a local ".env" file) so that nothing is hard-coded, and so the
same code can move from SQLite -> PostgreSQL, or local disk -> cloud
storage, later on without code changes.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database -----------------------------------------------------
    database_url: str = "sqlite:///./modelforge.db"

    # --- Storage --------------------------------------------------------
    model_storage_dir: str = "./storage/models"
    max_upload_size_mb: int = 50
    allowed_model_extensions: str = ".joblib"

    # --- CORS -------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- API metadata ---------------------------------------------------
    api_title: str = "ModelForge API"
    api_version: str = "0.1.0"

    # --- Replica & Scaling Settings ------------------------------------
    max_replicas: int = 5
    default_replicas: int = 1

    # --- Monitoring & Alerting Settings --------------------------------
    alert_latency_threshold_ms: float = 500.0
    alert_error_rate_threshold_percent: float = 5.0
    monitoring_retention_days: int = 30

    # --- Docker & Container Settings (Phase 6) ------------------------
    docker_enabled: bool = False
    docker_network: str = "modelforge-network"
    inference_image: str = "modelforge-inference:latest"
    container_healthcheck_timeout_sec: float = 5.0
    model_storage_mount: str | None = None
    container_port_start: int = 8100

    # --- Auto-Scaling Settings (Phase 7) ------------------------------
    autoscaling_background_enabled: bool = True
    autoscaling_default_min_replicas: int = 1
    autoscaling_default_max_replicas: int = 5
    autoscaling_default_target_latency_ms: float = 200.0
    autoscaling_default_target_throughput_rps: float = 50.0
    autoscaling_default_scale_up_error_rate_percent: float = 10.0
    autoscaling_default_scale_down_idle_seconds: int = 120
    autoscaling_default_cooldown_seconds: int = 60
    autoscaling_default_evaluation_interval_seconds: int = 30
    autoscaling_loop_sleep_seconds: int = 15

    # --- Authentication, Authorization & Security (Phase 8) -----------
    auth_enabled: bool = True
    jwt_secret_key: str = "modelforge-secret-key-32-chars-minimum-token-protection"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    allow_public_registration: bool = False
    initial_admin_email: str = "admin@modelforge.local"
    initial_admin_password: str = "AdminPassword123!"
    initial_admin_name: str = "ModelForge Administrator"

    # protected_namespaces=() silences pydantic's default "model_*" field
    # name warning - several of our settings (e.g. model_storage_dir) are
    # legitimately about ML models, not about pydantic's own `model_*` API.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", protected_namespaces=()
    )

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [
            ext.strip().lower()
            for ext in self.allowed_model_extensions.split(",")
            if ext.strip()
        ]

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def model_storage_path(self) -> Path:
        path = Path(self.model_storage_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
