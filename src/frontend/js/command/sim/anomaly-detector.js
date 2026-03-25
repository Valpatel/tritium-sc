// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * AnomalyDetector — learns normal city patterns and detects deviations.
 *
 * During a learning period, collects baseline statistics:
 * - Vehicle density per road segment per hour
 * - Average speed per road segment
 * - Typical travel times between intersections
 * - Pedestrian flow rates by zone
 *
 * After baseline established, flags anomalies:
 * - Vehicle circling (same area N times)
 * - Speed violations (too fast or too slow for road)
 * - Stopped vehicle (not moving for > threshold)
 * - Unusual location for time of day
 */

/**
 * @typedef {Object} Anomaly
 * @property {string} id — anomaly ID
 * @property {string} entityId — entity that caused it
 * @property {string} type — 'circling'|'speed'|'stopped'|'location'|'route'
 * @property {string} description — human-readable
 * @property {number} confidence — 0-1
 * @property {number} x — position
 * @property {number} z — position
 * @property {number} timestamp — when detected
 */

let _anomalyId = 0;

/**
 * MarkovRoutePredictor — builds a transition probability matrix between
 * road junctions from observed vehicle routes. Flags low-probability
 * transitions as route anomalies.
 */
class MarkovRoutePredictor {
    constructor() {
        this._transitions = new Map(); // "fromNodeId" -> Map<"toNodeId", count>
        this._totalFromNode = new Map(); // "fromNodeId" -> total transitions
    }

    observe(fromNodeId, toNodeId) {
        if (!this._transitions.has(fromNodeId))
            this._transitions.set(fromNodeId, new Map());
        const t = this._transitions.get(fromNodeId);
        t.set(toNodeId, (t.get(toNodeId) || 0) + 1);
        this._totalFromNode.set(fromNodeId, (this._totalFromNode.get(fromNodeId) || 0) + 1);
    }

    probability(fromNodeId, toNodeId) {
        const total = this._totalFromNode.get(fromNodeId) || 0;
        if (total === 0) return 1.0; // unknown = assume normal
        const count = this._transitions.get(fromNodeId)?.get(toNodeId) || 0;
        return count / total;
    }

    isAnomaly(fromNodeId, toNodeId, threshold = 0.05) {
        return this.probability(fromNodeId, toNodeId) < threshold;
    }

    get nodeCount() { return this._totalFromNode.size; }
}

/**
 * Welford's online algorithm for streaming mean/variance.
 * O(1) memory per metric. Detects 3-sigma deviations.
 */
class StreamingStat {
    constructor() { this.n = 0; this.mean = 0; this.m2 = 0; }
    push(x) {
        this.n++;
        const delta = x - this.mean;
        this.mean += delta / this.n;
        this.m2 += delta * (x - this.mean);
    }
    get variance() { return this.n > 1 ? this.m2 / (this.n - 1) : 0; }
    get stddev() { return Math.sqrt(this.variance); }
    zScore(x) { const s = this.stddev; return s > 0 ? (x - this.mean) / s : 0; }
}

export class AnomalyDetector {
    constructor() {
        // Baseline data collection
        this._roadDensity = new Map();      // edgeId → { counts: number[], avgSpeed: number[] }
        this._entityPositionHistory = new Map(); // entityId → [{x, z, t}, ...]
        this._baselineReady = false;
        this._baselineTime = 0;
        this._baselineDuration = 300;       // 5 minutes of sim time to establish baseline

        // Z-Score streaming stats per edge
        this._edgeSpeedStats = new Map();   // edgeId → StreamingStat

        // Markov route prediction
        this._routePredictor = new MarkovRoutePredictor();

        // Detection state
        this.anomalies = [];                // active anomalies
        this._maxAnomalies = 50;
        this._stoppedThreshold = 30;        // seconds before flagging stopped vehicle
        this._circlingThreshold = 3;        // visits to same area before flagging

        // Stats
        this.totalDetections = 0;
        this.enabled = true;
    }

