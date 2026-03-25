#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * City Simulation STRESS TEST — performance validation.
 *
 * Proves the sim can handle 500+ vehicles with physics tick < 16ms.
 * Tests: IDM physics scaling, spatial grid efficiency, pathfinding throughput,
 * anomaly detection overhead, and memory footprint.
 *
 * All simulation classes are inlined (no Three.js dependency).
 */

let passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; console.log(`  PASS: ${msg}`); }
    else { failed++; console.log(`  FAIL: ${msg}`); }
}

// ============================================================
// INLINED CORE: IDM
// ============================================================

const IDM_DEFAULTS = { v0: 12, a: 1.4, b: 2.0, s0: 2.0, T: 1.5, delta: 4 };

function idmAcceleration(v, s, vLeader, params = IDM_DEFAULTS) {
    const { v0, a, b, s0, T, delta } = params;
    const deltaV = v - vLeader;
    const interaction = (v * deltaV) / (2 * Math.sqrt(a * b));
    const sStar = s0 + Math.max(0, v * T + interaction);
    const vRatio = (v0 > 0) ? Math.pow(v / v0, delta) : 0;
    const sRatio = (s > 0.01) ? Math.pow(sStar / s, 2) : 100;
    const acc = a * (1 - vRatio - sRatio);
    return Math.max(-9.0, Math.min(a, acc));
}

function ballisticUpdate(u, v, acc, dt) {
    const newU = u + Math.max(0, v * dt + 0.5 * acc * dt * dt);
    const newV = Math.max(0, v + acc * dt);
    return { u: newU, v: newV };
}

// ============================================================
// INLINED CORE: ROAD NETWORK (with 5x5 grid builder)
// ============================================================

class TestRoadNetwork {
    constructor() {
        this.nodes = {};
        this.edges = [];
        this.adjList = {};
        this.edgeById = {};
    }

    addNode(id, x, z, approaches = [], col = 0, row = 0) {
        this.nodes[id] = { id, x, z, approaches, col, row };
        if (!this.adjList[id]) this.adjList[id] = [];
    }

    addEdge(id, fromId, toId, length, horizontal = true) {
        const fromNode = this.nodes[fromId];
        const toNode = this.nodes[toId];
        const edge = {
            id, from: fromId, to: toId, horizontal,
            ax: fromNode.x, az: fromNode.z,
            bx: toNode.x, bz: toNode.z,
            length,
            numLanesPerDir: 2,
            laneWidth: 3,
        };
        const idx = this.edges.length;
        this.edges.push(edge);
        this.edgeById[id] = edge;
        this.adjList[fromId].push(idx);
        this.adjList[toId].push(idx);
        return edge;
    }

    buildGrid(cols, rows, blockSize) {
        // Create intersection nodes
        for (let r = 0; r <= rows; r++) {
            for (let c = 0; c <= cols; c++) {
                const id = `${c}_${r}`;
                const approaches = [];
                if (r > 0) approaches.push('N');
                if (r < rows) approaches.push('S');
                if (c > 0) approaches.push('W');
                if (c < cols) approaches.push('E');
                this.addNode(id, c * blockSize, r * blockSize, approaches, c, r);
            }
        }
        // Horizontal edges
        for (let r = 0; r <= rows; r++) {
            for (let c = 0; c < cols; c++) {
                this.addEdge(`h_${c}_${r}`, `${c}_${r}`, `${c + 1}_${r}`, blockSize, true);
            }
        }
        // Vertical edges
        for (let c = 0; c <= cols; c++) {
            for (let r = 0; r < rows; r++) {
                this.addEdge(`v_${c}_${r}`, `${c}_${r}`, `${c}_${r + 1}`, blockSize, false);
            }
        }
        return this;
    }

