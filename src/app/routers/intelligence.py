# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Intelligence model management API.

Endpoints for retraining the correlation model and querying model status.
Also includes Ollama-powered anomaly description for RF events.

Endpoints:
    POST /api/intelligence/retrain      — Trigger model retraining
    GET  /api/intelligence/model/status  — Model accuracy, training count, timestamps
    POST /api/intelligence/anomaly/describe — Ollama-powered anomaly description
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from loguru import logger

from app.auth import optional_auth, require_auth

router = APIRouter(prefix="/api/intelligence", tags=["intelligence"])


class RetrainResponse(BaseModel):
    """Response from model retrain endpoint."""
    success: bool
    accuracy: float = 0.0
    training_count: int = 0
    error: Optional[str] = None
    feature_names: list[str] = Field(default_factory=list)


class ModelStatusResponse(BaseModel):
    """Current model status."""
    trained: bool = False
    accuracy: float = 0.0
    training_count: int = 0
    last_trained: Optional[float] = None
    last_trained_iso: Optional[str] = None
    sklearn_available: bool = False
    model_path: str = ""
    feature_names: list[str] = Field(default_factory=list)
    training_data_stats: dict[str, Any] = Field(default_factory=dict)


class AnomalyDescribeRequest(BaseModel):
    """Request to describe an anomaly using LLM."""
    anomaly_type: str = Field(..., description="Type of anomaly (rf_drop, rf_spike, device_loss)")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Anomaly context: device counts, RSSI values, timestamps, etc.",
    )
    ollama_model: str = Field("qwen2.5:7b", description="Ollama model to use")


class AnomalyDescribeResponse(BaseModel):
    """LLM-generated anomaly description."""
    description: str
    severity: str = "unknown"
    suggested_action: str = ""
    model_used: str = ""
    generated: bool = True


@router.post("/retrain", response_model=RetrainResponse)
async def retrain_model(request: Request, user: dict = Depends(require_auth)) -> RetrainResponse:
    """Trigger retraining of the correlation model from accumulated training data.

    Loads all confirmed correlation decisions from the TrainingStore,
    trains a logistic regression model, and saves it to disk. Returns
    the model accuracy and training data count.
    """
    try:
        from engine.intelligence.correlation_learner import get_correlation_learner
        learner = get_correlation_learner()
        result = learner.train()

        return RetrainResponse(
            success=result.get("success", False),
            accuracy=result.get("accuracy", 0.0),
            training_count=result.get("training_count", 0),
            error=result.get("error"),
            feature_names=result.get("feature_names", []),
        )
    except Exception as exc:
        logger.error("Retrain endpoint failed: %s", exc)
        return RetrainResponse(success=False, error=str(exc))


@router.get("/model/status", response_model=ModelStatusResponse)
async def model_status(request: Request) -> ModelStatusResponse:
    """Get current model accuracy, training data count, and last trained timestamp."""
    try:
        from engine.intelligence.correlation_learner import get_correlation_learner
        learner = get_correlation_learner()
        status = learner.get_status()

        # Also get training data stats
        training_stats: dict[str, Any] = {}
        try:
            from engine.intelligence.training_store import get_training_store
            store = get_training_store()
            training_stats = store.get_stats()
        except Exception:
            pass

        return ModelStatusResponse(
            trained=status.get("trained", False),
            accuracy=status.get("accuracy", 0.0),
            training_count=status.get("training_count", 0),
            last_trained=status.get("last_trained"),
            last_trained_iso=status.get("last_trained_iso"),
            sklearn_available=status.get("sklearn_available", False),
            model_path=status.get("model_path", ""),
            feature_names=status.get("feature_names", []),
            training_data_stats=training_stats,
        )
    except Exception as exc:
        logger.error("Model status endpoint failed: %s", exc)
        return ModelStatusResponse()


