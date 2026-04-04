// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * City Simulation Panel — controls for the OSM-based city simulation.
 *
 * Start/stop simulation, adjust vehicle/pedestrian counts, view stats,
 * select scenarios, monitor anomaly feed, toggle sensor bridge.
 */

import { EventBus } from '/lib/events.js';
import { BUILT_IN_SCENARIOS } from '../sim/scenario-loader.js';

export const CitySimPanelDef = {
    id: 'city-sim',
    title: 'CITY SIMULATION',
    category: 'simulation',
    defaultPosition: { x: 20, y: 100 },
    defaultSize: { w: 280, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'csim-panel';
        el.innerHTML = `
            <div class="csim-status">
                <div class="csim-row">
                    <span class="csim-label mono">STATUS</span>
                    <span class="csim-value mono csim-status-val" data-bind="status">IDLE</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">TIME</span>
                    <span class="csim-value mono" data-bind="time">--:--</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">WEATHER</span>
                    <span class="csim-value mono" data-bind="weather">CLEAR</span>
                </div>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">ENTITIES</div>
                <div class="csim-row">
                    <span class="csim-label mono">VEHICLES</span>
                    <span class="csim-value mono" data-bind="vehicles">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">AVG SPEED</span>
                    <span class="csim-value mono" data-bind="avgSpeed">0 km/h</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">PEDESTRIANS</span>
                    <span class="csim-value mono" data-bind="pedestrians">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">IN BUILDING</span>
                    <span class="csim-value mono" data-bind="inBuilding">0</span>
                </div>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">INFRASTRUCTURE</div>
                <div class="csim-row">
                    <span class="csim-label mono">ROAD NODES</span>
                    <span class="csim-value mono" data-bind="nodes">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">ROAD EDGES</span>
                    <span class="csim-value mono" data-bind="edges">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">TRAFFIC CTRL</span>
                    <span class="csim-value mono" data-bind="trafficCtrl">0</span>
                </div>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">ANOMALIES</div>
                <div class="csim-row">
                    <span class="csim-label mono">BASELINE</span>
                    <span class="csim-value mono" data-bind="baseline">--</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">DETECTIONS</span>
                    <span class="csim-value mono" data-bind="detections">0</span>
                </div>
                <div class="csim-anomaly-feed" data-bind="anomalyFeed"></div>
            </div>

            <div class="csim-section csim-protest-section" style="display:none" data-bind="protestSection">
                <div class="csim-section-title mono" style="color:#ff2a6d">PROTEST</div>
                <div class="csim-row">
                    <span class="csim-label mono">PHASE</span>
                    <span class="csim-value mono" style="color:#ff2a6d" data-bind="protestPhase">--</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">ACTIVE</span>
                    <span class="csim-value mono" data-bind="protestActive">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">ARRESTED</span>
                    <span class="csim-value mono" data-bind="protestArrested">0</span>
                </div>
                <div class="csim-row">
                    <span class="csim-label mono">LEGITIMACY</span>
                    <span class="csim-value mono" data-bind="protestLegitimacy">--</span>
                </div>
                <div class="csim-protest-phases mono" style="font-size:9px;color:#666;margin-top:4px" data-bind="protestTimeline"></div>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">SCENARIO</div>
                <select class="csim-scenario-select" data-bind="scenario">
                    <option value="">-- Select --</option>
                    ${BUILT_IN_SCENARIOS.map(s =>
                        `<option value="${s.id}">${s.name} (${s.vehicles} cars, ${s.pedestrians} people)</option>`
                    ).join('\n                    ')}
                </select>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">METRICS</div>
                <div class="csim-sparkline-row">
                    <span class="csim-label mono">VEHICLES</span>
                    <canvas class="csim-sparkline" data-sparkline="vehicles" width="60" height="18"></canvas>
                </div>
                <div class="csim-sparkline-row">
                    <span class="csim-label mono">AVG SPEED</span>
                    <canvas class="csim-sparkline" data-sparkline="speed" width="60" height="18"></canvas>
                </div>
                <div class="csim-sparkline-row">
                    <span class="csim-label mono">ANOMALIES</span>
                    <canvas class="csim-sparkline" data-sparkline="anomalies" width="60" height="18"></canvas>
                </div>
            </div>

            <div class="csim-section">
                <div class="csim-section-title mono">VEHICLE COLORS</div>
                <div class="csim-color-modes">
                    <button class="csim-color-btn csim-color-active" data-color-mode="default">DEFAULT</button>
                    <button class="csim-color-btn" data-color-mode="speed">SPEED</button>
                    <button class="csim-color-btn" data-color-mode="purpose">PURPOSE</button>
                </div>
            </div>

            <div class="csim-actions">
                <button class="panel-action-btn panel-action-btn-primary" data-action="toggle-sim">START SIM</button>
                <button class="panel-action-btn" data-action="add-vehicles">+10 CARS</button>
                <button class="panel-action-btn" data-action="add-peds">+10 PEOPLE</button>
                <button class="panel-action-btn" data-action="demo-city">DEMO CITY</button>
                <button class="panel-action-btn" style="background:#ff2a6d33;color:#ff2a6d;border-color:#ff2a6d" data-action="start-protest">PROTEST</button>
            </div>
        `;

        // Style
        const style = document.createElement('style');
        style.textContent = `
            .csim-panel { padding: 8px; font-size: 12px; }
            .csim-row { display: flex; justify-content: space-between; padding: 2px 0; }
            .csim-label { color: #888; }
            .csim-value { color: #00f0ff; }
            .csim-status-val { font-weight: bold; }
            .csim-section { margin-top: 8px; border-top: 1px solid #222; padding-top: 4px; }
            .csim-section-title { color: #666; font-size: 10px; margin-bottom: 4px; }
            .csim-actions { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px; }
            .csim-scenario-select {
                width: 100%; padding: 4px; background: #111; color: #00f0ff;
                border: 1px solid #333; font-family: inherit; font-size: 11px;
            }
            .csim-sparkline-row { display: flex; justify-content: space-between; align-items: center; padding: 1px 0; }
            .csim-sparkline { border: 1px solid #222; background: #0a0a0a; }
            .csim-anomaly-feed {
                max-height: 60px; overflow-y: auto; font-size: 10px; color: #ff2a6d;
                margin-top: 4px;
            }
            .csim-color-modes {
                display: flex; gap: 4px;
            }
            .csim-color-btn {
                flex: 1; padding: 3px 4px; font-size: 9px; font-family: inherit;
                background: #111; color: #666; border: 1px solid #333; cursor: pointer;
            }
            .csim-color-btn:hover { color: #00f0ff; border-color: #00f0ff; }
            .csim-color-btn.csim-color-active {
                color: #00f0ff; border-color: #00f0ff; background: #00f0ff11;
            }
        `;
        el.appendChild(style);

        // Button handlers
        el.querySelector('[data-action="toggle-sim"]').addEventListener('click', () => {
            EventBus.emit('city-sim:toggle');
        });
        el.querySelector('[data-action="add-vehicles"]').addEventListener('click', () => {
            EventBus.emit('city-sim:add-vehicles', 10);
        });
        el.querySelector('[data-action="add-peds"]').addEventListener('click', () => {
            EventBus.emit('city-sim:add-peds', 10);
        });
        el.querySelector('[data-action="demo-city"]').addEventListener('click', () => {
            EventBus.emit('city-sim:demo-city');
        });
        el.querySelector('[data-action="start-protest"]').addEventListener('click', () => {
            EventBus.emit('city-sim:start-protest', {
                plazaCenter: { x: 0, z: 0 },
                participantCount: 50,
                legitimacy: 0.25,
            });
        });
        el.querySelector('[data-bind="scenario"]').addEventListener('change', (e) => {
            if (e.target.value) {
                EventBus.emit('city-sim:load-scenario', e.target.value);
            }
        });

        // Color mode toggle buttons
        for (const btn of el.querySelectorAll('.csim-color-btn')) {
            btn.addEventListener('click', () => {
                const mode = btn.dataset.colorMode;
                EventBus.emit('city-sim:set-color-mode', mode);
                for (const b of el.querySelectorAll('.csim-color-btn')) {
                    b.classList.toggle('csim-color-active', b.dataset.colorMode === mode);
                }
            });
        }

        // Clean up any previous interval (prevent leak on reopen)
        if (panel._csimInterval) clearInterval(panel._csimInterval);

        // Periodic stats update — stored on panel instance, not module scope
        panel._csimInterval = setInterval(() => {
            _updatePanel(el);
        }, 500);

        // Subscribe to anomaly events for live feed
        const _anomalyUnsub = EventBus.on('city-sim:anomaly', (anomaly) => {
            const feed = el.querySelector('[data-bind="anomalyFeed"]');
            if (feed) {
                const line = document.createElement('div');
                line.textContent = `[${anomaly.type}] ${anomaly.description}`;
                line.style.borderBottom = '1px solid #220a0a';
                line.style.padding = '2px 0';
                feed.prepend(line);
                // Keep only last 10 entries
                while (feed.children.length > 10) {
                    feed.removeChild(feed.lastChild);
                }
            }
        });
        panel._anomalyUnsub = _anomalyUnsub;

        panel._csimEl = el;
        return el;
    },

    // PanelManager calls unmount on close — do cleanup here
    unmount(panel) {
        if (panel._csimInterval) {
            clearInterval(panel._csimInterval);
            panel._csimInterval = null;
        }
        if (panel._anomalyUnsub) {
            panel._anomalyUnsub();
            panel._anomalyUnsub = null;
        }
    },

    destroy(panel) {
        // Also clean up on permanent destruction
        this.unmount(panel);
    },
};

