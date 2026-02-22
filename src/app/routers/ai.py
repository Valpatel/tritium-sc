"""AI content mapping and analysis endpoints."""

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from loguru import logger

from app.config import settings

router = APIRouter(prefix="/api/ai", tags=["ai"])

# Global state for background tasks
analysis_tasks = {}


class AnalysisRequest(BaseModel):
    """Request to analyze videos."""

    channel: int
    date: str  # YYYY-MM-DD
    sample_rate: int = 15  # Process every Nth frame


class AnalysisStatus(BaseModel):
    """Status of an analysis task."""

    task_id: str
    status: str  # "pending", "running", "complete", "failed"
    progress: float  # 0-100
    message: str
    result: Optional[dict] = None


class TimelineResponse(BaseModel):
    """Response with day timeline."""

    date: str
    channel: int
    events: list[dict]
    total_people: int
    total_vehicles: int
    active_hours: list[int]
    peak_hour: Optional[int]


def get_video_paths(channel: int, date: str) -> list[Path]:
    """Get all video paths for a channel/date."""
    from app.routers.videos import find_channel_dir, find_date_dir

    channel_dir = find_channel_dir(channel)
    if not channel_dir:
        return []

    date_dir = find_date_dir(channel_dir, date)
    if not date_dir:
        return []

    return sorted(date_dir.glob("*.mp4"))


@router.get("/status")
async def ai_status():
    """Check AI module status and capabilities."""
    try:
        from app.ai.detector import YOLO_AVAILABLE
        import torch

        gpu_available = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if gpu_available else None

        return {
            "yolo_available": YOLO_AVAILABLE,
            "gpu_available": gpu_available,
            "gpu_name": gpu_name,
            "active_tasks": len([t for t in analysis_tasks.values() if t["status"] == "running"]),
        }
    except Exception as e:
        return {
            "yolo_available": False,
            "gpu_available": False,
            "error": str(e),
        }


@router.post("/analyze", response_model=AnalysisStatus)
async def start_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
):
    """Start background analysis of videos for a day."""
    video_paths = get_video_paths(request.channel, request.date)

    if not video_paths:
        raise HTTPException(
            status_code=404,
            detail=f"No videos found for CH{request.channel} on {request.date}",
        )

    task_id = f"analysis_{request.channel}_{request.date}"

    # Check if already running
    if task_id in analysis_tasks and analysis_tasks[task_id]["status"] == "running":
        return AnalysisStatus(
            task_id=task_id,
            status="running",
            progress=analysis_tasks[task_id].get("progress", 0),
            message="Analysis already in progress",
        )

    # Initialize task
    analysis_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "message": "Starting analysis...",
        "result": None,
    }

    # Start background task
    background_tasks.add_task(
        run_analysis,
        task_id,
        request.channel,
        request.date,
        video_paths,
        request.sample_rate,
    )

    return AnalysisStatus(
        task_id=task_id,
        status="pending",
        progress=0,
        message=f"Analysis queued for {len(video_paths)} videos",
    )


@router.get("/analyze/{task_id}", response_model=AnalysisStatus)
async def get_analysis_status(task_id: str):
    """Get status of an analysis task."""
    if task_id not in analysis_tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    task = analysis_tasks[task_id]
    return AnalysisStatus(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        message=task["message"],
        result=task.get("result"),
    )


