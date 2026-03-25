# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Path parameter sanitization for API routes.

Prevents path traversal attacks by validating user-supplied path
components before they reach filesystem operations.
"""

from __future__ import annotations

import re

from fastapi import HTTPException


# Only allow alphanumeric, hyphen, underscore, dot (no leading dot)
_SAFE_PATH_PARAM = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def sanitize_path_param(value: str, name: str = "parameter") -> str:
    """Validate a single path component from a URL parameter.

    Rejects values that contain:
    - ``..`` (parent directory traversal)
    - Absolute paths (starting with ``/``)
    - Null bytes
    - Characters outside ``[a-zA-Z0-9._-]``

    Parameters
    ----------
    value:
        The raw path parameter from the request.
    name:
        Human-readable name for error messages.

    Returns
    -------
    str
        The validated value, unchanged.

    Raises
    ------
    HTTPException (400)
        If the value fails any check.
    """
    if not value:
        raise HTTPException(status_code=400, detail=f"Empty {name}")

    if "\x00" in value:
        raise HTTPException(status_code=400, detail=f"Invalid {name}")

    if ".." in value:
        raise HTTPException(status_code=400, detail=f"Invalid {name}")

    if value.startswith("/"):
        raise HTTPException(status_code=400, detail=f"Invalid {name}")

    if not _SAFE_PATH_PARAM.match(value):
        raise HTTPException(status_code=400, detail=f"Invalid {name}")

    return value
