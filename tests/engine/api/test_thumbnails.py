# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Unit tests for app.ai.thumbnails — thumbnail extraction, disk caching,
category routing, padding/clipping, deduplication, and embedding generation.

Mocks cv2 and the CLIP embedding generator to avoid heavy dependencies.
Uses tempfile.TemporaryDirectory for cache hit/miss verification.
"""
from __future__ import annotations

import hashlib
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Lightweight Detection stand-in (mirrors app.ai.detector.Detection)
# ---------------------------------------------------------------------------

@dataclass
class _Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    area: int


def _make_detection(
    class_name: str = "person",
    confidence: float = 0.9,
    bbox: tuple[int, int, int, int] = (100, 100, 200, 200),
) -> _Detection:
    x1, y1, x2, y2 = bbox
    return _Detection(
        class_id=0,
        class_name=class_name,
        confidence=confidence,
        bbox=bbox,
        center=((x1 + x2) // 2, (y1 + y2) // 2),
        area=(x2 - x1) * (y2 - y1),
    )


# ---------------------------------------------------------------------------
# ObjectThumbnail dataclass
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestObjectThumbnail:
    """Verify ObjectThumbnail serialisation."""

    def test_to_dict_keys(self):
        from app.ai.thumbnails import ObjectThumbnail

        ts = datetime(2026, 2, 24, 12, 0, 0)
        ot = ObjectThumbnail(
            thumbnail_id="person_20260224120000_abc",
            target_type="person",
            timestamp=ts,
            channel=1,
            video_path="/tmp/vid.mp4",
            frame_number=42,
            bbox=(10, 20, 110, 120),
            confidence=0.95,
            thumbnail_path="/tmp/thumbs/person/abc.jpg",
            embedding=None,
        )
        d = ot.to_dict()
        assert d["thumbnail_id"] == "person_20260224120000_abc"
        assert d["target_type"] == "person"
        assert d["timestamp"] == "2026-02-24T12:00:00"
        assert d["channel"] == 1
        assert d["frame_number"] == 42
        assert d["bbox"] == [10, 20, 110, 120]
        assert d["confidence"] == 0.95
        assert d["has_embedding"] is False

    def test_to_dict_with_embedding(self):
        from app.ai.thumbnails import ObjectThumbnail

        ts = datetime(2026, 1, 1)
        ot = ObjectThumbnail(
            thumbnail_id="car_id",
            target_type="car",
            timestamp=ts,
            channel=2,
            video_path="/v.mp4",
            frame_number=0,
            bbox=(0, 0, 50, 50),
            confidence=0.8,
            thumbnail_path="/p.jpg",
            embedding=[0.1, 0.2, 0.3],
        )
        assert ot.to_dict()["has_embedding"] is True


# ---------------------------------------------------------------------------
# ThumbnailExtractor — directory creation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractorInit:
    """Constructor must create category subdirectories."""

    def test_creates_subdirectories(self):
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ThumbnailExtractor(output_dir=Path(tmp))
            assert (Path(tmp) / "person").is_dir()
            assert (Path(tmp) / "vehicle").is_dir()
            assert (Path(tmp) / "animal").is_dir()

    def test_custom_params_stored(self):
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=80, padding=0.25)
            assert ext.min_size == 80
            assert ext.padding == 0.25


# ---------------------------------------------------------------------------
# extract_from_frame — core logic
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractFromFrame:
    """Tests for single-frame thumbnail extraction."""

    def _make_extractor(self, tmp: str, **kw):
        from app.ai.thumbnails import ThumbnailExtractor
        return ThumbnailExtractor(output_dir=Path(tmp), **kw)

    def _frame(self, w: int = 640, h: int = 480) -> np.ndarray:
        """Create a random BGR frame."""
        return np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)

    # -- category routing --------------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_person_goes_to_person_dir(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            frame = self._frame()
            ts = datetime(2026, 2, 24, 8, 0, 0)

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, ts)

            assert len(results) == 1
            assert results[0].target_type == "person"
            assert "/person/" in results[0].thumbnail_path

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_vehicle_classes_route_to_vehicle_dir(self, _emb, mock_cv2):
        for cls in ("car", "truck", "bus", "motorcycle", "bicycle"):
            with tempfile.TemporaryDirectory() as tmp:
                ext = self._make_extractor(tmp, min_size=10)
                det = _make_detection(cls, bbox=(10, 10, 100, 100))
                frame = self._frame()
                ts = datetime(2026, 2, 24)

                results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, ts)

                assert len(results) == 1, f"{cls} should produce 1 thumbnail"
                assert "/vehicle/" in results[0].thumbnail_path, f"{cls} -> vehicle dir"

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_animal_classes_route_to_animal_dir(self, _emb, mock_cv2):
        for cls in ("dog", "cat", "bird"):
            with tempfile.TemporaryDirectory() as tmp:
                ext = self._make_extractor(tmp, min_size=10)
                det = _make_detection(cls, bbox=(10, 10, 100, 100))
                frame = self._frame()
                ts = datetime(2026, 2, 24)

                results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, ts)

                assert len(results) == 1, f"{cls} should produce 1 thumbnail"
                assert "/animal/" in results[0].thumbnail_path, f"{cls} -> animal dir"

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_unknown_class_is_skipped(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("laptop", bbox=(10, 10, 100, 100))
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            assert results == []

    # -- size filtering ----------------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_small_detection_filtered_by_min_size(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=50)
            # 30x30 box is below min_size=50
            det = _make_detection("person", bbox=(100, 100, 130, 130))
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())
            assert results == []

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_width_below_min_size_filtered(self, _emb, mock_cv2):
        """Width < min_size even if height is fine."""
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=50)
            det = _make_detection("person", bbox=(100, 100, 130, 200))  # 30w x 100h
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())
            assert results == []

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_exactly_min_size_passes(self, _emb, mock_cv2):
        """Object exactly at min_size should NOT be filtered."""
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=50)
            det = _make_detection("person", bbox=(100, 100, 150, 150))  # 50x50
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())
            assert len(results) == 1

    # -- padding & clamping ------------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_padding_expands_bbox(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10, padding=0.5)
            det = _make_detection("person", bbox=(100, 100, 200, 200))
            frame = self._frame(640, 480)

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            # Padding: 100*0.5=50 each side -> x1=50, y1=50, x2=250, y2=250
            assert len(results) == 1
            x1, y1, x2, y2 = results[0].bbox
            assert x1 == 50
            assert y1 == 50
            assert x2 == 250
            assert y2 == 250

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_padding_clamped_to_frame_bounds(self, _emb, mock_cv2):
        """Padding near edges must be clamped to 0 / frame dimensions."""
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10, padding=0.5)
            # Near top-left corner: padding would push negative
            det = _make_detection("person", bbox=(5, 5, 105, 105))
            frame = self._frame(200, 200)

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            assert len(results) == 1
            x1, y1, x2, y2 = results[0].bbox
            assert x1 == 0  # clamped
            assert y1 == 0  # clamped
            assert x2 <= 200
            assert y2 <= 200

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_padding_clamped_to_frame_bottom_right(self, _emb, mock_cv2):
        """Padding near bottom-right edge must not exceed frame dimensions."""
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10, padding=0.5)
            # Near bottom-right corner
            det = _make_detection("person", bbox=(150, 350, 250, 470))
            frame = self._frame(300, 480)

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            assert len(results) == 1
            x1, y1, x2, y2 = results[0].bbox
            assert x2 <= 300  # clamped to frame width
            assert y2 <= 480  # clamped to frame height

    # -- thumbnail ID generation -------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_thumbnail_id_contains_class_and_timestamp(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("car", bbox=(10, 10, 100, 100))
            ts = datetime(2026, 3, 15, 14, 30, 0)
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 5, ts)

            tid = results[0].thumbnail_id
            assert tid.startswith("car_20260315143000_")
            # Should have a 12-char hex hash suffix
            hash_part = tid.split("_", 2)[2]
            assert len(hash_part) == 12
            int(hash_part, 16)  # must be valid hex

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_different_content_gives_different_ids(self, _emb, mock_cv2):
        """Two different frames with same detection bbox give different IDs."""
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            ts = datetime(2026, 1, 1)

            frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
            frame2 = np.ones((480, 640, 3), dtype=np.uint8) * 255

            r1 = ext.extract_from_frame(frame1, [det], 1, "/v.mp4", 0, ts)
            r2 = ext.extract_from_frame(frame2, [det], 1, "/v.mp4", 0, ts)

            assert r1[0].thumbnail_id != r2[0].thumbnail_id

    # -- cv2.imwrite call --------------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_imwrite_called_with_correct_path(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("dog", bbox=(10, 10, 100, 100))
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            mock_cv2.imwrite.assert_called_once()
            written_path = mock_cv2.imwrite.call_args[0][0]
            assert "/animal/" in written_path
            assert written_path.endswith(".jpg")

    # -- multiple detections -----------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_multiple_detections_in_one_frame(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            dets = [
                _make_detection("person", bbox=(10, 10, 100, 100)),
                _make_detection("car", confidence=0.8, bbox=(200, 200, 400, 400)),
                _make_detection("laptop", bbox=(50, 50, 80, 80)),  # unknown => skip
            ]
            frame = self._frame()

            results = ext.extract_from_frame(frame, dets, 1, "/v.mp4", 0, datetime.now())

            assert len(results) == 2
            types = {r.target_type for r in results}
            assert types == {"person", "car"}

    # -- metadata fields ---------------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_metadata_fields_populated(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            det = _make_detection("person", confidence=0.85, bbox=(10, 10, 100, 100))
            ts = datetime(2026, 6, 1, 9, 30, 0)

            results = ext.extract_from_frame(frame=self._frame(), detections=[det],
                                             channel=5, video_path="/cam/vid.mp4",
                                             frame_number=99, timestamp=ts)

            r = results[0]
            assert r.channel == 5
            assert r.video_path == "/cam/vid.mp4"
            assert r.frame_number == 99
            assert r.timestamp == ts
            assert r.confidence == 0.85

    # -- empty detections list ---------------------------------------------

    @patch("app.ai.thumbnails.cv2")
    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_empty_detections_returns_empty(self, _emb, mock_cv2):
        with tempfile.TemporaryDirectory() as tmp:
            ext = self._make_extractor(tmp, min_size=10)
            results = ext.extract_from_frame(self._frame(), [], 1, "/v.mp4", 0, datetime.now())
            assert results == []
            mock_cv2.imwrite.assert_not_called()


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestEmbeddings:
    """Embedding generator integration in extract_from_frame."""

    def _frame(self) -> np.ndarray:
        return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    @patch("app.ai.thumbnails.cv2")
    def test_person_gets_embedding(self, mock_cv2):
        """Person detections always attempt embedding generation."""
        mock_gen = MagicMock()
        mock_gen.embed_image.return_value = [0.1, 0.2, 0.3]

        with patch("app.ai.thumbnails.get_embedding_generator", return_value=mock_gen):
            from app.ai.thumbnails import ThumbnailExtractor
            with tempfile.TemporaryDirectory() as tmp:
                ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
                det = _make_detection("person", confidence=0.5, bbox=(10, 10, 100, 100))
                results = ext.extract_from_frame(self._frame(), [det], 1, "/v.mp4", 0, datetime.now())

                assert results[0].embedding == [0.1, 0.2, 0.3]
                mock_gen.embed_image.assert_called_once()

    @patch("app.ai.thumbnails.cv2")
    def test_high_confidence_vehicle_gets_embedding(self, mock_cv2):
        """Vehicles with confidence > 0.7 get embeddings."""
        mock_gen = MagicMock()
        mock_gen.embed_image.return_value = [0.5]

        with patch("app.ai.thumbnails.get_embedding_generator", return_value=mock_gen):
            from app.ai.thumbnails import ThumbnailExtractor
            with tempfile.TemporaryDirectory() as tmp:
                ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
                det = _make_detection("car", confidence=0.85, bbox=(10, 10, 100, 100))
                results = ext.extract_from_frame(self._frame(), [det], 1, "/v.mp4", 0, datetime.now())

                assert results[0].embedding == [0.5]

    @patch("app.ai.thumbnails.cv2")
    def test_low_confidence_animal_no_embedding(self, mock_cv2):
        """Low-confidence non-person detection skips embedding."""
        mock_gen = MagicMock()

        with patch("app.ai.thumbnails.get_embedding_generator", return_value=mock_gen):
            from app.ai.thumbnails import ThumbnailExtractor
            with tempfile.TemporaryDirectory() as tmp:
                ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
                det = _make_detection("dog", confidence=0.6, bbox=(10, 10, 100, 100))
                results = ext.extract_from_frame(self._frame(), [det], 1, "/v.mp4", 0, datetime.now())

                assert results[0].embedding is None
                mock_gen.embed_image.assert_not_called()

    @patch("app.ai.thumbnails.cv2")
    def test_no_generator_available(self, mock_cv2):
        """When get_embedding_generator returns None, embedding is None."""
        with patch("app.ai.thumbnails.get_embedding_generator", return_value=None):
            from app.ai.thumbnails import ThumbnailExtractor
            with tempfile.TemporaryDirectory() as tmp:
                ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
                det = _make_detection("person", confidence=0.95, bbox=(10, 10, 100, 100))
                results = ext.extract_from_frame(self._frame(), [det], 1, "/v.mp4", 0, datetime.now())

                assert results[0].embedding is None

    @patch("app.ai.thumbnails.cv2")
    def test_embedding_failure_does_not_crash(self, mock_cv2):
        """If embed_image raises, the thumbnail is still returned with None embedding."""
        mock_gen = MagicMock()
        mock_gen.embed_image.side_effect = RuntimeError("GPU OOM")

        with patch("app.ai.thumbnails.get_embedding_generator", return_value=mock_gen):
            from app.ai.thumbnails import ThumbnailExtractor
            with tempfile.TemporaryDirectory() as tmp:
                ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
                det = _make_detection("person", bbox=(10, 10, 100, 100))
                results = ext.extract_from_frame(self._frame(), [det], 1, "/v.mp4", 0, datetime.now())

                assert len(results) == 1
                assert results[0].embedding is None


# ---------------------------------------------------------------------------
# get_embedding_generator singleton
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestGetEmbeddingGenerator:
    """Singleton logic for the embedding generator."""

    def test_returns_none_when_clip_unavailable(self):
        import app.ai.thumbnails as mod
        original = mod._embedding_generator
        try:
            mod._embedding_generator = None  # reset
            with patch.dict("sys.modules", {"app.ai.embeddings": None}):
                result = mod.get_embedding_generator()
                # Should have set _embedding_generator to False and returned None
                assert result is None
        finally:
            mod._embedding_generator = original

    def test_returns_generator_when_available(self):
        import app.ai.thumbnails as mod
        original = mod._embedding_generator
        try:
            mod._embedding_generator = None  # reset

            mock_gen = MagicMock()
            mock_module = MagicMock()
            mock_module.EmbeddingGenerator.return_value = mock_gen

            with patch.dict("sys.modules", {"app.ai.embeddings": mock_module}):
                result = mod.get_embedding_generator()
                assert result is mock_gen
        finally:
            mod._embedding_generator = original

    def test_caches_failed_result(self):
        """After failure, repeated calls don't retry."""
        import app.ai.thumbnails as mod
        original = mod._embedding_generator
        try:
            mod._embedding_generator = False  # already failed
            result = mod.get_embedding_generator()
            assert result is None
        finally:
            mod._embedding_generator = original

    def test_caches_success_result(self):
        """After success, repeated calls return cached instance."""
        import app.ai.thumbnails as mod
        original = mod._embedding_generator
        try:
            mock_gen = MagicMock()
            mod._embedding_generator = mock_gen
            result = mod.get_embedding_generator()
            assert result is mock_gen
        finally:
            mod._embedding_generator = original


