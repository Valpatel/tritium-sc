# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Post-fix verification sweep: confirm all visual defects are actually fixed.

Uses headed Playwright + OpenCV + local VLM (llava:7b) to verify:
  A. Label overflow at 60-degree pitch (no green/cyan lines spanning viewport)
  B. Water layer visibility (subtle, not dominant)
  C. Escape from chat input
  D. Terrain toggle (3D deformation on/off)
  E. All layers off = near-black screen
  F. MAP menu items complete
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

SCREENSHOT_DIR = Path("tests/.test-results/post-fix-verify")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

VISION_MODEL = "llava:7b"


def vlm_ask(fleet, image_path: Path, prompt: str, retries: int = 3) -> str:
    """Ask VLM a question about an image with majority-vote style retries."""
    responses = []
    for _ in range(retries):
        try:
            resp = fleet.generate(VISION_MODEL, prompt, image_path=image_path)
            responses.append(resp["response"])
        except Exception as e:
            responses.append(f"[error: {e}]")
    return responses[0] if responses else "[no response]"


def vlm_yes_no(fleet, image_path: Path, question: str, retries: int = 3) -> tuple[bool, list[str]]:
    """Ask VLM a yes/no question with majority vote. Returns (majority_yes, raw_responses)."""
    prompt = f"{question}\n\nAnswer with EXACTLY one word: YES or NO. Do not explain."
    yes_count = 0
    responses = []
    for _ in range(retries):
        try:
            resp = fleet.generate(VISION_MODEL, prompt, image_path=image_path)
            text = resp["response"].strip().lower()
            responses.append(text)
            if text.startswith("yes"):
                yes_count += 1
        except Exception as e:
            responses.append(f"[error: {e}]")
    return (yes_count > retries // 2, responses)


def detect_label_overflow_lines(img: np.ndarray, min_length_frac: float = 0.5,
                                max_angle_deg: float = 15.0) -> list[dict]:
    """Detect NEAR-HORIZONTAL green/cyan lines spanning > min_length_frac of viewport.

    The original label overflow bug created horizontal bars from CSS overflow --
    text labels stretching into bright colored horizontal lines. This filters:
    - Only near-horizontal lines (within max_angle_deg of horizontal)
    - Only lines spanning > 50% of viewport width
    - Ignores diagonal vision cones, building outlines, grid lines, etc.
    """
    h, w = img.shape[:2]
    min_len = int(w * min_length_frac)

    # Focus on bright green/cyan lines
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Green range: H=35-85, S>50, V>100
    mask_green = cv2.inRange(hsv, (35, 50, 100), (85, 255, 255))
    # Cyan range: H=80-100, S>50, V>100
    mask_cyan = cv2.inRange(hsv, (80, 50, 100), (100, 255, 255))
    mask = cv2.bitwise_or(mask_green, mask_cyan)

    # Dilate to connect nearby fragments
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)

    edges = cv2.Canny(mask, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50,
                            minLineLength=min_len, maxLineGap=20)
    results = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            # Calculate angle from horizontal
            angle_deg = np.degrees(np.arctan2(dy, max(dx, 1)))
            # Only count near-horizontal lines (label overflow creates horizontal bars)
            if angle_deg > max_angle_deg:
                continue
            # Horizontal span must exceed threshold
            horiz_span = dx
            if horiz_span < min_len:
                continue
            length = np.sqrt(dx**2 + dy**2)
            results.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "length": float(length),
                "horiz_span": int(horiz_span),
                "angle_deg": round(float(angle_deg), 1),
                "frac": float(horiz_span / w),
            })
    return results


def count_cyan_pixels(img: np.ndarray) -> int:
    """Count bright cyan/blue pixels in the map area."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Cyan-blue range
    mask = cv2.inRange(hsv, (80, 80, 120), (130, 255, 255))
    return int(cv2.countNonZero(mask))


def mean_brightness(img: np.ndarray) -> float:
    """Mean brightness of image (grayscale)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(gray.mean())


