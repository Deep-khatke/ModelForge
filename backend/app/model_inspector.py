"""
Utilities for inspecting an uploaded model artifact to pull out basic
metadata (e.g. the scikit-learn class name, whether it supports
predict_proba).

SECURITY NOTE
-------------
`.joblib` files are backed by Python's `pickle` format. Loading a pickle
file can execute arbitrary code embedded in it. This function is only
ever called on files that a user of THIS platform has explicitly
uploaded through the model registry - it must never be pointed at
artifacts from an untrusted or unknown source. See README.md for the
full trust-boundary discussion.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib


@dataclass
class InspectionResult:
    ok: bool
    model_type: str | None = None
    supports_proba: bool = False
    error: str | None = None


def inspect_joblib_model(path: Path) -> InspectionResult:
    """
    Load a joblib artifact just far enough to record its Python class name
    and whether it exposes predict_proba(). Any failure is reported back
    rather than raised, so upload can still succeed with partial metadata.
    """
    try:
        obj = joblib.load(path)
    except Exception as exc:  # noqa: BLE001 - we want to surface any failure
        return InspectionResult(ok=False, error=f"Could not load model artifact: {exc}")

    model_type = type(obj).__name__
    supports_proba = hasattr(obj, "predict_proba") and callable(getattr(obj, "predict_proba"))

    if not hasattr(obj, "predict"):
        return InspectionResult(
            ok=False,
            model_type=model_type,
            error=(
                f"Uploaded object of type '{model_type}' does not expose a "
                "predict() method, so it cannot be used for inference."
            ),
        )

    return InspectionResult(ok=True, model_type=model_type, supports_proba=supports_proba)
