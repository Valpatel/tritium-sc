// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Escalation Panel
// Shows current threat level, auto-dispatch status, and recent escalation changes.
// Subscribes to: EventBus 'escalation_change', polls /api/targets/hostiles for count.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const THREAT_LEVELS = [
    { level: 1, label: 'GREEN',  color: '#05ffa1', desc: 'All clear' },
    { level: 2, label: 'BLUE',   color: '#00a0ff', desc: 'Low activity' },
    { level: 3, label: 'YELLOW', color: '#fcee0a', desc: 'Suspicious activity' },
    { level: 4, label: 'ORANGE', color: '#ff6b35', desc: 'Active threat' },
    { level: 5, label: 'RED',    color: '#ff2a6d', desc: 'Critical threat' },
];

export const EscalationPanelDef = {
    id: 'escalation',
    title: 'THREAT LEVEL',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 260, h: 300 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'escalation-panel-inner';
        el.innerHTML = `
            <div class="esc-threat-display" data-bind="threat-display">
                <div class="esc-level-num" data-bind="level-num">1</div>
                <div class="esc-level-label" data-bind="level-label">GREEN</div>
                <div class="esc-level-desc mono" data-bind="level-desc">All clear</div>
            </div>
            <div class="esc-stats">
                <div class="esc-stat-row">
                    <span class="esc-stat-label">HOSTILES</span>
                    <span class="esc-stat-val mono" data-bind="hostile-count">0</span>
                </div>
                <div class="esc-stat-row">
                    <span class="esc-stat-label">AUTO-DISPATCH</span>
                    <span class="esc-stat-val mono" data-bind="auto-dispatch">ENABLED</span>
                </div>
                <div class="esc-stat-row">
                    <span class="esc-stat-label">LAST CHANGE</span>
                    <span class="esc-stat-val mono" data-bind="last-change">---</span>
                </div>
            </div>
            <div class="esc-section-label mono">RECENT CHANGES</div>
            <ul class="panel-list esc-history" data-bind="history" role="log" aria-label="Escalation history">
                <li class="panel-empty">No escalation changes</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const levelNumEl = bodyEl.querySelector('[data-bind="level-num"]');
        const levelLabelEl = bodyEl.querySelector('[data-bind="level-label"]');
        const levelDescEl = bodyEl.querySelector('[data-bind="level-desc"]');
        const threatDisplayEl = bodyEl.querySelector('[data-bind="threat-display"]');
        const hostileCountEl = bodyEl.querySelector('[data-bind="hostile-count"]');
        const autoDispatchEl = bodyEl.querySelector('[data-bind="auto-dispatch"]');
        const lastChangeEl = bodyEl.querySelector('[data-bind="last-change"]');
        const historyEl = bodyEl.querySelector('[data-bind="history"]');

        let currentLevel = 1;
        const history = [];
        const MAX_HISTORY = 20;

        function updateDisplay(level) {
            currentLevel = Math.max(1, Math.min(5, level));
            const cfg = THREAT_LEVELS[currentLevel - 1];
            if (levelNumEl) levelNumEl.textContent = currentLevel;
            if (levelLabelEl) {
                levelLabelEl.textContent = cfg.label;
                levelLabelEl.style.color = cfg.color;
            }
            if (levelDescEl) levelDescEl.textContent = cfg.desc;
            if (threatDisplayEl) {
                threatDisplayEl.style.borderColor = cfg.color;
                threatDisplayEl.style.boxShadow = `0 0 12px ${cfg.color}40`;
            }
            if (levelNumEl) levelNumEl.style.color = cfg.color;
        }

        function renderHistory() {
            if (!historyEl) return;
            if (history.length === 0) {
                historyEl.innerHTML = '<li class="panel-empty">No escalation changes</li>';
                return;
            }
            historyEl.innerHTML = history.slice(-10).reverse().map(h => {
                const cfg = THREAT_LEVELS[(h.level || 1) - 1];
                return `<li class="events-entry">
                    <span class="events-ts mono">${_esc(h.ts)}</span>
                    <span class="events-badge" style="color:${cfg.color};border-color:${cfg.color}">${h.level}</span>
                    <span class="events-text">${_esc(h.reason || cfg.label)}</span>
                </li>`;
            }).join('');
        }

        // Derive threat level from hostile count
        function deriveLevel() {
            let hostiles = 0;
            if (TritiumStore.units) {
                for (const [, u] of TritiumStore.units) {
                    if ((u.alliance || '').toLowerCase() === 'hostile' &&
                        (u.status || 'active') !== 'eliminated') {
                        hostiles++;
                    }
                }
            }
            if (hostileCountEl) hostileCountEl.textContent = hostiles;
            let level = 1;
            if (hostiles >= 8) level = 5;
            else if (hostiles >= 5) level = 4;
            else if (hostiles >= 3) level = 3;
            else if (hostiles >= 1) level = 2;
            if (level !== currentLevel) {
                const now = new Date();
                const ts = `${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
                history.push({ level, ts, reason: `${hostiles} hostiles detected` });
                if (history.length > MAX_HISTORY) history.shift();
                if (lastChangeEl) lastChangeEl.textContent = ts;
                renderHistory();
            }
            updateDisplay(level);
        }

        // Subscribe to unit updates
        panel._unsubs.push(
            EventBus.on('units:updated', deriveLevel),
            EventBus.on('combat:elimination', deriveLevel),
        );

        // Auto-dispatch indicator (from game state)
        panel._unsubs.push(
            TritiumStore.on('game.phase', (phase) => {
                if (autoDispatchEl) {
                    autoDispatchEl.textContent = (phase === 'active') ? 'ACTIVE' : 'STANDBY';
                    autoDispatchEl.style.color = (phase === 'active') ? '#05ffa1' : 'rgba(0,240,255,0.5)';
                }
            })
        );

        // Initial state
        updateDisplay(1);
        deriveLevel();
        renderHistory();
    },

    unmount(bodyEl) {},
};
