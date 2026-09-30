"""
ModelForge Inference Service.

Reusable, standalone microservice running inside an isolated Docker container for
a single model replica. Exposes /health and /predict endpoints, measures real
inference latency, and never exposes host paths, secrets, or environment details.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

# Read container configuration from environment
MODEL_PATH = os.getenv("MODEL_PATH", "/models/model.joblib")
REPLICA_ID = os.getenv("REPLICA_ID", "replica_default")
DEPLOYMENT_ID = os.getenv("DEPLOYMENT_ID", "deployment_default")
MODEL_ID = os.getenv("MODEL_ID", "model_default")
MODEL_VERSION = os.getenv("MODEL_VERSION", "v1")

app = FastAPI(
    title=f"ModelForge Replica - {REPLICA_ID}",
    version="0.1.0",
    description="Containerized inference microservice for ModelForge",
    docs_url=None,  # Disable docs in production replica containers for security
    redoc_url=None,
    openapi_url=None,
)

# Global model holder
_loaded_model: Any = None
_model_load_error: str | None = None


def load_model() -> bool:
    """Load the model artifact safely."""
    global _loaded_model, _model_load_error
    path = Path(MODEL_PATH)
    if not path.exists():
        _model_load_error = "Model file does not exist"
        return False

    try:
        model = joblib.load(path)
        if not hasattr(model, "predict"):
            _model_load_error = "Model object missing predict() method"
            return False
        _loaded_model = model
        _model_load_error = None
        return True
    except Exception:
        _model_load_error = "Failed to load model artifact"
        return False


@app.on_event("startup")
def on_startup():
    load_model()


class PredictRequest(BaseModel):
    features: list[Any] = Field(..., description="1D or 2D numerical feature array")


class PredictResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_id: str
    version: str
    replica_id: str
    predictions: list[Any]
    probabilities: list[Any] | None = None
    inference_time_ms: float


class HealthResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    status: str
    replica_id: str
    model_id: str
    model_version: str


@app.get("/health", response_model=HealthResponse)
def health_check():
    """Health check endpoint confirming model readiness."""
    global _loaded_model
    if _loaded_model is None:
        # Retry loading if startup load had an issue
        success = load_model()
        if not success:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"status": "unhealthy", "error": "Model not ready"},
            )

    return HealthResponse(
        status="healthy",
        replica_id=REPLICA_ID,
        model_id=MODEL_ID,
        model_version=MODEL_VERSION,
    )


@app.post("/predict", response_model=PredictResponse)
def predict(payload: PredictRequest):
    """Execute model prediction and measure latency."""
    global _loaded_model
    if _loaded_model is None:
        if not load_model():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Inference service model is unavailable",
            )

    features = payload.features
    if not features:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features array cannot be empty",
        )

    try:
        X = np.array(features)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features must be a valid numerical array",
        )

    if X.size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features array cannot be empty",
        )

    if X.ndim == 1:
        X = X.reshape(1, -1)
    elif X.ndim > 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Features must be a 1D or 2D array",
        )

    start_time = time.perf_counter()
    try:
        raw_predictions = _loaded_model.predict(X)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Inference execution failed: {type(exc).__name__}",
        )

    probabilities = None
    if hasattr(_loaded_model, "predict_proba") and callable(getattr(_loaded_model, "predict_proba")):
        try:
            raw_proba = _loaded_model.predict_proba(X)
            if raw_proba is not None:
                probabilities = raw_proba.tolist()
        except Exception:
            probabilities = None

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 3)

    predictions = (
        raw_predictions.tolist() if hasattr(raw_predictions, "tolist") else list(raw_predictions)
    )

    return PredictResponse(
        model_id=MODEL_ID,
        version=MODEL_VERSION,
        replica_id=REPLICA_ID,
        predictions=predictions,
        probabilities=probabilities,
        inference_time_ms=elapsed_ms,
    )
