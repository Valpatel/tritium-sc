# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for Speaker (Piper TTS) and ObjectThumbnail dataclass.

Tests Speaker availability checks, queue lifecycle, command building,
synthesis, and shutdown — all with mocked subprocess (no actual Piper).
Tests ObjectThumbnail to_dict serialization.
"""
from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from engine.comms.speaker import Speaker, DEFAULT_PIPER_DIR
from app.ai.thumbnails import ObjectThumbnail


# ===========================================================================
# ObjectThumbnail Dataclass
# ===========================================================================

@pytest.mark.unit
class TestObjectThumbnail:
    """ObjectThumbnail — cropped detection thumbnail metadata."""

    def _make_thumbnail(self, **kwargs):
        defaults = dict(
            thumbnail_id="person_20260220100000_abc123",
            target_type="person",
            timestamp=datetime(2026, 2, 20, 10, 0, 0),
            channel=1,
            video_path="/recordings/ch1/2026-02-20/video_001.mp4",
            frame_number=150,
            bbox=(100, 200, 300, 400),
            confidence=0.92,
            thumbnail_path="/cache/thumbnails/person/person_20260220100000_abc123.jpg",
        )
        defaults.update(kwargs)
        return ObjectThumbnail(**defaults)

    def test_basic_fields(self):
        t = self._make_thumbnail()
        assert t.target_type == "person"
        assert t.channel == 1
        assert t.frame_number == 150
        assert t.confidence == pytest.approx(0.92)

    def test_embedding_default_none(self):
        t = self._make_thumbnail()
        assert t.embedding is None

    def test_embedding_with_values(self):
        t = self._make_thumbnail(embedding=[0.1, 0.2, 0.3])
        assert t.embedding == [0.1, 0.2, 0.3]

    def test_to_dict(self):
        t = self._make_thumbnail()
        d = t.to_dict()
        assert d["thumbnail_id"] == "person_20260220100000_abc123"
        assert d["target_type"] == "person"
        assert d["timestamp"] == "2026-02-20T10:00:00"
        assert d["channel"] == 1
        assert d["frame_number"] == 150
        assert d["bbox"] == [100, 200, 300, 400]
        assert d["confidence"] == pytest.approx(0.92)
        assert d["has_embedding"] is False

    def test_to_dict_with_embedding(self):
        t = self._make_thumbnail(embedding=[0.5] * 512)
        d = t.to_dict()
        assert d["has_embedding"] is True

    def test_to_dict_vehicle(self):
        t = self._make_thumbnail(
            thumbnail_id="car_20260220_xyz",
            target_type="car",
        )
        d = t.to_dict()
        assert d["target_type"] == "car"

    def test_bbox_is_list_in_dict(self):
        """bbox should be a list (not tuple) in to_dict output."""
        t = self._make_thumbnail()
        d = t.to_dict()
        assert isinstance(d["bbox"], list)


# ===========================================================================
# Speaker — Availability
# ===========================================================================

@pytest.mark.unit
class TestSpeakerAvailability:
    """Speaker.available checks for Piper binary and voice model."""

    def test_available_when_both_exist(self):
        with tempfile.TemporaryDirectory() as td:
            piper_bin = Path(td) / "piper"
            voice_model = Path(td) / "voice.onnx"
            piper_bin.write_bytes(b"\x00")
            voice_model.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = str(piper_bin)
                s.voice_model = str(voice_model)
                assert s.available is True

    def test_not_available_no_binary(self):
        with tempfile.TemporaryDirectory() as td:
            voice_model = Path(td) / "voice.onnx"
            voice_model.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = "/nonexistent/piper"
                s.voice_model = str(voice_model)
                assert s.available is False

    def test_not_available_no_model(self):
        with tempfile.TemporaryDirectory() as td:
            piper_bin = Path(td) / "piper"
            piper_bin.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = str(piper_bin)
                s.voice_model = "/nonexistent/voice.onnx"
                assert s.available is False

    def test_not_available_neither_exist(self):
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            s = Speaker.__new__(Speaker)
            s.piper_bin = "/nonexistent/piper"
            s.voice_model = "/nonexistent/voice.onnx"
            assert s.available is False


# ===========================================================================
# Speaker — Command Building
# ===========================================================================

@pytest.mark.unit
class TestSpeakerBuildCmd:
    """Speaker._build_play_cmd generates correct pw-play arguments."""

    def _make_speaker(self, sample_rate=22050):
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            s = Speaker.__new__(Speaker)
            s.sample_rate = sample_rate
            return s

    def test_default_rate(self):
        s = self._make_speaker(22050)
        cmd = s._build_play_cmd()
        assert cmd == ["pw-play", "--format=s16", "--rate=22050", "--channels=1", "-"]

    def test_custom_rate(self):
        s = self._make_speaker(22050)
        cmd = s._build_play_cmd(rate=16000)
        assert cmd == ["pw-play", "--format=s16", "--rate=16000", "--channels=1", "-"]

    def test_override_rate(self):
        s = self._make_speaker(44100)
        cmd = s._build_play_cmd()
        assert "--rate=44100" in cmd

    def test_stdin_marker(self):
        s = self._make_speaker()
        cmd = s._build_play_cmd()
        assert cmd[-1] == "-"


# ===========================================================================
# Speaker — Playback Device
# ===========================================================================

@pytest.mark.unit
class TestSpeakerPlaybackDevice:
    """Speaker.playback_device returns human-readable name."""

    def test_playback_device(self):
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            s = Speaker.__new__(Speaker)
            assert s.playback_device == "pw-play (default sink)"


# ===========================================================================
# Speaker — Queue Lifecycle
# ===========================================================================

@pytest.mark.unit
class TestSpeakerLifecycle:
    """Speaker speak/shutdown queue behavior."""

    def test_speak_enqueues(self):
        """speak() adds text to internal queue without blocking."""
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            import queue
            s = Speaker.__new__(Speaker)
            s._queue = queue.Queue()
            s.speak("Hello")
            s.speak("World")
            assert s._queue.qsize() == 2
            assert s._queue.get() == "Hello"
            assert s._queue.get() == "World"

    def test_shutdown_sends_sentinel(self):
        """shutdown() sends None sentinel to stop worker."""
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            import queue, threading
            s = Speaker.__new__(Speaker)
            s._queue = queue.Queue()
            s._thread = MagicMock()
            s._thread.join = MagicMock()
            s.shutdown()
            assert s._queue.get() is None
            s._thread.join.assert_called_once_with(timeout=5)

    def test_synthesize_raw_unavailable(self):
        """synthesize_raw returns None when Piper not available."""
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            s = Speaker.__new__(Speaker)
            s.piper_bin = "/nonexistent"
            s.voice_model = "/nonexistent"
            result = s.synthesize_raw("Hello")
            assert result is None

    def test_synthesize_raw_success(self):
        """synthesize_raw returns PCM bytes on success."""
        with tempfile.TemporaryDirectory() as td:
            piper_bin = Path(td) / "piper"
            voice_model = Path(td) / "voice.onnx"
            piper_bin.write_bytes(b"\x00")
            voice_model.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = str(piper_bin)
                s.voice_model = str(voice_model)
                fake_pcm = b"\x00\x01" * 100
                mock_result = MagicMock()
                mock_result.returncode = 0
                mock_result.stdout = fake_pcm
                with patch("engine.comms.speaker.subprocess.run", return_value=mock_result):
                    result = s.synthesize_raw("Hello")
                    assert result == fake_pcm

    def test_synthesize_raw_failure(self):
        """synthesize_raw returns None on non-zero exit."""
        with tempfile.TemporaryDirectory() as td:
            piper_bin = Path(td) / "piper"
            voice_model = Path(td) / "voice.onnx"
            piper_bin.write_bytes(b"\x00")
            voice_model.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = str(piper_bin)
                s.voice_model = str(voice_model)
                mock_result = MagicMock()
                mock_result.returncode = 1
                mock_result.stdout = b""
                with patch("engine.comms.speaker.subprocess.run", return_value=mock_result):
                    result = s.synthesize_raw("Hello")
                    assert result is None

    def test_synthesize_raw_exception(self):
        """synthesize_raw returns None on subprocess exception."""
        with tempfile.TemporaryDirectory() as td:
            piper_bin = Path(td) / "piper"
            voice_model = Path(td) / "voice.onnx"
            piper_bin.write_bytes(b"\x00")
            voice_model.write_bytes(b"\x00")
            with patch.object(Speaker, '__init__', lambda self, **kw: None):
                s = Speaker.__new__(Speaker)
                s.piper_bin = str(piper_bin)
                s.voice_model = str(voice_model)
                with patch("engine.comms.speaker.subprocess.run", side_effect=OSError("No such file")):
                    result = s.synthesize_raw("Hello")
                    assert result is None

    def test_synthesize_and_play_unavailable(self, capsys):
        """_synthesize_and_play prints message when unavailable."""
        with patch.object(Speaker, '__init__', lambda self, **kw: None):
            s = Speaker.__new__(Speaker)
            s.piper_bin = "/nonexistent"
            s.voice_model = "/nonexistent"
            s._synthesize_and_play("Hello")
            captured = capsys.readouterr()
            assert "[TTS unavailable]" in captured.out
            assert "Hello" in captured.out

    def test_init_paths_resolved(self):
        """Speaker.__init__ resolves paths to absolute."""
        with patch("threading.Thread") as mock_thread:
            mock_instance = MagicMock()
            mock_thread.return_value = mock_instance
            s = Speaker(
                piper_bin="./relative/piper",
                voice_model="./relative/voice.onnx",
            )
            assert os.path.isabs(s.piper_bin)
            assert os.path.isabs(s.voice_model)
