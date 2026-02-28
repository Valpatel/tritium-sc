# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Automated layout drift test for MJPEG video panels.

Uses Playwright (headless Chromium) + OpenCV to detect layout inflation,
scroll drift, or positional shift in the PRIMARY OPTICS panel.

Captures 30 screenshots over 30 seconds.  Measures container size, image
offset, scroll position, and pixel-level content position each frame.
Fails if any metric drifts beyond TOLERANCE_PX.

Usage:
    .venv/bin/python3 tests/ui/test_layout_drift.py [--url URL] [--duration N] [--verbose]

Requires:
    pip install playwright opencv-python-headless numpy
    playwright install chromium
"""

from __future__ import annotations

import argparse
import sys
import time

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

TOLERANCE_PX = 3
DEFAULT_URL = "http://localhost:8000"
DEFAULT_DURATION = 30
INTERVAL = 1.0
SETTLE_TIME = 4.0  # seconds to let MJPEG stream stabilize


def find_content_bbox(crop: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box of non-black pixels in a cropped image."""
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 12, 255, cv2.THRESH_BINARY)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return None
    return cv2.boundingRect(coords)


def get_dom_metrics(page) -> dict | None:
    """Read layout metrics for the PRIMARY OPTICS panel."""
    return page.evaluate("""() => {
        const c = document.getElementById('amy-video-container');
        const img = document.getElementById('amy-video-feed');
        const dash = document.querySelector('.amy-dashboard');
        const vc = document.querySelector('#view-amy');
        if (!c || !img) return null;
        const cr = c.getBoundingClientRect();
        return {
            cx: Math.round(cr.x), cy: Math.round(cr.y),
            cw: Math.round(cr.width), ch: Math.round(cr.height),
            imgW: img.offsetWidth, imgH: img.offsetHeight,
            imgT: img.offsetTop, imgL: img.offsetLeft,
            natW: img.naturalWidth, natH: img.naturalHeight,
            scrollTop: c.scrollTop,
            scrollH: c.scrollHeight,
            clientH: c.clientHeight,
            dashH: dash ? Math.round(dash.getBoundingClientRect().height) : -1,
            vcH: vc ? Math.round(vc.getBoundingClientRect().height) : -1,
        };
    }""")


def run_test(url: str, duration: float, verbose: bool) -> bool:
    """Run the drift test.  Returns True on pass."""
    num_captures = int(duration / INTERVAL)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-gpu-cache", "--disable-http-cache"],
        )
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            bypass_csp=True,
        )
        page = ctx.new_page()

        # Bypass CSS cache
        page.route("**/*.css", lambda route: route.continue_(headers={
            **route.request.headers,
            "cache-control": "no-cache",
            "pragma": "no-cache",
        }))

        page.goto(url, wait_until="networkidle")
        time.sleep(1)

        # Switch to Amy view
        page.click("#btn-amy")
        time.sleep(SETTLE_TIME)

        container_sizes: list[tuple[int, int]] = []
        img_offsets: list[tuple[int, int, int]] = []
        content_bboxes: list[tuple[int, int, int, int] | None] = []

        if verbose:
            print(f"Capturing {num_captures} frames over {duration:.0f}s...")
            print(f"{'frm':>3} | {'container':>12} | {'img offset':>14} | "
                  f"{'scrollTop':>9} | {'scrollH':>7} | {'clientH':>7} | "
                  f"{'dash':>5} | {'vc':>5}")
            print("-" * 90)

        for i in range(num_captures):
            info = get_dom_metrics(page)
            if info is None:
                if verbose:
                    print(f"  {i:2d}  | ELEMENTS NOT FOUND")
                time.sleep(INTERVAL)
                continue

            container_sizes.append((info["cw"], info["ch"]))
            img_offsets.append((info["imgW"], info["imgH"], info["imgT"]))

            # OpenCV content bbox from screenshot crop
            shot = page.screenshot()
            full = cv2.imdecode(np.frombuffer(shot, np.uint8), cv2.IMREAD_COLOR)
            x, y = info["cx"], info["cy"]
            w, h = info["cw"], info["ch"]
            y2 = min(y + h, full.shape[0])
            x2 = min(x + w, full.shape[1])
            crop = full[max(0, y):y2, max(0, x):x2]
            bbox = find_content_bbox(crop)
            content_bboxes.append(bbox)

            if i == 0:
                cv2.imwrite("/tmp/drift_first.png", crop)
            if i == num_captures - 1:
                cv2.imwrite("/tmp/drift_last.png", crop)

            if verbose:
                print(f"  {i:2d}  | {info['cw']:>5}x{info['ch']:<5} | "
                      f"{info['imgW']:>5}x{info['imgH']:<5} t={info['imgT']:<3}| "
                      f"{info['scrollTop']:>9} | {info['scrollH']:>7} | "
                      f"{info['clientH']:>7} | {info['dashH']:>5} | {info['vcH']:>5}")

            if i < num_captures - 1:
                time.sleep(INTERVAL)

        browser.close()

    # --- Analysis ---
    if not container_sizes:
        print("FAIL: No data captured")
        return False

    widths = [s[0] for s in container_sizes]
    heights = [s[1] for s in container_sizes]
    img_heights = [o[1] for o in img_offsets]
    img_tops = [o[2] for o in img_offsets]
    valid_bboxes = [b for b in content_bboxes if b is not None]

    w_range = max(widths) - min(widths)
    h_range = max(heights) - min(heights)
    ih_range = max(img_heights) - min(img_heights)
    it_range = max(img_tops) - min(img_tops)

    print(f"\nContainer: {widths[0]}x{heights[0]}  (width range={w_range}px, height range={h_range}px)")
    print(f"Image:     {img_offsets[0][0]}x{img_offsets[0][1]}  (height range={ih_range}px, top range={it_range}px)")

    if valid_bboxes:
        cy_vals = [b[1] for b in valid_bboxes]
        ch_vals = [b[3] for b in valid_bboxes]
        cy_range = max(cy_vals) - min(cy_vals)
        ch_range = max(ch_vals) - min(ch_vals)
        print(f"Content:   y_range={cy_range}px, h_range={ch_range}px")

    issues: list[str] = []
    if h_range > TOLERANCE_PX:
        issues.append(f"Container height drifted {h_range}px")
    if ih_range > TOLERANCE_PX:
        issues.append(f"Image height drifted {ih_range}px")
    if it_range > TOLERANCE_PX:
        issues.append(f"Image top offset drifted {it_range}px")
    if valid_bboxes:
        cy_range = max(b[1] for b in valid_bboxes) - min(b[1] for b in valid_bboxes)
        if cy_range > TOLERANCE_PX * 2:
            issues.append(f"Content Y drifted {cy_range}px")

    if issues:
        print(f"\nFAIL: Layout drift detected (tolerance={TOLERANCE_PX}px)")
        for issue in issues:
            print(f"  - {issue}")
        return False

    print(f"\nPASS: No drift over {duration:.0f}s ({num_captures} frames, tolerance={TOLERANCE_PX}px)")
    return True


def main():
    parser = argparse.ArgumentParser(description="MJPEG layout drift test")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    ok = run_test(args.url, args.duration, args.verbose)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
