"""
ModelForge Backend - Prometheus Metrics Definitions and Exporter.
Tracks HTTP requests, latencies, inference performance, deployments, and storage operations.
Ensures low cardinality by sanitizing endpoint paths and bounding label sets.
Safely handles test suite reloads without CollectorRegistry conflicts.
"""
from __future__ import annotations

import re
from typing import Any
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    REGISTRY,
    generate_latest,
)

# Use dedicated CollectorRegistry for ModelForge backend to avoid test reload collisions
registry: CollectorRegistry = CollectorRegistry(auto_describe=True)


def _get_or_create_counter(name: str, documentation: str, labelnames: tuple = (), **kwargs) -> Counter:
    if name in registry._names_to_collectors:
        return registry._names_to_collectors[name]
    return Counter(name, documentation, labelnames, registry=registry, **kwargs)


def _get_or_create_histogram(name: str, documentation: str, labelnames: tuple = (), buckets: list = None, **kwargs) -> Histogram:
    if name in registry._names_to_collectors:
        return registry._names_to_collectors[name]
    if buckets:
        return Histogram(name, documentation, labelnames, buckets=buckets, registry=registry, **kwargs)
    return Histogram(name, documentation, labelnames, registry=registry, **kwargs)


def _get_or_create_gauge(name: str, documentation: str, labelnames: tuple = (), **kwargs) -> Gauge:
    if name in registry._names_to_collectors:
        return registry._names_to_collectors[name]
    return Gauge(name, documentation, labelnames, registry=registry, **kwargs)


# 1. HTTP Request Metrics
HTTP_REQUESTS_TOTAL = _get_or_create_counter(
    "modelforge_http_requests_total",
    "Total HTTP requests received by ModelForge backend",
    labelnames=("method", "endpoint", "status"),
)

HTTP_REQUEST_DURATION_SECONDS = _get_or_create_histogram(
    "modelforge_http_request_duration_seconds",
    "HTTP request latency in seconds",
    labelnames=("method", "endpoint", "status"),
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_ERRORS_TOTAL = _get_or_create_counter(
    "modelforge_http_errors_total",
    "Total HTTP error responses (status >= 400)",
    labelnames=("method", "endpoint", "status"),
)

# 2. Inference Metrics (Backend Orchestration Layer)
INFERENCE_REQUESTS_TOTAL = _get_or_create_counter(
    "modelforge_inference_requests_total",
    "Total model inference requests routed by ModelForge backend",
    labelnames=("model", "deployment", "status"),
)

INFERENCE_LATENCY_SECONDS = _get_or_create_histogram(
    "modelforge_inference_latency_seconds",
    "End-to-end inference latency measured by ModelForge backend in seconds",
    labelnames=("model", "deployment"),
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

INFERENCE_ERRORS_TOTAL = _get_or_create_counter(
    "modelforge_inference_errors_total",
    "Total model inference errors observed by ModelForge backend",
    labelnames=("model", "deployment", "error_type"),
)

# 3. Model Deployment Metrics
DEPLOYMENTS_TOTAL = _get_or_create_counter(
    "modelforge_deployments_total",
    "Total model deployment lifecycle events",
    labelnames=("status",),
)

DEPLOYMENT_FAILURES_TOTAL = _get_or_create_counter(
    "modelforge_deployment_failures_total",
    "Total model deployment failures",
    labelnames=("model",),
)

MODEL_LOAD_FAILURES_TOTAL = _get_or_create_counter(
    "modelforge_model_load_failures_total",
    "Total model artifact loading failures",
    labelnames=("model",),
)

ACTIVE_DEPLOYMENTS = _get_or_create_gauge(
    "modelforge_active_deployments",
    "Current number of active model deployments",
)

# 4. Security & Authentication Metrics
AUTH_FAILURES_TOTAL = _get_or_create_counter(
    "modelforge_auth_failures_total",
    "Total authentication and authorization failures",
    labelnames=("reason",),
)

# 5. Storage & Registry Metrics
STORAGE_OPERATIONS_TOTAL = _get_or_create_counter(
    "modelforge_storage_operations_total",
    "Total object storage (MinIO/S3) operations",
    labelnames=("operation", "status"),
)

# Path normalization regexes to avoid high-cardinality label explosions
_UUID_OR_ID_PATTERN = re.compile(
    r"/api/v1/models/([a-zA-Z0-9_\-\.]+)(/predict|/metrics|/versions)?"
)
_DEPLOYMENT_ID_PATTERN = re.compile(
    r"/api/v1/deployments/([a-zA-Z0-9_\-\.]+)(/health|/stop|/metrics)?"
)
_EXPERIMENT_ID_PATTERN = re.compile(
    r"/api/v1/experiments/([a-zA-Z0-9_\-\.]+)"
)


def sanitize_endpoint(path: str) -> str:
    """
    Sanitize endpoint paths to prevent high-cardinality metric labels.
    Replaces arbitrary UUIDs, model IDs, and deployment IDs with static placeholders.
    """
    if not path:
        return "/"
    
    # Model routes
    if path.startswith("/api/v1/models/"):
        m = _UUID_OR_ID_PATTERN.match(path)
        if m:
            sub = m.group(2) or ""
            return f"/api/v1/models/{{model_id}}{sub}"
        return "/api/v1/models/{model_id}"

    # Deployment routes
    if path.startswith("/api/v1/deployments/"):
        m = _DEPLOYMENT_ID_PATTERN.match(path)
        if m:
            sub = m.group(2) or ""
            return f"/api/v1/deployments/{{deployment_id}}{sub}"
        return "/api/v1/deployments/{deployment_id}"

    # Experiment routes
    if path.startswith("/api/v1/experiments/"):
        m = _EXPERIMENT_ID_PATTERN.match(path)
        if m:
            return "/api/v1/experiments/{experiment_id}"

    return path


def get_metrics_content() -> tuple[bytes, str]:
    """Generate latest Prometheus metrics text and return with content-type."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
