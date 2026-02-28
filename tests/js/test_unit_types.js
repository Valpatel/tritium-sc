// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Unit Type Registry tests
 * Run: node tests/js/test_unit_types.js
 *
 * Tests the new unit-types/ package:
 * - Registry population (all types registered)
 * - getType() lookup
 * - resolveTypeId() fuzzy matching
 * - getIconLetter() and getVisionRadius() helpers
 * - Type property validation
 * - Draw function presence
 */

const fs = require('fs');
const vm = require('vm');
const path = require('path');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Load all unit-types files into a single sandbox
// ============================================================

const BASE_DIR = path.join(__dirname, '..', '..', 'frontend', 'js', 'command', 'unit-types');

// Read files in dependency order
const files = [
    'base.js',
    'registry.js',
    'rover.js',
    'drone.js',
    'turret.js',
    'tank.js',
    'hostile-person.js',
    'neutral-person.js',
    'sensor.js',
    'camera.js',
];

// Build a combined script that strips ES module syntax
// and emulates import/export with a simple module registry
let combined = `
var _modules = {};
var _exports = {};
var _registry_api = {};
var performance = { now: function() { return 1000; } };

// Emulate UnitType base
`;

for (const file of files) {
    const filePath = path.join(BASE_DIR, file);
    let code = fs.readFileSync(filePath, 'utf8');

    // Strip import statements
    code = code.replace(/import\s+\{[^}]*\}\s+from\s+'[^']*';/g, '');
    code = code.replace(/import\s+'[^']*';/g, '');
    code = code.replace(/import\s+\w+\s+from\s+'[^']*';/g, '');

    // Strip export default
    code = code.replace(/export\s+default\s+\w+;/g, '');

    // Strip export from class/function declarations
    code = code.replace(/export\s+class\s+/g, 'class ');
    code = code.replace(/export\s+function\s+/g, 'function ');

    // Strip re-export blocks
    code = code.replace(/export\s+\{[\s\S]*?\}\s*from\s*'[^']*';/g, '');

    combined += `\n// --- ${file} ---\n${code}\n`;
}

// Add accessors for test code
combined += `
_exports.getType = typeof getType === 'function' ? getType : null;
_exports.allTypes = typeof allTypes === 'function' ? allTypes : null;
_exports.getIconLetter = typeof getIconLetter === 'function' ? getIconLetter : null;
_exports.getVisionRadius = typeof getVisionRadius === 'function' ? getVisionRadius : null;
_exports.getCotType = typeof getCotType === 'function' ? getCotType : null;
_exports.resolveTypeId = typeof resolveTypeId === 'function' ? resolveTypeId : null;
_exports.registerType = typeof registerType === 'function' ? registerType : null;
_exports.UnitType = typeof UnitType === 'function' ? UnitType : null;
`;

const ctx = vm.createContext({
    Math, Date, console, Map, Array, Object, Number, Infinity, Boolean,
    parseInt, parseFloat, isNaN, isFinite, undefined, null: null,
    performance: { now: () => 1000 },
});

vm.runInContext(combined, ctx);

const { getType, allTypes, getIconLetter, getVisionRadius, getCotType, resolveTypeId, registerType, UnitType } = ctx._exports;

// ============================================================
// Test: Functions exist
// ============================================================

console.log('\n--- Registry API ---');

assert(typeof getType === 'function', 'getType is exported as a function');
assert(typeof allTypes === 'function', 'allTypes is exported as a function');
assert(typeof getIconLetter === 'function', 'getIconLetter is exported as a function');
assert(typeof getVisionRadius === 'function', 'getVisionRadius is exported as a function');
assert(typeof resolveTypeId === 'function', 'resolveTypeId is exported as a function');
assert(typeof registerType === 'function', 'registerType is exported as a function');

// ============================================================
// Test: Registry population
// ============================================================

console.log('\n--- Registry Population ---');

