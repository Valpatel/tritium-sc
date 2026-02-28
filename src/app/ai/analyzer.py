# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Video analyzer for content mapping and timeline generation."""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from app.ai.detector import ObjectDetector, FrameDetections, Detection


@dataclass
class ActivitySegment:
    """A continuous segment of activity."""

    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    object_types: set[str] = field(default_factory=set)
    max_people: int = 0
    max_vehicles: int = 0
    total_detections: int = 0

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "object_types": list(self.object_types),
            "max_people": self.max_people,
            "max_vehicles": self.max_vehicles,
            "total_detections": self.total_detections,
        }


@dataclass
class VideoAnalysis:
    """Complete analysis of a video file."""

    video_path: str
    duration: float
    fps: float
    frame_count: int
    resolution: tuple[int, int]
    analyzed_at: str

    # Activity data
    activity_segments: list[ActivitySegment] = field(default_factory=list)
    frame_detections: list[FrameDetections] = field(default_factory=list)

    # Summary stats (fixed: now max concurrent, not sum across frames)
    max_people_concurrent: int = 0      # Most people seen at once
    max_vehicles_concurrent: int = 0    # Most vehicles seen at once
    unique_people_estimate: int = 0     # Estimated unique people (by position tracking)
    unique_vehicles_estimate: int = 0   # Estimated unique vehicles
    active_time: float = 0.0
    inactive_time: float = 0.0

    # Zone events triggered during analysis
    zone_events_triggered: int = 0
    zone_events: list = field(default_factory=list)

    # Legacy aliases for compatibility
    @property
    def total_people_seen(self) -> int:
        return self.unique_people_estimate

    @property
    def total_vehicles_seen(self) -> int:
        return self.unique_vehicles_estimate

    # Key frames
    key_frames: list[int] = field(default_factory=list)

    def to_dict(self, include_detections: bool = True) -> dict:
        """Convert to dictionary for caching.

        Args:
            include_detections: If True, include frame-by-frame detections.
                                This is essential for annotation overlay but
                                increases file size significantly.
        """
        result = {
            "video_path": self.video_path,
            "duration": self.duration,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "resolution": self.resolution,
            "analyzed_at": self.analyzed_at,
            "activity_segments": [s.to_dict() for s in self.activity_segments],
            "max_people_concurrent": self.max_people_concurrent,
            "max_vehicles_concurrent": self.max_vehicles_concurrent,
            "unique_people_estimate": self.unique_people_estimate,
            "unique_vehicles_estimate": self.unique_vehicles_estimate,
            "active_time": self.active_time,
            "inactive_time": self.inactive_time,
            "key_frames": self.key_frames,
            "zone_events_triggered": self.zone_events_triggered,
        }

        # Include frame-level detections for annotation overlay
        # CRITICAL FOR SAFETY: Allows reviewing footage with bounding boxes
        if include_detections and self.frame_detections:
            result["frame_detections"] = [
                {
                    "frame_number": int(fd.frame_number),
                    "timestamp": float(fd.timestamp) if fd.timestamp else 0.0,
                    "detections": [
                        {
                            "class_name": str(det.class_name),
                            "confidence": float(det.confidence),
                            "bbox": [int(x) for x in det.bbox],
                            "center": [int(x) for x in det.center],
                            "area": int(det.area),
                            "track_id": int(getattr(det, 'track_id', 0)) if getattr(det, 'track_id', None) is not None else None,
                        }
                        for det in fd.detections
                    ],
                    "people_count": int(fd.people_count),
                    "vehicle_count": int(fd.vehicle_count),
                }
                for fd in self.frame_detections
            ]

        return result


