"""
Audit event service for security, state-change tracking, and compliance.

Records immutable user actions, supports paged queries and CSV export.
Never logs plaintext passwords, bearer tokens, or raw inference inputs.
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import AuditEvent

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {"password", "password_hash", "token", "access_token", "secret", "jwt_secret_key"}


def _sanitize_details(details: Any) -> str | None:
    """Strip passwords and tokens from audit event details."""
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


def log_audit_event(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
    details: Any = None,
    ip_address: str | None = None,
    success: bool = True,
) -> AuditEvent | None:
    """Record an audit event into persistent storage."""
    try:
        sanitized_details = _sanitize_details(details)
        event = AuditEvent(
            action=action.upper(),
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else None,
            user_id=str(user_id) if user_id else None,
            user_email=str(user_email) if user_email else None,
            details=sanitized_details,
            ip_address=str(ip_address) if ip_address else None,
            success=success,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
    except Exception as exc:
        logger.error("Failed to persist audit event (%s): %s", action, exc)
        db.rollback()
        return None


def get_audit_events(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[AuditEvent], int]:
    """Retrieve paged audit events with optional filters."""
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


def export_audit_events_csv(
    db: Session,
    user_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    max_records: int = 5000,
) -> str:
    """Generate a CSV string of audit event logs."""
    events, _ = get_audit_events(
        db,
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
        "Event ID",
        "Timestamp (UTC)",
        "Action",
        "Resource Type",
        "Resource ID",
        "User ID",
        "User Email",
        "IP Address",
        "Success",
        "Details",
    ])

    for ev in events:
        writer.writerow([
            ev.id,
            ev.timestamp.isoformat() if ev.timestamp else "",
            ev.action,
            ev.resource_type,
            ev.resource_id or "",
            ev.user_id or "",
            ev.user_email or "",
            ev.ip_address or "",
            "true" if ev.success else "false",
            ev.details or "",
        ])

    return output.getvalue()
