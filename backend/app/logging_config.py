"""
ModelForge Backend - Structured JSON Logging Configuration (Phase 14).
Outputs uniform, parseable JSON logs with contextual request_id, service name,
log level, timestamp, and sensitive field redaction.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

# Sensitive keys to redact
SENSITIVE_PATTERNS = {
    "password",
    "token",
    "access_token",
    "jwt_secret_key",
    "secret",
    "authorization",
    "private_key",
    "credentials",
    "api_key",
}


def redact_sensitive_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and token values from logs."""
    if isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            if any(s in k.lower() for s in SENSITIVE_PATTERNS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    elif isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]
    return data


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def __init__(self, service_name: str = "backend"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        # Generate ISO8601 timestamp in UTC
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        
        # Build base structured dictionary
        log_entry: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include request_id if present
        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = str(request_id)

        # Include event if present
        event = getattr(record, "event", None)
        if event:
            log_entry["event"] = str(event)

        # Include any custom attributes in extra
        for key in ("endpoint", "method", "status_code", "latency_ms", "model", "deployment", "error"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        # Include exception trace if available
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Ensure sensitive values are not leaked
        cleaned_entry = redact_sensitive_data(log_entry)
        return json.dumps(cleaned_entry, ensure_ascii=False)


def setup_structured_logging(service_name: str = "backend") -> logging.Logger:
    """Configure root logger with structured JSON handler and configured log level."""
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level_str, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Avoid duplicate handlers
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
    stream_handler.setLevel(level)
    root_logger.addHandler(stream_handler)

    # Also adjust uvicorn loggers to avoid duplicate unformatted noise
    for uvi_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvi_logger = logging.getLogger(uvi_logger_name)
        uvi_logger.handlers = []
        uvi_logger.propagate = True

    logger = logging.getLogger(service_name)
    logger.info("Structured JSON logging initialized", extra={"event": "startup", "log_level": log_level_str})
    return logger
