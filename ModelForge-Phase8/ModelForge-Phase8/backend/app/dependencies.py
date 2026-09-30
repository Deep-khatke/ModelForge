"""
Reusable FastAPI dependency providers for authentication, role authorization, and request metadata.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from datetime import datetime, timezone
from app.services.auth_service import decode_access_token

# auto_error=False lets us handle missing tokens gracefully and support AUTH_ENABLED=false
http_bearer = HTTPBearer(auto_error=False)

# Reusable local development user when AUTH_ENABLED=false
_DEV_ADMIN_USER = User(
    id="dev-admin",
    email="dev-admin@modelforge.local",
    display_name="Development Local Admin",
    password_hash="",
    role="ADMIN",
    is_active=True,
    created_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    Validates bearer token and returns active User instance.
    If AUTH_ENABLED=false, transparently returns a development local administrator.
    """
    if not settings.auth_enabled:
        return _DEV_ADMIN_USER

    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated",
        )

    return user


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    """
    Dependency factory that checks if the authenticated user has one of the allowed roles.
    Raises HTTP 403 Forbidden if not permitted.
    """
    def _role_checker(user: User = Depends(get_current_user)) -> User:
        if not settings.auth_enabled:
            return user

        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access forbidden: requires one of {allowed_roles}, "
                    f"but user role is '{user.role}'"
                ),
            )
        return user

    return _role_checker


def get_client_ip(request: Request) -> str | None:
    """Extract client IP address from proxy headers or socket connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None
