"""
SQLAlchemy / SQLite implementation of repository interfaces.
Wraps existing ModelForge SQLAlchemy models ensuring 100% backward compatibility.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import (
    AuditEvent,
    AutoScalingConfig,
    Deployment,
    Model,
    ModelVersion,
    Replica,
    User,
)
from app.services.database.interface import (
    IAuditRepository,
    IDeploymentRepository,
    IModelRepository,
    IUserRepository,
)

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"password", "password_hash", "token", "access_token", "secret", "jwt_secret_key"}


def _sanitize_details(details: Any) -> str | None:
    if details is None:
        return None
    if isinstance(details, str):
        return details
    if isinstance(details, dict):
        sanitized = {}
        for k, v in details.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v
        try:
            return json.dumps(sanitized, default=str)
        except Exception:
            return str(sanitized)
    return str(details)


class SQLiteModelRepository(IModelRepository):
    """SQLite / SQLAlchemy implementation for Model registry."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def _get_db(self) -> tuple[Session, bool]:
        if self._db is not None:
            return self._db, False
        return SessionLocal(), True

    def list_models(self) -> list[Model]:
        db, should_close = self._get_db()
        try:
            return list(db.scalars(select(Model).order_by(Model.created_at.desc())).all())
        finally:
            if should_close:
                db.close()

    def get_model(self, model_id: str) -> Model | None:
        db, should_close = self._get_db()
        try:
            return db.get(Model, model_id)
        finally:
            if should_close:
                db.close()

    def get_model_by_name(self, name: str) -> Model | None:
        db, should_close = self._get_db()
        try:
            return db.scalar(select(Model).where(Model.name == name))
        finally:
            if should_close:
                db.close()

    def create_model(self, name: str, user_id: str | None = None) -> Model:
        db, should_close = self._get_db()
        try:
            model = Model(name=name)
            db.add(model)
            db.commit()
            db.refresh(model)
            return model
        finally:
            if should_close:
                db.close()

    def delete_model(self, model_id: str) -> bool:
        db, should_close = self._get_db()
        try:
            model = db.get(Model, model_id)
            if not model:
                return False
            db.delete(model)
            db.commit()
            return True
        finally:
            if should_close:
                db.close()

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
    ) -> ModelVersion:
        db, should_close = self._get_db()
        try:
            mv = ModelVersion(
                model_id=model_id,
                version=version,
                framework=framework,
                model_type=model_type,
                supports_proba=supports_proba,
                original_filename=original_filename,
                stored_filename=stored_filename,
                file_path=file_path,
                file_size_bytes=file_size_bytes,
                status=status,
                is_active=is_active,
            )
            db.add(mv)
            db.commit()
            db.refresh(mv)
            return mv
        finally:
            if should_close:
                db.close()

    def get_version(self, model_id: str, version_label: str) -> ModelVersion | None:
        db, should_close = self._get_db()
        try:
            return db.scalar(
                select(ModelVersion).where(
                    ModelVersion.model_id == model_id,
                    ModelVersion.version == version_label,
                )
            )
        finally:
            if should_close:
                db.close()

    def get_version_by_id(self, version_id: str) -> ModelVersion | None:
        db, should_close = self._get_db()
        try:
            return db.get(ModelVersion, version_id)
        finally:
            if should_close:
                db.close()

    def delete_version(self, model_id: str, version_label: str) -> bool:
        db, should_close = self._get_db()
        try:
            v = db.scalar(
                select(ModelVersion).where(
                    ModelVersion.model_id == model_id,
                    ModelVersion.version == version_label,
                )
            )
            if not v:
                return False
            db.delete(v)
            db.commit()
            return True
        finally:
            if should_close:
                db.close()


