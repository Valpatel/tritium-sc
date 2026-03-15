// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Prediction Confidence Ellipses — renders directional uncertainty
 * ellipses on the map for each tracked target.
 *
 * Instead of circles, the ellipse stretches along the target's direction
 * of travel. Uncertainty is lower in the direction of motion (longitudinal)
 * and higher laterally (perpendicular to travel).
 *
 * The ellipse axes are:
 *   - Semi-major axis (lateral): proportional to position uncertainty
 *   - Semi-minor axis (longitudinal): compressed based on speed/confidence
 *   - Rotation: aligned with heading (direction of travel)
 *
 * Uses the target trail history to compute heading and speed.
 *
 * Usage:
 *   import { PredictionEllipseManager } from './prediction-ellipses.js';
 *   const ellipses = new PredictionEllipseManager();
 *   ellipses.start();
 */

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';

const ELLIPSE_SOURCE_ID = 'tritium-prediction-ellipses';
const ELLIPSE_FILL_LAYER_ID = 'tritium-prediction-ellipses-fill';
const ELLIPSE_STROKE_LAYER_ID = 'tritium-prediction-ellipses-stroke';
const UPDATE_INTERVAL_MS = 1000;     // Update at 1Hz (ellipses don't need 10Hz)
const ELLIPSE_SEGMENTS = 36;         // Points per ellipse polygon
const BASE_RADIUS_M = 15;            // Base uncertainty radius in meters
const MIN_RADIUS_M = 3;              // Minimum radius even for high-confidence
const MAX_RADIUS_M = 80;             // Max radius for very uncertain positions
const SPEED_COMPRESSION = 0.4;       // How much speed compresses the longitudinal axis (0-1)

const ALLIANCE_FILL = {
    friendly: 'rgba(5, 255, 161, 0.08)',
    hostile:  'rgba(255, 42, 109, 0.12)',
    neutral:  'rgba(0, 160, 255, 0.08)',
    unknown:  'rgba(252, 238, 10, 0.08)',
};

const ALLIANCE_STROKE = {
    friendly: 'rgba(5, 255, 161, 0.35)',
    hostile:  'rgba(255, 42, 109, 0.45)',
    neutral:  'rgba(0, 160, 255, 0.35)',
    unknown:  'rgba(252, 238, 10, 0.35)',
};

/**
 * Generate an ellipse polygon (in lng/lat) centered at a point,
 * with given semi-major and semi-minor axes and rotation angle.
 *
 * @param {number} centerLng
 * @param {number} centerLat
 * @param {number} semiMajorM - semi-major axis in meters (lateral/perpendicular)
 * @param {number} semiMinorM - semi-minor axis in meters (longitudinal/along heading)
 * @param {number} rotationRad - rotation in radians (0 = north, CW positive)
 * @returns {Array<[number, number]>} Array of [lng, lat] coordinates
 */
function _generateEllipseCoords(centerLng, centerLat, semiMajorM, semiMinorM, rotationRad) {
    const coords = [];
    const latRad = centerLat * Math.PI / 180;
    const mPerDegLat = 111320;
    const mPerDegLng = 111320 * Math.cos(latRad);

    for (let i = 0; i <= ELLIPSE_SEGMENTS; i++) {
        const angle = (i / ELLIPSE_SEGMENTS) * 2 * Math.PI;

        // Point on unit ellipse
        const ex = semiMajorM * Math.cos(angle);
        const ey = semiMinorM * Math.sin(angle);

        // Rotate by heading (rotation is from north, CW)
        const cosR = Math.cos(rotationRad);
        const sinR = Math.sin(rotationRad);
        const rx = ex * cosR - ey * sinR;
        const ry = ex * sinR + ey * cosR;

        // Convert meters offset to degrees
        const dLng = rx / mPerDegLng;
        const dLat = ry / mPerDegLat;

        coords.push([centerLng + dLng, centerLat + dLat]);
    }

    return coords;
}

/**
 * Compute heading from recent trail points (radians, 0=north, CW positive).
 * Returns null if insufficient data.
 */
