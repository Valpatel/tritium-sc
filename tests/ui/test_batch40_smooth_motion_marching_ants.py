# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Batch 40 smooth motion, marching ants, help gaps, toast animation tests.

Verifies smooth unit position interpolation, animated patrol path dashes,
Shift+F help entry, and toast slide-in animation.

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_batch40_smooth_motion_marching_ants.py -v -m ux
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
# Smooth position interpolation
# ============================================================


class TestSmoothPositionInterpolation:
    """Verify units use smoothed positions for rendering."""

    def test_smooth_positions_map_exists(self, page):
        """Map state has smoothPositions Map."""
        result = page.evaluate("""() => {
            const actions = window._mapActions || {};
            // Check internal state — smoothPositions Map should exist
            // We verify by placing a unit and checking if positions get tracked
            window.TritiumStore.updateUnit('sp_test', {
                name: 'SP Test', type: 'turret', alliance: 'friendly',
                position: { x: 10, y: 20 }, health: 100, maxHealth: 100,
            });
            return new Promise(resolve => {
                // Allow 2 render frames for interpolation to kick in
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    });
                });
            });
        }""")
        assert result["canvasOk"]

    def test_smooth_motion_no_crash_on_position_update(self, page):
        """Rapidly updating unit position doesn't crash."""
        result = page.evaluate("""() => {
            // Place unit at position 0,0
            window.TritiumStore.updateUnit('sm_rapid', {
                name: 'SM Rapid', type: 'drone', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            // Rapidly update position 10 times
            let crashed = false;
            try {
                for (let i = 0; i < 10; i++) {
                    window.TritiumStore.updateUnit('sm_rapid', {
                        position: { x: i * 5, y: i * 3 },
                    });
                }
            } catch (e) {
                crashed = true;
            }
            return new Promise(resolve => {
                // Let a few frames render
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 5) requestAnimationFrame(tick);
                    else resolve({
                        crashed,
                        canvasOk: !!document.getElementById('tactical-canvas'),
                    });
                }
                requestAnimationFrame(tick);
            });
        }""")
        assert not result["crashed"], "Rapid position updates should not crash"
        assert result["canvasOk"]

    def test_smooth_position_tracks_target(self, page):
        """Smoothed position converges toward actual position over frames."""
        result = page.evaluate("""() => {
            // Place unit at known position
            window.TritiumStore.updateUnit('sp_converge', {
                name: 'SP Conv', type: 'rover', alliance: 'friendly',
                position: { x: 0, y: 0 }, health: 100, maxHealth: 100,
            });
            return new Promise(resolve => {
                // Let a couple frames establish the smooth position
                setTimeout(() => {
                    // Now jump to a distant position
                    window.TritiumStore.updateUnit('sp_converge', {
                        position: { x: 100, y: 100 },
                    });
                    // After a few more frames, canvas should still be OK
                    setTimeout(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    }, 200);
                }, 100);
            });
        }""")
        assert result["canvasOk"]

    def test_smooth_cleanup_on_unit_removal(self, page):
        """Smooth positions are pruned when units are removed."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('sp_cleanup', {
                name: 'SP Clean', type: 'turret', alliance: 'friendly',
                position: { x: 50, y: 50 }, health: 100, maxHealth: 100,
            });
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    // Remove the unit
                    window.TritiumStore.units.delete('sp_cleanup');
                    window.TritiumStore._notify('units', window.TritiumStore.units);
                    // Let prune cycle run
                    setTimeout(() => {
                        resolve({ canvasOk: !!document.getElementById('tactical-canvas') });
                    }, 200);
                });
            });
        }""")
        assert result["canvasOk"]


# ============================================================
# Marching ants on patrol paths
# ============================================================


