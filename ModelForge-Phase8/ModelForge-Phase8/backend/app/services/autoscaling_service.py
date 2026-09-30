"""
Intelligent Auto-Scaling & Reliability Automation Service.

Provides telemetry-driven horizontal auto-scaling for model deployments.
Evaluates observed Phase 5 inference telemetry (P95 latency, throughput RPS, error rate,
and idle duration) and executes replica scaling via Phase 6 container management.
Enforces strict min/max replica bounds, cooldown protections, flap prevention, and
retains complete scaling decision history.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import AutoScalingConfig, Deployment, InferenceLog, ScalingEvent
from app.replica_manager import sync_deployment_replicas
from app.schemas import (
    AutoScalingConfigOut,
    AutoScalingConfigUpdate,
    AutoScalingEvaluationResult,
)

logger = logging.getLogger("modelforge.autoscaling")

# Global lock and task tracking for background evaluation loop
_scheduler_lock = threading.Lock()
_scheduler_running = False
_scheduler_thread: threading.Thread | None = None


def get_or_create_autoscaling_config(db: Session, deployment_id: str) -> AutoScalingConfig:
    """Retrieve existing auto-scaling configuration or create one with system defaults."""
    cfg = db.scalar(
        select(AutoScalingConfig).where(AutoScalingConfig.deployment_id == deployment_id)
    )
    if cfg is None:
        cfg = AutoScalingConfig(
            deployment_id=deployment_id,
            enabled=False,  # disabled by default
            min_replicas=settings.autoscaling_default_min_replicas,
            max_replicas=settings.autoscaling_default_max_replicas,
            target_latency_ms=settings.autoscaling_default_target_latency_ms,
            target_throughput_rps=settings.autoscaling_default_target_throughput_rps,
            scale_up_error_rate_percent=settings.autoscaling_default_scale_up_error_rate_percent,
            scale_down_idle_seconds=settings.autoscaling_default_scale_down_idle_seconds,
            cooldown_seconds=settings.autoscaling_default_cooldown_seconds,
            evaluation_interval_seconds=settings.autoscaling_default_evaluation_interval_seconds,
        )
        db.add(cfg)
        db.flush()
    return cfg


def compute_cooldown_status(config: AutoScalingConfig) -> tuple[bool, int]:
    """Compute whether cooldown is currently active and remaining seconds."""
    if not config.last_scaled_at:
        return False, 0

    now = datetime.now(timezone.utc)
    last_scaled = config.last_scaled_at
    if last_scaled.tzinfo is None:
        last_scaled = last_scaled.replace(tzinfo=timezone.utc)

    elapsed_sec = (now - last_scaled).total_seconds()
    if elapsed_sec < config.cooldown_seconds:
        remaining = max(1, int(config.cooldown_seconds - elapsed_sec))
        return True, remaining

    return False, 0


def to_config_out(config: AutoScalingConfig) -> AutoScalingConfigOut:
    """Convert ORM AutoScalingConfig to response schema including cooldown state."""
    is_in_cooldown, remaining = compute_cooldown_status(config)
    return AutoScalingConfigOut(
        id=config.id,
        deployment_id=config.deployment_id,
        enabled=config.enabled,
        min_replicas=config.min_replicas,
        max_replicas=config.max_replicas,
        target_latency_ms=config.target_latency_ms,
        target_throughput_rps=config.target_throughput_rps,
        scale_up_error_rate_percent=config.scale_up_error_rate_percent,
        scale_down_idle_seconds=config.scale_down_idle_seconds,
        cooldown_seconds=config.cooldown_seconds,
        evaluation_interval_seconds=config.evaluation_interval_seconds,
        last_evaluated_at=config.last_evaluated_at,
        last_scaled_at=config.last_scaled_at,
        cooldown_remaining_seconds=remaining,
        is_in_cooldown=is_in_cooldown,
    )


def validate_autoscaling_update(
    current_config: AutoScalingConfig, update: AutoScalingConfigUpdate
) -> None:
    """Validate auto-scaling configuration parameter boundaries."""
    new_min = update.min_replicas if update.min_replicas is not None else current_config.min_replicas
    new_max = update.max_replicas if update.max_replicas is not None else current_config.max_replicas

    if new_min < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="min_replicas must be at least 1",
        )

    if new_max > settings.max_replicas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"max_replicas cannot exceed system limit of {settings.max_replicas}",
        )

    if new_min > new_max:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"min_replicas ({new_min}) cannot be greater than max_replicas ({new_max})",
        )

    if update.target_latency_ms is not None and update.target_latency_ms <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_latency_ms must be greater than 0",
        )

    if update.target_throughput_rps is not None and update.target_throughput_rps <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_throughput_rps must be greater than 0",
        )

    if update.scale_up_error_rate_percent is not None and not (
        0 <= update.scale_up_error_rate_percent <= 100
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scale_up_error_rate_percent must be between 0 and 100",
        )

    if update.scale_down_idle_seconds is not None and update.scale_down_idle_seconds < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scale_down_idle_seconds must be at least 10 seconds",
        )

    if update.cooldown_seconds is not None and update.cooldown_seconds < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cooldown_seconds cannot be negative",
        )

    if update.evaluation_interval_seconds is not None and update.evaluation_interval_seconds < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="evaluation_interval_seconds must be at least 5 seconds",
        )


def evaluate_deployment_autoscaling(
    db: Session, deployment_id: str, force: bool = False
) -> AutoScalingEvaluationResult:
    """
    Evaluate actual operational metrics for a deployment and scale replicas if justified.
    Records a persistent ScalingEvent with the full reason and outcome.
    """
    deployment = db.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Deployment '{deployment_id}' not found",
        )

    config = get_or_create_autoscaling_config(db, deployment.id)
    now = datetime.now(timezone.utc)

    # If deployment is not running, no scaling action can take place
    if deployment.status != "running":
        return AutoScalingEvaluationResult(
            deployment_id=deployment.id,
            action="NO_ACTION",
            previous_replicas=deployment.replicas,
            target_replicas=deployment.replicas,
            trigger_reason=f"Deployment is '{deployment.status}', not 'running'",
            cooldown_active=False,
            success=True,
        )

    # If auto-scaling is disabled and not a forced manual trigger, do nothing
    if not config.enabled and not force:
        return AutoScalingEvaluationResult(
            deployment_id=deployment.id,
            action="NO_ACTION",
            previous_replicas=deployment.replicas,
            target_replicas=deployment.replicas,
            trigger_reason="Auto-scaling is disabled for this deployment",
            cooldown_active=False,
            success=True,
        )

    # Check cooldown protection
    is_in_cooldown, remaining_cooldown = compute_cooldown_status(config)
    if is_in_cooldown and not force:
        reason = f"Cooldown period active ({remaining_cooldown}s remaining); scaling postponed"
        event = ScalingEvent(
            deployment_id=deployment.id,
            previous_replicas=deployment.replicas,
            target_replicas=deployment.replicas,
            action="NO_ACTION",
            trigger_reason=reason,
            timestamp=now,
            success=True,
        )
        db.add(event)
        config.last_evaluated_at = now
        db.commit()
        return AutoScalingEvaluationResult(
            deployment_id=deployment.id,
            action="NO_ACTION",
            previous_replicas=deployment.replicas,
            target_replicas=deployment.replicas,
            trigger_reason=reason,
            cooldown_active=True,
            success=True,
        )

    # 1. Fetch recent telemetry records
    window_sec = max(config.evaluation_interval_seconds * 2, 60)
    window_start = now - timedelta(seconds=window_sec)

    recent_logs = list(
        db.scalars(
            select(InferenceLog)
            .where(InferenceLog.deployment_id == deployment.id)
            .where(InferenceLog.timestamp >= window_start)
            .order_by(InferenceLog.timestamp.desc())
        ).all()
    )

    last_log = db.scalar(
        select(InferenceLog)
        .where(InferenceLog.deployment_id == deployment.id)
        .order_by(InferenceLog.timestamp.desc())
        .limit(1)
    )

    action = "NO_ACTION"
    target_replicas = deployment.replicas
    prev_replicas = deployment.replicas
    trigger_reason = ""
    p95_lat: float | None = None
    throughput: float | None = None
    error_rate: float | None = None

    if not recent_logs:
        # No traffic in the recent evaluation window - calculate idle time
        if last_log and last_log.timestamp:
            ts = last_log.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            idle_seconds = (now - ts).total_seconds()
        else:
            dep_created = deployment.created_at
            if dep_created.tzinfo is None:
                dep_created = dep_created.replace(tzinfo=timezone.utc)
            idle_seconds = (now - dep_created).total_seconds()

        if idle_seconds >= config.scale_down_idle_seconds:
            if deployment.replicas > config.min_replicas:
                target_replicas = max(config.min_replicas, deployment.replicas - 1)
                action = "SCALE_DOWN"
                trigger_reason = (
                    f"No traffic observed for {int(idle_seconds)}s (idle threshold: "
                    f"{config.scale_down_idle_seconds}s); scaling down towards minimum ({config.min_replicas})"
                )
            else:
                action = "NO_ACTION"
                trigger_reason = (
                    f"Deployment is idle ({int(idle_seconds)}s) and already at configured "
                    f"minimum replicas ({config.min_replicas})"
                )
        else:
            action = "NO_ACTION"
            trigger_reason = (
                f"Insufficient telemetry in recent evaluation window ({int(idle_seconds)}s since activity); "
                f"idle threshold ({config.scale_down_idle_seconds}s) not yet reached; maintaining replica count"
            )

    else:
        # Check telemetry sufficiency (prevent flapping/oscillation on near-empty metrics)
        if len(recent_logs) < 3:
            action = "NO_ACTION"
            trigger_reason = (
                f"Insufficient telemetry sample count ({len(recent_logs)} requests observed; minimum 3 required); "
                f"maintaining replica count"
            )
        else:
            # Real traffic exists - compute real statistical telemetry
            latencies = [l.latency_ms for l in recent_logs]
            p95_lat = round(float(np.percentile(latencies, 95)), 2)
            total_req = len(recent_logs)
            successful_logs = [l for l in recent_logs if l.status == "success"]
            failed_req = total_req - len(successful_logs)
            error_rate = round((failed_req / total_req) * 100.0, 2)

            timestamps = [l.timestamp for l in recent_logs]
            span_sec = max((max(timestamps) - min(timestamps)).total_seconds(), 1.0)
            throughput = round(len(successful_logs) / span_sec, 2)

            # Scale-Up Triggers
            scale_up_reason = None
            if p95_lat > config.target_latency_ms:
                scale_up_reason = (
                    f"Observed P95 latency ({p95_lat} ms) exceeded target threshold ({config.target_latency_ms} ms)"
                )
            elif throughput >= config.target_throughput_rps:
                scale_up_reason = (
                    f"Observed throughput ({throughput} RPS) reached capacity threshold ({config.target_throughput_rps} RPS)"
                )
            elif error_rate >= config.scale_up_error_rate_percent:
                scale_up_reason = (
                    f"Observed error rate ({error_rate}%) exceeded threshold ({config.scale_up_error_rate_percent}%)"
                )
            elif deployment.active_replicas < deployment.replicas:
                scale_up_reason = (
                    f"Replica health degraded ({deployment.active_replicas}/{deployment.replicas} healthy) while serving traffic"
                )

            if scale_up_reason:
                if deployment.replicas < config.max_replicas:
                    target_replicas = min(config.max_replicas, deployment.replicas + 1)
                    action = "SCALE_UP"
                    trigger_reason = scale_up_reason
                else:
                    action = "NO_ACTION"
                    trigger_reason = (
                        f"{scale_up_reason}, but deployment is already at maximum replicas ({config.max_replicas})"
                    )
            else:
                # Scale-Down Check (low load conditions)
                if (
                    deployment.replicas > config.min_replicas
                    and p95_lat < (0.5 * config.target_latency_ms)
                    and throughput < (0.2 * config.target_throughput_rps)
                ):
                    target_replicas = max(config.min_replicas, deployment.replicas - 1)
                    action = "SCALE_DOWN"
                    trigger_reason = (
                        f"Traffic load is low (P95 latency {p95_lat} ms, throughput {throughput} RPS); "
                        f"scaling down towards minimum ({config.min_replicas})"
                    )
                else:
                    action = "NO_ACTION"
                    trigger_reason = (
                        f"Observed metrics are within operational targets (P95 latency {p95_lat} ms, "
                        f"throughput {throughput} RPS, error rate {error_rate}%); maintaining replica count"
                    )

    # 2. Execute scaling if justified
    scaling_success = True
    error_message: str | None = None

    if action in ["SCALE_UP", "SCALE_DOWN"] and target_replicas != prev_replicas:
        try:
            target_version = deployment.model_version
            if target_version is None:
                target_version = next(
                    (v for v in deployment.model.versions if v.id == deployment.model_version_id), None
                )

            deployment.replicas = target_replicas
            deployment.scaling_status = "scaling"
            db.commit()

            sync_deployment_replicas(db, deployment, target_version)
            config.last_scaled_at = now
        except Exception as exc:
            scaling_success = False
            error_message = str(exc)
            logger.error("Auto-scaling failed for deployment %s: %s", deployment.id, exc)

    # 3. Persist scaling decision event
    event = ScalingEvent(
        deployment_id=deployment.id,
        previous_replicas=prev_replicas,
        target_replicas=target_replicas,
        action=action,
        trigger_reason=trigger_reason,
        observed_p95_latency_ms=p95_lat,
        observed_throughput_rps=throughput,
        observed_error_rate_percent=error_rate,
        success=scaling_success,
        error_message=error_message,
        timestamp=now,
    )
    db.add(event)
    config.last_evaluated_at = now
    db.commit()

    return AutoScalingEvaluationResult(
        deployment_id=deployment.id,
        action=action,
        previous_replicas=prev_replicas,
        target_replicas=target_replicas,
        trigger_reason=trigger_reason,
        observed_p95_latency_ms=p95_lat,
        observed_throughput_rps=throughput,
        observed_error_rate_percent=error_rate,
        cooldown_active=is_in_cooldown,
        success=scaling_success,
        error_message=error_message,
    )


def evaluate_all_enabled_deployments(db: Session) -> list[AutoScalingEvaluationResult]:
    """System-wide evaluation of all running deployments with auto-scaling enabled."""
    deployments = list(
        db.scalars(
            select(Deployment)
            .join(AutoScalingConfig, AutoScalingConfig.deployment_id == Deployment.id)
            .where(Deployment.status == "running")
            .where(AutoScalingConfig.enabled == True)  # noqa: E712
        ).all()
    )

    results: list[AutoScalingEvaluationResult] = []
    for dep in deployments:
        try:
            res = evaluate_deployment_autoscaling(db, dep.id, force=False)
            results.append(res)
        except Exception as exc:
            logger.error("Error evaluating deployment %s: %s", dep.id, exc)
    return results


def _scheduler_worker_loop():
    """Background evaluation worker thread."""
    global _scheduler_running
    logger.info("Auto-scaling background evaluation loop started")
    while _scheduler_running:
        try:
            with SessionLocal() as db:
                evaluate_all_enabled_deployments(db)
        except Exception as exc:
            logger.warning("Auto-scaling background loop iteration encountered: %s", exc)

        # Sleep in small slices to allow rapid shutdown
        for _ in range(settings.autoscaling_loop_sleep_seconds):
            if not _scheduler_running:
                break
            time.sleep(1.0)

    logger.info("Auto-scaling background evaluation loop stopped")


def start_autoscaling_scheduler():
    """Start the background scheduler thread if not already running."""
    global _scheduler_running, _scheduler_thread
    if not settings.autoscaling_background_enabled:
        logger.info("Auto-scaling background scheduler is disabled by configuration")
        return

    with _scheduler_lock:
        if _scheduler_running:
            return
        _scheduler_running = True
        _scheduler_thread = threading.Thread(
            target=_scheduler_worker_loop, daemon=True, name="ModelForge-AutoScaler"
        )
        _scheduler_thread.start()


def stop_autoscaling_scheduler():
    """Cleanly stop the background scheduler thread."""
    global _scheduler_running
    with _scheduler_lock:
        _scheduler_running = False
