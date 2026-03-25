// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Dossier Groups Panel — toggle target grouping by dossier on the map
// When enabled, targets sharing a dossier are collapsed into a single
// icon with a count badge, reducing visual clutter for correlated targets.
// Provides a toggle and a live view of active dossier groups.

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';
import { _esc } from '/lib/utils.js';


// State
let _enabled = false;
let _dossierMap = new Map();  // dossier_id -> { targets: [...], name, threat_level }
let _refreshTimer = null;

/**
 * Check if dossier grouping is currently enabled.
 * Used by map renderers to decide whether to cluster by dossier.
 */
export function isDossierGroupingEnabled() {
    return _enabled;
}

/**
 * Get the dossier groups: Map of dossier_id -> { targets, name, lat, lng }
 * Map renderers use this to draw grouped icons.
 */
export function getDossierGroups() {
    return _dossierMap;
}

async function _fetchDossiers() {
    try {
        const r = await fetch('/api/dossiers?limit=200');
        if (!r.ok) return [];
        return await r.json();
    } catch { return []; }
}

async function _rebuild() {
    const dossiers = await _fetchDossiers();
    _dossierMap.clear();

    for (const d of dossiers) {
        const targets = d.target_ids || d.signals?.map(s => s.target_id) || [];
        if (targets.length < 2) continue; // Only group 2+ targets

        // Compute center position from target positions
        let latSum = 0, lngSum = 0, posCount = 0;
        for (const tid of targets) {
            // Look up position from store targets
            const t = _lookupTarget(tid);
            if (t && t.lat && t.lng) {
                latSum += t.lat;
                lngSum += t.lng;
                posCount++;
            }
        }

        _dossierMap.set(d.id || d.dossier_id, {
            id: d.id || d.dossier_id,
            name: d.name || d.entity_type || 'Unknown',
            targets: targets,
            count: targets.length,
            threat_level: d.threat_level || 'none',
            lat: posCount > 0 ? latSum / posCount : null,
            lng: posCount > 0 ? lngSum / posCount : null,
        });
    }

    EventBus.emit('dossier-groups:updated', {
        enabled: _enabled,
        groups: Array.from(_dossierMap.values()),
    });
}

function _lookupTarget(targetId) {
    // Try store units first
    const unit = TritiumStore.units.get(targetId);
    if (unit?.position) {
        return { lat: unit.position.lat || unit.position.y, lng: unit.position.lng || unit.position.x };
    }
    return null;
}

const THREAT_COLORS = {
    none: '#888',
    low: '#05ffa1',
    medium: '#fcee0a',
    high: '#ff8c00',
    critical: '#ff2a6d',
};

function _renderGroups(bodyEl) {
    const listEl = bodyEl.querySelector('[data-bind="group-list"]');
    if (!listEl) return;

    if (!_enabled || _dossierMap.size === 0) {
        listEl.innerHTML = `<div style="color:var(--text-dim,#888);font-size:0.65rem;padding:8px;">
            ${_enabled ? 'No dossier groups found (need 2+ targets per dossier)' : 'Grouping disabled'}
        </div>`;
        return;
    }

    const groups = Array.from(_dossierMap.values());
    listEl.innerHTML = groups.map(g => {
        const color = THREAT_COLORS[g.threat_level] || '#888';
        return `<div style="display:flex;align-items:center;gap:8px;padding:4px 8px;border-bottom:1px solid rgba(0,240,255,0.1);cursor:pointer;" data-dossier-id="${_esc(g.id)}">
            <div style="min-width:24px;height:24px;border-radius:50%;background:rgba(0,240,255,0.15);border:1px solid ${color};display:flex;align-items:center;justify-content:center;font-size:0.7rem;font-weight:700;color:${color};">${g.count}</div>
            <div style="flex:1;overflow:hidden;">
                <div style="color:var(--text,#e0e0e0);font-size:0.7rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_esc(g.name)}</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">${g.targets.length} targets</div>
            </div>
            <div style="color:${color};font-size:0.6rem;text-transform:uppercase;">${g.threat_level}</div>
        </div>`;
    }).join('');

    // Click handler to center map on dossier group and highlight members
    listEl.querySelectorAll('[data-dossier-id]').forEach(el => {
        el.addEventListener('click', () => {
            const gid = el.dataset.dossierId;
            const g = _dossierMap.get(gid);
            if (!g) return;

            // Toggle selection: clicking same group deselects
            const wasSelected = el.classList.contains('ops-group-selected');

            // Clear previous selection styling
            listEl.querySelectorAll('.ops-group-selected').forEach(s => {
                s.classList.remove('ops-group-selected');
                s.style.background = '';
            });

            if (wasSelected) {
                // Deselect
                EventBus.emit('dossier-groups:selected', { group: null });
            } else {
                // Select this group
                el.classList.add('ops-group-selected');
                el.style.background = 'rgba(0,240,255,0.08)';
                EventBus.emit('dossier-groups:selected', {
                    group: g,
                    groupId: gid,
                    targets: g.targets,
                    name: g.name,
                    lat: g.lat,
                    lng: g.lng,
                    color: THREAT_COLORS[g.threat_level] || '#00f0ff',
                });
                if (g.lat && g.lng) {
                    EventBus.emit('map:center', { lat: g.lat, lng: g.lng });
                }
            }
        });
    });
}

export const DossierGroupsPanelDef = {
    id: 'dossier-groups',
    title: 'DOSSIER GROUPS',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 320, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;font-family:var(--font-mono,"JetBrains Mono",monospace);font-size:0.75rem;';
        el.innerHTML = `
            <div style="padding:8px;border-bottom:1px solid rgba(0,240,255,0.2);display:flex;align-items:center;gap:8px;">
                <label style="display:flex;align-items:center;gap:6px;cursor:pointer;color:var(--text,#e0e0e0);">
                    <input type="checkbox" data-bind="toggle" style="accent-color:var(--cyan,#00f0ff);width:14px;height:14px;" />
                    <span>Group by Dossier</span>
                </label>
                <button data-action="refresh" style="margin-left:auto;padding:2px 8px;font-size:0.6rem;background:rgba(0,240,255,0.1);border:1px solid rgba(0,240,255,0.3);color:var(--cyan,#00f0ff);border-radius:3px;cursor:pointer;">REFRESH</button>
            </div>
            <div data-bind="group-list" style="flex:1;overflow-y:auto;">
                <div style="color:var(--text-dim,#888);font-size:0.65rem;padding:8px;">Grouping disabled</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const toggle = bodyEl.querySelector('[data-bind="toggle"]');
        if (toggle) {
            toggle.checked = _enabled;
            toggle.addEventListener('change', () => {
                _enabled = toggle.checked;
                if (_enabled) {
                    _rebuild().then(() => _renderGroups(bodyEl));
                } else {
                    _dossierMap.clear();
                    EventBus.emit('dossier-groups:updated', { enabled: false, groups: [] });
                    _renderGroups(bodyEl);
                }
            });
        }

        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                if (_enabled) _rebuild().then(() => _renderGroups(bodyEl));
            });
        }

        if (_enabled) {
            _rebuild().then(() => _renderGroups(bodyEl));
        }

        _refreshTimer = setInterval(() => {
            if (_enabled) _rebuild().then(() => _renderGroups(bodyEl));
        }, 10000);
    },

    unmount(bodyEl) {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    },
};
