"""Responsive RESIZE tests — verify the UI adapts when viewport changes.

Unlike test_responsive_width.py (which opens fresh pages at each size),
these tests RESIZE a running page and verify that all layout elements
reflow correctly. This catches the real-world issue: the user drags
their browser window narrower and the canvas/layout/command-bar fail to
update.

Dimensions tested:
  - Canvas buffer (canvas.width/height) must match container after resize
  - Canvas CSS size must fill its parent
  - .unified-layout must span the full viewport width
  - .unified-tactical must span viewport minus bars
  - Command bar buttons must not overflow the viewport
  - Status bar must span full width
  - Header must span full width
  - Panels must stay within viewport bounds after resize

Run:
    .venv/bin/python3 -m pytest tests/ui/test_responsive_resize.py -v -s
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.lib.server_manager import TritiumServer

pytestmark = [pytest.mark.ui, pytest.mark.layout, pytest.mark.responsive]

SCREENSHOT_DIR = Path("tests/.test-results/responsive-resize")

# Start wide, then resize through these widths.
# The test starts at 1920 and RESIZES to each, measuring after each change.
RESIZE_WIDTHS = [1920, 1280, 1024, 800, 640]
INITIAL_HEIGHT = 900


class TestResponsiveResize:
    """Verify the UI adapts dynamically when the viewport is resized."""

    @pytest.fixture(autouse=True, scope="class")
    def _browser(self, request, tritium_server: TritiumServer):
        cls = request.cls
        cls.url = tritium_server.url
        cls._errors: list[str] = []

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        cls._browser_inst = cls._pw.chromium.launch(headless=True)

        yield

        cls._browser_inst.close()
        cls._pw.stop()

    def _make_page(self, width=1920, height=INITIAL_HEIGHT):
        """Create a page at the given viewport and load the Command Center."""
        ctx = self._browser_inst.new_context(
            viewport={"width": width, "height": height},
        )
        page = ctx.new_page()
        page.on("pageerror", lambda e: self._errors.append(str(e)))
        page.goto(f"{self.url}/", wait_until="domcontentloaded", timeout=30000)
        # Dismiss keyboard guide
        page.evaluate(
            "localStorage.setItem('tritium_keyboard_guide_dismissed','true')"
        )
        page.evaluate(
            "localStorage.setItem('tritium-seen-keyboard-guide','1')"
        )
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        return page, ctx

    def _measure_all(self, page):
        """Collect all layout measurements in a single JS eval."""
        return page.evaluate("""() => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;

            // Helper: getBoundingClientRect safely
            function rect(sel) {
                const el = document.querySelector(sel);
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return { x: r.x, y: r.y, w: r.width, h: r.height,
                         right: r.right, bottom: r.bottom };
            }

            // Canvas internal buffer vs CSS size
            const canvas = document.getElementById('tactical-canvas');
            const canvasParent = canvas ? canvas.parentElement : null;
            const dpr = window.devicePixelRatio || 1;

            const canvasData = canvas ? {
                bufferW: canvas.width,
                bufferH: canvas.height,
                cssW: canvas.getBoundingClientRect().width,
                cssH: canvas.getBoundingClientRect().height,
                parentW: canvasParent ? canvasParent.clientWidth : 0,
                parentH: canvasParent ? canvasParent.clientHeight : 0,
                expectedBufW: Math.round((canvasParent ? canvasParent.clientWidth : 0) * dpr),
                expectedBufH: Math.round((canvasParent ? canvasParent.clientHeight : 0) * dpr),
            } : null;

            // Document overflow
            const docW = document.documentElement.scrollWidth;
            const bodyW = document.body.scrollWidth;
            const hOverflow = Math.max(0, docW - vw, bodyW - vw);

            // Command bar right: do buttons overflow?
            const barRight = document.querySelector('.command-bar-right');
            let cmdBarOverflow = 0;
            let cmdBarScrollW = 0;
            let cmdBarClientW = 0;
            if (barRight) {
                cmdBarScrollW = barRight.scrollWidth;
                cmdBarClientW = barRight.clientWidth;
                const brRect = barRight.getBoundingClientRect();
                cmdBarOverflow = Math.max(0, brRect.right - vw);
            }

            // Overflowing elements (top 10 worst)
            const overflowers = [];
            for (const el of document.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                if (r.bottom < 0 || r.top > vh) continue;
                const ov = r.right - vw;
                if (ov > 1) {
                    let sel = el.tagName.toLowerCase();
                    if (el.id) sel = '#' + el.id;
                    else if (el.className && typeof el.className === 'string') {
                        const c = el.className.trim().split(/\\s+/)[0];
                        if (c) sel = '.' + c;
                    }
                    overflowers.push({ sel, overflow: Math.round(ov),
                                       right: Math.round(r.right),
                                       width: Math.round(r.width) });
                }
            }
            overflowers.sort((a, b) => b.overflow - a.overflow);

            return {
                viewport: { w: vw, h: vh },
                dpr,
                canvas: canvasData,
                layout: rect('#main-layout') || rect('.unified-layout'),
                tactical: rect('#tactical-area') || rect('.unified-tactical'),
                header: rect('#header-bar') || rect('.cc-header'),
                statusBar: rect('#status-bar') || rect('.status-bar'),
                commandBar: rect('.command-bar'),
                commandBarRight: {
                    overflow: cmdBarOverflow,
                    scrollWidth: cmdBarScrollW,
                    clientWidth: cmdBarClientW,
                },
                documentOverflow: hOverflow,
                overflowers: overflowers.slice(0, 10),
            };
        }""")

    def _screenshot(self, page, name: str) -> Path:
        path = SCREENSHOT_DIR / f"{name}.png"
        page.screenshot(path=str(path), full_page=False)
        return path

    def _print_measurements(self, m, label):
        """Print diagnostic info for a measurement snapshot."""
        vw = m["viewport"]["w"]
        print(f"\n  [{label}] viewport={vw}x{m['viewport']['h']} dpr={m['dpr']}")

        if m["canvas"]:
            c = m["canvas"]
            buf_ok = (abs(c["bufferW"] - c["expectedBufW"]) <= 2 and
                      abs(c["bufferH"] - c["expectedBufH"]) <= 2)
            css_ok = abs(c["cssW"] - c["parentW"]) <= 2
            print(f"    canvas buffer: {c['bufferW']}x{c['bufferH']} "
                  f"(expected {c['expectedBufW']}x{c['expectedBufH']}) "
                  f"{'OK' if buf_ok else 'MISMATCH'}")
            print(f"    canvas CSS:    {c['cssW']:.0f}x{c['cssH']:.0f} "
                  f"parent: {c['parentW']}x{c['parentH']} "
                  f"{'OK' if css_ok else 'MISMATCH'}")

        if m["layout"]:
            l = m["layout"]
            print(f"    layout:   x={l['x']:.0f} w={l['w']:.0f} "
                  f"(viewport={vw}) "
                  f"{'OK' if abs(l['w'] - vw) <= 2 else 'MISMATCH'}")

        if m["tactical"]:
            t = m["tactical"]
            print(f"    tactical: x={t['x']:.0f} w={t['w']:.0f} "
                  f"(viewport={vw}) "
                  f"{'OK' if abs(t['w'] - vw) <= 2 else 'MISMATCH'}")

        if m["header"]:
            h = m["header"]
            print(f"    header:   x={h['x']:.0f} w={h['w']:.0f} right={h['right']:.0f}")

        if m["statusBar"]:
            s = m["statusBar"]
            print(f"    status:   x={s['x']:.0f} w={s['w']:.0f} right={s['right']:.0f}")

        cbr = m["commandBarRight"]
        print(f"    cmd-bar-right: scroll={cbr['scrollWidth']} "
              f"client={cbr['clientWidth']} overflow={cbr['overflow']:.0f}px")

        print(f"    doc overflow:  {m['documentOverflow']}px")
        if m["overflowers"]:
            print(f"    overflowing elements ({len(m['overflowers'])}):")
            for o in m["overflowers"][:5]:
                print(f"      {o['sel']}: right={o['right']} "
                      f"overflow=+{o['overflow']}px")

    # =================================================================
    # Test 1: Canvas buffer matches container after resize
    # =================================================================

    def test_01_canvas_resizes_with_viewport(self):
        """Canvas internal buffer must update when viewport shrinks."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                # Give ResizeObserver + rAF time to fire
                page.wait_for_timeout(1000)

                m = self._measure_all(page)
                self._print_measurements(m, f"canvas@{width}")
                self._screenshot(page, f"canvas_resize_{width}")

                c = m["canvas"]
                if c is None:
                    failures.append(f"  {width}px: canvas not found")
                    continue

                buf_w_diff = abs(c["bufferW"] - c["expectedBufW"])
                buf_h_diff = abs(c["bufferH"] - c["expectedBufH"])
                css_w_diff = abs(c["cssW"] - c["parentW"])

                if buf_w_diff > 2:
                    failures.append(
                        f"  {width}px: buffer width {c['bufferW']} != "
                        f"expected {c['expectedBufW']} (diff={buf_w_diff})")
                if buf_h_diff > 2:
                    failures.append(
                        f"  {width}px: buffer height {c['bufferH']} != "
                        f"expected {c['expectedBufH']} (diff={buf_h_diff})")
                if css_w_diff > 2:
                    failures.append(
                        f"  {width}px: CSS width {c['cssW']:.0f} != "
                        f"parent {c['parentW']} (diff={css_w_diff:.0f})")

            assert not failures, (
                f"Canvas did not resize correctly:\n"
                + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 2: Layout container spans full viewport width after resize
    # =================================================================

    def test_02_layout_spans_viewport_after_resize(self):
        """.unified-layout must be exactly viewport width at every size."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(800)

                m = self._measure_all(page)
                self._print_measurements(m, f"layout@{width}")

                if m["layout"]:
                    diff = abs(m["layout"]["w"] - width)
                    if diff > 2:
                        failures.append(
                            f"  {width}px: layout width={m['layout']['w']:.0f} "
                            f"(expected {width}, diff={diff:.0f})")
                else:
                    failures.append(f"  {width}px: layout element not found")

            assert not failures, (
                f"Layout does not span viewport:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 3: Tactical area spans full width after resize
    # =================================================================

    def test_03_tactical_area_spans_width(self):
        """.unified-tactical must be exactly viewport width at every size."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(800)

                m = self._measure_all(page)

                if m["tactical"]:
                    diff = abs(m["tactical"]["w"] - width)
                    if diff > 2:
                        failures.append(
                            f"  {width}px: tactical width={m['tactical']['w']:.0f} "
                            f"(expected {width}, diff={diff:.0f})")
                else:
                    failures.append(f"  {width}px: tactical area not found")

            assert not failures, (
                f"Tactical area does not span viewport:\n"
                + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 4: No horizontal document overflow after resize
    # =================================================================

    def test_04_no_document_overflow_after_resize(self):
        """Document scrollWidth must not exceed viewport at any width."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(800)

                m = self._measure_all(page)
                self._screenshot(page, f"overflow_{width}")

                ov = m["documentOverflow"]
                if ov > 0:
                    culprits = ", ".join(
                        f"{o['sel']}(+{o['overflow']}px)"
                        for o in m["overflowers"][:5]
                    )
                    failures.append(
                        f"  {width}px: {ov}px overflow — {culprits}")

            assert not failures, (
                f"Document overflow after resize:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 5: Command bar right does not extend past viewport
    # =================================================================

    def test_05_command_bar_fits_viewport(self):
        """Command bar buttons must not push past viewport edge."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(800)

                m = self._measure_all(page)
                cbr = m["commandBarRight"]
                if cbr["overflow"] > 1:
                    failures.append(
                        f"  {width}px: cmd-bar-right overflow "
                        f"{cbr['overflow']:.0f}px "
                        f"(scroll={cbr['scrollWidth']} "
                        f"client={cbr['clientWidth']})")

                # Also check the overall command bar rect
                cb = m["commandBar"]
                if cb and cb["right"] > width + 1:
                    failures.append(
                        f"  {width}px: command-bar right={cb['right']:.0f} "
                        f"> viewport {width}")

            assert not failures, (
                f"Command bar overflow:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 6: Header and status bar span full width
    # =================================================================

    def test_06_header_and_status_span_width(self):
        """Header and status bar must span viewport width after resize."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            failures = []
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(800)

                m = self._measure_all(page)

                for name, data in [("header", m["header"]),
                                   ("statusBar", m["statusBar"])]:
                    if not data:
                        continue
                    # Must start at x=0 and span full width
                    if data["x"] > 1:
                        failures.append(
                            f"  {width}px: {name} x={data['x']:.0f} (should be 0)")
                    right_diff = abs(data["right"] - width)
                    if right_diff > 2:
                        failures.append(
                            f"  {width}px: {name} right={data['right']:.0f} "
                            f"(should be {width}, diff={right_diff:.0f})")

            assert not failures, (
                f"Header/status bar sizing:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 7: Panels re-clamp after resize
    # =================================================================

    def test_07_panels_stay_within_bounds_after_resize(self):
        """Open panels, resize smaller, panels must stay within viewport."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            # Dismiss overlays
            page.evaluate(
                'document.querySelectorAll("[id$=overlay], .keyboard-guide")'
                '.forEach(e => e.hidden = true)'
            )
            page.wait_for_timeout(200)

            # Open 4 panels
            for key in ["1", "2", "3", "4"]:
                page.keyboard.press(key)
                page.wait_for_timeout(400)

            # Now resize down to 800px
            page.set_viewport_size({"width": 800, "height": 600})
            page.wait_for_timeout(1500)  # debounced resize handler = 150ms

            self._screenshot(page, "panels_after_resize_800")

            # Measure panel positions
            panel_data = page.evaluate("""() => {
                const vw = window.innerWidth;
                const vh = window.innerHeight;
                const panels = document.querySelectorAll('.panel');
                const results = [];
                for (const p of panels) {
                    if (p.style.display === 'none') continue;
                    const r = p.getBoundingClientRect();
                    if (r.width === 0 || r.height === 0) continue;
                    const id = p.dataset.panelId || 'unknown';
                    results.push({
                        id,
                        x: Math.round(r.x), y: Math.round(r.y),
                        w: Math.round(r.width), h: Math.round(r.height),
                        right: Math.round(r.right), bottom: Math.round(r.bottom),
                        overflowRight: Math.max(0, Math.round(r.right - vw)),
                        overflowBottom: Math.max(0, Math.round(r.bottom - vh)),
                    });
                }
                return { panels: results, viewport: { w: vw, h: vh } };
            }""")

            failures = []
            vw = panel_data["viewport"]["w"]
            vh = panel_data["viewport"]["h"]
            for p in panel_data["panels"]:
                # Panel header (40px minimum) must be on-screen horizontally
                header_visible = (p["x"] + p["w"] >= 40 and p["x"] <= vw - 40)
                if not header_visible:
                    failures.append(
                        f"  Panel '{p['id']}': header not grabbable "
                        f"(x={p['x']} w={p['w']} viewport={vw})")

                print(f"    panel '{p['id']}': "
                      f"x={p['x']} y={p['y']} w={p['w']} h={p['h']} "
                      f"right={p['right']} bottom={p['bottom']}")

            assert not failures, (
                f"Panels out of bounds after resize:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 8: Resize up restores layout correctly
    # =================================================================

    def test_08_resize_up_restores_layout(self):
        """Shrink then expand — layout must recover to full width."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            # Shrink to 640px
            page.set_viewport_size({"width": 640, "height": INITIAL_HEIGHT})
            page.wait_for_timeout(1000)
            m_small = self._measure_all(page)

            # Expand back to 1920px
            page.set_viewport_size({"width": 1920, "height": INITIAL_HEIGHT})
            page.wait_for_timeout(1000)
            m_big = self._measure_all(page)
            self._screenshot(page, "resize_up_1920")
            self._print_measurements(m_big, "resize_up@1920")

            failures = []

            # Canvas should have re-expanded
            if m_big["canvas"]:
                c = m_big["canvas"]
                if abs(c["bufferW"] - c["expectedBufW"]) > 2:
                    failures.append(
                        f"  canvas buffer width {c['bufferW']} != "
                        f"expected {c['expectedBufW']} after resize up")
                if abs(c["cssW"] - c["parentW"]) > 2:
                    failures.append(
                        f"  canvas CSS width {c['cssW']:.0f} != "
                        f"parent {c['parentW']} after resize up")

            # Layout should span 1920
            if m_big["layout"]:
                if abs(m_big["layout"]["w"] - 1920) > 2:
                    failures.append(
                        f"  layout width {m_big['layout']['w']:.0f} != 1920 "
                        f"after resize up")

            # No overflow
            if m_big["documentOverflow"] > 0:
                failures.append(
                    f"  document overflow {m_big['documentOverflow']}px "
                    f"after resize up")

            assert not failures, (
                f"Layout not restored after resize up:\n"
                + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 9: Rapid resize stress test
    # =================================================================

    def test_09_rapid_resize_stress(self):
        """Rapidly toggle between sizes — no crash, no stuck layout."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            sizes = [1920, 640, 1280, 800, 1920, 1024, 640, 1920]
            for w in sizes:
                page.set_viewport_size({"width": w, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(200)  # minimal settle

            # Final settle
            page.set_viewport_size({"width": 1280, "height": INITIAL_HEIGHT})
            page.wait_for_timeout(1500)

            m = self._measure_all(page)
            self._screenshot(page, "stress_final_1280")
            self._print_measurements(m, "stress_final@1280")

            failures = []
            if m["canvas"]:
                c = m["canvas"]
                if abs(c["bufferW"] - c["expectedBufW"]) > 2:
                    failures.append(
                        f"  canvas buffer {c['bufferW']} != "
                        f"expected {c['expectedBufW']}")
            if m["layout"] and abs(m["layout"]["w"] - 1280) > 2:
                failures.append(
                    f"  layout width {m['layout']['w']:.0f} != 1280")
            if m["documentOverflow"] > 0:
                failures.append(
                    f"  overflow {m['documentOverflow']}px")

            assert not failures, (
                f"Layout broken after rapid resize:\n" + "\n".join(failures)
            )
        finally:
            ctx.close()

    # =================================================================
    # Test 10: Full diagnostic report (always prints, never asserts)
    # =================================================================

    def test_10_resize_diagnostic_report(self):
        """Comprehensive diagnostic of all measurements at every width."""
        page, ctx = self._make_page(1920, INITIAL_HEIGHT)
        try:
            all_results = {}
            for width in RESIZE_WIDTHS:
                page.set_viewport_size({"width": width, "height": INITIAL_HEIGHT})
                page.wait_for_timeout(1000)
                m = self._measure_all(page)
                self._screenshot(page, f"diag_{width}")
                self._print_measurements(m, f"diagnostic@{width}")

                c = m["canvas"]
                all_results[width] = {
                    "canvas_buf_match": (
                        c and abs(c["bufferW"] - c["expectedBufW"]) <= 2),
                    "canvas_css_match": (
                        c and abs(c["cssW"] - c["parentW"]) <= 2),
                    "layout_spans": (
                        m["layout"] and
                        abs(m["layout"]["w"] - width) <= 2),
                    "tactical_spans": (
                        m["tactical"] and
                        abs(m["tactical"]["w"] - width) <= 2),
                    "no_overflow": m["documentOverflow"] == 0,
                    "cmd_bar_ok": m["commandBarRight"]["overflow"] <= 1,
                    "overflower_count": len(m["overflowers"]),
                }

            # Print summary table
            print("\n" + "=" * 78)
            print("  RESPONSIVE RESIZE DIAGNOSTIC REPORT")
            print("=" * 78)
            print(f"  {'Width':>6}  {'Canvas':>7}  {'CSS':>5}  "
                  f"{'Layout':>7}  {'Tact':>5}  {'NoOvfl':>7}  "
                  f"{'CmdBar':>7}  {'Ovfl#':>5}")
            print("-" * 78)
            for width, r in all_results.items():
                def yn(v):
                    return "OK" if v else "FAIL"
                print(f"  {width:>6}  {yn(r['canvas_buf_match']):>7}  "
                      f"{yn(r['canvas_css_match']):>5}  "
                      f"{yn(r['layout_spans']):>7}  "
                      f"{yn(r['tactical_spans']):>5}  "
                      f"{yn(r['no_overflow']):>7}  "
                      f"{yn(r['cmd_bar_ok']):>7}  "
                      f"{r['overflower_count']:>5}")
            print("=" * 78)

            # Save JSON metrics
            metrics_path = SCREENSHOT_DIR / "resize_metrics.json"
            metrics_path.write_text(json.dumps(all_results, indent=2))
            print(f"  Metrics: {metrics_path}")
            print(f"  Screenshots: {SCREENSHOT_DIR}/")
        finally:
            ctx.close()
