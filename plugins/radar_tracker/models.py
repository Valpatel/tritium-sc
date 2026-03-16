# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Pydantic models for radar tracker plugin API requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RadarConfigRequest(BaseModel):
    """Request body for configuring a radar unit's position and settings."""

    radar_id: str
    lat: float
    lng: float
    altitude_m: float = 0.0
    orientation_deg: float = 0.0  # boresight direction, degrees from north
    max_range_m: float = 20000.0
    min_range_m: float = 50.0
    name: str = ""
    enabled: bool = True


class RadarTrackResponse(BaseModel):
    """A single radar track for API responses."""

    track_id: str
    radar_id: str
    range_m: float
    azimuth_deg: float
    elevation_deg: float = 0.0
    velocity_mps: float = 0.0
    rcs_dbsm: float = 0.0
    classification: str = "unknown"
    confidence: float = 1.0
    lat: float = 0.0
    lng: float = 0.0
    timestamp: float = 0.0
    target_id: str = ""


class RadarStatusResponse(BaseModel):
    """Status of the radar tracker system."""

    radars: list[dict] = Field(default_factory=list)
    total_tracks: int = 0
    running: bool = False


class PPIDataResponse(BaseModel):
    """PPI scope data for frontend rendering."""

    radar_id: str
    lat: float
    lng: float
    orientation_deg: float = 0.0
    max_range_m: float = 20000.0
    tracks: list[dict] = Field(default_factory=list)
    sweep_angle_deg: float = 0.0  # current antenna position
    timestamp: float = 0.0
