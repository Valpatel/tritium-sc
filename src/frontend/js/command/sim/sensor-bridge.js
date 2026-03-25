// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * SensorBridge — generates synthetic BLE/WiFi sensor data from simulated
 * entities and sends them to the SC target tracker via WebSocket.
 *
 * Each vehicle emits a WiFi sighting (hotspot BSSID) and each pedestrian
 * emits a BLE sighting (phone/watch MAC).  Camera zones generate YOLO
 * detections.  All data is sent as `sim_sighting_batch` messages over the
 * WebSocket so the backend target tracker can ingest them alongside real
 * sensor data.
 *
 * The bridge is toggleable: off by default, enabled when city sim runs.
 * Wire the output by calling `setWebSocketSend(fn)` with a function that
 * accepts a JSON-serializable object, or leave unwired to use EventBus.
 */

let _macCounter = 0;

function _generateMac(prefix) {
    const ouis = prefix === 'wifi'
        ? ['CA:FE:01', 'CA:FE:02', 'CA:FE:03']
        : ['AA:BB:CC', 'DD:EE:FF', '11:22:33'];
    const oui = ouis[_macCounter % ouis.length];
    const suffix = [
        (((_macCounter >> 16) & 0xFF).toString(16)).padStart(2, '0'),
        (((_macCounter >> 8) & 0xFF).toString(16)).padStart(2, '0'),
        ((_macCounter & 0xFF).toString(16)).padStart(2, '0'),
    ].join(':');
    _macCounter++;
    return `${oui}:${suffix}`;
}

export class SensorBridge {
    /**
     * @param {Object} options
     * @param {number} [options.bleInterval=2] — seconds between BLE sightings
     * @param {number} [options.wifiInterval=2] — seconds between WiFi sightings
     * @param {number} [options.detectionInterval=1] — seconds between YOLO detections
     */
    constructor(options = {}) {
        this.bleInterval = options.bleInterval || 2;
        this.wifiInterval = options.wifiInterval || 2;
        this.detectionInterval = options.detectionInterval || 1;
        this._bleTimer = 0;
        this._wifiTimer = 0;
        this._detTimer = 0;
        this._entityMacs = new Map();     // entityId → BLE MAC
        this._entityWifiMacs = new Map(); // entityId → WiFi BSSID
        this._sightings = [];
        this._detections = [];
        this._wsSend = null;  // WebSocket send function
        this.enabled = false;
        this.stats = { bleSent: 0, wifiSent: 0, detSent: 0, batchesSent: 0 };
    }

    /**
     * Set the WebSocket send function.  Pass `null` to disconnect.
     * @param {Function|null} sendFn — function(obj) that sends JSON over WS
     */
    setWebSocketSend(sendFn) {
        this._wsSend = sendFn;
    }

    /**
     * Assign a persistent BLE MAC to an entity.
     */
    getMac(entityId) {
        if (!this._entityMacs.has(entityId)) {
            this._entityMacs.set(entityId, _generateMac('ble'));
        }
        return this._entityMacs.get(entityId);
    }

    /**
     * Assign a persistent WiFi BSSID to an entity (vehicles).
     */
    getWifiMac(entityId) {
        if (!this._entityWifiMacs.has(entityId)) {
            this._entityWifiMacs.set(entityId, _generateMac('wifi'));
        }
        return this._entityWifiMacs.get(entityId);
    }

