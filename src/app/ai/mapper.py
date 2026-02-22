"""Content mapper for multi-video timeline and compression analysis."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from app.ai.analyzer import VideoAnalysis, VideoAnalyzer, ActivitySegment


@dataclass
class TimelineEvent:
    """A single event in the timeline."""

    timestamp: datetime
    end_timestamp: datetime
    event_type: str  # "person", "vehicle", "animal", "motion"
    channel: int
    video_path: str
    frame_number: int
    confidence: float
    thumbnail_path: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "end_timestamp": self.end_timestamp.isoformat(),
            "duration_seconds": (self.end_timestamp - self.timestamp).total_seconds(),
            "event_type": self.event_type,
            "channel": self.channel,
            "video_path": self.video_path,
            "frame_number": self.frame_number,
            "confidence": self.confidence,
            "thumbnail_path": self.thumbnail_path,
            "description": self.description,
        }


@dataclass
class DayTimeline:
    """Timeline of all events for a day."""

    date: str  # YYYY-MM-DD
    channel: int
    events: list[TimelineEvent] = field(default_factory=list)
    total_people: int = 0
    total_vehicles: int = 0
    active_hours: list[int] = field(default_factory=list)  # Hours with activity
    peak_hour: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "channel": self.channel,
            "events": [e.to_dict() for e in self.events],
            "total_people": self.total_people,
            "total_vehicles": self.total_vehicles,
            "active_hours": self.active_hours,
            "peak_hour": self.peak_hour,
            "event_count": len(self.events),
        }


@dataclass
class CompressionCandidate:
    """A video segment that could be compressed/deleted."""

    video_path: str
    start_time: float
    end_time: float
    duration: float
    reason: str  # "no_activity", "duplicate", "low_quality"
    estimated_savings_mb: float
    keep_thumbnail: bool = True


class ContentMapper:
    """Maps content across multiple videos to build timelines and identify compression opportunities."""

    def __init__(
        self,
        analyzer: Optional[VideoAnalyzer] = None,
        cache_dir: Optional[Path] = None,
    ):
        """Initialize content mapper.

        Args:
            analyzer: Video analyzer to use
            cache_dir: Directory to cache analysis results
        """
        self.analyzer = analyzer or VideoAnalyzer()
        self.cache_dir = Path(cache_dir) if cache_dir else None

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def analyze_day(
        self,
        channel: int,
        date: str,
        video_paths: list[Path],
        progress_callback=None,
    ) -> DayTimeline:
        """Analyze all videos for a day and build timeline.

        Args:
            channel: Camera channel number
            date: Date string (YYYY-MM-DD)
            video_paths: List of video files for this day
            progress_callback: Optional callback(current, total, message)

        Returns:
            DayTimeline with all events
        """
        logger.info(f"Analyzing day: CH{channel} {date} ({len(video_paths)} videos)")

        timeline = DayTimeline(date=date, channel=channel)
        hourly_counts = [0] * 24

        # Track unique objects across ALL videos (cross-video deduplication)
        # Using position-based tracking with larger threshold for static objects
        all_people_positions: list[tuple[int, int]] = []
        all_vehicle_positions: list[tuple[int, int]] = []
        position_threshold = 100  # pixels - static objects stay in place

        for i, video_path in enumerate(video_paths):
            if progress_callback:
                progress_callback(i, len(video_paths), f"Analyzing {video_path.name}")

            try:
                # Check cache
                analysis = self._load_cached(video_path)
                if not analysis:
                    analysis = self.analyzer.analyze_video(video_path)
                    self._save_cached(video_path, analysis)

                # Extract video start time from filename
                video_start_time = self._parse_video_time(video_path.name, date)

                # Convert segments to timeline events
                for segment in analysis.activity_segments:
                    event_time = video_start_time + timedelta(seconds=segment.start_time)
                    end_time = video_start_time + timedelta(seconds=segment.end_time)

                    # Determine primary event type
                    if segment.max_people > 0:
                        event_type = "person"
                    elif segment.max_vehicles > 0:
                        event_type = "vehicle"
                    elif "dog" in segment.object_types or "cat" in segment.object_types:
                        event_type = "animal"
                    else:
                        event_type = "motion"

                    event = TimelineEvent(
                        timestamp=event_time,
                        end_timestamp=end_time,
                        event_type=event_type,
                        channel=channel,
                        video_path=str(video_path),
                        frame_number=segment.start_frame,
                        confidence=0.8,  # Average confidence
                    )
                    timeline.events.append(event)

                    # Track hourly activity
                    hourly_counts[event_time.hour] += 1

                # Cross-video deduplication: track unique objects by position
                # Instead of summing per-video counts, dedupe across all videos
                for fd in analysis.frame_detections:
                    for det in fd.detections:
                        center = det.center
                        is_new = True

                        if det.class_name == "person":
                            positions = all_people_positions
                        elif det.class_name in ("car", "truck", "bus", "motorcycle"):
                            positions = all_vehicle_positions
                        else:
                            continue

                        # Check if near any known position (same object)
                        for known_pos in positions:
                            dist = ((center[0] - known_pos[0])**2 + (center[1] - known_pos[1])**2)**0.5
                            if dist < position_threshold:
                                is_new = False
                                break

                        if is_new:
                            positions.append(center)

            except Exception as e:
                logger.error(f"Failed to analyze {video_path}: {e}")
                continue

        # Calculate active hours and peak
        timeline.active_hours = [h for h, count in enumerate(hourly_counts) if count > 0]
        if hourly_counts:
            timeline.peak_hour = hourly_counts.index(max(hourly_counts))

        # Set final counts from cross-video deduplication
        timeline.total_people = len(all_people_positions)
        timeline.total_vehicles = len(all_vehicle_positions)

        # Sort events by time
        timeline.events.sort(key=lambda e: e.timestamp)

        logger.info(f"Day analysis complete: {len(timeline.events)} events, "
                   f"{timeline.total_people} unique people, {timeline.total_vehicles} unique vehicles")

        return timeline

    def find_compression_candidates(
        self,
        analysis: VideoAnalysis,
        min_inactive_duration: float = 60.0,  # 1 minute
    ) -> list[CompressionCandidate]:
        """Find segments of video that can be safely compressed or removed.

        Args:
            analysis: Video analysis
            min_inactive_duration: Minimum inactive duration to consider (seconds)

        Returns:
            List of compression candidates
        """
        candidates = []
        video_path = analysis.video_path

        # Find gaps between activity segments
        segments = sorted(analysis.activity_segments, key=lambda s: s.start_time)

        # Check start of video
        if segments and segments[0].start_time > min_inactive_duration:
            duration = segments[0].start_time
            candidates.append(CompressionCandidate(
                video_path=video_path,
                start_time=0,
                end_time=segments[0].start_time,
                duration=duration,
                reason="no_activity",
                estimated_savings_mb=self._estimate_size(duration, analysis.fps, analysis.resolution),
            ))

        # Check gaps between segments
        for i in range(len(segments) - 1):
            gap_start = segments[i].end_time
            gap_end = segments[i + 1].start_time
            gap_duration = gap_end - gap_start

            if gap_duration >= min_inactive_duration:
                candidates.append(CompressionCandidate(
                    video_path=video_path,
                    start_time=gap_start,
                    end_time=gap_end,
                    duration=gap_duration,
                    reason="no_activity",
                    estimated_savings_mb=self._estimate_size(gap_duration, analysis.fps, analysis.resolution),
                ))

        # Check end of video
        if segments and analysis.duration - segments[-1].end_time > min_inactive_duration:
            duration = analysis.duration - segments[-1].end_time
            candidates.append(CompressionCandidate(
                video_path=video_path,
                start_time=segments[-1].end_time,
                end_time=analysis.duration,
                duration=duration,
                reason="no_activity",
                estimated_savings_mb=self._estimate_size(duration, analysis.fps, analysis.resolution),
            ))

        total_savings = sum(c.estimated_savings_mb for c in candidates)
        logger.info(f"Found {len(candidates)} compression candidates, "
                   f"potential savings: {total_savings:.1f} MB")

        return candidates

    def generate_hyperlapse(
        self,
        video_paths: list[Path],
        output_path: Path,
        interval_seconds: float = 60.0,  # Sample every N seconds
        target_fps: float = 30.0,
        target_duration: float = 60.0,  # Target output duration in seconds
    ) -> Path:
        """Generate a hyperlapse showing changes over time.

        Args:
            video_paths: List of source videos (chronological order)
            output_path: Output video path
            interval_seconds: Sample interval from source videos
            target_fps: Output video FPS
            target_duration: Target output duration

        Returns:
            Path to generated hyperlapse video
        """
        logger.info(f"Generating hyperlapse from {len(video_paths)} videos")

        frames = []
        total_source_duration = 0

        for video_path in video_paths:
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
            total_source_duration += duration

            # Sample frames at interval
            sample_interval_frames = int(interval_seconds * fps)
            frame_num = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_num % sample_interval_frames == 0:
                    frames.append(frame)

                frame_num += 1

            cap.release()

        if not frames:
            raise ValueError("No frames extracted for hyperlapse")

        # Calculate speed multiplier to hit target duration
        total_frames_needed = int(target_duration * target_fps)
        if len(frames) > total_frames_needed:
            # Subsample frames
            step = len(frames) / total_frames_needed
            indices = [int(i * step) for i in range(total_frames_needed)]
            frames = [frames[i] for i in indices]

        # Write output video
        height, width = frames[0].shape[:2]
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(str(output_path), fourcc, target_fps, (width, height))

        for frame in frames:
            writer.write(frame)

        writer.release()

        speedup = total_source_duration / (len(frames) / target_fps)
        logger.info(f"Hyperlapse created: {len(frames)} frames, {speedup:.0f}x speedup")

        return output_path

    def generate_people_overlay(
        self,
        video_path: Path,
        analysis: VideoAnalysis,
        output_path: Path,
    ) -> Path:
        """Generate a composite image showing all people detected.

        Args:
            video_path: Source video
            analysis: Analysis with detections
            output_path: Output image path

        Returns:
            Path to generated image
        """
        logger.info(f"Generating people overlay for {video_path.name}")

        # Get background frame (first frame)
        cap = cv2.VideoCapture(str(video_path))
        ret, background = cap.read()
        if not ret:
            raise ValueError("Could not read video")

        height, width = background.shape[:2]
        overlay = background.copy().astype(np.float32)
        person_mask = np.zeros((height, width), dtype=np.float32)

        # Collect all person detections
        person_frames = []
        for fd in analysis.frame_detections:
            for det in fd.detections:
                if det.class_name == "person":
                    person_frames.append((fd.frame_number, det.bbox))

        # Extract and composite people
        for frame_num, bbox in person_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                continue

            x1, y1, x2, y2 = bbox
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)

            # Add person region to overlay
            region = frame[y1:y2, x1:x2].astype(np.float32)
            overlay[y1:y2, x1:x2] = overlay[y1:y2, x1:x2] * 0.7 + region * 0.3
            person_mask[y1:y2, x1:x2] += 1

        cap.release()

        # Normalize overlay
        person_mask = np.clip(person_mask, 1, None)  # Avoid division by zero
        for c in range(3):
            overlay[:, :, c] = overlay[:, :, c] / person_mask * (person_mask > 0) + \
                              background[:, :, c] * (person_mask == 0)

        # Add glow effect to person regions
        glow = cv2.GaussianBlur((person_mask > 0).astype(np.uint8) * 255, (21, 21), 0)
        glow_color = np.zeros_like(overlay)
        glow_color[:, :, 0] = 255  # Cyan glow (BGR)
        glow_color[:, :, 1] = 240
        overlay = cv2.addWeighted(overlay, 1, glow_color * (glow[:, :, None] / 255) * 0.3, 1, 0)

        cv2.imwrite(str(output_path), overlay.astype(np.uint8))
        logger.info(f"People overlay saved: {len(person_frames)} person instances")

        return output_path

    def _parse_video_time(self, filename: str, date: str) -> datetime:
        """Parse timestamp from video filename."""
        import re
        # Expected: fragment_02_20260125081651.mp4 or similar
        match = re.search(r'(\d{14})', filename)
        if match:
            ts = match.group(1)
            return datetime.strptime(ts, "%Y%m%d%H%M%S")

        # Fallback to date at midnight
        return datetime.strptime(date, "%Y-%m-%d")

    def _estimate_size(
        self,
        duration: float,
        fps: float,
        resolution: tuple[int, int],
    ) -> float:
        """Estimate video size in MB based on duration and resolution."""
        # Rough estimate: 1080p @ 30fps ≈ 5 MB/minute
        base_rate = 5.0 / 60  # MB per second for 1080p
        width, height = resolution
        scale = (width * height) / (1920 * 1080)
        return duration * base_rate * scale * (fps / 30)

    def _load_cached(self, video_path: Path) -> Optional[VideoAnalysis]:
        """Load cached analysis if available."""
        if not self.cache_dir:
            return None

        cache_path = self.cache_dir / f"{video_path.stem}.json"
        if cache_path.exists():
            try:
                with open(cache_path) as f:
                    data = json.load(f)
                # TODO: Deserialize properly
                return None  # For now, skip cache loading
            except Exception:
                pass
        return None

    def _save_cached(self, video_path: Path, analysis: VideoAnalysis):
        """Save analysis to cache."""
        if not self.cache_dir:
            return

        cache_path = self.cache_dir / f"{video_path.stem}.json"
        try:
            with open(cache_path, 'w') as f:
                json.dump(analysis.to_dict(), f)
        except Exception as e:
            logger.warning(f"Failed to cache analysis: {e}")
