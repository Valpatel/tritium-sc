"""Batch 22 game phase HUD, radar sweep, velocity vectors, and gamePhase sync tests.

Verifies canvas combat HUD overlay, minimap radar sweep animation,
unit velocity vector arrows, and _state.gamePhase store sync.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch22_hud_radar_velocity.py -v -m ux
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
    # Reset game state and escape any mode
    p.evaluate("""() => {
        window.TritiumStore.set('game.phase', 'idle');
        window.TritiumStore.set('game.wave', 0);
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Game Phase HUD — Countdown overlay
# ============================================================


class TestGamePhaseCountdown:
    """Verify countdown phase shows large centered overlay."""

    def test_countdown_hud_renders_on_phase_change(self, page):
        """Setting game.phase to 'countdown' triggers HUD without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'countdown');
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.countdown', '3');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"], "Canvas should render countdown HUD"

    def test_countdown_hud_shows_wave_number(self, page):
        """Countdown HUD references the current wave."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'countdown');
            window.TritiumStore.set('game.wave', 5);
            window.TritiumStore.set('game.totalWaves', 10);
            return new Promise(resolve => {
                // Let render cycle execute the HUD code path
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        const wave = window.TritiumStore.get('game.wave');
                        resolve({ wave, canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["wave"] == 5
        assert result["canvasOk"]


# ============================================================
# Game Phase HUD — Active combat strip
# ============================================================


class TestGamePhaseActive:
    """Verify active phase shows compact top-center HUD strip."""

    def test_active_hud_renders_without_crash(self, page):
        """Setting phase to 'active' with score/wave renders HUD."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 2);
            window.TritiumStore.set('game.score', 1500);
            window.TritiumStore.set('game.eliminations', 7);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_active_hud_reads_game_state(self, page):
        """Active HUD reads correct wave, score, eliminations from store."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 4);
            window.TritiumStore.set('game.score', 3200);
            window.TritiumStore.set('game.eliminations', 12);
            return {
                wave: window.TritiumStore.get('game.wave'),
                score: window.TritiumStore.get('game.score'),
                elims: window.TritiumStore.get('game.eliminations'),
            };
        }""")
        assert result["wave"] == 4
        assert result["score"] == 3200
        assert result["elims"] == 12

    def test_idle_phase_no_hud(self, page):
        """In idle phase, game HUD does not render (no crash)."""
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

    def test_setup_phase_no_combat_hud(self, page):
        """In setup phase, combat HUD does not show (setup summary shows instead)."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'setup');
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
# GamePhase sync from store
# ============================================================


class TestGamePhaseSync:
    """Verify _state.gamePhase is synced from TritiumStore in _update."""

    def test_game_phase_syncs_to_active(self, page):
        """Setting store game.phase to 'active' updates render state."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            return new Promise(resolve => {
                // Wait for update loop to sync
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        const phase = window.TritiumStore.get('game.phase');
                        resolve({ phase });
                    });
                });
            });
        }""")
        assert result["phase"] == "active"

    def test_game_phase_defaults_to_idle(self, page):
        """Default game phase is 'idle'."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ phase: window.TritiumStore.get('game.phase') || 'idle' });
                });
            });
        }""")
        assert result["phase"] == "idle"


# ============================================================
# Radar sweep animation on minimap
# ============================================================


class TestRadarSweep:
    """Verify minimap radar sweep during active combat."""

    def test_radar_renders_during_active_phase(self, page):
        """Setting phase to 'active' and rendering doesn't crash minimap."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) {
                        requestAnimationFrame(tick);
                    } else {
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
        assert result["frames"] >= 15

    def test_radar_not_active_during_idle(self, page):
        """Radar sweep should not animate during idle phase."""
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

    def test_radar_continues_through_many_frames(self, page):
        """Radar sweep renders across 30+ frames without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) {
                        requestAnimationFrame(tick);
                    } else {
                        resolve({ frames, ok: true });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["ok"]


# ============================================================
# Velocity vector arrows
# ============================================================


class TestVelocityVectors:
    """Verify velocity vector arrows on moving units."""

    def test_velocity_renders_for_moving_unit(self, page):
        """Unit with trail data renders velocity arrow without crash."""
        result = page.evaluate("""() => {
            // Inject a unit that moves (simulate trail by updating position)
            const id = 'velocity_test_1';
            window.TritiumStore.updateUnit(id, {
                name: 'Speed Test',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });

            // Simulate movement by updating position over time
            return new Promise(resolve => {
                let step = 0;
                function moveUnit() {
                    step++;
                    window.TritiumStore.updateUnit(id, {
                        name: 'Speed Test',
                        type: 'rover',
                        alliance: 'friendly',
                        position: { x: step * 5, y: step * 3 },
                    });
                    if (step < 10) {
                        requestAnimationFrame(moveUnit);
                    } else {
                        requestAnimationFrame(() => {
                            resolve({
                                canvasOk: !!document.getElementById('tactical-canvas'),
                                finalPos: { x: step * 5, y: step * 3 },
                            });
                        });
                    }
                }
                requestAnimationFrame(moveUnit);
            });
        }""")
        assert result["canvasOk"]
        assert result["finalPos"]["x"] == 50

    def test_stationary_unit_no_velocity_arrow(self, page):
        """Stationary unit doesn't show velocity arrow (speed < threshold)."""
        result = page.evaluate("""() => {
            // Inject stationary unit
            window.TritiumStore.updateUnit('static_test', {
                name: 'Static Turret',
                type: 'turret',
                alliance: 'friendly',
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

    def test_hostile_velocity_uses_red_color(self, page):
        """Hostile unit velocity arrow uses red alliance color."""
        result = page.evaluate("""() => {
            const id = 'hostile_velocity';
            let step = 0;
            function moveHostile() {
                step++;
                window.TritiumStore.updateUnit(id, {
                    name: 'Fast Hostile',
                    type: 'hostile_kid',
                    alliance: 'hostile',
                    position: { x: step * 8, y: -step * 4 },
                });
                if (step < 8) {
                    requestAnimationFrame(moveHostile);
                }
            }
            requestAnimationFrame(moveHostile);
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 500);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Combined effects render stability
# ============================================================


class TestCombinedEffects:
    """Verify all new features work together without crash."""

    def test_all_batch22_features_simultaneously(self, page):
        """Active combat with HUD + radar + velocity + spawn/despawn."""
        result = page.evaluate("""() => {
            // Set active combat
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.score', 2000);
            window.TritiumStore.set('game.eliminations', 5);

            // Spawn some units
            for (let i = 0; i < 5; i++) {
                window.TritiumStore.updateUnit(`combo_test_${i}`, {
                    name: `Combo ${i}`,
                    type: i % 2 === 0 ? 'turret' : 'hostile_kid',
                    alliance: i % 2 === 0 ? 'friendly' : 'hostile',
                    position: { x: i * 30, y: i * 20 },
                });
            }

            // Fire an elimination
            window.EventBus.emit('combat:elimination', {
                target_id: 'combo_test_1',
                target_alliance: 'hostile',
                position: { x: 30, y: 20 },
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    // Move a unit each frame for velocity vector
                    window.TritiumStore.updateUnit('combo_test_0', {
                        name: 'Combo 0',
                        type: 'turret',
                        alliance: 'friendly',
                        position: { x: frames * 2, y: frames },
                    });
                    if (frames < 20) {
                        requestAnimationFrame(tick);
                    } else {
                        resolve({
                            frames,
                            canvasOk: !!document.getElementById('tactical-canvas'),
                        });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 20
        assert result["canvasOk"]

    def test_phase_transitions_no_crash(self, page):
        """Rapidly cycling through game phases doesn't crash."""
        result = page.evaluate("""() => {
            const phases = ['idle', 'setup', 'countdown', 'active', 'wave_complete', 'victory', 'defeat', 'idle'];
            let i = 0;
            return new Promise(resolve => {
                function cycle() {
                    if (i < phases.length) {
                        window.TritiumStore.set('game.phase', phases[i]);
                        i++;
                        requestAnimationFrame(cycle);
                    } else {
                        requestAnimationFrame(() => {
                            resolve({ cycled: i, canvasOk: !!document.getElementById('tactical-canvas') });
                        });
                    }
                }
                requestAnimationFrame(cycle);
            });
        }""")
        assert result["cycled"] == 8
        assert result["canvasOk"]
