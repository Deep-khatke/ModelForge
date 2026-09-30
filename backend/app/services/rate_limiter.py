"""
ModelForge Phase 13: In-Memory Sliding Window Rate Limiter & Abuse Protection.

Provides lightweight, robust rate-limiting for sensitive endpoints such as:
- /api/v1/auth/login (Credential brute force protection)
- /api/v1/models/upload (Resource exhaustion protection)
- /api/v1/deployments (Denial-of-Service / quota protection)
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from fastapi import HTTPException, Request, status

logger = logging.getLogger("modelforge.rate_limiter")


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter."""

    def __init__(self):
        self._lock = threading.Lock()
        # Key: (client_ip, endpoint_bucket) -> List[timestamp]
        self._history: Dict[Tuple[str, str], List[float]] = defaultdict(list)
        # Default endpoint rate limits: (max_requests, window_seconds)
        self._rules: Dict[str, Tuple[int, int]] = {
            "auth": (15, 60),      # 15 login attempts per minute per IP
            "upload": (30, 60),    # 30 model uploads per minute per IP
            "deploy": (45, 60),    # 45 deployment actions per minute per IP
            "general": (300, 60),  # 300 requests per minute general
        }

    def check_rate_limit(self, client_ip: str, bucket: str = "general") -> None:
        """
        Check and record an access attempt.
        Raises HTTP 429 Too Many Requests if rate limit is exceeded.
        """
        now = time.time()
        max_requests, window_seconds = self._rules.get(bucket, self._rules["general"])
        window_start = now - window_seconds

        with self._lock:
            key = (client_ip, bucket)
            timestamps = self._history[key]
            # Prune timestamps older than window_start
            valid_timestamps = [t for t in timestamps if t > window_start]
            self._history[key] = valid_timestamps

            if len(valid_timestamps) >= max_requests:
                oldest_in_window = valid_timestamps[0]
                retry_after = int(max(1, (oldest_in_window + window_seconds) - now))
                logger.warning(
                    "Rate limit exceeded for IP %s on bucket '%s' (%d/%d in %ds). Retry-After: %ds",
                    client_ip, bucket, len(valid_timestamps), max_requests, window_seconds, retry_after
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded for {bucket}. Please retry in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

            self._history[key].append(now)

    def reset(self) -> None:
        """Clear all rate limit history (useful for testing)."""
        with self._lock:
            self._history.clear()


# Global singleton instance
rate_limiter = SlidingWindowRateLimiter()