    /**
     * Update detector with current entity states.
     * @param {number} dt — delta time
     * @param {number} simHour — current sim hour
     * @param {Array} vehicles
     * @param {Array} pedestrians
     * @param {Object} roadNetwork — for road segment lookup
     * @returns {Array<Anomaly>} newly detected anomalies
     */
    tick(dt, simHour, vehicles, pedestrians, roadNetwork) {
        if (!this.enabled) return [];

        this._baselineTime += dt;
        const newAnomalies = [];

        // Record position history for all entities
        const now = Date.now();
        for (const v of vehicles) {
            if (!this._entityPositionHistory.has(v.id)) {
                this._entityPositionHistory.set(v.id, []);
            }
            const history = this._entityPositionHistory.get(v.id);
            history.push({ x: v.x, z: v.z, t: now, speed: v.speed });

            // Keep only last 60 seconds of history AND cap array length to prevent unbounded growth
            while (history.length > 7200) {  // ~2 min at 60fps, hard cap
                history.shift();
            }
            while (history.length > 0 && now - history[0].t > 60000) {  // 60s time window
                history.shift();
            }
        }

        // Baseline collection phase
        if (!this._baselineReady) {
            if (this._baselineTime >= this._baselineDuration) {
                this._baselineReady = true;
                // Finalize averages and clear stale accumulated counts
                for (const [key, rd] of this._roadDensity) {
                    rd.avgSpeed = rd.samples > 0 ? rd.totalSpeed / rd.samples : 0;
                }
                console.log(`[AnomalyDetector] Baseline established after ${this._baselineDuration}s`);
            }
            // Collect Markov route transitions during baseline
            for (const v of vehicles) {
                if (v._pendingTransition) {
                    this._routePredictor.observe(v._pendingTransition.from, v._pendingTransition.to);
                    v._pendingTransition = null;
                }
            }
            // Collect road density data + feed streaming stats
            for (const v of vehicles) {
                if (v.edge && !v.parked) {
                    const key = v.edge.id;
                    if (!this._roadDensity.has(key)) {
                        this._roadDensity.set(key, { counts: 0, totalSpeed: 0, samples: 0 });
                    }
                    const rd = this._roadDensity.get(key);
                    rd.counts++;
                    rd.totalSpeed += v.speed;
                    rd.samples++;

                    // Feed Z-Score streaming stats
                    if (!this._edgeSpeedStats.has(key)) {
                        this._edgeSpeedStats.set(key, new StreamingStat());
                    }
                    this._edgeSpeedStats.get(key).push(v.speed);
                }
            }
            return [];
        }

        // Detection phase — check each vehicle for anomalies

        // 1. Stopped vehicle detection (skip parked vehicles — those are intentional)
        for (const v of vehicles) {
            if (v.parked) continue;
            const history = this._entityPositionHistory.get(v.id);
            if (!history || history.length < 10) continue;

            // Check if vehicle hasn't moved significantly in last 30 seconds
            const recent = history.filter(h => now - h.t < this._stoppedThreshold * 1000);
            if (recent.length >= 5) {
                const dx = recent[recent.length - 1].x - recent[0].x;
                const dz = recent[recent.length - 1].z - recent[0].z;
                const dist = Math.sqrt(dx * dx + dz * dz);

                if (dist < 2 && v.speed < 0.5) {
                    // Vehicle stopped — check if it's at an intersection (normal) or mid-road (anomaly)
                    const nearestNode = roadNetwork?.nearestNode(v.x, v.z);
                    if (!nearestNode || nearestNode.dist > 15) {
                        // Not near intersection — suspicious
                        newAnomalies.push(this._createAnomaly(
                            v.id, 'stopped',
                            `Vehicle ${v.id} stopped for ${this._stoppedThreshold}s at mid-road`,
                            0.7, v.x, v.z
                        ));
                    }
                }
            }
        }

        // 2. Circling detection
        for (const v of vehicles) {
            const history = this._entityPositionHistory.get(v.id);
            if (!history || history.length < 20) continue;

            // Divide area into 50m grid cells, count visits
            const cellVisits = new Map();
            for (const h of history) {
                const cellKey = `${Math.floor(h.x / 50)},${Math.floor(h.z / 50)}`;
                cellVisits.set(cellKey, (cellVisits.get(cellKey) || 0) + 1);
            }

            // Check for any cell visited too many times
            for (const [cellKey, count] of cellVisits) {
                if (count >= this._circlingThreshold * 10) { // 10 samples per visit
                    // Already flagged this entity+cell?
                    const anomId = `circle_${v.id}_${cellKey}`;
                    if (!this.anomalies.some(a => a.id === anomId)) {
                        const [cx, cz] = cellKey.split(',').map(n => (parseInt(n) + 0.5) * 50);
                        newAnomalies.push(this._createAnomaly(
                            v.id, 'circling',
                            `Vehicle ${v.id} circling area (${count} visits to same zone)`,
                            Math.min(0.95, 0.5 + count * 0.05),
                            cx, cz,
                            anomId
                        ));
                    }
                }
            }
        }

        // 3. Speed anomaly — Z-Score based (3-sigma, dedup per vehicle per edge)
        for (const v of vehicles) {
            if (!v.edge || v.parked) continue;
            const edgeStats = this._edgeSpeedStats.get(v.edge.id);
            if (!edgeStats || edgeStats.n < 20) continue;

            const z = edgeStats.zScore(v.speed);
            if (Math.abs(z) > 3.0) {
                const speedAnomalyId = `speed_${v.id}_${v.edge.id}`;
                if (!this.anomalies.some(a => a.id === speedAnomalyId)) {
                    const dir = z > 0 ? 'fast' : 'slow';
                    newAnomalies.push(this._createAnomaly(
                        v.id, 'speed',
                        `Vehicle ${v.id} ${dir}: ${(v.speed * 3.6).toFixed(0)} km/h (mean: ${(edgeStats.mean * 3.6).toFixed(0)}, z=${z.toFixed(1)})`,
                        Math.min(0.95, 0.5 + Math.abs(z) * 0.1),
                        v.x, v.z,
                        speedAnomalyId
                    ));
                }
            }
        }

        // 4. Route anomaly — Markov chain (low-probability junction transition)
        for (const v of vehicles) {
            if (v._pendingTransition) {
                const { from, to } = v._pendingTransition;
                // Still observe during detection to keep the model learning
                this._routePredictor.observe(from, to);
                if (this._routePredictor.isAnomaly(from, to)) {
                    const prob = this._routePredictor.probability(from, to);
                    const routeAnomalyId = `route_${v.id}_${from}_${to}`;
                    if (!this.anomalies.some(a => a.id === routeAnomalyId)) {
                        newAnomalies.push(this._createAnomaly(
                            v.id, 'route',
                            `Vehicle ${v.id} unusual route: ${from}→${to} (p=${(prob * 100).toFixed(1)}%)`,
                            Math.min(0.95, 0.8 - prob * 5),
                            v.x, v.z,
                            routeAnomalyId
                        ));
                    }
                }
                v._pendingTransition = null;
            }
        }

        // Add new anomalies, cap total
        for (const a of newAnomalies) {
            this.anomalies.push(a);
            this.totalDetections++;
        }
        while (this.anomalies.length > this._maxAnomalies) {
            this.anomalies.shift();
        }

        return newAnomalies;
    }