function _computeHeadingFromTrail(trail) {
    if (!trail || trail.length < 2) return null;

    // Use last 3 points for smoother heading
    const n = Math.min(trail.length, 3);
    const recent = trail.slice(-n);
    const first = recent[0];
    const last = recent[recent.length - 1];

    const dlng = last.lng - first.lng;
    const dlat = last.lat - first.lat;
    const dist = Math.sqrt(dlng * dlng + dlat * dlat);

    // If too little movement, no reliable heading
    if (dist < 0.0000005) return null;

    // atan2(dlng, dlat) gives heading from north, CW positive
    return Math.atan2(dlng, dlat);
}

/**
 * Compute speed from trail in m/s.
 */
function _computeSpeedFromTrail(trail) {
    if (!trail || trail.length < 2) return 0;

    const a = trail[trail.length - 2];
    const b = trail[trail.length - 1];
    const dt = (b.time - a.time) / 1000;
    if (dt <= 0) return 0;

    const dlng = b.lng - a.lng;
    const dlat = b.lat - a.lat;
    const distDeg = Math.sqrt(dlng * dlng + dlat * dlat);
    return (distDeg * 111000) / dt;
}


export class PredictionEllipseManager {
    constructor() {
        this._map = null;
        this._timer = null;
        this._visible = true;
        this._layersAdded = false;
        // Trail data shared from TargetTrailManager via the store
        this._trailData = new Map(); // unitId -> [{ lng, lat, time }]
    }

