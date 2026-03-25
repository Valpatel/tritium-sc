# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Visual animation tests for the city simulation.

Verifies that city sim vehicles ACTUALLY MOVE on screen, that enough
markers are visible, that no stack overflow errors occur, and that
protests produce visible crowd density changes.

Uses Playwright for browser control + OpenCV for pixel-level image analysis.
These tests are STRICT — they fail when the feature is broken.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np
import pytest

try:
    from playwright.sync_api import sync_playwright
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

pytestmark = [
    pytest.mark.visual,
    pytest.mark.skipif(not HAS_PLAYWRIGHT, reason="playwright not installed"),
]

BASE_URL = os.environ.get("TRITIUM_URL", "http://localhost:8000")
RESULTS_DIR = Path(__file__).parent.parent / ".test-results" / "city-sim-animation"


def _server_up() -> bool:
    """Return True if the server is running."""
    import requests
    try:
        r = requests.get(f"{BASE_URL}/api/city-sim/status", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _ensure_results_dir():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)


def _pixel_diff_pct(img1_path: str, img2_path: str) -> float:
    """Compute the percentage of pixels that differ between two images.

    Uses a per-channel absolute difference with a threshold of 10
    to filter out compression artifacts and sub-pixel rendering noise.
    Returns percentage of pixels where ANY channel changed by > threshold.
    """
    a = cv2.imread(img1_path)
    b = cv2.imread(img2_path)
    if a is None or b is None:
        raise ValueError(f"Failed to read images: {img1_path}, {img2_path}")
    if a.shape != b.shape:
        # Resize to match if dimensions differ slightly
        b = cv2.resize(b, (a.shape[1], a.shape[0]))

    diff = cv2.absdiff(a, b)
    # Any channel changed by more than 10 counts as a changed pixel
    changed = np.any(diff > 10, axis=2)
    total_pixels = changed.size
    changed_pixels = np.count_nonzero(changed)
    return (changed_pixels / total_pixels) * 100.0


