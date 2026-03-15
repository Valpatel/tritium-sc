# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""InvestigationEngine — entity intelligence investigation workflows.

Implements the ontology research pattern:
  Seed -> Expand -> Filter -> Analyze -> Annotate -> Share

An Investigation is a focused analytical workspace that starts with seed
entities (dossiers) and expands outward through graph traversal of
relationships (shared signals, correlations, co-occurrence).  Analysts
can filter by time and entity type, annotate findings, and close
investigations when complete.

Auto-escalation: when a dossier's threat_level reaches "high" or
"critical", an investigation is automatically created if one doesn't
already exist for that entity.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("investigation")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Annotation:
    """A timestamped note attached to an entity within an investigation."""

    annotation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id: str = ""
    note: str = ""
    analyst: str = "system"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "annotation_id": self.annotation_id,
            "entity_id": self.entity_id,
            "note": self.note,
            "analyst": self.analyst,
            "timestamp": self.timestamp,
        }


@dataclass
class Investigation:
    """A focused analytical workspace for entity intelligence."""

    inv_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    created: float = field(default_factory=time.time)
    status: str = "open"  # open, closed, archived
    seed_entities: list[str] = field(default_factory=list)
    discovered_entities: set[str] = field(default_factory=set)
    annotations: list[Annotation] = field(default_factory=list)
    analyst_notes: str = ""

    def all_entity_ids(self) -> set[str]:
        """Return all entity IDs (seeds + discovered)."""
        return set(self.seed_entities) | self.discovered_entities

    def to_dict(self) -> dict:
        return {
            "inv_id": self.inv_id,
            "title": self.title,
            "description": self.description,
            "created": self.created,
            "status": self.status,
            "seed_entities": list(self.seed_entities),
            "discovered_entities": sorted(self.discovered_entities),
            "annotations": [a.to_dict() for a in self.annotations],
            "analyst_notes": self.analyst_notes,
            "entity_count": len(self.all_entity_ids()),
        }


# ---------------------------------------------------------------------------
# SQL schema for persistence
# ---------------------------------------------------------------------------

_SCHEMA_INVESTIGATIONS = """
CREATE TABLE IF NOT EXISTS investigations (
    inv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    seed_entities TEXT NOT NULL DEFAULT '[]',
    discovered_entities TEXT NOT NULL DEFAULT '[]',
    analyst_notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_created ON investigations(created);
"""

_SCHEMA_ANNOTATIONS = """
CREATE TABLE IF NOT EXISTS investigation_annotations (
    annotation_id TEXT PRIMARY KEY,
    inv_id TEXT NOT NULL,
    entity_id TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    analyst TEXT NOT NULL DEFAULT 'system',
    timestamp REAL NOT NULL,
    FOREIGN KEY (inv_id) REFERENCES investigations(inv_id)
);
CREATE INDEX IF NOT EXISTS idx_ann_inv ON investigation_annotations(inv_id);
CREATE INDEX IF NOT EXISTS idx_ann_entity ON investigation_annotations(entity_id);
"""


# ---------------------------------------------------------------------------
# InvestigationEngine
# ---------------------------------------------------------------------------

