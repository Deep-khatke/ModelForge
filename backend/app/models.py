"""
ORM models for the model registry.

Two tables:

- Model:        a logical, named model (e.g. "fraud_detector"). Groups
                 together every version that has ever been uploaded for it.
- ModelVersion:  one uploaded artifact (e.g. "fraud_detector" v1, v2, v3).
                 Each version points at its own file on disk and is never
                 overwritten by later uploads.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Model(Base):
    """A logical model grouping (identified by a unique name)."""

    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    versions: Mapped[list["ModelVersion"]] = relationship(
        "ModelVersion",
        back_populates="model",
        cascade="all, delete-orphan",
        order_by="ModelVersion.created_at",
    )
    deployments: Mapped[list["Deployment"]] = relationship(
        "Deployment",
        back_populates="model",
        cascade="all, delete-orphan",
        order_by="Deployment.created_at",
    )

    @property
    def active_version(self) -> "ModelVersion | None":
        for v in self.versions:
            if v.is_active:
                return v
        return None

    @property
    def current_deployment(self) -> "Deployment | None":
        """The deployment currently serving traffic for this model, if any."""
        for d in self.deployments:
            if d.status == "running":
                return d
        return None


class ModelVersion(Base):
    """One uploaded model artifact belonging to a logical Model."""

    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_id", "version", name="uq_model_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    model_id: Mapped[str] = mapped_column(String, ForeignKey("models.id"), nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "v1"

    framework: Mapped[str] = mapped_column(String, default="sklearn")
    model_type: Mapped[str] = mapped_column(String, nullable=True)  # e.g. RandomForestClassifier
    supports_proba: Mapped[bool] = mapped_column(default=False)

    original_filename: Mapped[str] = mapped_column(String, nullable=False)
    stored_filename: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String, default="uploaded")
    is_active: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    model: Mapped["Model"] = relationship("Model", back_populates="versions")


class Deployment(Base):
    """
    One deployment "slot" for a model: a record of deploying a specific
    version to serve inference traffic.

    MVP NOTE: Phase 2 does not yet spin up a separate container/process
    per deployment (that lands with Docker support in a later phase).
    "Deploying" here means: validate the artifact loads correctly, mark
    any previously running deployment for this model as stopped, and mark
    this one as the model's current serving deployment. The status field
    and replica count are tracked for real so the deployment lifecycle
    and later scaling/monitoring phases have something real to build on.
    """

    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    model_id: Mapped[str] = mapped_column(String, ForeignKey("models.id"), nullable=False)
    model_version_id: Mapped[str] = mapped_column(
        String, ForeignKey("model_versions.id"), nullable=False
    )
    owner_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)

    # Denormalized for convenience/history - the version label ("v2") is
    # kept even if the underlying ModelVersion row were ever deleted.
    version_label: Mapped[str] = mapped_column(String, nullable=False)

    status: Mapped[str] = mapped_column(String, default="deploying")
    # one of: "deploying", "running", "stopped", "failed"

    endpoint: Mapped[str] = mapped_column(String, nullable=True)
    replicas: Mapped[int] = mapped_column(Integer, default=1)
    active_replicas: Mapped[int] = mapped_column(Integer, default=1)
    scaling_status: Mapped[str] = mapped_column(String, default="stable")
    is_containerized: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    model: Mapped["Model"] = relationship("Model", back_populates="deployments")
    model_version: Mapped["ModelVersion"] = relationship("ModelVersion")
    replica_instances: Mapped[list["Replica"]] = relationship(
        "Replica",
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="Replica.created_at",
    )
    autoscaling_config: Mapped["AutoScalingConfig | None"] = relationship(
        "AutoScalingConfig",
        back_populates="deployment",
        uselist=False,
        cascade="all, delete-orphan",
    )
    scaling_events: Mapped[list["ScalingEvent"]] = relationship(
        "ScalingEvent",
        back_populates="deployment",
        cascade="all, delete-orphan",
        order_by="ScalingEvent.timestamp.desc()",
    )


class Replica(Base):
    """An individual inference replica instance belonging to a Deployment."""

    __tablename__ = "replicas"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(String, ForeignKey("deployments.id"), nullable=False)
    replica_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="healthy")
    requests_count: Mapped[int] = mapped_column(Integer, default=0)
    total_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    container_id: Mapped[str | None] = mapped_column(String, nullable=True)
    container_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    endpoint_url: Mapped[str | None] = mapped_column(String, nullable=True)
    is_containerized: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    deployment: Mapped["Deployment"] = relationship("Deployment", back_populates="replica_instances")


class InferenceLog(Base):
    """Log record of an individual inference request for tracking & monitoring."""

    __tablename__ = "inference_logs"
    __table_args__ = (
        Index("ix_inference_logs_deployment_timestamp", "deployment_id", "timestamp"),
        Index("ix_inference_logs_model_timestamp", "model_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    deployment_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    replica_id: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String, default="success")
    error_message: Mapped[str] = mapped_column(String, nullable=True)


class ReplicaHealthEvent(Base):
    """An observed replica health transition, retained for operational history."""

    __tablename__ = "replica_health_events"
    __table_args__ = (Index("ix_health_events_deployment_timestamp", "deployment_id", "timestamp"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    deployment_id: Mapped[str] = mapped_column(String, ForeignKey("deployments.id"), nullable=False)
    replica_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)


class Experiment(Base):
    """Record of a controlled performance benchmark experiment."""

    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    model_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    replica_count: Mapped[int] = mapped_column(Integer, default=1)
    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    successful_requests: Mapped[int] = mapped_column(Integer, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, default=0)
    average_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    p95_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    throughput_rps: Mapped[float] = mapped_column(Float, default=0.0)
    error_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    autoscaling_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AutoScalingConfig(Base):
    """Per-deployment horizontal auto-scaling configuration."""

    __tablename__ = "autoscaling_configs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    deployment_id: Mapped[str] = mapped_column(
        String, ForeignKey("deployments.id"), unique=True, nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    min_replicas: Mapped[int] = mapped_column(Integer, default=1)
    max_replicas: Mapped[int] = mapped_column(Integer, default=5)
    target_latency_ms: Mapped[float] = mapped_column(Float, default=200.0)
    target_throughput_rps: Mapped[float] = mapped_column(Float, default=50.0)
    scale_up_error_rate_percent: Mapped[float] = mapped_column(Float, default=10.0)
    scale_down_idle_seconds: Mapped[int] = mapped_column(Integer, default=120)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    evaluation_interval_seconds: Mapped[int] = mapped_column(Integer, default=30)

    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scaled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    deployment: Mapped["Deployment"] = relationship("Deployment", back_populates="autoscaling_config")


class ScalingEvent(Base):
    """Historical record of an automated or manual scaling evaluation decision."""

    __tablename__ = "scaling_events"
    __table_args__ = (
        Index("ix_scaling_events_deployment_timestamp", "deployment_id", "timestamp"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    deployment_id: Mapped[str] = mapped_column(
        String, ForeignKey("deployments.id"), index=True, nullable=False
    )
    previous_replicas: Mapped[int] = mapped_column(Integer, nullable=False)
    target_replicas: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # "SCALE_UP", "SCALE_DOWN", "NO_ACTION"
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    observed_p95_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_throughput_rps: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_error_rate_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    deployment: Mapped["Deployment"] = relationship("Deployment", back_populates="scaling_events")


class User(Base):
    """User account record for authentication and role-based access control."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, default="VIEWER", nullable=False)  # "ADMIN", "OPERATOR", "VIEWER"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    """Historical immutable record of state-changing actions and security events."""

    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    user_email: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

