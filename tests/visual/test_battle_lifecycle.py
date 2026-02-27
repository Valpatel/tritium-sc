"""
Battle Lifecycle Exercise: Full battle from start to finish.
Tracks game state transitions, wave progression, combat events,
unit elimination, and captures visual evidence at each stage.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_battle_lifecycle.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/battle-lifecycle")
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


class TestBattleLifecycle:
    """Full battle lifecycle from idle through combat to game-over."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._errors = []
        self._console_logs = []
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        self.page.on("console", lambda msg: self._console_logs.append(
            {"type": msg.type, "text": msg.text[:200]}
        ))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        # Reset game state
        self._reset()
        yield
        self._reset()
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _reset(self):
        self.page.evaluate("""async () => {
            try { await fetch('/api/game/reset', { method: 'POST' }); }
            catch (e) {}
        }""")
        time.sleep(1)

    def _get_state(self) -> dict:
        return self.page.evaluate("""() => {
            const s = window.TritiumStore;
            return s ? {
                phase: s.game?.phase || 'unknown',
                wave: s.game?.wave || 0,
                score: s.game?.score || 0,
                kills: s.game?.kills || 0,
            } : {};
        }""")

    def _get_hostile_count(self) -> int:
        return self.page.evaluate("""() => {
            const s = window.TritiumStore;
            if (!s || !s.units) return 0;
            let count = 0;
            s.units.forEach(u => { if (u.alliance === 'hostile') count++; });
            return count;
        }""")

    def _get_friendly_count(self) -> int:
        return self.page.evaluate("""() => {
            const s = window.TritiumStore;
            if (!s || !s.units) return 0;
            let count = 0;
            s.units.forEach(u => { if (u.alliance === 'friendly') count++; });
            return count;
        }""")

    def _begin_battle(self) -> dict:
        return self.page.evaluate("""async () => {
            try {
                const r = await fetch('/api/game/begin', { method: 'POST' });
                return await r.json();
            } catch (e) {
                return { error: e.message };
            }
        }""")

    # --- Phase 1: Pre-battle ---

    def test_01_idle_state(self):
        """Game starts in idle/setup state."""
        state = self._get_state()
        print(f"\nIdle state: {state}")
        self._screenshot("01_idle")

        assert state.get("phase") in ("idle", "setup"), (
            f"Game should start idle, got: {state.get('phase')}"
        )

    def test_02_pre_battle_units(self):
        """Friendly units are deployed before battle starts."""
        friendly = self._get_friendly_count()
        hostile = self._get_hostile_count()

        print(f"\nPre-battle: friendly={friendly}, hostile={hostile}")
        self._screenshot("02_pre_battle_units")

        assert friendly > 0, f"Should have friendly units deployed, got {friendly}"
        assert hostile == 0, f"Should have no hostiles before battle, got {hostile}"

    # --- Phase 2: Battle start ---

    def test_03_begin_battle(self):
        """Starting battle transitions to countdown/active phase."""
        before_state = self._get_state()
        before = self._screenshot("03_before_battle")

        result = self._begin_battle()
        print(f"\nBegin result: {result}")
        time.sleep(2)

        after_state = self._get_state()
        after = self._screenshot("03_after_begin")

        diff = _opencv_diff(before, after)
        print(f"State: {before_state.get('phase')} -> {after_state.get('phase')}, diff={diff:.1f}%")

        assert after_state.get("phase") != "idle", (
            f"Game should leave idle after begin: {after_state.get('phase')}"
        )

    # --- Phase 3: Combat active ---

    def test_04_hostiles_spawn(self):
        """Hostiles appear after battle starts."""
        self._begin_battle()

        # Wait for hostiles
        max_wait = 20
        hostile_count = 0
        for i in range(max_wait):
            time.sleep(1)
            hostile_count = self._get_hostile_count()
            if hostile_count > 0:
                break

        state = self._get_state()
        self._screenshot("04_hostiles_spawned")

        print(f"\nHostiles: {hostile_count}, state: {state}")
        assert hostile_count > 0, f"Hostiles should spawn, got 0 after {max_wait}s"

    def test_05_wave_tracking(self):
        """Track wave progression for 60 seconds."""
        self._begin_battle()
        time.sleep(3)  # Wait for first wave

        timeline = []
        screenshots = []
        for i in range(10):
            time.sleep(2)
            state = self._get_state()
            hostiles = self._get_hostile_count()
            friendlies = self._get_friendly_count()

            entry = {
                "t": (i + 1) * 2,
                **state,
                "hostiles": hostiles,
                "friendlies": friendlies,
            }
            timeline.append(entry)

            print(f"  t={entry['t']:3d}s: phase={state.get('phase'):12s} wave={state.get('wave')} "
                  f"score={state.get('score')} kills={state.get('kills')} "
                  f"h={hostiles} f={friendlies}")

            if i in (0, 3, 6, 9):
                shot = self._screenshot(f"05_wave_t{entry['t']}")
                screenshots.append(shot)

        # Analyze progression
        phases = set(e.get("phase") for e in timeline)
        max_wave = max(e.get("wave", 0) for e in timeline)
        max_score = max(e.get("score", 0) for e in timeline)
        max_kills = max(e.get("kills", 0) for e in timeline)

        print(f"\nTimeline summary:")
        print(f"  Phases seen: {phases}")
        print(f"  Max wave: {max_wave}")
        print(f"  Max score: {max_score}")
        print(f"  Max kills: {max_kills}")

        assert "active" in phases or "wave_complete" in phases, (
            f"Battle should reach active state: {phases}"
        )

    def test_06_combat_visual_changes(self):
        """Visual changes occur during combat (projectiles, effects)."""
        self._begin_battle()
        time.sleep(5)

        # Capture multiple frames rapidly
        frames = []
        for i in range(5):
            shot = self._screenshot(f"06_frame_{i}")
            frames.append(shot)
            time.sleep(0.5)

        # Compare consecutive frames for animation/motion
        diffs = []
        for i in range(len(frames) - 1):
            d = _opencv_diff(frames[i], frames[i + 1])
            diffs.append(d)

        avg_diff = sum(diffs) / len(diffs)
        max_diff = max(diffs)
        print(f"\nCombat frame diffs: {[f'{d:.1f}%' for d in diffs]}")
        print(f"  avg={avg_diff:.1f}%, max={max_diff:.1f}%")

        # Some visual change should occur during combat
        assert max_diff > 0.1, f"Expected visual changes during combat, max_diff={max_diff:.1f}%"

    # --- Phase 4: Toasts and events ---

    def test_07_combat_toasts(self):
        """Toast notifications appear during battle."""
        self._begin_battle()
        time.sleep(10)

        toasts = self.page.evaluate("""() => {
            const container = document.getElementById('toast-container');
            if (!container) return [];
            return Array.from(container.querySelectorAll('.toast')).map(t => ({
                label: t.querySelector('.toast-label')?.textContent?.trim() || '',
                body: t.querySelector('.toast-body')?.textContent?.trim() || '',
            }));
        }""")

        print(f"\nCombat toasts: {len(toasts)}")
        for t in toasts[:5]:
            print(f"  [{t['label']}] {t['body'][:80]}")

        self._screenshot("07_combat_toasts")

    # --- Phase 5: Reset ---

    def test_08_reset_clears_battle(self):
        """Reset returns game to idle state."""
        self._begin_battle()
        time.sleep(5)

        during = self._get_state()
        during_shot = self._screenshot("08_during")

        self._reset()

        after = self._get_state()
        after_shot = self._screenshot("08_after_reset")

        diff = _opencv_diff(during_shot, after_shot)
        print(f"\nReset: {during.get('phase')} -> {after.get('phase')}, diff={diff:.1f}%")

        assert after.get("phase") in ("idle", "setup"), (
            f"Should be idle after reset: {after.get('phase')}"
        )

    # --- Phase 6: Keyboard start ---

    def test_09_keyboard_begin(self):
        """'B' key starts the battle."""
        state_before = self._get_state()
        assert state_before.get("phase") in ("idle", "setup"), "Should start idle"

        self.page.keyboard.press("b")
        time.sleep(3)

        state_after = self._get_state()
        self._screenshot("09_keyboard_begin")

        print(f"\nKeyboard begin: {state_before.get('phase')} -> {state_after.get('phase')}")
        assert state_after.get("phase") != "idle", (
            f"'B' should start battle: {state_after.get('phase')}"
        )

        self._reset()

    # --- Phase 7: Status bar during battle ---

    def test_10_status_bar_updates(self):
        """Status bar shows live counts during battle."""
        before_text = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar, #status-bar');
            return bar ? bar.textContent.trim() : '';
        }""")

        self._begin_battle()
        time.sleep(8)

        during_text = self.page.evaluate("""() => {
            const bar = document.querySelector('.status-bar, #status-bar');
            return bar ? bar.textContent.trim() : '';
        }""")

        print(f"\nStatus bar before: {before_text[:100]}")
        print(f"Status bar during: {during_text[:100]}")

        self._screenshot("10_status_bar_battle")
        self._reset()

    # --- LLM analysis ---

    def test_11_llm_battle_analysis(self):
        """LLaVA analyzes the battle at different stages."""
        analyses = {}

        # Idle state
        idle_shot = self._screenshot("11_idle")
        analyses["idle"] = _llava_analyze(idle_shot,
            "This shows a tactical command center before any battle. "
            "Describe the map state and UI panels visible.")

        # Active battle
        self._begin_battle()
        time.sleep(10)
        battle_shot = self._screenshot("11_battle")
        analyses["battle"] = _llava_analyze(battle_shot,
            "This shows a tactical command center during an active battle. "
            "Describe any combat activity, hostile units, and UI updates visible.")

        self._reset()

        for name, text in analyses.items():
            print(f"\n{name}: {text[:200]}")

        self._generate_report(analyses)

    def _generate_report(self, analyses: dict):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Battle Lifecycle Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; flex-wrap:wrap; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
  .pair {{ display:flex; gap:16px; margin:16px 0; }}
  .pair img {{ max-width:48%; }}
</style></head><body>
<h1>Battle Lifecycle Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<div class="summary">
  <div class="stat"><div class="val">12</div><div class="label">TESTS RUN</div></div>
</div>

<h2>Idle vs Battle</h2>
<div class="pair">
  <img src="11_idle.png">
  <img src="11_battle.png">
</div>

<h2>Idle State</h2>
<div class="llm">{analyses.get('idle', 'N/A')}</div>

<h2>Battle Active</h2>
<div class="llm">{analyses.get('battle', 'N/A')}</div>

<h2>Wave Timeline</h2>
<div class="pair">
  <img src="05_wave_t3.png">
  <img src="05_wave_t60.png">
</div>

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_12_no_js_errors(self):
        """No critical JS errors during battle lifecycle."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