function _updatePanel(el) {
    // Get stats from map3d's city sim manager
    let stats = null;
    try {
        if (window._mapActions?.getCitySimStats) {
            stats = window._mapActions.getCitySimStats();
        }
    } catch (e) { /* silent */ }

    if (!stats) return;

    const bind = (key, value) => {
        const node = el.querySelector(`[data-bind="${key}"]`);
        if (node) node.textContent = value;
    };

    bind('status', stats.running ? 'RUNNING' : 'IDLE');
    bind('time', stats.timeOfDay || '--:--');
    bind('weather', (stats.weather || 'clear').toUpperCase());
    bind('vehicles', stats.vehicles || 0);
    bind('avgSpeed', `${stats.avgSpeedKmh || 0} km/h`);
    bind('pedestrians', stats.pedestrians || 0);
    bind('inBuilding', stats.pedestriansInBuilding || 0);
    bind('nodes', stats.nodes || 0);
    bind('edges', stats.edges || 0);
    bind('trafficCtrl', stats.trafficControllers || 0);

    // Anomaly stats
    if (stats.anomalies) {
        const a = stats.anomalies;
        bind('baseline', a.baselineReady ? 'READY' : `${Math.round(a.baselineProgress * 100)}%`);
        bind('detections', a.totalDetections || 0);
    }

    // Protest status
    const protestSection = el.querySelector('[data-bind="protestSection"]');
    if (stats.protest && stats.protest.phase !== 'NORMAL') {
        if (protestSection) protestSection.style.display = '';
        const p = stats.protest;
        bind('protestPhase', p.phase?.replace(/_/g, ' ') || '--');
        bind('protestActive', p.active || 0);
        bind('protestArrested', p.arrested || 0);
        bind('protestLegitimacy', p.legitimacy || '--');

        // Phase timeline
        const PHASES = ['CALL', 'MARCH', 'ASSEMBLE', 'TENSION', 'INCIDENT', 'RIOT', 'DISPERSE', 'AFTER'];
        const phaseMap = { CALL_TO_ACTION: 0, MARCHING: 1, ASSEMBLED: 2, TENSION: 3, FIRST_INCIDENT: 4, RIOT: 5, DISPERSAL: 6, AFTERMATH: 7 };
        const currentIdx = phaseMap[p.phase] ?? -1;
        const timeline = PHASES.map((name, i) => {
            if (i < currentIdx) return `<span style="color:#05ffa1">${name}</span>`;
            if (i === currentIdx) return `<span style="color:#ff2a6d;font-weight:bold">[${name}]</span>`;
            return `<span style="color:#444">${name}</span>`;
        }).join(' → ');
        const timelineEl = el.querySelector('[data-bind="protestTimeline"]');
        if (timelineEl) timelineEl.innerHTML = timeline;
    } else if (protestSection) {
        protestSection.style.display = 'none';
    }

    // Toggle button text
    const btn = el.querySelector('[data-action="toggle-sim"]');
    if (btn) btn.textContent = stats.running ? 'STOP SIM' : 'START SIM';

    // Sparkline charts (keep last 60 samples = 30 seconds at 500ms interval)
    if (!el._sparkData) {
        el._sparkData = { vehicles: [], speed: [], anomalies: [] };
    }
    const sd = el._sparkData;
    sd.vehicles.push(stats.vehicles || 0);
    sd.speed.push(stats.avgSpeedKmh || 0);
    sd.anomalies.push(stats.anomalies?.totalDetections || 0);
    while (sd.vehicles.length > 60) { sd.vehicles.shift(); sd.speed.shift(); sd.anomalies.shift(); }

    _drawSparkline(el.querySelector('[data-sparkline="vehicles"]'), sd.vehicles, '#00f0ff');
    _drawSparkline(el.querySelector('[data-sparkline="speed"]'), sd.speed, '#05ffa1');
    _drawSparkline(el.querySelector('[data-sparkline="anomalies"]'), sd.anomalies, '#ff2a6d');
}

function _drawSparkline(canvas, data, color) {
    if (!canvas || !data.length) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);

    const max = Math.max(1, ...data);
    const step = w / Math.max(1, data.length - 1);

    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    for (let i = 0; i < data.length; i++) {
        const x = i * step;
        const y = h - (data[i] / max) * (h - 2) - 1;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
}

// Export for panel manager
export default CitySimPanelDef;
