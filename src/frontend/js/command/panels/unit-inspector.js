// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Unit Inspector Panel
// Draggable panel for inspecting and controlling individual units.
// Replaces the blocking device modal with an inline inspector.
// Subscribes to: units (Map), map.selectedUnitId

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { DeviceControlRegistry, DeviceAPI } from '../device-modal.js';
import { _esc } from '/lib/utils.js';


function _resolveModalType(unit) {
    const type = unit.asset_type || unit.type || 'generic';
    const alliance = unit.alliance || 'unknown';
    const npcTypes = ['person', 'animal', 'vehicle'];
    return (npcTypes.includes(type) && alliance === 'neutral') ? 'npc' : type;
}

function _renderStats(unit) {
    const s = unit.stats;
    if (!s || (s.shots_fired === 0 && s.distance_traveled <= 0.1)) return '';
    const accPct = s.shots_fired > 0 ? Math.round((s.shots_hit / s.shots_fired) * 100) : 0;
    return `
        <div style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border)">
            <div style="font-size:0.45rem;color:var(--text-ghost);text-transform:uppercase;letter-spacing:1px;margin-bottom:4px">COMBAT STATS</div>
            <div style="display:flex;justify-content:space-between;font-size:0.5rem;color:var(--text-secondary)">
                <span>SHOTS</span><span>${_esc(String(s.shots_fired))} fired / ${_esc(String(s.shots_hit))} hit (${accPct}%)</span>
            </div>
            <div style="display:flex;justify-content:space-between;font-size:0.5rem;color:var(--text-secondary)">
                <span>DAMAGE</span><span>${s.damage_dealt} dealt / ${s.damage_taken} taken</span>
            </div>
            ${s.distance_traveled > 0.1 ? `
            <div style="display:flex;justify-content:space-between;font-size:0.5rem;color:var(--text-secondary)">
                <span>DISTANCE</span><span>${s.distance_traveled}m traveled</span>
            </div>` : ''}
            <div style="display:flex;justify-content:space-between;font-size:0.5rem;color:var(--text-secondary)">
                <span>TIME</span><span>${s.time_alive}s alive / ${s.time_in_combat}s combat</span>
            </div>
            ${s.assists > 0 ? `
            <div style="display:flex;justify-content:space-between;font-size:0.5rem;color:var(--text-secondary)">
                <span>ASSISTS</span><span>${s.assists}</span>
            </div>` : ''}
        </div>`;
}

const TYPE_FILTER_OPTIONS = [
    'ALL', 'turret', 'heavy_turret', 'missile_turret', 'rover', 'drone',
    'scout_drone', 'tank', 'apc', 'sensor', 'camera', 'person',
];

const ALLIANCE_FILTER_OPTIONS = ['ALL', 'friendly', 'hostile', 'neutral'];

