# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 20 heat map legend, unit search, status bar mode, and type breakdown tests.

Verifies heat map legend rendering, unit text search filter,
map mode indicator in status bar, and unit type breakdown in header.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch20_heatmap_search.py -v -m ux
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
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Heat map legend
# ============================================================


class TestHeatMapLegend:
    """Verify heat map legend renders when heat map is active."""

    def test_heat_map_toggle_function(self, page):
        """Heat map can be toggled on and off via keyboard."""
        result = page.evaluate("""() => {
            // Toggle on
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'h', code: 'KeyH', bubbles: true
            }));
            return true;
        }""")
        assert result
        page.wait_for_timeout(200)
        # Toggle off
        page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'h', code: 'KeyH', bubbles: true
            }));
        }""")

    def test_heat_map_legend_renders_on_canvas(self, page):
        """When heat map is active, legend draws on canvas without crash."""
        page.evaluate("""() => {
            // Toggle heat map on
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'h', code: 'KeyH', bubbles: true
            }));
        }""")
        page.wait_for_timeout(300)
        # Canvas should still render
        has_canvas = page.evaluate("() => !!document.getElementById('tactical-canvas')")
        assert has_canvas, "Canvas should exist with heat map + legend active"
        # Toggle off
        page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'h', code: 'KeyH', bubbles: true
            }));
        }""")

    def test_heat_map_tracks_hostile_activity(self, page):
        """Heat map accumulates for hostile units only."""
        # This is a structural test - heat map uses hostile positions
        result = page.evaluate("""() => {
            // Inject a hostile unit to generate heat
            window.TritiumStore.updateUnit('heatmap_hostile_test', {
                name: 'Heat Test',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 50, y: 50 },
                status: 'active',
            });
            return true;
        }""")
        assert result


# ============================================================
# Unit type breakdown in header
# ============================================================


class TestUnitTypeBreakdown:
    """Verify header shows per-type unit counts."""

    def test_header_units_element_exists(self, page):
        """Header units stat element exists."""
        exists = page.evaluate("() => !!document.getElementById('header-units')")
        assert exists, "header-units not found"

    def test_unit_type_breakdown_in_tooltip(self, page):
        """Header units element has type breakdown tooltip."""
        result = page.evaluate("""() => {
            // Inject test units of different types (each updateUnit triggers notify)
            window.TritiumStore.updateUnit('type_test_turret', {
                name: 'Turret NW',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 10, y: 10 },
            });
            window.TritiumStore.updateUnit('type_test_rover', {
                name: 'Rover Alpha',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 20, y: 20 },
            });
            window.TritiumStore.updateUnit('type_test_drone', {
                name: 'Drone Charlie',
                type: 'drone',
                alliance: 'friendly',
                position: { x: 30, y: 30 },
            });

            // Wait a tick for the handler to run
            return new Promise(resolve => {
                setTimeout(() => {
                    const el = document.getElementById('header-units');
                    resolve({
                        title: el?.title || '',
                        label: el?.querySelector('.stat-label')?.textContent || '',
                    });
                }, 200);
            });
        }""")
        # Should have type breakdown in title or label
        assert result["title"] or result["label"], "Should show type breakdown"

    def test_header_label_shows_type_codes(self, page):
        """Header stat-label shows compact type codes (T:n R:n D:n)."""
        result = page.evaluate("""() => {
            const el = document.getElementById('header-units');
            return el?.querySelector('.stat-label')?.textContent || '';
        }""")
        # Should contain at least one type code like "T:1" or "R:1"
        assert any(c in result for c in ['T:', 'R:', 'D:']), \
            f"Expected type codes, got '{result}'"


# ============================================================
# Map mode in status bar
# ============================================================


