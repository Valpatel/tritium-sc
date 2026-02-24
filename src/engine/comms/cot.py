"""CoT (Cursor on Target) XML generation and parsing.

Pure functions for converting TRITIUM targets to/from MIL-STD-2045 CoT XML.
Zero external dependencies (only xml.etree.ElementTree).

CoT is the lingua franca of TAK (Team Awareness Kit) — ATAK, WinTAK, WebTAK
all speak it.  This module handles the XML serialization; the transport layer
(TCP/TLS to a TAK server via pytak) lives in tak_bridge.py.

Reference: https://git.tak.gov/standards/cot
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from engine.tactical.geo import latlng_to_local


# ---------------------------------------------------------------------------
# Type mapping: resolved dynamically from unit type registry
# ---------------------------------------------------------------------------

# Fallback by alliance only (when no registry match)
_ALLIANCE_FALLBACK: dict[str, str] = {
    "friendly": "a-f-G",
    "hostile":  "a-h-G",
    "neutral":  "a-n-G",
    "unknown":  "a-u-G",
}


def _resolve_cot_type(asset_type: str, alliance: str) -> str:
    """Resolve CoT type code via unit type registry with alliance swap."""
    from engine.units import cot_type_for_target
    code = cot_type_for_target(asset_type, alliance)
    if code:
        return code
    return _ALLIANCE_FALLBACK.get(alliance, "a-u-G")

# How codes by source
_HOW_MAP: dict[str, str] = {
    "simulation": "m-s",   # machine-simulated
    "yolo":       "m-r",   # machine-reported (sensor)
    "mqtt":       "m-g",   # machine-GPS derived
    "manual":     "h-e",   # human-estimated
}

# Team colors by alliance
_TEAM_COLORS: dict[str, str] = {
    "friendly": "Cyan",
    "hostile":  "Red",
    "neutral":  "White",
    "unknown":  "Yellow",
}

# Reverse type mapping: built lazily from unit type registry
_reverse_type_cache: list[tuple[str, str]] | None = None

# Hostile type IDs only get their original affiliation in reverse lookup
_HOSTILE_TYPE_IDS = {"hostile_person", "hostile_leader", "hostile_vehicle"}

# Legacy short-prefix fallbacks for backward compat with old ATAK codes
_LEGACY_REVERSE: list[tuple[str, str]] = [
    ("a-f-A",   "drone"),
    ("a-h-A",   "drone"),
    ("a-f-G-E", "rover"),
    ("a-h-G-E", "rover"),
    ("a-f-G-U", "person"),
    ("a-h-G-U", "person"),
    ("a-n-G-U", "person"),
    ("a-u-G",   "person"),
]


def _get_reverse_type() -> list[tuple[str, str]]:
    """Return the reverse type mapping, building it lazily on first call."""
    global _reverse_type_cache
    if _reverse_type_cache is not None:
        return _reverse_type_cache
    _reverse_type_cache = _build_reverse_type()
    return _reverse_type_cache


def _build_reverse_type() -> list[tuple[str, str]]:
    """Build reverse type mapping from unit type registry.

    - Non-hostile types are cross-affiliated (all 4 affiliation variants).
    - Hostile types keep only their original affiliation entry.
    - Sorted longest-first so more specific codes match before generic.
    - Legacy short prefixes appended as fallbacks.
    """
    from engine.units import all_types

    entries: dict[str, str] = {}
    for cls in all_types():
        code = cls.cot_type
        if len(code) < 3:
            continue
        if cls.type_id in _HOSTILE_TYPE_IDS:
            if code not in entries:
                entries[code] = cls.type_id
        else:
            suffix = code[3:]
            for affil in ("f", "h", "n", "u"):
                new_code = f"a-{affil}{suffix}"
                if new_code not in entries:
                    entries[new_code] = cls.type_id

    result = sorted(entries.items(), key=lambda x: -len(x[0]))

    seen = {code for code, _ in result}
    for code, tid in _LEGACY_REVERSE:
        if code not in seen:
            result.append((code, tid))

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def target_to_cot_xml(
    target_dict: dict,
    stale_seconds: int = 120,
    opex: str = "s",
) -> str:
    """Convert a TRITIUM target dict to CoT XML string.

    Args:
        target_dict: Output of SimulationTarget.to_dict() or TrackedTarget.to_dict()
        stale_seconds: Seconds until the position report goes stale
        opex: Operational exercise code ("s"=simulation, "e"=exercise, "o"=operational)

    Returns:
        CoT XML string ready for TAK server transmission
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Resolve type code via unit type registry
    asset_type = target_dict.get("asset_type", "person")
    alliance = target_dict.get("alliance", "unknown")
    cot_type = _resolve_cot_type(asset_type, alliance)

    # How code from source
    source = target_dict.get("source", "simulation")
    how = _HOW_MAP.get(source, "m-s")

    # Build XML tree
    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", target_dict.get("target_id", "unknown"))
    event.set("type", cot_type)
    event.set("how", how)
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)
    event.set("opex", opex)

    # Point
    point = ET.SubElement(event, "point")
    point.set("lat", str(target_dict.get("lat", 0.0)))
    point.set("lon", str(target_dict.get("lng", 0.0)))
    point.set("hae", str(target_dict.get("alt", 0.0)))
    point.set("ce", "10.0")
    point.set("le", "10.0")

    # Detail
    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    name = target_dict.get("name", target_dict.get("target_id", "unknown"))
    contact.set("callsign", name)

    group = ET.SubElement(detail, "__group")
    group.set("name", _TEAM_COLORS.get(alliance, "Yellow"))
    group.set("role", "Team Member")

    status = ET.SubElement(detail, "status")
    battery_pct = target_dict.get("battery", 1.0) * 100.0
    status.set("battery", str(round(battery_pct, 1)))

    track = ET.SubElement(detail, "track")
    track.set("speed", str(target_dict.get("speed", 0.0)))
    track.set("course", str(target_dict.get("heading", 0.0)))

    remarks = ET.SubElement(detail, "remarks")
    health = target_dict.get("health", 0)
    max_health = target_dict.get("max_health", 0)
    kills = target_dict.get("kills", 0)
    tgt_status = target_dict.get("status", "unknown")
    remarks.text = f"health:{health}/{max_health} kills:{kills} status:{tgt_status}"

    uid_elem = ET.SubElement(detail, "uid")
    uid_elem.set("Droid", name)

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


