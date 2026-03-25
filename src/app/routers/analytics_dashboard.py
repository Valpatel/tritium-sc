# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Analytics dashboard widget API.

Serves pre-configured and operator-customized dashboard widget
definitions. Operators can GET the default widget set, POST to
save a custom layout, and PUT to update individual widgets.

Endpoints:
    GET  /api/analytics/widgets        — list all dashboard widgets
    POST /api/analytics/widgets/layout — save a custom widget layout
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from tritium_lib.models.analytics_dashboard import (
    DEFAULT_WIDGETS,
    DashboardWidget,
    WidgetConfig,
    WidgetType,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

# In-memory custom layouts per operator session (keyed by operator_id)
_custom_layouts: dict[str, list[dict]] = {}


@router.get("/widgets")
async def get_analytics_widgets(
    request: Request,
    operator_id: Optional[str] = None,
):
    """Return dashboard widget definitions.

    If operator_id is provided and they have a saved custom layout,
    return that. Otherwise return the default widget set.
    """
    if operator_id and operator_id in _custom_layouts:
        widgets = _custom_layouts[operator_id]
    else:
        widgets = [w.to_dict() for w in DEFAULT_WIDGETS]

    return JSONResponse(content={
        "widgets": widgets,
        "count": len(widgets),
        "is_custom": bool(operator_id and operator_id in _custom_layouts),
        "generated_at": time.time(),
    })


@router.post("/widgets/layout")
async def save_widget_layout(request: Request):
    """Save a custom widget layout for an operator.

    Body JSON:
        operator_id: str — operator identifier
        widgets: list[dict] — widget definitions with positions
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
    operator_id = body.get("operator_id", "default")
    widgets_data = body.get("widgets", [])

    # Validate each widget can be deserialized
    validated = []
    for wd in widgets_data:
        try:
            w = DashboardWidget.from_dict(wd)
            validated.append(w.to_dict())
        except Exception:
            # Skip invalid widgets silently
            continue

    _custom_layouts[operator_id] = validated

    return JSONResponse(content={
        "status": "saved",
        "operator_id": operator_id,
        "widget_count": len(validated),
        "saved_at": time.time(),
    })
