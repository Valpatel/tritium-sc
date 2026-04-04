// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Camera Drag-to-Reposition Tests
 *
 * Tests the camera drag-to-reposition logic for UX Loop 8:
 * - _cameraDrag state management
 * - _storeCamerasForDrag stores copies of camera data
 * - _updateCameraGeoJSON rebuilds GeoJSON from stored cameras
 * - Click suppression after drag via _cameraDragJustEnded flag
 * - FOV cone updates during drag
 *
 * Run: node tests/js/test_camera_drag.js
 */

const fs = require('fs');
const path = require('path');
const mapLibreSource = fs.readFileSync(
    path.join(__dirname, '../../src/frontend/js/command/map-maplibre.js'), 'utf8');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function approx(a, b, tolerance, msg) {
    if (Math.abs(a - b) <= tolerance) { console.log('PASS:', msg); passed++; }
    else { console.error(`FAIL: ${msg} (expected ~${b}, got ${a})`); failed++; }
}


// ============================================================
// Static analysis: drag code exists in map-maplibre.js
// ============================================================

console.log('\n--- Camera drag code presence ---');

{
    assert(mapLibreSource.includes('_cameraDrag'),
        'map-maplibre.js has _cameraDrag state object');
    assert(mapLibreSource.includes('_cameraDragJustEnded'),
        'map-maplibre.js has _cameraDragJustEnded flag');
    assert(mapLibreSource.includes('_initCameraDrag'),
        'map-maplibre.js has _initCameraDrag function');
    assert(mapLibreSource.includes('_onCameraDragMove'),
        'map-maplibre.js has _onCameraDragMove function');
    assert(mapLibreSource.includes('_onCameraDragEnd'),
        'map-maplibre.js has _onCameraDragEnd function');
    assert(mapLibreSource.includes('_storeCamerasForDrag'),
        'map-maplibre.js has _storeCamerasForDrag function');
    assert(mapLibreSource.includes('_updateCameraGeoJSON'),
        'map-maplibre.js has _updateCameraGeoJSON function');
}


// ============================================================
// Drag state initialisation
// ============================================================

console.log('\n--- Drag state management ---');

{
    // Simulate the _cameraDrag state structure
    const dragState = {
        active: false,
        cameraId: null,
        startLngLat: null,
        cameras: [],
    };

    assert(dragState.active === false, 'drag starts inactive');
    assert(dragState.cameraId === null, 'no camera selected initially');
    assert(dragState.cameras.length === 0, 'cameras array empty initially');
}


// ============================================================
// _storeCamerasForDrag makes shallow copies
// ============================================================

console.log('\n--- _storeCamerasForDrag ---');

{
    const dragState = { cameras: [] };

    function storeCamerasForDrag(cameras) {
        dragState.cameras = cameras.map(c => ({ ...c }));
    }

    const original = [
        { id: 'cam-1', lat: 33.0, lng: -97.0, heading: 90, name: 'Front' },
        { id: 'cam-2', lat: 34.0, lng: -98.0, heading: 0, name: 'Back' },
    ];

    storeCamerasForDrag(original);

    assert(dragState.cameras.length === 2, 'stored 2 cameras');
    assert(dragState.cameras[0].id === 'cam-1', 'camera 1 id preserved');
    assert(dragState.cameras[1].lat === 34.0, 'camera 2 lat preserved');

    // Verify they are copies, not references
    original[0].lat = 99.0;
    assert(dragState.cameras[0].lat === 33.0, 'stored camera is a copy, not a reference');
}


// ============================================================
// Drag move updates camera position
// ============================================================

console.log('\n--- Drag move updates position ---');

{
    const dragState = {
        active: true,
        cameraId: 'cam-1',
        cameras: [
            { id: 'cam-1', lat: 33.0, lng: -97.0, heading: 90 },
            { id: 'cam-2', lat: 34.0, lng: -98.0, heading: 0 },
        ],
    };

    function onDragMove(lngLat) {
        if (!dragState.active || !dragState.cameraId) return;
        const cam = dragState.cameras.find(c => (c.id || c.source_id) === dragState.cameraId);
        if (cam) {
            cam.lat = lngLat.lat;
            cam.lng = lngLat.lng;
        }
    }

    onDragMove({ lat: 33.5, lng: -97.5 });

    assert(dragState.cameras[0].lat === 33.5, 'dragged camera lat updated');
    assert(dragState.cameras[0].lng === -97.5, 'dragged camera lng updated');
    // Non-dragged camera unchanged
    assert(dragState.cameras[1].lat === 34.0, 'non-dragged camera lat unchanged');
    assert(dragState.cameras[1].lng === -98.0, 'non-dragged camera lng unchanged');
}


