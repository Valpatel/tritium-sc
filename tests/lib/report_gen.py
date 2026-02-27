"""HTML Report Generator — Cybercore v2 styled interactive test reports.

Generates self-contained HTML reports from ResultsDB data with:
- Cybercore v2 styling (Inter + JetBrains Mono, grid bg, scanlines, panels)
- Tab navigation (Results | Screenshots | Game Loop | Metrics | Trend)
- Collapsible test details
- Screenshot lightbox (click thumbnail -> fullscreen overlay)
- Game loop timeline visualization
- Metrics dashboard
- JSON metrics export
- Optional LLM executive summary via OllamaFleet
"""

from __future__ import annotations

import base64
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.inference.fleet import OllamaFleet
from tests.lib.results_db import ResultsDB


# -----------------------------------------------------------------------
# Cybercore v2 CSS — inlined for self-contained reports
# -----------------------------------------------------------------------

_CSS = """
/* === Reset + Fonts === */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

:root {
    --cyan: #00f0ff;
    --cyan-dim: #0e7490;
    --cyan-glow: rgba(0, 240, 255, 0.15);
    --green: #05ffa1;
    --amber: #fcee0a;
    --magenta: #ff2a6d;
    --void: #0a0a0f;
    --surface-1: #0e0e14;
    --surface-2: #12121a;
    --surface-3: #1a1a2e;
    --border: rgba(0, 240, 255, 0.08);
    --text-primary: #c8d0dc;
    --text-secondary: #8892a4;
    --text-muted: #5a6577;
    --text-dim: #4a5568;
    --text-ghost: #3a4250;
    --radius-sm: 4px;
    --radius-md: 6px;
    --radius-lg: 8px;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    background: var(--void);
    color: var(--text-primary);
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
    /* Grid background */
    background-image:
        linear-gradient(rgba(0, 240, 255, 0.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0, 240, 255, 0.025) 1px, transparent 1px);
    background-size: 80px 80px;
}

/* Scanline overlay */
body::before {
    content: '';
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0, 0, 0, 0.03) 2px,
        rgba(0, 0, 0, 0.03) 4px
    );
    pointer-events: none;
    z-index: 9999;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

/* === Header === */
.cc-header {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 16px 24px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 20px;
    position: relative;
}
.cc-header::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--cyan-glow), transparent);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
}
.header-logo {
    font-family: 'JetBrains Mono', monospace;
    font-size: 20px;
    font-weight: 700;
    color: var(--cyan);
    letter-spacing: 2px;
    white-space: nowrap;
}
.header-info {
    flex: 1;
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
}
.header-tag {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--surface-3);
    padding: 3px 10px;
    border-radius: var(--radius-sm);
    border: 1px solid var(--border);
}
.header-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 600;
    padding: 4px 14px;
    border-radius: var(--radius-sm);
}
.header-badge.pass {
    color: var(--green);
    background: rgba(5, 255, 161, 0.1);
    border: 1px solid rgba(5, 255, 161, 0.25);
}
.header-badge.fail {
    color: var(--magenta);
    background: rgba(255, 42, 109, 0.1);
    border: 1px solid rgba(255, 42, 109, 0.25);
}

/* === Summary Dashboard === */
.summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}
.stat-card {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 14px;
    text-align: center;
    position: relative;
}
.stat-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--cyan-glow), transparent);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    opacity: 0;
    transition: opacity 0.3s ease;
}
.stat-card:hover::before { opacity: 1; }
.stat-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 26px;
    font-weight: 700;
    line-height: 1.2;
}
.stat-value.pass { color: var(--green); }
.stat-value.fail { color: var(--magenta); }
.stat-value.skip { color: var(--amber); }
.stat-value.neutral { color: var(--cyan); }
.stat-label {
    font-size: 10px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--text-dim);
    margin-top: 4px;
}

/* === Tab Navigation === */
.tab-bar {
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 4px;
}
.tab-btn {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.5px;
    color: var(--text-muted);
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--radius-md);
    padding: 8px 16px;
    cursor: pointer;
    transition: all 0.2s ease;
    text-transform: uppercase;
}
.tab-btn:hover {
    color: var(--text-primary);
    background: var(--surface-2);
}
.tab-btn.active {
    color: var(--cyan);
    background: var(--surface-2);
    border-color: rgba(0, 240, 255, 0.15);
    box-shadow: 0 0 12px rgba(0, 240, 255, 0.05);
}
.tab-content { display: none; }
.tab-content.active { display: block; }

/* === Test Result Cards === */
.result-card {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    margin-bottom: 8px;
    overflow: hidden;
    transition: border-color 0.2s ease;
}
.result-card:hover {
    border-color: rgba(0, 240, 255, 0.15);
}
.result-card.passed {
    border-left: 3px solid var(--green);
}
.result-card.failed {
    border-left: 3px solid var(--magenta);
}
.result-header {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    cursor: pointer;
    user-select: none;
}
.result-header:hover {
    background: rgba(0, 240, 255, 0.02);
}
.result-badge {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 10px;
    border-radius: var(--radius-sm);
    text-transform: uppercase;
    flex-shrink: 0;
}
.result-badge.pass {
    color: var(--green);
    background: rgba(5, 255, 161, 0.1);
    border: 1px solid rgba(5, 255, 161, 0.2);
}
.result-badge.fail {
    color: var(--magenta);
    background: rgba(255, 42, 109, 0.1);
    border: 1px solid rgba(255, 42, 109, 0.2);
}
.result-name {
    flex: 1;
    font-weight: 600;
    font-size: 13px;
}
.result-duration {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-dim);
}
.result-chevron {
    color: var(--text-dim);
    font-size: 12px;
    transition: transform 0.2s ease;
}
.result-card.expanded .result-chevron {
    transform: rotate(90deg);
}
.result-details {
    display: none;
    padding: 0 16px 14px 16px;
    border-top: 1px solid var(--border);
}
.result-card.expanded .result-details {
    display: block;
}
.result-details pre {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    padding: 10px 14px;
    margin-top: 10px;
    overflow-x: auto;
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 400px;
    overflow-y: auto;
}

/* === Screenshots === */
.screenshot-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 12px;
}
.screenshot-card {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    overflow: hidden;
    cursor: pointer;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.screenshot-card:hover {
    border-color: rgba(0, 240, 255, 0.2);
    box-shadow: 0 0 20px rgba(0, 240, 255, 0.05);
}
.screenshot-card img {
    width: 100%;
    display: block;
}
.screenshot-meta {
    padding: 10px 14px;
}
.screenshot-meta .phase-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    color: var(--cyan);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.screenshot-meta .test-label {
    font-size: 12px;
    color: var(--text-secondary);
    margin-top: 2px;
}

/* === Lightbox === */
.lightbox {
    display: none;
    position: fixed;
    top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0, 0, 0, 0.92);
    z-index: 10000;
    cursor: pointer;
    align-items: center;
    justify-content: center;
}
.lightbox.active {
    display: flex;
}
.lightbox img {
    max-width: 95vw;
    max-height: 95vh;
    border: 1px solid rgba(0, 240, 255, 0.15);
    border-radius: var(--radius-md);
}

/* === Game Loop Timeline === */
.timeline {
    position: relative;
    margin: 20px 0;
}
.timeline-track {
    position: relative;
    display: flex;
    gap: 0;
    margin-bottom: 24px;
}
.timeline-phase {
    flex: 1;
    position: relative;
    padding: 12px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    text-align: center;
    transition: border-color 0.2s ease;
}
.timeline-phase:first-child {
    border-radius: var(--radius-md) 0 0 var(--radius-md);
}
.timeline-phase:last-child {
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
}
.timeline-phase:hover {
    border-color: rgba(0, 240, 255, 0.2);
}
.timeline-phase::after {
    content: '';
    position: absolute;
    right: -8px;
    top: 50%;
    transform: translateY(-50%);
    border: 6px solid transparent;
    border-left-color: var(--cyan-dim);
    z-index: 1;
}
.timeline-phase:last-child::after {
    display: none;
}
.phase-name {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    color: var(--cyan);
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.phase-detail {
    font-size: 11px;
    color: var(--text-secondary);
    margin-top: 4px;
}
.timeline-events {
    background: var(--surface-1);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 14px;
    max-height: 400px;
    overflow-y: auto;
}
.timeline-event {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    color: var(--text-secondary);
    padding: 3px 0;
    border-bottom: 1px solid rgba(0, 240, 255, 0.03);
}
.timeline-event:last-child {
    border-bottom: none;
}
.timeline-event .event-phase {
    color: var(--cyan);
    font-weight: 600;
}
.timeline-event .event-time {
    color: var(--text-dim);
}
.timeline-screenshots {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
    margin-top: 16px;
}

/* === Metrics Dashboard === */
.metrics-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 14px;
}
.metric-panel {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 16px;
}
.metric-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    font-weight: 600;
    color: var(--cyan);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 10px;
}
.metric-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
    border-bottom: 1px solid rgba(0, 240, 255, 0.03);
}
.metric-row:last-child { border-bottom: none; }
.metric-key {
    font-size: 12px;
    color: var(--text-secondary);
}
.metric-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
}
.metric-val.ok { color: var(--green); }
.metric-val.warn { color: var(--amber); }
.metric-val.bad { color: var(--magenta); }

/* Checklist items */
.check-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 3px 0;
    font-size: 12px;
}
.check-icon { font-size: 14px; }
.check-icon.found { color: var(--green); }
.check-icon.missing { color: var(--magenta); }
.check-label { color: var(--text-secondary); }

/* === Trend Chart === */
.trend-chart {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 16px;
}
.trend-chart svg { display: block; }
.trend-tooltip {
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
}

/* === Executive Summary === */
.exec-summary {
    background: linear-gradient(135deg, var(--surface-2) 0%, var(--surface-1) 100%);
    border: 1px solid rgba(0, 240, 255, 0.12);
    border-radius: var(--radius-md);
    padding: 16px;
    margin-bottom: 20px;
    white-space: pre-wrap;
    font-size: 13px;
    color: var(--text-secondary);
    line-height: 1.7;
}

/* === Section Headers === */
.section-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 14px;
    font-weight: 600;
    color: var(--cyan);
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-bottom: 14px;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(0, 240, 255, 0.08);
}

/* === Overlap Diagnostic === */
.overlap-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
}
.overlap-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--text-secondary);
}
.overlap-swatch {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid rgba(255,255,255,0.15);
}
.overlap-finding {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 12px 16px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.overlap-finding.ok {
    border-left: 3px solid var(--green);
}
.overlap-finding.bad {
    border-left: 3px solid var(--magenta);
}
.overlap-finding .of-label {
    font-weight: 600;
    font-size: 13px;
    flex: 1;
}
.overlap-finding .of-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
}
.overlap-finding .of-value.ok { color: var(--green); }
.overlap-finding .of-value.bad { color: var(--magenta); }
.overlap-screenshot-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-top: 16px;
}
.overlap-screenshot-grid .screenshot-card img {
    width: 100%;
}
.coverage-bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 5px 0;
    border-bottom: 1px solid rgba(0, 240, 255, 0.03);
}
.coverage-bar-row:last-child { border-bottom: none; }
.coverage-bar-label {
    width: 80px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    font-weight: 600;
}
.coverage-bar-track {
    flex: 1;
    height: 18px;
    background: var(--surface-1);
    border-radius: 3px;
    position: relative;
    overflow: hidden;
}
.coverage-bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.3s ease;
}
.coverage-bar-pct {
    width: 50px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    text-align: right;
    font-weight: 600;
}

/* === Footer === */
.report-footer {
    text-align: center;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    color: var(--text-ghost);
    margin-top: 40px;
    padding-top: 16px;
    border-top: 1px solid var(--border);
    letter-spacing: 0.5px;
}

/* === Scrollbar === */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--surface-1); }
::-webkit-scrollbar-thumb { background: var(--surface-3); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--cyan-dim); }
"""