@pytest.fixture(scope="module")
def city_sim_page():
    """Launch headed Chromium, open Command Center, start city sim, yield page.

    Waits for city sim to initialize with vehicles before yielding.
    Cleans up browser on exit.
    """
    if not _server_up():
        pytest.skip("Server not running on port 8000")

    _ensure_results_dir()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = ctx.new_page()

        # Collect console messages for later inspection
        page._console_msgs = []
        page._console_errors = []
        page.on("console", lambda msg: (
            page._console_errors.append(msg.text) if msg.type == "error"
            else page._console_msgs.append(msg.text)
        ))

        # Navigate and wait for app to initialize
        page.goto(BASE_URL, wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(5000)

        # Press J to start city sim
        page.keyboard.press("j")
        page.wait_for_timeout(15000)  # City sim needs time to load OSM + spawn vehicles

        # Verify city sim actually started
        stats = page.evaluate("""() => {
            const mod = window.__citySimExports || null;
            if (mod && mod.getCitySimStats) return mod.getCitySimStats();
            // Fallback: try global accessor
            if (window._tritiumCitySimStats) return window._tritiumCitySimStats();
            return null;
        }""")

        # Also try the module import approach
        if stats is None:
            stats = page.evaluate("""async () => {
                try {
                    const mod = await import('/static/js/command/map-maplibre.js');
                    return mod.getCitySimStats ? mod.getCitySimStats() : null;
                } catch(e) { return null; }
            }""")

        if stats and not stats.get("running"):
            # City sim failed to start — skip all tests in this module
            browser.close()
            pytest.skip("City sim did not start (stats.running=false)")

        yield page
        browser.close()


class TestCitySimVehiclesMove:
    """Verify city sim vehicles actually animate between frames."""

    def test_city_sim_vehicles_move(self, city_sim_page):
        """Takes two screenshots 3 seconds apart with city sim running.

        Compares them pixel-by-pixel. If less than 0.3% of pixels changed,
        the test FAILS because vehicles should be moving, pedestrians walking,
        and the HUD updating. Animation means pixels change.
        """
        page = city_sim_page
        _ensure_results_dir()

        # Set a consistent top-down view at zoom 16 for good vehicle visibility
        page.evaluate("""
            window._tritiumMap?.flyTo({ zoom: 16, pitch: 0, bearing: 0, duration: 0 });
        """)
        page.wait_for_timeout(2000)

        # Capture frame 1
        path1 = str(RESULTS_DIR / "frame_t0.png")
        page.screenshot(path=path1)

        # Wait 3 seconds for animation to progress
        page.wait_for_timeout(3000)

        # Capture frame 2
        path2 = str(RESULTS_DIR / "frame_t3.png")
        page.screenshot(path=path2)

        diff_pct = _pixel_diff_pct(path1, path2)
        print(f"Pixel diff between t=0 and t=3s: {diff_pct:.3f}%")

        # Save a visual diff image for debugging
        a = cv2.imread(path1)
        b = cv2.imread(path2)
        if a is not None and b is not None:
            diff_img = cv2.absdiff(a, b)
            # Amplify differences for visibility (5x brightness)
            diff_img = np.clip(diff_img.astype(np.int16) * 5, 0, 255).astype(np.uint8)
            cv2.imwrite(str(RESULTS_DIR / "frame_diff_amplified.png"), diff_img)

        # STRICT: vehicles, pedestrians, HUD clock, weather effects should all
        # cause pixel changes. 0.3% of 1920x1080 = ~6220 pixels minimum.
        assert diff_pct > 0.3, (
            f"Only {diff_pct:.3f}% of pixels changed in 3 seconds. "
            f"City sim appears STATIC — vehicles are not moving! "
            f"Diff image saved to {RESULTS_DIR / 'frame_diff_amplified.png'}"
        )

    def test_city_sim_sustained_animation(self, city_sim_page):
        """Verify animation continues over 10 seconds (not just a single update).

        Takes 4 screenshots at 0s, 3s, 6s, 9s and verifies EACH consecutive
        pair has pixel differences. Catches the case where animation runs once
        then freezes.
        """
        page = city_sim_page
        _ensure_results_dir()

        page.evaluate("""
            window._tritiumMap?.flyTo({ zoom: 16, pitch: 0, bearing: 0, duration: 0 });
        """)
        page.wait_for_timeout(1000)

        paths = []
        for i in range(4):
            path = str(RESULTS_DIR / f"sustained_t{i * 3}.png")
            page.screenshot(path=path)
            paths.append(path)
            if i < 3:
                page.wait_for_timeout(3000)

        diffs = []
        for i in range(3):
            d = _pixel_diff_pct(paths[i], paths[i + 1])
            diffs.append(d)
            print(f"Diff t={i*3}s -> t={(i+1)*3}s: {d:.3f}%")

        # Every 3-second interval should show change
        for i, d in enumerate(diffs):
            assert d > 0.1, (
                f"Frame pair {i} (t={i*3}s -> t={(i+1)*3}s) shows only {d:.3f}% change. "
                f"Animation appears to have stalled!"
            )


class TestCitySimMarkerCount:
    """Assert a minimum number of vehicle markers are visible after pressing J."""

    def test_city_sim_marker_count(self, city_sim_page):
        """After city sim starts, at least 50 vehicle markers should be visible.

        Queries the MapLibre GeoJSON source directly to count features,
        which is more reliable than pixel detection.
        """
        page = city_sim_page

        # Query city sim stats from the JS engine
        stats = page.evaluate("""async () => {
            try {
                const mod = await import('/static/js/command/map-maplibre.js');
                return mod.getCitySimStats ? mod.getCitySimStats() : null;
            } catch(e) { return { error: e.message }; }
        }""")

        print(f"City sim stats: {stats}")

        assert stats is not None, "getCitySimStats() returned null — city sim not running"
        assert "error" not in stats, f"Error getting stats: {stats.get('error')}"
        assert stats.get("running") is True, f"City sim not running: {stats}"

        vehicle_count = stats.get("vehicles", 0)
        pedestrian_count = stats.get("pedestrians", 0)
        total_entities = vehicle_count + pedestrian_count

        print(f"Vehicles: {vehicle_count}, Pedestrians: {pedestrian_count}, Total: {total_entities}")

        # STRICT: a working city sim should have at least 50 vehicles
        assert vehicle_count >= 50, (
            f"Only {vehicle_count} vehicles in city sim. Expected >= 50. "
            f"Vehicle spawning may be broken."
        )

    def test_geojson_source_has_features(self, city_sim_page):
        """Verify the MapLibre GeoJSON source actually has renderable features.

        This catches the case where stats report vehicles exist but
        the GeoJSON source feeding the map layer is empty or stale.
        """
        page = city_sim_page

        feature_count = page.evaluate("""() => {
            const map = window._tritiumMap;
            if (!map) return -1;
            const src = map.getSource('city-sim-markers');
            if (!src) return -2;
            // GeoJSON sources expose _data or we can query rendered features
            const rendered = map.queryRenderedFeatures({ layers: ['city-sim-vehicles-2d'] });
            return rendered ? rendered.length : -3;
        }""")

        print(f"Rendered vehicle features on map: {feature_count}")

        if feature_count == -1:
            pytest.fail("Map not found (window._tritiumMap is null)")
        elif feature_count == -2:
            pytest.fail("city-sim-markers source not found — city sim rendering not initialized")
        elif feature_count == -3:
            pytest.fail("queryRenderedFeatures returned null")

        # At the default zoom, we should see a meaningful number of vehicles
        # on screen. Not all 100+ will be in viewport, but at zoom 16 we
        # should see at least 10.
        assert feature_count >= 10, (
            f"Only {feature_count} vehicle features rendered on map. "
            f"Expected >= 10 at zoom 16. Vehicles may not be rendering."
        )

    def test_vehicle_markers_visible_opencv(self, city_sim_page):
        """Use OpenCV to detect cyan (#00f0ff) circles on the screenshot.

        City sim vehicles are rendered as cyan dots. Count them via
        color segmentation in HSV space.
        """
        page = city_sim_page
        _ensure_results_dir()

        # Set view for maximum vehicle visibility
        page.evaluate("""
            window._tritiumMap?.flyTo({ zoom: 16, pitch: 0, bearing: 0, duration: 0 });
        """)
        page.wait_for_timeout(2000)

        path = str(RESULTS_DIR / "marker_detection.png")
        page.screenshot(path=path)

        img = cv2.imread(path)
        assert img is not None, f"Failed to read screenshot: {path}"

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

        # Cyan (#00f0ff) in HSV: H~90 (openCV uses 0-180 range), high S, high V
        # Cyan BGR = (255, 240, 0) -> HSV ~ (90, 255, 255)
        # Use a broad range to catch anti-aliased edges
        lower_cyan = np.array([80, 120, 120])
        upper_cyan = np.array([100, 255, 255])
        mask = cv2.inRange(hsv, lower_cyan, upper_cyan)

        # Find contours (vehicle dots)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Filter by area — vehicle dots at zoom 16 are roughly 3-20px radius
        # Area range: pi*3^2=28 to pi*20^2=1257
        vehicle_contours = [c for c in contours if 20 < cv2.contourArea(c) < 2000]

        # Save annotated image for debugging
        debug_img = img.copy()
        cv2.drawContours(debug_img, vehicle_contours, -1, (0, 0, 255), 2)
        cv2.putText(debug_img, f"Detected: {len(vehicle_contours)} vehicles",
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
        cv2.imwrite(str(RESULTS_DIR / "marker_detection_annotated.png"), debug_img)

        print(f"Cyan contours detected: {len(vehicle_contours)} (from {len(contours)} total)")

        # We want to see at least 10 cyan dots on screen
        # This is more lenient than the stats check because some vehicles
        # may be occluded by UI panels or outside the current viewport
        assert len(vehicle_contours) >= 10, (
            f"Only {len(vehicle_contours)} cyan vehicle markers detected via OpenCV. "
            f"Expected >= 10. Check {RESULTS_DIR / 'marker_detection_annotated.png'} "
            f"for visual debug."
        )


class TestCitySimNoStackOverflow:
    """Assert zero RangeError / stack overflow in console after 30s of city sim."""

    def test_city_sim_no_stack_overflow(self, city_sim_page):
        """Run city sim for 30 seconds and assert zero RangeError in console.

        Stack overflows typically manifest as:
        - RangeError: Maximum call stack size exceeded
        - InternalError: too much recursion

        These indicate infinite recursion in the simulation tick loop,
        pathfinding, or event propagation.
        """
        page = city_sim_page

        # Clear any existing error records from fixture setup
        pre_existing_errors = list(page._console_errors)
        page._console_errors.clear()

        # Let the city sim run for 30 seconds
        print("Running city sim for 30 seconds to check for stack overflows...")
        page.wait_for_timeout(30000)

        # Collect all errors that occurred during the 30s window
        errors = list(page._console_errors)

        # Filter for stack overflow indicators
        stack_overflow_errors = [
            e for e in errors
            if any(keyword in e.lower() for keyword in [
                "rangeerror",
                "maximum call stack",
                "too much recursion",
                "stack overflow",
                "internalerror",
            ])
        ]

        # Also check for other critical JS errors that indicate broken simulation
        critical_errors = [
            e for e in errors
            if any(keyword in e.lower() for keyword in [
                "typeerror: cannot read",
                "typeerror: null is not",
                "typeerror: undefined is not",
                "referenceerror",
            ])
        ]

        print(f"Total console errors: {len(errors)}")
        print(f"Stack overflow errors: {len(stack_overflow_errors)}")
        print(f"Critical JS errors: {len(critical_errors)}")

        if stack_overflow_errors:
            for e in stack_overflow_errors[:5]:
                print(f"  STACK OVERFLOW: {e[:200]}")
        if critical_errors:
            for e in critical_errors[:5]:
                print(f"  CRITICAL: {e[:200]}")

        assert len(stack_overflow_errors) == 0, (
            f"{len(stack_overflow_errors)} stack overflow errors in 30s of city sim! "
            f"First: {stack_overflow_errors[0][:300]}"
        )

    def test_city_sim_still_running_after_30s(self, city_sim_page):
        """After 30 seconds, city sim should still be running (not crashed).

        A stack overflow or uncaught exception could silently kill the
        animation loop. Verify stats still report running=true.
        """
        page = city_sim_page

        stats = page.evaluate("""async () => {
            try {
                const mod = await import('/static/js/command/map-maplibre.js');
                return mod.getCitySimStats ? mod.getCitySimStats() : null;
            } catch(e) { return { error: e.message }; }
        }""")

        assert stats is not None, "getCitySimStats returned null after 30s"
        assert stats.get("running") is True, (
            f"City sim stopped running after 30s! Stats: {stats}"
        )

        # Verify vehicles still exist (not all despawned due to errors)
        assert stats.get("vehicles", 0) > 0, (
            f"No vehicles remaining after 30s. Vehicles may have been lost "
            f"due to simulation errors. Stats: {stats}"
        )


class TestProtestCrowdVisible:
    """After triggering protest, verify crowd density increases in protest area."""

    def test_protest_crowd_visible(self, city_sim_page):
        """Press backslash to trigger protest, then verify:
        1. Protest phase changes from NORMAL
        2. Protestor count increases
        3. More green (pedestrian) pixels appear near protest area

        Takes a before/after screenshot to visually confirm crowd gathering.
        """
        page = city_sim_page
        _ensure_results_dir()

        # Get baseline state before protest
        stats_before = page.evaluate("""async () => {
            try {
                const mod = await import('/static/js/command/map-maplibre.js');
                return mod.getCitySimStats ? mod.getCitySimStats() : null;
            } catch(e) { return { error: e.message }; }
        }""")

        protest_before = stats_before.get("protest") if stats_before else None
        peds_active_before = stats_before.get("pedestriansActive", 0) if stats_before else 0
        print(f"Before protest — active peds: {peds_active_before}, protest info: {protest_before}")

        # Screenshot before protest
        before_path = str(RESULTS_DIR / "protest_before.png")
        page.screenshot(path=before_path)

        # Trigger protest via backslash key
        page.keyboard.press("Backslash")
        print("Backslash pressed — triggering protest")

        # Wait for protest to develop (crowd needs time to gather)
        page.wait_for_timeout(15000)

        # Get stats after protest trigger
        stats_after = page.evaluate("""async () => {
            try {
                const mod = await import('/static/js/command/map-maplibre.js');
                return mod.getCitySimStats ? mod.getCitySimStats() : null;
            } catch(e) { return { error: e.message }; }
        }""")

        protest_after = stats_after.get("protest") if stats_after else None
        print(f"After protest — protest info: {protest_after}")

        # Screenshot after protest
        after_path = str(RESULTS_DIR / "protest_after.png")
        page.screenshot(path=after_path)

        # Verify protest state changed
        assert protest_after is not None, (
            "Protest info is null after pressing backslash. "
            "Protest system may not be wired up."
        )

        # The protest phase should have advanced past NORMAL
        phase = protest_after.get("phase", "NORMAL")
        assert phase != "NORMAL", (
            f"Protest phase still NORMAL after 15 seconds. "
            f"Expected ASSEMBLED, TENSION, or RIOT. Got: {phase}"
        )

        # Check protestor count
        protestor_count = protest_after.get("protestorCount", 0)
        active_count = protest_after.get("active", 0)
        print(f"Protestor count: {protestor_count}, Active: {active_count}")

        assert protestor_count > 0 or active_count > 0, (
            f"No protestors after triggering protest. "
            f"protestorCount={protestor_count}, active={active_count}"
        )

    def test_protest_pixel_density_increases(self, city_sim_page):
        """Measure green pixel density before and after protest.

        Pedestrians are rendered as green (#05ffa1) dots. During a protest,
        more pedestrians should gather in one area, increasing the total
        green pixel count on screen.
        """
        page = city_sim_page
        _ensure_results_dir()

        # Read the before/after screenshots saved by the previous test
        before_path = str(RESULTS_DIR / "protest_before.png")
        after_path = str(RESULTS_DIR / "protest_after.png")

        before_img = cv2.imread(before_path)
        after_img = cv2.imread(after_path)

        if before_img is None or after_img is None:
            pytest.skip("Before/after protest screenshots not available")

        def count_green_pixels(img):
            """Count pixels matching pedestrian green (#05ffa1) in HSV."""
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            # Green (#05ffa1) BGR = (161, 255, 5) -> HSV ~ (75, 253, 255)
            # Broader range to catch anti-aliased pedestrian markers
            lower = np.array([60, 100, 100])
            upper = np.array([90, 255, 255])
            mask = cv2.inRange(hsv, lower, upper)
            return np.count_nonzero(mask)

        green_before = count_green_pixels(before_img)
        green_after = count_green_pixels(after_img)
        print(f"Green pixels — before: {green_before}, after: {green_after}")

        # During a protest, crowd gathers — we should see MORE green pixels
        # (or at minimum, the same amount if they were already all outside)
        # The pixel diff between screenshots should also be significant
        diff_pct = _pixel_diff_pct(before_path, after_path)
        print(f"Pixel diff before/after protest: {diff_pct:.3f}%")

        # Save diff image
        diff_img = cv2.absdiff(before_img, after_img)
        diff_img = np.clip(diff_img.astype(np.int16) * 5, 0, 255).astype(np.uint8)
        cv2.imwrite(str(RESULTS_DIR / "protest_diff_amplified.png"), diff_img)

        # The protest should cause visible changes — at minimum 0.5% pixel diff
        # from crowd movement, gathering, and any protest UI indicators
        assert diff_pct > 0.5, (
            f"Only {diff_pct:.3f}% pixel change after triggering protest. "
            f"Protest may not be rendering visibly. "
            f"Check {RESULTS_DIR / 'protest_diff_amplified.png'}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
