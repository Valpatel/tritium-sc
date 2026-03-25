#!/usr/bin/env node
// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Tests for SensorBridge — synthetic BLE/WiFi sighting generation
 * from city-sim entities and WebSocket delivery.
 */

const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;

function assert(cond, msg) {
    if (cond) { passed++; console.log(`PASS: ${msg}`); }
    else { failed++; console.log(`FAIL: ${msg}`); }
}

// ---------------------------------------------------------------------------
// Source-level checks (sensor-bridge.js)
// ---------------------------------------------------------------------------

const simDir = path.join(__dirname, '../../src/frontend/js/command/sim');
const src = fs.readFileSync(path.join(simDir, 'sensor-bridge.js'), 'utf8');

console.log('=== Source Structure ===');
assert(src.includes('class SensorBridge'), 'SensorBridge class exists');
assert(src.includes('getMac('), 'BLE MAC assignment method');
assert(src.includes('getWifiMac('), 'WiFi BSSID assignment method');
assert(src.includes('setWebSocketSend('), 'WebSocket send setter');
assert(src.includes('wifiInterval'), 'Configurable WiFi interval');
assert(src.includes('bleInterval'), 'Configurable BLE interval');
assert(src.includes('detectionInterval'), 'Configurable detection interval');
assert(src.includes("type: 'ble_sighting'"), 'Generates BLE sighting events');
assert(src.includes("type: 'wifi_sighting'"), 'Generates WiFi sighting events');
assert(src.includes("type: 'detection'"), 'Generates YOLO detection events');
assert(src.includes('_entityWifiMacs'), 'WiFi MAC persistence map');
assert(src.includes('_entityMacs'), 'BLE MAC persistence map');
assert(src.includes("class: 'car'"), 'Vehicle detections classify as car');
assert(src.includes("class: 'person'"), 'Pedestrian detections classify as person');
assert(src.includes('sim_sighting_batch'), 'Sends sim_sighting_batch via WS');
assert(src.includes('this.enabled = false'), 'Disabled by default');
assert(src.includes('this.stats'), 'Tracks send statistics');

// ---------------------------------------------------------------------------
// Behavioral tests (eval-based, Node.js compatible)
// ---------------------------------------------------------------------------

console.log('\n=== Behavioral Tests ===');

// Extract the class and helper code for Node.js evaluation.
// We strip the export keyword and import statements, then use Function()
// to return the class for use in tests.
let evalSrc = src
    .replace(/^import .*/gm, '')
    .replace('export class', 'class');

const SensorBridge = new Function(evalSrc + '\nreturn SensorBridge;')();

// Test 1: Constructor defaults
{
    const sb = new SensorBridge();
    assert(sb.enabled === false, 'Bridge is disabled by default');
    assert(sb.bleInterval === 2, 'Default BLE interval is 2s');
    assert(sb.wifiInterval === 2, 'Default WiFi interval is 2s');
    assert(sb.detectionInterval === 1, 'Default detection interval is 1s');
    assert(sb._sightings.length === 0, 'No initial sightings');
    assert(sb._detections.length === 0, 'No initial detections');
}

// Test 2: getMac returns persistent MAC
{
    const sb = new SensorBridge();
    const mac1 = sb.getMac('ped_1');
    const mac2 = sb.getMac('ped_1');
    const mac3 = sb.getMac('ped_2');
    assert(mac1 === mac2, 'Same entity gets same BLE MAC');
    assert(mac1 !== mac3, 'Different entities get different BLE MACs');
    assert(mac1.split(':').length === 6, 'BLE MAC has 6 octets');
}

// Test 3: getWifiMac returns persistent BSSID (different from BLE)
{
    const sb = new SensorBridge();
    const bssid1 = sb.getWifiMac('car_1');
    const bssid2 = sb.getWifiMac('car_1');
    const bssid3 = sb.getWifiMac('car_2');
    assert(bssid1 === bssid2, 'Same entity gets same WiFi BSSID');
    assert(bssid1 !== bssid3, 'Different entities get different BSSIDs');
    assert(bssid1.split(':').length === 6, 'WiFi BSSID has 6 octets');
}

// Test 4: tick() returns empty when disabled
{
    const sb = new SensorBridge();
    const result = sb.tick(5, [{ id: 'car_1', x: 10, z: 20 }], [{ id: 'ped_1', x: 30, z: 40 }]);
    assert(result.sightings.length === 0, 'No sightings when disabled');
    assert(result.detections.length === 0, 'No detections when disabled');
}

