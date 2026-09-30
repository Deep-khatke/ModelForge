"""
Monitoring & Telemetry API endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import InferenceLog, User
from app.schemas import (
    AlertOut,
    DeploymentMetricsOut,
    ModelMetricsOut,
    MonitoringSummaryOut,
    RecentInferencesPage,
    ReplicaMetricsOut,
    SystemMetricsOut,
    TimeSeriesPoint,
)
from app.services.monitoring_service import (
    evaluate_active_alerts,
    generate_monitoring_csv,
    get_deployment_metrics,
    get_all_deployment_metrics,
    get_model_metrics,
    get_recent_inferences,
    get_replica_metrics,
    get_monitoring_summary,
    get_system_resources,
    get_time_series,
    parse_time_range,
)

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("/summary", response_model=MonitoringSummaryOut)
def monitoring_summary(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MonitoringSummaryOut:
    return get_monitoring_summary(db, range)


@router.get("/deployments/{deployment_id}", response_model=DeploymentMetricsOut)
def deployment_metrics(
    deployment_id: str,
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeploymentMetricsOut:
    return get_deployment_metrics(db, deployment_id, range)


@router.get("/deployments", response_model=list[DeploymentMetricsOut])
def all_deployment_metrics(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeploymentMetricsOut]:
    return get_all_deployment_metrics(db, range)


@router.get("/deployments/{deployment_id}/replicas", response_model=list[ReplicaMetricsOut])
def deployment_replica_metrics(
    deployment_id: str,
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReplicaMetricsOut]:
    return get_replica_metrics(db, deployment_id, range)


@router.get("/models/{model_id}", response_model=ModelMetricsOut)
def model_metrics(
    model_id: str,
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelMetricsOut:
    return get_model_metrics(db, model_id, range)


@router.get("/timeseries", response_model=list[TimeSeriesPoint])
def timeseries_metrics(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    deployment_id: str | None = Query(None, description="Optional deployment_id filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TimeSeriesPoint]:
    return get_time_series(db, range, deployment_id)


@router.get("/requests/recent", response_model=RecentInferencesPage)
def recent_inference_requests(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    deployment_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RecentInferencesPage:
    return get_recent_inferences(db, range, deployment_id, limit, offset)


@router.get("/system", response_model=SystemMetricsOut)
def system_metrics(
    current_user: User = Depends(get_current_user),
) -> SystemMetricsOut:
    return get_system_resources()


@router.get("/alerts", response_model=list[AlertOut])
def monitoring_alerts(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[AlertOut]:
    return evaluate_active_alerts(db, range)


@router.get("/export")
def export_monitoring_csv(
    range: str = Query("1h", description="Time range ('5m', '15m', '1h', '6h', '24h', 'all')"),
    deployment_id: str | None = Query(None, description="Optional deployment_id filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    start_time = parse_time_range(range)
    query = select(InferenceLog)
    if deployment_id:
        query = query.where(InferenceLog.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)

    logs = list(db.scalars(query.order_by(InferenceLog.timestamp.desc())).all())
    csv_data = generate_monitoring_csv(logs)

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=modelforge_monitoring_telemetry.csv"},
    )
