// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Meshtastic Addon — Device Config panel
// Shows current device info, connect via serial/TCP, port selection, capabilities

import { EventBus } from '/static/js/command/events.js';
import { _esc } from '/static/js/command/panel-utils.js';

const API_BASE = '/api/addons/meshtastic';

export const MeshConfigPanelDef = {
    id: 'mesh-config',
    title: 'DEVICE CONFIG',
    defaultPosition: { x: 360, y: 60 },
    defaultSize: { w: 340, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mesh-config-panel';
        el.innerHTML = `
            <div class="mesh-cfg-device-section">
                <div class="panel-section-label">DEVICE INFO</div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">NAME</span>
                    <span class="panel-stat-value mono" data-bind="dev-name">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">FIRMWARE</span>
                    <span class="panel-stat-value mono" data-bind="dev-firmware">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">HW MODEL</span>
                    <span class="panel-stat-value mono" data-bind="dev-hw">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">ROLE</span>
                    <span class="panel-stat-value mono" data-bind="dev-role">--</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">STATUS</span>
                    <span class="panel-stat-value" data-bind="dev-status">
                        <span class="panel-dot panel-dot-neutral" data-bind="dev-dot"></span>
                        <span data-bind="dev-status-text" style="color:var(--text-dim,#888)">DISCONNECTED</span>
                    </span>
                </div>
            </div>

            <div class="mesh-cfg-capabilities">
                <div class="panel-section-label">CAPABILITIES</div>
                <div style="display:flex;gap:8px;padding:4px 8px;flex-wrap:wrap;" data-bind="caps">
                    <span class="panel-badge" style="background:var(--surface-2,#1a1a2e);color:var(--text-dim,#888);padding:2px 8px;border-radius:3px;font-size:0.65rem;" data-cap="wifi">WiFi</span>
                    <span class="panel-badge" style="background:var(--surface-2,#1a1a2e);color:var(--text-dim,#888);padding:2px 8px;border-radius:3px;font-size:0.65rem;" data-cap="ble">BLE</span>
                    <span class="panel-badge" style="background:var(--surface-2,#1a1a2e);color:var(--text-dim,#888);padding:2px 8px;border-radius:3px;font-size:0.65rem;" data-cap="gps">GPS</span>
                </div>
            </div>

            <div class="mesh-cfg-connect-section">
                <div class="panel-section-label">CONNECT</div>
                <div style="padding:4px 8px;">
                    <div style="display:flex;gap:6px;margin-bottom:6px;">
                        <label class="mono" style="font-size:0.65rem;color:var(--text-dim,#888);min-width:70px;line-height:26px;">TRANSPORT</label>
                        <select class="panel-filter" data-bind="transport-select" style="flex:1;font-size:0.7rem;">
                            <option value="serial">Serial (USB)</option>
                            <option value="tcp">TCP/IP</option>
                        </select>
                    </div>
                    <div data-bind="serial-fields" style="display:flex;gap:6px;margin-bottom:6px;">
                        <label class="mono" style="font-size:0.65rem;color:var(--text-dim,#888);min-width:70px;line-height:26px;">PORT</label>
                        <select class="panel-filter" data-bind="port-select" style="flex:1;font-size:0.7rem;">
                            <option value="/dev/ttyACM0">/dev/ttyACM0</option>
                            <option value="/dev/ttyUSB0">/dev/ttyUSB0</option>
                            <option value="/dev/ttyACM1">/dev/ttyACM1</option>
                            <option value="/dev/ttyUSB1">/dev/ttyUSB1</option>
                            <option value="COM3">COM3</option>
                            <option value="COM4">COM4</option>
                        </select>
                    </div>
                    <div data-bind="tcp-fields" style="display:none;gap:6px;margin-bottom:6px;">
                        <label class="mono" style="font-size:0.65rem;color:var(--text-dim,#888);min-width:70px;line-height:26px;">HOST</label>
                        <input type="text" class="panel-filter" data-bind="tcp-host"
                               placeholder="192.168.1.50:4403" autocomplete="off"
                               style="flex:1;font-size:0.7rem;" />
                    </div>
                    <div style="display:flex;gap:6px;margin-top:8px;">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="connect"
                                style="flex:1">CONNECT</button>
                        <button class="panel-action-btn" data-action="disconnect"
                                style="flex:1">DISCONNECT</button>
                    </div>
                </div>
            </div>

            <div class="mesh-cfg-future" style="padding:8px;margin-top:auto;">
                <div class="panel-section-label">CONFIGURATION</div>
                <div class="panel-empty" style="font-size:0.65rem;padding:8px;text-align:center;">
                    Name, channel, and role configuration coming soon.
                    <br/>Connect a device to enable settings.
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const devNameEl = bodyEl.querySelector('[data-bind="dev-name"]');
        const devFirmwareEl = bodyEl.querySelector('[data-bind="dev-firmware"]');
        const devHwEl = bodyEl.querySelector('[data-bind="dev-hw"]');
        const devRoleEl = bodyEl.querySelector('[data-bind="dev-role"]');
        const devDot = bodyEl.querySelector('[data-bind="dev-dot"]');
        const devStatusText = bodyEl.querySelector('[data-bind="dev-status-text"]');
        const capsEl = bodyEl.querySelector('[data-bind="caps"]');
        const transportSelect = bodyEl.querySelector('[data-bind="transport-select"]');
        const serialFields = bodyEl.querySelector('[data-bind="serial-fields"]');
        const tcpFields = bodyEl.querySelector('[data-bind="tcp-fields"]');
        const portSelect = bodyEl.querySelector('[data-bind="port-select"]');
        const tcpHostInput = bodyEl.querySelector('[data-bind="tcp-host"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');

        // Transport switching
        if (transportSelect) {
            transportSelect.addEventListener('change', () => {
                const isTcp = transportSelect.value === 'tcp';
                if (serialFields) serialFields.style.display = isTcp ? 'none' : 'flex';
                if (tcpFields) tcpFields.style.display = isTcp ? 'flex' : 'none';
            });
        }

        function updateDevice(data) {
            if (!data) return;
            const connected = data.connected || false;

            if (devDot) {
                devDot.className = connected
                    ? 'panel-dot panel-dot-green'
                    : 'panel-dot panel-dot-neutral';
            }
            if (devStatusText) {
                devStatusText.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
                devStatusText.style.color = connected
                    ? 'var(--green, #05ffa1)'
                    : 'var(--text-dim, #888)';
            }

            const dev = data.device || {};
            if (devNameEl) devNameEl.textContent = _esc(dev.long_name || dev.short_name || '--');
            if (devFirmwareEl) devFirmwareEl.textContent = _esc(dev.firmware_version || '--');
            if (devHwEl) devHwEl.textContent = _esc(dev.hw_model || '--');
            if (devRoleEl) devRoleEl.textContent = _esc(dev.role || '--');

            // Update capability badges
            if (capsEl) {
                const capabilities = dev.capabilities || {};
                ['wifi', 'ble', 'gps'].forEach(cap => {
                    const badge = capsEl.querySelector(`[data-cap="${cap}"]`);
                    if (badge) {
                        const active = capabilities[cap] || false;
                        badge.style.background = active
                            ? 'var(--cyan, #00f0ff)'
                            : 'var(--surface-2, #1a1a2e)';
                        badge.style.color = active
                            ? 'var(--void, #0a0a0f)'
                            : 'var(--text-dim, #888)';
                    }
                });
            }
        }

        // Connect
        if (connectBtn) {
            connectBtn.addEventListener('click', async () => {
                const transport = transportSelect ? transportSelect.value : 'serial';
                let port = '';
                if (transport === 'serial') {
                    port = portSelect ? portSelect.value : '/dev/ttyACM0';
                } else {
                    port = tcpHostInput ? tcpHostInput.value.trim() : '';
                    if (!port) return;
                }

                connectBtn.disabled = true;
                connectBtn.textContent = 'CONNECTING...';
                try {
                    const res = await fetch(API_BASE + '/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ transport, port }),
                    });
                    if (res.ok) {
                        const data = await res.json();
                        updateDevice(data);
                        EventBus.emit('mesh:connected', data);
                    }
                } catch (_) {}
                connectBtn.disabled = false;
                connectBtn.textContent = 'CONNECT';
            });
        }

        // Disconnect
        if (disconnectBtn) {
            disconnectBtn.addEventListener('click', async () => {
                try {
                    await fetch(API_BASE + '/disconnect', { method: 'POST' });
                    updateDevice({ connected: false, transport: 'none', port: '', device: {} });
                    EventBus.emit('mesh:disconnected', {});
                } catch (_) {}
            });
        }

        // EventBus
        panel._unsubs.push(
            EventBus.on('mesh:connected', () => fetchStatus()),
            EventBus.on('mesh:disconnected', () => fetchStatus()),
        );

        async function fetchStatus() {
            try {
                const res = await fetch(API_BASE + '/status');
                if (!res.ok) return;
                const data = await res.json();
                updateDevice(data);
            } catch (_) {}
        }

        // Initial fetch
        fetchStatus();
    },

    unmount(bodyEl, panel) {
        // _unsubs cleaned up by panel base class
    },
};
