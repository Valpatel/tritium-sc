# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 12 combat UX feature tests.

Verifies panel border flash animations, inline health bars in Units panel,
fog of war globals, EventBus event wiring, and WebSocket event handling.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch12_combat_ux.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ux, pytest.mark.ui]


@pytest.fixture(scope="module")
def _server():
    """Module-scoped server to avoid per-test restarts."""
    srv = TritiumServer(auto_port=True)
    srv.start()
    yield srv
    srv.stop()


@pytest.fixture(scope="module")
def _browser(_server):
    """Module-scoped browser."""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    b = pw.chromium.launch(headless=True)
    yield b
    b.close()
    pw.stop()


@pytest.fixture(scope="module")
def _ctx(_browser, _server):
    """Module-scoped browser context -- single page on /unified."""
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
    """Per-test fixture: yields the shared page, closes any open panels after."""
    p = _ctx["page"]
    yield p
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Panel border flash CSS animations
# ============================================================


class TestPanelBorderFlash:
    """Verify CSS animation classes for panel border flash."""

    def test_threat_flash_keyframes_exist(self, page):
        """panel-threat-flash animation is defined in stylesheet."""
        has_rule = page.evaluate("""() => {
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name === 'panel-threat-flash') {
                            return true;
                        }
                    }
                } catch (_) {}
            }
            return false;
        }""")
        assert has_rule, "panel-threat-flash @keyframes not found in stylesheets"

    def test_alert_flash_keyframes_exist(self, page):
        """panel-alert-flash animation is defined in stylesheet."""
        has_rule = page.evaluate("""() => {
            for (const sheet of document.styleSheets) {
                try {
                    for (const rule of sheet.cssRules) {
                        if (rule.type === CSSRule.KEYFRAMES_RULE && rule.name === 'panel-alert-flash') {
                            return true;
                        }
                    }
                } catch (_) {}
            }
            return false;
        }""")
        assert has_rule, "panel-alert-flash @keyframes not found in stylesheets"

    def test_threat_flash_class_applies_animation(self, page):
        """Adding panel-threat-flash class triggers CSS animation."""
        animation = page.evaluate("""() => {
            const el = document.createElement('div');
            el.className = 'panel-threat-flash';
            document.body.appendChild(el);
            const style = getComputedStyle(el);
            const name = style.animationName;
            el.remove();
            return name;
        }""")
        assert animation == "panel-threat-flash"

    def test_alert_flash_class_applies_animation(self, page):
        """Adding panel-alert-flash class triggers CSS animation."""
        animation = page.evaluate("""() => {
            const el = document.createElement('div');
            el.className = 'panel-alert-flash';
            document.body.appendChild(el);
            const style = getComputedStyle(el);
            const name = style.animationName;
            el.remove();
            return name;
        }""")
        assert animation == "panel-alert-flash"

    def test_amy_panel_subscribes_to_hostile_spawned(self, page):
        """Amy panel mount registers listener for game:hostile_spawned."""
        page.keyboard.press("1")
        page.wait_for_timeout(500)
        has_flash = page.evaluate("""() => {
            return new Promise(resolve => {
                const EB = window.EventBus;
                if (!EB) { resolve(false); return; }
                EB.emit('game:hostile_spawned', { id: 'test_hostile' });
                setTimeout(() => {
                    const panel = document.querySelector('[data-panel-id="amy"]');
                    resolve(panel ? panel.classList.contains('panel-threat-flash') : false);
                }, 100);
            });
        }""")
        page.keyboard.press("1")
        page.wait_for_timeout(200)
        assert has_flash, "Amy panel should flash on hostile_spawned"

    def test_alerts_panel_subscribes_to_alert_new(self, page):
        """Alerts panel mount registers listener for alert:new."""
        page.keyboard.press("3")
        page.wait_for_timeout(500)
        has_flash = page.evaluate("""() => {
            return new Promise(resolve => {
                const EB = window.EventBus;
                if (!EB) { resolve(false); return; }
                EB.emit('alert:new', { type: 'info', message: 'test flash' });
                setTimeout(() => {
                    const panel = document.querySelector('[data-panel-id="alerts"]');
                    resolve(panel ? panel.classList.contains('panel-alert-flash') : false);
                }, 100);
            });
        }""")
        page.keyboard.press("3")
        page.wait_for_timeout(200)
        assert has_flash, "Alerts panel should flash on alert:new"


# ============================================================
# Inline health bars in Units panel
# ============================================================


