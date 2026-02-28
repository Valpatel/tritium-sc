// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Geo coordinate transform tests
 * Run: node tests/js/test_geo_math.js
 *
 * Tests: latlngToGame, gameToLatlng, tileForLatlng, tileBounds,
 *        metersPerPixel, _estimateBuildingHeight, initGeo roundtrip.
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}

// Load geo.js into a sandboxed context
const code = fs.readFileSync(__dirname + '/../../frontend/js/geo.js', 'utf8');
const _window = {};
const ctx = vm.createContext({
    Math, Date, console, Array, Object, Number, Infinity, parseFloat, parseInt, isNaN,
    window: _window,
    navigator: { geolocation: null },
    fetch: () => Promise.reject(new Error('no fetch in tests')),
    Image: function() {},
    Promise,
});
vm.runInContext(code, ctx);

const geo = _window.geo;

// ============================================================
// initGeo
// ============================================================

console.log('\n--- initGeo ---');

geo.initGeo(37.7749, -122.4194);  // San Francisco
const state = geo.getGeoState();
assert(state.initialized === true, 'geo initialized');
assertClose(state.centerLat, 37.7749, 0.0001, 'center lat stored');
assertClose(state.centerLng, -122.4194, 0.0001, 'center lng stored');
assert(state.metersPerDegLng > 0, 'metersPerDegLng positive');
assert(state.metersPerDegLng < geo.METERS_PER_DEG_LAT, 'metersPerDegLng < metersPerDegLat (latitude contraction)');

// ============================================================
// latlngToGame — center maps to origin
// ============================================================

console.log('\n--- latlngToGame ---');

const origin = geo.latlngToGame(37.7749, -122.4194);
assertClose(origin.x, 0, 0.01, 'center lat/lng → x=0');
assertClose(origin.y, 0, 0.01, 'center lat/lng → y=0');

// North = +Y
const north = geo.latlngToGame(37.7759, -122.4194);  // 0.001 deg north
assert(north.y > 0, 'north of center → positive Y');
assertClose(north.x, 0, 0.01, 'same longitude → x=0');

// East = +X
const east = geo.latlngToGame(37.7749, -122.4184);  // 0.001 deg east
assert(east.x > 0, 'east of center → positive X');
assertClose(east.y, 0, 0.01, 'same latitude → y=0');

// South = -Y
const south = geo.latlngToGame(37.7739, -122.4194);
assert(south.y < 0, 'south of center → negative Y');

// West = -X
const west = geo.latlngToGame(37.7749, -122.4204);
assert(west.x < 0, 'west of center → negative X');

// Approximate scale: 0.001 deg lat ≈ 111.32 meters
assertClose(north.y, 111.32, 1.0, '0.001° lat ≈ 111m');

// ============================================================
// gameToLatlng — roundtrip
// ============================================================

console.log('\n--- gameToLatlng roundtrip ---');

const testPoints = [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 0, y: 100 },
    { x: -50, y: -50 },
    { x: 200, y: -100 },
];

for (const pt of testPoints) {
    const ll = geo.gameToLatlng(pt.x, pt.y);
    const back = geo.latlngToGame(ll.lat, ll.lng);
    assertClose(back.x, pt.x, 0.01, `roundtrip (${pt.x},${pt.y}) x`);
    assertClose(back.y, pt.y, 0.01, `roundtrip (${pt.x},${pt.y}) y`);
}

// ============================================================
// tileForLatlng
// ============================================================

console.log('\n--- tileForLatlng ---');

// Known tile for (0, 0) at zoom 0 = (0, 0)
const tile00 = geo.tileForLatlng(0, 0, 0);
assert(tile00.x === 0, 'equator prime meridian zoom 0 → x=0');
assert(tile00.y === 0, 'equator prime meridian zoom 0 → y=0');
assert(tile00.z === 0, 'zoom level preserved');

// At zoom 1, world is 2x2 tiles
const tileZ1 = geo.tileForLatlng(0, 0, 1);
assert(tileZ1.x === 1, 'equator prime meridian zoom 1 → x=1');
assert(tileZ1.y === 1, 'equator prime meridian zoom 1 → y=1');

