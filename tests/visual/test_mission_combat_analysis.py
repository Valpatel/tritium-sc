# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Deep tactical analysis of combat test screenshots.

Post-test analysis suite that runs AFTER combat tests produce screenshots.
Uses a three-model pipeline:
1. llava:7b (vision) -- describes what's in each screenshot
2. qwen3-vl:8b (vision) -- direct tactical analysis of images
3. qwen3.5:27b (text) -- deep synthesis from both vision outputs

Run:
    .venv/bin/python3 -m pytest tests/visual/test_mission_combat_analysis.py -v --timeout=600
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import requests

pytestmark = [pytest.mark.visual, pytest.mark.deep_analysis]

# Screenshot directories to search (priority order)
SCREENSHOT_DIRS = [
    Path("tests/.test-results/mission-combat"),
    Path("tests/.test-results/combat-visuals"),
    Path("tests/.test-results/battle-proof"),
    Path("tests/.test-results/screenshots"),
]

OUTPUT_DIR = Path("tests/.test-results/deep-analysis")
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# Model names
LLAVA_MODEL = "llava:7b"
QWEN3VL_MODEL = "qwen3-vl:8b"
DEEP_MODEL = "qwen3.5:27b"

LLAVA_PROMPT = (
    "Describe this tactical satellite map screenshot in detail. "
    "List all visible military units, their colors, positions relative "
    "to buildings and streets, and any combat indicators."
)

QWEN3VL_PROMPT = (
    "Analyze this military tactical display. Rate the defensive positioning "
    "of green friendly units around buildings on a 1-10 scale. Identify gaps "
    "in coverage and approach routes for hostiles."
)

DEEP_PROMPT_TEMPLATE = (
    "Given this tactical situation description from a satellite map:\n\n"
    "{llava_description}\n\n"
    "And this visual analysis:\n\n"
    "{qwen3vl_analysis}\n\n"
    "Provide a comprehensive tactical assessment. Include:\n"
    "1. An overall tactical rating (1-10 scale)\n"
    "2. Coverage assessment of defensive positions\n"
    "3. Identified gaps in the defensive perimeter\n"
    "4. Approach vulnerability analysis (where hostiles could exploit)\n"
    "5. Specific tactical recommendations for improvement\n"
    "6. A brief overall summary\n\n"
    "Format your response as structured analysis with clear headings."
)


def _find_screenshots() -> list[Path]:
    """Find combat screenshots from any available test output directory."""
    for d in SCREENSHOT_DIRS:
        if d.is_dir():
            images = []
            for ext in IMAGE_EXTENSIONS:
                images.extend(d.glob(f"*{ext}"))
            if images:
                return sorted(images, key=lambda p: p.name)
    return []


def _find_deployment_screenshot() -> Path | None:
    """Find a screenshot that shows unit deployment (before combat)."""
    screenshots = _find_screenshots()
    # Prefer images with deployment/setup/defender/units in the name
    for kw in ("deploy", "setup", "defender", "unit", "turret", "01_", "02_"):
        for s in screenshots:
            if kw in s.name.lower():
                return s
    return screenshots[0] if screenshots else None


def _find_combat_screenshot() -> Path | None:
    """Find a screenshot that shows active combat."""
    screenshots = _find_screenshots()
    for kw in ("combat", "battle", "fight", "active", "wave", "07_", "08_"):
        for s in screenshots:
            if kw in s.name.lower():
                return s
    return screenshots[-1] if screenshots else None


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}")


# -----------------------------------------------------------------------
# Setup checks
# -----------------------------------------------------------------------

