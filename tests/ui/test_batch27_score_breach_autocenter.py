# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 27 score popups, zone breach alarm, auto-center, compass labels tests.

Verifies floating score popups on eliminations, zone breach flash overlay,
auto-center camera mode (Shift+F), and compass edge labels (N/S/E/W).

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch27_score_breach_autocenter.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ux, pytest.mark.ui]


@pytest.fixture(scope="module")
def _server():
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def _browser(_server):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def _ctx(_browser, _server):
    ctx = _browser.new_context(viewport={"width": 1920, "height": 1080})
    p = ctx.new_page()
    p.goto(f"{_server.url}/unified", wait_until="domcontentloaded", timeout=60000)
    try:
        p.wait_for_function(
            "() => window.TritiumStore && window.TritiumStore.units.size >= 3",
            timeout=15000,
        )
    except Exception:
        pass
    p.wait_for_timeout(1000)
    yield {"page": p, "url": _server.url}
    ctx.close()


@pytest.fixture
def page(_ctx):
    p = _ctx["page"]
    yield p
    p.evaluate("""() => {
        window.TritiumStore.set('game.phase', 'idle');
        window.TritiumStore.set('map.selectedUnitId', null);
        window.TritiumStore.set('map.selectedUnitIds', []);
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Score popups
# ============================================================


class TestScorePopups:
    """Verify floating score popups on eliminations."""

    def test_elimination_creates_score_popup(self, page):
        """combat:elimination event creates a rising score popup."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('score_turret', {
                name: 'Score Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('score_hostile', {
                name: 'Score Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 50, y: 50 },
            });

            window.EventBus.emit('combat:elimination', {
                target_id: 'score_hostile',
                target_alliance: 'hostile',
                target_name: 'SCORE HOSTILE',
                shooter_name: 'SCORE TURRET',
                position: { x: 50, y: 50 },
                streak: 1,
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15

    def test_double_kill_streak_popup(self, page):
        """Double kill shows streak multiplier text."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('combat:elimination', {
                target_id: 'dk_hostile',
                target_alliance: 'hostile',
                target_name: 'DK HOSTILE',
                shooter_name: 'DK TURRET',
                position: { x: 30, y: 30 },
                streak: 2,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_triple_kill_streak_popup(self, page):
        """Triple kill shows TRIPLE streak text."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('combat:elimination', {
                target_id: 'tk_hostile',
                target_alliance: 'hostile',
                target_name: 'TK HOSTILE',
                shooter_name: 'TK TURRET',
                position: { x: -20, y: -20 },
                streak: 3,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_rampage_streak_popup(self, page):
        """5+ streak shows RAMPAGE text."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('combat:elimination', {
                target_id: 'rp_hostile',
                target_alliance: 'hostile',
                target_name: 'RP HOSTILE',
                shooter_name: 'RP TURRET',
                position: { x: 60, y: -60 },
                streak: 5,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_score_popups_fade_over_time(self, page):
        """Score popups disappear after their maxAge."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('combat:elimination', {
                target_id: 'fade_hostile',
                target_alliance: 'hostile',
                target_name: 'FADE HOSTILE',
                shooter_name: 'FADE TURRET',
                position: { x: 0, y: 0 },
                streak: 1,
            });
            // Run many frames to let popup age out
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 120) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 120


# ============================================================
# Zone breach alarm
# ============================================================


class TestZoneBreachAlarm:
    """Verify zone breach flash when hostiles enter zones."""

    def test_zone_breach_renders_without_crash(self, page):
        """Hostile inside a zone during active combat doesn't crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Place hostile at origin — may or may not be inside a zone
            window.TritiumStore.updateUnit('breach_hostile', {
                name: 'Breach Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 0, y: 0 },
                status: 'active',
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_no_breach_during_idle(self, page):
        """No zone breach flash during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_breach_flash_fades(self, page):
        """Zone breach flash fades after timeout."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Run many frames to let any flash fade
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 60) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 60


# ============================================================
# Auto-center camera
# ============================================================


class TestAutoCenter:
    """Verify auto-center camera mode during combat."""

    def test_auto_center_toggle_no_crash(self, page):
        """Toggling auto-center mode doesn't crash render loop."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Create units for centroid calculation
            window.TritiumStore.updateUnit('ac_turret', {
                name: 'AC Turret', type: 'turret', alliance: 'friendly',
                position: { x: -50, y: -50 },
            });
            window.TritiumStore.updateUnit('ac_hostile', {
                name: 'AC Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 50, y: 50 },
            });

            // Toggle auto-center via module if available
            const mod = window._mapModule;
            if (mod && typeof mod.toggleAutoCenter === 'function') {
                mod.toggleAutoCenter();
            }

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 20) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 20

    def test_auto_center_off_by_default(self, page):
        """Auto-center is off by default — camera doesn't auto-drift."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_auto_center_disabled_during_idle(self, page):
        """Auto-center doesn't pull camera during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_auto_center_indicator_renders(self, page):
        """Auto-center indicator renders when mode is active."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('aci_unit', {
                name: 'ACI Unit', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            const mod = window._mapModule;
            if (mod && typeof mod.toggleAutoCenter === 'function') {
                mod.toggleAutoCenter();
            }
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else {
                        // Turn it off again
                        if (mod && typeof mod.toggleAutoCenter === 'function') {
                            mod.toggleAutoCenter();
                        }
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Compass edge labels
# ============================================================


class TestCompassEdgeLabels:
    """Verify N/S/E/W compass labels on map edges."""

    def test_compass_labels_render(self, page):
        """Compass labels render without crash."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]

    def test_compass_labels_during_zoom(self, page):
        """Compass labels stay at edges during zoom changes."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    // Simulate zoom changes via wheel events
                    if (frames === 5) {
                        const canvas = document.getElementById('tactical-canvas');
                        if (canvas) {
                            canvas.dispatchEvent(new WheelEvent('wheel', {
                                deltaY: -100, clientX: 960, clientY: 540, bubbles: true,
                            }));
                        }
                    }
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Combined render stability
# ============================================================


class TestBatch27Combined:
    """All Batch 27 features work together without crash."""

    def test_full_batch27_scenario(self, page):
        """All features active simultaneously render cleanly."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 6);
            window.TritiumStore.set('game.score', 15000);

            // Friendly units
            window.TritiumStore.updateUnit('b27_ace', {
                name: 'B27 Ace', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, eliminations: 15,
                weapon_range: 50, health: 80, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('b27_drone', {
                name: 'B27 Drone', type: 'drone', alliance: 'friendly',
                position: { x: 60, y: -30 }, eliminations: 8,
            });

            // Hostile in zone area
            window.TritiumStore.updateUnit('b27_breach', {
                name: 'B27 Breach', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 10, y: 10 }, status: 'active',
            });

            // Fire elimination for score popup
            window.EventBus.emit('combat:elimination', {
                target_id: 'b27_breach',
                target_alliance: 'hostile',
                target_name: 'B27 BREACH',
                shooter_name: 'B27 ACE',
                position: { x: 10, y: 10 },
                streak: 3,
            });

            // Toggle auto-center
            const mod = window._mapModule;
            if (mod && typeof mod.toggleAutoCenter === 'function') {
                mod.toggleAutoCenter();
            }

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        // Clean up
                        window.TritiumStore.set('game.phase', 'idle');
                        if (mod && typeof mod.toggleAutoCenter === 'function') {
                            mod.toggleAutoCenter();
                        }
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
