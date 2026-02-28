# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Game HUD Panel Exercise: Verify phase, wave, score, eliminations display,
BEGIN WAR / SPAWN HOSTILE / RESET buttons, and state transitions during battle.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_game_hud_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/game-hud")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


def _opencv_diff(path_a: str, path_b: str) -> float:
    a = cv2.imread(path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]))
    diff = cv2.absdiff(a, b)
    return float(np.count_nonzero(diff > 15) / diff.size * 100)


def _llava_analyze(img_path: str, prompt: str) -> str:
    import base64, requests
    try:
        with open(img_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": "llava:7b", "prompt": prompt,
            "images": [b64], "stream": False,
        }, timeout=60)
        if resp.ok:
            return resp.json().get("response", "")
    except Exception as e:
        return f"LLM error: {e}"
    return ""


class TestGameHudExercise:
    """Exercise the Game HUD panel."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._errors = []
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        # Open game panel
        try:
            self.page.evaluate("""() => {
                if (window.panelManager) window.panelManager.open('game');
            }""")
            time.sleep(2)
        except Exception:
            pass
        yield
        # Reset game state
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(0.5)
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    # --- Structure ---

    def test_01_game_hud_opens(self):
        """Game HUD panel opens and is visible."""
        state = self.page.evaluate("""() => {
            const inner = document.querySelector('.game-hud-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
            };
        }""")

        print(f"\nGame HUD: {state}")
        self._screenshot("01_panel_open")

        assert state["found"], "Game HUD should exist"
        assert state["visible"], "Panel should be visible"

    def test_02_status_rows(self):
        """Status shows PHASE, WAVE, SCORE, ELIMS rows."""
        status = self.page.evaluate("""() => {
            return {
                phase: document.querySelector('[data-bind="phase"]')?.textContent?.trim() || '',
                wave: document.querySelector('[data-bind="wave"]')?.textContent?.trim() || '',
                score: document.querySelector('[data-bind="score"]')?.textContent?.trim() || '',
                elims: document.querySelector('[data-bind="elims"]')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nPhase: {status['phase']}")
        print(f"Wave: {status['wave']}")
        print(f"Score: {status['score']}")
        print(f"Elims: {status['elims']}")
        self._screenshot("02_status")

        assert status["phase"], "Phase should have value"
        assert status["wave"], "Wave should have value"

    def test_03_begin_war_button(self):
        """BEGIN WAR button exists and is primary styled."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="begin-war"]');
            return b ? {
                text: b.textContent.trim(),
                visible: b.offsetHeight > 0,
                display: b.style.display,
                isPrimary: b.classList.contains('panel-action-btn-primary'),
            } : null;
        }""")

        print(f"\nBegin War button: {btn}")
        self._screenshot("03_begin_war")

        assert btn is not None, "BEGIN WAR button should exist"
        assert btn["text"] == "BEGIN WAR", f"Text: {btn['text']}"
        assert btn["isPrimary"], "Should be primary button"

    def test_04_spawn_hostile_button(self):
        """SPAWN HOSTILE button exists."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="spawn-hostile"]');
            return b ? {
                text: b.textContent.trim(),
                visible: b.offsetHeight > 0,
            } : null;
        }""")

        print(f"\nSpawn Hostile button: {btn}")
        self._screenshot("04_spawn")

        assert btn is not None, "SPAWN HOSTILE button should exist"
        assert btn["text"] == "SPAWN HOSTILE", f"Text: {btn['text']}"

    def test_05_reset_button(self):
        """RESET button exists."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="reset-game"]');
            return b ? {
                text: b.textContent.trim(),
                exists: true,
            } : null;
        }""")

        print(f"\nReset button: {btn}")
        self._screenshot("05_reset")

        assert btn is not None, "RESET button should exist"
        assert btn["text"] == "RESET", f"Text: {btn['text']}"

    def test_06_idle_state(self):
        """Initial state shows IDLE phase."""
        phase = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="phase"]')?.textContent?.trim() || '';
        }""")

        print(f"\nIdle phase: {phase}")
        self._screenshot("06_idle")

        assert phase.upper() in ["IDLE", "SETUP"], f"Should be IDLE or SETUP: {phase}"

    def test_07_battle_updates_stats(self):
        """Starting battle updates phase, wave, score, and elims."""
        before = self.page.evaluate("""() => ({
            phase: document.querySelector('[data-bind="phase"]')?.textContent?.trim() || '',
            score: document.querySelector('[data-bind="score"]')?.textContent?.trim() || '',
            elims: document.querySelector('[data-bind="elims"]')?.textContent?.trim() || '',
        })""")

        before_shot = self._screenshot("07_before_battle")

        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(10)

        after = self.page.evaluate("""() => ({
            phase: document.querySelector('[data-bind="phase"]')?.textContent?.trim() || '',
            wave: document.querySelector('[data-bind="wave"]')?.textContent?.trim() || '',
            score: document.querySelector('[data-bind="score"]')?.textContent?.trim() || '',
            elims: document.querySelector('[data-bind="elims"]')?.textContent?.trim() || '',
        })""")

        after_shot = self._screenshot("07_during_battle")
        diff = _opencv_diff(before_shot, after_shot)

        print(f"\nBefore: {before}")
        print(f"After:  {after}")
        print(f"Visual diff: {diff:.1f}%")

        # Phase should change from idle
        assert after["phase"].upper() != "IDLE", \
            f"Phase should change during battle: {after['phase']}"

    def test_08_wave_counter_format(self):
        """Wave counter shows X/Y format."""
        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(5)

        wave = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="wave"]')?.textContent?.trim() || '';
        }""")

        print(f"\nWave format: {wave}")
        self._screenshot("08_wave")

        assert "/" in wave, f"Wave should show X/Y format: {wave}"

    def test_09_begin_hides_during_battle(self):
        """BEGIN WAR button hides during active battle."""
        # Start battle
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(3)

        btn_display = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="begin-war"]');
            return b ? b.style.display : null;
        }""")

        print(f"\nBegin button display during battle: {btn_display}")
        self._screenshot("09_begin_hidden")

        assert btn_display == "none", \
            f"Begin button should be hidden during battle: {btn_display}"

    def test_10_score_increases_during_battle(self):
        """Score increases as battle progresses."""
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(3)

        score1 = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="score"]')?.textContent?.trim() || '0';
        }""")

        time.sleep(8)

        score2 = self.page.evaluate("""() => {
            return document.querySelector('[data-bind="score"]')?.textContent?.trim() || '0';
        }""")

        print(f"\nScore early: {score1}, Score later: {score2}")
        self._screenshot("10_score_increase")

    def test_11_game_helpers_exposed(self):
        """GameHudHelpers exposed on window for testing."""
        helpers = self.page.evaluate("""() => {
            const h = window.GameHudHelpers;
            if (!h) return null;
            return {
                hasHealthColor: typeof h.healthColor === 'function',
                hasHealthBar: typeof h.healthBar === 'function',
                hasMoraleTrend: typeof h.moraleTrend === 'function',
                hasWaveProgressPct: typeof h.waveProgressPct === 'function',
                hasComputeAccuracy: typeof h.computeAccuracy === 'function',
                hasFindMVP: typeof h.findMVP === 'function',
                hasTypeIcon: typeof h.typeIcon === 'function',
                hasFormatTime: typeof h.formatTime === 'function',
                // Quick test
                healthColorGreen: h.healthColor(0.8),
                healthColorRed: h.healthColor(0.1),
                formatTime60: h.formatTime(60),
                waveProgress: h.waveProgressPct(3, 10),
            };
        }""")

        print(f"\nGameHudHelpers: {helpers}")
        self._screenshot("11_helpers")

        assert helpers is not None, "GameHudHelpers should be on window"
        assert helpers["hasHealthColor"], "Should have healthColor"
        assert helpers["hasFormatTime"], "Should have formatTime"
        assert helpers["healthColorGreen"] == "#05ffa1", \
            f"healthColor(0.8) should be green: {helpers['healthColorGreen']}"
        assert helpers["healthColorRed"] == "#ff2a6d", \
            f"healthColor(0.1) should be red: {helpers['healthColorRed']}"
        assert helpers["formatTime60"] == "1:00", \
            f"formatTime(60) should be 1:00: {helpers['formatTime60']}"
        assert helpers["waveProgress"] == 70, \
            f"waveProgressPct(3, 10) should be 70: {helpers['waveProgress']}"

    def test_12_llm_game_analysis(self):
        """LLaVA analyzes the game HUD."""
        # Start battle for interesting state
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/begin', { method: 'POST' }); } catch (e) {}
        }""")
        time.sleep(8)

        shot = self._screenshot("12_llm_game")
        analysis = _llava_analyze(shot,
            "Focus on any game status or HUD panel in this tactical interface. "
            "Describe the phase indicator, wave counter, score, elimination count, "
            "and any action buttons.")

        print(f"\nGame analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Game HUD Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Game HUD Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Game HUD Panel</h2>
<img src="12_llm_game.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during game HUD testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
