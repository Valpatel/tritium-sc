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

const SOURCE_BADGE = {
    sim:       { label: 'SIM',       color: 'var(--text-ghost)',  border: 'var(--border)' },
    real:      { label: 'REAL',      color: 'var(--green)',       border: 'var(--green)' },
    graphling: { label: 'GRAPHLING', color: 'var(--magenta)',     border: 'var(--magenta)' },
};

const INV_TYPE_LABELS = {
    weapon: 'GUN',
    armor: 'SHIELD',
    grenade: 'BOMB',
};

/**
 * Render the inventory section HTML for a unit detail panel.
 * For allied units with full item data, shows each item with type-specific formatting.
 * For hostile/neutral units, shows a CLASSIFIED block.
 * Returns empty string if no inventory data present.
 * @param {Object} inventory - the unit's inventory object
 * @returns {string} HTML string
 */
function _renderInventory(inventory) {
    if (!inventory) return '';

    // Hostile/neutral: classified view
    if (inventory.status === 'unknown') {
        const count = inventory.item_count || 0;
        return `
            <div class="unit-inv-section" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
                <div class="panel-section-label">INVENTORY</div>
                <div class="unit-inv-classified">
                    <span class="unit-inv-classified-label">CLASSIFIED</span>
                    <span class="unit-inv-classified-bar">\u2588\u2588\u2588\u2588\u2588\u2588\u2588</span>
                    <div class="unit-inv-classified-hint">Carrying ~${count} item${count !== 1 ? 's' : ''} (unidentified)</div>
                </div>
            </div>`;
    }

    // Allied: full item list
    const items = inventory.items;
    if (!items || !Array.isArray(items) || items.length === 0) return '';

    const activeId = inventory.active_weapon_id || '';
    const rows = items.map(item => {
        const typeLabel = INV_TYPE_LABELS[item.item_type] || item.item_type.toUpperCase();
        const isActive = item.item_id === activeId;

        if (item.item_type === 'weapon') {
            const ammoStr = (item.ammo !== undefined && item.max_ammo !== undefined)
                ? `<span class="unit-inv-ammo">${item.ammo}/${item.max_ammo}</span>` : '';
            const activeBadge = isActive ? '<span class="unit-inv-active">ACTIVE</span>' : '';
            return `<div class="unit-inv-item unit-inv-weapon">[${_esc(typeLabel)}] ${_esc(item.name)} ${ammoStr} ${activeBadge}</div>`;
        }

        if (item.item_type === 'armor') {
            const dur = item.durability !== undefined && item.max_durability
                ? item.durability / item.max_durability : 1;
            const durPct = Math.round(dur * 100);
            const filled = Math.round(dur * 6);
            const empty = 6 - filled;
            const barStr = '\u2588'.repeat(filled) + '\u2591'.repeat(empty);
            const drStr = item.damage_reduction !== undefined ? ` (${item.damage_reduction} DR)` : '';
            return `<div class="unit-inv-item unit-inv-armor">[${_esc(typeLabel)}] ${_esc(item.name)} <span class="unit-inv-durability">${barStr} ${durPct}%${drStr}</span></div>`;
        }

        if (item.item_type === 'grenade') {
            const countStr = item.count !== undefined ? `x${item.count}` : '';
            return `<div class="unit-inv-item unit-inv-grenade">[${_esc(typeLabel)}] ${_esc(item.name)} ${countStr}</div>`;
        }

        // Fallback for unknown item types
        return `<div class="unit-inv-item">[${_esc(typeLabel)}] ${_esc(item.name)}</div>`;
    }).join('\n');

    return `
        <div class="unit-inv-section" style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
            <div class="panel-section-label">INVENTORY</div>
            ${rows}
        </div>`;
}

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
                <option value="source:real">SOURCE: REAL</option>
                <option value="source:sim">SOURCE: SIM</option>
                <option value="source:graphling">SOURCE: GRAPHLING</option>
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

        // DOM element cache: unit id -> <li> element
        const _domCache = new Map();

        /**
         * Build the inner HTML for a single unit list item.
         * Returns only the inner content (not the <li> wrapper).
         */
        function _buildItemContent(u, selectedId) {
            const alliance = u.alliance || 'unknown';
            const color = ALLIANCE_COLORS[alliance] || 'var(--text-dim)';
            const icon = TYPE_ICONS[u.type] || '?';
            const hp = (u.health !== undefined && u.maxHealth)
                ? `${Math.round(u.health)}/${u.maxHealth}`
                : '';
            const fsm = u.fsmState || '';
            const fsmBadge = fsm ? `<span class="unit-fsm-badge" style="color:${FSM_STATE_COLORS[fsm] || '#888'}">${fsm.toUpperCase()}</span>` : '';
            const shortId = (u.identity && u.identity.short_id)
                ? `<span style="font-family:var(--font-mono);font-size:0.4rem;color:var(--text-ghost);margin-right:3px">${_esc(u.identity.short_id)}</span>`
                : '';
            const srcInfo = SOURCE_BADGE[u.source] || SOURCE_BADGE.sim;
            const srcBadge = `<span style="font-size:0.35rem;padding:0 3px;border:1px solid ${srcInfo.border};border-radius:2px;color:${srcInfo.color};margin-right:3px;flex-shrink:0">${srcInfo.label}</span>`;
            const statusBadge = u.weaponJammed
                ? '<span style="font-size:0.35rem;padding:0 3px;border:1px solid var(--magenta);border-radius:2px;color:var(--magenta);margin-right:3px;flex-shrink:0">JAM</span>'
                : u.ammoDepleted
                ? '<span style="font-size:0.35rem;padding:0 3px;border:1px solid var(--magenta);border-radius:2px;color:var(--magenta);margin-right:3px;flex-shrink:0">EMPTY</span>'
                : u.ammoLow
                ? '<span style="font-size:0.35rem;padding:0 3px;border:1px solid var(--amber);border-radius:2px;color:var(--amber);margin-right:3px;flex-shrink:0">LOW</span>'
                : '';
            return `<span class="panel-icon-badge" style="color:${color};border-color:${color}">${icon}</span>` +
                shortId +
                `<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(u.name || u.id)}</span>` +
                statusBadge +
                srcBadge +
                fsmBadge +
                `<span class="panel-stat-value" style="font-size:0.5rem">${hp}</span>`;
        }

        function render() {
            if (!listEl) return;
            const units = [];
            TritiumStore.units.forEach((u) => {
                if (currentFilter === 'all') {
                    units.push(u);
                } else if (currentFilter.startsWith('source:')) {
                    if ((u.source || 'sim') === currentFilter.slice(7)) units.push(u);
                } else if (u.alliance === currentFilter) {
                    units.push(u);
                }
            });

            if (countEl) countEl.textContent = units.length;

            if (units.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No units detected</li>';
                _domCache.clear();
                return;
            }

            const selectedId = TritiumStore.get('map.selectedUnitId');
            const currentIds = new Set();

            for (const u of units) {
                currentIds.add(u.id);
                const content = _buildItemContent(u, selectedId);
                const isActive = u.id === selectedId;
                let li = _domCache.get(u.id);

                if (li) {
                    // Update existing DOM element in place — skip if unchanged to prevent flashing
                    if (li._lastContent !== content) {
                        li.innerHTML = content;
                        li._lastContent = content;
                    }
                    if (isActive && !li.classList.contains('active')) {
                        li.classList.add('active');
                    } else if (!isActive && li.classList.contains('active')) {
                        li.classList.remove('active');
                    }
                } else {
                    // Create new <li> element
                    li = document.createElement('li');
                    li.className = 'panel-list-item' + (isActive ? ' active' : '');
                    li.dataset.unitId = u.id;
                    li.setAttribute('role', 'option');
                    li.innerHTML = content;
                    li._lastContent = content;
                    li.addEventListener('click', () => {
                        const id = li.dataset.unitId;
                        TritiumStore.set('map.selectedUnitId', id);
                        EventBus.emit('unit:selected', { id });
                        render();
                    });
                    listEl.appendChild(li);
                    _domCache.set(u.id, li);
                }
            }

            // Remove DOM elements for units no longer present
            for (const [id, li] of _domCache) {
                if (!currentIds.has(id)) {
                    li.remove();
                    _domCache.delete(id);
                }
            }

            // Remove the "No units detected" placeholder if still present
            const emptyEl = listEl.querySelector('.panel-empty');
            if (emptyEl) emptyEl.remove();
        }

        /**
         * Load abilities for a unit and render ability buttons.
         * Fetches from /api/game/unit/{id}/upgrades to get granted abilities + cooldowns.
         */
        async function _loadAbilities(unitId, containerEl) {
            if (!unitId || !containerEl) return;
            try {
                const resp = await fetch(`/api/game/unit/${unitId}/upgrades`);
                if (!resp.ok) {
                    containerEl.innerHTML = '<span style="color:var(--text-ghost);font-size:0.45rem">No abilities</span>';
                    return;
                }
                const data = await resp.json();
                const abilities = data.abilities || [];
                if (abilities.length === 0) {
                    containerEl.innerHTML = '<span style="color:var(--text-ghost);font-size:0.45rem">No abilities granted</span>';
                    return;
                }

                // Fetch ability definitions to get names/descriptions
                let abilityDefs = [];
                try {
                    const defsResp = await fetch('/api/game/abilities');
                    if (defsResp.ok) abilityDefs = await defsResp.json();
                } catch (_) { /* ignore */ }

                const cooldowns = data.ability_cooldowns || {};
                const helpers = typeof window !== 'undefined' ? window.UpgradeHelpers : null;

                if (helpers && helpers.buildAbilityBarHTML) {
                    // Filter to only granted abilities
                    const grantedDefs = abilityDefs.filter(a => abilities.includes(a.ability_id));
                    containerEl.innerHTML = helpers.buildAbilityBarHTML(grantedDefs, cooldowns);
                } else {
                    // Fallback: simple button rendering
                    containerEl.innerHTML = abilities.map(aid => {
                        const cd = cooldowns[aid] || 0;
                        const ready = cd <= 0;
                        const cls = ready ? 'unit-ability-btn unit-ability-btn--ready' : 'unit-ability-btn unit-ability-btn--cooldown';
                        return `<button class="${cls}" data-ability-id="${_esc(aid)}" ${ready ? '' : 'disabled'}>${_esc(aid)}</button>`;
                    }).join('');
                }

                // Wire click handlers on ability buttons
                containerEl.querySelectorAll('.unit-ability-btn').forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const abilityId = btn.dataset.abilityId;
                        if (!abilityId || btn.disabled) return;
                        try {
                            const resp = await fetch('/api/game/ability', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ unit_id: unitId, ability_id: abilityId }),
                            });
                            if (resp.ok) {
                                // Flash feedback
                                btn.classList.add('unit-ability-btn--activated');
                                setTimeout(() => btn.classList.remove('unit-ability-btn--activated'), 300);
                                EventBus.emit('toast:show', {
                                    message: `Ability activated: ${abilityId.replace(/_/g, ' ')}`,
                                    type: 'success',
                                });
                                // Refresh abilities after a short delay (cooldown started)
                                setTimeout(() => _loadAbilities(unitId, containerEl), 500);
                            } else {
                                const err = await resp.json().catch(() => ({}));
                                EventBus.emit('toast:show', {
                                    message: err.detail || 'Ability failed',
                                    type: 'alert',
                                });
                            }
                        } catch (e) {
                            console.error('[UNIT] Use ability failed:', e);
                        }
                    });
                });
            } catch (e) {
                console.error('[UNIT] Load abilities failed:', e);
                containerEl.innerHTML = '<span style="color:var(--text-ghost);font-size:0.45rem">Error loading abilities</span>';
            }
        }

        let _lastDetailId = null;

        /**
         * Incrementally update the dynamic fields in the detail panel
         * without rebuilding the entire DOM.  Called on every store
         * notification for the already-selected unit.
         */
        function _updateDetailFields(u) {
            if (!detailEl || detailEl.style.display === 'none') return;

            // Update stat values by label text
            const rows = detailEl.querySelectorAll('.panel-stat-row');
            for (const row of rows) {
                const lbl = row.querySelector('.panel-stat-label');
                const val = row.querySelector('.panel-stat-value');
                if (!lbl || !val) continue;
                const key = lbl.textContent;
                let newText;
                switch (key) {
                    case 'HEALTH':
                        if (u.maxHealth) newText = `${Math.round(u.health)}/${u.maxHealth}`;
                        break;
                    case 'HEADING':
                        newText = u.heading !== undefined ? Math.round(u.heading) + '\u00B0' : '--';
                        break;
                    case 'POSITION': {
                        const pos = u.position || {};
                        newText = `(${(pos.x || 0).toFixed(1)}, ${(pos.y || 0).toFixed(1)})`;
                        break;
                    }
                    case 'FSM':
                        newText = (u.fsmState || '').toUpperCase();
                        if (u.fsmState) val.style.color = FSM_STATE_COLORS[u.fsmState] || '#888';
                        break;
                    case 'MORALE':
                        if (u.morale !== undefined) {
                            newText = Math.round(u.morale * 100) + '%';
                            val.style.color = u.morale > 0.6 ? 'var(--green)' : u.morale > 0.3 ? 'var(--amber)' : 'var(--magenta)';
                        }
                        break;
                    case 'DEGRADATION':
                        if (u.degradation !== undefined) newText = Math.round(u.degradation * 100) + '%';
                        break;
                    case 'BATTERY':
                        if (u.battery !== undefined) newText = Math.round(u.battery) + '%';
                        break;
                    case 'KILLS':
                        if (u.kills !== undefined) newText = String(u.kills);
                        break;
                    case 'AMMO':
                        if (u.ammoCount !== undefined) {
                            if (u.ammoCount < 0) {
                                newText = '\u221E';
                                val.style.color = 'var(--green)';
                            } else {
                                const ammoPct = u.ammoMax > 0 ? u.ammoCount / u.ammoMax : 0;
                                newText = u.ammoCount === 0 ? 'RELOADING' : `${u.ammoCount}${u.ammoMax > 0 ? '/' + u.ammoMax : ''}`;
                                val.style.color = u.ammoCount === 0 ? 'var(--text-ghost)' : ammoPct > 0.5 ? 'var(--green)' : ammoPct > 0.2 ? 'var(--amber)' : 'var(--magenta)';
                            }
                        }
                        break;
                }
                if (newText !== undefined && val.textContent !== newText) {
                    val.textContent = newText;
                }
            }

            // Update health bar fill
            if (u.maxHealth) {
                const hpPct = Math.round((u.health / u.maxHealth) * 100);
                const hpColor = hpPct > 60 ? 'var(--green)' : hpPct > 25 ? 'var(--amber)' : 'var(--magenta)';
                const fill = detailEl.querySelector('.panel-bar-fill');
                if (fill) {
                    fill.style.width = hpPct + '%';
                    fill.style.background = hpColor;
                }
            }

            // Update ammo bar fill
            if (u.ammoCount !== undefined && u.ammoMax > 0) {
                const ammoPct = u.ammoCount / u.ammoMax;
                const ammoColor = u.ammoCount === 0 ? 'var(--text-ghost)' : ammoPct > 0.5 ? 'var(--green)' : ammoPct > 0.2 ? 'var(--amber)' : 'var(--magenta)';
                const ammoFill = detailEl.querySelector('.unit-ammo-bar .panel-bar-fill');
                if (ammoFill) {
                    ammoFill.style.width = Math.round(ammoPct * 100) + '%';
                    ammoFill.style.background = ammoColor;
                }
            }

            // Update thought text incrementally
            const thoughtSection = detailEl.querySelector('.panel-section-label');
            // Find the THOUGHT section by scanning section labels
            const allSections = detailEl.querySelectorAll('.panel-section-label');
            for (const sec of allSections) {
                if (sec.textContent !== 'THOUGHT') continue;
                const thoughtContainer = sec.parentElement;
                if (!thoughtContainer) break;
                const emotionSpan = thoughtContainer.querySelector('span[style*="background"]');
                const quoteEl = thoughtContainer.querySelector('q');
                if (u.thoughtText) {
                    if (quoteEl && quoteEl.textContent !== u.thoughtText) {
                        quoteEl.textContent = u.thoughtText;
                    }
                    if (emotionSpan) {
                        const emotion = u.thoughtEmotion || 'neutral';
                        const emotionColor = {curious:'#00f0ff',afraid:'#fcee0a',angry:'#ff2a6d',happy:'#05ffa1',neutral:'#888888'}[emotion] || '#888888';
                        if (emotionSpan.textContent !== emotion) {
                            emotionSpan.textContent = emotion;
                            emotionSpan.style.background = emotionColor;
                        }
                    }
                } else if (!u.thoughtText && quoteEl) {
                    // Thought was cleared — hide section
                    thoughtContainer.style.display = 'none';
                }
                break;
            }
        }

        function renderDetail() {
            const selectedId = TritiumStore.get('map.selectedUnitId');
            if (!selectedId || !detailEl) {
                if (detailEl) detailEl.style.display = 'none';
                _lastDetailId = null;
                return;
            }
            const u = TritiumStore.units.get(selectedId);
            if (!u) {
                detailEl.style.display = 'none';
                _lastDetailId = null;
                return;
            }

            // Same unit selected — do incremental field updates only
            if (selectedId === _lastDetailId) {
                _updateDetailFields(u);
                return;
            }
            _lastDetailId = selectedId;

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
                ${(() => {
                    const si = SOURCE_BADGE[u.source] || SOURCE_BADGE.sim;
                    return `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">SOURCE</span>
                    <span class="panel-stat-value" style="color:${si.color}">${si.label}</span>
                </div>`;
                })()}
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
                ${u.weaponJammed ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">WEAPON</span>
                    <span class="panel-stat-value" style="color:var(--magenta);font-weight:bold">JAMMED</span>
                </div>` : ''}
                ${u.ammoDepleted ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">AMMO</span>
                    <span class="panel-stat-value" style="color:var(--magenta);font-weight:bold">DEPLETED</span>
                </div>` : u.ammoLow ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">AMMO</span>
                    <span class="panel-stat-value" style="color:var(--amber);font-weight:bold">LOW</span>
                </div>` : ''}
                ${u.kills !== undefined && u.kills > 0 ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">KILLS</span>
                    <span class="panel-stat-value" style="color:var(--magenta)">${u.kills}</span>
                </div>` : ''}
                ${u.stats && (u.stats.shots_fired > 0 || u.stats.distance_traveled > 0.1) ? (() => {
                    const s = u.stats;
                    const accPct = s.shots_fired > 0 ? Math.round((s.shots_hit / s.shots_fired) * 100) : 0;
                    return `
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">COMBAT STATS</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">SHOTS</span>
                        <span class="panel-stat-value">${s.shots_fired} fired / ${s.shots_hit} hit (${accPct}%)</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">DAMAGE</span>
                        <span class="panel-stat-value">${s.damage_dealt} dealt / ${s.damage_taken} taken</span>
                    </div>
                    ${s.distance_traveled > 0.1 ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">DISTANCE</span>
                        <span class="panel-stat-value">${s.distance_traveled}m traveled</span>
                    </div>` : ''}
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">TIME</span>
                        <span class="panel-stat-value">${s.time_alive}s alive / ${s.time_in_combat}s in combat</span>
                    </div>
                    ${s.assists > 0 ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">ASSISTS</span>
                        <span class="panel-stat-value">${s.assists}</span>
                    </div>` : ''}
                </div>`;
                })() : ''}
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
                ${u.crowdRole ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">CROWD ROLE</span>
                    <span class="panel-stat-value" style="color:${
                        u.crowdRole === 'instigator' ? 'var(--magenta)' : u.crowdRole === 'rioter' ? 'var(--amber)' : 'var(--cyan)'
                    }">${_esc(u.crowdRole.toUpperCase())}</span>
                </div>` : ''}
                ${u.instigatorState ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">INSTIGATOR</span>
                    <span class="panel-stat-value" style="color:${
                        u.instigatorState === 'active' ? 'var(--magenta)' : u.instigatorState === 'activating' ? 'var(--amber)' : 'var(--text-dim)'
                    }">${_esc(u.instigatorState.toUpperCase())}</span>
                </div>` : ''}
                ${u.droneVariant ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">DRONE TYPE</span>
                    <span class="panel-stat-value" style="color:${
                        u.droneVariant === 'bomber' ? 'var(--magenta)' : u.droneVariant === 'attack' ? 'var(--amber)' : 'var(--cyan)'
                    }">${_esc(u.droneVariant.toUpperCase())}</span>
                </div>` : ''}
                ${u.altitude !== undefined && u.altitude > 0 ? `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">ALTITUDE</span>
                    <span class="panel-stat-value">${Math.round(u.altitude)}m</span>
                </div>` : ''}
                ${u.ammoCount !== undefined && !['person', 'camera', 'sensor', 'animal', 'vehicle'].includes(u.type) ? (() => {
                    if (u.ammoCount < 0) {
                        return `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">AMMO</span>
                    <span class="panel-stat-value" style="color:var(--green)">\u221E</span>
                </div>`;
                    }
                    const ammoPct = u.ammoMax > 0 ? u.ammoCount / u.ammoMax : 0;
                    const ammoColor = u.ammoCount === 0 ? 'var(--text-ghost)'
                        : ammoPct > 0.5 ? 'var(--green)'
                        : ammoPct > 0.2 ? 'var(--amber)'
                        : 'var(--magenta)';
                    const ammoLabel = u.ammoCount === 0 ? 'RELOADING' : `${u.ammoCount}${u.ammoMax > 0 ? '/' + u.ammoMax : ''}`;
                    return `
                <div class="panel-stat-row">
                    <span class="panel-stat-label">AMMO</span>
                    <span class="panel-stat-value" style="color:${ammoColor}">${ammoLabel}</span>
                </div>
                ${u.ammoMax > 0 ? `<div class="panel-bar unit-ammo-bar" style="margin:2px 0 4px">
                    <div class="panel-bar-fill" style="width:${Math.round(ammoPct * 100)}%;background:${ammoColor}"></div>
                </div>` : ''}`;
                })() : ''}
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
                ${u.identity ? (() => {
                    const id = u.identity;
                    const hasPerson = id.first_name || id.last_name;
                    const hasDevice = id.bluetooth_mac || id.wifi_mac || id.cell_id;
                    const hasVehicle = id.license_plate || id.vehicle_make;
                    const hasRobot = id.serial_number || id.firmware_version;
                    return `
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">IDENTITY</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">ID</span>
                        <span class="panel-stat-value" style="font-family:var(--font-mono);color:var(--cyan);letter-spacing:1px">${_esc(id.short_id)}</span>
                    </div>
                    ${hasPerson ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">NAME</span>
                        <span class="panel-stat-value">${_esc(id.first_name)} ${_esc(id.last_name)}</span>
                    </div>` : ''}
                    ${id.home_address ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">HOME</span>
                        <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.home_address)}</span>
                    </div>` : ''}
                    ${id.employer ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">EMPLOYER</span>
                        <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.employer)}</span>
                    </div>` : ''}
                    ${id.work_address ? `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">WORK ADDR</span>
                        <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.work_address)}</span>
                    </div>` : ''}
                    ${hasDevice ? `
                    <div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border-subtle, var(--border))">
                        <div class="panel-section-label" style="font-size:0.4rem;color:var(--text-ghost)">DEVICE SIGNATURES</div>
                        ${id.bluetooth_mac ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">BLE MAC</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-size:0.4rem;color:var(--cyan)">${_esc(id.bluetooth_mac)}</span>
                        </div>` : ''}
                        ${id.wifi_mac ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">WIFI MAC</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-size:0.4rem;color:var(--cyan)">${_esc(id.wifi_mac)}</span>
                        </div>` : ''}
                        ${id.cell_id ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">IMSI</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-size:0.4rem;color:var(--amber)">${_esc(id.cell_id)}</span>
                        </div>` : ''}
                    </div>` : ''}
                    ${hasVehicle ? `
                    <div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border-subtle, var(--border))">
                        <div class="panel-section-label" style="font-size:0.4rem;color:var(--text-ghost)">VEHICLE</div>
                        ${id.license_plate ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">PLATE</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-weight:bold;color:var(--green);letter-spacing:1px">${_esc(id.license_plate)}</span>
                        </div>` : ''}
                        ${id.vehicle_make ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">VEHICLE</span>
                            <span class="panel-stat-value" style="font-size:0.45rem">${id.vehicle_year ? _esc(id.vehicle_year) + ' ' : ''}${_esc(id.vehicle_color || '')} ${_esc(id.vehicle_make)} ${_esc(id.vehicle_model || '')}</span>
                        </div>` : ''}
                        ${id.owner_name ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">REG OWNER</span>
                            <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.owner_name)}</span>
                        </div>` : ''}
                        ${id.owner_address ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">REG ADDR</span>
                            <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.owner_address)}</span>
                        </div>` : ''}
                    </div>` : ''}
                    ${hasRobot ? `
                    <div style="margin-top:4px;padding-top:4px;border-top:1px solid var(--border-subtle, var(--border))">
                        <div class="panel-section-label" style="font-size:0.4rem;color:var(--text-ghost)">SYSTEM</div>
                        ${id.serial_number ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">SERIAL</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-size:0.45rem;color:var(--cyan)">${_esc(id.serial_number)}</span>
                        </div>` : ''}
                        ${id.firmware_version ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">FIRMWARE</span>
                            <span class="panel-stat-value" style="font-family:var(--font-mono);font-size:0.45rem">${_esc(id.firmware_version)}</span>
                        </div>` : ''}
                        ${id.operator ? `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">OPERATOR</span>
                            <span class="panel-stat-value" style="font-size:0.45rem">${_esc(id.operator)}</span>
                        </div>` : ''}
                    </div>` : ''}
                </div>`;
                })() : ''}
                ${u.backstoryBackground ? `
                <div style="margin-top:6px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">BACKSTORY</div>
                    <div style="margin-top:2px;font-size:0.5rem;color:var(--text-secondary);line-height:1.4">
                        ${_esc(u.backstoryBackground)}
                    </div>
                    ${u.backstoryMotivation ? `
                    <div style="margin-top:4px;font-size:0.45rem;color:var(--text-ghost)">
                        <span style="color:var(--cyan)">MOTIVATION:</span> ${_esc(u.backstoryMotivation)}
                    </div>` : ''}
                    ${u.backstoryTraits && u.backstoryTraits.length ? `
                    <div style="margin-top:3px;display:flex;gap:3px;flex-wrap:wrap">
                        ${u.backstoryTraits.map(t => `<span style="display:inline-block;padding:1px 4px;border-radius:2px;font-size:0.4rem;text-transform:uppercase;background:var(--surface-3);color:var(--text-dim);border:1px solid var(--border)">${_esc(t)}</span>`).join('')}
                    </div>` : ''}
                    ${u.backstorySpeechPattern ? `
                    <div style="margin-top:3px;font-size:0.45rem;color:var(--text-ghost)">
                        <span style="color:var(--text-dim)">SPEECH:</span> ${_esc(u.backstorySpeechPattern)}
                    </div>` : ''}
                    ${u.backstoryTacticalPref ? `
                    <div style="margin-top:3px;font-size:0.45rem;color:var(--text-ghost)">
                        <span style="color:var(--amber)">TACTICS:</span> ${_esc(u.backstoryTacticalPref)}
                    </div>` : ''}
                    ${u.backstoryNeighborhood ? `
                    <div style="margin-top:3px;font-size:0.45rem;color:var(--text-ghost)">
                        <span style="color:var(--green)">LOCAL:</span> ${_esc(u.backstoryNeighborhood)}
                    </div>` : ''}
                    ${u.backstoryRoutine ? `
                    <div style="margin-top:3px;font-size:0.45rem;color:var(--text-ghost)">
                        <span style="color:var(--cyan)">ROUTINE:</span> ${_esc(u.backstoryRoutine)}
                    </div>` : ''}
                </div>` : ''}
                ${_renderInventory(u.inventory)}
                ${alliance === 'neutral' && ['person','animal','vehicle'].includes(u.type || u.asset_type) ? `
                <div style="margin-top:6px">
                    <button class="panel-action-btn panel-npc-detail-btn" style="width:100%;font-size:0.5rem">VIEW NPC DETAILS</button>
                </div>` : ''}
                ${alliance === 'friendly' ? `
                <div class="unit-abilities-section" data-section="abilities" style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border)">
                    <div class="panel-section-label">ABILITIES</div>
                    <div class="unit-ability-bar" data-bind="ability-bar"></div>
                </div>
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

            // Wire ability buttons for friendly units
            if (alliance === 'friendly') {
                const abilityBar = detailEl.querySelector('[data-bind="ability-bar"]');
                if (abilityBar) {
                    _loadAbilities(selectedId, abilityBar);
                }
            }

            // Wire command send button
            const cmdInput = detailEl.querySelector('.panel-cmd-input');
            const cmdSend = detailEl.querySelector('.panel-cmd-send');
            const cmdStatus = detailEl.querySelector('.panel-cmd-status');
            if (cmdInput && cmdSend) {
                const sendCmd = () => {
                    const cmd = cmdInput.value.trim();
                    if (!cmd) return;
                    if (cmdStatus) cmdStatus.textContent = 'Sending...';
                    const payload = cmd.includes('(')
                        ? { action: cmd }
                        : { action: cmd, params: [selectedId] };
                    fetch('/api/amy/command', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
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

        // Subscribe — units fires at ~60Hz (RAF-batched), detail fields update incrementally
        panel._unsubs.push(
            TritiumStore.on('units', () => { render(); renderDetail(); }),
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
