"""Persistent daily transcript for Amy.

Append-only JSONL files at amy/transcripts/YYYY-MM-DD.jsonl.
Thread-safe, auto-rotates on date change.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path


class Transcript:
    """Append-only daily transcript stored as JSONL."""

    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), "transcripts")
        self._base_dir = base_dir
        os.makedirs(self._base_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._current_date: str = ""
        self._file = None
        self._rotate()

    def _rotate(self) -> None:
        """Open (or rotate to) the file for today's date."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today == self._current_date and self._file is not None:
            return
        if self._file is not None:
            self._file.close()
        self._current_date = today
        path = os.path.join(self._base_dir, f"{today}.jsonl")
        self._file = open(path, "a", encoding="utf-8")

    def append(self, speaker: str, text: str, entry_type: str = "speech") -> None:
        """Append an entry to today's transcript."""
        entry = {
            "ts": datetime.now().isoformat(),
            "speaker": speaker,
            "text": text,
            "type": entry_type,
        }
        with self._lock:
            self._rotate()
            self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._file.flush()

    def get_recent(self, count: int = 10, entry_type: str | None = None) -> list[dict]:
        """Return the last N entries from today's transcript."""
        with self._lock:
            self._rotate()
            path = os.path.join(self._base_dir, f"{self._current_date}.jsonl")
        return self._read_tail(path, count, entry_type)

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search today's transcript for entries matching query."""
        with self._lock:
            self._rotate()
            path = os.path.join(self._base_dir, f"{self._current_date}.jsonl")
        query_lower = query.lower()
        results: list[dict] = []
        if not os.path.exists(path):
            return results
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if query_lower in entry.get("text", "").lower():
                    results.append(entry)
                    if len(results) >= limit:
                        break
        return results

    def close(self) -> None:
        """Close the transcript file."""
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None

    @staticmethod
    def _read_tail(path: str, count: int, entry_type: str | None = None) -> list[dict]:
        """Read the last N entries from a JSONL file."""
        if not os.path.exists(path):
            return []
        entries: list[dict] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry_type is not None and entry.get("type") != entry_type:
                    continue
                entries.append(entry)
        return entries[-count:]
