"""Pydantic schemas used for API request/response validation."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class ModelVersionOut(BaseModel):
    """A single uploaded version of a model, as returned by the API."""

    # protected_namespaces=() silences pydantic's "model_*" field name
    # warning for fields like `model_id` / `model_type`, which describe
    # the ML model, not pydantic's own API.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    model_id: str
    version: str
    framework: str
    model_type: str | None
    supports_proba: bool
    original_filename: str
    file_size_bytes: int
    status: str
    is_active: bool
    created_at: datetime


class ModelOut(BaseModel):
    """A logical model plus all of its versions."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    owner_id: str | None = None
    created_at: datetime
    versions: list[ModelVersionOut] = []


class ErrorResponse(BaseModel):
    detail: str


class DeploymentCreate(BaseModel):
    """Request body for POST /api/v1/deployments."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    version: str | None = None  # defaults to the model's active version
    replicas: int = 1


class DeploymentOut(BaseModel):
    """A deployment record, as returned by the API."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    model_id: str
    model_name: str
    model_version_id: str
    version_label: str
    owner_id: str | None = None
    status: str
    endpoint: str | None
    replicas: int
    active_replicas: int = 1
    scaling_status: str = "stable"
    is_containerized: bool = False
    autoscaling_enabled: bool = False
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ScaleRequest(BaseModel):
    """Request payload for POST /api/v1/deployments/{id}/scale."""

    replicas: int


class ScaleResponse(BaseModel):
    """Response payload for scaling endpoint."""

    model_config = ConfigDict(protected_namespaces=())

    deployment_id: str
    previous_replicas: int
    requested_replicas: int
    active_replicas: int
    scaling_status: str
    status: str


class ReplicaOut(BaseModel):
    """Information on an individual inference replica."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    deployment_id: str
    replica_id: str
    status: str
    requests_count: int
    avg_latency_ms: float
    container_id: str | None = None
    container_port: int | None = None
    endpoint_url: str | None = None
    is_containerized: bool = False


class ReplicaMetricsOut(BaseModel):
    """Observed monitoring data for one replica in a deployment."""

    model_config = ConfigDict(protected_namespaces=())

    replica_id: str
    status: str
    request_count: int
    successful_requests: int
    failed_requests: int
    average_latency_ms: float
    last_seen: datetime | None = None


class RecentInferenceOut(BaseModel):
    """A paged recent request record; the ORM id is the request identifier."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    timestamp: datetime
    deployment_id: str
    model_id: str
    model_version: str
    replica_id: str
    latency_ms: float
    status: str
    error_message: str | None = None


