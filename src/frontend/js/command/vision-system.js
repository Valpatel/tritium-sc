// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Frontend Vision System
 *
 * Provides tactical fog of war, directional vision cones, sweep animation,
 * and ghost tracking for the MapLibre + Three.js tactical overlay.
 *
 * Architecture:
 *   - Pure geometry helpers (isInCone, updateSweepAngle) are testable without canvas/Three.js
 *   - GhostTracker maintains last-known positions for invisible hostiles
 *   - FrontendVisionSystem composites a fog overlay using an offscreen canvas
 *     and renders it as a Three.js CanvasTexture on a screen-aligned plane
 *
 * Heading convention: 0=north, clockwise (matching SimulationTarget).
 */

import { getVisionProfile, getType } from './unit-types/registry.js';

// ============================================================
// Pure geometry helpers
// ============================================================

/**
 * Check whether a point is inside a vision cone.
 * @param {number} unitX - unit X position (game meters)
 * @param {number} unitY - unit Y position (game meters)
 * @param {number} heading - unit heading in degrees (0=north, CW)
 * @param {number} coneAngle - total cone angle in degrees
 * @param {number} coneRange - cone range in meters
 * @param {number} targetX - target X position
 * @param {number} targetY - target Y position
 * @returns {boolean}
 */
export function isInCone(unitX, unitY, heading, coneAngle, coneRange, targetX, targetY) {
    const dx = targetX - unitX;
    const dy = targetY - unitY;
    const dist = Math.hypot(dx, dy);
    if (dist > coneRange) return false;
    // Heading: 0=north(+Y), 90=east(+X), CW
    // atan2(dx, dy) gives angle from +Y axis CW, matching our heading convention
    const angleToTarget = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
    const normalizedHeading = ((heading % 360) + 360) % 360;
    let diff = angleToTarget - normalizedHeading;
    if (diff > 180) diff -= 360;
    if (diff < -180) diff += 360;
    return Math.abs(diff) <= coneAngle / 2;
}

/**
 * Advance a sweep angle by RPM over dt seconds.
 * @param {number} currentAngle - current sweep angle (degrees)
 * @param {number} rpm - revolutions per minute
 * @param {number} dt - time step in seconds
 * @returns {number} new angle (0..360)
 */
export function updateSweepAngle(currentAngle, rpm, dt) {
    return (currentAngle + rpm * 360 * dt / 60) % 360;
}

// ============================================================
// GhostTracker
// ============================================================

const VISUAL_GHOST_FADE_SECONDS = 30;
const RADIO_GHOST_FADE_SECONDS = 60;

export class GhostTracker {
    constructor() {
        /** @type {Map<string, {x: number, y: number, age: number, opacity: number, type: string, mac: string, uncertainty: number}>} */
        this._ghosts = new Map();
        /** @type {Set<string>} IDs that have fully faded -- do not re-create */
        this._fadedIds = new Set();
    }

    /**
     * Update ghost state from the current unit list.
     * @param {Array} units - array of unit objects with target_id, alliance, visible, position,
     *                        radio_detected, radio_signal_strength, identity
     * @param {number} dt - time step in seconds
     */
    update(units, dt) {
        // Track which hostile IDs are currently visible
        const visibleIds = new Set();
        const invisibleHostiles = new Map();
        const radioDetected = new Map();

        for (const u of units) {
            if (u.alliance !== 'hostile') continue;
            if (u.visible === true) {
                visibleIds.add(u.target_id);
            } else if (u.visible === false) {
                invisibleHostiles.set(u.target_id, u);
            }
            // Track radio-detected units separately
            if (u.radio_detected === true) {
                radioDetected.set(u.target_id, u);
            }
        }

        // Remove ghosts that became visible (and allow re-ghosting later)
        for (const id of visibleIds) {
            this._ghosts.delete(id);
            this._fadedIds.delete(id);
        }

        // Create or update ghosts for invisible hostiles
        for (const [id, u] of invisibleHostiles) {
            // Determine ghost type: radio if radio_detected, else visual
            const isRadio = radioDetected.has(id);
            const fadeSecs = isRadio ? RADIO_GHOST_FADE_SECONDS : VISUAL_GHOST_FADE_SECONDS;
            const ghostType = isRadio ? 'radio' : 'visual';
            const mac = isRadio ? _extractMac(u) : '';

            if (!this._ghosts.has(id) && !this._fadedIds.has(id)) {
                this._ghosts.set(id, {
                    x: u.position.x,
                    y: u.position.y,
                    age: 0,
                    opacity: 1.0,
                    type: ghostType,
                    mac: mac,
                    uncertainty: 0,
                });
            } else if (this._ghosts.has(id)) {
                const g = this._ghosts.get(id);
                g.age += dt;
                // If radio contact re-established, upgrade ghost type and reset fade
                if (isRadio && g.type === 'visual') {
                    g.type = 'radio';
                    g.mac = mac;
                }
                const activeFade = g.type === 'radio' ? RADIO_GHOST_FADE_SECONDS : VISUAL_GHOST_FADE_SECONDS;
                g.opacity = Math.max(0, 1.0 - g.age / activeFade);
                // Uncertainty ring grows with age (meters of positional error)
                g.uncertainty = g.age * 0.5;
            }
        }

        // Age and fade ghosts not in current unit list (disappeared entirely)
        for (const [id, g] of this._ghosts) {
            if (!invisibleHostiles.has(id) && !visibleIds.has(id)) {
                g.age += dt;
                const fadeSecs = g.type === 'radio' ? RADIO_GHOST_FADE_SECONDS : VISUAL_GHOST_FADE_SECONDS;
                g.opacity = Math.max(0, 1.0 - g.age / fadeSecs);
                g.uncertainty = g.age * 0.5;
            }
        }

        // Remove fully faded ghosts (and remember them so they aren't re-created)
        for (const [id, g] of this._ghosts) {
            if (g.opacity <= 0) {
                this._ghosts.delete(id);
                this._fadedIds.add(id);
            }
        }
    }

