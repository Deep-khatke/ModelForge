"""
ModelForge SQLite -> Firestore Migration Script (Phase 8.5).

Safely and idempotently migrates existing SQLite records into Firestore:
- Users (profile & role metadata; passwords handled by Firebase Auth)
- Models & ModelVersions (subcollections under models/{id}/versions)
- Deployments, Replicas & AutoScalingConfigs
- Audit Events

Features:
- Idempotent: checks document existence before writing unless --overwrite is passed.
- Preserves all unique primary key IDs, foreign key references, and UTC timestamps.
- Preserves SQLite database (never deletes or modifies SQLite source data).
- Supports --dry-run mode for safe preview.
- Detailed progress and error summary reporting.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path so app imports work
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import (
    AuditEvent,
    AutoScalingConfig,
    Deployment,
    Model,
    ModelVersion,
    Replica,
    ScalingEvent,
    User,
)
from app.services.firebase.client import get_firebase_status, get_firestore_client, initialize_firebase
from app.services.firebase.firestore import to_firestore_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("modelforge.migration")


class MigrationStats:
    def __init__(self) -> None:
        self.processed = 0
        self.created = 0
        self.skipped = 0
        self.failed = 0
        self.details: dict[str, dict[str, int]] = {}

    def record(self, entity_type: str, status: str) -> None:
        self.processed += 1
        if status == "created":
            self.created += 1
        elif status == "skipped":
            self.skipped += 1
        elif status == "failed":
            self.failed += 1

        if entity_type not in self.details:
            self.details[entity_type] = {"created": 0, "skipped": 0, "failed": 0}
        self.details[entity_type][status] += 1

    def print_summary(self, dry_run: bool) -> None:
        mode_str = "DRY RUN COMPLETE (No Firestore changes written)" if dry_run else "MIGRATION COMPLETE"
        print("\n" + "=" * 60)
        print(f"  {mode_str}")
        print("=" * 60)
        print(f"Total records processed: {self.processed}")
        print(f"Successfully migrated:   {self.created}")
        print(f"Skipped (already exist): {self.skipped}")
        print(f"Failed / Errors:         {self.failed}")
        print("-" * 60)
        print("Breakdown by entity:")
        for entity, counts in self.details.items():
            print(f"  * {entity:20s}: created={counts['created']:<4d} skipped={counts['skipped']:<4d} failed={counts['failed']:<4d}")
        print("=" * 60 + "\n")


def migrate(
    sqlite_url: str | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> int:
    """Executes SQLite to Firestore migration."""
    print("=" * 60)
    print("  ModelForge Phase 8.5: SQLite -> Firebase Migration")
    print("=" * 60)

    # 1. Initialize Firestore client
    db_url = sqlite_url or settings.database_url
    logger.info("Source SQLite Database: %s", db_url)
    logger.info("Mode: %s", "DRY-RUN (Preview)" if dry_run else "LIVE WRITE")

    if not dry_run:
        if not initialize_firebase():
            status = get_firebase_status()
            logger.error(
                "Cannot connect to Firebase: %s. Please check GOOGLE_APPLICATION_CREDENTIALS "
                "and FIREBASE_PROJECT_ID environment variables.",
                status.get("error"),
            )
            return 1
        firestore_client = get_firestore_client()
    else:
        firestore_client = None

    # 2. Connect to SQLite
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    engine = create_engine(db_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()

    stats = MigrationStats()

    try:
        # -------------------------------------------------------------
        # 1. Migrate Users
        # -------------------------------------------------------------
        users = list(session.scalars(select(User)).all())
        logger.info("Found %d user records in SQLite.", len(users))
        for u in users:
            try:
                doc_ref = firestore_client.collection("users").document(u.id) if firestore_client else None
                if not overwrite and doc_ref and doc_ref.get().exists:
                    logger.debug("User '%s' (%s) already exists in Firestore. Skipping.", u.email, u.id)
                    stats.record("Users", "skipped")
                    continue

                user_data = {
                    "id": u.id,
                    "email": u.email,
                    "display_name": u.display_name,
                    "role": u.role,
                    "is_active": u.is_active,
                    "created_at": u.created_at,
                    "updated_at": u.updated_at,
                    "last_login_at": u.last_login_at,
                }

                if not dry_run and doc_ref:
                    doc_ref.set(to_firestore_data(user_data))
                logger.info("Migrated user: %s (role: %s)", u.email, u.role)
                stats.record("Users", "created")
            except Exception as exc:
                logger.error("Failed to migrate user '%s': %s", u.email, exc)
                stats.record("Users", "failed")

        # -------------------------------------------------------------
        # 2. Migrate Models and Model Versions
        # -------------------------------------------------------------
        models = list(session.scalars(select(Model)).all())
        logger.info("Found %d model records in SQLite.", len(models))
        for m in models:
            try:
                m_ref = firestore_client.collection("models").document(m.id) if firestore_client else None
                if not overwrite and m_ref and m_ref.get().exists:
                    logger.debug("Model '%s' (%s) already exists. Checking versions.", m.name, m.id)
                    stats.record("Models", "skipped")
                else:
                    m_data = {
                        "id": m.id,
                        "name": m.name,
                        "created_at": m.created_at,
                    }
                    if not dry_run and m_ref:
                        m_ref.set(to_firestore_data(m_data))
                    logger.info("Migrated model: %s (%s)", m.name, m.id)
                    stats.record("Models", "created")

                # Migrate subcollection versions: models/{m.id}/versions/{v.id}
                for v in m.versions:
                    v_ref = (
                        firestore_client.collection("models")
                        .document(m.id)
                        .collection("versions")
                        .document(v.id)
                        if firestore_client
                        else None
                    )
                    if not overwrite and v_ref and v_ref.get().exists:
                        stats.record("ModelVersions", "skipped")
                        continue

                    v_data = {
                        "id": v.id,
                        "model_id": v.model_id,
                        "version": v.version,
                        "framework": v.framework,
                        "model_type": v.model_type,
                        "supports_proba": v.supports_proba,
                        "original_filename": v.original_filename,
                        "stored_filename": v.stored_filename,
                        "file_path": v.file_path,
                        "file_size_bytes": v.file_size_bytes,
                        "status": v.status,
                        "is_active": v.is_active,
                        "created_at": v.created_at,
                    }
                    if not dry_run and v_ref:
                        v_ref.set(to_firestore_data(v_data))
                    logger.info("  -> Migrated version %s for model '%s'", v.version, m.name)
                    stats.record("ModelVersions", "created")

            except Exception as exc:
                logger.error("Failed to migrate model '%s': %s", m.name, exc)
                stats.record("Models", "failed")

        # -------------------------------------------------------------
        # 3. Migrate Deployments, Replicas, AutoScalingConfig
        # -------------------------------------------------------------
        deployments = list(session.scalars(select(Deployment)).all())
        logger.info("Found %d deployment records in SQLite.", len(deployments))
        for d in deployments:
            try:
                d_ref = firestore_client.collection("deployments").document(d.id) if firestore_client else None
                if not overwrite and d_ref and d_ref.get().exists:
                    stats.record("Deployments", "skipped")
                else:
                    d_data = {
                        "id": d.id,
                        "model_id": d.model_id,
                        "model_version_id": d.model_version_id,
                        "version_label": d.version_label,
                        "status": d.status,
                        "endpoint": d.endpoint,
                        "replicas": d.replicas,
                        "active_replicas": d.active_replicas,
                        "scaling_status": d.scaling_status,
                        "is_containerized": d.is_containerized,
                        "error_message": d.error_message,
                        "created_at": d.created_at,
                        "updated_at": d.updated_at,
                    }
                    if not dry_run and d_ref:
                        d_ref.set(to_firestore_data(d_data))
                    logger.info("Migrated deployment: %s (%s)", d.id, d.version_label)
                    stats.record("Deployments", "created")

                # Replicas subcollection: deployments/{d.id}/replicas/{rep.id}
                for r in d.replica_instances:
                    r_ref = (
                        firestore_client.collection("deployments")
                        .document(d.id)
                        .collection("replicas")
                        .document(r.id)
                        if firestore_client
                        else None
                    )
                    if not overwrite and r_ref and r_ref.get().exists:
                        stats.record("Replicas", "skipped")
                        continue

                    r_data = {
                        "id": r.id,
                        "deployment_id": r.deployment_id,
                        "replica_id": r.replica_id,
                        "status": r.status,
                        "requests_count": r.requests_count,
                        "total_latency_ms": r.total_latency_ms,
                        "container_id": r.container_id,
                        "container_port": r.container_port,
                        "endpoint_url": r.endpoint_url,
                        "is_containerized": r.is_containerized,
                        "created_at": r.created_at,
                        "updated_at": r.updated_at,
                    }
                    if not dry_run and r_ref:
                        r_ref.set(to_firestore_data(r_data))
                    stats.record("Replicas", "created")

                # AutoScaling config: deployments/{d.id}/autoscaling_config/current
                if d.autoscaling_config:
                    cfg = d.autoscaling_config
                    cfg_ref = (
                        firestore_client.collection("deployments")
                        .document(d.id)
                        .collection("autoscaling_config")
                        .document("current")
                        if firestore_client
                        else None
                    )
                    if not overwrite and cfg_ref and cfg_ref.get().exists:
                        stats.record("AutoScalingConfig", "skipped")
                    else:
                        cfg_data = {
                            "id": cfg.id,
                            "deployment_id": cfg.deployment_id,
                            "enabled": cfg.enabled,
                            "min_replicas": cfg.min_replicas,
                            "max_replicas": cfg.max_replicas,
                            "target_latency_ms": cfg.target_latency_ms,
                            "target_throughput_rps": cfg.target_throughput_rps,
                            "scale_up_error_rate_percent": cfg.scale_up_error_rate_percent,
                            "scale_down_idle_seconds": cfg.scale_down_idle_seconds,
                            "cooldown_seconds": cfg.cooldown_seconds,
                            "evaluation_interval_seconds": cfg.evaluation_interval_seconds,
                            "last_evaluated_at": cfg.last_evaluated_at,
                            "last_scaled_at": cfg.last_scaled_at,
                            "created_at": cfg.created_at,
                            "updated_at": cfg.updated_at,
                        }
                        if not dry_run and cfg_ref:
                            cfg_ref.set(to_firestore_data(cfg_data))
                        stats.record("AutoScalingConfig", "created")

            except Exception as exc:
                logger.error("Failed to migrate deployment '%s': %s", d.id, exc)
                stats.record("Deployments", "failed")

        # -------------------------------------------------------------
        # 4. Migrate Audit Events
        # -------------------------------------------------------------
        audits = list(session.scalars(select(AuditEvent)).all())
        logger.info("Found %d audit events in SQLite.", len(audits))
        for a in audits:
            try:
                a_ref = firestore_client.collection("audit_events").document(a.id) if firestore_client else None
                if not overwrite and a_ref and a_ref.get().exists:
                    stats.record("AuditEvents", "skipped")
                    continue

                a_data = {
                    "id": a.id,
                    "timestamp": a.timestamp,
                    "user_id": a.user_id,
                    "user_email": a.user_email,
                    "action": a.action,
                    "resource_type": a.resource_type,
                    "resource_id": a.resource_id,
                    "details": a.details,
                    "ip_address": a.ip_address,
                    "success": a.success,
                }
                if not dry_run and a_ref:
                    a_ref.set(to_firestore_data(a_data))
                stats.record("AuditEvents", "created")
            except Exception as exc:
                logger.error("Failed to migrate audit event '%s': %s", a.id, exc)
                stats.record("AuditEvents", "failed")

    finally:
        session.close()

    stats.print_summary(dry_run)
    return 0 if stats.failed == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate ModelForge SQLite database to Firestore.")
    parser.add_argument("--sqlite-url", type=str, default=None, help="SQLite connection URL (defaults to DATABASE_URL)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate migration without writing to Firestore")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing Firestore documents")
    args = parser.parse_args()

    exit_code = migrate(sqlite_url=args.sqlite_url, dry_run=args.dry_run, overwrite=args.overwrite)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