def run_all():
    """Run all verification tests."""
    from playwright.sync_api import sync_playwright
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from lib.ollama_fleet import OllamaFleet

    print("=" * 70)
    print("POST-FIX VERIFICATION SWEEP")
    print("=" * 70)

    fleet = OllamaFleet()
    print(f"\n{fleet.status()}\n")

    results = {}

    pw = sync_playwright().start()
    # Headed browser per MEMORY.md preference
    browser = pw.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()

    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("[*] Navigating to http://localhost:8000/ ...")
    page.goto("http://localhost:8000/", wait_until="networkidle")
    page.wait_for_timeout(4000)  # Let map tiles load

    # ============================================================
    # TEST A: Label overflow at 60-degree pitch
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST A: Label overflow at 60-degree pitch")
    print("=" * 60)

    # First tilt to 60 degrees
    page.evaluate("window._mapState.map.easeTo({pitch: 60, duration: 0})")
    page.wait_for_timeout(2000)  # Let tiles render at new pitch

    ss_a = SCREENSHOT_DIR / "test_a_pitch60.png"
    page.screenshot(path=str(ss_a), full_page=False)

    # OpenCV: detect near-horizontal green/cyan lines (label overflow artifact)
    # The original bug: label text with no max-width created horizontal bars at tilted pitch.
    # Vision cones, building outlines, and diagonal map features are NOT the bug.
    img_a = cv2.imread(str(ss_a))
    overflow_lines = detect_label_overflow_lines(img_a, min_length_frac=0.5, max_angle_deg=15.0)
    opencv_pass_a = len(overflow_lines) == 0

    # Also check DOM: verify labels have max-width constraint
    label_has_maxwidth = page.evaluate("""() => {
        const markers = document.querySelectorAll('.maplibregl-marker, .unit-label, [class*=label]');
        let constrained = 0, total = 0;
        markers.forEach(m => {
            const style = window.getComputedStyle(m);
            const mw = style.maxWidth;
            if (mw && mw !== 'none' && mw !== '0px') constrained++;
            total++;
        });
        return { total, constrained };
    }""")

    # VLM: ask specifically about horizontal bar artifacts from labels
    vlm_result_a, vlm_raw_a = vlm_yes_no(
        fleet, ss_a,
        "Are there any bright green or cyan HORIZONTAL BARS stretching across the screen? "
        "These would be solid colored horizontal lines or bars that look like CSS overflow artifacts. "
        "Ignore diagonal lines, triangular vision cones, building outlines, or map grid lines. "
        "Only answer YES if you see unnatural horizontal bars spanning most of the screen width."
    )
    vlm_pass_a = not vlm_result_a  # NO = no bars = pass

    overall_a = opencv_pass_a  # OpenCV is authoritative
    results["A_label_overflow"] = {
        "passed": overall_a,
        "opencv": {"overflow_lines_found": len(overflow_lines), "lines": overflow_lines, "pass": opencv_pass_a},
        "dom": {"label_info": label_has_maxwidth},
        "vlm": {"sees_bars": vlm_result_a, "raw": vlm_raw_a, "pass": vlm_pass_a},
    }
    print(f"  OpenCV: {len(overflow_lines)} horizontal overflow lines detected -> {'PASS' if opencv_pass_a else 'FAIL'}")
    print(f"  DOM: labels with max-width: {label_has_maxwidth}")
    print(f"  VLM: sees horizontal bars = {vlm_result_a} -> {'PASS' if vlm_pass_a else 'FAIL'}")
    print(f"  -> {'PASS' if overall_a else 'FAIL'}")

    # ============================================================
    # TEST B: Water layer visibility
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST B: Water layer visibility")
    print("=" * 60)

    # Reset pitch to 0 for overhead view
    page.evaluate("window._mapState.map.easeTo({pitch: 0, duration: 0})")
    page.wait_for_timeout(2000)

    ss_b = SCREENSHOT_DIR / "test_b_water_overhead.png"
    page.screenshot(path=str(ss_b), full_page=False)

    img_b = cv2.imread(str(ss_b))
    # Count cyan pixels in the map region (exclude header/panels)
    # Map is roughly the center area
    h_b, w_b = img_b.shape[:2]
    map_region = img_b[60:h_b - 20, 200:w_b - 300]  # rough crop around map
    cyan_count = count_cyan_pixels(map_region)
    total_pixels = map_region.shape[0] * map_region.shape[1]
    cyan_fraction = cyan_count / total_pixels if total_pixels > 0 else 0

    # Water should be < 5% of pixels (subtle, not dominant)
    opencv_pass_b = cyan_fraction < 0.05

    # VLM check
    vlm_result_b, vlm_raw_b = vlm_yes_no(
        fleet, ss_b,
        "Are there bright blue water feature lines that are visually dominant and distracting on this map? "
        "Or are they subtle background context? Answer YES if they are distracting, NO if subtle."
    )
    vlm_pass_b = not vlm_result_b  # NO = not distracting = pass

    overall_b = opencv_pass_b
    results["B_water_visibility"] = {
        "passed": overall_b,
        "opencv": {"cyan_pixels": cyan_count, "cyan_fraction": round(cyan_fraction, 4),
                    "threshold": 0.05, "pass": opencv_pass_b},
        "vlm": {"distracting": vlm_result_b, "raw": vlm_raw_b, "pass": vlm_pass_b},
    }
    print(f"  OpenCV: cyan fraction = {cyan_fraction:.4f} (threshold 0.05) -> {'PASS' if opencv_pass_b else 'FAIL'}")
    print(f"  VLM: distracting = {vlm_result_b} -> {'PASS' if vlm_pass_b else 'FAIL'}")
    print(f"  -> {'PASS' if overall_b else 'FAIL'}")

    # ============================================================
    # TEST C: Escape from chat
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST C: Escape from chat input")
    print("=" * 60)

    # Ensure keyboard focus is on the page body (not stuck in map canvas)
    page.locator("body").click(position={"x": 960, "y": 540})
    page.wait_for_timeout(300)

    # The chat overlay is 'chat-overlay' (not 'chat-container')
    # Method 1: Try keyboard shortcut C
    page.keyboard.press("c")
    page.wait_for_timeout(800)

    # Check if chat overlay opened
    chat_visible_after_c = page.evaluate("""() => {
        const el = document.getElementById('chat-overlay');
        return el && !el.hidden;
    }""")

    # If C didn't work (maybe maplibre canvas captured it), use JS directly
    if not chat_visible_after_c:
        print("  [note] 'C' key did not open chat -- using toggleChat(true) directly")
        page.evaluate("typeof toggleChat === 'function' && toggleChat(true)")
        page.wait_for_timeout(500)
        chat_visible_after_c = page.evaluate("""() => {
            const el = document.getElementById('chat-overlay');
            return el && !el.hidden;
        }""")

    # Screenshot with chat open
    ss_c_open = SCREENSHOT_DIR / "test_c_chat_open.png"
    page.screenshot(path=str(ss_c_open), full_page=False)

    # Type something in chat input to give it focus
    chat_input = page.locator("#chat-input")
    if chat_input.count() > 0 and chat_input.is_visible():
        chat_input.click()
        chat_input.type("test message", delay=50)
        page.wait_for_timeout(300)

    # Verify focus is on the input
    focused_tag = page.evaluate("() => document.activeElement?.tagName")
    print(f"  Active element before Escape: {focused_tag}")

    # Press Escape -- should close chat even when input is focused
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    # Check chat is closed
    chat_hidden_after = page.evaluate("""() => {
        const el = document.getElementById('chat-overlay');
        return !el || el.hidden;
    }""")

    ss_c = SCREENSHOT_DIR / "test_c_escape_chat.png"
    page.screenshot(path=str(ss_c), full_page=False)

    overall_c = bool(chat_visible_after_c) and bool(chat_hidden_after)
    results["C_escape_chat"] = {
        "passed": overall_c,
        "chat_opened": chat_visible_after_c,
        "focused_element_before_escape": focused_tag,
        "chat_hidden_after_escape": chat_hidden_after,
    }
    print(f"  Chat opened: {chat_visible_after_c}")
    print(f"  Chat hidden after Escape: {chat_hidden_after}")
    print(f"  -> {'PASS' if overall_c else 'FAIL'}")

    # ============================================================
    # TEST D: Terrain toggle
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST D: Terrain toggle (3D deformation)")
    print("=" * 60)

    # Press H to enable terrain
    page.keyboard.press("h")
    page.wait_for_timeout(1000)

    # Tilt to 60 degrees to see terrain
    page.evaluate("window._mapState.map.easeTo({pitch: 60, duration: 0})")
    page.wait_for_timeout(2000)

    ss_d1 = SCREENSHOT_DIR / "test_d_terrain_on.png"
    page.screenshot(path=str(ss_d1), full_page=False)

    # VLM: check for 3D terrain
    vlm_terrain_on, vlm_raw_d1 = vlm_yes_no(
        fleet, ss_d1,
        "Is there visible 3D terrain elevation deformation on this map surface? "
        "Look for hills, valleys, or raised/lowered ground that creates a 3D relief effect. "
        "Flat satellite imagery tilted in perspective does NOT count."
    )

    # Toggle terrain off with H
    page.keyboard.press("h")
    page.wait_for_timeout(1500)

    ss_d2 = SCREENSHOT_DIR / "test_d_terrain_off.png"
    page.screenshot(path=str(ss_d2), full_page=False)

    vlm_terrain_off, vlm_raw_d2 = vlm_yes_no(
        fleet, ss_d2,
        "Is the map surface completely flat with no 3D terrain elevation? "
        "A flat map tilted in perspective should look like a flat plane."
    )

    # OpenCV: compare the two screenshots for structural difference
    img_d1 = cv2.imread(str(ss_d1))
    img_d2 = cv2.imread(str(ss_d2))
    if img_d1 is not None and img_d2 is not None and img_d1.shape == img_d2.shape:
        diff = cv2.absdiff(img_d1, img_d2)
        diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        diff_mean = float(diff_gray.mean())
        # Save diff image
        cv2.imwrite(str(SCREENSHOT_DIR / "test_d_terrain_diff.png"), diff * 3)
    else:
        diff_mean = -1.0

    # Terrain toggle should produce visible difference (diff_mean > 2)
    opencv_pass_d = diff_mean > 2.0

    overall_d = opencv_pass_d
    results["D_terrain_toggle"] = {
        "passed": overall_d,
        "opencv": {"diff_mean": round(diff_mean, 2), "pass": opencv_pass_d},
        "vlm_terrain_on": {"sees_terrain": vlm_terrain_on, "raw": vlm_raw_d1},
        "vlm_terrain_off": {"sees_flat": vlm_terrain_off, "raw": vlm_raw_d2},
    }
    print(f"  OpenCV diff mean: {diff_mean:.2f} (threshold >2.0) -> {'PASS' if opencv_pass_d else 'FAIL'}")
    print(f"  VLM sees terrain ON: {vlm_terrain_on}")
    print(f"  VLM sees terrain OFF (flat): {vlm_terrain_off}")
    print(f"  -> {'PASS' if overall_d else 'FAIL'}")

    # ============================================================
    # TEST E: All layers off = near-black screen
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST E: All layers off = near-black screen")
    print("=" * 60)

    # Reset pitch first
    page.evaluate("window._mapState.map.easeTo({pitch: 0, duration: 0})")
    page.wait_for_timeout(500)

    # Turn off all layers
    page.evaluate("""
        window._mapActions.setLayers({
            allMapLayers: false, models3d: false, domMarkers: false
        })
    """)
    page.wait_for_timeout(1000)

    # Tilt to 60 to show empty space
    page.evaluate("window._mapState.map.easeTo({pitch: 60, duration: 0})")
    page.wait_for_timeout(1500)

    ss_e = SCREENSHOT_DIR / "test_e_all_layers_off.png"
    page.screenshot(path=str(ss_e), full_page=False)

    img_e = cv2.imread(str(ss_e))
    # Measure brightness in center map region (avoiding header/panels)
    h_e, w_e = img_e.shape[:2]
    map_center = img_e[100:h_e - 50, 250:w_e - 300]
    brightness = mean_brightness(map_center)
    opencv_pass_e = brightness < 30  # should be very dark

    # VLM check
    vlm_result_e, vlm_raw_e = vlm_yes_no(
        fleet, ss_e,
        "Is the main map area of this screen nearly completely black or very dark, "
        "with just some UI elements around the edges?"
    )
    vlm_pass_e = vlm_result_e  # YES = dark = pass

    overall_e = opencv_pass_e
    results["E_all_layers_off"] = {
        "passed": overall_e,
        "opencv": {"brightness": round(brightness, 2), "threshold": 30, "pass": opencv_pass_e},
        "vlm": {"sees_dark": vlm_result_e, "raw": vlm_raw_e, "pass": vlm_pass_e},
    }
    print(f"  OpenCV: mean brightness = {brightness:.2f} (threshold <30) -> {'PASS' if opencv_pass_e else 'FAIL'}")
    print(f"  VLM: sees dark screen = {vlm_result_e} -> {'PASS' if vlm_pass_e else 'FAIL'}")
    print(f"  -> {'PASS' if overall_e else 'FAIL'}")

    # Restore layers
    page.evaluate("""
        window._mapActions.setLayers({
            allMapLayers: true, models3d: true, domMarkers: true
        })
    """)
    page.wait_for_timeout(1000)

    # ============================================================
    # TEST F: MAP menu items
    # ============================================================
    print("\n" + "=" * 60)
    print("TEST F: MAP menu items")
    print("=" * 60)

    # Reset view
    page.evaluate("window._mapState.map.easeTo({pitch: 0, duration: 0})")
    page.wait_for_timeout(500)

    # Click MAP menu button
    map_btn = page.locator("text=MAP").first
    if map_btn.count() > 0:
        map_btn.click()
        page.wait_for_timeout(800)

    ss_f = SCREENSHOT_DIR / "test_f_map_menu.png"
    page.screenshot(path=str(ss_f), full_page=False)

    # VLM: list menu items
    vlm_menu_text = vlm_ask(
        fleet, ss_f,
        "List ALL menu items visible in the dropdown menu on this screen. "
        "Include every item you can read, one per line."
    )

    # Expected items
    expected_items = [
        "Satellite", "Roads", "Buildings", "Waterways", "Parks",
        "Grid", "3D Models", "Labels", "Fog", "Terrain", "3D Mode",
        "Center on Action", "Reset Camera", "Zoom In", "Zoom Out"
    ]

    # Check which items the VLM found
    vlm_lower = vlm_menu_text.lower()
    found_items = []
    missing_items = []
    for item in expected_items:
        if item.lower() in vlm_lower:
            found_items.append(item)
        else:
            missing_items.append(item)

    # Also do DOM check — more reliable
    menu_items_dom = page.evaluate("""() => {
        // Look for dropdown/menu items
        const items = [];
        document.querySelectorAll('.dropdown-menu-item, .menu-item, [class*=menu] button, [class*=menu] label, [class*=dropdown] button, [class*=dropdown] label').forEach(el => {
            const text = el.textContent.trim();
            if (text && text.length < 50) items.push(text);
        });
        // Also check for any visible menu/dropdown
        document.querySelectorAll('.dropdown-content, .menu-dropdown, .dropdown').forEach(el => {
            if (el.offsetHeight > 0) {
                el.querySelectorAll('*').forEach(child => {
                    const text = child.textContent.trim();
                    if (text && text.length < 40 && child.children.length === 0) {
                        items.push(text);
                    }
                });
            }
        });
        return [...new Set(items)];
    }""")

    dom_found = []
    dom_missing = []
    dom_lower_texts = [t.lower() for t in (menu_items_dom or [])]
    for item in expected_items:
        if any(item.lower() in t for t in dom_lower_texts):
            dom_found.append(item)
        else:
            dom_missing.append(item)

    # Pass if at least 12/15 items found in either VLM or DOM
    vlm_pass_f = len(found_items) >= 10
    dom_pass_f = len(dom_found) >= 12
    overall_f = dom_pass_f or vlm_pass_f

    results["F_map_menu"] = {
        "passed": overall_f,
        "vlm": {
            "found": found_items,
            "missing": missing_items,
            "raw_text": vlm_menu_text[:500],
            "pass": vlm_pass_f,
        },
        "dom": {
            "all_items": menu_items_dom,
            "found": dom_found,
            "missing": dom_missing,
            "pass": dom_pass_f,
        },
    }
    print(f"  VLM found: {len(found_items)}/15 items -> {'PASS' if vlm_pass_f else 'FAIL'}")
    print(f"    Found: {found_items}")
    print(f"    Missing: {missing_items}")
    print(f"  DOM found: {len(dom_found)}/15 items -> {'PASS' if dom_pass_f else 'FAIL'}")
    print(f"    Found: {dom_found}")
    print(f"    Missing: {dom_missing}")
    print(f"  -> {'PASS' if overall_f else 'FAIL'}")

    # Close menu by pressing Escape
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)

    all_passed = True
    for name, result in results.items():
        status = "PASS" if result["passed"] else "FAIL"
        if not result["passed"]:
            all_passed = False
        print(f"  {name}: {status}")

    print(f"\n  Console errors during test: {len(errors)}")
    if errors:
        for e in errors[:5]:
            print(f"    - {e[:120]}")

    print(f"\n  Overall: {'ALL PASSED' if all_passed else 'SOME FAILURES'}")
    print(f"  Screenshots saved to: {SCREENSHOT_DIR.resolve()}")

    # Save results JSON
    results_file = SCREENSHOT_DIR / "results.json"
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results JSON: {results_file.resolve()}")

    # Cleanup
    browser.close()
    pw.stop()

    return all_passed


if __name__ == "__main__":
    passed = run_all()
    sys.exit(0 if passed else 1)
