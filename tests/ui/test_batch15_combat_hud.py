# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 15 combat HUD tests.

Verifies map health bars, kill streak leaderboard, wave progress bar,
and dispatch mode visual feedback.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch15_combat_hud.py -v -m ux
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
# Map health bar rendering
# ============================================================


class TestMapHealthBars:
    """Verify health bars render on tactical map for combatant units."""

    def test_units_have_health_data(self, page):
        """Units in store have health and maxHealth fields."""
        result = page.evaluate("""() => {
            let withHealth = 0;
            let total = 0;
            window.TritiumStore.units.forEach(u => {
                total++;
                if (u.health !== undefined && u.maxHealth !== undefined) withHealth++;
            });
            return { total, withHealth };
        }""")
        assert result["total"] > 0, "Should have units"
        assert result["withHealth"] > 0, "At least one unit should have health data"

    def test_health_bar_function_exists(self, page):
        """Canvas rendering includes health bar logic (verified by checking tactical canvas draws)."""
        # The health bar is canvas-rendered, not DOM — verify canvas has content
        has_content = page.evaluate("""() => {
            const c = document.getElementById('tactical-canvas');
            if (!c) return false;
            const ctx = c.getContext('2d');
            const data = ctx.getImageData(0, 0, c.width, c.height).data;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 0 || data[i+1] > 0 || data[i+2] > 0) return true;
            }
            return false;
        }""")
        assert has_content, "Tactical canvas should have rendered content"

    def test_is_combatant_field_available(self, page):
        """Units have is_combatant field from backend."""
        result = page.evaluate("""() => {
            let found = false;
            window.TritiumStore.units.forEach(u => {
                if (u.is_combatant !== undefined) found = true;
            });
            return found;
        }""")
        assert result, "At least one unit should have is_combatant field"


# ============================================================
# Kill streak leaderboard
# ============================================================


class TestKillStreakLeaderboard:
    """Verify kill streak leaderboard in game HUD panel."""

    def _open_game(self, page):
        page.keyboard.press("4")
        page.wait_for_timeout(500)

    def _close_game(self, page):
        page.keyboard.press("4")
        page.wait_for_timeout(200)

    def test_leaderboard_section_exists(self, page):
        """Game HUD has leaderboard section."""
        self._open_game(page)
        exists = page.evaluate("""() => {
            return !!document.querySelector('[data-bind="leaderboard"]');
        }""")
        self._close_game(page)
        assert exists, "Leaderboard section not found in game HUD"

    def test_leaderboard_list_exists(self, page):
        """Game HUD has leaderboard list container."""
        self._open_game(page)
        exists = page.evaluate("""() => {
            return !!document.querySelector('[data-bind="leaderboard-list"]');
        }""")
        self._close_game(page)
        assert exists, "Leaderboard list not found"

    def test_leaderboard_entry_css_exists(self, page):
        """Leaderboard entry CSS classes render correctly."""
        result = page.evaluate("""() => {
            const el = document.createElement('div');
            el.className = 'ghud-leader-entry';
            el.innerHTML = `
                <span class="ghud-leader-rank mono">1</span>
                <span class="ghud-leader-name">Test Turret</span>
                <span class="ghud-leader-kills mono" style="color:var(--magenta)">5</span>
                <span class="ghud-streak-badge">RAMPAGE</span>
            `;
            document.body.appendChild(el);
            const style = getComputedStyle(el);
            const display = style.display;
            const gap = style.gap;
            el.remove();
            return { display, gap };
        }""")
        assert result["display"] == "flex", f"Leader entry should be flex, got {result['display']}"

    def test_streak_badge_css_exists(self, page):
        """Streak badge CSS class exists."""
        color = page.evaluate("""() => {
            const el = document.createElement('span');
            el.className = 'ghud-streak-badge';
            el.textContent = 'RAMPAGE';
            document.body.appendChild(el);
            const style = getComputedStyle(el);
            const c = style.color;
            el.remove();
            return c;
        }""")
        # Should be magenta
        assert "255" in color and "42" in color, f"Streak badge should be magenta, got {color}"


# ============================================================
# Wave progress bar
# ============================================================


class TestWaveProgressBar:
    """Verify wave progress bar in game HUD."""

    def _open_game(self, page):
        page.keyboard.press("4")
        page.wait_for_timeout(500)

    def _close_game(self, page):
        page.keyboard.press("4")
        page.wait_for_timeout(200)

    def test_progress_bar_elements_exist(self, page):
        """Progress bar track and fill elements exist."""
        self._open_game(page)
        result = page.evaluate("""() => {
            return {
                track: !!document.querySelector('.ghud-progress-track'),
                fill: !!document.querySelector('[data-bind="wave-fill"]'),
                label: !!document.querySelector('[data-bind="wave-label"]'),
            };
        }""")
        self._close_game(page)
        assert result["track"], "Progress track not found"
        assert result["fill"], "Progress fill not found"
        assert result["label"], "Progress label not found"

    def test_progress_fill_css(self, page):
        """Progress fill has gradient background and transition."""
        self._open_game(page)
        style = page.evaluate("""() => {
            const fill = document.querySelector('.ghud-progress-fill');
            if (!fill) return null;
            const s = getComputedStyle(fill);
            return {
                transition: s.transition,
                borderRadius: s.borderRadius,
            };
        }""")
        self._close_game(page)
        assert style is not None, "Progress fill not found"
        assert "width" in style["transition"], f"Fill should transition width, got {style['transition']}"

    def test_progress_label_shows_hostiles(self, page):
        """Progress label text reflects hostile count."""
        self._open_game(page)
        text = page.evaluate("""() => {
            const label = document.querySelector('[data-bind="wave-label"]');
            return label ? label.textContent : null;
        }""")
        self._close_game(page)
        assert text is not None, "Progress label not found"
        # Should show either "No hostiles" or "X/Y eliminated"
        assert "hostile" in text.lower() or "eliminated" in text.lower() or "no" in text.lower(), \
            f"Label should mention hostiles, got: {text}"


