#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""TRITIUM-SC Autonomous Demo Story — headed screensaver with metrics.

Starts the TRITIUM-SC server with AMY_ENABLED=true, opens a VISIBLE Chromium
window at 1920x1080, and orchestrates a multi-act demo story via API calls +
Playwright keyboard/mouse automation. Amy thinks every 3 seconds and is
prompted via chat to react to every major event. Runs as an infinite
screensaver loop collecting real performance data for analysis.

Acts:
  1. Dawn Patrol     — Amy wakes, observes neighborhood, thinks out loud
  2. Force Deployment — Strategic unit placement, Amy briefs the plan
  3. War             — Multi-wave battle, Amy announces kills and waves
  4. TAK Network Ops — TAK panel, simulated clients, GeoChat
  5. Escalation      — Threat classification, Amy dispatches
  6. System Tour     — Events, escalation, patrol, system, scenarios, audio
  7. Cinematic Finale — Wide neighborhood shot, Amy reflects on the day

Metrics written to docs/screenshots/demo/metrics_{timestamp}.json per loop.

Usage:
    .venv/bin/python3 scripts/demo_story.py              # 1 loop, headed
    .venv/bin/python3 scripts/demo_story.py --forever     # infinite screensaver
    .venv/bin/python3 scripts/demo_story.py --loops 5     # 5 loops
    .venv/bin/python3 scripts/demo_story.py --waves 10    # full 10-wave battle
    .venv/bin/python3 scripts/demo_story.py --port 8000   # specific port
    .venv/bin/python3 scripts/demo_story.py --no-server   # connect to existing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import requests

# ---------------------------------------------------------------------------
# Project imports
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from tests.lib.server_manager import TritiumServer, _find_free_port

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots" / "demo"

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])   # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])      # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])              # #00f0ff
YELLOW_BGR = np.array([10, 238, 252])           # #fcee0a

# Chat prompts Amy will respond to at key moments
AMY_PROMPTS = {
    "dawn": "Good morning Amy. Run a status check on all sensors and give me a neighborhood sitrep.",
    "deploy": "Amy, I'm deploying a defensive perimeter. Seven turrets in a diamond, two drones on flanks, two rovers mobile. What do you think of this formation?",
    "war_begin": "Amy, hostiles inbound! Begin engagement protocols. Call out targets as you see them.",
    "first_kill": "First hostile down! Amy, keep the pressure on. How's our perimeter holding?",
    "wave_complete": "Wave cleared. Amy, damage report. How are our units?",
    "mid_battle": "Amy, give me a tactical assessment. Where are the gaps in our defense?",
    "tak_ops": "Amy, I'm checking the TAK network. Three ATAK operators are in the field. Coordinate with Alpha team.",
    "escalation": "Amy, we have hostile contacts at the perimeter! Multiple bogeys from different directions. Dispatch units to intercept.",
    "multi_threat": "Amy, threat level is rising. Four hostiles converging. What's your recommendation?",
    "finale": "Amy, the day's operations are complete. Give me your final assessment of the neighborhood security posture.",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_t0 = time.monotonic()


def log(msg: str) -> None:
    elapsed = time.monotonic() - _t0
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] [{elapsed:7.1f}s] {msg}")


def count_color_pixels(
    img: np.ndarray, target_bgr: np.ndarray, tolerance: int = 50,
) -> int:
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    return int(np.count_nonzero(mask))


def score_combat_frame(img: np.ndarray) -> float:
    green = count_color_pixels(img, FRIENDLY_GREEN_BGR, tolerance=50)
    red = count_color_pixels(img, HOSTILE_RED_BGR, tolerance=60)
    return green + red * 2.0


def api_get(base_url: str, path: str, timeout: float = 5):
    t0 = time.monotonic()
    try:
        resp = requests.get(f"{base_url}{path}", timeout=timeout)
        latency = (time.monotonic() - t0) * 1000
        data = resp.json() if resp.status_code == 200 else None
        return data, latency
    except Exception:
        return None, (time.monotonic() - t0) * 1000


def api_post(base_url: str, path: str, data: dict | None = None, timeout: float = 5):
    t0 = time.monotonic()
    try:
        resp = requests.post(f"{base_url}{path}", json=data or {}, timeout=timeout)
        latency = (time.monotonic() - t0) * 1000
        # Accept 200, 400, and 503 (Amy not ready yet) so we can see the body
        result = resp.json() if resp.status_code in (200, 400, 503) else None
        return result, latency
    except Exception:
        return None, (time.monotonic() - t0) * 1000


def get_targets(base_url: str) -> list[dict]:
    data, _ = api_get(base_url, "/api/amy/simulation/targets")
    if isinstance(data, dict):
        return data.get("targets", [])
    return data if isinstance(data, list) else []


def get_game_state(base_url: str) -> dict:
    data, _ = api_get(base_url, "/api/game/state")
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# DemoServer — TritiumServer with AMY_ENABLED=true, fast thinking
# ---------------------------------------------------------------------------

