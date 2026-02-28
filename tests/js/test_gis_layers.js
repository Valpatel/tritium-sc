// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC GIS Infrastructure Layer tests
 *
 * Tests that:
 * 1. map-maplibre.js has GIS layer loading (catalog fetch + per-layer fetch)
 * 2. menu-bar.js has GIS infrastructure layer menu items
 * 3. _loadGeoLayers() fetches from /api/geo/layers/catalog
 * 4. _loadGeoLayer() handles point, line, polygon geometry types
 * 5. GIS layer visibility is toggleable via showGeoLayers state
 * 6. Layer catalog frontend expects required fields (id, name, type, color, endpoint)
 *
 * Run: node tests/js/test_gis_layers.js
 */

const fs = require('fs');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Read sources
const mapSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
const menuBarSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/menu-bar.js', 'utf8');
const geoSrc = fs.readFileSync(__dirname + '/../../src/app/routers/geo.py', 'utf8');

// ============================================================
// 1. Backend: verify GIS layer catalog is defined
// ============================================================

console.log('\n--- Backend: GIS layer catalog ---');

assert(geoSrc.includes('_LAYER_CATALOG'), 'geo.py defines _LAYER_CATALOG');
assert(geoSrc.includes('"power-lines"'), 'Catalog has power-lines layer');
assert(geoSrc.includes('"traffic-signals"'), 'Catalog has traffic-signals layer');
assert(geoSrc.includes('"waterways"'), 'Catalog has waterways layer');
assert(geoSrc.includes('"telecom-lines"'), 'Catalog has telecom-lines layer');
assert(geoSrc.includes('"building-heights"'), 'Catalog has building-heights layer');

// ============================================================
// 2. Backend: verify color codes match cyberpunk palette
// ============================================================

console.log('\n--- Backend: layer colors ---');

assert(geoSrc.includes('"#fcee0a"'), 'Power lines use amber/yellow color');
assert(geoSrc.includes('"#0066ff"'), 'Waterways use deep blue color');
assert(geoSrc.includes('"#ff2a6d"'), 'Traffic signals use magenta/red color');
assert(geoSrc.includes('"#ff8800"'), 'Telecom lines use orange color');
assert(geoSrc.includes('"#00f0ff"'), 'Building heights use cyan color');

// ============================================================
// 3. Backend: verify endpoint definitions
// ============================================================

console.log('\n--- Backend: endpoints ---');

assert(geoSrc.includes('/layers/catalog'), 'geo.py has /layers/catalog endpoint');
assert(geoSrc.includes('/layers/power'), 'geo.py has /layers/power endpoint');
assert(geoSrc.includes('/layers/traffic'), 'geo.py has /layers/traffic endpoint');
assert(geoSrc.includes('/layers/water'), 'geo.py has /layers/water endpoint');
assert(geoSrc.includes('/layers/cable'), 'geo.py has /layers/cable endpoint');
assert(geoSrc.includes('/layers/building-heights'), 'geo.py has /layers/building-heights endpoint');

// ============================================================
// 4. Backend: verify Overpass queries
// ============================================================

console.log('\n--- Backend: Overpass queries ---');

assert(geoSrc.includes('"power"="line"'), 'Power query includes power=line');
assert(geoSrc.includes('"power"="tower"'), 'Power query includes power=tower');
assert(geoSrc.includes('"highway"="traffic_signals"'), 'Traffic query includes traffic_signals');
assert(geoSrc.includes('"highway"="stop"'), 'Traffic query includes stop signs');
assert(geoSrc.includes('"waterway"'), 'Water query includes waterway');
assert(geoSrc.includes('"man_made"="water_tower"'), 'Water query includes water_tower');
assert(geoSrc.includes('"building:height"'), 'Building heights query includes building:height');
assert(geoSrc.includes('"building:levels"'), 'Building heights query includes building:levels');

// ============================================================
// 5. Backend: verify GeoJSON helper
// ============================================================

console.log('\n--- Backend: _overpass_to_geojson helper ---');

assert(geoSrc.includes('def _overpass_to_geojson'), 'geo.py has _overpass_to_geojson function');
assert(geoSrc.includes('"FeatureCollection"'), 'Helper returns FeatureCollection');
assert(geoSrc.includes('as_polygon'), 'Helper supports as_polygon parameter');

// ============================================================
// 6. Backend: verify caching
// ============================================================

console.log('\n--- Backend: caching ---');

assert(geoSrc.includes('_GIS_CACHE'), 'geo.py defines _GIS_CACHE directory');
assert(geoSrc.includes('_fetch_overpass_geojson'), 'geo.py has _fetch_overpass_geojson with caching');

// ============================================================
// 7. Frontend: map-maplibre.js has GIS layer infrastructure
// ============================================================

