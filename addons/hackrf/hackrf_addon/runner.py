# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.

"""HackRF runner — standalone mode for remote Pi, publishes spectrum data to MQTT."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from typing import Any

from tritium_lib.sdk import BaseRunner

logger = logging.getLogger(__name__)


class HackRFRunner(BaseRunner):
    """Agent that wraps hackrf_sweep and publishes spectrum data to MQTT.

    Discovers connected HackRF devices via ``hackrf_info``, starts
    ``hackrf_sweep`` subprocesses, parses CSV output line-by-line, and
    publishes batched spectrum measurements to MQTT.
    """

    def __init__(
        self,
        agent_id: str = "hackrf-agent",
        site_id: str = "home",
        mqtt_host: str = "localhost",
        mqtt_port: int = 1883,
        freq_start: int = 2_400_000_000,
        freq_end: int = 2_500_000_000,
        bin_width: int = 100_000,
    ) -> None:
        super().__init__(
            agent_id=agent_id,
            device_type="sdr",
            site_id=site_id,
            mqtt_host=mqtt_host,
            mqtt_port=mqtt_port,
        )
        self._sweep_process: subprocess.Popen | None = None
        self._sweep_running: bool = False
        self._sweep_thread: threading.Thread | None = None
        self._freq_start = freq_start
        self._freq_end = freq_end
        self._bin_width = bin_width
        self._last_status_time: float = 0.0
        self._measurement_count: int = 0
        self._active_device_id: str | None = None

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Run ``hackrf_info`` and parse output for all connected HackRFs.

        Reuses the parsing logic from tritium-sc's ``detect_all_hackrfs``.
        """
        if not shutil.which("hackrf_info"):
            logger.warning("hackrf_info not found on PATH — cannot detect devices")
            return []

        try:
            result = subprocess.run(
                ["hackrf_info"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            logger.error("discover_devices failed: %s", exc)
            return []

        if result.returncode != 0:
            logger.warning(
                "hackrf_info returned %d: %s",
                result.returncode,
                result.stderr.strip(),
            )
            return []

        output = result.stdout
        if "Found HackRF" not in output and "Serial number" not in output:
            return []

        # Split by "Index:" sections — each HackRF starts with "Index: N"
        sections = re.split(r"(?=Index:\s*\d+)", output)
        devices: list[dict[str, Any]] = []

        for section in sections:
            section = section.strip()
            if not section or "Index:" not in section:
                continue
            info = self._parse_hackrf_info(section)
            if info is None:
                continue

            m = re.search(r"Index:\s*(\d+)", section)
            info["index"] = int(m.group(1)) if m else len(devices)

            serial = info.get("serial", "")
            serial_clean = serial.replace(" ", "")
            if serial_clean:
                info["device_id"] = f"hackrf-{serial_clean[-8:]}"
            else:
                info["device_id"] = f"hackrf-{info['index']}"

            devices.append(info)

        # Single-device fallback
        if not devices:
            info = self._parse_hackrf_info(output)
            if info:
                info["index"] = 0
                serial = info.get("serial", "")
                serial_clean = serial.replace(" ", "")
                info["device_id"] = (
                    f"hackrf-{serial_clean[-8:]}" if serial_clean else "hackrf-0"
                )
                devices.append(info)

        logger.info("Detected %d HackRF device(s)", len(devices))
        return devices

    @staticmethod
    def _parse_hackrf_info(output: str) -> dict[str, Any] | None:
        """Parse ``hackrf_info`` output into a structured dict.

        Example output::

            hackrf_info version: 2024.02.1
            libhackrf version: 2024.02.1 (0.9)
            Found HackRF
            Index: 0
            Serial number: 0000000000000000 c66c63dc308d3d83
            Board ID Number: 2 (HackRF One)
            Firmware Version: 2024.02.1 (API version 1.08)
            Part ID Number: 0xa000cb3c 0x00724f61
            Hardware Revision: r9
        """
        if "Found HackRF" not in output and "Serial number" not in output:
            return None

        info: dict[str, Any] = {}

        m = re.search(
            r"Serial number:\s+([0-9a-fA-F]+(?:[ ]+[0-9a-fA-F]+)?)", output
        )
        if m:
            info["serial"] = m.group(1).strip()

        m = re.search(r"Board ID Number:\s+(\d+)\s*\(([^)]+)\)", output)
        if m:
            info["board_id"] = int(m.group(1))
            info["board_name"] = m.group(2)

        m = re.search(
            r"Firmware Version:\s+(\S+)"
            r"(?:\s*\((?:API version|API:)\s*([^)]+)\))?",
            output,
        )
        if m:
            info["firmware_version"] = m.group(1)
            if m.group(2):
                info["api_version"] = m.group(2)

        m = re.search(r"Part ID Number:\s+(0x\w+\s+0x\w+)", output)
        if m:
            info["part_id"] = m.group(1)

        m = re.search(r"Hardware Revision:\s+(\S+)", output)
        if m:
            info["hardware_revision"] = m.group(1)

        m = re.search(r"manufactured by\s+(.+?)\.?\s*$", output, re.MULTILINE)
        if m:
            info["manufacturer"] = m.group(1).strip()

        return info

    # ------------------------------------------------------------------
    # Device lifecycle
    # ------------------------------------------------------------------

    async def start_device(self, device_info: dict[str, Any]) -> bool:
        """Start ``hackrf_sweep`` for the given device.

        Launches the subprocess and starts a background thread that reads
        CSV output, parses it, and publishes spectrum data to MQTT.
        """
        device_id = device_info.get("device_id", "hackrf-0")

        if self._sweep_running:
            logger.warning("Sweep already running for %s", self._active_device_id)
            return device_id

        serial = device_info.get("serial", "").replace(" ", "")
        cmd = [
            "hackrf_sweep",
            "-f",
            f"{self._freq_start // 1_000_000}:{self._freq_end // 1_000_000}",
            "-w",
            str(self._bin_width),
        ]
        if serial:
            cmd.extend(["-d", serial])

        logger.info("Starting hackrf_sweep: %s", " ".join(cmd))

        try:
            self._sweep_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            logger.error("hackrf_sweep not found on PATH")
            return device_id
        except OSError as exc:
            logger.error("Failed to start hackrf_sweep: %s", exc)
            return device_id

        self._sweep_running = True
        self._active_device_id = device_id
        self._measurement_count = 0
        self._last_status_time = time.monotonic()
        self._devices[device_id] = {
            **device_info,
            "started_at": time.time(),
        }

        self._sweep_thread = threading.Thread(
            target=self._sweep_reader_loop,
            args=(self._sweep_process, device_id),
            daemon=True,
        )
        self._sweep_thread.start()

        self._publish_status(device_id, "sweep_running")
        logger.info("hackrf_sweep started for %s", device_id)
        return device_id

    async def stop_device(self, device_id: str) -> bool:
        """Kill the hackrf_sweep subprocess for a device."""
        if not self._sweep_running:
            logger.debug("No sweep running for %s", device_id)
            return

        self._sweep_running = False

        if self._sweep_process is not None:
            try:
                self._sweep_process.terminate()
                self._sweep_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._sweep_process.kill()
                self._sweep_process.wait(timeout=2)
            except Exception as exc:
                logger.error("Error stopping hackrf_sweep: %s", exc)
            self._sweep_process = None

        if self._sweep_thread is not None:
            self._sweep_thread.join(timeout=3)
            self._sweep_thread = None

        self._devices.pop(device_id, None)
        self._publish_status(device_id, "stopped")
        self._active_device_id = None
        logger.info("hackrf_sweep stopped for %s", device_id)

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def on_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle commands from SC.

        Supported commands:
            start_sweep  — start sweep with optional freq_start, freq_end,
                           bin_width params
            stop_sweep   — stop current sweep
            set_freq_range — change sweep frequency range (restarts if running)
            status       — return current device status
        """
        if command == "start_sweep":
            if payload.get("freq_start"):
                self._freq_start = int(payload["freq_start"])
            if payload.get("freq_end"):
                self._freq_end = int(payload["freq_end"])
            if payload.get("bin_width"):
                self._bin_width = int(payload["bin_width"])

            devices = self.discover_devices()
            if not devices:
                return {"error": "No HackRF devices found"}
            did = self.start_device(devices[0])
            return {"status": "sweep_started", "device_id": did}

        elif command == "stop_sweep":
            if self._active_device_id:
                self.stop_device(self._active_device_id)
                return {"status": "sweep_stopped"}
            return {"error": "No sweep running"}

        elif command == "set_freq_range":
            freq_start = payload.get("freq_start")
            freq_end = payload.get("freq_end")
            if freq_start is None or freq_end is None:
                return {"error": "freq_start and freq_end required"}
            self._freq_start = int(freq_start)
            self._freq_end = int(freq_end)
            if payload.get("bin_width"):
                self._bin_width = int(payload["bin_width"])

            # Restart sweep if running
            if self._sweep_running and self._active_device_id:
                device_id = self._active_device_id
                device_info = self._devices.get(
                    device_id, {"device_id": device_id}
                )
                self.stop_device(device_id)
                self.start_device(device_info)

            return {
                "status": "freq_range_updated",
                "freq_start": self._freq_start,
                "freq_end": self._freq_end,
                "bin_width": self._bin_width,
            }

        elif command == "status":
            return self._get_status()

        else:
            logger.warning("Unknown command: %s", command)
            return {"error": f"Unknown command: {command}"}

    def _get_status(self) -> dict[str, Any]:
        """Build a status dict for the current agent state."""
        return {
            "device_type": self.device_type,
            "sweep_running": self._sweep_running,
            "active_device_id": self._active_device_id,
            "freq_start": self._freq_start,
            "freq_end": self._freq_end,
            "bin_width": self._bin_width,
            "measurement_count": self._measurement_count,
        }

    # ------------------------------------------------------------------
    # Sweep line parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_sweep_line(line: str) -> dict[str, Any] | None:
        """Parse a single hackrf_sweep CSV output line.

        ``hackrf_sweep`` CSV format::

            date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...

        Example::

            2024-01-15, 10:30:45.123456, 2400000000, 2420000000, 100000.00, 8192, -45.2, -42.1, ...

        Returns a dict with ``freq_hz`` (center frequencies) and
        ``power_dbm`` (power values), or ``None`` for unparseable lines.
        """
        if not line or not line.strip():
            return None

        line = line.strip()

        # Skip comment/header lines
        if line.startswith("#") or line.startswith("date"):
            return None

        parts = [p.strip() for p in line.split(",")]

        # Need at least: date, time, hz_low, hz_high, hz_bin_width,
        # num_samples, 1+ dB values
        if len(parts) < 7:
            return None

        try:
            date_str = parts[0]
            time_str = parts[1]
            hz_low = int(float(parts[2]))
            hz_high = int(float(parts[3]))
            hz_bin_width = int(float(parts[4]))
            num_samples = int(float(parts[5]))

            # Remaining fields are dB power values
            power_values: list[float] = []
            for p in parts[6:]:
                p = p.strip()
                if p:
                    power_values.append(float(p))

            if not power_values:
                return None

            # Compute center frequency for each bin
            freq_hz = [
                hz_low + (i * hz_bin_width) + (hz_bin_width // 2)
                for i in range(len(power_values))
            ]

            return {
                "timestamp": f"{date_str} {time_str}",
                "hz_low": hz_low,
                "hz_high": hz_high,
                "hz_bin_width": hz_bin_width,
                "num_samples": num_samples,
                "freq_hz": freq_hz,
                "power_dbm": power_values,
            }

        except (ValueError, IndexError) as exc:
            logger.debug("Failed to parse sweep line: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Background sweep reader
    # ------------------------------------------------------------------

    def _sweep_reader_loop(
        self, process: subprocess.Popen, device_id: str
    ) -> None:
        """Background thread: read hackrf_sweep stdout, parse, publish.

        Accumulates measurements and publishes a batch every ~1 second
        instead of publishing every individual line.
        """
        batch: list[dict[str, Any]] = []
        batch_start = time.monotonic()

        try:
            while self._sweep_running and process.poll() is None:
                line = process.stdout.readline()  # type: ignore[union-attr]
                if not line:
                    if process.poll() is not None:
                        break
                    continue

                measurement = self._parse_sweep_line(line)
                if measurement:
                    batch.append(measurement)
                    self._measurement_count += 1

                now = time.monotonic()

                # Publish batch every ~1 second
                if batch and (now - batch_start) >= 1.0:
                    self._mqtt.publish(
                        self.data_topic("spectrum", device_id),
                        {
                            "device_id": device_id,
                            "batch": batch,
                            "count": len(batch),
                            "timestamp": time.time(),
                        },
                    )
                    batch = []
                    batch_start = now

                # Publish status every 10 seconds
                if (now - self._last_status_time) >= 10.0:
                    self._publish_status(device_id, "sweep_running")
                    self._last_status_time = now

        except Exception:
            logger.exception("Sweep reader error for %s", device_id)
        finally:
            # Flush remaining batch
            if batch:
                self._mqtt.publish(
                    self.data_topic("spectrum", device_id),
                    {
                        "device_id": device_id,
                        "batch": batch,
                        "count": len(batch),
                        "timestamp": time.time(),
                    },
                )
            logger.info(
                "Sweep reader loop ended for %s (%d measurements)",
                device_id,
                self._measurement_count,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _publish_status(self, device_id: str, status: str) -> None:
        """Publish a status message for the device."""
        self._mqtt.publish(
            self.data_topic("status", device_id),
            {
                **self._get_status(),
                "status": status,
                "device_id": device_id,
                "timestamp": time.time(),
            },
        )
        self._last_status_time = time.monotonic()
