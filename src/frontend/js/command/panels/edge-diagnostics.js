/**
 * Edge Diagnostics Panel — Remote device diagnostic dump viewer.
 *
 * Allows operators to select an edge device, request a diagnostic dump
 * via MQTT, and view results (heap, tasks, WiFi, BLE, NVS, I2C).
 *
 * Created by Matthew Valancy
 * Copyright 2026 Valpatel Software LLC
 * Licensed under AGPL-3.0
 */

export function createEdgeDiagnosticsPanel() {
    const panel = document.createElement('div');
    panel.className = 'panel edge-diagnostics-panel';
    panel.innerHTML = `
        <div class="panel-header">
            <span class="panel-title">EDGE DIAGNOSTICS</span>
            <div class="panel-controls">
                <button class="btn-cyber btn-sm" id="diag-refresh-btn" title="Refresh device list">REFRESH</button>
            </div>
        </div>
        <div class="panel-body" style="padding: 8px; overflow-y: auto;">
            <div class="diag-device-selector" style="margin-bottom: 8px;">
                <select id="diag-device-select" class="cyber-select" style="width: 100%; background: #0e0e14; color: #00f0ff; border: 1px solid #00f0ff33; padding: 6px; font-family: monospace;">
                    <option value="">-- Select Device --</option>
                </select>
            </div>
            <div class="diag-actions" style="margin-bottom: 8px; display: flex; gap: 6px;">
                <button class="btn-cyber btn-sm" id="diag-request-btn" disabled>REQUEST DUMP</button>
                <button class="btn-cyber btn-sm" id="diag-view-btn" disabled>VIEW LAST</button>
            </div>
            <div id="diag-status" class="diag-status" style="font-size: 11px; color: #05ffa1; margin-bottom: 8px;"></div>
            <div id="diag-results" class="diag-results" style="font-size: 11px; font-family: monospace;"></div>
        </div>
    `;

    const select = panel.querySelector('#diag-device-select');
    const requestBtn = panel.querySelector('#diag-request-btn');
    const viewBtn = panel.querySelector('#diag-view-btn');
    const refreshBtn = panel.querySelector('#diag-refresh-btn');
    const statusDiv = panel.querySelector('#diag-status');
    const resultsDiv = panel.querySelector('#diag-results');

    select.addEventListener('change', () => {
        const hasDevice = select.value !== '';
        requestBtn.disabled = !hasDevice;
        viewBtn.disabled = !hasDevice;
        if (hasDevice) {
            loadDiagnostics(select.value);
        } else {
            resultsDiv.innerHTML = '';
            statusDiv.textContent = '';
        }
    });

    refreshBtn.addEventListener('click', loadDevices);
    requestBtn.addEventListener('click', () => {
        if (select.value) requestDiagnostics(select.value);
    });
    viewBtn.addEventListener('click', () => {
        if (select.value) loadDiagnostics(select.value);
    });

    async function loadDevices() {
        try {
            const resp = await fetch('/api/fleet/devices');
            const data = await resp.json();
            const devices = data.devices || [];
            select.innerHTML = '<option value="">-- Select Device --</option>';
            devices.forEach(dev => {
                const opt = document.createElement('option');
                opt.value = dev.device_id;
                const status = dev.status || 'unknown';
                const icon = status === 'online' ? '\u25CF' : '\u25CB';
                opt.textContent = `${icon} ${dev.name || dev.device_id} (${status})`;
                select.appendChild(opt);
            });
        } catch (err) {
            statusDiv.textContent = 'Failed to load devices: ' + err.message;
            statusDiv.style.color = '#ff2a6d';
        }
    }

    async function requestDiagnostics(deviceId) {
        statusDiv.textContent = 'Requesting diagnostic dump...';
        statusDiv.style.color = '#fcee0a';
        requestBtn.disabled = true;

        try {
            const resp = await fetch(`/api/fleet/devices/${deviceId}/diagnostics`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sections: ['heap', 'tasks', 'wifi', 'ble', 'nvs', 'i2c']
                }),
            });
            const data = await resp.json();
            if (data.status === 'requested') {
                statusDiv.textContent = 'Dump requested. Waiting for response...';
                statusDiv.style.color = '#05ffa1';
                // Poll for results after a brief delay
                setTimeout(() => loadDiagnostics(deviceId), 3000);
            } else {
                statusDiv.textContent = data.error || 'Request failed';
                statusDiv.style.color = '#ff2a6d';
            }
        } catch (err) {
            statusDiv.textContent = 'Request error: ' + err.message;
            statusDiv.style.color = '#ff2a6d';
        } finally {
            requestBtn.disabled = false;
        }
    }

    async function loadDiagnostics(deviceId) {
        try {
            const resp = await fetch(`/api/fleet/devices/${deviceId}/diagnostics`);
            const data = await resp.json();

            if (data.status === 'no_data') {
                resultsDiv.innerHTML = `<div style="color: #888; text-align: center; padding: 20px;">
                    No diagnostic data available.<br>Click REQUEST DUMP to fetch from device.
                </div>`;
                return;
            }

            renderDiagnostics(data);
        } catch (err) {
            resultsDiv.innerHTML = `<div style="color: #ff2a6d;">Error loading diagnostics: ${err.message}</div>`;
        }
    }

    function renderDiagnostics(data) {
        const receivedAt = data.received_at ? new Date(data.received_at * 1000).toLocaleString() : 'N/A';
        let html = `<div style="color: #888; margin-bottom: 8px;">Last updated: ${receivedAt}</div>`;

        // Heap section
        if (data.heap) {
            const h = data.heap;
            const heapKB = (h.free_heap / 1024).toFixed(1);
            const minKB = (h.min_free_heap / 1024).toFixed(1);
            const psramKB = (h.free_psram / 1024).toFixed(1);
            const heapColor = h.free_heap < 20000 ? '#ff2a6d' : h.free_heap < 50000 ? '#fcee0a' : '#05ffa1';
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">HEAP MEMORY</div>
                <div style="color: ${heapColor};">Free: ${heapKB} KB</div>
                <div>Min Free: ${minKB} KB</div>
                <div>PSRAM Free: ${psramKB} KB</div>
                <div>Largest Block: ${(h.largest_free_block / 1024).toFixed(1)} KB</div>
            </div>`;
        }

        // WiFi section
        if (data.wifi) {
            const w = data.wifi;
            const rssiColor = w.rssi > -50 ? '#05ffa1' : w.rssi > -70 ? '#fcee0a' : '#ff2a6d';
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">WIFI</div>
                <div>Status: ${w.connected ? '<span style="color:#05ffa1;">CONNECTED</span>' : '<span style="color:#ff2a6d;">DISCONNECTED</span>'}</div>
                <div>SSID: ${w.ssid || 'N/A'}</div>
                <div style="color: ${rssiColor};">RSSI: ${w.rssi} dBm</div>
                <div>IP: ${w.ip || 'N/A'}</div>
                <div>Channel: ${w.channel || 'N/A'}</div>
                <div>Disconnects: ${w.disconnects || 0}</div>
            </div>`;
        }

        // BLE section
        if (data.ble) {
            const b = data.ble;
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">BLE</div>
                <div>Enabled: ${b.enabled ? 'YES' : 'NO'}</div>
                <div>Scanning: ${b.scan_active ? 'YES' : 'NO'}</div>
                <div>Devices Found: ${b.devices_found || 0}</div>
                <div>Scan Count: ${b.scan_count || 0}</div>
            </div>`;
        }

        // NVS section
        if (data.nvs) {
            const n = data.nvs;
            const usedPct = n.total_entries > 0 ? ((n.used_entries / n.total_entries) * 100).toFixed(1) : 0;
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">NVS STORAGE</div>
                <div>Used: ${n.used_entries || 0} / ${n.total_entries || 0} (${usedPct}%)</div>
                <div>Free: ${n.free_entries || 0}</div>
            </div>`;
        }

        // I2C section
        if (data.i2c) {
            const i = data.i2c;
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">I2C BUS</div>
                <div>Devices: ${i.devices_found || 0}</div>
                <div>Errors: ${i.errors || 0}</div>
            </div>`;
            if (i.slaves && i.slaves.length > 0) {
                html += '<div style="margin-left: 8px;">';
                i.slaves.forEach(s => {
                    html += `<div style="color: #888;">  ${s.addr}: OK=${s.success_count || 0} ERR=${(s.nack_count || 0) + (s.timeout_count || 0)}</div>`;
                });
                html += '</div>';
            }
        }

        // System section
        if (data.system) {
            const s = data.system;
            const uptimeH = (s.uptime_s / 3600).toFixed(1);
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">SYSTEM</div>
                <div>Uptime: ${uptimeH}h</div>
                <div>Firmware: ${s.firmware || 'N/A'}</div>
                <div>Board: ${s.board_type || 'N/A'}</div>
                <div>Reboots: ${s.reboot_count || 0}</div>
                ${s.cpu_temp_c ? `<div>CPU Temp: ${s.cpu_temp_c}\u00B0C</div>` : ''}
                ${s.battery_pct != null ? `<div>Battery: ${s.battery_pct}%</div>` : ''}
                <div>Loop Time: ${s.loop_time_us || 0} \u00B5s</div>
            </div>`;
        }

        // Tasks section
        if (data.tasks && data.tasks.length > 0) {
            html += `<div class="diag-section">
                <div class="diag-section-title" style="color: #00f0ff; font-weight: bold; border-bottom: 1px solid #00f0ff33; margin: 6px 0 4px;">TASKS (${data.task_count || data.tasks.length})</div>
                <div style="max-height: 120px; overflow-y: auto;">`;
            data.tasks.forEach(t => {
                html += `<div style="color: #888;">  ${t.name || 'unknown'}: stack=${t.stack_hwm || '?'} prio=${t.priority || '?'}</div>`;
            });
            html += '</div></div>';
        }

        resultsDiv.innerHTML = html;
    }

    // Initial load
    loadDevices();

    return panel;
}
