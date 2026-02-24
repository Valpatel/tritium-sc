"""HTML report generator for synthetic video test results.

Generates a self-contained cyberpunk-styled HTML report with:
- Sample frames (inline base64 PNG) for each scene type
- OpenCV analysis results (histograms, detected features)
- Performance metrics (frame time, throughput)
- LLaVA responses (if available)
- Overall summary table with pass/fail per scene type

Output: tests/.test-results/synthetic-video-report.html
"""

from __future__ import annotations

import base64
import html
import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from engine.synthetic.video_gen import (
    DARK_BG,
    FRIENDLY_GREEN,
    HOSTILE_RED,
    UNKNOWN_YELLOW,
    Explosion,
    Projectile,
    render_battle_scene,
    render_bird_eye,
    render_neighborhood,
    render_street_cam,
)
from engine.synthetic.video_library import _make_demo_targets


pytestmark = pytest.mark.unit

SEED = 42
RESOLUTION = (640, 480)
RESULTS_DIR = Path(__file__).parent.parent / ".test-results"

# Cyberpunk palette
BG_DARK = "#0a0a0f"
BG_CARD = "#12121a"
CYAN = "#00f0ff"
MAGENTA = "#ff2a6d"
GREEN = "#05ffa1"
YELLOW = "#fcee0a"
TEXT = "#c0c0d0"
TEXT_DIM = "#606080"
BORDER = "#1a1a2e"


_CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: {BG_DARK};
    color: {TEXT};
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
    line-height: 1.6;
    padding: 24px;
    max-width: 1200px;
    margin: 0 auto;
}}
h1 {{
    color: {CYAN};
    font-size: 22px;
    border-bottom: 2px solid {CYAN}40;
    padding-bottom: 8px;
    margin-bottom: 16px;
}}
h2 {{
    color: {CYAN};
    font-size: 16px;
    margin: 20px 0 10px 0;
}}
h3 {{
    color: {TEXT};
    font-size: 14px;
    margin: 12px 0 6px 0;
}}
table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0;
}}
th, td {{
    padding: 6px 10px;
    text-align: left;
    border: 1px solid {BORDER};
}}
th {{
    background: {BG_CARD};
    color: {CYAN};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
td {{ font-size: 12px; }}
.pass {{ color: {GREEN}; font-weight: bold; }}
.fail {{ color: {MAGENTA}; font-weight: bold; }}
.scene-card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 16px;
    margin: 16px 0;
}}
.scene-card img {{
    max-width: 320px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    margin: 8px 0;
}}
.analysis-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin: 8px 0;
}}
.metric {{ font-size: 12px; }}
.metric .label {{ color: {TEXT_DIM}; }}
.metric .value {{ color: {GREEN}; font-weight: bold; }}
pre {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 11px;
    overflow-x: auto;
    white-space: pre-wrap;
}}
.footer {{
    text-align: center;
    color: {TEXT_DIM};
    font-size: 11px;
    margin-top: 40px;
    padding-top: 12px;
    border-top: 1px solid {BORDER};
}}
"""


def _frame_to_b64(frame: np.ndarray) -> str:
    """Encode a BGR frame to base64 PNG."""
    _, buf = cv2.imencode(".png", frame)
    return base64.b64encode(buf.tobytes()).decode()


def _count_color(frame: np.ndarray, bgr: tuple, tolerance: int = 40) -> int:
    """Count pixels matching a BGR color."""
    lower = np.array([max(0, c - tolerance) for c in bgr], dtype=np.uint8)
    upper = np.array([min(255, c + tolerance) for c in bgr], dtype=np.uint8)
    mask = cv2.inRange(frame, lower, upper)
    return int(cv2.countNonZero(mask))


def _detect_lines(frame: np.ndarray) -> int:
    """Count lines detected by HoughLinesP."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 15, 60)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=25, minLineLength=30, maxLineGap=10)
    return len(lines) if lines is not None else 0


def _brightness(frame: np.ndarray) -> float:
    """Mean grayscale brightness."""
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())


