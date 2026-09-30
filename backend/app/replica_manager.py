"""
Replica Manager & Round-Robin Load Balancer.

Manages independent inference replica instances for deployments, performs health
checks, routes inference traffic using Round-Robin load balancing across healthy
replicas, and records telemetry logs for benchmarking.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.container_engine import container_manager
from app.metrics import (
    INFERENCE_ERRORS_TOTAL,
    INFERENCE_LATENCY_SECONDS,
    INFERENCE_REQUESTS_TOTAL,
)
from app.models import Deployment, InferenceLog, ModelVersion, Replica, ReplicaHealthEvent
from app.schemas import PredictResponse
from app.services.storage.factory import get_artifact_store

logger = logging.getLogger("modelforge.replica_manager")

# Global round-robin index pointer tracking per deployment_id
_rr_counters: dict[str, int] = {}


def sync_deployment_replicas(db: Session, deployment: Deployment, target_version: ModelVersion) -> None:
    """
    Sync replica database instances to match deployment.replicas count,
    spin up or tear down Docker containers (if Docker is available),
    or verify model artifacts in-process (fallback mode), and update active_replicas & scaling_status.
    """
    requested = max(1, min(deployment.replicas, settings.max_replicas))
    existing_replicas = list(
        db.scalars(
            select(Replica)
            .where(Replica.deployment_id == deployment.id)
            .order_by(Replica.created_at)
        ).all()
    )
    new_replica_ids: set[str] = set()
    use_docker = container_manager.is_available()

    # 1. Scale UP if needed
    if len(existing_replicas) < requested:
        for i in range(len(existing_replicas) + 1, requested + 1):
            replica_label = f"replica_{i}"
            container_meta = None
            if use_docker:
                try:
                    container_meta = container_manager.start_replica_container(
                        deployment_id=deployment.id,
                        replica_id=replica_label,
                        model_id=deployment.model_id,
                        version_label=deployment.version_label,
                        file_path=target_version.file_path,
                    )
                except Exception as exc:
                    logger.error("Failed to start container for %s: %s", replica_label, exc)
                    container_meta = {
                        "container_id": None,
                        "container_port": None,
                        "endpoint_url": None,
                        "status": "unhealthy",
                    }

            rep = Replica(
                deployment_id=deployment.id,
                replica_id=replica_label,
                status=container_meta["status"] if container_meta else "healthy",
                container_id=container_meta["container_id"] if container_meta else None,
                container_port=container_meta["container_port"] if container_meta else None,
                endpoint_url=container_meta["endpoint_url"] if container_meta else None,
                is_containerized=bool(use_docker and container_meta and container_meta.get("container_id")),
            )
            db.add(rep)
            existing_replicas.append(rep)
            new_replica_ids.add(rep.replica_id)
        db.flush()

    # 2. Scale DOWN if needed
    elif len(existing_replicas) > requested:
        to_remove = existing_replicas[requested:]
        for rep in to_remove:
            if rep.is_containerized and rep.container_id:
                container_manager.stop_replica_container(rep.container_id)
            db.delete(rep)
        existing_replicas = existing_replicas[:requested]
        db.flush()

    # 3. Verify health of each replica
    healthy_count = 0
    store = get_artifact_store()
    artifact_exists = store.model_exists(target_version.file_path)

    for rep in existing_replicas:
        previous_status = rep.status
        if rep.is_containerized and rep.endpoint_url:
            is_healthy = container_manager.check_replica_health(
                rep.endpoint_url, timeout=settings.container_healthcheck_timeout_sec
            )
            rep.status = "healthy" if is_healthy else "unhealthy"
            if is_healthy:
                healthy_count += 1
        else:
            # Fallback mode (no container)
            if artifact_exists:
                try:
                    m = store.load_model(target_version.file_path)
                    if hasattr(m, "predict"):
                        rep.status = "healthy"
                        healthy_count += 1
                    else:
                        rep.status = "unhealthy"
                except Exception:
                    rep.status = "unhealthy"
            else:
                rep.status = "unhealthy"

        if rep.status != previous_status or rep.replica_id in new_replica_ids:
            db.add(
                ReplicaHealthEvent(
                    deployment_id=deployment.id,
                    replica_id=rep.replica_id,
                    status=rep.status,
                )
            )

    deployment.replicas = requested
    deployment.active_replicas = healthy_count
    deployment.is_containerized = bool(use_docker and any(r.is_containerized for r in existing_replicas))

    if healthy_count == requested:
        deployment.scaling_status = "stable"
        deployment.status = "running"
    elif healthy_count > 0:
        deployment.scaling_status = "degraded"
        deployment.status = "running"
    else:
        deployment.scaling_status = "failed"
        deployment.status = "failed"
        deployment.error_message = "No healthy model replicas available"

    db.commit()


def cleanup_deployment_containers(db: Session, deployment: Deployment) -> None:
    """Stop and remove all replica containers for a deployment."""
    for rep in deployment.replica_instances:
        if rep.is_containerized and rep.container_id:
            container_manager.stop_replica_container(rep.container_id)
            rep.container_id = None
            rep.endpoint_url = None
            rep.status = "stopped"
    container_manager.stop_deployment_containers(deployment.id)
    deployment.active_replicas = 0
    db.commit()


def get_next_healthy_replica(db: Session, deployment_id: str) -> Replica:
    """
    Select next healthy replica using Round-Robin load balancing.
    """
    replicas = list(
        db.scalars(
            select(Replica)
            .where(Replica.deployment_id == deployment_id)
            .order_by(Replica.replica_id)
        ).all()
    )

    healthy_replicas = [r for r in replicas if r.status == "healthy"]
    if not healthy_replicas:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No healthy inference replicas available for deployment '{deployment_id}'",
        )

    rr_idx = _rr_counters.get(deployment_id, 0)
    selected = healthy_replicas[rr_idx % len(healthy_replicas)]
    _rr_counters[deployment_id] = rr_idx + 1

    return selected


def execute_predict_with_load_balancer(
    db: Session,
    deployment: Deployment,
    model_name: str,
    target_version: ModelVersion,
    features: list[Any],
    request_id: str | None = None,
) -> PredictResponse:
    """
    Route an inference request through Round-Robin load balancer across healthy replicas,
    collecting Prometheus inference metrics and propagating request_id.
    """
    if not features:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features array cannot be empty",
        )

    try:
        X = np.array(features)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid features array: {exc}",
        )

    if X.size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features array cannot be empty",
        )

    if X.ndim == 1:
        X = X.reshape(1, -1)
    elif X.ndim > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features must be a 1D or 2D numerical array",
        )

    # 1. Round-Robin select replica
    replica = get_next_healthy_replica(db, deployment.id)

    # 2. If replica is containerized, route via container HTTP endpoint
    if replica.is_containerized and replica.endpoint_url:
        start_time = time.perf_counter()
        try:
            container_resp = container_manager.predict_container(
                replica.endpoint_url, features, request_id=request_id
            )
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            inf_time = container_resp.get("inference_time_ms", round(elapsed_ms, 3))
            predictions = container_resp.get("predictions", [])
            probabilities = container_resp.get("probabilities")

            replica.requests_count += 1
            replica.total_latency_ms += round(inf_time, 3)

            # Record Prometheus inference metrics
            INFERENCE_REQUESTS_TOTAL.labels(
                model=deployment.model_id, deployment=deployment.id, status="success"
            ).inc()
            INFERENCE_LATENCY_SECONDS.labels(
                model=deployment.model_id, deployment=deployment.id
            ).observe(inf_time / 1000.0)

            log_entry = InferenceLog(
                deployment_id=deployment.id,
                model_id=deployment.model_id,
                model_version=deployment.version_label,
                replica_id=replica.replica_id,
                latency_ms=round(inf_time, 3),
                status="success",
            )
            db.add(log_entry)
            db.commit()

            return PredictResponse(
                model_id=deployment.model_id,
                model_name=model_name,
                deployment_id=deployment.id,
                version=deployment.version_label,
                replica_id=replica.replica_id,
                predictions=predictions,
                probabilities=probabilities,
                inference_time_ms=round(inf_time, 3),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            INFERENCE_REQUESTS_TOTAL.labels(
                model=deployment.model_id, deployment=deployment.id, status="error"
            ).inc()
            INFERENCE_ERRORS_TOTAL.labels(
                model=deployment.model_id,
                deployment=deployment.id,
                error_type=type(exc).__name__,
            ).inc()

            log_entry = InferenceLog(
                deployment_id=deployment.id,
                model_id=deployment.model_id,
                model_version=deployment.version_label,
                replica_id=replica.replica_id,
                latency_ms=round(elapsed_ms, 3),
                status="failed",
                error_message=str(exc),
            )
            db.add(log_entry)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Container replica inference error: {exc}",
            )

    # 3. Fallback: Load model artifact & predict in-process
    store = get_artifact_store()
    try:
        loaded_model = store.load_model(target_version.file_path)
    except Exception as exc:
        INFERENCE_REQUESTS_TOTAL.labels(
            model=deployment.model_id, deployment=deployment.id, status="error"
        ).inc()
        INFERENCE_ERRORS_TOTAL.labels(
            model=deployment.model_id, deployment=deployment.id, error_type="ModelLoadError"
        ).inc()
        log_entry = InferenceLog(
            deployment_id=deployment.id,
            model_id=deployment.model_id,
            model_version=deployment.version_label,
            replica_id=replica.replica_id,
            latency_ms=0.0,
            status="failed",
            error_message=str(exc),
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load model artifact: {exc}",
        )

    start_time = time.perf_counter()
    try:
        raw_predictions = loaded_model.predict(X)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        INFERENCE_REQUESTS_TOTAL.labels(
            model=deployment.model_id, deployment=deployment.id, status="error"
        ).inc()
        INFERENCE_ERRORS_TOTAL.labels(
            model=deployment.model_id, deployment=deployment.id, error_type=type(exc).__name__
        ).inc()
        log_entry = InferenceLog(
            deployment_id=deployment.id,
            model_id=deployment.model_id,
            model_version=deployment.version_label,
            replica_id=replica.replica_id,
            latency_ms=round(elapsed_ms, 3),
            status="failed",
            error_message=str(exc),
        )
        db.add(log_entry)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Prediction failed: {exc}",
        )

    probabilities = None
    if target_version.supports_proba or (
        hasattr(loaded_model, "predict_proba") and callable(getattr(loaded_model, "predict_proba"))
    ):
        try:
            raw_proba = loaded_model.predict_proba(X)
            if raw_proba is not None:
                probabilities = raw_proba.tolist()
        except Exception:
            probabilities = None

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    predictions = (
        raw_predictions.tolist() if hasattr(raw_predictions, "tolist") else list(raw_predictions)
    )

    # 3. Update replica counters and record inference log
    replica.requests_count += 1
    replica.total_latency_ms += round(elapsed_ms, 3)

    INFERENCE_REQUESTS_TOTAL.labels(
        model=deployment.model_id, deployment=deployment.id, status="success"
    ).inc()
    INFERENCE_LATENCY_SECONDS.labels(
        model=deployment.model_id, deployment=deployment.id
    ).observe(elapsed_ms / 1000.0)

    log_entry = InferenceLog(
        deployment_id=deployment.id,
        model_id=deployment.model_id,
        model_version=deployment.version_label,
        replica_id=replica.replica_id,
        latency_ms=round(elapsed_ms, 3),
        status="success",
    )
    db.add(log_entry)
    db.commit()

    return PredictResponse(
        model_id=deployment.model_id,
        model_name=model_name,
        deployment_id=deployment.id,
        version=deployment.version_label,
        replica_id=replica.replica_id,
        predictions=predictions,
        probabilities=probabilities,
        inference_time_ms=round(elapsed_ms, 3),
    )
