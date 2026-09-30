"""
Controlled Performance Benchmark Experiment API endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_roles
from app.models import User
from app.schemas import ExperimentOut, ExperimentRunRequest
from app.services.audit_service import log_audit_event
from app.services.experiment_service import (
    generate_experiments_csv,
    get_experiments_list,
    run_controlled_experiment,
)

router = APIRouter(prefix="/api/v1/experiments", tags=["experiments"])


@router.post("/run", response_model=ExperimentOut, status_code=status.HTTP_201_CREATED)
def run_experiment_endpoint(
    payload: ExperimentRunRequest,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> ExperimentOut:
    """Execute a controlled benchmark experiment across deployment replicas."""
    exp = run_controlled_experiment(
        db, payload.deployment_id, payload.requests, payload.features
    )

    log_audit_event(
        db,
        action="EXPERIMENT_RUN",
        resource_type="deployment",
        resource_id=payload.deployment_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "experiment_id": exp.id,
            "requests_count": payload.requests,
            "failed_requests": exp.failed_requests,
            "successful_requests": exp.successful_requests,
        },
        ip_address=get_client_ip(request),
        success=(exp.failed_requests == 0),
    )

    return exp


@router.get("", response_model=list[ExperimentOut])
def list_experiments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ExperimentOut]:
    """Retrieve all past experiment benchmark records."""
    return get_experiments_list(db)


@router.get("/export")
def export_experiments_csv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Export all recorded experiment comparison benchmarks as a CSV file."""
    experiments = get_experiments_list(db)
    csv_data = generate_experiments_csv(experiments)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelforge_experiment_benchmarks.csv"},
    )
