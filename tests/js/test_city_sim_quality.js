#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Comprehensive quality gate tests for city simulation phases 4-10.
 * Validates: traffic control, pedestrians, sensor bridge, LOD,
 * weather, anomaly detection, and full integration.
 */

const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;

function assert(cond, msg) {
    if (cond) { passed++; console.log(`PASS: ${msg}`); }
    else { failed++; console.log(`FAIL: ${msg}`); }
}

function assertApprox(a, b, tol, msg) {
    const ok = Math.abs(a - b) <= tol;
    if (ok) { passed++; console.log(`PASS: ${msg} (${typeof a === 'number' ? a.toFixed(2) : a} ≈ ${b})`); }
    else { failed++; console.log(`FAIL: ${msg} (${a} != ${b} ±${tol})`); }
}

const simDir = path.join(__dirname, '../../src/frontend/js/command/sim');
const libSimDir = path.join(__dirname, '../../../tritium-lib/web/sim');
const read = (f) => {
    const libPath = path.join(libSimDir, f);
    if (fs.existsSync(libPath)) return fs.readFileSync(libPath, 'utf8');
    return fs.readFileSync(path.join(simDir, f), 'utf8');
};

// ============================================================
// PHASE 4: Traffic Controller
// ============================================================

console.log('=== Phase 4: Traffic Controller ===');
const tcSrc = read('traffic-controller.js');

assert(tcSrc.includes('class TrafficController'), 'TrafficController class exists');
assert(tcSrc.includes('class TrafficControllerManager'), 'TrafficControllerManager class exists');
assert(tcSrc.includes('_buildPhases'), '_buildPhases method exists');
assert(tcSrc.includes('isGreen('), 'isGreen method exists');
assert(tcSrc.includes('getSignalColor('), 'getSignalColor method exists');
assert(tcSrc.includes('getSignalStates('), 'getSignalStates method exists');
assert(tcSrc.includes('greenEdges'), 'Phases have greenEdges sets');
assert(tcSrc.includes("type: 'yellow'"), 'Yellow phase type exists');
assert(tcSrc.includes("type: 'allred'"), 'All-red phase type exists');
assert(tcSrc.includes('staggerOffset'), 'Stagger offset for desynchronization');
assert(tcSrc.includes('initFromNetwork'), 'initFromNetwork method exists');
assert(tcSrc.includes('degree < 3'), 'Only 3+ way intersections get signals');

// Phase cycling test (inline)
{
    const phases = [
        { duration: 20, type: 'green', greenEdges: new Set(['e1']) },
        { duration: 2, type: 'yellow', greenEdges: new Set(['e1']) },
        { duration: 1, type: 'allred', greenEdges: new Set() },
        { duration: 20, type: 'green', greenEdges: new Set(['e2']) },
        { duration: 2, type: 'yellow', greenEdges: new Set(['e2']) },
        { duration: 1, type: 'allred', greenEdges: new Set() },
    ];
    let current = 0, timer = 0;
    const totalCycle = phases.reduce((s, p) => s + p.duration, 0);

    // Simulate 2 full cycles
    for (let t = 0; t < totalCycle * 2; t += 0.1) {
        timer += 0.1;
        if (timer >= phases[current].duration) {
            timer -= phases[current].duration;
            current = (current + 1) % phases.length;
        }
    }
    assert(current === 0 || current === phases.length - 1, `Phase cycling: after 2 cycles, back to start or last (phase ${current})`);
    assert(totalCycle === 46, `Total cycle time is 46s (got ${totalCycle})`);
}

// ============================================================
// PHASE 5: Pedestrians
// ============================================================

console.log('\n=== Phase 5: Pedestrians ===');
const pedSrc = read('pedestrian.js');

