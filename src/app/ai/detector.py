"""Object detection using YOLO."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False
    logger.warning("YOLO not available. Run: pip install ultralytics")


@dataclass
class Detection:
    """A single object detection."""

    class_id: int
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    center: tuple[int, int]
    area: int

    def to_dict(self) -> dict:
        return {
            "class_id": int(self.class_id),
            "class_name": str(self.class_name),
            "confidence": round(float(self.confidence), 3),
            "bbox": tuple(int(x) for x in self.bbox),
            "center": tuple(int(x) for x in self.center),
            "area": int(self.area),
        }


@dataclass
class FrameDetections:
    """Detections for a single frame."""

    frame_number: int
    timestamp: float
    detections: list[Detection]
    frame_shape: tuple[int, int]  # height, width

    @property
    def has_people(self) -> bool:
        return any(d.class_name == "person" for d in self.detections)

    @property
    def has_vehicles(self) -> bool:
        return any(d.class_name in ("car", "truck", "bus", "motorcycle") for d in self.detections)

    @property
    def people_count(self) -> int:
        return sum(1 for d in self.detections if d.class_name == "person")

    @property
    def vehicle_count(self) -> int:
        return sum(1 for d in self.detections if d.class_name in ("car", "truck", "bus", "motorcycle"))


class ObjectDetector:
    """YOLO-based object detector for security camera footage."""

    # Classes we care about for security cameras (COCO classes)
    RELEVANT_CLASSES = {
        0: "person",
        1: "bicycle",
        2: "car",
        3: "motorcycle",
        5: "bus",
        6: "train",
        7: "truck",
        14: "bird",
        15: "cat",
        16: "dog",
        24: "backpack",
        26: "handbag",
        28: "suitcase",
    }

    # Vehicle types for grouping
    VEHICLE_TYPES = {"car", "truck", "bus", "motorcycle", "bicycle", "train"}

    def __init__(
        self,
        model_name: str = "yolov8n.pt",
        confidence_threshold: float = 0.5,
        device: Optional[str] = None,
    ):
        """Initialize the detector.

        Args:
            model_name: YOLO model to use (yolov8n.pt, yolov8s.pt, etc.)
            confidence_threshold: Minimum confidence for detections
            device: Device to run on ('cuda', 'cpu', or None for auto)
        """
        if not YOLO_AVAILABLE:
            raise RuntimeError("YOLO not available. Install with: pip install ultralytics")

        self.confidence_threshold = confidence_threshold
        self.device = device

        logger.info(f"Loading YOLO model: {model_name}")
        self.model = YOLO(model_name)

        if device:
            self.model.to(device)

        # Get class names from model
        self.class_names = self.model.names
        logger.info(f"YOLO model loaded with {len(self.class_names)} classes")

    def detect_frame(
        self,
        frame: np.ndarray,
        frame_number: int = 0,
        timestamp: float = 0.0,
    ) -> FrameDetections:
        """Detect objects in a single frame.

        Args:
            frame: BGR image as numpy array
            frame_number: Frame index in video
            timestamp: Timestamp in seconds

        Returns:
            FrameDetections with all detected objects
        """
        height, width = frame.shape[:2]
        detections = []

        # Run YOLO inference
        results = self.model(frame, conf=self.confidence_threshold, verbose=False)

        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i in range(len(boxes)):
                class_id = int(boxes.cls[i].item())
                confidence = float(boxes.conf[i].item())

                # Filter to relevant classes only
                if class_id not in self.RELEVANT_CLASSES:
                    continue

                class_name = self.class_names.get(class_id, f"class_{class_id}")

                # Get bounding box
                x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(int)
                center = ((x1 + x2) // 2, (y1 + y2) // 2)
                area = (x2 - x1) * (y2 - y1)

                detections.append(
                    Detection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        bbox=(x1, y1, x2, y2),
                        center=center,
                        area=area,
                    )
                )

        return FrameDetections(
            frame_number=frame_number,
            timestamp=timestamp,
            detections=detections,
            frame_shape=(height, width),
        )

    def detect_video(
        self,
        video_path: Path,
        sample_rate: int = 1,
        max_frames: Optional[int] = None,
        callback=None,
    ) -> list[FrameDetections]:
        """Detect objects across a video file.

        Args:
            video_path: Path to video file
            sample_rate: Process every Nth frame (1 = all frames)
            max_frames: Maximum number of frames to process
            callback: Optional callback(frame_num, total_frames) for progress

        Returns:
            List of FrameDetections for sampled frames
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        logger.info(f"Analyzing video: {video_path.name} ({total_frames} frames @ {fps:.1f} fps)")

        all_detections = []
        frame_num = 0
        processed = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_num % sample_rate == 0:
                timestamp = frame_num / fps
                detection = self.detect_frame(frame, frame_num, timestamp)
                all_detections.append(detection)
                processed += 1

                if callback:
                    callback(frame_num, total_frames)

                if max_frames and processed >= max_frames:
                    break

            frame_num += 1

        cap.release()

        logger.info(f"Processed {processed} frames, found {sum(len(d.detections) for d in all_detections)} total detections")
        return all_detections

    def track_video(
        self,
        video_path: Path,
        sample_rate: int = 1,
        max_frames: Optional[int] = None,
        callback=None,
    ) -> tuple[list[FrameDetections], dict]:
        """Track objects across a video using ByteTrack.

        Uses YOLO's built-in tracking for proper object persistence across frames.
        Handles occlusions and maintains consistent track IDs.

        Args:
            video_path: Path to video file
            sample_rate: Process every Nth frame
            max_frames: Maximum frames to process
            callback: Progress callback(frame_num, total_frames)

        Returns:
            (frame_detections, unique_tracks) - detections and unique object counts
        """
        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        logger.info(f"Tracking video: {video_path.name} ({total_frames} frames @ {fps:.1f} fps)")

        all_detections = []
        unique_track_ids = {"person": set(), "vehicle": set(), "animal": set()}

        # Use YOLO's built-in tracking with ByteTrack
        # persist=True maintains tracks across frames
        results = self.model.track(
            source=str(video_path),
            conf=self.confidence_threshold,
            tracker="bytetrack.yaml",
            persist=True,
            stream=True,  # Generator for memory efficiency
            verbose=False,
        )

        frame_num = 0
        processed = 0

        for result in results:
            # Only process sampled frames
            if frame_num % sample_rate != 0:
                frame_num += 1
                continue

            timestamp = frame_num / fps
            height, width = result.orig_shape
            detections = []

            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                for i in range(len(boxes)):
                    class_id = int(boxes.cls[i].item())
                    confidence = float(boxes.conf[i].item())

                    # Filter to relevant classes
                    if class_id not in self.RELEVANT_CLASSES:
                        continue

                    class_name = self.class_names.get(class_id, f"class_{class_id}")

                    # Get track ID if available
                    track_id = None
                    if boxes.id is not None:
                        track_id = int(boxes.id[i].item())

                        # Track unique objects by category
                        if class_name == "person":
                            unique_track_ids["person"].add(track_id)
                        elif class_name in self.VEHICLE_TYPES:
                            unique_track_ids["vehicle"].add(track_id)
                        elif class_name in ("dog", "cat", "bird"):
                            unique_track_ids["animal"].add(track_id)

                    # Get bounding box
                    x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy().astype(int)
                    center = ((x1 + x2) // 2, (y1 + y2) // 2)
                    area = (x2 - x1) * (y2 - y1)

                    det = Detection(
                        class_id=class_id,
                        class_name=class_name,
                        confidence=confidence,
                        bbox=(x1, y1, x2, y2),
                        center=center,
                        area=area,
                    )
                    # Store track_id as attribute
                    det.track_id = track_id
                    detections.append(det)

            all_detections.append(FrameDetections(
                frame_number=frame_num,
                timestamp=timestamp,
                detections=detections,
                frame_shape=(height, width),
            ))

            processed += 1
            if callback:
                callback(frame_num, total_frames)

            if max_frames and processed >= max_frames:
                break

            frame_num += 1

        unique_counts = {
            "person": len(unique_track_ids["person"]),
            "vehicle": len(unique_track_ids["vehicle"]),
            "animal": len(unique_track_ids["animal"]),
        }

        logger.info(f"Tracked {processed} frames: {unique_counts['person']} unique people, "
                   f"{unique_counts['vehicle']} unique vehicles")

        return all_detections, unique_counts

    def draw_detections(
        self,
        frame: np.ndarray,
        detections: FrameDetections,
        color_map: Optional[dict] = None,
    ) -> np.ndarray:
        """Draw detection boxes on a frame.

        Args:
            frame: BGR image
            detections: FrameDetections to draw
            color_map: Optional dict mapping class names to BGR colors

        Returns:
            Frame with detections drawn
        """
        default_colors = {
            "person": (0, 255, 255),      # Cyan
            "car": (255, 42, 109),         # Magenta
            "truck": (255, 42, 109),
            "bus": (255, 42, 109),
            "motorcycle": (255, 42, 109),
            "bicycle": (5, 255, 161),      # Green
            "dog": (252, 238, 10),         # Yellow
            "cat": (252, 238, 10),
            "bird": (252, 238, 10),
        }
        colors = color_map or default_colors

        result = frame.copy()

        for det in detections.detections:
            color = colors.get(det.class_name, (0, 240, 255))
            x1, y1, x2, y2 = det.bbox

            # Draw box
            cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)

            # Draw label
            label = f"{det.class_name} {det.confidence:.0%}"
            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
            cv2.rectangle(result, (x1, y1 - label_size[1] - 5), (x1 + label_size[0], y1), color, -1)
            cv2.putText(result, label, (x1, y1 - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return result
