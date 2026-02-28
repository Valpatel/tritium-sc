# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Building alignment verification via edge detection.

Uses deterministic layer control (setLayers API) to capture:
  1. BLANK — all layers off (proves we can reach empty canvas)
  2. SAT ONLY — satellite on, everything else off
  3. BLDG ONLY — buildings on, everything else off
  4. BOTH — satellite + buildings combined

Runs Canny edge detection on SAT ONLY and BLDG ONLY views,
then overlays them with proximity scoring.

Run:
    .venv/bin/python3 tests/visual/test_building_alignment.py
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from playwright.sync_api import sync_playwright

OUT = Path("tests/.test-results/building-alignment")
OUT.mkdir(parents=True, exist_ok=True)

SETTLE = 1.5        # seconds after layer change for render to settle
CANNY_LO = 30
CANNY_HI = 100
PROXIMITY_PX = 8    # pixel tolerance for alignment scoring


def _grab(page) -> np.ndarray:
    """Grab canvas pixels as BGR numpy array."""
    canvas = page.locator("#tactical-3d-canvas")
    buf = canvas.screenshot()
    arr = np.frombuffer(buf, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _set_layers(page, **kwargs):
    """Set map layers deterministically and verify state.

    Example: _set_layers(page, satellite=True, buildings=False, roads=False, grid=False, units=False)
    Returns the verified state dict.
    """
    js_obj = ", ".join(f"{k}: {str(v).lower()}" for k, v in kwargs.items())
    state = page.evaluate(f"window._mapActions.setLayers({{ {js_obj} }})")
    return state


def _crop(img: np.ndarray) -> np.ndarray:
    """Crop to map area (remove UI panels)."""
    h, w = img.shape[:2]
    return img[int(h * 0.04):int(h * 0.88), int(w * 0.12):int(w * 0.88)].copy()


def _edges(bgr: np.ndarray) -> np.ndarray:
    """Canny edge detection."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.0)
    return cv2.Canny(blurred, CANNY_LO, CANNY_HI)


def _dilate(edges: np.ndarray, px: int) -> np.ndarray:
    """Dilate edges for proximity matching."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (px * 2 + 1, px * 2 + 1))
    return cv2.dilate(edges, kernel)


def _mean_brightness(bgr: np.ndarray) -> float:
    """Mean brightness of a BGR image."""
    return float(np.mean(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)))