class SQLiteDeploymentRepository(IDeploymentRepository):
    """SQLite / SQLAlchemy implementation for Deployment lifecycle."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def _get_db(self) -> tuple[Session, bool]:
        if self._db is not None:
            return self._db, False
        return SessionLocal(), True

    def list_deployments(self, model_id: str | None = None) -> list[Deployment]:
        db, should_close = self._get_db()
        try:
            query = select(Deployment).order_by(Deployment.created_at.desc())
            if model_id:
                query = query.where(Deployment.model_id == model_id)
            return list(db.scalars(query).all())
        finally:
            if should_close:
                db.close()

    def get_deployment(self, deployment_id: str) -> Deployment | None:
        db, should_close = self._get_db()
        try:
            return db.get(Deployment, deployment_id)
        finally:
            if should_close:
                db.close()

    def create_deployment(
        self,
        model_id: str,
        model_version_id: str,
        version_label: str,
        replicas: int = 1,
        endpoint: str | None = None,
        status: str = "deploying",
        is_containerized: bool = False,
    ) -> Deployment:
        db, should_close = self._get_db()
        try:
            d = Deployment(
                model_id=model_id,
                model_version_id=model_version_id,
                version_label=version_label,
                replicas=replicas,
                active_replicas=replicas if status == "running" else 0,
                endpoint=endpoint,
                status=status,
                is_containerized=is_containerized,
            )
            db.add(d)
            db.commit()
            db.refresh(d)
            return d
        finally:
            if should_close:
                db.close()

    def update_deployment(self, deployment_id: str, **fields: Any) -> Deployment | None:
        db, should_close = self._get_db()
        try:
            d = db.get(Deployment, deployment_id)
            if not d:
                return None
            for k, v in fields.items():
                if hasattr(d, k):
                    setattr(d, k, v)
            db.commit()
            db.refresh(d)
            return d
        finally:
            if should_close:
                db.close()

    def delete_deployment(self, deployment_id: str) -> bool:
        db, should_close = self._get_db()
        try:
            d = db.get(Deployment, deployment_id)
            if not d:
                return False
            db.delete(d)
            db.commit()
            return True
        finally:
            if should_close:
                db.close()

    def list_replicas(self, deployment_id: str) -> list[Replica]:
        db, should_close = self._get_db()
        try:
            return list(
                db.scalars(
                    select(Replica)
                    .where(Replica.deployment_id == deployment_id)
                    .order_by(Replica.created_at)
                ).all()
            )
        finally:
            if should_close:
                db.close()

    def get_autoscaling_config(self, deployment_id: str) -> AutoScalingConfig | None:
        db, should_close = self._get_db()
        try:
            return db.scalar(
                select(AutoScalingConfig).where(AutoScalingConfig.deployment_id == deployment_id)
            )
        finally:
            if should_close:
                db.close()

    def save_autoscaling_config(self, deployment_id: str, **fields: Any) -> AutoScalingConfig:
        db, should_close = self._get_db()
        try:
            cfg = db.scalar(
                select(AutoScalingConfig).where(AutoScalingConfig.deployment_id == deployment_id)
            )
            if cfg is None:
                cfg = AutoScalingConfig(deployment_id=deployment_id, **fields)
                db.add(cfg)
            else:
                for k, v in fields.items():
                    if hasattr(cfg, k):
                        setattr(cfg, k, v)
            db.commit()
            db.refresh(cfg)
            return cfg
        finally:
            if should_close:
                db.close()


class SQLiteUserRepository(IUserRepository):
    """SQLite / SQLAlchemy implementation for User profile records."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def _get_db(self) -> tuple[Session, bool]:
        if self._db is not None:
            return self._db, False
        return SessionLocal(), True

    def list_users(self) -> list[User]:
        db, should_close = self._get_db()
        try:
            return list(db.scalars(select(User).order_by(User.created_at.desc())).all())
        finally:
            if should_close:
                db.close()

    def get_user_by_id(self, user_id: str) -> User | None:
        db, should_close = self._get_db()
        try:
            return db.get(User, user_id)
        finally:
            if should_close:
                db.close()

    def get_user_by_email(self, email: str) -> User | None:
        db, should_close = self._get_db()
        try:
            clean_email = email.strip().lower()
            return db.scalar(select(User).where(User.email == clean_email))
        finally:
            if should_close:
                db.close()

    def create_user(
        self,
        email: str,
        display_name: str,
        role: str = "VIEWER",
        password_hash: str = "",
        is_active: bool = True,
        user_id: str | None = None,
    ) -> User:
        db, should_close = self._get_db()
        try:
            clean_email = email.strip().lower()
            user = User(
                email=clean_email,
                display_name=display_name.strip(),
                password_hash=password_hash,
                role=role.upper(),
                is_active=is_active,
            )
            if user_id:
                user.id = user_id
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        finally:
            if should_close:
                db.close()

    def update_user(self, user_id: str, **fields: Any) -> User | None:
        db, should_close = self._get_db()
        try:
            user = db.get(User, user_id)
            if not user:
                return None
            for k, v in fields.items():
                if hasattr(user, k):
                    if k == "role" and isinstance(v, str):
                        v = v.upper()
                    setattr(user, k, v)
            db.commit()
            db.refresh(user)
            return user
        finally:
            if should_close:
                db.close()

    def delete_user(self, user_id: str) -> bool:
        db, should_close = self._get_db()
        try:
            user = db.get(User, user_id)
            if not user:
                return False
            db.delete(user)
            db.commit()
            return True
        finally:
            if should_close:
                db.close()

    def count_users(self) -> int:
        db, should_close = self._get_db()
        try:
            return db.scalar(select(func.count(User.id))) or 0
        finally:
            if should_close:
                db.close()


