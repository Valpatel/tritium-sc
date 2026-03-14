# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""DossierStore — persistent identity resolution for correlated targets.

A TargetDossier is a stable identity record that persists across sessions.
When a BLE phone and a camera person detection are correlated, they get
assigned to the same dossier with a stable UUID. Future sightings of either
signal are immediately associated with the existing dossier.

The store maintains:
  - UUID -> TargetDossier mapping (the identity graph)
  - signal_id -> UUID reverse index (fast lookup by MAC, detection ID, etc.)
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class TargetDossier:
    """A persistent identity record fusing multiple signal sources."""

    uuid: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    correlation_count: int = 0
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)

    def add_signal(self, signal_id: str, source: str) -> None:
        """Add a signal identifier to this dossier."""
        if signal_id not in self.signal_ids:
            self.signal_ids.append(signal_id)
        if source not in self.sources:
            self.sources.append(source)
        self.last_seen = time.monotonic()

    def has_signal(self, signal_id: str) -> bool:
        """Check if this dossier contains a signal."""
        return signal_id in self.signal_ids

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "signal_ids": list(self.signal_ids),
            "sources": list(self.sources),
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "correlation_count": self.correlation_count,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


class DossierStore:
    """Thread-safe store for target dossiers with reverse signal index.

    Provides O(1) lookup by either dossier UUID or signal ID (MAC address,
    detection ID, etc.).
    """

    def __init__(self) -> None:
        self._dossiers: dict[str, TargetDossier] = {}  # uuid -> dossier
        self._signal_index: dict[str, str] = {}  # signal_id -> uuid
        self._lock = threading.Lock()

    def find_by_signal(self, signal_id: str) -> TargetDossier | None:
        """Look up a dossier by any of its signal IDs."""
        with self._lock:
            dossier_uuid = self._signal_index.get(signal_id)
            if dossier_uuid:
                return self._dossiers.get(dossier_uuid)
            return None

    def find_by_uuid(self, dossier_uuid: str) -> TargetDossier | None:
        """Look up a dossier by its UUID."""
        with self._lock:
            return self._dossiers.get(dossier_uuid)

    def find_association(self, signal_a: str, signal_b: str) -> TargetDossier | None:
        """Check if two signals are already associated in any dossier."""
        with self._lock:
            uuid_a = self._signal_index.get(signal_a)
            uuid_b = self._signal_index.get(signal_b)
            if uuid_a and uuid_b and uuid_a == uuid_b:
                return self._dossiers.get(uuid_a)
            return None

    def create_or_update(
        self,
        signal_a: str,
        source_a: str,
        signal_b: str,
        source_b: str,
        confidence: float,
        metadata: dict | None = None,
    ) -> TargetDossier:
        """Create a new dossier or update an existing one for the signal pair.

        If either signal already belongs to a dossier, the other signal is
        added to that dossier. If both belong to different dossiers, they
        are merged into the one with higher confidence.
        """
        with self._lock:
            uuid_a = self._signal_index.get(signal_a)
            uuid_b = self._signal_index.get(signal_b)

            if uuid_a and uuid_b:
                if uuid_a == uuid_b:
                    # Already in the same dossier — just update
                    dossier = self._dossiers[uuid_a]
                    dossier.last_seen = time.monotonic()
                    dossier.correlation_count += 1
                    dossier.confidence = max(dossier.confidence, confidence)
                    if metadata:
                        dossier.metadata.update(metadata)
                    return dossier
                else:
                    # Merge: keep the one with higher confidence
                    d_a = self._dossiers[uuid_a]
                    d_b = self._dossiers[uuid_b]
                    if d_b.confidence > d_a.confidence:
                        keep, discard = d_b, d_a
                    else:
                        keep, discard = d_a, d_b
                    # Move all signals from discard to keep
                    for sig in discard.signal_ids:
                        keep.add_signal(sig, "")
                        self._signal_index[sig] = keep.uuid
                    for src in discard.sources:
                        if src not in keep.sources:
                            keep.sources.append(src)
                    keep.correlation_count += discard.correlation_count + 1
                    keep.confidence = max(keep.confidence, confidence)
                    keep.first_seen = min(keep.first_seen, discard.first_seen)
                    keep.last_seen = time.monotonic()
                    if metadata:
                        keep.metadata.update(metadata)
                    del self._dossiers[discard.uuid]
                    return keep
            elif uuid_a:
                dossier = self._dossiers[uuid_a]
                dossier.add_signal(signal_b, source_b)
                self._signal_index[signal_b] = dossier.uuid
                dossier.correlation_count += 1
                dossier.confidence = max(dossier.confidence, confidence)
                if metadata:
                    dossier.metadata.update(metadata)
                return dossier
            elif uuid_b:
                dossier = self._dossiers[uuid_b]
                dossier.add_signal(signal_a, source_a)
                self._signal_index[signal_a] = dossier.uuid
                dossier.correlation_count += 1
                dossier.confidence = max(dossier.confidence, confidence)
                if metadata:
                    dossier.metadata.update(metadata)
                return dossier
            else:
                # New dossier
                dossier = TargetDossier(
                    confidence=confidence,
                    correlation_count=1,
                    metadata=metadata or {},
                )
                dossier.add_signal(signal_a, source_a)
                dossier.add_signal(signal_b, source_b)
                self._dossiers[dossier.uuid] = dossier
                self._signal_index[signal_a] = dossier.uuid
                self._signal_index[signal_b] = dossier.uuid
                return dossier

    def get_all(self) -> list[TargetDossier]:
        """Return all dossiers."""
        with self._lock:
            return list(self._dossiers.values())

    @property
    def count(self) -> int:
        """Number of dossiers in the store."""
        with self._lock:
            return len(self._dossiers)

    def clear(self) -> None:
        """Clear all dossiers and signal index."""
        with self._lock:
            self._dossiers.clear()
            self._signal_index.clear()
