"""Panel defect detection tests for the Command Center.

These tests exercise KNOWN DEFECTS in the panel management system.
They are designed to FAIL when the defects exist and PASS when fixed.

Current known defects:
1. Non-Amy panels may be blocked from reaching the top region of the game area
2. Resizing Amy panel causes other panels to reposition (cascade)
3. UI elements overlap in the bottom-left corner (map coords, status bar, Amy panel)
4. Panels can overlap each other with no awareness

Usage:
    .venv/bin/python3 -m pytest tests/ui/test_panel_defects.py -v -m ux
"""

from __future__ import annotations

import pytest
from tests.ui.conftest import assert_panel_visible

pytestmark = [pytest.mark.ux, pytest.mark.ui, pytest.mark.defect]

PANELS = [
    ('1', 'amy'),
    ('2', 'units'),
    ('3', 'alerts'),
    ('4', 'game'),
    ('5', 'mesh'),
]


# ---------------------------------------------------------------------------
# Helpers — purely mouse-driven, no JS setPosition() bypass
# ---------------------------------------------------------------------------

def _close_all_panels(page):
    """Close all open panels using keyboard toggles."""
    page.keyboard.press('Escape')
    page.wait_for_timeout(200)
    for key, pid in PANELS:
        panel = page.locator(f'[data-panel-id="{pid}"]')
        if panel.count() > 0 and panel.is_visible():
            page.keyboard.press(key)
            page.wait_for_timeout(300)


def _open_panel(page, key, panel_id):
    """Open a panel via keyboard shortcut. Does NOT close others."""
    panel = page.locator(f'[data-panel-id="{panel_id}"]')
    if panel.count() == 0 or not panel.is_visible():
        page.keyboard.press(key)
        page.wait_for_timeout(500)
    assert_panel_visible(page, panel_id)


def _get_container_bounds(page):
    """Get the panel container's bounding rect in viewport coordinates."""
    return page.evaluate("""() => {
        const c = document.getElementById('panel-container');
        if (!c) return null;
        const r = c.getBoundingClientRect();
        return { x: r.x, y: r.y, w: r.width, h: r.height,
                 bottom: r.y + r.height };
    }""")


def _get_panel_container_y(page, panel_id):
    """Get a panel's y coordinate in container-relative coords via JS."""
    return page.evaluate("""(pid) => {
        const panel = window.panelManager && window.panelManager.getPanel(pid);
        return panel ? panel.y : null;
    }""", panel_id)


def _drag_panel_to(page, panel_id, target_vp_x, target_vp_y):
    """Drag a panel by its header to a target viewport position.

    Uses realistic mouse movements (mousedown, move in steps, mouseup).
    Does NOT use setPosition — this tests the actual drag handler.
    """
    header = page.locator(f'[data-panel-id="{panel_id}"] [data-drag-handle]')
    hdr_box = header.bounding_box()
    if hdr_box is None:
        return False

    start_x = hdr_box['x'] + hdr_box['width'] / 2
    start_y = hdr_box['y'] + hdr_box['height'] / 2

    # Realistic drag: move to start, press, move in steps, release
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(target_vp_x, target_vp_y, steps=25)
    page.mouse.up()
    page.wait_for_timeout(400)
    return True


# ===========================================================================
# TEST 1: Panel Top Region Access
# ===========================================================================

