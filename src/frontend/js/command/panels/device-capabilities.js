// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Device Capabilities Matrix Panel — grid showing all edge devices vs capabilities
// Quick visual of what each device can do: BLE, WiFi, Camera, Audio, Mesh, GPS.
// Auto-refreshes every 15s. Data from /api/fleet/devices and /api/fleet/nodes.

import { _esc, _timeAgo } from '/lib/utils.js';

// Capability columns with icons and detection heuristics
const CAPABILITIES = [
    { key: 'ble',    label: 'BLE',    icon: 'B', color: '#00f0ff' },
    { key: 'wifi',   label: 'WiFi',   icon: 'W', color: '#05ffa1' },
    { key: 'camera', label: 'Camera', icon: 'C', color: '#ff2a6d' },
    { key: 'audio',  label: 'Audio',  icon: 'A', color: '#fcee0a' },
    { key: 'mesh',   label: 'Mesh',   icon: 'M', color: '#ff8800' },
    { key: 'gps',    label: 'GPS',    icon: 'G', color: '#4a9eff' },
];

/**
 * Detect capabilities from device data fields.
 * Checks explicit capability flags, count fields, and hardware info.
 */
function _detectCapabilities(device) {
    const caps = {};
    for (const cap of CAPABILITIES) {
        caps[cap.key] = false;
    }

    // Explicit capability flags
    if (device.capabilities) {
        for (const cap of CAPABILITIES) {
            if (device.capabilities[cap.key] !== undefined) {
                caps[cap.key] = !!device.capabilities[cap.key];
            }
        }
        return caps;
    }

    // Heuristic detection from device fields
    // BLE: ble_count > 0 or has_ble flag
    if (device.ble_count > 0 || device.has_ble || device.ble_enabled) caps.ble = true;

    // WiFi: wifi_count > 0 or has_wifi flag or always true for ESP32
    if (device.wifi_count > 0 || device.has_wifi || device.wifi_enabled ||
        (device.board && device.board.includes('esp32'))) caps.wifi = true;

    // Camera: has_camera flag or camera_id present
    if (device.has_camera || device.camera_id || device.camera_enabled) caps.camera = true;

    // Audio: has_mic or has_speaker
    if (device.has_mic || device.has_speaker || device.audio_enabled) caps.audio = true;

    // Mesh: meshtastic or espnow
    if (device.has_mesh || device.mesh_enabled || device.meshtastic ||
        device.espnow_enabled) caps.mesh = true;

    // GPS: has_gps flag or lat/lng present
    if (device.has_gps || device.gps_enabled ||
        (device.lat !== undefined && device.lng !== undefined)) caps.gps = true;

    return caps;
}

function _capabilityCell(enabled, cap) {
    if (enabled) {
        return `<td class="dcm-cap-cell dcm-cap-on" style="color:${cap.color};border-color:${cap.color}" title="${cap.label}: Available">
            <span class="dcm-cap-icon">${cap.icon}</span>
        </td>`;
    }
    return `<td class="dcm-cap-cell dcm-cap-off" title="${cap.label}: Not detected">
        <span class="dcm-cap-icon">-</span>
    </td>`;
}

// ============================================================
// Panel Definition
// ============================================================

