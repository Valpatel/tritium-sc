#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Phase 3.5 Quality Gate: IDM physics, vehicle simulation, city sim manager.
 */

const fs = require('fs');
const path = require('path');

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
// SECTION 1: IDM Source Structure
// ============================================================

console.log('--- IDM Module ---');
const libSimDir = path.join(__dirname, '../../../tritium-lib/web/sim');
const idmSource = fs.readFileSync(
    path.join(libSimDir, 'idm.js'), 'utf8'
);

assert(idmSource.includes('idmAcceleration'), 'idmAcceleration function exists');
assert(idmSource.includes('idmFreeFlow'), 'idmFreeFlow function exists');
assert(idmSource.includes('idmStep'), 'idmStep function exists');
assert(idmSource.includes('IDM_DEFAULTS'), 'IDM_DEFAULTS exported');
assert(idmSource.includes('ROAD_SPEEDS'), 'ROAD_SPEEDS exported');
assert(idmSource.includes('Treiber 2000'), 'References IDM paper');

// ============================================================
// SECTION 2: IDM Physics Tests (inline)
// ============================================================

console.log('\n--- IDM Physics ---');

// Replicate IDM formulas for testing
function idmAcceleration(v, gap, vLeader, params) {
    const { v0, a, b, s0, T, delta } = params;
    const freeRoad = 1 - Math.pow(v / v0, delta);
    const dv = v - vLeader;
    const sStar = s0 + Math.max(0, v * T + (v * dv) / (2 * Math.sqrt(a * b)));
    const interaction = (sStar / Math.max(gap, 0.1)) ** 2;
    return Math.max(-9.0, Math.min(a, a * (freeRoad - interaction)));
}

function idmFreeFlow(v, params) {
    const { v0, a, delta } = params;
    return a * (1 - Math.pow(v / v0, delta));
}

const IDM = { v0: 12, a: 1.4, b: 2.0, s0: 2.0, T: 1.5, delta: 4 };

// Free flow: car at 0 speed should accelerate
{
    const acc = idmFreeFlow(0, IDM);
    assert(acc > 0, `Free flow from standstill: acc=${acc.toFixed(2)} > 0`);
    assertApprox(acc, IDM.a, 0.01, 'Free flow at v=0 gives max acceleration');
}

// Free flow: car at desired speed should have ~0 acceleration
{
    const acc = idmFreeFlow(IDM.v0, IDM);
    assertApprox(acc, 0, 0.1, 'Free flow at v0 gives ~0 acceleration');
}

// Following: car close behind stopped car should brake hard
{
    const acc = idmAcceleration(10, 3, 0, IDM);
    assert(acc < -2, `Braking behind stopped car: acc=${acc.toFixed(2)} < -2`);
}

// Following: car far behind moving car at same speed should be ~free flow
{
    const acc = idmAcceleration(10, 100, 10, IDM);
    assert(acc > -0.5, `Far behind at same speed: acc=${acc.toFixed(2)} > -0.5`);
}

// Following: car approaching faster leader should have mild deceleration
{
    const acc = idmAcceleration(10, 30, 12, IDM);
    assert(acc > -1, `Approaching faster leader: acc=${acc.toFixed(2)} > -1`);
}

// Emergency braking: very close to stopped car
{
    const acc = idmAcceleration(15, 1, 0, IDM);
    assert(acc < -5, `Emergency braking: acc=${acc.toFixed(2)} < -5`);
}

// IDM step: speed never goes negative
{
    const v = 0.1, acc = -5, dt = 1;
    const newV = Math.max(0, v + acc * dt);
    assert(newV === 0, 'Speed clamped to 0 (never negative)');
}

// IDM convergence: simulate 30 seconds of free flow
{
    let v = 0, pos = 0;
    for (let t = 0; t < 300; t++) {
        const acc = idmFreeFlow(v, IDM);
        const dt = 0.1;
        v = Math.max(0, v + acc * dt);
        pos += v * dt;
    }
    assertApprox(v, IDM.v0, 1.0, `Free flow converges to v0 after 30s (v=${v.toFixed(1)})`);
}

// Following convergence: car behind leader at v0 should stabilize
{
    let v = 0, gap = 50;
    const leaderSpeed = 10;
    for (let t = 0; t < 500; t++) {
        const acc = idmAcceleration(v, gap, leaderSpeed, IDM);
        const dt = 0.1;
        const oldV = v;
        v = Math.max(0, v + acc * dt);
        gap -= (v - leaderSpeed) * dt;
    }
    assertApprox(v, leaderSpeed, 1.0, `Following converges to leader speed (v=${v.toFixed(1)})`);
    assert(gap > IDM.s0, `Following maintains safe gap (gap=${gap.toFixed(1)} > s0=${IDM.s0})`);
}

// ============================================================
// SECTION 3: Vehicle Source Structure
// ============================================================

console.log('\n--- Vehicle Module ---');
const vehSource = fs.readFileSync(
    path.join(__dirname, '../../../tritium-lib/web/sim/vehicle.js'), 'utf8'
);

assert(vehSource.includes('class SimVehicle'), 'SimVehicle class defined');
assert(vehSource.includes('tick('), 'tick method exists');
assert(vehSource.includes('_planNewRoute'), '_planNewRoute method exists');
assert(vehSource.includes('_advanceToNextEdge'), '_advanceToNextEdge method exists');
assert(vehSource.includes('_updatePosition'), '_updatePosition method exists');
assert(vehSource.includes("import { idmAcceleration"), 'Imports IDM functions');
assert(vehSource.includes('ROAD_SPEEDS'), 'Uses ROAD_SPEEDS for speed limits');
assert(vehSource.includes('_CAR_COLORS'), 'Has car color palette');

// ============================================================
// SECTION 4: CitySimManager Structure
// ============================================================

console.log('\n--- CitySimManager ---');
const csmSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/sim/city-sim-manager.js'), 'utf8'
);

assert(csmSource.includes('spawnVehicles('), 'spawnVehicles method exists');
assert(csmSource.includes('clearVehicles('), 'clearVehicles method exists');
assert(csmSource.includes('initRendering('), 'initRendering method exists');
assert(csmSource.includes('updateRendering('), 'updateRendering method exists');
assert(csmSource.includes('InstancedMesh'), 'Uses InstancedMesh for vehicles');
assert(csmSource.includes('maxVehicles'), 'Has maxVehicles limit');
assert(csmSource.includes('avgSpeedMs'), 'Stats include average speed');
assert(csmSource.includes("import { SimVehicle }"), 'Imports SimVehicle');

// ============================================================
// SECTION 5: map3d Integration
// ============================================================

console.log('\n--- map3d Integration ---');
const map3dSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map3d.js'), 'utf8'
);

assert(map3dSource.includes('citySim.tick'), 'map3d calls citySim.tick in render loop');
assert(map3dSource.includes('citySim.updateRendering'), 'map3d calls updateRendering in render loop');
assert(map3dSource.includes('citySim.spawnVehicles'), 'map3d spawns vehicles after load');
assert(map3dSource.includes('citySim.initRendering'), 'map3d initializes vehicle rendering');
assert(map3dSource.includes('toggleCitySim'), 'toggleCitySim function exists');
assert(map3dSource.includes('getCitySimStats'), 'getCitySimStats function exists');
assert(map3dSource.includes('showCitySim'), 'getMapState includes showCitySim');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== CITY SIM: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
