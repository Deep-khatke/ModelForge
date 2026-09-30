"""
Authentication router: registration, login, logout, and current user profile.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_client_ip, get_current_user
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserCreate, UserOut
from app.services.audit_service import log_audit_event
from app.services.auth_service import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> UserOut:
    """
    Register a new user account.
    Allowed only if ALLOW_PUBLIC_REGISTRATION=true or if this is the first user registered.
    """
    ip = get_client_ip(request)
    existing_user_count = db.scalar(select(User).limit(1))

    if not settings.allow_public_registration and existing_user_count is not None:
        log_audit_event(
            db,
            action="USER_REGISTRATION_REJECTED",
            resource_type="auth",
            details={"email": payload.email, "reason": "public_registration_disabled"},
            ip_address=ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Contact an administrator to create an account.",
        )

    clean_email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email address already exists",
        )

    # First registered user becomes ADMIN if no users exist
    assigned_role = "ADMIN" if existing_user_count is None else payload.role

    user = User(
        email=clean_email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=assigned_role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_audit_event(
        db,
        action="USER_REGISTERED",
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        user_email=user.email,
        details={"email": user.email, "role": user.role},
        ip_address=ip,
        success=True,
    )

    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email and password to receive a JWT access token."""
    ip = get_client_ip(request)
    clean_email = payload.email.strip().lower()

    user = db.scalar(select(User).where(User.email == clean_email))
    if user is None or not verify_password(payload.password, user.password_hash):
        log_audit_event(
            db,
            action="LOGIN_FAILED",
            resource_type="auth",
            user_id=user.id if user else None,
            user_email=clean_email,
            details={"attempted_email": clean_email, "reason": "invalid_credentials"},
            ip_address=ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        log_audit_event(
            db,
            action="LOGIN_FAILED",
            resource_type="auth",
            user_id=user.id,
            user_email=user.email,
            details={"reason": "account_inactive"},
            ip_address=ip,
            success=False,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact an administrator.",
        )

    # Update last login time
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(user_id=user.id, email=user.email, role=user.role)

    log_audit_event(
        db,
        action="LOGIN_SUCCEEDED",
        resource_type="auth",
        user_id=user.id,
        user_email=user.email,
        details={"role": user.role},
        ip_address=ip,
        success=True,
    )

    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserOut.model_validate(user),
    )


@router.post("/logout")
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Logs a logout audit record. Client discards its local bearer token."""
    ip = get_client_ip(request)
    log_audit_event(
        db,
        action="LOGOUT",
        resource_type="auth",
        user_id=current_user.id,
        user_email=current_user.email,
        ip_address=ip,
        success=True,
    )
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserOut:
    """Return the profile and permissions of the currently authenticated user."""
    return UserOut.model_validate(current_user)