// Test 5: tick() generates WiFi sightings for vehicles
{
    const sb = new SensorBridge();
    sb.enabled = true;
    const vehicles = [
        { id: 'car_1', x: 10, z: 20 },
        { id: 'car_2', x: 30, z: 40, parked: true },
        { id: 'car_3', x: 50, z: 60 },
    ];
    // First tick with dt=3 exceeds wifiInterval=2
    const result = sb.tick(3, vehicles, []);
    const wifiSightings = result.sightings.filter(s => s.type === 'wifi_sighting');
    // car_2 is parked so should be skipped
    assert(wifiSightings.length === 2, 'WiFi sightings for 2 non-parked vehicles');
    assert(wifiSightings[0].source === 'city_sim', 'WiFi sighting source is city_sim');
    assert(wifiSightings[0].target_id.startsWith('sim_wifi_'), 'WiFi target_id has sim_wifi_ prefix');
    assert(wifiSightings[0].mac !== undefined, 'WiFi sighting has mac field');
    assert(wifiSightings[0].position !== undefined, 'WiFi sighting has position');
    assert(wifiSightings[0].position.x === 10, 'WiFi sighting position.x matches vehicle x');
    assert(wifiSightings[0].position.y === 20, 'WiFi sighting position.y matches vehicle z');
    assert(typeof wifiSightings[0].rssi === 'number', 'WiFi sighting has numeric RSSI');
    assert(wifiSightings[0].rssi <= -50 && wifiSightings[0].rssi >= -80, 'WiFi RSSI in expected range');
    assert(typeof wifiSightings[0].timestamp === 'number', 'WiFi sighting has timestamp');
}

// Test 6: tick() generates BLE sightings for pedestrians
{
    const sb = new SensorBridge();
    sb.enabled = true;
    const pedestrians = [
        { id: 'ped_1', x: 100, z: 200 },
        { id: 'ped_2', x: 300, z: 400, inBuilding: true },
        { id: 'ped_3', x: 500, z: 600 },
    ];
    const result = sb.tick(3, [], pedestrians);
    const bleSightings = result.sightings.filter(s => s.type === 'ble_sighting');
    // ped_2 is inBuilding so should be skipped
    assert(bleSightings.length === 2, 'BLE sightings for 2 visible pedestrians');
    assert(bleSightings[0].source === 'city_sim', 'BLE sighting source is city_sim');
    assert(bleSightings[0].target_id.startsWith('sim_ble_'), 'BLE target_id has sim_ble_ prefix');
    assert(bleSightings[0].mac !== undefined, 'BLE sighting has mac field');
    assert(bleSightings[0].position !== undefined, 'BLE sighting has position');
    assert(bleSightings[0].position.x === 100, 'BLE sighting position.x matches ped x');
    assert(bleSightings[0].position.y === 200, 'BLE sighting position.y matches ped z');
    assert(typeof bleSightings[0].rssi === 'number', 'BLE sighting has numeric RSSI');
    assert(bleSightings[0].rssi <= -35 && bleSightings[0].rssi >= -60, 'BLE RSSI in expected range');
    const validDevices = ['phone', 'smartwatch', 'fitness_tracker'];
    assert(validDevices.includes(bleSightings[0].device_class), 'BLE device_class is valid');
}

// Test 7: tick() generates camera detections
{
    const sb = new SensorBridge();
    sb.enabled = true;
    const vehicles = [{ id: 'car_1', x: 10, z: 20 }];
    const peds = [{ id: 'ped_1', x: 30, z: 40 }];
    const result = sb.tick(3, vehicles, peds);
    const carDets = result.detections.filter(d => d.class === 'car');
    const pedDets = result.detections.filter(d => d.class === 'person');
    assert(carDets.length === 1, 'One car detection');
    assert(pedDets.length === 1, 'One person detection');
    assert(carDets[0].confidence >= 0.85 && carDets[0].confidence <= 0.99, 'Car confidence in range');
    assert(pedDets[0].confidence >= 0.80 && pedDets[0].confidence <= 0.99, 'Person confidence in range');
    assert(carDets[0].target_id === 'sim_det_vehicle_car_1', 'Car detection target_id correct');
    assert(pedDets[0].target_id === 'sim_det_person_ped_1', 'Person detection target_id correct');
}

// Test 8: timer gating — no sightings before interval elapses
{
    const sb = new SensorBridge();
    sb.enabled = true;
    // dt=1 < bleInterval=2 and wifiInterval=2 → no sightings
    // dt=1 >= detectionInterval=1 → detections fire
    const result = sb.tick(1, [{ id: 'c1', x: 0, z: 0 }], [{ id: 'p1', x: 0, z: 0 }]);
    assert(result.sightings.length === 0, 'No BLE/WiFi sightings before interval (dt=1 < 2)');
    assert(result.detections.length === 2, 'Detections fire at 1s interval');
}