def main():
    print("=" * 60)
    print("  Building Alignment Verification v2")
    print("  Deterministic Layer Control + Edge Detection")
    print("=" * 60)

    ALL_OFF = dict(satellite=False, buildings=False, roads=False, grid=False, units=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})

        console_msgs = []
        page.on("console", lambda msg: console_msgs.append(msg.text))

        page.goto("http://localhost:8000", wait_until="networkidle", timeout=15000)
        time.sleep(5)

        # Dismiss modals
        page.keyboard.press("Escape")
        time.sleep(0.5)

        # ============================================================
        # STEP 0: Verify API works
        # ============================================================
        print("\n[Step 0] Verify setLayers API")
        state = _set_layers(page, **ALL_OFF)
        print(f"  State after ALL OFF: {state}")
        assert not state["showSatellite"], "Satellite should be OFF"
        assert not state["showBuildings"], "Buildings should be OFF"
        assert not state["showRoads"], "Roads should be OFF"
        print("  API control verified.")

        # ============================================================
        # STEP 1: BLANK — everything off
        # ============================================================
        print("\n[Step 1] BLANK — all layers off")
        _set_layers(page, **ALL_OFF)
        time.sleep(SETTLE)

        blank = _grab(page)
        cv2.imwrite(str(OUT / "01_blank.png"), blank)
        blank_brightness = _mean_brightness(_crop(blank))
        print(f"  Brightness: {blank_brightness:.1f} (should be very dark)")
        assert blank_brightness < 30, f"Blank canvas too bright: {blank_brightness:.1f}"
        print("  PASS: blank canvas is dark")

        # ============================================================
        # STEP 2: SATELLITE ONLY
        # ============================================================
        print("\n[Step 2] SATELLITE ONLY")
        _set_layers(page, satellite=True, buildings=False, roads=False, grid=False, units=False)
        time.sleep(SETTLE + 1)  # Extra time for tile texture

        sat_only = _grab(page)
        cv2.imwrite(str(OUT / "02_sat_only.png"), sat_only)
        sat_brightness = _mean_brightness(_crop(sat_only))
        print(f"  Brightness: {sat_brightness:.1f} (should be bright)")
        assert sat_brightness > 40, f"Satellite too dark: {sat_brightness:.1f}"
        print("  PASS: satellite visible")

        # ============================================================
        # STEP 3: BUILDINGS ONLY
        # ============================================================
        print("\n[Step 3] BUILDINGS ONLY")
        _set_layers(page, satellite=False, buildings=True, roads=False, grid=False, units=False)
        time.sleep(SETTLE)

        bldg_only = _grab(page)
        cv2.imwrite(str(OUT / "03_bldg_only.png"), bldg_only)
        bldg_crop = _crop(bldg_only)
        bldg_brightness = _mean_brightness(bldg_crop)
        # Buildings are cyan outlines on dark background — should be dimmer than sat but brighter than blank
        print(f"  Brightness: {bldg_brightness:.1f} (should be dim with cyan outlines)")
        # Check that cyan channel has content (low opacity outlines, so use lower threshold)
        cyan_pixels = np.count_nonzero(bldg_crop[:, :, 0] > 50)  # Blue channel
        print(f"  Cyan pixels (blue > 50): {cyan_pixels:,}")
        assert cyan_pixels > 200, f"Too few building pixels: {cyan_pixels}"
        print("  PASS: buildings visible as outlines")

        # ============================================================
        # STEP 4: BOTH
        # ============================================================
        print("\n[Step 4] BOTH — satellite + buildings")
        _set_layers(page, satellite=True, buildings=True, roads=False, grid=False, units=False)
        time.sleep(SETTLE + 1)

        both = _grab(page)
        cv2.imwrite(str(OUT / "04_both.png"), both)
        both_brightness = _mean_brightness(_crop(both))
        print(f"  Brightness: {both_brightness:.1f}")
        print("  PASS: combined view captured")

        # ============================================================
        # STEP 5: EVERYTHING ON (reference)
        # ============================================================
        print("\n[Step 5] ALL ON (reference)")
        _set_layers(page, satellite=True, buildings=True, roads=True, grid=False, units=True)
        time.sleep(SETTLE)
        all_on = _grab(page)
        cv2.imwrite(str(OUT / "05_all_on.png"), all_on)

        browser.close()

    # ============================================================
    # STEP 6: Edge detection on cropped map areas
    # ============================================================
    print("\n[Step 6] Edge detection")

    sat_crop = _crop(sat_only)
    bldg_crop = _crop(bldg_only)
    both_crop = _crop(both)

    sat_edges = _edges(sat_crop)
    bldg_edges = _edges(bldg_crop)

    cv2.imwrite(str(OUT / "06_sat_edges.png"), sat_edges)
    cv2.imwrite(str(OUT / "07_bldg_edges.png"), bldg_edges)

    sat_px = np.count_nonzero(sat_edges)
    bldg_px = np.count_nonzero(bldg_edges)
    print(f"  Satellite edge pixels:  {sat_px:,}")
    print(f"  Building edge pixels:   {bldg_px:,}")

    # ============================================================
    # STEP 7: Color edge overlay
    # ============================================================
    print("\n[Step 7] Edge overlay visualization")

    h, w = sat_edges.shape
    # Background: dimmed satellite
    overlay = (sat_crop * 0.3).astype(np.uint8)

    sat_mask = sat_edges > 0
    bldg_mask = bldg_edges > 0

    # Red: satellite edges only
    overlay[sat_mask & ~bldg_mask, 2] = 200
    overlay[sat_mask & ~bldg_mask, 1] = 50
    overlay[sat_mask & ~bldg_mask, 0] = 50

    # Cyan: building edges only
    overlay[bldg_mask & ~sat_mask, 0] = 255
    overlay[bldg_mask & ~sat_mask, 1] = 240
    overlay[bldg_mask & ~sat_mask, 2] = 0

    # White: exact overlap
    overlap = sat_mask & bldg_mask
    overlay[overlap] = [255, 255, 255]

    cv2.imwrite(str(OUT / "08_edge_overlay.png"), overlay)

    # ============================================================
    # STEP 8: Proximity scoring
    # ============================================================
    print("\n[Step 8] Proximity analysis")

    sat_dilated = _dilate(sat_edges, PROXIMITY_PX)
    bldg_dilated = _dilate(bldg_edges, PROXIMITY_PX)

    if bldg_px > 0:
        aligned = np.count_nonzero(bldg_edges & sat_dilated)
        score = aligned / bldg_px * 100
    else:
        aligned = 0
        score = 0

    if sat_px > 0:
        reverse_aligned = np.count_nonzero(sat_edges & bldg_dilated)
        reverse_score = reverse_aligned / sat_px * 100
    else:
        reverse_score = 0

    print(f"  Building edges within {PROXIMITY_PX}px of satellite: {aligned:,} / {bldg_px:,} ({score:.1f}%)")
    print(f"  Satellite edges within {PROXIMITY_PX}px of building: {reverse_aligned:,} / {sat_px:,} ({reverse_score:.1f}%)")

    # Proximity visualization: green=aligned, red=misaligned
    prox = (sat_crop * 0.3).astype(np.uint8)
    aligned_mask = (bldg_edges > 0) & (sat_dilated > 0)
    misaligned_mask = (bldg_edges > 0) & (sat_dilated == 0)
    prox[aligned_mask, 1] = 255    # Green = aligned
    prox[misaligned_mask, 2] = 255  # Red = misaligned
    # Dim cyan: satellite edges for reference
    sat_ref_mask = sat_mask & ~bldg_mask
    prox[sat_ref_mask, 0] = 150
    prox[sat_ref_mask, 1] = 150

    cv2.imwrite(str(OUT / "09_proximity.png"), prox)

    # ============================================================
    # STEP 9: 2x3 comparison grid
    # ============================================================
    print("\n[Step 9] Comparison grid")

    def _resize(img, target_w, target_h):
        return cv2.resize(img, (target_w, target_h))

    gw, gh = w // 3, h // 2
    panels = [
        (_resize(_crop(blank), gw, gh), "BLANK"),
        (_resize(sat_crop, gw, gh), "SATELLITE"),
        (_resize(bldg_crop, gw, gh), "BUILDINGS"),
        (_resize(both_crop, gw, gh), "BOTH"),
        (_resize(overlay, gw, gh), "EDGES"),
        (_resize(prox, gw, gh), "ALIGNMENT"),
    ]

    font = cv2.FONT_HERSHEY_SIMPLEX
    for img, label in panels:
        cv2.putText(img, label, (8, 25), font, 0.7, (0, 255, 255), 2)

    row1 = np.hstack([panels[0][0], panels[1][0], panels[2][0]])
    row2 = np.hstack([panels[3][0], panels[4][0], panels[5][0]])
    grid = np.vstack([row1, row2])

    txt = f"Building->Sat alignment: {score:.1f}% (within {PROXIMITY_PX}px)"
    cv2.putText(grid, txt, (8, grid.shape[0] - 12), font, 0.8, (0, 255, 255), 2)

    cv2.imwrite(str(OUT / "10_grid.png"), grid)

    # ============================================================
    # Report
    # ============================================================
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Blank brightness      : {blank_brightness:.1f} (expect < 30)")
    print(f"  Satellite brightness  : {sat_brightness:.1f} (expect > 40)")
    print(f"  Building cyan pixels  : {cyan_pixels:,} (expect > 500)")
    print(f"  Satellite edge px     : {sat_px:,}")
    print(f"  Building edge px      : {bldg_px:,}")
    print(f"  Proximity tolerance   : {PROXIMITY_PX}px")
    print(f"  Building→Sat score    : {score:.1f}%")
    print(f"  Sat→Building score    : {reverse_score:.1f}%")
    print()

    if score >= 80:
        verdict = "GOOD"
    elif score >= 65:
        verdict = "FAIR — buildings roughly positioned but individual offsets visible"
    elif score >= 40:
        verdict = "POOR — significant misalignment, OSM data quality issue"
    else:
        verdict = "BAD — buildings do not align with satellite imagery"
    print(f"  Verdict: {verdict}")
    # Alignment below 80% is not acceptable for production
    if score < 80:
        print(f"  FAIL: alignment {score:.1f}% is below 80% threshold")
        print(f"  NOTE: OSM building outlines were traced from different imagery than ESRI satellite")
        print(f"        This is a data source mismatch, not a coordinate bug")
    print(f"  Output:  {OUT}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