    findPath(fromNodeId, toNodeId) {
        if (fromNodeId === toNodeId) return [];
        const dist = {};
        const prev = {};
        const visited = new Set();
        const queue = [];
        for (const id in this.nodes) dist[id] = Infinity;
        dist[fromNodeId] = 0;
        queue.push({ id: fromNodeId, dist: 0 });
        while (queue.length > 0) {
            queue.sort((a, b) => a.dist - b.dist);
            const { id: current } = queue.shift();
            if (current === toNodeId) break;
            if (visited.has(current)) continue;
            visited.add(current);
            for (const edgeIdx of this.adjList[current]) {
                const edge = this.edges[edgeIdx];
                const neighbor = edge.from === current ? edge.to : edge.from;
                const newDist = dist[current] + edge.length;
                if (newDist < dist[neighbor]) {
                    dist[neighbor] = newDist;
                    prev[neighbor] = { nodeId: current, edgeIdx };
                    queue.push({ id: neighbor, dist: newDist });
                }
            }
        }
        if (dist[toNodeId] === Infinity) return [];
        const path = [];
        let current = toNodeId;
        while (current !== fromNodeId) {
            const { nodeId: prevNode, edgeIdx } = prev[current];
            path.unshift({ edge: this.edges[edgeIdx], nodeId: current });
            current = prevNode;
        }
        return path;
    }

    getEdgesForNode(nodeId) {
        return (this.adjList[nodeId] || []).map(idx => this.edges[idx]);
    }

    getRandomNodeId() {
        const ids = Object.keys(this.nodes);
        return ids[Math.floor(Math.random() * ids.length)];
    }
}

// ============================================================
// INLINED CORE: SPATIAL GRID
// ============================================================

class SpatialGrid {
    constructor(cellSize = 20) {
        this.cellSize = cellSize;
        this._cells = new Map();
        this._entityCell = new Map();
    }

    clear() {
        this._cells.clear();
        this._entityCell.clear();
    }

    insert(entity) {
        const key = `${Math.floor(entity.x / this.cellSize)},${Math.floor(entity.z / this.cellSize)}`;
        if (!this._cells.has(key)) this._cells.set(key, new Set());
        this._cells.get(key).add(entity);
        this._entityCell.set(entity.id, key);
    }

    getNearby(x, z) {
        const cx = Math.floor(x / this.cellSize);
        const cz = Math.floor(z / this.cellSize);
        const result = [];
        for (let dx = -1; dx <= 1; dx++) {
            for (let dz = -1; dz <= 1; dz++) {
                const cell = this._cells.get(`${cx + dx},${cz + dz}`);
                if (cell) for (const e of cell) result.push(e);
            }
        }
        return result;
    }

    stats() {
        let maxCellSize = 0, totalEntities = 0;
        for (const [, cell] of this._cells) {
            maxCellSize = Math.max(maxCellSize, cell.size);
            totalEntities += cell.size;
        }
        return {
            cells: this._cells.size,
            entities: totalEntities,
            maxCellSize,
            avgCellSize: this._cells.size > 0 ? Math.round(totalEntities / this._cells.size * 10) / 10 : 0,
        };
    }
}

// ============================================================
// INLINED CORE: TRAFFIC CONTROLLER
// ============================================================

function buildSignalPhases(approaches) {
    const phases = [];
    if (approaches.length === 4) {
        phases.push({ greenApproaches: ['N', 'S'], duration: 15, type: 'green' });
        phases.push({ greenApproaches: ['N', 'S'], duration: 2, type: 'yellow' });
        phases.push({ greenApproaches: [], duration: 1, type: 'allRed' });
        phases.push({ greenApproaches: ['E', 'W'], duration: 15, type: 'green' });
        phases.push({ greenApproaches: ['E', 'W'], duration: 2, type: 'yellow' });
        phases.push({ greenApproaches: [], duration: 1, type: 'allRed' });
    }
    return phases;
}

