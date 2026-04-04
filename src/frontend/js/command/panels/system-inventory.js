// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// System Inventory Panel — full system awareness at a glance.
// Fetches /api/system/inventory and shows:
//   - Panel, router, route, plugin, test, unit type counts
//   - Fleet device status (online/offline)
//   - MQTT connection status
//   - Intelligence model status (trained, accuracy, training count)
//   - Target tracker summary (count by source)
//   - Simulation engine status
//   - Auto-refreshes every 15 seconds

import { _esc } from '/lib/utils.js';

const REFRESH_MS = 15000;
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// ============================================================
// Inventory Card renderer
// ============================================================

function _inventoryCard(label, value, color, icon) {
    return `<div class="si-card">
        <div class="si-card-icon" style="color:${color}">${icon || ''}</div>
        <div class="si-card-value" style="color:${color}">${value}</div>
        <div class="si-card-label">${label}</div>
    </div>`;
}

function _statusDot(active, label) {
    const color = active ? GREEN : MAGENTA;
    const text = active ? 'ACTIVE' : 'INACTIVE';
    return `<div style="display:flex;align-items:center;gap:4px;padding:2px 0;">
        <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color};box-shadow:0 0 6px ${color};"></span>
        <span style="color:#aaa;font-size:10px;font-family:monospace;">${_esc(label)}</span>
        <span style="color:${color};font-size:10px;font-family:monospace;margin-left:auto;">${text}</span>
    </div>`;
}

function _sourcePill(source, count) {
    const colors = {
        simulation: CYAN,
        camera: YELLOW,
        ble: GREEN,
        wifi: '#a855f7',
        mesh: '#f97316',
        mqtt: '#06b6d4',
    };
    const color = colors[source] || DIM;
    return `<span style="display:inline-block;padding:1px 6px;border:1px solid ${color};border-radius:8px;font-size:9px;font-family:monospace;color:${color};margin:1px 2px;">${_esc(source)}: ${count}</span>`;
}

// ============================================================
// Panel Definition
// ============================================================

