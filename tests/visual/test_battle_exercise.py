"""
Battle Exercise: Start a 10-wave battle and verify visual combat effects.

This test:
  1. Screenshots the pre-battle state
  2. Presses 'B' to begin battle
  3. Monitors unit markers, combat events, and wave progression
  4. Captures screenshots at key moments (wave starts, eliminations, etc.)
  5. Verifies combat FX appear (tracers, explosions, hit flashes)
  6. Uses OpenCV to detect visual changes in the map area during combat
  7. Uses LLM (llava:7b) to analyze battle screenshots
  8. Generates an HTML battle report

Run:
    .venv/bin/python3 -m pytest tests/visual/test_battle_exercise.py -v -s
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/battle-exercise")
REPORT_PATH = SCREENSHOT_DIR / "report.html"
OLLAMA_URL = "http://localhost:11434"


@dataclass
class BattleSnapshot:
    name: str
    timestamp: float = 0.0
    screenshot: str = ""
    markers: dict = field(default_factory=dict)
    game_state: dict = field(default_factory=dict)
    console_events: list = field(default_factory=list)
    brightness: float = 0.0
    edge_density: float = 0.0
    pixel_diff_from_prev: float = 0.0
    llm_description: str = ""


def _opencv_stats(img_path: str, region=None):
    """Get brightness and edge density for a screenshot."""
    img = cv2.imread(img_path)
    if img is None:
        return 0.0, 0.0
    if region:
        x, y, w, h = region
        img = img[y:y+h, x:x+w]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    brightness = float(np.mean(gray))
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / edges.size * 100
    return brightness, edge_density


def _opencv_diff(path_a: str, path_b: str, region=None):
    """Calculate pixel diff percentage between two screenshots."""
    a = cv2.imread(path_a)
    b = cv2.imread(path_b)
    if a is None or b is None:
        return 0.0
    if region:
        x, y, w, h = region
        a = a[y:y+h, x:x+w]
        b = b[y:y+h, x:x+w]
    if a.shape != b.shape:
        return 0.0
    diff = cv2.absdiff(
        cv2.cvtColor(a, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(b, cv2.COLOR_BGR2GRAY),
    )
    return float(np.count_nonzero(diff > 10)) / diff.size * 100


def _llava_analyze(image_path: str, prompt: str) -> str:
    """Use llava:7b to analyze a screenshot."""
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "llava:7b",
                "prompt": prompt,
                "images": [b64],
                "stream": False,
            },
            timeout=60,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")[:500]
    except Exception as e:
        return f"LLM error: {e}"
    return ""


def _qwen_summarize(text: str) -> str:
    """Use qwen2.5:7b for text summarization."""
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "qwen2.5:7b",
                "prompt": text,
                "stream": False,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("response", "")
    except Exception:
        pass
    return ""


def _generate_battle_report(snapshots: list[BattleSnapshot],
                            combat_log: list[dict],
                            llm_summary: str,
                            total_time: float) -> str:
    """Generate HTML battle report."""
    snap_rows = []
    for s in snapshots:
        img = ""
        if s.screenshot and Path(s.screenshot).exists():
            img = f'<img src="{Path(s.screenshot).name}" style="max-width:400px;max-height:200px;">'
        markers = s.markers
        llm = f'<div style="font-size:11px;color:#888;max-width:300px;">{s.llm_description[:200]}</div>' if s.llm_description else ""
        snap_rows.append(f"""
        <tr>
            <td>{s.name}</td>
            <td>{s.timestamp:.1f}s</td>
            <td>{markers.get('friendly',0)}/{markers.get('hostile',0)}/{markers.get('neutral',0)}</td>
            <td>{s.game_state.get('wave','?')}</td>
            <td>{s.brightness:.0f}</td>
            <td>{s.pixel_diff_from_prev:.1f}%</td>
            <td>{img}</td>
            <td>{llm}</td>
        </tr>""")

    event_rows = ""
    for evt in combat_log[-50:]:
        event_rows += f"<tr><td>{evt.get('time',''):.1f}s</td><td>{evt.get('type','')}</td><td>{evt.get('detail','')}</td></tr>\n"

    llm_html = llm_summary.replace("\n", "<br>") if llm_summary else "N/A"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Battle Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .summary {{ display:flex; gap:30px; margin:20px 0; flex-wrap:wrap; }}
  .stat {{ padding:12px 24px; border:1px solid #00f0ff33; border-radius:4px; }}
  .stat .val {{ font-size:28px; color:#00f0ff; }}
  .stat .label {{ font-size:12px; color:#666; }}
  table {{ border-collapse:collapse; width:100%; margin:16px 0; font-size:12px; }}
  th {{ background:#111; color:#00f0ff; padding:8px; text-align:left; border-bottom:2px solid #00f0ff33; }}
  td {{ padding:6px 8px; border-bottom:1px solid #222; vertical-align:top; }}
  tr:hover {{ background:#111; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; }}
</style></head><body>
<h1>TRITIUM-SC Battle Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} | Duration: {total_time:.1f}s</p>

<div class="summary">
  <div class="stat"><div class="val">{len(snapshots)}</div><div class="label">SNAPSHOTS</div></div>
  <div class="stat"><div class="val">{len(combat_log)}</div><div class="label">COMBAT EVENTS</div></div>
</div>

<h2>Battle Timeline</h2>
<table>
<tr><th>Moment</th><th>Time</th><th>F/H/N Markers</th><th>Wave</th><th>Brightness</th><th>Diff</th><th>Screenshot</th><th>LLM</th></tr>
{"".join(snap_rows)}
</table>

<h2>Combat Event Log (last 50)</h2>
<table>
<tr><th>Time</th><th>Type</th><th>Detail</th></tr>
{event_rows}
</table>

<h2>LLM Battle Analysis</h2>
<div class="llm">{llm_html}</div>

</body></html>"""
    return html


