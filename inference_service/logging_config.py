"""
ModelForge Inference Service - Structured JSON Logging Configuration (Phase 14).
Outputs single-line JSON log events for container log collection by Promtail / Loki.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

SENSITIVE_PATTERNS = {"password", "token", "access_token", "secret", "authorization", "credentials"}


def redact_sensitive_data(data: Any) -> Any:
    """Scrub sensitive keys and credential values from logs."""
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
    """Formats log records as uniform, parseable JSON lines."""

    def __init__(self, service_name: str = "model-server"):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        log_entry: dict[str, Any] = {
            "timestamp": ts,
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }

        request_id = getattr(record, "request_id", None)
        if request_id:
            log_entry["request_id"] = str(request_id)

        event = getattr(record, "event", None)
        if event:
            log_entry["event"] = str(event)

        for key in ("endpoint", "method", "status_code", "latency_ms", "model", "replica_id", "error"):
            val = getattr(record, key, None)
            if val is not None:
                log_entry[key] = val

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        cleaned_entry = redact_sensitive_data(log_entry)
        return json.dumps(cleaned_entry, ensure_ascii=False)


def setup_structured_logging(service_name: str = "model-server") -> logging.Logger:
    """Configure logger with structured JSON formatting and LOG_LEVEL environment control."""
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, log_level_str, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(StructuredJsonFormatter(service_name=service_name))
    stream_handler.setLevel(level)
    root_logger.addHandler(stream_handler)

    for uvi_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvi_logger = logging.getLogger(uvi_logger_name)
        uvi_logger.handlers = []
        uvi_logger.propagate = True

    logger = logging.getLogger(service_name)
    logger.info("Model server structured logging initialized", extra={"event": "startup", "log_level": log_level_str})
    return logger