class TestTrafficController {
    constructor(node, roadNetwork) {
        this.nodeId = node.id;
        this.node = node;
        this.roadNetwork = roadNetwork;
        this.phases = buildSignalPhases(node.approaches);
        this.currentPhase = 0;
        this.phaseTimer = ((node.col * 7 + node.row * 13) % 17) * 2;
    }
    getCurrentPhase() { return this.phases[this.currentPhase]; }
    isGreen(dir) {
        const phase = this.getCurrentPhase();
        return phase && phase.type === 'green' && phase.greenApproaches.includes(dir);
    }
    tick(dt) {
        if (!this.phases.length) return;
        this.phaseTimer += dt;
        const phase = this.getCurrentPhase();
        if (this.phaseTimer >= phase.duration) {
            this.phaseTimer -= phase.duration;
            this.currentPhase = (this.currentPhase + 1) % this.phases.length;
        }
    }
    buildVirtualObstacles() {
        const obstacles = [];
        const edges = this.roadNetwork.getEdgesForNode(this.nodeId);
        for (const edge of edges) {
            const n = edge.numLanesPerDir || 2;
            if (edge.to === this.nodeId) {
                const arrivalDir = edge.horizontal ? 'W' : 'N';
                if (!this.isGreen(arrivalDir)) {
                    for (let lane = 0; lane < n; lane++) {
                        obstacles.push({
                            id: `virt_${this.nodeId}_${arrivalDir}_${lane}`,
                            road: edge, lane, u: edge.length - 2,
                            speed: 0, length: 1, isVirtual: true,
                        });
                    }
                }
            }
            if (edge.from === this.nodeId) {
                const arrivalDir = edge.horizontal ? 'E' : 'S';
                if (!this.isGreen(arrivalDir)) {
                    for (let lane = n; lane < 2 * n; lane++) {
                        obstacles.push({
                            id: `virt_${this.nodeId}_${arrivalDir}_${lane}`,
                            road: edge, lane, u: edge.length - 2,
                            speed: 0, length: 1, isVirtual: true,
                        });
                    }
                }
            }
        }
        return obstacles;
    }
}

class TrafficControllerManager {
    constructor() { this.controllers = {}; }
    initFromNetwork(rn) {
        this.controllers = {};
        for (const nodeId in rn.nodes) {
            const node = rn.nodes[nodeId];
            if (node.approaches.length >= 4) {
                this.controllers[nodeId] = new TestTrafficController(node, rn);
            }
        }
    }
    tick(dt) {
        for (const id in this.controllers) this.controllers[id].tick(dt);
    }
    getAllVirtualObstacles() {
        const all = [];
        for (const id in this.controllers) {
            all.push(...this.controllers[id].buildVirtualObstacles());
        }
        return all;
    }
}

// ============================================================
// INLINED CORE: ANOMALY DETECTOR (simplified)
// ============================================================

class StreamingStat {
    constructor() { this.n = 0; this.mean = 0; this.m2 = 0; }
    push(x) {
        this.n++;
        const delta = x - this.mean;
        this.mean += delta / this.n;
        this.m2 += delta * (x - this.mean);
    }
    get stddev() { return this.n > 1 ? Math.sqrt(this.m2 / (this.n - 1)) : 0; }
    zScore(x) { const s = this.stddev; return s > 0 ? (x - this.mean) / s : 0; }
}

class TestAnomalyDetector {
    constructor() {
        this._edgeSpeedStats = new Map();
        this._entityPositionHistory = new Map();
        this._baselineReady = false;
        this._baselineTime = 0;
        this._baselineDuration = 300;
        this.anomalies = [];
        this.totalDetections = 0;
    }

    tick(dt, vehicles) {
        this._baselineTime += dt;
        const now = Date.now();

        // Record positions
        for (const v of vehicles) {
            if (!this._entityPositionHistory.has(v.id)) {
                this._entityPositionHistory.set(v.id, []);
            }
            const hist = this._entityPositionHistory.get(v.id);
            hist.push({ x: v.x, z: v.z, t: now, speed: v.speed });
            while (hist.length > 120) hist.shift();
        }

        // Baseline collection
        if (!this._baselineReady) {
            for (const v of vehicles) {
                if (v.edge) {
                    const key = v.edge.id;
                    if (!this._edgeSpeedStats.has(key))
                        this._edgeSpeedStats.set(key, new StreamingStat());
                    this._edgeSpeedStats.get(key).push(v.speed);
                }
            }
            if (this._baselineTime >= this._baselineDuration) {
                this._baselineReady = true;
            }
            return [];
        }

        // Detection phase: speed anomalies
        const newAnomalies = [];
        for (const v of vehicles) {
            if (!v.edge) continue;
            const stats = this._edgeSpeedStats.get(v.edge.id);
            if (!stats || stats.n < 20) continue;
            const z = stats.zScore(v.speed);
            if (Math.abs(z) > 3.0) {
                newAnomalies.push({
                    id: `speed_${v.id}_${v.edge.id}`,
                    entityId: v.id, type: 'speed',
                    confidence: Math.min(0.95, 0.5 + Math.abs(z) * 0.1),
                    x: v.x, z: v.z,
                });
                this.totalDetections++;
            }
        }
        this.anomalies.push(...newAnomalies);
        while (this.anomalies.length > 50) this.anomalies.shift();
        return newAnomalies;
    }

