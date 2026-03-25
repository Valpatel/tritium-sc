# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unified test report generator for the Tritium project.

Runs pytest across tritium-sc and tritium-lib, collects results, computes
quality metrics (test density, untested modules, trends), and generates
JSON + HTML reports stored in data/test_reports/.
"""

from __future__ import annotations

import html as _html_mod
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SC_ROOT = Path(__file__).resolve().parents[3]  # tritium-sc/
_LIB_ROOT = _SC_ROOT.parent / "tritium-lib"
_REPORTS_DIR = _SC_ROOT / "data" / "test_reports"

# Directories to exclude when scanning source files
_EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    "migrations", "alembic", ".pytest_cache", ".mypy_cache",
    "egg-info", "dist", "build",
}


def _is_excluded(path: Path) -> bool:
    """Return True if any path component matches an excluded dir name."""
    for part in path.parts:
        if part in _EXCLUDE_DIRS or part.endswith(".egg-info"):
            return True
    return False


# ---------------------------------------------------------------------------
# TestReportGenerator
# ---------------------------------------------------------------------------

class TestReportGenerator:
    """Runs tests, collects results, and generates unified reports."""

    def __init__(self, reports_dir: Path | None = None):
        self.reports_dir = reports_dir or _REPORTS_DIR
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        """Execute a full test run across all sub-projects and return the
        unified report dict.  The report is also persisted to disk."""
        started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()

        sc_results = self._run_pytest(_SC_ROOT, label="tritium-sc")
        lib_results = self._run_pytest(_LIB_ROOT, label="tritium-lib")

        sc_density = self._compute_density(_SC_ROOT / "src", _SC_ROOT / "tests")
        lib_density = self._compute_density(
            _LIB_ROOT / "src", _LIB_ROOT / "tests"
        )

        elapsed = round(time.monotonic() - started, 2)

        report: dict[str, Any] = {
            "timestamp": timestamp,
            "duration_s": elapsed,
            "projects": {
                "tritium-sc": {**sc_results, **sc_density},
                "tritium-lib": {**lib_results, **lib_density},
            },
            "totals": self._merge_totals(sc_results, lib_results),
        }

        # Trend comparison
        previous = self._load_previous()
        if previous:
            report["trend"] = self._compute_trend(report, previous)

        # Persist
        self._save_report(report)

        return report

    def latest(self) -> dict[str, Any] | None:
        """Return the most recent report from disk, or None."""
        return self._load_previous()

    def generate_html(self, report: dict[str, Any]) -> str:
        """Render a minimal cyberpunk-styled HTML summary."""
        return _render_html(report)

    # ------------------------------------------------------------------
    # pytest runner
    # ------------------------------------------------------------------

    def _run_pytest(self, root: Path, label: str) -> dict[str, Any]:
        """Run pytest in *root* and parse the JSON output."""
        test_dir = root / "tests"
        if not test_dir.is_dir():
            logger.warning("No tests/ directory in %s", root)
            return self._empty_results(label)

        json_file = self.reports_dir / f"_tmp_{label}.json"
        cmd = [
            "python3", "-m", "pytest",
            str(test_dir),
            f"--json-report-file={json_file}",
            "--json-report",
            "-q",
            "--tb=no",
            "--no-header",
            "-x",  # stop on first failure to keep runs fast
            "--timeout=120",
        ]

        env = None
        venv_python = root / ".venv" / "bin" / "python3"
        if venv_python.exists():
            cmd[0] = str(venv_python)

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
        except FileNotFoundError:
            logger.warning("pytest not found for %s", label)
            return self._empty_results(label)
        except subprocess.TimeoutExpired:
            logger.warning("pytest timed out for %s", label)
            return self._empty_results(label, error="timeout")

        # Parse json-report output
        if json_file.exists():
            try:
                raw = json.loads(json_file.read_text())
                results = self._parse_json_report(raw, label)
                json_file.unlink(missing_ok=True)
                return results
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("Failed to parse json-report for %s: %s", label, exc)
                json_file.unlink(missing_ok=True)

        # Fallback: parse stdout
        return self._parse_stdout(proc.stdout, proc.returncode, label)

    # ------------------------------------------------------------------
    # JSON-report parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_report(raw: dict, label: str) -> dict[str, Any]:
        summary = raw.get("summary", {})
        tests = raw.get("tests", [])

        by_module: dict[str, dict[str, int]] = {}
        for t in tests:
            nodeid = t.get("nodeid", "")
            module = nodeid.split("::")[0] if "::" in nodeid else nodeid
            outcome = t.get("outcome", "unknown")
            entry = by_module.setdefault(module, {"passed": 0, "failed": 0, "skipped": 0, "error": 0})
            if outcome == "passed":
                entry["passed"] += 1
            elif outcome == "failed":
                entry["failed"] += 1
            elif outcome in ("skipped", "deselected"):
                entry["skipped"] += 1
            else:
                entry["error"] += 1

        return {
            "total": summary.get("total", 0),
            "passed": summary.get("passed", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0) + summary.get("deselected", 0),
            "error": summary.get("error", 0),
            "duration_s": round(raw.get("duration", 0), 2),
            "by_module": by_module,
        }

    # ------------------------------------------------------------------
    # Stdout fallback parser
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_stdout(stdout: str, returncode: int, label: str) -> dict[str, Any]:
        """Best-effort parse of pytest summary line like '10 passed, 2 failed'."""
        import re

        total = passed = failed = skipped = errors = 0
        # Match patterns like "10 passed", "2 failed", "1 skipped", "3 error"
        for match in re.finditer(r"(\d+)\s+(passed|failed|skipped|error|warnings)", stdout):
            count = int(match.group(1))
            kind = match.group(2)
            if kind == "passed":
                passed = count
            elif kind == "failed":
                failed = count
            elif kind == "skipped":
                skipped = count
            elif kind == "error":
                errors = count
        total = passed + failed + skipped + errors

        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "error": errors,
            "duration_s": 0,
            "by_module": {},
        }

    @staticmethod
    def _empty_results(label: str, error: str | None = None) -> dict[str, Any]:
        return {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": 0,
            "duration_s": 0,
            "by_module": {},
            **({"run_error": error} if error else {}),
        }

    # ------------------------------------------------------------------
    # Density / untested module analysis
    # ------------------------------------------------------------------

    def _compute_density(
        self, src_dir: Path, test_dir: Path
    ) -> dict[str, Any]:
        """Compute test density and find untested source modules."""
        if not src_dir.is_dir():
            return {"source_files": 0, "test_files": 0, "density": 0, "untested_modules": []}

        source_files = self._find_py_files(src_dir)
        test_files = self._find_py_files(test_dir) if test_dir.is_dir() else []

        # Build set of tested module basenames (strip test_ prefix)
        tested_names: set[str] = set()
        for tf in test_files:
            name = tf.stem
            if name.startswith("test_"):
                tested_names.add(name[5:])
            else:
                tested_names.add(name)

        # Find untested source modules
        untested: list[str] = []
        for sf in source_files:
            name = sf.stem
            if name.startswith("_"):
                continue  # skip __init__, __main__, etc.
            if name == "conftest":
                continue
            if name not in tested_names:
                rel = str(sf.relative_to(src_dir))
                untested.append(rel)

        src_count = len(source_files)
        test_count = len(test_files)
        density = round(test_count / src_count, 2) if src_count > 0 else 0

        return {
            "source_files": src_count,
            "test_files": test_count,
            "density": density,
            "untested_modules": sorted(untested),
        }

    @staticmethod
    def _find_py_files(directory: Path) -> list[Path]:
        """Find all .py files in directory, excluding junk dirs."""
        results = []
        if not directory.is_dir():
            return results
        for p in directory.rglob("*.py"):
            if _is_excluded(p):
                continue
            results.append(p)
        return results

    # ------------------------------------------------------------------
    # Totals
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_totals(*results: dict[str, Any]) -> dict[str, Any]:
        total = passed = failed = skipped = errors = 0
        duration = 0.0
        for r in results:
            total += r.get("total", 0)
            passed += r.get("passed", 0)
            failed += r.get("failed", 0)
            skipped += r.get("skipped", 0)
            errors += r.get("error", 0)
            duration += r.get("duration_s", 0)
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "error": errors,
            "duration_s": round(duration, 2),
        }

    # ------------------------------------------------------------------
    # Trend comparison
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_trend(
        current: dict[str, Any], previous: dict[str, Any]
    ) -> dict[str, Any]:
        ct = current.get("totals", {})
        pt = previous.get("totals", {})
        return {
            "total_delta": ct.get("total", 0) - pt.get("total", 0),
            "passed_delta": ct.get("passed", 0) - pt.get("passed", 0),
            "failed_delta": ct.get("failed", 0) - pt.get("failed", 0),
            "duration_delta": round(
                ct.get("duration_s", 0) - pt.get("duration_s", 0), 2
            ),
            "previous_timestamp": previous.get("timestamp", ""),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_report(self, report: dict[str, Any]) -> Path:
        ts = report["timestamp"].replace(":", "-").replace("+", "_")
        filename = f"report_{ts}.json"
        path = self.reports_dir / filename
        path.write_text(json.dumps(report, indent=2, default=str))
        # Also write a 'latest.json' symlink-like file
        latest = self.reports_dir / "latest.json"
        latest.write_text(json.dumps(report, indent=2, default=str))
        logger.info("Test report saved: %s", path)
        return path

    def _load_previous(self) -> dict[str, Any] | None:
        """Load the most recent report from disk."""
        latest = self.reports_dir / "latest.json"
        if latest.exists():
            try:
                return json.loads(latest.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        # Fallback: find newest report_*.json
        reports = sorted(self.reports_dir.glob("report_*.json"), reverse=True)
        if reports:
            try:
                return json.loads(reports[0].read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return None


# ---------------------------------------------------------------------------
# HTML renderer
# ---------------------------------------------------------------------------

def _render_html(report: dict[str, Any]) -> str:
    """Generate a cyberpunk-styled HTML summary of the test report."""
    _esc = _html_mod.escape
    totals = report.get("totals", {})
    trend = report.get("trend", {})
    projects = report.get("projects", {})

    def _arrow(delta: int | float) -> str:
        if delta > 0:
            return f'<span style="color:#05ffa1">+{delta}</span>'
        elif delta < 0:
            return f'<span style="color:#ff2a6d">{delta}</span>'
        return '<span style="color:#888">0</span>'

    def _pct(passed: int, total: int) -> str:
        if total == 0:
            return "N/A"
        return f"{round(100 * passed / total, 1)}%"

    project_rows = ""
    for name, proj in projects.items():
        untested_count = len(proj.get("untested_modules", []))
        untested_list = ", ".join(proj.get("untested_modules", [])[:10])
        if untested_count > 10:
            untested_list += f" ... (+{untested_count - 10} more)"
        project_rows += f"""
        <tr>
            <td>{_esc(str(name))}</td>
            <td>{int(proj.get('total', 0))}</td>
            <td style="color:#05ffa1">{int(proj.get('passed', 0))}</td>
            <td style="color:#ff2a6d">{int(proj.get('failed', 0))}</td>
            <td>{int(proj.get('skipped', 0))}</td>
            <td>{float(proj.get('duration_s', 0))}s</td>
            <td>{float(proj.get('density', 0))}</td>
            <td title="{_esc(untested_list)}">{untested_count}</td>
        </tr>"""

    # Module breakdown
    module_rows = ""
    for proj_name, proj in projects.items():
        for mod, counts in sorted(proj.get("by_module", {}).items()):
            if counts.get("failed", 0) > 0 or counts.get("error", 0) > 0:
                color = "#ff2a6d"
            else:
                color = "#05ffa1"
            module_rows += f"""
            <tr>
                <td>{_esc(str(proj_name))}</td>
                <td>{_esc(str(mod))}</td>
                <td style="color:#05ffa1">{int(counts.get('passed', 0))}</td>
                <td style="color:#ff2a6d">{int(counts.get('failed', 0))}</td>
                <td>{int(counts.get('skipped', 0))}</td>
            </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tritium Test Report</title>