class SQLiteAuditRepository(IAuditRepository):
    """SQLite / SQLAlchemy implementation for Audit events."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db

    def _get_db(self) -> tuple[Session, bool]:
        if self._db is not None:
            return self._db, False
        return SessionLocal(), True

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
    ) -> AuditEvent | None:
        db, should_close = self._get_db()
        try:
            event = AuditEvent(
                action=action.upper(),
                resource_type=resource_type,
                resource_id=str(resource_id) if resource_id else None,
                user_id=str(user_id) if user_id else None,
                user_email=str(user_email) if user_email else None,
                details=_sanitize_details(details),
                ip_address=str(ip_address) if ip_address else None,
                success=success,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            return event
        except Exception as exc:
            logger.error("Failed to log audit event: %s", exc)
            db.rollback()
            return None
        finally:
            if should_close:
                db.close()

    def query_events(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[AuditEvent], int]:
        db, should_close = self._get_db()
        try:
            query = select(AuditEvent)
            count_query = select(func.count(AuditEvent.id))

            if user_id:
                query = query.where(AuditEvent.user_id == user_id)
                count_query = count_query.where(AuditEvent.user_id == user_id)
            if action:
                query = query.where(AuditEvent.action == action.upper())
                count_query = count_query.where(AuditEvent.action == action.upper())
            if date_from:
                query = query.where(AuditEvent.timestamp >= date_from)
                count_query = count_query.where(AuditEvent.timestamp >= date_from)
            if date_to:
                query = query.where(AuditEvent.timestamp <= date_to)
                count_query = count_query.where(AuditEvent.timestamp <= date_to)

            total = db.scalar(count_query) or 0
            items = list(
                db.scalars(
                    query.order_by(desc(AuditEvent.timestamp)).offset(offset).limit(limit)
                ).all()
            )
            return items, total
        finally:
            if should_close:
                db.close()

    def export_csv(
        self,
        user_id: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        max_records: int = 5000,
    ) -> str:
        events, _ = self.query_events(
            limit=max_records,
            offset=0,
            user_id=user_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Event ID", "Timestamp (UTC)", "Action", "Resource Type",
            "Resource ID", "User ID", "User Email", "IP Address", "Success", "Details",
        ])
        for e in events:
            writer.writerow([
                e.id,
                e.timestamp.isoformat() if e.timestamp else "",
                e.action,
                e.resource_type,
                e.resource_id or "",
                e.user_id or "",
                e.user_email or "",
                e.ip_address or "",
                "SUCCESS" if e.success else "FAILURE",
                e.details or "",
            ])
        return output.getvalue()
