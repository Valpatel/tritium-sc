// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Sensor Net Panel
// Displays live sensor network activations: motion detectors, door sensors,
// tripwires. Subscribes to sensor:triggered and sensor:cleared EventBus events.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// ============================================================
// Sensor type metadata
// ============================================================

const SENSOR_TYPES = {
    motion:   { label: 'MOTION',   icon: 'M', color: '#ff2a6d' },
    door:     { label: 'DOOR',     icon: 'D', color: '#fcee0a' },
    tripwire: { label: 'TRIPWIRE', icon: 'T', color: '#ff6b35' },
};

function getSensorIcon(type) {
    const cfg = SENSOR_TYPES[type];
    return cfg ? cfg.icon : '?';
}

function getSensorLabel(type) {
    const cfg = SENSOR_TYPES[type];
    return cfg ? cfg.label : (type || 'UNKNOWN').toUpperCase();
}

// ============================================================
// Pure helpers -- exposed via window.SensorNetHelpers per instance
// ============================================================

// Expose static helpers immediately
if (typeof window !== 'undefined') {
    window.SensorNetHelpers = {
        getSensorIcon,
        getSensorLabel,
        // Instance methods are populated in mount()
        getActiveCount: () => 0,
        getLogLength: () => 0,
        getLastLogEntry: () => null,
    };
}

// ============================================================
// Panel Definition
// ============================================================

const MAX_LOG_ENTRIES = 50;

export const SensorNetPanelDef = {
    id: 'sensors',
    title: 'SENSOR NET',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 280, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'sensor-panel-inner';
        el.innerHTML = `
            <div class="sensor-toolbar">
                <span class="sensor-active-count mono" data-bind="active-count">0 active</span>
                <button class="panel-action-btn" data-action="clear" title="Clear sensor log">CLEAR</button>
            </div>
            <ul class="panel-list sensor-log" data-bind="log" role="log" aria-label="Sensor event log">
                <li class="panel-empty">Waiting for sensor data...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const logEl = bodyEl.querySelector('[data-bind="log"]');
        const countEl = bodyEl.querySelector('[data-bind="active-count"]');
        const clearBtn = bodyEl.querySelector('[data-action="clear"]');

        // Active sensors: sensor_id -> { name, type, triggered_by }
        const activeSensors = new Map();
        // Event log: most recent first internally, rendered most-recent-first
        let eventLog = [];

        function _formatTime(d) {
            return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
        }

        function render() {
            if (!logEl) return;

            // Update active count
            if (countEl) countEl.textContent = `${activeSensors.size} active`;

            if (eventLog.length === 0) {
                logEl.innerHTML = '<li class="panel-empty">Waiting for sensor data...</li>';
                return;
            }

            // Show entries most-recent-first
            const visible = eventLog.slice().reverse();
            logEl.innerHTML = visible.map(e => {
                const cfg = SENSOR_TYPES[e.sensor_type] || { label: '?', icon: '?', color: '#888' };
                const isTriggered = e.action === 'triggered';
                const stateColor = isTriggered ? '#ff2a6d' : '#00f0ff';
                const stateLabel = isTriggered ? 'TRIGGERED' : 'CLEAR';
                const triggerInfo = e.triggered_by ? ` &lt;${_esc(e.triggered_by)}&gt;` : '';

                return `<li class="sensor-entry" data-state="${e.action}">
                    <span class="sensor-ts mono">${_esc(e.ts)}</span>
                    <span class="sensor-badge" style="color:${cfg.color};border-color:${cfg.color}">${cfg.icon}</span>
                    <span class="sensor-name">${_esc(e.name)}</span>
                    <span class="sensor-state" style="color:${stateColor}">${stateLabel}</span>${triggerInfo}
                </li>`;
            }).join('');
        }

        function addLogEntry(data, action) {
            eventLog.push({
                sensor_id: data.sensor_id,
                name: data.name || data.sensor_id,
                sensor_type: data.type || 'unknown',
                action: action,
                triggered_by: data.triggered_by || '',
                ts: _formatTime(new Date()),
            });
            // Cap log at MAX_LOG_ENTRIES
            if (eventLog.length > MAX_LOG_ENTRIES) {
                eventLog = eventLog.slice(eventLog.length - MAX_LOG_ENTRIES);
            }
            render();
        }

        function onSensorTriggered(data) {
            if (!data || !data.sensor_id) return;
            activeSensors.set(data.sensor_id, {
                name: data.name || data.sensor_id,
                type: data.type || 'unknown',
                triggered_by: data.triggered_by || '',
            });
            addLogEntry(data, 'triggered');
        }

        function onSensorCleared(data) {
            if (!data || !data.sensor_id) return;
            activeSensors.delete(data.sensor_id);
            addLogEntry(data, 'cleared');
        }

        // Subscribe to events
        const unsubTriggered = EventBus.on('sensor:triggered', onSensorTriggered);
        const unsubCleared = EventBus.on('sensor:cleared', onSensorCleared);

        panel._unsubs.push(unsubTriggered);
        panel._unsubs.push(unsubCleared);

        // Clear button
        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                eventLog = [];
                render();
            });
        }

        // Expose instance helpers for testing
        if (typeof window !== 'undefined') {
            window.SensorNetHelpers = {
                getSensorIcon,
                getSensorLabel,
                getActiveCount: () => activeSensors.size,
                getLogLength: () => eventLog.length,
                getLastLogEntry: () => eventLog.length > 0 ? eventLog[eventLog.length - 1] : null,
            };
        }
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
