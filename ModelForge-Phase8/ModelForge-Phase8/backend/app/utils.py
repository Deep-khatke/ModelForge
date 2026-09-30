"""Small security/filesystem helpers shared by the routers."""
from __future__ import annotations

import re
from pathlib import Path

_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(filename: str) -> str:
    """
    Reduce a user-supplied filename to a safe, flat basename.

    - Strips any directory components (prevents path traversal such as
      "../../etc/passwd").
    - Replaces anything that is not alphanumeric, dot, dash or underscore.
    """
    name = Path(filename).name  # drop any directory components
    name = _SAFE_CHARS.sub("_", name)
    return name or "model"


def next_version_label(existing_versions: list[str]) -> str:
    """
    Compute the next version label ("v1", "v2", ...) given existing ones.

    Falls back gracefully if versions were ever created out of the usual
    "vN" pattern.
    """
    numbers = []
    for v in existing_versions:
        if v.startswith("v") and v[1:].isdigit():
            numbers.append(int(v[1:]))
    next_number = (max(numbers) + 1) if numbers else 1
    return f"v{next_number}"
