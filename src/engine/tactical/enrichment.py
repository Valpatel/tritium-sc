# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Target enrichment pipeline — auto-query intelligence providers on new targets.

When a new target appears (BLE device, detection, etc.), the enrichment pipeline
runs all registered providers in parallel to gather additional intelligence:
OUI manufacturer lookup, WiFi fingerprinting, BLE device classification, and
any custom providers registered at runtime.

The ``device_classifier`` provider delegates to tritium-lib's DeviceClassifier
for multi-signal BLE/WiFi classification using GAP appearance, service UUIDs,
company IDs, Apple continuity data, Google Fast Pair, and name patterns.

Results are cached per (target_id, provider) to avoid redundant queries.
The pipeline subscribes to EventBus for ``ble:new_device`` events and
auto-enriches new targets as they appear.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from ..comms.event_bus import EventBus

logger = logging.getLogger("enrichment")

# Singleton DeviceClassifier — loaded once at import time.
_device_classifier = None
try:
    from tritium_lib.classifier import DeviceClassifier as _DC
    _device_classifier = _DC()
    logger.info("DeviceClassifier loaded from tritium-lib")
except ImportError:
    logger.debug("tritium_lib.classifier not available — DeviceClassifier disabled")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class EnrichmentResult:
    """Result from a single enrichment provider."""

    provider: str
    enrichment_type: str
    data: dict = field(default_factory=dict)
    confidence: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "enrichment_type": self.enrichment_type,
            "data": self.data,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }


# Type alias for provider callbacks:
# (target_id, identifiers) -> EnrichmentResult | None
ProviderCallback = Callable[[str, dict], Awaitable[EnrichmentResult | None]]


# ---------------------------------------------------------------------------
# Built-in providers
# ---------------------------------------------------------------------------

# Common OUI prefixes for offline lookup when tritium-lib data is unavailable
_OUI_FALLBACK: dict[str, str] = {
    "00:1A:7D": "Cyber-Blue(HK)",
    "00:50:C2": "IEEE Registration Authority",
    "24:0A:C4": "Espressif",
    "30:AE:A4": "Espressif",
    "3C:61:05": "Espressif",
    "3C:71:BF": "Espressif",
    "40:F5:20": "Espressif",
    "48:3F:DA": "Espressif",
    "58:CF:79": "Espressif",
    "7C:9E:BD": "Espressif",
    "84:0D:8E": "Espressif",
    "84:CC:A8": "Espressif",
    "8C:AA:B5": "Espressif",
    "94:3C:C6": "Espressif",
    "A4:CF:12": "Espressif",
    "AC:67:B2": "Espressif",
    "B4:E6:2D": "Espressif",
    "BC:DD:C2": "Espressif",
    "C4:4F:33": "Espressif",
    "CC:50:E3": "Espressif",
    "D8:A0:1D": "Espressif",
    "E8:68:E7": "Espressif",
    "F0:08:D1": "Espressif",
    "F4:12:FA": "Espressif",
    "00:17:88": "Philips Lighting",
    "DC:A6:32": "Raspberry Pi",
    "B8:27:EB": "Raspberry Pi",
    "E4:5F:01": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi",
    "00:0A:95": "Apple",
    "3C:E0:72": "Apple",
    "F0:18:98": "Apple",
    "AC:BC:32": "Apple",
    "F8:FF:C2": "Apple",
    "00:25:00": "Apple",
    "A4:83:E7": "Apple",
    "40:B4:CD": "Samsung",
    "8C:F5:A3": "Samsung",
    "00:1E:75": "Samsung",
    "78:47:1D": "Samsung",
    "60:AF:6D": "Samsung",
}


async def _oui_lookup(target_id: str, identifiers: dict) -> EnrichmentResult | None:
    """Look up manufacturer from MAC address OUI prefix."""
    mac = identifiers.get("mac", "")
    if not mac or len(mac) < 8:
        return None

    # Normalize MAC: uppercase, colon-separated
    mac_clean = mac.upper().replace("-", ":").replace(".", ":")
    prefix = mac_clean[:8]  # "AA:BB:CC"

    # Look up manufacturer from built-in OUI table
    manufacturer = None
    if not manufacturer:
        manufacturer = _OUI_FALLBACK.get(prefix)

    if not manufacturer:
        return None

    return EnrichmentResult(
        provider="oui_lookup",
        enrichment_type="manufacturer",
        data={"mac": mac_clean, "prefix": prefix, "manufacturer": manufacturer},
        confidence=0.95,
    )