// Negative longitude
const tileWest = geo.tileForLatlng(37.7749, -122.4194, 10);
assert(tileWest.x >= 0 && tileWest.x < 1024, 'SF tile X in range at zoom 10');
assert(tileWest.y >= 0 && tileWest.y < 1024, 'SF tile Y in range at zoom 10');

// Higher zoom = more tiles
const tileZ18 = geo.tileForLatlng(37.7749, -122.4194, 18);
const tileZ19 = geo.tileForLatlng(37.7749, -122.4194, 19);
assert(tileZ19.x >= tileZ18.x * 2 - 1, 'higher zoom → larger tile numbers');

// ============================================================
// tileBounds
// ============================================================

console.log('\n--- tileBounds ---');

const bounds = geo.tileBounds(0, 0, 0);
assertClose(bounds.west, -180, 0.01, 'zoom 0 tile 0,0 west = -180');
assertClose(bounds.east, 180, 0.01, 'zoom 0 tile 0,0 east = 180');
assert(bounds.north > 80, 'zoom 0 tile 0,0 north > 80');
assert(bounds.south < -80, 'zoom 0 tile 0,0 south < -80');

// Zoom 1 — 4 tiles, each covers a quadrant
const boundsNW = geo.tileBounds(0, 0, 1);
const boundsSE = geo.tileBounds(1, 1, 1);
assertClose(boundsNW.west, -180, 0.01, 'NW tile west = -180');
assertClose(boundsNW.east, 0, 0.01, 'NW tile east = 0');
assertClose(boundsSE.west, 0, 0.01, 'SE tile west = 0');
assertClose(boundsSE.east, 180, 0.01, 'SE tile east = 180');
assert(boundsNW.north > boundsSE.north, 'NW tile is north of SE tile');

// ============================================================
// metersPerPixel
// ============================================================

console.log('\n--- metersPerPixel ---');

// At equator, zoom 0: ~156543m/pixel
const mppZ0 = geo.metersPerPixel(0, 0);
assertClose(mppZ0, 156543.03, 1.0, 'zoom 0 equator ≈ 156543 m/px');

// Higher zoom = smaller m/px
const mppZ19 = geo.metersPerPixel(19, 0);
assert(mppZ19 < 1.0, 'zoom 19 < 1 m/px');

// Higher latitude = smaller m/px (Mercator projection)
const mppEq = geo.metersPerPixel(10, 0);
const mppSF = geo.metersPerPixel(10, 37.7749);
assert(mppSF < mppEq, 'SF latitude gives smaller m/px than equator');

// ============================================================
// METERS_PER_DEG_LAT constant
// ============================================================

console.log('\n--- constants ---');

assert(geo.METERS_PER_DEG_LAT === 111320, 'METERS_PER_DEG_LAT = 111320');
assert(geo.TILE_SIZE === 256, 'TILE_SIZE = 256');

// ============================================================
// _estimateBuildingHeight (via loadBuildings internals — test indirectly)
// We can't call _estimateBuildingHeight directly since it's not exported,
// but we can verify the transform logic.
// ============================================================

console.log('\n--- coordinate transform edge cases ---');

// Reinit for London
geo.initGeo(51.5074, -0.1278);
const londonState = geo.getGeoState();
assert(londonState.metersPerDegLng < geo.METERS_PER_DEG_LAT, 'London metersPerDegLng < lat');
// London is at higher latitude than SF, so metersPerDegLng should be smaller
const sfMpdLng = geo.METERS_PER_DEG_LAT * Math.cos(37.7749 * Math.PI / 180);
assert(londonState.metersPerDegLng < sfMpdLng, 'London lng contraction > SF lng contraction');

// Origin check for London
const londonOrigin = geo.latlngToGame(51.5074, -0.1278);
assertClose(londonOrigin.x, 0, 0.01, 'London center → x=0');
assertClose(londonOrigin.y, 0, 0.01, 'London center → y=0');

// Equator special case
geo.initGeo(0, 0);
const eqState = geo.getGeoState();
assertClose(eqState.metersPerDegLng, geo.METERS_PER_DEG_LAT, 1.0,
    'equator: metersPerDegLng ≈ metersPerDegLat');

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(50)}`);
console.log(`Geo math tests: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
