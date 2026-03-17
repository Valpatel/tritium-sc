# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for HackRF persistent data store."""

import asyncio
import json
import time

import pytest
import pytest_asyncio

from addons.hackrf.hackrf_addon.data_store import HackRFDataStore


@pytest_asyncio.fixture
async def store(tmp_path):
    """Create a temporary data store for testing."""
    db_path = str(tmp_path / "test_hackrf.db")
    s = HackRFDataStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_store_and_query_sweep(store):
    """Store a spectrum sweep and retrieve it."""
    sweep = {
        "freq_start_hz": 88_000_000,
        "freq_end_hz": 108_000_000,
        "bin_width": 500_000,
        "data": [
            {"freq_hz": 88_000_000, "power_dbm": -40.0},
            {"freq_hz": 89_000_000, "power_dbm": -35.0},
            {"freq_hz": 90_000_000, "power_dbm": -50.0},
        ],
    }
    await store.store_sweep(sweep)

    history = await store.get_spectrum_history()
    assert len(history) == 1
    assert history[0]["freq_start_hz"] == 88_000_000
    assert len(history[0]["data"]) == 3
    assert history[0]["data"][1]["power_dbm"] == -35.0


@pytest.mark.asyncio
async def test_store_signal_upsert(store):
    """Signal detections are upserted by frequency."""
    await store.store_signal(433_000_000, -25.0, "ISM 433")
    await store.store_signal(433_000_000, -20.0, "ISM 433")
    await store.store_signal(433_000_000, -18.0, "ISM 433")

    signals = await store.get_all_signals()
    assert len(signals) == 1
    assert signals[0]["freq_hz"] == 433_000_000
    assert signals[0]["power_dbm"] == -18.0  # Latest value
    assert signals[0]["detection_count"] == 3


@pytest.mark.asyncio
async def test_store_device(store):
    """Store and retrieve decoded devices."""
    await store.store_device({
        "protocol": "LaCrosse-TX",
        "model": "TX141W",
        "device_id": "42",
        "freq_hz": 433_920_000,
        "temperature_C": 22.5,
        "humidity": 65,
    })

    devices = await store.get_all_devices()
    assert len(devices) == 1
    assert devices[0]["protocol"] == "LaCrosse-TX"
    assert devices[0]["model"] == "TX141W"
    assert devices[0]["device_id"] == "42"
    assert devices[0]["last_data"]["temperature_C"] == 22.5


@pytest.mark.asyncio
async def test_device_upsert_increments_count(store):
    """Storing the same device multiple times increments event_count."""
    for i in range(5):
        await store.store_device({
            "protocol": "Acurite",
            "device_id": "1234",
            "temperature_C": 20.0 + i,
        })

    devices = await store.get_all_devices()
    assert len(devices) == 1
    assert devices[0]["event_count"] == 5
    assert devices[0]["last_data"]["temperature_C"] == 24.0


@pytest.mark.asyncio
async def test_device_history(store):
    """Get device history by device_id."""
    await store.store_device({"protocol": "X10", "device_id": "abc", "freq_hz": 315_000_000})
    await store.store_device({"protocol": "TPMS", "device_id": "xyz", "freq_hz": 315_000_000})

    history = await store.get_device_history("abc")
    assert len(history) == 1
    assert history[0]["protocol"] == "X10"

    history2 = await store.get_device_history("nonexistent")
    assert len(history2) == 0


@pytest.mark.asyncio
async def test_store_tpms(store):
    """Store and retrieve TPMS sensor data."""
    await store.store_tpms({
        "sensor_id": "AABB1234",
        "vehicle_hash": "car_01",
        "pressure_psi": 32.5,
        "temperature_c": 28.0,
    })

    sensors = await store.get_tpms_sensors()
    assert len(sensors) == 1
    assert sensors[0]["sensor_id"] == "AABB1234"
    assert sensors[0]["pressure_psi"] == 32.5
    assert sensors[0]["vehicle_hash"] == "car_01"


@pytest.mark.asyncio
async def test_tpms_upsert(store):
    """TPMS sensors are upserted by sensor_id."""
    await store.store_tpms({"sensor_id": "S1", "pressure_psi": 30.0})
    await store.store_tpms({"sensor_id": "S1", "pressure_psi": 31.5, "temperature_c": 25.0})

    sensors = await store.get_tpms_sensors()
    assert len(sensors) == 1
    assert sensors[0]["pressure_psi"] == 31.5
    assert sensors[0]["temperature_c"] == 25.0


