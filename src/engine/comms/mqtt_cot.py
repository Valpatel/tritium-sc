"""MQTT CoT codec -- converts between TRITIUM JSON and CoT XML on MQTT.

Pure functions for encoding/decoding CoT XML payloads that travel over MQTT.
Reuses the unit type registry for type code resolution.

Zero external dependencies (only xml.etree.ElementTree from stdlib).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from engine.comms.cot import _resolve_cot_type, _get_reverse_type

# Team colors by alliance (same as cot.py)
_TEAM_COLORS: dict[str, str] = {
    "friendly": "Cyan",
    "hostile":  "Red",
    "neutral":  "White",
    "unknown":  "Yellow",
}

# Alliance fallback when registry has no match
_ALLIANCE_FALLBACK: dict[str, str] = {
    "friendly": "a-f-G",
    "hostile":  "a-h-G",
    "neutral":  "a-n-G",
    "unknown":  "a-u-G",
}


def telemetry_to_cot(
    robot_id: str,
    telemetry: dict,
    site_id: str = "home",
    stale_seconds: int = 120,
) -> str:
    """Convert robot JSON telemetry to CoT SA (situational awareness) XML.

    Args:
        robot_id: Unique ID of the robot (becomes the CoT uid).
        telemetry: Dict with lat, lng, alt, speed, heading, battery,
                   asset_type, alliance.
        site_id: MQTT site prefix (not embedded in XML).
        stale_seconds: Seconds until the position report goes stale.

    Returns:
        CoT XML string.
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=stale_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )

    asset_type = telemetry.get("asset_type", "person")
    alliance = telemetry.get("alliance", "unknown")
    cot_type = _resolve_cot_type(asset_type, alliance)

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", robot_id)
    event.set("type", cot_type)
    event.set("how", "m-g")  # machine-GPS derived
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(telemetry.get("lat", 0.0)))
    point.set("lon", str(telemetry.get("lng", 0.0)))
    point.set("hae", str(telemetry.get("alt", 0.0)))
    point.set("ce", "10.0")
    point.set("le", "10.0")

    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", robot_id)

    group = ET.SubElement(detail, "__group")
    group.set("name", _TEAM_COLORS.get(alliance, "Yellow"))
    group.set("role", "Team Member")

    status = ET.SubElement(detail, "status")
    battery_pct = telemetry.get("battery", 1.0) * 100.0
    status.set("battery", str(round(battery_pct, 1)))

    track = ET.SubElement(detail, "track")
    track.set("speed", str(telemetry.get("speed", 0.0)))
    track.set("course", str(telemetry.get("heading", 0.0)))

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_to_telemetry(xml_string: str) -> dict | None:
    """Parse CoT SA XML back to TRITIUM telemetry dict.

    Returns:
        Dict with target_id, lat, lng, alt, speed, heading, battery,
        asset_type, alliance, source="mqtt_cot".
        Or None if not parseable.
    """
    if not xml_string:
        return None

    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    point = root.find("point")
    if point is None:
        return None

    uid = root.get("uid", "unknown")
    cot_type = root.get("type", "a-u-G")

    # Infer alliance from type code
    alliance = "unknown"
    if len(cot_type) >= 3:
        affil = cot_type[2]
        alliance = {"f": "friendly", "h": "hostile", "n": "neutral"}.get(
            affil, "unknown"
        )

    # Infer asset_type from type code via registry
    asset_type = "person"
    for prefix, a_type in _get_reverse_type():
        if cot_type.startswith(prefix):
            asset_type = a_type
            break

    lat = float(point.get("lat", 0.0))
    lon = float(point.get("lon", 0.0))
    hae = float(point.get("hae", 0.0))

    speed = 0.0
    heading = 0.0
    battery = 1.0

    detail = root.find("detail")
    if detail is not None:
        track_elem = detail.find("track")
        if track_elem is not None:
            speed = float(track_elem.get("speed", 0.0))
            heading = float(track_elem.get("course", 0.0))

        status_elem = detail.find("status")
        if status_elem is not None:
            battery = float(status_elem.get("battery", 100.0)) / 100.0

    return {
        "target_id": uid,
        "lat": lat,
        "lng": lon,
        "alt": hae,
        "speed": speed,
        "heading": heading,
        "battery": battery,
        "asset_type": asset_type,
        "alliance": alliance,
        "source": "mqtt_cot",
    }