<style>
  body {{ background: #0a0a0f; color: #c8c8d0; font-family: 'JetBrains Mono', 'Fira Code', monospace; margin: 0; padding: 20px; }}
  h1 {{ color: #00f0ff; font-size: 1.4rem; border-bottom: 1px solid #1a1a2e; padding-bottom: 8px; }}
  h2 {{ color: #00f0ff; font-size: 1.1rem; margin-top: 24px; }}
  .summary {{ display: flex; gap: 24px; flex-wrap: wrap; margin: 16px 0; }}
  .stat {{ background: #0e0e14; border: 1px solid #1a1a2e; border-radius: 6px; padding: 12px 20px; min-width: 120px; }}
  .stat-label {{ font-size: 0.65rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }}
  .stat-value {{ font-size: 1.6rem; font-weight: bold; margin-top: 4px; }}
  .stat-trend {{ font-size: 0.7rem; margin-top: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 0.75rem; }}
  th {{ background: #12121a; color: #00f0ff; text-align: left; padding: 6px 10px; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1px; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #1a1a2e; }}
  tr:hover {{ background: #12121a; }}
  .pass {{ color: #05ffa1; }}
  .fail {{ color: #ff2a6d; }}
  .timestamp {{ color: #888; font-size: 0.7rem; }}
</style>
</head>
<body>
<h1>TRITIUM TEST REPORT</h1>
<p class="timestamp">Generated: {_esc(str(report.get('timestamp', 'N/A')))} | Duration: {float(report.get('duration_s', 0))}s</p>

<div class="summary">
  <div class="stat">
    <div class="stat-label">Total Tests</div>
    <div class="stat-value" style="color:#00f0ff">{totals.get('total', 0)}</div>
    <div class="stat-trend">{_arrow(trend.get('total_delta', 0))}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Passed</div>
    <div class="stat-value pass">{totals.get('passed', 0)}</div>
    <div class="stat-trend">{_arrow(trend.get('passed_delta', 0))}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Failed</div>
    <div class="stat-value fail">{totals.get('failed', 0)}</div>
    <div class="stat-trend">{_arrow(trend.get('failed_delta', 0))}</div>
  </div>
  <div class="stat">
    <div class="stat-label">Pass Rate</div>
    <div class="stat-value" style="color:#fcee0a">{_pct(totals.get('passed', 0), totals.get('total', 0))}</div>
  </div>
</div>

<h2>BY PROJECT</h2>
<table>
<tr><th>Project</th><th>Total</th><th>Pass</th><th>Fail</th><th>Skip</th><th>Duration</th><th>Density</th><th>Untested</th></tr>
{project_rows}
</table>

<h2>MODULE BREAKDOWN (failures highlighted)</h2>
<table>
<tr><th>Project</th><th>Module</th><th>Pass</th><th>Fail</th><th>Skip</th></tr>
{module_rows if module_rows else '<tr><td colspan="5">No module-level data available</td></tr>'}
</table>

</body>
</html>"""