# ---------------------------------------------------------------------------
# extract_from_video — VideoCapture mocking
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestExtractFromVideo:
    """Tests for video-based thumbnail extraction with deduplication."""

    def _frame(self, w: int = 640, h: int = 480) -> np.ndarray:
        return np.random.randint(0, 255, (h, w, 3), dtype=np.uint8)

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_empty_detections_returns_empty(self, mock_cv2, _emb):
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            result = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
            )
            assert result == []
            mock_cv2.VideoCapture.assert_not_called()

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_single_frame_extraction(self, mock_cv2, _emb):
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={100: [det]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
            )

            assert len(results) == 1
            mock_cap.set.assert_called_with(mock_cv2.CAP_PROP_POS_FRAMES, 100)
            mock_cap.release.assert_called_once()

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_failed_frame_read_skipped(self, mock_cv2, _emb):
        from app.ai.thumbnails import ThumbnailExtractor

        mock_cap = MagicMock()
        mock_cap.read.return_value = (False, None)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={50: [det]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
            )

            assert results == []
            mock_cap.release.assert_called_once()

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_deduplication_by_position(self, mock_cv2, _emb):
        """Same object at similar position within sample_interval is deduplicated."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            # Same detection at frames 10 and 15 (interval=30 => dedup)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={10: [det], 15: [det]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
                sample_interval=30,
            )

            # Only first extraction should pass (15 - 10 = 5 < 30)
            assert len(results) == 1

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_dedup_allows_after_interval(self, mock_cv2, _emb):
        """Same object re-extracted once sample_interval has elapsed."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={10: [det], 50: [det]},  # 50-10=40 >= 30
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
                sample_interval=30,
            )

            assert len(results) == 2

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_different_objects_not_deduped(self, mock_cv2, _emb):
        """Different classes at nearby frames are extracted independently."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det_person = _make_detection("person", bbox=(10, 10, 100, 100))
            det_car = _make_detection("car", bbox=(10, 10, 100, 100))

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={10: [det_person, det_car]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
            )

            assert len(results) == 2

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_frames_processed_in_order(self, mock_cv2, _emb):
        """Frame numbers must be processed in sorted order."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={200: [det], 50: [det], 100: [det]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
                sample_interval=1,  # allow all
            )

            # Check that cap.set was called in ascending frame order
            set_calls = [c for c in mock_cap.set.call_args_list]
            frame_nums = [c[0][1] for c in set_calls]
            assert frame_nums == [50, 100, 200]

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_timestamp_computed_from_fps(self, mock_cv2, _emb):
        """Timestamp should be base_timestamp + frame_number / fps."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            base = datetime(2026, 1, 1, 12, 0, 0)

            results = ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={300: [det]},
                channel=1,
                base_timestamp=base,
                fps=30.0,
                sample_interval=1,
            )

            expected_ts = base + timedelta(seconds=300 / 30.0)
            assert results[0].timestamp == expected_ts

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    @patch("app.ai.thumbnails.cv2")
    def test_video_capture_released(self, mock_cv2, _emb):
        """VideoCapture is always released, even with detections."""
        from app.ai.thumbnails import ThumbnailExtractor

        frame = self._frame()
        mock_cap = MagicMock()
        mock_cap.read.return_value = (True, frame)
        mock_cv2.VideoCapture.return_value = mock_cap

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))

            ext.extract_from_video(
                video_path=Path("/fake/video.mp4"),
                detections_by_frame={0: [det]},
                channel=1,
                base_timestamp=datetime(2026, 1, 1),
                fps=30.0,
            )

            mock_cap.release.assert_called_once()


# ---------------------------------------------------------------------------
# Disk caching — actual file write verification
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestDiskCaching:
    """Verify thumbnails are written to and discoverable on disk."""

    def _frame(self) -> np.ndarray:
        return np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_thumbnail_file_written_to_disk(self, _emb):
        """With real cv2 (not mocked), the JPEG file must exist on disk."""
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            frame = self._frame()

            results = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, datetime.now())

            assert len(results) == 1
            path = Path(results[0].thumbnail_path)
            assert path.exists(), f"Thumbnail file should exist at {path}"
            assert path.stat().st_size > 0, "Thumbnail file should not be empty"

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_cache_hit_same_content_gives_same_path(self, _emb):
        """Extracting the exact same frame+detection should produce the same thumbnail_id."""
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            ts = datetime(2026, 1, 1, 0, 0, 0)

            r1 = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, ts)
            r2 = ext.extract_from_frame(frame, [det], 1, "/v.mp4", 0, ts)

            assert r1[0].thumbnail_id == r2[0].thumbnail_id, "Same content = same ID"

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_cache_miss_different_frame_content(self, _emb):
        """Different frame content should produce different thumbnail_ids."""
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            det = _make_detection("person", bbox=(10, 10, 100, 100))
            ts = datetime(2026, 1, 1, 0, 0, 0)

            frame1 = np.zeros((480, 640, 3), dtype=np.uint8)
            frame2 = np.ones((480, 640, 3), dtype=np.uint8) * 128

            r1 = ext.extract_from_frame(frame1, [det], 1, "/v.mp4", 0, ts)
            r2 = ext.extract_from_frame(frame2, [det], 1, "/v.mp4", 0, ts)

            assert r1[0].thumbnail_id != r2[0].thumbnail_id

    @patch("app.ai.thumbnails.get_embedding_generator", return_value=None)
    def test_multiple_categories_on_disk(self, _emb):
        """Person and vehicle thumbnails end up in separate directories."""
        from app.ai.thumbnails import ThumbnailExtractor

        with tempfile.TemporaryDirectory() as tmp:
            ext = ThumbnailExtractor(output_dir=Path(tmp), min_size=10)
            dets = [
                _make_detection("person", bbox=(10, 10, 100, 100)),
                _make_detection("car", bbox=(200, 200, 400, 400)),
            ]
            frame = self._frame()

            results = ext.extract_from_frame(frame, dets, 1, "/v.mp4", 0, datetime.now())

            person_files = list((Path(tmp) / "person").glob("*.jpg"))
            vehicle_files = list((Path(tmp) / "vehicle").glob("*.jpg"))
            assert len(person_files) == 1
            assert len(vehicle_files) == 1