const types = allTypes();
assert(Array.isArray(types), 'allTypes() returns an array');
assert(types.length >= 8, `allTypes() has at least 8 types (got ${types.length})`);

// Check known types are registered
const expectedTypes = ['rover', 'drone', 'turret', 'tank', 'hostile_person', 'neutral_person', 'sensor', 'camera'];
for (const typeId of expectedTypes) {
    const t = getType(typeId);
    assert(t !== null, `getType("${typeId}") returns a class`);
}

// Unknown type returns null
assert(getType('nonexistent') === null, 'getType("nonexistent") returns null');

// No duplicate typeIds
const typeIds = types.map(t => t.typeId);
const uniqueIds = new Set(typeIds);
assert(uniqueIds.size === typeIds.length, `No duplicate typeIds (${typeIds.length} types, ${uniqueIds.size} unique)`);

// ============================================================
// Test: Type properties
// ============================================================

console.log('\n--- Type Properties ---');

for (const t of types) {
    assert(typeof t.typeId === 'string' && t.typeId.length > 0, `${t.typeId || '??'}: has non-empty typeId`);
    assert(typeof t.displayName === 'string' && t.displayName.length > 0, `${t.typeId}: has non-empty displayName`);
    assert(typeof t.iconLetter === 'string' && t.iconLetter.length === 1, `${t.typeId}: iconLetter is single char ("${t.iconLetter}")`);
    assert(typeof t.visionRadius === 'number' && t.visionRadius > 0, `${t.typeId}: visionRadius > 0 (${t.visionRadius})`);
    assert(typeof t.draw === 'function', `${t.typeId}: has draw() function`);
}

// ============================================================
// Test: Specific icon letters
// ============================================================

console.log('\n--- Icon Letters ---');

assert(getIconLetter('rover') === 'R', 'getIconLetter("rover") === "R"');
assert(getIconLetter('drone') === 'D', 'getIconLetter("drone") === "D"');
assert(getIconLetter('turret') === 'T', 'getIconLetter("turret") === "T"');
assert(getIconLetter('hostile_person') === 'H', 'getIconLetter("hostile_person") === "H"');
assert(getIconLetter('neutral_person') === 'P', 'getIconLetter("neutral_person") === "P"');
assert(getIconLetter('sensor') === 'S', 'getIconLetter("sensor") === "S"');
assert(getIconLetter('camera') === 'C', 'getIconLetter("camera") === "C"');
assert(getIconLetter('nonexistent') === '?', 'getIconLetter("nonexistent") === "?"');

// ============================================================
// Test: Vision radii
// ============================================================

console.log('\n--- Vision Radii ---');

assert(getVisionRadius('rover') === 40, 'getVisionRadius("rover") === 40');
assert(getVisionRadius('drone') === 60, 'getVisionRadius("drone") === 60');
assert(getVisionRadius('turret') === 50, 'getVisionRadius("turret") === 50');
assert(getVisionRadius('hostile_person') === 20, 'getVisionRadius("hostile_person") === 20');
assert(getVisionRadius('neutral_person') === 15, 'getVisionRadius("neutral_person") === 15');
assert(getVisionRadius('camera') === 30, 'getVisionRadius("camera") === 30');
assert(getVisionRadius('sensor') === 30, 'getVisionRadius("sensor") === 30');
assert(getVisionRadius('tank') === 45, 'getVisionRadius("tank") === 45');
assert(getVisionRadius('nonexistent') === 25, 'getVisionRadius("nonexistent") defaults to 25');

// ============================================================
// Test: resolveTypeId() fuzzy matching
// ============================================================

console.log('\n--- resolveTypeId() ---');

// Direct matches
assert(resolveTypeId('rover') === 'rover', 'resolveTypeId("rover") direct match');
assert(resolveTypeId('drone') === 'drone', 'resolveTypeId("drone") direct match');
assert(resolveTypeId('turret') === 'turret', 'resolveTypeId("turret") direct match');

