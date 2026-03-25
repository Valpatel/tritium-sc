// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Handoff Line Visualization -- draws animated handoff arcs on the map
 * when a target transitions from one edge node's detection range to another.
 *
 * Listens for WebSocket "edge_target_handoff" events (the : is converted to _
 * by the WS bridge).  Each handoff draws a brief animated arc from the
 * departure sensor to the arrival sensor, colored by confidence.
 *
 * Uses MapLibre GeoJSON source/layer.  Lines fade out over HANDOFF_DISPLAY_MS.
 *
 * Usage:
 *   import { HandoffLineManager } from './handoff-lines.js';
 *   const mgr = new HandoffLineManager();
 *   mgr.start();
 */

import { EventBus } from '/lib/events.js';

const HANDOFF_SOURCE_ID = 'tritium-handoffs';
const HANDOFF_LAYER_ID = 'tritium-handoffs-layer';
const HANDOFF_DISPLAY_MS = 4000; // how long each handoff line is visible
const CLEANUP_INTERVAL_MS = 500;

/**
 * @typedef {Object} HandoffEntry
 * @property {string} handoff_id
 * @property {string} target_id
 * @property {[number,number]} from_position - [lat, lon]
 * @property {[number,number]} to_position   - [lat, lon]
 * @property {number} confidence
 * @property {number} created_at - Date.now()
 */

export class HandoffLineManager {
    constructor() {
        /** @type {Map<string, HandoffEntry>} */
        this._handoffs = new Map();
        this._map = null;
        this._layersAdded = false;
        this._cleanupTimer = null;
    }

    start() {
        // Listen for handoff events from WebSocket
        // The WS bridge converts "edge:target_handoff" to type "edge_target_handoff"
        // but it goes through broadcast_amy_event which prefixes with "amy_"
        // Actually looking at the code, events in the explicit list get
        // broadcast via broadcast_amy_event(event_type, data) which wraps as
        // { type: "amy_<event_type>", data: ... }
        // BUT edge:target_handoff has a colon — broadcast_amy_event prefixes "amy_"
        // so the WS message type = "amy_edge:target_handoff"
        // Actually let me re-read: broadcast_amy_event does:
        //   {"type": f"amy_{event_type}", ...}
        // so the client sees type = "amy_edge:target_handoff"
        //
        // We listen for both possible formats to be safe.
        EventBus.on('ws:edge:target_handoff', (data) => this._onHandoff(data));
        EventBus.on('ws:edge_target_handoff', (data) => this._onHandoff(data));
        EventBus.on('ws:amy_edge:target_handoff', (data) => this._onHandoff(data));

        // Hook into map when ready
        const checkMap = () => {
            if (window._mapState && window._mapState.map) {
                this._map = window._mapState.map;
                this._ensureLayers();
            }
        };
        checkMap();
        EventBus.on('map:ready', checkMap);

        // Periodic cleanup of expired handoffs
        this._cleanupTimer = setInterval(() => this._cleanup(), CLEANUP_INTERVAL_MS);
    }

    stop() {
        if (this._cleanupTimer) {
            clearInterval(this._cleanupTimer);
            this._cleanupTimer = null;
        }
    }

    /**
     * Handle a handoff event from the WebSocket.
     * @param {Object} data - HandoffEvent dict from the backend
     */
    _onHandoff(data) {
        if (!data || !data.handoff_id) return;

        const from = data.from_position; // [lat, lon] or [x, y]
        const to = data.to_position;

        // Need valid positions
        if (!from || !to) return;
        if (from[0] === 0 && from[1] === 0) return;
        if (to[0] === 0 && to[1] === 0) return;

        this._handoffs.set(data.handoff_id, {
            handoff_id: data.handoff_id,
            target_id: data.target_id || '',
            from_position: from,
            to_position: to,
            confidence: data.confidence || 0.5,
            created_at: Date.now(),
        });

        this._render();
    }

    _cleanup() {
        const now = Date.now();
        let changed = false;
        for (const [id, entry] of this._handoffs) {
            if (now - entry.created_at > HANDOFF_DISPLAY_MS) {
                this._handoffs.delete(id);
                changed = true;
            }
        }
        if (changed) this._render();
    }

    _ensureLayers() {
        if (!this._map || this._layersAdded) return;

        if (!this._map.getSource(HANDOFF_SOURCE_ID)) {
            this._map.addSource(HANDOFF_SOURCE_ID, {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: [] },
            });
        }

        if (!this._map.getLayer(HANDOFF_LAYER_ID)) {
            this._map.addLayer({
                id: HANDOFF_LAYER_ID,
                type: 'line',
                source: HANDOFF_SOURCE_ID,
                paint: {
                    'line-color': ['get', 'color'],
                    'line-width': ['get', 'width'],
                    'line-opacity': ['get', 'opacity'],
                    'line-dasharray': [4, 3],
                },
                layout: {
                    'line-cap': 'round',
                    'line-join': 'round',
                },
            });
        }

        this._layersAdded = true;
    }

    _render() {
        if (!this._map) {
            if (window._mapState && window._mapState.map) {
                this._map = window._mapState.map;
                this._ensureLayers();
            }
            if (!this._map) return;
        }
        this._ensureLayers();

        const source = this._map.getSource(HANDOFF_SOURCE_ID);
        if (!source) return;

        const now = Date.now();
        const features = [];

        for (const entry of this._handoffs.values()) {
            const age = now - entry.created_at;
            const progress = Math.min(1, age / HANDOFF_DISPLAY_MS);

            // Fade out over time
            const opacity = Math.max(0.1, 1 - progress * 0.8);
            // Width based on confidence
            const width = 2 + entry.confidence * 3;
            // Color: high confidence = cyan, low = yellow
            const color = entry.confidence > 0.7 ? '#00f0ff' :
                          entry.confidence > 0.4 ? '#fcee0a' : '#ff2a6d';

            // from_position is [lat, lon] but GeoJSON wants [lon, lat]
            const fromCoord = [entry.from_position[1], entry.from_position[0]];
            const toCoord = [entry.to_position[1], entry.to_position[0]];

            // Create a curved arc through a midpoint offset perpendicular to the line
            const midLon = (fromCoord[0] + toCoord[0]) / 2;
            const midLat = (fromCoord[1] + toCoord[1]) / 2;
            const dx = toCoord[0] - fromCoord[0];
            const dy = toCoord[1] - fromCoord[1];
            const arcOffset = 0.0003; // perpendicular offset for arc
            const arcLon = midLon + dy * arcOffset / (Math.sqrt(dx*dx + dy*dy) || 1);
            const arcLat = midLat - dx * arcOffset / (Math.sqrt(dx*dx + dy*dy) || 1);

            features.push({
                type: 'Feature',
                properties: { color, width, opacity },
                geometry: {
                    type: 'LineString',
                    coordinates: [fromCoord, [arcLon, arcLat], toCoord],
                },
            });
        }

        source.setData({ type: 'FeatureCollection', features });
    }
}