# ---------------------------------------------------------------------------
# GeoChat
# ---------------------------------------------------------------------------

def geochat_to_cot_xml(
    sender_uid: str,
    sender_callsign: str,
    message: str,
    lat: float = 0.0,
    lng: float = 0.0,
    alt: float = 0.0,
    to_callsign: str = "All Chat Rooms",
    to_uid: str = "All Chat Rooms",
) -> str:
    """Generate a GeoChat CoT XML message.

    Args:
        sender_uid: UID of the sender (e.g. "TRITIUM-SC")
        sender_callsign: Human-readable callsign
        message: Chat message text
        lat: Sender latitude (optional)
        lng: Sender longitude (optional)
        alt: Sender altitude (optional)
        to_callsign: Recipient callsign ("All Chat Rooms" for broadcast)
        to_uid: Recipient UID

    Returns:
        CoT XML string for GeoChat
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    uid = f"GeoChat.{sender_uid}.{to_callsign}.{now_str}"

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", uid)
    event.set("type", "b-t-f")  # Bits-Text-Free (GeoChat)
    event.set("how", "h-g-i-g-o")
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "999999")
    point.set("le", "999999")

    detail = ET.SubElement(event, "detail")

    chat = ET.SubElement(detail, "__chat")
    chat.set("senderCallsign", sender_callsign)
    chat.set("chatroom", to_callsign)
    chat.set("id", to_uid)
    chat.set("parent", "RootContactGroup")

    chat_group = ET.SubElement(chat, "chatgrp")
    chat_group.set("uid0", sender_uid)
    chat_group.set("uid1", to_uid)
    chat_group.set("id", to_uid)

    link = ET.SubElement(detail, "link")
    link.set("uid", sender_uid)
    link.set("type", "a-f-G-E-C-I")
    link.set("relation", "p-p")

    remarks = ET.SubElement(detail, "remarks")
    remarks.set("source", sender_uid)
    remarks.set("to", to_uid)
    remarks.set("time", now_str)
    remarks.text = message

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_geochat(xml_string: str) -> dict | None:
    """Parse inbound GeoChat CoT XML into a message dict.

    Args:
        xml_string: Raw CoT XML from TAK server

    Returns:
        Dict with sender_uid, sender_callsign, message, lat, lng, or None
        if the XML is not a GeoChat message.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if cot_type != "b-t-f":
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")
    if detail is None:
        return None

    remarks = detail.find("remarks")
    message = remarks.text if remarks is not None and remarks.text else ""
    sender_uid = remarks.get("source", "") if remarks is not None else ""

    chat = detail.find("__chat")
    sender_callsign = chat.get("senderCallsign", sender_uid) if chat is not None else sender_uid
    chatroom = chat.get("chatroom", "") if chat is not None else ""

    uid = root.get("uid", "")

    return {
        "uid": uid,
        "sender_uid": sender_uid,
        "sender_callsign": sender_callsign,
        "message": message,
        "chatroom": chatroom,
        "lat": lat,
        "lng": lng,
        "timestamp": root.get("time", ""),
    }