# WiFi fingerprint patterns: SSID patterns -> device type hint
_WIFI_PATTERNS: list[tuple[str, str, float]] = [
    (r"(?i)^iPhone", "phone", 0.9),
    (r"(?i)^Android[_\- ]", "phone", 0.85),
    (r"(?i)^Galaxy[_\- ]", "phone", 0.85),
    (r"(?i)^Pixel[_\- ]", "phone", 0.85),
    (r"(?i)^DIRECT-", "printer", 0.7),
    (r"(?i)^HP-", "printer", 0.7),
    (r"(?i)^ChromeCast", "media_player", 0.8),
    (r"(?i)^Roku", "media_player", 0.8),
    (r"(?i)^FireTV", "media_player", 0.8),
    (r"(?i)^Ring[_\- ]", "camera", 0.8),
    (r"(?i)^Nest[_\- ]", "smart_home", 0.75),
    (r"(?i)^Amazon[_\- ]", "smart_home", 0.6),
    (r"(?i)^Echo[_\- ]", "smart_home", 0.75),
    (r"(?i)MacBook", "laptop", 0.85),
    (r"(?i)^LAPTOP-", "laptop", 0.8),
    (r"(?i)^DESKTOP-", "desktop", 0.8),
    (r"(?i)Tesla", "vehicle", 0.7),
    (r"(?i)^xfinitywifi$", "hotspot", 0.5),
    (r"(?i)^ATT.*Hotspot", "hotspot", 0.5),
]


async def _wifi_fingerprint(target_id: str, identifiers: dict) -> EnrichmentResult | None:
    """Classify device type from probed SSIDs."""
    ssids = identifiers.get("probed_ssids", [])
    if not ssids:
        return None

    best_type = None
    best_confidence = 0.0
    matched_ssid = ""

    for ssid in ssids:
        for pattern, device_type, confidence in _WIFI_PATTERNS:
            if re.search(pattern, ssid):
                if confidence > best_confidence:
                    best_type = device_type
                    best_confidence = confidence
                    matched_ssid = ssid

    if not best_type:
        return None

    return EnrichmentResult(
        provider="wifi_fingerprint",
        enrichment_type="device_type",
        data={
            "device_type": best_type,
            "matched_ssid": matched_ssid,
            "ssid_count": len(ssids),
        },
        confidence=best_confidence,
    )


# BLE device name patterns -> category
_BLE_NAME_PATTERNS: list[tuple[str, str, float]] = [
    (r"(?i)^iPhone", "phone", 0.9),
    (r"(?i)^Samsung", "phone", 0.8),
    (r"(?i)^Pixel", "phone", 0.85),
    (r"(?i)^Galaxy", "phone", 0.8),
    (r"(?i)Watch", "watch", 0.85),
    (r"(?i)^Fitbit", "watch", 0.9),
    (r"(?i)^Garmin", "watch", 0.9),
    (r"(?i)AirPod", "earbuds", 0.95),
    (r"(?i)^Bose", "headphones", 0.85),
    (r"(?i)^Sony.*WH", "headphones", 0.85),
    (r"(?i)^JBL", "speaker", 0.8),
    (r"(?i)^UE.*BOOM", "speaker", 0.85),
    (r"(?i)MacBook", "laptop", 0.9),
    (r"(?i)^iPad", "tablet", 0.9),
    (r"(?i)^Fire.*HD", "tablet", 0.8),
    (r"(?i)^Tile", "tracker", 0.9),
    (r"(?i)^AirTag", "tracker", 0.95),
    (r"(?i)^Chipolo", "tracker", 0.9),
    (r"(?i)^Tesla", "vehicle", 0.8),
    (r"(?i)^Govee", "light", 0.85),
    (r"(?i)^Wyze", "camera", 0.8),
    (r"(?i)^Ring", "camera", 0.8),
    (r"(?i)^ESP32", "microcontroller", 0.9),
    (r"(?i)^Raspberry", "microcontroller", 0.85),
    (r"(?i)^Nintendo", "game_console", 0.9),
    (r"(?i)^Xbox", "game_console", 0.9),
    (r"(?i)^DualSense", "game_controller", 0.9),
]


