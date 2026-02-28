"""Configuration management using Pydantic settings."""

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore extra fields like NVR_HOST, etc.
    )

    # Application
    app_name: str = "TRITIUM"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./tritium.db"

    # Recordings path (where synced footage lives)
    recordings_path: Path = Path("./data/recordings")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # go2rtc integration (Phase 2)
    go2rtc_url: str = "http://localhost:1984"

    # MQTT distributed bus — foundational infrastructure (always available)
    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_site_id: str = "home"
    mqtt_username: str = ""
    mqtt_password: str = ""

    # Meshtastic mesh radio
    meshtastic_enabled: bool = False
    meshtastic_host: str = ""           # auto-discover if empty
    meshtastic_port: int = 4403

    # MeshCore mesh radio (serial USB)
    meshcore_enabled: bool = False
    meshcore_serial_port: str = ""      # e.g. "/dev/ttyUSB0"

    # Mesh web source (public mesh network maps)
    mesh_web_enabled: bool = False
    mesh_web_poll_interval: int = 60    # seconds
    mesh_web_url: str = ""              # JSON endpoint returning mesh node list

    # InfluxDB v2 time-series store
    influx_enabled: bool = True
    influx_url: str = "http://localhost:8086"
    influx_token: str = "tritium-dev-token"
    influx_org: str = "tritium"
    influx_bucket: str = "telemetry"

    # Ollama (Phase 5)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llava:13b"

    # Geo engine
    geo_cache_dir: str = "~/.cache/tritium-sc"

    # Geo reference — real-world origin for the local coordinate system.
    # Set from geocoding or manually.  All simulation/target coordinates
    # are meters from this point.  (0, 0) local = (lat, lng) real.
    map_center_lat: float = 37.7159
    map_center_lng: float = -121.8960
    map_center_alt: float = 16.0  # meters above sea level

    # Simulation engine
    simulation_enabled: bool = True
    simulation_layout: str = "scenarios/neighborhood_default.json"
    simulation_mode: str = "sim"  # "sim" or "live" — controls Amy's tactical data source
    simulation_bounds: float = 200.0  # Half-extent in meters (±200 = 400m x 400m)
    simulation_max_hostiles: int = 200  # Maximum simultaneous hostile targets

    # Plugin system
    plugins_dir: str = "plugins"              # Directory for drop-in plugins
    plugins_enabled: bool = True              # Enable plugin discovery and loading

    # NPC world population
    npc_enabled: bool = True
    npc_max_vehicles: int = 150      # Peak vehicle count (scaled by time-of-day)
    npc_max_pedestrians: int = 200   # Peak pedestrian count (scaled by time-of-day)

    # Amy AI Commander
    amy_enabled: bool = True
    amy_camera_device: str | None = None    # auto-detect BCC950
    amy_deep_model: str = "llava:7b"
    amy_chat_model: str = "gemma3:4b"
    amy_whisper_model: str = "large-v3"
    amy_tts_enabled: bool = True
    amy_wake_word: str = "amy"
    amy_think_interval: float = 8.0

    # Fleet / Model routing
    fleet_enabled: bool = False       # opt-in; False = existing static behavior
    fleet_auto_discover: bool = True  # Tailscale peer scan when fleet_enabled

    # Escalation thresholds
    escalation_linger_threshold: float = 30.0
    escalation_deescalation_time: float = 30.0
    escalation_min_battery: float = 0.20

    # Detection settings
    motion_threshold: float = 25.0
    detection_confidence: float = 0.5
    yolo_model: str = "yolov8n.pt"

    # NVR settings
    nvr_host: Optional[str] = None
    nvr_user: Optional[str] = None
    nvr_pass: Optional[str] = None
    nvr_port: int = 443


settings = Settings()
