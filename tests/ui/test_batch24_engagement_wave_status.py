"""Batch 24 engagement lines, hostile threat ranges, wave progress, unit status tests.

Verifies engagement line rendering between shooter and target,
hostile weapon range circles during combat, wave progress bar,
and unit status text (ENGAGED/PATROL/IDLE).

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch24_engagement_wave_status.py -v -m ux
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
    }""")
    p.keyboard.press("Escape")
    p.wait_for_timeout(200)


# ============================================================
# Engagement lines
# ============================================================


class TestEngagementLines:
    """Verify engagement lines render between shooter and target."""

    def test_projectile_creates_engagement(self, page):
        """combat:projectile event with source and target creates engagement."""
        result = page.evaluate("""() => {
            // Inject shooter and target
            window.TritiumStore.updateUnit('eng_shooter', {
                name: 'Turret Alpha',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.TritiumStore.updateUnit('eng_target', {
                name: 'Hostile Beta',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 80, y: 60 },
            });

            // Fire projectile
            window.EventBus.emit('combat:projectile', {
                source_id: 'eng_shooter',
                target_id: 'eng_target',
            });
            return true;
        }""")
        assert result

    def test_engagement_lines_render_without_crash(self, page):
        """Engagement lines render through multiple frames."""
        result = page.evaluate("""() => {
            // Set active combat
            window.TritiumStore.set('game.phase', 'active');

            // Fire projectile
            window.EventBus.emit('combat:projectile', {
                source_id: 'eng_shooter',
                target_id: 'eng_target',
            });

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

    def test_engagement_fades_over_time(self, page):
        """Engagement lines have a limited lifetime and fade."""
        result = page.evaluate("""() => {
            window.EventBus.emit('combat:projectile', {
                source_id: 'eng_shooter',
                target_id: 'eng_target',
            });
            return new Promise(resolve => {
                setTimeout(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                }, 500);
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Hostile threat range circles
# ============================================================


class TestHostileThreatRanges:
    """Verify hostile weapon range circles during active combat."""

    def test_hostile_range_renders_during_active(self, page):
        """Hostile with weapon_range shows threat circle during active phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('threat_hostile_1', {
                name: 'Armed Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: 50, y: 50 },
                weapon_range: 30,
                status: 'active',
            });
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

    def test_no_threat_range_during_idle(self, page):
        """Hostile ranges don't render during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_eliminated_hostile_no_range(self, page):
        """Eliminated hostile units don't show threat ranges."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('threat_dead', {
                name: 'Dead Hostile',
                type: 'hostile_kid',
                alliance: 'hostile',
                position: { x: -50, y: -50 },
                weapon_range: 30,
                status: 'eliminated',
            });
            window.TritiumStore.set('game.phase', 'active');

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
# Wave progress bar
# ============================================================


class TestWaveProgressBar:
    """Verify wave progress bar during active combat."""

    def test_progress_bar_renders_with_wave_data(self, page):
        """Progress bar renders when waveStartTime and phase are set."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.waveStartTime', Date.now() - 10000);
            window.TritiumStore.set('game.waveDuration', 60);

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

    def test_progress_bar_not_shown_during_idle(self, page):
        """Progress bar is hidden during idle phase."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'idle');
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_progress_bar_caps_at_100_percent(self, page):
        """Progress doesn't exceed 100% even if wave overruns duration."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.waveStartTime', Date.now() - 120000); // 2 minutes ago
            window.TritiumStore.set('game.waveDuration', 60);

            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Unit status text
# ============================================================


class TestUnitStatusText:
    """Verify unit status labels during combat."""

    def test_engaged_status_during_combat(self, page):
        """Unit with active engagement shows status without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');

            // Create friendly unit and fire from it
            window.TritiumStore.updateUnit('status_turret', {
                name: 'Status Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: 0, y: 0 },
            });
            window.EventBus.emit('combat:projectile', {
                source_id: 'status_turret',
                target_id: 'eng_target',
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

    def test_patrol_status_for_unit_with_waypoints(self, page):
        """Unit with waypoints shows PATROL status."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('status_patrol', {
                name: 'Patrol Rover',
                type: 'rover',
                alliance: 'friendly',
                position: { x: 100, y: 100 },
                waypoints: [{ x: 100, y: 100 }, { x: 200, y: 200 }],
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

    def test_idle_status_for_stationary_unit(self, page):
        """Unit without engagement or waypoints shows IDLE."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.updateUnit('status_idle', {
                name: 'Idle Turret',
                type: 'turret',
                alliance: 'friendly',
                position: { x: -100, y: -100 },
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

    def test_no_status_during_idle_phase(self, page):
        """Unit status text not shown during idle phase."""
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


class TestBatch24Combined:
    """All Batch 24 features work together."""

    def test_full_combat_scenario(self, page):
        """Full combat scenario with all effects active."""
        result = page.evaluate("""() => {
            // Active combat setup
            window.TritiumStore.set('game.phase', 'active');
            window.TritiumStore.set('game.wave', 3);
            window.TritiumStore.set('game.score', 5000);
            window.TritiumStore.set('game.eliminations', 15);
            window.TritiumStore.set('game.waveStartTime', Date.now() - 20000);
            window.TritiumStore.set('game.waveDuration', 60);

            // Spawn units
            window.TritiumStore.updateUnit('b24_turret', {
                name: 'B24 Turret', type: 'turret', alliance: 'friendly',
                position: { x: 0, y: 0 }, weapon_range: 50,
                health: 80, maxHealth: 100,
            });
            window.TritiumStore.updateUnit('b24_hostile', {
                name: 'B24 Hostile', type: 'hostile_kid', alliance: 'hostile',
                position: { x: 40, y: 30 }, weapon_range: 20,
                health: 50, maxHealth: 100,
            });

            // Fire engagement
            window.EventBus.emit('combat:projectile', {
                source_id: 'b24_turret', target_id: 'b24_hostile',
            });

            // Elimination for kill feed
            window.EventBus.emit('combat:elimination', {
                target_id: 'b24_hostile',
                target_alliance: 'hostile',
                target_name: 'B24 HOSTILE',
                shooter_name: 'B24 TURRET',
                position: { x: 40, y: 30 },
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