def _edge_density(frame: np.ndarray) -> float:
    """Fraction of pixels that are edges."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 20, 80)
    return float(cv2.countNonZero(edges) / edges.size)


def _analyze_scene(scene_name: str, frame: np.ndarray) -> dict:
    """Run OpenCV analysis on a frame and return metrics dict."""
    metrics = {
        "brightness": round(_brightness(frame), 2),
        "edge_density": round(_edge_density(frame), 5),
        "lines_detected": _detect_lines(frame),
        "friendly_green_pixels": _count_color(frame, FRIENDLY_GREEN),
        "hostile_red_pixels": _count_color(frame, HOSTILE_RED),
        "unknown_yellow_pixels": _count_color(frame, UNKNOWN_YELLOW),
    }

    # Color histogram (BGR channels)
    for i, ch_name in enumerate(["blue", "green", "red"]):
        hist = cv2.calcHist([frame], [i], None, [256], [0, 256])
        metrics[f"hist_{ch_name}_mean"] = round(float(hist.mean()), 2)
        metrics[f"hist_{ch_name}_max_bin"] = int(np.argmax(hist))

    return metrics


def _time_renderer(renderer, kwargs: dict, n: int = 10) -> dict:
    """Time a renderer over n frames."""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        renderer(**kwargs)
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "avg_ms": round(sum(times) / len(times), 2),
        "max_ms": round(max(times), 2),
        "min_ms": round(min(times), 2),
    }


class TestVideoReport:
    """Generate the comprehensive HTML report."""

    def test_generate_report(self, tmp_path):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        scenes = {}

        # -- Bird Eye --
        demo = _make_demo_targets("bird_eye", 25, 50, SEED)
        frame = render_bird_eye(resolution=RESOLUTION, seed=SEED, timestamp="12:00:00", **demo)
        analysis = _analyze_scene("bird_eye", frame)
        perf = _time_renderer(render_bird_eye, {"resolution": RESOLUTION, "seed": SEED})
        scenes["bird_eye"] = {
            "frame_b64": _frame_to_b64(frame),
            "analysis": analysis,
            "perf": perf,
            "checks": {
                "grid_lines": analysis["lines_detected"] >= 4,
                "friendly_color": analysis["friendly_green_pixels"] > 20,
                "hostile_color": analysis["hostile_red_pixels"] > 20,
                "dark_background": analysis["brightness"] < 60,
            },
        }

        # -- Street Cam --
        demo = _make_demo_targets("street_cam", 10, 50, SEED)
        frame = render_street_cam(
            resolution=RESOLUTION, seed=SEED, timestamp="2026-02-20 22:00:00",
            camera_name="CAM-01", **demo,
        )
        analysis = _analyze_scene("street_cam", frame)
        perf = _time_renderer(
            render_street_cam,
            {"resolution": RESOLUTION, "seed": SEED, "camera_name": "PERF"},
        )
        scenes["street_cam"] = {
            "frame_b64": _frame_to_b64(frame),
            "analysis": analysis,
            "perf": perf,
            "checks": {
                "perspective_lines": analysis["lines_detected"] >= 3,
                "has_text": analysis["edge_density"] > 0.005,
                "night_dark": analysis["brightness"] < 60,
            },
        }

        # -- Battle --
        demo = _make_demo_targets("battle", 15, 50, SEED)
        frame = render_battle_scene(resolution=RESOLUTION, seed=SEED, timestamp="09:00:00", **demo)
        analysis = _analyze_scene("battle", frame)
        perf = _time_renderer(render_battle_scene, {"resolution": RESOLUTION, "seed": SEED})
        scenes["battle"] = {
            "frame_b64": _frame_to_b64(frame),
            "analysis": analysis,
            "perf": perf,
            "checks": {
                "friendly_present": analysis["friendly_green_pixels"] > 10,
                "hostile_present": analysis["hostile_red_pixels"] > 10,
                "dark_background": analysis["brightness"] < 60,
            },
        }

        # -- Neighborhood --
        demo = _make_demo_targets("neighborhood", 10, 50, SEED)
        frame = render_neighborhood(
            resolution=RESOLUTION, seed=SEED, timestamp="2026-02-20 22:00:00",
            camera_name="NBHD-01", **demo,
        )
        analysis = _analyze_scene("neighborhood", frame)
        perf = _time_renderer(
            render_neighborhood,
            {"resolution": RESOLUTION, "seed": SEED, "camera_name": "PERF"},
        )
        scenes["neighborhood"] = {
            "frame_b64": _frame_to_b64(frame),
            "analysis": analysis,
            "perf": perf,
            "checks": {
                "has_edges": analysis["edge_density"] > 0.003,
                "night_dark": analysis["brightness"] < 60,
            },
        }

        # -- Load LLaVA results if available --
        llava_path = RESULTS_DIR / "llava-report.json"
        llava_data = {}
        if llava_path.exists():
            try:
                with open(llava_path) as f:
                    llava_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # -- Load perf results if available --
        perf_path = RESULTS_DIR / "perf-report.json"
        perf_data = {}
        if perf_path.exists():
            try:
                with open(perf_path) as f:
                    perf_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        # -- Generate HTML --
        html_content = _render_html(scenes, llava_data, perf_data)
        report_path = RESULTS_DIR / "synthetic-video-report.html"
        report_path.write_text(html_content, encoding="utf-8")

        # Verify report was generated
        assert report_path.exists()
        assert report_path.stat().st_size > 1000, "Report too small"

        # Verify all scenes passed their checks
        for scene_name, scene_data in scenes.items():
            for check_name, passed in scene_data["checks"].items():
                assert passed, f"{scene_name}.{check_name} failed"


def _render_html(
    scenes: dict,
    llava_data: dict,
    perf_data: dict,
) -> str:
    """Render the full HTML report."""
    parts = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='utf-8'>",
        "<title>TRITIUM-SC Synthetic Video Report</title>",
        f"<style>{_CSS}</style>",
        "</head>",
        "<body>",
        "<h1>TRITIUM-SC // SYNTHETIC VIDEO VALIDATION REPORT</h1>",
        f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
    ]

    # -- Summary table --
    parts.append("<h2>Summary</h2>")
    parts.append("<table>")
    parts.append("<tr><th>Scene</th><th>Checks</th><th>Brightness</th>"
                 "<th>Lines</th><th>Avg Frame ms</th><th>Status</th></tr>")
    for name, data in scenes.items():
        checks = data["checks"]
        all_pass = all(checks.values())
        status_cls = "pass" if all_pass else "fail"
        status_text = "PASS" if all_pass else "FAIL"
        check_str = ", ".join(
            f"<span class='{'pass' if v else 'fail'}'>{k}</span>"
            for k, v in checks.items()
        )
        parts.append(
            f"<tr>"
            f"<td><strong>{html.escape(name)}</strong></td>"
            f"<td>{check_str}</td>"
            f"<td>{data['analysis']['brightness']}</td>"
            f"<td>{data['analysis']['lines_detected']}</td>"
            f"<td>{data['perf']['avg_ms']}ms</td>"
            f"<td class='{status_cls}'>{status_text}</td>"
            f"</tr>"
        )
    parts.append("</table>")

    # -- Scene cards --
    for name, data in scenes.items():
        parts.append(f'<div class="scene-card">')
        parts.append(f"<h2>{html.escape(name.upper().replace('_', ' '))}</h2>")

        # Frame image
        parts.append(
            f'<img src="data:image/png;base64,{data["frame_b64"]}" '
            f'alt="{html.escape(name)}">'
        )

        parts.append('<div class="analysis-grid">')

        # OpenCV analysis
        parts.append("<div>")
        parts.append("<h3>OpenCV Analysis</h3>")
        parts.append("<table>")
        for k, v in data["analysis"].items():
            parts.append(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>")
        parts.append("</table>")
        parts.append("</div>")

        # Performance
        parts.append("<div>")
        parts.append("<h3>Performance</h3>")
        parts.append("<table>")
        for k, v in data["perf"].items():
            parts.append(f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>")
        parts.append("</table>")

        # Checks
        parts.append("<h3>Checks</h3>")
        parts.append("<table>")
        for k, v in data["checks"].items():
            cls = "pass" if v else "fail"
            parts.append(
                f"<tr><td>{html.escape(k)}</td>"
                f"<td class='{cls}'>{'PASS' if v else 'FAIL'}</td></tr>"
            )
        parts.append("</table>")
        parts.append("</div>")

        parts.append("</div>")  # analysis-grid

        # LLaVA results if available
        scene_llava = {k: v for k, v in llava_data.items() if name in k}
        if scene_llava:
            parts.append("<h3>LLaVA Validation</h3>")
            parts.append("<pre>")
            parts.append(html.escape(json.dumps(scene_llava, indent=2)))
            parts.append("</pre>")

        parts.append("</div>")  # scene-card

    # -- Extended performance data --
    if perf_data:
        parts.append("<h2>Extended Performance Metrics</h2>")
        parts.append("<pre>")
        parts.append(html.escape(json.dumps(perf_data, indent=2)))
        parts.append("</pre>")

    # Footer
    parts.append('<div class="footer">')
    parts.append(
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
        "by TRITIUM-SC Synthetic Video Report Generator"
    )
    parts.append("</div>")

    parts.extend(["</body>", "</html>"])
    return "\n".join(parts)
