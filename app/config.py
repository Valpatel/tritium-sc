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
    recordings_path: Path = Path("/mnt/nvme-raid5/mvalancy/sec-cameras")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # go2rtc integration (Phase 2)
    go2rtc_url: str = "http://localhost:1984"

    # MQTT (Phase 4)
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "tritium"

    # Ollama (Phase 5)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llava:13b"

    # Amy AI Commander
    amy_enabled: bool = True
    amy_camera_device: str | None = None    # auto-detect BCC950
    amy_deep_model: str = "llava:7b"
    amy_chat_model: str = "gemma3:4b"
    amy_whisper_model: str = "large-v3"
    amy_tts_enabled: bool = True
    amy_wake_word: str = "amy"
    amy_think_interval: float = 8.0

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
