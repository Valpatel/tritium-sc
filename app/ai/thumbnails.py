"""Thumbnail extraction and storage for detected objects.

Critical for safety: Generates CLIP embeddings for person re-identification.
This enables tracking the same individual across multiple appearances.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

# Lazy load embedding generator to avoid import errors when CLIP not installed
_embedding_generator = None


def get_embedding_generator():
    """Get or create the singleton embedding generator."""
    global _embedding_generator
    if _embedding_generator is None:
        try:
            from app.ai.embeddings import EmbeddingGenerator
            _embedding_generator = EmbeddingGenerator()
            logger.info("CLIP embedding generator initialized for person re-identification")
        except Exception as e:
            logger.warning(f"CLIP not available, embeddings will be zeros: {e}")
            _embedding_generator = False  # Mark as failed, don't retry
    return _embedding_generator if _embedding_generator else None


@dataclass
class ObjectThumbnail:
    """A cropped thumbnail of a detected object."""

    thumbnail_id: str  # Hash-based unique ID
    target_type: str  # "person", "car", "truck", etc.
    timestamp: datetime
    channel: int
    video_path: str
    frame_number: int
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    confidence: float
    thumbnail_path: str
    embedding: Optional[list[float]] = None  # For similarity search

    def to_dict(self) -> dict:
        return {
            "thumbnail_id": self.thumbnail_id,
            "target_type": self.target_type,
            "timestamp": self.timestamp.isoformat(),
            "channel": self.channel,
            "video_path": self.video_path,
            "frame_number": self.frame_number,
            "bbox": list(self.bbox),
            "confidence": self.confidence,
            "thumbnail_path": self.thumbnail_path,
            "has_embedding": self.embedding is not None,
        }


class ThumbnailExtractor:
    """Extracts and stores thumbnails of detected objects."""

    def __init__(
        self,
        output_dir: Path,
        min_size: int = 50,  # Minimum object size in pixels
        padding: float = 0.15,  # Add padding around detections
    ):
        """Initialize thumbnail extractor.

        Args:
            output_dir: Directory to store thumbnails
            min_size: Minimum object dimension to extract
            padding: Fraction of bbox size to add as padding
        """
        self.output_dir = Path(output_dir)
        self.min_size = min_size
        self.padding = padding

        # Create subdirectories
        (self.output_dir / "person").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "vehicle").mkdir(parents=True, exist_ok=True)
        (self.output_dir / "animal").mkdir(parents=True, exist_ok=True)

    def extract_from_frame(
        self,
        frame: np.ndarray,
        detections: list,  # List of Detection objects
        channel: int,
        video_path: str,
        frame_number: int,
        timestamp: datetime,
    ) -> list[ObjectThumbnail]:
        """Extract thumbnails from a frame for all detections.

        Args:
            frame: BGR image
            detections: List of Detection objects
            channel: Camera channel
            video_path: Source video path
            frame_number: Frame number in video
            timestamp: Frame timestamp

        Returns:
            List of extracted ObjectThumbnail objects
        """
        height, width = frame.shape[:2]
        thumbnails = []

        for det in detections:
            # Skip small detections
            x1, y1, x2, y2 = det.bbox
            obj_width = x2 - x1
            obj_height = y2 - y1

            if obj_width < self.min_size or obj_height < self.min_size:
                continue

            # Add padding
            pad_x = int(obj_width * self.padding)
            pad_y = int(obj_height * self.padding)

            x1 = max(0, x1 - pad_x)
            y1 = max(0, y1 - pad_y)
            x2 = min(width, x2 + pad_x)
            y2 = min(height, y2 + pad_y)

            # Crop thumbnail
            thumbnail_img = frame[y1:y2, x1:x2].copy()

            # Generate unique ID based on content
            img_hash = hashlib.md5(thumbnail_img.tobytes()).hexdigest()[:12]
            thumbnail_id = f"{det.class_name}_{timestamp.strftime('%Y%m%d%H%M%S')}_{img_hash}"

            # Determine category and save path
            if det.class_name == "person":
                category = "person"
            elif det.class_name in ("car", "truck", "bus", "motorcycle", "bicycle"):
                category = "vehicle"
            elif det.class_name in ("dog", "cat", "bird"):
                category = "animal"
            else:
                continue

            # Save thumbnail
            save_path = self.output_dir / category / f"{thumbnail_id}.jpg"
            cv2.imwrite(str(save_path), thumbnail_img)

            # Generate CLIP embedding for re-identification
            # CRITICAL for safety: This enables finding the same person across appearances
            embedding = None
            if category == "person" or det.confidence > 0.7:
                # Prioritize people, but also embed high-confidence vehicles
                generator = get_embedding_generator()
                if generator:
                    try:
                        embedding = generator.embed_image(thumbnail_img)
                        logger.debug(f"Generated embedding for {det.class_name} ({thumbnail_id})")
                    except Exception as e:
                        logger.warning(f"Failed to generate embedding: {e}")

            thumbnails.append(ObjectThumbnail(
                thumbnail_id=thumbnail_id,
                target_type=det.class_name,
                timestamp=timestamp,
                channel=channel,
                video_path=video_path,
                frame_number=frame_number,
                bbox=(x1, y1, x2, y2),
                confidence=det.confidence,
                thumbnail_path=str(save_path),
                embedding=embedding,
            ))

        return thumbnails

    def extract_from_video(
        self,
        video_path: Path,
        detections_by_frame: dict[int, list],  # frame_number -> detections
        channel: int,
        base_timestamp: datetime,
        fps: float,
        sample_interval: int = 30,  # Only extract every N frames to avoid duplicates
    ) -> list[ObjectThumbnail]:
        """Extract thumbnails from a video for all detections.

        Args:
            video_path: Path to video file
            detections_by_frame: Dict mapping frame numbers to detections
            channel: Camera channel
            base_timestamp: Start time of video
            fps: Video frame rate
            sample_interval: Minimum frames between extractions of same object

        Returns:
            List of extracted thumbnails
        """
        if not detections_by_frame:
            return []

        cap = cv2.VideoCapture(str(video_path))
        thumbnails = []
        last_extracted = {}  # Track last extraction by position hash

        for frame_number in sorted(detections_by_frame.keys()):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ret, frame = cap.read()
            if not ret:
                continue

            timestamp = base_timestamp + timedelta(seconds=frame_number / fps)
            dets = detections_by_frame[frame_number]

            for det in dets:
                # Create position hash for deduplication
                pos_hash = f"{det.class_name}_{det.center[0]//50}_{det.center[1]//50}"

                # Skip if we recently extracted this object at similar position
                if pos_hash in last_extracted:
                    if frame_number - last_extracted[pos_hash] < sample_interval:
                        continue

                # Extract thumbnail
                extracted = self.extract_from_frame(
                    frame, [det], channel, str(video_path),
                    frame_number, timestamp
                )

                if extracted:
                    thumbnails.extend(extracted)
                    last_extracted[pos_hash] = frame_number

        cap.release()
        logger.info(f"Extracted {len(thumbnails)} thumbnails from {video_path.name}")
        return thumbnails


# Import for timedelta used above
from datetime import timedelta