def command_to_cot(
    robot_id: str,
    command: str,
    params: dict | None = None,
) -> str:
    """Convert dispatch/patrol/recall command to CoT tasking XML.

    Args:
        robot_id: Target robot ID.
        command: "dispatch", "patrol", or "recall".
        params: {"x": float, "y": float} for dispatch,
                {"waypoints": [...]} for patrol.

    Returns:
        CoT XML with type="t-x-t-a" (tasking assignment).
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=120)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"{robot_id}-cmd-{now_str}")
    event.set("type", "t-x-t-a")  # tasking assignment
    event.set("how", "h-e")  # human-estimated
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    if params and "x" in params:
        point.set("lat", str(params.get("y", 0.0)))
        point.set("lon", str(params.get("x", 0.0)))
    else:
        point.set("lat", "0.0")
        point.set("lon", "0.0")
    point.set("hae", "0.0")
    point.set("ce", "999999")
    point.set("le", "999999")

    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", robot_id)

    remarks = ET.SubElement(detail, "remarks")
    if command == "dispatch" and params:
        remarks.text = f"DISPATCH to ({params.get('x', 0)}, {params.get('y', 0)})"
    elif command == "patrol" and params and "waypoints" in params:
        wp_str = ", ".join(
            f"({w.get('x', 0)}, {w.get('y', 0)})"
            for w in params["waypoints"]
        )
        remarks.text = f"PATROL waypoints: {wp_str}"
    elif command == "recall":
        remarks.text = "RECALL to base"
    else:
        remarks.text = f"{command.upper()}"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)


def cot_to_command(xml_string: str) -> tuple[str, dict] | None:
    """Parse CoT tasking XML back to (command, params).

    Returns:
        Tuple of (command_name, params_dict) where command_name is one of
        "dispatch", "patrol", "recall", and params contains the extracted
        data (coordinates, waypoints, robot_id).
        Returns None if the XML is not a tasking event (type must start
        with "t-x-t").
    """
    if not xml_string:
        return None

    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return None

    if root.tag != "event":
        return None

    cot_type = root.get("type", "")
    if not cot_type.startswith("t-x-t"):
        return None

    # Extract robot_id from contact callsign
    detail = root.find("detail")
    robot_id = ""
    if detail is not None:
        contact = detail.find("contact")
        if contact is not None:
            robot_id = contact.get("callsign", "")

    # Extract command type and params from remarks text
    remarks_text = ""
    if detail is not None:
        remarks = detail.find("remarks")
        if remarks is not None and remarks.text:
            remarks_text = remarks.text.strip()

    # Parse the remarks to determine command type
    params: dict = {}
    if robot_id:
        params["robot_id"] = robot_id

    if remarks_text.startswith("DISPATCH"):
        command = "dispatch"
        # Extract coordinates from "DISPATCH to (x, y)"
        # Point element has lat=y, lon=x
        point = root.find("point")
        if point is not None:
            params["x"] = float(point.get("lon", 0.0))
            params["y"] = float(point.get("lat", 0.0))
    elif remarks_text.startswith("PATROL"):
        command = "patrol"
        # Parse waypoints from "PATROL waypoints: (x1, y1), (x2, y2), ..."
        import re
        coords = re.findall(r'\(([^)]+)\)', remarks_text)
        waypoints = []
        for coord_str in coords:
            parts = coord_str.split(",")
            if len(parts) == 2:
                try:
                    wx = float(parts[0].strip())
                    wy = float(parts[1].strip())
                    waypoints.append({"x": wx, "y": wy})
                except ValueError:
                    continue
        params["waypoints"] = waypoints
    elif remarks_text.startswith("RECALL"):
        command = "recall"
    else:
        # Unknown tasking command -- use the raw text as command name
        command = remarks_text.lower().split()[0] if remarks_text else "unknown"

    return (command, params)


def sensor_event_to_cot(sensor_id: str, event_data: dict) -> str:
    """Convert sensor activation to CoT sensor reading XML.

    Args:
        sensor_id: Unique sensor identifier.
        event_data: Dict with sensor_type, lat, lng, triggered_by, timestamp.

    Returns:
        CoT XML with type="b-s-r" (sensor reading).
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    stale_str = (now + timedelta(seconds=60)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )

    event = ET.Element("event")
    event.set("version", "2.0")
    event.set("uid", f"{sensor_id}-{now_str}")
    event.set("type", "b-s-r")  # bits-sensor-reading
    event.set("how", "m-r")  # machine-reported
    event.set("time", now_str)
    event.set("start", now_str)
    event.set("stale", stale_str)

    point = ET.SubElement(event, "point")
    point.set("lat", str(event_data.get("lat", 0.0)))
    point.set("lon", str(event_data.get("lng", 0.0)))
    point.set("hae", "0.0")
    point.set("ce", "20.0")
    point.set("le", "20.0")

    detail = ET.SubElement(event, "detail")

    contact = ET.SubElement(detail, "contact")
    contact.set("callsign", sensor_id)

    remarks = ET.SubElement(detail, "remarks")
    sensor_type = event_data.get("sensor_type", "unknown")
    triggered_by = event_data.get("triggered_by", "unknown")
    remarks.text = f"{sensor_type} sensor activated by {triggered_by}"

    return ET.tostring(event, encoding="unicode", xml_declaration=False)
