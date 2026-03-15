# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Weather API router — proxy Open-Meteo for current weather conditions.

Fetches current weather for a given lat/lng from Open-Meteo (free, no API
key needed) and returns it in a format suitable for the map weather widget.

Open-Meteo documentation: https://open-meteo.com/en/docs
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import APIRouter, Query

logger = logging.getLogger("weather")

router = APIRouter(prefix="/api/weather", tags=["weather"])

# Simple in-memory cache to avoid hammering the API
_cache: dict[str, dict] = {}
_CACHE_TTL = 600  # 10 minutes


# WMO Weather interpretation codes -> human readable
WMO_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}

# WMO code to icon mapping (emoji-free, using simple text codes)
WMO_ICONS: dict[int, str] = {
    0: "sun",
    1: "sun_cloud",
    2: "cloud_sun",
    3: "cloud",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    56: "freezing",
    57: "freezing",
    61: "rain",
    63: "rain",
    65: "rain_heavy",
    66: "freezing",
    67: "freezing",
    71: "snow",
    73: "snow",
    75: "snow_heavy",
    77: "snow",
    80: "rain",
    81: "rain",
    82: "rain_heavy",
    85: "snow",
    86: "snow_heavy",
    95: "thunder",
    96: "thunder",
    99: "thunder",
}


def _cache_key(lat: float, lng: float) -> str:
    """Round to 2 decimal places for cache key (same city)."""
    return f"{lat:.2f},{lng:.2f}"


@router.get("/current")
async def get_current_weather(
    lat: float = Query(..., description="Latitude"),
    lng: float = Query(..., description="Longitude"),
) -> dict:
    """Fetch current weather for given coordinates.

    Uses Open-Meteo free API (no key needed). Results cached for 10 minutes.

    Returns:
        {
            "temperature_c": 22.5,
            "temperature_f": 72.5,
            "wind_speed_kmh": 15.2,
            "wind_speed_mph": 9.4,
            "wind_direction": 225,
            "humidity": 45,
            "weather_code": 2,
            "weather_desc": "Partly cloudy",
            "weather_icon": "cloud_sun",
            "is_day": true,
            "lat": 40.71,
            "lng": -74.01,
            "cached": false,
            "timestamp": 1710000000
        }
    """
    key = _cache_key(lat, lng)

    # Check cache
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry.get("_fetched_at", 0) < _CACHE_TTL:
            result = dict(entry)
            result.pop("_fetched_at", None)
            result["cached"] = True
            return result

    # Fetch from Open-Meteo
    try:
        import httpx
    except ImportError:
        return {
            "error": "httpx not installed",
            "temperature_c": None,
            "temperature_f": None,
            "weather_desc": "Weather unavailable",
            "weather_icon": "unknown",
        }

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m,is_day",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        current = data.get("current", {})
        temp_c = current.get("temperature_2m")
        temp_f = temp_c * 9 / 5 + 32 if temp_c is not None else None
        wind_kmh = current.get("wind_speed_10m", 0)
        wind_mph = wind_kmh * 0.621371 if wind_kmh else 0
        weather_code = current.get("weather_code", 0)

        result = {
            "temperature_c": temp_c,
            "temperature_f": round(temp_f, 1) if temp_f is not None else None,
            "wind_speed_kmh": wind_kmh,
            "wind_speed_mph": round(wind_mph, 1),
            "wind_direction": current.get("wind_direction_10m", 0),
            "humidity": current.get("relative_humidity_2m"),
            "weather_code": weather_code,
            "weather_desc": WMO_CODES.get(weather_code, "Unknown"),
            "weather_icon": WMO_ICONS.get(weather_code, "unknown"),
            "is_day": bool(current.get("is_day", 1)),
            "lat": lat,
            "lng": lng,
            "cached": False,
            "timestamp": int(time.time()),
        }

        # Cache it
        _cache[key] = {**result, "_fetched_at": time.time()}

        return result

    except Exception as exc:
        logger.warning("Weather fetch failed: %s", exc)
        return {
            "error": str(exc),
            "temperature_c": None,
            "temperature_f": None,
            "weather_desc": "Weather unavailable",
            "weather_icon": "unknown",
            "lat": lat,
            "lng": lng,
            "cached": False,
            "timestamp": int(time.time()),
        }