    /**
     * Get ghost data for a specific target.
     * @param {string} targetId
     * @returns {{x: number, y: number, age: number, opacity: number, type: string, mac: string, uncertainty: number}|null}
     */
    getGhost(targetId) {
        return this._ghosts.get(targetId) || null;
    }

    /**
     * Get all ghost entries as [id, ghostData] pairs.
     * @returns {Array<[string, {x: number, y: number, age: number, opacity: number, type: string, mac: string, uncertainty: number}]>}
     */
    getAll() {
        return [...this._ghosts.entries()];
    }

    /**
     * Get only radio-type ghosts.
     * @returns {Array<[string, object]>}
     */
    getRadioGhosts() {
        return [...this._ghosts.entries()].filter(([, g]) => g.type === 'radio');
    }

    /**
     * Get only visual-type ghosts.
     * @returns {Array<[string, object]>}
     */
    getVisualGhosts() {
        return [...this._ghosts.entries()].filter(([, g]) => g.type === 'visual');
    }
}

/**
 * Extract the best MAC address from a unit for radio ghost labeling.
 * Prefers bluetooth_mac, falls back to wifi_mac.
 * @param {object} u - unit object with identity field
 * @returns {string} MAC address or empty string
 */
function _extractMac(u) {
    const id = u.identity;
    if (!id) return '';
    return id.bluetooth_mac || id.wifi_mac || '';
}

// ============================================================
// FrontendVisionSystem
// ============================================================

export class FrontendVisionSystem {
    constructor() {
        this._enabled = false;
        this._disposed = false;
        this._ghostTracker = new GhostTracker();
        this._sweepAngles = new Map();
        this._fogCanvas = null;
        this._fogCtx = null;
        this._fogTexture = null;
        this._fogMesh = null;
        this._buildings = [];
    }

    /**
     * Initialize Three.js fog overlay objects.
     * @param {THREE.Scene} threeScene
     * @param {object} mapState - reference to _state from map-maplibre.js
     */
    init(threeScene, mapState) {
        this._mapState = mapState;

        // Create offscreen canvas for fog compositing
        this._fogCanvas = document.createElement('canvas');
        this._fogCanvas.width = 1024;
        this._fogCanvas.height = 1024;
        this._fogCtx = this._fogCanvas.getContext('2d');

        // Create Three.js CanvasTexture + screen-aligned plane
        if (typeof THREE !== 'undefined') {
            this._fogTexture = new THREE.CanvasTexture(this._fogCanvas);
            this._fogTexture.minFilter = THREE.LinearFilter;
            this._fogTexture.magFilter = THREE.LinearFilter;

            const mat = new THREE.MeshBasicMaterial({
                map: this._fogTexture,
                transparent: true,
                depthTest: false,
                depthWrite: false,
            });

            const geom = new THREE.PlaneGeometry(2, 2);
            this._fogMesh = new THREE.Mesh(geom, mat);
            this._fogMesh.frustumCulled = false;
            this._fogMesh.renderOrder = 999;
            threeScene.add(this._fogMesh);
        }
    }

