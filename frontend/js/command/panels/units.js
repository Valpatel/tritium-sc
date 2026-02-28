// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Unit List Panel
// Filterable list of all units on the tactical map.
// Subscribes to: units (Map), map.selectedUnitId

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const ALLIANCE_COLORS = {
    friendly: 'var(--green)',
    hostile: 'var(--magenta)',
    neutral: 'var(--cyan)',
    unknown: 'var(--amber)',
};

const TYPE_ICONS = {
    rover: 'R', drone: 'D', turret: 'T', person: 'P',
    hostile_kid: 'H', camera: 'C', sensor: 'S',
    tank: 'K', apc: 'A', scout_drone: 'D',
    hostile_vehicle: 'V', hostile_leader: 'L', vehicle: 'V',
    heavy_turret: 'T', missile_turret: 'T',
};

const FSM_STATE_COLORS = {
    idle: '#888888',
    scanning: '#4a9eff',
    tracking: '#00f0ff',
    engaging: '#ff2a6d',
    cooldown: '#668899',
    patrolling: '#05ffa1',
    pursuing: '#ff8800',
    retreating: '#fcee0a',
    rtb: '#4a8866',
    scouting: '#88ddaa',
    orbiting: '#66ccee',
    spawning: '#cccccc',
    advancing: '#22dd66',
    flanking: '#ff6633',
    fleeing: '#ffff00',
};