    injectAnomaly(vehicle) {
        vehicle.speed = vehicle.idm.v0 * 3; // 3x desired speed = obvious outlier
    }
}

// ============================================================
// INLINED CORE: STRESS VEHICLE
// ============================================================

let _nextVehicleId = 0;

class StressVehicle {
    constructor(edge, u, roadNetwork) {
        this.id = `car_${_nextVehicleId++}`;
        this.edge = edge;
        this.u = u;
        this.speed = 2 + Math.random() * 6;
        this.acc = 0;
        this.x = 0;
        this.z = 0;
        this.alive = true;
        this.lane = Math.floor(Math.random() * (edge.numLanesPerDir || 2));
        this.length = 4;
        this.idm = { ...IDM_DEFAULTS };
        this.roadNetwork = roadNetwork;
        this.direction = Math.random() < 0.5 ? 1 : -1;
        this._updatePosition();
    }

    _updatePosition() {
        const t = Math.max(0, Math.min(1, this.u / this.edge.length));
        this.x = this.edge.ax + t * (this.edge.bx - this.edge.ax);
        this.z = this.edge.az + t * (this.edge.bz - this.edge.az);
    }

    tick(dt, nearbyVehicles) {
        if (!this.alive) return;

        // Find leader on same edge + lane
        let bestGap = Infinity;
        let leaderSpeed = this.speed;
        const isForward = this.direction === 1;

        for (const other of nearbyVehicles) {
            if (other === this || other.edge !== this.edge || other.lane !== this.lane) continue;
            let gap;
            if (isForward) {
                gap = other.u - this.u;
            } else {
                gap = this.u - other.u;
            }
            if (gap > 0 && gap < bestGap) {
                bestGap = gap - this.length - (other.length || 4);
                leaderSpeed = other.speed;
            }
        }
        bestGap = Math.max(0.1, bestGap);

        // IDM acceleration
        this.acc = idmAcceleration(this.speed, bestGap, leaderSpeed, this.idm);

        // Ballistic update
        const result = ballisticUpdate(this.u, this.speed, this.acc, dt);
        this.u = result.u;
        this.speed = result.v;

        // Wrap at edge boundaries (simple: loop back)
        if (this.u >= this.edge.length) {
            // Pick a random connected edge
            const nodeId = this.direction === 1 ? this.edge.to : this.edge.from;
            const connectedEdges = this.roadNetwork.getEdgesForNode(nodeId);
            if (connectedEdges.length > 0) {
                const newEdge = connectedEdges[Math.floor(Math.random() * connectedEdges.length)];
                this.edge = newEdge;
                this.u = 1;
                this.lane = Math.floor(Math.random() * (newEdge.numLanesPerDir || 2));
                this.direction = Math.random() < 0.5 ? 1 : -1;
            } else {
                this.u = 1;
                this.direction *= -1;
            }
        } else if (this.u < 0) {
            this.u = 1;
            this.direction *= -1;
        }

        this._updatePosition();
    }
}

// ============================================================
// TEST HARNESS
// ============================================================

function buildTestNetwork() {
    const rn = new TestRoadNetwork();
    rn.buildGrid(5, 5, 100); // 5x5 grid, 100m edges
    return rn;
}

function spawnVehicles(count, roadNetwork) {
    const vehicles = [];
    const edges = roadNetwork.edges;
    for (let i = 0; i < count; i++) {
        const edge = edges[Math.floor(Math.random() * edges.length)];
        const u = 5 + Math.random() * (edge.length - 10);
        vehicles.push(new StressVehicle(edge, u, roadNetwork));
    }
    return vehicles;
}