class RecentInferencesPage(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    items: list[RecentInferenceOut]
    limit: int
    offset: int
    has_more: bool


class InferenceLogOut(BaseModel):
    """Recorded entry of an inference request."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    timestamp: datetime
    deployment_id: str
    model_id: str
    model_version: str
    replica_id: str
    latency_ms: float
    status: str
    error_message: str | None = None


class PredictRequest(BaseModel):
    """Request body for POST /api/v1/models/{model_id}/predict."""

    features: list[Any]


class PredictResponse(BaseModel):
    """Response payload returned by the inference API."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    model_name: str
    deployment_id: str
    version: str
    replica_id: str
    predictions: list[Any]
    probabilities: list[Any] | None = None
    inference_time_ms: float


class LoadTestRequest(BaseModel):
    """Request payload for POST /api/v1/deployments/{id}/load-test."""

    requests: int = 20
    features: list[Any] | None = None


class LoadTestResponse(BaseModel):
    """Metrics returned by load testing endpoint."""

    model_config = ConfigDict(protected_namespaces=())

    total_requests: int
    successful_requests: int
    failed_requests: int
    average_latency_ms: float
    throughput_requests_per_second: float
    replicas_used: int
    replica_distribution: dict[str, int]


class MonitoringSummaryOut(BaseModel):
    """System-wide operational metrics summary."""

    model_config = ConfigDict(protected_namespaces=())

    time_range: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_percent: float
    average_latency_ms: float
    min_latency_ms: float
    max_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    throughput_rps: float
    active_deployments_count: int
    active_replicas_count: int


class DeploymentMetricsOut(BaseModel):
    """Metrics for a specific deployment."""

    model_config = ConfigDict(protected_namespaces=())

    deployment_id: str
    model_id: str
    model_name: str
    version_label: str
    status: str
    scaling_status: str
    replicas: int
    active_replicas: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    error_rate_percent: float
    average_latency_ms: float
    p95_latency_ms: float
    throughput_rps: float


class ModelMetricsOut(BaseModel):
    """Metrics for a model grouped by version."""

    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    model_name: str
    total_requests: int
    average_latency_ms: float
    versions_metrics: list[dict[str, Any]]


class TimeSeriesPoint(BaseModel):
    """Data point for graph visualizations over time."""

    model_config = ConfigDict(protected_namespaces=())

    timestamp: datetime
    request_count: int
    average_latency_ms: float
    p95_latency_ms: float
    error_rate_percent: float


class SystemMetricsOut(BaseModel):
    """Host resource metrics collected via psutil."""

    model_config = ConfigDict(protected_namespaces=())

    cpu_percent: float | None = None
    memory_percent: float | None = None


class AlertOut(BaseModel):
    """Operational alert notice."""

    model_config = ConfigDict(protected_namespaces=())

    alert_type: str
    title: str
    message: str
    severity: str
    timestamp: datetime
    deployment_id: str | None = None


class ExperimentRunRequest(BaseModel):
    """Payload to trigger a controlled benchmark experiment."""

    deployment_id: str
    requests: int = 100
    features: list[Any] | None = None


class ExperimentOut(BaseModel):
    """Stored benchmark experiment result."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    deployment_id: str
    model_id: str
    model_name: str
    model_version: str
    replica_count: int
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_latency_ms: float
    p95_latency_ms: float
    throughput_rps: float
    error_rate_percent: float
    autoscaling_enabled: bool = False
    started_at: datetime
    completed_at: datetime


class AutoScalingConfigUpdate(BaseModel):
    """Payload to update auto-scaling configuration."""

    model_config = ConfigDict(protected_namespaces=())

    enabled: bool | None = None
    min_replicas: int | None = None
    max_replicas: int | None = None
    target_latency_ms: float | None = None
    target_throughput_rps: float | None = None
    scale_up_error_rate_percent: float | None = None
    scale_down_idle_seconds: int | None = None
    cooldown_seconds: int | None = None
    evaluation_interval_seconds: int | None = None


class AutoScalingConfigOut(BaseModel):
    """Auto-scaling configuration and state for a deployment."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    deployment_id: str
    enabled: bool
    min_replicas: int
    max_replicas: int
    target_latency_ms: float
    target_throughput_rps: float
    scale_up_error_rate_percent: float
    scale_down_idle_seconds: int
    cooldown_seconds: int
    evaluation_interval_seconds: int
    last_evaluated_at: datetime | None = None
    last_scaled_at: datetime | None = None
    cooldown_remaining_seconds: int = 0
    is_in_cooldown: bool = False


class ScalingEventOut(BaseModel):
    """Record of a scaling evaluation decision."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    event_id: str | None = None
    timestamp: datetime
    deployment_id: str
    previous_replicas: int
    target_replicas: int
    action: str
    trigger_reason: str
    observed_p95_latency_ms: float | None = None
    observed_throughput_rps: float | None = None
    observed_error_rate_percent: float | None = None
    success: bool = True
    error_message: str | None = None

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not self.event_id:
            self.event_id = self.id


class AutoScalingEvaluationResult(BaseModel):
    """Outcome of an immediate auto-scaling evaluation."""

    model_config = ConfigDict(protected_namespaces=())

    deployment_id: str
    action: str
    previous_replicas: int
    target_replicas: int
    trigger_reason: str
    observed_p95_latency_ms: float | None = None
    observed_throughput_rps: float | None = None
    observed_error_rate_percent: float | None = None
    cooldown_active: bool = False
    success: bool = True
    error_message: str | None = None


# --- Phase 8: Authentication, Authorization & Audit Schemas ---

VALID_ROLES = {"ADMIN", "OPERATOR", "VIEWER"}


class UserCreate(BaseModel):
    """Payload for creating a new user account."""

    email: str
    password: str
    display_name: str
    role: str = "VIEWER"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or "." not in v.split("@")[-1] or len(v) < 5:
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        role_upper = v.strip().upper()
        if role_upper not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return role_upper


class UserUpdate(BaseModel):
    """Payload for updating an existing user account."""

    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str | None) -> str | None:
        if v is None:
            return None
        role_upper = v.strip().upper()
        if role_upper not in VALID_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(sorted(VALID_ROLES))}")
        return role_upper

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class UserOut(BaseModel):
    """User representation returned in API responses (never reveals password hash)."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    user_id: str | None = None
    email: str
    display_name: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_login_at: datetime | None = None

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not self.user_id:
            self.user_id = self.id


class LoginRequest(BaseModel):
    """Payload for POST /api/v1/auth/login."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """JWT bearer token and authenticated user details."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut


class AuditEventOut(BaseModel):
    """Immutable audit event record."""

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    event_id: str | None = None
    timestamp: datetime
    user_id: str | None = None
    user_email: str | None = None
    action: str
    resource_type: str
    resource_id: str | None = None
    details: str | None = None
    ip_address: str | None = None
    success: bool = True

    def __init__(self, **data: Any):
        super().__init__(**data)
        if not self.event_id:
            self.event_id = self.id


class AuditEventsPage(BaseModel):
    """Paged response for audit event queries."""

    items: list[AuditEventOut]
    total: int
    limit: int
    offset: int