@pytest.mark.asyncio
async def test_store_aircraft(store):
    """Store and retrieve ADS-B aircraft."""
    await store.store_aircraft({
        "icao": "a1b2c3",
        "callsign": "UAL123",
        "alt": 35000,
        "lat": 40.7128,
        "lng": -74.0060,
        "speed": 450,
    })

    aircraft = await store.get_aircraft_tracks()
    assert len(aircraft) == 1
    assert aircraft[0]["icao"] == "a1b2c3"
    assert aircraft[0]["callsign"] == "UAL123"
    assert aircraft[0]["last_alt"] == 35000
    assert aircraft[0]["last_lat"] == pytest.approx(40.7128)


@pytest.mark.asyncio
async def test_aircraft_upsert(store):
    """Aircraft are upserted by ICAO."""
    await store.store_aircraft({"icao": "abc123", "callsign": "DAL456", "alt": 30000})
    await store.store_aircraft({"icao": "abc123", "alt": 32000, "speed": 500})

    aircraft = await store.get_aircraft_tracks(icao="abc123")
    assert len(aircraft) == 1
    assert aircraft[0]["callsign"] == "DAL456"  # Preserved from first insert
    assert aircraft[0]["last_alt"] == 32000  # Updated
    assert aircraft[0]["last_speed"] == 500


@pytest.mark.asyncio
async def test_rf_environment_snapshot(store):
    """Store and retrieve RF environment snapshots."""
    await store.store_rf_snapshot("ISM 433", avg_power_dbm=-60.0, peak_power_dbm=-25.0, peak_freq_hz=433_920_000)
    await store.store_rf_snapshot("WiFi 2.4GHz", avg_power_dbm=-50.0, peak_power_dbm=-20.0, peak_freq_hz=2_437_000_000)

    history = await store.get_rf_environment_history()
    assert len(history) == 2

    ism_history = await store.get_rf_environment_history(band_name="ISM 433")
    assert len(ism_history) == 1
    assert ism_history[0]["peak_power_dbm"] == -25.0


@pytest.mark.asyncio
async def test_spectrum_history_frequency_filter(store):
    """Filter spectrum history by frequency range."""
    await store.store_sweep({"freq_start_hz": 88_000_000, "freq_end_hz": 108_000_000, "bin_width": 500_000, "data": []})
    await store.store_sweep({"freq_start_hz": 433_000_000, "freq_end_hz": 434_000_000, "bin_width": 100_000, "data": []})

    fm_only = await store.get_spectrum_history(freq_start=80_000_000, freq_end=200_000_000)
    assert len(fm_only) == 1
    assert fm_only[0]["freq_start_hz"] == 88_000_000


@pytest.mark.asyncio
async def test_signal_min_power_filter(store):
    """Filter signals by minimum power."""
    await store.store_signal(100_000_000, -80.0, "FM")
    await store.store_signal(200_000_000, -20.0, "ISM")
    await store.store_signal(300_000_000, -50.0, "UHF")

    strong = await store.get_all_signals(min_power=-30.0)
    assert len(strong) == 1
    assert strong[0]["freq_hz"] == 200_000_000


@pytest.mark.asyncio
async def test_signal_trend(store):
    """Get signal trend for a frequency."""
    await store.store_signal(433_920_000, -30.0, "ISM 433")

    trend = await store.get_signal_trend(433_920_000)
    assert len(trend) == 1
    assert trend[0]["freq_hz"] == 433_920_000

    # Non-existent frequency
    empty = await store.get_signal_trend(999_999_999)
    assert len(empty) == 0


@pytest.mark.asyncio
async def test_empty_store_returns_empty(store):
    """Querying empty store returns empty results."""
    assert await store.get_all_signals() == []
    assert await store.get_all_devices() == []
    assert await store.get_tpms_sensors() == []
    assert await store.get_aircraft_tracks() == []
    assert await store.get_spectrum_history() == []
    assert await store.get_rf_environment_history() == []
    assert await store.get_device_history("nonexistent") == []
    assert await store.get_signal_trend(0) == []