    /**
     * Generate sensor data for this tick.
     * @param {number} dt
     * @param {Array} vehicles
     * @param {Array} pedestrians
     * @returns {{ sightings: Array, detections: Array }}
     */
    tick(dt, vehicles, pedestrians) {
        if (!this.enabled) return { sightings: [], detections: [] };

        this._bleTimer += dt;
        this._wifiTimer += dt;
        this._detTimer += dt;

        const sightings = [];
        const detections = [];

        // WiFi sightings from vehicles (hotspot/probe requests)
        if (this._wifiTimer >= this.wifiInterval) {
            this._wifiTimer = 0;

            for (const car of vehicles) {
                if (car.parked) continue;
                const bssid = this.getWifiMac(car.id);
                sightings.push({
                    type: 'wifi_sighting',
                    target_id: `sim_wifi_${bssid}`,
                    mac: bssid,
                    rssi: -50 - Math.floor(Math.random() * 30),
                    ssid: car._identity?.vehicleDesc || `Vehicle_${car.id}`,
                    source: 'city_sim',
                    position: { x: car.x, y: car.z },
                    timestamp: Date.now(),
                });
            }
        }

        // BLE sightings from pedestrians (phone, smartwatch, fitness tracker)
        if (this._bleTimer >= this.bleInterval) {
            this._bleTimer = 0;

            const pedDevices = ['phone', 'phone', 'phone', 'smartwatch', 'fitness_tracker'];
            for (const ped of pedestrians) {
                if (ped.inBuilding) continue;
                sightings.push({
                    type: 'ble_sighting',
                    target_id: `sim_ble_${this.getMac(ped.id)}`,
                    mac: this.getMac(ped.id),
                    rssi: -35 - Math.floor(Math.random() * 25),
                    device_class: pedDevices[Math.floor(Math.random() * pedDevices.length)],
                    source: 'city_sim',
                    position: { x: ped.x, y: ped.z },
                    timestamp: Date.now(),
                });
            }
        }

        // Camera detections
        if (this._detTimer >= this.detectionInterval) {
            this._detTimer = 0;

            for (const car of vehicles) {
                detections.push({
                    type: 'detection',
                    target_id: `sim_det_vehicle_${car.id}`,
                    class: 'car',
                    confidence: 0.85 + Math.random() * 0.14,
                    source: 'city_sim',
                    position: { x: car.x, y: car.z },
                    timestamp: Date.now(),
                });
            }

            for (const ped of pedestrians) {
                if (ped.inBuilding) continue;
                detections.push({
                    type: 'detection',
                    target_id: `sim_det_person_${ped.id}`,
                    class: 'person',
                    confidence: 0.80 + Math.random() * 0.19,
                    source: 'city_sim',
                    position: { x: ped.x, y: ped.z },
                    timestamp: Date.now(),
                });
            }
        }

        this._sightings = sightings;
        this._detections = detections;

        // Send over WebSocket if wired
        if (sightings.length > 0 || detections.length > 0) {
            this._sendBatch(sightings, detections);
        }

        return { sightings, detections };
    }

    /**
     * Send a batch of sightings and detections via WebSocket.
     * @private
     */
    _sendBatch(sightings, detections) {
        if (!this._wsSend) return;

        const batch = [...sightings, ...detections];
        if (batch.length === 0) return;

        try {
            this._wsSend({
                type: 'sim_sighting_batch',
                data: batch,
            });
            this.stats.bleSent += sightings.filter(s => s.type === 'ble_sighting').length;
            this.stats.wifiSent += sightings.filter(s => s.type === 'wifi_sighting').length;
            this.stats.detSent += detections.length;
            this.stats.batchesSent++;
        } catch (_e) {
            // Fire-and-forget — do not break the sim loop
        }
    }

    /**
     * Get pending sightings and detections, then clear buffers.
     */
    flush() {
        const result = { sightings: [...this._sightings], detections: [...this._detections] };
        this._sightings = [];
        this._detections = [];
        return result;
    }

    /**
     * Reset all state.
     */
    reset() {
        this._entityMacs.clear();
        this._entityWifiMacs.clear();
        this._sightings = [];
        this._detections = [];
        this._bleTimer = 0;
        this._wifiTimer = 0;
        this._detTimer = 0;
        this.stats = { bleSent: 0, wifiSent: 0, detSent: 0, batchesSent: 0 };
    }
}
