// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Patrol Routes Panel
// Shows friendly units with patrol waypoints, allows clearing/dispatching patrols.
// Subscribes to: units (Map), game.phase

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const PatrolPanelDef = {
    id: 'patrol',
    title: 'PATROL ROUTES',
    defaultPosition: { x: 8, y: 200 },
    defaultSize: { w: 280, h: 320 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'patrol-panel-inner';
        el.innerHTML = `
            <div class="patrol-summary" data-bind="summary">
                <span class="mono" style="font-size:0.5rem;color:var(--text-ghost)">Loading...</span>
            </div>
            <div class="patrol-list" data-bind="list">
                <div class="panel-empty">No patrol routes</div>
            </div>
            <div class="patrol-actions">
                <button class="panel-action-btn" data-action="patrol-all">PATROL ALL</button>
                <button class="panel-action-btn" data-action="recall-all">RECALL ALL</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const summaryEl = bodyEl.querySelector('[data-bind="summary"]');
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const patrolAllBtn = bodyEl.querySelector('[data-action="patrol-all"]');
        const recallAllBtn = bodyEl.querySelector('[data-action="recall-all"]');

        function renderList() {
            const patrolling = [];
            const idle = [];
            TritiumStore.units.forEach((u, id) => {
                if ((u.alliance || '').toLowerCase() !== 'friendly') return;
                const status = (u.status || 'active').toLowerCase();
                if (status === 'neutralized' || status === 'eliminated') return;
                const wps = u.waypoints;
                if (Array.isArray(wps) && wps.length >= 2) {
                    patrolling.push({ id, name: u.name || id, type: u.type || 'unknown', waypoints: wps.length, health: u.health, maxHealth: u.maxHealth || 100 });
                } else {
                    idle.push({ id, name: u.name || id, type: u.type || 'unknown' });
                }
            });

            // Summary
            if (summaryEl) {
                const phase = (TritiumStore.game?.phase || 'idle').toUpperCase();
                summaryEl.innerHTML = `
                    <div class="patrol-summary-row">
                        <span class="mono" style="font-size:0.5rem;color:var(--green)">${patrolling.length} PATROLLING</span>
                        <span class="mono" style="font-size:0.5rem;color:var(--text-ghost)">${idle.length} IDLE</span>
                        <span class="mono" style="font-size:0.5rem;color:var(--text-ghost)">${phase}</span>
                    </div>
                `;
            }

            // List
            if (!listEl) return;
            if (patrolling.length === 0 && idle.length === 0) {
                listEl.innerHTML = '<div class="panel-empty">No friendly units</div>';
                return;
            }

            let html = '';
            if (patrolling.length > 0) {
                html += '<div class="panel-section-label">ACTIVE PATROLS</div>';
                for (const u of patrolling) {
                    const hpPct = u.maxHealth > 0 ? Math.round((u.health / u.maxHealth) * 100) : 100;
                    const hpColor = hpPct > 50 ? 'var(--green)' : hpPct > 25 ? 'var(--amber)' : 'var(--magenta)';
                    html += `<div class="patrol-entry" data-unit-id="${_esc(u.id)}">
                        <div class="patrol-entry-name">
                            <span class="patrol-dot" style="background:var(--green)"></span>
                            <span class="mono">${_esc(u.name)}</span>
                            <span class="mono" style="color:var(--text-ghost);font-size:0.45rem">${_esc(u.type)}</span>
                        </div>
                        <div class="patrol-entry-info">
                            <span class="mono" style="font-size:0.45rem;color:var(--cyan)">${u.waypoints} waypoints</span>
                            <span class="mono" style="font-size:0.45rem;color:${hpColor}">${hpPct}%</span>
                            <button class="patrol-btn-clear" data-action="clear-patrol" data-unit-id="${_esc(u.id)}" title="Clear patrol">STOP</button>
                        </div>
                    </div>`;
                }
            }

            if (idle.length > 0) {
                html += '<div class="panel-section-label" style="margin-top:6px">IDLE UNITS</div>';
                for (const u of idle) {
                    html += `<div class="patrol-entry patrol-entry-idle" data-unit-id="${_esc(u.id)}">
                        <div class="patrol-entry-name">
                            <span class="patrol-dot" style="background:var(--text-ghost)"></span>
                            <span class="mono">${_esc(u.name)}</span>
                            <span class="mono" style="color:var(--text-ghost);font-size:0.45rem">${_esc(u.type)}</span>
                        </div>
                    </div>`;
                }
            }

            listEl.innerHTML = html;

            // Wire click handlers
            listEl.querySelectorAll('.patrol-entry').forEach(entry => {
                entry.addEventListener('click', () => {
                    const uid = entry.dataset.unitId;
                    if (uid) {
                        TritiumStore.set('map.selectedUnitId', uid);
                        EventBus.emit('unit:selected', { id: uid });
                        EventBus.emit('map:centerOnUnit', { id: uid });
                    }
                });
            });

            listEl.querySelectorAll('[data-action="clear-patrol"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const uid = btn.dataset.unitId;
                    if (!uid) return;
                    fetch('/api/amy/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'stand_down', target_id: uid }),
                    }).then(() => {
                        EventBus.emit('toast:show', { message: `${uid}: patrol cleared`, type: 'info' });
                    }).catch(() => {});
                });
            });
        }

        // Refresh on unit changes
        panel._unsubs.push(
            TritiumStore.on('units', renderList),
            TritiumStore.on('game.phase', renderList),
        );

        // Batch actions
        if (patrolAllBtn) {
            patrolAllBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/amy/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'patrol_all' }),
                    });
                    EventBus.emit('toast:show', { message: 'All units: PATROL', type: 'info' });
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Patrol command failed', type: 'alert' });
                }
            });
        }

        if (recallAllBtn) {
            recallAllBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/amy/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: 'stand_down' }),
                    });
                    EventBus.emit('toast:show', { message: 'All units: STAND DOWN', type: 'info' });
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Recall command failed', type: 'alert' });
                }
            });
        }

        // Initial render
        renderList();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
