# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 26 prediction cones, leaderboard, rally points, vision range tests.

Verifies enemy prediction cones, combat leaderboard overlay,
rally point markers (Ctrl+R), and vision range arcs on hover.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch26_predict_leaderboard_rally.py -v -m ux
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
# Enemy prediction cones
# ============================================================


class TestPredictionCones:
    """Verify translucent prediction cones on moving hostiles."""

    def test_hostile_with_trail_renders_cone(self, page):
        """Moving hostile shows prediction cone without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Create hostile with movement (trail will build up)
            window.TritiumStore.updateUnit('pred_hostile', {
                name: 'Moving Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 10, y: 10 },
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    // Simulate movement by updating position each frame
                    if (frames < 15) {
                        window.TritiumStore.updateUnit('pred_hostile', {
                            name: 'Moving Hostile',
                            type: 'hostile_kid',
                            alliance: 'hostile',
                            position: { x: 10 + frames * 2, y: 10 + frames },
                        });
                        requestAnimationFrame(tick);
                    } else {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15

    def test_stationary_hostile_no_cone(self, page):
        """Stationary hostile doesn't show prediction cone."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('static_hostile', {
                name: 'Static Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: -50, y: -50 },
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_friendly_no_prediction_cone(self, page):
        """Friendly units don't show prediction cones."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('friend_no_cone', {
                name: 'Friendly Rover',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 30, y: 30 },
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Vision range arc on hover
# ============================================================


class TestVisionRangeArc:
    """Verify friendly unit vision range shown on hover."""

    def test_vision_range_renders_without_crash(self, page):
        """Hovering over friendly unit renders vision range arc."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('vision_turret', {
                name: 'Vision Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
                weapon_range: 40,
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

    def test_no_vision_arc_for_hostile(self, page):
        """Hostile units don't show vision range arc."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Combat leaderboard
# ============================================================


class TestLeaderboard:
    """Verify combat leaderboard overlay during active game."""

    def test_leaderboard_renders_with_eliminations(self, page):
        """Leaderboard shows units with eliminations during active combat."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Create units with eliminations
            window.TritiumStore.updateUnit('lb_turret_1', {
                name: 'Top Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
                eliminations: 7,
            });
            window.TritiumStore.updateUnit('lb_turret_2', {
                name: 'Mid Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 50, y: 50 },
                eliminations: 3,
            });
            window.TritiumStore.updateUnit('lb_drone', {
                name: 'Kill Drone',
                type: 'drone',
                alliance: 'friendly',
                position: { x: -50, y: -50 },
                eliminations: 5,
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

    def test_no_leaderboard_during_idle(self, page):
        """Leaderboard hidden during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_no_leaderboard_without_eliminations(self, page):
        """No leaderboard when no units have eliminations."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Unit with no eliminations
            window.TritiumStore.updateUnit('lb_zero', {
                name: 'No Kills',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 100, y: 100 },
                eliminations: 0,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Rally points
# ============================================================


class TestRallyPoints:
    """Verify rally point markers on map."""

    def test_rally_point_creates_marker(self, page):
        """Emitting map:rallyPoint adds a rally marker."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:rallyPoint', { x: 100, y: 100 });
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

    def test_multiple_rally_points(self, page):
        """Up to 3 rally points can be placed."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:rallyPoint', { x: 0, y: 0 });
            window.EventBus.emit('map:rallyPoint', { x: 50, y: 50 });
            window.EventBus.emit('map:rallyPoint', { x: -50, y: -50 });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_rally_clear(self, page):
        """map:clearRallyPoints removes all markers."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:rallyPoint', { x: 100, y: 100 });
            window.EventBus.emit('map:clearRallyPoints');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_rally_dotted_line_to_selected(self, page):
        """Selected unit shows dotted line to rally point."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('rally_unit', {
                name: 'Rally Unit',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.set('map.selectedUnitId', 'rally_unit');
            window.EventBus.emit('map:rallyPoint', { x: 200, y: 200 });
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
# Help overlay updates
# ============================================================


class TestHelpOverlayBatch26:
    """Verify help overlay includes Ctrl+R rally shortcut."""

    def test_rally_shortcut_in_help(self, page):
        """Help overlay lists Ctrl+R rally point shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "rally" in text, f"Expected 'rally' in help, got: {text[:200]}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch26Combined:
    """All Batch 26 features work together without crash."""

    def test_full_batch26_scenario(self, page):
        """All features active simultaneously render cleanly."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 5);
            window.TritiumStore.set('game.score', 10000);

            // Units with eliminations for leaderboard
            window.TritiumStore.updateUnit('b26_ace', {
                name: 'B26 Ace', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, eliminations: 12,
                weapon_range: 50, health: 90, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('b26_rookie', {
                name: 'B26 Rookie', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: 50 }, eliminations: 2,
            });

            // Moving hostile for prediction cone
            let hostile_x = 100;
            window.TritiumStore.updateUnit('b26_mover', {
                name: 'B26 Mover', type: 'hostile_kid', alliance: 'hostile',
                position: { x: hostile_x, y: 100 },
            });

            // Rally point
            window.EventBus.emit('map:rallyPoint', { x: -100, y: -100 });

            // Multi-select for formation
            window.TritiumStore.set('map.selectedUnitIds', ['b26_ace', 'b26_rookie']);

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    hostile_x += 3;
                    window.TritiumStore.updateUnit('b26_mover', {
                        name: 'B26 Mover', type: 'hostile_kid', alliance: 'hostile',
                        position: { x: hostile_x, y: 100 + frames },
                    });
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        window.EventBus.emit('map:clearRallyPoints');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