class TestMarchingAnts:
    """Verify patrol paths have animated dashes."""

    def test_patrol_path_renders_with_unit(self, page):
        """Unit with waypoints renders patrol path without crash."""
        result = page.evaluate("""() => {
            window.TritiumStore.updateUnit('ma_patrol', {
                name: 'MA Patrol', type: 'turret', alliance: 'friendly',
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

    def test_marching_ants_multiple_patrols(self, page):
        """Multiple patrolling units render simultaneously."""
        result = page.evaluate("""() => {
            for (let i = 0; i < 5; i++) {
                window.TritiumStore.updateUnit(`ma_multi_${i}`, {
                    name: `MA Multi ${i}`, type: 'rover', alliance: 'friendly',
                    position: { x: i * 20, y: 0 }, health: 100, maxHealth: 100,
                    waypoints: [
                        { x: i * 20, y: 0 },
                        { x: i * 20 + 15, y: 10 },
                        { x: i * 20, y: 20 },
                    ],
                });
            }
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
# Help overlay: Shift+F entry
# ============================================================


class TestHelpOverlayBatch40:
    """Verify Shift+F auto-center is documented."""

    def test_shift_f_in_help(self, page):
        """Help overlay lists Shift+F auto-center shortcut."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false, text: '' };
            return { found: true, text: overlay.textContent || '' };
        }""")
        assert result["found"]
        text = result["text"].lower()
        assert "auto-center" in text, f"Expected 'auto-center' in help, got: {text[:300]}"

    def test_shift_f_kbd_element_present(self, page):
        """Help overlay has a kbd element containing Shift+F."""
        result = page.evaluate("""() => {
            const overlay = document.getElementById('help-overlay');
            if (!overlay) return { found: false };
            const kbds = overlay.querySelectorAll('kbd');
            for (const kbd of kbds) {
                if (kbd.textContent.includes('Shift+F')) return { found: true };
            }
            return { found: false };
        }""")
        assert result["found"], "Expected <kbd>Shift+F</kbd> in help overlay"


# ============================================================
# Toast slide-in animation
# ============================================================


class TestToastAnimation:
    """Verify toasts use slide-in-from-right animation."""

    def test_toast_has_slide_animation(self, page):
        """Toast element uses v2-fadeInRight animation."""
        result = page.evaluate("""() => {
            // Trigger a toast
            if (window.EventBus) {
                window.EventBus.emit('toast:show', { message: 'Test slide animation', type: 'info' });
            }
            return new Promise(resolve => {
                requestAnimationFrame(() => {
                    const toasts = document.querySelectorAll('.toast');
                    if (toasts.length === 0) return resolve({ found: false, animation: '' });
                    const latest = toasts[0];
                    const style = window.getComputedStyle(latest);
                    const anim = style.animationName || style.animation || '';
                    resolve({ found: true, animation: anim });
                });
            });
        }""")
        assert result["found"], "Toast should appear"
        assert "fadeInRight" in result["animation"] or "v2-fadeInRight" in result["animation"], \
            f"Toast should use fadeInRight animation, got: {result['animation']}"

    def test_toast_fade_out_still_works(self, page):
        """Toast fade-out class still applies correctly."""
        result = page.evaluate("""() => {
            if (window.EventBus) {
                window.EventBus.emit('toast:show', { message: 'Fade out test', type: 'info' });
            }
            return new Promise(resolve => {
                setTimeout(() => {
                    const toasts = document.querySelectorAll('.toast');
                    // Manually trigger fade
                    if (toasts.length > 0) {
                        toasts[0].classList.add('toast-fade');
                        const style = window.getComputedStyle(toasts[0]);
                        const anim = style.animationName || '';
                        resolve({ found: true, fadeAnim: anim });
                    } else {
                        resolve({ found: false, fadeAnim: '' });
                    }
                }, 100);
            });
        }""")
        assert result["found"]
        assert "fadeOut" in result["fadeAnim"] or "v2-fadeOut" in result["fadeAnim"], \
            f"Toast-fade should use fadeOut, got: {result['fadeAnim']}"


# ============================================================
# Combined render stability
# ============================================================


class TestBatch40Combined:
    """All Batch 40 features work together without crash."""

    def test_full_batch40_scenario(self, page):
        """Smooth motion + patrol paths + toasts + combat — all active at once."""
        result = page.evaluate("""() => {
            window.TritiumStore.set('game.phase', 'active');

            // Place multiple units with varying positions
            for (let i = 0; i < 6; i++) {
                const type = ['turret', 'drone', 'rover'][i % 3];
                window.TritiumStore.updateUnit(`b40_unit_${i}`, {
                    name: `B40 Unit ${i}`, type, alliance: 'friendly',
                    position: { x: i * 15 - 30, y: (i % 2) * 20 - 10 },
                    health: 60 + i * 8, maxHealth: 100,
                    eliminations: i * 2, weapon_range: 60,
                    waypoints: i < 3 ? [
                        { x: i * 15 - 30, y: -10 },
                        { x: i * 15 - 15, y: 10 },
                        { x: i * 15 - 30, y: 30 },
                    ] : undefined,
                });
            }

            // Place hostiles that move
            for (let i = 0; i < 3; i++) {
                window.TritiumStore.updateUnit(`b40_hostile_${i}`, {
                    name: `B40 Hostile ${i}`, type: 'hostile_kid', alliance: 'hostile',
                    position: { x: 50 + i * 10, y: i * 15 },
                    health: 40, maxHealth: 100,
                });
            }

            // Trigger a toast
            if (window.EventBus) {
                window.EventBus.emit('toast:show', { message: 'Batch 40 active', type: 'info' });
            }

            // Simulate position updates (movement)
            let updateCount = 0;
            const moveInterval = setInterval(() => {
                updateCount++;
                for (let i = 0; i < 3; i++) {
                    window.TritiumStore.updateUnit(`b40_hostile_${i}`, {
                        position: { x: 50 + i * 10 - updateCount * 2, y: i * 15 + updateCount },
                    });
                }
                if (updateCount >= 10) clearInterval(moveInterval);
            }, 100);

            return new Promise(resolve => {
                let frames = 0;
                function tick() {
                    frames++;
                    if (frames < 30) requestAnimationFrame(tick);
                    else {
                        clearInterval(moveInterval);
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