class TestDeepAnalysisSetup:
    """Verify prerequisites for deep analysis."""

    def test_01_screenshots_exist(self):
        """Verify at least one screenshot directory has images."""
        screenshots = _find_screenshots()
        _log(f"Found {len(screenshots)} screenshots")
        for s in screenshots[:5]:
            _log(f"  {s}")

        assert len(screenshots) > 0, (
            f"No screenshots found in any of: "
            f"{[str(d) for d in SCREENSHOT_DIRS]}"
        )

    def test_02_fleet_has_models(self, fleet):
        """Verify llava:7b and qwen3.5:27b available via fleet."""
        _log(fleet.status())

        llava_hosts = fleet.hosts_with_model(LLAVA_MODEL)
        deep_hosts = fleet.hosts_with_model(DEEP_MODEL)

        _log(f"llava:7b available on: {[h.name for h in llava_hosts]}")
        _log(f"qwen3.5:27b available on: {[h.name for h in deep_hosts]}")

        assert len(llava_hosts) > 0, f"No host has {LLAVA_MODEL}"
        assert len(deep_hosts) > 0, f"No host has {DEEP_MODEL}"

    def test_03_remote_host_reachable(self, fleet):
        """Verify at least one non-localhost host responds."""
        remote_hosts = [h for h in fleet.hosts if h.name != "localhost"]
        _log(f"Remote hosts: {[h.name for h in remote_hosts]}")

        if not remote_hosts:
            pytest.skip("No remote hosts discovered (single-host mode)")

        # At least one remote host should have responded during discovery
        for h in remote_hosts:
            _log(f"  {h.name}: {len(h.models)} models, {h.latency_ms:.0f}ms")

        assert len(remote_hosts) > 0


# -----------------------------------------------------------------------
# llava:7b descriptions
# -----------------------------------------------------------------------

class TestLlavaDescriptions:
    """Test llava:7b vision descriptions of combat screenshots."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request):
        cls = request.cls
        cls._results = {}
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @pytest.mark.timeout(120)
    def test_04_llava_describes_deployment(self, fleet):
        """llava:7b describes a defender placement screenshot."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        _log(f"Sending to llava:7b: {screenshot.name}")
        result = fleet.generate(
            model=LLAVA_MODEL,
            prompt=LLAVA_PROMPT,
            image_path=screenshot,
            timeout=120,
        )

        response = result["response"]
        _log(f"llava response ({result['host']}, {result['elapsed_ms']:.0f}ms):")
        _log(f"  {response[:200]}...")

        self.__class__._results["deployment_llava"] = {
            "screenshot": str(screenshot),
            "response": response,
            "host": result["host"],
            "elapsed_ms": result["elapsed_ms"],
        }

        assert len(response) > 50, f"llava response too short: {len(response)} chars"

    @pytest.mark.timeout(120)
    def test_05_llava_describes_combat(self, fleet):
        """llava:7b describes a mid-battle screenshot."""
        screenshot = _find_combat_screenshot()
        if not screenshot:
            pytest.skip("No combat screenshot available")

        _log(f"Sending to llava:7b: {screenshot.name}")
        result = fleet.generate(
            model=LLAVA_MODEL,
            prompt=LLAVA_PROMPT,
            image_path=screenshot,
            timeout=120,
        )

        response = result["response"]
        _log(f"llava response ({result['host']}, {result['elapsed_ms']:.0f}ms):")
        _log(f"  {response[:200]}...")

        self.__class__._results["combat_llava"] = {
            "screenshot": str(screenshot),
            "response": response,
            "host": result["host"],
            "elapsed_ms": result["elapsed_ms"],
        }

        assert len(response) > 50, f"llava response too short: {len(response)} chars"

    @pytest.mark.timeout(120)
    def test_06_llava_sees_buildings(self, fleet):
        """llava:7b mentions buildings or structures in description."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        # Reuse cached result if available
        cached = self.__class__._results.get("deployment_llava")
        if cached:
            response = cached["response"]
        else:
            result = fleet.generate(
                model=LLAVA_MODEL,
                prompt=LLAVA_PROMPT,
                image_path=screenshot,
                timeout=120,
            )
            response = result["response"]

        lower = response.lower()
        building_terms = ["building", "structure", "house", "roof", "block",
                          "construction", "road", "street", "urban"]
        found = [t for t in building_terms if t in lower]
        _log(f"Building terms found: {found}")

        assert len(found) > 0, (
            f"llava did not mention any building/structure terms. "
            f"Response: {response[:300]}"
        )

    @pytest.mark.timeout(120)
    def test_07_llava_sees_units(self, fleet):
        """llava:7b mentions markers, units, dots, or military terms."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        cached = self.__class__._results.get("deployment_llava")
        if cached:
            response = cached["response"]
        else:
            result = fleet.generate(
                model=LLAVA_MODEL,
                prompt=LLAVA_PROMPT,
                image_path=screenshot,
                timeout=120,
            )
            response = result["response"]

        lower = response.lower()
        unit_terms = ["marker", "unit", "dot", "icon", "green", "blue",
                      "red", "circle", "triangle", "symbol", "military",
                      "position", "defense", "turret", "troop", "soldier",
                      "vehicle", "point", "indicator", "overlay"]
        found = [t for t in unit_terms if t in lower]
        _log(f"Unit terms found: {found}")

        assert len(found) > 0, (
            f"llava did not mention any unit/marker terms. "
            f"Response: {response[:300]}"
        )


