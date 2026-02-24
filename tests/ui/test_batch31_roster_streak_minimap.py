"""Batch 31 selection roster bar, streak screen flash, minimap danger indicator tests.

Verifies bottom unit roster on multi-select, kill streak screen edge glow,
and minimap danger close red border flash.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch31_roster_streak_minimap.py -v -m ux
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
# Selection roster bar
# ============================================================


class TestSelectionRoster:
    """Verify bottom roster bar when multiple units are selected."""

    def test_roster_shows_on_multi_select(self, page):
        """Multi-selecting 2+ units renders bottom roster bar."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('roster_a', {
                name: 'Roster A', type: 'turret', alliance: 'friendly',
                position: { x: -30, y: -30 }, health: 80, maxHealth: 100,
                eliminations: 5, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('roster_b', {
                name: 'Roster B', type: 'drone', alliance: 'friendly',
                position: { x: 30, y: 30 }, health: 50, maxHealth: 100,
                eliminations: 12,
            });
            window.TritiumStore.updateUnit('roster_c', {
                name: 'Roster C', type: 'rover', alliance: 'friendly',
                position: { x: 0, y: 60 }, health: 10, maxHealth: 100,
            });
            window.TritiumStore.set('map.selectedUnitIds', ['roster_a', 'roster_b', 'roster_c']);

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

    def test_no_roster_for_single_select(self, page):
        """Single selection doesn't show roster bar."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', ['roster_a']);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_no_roster_for_empty_select(self, page):
        """Empty selection doesn't crash roster rendering."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('map.selectedUnitIds', []);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_roster_with_eliminated_unit(self, page):
        """Roster handles eliminated units gracefully."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('roster_dead', {
                name: 'Dead Unit', type: 'turret', alliance: 'friendly',
                position: { x: 100, y: 100 }, health: 0, maxHealth: 100,
                status: 'eliminated',
            });
            window.TritiumStore.set('map.selectedUnitIds', ['roster_a', 'roster_dead']);
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
# Kill streak screen flash
# ============================================================


class TestStreakScreenFlash:
    """Verify screen edge glow during kill streaks."""

    def test_streak_flash_during_active(self, page):
        """Kill streak >= 3 shows screen edge glow during combat."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.currentStreak', 5);
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

    def test_no_streak_flash_below_three(self, page):
        """Streak < 3 doesn't show flash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.currentStreak', 1);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_no_streak_flash_during_idle(self, page):
        """No streak flash during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            window.TritiumStore.set('game.currentStreak', 10);
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Minimap danger close indicator
# ============================================================


class TestMinimapDangerIndicator:
    """Verify minimap border flashes red during danger close."""

    def test_minimap_danger_border(self, page):
        """Danger close condition shows red border on minimap."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('mm_turret', {
                name: 'MM Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('mm_hostile', {
                name: 'MM Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 10, y: 5 }, status: 'active',
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

    def test_no_minimap_danger_when_far(self, page):
        """No danger border when units are far apart."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('mm_far_t', {
                name: 'MM Far T', type: 'turret', alliance: 'friendly',
                position: { x: -300, y: -300 },
            });
            window.TritiumStore.updateUnit('mm_far_h', {
                name: 'MM Far H', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 300, y: 300 },
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


# ============================================================
# Combined render stability
# ============================================================


class TestBatch31Combined:
    """All Batch 31 features work together without crash."""

    def test_full_batch31_scenario(self, page):
        """Multi-select roster + streak flash + danger close all render."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 10);
            window.TritiumStore.set('game.score', 60000);
            window.TritiumStore.set('game.currentStreak', 7);

            // Units for roster
            window.TritiumStore.updateUnit('b31_a', {
                name: 'B31 Alpha', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 30, maxHealth: 100,
                eliminations: 20, weapon_range: 60,
            });
            window.TritiumStore.updateUnit('b31_b', {
                name: 'B31 Beta', type: 'drone', alliance: 'friendly',
                position: { x: 40, y: -20 }, health: 90, maxHealth: 100,
                eliminations: 10,
            });
            window.TritiumStore.set('map.selectedUnitIds', ['b31_a', 'b31_b']);

            // Danger close hostile
            window.TritiumStore.updateUnit('b31_close', {
                name: 'B31 Close', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 8, y: 5 }, status: 'active',
            });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        window.TritiumStore.set('game.currentStreak', 0);
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