@router.post("/anomaly/describe", response_model=AnomalyDescribeResponse)
async def describe_anomaly(req: AnomalyDescribeRequest, user: dict = Depends(optional_auth)) -> AnomalyDescribeResponse:
    """Use a local Ollama LLM to describe an anomaly in natural language.

    When the anomaly detector flags unusual RF activity, this endpoint
    generates a human-readable description of what is unusual and why
    it matters. Requires a running Ollama instance.

    Example output: "BLE device count dropped from 12 to 3 in the last
    5 minutes -- possible jamming or evacuation."
    """
    prompt = _build_anomaly_prompt(req.anomaly_type, req.context)

    try:
        description = await _query_ollama(prompt, req.ollama_model)

        # Extract severity from description
        severity = _classify_severity(req.anomaly_type, req.context)
        suggested_action = _suggest_action(req.anomaly_type, req.context)

        return AnomalyDescribeResponse(
            description=description,
            severity=severity,
            suggested_action=suggested_action,
            model_used=req.ollama_model,
            generated=True,
        )
    except Exception as exc:
        # Fallback to template-based description
        logger.warning("Ollama unavailable, using template: %s", exc)
        fallback = _template_description(req.anomaly_type, req.context)
        return AnomalyDescribeResponse(
            description=fallback,
            severity=_classify_severity(req.anomaly_type, req.context),
            suggested_action=_suggest_action(req.anomaly_type, req.context),
            model_used="template",
            generated=False,
        )


def _sanitize_context_value(value: Any) -> str:
    """Sanitize a context value to prevent prompt injection."""
    s = str(value)
    # Truncate long values and strip control characters
    s = s[:200]
    s = "".join(c for c in s if c.isprintable() or c in (" ", "\t"))
    return s


def _build_anomaly_prompt(anomaly_type: str, context: dict[str, Any]) -> str:
    """Build a prompt for the LLM to describe an anomaly."""
    # Sanitize anomaly type — only allow known types or truncate to safe chars
    _KNOWN_TYPES = {
        "rf_drop", "rf_spike", "device_loss", "jamming_suspected",
        "mass_departure", "new_device_flood", "rssi_anomaly",
    }
    if anomaly_type in _KNOWN_TYPES:
        safe_type = anomaly_type
    else:
        safe_type = "".join(c for c in str(anomaly_type)[:30] if c.isalnum() or c in ("_", "-"))
    ctx_lines = []
    for k, v in context.items():
        safe_k = "".join(c for c in str(k)[:30] if c.isalnum() or c in ("_", "-"))
        ctx_lines.append(f"  {safe_k}: {_sanitize_context_value(v)}")
    ctx_str = "\n".join(ctx_lines) if ctx_lines else "  (no additional context)"

    return f"""You are a cybersecurity analyst monitoring an RF sensor network.
An anomaly has been detected. Describe what is happening in 1-2 sentences,
using plain language that a security operator would understand. Include
possible explanations and severity.

Anomaly type: {safe_type}
Context:
{ctx_str}

Respond with ONLY the description, no headers or formatting."""


async def _query_ollama(prompt: str, model: str) -> str:
    """Query local Ollama instance for anomaly description."""
    import httpx

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "http://localhost:11434/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 150,
                },
            },
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()


def _classify_severity(anomaly_type: str, context: dict[str, Any]) -> str:
    """Classify anomaly severity based on type and context."""
    severity_map = {
        "rf_drop": "warning",
        "rf_spike": "warning",
        "device_loss": "critical",
        "jamming_suspected": "critical",
        "mass_departure": "warning",
        "new_device_flood": "warning",
        "rssi_anomaly": "info",
    }

    severity = severity_map.get(anomaly_type, "info")

    # Escalate based on magnitude
    magnitude = context.get("magnitude", 0)
    if isinstance(magnitude, (int, float)) and magnitude > 0.8:
        if severity == "info":
            severity = "warning"
        elif severity == "warning":
            severity = "critical"

    return severity


def _suggest_action(anomaly_type: str, context: dict[str, Any]) -> str:
    """Suggest a response action based on anomaly type."""
    actions = {
        "rf_drop": "Investigate area for RF interference or jamming. Check sensor health.",
        "rf_spike": "Monitor for unauthorized transmitter. Run spectrum analysis.",
        "device_loss": "Verify sensor connectivity. Check for power outage or physical damage.",
        "jamming_suspected": "Activate counter-jamming protocols. Alert security team. Switch to backup frequencies.",
        "mass_departure": "Review camera feeds for evacuation. Check for active threats.",
        "new_device_flood": "Run device fingerprinting. Check for spoofing attack.",
        "rssi_anomaly": "Log for pattern analysis. No immediate action required.",
    }
    return actions.get(anomaly_type, "Monitor and log. Investigate if pattern persists.")