export const UnitInspectorPanelDef = {
    id: 'unit-inspector',
    title: 'UNIT INSPECTOR',
    defaultPosition: { x: null, y: 60 },
    defaultSize: { w: 320, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'unit-inspector-inner';

        const typeOpts = TYPE_FILTER_OPTIONS.map(t =>
            `<option value="${t}">${t.toUpperCase()}</option>`
        ).join('');

        const allianceOpts = ALLIANCE_FILTER_OPTIONS.map(a =>
            `<option value="${a}">${a.toUpperCase()}</option>`
        ).join('');

        el.innerHTML = `
            <div class="ui-nav-bar">
                <button class="ui-nav-btn" data-action="prev">&lt;&lt;</button>
                <span class="ui-nav-label" data-bind="nav-label">-- / --</span>
                <button class="ui-nav-btn" data-action="next">&gt;&gt;</button>
            </div>
            <div class="ui-filter-row">
                <input class="panel-filter ui-search" type="text" placeholder="Search units..." data-bind="search">
                <select class="panel-filter ui-type-filter" data-bind="type-filter">
                    ${typeOpts}
                </select>
                <select class="panel-filter ui-alliance-filter" data-bind="alliance-filter">
                    ${allianceOpts}
                </select>
            </div>
            <div class="ui-content" data-bind="content"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const navLabel = bodyEl.querySelector('[data-bind="nav-label"]');
        const contentEl = bodyEl.querySelector('[data-bind="content"]');
        const searchEl = bodyEl.querySelector('[data-bind="search"]');
        const typeFilterEl = bodyEl.querySelector('[data-bind="type-filter"]');
        const allianceFilterEl = bodyEl.querySelector('[data-bind="alliance-filter"]');
        const prevBtn = bodyEl.querySelector('[data-action="prev"]');
        const nextBtn = bodyEl.querySelector('[data-action="next"]');

        let currentControl = null;
        let _lastRenderedId = null;
        let _lastRenderedType = null;

        function _getFilteredIds() {
            const search = searchEl ? (searchEl.value || '').toLowerCase() : '';
            const typeFilter = typeFilterEl ? typeFilterEl.value : 'ALL';
            const allianceFilter = allianceFilterEl ? allianceFilterEl.value : 'ALL';
            const ids = [];

            TritiumStore.units.forEach((u) => {
                if (typeFilter !== 'ALL' && (u.type || '') !== typeFilter) return;
                if (allianceFilter !== 'ALL' && (u.alliance || '') !== allianceFilter) return;
                if (search) {
                    const name = (u.name || u.id || '').toLowerCase();
                    const id = (u.id || '').toLowerCase();
                    if (!name.includes(search) && !id.includes(search)) return;
                }
                ids.push(u.id);
            });

            return ids;
        }

        function _renderUnit() {
            const selectedId = TritiumStore.get('map.selectedUnitId');
            const ids = _getFilteredIds();
            const idx = selectedId ? ids.indexOf(selectedId) : -1;

            // Update nav label
            if (navLabel) {
                navLabel.textContent = idx >= 0 ? `${idx + 1} / ${ids.length}` : `-- / ${ids.length}`;
            }

            if (!contentEl) return;

            if (!selectedId || idx < 0) {
                if (_lastRenderedId !== null) {
                    if (currentControl && currentControl.destroy) {
                        currentControl.destroy(contentEl);
                        currentControl = null;
                    }
                    contentEl.innerHTML = '<div style="padding:12px;color:var(--text-ghost);text-align:center;font-size:0.55rem">Click a unit to inspect</div>';
                    _lastRenderedId = null;
                    _lastRenderedType = null;
                }
                return;
            }

            const unit = TritiumStore.units.get(selectedId);
            if (!unit) {
                if (_lastRenderedId !== null) {
                    if (currentControl && currentControl.destroy) {
                        currentControl.destroy(contentEl);
                        currentControl = null;
                    }
                    contentEl.innerHTML = '<div style="padding:12px;color:var(--text-ghost);text-align:center;font-size:0.55rem">Unit not found</div>';
                    _lastRenderedId = null;
                    _lastRenderedType = null;
                }
                return;
            }

            const resolvedType = _resolveModalType(unit);

            // If same unit and same type, do incremental update instead of full re-render.
            // This prevents thought text flashing and preserves input focus.
            if (selectedId === _lastRenderedId && resolvedType === _lastRenderedType && currentControl) {
                if (currentControl.update) {
                    currentControl.update(contentEl, unit);
                }
                // Update stats section in-place
                const statsEl = contentEl.querySelector('.dc-stats-live');
                if (statsEl) {
                    statsEl.innerHTML = _renderStats(unit);
                }
                return;
            }

            // Full re-render: different unit or type
            if (currentControl && currentControl.destroy) {
                currentControl.destroy(contentEl);
                currentControl = null;
            }

            const control = DeviceControlRegistry.get(resolvedType);
            currentControl = control;
            _lastRenderedId = selectedId;
            _lastRenderedType = resolvedType;

            const currentAlliance = (unit.alliance || 'unknown').toLowerCase();
            contentEl.innerHTML = control.render(unit) + '<div class="dc-stats-live">' + _renderStats(unit) + '</div>' +
                '<div class="tag-btn-row" data-bind="ui-tag-buttons" style="margin-top:8px;padding-top:6px;border-top:1px solid var(--border)">' +
                    '<button class="tag-btn tag-btn-friendly' + (currentAlliance === 'friendly' ? ' active' : '') + '" data-ui-tag="friendly">FRIENDLY</button>' +
                    '<button class="tag-btn tag-btn-hostile' + (currentAlliance === 'hostile' ? ' active' : '') + '" data-ui-tag="hostile">HOSTILE</button>' +
                    '<button class="tag-btn tag-btn-vip' + (unit.vip ? ' active' : '') + '" data-ui-tag="vip">VIP</button>' +
                '</div>' +
                '<div style="margin-top:6px;display:flex;gap:4px">' +
                    '<button class="panel-action-btn" data-action="investigate" style="flex:1;font-size:0.45rem;background:rgba(0,240,255,0.12);border:1px solid #00f0ff;color:#00f0ff;font-weight:700;letter-spacing:0.06em;cursor:pointer;padding:6px">INVESTIGATE</button>' +
                    '<button class="panel-action-btn" data-action="ar-export" style="flex:1;font-size:0.45rem">EXPORT AR</button>' +
                '</div>' +
                '<div class="ui-ar-export-result" data-bind="ar-result" style="display:none;margin-top:6px;font-size:0.4rem;color:var(--text-ghost);max-height:120px;overflow:auto"></div>';
            control.bind(contentEl, unit, DeviceAPI);

            // Wire tagging buttons (FRIENDLY / HOSTILE / VIP)
            const tagBtns = contentEl.querySelectorAll('[data-ui-tag]');
            tagBtns.forEach(btn => {
                btn.addEventListener('click', async () => {
                    const tag = btn.dataset.uiTag;
                    const targetId = unit.id;
                    if (!targetId) return;

                    try {
                        if (tag === 'vip') {
                            const isVip = btn.classList.contains('active');
                            await fetch(`/api/targets/${encodeURIComponent(targetId)}/classify`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    target_id: targetId,
                                    alliance: isVip ? (unit.alliance || 'unknown') : (unit.alliance || 'unknown'),
                                    reason: isVip ? 'VIP tag removed' : 'Tagged as VIP',
                                }),
                            });
                            unit.vip = !isVip;
                            btn.classList.toggle('active');
                            EventBus.emit('toast:show', { message: isVip ? 'VIP tag removed' : `${targetId} tagged as VIP`, type: 'info' });
                        } else {
                            const resp = await fetch(`/api/targets/${encodeURIComponent(targetId)}/classify`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    target_id: targetId,
                                    alliance: tag,
                                    reason: `Operator tagged as ${tag}`,
                                }),
                            });
                            if (resp.ok) {
                                unit.alliance = tag;
                                tagBtns.forEach(b => {
                                    if (b.dataset.uiTag !== 'vip') {
                                        b.classList.toggle('active', b.dataset.uiTag === tag);
                                    }
                                });
                                EventBus.emit('toast:show', { message: `${targetId} tagged as ${tag.toUpperCase()}`, type: 'info' });
                            }
                        }
                    } catch (_err) {
                        EventBus.emit('toast:show', { message: 'Tag update failed', type: 'error' });
                    }
                });
            });

            // Wire INVESTIGATE button — opens dossier panel for this target
            const investigateBtn = contentEl.querySelector('[data-action="investigate"]');
            if (investigateBtn) {
                investigateBtn.addEventListener('click', () => {
                    // Open the dossiers panel
                    if (window.panelManager) {
                        window.panelManager.open('dossiers');
                    }
                    // Emit event to load this target's dossier
                    EventBus.emit('dossier:load-target', { target_id: unit.id });
                });
            }

            // Wire AR export button
            const arBtn = contentEl.querySelector('[data-action="ar-export"]');
            const arResult = contentEl.querySelector('[data-bind="ar-result"]');
            if (arBtn) {
                arBtn.addEventListener('click', async () => {
                    try {
                        const resp = await fetch('/api/targets/ar-export?max_targets=50');
                        if (!resp.ok) {
                            if (arResult) {
                                arResult.style.display = 'block';
                                arResult.textContent = 'AR export unavailable';
                            }
                            return;
                        }
                        const data = await resp.json();
                        const json = JSON.stringify(data, null, 2);
                        // Copy to clipboard
                        try {
                            await navigator.clipboard.writeText(json);
                            EventBus.emit('toast:show', { message: `AR export copied: ${data.target_count || 0} targets`, type: 'info' });
                        } catch (_clipErr) {
                            // Fallback: show in panel
                            EventBus.emit('toast:show', { message: `AR export: ${data.target_count || 0} targets`, type: 'info' });
                        }
                        if (arResult) {
                            arResult.style.display = 'block';
                            arResult.innerHTML = `<pre style="white-space:pre-wrap;word-break:break-all;margin:0;color:var(--cyan)">${_esc(json)}</pre>`;
                        }
                    } catch (_err) {
                        if (arResult) {
                            arResult.style.display = 'block';
                            arResult.textContent = 'AR export failed';
                        }
                    }
                });
            }
        }

        function _navigate(delta) {
            const ids = _getFilteredIds();
            if (ids.length === 0) return;

            const selectedId = TritiumStore.get('map.selectedUnitId');
            let idx = selectedId ? ids.indexOf(selectedId) : -1;

            if (idx < 0) {
                idx = delta > 0 ? 0 : ids.length - 1;
            } else {
                idx = (idx + delta + ids.length) % ids.length;
            }

            TritiumStore.set('map.selectedUnitId', ids[idx]);
            EventBus.emit('unit:selected', { id: ids[idx] });
        }

        // Wire buttons
        if (prevBtn) prevBtn.addEventListener('click', () => _navigate(-1));
        if (nextBtn) nextBtn.addEventListener('click', () => _navigate(1));

        // Wire filter changes
        const onFilterChange = () => _renderUnit();
        if (searchEl) searchEl.addEventListener('input', onFilterChange);
        if (typeFilterEl) typeFilterEl.addEventListener('change', onFilterChange);
        if (allianceFilterEl) allianceFilterEl.addEventListener('change', onFilterChange);

        // Subscribe to store changes
        panel._unsubs.push(
            TritiumStore.on('map.selectedUnitId', _renderUnit),
            TritiumStore.on('units', _renderUnit),
        );

        // Cleanup filter listeners
        panel._unsubs.push(() => {
            if (searchEl) searchEl.removeEventListener('input', onFilterChange);
            if (typeFilterEl) typeFilterEl.removeEventListener('change', onFilterChange);
            if (allianceFilterEl) allianceFilterEl.removeEventListener('change', onFilterChange);
        });

        // Initial render
        _renderUnit();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