    /**
     * Per-frame update: sweep angles, fog overlay, ghost tracker.
     * @param {Array} units - array of unit objects from TritiumStore
     * @param {string} gamePhase - current game phase
     * @param {number} dt - time step in seconds
     */
    update(units, gamePhase, dt) {
        if (!this._enabled || this._disposed) return;

        // Update sweep angles for sweeping units
        for (const unit of units) {
            if (unit.alliance !== 'friendly') continue;
            const profile = getVisionProfile(unit.asset_type || unit.type);
            if (profile.coneSweeps && profile.coneSweepRPM > 0) {
                const current = this._sweepAngles.get(unit.target_id) || (unit.heading || 0);
                this._sweepAngles.set(unit.target_id, updateSweepAngle(current, profile.coneSweepRPM, dt));
            }
        }

        // Draw fog overlay
        if (this._fogCtx) {
            const w = this._fogCanvas.width;
            const h = this._fogCanvas.height;
            this._fogCtx.clearRect(0, 0, w, h);
            this._drawFog(this._fogCtx, w, h, units);
            this._drawConeEdges(this._fogCtx, units);
            if (this._fogTexture) {
                this._fogTexture.needsUpdate = true;
            }
        }

        // Update ghost tracker
        this._ghostTracker.update(units, dt);
    }

    /**
     * Set building footprints for fog occlusion.
     * @param {Array} buildings - array of {points: [[x,y],...]} objects
     */
    setBuildings(buildings) {
        this._buildings = buildings;
    }

    enable() { this._enabled = true; }
    disable() { this._enabled = false; }

    get enabled() { return this._enabled; }

    get ghostTracker() { return this._ghostTracker; }

    dispose() {
        this._disposed = true;
        if (this._fogMesh && this._fogMesh.parent) {
            this._fogMesh.parent.remove(this._fogMesh);
        }
        if (this._fogTexture) {
            this._fogTexture.dispose();
        }
        if (this._fogMesh) {
            this._fogMesh.geometry.dispose();
            this._fogMesh.material.dispose();
        }
    }

    /**
     * Convert game-meter position {x, y} or {lng, lat} to fog canvas pixel coords.
     * Uses MapLibre's project() to go from geographic coords to screen pixels,
     * then scales to the 1024x1024 fog canvas.
     * Override in tests for mocking.
     */
    _worldToScreen(pos) {
        if (!this._mapState || !this._mapState.map) return { x: 0, y: 0 };

        const map = this._mapState.map;
        const container = map.getContainer();
        if (!container) return { x: 0, y: 0 };

        // If position has lat/lng, use those directly; otherwise fall back
        // to pos.x/pos.y (game meters) which need geo-reference conversion.
        // The units array from TritiumStore includes both lat/lng and position.
        let screenPt;
        if (pos.lng !== undefined && pos.lat !== undefined) {
            screenPt = map.project([pos.lng, pos.lat]);
        } else {
            // Fallback: treat x/y as game-meter offsets from geo center
            const center = this._mapState.geoCenter;
            if (!center) return { x: pos.x, y: pos.y };
            // Convert meters to approximate lat/lng offset
            const mPerDegLat = 111320;
            const mPerDegLng = 111320 * Math.cos(center.lat * Math.PI / 180);
            const lng = center.lng + pos.x / mPerDegLng;
            const lat = center.lat + pos.y / mPerDegLat;
            screenPt = map.project([lng, lat]);
        }

        // Scale screen pixels to fog canvas (1024x1024)
        const cw = container.clientWidth || 1;
        const ch = container.clientHeight || 1;
        const canvasW = this._fogCanvas ? this._fogCanvas.width : 1024;
        const canvasH = this._fogCanvas ? this._fogCanvas.height : 1024;

        return {
            x: (screenPt.x / cw) * canvasW,
            y: (screenPt.y / ch) * canvasH,
        };
    }

    /**
     * Convert meters to pixels at current zoom level.
     * Uses the Web Mercator meters-per-pixel formula:
     *   pixelsPerMeter = 256 * 2^zoom / (40075016.686 * cos(lat))
     * Then scales to the fog canvas dimensions.
     * Override in tests for mocking.
     */
    _metersToPixels(meters) {
        if (!this._mapState || !this._mapState.map) return meters;

        const map = this._mapState.map;
        const zoom = map.getZoom();
        const center = map.getCenter();
        const lat = center.lat;

        // Meters per pixel at this zoom/lat in screen space
        const earthCircumference = 40075016.686;
        const metersPerPixel = earthCircumference * Math.cos(lat * Math.PI / 180) / (256 * Math.pow(2, zoom));
        const screenPixels = meters / metersPerPixel;

        // Scale from screen pixels to fog canvas pixels
        const container = map.getContainer();
        const cw = (container && container.clientWidth) || 1;
        const canvasW = this._fogCanvas ? this._fogCanvas.width : 1024;

        return screenPixels * (canvasW / cw);
    }