async def run_analysis(
    task_id: str,
    channel: int,
    date: str,
    video_paths: list[Path],
    sample_rate: int,
):
    """Run video analysis in background with thumbnail extraction."""
    try:
        from app.ai.mapper import ContentMapper
        from app.ai.thumbnails import ThumbnailExtractor
        from datetime import datetime, timedelta
        import cv2

        analysis_tasks[task_id]["status"] = "running"
        analysis_tasks[task_id]["message"] = "Initializing AI models..."

        # Setup paths
        cache_dir = settings.recordings_path / ".cache"
        thumbnail_dir = cache_dir / "thumbnails"
        vectors_path = cache_dir / "vectors.json"

        mapper = ContentMapper(cache_dir=cache_dir / "ai")
        extractor = ThumbnailExtractor(output_dir=thumbnail_dir)

        def on_progress(current, total, message):
            progress = (current / total) * 100 if total > 0 else 0
            analysis_tasks[task_id]["progress"] = progress * 0.8  # 80% for analysis
            analysis_tasks[task_id]["message"] = message

        timeline = mapper.analyze_day(
            channel=channel,
            date=date,
            video_paths=video_paths,
            progress_callback=on_progress,
        )

        # Phase 2: Extract thumbnails from key detections
        analysis_tasks[task_id]["message"] = "Extracting thumbnails..."
        analysis_tasks[task_id]["progress"] = 80

        thumbnails_extracted = 0
        try:
            # Load vector store for indexing
            from app.ai.embeddings import VectorStore
            vector_store = VectorStore(vectors_path)

            # Extract thumbnails from analysis
            for i, video_path in enumerate(video_paths):
                analysis_tasks[task_id]["progress"] = 80 + (i / len(video_paths)) * 15

                # Get cached analysis for this video
                cache_path = cache_dir / "ai" / f"{Path(video_path).stem}.json"
                if not cache_path.exists():
                    continue

                import json
                with open(cache_path) as f:
                    analysis_data = json.load(f)

                # Build detection map by frame
                detections_by_frame = {}
                for fd in analysis_data.get("frame_detections", []):
                    frame_num = fd.get("frame_number", 0)
                    detections_by_frame[frame_num] = fd.get("detections", [])

                if not detections_by_frame:
                    continue

                # Parse video timestamp
                import re
                match = re.search(r'(\d{14})', Path(video_path).name)
                if match:
                    base_time = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
                else:
                    base_time = datetime.strptime(date, "%Y-%m-%d")

                fps = analysis_data.get("fps", 20)

                # Extract thumbnails for frames with people or vehicles
                cap = cv2.VideoCapture(str(video_path))
                last_extracted = {}

                for frame_num, dets in sorted(detections_by_frame.items()):
                    # Skip empty frames
                    if not dets:
                        continue

                    # Filter to people and vehicles only
                    important_dets = [d for d in dets
                                     if d.get("class_name") in ("person", "car", "truck", "bus", "motorcycle")]
                    if not important_dets:
                        continue

                    # Skip if we recently extracted from similar position
                    skip = True
                    for d in important_dets:
                        pos_key = f"{d['class_name']}_{d['center'][0]//80}_{d['center'][1]//80}"
                        if pos_key not in last_extracted or frame_num - last_extracted[pos_key] > 30:
                            skip = False
                            last_extracted[pos_key] = frame_num
                            break

                    if skip:
                        continue

                    # Read frame
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                    ret, frame = cap.read()
                    if not ret:
                        continue

                    timestamp = base_time + timedelta(seconds=frame_num / fps)

                    # Extract each detection
                    for det in important_dets:
                        bbox = det.get("bbox", [0, 0, 100, 100])
                        x1, y1, x2, y2 = bbox

                        # Skip tiny detections
                        if (x2 - x1) < 30 or (y2 - y1) < 30:
                            continue

                        # Crop with padding
                        h, w = frame.shape[:2]
                        pad = 15
                        x1 = max(0, x1 - pad)
                        y1 = max(0, y1 - pad)
                        x2 = min(w, x2 + pad)
                        y2 = min(h, y2 + pad)

                        crop = frame[y1:y2, x1:x2]
                        if crop.size == 0:
                            continue

                        # Generate ID and save
                        import hashlib
                        img_hash = hashlib.md5(crop.tobytes()).hexdigest()[:8]
                        class_name = det.get("class_name", "unknown")
                        thumb_id = f"{class_name}_{timestamp.strftime('%Y%m%d%H%M%S')}_{img_hash}"

                        # Determine category
                        if class_name == "person":
                            category = "person"
                        elif class_name in ("car", "truck", "bus", "motorcycle"):
                            category = "vehicle"
                        else:
                            continue

                        save_dir = thumbnail_dir / category
                        save_dir.mkdir(parents=True, exist_ok=True)
                        save_path = save_dir / f"{thumb_id}.jpg"

                        if not save_path.exists():
                            cv2.imwrite(str(save_path), crop)

                            # Generate CLIP embedding for visual re-identification
                            # CRITICAL FOR SAFETY: This enables finding the same person
                            # across multiple appearances (e.g., stalker detection)
                            embedding = [0.0] * 512  # Default placeholder
                            try:
                                from app.ai.embeddings import EmbeddingGenerator
                                # Use singleton pattern to avoid reloading model
                                if not hasattr(generate_embedding, '_generator'):
                                    generate_embedding._generator = EmbeddingGenerator()
                                embedding = generate_embedding._generator.embed_image(crop)
                                logger.debug(f"Generated embedding for {thumb_id}")
                            except Exception as emb_err:
                                logger.warning(f"Could not generate embedding: {emb_err}")

                            # Add to vector store with real embedding
                            vector_store.add(
                                embedding=embedding,
                                metadata={
                                    "thumbnail_id": thumb_id,
                                    "target_type": class_name,
                                    "timestamp": timestamp.isoformat(),
                                    "channel": channel,
                                    "video_path": str(video_path),
                                    "frame_number": frame_num,
                                    "bbox": bbox,
                                    "confidence": det.get("confidence", 0),
                                    "thumbnail_path": str(save_path),
                                }
                            )
                            thumbnails_extracted += 1

                cap.release()

            logger.info(f"Extracted {thumbnails_extracted} thumbnails")

        except Exception as e:
            logger.warning(f"Thumbnail extraction error: {e}")

        analysis_tasks[task_id]["status"] = "complete"
        analysis_tasks[task_id]["progress"] = 100
        analysis_tasks[task_id]["message"] = f"Analysis complete. {thumbnails_extracted} thumbnails extracted."
        analysis_tasks[task_id]["result"] = timeline.to_dict()
        analysis_tasks[task_id]["result"]["thumbnails_extracted"] = thumbnails_extracted

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        analysis_tasks[task_id]["status"] = "failed"
        analysis_tasks[task_id]["message"] = str(e)