// Test 9: WebSocket send function is called with batch
{
    const sb = new SensorBridge();
    sb.enabled = true;
    let captured = null;
    sb.setWebSocketSend((msg) => { captured = msg; });
    sb.tick(3, [{ id: 'c1', x: 0, z: 0 }], [{ id: 'p1', x: 0, z: 0 }]);
    assert(captured !== null, 'WebSocket send function was called');
    assert(captured.type === 'sim_sighting_batch', 'WS message type is sim_sighting_batch');
    assert(Array.isArray(captured.data), 'WS message data is an array');
    assert(captured.data.length > 0, 'WS batch is non-empty');
    // Should contain wifi + ble + detections
    const types = captured.data.map(d => d.type);
    assert(types.includes('wifi_sighting'), 'WS batch contains wifi_sighting');
    assert(types.includes('ble_sighting'), 'WS batch contains ble_sighting');
    assert(types.includes('detection'), 'WS batch contains detection');
}

// Test 10: Stats tracking
{
    const sb = new SensorBridge();
    sb.enabled = true;
    sb.setWebSocketSend(() => {});
    sb.tick(3, [{ id: 'c1', x: 0, z: 0 }], [{ id: 'p1', x: 0, z: 0 }]);
    assert(sb.stats.wifiSent === 1, 'Stats: 1 WiFi sighting sent');
    assert(sb.stats.bleSent === 1, 'Stats: 1 BLE sighting sent');
    assert(sb.stats.detSent === 2, 'Stats: 2 detections sent (1 car + 1 person)');
    assert(sb.stats.batchesSent === 1, 'Stats: 1 batch sent');
}

// Test 11: No WS send when wsSend is null (no crash)
{
    const sb = new SensorBridge();
    sb.enabled = true;
    // No setWebSocketSend called — _wsSend is null
    let threw = false;
    try {
        sb.tick(3, [{ id: 'c1', x: 0, z: 0 }], []);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'No crash when WebSocket send is null');
}

// Test 12: flush() returns buffered data and clears
{
    const sb = new SensorBridge();
    sb.enabled = true;
    sb.tick(3, [{ id: 'c1', x: 0, z: 0 }], [{ id: 'p1', x: 0, z: 0 }]);
    const flushed = sb.flush();
    assert(flushed.sightings.length > 0, 'Flush returns sightings');
    assert(flushed.detections.length > 0, 'Flush returns detections');
    const flushed2 = sb.flush();
    assert(flushed2.sightings.length === 0, 'Second flush is empty (sightings)');
    assert(flushed2.detections.length === 0, 'Second flush is empty (detections)');
}

// Test 13: reset() clears all state
{
    const sb = new SensorBridge();
    sb.enabled = true;
    sb.setWebSocketSend(() => {});
    sb.tick(3, [{ id: 'c1', x: 0, z: 0 }], [{ id: 'p1', x: 0, z: 0 }]);
    sb.reset();
    assert(sb._entityMacs.size === 0, 'Reset clears BLE MAC map');
    assert(sb._entityWifiMacs.size === 0, 'Reset clears WiFi MAC map');
    assert(sb._sightings.length === 0, 'Reset clears sightings');
    assert(sb._detections.length === 0, 'Reset clears detections');
    assert(sb._bleTimer === 0, 'Reset clears BLE timer');
    assert(sb._wifiTimer === 0, 'Reset clears WiFi timer');
    assert(sb.stats.bleSent === 0, 'Reset clears stats');
}

// Test 14: WiFi BSSIDs use different OUI prefix from BLE MACs
{
    const sb = new SensorBridge();
    const bleMac = sb.getMac('entity_a');
    const wifiBssid = sb.getWifiMac('entity_b');
    const bleOui = bleMac.split(':').slice(0, 3).join(':');
    const wifiOui = wifiBssid.split(':').slice(0, 3).join(':');
    const bleOuis = ['AA:BB:CC', 'DD:EE:FF', '11:22:33'];
    const wifiOuis = ['CA:FE:01', 'CA:FE:02', 'CA:FE:03'];
    assert(bleOuis.includes(bleOui), 'BLE MAC uses BLE OUI prefix');
    assert(wifiOuis.includes(wifiOui), 'WiFi BSSID uses WiFi OUI prefix');
}

// ---------------------------------------------------------------------------
// Summary
// ---------------------------------------------------------------------------

console.log(`\n=== Sensor Bridge Tests: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
