// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Convoy Overlay — draws bounding boxes around detected convoys on the map.
// Color by suspicious score: green=normal, yellow=moderate, red=suspicious.
// Polls /api/convoys every 5 seconds.

import { EventBus } from '/lib/events.js';

const POLL_INTERVAL_MS = 5000;
const SCORE_THRESHOLDS = { low: 0.3, high: 0.6 };

function scoreToColor(score) {
    if (score >= SCORE_THRESHOLDS.high) return 'rgba(255, 42, 109, 0.7)';  // red/magenta
    if (score >= SCORE_THRESHOLDS.low) return 'rgba(252, 238, 10, 0.7)';   // yellow
    return 'rgba(5, 255, 161, 0.5)';  // green
}

function scoreToBorderColor(score) {
    if (score >= SCORE_THRESHOLDS.high) return '#ff2a6d';
    if (score >= SCORE_THRESHOLDS.low) return '#fcee0a';
    return '#05ffa1';
}

export class ConvoyOverlayManager {
    constructor() {
        this._map = null;
        this._timer = null;
        this._convoys = [];
        this._sourceId = 'convoy-overlay-source';
        this._fillLayerId = 'convoy-overlay-fill';
        this._lineLayerId = 'convoy-overlay-line';
        this._labelLayerId = 'convoy-overlay-label';
        this._initialized = false;
    }

    start(map) {
        this._map = map;
        if (!map) return;

        this._ensureLayers();
        this._poll();
        this._timer = setInterval(() => this._poll(), POLL_INTERVAL_MS);

        // Listen for convoy events from WebSocket
        this._unsubConvoy = EventBus.on('convoy_detected', (data) => {
            this._poll();  // refresh immediately on new convoy
        });
    }

    stop() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
        if (this._unsubConvoy) {
            this._unsubConvoy();
            this._unsubConvoy = null;
        }
    }

    _ensureLayers() {
        const map = this._map;
        if (!map || this._initialized) return;

        // Add source
        if (!map.getSource(this._sourceId)) {
            map.addSource(this._sourceId, {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: [] },
            });
        }

        // Fill layer for convoy bounding box
        if (!map.getLayer(this._fillLayerId)) {
            map.addLayer({
                id: this._fillLayerId,
                type: 'fill',
                source: this._sourceId,
                filter: ['==', ['get', 'featureType'], 'bbox'],
                paint: {
                    'fill-color': ['get', 'fillColor'],
                    'fill-opacity': 0.15,
                },
            });
        }

        // Outline layer
        if (!map.getLayer(this._lineLayerId)) {
            map.addLayer({
                id: this._lineLayerId,
                type: 'line',
                source: this._sourceId,
                filter: ['==', ['get', 'featureType'], 'bbox'],
                paint: {
                    'line-color': ['get', 'borderColor'],
                    'line-width': 2,
                    'line-dasharray': [4, 2],
                },
            });
        }

        // Label layer
        if (!map.getLayer(this._labelLayerId)) {
            map.addLayer({
                id: this._labelLayerId,
                type: 'symbol',
                source: this._sourceId,
                filter: ['==', ['get', 'featureType'], 'label'],
                layout: {
                    'text-field': ['get', 'label'],
                    'text-size': 12,
                    'text-font': ['Open Sans Bold'],
                    'text-anchor': 'bottom',
                    'text-offset': [0, -0.5],
                    'text-allow-overlap': true,
                },
                paint: {
                    'text-color': ['get', 'borderColor'],
                    'text-halo-color': '#0a0a0f',
                    'text-halo-width': 2,
                },
            });
        }

        this._initialized = true;
    }

    async _poll() {
        try {
            const resp = await fetch('/api/convoys');
            if (!resp.ok) return;
            const data = await resp.json();
            this._convoys = data.convoys || [];
            this._updateMap();
        } catch (_) {
            // offline
        }
    }

    _updateMap() {
        const map = this._map;
        if (!map) return;

        this._ensureLayers();
        const source = map.getSource(this._sourceId);
        if (!source) return;

        const features = [];

        for (const convoy of this._convoys) {
            const bbox = convoy.bbox;
            if (!bbox) continue;

            const score = convoy.suspicious_score || 0;
            const fillColor = scoreToColor(score);
            const borderColor = scoreToBorderColor(score);
            const memberCount = (convoy.member_target_ids || []).length;

            // Bounding box polygon
            features.push({
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [[
                        [bbox.west, bbox.south],
                        [bbox.east, bbox.south],
                        [bbox.east, bbox.north],
                        [bbox.west, bbox.north],
                        [bbox.west, bbox.south],
                    ]],
                },
                properties: {
                    featureType: 'bbox',
                    convoyId: convoy.convoy_id,
                    fillColor,
                    borderColor,
                    score,
                },
            });

            // Label point at top center of bbox
            features.push({
                type: 'Feature',
                geometry: {
                    type: 'Point',
                    coordinates: [bbox.center_lng, bbox.north],
                },
                properties: {
                    featureType: 'label',
                    label: `CONVOY [${memberCount}] ${Math.round(score * 100)}%`,
                    borderColor,
                    convoyId: convoy.convoy_id,
                },
            });
        }

        source.setData({
            type: 'FeatureCollection',
            features,
        });
    }
}
