#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Analyze combat test screenshots with multi-model LLM pipeline.

Uses a three-stage pipeline:
1. llava:7b (vision) -- quick description of what's in the screenshot
2. qwen3-vl:8b (vision) -- direct tactical analysis of the image
3. qwen3.5:27b (text) -- deep synthesis from both vision descriptions

Parallelizes across the OllamaFleet (localhost + remote hosts).

Usage:
    python3 scripts/analyze_combat_screenshots.py <screenshot_dir> [options]

Options:
    --model TEXT          Deep analysis model (default: qwen3.5:27b)
    --vision-model TEXT   Vision description model (default: llava:7b)
    --direct-vision TEXT  Direct vision analysis model (default: qwen3-vl:8b)
    --output TEXT         Output directory (default: <screenshot_dir>/analysis/)
    --report              Generate HTML report
    --json                Output JSON analysis
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.lib.ollama_fleet import OllamaFleet

LLAVA_PROMPT = (
    "Describe this tactical satellite map screenshot in detail. "
    "List all visible military units, their colors, positions relative "
    "to buildings and streets, and any combat indicators."
)

QWEN3VL_PROMPT = (
    "Analyze this military tactical display. Rate the defensive positioning "
    "of green friendly units around buildings on a 1-10 scale. Identify gaps "
    "in coverage and approach routes for hostiles."
)

DEEP_PROMPT_TEMPLATE = (
    "Given this tactical situation description from a satellite map:\n\n"
    "{llava_description}\n\n"
    "And this visual analysis:\n\n"
    "{qwen3vl_analysis}\n\n"
    "Provide a comprehensive tactical assessment. Include:\n"
    "1. An overall tactical rating (1-10 scale)\n"
    "2. Coverage assessment of defensive positions\n"
    "3. Identified gaps in the defensive perimeter\n"
    "4. Approach vulnerability analysis (where hostiles could exploit)\n"
    "5. Specific tactical recommendations for improvement\n"
    "6. A brief overall summary\n\n"
    "Format your response as structured analysis with clear headings."
)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def find_screenshots(directory: Path) -> list[Path]:
    """Find all image files in a directory, sorted by name."""
    images = []
    for ext in IMAGE_EXTENSIONS:
        images.extend(directory.glob(f"*{ext}"))
    return sorted(images, key=lambda p: p.name)


def _resize_for_vision(image_path: Path, max_dim: int = 1080) -> Path:
    """Resize image to max_dim on longest side for faster vision model inference."""
    import cv2
    img = cv2.imread(str(image_path))
    if img is None:
        return image_path
    h, w = img.shape[:2]
    if max(h, w) <= max_dim:
        return image_path
    scale = max_dim / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    out = image_path.parent / f"_resized_{image_path.name}"
    cv2.imwrite(str(out), resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return out


def opencv_analyze(image_path: Path) -> dict:
    """Primary analysis layer: deterministic OpenCV metrics."""
    import cv2
    import numpy as np
    img = cv2.imread(str(image_path))
    if img is None:
        return {"error": "cannot read image"}

    h, w = img.shape[:2]

    # Green (friendly) detection: #05ffa1 in BGR = (161, 255, 5)
    green_bgr = np.array([161, 255, 5])
    green_lo = np.clip(green_bgr.astype(int) - 50, 0, 255).astype(np.uint8)
    green_hi = np.clip(green_bgr.astype(int) + 50, 0, 255).astype(np.uint8)
    green_mask = cv2.inRange(img, green_lo, green_hi)
    green_contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    green_blobs = [c for c in green_contours if cv2.contourArea(c) >= 15]

    # Red (hostile) detection: #ff2a6d in BGR = (109, 42, 255)
    red_bgr = np.array([109, 42, 255])
    red_lo = np.clip(red_bgr.astype(int) - 60, 0, 255).astype(np.uint8)
    red_hi = np.clip(red_bgr.astype(int) + 60, 0, 255).astype(np.uint8)
    red_mask = cv2.inRange(img, red_lo, red_hi)
    red_contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    red_blobs = [c for c in red_contours if cv2.contourArea(c) >= 10]

    # Spatial spread of green blobs
    green_centers = []
    for c in green_blobs:
        M = cv2.moments(c)
        if M["m00"] > 0:
            green_centers.append((int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])))
    spread = 0
    if len(green_centers) >= 2:
        xs = [p[0] for p in green_centers]
        ys = [p[1] for p in green_centers]
        spread = max(max(xs) - min(xs), max(ys) - min(ys))

    # Map content (non-black pixels in center 50%)
    cx, cy = w // 4, h // 4
    center = img[cy:cy + h // 2, cx:cx + w // 2]
    gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
    content_pct = round(np.count_nonzero(gray > 15) / gray.size * 100, 1)

    return {
        "friendly_count": len(green_blobs),
        "hostile_count": len(red_blobs),
        "friendly_spread_px": spread,
        "map_content_pct": content_pct,
        "image_size": f"{w}x{h}",
        "green_centers": green_centers[:20],
    }


def run_vision_pass(
    fleet: OllamaFleet, model: str, image_path: Path, prompt: str,
    timeout: float = 60, prefer_host: str | None = None,
) -> dict:
    """Run a single vision model pass on an image (resized for speed)."""
    resized = _resize_for_vision(image_path)
    t0 = time.monotonic()
    try:
        result = fleet.generate(
            model=model,
            prompt=prompt,
            image_path=resized,
            timeout=timeout,
            prefer_host=prefer_host,
        )
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "response": result["response"],
            "host": result["host"],
            "elapsed_ms": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "response": f"[error: {e}]",
            "host": "failed",
            "elapsed_ms": round(elapsed, 1),
        }


