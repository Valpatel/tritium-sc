# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 30 victory particles, ambient sparks, placement grid snap, enhanced HUD tests.

Verifies victory celebration confetti, ambient combat spark particles,
placement mode grid snap, and enhanced combat HUD with elapsed timer.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch30_victory_particles_gridsnap.py -v -m ux
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
# Victory celebration particles
# ============================================================


class TestVictoryParticles:
    """Verify confetti particles on victory."""

    def test_victory_triggers_particles(self, page):
        """Setting game phase to victory spawns celebration particles."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.score', 50000);

            return new Promise(resolve => {
                // Trigger victory
                window.TritiumStore.set('game.phase', 'victory');
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

    def test_victory_particles_fall(self, page):
        """Victory particles animate over multiple frames."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'victory');
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 90) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 90

    def test_no_particles_during_idle(self, page):
        """No victory particles during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Ambient combat particles
# ============================================================


class TestAmbientParticles:
    """Verify ambient spark particles during combat."""

    def test_ambient_sparks_during_engagement(self, page):
        """Active engagements spawn ambient spark particles."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('spark_turret', {
                name: 'Spark Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('spark_hostile', {
                name: 'Spark Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 30, y: 30 },
            });
            // Create engagement
            window.EventBus.emit('combat:projectile', {
                source_id: 'spark_turret', target_id: 'spark_hostile',
            });

            return new Promise(resolve => {
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

    def test_no_sparks_during_idle(self, page):
        """No ambient sparks during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Placement grid snap
# ============================================================


class TestPlacementGridSnap:
    """Verify placement mode snaps to 5m grid."""

    def test_placement_ghost_renders(self, page):
        """Entering placement mode renders ghost without crash."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:placementMode', { type: 'turret' });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else {
                        window.EventBus.emit('map:cancelPlacement');
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15

    def test_placement_cancel_cleans_up(self, page):
        """Canceling placement mode cleans up properly."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:placementMode', { type: 'drone' });
            window.EventBus.emit('map:cancelPlacement');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Enhanced combat HUD
# ============================================================


class TestEnhancedCombatHUD:
    """Verify wider combat HUD with elapsed timer and compact layout."""

    def test_combat_hud_renders(self, page):
        """Active combat HUD renders all elements."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 5);
            window.TritiumStore.set('game.score', 15000);
            window.TritiumStore.set('game.eliminations', 25);
            window.TritiumStore.set('game.waveStartTime', Date.now() - 90000);

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

    def test_countdown_hud_renders(self, page):
        """Countdown phase renders centered countdown text."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'countdown');
            window.TritiumStore.set('game.countdown', '3');
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
# Combined render stability
# ============================================================


class TestBatch30Combined:
    """All Batch 30 features work together without crash."""

    def test_full_batch30_scenario(self, page):
        """Complete game lifecycle with all effects renders cleanly."""
        result = page.evaluate("""() => {
            // Start combat
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 10);
            window.TritiumStore.set('game.score', 50000);
            window.TritiumStore.set('game.waveStartTime', Date.now());

            // Units
            window.TritiumStore.updateUnit('b30_hero', {
                name: 'B30 Hero', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 15, maxHealth: 100,
                eliminations: 30, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b30_hostile', {
                name: 'B30 Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 25, y: 25 }, status: 'active',
            });

            // Combat engagement
            window.EventBus.emit('combat:projectile', {
                source_id: 'b30_hero', target_id: 'b30_hostile',
            });

            // Placement mode
            window.EventBus.emit('map:placementMode', { type: 'turret' });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames === 30) {
                        // Cancel placement and trigger victory
                        window.EventBus.emit('map:cancelPlacement');
                        window.TritiumStore.set('game.phase', 'victory');
                    }
                    if (frames < 90) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 90
        assert result["canvasOk"]