_JS = """
// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const target = btn.dataset.tab;
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        btn.classList.add('active');
        const el = document.getElementById('tab-' + target);
        if (el) el.classList.add('active');
    });
});

// Collapsible result cards
document.querySelectorAll('.result-header').forEach(header => {
    header.addEventListener('click', () => {
        header.closest('.result-card').classList.toggle('expanded');
    });
});

// Screenshot lightbox
const lightbox = document.getElementById('lightbox');
const lightboxImg = document.getElementById('lightbox-img');
document.querySelectorAll('.screenshot-card img').forEach(img => {
    img.addEventListener('click', (e) => {
        e.stopPropagation();
        lightboxImg.src = img.src;
        lightbox.classList.add('active');
    });
});
if (lightbox) {
    lightbox.addEventListener('click', () => {
        lightbox.classList.remove('active');
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') lightbox.classList.remove('active');
    });
}

// Trend chart tooltips
document.querySelectorAll('.trend-bar').forEach(bar => {
    bar.addEventListener('mouseenter', (e) => {
        const tip = document.getElementById('trend-tip');
        if (tip) {
            tip.textContent = bar.dataset.tooltip || '';
            tip.style.display = 'block';
            const rect = bar.getBoundingClientRect();
            tip.style.left = rect.left + 'px';
            tip.style.top = (rect.top - 30) + 'px';
        }
    });
    bar.addEventListener('mouseleave', () => {
        const tip = document.getElementById('trend-tip');
        if (tip) tip.style.display = 'none';
    });
});
"""


