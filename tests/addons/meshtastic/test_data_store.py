# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Tests for Meshtastic persistent data store."""

import asyncio
import os
import tempfile
import time

import pytest
import pytest_asyncio

from addons.meshtastic.meshtastic_addon.data_store import MeshtasticDataStore


@pytest_asyncio.fixture
async def store(tmp_path):
    """Create a temporary data store for testing."""
    db_path = str(tmp_path / "test_meshtastic.db")
    s = MeshtasticDataStore(db_path=db_path)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_store_and_retrieve_node(store):
    """Store a node and verify it persists."""
    node = {
        "node_id": "!aabbccdd",
        "long_name": "Test Node",
        "short_name": "TST",
        "hw_model": "TBEAM",
        "role": "ROUTER",
        "lat": 40.7128,
        "lng": -74.0060,
        "altitude": 10.0,
        "battery": 85,
        "voltage": 3.8,
        "snr": 7.5,
        "channel_util": 12.3,
    }
    await store.store_node(node)

    nodes = await store.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == "!aabbccdd"
    assert nodes[0]["long_name"] == "Test Node"
    assert nodes[0]["hw_model"] == "TBEAM"


@pytest.mark.asyncio
async def test_node_upsert(store):
    """Storing the same node twice updates last_seen but preserves first_seen."""
    node = {"node_id": "!112233", "long_name": "Alpha"}
    await store.store_node(node)

    nodes = await store.get_all_nodes()
    first_seen_1 = nodes[0]["first_seen"]

    # Small delay to ensure different timestamp
    await asyncio.sleep(0.05)

    node2 = {"node_id": "!112233", "long_name": "Alpha Updated"}
    await store.store_node(node2)

    nodes = await store.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0]["first_seen"] == first_seen_1  # Preserved
    assert nodes[0]["last_seen"] > first_seen_1  # Updated
    assert nodes[0]["long_name"] == "Alpha Updated"


@pytest.mark.asyncio
async def test_position_history(store):
    """Store multiple positions and retrieve history."""
    for i in range(5):
        await store.store_node({
            "node_id": "!pos_test",
            "lat": 40.0 + i * 0.001,
            "lng": -74.0 + i * 0.001,
            "altitude": 10.0 + i,
        })

    history = await store.get_node_history("!pos_test")
    assert len(history["positions"]) == 5
    assert history["positions"][0]["lat"] == pytest.approx(40.0, abs=0.01)
    assert history["positions"][4]["lat"] == pytest.approx(40.004, abs=0.01)


@pytest.mark.asyncio
async def test_telemetry_history(store):
    """Store telemetry and retrieve history."""
    for i in range(3):
        await store.store_node({
            "node_id": "!tel_test",
            "battery": 100 - i * 10,
            "voltage": 4.2 - i * 0.1,
            "snr": 10.0 - i,
        })

    history = await store.get_node_history("!tel_test")
    assert len(history["telemetry"]) == 3
    assert history["telemetry"][0]["battery"] == 100


@pytest.mark.asyncio
async def test_store_and_query_messages(store):
    """Store messages and query with filters."""
    await store.store_message({
        "sender_id": "!node1",
        "sender_name": "Node One",
        "text": "Hello world",
        "channel": 0,
        "type": "text",
        "timestamp": time.time() - 60,
    })
    await store.store_message({
        "sender_id": "!node2",
        "sender_name": "Node Two",
        "text": "Position update",
        "channel": 1,
        "type": "position",
        "timestamp": time.time(),
    })

    # All messages
    msgs = await store.get_message_history()
    assert len(msgs) == 2

    # Filter by type
    text_msgs = await store.get_message_history(msg_type="text")
    assert len(text_msgs) == 1
    assert text_msgs[0]["text"] == "Hello world"

    # Filter by channel
    ch1_msgs = await store.get_message_history(channel=1)
    assert len(ch1_msgs) == 1
    assert ch1_msgs[0]["type"] == "position"


@pytest.mark.asyncio
async def test_stats_snapshot(store):
    """Store and retrieve stats snapshots."""
    await store.store_stats_snapshot({
        "total_nodes": 250,
        "online_nodes": 180,
        "with_gps": 120,
        "avg_snr": 5.5,
        "avg_battery": 72.0,
    })
    await store.store_stats_snapshot({
        "total_nodes": 252,
        "online_nodes": 185,
        "with_gps": 125,
        "avg_snr": 6.0,
        "avg_battery": 71.0,
    })

    stats = await store.get_stats_history()
    assert len(stats) == 2
    assert stats[0]["total_nodes"] == 250
    assert stats[1]["total_nodes"] == 252


@pytest.mark.asyncio
async def test_node_count_over_time(store):
    """Get node count trend from stats."""
    for i in range(3):
        await store.store_stats_snapshot({
            "total_nodes": 100 + i * 10,
            "online_nodes": 80 + i * 5,
            "with_gps": 50,
        })

    trend = await store.get_node_count_over_time()
    assert len(trend) == 3
    assert trend[0]["total_nodes"] == 100
    assert trend[2]["total_nodes"] == 120


@pytest.mark.asyncio
async def test_signal_quality_trend(store):
    """Get SNR trend for a node."""
    for i in range(4):
        await store.store_node({
            "node_id": "!snr_test",
            "snr": 5.0 + i * 0.5,
        })

    trend = await store.get_signal_quality_trend("!snr_test")
    assert len(trend) == 4
    assert trend[0]["snr"] == 5.0
    assert trend[3]["snr"] == 6.5


@pytest.mark.asyncio
async def test_node_count(store):
    """Test get_node_count method."""
    assert await store.get_node_count() == 0
    await store.store_node({"node_id": "!a"})
    await store.store_node({"node_id": "!b"})
    assert await store.get_node_count() == 2


@pytest.mark.asyncio
async def test_empty_store_returns_empty(store):
    """Querying an empty store returns empty results."""
    assert await store.get_all_nodes() == []
    assert await store.get_message_history() == []
    assert await store.get_stats_history() == []
    assert await store.get_node_count_over_time() == []
    assert await store.get_signal_quality_trend("!nonexistent") == []
    history = await store.get_node_history("!nonexistent")
    assert history == {"positions": [], "telemetry": []}


@pytest.mark.asyncio
async def test_message_history_since_filter(store):
    """Test since filter on message history."""
    old_ts = time.time() - 3600
    new_ts = time.time()

    await store.store_message({"sender_id": "!a", "text": "old", "timestamp": old_ts})
    await store.store_message({"sender_id": "!b", "text": "new", "timestamp": new_ts})

    recent = await store.get_message_history(since=time.time() - 60)
    assert len(recent) == 1
    assert recent[0]["text"] == "new"
