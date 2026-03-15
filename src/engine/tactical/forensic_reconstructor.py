# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""ForensicReconstructor — rebuild what happened in a time/area window.

Given a time range and geographic bounds, queries the event store and
target tracker to reconstruct the complete tactical picture: which targets
were present, what events occurred, what sensors observed, and the chain
of evidence linking observations to conclusions.

Usage::

    reconstructor = ForensicReconstructor(event_store, target_tracker, playback)
    result = reconstructor.reconstruct(time_range, bounds)
    report = reconstructor.generate_incident_report(result)
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ForensicReconstructor:
    """Reconstructs tactical history from stored events and snapshots.

    Parameters
    ----------
    event_store:
        TacticalEventStore or compatible — must have query_time_range().
    target_tracker:
        TargetTracker or None — for current target state lookup.
    playback:
        TemporalPlayback or None — for snapshot-based reconstruction.
    """

    def __init__(
        self,
        event_store: Any = None,
        target_tracker: Any = None,
        playback: Any = None,
    ) -> None:
        self._event_store = event_store
        self._target_tracker = target_tracker
        self._playback = playback
        self._reconstructions: dict[str, dict] = {}

    def reconstruct(
        self,
        start: float,
        end: float,
        bounds: Optional[dict] = None,
        max_events: int = 10000,
    ) -> dict:
        """Reconstruct what happened in a time/area window.

        Args:
            start: Start timestamp (unix).
            end: End timestamp (unix).
            bounds: Optional geographic bounds {north, south, east, west}.
            max_events: Maximum events to include.

        Returns:
            Full reconstruction dict with targets, events, evidence, coverage.
        """
        recon_id = f"recon_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        result = {
            "reconstruction_id": recon_id,
            "status": "processing",
            "time_range": {"start": start, "end": end, "duration_s": end - start},
            "bounds": bounds or {},
            "targets": [],
            "events": [],
            "evidence_chain": [],
            "sensor_coverage": {},
            "created_at": now.isoformat(),
            "completed_at": None,
            "total_events": 0,
            "total_targets": 0,
            "error": "",
        }

        try:
            # Phase 1: Gather events from event store
            events = self._query_events(start, end, max_events)

            # Phase 2: Filter by geographic bounds if provided
            if bounds:
                events = self._filter_by_bounds(events, bounds)

            # Phase 3: Extract target timelines from events
            targets = self._extract_target_timelines(events, start, end)

            # Phase 4: Build evidence chain
            evidence = self._build_evidence_chain(events)

            # Phase 5: Compute sensor coverage
            coverage = self._compute_sensor_coverage(events, start, end)

            # Phase 6: Augment with playback snapshots if available
            if self._playback:
                self._augment_with_snapshots(targets, start, end)

            result["events"] = events
            result["targets"] = list(targets.values())
            result["evidence_chain"] = evidence
            result["sensor_coverage"] = coverage
            result["total_events"] = len(events)
            result["total_targets"] = len(targets)
            result["status"] = "complete"
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

        except Exception as exc:
            logger.error("Forensic reconstruction failed: %s", exc)
            result["status"] = "failed"
            result["error"] = str(exc)
            result["completed_at"] = datetime.now(timezone.utc).isoformat()

        self._reconstructions[recon_id] = result
        return result

    def get_reconstruction(self, recon_id: str) -> Optional[dict]:
        """Retrieve a cached reconstruction by ID."""
        return self._reconstructions.get(recon_id)

    def list_reconstructions(self) -> list[dict]:
        """List all cached reconstruction summaries."""
        return [
            {
                "reconstruction_id": r["reconstruction_id"],
                "status": r["status"],
                "time_range": r["time_range"],
                "total_events": r["total_events"],
                "total_targets": r["total_targets"],
                "created_at": r["created_at"],
            }
            for r in self._reconstructions.values()
        ]

    def generate_incident_report(
        self,
        reconstruction: dict,
        title: str = "",
        created_by: str = "system",
    ) -> dict:
        """Generate a structured incident report from a reconstruction.

        Args:
            reconstruction: Result from reconstruct().
            title: Report title (auto-generated if empty).
            created_by: Author of the report.

        Returns:
            Incident report dict.
        """
        recon_id = reconstruction.get("reconstruction_id", "")
        time_range = reconstruction.get("time_range", {})
        targets = reconstruction.get("targets", [])
        events = reconstruction.get("events", [])
        coverage = reconstruction.get("sensor_coverage", {})

        if not title:
            target_count = len(targets)
            event_count = len(events)
            title = f"Incident Report: {target_count} targets, {event_count} events"

        # Auto-classify based on content
        classification = self._classify_incident(reconstruction)

        # Generate findings from targets and events
        findings = self._generate_findings(targets, events)

        # Generate recommendations
        recommendations = self._generate_recommendations(findings, targets)

        # Build timeline summary — key moments
        timeline_summary = self._build_timeline_summary(events)

        # Sensor coverage summary
        sensor_summary = []
        if isinstance(coverage, dict):
            for sensor_id, info in coverage.items():
                sensor_summary.append({
                    "sensor_id": sensor_id,
                    "sensor_type": info.get("sensor_type", "unknown"),
                    "observation_count": info.get("count", 0),
                    "targets_observed": info.get("targets", []),
                })

        report = {
            "incident_id": f"inc_{uuid.uuid4().hex[:12]}",
            "title": title,
            "summary": self._generate_summary(reconstruction),
            "reconstruction_id": recon_id,
            "classification": classification,
            "findings": findings,
            "recommendations": recommendations,
            "entities": [t.get("target_id", "") for t in targets],
            "sensor_summary": sensor_summary,
            "timeline_summary": timeline_summary,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": created_by,
            "status": "draft",
            "tags": [],
        }

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _query_events(self, start: float, end: float, max_events: int) -> list[dict]:
        """Query events from the event store."""
        if self._event_store is None:
            return []

        try:
            # TacticalEventStore has query_time_range
            if hasattr(self._event_store, "query_time_range"):
                raw = self._event_store.query_time_range(
                    start=start, end=end, limit=max_events
                )
                # Convert to dicts if needed
                if raw and hasattr(raw[0], "to_dict"):
                    return [e.to_dict() for e in raw]
                if raw and isinstance(raw[0], dict):
                    return raw
                return [{"data": str(e)} for e in raw]
        except Exception as exc:
            logger.warning("Event store query failed: %s", exc)

        return []

    def _filter_by_bounds(self, events: list[dict], bounds: dict) -> list[dict]:
        """Filter events to those within geographic bounds."""
        north = bounds.get("north", 90.0)
        south = bounds.get("south", -90.0)
        east = bounds.get("east", 180.0)
        west = bounds.get("west", -180.0)

        filtered = []
        for event in events:
            # Check event position fields
            lat = event.get("lat") or event.get("latitude")
            lng = event.get("lng") or event.get("longitude")

            if lat is not None and lng is not None:
                try:
                    lat, lng = float(lat), float(lng)
                    if south <= lat <= north and west <= lng <= east:
                        filtered.append(event)
                except (TypeError, ValueError):
                    filtered.append(event)  # include if can't parse
            else:
                # No position info — include by default
                filtered.append(event)

        return filtered

    def _extract_target_timelines(
        self, events: list[dict], start: float, end: float
    ) -> dict[str, dict]:
        """Build per-target timelines from events."""
        targets: dict[str, dict] = {}

        for event in events:
            target_id = (
                event.get("target_id")
                or event.get("entity_id")
                or event.get("device_id")
                or ""
            )
            if not target_id:
                continue

            ts = event.get("timestamp") or event.get("ts") or event.get("time", 0)
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts).timestamp()
                except (ValueError, TypeError):
                    ts = 0

            if target_id not in targets:
                targets[target_id] = {
                    "target_id": target_id,
                    "target_type": event.get("target_type", "unknown"),
                    "first_seen": ts,
                    "last_seen": ts,
                    "positions": [],
                    "events": [],
                    "evidence_ids": [],
                    "alliance": event.get("alliance", "unknown"),
                    "classification": event.get("classification", "unknown"),
                }

            t = targets[target_id]
            if ts:
                if ts < t["first_seen"] or t["first_seen"] == 0:
                    t["first_seen"] = ts
                if ts > t["last_seen"]:
                    t["last_seen"] = ts

            # Extract position if available
            lat = event.get("lat") or event.get("latitude")
            lng = event.get("lng") or event.get("longitude")
            if lat is not None and lng is not None:
                t["positions"].append({
                    "ts": ts,
                    "lat": float(lat),
                    "lng": float(lng),
                    "source": event.get("source", "unknown"),
                })

            t["events"].append({
                "type": event.get("event_type") or event.get("type", "unknown"),
                "ts": ts,
                "summary": event.get("summary", ""),
            })

        return targets

    def _build_evidence_chain(self, events: list[dict]) -> list[dict]:
        """Build an evidence chain from events."""
        evidence = []
        for i, event in enumerate(events):
            target_id = (
                event.get("target_id")
                or event.get("entity_id")
                or event.get("device_id")
                or ""
            )
            evidence.append({
                "evidence_id": f"ev_{i:04d}",
                "timestamp": event.get("timestamp") or event.get("ts", 0),
                "sensor_id": event.get("sensor_id") or event.get("node_id", ""),
                "sensor_type": event.get("sensor_type") or event.get("source", ""),
                "target_id": target_id,
                "observation_type": event.get("event_type") or event.get("type", ""),
                "confidence": event.get("confidence", 0.0),
            })
        return evidence

    def _compute_sensor_coverage(
        self, events: list[dict], start: float, end: float
    ) -> dict[str, dict]:
        """Compute per-sensor coverage statistics."""
        coverage: dict[str, dict] = {}

        for event in events:
            sensor_id = event.get("sensor_id") or event.get("node_id", "")
            if not sensor_id:
                continue

            if sensor_id not in coverage:
                coverage[sensor_id] = {
                    "sensor_id": sensor_id,
                    "sensor_type": event.get("sensor_type") or event.get("source", "unknown"),
                    "count": 0,
                    "targets": [],
                    "first_ts": float("inf"),
                    "last_ts": 0.0,
                }

            c = coverage[sensor_id]
            c["count"] += 1

            target_id = event.get("target_id") or event.get("entity_id", "")
            if target_id and target_id not in c["targets"]:
                c["targets"].append(target_id)

            ts = event.get("timestamp") or event.get("ts", 0)
            if isinstance(ts, (int, float)):
                if ts < c["first_ts"]:
                    c["first_ts"] = ts
                if ts > c["last_ts"]:
                    c["last_ts"] = ts

        # Clean up inf values
        for c in coverage.values():
            if c["first_ts"] == float("inf"):
                c["first_ts"] = start

        return coverage

    def _augment_with_snapshots(
        self, targets: dict[str, dict], start: float, end: float
    ) -> None:
        """Add position data from playback snapshots."""
        if not self._playback:
            return

        try:
            snapshots = self._playback.get_snapshots_between(start, end, max_count=200)
            for snap in snapshots:
                ts = snap.get("timestamp", 0)
                for target_data in snap.get("targets", []):
                    tid = target_data.get("target_id") or target_data.get("id", "")
                    if tid and tid in targets:
                        pos = target_data.get("position", {})
                        if isinstance(pos, dict) and ("lat" in pos or "x" in pos):
                            targets[tid]["positions"].append({
                                "ts": ts,
                                "lat": pos.get("lat", pos.get("y", 0)),
                                "lng": pos.get("lng", pos.get("x", 0)),
                                "source": "playback_snapshot",
                            })
        except Exception as exc:
            logger.warning("Snapshot augmentation failed: %s", exc)

    def _classify_incident(self, reconstruction: dict) -> str:
        """Auto-classify incident severity."""
        targets = reconstruction.get("targets", [])
        events = reconstruction.get("events", [])

        # Check for hostile targets
        hostile_count = sum(
            1 for t in targets if t.get("alliance") == "hostile"
        )
        threat_events = sum(
            1 for e in events
            if e.get("event_type") in ("threat_classified", "alert", "escalation")
            or e.get("type") in ("threat_classified", "alert", "escalation")
        )

        if hostile_count > 2 or threat_events > 5:
            return "critical"
        if hostile_count > 0 or threat_events > 0:
            return "significant"
        if len(targets) > 5:
            return "notable"
        return "routine"

    def _generate_findings(
        self, targets: list[dict], events: list[dict]
    ) -> list[dict]:
        """Auto-generate findings from the reconstruction data."""
        findings = []

        # Finding: target count
        if targets:
            findings.append({
                "finding_id": "f_target_count",
                "title": f"{len(targets)} targets detected in area",
                "description": (
                    f"During the reconstruction window, {len(targets)} distinct "
                    f"targets were observed by {len(set(e.get('sensor_id', '') for e in events if e.get('sensor_id')))} sensors."
                ),
                "confidence": 1.0,
                "target_refs": [t.get("target_id", "") for t in targets],
                "tags": ["overview"],
            })

        # Finding: hostile targets
        hostiles = [t for t in targets if t.get("alliance") == "hostile"]
        if hostiles:
            findings.append({
                "finding_id": "f_hostile_presence",
                "title": f"{len(hostiles)} hostile target(s) detected",
                "description": (
                    f"Hostile targets: {', '.join(t.get('target_id', '') for t in hostiles)}. "
                    "Review evidence chain for threat assessment."
                ),
                "confidence": 0.9,
                "target_refs": [t.get("target_id", "") for t in hostiles],
                "tags": ["threat", "hostile"],
            })

        # Finding: unknown targets
        unknowns = [t for t in targets if t.get("alliance") == "unknown"]
        if unknowns:
            findings.append({
                "finding_id": "f_unknown_targets",
                "title": f"{len(unknowns)} unclassified target(s)",
                "description": (
                    "Targets with unknown alliance require further investigation."
                ),
                "confidence": 0.7,
                "target_refs": [t.get("target_id", "") for t in unknowns],
                "tags": ["investigation_needed"],
            })

        return findings

    def _generate_recommendations(
        self, findings: list[dict], targets: list[dict]
    ) -> list[dict]:
        """Auto-generate recommendations from findings."""
        recs = []

        hostile_finding = next(
            (f for f in findings if "hostile" in f.get("tags", [])), None
        )
        if hostile_finding:
            recs.append({
                "recommendation_id": "r_hostile_response",
                "action": "Increase monitoring and dispatch patrol to area",
                "priority": 1,
                "rationale": "Hostile targets detected in reconstruction area",
            })

        unknown_finding = next(
            (f for f in findings if "investigation_needed" in f.get("tags", [])), None
        )
        if unknown_finding:
            recs.append({
                "recommendation_id": "r_investigate_unknowns",
                "action": "Initiate investigation on unclassified targets",
                "priority": 2,
                "rationale": "Unknown targets may represent emerging threats",
            })

        return recs

    def _build_timeline_summary(self, events: list[dict]) -> list[dict]:
        """Extract key moments from events for timeline summary."""
        # Sort by timestamp
        sorted_events = sorted(
            events,
            key=lambda e: e.get("timestamp") or e.get("ts") or 0,
        )

        # Take first, last, and any significant events
        key_types = {
            "alert", "threat_classified", "escalation",
            "geofence_enter", "geofence_exit", "target_correlation",
        }

        summary = []
        seen_types = set()

        for event in sorted_events:
            etype = event.get("event_type") or event.get("type", "")
            if etype in key_types and etype not in seen_types:
                summary.append({
                    "timestamp": event.get("timestamp") or event.get("ts", 0),
                    "type": etype,
                    "summary": event.get("summary", event.get("message", etype)),
                })
                seen_types.add(etype)

        # Always include first and last events
        if sorted_events and sorted_events[0] not in [s.get("_src") for s in summary]:
            first = sorted_events[0]
            summary.insert(0, {
                "timestamp": first.get("timestamp") or first.get("ts", 0),
                "type": first.get("event_type") or first.get("type", "start"),
                "summary": "Reconstruction window start",
            })

        if sorted_events and len(sorted_events) > 1:
            last = sorted_events[-1]
            summary.append({
                "timestamp": last.get("timestamp") or last.get("ts", 0),
                "type": last.get("event_type") or last.get("type", "end"),
                "summary": "Reconstruction window end",
            })

        return summary

    def _generate_summary(self, reconstruction: dict) -> str:
        """Generate a human-readable summary of the reconstruction."""
        targets = reconstruction.get("targets", [])
        events = reconstruction.get("events", [])
        time_range = reconstruction.get("time_range", {})
        duration = time_range.get("duration_s", 0)

        minutes = int(duration / 60) if duration else 0
        target_types = {}
        for t in targets:
            tt = t.get("target_type", "unknown")
            target_types[tt] = target_types.get(tt, 0) + 1

        type_str = ", ".join(f"{v} {k}" for k, v in target_types.items()) if target_types else "none"

        return (
            f"Forensic reconstruction covering {minutes} minutes. "
            f"Detected {len(targets)} targets ({type_str}) "
            f"across {len(events)} events."
        )
