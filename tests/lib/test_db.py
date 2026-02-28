# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Backward-compatible shim — imports moved to results_db.py.

The class was renamed from TestDB to ResultsDB and moved to results_db.py
to avoid PytestCollectionWarning (the test_ prefix caused pytest to scan
this file for test classes).

New code should import from tests.lib.results_db.
"""
# Do NOT import at module level to avoid pytest collection warnings.
# Use __getattr__ for lazy import so pytest does not see any classes here.


def __getattr__(name):
    if name in ("ResultsDB", "TestDB"):
        from tests.lib.results_db import ResultsDB
        return ResultsDB
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ResultsDB", "TestDB"]
