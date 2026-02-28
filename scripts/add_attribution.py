#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Add attribution headers to all source files in the project."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", ".claude", ".pytest_cache"}

# Attribution text per comment style
PY_HEADER = (
    "# Created by Matthew Valancy\n"
    "# Copyright 2026 Valpatel Software LLC\n"
    "# Licensed under AGPL-3.0 — see LICENSE for details.\n"
)

JS_HEADER = (
    "// Created by Matthew Valancy\n"
    "// Copyright 2026 Valpatel Software LLC\n"
    "// Licensed under AGPL-3.0 — see LICENSE for details.\n"
)

CSS_HEADER = (
    "/* Created by Matthew Valancy\n"
    " * Copyright 2026 Valpatel Software LLC\n"
    " * Licensed under AGPL-3.0 — see LICENSE for details.\n"
    " */\n"
)

HTML_HEADER = (
    "<!-- Created by Matthew Valancy\n"
    "     Copyright 2026 Valpatel Software LLC\n"
    "     Licensed under AGPL-3.0 — see LICENSE for details. -->\n"
)

SH_HEADER = (
    "# Created by Matthew Valancy\n"
    "# Copyright 2026 Valpatel Software LLC\n"
    "# Licensed under AGPL-3.0 — see LICENSE for details.\n"
)

HEADERS = {
    ".py": PY_HEADER,
    ".js": JS_HEADER,
    ".css": CSS_HEADER,
    ".html": HTML_HEADER,
    ".sh": SH_HEADER,
}

MARKER = "Valpatel Software LLC"


def should_skip(path: Path) -> bool:
    parts = path.relative_to(PROJECT_ROOT).parts
    return any(p in SKIP_DIRS for p in parts)


def add_header(path: Path, dry_run: bool = False) -> bool:
    try:
        content = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError):
        return False

    if MARKER in content:
        return False  # already has attribution

    ext = path.suffix
    header = HEADERS.get(ext)
    if not header:
        return False

    if dry_run:
        return True

    # Handle shebang lines in .py and .sh — keep them first
    if ext in (".py", ".sh") and content.startswith("#!"):
        first_newline = content.index("\n") + 1
        shebang = content[:first_newline]
        rest = content[first_newline:]
        new_content = shebang + header + rest
    else:
        new_content = header + content

    path.write_text(new_content, encoding="utf-8")
    return True


def main():
    dry_run = "--dry-run" in sys.argv
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    extensions = set(HEADERS.keys())
    modified = 0
    skipped = 0
    already = 0

    for root, dirs, files in os.walk(PROJECT_ROOT):
        # Prune skip dirs
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in sorted(files):
            fpath = Path(root) / fname
            if fpath.suffix not in extensions:
                continue
            if should_skip(fpath):
                skipped += 1
                continue

            content = ""
            try:
                content = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                skipped += 1
                continue

            if MARKER in content:
                already += 1
                continue

            if add_header(fpath, dry_run=dry_run):
                modified += 1
                if verbose:
                    rel = fpath.relative_to(PROJECT_ROOT)
                    action = "would add" if dry_run else "added"
                    print(f"  {action}: {rel}")

    mode = "DRY RUN" if dry_run else "DONE"
    print(f"\n[{mode}] {modified} files {'would be ' if dry_run else ''}modified, "
          f"{already} already had attribution, {skipped} skipped")


if __name__ == "__main__":
    main()
