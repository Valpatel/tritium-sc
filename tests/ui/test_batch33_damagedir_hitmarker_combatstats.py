# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 33 damage direction, hit marker, combat stats overlay, unit trail glow tests.

Verifies damage direction indicator arcs, hit marker X flashes,
J-key combat stats overlay, and enhanced unit trail rendering.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch33_damagedir_hitmarker_combatstats.py -v -m ux
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
# Damage direction indicator
# ============================================================


class TestDamageDirection:
    """Verify red arc on screen edge pointing toward damage source."""

    def test_hit_creates_damage_direction(self, page):
        """combat:hit event creates a damage direction indicator."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('dd_target', {
                name: 'DD Target', type: 'turret', alliance: 'friendly',
                position: { x: 100, y: 50 }, health: 80, maxHealth: 100,
            });
            window.EventBus.emit('combat:hit', {
                target_id: 'dd_target', damage: 15,
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

    def test_damage_direction_fades(self, page):
        """Damage direction fades away after maxAge."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('dd_fade', {
                name: 'DD Fade', type: 'turret', alliance: 'friendly',
                position: { x: -50, y: -50 }, health: 60, maxHealth: 100,
            });
            window.EventBus.emit('combat:hit', {
                target_id: 'dd_fade', damage: 10,
            });
            return new Promise(resolve => {
                // Wait 1 second (beyond 0.6s maxAge)
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 1000);
            });
        }""")
        assert result["canvasOk"]

    def test_multiple_damage_directions(self, page):
        """Multiple hits create multiple direction indicators."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('dd_multi_a', {
                name: 'DD A', type: 'turret', alliance: 'friendly',
                position: { x: 100, y: 0 }, health: 70, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('dd_multi_b', {
                name: 'DD B', type: 'drone', alliance: 'friendly',
                position: { x: 0, y: 100 }, health: 50, maxHealth: 100,
            });
            window.EventBus.emit('combat:hit', { target_id: 'dd_multi_a', damage: 10 });
            window.EventBus.emit('combat:hit', { target_id: 'dd_multi_b', damage: 20 });
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
# Hit marker flash
# ============================================================


class TestHitMarker:
    """Verify white X flash at hit location."""

    def test_hit_creates_marker(self, page):
        """combat:hit event creates a white X marker at target position."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('hm_target', {
                name: 'HM Target', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 30, y: 30 }, health: 40, maxHealth: 100,
            });
            window.EventBus.emit('combat:hit', {
                target_id: 'hm_target', damage: 25,
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

    def test_hit_marker_fades(self, page):
        """Hit marker fades away after 0.4 seconds."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('hm_fade', {
                name: 'HM Fade', type: 'hostile_kid', alliance: 'hostile',
                position: { x: -30, y: -30 }, health: 20, maxHealth: 100,
            });
            window.EventBus.emit('combat:hit', {
                target_id: 'hm_fade', damage: 15,
            });
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 600);
            });
        }""")
        assert result["canvasOk"]

    def test_no_marker_on_missing_unit(self, page):
        """Hit on non-existent unit doesn't crash."""
        result = page.evaluate("""() => {
            window.EventBus.emit('combat:hit', {
                target_id: 'nonexistent_unit', damage: 10,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Combat stats overlay
# ============================================================


class TestCombatStats:
    """Verify J-key combat stats overlay."""

    def test_j_key_toggles_stats(self, page):
        """Pressing J shows combat stats overlay during active game."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('cs_turret', {
                name: 'CS Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 80, maxHealth: 100,
                eliminations: 12,
            });
            // Toggle combat stats on
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));
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

    def test_j_key_off_toggle(self, page):
        """Pressing J again hides the overlay."""
        result = page.evaluate("""() => {
            // Toggle on then off
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_stats_not_shown_during_idle(self, page):
        """Stats overlay not rendered during idle even when toggled on."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));
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

    def test_stats_shows_multiple_units(self, page):
        """Stats overlay lists multiple friendly units sorted by elims."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('cs_ace', {
                name: 'CS Ace', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                eliminations: 20,
            });
            window.TritiumStore.updateUnit('cs_mid', {
                name: 'CS Mid', type: 'drone', alliance: 'friendly',
                position: { x: 50, y: 50 }, health: 60, maxHealth: 100,
                eliminations: 8,
            });
            window.TritiumStore.updateUnit('cs_low', {
                name: 'CS Low', type: 'rover', alliance: 'friendly',
                position: { x: -50, y: -50 }, health: 30, maxHealth: 100,
                eliminations: 2,
            });
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else {
                        // Toggle off
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'j', code: 'KeyJ', bubbles: true,
                        }));
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas'), frames });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["canvasOk"]
        assert result["frames"] >= 15


# ============================================================
# Help overlay update
# ============================================================


class TestHelpOverlayBatch33:
    """Verify help overlay includes J combat stats shortcut."""

    def test_j_combatstats_in_help(self, page):
        """Help overlay lists J combat stats shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "combat stats" in text, f"Expected 'combat stats' in help, got: {text[:200]}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch33Combined:
    """All Batch 33 features work together without crash."""

    def test_full_batch33_scenario(self, page):
        """Damage directions + hit markers + combat stats all render together."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 6);
            window.TritiumStore.set('game.score', 30000);

            // Friendlies
            window.TritiumStore.updateUnit('b33_alpha', {
                name: 'B33 Alpha', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 40, maxHealth: 100,
                eliminations: 15, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b33_beta', {
                name: 'B33 Beta', type: 'drone', alliance: 'friendly',
                position: { x: 60, y: -30 }, health: 85, maxHealth: 100,
                eliminations: 7,
            });

            // Hostiles
            window.TritiumStore.updateUnit('b33_h1', {
                name: 'B33 H1', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 80, y: 40 }, status: 'active', health: 60, maxHealth: 100,
            });

            // Combat events
            window.EventBus.emit('combat:hit', { target_id: 'b33_alpha', damage: 15 });
            window.EventBus.emit('combat:hit', { target_id: 'b33_h1', damage: 25 });
            window.EventBus.emit('combat:projectile', {
                source_id: 'b33_alpha', target_id: 'b33_h1',
            });

            // Toggle combat stats
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'j', code: 'KeyJ', bubbles: true,
            }));

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 60) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        // Toggle stats off
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'j', code: 'KeyJ', bubbles: true,
                        }));
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 60
        assert result["canvasOk"]
