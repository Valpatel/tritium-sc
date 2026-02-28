#!/usr/bin/env python3
# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""LLM review of gameplay test results using qwen2.5:7b on a remote Ollama host."""

import json, os, subprocess, sys, requests
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path("tests/ui/.gameplay-results")
REMOTE_OLLAMA_HOST = os.environ.get("REMOTE_OLLAMA_HOST", "")
REMOTE_OLLAMA = f"http://{REMOTE_OLLAMA_HOST}:11434" if REMOTE_OLLAMA_HOST else ""

def find_latest_report():
    dirs = sorted(RESULTS_DIR.iterdir(), reverse=True) if RESULTS_DIR.exists() else []
    for d in dirs:
        report = d / "report.json"
        if report.exists():
            return report
    return None

def review_with_llm(report_data: dict) -> str:
    """Send report to qwen2.5:7b for review."""
    prompt = f"""Review this UI gameplay test report for a tactical RTS game called TRITIUM-SC.

Report:
{json.dumps(report_data, indent=2)}

For each test result:
1. Was it a PASS or FAIL?
2. If FAIL, what might be wrong based on the LLM response?
3. Any suggestions for improving the test prompts?

Provide a concise summary."""

    if not REMOTE_OLLAMA:
        return "SKIPPED: REMOTE_OLLAMA_HOST not set"

    try:
        resp = requests.post(f"{REMOTE_OLLAMA}/api/generate", json={
            "model": "qwen2.5:7b",
            "prompt": prompt,
            "stream": False,
        }, timeout=300)
        return resp.json().get("response", "No response")
    except requests.ConnectionError:
        # Try via SSH tunnel
        payload = json.dumps({"model": "qwen2.5:7b", "prompt": prompt, "stream": False})
        result = subprocess.run([
            "ssh", REMOTE_OLLAMA_HOST,
            f"curl -s http://localhost:11434/api/generate -d '{payload}'"
        ], capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            return json.loads(result.stdout).get("response", "No response")
        return f"Failed to reach {REMOTE_OLLAMA_HOST}: {result.stderr}"

def main():
    if not REMOTE_OLLAMA_HOST:
        print("REMOTE_OLLAMA_HOST not set — skipping LLM review.")
        print("Usage: REMOTE_OLLAMA_HOST=myhost python3 tests/ui/test_review.py")
        sys.exit(0)

    report_path = find_latest_report()
    if not report_path:
        print("No gameplay test reports found. Run test_gameplay.py first.")
        sys.exit(1)

    print(f"Reviewing: {report_path}")
    with open(report_path) as f:
        report = json.load(f)

    print(f"Sending to qwen2.5:7b on {REMOTE_OLLAMA_HOST}...")
    review = review_with_llm(report)

    print("\n=== LLM REVIEW ===")
    print(review)

    # Save review
    review_path = report_path.parent / "review.txt"
    review_path.write_text(f"Review by qwen2.5:7b at {datetime.now().isoformat()}\n\n{review}")
    print(f"\nSaved to: {review_path}")

if __name__ == "__main__":
    main()