async def _ble_device_class(target_id: str, identifiers: dict) -> EnrichmentResult | None:
    """Classify BLE device category from name patterns."""
    name = identifiers.get("name", "")
    if not name:
        return None

    for pattern, category, confidence in _BLE_NAME_PATTERNS:
        if re.search(pattern, name):
            return EnrichmentResult(
                provider="ble_device_class",
                enrichment_type="device_category",
                data={"category": category, "matched_name": name},
                confidence=confidence,
            )
    return None


async def _device_classifier_provider(
    target_id: str, identifiers: dict
) -> EnrichmentResult | None:
    """Classify device using tritium-lib DeviceClassifier with all available signals.

    Accepts identifiers dict with optional keys:
        mac, name, company_id, appearance, service_uuids,
        fast_pair_model_id, apple_device_class, ssid, bssid, probed_ssids
    """
    if _device_classifier is None:
        return None

    # Determine if this is a BLE or WiFi target
    mac = identifiers.get("mac", "")
    name = identifiers.get("name", "")
    ssid = identifiers.get("ssid", "")
    bssid = identifiers.get("bssid", "")

    classification = None

    if mac or name or identifiers.get("company_id") is not None:
        # BLE classification with all available signals
        classification = _device_classifier.classify_ble(
            mac=mac,
            name=name,
            company_id=identifiers.get("company_id"),
            appearance=identifiers.get("appearance"),
            service_uuids=identifiers.get("service_uuids"),
            fast_pair_model_id=identifiers.get("fast_pair_model_id"),
            apple_device_class=identifiers.get("apple_device_class"),
        )
    elif ssid or bssid or identifiers.get("probed_ssids"):
        # WiFi classification
        classification = _device_classifier.classify_wifi(
            ssid=ssid,
            bssid=bssid,
            probed_ssids=identifiers.get("probed_ssids"),
        )

    if classification is None or classification.device_type == "unknown":
        return None

    return EnrichmentResult(
        provider="device_classifier",
        enrichment_type="device_classification",
        data=classification.to_dict(),
        confidence=classification.confidence,
    )


# ---------------------------------------------------------------------------
# EnrichmentPipeline
# ---------------------------------------------------------------------------

