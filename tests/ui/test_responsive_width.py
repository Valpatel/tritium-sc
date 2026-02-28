# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Responsive width tests — detect horizontal overflow at every viewport size.

Tests the Command Center at 5 viewport widths (375..1920px) and reports
any element whose right edge extends past the viewport. Also checks for
document-level horizontal scrollbars and measures total overflow.

Run:
    .venv/bin/python3 -m pytest tests/ui/test_responsive_width.py -v -s
    ./test.sh 12   # if wired into test.sh as tier 12
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ui, pytest.mark.layout]

SCREENSHOT_DIR = Path("tests/.test-results/responsive-screenshots")

# Viewport widths to test (mobile -> ultrawide)
VIEWPORTS = [
    (375, 812, "mobile"),
    (768, 1024, "tablet"),
    (1024, 768, "laptop"),
    (1280, 800, "desktop"),
    (1920, 1080, "fullhd"),
]

# Selectors for elements most likely to overflow.
# Organized by area: structural containers, header, panels, overlays.
OVERFLOW_CHECK_SELECTORS = [
    # Structural
    "body",
    "#app",
    "#command-center",
    "#command-bar",
    "#tactical-area",
    "#status-bar",
    # Header / command bar
    ".cmd-bar",
    ".cmd-bar-left",
    ".cmd-bar-right",
    ".cmd-bar-center",
    # Panels (check the container + visible panels)
    ".panel",
    ".panel-header",
    ".panel-body",
    # Map
    "#tactical-canvas",
    # Overlays
    "#keyboard-guide",
    "#help-overlay",
    ".modal",
    # HUD elements
    ".game-hud",
    ".kill-feed",
    ".wave-banner",
    ".countdown-overlay",
    # Menu bar
    "#menu-bar",
    ".menu-bar",
]

# Elements to check with open panels
PANEL_KEYS = {
    "1": "Amy",
    "2": "Units",
    "3": "Alerts",
    "4": "Game HUD",
}


