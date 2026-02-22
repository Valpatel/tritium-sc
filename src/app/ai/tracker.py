"""Simple object tracker for counting unique people/vehicles."""

from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class TrackedObject:
    """A tracked object across multiple frames."""

    track_id: int
    class_name: str
    positions: list[tuple[int, int]] = field(default_factory=list)  # Center positions
    bboxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    confidences: list[float] = field(default_factory=list)
    first_frame: int = 0
    last_frame: int = 0
    frames_missing: int = 0

    @property
    def last_position(self) -> tuple[int, int]:
        return self.positions[-1] if self.positions else (0, 0)

    @property
    def last_bbox(self) -> tuple[int, int, int, int]:
        return self.bboxes[-1] if self.bboxes else (0, 0, 0, 0)

    @property
    def velocity(self) -> tuple[float, float]:
        """Estimate velocity from last few positions."""
        if len(self.positions) < 2:
            return (0, 0)

        # Use last 3-5 positions for smoothing
        recent = self.positions[-5:]
        if len(recent) < 2:
            return (0, 0)

        # Average velocity
        vx = (recent[-1][0] - recent[0][0]) / len(recent)
        vy = (recent[-1][1] - recent[0][1]) / len(recent)
        return (vx, vy)

    @property
    def predicted_position(self) -> tuple[int, int]:
        """Predict next position based on velocity."""
        vx, vy = self.velocity
        lx, ly = self.last_position
        return (int(lx + vx), int(ly + vy))

    @property
    def avg_confidence(self) -> float:
        return sum(self.confidences) / len(self.confidences) if self.confidences else 0

    @property
    def duration_frames(self) -> int:
        return self.last_frame - self.first_frame

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "class_name": self.class_name,
            "first_frame": self.first_frame,
            "last_frame": self.last_frame,
            "duration_frames": self.duration_frames,
            "avg_confidence": round(self.avg_confidence, 3),
            "positions_count": len(self.positions),
            "last_bbox": list(self.last_bbox),
        }


class SimpleTracker:
    """
    Simple IoU + velocity-based tracker for security cameras.

    Since cameras are static, objects move predictably. We track by:
    1. IoU (bounding box overlap) for nearby objects
    2. Predicted position based on velocity
    3. Maximum missing frames before track is closed
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        distance_threshold: int = 100,  # Max pixels to match
        max_missing: int = 10,  # Max frames before track lost
    ):
        self.iou_threshold = iou_threshold
        self.distance_threshold = distance_threshold
        self.max_missing = max_missing

        self.next_id = 1
        self.active_tracks: list[TrackedObject] = []
        self.completed_tracks: list[TrackedObject] = []

    def update(
        self,
        frame_number: int,
        detections: list[dict],  # List of detection dicts with bbox, class_name, confidence
    ) -> list[TrackedObject]:
        """
        Update tracker with new frame detections.

        Args:
            frame_number: Current frame number
            detections: List of detections with keys: bbox, class_name, confidence, center

        Returns:
            List of active tracks with assigned track IDs
        """
        # Increment missing counter for all tracks
        for track in self.active_tracks:
            track.frames_missing += 1

        # Match detections to existing tracks
        matched_tracks = set()
        matched_detections = set()

        for det_idx, det in enumerate(detections):
            best_track = None
            best_score = float('inf')

            det_center = det.get("center", (0, 0))
            det_bbox = det.get("bbox", (0, 0, 0, 0))
            det_class = det.get("class_name", "")

            for track in self.active_tracks:
                # Skip if class doesn't match
                if track.class_name != det_class:
                    continue

                # Skip if already matched
                if id(track) in matched_tracks:
                    continue

                # Calculate IoU
                iou = self._calculate_iou(track.last_bbox, det_bbox)

                # Calculate distance to predicted position
                pred_pos = track.predicted_position
                dist = np.sqrt((det_center[0] - pred_pos[0])**2 +
                              (det_center[1] - pred_pos[1])**2)

                # Score: lower is better (prefer high IoU, low distance)
                if iou > self.iou_threshold:
                    score = dist - (iou * 100)  # Bonus for IoU overlap
                elif dist < self.distance_threshold:
                    score = dist
                else:
                    continue  # No match

                if score < best_score:
                    best_score = score
                    best_track = track

            if best_track is not None:
                # Update existing track
                best_track.positions.append(det_center)
                best_track.bboxes.append(det_bbox)
                best_track.confidences.append(det.get("confidence", 0))
                best_track.last_frame = frame_number
                best_track.frames_missing = 0
                matched_tracks.add(id(best_track))
                matched_detections.add(det_idx)

        # Create new tracks for unmatched detections
        for det_idx, det in enumerate(detections):
            if det_idx in matched_detections:
                continue

            new_track = TrackedObject(
                track_id=self.next_id,
                class_name=det.get("class_name", "unknown"),
                positions=[det.get("center", (0, 0))],
                bboxes=[det.get("bbox", (0, 0, 0, 0))],
                confidences=[det.get("confidence", 0)],
                first_frame=frame_number,
                last_frame=frame_number,
            )
            self.active_tracks.append(new_track)
            self.next_id += 1

        # Remove tracks that have been missing too long
        still_active = []
        for track in self.active_tracks:
            if track.frames_missing > self.max_missing:
                # Track lost - move to completed
                self.completed_tracks.append(track)
            else:
                still_active.append(track)
        self.active_tracks = still_active

        return self.active_tracks

    def finalize(self) -> list[TrackedObject]:
        """
        Finalize tracking - move all active tracks to completed.

        Returns:
            All completed tracks (unique objects seen in video)
        """
        self.completed_tracks.extend(self.active_tracks)
        self.active_tracks = []
        return self.completed_tracks

    def get_unique_counts(self) -> dict[str, int]:
        """Get counts of unique objects by class."""
        all_tracks = self.active_tracks + self.completed_tracks

        # Filter short tracks (likely false positives)
        valid_tracks = [t for t in all_tracks if t.duration_frames >= 3 or len(t.positions) >= 2]

        counts = {}
        for track in valid_tracks:
            cls = track.class_name
            counts[cls] = counts.get(cls, 0) + 1

        return counts

    def _calculate_iou(
        self,
        box1: tuple[int, int, int, int],
        box2: tuple[int, int, int, int],
    ) -> float:
        """Calculate Intersection over Union between two bboxes."""
        x1_1, y1_1, x2_1, y2_1 = box1
        x1_2, y1_2, x2_2, y2_2 = box2

        # Calculate intersection
        x1_i = max(x1_1, x1_2)
        y1_i = max(y1_1, y1_2)
        x2_i = min(x2_1, x2_2)
        y2_i = min(y2_1, y2_2)

        if x2_i <= x1_i or y2_i <= y1_i:
            return 0.0

        intersection = (x2_i - x1_i) * (y2_i - y1_i)

        # Calculate union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0


def track_detections_in_video(frame_detections: list) -> tuple[list[TrackedObject], dict[str, int]]:
    """
    Track objects across all frames in a video.

    Args:
        frame_detections: List of FrameDetections objects

    Returns:
        (all_tracks, unique_counts) - list of all tracked objects and counts by class
    """
    tracker = SimpleTracker()

    for fd in frame_detections:
        # Convert detections to dict format
        dets = []
        for det in fd.detections:
            dets.append({
                "bbox": det.bbox,
                "center": det.center,
                "class_name": det.class_name,
                "confidence": det.confidence,
            })

        tracker.update(fd.frame_number, dets)

    all_tracks = tracker.finalize()
    unique_counts = tracker.get_unique_counts()

    return all_tracks, unique_counts