class TestInlineHealthBars:
    """Verify inline health bars appear in Units panel list items."""

    def _open_units(self, page):
        page.keyboard.press("2")
        page.wait_for_timeout(500)

    def _close_units(self, page):
        page.keyboard.press("2")
        page.wait_for_timeout(200)

    def test_health_bar_elements_exist(self, page):
        """Unit list items contain .unit-inline-hp elements."""
        self._open_units(page)
        count = page.evaluate("""() => {
            return document.querySelectorAll('.unit-inline-hp').length;
        }""")
        self._close_units(page)
        assert count > 0, "No inline health bar elements found"

    def test_health_bar_has_fill_child(self, page):
        """Each .unit-inline-hp has a .unit-inline-hp-fill child."""
        self._open_units(page)
        result = page.evaluate("""() => {
            const bars = document.querySelectorAll('.unit-inline-hp');
            let withFill = 0;
            bars.forEach(b => { if (b.querySelector('.unit-inline-hp-fill')) withFill++; });
            return { total: bars.length, withFill };
        }""")
        self._close_units(page)
        assert result["total"] > 0, "No health bars found"
        assert result["withFill"] == result["total"], "Some health bars missing fill element"

    def test_health_bar_fill_has_width(self, page):
        """Health bar fill elements have nonzero width (units have health)."""
        self._open_units(page)
        has_width = page.evaluate("""() => {
            const fills = document.querySelectorAll('.unit-inline-hp-fill');
            for (const f of fills) {
                if (f.style.width && f.style.width !== '0%') return true;
            }
            return false;
        }""")
        self._close_units(page)
        assert has_width, "No health bar fill has nonzero width"

    def test_health_bar_css_dimensions(self, page):
        """Inline health bar CSS: 48px wide, 3px tall."""
        self._open_units(page)
        dims = page.evaluate("""() => {
            const bar = document.querySelector('.unit-inline-hp');
            if (!bar) return null;
            const style = getComputedStyle(bar);
            return { width: parseFloat(style.width), height: parseFloat(style.height) };
        }""")
        self._close_units(page)
        assert dims is not None, "No health bar found"
        assert abs(dims["width"] - 48) < 2, f"Width should be ~48px, got {dims['width']}"
        assert abs(dims["height"] - 3) < 1, f"Height should be ~3px, got {dims['height']}"


# ============================================================
# EventBus event routing (tests fire events directly)
# ============================================================


class TestEventBusRouting:
    """Verify EventBus events are wired correctly."""

    def test_eventbus_available(self, page):
        """window.EventBus is available on /unified."""
        available = page.evaluate("() => typeof window.EventBus === 'object' && typeof window.EventBus.emit === 'function'")
        assert available, "EventBus not found on window"

    def test_unit_dispatched_event_fires(self, page):
        """EventBus can emit and receive unit:dispatched."""
        got = page.evaluate("""() => {
            return new Promise(resolve => {
                let received = false;
                const unsub = window.EventBus.on('unit:dispatched', () => { received = true; });
                window.EventBus.emit('unit:dispatched', { id: 'test', target: { x: 0, y: 0 } });
                setTimeout(() => { if (typeof unsub === 'function') unsub(); resolve(received); }, 50);
            });
        }""")
        assert got, "unit:dispatched event should fire"

    def test_hostile_spawned_event_fires(self, page):
        """EventBus can emit and receive game:hostile_spawned."""
        got = page.evaluate("""() => {
            return new Promise(resolve => {
                let received = false;
                const unsub = window.EventBus.on('game:hostile_spawned', () => { received = true; });
                window.EventBus.emit('game:hostile_spawned', { id: 'test' });
                setTimeout(() => { if (typeof unsub === 'function') unsub(); resolve(received); }, 50);
            });
        }""")
        assert got, "game:hostile_spawned event should fire"

    def test_alert_new_event_fires(self, page):
        """EventBus can emit and receive alert:new."""
        got = page.evaluate("""() => {
            return new Promise(resolve => {
                let received = false;
                const unsub = window.EventBus.on('alert:new', () => { received = true; });
                window.EventBus.emit('alert:new', { type: 'info', message: 'test' });
                setTimeout(() => { if (typeof unsub === 'function') unsub(); resolve(received); }, 50);
            });
        }""")
        assert got, "alert:new event should fire"

    def test_combat_streak_event_fires(self, page):
        """EventBus can emit and receive combat:streak."""
        got = page.evaluate("""() => {
            return new Promise(resolve => {
                let received = false;
                const unsub = window.EventBus.on('combat:streak', () => { received = true; });
                window.EventBus.emit('combat:streak', { streak: 3, name: 'KILLING SPREE' });
                setTimeout(() => { if (typeof unsub === 'function') unsub(); resolve(received); }, 50);
            });
        }""")
        assert got, "combat:streak event should fire"


# ============================================================
# Fog of war integration
# ============================================================


