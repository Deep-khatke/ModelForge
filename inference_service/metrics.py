"""
ModelForge Inference Service - Prometheus Metrics Definitions.
Tracks prediction requests, errors, latencies, model loading performance, and active requests.
"""
from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Dedicated registry for standalone inference replica container
registry: CollectorRegistry = CollectorRegistry(auto_describe=True)

PREDICTION_REQUESTS_TOTAL = Counter(
    "modelforge_model_server_prediction_requests_total",
    "Total prediction requests received by model-server",
    ["model", "status"],
    registry=registry,
)

PREDICTION_ERRORS_TOTAL = Counter(
    "modelforge_model_server_prediction_errors_total",
    "Total prediction errors encountered by model-server",
    ["model", "error_type"],
    registry=registry,
)

PREDICTION_LATENCY_SECONDS = Histogram(
    "modelforge_model_server_prediction_latency_seconds",
    "Model inference latency measured inside model-server in seconds",
    ["model"],
    buckets=[0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5],
    registry=registry,
)

MODEL_LOADING_DURATION_SECONDS = Gauge(
    "modelforge_model_server_loading_duration_seconds",
    "Model artifact load duration in seconds",
    ["model"],
    registry=registry,
)

MODEL_LOADED_STATUS = Gauge(
    "modelforge_model_server_loaded_status",
    "Model loaded readiness status (1=loaded and ready, 0=not ready)",
    ["model"],
    registry=registry,
)

ACTIVE_REQUESTS = Gauge(
    "modelforge_model_server_active_requests",
    "Number of inference requests currently being processed by model-server",
    ["model"],
    registry=registry,
)


def get_metrics_content() -> tuple[bytes, str]:
    """Generate latest Prometheus metrics formatted output and content-type."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