// Fuzzy matches for rover variants
assert(resolveTypeId('patrol_rover') === 'rover', 'resolveTypeId("patrol_rover") -> "rover"');
assert(resolveTypeId('interceptor_bot') === 'rover', 'resolveTypeId("interceptor_bot") -> "rover"');

// Fuzzy matches for turret variants
assert(resolveTypeId('sentry_turret') === 'turret', 'resolveTypeId("sentry_turret") -> "turret"');
assert(resolveTypeId('heavy_turret') === 'turret', 'resolveTypeId("heavy_turret") -> "turret"');

// Fuzzy matches for drone variants
assert(resolveTypeId('recon_drone') === 'drone', 'resolveTypeId("recon_drone") -> "drone"');
assert(resolveTypeId('heavy_drone') === 'drone', 'resolveTypeId("heavy_drone") -> "drone"');

// Tank/vehicle matching
assert(resolveTypeId('army_tank') === 'tank', 'resolveTypeId("army_tank") -> "tank"');
assert(resolveTypeId('truck') === 'tank', 'resolveTypeId("truck") -> "tank"');

// Sensor/camera matching
assert(resolveTypeId('motion_sensor') === 'sensor', 'resolveTypeId("motion_sensor") -> "sensor"');
assert(resolveTypeId('ptz_camera') === 'sensor', 'resolveTypeId("ptz_camera") -> "sensor"');

// Person with alliance
assert(resolveTypeId('person', 'hostile') === 'hostile_person', 'resolveTypeId("person", "hostile") -> "hostile_person"');
assert(resolveTypeId('person', 'neutral') === 'neutral_person', 'resolveTypeId("person", "neutral") -> "neutral_person"');

// hostile_kid mapping
assert(resolveTypeId('hostile_kid') === 'hostile_person', 'resolveTypeId("hostile_kid") -> "hostile_person"');

// Mesh/meshtastic mapping
assert(resolveTypeId('mesh_radio') === 'sensor', 'resolveTypeId("mesh_radio") -> "sensor"');
assert(resolveTypeId('meshtastic') === 'sensor', 'resolveTypeId("meshtastic") -> "sensor"');

// Unknown type stays unchanged
assert(resolveTypeId('unknown_thing') === 'unknown_thing', 'resolveTypeId("unknown_thing") returns raw type');

// ============================================================
// Test: Draw functions produce canvas calls
// ============================================================

console.log('\n--- Draw Functions ---');

function createMockCtx() {
    const calls = [];
    const state = {
        fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1.0,
    };
    const stateStack = [];
    return {
        calls,
        get fillStyle() { return state.fillStyle; },
        set fillStyle(v) { state.fillStyle = v; },
        get strokeStyle() { return state.strokeStyle; },
        set strokeStyle(v) { state.strokeStyle = v; },
        get lineWidth() { return state.lineWidth; },
        set lineWidth(v) { state.lineWidth = v; },
        get globalAlpha() { return state.globalAlpha; },
        set globalAlpha(v) { state.globalAlpha = v; },
        save() { stateStack.push({ ...state }); calls.push({ fn: 'save' }); },
        restore() { const s = stateStack.pop(); if (s) Object.assign(state, s); calls.push({ fn: 'restore' }); },
        beginPath() { calls.push({ fn: 'beginPath' }); },
        closePath() { calls.push({ fn: 'closePath' }); },
        moveTo(x, y) { calls.push({ fn: 'moveTo', x, y }); },
        lineTo(x, y) { calls.push({ fn: 'lineTo', x, y }); },
        arc(x, y, r, start, end) { calls.push({ fn: 'arc', x, y, r }); },
        fill() { calls.push({ fn: 'fill', fillStyle: state.fillStyle }); },
        stroke() { calls.push({ fn: 'stroke', strokeStyle: state.strokeStyle }); },
        fillRect(x, y, w, h) { calls.push({ fn: 'fillRect', x, y, w, h }); },
        quadraticCurveTo(cpx, cpy, x, y) { calls.push({ fn: 'quadraticCurveTo' }); },
    };
}

