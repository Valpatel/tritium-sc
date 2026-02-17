#!/usr/bin/env python3
"""Take a screenshot of a TRITIUM-SC view and analyze it with a local vision model.

Usage:
    python3 tests/ui/screenshot_and_analyze.py [view] [--url URL] [--model MODEL]

Arguments:
    view    - View to screenshot: war, assets, amy, grid (default: war)
    --url   - Server URL (default: http://localhost:8000)
    --model - Ollama vision model (default: llava:7b)
    --ocr   - Run OCR pass with glm-ocr:latest after vision analysis
    --save  - Save screenshot to this path (default: /tmp/tritium-{view}.png)

Requires: Node.js with Playwright (tests/e2e/node_modules/), requests
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Resolve paths relative to this file
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_E2E_DIR = _PROJECT_ROOT / "tests" / "e2e"
_NODE_MODULES = _E2E_DIR / "node_modules"

# Playwright script template (runs in Node)
_PW_SCRIPT = """
const {{ chromium }} = require('playwright');

(async () => {{
    const browser = await chromium.launch({{
        headless: true,
        args: ['--disable-gpu', '--no-sandbox'],
    }});
    const context = await browser.newContext({{
        viewport: {{ width: 1920, height: 1080 }},
        deviceScaleFactor: 1,
    }});
    const page = await context.newPage();

    // Suppress dialog boxes
    page.on('dialog', async dialog => await dialog.dismiss());

    await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 30000 }});

    // Wait for initial render
    await page.waitForTimeout(1500);

    // Switch to the requested view
    const view = '{view}';
    if (view !== 'grid') {{
        const shortcutMap = {{
            'war': 'w', 'assets': 'a', 'amy': 'y', 'targets': 't',
            'zones': 'z', 'player': 'p', '3d': 'd', 'analytics': 'n',
            'scenarios': 's',
        }};
        const key = shortcutMap[view] || view[0];
        await page.keyboard.press(key);
    }}

    // Wait for view to render
    await page.waitForTimeout({wait_ms});

    // Take screenshot
    await page.screenshot({{ path: '{output}', fullPage: false }});
    console.log('Screenshot saved to {output}');

    await browser.close();
    process.exit(0);
}})().catch(err => {{
    console.error(err.message);
    process.exit(1);
}});
"""


def take_screenshot(url: str, view: str, output: str, wait_ms: int = 3000) -> str:
    """Take a screenshot using Playwright via Node subprocess. Returns output path."""
    script = _PW_SCRIPT.format(url=url, view=view, output=output, wait_ms=wait_ms)
    script_path = Path("/tmp/tritium_screenshot.js")
    script_path.write_text(script)

    # Set NODE_PATH so node can find playwright in tests/e2e/node_modules
    env = os.environ.copy()
    env["NODE_PATH"] = str(_NODE_MODULES)

    result = subprocess.run(
        ["node", str(script_path)],
        capture_output=True, text=True, timeout=60,
        env=env,
    )
    if result.returncode != 0:
        print(f"Playwright error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    return output


def analyze_with_ollama(image_path: str, model: str, prompt: str) -> str:
    """Send image to Ollama vision model for analysis."""
    import requests

    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "images": [img_b64],
            "stream": False,
            "options": {"num_predict": 1024, "temperature": 0.1},
        },
        timeout=600,  # qwen3-vl:32b can take 5+ min per image
    )
    resp.raise_for_status()
    return resp.json().get("response", "")


def main():
    parser = argparse.ArgumentParser(description="Screenshot + local vision analysis")
    parser.add_argument("view", nargs="?", default="war", help="View to screenshot")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--model", default="llava:7b", help="Ollama vision model")
    parser.add_argument("--ocr", action="store_true", help="Also run OCR pass")
    parser.add_argument("--save", default=None, help="Screenshot output path")
    parser.add_argument("--wait", type=int, default=3000, help="Wait ms after view switch")
    parser.add_argument("--prompt", default=None, help="Custom analysis prompt")
    args = parser.parse_args()

    output = args.save or f"/tmp/tritium-{args.view}.png"

    print(f"Taking screenshot of '{args.view}' view...")
    take_screenshot(args.url, args.view, output, args.wait)
    print(f"Screenshot saved: {output}")

    # Vision analysis
    vision_prompt = args.prompt or (
        "Analyze this screenshot of a tactical/RTS game interface. Describe:\n"
        "1. What UI elements are visible (buttons, panels, maps, HUD)\n"
        "2. Are there any visible units/targets on the map (colored dots, icons, shapes)\n"
        "3. Is there a grid or map background visible\n"
        "4. What text labels or buttons can you read\n"
        "5. Any obvious UI problems (blank areas, missing content, broken layout)\n"
        "Be specific and concise."
    )

    print(f"\nAnalyzing with {args.model}...")
    t0 = time.time()
    analysis = analyze_with_ollama(output, args.model, vision_prompt)
    dt = time.time() - t0
    print(f"Analysis ({dt:.1f}s):\n{analysis}")

    # Optional OCR pass
    if args.ocr:
        print(f"\nRunning OCR with glm-ocr:latest...")
        t0 = time.time()
        ocr_result = analyze_with_ollama(
            output, "glm-ocr:latest",
            "Extract ALL visible text from this screenshot. List each text element on its own line."
        )
        dt = time.time() - t0
        print(f"OCR ({dt:.1f}s):\n{ocr_result}")


if __name__ == "__main__":
    main()
