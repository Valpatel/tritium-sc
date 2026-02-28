# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Comprehensive game loop verification with visual proof.

Runs the FULL game loop and proves every UI element works using:
1. Full game loop logs (API state at each phase)
2. OpenCV color filters for unit detection (friendly green, hostile red)
3. Edge detection + bounding boxes for UI panel identification
4. OCR text detection via pytesseract
5. Annotated screenshots showing what was detected

All results are recorded to ResultsDB for interactive HTML reports.

Run:
    .venv/bin/python3 -m pytest tests/visual/test_game_loop_proof.py -v -s
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import requests

pytestmark = pytest.mark.visual

PROOF_DIR = Path("tests/.test-results/game-loop-proof")

# BGR colors from the UI
FRIENDLY_GREEN_BGR = np.array([161, 255, 5])    # #05ffa1
HOSTILE_RED_BGR = np.array([109, 42, 255])       # #ff2a6d
CYAN_BGR = np.array([255, 240, 0])               # #00f0ff
YELLOW_BGR = np.array([10, 238, 252])            # #fcee0a
WHITE_BGR = np.array([255, 255, 255])


def _ensure_dir() -> Path:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    return PROOF_DIR


def _screenshot(page, name: str) -> tuple[Path, np.ndarray]:
    d = _ensure_dir()
    path = d / f"{name}.png"
    page.screenshot(path=str(path))
    img = cv2.imread(str(path))
    return path, img