class TestPanelTopRegionAccess:
    """DEFECT: Non-Amy panels may not reach the top of the game area.

    All panels should be draggable to container y=0 (top of game area,
    just below the command bar). This test opens panels at their DEFAULT
    positions and drags them to the very top using only mouse operations.
    No JS setPosition() is used — this tests the real drag path.
    """

    @pytest.mark.parametrize("key,panel_id", [
        ('2', 'units'),
        ('3', 'alerts'),
        ('4', 'game'),
        ('5', 'mesh'),
    ])
    def test_drag_to_top_with_amy_open(self, page, take_screenshot, key, panel_id):
        """With Amy open, drag {panel_id} to the very top of the game area."""
        _close_all_panels(page)

        # Open Amy first (bottom-left default)
        _open_panel(page, '1', 'amy')

        # Open the target panel at its default position
        _open_panel(page, key, panel_id)

        # Get container bounds
        container = _get_container_bounds(page)
        assert container is not None, "Panel container not found"

        # Target: very top of the game area (container y=0 in viewport coords)
        target_y = container['y'] + 14  # 14px = half the header height
        target_x = 400  # arbitrary x, away from Amy

        # Drag the panel to the top
        _drag_panel_to(page, panel_id, target_x, target_y)

        take_screenshot(page, f'defect-top-{panel_id}-with-amy')

        # Check: panel should be within 10px of container top
        box = page.locator(f'[data-panel-id="{panel_id}"]').bounding_box()
        assert box is not None, f"Panel '{panel_id}' should have a bounding box"

        distance_from_top = box['y'] - container['y']
        assert distance_from_top < 10, (
            f"Panel '{panel_id}' should reach the top of the game area. "
            f"Container top: {container['y']:.0f}, panel top: {box['y']:.0f}, "
            f"distance: {distance_from_top:.0f}px (max 10px allowed)"
        )

        # Also verify container-relative y coordinate
        panel_y = _get_panel_container_y(page, panel_id)
        assert panel_y is not None and panel_y < 10, (
            f"Panel '{panel_id}' container y should be < 10, got {panel_y}"
        )

    @pytest.mark.parametrize("key,panel_id", [
        ('2', 'units'),
        ('3', 'alerts'),
    ])
    def test_drag_to_top_with_all_panels_open(self, page, take_screenshot, key, panel_id):
        """With ALL 5 panels open, drag {panel_id} to the top of the game area."""
        _close_all_panels(page)

        # Open all 5 panels (realistic multi-panel scenario)
        for k, pid in PANELS:
            _open_panel(page, k, pid)

        container = _get_container_bounds(page)
        assert container is not None

        # Target the top of the game area
        target_y = container['y'] + 14
        target_x = 500  # middle area, avoid panel stack on the left

        _drag_panel_to(page, panel_id, target_x, target_y)

        take_screenshot(page, f'defect-top-all-{panel_id}')

        box = page.locator(f'[data-panel-id="{panel_id}"]').bounding_box()
        assert box is not None

        distance_from_top = box['y'] - container['y']
        assert distance_from_top < 10, (
            f"Panel '{panel_id}' blocked from top with all panels open. "
            f"Container top: {container['y']:.0f}, panel top: {box['y']:.0f}, "
            f"distance: {distance_from_top:.0f}px"
        )

    def test_drag_units_up_down_up(self, page, take_screenshot):
        """Drag Units down to center, then back up. Should reach the top both times."""
        _close_all_panels(page)
        _open_panel(page, '1', 'amy')
        _open_panel(page, '2', 'units')

        container = _get_container_bounds(page)
        assert container is not None

        center_y = container['y'] + container['h'] / 2

        # 1) Drag Units DOWN to center
        _drag_panel_to(page, 'units', 400, center_y)
        mid_box = page.locator('[data-panel-id="units"]').bounding_box()
        assert mid_box is not None
        assert mid_box['y'] > container['y'] + 100, (
            "Units should be dragged to center area"
        )
        take_screenshot(page, 'defect-units-at-center')

        # 2) Drag Units back UP to top
        _drag_panel_to(page, 'units', 400, container['y'] + 14)
        top_box = page.locator('[data-panel-id="units"]').bounding_box()
        assert top_box is not None

        distance_from_top = top_box['y'] - container['y']
        take_screenshot(page, 'defect-units-back-to-top')

        assert distance_from_top < 10, (
            f"Units should return to the top after down-up drag. "
            f"Got distance: {distance_from_top:.0f}px from top"
        )


# ===========================================================================
# TEST 2: Resize Cascade (resizing one panel moves others)
# ===========================================================================

