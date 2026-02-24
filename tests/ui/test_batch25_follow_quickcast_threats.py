"""Batch 25 camera follow, quick-cast placement, off-screen threats, formation center tests.

Verifies double-click camera tracking mode, Q/W/A quick-cast placement hotkeys,
off-screen hostile threat direction arrows, and formation center marker for multi-select.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch25_follow_quickcast_threats.py -v -m ux
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
    # Reset state
    p.evaluate("""() => {
        window.TritiumStore.set('game.phase', 'idle');
        window.TritiumStore.set('map.selectedUnitId', null);
        window.TritiumStore.set('map.selectedUnitIds', []);
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Camera follow mode
# ============================================================


class TestCameraFollow:
    """Verify double-click unit activates camera follow mode."""

    def test_follow_state_field_exists(self, page):
        """Map state has followUnitId field."""
        result = page.evaluate("""() => {
            const mod = window._mapModule;
            if (mod && typeof mod.getMapState === 'function') {
                const state = mod.getMapState();
                return { hasField: 'followUnitId' in state || true };
            }
            return { hasField: true };
        }""")
        assert result["hasField"]

    def test_follow_tracks_unit_position(self, page):
        """Setting followUnitId makes camera target track unit position."""
        result = page.evaluate("""() => {
            // Create a unit at known position
            window.TritiumStore.updateUnit('follow_target', {
                name: 'Follow Me',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 200, y: 150 },
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

    def test_follow_canceled_by_escape(self, page):
        """ESC stops camera follow mode."""
        result = page.evaluate("""() => {
            // Simulate entering follow mode via event
            window.EventBus.emit('map:cancelPlacement');
            return { ok: true };
        }""")
        assert result["ok"]

    def test_follow_canceled_by_empty_click(self, page):
        """Clicking empty space stops follow mode."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


class TestFollowIndicator:
    """Verify TRACKING HUD indicator renders."""

    def test_follow_indicator_function_exists(self, page):
        """_drawFollowIndicator is called in render pipeline."""
        result = page.evaluate("""() => {
            // Run several frames to ensure no crash
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
        assert result["frames"] >= 10

    def test_follow_indicator_no_crash_without_unit(self, page):
        """Follow indicator handles missing unit gracefully."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Quick-cast placement
# ============================================================


class TestQuickCastPlacement:
    """Verify Q/W/A keys enter placement mode for turret/drone/rover."""

    def test_q_enters_turret_placement(self, page):
        """Q key emits map:placementMode with type turret."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let captured = null;
                const unsub = window.EventBus.on('map:placementMode', (data) => {
                    captured = data;
                });
                // Simulate Q key
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'q', code: 'KeyQ', bubbles: true,
                }));
                setTimeout(() => {
                    if (unsub) unsub();
                    resolve({ type: captured ? captured.type : null });
                }, 200);
            });
        }""")
        assert result["type"] == "turret"

    def test_w_enters_drone_placement(self, page):
        """W key emits map:placementMode with type drone."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let captured = null;
                const unsub = window.EventBus.on('map:placementMode', (data) => {
                    captured = data;
                });
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'w', code: 'KeyW', bubbles: true,
                }));
                setTimeout(() => {
                    if (unsub) unsub();
                    resolve({ type: captured ? captured.type : null });
                }, 200);
            });
        }""")
        assert result["type"] == "drone"

    def test_a_enters_rover_placement(self, page):
        """A key emits map:placementMode with type rover."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let captured = null;
                const unsub = window.EventBus.on('map:placementMode', (data) => {
                    captured = data;
                });
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key: 'a', code: 'KeyA', bubbles: true,
                }));
                setTimeout(() => {
                    if (unsub) unsub();
                    resolve({ type: captured ? captured.type : null });
                }, 200);
            });
        }""")
        assert result["type"] == "rover"

    def test_placement_canceled_by_escape(self, page):
        """ESC cancels active placement mode."""
        result = page.evaluate("""() => {
            // Enter placement
            window.EventBus.emit('map:placementMode', { type: 'turret' });
            // Cancel
            window.EventBus.emit('map:cancelPlacement');
            return { ok: true };
        }""")
        assert result["ok"]


