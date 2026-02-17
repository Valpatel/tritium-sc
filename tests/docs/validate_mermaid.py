#!/usr/bin/env python3
"""Validate all Mermaid diagrams in docs/ by rendering them in a real browser.

Uses Playwright to load mermaid.js, render each diagram, and capture
screenshots. Reports pass/fail for each diagram and saves visual output
for human review.

Usage:
    .venv/bin/python3 tests/docs/validate_mermaid.py

    # Keep browser open for manual inspection
    .venv/bin/python3 tests/docs/validate_mermaid.py --headed

    # Output to specific directory
    .venv/bin/python3 tests/docs/validate_mermaid.py --output /tmp/renders

Requirements:
    pip install playwright
    playwright install chromium
"""
import argparse
import json
import re
import sys
import textwrap
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed.")
    print("  pip install playwright && playwright install chromium")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
DEFAULT_OUTPUT = PROJECT_ROOT / "tests" / "docs" / ".renders"

# All markdown files that may contain Mermaid diagrams
DOC_FILES = sorted(DOCS_DIR.glob("*.md"))

VALIDATION_HTML = textwrap.dedent("""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<style>
body { background: #1a1a2e; color: #e0e0e0; font-family: monospace; padding: 20px; }
.diagram { background: #16213e; border: 1px solid #0f3460; border-radius: 8px;
           padding: 20px; margin: 20px 0; }
.title { color: #00f0ff; font-size: 14px; margin-bottom: 10px; }
.error { color: #ff2a6d; font-weight: bold; }
.ok { color: #05ffa1; }
#summary { position: fixed; top: 10px; right: 10px; background: #0f3460;
           padding: 15px; border-radius: 8px; z-index: 1000; }
</style>
</head>
<body>
<h1>TRITIUM-SC Mermaid Diagram Validation</h1>
<div id="summary"></div>
<div id="diagrams"></div>
<script>
mermaid.initialize({ startOnLoad: false, theme: 'dark',
  themeVariables: { primaryColor: '#16213e', primaryTextColor: '#e0e0e0',
    primaryBorderColor: '#0f3460', lineColor: '#00f0ff',
    secondaryColor: '#1a1a2e', tertiaryColor: '#0f3460' }
});
window.diagrams = [];
window.results = [];
window.addDiagram = (name, source, line, code) =>
  window.diagrams.push({ name, source, line, code });

window.renderAll = async function() {
  const container = document.getElementById('diagrams');
  let pass = 0, fail = 0;
  for (const d of window.diagrams) {
    const wrapper = document.createElement('div');
    wrapper.className = 'diagram';
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = d.source + ':' + d.line + ' — ' + d.name;
    wrapper.appendChild(title);
    const renderDiv = document.createElement('div');
    renderDiv.id = 'mermaid-' + d.name.replace(/[^a-zA-Z0-9]/g, '_');
    wrapper.appendChild(renderDiv);
    const status = document.createElement('div');
    try {
      const { svg } = await mermaid.render(renderDiv.id + '-svg', d.code);
      renderDiv.innerHTML = svg;
      const svgEl = renderDiv.querySelector('svg');
      const w = svgEl ? svgEl.viewBox.baseVal.width || parseInt(svgEl.getAttribute('width') || '0') : 0;
      const h = svgEl ? svgEl.viewBox.baseVal.height || parseInt(svgEl.getAttribute('height') || '0') : 0;
      status.className = 'ok';
      status.textContent = 'OK (' + Math.round(w) + 'x' + Math.round(h) + ')';
      pass++;
      window.results.push({ name: d.name, source: d.source, line: d.line, status: 'OK', width: Math.round(w), height: Math.round(h) });
    } catch (e) {
      status.className = 'error';
      status.textContent = 'FAIL: ' + e.message;
      fail++;
      window.results.push({ name: d.name, source: d.source, line: d.line, status: 'FAIL', error: e.message });
    }
    wrapper.appendChild(status);
    container.appendChild(wrapper);
  }
  document.getElementById('summary').innerHTML =
    '<b>Results:</b> <span class="ok">' + pass + ' passed</span> / ' +
    '<span class="error">' + fail + ' failed</span> / ' + window.diagrams.length + ' total';
  return window.results;
};
</script>
</body>
</html>
""")


def extract_diagrams(files):
    """Extract all mermaid code blocks from markdown files."""
    pattern = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
    diagrams = []
    for fpath in files:
        if not fpath.exists():
            continue
        content = fpath.read_text()
        for i, match in enumerate(pattern.finditer(content)):
            line_num = content[: match.start()].count("\n") + 1
            code = match.group(1).strip()
            name = f"{fpath.stem}_{i + 1}_line{line_num}"
            diagrams.append(
                {"name": name, "source": fpath.name, "line": line_num, "code": code}
            )
    return diagrams


def main():
    parser = argparse.ArgumentParser(description="Validate Mermaid diagrams in docs/")
    parser.add_argument(
        "--output", "-o", type=Path, default=DEFAULT_OUTPUT, help="Output directory"
    )
    parser.add_argument(
        "--headed", action="store_true", help="Run browser in headed mode"
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)

    diagrams = extract_diagrams(DOC_FILES)
    if not diagrams:
        print("No Mermaid diagrams found in docs/")
        return 0

    print(f"Found {len(diagrams)} Mermaid diagrams across {len(DOC_FILES)} doc files\n")

    # Write validation HTML
    html_path = args.output / "validate.html"
    html_path.write_text(VALIDATION_HTML)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        page.goto(f"file://{html_path}")
        page.wait_for_load_state("networkidle")

        for d in diagrams:
            page.evaluate(
                "([n,s,l,c]) => window.addDiagram(n,s,l,c)",
                [d["name"], d["source"], d["line"], d["code"]],
            )

        results = page.evaluate("() => window.renderAll()")
        page.wait_for_timeout(2000)

        # Screenshots
        page.screenshot(path=str(args.output / "all_diagrams.png"), full_page=True)
        containers = page.query_selector_all(".diagram")
        for i, container in enumerate(containers):
            if i < len(diagrams):
                container.screenshot(
                    path=str(args.output / f"{diagrams[i]['name']}.png")
                )

        if args.headed:
            print("\nBrowser open for inspection. Press Enter to close...")
            input()

        browser.close()

    # Report
    passed = [r for r in results if r["status"] == "OK"]
    failed = [r for r in results if r["status"] == "FAIL"]

    print(f"{'=' * 70}")
    print(f"  RESULTS: {len(passed)}/{len(results)} passed, {len(failed)} failed")
    print(f"{'=' * 70}\n")

    for r in results:
        if r["status"] == "OK":
            print(f"  [OK]   {r['source']}:{r['line']} ({r.get('width', '?')}x{r.get('height', '?')})")
        else:
            print(f"  [FAIL] {r['source']}:{r['line']}")
            err = r.get("error", "unknown")[:200]
            print(f"         {err}")

    print(f"\nScreenshots: {args.output}/")

    # Save JSON results
    (args.output / "results.json").write_text(json.dumps(results, indent=2))

    if failed:
        print(f"\n{len(failed)} diagram(s) FAILED — see screenshots for details")
        return 1

    print("\nAll diagrams render successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
