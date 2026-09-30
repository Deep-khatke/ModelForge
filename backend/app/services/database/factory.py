"""
Repository Factory and FastAPI dependencies.

Provides active repository instances based on DATABASE_BACKEND setting ('sqlite' or 'firestore').
"""
from __future__ import annotations

import logging
from typing import Generator

from fastapi import Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.database.firebase_repository import (
    FirestoreAuditRepository,
    FirestoreDeploymentRepository,
    FirestoreModelRepository,
    FirestoreUserRepository,
)
from app.services.database.interface import (
    IAuditRepository,
    IDeploymentRepository,
    IModelRepository,
    IUserRepository,
)
from app.services.database.sqlite_repository import (
    SQLiteAuditRepository,
    SQLiteDeploymentRepository,
    SQLiteModelRepository,
    SQLiteUserRepository,
)
from app.services.firebase.client import is_firebase_available

logger = logging.getLogger("modelforge.db_factory")


def is_firestore_enabled() -> bool:
    """Return True if DATABASE_BACKEND is firestore and Firebase is available."""
    if settings.database_backend.lower() == "firestore":
        if is_firebase_available():
            return True
        logger.warning(
            "DATABASE_BACKEND='firestore' requested, but Firebase is not initialized. "
            "Falling back to SQLite repository."
        )
    return False


# --- FastAPI Dependency Providers --------------------------------------------

def get_model_repository(db: Session = Depends(get_db)) -> IModelRepository:
    """FastAPI dependency for ModelRepository."""
    if is_firestore_enabled():
        return FirestoreModelRepository()
    return SQLiteModelRepository(db)


def get_deployment_repository(db: Session = Depends(get_db)) -> IDeploymentRepository:
    """FastAPI dependency for DeploymentRepository."""
    if is_firestore_enabled():
        return FirestoreDeploymentRepository()
    return SQLiteDeploymentRepository(db)


def get_user_repository(db: Session = Depends(get_db)) -> IUserRepository:
    """FastAPI dependency for UserRepository."""
    if is_firestore_enabled():
        return FirestoreUserRepository()
    return SQLiteUserRepository(db)


def get_audit_repository(db: Session = Depends(get_db)) -> IAuditRepository:
    """FastAPI dependency for AuditRepository."""
    if is_firestore_enabled():
        return FirestoreAuditRepository()
    return SQLiteAuditRepository(db)