class VideoAnalyzer:
    """Analyzes video files and generates content maps."""

    def __init__(
        self,
        detector: Optional[ObjectDetector] = None,
        sample_rate: int = 15,  # Sample every N frames (2 fps for 30fps video)
        activity_gap: float = 5.0,  # Gap in seconds to consider new segment
        zone_checker=None,  # Optional ZoneChecker for zone event detection
    ):
        """Initialize video analyzer.

        Args:
            detector: Object detector to use (creates default if None)
            sample_rate: Sample every Nth frame
            activity_gap: Seconds of no activity before starting new segment
            zone_checker: Optional ZoneChecker for detecting zone events
        """
        self.detector = detector or ObjectDetector()
        self.sample_rate = sample_rate
        self.activity_gap = activity_gap
        self.zone_checker = zone_checker

    def analyze_video(
        self,
        video_path: Path,
        progress_callback=None,
        camera_id: Optional[int] = None,
    ) -> VideoAnalysis:
        """Fully analyze a video file.

        Args:
            video_path: Path to video file
            progress_callback: Optional callback(current, total, message)
            camera_id: Optional camera ID for zone checking (auto-detected from path if None)

        Returns:
            VideoAnalysis with all detected content
        """
        video_path = Path(video_path)
        logger.info(f"Starting analysis: {video_path.name}")

        # Try to extract camera_id from path if not provided (e.g., channel_01/...)
        if camera_id is None:
            camera_id = self._extract_camera_id(video_path)

        # Get video metadata
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps
        cap.release()

        # Try to extract video start time from filename
        video_start_time = self._parse_video_timestamp(video_path.name)

        # Track objects with ByteTrack for accurate unique counts
        def on_progress(frame, total):
            if progress_callback:
                progress_callback(frame, total, "Tracking objects...")

        # Use tracking for better unique object counting
        frame_detections, tracked_counts = self.detector.track_video(
            video_path,
            sample_rate=self.sample_rate,
            callback=on_progress,
        )

        # Check zones if zone_checker is available and we have camera_id
        zone_events = []
        if self.zone_checker and camera_id is not None:
            logger.info(f"Checking zones for camera {camera_id}")
            for fd in frame_detections:
                if fd.detections:
                    # Calculate actual timestamp for this frame
                    frame_timestamp = video_start_time + timedelta(seconds=fd.timestamp) if video_start_time else datetime.now()

                    events = self.zone_checker.check_frame_detections(
                        camera_id=camera_id,
                        detections=fd.detections,
                        timestamp=frame_timestamp,
                        video_path=str(video_path),
                        frame_number=fd.frame_number,
                    )
                    zone_events.extend(events)

            if zone_events:
                logger.info(f"Triggered {len(zone_events)} zone events")

        # Generate activity segments
        segments = self._generate_segments(frame_detections, fps)

        # Find key frames (frames with significant activity)
        key_frames = self._find_key_frames(frame_detections)

        # Calculate stats from ByteTrack results
        max_people = max((fd.people_count for fd in frame_detections), default=0)
        max_vehicles = max((fd.vehicle_count for fd in frame_detections), default=0)

        # Use ByteTrack's unique counts (handles occlusion, re-identification)
        unique_people = tracked_counts.get("person", 0)
        unique_vehicles = tracked_counts.get("vehicle", 0)

        active_time = sum(s.duration for s in segments)
        inactive_time = duration - active_time

        analysis = VideoAnalysis(
            video_path=str(video_path),
            duration=duration,
            fps=fps,
            frame_count=frame_count,
            resolution=(width, height),
            analyzed_at=datetime.now().isoformat(),
            activity_segments=segments,
            frame_detections=frame_detections,
            max_people_concurrent=max_people,
            max_vehicles_concurrent=max_vehicles,
            unique_people_estimate=unique_people,
            unique_vehicles_estimate=unique_vehicles,
            active_time=active_time,
            inactive_time=inactive_time,
            key_frames=key_frames,
            zone_events_triggered=len(zone_events),
            zone_events=zone_events,
        )

        logger.info(f"Analysis complete: {len(segments)} activity segments, "
                   f"{unique_people} unique people (max {max_people}), "
                   f"{unique_vehicles} unique vehicles (max {max_vehicles}), "
                   f"{len(zone_events)} zone events")

        return analysis

    def _extract_camera_id(self, video_path: Path) -> Optional[int]:
        """Extract camera/channel ID from video path.

        Looks for patterns like 'channel_01', 'CH01', 'cam1', etc.
        """
        path_str = str(video_path)

        # Try various patterns
        patterns = [
            r'channel_(\d+)',
            r'CH(\d+)',
            r'cam(\d+)',
            r'camera_(\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, path_str, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def _parse_video_timestamp(self, filename: str) -> Optional[datetime]:
        """Parse timestamp from video filename.

        Expected formats:
        - fragment_02_20260125081651.mp4
        - 20260125_081651.mp4
        """
        # Try to find 14-digit timestamp (YYYYMMDDHHmmss)
        match = re.search(r'(\d{14})', filename)
        if match:
            try:
                return datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
            except ValueError:
                pass

        # Try YYYYMMDD_HHMMSS format
        match = re.search(r'(\d{8})_(\d{6})', filename)
        if match:
            try:
                return datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S")
            except ValueError:
                pass

        return None

    def _generate_segments(
        self,
        detections: list[FrameDetections],
        fps: float,
    ) -> list[ActivitySegment]:
        """Group detections into continuous activity segments."""
        if not detections:
            return []

        segments = []
        current_segment = None

        for fd in detections:
            has_activity = len(fd.detections) > 0

            if has_activity:
                if current_segment is None:
                    # Start new segment
                    current_segment = ActivitySegment(
                        start_time=fd.timestamp,
                        end_time=fd.timestamp,
                        start_frame=fd.frame_number,
                        end_frame=fd.frame_number,
                    )
                elif fd.timestamp - current_segment.end_time > self.activity_gap:
                    # Gap too large, finish current and start new
                    segments.append(current_segment)
                    current_segment = ActivitySegment(
                        start_time=fd.timestamp,
                        end_time=fd.timestamp,
                        start_frame=fd.frame_number,
                        end_frame=fd.frame_number,
                    )

                # Update current segment
                current_segment.end_time = fd.timestamp
                current_segment.end_frame = fd.frame_number
                current_segment.total_detections += len(fd.detections)
                current_segment.max_people = max(current_segment.max_people, fd.people_count)
                current_segment.max_vehicles = max(current_segment.max_vehicles, fd.vehicle_count)

                for det in fd.detections:
                    current_segment.object_types.add(det.class_name)

        # Don't forget the last segment
        if current_segment is not None:
            segments.append(current_segment)

        return segments

    def _estimate_unique_objects(
        self,
        detections: list[FrameDetections],
        position_threshold: float = 0.3,  # 30% of frame dimension
    ) -> tuple[int, int]:
        """Estimate unique people and vehicles by tracking position changes.

        Uses simple position-based tracking: if an object appears at a location
        that's significantly different from all known positions, count as new.
        Static objects (parked cars) only count once.

        Args:
            detections: Frame detections
            position_threshold: Fraction of frame size to consider "same position"

        Returns:
            (unique_people, unique_vehicles)
        """
        if not detections:
            return 0, 0

        # Get frame dimensions from first detection
        frame_h, frame_w = detections[0].frame_shape
        threshold_px = int(max(frame_w, frame_h) * position_threshold)

        # Track known positions for each class
        people_positions: list[tuple[int, int]] = []  # List of center points
        vehicle_positions: list[tuple[int, int]] = []

        for fd in detections:
            for det in fd.detections:
                center = det.center

                if det.class_name == "person":
                    positions = people_positions
                elif det.class_name in ("car", "truck", "bus", "motorcycle"):
                    positions = vehicle_positions
                else:
                    continue

                # Check if this is near a known position
                is_new = True
                for known_pos in positions:
                    dist = ((center[0] - known_pos[0])**2 + (center[1] - known_pos[1])**2)**0.5
                    if dist < threshold_px:
                        # Close to known position - same object (or static object)
                        # Update position to track movement
                        # Find index and update
                        idx = positions.index(known_pos)
                        # Weighted average to smooth tracking
                        new_x = int(known_pos[0] * 0.7 + center[0] * 0.3)
                        new_y = int(known_pos[1] * 0.7 + center[1] * 0.3)
                        positions[idx] = (new_x, new_y)
                        is_new = False
                        break

                if is_new:
                    positions.append(center)

        return len(people_positions), len(vehicle_positions)

    def _find_key_frames(
        self,
        detections: list[FrameDetections],
        min_detections: int = 1,
    ) -> list[int]:
        """Find frames with significant activity for thumbnails/previews."""
        key_frames = []

        # Group frames by activity level
        activity_frames = [
            (fd.frame_number, len(fd.detections), fd.people_count)
            for fd in detections
            if len(fd.detections) >= min_detections
        ]

        if not activity_frames:
            return key_frames

        # Take frames with above-average activity
        avg_detections = sum(f[1] for f in activity_frames) / len(activity_frames)

        for frame_num, det_count, people_count in activity_frames:
            if det_count >= avg_detections or people_count >= 2:
                key_frames.append(frame_num)

        # Limit to reasonable number
        if len(key_frames) > 20:
            step = len(key_frames) // 20
            key_frames = key_frames[::step][:20]

        return key_frames

    def extract_key_frames(
        self,
        video_path: Path,
        analysis: VideoAnalysis,
        output_dir: Path,
    ) -> list[Path]:
        """Extract key frames as images.

        Args:
            video_path: Source video
            analysis: Analysis with key frame numbers
            output_dir: Directory to save images

        Returns:
            List of saved image paths
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        cap = cv2.VideoCapture(str(video_path))
        saved = []

        for frame_num in analysis.key_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if ret:
                output_path = output_dir / f"frame_{frame_num:06d}.jpg"
                cv2.imwrite(str(output_path), frame)
                saved.append(output_path)

        cap.release()
        return saved

    def generate_activity_heatmap(
        self,
        analysis: VideoAnalysis,
        resolution: tuple[int, int] = (1920, 1080),
    ) -> np.ndarray:
        """Generate a heatmap of where activity occurs in the frame.

        Args:
            analysis: Video analysis with detections
            resolution: Output resolution

        Returns:
            Heatmap as numpy array (can be overlaid on video frame)
        """
        height, width = resolution
        heatmap = np.zeros((height, width), dtype=np.float32)

        for fd in analysis.frame_detections:
            scale_x = width / fd.frame_shape[1]
            scale_y = height / fd.frame_shape[0]

            for det in fd.detections:
                x1, y1, x2, y2 = det.bbox
                x1, x2 = int(x1 * scale_x), int(x2 * scale_x)
                y1, y2 = int(y1 * scale_y), int(y2 * scale_y)

                # Add heat at detection location
                heatmap[y1:y2, x1:x2] += 1

        # Normalize
        if heatmap.max() > 0:
            heatmap = heatmap / heatmap.max()

        # Apply colormap
        heatmap_color = cv2.applyColorMap(
            (heatmap * 255).astype(np.uint8),
            cv2.COLORMAP_JET,
        )

        return heatmap_color