@router.get("/timeline/{channel}/{date}", response_model=TimelineResponse)
async def get_timeline(channel: int, date: str):
    """Get the analyzed timeline for a day (must be analyzed first)."""
    task_id = f"analysis_{channel}_{date}"

    if task_id not in analysis_tasks:
        raise HTTPException(
            status_code=404,
            detail="Day not analyzed yet. POST to /api/ai/analyze first.",
        )

    task = analysis_tasks[task_id]
    if task["status"] != "complete":
        raise HTTPException(
            status_code=202,
            detail=f"Analysis in progress: {task['status']} - {task['message']}",
        )

    result = task["result"]
    return TimelineResponse(
        date=result["date"],
        channel=result["channel"],
        events=result["events"],
        total_people=result["total_people"],
        total_vehicles=result["total_vehicles"],
        active_hours=result["active_hours"],
        peak_hour=result["peak_hour"],
    )


@router.post("/hyperlapse/{channel}/{date}")
async def generate_hyperlapse(
    channel: int,
    date: str,
    interval: float = Query(60.0, description="Sample interval in seconds"),
    duration: float = Query(60.0, description="Target output duration in seconds"),
):
    """Generate a hyperlapse video for a day."""
    video_paths = get_video_paths(channel, date)

    if not video_paths:
        raise HTTPException(status_code=404, detail="No videos found")

    try:
        from app.ai.mapper import ContentMapper

        output_dir = settings.recordings_path / ".cache" / "hyperlapse"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"hyperlapse_ch{channel}_{date}.mp4"

        mapper = ContentMapper()
        result_path = mapper.generate_hyperlapse(
            video_paths=video_paths,
            output_path=output_path,
            interval_seconds=interval,
            target_duration=duration,
        )

        return {
            "status": "success",
            "path": str(result_path),
            "url": f"/api/ai/hyperlapse/{channel}/{date}/video",
        }
    except Exception as e:
        logger.error(f"Hyperlapse generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/hyperlapse/{channel}/{date}/video")
async def get_hyperlapse_video(channel: int, date: str):
    """Stream the generated hyperlapse video."""
    from fastapi.responses import FileResponse

    video_path = settings.recordings_path / ".cache" / "hyperlapse" / f"hyperlapse_ch{channel}_{date}.mp4"

    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Hyperlapse not generated yet")

    return FileResponse(video_path, media_type="video/mp4")


@router.post("/compression/{channel}/{date}")
async def analyze_compression(channel: int, date: str):
    """Analyze videos for compression opportunities."""
    task_id = f"analysis_{channel}_{date}"

    if task_id not in analysis_tasks or analysis_tasks[task_id]["status"] != "complete":
        raise HTTPException(
            status_code=400,
            detail="Run analysis first with POST /api/ai/analyze",
        )

    # For now, return summary from timeline
    result = analysis_tasks[task_id]["result"]
    total_duration = sum(e.get("duration_seconds", 0) for e in result["events"])
    active_duration = total_duration

    # Rough estimate: 5MB per minute at 1080p
    video_paths = get_video_paths(channel, date)
    total_size_mb = sum(p.stat().st_size / (1024 * 1024) for p in video_paths)

    return {
        "channel": channel,
        "date": date,
        "total_videos": len(video_paths),
        "total_size_mb": round(total_size_mb, 1),
        "active_segments": len(result["events"]),
        "active_duration_seconds": round(active_duration, 1),
        "potential_savings_percent": round((1 - active_duration / (24 * 3600)) * 100, 1) if active_duration else 100,
        "recommendation": "Run detailed compression analysis for specific candidates",
    }


@router.get("/detect/frame/{channel}/{date}/{filename}")
async def detect_single_frame(
    channel: int,
    date: str,
    filename: str,
    frame: int = Query(0, description="Frame number to analyze"),
):
    """Run detection on a single frame from a video."""
    video_paths = get_video_paths(channel, date)
    video_path = next((p for p in video_paths if p.name == filename), None)

    if not video_path:
        raise HTTPException(status_code=404, detail="Video not found")

    try:
        import cv2
        from app.ai.detector import ObjectDetector

        detector = ObjectDetector()

        cap = cv2.VideoCapture(str(video_path))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ret, frame_data = cap.read()
        cap.release()

        if not ret:
            raise HTTPException(status_code=400, detail="Could not read frame")

        detections = detector.detect_frame(frame_data, frame)

        return {
            "frame_number": frame,
            "detections": [d.to_dict() for d in detections.detections],
            "people_count": detections.people_count,
            "vehicle_count": detections.vehicle_count,
        }
    except Exception as e:
        logger.error(f"Detection failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
