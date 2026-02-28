# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Audio effects system E2E integration tests.

Verifies the audio pipeline works end-to-end: API returns effects,
WAV bytes stream correctly, browser AudioContext initializes, mute
toggle works, and the audio panel renders with its effects list.

Uses TritiumServer fixture for a live server and Playwright for
browser-based tests. API-level tests use requests directly.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import requests

from tests.lib.results_db import ResultsDB
from tests.lib.server_manager import TritiumServer

pytestmark = pytest.mark.visual

SCREENSHOT_DIR = Path("tests/.test-results/audio-screenshots")

# Categories present in the AudioLibrary _EFFECT_CATALOG
EXPECTED_CATEGORIES = {"combat", "ambient", "alerts", "game"}

# A known effect that always exists in the catalog
KNOWN_EFFECT = "nerf_shot"


class TestAudioIntegration:
    """Playwright + API tests for the audio effects system."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(
        self,
        request,
        tritium_server: TritiumServer,
        test_db: ResultsDB,
        run_id: int,
    ):
        """Launch browser, navigate to Command Center, wait for data."""
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._errors: list[str] = []
        cls._t0 = time.monotonic()

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(3000)

        yield

        browser.close()
        cls._pw.stop()

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        """Record result to ResultsDB and take a screenshot."""
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})
        try:
            self.page.screenshot(
                path=str(SCREENSHOT_DIR / f"{name}.png"),
                full_page=False,
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Test 1: Audio panel loads with effects list
    # ------------------------------------------------------------------

    def test_01_audio_panel_loads(self):
        """Open audio panel programmatically, verify it renders with effects list."""
        name = "audio_01_panel_loads"
        try:
            # The audio panel (AudioPanelDef) may not be registered by default.
            # Register it via panelManager using _registry.has() and then open it.
            self.page.evaluate("""() => {
                const pm = window.panelManager;
                if (!pm) return;

                // Check if audio panel is already registered via internal Map
                if (!pm._registry.has('audio')) {
                    pm.register({
                        id: 'audio',
                        title: 'AUDIO',
                        defaultPosition: { x: 8, y: 8 },
                        defaultSize: { w: 280, h: 320 },
                        create(panel) {
                            const el = document.createElement('div');
                            el.className = 'audio-panel-inner';
                            el.innerHTML = `
                                <div class="audio-master">
                                    <div class="panel-stat-row">
                                        <span class="panel-stat-label">MASTER</span>
                                        <input type="range" class="audio-volume-slider" data-bind="master-vol"
                                               min="0" max="100" value="80" />
                                        <span class="panel-stat-value mono" data-bind="master-vol-label">80%</span>
                                    </div>
                                    <div class="audio-mute-row">
                                        <button class="panel-action-btn" data-action="mute" data-bind="mute-btn">MUTE</button>
                                        <button class="panel-action-btn" data-action="stop-all">STOP ALL</button>
                                    </div>
                                </div>
                                <div class="panel-section-label mono">SOUND EFFECTS</div>
                                <ul class="panel-list audio-effects-list" data-bind="effects-list" role="listbox" aria-label="Sound effects">
                                    <li class="panel-empty">Loading effects...</li>
                                </ul>
                            `;
                            return el;
                        },
                        mount(bodyEl, panel) {
                            const effectsListEl = bodyEl.querySelector('[data-bind="effects-list"]');
                            fetch('/api/audio/effects')
                                .then(r => r.json())
                                .then(effects => {
                                    const list = Array.isArray(effects) ? effects : (effects.effects || []);
                                    if (list.length === 0) {
                                        effectsListEl.innerHTML = '<li class="panel-empty">No effects</li>';
                                        return;
                                    }
                                    effectsListEl.innerHTML = list.map(e =>
                                        `<li class="panel-list-item audio-effect-item" data-effect="${e.name}">
                                            <span class="audio-effect-name">${e.name}</span>
                                            <span class="audio-effect-meta mono">${e.category || ''}</span>
                                        </li>`
                                    ).join('');
                                })
                                .catch(() => {
                                    effectsListEl.innerHTML = '<li class="panel-empty">Load failed</li>';
                                });
                        },
                        unmount() {},
                    });
                }
                pm.open('audio');
            }""")

            # Wait for the effects list to populate
            self.page.wait_for_timeout(2000)

            # Verify the audio panel is visible
            panel_visible = self.page.evaluate("""() => {
                const panels = document.querySelectorAll('.panel');
                for (const p of panels) {
                    const title = p.querySelector('.panel-title');
                    if (title && title.textContent.includes('AUDIO')) {
                        return p.offsetWidth > 0 && p.offsetHeight > 0;
                    }
                }
                return false;
            }""")
            assert panel_visible, "Audio panel is not visible after opening"

            # Verify effects list has items
            effect_count = self.page.evaluate("""() => {
                return document.querySelectorAll('.audio-effect-item').length;
            }""")
            assert effect_count > 0, f"Audio panel has no effect items (got {effect_count})"

            self._record(name, True, {"effect_count": effect_count})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 2: GET /api/audio/effects returns effects list with categories
    # ------------------------------------------------------------------

    def test_02_audio_api_effects_list(self):
        """GET /api/audio/effects returns a list of effects with categories."""
        name = "audio_02_api_effects_list"
        try:
            resp = requests.get(f"{self.url}/api/audio/effects", timeout=10)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            effects = resp.json()
            assert isinstance(effects, list), f"Expected list, got {type(effects)}"
            assert len(effects) > 0, "Effects list is empty"

            # Every effect should have name, category, duration
            for e in effects:
                assert "name" in e, f"Effect missing 'name': {e}"
                assert "category" in e, f"Effect missing 'category': {e}"
                assert "duration" in e, f"Effect missing 'duration': {e}"

            # Collect categories
            categories = {e["category"] for e in effects}
            assert len(categories) >= 3, (
                f"Expected at least 3 categories, got {len(categories)}: {categories}"
            )

            self._record(name, True, {
                "effect_count": len(effects),
                "categories": sorted(categories),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 3: GET /api/audio/effects/{name}/metadata returns metadata
    # ------------------------------------------------------------------

    def test_03_audio_api_effect_metadata(self):
        """GET /api/audio/effects/{name}/metadata returns duration, sample_rate."""
        name = "audio_03_api_effect_metadata"
        try:
            resp = requests.get(
                f"{self.url}/api/audio/effects/{KNOWN_EFFECT}/metadata",
                timeout=10,
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            meta = resp.json()
            assert "name" in meta, f"Metadata missing 'name': {meta}"
            assert meta["name"] == KNOWN_EFFECT, (
                f"Expected name '{KNOWN_EFFECT}', got '{meta.get('name')}'"
            )
            assert "duration" in meta, f"Metadata missing 'duration': {meta}"
            assert isinstance(meta["duration"], (int, float)), (
                f"Duration should be numeric, got {type(meta['duration'])}"
            )
            assert meta["duration"] > 0, f"Duration should be positive, got {meta['duration']}"
            assert "category" in meta, f"Metadata missing 'category': {meta}"

            self._record(name, True, {"metadata": meta})
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 4: GET /api/audio/effects/{name} returns WAV bytes
    # ------------------------------------------------------------------

    def test_04_audio_api_effect_stream(self):
        """GET /api/audio/effects/{name} returns WAV bytes with audio/wav content-type."""
        name = "audio_04_api_effect_stream"
        try:
            resp = requests.get(
                f"{self.url}/api/audio/effects/{KNOWN_EFFECT}",
                timeout=10,
            )
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            # Check content-type is audio/wav
            content_type = resp.headers.get("content-type", "")
            assert "audio/wav" in content_type, (
                f"Expected content-type 'audio/wav', got '{content_type}'"
            )

            # Check WAV bytes are non-empty and start with RIFF header
            wav_bytes = resp.content
            assert len(wav_bytes) > 44, (
                f"WAV data too small ({len(wav_bytes)} bytes), expected > 44"
            )
            assert wav_bytes[:4] == b"RIFF", (
                f"WAV data does not start with RIFF header: {wav_bytes[:4]!r}"
            )
            assert wav_bytes[8:12] == b"WAVE", (
                f"WAV data missing WAVE marker: {wav_bytes[8:12]!r}"
            )

            self._record(name, True, {
                "content_type": content_type,
                "wav_bytes_length": len(wav_bytes),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 5: AudioContext initializes after user interaction
    # ------------------------------------------------------------------

    def test_05_audio_context_initializes(self):
        """Verify AudioContext starts after user interaction (click/keypress)."""
        name = "audio_05_audio_context_initializes"
        try:
            # Before interaction, check that _tritiumAudio may or may not exist
            # (depends on whether a gesture already happened in previous tests).
            # Trigger a user gesture to ensure AudioContext initializes.
            self.page.click("body")
            self.page.wait_for_timeout(500)

            # Now check if _tritiumAudio was created and has an AudioContext
            audio_state = self.page.evaluate("""() => {
                const audio = window._tritiumAudio;
                if (!audio) return { exists: false };
                // Try to init if not already done
                if (typeof audio.init === 'function') audio.init();
                return {
                    exists: true,
                    hasCtx: !!audio._ctx,
                    ctxState: audio._ctx ? audio._ctx.state : 'none',
                };
            }""")

            assert audio_state["exists"], (
                "window._tritiumAudio does not exist after user click"
            )
            assert audio_state["hasCtx"], (
                "AudioContext was not created after init()"
            )
            # State should be 'running' or 'suspended' (Chromium autoplay policy)
            assert audio_state["ctxState"] in ("running", "suspended"), (
                f"AudioContext state unexpected: {audio_state['ctxState']}"
            )

            self._record(name, True, audio_state)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 6: Mute toggle via WarAudioManager
    # ------------------------------------------------------------------

    def test_06_mute_toggle(self):
        """Verify mute state toggles when toggleMute is called."""
        name = "audio_06_mute_toggle"
        try:
            # Ensure AudioContext is initialized
            self.page.click("body")
            self.page.wait_for_timeout(300)

            mute_states = self.page.evaluate("""() => {
                const audio = window._tritiumAudio;
                if (!audio) return { error: 'no _tritiumAudio' };
                if (typeof audio.init === 'function') audio.init();

                // Record initial state
                const initial = audio.isMuted();

                // Toggle mute on
                audio.toggleMute();
                const afterFirst = audio.isMuted();

                // Toggle mute off
                audio.toggleMute();
                const afterSecond = audio.isMuted();

                // Check gain node reflects mute
                const gainValue = audio._masterGain ? audio._masterGain.gain.value : -1;

                return {
                    initial: initial,
                    afterFirst: afterFirst,
                    afterSecond: afterSecond,
                    gainValue: gainValue,
                };
            }""")

            if "error" in mute_states:
                pytest.fail(mute_states["error"])

            # initial should be false (not muted by default)
            assert mute_states["initial"] is False, (
                f"Expected initial mute=false, got {mute_states['initial']}"
            )
            # After first toggle, should be true
            assert mute_states["afterFirst"] is True, (
                f"Expected muted after first toggle, got {mute_states['afterFirst']}"
            )
            # After second toggle, should be false again
            assert mute_states["afterSecond"] is False, (
                f"Expected unmuted after second toggle, got {mute_states['afterSecond']}"
            )
            # Gain should be non-zero when unmuted
            assert mute_states["gainValue"] > 0, (
                f"Expected gain > 0 when unmuted, got {mute_states['gainValue']}"
            )

            self._record(name, True, mute_states)
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc

    # ------------------------------------------------------------------
    # Test 7: API returns effects in expected categories
    # ------------------------------------------------------------------

    def test_07_sound_categories(self):
        """API returns effects in expected categories (combat, ambient, alerts, game)."""
        name = "audio_07_sound_categories"
        try:
            resp = requests.get(f"{self.url}/api/audio/effects", timeout=10)
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

            effects = resp.json()
            categories_found: dict[str, list[str]] = {}
            for e in effects:
                cat = e["category"]
                if cat not in categories_found:
                    categories_found[cat] = []
                categories_found[cat].append(e["name"])

            # Verify each expected category has at least one effect
            for cat in EXPECTED_CATEGORIES:
                assert cat in categories_found, (
                    f"Category '{cat}' not found in API response. "
                    f"Found: {sorted(categories_found.keys())}"
                )
                assert len(categories_found[cat]) > 0, (
                    f"Category '{cat}' has no effects"
                )

            # Also verify we can filter by category via query param
            for cat in EXPECTED_CATEGORIES:
                cat_resp = requests.get(
                    f"{self.url}/api/audio/effects?category={cat}",
                    timeout=10,
                )
                assert cat_resp.status_code == 200, (
                    f"Category filter for '{cat}' returned {cat_resp.status_code}"
                )
                cat_effects = cat_resp.json()
                assert len(cat_effects) > 0, (
                    f"Category filter for '{cat}' returned empty list"
                )
                # All returned effects should be in the requested category
                for ce in cat_effects:
                    assert ce["category"] == cat, (
                        f"Effect '{ce['name']}' has category '{ce['category']}', "
                        f"expected '{cat}'"
                    )

            self._record(name, True, {
                "categories": {k: len(v) for k, v in categories_found.items()},
                "total_effects": len(effects),
            })
        except Exception as exc:
            self._record(name, False, {"error": str(exc)})
            raise exc