function runTicks(vehicles, grid, trafficMgr, numTicks, dt) {
    const times = [];

    for (let t = 0; t < numTicks; t++) {
        const start = performance.now();

        // Rebuild spatial grid
        grid.clear();
        for (const v of vehicles) grid.insert(v);

        // Tick traffic controllers
        trafficMgr.tick(dt);

        // Get virtual obstacles (not used in vehicle tick for simplicity,
        // but measure the cost)
        trafficMgr.getAllVirtualObstacles();

        // Tick each vehicle with nearby lookup
        for (const v of vehicles) {
            const nearby = grid.getNearby(v.x, v.z);
            v.tick(dt, nearby);
        }

        const elapsed = performance.now() - start;
        times.push(elapsed);
    }

    return {
        min: Math.min(...times),
        max: Math.max(...times),
        avg: times.reduce((a, b) => a + b, 0) / times.length,
        p95: times.sort((a, b) => a - b)[Math.floor(times.length * 0.95)],
        p99: times.sort((a, b) => a - b)[Math.floor(times.length * 0.99)],
    };
}

// ============================================================
// TEST 1: VEHICLE SCALING — tick time vs vehicle count
// ============================================================

console.log('');
console.log('================================================================');
console.log('  CITY SIM STRESS TEST — Performance Validation');
console.log('================================================================');
console.log('');

const roadNetwork = buildTestNetwork();
const nodeIds = Object.keys(roadNetwork.nodes);
const edgeCount = roadNetwork.edges.length;

console.log(`Road network: ${nodeIds.length} nodes, ${edgeCount} edges, 100m segments`);
console.log('');

console.log('--- Test 1: Vehicle Scaling ---');

const grid = new SpatialGrid(20);
const trafficMgr = new TrafficControllerManager();
trafficMgr.initFromNetwork(roadNetwork);

const controllerCount = Object.keys(trafficMgr.controllers).length;
console.log(`Traffic controllers: ${controllerCount} (4-way intersections)`);
console.log('');

const batches = [
    { count: 50,   budgetMs: 2 },
    { count: 100,  budgetMs: 4 },
    { count: 200,  budgetMs: 8 },
    { count: 500,  budgetMs: 16 },
    { count: 1000, budgetMs: null }, // report only
];

const dt = 0.1; // 100ms timestep
const numTicks = 100;
const results = {};

for (const batch of batches) {
    _nextVehicleId = 0; // reset IDs
    const vehicles = spawnVehicles(batch.count, roadNetwork);

    // Warmup: 10 ticks
    for (let w = 0; w < 10; w++) {
        grid.clear();
        for (const v of vehicles) grid.insert(v);
        trafficMgr.tick(dt);
        for (const v of vehicles) {
            const nearby = grid.getNearby(v.x, v.z);
            v.tick(dt, nearby);
        }
    }

    const perf = runTicks(vehicles, grid, trafficMgr, numTicks, dt);
    results[batch.count] = perf;

    // Verify no NaN positions
    let nanCount = 0;
    for (const v of vehicles) {
        if (isNaN(v.x) || isNaN(v.z) || isNaN(v.speed) || isNaN(v.u)) nanCount++;
    }

    // Spatial grid stats after final tick
    grid.clear();
    for (const v of vehicles) grid.insert(v);
    const gridStats = grid.stats();

    console.log(`  ${batch.count} vehicles: avg=${perf.avg.toFixed(2)}ms  p95=${perf.p95.toFixed(2)}ms  p99=${perf.p99.toFixed(2)}ms  max=${perf.max.toFixed(2)}ms`);
    console.log(`    Grid: ${gridStats.cells} cells, max_occupancy=${gridStats.maxCellSize}, avg=${gridStats.avgCellSize}`);

    assert(nanCount === 0, `${batch.count} vehicles: no NaN positions (found ${nanCount})`);
    assert(gridStats.entities === batch.count, `${batch.count} vehicles: spatial grid contains all (${gridStats.entities})`);

    if (batch.budgetMs !== null) {
        assert(perf.avg < batch.budgetMs,
            `${batch.count} vehicles: avg tick ${perf.avg.toFixed(2)}ms < ${batch.budgetMs}ms budget`);
    } else {
        console.log(`    (1000-vehicle budget: REPORT ONLY — avg=${perf.avg.toFixed(2)}ms)`);
    }
}