def _template_description(anomaly_type: str, context: dict[str, Any]) -> str:
    """Generate a template-based description when Ollama is unavailable."""
    templates = {
        "rf_drop": (
            "RF activity dropped significantly. "
            "Device count went from {prev_count} to {current_count} "
            "in the last {window_minutes} minutes. "
            "Possible causes: jamming, power outage, or evacuation."
        ),
        "rf_spike": (
            "Unusual spike in RF activity detected. "
            "{current_count} devices now visible (was {prev_count}). "
            "Could indicate new device deployment or spoofing attack."
        ),
        "device_loss": (
            "Sensor node went offline. Device {device_id} has not "
            "reported in {minutes_silent} minutes. "
            "Check physical connectivity and power."
        ),
        "jamming_suspected": (
            "Possible RF jamming detected. Multiple sensors report "
            "degraded signal quality simultaneously. "
            "{affected_count} nodes affected."
        ),
        "mass_departure": (
            "Large number of tracked devices departed the area. "
            "{departed_count} devices lost in {window_minutes} minutes."
        ),
        "new_device_flood": (
            "Rapid appearance of {new_count} new devices. "
            "Unusual pattern may indicate spoofing or large group arrival."
        ),
    }

    template = templates.get(anomaly_type, "Anomaly detected: {anomaly_type}. Investigating.")

    # Fill template with context values, using defaults for missing keys
    defaults = {
        "prev_count": "?",
        "current_count": "?",
        "window_minutes": "5",
        "device_id": "unknown",
        "minutes_silent": "?",
        "affected_count": "?",
        "departed_count": "?",
        "new_count": "?",
        "anomaly_type": anomaly_type,
    }
    merged = {**defaults, **{k: str(v) for k, v in context.items()}}

    try:
        return template.format(**merged)
    except (KeyError, IndexError):
        return f"Anomaly detected: {anomaly_type}. Context: {context}"


# ---------------------------------------------------------------------------
# Feature aggregation & classification feedback endpoints
# ---------------------------------------------------------------------------


class FeatureIngestRequest(BaseModel):
    """Request to ingest feature vectors from an edge node."""
    node_id: str = Field(..., description="Edge node identifier")
    features: list[dict[str, Any]] = Field(
        ..., description="List of {mac, features} dicts"
    )


class FeatureIngestResponse(BaseModel):
    """Response from feature ingest."""
    ingested: int = 0
    device_count: int = 0


class FeaturesResponse(BaseModel):
    """Accumulated features for a device."""
    mac: str = ""
    vector_count: int = 0
    node_count: int = 0
    node_ids: list[str] = Field(default_factory=list)
    first_seen: Optional[float] = None
    last_seen: Optional[float] = None
    mean_features: dict[str, float] = Field(default_factory=dict)


class FeedbackRequest(BaseModel):
    """Request to classify a device and send feedback to edge."""
    mac: str = Field(..., description="Device MAC address")
    node_id: str = Field(..., description="Edge node to send feedback to")


class FeedbackResponse(BaseModel):
    """Classification feedback result."""
    mac: str = ""
    predicted_type: str = "unknown"
    confidence: float = 0.0
    feedback_sent: bool = False
    inconsistent: bool = False


class EdgeMetricsResponse(BaseModel):
    """Per-edge-node intelligence metrics."""
    nodes: dict[str, dict[str, Any]] = Field(default_factory=dict)
    aggregator_stats: dict[str, Any] = Field(default_factory=dict)
    feedback_stats: dict[str, Any] = Field(default_factory=dict)