export const UnitsPanelDef = {
    id: 'units',
    title: 'UNITS',
    defaultPosition: { x: 8, y: 44 },
    defaultSize: { w: 260, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'units-panel-inner';
        el.innerHTML = `
            <select class="panel-filter" data-bind="filter">
                <option value="all">ALL</option>
                <option value="friendly">FRIENDLY</option>
                <option value="hostile">HOSTILE</option>
                <option value="neutral">NEUTRAL</option>
                <option value="unknown">UNKNOWN</option>
            </select>
            <div class="panel-section-label">
                <span data-bind="count">0</span> UNITS
            </div>
            <ul class="panel-list" data-bind="list" role="listbox" aria-label="Unit list">
                <li class="panel-empty">No units detected</li>
            </ul>
            <div class="panel-detail" data-bind="detail" style="display:none"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const filterEl = bodyEl.querySelector('[data-bind="filter"]');
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const detailEl = bodyEl.querySelector('[data-bind="detail"]');
        let currentFilter = 'all';

        function render() {
            const units = [];
            TritiumStore.units.forEach((u) => {
                if (currentFilter === 'all' || u.alliance === currentFilter) {
                    units.push(u);
                }
            });

            if (countEl) countEl.textContent = units.length;

            if (units.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No units detected</li>';
                return;
            }

            const selectedId = TritiumStore.get('map.selectedUnitId');

            listEl.innerHTML = units.map(u => {
                const alliance = u.alliance || 'unknown';
                const color = ALLIANCE_COLORS[alliance] || 'var(--text-dim)';
                const icon = TYPE_ICONS[u.type] || '?';
                const hp = (u.health !== undefined && u.maxHealth)
                    ? `${Math.round(u.health)}/${u.maxHealth}`
                    : '';
                const active = u.id === selectedId ? ' active' : '';
                const fsm = u.fsmState || '';
                const fsmBadge = fsm ? `<span class="unit-fsm-badge" style="color:${FSM_STATE_COLORS[fsm] || '#888'}">${fsm.toUpperCase()}</span>` : '';
                return `<li class="panel-list-item${active}" data-unit-id="${_esc(u.id)}" role="option">
                    <span class="panel-icon-badge" style="color:${color};border-color:${color}">${icon}</span>
                    <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(u.name || u.id)}</span>
                    ${fsmBadge}
                    <span class="panel-stat-value" style="font-size:0.5rem">${hp}</span>
                </li>`;
            }).join('');

            // Click handlers
            listEl.querySelectorAll('.panel-list-item').forEach(item => {
                item.addEventListener('click', () => {
                    const id = item.dataset.unitId;
                    TritiumStore.set('map.selectedUnitId', id);
                    EventBus.emit('unit:selected', { id });
                    render(); // Re-render to update active highlight
                });
            });
        }

        function renderDetail() {
            const selectedId = TritiumStore.get('map.selectedUnitId');
            if (!selectedId || !detailEl) {
                if (detailEl) detailEl.style.display = 'none';
                return;
            }
            const u = TritiumStore.units.get(selectedId);
            if (!u) {
                detailEl.style.display = 'none';
                return;
            }

            const alliance = u.alliance || 'unknown';
            const color = ALLIANCE_COLORS[alliance] || 'var(--text-dim)';
            const icon = TYPE_ICONS[u.type] || '?';
            const pos = u.position || {};
            const hpPct = (u.maxHealth > 0) ? Math.round((u.health / u.maxHealth) * 100) : 100;
            const hpColor = hpPct > 60 ? 'var(--green)' : hpPct > 25 ? 'var(--amber)' : 'var(--magenta)';
            const batPct = u.battery !== undefined ? Math.round(u.battery) : null;

            const fsmState = u.fsmState || '';
            const fsmColor = FSM_STATE_COLORS[fsmState] || '#888';

            detailEl.style.display = '';
            detailEl.innerHTML = `
                <div class="panel-section-label" style="margin-top:6px;border-top:1px solid var(--border);padding-top:6px">
                    <span class="panel-icon-badge" style="color:${color};border-color:${color}">${icon}</span>
                    ${_esc(u.name || u.id)}
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">TYPE</span>
                    <span class="panel-stat-value">${_esc(u.type || 'unknown')}</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">ALLIANCE</span>
                    <span class="panel-stat-value" style="color:${color}">${alliance.toUpperCase()}</span>
                </div>
                ${fsmState ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">FSM</span>
                    <span class="panel-stat-value" style="color:${fsmColor}">${fsmState.toUpperCase()}</span>
                </div>` : ''}
                ${u.maxHealth ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">HEALTH</span>
                    <span class="panel-stat-value">${Math.round(u.health)}/${u.maxHealth}</span>
                </div>
                <div class="panel-bar" style="margin:2px 0 4px">
                    <div class="panel-bar-fill" style="width:${hpPct}%;background:${hpColor}"></div>
                </div>` : ''}
                ${batPct !== null ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">BATTERY</span>
                    <span class="panel-stat-value">${batPct}%</span>
                </div>` : ''}
                ${u.morale !== undefined ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">MORALE</span>
                    <span class="panel-stat-value" style="color:${u.morale > 0.6 ? 'var(--green)' : u.morale > 0.3 ? 'var(--amber)' : 'var(--magenta)'}">${Math.round(u.morale * 100)}%</span>
                </div>` : ''}
                ${u.degradation !== undefined && u.degradation > 0 ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">DEGRADATION</span>
                    <span class="panel-stat-value" style="color:var(--amber)">${Math.round(u.degradation * 100)}%</span>
                </div>` : ''}
                ${u.weaponRange !== undefined && u.weaponRange > 0 ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">WEAPON RANGE</span>
                    <span class="panel-stat-value">${Math.round(u.weaponRange)}m</span>
                </div>` : ''}
                ${u.kills !== undefined && u.kills > 0 ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">KILLS</span>
                    <span class="panel-stat-value" style="color:var(--magenta)">${u.kills}</span>
                </div>` : ''}
                <div class="panel-stat-row">
                    <span class="panel-stat-label">HEADING</span>
                    <span class="panel-stat-value">${u.heading !== undefined ? Math.round(u.heading) + '\u00B0' : '--'}</span>
                </div>
                <div class="panel-stat-row">
                    <span class="panel-stat-label">POSITION</span>
                    <span class="panel-stat-value">(${(pos.x || 0).toFixed(1)}, ${(pos.y || 0).toFixed(1)})</span>
                </div>
                ${u.squadId ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">SQUAD</span>
                    <span class="panel-stat-value">${_esc(u.squadId)}</span>
                </div>` : ''}
                ${u.thoughtText ? `
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">THOUGHT</div>
                    <div style="display:flex;align-items:center;gap:4px;margin-top:2px">
                        <span style="display:inline-block;padding:1px 4px;border-radius:2px;font-size:0.4rem;text-transform:uppercase;background:${
                            {curious:'#00f0ff',afraid:'#fcee0a',angry:'#ff2a6d',happy:'#05ffa1',neutral:'#888888'}[u.thoughtEmotion||'neutral']||'#888888'
                        };color:#000">${_esc(u.thoughtEmotion || 'neutral')}</span>
                        <q style="font-style:italic;color:var(--text-primary);font-size:0.5rem">${_esc(u.thoughtText)}</q>
                    </div>
                </div>` : ''}
                ${alliance === 'neutral' && ['person','animal','vehicle'].includes(u.type || u.asset_type) ? `
                <div style="margin-top:6px">
                    <button class="panel-action-btn panel-npc-detail-btn" style="width:100%;font-size:0.5rem">VIEW NPC DETAILS</button>
                </div>` : ''}
                ${alliance === 'friendly' ? `
                <div style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">SEND COMMAND</div>
                    <div style="display:flex;gap:4px;margin-top:4px">
                        <input class="panel-cmd-input" type="text" placeholder="Lua command..."
                            style="flex:1;font-family:var(--font-mono);font-size:0.55rem;color:var(--text-primary);background:var(--surface-3);border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 6px;outline:none">
                        <button class="panel-action-btn panel-action-btn-primary panel-cmd-send"
                            style="flex-shrink:0">SEND</button>
                    </div>
                    <div class="panel-cmd-status" style="font-size:0.45rem;color:var(--text-ghost);margin-top:2px;min-height:12px"></div>
                </div>` : ''}
            `;

            // Wire command send button
            const cmdInput = detailEl.querySelector('.panel-cmd-input');
            const cmdSend = detailEl.querySelector('.panel-cmd-send');
            const cmdStatus = detailEl.querySelector('.panel-cmd-status');
            if (cmdInput && cmdSend) {
                const sendCmd = () => {
                    const cmd = cmdInput.value.trim();
                    if (!cmd) return;
                    if (cmdStatus) cmdStatus.textContent = 'Sending...';
                    fetch('/api/amy/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ action: cmd, target_id: selectedId }),
                    }).then(r => {
                        if (cmdStatus) cmdStatus.textContent = r.ok ? 'Sent' : 'Failed';
                        if (r.ok) cmdInput.value = '';
                    }).catch(() => {
                        if (cmdStatus) cmdStatus.textContent = 'Error';
                    });
                };
                cmdSend.addEventListener('click', sendCmd);
                cmdInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') sendCmd();
                });
            }

            // Wire NPC detail button
            const npcBtn = detailEl.querySelector('.panel-npc-detail-btn');
            if (npcBtn && selectedId) {
                npcBtn.addEventListener('click', () => {
                    EventBus.emit('device:open-modal', { id: selectedId });
                });
            }
        }

        // Subscribe
        panel._unsubs.push(
            TritiumStore.on('units', render),
            TritiumStore.on('map.selectedUnitId', () => { render(); renderDetail(); })
        );

        // Filter change
        if (filterEl) {
            const onFilterChange = () => {
                currentFilter = filterEl.value;
                render();
            };
            filterEl.addEventListener('change', onFilterChange);
            panel._unsubs.push(() => filterEl.removeEventListener('change', onFilterChange));
        }

        // Listen for external unit selection (e.g. from map click)
        const onUnitSelected = () => renderDetail();
        EventBus.on('unit:selected', onUnitSelected);
        panel._unsubs.push(() => EventBus.off('unit:selected', onUnitSelected));

        // Initial render
        render();
        renderDetail();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