def cot_xml_to_target(xml_string: str) -> dict | None:
    """Parse inbound CoT XML into a TRITIUM target dict.

    Args:
        xml_string: Raw CoT XML from TAK server

    Returns:
        Target dict compatible with TargetTracker.update_from_simulation(),
        or None if the XML is malformed or missing required elements.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    # Point element is required
    point = root.find("point")
    if point is None:
        return None

    uid = root.get("uid", "unknown")
    cot_type = root.get("type", "a-u-G")

    # Infer alliance from type code
    alliance = "unknown"
    if len(cot_type) >= 3:
        affil = cot_type[2]  # a-{f/h/n/u}-...
        alliance = {"f": "friendly", "h": "hostile", "n": "neutral"}.get(affil, "unknown")

    # Infer asset_type from type code (dynamic registry lookup)
    asset_type = "person"  # default
    for prefix, a_type in _get_reverse_type():
        if cot_type.startswith(prefix):
            asset_type = a_type
            break

    # Parse position
    lat = float(point.get("lat", 0.0))
    lon = float(point.get("lon", 0.0))
    hae = float(point.get("hae", 0.0))
    x, y, z = latlng_to_local(lat, lon, hae)

    # Detail parsing
    detail = root.find("detail")
    callsign = uid
    speed = 0.0
    heading = 0.0

    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", uid)

        track_elem = detail.find("track")
        if track_elem is not None:
            speed = float(track_elem.get("speed", 0.0))
            heading = float(track_elem.get("course", 0.0))

    return {
        "target_id": uid,
        "name": callsign,
        "alliance": alliance,
        "asset_type": asset_type,
        "position": {"x": x, "y": y},
        "lat": lat,
        "lng": lon,
        "alt": hae,
        "heading": heading,
        "speed": speed,
        "battery": 1.0,
        "status": "active",
        "source": "tak",
    }


# ---------------------------------------------------------------------------
# Video Feed
# ---------------------------------------------------------------------------

def video_feed_to_cot(
    feed_id: str,
    feed_url: str,
    lat: float = 0.0,
    lng: float = 0.0,
    alt: float = 0.0,
    stale_seconds: int = 300,
    callsign: str = "",
    mime_type: str = "video/mp4",
) -> str:
    """Generate CoT XML to advertise a video feed to TAK clients.

    type="b-i-v" (Bits-Image-Video)
    Detail includes <__video> element with connection info.

    Args:
        feed_id: Unique identifier for the feed (e.g. "cam-01")
        feed_url: Stream URL (e.g. "rtsp://192.168.1.100:554/stream1")
        lat: Feed source latitude
        lng: Feed source longitude
        alt: Feed source altitude
        stale_seconds: Seconds until the feed advertisement goes stale
        callsign: Human-readable name for the feed (defaults to feed_id)
        mime_type: MIME type of the video stream (default "video/mp4")

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    display_name = callsign if callsign else feed_id

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"video-{feed_id}")
    event.set("type", "b-i-v")
    event.set("how", "m-g")
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "999999")
    point.set("le", "999999")

    detail = ET.SubElement(event, "detail")

    video = ET.SubElement(detail, "__video")
    video.set("url", feed_url)
    video.set("uid", feed_id)
    video.set("mimeType", mime_type)

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", display_name)

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_video_feed(xml_string: str) -> dict | None:
    """Parse video feed CoT XML.

    Returns dict with feed_id, url, callsign, lat, lng,
    or None if the XML is not a video feed message.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if cot_type != "b-i-v":
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")

    feed_id = ""
    url = ""
    callsign = ""

    if detail is not None:
        video = detail.find("__video")
        if video is not None:
            url = video.get("url", "")
            feed_id = video.get("uid", "")

        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", "")

    # Fallback: extract feed_id from uid if not in video element
    if not feed_id:
        uid = root.get("uid", "")
        if uid.startswith("video-"):
            feed_id = uid[6:]
        else:
            feed_id = uid

    return {
        "feed_id": feed_id,
        "url": url,
        "callsign": callsign,
        "lat": lat,
        "lng": lng,
    }


# ---------------------------------------------------------------------------
# Emergency
# ---------------------------------------------------------------------------

# Emergency type mapping: friendly names -> CoT type codes
_EMERGENCY_TYPE_MAP: dict[str, str] = {
    "911":    "b-a-o-tbl",   # Trouble / 911
    "sos":    "b-a-o-tbl",   # SOS (same as 911)
    "alert":  "b-a-o-tbl",   # Generic alert
    "cancel": "b-a-o-can",   # Cancel emergency
    "medic":  "b-a-o-tbl",   # Medical emergency
    "fire":   "b-a-o-tbl",   # Fire emergency
}

# Reverse mapping: CoT type -> friendly name
_EMERGENCY_REVERSE: dict[str, str] = {
    "b-a-o-tbl": "911",
    "b-a-o-can": "cancel",
}


def emergency_to_cot(
    callsign: str,
    emergency_type: str,
    lat: float,
    lng: float,
    alt: float = 0.0,
    remarks: str = "",
) -> str:
    """Generate emergency CoT XML.

    Args:
        callsign: Sender callsign
        emergency_type: One of "911", "sos", "alert", "cancel"
        lat: Emergency location latitude
        lng: Emergency location longitude
        alt: Altitude
        remarks: Free-text description

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    cot_type = _EMERGENCY_TYPE_MAP.get(emergency_type, "b-a-o-tbl")

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"emergency-{callsign}")
    event.set("type", cot_type)
    event.set("how", "h-e")
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "10.0")
    point.set("le", "10.0")

    detail = ET.SubElement(event, "detail")

    contact_elem = ET.SubElement(detail, "contact")
    contact_elem.set("callsign", callsign)

    emergency_elem = ET.SubElement(detail, "emergency")
    emergency_elem.set("type", emergency_type)

    remarks_elem = ET.SubElement(detail, "remarks")
    remarks_elem.text = remarks if remarks else f"Emergency ({emergency_type}) from {callsign}"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_emergency(xml_string: str) -> dict | None:
    """Parse emergency CoT XML.

    Returns dict with callsign, emergency_type, lat, lng, remarks,
    or None if the XML is not an emergency message.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if not cot_type.startswith("b-a-o"):
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")

    callsign = ""
    emergency_type = _EMERGENCY_REVERSE.get(cot_type, "alert")
    remarks_text = ""

    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", "")

        emergency_elem = detail.find("emergency")
        if emergency_elem is not None:
            emergency_type = emergency_elem.get("type", emergency_type)

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            remarks_text = remarks.text

    return {
        "callsign": callsign,
        "emergency_type": emergency_type,
        "lat": lat,
        "lng": lng,
        "remarks": remarks_text,
    }


# ---------------------------------------------------------------------------
# Tasking
# ---------------------------------------------------------------------------

def tasking_to_cot(
    task_id: str,
    assignee_uid: str,
    task_type: str,
    lat: float = 0.0,
    lng: float = 0.0,
    remarks: str = "",
) -> str:
    """Generate tasking CoT XML for unit dispatch.

    type="t-x-t-a" (Tasking-Executive-Task-Assignment)

    Args:
        task_id: Unique task identifier
        assignee_uid: UID of the unit being tasked
        task_type: One of "dispatch", "patrol", "recall"
        lat: Task destination latitude
        lng: Task destination longitude
        remarks: Free-text instructions

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"tasking-{task_id}")
    event.set("type", "t-x-t-a")
    event.set("how", "h-e")
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", "0.0")
    point.set("ce", "999999")
    point.set("le", "999999")

    detail = ET.SubElement(event, "detail")

    tasking_elem = ET.SubElement(detail, "tasking")
    tasking_elem.set("task_id", task_id)
    tasking_elem.set("assignee_uid", assignee_uid)
    tasking_elem.set("task_type", task_type)

    remarks_elem = ET.SubElement(detail, "remarks")
    remarks_elem.text = remarks if remarks else f"Task {task_type} for {assignee_uid}"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_tasking(xml_string: str) -> dict | None:
    """Parse tasking CoT XML.

    Returns dict with task_id, assignee_uid, task_type, lat, lng, remarks,
    or None if the XML is not a tasking message.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if not cot_type.startswith("t-x-t"):
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")

    task_id = ""
    assignee_uid = ""
    task_type = ""
    remarks_text = ""

    if detail is not None:
        tasking_elem = detail.find("tasking")
        if tasking_elem is not None:
            task_id = tasking_elem.get("task_id", "")
            assignee_uid = tasking_elem.get("assignee_uid", "")
            task_type = tasking_elem.get("task_type", "")

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            remarks_text = remarks.text

    return {
        "task_id": task_id,
        "assignee_uid": assignee_uid,
        "task_type": task_type,
        "lat": lat,
        "lng": lng,
        "remarks": remarks_text,
    }


# ---------------------------------------------------------------------------
# Sensor Reading
# ---------------------------------------------------------------------------

# Sensor type -> CoT type code mapping
_SENSOR_TYPE_MAP: dict[str, str] = {
    "motion":    "b-s-r",     # Generic sensor reading
    "infrared":  "b-s-r-i",   # Infrared sensor
    "radar":     "b-s-r-r",   # Radar sensor
    "humidity":  "b-s-r-h",   # Humidity sensor
    "pressure":  "b-s-r-p",   # Pressure sensor
    "temperature": "b-s-r-t", # Temperature sensor
}


def sensor_reading_to_cot(
    sensor_id: str,
    lat: float,
    lng: float,
    alt: float = 16.0,
    sensor_type: str = "motion",
    detection_type: str = "human",
    confidence: float = 0.8,
    stale_seconds: int = 300,
) -> str:
    """Generate CoT XML for a sensor reading.

    Args:
        sensor_id: Unique identifier for the sensor
        lat: Sensor latitude
        lng: Sensor longitude
        alt: Sensor altitude
        sensor_type: One of "motion", "infrared", "radar", etc.
        detection_type: What was detected (e.g. "human", "vehicle")
        confidence: Detection confidence (0.0 to 1.0)
        stale_seconds: Seconds until the reading goes stale

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    cot_type = _SENSOR_TYPE_MAP.get(sensor_type, "b-s-r")

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"sensor-{sensor_id}")
    event.set("type", cot_type)
    event.set("how", "m-r")  # machine-reported (sensor)
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "10.0")
    point.set("le", "10.0")

    detail = ET.SubElement(event, "detail")

    sensor_elem = ET.SubElement(detail, "sensor")
    sensor_elem.set("type", sensor_type)
    sensor_elem.set("detection", detection_type)
    sensor_elem.set("confidence", str(confidence))

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", sensor_id)

    remarks_elem = ET.SubElement(detail, "remarks")
    remarks_elem.text = f"Sensor {sensor_id}: {detection_type} detected ({sensor_type}, confidence={confidence:.2f})"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_sensor_reading(xml_string: str) -> dict | None:
    """Parse sensor reading CoT XML.

    Returns dict with sensor_id, sensor_type, detection_type, confidence,
    lat, lng, or None if the XML is not a sensor reading.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if not cot_type.startswith("b-s-r"):
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")

    sensor_id = ""
    sensor_type = "motion"
    detection_type = ""
    confidence = 0.0

    if detail is not None:
        sensor_elem = detail.find("sensor")
        if sensor_elem is not None:
            sensor_type = sensor_elem.get("type", "motion")
            detection_type = sensor_elem.get("detection", "")
            try:
                confidence = float(sensor_elem.get("confidence", 0.0))
            except (ValueError, TypeError):
                confidence = 0.0

        contact = detail.find("contact")
        if contact is not None:
            sensor_id = contact.get("callsign", "")

    # Fallback: extract sensor_id from uid
    if not sensor_id:
        uid = root.get("uid", "")
        if uid.startswith("sensor-"):
            sensor_id = uid[7:]
        else:
            sensor_id = uid

    return {
        "sensor_id": sensor_id,
        "sensor_type": sensor_type,
        "detection_type": detection_type,
        "confidence": confidence,
        "lat": lat,
        "lng": lng,
    }


# ---------------------------------------------------------------------------
# Spot Report
# ---------------------------------------------------------------------------

def spot_report_to_cot(
    callsign: str,
    lat: float,
    lng: float,
    alt: float = 16.0,
    category: str = "hostile",
    description: str = "",
    stale_seconds: int = 300,
) -> str:
    """Generate CoT XML for a spot report (SPOTREP).

    type="b-m-p-s-m" (Spot Report)
    Human-readable observation report with coordinates.

    Args:
        callsign: Reporter callsign
        lat: Observation latitude
        lng: Observation longitude
        alt: Altitude
        category: One of "hostile", "friendly", "neutral", "unknown"
        description: Free-text description of what was observed
        stale_seconds: Seconds until the report goes stale

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Generate a unique ID using timestamp
    uid = f"spotrep-{callsign}-{now_str}"

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", uid)
    event.set("type", "b-m-p-s-m")
    event.set("how", "h-e")  # human-estimated
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "10.0")
    point.set("le", "10.0")

    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", callsign)

    spotrep = ET.SubElement(detail, "spotrep")
    spotrep.set("category", category)

    remarks_elem = ET.SubElement(detail, "remarks")
    if description:
        remarks_elem.text = description
    else:
        remarks_elem.text = f"Spot report from {callsign}: {category} activity"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_xml_to_spot_report(xml_string: str) -> dict | None:
    """Parse spot report CoT XML.

    Returns dict with callsign, category, description, lat, lng,
    or None if the XML is not a spot report.
    """
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if cot_type != "b-m-p-s-m":
        return None

    point = root.find("point")
    lat = float(point.get("lat", 0.0)) if point is not None else 0.0
    lng = float(point.get("lon", 0.0)) if point is not None else 0.0

    detail = root.find("detail")

    callsign = ""
    category = "unknown"
    description = ""

    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            callsign = contact.get("callsign", "")

        spotrep = detail.find("spotrep")
        if spotrep is not None:
            category = spotrep.get("category", "unknown")

        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            description = remarks.text

    return {
        "callsign": callsign,
        "category": category,
        "description": description,
        "lat": lat,
        "lng": lng,
    }


