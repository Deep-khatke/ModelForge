"""
Deployment manager endpoints.

Lets a user pick Model -> Version -> Deploy. Creates a Deployment record,
validates the artifact loads, syncs replica instances, and handles dynamic scaling,
replica monitoring, round-robin load testing, and logging.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import (
    get_client_ip,
    get_current_user,
    require_roles,
    verify_resource_ownership,
)
from app.model_inspector import inspect_joblib_model
from app.models import Deployment, InferenceLog, Model, Replica, User
from app.metrics import (
    ACTIVE_DEPLOYMENTS,
    DEPLOYMENTS_TOTAL,
    DEPLOYMENT_FAILURES_TOTAL,
)
from app.replica_manager import (
    cleanup_deployment_containers,
    execute_predict_with_load_balancer,
    sync_deployment_replicas,
)
from app.services.audit_service import log_audit_event
from app.schemas import (
    DeploymentCreate,
    DeploymentOut,
    InferenceLogOut,
    LoadTestRequest,
    LoadTestResponse,
    ReplicaOut,
    ScaleRequest,
    ScaleResponse,
)

router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])


def _to_deployment_out(d: Deployment) -> DeploymentOut:
    return DeploymentOut(
        id=d.id,
        model_id=d.model_id,
        model_name=d.model.name,
        model_version_id=d.model_version_id,
        version_label=d.version_label,
        owner_id=d.owner_id,
        status=d.status,
        endpoint=d.endpoint,
        replicas=d.replicas,
        active_replicas=d.active_replicas,
        scaling_status=d.scaling_status,
        is_containerized=d.is_containerized,
        autoscaling_enabled=bool(d.autoscaling_config and d.autoscaling_config.enabled),
        error_message=d.error_message,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.post("", response_model=DeploymentOut, status_code=status.HTTP_201_CREATED)
def create_deployment(
    payload: DeploymentCreate,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> DeploymentOut:
    model = db.get(Model, payload.model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{payload.model_id}' not found"
        )
    verify_resource_ownership(model.owner_id, current_user, "model")

    if payload.replicas < 1 or payload.replicas > settings.max_replicas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"replicas must be between 1 and {settings.max_replicas}",
        )

    if payload.version:
        target_version = next((v for v in model.versions if v.version == payload.version), None)
        if target_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version '{payload.version}' not found for model '{payload.model_id}'",
            )
    else:
        target_version = model.active_version
        if target_version is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Model has no active version and none was specified",
            )

    for d in model.deployments:
        if d.status == "running":
            cleanup_deployment_containers(db, d)
            d.status = "stopped"

    deployment = Deployment(
        model_id=model.id,
        model_version_id=target_version.id,
        version_label=target_version.version,
        owner_id=current_user.id if current_user else None,
        status="deploying",
        replicas=payload.replicas,
        active_replicas=0,
        scaling_status="scaling",
    )
    db.add(deployment)
    db.flush()

    inspection = inspect_joblib_model(Path(target_version.file_path))
    if inspection.ok:
        deployment.status = "running"
        deployment.endpoint = f"/api/v1/models/{model.id}/predict"
        deployment.error_message = None
        sync_deployment_replicas(db, deployment, target_version)
        DEPLOYMENTS_TOTAL.labels(status="running").inc()
        ACTIVE_DEPLOYMENTS.inc()
    else:
        deployment.status = "failed"
        deployment.endpoint = None
        deployment.error_message = inspection.error
        deployment.active_replicas = 0
        deployment.scaling_status = "failed"
        DEPLOYMENTS_TOTAL.labels(status="failed").inc()
        DEPLOYMENT_FAILURES_TOTAL.labels(model=model.name).inc()

    db.commit()
    db.refresh(deployment)

    log_audit_event(
        db,
        action="DEPLOYMENT_CREATED",
        resource_type="deployment",
        resource_id=deployment.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "model_name": model.name,
            "version": target_version.version,
            "replicas": deployment.replicas,
            "status": deployment.status,
        },
        ip_address=get_client_ip(request),
        success=deployment.status == "running",
    )

    return _to_deployment_out(deployment)


@router.get("", response_model=list[DeploymentOut])
def list_deployments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DeploymentOut]:
    deployments = db.scalars(select(Deployment).order_by(Deployment.created_at.desc())).all()
    return [_to_deployment_out(d) for d in deployments]


@router.get("/{deployment_id}", response_model=DeploymentOut)
def get_deployment(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DeploymentOut:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )
    verify_resource_ownership(deployment.owner_id, current_user, "deployment")
    return _to_deployment_out(deployment)


@router.post("/{deployment_id}/scale", response_model=ScaleResponse)
def scale_deployment(
    deployment_id: str,
    payload: ScaleRequest,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> ScaleResponse:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )
    verify_resource_ownership(deployment.owner_id, current_user, "deployment")

    if deployment.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deployment is '{deployment.status}', not 'running' - cannot scale",
        )

    if payload.replicas < 1 or payload.replicas > settings.max_replicas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"replicas must be between 1 and {settings.max_replicas}",
        )

    target_version = deployment.model_version
    if target_version is None:
        target_version = next(
            (v for v in deployment.model.versions if v.id == deployment.model_version_id), None
        )

    if target_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment model version is invalid",
        )

    prev_replicas = deployment.replicas
    deployment.replicas = payload.replicas
    deployment.scaling_status = "scaling"
    db.commit()

    sync_deployment_replicas(db, deployment, target_version)

    log_audit_event(
        db,
        action="DEPLOYMENT_SCALED",
        resource_type="deployment",
        resource_id=deployment.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "previous_replicas": prev_replicas,
            "requested_replicas": payload.replicas,
            "active_replicas": deployment.active_replicas,
        },
        ip_address=get_client_ip(request),
        success=True,
    )

    return ScaleResponse(
        deployment_id=deployment.id,
        previous_replicas=prev_replicas,
        requested_replicas=deployment.replicas,
        active_replicas=deployment.active_replicas,
        scaling_status=deployment.scaling_status,
        status=deployment.status,
    )


@router.get("/{deployment_id}/replicas", response_model=list[ReplicaOut])
def get_deployment_replicas(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ReplicaOut]:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )

    replicas = list(
        db.scalars(
            select(Replica)
            .where(Replica.deployment_id == deployment_id)
            .order_by(Replica.replica_id)
        ).all()
    )

    result = []
    for r in replicas:
        avg_lat = round(r.total_latency_ms / r.requests_count, 2) if r.requests_count > 0 else 0.0
        result.append(
            ReplicaOut(
                id=r.id,
                deployment_id=r.deployment_id,
                replica_id=r.replica_id,
                status=r.status,
                requests_count=r.requests_count,
                avg_latency_ms=avg_lat,
                container_id=r.container_id,
                container_port=r.container_port,
                endpoint_url=r.endpoint_url,
                is_containerized=r.is_containerized,
            )
        )
    return result


@router.post("/{deployment_id}/load-test", response_model=LoadTestResponse)
def run_load_test(
    deployment_id: str,
    payload: LoadTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LoadTestResponse:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )

    if deployment.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deployment '{deployment_id}' is '{deployment.status}', not 'running'",
        )

    target_version = deployment.model_version
    if target_version is None:
        target_version = next(
            (v for v in deployment.model.versions if v.id == deployment.model_version_id), None
        )

    num_requests = max(1, min(payload.requests, 1000))
    features = payload.features if payload.features is not None else [0.0, 0.0]

    successful = 0
    failed = 0
    total_latency_ms = 0.0
    replica_dist: dict[str, int] = {}
    used_replicas = set()

    start_wall = time.perf_counter()

    for _ in range(num_requests):
        try:
            res = execute_predict_with_load_balancer(
                db, deployment, deployment.model.name, target_version, features
            )
            successful += 1
            total_latency_ms += res.inference_time_ms
            replica_dist[res.replica_id] = replica_dist.get(res.replica_id, 0) + 1
            used_replicas.add(res.replica_id)
        except Exception:
            failed += 1

    total_wall = time.perf_counter() - start_wall
    avg_latency = round(total_latency_ms / successful, 2) if successful > 0 else 0.0
    throughput = round(num_requests / total_wall, 2) if total_wall > 0 else 0.0

    return LoadTestResponse(
        total_requests=num_requests,
        successful_requests=successful,
        failed_requests=failed,
        average_latency_ms=avg_latency,
        throughput_requests_per_second=throughput,
        replicas_used=len(used_replicas),
        replica_distribution=replica_dist,
    )


@router.get("/{deployment_id}/logs", response_model=list[InferenceLogOut])
def get_deployment_logs(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[InferenceLogOut]:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )

    logs = list(
        db.scalars(
            select(InferenceLog)
            .where(InferenceLog.deployment_id == deployment_id)
            .order_by(InferenceLog.timestamp.desc())
            .limit(50)
        ).all()
    )
    return logs


@router.get("/{deployment_id}/health")
def deployment_health(
    deployment_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )
    return {"status": "healthy" if deployment.status == "running" else deployment.status}


@router.post("/{deployment_id}/stop", response_model=DeploymentOut)
def stop_deployment(
    deployment_id: str,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> DeploymentOut:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )
    verify_resource_ownership(deployment.owner_id, current_user, "deployment")
    if deployment.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Deployment is '{deployment.status}', not 'running' - nothing to stop",
        )
    cleanup_deployment_containers(db, deployment)
    deployment.status = "stopped"
    DEPLOYMENTS_TOTAL.labels(status="stopped").inc()
    ACTIVE_DEPLOYMENTS.dec()
    db.commit()
    db.refresh(deployment)

    log_audit_event(
        db,
        action="DEPLOYMENT_STOPPED",
        resource_type="deployment",
        resource_id=deployment.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={"model_name": deployment.model.name, "version": deployment.version_label},
        ip_address=get_client_ip(request),
        success=True,
    )

    return _to_deployment_out(deployment)


@router.delete("/{deployment_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_deployment(
    deployment_id: str,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> None:
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )
    verify_resource_ownership(deployment.owner_id, current_user, "deployment")
    model_name = deployment.model.name if deployment.model else "unknown"
    version_label = deployment.version_label
    cleanup_deployment_containers(db, deployment)
    db.delete(deployment)
    db.commit()

    log_audit_event(
        db,
        action="DEPLOYMENT_DELETED",
        resource_type="deployment",
        resource_id=deployment_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={"model_name": model_name, "version": version_label},
        ip_address=get_client_ip(request),
        success=True,
    )

