#!/usr/bin/env python3
"""Run scenarios and report behavioral profiles.

Usage:
    .venv/bin/python3 run_scenarios.py [scenario_name ...]

If no scenario names given, runs a default set of interesting ones.
"""

import json
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from amy.scenarios.library import ScenarioLibrary
from amy.scenarios.runner import ScenarioRunner


DEFAULTS = [
    "self_introduction",
    "empty_room",
    "rapid_questions",
]


def run_one(lib: ScenarioLibrary, name: str) -> dict:
    """Run one scenario, save result, return summary."""
    print(f"\n{'='*60}")
    print(f"  SCENARIO: {name}")
    print(f"{'='*60}")

    scenario = lib.load_scenario(name)
    print(f"  Description: {scenario.description}")
    print(f"  Duration: {scenario.duration}s (x{scenario.time_scale} = "
          f"{scenario.duration * scenario.time_scale:.1f}s real)")
    print(f"  Events: {len(scenario.events)}, Expected: {len(scenario.expected)}")
    print()

    runner = ScenarioRunner(
        scenario,
        chat_model="gemma3:4b",
        deep_model="llava:7b",
    )

    t0 = time.time()
    result = runner.run()
    elapsed = time.time() - t0

    # Save
    lib.save_result(result)

    print(f"\n  Status: {result.status}")
    print(f"  Wall time: {elapsed:.1f}s")
    print(f"  Actions recorded: {len(result.actions)}")

    # Show actions
    print(f"\n  --- Amy's Actions ---")
    for a in result.actions:
        prefix = f"  [{a.timestamp:5.1f}s] {a.category:>9s}/{a.action_type}"
        text = a.text[:80] if a.text else ""
        print(f"  {prefix}: {text}")

    # Score
    s = result.score
    print(f"\n  --- Score ---")
    print(f"  Total: {s.total_score:.3f} ({s.matched}/{s.total_expected} matched)")
    print(f"  Detection accuracy: {s.detection_accuracy:.3f}")
    print(f"  Avg response latency: {s.avg_response_latency:.1f}s")

    if s.behavioral:
        b = s.behavioral
        print(f"\n  --- Behavioral Profile ---")
        print(f"  Composite:           {b.composite_score:.3f}")
        print(f"  Verbosity:           {b.verbosity:.3f}")
        print(f"  Lexical Diversity:   {b.lexical_diversity:.3f}")
        print(f"  Think-Speak Balance: {b.think_speak_balance:.3f}")
        print(f"  Responsiveness:      {b.responsiveness:.3f}")
        print(f"  Initiative:          {b.initiative:.3f}")
        print(f"  Emotional Coherence: {b.emotional_coherence:.3f}")
        print(f"  Safety:              {b.safety:.3f}")
        print(f"  Counts: {b.speech_count} speech, {b.thought_count} thought, "
              f"{b.goal_count} goal, {b.user_utterance_count} user utterances")

    summary = {
        "scenario": name,
        "status": result.status,
        "total_score": s.total_score,
        "actions": len(result.actions),
        "wall_time": round(elapsed, 1),
    }
    if s.behavioral:
        summary["behavioral_composite"] = s.behavioral.composite_score
    return summary


def main():
    names = sys.argv[1:] if len(sys.argv) > 1 else DEFAULTS

    lib = ScenarioLibrary()
    results = []

    for name in names:
        try:
            summary = run_one(lib, name)
            results.append(summary)
        except Exception as e:
            print(f"\n  FAILED: {e}")
            results.append({"scenario": name, "status": "error", "error": str(e)})

    print(f"\n\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status = r.get("status", "?")
        score = r.get("total_score", 0)
        beh = r.get("behavioral_composite", "n/a")
        print(f"  {r['scenario']:30s}  status={status}  score={score:.3f}  behavioral={beh}")


if __name__ == "__main__":
    main()