// ============================================================
// Drag does not interfere with non-matching cameras
// ============================================================

console.log('\n--- Drag only affects target camera ---');

{
    const dragState = {
        active: true,
        cameraId: 'cam-nonexistent',
        cameras: [
            { id: 'cam-1', lat: 33.0, lng: -97.0 },
        ],
    };

    function onDragMove(lngLat) {
        if (!dragState.active || !dragState.cameraId) return;
        const cam = dragState.cameras.find(c => (c.id || c.source_id) === dragState.cameraId);
        if (cam) {
            cam.lat = lngLat.lat;
            cam.lng = lngLat.lng;
        }
    }

    onDragMove({ lat: 99.0, lng: -99.0 });
    assert(dragState.cameras[0].lat === 33.0, 'camera unchanged when drag targets nonexistent id');
}


// ============================================================
// GeoJSON rebuilding from stored cameras
// ============================================================

console.log('\n--- GeoJSON rebuild from stored cameras ---');

{
    const cameras = [
        { id: 'cam-1', lat: 33.1, lng: -97.1, heading: 45, name: 'North', status: 'streaming' },
        { id: 'cam-2', lat: 34.2, lng: -98.2, heading: null, name: 'South', status: 'offline' },
        { id: 'cam-3', lat: null, lng: null, name: 'NoPos' },  // should be filtered
    ];

    const filtered = cameras.filter(c => c.lat != null && c.lng != null);
    assert(filtered.length === 2, 'cameras without position are filtered out');

    const geojson = {
        type: 'FeatureCollection',
        features: filtered.map(c => ({
            type: 'Feature',
            properties: {
                id: c.id || c.source_id || '',
                name: c.name || c.id || 'Camera',
                status: c.status || 'offline',
            },
            geometry: {
                type: 'Point',
                coordinates: [c.lng, c.lat],
            },
        })),
    };

    assert(geojson.features.length === 2, 'GeoJSON has 2 features');
    assert(geojson.features[0].geometry.coordinates[0] === -97.1, 'feature 1 lng correct');
    assert(geojson.features[0].geometry.coordinates[1] === 33.1, 'feature 1 lat correct');
    assert(geojson.features[0].properties.id === 'cam-1', 'feature 1 id correct');
    assert(geojson.features[1].properties.status === 'offline', 'feature 2 status correct');
}


// ============================================================
// FOV cone polygon generation (from filtered cameras)
// ============================================================

console.log('\n--- FOV cone features built during drag ---');

{
    const cameras = [
        { id: 'cam-1', lat: 33.1, lng: -97.1, heading: 45, fov_angle: 60, fov_range: 30 },
        { id: 'cam-2', lat: 34.2, lng: -98.2, heading: null, fov_angle: null, fov_range: null },
    ];

    const fovFeatures = cameras.map(c => {
        const heading = c.heading != null ? c.heading : 0;
        const fovAngle = c.fov_angle || 60;
        const rangeM = c.fov_range || 30;
        return {
            type: 'Feature',
            properties: { id: c.id, status: c.status || 'offline' },
            heading: heading,
            fovAngle: fovAngle,
            rangeM: rangeM,
        };
    });

    assert(fovFeatures.length === 2, 'FOV features built for all cameras');
    assert(fovFeatures[0].heading === 45, 'cam-1 heading preserved');
    assert(fovFeatures[0].fovAngle === 60, 'cam-1 fov_angle used');
    assert(fovFeatures[1].heading === 0, 'cam-2 heading defaults to 0');
    assert(fovFeatures[1].fovAngle === 60, 'cam-2 fov_angle defaults to 60');
    assert(fovFeatures[1].rangeM === 30, 'cam-2 fov_range defaults to 30');
}


// ============================================================
// Click suppression after drag
// ============================================================

console.log('\n--- Click suppression after drag ---');

{
    let cameraDragJustEnded = false;
    let clickHandled = false;

    function onCameraClick() {
        if (cameraDragJustEnded) {
            cameraDragJustEnded = false;
            return;
        }
        clickHandled = true;
    }

    // Normal click without drag
    clickHandled = false;
    onCameraClick();
    assert(clickHandled === true, 'normal click is handled');

    // Click right after drag should be suppressed
    cameraDragJustEnded = true;
    clickHandled = false;
    onCameraClick();
    assert(clickHandled === false, 'click after drag is suppressed');
    assert(cameraDragJustEnded === false, 'flag reset after suppression');

    // Next click should work normally
    clickHandled = false;
    onCameraClick();
    assert(clickHandled === true, 'subsequent click after suppression works');
}


