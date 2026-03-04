# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Combat Matrix — parametric battle validation.

Generates randomized battle configurations, runs each in a headed browser,
collects every measurable metric, and verifies against computed expectations.

Usage:
    # Fast sweep (50 configs, ~25 min)
    .venv/bin/python3 -m pytest tests/visual/test_combat_matrix.py -v -s

    # Quick smoke (10 configs, ~5 min)
    .venv/bin/python3 -m pytest tests/visual/test_combat_matrix.py -v -s --matrix-count=10

    # Full sweep (42 configs from all loadout x ratio combos, ~35 min)
    .venv/bin/python3 -m pytest tests/visual/test_combat_matrix.py -v -s --full-sweep
"""

from __future__ import annotations

import logging

import pytest

from tests.combat_matrix.assertion_engine import check_assertions
from tests.combat_matrix.battle_runner import run_battle
from tests.combat_matrix.config_matrix import ConfigMatrix
from tests.combat_matrix.metrics import BattleMetrics
from tests.combat_matrix.report import generate_report
from tests.combat_matrix.scenario_factory import cleanup as cleanup_scenarios

logger = logging.getLogger(__name__)


class TestCombatMatrix:
    """Parametric combat validation suite."""

    def test_combat_matrix(self, tritium_server, request):
        """Run all battle configurations and verify metrics."""
        full_sweep = request.config.getoption("--full-sweep", False)
        matrix_count = request.config.getoption("--matrix-count", 50)

        # Generate configs
        if full_sweep:
            configs = ConfigMatrix.generate_full_sweep()
            logger.info("Full sweep: %d configurations", len(configs))
        else:
            configs = ConfigMatrix.generate_fast_sweep(count=matrix_count)
            logger.info("Fast sweep: %d configurations", len(configs))

        base_url = tritium_server.url

        # Try to get a Playwright browser
        page = None
        browser = None
        pw_instance = None
        try:
            from playwright.sync_api import sync_playwright
            pw_instance = sync_playwright().start()
            browser = pw_instance.chromium.launch(
                headless=False,
                args=["--window-size=1920,1080"],
            )
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            logger.info("Playwright browser launched (headed)")
        except Exception as exc:
            logger.warning("Playwright not available, running without browser: %s", exc)

        results: list[BattleMetrics] = []
        critical_failures = 0

        try:
            for i, config in enumerate(configs):
                logger.info(
                    "[%d/%d] Running %s (%dv%d %s %.0fm)",
                    i + 1, len(configs),
                    config.config_id,
                    config.defender_count, config.hostile_count,
                    config.loadout_profile, config.map_bounds,
                )

                # Run battle
                metrics = run_battle(config, base_url, page=page)

                # Check assertions
                assertions = check_assertions(config, metrics)
                metrics.assertions = assertions

                # Log result
                crit_ok = metrics.critical_pass
                pass_rate = metrics.pass_rate
                if not crit_ok:
                    critical_failures += 1
                    logger.error(
                        "  CRITICAL FAIL: %s — %d/%d assertions passed",
                        config.config_id,
                        sum(1 for a in assertions if a.passed),
                        len(assertions),
                    )
                else:
                    logger.info(
                        "  OK: %s — %.0f%% pass (%s, score=%d, shots=%d, kills=%d)",
                        config.config_id,
                        pass_rate * 100,
                        metrics.game_result,
                        metrics.final_score,
                        metrics.total_shots_fired,
                        metrics.total_eliminations,
                    )

                results.append(metrics)

        finally:
            # Generate report regardless of failures
            report_path = generate_report(configs[:len(results)], results)
            logger.info("Report: %s", report_path)
            print(f"\n{'='*60}")
            print(f"COMBAT MATRIX REPORT: file://{report_path}")
            print(f"Configs: {len(results)}/{len(configs)}")
            print(f"Critical pass: {len(results) - critical_failures}/{len(results)}")
            print(f"{'='*60}\n")

            # Cleanup
            cleanup_scenarios()
            if page is not None:
                page.close()
            if browser is not None:
                browser.close()
            if pw_instance is not None:
                pw_instance.stop()

        # Final assertion: zero critical failures
        assert critical_failures == 0, (
            f"{critical_failures}/{len(results)} configs had critical failures. "
            f"See report: file://{report_path}"
        )