class ReportGenerator:
    """Generates self-contained interactive HTML reports from ResultsDB data."""

    def __init__(
        self,
        db: ResultsDB,
        output_dir: str = "tests/.test-results/reports",
    ):
        self._db = db
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, run_id: int, fleet: Any = None) -> Path:
        """Generate an interactive HTML report for a test run.

        Args:
            run_id: The run ID from ResultsDB.
            fleet: Optional OllamaFleet for LLM executive summary.

        Returns:
            Path to the generated HTML file.
        """
        summary = self._db.get_run_summary(run_id)
        if summary is None:
            raise ValueError(f"Run {run_id} not found")

        failures = self._db.get_failures(run_id)
        screenshots = self._db.get_screenshots(run_id)
        trend = self._db.get_trend(summary["suite"], last_n=20)
        all_results = self._get_all_results(run_id)

        exec_summary = ""
        if fleet is not None:
            exec_summary = self._generate_summary(fleet, summary, all_results)

        # LLM failure analysis
        failed_results = [r for r in all_results if not r.get("passed")]
        analysis_data: dict[str, Any] = {}
        screenshot_annotations: dict[str, str] = {}
        if failed_results:
            analysis_data = self._analyze_failures(failed_results, fleet=fleet)
            failed_names = {r["test_name"] for r in failed_results}
            screenshot_annotations = self._analyze_screenshots(
                screenshots, failed_names, fleet=fleet,
            )

        html_content = self._render(
            summary, all_results, failures, screenshots, trend, exec_summary,
            analysis_data=analysis_data,
            screenshot_annotations=screenshot_annotations,
        )

        filename = (
            f"report_{summary['suite']}_run{run_id}_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        )
        path = self._output_dir / filename
        path.write_text(html_content, encoding="utf-8")
        return path

    def export_json(self, run_id: int) -> Path:
        """Export all run data as a single JSON metrics file.

        Args:
            run_id: The run ID from ResultsDB.

        Returns:
            Path to the generated JSON file.
        """
        summary = self._db.get_run_summary(run_id)
        if summary is None:
            raise ValueError(f"Run {run_id} not found")

        all_results = self._get_all_results(run_id)
        screenshots = self._db.get_screenshots(run_id)
        trend = self._db.get_trend(summary["suite"], last_n=20)

        # Build export data
        export = {
            "generated_at": datetime.now().isoformat(),
            "run": {
                "id": summary["id"],
                "suite": summary["suite"],
                "git_hash": summary.get("git_hash", ""),
                "machine": summary.get("machine", ""),
                "started_at": summary.get("started_at", ""),
                "finished_at": summary.get("finished_at", ""),
                "total_tests": summary["total_tests"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "skipped": summary.get("skipped", 0),
                "pass_rate": (
                    round(summary["passed"] / summary["total_tests"] * 100, 1)
                    if summary["total_tests"] > 0 else 0
                ),
            },
            "results": [],
            "screenshots": [],
            "trend": [],
        }

        for r in all_results:
            entry = {
                "test_name": r.get("test_name", ""),
                "passed": bool(r.get("passed", False)),
                "duration_ms": r.get("duration_ms", 0),
            }
            if r.get("details_json"):
                try:
                    entry["details"] = json.loads(r["details_json"])
                except (json.JSONDecodeError, TypeError):
                    entry["details"] = {}
            export["results"].append(entry)

        for s in screenshots:
            entry = {
                "test_name": s.get("test_name", ""),
                "phase": s.get("phase", ""),
                "image_path": s.get("image_path", ""),
                "timestamp": s.get("timestamp", ""),
            }
            if s.get("opencv_json"):
                try:
                    entry["opencv"] = json.loads(s["opencv_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            if s.get("api_state_json"):
                try:
                    entry["api_state"] = json.loads(s["api_state_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            export["screenshots"].append(entry)

        for t in trend:
            export["trend"].append({
                "id": t["id"],
                "total_tests": t.get("total_tests", 0),
                "passed": t.get("passed", 0),
                "failed": t.get("failed", 0),
                "started_at": t.get("started_at", ""),
            })

        filename = f"metrics_{summary['suite']}_run{run_id}.json"
        path = self._output_dir / filename
        path.write_text(json.dumps(export, indent=2), encoding="utf-8")
        return path

    def _get_all_results(self, run_id: int) -> list[dict]:
        """Fetch all results for a run."""
        rows = self._db._conn.execute(
            "SELECT * FROM results WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("details_json"):
                d["details"] = json.loads(d["details_json"])
            results.append(d)
        return results

    # -------------------------------------------------------------------
    # LLM Analysis
    # -------------------------------------------------------------------

    def _analyze_failures(
        self, failed_results: list[dict], fleet: Any = None,
    ) -> dict[str, Any]:
        """Cluster failures by error message similarity and optionally get LLM analysis.

        Groups failures by first 50 characters of their error message. For each
        cluster: count, representative error, affected test files.

        Args:
            failed_results: List of failed test result dicts.
            fleet: Optional OllamaFleet for LLM root cause analysis.

        Returns:
            Dict with 'clusters' list and optional 'llm_analysis' string.
        """
        if not failed_results:
            return {"clusters": [], "llm_analysis": ""}

        # Extract error strings from details
        prefix_groups: dict[str, list[dict]] = {}
        for r in failed_results:
            details = r.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (json.JSONDecodeError, TypeError):
                    details = {}
            error_msg = ""
            if isinstance(details, dict):
                error_msg = str(details.get("error", ""))
            if not error_msg:
                # Fall back to details_json
                dj = r.get("details_json", "")
                if dj:
                    try:
                        d = json.loads(dj)
                        error_msg = str(d.get("error", ""))
                    except (json.JSONDecodeError, TypeError):
                        pass
            if not error_msg:
                error_msg = "Unknown error"

            prefix = error_msg[:50]
            prefix_groups.setdefault(prefix, []).append({
                "test_name": r.get("test_name", "unknown"),
                "error": error_msg,
            })

        clusters = []
        for prefix, items in prefix_groups.items():
            clusters.append({
                "count": len(items),
                "representative": items[0]["error"],
                "test_files": [i["test_name"] for i in items],
            })

        # Sort by count descending
        clusters.sort(key=lambda c: c["count"], reverse=True)

        result: dict[str, Any] = {"clusters": clusters}

        # LLM analysis if fleet available
        if fleet is not None:
            cluster_summary = "\n".join(
                f"- {c['count']}x: {c['representative'][:100]}"
                for c in clusters
            )
            prompt = (
                "Given these test failure clusters, identify root causes and "
                "suggest fixes:\n\n"
                f"{cluster_summary}\n\n"
                "Be concise. Focus on actionable root causes."
            )
            try:
                llm_text = fleet.generate(model="qwen2.5:7b", prompt=prompt, timeout=30)
                if llm_text:
                    result["llm_analysis"] = llm_text
                else:
                    result["llm_analysis"] = "LLM analysis unavailable"
            except Exception:
                result["llm_analysis"] = "LLM analysis unavailable"
        else:
            result["llm_analysis"] = ""

        return result

    def _analyze_screenshots(
        self,
        screenshots: list[dict],
        failed_test_names: set[str],
        fleet: Any = None,
    ) -> dict[str, str]:
        """Analyze screenshots from failed tests using vision LLM.

        Only screenshots associated with failed tests are analyzed.

        Args:
            screenshots: All screenshots from the run.
            failed_test_names: Set of test names that failed.
            fleet: Optional OllamaFleet with vision model (llava:7b).

        Returns:
            Dict mapping test_name to LLM description of screenshot issues.
        """
        if fleet is None:
            return {}

        annotations: dict[str, str] = {}
        for shot in screenshots:
            test_name = shot.get("test_name", "")
            if test_name not in failed_test_names:
                continue

            image_path = shot.get("image_path", "")
            if not image_path or not os.path.isfile(image_path):
                continue

            try:
                with open(image_path, "rb") as f:
                    import base64 as b64mod
                    img_b64 = b64mod.b64encode(f.read()).decode()

                prompt = (
                    f"This is a screenshot from a failed test '{test_name}'. "
                    "Describe what looks wrong or broken in 1-2 sentences."
                )
                result = fleet.chat(
                    model="llava:7b",
                    prompt=prompt,
                    images=[img_b64],
                    timeout=30,
                )
                if result:
                    annotations[test_name] = result
            except Exception:
                continue

        return annotations

    # -------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------

    def _render(
        self,
        summary: dict,
        results: list[dict],
        failures: list[dict],
        screenshots: list[dict],
        trend: list[dict],
        exec_summary: str,
        analysis_data: dict[str, Any] | None = None,
        screenshot_annotations: dict[str, str] | None = None,
    ) -> str:
        """Render the full interactive HTML report."""
        suite = html.escape(summary["suite"]).upper()
        run_num = summary["id"]
        pass_rate = (
            (summary["passed"] / summary["total_tests"] * 100)
            if summary["total_tests"] > 0 else 0
        )
        rate_cls = "pass" if pass_rate >= 90 else "fail"

        # Detect game loop data
        game_log = self._extract_game_log(results)
        game_screenshots = [s for s in screenshots if "04_" in (s.get("phase") or "")]
        has_game_loop = bool(game_log)

        # Detect metrics data
        metrics_data = self._extract_metrics(results)
        has_metrics = bool(metrics_data)

        # Detect overlap diagnostic data
        overlap_data = self._extract_overlap(results, screenshots)
        has_overlap = bool(overlap_data.get("overlap_pairs") is not None
                          or overlap_data.get("coverage"))

        # Detect analysis data
        has_analysis = bool(
            analysis_data and analysis_data.get("clusters")
        )

        # Determine which tabs to show
        tabs = [("results", "Results"), ("screenshots", "Screenshots")]
        if has_analysis:
            tabs.append(("analysis", "Analysis"))
        if has_overlap:
            tabs.append(("overlap", "Overlap"))
        if has_game_loop:
            tabs.append(("gameloop", "Game Loop"))
        if has_metrics:
            tabs.append(("metrics", "Metrics"))
        if len(trend) > 1:
            tabs.append(("trend", "Trend"))

        parts = [
            "<!DOCTYPE html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8'>",
            f"<title>TRITIUM-SC // {suite} // RUN #{run_num}</title>",
            f"<style>{_CSS}</style>",
            "</head>",
            "<body>",
            '<div class="container">',
        ]

        # Header
        git_hash = html.escape(summary.get("git_hash", "???")[:8])
        machine = html.escape(summary.get("machine", "unknown"))
        started = summary.get("started_at", "")
        started_str = html.escape(started[:19] if started else "---")
        parts.append(f"""
<div class="cc-header">
    <div class="header-logo">TRITIUM-SC</div>
    <div class="header-info">
        <span class="header-tag">{suite}</span>
        <span class="header-tag">RUN #{run_num}</span>
        <span class="header-tag">{git_hash}</span>
        <span class="header-tag">{machine}</span>
        <span class="header-tag">{started_str}</span>
    </div>
    <div class="header-badge {rate_cls}">{pass_rate:.0f}%</div>
</div>""")

        # Summary dashboard
        parts.append('<div class="summary-grid">')
        parts.append(self._stat(str(summary["total_tests"]), "Total", "neutral"))
        parts.append(self._stat(str(summary["passed"]), "Passed", "pass"))
        parts.append(self._stat(str(summary["failed"]), "Failed",
                                "fail" if summary["failed"] > 0 else "neutral"))
        parts.append(self._stat(str(summary.get("skipped", 0)), "Skipped", "skip"))
        parts.append(self._stat(f"{pass_rate:.1f}%", "Pass Rate", rate_cls))
        parts.append(self._stat(machine, "Machine", ""))
        parts.append(self._stat(git_hash, "Git Hash", ""))
        # Duration
        duration_ms = sum(r.get("duration_ms", 0) for r in results)
        dur_str = f"{duration_ms / 1000:.1f}s" if duration_ms > 0 else "---"
        parts.append(self._stat(dur_str, "Duration", ""))
        parts.append("</div>")

        # Executive summary
        if exec_summary:
            parts.append(f'<div class="exec-summary">{html.escape(exec_summary)}</div>')

        # Tab bar
        parts.append('<div class="tab-bar">')
        for i, (tab_id, tab_label) in enumerate(tabs):
            active = " active" if i == 0 else ""
            parts.append(
                f'<button class="tab-btn{active}" data-tab="{tab_id}">'
                f'{tab_label}</button>'
            )
        parts.append("</div>")

        # Tab: Results
        active_cls = " active" if tabs[0][0] == "results" else ""
        parts.append(f'<div id="tab-results" class="tab-content{active_cls}">')
        parts.append(self._render_results(results))
        parts.append("</div>")

        # Tab: Screenshots
        active_cls = ""
        parts.append(f'<div id="tab-screenshots" class="tab-content{active_cls}">')
        parts.append(self._render_screenshots(screenshots))
        parts.append("</div>")

        # Tab: Analysis
        if has_analysis:
            parts.append('<div id="tab-analysis" class="tab-content">')
            parts.append(
                self._render_analysis(analysis_data or {}, screenshot_annotations or {})
            )
            parts.append("</div>")

        # Tab: Overlap Diagnostic
        if has_overlap:
            parts.append('<div id="tab-overlap" class="tab-content">')
            parts.append(self._render_overlap(overlap_data, screenshots))
            parts.append("</div>")

        # Tab: Game Loop
        if has_game_loop:
            parts.append('<div id="tab-gameloop" class="tab-content">')
            parts.append(self._render_game_loop(game_log, game_screenshots))
            parts.append("</div>")

        # Tab: Metrics
        if has_metrics:
            parts.append('<div id="tab-metrics" class="tab-content">')
            parts.append(self._render_metrics(metrics_data))
            parts.append("</div>")

        # Tab: Trend
        if len(trend) > 1:
            parts.append('<div id="tab-trend" class="tab-content">')
            parts.append(self._render_trend_svg(trend))
            parts.append("</div>")

        # Lightbox
        parts.append("""
<div id="lightbox" class="lightbox">
    <img id="lightbox-img" src="" alt="Screenshot">
</div>""")

        # Trend tooltip
        parts.append(
            '<div id="trend-tip" class="trend-tooltip" '
            'style="display:none;position:fixed;background:var(--surface-3);'
            'color:var(--cyan);padding:4px 10px;border-radius:4px;'
            'border:1px solid var(--border);pointer-events:none;z-index:10001;"></div>'
        )

        # Footer
        gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts.append(f"""
<div class="report-footer">
    TRITIUM-SC ReportGenerator // {gen_time} // Cybercore v2
</div>""")

        parts.append("</div>")  # .container
        parts.append(f"<script>{_JS}</script>")
        parts.append("</body>")
        parts.append("</html>")
        return "\n".join(parts)

    def _stat(self, value: str, label: str, cls: str) -> str:
        """Render a stat card."""
        val_cls = f' {cls}' if cls else ""
        return (
            f'<div class="stat-card">'
            f'<div class="stat-value{val_cls}">{html.escape(value)}</div>'
            f'<div class="stat-label">{html.escape(label)}</div>'
            f"</div>"
        )

    def _render_results(self, results: list[dict]) -> str:
        """Render the Results tab content."""
        parts = ['<div class="section-title">Test Results</div>']
        for r in results:
            passed = r.get("passed", False)
            card_cls = "passed" if passed else "failed"
            badge_cls = "pass" if passed else "fail"
            badge_text = "PASS" if passed else "FAIL"
            name = html.escape(r.get("test_name", "unknown"))
            dur = r.get("duration_ms", 0)
            dur_str = f"{dur:.0f}ms" if dur else ""

            parts.append(f'<div class="result-card {card_cls}">')
            parts.append(f'<div class="result-header">')
            parts.append(f'<span class="result-badge {badge_cls}">{badge_text}</span>')
            parts.append(f'<span class="result-name">{name}</span>')
            parts.append(f'<span class="result-duration">{dur_str}</span>')
            parts.append(f'<span class="result-chevron">&#9654;</span>')
            parts.append("</div>")

            # Collapsible details
            details = r.get("details", {})
            if details:
                details_str = json.dumps(details, indent=2, default=str)
                parts.append(f'<div class="result-details">')
                parts.append(f"<pre>{html.escape(details_str)}</pre>")
                parts.append("</div>")
            elif r.get("details_json"):
                parts.append(f'<div class="result-details">')
                try:
                    details_str = json.dumps(
                        json.loads(r["details_json"]), indent=2, default=str
                    )
                except (json.JSONDecodeError, TypeError):
                    details_str = r["details_json"]
                parts.append(f"<pre>{html.escape(details_str)}</pre>")
                parts.append("</div>")

            parts.append("</div>")
        return "\n".join(parts)

    def _render_screenshots(self, screenshots: list[dict]) -> str:
        """Render the Screenshots tab with thumbnails and lightbox."""
        if not screenshots:
            return '<div class="section-title">No screenshots recorded</div>'

        parts = [
            '<div class="section-title">Screenshots</div>',
            '<div class="screenshot-grid">',
        ]
        for shot in screenshots:
            parts.append(self._render_screenshot_card(shot))
        parts.append("</div>")
        return "\n".join(parts)

    def _render_screenshot_card(self, shot: dict) -> str:
        """Render a single screenshot card with inline base64 thumbnail."""
        parts = ['<div class="screenshot-card">']

        img_path = shot.get("image_path", "")
        if img_path and os.path.isfile(img_path):
            try:
                with open(img_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                ext = Path(img_path).suffix.lower()
                mime = "image/png" if ext == ".png" else "image/jpeg"
                test_name = html.escape(shot.get("test_name", ""))
                parts.append(
                    f'<img src="data:{mime};base64,{b64}" alt="{test_name}">'
                )
            except OSError:
                pass

        parts.append('<div class="screenshot-meta">')
        phase = html.escape(shot.get("phase", ""))
        test_name = html.escape(shot.get("test_name", ""))
        if phase:
            parts.append(f'<div class="phase-label">{phase}</div>')
        parts.append(f'<div class="test-label">{test_name}</div>')

        if shot.get("llava_host"):
            parts.append(
                f'<div class="test-label">LLaVA: {html.escape(shot["llava_host"])} '
                f'({shot.get("llava_ms", 0):.0f}ms)</div>'
            )
        if shot.get("llava_response"):
            resp = html.escape(str(shot["llava_response"])[:200])
            parts.append(f'<div class="test-label">{resp}</div>')

        parts.append("</div>")
        parts.append("</div>")
        return "\n".join(parts)

    def _render_analysis(
        self, analysis_data: dict, screenshot_annotations: dict[str, str],
    ) -> str:
        """Render the Analysis tab with failure clusters and LLM insights."""
        parts = ['<div class="section-title">Failure Clusters</div>']

        clusters = analysis_data.get("clusters", [])
        if clusters:
            for cluster in clusters:
                count = cluster.get("count", 0)
                rep = html.escape(cluster.get("representative", "")[:200])
                test_files = cluster.get("test_files", [])
                files_str = html.escape(", ".join(test_files[:5]))
                if len(test_files) > 5:
                    files_str += f" (+{len(test_files) - 5} more)"

                parts.append(
                    f'<div class="overlap-finding bad">'
                    f'<span class="of-label">'
                    f'<strong>{count}x</strong> {rep}'
                    f'<br><span style="font-size:11px;color:var(--text-dim);">'
                    f'{files_str}</span>'
                    f'</span>'
                    f'</div>'
                )
        else:
            parts.append(
                '<div class="overlap-finding ok">'
                '<span class="of-label">No failure clusters</span>'
                '<span class="of-value ok">CLEAR</span>'
                '</div>'
            )

        # LLM root cause analysis
        llm_text = analysis_data.get("llm_analysis", "")
        if llm_text:
            parts.append(
                '<div class="section-title" style="margin-top:20px;">'
                'LLM Root Cause Analysis</div>'
            )
            parts.append(
                f'<div class="exec-summary">{html.escape(llm_text)}</div>'
            )

        # Screenshot annotations
        if screenshot_annotations:
            parts.append(
                '<div class="section-title" style="margin-top:20px;">'
                'Screenshot Analysis</div>'
            )
            for test_name, annotation in screenshot_annotations.items():
                parts.append(
                    f'<div class="overlap-finding bad">'
                    f'<span class="of-label">'
                    f'<strong>{html.escape(test_name)}</strong>'
                    f'<br>{html.escape(annotation)}'
                    f'</span>'
                    f'</div>'
                )

        return "\n".join(parts)

    def _render_game_loop(
        self, game_log: list[str], game_screenshots: list[dict]
    ) -> str:
        """Render the Game Loop tab with timeline and events."""
        parts = ['<div class="section-title">Game Loop Timeline</div>']

        # Phase markers
        phases = [
            ("RESET", "Clear state"),
            ("PLACE", "Deploy turrets"),
            ("BEGIN", "Start countdown"),
            ("HOSTILES", "Enemy spawn"),
            ("COMBAT", "Active battle"),
            ("CLEANUP", "Final reset"),
        ]
        parts.append('<div class="timeline-track">')
        for name, detail in phases:
            parts.append(
                f'<div class="timeline-phase">'
                f'<div class="phase-name">{name}</div>'
                f'<div class="phase-detail">{detail}</div>'
                f'</div>'
            )
        parts.append("</div>")

        # Event log
        if game_log:
            parts.append('<div class="timeline-events">')
            for line in game_log:
                escaped = html.escape(line)
                # Highlight phase headers
                if "===" in line:
                    parts.append(
                        f'<div class="timeline-event">'
                        f'<span class="event-phase">{escaped}</span>'
                        f'</div>'
                    )
                elif line.startswith("t=") or "t=" in line:
                    parts.append(
                        f'<div class="timeline-event">'
                        f'<span class="event-time">{escaped}</span>'
                        f'</div>'
                    )
                else:
                    parts.append(f'<div class="timeline-event">{escaped}</div>')
            parts.append("</div>")

        # Game loop screenshots
        if game_screenshots:
            parts.append('<div class="timeline-screenshots">')
            for shot in game_screenshots:
                parts.append(self._render_screenshot_card(shot))
            parts.append("</div>")

        return "\n".join(parts)

    def _render_metrics(self, metrics_data: dict) -> str:
        """Render the Metrics dashboard tab."""
        parts = ['<div class="section-title">Metrics Dashboard</div>']
        parts.append('<div class="metrics-grid">')

        # Canvas & Rendering
        canvas = metrics_data.get("canvas", {})
        if canvas:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">Canvas & Rendering</div>')
            for key, val in canvas.items():
                val_cls = self._metric_cls(key, val)
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val {val_cls}">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # Unit counts
        units = metrics_data.get("units", {})
        if units:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">Unit Counts</div>')
            for key, val in units.items():
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val ok">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # Detection results
        detection = metrics_data.get("detection", {})
        if detection:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">Detection Results</div>')
            for key, val in detection.items():
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val ok">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # DOM elements checklist
        dom_checks = metrics_data.get("dom_checks", {})
        if dom_checks:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">DOM Elements</div>')
            for name, found in dom_checks.items():
                icon_cls = "found" if found else "missing"
                icon = "&#10003;" if found else "&#10007;"
                parts.append(
                    f'<div class="check-item">'
                    f'<span class="check-icon {icon_cls}">{icon}</span>'
                    f'<span class="check-label">{html.escape(str(name))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # OCR results
        ocr = metrics_data.get("ocr", {})
        if ocr:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">OCR Text Detection</div>')
            for key, val in ocr.items():
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val ok">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # Panels
        panels = metrics_data.get("panels", {})
        if panels:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">Panel Detection</div>')
            for key, val in panels.items():
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val ok">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # API response times
        api_times = metrics_data.get("api_times", {})
        if api_times:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">API Response Times</div>')
            for endpoint, ms in api_times.items():
                val_cls = "ok" if ms < 200 else ("warn" if ms < 1000 else "bad")
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(endpoint))}</span>'
                    f'<span class="metric-val {val_cls}">{ms}ms</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # FPS summary stats
        fps_stats = metrics_data.get("fps_stats", {})
        if fps_stats:
            parts.append('<div class="metric-panel">')
            parts.append('<div class="metric-title">FPS Performance</div>')
            for key, val in fps_stats.items():
                val_cls = "ok"
                try:
                    v = float(val)
                    val_cls = "ok" if v >= 30 else ("warn" if v >= 10 else "bad")
                except (ValueError, TypeError):
                    pass
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key">{html.escape(str(key))}</span>'
                    f'<span class="metric-val {val_cls}">{html.escape(str(val))}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        parts.append("</div>")  # .metrics-grid

        # FPS time-series chart (full width, below grid)
        fps_samples = metrics_data.get("fps_samples", [])
        if fps_samples:
            parts.append(self._render_fps_chart(fps_samples))

        return "\n".join(parts)

    def _render_fps_chart(self, samples: list[dict]) -> str:
        """Render an inline SVG line chart of FPS over time."""
        w, h = 700, 200
        pad_l, pad_r, pad_t, pad_b = 45, 15, 20, 30
        plot_w = w - pad_l - pad_r
        plot_h = h - pad_t - pad_b

        max_t = max((s.get("t", 0) for s in samples), default=1) or 1
        max_fps = 60  # fixed Y-axis to 60 FPS

        def tx(t: float) -> float:
            return pad_l + (t / max_t) * plot_w

        def ty(fps: float) -> float:
            return pad_t + plot_h - (min(fps, max_fps) / max_fps) * plot_h

        parts = [
            '<div class="metric-panel" style="grid-column: 1 / -1; margin-top: 14px;">',
            '<div class="metric-title">FPS Over Time</div>',
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{w}" height="{h}" fill="#0a0a0f" rx="6"/>',
        ]

        # Grid lines at 10 FPS intervals
        for fps_level in range(0, 61, 10):
            y = ty(fps_level)
            opacity = "0.12" if fps_level % 30 == 0 else "0.06"
            parts.append(
                f'<line x1="{pad_l}" y1="{y}" x2="{w - pad_r}" y2="{y}" '
                f'stroke="#00f0ff" stroke-width="1" opacity="{opacity}"/>'
            )
            parts.append(
                f'<text x="{pad_l - 5}" y="{y + 4}" fill="#4a5568" '
                f'font-size="9" font-family="JetBrains Mono, monospace" '
                f'text-anchor="end">{fps_level}</text>'
            )

        # 30 FPS threshold line (yellow dashed)
        y30 = ty(30)
        parts.append(
            f'<line x1="{pad_l}" y1="{y30}" x2="{w - pad_r}" y2="{y30}" '
            f'stroke="#fcee0a" stroke-width="1" stroke-dasharray="6,4" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{w - pad_r + 2}" y="{y30 + 4}" fill="#fcee0a" '
            f'font-size="9" font-family="JetBrains Mono, monospace" '
            f'opacity="0.7">30</text>'
        )

        # 10 FPS threshold line (magenta dashed)
        y10 = ty(10)
        parts.append(
            f'<line x1="{pad_l}" y1="{y10}" x2="{w - pad_r}" y2="{y10}" '
            f'stroke="#ff2a6d" stroke-width="1" stroke-dasharray="6,4" opacity="0.5"/>'
        )
        parts.append(
            f'<text x="{w - pad_r + 2}" y="{y10 + 4}" fill="#ff2a6d" '
            f'font-size="9" font-family="JetBrains Mono, monospace" '
            f'opacity="0.7">10</text>'
        )

        # X-axis time labels
        for t_label in range(0, int(max_t) + 1, max(1, int(max_t) // 6)):
            x = tx(t_label)
            parts.append(
                f'<text x="{x}" y="{h - 8}" fill="#4a5568" '
                f'font-size="9" font-family="JetBrains Mono, monospace" '
                f'text-anchor="middle">{t_label}s</text>'
            )

        # FPS line (cyan)
        points = []
        for s in samples:
            t = s.get("t", 0)
            fps = s.get("fps", 0)
            points.append(f"{tx(t):.1f},{ty(fps):.1f}")

        if points:
            # Area fill under the line
            area_points = [f"{tx(samples[0].get('t', 0)):.1f},{ty(0):.1f}"]
            area_points.extend(points)
            area_points.append(f"{tx(samples[-1].get('t', 0)):.1f},{ty(0):.1f}")
            parts.append(
                f'<polygon points="{" ".join(area_points)}" '
                f'fill="rgba(0, 240, 255, 0.08)"/>'
            )
            # Line
            parts.append(
                f'<polyline points="{" ".join(points)}" '
                f'fill="none" stroke="#00f0ff" stroke-width="2" '
                f'stroke-linejoin="round" stroke-linecap="round"/>'
            )
            # Data point dots
            for s in samples[::max(1, len(samples) // 15)]:
                x = tx(s.get("t", 0))
                y = ty(s.get("fps", 0))
                fps = s.get("fps", 0)
                color = "#05ffa1" if fps >= 30 else ("#fcee0a" if fps >= 10 else "#ff2a6d")
                parts.append(
                    f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" '
                    f'fill="{color}" opacity="0.9"/>'
                )

        # Axis labels
        parts.append(
            f'<text x="{w // 2}" y="{h - 1}" fill="#5a6577" '
            f'font-size="10" font-family="JetBrains Mono, monospace" '
            f'text-anchor="middle">Time (seconds)</text>'
        )
        parts.append(
            f'<text x="12" y="{h // 2}" fill="#5a6577" '
            f'font-size="10" font-family="JetBrains Mono, monospace" '
            f'text-anchor="middle" transform="rotate(-90, 12, {h // 2})">FPS</text>'
        )

        parts.extend(["</svg>", "</div>"])
        return "\n".join(parts)

    def _render_trend_svg(self, trend: list[dict]) -> str:
        """Render an interactive SVG bar chart of pass rates."""
        w, h = 700, 160
        bar_w = max(8, (w - 60) // max(len(trend), 1))
        parts = [
            '<div class="trend-chart">',
            '<div class="section-title">Pass Rate Trend</div>',
            f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
            f'xmlns="http://www.w3.org/2000/svg">',
            f'<rect width="{w}" height="{h}" fill="#0e0e14" rx="6"/>',
        ]

        for i, run in enumerate(trend):
            total = run.get("total_tests", 0)
            passed = run.get("passed", 0)
            rate = (passed / total) if total > 0 else 0
            bar_h = max(2, rate * (h - 40))
            x = 30 + i * bar_w
            y = h - 20 - bar_h
            color = "#05ffa1" if rate >= 0.9 else ("#fcee0a" if rate >= 0.7 else "#ff2a6d")
            tooltip = f"Run #{run['id']}: {passed}/{total} ({rate * 100:.0f}%)"
            parts.append(
                f'<rect class="trend-bar" x="{x}" y="{y}" '
                f'width="{bar_w - 3}" height="{bar_h}" '
                f'fill="{color}" rx="2" opacity="0.85" '
                f'data-tooltip="{html.escape(tooltip)}" '
                f'style="cursor:pointer;"/>'
            )
            # Label every 5th bar or last
            if i % 5 == 0 or i == len(trend) - 1:
                parts.append(
                    f'<text x="{x}" y="{h - 4}" fill="#4a5568" '
                    f'font-size="9" font-family="JetBrains Mono, monospace">'
                    f'#{run["id"]}</text>'
                )

        # 90% threshold line
        y90 = h - 20 - 0.9 * (h - 40)
        parts.append(
            f'<line x1="28" y1="{y90}" x2="{w - 10}" y2="{y90}" '
            f'stroke="#00f0ff" stroke-width="1" stroke-dasharray="4,4" opacity="0.3"/>'
        )
        parts.append(
            f'<text x="{w - 8}" y="{y90 - 3}" fill="#0e7490" '
            f'font-size="9" font-family="JetBrains Mono, monospace" '
            f'text-anchor="end">90%</text>'
        )

        parts.extend(["</svg>", "</div>"])
        return "\n".join(parts)

    # -------------------------------------------------------------------
    # Overlap diagnostic rendering
    # -------------------------------------------------------------------

    # Diagnostic color map matching test_full_report.py
    _OVERLAP_COLORS = {
        "amy":    ("#FF0000", "AMY"),
        "units":  ("#00FF00", "UNITS"),
        "alerts": ("#0000FF", "ALERTS"),
        "game":   ("#FFFF00", "GAME"),
        "mesh":   ("#FF00FF", "MESH"),
    }

    def _extract_overlap(
        self, results: list[dict], screenshots: list[dict],
    ) -> dict:
        """Extract overlap diagnostic data from results."""
        data: dict[str, Any] = {}
        for r in results:
            details = r.get("details", {})
            if not isinstance(details, dict):
                continue
            name = r.get("test_name", "")
            if "overlap" in name.lower() or "diag" in name.lower():
                if "overlap_pairs" in details:
                    data["overlap_pairs"] = details["overlap_pairs"]
                    data["issues"] = details.get("issues", [])
                    data["dom_panels"] = details.get("dom_panels", [])
                    data["detected_panels"] = details.get("detected_panels", {})
            if "coverage" in name.lower() or "pixel_coverage" in name.lower():
                if "coverage" in details:
                    data["coverage"] = details["coverage"]
                    data["occluded_count"] = details.get("occluded_count", 0)
        # Collect diagnostic screenshots
        data["screenshots"] = [
            s for s in screenshots
            if "diag" in (s.get("phase") or "").lower()
            or "diag" in (s.get("test_name") or "").lower()
            or "overlap" in (s.get("phase") or "").lower()
            or "overlap" in (s.get("test_name") or "").lower()
        ]
        return data

    def _render_overlap(self, data: dict, all_screenshots: list[dict]) -> str:
        """Render the Overlap Diagnostic tab."""
        parts = ['<div class="section-title">Panel Overlap Diagnostic</div>']

        # Color legend
        parts.append('<div class="overlap-legend">')
        for pid, (hexcol, label) in self._OVERLAP_COLORS.items():
            parts.append(
                f'<div class="overlap-legend-item">'
                f'<div class="overlap-swatch" style="background:{hexcol};"></div>'
                f'{label}'
                f'</div>'
            )
        parts.append("</div>")

        # Overlap pair findings
        overlap_pairs = data.get("overlap_pairs", [])
        if overlap_pairs:
            parts.append(
                f'<div class="section-title" style="color:var(--magenta)">'
                f'Overlapping Panels ({len(overlap_pairs)} pair(s))</div>'
            )
            for op in overlap_pairs:
                panels_str = html.escape(str(op.get("panels", "")))
                px = op.get("overlap_px", 0)
                parts.append(
                    f'<div class="overlap-finding bad">'
                    f'<span class="of-label">{panels_str}</span>'
                    f'<span class="of-value bad">{px:,}px overlap</span>'
                    f'</div>'
                )
        else:
            parts.append(
                '<div class="overlap-finding ok">'
                '<span class="of-label">No panel overlaps detected</span>'
                '<span class="of-value ok">CLEAR</span>'
                '</div>'
            )

        # Pixel coverage bars
        coverage = data.get("coverage", [])
        if coverage:
            parts.append(
                '<div class="section-title" style="margin-top:20px;">'
                'Panel Pixel Coverage</div>'
            )
            parts.append('<div class="metric-panel">')
            for c in coverage:
                panel_name = html.escape(str(c.get("panel", "?")))
                ratio = c.get("coverage_ratio", 0)
                pct = round(ratio * 100, 1)
                # Match panel to color
                color = "#00f0ff"
                for pid, (hexcol, label) in self._OVERLAP_COLORS.items():
                    if label == panel_name:
                        color = hexcol
                        break
                bar_cls = "ok" if ratio >= 0.85 else "bad"
                parts.append(
                    f'<div class="coverage-bar-row">'
                    f'<span class="coverage-bar-label" '
                    f'style="color:{color};">{panel_name}</span>'
                    f'<div class="coverage-bar-track">'
                    f'<div class="coverage-bar-fill" '
                    f'style="width:{min(pct, 100):.0f}%;background:{color};'
                    f'opacity:0.7;"></div>'
                    f'</div>'
                    f'<span class="coverage-bar-pct {bar_cls}">{pct:.1f}%</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # Issues list
        issues = data.get("issues", [])
        if issues:
            parts.append(
                '<div class="section-title" style="margin-top:20px;">'
                'Issues</div>'
            )
            parts.append('<div class="metric-panel">')
            for issue in issues:
                parts.append(
                    f'<div class="metric-row">'
                    f'<span class="metric-key" style="color:var(--magenta);">'
                    f'{html.escape(issue)}</span>'
                    f'</div>'
                )
            parts.append("</div>")

        # Diagnostic screenshots
        diag_shots = data.get("screenshots", [])
        if diag_shots:
            parts.append(
                '<div class="section-title" style="margin-top:20px;">'
                'Diagnostic Screenshots</div>'
            )
            parts.append('<div class="overlap-screenshot-grid">')
            for shot in diag_shots:
                parts.append(self._render_screenshot_card(shot))
            parts.append("</div>")

        return "\n".join(parts)

    # -------------------------------------------------------------------
    # Data extraction helpers
    # -------------------------------------------------------------------

    def _extract_game_log(self, results: list[dict]) -> list[str]:
        """Extract game loop log from results details."""
        for r in results:
            details = r.get("details", {})
            if isinstance(details, dict):
                game_log = details.get("game_log")
                if game_log and isinstance(game_log, list):
                    return game_log
        return []

    def _extract_metrics(self, results: list[dict]) -> dict:
        """Extract metrics from results details into dashboard categories."""
        metrics: dict[str, dict] = {}

        for r in results:
            details = r.get("details", {})
            if not isinstance(details, dict):
                continue
            name = r.get("test_name", "")

            # Canvas metrics
            if "canvas_brightness" in details or "canvas_pct" in details:
                canvas = metrics.setdefault("canvas", {})
                if "canvas_brightness" in details:
                    canvas["Brightness"] = f"{details['canvas_brightness']:.1f}"
                if "canvas_pct" in details:
                    canvas["Non-black %"] = f"{details['canvas_pct']:.1f}%"
                if "header_brightness" in details:
                    canvas["Header brightness"] = f"{details['header_brightness']:.1f}"
                if "status_brightness" in details:
                    canvas["Status brightness"] = f"{details['status_brightness']:.1f}"

            # FPS
            if "fps" in details:
                canvas = metrics.setdefault("canvas", {})
                canvas["FPS"] = str(details["fps"])

            # Unit counts
            if "green_blobs" in details or "friendly_count" in details:
                units = metrics.setdefault("units", {})
                if "green_blobs" in details:
                    units["Green blobs (friendly)"] = str(details["green_blobs"])
                if "red_blobs" in details:
                    units["Red blobs (hostile)"] = str(details["red_blobs"])
                if "friendly_count" in details:
                    units["Friendlies"] = str(details["friendly_count"])
                if "hostile_count" in details:
                    units["Hostiles"] = str(details["hostile_count"])
                if "cyan_elements" in details:
                    units["Cyan UI elements"] = str(details["cyan_elements"])

            # Detection
            if "text_regions" in details or "panel_count" in details:
                detection = metrics.setdefault("detection", {})
                if "text_regions" in details:
                    detection["Text regions"] = str(details["text_regions"])
                if "panel_count" in details:
                    detection["Panels (DOM)"] = str(details["panel_count"])
                if "panel_count_cv" in details:
                    detection["Panels (OpenCV)"] = str(details["panel_count_cv"])
                if "mode_buttons" in details:
                    detection["Mode buttons"] = str(details["mode_buttons"])

            # DOM checks
            if "dom_checks" in details:
                metrics["dom_checks"] = details["dom_checks"]

            # OCR
            if "ocr_segments" in details or "ocr_text_length" in details:
                ocr = metrics.setdefault("ocr", {})
                if "ocr_segments" in details:
                    ocr["Text segments"] = str(details["ocr_segments"])
                if "ocr_text_length" in details:
                    ocr["Total text length"] = str(details["ocr_text_length"])

            # Panels
            if "panels" in details and isinstance(details["panels"], list):
                panels = metrics.setdefault("panels", {})
                for i, p in enumerate(details["panels"]):
                    if isinstance(p, dict):
                        title = p.get("title", f"Panel {i+1}")
                        panels[title] = (
                            f"{p.get('width', '?')}x{p.get('height', '?')} "
                            f"@ ({p.get('x', '?')},{p.get('y', '?')})"
                        )

            # FPS time-series samples
            if "fps_samples" in details and isinstance(details["fps_samples"], list):
                metrics["fps_samples"] = details["fps_samples"]
                fps_stats = metrics.setdefault("fps_stats", {})
                fps_vals = [s["fps"] for s in details["fps_samples"]
                            if isinstance(s, dict) and s.get("fps", 0) > 0]
                if fps_vals:
                    fps_stats["Min"] = str(min(fps_vals))
                    fps_stats["Max"] = str(max(fps_vals))
                    fps_stats["Mean"] = f"{sum(fps_vals) / len(fps_vals):.1f}"
                    sorted_v = sorted(fps_vals)
                    fps_stats["P5"] = str(sorted_v[max(0, len(sorted_v) // 20)])
                    fps_stats["Samples"] = str(len(details["fps_samples"]))

            # API response times
            if "api_response_times" in details and isinstance(
                details["api_response_times"], dict
            ):
                metrics["api_times"] = details["api_response_times"]

        return metrics

    def _metric_cls(self, key: str, val: Any) -> str:
        """Determine CSS class for a metric value."""
        try:
            v = float(str(val).rstrip("%"))
            if "brightness" in key.lower():
                return "ok" if v > 8 else "bad"
            if "fps" in key.lower():
                return "ok" if v >= 30 else ("warn" if v >= 10 else "bad")
            if "%" in str(val):
                return "ok" if v > 5 else "bad"
        except (ValueError, TypeError):
            pass
        return "ok"

    def _generate_summary(
        self, fleet: Any, summary: dict, results: list[dict],
    ) -> str:
        """Use OllamaFleet to generate an executive summary."""
        failures = [r for r in results if not r.get("passed")]
        failure_names = [r.get("test_name", "?") for r in failures[:10]]

        prompt = (
            f"Summarize this test run in 2-3 sentences.\n"
            f"Suite: {summary['suite']}\n"
            f"Total: {summary['total_tests']}, "
            f"Passed: {summary['passed']}, "
            f"Failed: {summary['failed']}\n"
            f"Machine: {summary.get('machine', 'unknown')}\n"
        )
        if failure_names:
            prompt += f"Failed tests: {', '.join(failure_names)}\n"
        prompt += "Be concise. Focus on what failed and why it matters."

        try:
            result = fleet.generate(
                model="qwen2.5:7b", prompt=prompt, timeout=30,
            )
            # generate() returns a string directly
            if isinstance(result, dict):
                return result.get("response", "")
            return str(result) if result else ""
        except Exception:
            return ""


def _cli():
    """CLI entry point for report generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate TRITIUM-SC test report")
    parser.add_argument("--run-id", type=int, help="Specific run ID to report on")
    parser.add_argument("--latest", action="store_true", help="Report on latest run")
    parser.add_argument("--suite", default="unit", help="Suite to query (default: unit)")
    parser.add_argument("--db", default="tests/.test-results/results.db",
                        help="Path to results database")
    parser.add_argument("--output-dir", default="tests/.test-results/reports",
                        help="Output directory for reports")
    parser.add_argument("--json", action="store_true",
                        help="Also export JSON metrics")
    parser.add_argument("--fleet", action="store_true",
                        help="Enable LLM analysis via OllamaFleet")
    parser.add_argument("--serve", action="store_true",
                        help="Open report in browser after generation")
    args = parser.parse_args()

    db = ResultsDB(db_path=args.db)
    gen = ReportGenerator(db, output_dir=args.output_dir)

    fleet = None
    if args.fleet:
        fleet = OllamaFleet(auto_discover=True)
        print(fleet.status())

    run_id = args.run_id
    if args.latest or run_id is None:
        trend = db.get_trend(args.suite, last_n=1)
        if not trend:
            print(f"No runs found for suite '{args.suite}'")
            sys.exit(1)
        run_id = trend[-1]["id"]

    path = gen.generate(run_id, fleet=fleet)
    print(f"Report generated: {path}")

    if args.json:
        json_path = gen.export_json(run_id)
        print(f"JSON metrics: {json_path}")

    if args.serve:
        import webbrowser
        webbrowser.open(f"file://{path.resolve()}")


if __name__ == "__main__":
    _cli()
