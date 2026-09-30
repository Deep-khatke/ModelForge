"""
Model registry endpoints: upload, list, and retrieve models/versions.

Deployment, inference, and monitoring endpoints are intentionally NOT part
of Phase 1 - see the project README for the phased roadmap.
"""
from __future__ import annotations

import time
from pathlib import Path

import joblib
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import (
    get_client_ip,
    get_current_user,
    require_roles,
    verify_resource_ownership,
)
from app.model_inspector import inspect_joblib_model
from app.models import Model, ModelVersion, User
from app.replica_manager import cleanup_deployment_containers, execute_predict_with_load_balancer
from app.schemas import ModelOut, PredictRequest, PredictResponse
from app.services.audit_service import log_audit_event
from app.services.storage.factory import get_artifact_store
from app.utils import next_version_label, safe_filename

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.post("/upload", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def upload_model(
    request: Request,
    model_name: str = Form(..., description="Logical model name, e.g. 'fraud_detector'"),
    framework: str = Form("sklearn", description="ML framework the artifact was trained with"),
    file: UploadFile = File(..., description="Trained model artifact (.joblib)"),
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> ModelOut:
    """
    Upload a trained model artifact.

    - If `model_name` does not exist yet, a new Model is created and this
      upload becomes its "v1" (and is marked active).
    - If `model_name` already exists, this upload becomes the next version
      (v2, v3, ...) without touching any previously uploaded artifact.
    """
    # --- Validate file extension -----------------------------------------
    original_name = file.filename or "model.joblib"
    extension = Path(original_name).suffix.lower()
    if extension not in settings.allowed_extensions_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file extension '{extension}'. "
                f"Allowed: {', '.join(settings.allowed_extensions_list)}"
            ),
        )

    # --- Validate model_name -----------------------------------------------
    model_name = model_name.strip()
    if not model_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="model_name is required")

    # --- Read upload into memory, enforcing the size limit ---------------
    contents = await file.read()
    if len(contents) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(contents) > settings.max_upload_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.max_upload_size_mb}MB upload limit",
        )

    # --- Find or create the logical Model -----------------------------
    model = db.scalar(select(Model).where(Model.name == model_name))
    is_new_model = model is None
    if model is None:
        model = Model(name=model_name, owner_id=current_user.id if current_user else None)
        db.add(model)
        db.flush()  # populate model.id without committing yet
    else:
        verify_resource_ownership(model.owner_id, current_user, "model")

    existing_versions = [v.version for v in model.versions]
    version_label = next_version_label(existing_versions)

    # --- Persist the artifact using storage abstraction (Local or MinIO/S3) -----
    store = get_artifact_store()
    try:
        stored_name, artifact_uri, file_size = store.upload_model(
            model_id=model.id,
            version_label=version_label,
            filename=original_name,
            contents=contents,
            user_id=current_user.id if current_user else "default_user",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded file: {exc}",
        ) from exc

    # Ensure local path is available for inspection
    local_path = settings.model_storage_path / model.id / version_label / stored_name
    if not local_path.exists():
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(contents)

    # --- Inspect the artifact for basic metadata --------------------------
    inspection = inspect_joblib_model(local_path)
    if not inspection.ok:
        store.delete_model(artifact_uri)
        local_path.unlink(missing_ok=True)
        if is_new_model:
            db.expunge(model)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=inspection.error or "Uploaded file is not a valid model artifact",
        )

    # --- Create the version row --------------------------------------------
    version = ModelVersion(
        model_id=model.id,
        version=version_label,
        framework=framework,
        model_type=inspection.model_type,
        supports_proba=inspection.supports_proba,
        original_filename=original_name,
        stored_filename=stored_name,
        file_path=str(artifact_uri),
        file_size_bytes=file_size,
        status="uploaded",
        is_active=is_new_model,  # first version of a new model is active by default
    )
    db.add(version)
    db.commit()
    db.refresh(model)

    log_audit_event(
        db,
        action="MODEL_UPLOADED",
        resource_type="model",
        resource_id=model.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={
            "model_name": model.name,
            "version": version_label,
            "framework": framework,
            "file_size_bytes": len(contents),
        },
        ip_address=get_client_ip(request),
        success=True,
    )

    return model


@router.get("", response_model=list[ModelOut])
def list_models(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ModelOut]:
    """List every registered logical model, each with all of its versions."""
    # order_by defined on the relationship (see models.py) keeps versions
    # sorted oldest -> newest for each model.
    return list(db.scalars(select(Model).order_by(Model.created_at)).all())


@router.get("/{model_id}", response_model=ModelOut)
def get_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ModelOut:
    """Retrieve a single logical model with all of its versions."""
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")
    verify_resource_ownership(model.owner_id, current_user, "model")
    return model


@router.post("/{model_id}/versions/{version}/activate", response_model=ModelOut)
def activate_version(
    model_id: str,
    version: str,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> ModelOut:
    """Mark a specific version as the active one for this model."""
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")
    verify_resource_ownership(model.owner_id, current_user, "model")

    target = next((v for v in model.versions if v.version == version), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version '{version}' not found for model '{model_id}'",
        )

    for v in model.versions:
        v.is_active = v.id == target.id
    db.commit()
    db.refresh(model)

    log_audit_event(
        db,
        action="MODEL_VERSION_ACTIVATED",
        resource_type="model",
        resource_id=model.id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={"model_name": model.name, "activated_version": version},
        ip_address=get_client_ip(request),
        success=True,
    )

    return model


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_model(
    model_id: str,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN", "OPERATOR")),
    db: Session = Depends(get_db),
) -> None:
    """Delete a logical model, all of its versions, and their files on disk."""
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")
    verify_resource_ownership(model.owner_id, current_user, "model")

    model_name = model.name
    for d in model.deployments:
        cleanup_deployment_containers(db, d)

    store = get_artifact_store()
    for v in model.versions:
        store.delete_model(v.file_path)
    model_dir = settings.model_storage_path / model.id
    if model_dir.exists():
        for child in sorted(model_dir.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink(missing_ok=True)
            else:
                child.rmdir()
        model_dir.rmdir()

    db.delete(model)
    db.commit()

    log_audit_event(
        db,
        action="MODEL_DELETED",
        resource_type="model",
        resource_id=model_id,
        user_id=current_user.id,
        user_email=current_user.email,
        details={"deleted_model_name": model_name},
        ip_address=get_client_ip(request),
        success=True,
    )


@router.post("/{model_id}/predict", response_model=PredictResponse)
def predict_model(
    model_id: str,
    payload: PredictRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PredictResponse:
    """
    Run real inference using the currently running deployment of a model,
    routed through the Round-Robin Load Balancer across active healthy replicas.
    """
    model = db.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")

    deployment = model.current_deployment
    if deployment is None or deployment.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model '{model_id}' does not have a running deployment",
        )

    target_version = deployment.model_version
    if target_version is None:
        target_version = next((v for v in model.versions if v.id == deployment.model_version_id), None)

    store = get_artifact_store()
    if target_version is None or not store.model_exists(target_version.file_path):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Model artifact file is missing from storage",
        )

    req_id = getattr(request.state, "request_id", None)
    return execute_predict_with_load_balancer(
        db, deployment, model.name, target_version, payload.features, request_id=req_id
    )