class InvestigationEngine:
    """Manages investigation workflows backed by SQLite persistence.

    Uses the DossierStore's signal relationships for graph expansion:
    two dossiers are "related" if they share a signal source, have
    correlated signals, or were seen at similar times/locations.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file for investigation persistence.
    dossier_store:
        Optional ``DossierStore`` instance for graph traversal.  If None,
        expand operations return empty results.
    """

    def __init__(
        self,
        db_path: str | Path = "data/investigations.db",
        dossier_store=None,
    ) -> None:
        self._db_path = str(db_path)
        self._dossier_store = dossier_store
        self._lock = threading.Lock()

        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(_SCHEMA_INVESTIGATIONS)
        cur.executescript(_SCHEMA_ANNOTATIONS)
        self._conn.commit()

    def close_db(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _save_investigation(self, inv: Investigation) -> None:
        """Insert or replace an investigation in the database."""
        with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO investigations
                   (inv_id, title, description, created, status,
                    seed_entities, discovered_entities, analyst_notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    inv.inv_id, inv.title, inv.description, inv.created,
                    inv.status,
                    json.dumps(inv.seed_entities),
                    json.dumps(sorted(inv.discovered_entities)),
                    inv.analyst_notes,
                ),
            )
            self._conn.commit()

    def _save_annotation(self, inv_id: str, ann: Annotation) -> None:
        """Insert an annotation into the database."""
        with self._lock:
            self._conn.execute(
                """INSERT INTO investigation_annotations
                   (annotation_id, inv_id, entity_id, note, analyst, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ann.annotation_id, inv_id, ann.entity_id,
                    ann.note, ann.analyst, ann.timestamp,
                ),
            )
            self._conn.commit()

    def _load_investigation(self, row: sqlite3.Row) -> Investigation:
        """Reconstruct an Investigation from a database row."""
        d = dict(row)
        seed_list = json.loads(d.get("seed_entities", "[]"))
        discovered_list = json.loads(d.get("discovered_entities", "[]"))

        # Load annotations
        ann_rows = self._conn.execute(
            """SELECT * FROM investigation_annotations
               WHERE inv_id = ?
               ORDER BY timestamp ASC""",
            (d["inv_id"],),
        ).fetchall()
        annotations = [
            Annotation(
                annotation_id=ar["annotation_id"],
                entity_id=ar["entity_id"],
                note=ar["note"],
                analyst=ar["analyst"],
                timestamp=ar["timestamp"],
            )
            for ar in ann_rows
        ]

        return Investigation(
            inv_id=d["inv_id"],
            title=d["title"],
            description=d["description"],
            created=d["created"],
            status=d["status"],
            seed_entities=seed_list,
            discovered_entities=set(discovered_list),
            annotations=annotations,
            analyst_notes=d.get("analyst_notes", ""),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        title: str,
        seed_entity_ids: list[str],
        description: str = "",
    ) -> Investigation:
        """Create a new investigation seeded with entity (dossier) IDs.

        Parameters
        ----------
        title:
            Human-readable investigation title.
        seed_entity_ids:
            List of dossier_ids to start the investigation with.
        description:
            Optional longer description of the investigation purpose.

        Returns
        -------
        Investigation:
            The newly created investigation.
        """
        inv = Investigation(
            title=title,
            description=description,
            seed_entities=list(seed_entity_ids),
        )
        self._save_investigation(inv)
        logger.info(
            "Created investigation %s: %s (%d seeds)",
            inv.inv_id[:8], title, len(seed_entity_ids),
        )
        return inv

    def get(self, inv_id: str) -> Investigation | None:
        """Get an investigation by ID, fully loaded with annotations.

        Returns None if not found.
        """
        row = self._conn.execute(
            "SELECT * FROM investigations WHERE inv_id = ?", (inv_id,)
        ).fetchone()
        if row is None:
            return None
        return self._load_investigation(row)

    def list_investigations(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Investigation]:
        """List investigations, optionally filtered by status.

        Parameters
        ----------
        status:
            Filter by status (open, closed, archived).  None returns all.
        limit:
            Maximum number of results.
        offset:
            Pagination offset.

        Returns
        -------
        list[Investigation]:
            Investigations ordered by creation time, newest first.
        """
        if status is not None:
            rows = self._conn.execute(
                """SELECT * FROM investigations
                   WHERE status = ?
                   ORDER BY created DESC
                   LIMIT ? OFFSET ?""",
                (status, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT * FROM investigations
                   ORDER BY created DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset),
            ).fetchall()
        return [self._load_investigation(r) for r in rows]

    def expand(
        self,
        inv_id: str,
        entity_id: str,
        max_hops: int = 1,
    ) -> list[str]:
        """Expand the investigation graph from an entity.

        Traverses relationships in the DossierStore to discover related
        entities.  Two dossiers are related if they:
        - Share a signal source (e.g. both seen by the same camera)
        - Have correlation signals linking them
        - Share identifiers (e.g. same MAC in different dossiers)

        Parameters
        ----------
        inv_id:
            Investigation to expand.
        entity_id:
            Starting dossier_id for expansion.
        max_hops:
            Number of relationship hops to traverse (default 1).

        Returns
        -------
        list[str]:
            Newly discovered entity (dossier) IDs added to the investigation.
        """
        inv = self.get(inv_id)
        if inv is None:
            return []

        if self._dossier_store is None:
            return []

        known = inv.all_entity_ids()
        newly_discovered: list[str] = []

        # BFS expansion
        frontier = {entity_id}
        for _hop in range(max_hops):
            next_frontier: set[str] = set()
            for eid in frontier:
                related = self._find_related_entities(eid)
                for rid in related:
                    if rid not in known and rid not in newly_discovered:
                        newly_discovered.append(rid)
                        next_frontier.add(rid)
            frontier = next_frontier
            if not frontier:
                break

        # Update investigation
        if newly_discovered:
            inv.discovered_entities.update(newly_discovered)
            self._save_investigation(inv)
            logger.info(
                "Investigation %s expanded: %d new entities from %s",
                inv_id[:8], len(newly_discovered), entity_id[:8],
            )

        return newly_discovered

    def _find_related_entities(self, entity_id: str) -> list[str]:
        """Find dossier IDs related to the given entity via shared signals.

        Looks for:
        1. Correlation signals that reference other entities
        2. Shared signal sources (same camera/sensor saw both)
        3. Co-occurring signals within a short time window
        """
        if self._dossier_store is None:
            return []

        related: set[str] = set()
        store = self._dossier_store

        dossier = store.get_dossier(entity_id)
        if dossier is None:
            return []

        # 1. Check correlation signals for explicit references
        for signal in dossier.get("signals", []):
            data = signal.get("data", {})
            if signal.get("signal_type") == "correlation":
                correlated_with = data.get("correlated_with", "")
                if correlated_with:
                    # The correlated_with might be a target_id, try to map
                    # to a dossier
                    related_dossier = store.find_by_identifier(
                        "target_id", correlated_with,
                    )
                    if related_dossier:
                        related.add(related_dossier["dossier_id"])

        # 2. Find dossiers that share signal sources
        sources = set()
        for signal in dossier.get("signals", []):
            src = signal.get("source", "")
            if src and src not in ("system", "correlator", "tracker_sync"):
                sources.add(src)

        if sources:
            # Query all dossier IDs that have signals from the same sources
            placeholders = ",".join("?" * len(sources))
            try:
                rows = store._conn.execute(
                    f"""SELECT DISTINCT dossier_id
                        FROM dossier_signals
                        WHERE source IN ({placeholders})
                          AND dossier_id != ?""",
                    (*sources, entity_id),
                ).fetchall()
                for row in rows:
                    related.add(row["dossier_id"])
            except Exception:
                logger.debug("Shared source lookup failed", exc_info=True)

        # 3. Co-occurrence: dossiers seen within 60s of this entity
        if dossier.get("signals"):
            timestamps = [s.get("timestamp", 0) for s in dossier["signals"]]
            if timestamps:
                latest = max(timestamps)
                earliest = min(timestamps)
                try:
                    rows = store._conn.execute(
                        """SELECT DISTINCT dossier_id
                           FROM dossier_signals
                           WHERE timestamp BETWEEN ? AND ?
                             AND dossier_id != ?
                           LIMIT 20""",
                        (earliest - 60, latest + 60, entity_id),
                    ).fetchall()
                    for row in rows:
                        related.add(row["dossier_id"])
                except Exception:
                    logger.debug("Co-occurrence lookup failed", exc_info=True)

        return list(related)

    def filter_by_time(
        self,
        inv_id: str,
        start: float,
        end: float,
    ) -> list[str]:
        """Filter investigation entities by time range.

        Returns entity IDs whose dossiers have signals within [start, end].

        Parameters
        ----------
        inv_id:
            Investigation to filter.
        start:
            Start timestamp (epoch seconds).
        end:
            End timestamp (epoch seconds).

        Returns
        -------
        list[str]:
            Entity IDs with activity in the time range.
        """
        inv = self.get(inv_id)
        if inv is None:
            return []

        if self._dossier_store is None:
            # Without a store, just return all entities (no filtering possible)
            return sorted(inv.all_entity_ids())

        filtered: list[str] = []
        store = self._dossier_store

        for eid in inv.all_entity_ids():
            try:
                row = store._conn.execute(
                    """SELECT COUNT(*) as cnt FROM dossier_signals
                       WHERE dossier_id = ?
                         AND timestamp BETWEEN ? AND ?""",
                    (eid, start, end),
                ).fetchone()
                if row and row["cnt"] > 0:
                    filtered.append(eid)
            except Exception:
                continue

        return sorted(filtered)

    def filter_by_type(
        self,
        inv_id: str,
        entity_types: list[str],
    ) -> list[str]:
        """Filter investigation entities by entity type.

        Parameters
        ----------
        inv_id:
            Investigation to filter.
        entity_types:
            List of entity types to include (e.g. ["person", "device"]).

        Returns
        -------
        list[str]:
            Entity IDs matching any of the specified types.
        """
        inv = self.get(inv_id)
        if inv is None:
            return []

        if self._dossier_store is None:
            return sorted(inv.all_entity_ids())

        filtered: list[str] = []
        store = self._dossier_store

        for eid in inv.all_entity_ids():
            try:
                row = store._conn.execute(
                    "SELECT entity_type FROM dossiers WHERE dossier_id = ?",
                    (eid,),
                ).fetchone()
                if row and row["entity_type"] in entity_types:
                    filtered.append(eid)
            except Exception:
                continue

        return sorted(filtered)

    def annotate(
        self,
        inv_id: str,
        entity_id: str,
        note: str,
        analyst: str = "system",
    ) -> Annotation | None:
        """Add an annotation to an entity within an investigation.

        Parameters
        ----------
        inv_id:
            Investigation ID.
        entity_id:
            Entity (dossier) ID to annotate.
        note:
            The annotation text.
        analyst:
            Who created the annotation (default "system").

        Returns
        -------
        Annotation:
            The created annotation, or None if investigation not found.
        """
        inv = self.get(inv_id)
        if inv is None:
            return None

        ann = Annotation(
            entity_id=entity_id,
            note=note,
            analyst=analyst,
        )
        inv.annotations.append(ann)
        self._save_annotation(inv_id, ann)
        logger.info(
            "Annotation on %s in investigation %s by %s",
            entity_id[:8], inv_id[:8], analyst,
        )
        return ann

    def close(self, inv_id: str) -> bool:
        """Close an investigation.

        Parameters
        ----------
        inv_id:
            Investigation ID to close.

        Returns
        -------
        bool:
            True if the investigation existed and was closed.
        """
        inv = self.get(inv_id)
        if inv is None:
            return False
        inv.status = "closed"
        self._save_investigation(inv)
        logger.info("Investigation %s closed", inv_id[:8])
        return True

    def archive(self, inv_id: str) -> bool:
        """Archive an investigation.

        Parameters
        ----------
        inv_id:
            Investigation ID to archive.

        Returns
        -------
        bool:
            True if the investigation existed and was archived.
        """
        inv = self.get(inv_id)
        if inv is None:
            return False
        inv.status = "archived"
        self._save_investigation(inv)
        logger.info("Investigation %s archived", inv_id[:8])
        return True

    # ------------------------------------------------------------------
    # Auto-escalation
    # ------------------------------------------------------------------

    def check_escalation(
        self,
        inv_id: str,
        dossier_store=None,
        on_escalate: object = None,
    ) -> bool:
        """Auto-escalate an investigation when it accumulates 5+ entities
        with threat_level >= medium.

        Checks all entities in the investigation against their dossiers'
        threat levels. If 5 or more have threat_level in
        (medium, high, critical), the investigation is upgraded to
        priority status and an optional callback is invoked.

        Parameters
        ----------
        inv_id:
            Investigation ID to check.
        dossier_store:
            DossierStore to look up entity threat levels.
            Falls back to self._dossier_store if None.
        on_escalate:
            Optional callback(investigation, threat_count) invoked on escalation.

        Returns
        -------
        bool:
            True if the investigation was escalated.
        """
        inv = self.get(inv_id)
        if inv is None:
            return False

        store = dossier_store or self._dossier_store
        if store is None:
            return False

        # Already escalated?
        if inv.title.startswith("PRIORITY:"):
            return False

        threat_levels = {"medium", "high", "critical"}
        threat_count = 0

        for entity_id in inv.all_entity_ids():
            try:
                dossier = store.get_dossier(entity_id)
                if dossier is None:
                    continue
                level = dossier.get("threat_level", "unknown")
                if level in threat_levels:
                    threat_count += 1
            except Exception:
                continue

        if threat_count < 5:
            return False

        # Escalate
        inv.title = f"PRIORITY: {inv.title}"
        ann = Annotation(
            entity_id="",
            note=(
                f"Auto-escalated: {threat_count} entities with "
                f"threat_level >= medium"
            ),
            analyst="system",
        )
        inv.annotations.append(ann)
        self._save_investigation(inv)
        self._save_annotation(inv_id, ann)

        logger.info(
            "Investigation %s auto-escalated: %d medium+ threats",
            inv_id[:8], threat_count,
        )

        if on_escalate is not None:
            try:
                on_escalate(inv, threat_count)  # type: ignore[operator]
            except Exception as exc:
                logger.warning("Escalation callback failed: %s", exc)

        return True

    def auto_investigate_threat(
        self,
        dossier_id: str,
        threat_level: str,
        dossier_name: str = "",
    ) -> Investigation | None:
        """Auto-create an investigation when threat_level reaches high/critical.

        Checks if an open investigation already exists for this dossier.
        If not, creates one with the dossier as the sole seed entity.

        Parameters
        ----------
        dossier_id:
            The dossier whose threat level changed.
        threat_level:
            The new threat level.
        dossier_name:
            Optional name for the investigation title.

        Returns
        -------
        Investigation or None:
            The created investigation, or None if not needed.
        """
        if threat_level not in ("high", "critical"):
            return None

        # Check if an open investigation already contains this dossier
        for inv in self.list_investigations(status="open"):
            if dossier_id in inv.all_entity_ids():
                return None

        name = dossier_name or dossier_id[:8]
        title = f"Auto: {threat_level} threat — {name}"
        description = (
            f"Automatically created when dossier {dossier_id} "
            f"reached threat level '{threat_level}'."
        )
        inv = self.create(title, [dossier_id], description=description)
        logger.info(
            "Auto-investigation %s for %s threat on %s",
            inv.inv_id[:8], threat_level, dossier_id[:8],
        )
        return inv

    # ------------------------------------------------------------------
    # Auto-close
    # ------------------------------------------------------------------

    def check_auto_close(
        self,
        dossier_store=None,
        target_tracker=None,
        auto_close_delay_s: float = 1800.0,
    ) -> list[str]:
        """Check open investigations for auto-close eligibility.

        An investigation is eligible for auto-close when ALL of its
        entities have been resolved:
        - Dossier threat_level is "none" or "low"
        - Target alliance is "friendly" (classified as non-threat)
        - Entity no longer exists in tracker (departed/expired)

        The investigation is closed after ``auto_close_delay_s`` seconds
        (default 30 minutes) of all entities being resolved, to allow
        analysts time to review before automatic closure.

        Parameters
        ----------
        dossier_store:
            DossierStore for looking up entity threat levels.
            Falls back to self._dossier_store if None.
        target_tracker:
            TargetTracker for checking target alliances.
        auto_close_delay_s:
            Delay in seconds before closing after all entities resolve
            (default 1800 = 30 minutes).

        Returns
        -------
        list[str]:
            List of investigation IDs that were auto-closed.
        """
        store = dossier_store or self._dossier_store
        closed_ids: list[str] = []
        now = time.time()

        for inv in self.list_investigations(status="open"):
            all_resolved = True
            entity_ids = inv.all_entity_ids()

            if not entity_ids:
                # No entities — consider resolved
                pass
            else:
                for entity_id in entity_ids:
                    resolved = self._is_entity_resolved(
                        entity_id, store, target_tracker
                    )
                    if not resolved:
                        all_resolved = False
                        break

            if not all_resolved:
                continue

            # Check if we have an auto-close annotation with a scheduled time
            close_scheduled = None
            for ann in inv.annotations:
                if ann.note.startswith("AUTO-CLOSE SCHEDULED:"):
                    try:
                        close_scheduled = float(
                            ann.note.split(":", 1)[1].strip()
                        )
                    except (ValueError, IndexError):
                        pass

            if close_scheduled is None:
                # Schedule auto-close
                scheduled_time = now + auto_close_delay_s
                ann = Annotation(
                    entity_id="",
                    note=f"AUTO-CLOSE SCHEDULED: {scheduled_time}",
                    analyst="system",
                )
                inv.annotations.append(ann)
                self._save_investigation(inv)
                self._save_annotation(inv.inv_id, ann)
                logger.info(
                    "Investigation %s scheduled for auto-close in %.0fs",
                    inv.inv_id[:8], auto_close_delay_s,
                )
            elif now >= close_scheduled:
                # Time to close
                ann = Annotation(
                    entity_id="",
                    note=(
                        "Auto-closed: all entities resolved "
                        "(threats cleared or targets classified as friendly)"
                    ),
                    analyst="system",
                )
                inv.annotations.append(ann)
                inv.status = "closed"
                self._save_investigation(inv)
                self._save_annotation(inv.inv_id, ann)
                closed_ids.append(inv.inv_id)
                logger.info(
                    "Investigation %s auto-closed (all entities resolved)",
                    inv.inv_id[:8],
                )

        return closed_ids

    def _is_entity_resolved(
        self,
        entity_id: str,
        dossier_store=None,
        target_tracker=None,
    ) -> bool:
        """Check if an entity is considered resolved (non-threatening).

        An entity is resolved if:
        1. Its dossier threat_level is "none" or "low", OR
        2. Its tracked target alliance is "friendly", OR
        3. It no longer exists in either the dossier store or tracker
           (departed / expired).

        Returns True if resolved, False if still an active concern.
        """
        resolved_threat_levels = {"none", "low", ""}

        # Check dossier
        if dossier_store is not None:
            try:
                dossier = dossier_store.get_dossier(entity_id)
                if dossier is not None:
                    level = dossier.get("threat_level", "unknown")
                    if level not in resolved_threat_levels:
                        return False
                    # Dossier exists and threat is low — resolved
                    return True
            except Exception:
                pass

        # Check target tracker
        if target_tracker is not None:
            try:
                targets = target_tracker.get_all()
                target = targets.get(entity_id)
                if target is not None:
                    if target.alliance == "friendly":
                        return True
                    if target.alliance in ("hostile", "unknown"):
                        return False
            except Exception:
                pass

        # Entity not found in any store — consider it resolved (departed)
        return True
