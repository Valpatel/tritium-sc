"""Reolink NVR discovery and API client."""

import asyncio
import os
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger


@dataclass
class CameraInfo:
    """Discovered camera information."""

    channel: int
    name: str
    online: bool
    rtsp_main: str
    rtsp_sub: str
    model: Optional[str] = None
    firmware: Optional[str] = None


class NVRClient:
    """Async client for Reolink NVR API."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        timeout: float = 30.0,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._token: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"

    async def __aenter__(self):
        self._client = httpx.AsyncClient(verify=False, timeout=self.timeout)
        await self.login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
            self._client = None
        self._token = None

    async def _request(self, cmd: str, params: dict = None, action: int = 0) -> dict:
        """Make an API request to the NVR."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async with.")

        url = f"{self.base_url}/cgi-bin/api.cgi"
        query_params = {"cmd": cmd}
        if self._token:
            query_params["token"] = self._token

        payload = [{"cmd": cmd, "action": action, "param": params or {}}]

        try:
            response = await self._client.post(url, params=query_params, json=payload)
            response.raise_for_status()
            data = response.json()
            return data[0] if data else {}
        except Exception as e:
            logger.error(f"NVR request failed: {cmd} - {e}")
            raise

    async def login(self) -> bool:
        """Authenticate with the NVR."""
        try:
            result = await self._request(
                "Login",
                {"User": {"userName": self.username, "password": self.password}},
            )
            if result.get("code") == 0:
                self._token = result.get("value", {}).get("Token", {}).get("name")
                if self._token:
                    logger.info(f"NVR login successful: {self.host}")
                    return True
            logger.error(f"NVR login failed: {result}")
            return False
        except Exception as e:
            logger.error(f"NVR login error: {e}")
            return False

    async def get_channel_status(self) -> list[dict]:
        """Get status of all channels."""
        result = await self._request("GetChannelStatus")
        if result.get("code") == 0:
            return result.get("value", {}).get("status", [])
        return []

    async def get_device_info(self) -> dict:
        """Get NVR device information."""
        result = await self._request("GetDevInfo")
        if result.get("code") == 0:
            return result.get("value", {}).get("DevInfo", {})
        return {}

    async def discover_cameras(self) -> list[CameraInfo]:
        """Discover all cameras connected to the NVR."""
        cameras = []
        channels = await self.get_channel_status()

        for ch in channels:
            channel_num = ch.get("channel", 0)
            online = ch.get("online") == 1
            name = ch.get("name", f"Camera {channel_num}")

            # Build RTSP URLs
            rtsp_main = f"rtsp://{self.username}:{self.password}@{self.host}:554/h264Preview_{channel_num + 1:02d}_main"
            rtsp_sub = f"rtsp://{self.username}:{self.password}@{self.host}:554/h264Preview_{channel_num + 1:02d}_sub"

            cameras.append(
                CameraInfo(
                    channel=channel_num,
                    name=name,
                    online=online,
                    rtsp_main=rtsp_main,
                    rtsp_sub=rtsp_sub,
                )
            )

        return cameras

    async def get_recording_days(self, channel: int, year: int, month: int) -> list[int]:
        """Get days with recordings for a channel/month."""
        result = await self._request(
            "Search",
            {
                "Search": {
                    "channel": channel,
                    "onlyStatus": 1,
                    "streamType": "main",
                    "StartTime": {
                        "year": year,
                        "mon": month,
                        "day": 1,
                        "hour": 0,
                        "min": 0,
                        "sec": 0,
                    },
                    "EndTime": {
                        "year": year,
                        "mon": month,
                        "day": 31,
                        "hour": 23,
                        "min": 59,
                        "sec": 59,
                    },
                }
            },
            action=1,
        )

        if result.get("code") == 0:
            table = result.get("value", {}).get("SearchResult", {}).get("table", "")
            # Table is a bitmask string, "1" at position i means day i+1 has recordings
            days = []
            for i, char in enumerate(table):
                if char == "1":
                    days.append(i + 1)
            return days
        return []


async def discover_cameras() -> list[CameraInfo]:
    """Discover cameras from NVR using configuration."""
    from app.config import settings

    host = settings.nvr_host
    user = settings.nvr_user
    password = settings.nvr_pass
    port = settings.nvr_port

    if not all([host, user, password]):
        logger.warning("NVR credentials not configured (NVR_HOST, NVR_USER, NVR_PASS)")
        return []

    try:
        async with NVRClient(host, user, password, port) as nvr:
            cameras = await nvr.discover_cameras()
            logger.info(f"Discovered {len(cameras)} cameras from NVR")
            return cameras
    except Exception as e:
        logger.error(f"Camera discovery failed: {e}")
        return []


# CLI test
if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    async def main():
        cameras = await discover_cameras()
        for cam in cameras:
            status = "ONLINE" if cam.online else "OFFLINE"
            print(f"  CH{cam.channel}: {cam.name} [{status}]")
            print(f"    RTSP: {cam.rtsp_main}")

    asyncio.run(main())
