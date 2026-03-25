# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Secure client IP extraction with trusted proxy validation.

Only reads X-Forwarded-For when the direct connecting IP is in the
configured trusted_proxies list.  When trusted, takes the rightmost
(last) IP in the X-Forwarded-For chain — the one appended by the
trusted proxy itself, which cannot be spoofed by the client.

When no trusted proxies are configured (default), always returns
request.client.host, ignoring proxy headers entirely.
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import FrozenSet

from fastapi import Request

from app.config import settings


@lru_cache(maxsize=1)
def _trusted_proxy_set() -> FrozenSet[str]:
    """Parse trusted_proxies config into a frozen set (cached)."""
    raw = settings.trusted_proxies.strip()
    if not raw:
        return frozenset()
    proxies: set[str] = set()
    for entry in raw.split(","):
        entry = entry.strip()
        if entry:
            # Normalize IP addresses (e.g. ::1 vs 0:0:0:0:0:0:0:1)
            try:
                proxies.add(str(ipaddress.ip_address(entry)))
            except ValueError:
                # Not a valid IP — keep as-is (hostname, etc.)
                proxies.add(entry)
    return frozenset(proxies)


def get_client_ip(request: Request) -> str:
    """Extract the real client IP from a request.

    Security:
        - Only trusts X-Forwarded-For if the direct peer (request.client.host)
          is in config.trusted_proxies.
        - Takes the rightmost IP in X-Forwarded-For (the one added by the
          trusted proxy, not spoofable by the client).
        - Falls back to request.client.host when no trusted proxies configured
          or when the peer is not a trusted proxy.
    """
    peer_ip = request.client.host if request.client else "unknown"

    trusted = _trusted_proxy_set()
    if not trusted:
        # No proxies configured — never trust forwarded headers
        return peer_ip

    if peer_ip not in trusted:
        # Direct connection from untrusted source — ignore headers
        return peer_ip

    # Peer is a trusted proxy — read X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Rightmost non-empty entry is the one appended by the proxy
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            return parts[-1]

    # Header missing or empty — fall back to peer
    return peer_ip