@router.post("/features/ingest", response_model=FeatureIngestResponse)
async def ingest_features(req: FeatureIngestRequest, user: dict = Depends(optional_auth)) -> FeatureIngestResponse:
    """Ingest feature vectors from an edge node.

    Edge nodes publish feature vectors as part of BLE sightings.
    This endpoint collects them for ML classification.
    """
    try:
        from engine.intelligence.feature_aggregator import get_feature_aggregator
        aggregator = get_feature_aggregator()
        count = aggregator.ingest_batch(req.features, req.node_id)
        return FeatureIngestResponse(
            ingested=count,
            device_count=aggregator.device_count,
        )
    except Exception as exc:
        logger.error("Feature ingest failed: %s", exc)
        return FeatureIngestResponse()


@router.get("/features/{mac}", response_model=FeaturesResponse)
async def get_device_features(mac: str) -> FeaturesResponse:
    """Get accumulated feature vectors for a specific device.

    Returns mean features, contributing node IDs, and observation window.
    """
    try:
        from engine.intelligence.feature_aggregator import get_feature_aggregator
        aggregator = get_feature_aggregator()
        result = aggregator.get_features(mac)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No features for {mac}")
        return FeaturesResponse(**result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get features failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/features", response_model=list[FeaturesResponse])
async def list_all_features(limit: int = Query(100, ge=1, le=1000)) -> list[FeaturesResponse]:
    """List accumulated features for all tracked devices.

    Returns features ordered by most recently seen, limited to `limit` entries.
    """
    try:
        from engine.intelligence.feature_aggregator import get_feature_aggregator
        aggregator = get_feature_aggregator()
        results = aggregator.get_all_features(limit=limit)
        return [FeaturesResponse(**r) for r in results]
    except Exception as exc:
        logger.error("List features failed: %s", exc)
        return []


@router.post("/feedback/classify", response_model=FeedbackResponse)
async def classify_and_feedback(req: FeedbackRequest, user: dict = Depends(optional_auth)) -> FeedbackResponse:
    """Classify a device and send feedback to the originating edge node.

    Triggers ML classification on accumulated features and publishes
    the result via MQTT so the edge node can cache it.
    """
    try:
        from engine.intelligence.feature_aggregator import get_feature_aggregator
        from engine.intelligence.classification_feedback import (
            get_classification_feedback_service,
        )

        aggregator = get_feature_aggregator()
        device_data = aggregator.get_features(req.mac)
        if device_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"No features for {req.mac}",
            )

        feedback_svc = get_classification_feedback_service()
        result = feedback_svc.classify_and_feedback(
            mac=req.mac,
            node_id=req.node_id,
            features=device_data.get("mean_features", {}),
        )

        if result is None:
            return FeedbackResponse(mac=req.mac)

        return FeedbackResponse(
            mac=result.get("mac", req.mac),
            predicted_type=result.get("predicted_type", "unknown"),
            confidence=result.get("confidence", 0.0),
            feedback_sent=True,
            inconsistent=result.get("inconsistent", False),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Classification feedback failed: %s", exc)
        return FeedbackResponse(mac=req.mac)


@router.get("/feedback/{mac}")
async def get_feedback_record(mac: str) -> dict[str, Any]:
    """Get classification feedback history for a device.

    Shows classification consistency and feedback counts.
    """
    try:
        from engine.intelligence.classification_feedback import (
            get_classification_feedback_service,
        )
        svc = get_classification_feedback_service()
        record = svc.get_record(mac)
        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"No classification record for {mac}",
            )
        return record
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Get feedback record failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/edge-metrics", response_model=EdgeMetricsResponse)
async def edge_intelligence_metrics() -> EdgeMetricsResponse:
    """Get per-edge-node intelligence pipeline metrics.

    Shows how many devices each edge node has reported, classification
    rates, feedback health, and pipeline status.
    """
    try:
        from engine.intelligence.feature_aggregator import get_feature_aggregator
        from engine.intelligence.classification_feedback import (
            get_classification_feedback_service,
        )

        aggregator = get_feature_aggregator()
        feedback_svc = get_classification_feedback_service()

        return EdgeMetricsResponse(
            nodes=feedback_svc.get_node_metrics(),
            aggregator_stats=aggregator.get_stats(),
            feedback_stats=feedback_svc.get_stats(),
        )
    except Exception as exc:
        logger.error("Edge metrics failed: %s", exc)
        return EdgeMetricsResponse()