// ============================================================
// TEST 2: MEMORY FOOTPRINT
// ============================================================

console.log('');
console.log('--- Test 2: Memory Footprint ---');

if (typeof process !== 'undefined' && process.memoryUsage) {
    // Force GC if available
    if (global.gc) global.gc();
    const memBefore = process.memoryUsage();

    _nextVehicleId = 0;
    const bigFleet = spawnVehicles(1000, roadNetwork);
    const bigGrid = new SpatialGrid(20);

    // Run 50 ticks to let memory stabilize
    for (let t = 0; t < 50; t++) {
        bigGrid.clear();
        for (const v of bigFleet) bigGrid.insert(v);
        for (const v of bigFleet) {
            const nearby = bigGrid.getNearby(v.x, v.z);
            v.tick(dt, nearby);
        }
    }

    if (global.gc) global.gc();
    const memAfter = process.memoryUsage();
    const heapDeltaMB = (memAfter.heapUsed - memBefore.heapUsed) / (1024 * 1024);
    const rssDeltaMB = (memAfter.rss - memBefore.rss) / (1024 * 1024);

    console.log(`  Heap before: ${(memBefore.heapUsed / 1024 / 1024).toFixed(1)}MB`);
    console.log(`  Heap after:  ${(memAfter.heapUsed / 1024 / 1024).toFixed(1)}MB`);
    console.log(`  Heap delta:  ${heapDeltaMB.toFixed(1)}MB for 1000 vehicles`);
    console.log(`  RSS delta:   ${rssDeltaMB.toFixed(1)}MB`);

    // 1000 vehicles should use < 50MB heap
    assert(heapDeltaMB < 50, `Memory: heap delta ${heapDeltaMB.toFixed(1)}MB < 50MB for 1000 vehicles`);
} else {
    console.log('  (process.memoryUsage not available — skipping)');
}

// ============================================================
// TEST 3: PATHFINDING STRESS
// ============================================================

console.log('');
console.log('--- Test 3: Pathfinding Stress ---');

const pathCount = 100;
const pathStart = performance.now();
let totalPathLength = 0;
let emptyPaths = 0;

for (let i = 0; i < pathCount; i++) {
    const from = roadNetwork.getRandomNodeId();
    let to = roadNetwork.getRandomNodeId();
    // Ensure different nodes
    while (to === from) to = roadNetwork.getRandomNodeId();
    const path = roadNetwork.findPath(from, to);
    if (path.length === 0) emptyPaths++;
    totalPathLength += path.length;
}

const pathElapsed = performance.now() - pathStart;
const avgPathLen = totalPathLength / pathCount;

console.log(`  ${pathCount} random paths in ${pathElapsed.toFixed(1)}ms`);
console.log(`  Avg path length: ${avgPathLen.toFixed(1)} edges`);
console.log(`  Empty paths: ${emptyPaths} (same-node or isolated)`);

assert(pathElapsed < 100, `Pathfinding: ${pathCount} paths in ${pathElapsed.toFixed(1)}ms < 100ms`);
assert(emptyPaths === 0, `Pathfinding: all ${pathCount} paths found (${emptyPaths} empty)`);

// ============================================================
// TEST 4: TRAFFIC CONTROLLER OVERHEAD
// ============================================================

console.log('');
console.log('--- Test 4: Traffic Controller Overhead ---');

const tcTicks = 1000;
const tcStart = performance.now();
for (let t = 0; t < tcTicks; t++) {
    trafficMgr.tick(dt);
    trafficMgr.getAllVirtualObstacles();
}
const tcElapsed = performance.now() - tcStart;
const tcPerTick = tcElapsed / tcTicks;

console.log(`  ${tcTicks} controller ticks + virtual obstacles: ${tcElapsed.toFixed(1)}ms total`);
console.log(`  Per tick: ${tcPerTick.toFixed(3)}ms`);