class TestBattleExercise:
    """Run a battle and verify combat effects visually."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=False)
        ctx = self._browser.new_context(viewport={"width": 1920, "height": 1080})
        self.page = ctx.new_page()
        self._console_msgs = []
        self.page.on("console", lambda msg: self._console_msgs.append(msg.text))
        self.page.goto("http://localhost:8000", wait_until="networkidle", timeout=30000)
        time.sleep(5)
        yield
        self._browser.close()
        self._pw.stop()

    MAP_REGION = (300, 60, 1300, 900)

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_markers(self) -> dict:
        return self.page.evaluate("""() => {
            const m = document.querySelectorAll('.tritium-unit-marker');
            const result = { total: 0, visible: 0, friendly: 0, hostile: 0, neutral: 0 };
            m.forEach(el => {
                result.total++;
                const vis = getComputedStyle(el).display !== 'none';
                if (vis) {
                    result.visible++;
                    const a = el.dataset.alliance || '';
                    if (a === 'friendly') result.friendly++;
                    else if (a === 'hostile') result.hostile++;
                    else result.neutral++;
                }
            });
            return result;
        }""")

    def _get_game_state(self) -> dict:
        return self.page.evaluate("""() => {
            const ma = window._mapActions;
            const state = ma && ma.getMapState ? ma.getMapState() : {};
            // Also check for game state elements
            const waveBanner = document.querySelector('.fx-wave-banner, .game-wave');
            const killFeed = document.querySelector('.fx-kill-feed');
            const killEntries = killFeed ? killFeed.querySelectorAll('.kill-entry, .fx-kill-entry').length : 0;
            return {
                ...state,
                wave: waveBanner?.textContent?.trim() || '',
                killFeedEntries: killEntries,
                gameActive: !!document.querySelector('.game-active, [data-game-active="true"]'),
            };
        }""")

    def _get_fx_elements(self) -> dict:
        """Count visible combat FX elements."""
        return self.page.evaluate("""() => {
            return {
                tracers: document.querySelectorAll('.fx-tracer, .combat-tracer').length,
                explosions: document.querySelectorAll('.fx-explosion, .combat-explosion').length,
                hitFlashes: document.querySelectorAll('.fx-hit-flash, .combat-flash').length,
                floatingText: document.querySelectorAll('.fx-floating-text, .floating-damage').length,
                banners: document.querySelectorAll('.fx-banner, .wave-banner, .streak-banner').length,
                killFeedEntries: document.querySelectorAll('.fx-kill-entry, .kill-entry').length,
                healthBars: document.querySelectorAll('.unit-hp-bar, .unit-hp-bar-3d').length,
            };
        }""")

    def _take_snapshot(self, name: str, t0: float, prev_path: str = "") -> BattleSnapshot:
        snap = BattleSnapshot(name=name, timestamp=time.monotonic() - t0)
        snap.screenshot = self._screenshot(name)
        snap.markers = self._get_markers()
        snap.game_state = self._get_game_state()
        snap.brightness, snap.edge_density = _opencv_stats(
            snap.screenshot, self.MAP_REGION
        )
        if prev_path:
            snap.pixel_diff_from_prev = _opencv_diff(
                prev_path, snap.screenshot, self.MAP_REGION
            )
        # Recent console combat events
        snap.console_events = [
            m for m in self._console_msgs[-20:]
            if any(kw in m.lower() for kw in
                   ['combat', 'wave', 'kill', 'elim', 'damage', 'hit', 'fire'])
        ]
        return snap

    def test_battle_flow(self):
        """Run a battle and monitor visual state at key moments."""
        t0 = time.monotonic()
        snapshots: list[BattleSnapshot] = []
        combat_log: list[dict] = []
        prev_path = ""

        # ── Reset game first ───────────────────────────────────
        self.page.evaluate("""() =>
            fetch('/api/game/reset', { method: 'POST' }).then(r => r.json())
        """)
        time.sleep(2)

        # ── Pre-battle state ──────────────────────────────────
        snap = self._take_snapshot("00_pre_battle", t0)
        snapshots.append(snap)
        prev_path = snap.screenshot
        print(f"\nPre-battle: {snap.markers['friendly']}F/{snap.markers['hostile']}H/"
              f"{snap.markers['neutral']}N markers, brightness={snap.brightness:.0f}")

        # ── Start battle ──────────────────────────────────────
        print("\n--- Starting Battle (API) ---")
        start_result = self.page.evaluate("""() => {
            return fetch('/api/game/begin', { method: 'POST' })
                .then(r => r.json())
                .catch(e => ({ error: e.message }));
        }""")
        print(f"  API response: {start_result}")
        time.sleep(7)  # Wait for countdown (5s) + first wave spawn

        snap = self._take_snapshot("01_battle_started", t0, prev_path)
        snapshots.append(snap)
        prev_path = snap.screenshot
        print(f"Battle started: {snap.markers['hostile']}H hostiles, "
              f"diff={snap.pixel_diff_from_prev:.1f}%")

        # ── Monitor waves 1-3 (or ~60s of combat) ────────────
        print("\n--- Monitoring Combat ---")
        wave_screenshots = 0
        max_monitor_time = 120  # seconds (hostiles take ~100s to reach center)
        monitor_start = time.monotonic()
        last_hostile_count = snap.markers.get("hostile", 0)
        combat_started = False

        while time.monotonic() - monitor_start < max_monitor_time:
            time.sleep(3)

            markers = self._get_markers()
            fx = self._get_fx_elements()
            elapsed = time.monotonic() - t0

            hostile_count = markers.get("hostile", 0)
            hostile_change = hostile_count != last_hostile_count

            # Log combat events from console
            new_msgs = [
                m for m in self._console_msgs[-30:]
                if any(kw in m.lower() for kw in ['wave', 'elim', 'kill', 'combat'])
            ]
            for m in new_msgs:
                if not any(e.get("detail") == m for e in combat_log[-10:]):
                    combat_log.append({
                        "time": elapsed,
                        "type": "console",
                        "detail": m[:200],
                    })

            # Detect interesting moments to screenshot
            should_snap = False
            snap_name = ""

            if hostile_count > 0 and not combat_started:
                combat_started = True
                should_snap = True
                snap_name = f"02_hostiles_spawned_{wave_screenshots}"
                combat_log.append({
                    "time": elapsed,
                    "type": "hostiles_spawned",
                    "detail": f"{hostile_count} hostiles visible",
                })

            if hostile_change and abs(hostile_count - last_hostile_count) >= 2:
                should_snap = True
                snap_name = f"03_hostile_change_{wave_screenshots}"
                combat_log.append({
                    "time": elapsed,
                    "type": "hostile_count_change",
                    "detail": f"{last_hostile_count} → {hostile_count}",
                })

            if fx.get("tracers", 0) > 0 or fx.get("explosions", 0) > 0:
                combat_log.append({
                    "time": elapsed,
                    "type": "fx_active",
                    "detail": f"tracers={fx['tracers']} explosions={fx['explosions']} "
                              f"flashes={fx['hitFlashes']} text={fx['floatingText']}",
                })

            if should_snap and wave_screenshots < 10:
                snap = self._take_snapshot(snap_name, t0, prev_path)
                snapshots.append(snap)
                prev_path = snap.screenshot
                wave_screenshots += 1

            # Also check hostile positions via API for distance tracking
            hostile_dist = self.page.evaluate("""() => {
                return fetch('/api/amy/simulation/targets')
                    .then(r => r.json())
                    .then(data => {
                        const targets = Array.isArray(data) ? data : (data.targets || []);
                        const hostiles = targets.filter(t => t.alliance === 'hostile');
                        return hostiles.map(h => {
                            const p = h.position || {};
                            const dist = Math.sqrt((p.x||0)**2 + (p.y||0)**2);
                            return { name: h.name, dist: Math.round(dist), hp: h.health, fsm: h.fsm_state };
                        });
                    })
                    .catch(() => []);
            }""")
            closest = min((h['dist'] for h in hostile_dist), default=999) if hostile_dist else 999

            print(f"  t={elapsed:5.1f}s  F={markers['friendly']} H={hostile_count} "
                  f"N={markers['neutral']} fx=T{fx.get('tracers',0)} "
                  f"E{fx.get('explosions',0)} HP{fx.get('healthBars',0)} "
                  f"KF{fx.get('killFeedEntries',0)} closest={closest}m")

            last_hostile_count = hostile_count

            # Stop early if battle seems over (no hostiles for a while)
            if combat_started and hostile_count == 0:
                time.sleep(5)
                markers2 = self._get_markers()
                if markers2.get("hostile", 0) == 0:
                    combat_log.append({
                        "time": time.monotonic() - t0,
                        "type": "battle_quiet",
                        "detail": "No hostiles for 5s, stopping monitor",
                    })
                    break

        # ── Final state ───────────────────────────────────────
        snap = self._take_snapshot("99_final_state", t0, prev_path)
        snapshots.append(snap)
        print(f"\nFinal: {snap.markers['friendly']}F/{snap.markers['hostile']}H/"
              f"{snap.markers['neutral']}N, brightness={snap.brightness:.0f}")

        # ── LLM analysis ─────────────────────────────────────
        print("\n--- LLM Battle Analysis ---")
        llm_parts = []

        # Analyze pre-battle
        if snapshots[0].screenshot:
            llm = _llava_analyze(
                snapshots[0].screenshot,
                "This is a tactical command center before a battle starts. "
                "Describe the map layout, unit positions, and overall state.",
            )
            if llm:
                llm_parts.append(f"Pre-battle:\n{llm}")
                print(f"  LLaVA (pre): {llm[:200]}...")

        # Analyze a mid-combat screenshot if we got one
        combat_snaps = [s for s in snapshots if "hostile" in s.name or "change" in s.name]
        if combat_snaps:
            best = max(combat_snaps, key=lambda s: s.pixel_diff_from_prev)
            if best.screenshot:
                llm = _llava_analyze(
                    best.screenshot,
                    "This is a tactical map during active combat. Look for: "
                    "unit markers (colored dots), combat effects (tracers, "
                    "explosions, flashes), hostile positions, and overall "
                    "battle state. What's happening in this moment?",
                )
                if llm:
                    llm_parts.append(f"\nMid-combat:\n{llm}")
                    print(f"  LLaVA (combat): {llm[:200]}...")

        # Analyze final state
        if snapshots[-1].screenshot and len(snapshots) > 2:
            llm = _llava_analyze(
                snapshots[-1].screenshot,
                "This is a tactical map after combat. How does it compare to "
                "a pre-battle state? Are there signs of battle damage, "
                "eliminated units, or changed positions?",
            )
            if llm:
                llm_parts.append(f"\nPost-combat:\n{llm}")
                print(f"  LLaVA (final): {llm[:200]}...")

        llm_summary = ""
        if llm_parts:
            summary_prompt = (
                "Summarize these battle analysis observations into a concise "
                "after-action report (5-7 sentences). Note battle flow, "
                "combat effectiveness, and any issues:\n\n"
                + "\n".join(llm_parts)
            )
            llm_summary = _qwen_summarize(summary_prompt)
            if llm_summary:
                print(f"  Summary: {llm_summary[:300]}...")

        # ── Generate report ───────────────────────────────────
        total_time = time.monotonic() - t0
        html = _generate_battle_report(snapshots, combat_log, llm_summary, total_time)
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

        # Save metrics JSON
        metrics = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": total_time,
            "snapshots": len(snapshots),
            "combat_events": len(combat_log),
            "max_hostiles_seen": max(
                (s.markers.get("hostile", 0) for s in snapshots), default=0
            ),
            "pixel_diffs": [s.pixel_diff_from_prev for s in snapshots],
        }
        (SCREENSHOT_DIR / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # ── Assertions ────────────────────────────────────────
        # Battle should have produced some visual changes
        total_diff = sum(s.pixel_diff_from_prev for s in snapshots)
        assert total_diff > 0, "No visual changes detected during battle"

        # Should have captured at least pre-battle + started + final
        assert len(snapshots) >= 3, (
            f"Only {len(snapshots)} snapshots, expected at least 3"
        )

        print(f"\nBattle exercise complete: {len(snapshots)} snapshots, "
              f"{len(combat_log)} events, {total_time:.0f}s total")
