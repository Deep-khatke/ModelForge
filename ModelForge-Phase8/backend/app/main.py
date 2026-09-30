"""ModelForge backend - FastAPI application entrypoint (Phase 2)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import SessionLocal, init_db
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
    start_autoscaling_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_autoscaling_scheduler()


@app.get("/api/health", tags=["health"])
def api_health() -> dict[str, str]:
    return {"status": "healthy"}


app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(audit_router.router)
app.include_router(models_router.router)
app.include_router(deployments_router.router)
app.include_router(autoscaling_router.router)
app.include_router(monitoring_router.router)
app.include_router(experiments_router.router)

