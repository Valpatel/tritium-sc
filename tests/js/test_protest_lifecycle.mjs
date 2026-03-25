// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// End-to-end protest lifecycle test in Node.js.
// Proves: NPC identity → daily routines → protest activation → phase transitions → police → dispersal

import { ProtestEngine } from '../../src/frontend/js/command/sim/protest-engine.js';
import { PHASES } from '../../src/frontend/js/command/sim/protest-scenario.js';
import { buildIdentity } from '../../src/frontend/js/command/sim/identity.js';

let passed = 0;
let failed = 0;

function assert(condition, msg) {
    if (condition) { passed++; console.log(`  PASS: ${msg}`); }
    else { failed++; console.log(`  FAIL: ${msg}`); }
}

// === TEST 1: Identity System ===
console.log('\n=== NPC Identity ===');
const id1 = buildIdentity('ped_0', 'person');
const id2 = buildIdentity('ped_1', 'person');
const id1b = buildIdentity('ped_0', 'person'); // same ID = same identity

assert(id1.fullName && id1.fullName.length > 3, `Identity has name: ${id1.fullName}`);
assert(id1.fullName === id1b.fullName, 'Same ID produces same name (deterministic)');
assert(id1.fullName !== id2.fullName, 'Different IDs produce different names');
assert(id1.bluetoothMac && id1.bluetoothMac.includes(':'), `Has BLE MAC: ${id1.bluetoothMac}`);
assert(id1.phoneModel, `Has phone model: ${id1.phoneModel}`);

const carId = buildIdentity('car_0', 'vehicle');
assert(carId.licensePlate, `Vehicle has plate: ${carId.licensePlate}`);
assert(carId.vehicleDesc, `Vehicle has description: ${carId.vehicleDesc}`);

// === TEST 2: Protest Engine Phases ===
console.log('\n=== Protest Engine Lifecycle ===');
const engine = new ProtestEngine({
    legitimacy: 0.25,
    threshold: 0.1,
    plazaCenter: { x: 0, z: 0 },
    plazaRadius: 30,
});

// Register 50 NPCs with varying hardship
for (let i = 0; i < 50; i++) {
    engine.registerAgent(`ped_${i}`, 0.5 + Math.random() * 0.5, Math.random() * 0.5);
}

engine.start();
assert(engine.active, 'Engine starts active');
assert(engine.currentPhase === PHASES.CALL_TO_ACTION, `Initial phase: ${engine.currentPhase}`);

// Simulate NPCs at the plaza
const positions = [];
for (let i = 0; i < 50; i++) {
    positions.push({ id: `ped_${i}`, x: Math.random() * 10 - 5, z: Math.random() * 10 - 5, type: 'civilian' });
}
// Add police
for (let i = 0; i < 5; i++) {
    positions.push({ id: `cop_${i}`, x: 40, z: -30 + i * 5, type: 'police' });
}

// Run through all phases
const phasesSeen = new Set();
let lastPhase = null;
const phaseTransitions = [];
for (let t = 0; t < 5000; t++) {
    const result = engine.tick(0.1, positions);
    if (result.phase !== lastPhase) {
        phaseTransitions.push({ from: lastPhase, to: result.phase, t: (t * 0.1).toFixed(1) });
        phasesSeen.add(result.phase);
        lastPhase = result.phase;
    }
    if (result.phase === PHASES.NORMAL) break;
}

console.log('  Phase transitions:');
for (const t of phaseTransitions) {
    console.log(`    t=${t.t}s: ${t.from || 'NONE'} → ${t.to}`);
}

assert(phasesSeen.has(PHASES.CALL_TO_ACTION), 'Reached CALL_TO_ACTION');
assert(phasesSeen.has(PHASES.MARCHING), 'Reached MARCHING');
assert(phasesSeen.has(PHASES.ASSEMBLED), 'Reached ASSEMBLED');
assert(phasesSeen.has(PHASES.TENSION), 'Reached TENSION');
assert(phasesSeen.has(PHASES.FIRST_INCIDENT), 'Reached FIRST_INCIDENT');
assert(phasesSeen.has(PHASES.RIOT), 'Reached RIOT');
assert(phasesSeen.has(PHASES.DISPERSAL), 'Reached DISPERSAL');
assert(phasesSeen.has(PHASES.AFTERMATH), 'Reached AFTERMATH');
assert(!engine.active, 'Engine stopped after AFTERMATH');

// === TEST 3: Agent Goals ===
console.log('\n=== Agent Goals by Phase ===');
const engine2 = new ProtestEngine({
    legitimacy: 0.3,
    threshold: 0.1,
    plazaCenter: { x: 100, z: 200 },
    plazaRadius: 25,
});
engine2.registerAgent('test_ped', 0.8, 0.2); // high hardship, low risk aversion
engine2.start();

// Tick once to activate
engine2.tick(0.1, [{ id: 'test_ped', x: 0, z: 0, type: 'civilian' }]);
const goal1 = engine2.getAgentGoal('test_ped');
assert(goal1 !== null, 'Active agent gets a goal');
assert(goal1.action === 'go_to', `CALL_TO_ACTION goal: ${goal1.action}`);
assert(goal1.target.x === 100, 'Goal target is plaza center');

// Advance to RIOT
for (let t = 0; t < 500; t++) {
    engine2.tick(0.1, [{ id: 'test_ped', x: 100, z: 200, type: 'civilian' }]);
    if (engine2.currentPhase === PHASES.RIOT) break;
}
const goal2 = engine2.getAgentGoal('test_ped');
assert(engine2.currentPhase === PHASES.RIOT || engine2.currentPhase === PHASES.FIRST_INCIDENT, `Reached riot/incident phase: ${engine2.currentPhase}`);
assert(goal2 !== null, 'Agent has goal during riot');

// === TEST 4: Debug Info ===
console.log('\n=== Debug Info ===');
const debug = engine2.getDebugInfo();
assert(typeof debug.phase === 'string', `Phase: ${debug.phase}`);
assert(typeof debug.legitimacy === 'string', `Legitimacy: ${debug.legitimacy}`);
assert(typeof debug.active === 'number', `Active count: ${debug.active}`);

// === SUMMARY ===
console.log(`\n${'='.repeat(40)}`);
console.log(`RESULTS: ${passed} passed, ${failed} failed`);
if (failed === 0) {
    console.log('ALL TESTS PASSED');
} else {
    console.log('FAILURES DETECTED');
    process.exit(1);
}