class EnrichmentPipeline:
    """Runs registered enrichment providers in parallel against targets.

    Parameters
    ----------
    event_bus:
        Optional EventBus to subscribe to for auto-enrichment on new targets.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._providers: dict[str, ProviderCallback] = {}
        self._cache: dict[str, list[EnrichmentResult]] = {}  # target_id -> results
        self._lock = threading.Lock()
        self._event_bus = event_bus
        self._listener_thread: threading.Thread | None = None
        self._running = False

        # Register built-in providers
        self.register_provider("oui_lookup", _oui_lookup)
        self.register_provider("wifi_fingerprint", _wifi_fingerprint)
        self.register_provider("ble_device_class", _ble_device_class)
        self.register_provider("device_classifier", _device_classifier_provider)

        # Auto-subscribe to EventBus if provided
        if event_bus is not None:
            self._start_listener()

    def register_provider(self, name: str, callback: ProviderCallback) -> None:
        """Register an enrichment provider.

        Args:
            name: Unique provider name.
            callback: Async callable (target_id, identifiers) -> EnrichmentResult | None.
        """
        self._providers[name] = callback
        logger.info("Registered enrichment provider: %s", name)

    def unregister_provider(self, name: str) -> bool:
        """Remove a registered provider. Returns True if it existed."""
        return self._providers.pop(name, None) is not None

    def get_provider_names(self) -> list[str]:
        """Return names of all registered providers."""
        return list(self._providers.keys())

    async def enrich(self, target_id: str, identifiers: dict) -> list[EnrichmentResult]:
        """Run all providers in parallel and return enrichment results.

        Results are cached. Subsequent calls for the same target_id return
        cached data without re-querying providers.

        Args:
            target_id: Unique target identifier.
            identifiers: Dict of known identifiers (mac, name, probed_ssids, etc.)

        Returns:
            List of EnrichmentResult from all providers (empty results filtered out).
        """
        # Check cache first
        with self._lock:
            if target_id in self._cache:
                return list(self._cache[target_id])

        # Run all providers in parallel
        tasks = [
            self._run_provider(name, cb, target_id, identifiers)
            for name, cb in self._providers.items()
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[EnrichmentResult] = []
        for r in raw_results:
            if isinstance(r, EnrichmentResult):
                results.append(r)
            elif isinstance(r, Exception):
                logger.warning("Enrichment provider error: %s", r)

        # Cache results
        with self._lock:
            self._cache[target_id] = list(results)

        logger.info(
            "Enriched target %s: %d results from %d providers",
            target_id, len(results), len(self._providers),
        )
        return results

    async def force_enrich(self, target_id: str, identifiers: dict) -> list[EnrichmentResult]:
        """Force re-enrichment, bypassing cache."""
        with self._lock:
            self._cache.pop(target_id, None)
        return await self.enrich(target_id, identifiers)

    def get_cached(self, target_id: str) -> list[EnrichmentResult] | None:
        """Return cached enrichment results for a target, or None if not cached."""
        with self._lock:
            cached = self._cache.get(target_id)
            return list(cached) if cached is not None else None

    def clear_cache(self, target_id: str | None = None) -> None:
        """Clear cache for a specific target, or all targets if None."""
        with self._lock:
            if target_id is not None:
                self._cache.pop(target_id, None)
            else:
                self._cache.clear()

    def stop(self) -> None:
        """Stop the EventBus listener thread."""
        self._running = False
        if self._listener_thread is not None:
            self._listener_thread.join(timeout=2.0)
            self._listener_thread = None

    # -- Internal --------------------------------------------------------------

    @staticmethod
    async def _run_provider(
        name: str,
        callback: ProviderCallback,
        target_id: str,
        identifiers: dict,
    ) -> EnrichmentResult | None:
        """Run a single provider, catching exceptions."""
        try:
            return await callback(target_id, identifiers)
        except Exception as exc:
            logger.warning("Provider %s failed for %s: %s", name, target_id, exc)
            return None

    def _start_listener(self) -> None:
        """Start background thread listening to EventBus for new targets."""
        if self._event_bus is None:
            return
        self._running = True
        self._listener_thread = threading.Thread(
            target=self._event_listener_loop,
            name="enrichment-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def _event_listener_loop(self) -> None:
        """Background loop: listen to EventBus, auto-enrich new targets."""
        import queue as queue_mod

        bus_queue = self._event_bus.subscribe()
        try:
            while self._running:
                try:
                    msg = bus_queue.get(timeout=1.0)
                except queue_mod.Empty:
                    continue

                event_type = msg.get("type", "")
                # Auto-enrich on BLE new device events
                if event_type in ("ble:new_device", "ble:suspicious_device"):
                    data = msg.get("data", {})
                    mac = data.get("mac", "")
                    name = data.get("name", "")
                    if mac:
                        target_id = f"ble_{mac.replace(':', '').lower()}"
                        identifiers = {"mac": mac, "name": name}
                        self._enrich_in_background(target_id, identifiers)
        finally:
            self._event_bus.unsubscribe(bus_queue)

    def _enrich_in_background(self, target_id: str, identifiers: dict) -> None:
        """Schedule enrichment on an asyncio event loop (or create one)."""
        try:
            loop = asyncio.get_running_loop()
            asyncio.ensure_future(self.enrich(target_id, identifiers), loop=loop)
        except RuntimeError:
            # No running loop — create a temporary one
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.enrich(target_id, identifiers))
            finally:
                loop.close()
