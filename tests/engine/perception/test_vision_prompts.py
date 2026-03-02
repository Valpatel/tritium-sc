# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for VisionPromptTemplate and VisionPromptManager.

18 tests covering template management, message building, response parsing,
retry logic escalation, and end-to-end mocked analyze() flow.
"""

from __future__ import annotations

import base64
import json
from dataclasses import field
from unittest.mock import MagicMock, patch

import pytest

from engine.perception.vision_prompts import (
    VisionPromptManager,
    VisionPromptTemplate,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager() -> VisionPromptManager:
    """Fresh VisionPromptManager with default templates loaded."""
    return VisionPromptManager()


@pytest.fixture
def custom_template() -> VisionPromptTemplate:
    """A custom template for registration tests."""
    return VisionPromptTemplate(
        template_id="custom_test",
        system_prompt="You are a test assistant.",
        user_prompt="Analyze this {thing} for {reason}.",
        response_schema={
            "required": ["result"],
            "properties": {
                "result": {"type": "string"},
            },
        },
        temperature=0.5,
        max_tokens=128,
    )


@pytest.fixture
def sample_image_b64() -> str:
    """A tiny 1x1 red PNG encoded as base64."""
    # Minimal valid PNG: 1x1 red pixel
    import struct
    import zlib

    def _make_png() -> bytes:
        sig = b"\x89PNG\r\n\x1a\n"
        # IHDR
        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
        ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
        # IDAT
        raw = zlib.compress(b"\x00\xff\x00\x00")
        idat_crc = zlib.crc32(b"IDAT" + raw) & 0xFFFFFFFF
        idat = struct.pack(">I", len(raw)) + b"IDAT" + raw + struct.pack(">I", idat_crc)
        # IEND
        iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
        iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
        return sig + ihdr + idat + iend

    return base64.b64encode(_make_png()).decode("ascii")


# ---------------------------------------------------------------------------
# Template Management (tests 1-4)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestTemplateManagement:
    """Tests for loading, retrieving, and registering templates."""

    def test_default_templates_loaded(self, manager: VisionPromptManager):
        """VisionPromptManager should have all 6 default templates on init."""
        expected_ids = {
            "scene_description",
            "person_count",
            "threat_assessment",
            "equipment_id",
            "weather_conditions",
            "change_detection",
        }
        for tid in expected_ids:
            tmpl = manager.get_template(tid)
            assert tmpl is not None, f"Missing default template: {tid}"
            assert isinstance(tmpl, VisionPromptTemplate)
            assert tmpl.template_id == tid

    def test_get_template_by_id(self, manager: VisionPromptManager):
        """get_template() returns the correct template for a known id."""
        tmpl = manager.get_template("person_count")
        assert tmpl is not None
        assert tmpl.template_id == "person_count"
        assert "person" in tmpl.system_prompt.lower() or "person" in tmpl.user_prompt.lower() or "people" in tmpl.user_prompt.lower() or "count" in tmpl.user_prompt.lower()

    def test_get_unknown_template(self, manager: VisionPromptManager):
        """get_template() returns None for an unknown template id."""
        assert manager.get_template("nonexistent_template_xyz") is None

    def test_register_custom_template(
        self, manager: VisionPromptManager, custom_template: VisionPromptTemplate
    ):
        """register_template() adds a template retrievable by id."""
        manager.register_template(custom_template)
        retrieved = manager.get_template("custom_test")
        assert retrieved is not None
        assert retrieved.template_id == "custom_test"
        assert retrieved.system_prompt == "You are a test assistant."


# ---------------------------------------------------------------------------
# Message Building (tests 5-8)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestMessageBuilding:
    """Tests for build_messages() — constructing Ollama chat messages."""

    def test_build_messages_basic(self, manager: VisionPromptManager):
        """build_messages() produces a list with system + user messages."""
        msgs = manager.build_messages("scene_description", "llava:7b", images=[])
        assert isinstance(msgs, list)
        assert len(msgs) >= 2
        # First message should be system
        assert msgs[0]["role"] == "system"
        # Last message should be user
        assert msgs[-1]["role"] == "user"

    def test_build_messages_with_images(
        self, manager: VisionPromptManager, sample_image_b64: str
    ):
        """build_messages() includes image data in the user message."""
        msgs = manager.build_messages(
            "scene_description", "llava:7b", images=[sample_image_b64]
        )
        user_msg = msgs[-1]
        assert "images" in user_msg
        assert len(user_msg["images"]) == 1
        assert user_msg["images"][0] == sample_image_b64

    def test_build_messages_with_context(self, manager: VisionPromptManager):
        """build_messages() fills {placeholders} in user_prompt with context."""
        # Register a template with a placeholder
        tmpl = VisionPromptTemplate(
            template_id="ctx_test",
            system_prompt="System.",
            user_prompt="Analyze the {location} area for {target_type} activity.",
            response_schema={"required": ["description"]},
        )
        manager.register_template(tmpl)
        msgs = manager.build_messages(
            "ctx_test",
            "llava:7b",
            images=[],
            context={"location": "backyard", "target_type": "hostile"},
        )
        user_content = msgs[-1]["content"]
        assert "backyard" in user_content
        assert "hostile" in user_content
        assert "{location}" not in user_content
        assert "{target_type}" not in user_content

    def test_build_messages_model_override(self, manager: VisionPromptManager):
        """build_messages() applies model-specific overrides when available."""
        tmpl = VisionPromptTemplate(
            template_id="override_test",
            system_prompt="Default system prompt.",
            user_prompt="Analyze this image.",
            response_schema={"required": ["result"]},
            temperature=0.5,
            model_overrides={
                "llava:7b": {
                    "temperature": 0.2,
                    "system_suffix": " Respond with JSON only, no markdown.",
                },
            },
        )
        manager.register_template(tmpl)
        msgs = manager.build_messages("override_test", "llava:7b", images=[])
        # System prompt should include the model-specific suffix
        sys_content = msgs[0]["content"]
        assert "JSON only" in sys_content


# ---------------------------------------------------------------------------
# Response Parsing (tests 9-13)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestResponseParsing:
    """Tests for parse_response() — extracting structured data from LLM text."""

    def test_parse_valid_json(self, manager: VisionPromptManager):
        """Clean JSON string parses correctly."""
        raw = '{"description": "A quiet suburban street.", "confidence": 0.9}'
        result = manager.parse_response("scene_description", raw)
        assert result is not None
        assert result["description"] == "A quiet suburban street."
        assert result["confidence"] == 0.9

    def test_parse_markdown_wrapped(self, manager: VisionPromptManager):
        """Strips ```json ... ``` wrapping before parsing."""
        raw = '```json\n{"description": "Front yard with trees.", "confidence": 0.8}\n```'
        result = manager.parse_response("scene_description", raw)
        assert result is not None
        assert result["description"] == "Front yard with trees."

    def test_parse_embedded_json(self, manager: VisionPromptManager):
        """Extracts JSON object from surrounding prose text."""
        raw = (
            'Here is my analysis:\n'
            '{"description": "Driveway with two cars.", "confidence": 0.7}\n'
            "I hope this helps!"
        )
        result = manager.parse_response("scene_description", raw)
        assert result is not None
        assert result["description"] == "Driveway with two cars."

    def test_parse_invalid_returns_none(self, manager: VisionPromptManager):
        """Completely invalid text with no JSON returns None."""
        raw = "I cannot analyze this image because reasons. No data available."
        result = manager.parse_response("scene_description", raw)
        assert result is None

    def test_parse_validates_schema(self, manager: VisionPromptManager):
        """Missing required keys from response_schema causes None return."""
        # Register a template requiring specific keys
        tmpl = VisionPromptTemplate(
            template_id="strict_schema",
            system_prompt="System.",
            user_prompt="Analyze.",
            response_schema={
                "required": ["count", "details"],
                "properties": {
                    "count": {"type": "integer"},
                    "details": {"type": "string"},
                },
            },
        )
        manager.register_template(tmpl)
        # JSON is valid but missing "details" key
        raw = '{"count": 3}'
        result = manager.parse_response("strict_schema", raw)
        assert result is None


# ---------------------------------------------------------------------------
# Analyze Pipeline (tests 14-18)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestAnalyzePipeline:
    """Tests for analyze() — full pipeline with mocked Ollama calls."""

    def _mock_fleet(self, host: str = "http://localhost:11434") -> MagicMock:
        """Create a mock fleet that returns a host."""
        fleet = MagicMock()
        mock_host = MagicMock()
        mock_host.base_url = host
        fleet.hosts_with_model.return_value = [mock_host]
        fleet.best_host.return_value = mock_host
        return fleet

    @patch("engine.perception.vision_prompts.ollama_chat")
    def test_analyze_success_mock(
        self, mock_chat: MagicMock, manager: VisionPromptManager
    ):
        """Mocked Ollama returns valid JSON — analyze returns parsed dict."""
        mock_chat.return_value = {
            "message": {
                "content": '{"description": "A residential street.", "confidence": 0.85}'
            }
        }
        fleet = self._mock_fleet()
        result = manager.analyze(
            "scene_description", "llava:7b", images=[], fleet=fleet
        )
        assert result is not None
        assert result["description"] == "A residential street."
        assert result["confidence"] == 0.85
        mock_chat.assert_called_once()

    @patch("engine.perception.vision_prompts.ollama_chat")
    def test_analyze_retry_on_bad_json(
        self, mock_chat: MagicMock, manager: VisionPromptManager
    ):
        """First response is bad JSON, retry succeeds with correction prompt."""
        mock_chat.side_effect = [
            # First call: invalid JSON
            {"message": {"content": "I see a street with some people walking."}},
            # Retry: valid JSON
            {
                "message": {
                    "content": '{"description": "Street with pedestrians.", "confidence": 0.7}'
                }
            },
        ]
        fleet = self._mock_fleet()
        result = manager.analyze(
            "scene_description", "llava:7b", images=[], fleet=fleet
        )
        assert result is not None
        assert result["description"] == "Street with pedestrians."
        assert mock_chat.call_count == 2

    @patch("engine.perception.vision_prompts.ollama_chat")
    def test_analyze_retry_with_schema_only(
        self, mock_chat: MagicMock, manager: VisionPromptManager
    ):
        """Two bad responses, third uses schema-only prompt and succeeds."""
        mock_chat.side_effect = [
            # First: prose
            {"message": {"content": "Nice weather today."}},
            # Second: still prose
            {"message": {"content": "Let me try again: it's sunny."}},
            # Third: valid JSON
            {
                "message": {
                    "content": '{"description": "Sunny day, clear skies.", "confidence": 0.9}'
                }
            },
        ]
        fleet = self._mock_fleet()
        result = manager.analyze(
            "scene_description",
            "llava:7b",
            images=[],
            fleet=fleet,
            max_retries=2,
        )
        assert result is not None
        assert result["description"] == "Sunny day, clear skies."
        assert mock_chat.call_count == 3

    @patch("engine.perception.vision_prompts.ollama_chat")
    def test_analyze_max_retries_returns_none(
        self, mock_chat: MagicMock, manager: VisionPromptManager
    ):
        """All retries fail — analyze returns None."""
        mock_chat.return_value = {
            "message": {"content": "I cannot produce JSON for this image."}
        }
        fleet = self._mock_fleet()
        result = manager.analyze(
            "scene_description",
            "llava:7b",
            images=[],
            fleet=fleet,
            max_retries=2,
        )
        assert result is None
        # 1 initial + 2 retries = 3 calls
        assert mock_chat.call_count == 3

    def test_analyze_no_fleet_returns_none(self, manager: VisionPromptManager):
        """No fleet available — analyze returns None gracefully."""
        result = manager.analyze(
            "scene_description", "llava:7b", images=[], fleet=None
        )
        assert result is None