# ---------------------------------------------------------------------------
# Self-SA
# ---------------------------------------------------------------------------

def make_sa_cot(
    callsign: str,
    lat: float,
    lng: float,
    alt: float,
    team: str,
    role: str,
    stale_seconds: int = 120,
) -> str:
    """Generate TRITIUM's own SA (situational awareness) position broadcast.

    This is TRITIUM announcing its own position to the TAK network, so that
    ATAK/WinTAK users can see the command post on their maps.

    Args:
        callsign: TRITIUM instance name (e.g. "TRITIUM-SC")
        lat: Latitude of command post
        lng: Longitude of command post
        alt: Altitude in meters
        team: Team color (e.g. "Cyan")
        role: Team role (e.g. "HQ")
        stale_seconds: Seconds until position goes stale

    Returns:
        CoT XML string
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"{callsign}-SA")
    event.set("type", "a-f-G-E-C-I")  # Friendly ground C2 infrastructure
    event.set("how", "h-g-i-g-o")     # Human-GPS-inertial-GPS-other
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(lat))
    point.set("lon", str(lng))
    point.set("hae", str(alt))
    point.set("ce", "5.0")
    point.set("le", "5.0")

    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", callsign)

    group = ET.SubElement(detail, "__group")
    group.set("name", team)
    group.set("role", role)

    uid_elem = ET.SubElement(detail, "uid")
    uid_elem.set("Droid", callsign)

    return ET.tostring(event, encoding="unicode", xml_declaration=False)
