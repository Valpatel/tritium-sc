#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Full battle simulation verification — plays through combat, screenshots every phase,
distributes visual analysis across all available ollama hosts in parallel.

Phases:
1. War Room initial state (satellite/grid view with units)
2. Game setup (place turrets)
3. Countdown (3-2-1)
4. Wave active (hostiles incoming, projectiles, health bars)
5. Combat midpoint (kills, streaks, score)
6. Wave transitions
7. Game over (victory or defeat)

Each phase: screenshot + API state + parallel llava analysis across fleet.

Run: python3 tests/ui/test_battle.py
Requires: server on localhost:8000, ollama fleet (auto-discovered)
"""

import base64, json, os, sys, time, requests
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from tests.lib.ollama_fleet import OllamaFleet

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000")
REPORT_DIR = Path("tests/ui/.battle-results")
VISION_MODEL = os.environ.get("VISION_MODEL", "llava:7b")


class BattleVerifier:
    """Plays a full battle and verifies every phase visually + via API."""

    def __init__(self, fleet: OllamaFleet):
        self.fleet = fleet
        self.results: list[dict] = []
        self.screenshots: list[dict] = []  # {"name": str, "path": Path, "prompt": str}
        self.run_dir = REPORT_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.page = None
        self.pw = None
        self.browser = None

    def setup(self):
        """Launch browser, navigate to War Room."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080})
        self.page.goto(SERVER_URL)
        self.page.wait_for_load_state("networkidle")
        # Navigate to War Room
        self.page.keyboard.press("w")
        time.sleep(2)

    def teardown(self):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()
        # Reset game
        try:
            requests.post(f"{SERVER_URL}/api/game/reset", timeout=5)
        except Exception:
            pass

    def capture(self, name: str, prompt: str) -> Path:
        """Take a screenshot and queue it for llava analysis."""
        path = self.run_dir / f"{name}.png"
        self.page.screenshot(path=str(path))
        self.screenshots.append({"name": name, "image": path, "prompt": prompt})
        return path

    def api_get(self, path: str) -> dict | list | None:
        """Safe API GET."""
        try:
            resp = requests.get(f"{SERVER_URL}{path}", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def api_post(self, path: str, data: dict | None = None) -> dict | None:
        """Safe API POST."""
        try:
            resp = requests.post(f"{SERVER_URL}{path}", json=data or {}, timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def get_sim_targets(self) -> list[dict]:
        """Get simulation targets (handles both list and {targets:[]} formats)."""
        data = self.api_get("/api/amy/simulation/targets")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("targets", [])
        return []

    # ── Battle Phases ──────────────────────────────────────────────

    def phase_initial(self):
        """Phase 1: War Room initial view."""
        print("  Phase 1: War Room initial state...")
        self.capture("01_war_room",
            "This is a tactical war room interface for an RTS game. "
            "Describe what you see: map type (satellite imagery or dark grid), "
            "any unit markers, any buttons like 'BEGIN WAR', any minimap. "
            "List all visible UI elements.")

        # API verification — game should be in setup/idle before we start
        state = self.api_get("/api/game/state")
        phase = state.get("state", "") if state else ""
        self.results.append({
            "phase": "initial", "api_state": phase,
            "api_ok": phase in ("setup", "idle", ""),
        })

    def phase_setup(self):
        """Phase 2: Place turrets for defense."""
        print("  Phase 2: Placing turrets...")
        positions = [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]
        for i, (x, y) in enumerate(positions):
            resp = self.api_post("/api/game/place", {
                "name": f"Turret-{i+1}",
                "asset_type": "turret",
                "position": {"x": x, "y": y},
            })
            if resp and resp.get("target_id"):
                print(f"    Placed turret at ({x},{y})")
            else:
                print(f"    WARN: Failed to place turret at ({x},{y}): {resp}")
        time.sleep(1)

        self.capture("02_setup",
            "This is a tactical game screen after placing defensive turrets. "
            "Can you see green square shapes representing turrets? "
            "How many turrets or defensive units are visible? "
            "Is there a 'BEGIN WAR' button?")

        state = self.api_get("/api/game/state")
        self.results.append({
            "phase": "setup",
            "api_state": state.get("state") if state else "unknown",
            "api_ok": state is not None,
        })

    def phase_countdown(self):
        """Phase 3: Start game, capture countdown."""
        print("  Phase 3: Starting game (countdown)...")
        self.api_post("/api/game/begin")
        time.sleep(1.5)

        self.capture("03_countdown",
            "Look at the center of this game screen. "
            "Is there a large number (1, 2, 3, 4, or 5) displayed? "
            "It may be in a bright magenta/pink color on a dark background. "
            "What number do you see?")

        state = self.api_get("/api/game/state")
        phase = state.get("state", "") if state else ""
        self.results.append({
            "phase": "countdown",
            "api_state": phase,
            "api_ok": phase in ("countdown", "active"),
        })

    def phase_wave_active(self):
        """Phase 4: First wave active — hostiles spawning."""
        print("  Phase 4: Wave active (waiting for hostiles)...")
        # Wait for game to become active and hostiles to appear
        # Track whether we ever saw active state (game can end fast)
        saw_active = False
        max_hostiles = 0
        max_friendlies = 0
        for _ in range(15):
            time.sleep(1)
            state = self.api_get("/api/game/state")
            if state and state.get("state") in ("active", "wave_complete"):
                saw_active = True
            targets = self.get_sim_targets()
            h = len([t for t in targets if t.get("alliance") == "hostile"])
            f = len([t for t in targets if t.get("alliance") == "friendly"])
            max_hostiles = max(max_hostiles, h)
            max_friendlies = max(max_friendlies, f)
            if h > 0:
                break

        self.capture("04_wave_active",
            "This is an active combat scene in a tactical RTS game. "
            "Look for: green shapes (friendly turrets), red diamond shapes (hostile enemies), "
            "lines between units (projectile trails), health bars above units, "
            "and any HUD text showing wave number or score. "
            "Describe the combat action you can see.")

        self.results.append({
            "phase": "wave_active",
            "api_max_hostiles": max_hostiles,
            "api_max_friendlies": max_friendlies,
            "api_saw_active": saw_active,
            "api_ok": saw_active or max_hostiles > 0 or max_friendlies > 0,
        })

    def phase_combat_midpoint(self):
        """Phase 5: Mid-combat — captures score, kills."""
        print("  Phase 5: Combat midpoint...")
        time.sleep(5)

        self.capture("05_midpoint",
            "This tactical game screen shows ongoing combat. "
            "Look at the corners and edges for: SCORE display, KILLS counter, "
            "WAVE indicator, kill feed messages. "
            "Can you read any numbers or text in the HUD overlay? "
            "List every piece of text you can make out.")

        state = self.api_get("/api/game/state")
        self.results.append({
            "phase": "midpoint",
            "api_score": state.get("score", 0) if state else 0,
            "api_eliminations": state.get("total_eliminations", state.get("total_kills", 0)) if state else 0,
            "api_wave": state.get("wave", 0) if state else 0,
            "api_ok": state is not None,
        })

    def phase_late_game(self):
        """Phase 6: Late game — more waves, higher intensity."""
        print("  Phase 6: Late game (waiting for wave transitions)...")
        # Wait up to 60s for the game to progress or end
        for _ in range(30):
            time.sleep(2)
            state = self.api_get("/api/game/state")
            if state:
                phase = state.get("state", "")
                if phase in ("victory", "defeat", "idle"):
                    break
                if state.get("wave", 0) >= 3:
                    break

        self.capture("06_late_game",
            "This is a late-stage tactical combat game screen. "
            "Look for: multiple unit types, projectile effects, "
            "health bars, score display, wave banners, "
            "or a game over screen showing VICTORY or DEFEAT. "
            "Describe everything visible on screen.")

        state = self.api_get("/api/game/state")
        self.results.append({
            "phase": "late_game",
            "api_state": state.get("state", "") if state else "unknown",
            "api_wave": state.get("wave", 0) if state else 0,
            "api_score": state.get("score", 0) if state else 0,
            "api_ok": state is not None,
        })

    def phase_game_over(self):
        """Phase 7: Wait for game to end, capture final screen."""
        print("  Phase 7: Waiting for game over...")
        for _ in range(60):
            time.sleep(2)
            state = self.api_get("/api/game/state")
            if state and state.get("state") in ("victory", "defeat", "idle"):
                break

        time.sleep(2)  # Let the game over screen render
        self.capture("07_game_over",
            "Is this a game over screen? Look for large text saying "
            "'VICTORY' or 'DEFEAT'. Also look for final score, "
            "total kills, waves completed, and a 'PLAY AGAIN' button. "
            "List all text and numbers you can see.")

        state = self.api_get("/api/game/state")
        self.results.append({
            "phase": "game_over",
            "api_state": state.get("state", "") if state else "unknown",
            "api_score": state.get("score", 0) if state else 0,
            "api_eliminations": state.get("total_eliminations", state.get("total_kills", 0)) if state else 0,
            "api_waves": state.get("waves_completed", 0) if state else 0,
            "api_ok": state is not None,
        })

    def phase_synthetic_camera(self):
        """Bonus: Capture synthetic camera frame."""
        print("  Phase 8: Synthetic camera frame...")
        try:
            resp = requests.get(
                f"{SERVER_URL}/api/amy/nodes/syn-cam-0/video",
                timeout=5, stream=True,
            )
            if resp.status_code != 200:
                self.results.append({"phase": "synthetic_camera", "api_ok": False, "skip": "no endpoint"})
                return

            frame_data = b""
            for chunk in resp.iter_content(chunk_size=4096):
                frame_data += chunk
                if b"\xff\xd9" in frame_data:
                    start = frame_data.find(b"\xff\xd8")
                    end = frame_data.find(b"\xff\xd9") + 2
                    if start >= 0:
                        frame_data = frame_data[start:end]
                        break
            resp.close()

            frame_path = self.run_dir / "08_synthetic_camera.jpg"
            frame_path.write_bytes(frame_data)

            self.screenshots.append({
                "name": "08_synthetic_camera",
                "image": frame_path,
                "prompt": (
                    "This is a bird's-eye tactical camera view rendered by a simulation. "
                    "It has a dark background with grid lines and colored rectangles "
                    "representing units. Can you see any colored shapes? "
                    "Count the green (friendly) and red (hostile) rectangles."
                ),
            })

            self.results.append({
                "phase": "synthetic_camera",
                "frame_bytes": len(frame_data),
                "api_ok": len(frame_data) > 500,
            })
        except Exception as e:
            self.results.append({"phase": "synthetic_camera", "api_ok": False, "error": str(e)})

    # ── Parallel Visual Analysis ──────────────────────────────────

    def analyze_all(self):
        """Send all screenshots to the fleet for parallel llava analysis."""
        if not self.screenshots:
            return

        n_hosts = len(self.fleet.hosts_with_model(VISION_MODEL))
        print(f"\n  Analyzing {len(self.screenshots)} screenshots across {n_hosts} hosts...")
        t0 = time.monotonic()

        vision_results = self.fleet.parallel_vision(
            model=VISION_MODEL,
            tasks=self.screenshots,
            max_workers=n_hosts,
        )

        elapsed = time.monotonic() - t0
        print(f"  Fleet analysis complete in {elapsed:.1f}s")

        # Merge vision results into phase results
        vision_by_name = {r["name"]: r for r in vision_results}
        for result in self.results:
            phase = result.get("phase", "")
            # Find matching screenshot
            for ss in self.screenshots:
                if ss["name"].endswith(phase) or phase in ss["name"]:
                    vr = vision_by_name.get(ss["name"])
                    if vr:
                        result["llava_response"] = vr["response"]
                        result["llava_host"] = vr["host"]
                        result["llava_ms"] = vr["elapsed_ms"]
                    break

        # Also store raw vision results
        self._vision_results = vision_results

    # ── Scoring ───────────────────────────────────────────────────

    def score(self) -> dict:
        """Evaluate overall battle verification."""
        api_pass = sum(1 for r in self.results if r.get("api_ok"))
        api_total = len(self.results)

        # Check if llava saw reasonable things in each phase
        vision_checks = []
        for vr in getattr(self, "_vision_results", []):
            resp = vr.get("response", "").lower()
            # Broad check: does the response mention game-relevant things?
            relevant = any(w in resp for w in [
                "map", "game", "unit", "turret", "grid", "satellite",
                "combat", "score", "wave", "number", "shape", "color",
                "green", "red", "defeat", "victory", "button", "text",
                "display", "tactical", "military", "marker", "interface",
                "health", "bar", "projectile", "hostile", "diamond",
            ])
            vision_checks.append({"name": vr["name"], "relevant": relevant, "host": vr["host"]})

        vision_pass = sum(1 for v in vision_checks if v["relevant"])
        vision_total = len(vision_checks)

        return {
            "api_pass": api_pass,
            "api_total": api_total,
            "vision_pass": vision_pass,
            "vision_total": vision_total,
            "overall_pass": api_pass >= api_total * 0.7,  # 70% API checks pass
            "vision_checks": vision_checks,
        }

    # ── Main ──────────────────────────────────────────────────────

    def run(self) -> int:
        """Execute the full battle verification."""
        print("=" * 60)
        print("  TRITIUM-SC Full Battle Verification")
        print(f"  Fleet: {self.fleet.count} hosts")
        print("=" * 60)

        try:
            self.setup()
            self.phase_initial()
            self.phase_setup()
            self.phase_countdown()
            self.phase_wave_active()
            self.phase_combat_midpoint()
            self.phase_late_game()
            self.phase_game_over()
            self.phase_synthetic_camera()
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results.append({"phase": "error", "api_ok": False, "error": str(e)})
        finally:
            self.teardown()

        # Parallel visual analysis across fleet
        self.analyze_all()

        # Score and report
        scores = self.score()
        report = {
            "timestamp": datetime.now().isoformat(),
            "fleet": [{"name": h.name, "models": h.models[:5]} for h in self.fleet.hosts],
            "phases": self.results,
            "vision": getattr(self, "_vision_results", []),
            "scores": scores,
        }

        report_path = self.run_dir / "report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2, default=str)

        # Print summary
        print(f"\n{'=' * 60}")
        print(f"  API checks:    {scores['api_pass']}/{scores['api_total']}")
        print(f"  Vision checks: {scores['vision_pass']}/{scores['vision_total']}")
        print(f"  Fleet hosts:   {', '.join(h.name for h in self.fleet.hosts)}")
        for vc in scores["vision_checks"]:
            status = "OK" if vc["relevant"] else "WEAK"
            print(f"    {vc['name']}: {status} (via {vc['host']})")
        print(f"  Report: {report_path}")
        print(f"{'=' * 60}")

        return 0 if scores["overall_pass"] else 1


if __name__ == "__main__":
    # Prerequisites
    try:
        requests.get(f"{SERVER_URL}/health", timeout=5)
    except Exception:
        print(f"ERROR: Server not running at {SERVER_URL}")
        sys.exit(1)

    fleet = OllamaFleet()
    if fleet.count == 0:
        print("ERROR: No ollama hosts found")
        sys.exit(1)

    print(fleet.status())
    print()

    verifier = BattleVerifier(fleet)
    sys.exit(verifier.run())
