# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ResultsDB — SQLite store for test results, screenshots, and trends.

Persists test run data across sessions for reporting, trend analysis,
and fleet-parallel vision audit results.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    suite TEXT NOT NULL,
    git_hash TEXT,
    machine TEXT,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    total_tests INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    test_name TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    duration_ms REAL,
    details_json TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES runs(id),
    test_name TEXT,
    phase TEXT,
    image_path TEXT,
    opencv_json TEXT,
    llava_response TEXT,
    llava_host TEXT,
    llava_ms REAL,
    api_state_json TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);
"""


class ResultsDB:
    """SQLite test results store.

    Args:
        db_path: Path to SQLite database file. Parent dirs are created
                 automatically.
    """

    def __init__(self, db_path: str = "tests/.test-results/results.db"):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_run(self, suite: str, git_hash: str, machine: str) -> int:
        """Start a new test run. Returns the run ID."""
        cur = self._conn.execute(
            "INSERT INTO runs (suite, git_hash, machine) VALUES (?, ?, ?)",
            (suite, git_hash, machine),
        )
        self._conn.commit()
        return cur.lastrowid

    def record_result(
        self,
        run_id: int,
        test_name: str,
        passed: bool,
        duration_ms: float,
        details: dict[str, Any],
    ) -> None:
        """Record a single test result and update run counts."""
        self._conn.execute(
            "INSERT INTO results (run_id, test_name, passed, duration_ms, details_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, test_name, passed, duration_ms, json.dumps(details)),
        )
        self._conn.execute(
            "UPDATE runs SET total_tests = total_tests + 1, "
            "passed = passed + ?, failed = failed + ? WHERE id = ?",
            (1 if passed else 0, 0 if passed else 1, run_id),
        )
        self._conn.commit()

    def record_screenshot(
        self,
        run_id: int,
        test_name: str,
        phase: str,
        image_path: str,
        opencv_results: dict[str, Any],
        llava_response: str,
        llava_host: str,
        llava_ms: float,
        api_state: dict[str, Any],
    ) -> None:
        """Record a screenshot analysis result."""
        self._conn.execute(
            "INSERT INTO screenshots "
            "(run_id, test_name, phase, image_path, opencv_json, "
            "llava_response, llava_host, llava_ms, api_state_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id, test_name, phase, image_path,
                json.dumps(opencv_results), llava_response,
                llava_host, llava_ms, json.dumps(api_state),
            ),
        )
        self._conn.commit()

    def finish_run(self, run_id: int) -> None:
        """Mark a run as finished (sets finished_at timestamp)."""
        self._conn.execute(
            "UPDATE runs SET finished_at = datetime('now') WHERE id = ?",
            (run_id,),
        )
        self._conn.commit()

    def get_run_summary(self, run_id: int) -> dict[str, Any] | None:
        """Get summary for a run. Returns None if not found."""
        row = self._conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def get_failures(self, run_id: int) -> list[dict[str, Any]]:
        """Get all failed results for a run."""
        rows = self._conn.execute(
            "SELECT * FROM results WHERE run_id = ? AND passed = 0 "
            "ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("details_json"):
                d["details"] = json.loads(d["details_json"])
            results.append(d)
        return results

    def get_trend(self, suite: str, last_n: int = 20) -> list[dict[str, Any]]:
        """Get the last N runs for a suite, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM runs WHERE suite = ? "
            "ORDER BY id DESC LIMIT ?",
            (suite, last_n),
        ).fetchall()
        # Reverse to chronological order (oldest first)
        return [dict(r) for r in reversed(rows)]

    def get_screenshots(self, run_id: int) -> list[dict[str, Any]]:
        """Get all screenshots for a run, ordered by timestamp."""
        rows = self._conn.execute(
            "SELECT * FROM screenshots WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("opencv_json"):
                d["opencv_results"] = json.loads(d["opencv_json"])
            if d.get("api_state_json"):
                d["api_state"] = json.loads(d["api_state_json"])
            results.append(d)
        return results

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


# Backward-compatible alias (TestDB was renamed to avoid PytestCollectionWarning)
TestDB = ResultsDB