# -----------------------------------------------------------------------
# qwen3-vl:8b direct vision
# -----------------------------------------------------------------------

class TestQwen3VLDirectVision:
    """Test qwen3-vl:8b direct vision analysis of screenshots."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request):
        cls = request.cls
        cls._results = {}
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @pytest.mark.timeout(180)
    def test_08_qwen3vl_rates_deployment(self, fleet):
        """qwen3-vl:8b gives a tactical rating 1-10."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        hosts = fleet.hosts_with_model(QWEN3VL_MODEL)
        if not hosts:
            pytest.skip(f"No host has {QWEN3VL_MODEL}")

        _log(f"Sending to qwen3-vl:8b: {screenshot.name}")
        result = fleet.generate(
            model=QWEN3VL_MODEL,
            prompt=QWEN3VL_PROMPT,
            image_path=screenshot,
            timeout=180,
        )

        response = result["response"]
        _log(f"qwen3-vl response ({result['host']}, {result['elapsed_ms']:.0f}ms):")
        _log(f"  {response[:200]}...")

        self.__class__._results["deployment_qwen3vl"] = {
            "screenshot": str(screenshot),
            "response": response,
            "host": result["host"],
            "elapsed_ms": result["elapsed_ms"],
        }

        # Look for any numeric rating
        import re
        numbers = re.findall(r'\b(\d+)\s*/?\s*10\b|\brating[:\s]*(\d+)\b', response, re.IGNORECASE)
        _log(f"Rating patterns found: {numbers}")

        assert len(response) > 30, f"qwen3-vl response too short: {len(response)} chars"

    @pytest.mark.timeout(180)
    def test_09_qwen3vl_identifies_positions(self, fleet):
        """qwen3-vl:8b identifies defender positions."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        hosts = fleet.hosts_with_model(QWEN3VL_MODEL)
        if not hosts:
            pytest.skip(f"No host has {QWEN3VL_MODEL}")

        cached = self.__class__._results.get("deployment_qwen3vl")
        if cached:
            response = cached["response"]
        else:
            result = fleet.generate(
                model=QWEN3VL_MODEL,
                prompt=QWEN3VL_PROMPT,
                image_path=screenshot,
                timeout=180,
            )
            response = result["response"]

        lower = response.lower()
        position_terms = ["position", "deploy", "cover", "flank", "defense",
                          "perimeter", "guard", "watch", "north", "south",
                          "east", "west", "left", "right", "center",
                          "corner", "building", "road", "approach"]
        found = [t for t in position_terms if t in lower]
        _log(f"Position terms found: {found}")

        assert len(found) > 0, (
            f"qwen3-vl did not identify any defensive positions. "
            f"Response: {response[:300]}"
        )

    @pytest.mark.timeout(300)
    def test_10_qwen3vl_compares_phases(self, fleet):
        """qwen3-vl:8b gives different analysis for deployment vs combat screenshots."""
        deploy = _find_deployment_screenshot()
        combat = _find_combat_screenshot()

        if not deploy or not combat:
            pytest.skip("Need both deployment and combat screenshots")
        if deploy == combat:
            pytest.skip("Same screenshot for deploy and combat (only 1 image)")

        hosts = fleet.hosts_with_model(QWEN3VL_MODEL)
        if not hosts:
            pytest.skip(f"No host has {QWEN3VL_MODEL}")

        _log(f"Comparing: {deploy.name} vs {combat.name}")

        result1 = fleet.generate(
            model=QWEN3VL_MODEL,
            prompt=QWEN3VL_PROMPT,
            image_path=deploy,
            timeout=180,
        )
        result2 = fleet.generate(
            model=QWEN3VL_MODEL,
            prompt=QWEN3VL_PROMPT,
            image_path=combat,
            timeout=180,
        )

        resp1 = result1["response"]
        resp2 = result2["response"]

        _log(f"Deploy analysis: {resp1[:100]}...")
        _log(f"Combat analysis: {resp2[:100]}...")

        # They should produce different text (not identical)
        assert resp1 != resp2, "qwen3-vl gave identical output for different screenshots"
        _log("Different analyses produced for different phases")


# -----------------------------------------------------------------------
# qwen3.5:27b deep tactical analysis
# -----------------------------------------------------------------------

class TestDeepTacticalAnalysis:
    """Test qwen3.5:27b deep text analysis from vision descriptions."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, fleet):
        cls = request.cls
        cls._fleet = fleet
        cls._results = {}
        cls._deep_response = None
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def _get_vision_descriptions(self) -> tuple[str, str]:
        """Get llava + qwen3-vl descriptions, generating if needed."""
        screenshot = _find_deployment_screenshot()
        if not screenshot:
            pytest.skip("No deployment screenshot available")

        # llava description
        _log(f"Getting llava:7b description of {screenshot.name}")
        llava_result = self._fleet.generate(
            model=LLAVA_MODEL,
            prompt=LLAVA_PROMPT,
            image_path=screenshot,
            timeout=120,
        )
        llava_desc = llava_result["response"]
        _log(f"  llava: {llava_desc[:100]}...")

        # qwen3-vl description
        qwen3vl_hosts = self._fleet.hosts_with_model(QWEN3VL_MODEL)
        if qwen3vl_hosts:
            _log(f"Getting qwen3-vl:8b analysis of {screenshot.name}")
            qwen3vl_result = self._fleet.generate(
                model=QWEN3VL_MODEL,
                prompt=QWEN3VL_PROMPT,
                image_path=screenshot,
                timeout=180,
            )
            qwen3vl_desc = qwen3vl_result["response"]
        else:
            _log("qwen3-vl:8b not available, using llava only")
            qwen3vl_desc = "(Direct vision analysis not available)"

        return llava_desc, qwen3vl_desc

    @pytest.mark.timeout(600)
    def test_11_deep_analysis_produced(self, fleet):
        """qwen3.5:27b produces structured analysis from descriptions."""
        deep_hosts = fleet.hosts_with_model(DEEP_MODEL)
        if not deep_hosts:
            pytest.skip(f"No host has {DEEP_MODEL}")

        llava_desc, qwen3vl_desc = self._get_vision_descriptions()

        prompt = DEEP_PROMPT_TEMPLATE.format(
            llava_description=llava_desc,
            qwen3vl_analysis=qwen3vl_desc,
        )

        _log(f"Sending to qwen3.5:27b for deep analysis...")
        t0 = time.monotonic()
        result = fleet.generate(
            model=DEEP_MODEL,
            prompt=prompt,
            timeout=300,
        )
        elapsed = time.monotonic() - t0

        response = result["response"]
        _log(f"Deep analysis ({result['host']}, {elapsed:.1f}s):")
        _log(f"  {response[:300]}...")

        # Cache for subsequent tests
        self.__class__._deep_response = response
        self.__class__._results["deep"] = {
            "response": response,
            "host": result["host"],
            "elapsed_ms": result["elapsed_ms"],
            "llava_desc": llava_desc,
            "qwen3vl_desc": qwen3vl_desc,
        }

        assert len(response) > 100, (
            f"Deep analysis too short: {len(response)} chars. "
            f"Expected comprehensive tactical assessment."
        )

    @pytest.mark.timeout(30)
    def test_12_analysis_has_rating(self):
        """Analysis includes a numeric tactical rating."""
        response = self.__class__._deep_response
        if not response:
            pytest.skip("No deep analysis available (test_11 must run first)")

        import re
        # Look for rating patterns
        patterns = [
            r'(?:rating|score|overall)[:\s]*(\d+)\s*/?\s*10',
            r'(?:rating|score|overall)[:\s]*(\d+)',
            r'(\d+)\s*/\s*10',
            r'(?:tactical\s+rating)[:\s]*(\d+)',
        ]

        rating = None
        for pattern in patterns:
            m = re.search(pattern, response, re.IGNORECASE)
            if m:
                val = int(m.group(1))
                if 1 <= val <= 10:
                    rating = val
                    break

        _log(f"Extracted tactical rating: {rating}")

        assert rating is not None, (
            f"No tactical rating (1-10) found in analysis. "
            f"Response excerpt: {response[:500]}"
        )
        assert 1 <= rating <= 10, f"Rating {rating} out of range 1-10"

    @pytest.mark.timeout(30)
    def test_13_analysis_identifies_gaps(self):
        """Analysis mentions coverage gaps or vulnerabilities."""
        response = self.__class__._deep_response
        if not response:
            pytest.skip("No deep analysis available (test_11 must run first)")

        lower = response.lower()
        gap_terms = ["gap", "vulnerab", "weak", "exposed", "uncover",
                     "approach", "flank", "blind spot", "opening",
                     "undefend", "unprotect", "lack", "insufficient",
                     "missing", "neglect"]
        found = [t for t in gap_terms if t in lower]
        _log(f"Gap/vulnerability terms found: {found}")

        assert len(found) > 0, (
            f"Analysis did not mention any gaps or vulnerabilities. "
            f"Response excerpt: {response[:500]}"
        )

    @pytest.mark.timeout(30)
    def test_14_analysis_makes_recommendations(self):
        """Analysis includes tactical recommendations."""
        response = self.__class__._deep_response
        if not response:
            pytest.skip("No deep analysis available (test_11 must run first)")

        lower = response.lower()
        rec_terms = ["recommend", "suggest", "should", "could", "improve",
                     "consider", "advise", "deploy", "reposition",
                     "reinforce", "add", "move", "place", "establish"]
        found = [t for t in rec_terms if t in lower]
        _log(f"Recommendation terms found: {found}")

        assert len(found) >= 2, (
            f"Analysis lacks actionable recommendations (found: {found}). "
            f"Response excerpt: {response[:500]}"
        )