def run_deep_analysis(
    fleet: OllamaFleet, model: str,
    llava_desc: str, qwen3vl_analysis: str,
    timeout: float = 300,
) -> dict:
    """Run deep text analysis using qwen3.5:27b (text-only model)."""
    prompt = DEEP_PROMPT_TEMPLATE.format(
        llava_description=llava_desc,
        qwen3vl_analysis=qwen3vl_analysis,
    )
    t0 = time.monotonic()
    try:
        result = fleet.generate(
            model=model,
            prompt=prompt,
            timeout=timeout,
        )
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "response": result["response"],
            "host": result["host"],
            "elapsed_ms": round(elapsed, 1),
        }
    except Exception as e:
        elapsed = (time.monotonic() - t0) * 1000
        return {
            "response": f"[error: {e}]",
            "host": "failed",
            "elapsed_ms": round(elapsed, 1),
        }


def parse_tactical_rating(text: str) -> int | None:
    """Extract a numeric tactical rating (1-10) from analysis text."""
    import re
    # Look for patterns like "rating: 7", "7/10", "score: 8"
    patterns = [
        r'(?:rating|score|overall)[:\s]*(\d+)\s*/?\s*10',
        r'(?:rating|score|overall)[:\s]*(\d+)',
        r'(\d+)\s*/\s*10',
        r'(?:tactical rating)[:\s]*(\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 10:
                return val
    return None


def parse_deep_analysis(text: str) -> dict:
    """Parse structured fields from deep analysis text."""
    rating = parse_tactical_rating(text)

    # Extract sections by looking for common headings
    sections = {
        "coverage_assessment": "",
        "identified_gaps": [],
        "approach_vulnerability": "",
        "recommendations": [],
        "overall_summary": "",
    }

    lines = text.split("\n")
    current_section = None

    for line in lines:
        lower = line.lower().strip()
        if "coverage" in lower and ("assessment" in lower or ":" in lower):
            current_section = "coverage_assessment"
            continue
        elif "gap" in lower and (":" in lower or "identif" in lower):
            current_section = "identified_gaps"
            continue
        elif ("approach" in lower or "vulnerab" in lower) and ":" in lower:
            current_section = "approach_vulnerability"
            continue
        elif "recommend" in lower and ":" in lower:
            current_section = "recommendations"
            continue
        elif "summary" in lower and ":" in lower:
            current_section = "overall_summary"
            continue

        if current_section and line.strip():
            stripped = line.strip().lstrip("- *0123456789.)")
            if stripped:
                if current_section in ("identified_gaps", "recommendations"):
                    sections[current_section].append(stripped.strip())
                elif sections[current_section]:
                    sections[current_section] += " " + stripped.strip()
                else:
                    sections[current_section] = stripped.strip()

    return {
        "tactical_rating": rating,
        **sections,
    }


def analyze_image(
    fleet: OllamaFleet, image_path: Path,
    vision_model: str, direct_vision_model: str, deep_model: str,
) -> dict:
    """Run the full analysis pipeline: OpenCV (primary) + vision models (advisory)."""
    print(f"  Analyzing: {image_path.name}")
    sys.stdout.flush()

    # Layer 0: OpenCV (deterministic, instant, primary)
    t0_cv = time.monotonic()
    cv_metrics = opencv_analyze(image_path)
    cv_ms = (time.monotonic() - t0_cv) * 1000
    print(f"    OpenCV        -> {cv_metrics['friendly_count']} friendly, {cv_metrics['hostile_count']} hostile, spread={cv_metrics['friendly_spread_px']}px ({cv_ms:.0f}ms)")
    sys.stdout.flush()

    hosts = fleet.hosts
    host1 = hosts[0].name if hosts else None
    host2 = hosts[1].name if len(hosts) > 1 else host1

    # Layer 1 + 2: Run llava and qwen3-vl in parallel (resized images, 60s timeout)
    llava_result = {}
    qwen3vl_result = {}

    with ThreadPoolExecutor(max_workers=2) as pool:
        llava_future = pool.submit(
            run_vision_pass, fleet, vision_model, image_path,
            LLAVA_PROMPT, 60, host1,
        )
        qwen3vl_future = pool.submit(
            run_vision_pass, fleet, direct_vision_model, image_path,
            QWEN3VL_PROMPT, 60, host2,
        )

        llava_result = llava_future.result()
        qwen3vl_result = qwen3vl_future.result()

    print(f"    llava:7b      -> {llava_result['host']} ({llava_result['elapsed_ms']:.0f}ms)")
    print(f"    qwen3-vl:8b   -> {qwen3vl_result['host']} ({qwen3vl_result['elapsed_ms']:.0f}ms)")
    sys.stdout.flush()

    # Layer 3: Deep synthesis with qwen3.5:27b (text-only, 120s timeout)
    deep_result = run_deep_analysis(
        fleet, deep_model,
        llava_result["response"],
        qwen3vl_result["response"],
        timeout=120,
    )
    print(f"    qwen3.5:27b   -> {deep_result['host']} ({deep_result['elapsed_ms']:.0f}ms)")
    sys.stdout.flush()

    parsed = parse_deep_analysis(deep_result["response"])

    return {
        "image": image_path.name,
        "image_path": str(image_path),
        "opencv_metrics": cv_metrics,
        "llava_description": llava_result["response"],
        "qwen3vl_analysis": qwen3vl_result["response"],
        "deep_analysis": {
            **parsed,
            "raw_response": deep_result["response"],
        },
        "timing": {
            "opencv_ms": round(cv_ms, 1),
            "llava_ms": llava_result["elapsed_ms"],
            "qwen3vl_ms": qwen3vl_result["elapsed_ms"],
            "qwen35_ms": deep_result["elapsed_ms"],
        },
        "hosts": {
            "llava": llava_result["host"],
            "qwen3vl": qwen3vl_result["host"],
            "qwen35": deep_result["host"],
        },
    }


def generate_html_report(results: list[dict], output_dir: Path) -> Path:
    """Generate a self-contained HTML report from analysis results."""
    import base64
    import html as html_mod

    report_path = output_dir / "deep-analysis-report.html"

    # Build image cards
    cards = []
    for r in results:
        rating = r["deep_analysis"].get("tactical_rating")
        rating_str = f"{rating}/10" if rating else "N/A"

        # Embed thumbnail
        img_tag = ""
        img_path = Path(r["image_path"])
        if img_path.exists():
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            img_tag = f'<img src="data:image/png;base64,{b64}" style="max-width:400px;border:1px solid #00f0ff33;border-radius:4px;">'

        gaps = r["deep_analysis"].get("identified_gaps", [])
        recs = r["deep_analysis"].get("recommendations", [])

        gaps_html = "".join(f"<li>{html_mod.escape(g)}</li>" for g in gaps[:5])
        recs_html = "".join(f"<li>{html_mod.escape(rec)}</li>" for rec in recs[:5])

        timing = r.get("timing", {})
        total_ms = sum(timing.values())

        cards.append(f"""
        <div class="card">
            <h3>{html_mod.escape(r['image'])}</h3>
            <div style="display:flex;gap:20px;flex-wrap:wrap;">
                <div>{img_tag}</div>
                <div style="flex:1;min-width:300px;">
                    <div class="rating">Tactical Rating: {rating_str}</div>
                    <h4>Coverage</h4>
                    <p>{html_mod.escape(r['deep_analysis'].get('coverage_assessment', 'N/A')[:300])}</p>
                    <h4>Gaps</h4>
                    <ul>{gaps_html if gaps_html else '<li>None identified</li>'}</ul>
                    <h4>Recommendations</h4>
                    <ul>{recs_html if recs_html else '<li>None</li>'}</ul>
                    <div class="timing">
                        llava: {timing.get('llava_ms', 0):.0f}ms |
                        qwen3-vl: {timing.get('qwen3vl_ms', 0):.0f}ms |
                        qwen3.5: {timing.get('qwen35_ms', 0):.0f}ms |
                        total: {total_ms:.0f}ms
                    </div>
                </div>
            </div>
            <details><summary>llava:7b Description</summary>
                <pre>{html_mod.escape(r['llava_description'][:1000])}</pre>
            </details>
            <details><summary>qwen3-vl:8b Analysis</summary>
                <pre>{html_mod.escape(r['qwen3vl_analysis'][:1000])}</pre>
            </details>
            <details><summary>qwen3.5:27b Full Analysis</summary>
                <pre>{html_mod.escape(r['deep_analysis'].get('raw_response', '')[:2000])}</pre>
            </details>
        </div>
        """)

    cards_html = "\n".join(cards)

    # Compute summary stats
    ratings = [r["deep_analysis"].get("tactical_rating") for r in results]
    valid_ratings = [r for r in ratings if r is not None]
    avg_rating = sum(valid_ratings) / len(valid_ratings) if valid_ratings else 0

    total_time = sum(sum(r.get("timing", {}).values()) for r in results)

    report_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Deep Tactical Analysis Report</title>
<style>
body {{ background: #0a0a0f; color: #c8d0dc; font-family: 'Inter', sans-serif; margin: 0; padding: 20px; }}
h1 {{ color: #00f0ff; border-bottom: 1px solid #00f0ff33; padding-bottom: 10px; }}
h2 {{ color: #05ffa1; }}
h3 {{ color: #00f0ff; margin-top: 0; }}
h4 {{ color: #fcee0a; margin: 8px 0 4px; }}
.summary {{ background: #12121a; border: 1px solid #00f0ff22; border-radius: 8px; padding: 20px; margin: 20px 0; display: flex; gap: 40px; }}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 2em; font-weight: 700; color: #00f0ff; }}
.stat-label {{ color: #8892a4; font-size: 0.9em; }}
.card {{ background: #0e0e14; border: 1px solid #00f0ff15; border-radius: 8px; padding: 20px; margin: 16px 0; }}
.rating {{ font-size: 1.4em; font-weight: 700; color: #05ffa1; margin: 8px 0; }}
.timing {{ color: #8892a4; font-size: 0.85em; margin-top: 12px; font-family: 'JetBrains Mono', monospace; }}
details {{ margin: 8px 0; }}
summary {{ cursor: pointer; color: #00f0ff; }}
pre {{ background: #1a1a2e; padding: 12px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; font-size: 0.85em; max-height: 400px; overflow-y: auto; }}
ul {{ padding-left: 20px; }}
li {{ margin: 4px 0; }}
</style>
</head>
<body>
<h1>Deep Tactical Analysis Report</h1>
<div class="summary">
    <div class="stat">
        <div class="stat-value">{len(results)}</div>
        <div class="stat-label">Screenshots Analyzed</div>
    </div>
    <div class="stat">
        <div class="stat-value">{avg_rating:.1f}/10</div>
        <div class="stat-label">Avg Tactical Rating</div>
    </div>
    <div class="stat">
        <div class="stat-value">{total_time/1000:.1f}s</div>
        <div class="stat-label">Total Analysis Time</div>
    </div>
    <div class="stat">
        <div class="stat-value">{len(valid_ratings)}/{len(results)}</div>
        <div class="stat-label">Rated Images</div>
    </div>
</div>
<h2>Per-Image Analysis</h2>
{cards_html}
</body>
</html>"""

    report_path.write_text(report_html)
    return report_path


def main():
    parser = argparse.ArgumentParser(
        description="Analyze combat test screenshots with multi-model LLM pipeline",
    )
    parser.add_argument("screenshot_dir", type=Path, help="Directory containing screenshots")
    parser.add_argument("--model", default="qwen3.5:27b", help="Deep analysis model")
    parser.add_argument("--vision-model", default="llava:7b", help="Vision description model")
    parser.add_argument("--direct-vision", default="qwen3-vl:8b", help="Direct vision model")
    parser.add_argument("--output", type=Path, default=None, help="Output directory")
    parser.add_argument("--report", action="store_true", help="Generate HTML report")
    parser.add_argument("--json", action="store_true", dest="output_json", help="Output JSON")
    args = parser.parse_args()

    if not args.screenshot_dir.is_dir():
        print(f"Error: {args.screenshot_dir} is not a directory")
        sys.exit(1)

    output_dir = args.output or (args.screenshot_dir / "analysis")
    output_dir.mkdir(parents=True, exist_ok=True)

    images = find_screenshots(args.screenshot_dir)
    if not images:
        print(f"No screenshots found in {args.screenshot_dir}")
        sys.exit(1)

    print(f"Found {len(images)} screenshots in {args.screenshot_dir}")

    # Discover fleet
    fleet = OllamaFleet()
    print(fleet.status())
    print()

    # Verify models
    for model in [args.vision_model, args.direct_vision, args.model]:
        hosts = fleet.hosts_with_model(model)
        if not hosts:
            print(f"WARNING: No host has model '{model}'")
        else:
            print(f"  {model}: available on {[h.name for h in hosts]}")
    print()

    # Skip annotated duplicates (they have bounding boxes that confuse vision models)
    images = [p for p in images if "_annotated" not in p.stem]
    print(f"Analyzing {len(images)} images (skipping annotated versions)")
    print()

    # Analyze each image with progress tracking
    results = []
    t0 = time.monotonic()
    for idx, image_path in enumerate(images, 1):
        elapsed_so_far = time.monotonic() - t0
        avg_per = elapsed_so_far / max(idx - 1, 1) if idx > 1 else 0
        eta = avg_per * (len(images) - idx + 1) if idx > 1 else 0
        print(f"\n[{idx}/{len(images)}] {image_path.name}  (elapsed: {elapsed_so_far:.0f}s, ETA: {eta:.0f}s)")
        sys.stdout.flush()
        try:
            result = analyze_image(
                fleet, image_path,
                args.vision_model, args.direct_vision, args.model,
            )
            results.append(result)
            rating = result.get("deep_analysis", {}).get("tactical_rating")
            t = result.get("timing", {})
            total_t = sum(t.values())
            print(f"    Rating: {rating}/10  Total: {total_t:.0f}ms")
        except Exception as e:
            print(f"    ERROR: {e}")
            results.append({
                "image": image_path.name,
                "image_path": str(image_path),
                "error": str(e),
                "llava_description": "",
                "qwen3vl_analysis": "",
                "deep_analysis": {},
                "timing": {},
                "hosts": {},
            })
        sys.stdout.flush()

    total_time = time.monotonic() - t0
    print(f"\nAnalyzed {len(results)} images in {total_time:.1f}s")

    # Save JSON
    if args.output_json or args.report:
        json_path = output_dir / "deep-analysis.json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"JSON saved: {json_path}")

    # Generate HTML report
    if args.report:
        report_path = generate_html_report(results, output_dir)
        print(f"HTML report: {report_path}")

    # Print summary
    ratings = [r.get("deep_analysis", {}).get("tactical_rating") for r in results]
    valid = [r for r in ratings if r is not None]
    if valid:
        print(f"\nTactical ratings: {valid}")
        print(f"Average rating: {sum(valid)/len(valid):.1f}/10")
    else:
        print("\nNo tactical ratings extracted")


if __name__ == "__main__":
    main()