class TestResizeDoesNotMoveOtherPanels:
    """DEFECT: Resizing Amy panel causes other panels to reposition.

    When user resizes panel A, panels B/C/D should NOT move. Each panel's
    position should be independent of other panels' sizes.
    """

    def test_resize_amy_does_not_move_units(self, page, take_screenshot):
        """Resizing the Amy panel should not change the Units panel position."""
        _close_all_panels(page)

        # Open Amy, then Units — use JS positioning to get known starting points
        # (We need deterministic starting positions for this test)
        _open_panel(page, '1', 'amy')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('amy');
            if (p) { p.setPosition(50, 300); p.setSize(300, 200); }
        }""")
        page.wait_for_timeout(200)

        _open_panel(page, '2', 'units')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('units');
            if (p) { p.setPosition(400, 100); p.setSize(260, 300); }
        }""")
        page.wait_for_timeout(200)

        # Record Units position BEFORE resize
        units_loc = page.locator('[data-panel-id="units"]')
        units_before = units_loc.bounding_box()
        assert units_before is not None

        take_screenshot(page, 'defect-resize-before')

        # Resize Amy by dragging resize handle
        amy_resize = page.locator('[data-panel-id="amy"] [data-resize-handle]')
        rh = amy_resize.bounding_box()
        if rh is not None:
            page.mouse.move(rh['x'] + 5, rh['y'] + 5)
            page.mouse.down()
            page.mouse.move(rh['x'] + 200, rh['y'] + 150, steps=10)
            page.mouse.up()
            page.wait_for_timeout(500)

        take_screenshot(page, 'defect-resize-after')

        # Check: Units should NOT have moved
        units_after = units_loc.bounding_box()
        assert units_after is not None

        dx = abs(units_after['x'] - units_before['x'])
        dy = abs(units_after['y'] - units_before['y'])
        assert dx < 5 and dy < 5, (
            f"Units panel moved after Amy resize! "
            f"Before: ({units_before['x']:.0f}, {units_before['y']:.0f}), "
            f"After: ({units_after['x']:.0f}, {units_after['y']:.0f}), "
            f"Delta: ({dx:.0f}, {dy:.0f})"
        )

    def test_resize_amy_does_not_move_alerts(self, page, take_screenshot):
        """Resizing the Amy panel should not change the Alerts panel position."""
        _close_all_panels(page)

        _open_panel(page, '1', 'amy')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('amy');
            if (p) { p.setPosition(50, 300); p.setSize(300, 200); }
        }""")
        page.wait_for_timeout(200)

        _open_panel(page, '3', 'alerts')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('alerts');
            if (p) { p.setPosition(500, 200); p.setSize(280, 300); }
        }""")
        page.wait_for_timeout(200)

        alerts_loc = page.locator('[data-panel-id="alerts"]')
        alerts_before = alerts_loc.bounding_box()
        assert alerts_before is not None

        # Resize Amy
        amy_resize = page.locator('[data-panel-id="amy"] [data-resize-handle]')
        rh = amy_resize.bounding_box()
        if rh is not None:
            page.mouse.move(rh['x'] + 5, rh['y'] + 5)
            page.mouse.down()
            page.mouse.move(rh['x'] + 200, rh['y'] + 150, steps=10)
            page.mouse.up()
            page.wait_for_timeout(500)

        alerts_after = alerts_loc.bounding_box()
        assert alerts_after is not None

        dx = abs(alerts_after['x'] - alerts_before['x'])
        dy = abs(alerts_after['y'] - alerts_before['y'])
        assert dx < 5 and dy < 5, (
            f"Alerts panel moved after Amy resize! "
            f"Before: ({alerts_before['x']:.0f}, {alerts_before['y']:.0f}), "
            f"After: ({alerts_after['x']:.0f}, {alerts_after['y']:.0f}), "
            f"Delta: ({dx:.0f}, {dy:.0f})"
        )

    def test_resize_units_does_not_move_amy(self, page, take_screenshot):
        """Resizing the Units panel should not move the Amy panel."""
        _close_all_panels(page)

        _open_panel(page, '1', 'amy')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('amy');
            if (p) { p.setPosition(50, 600); p.setSize(300, 200); }
        }""")
        page.wait_for_timeout(200)

        _open_panel(page, '2', 'units')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('units');
            if (p) { p.setPosition(50, 50); p.setSize(260, 200); }
        }""")
        page.wait_for_timeout(200)

        amy_loc = page.locator('[data-panel-id="amy"]')
        amy_before = amy_loc.bounding_box()
        assert amy_before is not None

        # Resize Units downward (toward Amy)
        units_resize = page.locator('[data-panel-id="units"] [data-resize-handle]')
        rh = units_resize.bounding_box()
        if rh is not None:
            page.mouse.move(rh['x'] + 5, rh['y'] + 5)
            page.mouse.down()
            page.mouse.move(rh['x'] + 100, rh['y'] + 300, steps=15)
            page.mouse.up()
            page.wait_for_timeout(500)

        take_screenshot(page, 'defect-resize-units-over-amy')

        amy_after = amy_loc.bounding_box()
        assert amy_after is not None

        dx = abs(amy_after['x'] - amy_before['x'])
        dy = abs(amy_after['y'] - amy_before['y'])
        assert dx < 5 and dy < 5, (
            f"Amy panel moved after Units resize! "
            f"Before: ({amy_before['x']:.0f}, {amy_before['y']:.0f}), "
            f"After: ({amy_after['x']:.0f}, {amy_after['y']:.0f}), "
            f"Delta: ({dx:.0f}, {dy:.0f})"
        )


