"""
Monitoring & Telemetry Analytics Service.

Provides metrics calculation (averages, min/max, P95/P99 percentiles, throughput,
error rates), time-range filtering, time-series bucket aggregation for charts,
system resource metrics via psutil, operational alert evaluation, and CSV telemetry exports.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Deployment, InferenceLog, Model, Replica, ScalingEvent
from app.schemas import (
    AlertOut,
    DeploymentMetricsOut,
    ModelMetricsOut,
    MonitoringSummaryOut,
    SystemMetricsOut,
    TimeSeriesPoint,
    ReplicaMetricsOut,
    RecentInferencesPage,
    RecentInferenceOut,
)

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore


def parse_time_range(range_str: str) -> datetime | None:
    """Parse time range string ('5m', '15m', '1h', '6h', '24h', 'all') into a UTC start threshold."""
    now = datetime.now(timezone.utc)
    s = (range_str or "1h").strip().lower()

    if s == "5m":
        return now - timedelta(minutes=5)
    if s == "15m":
        return now - timedelta(minutes=15)
    if s == "1h":
        return now - timedelta(hours=1)
    if s == "6h":
        return now - timedelta(hours=6)
    if s == "24h":
        return now - timedelta(hours=24)
    if s == "all":
        return None

    return now - timedelta(hours=1)


def compute_metrics(logs: list[InferenceLog]) -> dict[str, Any]:
    """Calculate statistical operational metrics from a set of InferenceLog records."""
    total = len(logs)
    if total == 0:
        return {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "error_rate_percent": 0.0,
            "average_latency_ms": 0.0,
            "min_latency_ms": 0.0,
            "max_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "throughput_rps": 0.0,
        }

    successful_logs = [l for l in logs if l.status == "success"]
    successful = len(successful_logs)
    failed = total - successful
    error_rate = round((failed / total) * 100.0, 2)

    latencies = [l.latency_ms for l in logs]
    avg_lat = round(float(np.mean(latencies)), 2)
    min_lat = round(float(np.min(latencies)), 2)
    max_lat = round(float(np.max(latencies)), 2)
    p95_lat = round(float(np.percentile(latencies, 95)), 2)
    p99_lat = round(float(np.percentile(latencies, 99)), 2)

    # Compute duration span for throughput calculation
    timestamps = [l.timestamp for l in logs]
    if len(timestamps) > 1:
        span_sec = (max(timestamps) - min(timestamps)).total_seconds()
        span_sec = max(span_sec, 1.0)
    else:
        span_sec = 1.0

    throughput = round(successful / span_sec, 2)

    return {
        "total_requests": total,
        "successful_requests": successful,
        "failed_requests": failed,
        "error_rate_percent": error_rate,
        "average_latency_ms": avg_lat,
        "min_latency_ms": min_lat,
        "max_latency_ms": max_lat,
        "p95_latency_ms": p95_lat,
        "p99_latency_ms": p99_lat,
        "throughput_rps": throughput,
    }


def get_monitoring_summary(db: Session, range_str: str = "1h") -> MonitoringSummaryOut:
    """Fetch system-wide operational metrics summary over specified time range."""
    start_time = parse_time_range(range_str)

    query = select(InferenceLog)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)

    logs = list(db.scalars(query).all())
    stats = compute_metrics(logs)

    active_deps = list(db.scalars(select(Deployment).where(Deployment.status == "running")).all())
    active_replicas_sum = sum(d.active_replicas for d in active_deps)

    return MonitoringSummaryOut(
        time_range=range_str,
        total_requests=stats["total_requests"],
        successful_requests=stats["successful_requests"],
        failed_requests=stats["failed_requests"],
        error_rate_percent=stats["error_rate_percent"],
        average_latency_ms=stats["average_latency_ms"],
        min_latency_ms=stats["min_latency_ms"],
        max_latency_ms=stats["max_latency_ms"],
        p95_latency_ms=stats["p95_latency_ms"],
        p99_latency_ms=stats["p99_latency_ms"],
        throughput_rps=stats["throughput_rps"],
        active_deployments_count=len(active_deps),
        active_replicas_count=active_replicas_sum,
    )


def get_deployment_metrics(db: Session, deployment_id: str, range_str: str = "1h") -> DeploymentMetricsOut:
    """Fetch operational metrics for a single deployment."""
    dep = db.get(Deployment, deployment_id)
    if dep is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found"
        )

    start_time = parse_time_range(range_str)
    query = select(InferenceLog).where(InferenceLog.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)

    logs = list(db.scalars(query).all())
    stats = compute_metrics(logs)

    return DeploymentMetricsOut(
        deployment_id=dep.id,
        model_id=dep.model_id,
        model_name=dep.model.name,
        version_label=dep.version_label,
        status=dep.status,
        scaling_status=dep.scaling_status,
        replicas=dep.replicas,
        active_replicas=dep.active_replicas,
        total_requests=stats["total_requests"],
        successful_requests=stats["successful_requests"],
        failed_requests=stats["failed_requests"],
        error_rate_percent=stats["error_rate_percent"],
        average_latency_ms=stats["average_latency_ms"],
        p95_latency_ms=stats["p95_latency_ms"],
        throughput_rps=stats["throughput_rps"],
    )


def get_model_metrics(db: Session, model_id: str, range_str: str = "1h") -> ModelMetricsOut:
    """Fetch metrics for a model grouped by version."""
    model = db.get(Model, model_id)
    if model is None:
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found"
        )

    start_time = parse_time_range(range_str)
    query = select(InferenceLog).where(InferenceLog.model_id == model_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)

    all_logs = list(db.scalars(query).all())
    overall_stats = compute_metrics(all_logs)

    version_groups: dict[str, list[InferenceLog]] = {}
    for log in all_logs:
        version_groups.setdefault(log.model_version, []).append(log)

    v_metrics = []
    for ver_label, v_logs in version_groups.items():
        st = compute_metrics(v_logs)
        st["version"] = ver_label
        v_metrics.append(st)

    return ModelMetricsOut(
        model_id=model.id,
        model_name=model.name,
        total_requests=overall_stats["total_requests"],
        average_latency_ms=overall_stats["average_latency_ms"],
        versions_metrics=v_metrics,
    )


def get_all_deployment_metrics(db: Session, range_str: str = "1h") -> list[DeploymentMetricsOut]:
    """Return per-deployment measurements without mixing their traffic together."""
    deployments = list(db.scalars(select(Deployment).order_by(Deployment.created_at.desc())).all())
    return [get_deployment_metrics(db, deployment.id, range_str) for deployment in deployments]


def get_replica_metrics(
    db: Session, deployment_id: str, range_str: str = "1h"
) -> list[ReplicaMetricsOut]:
    """Aggregate request records by replica and retain replicas with no traffic."""
    if db.get(Deployment, deployment_id) is None:
        from fastapi import HTTPException, status
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Deployment '{deployment_id}' not found")

    start_time = parse_time_range(range_str)
    replicas = list(db.scalars(select(Replica).where(Replica.deployment_id == deployment_id)).all())
    query = select(InferenceLog).where(InferenceLog.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)
    logs = list(db.scalars(query).all())

    grouped: dict[str, list[InferenceLog]] = {}
    for log in logs:
        grouped.setdefault(log.replica_id, []).append(log)

    result: list[ReplicaMetricsOut] = []
    for replica in replicas:
        replica_logs = grouped.get(replica.replica_id, [])
        stats = compute_metrics(replica_logs)
        last_seen = max((log.timestamp for log in replica_logs), default=None)
        result.append(ReplicaMetricsOut(
            replica_id=replica.replica_id,
            status=replica.status.upper(),
            request_count=stats["total_requests"],
            successful_requests=stats["successful_requests"],
            failed_requests=stats["failed_requests"],
            average_latency_ms=stats["average_latency_ms"],
            last_seen=last_seen,
        ))
    return sorted(result, key=lambda replica: replica.replica_id)


def get_recent_inferences(
    db: Session, range_str: str = "1h", deployment_id: str | None = None,
    limit: int = 50, offset: int = 0,
) -> RecentInferencesPage:
    """Return a bounded page of observed requests, newest first."""
    start_time = parse_time_range(range_str)
    query = select(InferenceLog)
    if deployment_id:
        query = query.where(InferenceLog.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)
    rows = list(db.scalars(query.order_by(InferenceLog.timestamp.desc()).offset(offset).limit(limit + 1)).all())
    has_more = len(rows) > limit
    return RecentInferencesPage(
        items=[RecentInferenceOut.model_validate(row) for row in rows[:limit]],
        limit=limit,
        offset=offset,
        has_more=has_more,
    )


def get_time_series(
    db: Session, range_str: str = "1h", deployment_id: str | None = None
) -> list[TimeSeriesPoint]:
    """Bucket inference logs into time-series intervals for dashboard graph visualizations."""
    start_time = parse_time_range(range_str)
    query = select(InferenceLog)
    if deployment_id:
        query = query.where(InferenceLog.deployment_id == deployment_id)
    if start_time is not None:
        query = query.where(InferenceLog.timestamp >= start_time)

    logs = list(db.scalars(query.order_by(InferenceLog.timestamp)).all())
    if not logs:
        return []

    # Determine bucket size (e.g. 10 time intervals)
    t_min = logs[0].timestamp
    t_max = logs[-1].timestamp
    total_sec = max((t_max - t_min).total_seconds(), 1.0)
    num_buckets = 10
    bucket_sec = max(total_sec / num_buckets, 1.0)

    buckets: dict[int, list[InferenceLog]] = {}
    for log in logs:
        idx = int((log.timestamp - t_min).total_seconds() // bucket_sec)
        idx = min(idx, num_buckets - 1)
        buckets.setdefault(idx, []).append(log)

    points: list[TimeSeriesPoint] = []
    for b_idx in range(num_buckets):
        b_logs = buckets.get(b_idx, [])
        ts = t_min + timedelta(seconds=(b_idx + 0.5) * bucket_sec)
        if b_logs:
            st = compute_metrics(b_logs)
            points.append(
                TimeSeriesPoint(
                    timestamp=ts,
                    request_count=st["total_requests"],
                    average_latency_ms=st["average_latency_ms"],
                    p95_latency_ms=st["p95_latency_ms"],
                    error_rate_percent=st["error_rate_percent"],
                )
            )
        else:
            points.append(
                TimeSeriesPoint(
                    timestamp=ts,
                    request_count=0,
                    average_latency_ms=0.0,
                    p95_latency_ms=0.0,
                    error_rate_percent=0.0,
                )
            )

    return points


def evaluate_active_alerts(db: Session, range_str: str = "1h") -> list[AlertOut]:
    """Evaluate operational alert thresholds for latency, error rate, and degraded deployments."""
    alerts: list[AlertOut] = []
    now = datetime.now(timezone.utc)

    # 1. Check all running deployments for scaling/degraded state
    deployments = list(db.scalars(select(Deployment)).all())
    for d in deployments:
        if d.status == "running" and d.scaling_status == "degraded":
            alerts.append(
                AlertOut(
                    alert_type="degraded_deployment",
                    title="Deployment Degraded",
                    message=f"Deployment '{d.model.name}' is running with {d.active_replicas}/{d.replicas} healthy replicas.",
                    severity="warning",
                    timestamp=now,
                    deployment_id=d.id,
                )
            )
        elif d.status == "failed":
            alerts.append(
                AlertOut(
                    alert_type="deployment_failed",
                    title="Deployment Failed",
                    message=f"Deployment '{d.model.name}' ({d.version_label}) failed: {d.error_message or 'Unknown error'}",
                    severity="critical",
                    timestamp=now,
                    deployment_id=d.id,
                )
            )

    # 2. Check telemetry metric threshold breaches over time range
    summary = get_monitoring_summary(db, range_str)

    if summary.total_requests > 0:
        if summary.p95_latency_ms > settings.alert_latency_threshold_ms:
            alerts.append(
                AlertOut(
                    alert_type="high_latency",
                    title="High Latency Detected",
                    message=f"P95 latency ({summary.p95_latency_ms} ms) exceeded threshold ({settings.alert_latency_threshold_ms} ms).",
                    severity="warning",
                    timestamp=now,
                )
            )

        if summary.error_rate_percent > settings.alert_error_rate_threshold_percent:
            alerts.append(
                AlertOut(
                    alert_type="high_error_rate",
                    title="High Error Rate Detected",
                    message=f"Error rate ({summary.error_rate_percent}%) exceeded threshold ({settings.alert_error_rate_threshold_percent}%).",
                    severity="critical",
                    timestamp=now,
                )
            )

    # 3. Check recent auto-scaling decision notices
    start_threshold = parse_time_range(range_str)
    ev_query = select(ScalingEvent)
    if start_threshold is not None:
        ev_query = ev_query.where(ScalingEvent.timestamp >= start_threshold)
    recent_events = list(
        db.scalars(ev_query.order_by(ScalingEvent.timestamp.desc()).limit(20)).all()
    )

    for ev in recent_events:
        dep = db.get(Deployment, ev.deployment_id)
        dep_name = dep.model.name if dep and dep.model else ev.deployment_id

        if not ev.success:
            alerts.append(
                AlertOut(
                    alert_type="autoscaling_failed",
                    title="Auto-scaling Failed",
                    message=f"Deployment '{dep_name}' auto-scaling failed: {ev.error_message or 'Unknown error'}",
                    severity="critical",
                    timestamp=ev.timestamp,
                    deployment_id=ev.deployment_id,
                )
            )
        elif ev.action == "SCALE_UP":
            alerts.append(
                AlertOut(
                    alert_type="autoscaled_up",
                    title="Auto-scaled Up",
                    message=f"Deployment '{dep_name}' scaled up from {ev.previous_replicas} to {ev.target_replicas} replicas. {ev.trigger_reason}",
                    severity="info",
                    timestamp=ev.timestamp,
                    deployment_id=ev.deployment_id,
                )
            )
        elif ev.action == "SCALE_DOWN":
            alerts.append(
                AlertOut(
                    alert_type="autoscaled_down",
                    title="Auto-scaled Down",
                    message=f"Deployment '{dep_name}' scaled down from {ev.previous_replicas} to {ev.target_replicas} replicas. {ev.trigger_reason}",
                    severity="info",
                    timestamp=ev.timestamp,
                    deployment_id=ev.deployment_id,
                )
            )
        elif ev.action == "NO_ACTION" and "maximum replicas" in ev.trigger_reason.lower():
            alerts.append(
                AlertOut(
                    alert_type="autoscaling_blocked_max",
                    title="Auto-scaling Blocked by Max Replicas",
                    message=f"Deployment '{dep_name}' reached maximum replicas: {ev.trigger_reason}",
                    severity="warning",
                    timestamp=ev.timestamp,
                    deployment_id=ev.deployment_id,
                )
            )
        elif ev.action == "NO_ACTION" and "insufficient" in ev.trigger_reason.lower():
            alerts.append(
                AlertOut(
                    alert_type="insufficient_telemetry",
                    title="Insufficient Telemetry for Scaling",
                    message=f"Deployment '{dep_name}': {ev.trigger_reason}",
                    severity="info",
                    timestamp=ev.timestamp,
                    deployment_id=ev.deployment_id,
                )
            )

    return alerts


def get_system_resources() -> SystemMetricsOut:
    """Collect host CPU and Memory utilization using psutil if available."""
    if psutil is None:
        return SystemMetricsOut(cpu_percent=None, memory_percent=None)

    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        return SystemMetricsOut(cpu_percent=cpu, memory_percent=mem)
    except Exception:
        return SystemMetricsOut(cpu_percent=None, memory_percent=None)


def cleanup_expired_monitoring_data(db: Session) -> int:
    """Remove telemetry older than the explicitly configured retention period."""
    days = settings.monitoring_retention_days
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = db.execute(delete(InferenceLog).where(InferenceLog.timestamp < cutoff))
    db.commit()
    return int(result.rowcount or 0)


def generate_monitoring_csv(logs: list[InferenceLog]) -> str:
    """Generate CSV string formatted for research analysis export."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "timestamp",
            "deployment_id",
            "model_id",
            "model_version",
            "replica_id",
            "latency_ms",
            "status",
            "error_message",
        ]
    )

    for l in logs:
        writer.writerow(
            [
                l.id,
                l.timestamp.isoformat(),
                l.deployment_id,
                l.model_id,
                l.model_version,
                l.replica_id,
                l.latency_ms,
                l.status,
                l.error_message or "",
            ]
        )

    return output.getvalue()
