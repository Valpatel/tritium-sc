"""Unit tests for OllamaFleet production module — multi-host discovery.

Tests FleetHost, OllamaFleet discovery (mocked), model filtering,
and status reporting. No network calls in unit tests.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ===========================================================================
# FleetHost Dataclass
# ===========================================================================

@pytest.mark.unit
class TestFleetHost:
    """FleetHost — reachable Ollama instance."""

    def test_construction(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(url="http://localhost:11434", name="localhost")
        assert h.url == "http://localhost:11434"
        assert h.name == "localhost"

    def test_defaults(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(url="http://x:11434", name="x")
        assert h.models == []
        assert h.latency_ms == 0.0

    def test_has_model_exact(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(
            url="http://x:11434", name="x",
            models=["gemma3:4b", "llava:7b"],
        )
        assert h.has_model("gemma3:4b")
        assert h.has_model("llava:7b")

    def test_has_model_prefix(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(
            url="http://x:11434", name="x",
            models=["llava:7b", "llava:13b"],
        )
        assert h.has_model("llava")  # Prefix match

    def test_has_model_missing(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(
            url="http://x:11434", name="x",
            models=["gemma3:4b"],
        )
        assert not h.has_model("llava:7b")

    def test_has_model_empty(self):
        from amy.inference.fleet import FleetHost
        h = FleetHost(url="http://x:11434", name="x")
        assert not h.has_model("anything")


# ===========================================================================
# OllamaFleet — Construction (mocked discovery)
# ===========================================================================

@pytest.mark.unit
class TestOllamaFleetInit:
    """OllamaFleet — initialization with mocked network."""

    def test_construction_no_discover(self):
        from amy.inference.fleet import OllamaFleet
        with patch.object(OllamaFleet, '_discover'):
            fleet = OllamaFleet.__new__(OllamaFleet)
            fleet._hosts = []
            assert fleet.count == 0

    def test_hosts_property(self):
        from amy.inference.fleet import OllamaFleet, FleetHost
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            FleetHost(url="http://a:11434", name="a"),
            FleetHost(url="http://b:11434", name="b"),
        ]
        assert fleet.count == 2
        assert len(fleet.hosts) == 2

    def test_hosts_is_copy(self):
        from amy.inference.fleet import OllamaFleet, FleetHost
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [FleetHost(url="http://a:11434", name="a")]
        hosts = fleet.hosts
        hosts.clear()
        assert fleet.count == 1  # Original not modified


# ===========================================================================
# OllamaFleet — Model Filtering
# ===========================================================================

@pytest.mark.unit
class TestOllamaFleetFiltering:
    """OllamaFleet.hosts_with_model — filter by capability."""

    def _fleet_with_hosts(self):
        from amy.inference.fleet import OllamaFleet, FleetHost
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            FleetHost(
                url="http://host1:11434", name="host1",
                models=["gemma3:4b", "llava:7b"], latency_ms=10,
            ),
            FleetHost(
                url="http://host2:11434", name="host2",
                models=["gemma3:4b", "qwen2.5:7b"], latency_ms=20,
            ),
            FleetHost(
                url="http://host3:11434", name="host3",
                models=["llava:7b", "llava:34b"], latency_ms=40,
            ),
        ]
        return fleet

    def test_hosts_with_common_model(self):
        fleet = self._fleet_with_hosts()
        hosts = fleet.hosts_with_model("gemma3:4b")
        assert len(hosts) == 2
        assert hosts[0].name == "host1"  # Sorted by latency

    def test_hosts_with_rare_model(self):
        fleet = self._fleet_with_hosts()
        hosts = fleet.hosts_with_model("qwen2.5:7b")
        assert len(hosts) == 1
        assert hosts[0].name == "host2"

    def test_hosts_with_vision_prefix(self):
        fleet = self._fleet_with_hosts()
        hosts = fleet.hosts_with_model("llava")
        assert len(hosts) == 2

    def test_hosts_with_no_match(self):
        fleet = self._fleet_with_hosts()
        hosts = fleet.hosts_with_model("nonexistent:1b")
        assert hosts == []

    def test_best_host(self):
        fleet = self._fleet_with_hosts()
        best = fleet.best_host("llava:7b")
        assert best is not None
        assert best.name == "host1"  # Lowest latency

    def test_best_host_missing(self):
        fleet = self._fleet_with_hosts()
        assert fleet.best_host("nonexistent") is None


# ===========================================================================
# OllamaFleet — Status
# ===========================================================================

@pytest.mark.unit
class TestOllamaFleetStatus:
    """OllamaFleet.status — human-readable fleet report."""

    def test_status_empty(self):
        from amy.inference.fleet import OllamaFleet
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []
        assert "no hosts" in fleet.status().lower()

    def test_status_with_hosts(self):
        from amy.inference.fleet import OllamaFleet, FleetHost
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = [
            FleetHost(
                url="http://host1:11434", name="host1",
                models=["gemma3:4b", "llava:7b"], latency_ms=12.5,
            ),
        ]
        status = fleet.status()
        assert "1 host" in status
        assert "host1" in status
        assert "2 models" in status
        assert "llava" in status


# ===========================================================================
# OllamaFleet — Tailscale Scanning (mocked)
# ===========================================================================

@pytest.mark.unit
class TestOllamaFleetTailscale:
    """OllamaFleet._scan_tailscale — Tailscale peer discovery."""

    def test_scan_finds_peers(self):
        from amy.inference.fleet import OllamaFleet
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []

        tailscale_output = {
            "Peer": {
                "abc123": {"HostName": "gb10-02", "Online": True},
                "def456": {"HostName": "agx-02", "Online": True},
                "ghi789": {"HostName": "offline-host", "Online": False},
            }
        }

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=__import__("json").dumps(tailscale_output),
            )
            hosts = fleet._scan_tailscale()
            assert "gb10-02:11434" in hosts
            assert "agx-02:11434" in hosts
            assert "offline-host:11434" not in hosts

    def test_scan_tailscale_not_installed(self):
        from amy.inference.fleet import OllamaFleet
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []

        with patch("subprocess.run", side_effect=FileNotFoundError):
            hosts = fleet._scan_tailscale()
            assert hosts == set()

    def test_scan_tailscale_timeout(self):
        from amy.inference.fleet import OllamaFleet
        import subprocess

        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("tailscale", 5)):
            hosts = fleet._scan_tailscale()
            assert hosts == set()


# ===========================================================================
# OllamaFleet — Conf File Parsing (mocked)
# ===========================================================================

@pytest.mark.unit
class TestOllamaFleetConf:
    """OllamaFleet discovery from conf file."""

    def test_conf_parsing(self):
        from amy.inference.fleet import OllamaFleet
        fleet = OllamaFleet.__new__(OllamaFleet)
        fleet._hosts = []

        conf_content = """# Ollama fleet hosts
gb10-02
agx-02:11434
# commented-out-host
"""
        with patch("amy.inference.fleet.CONF_PATH") as mock_path:
            mock_path.exists.return_value = True
            mock_path.read_text.return_value = conf_content

            with patch.object(fleet, '_scan_tailscale', return_value=set()):
                with patch.object(fleet, '_probe', return_value=None):
                    fleet._discover(auto_discover=False)
                    # Should have tried probing localhost + conf hosts
                    # (even though they all return None)
                    assert fleet.count == 0  # All probes failed (mocked)