export const SystemInventoryPanelDef = {
    id: 'system-inventory',
    title: 'SYSTEM INVENTORY',
    defaultPosition: { x: 250, y: 70 },
    defaultSize: { w: 460, h: 540 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;font-size:12px;color:#c0c0c0;">
                <div style="display:flex;gap:4px;margin-bottom:8px;align-items:center;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                    <span data-bind="last-update" style="margin-left:auto;font-size:9px;color:${DIM};font-family:monospace;">--</span>
                </div>

                <!-- System Counts Grid -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">System Components</div>
                <div data-bind="counts-grid" class="si-counts-grid" style="margin-bottom:10px;">
                    <div style="color:${DIM};text-align:center;padding:12px;font-size:10px;grid-column:1/-1;">Loading...</div>
                </div>

                <!-- Subsystem Status -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Subsystems</div>
                <div data-bind="subsystems" style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;margin-bottom:10px;">
                    <div style="color:${DIM};text-align:center;padding:4px;font-size:10px;">Loading...</div>
                </div>

                <!-- Intelligence -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Intelligence</div>
                <div data-bind="intelligence" style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;margin-bottom:10px;">
                    <div style="color:${DIM};text-align:center;padding:4px;font-size:10px;">Loading...</div>
                </div>

                <!-- Targets by Source -->
                <div style="color:${MAGENTA};font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Targets by Source</div>
                <div data-bind="targets-sources" style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;margin-bottom:10px;">
                    <div style="color:${DIM};text-align:center;padding:4px;font-size:10px;">Loading...</div>
                </div>
            </div>

            <style>
                .si-counts-grid {
                    display: grid;
                    grid-template-columns: repeat(4, 1fr);
                    gap: 6px;
                }
                .si-card {
                    background: ${SURFACE};
                    border: 1px solid ${BORDER};
                    padding: 8px 6px;
                    text-align: center;
                    position: relative;
                }
                .si-card-icon {
                    font-size: 14px;
                    margin-bottom: 2px;
                }
                .si-card-value {
                    font-size: 20px;
                    font-family: monospace;
                    font-weight: bold;
                }
                .si-card-label {
                    font-size: 8px;
                    color: ${DIM};
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                    margin-top: 2px;
                }
            </style>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const countsGrid = bodyEl.querySelector('[data-bind="counts-grid"]');
        const subsystemsEl = bodyEl.querySelector('[data-bind="subsystems"]');
        const intelligenceEl = bodyEl.querySelector('[data-bind="intelligence"]');
        const targetsSourcesEl = bodyEl.querySelector('[data-bind="targets-sources"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        async function fetchData() {
            try {
                const resp = await fetch('/api/system/inventory');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                // Counts grid
                if (countsGrid) {
                    const panels = data.panels || {};
                    const routers = data.routers || {};
                    const plugins = data.plugins || {};
                    const tests = data.tests || {};

                    countsGrid.innerHTML = [
                        _inventoryCard('Panels', panels.file_count || 0, CYAN, '[]'),
                        _inventoryCard('Routers', routers.file_count || 0, GREEN, '//'),
                        _inventoryCard('Routes', routers.registered_routes || 0, YELLOW, '->'),
                        _inventoryCard('Plugins', plugins.directory_count || 0, MAGENTA, '++'),
                        _inventoryCard('Tests', tests.file_count || 0, CYAN, '()'),
                        _inventoryCard('Unit Types', data.unit_types || 0, GREEN, 'U'),
                        _inventoryCard('DB Models', (data.models || {}).sqlalchemy || 0, YELLOW, 'DB'),
                        _inventoryCard('Targets', (data.tracker || {}).target_count || 0, MAGENTA, '#'),
                    ].join('');
                }

                // Subsystem status
                if (subsystemsEl) {
                    const fleet = data.fleet || {};
                    const sim = data.simulation || {};

                    let html = '';
                    html += _statusDot(fleet.mqtt_connected, 'MQTT Broker');
                    html += _statusDot(fleet.device_count > 0, `Fleet (${fleet.online_count || 0}/${fleet.device_count || 0} online)`);
                    html += _statusDot(sim.enabled, `Simulation Engine${sim.running ? ' (running)' : ''}`);
                    if (sim.sim_target_count !== undefined) {
                        html += `<div style="padding:2px 0 2px 10px;font-size:10px;font-family:monospace;color:${DIM};">Sim targets: <span style="color:${CYAN}">${sim.sim_target_count}</span></div>`;
                    }
                    subsystemsEl.innerHTML = html;
                }

                // Intelligence
                if (intelligenceEl) {
                    const intel = data.intelligence || {};
                    const corr = intel.correlation_model || {};
                    const training = intel.training_data || {};

                    let html = '<div style="font-family:monospace;font-size:10px;">';
                    html += `<div style="display:flex;justify-content:space-between;padding:2px 0;">
                        <span style="color:${DIM}">Correlation Model</span>
                        <span style="color:${corr.trained ? GREEN : YELLOW}">${corr.trained ? 'TRAINED' : 'UNTRAINED'}</span>
                    </div>`;
                    html += `<div style="display:flex;justify-content:space-between;padding:2px 0;">
                        <span style="color:${DIM}">Accuracy</span>
                        <span style="color:${(corr.accuracy || 0) > 0.7 ? GREEN : (corr.accuracy || 0) > 0.4 ? YELLOW : MAGENTA}">${((corr.accuracy || 0) * 100).toFixed(1)}%</span>
                    </div>`;
                    html += `<div style="display:flex;justify-content:space-between;padding:2px 0;">
                        <span style="color:${DIM}">Training Count</span>
                        <span style="color:${CYAN}">${corr.training_count || 0}</span>
                    </div>`;

                    if (training && Object.keys(training).length > 0) {
                        html += `<div style="border-top:1px solid ${BORDER};margin-top:4px;padding-top:4px;">`;
                        for (const [key, val] of Object.entries(training)) {
                            html += `<div style="display:flex;justify-content:space-between;padding:1px 0;">
                                <span style="color:${DIM}">${_esc(key)}</span>
                                <span style="color:#aaa">${typeof val === 'number' ? val.toLocaleString() : _esc(String(val))}</span>
                            </div>`;
                        }
                        html += '</div>';
                    }

                    html += '</div>';
                    intelligenceEl.innerHTML = html;
                }

                // Targets by source
                if (targetsSourcesEl) {
                    const tracker = data.tracker || {};
                    const bySrc = tracker.by_source || {};

                    if (Object.keys(bySrc).length === 0) {
                        targetsSourcesEl.innerHTML = `<div style="display:flex;align-items:center;gap:8px;">
                            <span style="font-size:10px;font-family:monospace;color:${DIM};">Total:</span>
                            <span style="font-size:16px;font-family:monospace;color:${CYAN};">${tracker.target_count || 0}</span>
                            <span style="font-size:10px;font-family:monospace;color:${DIM};margin-left:8px;">No source breakdown</span>
                        </div>`;
                    } else {
                        let html = `<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
                            <span style="font-size:10px;font-family:monospace;color:${DIM};">Total:</span>
                            <span style="font-size:16px;font-family:monospace;color:${CYAN};">${tracker.target_count || 0}</span>
                        </div><div style="display:flex;flex-wrap:wrap;gap:2px;">`;
                        for (const [src, count] of Object.entries(bySrc).sort((a, b) => b[1] - a[1])) {
                            html += _sourcePill(src, count);
                        }
                        html += '</div>';
                        targetsSourcesEl.innerHTML = html;
                    }
                }

                // Update timestamp
                if (lastUpdateEl) {
                    lastUpdateEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
                }

            } catch (e) {
                console.error('[SystemInventory] fetch failed:', e);
                if (countsGrid) {
                    countsGrid.innerHTML = `<div style="color:${MAGENTA};text-align:center;padding:12px;font-size:10px;grid-column:1/-1;">Failed to load system inventory</div>`;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchData);

        // Initial fetch and timer
        fetchData();
        panel._siTimer = setInterval(fetchData, REFRESH_MS);
    },

    unmount(bodyEl, panel) {
        if (panel && panel._siTimer) {
            clearInterval(panel._siTimer);
            panel._siTimer = null;
        }
    },
};