class TestResponsiveWidth:
    """Detect horizontal overflow at every viewport size."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(self, request, tritium_server: TritiumServer):
        cls = request.cls
        cls.url = tritium_server.url
        cls._errors: list[str] = []

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls.page = None  # Created per viewport

        yield

        cls._browser.close()
        cls._pw.stop()

    def _new_page(self, width: int, height: int):
        """Create a new page at the given viewport size."""
        if self.page:
            self.page.close()
        ctx = self._browser.new_context(
            viewport={"width": width, "height": height},
        )
        self.page = ctx.new_page()
        self.page.on("pageerror", lambda e: self._errors.append(str(e)))
        # Dismiss keyboard guide before loading
        self.page.goto(f"{self.url}/", wait_until="domcontentloaded")
        self.page.evaluate(
            "localStorage.setItem('tritium_keyboard_guide_dismissed','true')"
        )
        self.page.evaluate(
            "localStorage.setItem('tritium-seen-keyboard-guide','1')"
        )
        self.page.reload(wait_until="domcontentloaded")
        self.page.wait_for_timeout(3000)
        # Dismiss any overlay
        self.page.keyboard.press("Escape")
        self.page.wait_for_timeout(500)

    def _measure_document_overflow(self) -> dict:
        """Measure document-level horizontal overflow."""
        return self.page.evaluate("""() => {
            const vw = window.innerWidth;
            const docW = document.documentElement.scrollWidth;
            const bodyW = document.body.scrollWidth;
            const hasHScrollbar = docW > vw || bodyW > vw;
            return {
                viewportWidth: vw,
                documentScrollWidth: docW,
                bodyScrollWidth: bodyW,
                overflow: Math.max(0, docW - vw, bodyW - vw),
                hasHorizontalScrollbar: hasHScrollbar,
            };
        }""")

    def _find_overflowing_elements(self) -> list[dict]:
        """Find all visible elements whose right edge exceeds the viewport."""
        return self.page.evaluate("""() => {
            const vw = window.innerWidth;
            const results = [];
            // Check all elements, not just specific selectors
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const rect = el.getBoundingClientRect();
                // Skip invisible or zero-width elements
                if (rect.width === 0 || rect.height === 0) continue;
                // Skip elements not in viewport vertically
                if (rect.bottom < 0 || rect.top > window.innerHeight) continue;
                // Check if right edge exceeds viewport
                const overflow = rect.right - vw;
                if (overflow > 1) {  // 1px tolerance
                    // Get a useful selector for this element
                    let selector = el.tagName.toLowerCase();
                    if (el.id) selector = '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        const cls = el.className.trim().split(/\\s+/)[0];
                        if (cls) selector = '.' + cls;
                    }
                    // Get parent info for context
                    let parentSelector = '';
                    if (el.parentElement) {
                        if (el.parentElement.id) parentSelector = '#' + el.parentElement.id;
                        else if (el.parentElement.className && typeof el.parentElement.className === 'string') {
                            const pcls = el.parentElement.className.trim().split(/\\s+/)[0];
                            if (pcls) parentSelector = '.' + pcls;
                        }
                    }
                    results.push({
                        selector: selector,
                        parent: parentSelector,
                        left: Math.round(rect.left),
                        right: Math.round(rect.right),
                        width: Math.round(rect.width),
                        top: Math.round(rect.top),
                        overflow: Math.round(overflow),
                        computedWidth: window.getComputedStyle(el).width,
                        computedPosition: window.getComputedStyle(el).position,
                        computedOverflow: window.getComputedStyle(el).overflow,
                    });
                }
            }
            // Deduplicate by selector+parent and keep worst overflow
            const seen = new Map();
            for (const r of results) {
                const key = r.selector + '>' + r.parent;
                if (!seen.has(key) || seen.get(key).overflow < r.overflow) {
                    seen.set(key, r);
                }
            }
            return [...seen.values()].sort((a, b) => b.overflow - a.overflow);
        }""")

    def _screenshot(self, name: str) -> Path:
        path = SCREENSHOT_DIR / f"{name}.png"
        self.page.screenshot(path=str(path), full_page=False)
        return path

    # =================================================================
    # Test: No horizontal scrollbar at any viewport width
    # =================================================================

    @pytest.mark.parametrize("width,height,label", VIEWPORTS)
    def test_no_horizontal_scrollbar(self, width, height, label):
        """Document scrollWidth must not exceed viewport width."""
        self._new_page(width, height)
        self._screenshot(f"viewport_{label}_{width}x{height}")

        overflow = self._measure_document_overflow()
        print(f"\n  [{label} {width}x{height}]")
        print(f"    viewport:  {overflow['viewportWidth']}px")
        print(f"    doc scroll: {overflow['documentScrollWidth']}px")
        print(f"    body scroll: {overflow['bodyScrollWidth']}px")
        print(f"    overflow:   {overflow['overflow']}px")

        if overflow["overflow"] > 0:
            # Find the culprits
            culprits = self._find_overflowing_elements()
            print(f"    OVERFLOWING ELEMENTS ({len(culprits)}):")
            for c in culprits[:15]:
                print(f"      {c['selector']} (parent: {c['parent']})")
                print(f"        right={c['right']}px overflow={c['overflow']}px "
                      f"width={c['computedWidth']} pos={c['computedPosition']} "
                      f"overflow-css={c['computedOverflow']}")

        assert overflow["overflow"] == 0, (
            f"Horizontal overflow at {width}x{height}: "
            f"{overflow['overflow']}px beyond viewport. "
            f"scrollWidth={overflow['documentScrollWidth']}, "
            f"viewport={overflow['viewportWidth']}"
        )

    # =================================================================
    # Test: No element overflows when panels are open
    # =================================================================

    @pytest.mark.parametrize("width,height,label", VIEWPORTS)
    def test_no_overflow_with_panels(self, width, height, label):
        """Opening panels must not push content past viewport width."""
        self._new_page(width, height)

        # Open several panels
        for key, name in PANEL_KEYS.items():
            self.page.keyboard.press(key)
            self.page.wait_for_timeout(500)

        self.page.wait_for_timeout(1000)
        self._screenshot(f"panels_{label}_{width}x{height}")

        overflow = self._measure_document_overflow()
        print(f"\n  [{label} {width}x{height} + panels]")
        print(f"    overflow: {overflow['overflow']}px")

        if overflow["overflow"] > 0:
            culprits = self._find_overflowing_elements()
            print(f"    OVERFLOWING ELEMENTS ({len(culprits)}):")
            for c in culprits[:10]:
                print(f"      {c['selector']} (parent: {c['parent']}) "
                      f"overflow={c['overflow']}px")

        assert overflow["overflow"] == 0, (
            f"Horizontal overflow at {width}x{height} with panels: "
            f"{overflow['overflow']}px beyond viewport"
        )

    # =================================================================
    # Test: Specific known-risk elements stay within viewport
    # =================================================================

    @pytest.mark.parametrize("width,height,label", VIEWPORTS)
    def test_key_elements_within_viewport(self, width, height, label):
        """Header, status bar, and map canvas must fit within viewport."""
        self._new_page(width, height)

        vw = self.page.evaluate("window.innerWidth")
        violations = []

        for sel in OVERFLOW_CHECK_SELECTORS:
            try:
                elements = self.page.locator(sel)
                count = elements.count()
                for i in range(min(count, 5)):  # Check up to 5 matches
                    el = elements.nth(i)
                    if not el.is_visible():
                        continue
                    box = el.bounding_box()
                    if box is None:
                        continue
                    right_edge = box["x"] + box["width"]
                    if right_edge > vw + 1:  # 1px tolerance
                        overflow = right_edge - vw
                        violations.append({
                            "selector": sel,
                            "index": i,
                            "right": round(right_edge),
                            "overflow": round(overflow),
                            "width": round(box["width"]),
                            "x": round(box["x"]),
                        })
            except Exception:
                continue  # Element not found, skip

        if violations:
            print(f"\n  [{label} {width}x{height}] "
                  f"ELEMENT OVERFLOW ({len(violations)}):")
            for v in violations:
                print(f"    {v['selector']}[{v['index']}]: "
                      f"x={v['x']} width={v['width']} "
                      f"right={v['right']} overflow={v['overflow']}px")
            self._screenshot(f"elements_{label}_{width}x{height}_overflow")

        assert len(violations) == 0, (
            f"{len(violations)} element(s) overflow viewport at "
            f"{width}x{height}: "
            + ", ".join(f"{v['selector']} (+{v['overflow']}px)"
                        for v in violations[:5])
        )

    # =================================================================
    # Test: Full viewport report (always passes, diagnostic)
    # =================================================================

    def test_viewport_report(self):
        """Generate a full diagnostic report of overflow at all sizes."""
        results = {}
        for width, height, label in VIEWPORTS:
            self._new_page(width, height)
            self._screenshot(f"report_{label}_{width}x{height}")

            doc_overflow = self._measure_document_overflow()
            culprits = (self._find_overflowing_elements()
                        if doc_overflow["overflow"] > 0 else [])

            results[label] = {
                "width": width,
                "height": height,
                "overflow": doc_overflow["overflow"],
                "scrollWidth": doc_overflow["documentScrollWidth"],
                "culprit_count": len(culprits),
                "worst_culprits": [
                    f"{c['selector']} (+{c['overflow']}px)"
                    for c in culprits[:5]
                ],
            }

        # Print report
        print("\n" + "=" * 70)
        print("  RESPONSIVE WIDTH REPORT")
        print("=" * 70)
        all_clean = True
        for label, r in results.items():
            status = "OK" if r["overflow"] == 0 else "OVERFLOW"
            if r["overflow"] > 0:
                all_clean = False
            print(f"  {label:>8} ({r['width']}x{r['height']}): "
                  f"{status} — overflow={r['overflow']}px "
                  f"scrollW={r['scrollWidth']}px")
            if r["worst_culprits"]:
                for c in r["worst_culprits"]:
                    print(f"           {c}")
        print("=" * 70)
        if all_clean:
            print("  ALL VIEWPORTS CLEAN")
        else:
            fail_count = sum(1 for r in results.values() if r["overflow"] > 0)
            print(f"  {fail_count}/{len(results)} viewport(s) have overflow")
        print("=" * 70)
        print(f"  Screenshots: {SCREENSHOT_DIR}/")