# ===========================================================================
# TEST 3: Bottom-Left Element Overlap
# ===========================================================================

class TestBottomLeftOverlap:
    """DEFECT: UI elements overlap in the bottom-left corner.

    The map coordinates display (X/Y), status bar items, and the Amy panel
    can all crowd the bottom-left region, causing text to overlap.
    """

    def test_amy_default_does_not_overlap_map_coords(self, page, take_screenshot):
        """Amy panel at default position should not overlap the map coords display."""
        _close_all_panels(page)
        _open_panel(page, '1', 'amy')
        page.wait_for_timeout(500)

        take_screenshot(page, 'defect-amy-vs-coords')

        amy_loc = page.locator('[data-panel-id="amy"]')
        coords_loc = page.locator('#map-coords')

        amy_box = amy_loc.bounding_box()
        coords_box = coords_loc.bounding_box()

        if amy_box is None or coords_box is None:
            pytest.skip("Could not get bounding boxes for Amy/coords")

        # Check overlap
        h_overlap = amy_box['x'] < coords_box['x'] + coords_box['width'] and \
                    amy_box['x'] + amy_box['width'] > coords_box['x']
        v_overlap = amy_box['y'] < coords_box['y'] + coords_box['height'] and \
                    amy_box['y'] + amy_box['height'] > coords_box['y']

        assert not (h_overlap and v_overlap), (
            f"Amy panel overlaps map coordinates display! "
            f"Amy: ({amy_box['x']:.0f},{amy_box['y']:.0f}) "
            f"{amy_box['width']:.0f}x{amy_box['height']:.0f}, "
            f"Coords: ({coords_box['x']:.0f},{coords_box['y']:.0f}) "
            f"{coords_box['width']:.0f}x{coords_box['height']:.0f}"
        )

    def test_no_status_bar_overlap_with_map_coords(self, page, take_screenshot):
        """Status bar and map coords display should not overlap."""
        take_screenshot(page, 'defect-bottom-left-overlap')

        status_bar = page.locator('#status-bar')
        map_coords = page.locator('#map-coords')

        if status_bar.count() == 0 or map_coords.count() == 0:
            pytest.skip("Status bar or map coords element not found")

        sb_box = status_bar.bounding_box()
        mc_box = map_coords.bounding_box()

        if sb_box is None or mc_box is None:
            pytest.skip("Could not get bounding boxes")

        h_overlap = sb_box['x'] < mc_box['x'] + mc_box['width'] and \
                    sb_box['x'] + sb_box['width'] > mc_box['x']
        v_overlap = sb_box['y'] < mc_box['y'] + mc_box['height'] and \
                    sb_box['y'] + sb_box['height'] > mc_box['y']

        assert not (h_overlap and v_overlap), (
            f"Status bar and map coords overlap! "
            f"Status bar: ({sb_box['x']:.0f},{sb_box['y']:.0f})-"
            f"({sb_box['x'] + sb_box['width']:.0f},{sb_box['y'] + sb_box['height']:.0f}), "
            f"Map coords: ({mc_box['x']:.0f},{mc_box['y']:.0f})-"
            f"({mc_box['x'] + mc_box['width']:.0f},{mc_box['y'] + mc_box['height']:.0f})"
        )

    def test_no_overlapping_text_in_bottom_left(self, page, take_screenshot):
        """No text elements in the bottom-left 400x80px region should overlap each other."""
        viewport = page.viewport_size
        if viewport is None:
            pytest.skip("Could not get viewport size")

        bottom_left_region = {
            'x': 0,
            'y': viewport['height'] - 80,
            'width': 400,
            'height': 80,
        }

        # Find all visible text-containing leaf elements in that region
        elements = page.evaluate("""(region) => {
            const result = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_ELEMENT
            );
            while (walker.nextNode()) {
                const el = walker.currentNode;
                const text = el.textContent.trim();
                if (!text || text.length > 100) continue;
                if (el.children.length > 0) continue;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) continue;
                const style = getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') continue;
                if (style.opacity === '0') continue;
                if (rect.x < region.x + region.width &&
                    rect.x + rect.width > region.x &&
                    rect.y < region.y + region.height &&
                    rect.y + rect.height > region.y) {
                    result.push({
                        tag: el.tagName,
                        text: text.substring(0, 50),
                        x: rect.x, y: rect.y,
                        w: rect.width, h: rect.height,
                        id: el.id || '',
                        cls: (typeof el.className === 'string' ? el.className : '').substring(0, 60),
                    });
                }
            }
            return result;
        }""", bottom_left_region)

        take_screenshot(page, 'defect-bottom-left-elements')

        if len(elements) < 2:
            return

        overlaps = []
        for i in range(len(elements)):
            for j in range(i + 1, len(elements)):
                a = elements[i]
                b = elements[j]
                h_ov = a['x'] < b['x'] + b['w'] and a['x'] + a['w'] > b['x']
                v_ov = a['y'] < b['y'] + b['h'] and a['y'] + a['h'] > b['y']
                if h_ov and v_ov:
                    ox = min(a['x'] + a['w'], b['x'] + b['w']) - max(a['x'], b['x'])
                    oy = min(a['y'] + a['h'], b['y'] + b['h']) - max(a['y'], b['y'])
                    area = ox * oy
                    if area > 20:  # Flag even small overlaps (>20 sq px)
                        overlaps.append(
                            f"  '{a['text']}' ({a['id'] or a['cls']}) at "
                            f"({a['x']:.0f},{a['y']:.0f} {a['w']:.0f}x{a['h']:.0f}) "
                            f"overlaps '{b['text']}' ({b['id'] or b['cls']}) at "
                            f"({b['x']:.0f},{b['y']:.0f} {b['w']:.0f}x{b['h']:.0f}) "
                            f"by {area:.0f} sq px"
                        )

        assert len(overlaps) == 0, (
            f"Found {len(overlaps)} overlapping text elements in bottom-left corner:\n"
            + "\n".join(overlaps)
        )

    def test_commander_layout_panels_dont_obscure_status_bar(self, page, take_screenshot):
        """Panels in Commander layout should not overlap the status bar."""
        _close_all_panels(page)

        # Apply the Commander preset layout
        page.evaluate("""() => {
            if (window.panelManager) window.panelManager.applyPreset('commander');
        }""")
        page.wait_for_timeout(1000)

        take_screenshot(page, 'defect-commander-layout-status')

        status_bar = page.locator('#status-bar')
        if status_bar.count() == 0:
            pytest.skip("Status bar not found")

        sb_box = status_bar.bounding_box()
        if sb_box is None:
            pytest.skip("Could not get status bar bounding box")

        panels = page.locator('[data-panel-id]')
        panel_count = panels.count()
        overlapping = []

        for i in range(panel_count):
            panel = panels.nth(i)
            if not panel.is_visible():
                continue
            p_box = panel.bounding_box()
            if p_box is None:
                continue

            h_ov = p_box['x'] < sb_box['x'] + sb_box['width'] and \
                   p_box['x'] + p_box['width'] > sb_box['x']
            v_ov = p_box['y'] < sb_box['y'] + sb_box['height'] and \
                   p_box['y'] + p_box['height'] > sb_box['y']
            if h_ov and v_ov:
                pid = panel.get_attribute('data-panel-id')
                overlapping.append(
                    f"Panel '{pid}' "
                    f"({p_box['x']:.0f},{p_box['y']:.0f} "
                    f"{p_box['width']:.0f}x{p_box['height']:.0f}) "
                    f"overlaps status bar "
                    f"({sb_box['x']:.0f},{sb_box['y']:.0f} "
                    f"{sb_box['width']:.0f}x{sb_box['height']:.0f})"
                )

        assert len(overlapping) == 0, (
            f"Panels obscure the status bar in Commander layout:\n"
            + "\n".join(overlapping)
        )

    def test_bottom_left_sufficient_clearance(self, page, take_screenshot):
        """Elements in the bottom-left should have at least 4px clearance."""
        _close_all_panels(page)
        _open_panel(page, '1', 'amy')
        page.wait_for_timeout(500)

        # Get positions of the three bottom-left elements
        positions = page.evaluate("""() => {
            const result = {};
            const amy = document.querySelector('[data-panel-id="amy"]');
            const coords = document.getElementById('map-coords');
            const status = document.getElementById('status-bar');
            if (amy) {
                const r = amy.getBoundingClientRect();
                result.amy = { y: r.y, bottom: r.y + r.height, x: r.x, right: r.x + r.width };
            }
            if (coords) {
                const r = coords.getBoundingClientRect();
                result.coords = { y: r.y, bottom: r.y + r.height, x: r.x, right: r.x + r.width };
            }
            if (status) {
                const r = status.getBoundingClientRect();
                result.status = { y: r.y, bottom: r.y + r.height, x: r.x, right: r.x + r.width };
            }
            return result;
        }""")

        take_screenshot(page, 'defect-bottom-clearance')

        # Check Amy -> map-coords clearance (they share the left side)
        if 'amy' in positions and 'coords' in positions:
            amy = positions['amy']
            coords = positions['coords']
            # Check horizontal overlap
            h_overlap = amy['x'] < coords['right'] and amy['right'] > coords['x']
            if h_overlap:
                gap = coords['y'] - amy['bottom']
                assert gap >= 4, (
                    f"Insufficient clearance between Amy panel bottom ({amy['bottom']:.0f}) "
                    f"and map coords top ({coords['y']:.0f}): {gap:.0f}px (need >= 4px)"
                )

        # Check map-coords -> status-bar clearance
        if 'coords' in positions and 'status' in positions:
            coords = positions['coords']
            status = positions['status']
            h_overlap = coords['x'] < status['right'] and coords['right'] > status['x']
            if h_overlap:
                gap = status['y'] - coords['bottom']
                assert gap >= 0, (
                    f"Map coords bottom ({coords['bottom']:.0f}) extends below "
                    f"status bar top ({status['y']:.0f}): overlap of {-gap:.0f}px"
                )


