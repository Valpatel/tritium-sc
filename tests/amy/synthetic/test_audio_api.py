"""Tests for the audio effects API endpoint.

Validates:
    - GET /api/audio/effects lists all effects
    - GET /api/audio/effects/{name} streams WAV bytes
    - GET /api/audio/effects/{name}/metadata returns metadata
    - 404 for unknown effect names
    - WAV responses have correct content-type
"""
import pytest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _make_app():
    """Create a minimal FastAPI app with the audio router for testing."""
    from fastapi import FastAPI
    from app.routers.audio import router
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.mark.unit
class TestAudioEffectsListEndpoint:
    """GET /api/audio/effects — list all effects."""

    def test_returns_list(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_each_effect_has_required_fields(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects")
        data = resp.json()
        for effect in data:
            assert "name" in effect
            assert "category" in effect
            assert "duration" in effect

    def test_known_effects_present(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects")
        names = {e["name"] for e in resp.json()}
        expected = {"nerf_shot", "explosion", "wave_start", "victory_fanfare",
                    "defeat_sting", "alert_tone", "dispatch_ack", "impact_hit",
                    "drone_buzz", "turret_rotate", "ambient_wind"}
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_categories_are_valid(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects")
        valid_cats = {"combat", "ambient", "alerts", "game"}
        for effect in resp.json():
            assert effect["category"] in valid_cats, (
                f"{effect['name']} has invalid category: {effect['category']}"
            )

    def test_filter_by_category(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects?category=combat")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0
        for effect in data:
            assert effect["category"] == "combat"


@pytest.mark.unit
class TestAudioEffectStreamEndpoint:
    """GET /api/audio/effects/{name} — stream WAV bytes."""

    def test_returns_wav(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/nerf_shot")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        # WAV files start with RIFF header
        assert resp.content[:4] == b"RIFF"

    def test_wav_has_wave_magic(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/explosion")
        assert resp.content[8:12] == b"WAVE"

    def test_unknown_effect_404(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/nonexistent_sound")
        assert resp.status_code == 404

    def test_content_length_reasonable(self):
        """WAV for nerf_shot (0.3s, 16kHz, 16bit) should be ~9.6KB + header."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/nerf_shot")
        size = len(resp.content)
        # 0.3s * 16000 samples/s * 2 bytes/sample + 44 byte header = 9644
        assert 5000 < size < 20000, f"Unexpected WAV size: {size}"


@pytest.mark.unit
class TestAudioEffectMetadataEndpoint:
    """GET /api/audio/effects/{name}/metadata — effect info."""

    def test_returns_metadata(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/nerf_shot/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "nerf_shot"
        assert data["category"] == "combat"
        assert data["duration"] == pytest.approx(0.3)

    def test_unknown_effect_404(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/nope/metadata")
        assert resp.status_code == 404

    def test_elimination_streak_metadata(self):
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects/elimination_streak_godlike/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["category"] == "game"
        assert data["duration"] > 0


@pytest.mark.unit
class TestAudioEffectWavValidity:
    """Verify generated WAV files are structurally valid."""

    def test_all_effects_generate_valid_wav(self):
        """Every effect in the catalog should produce valid WAV bytes."""
        app = _make_app()
        client = TestClient(app)
        resp = client.get("/api/audio/effects")
        effects = resp.json()
        for effect in effects:
            name = effect["name"]
            wav_resp = client.get(f"/api/audio/effects/{name}")
            assert wav_resp.status_code == 200, f"Failed for {name}"
            content = wav_resp.content
            assert content[:4] == b"RIFF", f"{name}: missing RIFF header"
            assert content[8:12] == b"WAVE", f"{name}: missing WAVE magic"
            assert len(content) > 44, f"{name}: WAV too small ({len(content)} bytes)"
