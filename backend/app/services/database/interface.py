"""
Database Repository Interface Layer.

Provides abstract repository contracts for models, deployments, users, and audit logs.
Decouples FastAPI routers from direct ORM / Firestore calls.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class IModelRepository(ABC):
    """Repository contract for logical models and model versions."""

    @abstractmethod
    def list_models(self) -> list[Any]:
        """List all models sorted by created_at descending."""
        pass

    @abstractmethod
    def get_model(self, model_id: str) -> Any | None:
        """Get model by ID with all versions and deployments."""
        pass

    @abstractmethod
    def get_model_by_name(self, name: str) -> Any | None:
        """Get model by unique name."""
        pass

    @abstractmethod
    def create_model(self, name: str, user_id: str | None = None) -> Any:
        """Create a new logical model grouping."""
        pass

    @abstractmethod
    def delete_model(self, model_id: str) -> bool:
        """Delete model and its cascaded versions/deployments."""
        pass

    @abstractmethod
    def create_version(
        self,
        model_id: str,
        version: str,
        framework: str,
        model_type: str | None,
        supports_proba: bool,
        original_filename: str,
        stored_filename: str,
        file_path: str,
        file_size_bytes: int,
        status: str = "uploaded",
        is_active: bool = False,
    ) -> Any:
        """Create a new version artifact record for a model."""
        pass

    @abstractmethod
    def get_version(self, model_id: str, version_label: str) -> Any | None:
        """Get a specific model version by label (e.g. 'v1')."""
        pass

    @abstractmethod
    def get_version_by_id(self, version_id: str) -> Any | None:
        """Get version by primary ID."""
        pass

    @abstractmethod
    def delete_version(self, model_id: str, version_label: str) -> bool:
        """Delete a single version artifact record."""
        pass


class IDeploymentRepository(ABC):
    """Repository contract for deployments, replicas, and auto-scaling policies."""

    @abstractmethod
    def list_deployments(self, model_id: str | None = None) -> list[Any]:
        """List deployments, optionally filtered by model."""
        pass

    @abstractmethod
    def get_deployment(self, deployment_id: str) -> Any | None:
        """Get deployment by ID."""
        pass

    @abstractmethod
    def create_deployment(
        self,
        model_id: str,
        model_version_id: str,
        version_label: str,
        replicas: int = 1,
        endpoint: str | None = None,
        status: str = "deploying",
        is_containerized: bool = False,
    ) -> Any:
        """Create a new deployment record."""
        pass

    @abstractmethod
    def update_deployment(self, deployment_id: str, **fields: Any) -> Any | None:
        """Update fields on a deployment."""
        pass

    @abstractmethod
    def delete_deployment(self, deployment_id: str) -> bool:
        """Delete a deployment and its replica instances."""
        pass

    @abstractmethod
    def list_replicas(self, deployment_id: str) -> list[Any]:
        """List active replica instances for a deployment."""
        pass

    @abstractmethod
    def get_autoscaling_config(self, deployment_id: str) -> Any | None:
        """Get autoscaling configuration for a deployment."""
        pass

    @abstractmethod
    def save_autoscaling_config(self, deployment_id: str, **fields: Any) -> Any:
        """Create or update autoscaling configuration."""
        pass


class IUserRepository(ABC):
    """Repository contract for user management and RBAC authorization profiles."""

    @abstractmethod
    def list_users(self) -> list[Any]:
        """List all registered users."""
        pass

    @abstractmethod
    def get_user_by_id(self, user_id: str) -> Any | None:
        """Get user by unique ID."""
        pass

    @abstractmethod
    def get_user_by_email(self, email: str) -> Any | None:
        """Get user by normalized email."""
        pass

    @abstractmethod
    def create_user(
        self,
        email: str,
        display_name: str,
        role: str = "VIEWER",
        password_hash: str = "",
        is_active: bool = True,
        user_id: str | None = None,
    ) -> Any:
        """Create a new user account profile."""
        pass

    @abstractmethod
    def update_user(self, user_id: str, **fields: Any) -> Any | None:
        """Update user properties (role, display_name, active status, last_login)."""
        pass

    @abstractmethod
    def delete_user(self, user_id: str) -> bool:
        """Delete a user account."""
        pass

    @abstractmethod
    def count_users(self) -> int:
        """Get total user count."""
        pass


class IAuditRepository(ABC):
    """Repository contract for immutable audit log records."""

    @abstractmethod
    def log_event(
        self,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        user_id: str | None = None,
        user_email: str | None = None,
        details: Any = None,
        ip_address: str | None = None,
        success: bool = True,
    ) -> Any | None:
        """Append an immutable audit event."""
        pass

    @abstractmethod
    def query_events(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[Any], int]:
        """Retrieve paginated audit events with optional filters."""
        pass

    @abstractmethod
    def export_csv(
        self,
        user_id: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        max_records: int = 5000,
    ) -> str:
        """Export audit events as CSV."""
        pass
