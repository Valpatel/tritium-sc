# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Authentication API endpoints.

Provides login, token refresh, and user info endpoints.
Only active when auth_enabled=True in config.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import (
    api_key_store,
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    require_admin,
    require_auth,
)
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Authenticate and receive JWT tokens."""
    if not settings.auth_enabled:
        # Auth disabled — return a dummy token
        return TokenResponse(
            access_token=create_access_token("admin", "admin"),
            refresh_token=create_refresh_token("admin"),
            expires_in=settings.auth_access_token_expire_minutes * 60,
        )

    user = authenticate_user(request.username, request.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    return TokenResponse(
        access_token=create_access_token(user["sub"], user["role"]),
        refresh_token=create_refresh_token(user["sub"]),
        expires_in=settings.auth_access_token_expire_minutes * 60,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest):
    """Refresh an access token using a refresh token."""
    payload = decode_token(request.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid refresh token",
        )

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token missing subject claim",
        )

    return TokenResponse(
        access_token=create_access_token(subject, payload.get("role", "user")),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.auth_access_token_expire_minutes * 60,
    )


@router.get("/me")
async def get_current_user(user: dict = Depends(require_auth)):
    """Get current user information."""
    return {
        "username": user["sub"],
        "role": user.get("role", "user"),
    }


@router.get("/status")
async def auth_status():
    """Check if authentication is enabled."""
    return {
        "auth_enabled": settings.auth_enabled,
        "tls_enabled": settings.tls_enabled,
    }


# ---------------------------------------------------------------------------
# API Key Management — create, rotate, revoke, list
# ---------------------------------------------------------------------------

class CreateAPIKeyRequest(BaseModel):
    name: str = "default"
    role: str = "admin"
    expires_in_days: int = 0  # 0 = no expiry
    scope: str = "full"  # "full", "read-only", or "admin"


class RotateAPIKeyRequest(BaseModel):
    key_id: str
    grace_period_seconds: int = 3600  # Old key valid for 1 hour default


class RevokeAPIKeyRequest(BaseModel):
    key_id: str


@router.post("/api-keys")
async def create_api_key(
    request: CreateAPIKeyRequest,
    user: dict = Depends(require_admin),
):
    """Create a new API key. Returns the plaintext key (shown once only)."""
    result = api_key_store.create_key(
        name=request.name,
        role=request.role,
        expires_in_days=request.expires_in_days,
        scope=request.scope,
    )
    return result


@router.post("/api-keys/rotate")
async def rotate_api_key(
    request: RotateAPIKeyRequest,
    user: dict = Depends(require_admin),
):
    """Rotate an API key.

    Generates a new key value. The old key remains valid for the
    grace period (default 1 hour) to allow clients to switch over.
    """
    result = api_key_store.rotate_key(
        key_id=request.key_id,
        grace_period_seconds=request.grace_period_seconds,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {request.key_id} not found or already revoked",
        )
    return result


@router.post("/api-keys/revoke")
async def revoke_api_key(
    request: RevokeAPIKeyRequest,
    user: dict = Depends(require_admin),
):
    """Revoke an API key immediately (no grace period)."""
    ok = api_key_store.revoke_key(request.key_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"API key {request.key_id} not found",
        )
    return {"revoked": True, "key_id": request.key_id}


@router.get("/api-keys")
async def list_api_keys(user: dict = Depends(require_admin)):
    """List all API keys (without plaintext values)."""
    keys = api_key_store.list_keys()
    return {"keys": keys, "count": len(keys)}


@router.get("/api-keys/audit")
async def api_key_audit(
    limit: int = 100,
    user: dict = Depends(require_admin),
):
    """Get API key audit log — shows all create/rotate/revoke events."""
    entries = api_key_store.get_audit_log(limit=limit)
    return {"entries": entries, "count": len(entries)}