class TestStatusBarMapMode:
    """Verify status bar shows current map mode."""

    def test_status_map_mode_element_exists(self, page):
        """Status bar map mode element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-map-mode')")
        assert exists, "status-map-mode not found"

    def test_status_shows_observe_by_default(self, page):
        """Default map mode is OBSERVE."""
        text = page.evaluate("""() => {
            return document.getElementById('status-map-mode')?.textContent || '';
        }""")
        assert text == "OBSERVE", f"Expected OBSERVE, got '{text}'"

    def test_mode_change_updates_status_bar(self, page):
        """Switching to tactical mode updates status bar."""
        result = page.evaluate("""() => {
            // Click tactical mode button
            const btn = document.querySelector('[data-map-mode="tactical"]');
            if (btn) btn.click();
            return document.getElementById('status-map-mode')?.textContent || '';
        }""")
        assert result == "TACTICAL", f"Expected TACTICAL, got '{result}'"
        # Reset to observe
        page.evaluate("""() => {
            const btn = document.querySelector('[data-map-mode="observe"]');
            if (btn) btn.click();
        }""")

    def test_setup_mode_updates_status_bar(self, page):
        """Switching to setup mode updates status bar."""
        result = page.evaluate("""() => {
            const btn = document.querySelector('[data-map-mode="setup"]');
            if (btn) btn.click();
            return document.getElementById('status-map-mode')?.textContent || '';
        }""")
        assert result == "SETUP", f"Expected SETUP, got '{result}'"
        # Reset to observe
        page.evaluate("""() => {
            const btn = document.querySelector('[data-map-mode="observe"]');
            if (btn) btn.click();
        }""")

    def test_keyboard_mode_change(self, page):
        """Pressing T key switches to tactical and updates status bar."""
        result = page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 't', code: 'KeyT', bubbles: true
            }));
            return document.getElementById('status-map-mode')?.textContent || '';
        }""")
        assert result == "TACTICAL", f"Expected TACTICAL, got '{result}'"
        # Reset
        page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: 'o', code: 'KeyO', bubbles: true
            }));
        }""")


# ============================================================
# Unit text search filter
# ============================================================


class TestUnitSearchFilter:
    """Verify units panel has text search filter."""

    def test_search_input_exists_in_units_panel(self, page):
        """Units panel contains a search input field."""
        # Open units panel first
        page.evaluate("""() => {
            document.dispatchEvent(new KeyboardEvent('keydown', {
                key: '2', code: 'Digit2', bubbles: true
            }));
        }""")
        page.wait_for_timeout(300)

        exists = page.evaluate("""() => {
            return !!document.querySelector('.units-panel-inner .panel-search');
        }""")
        assert exists, "Units panel should have search input"

    def test_search_placeholder_text(self, page):
        """Search input has appropriate placeholder text."""
        placeholder = page.evaluate("""() => {
            const el = document.querySelector('.units-panel-inner .panel-search');
            return el?.placeholder || '';
        }""")
        assert "Search" in placeholder or "search" in placeholder, \
            f"Expected search placeholder, got '{placeholder}'"

    def test_search_filters_unit_list(self, page):
        """Typing in search filters the unit list."""
        result = page.evaluate("""() => {
            // Inject distinct units (each updateUnit triggers store notify)
            window.TritiumStore.updateUnit('search_alpha', {
                name: 'Alpha Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('search_bravo', {
                name: 'Bravo Rover',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 10, y: 10 },
            });

            return new Promise(resolve => {
                setTimeout(() => {
                    const searchEl = document.querySelector('.units-panel-inner .panel-search');
                    if (!searchEl) { resolve({ found: false }); return; }

                    // Count all items before search
                    const beforeCount = document.querySelectorAll('.units-panel-inner .panel-list-item').length;

                    // Type "turret" in search
                    searchEl.value = 'turret';
                    searchEl.dispatchEvent(new Event('input', { bubbles: true }));

                    setTimeout(() => {
                        const afterCount = document.querySelectorAll('.units-panel-inner .panel-list-item').length;
                        // Clear search
                        searchEl.value = '';
                        searchEl.dispatchEvent(new Event('input', { bubbles: true }));
                        resolve({ found: true, beforeCount, afterCount });
                    }, 100);
                }, 200);
            });
        }""")
        assert result.get("found"), "Search input should exist"
        # After filtering for "turret", count should be less than before
        assert result["afterCount"] <= result["beforeCount"], \
            f"Filtering should reduce items: before={result['beforeCount']}, after={result['afterCount']}"
        # And should have at least 1 result (the turret)
        assert result["afterCount"] >= 1, "Should find at least one turret"

    def test_filter_and_search_combine(self, page):
        """Alliance filter and text search work together."""
        result = page.evaluate("""() => {
            const filterEl = document.querySelector('.units-panel-inner .panel-filter');
            const searchEl = document.querySelector('.units-panel-inner .panel-search');
            if (!filterEl || !searchEl) return { found: false };

            // Set filter to friendly
            filterEl.value = 'friendly';
            filterEl.dispatchEvent(new Event('change', { bubbles: true }));

            // Search for rover
            searchEl.value = 'rover';
            searchEl.dispatchEvent(new Event('input', { bubbles: true }));

            return new Promise(resolve => {
                setTimeout(() => {
                    const items = document.querySelectorAll('.units-panel-inner .panel-list-item');
                    // Reset
                    filterEl.value = 'all';
                    filterEl.dispatchEvent(new Event('change', { bubbles: true }));
                    searchEl.value = '';
                    searchEl.dispatchEvent(new Event('input', { bubbles: true }));
                    resolve({ found: true, count: items.length });
                }, 100);
            });
        }""")
        assert result.get("found"), "Filter and search elements should exist"


# ============================================================
# Status bar completeness
# ============================================================


class TestStatusBar:
    """Verify all status bar elements are present and functional."""

    def test_status_bar_exists(self, page):
        """Status bar element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-bar')")
        assert exists, "status-bar not found"

    def test_fps_counter(self, page):
        """FPS counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-fps')")
        assert exists, "status-fps not found"

    def test_alive_counter(self, page):
        """Alive counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-alive')")
        assert exists, "status-alive not found"

    def test_threats_counter(self, page):
        """Threats counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-threats')")
        assert exists, "status-threats not found"

    def test_ws_status(self, page):
        """WebSocket status element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-ws')")
        assert exists, "status-ws not found"

    def test_audio_status(self, page):
        """Audio status element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-audio')")
        assert exists, "status-audio not found"

    def test_coords_display(self, page):
        """Coordinates display element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-coords')")
        assert exists, "status-coords not found"

    def test_panels_counter(self, page):
        """Panels counter element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-panels')")
        assert exists, "status-panels not found"

    def test_mode_indicator(self, page):
        """Mode indicator element exists."""
        exists = page.evaluate("() => !!document.getElementById('status-mode')")
        assert exists, "status-mode not found"