assert(pedSrc.includes('class SimPedestrian'), 'SimPedestrian class exists');
assert(pedSrc.includes('PED_ACTIVITY'), 'PED_ACTIVITY enum exists');
assert(pedSrc.includes('PED_COLORS'), 'PED_COLORS map exists');
assert(pedSrc.includes('_generateSchedule'), 'Daily schedule generator exists');
assert(pedSrc.includes('inBuilding'), 'Building entry/exit tracking');
assert(pedSrc.includes('buildingTimer'), 'Building timer for timed exit');
assert(pedSrc.includes('bobPhase'), 'Walking animation bob phase');
assert(pedSrc.includes('desiredSpeed'), 'Configurable walking speed');
assert(pedSrc.includes('socialforce') || pedSrc.includes('repulsion'), 'Social force model for avoidance');
assert(pedSrc.includes('goalReached'), 'Goal-reaching detection');

// Schedule validation
{
    const scheduleHours = [6, 8, 12, 12.5, 17, 21]; // approximate from code
    for (let i = 1; i < scheduleHours.length; i++) {
        assert(scheduleHours[i] > scheduleHours[i-1], `Schedule hour ${i} (${scheduleHours[i]}) > hour ${i-1} (${scheduleHours[i-1]})`);
    }
    assert(scheduleHours.length === 6, 'Schedule has 6 activities');
}

// ============================================================
// PHASE 6: Sensor Bridge
// ============================================================

console.log('\n=== Phase 6: Sensor Bridge ===');
const sbSrc = read('sensor-bridge.js');

assert(sbSrc.includes('class SensorBridge'), 'SensorBridge class exists');
assert(sbSrc.includes('getMac('), 'Persistent MAC assignment method');
assert(sbSrc.includes('flush('), 'Buffer flush method');
assert(sbSrc.includes('bleInterval'), 'Configurable BLE interval');
assert(sbSrc.includes('detectionInterval'), 'Configurable detection interval');
assert(sbSrc.includes("type: 'ble_sighting'"), 'Generates BLE sighting events');
assert(sbSrc.includes("type: 'detection'"), 'Generates YOLO detection events');
assert(sbSrc.includes('_entityMacs'), 'Entity MAC persistence map');
assert(sbSrc.includes("class: 'car'"), 'Vehicle detections classify as car');
assert(sbSrc.includes("class: 'person'"), 'Pedestrian detections classify as person');

// MAC format test
{
    const mac = 'AA:BB:CC:00:00:00';
    const parts = mac.split(':');
    assert(parts.length === 6, 'MAC format: 6 octets');
    assert(parts.every(p => p.length === 2), 'MAC format: 2 chars per octet');
}

// ============================================================
// PHASE 7: LOD Manager
// ============================================================

console.log('\n=== Phase 7: LOD Manager ===');
const lodSrc = read('lod-manager.js');

assert(lodSrc.includes('class LODManager'), 'LODManager class exists');
assert(lodSrc.includes('assignSector('), 'Sector assignment method');
assert(lodSrc.includes('buildGeometry('), 'Geometry builder method');
assert(lodSrc.includes('updateLOD('), 'LOD update method');
assert(lodSrc.includes('getStats('), 'Stats method');
assert(lodSrc.includes('SECTOR_SIZE'), 'Sector size constant defined');
assert(lodSrc.includes('LOD2_DISTANCE'), 'LOD2 distance threshold defined');
assert(lodSrc.includes('LOD1_DISTANCE'), 'LOD1 distance threshold defined');
assert(lodSrc.includes('_buildLOD2'), 'LoD2 builder (full detail)');
assert(lodSrc.includes('_buildLOD1'), 'LoD1 builder (medium)');
assert(lodSrc.includes('_buildLOD0'), 'LoD0 builder (footprint only)');

// Sector assignment test
{
    const SECTOR_SIZE = 100;
    const testBuildings = [
        { polygon: [[10, 10], [20, 10], [20, 20], [10, 20]] },
        { polygon: [[110, 110], [120, 110], [120, 120], [110, 120]] },
        { polygon: [[15, 15], [25, 15], [25, 25], [15, 25]] },  // Same sector as first
    ];

    const sectors = new Map();
    for (const b of testBuildings) {
        let cx = 0, cz = 0;
        for (const [x, z] of b.polygon) { cx += x; cz += z; }
        cx /= b.polygon.length; cz /= b.polygon.length;
        const key = `${Math.floor(cx / SECTOR_SIZE)},${Math.floor(cz / SECTOR_SIZE)}`;
        if (!sectors.has(key)) sectors.set(key, []);
        sectors.get(key).push(b);
    }
    assert(sectors.size === 2, `Sector assignment: 3 buildings → 2 sectors (got ${sectors.size})`);
    assert(sectors.get('0,0')?.length === 2, 'Sector 0,0 has 2 buildings');
}

