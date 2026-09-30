"""
User management router (ADMIN only): list, create, update, and deactivate users.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_client_ip, require_roles
from app.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
from app.services.audit_service import log_audit_event
from app.services.auth_service import hash_password

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    """List all registered users (ADMIN only)."""
    users = list(db.scalars(select(User).order_by(User.created_at.asc())).all())
    return [UserOut.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: str,
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> UserOut:
    """Get a single user by ID (ADMIN only)."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )
    return UserOut.model_validate(user)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> UserOut:
    """Create a new user account (ADMIN only)."""
    ip = get_client_ip(request)
    clean_email = payload.email.strip().lower()

    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with email '{clean_email}' already exists",
        )

    user = User(
        email=clean_email,
        display_name=payload.display_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    log_audit_event(
        db,
        action="USER_CREATED",
        resource_type="user",
        resource_id=user.id,
        user_id=admin_user.id,
        user_email=admin_user.email,
        details={"created_email": user.email, "role": user.role},
        ip_address=ip,
        success=True,
    )

    return UserOut.model_validate(user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    request: Request,
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> UserOut:
    """Update user role, active status, display name, or password (ADMIN only)."""
    ip = get_client_ip(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )

    # Prevent admin from deactivating themselves
    if user.id == admin_user.id and payload.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot deactivate their own account",
        )

    # Prevent admin from removing their own admin role
    if user.id == admin_user.id and payload.role is not None and payload.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Administrators cannot revoke their own administrator role",
        )

    changes: dict[str, str | bool] = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
        changes["display_name"] = user.display_name
    if payload.role is not None:
        user.role = payload.role
        changes["role"] = user.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = user.is_active
    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
        changes["password_reset"] = True

    db.commit()
    db.refresh(user)

    log_audit_event(
        db,
        action="USER_UPDATED",
        resource_type="user",
        resource_id=user.id,
        user_id=admin_user.id,
        user_email=admin_user.email,
        details=changes,
        ip_address=ip,
        success=True,
    )

    return UserOut.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_user(
    user_id: str,
    request: Request,
    admin_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a user account permanently (ADMIN only)."""
    ip = get_client_ip(request)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{user_id}' not found",
        )

    if user.id == admin_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    user_email = user.email
    db.delete(user)
    db.commit()

    log_audit_event(
        db,
        action="USER_DELETED",
        resource_type="user",
        resource_id=user_id,
        user_id=admin_user.id,
        user_email=admin_user.email,
        details={"deleted_email": user_email},
        ip_address=ip,
        success=True,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