assert(tcPerTick < 1.0, `Traffic controllers: ${tcPerTick.toFixed(3)}ms/tick < 1.0ms`);

// ============================================================
// TEST 5: ANOMALY DETECTOR STRESS
// ============================================================

console.log('');
console.log('--- Test 5: Anomaly Detector Stress ---');

_nextVehicleId = 0;
const anomalyVehicles = spawnVehicles(500, roadNetwork);
const anomalyGrid = new SpatialGrid(20);
const detector = new TestAnomalyDetector();

// Baseline phase: 300s simulated time at dt=1.0 (300 ticks)
const baselineTicks = 300;
const baselineStart = performance.now();
for (let t = 0; t < baselineTicks; t++) {
    anomalyGrid.clear();
    for (const v of anomalyVehicles) anomalyGrid.insert(v);
    for (const v of anomalyVehicles) {
        const nearby = anomalyGrid.getNearby(v.x, v.z);
        v.tick(1.0, nearby);
    }
    detector.tick(1.0, anomalyVehicles);
}
const baselineElapsed = performance.now() - baselineStart;

console.log(`  Baseline (${baselineTicks} ticks, 500 vehicles): ${baselineElapsed.toFixed(0)}ms total`);
assert(detector._baselineReady, 'Anomaly detector: baseline established after 300s');

// Inject anomalies: make 5 vehicles go 3x speed
const injectedCount = 5;
for (let i = 0; i < injectedCount; i++) {
    detector.injectAnomaly(anomalyVehicles[i]);
}

// Detection phase: 50 ticks
const detectTimes = [];
let detectedAnomalies = 0;
for (let t = 0; t < 50; t++) {
    anomalyGrid.clear();
    for (const v of anomalyVehicles) anomalyGrid.insert(v);
    for (const v of anomalyVehicles) {
        const nearby = anomalyGrid.getNearby(v.x, v.z);
        v.tick(1.0, nearby);
    }

    // Re-inject speed anomaly each tick (vehicles keep getting IDM-corrected)
    for (let i = 0; i < injectedCount; i++) {
        detector.injectAnomaly(anomalyVehicles[i]);
    }

    const dStart = performance.now();
    const newAnomalies = detector.tick(1.0, anomalyVehicles);
    detectTimes.push(performance.now() - dStart);
    detectedAnomalies += newAnomalies.length;
}

const avgDetectTime = detectTimes.reduce((a, b) => a + b, 0) / detectTimes.length;
const maxDetectTime = Math.max(...detectTimes);

console.log(`  Detection (50 ticks, 500 vehicles): avg=${avgDetectTime.toFixed(2)}ms, max=${maxDetectTime.toFixed(2)}ms`);
console.log(`  Anomalies detected: ${detectedAnomalies} (injected ${injectedCount} speed anomalies)`);

assert(avgDetectTime < 5.0, `Anomaly detection: avg ${avgDetectTime.toFixed(2)}ms < 5.0ms per tick`);
assert(detectedAnomalies > 0, `Anomaly detection: found ${detectedAnomalies} anomalies from ${injectedCount} injected`);

// ============================================================
// TEST 6: SPATIAL GRID EFFICIENCY
// ============================================================

console.log('');
console.log('--- Test 6: Spatial Grid Query Efficiency ---');

_nextVehicleId = 0;
const gridTestVehicles = spawnVehicles(500, roadNetwork);
const testGrid = new SpatialGrid(20);
for (const v of gridTestVehicles) testGrid.insert(v);

const queryCount = 1000;
const queryStart = performance.now();
let totalNeighbors = 0;

for (let i = 0; i < queryCount; i++) {
    const v = gridTestVehicles[Math.floor(Math.random() * gridTestVehicles.length)];
    const nearby = testGrid.getNearby(v.x, v.z);
    totalNeighbors += nearby.length;
}

const queryElapsed = performance.now() - queryStart;
const avgNeighbors = totalNeighbors / queryCount;

console.log(`  ${queryCount} getNearby queries: ${queryElapsed.toFixed(1)}ms total`);
console.log(`  Avg neighbors per query: ${avgNeighbors.toFixed(1)} (vs ${gridTestVehicles.length} total)`);

