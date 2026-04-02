# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Testing API router — run tests and view reports.

GET  /api/testing/report  — latest test report
POST /api/testing/run     — trigger a test run and return results
GET  /api/testing/html    — latest report as HTML
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from engine.testing.report_generator import TestReportGenerator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/testing", tags=["testing"])

_generator = TestReportGenerator()

# Guard against concurrent runs
_run_lock = asyncio.Lock()
_running = False


@router.get("/report")
async def get_latest_report() -> JSONResponse:
    """Return the latest test report JSON."""
    report = _generator.latest()
    if report is None:
        return JSONResponse(
            {"error": "No test report available. POST /api/testing/run to generate one."},
            status_code=404,
        )
    return JSONResponse(report)


@router.post("/run")
async def trigger_test_run() -> JSONResponse:
    """Trigger a test run across all sub-projects.

    Runs synchronously in a thread pool to avoid blocking the event loop.
    Returns the full report on completion.
    """
    global _running
    if _running:
        return JSONResponse(
            {"error": "A test run is already in progress."},
            status_code=409,
        )

    _running = True
    try:
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, _generator.run)
        return JSONResponse(report)
    except Exception as exc:
        logger.exception("Test run failed: %s", exc)
        return JSONResponse(
            {"error": f"Test run failed: {exc}"},
            status_code=500,
        )
    finally:
        _running = False


@router.get("/html")
async def get_latest_html() -> HTMLResponse:
    """Return the latest test report rendered as HTML."""
    report = _generator.latest()
    if report is None:
        return HTMLResponse(
            "<h1>No report available</h1><p>POST /api/testing/run first.</p>",
            status_code=404,
        )
    html = _generator.generate_html(report)
    return HTMLResponse(html)
