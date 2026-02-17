"""Backward-compatible re-export — canonical location is tracking.escalation."""
from tracking.escalation import (
    THREAT_LEVELS,
    ThreatRecord,
    ThreatClassifier,
    AutoDispatcher,
)

__all__ = ["THREAT_LEVELS", "ThreatRecord", "ThreatClassifier", "AutoDispatcher"]