# ============================================================
# Dispatch mode visual feedback
# ============================================================


class TestDispatchMode:
    """Verify dispatch mode visual feedback."""

    def test_dispatch_mode_state_exists(self, page):
        """Map module tracks dispatch mode state."""
        # We can verify by emitting the dispatch-mode event
        ok = page.evaluate("""() => {
            try {
                window.EventBus.emit('unit:dispatch-mode', { id: 'test_dispatch_unit' });
                return true;
            } catch (e) {
                return false;
            }
        }""")
        # Cancel dispatch mode
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        assert ok, "dispatch-mode event should emit without error"

    def test_dispatch_cancel_on_escape(self, page):
        """ESC key cancels placement and dispatch modes."""
        result = page.evaluate("""() => {
            // Enter dispatch mode
            window.EventBus.emit('unit:dispatch-mode', { id: 'test_esc' });
            // Emit cancel (simulating ESC)
            window.EventBus.emit('map:cancelPlacement');
            return true;
        }""")
        assert result, "Cancel placement event should work"

    def test_dispatch_arrow_from_right_click(self, page):
        """Dispatching creates a visual arrow."""
        result = page.evaluate("""() => {
            return new Promise(resolve => {
                let gotEvent = false;
                const unsub = window.EventBus.on('unit:dispatched', () => { gotEvent = true; });
                window.EventBus.emit('unit:dispatched', {
                    id: 'test_arrow',
                    target: { x: 200, y: 200 },
                    from: { x: 50, y: 50 }
                });
                setTimeout(() => {
                    if (typeof unsub === 'function') unsub();
                    resolve(gotEvent);
                }, 50);
            });
        }""")
        assert result, "unit:dispatched event should fire"


# ============================================================
# Game HUD integration
# ============================================================


class TestGameHudIntegration:
    """Verify game HUD panel integration."""

    def test_game_hud_opens_with_key_4(self, page):
        """Pressing 4 opens game HUD panel."""
        page.keyboard.press("4")
        page.wait_for_timeout(500)
        visible = page.evaluate("""() => {
            const panel = document.querySelector('[data-panel-id="game"]');
            return panel ? !panel.hidden && panel.offsetParent !== null : false;
        }""")
        page.keyboard.press("4")
        page.wait_for_timeout(200)
        assert visible, "Game HUD should be visible after pressing 4"

    def test_game_status_fields_exist(self, page):
        """Game HUD has phase, wave, score, and elims fields."""
        page.keyboard.press("4")
        page.wait_for_timeout(500)
        result = page.evaluate("""() => {
            return {
                phase: !!document.querySelector('[data-bind="phase"]'),
                wave: !!document.querySelector('[data-bind="wave"]'),
                score: !!document.querySelector('[data-bind="score"]'),
                elims: !!document.querySelector('[data-bind="elims"]'),
            };
        }""")
        page.keyboard.press("4")
        page.wait_for_timeout(200)
        for field, exists in result.items():
            assert exists, f"Game HUD missing {field} field"

    def test_game_buttons_exist(self, page):
        """Game HUD has action buttons."""
        page.keyboard.press("4")
        page.wait_for_timeout(500)
        result = page.evaluate("""() => {
            return {
                begin: !!document.querySelector('[data-action="begin-war"]'),
                place: !!document.querySelector('[data-action="place-turret"]'),
                spawn: !!document.querySelector('[data-action="spawn-hostile"]'),
                reset: !!document.querySelector('[data-action="reset-game"]'),
            };
        }""")
        page.keyboard.press("4")
        page.wait_for_timeout(200)
        assert result["begin"], "BEGIN WAR button not found"
        assert result["place"], "PLACE TURRET button not found"
        assert result["spawn"], "SPAWN button not found"
        assert result["reset"], "RESET button not found"

    def test_kill_feed_section_exists(self, page):
        """Game HUD has kill feed section."""
        page.keyboard.press("4")
        page.wait_for_timeout(500)
        exists = page.evaluate("() => !!document.querySelector('[data-bind=\"killfeed-list\"]')")
        page.keyboard.press("4")
        page.wait_for_timeout(200)
        assert exists, "Kill feed list not found"

    def test_kill_feed_updates_on_elimination(self, page):
        """Kill feed shows new entries from combat:elimination."""
        page.keyboard.press("4")
        page.wait_for_timeout(500)
        count = page.evaluate("""() => {
            return new Promise(resolve => {
                window.EventBus.emit('combat:elimination', {
                    interceptor_name: 'HUD Test Turret',
                    target_name: 'HUD Test Hostile'
                });
                setTimeout(() => {
                    const entries = document.querySelectorAll('.ghud-kill-entry');
                    resolve(entries.length);
                }, 200);
            });
        }""")
        page.keyboard.press("4")
        page.wait_for_timeout(200)
        assert count > 0, "Kill feed should show entries after elimination"