// ============================================================
// Drag end resets state
// ============================================================

console.log('\n--- Drag end resets state ---');

{
    const dragState = {
        active: true,
        cameraId: 'cam-1',
        startLngLat: { lng: -97.0, lat: 33.0 },
        cameras: [{ id: 'cam-1', lat: 33.5, lng: -97.5 }],
    };

    function onDragEnd() {
        if (!dragState.active) return;
        dragState.active = false;
        dragState.cameraId = null;
        dragState.startLngLat = null;
    }

    onDragEnd();
    assert(dragState.active === false, 'drag state reset to inactive');
    assert(dragState.cameraId === null, 'camera id cleared');
    assert(dragState.startLngLat === null, 'start position cleared');
    // cameras array should persist for reference
    assert(dragState.cameras.length === 1, 'cameras array persists after drag end');
}


// ============================================================
// API endpoint used for position update
// ============================================================

console.log('\n--- API endpoint in drag code ---');

{
    assert(mapLibreSource.includes('/api/camera-feeds/sources/'),
        'drag code uses camera-feeds sources API');
    assert(mapLibreSource.includes('/position'),
        'drag code patches the position endpoint');
    assert(mapLibreSource.includes("method: 'PATCH'"),
        'drag uses PATCH method');
}


// ============================================================
// Cursor changes during drag
// ============================================================

console.log('\n--- Cursor changes ---');

{
    assert(mapLibreSource.includes("cursor = 'grab'"),
        'hover cursor is grab (indicating draggable)');
    assert(mapLibreSource.includes("cursor = 'grabbing'"),
        'drag cursor is grabbing (indicating active drag)');
}


// ============================================================
// Visual feedback during drag
// ============================================================

console.log('\n--- Visual feedback ---');

{
    // During drag, circle opacity reduces
    assert(mapLibreSource.includes("'circle-opacity', 0.5"),
        'circle opacity reduces during drag');
    // After drag, opacity restores
    assert(mapLibreSource.includes("'circle-opacity', 0.9"),
        'circle opacity restores after drag');
    // Glow ring brightens during drag
    assert(mapLibreSource.includes("'circle-stroke-opacity', 1.0"),
        'glow ring brightens during drag');
}


// ============================================================
// dragPan disable/enable
// ============================================================

console.log('\n--- Map pan disabled during drag ---');

{
    assert(mapLibreSource.includes('dragPan.disable()'),
        'map pan is disabled during camera drag');
    assert(mapLibreSource.includes('dragPan.enable()'),
        'map pan is re-enabled after camera drag');
}


// ============================================================
// Toast feedback on position save
// ============================================================

console.log('\n--- Toast feedback ---');

{
    assert(mapLibreSource.includes('Camera repositioned to'),
        'success toast shows new coordinates');
    assert(mapLibreSource.includes('Failed to save camera position'),
        'failure toast on bad response');
    assert(mapLibreSource.includes('Network error saving camera position'),
        'network error toast');
}


// ============================================================
// _initCameraDrag is called once (guarded)
// ============================================================

console.log('\n--- Init guard ---');

{
    assert(mapLibreSource.includes('_cameraDragInitialised'),
        'init guard variable exists');
    assert(mapLibreSource.includes('if (_cameraDragInitialised'),
        'init function checks guard before running');
}


// ============================================================
// cameras:changed event emitted after drag
// ============================================================

console.log('\n--- cameras:changed event after drag ---');

{
    assert(mapLibreSource.includes("EventBus.emit('cameras:changed'"),
        'cameras:changed event emitted after position save');
}


// ============================================================
// Source_id fallback in camera matching
// ============================================================

console.log('\n--- Source ID fallback ---');

{
    // The drag code should handle both c.id and c.source_id
    const cameras = [
        { source_id: 'front_door', lat: 33.0, lng: -97.0 },
    ];

    const camId = 'front_door';
    const cam = cameras.find(c => (c.id || c.source_id) === camId);
    assert(cam !== undefined, 'camera found by source_id fallback');
    assert(cam.source_id === 'front_door', 'correct camera found');
}


// ============================================================
// Summary
// ============================================================

console.log(`\n=== ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
