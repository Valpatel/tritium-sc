"""AgentBridge — HTTP client to the Graphling home server.

Provides deploy/recall/think/heartbeat/experience operations against
the Graphling server's deployment REST API. All methods are synchronous
(called from the plugin's background thread) and handle errors gracefully.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from httpx import ConnectError as _ConnectError
from httpx import TimeoutException as _TimeoutException

from .config import GraphlingsConfig

log = logging.getLogger(__name__)


class AgentBridge:
    """HTTP client connecting the tritium-sc plugin to the Graphling home server."""

    def __init__(self, config: GraphlingsConfig) -> None:
        self._base_url = config.server_url.rstrip("/")
        self._timeout = config.server_timeout

    # ── Deploy / Recall ──────────────────────────────────────────

    def deploy(self, soul_id: str, config: dict) -> Optional[dict]:
        """Deploy a graphling to this service.

        Returns the deployment record dict, or None on error.
        """
        return self._post(
            "/deployment/deploy",
            json={"soul_id": soul_id, "config": config},
        )

    def recall(self, soul_id: str, reason: str = "manual") -> Optional[dict]:
        """Recall a deployed graphling.

        Returns recall result dict, or None on error.
        """
        return self._post(
            f"/deployment/{soul_id}/recall",
            json={"reason": reason},
        )

    # ── Batch Deploy / Recall ────────────────────────────────────

    def batch_deploy(self, config: dict) -> Optional[dict]:
        """Deploy a batch of graphlings.

        POST /deployment/deploy-batch
        Returns the batch result dict, or None on error.
        """
        return self._post("/deployment/deploy-batch", json=config)

    def batch_recall(self, service_name: str, reason: str) -> Optional[dict]:
        """Recall all graphlings for a service.

        POST /deployment/recall-batch
        Returns recall result dict, or None on error.
        """
        return self._post(
            "/deployment/recall-batch",
            json={"service_name": service_name, "reason": reason},
        )

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
        """Ask the graphling to make a decision.

        Returns ThinkResponse dict (thought, action, emotion, layer, model, confidence),
        or None on timeout/error.
        """
        body: dict[str, Any] = {
            "perception": perception,
            "current_state": current_state,
            "available_actions": available_actions,
            "urgency": urgency,
        }
        if preferred_layer is not None:
            body["preferred_layer"] = preferred_layer

        return self._post(f"/deployment/{soul_id}/think", json=body)

    # ── Heartbeat ────────────────────────────────────────────────

    def heartbeat(self, soul_id: str) -> Optional[dict]:
        """Send heartbeat to keep deployment alive.

        Returns heartbeat response dict, or None on error.
        """
        return self._post(f"/deployment/{soul_id}/heartbeat", json={})

    # ── Experience ───────────────────────────────────────────────

    def record_experiences(self, soul_id: str, experiences: list[dict]) -> int:
        """Record a batch of experiences.

        Returns the number of experiences recorded (0 on error).
        """
        result = self._post(
            f"/deployment/{soul_id}/experience",
            json={"experiences": experiences},
        )
        if result is None:
            return 0
        return result.get("recorded", 0)

    # ── Feedback (RL loop) ────────────────────────────────────────

    def feedback(
        self,
        soul_id: str,
        action: str,
        success: bool,
        outcome: str = "",
    ) -> Optional[dict]:
        """Report action success/failure to close the RL reinforcement loop.

        The server uses this to update Thompson Sampling arms and adjust
        future model selection for this graphling.

        Returns server response dict, or None on error.
        """
        return self._post(
            f"/deployment/{soul_id}/feedback",
            json={"action": action, "success": success, "outcome": outcome},
        )

    # ── Pending Actions (server autonomy) ──────────────────────

    def get_pending_actions(self, soul_id: str) -> list[dict]:
        """Poll server-generated autonomous actions.

        The server's tickDeployedAutonomous() generates proactive goals
        and actions. External apps poll this to discover what the graphling
        wants to do on its own initiative.

        Returns list of action dicts (empty on error).
        """
        result = self._get(f"/deployment/{soul_id}/pending-actions")
        if result is None:
            return []
        return result.get("actions", [])

    # ── World Model ────────────────────────────────────────────

    def report_entity(self, soul_id: str, entity: dict) -> Optional[dict]:
        """Report a perceived entity to update the graphling's mental model.

        Builds persistent world knowledge that persists across think cycles,
        allowing the graphling to remember entities it has seen before.

        Returns server response dict, or None on error.
        """
        return self._post(f"/deployment/{soul_id}/world/entity", json=entity)

    # ── Mood ───────────────────────────────────────────────────

    def get_mood(self, soul_id: str) -> Optional[dict]:
        """Get the graphling's current emotional state.

        Returns mood dict (happiness, stress, engagement, confidence),
        or None on error. Use for adaptive behavior and auto-recall.
        """
        return self._get(f"/deployment/{soul_id}/mood")

    # ── Objectives ─────────────────────────────────────────────

    def set_objective(self, soul_id: str, objective: dict) -> Optional[dict]:
        """Set a goal for the graphling to pursue autonomously.

        Game events can drive objectives (e.g., "protect village" when
        enemies approach). The server's autonomous tick will work toward it.

        Returns created objective dict, or None on error.
        """
        return self._post(f"/deployment/{soul_id}/objectives", json=objective)

    # ── Status ───────────────────────────────────────────────────

    def get_status(self, soul_id: str) -> Optional[dict]:
        """Get deployment status for a soul.

        Returns deployment record dict, or None if not found/error.
        """
        return self._get(f"/deployment/{soul_id}")

    def list_active(self) -> list[dict]:
        """List all active deployments.

        Returns list of deployment records (empty on error).
        """
        result = self._get("/deployment/active")
        if result is None:
            return []
        return result.get("deployments", [])

    # ── HTTP helpers ─────────────────────────────────────────────

    def _post(self, path: str, json: dict) -> Optional[dict]:
        """POST to the Graphling server. Returns parsed JSON or None."""
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.post(url, json=json, timeout=self._timeout)
            if resp.is_success:
                return resp.json()
            log.warning("POST %s returned %d", path, resp.status_code)
            return None
        except _TimeoutException:
            log.warning("POST %s timed out", path)
            return None
        except _ConnectError:
            log.warning("POST %s connection refused", path)
            return None
        except Exception as e:
            log.warning("POST %s failed: %s", path, e)
            return None

    def _get(self, path: str) -> Optional[dict]:
        """GET from the Graphling server. Returns parsed JSON or None."""
        url = f"{self._base_url}{path}"
        try:
            resp = httpx.get(url, timeout=self._timeout)
            if resp.is_success:
                return resp.json()
            log.warning("GET %s returned %d", path, resp.status_code)
            return None
        except _TimeoutException:
            log.warning("GET %s timed out", path)
            return None
        except _ConnectError:
            log.warning("GET %s connection refused", path)
            return None
        except Exception as e:
            log.warning("GET %s failed: %s", path, e)
            return None