# ===========================================================================
# TEST 4: Panel Free Movement (all quadrants via drag only)
# ===========================================================================

class TestPanelFreeMovement:
    """Verify all panels can move freely throughout the ENTIRE game area.

    Uses ONLY mouse drag operations — no JS setPosition() bypass.
    Tests with other panels open to detect interaction issues.
    """

    @pytest.mark.parametrize("key,panel_id", [
        ('1', 'amy'),
        ('2', 'units'),
        ('3', 'alerts'),
        ('4', 'game'),
        ('5', 'mesh'),
    ])
    def test_panel_reaches_all_four_quadrants(self, page, take_screenshot, key, panel_id):
        """Panel {panel_id} should be draggable to all four quadrants via mouse."""
        _close_all_panels(page)
        _open_panel(page, key, panel_id)

        # Resize panel small for easier movement
        page.evaluate("""(pid) => {
            const p = window.panelManager && window.panelManager.getPanel(pid);
            if (p) p.setSize(200, 150);
        }""", panel_id)
        page.wait_for_timeout(200)

        container = _get_container_bounds(page)
        assert container is not None

        margin = 50  # px from container edge
        targets = {
            'top-left': (container['x'] + margin + 100, container['y'] + margin + 14),
            'top-right': (container['x'] + container['w'] - margin - 100, container['y'] + margin + 14),
            'bottom-left': (container['x'] + margin + 100, container['bottom'] - margin - 75),
            'bottom-right': (container['x'] + container['w'] - margin - 100, container['bottom'] - margin - 75),
        }

        failed = []
        panel_loc = page.locator(f'[data-panel-id="{panel_id}"]')

        for name, (tx, ty) in targets.items():
            _drag_panel_to(page, panel_id, tx, ty)

            box = panel_loc.bounding_box()
            if box is None:
                failed.append(f"{name}: no bounding box")
                continue

            # Panel center should be within 100px of target
            center_x = box['x'] + box['width'] / 2
            center_y = box['y'] + box['height'] / 2
            distance = ((center_x - tx) ** 2 + (center_y - ty) ** 2) ** 0.5

            if distance > 100:
                failed.append(
                    f"{name}: target ({tx:.0f},{ty:.0f}), "
                    f"center ({center_x:.0f},{center_y:.0f}), "
                    f"distance={distance:.0f}px"
                )

        take_screenshot(page, f'defect-quadrant-{panel_id}')

        assert len(failed) == 0, (
            f"Panel '{panel_id}' could not reach some quadrants:\n"
            + "\n".join(f"  - {f}" for f in failed)
        )


