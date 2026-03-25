// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Events tab for the Simulation container.
 * Shows active events, event log, and trigger buttons.
 * Registers itself as a tab via EventBus.
 */

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'simulation-container',
    id: 'events-tab',
    title: 'EVENTS',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#fcee0a;margin-bottom:8px;font-size:12px">EVENTS</div>
                <div class="se-row"><span class="se-l">SIM TIME</span><span class="se-v" data-bind="time">--</span></div>
                <div class="se-row"><span class="se-l">DAY</span><span class="se-v" data-bind="day">--</span></div>
                <div class="se-row"><span class="se-l">TIME SCALE</span><span class="se-v" data-bind="scale">--</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px">TRIGGER EVENT</div>
                <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:8px">
                    <button class="se-btn" data-action="protest" style="color:#ff2a6d;border-color:#ff2a6d">PROTEST</button>
                    <button class="se-btn" data-action="accident" style="color:#fcee0a;border-color:#fcee0a">ACCIDENT</button>
                    <button class="se-btn" data-action="emergency" style="color:#ff8844;border-color:#ff8844">EMERGENCY</button>
                    <button class="se-btn" data-action="dramatic" style="color:#00f0ff;border-color:#00f0ff">DRAMATIC DAY</button>
                </div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px">EVENT LOG</div>
                <div class="se-log" data-bind="log" style="max-height:150px;overflow-y:auto;font-size:10px;color:#666"></div>
            </div>
            <style>
                .se-row{display:flex;justify-content:space-between;padding:2px 0}
                .se-l{color:#666}.se-v{color:#fcee0a}
                .se-btn{background:#0a0a12;border:1px solid;padding:3px 8px;font-family:inherit;font-size:10px;cursor:pointer;border-radius:2px}
                .se-btn:hover{filter:brightness(1.3)}
            </style>
        `;

        // Wire buttons
        el.querySelector('[data-action="protest"]').addEventListener('click', () => {
            EventBus.emit('city-sim:start-protest', { plazaCenter: { x: 0, z: 0 }, participantCount: 50, legitimacy: 0.25 });
        });
        el.querySelector('[data-action="accident"]').addEventListener('click', () => {
            EventBus.emit('city-sim:trigger-event', { type: 'car_accident' });
        });
        el.querySelector('[data-action="emergency"]').addEventListener('click', () => {
            EventBus.emit('city-sim:trigger-event', { type: 'emergency_response' });
        });
        el.querySelector('[data-action="dramatic"]').addEventListener('click', () => {
            EventBus.emit('city-sim:load-scenario', 'dramatic_day');
        });

        // Event log
        const logEl = el.querySelector('[data-bind="log"]');
        const logEntries = [];
        const addLog = (msg) => {
            logEntries.unshift(msg);
            if (logEntries.length > 20) logEntries.pop();
            logEl.innerHTML = logEntries.map(e => `<div>${e}</div>`).join('');
        };

        el._unsubs = [
            EventBus.on('city-sim:protest-phase', (d) => addLog(`<span style="color:#ff2a6d">PROTEST ${d.phase}</span> active=${d.activeCount}`)),
            EventBus.on('city-sim:collision', (d) => addLog(`<span style="color:#fcee0a">${d.severity}</span> ${d.vehicle1} ↔ ${d.vehicle2}`)),
            EventBus.on('city-sim:police-dispatched', (d) => addLog(`<span style="color:#4488ff">POLICE</span> ${d.count} dispatched`)),
            EventBus.on('city-sim:event-triggered', (d) => addLog(`<span style="color:#00f0ff">EVENT</span> ${d.name}`)),
        ];

        const bind = (key, val) => {
            const e = el.querySelector(`[data-bind="${key}"]`);
            if (e) e.textContent = val;
        };

        el._interval = setInterval(() => {
            const stats = window._mapActions?.getCitySimStats?.();
            if (!stats) return;
            bind('time', stats.timeOfDay || '--');
            bind('day', `${stats.dayOfWeek || '?'} (day ${stats.simDay || 0})`);
            bind('scale', `${stats.timeScale || 60}x`);
        }, 1000);
    },
    unmount() {
        // Unsub handled by container cleanup
    },
});
