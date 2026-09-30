"""
Firestore helper functions and collection references.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.services.firebase.client import get_firestore_client

logger = logging.getLogger("modelforge.firestore")


def get_db_client():
    """Retrieve the Firestore client or raise an exception if unavailable."""
    client = get_firestore_client()
    if client is None:
        raise RuntimeError(
            "Firestore is not available. Please verify Firebase credentials or check that "
            "FIREBASE_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS are set correctly."
        )
    return client


def to_firestore_data(data: dict[str, Any]) -> dict[str, Any]:
    """Convert Python datatypes (e.g. datetimes) into Firestore-compatible values."""
    converted = {}
    for k, v in data.items():
        if isinstance(v, datetime):
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            converted[k] = v
        elif isinstance(v, dict):
            converted[k] = to_firestore_data(v)
        elif isinstance(v, list):
            converted[k] = [to_firestore_data(item) if isinstance(item, dict) else item for item in v]
        elif v is not None:
            converted[k] = v
    return converted


def from_firestore_doc(doc: Any) -> dict[str, Any] | None:
    """Convert Firestore DocumentSnapshot into Python dictionary with document ID."""
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    data["id"] = doc.id

    # Normalize timestamps to Python UTC datetime
    for k, v in list(data.items()):
        # Firestore returns Timestamp objects with a date()/to_datetime() method
        if hasattr(v, "to_datetime"):
            data[k] = v.to_datetime()
        elif hasattr(v, "isoformat") and not isinstance(v, datetime):
            try:
                data[k] = datetime.fromisoformat(str(v))
            except Exception:
                pass
    return data
