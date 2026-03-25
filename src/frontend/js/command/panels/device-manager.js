// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Device Manager Panel — remote OTA, reboot, config, and screenshot for edge devices
// Displays device list with per-device controls for fleet management operations.

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';



function _formatUptime(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
}

function _formatBytes(bytes) {
    if (!bytes && bytes !== 0) return '--';
    if (bytes > 1048576) return `${(bytes / 1048576).toFixed(1)}MB`;
    if (bytes > 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${bytes}B`;
}

function _statusDot(status) {
    const colors = {
        online: 'var(--green, #05ffa1)',
        stale: 'var(--yellow, #fcee0a)',
        offline: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[status] || 'var(--text-dim, #888)';
    return `<span class="dm-status-dot" style="background:${color}" title="${(status || 'unknown').toUpperCase()}"></span>`;
}

// ============================================================
// Panel Definition
// ============================================================

export const DeviceManagerPanelDef = {
    id: 'device-manager',
    title: 'DEVICE MANAGER',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 680, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'dm-inner';
        el.innerHTML = `
            <div class="dm-toolbar">
                <div class="dm-toolbar-left">
                    <button class="panel-action-btn dm-btn" data-action="refresh" title="Refresh device list">REFRESH</button>
                    <button class="panel-action-btn dm-btn dm-btn-warn" data-action="reboot-selected" title="Reboot selected devices" disabled>REBOOT SELECTED</button>
                    <label class="dm-select-all-label">
                        <input type="checkbox" data-action="select-all" /> ALL
                    </label>
                </div>
                <div class="dm-toolbar-right">
                    <span class="mono dm-device-count" data-bind="device-count">0 devices</span>
                </div>
            </div>
            <div class="dm-list-wrap" data-bind="list-wrap">
                <div class="dm-device-list" data-bind="device-list">
                    <div class="panel-empty">Loading devices...</div>
                </div>
            </div>
            <div class="dm-detail-pane" data-bind="detail-pane" style="display:none;">
                <div class="dm-detail-header">
                    <button class="panel-action-btn dm-btn-sm" data-action="back-to-list">BACK</button>
                    <span class="mono dm-detail-title" data-bind="detail-title">--</span>
                </div>
                <div class="dm-detail-body" data-bind="detail-body"></div>
            </div>
            <div class="dm-footer">
                <span class="mono" style="color:var(--text-dim)" data-bind="status-msg">--</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const deviceListEl = bodyEl.querySelector('[data-bind="device-list"]');
        const listWrapEl = bodyEl.querySelector('[data-bind="list-wrap"]');
        const detailPaneEl = bodyEl.querySelector('[data-bind="detail-pane"]');
        const detailTitleEl = bodyEl.querySelector('[data-bind="detail-title"]');
        const detailBodyEl = bodyEl.querySelector('[data-bind="detail-body"]');
        const deviceCountEl = bodyEl.querySelector('[data-bind="device-count"]');
        const statusMsgEl = bodyEl.querySelector('[data-bind="status-msg"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const rebootSelectedBtn = bodyEl.querySelector('[data-action="reboot-selected"]');
        const selectAllCb = bodyEl.querySelector('[data-action="select-all"]');
        const backBtn = bodyEl.querySelector('[data-action="back-to-list"]');

        let devices = [];
        let selectedIds = new Set();
        let refreshInterval = null;
        let currentDetailId = null;

        function setStatus(msg) {
            if (statusMsgEl) statusMsgEl.textContent = msg;
        }

        // -- Fetch devices --
        async function fetchDevices() {
            try {
                const res = await fetch('/api/fleet/devices');
                if (!res.ok) { setStatus('API error'); return; }
                const data = await res.json();
                devices = data.devices || [];
                renderDeviceList();
                if (deviceCountEl) deviceCountEl.textContent = `${devices.length} device${devices.length !== 1 ? 's' : ''}`;
                setStatus(`Updated ${new Date().toLocaleTimeString()}`);
            } catch (err) {
                setStatus('Fetch error');
            }
        }

        // -- Render device list --
        function renderDeviceList() {
            if (!deviceListEl) return;
            if (devices.length === 0) {
                deviceListEl.innerHTML = '<div class="panel-empty">No fleet devices detected</div>';
                return;
            }

            const order = { online: 0, stale: 1, offline: 2 };
            devices.sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9));

            deviceListEl.innerHTML = devices.map(d => {
                const did = d.device_id || d.name || '--';
                const checked = selectedIds.has(did) ? 'checked' : '';
                return `<div class="dm-device-card" data-device-id="${_esc(did)}">
                    <div class="dm-card-header">
                        <label class="dm-card-check">
                            <input type="checkbox" class="dm-select-device" data-id="${_esc(did)}" ${checked} />
                        </label>
                        ${_statusDot(d.status)}
                        <span class="mono dm-card-name" title="${_esc(did)}">${_esc(did)}</span>
                        <span class="mono dm-card-ip" style="color:var(--text-dim)">${_esc(d.ip || '')}</span>
                    </div>
                    <div class="dm-card-stats">
                        <span class="dm-stat" title="Firmware">${_esc(d.firmware || d.version || '--')}</span>
                        <span class="dm-stat" title="Uptime">${_formatUptime(d.uptime)}</span>
                        <span class="dm-stat" title="Free Heap">${_formatBytes(d.free_heap)}</span>
                        <span class="dm-stat" title="Last Seen">${_timeAgo(d.last_seen)}</span>
                    </div>
                    <div class="dm-card-actions">
                        <button class="panel-action-btn dm-btn-sm" data-action="detail" data-id="${_esc(did)}">DETAILS</button>
                        <button class="panel-action-btn dm-btn-sm" data-action="reboot" data-id="${_esc(did)}">REBOOT</button>
                        <button class="panel-action-btn dm-btn-sm" data-action="ota" data-id="${_esc(did)}">OTA</button>
                        <button class="panel-action-btn dm-btn-sm" data-action="screenshot" data-id="${_esc(did)}">SCREENSHOT</button>
                    </div>
                </div>`;
            }).join('');

            // Bind card action buttons
            deviceListEl.querySelectorAll('[data-action="reboot"]').forEach(btn => {
                btn.addEventListener('click', () => rebootDevice(btn.dataset.id));
            });
            deviceListEl.querySelectorAll('[data-action="ota"]').forEach(btn => {
                btn.addEventListener('click', () => otaDevice(btn.dataset.id));
            });
            deviceListEl.querySelectorAll('[data-action="screenshot"]').forEach(btn => {
                btn.addEventListener('click', () => screenshotDevice(btn.dataset.id));
            });
            deviceListEl.querySelectorAll('[data-action="detail"]').forEach(btn => {
                btn.addEventListener('click', () => showDetail(btn.dataset.id));
            });
            deviceListEl.querySelectorAll('.dm-select-device').forEach(cb => {
                cb.addEventListener('change', () => {
                    if (cb.checked) selectedIds.add(cb.dataset.id);
                    else selectedIds.delete(cb.dataset.id);
                    updateBulkButton();
                });
            });
        }

        function updateBulkButton() {
            if (rebootSelectedBtn) rebootSelectedBtn.disabled = selectedIds.size === 0;
        }

        // -- Device actions --
        async function rebootDevice(deviceId) {
            setStatus(`Rebooting ${deviceId}...`);
            try {
                const res = await fetch(`/api/devices/${encodeURIComponent(deviceId)}/reboot`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    setStatus(`Reboot sent to ${deviceId} via ${data.via}`);
                } else {
                    setStatus(`Reboot failed: ${data.error || 'unknown'}`);
                }
            } catch (err) {
                setStatus(`Reboot error: ${err.message}`);
            }
        }

        function otaDevice(deviceId) {
            // Create hidden file input for firmware upload
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.bin,.elf';
            input.style.display = 'none';
            input.addEventListener('change', async () => {
                const file = input.files[0];
                if (!file) return;
                setStatus(`Uploading ${file.name} to ${deviceId}...`);
                const formData = new FormData();
                formData.append('firmware', file);
                try {
                    const res = await fetch(`/api/devices/${encodeURIComponent(deviceId)}/ota`, {
                        method: 'POST',
                        body: formData,
                    });
                    const data = await res.json();
                    if (res.ok) {
                        setStatus(`OTA ${data.status}: ${file.name} -> ${deviceId} via ${data.via}`);
                    } else {
                        setStatus(`OTA failed: ${data.error || 'unknown'}`);
                    }
                } catch (err) {
                    setStatus(`OTA error: ${err.message}`);
                }
                input.remove();
            });
            document.body.appendChild(input);
            input.click();
        }

        async function screenshotDevice(deviceId) {
            setStatus(`Requesting screenshot from ${deviceId}...`);
            try {
                const res = await fetch(`/api/devices/${encodeURIComponent(deviceId)}/screenshot`, { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    setStatus(`Screenshot ${data.status} from ${deviceId} via ${data.via}`);
                    if (data.url) {
                        window.open(data.url, '_blank');
                    }
                } else {
                    setStatus(`Screenshot failed: ${data.error || 'unknown'}`);
                }
            } catch (err) {
                setStatus(`Screenshot error: ${err.message}`);
            }
        }

        // -- Detail view --
        async function showDetail(deviceId) {
            currentDetailId = deviceId;
            if (listWrapEl) listWrapEl.style.display = 'none';
            if (detailPaneEl) detailPaneEl.style.display = 'flex';
            if (detailTitleEl) detailTitleEl.textContent = deviceId;

            if (detailBodyEl) {
                detailBodyEl.innerHTML = '<div class="panel-empty">Loading device details...</div>';

                try {
                    const [configRes, diagRes] = await Promise.allSettled([
                        fetch(`/api/devices/${encodeURIComponent(deviceId)}/config`),
                        fetch(`/api/fleet/node/${encodeURIComponent(deviceId)}/diag`),
                    ]);

                    let configData = null;
                    let diagData = null;

                    if (configRes.status === 'fulfilled' && configRes.value.ok) {
                        configData = await configRes.value.json();
                    }
                    if (diagRes.status === 'fulfilled' && diagRes.value.ok) {
                        diagData = await diagRes.value.json();
                    }

                    // Find device in local list
                    const dev = devices.find(d => (d.device_id || d.name) === deviceId) || {};

                    detailBodyEl.innerHTML = `
                        <div class="dm-detail-section">
                            <h4 class="dm-section-title">DEVICE INFO</h4>
                            <div class="dm-detail-grid">
                                <span class="dm-label">Device ID</span><span class="mono">${_esc(deviceId)}</span>
                                <span class="dm-label">IP Address</span><span class="mono">${_esc(dev.ip || configData?.config?.ip || '--')}</span>
                                <span class="dm-label">Firmware</span><span class="mono">${_esc(dev.firmware || dev.version || configData?.config?.firmware || '--')}</span>
                                <span class="dm-label">Board</span><span class="mono">${_esc(configData?.config?.board || '--')}</span>
                                <span class="dm-label">MAC</span><span class="mono">${_esc(configData?.config?.mac || '--')}</span>
                                <span class="dm-label">Uptime</span><span class="mono">${_formatUptime(dev.uptime)}</span>
                                <span class="dm-label">Free Heap</span><span class="mono">${_formatBytes(dev.free_heap)}</span>
                                <span class="dm-label">RSSI</span><span class="mono">${dev.rssi != null ? dev.rssi + ' dBm' : '--'}</span>
                                <span class="dm-label">Status</span><span>${_statusDot(dev.status)} ${(dev.status || 'unknown').toUpperCase()}</span>
                                <span class="dm-label">Last Seen</span><span class="mono">${_timeAgo(dev.last_seen)}</span>
                            </div>
                        </div>

                        ${diagData ? `
                        <div class="dm-detail-section">
                            <h4 class="dm-section-title">DIAGNOSTICS</h4>
                            <div class="dm-detail-grid">
                                ${diagData.health ? Object.entries(diagData.health).map(([k, v]) =>
                                    `<span class="dm-label">${_esc(k)}</span><span class="mono">${_esc(String(v))}</span>`
                                ).join('') : '<span class="dm-label">Health</span><span class="mono">--</span>'}
                            </div>
                            ${diagData.i2c_slaves && diagData.i2c_slaves.length > 0 ? `
                                <h4 class="dm-section-title" style="margin-top:8px">I2C PERIPHERALS</h4>
                                <div class="dm-periph-list">
                                    ${diagData.i2c_slaves.map(s => `<span class="dm-periph mono">${_esc(s.addr || s)}</span>`).join('')}
                                </div>
                            ` : ''}
                            ${diagData.anomalies && diagData.anomalies.length > 0 ? `
                                <h4 class="dm-section-title" style="margin-top:8px;color:var(--magenta)">ANOMALIES</h4>
                                <div class="dm-anomaly-list">
                                    ${diagData.anomalies.map(a => `<div class="dm-anomaly">${_esc(typeof a === 'string' ? a : a.description || JSON.stringify(a))}</div>`).join('')}
                                </div>
                            ` : ''}
                        </div>
                        ` : ''}

                        <div class="dm-detail-section">
                            <h4 class="dm-section-title">CONFIGURATION</h4>
                            <div class="dm-config-editor" data-bind="config-editor">
                                ${configData?.config ? `
                                    <div class="dm-config-group">
                                        <label class="dm-label">WiFi SSID</label>
                                        <input type="text" class="dm-input" data-config="wifi.ssid" value="${_esc(configData.config.wifi?.ssid || '')}" />
                                    </div>
                                    <div class="dm-config-group">
                                        <label class="dm-label">WiFi Password</label>
                                        <input type="password" class="dm-input" data-config="wifi.password" value="" placeholder="(unchanged)" />
                                    </div>
                                    <div class="dm-config-group">
                                        <label class="dm-label">MQTT Broker</label>
                                        <input type="text" class="dm-input" data-config="mqtt.broker" value="${_esc(configData.config.mqtt?.broker || '')}" />
                                    </div>
                                    <div class="dm-config-group">
                                        <label class="dm-label">Display Brightness</label>
                                        <input type="range" class="dm-input" data-config="display.brightness" min="0" max="255" value="${configData.config.display?.brightness ?? 128}" />
                                    </div>
                                ` : '<div class="panel-empty">Config not available</div>'}
                                <button class="panel-action-btn dm-btn" data-action="save-config">SAVE CONFIG</button>
                            </div>
                        </div>

                        <div class="dm-detail-section">
                            <h4 class="dm-section-title">ACTIONS</h4>
                            <div class="dm-action-bar">
                                <button class="panel-action-btn dm-btn" data-action="detail-reboot">REBOOT</button>
                                <button class="panel-action-btn dm-btn" data-action="detail-ota">OTA FLASH</button>
                                <button class="panel-action-btn dm-btn" data-action="detail-screenshot">SCREENSHOT</button>
                                ${dev.ip ? `<a class="panel-action-btn dm-btn" href="http://${_esc(dev.ip)}" target="_blank" rel="noopener">OPEN WEB UI</a>` : ''}
                            </div>
                        </div>
                    `;

                    // Bind detail action buttons
                    const detailReboot = detailBodyEl.querySelector('[data-action="detail-reboot"]');
                    if (detailReboot) detailReboot.addEventListener('click', () => rebootDevice(deviceId));

                    const detailOta = detailBodyEl.querySelector('[data-action="detail-ota"]');
                    if (detailOta) detailOta.addEventListener('click', () => otaDevice(deviceId));

                    const detailScreenshot = detailBodyEl.querySelector('[data-action="detail-screenshot"]');
                    if (detailScreenshot) detailScreenshot.addEventListener('click', () => screenshotDevice(deviceId));

                    const saveConfigBtn = detailBodyEl.querySelector('[data-action="save-config"]');
                    if (saveConfigBtn) saveConfigBtn.addEventListener('click', () => saveConfig(deviceId));

                } catch (err) {
                    detailBodyEl.innerHTML = `<div class="panel-empty">Error loading details: ${_esc(err.message)}</div>`;
                }
            }
        }

        function hideDetail() {
            currentDetailId = null;
            if (listWrapEl) listWrapEl.style.display = '';
            if (detailPaneEl) detailPaneEl.style.display = 'none';
        }

        async function saveConfig(deviceId) {
            const editor = detailBodyEl.querySelector('[data-bind="config-editor"]');
            if (!editor) return;

            const config = {};
            editor.querySelectorAll('[data-config]').forEach(input => {
                const path = input.dataset.config;
                const value = input.type === 'range' ? parseInt(input.value, 10) : input.value;
                if (input.type === 'password' && !value) return; // Skip empty passwords
                const parts = path.split('.');
                let obj = config;
                for (let i = 0; i < parts.length - 1; i++) {
                    if (!obj[parts[i]]) obj[parts[i]] = {};
                    obj = obj[parts[i]];
                }
                obj[parts[parts.length - 1]] = value;
            });

            if (Object.keys(config).length === 0) {
                setStatus('No config changes to save');
                return;
            }

            setStatus(`Saving config for ${deviceId}...`);
            try {
                const res = await fetch(`/api/devices/${encodeURIComponent(deviceId)}/config`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config),
                });
                const data = await res.json();
                if (res.ok) {
                    setStatus(`Config saved for ${deviceId} via ${data.via}: ${data.fields_updated?.join(', ')}`);
                } else {
                    setStatus(`Config save failed: ${data.error || data.detail || 'unknown'}`);
                }
            } catch (err) {
                setStatus(`Config save error: ${err.message}`);
            }
        }

        // -- Bulk operations --
        async function rebootSelected() {
            if (selectedIds.size === 0) return;
            setStatus(`Rebooting ${selectedIds.size} devices...`);
            try {
                const res = await fetch('/api/devices/bulk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        device_ids: Array.from(selectedIds),
                        action: 'reboot',
                    }),
                });
                const data = await res.json();
                if (res.ok) {
                    setStatus(`Bulk reboot: ${data.succeeded}/${data.total} succeeded`);
                } else {
                    setStatus(`Bulk reboot failed: ${data.error || data.detail || 'unknown'}`);
                }
            } catch (err) {
                setStatus(`Bulk reboot error: ${err.message}`);
            }
        }

        // -- Event bindings --
        if (refreshBtn) refreshBtn.addEventListener('click', fetchDevices);
        if (rebootSelectedBtn) rebootSelectedBtn.addEventListener('click', rebootSelected);
        if (backBtn) backBtn.addEventListener('click', hideDetail);
        if (selectAllCb) {
            selectAllCb.addEventListener('change', () => {
                if (selectAllCb.checked) {
                    devices.forEach(d => selectedIds.add(d.device_id || d.name || '--'));
                } else {
                    selectedIds.clear();
                }
                renderDeviceList();
                updateBulkButton();
            });
        }

        // Initial fetch
        fetchDevices();

        // Auto-refresh every 15s
        refreshInterval = setInterval(fetchDevices, 15000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Refresh on fleet heartbeat events
        const unsub = EventBus.on('fleet:heartbeat', fetchDevices);
        if (unsub) panel._unsubs.push(unsub);
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },
};
