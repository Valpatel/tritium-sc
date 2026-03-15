// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Sensor Health Panel — grid showing all sensors with health indicators,
// sighting rate sparklines, last-seen timestamps, and degraded alerts.

import { EventBus } from '../events.js';
import { _esc, _timeAgo } from '../panel-utils.js';

const REFRESH_INTERVAL = 10000; // 10s

function _healthDot(health) {
    const colors = {
        green: 'var(--green, #05ffa1)',
        yellow: 'var(--yellow, #fcee0a)',
        red: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[health] || 'var(--text-dim, #888)';
    return `<span class="sh-health-dot" style="background:${color};box-shadow:0 0 6px ${color}"></span>`;
}

function _sparklineSvg(data, width, height) {
    if (!data || data.length < 2) {
        return `<svg width="${width}" height="${height}" class="sh-sparkline"><text x="${width/2}" y="${height/2+3}" text-anchor="middle" fill="var(--text-dim, #666)" font-size="8">--</text></svg>`;
    }
    const max = Math.max(...data, 1);
    const step = width / (data.length - 1);
    const points = data.map((v, i) => `${i * step},${height - (v / max) * (height - 4) - 2}`).join(' ');
    return `<svg width="${width}" height="${height}" class="sh-sparkline">
        <polyline points="${points}" fill="none" stroke="var(--cyan, #00f0ff)" stroke-width="1.5" opacity="0.8"/>
    </svg>`;
}

function _sensorTypeIcon(type) {
    const icons = {
        edge_node: 'E',
        camera: 'C',
        mesh_radio: 'M',
        none: '?',
    };
    return icons[type] || '?';
}

function _sensorTypeLabel(type) {
    const labels = {
        edge_node: 'EDGE',
        camera: 'CAM',
        mesh_radio: 'MESH',
        none: 'N/A',
    };
    return labels[type] || type.toUpperCase();
}

// ============================================================
// Panel Definition
// ============================================================

export const SensorHealthPanelDef = {
    id: 'sensor-health',
    title: 'SENSOR HEALTH',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 520, h: 420 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'sh-inner';
        el.innerHTML = `
            <div class="sh-summary" data-bind="summary">
                <div class="sh-stat">
                    <span class="sh-stat-value mono" style="color:var(--green, #05ffa1)" data-bind="healthy">0</span>
                    <span class="sh-stat-label">HEALTHY</span>
                </div>
                <div class="sh-stat">
                    <span class="sh-stat-value mono" style="color:var(--yellow, #fcee0a)" data-bind="degraded">0</span>
                    <span class="sh-stat-label">DEGRADED</span>
                </div>
                <div class="sh-stat">
                    <span class="sh-stat-value mono" data-bind="total">0</span>
                    <span class="sh-stat-label">TOTAL</span>
                </div>
                <button class="panel-action-btn" data-action="refresh" title="Refresh sensor health">REFRESH</button>
            </div>
            <div class="sh-alert-bar" data-bind="alerts" style="display:none"></div>
            <div class="sh-grid-wrap" data-bind="grid">
                <div class="panel-empty">Loading sensor health...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const gridEl = bodyEl.querySelector('[data-bind="grid"]');
        const alertBar = bodyEl.querySelector('[data-bind="alerts"]');
        const healthyEl = bodyEl.querySelector('[data-bind="healthy"]');
        const degradedEl = bodyEl.querySelector('[data-bind="degraded"]');
        const totalEl = bodyEl.querySelector('[data-bind="total"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let sensors = [];
        let timer = null;

        async function fetchHealth() {
            try {
                const resp = await fetch('/api/sensors/health');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                sensors = data.sensors || [];

                // Update summary
                if (healthyEl) healthyEl.textContent = data.healthy || 0;
                if (degradedEl) degradedEl.textContent = data.degraded || 0;
                if (totalEl) totalEl.textContent = data.total || 0;

                // Alert bar for degraded sensors
                const degradedSensors = sensors.filter(s => s.health !== 'green');
                if (degradedSensors.length > 0 && alertBar) {
                    alertBar.style.display = '';
                    alertBar.innerHTML = `<span class="sh-alert-icon">!</span> ${degradedSensors.length} sensor${degradedSensors.length > 1 ? 's' : ''} degraded: ${degradedSensors.map(s => _esc(s.name)).join(', ')}`;
                } else if (alertBar) {
                    alertBar.style.display = 'none';
                }

                render();
            } catch (e) {
                console.error('[SensorHealth] fetch failed:', e);
                if (gridEl) gridEl.innerHTML = '<div class="panel-empty">Failed to load sensor health</div>';
            }
        }

        function render() {
            if (!gridEl) return;
            if (sensors.length === 0) {
                gridEl.innerHTML = '<div class="panel-empty">No sensors registered</div>';
                return;
            }

            let html = '<div class="sh-grid">';
            for (const s of sensors) {
                const lastSeen = s.last_seen ? _timeAgo(s.last_seen) : 'never';
                const batteryHtml = s.battery_pct !== null && s.battery_pct !== undefined
                    ? `<span class="sh-battery mono">${s.battery_pct}%</span>`
                    : '';
                const rate = typeof s.sighting_rate === 'number' ? `${s.sighting_rate}/min` : '--';

                html += `
                    <div class="sh-card sh-card-${_esc(s.health)}">
                        <div class="sh-card-header">
                            ${_healthDot(s.health)}
                            <span class="sh-card-name mono">${_esc(s.name)}</span>
                            <span class="sh-card-type">${_sensorTypeLabel(s.type)}</span>
                        </div>
                        <div class="sh-card-sparkline">
                            ${_sparklineSvg(s.sparkline, 120, 24)}
                        </div>
                        <div class="sh-card-footer">
                            <span class="sh-card-rate mono">${rate}</span>
                            ${batteryHtml}
                            <span class="sh-card-seen">${lastSeen}</span>
                        </div>
                    </div>
                `;
            }
            html += '</div>';
            gridEl.innerHTML = html;
        }

        // Initial fetch
        fetchHealth();
        timer = setInterval(fetchHealth, REFRESH_INTERVAL);

        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchHealth);
        }

        // Store cleanup ref
        panel._shTimer = timer;
    },

    unmount(bodyEl, panel) {
        if (panel && panel._shTimer) {
            clearInterval(panel._shTimer);
            panel._shTimer = null;
        }
    },
};