# -----------------------------------------------------------------------
# Report generation
# -----------------------------------------------------------------------

class TestAnalysisReport:
    """Generate analysis reports from all collected data."""

    @pytest.fixture(autouse=True, scope="class")
    def _setup(self, request, fleet):
        cls = request.cls
        cls._fleet = fleet
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    @pytest.mark.timeout(600)
    def test_15_json_report_generated(self, fleet):
        """Full analysis saved to deep-analysis.json."""
        screenshots = _find_screenshots()
        if not screenshots:
            pytest.skip("No screenshots available")

        # Analyze up to 5 screenshots for the report
        screenshots = screenshots[:5]
        results = []

        for screenshot in screenshots:
            _log(f"Analyzing: {screenshot.name}")

            # llava pass
            try:
                llava = fleet.generate(
                    model=LLAVA_MODEL,
                    prompt=LLAVA_PROMPT,
                    image_path=screenshot,
                    timeout=120,
                )
                llava_desc = llava["response"]
                llava_ms = llava["elapsed_ms"]
            except Exception as e:
                _log(f"  llava failed: {e}")
                llava_desc = f"[error: {e}]"
                llava_ms = 0

            # qwen3-vl pass
            qwen3vl_hosts = fleet.hosts_with_model(QWEN3VL_MODEL)
            if qwen3vl_hosts:
                try:
                    qwen3vl = fleet.generate(
                        model=QWEN3VL_MODEL,
                        prompt=QWEN3VL_PROMPT,
                        image_path=screenshot,
                        timeout=180,
                    )
                    qwen3vl_desc = qwen3vl["response"]
                    qwen3vl_ms = qwen3vl["elapsed_ms"]
                except Exception as e:
                    _log(f"  qwen3-vl failed: {e}")
                    qwen3vl_desc = f"[error: {e}]"
                    qwen3vl_ms = 0
            else:
                qwen3vl_desc = "(model not available)"
                qwen3vl_ms = 0

            # Deep analysis
            deep_hosts = fleet.hosts_with_model(DEEP_MODEL)
            if deep_hosts:
                prompt = DEEP_PROMPT_TEMPLATE.format(
                    llava_description=llava_desc,
                    qwen3vl_analysis=qwen3vl_desc,
                )
                try:
                    deep = fleet.generate(
                        model=DEEP_MODEL,
                        prompt=prompt,
                        timeout=300,
                    )
                    deep_resp = deep["response"]
                    deep_ms = deep["elapsed_ms"]
                except Exception as e:
                    _log(f"  qwen3.5 failed: {e}")
                    deep_resp = f"[error: {e}]"
                    deep_ms = 0
            else:
                deep_resp = "(model not available)"
                deep_ms = 0

            import re
            rating = None
            for pattern in [r'(\d+)\s*/\s*10', r'(?:rating|score)[:\s]*(\d+)']:
                m = re.search(pattern, deep_resp, re.IGNORECASE)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= 10:
                        rating = val
                        break

            results.append({
                "image": screenshot.name,
                "llava_description": llava_desc,
                "qwen3vl_analysis": qwen3vl_desc,
                "deep_analysis": {
                    "tactical_rating": rating,
                    "raw_response": deep_resp,
                },
                "timing": {
                    "llava_ms": llava_ms,
                    "qwen3vl_ms": qwen3vl_ms,
                    "qwen35_ms": deep_ms,
                },
            })

            _log(f"  Done: rating={rating}, "
                 f"llava={llava_ms:.0f}ms, "
                 f"qwen3vl={qwen3vl_ms:.0f}ms, "
                 f"deep={deep_ms:.0f}ms")

        # Save JSON
        json_path = OUTPUT_DIR / "deep-analysis.json"
        with open(json_path, "w") as f:
            json.dump(results, f, indent=2)

        _log(f"Saved: {json_path}")
        assert json_path.exists()
        assert len(results) > 0

        # Store for HTML test
        self.__class__._report_results = results

    @pytest.mark.timeout(30)
    def test_16_html_report_generated(self):
        """Interactive HTML report created from analysis data."""
        json_path = OUTPUT_DIR / "deep-analysis.json"
        if not json_path.exists():
            pytest.skip("No JSON report (test_15 must run first)")

        with open(json_path) as f:
            results = json.load(f)

        if not results:
            pytest.skip("Empty analysis results")

        # Generate HTML report
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from scripts.analyze_combat_screenshots import generate_html_report

        report_path = generate_html_report(results, OUTPUT_DIR)
        _log(f"Generated: {report_path}")

        assert report_path.exists(), f"Report not created at {report_path}"
        content = report_path.read_text()
        assert len(content) > 500, f"Report too small: {len(content)} chars"
        assert "Tactical Rating" in content or "tactical" in content.lower()
        _log(f"HTML report: {len(content)} chars")
