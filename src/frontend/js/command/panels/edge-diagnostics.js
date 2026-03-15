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

export const EdgeDiagnosticsPanelDef = {
    id: 'edge-diagnostics',
    title: 'EDGE DIAGNOSTICS',
    defaultPosition: { x: 200, y: 80 },
    defaultSize: { w: 420, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'edge-diagnostics-panel';
        el.innerHTML = `
            <div style="padding: 8px;">
                <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px;">
                    <select data-bind="device-select" style="flex:1;background:#0e0e14;color:#00f0ff;border:1px solid #00f0ff33;padding:6px;font-family:monospace;font-size:0.42rem;">
                        <option value="">-- Select Device --</option>
                    </select>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                </div>
                <div style="display:flex;gap:6px;margin-bottom:8px;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="request" disabled style="font-size:0.42rem">REQUEST DUMP</button>
                    <button class="panel-action-btn" data-action="view" disabled style="font-size:0.42rem">VIEW LAST</button>
                </div>
                <div data-bind="status" style="font-size:11px;color:#05ffa1;margin-bottom:8px;"></div>
                <div data-bind="results" style="font-size:11px;font-family:monospace;overflow-y:auto;max-height:360px;"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const select = bodyEl.querySelector('[data-bind="device-select"]');
        const requestBtn = bodyEl.querySelector('[data-action="request"]');
        const viewBtn = bodyEl.querySelector('[data-action="view"]');
        const statusDiv = bodyEl.querySelector('[data-bind="status"]');
        const resultsDiv = bodyEl.querySelector('[data-bind="results"]');

        select.addEventListener('change', () => {
            const hasDevice = select.value !== '';
            requestBtn.disabled = !hasDevice;
            viewBtn.disabled = !hasDevice;
            if (hasDevice) loadDiagnostics(select.value);
            else { resultsDiv.innerHTML = ''; statusDiv.textContent = ''; }
        });

        bodyEl.addEventListener('click', (e) => {
            const action = e.target.dataset?.action;
            if (action === 'refresh') loadDevices();
            else if (action === 'request' && select.value) requestDiagnostics(select.value);
            else if (action === 'view' && select.value) loadDiagnostics(select.value);
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
                    body: JSON.stringify({ sections: ['heap', 'tasks', 'wifi', 'ble', 'nvs', 'i2c'] }),
                });
                const data = await resp.json();
                if (data.status === 'requested') {
                    statusDiv.textContent = 'Dump requested. Waiting for response...';
                    statusDiv.style.color = '#05ffa1';
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
                    resultsDiv.innerHTML = `<div style="color:#888;text-align:center;padding:20px;">No diagnostic data available.<br>Click REQUEST DUMP to fetch from device.</div>`;
                    return;
                }
                renderDiagnostics(data);
            } catch (err) {
                resultsDiv.innerHTML = `<div style="color:#ff2a6d;">Error loading diagnostics: ${err.message}</div>`;
            }
        }

        function renderDiagnostics(data) {
            const receivedAt = data.received_at ? new Date(data.received_at * 1000).toLocaleString() : 'N/A';
            let html = `<div style="color:#888;margin-bottom:8px;">Last updated: ${receivedAt}</div>`;

            if (data.heap) {
                const h = data.heap;
                const heapKB = (h.free_heap / 1024).toFixed(1);
                const minKB = (h.min_free_heap / 1024).toFixed(1);
                const psramKB = (h.free_psram / 1024).toFixed(1);
                const heapColor = h.free_heap < 20000 ? '#ff2a6d' : h.free_heap < 50000 ? '#fcee0a' : '#05ffa1';
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">HEAP MEMORY</div>
                    <div style="color:${heapColor};">Free: ${heapKB} KB</div>
                    <div>Min Free: ${minKB} KB</div>
                    <div>PSRAM Free: ${psramKB} KB</div>
                    <div>Largest Block: ${(h.largest_free_block / 1024).toFixed(1)} KB</div></div>`;
            }

            if (data.wifi) {
                const w = data.wifi;
                const rssiColor = w.rssi > -50 ? '#05ffa1' : w.rssi > -70 ? '#fcee0a' : '#ff2a6d';
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">WIFI</div>
                    <div>Status: ${w.connected ? '<span style="color:#05ffa1;">CONNECTED</span>' : '<span style="color:#ff2a6d;">DISCONNECTED</span>'}</div>
                    <div>SSID: ${w.ssid || 'N/A'}</div>
                    <div style="color:${rssiColor};">RSSI: ${w.rssi} dBm</div>
                    <div>IP: ${w.ip || 'N/A'}</div>
                    <div>Channel: ${w.channel || 'N/A'}</div>
                    <div>Disconnects: ${w.disconnects || 0}</div></div>`;
            }

            if (data.ble) {
                const b = data.ble;
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">BLE</div>
                    <div>Enabled: ${b.enabled ? 'YES' : 'NO'}</div>
                    <div>Scanning: ${b.scan_active ? 'YES' : 'NO'}</div>
                    <div>Devices Found: ${b.devices_found || 0}</div>
                    <div>Scan Count: ${b.scan_count || 0}</div></div>`;
            }

            if (data.nvs) {
                const n = data.nvs;
                const usedPct = n.total_entries > 0 ? ((n.used_entries / n.total_entries) * 100).toFixed(1) : 0;
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">NVS STORAGE</div>
                    <div>Used: ${n.used_entries || 0} / ${n.total_entries || 0} (${usedPct}%)</div>
                    <div>Free: ${n.free_entries || 0}</div></div>`;
            }

            if (data.i2c) {
                const i = data.i2c;
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">I2C BUS</div>
                    <div>Devices: ${i.devices_found || 0}</div>
                    <div>Errors: ${i.errors || 0}</div></div>`;
                if (i.slaves && i.slaves.length > 0) {
                    html += '<div style="margin-left:8px;">';
                    i.slaves.forEach(s => {
                        html += `<div style="color:#888;">  ${s.addr}: OK=${s.success_count || 0} ERR=${(s.nack_count || 0) + (s.timeout_count || 0)}</div>`;
                    });
                    html += '</div>';
                }
            }

            if (data.system) {
                const s = data.system;
                const uptimeH = (s.uptime_s / 3600).toFixed(1);
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">SYSTEM</div>
                    <div>Uptime: ${uptimeH}h</div>
                    <div>Firmware: ${s.firmware || 'N/A'}</div>
                    <div>Board: ${s.board_type || 'N/A'}</div>
                    <div>Reboots: ${s.reboot_count || 0}</div>
                    ${s.cpu_temp_c ? `<div>CPU Temp: ${s.cpu_temp_c}\u00B0C</div>` : ''}
                    ${s.battery_pct != null ? `<div>Battery: ${s.battery_pct}%</div>` : ''}
                    <div>Loop Time: ${s.loop_time_us || 0} \u00B5s</div></div>`;
            }

            if (data.tasks && data.tasks.length > 0) {
                html += `<div style="margin:6px 0 4px;"><div style="color:#00f0ff;font-weight:bold;border-bottom:1px solid #00f0ff33;">TASKS (${data.task_count || data.tasks.length})</div>
                    <div style="max-height:120px;overflow-y:auto;">`;
                data.tasks.forEach(t => {
                    html += `<div style="color:#888;">  ${t.name || 'unknown'}: stack=${t.stack_hwm || '?'} prio=${t.priority || '?'}</div>`;
                });
                html += '</div></div>';
            }

            resultsDiv.innerHTML = html;
        }

        // Initial load
        loadDevices();
    },
};