class DemoServer(TritiumServer):
    """Server configured for demo mode: Amy enabled, fast thinking."""

    def start(self, timeout: float = 90) -> None:
        if self.is_running:
            return

        import subprocess

        env = os.environ.copy()
        src_dir = str(PROJECT_ROOT / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{src_dir}:{existing}" if existing else src_dir
        env["SIMULATION_ENABLED"] = "true"
        env["AMY_ENABLED"] = "true"
        env["AMY_THINK_INTERVAL"] = "3"   # Think every 3s (default 8s)
        env["MQTT_ENABLED"] = "false"
        env["TAK_ENABLED"] = "false"
        # Let CUDA be available for Amy's model inference
        env.pop("CUDA_VISIBLE_DEVICES", None)

        cmd = [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", self.host,
            "--port", str(self.port),
            "--log-level", "info",
        ]

        self._process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if not self._wait_healthy(timeout):
            self.stop()
            raise RuntimeError(
                f"Server failed to become healthy within {timeout}s "
                f"on {self.base_url}"
            )


# ---------------------------------------------------------------------------
# Metrics Collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Collects performance data per demo loop for later analysis."""

    def __init__(self):
        self.loop_start = time.monotonic()
        self.act_timings: dict[str, float] = {}
        self.api_latencies: list[dict] = []
        self.amy_thoughts: list[dict] = []
        self.amy_chat_responses: list[dict] = []
        self.combat_stats: dict = {}
        self.frame_scores: list[dict] = []
        self.screenshot_count = 0
        self.page_errors: list[str] = []
        self.act_results: dict[str, str] = {}
        self.sensorium_polls: list[dict] = []

    def start_act(self, name: str) -> float:
        return time.monotonic()

    def end_act(self, name: str, t0: float) -> None:
        self.act_timings[name] = time.monotonic() - t0

    def record_api(self, endpoint: str, latency_ms: float) -> None:
        self.api_latencies.append({
            "endpoint": endpoint,
            "latency_ms": round(latency_ms, 1),
            "t": round(time.monotonic() - self.loop_start, 1),
        })

    def record_thought(self, text: str, source: str = "sensorium") -> None:
        self.amy_thoughts.append({
            "text": text[:200],
            "source": source,
            "t": round(time.monotonic() - self.loop_start, 1),
        })

    def record_chat(self, prompt: str, latency_ms: float) -> None:
        self.amy_chat_responses.append({
            "prompt": prompt[:80],
            "latency_ms": round(latency_ms, 1),
            "t": round(time.monotonic() - self.loop_start, 1),
        })

    def record_frame_score(self, name: str, score: float) -> None:
        self.frame_scores.append({
            "name": name,
            "score": round(score, 1),
            "t": round(time.monotonic() - self.loop_start, 1),
        })

    def record_sensorium(self, data: dict) -> None:
        self.sensorium_polls.append({
            "mood": data.get("mood", "unknown"),
            "event_count": data.get("event_count", 0),
            "narrative_len": len(data.get("narrative", "")),
            "t": round(time.monotonic() - self.loop_start, 1),
        })

    def to_dict(self) -> dict:
        total_time = time.monotonic() - self.loop_start
        latencies = [a["latency_ms"] for a in self.api_latencies]
        return {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "total_duration_s": round(total_time, 1),
            "act_timings_s": {k: round(v, 1) for k, v in self.act_timings.items()},
            "act_results": self.act_results,
            "screenshots": self.screenshot_count,
            "page_errors": len(self.page_errors),
            "amy": {
                "thoughts_captured": len(self.amy_thoughts),
                "chat_prompts_sent": len(self.amy_chat_responses),
                "avg_chat_latency_ms": round(
                    sum(c["latency_ms"] for c in self.amy_chat_responses)
                    / max(len(self.amy_chat_responses), 1), 1
                ),
                "thoughts": self.amy_thoughts,
                "chat_responses": self.amy_chat_responses,
                "sensorium_samples": self.sensorium_polls,
            },
            "api": {
                "total_calls": len(self.api_latencies),
                "avg_latency_ms": round(sum(latencies) / max(len(latencies), 1), 1),
                "max_latency_ms": round(max(latencies, default=0), 1),
                "p95_latency_ms": round(
                    sorted(latencies)[int(len(latencies) * 0.95)]
                    if latencies else 0, 1
                ),
            },
            "combat": self.combat_stats,
            "frame_scores": self.frame_scores,
        }

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = output_dir / f"metrics_{ts}.json"
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
        return path


# ---------------------------------------------------------------------------
# Screenshot helper
# ---------------------------------------------------------------------------

class ScreenshotManager:
    """Captures and saves timestamped screenshots."""

    def __init__(self, page, output_dir: Path, metrics: MetricsCollector):
        self.page = page
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._count = 0
        self._metrics = metrics
        self._ts_prefix = time.strftime("%Y%m%d_%H%M%S")

    def capture(self, name: str) -> tuple[Path, np.ndarray | None]:
        self._count += 1
        self._metrics.screenshot_count = self._count
        filename = f"{self._ts_prefix}_{name}.png"
        path = self.output_dir / filename
        try:
            self.page.screenshot(path=str(path))
            img = cv2.imread(str(path))
            log(f"Screenshot [{self._count}]: {filename}")
            return path, img
        except Exception as e:
            log(f"Screenshot FAILED ({name}): {e}")
            return path, None

    def burst_capture(self, name: str, count: int = 5, interval_ms: int = 400):
        best_score = -1.0
        best_path = None
        best_img = None
        for i in range(count):
            path, img = self.capture(f"{name}_burst{i}")
            if img is not None:
                score = score_combat_frame(img)
                self._metrics.record_frame_score(f"{name}_burst{i}", score)
                if score > best_score:
                    best_score = score
                    best_path = path
                    best_img = img
            if i < count - 1:
                self.page.wait_for_timeout(interval_ms)

        if best_img is not None:
            clean_path = self.output_dir / f"{self._ts_prefix}_{name}_best.png"
            cv2.imwrite(str(clean_path), best_img)
            log(f"Best burst frame: {clean_path.name} (score={best_score:.0f})")
            return clean_path, best_img
        return best_path, best_img

    @property
    def total(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Demo Runner
# ---------------------------------------------------------------------------

class DemoRunner:
    """Orchestrates the 7-act demo story with Amy engagement + metrics."""

    def __init__(self, base_url: str, page, shots: ScreenshotManager,
                 metrics: MetricsCollector, waves: int = 3):
        self.url = base_url
        self.page = page
        self.shots = shots
        self.metrics = metrics
        self.waves = waves

    def press(self, key: str, delay_ms: int = 200) -> None:
        self.page.keyboard.press(key)
        if delay_ms > 0:
            self.page.wait_for_timeout(delay_ms)

    def wait(self, ms: int) -> None:
        self.page.wait_for_timeout(ms)

    def js(self, code: str):
        return self.page.evaluate(code)

    def apply_preset(self, preset: str) -> None:
        """Apply a named panel preset layout via the PanelManager."""
        self.js(f"""() => {{
            if (window.panelManager && window.panelManager.applyPreset) {{
                window.panelManager.applyPreset('{preset}');
            }}
        }}""")
        self.wait(500)

    def close_all_panels(self) -> None:
        """Close all open panels."""
        self.js("""() => {
            if (window.panelManager && window.panelManager._panels) {
                const ids = [...window.panelManager._panels.keys()];
                ids.forEach(id => window.panelManager.close(id));
            }
        }""")
        self.wait(300)

    def set_camera(self, x: float | None = None, y: float | None = None,
                   zoom: float | None = None) -> None:
        """Set camera target via the Command Center's mapActions API."""
        opts_parts = []
        if x is not None:
            opts_parts.append(f"x: {x}")
        if y is not None:
            opts_parts.append(f"y: {y}")
        if zoom is not None:
            opts_parts.append(f"zoom: {zoom}")
        opts_str = ", ".join(opts_parts)
        self.js(f"""() => {{
            if (window.mapActions && window.mapActions.setCameraTarget) {{
                window.mapActions.setCameraTarget({{ {opts_str} }});
            }}
        }}""")

    def get_map_state(self) -> dict:
        """Read the current map state (showSatellite, zoom, etc.)."""
        return self.js("""() => {
            if (window.mapActions && window.mapActions.getMapState) {
                return window.mapActions.getMapState();
            }
            return {};
        }""") or {}

    def chat_amy(self, prompt_key: str, quick: bool = False) -> str | None:
        """Send a chat message to Amy and wait for her to process it.

        Args:
            prompt_key: Key into AMY_PROMPTS dict (or literal text).
            quick: If True, use a short timeout and don't retry.
                   Use this during combat when the LLM is busy.

        Returns the sensorium narrative after Amy responds, or None.
        """
        prompt = AMY_PROMPTS.get(prompt_key, prompt_key)
        log(f"[AMY CHAT] >> {prompt[:60]}...")

        # Check Amy's state first — skip if she's busy (SPEAKING/THINKING)
        status = self.poll_amy_status()
        if status:
            state = status.get("state", "").upper()
            if state in ("SPEAKING", "THINKING"):
                log(f"[AMY CHAT] Amy is {state}, polling sensorium instead...")
                return self.poll_sensorium(max_wait=5, log_prefix="AMY BUSY")

        # Use short timeouts — the endpoint blocks on Ollama generation
        timeout = 8 if quick else 15
        max_attempts = 1 if quick else 2

        result = None
        for attempt in range(max_attempts):
            result, latency = api_post(
                self.url, "/api/amy/chat", {"text": prompt}, timeout=timeout,
            )
            self.metrics.record_api("/api/amy/chat", latency)

            if result and result.get("status") == "ok":
                self.metrics.record_chat(prompt, latency)
                log(f"[AMY CHAT] Accepted in {latency:.0f}ms")
                break

            error = result.get("error", "unknown") if result else "no response"
            log(f"[AMY CHAT] Attempt {attempt + 1}/{max_attempts} failed: {error}")
            if attempt < max_attempts - 1:
                time.sleep(3)
        else:
            log(f"[AMY CHAT] Amy chat unavailable after {max_attempts} attempt(s)")
            return self.poll_sensorium(max_wait=5, log_prefix="AMY FALLBACK")

        # Give Amy time to generate the LLM response
        wait_time = 3 if quick else 5
        log("[AMY CHAT] Waiting for Amy to process...")
        time.sleep(wait_time)

        poll_time = 5 if quick else 10
        return self.poll_sensorium(max_wait=poll_time, log_prefix="AMY RESPONSE")

    def poll_sensorium(self, max_wait: int = 15, log_prefix: str = "SENSORIUM",
                       keywords: list[str] | None = None) -> str | None:
        """Poll Amy's sensorium for narrative content."""
        for tick in range(max_wait):
            data, latency = api_get(self.url, "/api/amy/sensorium")
            self.metrics.record_api("/api/amy/sensorium", latency)
            if data and isinstance(data, dict):
                self.metrics.record_sensorium(data)
                narrative = data.get("narrative", "")
                mood = data.get("mood", "unknown")
                events = data.get("event_count", 0)

                if narrative and len(narrative) > 10:
                    if keywords:
                        if not any(w in narrative.lower() for w in keywords):
                            time.sleep(1)
                            continue
                    log(f"[{log_prefix}] mood={mood} events={events}: "
                        f"{narrative[:100]}...")
                    self.metrics.record_thought(narrative, log_prefix.lower())
                    return narrative
            time.sleep(1)
        log(f"[{log_prefix}] No narrative after {max_wait}s")
        return None

    def poll_amy_status(self) -> dict | None:
        """Quick check of Amy's status."""
        data, latency = api_get(self.url, "/api/amy/status")
        self.metrics.record_api("/api/amy/status", latency)
        return data

    # ===================================================================
    # ACT 1: DAWN PATROL
    # ===================================================================

    def act1_dawn_patrol(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 1: DAWN PATROL — Amy Wakes Up")
        print("=" * 70)

        # Wait for units to load
        log("Waiting for simulation units in TritiumStore...")
        try:
            self.page.wait_for_function(
                "() => window.TritiumStore && window.TritiumStore.units "
                "&& window.TritiumStore.units.size >= 3",
                timeout=20000,
            )
            unit_count = self.js("() => window.TritiumStore.units.size")
            log(f"Units loaded: {unit_count}")
        except Exception:
            log("WARNING: TritiumStore units not detected, continuing...")

        # Dismiss keyboard guide overlay + help overlay + clear stale layout
        self.js("""() => {
            localStorage.setItem('tritium-seen-keyboard-guide', '1');
            localStorage.setItem('tritium-help-dismissed', 'true');
            localStorage.removeItem('tritium-panel-layout');
            const guide = document.getElementById('keyboard-guide');
            if (guide) guide.hidden = true;
            const overlay = document.getElementById('help-overlay');
            if (overlay) overlay.hidden = true;
        }""")
        self.wait(500)

        # Check Amy status
        amy_status = self.poll_amy_status()
        amy_running = amy_status is not None and amy_status.get("running", False)
        log(f"Amy running: {amy_running}")
        if amy_status:
            log(f"Amy mood: {amy_status.get('mood', 'unknown')}, "
                f"thoughts: {amy_status.get('thought_count', 0)}")

        # Apply "commander" preset layout for well-sized panels
        log("Applying commander preset layout...")
        self.apply_preset('commander')
        self.wait(1000)
        self.shots.capture("act1_commander_layout")

        # Talk to Amy — morning briefing
        self.chat_amy("dawn")
        self.shots.capture("act1_amy_briefing")

        # Open more panels
        self.press("2")  # Units
        self.wait(1000)
        self.press("3")  # Alerts
        self.wait(1000)
        self.press("4")  # Game HUD
        self.wait(1000)
        self.shots.capture("act1_all_panels")

        # Cycle map modes
        log("Cycling map modes...")
        self.press("o")  # Observe
        self.wait(1000)
        self.shots.capture("act1_observe_mode")

        self.press("t")  # Tactical
        self.wait(1000)
        self.shots.capture("act1_tactical_mode")

        self.press("s")  # Setup
        self.wait(1000)
        self.shots.capture("act1_setup_mode")

        # Zoom out to neighborhood
        log("Zooming out to neighborhood view...")
        self.set_camera(zoom=0.5)
        self.wait(3000)
        self.shots.capture("act1_neighborhood")

        # Zoom back in
        log("Zooming in on center...")
        self.set_camera(x=0, y=0, zoom=3.0)
        self.wait(2000)

        # Ensure satellite imagery is ON (check via mapActions)
        map_state = self.get_map_state()
        if not map_state.get("showSatellite", False):
            self.press("i")  # Toggle satellite ON
            log("Toggled satellite imagery ON")
        else:
            log("Satellite imagery already ON")
        self.wait(3000)   # Extra time for tile loading
        self.shots.capture("act1_satellite")

        # Check what Amy has been thinking
        self.poll_sensorium(max_wait=5, log_prefix="AMY DAWN THOUGHTS")
        self.shots.capture("act1_amy_thinking")

        log("ACT 1 complete.")

    # ===================================================================
    # ACT 2: FORCE DEPLOYMENT
    # ===================================================================

    def act2_force_deployment(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 2: FORCE DEPLOYMENT — Strategic Unit Placement")
        print("=" * 70)

        # Ensure key panels are open
        self.press("4")  # Game HUD
        self.wait(300)
        self.press("2")  # Units
        self.wait(300)

        # Reset any previous game state
        api_post(self.url, "/api/game/reset")
        self.wait(1000)

        # Place turrets in defensive diamond
        turret_positions = [
            ("Alpha", 0, 0), ("Bravo", 12, 5), ("Charlie", -12, 5),
            ("Delta", 6, -10), ("Echo", -6, -10),
            ("Foxtrot", 15, -5), ("Golf", -15, -5),
        ]
        log(f"Placing {len(turret_positions)} turrets...")
        for name, x, y in turret_positions:
            result, latency = api_post(self.url, "/api/game/place", {
                "name": name, "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
            self.metrics.record_api("/api/game/place", latency)

        # Place drones
        drones = [("Hawk-1", 20, 0), ("Hawk-2", -20, 0)]
        log(f"Placing {len(drones)} drones...")
        for name, x, y in drones:
            result, latency = api_post(self.url, "/api/game/place", {
                "name": name, "asset_type": "drone",
                "position": {"x": x, "y": y},
            })
            self.metrics.record_api("/api/game/place", latency)

        # Place rovers
        rovers = [("Tank-1", 0, -15), ("Tank-2", 0, 15)]
        log(f"Placing {len(rovers)} rovers...")
        for name, x, y in rovers:
            result, latency = api_post(self.url, "/api/game/place", {
                "name": name, "asset_type": "rover",
                "position": {"x": x, "y": y},
            })
            self.metrics.record_api("/api/game/place", latency)

        total_placed = len(turret_positions) + len(drones) + len(rovers)
        self.wait(2000)

        # Verify placement
        targets = get_targets(self.url)
        friendlies = [t for t in targets if t.get("alliance") == "friendly"]
        log(f"Placed {total_placed} units. API reports {len(friendlies)} friendlies.")

        # Tell Amy about the deployment
        self.chat_amy("deploy")
        self.shots.capture("act2_amy_deployment_brief")

        # Click first unit in units panel
        try:
            self.page.click(".unit-entry, .panel-list-item", timeout=3000)
            self.wait(500)
        except Exception:
            log("Could not click unit row (panel may not have items)")

        self.shots.capture("act2_unit_selected")

        # Tactical view
        self.press("t")
        self.wait(1000)
        self.shots.capture("act2_tactical_overview")

        log("ACT 2 complete.")

    # ===================================================================
    # ACT 3: WAR
    # ===================================================================

    def act3_war(self) -> None:
        print()
        print("=" * 70)
        print(f"  ACT 3: WAR — {self.waves}-Wave Battle")
        print("=" * 70)

        # Apply "battle" preset — properly sized panels for combat
        log("Applying battle preset layout...")
        self.apply_preset('battle')

        # Switch to observe mode for best combat visuals
        self.press("o")
        self.wait(500)

        # Zoom to a level where combat effects (explosions, trails) are visible
        self.set_camera(x=0, y=0, zoom=2.5)
        self.wait(500)

        # Tell Amy to engage
        self.chat_amy("war_begin", quick=True)

        # Begin war
        log("Beginning war...")
        self.press("b")
        self.wait(1000)

        # Capture countdown
        state = get_game_state(self.url)
        current = state.get("state", "unknown")
        log(f"Game state after begin: {current}")
        if current in ("countdown", "active"):
            self.shots.capture("act3_countdown")

        # Wait for countdown to end
        if current == "countdown":
            self.wait(5000)

        waves_completed = 0
        last_wave = 0
        total_elims = 0
        first_kill_captured = False
        last_amy_prompt_time = time.monotonic()
        amy_combat_fails = 0  # Stop trying after 2 consecutive fails

        for wave_num in range(1, self.waves + 1):
            print()
            log(f"--- WAVE {wave_num} ---")

            hostiles_found = False
            for tick in range(90):
                time.sleep(1)
                state = get_game_state(self.url)
                phase = state.get("state", "unknown")
                wave = state.get("wave", 0)
                elims = state.get("total_eliminations", 0)

                if phase in ("victory", "defeat"):
                    log(f"Game ended: {phase} at wave {wave}")
                    self.shots.capture(f"act3_game_end_{phase}")
                    waves_completed = wave
                    break

                targets = get_targets(self.url)
                hostiles = [t for t in targets
                            if t.get("alliance") == "hostile"]

                if hostiles and not hostiles_found:
                    hostiles_found = True
                    log(f"Hostiles detected: {len(hostiles)} "
                        f"(wave={wave}, elims={elims})")
                    # Center camera on the action (first hostile)
                    h = hostiles[0]
                    hx = h.get("position", {}).get("x", 0)
                    hy = h.get("position", {}).get("y", 0)
                    self.set_camera(x=hx, y=hy, zoom=3.0)
                    self.wait(500)
                    self.shots.capture(f"act3_wave{wave_num}_hostiles")

                # Elimination detected — capture the explosion effects
                if elims > total_elims:
                    new_kills = elims - total_elims
                    total_elims = elims
                    log(f"  +{new_kills} elimination(s)! Total: {elims}")
                    # Quick burst to catch the explosion particles
                    self.shots.capture(
                        f"act3_elim_{elims}_w{wave_num}")

                    if not first_kill_captured:
                        first_kill_captured = True
                        if amy_combat_fails < 2:
                            r = self.chat_amy("first_kill", quick=True)
                            if r is None:
                                amy_combat_fails += 1
                            else:
                                amy_combat_fails = 0

                # Prompt Amy every ~30s during combat (skip if unresponsive)
                now = time.monotonic()
                if (now - last_amy_prompt_time > 30
                        and phase == "active"
                        and amy_combat_fails < 2):
                    last_amy_prompt_time = now
                    r = self.chat_amy("mid_battle", quick=True)
                    if r is None:
                        amy_combat_fails += 1
                    else:
                        amy_combat_fails = 0
                    self.shots.capture(f"act3_amy_mid_battle_w{wave_num}")

                if tick % 15 == 0:
                    log(f"  t={tick}s: phase={phase} wave={wave} "
                        f"hostiles={len(hostiles)} elims={elims}")
                    # Capture Amy's sensorium periodically
                    self.poll_sensorium(max_wait=2, log_prefix="AMY COMBAT")

                # Wave transition
                if wave > last_wave and wave > wave_num:
                    last_wave = wave
                    waves_completed = wave_num
                    log(f"Wave {wave_num} complete, now on wave {wave}")
                    if amy_combat_fails < 2:
                        r = self.chat_amy("wave_complete", quick=True)
                        if r is None:
                            amy_combat_fails += 1
                    break

                if phase == "wave_complete":
                    self.shots.capture(f"act3_wave{wave_num}_complete")
                    waves_completed = wave_num
                    if amy_combat_fails < 2:
                        r = self.chat_amy("wave_complete", quick=True)
                        if r is None:
                            amy_combat_fails += 1
                    self.wait(3000)
                    break

            else:
                waves_completed = wave_num
                log(f"Wave {wave_num} timeout (still in progress)")

            if state.get("state") in ("victory", "defeat"):
                break

            # Burst capture mid-combat
            self.shots.burst_capture(f"act3_wave{wave_num}_combat", count=3)

            last_wave = state.get("wave", last_wave)

        # Final combat snapshot
        self.wait(3000)

        # Final game state
        final = get_game_state(self.url)
        self.metrics.combat_stats = {
            "final_state": final.get("state"),
            "waves_reached": final.get("wave", 0),
            "score": final.get("score", 0),
            "total_eliminations": final.get("total_eliminations", 0),
        }
        log(f"Battle result: state={final.get('state')} "
            f"wave={final.get('wave')} score={final.get('score')} "
            f"elims={final.get('total_eliminations')}")

        # Leaderboard
        self.press("4")
        self.wait(500)
        self.shots.capture("act3_leaderboard")

        # Combat stats overlay
        self.press("j")
        self.wait(500)
        self.shots.capture("act3_combat_stats")
        self.press("j")

        # End war if still running
        if final.get("state") not in ("victory", "defeat", "idle"):
            api_post(self.url, "/api/game/reset")
            log("Game reset (ended early after demo waves)")

        log(f"ACT 3 complete. Waves: {waves_completed}, "
            f"Elims: {total_elims}")

    # ===================================================================
    # ACT 4: TAK NETWORK OPS
    # ===================================================================

    def act4_tak_network(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 4: TAK NETWORK OPS")
        print("=" * 70)

        # Open TAK panel
        self.press(";")
        self.wait(1500)
        self.shots.capture("act4_tak_status")

        # Check TAK status
        tak_status, latency = api_get(self.url, "/api/tak/status")
        self.metrics.record_api("/api/tak/status", latency)
        tak_enabled = tak_status.get("enabled", False) if tak_status else False
        log(f"TAK bridge enabled: {tak_enabled}")

        # Spawn ATAK-style units
        log("Spawning ATAK-style simulation targets...")
        atak_units = [
            {"name": "ATAK-Alpha-1", "position": {"x": 30, "y": 20}},
            {"name": "ATAK-Alpha-2", "position": {"x": -25, "y": 15}},
            {"name": "ATAK-Alpha-3", "position": {"x": 10, "y": -30}},
        ]
        for unit in atak_units:
            result, latency = api_post(self.url, "/api/amy/simulation/spawn", {
                "name": unit["name"],
                "asset_type": "person",
                "alliance": "neutral",
                "position": unit["position"],
            })
            self.metrics.record_api("/api/amy/simulation/spawn", latency)
            log(f"  Spawned {unit['name']}")

        self.wait(2000)

        # Brief Amy on TAK ops
        self.chat_amy("tak_ops", quick=True)
        self.shots.capture("act4_tak_clients")

        # Try TAK chat
        chat_result, latency = api_post(self.url, "/api/tak/chat", {
            "message": "Alpha team, sweep sector 3",
            "to_callsign": "All Chat Rooms",
        })
        self.metrics.record_api("/api/tak/chat", latency)
        log(f"TAK GeoChat: {chat_result}")
        self.shots.capture("act4_geochat_sent")

        # Try TAK alert
        alert_result, latency = api_post(self.url, "/api/tak/alert", {
            "callsign": "Intruder-X",
            "lat": 33.524, "lng": -112.262,
            "remarks": "Demo hostile marker",
        })
        self.metrics.record_api("/api/tak/alert", latency)
        log(f"TAK alert: {alert_result}")
        self.wait(1000)
        self.shots.capture("act4_tak_alert")

        # Close TAK panel
        self.press(";")
        self.wait(500)

        log("ACT 4 complete.")

    # ===================================================================
    # ACT 5: ESCALATION & DISPATCH
    # ===================================================================

    def act5_escalation(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 5: ESCALATION & DISPATCH")
        print("=" * 70)

        # Reset to commander layout + add escalation panel
        self.apply_preset('commander')

        # Open Escalation panel
        self.press("x")
        self.wait(1500)
        self.shots.capture("act5_escalation_green")

        # Spawn hostile near perimeter
        log("Spawning hostile at perimeter...")
        result, latency = api_post(self.url, "/api/amy/simulation/spawn", {
            "name": "Intruder-1",
            "asset_type": "hostile",
            "alliance": "hostile",
            "position": {"x": 50, "y": 0},
        })
        self.metrics.record_api("/api/amy/simulation/spawn", latency)

        # Tell Amy about the threat
        self.chat_amy("escalation", quick=True)

        # Wait for threat detection
        log("Waiting for threat detection (up to 15s)...")
        hostile_detected = False
        for tick in range(15):
            time.sleep(1)
            data, latency = api_get(self.url, "/api/targets/hostiles")
            self.metrics.record_api("/api/targets/hostiles", latency)
            hostiles = data if isinstance(data, list) else (
                data.get("targets", []) if isinstance(data, dict) else []
            )
            if hostiles:
                hostile_detected = True
                log(f"Hostile detected at t={tick}s: {len(hostiles)} threats")
                break

        self.shots.capture("act5_hostile_detected")

        # Open Alerts panel
        self.press("3")
        self.wait(1000)
        self.shots.capture("act5_alert_triggered")

        # Spawn more hostiles
        log("Spawning 3 more hostiles from different directions...")
        additional_hostiles = [
            {"name": "Flanker-N", "position": {"x": 0, "y": 60}},
            {"name": "Flanker-E", "position": {"x": -60, "y": 0}},
            {"name": "Flanker-S", "position": {"x": 0, "y": -60}},
        ]
        for h in additional_hostiles:
            result, latency = api_post(self.url, "/api/amy/simulation/spawn", {
                "name": h["name"],
                "asset_type": "hostile",
                "alliance": "hostile",
                "position": h["position"],
            })
            self.metrics.record_api("/api/amy/simulation/spawn", latency)

        # Tell Amy about multi-threat
        self.chat_amy("multi_threat", quick=True)
        self.shots.capture("act5_multi_threat")

        # Check Amy's dispatch response via sensorium
        self.poll_sensorium(
            max_wait=15, log_prefix="AMY DISPATCH",
            keywords=["dispatch", "threat", "hostile", "alert", "engage",
                       "intercept", "perimeter", "contact"],
        )
        self.shots.capture("act5_amy_dispatch")

        # Clean up
        api_post(self.url, "/api/game/reset")
        self.wait(1000)

        self.press("x")  # Close escalation
        self.press("3")  # Close alerts
        self.wait(500)

        log(f"ACT 5 complete. Hostile detected: {hostile_detected}")

    # ===================================================================
    # ACT 6: SYSTEM TOUR
    # ===================================================================

    def act6_system_tour(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 6: SYSTEM TOUR — Panels With Content")
        print("=" * 70)

        # Close everything for a clean tour
        self.close_all_panels()

        # Only open panels that have real content in demo mode.
        # Panels that depend on external hardware (mesh, cameras, videos,
        # zones, search) are empty — skip them.
        panels = [
            ("e", "events", "Events"),      # Has events from game + Amy
            ("x", "escalation", "Escalation"),  # Has threat data from game
            ("p", "patrol", "Patrol"),       # Has friendly units
            ("u", "system", "System"),       # Shows server info
            ("9", "scenarios", "Scenarios"), # Lists scenario JSON files
            ("7", "audio", "Audio"),         # Lists sound effects library
        ]

        for key, name, label in panels:
            log(f"Opening {label} panel...")
            self.press(key)
            self.wait(2000)
            self.shots.capture(f"act6_{name}")
            self.press(key)  # Close
            self.wait(500)

        log("ACT 6 complete.")

    # ===================================================================
    # ACT 7: CINEMATIC FINALE
    # ===================================================================

    def act7_cinematic_finale(self) -> None:
        print()
        print("=" * 70)
        print("  ACT 7: CINEMATIC FINALE")
        print("=" * 70)

        # Clean slate
        api_post(self.url, "/api/game/reset")
        self.wait(1000)

        # Ask Amy for her final thoughts (quick — LLM may be saturated)
        self.chat_amy("finale", quick=True)
        self.shots.capture("act7_amy_reflection")

        # Zoom out to minimum
        log("Zooming out for wide neighborhood view...")
        self.set_camera(x=0, y=0, zoom=0.3)

        # Hide all panels for clean shot
        self.js("""() => {
            document.querySelectorAll('.panel').forEach(p => {
                p.style.display = 'none';
            });
        }""")

        # Ensure satellite view is ON
        map_state = self.get_map_state()
        if not map_state.get("showSatellite", False):
            self.press("i")
        self.wait(3000)
        self.shots.capture("act7_neighborhood_wide")

        # Slow zoom in over 5 steps
        log("Cinematic zoom in...")
        zoom_steps = [0.5, 0.8, 1.2, 1.6, 2.0]
        for i, zoom in enumerate(zoom_steps):
            self.set_camera(zoom=zoom)
            self.wait(1000)
            self.shots.capture(f"act7_zoom_{i}")

        # Cinematic mode
        log("Activating cinematic mode...")
        self.press("k")
        self.wait(2000)
        self.shots.capture("act7_cinematic")
        self.press("k")

        # Re-show panels
        self.js("""() => {
            document.querySelectorAll('.panel').forEach(p => {
                p.style.display = '';
            });
        }""")
        self.wait(500)

        # Reset zoom
        self.set_camera(zoom=2.0)
        self.wait(1000)

        # Final sensorium snapshot
        self.poll_sensorium(max_wait=5, log_prefix="AMY FINALE")

        log("ACT 7 complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_demo(args) -> int:
    from playwright.sync_api import sync_playwright

    # Server setup
    server = None
    base_url = f"http://127.0.0.1:{args.port}"

    if not args.no_server:
        log("Starting TRITIUM-SC server with AMY_ENABLED=true, "
            "AMY_THINK_INTERVAL=3s...")
        port = args.port if args.port != 0 else None
        if port:
            server = DemoServer(port=port, auto_port=False)
        else:
            server = DemoServer(auto_port=True)
        try:
            server.start(timeout=90)
        except RuntimeError:
            log("WARNING: Server with AMY_ENABLED failed. "
                "Trying without Amy (Ollama may not be running)...")
            if server:
                server.stop()
            server = TritiumServer(
                port=args.port if args.port != 0 else 0,
                auto_port=(args.port == 0),
            )
            server.start(timeout=30)
        base_url = server.url
        log(f"Server running at {base_url}")
    else:
        log(f"Connecting to existing server at {base_url}")
        try:
            resp = requests.get(f"{base_url}/health", timeout=5)
            if resp.status_code != 200:
                print(f"ERROR: Server at {base_url} not healthy")
                return 1
        except Exception as e:
            print(f"ERROR: Cannot connect to {base_url}: {e}")
            return 1

    loop_count = 0
    max_loops = 0 if args.forever else args.loops

    try:
        # Launch headed Chromium
        log("Launching headed Chromium (1920x1080)...")
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        # Capture console errors
        page_errors: list[str] = []
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        try:
            while True:
                loop_count += 1
                if max_loops > 0 and loop_count > max_loops:
                    break

                print()
                print("#" * 70)
                loop_label = (f"/{max_loops}" if max_loops > 0
                              else " (infinite screensaver)")
                print(f"#  TRITIUM-SC DEMO STORY — Loop {loop_count}"
                      f"{loop_label}")
                print("#" * 70)

                # Fresh metrics per loop
                metrics = MetricsCollector()
                metrics.page_errors = page_errors

                # Navigate
                log(f"Navigating to {base_url}/...")
                page.goto(f"{base_url}/",
                          wait_until="domcontentloaded", timeout=60000)
                # Pre-dismiss keyboard guide before its 2s show timer fires
                page.evaluate(
                    "localStorage.setItem('tritium-seen-keyboard-guide','1')"
                )
                page.wait_for_timeout(3000)

                shots = ScreenshotManager(page, OUTPUT_DIR, metrics)
                runner = DemoRunner(base_url, page, shots, metrics,
                                    waves=args.waves)

                # Run all 7 acts
                acts = [
                    ("ACT 1", runner.act1_dawn_patrol),
                    ("ACT 2", runner.act2_force_deployment),
                    ("ACT 3", runner.act3_war),
                    ("ACT 4", runner.act4_tak_network),
                    ("ACT 5", runner.act5_escalation),
                    ("ACT 6", runner.act6_system_tour),
                    ("ACT 7", runner.act7_cinematic_finale),
                ]

                for act_name, act_fn in acts:
                    t_act = metrics.start_act(act_name)
                    try:
                        act_fn()
                        metrics.act_results[act_name] = "PASS"
                    except Exception as e:
                        metrics.act_results[act_name] = f"FAIL: {e}"
                        log(f"{act_name} FAILED: {e}")
                        try:
                            shots.capture(
                                f"error_{act_name.lower().replace(' ', '_')}"
                            )
                        except Exception:
                            pass
                    metrics.end_act(act_name, t_act)

                # Save metrics
                metrics_path = metrics.save(OUTPUT_DIR)
                metrics_data = metrics.to_dict()

                # Summary
                print()
                print("=" * 70)
                print(f"  DEMO LOOP {loop_count} COMPLETE")
                print("=" * 70)
                print(f"  Duration:       {metrics_data['total_duration_s']}s")
                print(f"  Screenshots:    {shots.total}")
                print(f"  Amy thoughts:   {metrics_data['amy']['thoughts_captured']}")
                print(f"  Amy chats sent: {metrics_data['amy']['chat_prompts_sent']}")
                print(f"  Avg chat lat:   {metrics_data['amy']['avg_chat_latency_ms']}ms")
                print(f"  API calls:      {metrics_data['api']['total_calls']}")
                print(f"  Avg API lat:    {metrics_data['api']['avg_latency_ms']}ms")
                print(f"  P95 API lat:    {metrics_data['api']['p95_latency_ms']}ms")
                print(f"  Combat:         {json.dumps(metrics_data['combat'])}")
                print(f"  Page errors:    {len(page_errors)}")
                for name, result in metrics.act_results.items():
                    status = "OK" if result == "PASS" else "FAIL"
                    timing = metrics_data["act_timings_s"].get(name, 0)
                    print(f"  {name}: {status} ({timing}s)")
                print(f"  Metrics:        {metrics_path}")
                print(f"  Screenshots:    {OUTPUT_DIR}/")
                print("=" * 70)

                # If looping, brief pause
                if max_loops == 0 or loop_count < max_loops:
                    log("Next loop in 5s...")
                    time.sleep(5)

        except KeyboardInterrupt:
            log("Interrupted by user.")

        finally:
            browser.close()
            pw.stop()

    finally:
        if server:
            log("Stopping server...")
            server.stop()

    log("Demo complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TRITIUM-SC Autonomous Demo Story (headed screensaver)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--loops", type=int, default=1,
        help="Number of demo loops (default: 1)",
    )
    parser.add_argument(
        "--forever", action="store_true",
        help="Run indefinitely as a screensaver until Ctrl+C",
    )
    parser.add_argument(
        "--waves", type=int, default=3,
        help="Number of battle waves to run (default: 3, max: 10)",
    )
    parser.add_argument(
        "--port", type=int, default=0,
        help="Server port (default: auto-detect free port)",
    )
    parser.add_argument(
        "--no-server", action="store_true",
        help="Connect to existing server instead of starting one",
    )

    args = parser.parse_args()

    if args.no_server and args.port == 0:
        args.port = 8000

    print("=" * 70)
    print("  TRITIUM-SC AUTONOMOUS DEMO STORY")
    print("=" * 70)
    print(f"  Mode:    headed (visible browser)")
    print(f"  Loops:   {'infinite screensaver' if args.forever else args.loops}")
    print(f"  Waves:   {args.waves}")
    print(f"  Amy:     AMY_ENABLED=true, think_interval=3s")
    print(f"  Server:  {'external' if args.no_server else 'auto-start'}")
    print(f"  Output:  {OUTPUT_DIR}/")
    print(f"  Metrics: {OUTPUT_DIR}/metrics_*.json")
    print("=" * 70)

    return run_demo(args)


if __name__ == "__main__":
    sys.exit(main())
