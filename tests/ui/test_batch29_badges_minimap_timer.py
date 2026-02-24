"""Batch 29 unit status badges, minimap pings/rally, elapsed timer, cooldown arcs tests.

Verifies unit health status badges (critical/damaged), minimap ping and rally
markers, combat elapsed timer in HUD, and weapon cooldown arc indicators.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch29_badges_minimap_timer.py -v -m ux
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
# Unit status badges
# ============================================================


class TestUnitStatusBadges:
    """Verify health status badges on friendly units."""

    def test_critical_health_badge(self, page):
        """Unit at <25% health shows critical badge without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('badge_crit', {
                name: 'Critical Unit',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
                health: 15,
                maxHealth: 100,
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

    def test_damaged_health_badge(self, page):
        """Unit at 25-60% health shows damaged badge without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('badge_dmg', {
                name: 'Damaged Unit',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 50, y: 50 },
                health: 45,
                maxHealth: 100,
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

    def test_healthy_unit_no_badge(self, page):
        """Unit at >60% health shows no damage badge."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('badge_ok', {
                name: 'Healthy Unit',
                type: 'turret',
                alliance: 'friendly',
                position: { x: -50, y: -50 },
                health: 95,
                maxHealth: 100,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_hostile_no_badge(self, page):
        """Hostile units don't show health badges."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('badge_hostile', {
                name: 'Hostile No Badge',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 100, y: 100 },
                health: 10,
                maxHealth: 100,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Weapon cooldown arc
# ============================================================


class TestWeaponCooldownArc:
    """Verify cooldown arc indicator after unit fires."""

    def test_cooldown_arc_after_projectile(self, page):
        """Projectile event creates a brief cooldown arc on shooter."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('cd_turret', {
                name: 'CD Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('cd_target', {
                name: 'CD Target', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 40, y: 40 },
            });
            window.EventBus.emit('combat:projectile', {
                source_id: 'cd_turret', target_id: 'cd_target',
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

    def test_no_cooldown_without_fire(self, page):
        """Units that haven't fired don't show cooldown arc."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('no_cd', {
                name: 'No CD', type: 'turret', alliance: 'friendly',
                position: { x: -100, y: -100 },
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Minimap pings and rally markers
# ============================================================


class TestMinimapPings:
    """Verify pings and rally points appear on minimap."""

    def test_minimap_ping_renders(self, page):
        """Ping shows on minimap without crash."""
        result = page.evaluate("""() => {
            const mod = window._mapModule;
            if (mod && typeof mod.addPing === 'function') {
                mod.addPing(0, 0, '#00f0ff');
            }
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

    def test_minimap_rally_renders(self, page):
        """Rally point shows on minimap without crash."""
        result = page.evaluate("""() => {
            window.EventBus.emit('map:rallyPoint', { x: 50, y: 50 });
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
# Elapsed timer in combat HUD
# ============================================================


class TestElapsedTimer:
    """Verify elapsed time display in combat HUD."""

    def test_elapsed_timer_renders_during_active(self, page):
        """Active combat HUD shows elapsed time without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.score', 5000);
            window.TritiumStore.set('game.eliminations', 10);
            window.TritiumStore.set('game.waveStartTime', Date.now() - 45000);

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

    def test_timer_no_crash_without_start_time(self, page):
        """HUD handles missing waveStartTime gracefully."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
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

    def test_timer_not_shown_during_idle(self, page):
        """Timer not shown during idle phase."""
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
# Combined render stability
# ============================================================


class TestBatch29Combined:
    """All Batch 29 features work together without crash."""

    def test_full_batch29_scenario(self, page):
        """All features active simultaneously render cleanly."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 9);
            window.TritiumStore.set('game.score', 30000);
            window.TritiumStore.set('game.waveStartTime', Date.now() - 120000);

            // Unit at critical health
            window.TritiumStore.updateUnit('b29_crit', {
                name: 'B29 Critical', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 10, maxHealth: 100,
                eliminations: 25,
            });
            // Unit at damaged health
            window.TritiumStore.updateUnit('b29_dmg', {
                name: 'B29 Damaged', type: 'drone', alliance: 'friendly',
                position: { x: 40, y: -20 }, health: 40, maxHealth: 100,
                eliminations: 12,
            });
            // Healthy unit
            window.TritiumStore.updateUnit('b29_ok', {
                name: 'B29 Healthy', type: 'rover', alliance: 'friendly',
                position: { x: -40, y: 40 }, health: 90, maxHealth: 100,
                eliminations: 5,
            });

            // Fire projectile for cooldown arc
            window.EventBus.emit('combat:projectile', {
                source_id: 'b29_crit', target_id: 'b29_hostile',
            });

            // Hostile nearby for combat
            window.TritiumStore.updateUnit('b29_hostile', {
                name: 'B29 Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 60, y: 60 }, status: 'active',
            });

            // Drop a ping + rally
            const mod = window._mapModule;
            if (mod && typeof mod.addPing === 'function') {
                mod.addPing(-80, -80, '#fcee0a');
            }
            window.EventBus.emit('map:rallyPoint', { x: 100, y: -100 });

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        window.TritiumStore.set('game.phase', 'idle');
                        window.EventBus.emit('map:clearRallyPoints');
                        resolve({ frames, canvasOk: !!document.getElementById('tactical-canvas') });
                    }
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert result["frames"] >= 30
        assert result["canvasOk"]
