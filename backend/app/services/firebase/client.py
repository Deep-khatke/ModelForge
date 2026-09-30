"""
Thread-safe Firebase Admin SDK initialization and client provider.

Supports explicit credential paths, GOOGLE_APPLICATION_CREDENTIALS environment variable,
and graceful fallback when Firebase is not yet configured.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("modelforge.firebase")

_firebase_app: Any = None
_firestore_client: Any = None
_initialization_attempted = False
_initialization_error: str | None = None


def get_firebase_credentials_path() -> Path | None:
    """Resolve the local path to the Firebase service account credential JSON file."""
    # 1. Direct config setting
    if settings.firebase_credentials_path:
        p = Path(settings.firebase_credentials_path).resolve()
        if p.is_file():
            return p
        logger.warning("Configured firebase_credentials_path does not exist: %s", p)

    # 2. Standard Google Cloud environment variable or settings
    g_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or settings.google_application_credentials
    if g_creds:
        p = Path(g_creds).resolve()
        if p.is_file():
            return p
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS path does not exist: %s", p)

    # 3. Conventional local file in backend directory (if present and gitignored)
    local_p = Path("firebase-credentials.json").resolve()
    if local_p.is_file():
        return local_p

    return None


def initialize_firebase() -> bool:
    """
    Safely initialize the Firebase Admin SDK if not already initialized.
    Returns True if successfully initialized, False otherwise.
    """
    global _firebase_app, _initialization_attempted, _initialization_error

    if _firebase_app is not None:
        return True

    if _initialization_attempted and _initialization_error:
        return False

    _initialization_attempted = True

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Check if already initialized in this process
        try:
            _firebase_app = firebase_admin.get_app()
            logger.info("Found existing Firebase Admin App instance.")
            return True
        except ValueError:
            pass  # Not yet initialized

        cred_path = get_firebase_credentials_path()
        cred = None
        options: dict[str, Any] = {}

        if settings.firebase_project_id:
            options["projectId"] = settings.firebase_project_id

        if cred_path:
            logger.info("Initializing Firebase Admin SDK using credential file: %s", cred_path)
            cred = credentials.Certificate(str(cred_path))
        elif settings.firebase_project_id and (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GCLOUD_PROJECT")):
            try:
                cred = credentials.ApplicationDefault()
                logger.info("Using Application Default Credentials for Firebase.")
            except Exception:
                cred = None
        else:
            _initialization_error = "No Firebase credentials or project ID configured."
            logger.debug(_initialization_error)
            return False

        if cred is None:
            _initialization_error = "Could not resolve valid Firebase credentials."
            logger.debug(_initialization_error)
            return False

        _firebase_app = firebase_admin.initialize_app(cred, options=options if options else None)
        logger.info("Firebase Admin SDK successfully initialized.")
        return True

    except ImportError:
        _initialization_error = "firebase_admin package is not installed."
        logger.warning(_initialization_error)
        return False
    except Exception as exc:
        _initialization_error = f"Firebase initialization failed: {exc}"
        logger.warning(_initialization_error)
        return False


def is_firebase_available() -> bool:
    """Check if Firebase Admin SDK is initialized and accessible."""
    return initialize_firebase()


def get_firestore_client() -> Any | None:
    """Get Firestore client instance, or None if Firebase is unavailable."""
    global _firestore_client
    if _firestore_client is not None:
        return _firestore_client

    if not initialize_firebase():
        return None

    try:
        from firebase_admin import firestore
        _firestore_client = firestore.client()
        return _firestore_client
    except Exception as exc:
        logger.warning("Failed to obtain Firestore client: %s", exc)
        return None


def get_firebase_status() -> dict[str, Any]:
    """Get human-readable diagnostics of Firebase connectivity."""
    cred_path = get_firebase_credentials_path()
    is_init = initialize_firebase()
    return {
        "initialized": is_init,
        "project_id": settings.firebase_project_id or "Not configured",
        "credentials_path": str(cred_path) if cred_path else "Not found",
        "credentials_configured": cred_path is not None,
        "error": _initialization_error if not is_init else None,
    }