assert(queryElapsed < 50, `Grid queries: ${queryCount} in ${queryElapsed.toFixed(1)}ms < 50ms`);
assert(avgNeighbors < gridTestVehicles.length * 0.5,
    `Grid reduces search space: avg ${avgNeighbors.toFixed(0)} < ${Math.floor(gridTestVehicles.length * 0.5)}`);

// ============================================================
// TEST 7: SUSTAINED SIMULATION — no drift or crash over time
// ============================================================

console.log('');
console.log('--- Test 7: Sustained 1000-tick Run (500 vehicles) ---');

_nextVehicleId = 0;
const sustainedVehicles = spawnVehicles(500, roadNetwork);
const sustainedGrid = new SpatialGrid(20);
const sustainedTimes = [];

for (let t = 0; t < 1000; t++) {
    const start = performance.now();
    sustainedGrid.clear();
    for (const v of sustainedVehicles) sustainedGrid.insert(v);
    trafficMgr.tick(dt);
    for (const v of sustainedVehicles) {
        const nearby = sustainedGrid.getNearby(v.x, v.z);
        v.tick(dt, nearby);
    }
    sustainedTimes.push(performance.now() - start);
}

// Check for NaN or Infinity
let badValues = 0;
for (const v of sustainedVehicles) {
    if (!isFinite(v.x) || !isFinite(v.z) || !isFinite(v.speed) || !isFinite(v.u)) badValues++;
}

const sustainedAvg = sustainedTimes.reduce((a, b) => a + b, 0) / sustainedTimes.length;
const sustainedMax = Math.max(...sustainedTimes);
const sustainedP95 = sustainedTimes.sort((a, b) => a - b)[Math.floor(sustainedTimes.length * 0.95)];

// Check for performance degradation: compare first 100 vs last 100
const first100Avg = sustainedTimes.slice(0, 100).reduce((a, b) => a + b, 0) / 100;
const last100Avg = sustainedTimes.slice(-100).reduce((a, b) => a + b, 0) / 100;
const degradation = last100Avg / first100Avg;

console.log(`  1000 ticks completed`);
console.log(`  Avg: ${sustainedAvg.toFixed(2)}ms  P95: ${sustainedP95.toFixed(2)}ms  Max: ${sustainedMax.toFixed(2)}ms`);
console.log(`  First 100 avg: ${first100Avg.toFixed(2)}ms, Last 100 avg: ${last100Avg.toFixed(2)}ms`);
console.log(`  Degradation ratio: ${degradation.toFixed(2)}x`);

assert(badValues === 0, `Sustained: no NaN/Infinity after 1000 ticks (found ${badValues})`);
assert(sustainedAvg < 16, `Sustained: avg tick ${sustainedAvg.toFixed(2)}ms < 16ms`);
assert(degradation < 3.5, `Sustained: no perf degradation (ratio ${degradation.toFixed(2)} < 3.5x)`);

// ============================================================
// RESULTS SUMMARY
// ============================================================

console.log('');
console.log('================================================================');
console.log('  PERFORMANCE PROFILE');
console.log('================================================================');
console.log('');
console.log('  Vehicles  |  Avg (ms)  |  P95 (ms)  |  P99 (ms)  |  Max (ms)');
console.log('  ----------|------------|------------|------------|----------');
for (const count of [50, 100, 200, 500, 1000]) {
    const r = results[count];
    if (r) {
        console.log(`  ${String(count).padStart(8)}  |  ${r.avg.toFixed(2).padStart(8)}  |  ${r.p95.toFixed(2).padStart(8)}  |  ${r.p99.toFixed(2).padStart(8)}  |  ${r.max.toFixed(2).padStart(8)}`);
    }
}
console.log('');
console.log(`  Total: ${passed} passed, ${failed} failed`);
console.log('');

if (failed > 0) {
    console.log(`STRESS TEST FAILED: ${failed} assertions failed`);
    process.exit(1);
} else {
    console.log('STRESS TEST PASSED: All performance budgets met');
    process.exit(0);
}
