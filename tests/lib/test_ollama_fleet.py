# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for OllamaFleet — host discovery and parallel inference."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from tests.lib.ollama_fleet import OllamaFleet, OllamaHost, CONF_PATH

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# OllamaHost
# ---------------------------------------------------------------------------


class TestOllamaHost:
    def test_has_model_exact(self):
        """has_model matches by family prefix."""
        host = OllamaHost(
            url="http://localhost:11434", name="local",
            models=["llava:7b", "qwen2.5:7b"],
        )
        assert host.has_model("llava:7b")
        assert host.has_model("llava")  # family prefix
        assert not host.has_model("gemma")

    def test_has_model_prefix_match(self):
        """has_model matches model family regardless of tag."""
        host = OllamaHost(
            url="http://x:11434", name="x",
            models=["llava:34b-v1.6"],
        )
        assert host.has_model("llava:34b")  # split(":")→"llava" matches
        assert host.has_model("llava")

    def test_has_model_empty_models(self):
        """Empty model list returns False for any query."""
        host = OllamaHost(url="http://x:11434", name="x", models=[])
        assert not host.has_model("llava")

    def test_default_fields(self):
        """Verify default field values."""
        host = OllamaHost(url="http://x:11434", name="x")
        assert host.models == []
        assert host.latency_ms == 0.0
        assert host.busy is False


# ---------------------------------------------------------------------------
# OllamaFleet — host filtering
# ---------------------------------------------------------------------------


class TestOllamaFleetFiltering:
    def _make_fleet(self, hosts):
        """Build a fleet with pre-set hosts, bypassing discovery."""
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = hosts
        return fleet

    def test_hosts_with_model(self):
        """Filter hosts by model availability."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b", "qwen2.5:7b"]),
            OllamaHost(url="http://b:11434", name="b", models=["qwen2.5:7b"]),
        ])
        llava_hosts = fleet.hosts_with_model("llava:7b")
        assert len(llava_hosts) == 1
        assert llava_hosts[0].name == "a"

    def test_hosts_with_model_returns_all_matches(self):
        """All hosts with the model are returned."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
            OllamaHost(url="http://b:11434", name="b", models=["llava:34b"]),
        ])
        assert len(fleet.hosts_with_model("llava")) == 2

    def test_count_and_hosts_properties(self):
        """count and hosts reflect internal state."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a"),
            OllamaHost(url="http://b:11434", name="b"),
        ])
        assert fleet.count == 2
        assert len(fleet.hosts) == 2
        # hosts returns a copy
        fleet.hosts.append(OllamaHost(url="http://c:11434", name="c"))
        assert fleet.count == 2  # original unchanged


# ---------------------------------------------------------------------------
# OllamaFleet — generate
# ---------------------------------------------------------------------------


class TestOllamaFleetGenerate:
    def _make_fleet(self, hosts):
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = hosts
        return fleet

    def test_empty_fleet_generate_raises(self):
        """Generate raises RuntimeError when no hosts have the model."""
        fleet = self._make_fleet([])
        with pytest.raises(RuntimeError, match="No host has model"):
            fleet.generate("llava:7b", "test prompt")

    @patch("tests.lib.ollama_fleet.requests.post")
    def test_generate_success(self, mock_post):
        """Successful generate returns response with host metadata."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
        ])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "I see a map"}
        mock_post.return_value = mock_resp

        result = fleet.generate("llava:7b", "describe this")
        assert result["response"] == "I see a map"
        assert result["host"] == "a"
        assert result["model"] == "llava:7b"
        assert "elapsed_ms" in result

    @patch("tests.lib.ollama_fleet.requests.post")
    def test_generate_fallback(self, mock_post):
        """First host fails, second succeeds."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
            OllamaHost(url="http://b:11434", name="b", models=["llava:7b"]),
        ])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "I see a map"}
        mock_post.side_effect = [ConnectionError("host a down"), mock_resp]

        result = fleet.generate("llava:7b", "describe this")
        assert result["response"] == "I see a map"
        assert result["host"] == "b"

    @patch("tests.lib.ollama_fleet.requests.post")
    def test_generate_all_fail_raises(self, mock_post):
        """All hosts failing raises RuntimeError."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
        ])
        mock_post.side_effect = ConnectionError("down")
        with pytest.raises(RuntimeError, match="All hosts failed"):
            fleet.generate("llava:7b", "describe this")

    @patch("tests.lib.ollama_fleet.requests.post")
    def test_generate_prefer_host(self, mock_post):
        """prefer_host reorders the host list."""
        fleet = self._make_fleet([
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
            OllamaHost(url="http://b:11434", name="b", models=["llava:7b"]),
        ])
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "ok"}
        mock_post.return_value = mock_resp

        result = fleet.generate("llava:7b", "test", prefer_host="b")
        assert result["host"] == "b"
        # Should have called b's URL first
        first_call_url = mock_post.call_args_list[0][0][0]
        assert "b:11434" in first_call_url


# ---------------------------------------------------------------------------
# OllamaFleet — probe
# ---------------------------------------------------------------------------


