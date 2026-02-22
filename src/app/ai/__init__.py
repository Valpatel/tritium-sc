"""TRITIUM-SC AI Content Mapping Module.

Provides intelligent video analysis including:
- Object detection (YOLO)
- Activity timeline mapping
- Hyperlapse generation
- People/vehicle overlay compositing
- Content-aware compression analysis
"""

from app.ai.detector import ObjectDetector
from app.ai.analyzer import VideoAnalyzer
from app.ai.mapper import ContentMapper

__all__ = ["ObjectDetector", "VideoAnalyzer", "ContentMapper"]
