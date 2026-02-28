# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""
Audio Panel Exercise: Verify volume controls, mute toggle, category filters,
sound effects list, play buttons, and stop-all functionality.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_audio_panel_exercise.py -v -s
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import pytest

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/audio-panel")
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


class TestAudioPanelExercise:
    """Exercise all audio panel features and controls."""

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
        # Open audio panel via panel manager
        self.page.evaluate("""() => {
            if (window.panelManager) window.panelManager.open('audio');
        }""")
        time.sleep(2)
        yield
        self._browser.close()
        self._pw.stop()

    def _screenshot(self, name: str) -> str:
        path = str(SCREENSHOT_DIR / f"{name}.png")
        self.page.screenshot(path=path)
        return path

    def _get_audio_panel(self) -> dict:
        return self.page.evaluate("""() => {
            const inner = document.querySelector('.audio-panel-inner');
            if (!inner) return { found: false };
            return {
                found: true,
                visible: inner.offsetHeight > 0,
                width: inner.offsetWidth,
                height: inner.offsetHeight,
            };
        }""")

    # --- Structure ---

    def test_01_audio_panel_opens(self):
        """Audio panel opens and is visible."""
        panel = self._get_audio_panel()
        print(f"\nAudio panel: {panel}")
        self._screenshot("01_panel_open")

        assert panel["found"], "Audio panel inner should exist"
        assert panel["visible"], "Audio panel should be visible"

    def test_02_master_volume_slider(self):
        """Master volume slider exists with correct default."""
        slider = self.page.evaluate("""() => {
            const s = document.querySelector('.audio-volume-slider');
            if (!s) return null;
            return {
                value: parseInt(s.value, 10),
                min: parseInt(s.min, 10),
                max: parseInt(s.max, 10),
            };
        }""")

        label = self.page.evaluate("""() => {
            const l = document.querySelector('[data-bind="master-vol-label"]');
            return l ? l.textContent.trim() : null;
        }""")

        print(f"\nVolume slider: {slider}")
        print(f"Volume label: {label}")
        self._screenshot("02_volume_slider")

        assert slider is not None, "Volume slider should exist"
        assert slider["value"] == 80, f"Default volume should be 80, got {slider['value']}"
        assert slider["min"] == 0, "Min should be 0"
        assert slider["max"] == 100, "Max should be 100"
        assert label == "80%", f"Label should show 80%, got {label}"

    def test_03_volume_slider_changes(self):
        """Adjusting volume slider updates the label."""
        before = self._screenshot("03_before_vol")

        # Set slider to 40
        self.page.evaluate("""() => {
            const s = document.querySelector('.audio-volume-slider');
            if (s) {
                s.value = 40;
                s.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }""")
        time.sleep(0.5)

        label = self.page.evaluate("""() => {
            const l = document.querySelector('[data-bind="master-vol-label"]');
            return l ? l.textContent.trim() : null;
        }""")

        after = self._screenshot("03_after_vol")
        diff = _opencv_diff(before, after)

        print(f"\nAfter volume change: label={label}, diff={diff:.1f}%")
        assert label == "40%", f"Label should show 40%, got {label}"

    def test_04_mute_button(self):
        """Mute button toggles state."""
        btn_before = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="mute"]');
            return b ? { text: b.textContent.trim(), primary: b.classList.contains('panel-action-btn-primary') } : null;
        }""")

        # Click mute
        self.page.click('[data-action="mute"]')
        time.sleep(0.5)

        btn_after = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="mute"]');
            return b ? { text: b.textContent.trim(), primary: b.classList.contains('panel-action-btn-primary') } : null;
        }""")

        self._screenshot("04_mute_toggle")

        print(f"\nBefore mute: {btn_before}")
        print(f"After mute: {btn_after}")

        assert btn_before["text"] == "MUTE", f"Initial: {btn_before['text']}"
        assert btn_after["text"] == "UNMUTE", f"After mute: {btn_after['text']}"
        assert btn_after["primary"], "Muted button should have primary class"

    def test_05_stop_all_button(self):
        """Stop All button exists and is clickable."""
        btn = self.page.evaluate("""() => {
            const b = document.querySelector('[data-action="stop-all"]');
            return b ? { text: b.textContent.trim(), visible: b.offsetHeight > 0 } : null;
        }""")

        print(f"\nStop All button: {btn}")
        self._screenshot("05_stop_all")

        assert btn is not None, "Stop All button should exist"
        assert btn["text"] == "STOP ALL", f"Button text: {btn['text']}"
        assert btn["visible"], "Button should be visible"

    def test_06_category_buttons(self):
        """Category filter buttons exist with correct labels."""
        cats = self.page.evaluate("""() => {
            const btns = document.querySelectorAll('.audio-cat-btn');
            return Array.from(btns).map(b => ({
                text: b.textContent.trim(),
                active: b.classList.contains('active'),
                cat: b.dataset.cat,
            }));
        }""")

        print(f"\nCategories ({len(cats)}):")
        for c in cats:
            active = "ACTIVE" if c["active"] else "      "
            print(f"  [{active}] {c['text']} (data-cat={c['cat']})")

        self._screenshot("06_categories")

        assert len(cats) == 6, f"Should have 6 category buttons, got {len(cats)}"
        expected = ['ALL', 'COMBAT', 'AMBIENT', 'UI', 'VOICE', 'ALERT']
        actual = [c["text"] for c in cats]
        assert actual == expected, f"Categories: {actual}"

        active_cats = [c for c in cats if c["active"]]
        assert len(active_cats) == 1, f"Exactly one active: {active_cats}"
        assert active_cats[0]["text"] == "ALL", "ALL should be active by default"

    def test_07_category_filter_switches(self):
        """Clicking a category filters the effects list."""
        before = self._screenshot("07_before_filter")

        # Click 'COMBAT' category
        self.page.click('.audio-cat-btn[data-cat="combat"]')
        time.sleep(1)

        active = self.page.evaluate("""() => {
            const btns = document.querySelectorAll('.audio-cat-btn');
            const active = Array.from(btns).find(b => b.classList.contains('active'));
            return active ? active.dataset.cat : null;
        }""")

        after = self._screenshot("07_after_filter")
        diff = _opencv_diff(before, after)

        print(f"\nActive category after click: {active}, diff={diff:.1f}%")
        assert active == "combat", f"Active should be 'combat', got {active}"

    def test_08_effects_list_loaded(self):
        """Effects list loads from /api/audio/effects."""
        # Wait for effects to load
        time.sleep(2)

        effects = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.audio-effect-item');
            if (items.length === 0) {
                const empty = document.querySelector('.audio-effects-list .panel-empty');
                return { count: 0, empty: empty ? empty.textContent.trim() : null };
            }
            return {
                count: items.length,
                first: items[0]?.querySelector('.audio-effect-name')?.textContent?.trim() || '',
                last: items[items.length - 1]?.querySelector('.audio-effect-name')?.textContent?.trim() || '',
            };
        }""")

        print(f"\nEffects list: {effects}")
        self._screenshot("08_effects_list")

        assert effects["count"] > 0, f"Should have sound effects loaded: {effects}"

    def test_09_effect_items_have_play_buttons(self):
        """Each effect item has a play button."""
        time.sleep(1)
        play_btns = self.page.evaluate("""() => {
            const btns = document.querySelectorAll('.audio-play-btn');
            return { count: btns.length };
        }""")

        items = self.page.evaluate("""() => {
            return document.querySelectorAll('.audio-effect-item').length;
        }""")

        print(f"\nPlay buttons: {play_btns['count']}, Effect items: {items}")
        self._screenshot("09_play_buttons")

        assert play_btns["count"] > 0, "Should have play buttons"
        assert play_btns["count"] == items, f"Play buttons ({play_btns['count']}) should match items ({items})"

    def test_10_effect_metadata_displayed(self):
        """Effect items show category and duration metadata."""
        time.sleep(1)
        meta = self.page.evaluate("""() => {
            const items = document.querySelectorAll('.audio-effect-item');
            const results = [];
            for (const item of Array.from(items).slice(0, 5)) {
                const name = item.querySelector('.audio-effect-name')?.textContent?.trim() || '';
                const meta = item.querySelector('.audio-effect-meta')?.textContent?.trim() || '';
                results.push({ name, meta });
            }
            return results;
        }""")

        print(f"\nEffect metadata (first 5):")
        for m in meta:
            print(f"  {m['name']:30s} | {m['meta']}")

        self._screenshot("10_metadata")

        assert len(meta) > 0, "Should have effect metadata"
        # At least some should have category info
        has_meta = any(m["meta"] for m in meta)
        assert has_meta, "At least some effects should have metadata"

    def test_11_effects_list_role(self):
        """Effects list has proper ARIA role."""
        role = self.page.evaluate("""() => {
            const list = document.querySelector('.audio-effects-list');
            return list ? {
                role: list.getAttribute('role'),
                label: list.getAttribute('aria-label'),
            } : null;
        }""")

        print(f"\nARIA: {role}")
        assert role is not None, "Effects list should exist"
        assert role["role"] == "listbox", f"Role should be listbox: {role['role']}"
        assert role["label"] == "Sound effects", f"Label: {role['label']}"

    def test_12_llm_audio_panel_analysis(self):
        """LLaVA analyzes the audio panel."""
        shot = self._screenshot("12_llm_audio")
        analysis = _llava_analyze(shot,
            "Focus on any audio control panel visible in this tactical interface. "
            "Describe the volume slider, mute button, category filters, and sound effects list.")

        print(f"\nAudio panel analysis: {analysis[:200]}")
        self._generate_report(analysis)

    def _generate_report(self, analysis: str):
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Audio Panel Exercise Report</title>
<style>
  body {{ background:#0a0a0f; color:#c0c0c0; font-family:'JetBrains Mono',monospace; margin:20px; }}
  h1 {{ color:#00f0ff; border-bottom:2px solid #00f0ff33; padding-bottom:8px; }}
  h2 {{ color:#ff2a6d; margin-top:32px; }}
  .llm {{ background:#111; border:1px solid #333; padding:16px; margin:16px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
  img {{ border:1px solid #333; border-radius:2px; max-width:100%; }}
</style></head><body>
<h1>Audio Panel Exercise Report</h1>
<p>Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}</p>

<h2>Audio Panel</h2>
<img src="12_llm_audio.png" style="max-width:100%;">
<div class="llm">{analysis}</div>

<h2>Volume Controls</h2>
<img src="03_after_vol.png" style="max-width:48%;display:inline">
<img src="04_mute_toggle.png" style="max-width:48%;display:inline">

<h2>Category Filter</h2>
<img src="07_after_filter.png" style="max-width:100%;">

</body></html>"""
        REPORT_PATH.write_text(html)
        print(f"\nReport: {REPORT_PATH}")

    def test_13_no_js_errors(self):
        """No critical JS errors during audio panel testing."""
        critical = [e for e in self._errors if "TypeError" in e or "ReferenceError" in e]
        if critical:
            print(f"Critical JS errors: {critical}")
        assert len(critical) == 0, f"JS errors: {critical}"
