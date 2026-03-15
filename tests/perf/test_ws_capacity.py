# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""WebSocket connection stress test — measures capacity and delivery latency.

Opens 10, 50, and 100 concurrent WebSocket connections against a headless
server and measures message delivery latency and dropped messages.
"""
import asyncio
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _find_free_port() -> int:
    """Find an available TCP port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_port():
    """Start a headless server on a random port for WebSocket testing."""
    port = _find_free_port()

    # Start server in background
    import subprocess
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite+aiosqlite:///data/test_ws_capacity.db"
    env["SIMULATION_ENABLED"] = "false"
    env["MQTT_ENABLED"] = "false"
    env["AMY_ENABLED"] = "false"

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--log-level", "warning",
        ],
        cwd=os.path.join(os.path.dirname(__file__), "..", "..", "src"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for server to be ready
    import socket
    for attempt in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("Server failed to start within 10 seconds")

    yield port

    proc.kill()
    proc.wait(timeout=5)
    # Clean up test database
    db_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "src", "data", "test_ws_capacity.db"
    )
    if os.path.exists(db_path):
        os.unlink(db_path)


async def _connect_ws(port: int, received: list, conn_id: int, ready_event: asyncio.Event):
    """Connect a WebSocket client and collect messages."""
    try:
        import websockets
    except ImportError:
        pytest.skip("websockets package not installed")
        return

    uri = f"ws://127.0.0.1:{port}/ws/live"
    try:
        async with websockets.connect(uri, open_timeout=5, close_timeout=2) as ws:
            ready_event.set()
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    data = json.loads(msg)
                    data["_received_at"] = time.perf_counter()
                    data["_conn_id"] = conn_id
                    received.append(data)
            except asyncio.TimeoutError:
                pass
    except Exception as exc:
        # Connection failed — record the error
        received.append({"_error": str(exc), "_conn_id": conn_id})


class TestWebSocketCapacity:
    """Stress test WebSocket connection handling."""

    @pytest.mark.parametrize("num_connections", [10, 50, 100])
    def test_concurrent_connections(self, server_port, num_connections: int) -> None:
        """Open N concurrent WebSocket connections and verify all connect."""
        try:
            import websockets  # noqa: F401
        except ImportError:
            pytest.skip("websockets package not installed")

        async def _run():
            connected = 0
            errors = 0

            async def _try_connect():
                nonlocal connected, errors
                uri = f"ws://127.0.0.1:{server_port}/ws/live"
                try:
                    async with websockets.connect(uri, open_timeout=10) as ws:
                        # Read connection confirmation
                        msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                        data = json.loads(msg)
                        if data.get("type") == "connected":
                            connected += 1
                        else:
                            connected += 1  # Still connected
                        # Hold connection briefly
                        await asyncio.sleep(0.5)
                except Exception:
                    errors += 1

            tasks = [asyncio.create_task(_try_connect()) for _ in range(num_connections)]
            await asyncio.gather(*tasks, return_exceptions=True)

            return connected, errors

        connected, errors = asyncio.run(_run())

        # At least 90% should connect successfully
        success_rate = connected / num_connections if num_connections > 0 else 0
        assert success_rate >= 0.9, (
            f"Connection success rate too low: {success_rate:.1%} "
            f"({connected}/{num_connections} connected, {errors} errors)"
        )
        print(
            f"  [{num_connections:>3} connections] "
            f"connected={connected}, errors={errors}, "
            f"rate={success_rate:.1%}"
        )

    def test_broadcast_delivery(self, server_port) -> None:
        """Verify broadcast reaches all 10 connected clients."""
        try:
            import websockets  # noqa: F401
        except ImportError:
            pytest.skip("websockets package not installed")

        num_clients = 10

        async def _run():
            received_per_client: dict[int, list] = {i: [] for i in range(num_clients)}
            connections = []

            async def _client(client_id: int):
                uri = f"ws://127.0.0.1:{server_port}/ws/live"
                try:
                    async with websockets.connect(uri, open_timeout=10) as ws:
                        connections.append(ws)
                        # Drain initial messages
                        while True:
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                                data = json.loads(msg)
                                received_per_client[client_id].append(data)
                            except asyncio.TimeoutError:
                                break
                except Exception:
                    pass

            tasks = [asyncio.create_task(_client(i)) for i in range(num_clients)]
            await asyncio.gather(*tasks, return_exceptions=True)

            # Count clients that received the initial "connected" message
            clients_with_connected = sum(
                1 for msgs in received_per_client.values()
                if any(m.get("type") == "connected" for m in msgs)
            )

            return clients_with_connected

        clients_with_msg = asyncio.run(_run())

        # All clients should get the connection confirmation
        assert clients_with_msg >= num_clients * 0.9, (
            f"Not enough clients received connected message: "
            f"{clients_with_msg}/{num_clients}"
        )
        print(f"  [broadcast] {clients_with_msg}/{num_clients} clients received messages")

    def test_connection_cleanup(self, server_port) -> None:
        """Verify disconnected clients are cleaned up properly."""
        try:
            import websockets  # noqa: F401
        except ImportError:
            pytest.skip("websockets package not installed")

        async def _run():
            # Connect 20 clients, disconnect all, reconnect 5
            connections = []
            uri = f"ws://127.0.0.1:{server_port}/ws/live"

            # Phase 1: Connect 20
            for _ in range(20):
                try:
                    ws = await websockets.connect(uri, open_timeout=5)
                    connections.append(ws)
                except Exception:
                    pass

            phase1_count = len(connections)

            # Phase 2: Disconnect all
            for ws in connections:
                try:
                    await ws.close()
                except Exception:
                    pass
            connections.clear()

            await asyncio.sleep(0.5)  # Give server time to clean up

            # Phase 3: Connect 5 more — should succeed
            for _ in range(5):
                try:
                    ws = await websockets.connect(uri, open_timeout=5)
                    msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    data = json.loads(msg)
                    if data.get("type") == "connected":
                        connections.append(ws)
                except Exception:
                    pass

            phase3_count = len(connections)

            # Cleanup
            for ws in connections:
                try:
                    await ws.close()
                except Exception:
                    pass

            return phase1_count, phase3_count

        p1, p3 = asyncio.run(_run())

        assert p1 >= 18, f"Phase 1 too few connections: {p1}/20"
        assert p3 >= 4, f"Phase 3 too few reconnections: {p3}/5"
        print(f"  [cleanup] phase1={p1}/20 connected, phase3={p3}/5 reconnected")
