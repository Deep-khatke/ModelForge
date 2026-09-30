"""
Firebase Authentication service for token verification and user claim management.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status

from app.services.firebase.client import initialize_firebase

logger = logging.getLogger("modelforge.firebase_auth")


def verify_firebase_id_token(token: str) -> dict[str, Any]:
    """
    Verify a Firebase ID token using the Firebase Admin SDK.
    Raises HTTPException(401) on invalid or expired token.
    Returns decoded token dictionary containing 'uid', 'email', etc.
    """
    if not initialize_firebase():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Authentication service is not initialized on the server.",
        )

    try:
        from firebase_admin import auth
        # check_revoked=True provides extra security
        decoded = auth.verify_id_token(token, check_revoked=False)
        return decoded
    except Exception as exc:
        err_msg = str(exc)
        logger.warning("Firebase token verification failed: %s", err_msg)
        if "expired" in err_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Firebase ID token has expired. Please refresh your session.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Firebase ID token: {err_msg}",
            headers={"WWW-Authenticate": "Bearer"},
        )
