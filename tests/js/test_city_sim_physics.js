#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Comprehensive city simulation physics test.
 *
 * Tests IDM car-following, road network pathfinding, vehicle-on-road movement,
 * spatial grid, traffic controller cycles, MOBIL lane changes, weather effects,
 * and anomaly detection — all with inlined pure logic (no Three.js).
 */

let passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; console.log(`PASS: ${msg}`); }
    else { failed++; console.log(`FAIL: ${msg}`); }
}

function assertApprox(a, b, tol, msg) {
    const ok = Math.abs(a - b) <= tol;
    if (ok) { passed++; console.log(`PASS: ${msg} (${a} ≈ ${b})`); }
    else { failed++; console.log(`FAIL: ${msg} (${a} != ${b} ±${tol})`); }
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
// INLINED CORE: ROAD NETWORK (minimal for testing)
// ============================================================

class TestRoadNetwork {
    constructor() {
        this.nodes = {};
        this.edges = [];
        this.adjList = {};
        this.edgeById = {};
    }

    addNode(id, x, z, approaches = []) {
        this.nodes[id] = { id, x, z, approaches, col: 0, row: 0 };
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
    constructor(approaches) {
        this.phases = buildSignalPhases(approaches);
        this.currentPhase = 0;
        this.phaseTimer = 0;
    }
    getCurrentPhase() { return this.phases[this.currentPhase]; }
    isGreen(dir) {
        const phase = this.getCurrentPhase();
        return phase.type === 'green' && phase.greenApproaches.includes(dir);
    }
    getLightState(dir) {
        const phase = this.getCurrentPhase();
        if (phase.type === 'allRed') return 'red';
        if (phase.greenApproaches.includes(dir)) return phase.type === 'yellow' ? 'yellow' : 'green';
        return 'red';
    }
    tick(dt) {
        this.phaseTimer += dt;
        const phase = this.getCurrentPhase();
        if (this.phaseTimer >= phase.duration) {
            this.phaseTimer -= phase.duration;
            this.currentPhase = (this.currentPhase + 1) % this.phases.length;
        }
    }
}

// ============================================================
// INLINED CORE: MOBIL
// ============================================================

const MOBIL_DEFAULTS = { politeness: 0.3, threshold: 0.2, bSafe: 4.0, minGap: 5.0 };

function findNeighborsInLane(u, road, lane, allCars, excludeCar) {
    let aheadGap = Infinity, behindGap = Infinity;
    let ahead = null, behind = null;
    for (const car of allCars) {
        if (car === excludeCar) continue;
        if (car.road !== road) continue;
        if (car.lane !== lane) continue;
        const gap = car.u - u;
        if (gap > 0 && gap < aheadGap) { aheadGap = gap; ahead = car; }
        else if (gap < 0 && -gap < behindGap) { behindGap = -gap; behind = car; }
    }
    if (ahead) aheadGap = Math.max(0.1, aheadGap - (excludeCar.length || 4) - (ahead.length || 4));
    if (behind) behindGap = Math.max(0.1, behindGap - (excludeCar.length || 4) - (behind.length || 4));
    return { ahead, aheadGap, behind, behindGap };
}

function evaluateLaneChange(car, targetLane, allCars, params = MOBIL_DEFAULTS) {
    const { politeness, threshold, bSafe, minGap } = params;
    const idmP = car.idmParams;
    const currentNeighbors = findNeighborsInLane(car.u, car.road, car.lane, allCars, car);
    const a_c = idmAcceleration(car.speed, currentNeighbors.aheadGap,
        currentNeighbors.ahead ? currentNeighbors.ahead.speed : car.speed, idmP);
    const targetNeighbors = findNeighborsInLane(car.u, car.road, targetLane, allCars, car);
    if (targetNeighbors.aheadGap < minGap || targetNeighbors.behindGap < minGap) {
        return { shouldChange: false, incentive: -Infinity, reason: 'insufficient_gap' };
    }
    const a_c_prime = idmAcceleration(car.speed, targetNeighbors.aheadGap,
        targetNeighbors.ahead ? targetNeighbors.ahead.speed : car.speed, idmP);
    if (!targetNeighbors.behind) {
        const incentive = a_c_prime - a_c;
        return { shouldChange: incentive > threshold, incentive, reason: incentive > threshold ? 'beneficial_empty_lane' : 'insufficient_incentive' };
    }
    const newFollower = targetNeighbors.behind;
    const newFollowerIdm = newFollower.idmParams || idmP;
    const a_n_prime = idmAcceleration(newFollower.speed, targetNeighbors.behindGap, car.speed, newFollowerIdm);
    if (a_n_prime < -bSafe) {
        return { shouldChange: false, incentive: -Infinity, reason: 'unsafe_new_follower' };
    }
    const incentive = a_c_prime - a_c;
    return { shouldChange: incentive > threshold, incentive, reason: incentive > threshold ? 'beneficial' : 'insufficient_incentive' };
}

// ============================================================
// INLINED CORE: WEATHER
// ============================================================

function computeWeather(simState) {
    const isNight = simState.isNight;
    const rain = simState.weather.rain;
    const dayFactor = isNight ? 0.2 : 1.0;
    const rainDim = rain ? 0.7 : 1.0;
    let baseFogDensity = isNight ? 0.004 : 0.0015;
    if (rain) baseFogDensity = Math.max(baseFogDensity, 0.004);
    if (simState.weather.fog) baseFogDensity = 0.008;
    return {
        isNight, dayFactor, rainDim,
        ambientIntensity: (0.3 + dayFactor * 0.4) * rainDim,
        sunIntensity: dayFactor * 1.2 * rainDim,
        fogDensity: baseFogDensity,
    };
}

// ============================================================
// INLINED CORE: STREAMING STAT (for anomaly detection)
// ============================================================

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

// ============================================================
// INLINED CORE: ANOMALY DETECTOR
// ============================================================

class TestAnomalyDetector {
    constructor() {
        this._edgeSpeedStats = new Map();
        this._baselineReady = false;
        this._baselineTime = 0;
        this._baselineDuration = 300;
        this.anomalies = [];
        this.totalDetections = 0;
    }

    tick(dt, vehicles) {
        this._baselineTime += dt;
        const newAnomalies = [];

        if (!this._baselineReady) {
            if (this._baselineTime >= this._baselineDuration) {
                this._baselineReady = true;
            }
            for (const v of vehicles) {
                if (v.edge) {
                    const key = v.edge.id;
                    if (!this._edgeSpeedStats.has(key)) {
                        this._edgeSpeedStats.set(key, new StreamingStat());
                    }
                    this._edgeSpeedStats.get(key).push(v.speed);
                }
            }
            return [];
        }

        // Speed anomaly detection (Z-Score)
        for (const v of vehicles) {
            if (!v.edge) continue;
            const edgeStats = this._edgeSpeedStats.get(v.edge.id);
            if (!edgeStats || edgeStats.n < 20) continue;
            const z = edgeStats.zScore(v.speed);
            if (Math.abs(z) > 3.0) {
                newAnomalies.push({
                    entityId: v.id,
                    type: 'speed',
                    zScore: z,
                });
                this.totalDetections++;
            }
        }

        this.anomalies.push(...newAnomalies);
        return newAnomalies;
    }

    get baselineReady() { return this._baselineReady; }
}

// ============================================================
// SECTION 1: IDM Physics Convergence
// ============================================================

console.log('=== SECTION 1: IDM Physics Convergence ===');

// 1a. Free flow: car from 0 m/s reaches v0 within 30s
{
    let v = 0;
    const dt = 0.1;
    for (let t = 0; t < 300; t++) {
        const acc = idmAcceleration(v, Infinity, v);
        const upd = ballisticUpdate(0, v, acc, dt);
        v = upd.v;
    }
    assert(Math.abs(v - IDM_DEFAULTS.v0) < 1.0,
        `Free flow: v=${v.toFixed(2)} reaches v0=${IDM_DEFAULTS.v0} within tolerance`);
}

// 1b. Following: two cars, leader at constant speed, follower converges
{
    let v = 0, gap = 50;
    const leaderSpeed = 10;
    const dt = 0.1;
    for (let t = 0; t < 500; t++) {
        const acc = idmAcceleration(v, gap, leaderSpeed);
        v = Math.max(0, v + acc * dt);
        gap -= (v - leaderSpeed) * dt;
    }
    assertApprox(v, leaderSpeed, 1.0, `Following: follower converges to leader speed=${leaderSpeed}`);
    assert(gap > IDM_DEFAULTS.s0, `Following: safe gap maintained (gap=${gap.toFixed(1)} > s0=${IDM_DEFAULTS.s0})`);
}

// 1c. Emergency braking: car at 15 m/s, stopped obstacle 30m ahead
{
    let v = 15, u = 0;
    const obstacleU = 30;
    const carLen = 4;
    const dt = 0.05; // finer step for braking
    for (let t = 0; t < 400; t++) {
        const gap = Math.max(0.1, obstacleU - u - carLen);
        const acc = idmAcceleration(v, gap, 0);
        const upd = ballisticUpdate(u, v, acc, dt);
        u = upd.u;
        v = upd.v;
        if (v < 0.01) break;
    }
    assert(u < obstacleU - carLen, `Emergency braking: stopped at u=${u.toFixed(2)} before obstacle at ${obstacleU - carLen}`);
    assert(v < 0.1, `Emergency braking: speed near zero (v=${v.toFixed(3)})`);
}

// 1d. Multiple cars in chain: 5 cars following each other
{
    const cars = [];
    for (let i = 0; i < 5; i++) {
        cars.push({ u: i * 20, v: 0 }); // 20m apart initially
    }
    const dt = 0.1;
    for (let t = 0; t < 600; t++) {
        for (let i = 0; i < 5; i++) {
            let gap = Infinity, leaderSpeed = cars[i].v;
            // Leader is the car ahead (higher index = further ahead)
            if (i < 4) {
                gap = Math.max(0.1, cars[i + 1].u - cars[i].u - 8);
                leaderSpeed = cars[i + 1].v;
            }
            const acc = idmAcceleration(cars[i].v, gap, leaderSpeed);
            const upd = ballisticUpdate(cars[i].u, cars[i].v, acc, dt);
            cars[i].u = upd.u;
            cars[i].v = upd.v;
        }
    }

    // All cars should have positive speed and maintain gaps
    let allHaveGaps = true;
    for (let i = 0; i < 4; i++) {
        const gap = cars[i + 1].u - cars[i].u;
        if (gap < IDM_DEFAULTS.s0) allHaveGaps = false;
    }
    assert(allHaveGaps, `Chain: all 5 cars maintain safe gaps`);
    assert(cars[0].v > 5, `Chain: rear car has reasonable speed (v=${cars[0].v.toFixed(1)})`);
    assert(cars[4].v > 5, `Chain: lead car has reasonable speed (v=${cars[4].v.toFixed(1)})`);
}

// ============================================================
// SECTION 2: Road Network Pathfinding
// ============================================================

console.log('\n=== SECTION 2: Road Network Pathfinding ===');

// 2a. Create a 3x3 grid (4x4 = 16 intersections, 24 edges)
{
    const net = new TestRoadNetwork();
    // Create 4x4 grid of nodes
    for (let r = 0; r < 4; r++) {
        for (let c = 0; c < 4; c++) {
            net.addNode(`${c}_${r}`, c * 100, r * 100, ['N', 'S', 'E', 'W']);
        }
    }
    // Horizontal edges
    for (let r = 0; r < 4; r++) {
        for (let c = 0; c < 3; c++) {
            net.addEdge(`h_${c}_${r}`, `${c}_${r}`, `${c + 1}_${r}`, 100, true);
        }
    }
    // Vertical edges
    for (let c = 0; c < 4; c++) {
        for (let r = 0; r < 3; r++) {
            net.addEdge(`v_${c}_${r}`, `${c}_${r}`, `${c}_${r + 1}`, 100, false);
        }
    }

    assert(Object.keys(net.nodes).length === 16, `3x3 grid: 16 nodes created`);
    assert(net.edges.length === 24, `3x3 grid: 24 edges created`);

    // Shortest path from corner (0,0) to corner (3,3) = 6 edges (Manhattan distance)
    const path = net.findPath('0_0', '3_3');
    assert(path.length === 6, `Path 0,0→3,3: length=${path.length} (expected 6)`);

    // Total distance = 6 * 100 = 600
    let totalDist = 0;
    for (const step of path) totalDist += step.edge.length;
    assertApprox(totalDist, 600, 0.1, `Path distance: ${totalDist} = 600`);

    // Adjacent path is 1 edge
    const shortPath = net.findPath('0_0', '1_0');
    assert(shortPath.length === 1, `Adjacent path: 1 edge`);

    // Same node returns empty
    const samePath = net.findPath('0_0', '0_0');
    assert(samePath.length === 0, `Same node: empty path`);
}

// 2b. Disconnected components return empty path
{
    const net = new TestRoadNetwork();
    net.addNode('A', 0, 0);
    net.addNode('B', 100, 0);
    net.addNode('C', 200, 0);
    net.addNode('D', 500, 500);
    net.addEdge('e1', 'A', 'B', 100);
    net.addEdge('e2', 'B', 'C', 100);
    // D is disconnected
    const path = net.findPath('A', 'D');
    assert(path.length === 0, `Disconnected: no path A→D`);

    // But A→C works
    const pathAC = net.findPath('A', 'C');
    assert(pathAC.length === 2, `Connected: A→C = 2 edges`);
}

// ============================================================
// SECTION 3: Vehicle on Road
// ============================================================

console.log('\n=== SECTION 3: Vehicle on Road ===');

// Create a simple 2-edge road: A → B → C
{
    const net = new TestRoadNetwork();
    net.addNode('A', 0, 0);
    net.addNode('B', 100, 0);
    net.addNode('C', 200, 0);
    const edge1 = net.addEdge('e1', 'A', 'B', 100, true);
    const edge2 = net.addEdge('e2', 'B', 'C', 100, true);

    // Simulate a vehicle starting at A, lane 0, u=0
    let u = 0, v = 0;
    let currentEdge = edge1;
    const dt = 0.1;

    for (let t = 0; t < 100; t++) { // 10 seconds
        const acc = idmAcceleration(v, Infinity, v); // free flow
        const upd = ballisticUpdate(u, v, acc, dt);
        u = upd.u;
        v = upd.v;

        // Edge transition
        if (u >= currentEdge.length && currentEdge === edge1) {
            u -= currentEdge.length;
            currentEdge = edge2;
        }
    }

    assert(u > 0, `Vehicle moved: u=${u.toFixed(1)}`);
    assert(v > 0, `Vehicle has positive speed: v=${v.toFixed(2)}`);
    assert(v <= IDM_DEFAULTS.v0 + 0.1, `Vehicle speed <= v0: v=${v.toFixed(2)} <= ${IDM_DEFAULTS.v0}`);

    // Position is on one of the two edges
    const totalTravel = (currentEdge === edge2 ? edge1.length + u : u);
    assert(totalTravel > 0 && totalTravel < 200, `Vehicle within road bounds: pos=${totalTravel.toFixed(1)}`);
}

// ============================================================
// SECTION 4: Spatial Grid
// ============================================================

console.log('\n=== SECTION 4: Spatial Grid ===');

{
    // Simple spatial hash grid
    const cellSize = 50;
    const grid = new Map();
    const entities = [];

    function cellKey(x, z) {
        return `${Math.floor(x / cellSize)},${Math.floor(z / cellSize)}`;
    }

    function insertEntity(e) {
        const key = cellKey(e.x, e.z);
        if (!grid.has(key)) grid.set(key, []);
        grid.get(key).push(e);
    }

    function queryNearby(x, z, radius) {
        const results = [];
        const minCX = Math.floor((x - radius) / cellSize);
        const maxCX = Math.floor((x + radius) / cellSize);
        const minCZ = Math.floor((z - radius) / cellSize);
        const maxCZ = Math.floor((z + radius) / cellSize);
        for (let cx = minCX; cx <= maxCX; cx++) {
            for (let cz = minCZ; cz <= maxCZ; cz++) {
                const key = `${cx},${cz}`;
                const cell = grid.get(key);
                if (cell) {
                    for (const e of cell) {
                        const dx = e.x - x, dz = e.z - z;
                        if (Math.sqrt(dx * dx + dz * dz) <= radius) results.push(e);
                    }
                }
            }
        }
        return results;
    }

    // Insert 100 entities at random positions in a 500x500 area
    // Use deterministic pseudo-random for repeatability
    let seed = 42;
    function pseudoRandom() {
        seed = (seed * 1664525 + 1013904223) & 0x7fffffff;
        return seed / 0x7fffffff;
    }

    for (let i = 0; i < 100; i++) {
        const e = { id: i, x: pseudoRandom() * 500, z: pseudoRandom() * 500 };
        entities.push(e);
        insertEntity(e);
    }

    assert(entities.length === 100, `Inserted 100 entities`);

    // Query center with 75m radius — should find some but not all
    const nearby = queryNearby(250, 250, 75);
    assert(nearby.length > 0, `Center query found ${nearby.length} entities (> 0)`);
    assert(nearby.length < 100, `Center query found ${nearby.length} entities (< 100)`);

    // Verify all returned entities are actually within radius
    let allWithinRadius = true;
    for (const e of nearby) {
        const dx = e.x - 250, dz = e.z - 250;
        if (Math.sqrt(dx * dx + dz * dz) > 75) {
            allWithinRadius = false;
            break;
        }
    }
    assert(allWithinRadius, `All returned entities within query radius`);

    // Verify no entity is in the wrong cell
    let allCorrectCell = true;
    for (const e of entities) {
        const expectedKey = cellKey(e.x, e.z);
        const cell = grid.get(expectedKey);
        if (!cell || !cell.some(c => c.id === e.id)) {
            allCorrectCell = false;
            break;
        }
    }
    assert(allCorrectCell, `All entities in correct grid cell`);
}

// ============================================================
// SECTION 5: Traffic Controller
// ============================================================

console.log('\n=== SECTION 5: Traffic Controller ===');

{
    const ctrl = new TestTrafficController(['N', 'S', 'E', 'W']);
    assert(ctrl.phases.length === 6, `4-way intersection: 6 phases`);

    // Track which directions get green over a full cycle
    const gotGreen = { N: false, S: false, E: false, W: false };
    let allRedCount = 0;
    const dt = 0.5;
    const totalCycleTime = 36; // 15+2+1+15+2+1 = 36s

    // Run for 2 full cycles to be safe
    for (let t = 0; t < totalCycleTime * 2; t += dt) {
        const phase = ctrl.getCurrentPhase();
        if (phase.type === 'allRed') allRedCount++;
        for (const dir of ['N', 'S', 'E', 'W']) {
            if (ctrl.isGreen(dir)) gotGreen[dir] = true;
        }
        ctrl.tick(dt);
    }

    assert(gotGreen.N, `Traffic: N gets green`);
    assert(gotGreen.S, `Traffic: S gets green`);
    assert(gotGreen.E, `Traffic: E gets green`);
    assert(gotGreen.W, `Traffic: W gets green`);
    assert(allRedCount > 0, `Traffic: all-red phases exist (count=${allRedCount})`);

    // Verify N and S get green together
    const ctrl2 = new TestTrafficController(['N', 'S', 'E', 'W']);
    ctrl2.phaseTimer = 0;
    ctrl2.currentPhase = 0; // NS green
    assert(ctrl2.isGreen('N') && ctrl2.isGreen('S'), `Traffic: N and S green together`);
    assert(!ctrl2.isGreen('E') && !ctrl2.isGreen('W'), `Traffic: E and W red when NS is green`);

    // Verify getLightState returns correct values
    assert(ctrl2.getLightState('N') === 'green', `getLightState: N=green`);
    assert(ctrl2.getLightState('E') === 'red', `getLightState: E=red`);

    // Advance to yellow phase
    ctrl2.tick(15); // past first green
    assert(ctrl2.getLightState('N') === 'yellow', `getLightState: N=yellow after green`);
}

// ============================================================
// SECTION 6: MOBIL Lane Change
// ============================================================

console.log('\n=== SECTION 6: MOBIL Lane Change ===');

{
    const road = {
        id: 'test_road', length: 500, numLanesPerDir: 2, laneWidth: 3,
        ax: 0, az: 0, bx: 500, bz: 0, horizontal: true,
    };

    // Slow leader in lane 0 at u=200
    const leader = {
        id: 'leader', road, lane: 0, u: 200, speed: 5, length: 4,
        idmParams: IDM_DEFAULTS,
    };
    // Fast follower in lane 0 at u=170 (30m behind, 22m bumper-to-bumper gap)
    const follower = {
        id: 'follower', road, lane: 0, u: 170, speed: 12, length: 4,
        idmParams: IDM_DEFAULTS,
    };

    const allCars = [leader, follower];

    // Evaluate lane change to lane 1 (empty lane, same direction)
    const result = evaluateLaneChange(follower, 1, allCars);

    assert(result.shouldChange === true,
        `MOBIL: recommends lane change (incentive=${result.incentive.toFixed(2)})`);
    assert(result.incentive > MOBIL_DEFAULTS.threshold,
        `MOBIL: incentive ${result.incentive.toFixed(2)} > threshold ${MOBIL_DEFAULTS.threshold}`);

    // Now test with blocked target lane
    const blocker = {
        id: 'blocker', road, lane: 1, u: 175, speed: 5, length: 4,
        idmParams: IDM_DEFAULTS,
    };
    const allCars2 = [leader, follower, blocker];
    const result2 = evaluateLaneChange(follower, 1, allCars2);
    // With a slow car also in lane 1 very close, it should be less beneficial or unsafe
    assert(result2.incentive < result.incentive,
        `MOBIL: blocked lane has lower incentive (${result2.incentive.toFixed(2)} < ${result.incentive.toFixed(2)})`);
}

// Lane change with no benefit (already going desired speed, open road)
{
    const road = {
        id: 'test_road2', length: 500, numLanesPerDir: 2, laneWidth: 3,
        ax: 0, az: 0, bx: 500, bz: 0, horizontal: true,
    };
    const freeCar = {
        id: 'free', road, lane: 0, u: 100, speed: 12, length: 4,
        idmParams: IDM_DEFAULTS,
    };
    const result = evaluateLaneChange(freeCar, 1, [freeCar]);
    assert(result.shouldChange === false,
        `MOBIL: no lane change when already free flowing`);
}

// ============================================================
// SECTION 7: Weather Effects
// ============================================================

console.log('\n=== SECTION 7: Weather Effects ===');

{
    // Clear day
    const clearDay = computeWeather({ isNight: false, weather: { rain: false, fog: false }, simTime: 12 });
    assert(clearDay.dayFactor === 1.0, `Clear day: dayFactor=1.0`);
    assert(clearDay.rainDim === 1.0, `Clear day: rainDim=1.0`);
    assert(!clearDay.isNight, `Clear day: isNight=false`);

    // Rainy day
    const rainyDay = computeWeather({ isNight: false, weather: { rain: true, fog: false }, simTime: 12 });
    assert(rainyDay.rainDim < 1.0, `Rain: rainDim=${rainyDay.rainDim} < 1.0`);
    assert(rainyDay.fogDensity >= 0.004, `Rain: fogDensity=${rainyDay.fogDensity} >= 0.004`);

    // Night
    const night = computeWeather({ isNight: true, weather: { rain: false, fog: false }, simTime: 23 });
    assert(night.isNight === true, `Night: isNight=true`);
    assert(night.dayFactor === 0.2, `Night: dayFactor=0.2`);
    assert(night.sunIntensity < clearDay.sunIntensity, `Night: sunIntensity lower than day`);
    assert(night.ambientIntensity < clearDay.ambientIntensity, `Night: ambientIntensity lower than day`);

    // Fog
    const foggy = computeWeather({ isNight: false, weather: { rain: false, fog: true }, simTime: 12 });
    assert(foggy.fogDensity === 0.008, `Fog: fogDensity=0.008`);
    assert(foggy.fogDensity > clearDay.fogDensity, `Fog: fogDensity > clear day`);

    // Speed multiplier concept: rain reduces effective driving speed
    // (In the actual sim, weather affects IDM v0; here we verify the multiplier concept)
    const rainSpeedMult = rainyDay.rainDim;
    assert(rainSpeedMult < 1.0, `Rain: speed multiplier=${rainSpeedMult} < 1.0`);
}

// ============================================================
// SECTION 8: Anomaly Detection
// ============================================================

console.log('\n=== SECTION 8: Anomaly Detection ===');

{
    const detector = new TestAnomalyDetector();
    const edge = { id: 'test_edge' };

    // Feed baseline data for 300 ticks (baseline duration = 300s)
    // Normal vehicles: speed around 10 m/s with small variation
    seed = 123;
    for (let t = 0; t < 300; t++) {
        const normalVehicles = [];
        for (let i = 0; i < 5; i++) {
            normalVehicles.push({
                id: `v_${i}`, edge, speed: 10 + (pseudoRandom() - 0.5) * 2, // 9-11 m/s
            });
        }
        detector.tick(1, normalVehicles);
    }

    assert(detector.baselineReady === true, `Anomaly: baseline established after 300 ticks`);

    // Now feed a vehicle with speed 3x average (30 m/s vs ~10 m/s average)
    const anomalousVehicles = [
        { id: 'normal_1', edge, speed: 10 },
        { id: 'speeder', edge, speed: 30 }, // 3x average
    ];
    const anomalies = detector.tick(1, anomalousVehicles);

    // Check if speed anomaly detected
    const speedAnomaly = anomalies.find(a => a.entityId === 'speeder' && a.type === 'speed');
    assert(speedAnomaly !== undefined, `Anomaly: speed anomaly detected for 3x-speed vehicle`);

    if (speedAnomaly) {
        assert(Math.abs(speedAnomaly.zScore) > 3.0,
            `Anomaly: z-score=${speedAnomaly.zScore.toFixed(1)} exceeds 3-sigma threshold`);
    }

    // Normal vehicle should NOT trigger anomaly
    const normalAnomaly = anomalies.find(a => a.entityId === 'normal_1');
    assert(normalAnomaly === undefined, `Anomaly: normal vehicle not flagged`);
}

// ============================================================
// SECTION 9: IDM Edge Cases
// ============================================================

console.log('\n=== SECTION 9: IDM Edge Cases ===');

// Speed never goes negative
{
    const acc = idmAcceleration(0.1, 1, 0);
    const upd = ballisticUpdate(0, 0.1, acc, 1.0);
    assert(upd.v >= 0, `Speed never negative: v=${upd.v}`);
}

// Zero gap produces strong braking
{
    const acc = idmAcceleration(10, 0.01, 0);
    assert(acc < -5, `Near-zero gap: strong braking acc=${acc.toFixed(1)}`);
}

// Acceleration is bounded
{
    const acc = idmAcceleration(0, Infinity, 0);
    assert(acc <= IDM_DEFAULTS.a, `Max acceleration bounded: acc=${acc.toFixed(2)} <= a=${IDM_DEFAULTS.a}`);
    assert(acc >= IDM_DEFAULTS.a - 0.01, `Free flow from stop: acc=${acc.toFixed(2)} ≈ a=${IDM_DEFAULTS.a}`);
}

// ============================================================
// SECTION 10: Streaming Statistics
// ============================================================

console.log('\n=== SECTION 10: Streaming Statistics ===');

{
    const stat = new StreamingStat();
    const values = [10, 12, 11, 9, 10, 11, 10, 10, 12, 11];
    for (const v of values) stat.push(v);

    assert(stat.n === 10, `Streaming: n=10`);
    assertApprox(stat.mean, 10.6, 0.01, `Streaming: mean=10.6`);
    assert(stat.stddev > 0, `Streaming: stddev > 0 (${stat.stddev.toFixed(2)})`);

    // Z-score of mean should be 0
    assertApprox(stat.zScore(stat.mean), 0, 0.01, `Streaming: z-score of mean ≈ 0`);

    // Z-score of outlier should be large
    const z = stat.zScore(20);
    assert(Math.abs(z) > 3, `Streaming: z-score of 20 is large (z=${z.toFixed(1)})`);
}

// ============================================================
// Summary
// ============================================================

console.log(`\n=== CITY SIM PHYSICS: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
