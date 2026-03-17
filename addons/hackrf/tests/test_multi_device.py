# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for multi-device HackRF support via DeviceRegistry."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from hackrf_addon.device import HackRFDevice, detect_all_hackrfs
from tritium_lib.sdk import DeviceRegistry, DeviceState, SubprocessManager


# -- Sample hackrf_info outputs -----------------------------------------------

SINGLE_DEVICE_OUTPUT = """hackrf_info version: 2024.02.1
libhackrf version: 2024.02.1 (0.9)
Found HackRF
Index: 0
Serial number: 0000000000000000 c66c63dc308d3d83
Board ID Number: 2 (HackRF One)
Firmware Version: 2024.02.1 (API version 1.08)
Part ID Number: 0xa000cb3c 0x00724f61
Hardware Revision: r9
Hardware appears to have been manufactured by Great Scott Gadgets.
Hardware supported by installed firmware.
"""

MULTI_DEVICE_OUTPUT = """hackrf_info version: 2024.02.1
libhackrf version: 2024.02.1 (0.9)
Found HackRF
Index: 0
Serial number: 0000000000000000 c66c63dc308d3d83
Board ID Number: 2 (HackRF One)
Firmware Version: 2024.02.1 (API version 1.08)
Part ID Number: 0xa000cb3c 0x00724f61
Hardware Revision: r9
Hardware appears to have been manufactured by Great Scott Gadgets.
Hardware supported by installed firmware.

Found HackRF
Index: 1
Serial number: 0000000000000000 aabbccdd11223344
Board ID Number: 2 (HackRF One)
Firmware Version: 2024.02.1 (API version 1.08)
Part ID Number: 0xb111dd4e 0x00835f72
Hardware Revision: r9
Hardware appears to have been manufactured by Great Scott Gadgets.
Hardware supported by installed firmware.
"""

NO_DEVICE_OUTPUT = """hackrf_info version: 2024.02.1
libhackrf version: 2024.02.1 (0.9)
No HackRF boards found.
"""


# -- detect_all_hackrfs tests -------------------------------------------------

