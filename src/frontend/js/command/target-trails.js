// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Target Trail Color Coding — renders unit movement trails on the map
 * with color based on speed and width based on confidence.
 *
 * Speed color coding:
 *   Green  (#05ffa1) = slow (< 2 m/s, walking)
 *   Yellow (#fcee0a) = moderate (2-8 m/s, jogging/driving slow)
 *   Red    (#ff2a6d) = fast (> 8 m/s, vehicle speed)
 *
 * Width indicates confidence:
 *   High confidence (GPS/trilateration) = 3px
 *   Low confidence (proximity/estimate) = 1px
 *
 * Trail points are collected from TritiumStore.units at 1Hz.
 * Only the last MAX_TRAIL_POINTS are kept per unit.
 * Trails are rendered as MapLibre GeoJSON line layers with per-segment coloring.
 *
 * Usage:
 *   import { TargetTrailManager } from './target-trails.js';
 *   const trails = new TargetTrailManager(mapInstance);
 *   trails.start();
 *   trails.stop();
 */

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';

const MAX_TRAIL_POINTS = 60;     // ~60 seconds of history at 1Hz
const TRAIL_SAMPLE_MS = 1000;    // Sample positions every 1 second
const TRAIL_SOURCE_ID = 'tritium-trails';
const TRAIL_LAYER_ID = 'tritium-trails-layer';
const MIN_MOVE_DIST = 0.000001;  // ~0.1m in degrees — ignore jitter

// Speed thresholds in game-units per second (roughly meters/s)
const SPEED_SLOW = 2;
const SPEED_MODERATE = 8;

/**
 * Calculate approximate speed between two trail points.
 * @param {{ lng: number, lat: number, time: number }} a
 * @param {{ lng: number, lat: number, time: number }} b
 * @returns {number} speed in degrees/second (proxy for m/s at map scale)
 */
function _speedBetween(a, b) {
    const dt = (b.time - a.time) / 1000; // seconds
    if (dt <= 0) return 0;
    const dlng = b.lng - a.lng;
    const dlat = b.lat - a.lat;
    const dist = Math.sqrt(dlng * dlng + dlat * dlat);
    // Convert degrees to approximate meters (at mid-latitudes, 1deg ~ 111km)
    const distMeters = dist * 111000;
    return distMeters / dt;
}

/**
 * Map speed to a hex color.
 */
function _speedColor(speedMs) {
    if (speedMs < SPEED_SLOW) return '#05ffa1';    // green = slow
    if (speedMs < SPEED_MODERATE) return '#fcee0a'; // yellow = moderate
    return '#ff2a6d';                                // red = fast
}

/**
 * Map speed to a trail width.
 */
function _speedWidth(speedMs) {
    if (speedMs < SPEED_SLOW) return 2;
    if (speedMs < SPEED_MODERATE) return 2.5;
    return 3;
}

export class TargetTrailManager {
    constructor() {
        this._trails = new Map(); // unitId -> [{ lng, lat, time }]
        this._timer = null;
        this._map = null;
        this._visible = true;
        this._layersAdded = false;
    }

    /**
     * Start tracking trails. Call after map is initialized.
     * Hooks into the map via window._mapState.map.
     */
    start() {
        this._timer = setInterval(() => this._sample(), TRAIL_SAMPLE_MS);

        // Listen for map ready
        const checkMap = () => {
            if (window._mapState && window._mapState.map) {
                this._map = window._mapState.map;
                this._ensureLayers();
            }
        };
        checkMap();
        EventBus.on('map:ready', checkMap);

        // Listen for trail toggle
        EventBus.on('trails:toggle', () => {
            this._visible = !this._visible;
            this._render();
        });
        EventBus.on('trails:set-visible', (visible) => {
            this._visible = visible;
            this._render();
        });
    }

    stop() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    /**
     * Sample current unit positions and append to trails.
     */
    _sample() {
        const units = TritiumStore.units;
        if (!units || units.size === 0) return;

        const now = Date.now();
        const activeIds = new Set();

        units.forEach((unit, id) => {
            activeIds.add(id);
            const pos = unit.position || {};
            const gx = pos.x || 0;
            const gy = pos.y || 0;
            if (gx === 0 && gy === 0) return;

            // Convert game coords to lng/lat using the same transform as the map
            const lngLat = this._gameToLngLat(gx, gy);
            if (!lngLat) return;

            if (!this._trails.has(id)) {
                this._trails.set(id, []);
            }
            const trail = this._trails.get(id);

            // Skip if position hasn't changed enough (avoid jitter points)
            if (trail.length > 0) {
                const last = trail[trail.length - 1];
                const dlng = Math.abs(lngLat[0] - last.lng);
                const dlat = Math.abs(lngLat[1] - last.lat);
                if (dlng < MIN_MOVE_DIST && dlat < MIN_MOVE_DIST) return;
            }

            trail.push({ lng: lngLat[0], lat: lngLat[1], time: now });

            // Trim to max length
            if (trail.length > MAX_TRAIL_POINTS) {
                trail.splice(0, trail.length - MAX_TRAIL_POINTS);
            }
        });

        // Clean up trails for removed units
        for (const id of this._trails.keys()) {
            if (!activeIds.has(id)) {
                this._trails.delete(id);
            }
        }

        this._render();
    }

    /**
     * Convert game coordinates to [lng, lat].
     * Uses the same reference as map-maplibre's _gameToLngLat.
     */
    _gameToLngLat(gx, gy) {
        const mapState = window._mapState;
        if (!mapState || !mapState.geoCenter) return null;
        const center = mapState.geoCenter;
        // Game units are meters offset from center
        // 1 degree lat ~ 111320m, 1 degree lng ~ 111320 * cos(lat)
        const latRad = center.lat * Math.PI / 180;
        const mPerDegLat = 111320;
        const mPerDegLng = 111320 * Math.cos(latRad);
        return [
            center.lng + gx / mPerDegLng,
            center.lat + gy / mPerDegLat,
        ];
    }

    /**
     * Ensure MapLibre source and layers exist.
     */
    _ensureLayers() {
        if (!this._map || this._layersAdded) return;

        // Add empty GeoJSON source
        if (!this._map.getSource(TRAIL_SOURCE_ID)) {
            this._map.addSource(TRAIL_SOURCE_ID, {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: [] },
            });
        }

        // Add line layer for trail segments
        if (!this._map.getLayer(TRAIL_LAYER_ID)) {
            this._map.addLayer({
                id: TRAIL_LAYER_ID,
                type: 'line',
                source: TRAIL_SOURCE_ID,
                paint: {
                    'line-color': ['get', 'color'],
                    'line-width': ['get', 'width'],
                    'line-opacity': ['get', 'opacity'],
                },
                layout: {
                    'line-cap': 'round',
                    'line-join': 'round',
                },
            });
        }

        this._layersAdded = true;
    }

    /**
     * Render all trails as GeoJSON line features with per-segment coloring.
     */
    _render() {
        if (!this._map) {
            if (window._mapState && window._mapState.map) {
                this._map = window._mapState.map;
                this._ensureLayers();
            }
            if (!this._map) return;
        }
        this._ensureLayers();

        const source = this._map.getSource(TRAIL_SOURCE_ID);
        if (!source) return;

        if (!this._visible) {
            source.setData({ type: 'FeatureCollection', features: [] });
            return;
        }

        const features = [];

        for (const [unitId, trail] of this._trails) {
            if (trail.length < 2) continue;

            // Create per-segment features with speed-based coloring
            for (let i = 0; i < trail.length - 1; i++) {
                const a = trail[i];
                const b = trail[i + 1];
                const speed = _speedBetween(a, b);
                const color = _speedColor(speed);
                const width = _speedWidth(speed);

                // Fade older segments (oldest = most transparent)
                const age = (trail.length - 1 - i) / trail.length;
                const opacity = 0.3 + 0.7 * (1 - age);

                features.push({
                    type: 'Feature',
                    properties: {
                        color,
                        width,
                        opacity,
                        unitId,
                        speed: Math.round(speed * 10) / 10,
                    },
                    geometry: {
                        type: 'LineString',
                        coordinates: [
                            [a.lng, a.lat],
                            [b.lng, b.lat],
                        ],
                    },
                });
            }
        }

        source.setData({ type: 'FeatureCollection', features });
    }
}