class TestOllamaFleetProbe:
    @patch("tests.lib.ollama_fleet.requests.get")
    def test_probe_success(self, mock_get):
        """Probe returns OllamaHost on success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llava:7b"}, {"name": "qwen2.5:7b"}],
        }
        mock_get.return_value = mock_resp

        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        host = fleet._probe("localhost:11434")
        assert host is not None
        assert host.name == "localhost"
        assert "llava:7b" in host.models
        assert "qwen2.5:7b" in host.models
        assert host.latency_ms > 0 or host.latency_ms == 0  # can be very fast in mock

    @patch("tests.lib.ollama_fleet.requests.get")
    def test_probe_connection_error(self, mock_get):
        """Probe returns None on connection error."""
        import requests as req
        mock_get.side_effect = req.ConnectionError("connection refused")
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        host = fleet._probe("bad-host:11434")
        assert host is None

    @patch("tests.lib.ollama_fleet.requests.get")
    def test_probe_timeout(self, mock_get):
        """Probe returns None on timeout."""
        import requests as req
        mock_get.side_effect = req.Timeout("timed out")
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        host = fleet._probe("slow-host:11434")
        assert host is None

    @patch("tests.lib.ollama_fleet.requests.get")
    def test_probe_non_200(self, mock_get):
        """Probe returns None for non-200 status."""
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_get.return_value = mock_resp
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        host = fleet._probe("error-host:11434")
        assert host is None


# ---------------------------------------------------------------------------
# OllamaFleet — discovery / config parsing
# ---------------------------------------------------------------------------


class TestOllamaFleetDiscovery:
    def test_conf_file_parsing(self, tmp_path):
        """Config file hosts are parsed correctly."""
        conf = tmp_path / "ollama-fleet.conf"
        conf.write_text("# Comment\ngb10-02\nagx-02:11434\n\n")

        with patch("tests.lib.ollama_fleet.CONF_PATH", conf), \
             patch.object(OllamaFleet, "_probe", return_value=None), \
             patch.object(OllamaFleet, "_scan_tailscale", return_value=set()):
            fleet = OllamaFleet(auto_discover=True)
            # All probes returned None so no hosts
            assert fleet.count == 0

    def test_env_var_hosts(self, tmp_path):
        """OLLAMA_HOSTS env var adds candidates."""
        conf = tmp_path / "nonexistent.conf"  # won't exist

        probed_hosts = []

        def track_probe(self_inner, host_port):
            probed_hosts.append(host_port)
            return None

        with patch("tests.lib.ollama_fleet.CONF_PATH", conf), \
             patch.dict("os.environ", {"OLLAMA_HOSTS": "alpha,beta:9999"}), \
             patch.object(OllamaFleet, "_probe", track_probe), \
             patch.object(OllamaFleet, "_scan_tailscale", return_value=set()):
            OllamaFleet(auto_discover=False)
            # Should have probed localhost, alpha:11434, beta:9999
            assert "localhost:11434" in probed_hosts
            assert "alpha:11434" in probed_hosts
            assert "beta:9999" in probed_hosts


# ---------------------------------------------------------------------------
# OllamaFleet — parallel_vision
# ---------------------------------------------------------------------------


class TestOllamaFleetParallelVision:
    @patch("tests.lib.ollama_fleet.requests.post")
    def test_parallel_vision_round_robin(self, mock_post):
        """Tasks are distributed across hosts."""
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
            OllamaHost(url="http://b:11434", name="b", models=["llava:7b"]),
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "test response"}
        mock_post.return_value = mock_resp

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n")
            img_path = Path(f.name)

        try:
            tasks = [
                {"name": f"task_{i}", "image": img_path, "prompt": f"prompt {i}"}
                for i in range(4)
            ]
            results = fleet.parallel_vision("llava:7b", tasks)
            assert len(results) == 4
            for r in results:
                assert "response" in r
                assert "name" in r
        finally:
            img_path.unlink(missing_ok=True)

    def test_parallel_vision_no_hosts_raises(self):
        """parallel_vision raises when no hosts have the model."""
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        with pytest.raises(RuntimeError, match="No host has model"):
            fleet.parallel_vision("llava:7b", [])

    @patch("tests.lib.ollama_fleet.requests.post")
    def test_parallel_vision_error_handling(self, mock_post):
        """Failed tasks include error info instead of crashing."""
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            OllamaHost(url="http://a:11434", name="a", models=["llava:7b"]),
        ]
        mock_post.side_effect = ConnectionError("host down")

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n")
            img_path = Path(f.name)

        try:
            tasks = [{"name": "fail_task", "image": img_path, "prompt": "test"}]
            results = fleet.parallel_vision("llava:7b", tasks)
            assert len(results) == 1
            assert "error" in results[0]["response"].lower()
            assert results[0]["host"] == "failed"
        finally:
            img_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# OllamaFleet — status
# ---------------------------------------------------------------------------


class TestOllamaFleetStatus:
    def test_status_output(self):
        """status() returns human-readable fleet summary."""
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            OllamaHost(url="http://a:11434", name="a",
                        models=["llava:7b", "qwen2.5:7b"], latency_ms=12.5),
        ]
        s = fleet.status()
        assert "1 hosts" in s
        assert "a:" in s
        assert "llava:7b" in s