export const DeviceCapabilitiesPanelDef = {
    id: 'device-capabilities',
    title: 'DEVICE CAPABILITIES',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 520, h: 380 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'dcm-inner';

        // Build header columns
        const capHeaders = CAPABILITIES.map(c =>
            `<th class="dcm-cap-header mono" style="color:${c.color}" title="${c.label}">${c.icon}</th>`
        ).join('');

        el.innerHTML = `
            <div class="dcm-summary" data-bind="dcm-summary">
                <span class="mono" style="color:var(--text-dim)">Loading...</span>
            </div>
            <div class="dcm-table-wrap">
                <table class="dcm-table">
                    <thead>
                        <tr>
                            <th class="dcm-device-header">DEVICE</th>
                            <th class="dcm-status-header">STATUS</th>
                            ${capHeaders}
                            <th class="dcm-score-header">SCORE</th>
                        </tr>
                    </thead>
                    <tbody data-bind="dcm-tbody">
                        <tr><td colspan="${CAPABILITIES.length + 3}" class="panel-empty">Loading device data...</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="dcm-footer">
                <span class="mono" style="color:var(--text-dim)" data-bind="dcm-refresh-ts">--</span>
                <button class="panel-action-btn" data-action="dcm-refresh">REFRESH</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const summaryEl = bodyEl.querySelector('[data-bind="dcm-summary"]');
        const tbodyEl = bodyEl.querySelector('[data-bind="dcm-tbody"]');
        const refreshTsEl = bodyEl.querySelector('[data-bind="dcm-refresh-ts"]');
        const refreshBtn = bodyEl.querySelector('[data-action="dcm-refresh"]');

        let refreshInterval = null;

        async function fetchAndRender() {
            let devices = [];

            // Try fleet devices endpoint
            try {
                const res = await fetch('/api/fleet/devices');
                if (res.ok) {
                    const data = await res.json();
                    devices = data.devices || [];
                }
            } catch (_) { /* skip */ }

            // Also try fleet nodes endpoint
            if (devices.length === 0) {
                try {
                    const res = await fetch('/api/fleet/nodes');
                    if (res.ok) {
                        const data = await res.json();
                        devices = data.nodes || [];
                    }
                } catch (_) { /* skip */ }
            }

            // Also merge in Amy's sensor nodes
            try {
                const res = await fetch('/api/amy/nodes');
                if (res.ok) {
                    const data = await res.json();
                    const nodes = data.nodes || {};
                    for (const [nid, node] of Object.entries(nodes)) {
                        // Check if already in fleet list
                        const exists = devices.some(d =>
                            (d.device_id || d.name) === nid
                        );
                        if (!exists) {
                            devices.push({
                                device_id: nid,
                                name: node.name || nid,
                                status: 'online',
                                has_camera: node.camera,
                                has_mic: node.mic,
                                has_speaker: node.speaker,
                                has_ptz: node.ptz,
                            });
                        }
                    }
                }
            } catch (_) { /* skip */ }

            // Render summary
            const totalCaps = {};
            for (const cap of CAPABILITIES) totalCaps[cap.key] = 0;

            const deviceRows = devices.map(d => {
                const caps = _detectCapabilities(d);
                let score = 0;
                for (const cap of CAPABILITIES) {
                    if (caps[cap.key]) {
                        totalCaps[cap.key]++;
                        score++;
                    }
                }
                return { device: d, caps, score };
            });

            // Sort by score descending, then by name
            deviceRows.sort((a, b) => b.score - a.score ||
                ((a.device.device_id || a.device.name || '') > (b.device.device_id || b.device.name || '') ? 1 : -1));

            // Update summary
            if (summaryEl) {
                const summaryParts = CAPABILITIES.map(cap => {
                    const count = totalCaps[cap.key];
                    return `<span class="dcm-summary-item">
                        <span class="dcm-summary-icon" style="color:${cap.color}">${cap.icon}</span>
                        <span class="dcm-summary-count mono" style="color:${count > 0 ? cap.color : 'var(--text-dim)'}">${count}</span>
                    </span>`;
                }).join('');
                summaryEl.innerHTML = `
                    <span class="dcm-summary-label mono">${devices.length} DEVICES</span>
                    <span class="dcm-summary-caps">${summaryParts}</span>
                `;
            }

            // Render table
            if (tbodyEl) {
                if (deviceRows.length === 0) {
                    tbodyEl.innerHTML = `<tr><td colspan="${CAPABILITIES.length + 3}" class="panel-empty">No devices detected. Start fleet server or demo mode.</td></tr>`;
                } else {
                    tbodyEl.innerHTML = deviceRows.map(({ device: d, caps, score }) => {
                        const did = _esc(d.device_id || d.name || '--');
                        const status = d.status || 'unknown';
                        const statusColor = status === 'online' ? '#05ffa1' : status === 'stale' ? '#fcee0a' : '#ff2a6d';
                        const capCells = CAPABILITIES.map(cap => _capabilityCell(caps[cap.key], cap)).join('');
                        const scoreColor = score >= 4 ? '#05ffa1' : score >= 2 ? '#fcee0a' : '#ff2a6d';

                        return `<tr class="dcm-row">
                            <td class="mono dcm-device-cell" title="${did}">${did}</td>
                            <td class="mono" style="color:${statusColor}">${status.toUpperCase()}</td>
                            ${capCells}
                            <td class="mono dcm-score-cell" style="color:${scoreColor}">${score}/${CAPABILITIES.length}</td>
                        </tr>`;
                    }).join('');
                }
            }

            // Refresh timestamp
            if (refreshTsEl) {
                refreshTsEl.textContent = new Date().toLocaleTimeString();
            }
        }

        fetchAndRender();
        refreshInterval = setInterval(fetchAndRender, 15000);

        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchAndRender);
        }

        panel._dcmInterval = refreshInterval;
    },

    unmount(bodyEl, panel) {
        if (panel._dcmInterval) {
            clearInterval(panel._dcmInterval);
            panel._dcmInterval = null;
        }
    },
};