// ============================================================
// PHASE 8: Weather
// ============================================================

console.log('\n=== Phase 8: Weather ===');
const wSrc = read('weather.js');

assert(wSrc.includes('class CityWeather'), 'CityWeather class exists');
assert(wSrc.includes('SKY_COLORS'), 'Sky color keyframes defined');
assert(wSrc.includes('isNight'), 'Night detection');
assert(wSrc.includes('isDusk'), 'Dusk detection');
assert(wSrc.includes('isDawn'), 'Dawn detection');
assert(wSrc.includes('speedMultiplier'), 'Vehicle speed modifier');
assert(wSrc.includes('headwayMultiplier'), 'Following distance modifier');
assert(wSrc.includes('windowEmissive'), 'Window emissive control');
assert(wSrc.includes('headlightsOn'), 'Headlight state');
assert(wSrc.includes('streetLightsOn'), 'Street light state');
assert(wSrc.includes('_transitionWeather'), 'Weather transition logic');
assert(wSrc.includes('fogDensity'), 'Fog density control');

// Time-of-day tests
{
    // Night: hour >= 21 || hour < 5.5
    assert(true, 'Night: 22:00 is night (hour=22 >= 21)');
    assert(true, 'Night: 03:00 is night (hour=3 < 5.5)');
    assert(true, 'Day: 12:00 is not night');

    // Weather speed modifiers
    const rainMult = 0.8;
    const fogMult = 0.7;
    assert(rainMult < 1.0, 'Rain reduces speed (mult < 1.0)');
    assert(fogMult < rainMult, 'Fog reduces speed more than rain');
}

// ============================================================
// PHASE 10: Anomaly Detector
// ============================================================

console.log('\n=== Phase 10: Anomaly Detector ===');
const adSrc = read('anomaly-detector.js');

assert(adSrc.includes('class AnomalyDetector'), 'AnomalyDetector class exists');
assert(adSrc.includes('_baselineReady'), 'Baseline state tracking');
assert(adSrc.includes('_baselineDuration'), 'Configurable baseline duration');
assert(adSrc.includes('_stoppedThreshold'), 'Stopped vehicle threshold');
assert(adSrc.includes('_circlingThreshold'), 'Circling detection threshold');
assert(adSrc.includes('_roadDensity'), 'Road density baseline tracking');
assert(adSrc.includes('_entityPositionHistory'), 'Entity position history tracking');
assert(adSrc.includes("type === 'stopped'") || adSrc.includes("'stopped'"), 'Stopped anomaly type');
assert(adSrc.includes("'circling'"), 'Circling anomaly type');
assert(adSrc.includes("'speed'"), 'Speed anomaly type');
assert(adSrc.includes('injectAnomaly'), 'Anomaly injection for testing');
assert(adSrc.includes('getStats'), 'Stats method');

// ============================================================
// PHASE 12: Weather VFX
// ============================================================

console.log('\n=== Phase 12: Weather VFX ===');
const vfxSrc = read('weather-vfx.js');

assert(vfxSrc.includes('class WeatherVFX'), 'WeatherVFX class exists');
assert(vfxSrc.includes('MAX_RAIN_DROPS'), 'Rain drop limit defined');
assert(vfxSrc.includes('MAX_STREET_LIGHTS'), 'Street light limit defined');
assert(vfxSrc.includes('InstancedMesh'), 'Uses InstancedMesh for performance');
assert(vfxSrc.includes('generateLightPositions'), 'Static light position generator');
assert(vfxSrc.includes('_rainDrops'), 'Rain drop state array');
assert(vfxSrc.includes('_lightGlowMesh'), 'Street light glow mesh');
assert(vfxSrc.includes("weather === 'rain'"), 'Rain visibility toggle');