class TestDetectAllHackrfs:
    """Tests for the detect_all_hackrfs() function."""

    @pytest.mark.asyncio
    @patch("shutil.which", return_value=None)
    async def test_no_binary(self, mock_which):
        result = await detect_all_hackrfs()
        assert result == []

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/hackrf_info")
    @patch("asyncio.create_subprocess_exec")
    async def test_single_device(self, mock_exec, mock_which):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (SINGLE_DEVICE_OUTPUT.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        devices = await detect_all_hackrfs()
        assert len(devices) == 1
        dev = devices[0]
        assert dev["device_id"] == "hackrf-308d3d83"
        assert dev["index"] == 0
        assert "c66c63dc308d3d83" in dev["serial"]
        assert dev["firmware_version"] == "2024.02.1"

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/hackrf_info")
    @patch("asyncio.create_subprocess_exec")
    async def test_multi_device(self, mock_exec, mock_which):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (MULTI_DEVICE_OUTPUT.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        devices = await detect_all_hackrfs()
        assert len(devices) == 2
        assert devices[0]["device_id"] == "hackrf-308d3d83"
        assert devices[0]["index"] == 0
        assert devices[1]["device_id"] == "hackrf-11223344"
        assert devices[1]["index"] == 1

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/hackrf_info")
    @patch("asyncio.create_subprocess_exec")
    async def test_no_devices_found(self, mock_exec, mock_which):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (NO_DEVICE_OUTPUT.encode(), b"")
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        devices = await detect_all_hackrfs()
        assert devices == []

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/hackrf_info")
    @patch("asyncio.create_subprocess_exec")
    async def test_process_failure(self, mock_exec, mock_which):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"USB error")
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        devices = await detect_all_hackrfs()
        assert devices == []

    @pytest.mark.asyncio
    @patch("shutil.which", return_value="/usr/bin/hackrf_info")
    @patch("asyncio.create_subprocess_exec", side_effect=asyncio.TimeoutError)
    async def test_timeout(self, mock_exec, mock_which):
        devices = await detect_all_hackrfs()
        assert devices == []


# -- HackRFDevice.serial_short tests ------------------------------------------

class TestSerialShort:
    """Tests for the serial_short property."""

    def test_no_info(self):
        dev = HackRFDevice()
        assert dev.serial_short == ""

    def test_with_serial(self):
        dev = HackRFDevice()
        dev._info = {"serial": "0000000000000000 c66c63dc308d3d83"}
        assert dev.serial_short == "308d3d83"

    def test_short_serial(self):
        dev = HackRFDevice()
        dev._info = {"serial": "abcd1234"}
        assert dev.serial_short == "abcd1234"

    def test_empty_serial(self):
        dev = HackRFDevice()
        dev._info = {"serial": ""}
        assert dev.serial_short == ""


# -- DeviceRegistry integration tests -----------------------------------------

class TestDeviceRegistryIntegration:
    """Tests for DeviceRegistry usage with HackRF devices."""

    def test_add_and_list_devices(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-308d3d83", "hackrf", transport_type="local",
                            metadata={"serial": "c66c63dc308d3d83"})
        registry.add_device("hackrf-11223344", "hackrf", transport_type="local",
                            metadata={"serial": "aabbccdd11223344"})

        devices = registry.list_devices()
        assert len(devices) == 2
        assert registry.device_count == 2

    def test_get_device(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-abc", "hackrf", transport_type="local")
        dev = registry.get_device("hackrf-abc")
        assert dev is not None
        assert dev.device_id == "hackrf-abc"
        assert dev.device_type == "hackrf"

    def test_get_nonexistent(self):
        registry = DeviceRegistry("hackrf")
        assert registry.get_device("nope") is None

    def test_set_state(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-abc", "hackrf", transport_type="local")
        registry.set_state("hackrf-abc", DeviceState.CONNECTED)
        dev = registry.get_device("hackrf-abc")
        assert dev.state == DeviceState.CONNECTED

    def test_connected_count(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-a", "hackrf", transport_type="local")
        registry.add_device("hackrf-b", "hackrf", transport_type="local")
        registry.set_state("hackrf-a", DeviceState.CONNECTED)
        assert registry.connected_count == 1

    def test_to_dict(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-a", "hackrf", transport_type="local")
        d = registry.to_dict()
        assert d["addon_id"] == "hackrf"
        assert d["device_count"] == 1
        assert "hackrf-a" in d["devices"]

    def test_duplicate_device_raises(self):
        registry = DeviceRegistry("hackrf")
        registry.add_device("hackrf-a", "hackrf", transport_type="local")
        with pytest.raises(ValueError):
            registry.add_device("hackrf-a", "hackrf", transport_type="local")


# -- Router multi-device endpoint tests ----------------------------------------

class TestMultiDeviceRouterEndpoints:
    """Tests for the /devices/* API routes."""

    @pytest.fixture
    def app_client(self):
        """Create a test client with a router that has registry + device instances."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from hackrf_addon.router import create_router
        from hackrf_addon.spectrum import SpectrumAnalyzer
        from hackrf_addon.receiver import FMReceiver
        from hackrf_addon.signal_db import SignalDatabase
        from hackrf_addon.radio_lock import RadioLock

        registry = DeviceRegistry("hackrf")
        dev1 = HackRFDevice()
        dev1._info = {"serial": "c66c63dc308d3d83", "firmware_version": "2024.02.1"}
        dev2 = HackRFDevice()
        dev2._info = {"serial": "aabbccdd11223344", "firmware_version": "2024.02.1"}

        device_instances = {"hackrf-308d3d83": dev1, "hackrf-11223344": dev2}
        sig_db1 = SignalDatabase()
        sig_db2 = SignalDatabase()
        signal_dbs = {"hackrf-308d3d83": sig_db1, "hackrf-11223344": sig_db2}
        spec1 = SpectrumAnalyzer(signal_db=sig_db1)
        spec2 = SpectrumAnalyzer(signal_db=sig_db2)
        spectrum_instances = {"hackrf-308d3d83": spec1, "hackrf-11223344": spec2}
        rl1 = RadioLock()
        rl2 = RadioLock()
        radio_lock_instances = {"hackrf-308d3d83": rl1, "hackrf-11223344": rl2}

        registry.add_device("hackrf-308d3d83", "hackrf", transport_type="local",
                            metadata={"serial": "c66c63dc308d3d83"})
        registry.set_state("hackrf-308d3d83", DeviceState.CONNECTED)
        registry.add_device("hackrf-11223344", "hackrf", transport_type="local",
                            metadata={"serial": "aabbccdd11223344"})
        registry.set_state("hackrf-11223344", DeviceState.CONNECTED)

        router = create_router(
            device=dev1, spectrum=spec1, receiver=FMReceiver(),
            signal_db=sig_db1, radio_lock=rl1,
            registry=registry,
            device_instances=device_instances,
            spectrum_instances=spectrum_instances,
            radio_locks=radio_lock_instances,
            signal_dbs=signal_dbs,
        )

        app = FastAPI()
        app.include_router(router, prefix="/api/addons/hackrf")
        return TestClient(app)

    def test_list_devices(self, app_client):
        resp = app_client.get("/api/addons/hackrf/devices")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["devices"]) == 2
        ids = {d["device_id"] for d in data["devices"]}
        assert "hackrf-308d3d83" in ids
        assert "hackrf-11223344" in ids

    def test_get_device(self, app_client):
        resp = app_client.get("/api/addons/hackrf/devices/hackrf-308d3d83")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "hackrf-308d3d83"
        assert data["state"] == "connected"

    def test_get_device_not_found(self, app_client):
        resp = app_client.get("/api/addons/hackrf/devices/hackrf-nope")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data

    def test_device_status(self, app_client):
        resp = app_client.get("/api/addons/hackrf/devices/hackrf-308d3d83/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "hackrf-308d3d83"
        assert data["state"] == "connected"
        assert data["connected"] is True
        assert data["sweep_running"] is False

    def test_legacy_status_still_works(self, app_client):
        """Verify the original /status endpoint still works (backwards compat)."""
        resp = app_client.get("/api/addons/hackrf/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "device" in data

    def test_legacy_health_still_works(self, app_client):
        """Verify the original /health endpoint still works."""
        resp = app_client.get("/api/addons/hackrf/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
