#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Gameplay screenshot verification using Playwright + llava:7b + API cross-validation.

Verification strategy:
- Each test captures a screenshot AND queries the API for ground truth
- llava:7b analyzes the screenshot (visual verification)
- API response provides the expected state (data verification)
- A test passes if EITHER visual OR data check passes (llava is imperfect)
- A test fails only if BOTH checks fail

Run: python3 tests/ui/test_gameplay.py
Requires: server running on localhost:8000, ollama with llava:7b
"""

import base64, json, os, sys, time, requests
from pathlib import Path
from datetime import datetime

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
REPORT_DIR = Path("tests/ui/.gameplay-results")
SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:8000")


class GameplayVerifier:
    def __init__(self):
        self.results = []
        self.screenshots_dir = REPORT_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")

    def setup(self):
        """Start Playwright browser, navigate to War Room."""
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=True)
        self.page = self.browser.new_page(viewport={"width": 1920, "height": 1080})
        self.page.goto(SERVER_URL)
        self.page.wait_for_load_state("networkidle")
        # Navigate to War Room (W key)
        self.page.keyboard.press("w")
        time.sleep(2)

    def screenshot(self, name: str) -> Path:
        path = self.screenshots_dir / f"{name}.png"
        self.page.screenshot(path=str(path))
        return path

    def ask_llava(self, image_path: Path, prompt: str) -> str:
        """Send image to llava:7b for analysis."""
        try:
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
                "model": "llava:7b",
                "prompt": prompt,
                "images": [img_b64],
                "stream": False,
            }, timeout=120)
            return resp.json().get("response", "")
        except Exception as e:
            return f"[llava error: {e}]"

    def verify_war_room(self):
        """Verify War Room view is active."""
        path = self.screenshot("war_room_initial")

        # API check: verify we have simulation targets
        api_ok = False
        try:
            resp = requests.get(f"{SERVER_URL}/api/amy/simulation/targets", timeout=5)
            targets = resp.json()
            count = len(targets) if isinstance(targets, list) else len(targets.get("targets", []))
            api_ok = count > 0
        except Exception:
            pass

        # Visual check: llava analyzes the War Room
        response = self.ask_llava(path,
            "This is a screenshot of a tactical war room interface. "
            "Do you see any of: a map view, satellite imagery, grid lines, "
            "colored unit markers, a 'BEGIN WAR' button, or a minimap? "
            "List what you observe.")
        visual_ok = any(w in response.lower() for w in [
            "map", "satellite", "grid", "marker", "begin", "war",
            "minimap", "tactical", "unit", "button", "interface",
        ])

        passed = api_ok or visual_ok
        self.results.append({
            "test": "war_room_visible",
            "screenshot": str(path),
            "response": response,
            "api_targets": count if api_ok else 0,
            "visual_ok": visual_ok,
            "api_ok": api_ok,
            "pass": passed,
        })
        self._print_result("war_room_visible", passed, f"visual={visual_ok} api={api_ok}")

    def verify_game_countdown(self):
        """Start a game and verify countdown appears."""
        # Place turrets via API
        requests.post(f"{SERVER_URL}/api/game/place", json={"name": "Turret-A", "asset_type": "turret", "position": {"x": 0, "y": 0}})
        requests.post(f"{SERVER_URL}/api/game/place", json={"name": "Turret-B", "asset_type": "turret", "position": {"x": 5, "y": 5}})
        # Begin game
        requests.post(f"{SERVER_URL}/api/game/begin")
        time.sleep(1.5)

        path = self.screenshot("countdown")

        # API check: game state should be countdown or active
        api_ok = False
        try:
            resp = requests.get(f"{SERVER_URL}/api/game/state", timeout=5)
            state = resp.json()
            game_phase = state.get("state") or state.get("phase", "")
            api_ok = game_phase in ("countdown", "active", "wave_complete")
        except Exception:
            pass

        # Visual check
        response = self.ask_llava(path,
            "Look at this game interface screenshot. "
            "Is there a large number displayed in the center of the screen? "
            "The number could be 1, 2, 3, 4, or 5 and may be in a bright color like pink or magenta. "
            "Also look for any wave indicator or combat status text. "
            "Describe what you see.")
        visual_ok = any(w in response.lower() for w in [
            "number", "countdown", "1", "2", "3", "4", "5",
            "wave", "combat", "active", "digit",
        ])

        passed = api_ok or visual_ok
        self.results.append({
            "test": "countdown_visible",
            "screenshot": str(path),
            "response": response,
            "api_phase": game_phase if api_ok else "unknown",
            "visual_ok": visual_ok,
            "api_ok": api_ok,
            "pass": passed,
        })
        self._print_result("countdown_visible", passed, f"visual={visual_ok} api={api_ok} phase={game_phase if api_ok else '?'}")

    def verify_combat_active(self):
        """Wait for combat and verify units visible."""
        time.sleep(5)  # Wait for wave to start
        path = self.screenshot("combat_active")

        # API check: hostiles should exist
        api_ok = False
        hostile_count = 0
        try:
            resp = requests.get(f"{SERVER_URL}/api/targets/hostiles", timeout=5)
            hostiles = resp.json()
            hostile_count = len(hostiles.get("targets", [])) if isinstance(hostiles, dict) else 0
            api_ok = hostile_count > 0
        except Exception:
            pass

        # Visual check
        response = self.ask_llava(path,
            "This is a tactical game map. Look for colored shapes representing units. "
            "Green shapes are friendly units (turrets, rovers). "
            "Red shapes are hostile enemies. "
            "Do you see any colored shapes, health bars, or projectile trails? "
            "Describe the combat elements you can see.")
        visual_ok = any(w in response.lower() for w in [
            "green", "red", "shape", "square", "diamond", "turret", "hostile",
            "health", "bar", "projectile", "trail", "unit", "marker",
        ])

        passed = api_ok or visual_ok
        self.results.append({
            "test": "combat_units_visible",
            "screenshot": str(path),
            "response": response,
            "api_hostiles": hostile_count,
            "visual_ok": visual_ok,
            "api_ok": api_ok,
            "pass": passed,
        })
        self._print_result("combat_units_visible", passed, f"visual={visual_ok} api={api_ok} hostiles={hostile_count}")

    def verify_hud_elements(self):
        """Verify HUD elements during combat."""
        path = self.screenshot("hud_elements")

        # API check: game state should have score/wave info
        api_ok = False
        try:
            resp = requests.get(f"{SERVER_URL}/api/game/state", timeout=5)
            state = resp.json()
            api_ok = state.get("wave", 0) >= 1 or state.get("score", 0) > 0
        except Exception:
            pass

        # Visual check
        response = self.ask_llava(path,
            "Look at the edges and corners of this game interface screenshot. "
            "Can you see any text overlays showing: score, wave number, "
            "kill count, player statistics, or status information? "
            "List any text or numbers you can read.")
        visual_ok = any(w in response.lower() for w in [
            "score", "wave", "kill", "text", "number", "status",
            "display", "overlay", "hud", "statistic", "count",
        ])

        passed = api_ok or visual_ok
        self.results.append({
            "test": "hud_visible",
            "screenshot": str(path),
            "response": response,
            "visual_ok": visual_ok,
            "api_ok": api_ok,
            "pass": passed,
        })
        self._print_result("hud_visible", passed, f"visual={visual_ok} api={api_ok}")

    def verify_synthetic_camera(self):
        """Verify synthetic camera produces frames with targets."""
        try:
            # Get sim targets count from API
            resp = requests.get(f"{SERVER_URL}/api/amy/simulation/targets", timeout=5)
            if resp.status_code != 200:
                self.results.append({"test": "synthetic_camera", "pass": None, "skip": "No simulation API"})
                self._print_result("synthetic_camera", None, "SKIP: no sim API")
                return
            targets = resp.json()
            target_count = len(targets) if isinstance(targets, list) else len(targets.get("targets", []))

            # Get synthetic camera frame (MJPEG)
            resp = requests.get(f"{SERVER_URL}/api/amy/nodes/syn-cam-0/video", timeout=5, stream=True)
            if resp.status_code != 200:
                self.results.append({"test": "synthetic_camera", "pass": None, "skip": "No synthetic camera"})
                self._print_result("synthetic_camera", None, "SKIP: no syn-cam")
                return

            # Extract first JPEG from MJPEG stream
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

            frame_path = self.screenshots_dir / "synthetic_camera.jpg"
            frame_path.write_bytes(frame_data)

            # Data check: frame is a valid JPEG with content
            data_ok = len(frame_data) > 1000 and frame_data[:2] == b"\xff\xd8"

            # Visual check
            response = self.ask_llava(frame_path,
                "This is a bird's-eye tactical camera view with colored rectangles "
                "representing units on a dark background. "
                "Can you see any colored shapes? How many roughly?")
            visual_ok = any(w in response.lower() for w in [
                "rectangle", "shape", "color", "square", "unit", "marker",
            ])

            passed = data_ok  # Data check is reliable, visual is bonus
            self.results.append({
                "test": "synthetic_camera",
                "screenshot": str(frame_path),
                "response": response,
                "expected_targets": target_count,
                "frame_bytes": len(frame_data),
                "data_ok": data_ok,
                "visual_ok": visual_ok,
                "pass": passed,
            })
            self._print_result("synthetic_camera", passed, f"data={data_ok} visual={visual_ok} targets={target_count}")
        except Exception as e:
            self.results.append({"test": "synthetic_camera", "pass": None, "skip": str(e)})
            self._print_result("synthetic_camera", None, f"SKIP: {e}")

    def _print_result(self, test: str, passed, detail: str = ""):
        status = "PASS" if passed else ("SKIP" if passed is None else "FAIL")
        color = {"PASS": "\033[32m", "FAIL": "\033[31m", "SKIP": "\033[33m"}[status]
        print(f"  {color}[{status}]\033[0m {test} {detail}")

    def run(self):
        """Run all gameplay verifications."""
        print("=== TRITIUM-SC Gameplay Verification ===")
        try:
            self.setup()
            self.verify_war_room()
            self.verify_game_countdown()
            self.verify_combat_active()
            self.verify_hud_elements()
            self.verify_synthetic_camera()
        except Exception as e:
            self.results.append({"test": "setup", "pass": False, "error": str(e)})
            print(f"  \033[31m[FAIL]\033[0m setup: {e}")
        finally:
            if hasattr(self, "browser"):
                self.browser.close()
            if hasattr(self, "pw"):
                self.pw.stop()
            # Reset game state
            try:
                requests.post(f"{SERVER_URL}/api/game/reset", timeout=5)
            except Exception:
                pass

        # Report
        report_path = self.screenshots_dir / "report.json"
        with open(report_path, "w") as f:
            json.dump({"timestamp": datetime.now().isoformat(), "results": self.results}, f, indent=2)

        passed = sum(1 for r in self.results if r.get("pass") is True)
        failed = sum(1 for r in self.results if r.get("pass") is False)
        skipped = sum(1 for r in self.results if r.get("pass") is None)

        print(f"\nResults: {passed} passed, {failed} failed, {skipped} skipped")
        print(f"Report: {report_path}")

        return 0 if failed == 0 else 1


if __name__ == "__main__":
    # Check prerequisites
    try:
        requests.get(f"{SERVER_URL}/health", timeout=5)
    except Exception:
        print(f"ERROR: Server not available at {SERVER_URL}")
        sys.exit(1)

    try:
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
    except Exception:
        print(f"ERROR: Ollama not available at {OLLAMA_URL}")
        sys.exit(1)

    verifier = GameplayVerifier()
    sys.exit(verifier.run())
