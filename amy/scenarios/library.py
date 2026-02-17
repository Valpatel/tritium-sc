"""ScenarioLibrary — load, list, and save scenarios and results."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .schema import Scenario, ScenarioResult


class ScenarioLibrary:
    """Manages scenario files and run results on disk.

    Scenarios are JSON files in `scenarios_dir`.
    Results are stored in `scenarios_dir/.results/`.
    """

    def __init__(self, scenarios_dir: str | Path | None = None):
        if scenarios_dir is None:
            # Default: <project_root>/scenarios/
            scenarios_dir = Path(__file__).parent.parent.parent / "scenarios"
        self._dir = Path(scenarios_dir)
        self._results_dir = self._dir / ".results"
        self._results_dir.mkdir(parents=True, exist_ok=True)

    def list_scenarios(self) -> list[dict]:
        """List all available scenarios with latest scores."""
        scenarios = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                scenario = self.load_scenario(path.stem)
                latest = self.get_latest_result(path.stem)
                scenarios.append({
                    "name": scenario.name,
                    "description": scenario.description,
                    "duration": scenario.duration,
                    "event_count": len(scenario.events),
                    "expected_count": len(scenario.expected),
                    "latest_score": latest.score.total_score if latest else None,
                    "latest_rating": latest.human_rating if latest else None,
                    "run_count": len(self.list_results(path.stem)),
                })
            except Exception:
                continue
        return scenarios

    def load_scenario(self, name: str) -> Scenario:
        """Load a scenario by name (without .json extension)."""
        path = self._dir / f"{name}.json"
        if not path.exists():
            raise FileNotFoundError(f"Scenario not found: {path}")
        with open(path) as f:
            data = json.load(f)
        return Scenario(**data)

    def save_scenario(self, scenario: Scenario) -> Path:
        """Save a scenario to disk."""
        path = self._dir / f"{scenario.name}.json"
        with open(path, "w") as f:
            json.dump(scenario.model_dump(), f, indent=2)
        return path

    def save_result(self, result: ScenarioResult) -> Path:
        """Save a run result to disk."""
        filename = f"{result.scenario_name}_{result.run_id}.json"
        path = self._results_dir / filename
        with open(path, "w") as f:
            json.dump(result.model_dump(), f, indent=2)
        return path

    def list_results(self, scenario_name: str) -> list[ScenarioResult]:
        """List all results for a scenario, newest first."""
        results = []
        prefix = f"{scenario_name}_"
        for path in sorted(self._results_dir.glob(f"{prefix}*.json"), reverse=True):
            try:
                with open(path) as f:
                    data = json.load(f)
                results.append(ScenarioResult(**data))
            except Exception:
                continue
        return results

    def get_latest_result(self, scenario_name: str) -> ScenarioResult | None:
        """Get the most recent result for a scenario."""
        results = self.list_results(scenario_name)
        return results[0] if results else None

    def rate_result(self, run_id: str, rating: int) -> bool:
        """Apply a human rating (1-5) to a result."""
        rating = max(1, min(5, rating))
        for path in self._results_dir.glob("*.json"):
            try:
                with open(path) as f:
                    data = json.load(f)
                if data.get("run_id") == run_id:
                    data["human_rating"] = rating
                    with open(path, "w") as f:
                        json.dump(data, f, indent=2)
                    return True
            except Exception:
                continue
        return False

    def get_stats(self) -> dict:
        """Aggregate improvement data across all scenarios."""
        stats = {}
        for path in sorted(self._dir.glob("*.json")):
            name = path.stem
            results = self.list_results(name)
            if not results:
                continue
            scores = [r.score.total_score for r in results]
            ratings = [r.human_rating for r in results if r.human_rating is not None]

            # Per-model breakdown for A/B testing
            by_model: dict[str, list[float]] = {}
            for r in results:
                model_key = r.config.get("chat_model", "unknown")
                by_model.setdefault(model_key, []).append(r.score.total_score)

            model_stats = {
                k: {"avg": round(sum(v) / len(v), 3), "runs": len(v)}
                for k, v in by_model.items()
            }

            stats[name] = {
                "run_count": len(results),
                "avg_score": round(sum(scores) / len(scores), 3) if scores else 0,
                "best_score": max(scores) if scores else 0,
                "latest_score": scores[0] if scores else 0,
                "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
                "score_trend": scores[:5],  # Most recent 5
                "by_model": model_stats,
            }
        return stats

    def export_results(self, scenario_name: str | None = None) -> list[dict]:
        """Export results for prompt optimization analysis.

        Returns a flat list of result dicts suitable for CSV/JSON export.
        """
        output = []
        names = [scenario_name] if scenario_name else [
            p.stem for p in sorted(self._dir.glob("*.json"))
        ]
        for name in names:
            for r in self.list_results(name):
                output.append({
                    "scenario": r.scenario_name,
                    "run_id": r.run_id,
                    "timestamp": r.timestamp,
                    "duration": r.duration_actual,
                    "score": r.score.total_score,
                    "matched": r.score.matched,
                    "total_expected": r.score.total_expected,
                    "detection_accuracy": r.score.detection_accuracy,
                    "avg_latency": r.score.avg_response_latency,
                    "human_rating": r.human_rating,
                    "chat_model": r.config.get("chat_model"),
                    "deep_model": r.config.get("deep_model"),
                    "system_prompt_override": r.config.get("system_prompt_override"),
                    "action_count": len(r.actions),
                    "status": r.status,
                    "beh_composite": r.score.behavioral.composite_score if r.score.behavioral else None,
                    "beh_verbosity": r.score.behavioral.verbosity if r.score.behavioral else None,
                    "beh_lexical_diversity": r.score.behavioral.lexical_diversity if r.score.behavioral else None,
                    "beh_think_speak_balance": r.score.behavioral.think_speak_balance if r.score.behavioral else None,
                    "beh_responsiveness": r.score.behavioral.responsiveness if r.score.behavioral else None,
                    "beh_initiative": r.score.behavioral.initiative if r.score.behavioral else None,
                    "beh_emotional_coherence": r.score.behavioral.emotional_coherence if r.score.behavioral else None,
                    "beh_safety": r.score.behavioral.safety if r.score.behavioral else None,
                })
        return output