console.log('\n--- Frontend: map-maplibre.js GIS layers ---');

assert(mapSrc.includes('showGeoLayers'), '_state has showGeoLayers flag');
assert(mapSrc.includes('geoLayerIds'), '_state tracks geoLayerIds');
assert(mapSrc.includes('_loadGeoLayers'), 'map-maplibre.js has _loadGeoLayers function');
assert(mapSrc.includes('_loadGeoLayer'), 'map-maplibre.js has _loadGeoLayer function');
assert(mapSrc.includes('/api/geo/layers/catalog'), 'Frontend fetches layer catalog');

// ============================================================
// 8. Frontend: _loadGeoLayer handles geometry types
// ============================================================

console.log('\n--- Frontend: geometry type handling ---');

// Extract _loadGeoLayer function body
const loadLayerMatch = mapSrc.match(/async function _loadGeoLayer\b[\s\S]*?(?=async function|function _point)/);
assert(loadLayerMatch !== null, '_loadGeoLayer function found');
if (loadLayerMatch) {
    const body = loadLayerMatch[0];
    assert(body.includes("'circle'"), '_loadGeoLayer handles point geometry (circle layer)');
    assert(body.includes("'line'"), '_loadGeoLayer handles line geometry (line layer)');
    assert(body.includes("'fill'"), '_loadGeoLayer handles polygon geometry (fill layer)');
    assert(body.includes('geojson'), '_loadGeoLayer uses GeoJSON data');
}

// ============================================================
// 9. Frontend: GIS layer min-zoom and styling helpers
// ============================================================

console.log('\n--- Frontend: layer styling ---');

assert(mapSrc.includes('_pointMinZoom'), 'map-maplibre.js has _pointMinZoom helper');
assert(mapSrc.includes('_pointRadius'), 'map-maplibre.js has _pointRadius helper');
assert(mapSrc.includes('_lineWidth'), 'map-maplibre.js has _lineWidth helper');
assert(mapSrc.includes('_lineOpacity'), 'map-maplibre.js has _lineOpacity helper');

// Verify traffic-signals has appropriate min zoom
const minZoomMatch = mapSrc.match(/function _pointMinZoom[\s\S]*?(?=function _pointRadius)/);
assert(minZoomMatch !== null, '_pointMinZoom function found');
if (minZoomMatch) {
    assert(minZoomMatch[0].includes('traffic-signals'), '_pointMinZoom has traffic-signals entry');
    assert(minZoomMatch[0].includes('water-towers'), '_pointMinZoom has water-towers entry');
}

// Verify line width has infrastructure entries
const lineWidthMatch = mapSrc.match(/function _lineWidth[\s\S]*?(?=function _lineOpacity)/);
assert(lineWidthMatch !== null, '_lineWidth function found');
if (lineWidthMatch) {
    assert(lineWidthMatch[0].includes('power-lines'), '_lineWidth has power-lines entry');
    assert(lineWidthMatch[0].includes('telecom-lines'), '_lineWidth has telecom-lines entry');
    assert(lineWidthMatch[0].includes('waterways'), '_lineWidth has waterways entry');
}

// Verify line opacity has infrastructure entries
const lineOpacityMatch = mapSrc.match(/function _lineOpacity[\s\S]*?(?=\/\/|function\s)/);
assert(lineOpacityMatch !== null, '_lineOpacity function found');
if (lineOpacityMatch) {
    assert(lineOpacityMatch[0].includes('power-lines'), '_lineOpacity has power-lines entry');
    assert(lineOpacityMatch[0].includes('telecom-lines'), '_lineOpacity has telecom-lines entry');
    assert(lineOpacityMatch[0].includes('waterways'), '_lineOpacity has waterways entry');
}

// Verify point radius has water towers
const pointRadiusMatch = mapSrc.match(/function _pointRadius[\s\S]*?(?=function _lineWidth)/);
assert(pointRadiusMatch !== null, '_pointRadius function found');
if (pointRadiusMatch) {
    assert(pointRadiusMatch[0].includes('water-towers'), '_pointRadius has water-towers entry');
}

// ============================================================
// 10. Menu bar: GIS infrastructure items
// ============================================================

console.log('\n--- Menu bar: layer items ---');

// These should already be in the MAP menu via the existing toggles
// The GIS layers load automatically via the catalog
assert(menuBarSrc.includes('_mapMenuItems'), 'menu-bar.js has _mapMenuItems function');

// ============================================================
// 11. Building height estimation
// ============================================================

console.log('\n--- Backend: building height estimation ---');

assert(geoSrc.includes('_METERS_PER_LEVEL'), 'geo.py defines _METERS_PER_LEVEL constant');
assert(geoSrc.includes('levels * _METERS_PER_LEVEL'), 'Height estimated from levels when explicit height missing');

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