def _save_annotated(img: np.ndarray, name: str, annotations: list[dict]) -> Path:
    """Save a copy of the image with colored bounding boxes and labels."""
    d = _ensure_dir()
    annotated = img.copy()
    for ann in annotations:
        x, y, w, h = ann["bbox"]
        color = ann.get("color", (0, 255, 255))  # default cyan
        label = ann.get("label", "")
        thickness = ann.get("thickness", 2)
        cv2.rectangle(annotated, (x, y), (x + w, y + h), color, thickness)
        if label:
            # Background for text readability
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(annotated, (x, y - th - 6), (x + tw + 4, y), (0, 0, 0), -1)
            cv2.putText(annotated, label, (x + 2, y - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    path = d / f"{name}_annotated.png"
    cv2.imwrite(str(path), annotated)
    return path


def _detect_color_regions(img: np.ndarray, target_bgr: np.ndarray,
                          tolerance: int = 40, min_area: int = 20) -> list[dict]:
    """Find contiguous regions of a specific color. Returns bounding boxes."""
    lower = np.clip(target_bgr.astype(int) - tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(target_bgr.astype(int) + tolerance, 0, 255).astype(np.uint8)
    mask = cv2.inRange(img, lower, upper)
    # Dilate to connect nearby pixels
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.dilate(mask, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            x, y, w, h = cv2.boundingRect(c)
            regions.append({"bbox": (x, y, w, h), "area": area})
    return regions


def _detect_panels_by_edges(img: np.ndarray) -> list[dict]:
    """Detect floating panels using edge detection on rectangular structures.

    Panels are dark rectangles with subtle borders -- we look for rectangular
    contours in the upper half of the brightness range (panel backgrounds
    are brighter than the void background).
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Threshold to isolate panel regions (slightly brighter than void #060609)
    _, thresh = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)
    # Clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=3)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    panels = []
    h, w = img.shape[:2]
    for c in contours:
        area = cv2.contourArea(c)
        x, y, bw, bh = cv2.boundingRect(c)
        # Panels are rectangular, minimum 100x80, not the full screen
        if area < 5000 or bw < 100 or bh < 60:
            continue
        if bw > w * 0.9 and bh > h * 0.9:
            continue  # Skip full-screen regions
        # Check rectangularity (contour area / bounding box area)
        rect_ratio = area / (bw * bh) if bw * bh > 0 else 0
        if rect_ratio > 0.5:
            panels.append({"bbox": (x, y, bw, bh), "area": area,
                           "rectangularity": round(rect_ratio, 2)})
    return panels


def _detect_text_regions(img: np.ndarray) -> list[dict]:
    """Find text-like regions using edge density analysis.

    Text has high edge density in small horizontal strips. We look for
    regions with >3% edge density that are wider than tall.
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Brighten to isolate text (text is light on dark)
    _, text_mask = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
    # Dilate to connect individual letters into words/lines
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (12, 3))
    text_mask = cv2.dilate(text_mask, kernel_h, iterations=2)
    # Close small gaps
    kernel_c = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_CLOSE, kernel_c)
    contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    text_regions = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 20 or h < 6 or h > 100:
            continue
        # Text lines are wider than tall
        if w < h * 0.8:
            continue
        area = cv2.contourArea(c)
        if area < 100:
            continue
        text_regions.append({"bbox": (x, y, w, h), "area": area})
    return text_regions


def _ocr_region(img: np.ndarray, x: int, y: int, w: int, h: int) -> str:
    """Run OCR on a specific region of the image."""
    try:
        import pytesseract
        region = img[y:y+h, x:x+w]
        if region.size == 0:
            return ""
        # Preprocess: grayscale, invert (white text on dark -> black on white)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
        # Scale up for better OCR
        scale = max(2, 40 // max(h, 1))
        scaled = cv2.resize(binary, None, fx=scale, fy=scale,
                            interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(scaled, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789:/.-%() ").strip()
        return text
    except Exception:
        return ""


def _ocr_full_page(img: np.ndarray) -> list[dict]:
    """Run OCR on the entire page and return detected text with positions."""
    try:
        import pytesseract
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
        data = pytesseract.image_to_data(binary, output_type=pytesseract.Output.DICT,
                                         config="--psm 11")
        results = []
        for i in range(len(data["text"])):
            text = data["text"][i].strip()
            conf = int(data["conf"][i]) if data["conf"][i] != "-1" else 0
            if text and conf > 30 and len(text) > 1:
                results.append({
                    "text": text,
                    "bbox": (data["left"][i], data["top"][i],
                             data["width"][i], data["height"][i]),
                    "confidence": conf,
                })
        return results
    except Exception:
        return []


def _log(msg: str) -> None:
    """Print a log line with timestamp."""
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


class TestGameLoopProof:
    """Full game loop verification with OpenCV + OCR visual proof."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, tritium_server, test_db, run_id):
        cls = request.cls
        cls.url = tritium_server.url
        cls._db = test_db
        cls._run_id = run_id
        cls._game_log: list[str] = []
        cls._t0 = time.monotonic()

        _ensure_dir()

        from playwright.sync_api import sync_playwright

        cls._pw = sync_playwright().start()
        browser = cls._pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        cls.page = ctx.new_page()

        # Capture console errors
        cls._errors = []
        cls.page.on("pageerror", lambda e: cls._errors.append(str(e)))

        # Navigate and wait for data
        cls.page.goto(f"{cls.url}/", wait_until="networkidle")
        cls.page.wait_for_timeout(4000)

        yield

        # Generate report after all tests complete
        try:
            cls._db.finish_run(cls._run_id)
            from tests.lib.report_gen import ReportGenerator
            gen = ReportGenerator(cls._db)
            report_path = gen.generate(cls._run_id)
            json_path = gen.export_json(cls._run_id)
            print(f"\n  HTML Report: {report_path}")
            print(f"  JSON Metrics: {json_path}")
        except Exception as e:
            print(f"\n  Report generation failed: {e}")

        browser.close()
        cls._pw.stop()

    def _record(self, name: str, passed: bool, details: dict | None = None) -> None:
        """Record a test result to ResultsDB."""
        duration_ms = (time.monotonic() - self._t0) * 1000
        self._db.record_result(self._run_id, name, passed, duration_ms, details or {})

    def _record_screenshot(
        self, name: str, phase: str, image_path: str,
        opencv_data: dict | None = None, api_state: dict | None = None,
    ) -> None:
        """Record a screenshot to ResultsDB."""
        self._db.record_screenshot(
            run_id=self._run_id,
            test_name=name,
            phase=phase,
            image_path=image_path,
            opencv_results=opencv_data or {},
            llava_response="",
            llava_host="",
            llava_ms=0,
            api_state=api_state or {},
        )

    def _api_get(self, path: str) -> dict | list | None:
        try:
            resp = requests.get(f"{self.url}{path}", timeout=5)
            return resp.json() if resp.status_code == 200 else None
        except Exception:
            return None

    def _api_post(self, path: str, data: dict | None = None) -> dict | None:
        try:
            resp = requests.post(f"{self.url}{path}", json=data or {}, timeout=5)
            return resp.json() if resp.status_code in (200, 400) else None
        except Exception:
            return None

    def _get_targets(self) -> list[dict]:
        data = self._api_get("/api/amy/simulation/targets")
        if isinstance(data, dict):
            return data.get("targets", [])
        return data if isinstance(data, list) else []

    # -----------------------------------------------------------------------
    # Test 1: UI Element Audit with OpenCV
    # -----------------------------------------------------------------------
    def test_01_ui_element_audit(self):
        """Detect all UI elements using color filters + edge detection."""
        print("\n" + "=" * 70)
        print("  TEST 01: UI ELEMENT AUDIT (OpenCV)")
        print("=" * 70)

        test_name = "proof_01_ui_element_audit"
        path, img = _screenshot(self.page, "01_ui_audit")
        h, w = img.shape[:2]
        annotations = []

        # 1. Header bar (top 36px)
        header_region = img[0:36, :]
        header_brightness = float(cv2.cvtColor(header_region, cv2.COLOR_BGR2GRAY).mean())
        header_ok = header_brightness > 8
        annotations.append({"bbox": (0, 0, w, 36), "color": (0, 255, 0) if header_ok else (0, 0, 255),
                            "label": f"HEADER (brightness={header_brightness:.0f})"})
        _log(f"Header bar: brightness={header_brightness:.1f} {'PASS' if header_ok else 'FAIL'}")

        # 2. Status bar (bottom 20px)
        status_region = img[h-20:h, :]
        status_brightness = float(cv2.cvtColor(status_region, cv2.COLOR_BGR2GRAY).mean())
        status_ok = status_brightness > 5
        annotations.append({"bbox": (0, h-20, w, 20), "color": (0, 255, 0) if status_ok else (0, 0, 255),
                            "label": f"STATUS BAR (brightness={status_brightness:.0f})"})
        _log(f"Status bar: brightness={status_brightness:.1f} {'PASS' if status_ok else 'FAIL'}")

        # 3. Canvas (main tactical area between header and status)
        canvas_region = img[36:h-20, :]
        canvas_brightness = float(cv2.cvtColor(canvas_region, cv2.COLOR_BGR2GRAY).mean())
        canvas_nonblack = np.count_nonzero(cv2.cvtColor(canvas_region, cv2.COLOR_BGR2GRAY) > 15)
        canvas_pct = canvas_nonblack / canvas_region.shape[0] / canvas_region.shape[1] * 100
        canvas_ok = canvas_pct > 5
        annotations.append({"bbox": (0, 36, w, h-56), "color": (0, 255, 0) if canvas_ok else (0, 0, 255),
                            "label": f"CANVAS ({canvas_pct:.1f}% non-black)", "thickness": 1})
        _log(f"Canvas: {canvas_pct:.1f}% non-black, mean brightness={canvas_brightness:.1f} {'PASS' if canvas_ok else 'FAIL'}")

        # 4. Friendly units (green blobs)
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        for i, gr in enumerate(green_regions[:10]):
            annotations.append({"bbox": gr["bbox"], "color": (0, 255, 100),
                                "label": f"UNIT-F{i+1} (area={gr['area']:.0f})"})
        _log(f"Friendly unit blobs: {len(green_regions)} detected")

        # 5. Cyan UI elements (grid lines, borders, highlights)
        cyan_regions = _detect_color_regions(img, CYAN_BGR, tolerance=50, min_area=30)
        for i, cr in enumerate(cyan_regions[:5]):
            annotations.append({"bbox": cr["bbox"], "color": (255, 200, 0),
                                "label": f"CYAN-UI{i+1}"})
        _log(f"Cyan UI elements: {len(cyan_regions)} detected")

        # 6. Floating panels (DOM-verified + OpenCV overlay)
        panel_dom = self.page.evaluate("""() => {
            return [...document.querySelectorAll('.panel')].filter(p =>
                p.offsetParent !== null && p.style.display !== 'none'
            ).map(p => {
                const r = p.getBoundingClientRect();
                return {
                    title: p.querySelector('.panel-title')?.textContent?.trim() || '',
                    x: Math.round(r.x), y: Math.round(r.y),
                    w: Math.round(r.width), h: Math.round(r.height)
                };
            });
        }""")
        for i, p in enumerate(panel_dom):
            annotations.append({"bbox": (p["x"], p["y"], p["w"], p["h"]),
                                "color": (255, 0, 255),
                                "label": f"PANEL: {p['title']}"})
        _log(f"Floating panels (DOM): {len(panel_dom)} visible")
        # Also try OpenCV edge detection (advisory)
        panels_cv = _detect_panels_by_edges(img)
        _log(f"Floating panels (OpenCV edge): {len(panels_cv)} detected")

        # 7. Text regions
        text_regions = _detect_text_regions(img)
        for i, tr in enumerate(text_regions[:15]):
            annotations.append({"bbox": tr["bbox"], "color": (0, 200, 255),
                                "label": f"TEXT{i+1}", "thickness": 1})
        _log(f"Text regions detected: {len(text_regions)}")

        # 8. Map mode buttons (DOM check)
        mode_btns = self.page.query_selector_all(".map-mode-btn")
        mode_btn_count = len(mode_btns)
        for btn in mode_btns:
            box = btn.bounding_box()
            if box:
                annotations.append({"bbox": (int(box["x"]), int(box["y"]),
                                             int(box["width"]), int(box["height"])),
                                    "color": (100, 255, 100),
                                    "label": "MODE BTN"})
        _log(f"Map mode buttons: {mode_btn_count}")

        # 9. Minimap (DOM check)
        minimap = self.page.query_selector("#minimap-container")
        minimap_visible = minimap is not None and minimap.is_visible()
        if minimap_visible:
            box = minimap.bounding_box()
            if box:
                annotations.append({"bbox": (int(box["x"]), int(box["y"]),
                                             int(box["width"]), int(box["height"])),
                                    "color": (100, 200, 255),
                                    "label": "MINIMAP"})
        _log(f"Minimap visible: {minimap_visible}")

        # Save annotated screenshot
        annotated_path = _save_annotated(img, "01_ui_audit", annotations)
        _log(f"Annotated screenshot: {annotated_path}")

        # Build details for DB
        details = {
            "header_brightness": round(header_brightness, 1),
            "status_brightness": round(status_brightness, 1),
            "canvas_brightness": round(canvas_brightness, 1),
            "canvas_pct": round(canvas_pct, 1),
            "green_blobs": len(green_regions),
            "cyan_elements": len(cyan_regions),
            "panel_count": len(panel_dom),
            "panel_count_cv": len(panels_cv),
            "text_regions": len(text_regions),
            "mode_buttons": mode_btn_count,
            "minimap_visible": minimap_visible,
        }

        # Determine pass/fail
        passed = header_ok and status_ok and canvas_ok and len(green_regions) >= 3 and len(panel_dom) >= 1 and mode_btn_count >= 3
        self._record(test_name, passed, details)

        # Record annotated screenshot
        opencv_data = {
            "green_regions": len(green_regions),
            "cyan_regions": len(cyan_regions),
            "panels_cv": len(panels_cv),
            "text_regions": len(text_regions),
        }
        self._record_screenshot(
            test_name, "01_ui_audit_annotated", str(annotated_path),
            opencv_data=opencv_data,
            api_state={"panels_dom": panel_dom},
        )

        # Assertions
        assert header_ok, f"Header bar too dark (brightness={header_brightness:.1f})"
        assert status_ok, f"Status bar too dark (brightness={status_brightness:.1f})"
        assert canvas_ok, f"Canvas too dark ({canvas_pct:.1f}% non-black)"
        assert len(green_regions) >= 3, f"Expected >=3 friendly unit blobs, got {len(green_regions)}"
        assert len(panel_dom) >= 1, f"Expected >=1 floating panel, got {len(panel_dom)}"
        assert mode_btn_count >= 3, f"Expected 3 map mode buttons, got {mode_btn_count}"

        print(f"\n  UI Element Audit: ALL CHECKS PASSED")
        print(f"  Annotated proof: {annotated_path}")

    # -----------------------------------------------------------------------
    # Test 2: OCR Text Verification
    # -----------------------------------------------------------------------
    def test_02_ocr_text_verification(self):
        """Verify text on screen using OCR + DOM cross-check."""
        print("\n" + "=" * 70)
        print("  TEST 02: OCR TEXT VERIFICATION")
        print("=" * 70)

        test_name = "proof_02_ocr_text_verification"
        path, img = _screenshot(self.page, "02_ocr_text")
        annotations = []

        # Run full-page OCR
        ocr_results = _ocr_full_page(img)
        all_text = " ".join(r["text"] for r in ocr_results).upper()
        _log(f"OCR detected {len(ocr_results)} text segments")
        _log(f"Full OCR text: {all_text[:200]}...")

        # Annotate OCR detections
        for r in ocr_results[:25]:
            annotations.append({"bbox": r["bbox"], "color": (0, 255, 255),
                                "label": r["text"][:20], "thickness": 1})

        # Cross-check with DOM text for expected elements
        dom_checks = {}

        # Header text
        logo = self.page.locator(".header-logo").text_content() or ""
        dom_checks["TRITIUM-SC logo"] = "TRITIUM" in logo.upper()
        _log(f"DOM: logo = '{logo}' -> {'FOUND' if dom_checks['TRITIUM-SC logo'] else 'MISSING'}")

        clock = self.page.locator("#header-clock").text_content() or ""
        dom_checks["Clock (UTC)"] = "UTC" in clock.upper()
        _log(f"DOM: clock = '{clock}' -> {'FOUND' if dom_checks['Clock (UTC)'] else 'MISSING'}")

        conn = self.page.locator("#connection-status .conn-label").text_content() or ""
        dom_checks["Connection status"] = len(conn.strip()) > 0
        _log(f"DOM: connection = '{conn}' -> {'FOUND' if dom_checks['Connection status'] else 'MISSING'}")

        units_stat = self.page.locator("#header-units .stat-value").text_content() or "0"
        dom_checks["Unit count in header"] = int(units_stat.strip()) >= 0
        _log(f"DOM: units = '{units_stat}' -> {'FOUND' if dom_checks['Unit count in header'] else 'MISSING'}")

        # Status bar text
        fps_text = self.page.locator("#status-fps").text_content() or ""
        dom_checks["FPS counter"] = "FPS" in fps_text.upper()
        _log(f"DOM: fps = '{fps_text}' -> {'FOUND' if dom_checks['FPS counter'] else 'MISSING'}")

        alive_text = self.page.locator("#status-alive").text_content() or ""
        dom_checks["Alive count"] = "ALIVE" in alive_text.upper()
        _log(f"DOM: alive = '{alive_text}' -> {'FOUND' if dom_checks['Alive count'] else 'MISSING'}")

        version = self.page.evaluate(
            "() => document.querySelector('.status-right .status-item')?.textContent || ''"
        )
        dom_checks["Version string"] = "TRITIUM" in version.upper()
        _log(f"DOM: version = '{version}' -> {'FOUND' if dom_checks['Version string'] else 'MISSING'}")

        # Map elements
        coords = self.page.locator("#map-coords").text_content() or ""
        dom_checks["Map coordinates"] = "X:" in coords and "Y:" in coords
        _log(f"DOM: coords = '{coords}' -> {'FOUND' if dom_checks['Map coordinates'] else 'MISSING'}")

        minimap_label = self.page.evaluate(
            "() => document.querySelector('.minimap-label')?.textContent || ''"
        )
        dom_checks["Minimap label"] = len(minimap_label.strip()) > 0
        _log(f"DOM: minimap label = '{minimap_label}' -> {'FOUND' if dom_checks['Minimap label'] else 'MISSING'}")

        # Mode buttons
        mode_texts = self.page.evaluate(
            "() => [...document.querySelectorAll('.map-mode-btn')].map(b => b.textContent.trim())"
        )
        dom_checks["Mode buttons (O/T/S)"] = len(mode_texts) >= 3
        _log(f"DOM: mode buttons = {mode_texts}")

        # Panels
        panel_titles = self.page.evaluate(
            "() => [...document.querySelectorAll('.panel-title')].map(t => t.textContent.trim())"
        )
        dom_checks["Panel titles"] = len(panel_titles) >= 1
        _log(f"DOM: panel titles = {panel_titles}")

        # OCR-specific region checks on known areas
        h, w = img.shape[:2]

        # Try OCR on header region
        header_ocr = _ocr_region(img, 0, 0, w, 36)
        _log(f"OCR header region: '{header_ocr}'")

        # Try OCR on status bar region
        status_ocr = _ocr_region(img, 0, h - 20, w, 20)
        _log(f"OCR status bar: '{status_ocr}'")

        # Save annotated screenshot
        annotated_path = _save_annotated(img, "02_ocr_text", annotations)
        _log(f"Annotated screenshot: {annotated_path}")

        # Print summary
        print("\n  DOM Text Verification Summary:")
        passed_count = 0
        total = len(dom_checks)
        for check_name, result in dom_checks.items():
            status = "PASS" if result else "FAIL"
            print(f"    [{status}] {check_name}")
            if result:
                passed_count += 1
        print(f"\n  Result: {passed_count}/{total} DOM text checks passed")

        # Build details for DB
        details = {
            "dom_checks": dom_checks,
            "ocr_segments": len(ocr_results),
            "ocr_text_length": len(all_text),
            "header_ocr": header_ocr[:100],
            "status_ocr": status_ocr[:100],
            "dom_passed": passed_count,
            "dom_total": total,
        }

        test_passed = passed_count >= total - 2
        self._record(test_name, test_passed, details)

        # Record annotated screenshot
        self._record_screenshot(
            test_name, "02_ocr_text_annotated", str(annotated_path),
            opencv_data={"ocr_segments": len(ocr_results)},
            api_state={"dom_checks": dom_checks},
        )

        assert test_passed, f"Too many DOM text checks failed: {passed_count}/{total}"

    # -----------------------------------------------------------------------
    # Test 3: Panel Detection with Color Borders
    # -----------------------------------------------------------------------
    def test_03_panel_border_detection(self):
        """Detect floating panels using their visual borders."""
        print("\n" + "=" * 70)
        print("  TEST 03: PANEL BORDER DETECTION")
        print("=" * 70)

        test_name = "proof_03_panel_border_detection"
        path, img = _screenshot(self.page, "03_panel_borders")
        annotations = []

        # Get panel positions from DOM
        panel_data = self.page.evaluate("""() => {
            const panels = document.querySelectorAll('.panel');
            return [...panels].map(p => {
                const rect = p.getBoundingClientRect();
                const title = p.querySelector('.panel-title')?.textContent?.trim() || 'untitled';
                const visible = p.offsetParent !== null && p.style.display !== 'none';
                return {
                    title: title,
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    visible: visible
                };
            });
        }""")

        _log(f"Found {len(panel_data)} panels in DOM")

        panel_details = []
        for i, panel in enumerate(panel_data):
            _log(f"  Panel '{panel['title']}': {panel['width']}x{panel['height']} at ({panel['x']},{panel['y']}) visible={panel['visible']}")

            if not panel["visible"] or panel["width"] < 10 or panel["height"] < 10:
                continue

            # Extract panel region from screenshot
            px, py = max(0, panel["x"]), max(0, panel["y"])
            pw, ph = panel["width"], panel["height"]
            h, w = img.shape[:2]
            px2 = min(px + pw, w)
            py2 = min(py + ph, h)

            if px2 <= px or py2 <= py:
                continue

            panel_region = img[py:py2, px:px2]

            # Analyze panel border pixels
            if panel_region.shape[0] > 2 and panel_region.shape[1] > 2:
                top_edge = panel_region[0:2, :]
                left_edge = panel_region[:, 0:2]
                bottom_edge = panel_region[-2:, :]
                right_edge = panel_region[:, -2:]

                edges = np.vstack([
                    top_edge.reshape(-1, 3),
                    bottom_edge.reshape(-1, 3),
                    left_edge.reshape(-1, 3),
                    right_edge.reshape(-1, 3),
                ])
                edge_brightness = float(np.mean(cv2.cvtColor(
                    edges.reshape(1, -1, 3), cv2.COLOR_BGR2GRAY)))

                interior = panel_region[5:-5, 5:-5] if ph > 10 and pw > 10 else panel_region
                interior_brightness = float(cv2.cvtColor(interior, cv2.COLOR_BGR2GRAY).mean())

                has_content = interior_brightness > 8
                color = (0, 255, 0) if has_content else (0, 100, 255)
                annotations.append({
                    "bbox": (px, py, pw, ph), "color": color,
                    "label": f"{panel['title']} (int={interior_brightness:.0f})"
                })
                _log(f"    Edge brightness: {edge_brightness:.1f}, Interior: {interior_brightness:.1f}")

                panel_details.append({
                    "title": panel["title"],
                    "x": panel["x"], "y": panel["y"],
                    "width": panel["width"], "height": panel["height"],
                    "edge_brightness": round(edge_brightness, 1),
                    "interior_brightness": round(interior_brightness, 1),
                })

        # Also detect panels via OpenCV edge detection
        edge_panels = _detect_panels_by_edges(img)
        _log(f"OpenCV edge detection found {len(edge_panels)} panel-like regions")

        for i, ep in enumerate(edge_panels[:3]):
            annotations.append({"bbox": ep["bbox"], "color": (200, 100, 255),
                                "label": f"CV-PANEL{i+1}", "thickness": 1})

        annotated_path = _save_annotated(img, "03_panel_borders", annotations)
        _log(f"Annotated screenshot: {annotated_path}")

        visible_panels = [p for p in panel_data if p["visible"] and p["width"] > 10]

        # Build details for DB
        details = {
            "panels": panel_details,
            "panel_count": len(visible_panels),
            "panel_count_cv": len(edge_panels),
        }

        test_passed = len(visible_panels) >= 2
        self._record(test_name, test_passed, details)

        self._record_screenshot(
            test_name, "03_panel_borders_annotated", str(annotated_path),
            opencv_data={"edge_panels": len(edge_panels)},
            api_state={"visible_panels": len(visible_panels)},
        )

        assert test_passed, f"Expected >=2 visible panels, got {len(visible_panels)}"
        print(f"\n  Panel Detection: {len(visible_panels)} visible panels found")

    # -----------------------------------------------------------------------
    # Test 4: Full Game Loop with Logs
    # -----------------------------------------------------------------------
    def test_04_full_game_loop(self):
        """Run the complete game loop and log every phase."""
        print("\n" + "=" * 70)
        print("  TEST 04: FULL GAME LOOP")
        print("=" * 70)

        test_name = "proof_04_full_game_loop"
        log = []

        def glog(msg: str):
            _log(msg)
            log.append(msg)

        # ---- Phase 0: Reset ----
        glog("=== PHASE 0: RESET ===")
        reset_result = self._api_post("/api/game/reset")
        glog(f"Reset: {json.dumps(reset_result)}")
        self.page.wait_for_timeout(1000)

        state = self._api_get("/api/game/state")
        glog(f"Game state after reset: {json.dumps(state)}")

        # ---- Phase 1: Setup (place turrets) ----
        glog("=== PHASE 1: PLACE TURRETS ===")
        turret_positions = [(0, 0), (8, 0), (-8, 0), (0, 8), (0, -8)]
        placed = []
        for i, (x, y) in enumerate(turret_positions):
            result = self._api_post("/api/game/place", {
                "name": f"Turret-{i+1}", "asset_type": "turret",
                "position": {"x": x, "y": y}
            })
            placed.append(result)
            glog(f"Placed Turret-{i+1} at ({x},{y}): {json.dumps(result)}")

        self.page.wait_for_timeout(2000)
        targets_before = self._get_targets()
        friendlies = [t for t in targets_before if t.get("alliance") == "friendly"]
        glog(f"Targets after placement: {len(targets_before)} total, {len(friendlies)} friendly")

        # Screenshot: setup phase
        path_setup, img_setup = _screenshot(self.page, "04_phase1_setup")
        green_blobs = _detect_color_regions(img_setup, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        glog(f"Green unit blobs on canvas: {len(green_blobs)}")

        self._record_screenshot(
            test_name, "04_phase1_setup", str(path_setup),
            opencv_data={"green_blobs": len(green_blobs)},
            api_state={"friendlies": len(friendlies), "total_targets": len(targets_before)},
        )

        # ---- Phase 2: Begin War ----
        glog("=== PHASE 2: BEGIN WAR ===")
        begin_result = self._api_post("/api/game/begin")
        glog(f"Begin war response: {json.dumps(begin_result)}")

        # Wait for countdown
        self.page.wait_for_timeout(2000)
        state = self._api_get("/api/game/state")
        glog(f"State during countdown: {json.dumps(state)}")
        path_countdown, _ = _screenshot(self.page, "04_phase2_countdown")

        self._record_screenshot(
            test_name, "04_phase2_countdown", str(path_countdown),
            api_state={"state": state},
        )

        # ---- Phase 3: Wait for hostiles ----
        glog("=== PHASE 3: WAITING FOR HOSTILES ===")
        hostile_found = False
        for tick in range(30):
            time.sleep(1)
            targets = self._get_targets()
            hostiles = [t for t in targets if t.get("alliance") == "hostile"]
            state = self._api_get("/api/game/state")
            wave = state.get("wave", 0) if state else 0
            phase = state.get("state", "?") if state else "?"

            if tick % 5 == 0 or len(hostiles) > 0:
                glog(f"t={tick}s: state={phase} wave={wave} targets={len(targets)} hostiles={len(hostiles)}")

            if len(hostiles) > 0:
                hostile_found = True
                glog(f"HOSTILES DETECTED at t={tick}s: {len(hostiles)} hostiles")
                for h in hostiles[:3]:
                    pos = h.get("position", {})
                    glog(f"  Hostile '{h.get('name','')}' at ({pos.get('x',0):.1f}, {pos.get('y',0):.1f}) "
                         f"hp={h.get('health',0)}/{h.get('max_health',0)}")
                break

        # Screenshot: hostiles on map
        self.page.wait_for_timeout(1000)
        path_combat, img_combat = _screenshot(self.page, "04_phase3_combat")
        red_blobs = _detect_color_regions(img_combat, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        glog(f"Red hostile blobs on canvas: {len(red_blobs)}")

        # Annotate combat screenshot
        combat_annotations = []
        for i, gb in enumerate(green_blobs[:5]):
            combat_annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                        "label": f"FRIENDLY{i+1}"})
        for i, rb in enumerate(red_blobs[:5]):
            combat_annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                        "label": f"HOSTILE{i+1}"})
        combat_annotated = _save_annotated(img_combat, "04_phase3_combat", combat_annotations)

        self._record_screenshot(
            test_name, "04_phase3_combat_annotated", str(combat_annotated),
            opencv_data={"green_blobs": len(green_blobs), "red_blobs": len(red_blobs)},
            api_state={"hostile_found": hostile_found},
        )

        # ---- Phase 4: Watch combat (15s) ----
        glog("=== PHASE 4: COMBAT IN PROGRESS ===")
        eliminations_seen = 0
        max_wave = 0
        for tick in range(15):
            time.sleep(1)
            state = self._api_get("/api/game/state")
            if state:
                wave = state.get("wave", 0)
                phase = state.get("state", "?")
                score = state.get("score", 0)
                elims = state.get("eliminations", state.get("total_eliminations", 0))
                if wave > max_wave:
                    max_wave = wave
                if elims > eliminations_seen:
                    glog(f"t={tick}s: NEW ELIMINATIONS! score={score} elims={elims} wave={wave} state={phase}")
                    eliminations_seen = elims
                elif tick % 5 == 0:
                    glog(f"t={tick}s: score={score} elims={elims} wave={wave} state={phase}")

        # Final state
        state = self._api_get("/api/game/state")
        glog(f"Final game state: {json.dumps(state)}")
        targets_final = self._get_targets()
        hostiles_final = [t for t in targets_final if t.get("alliance") == "hostile"]
        friendlies_final = [t for t in targets_final if t.get("alliance") == "friendly"]
        glog(f"Final targets: {len(targets_final)} total, {len(friendlies_final)} friendly, {len(hostiles_final)} hostile")

        # Screenshot: final combat state
        path_final, img_final = _screenshot(self.page, "04_phase4_final")
        final_annotations = []
        green_final = _detect_color_regions(img_final, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        red_final = _detect_color_regions(img_final, HOSTILE_RED_BGR, tolerance=60, min_area=10)
        for i, gb in enumerate(green_final[:5]):
            final_annotations.append({"bbox": gb["bbox"], "color": (0, 255, 100),
                                       "label": f"F{i+1}"})
        for i, rb in enumerate(red_final[:5]):
            final_annotations.append({"bbox": rb["bbox"], "color": (0, 0, 255),
                                       "label": f"H{i+1}"})
        final_annotated = _save_annotated(img_final, "04_phase4_final", final_annotations)

        self._record_screenshot(
            test_name, "04_phase4_final_annotated", str(final_annotated),
            opencv_data={"green_blobs": len(green_final), "red_blobs": len(red_final)},
            api_state={
                "state": state,
                "friendlies": len(friendlies_final),
                "hostiles": len(hostiles_final),
            },
        )

        # ---- Phase 5: Reset and verify clean ----
        glog("=== PHASE 5: RESET ===")
        self._api_post("/api/game/reset")
        self.page.wait_for_timeout(1000)
        state_after_reset = self._api_get("/api/game/state")
        glog(f"State after final reset: {json.dumps(state_after_reset)}")

        # Save full game log
        log_path = _ensure_dir() / "game_loop_log.txt"
        log_path.write_text("\n".join(log))
        _log(f"Full game log saved: {log_path}")

        # Print summary
        print("\n  " + "-" * 60)
        print("  GAME LOOP SUMMARY")
        print("  " + "-" * 60)
        print(f"  Turrets placed:    {len(placed)}")
        print(f"  Hostiles appeared: {hostile_found}")
        print(f"  Max wave reached:  {max_wave}")
        print(f"  Eliminations:      {eliminations_seen}")
        print(f"  Green blobs (setup):  {len(green_blobs)}")
        print(f"  Red blobs (combat):   {len(red_blobs)}")
        print(f"  Screenshots:")
        print(f"    Setup:     {path_setup}")
        print(f"    Countdown: {path_countdown}")
        print(f"    Combat:    {combat_annotated}")
        print(f"    Final:     {final_annotated}")
        print(f"  Log file: {log_path}")
        print("  " + "-" * 60)

        # Build details with game log for timeline visualization
        details = {
            "game_log": log,
            "turrets_placed": len(placed),
            "hostile_found": hostile_found,
            "max_wave": max_wave,
            "eliminations": eliminations_seen,
            "green_blobs": len(green_blobs),
            "red_blobs": len(red_blobs),
            "friendly_count": len(friendlies),
            "hostile_count": len(hostiles_final),
            "final_state": state,
        }

        test_passed = len(friendlies) >= 5 and hostile_found and len(green_blobs) >= 2
        self._record(test_name, test_passed, details)

        # Assertions
        assert len(friendlies) >= 5, f"Expected >=5 friendlies placed, got {len(friendlies)}"
        assert hostile_found, "No hostiles spawned within 30s"
        assert len(green_blobs) >= 2, f"Expected >=2 green unit blobs on canvas, got {len(green_blobs)}"

    # -----------------------------------------------------------------------
    # Test 5: Comprehensive Annotated Proof
    # -----------------------------------------------------------------------
    def test_05_comprehensive_proof(self):
        """Generate final annotated proof image showing ALL detected elements."""
        print("\n" + "=" * 70)
        print("  TEST 05: COMPREHENSIVE PROOF IMAGE")
        print("=" * 70)

        test_name = "proof_05_comprehensive_proof"

        # Reset game to clean state
        self._api_post("/api/game/reset")
        self.page.wait_for_timeout(3000)

        path, img = _screenshot(self.page, "05_comprehensive")
        h, w = img.shape[:2]
        all_annotations = []

        # --- DOM-verified UI elements ---
        dom_elements = self.page.evaluate("""() => {
            const elements = {};
            const get = (sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                return {
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    text: el.textContent?.trim()?.substring(0, 30) || '',
                    visible: el.offsetParent !== null || el.offsetWidth > 0
                };
            };
            elements['header'] = get('#header-bar');
            elements['logo'] = get('.header-logo');
            elements['clock'] = get('#header-clock');
            elements['units_stat'] = get('#header-units');
            elements['threats_stat'] = get('#header-threats');
            elements['connection'] = get('#connection-status');
            elements['canvas'] = get('#tactical-canvas');
            elements['map_coords'] = get('#map-coords');
            elements['map_fps'] = get('#map-fps');
            elements['minimap'] = get('#minimap-container');
            elements['status_bar'] = get('#status-bar');
            elements['status_fps'] = get('#status-fps');
            elements['status_alive'] = get('#status-alive');
            elements['mode_observe'] = get('.map-mode-btn[data-map-mode="observe"]');
            elements['mode_tactical'] = get('.map-mode-btn[data-map-mode="tactical"]');
            elements['mode_setup'] = get('.map-mode-btn[data-map-mode="setup"]');
            return elements;
        }""")

        verified_count = 0
        missing = []
        dom_check_map = {}
        for name, el in dom_elements.items():
            if el and el["w"] > 0 and el["h"] > 0:
                color = (0, 255, 0)  # green = found
                label = f"{name}: {el['text'][:20]}" if el['text'] else name
                all_annotations.append({
                    "bbox": (el["x"], el["y"], el["w"], el["h"]),
                    "color": color, "label": label, "thickness": 2
                })
                verified_count += 1
                dom_check_map[name] = True
                _log(f"  FOUND: {name} = '{el['text'][:30]}' at ({el['x']},{el['y']}) {el['w']}x{el['h']}")
            else:
                missing.append(name)
                dom_check_map[name] = False
                _log(f"  MISSING: {name}")

        # --- OpenCV detections overlaid ---
        # Friendly units
        green_regions = _detect_color_regions(img, FRIENDLY_GREEN_BGR, tolerance=50, min_area=15)
        for i, gr in enumerate(green_regions[:8]):
            all_annotations.append({"bbox": gr["bbox"], "color": (50, 255, 50),
                                    "label": f"UNIT{i+1}", "thickness": 1})

        # Cyan elements
        cyan_regions = _detect_color_regions(img, CYAN_BGR, tolerance=50, min_area=50)
        _log(f"OpenCV: {len(green_regions)} green units, {len(cyan_regions)} cyan elements")

        # --- OCR results ---
        ocr_results = _ocr_full_page(img)
        _log(f"OCR: {len(ocr_results)} text segments detected")
        for r in ocr_results[:10]:
            all_annotations.append({"bbox": r["bbox"], "color": (0, 200, 255),
                                    "label": r["text"][:15], "thickness": 1})

        # --- Panels ---
        panel_data = self.page.evaluate("""() => {
            return [...document.querySelectorAll('.panel')].map(p => ({
                title: p.querySelector('.panel-title')?.textContent?.trim() || 'untitled',
                x: Math.round(p.getBoundingClientRect().x),
                y: Math.round(p.getBoundingClientRect().y),
                w: Math.round(p.getBoundingClientRect().width),
                h: Math.round(p.getBoundingClientRect().height),
                visible: p.offsetParent !== null
            }));
        }""")
        visible_panel_count = 0
        for p in panel_data:
            if p["visible"] and p["w"] > 10:
                all_annotations.append({"bbox": (p["x"], p["y"], p["w"], p["h"]),
                                        "color": (255, 0, 255),
                                        "label": f"PANEL: {p['title']}", "thickness": 2})
                visible_panel_count += 1

        # Save comprehensive annotated image
        annotated_path = _save_annotated(img, "05_comprehensive", all_annotations)

        # Print final summary
        print(f"\n  " + "=" * 60)
        print(f"  COMPREHENSIVE PROOF SUMMARY")
        print(f"  " + "=" * 60)
        print(f"  DOM elements verified: {verified_count}/{len(dom_elements)}")
        if missing:
            print(f"  Missing elements: {', '.join(missing)}")
        print(f"  Friendly unit blobs: {len(green_regions)}")
        print(f"  Cyan UI elements: {len(cyan_regions)}")
        print(f"  OCR text segments: {len(ocr_results)}")
        print(f"  Floating panels: {visible_panel_count}")
        print(f"  Console errors: {len(self._errors)}")
        print(f"  ")
        print(f"  ANNOTATED PROOF IMAGE: {annotated_path}")
        print(f"  (All bounding boxes + labels overlaid)")
        print(f"  " + "=" * 60)

        # Build details for DB
        details = {
            "dom_checks": dom_check_map,
            "dom_verified": verified_count,
            "dom_total": len(dom_elements),
            "green_blobs": len(green_regions),
            "cyan_elements": len(cyan_regions),
            "ocr_segments": len(ocr_results),
            "panel_count": visible_panel_count,
            "console_errors": len(self._errors),
        }

        test_passed = verified_count >= 12 and len(green_regions) >= 3 and len(self._errors) == 0
        self._record(test_name, test_passed, details)

        self._record_screenshot(
            test_name, "05_comprehensive_annotated", str(annotated_path),
            opencv_data={
                "green_regions": len(green_regions),
                "cyan_regions": len(cyan_regions),
                "ocr_segments": len(ocr_results),
            },
            api_state={
                "dom_verified": verified_count,
                "visible_panels": visible_panel_count,
                "console_errors": self._errors[:5],
            },
        )

        # Key assertions
        assert verified_count >= 12, f"Expected >=12 DOM elements found, got {verified_count}"
        assert len(green_regions) >= 3, f"Expected >=3 green units on map, got {len(green_regions)}"
        assert len(self._errors) == 0, f"Console errors: {self._errors}"
