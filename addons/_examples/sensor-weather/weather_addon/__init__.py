# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Weather station sensor addon example.

Fetches current weather from wttr.in (free, no API key) and creates
a weather-station target at the configured lat/lng with temperature
and conditions in its properties.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any
from urllib.request import urlopen, Request
from urllib.error import URLError

from tritium_lib.sdk import SensorAddon, AddonInfo

log = logging.getLogger("addon.sensor-weather")


class WeatherAddon(SensorAddon):
    """Fetches weather and publishes a weather-station target."""

    info = AddonInfo(
        id="sensor-weather",
        name="Weather Station",
        version="1.0.0",
        description="Current weather from wttr.in as a map target",
        author="Valpatel Software LLC",
        category="sensors",
    )

    def __init__(self):
        super().__init__()
        self._location: str = "San Francisco"
        self._latitude: float = 37.7749
        self._longitude: float = -122.4194
        self._poll_interval: int = 300
        self._last_weather: dict | None = None
        self._last_fetch: float = 0.0
        self._poll_task: asyncio.Task | None = None

    async def register(self, app: Any) -> None:
        await super().register(app)

        # Read config from app if available
        config = getattr(app, "config", None)
        if config and hasattr(config, "get"):
            self._location = config.get("location", self._location)
            self._latitude = float(config.get("latitude", self._latitude))
            self._longitude = float(config.get("longitude", self._longitude))
            self._poll_interval = int(config.get("poll_interval", self._poll_interval))

        # Start background polling
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._background_tasks.append(self._poll_task)
        log.info(f"Weather addon registered for {self._location}")

    async def unregister(self, app: Any) -> None:
        self._last_weather = None
        await super().unregister(app)
        log.info("Weather addon unregistered")

    async def gather(self) -> list[dict]:
        """Return the weather station target with current conditions."""
        if self._last_weather is None:
            return []

        w = self._last_weather
        return [{
            "target_id": "weather-station",
            "source": "weather",
            "name": f"Weather - {self._location}",
            "asset_type": "weather_station",
            "alliance": "neutral",
            "lat": self._latitude,
            "lng": self._longitude,
            "position": {"lat": self._latitude, "lng": self._longitude},
            "properties": {
                "temperature_c": w.get("temp_C"),
                "temperature_f": w.get("temp_F"),
                "feels_like_c": w.get("FeelsLikeC"),
                "humidity": w.get("humidity"),
                "wind_speed_kmph": w.get("windspeedKmph"),
                "wind_dir": w.get("winddir16Point"),
                "conditions": w.get("weatherDesc", [{}])[0].get("value", "Unknown"),
                "visibility_km": w.get("visibility"),
                "pressure_mb": w.get("pressure"),
                "cloud_cover": w.get("cloudcover"),
                "uv_index": w.get("uvIndex"),
            },
            "last_seen": self._last_fetch,
        }]

    def fetch_weather_sync(self, location: str | None = None) -> dict | None:
        """Fetch weather from wttr.in synchronously. Returns parsed JSON or None."""
        loc = location or self._location
        url = f"https://wttr.in/{loc}?format=j1"
        try:
            req = Request(url, headers={"User-Agent": "tritium-weather-addon/1.0"})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            # Extract current conditions
            current = data.get("current_condition", [{}])[0]
            return current
        except (URLError, json.JSONDecodeError, KeyError, IndexError) as e:
            log.warning(f"Weather fetch failed: {e}")
            return None

    async def _fetch_weather(self) -> dict | None:
        """Fetch weather in a thread to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.fetch_weather_sync)

    async def _poll_loop(self) -> None:
        """Background loop that fetches weather on the configured interval."""
        while self._registered:
            try:
                result = await self._fetch_weather()
                if result:
                    self._last_weather = result
                    self._last_fetch = time.time()
                    log.info(
                        f"Weather update: {result.get('temp_C', '?')}C, "
                        f"{(result.get('weatherDesc', [{}])[0]).get('value', '?')}"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning(f"Weather poll error: {e}")
            await asyncio.sleep(self._poll_interval)

    def get_panels(self) -> list[dict]:
        return [{
            "id": "weather-current",
            "title": "WEATHER",
            "file": "weather-panel.js",
            "category": "sensors",
            "tab_order": 50,
        }]

    def health_check(self) -> dict:
        if not self._registered:
            return {"status": "not_registered"}
        if self._last_weather is None:
            return {"status": "degraded", "detail": "No weather data yet"}
        age = time.time() - self._last_fetch
        if age > self._poll_interval * 3:
            return {"status": "degraded", "detail": f"Stale data ({int(age)}s old)"}
        return {
            "status": "ok",
            "location": self._location,
            "last_fetch_age_s": int(age),
        }
