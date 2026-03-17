# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HackRF One device detection and management via subprocess wrappers."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Optional

log = logging.getLogger("hackrf.device")


async def detect_all_hackrfs() -> list[dict]:
    """Run hackrf_info and parse output for ALL connected HackRF devices.

    hackrf_info lists each device as an "Index: N" section.
    Returns a list of device info dicts, one per device, each with a
    device_id like ``hackrf-{serial_last8}`` or ``hackrf-{index}`` if
    no serial is available.
    """
    if not shutil.which("hackrf_info"):
        log.warning("hackrf_info not found on PATH — cannot detect devices")
        return []

    try:
        proc = await asyncio.create_subprocess_exec(
            "hackrf_info",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    except (asyncio.TimeoutError, FileNotFoundError, OSError) as e:
        log.error(f"detect_all_hackrfs failed: {e}")
        return []

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        log.warning(f"hackrf_info returned {proc.returncode}: {err}")
        return []

    output = stdout.decode(errors="replace")
    if "Found HackRF" not in output and "Serial number" not in output:
        return []

    # Split by "Index:" sections — each HackRF starts with "Index: N"
    sections = re.split(r"(?=Index:\s*\d+)", output)
    devices: list[dict] = []
    parser = HackRFDevice()

    for section in sections:
        section = section.strip()
        if not section or "Index:" not in section:
            continue
        # Prepend "Found HackRF" so _parse_hackrf_info recognises the block
        parseable = "Found HackRF\n" + section if "Found HackRF" not in section else section
        info = parser._parse_hackrf_info(parseable)
        if info is None:
            continue

        # Extract index
        m = re.search(r"Index:\s*(\d+)", section)
        info["index"] = int(m.group(1)) if m else len(devices)

        # Build a stable device_id
        serial = info.get("serial", "")
        serial_clean = serial.replace(" ", "")
        if serial_clean:
            info["device_id"] = f"hackrf-{serial_clean[-8:]}"
        else:
            info["device_id"] = f"hackrf-{info['index']}"

        devices.append(info)

    if not devices:
        # Single-device fallback: maybe hackrf_info didn't use Index sections
        info = parser._parse_hackrf_info(output)
        if info:
            info["index"] = 0
            serial = info.get("serial", "")
            serial_clean = serial.replace(" ", "")
            info["device_id"] = f"hackrf-{serial_clean[-8:]}" if serial_clean else "hackrf-0"
            devices.append(info)

    log.info(f"Detected {len(devices)} HackRF device(s)")
    return devices


class HackRFDevice:
    """Interface to a HackRF One device via command-line tools.

    All operations use subprocess calls to hackrf_* binaries.
    No Python bindings required.
    """

    def __init__(self):
        self._info: dict | None = None
        self._available: bool | None = None

    @property
    def is_available(self) -> bool:
        """Check if hackrf_info binary exists on PATH."""
        if self._available is None:
            self._available = shutil.which("hackrf_info") is not None
        return self._available

    @property
    def serial_short(self) -> str:
        """Return the last 8 characters of the device serial number.

        Returns an empty string if no info has been detected yet.
        """
        if not self._info:
            return ""
        serial = self._info.get("serial", "")
        serial_clean = serial.replace(" ", "")
        return serial_clean[-8:] if serial_clean else ""

    def get_info(self) -> dict | None:
        """Return cached device info, or None if not yet detected."""
        return self._info

    async def detect(self) -> dict | None:
        """Run hackrf_info and parse output to detect the device.

        Returns:
            Device info dict with serial, firmware, board_id, etc., or None if not found.
        """
        if not self.is_available:
            log.warning("hackrf_info not found on PATH")
            return {"connected": False, "error": "hackrf_info not found on PATH"}

        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_info",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            log.error("hackrf_info timed out")
            return {"connected": False, "error": "hackrf_info timed out"}
        except FileNotFoundError:
            log.error("hackrf_info binary not found")
            self._available = False
            return {"connected": False, "error": "hackrf_info not installed"}
        except Exception as e:
            log.error(f"hackrf_info failed: {e}")
            return {"connected": False, "error": str(e)}

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            log.warning(f"hackrf_info returned {proc.returncode}: {err}")
            return {"connected": False, "error": err or f"hackrf_info exit code {proc.returncode}"}

        output = stdout.decode(errors="replace")
        info = self._parse_hackrf_info(output)
        if info:
            self._info = info
            log.info(f"HackRF detected: serial={info.get('serial', '?')}, "
                      f"firmware={info.get('firmware_version', '?')}")
        return info

    def _parse_hackrf_info(self, output: str) -> dict | None:
        """Parse hackrf_info output into a structured dict.

        Example output:
            hackrf_info version: 2024.02.1
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
        if "Found HackRF" not in output and "Serial number" not in output:
            return None

        info: dict = {"raw_output": output}

        # Serial number (hex string, possibly space-separated halves, same line only)
        m = re.search(r"Serial number:\s+([0-9a-fA-F]+(?:[ ]+[0-9a-fA-F]+)?)", output)
        if m:
            info["serial"] = m.group(1).strip()

        # Board ID
        m = re.search(r"Board ID Number:\s+(\d+)\s*\(([^)]+)\)", output)
        if m:
            info["board_id"] = int(m.group(1))
            info["board_name"] = m.group(2)

        # Firmware version
        m = re.search(r"Firmware Version:\s+(\S+)(?:\s*\((?:API version|API:)\s*([^)]+)\))?", output)
        if m:
            info["firmware_version"] = m.group(1)
            if m.group(2):
                info["api_version"] = m.group(2)

        # Part ID
        m = re.search(r"Part ID Number:\s+(0x\w+\s+0x\w+)", output)
        if m:
            info["part_id"] = m.group(1)

        # Hardware revision
        m = re.search(r"Hardware Revision:\s+(\S+)", output)
        if m:
            info["hardware_revision"] = m.group(1)

        # hackrf_info version
        m = re.search(r"hackrf_info version:\s+(\S+)", output)
        if m:
            info["tool_version"] = m.group(1)

        # libhackrf version
        m = re.search(r"libhackrf version:\s+(\S+)", output)
        if m:
            info["lib_version"] = m.group(1)

        # Manufacturer
        m = re.search(r"manufactured by\s+(.+?)\.?\s*$", output, re.MULTILINE)
        if m:
            info["manufacturer"] = m.group(1).strip()

        return info

    async def flash_firmware(self, firmware_path: str) -> dict:
        """Flash firmware to the HackRF using hackrf_spiflash.

        Args:
            firmware_path: Path to the firmware .bin file.

        Returns:
            Dict with success status and output.
        """
        if not shutil.which("hackrf_spiflash"):
            return {"success": False, "error": "hackrf_spiflash not found on PATH"}

        try:
            proc = await asyncio.create_subprocess_exec(
                "hackrf_spiflash", "-w", firmware_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        except asyncio.TimeoutError:
            return {"success": False, "error": "Flash timed out (120s)"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        success = proc.returncode == 0
        if success:
            log.info(f"Firmware flashed successfully from {firmware_path}")
            # Invalidate cached info since firmware changed
            self._info = None
        else:
            log.error(f"Firmware flash failed: {output}")

        return {"success": success, "output": output.strip(), "returncode": proc.returncode}

    # ── Helper ──────────────────────────────────────────────────

    async def _run_cmd(
        self,
        binary: str,
        args: list[str],
        timeout: float = 10.0,
    ) -> dict:
        """Run a hackrf_* command and return structured result.

        Args:
            binary: Name of the binary (e.g. ``hackrf_clock``).
            args: Command-line arguments.
            timeout: Maximum seconds to wait.

        Returns:
            Dict with ``success``, ``output``, ``returncode`` keys.
        """
        if not shutil.which(binary):
            return {"success": False, "error": f"{binary} not found on PATH"}

        try:
            proc = await asyncio.create_subprocess_exec(
                binary, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return {"success": False, "error": f"{binary} timed out ({timeout}s)"}
        except FileNotFoundError:
            return {"success": False, "error": f"{binary} binary not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

        output = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        return {
            "success": proc.returncode == 0,
            "output": output.strip(),
            "returncode": proc.returncode,
        }

    # ── Clock configuration ──────────────────────────────────────

    async def get_clock_info(self) -> dict:
        """Read current clock configuration via ``hackrf_clock -r``.

        Returns:
            Dict with success status and parsed clock info.
        """
        result = await self._run_cmd("hackrf_clock", ["-r"])
        if result["success"]:
            result["clock"] = self._parse_clock_output(result["output"])
        return result

    def _parse_clock_output(self, output: str) -> dict:
        """Parse hackrf_clock -r output into structured dict."""
        clock: dict = {}
        m = re.search(r"CLKIN\s*[:=]\s*(\d+)", output, re.IGNORECASE)
        if m:
            clock["clkin_hz"] = int(m.group(1))
        m = re.search(r"CLKOUT\s*[:=]\s*(\d+)", output, re.IGNORECASE)
        if m:
            clock["clkout_hz"] = int(m.group(1))
        # Capture enabled/disabled state if present
        if re.search(r"CLKOUT.*enabled", output, re.IGNORECASE):
            clock["clkout_enabled"] = True
        elif re.search(r"CLKOUT.*disabled", output, re.IGNORECASE):
            clock["clkout_enabled"] = False
        clock["raw"] = output
        return clock

    async def set_clkin(self, freq_hz: int) -> dict:
        """Set external clock input (CLKIN) frequency.

        Args:
            freq_hz: CLKIN frequency in Hz (typically 10 MHz for GPS reference).

        Returns:
            Dict with success status and output.
        """
        log.info(f"Setting CLKIN to {freq_hz} Hz")
        return await self._run_cmd("hackrf_clock", ["-i", str(freq_hz)])

    async def set_clkout(self, freq_hz: int, enable: bool = True) -> dict:
        """Set clock output (CLKOUT) frequency and enable/disable.

        Args:
            freq_hz: CLKOUT frequency in Hz.
            enable: Whether to enable the clock output.

        Returns:
            Dict with success status and output.
        """
        log.info(f"Setting CLKOUT to {freq_hz} Hz, enable={enable}")
        args = ["-o", str(freq_hz)]
        if not enable:
            args.append("-O")  # disable CLKOUT
        return await self._run_cmd("hackrf_clock", args)

    async def set_clock(self, freq_hz: int) -> dict:
        """Set the HackRF clock output frequency using hackrf_clock.

        Legacy method — prefer set_clkout() for new code.

        Args:
            freq_hz: Clock frequency in Hz.

        Returns:
            Dict with success status and output.
        """
        return await self.set_clkout(freq_hz)

    # ── Opera Cake antenna switching ─────────────────────────────

    async def get_operacake_boards(self) -> dict:
        """List connected Opera Cake add-on boards.

        Returns:
            Dict with list of detected boards.
        """
        result = await self._run_cmd("hackrf_operacake", ["-l"])
        if result["success"]:
            result["boards"] = self._parse_operacake_list(result["output"])
        return result

    def _parse_operacake_list(self, output: str) -> list[dict]:
        """Parse hackrf_operacake -l output."""
        boards: list[dict] = []
        for m in re.finditer(
            r"(?:Board|Opera\s*Cake)\s*(\d+)\s*(?:at\s+address\s+)?(?:0x)?([0-9a-fA-F]+)?",
            output, re.IGNORECASE,
        ):
            board: dict = {"index": int(m.group(1))}
            if m.group(2):
                board["address"] = m.group(2)
            boards.append(board)
        # If no structured entries but we got output, include raw
        if not boards and output.strip():
            boards.append({"index": 0, "raw": output.strip()})
        return boards

    async def set_antenna_port(self, port: str) -> dict:
        """Set Opera Cake antenna port (e.g. A1, A2, B1, B2, etc.).

        Args:
            port: Antenna port identifier (A1-A4, B1-B4).

        Returns:
            Dict with success status and output.
        """
        port = port.upper().strip()
        valid_ports = [f"{bank}{n}" for bank in "AB" for n in range(1, 5)]
        if port not in valid_ports:
            return {
                "success": False,
                "error": f"Invalid port '{port}'. Valid: {', '.join(valid_ports)}",
            }
        log.info(f"Setting Opera Cake antenna port to {port}")
        return await self._run_cmd("hackrf_operacake", ["-a", port])

    async def get_antenna_config(self) -> dict:
        """Get current Opera Cake antenna routing configuration.

        Returns:
            Dict with current antenna config.
        """
        result = await self._run_cmd("hackrf_operacake", ["-l"])
        if result["success"]:
            result["boards"] = self._parse_operacake_list(result["output"])
        return result

    # ── Bias tee control ─────────────────────────────────────────

    async def set_bias_tee(self, enabled: bool) -> dict:
        """Enable or disable the bias tee (DC power on antenna port).

        The bias tee provides ~3.3V DC on the antenna port for powering
        active antennas and low-noise amplifiers (LNAs).

        Args:
            enabled: True to enable, False to disable.

        Returns:
            Dict with success status and output.
        """
        flag = "1" if enabled else "0"
        log.info(f"Setting bias tee {'enabled' if enabled else 'disabled'}")
        return await self._run_cmd("hackrf_transfer", ["-p", flag, "-R"], timeout=5.0)

    # ── Device diagnostics ───────────────────────────────────────

    async def get_debug_info(self) -> dict:
        """Get PLL (Si5351C) status via hackrf_debug.

        Returns:
            Dict with PLL registers and status.
        """
        result = await self._run_cmd("hackrf_debug", ["--si5351c"])
        if result["success"]:
            result["pll"] = self._parse_debug_output(result["output"])
        return result

    def _parse_debug_output(self, output: str) -> dict:
        """Parse hackrf_debug --si5351c output into structured dict."""
        pll: dict = {"registers": {}}
        for m in re.finditer(r"(\d+)\s*[:=]\s*(0x[0-9a-fA-F]+|\d+)", output):
            pll["registers"][int(m.group(1))] = m.group(2)
        pll["raw"] = output
        return pll

    async def get_board_id(self) -> dict:
        """Get detailed board identification.

        Combines hackrf_info board fields into a board identity dict.
        """
        info = self._info
        if not info:
            info = await self.detect()
        if not info:
            return {"success": False, "error": "HackRF not detected"}
        return {
            "success": True,
            "board_id": info.get("board_id"),
            "board_name": info.get("board_name"),
            "serial": info.get("serial"),
            "part_id": info.get("part_id"),
            "hardware_revision": info.get("hardware_revision"),
            "manufacturer": info.get("manufacturer"),
        }

    async def get_cpld_checksum(self) -> dict:
        """Verify CPLD firmware checksum via hackrf_debug.

        Returns:
            Dict with CPLD checksum and verification status.
        """
        result = await self._run_cmd("hackrf_debug", ["--cpld-checksum"])
        if result["success"]:
            m = re.search(r"(?:checksum|CPLD)\s*[:=]?\s*(0x[0-9a-fA-F]+)", result["output"], re.IGNORECASE)
            if m:
                result["cpld_checksum"] = m.group(1)
        return result

    # ── Firmware management (enhanced) ───────────────────────────

    async def get_firmware_info(self) -> dict:
        """Get current firmware version and related info.

        Returns:
            Dict with firmware version, API version, tool versions.
        """
        info = self._info
        if not info:
            info = await self.detect()
        if not info:
            return {"success": False, "error": "HackRF not detected"}
        return {
            "success": True,
            "firmware_version": info.get("firmware_version", ""),
            "api_version": info.get("api_version", ""),
            "tool_version": info.get("tool_version", ""),
            "lib_version": info.get("lib_version", ""),
            "hardware_revision": info.get("hardware_revision", ""),
            "serial": info.get("serial", ""),
        }

    async def flash_cpld(self, firmware_path: str) -> dict:
        """Flash CPLD firmware using hackrf_cpldjtag.

        Args:
            firmware_path: Path to the CPLD .xsvf firmware file.

        Returns:
            Dict with success status and output.
        """
        log.info(f"Flashing CPLD from {firmware_path}")
        result = await self._run_cmd(
            "hackrf_cpldjtag", ["-x", firmware_path], timeout=120.0,
        )
        if result["success"]:
            log.info("CPLD firmware flashed successfully")
            self._info = None  # Invalidate cache
        else:
            log.error(f"CPLD flash failed: {result.get('output', '')}")
        return result

    async def reset_device(self) -> dict:
        """Reset HackRF into DFU mode for firmware recovery.

        Returns:
            Dict with success status and output.
        """
        log.warning("Resetting HackRF to DFU mode")
        result = await self._run_cmd("hackrf_spiflash", ["-R"], timeout=15.0)
        if result["success"]:
            self._info = None  # Device will be in DFU mode
            self._available = None  # Re-check availability after reset
        return result