for (const t of types) {
    const mockCtx = createMockCtx();
    t.draw(mockCtx, 1.0, '#05ffa1');
    const drawCalls = mockCtx.calls.filter(c => c.fn === 'fill' || c.fn === 'stroke' || c.fn === 'fillRect');
    assert(drawCalls.length > 0, `${t.typeId}: draw() produces canvas draw calls (${drawCalls.length})`);
}

// ============================================================
// Test: Different types produce different draw patterns
// ============================================================

console.log('\n--- Distinct Draw Patterns ---');

const drawPatterns = {};
for (const typeId of ['rover', 'drone', 'turret', 'hostile_person', 'tank', 'sensor']) {
    const t = getType(typeId);
    const mockCtx = createMockCtx();
    t.draw(mockCtx, 1.0, '#05ffa1');
    drawPatterns[typeId] = mockCtx.calls.map(c => c.fn).join(',');
}

const uniquePatterns = new Set(Object.values(drawPatterns));
assert(uniquePatterns.size >= 5, `At least 5 distinct draw patterns (got ${uniquePatterns.size})`);

// ============================================================
// Test: CoT type codes
// ============================================================

console.log('\n--- CoT Type Codes ---');

assert(typeof getCotType === 'function', 'getCotType is exported as a function');

// Every registered type has a cotType string starting with 'a-'
for (const t of types) {
    assert(typeof t.cotType === 'string', `${t.typeId}: cotType is a string`);
    assert(t.cotType.startsWith('a-'), `${t.typeId}: cotType starts with "a-" (got "${t.cotType}")`);
}

// Specific cotType values match Python definitions
assert(getType('rover').cotType === 'a-f-G-E-V-A-L', 'rover cotType is a-f-G-E-V-A-L');
assert(getType('drone').cotType === 'a-f-A-M-F-Q', 'drone cotType is a-f-A-M-F-Q');
assert(getType('turret').cotType === 'a-f-G-E-W-D', 'turret cotType is a-f-G-E-W-D');
assert(getType('tank').cotType === 'a-f-G-E-V-A-T', 'tank cotType is a-f-G-E-V-A-T');
assert(getType('hostile_person').cotType === 'a-h-G-U-C-I', 'hostile_person cotType is a-h-G-U-C-I');
assert(getType('neutral_person').cotType === 'a-n-G-U-C', 'neutral_person cotType is a-n-G-U-C');
assert(getType('sensor').cotType === 'a-f-G-E-S-E', 'sensor cotType is a-f-G-E-S-E');
assert(getType('camera').cotType === 'a-f-G-E-S-E', 'camera cotType is a-f-G-E-S-E');

// getCotType() helper returns correct values
assert(getCotType('rover') === 'a-f-G-E-V-A-L', 'getCotType("rover") returns correct value');
assert(getCotType('drone') === 'a-f-A-M-F-Q', 'getCotType("drone") returns correct value');
assert(getCotType('turret') === 'a-f-G-E-W-D', 'getCotType("turret") returns correct value');

// getCotType() returns default for unknown types
assert(getCotType('nonexistent') === 'a-u-G', 'getCotType("nonexistent") returns default "a-u-G"');
assert(getCotType('unknown_thing') === 'a-u-G', 'getCotType("unknown_thing") returns default "a-u-G"');

// getCotType() fuzzy resolution works
assert(getCotType('heavy_turret') === 'a-f-G-E-W-D', 'getCotType("heavy_turret") resolves to turret cotType');
assert(getCotType('recon_drone') === 'a-f-A-M-F-Q', 'getCotType("recon_drone") resolves to drone cotType');

// Base UnitType default cotType
assert(UnitType.cotType === 'a-u-G', 'UnitType base class cotType is "a-u-G"');

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(50)}`);
console.log(`Unit Types: ${passed} passed, ${failed} failed`);
console.log(`${'='.repeat(50)}\n`);

process.exit(failed > 0 ? 1 : 0);
