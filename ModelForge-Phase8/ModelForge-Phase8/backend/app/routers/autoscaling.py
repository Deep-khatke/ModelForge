"""
Auto-Scaling API endpoints.

Provides endpoints to view/update per-deployment auto-scaling configurations,
trigger evaluations on demand, and query historical scaling decision records.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_client_ip, get_current_user, require_roles
from app.models import Deployment, ScalingEvent, User
from app.replica_manager import sync_deployment_replicas
from app.schemas import (
    AutoScalingConfigOut,
    AutoScalingConfigUpdate,
    AutoScalingEvaluationResult,
    ScalingEventOut,
)
from app.services.audit_service import log_audit_event
from app.services.autoscaling_service import (
    evaluate_all_enabled_deployments,
    evaluate_deployment_autoscaling,
    get_or_create_autoscaling_config,
    to_config_out,
    validate_autoscaling_update,
)

router = APIRouter(tags=["autoscaling"])


@router.get(
    "/api/v1/deployments/{deployment_id}/autoscaling",
    response_model=AutoScalingConfigOut,
)
def get_deployment_autoscaling_config(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AutoScalingConfigOut:
    """Retrieve auto-scaling configuration for a deployment."""
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{deployment_id}' not found",
        )

    cfg = get_or_create_autoscaling_config(db, deployment.id)
    db.commit()
    return to_config_out(cfg)


@router.put(
    "/api/v1/deployments/{deployment_id}/autoscaling",
    response_model=AutoScalingConfigOut,
)
def update_deployment_autoscaling_config(
    deployment_id: str,
    payload: AutoScalingConfigUpdate,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> AutoScalingConfigOut:
    """Update auto-scaling configuration and threshold parameters."""
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{deployment_id}' not found",
        )

    cfg = get_or_create_autoscaling_config(db, deployment.id)
    validate_autoscaling_update(cfg, payload)

    if payload.enabled is not None:
        cfg.enabled = payload.enabled
    if payload.min_replicas is not None:
        cfg.min_replicas = payload.min_replicas
    if payload.max_replicas is not None:
        cfg.max_replicas = payload.max_replicas
    if payload.target_latency_ms is not None:
        cfg.target_latency_ms = payload.target_latency_ms
    if payload.target_throughput_rps is not None:
        cfg.target_throughput_rps = payload.target_throughput_rps
    if payload.scale_up_error_rate_percent is not None:
        cfg.scale_up_error_rate_percent = payload.scale_up_error_rate_percent
    if payload.scale_down_idle_seconds is not None:
        cfg.scale_down_idle_seconds = payload.scale_down_idle_seconds
    if payload.cooldown_seconds is not None:
        cfg.cooldown_seconds = payload.cooldown_seconds
    if payload.evaluation_interval_seconds is not None:
        cfg.evaluation_interval_seconds = payload.evaluation_interval_seconds

    # If replicas are outside the new bounds, adjust immediately if deployment is running
    if deployment.status == "running" and cfg.enabled:
        target_reps = None
        if deployment.replicas < cfg.min_replicas:
            target_reps = cfg.min_replicas
        elif deployment.replicas > cfg.max_replicas:
            target_reps = cfg.max_replicas

        if target_reps is not None:
            deployment.replicas = target_reps
            deployment.scaling_status = "scaling"
            db.commit()
            target_version = deployment.model_version
            if target_version is None:
                target_version = next(
                    (v for v in deployment.model.versions if v.id == deployment.model_version_id), None
                )
            sync_deployment_replicas(db, deployment, target_version)

    db.commit()
    db.refresh(cfg)

    log_audit_event(
        db,
        action="AUTOSCALING_CONFIG_UPDATED",
        resource_type="deployment",
        resource_id=deployment.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "deployment_id": deployment.id,
            "model_id": deployment.model_id,
            "enabled": cfg.enabled,
            "min_replicas": cfg.min_replicas,
            "max_replicas": cfg.max_replicas,
            "target_latency_ms": cfg.target_latency_ms,
            "target_throughput_rps": cfg.target_throughput_rps,
        },
        ip_address=get_client_ip(request),
        success=True,
    )

    return to_config_out(cfg)


@router.post(
    "/api/v1/deployments/{deployment_id}/autoscaling/evaluate",
    response_model=AutoScalingEvaluationResult,
)
def trigger_deployment_autoscaling_evaluation(
    deployment_id: str,
    force: bool = False,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> AutoScalingEvaluationResult:
    """Manually evaluate auto-scaling criteria for a single deployment right now."""
    return evaluate_deployment_autoscaling(db, deployment_id, force=force)


@router.get(
    "/api/v1/deployments/{deployment_id}/scaling-events",
    response_model=list[ScalingEventOut],
)
def get_deployment_scaling_events(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ScalingEventOut]:
    """Retrieve historical scaling decision records for a deployment."""
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{deployment_id}' not found",
        )

    events = list(
        db.scalars(
            select(ScalingEvent)
            .where(ScalingEvent.deployment_id == deployment_id)
            .order_by(ScalingEvent.timestamp.desc())
            .limit(100)
        ).all()
    )

    return [
        ScalingEventOut(
            id=e.id,
            event_id=e.id,
            timestamp=e.timestamp,
            deployment_id=e.deployment_id,
            previous_replicas=e.previous_replicas,
            target_replicas=e.target_replicas,
            action=e.action,
            trigger_reason=e.trigger_reason,
            observed_p95_latency_ms=e.observed_p95_latency_ms,
            observed_throughput_rps=e.observed_throughput_rps,
            observed_error_rate_percent=e.observed_error_rate_percent,
            success=e.success,
            error_message=e.error_message,
        )
        for e in events
    ]


@router.post(
    "/api/v1/autoscaling/evaluate",
    response_model=list[AutoScalingEvaluationResult],
)
def trigger_system_autoscaling_evaluation(
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> list[AutoScalingEvaluationResult]:
    """System-wide trigger to evaluate all active deployments with auto-scaling enabled."""
    return evaluate_all_enabled_deployments(db)
