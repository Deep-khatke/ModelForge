"""
Audit log router (ADMIN only): paginated event queries and CSV export.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_roles
from app.models import User
from app.schemas import AuditEventOut, AuditEventsPage
from app.services.audit_service import export_audit_events_csv, get_audit_events

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("/events", response_model=AuditEventsPage)
def list_audit_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> AuditEventsPage:
    """Retrieve paged audit events with optional filtering (ADMIN only)."""
    items, total = get_audit_events(
        db,
        limit=limit,
        offset=offset,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    return AuditEventsPage(
        items=[AuditEventOut.model_validate(e) for e in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/export")
def export_audit_events(
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Export audit events as a downloadable CSV file (ADMIN only)."""
    csv_content = export_audit_events_csv(
        db,
        user_id=user_id,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )
    filename = f"modelforge_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
