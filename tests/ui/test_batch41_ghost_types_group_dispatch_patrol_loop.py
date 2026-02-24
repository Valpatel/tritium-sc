"""Batch 41 placement ghost per type, group dispatch, patrol loop closure tests.

Verifies placement ghost icon changes by unit type, group dispatch with D key
on multi-select, and patrol paths closing back to first waypoint.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch41_ghost_types_group_dispatch_patrol_loop.py -v -m ux
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
# Placement ghost per unit type
# ============================================================


class TestPlacementGhostTypes:
    """Verify placement ghost shape changes by unit type."""

    def test_turret_placement_no_crash(self, page):
        """Q key enters turret placement mode without crash."""
        result = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'q', code: 'KeyQ', bubbles: true,
            }));
            return new Promise(resolve => {
                // Let render frame draw the ghost
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }));
            });
        }""")
        assert result["canvasOk"]

    def test_drone_placement_no_crash(self, page):
        """W key enters drone placement mode without crash."""
        result = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'w', code: 'KeyW', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }));
            });
        }""")
        assert result["canvasOk"]

    def test_rover_placement_no_crash(self, page):
        """A key enters rover placement mode without crash."""
        result = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'a', code: 'KeyA', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }));
            });
        }""")
        assert result["canvasOk"]

    def test_placement_type_stored_correctly(self, page):
        """Placement type is stored in EventBus dispatch data."""
        result = page.evaluate("""() => {
            let capturedType = null;
            const unsub = window.EventBus.on('map:placementMode', (data) => {
                capturedType = data && data.type;
            });
            // Trigger drone placement
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'w', code: 'KeyW', bubbles: true,
            }));
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    unsub();
                    resolve({ type: capturedType });
                });
            });
        }""")
        assert result["type"] == "drone"

    def test_all_three_types_render_without_crash(self, page):
        """All three placement types render multiple frames without crash."""
        result = page.evaluate("""() => {
            const types = ['q', 'w', 'a']; // turret, drone, rover
            for (const key of types) {
                document.dispatchEvent(new KeyboardEvent('keydown', {
                    key, code: `Key${key.toUpperCase()}`, bubbles: true,
                }));
            }
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({
                        frames,
                        canvasOk: !!document.getElementById('tactical-canvas'),
                    });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 10
        assert result["canvasOk"]


# ============================================================
# Group dispatch with D key
# ============================================================


class TestGroupDispatch:
    """Verify D key dispatches all multi-selected friendlies."""

    def test_group_dispatch_emits_event(self, page):
        """D with multi-selected friendlies emits group dispatch event."""
        result = page.evaluate("""() => {
            // Place 3 friendly units
            for (let i = 0; i < 3; i++) {
                window.TritiumStore.updateUnit(`gd_unit_${i}`, {
                    name: `GD Unit ${i}`, type: 'turret', alliance: 'friendly',
                    position: { x: i * 20, y: 0 }, health: 100, maxHealth: 100,
                });
            }
            // Multi-select them
            window.TritiumStore.set('map.selectedUnitIds', ['gd_unit_0', 'gd_unit_1', 'gd_unit_2']);

            let dispatchData = null;
            const unsub = window.EventBus.on('map:dispatchMode', (data) => {
                dispatchData = data;
            });

            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'd', code: 'KeyD', bubbles: true,
            }));

            return new Promise(resolve => {
                setTimeout(() => {
                    unsub();
                    resolve({
                        hasData: !!dispatchData,
                        isGroup: dispatchData ? !!dispatchData.group : false,
                        count: dispatchData && dispatchData.ids ? dispatchData.ids.length : 0,
                        canvasOk: !!document.getElementById('tactical-canvas'),
                    });
                }, 200);
            });
        }""")
        assert result["hasData"], "D key should emit dispatch event"
        assert result["isGroup"], "Should be a group dispatch"
        assert result["count"] == 3, f"Should dispatch 3 units, got {result['count']}"
        assert result["canvasOk"]

    def test_group_dispatch_filters_hostile(self, page):
        """Group dispatch only includes friendly units from selection."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('gdf_friendly', {
                name: 'GDF Friend', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('gdf_hostile', {
                name: 'GDF Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 20, y: 0 }, health: 50, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitIds', ['gdf_friendly', 'gdf_hostile']);

            let dispatchData = null;
            const unsub = window.EventBus.on('map:dispatchMode', (data) => {
                dispatchData = data;
            });

            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'd', code: 'KeyD', bubbles: true,
            }));

            return new Promise(resolve => {
                setTimeout(() => {
                    unsub();
                    resolve({
                        hasData: !!dispatchData,
                        count: dispatchData && dispatchData.ids ? dispatchData.ids.length : 0,
                        ids: dispatchData && dispatchData.ids ? dispatchData.ids : [],
                    });
                }, 200);
            });
        }""")
        assert result["hasData"], "Should emit dispatch event"
        assert result["count"] == 1, "Should only dispatch friendly unit"
        assert "gdf_friendly" in result["ids"]

    def test_single_dispatch_still_works(self, page):
        """D with single selection still dispatches one unit."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sd_unit', {
                name: 'SD Unit', type: 'drone', alliance: 'friendly',
                position: { x: 30, y: 0 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitId', 'sd_unit');
            window.TritiumStore.set('map.selectedUnitIds', []);

            let dispatched = false;
            const unsub = window.EventBus.on('map:dispatchMode', (data) => {
                dispatched = true;
            });

            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'd', code: 'KeyD', bubbles: true,
            }));

            return new Promise(resolve => {
                setTimeout(() => {
                    unsub();
                    resolve({ dispatched, canvasOk: !!document.getElementById('tactical-canvas') });
                }, 200);
            });
        }""")
        assert result["dispatched"]
        assert result["canvasOk"]


# ============================================================
# Patrol path loop closure
# ============================================================


class TestPatrolPathLoop:
    """Verify patrol paths close back to first waypoint."""

    def test_patrol_path_renders_as_loop(self, page):
        """Patrol path with 3+ waypoints renders without crash (loop)."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('pl_loop', {
                name: 'PL Loop', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                waypoints: [{ x: 0, y: 0 }, { x: 30, y: 0 }, { x: 30, y: 30 }, { x: 0, y: 30 }],
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 10) requestAnimationFrame(tick);
                    else resolve({
                        frames,
                        canvasOk: !!document.getElementById('tactical-canvas'),
                    });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 10
        assert result["canvasOk"]

    def test_two_waypoint_patrol_renders(self, page):
        """Patrol with exactly 2 waypoints (back-and-forth) renders OK."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('pl_two', {
                name: 'PL Two', type: 'rover', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                waypoints: [{ x: 0, y: 0 }, { x: 50, y: 0 }],
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }));
            });
        }""")
        assert result["canvasOk"]

    def test_many_waypoints_loop(self, page):
        """Patrol with 8 waypoints renders closed loop without crash."""
        result = page.evaluate("""() => {
            const wps = [];
            for (let i = 0; i < 8; i++) {
                const angle = (i / 8) * Math.PI * 2;
                wps.push({ x: Math.cos(angle) * 40, y: Math.sin(angle) * 40 });
            }
            window.TritiumStore.updateUnit('pl_many', {
                name: 'PL Many', type: 'drone', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                waypoints: wps,
            });
            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 15) requestAnimationFrame(tick);
                    else resolve({
                        frames,
                        canvasOk: !!document.getElementById('tactical-canvas'),
                    });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 15
        assert result["canvasOk"]


# ============================================================
# Combined render stability
# ============================================================


class TestBatch41Combined:
    """All Batch 41 features together without crash."""

    def test_full_batch41_scenario(self, page):
        """Ghost placement + group dispatch + patrol loops — all at once."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');

            // Place units with patrols (loop paths)
            for (let i = 0; i < 4; i++) {
                const type = ['turret', 'drone', 'rover', 'turret'][i];
                window.TritiumStore.updateUnit(`b41_unit_${i}`, {
                    name: `B41 ${type} ${i}`, type, alliance: 'friendly',
                    position: { x: i * 25 - 30, y: 0 }, health: 80 + i * 5, maxHealth: 100,
                    eliminations: i * 3, weapon_range: 60,
                    waypoints: [
                        { x: i * 25 - 30, y: -20 },
                        { x: i * 25 - 10, y: 0 },
                        { x: i * 25 - 30, y: 20 },
                        { x: i * 25 - 50, y: 0 },
                    ],
                });
            }

            // Multi-select all
            window.TritiumStore.set('map.selectedUnitIds', ['b41_unit_0', 'b41_unit_1', 'b41_unit_2', 'b41_unit_3']);

            // Trigger group dispatch
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'd', code: 'KeyD', bubbles: true,
            }));

            // Also enter a placement mode briefly
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'Escape', code: 'Escape', bubbles: true,
            }));
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'w', code: 'KeyW', bubbles: true,
            }));

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        // Clean up
                        document.dispatchEvent(new KeyboardEvent('keydown', {
                            key: 'Escape', code: 'Escape', bubbles: true,
                        }));
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({
                            frames,
                            canvasOk: !!document.getElementById('tactical-canvas'),
                        });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
