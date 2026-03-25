#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Tests for city simulation scenario loader.
 */

const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; console.log(`PASS: ${msg}`); }
    else { failed++; console.log(`FAIL: ${msg}`); }
}

// ============================================================
// SECTION 1: Source Structure
// ============================================================

console.log('--- Scenario Loader Module ---');
const loaderSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/sim/scenario-loader.js'), 'utf8'
);

assert(loaderSource.includes('BUILT_IN_SCENARIOS'), 'BUILT_IN_SCENARIOS exported');
assert(loaderSource.includes('export function loadScenario'), 'loadScenario function exported');
assert(loaderSource.includes('export function exportScenario'), 'exportScenario function exported');
assert(loaderSource.includes('export function getScenarioById'), 'getScenarioById function exported');

// ============================================================
// SECTION 2: Scenario Data Validation
// ============================================================

console.log('\n--- Scenario Data ---');

// Extract scenario IDs from source
const idMatches = loaderSource.match(/id:\s*'([^']+)'/g);
const scenarioIds = idMatches ? idMatches.map(m => m.match(/'([^']+)'/)[1]) : [];

assert(scenarioIds.length >= 4, `At least 4 built-in scenarios (found ${scenarioIds.length})`);
assert(scenarioIds.includes('rush_hour'), 'rush_hour scenario exists');
assert(scenarioIds.includes('night_patrol'), 'night_patrol scenario exists');
assert(scenarioIds.includes('lunch_rush'), 'lunch_rush scenario exists');
assert(scenarioIds.includes('emergency'), 'emergency scenario exists');

// Check required fields in each scenario
const requiredFields = ['id', 'name', 'description', 'vehicles', 'pedestrians', 'startTime', 'timeScale', 'weather'];
for (const field of requiredFields) {
    const regex = new RegExp(`${field}:`, 'g');
    const count = (loaderSource.match(regex) || []).length;
    // Each scenario should have this field, plus possible function refs
    assert(count >= scenarioIds.length, `Field '${field}' present in all scenarios (${count} occurrences)`);
}

// ============================================================
// SECTION 3: loadScenario Logic
// ============================================================

console.log('\n--- loadScenario Logic ---');

assert(loaderSource.includes('clearVehicles'), 'loadScenario calls clearVehicles');
assert(loaderSource.includes('spawnVehicles'), 'loadScenario calls spawnVehicles');
assert(loaderSource.includes('spawnPedestrians'), 'loadScenario calls spawnPedestrians');
assert(loaderSource.includes('spawnEmergency'), 'loadScenario handles emergency vehicles');
assert(loaderSource.includes('simHour'), 'loadScenario sets simHour');
assert(loaderSource.includes('timeScale'), 'loadScenario sets timeScale');
assert(loaderSource.includes('sensorBridge'), 'loadScenario handles sensorBridge');

// Guard check
assert(loaderSource.includes('!citySim || !citySim.loaded'), 'loadScenario checks citySim loaded state');

// ============================================================
// SECTION 4: exportScenario Logic
// ============================================================

console.log('\n--- exportScenario Logic ---');

assert(loaderSource.includes('custom_'), 'exportScenario generates custom ID');
assert(loaderSource.includes('isEmergency'), 'exportScenario counts emergency vehicles');

// ============================================================
// SECTION 5: Panel Integration
// ============================================================

console.log('\n--- Panel Integration ---');
const panelSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/panels/city-sim.js'), 'utf8'
);

assert(panelSource.includes("import { BUILT_IN_SCENARIOS }"), 'Panel imports BUILT_IN_SCENARIOS');
assert(panelSource.includes("city-sim:load-scenario"), 'Panel emits city-sim:load-scenario event');
assert(panelSource.includes('BUILT_IN_SCENARIOS.map'), 'Panel dynamically renders scenario options');

// ============================================================
// SECTION 6: Map3D Integration
// ============================================================

console.log('\n--- Map3D Integration ---');
const map3dSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map3d.js'), 'utf8'
);

assert(map3dSource.includes("import { getScenarioById, loadScenario }"), 'Map3D imports scenario loader');
assert(map3dSource.includes("city-sim:load-scenario"), 'Map3D handles city-sim:load-scenario event');
assert(map3dSource.includes("getScenarioById(scenarioId)"), 'Map3D looks up scenario by ID');

// ============================================================
// SECTION 7: CitySimManager Integration
// ============================================================

console.log('\n--- CitySimManager Integration ---');
const managerSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/sim/city-sim-manager.js'), 'utf8'
);

assert(managerSource.includes("import { loadScenario as _loadScenario, getScenarioById }"), 'Manager imports scenario loader');
assert(managerSource.includes('loadScenario(scenario)'), 'Manager has loadScenario method');

// ============================================================
// Done
// ============================================================

console.log(`\n=== Scenario Loader: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