    start() {
        this._timer = setInterval(() => this._update(), UPDATE_INTERVAL_MS);

        const checkMap = () => {
            if (window._mapState && window._mapState.map) {
                this._map = window._mapState.map;
                this._ensureLayers();
            }
        };
        checkMap();
        EventBus.on('map:ready', checkMap);

        EventBus.on('prediction-ellipses:toggle', () => {
            this._visible = !this._visible;
            this._render();
        });
        EventBus.on('prediction-ellipses:set-visible', (v) => {
            this._visible = v;
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
     * Accept trail data from an external source (e.g., TargetTrailManager).
     * @param {Map} trails - Map of unitId -> [{ lng, lat, time }]
     */
    setTrailData(trails) {
        this._trailData = trails;
    }

    _ensureLayers() {
        if (!this._map || this._layersAdded) return;

        if (!this._map.getSource(ELLIPSE_SOURCE_ID)) {
            this._map.addSource(ELLIPSE_SOURCE_ID, {
                type: 'geojson',
                data: { type: 'FeatureCollection', features: [] },
            });
        }

        // Fill layer (semi-transparent)
        if (!this._map.getLayer(ELLIPSE_FILL_LAYER_ID)) {
            this._map.addLayer({
                id: ELLIPSE_FILL_LAYER_ID,
                type: 'fill',
                source: ELLIPSE_SOURCE_ID,
                paint: {
                    'fill-color': ['get', 'fillColor'],
                    'fill-opacity': 1.0,  // opacity is baked into the fillColor
                },
            });
        }

        // Stroke layer (outline)
        if (!this._map.getLayer(ELLIPSE_STROKE_LAYER_ID)) {
            this._map.addLayer({
                id: ELLIPSE_STROKE_LAYER_ID,
                type: 'line',
                source: ELLIPSE_SOURCE_ID,
                paint: {
                    'line-color': ['get', 'strokeColor'],
                    'line-width': 1.5,
                    'line-opacity': 1.0,
                    'line-dasharray': [4, 3],
                },
            });
        }

        this._layersAdded = true;
    }

    _update() {
        // Sample trail positions from TritiumStore units
        const units = TritiumStore.units;
        if (!units || units.size === 0) return;

        const mapState = window._mapState;
        if (!mapState || !mapState.geoCenter) return;

        const now = Date.now();
        const center = mapState.geoCenter;
        const latRad = center.lat * Math.PI / 180;
        const mPerDegLat = 111320;
        const mPerDegLng = 111320 * Math.cos(latRad);

        units.forEach((unit, id) => {
            const pos = unit.position || {};
            const gx = pos.x || 0;
            const gy = pos.y || 0;
            if (gx === 0 && gy === 0) return;

            const lng = center.lng + gx / mPerDegLng;
            const lat = center.lat + gy / mPerDegLat;

            if (!this._trailData.has(id)) {
                this._trailData.set(id, []);
            }
            const trail = this._trailData.get(id);

            // Skip if position hasn't moved
            if (trail.length > 0) {
                const last = trail[trail.length - 1];
                if (Math.abs(lng - last.lng) < 0.0000001 && Math.abs(lat - last.lat) < 0.0000001) {
                    // Update time only
                    last.time = now;
                    return;
                }
            }

            trail.push({ lng, lat, time: now });
            if (trail.length > 30) {
                trail.splice(0, trail.length - 30);
            }
        });

        // Clean up stale trails
        const activeIds = new Set();
        units.forEach((_, id) => activeIds.add(id));
        for (const id of this._trailData.keys()) {
            if (!activeIds.has(id)) {
                this._trailData.delete(id);
            }
        }

        this._render();
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

        const source = this._map.getSource(ELLIPSE_SOURCE_ID);
        if (!source) return;

        if (!this._visible) {
            source.setData({ type: 'FeatureCollection', features: [] });
            return;
        }

        const units = TritiumStore.units;
        if (!units || units.size === 0) {
            source.setData({ type: 'FeatureCollection', features: [] });
            return;
        }

        const features = [];
        const mapState = window._mapState;
        if (!mapState || !mapState.geoCenter) return;

        const center = mapState.geoCenter;
        const latRad = center.lat * Math.PI / 180;
        const mPerDegLng = 111320 * Math.cos(latRad);
        const mPerDegLat = 111320;

        units.forEach((unit, id) => {
            const pos = unit.position || {};
            const gx = pos.x || 0;
            const gy = pos.y || 0;
            if (gx === 0 && gy === 0) return;

            const lng = center.lng + gx / mPerDegLng;
            const lat = center.lat + gy / mPerDegLat;

            const alliance = unit.alliance || 'unknown';
            const confidence = unit.position_confidence ?? unit.confidence ?? 0.5;
            const trail = this._trailData.get(id);
            const heading = _computeHeadingFromTrail(trail);
            const speed = _computeSpeedFromTrail(trail);

            // Compute ellipse parameters
            // Uncertainty radius inversely proportional to confidence
            const uncertaintyBase = MIN_RADIUS_M + (MAX_RADIUS_M - MIN_RADIUS_M) * (1 - confidence);

            // Lateral axis (perpendicular to motion) = full uncertainty
            const semiMajor = Math.max(MIN_RADIUS_M, uncertaintyBase);

            // Longitudinal axis (along motion) = compressed by speed
            // Higher speed = more confident about direction = smaller longitudinal uncertainty
            const speedFactor = Math.min(1.0, speed / 5.0); // normalize speed to 0-1 at 5 m/s
            const compression = 1.0 - speedFactor * SPEED_COMPRESSION;
            const semiMinor = Math.max(MIN_RADIUS_M, semiMajor * compression);

            // If no heading (stationary), draw a circle
            const rotation = heading !== null ? heading : 0;
            const effectiveMajor = heading !== null ? semiMajor : semiMinor;

            const coords = _generateEllipseCoords(lng, lat, effectiveMajor, semiMinor, rotation);

            const fillColor = ALLIANCE_FILL[alliance] || ALLIANCE_FILL.unknown;
            const strokeColor = ALLIANCE_STROKE[alliance] || ALLIANCE_STROKE.unknown;

            features.push({
                type: 'Feature',
                properties: {
                    unitId: id,
                    fillColor,
                    strokeColor,
                    confidence: Math.round(confidence * 100),
                    speed: Math.round(speed * 10) / 10,
                },
                geometry: {
                    type: 'Polygon',
                    coordinates: [coords],
                },
            });
        });

        source.setData({ type: 'FeatureCollection', features });
    }
}