# ===========================================================================
# TEST 5: Panel Independence (no interaction between panels)
# ===========================================================================

class TestPanelIndependence:
    """Panels should not interfere with each other's position or size."""

    def test_opening_new_panel_does_not_move_existing(self, page, take_screenshot):
        """Opening a new panel should not move any already-open panel."""
        _close_all_panels(page)

        # Open Units at default position and record its position
        _open_panel(page, '2', 'units')
        page.wait_for_timeout(500)
        units_before = page.locator('[data-panel-id="units"]').bounding_box()
        assert units_before is not None

        # Open Amy — should NOT move Units
        _open_panel(page, '1', 'amy')
        page.wait_for_timeout(500)

        units_after = page.locator('[data-panel-id="units"]').bounding_box()
        assert units_after is not None

        dx = abs(units_after['x'] - units_before['x'])
        dy = abs(units_after['y'] - units_before['y'])

        take_screenshot(page, 'defect-open-independence')

        assert dx < 5 and dy < 5, (
            f"Units panel moved when Amy was opened! "
            f"Before: ({units_before['x']:.0f},{units_before['y']:.0f}), "
            f"After: ({units_after['x']:.0f},{units_after['y']:.0f}), "
            f"Delta: ({dx:.0f},{dy:.0f})"
        )

    def test_closing_panel_does_not_move_others(self, page, take_screenshot):
        """Closing a panel should not move any other open panel."""
        _close_all_panels(page)

        _open_panel(page, '1', 'amy')
        _open_panel(page, '2', 'units')
        _open_panel(page, '3', 'alerts')
        page.wait_for_timeout(500)

        # Record Units and Alerts positions
        units_before = page.locator('[data-panel-id="units"]').bounding_box()
        alerts_before = page.locator('[data-panel-id="alerts"]').bounding_box()
        assert units_before is not None and alerts_before is not None

        # Close Amy
        page.keyboard.press('1')
        page.wait_for_timeout(500)

        units_after = page.locator('[data-panel-id="units"]').bounding_box()
        alerts_after = page.locator('[data-panel-id="alerts"]').bounding_box()
        assert units_after is not None and alerts_after is not None

        take_screenshot(page, 'defect-close-independence')

        units_dx = abs(units_after['x'] - units_before['x'])
        units_dy = abs(units_after['y'] - units_before['y'])
        alerts_dx = abs(alerts_after['x'] - alerts_before['x'])
        alerts_dy = abs(alerts_after['y'] - alerts_before['y'])

        assert units_dx < 5 and units_dy < 5, (
            f"Units moved when Amy was closed! Delta: ({units_dx:.0f},{units_dy:.0f})"
        )
        assert alerts_dx < 5 and alerts_dy < 5, (
            f"Alerts moved when Amy was closed! Delta: ({alerts_dx:.0f},{alerts_dy:.0f})"
        )

    def test_resize_does_not_constrain_by_container_size(self, page, take_screenshot):
        """Resizing a panel should not push it or others outside the container."""
        _close_all_panels(page)

        _open_panel(page, '2', 'units')
        page.evaluate("""() => {
            const p = window.panelManager && window.panelManager.getPanel('units');
            if (p) { p.setPosition(100, 100); p.setSize(260, 300); }
        }""")
        page.wait_for_timeout(200)

        container = _get_container_bounds(page)
        assert container is not None

        # Record position before resize
        units_before = page.locator('[data-panel-id="units"]').bounding_box()
        assert units_before is not None

        # Resize Units to be very tall (taller than container)
        resize_handle = page.locator('[data-panel-id="units"] [data-resize-handle]')
        rh = resize_handle.bounding_box()
        if rh is not None:
            page.mouse.move(rh['x'] + 5, rh['y'] + 5)
            page.mouse.down()
            page.mouse.move(rh['x'] + 5, rh['y'] + 500, steps=15)
            page.mouse.up()
            page.wait_for_timeout(500)

        take_screenshot(page, 'defect-resize-tall')

        # Position should not have changed
        units_after = page.locator('[data-panel-id="units"]').bounding_box()
        assert units_after is not None

        dy = abs(units_after['y'] - units_before['y'])
        assert dy < 5, (
            f"Units panel moved after being resized tall! "
            f"Before y: {units_before['y']:.0f}, After y: {units_after['y']:.0f}, "
            f"Delta: {dy:.0f}"
        )
