"""SQLAlchemy models for SENTINEL."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Camera(Base):
    """Camera/channel configuration."""

    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    rtsp_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    substream_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    events: Mapped[list["Event"]] = relationship(back_populates="camera")
    zones: Mapped[list["Zone"]] = relationship(back_populates="camera")
    transcripts: Mapped[list["Transcript"]] = relationship(back_populates="camera")


class Event(Base):
    """Detection events (motion, person, vehicle, etc.)."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(index=True)
    end_timestamp: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    bbox_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    video_clip_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zones_triggered: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    camera: Mapped["Camera"] = relationship(back_populates="events")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="event")


class Zone(Base):
    """Detection zones (polygons on camera view)."""

    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    polygon_json: Mapped[str] = mapped_column(Text)
    zone_type: Mapped[str] = mapped_column(String(50))  # perimeter, restricted, counting_line
    alert_on: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON array
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    camera: Mapped["Camera"] = relationship(back_populates="zones")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="zone")


class Alert(Base):
    """Alert delivery log."""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("zones.id"), nullable=True)
    delivery_method: Mapped[str] = mapped_column(String(50))  # ui, webhook, mqtt
    delivered_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship(back_populates="alerts")
    zone: Mapped[Optional["Zone"]] = relationship(back_populates="alerts")


class Transcript(Base):
    """Audio transcripts from footage."""

    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    start_time: Mapped[datetime] = mapped_column()
    end_time: Mapped[datetime] = mapped_column()
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Relationships
    camera: Mapped["Camera"] = relationship(back_populates="transcripts")


class Setting(Base):
    """System settings key-value store."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Asset(Base):
    """Autonomous operational assets (ground/aerial units).

    Assets are controllable units that can be tasked with various operations
    like patrol, tracking, engagement, etc.
    """

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # e.g., "UNIT-01"
    name: Mapped[str] = mapped_column(String(100))  # e.g., "Perimeter Guardian Alpha"
    asset_type: Mapped[str] = mapped_column(String(50))  # ground, aerial, fixed
    asset_class: Mapped[str] = mapped_column(String(50))  # patrol, interceptor, observation, transport
    status: Mapped[str] = mapped_column(String(50), default="standby")  # standby, active, tasked, returning, maintenance, offline
    battery_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100
    ammo_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-100 (for units with effectors)
    position_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Property-relative X
    position_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Property-relative Y
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # 0-360 degrees
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Current speed
    home_x: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Home/charging position
    home_y: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    capabilities: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: ["patrol", "track", "engage"]
    connection_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Control endpoint
    camera_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # Onboard camera stream
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    tasks: Mapped[list["AssetTask"]] = relationship(back_populates="asset")
    telemetry: Mapped[list["AssetTelemetry"]] = relationship(back_populates="asset")


class AssetTask(Base):
    """Tasks assigned to assets.

    Task types:
    - PATROL: Follow waypoints in loop
    - TRACK: Follow a specific target
    - ENGAGE: Move to and engage target
    - LOITER: Hold position, observe
    - RECALL: Return to home/base
    - REARM: Return for resupply
    - INVESTIGATE: Go to location, report
    """

    __tablename__ = "asset_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    task_type: Mapped[str] = mapped_column(String(50))  # patrol, track, engage, loiter, recall, rearm, investigate
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 (highest) - 10 (lowest)
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, active, completed, cancelled, failed
    target_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # person, vehicle, zone
    target_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)  # ID of target
    waypoints_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON: [[x,y], [x,y], ...]
    parameters_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Task-specific params
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Outcome description
    created_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, server_default=text("CURRENT_TIMESTAMP")
    )

    # Relationships
    asset: Mapped["Asset"] = relationship(back_populates="tasks")


class AssetTelemetry(Base):
    """Asset telemetry/position history."""

    __tablename__ = "asset_telemetry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(index=True)
    position_x: Mapped[float] = mapped_column(Float)
    position_y: Mapped[float] = mapped_column(Float)
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    battery_level: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    asset: Mapped["Asset"] = relationship(back_populates="telemetry")
