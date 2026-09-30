"""
Controlled Performance Benchmark Experiment Service.

Executes controlled inference benchmark tests across varying replica counts,
stores benchmark telemetry in the database, and provides CSV export capabilities for research analysis.
"""
from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Deployment, Experiment
from app.replica_manager import execute_predict_with_load_balancer


def run_controlled_experiment(
    db: Session,
    deployment_id: str,
    requests: int = 100,
    features: list[Any] | None = None,
) -> Experiment:
    """
    Run a controlled inference benchmark experiment across active replicas,
    compute P95 latency and throughput, and save the experiment record in DB.
    """
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

    num_requests = max(1, min(requests, 1000))
    feat_input = features if features is not None else [0.0, 0.0]

    started_at = datetime.now(timezone.utc)
    start_wall = time.perf_counter()

    successful = 0
    failed = 0
    latencies: list[float] = []

    for _ in range(num_requests):
        try:
            res = execute_predict_with_load_balancer(
                db, deployment, deployment.model.name, target_version, feat_input
            )
            successful += 1
            latencies.append(res.inference_time_ms)
        except Exception:
            failed += 1

    total_wall = time.perf_counter() - start_wall
    completed_at = datetime.now(timezone.utc)

    avg_lat = round(float(np.mean(latencies)), 2) if latencies else 0.0
    p95_lat = round(float(np.percentile(latencies, 95)), 2) if latencies else 0.0
    throughput = round(successful / total_wall, 2) if total_wall > 0 else 0.0
    error_rate = round((failed / num_requests) * 100.0, 2)

    is_autoscaling = bool(
        deployment.autoscaling_config and deployment.autoscaling_config.enabled
    )
    exp = Experiment(
        deployment_id=deployment.id,
        model_id=deployment.model_id,
        model_name=deployment.model.name,
        model_version=deployment.version_label,
        replica_count=deployment.replicas,
        total_requests=num_requests,
        successful_requests=successful,
        failed_requests=failed,
        average_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        throughput_rps=throughput,
        error_rate_percent=error_rate,
        autoscaling_enabled=is_autoscaling,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)

    return exp


def get_experiments_list(db: Session) -> list[Experiment]:
    """Retrieve all past experiment records, newest first."""
    return list(db.scalars(select(Experiment).order_by(Experiment.completed_at.desc())).all())


def generate_experiments_csv(experiments: list[Experiment]) -> str:
    """Generate CSV string formatted for research paper benchmark comparison."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "experiment_id",
            "deployment_id",
            "model_id",
            "model_name",
            "model_version",
            "replica_count",
            "total_requests",
            "successful_requests",
            "failed_requests",
            "average_latency_ms",
            "p95_latency_ms",
            "throughput_rps",
            "error_rate_percent",
            "autoscaling_enabled",
            "started_at",
            "completed_at",
        ]
    )

    for e in experiments:
        writer.writerow(
            [
                e.id,
                e.deployment_id,
                e.model_id,
                e.model_name,
                e.model_version,
                e.replica_count,
                e.total_requests,
                e.successful_requests,
                e.failed_requests,
                e.average_latency_ms,
                e.p95_latency_ms,
                e.throughput_rps,
                e.error_rate_percent,
                e.autoscaling_enabled,
                e.started_at.isoformat(),
                e.completed_at.isoformat(),
            ]
        )

    return output.getvalue()
