# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Security status API — one-stop security posture check.

Returns the current security configuration of the system:
auth enabled/disabled, TLS, rate limiting, MQTT auth, CSP headers, CORS config.

Endpoint:
    GET /api/system/security-status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import require_auth
from app.config import settings

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/security-status")
async def security_status(user: dict = Depends(require_auth)):
    """Return the current security posture of the system.

    Requires authentication (when auth is enabled). Returns a summary of
    all security-relevant configuration so operators can verify at a glance
    whether the deployment is hardened.
    """
    # CORS config
    if settings.cors_allowed_origins:
        cors_origins = [
            o.strip()
            for o in settings.cors_allowed_origins.split(",")
            if o.strip()
        ]
        cors_mode = "restricted"
    else:
        cors_origins = ["*"]
        cors_mode = "open"

    # MQTT auth
    mqtt_auth_configured = bool(
        settings.mqtt_username and settings.mqtt_password
    )

    # API keys configured
    api_keys_configured = bool(settings.api_keys)

    # Calculate overall security level
    checks_passed = 0
    checks_total = 6
    if settings.auth_enabled:
        checks_passed += 1
    if settings.tls_enabled:
        checks_passed += 1
    if settings.rate_limit_enabled:
        checks_passed += 1
    if mqtt_auth_configured:
        checks_passed += 1
    if settings.csp_enabled:
        checks_passed += 1
    if cors_mode == "restricted":
        checks_passed += 1

    if checks_passed >= 5:
        overall = "hardened"
    elif checks_passed >= 3:
        overall = "moderate"
    elif checks_passed >= 1:
        overall = "minimal"
    else:
        overall = "open"

    return {
        "overall": overall,
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "auth": {
            "enabled": settings.auth_enabled,
            "algorithm": settings.auth_algorithm,
            "access_token_expire_minutes": settings.auth_access_token_expire_minutes,
            "refresh_token_expire_days": settings.auth_refresh_token_expire_days,
            "api_keys_configured": api_keys_configured,
        },
        "tls": {
            "enabled": settings.tls_enabled,
            "cert_configured": bool(settings.tls_cert_file),
        },
        "rate_limiting": {
            "enabled": settings.rate_limit_enabled,
            "max_requests": settings.rate_limit_requests,
            "window_seconds": settings.rate_limit_window_seconds,
        },
        "mqtt": {
            "enabled": settings.mqtt_enabled,
            "auth_configured": mqtt_auth_configured,
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
        },
        "csp": {
            "enabled": settings.csp_enabled,
        },
        "cors": {
            "mode": cors_mode,
            "allowed_origins": cors_origins,
        },
    }