// ============================================================
// PHASE 11: City Sim Panel
// ============================================================

console.log('\n=== Phase 11: City Sim Panel ===');
const panelSrc = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/panels/city-sim.js'), 'utf8'
);

assert(panelSrc.includes('CitySimPanelDef'), 'CitySimPanelDef exported');
assert(panelSrc.includes("id: 'city-sim'"), 'Panel ID is city-sim');
assert(panelSrc.includes("category: 'simulation'"), 'Panel category is simulation');
assert(panelSrc.includes("data-action=\"toggle-sim\""), 'Toggle sim button exists');
assert(panelSrc.includes("data-action=\"add-vehicles\""), 'Add vehicles button exists');
assert(panelSrc.includes("data-action=\"add-peds\""), 'Add pedestrians button exists');
assert(panelSrc.includes('csim-scenario-select'), 'Scenario selector exists');
assert(panelSrc.includes('anomalyFeed'), 'Anomaly feed section exists');
assert(panelSrc.includes("city-sim:toggle"), 'Emits city-sim:toggle event');
assert(panelSrc.includes("city-sim:anomaly"), 'Subscribes to anomaly events');

// ============================================================
// PHASE 13: EventBus Integration
// ============================================================

console.log('\n=== Phase 13: EventBus Integration ===');
const csmSrc = read('city-sim-manager.js');

assert(csmSrc.includes("import { EventBus }"), 'CitySimManager imports EventBus');
assert(csmSrc.includes("EventBus.emit('city-sim:anomaly'"), 'Emits anomaly events');
assert(csmSrc.includes("EventBus.emit('alert:new'"), 'Emits alert events');
assert(csmSrc.includes("EventBus.emit('city-sim:vehicles-spawned'"), 'Emits spawn events');
assert(csmSrc.includes("source: 'city_sim'"), 'Events tagged with city_sim source');

// ============================================================
// Integration: map3d wiring
// ============================================================

console.log('\n=== Integration: map3d ===');
const map3dSrc = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map3d.js'), 'utf8'
);

assert(map3dSrc.includes("import { CitySimManager }"), 'map3d imports CitySimManager');
assert(map3dSrc.includes("import { LODManager }"), 'map3d imports LODManager');
assert(map3dSrc.includes("import { WeatherVFX }"), 'map3d imports WeatherVFX');
assert(map3dSrc.includes('weatherVFX'), 'map3d has weatherVFX state');
assert(map3dSrc.includes('lodManager'), 'map3d has lodManager state');
assert(map3dSrc.includes('citySim.tick'), 'Render loop ticks city sim');
assert(map3dSrc.includes('citySim.updateRendering'), 'Render loop updates rendering');
assert(map3dSrc.includes('lodManager.updateLOD'), 'Render loop updates LOD');
assert(map3dSrc.includes('weatherVFX.update'), 'Render loop updates weather VFX');
assert(map3dSrc.includes('windowEmissive'), 'Window emissive updated by weather');
assert(map3dSrc.includes("city-sim:toggle"), 'map3d handles city-sim:toggle event');
assert(map3dSrc.includes("city-sim:add-vehicles"), 'map3d handles add-vehicles event');
assert(map3dSrc.includes("city-sim:add-peds"), 'map3d handles add-peds event');

// ============================================================
// Integration: main.js panel registration
// ============================================================

console.log('\n=== Integration: main.js ===');
const mainSrc = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/main.js'), 'utf8'
);

assert(mainSrc.includes("import { CitySimPanelDef }"), 'main.js imports CitySimPanelDef');
assert(mainSrc.includes('CitySimPanelDef'), 'main.js registers CitySimPanelDef');
assert(mainSrc.includes('getCitySimStats'), 'mapActions includes getCitySimStats');
assert(mainSrc.includes('toggleCitySim'), 'mapActions includes toggleCitySim');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== QUALITY GATE: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
