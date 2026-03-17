# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Webhook bridge addon example.

Batches target updates and POSTs them as JSON to a configurable
webhook URL. Rate-limited to at most one POST per batch_interval
seconds (default 5s).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from tritium_lib.sdk import BridgeAddon, AddonInfo

log = logging.getLogger("addon.bridge-webhook")


class WebhookAddon(BridgeAddon):
    """Bridges target updates to an external webhook endpoint."""

    info = AddonInfo(
        id="bridge-webhook",
        name="Webhook Bridge",
        version="1.0.0",
        description="POSTs target updates to a webhook URL with batching",
        author="Valpatel Software LLC",
        category="integration",
    )

    def __init__(self):
        super().__init__()
        self._webhook_url: str = ""
        self._batch_interval: float = 5.0
        self._include_position: bool = True
        self._pending: list[dict] = []
        self._last_send: float = 0.0
        self._send_count: int = 0
        self._error_count: int = 0
        self._flush_task: asyncio.Task | None = None
        self._lock: asyncio.Lock = asyncio.Lock()

    async def register(self, app: Any) -> None:
        await super().register(app)

        # Read config from app if available
        config = getattr(app, "config", None)
        if config and hasattr(config, "get"):
            self._webhook_url = config.get("webhook_url", self._webhook_url)
            self._batch_interval = float(config.get("batch_interval", self._batch_interval))
            self._include_position = bool(config.get("include_position", self._include_position))

        # Start flush loop
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._background_tasks.append(self._flush_task)
        log.info(f"Webhook bridge registered (url={self._webhook_url or '<not configured>'})")

    async def unregister(self, app: Any) -> None:
        # Flush remaining before shutdown
        if self._pending:
            await self._flush()
        await super().unregister(app)
        log.info(f"Webhook bridge unregistered (sent {self._send_count} batches)")

    async def send(self, targets: list[dict]) -> None:
        """Queue targets for the next webhook batch.

        Args:
            targets: List of target dicts to send.
        """
        async with self._lock:
            self._pending.extend(targets)

        # If enough time has passed since last send, flush immediately
        if time.time() - self._last_send >= self._batch_interval:
            await self._flush()

    async def _flush(self) -> None:
        """Send all pending targets to the webhook URL."""
        if not self._webhook_url:
            return

        async with self._lock:
            if not self._pending:
                return
            batch = self._pending[:]
            self._pending.clear()

        # Filter position data if not included
        if not self._include_position:
            for t in batch:
                t.pop("lat", None)
                t.pop("lng", None)
                t.pop("position", None)

        payload = {
            "event": "target_update",
            "timestamp": time.time(),
            "count": len(batch),
            "targets": batch,
        }

        try:
            await self._post_json(self._webhook_url, payload)
            self._send_count += 1
            self._last_send = time.time()
            log.debug(f"Webhook sent {len(batch)} targets to {self._webhook_url}")
        except Exception as e:
            self._error_count += 1
            log.warning(f"Webhook POST failed: {e}")

    def _post_json_sync(self, url: str, payload: dict) -> int:
        """POST JSON to a URL synchronously. Returns HTTP status code.

        Args:
            url: The webhook URL.
            payload: Dict to JSON-encode and send.

        Returns:
            HTTP status code.

        Raises:
            URLError: On network failure.
        """
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "tritium-webhook-addon/1.0",
            },
            method="POST",
        )
        with urlopen(req, timeout=10) as resp:
            return resp.status

    async def _post_json(self, url: str, payload: dict) -> int:
        """POST JSON in a thread to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._post_json_sync, url, payload)

    async def _flush_loop(self) -> None:
        """Background loop that flushes pending targets at the batch interval."""
        while self._registered:
            try:
                await asyncio.sleep(self._batch_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Webhook flush error: {e}")

    def health_check(self) -> dict:
        if not self._registered:
            return {"status": "not_registered"}
        if not self._webhook_url:
            return {"status": "degraded", "detail": "No webhook URL configured"}
        if self._error_count > 0 and self._send_count == 0:
            return {"status": "error", "detail": f"{self._error_count} consecutive errors"}
        return {
            "status": "ok",
            "webhook_url": self._webhook_url,
            "send_count": self._send_count,
            "error_count": self._error_count,
            "pending": len(self._pending),
        }
