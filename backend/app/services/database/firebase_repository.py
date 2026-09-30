"""
Firestore implementation of repository interfaces.
Provides persistence for models, model versions, deployments, replicas, users, and audit logs.
Uses Firestore collections with subcollections and lightweight wrapper dataclasses.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.database.interface import (
    IAuditRepository,
    IDeploymentRepository,
    IModelRepository,
    IUserRepository,
)
from app.services.firebase.firestore import from_firestore_doc, get_db_client, to_firestore_data

logger = logging.getLogger("modelforge.firebase_repo")


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Data Wrapper Classes (Duck-typed to mirror SQLAlchemy models) -----------

@dataclass
class FirebaseModelVersion:
    id: str
    model_id: str
    version: str
    framework: str = "sklearn"
    model_type: str | None = None
    supports_proba: bool = False
    original_filename: str = ""
    stored_filename: str = ""
    file_path: str = ""
    file_size_bytes: int = 0
    status: str = "uploaded"
    is_active: bool = False
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class FirebaseModel:
    id: str
    name: str
    owner_id: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    versions: list[FirebaseModelVersion] = field(default_factory=list)
    deployments: list[Any] = field(default_factory=list)

    @property
    def active_version(self) -> FirebaseModelVersion | None:
        for v in self.versions:
            if v.is_active:
                return v
        return None

    @property
    def current_deployment(self) -> Any | None:
        for d in self.deployments:
            if getattr(d, "status", "") == "running":
                return d
        return None


@dataclass
class FirebaseReplica:
    id: str
    deployment_id: str
    replica_id: str
    status: str = "healthy"
    requests_count: int = 0
    total_latency_ms: float = 0.0
    container_id: str | None = None
    container_port: int | None = None
    endpoint_url: str | None = None
    is_containerized: bool = False
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class FirebaseAutoScalingConfig:
    id: str
    deployment_id: str
    enabled: bool = False
    min_replicas: int = 1
    max_replicas: int = 5
    target_latency_ms: float = 200.0
    target_throughput_rps: float = 50.0
    scale_up_error_rate_percent: float = 10.0
    scale_down_idle_seconds: int = 120
    cooldown_seconds: int = 60
    evaluation_interval_seconds: int = 30
    last_evaluated_at: datetime | None = None
    last_scaled_at: datetime | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)


@dataclass
class FirebaseDeployment:
    id: str
    model_id: str
    model_version_id: str
    version_label: str
    owner_id: str | None = None
    status: str = "deploying"
    endpoint: str | None = None
    replicas: int = 1
    active_replicas: int = 1
    scaling_status: str = "stable"
    is_containerized: bool = False
    error_message: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    model: Any = None
    model_version: Any = None
    replica_instances: list[FirebaseReplica] = field(default_factory=list)
    autoscaling_config: FirebaseAutoScalingConfig | None = None
    scaling_events: list[Any] = field(default_factory=list)


@dataclass
class FirebaseUser:
    id: str
    email: str
    display_name: str
    password_hash: str = ""
    role: str = "VIEWER"
    is_active: bool = True
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)
    last_login_at: datetime | None = None


@dataclass
class FirebaseAuditEvent:
    id: str
    timestamp: datetime = field(default_factory=_utcnow)
    user_id: str | None = None
    user_email: str | None = None
    action: str = ""
    resource_type: str = ""
    resource_id: str | None = None
    details: str | None = None
    ip_address: str | None = None
    success: bool = True


# --- Concrete Firestore Repositories -----------------------------------------

class FirestoreModelRepository(IModelRepository):
    """Firestore repository for logical models and model versions."""

    def __init__(self) -> None:
        self.client = get_db_client()

    def _doc_to_version(self, doc_data: dict[str, Any]) -> FirebaseModelVersion:
        return FirebaseModelVersion(
            id=doc_data.get("id", ""),
            model_id=doc_data.get("model_id", ""),
            version=doc_data.get("version", "v1"),
            framework=doc_data.get("framework", "sklearn"),
            model_type=doc_data.get("model_type"),
            supports_proba=doc_data.get("supports_proba", False),
            original_filename=doc_data.get("original_filename", ""),
            stored_filename=doc_data.get("stored_filename", ""),
            file_path=doc_data.get("file_path", ""),
            file_size_bytes=doc_data.get("file_size_bytes", 0),
            status=doc_data.get("status", "uploaded"),
            is_active=doc_data.get("is_active", False),
            created_at=doc_data.get("created_at") or _utcnow(),
        )

    def _doc_to_model(self, doc_data: dict[str, Any], load_subcollections: bool = True) -> FirebaseModel:
        model = FirebaseModel(
            id=doc_data.get("id", ""),
            name=doc_data.get("name", ""),
            created_at=doc_data.get("created_at") or _utcnow(),
        )
        if load_subcollections and model.id:
            # Load versions from subcollection models/{id}/versions
            v_docs = (
                self.client.collection("models")
                .document(model.id)
                .collection("versions")
                .order_by("created_at")
                .stream()
            )
            model.versions = [self._doc_to_version(from_firestore_doc(v)) for v in v_docs if v.exists]

            # Load deployments for this model
            d_docs = (
                self.client.collection("deployments")
                .where("model_id", "==", model.id)
                .stream()
            )
            deployments = []
            for d in d_docs:
                if d.exists:
                    d_data = from_firestore_doc(d)
                    deployments.append(
                        FirebaseDeployment(
                            id=d_data["id"],
                            model_id=d_data.get("model_id", model.id),
                            model_version_id=d_data.get("model_version_id", ""),
                            version_label=d_data.get("version_label", ""),
                            status=d_data.get("status", "stopped"),
                            endpoint=d_data.get("endpoint"),
                            replicas=d_data.get("replicas", 1),
                            active_replicas=d_data.get("active_replicas", 1),
                            scaling_status=d_data.get("scaling_status", "stable"),
                            is_containerized=d_data.get("is_containerized", False),
                            error_message=d_data.get("error_message"),
                            created_at=d_data.get("created_at") or _utcnow(),
                            updated_at=d_data.get("updated_at") or _utcnow(),
                            model=model,
                        )
                    )
            model.deployments = deployments

        return model

    def list_models(self) -> list[FirebaseModel]:
        docs = self.client.collection("models").order_by("created_at", direction="DESCENDING").stream()
        models = []
        for doc in docs:
            if doc.exists:
                models.append(self._doc_to_model(from_firestore_doc(doc), load_subcollections=True))
        return models

    def get_model(self, model_id: str) -> FirebaseModel | None:
        doc = self.client.collection("models").document(model_id).get()
        if not doc.exists:
            return None
        return self._doc_to_model(from_firestore_doc(doc), load_subcollections=True)

    def get_model_by_name(self, name: str) -> FirebaseModel | None:
        docs = list(self.client.collection("models").where("name", "==", name).limit(1).stream())
        if not docs:
            return None
        return self._doc_to_model(from_firestore_doc(docs[0]), load_subcollections=True)

    def create_model(self, name: str, user_id: str | None = None) -> FirebaseModel:
        model_id = _uuid()
        now = _utcnow()
        doc_data = {
            "name": name,
            "created_at": now,
            "created_by": user_id,
        }
        self.client.collection("models").document(model_id).set(to_firestore_data(doc_data))
        return FirebaseModel(id=model_id, name=name, created_at=now, versions=[], deployments=[])

    def delete_model(self, model_id: str) -> bool:
        doc_ref = self.client.collection("models").document(model_id)
        if not doc_ref.get().exists:
            return False

        # Delete subcollection versions
        for v in doc_ref.collection("versions").stream():
            v.reference.delete()

        # Delete model document
        doc_ref.delete()
        return True

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
    ) -> FirebaseModelVersion:
        version_id = _uuid()
        now = _utcnow()
        v_data = {
            "model_id": model_id,
            "version": version,
            "framework": framework,
            "model_type": model_type,
            "supports_proba": supports_proba,
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "file_path": file_path,
            "file_size_bytes": file_size_bytes,
            "status": status,
            "is_active": is_active,
            "created_at": now,
        }
        (
            self.client.collection("models")
            .document(model_id)
            .collection("versions")
            .document(version_id)
            .set(to_firestore_data(v_data))
        )
        return FirebaseModelVersion(id=version_id, **v_data)

    def get_version(self, model_id: str, version_label: str) -> FirebaseModelVersion | None:
        docs = list(
            self.client.collection("models")
            .document(model_id)
            .collection("versions")
            .where("version", "==", version_label)
            .limit(1)
            .stream()
        )
        if not docs:
            return None
        return self._doc_to_version(from_firestore_doc(docs[0]))

    def get_version_by_id(self, version_id: str) -> FirebaseModelVersion | None:
        # Use collection group to query across versions
        docs = list(self.client.collection_group("versions").where("id", "==", version_id).limit(1).stream())
        if not docs:
            return None
        return self._doc_to_version(from_firestore_doc(docs[0]))

    def delete_version(self, model_id: str, version_label: str) -> bool:
        docs = list(
            self.client.collection("models")
            .document(model_id)
            .collection("versions")
            .where("version", "==", version_label)
            .limit(1)
            .stream()
        )
        if not docs:
            return False
        docs[0].reference.delete()
        return True


class FirestoreDeploymentRepository(IDeploymentRepository):
    """Firestore repository for Deployments, Replicas, and Auto-Scaling configs."""

    def __init__(self) -> None:
        self.client = get_db_client()

    def _doc_to_deployment(self, doc_data: dict[str, Any]) -> FirebaseDeployment:
        dep = FirebaseDeployment(
            id=doc_data.get("id", ""),
            model_id=doc_data.get("model_id", ""),
            model_version_id=doc_data.get("model_version_id", ""),
            version_label=doc_data.get("version_label", ""),
            status=doc_data.get("status", "deploying"),
            endpoint=doc_data.get("endpoint"),
            replicas=doc_data.get("replicas", 1),
            active_replicas=doc_data.get("active_replicas", 1),
            scaling_status=doc_data.get("scaling_status", "stable"),
            is_containerized=doc_data.get("is_containerized", False),
            error_message=doc_data.get("error_message"),
            created_at=doc_data.get("created_at") or _utcnow(),
            updated_at=doc_data.get("updated_at") or _utcnow(),
        )

        # Load model name for schema compatibility
        if dep.model_id:
            m_doc = self.client.collection("models").document(dep.model_id).get()
            if m_doc.exists:
                dep.model = FirebaseModel(id=dep.model_id, name=m_doc.to_dict().get("name", ""))

        # Load replicas
        rep_docs = (
            self.client.collection("deployments")
            .document(dep.id)
            .collection("replicas")
            .order_by("created_at")
            .stream()
        )
        dep.replica_instances = [
            FirebaseReplica(**from_firestore_doc(r)) for r in rep_docs if r.exists
        ]

        # Load autoscaling config
        cfg_doc = (
            self.client.collection("deployments")
            .document(dep.id)
            .collection("autoscaling_config")
            .document("current")
            .get()
        )
        if cfg_doc.exists:
            cfg_dict = from_firestore_doc(cfg_doc)
            dep.autoscaling_config = FirebaseAutoScalingConfig(**cfg_dict)

        return dep

    def list_deployments(self, model_id: str | None = None) -> list[FirebaseDeployment]:
        query = self.client.collection("deployments")
        if model_id:
            query = query.where("model_id", "==", model_id)
        docs = query.order_by("created_at", direction="DESCENDING").stream()
        return [self._doc_to_deployment(from_firestore_doc(d)) for d in docs if d.exists]

    def get_deployment(self, deployment_id: str) -> FirebaseDeployment | None:
        doc = self.client.collection("deployments").document(deployment_id).get()
        if not doc.exists:
            return None
        return self._doc_to_deployment(from_firestore_doc(doc))

    def create_deployment(
        self,
        model_id: str,
        model_version_id: str,
        version_label: str,
        replicas: int = 1,
        endpoint: str | None = None,
        status: str = "deploying",
        is_containerized: bool = False,
    ) -> FirebaseDeployment:
        dep_id = _uuid()
        now = _utcnow()
        doc_data = {
            "model_id": model_id,
            "model_version_id": model_version_id,
            "version_label": version_label,
            "status": status,
            "endpoint": endpoint,
            "replicas": replicas,
            "active_replicas": replicas if status == "running" else 0,
            "scaling_status": "stable",
            "is_containerized": is_containerized,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
        self.client.collection("deployments").document(dep_id).set(to_firestore_data(doc_data))
        doc_data["id"] = dep_id
        return self._doc_to_deployment(doc_data)

    def update_deployment(self, deployment_id: str, **fields: Any) -> FirebaseDeployment | None:
        doc_ref = self.client.collection("deployments").document(deployment_id)
        if not doc_ref.get().exists:
            return None
        fields["updated_at"] = _utcnow()
        doc_ref.update(to_firestore_data(fields))
        return self.get_deployment(deployment_id)

    def delete_deployment(self, deployment_id: str) -> bool:
        doc_ref = self.client.collection("deployments").document(deployment_id)
        if not doc_ref.get().exists:
            return False

        # Delete subcollections
        for r in doc_ref.collection("replicas").stream():
            r.reference.delete()
        for c in doc_ref.collection("autoscaling_config").stream():
            c.reference.delete()

        doc_ref.delete()
        return True

    def list_replicas(self, deployment_id: str) -> list[FirebaseReplica]:
        docs = (
            self.client.collection("deployments")
            .document(deployment_id)
            .collection("replicas")
            .order_by("created_at")
            .stream()
        )
        return [FirebaseReplica(**from_firestore_doc(r)) for r in docs if r.exists]

    def get_autoscaling_config(self, deployment_id: str) -> FirebaseAutoScalingConfig | None:
        doc = (
            self.client.collection("deployments")
            .document(deployment_id)
            .collection("autoscaling_config")
            .document("current")
            .get()
        )
        if not doc.exists:
            return None
        return FirebaseAutoScalingConfig(**from_firestore_doc(doc))

    def save_autoscaling_config(self, deployment_id: str, **fields: Any) -> FirebaseAutoScalingConfig:
        doc_ref = (
            self.client.collection("deployments")
            .document(deployment_id)
            .collection("autoscaling_config")
            .document("current")
        )
        now = _utcnow()
        fields["deployment_id"] = deployment_id
        fields["updated_at"] = now
        existing = doc_ref.get()
        if not existing.exists:
            fields["id"] = _uuid()
            fields["created_at"] = now
            doc_ref.set(to_firestore_data(fields))
        else:
            doc_ref.update(to_firestore_data(fields))
        return FirebaseAutoScalingConfig(**from_firestore_doc(doc_ref.get()))


class FirestoreUserRepository(IUserRepository):
    """Firestore repository for User accounts & RBAC profiles."""

    def __init__(self) -> None:
        self.client = get_db_client()

    def _doc_to_user(self, doc_data: dict[str, Any]) -> FirebaseUser:
        return FirebaseUser(
            id=doc_data.get("id", ""),
            email=doc_data.get("email", ""),
            display_name=doc_data.get("display_name", ""),
            password_hash=doc_data.get("password_hash", ""),  # empty for Firebase Auth users
            role=doc_data.get("role", "VIEWER"),
            is_active=doc_data.get("is_active", True),
            created_at=doc_data.get("created_at") or _utcnow(),
            updated_at=doc_data.get("updated_at") or _utcnow(),
            last_login_at=doc_data.get("last_login_at"),
        )

    def list_users(self) -> list[FirebaseUser]:
        docs = self.client.collection("users").order_by("created_at", direction="DESCENDING").stream()
        return [self._doc_to_user(from_firestore_doc(d)) for d in docs if d.exists]

    def get_user_by_id(self, user_id: str) -> FirebaseUser | None:
        doc = self.client.collection("users").document(user_id).get()
        if not doc.exists:
            return None
        return self._doc_to_user(from_firestore_doc(doc))

    def get_user_by_email(self, email: str) -> FirebaseUser | None:
        clean_email = email.strip().lower()
        docs = list(self.client.collection("users").where("email", "==", clean_email).limit(1).stream())
        if not docs:
            return None
        return self._doc_to_user(from_firestore_doc(docs[0]))

    def create_user(
        self,
        email: str,
        display_name: str,
        role: str = "VIEWER",
        password_hash: str = "",
        is_active: bool = True,
        user_id: str | None = None,
    ) -> FirebaseUser:
        uid = user_id or _uuid()
        now = _utcnow()
        clean_email = email.strip().lower()
        user_data = {
            "email": clean_email,
            "display_name": display_name.strip(),
            "role": role.upper(),
            "is_active": is_active,
            "created_at": now,
            "updated_at": now,
            "last_login_at": None,
        }
        self.client.collection("users").document(uid).set(to_firestore_data(user_data))
        user_data["id"] = uid
        return self._doc_to_user(user_data)

    def update_user(self, user_id: str, **fields: Any) -> FirebaseUser | None:
        doc_ref = self.client.collection("users").document(user_id)
        if not doc_ref.get().exists:
            return None
        fields["updated_at"] = _utcnow()
        if "role" in fields and isinstance(fields["role"], str):
            fields["role"] = fields["role"].upper()
        doc_ref.update(to_firestore_data(fields))
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> bool:
        doc_ref = self.client.collection("users").document(user_id)
        if not doc_ref.get().exists:
            return False
        doc_ref.delete()
        return True

    def count_users(self) -> int:
        docs = list(self.client.collection("users").stream())
        return len(docs)


class FirestoreAuditRepository(IAuditRepository):
    """Firestore repository for immutable audit logs."""

    def __init__(self) -> None:
        self.client = get_db_client()

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
    ) -> FirebaseAuditEvent | None:
        try:
            event_id = _uuid()
            now = _utcnow()
            details_str = json.dumps(details, default=str) if isinstance(details, (dict, list)) else str(details or "")
            event_data = {
                "timestamp": now,
                "user_id": str(user_id) if user_id else None,
                "user_email": str(user_email) if user_email else None,
                "action": action.upper(),
                "resource_type": resource_type,
                "resource_id": str(resource_id) if resource_id else None,
                "details": details_str,
                "ip_address": str(ip_address) if ip_address else None,
                "success": success,
            }
            self.client.collection("audit_events").document(event_id).set(to_firestore_data(event_data))
            event_data["id"] = event_id
            return FirebaseAuditEvent(**event_data)
        except Exception as exc:
            logger.error("Failed to persist Firestore audit event: %s", exc)
            return None

    def query_events(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> tuple[list[FirebaseAuditEvent], int]:
        query = self.client.collection("audit_events")
        if user_id:
            query = query.where("user_id", "==", user_id)
        if action:
            query = query.where("action", "==", action.upper())
        if date_from:
            query = query.where("timestamp", ">=", date_from)
        if date_to:
            query = query.where("timestamp", "<=", date_to)

        docs = list(query.order_by("timestamp", direction="DESCENDING").stream())
        total = len(docs)
        paged = docs[offset : offset + limit]
        items = [FirebaseAuditEvent(**from_firestore_doc(d)) for d in paged if d.exists]
        return items, total

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