    _createAnomaly(entityId, type, description, confidence, x, z, customId) {
        return {
            id: customId || `anomaly_${_anomalyId++}`,
            entityId,
            type,
            description,
            confidence: Math.round(confidence * 100) / 100,
            x, z,
            timestamp: Date.now(),
        };
    }

    /**
     * Inject an anomalous behavior for testing.
     * @param {string} type — 'circling'|'stopped'|'speed'
     * @param {Object} entity — vehicle or pedestrian to make anomalous
     */
    injectAnomaly(type, entity) {
        if (type === 'stopped') {
            entity.speed = 0;
            entity.acc = 0;
        }
        // Other types would need route manipulation
    }

    /**
     * Get detection stats.
     */
    getStats() {
        return {
            baselineReady: this._baselineReady,
            baselineProgress: Math.min(1, this._baselineTime / this._baselineDuration),
            activeAnomalies: this.anomalies.length,
            totalDetections: this.totalDetections,
            roadSegmentsTracked: this._roadDensity.size,
            entitiesTracked: this._entityPositionHistory.size,
            routeNodesTracked: this._routePredictor.nodeCount,
        };
    }

    /**
     * Reset all state.
     */
    reset() {
        this._roadDensity.clear();
        this._entityPositionHistory.clear();
        this._edgeSpeedStats.clear();
        this._routePredictor = new MarkovRoutePredictor();
        this._baselineReady = false;
        this._baselineTime = 0;
        this.anomalies = [];
        this.totalDetections = 0;
    }
}