class TestFogOfWar:
    """Verify fog of war system integration on /unified."""

    def test_fog_draw_function_available(self, page):
        """fogDraw global function is loaded."""
        available = page.evaluate("() => typeof fogDraw === 'function'")
        assert available, "fogDraw should be available globally"

    def test_fog_build_vision_map_available(self, page):
        """fogBuildVisionMap global function is loaded."""
        available = page.evaluate("() => typeof fogBuildVisionMap === 'function'")
        assert available, "fogBuildVisionMap should be available globally"

    def test_fog_is_point_visible_available(self, page):
        """fogIsPointVisible global function is loaded."""
        available = page.evaluate("() => typeof fogIsPointVisible === 'function'")
        assert available, "fogIsPointVisible should be available globally"

    def test_fog_setup_preview_available(self, page):
        """fogDrawSetupPreview global function is loaded."""
        available = page.evaluate("() => typeof fogDrawSetupPreview === 'function'")
        assert available, "fogDrawSetupPreview should be available globally"

    def test_fog_vision_circles_from_friendlies(self, page):
        """fogBuildVisionMap produces circles for friendly units."""
        count = page.evaluate("""() => {
            if (typeof fogBuildVisionMap !== 'function') return -1;
            const targets = {};
            window.TritiumStore.units.forEach((u, id) => {
                targets[id] = {
                    x: u.position?.x || 0,
                    y: u.position?.y || 0,
                    position: u.position,
                    alliance: u.alliance || 'unknown',
                    asset_type: u.type || '',
                    status: u.status || 'active',
                };
            });
            return fogBuildVisionMap(targets).length;
        }""")
        assert count > 0, "Should have vision circles from friendly units"

    def test_fog_point_visibility_check(self, page):
        """Points near friendly units are visible; far-away points are not."""
        result = page.evaluate("""() => {
            if (typeof fogBuildVisionMap !== 'function' || typeof fogIsPointVisible !== 'function') return null;
            const targets = {};
            let friendlyPos = null;
            window.TritiumStore.units.forEach((u, id) => {
                targets[id] = {
                    x: u.position?.x || 0,
                    y: u.position?.y || 0,
                    position: u.position,
                    alliance: u.alliance || 'unknown',
                    asset_type: u.type || '',
                    status: u.status || 'active',
                };
                if (u.alliance === 'friendly' && u.position) friendlyPos = u.position;
            });
            const circles = fogBuildVisionMap(targets);
            if (!friendlyPos || circles.length === 0) return null;
            const nearVisible = fogIsPointVisible(friendlyPos.x, friendlyPos.y, circles);
            const farVisible = fogIsPointVisible(9999, 9999, circles);
            return { nearVisible, farVisible };
        }""")
        assert result is not None, "Could not run visibility test"
        assert result["nearVisible"] is True, "Point near friendly should be visible"
        assert result["farVisible"] is False, "Point far from all friendlies should be in fog"

    def test_fog_vision_radii_per_type(self, page):
        """FOG_VISION_RADII has entries for turret, drone, rover."""
        result = page.evaluate("""() => {
            if (typeof FOG_VISION_RADII === 'undefined') return null;
            return {
                turret: FOG_VISION_RADII.turret,
                drone: FOG_VISION_RADII.drone,
                rover: FOG_VISION_RADII.rover,
            };
        }""")
        assert result is not None, "FOG_VISION_RADII not found"
        assert result["turret"] == 50, f"Turret vision should be 50, got {result['turret']}"
        assert result["drone"] == 60, f"Drone vision should be 60, got {result['drone']}"
        assert result["rover"] == 40, f"Rover vision should be 40, got {result['rover']}"


# ============================================================
# TritiumStore integration
# ============================================================


class TestStoreIntegration:
    """Verify TritiumStore has the data structures used by Batch 12 features."""

    def test_store_has_units_map(self, page):
        """TritiumStore.units is a Map with entries."""
        size = page.evaluate("() => window.TritiumStore.units.size")
        assert size > 0, "TritiumStore.units should have entries"

    def test_units_have_health_fields(self, page):
        """At least one unit has health and maxHealth fields."""
        has_health = page.evaluate("""() => {
            let found = false;
            window.TritiumStore.units.forEach(u => {
                if (u.health !== undefined && u.maxHealth !== undefined) found = true;
            });
            return found;
        }""")
        assert has_health, "At least one unit should have health/maxHealth"

    def test_units_have_alliance(self, page):
        """All units have an alliance field."""
        result = page.evaluate("""() => {
            let total = 0, withAlliance = 0;
            window.TritiumStore.units.forEach(u => {
                total++;
                if (u.alliance) withAlliance++;
            });
            return { total, withAlliance };
        }""")
        assert result["total"] > 0
        assert result["withAlliance"] == result["total"], "All units should have alliance"

    def test_store_addAlert_works(self, page):
        """TritiumStore.addAlert adds to alerts array."""
        count = page.evaluate("""() => {
            const before = (window.TritiumStore.alerts || []).length;
            window.TritiumStore.addAlert({ type: 'test', message: 'Test alert', source: 'test' });
            const after = (window.TritiumStore.alerts || []).length;
            return after - before;
        }""")
        assert count == 1, "addAlert should add one alert"
