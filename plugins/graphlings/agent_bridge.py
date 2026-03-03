# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""AgentBridge — HTTP client to an external creature server.

Thin HTTP adapter: sends deploy/recall/think/heartbeat requests to a
configurable REST server.  No SDK dependency — just raw HTTP calls.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from .config import GraphlingsConfig

log = logging.getLogger(__name__)


class AgentBridge:
    """HTTP client connecting the tritium-sc plugin to a creature server."""

    def __init__(self, config: GraphlingsConfig) -> None:
        self._base_url = config.server_url.rstrip("/")
        self._timeout = config.server_timeout
        self._dry_run = config.dry_run

    # ── Deploy / Recall ──────────────────────────────────────────

    def deploy(self, soul_id: str, config: dict) -> Optional[dict]:
        """Deploy a creature.  Returns deployment record dict or None."""
        return self._post(f"/deployment/deploy", {
            "soul_id": soul_id, "config": config,
        })

    def recall(self, soul_id: str, reason: str = "manual") -> Optional[dict]:
        """Recall a deployed creature."""
        return self._post(f"/deployment/{soul_id}/recall", {"reason": reason})

    # ── Batch Deploy / Recall ────────────────────────────────────

    def batch_deploy(self, config: dict) -> Optional[dict]:
        return self._post("/deployment/batch/deploy", config)

    def batch_recall(self, service_name: str, reason: str) -> Optional[dict]:
        return self._post("/deployment/batch/recall", {
            "service_name": service_name, "reason": reason,
        })

    # ── Think ────────────────────────────────────────────────────

    def think(
        self,
        soul_id: str,
        perception: dict,
        current_state: str,
        available_actions: list[str],
        urgency: float,
        preferred_layer: Optional[int] = None,
    ) -> Optional[dict]:
        """Ask the creature to think.  Returns response dict or None."""
        body: dict[str, Any] = {
            "perception": perception,
            "current_state": current_state,
            "available_actions": available_actions,
            "urgency": urgency,
        }
        if preferred_layer is not None:
            body["preferred_layer"] = preferred_layer
        return self._post(f"/deployment/{soul_id}/think", body)

    # ── Heartbeat ────────────────────────────────────────────────

    def heartbeat(self, soul_id: str) -> Optional[dict]:
        return self._post(f"/deployment/{soul_id}/heartbeat", {})

    # ── Experience ───────────────────────────────────────────────

    def record_experiences(self, soul_id: str, experiences: list[dict]) -> int:
        result = self._post(f"/deployment/{soul_id}/experience", {
            "experiences": experiences,
        })
        return result.get("count", 0) if result else 0

    # ── Feedback (RL loop) ────────────────────────────────────────

    def feedback(
        self, soul_id: str, action: str, success: bool, outcome: str = "",
    ) -> Optional[dict]:
        return self._post(f"/deployment/{soul_id}/feedback", {
            "action": action, "success": success, "outcome": outcome,
        })

    # ── Status ───────────────────────────────────────────────────

    def get_status(self, soul_id: str) -> Optional[dict]:
        return self._get(f"/deployment/{soul_id}/status")

    def list_active(self) -> list[dict]:
        result = self._get("/deployment/active")
        if isinstance(result, dict):
            return result.get("deployments", [])
        return result if isinstance(result, list) else []

    def set_objective(
        self, soul_id: str, description: str, priority: float = 0.5,
        deadline_seconds: int = 0,
    ) -> Optional[dict]:
        return self._post(f"/deployment/{soul_id}/objective", {
            "description": description,
            "priority": priority,
            "deadline_seconds": deadline_seconds,
        })

    # ── Internal HTTP helpers ────────────────────────────────────

    def _post(self, path: str, body: dict) -> Optional[dict]:
        if self._dry_run:
            log.debug("[DRY RUN] POST %s%s", self._base_url, path)
            return {"dry_run": True}
        try:
            r = httpx.post(
                f"{self._base_url}{path}",
                json=body,
                timeout=self._timeout,
            )
            if r.status_code < 300:
                return r.json()
            log.warning("POST %s → %d", path, r.status_code)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.debug("POST %s failed: %s", path, exc)
        except Exception as exc:
            log.error("POST %s error: %s", path, exc)
        return None

    def _get(self, path: str) -> Optional[Any]:
        if self._dry_run:
            return {"dry_run": True}
        try:
            r = httpx.get(
                f"{self._base_url}{path}",
                timeout=self._timeout,
            )
            if r.status_code < 300:
                return r.json()
            log.warning("GET %s → %d", path, r.status_code)
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            log.debug("GET %s failed: %s", path, exc)
        except Exception as exc:
            log.error("GET %s error: %s", path, exc)
        return None
