# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""HTTP server for MJPEG streaming, snapshots, and status.

Uses stdlib http.server (no frameworks).

Endpoints:
  GET /mjpeg    - multipart/x-mixed-replace JPEG stream
  GET /snapshot - single JPEG frame
  GET /status   - JSON camera status
"""
import json
import logging
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

log = logging.getLogger(__name__)

# Boundary string for multipart MJPEG
BOUNDARY = "frameboundary"


class MJPEGHandler(BaseHTTPRequestHandler):
    """HTTP request handler for camera endpoints."""

    # Suppress per-request log output
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/mjpeg":
            self._handle_mjpeg()
        elif self.path == "/snapshot":
            self._handle_snapshot()
        elif self.path == "/status":
            self._handle_status()
        else:
            self.send_error(404, "Not Found")

    def _handle_mjpeg(self):
        """Stream MJPEG frames as multipart/x-mixed-replace."""
        self.send_response(200)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()

        server = self.server
        fps = getattr(server, "_fps", 10)
        frame_interval = 1.0 / max(1, fps)

        try:
            while True:
                jpeg_data = server._frame_generator.encode_jpeg()
                server._frame_generator.generate()  # Prepare next frame

                frame_header = (
                    f"--{BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg_data)}\r\n"
                    f"\r\n"
                )
                self.wfile.write(frame_header.encode())
                self.wfile.write(jpeg_data)
                self.wfile.write(b"\r\n")
                self.wfile.flush()

                time.sleep(frame_interval)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client disconnected
            pass

    def _handle_snapshot(self):
        """Return a single JPEG frame."""
        server = self.server
        server._frame_generator.generate()
        jpeg_data = server._frame_generator.encode_jpeg()

        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg_data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(jpeg_data)

    def _handle_status(self):
        """Return JSON status."""
        server = self.server
        gen = server._frame_generator
        uptime = time.monotonic() - server._start_time

        status = {
            "camera_id": server._camera_id,
            "fps": server._fps,
            "resolution": f"{gen.width}x{gen.height}",
            "uptime": round(uptime, 2),
        }

        body = json.dumps(status).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class MJPEGServer(HTTPServer):
    """HTTP server that serves MJPEG stream, snapshots, and status."""

    def __init__(
        self,
        frame_generator,
        port: int = 8081,
        camera_id: str = "demo-cam-01",
        fps: int = 10,
        bind_addr: str = "",
    ):
        self._frame_generator = frame_generator
        self._camera_id = camera_id
        self._fps = fps
        self._start_time = time.monotonic()

        # Generate the first frame so snapshot/mjpeg have something
        self._frame_generator.generate()

        super().__init__((bind_addr, port), MJPEGHandler)
        log.info("MJPEG server on port %d (camera=%s, fps=%d)", port, camera_id, fps)
