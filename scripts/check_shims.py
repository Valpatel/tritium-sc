#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 -- see LICENSE for details.
"""
Shim audit tool: detects engine/ files that re-export from tritium_lib.

For each shim, checks whether any other file imports from it.
Reports DELETE (no importers) or KEEP (has importers) for each shim.
Exit code = number of deletable shims (0 = all clean).

Usage:
    PYTHONPATH=src python3 scripts/check_shims.py
    PYTHONPATH=src python3 scripts/check_shims.py --verbose
    PYTHONPATH=src python3 scripts/check_shims.py --json
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path


def find_shims(engine_dir: Path) -> list[dict]:
    """Find all Python files in engine/ that contain 'from tritium_lib... import *'."""
    shims = []
    pattern = re.compile(r"from\s+(tritium_lib\S+)\s+import\s+\*")

    for root, _dirs, files in os.walk(engine_dir):
        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = pattern.search(text)
            if match:
                lib_module = match.group(1)
                # Derive the engine import path from filesystem
                rel = fpath.relative_to(engine_dir.parent)
                # e.g. engine/tactical/dossier.py -> engine.tactical.dossier
                module_path = str(rel).replace("/", ".").removesuffix(".py")
                shims.append({
                    "path": str(fpath),
                    "rel_path": str(rel),
                    "module_path": module_path,
                    "lib_module": lib_module,
                    "importers": [],
                })
    return shims


def find_importers(shims: list[dict], search_dirs: list[Path]) -> None:
    """For each shim, find files that import from its module path."""
    # Build lookup: module_path -> shim entry
    shim_lookup: dict[str, dict] = {}
    for shim in shims:
        shim_lookup[shim["module_path"]] = shim

    # Build regex patterns for matching imports from shim modules.
    # We match:
    #   from engine.tactical.dossier import X
    #   import engine.tactical.dossier
    #   from engine.tactical.dossier import *
    # but NOT if that's the shim file itself.
    shim_paths_set = {s["path"] for s in shims}

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for root, _dirs, files in os.walk(search_dir):
            for fname in sorted(files):
                if not fname.endswith(".py"):
                    continue
                fpath = Path(root) / fname
                fpath_str = str(fpath)

                # Skip the shim file itself
                if fpath_str in shim_paths_set:
                    continue

                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                for module_path, shim in shim_lookup.items():
                    # Match various import forms
                    # from engine.tactical.dossier import Foo
                    # from engine.tactical.dossier import (Foo, Bar)
                    # import engine.tactical.dossier
                    patterns = [
                        rf"from\s+{re.escape(module_path)}\s+import\s+",
                        rf"import\s+{re.escape(module_path)}\b",
                    ]
                    for pat in patterns:
                        if re.search(pat, text):
                            shim["importers"].append(fpath_str)
                            break  # Don't double-count same file


def print_report(shims: list[dict], verbose: bool = False) -> tuple[int, int, int]:
    """Print the shim report and return (total, deletable, active) counts."""
    deletable = 0
    active = 0

    print("=" * 60)
    print("  SHIM REPORT")
    print("=" * 60)
    print()

    # Group by subdirectory for readability
    by_subdir: dict[str, list[dict]] = {}
    for shim in shims:
        parts = shim["module_path"].split(".")
        subdir = parts[1] if len(parts) > 2 else "root"
        by_subdir.setdefault(subdir, []).append(shim)

    for subdir in sorted(by_subdir):
        print(f"  [{subdir}]")
        for shim in sorted(by_subdir[subdir], key=lambda s: s["module_path"]):
            n_imp = len(shim["importers"])
            verdict = "DELETE" if n_imp == 0 else "KEEP"
            if n_imp == 0:
                deletable += 1
                marker = "  [-]"
            else:
                active += 1
                marker = "  [+]"

            # Compact display
            mod = shim["module_path"]
            lib = shim["lib_module"]
            print(f"{marker} {mod}")
            print(f"       -> {lib}")
            print(f"       {n_imp} importer(s)  [{verdict}]")

            if verbose and shim["importers"]:
                for imp in sorted(shim["importers"]):
                    print(f"         - {imp}")
            print()

    total = deletable + active
    print("-" * 60)
    print(f"  Total shims: {total}")
    print(f"  Deletable:   {deletable}")
    print(f"  Active:      {active}")
    print("-" * 60)

    return total, deletable, active


def main():
    parser = argparse.ArgumentParser(description="Audit engine/ shims that re-export from tritium_lib")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show importer file paths")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text report")
    parser.add_argument("--engine-dir", default=None, help="Path to engine/ directory")
    args = parser.parse_args()

    # Find project root relative to this script
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent

    engine_dir = Path(args.engine_dir) if args.engine_dir else project_root / "src" / "engine"
    if not engine_dir.is_dir():
        print(f"ERROR: engine directory not found: {engine_dir}", file=sys.stderr)
        sys.exit(1)

    src_dir = project_root / "src"
    tests_dir = project_root / "tests"

    # Step 1: Find all shims
    shims = find_shims(engine_dir)
    if not shims:
        print("No shims found. All clean!")
        sys.exit(0)

    # Step 2: Find importers
    find_importers(shims, [src_dir, tests_dir])

    # Step 3: Report
    if args.json:
        output = {
            "shims": shims,
            "total": len(shims),
            "deletable": sum(1 for s in shims if len(s["importers"]) == 0),
            "active": sum(1 for s in shims if len(s["importers"]) > 0),
        }
        print(json.dumps(output, indent=2))
        deletable = output["deletable"]
    else:
        _total, deletable, _active = print_report(shims, verbose=args.verbose)

    # Exit code = number of deletable shims
    sys.exit(deletable)


if __name__ == "__main__":
    main()