    /**
     * Draw the fog overlay on the offscreen canvas.
     * @param {CanvasRenderingContext2D} ctx
     * @param {number} width
     * @param {number} height
     * @param {Array} units
     */
    _drawFog(ctx, width, height, units) {
        // 1. Fill entire canvas with dark fog
        ctx.fillStyle = 'rgba(5, 5, 15, 0.45)';
        ctx.fillRect(0, 0, width, height);

        // 2. Cut out vision areas with destination-out compositing
        ctx.globalCompositeOperation = 'destination-out';
        ctx.fillStyle = 'rgba(255, 255, 255, 1.0)';

        for (const unit of units) {
            if (unit.alliance !== 'friendly') continue;
            const profile = getVisionProfile(unit.asset_type || unit.type);
            const screenPos = this._worldToScreen(unit.position);

            // Always draw ambient radius circle
            ctx.beginPath();
            ctx.arc(screenPos.x, screenPos.y, this._metersToPixels(profile.ambient || 10), 0, Math.PI * 2);
            ctx.fill();

            if (profile.coneRange > 0) {
                // Draw cone sector
                const heading = unit.heading || 0;
                const sweepAngle = profile.coneSweeps
                    ? (this._sweepAngles.get(unit.target_id) || heading)
                    : heading;
                // Convert heading (0=north CW) to canvas angle (0=east CCW)
                const canvasAngle = -(sweepAngle - 90) * Math.PI / 180;
                const halfCone = (profile.coneAngle / 2) * Math.PI / 180;

                ctx.beginPath();
                ctx.moveTo(screenPos.x, screenPos.y);
                ctx.arc(screenPos.x, screenPos.y,
                    this._metersToPixels(profile.coneRange),
                    canvasAngle - halfCone, canvasAngle + halfCone);
                ctx.closePath();
                ctx.fill();
            } else {
                // Omni vision -- full circle
                ctx.beginPath();
                ctx.arc(screenPos.x, screenPos.y, this._metersToPixels(unit.vision_radius || 25), 0, Math.PI * 2);
                ctx.fill();
            }
        }

        // 3. Redraw buildings as fog (they block vision inside cones)
        ctx.globalCompositeOperation = 'source-over';
        ctx.fillStyle = 'rgba(5, 5, 15, 0.45)';
        for (const b of this._buildings) {
            if (!b.points || b.points.length < 3) continue;
            const pts = b.points.map(p => this._worldToScreen({ x: p[0], y: p[1] }));
            ctx.beginPath();
            ctx.moveTo(pts[0].x, pts[0].y);
            for (let i = 1; i < pts.length; i++) {
                ctx.lineTo(pts[i].x, pts[i].y);
            }
            ctx.closePath();
            ctx.fill();
        }

        ctx.globalCompositeOperation = 'source-over';
    }

    /**
     * Draw vision cone edge outlines (neon cyan).
     * @param {CanvasRenderingContext2D} ctx
     * @param {Array} units
     */
    _drawConeEdges(ctx, units) {
        ctx.strokeStyle = '#00f0ff';
        ctx.lineWidth = 2;
        ctx.shadowColor = '#00f0ff';
        ctx.shadowBlur = 8;

        for (const unit of units) {
            if (unit.alliance !== 'friendly') continue;
            const profile = getVisionProfile(unit.asset_type || unit.type);
            if (profile.coneRange <= 0) continue;

            const screenPos = this._worldToScreen(unit.position);
            const heading = profile.coneSweeps
                ? (this._sweepAngles.get(unit.target_id) || unit.heading || 0)
                : (unit.heading || 0);
            const canvasAngle = -(heading - 90) * Math.PI / 180;
            const halfCone = (profile.coneAngle / 2) * Math.PI / 180;
            const r = this._metersToPixels(profile.coneRange);

            ctx.beginPath();
            ctx.moveTo(screenPos.x, screenPos.y);
            ctx.arc(screenPos.x, screenPos.y, r, canvasAngle - halfCone, canvasAngle + halfCone);
            ctx.closePath();
            ctx.stroke();
        }

        ctx.shadowBlur = 0;
    }
}
