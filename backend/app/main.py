"""ModelForge backend - FastAPI application entrypoint (Phase 2)."""
from __future__ import annotations

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

import time
import uuid

from app.config import settings
from app.database import SessionLocal, init_db
from app.dependencies import get_client_ip
from app.logging_config import setup_structured_logging
from app.metrics import (
    HTTP_ERRORS_TOTAL,
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    get_metrics_content,
    sanitize_endpoint,
)
from app.routers import audit as audit_router
from app.routers import auth as auth_router
from app.routers import autoscaling as autoscaling_router
from app.routers import deployments as deployments_router
from app.routers import experiments as experiments_router
from app.routers import models as models_router
from app.routers import monitoring as monitoring_router
from app.routers import users as users_router
from app.services.auth_service import bootstrap_initial_admin
from app.services.autoscaling_service import (
    start_autoscaling_scheduler,
    stop_autoscaling_scheduler,
)
from app.services.rate_limiter import rate_limiter

# Initialize structured JSON logging (Phase 14)
logger = setup_structured_logging("backend")

app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=(
        "ModelForge API: model upload, registry, multi-replica deployment, "
        "round-robin load balancing, real-time monitoring, auto-scaling, RBAC auth, and audit logging."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observability_and_request_id_middleware(request: Request, call_next):
    """
    Propagate Request ID, collect Prometheus HTTP metrics, and log structured request records.
    """
    raw_req_id = request.headers.get("X-Request-ID")
    request_id = raw_req_id.strip() if raw_req_id else f"req_{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

    start_time = time.perf_counter()
    sanitized_path = sanitize_endpoint(request.url.path)

    # Process request
    try:
        response: Response = await call_next(request)
    except Exception as exc:
        duration = time.perf_counter() - start_time
        status_code = 500
        HTTP_REQUESTS_TOTAL.labels(method=request.method, endpoint=sanitized_path, status=str(status_code)).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, endpoint=sanitized_path, status=str(status_code)).observe(duration)
        HTTP_ERRORS_TOTAL.labels(method=request.method, endpoint=sanitized_path, status=str(status_code)).inc()
        logger.error(
            f"Unhandled exception during request: {exc}",
            exc_info=True,
            extra={
                "event": "http_request_error",
                "request_id": request_id,
                "endpoint": sanitized_path,
                "method": request.method,
                "status_code": status_code,
                "latency_ms": round(duration * 1000, 2),
            },
        )
        raise exc

    duration = time.perf_counter() - start_time
    status_str = str(response.status_code)

    # Record Prometheus metrics
    HTTP_REQUESTS_TOTAL.labels(method=request.method, endpoint=sanitized_path, status=status_str).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=request.method, endpoint=sanitized_path, status=status_str).observe(duration)
    if response.status_code >= 400:
        HTTP_ERRORS_TOTAL.labels(method=request.method, endpoint=sanitized_path, status=status_str).inc()

    # Propagate X-Request-ID in response header
    response.headers["X-Request-ID"] = request_id

    # Emit structured log (avoid noisy logs for /metrics and /api/health unless error)
    if sanitized_path not in ("/metrics", "/api/health") or response.status_code >= 400:
        logger.info(
            "HTTP request completed",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "endpoint": sanitized_path,
                "method": request.method,
                "status_code": response.status_code,
                "latency_ms": round(duration * 1000, 2),
            },
        )

    return response


@app.middleware("http")
async def security_and_rate_limiting_middleware(request: Request, call_next):
    # Apply rate limiting on sensitive API write / auth paths
    path = request.url.path
    if request.method != "OPTIONS" and not path.startswith("/api/health") and path != "/metrics":
        client_ip = get_client_ip(request) or "127.0.0.1"
        if path.startswith("/api/v1/auth/login"):
            rate_limiter.check_rate_limit(client_ip, bucket="auth")
        elif path.startswith("/api/v1/models/upload") and request.method == "POST":
            rate_limiter.check_rate_limit(client_ip, bucket="upload")
        elif path.startswith("/api/v1/deployments") and request.method == "POST":
            rate_limiter.check_rate_limit(client_ip, bucket="deploy")

    response: Response = await call_next(request)

    # Attach Cloud Security & Browser Hardening Headers (Phase 13)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none';"
    return response


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        bootstrap_initial_admin(db)
        from app.services.monitoring_service import cleanup_expired_monitoring_data
        cleanup_expired_monitoring_data(db)
    finally:
        db.close()

    # Attempt safe initialization of Firebase services if configured
    from app.services.firebase.client import initialize_firebase
    initialize_firebase()

    start_autoscaling_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_autoscaling_scheduler()


@app.get("/api/health", tags=["health"])
def api_health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/version", tags=["system"])
@app.get("/api/version", tags=["system"])
def api_version() -> dict[str, str]:
    """ModelForge platform version and build metadata."""
    return {
        "version": settings.api_version,
        "phase": "Phase 15: Infrastructure as Code & CI/CD",
        "service": "modelforge-backend",
        "environment": "local",
        "iac_engine": "OpenTofu",
        "container_runtime": "containerd",
    }


@app.get("/api/health/firebase", tags=["health"])
def firebase_health() -> dict:
    """Check Firebase configuration and connectivity diagnostics."""
    from app.services.firebase.client import get_firebase_status
    return get_firebase_status()


@app.get("/metrics", tags=["monitoring"])
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    content, content_type = get_metrics_content()
    return Response(content=content, media_type=content_type)


app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(audit_router.router)
app.include_router(models_router.router)
app.include_router(deployments_router.router)
app.include_router(autoscaling_router.router)
app.include_router(monitoring_router.router)
app.include_router(experiments_router.router)


