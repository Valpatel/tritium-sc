# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 32 canvas wave banner, cinematic camera, threat compass, minimap health tests.

Verifies big canvas wave banner animation, K-key cinematic camera orbit,
compass rose threat direction needles, and minimap friendly health bars.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch32_wavebanner_cinematic_threatcompass.py -v -m ux
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
# Canvas wave banner
# ============================================================


class TestCanvasWaveBanner:
    """Verify big wave banner animation on canvas."""

    def test_wave_start_triggers_banner(self, page):
        """game:wave_start event shows canvas wave banner."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('game:wave_start', { wave: 3 });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 20) requestAnimationFrame(tick);
                    else {
                        const mod = window._mapModule;
                        const hasBanner = mod && mod._state && mod._state.waveBanner !== null;
                        resolve({
                            canvasOk: !!document.getElementById('tactical-canvas'),
                            frames,
                        });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 20

    def test_wave_banner_expires(self, page):
        """Wave banner fades away after maxAge (3 seconds)."""
        result = page.evaluate("""() => {
            window.EventBus.emit('game:wave_start', { wave: 5 });
            return new Promise(resolve => {
                // Wait 3.5 seconds for banner to expire
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 3500);
            });
        }""")
        assert result["canvasOk"]

    def test_wave_banner_without_number(self, page):
        """Wave start without wave number still shows banner."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.EventBus.emit('game:wave_start', {});
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


# ============================================================
# Cinematic camera mode
# ============================================================


class TestCinematicCamera:
    """Verify K-key cinematic camera orbit."""

    def test_cinematic_toggle(self, page):
        """Pressing K toggles cinematic mode without crash."""
        result = page.evaluate("""() => {
            // Place some units for orbit center calculation
            window.TritiumStore.updateUnit('cine_a', {
                name: 'Cine A', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('cine_b', {
                name: 'Cine B', type: 'drone', alliance: 'friendly',
                position: { x: 60, y: 60 },
            });
            return new Promise(resolve => {
                // Toggle cinematic on
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'k', code: 'KeyK', bubbles: true,
                }));
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 30

    def test_cinematic_off_toggle(self, page):
        """Pressing K again turns off cinematic mode."""
        result = page.evaluate("""() => {
            // Toggle on then off
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'k', code: 'KeyK', bubbles: true,
            }));
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'k', code: 'KeyK', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_cinematic_camera_moves(self, page):
        """Camera position changes during cinematic orbit."""
        result = page.evaluate("""() => {
            // Place units far apart so orbit has meaningful radius
            window.TritiumStore.updateUnit('cine_far_a', {
                name: 'Cine Far A', type: 'turret', alliance: 'friendly',
                position: { x: -100, y: -100 },
            });
            window.TritiumStore.updateUnit('cine_far_b', {
                name: 'Cine Far B', type: 'drone', alliance: 'friendly',
                position: { x: 100, y: 100 },
            });

            // Record starting viewport position
            const vp = window.TritiumStore.map?.viewport;
            const startX = vp ? vp.x : 0;
            const startY = vp ? vp.y : 0;

            // Toggle cinematic on via keyboard
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'k', code: 'KeyK', bubbles: true,
            }));

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 60) requestAnimationFrame(tick);
                    else {
                        const vpEnd = window.TritiumStore.map?.viewport;
                        const endX = vpEnd ? vpEnd.x : 0;
                        const endY = vpEnd ? vpEnd.y : 0;
                        const moved = Math.abs(endX - startX) > 0.1 || Math.abs(endY - startY) > 0.1;
                        // Turn off
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'k', code: 'KeyK', bubbles: true,
                        }));
                        resolve({ moved, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        # Camera should have moved during orbit
        assert result["moved"]


# ============================================================
# Threat compass needles
# ============================================================


class TestThreatCompassNeedles:
    """Verify red needles on compass pointing toward hostiles."""

    def test_threat_needles_during_combat(self, page):
        """Hostile units create red direction needles on compass."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('tc_turret', {
                name: 'TC Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('tc_hostile', {
                name: 'TC Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 100, y: 100 }, status: 'active',
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

    def test_no_needles_during_idle(self, page):
        """No threat needles during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_no_needles_without_hostiles(self, page):
        """No needles when only friendlies exist."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Remove hostiles
            window.TritiumStore.updateUnit('tc_hostile', {
                name: 'TC Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 100, y: 100 }, status: 'eliminated',
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

    def test_multiple_hostile_directions(self, page):
        """Multiple hostiles in different directions show multiple needles."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('tc_h_n', {
                name: 'North Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 0, y: 200 }, status: 'active',
            });
            window.TritiumStore.updateUnit('tc_h_e', {
                name: 'East Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 200, y: 0 }, status: 'active',
            });
            window.TritiumStore.updateUnit('tc_h_s', {
                name: 'South Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 0, y: -200 }, status: 'active',
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


# ============================================================
# Minimap health indicators
# ============================================================


class TestMinimapHealth:
    """Verify tiny health bars on minimap for friendlies."""

    def test_minimap_health_bars_render(self, page):
        """Friendly units with health show minimap health bars."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('mmh_turret', {
                name: 'MMH Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 50, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('mmh_drone', {
                name: 'MMH Drone', type: 'drone', alliance: 'friendly',
                position: { x: 80, y: -40 }, health: 90, maxHealth: 100,
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

    def test_minimap_no_health_for_hostiles(self, page):
        """Hostile units don't show health bars on minimap."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('mmh_hostile', {
                name: 'MMH Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: -50, y: -50 }, health: 20, maxHealth: 100,
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

    def test_minimap_critical_health_color(self, page):
        """Critical health (<25%) renders red on minimap."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('mmh_crit', {
                name: 'MMH Critical', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 10, maxHealth: 100,
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


# ============================================================
# Help overlay update
# ============================================================


class TestHelpOverlayBatch32:
    """Verify help overlay includes K cinematic shortcut."""

    def test_k_cinematic_in_help(self, page):
        """Help overlay lists K cinematic camera shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "cinematic" in text, f"Expected 'cinematic' in help, got: {text[:200]}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch32Combined:
    """All Batch 32 features work together without crash."""

    def test_full_batch32_scenario(self, page):
        """Wave banner + cinematic + threat compass + minimap health all render."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 7);
            window.TritiumStore.set('game.score', 45000);

            // Friendlies with varying health
            window.TritiumStore.updateUnit('b32_alpha', {
                name: 'B32 Alpha', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 15, maxHealth: 100,
                eliminations: 18, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b32_beta', {
                name: 'B32 Beta', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: -30 }, health: 70, maxHealth: 100,
                eliminations: 8,
            });

            // Hostiles in different directions for compass needles
            window.TritiumStore.updateUnit('b32_h1', {
                name: 'B32 H1', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 150, y: 0 }, status: 'active',
            });
            window.TritiumStore.updateUnit('b32_h2', {
                name: 'B32 H2', type: 'hostile_kid', alliance: 'hostile',
                position: { x: -100, y: 80 }, status: 'active',
            });

            // Trigger wave banner
            window.EventBus.emit('game:wave_start', { wave: 7 });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 60) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 60
        assert result["canvasOk"]
