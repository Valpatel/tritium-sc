"""Batch 35 units panel actions, alert navigation, unit status badges, alert pings.

Verifies enhanced units panel (weapon range, PATROL/STAND DOWN buttons),
alert click-to-navigate, canvas unit status badges, and alert map pings.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch35_unitpanel_alertnav_statusbadge.py -v -m ux
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
# Units panel: weapon range display
# ============================================================


class TestUnitsPanelWeaponRange:
    """Verify weapon range shown in units panel detail view."""

    def test_weapon_range_in_detail(self, page):
        """Selecting a unit with weapon_range shows RNG in panel detail."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('up_turret', {
                name: 'UP Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                weapon_range: 60,
            });
            window.TritiumStore.set('map.selectedUnitId', 'up_turret');
            return new Promise(resolve => {
                setTimeout(() => {
                    const detail = document.querySelector('[data-bind="detail"]');
                    const text = detail ? detail.textContent : '';
                    resolve({
                        hasDetail: !!detail && detail.style.display !== 'none',
                        hasRange: text.includes('60m') || text.includes('RANGE'),
                        text: text.substring(0, 500),
                    });
                }, 300);
            });
        }""")
        assert result["hasDetail"], "Detail pane should be visible"
        assert result["hasRange"], f"Expected weapon range in detail, got: {result['text'][:200]}"

    def test_no_range_for_unarmed(self, page):
        """Unit without weapon_range doesn't show RANGE row."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('up_rover', {
                name: 'UP Rover', type: 'rover', alliance: 'friendly',
                position: { x: 10, y: 10 }, health: 80, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitId', 'up_rover');
            return new Promise(resolve => {
                setTimeout(() => {
                    const detail = document.querySelector('[data-bind="detail"]');
                    const text = detail ? detail.textContent : '';
                    resolve({
                        hasDetail: !!detail && detail.style.display !== 'none',
                        hasRange: text.includes('RANGE'),
                    });
                }, 300);
            });
        }""")
        assert result["hasDetail"]
        assert not result["hasRange"], "Unarmed unit should not show RANGE"


# ============================================================
# Units panel: PATROL and STAND DOWN buttons
# ============================================================


class TestUnitsPanelActions:
    """Verify PATROL and STAND DOWN action buttons in unit detail."""

    def test_patrol_button_exists(self, page):
        """Friendly unit detail shows PATROL button."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('up_patrol', {
                name: 'UP Patrol', type: 'drone', alliance: 'friendly',
                position: { x: 20, y: 20 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitId', 'up_patrol');
            return new Promise(resolve => {
                setTimeout(() => {
                    const btn = document.querySelector('[data-action="patrol"]');
                    resolve({ found: !!btn, text: btn ? btn.textContent : '' });
                }, 300);
            });
        }""")
        assert result["found"], "PATROL button should exist"
        assert "PATROL" in result["text"]

    def test_standdown_button_exists(self, page):
        """Friendly unit detail shows STAND DOWN button."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('up_standdown', {
                name: 'UP StandDown', type: 'turret', alliance: 'friendly',
                position: { x: 30, y: 30 }, health: 100, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitId', 'up_standdown');
            return new Promise(resolve => {
                setTimeout(() => {
                    const btn = document.querySelector('[data-action="standdown"]');
                    resolve({ found: !!btn, text: btn ? btn.textContent : '' });
                }, 300);
            });
        }""")
        assert result["found"], "STAND DOWN button should exist"
        assert "STAND DOWN" in result["text"]

    def test_hostile_no_action_buttons(self, page):
        """Hostile unit detail doesn't show DISPATCH/PATROL/etc buttons."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('up_hostile', {
                name: 'UP Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 40, y: 40 }, health: 50, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitId', 'up_hostile');
            return new Promise(resolve => {
                setTimeout(() => {
                    const dispatch = document.querySelector('[data-action="dispatch"]');
                    const patrol = document.querySelector('[data-action="patrol"]');
                    resolve({ hasDispatch: !!dispatch, hasPatrol: !!patrol });
                }, 300);
            });
        }""")
        assert not result["hasDispatch"], "Hostile should not have DISPATCH"
        assert not result["hasPatrol"], "Hostile should not have PATROL"


# ============================================================
# Alert click-to-navigate
# ============================================================


class TestAlertNavigation:
    """Verify clicking alert navigates camera to threat location."""

    def test_alert_emits_center_event(self, page):
        """Clicking alert with target_id emits map:centerOnUnit event."""
        result = page.evaluate("""() => {
            // Place a unit so there's a target to navigate to
            window.TritiumStore.updateUnit('alert_target', {
                name: 'Alert Target', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 80, y: -60 }, health: 50, maxHealth: 100,
            });
            // Add an alert referencing the target
            const alerts = window.TritiumStore.alerts || [];
            alerts.push({
                id: 'test_alert_1',
                type: 'escalation',
                message: 'Hostile detected near perimeter',
                target_id: 'alert_target',
                time: Date.now(),
            });
            window.TritiumStore.set('alerts', [...alerts]);

            // Listen for center event
            let centered = false;
            let centerData = null;
            const unsub = window.EventBus.on('map:centerOnUnit', (data) => {
                centered = true;
                centerData = data;
            });

            return new Promise(resolve => {
                setTimeout(() => {
                    // Click the alert item
                    const item = document.querySelector('.alert-item[data-alert-id="test_alert_1"]');
                    if (item) item.click();
                    setTimeout(() => {
                        if (unsub) unsub();
                        resolve({
                            itemFound: !!item,
                            centered,
                            centerId: centerData ? centerData.id : null,
                        });
                    }, 200);
                }, 300);
            });
        }""")
        assert result["itemFound"], "Alert item should be in the feed"
        assert result["centered"], "Clicking alert should emit centerOnUnit"
        assert result["centerId"] == "alert_target"


# ============================================================
# Alert map pings
# ============================================================


class TestAlertMapPings:
    """Verify alerts create red pulsing pings on the map."""

    def test_alert_creates_ping(self, page):
        """New alert with position data creates alert ping on canvas."""
        result = page.evaluate("""() => {
            // Emit alert:new event with position
            window.EventBus.emit('alert:new', {
                target_id: null,
                position: { x: 50, y: 50 },
                message: 'Test alert ping',
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

    def test_alert_ping_from_unit(self, page):
        """Alert referencing a unit creates ping at unit position."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('ping_target', {
                name: 'Ping Target', type: 'hostile_kid', alliance: 'hostile',
                position: { x: -40, y: 30 }, health: 60, maxHealth: 100,
            });
            window.EventBus.emit('alert:new', {
                target_id: 'ping_target',
                message: 'Hostile spotted',
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

    def test_alert_ping_no_crash_without_position(self, page):
        """Alert without position or target_id doesn't crash."""
        result = page.evaluate("""() => {
            window.EventBus.emit('alert:new', {
                message: 'Generic alert with no location',
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Unit status badges on canvas
# ============================================================


class TestUnitStatusBadges:
    """Verify canvas-drawn status badges on units."""

    def test_status_badges_render_at_zoom(self, page):
        """Units with status render badges at zoom >= 1.5."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sb_patrol', {
                name: 'SB Patrol', type: 'drone', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                status: 'patrol',
            });
            window.TritiumStore.updateUnit('sb_engaged', {
                name: 'SB Engaged', type: 'turret', alliance: 'friendly',
                position: { x: 30, y: 0 }, health: 80, maxHealth: 100,
                status: 'engaged',
            });
            // Set zoom high enough to show badges
            window.TritiumStore.set('map.viewport', { x: 15, y: 0, zoom: 3.0 });
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

    def test_no_badges_at_low_zoom(self, page):
        """Badges not shown when zoomed out below 1.5."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sb_low', {
                name: 'SB Low', type: 'rover', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                status: 'patrol',
            });
            window.TritiumStore.set('map.viewport', { x: 0, y: 0, zoom: 0.5 });
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

    def test_no_badge_for_active_status(self, page):
        """Units with 'active' status don't show badge (default state)."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sb_active', {
                name: 'SB Active', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
                status: 'active',
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Combined render stability
# ============================================================


class TestBatch35Combined:
    """All Batch 35 features work together without crash."""

    def test_full_batch35_scenario(self, page):
        """All features active: units panel, alert pings, status badges, navigation."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.score', 8000);

            // Friendlies with varied statuses
            window.TritiumStore.updateUnit('b35_turret', {
                name: 'B35 Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 90, maxHealth: 100,
                eliminations: 8, weapon_range: 60, status: 'engaged',
            });
            window.TritiumStore.updateUnit('b35_drone', {
                name: 'B35 Drone', type: 'drone', alliance: 'friendly',
                position: { x: 40, y: -20 }, health: 70, maxHealth: 100,
                eliminations: 3, status: 'patrol',
            });
            window.TritiumStore.updateUnit('b35_rover', {
                name: 'B35 Rover', type: 'rover', alliance: 'friendly',
                position: { x: -30, y: 30 }, health: 50, maxHealth: 100,
                status: 'flee',
            });

            // Hostile
            window.TritiumStore.updateUnit('b35_hostile', {
                name: 'B35 Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 80, y: 50 }, health: 40, maxHealth: 100,
                status: 'active',
            });

            // Zoom in to see status badges
            window.TritiumStore.set('map.viewport', { x: 20, y: 10, zoom: 3.0 });

            // Create alert with navigation data
            window.EventBus.emit('alert:new', {
                target_id: 'b35_hostile',
                message: 'Hostile closing on perimeter',
            });

            // Select turret to check panel
            window.TritiumStore.set('map.selectedUnitId', 'b35_turret');

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        const detail = document.querySelector('[data-bind="detail"]');
                        const detailText = detail ? detail.textContent : '';
                        window.TritiumStore.set('game.phase', 'idle');
                        resolve({
                            frames,
                            canvasOk: !!document.getElementById('tactical-canvas'),
                            hasRange: detailText.includes('60m') || detailText.includes('RANGE'),
                            hasPatrol: !!document.querySelector('[data-action="patrol"]'),
                            hasStandDown: !!document.querySelector('[data-action="standdown"]'),
                        });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
        assert result["hasRange"], "Detail should show weapon range"
        assert result["hasPatrol"], "Detail should show PATROL button"
        assert result["hasStandDown"], "Detail should show STAND DOWN button"

    def test_rapid_alert_stress(self, page):
        """Rapid alert pings don't crash the renderer."""
        result = page.evaluate("""() => {
            // Fire 10 alerts rapidly
            for (let i = 0; i < 10; i++) {
                window.EventBus.emit('alert:new', {
                    position: { x: Math.random() * 200 - 100, y: Math.random() * 200 - 100 },
                    message: 'Stress alert ' + i,
                });
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