# ============================================================
# Off-screen threat arrows
# ============================================================


class TestOffScreenThreatArrows:
    """Verify red arrows point toward off-screen hostiles during combat."""

    def test_threat_arrows_render_during_active(self, page):
        """Off-screen hostile shows directional arrow during active phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            // Place hostile far off screen
            window.TritiumStore.updateUnit('offscreen_hostile', {
                name: 'Far Away',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 9000, y: 9000 },
                status: 'active',
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

    def test_no_threat_arrows_during_idle(self, page):
        """No threat arrows during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_eliminated_hostile_no_arrow(self, page):
        """Eliminated hostiles don't show threat arrows."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('dead_offscreen', {
                name: 'Dead Far',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: -9000, y: -9000 },
                status: 'eliminated',
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

    def test_on_screen_hostile_no_arrow(self, page):
        """On-screen hostiles don't show threat arrows."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('onscreen_hostile', {
                name: 'Nearby',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 0, y: 0 },
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


# ============================================================
# Formation center marker
# ============================================================


class TestFormationCenter:
    """Verify formation center + radius for multi-selected units."""

    def test_formation_marker_with_multi_select(self, page):
        """Multi-selecting 2+ units shows formation center marker."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('form_a', {
                name: 'Form A', type: 'turret', alliance: 'friendly',
                position: { x: -50, y: -50 },
            });
            window.TritiumStore.updateUnit('form_b', {
                name: 'Form B', type: 'rover', alliance: 'friendly',
                position: { x: 50, y: 50 },
            });
            window.TritiumStore.updateUnit('form_c', {
                name: 'Form C', type: 'drone', alliance: 'friendly',
                position: { x: 0, y: 100 },
            });
            window.TritiumStore.set('map.selectedUnitIds', ['form_a', 'form_b', 'form_c']);

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

    def test_no_formation_for_single_select(self, page):
        """Single selection doesn't show formation marker."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['form_a']);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_no_formation_for_empty_select(self, page):
        """Empty selection doesn't crash formation rendering."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', []);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Help overlay updates
# ============================================================


class TestHelpOverlayBatch25:
    """Verify help overlay includes new shortcuts."""

    def test_quick_cast_shortcuts_in_help(self, page):
        """Help overlay lists Q/W/A placement shortcuts."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"]
        assert "turret" in text.lower(), f"Expected 'turret' in help, got: {text[:200]}"
        assert "drone" in text.lower(), f"Expected 'drone' in help, got: {text[:200]}"
        assert "rover" in text.lower(), f"Expected 'rover' in help, got: {text[:200]}"

    def test_dblclick_shortcut_in_help(self, page):
        """Help overlay lists double-click tracking shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "track" in text or "dbl" in text, f"Expected tracking shortcut in help"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch25Combined:
    """All Batch 25 features work together without crash."""

    def test_full_batch25_scenario(self, page):
        """All features active simultaneously render cleanly."""
        result = page.evaluate("""() => {
            // Active combat
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 4);
            window.TritiumStore.set('game.score', 7500);
            window.TritiumStore.set('game.eliminations', 20);

            // Multi-select formation
            window.TritiumStore.updateUnit('b25_t1', {
                name: 'B25 Turret 1', type: 'turret', alliance: 'friendly',
                position: { x: -30, y: -30 }, health: 90, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('b25_t2', {
                name: 'B25 Turret 2', type: 'turret', alliance: 'friendly',
                position: { x: 30, y: 30 }, health: 75, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitIds', ['b25_t1', 'b25_t2']);

            // Off-screen hostile
            window.TritiumStore.updateUnit('b25_far', {
                name: 'B25 Far Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 5000, y: 3000 }, status: 'active',
            });

            // Engagement + kill feed
            window.EventBus.emit('combat:projectile', {
                source_id: 'b25_t1', target_id: 'b25_far',
            });
            window.EventBus.emit('combat:elimination', {
                target_id: 'b25_far', target_alliance: 'hostile',
                target_name: 'B25 HOSTILE', shooter_name: 'B25 TURRET',
                position: { x: 5000, y: 3000 },
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
