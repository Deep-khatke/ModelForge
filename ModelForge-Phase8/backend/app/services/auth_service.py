"""
Authentication and security service.

Provides password hashing via bcrypt, JWT access token issuance/validation,
and initial administrator bootstrapping.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    pw_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(
    user_id: str | dict[str, Any] = "",
    email: str = "",
    role: str = "VIEWER",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    if isinstance(user_id, dict):
        payload: dict[str, Any] = dict(user_id)
        if "id" in payload and "sub" not in payload:
            payload["sub"] = str(payload["id"])
        payload.setdefault("iat", int(now.timestamp()))
        payload.setdefault("exp", int(expire.timestamp()))
    else:
        payload = {
            "sub": str(user_id),
            "email": email,
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, raise_exceptions: bool = True) -> dict[str, Any] | None:
    """
    Decode and validate a JWT access token.
    Raises HTTPException(401) on failure, expiry, or signature mismatch if raise_exceptions is True,
    otherwise returns None.
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except jwt.ExpiredSignatureError:
        if raise_exceptions:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Access token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None
    except jwt.InvalidTokenError:
        if raise_exceptions:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


def bootstrap_initial_admin(db: Session) -> User | None:
    """
    Ensures an initial administrator account exists when authentication is enabled.
    Called during application startup.
    """
    if not settings.auth_enabled:
        return None

    # Check if admin user or any user exists
    existing_admin = db.scalar(
        select(User).where(User.email == settings.initial_admin_email.strip().lower())
    )
    if existing_admin is not None:
        return existing_admin

    user_count = db.scalar(select(User).limit(1))
    if user_count is not None and not settings.initial_admin_email:
        return None

    admin_user = User(
        email=settings.initial_admin_email.strip().lower(),
        display_name=settings.initial_admin_name,
        password_hash=hash_password(settings.initial_admin_password),
        role="ADMIN",
        is_active=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    logger.info("Bootstrapped initial administrator account: %s", admin_user.email)
    return admin_user
