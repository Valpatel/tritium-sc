// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Zone Management Panel
// Shows zones, their alert status, event counts.
// CRUD via /api/zones.
// Emits zone:selected event when a zone is clicked (for map highlighting).

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const ZonesPanelDef = {
    id: 'zones',
    title: 'ZONES',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 280, h: 340 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'zones-panel-inner';
        el.innerHTML = `
            <div class="zone-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="create-zone">+ NEW ZONE</button>
            </div>
            <ul class="panel-list zone-list" data-bind="zone-list" role="listbox" aria-label="Security zones">
                <li class="panel-empty">Loading zones...</li>
            </ul>
            <div class="zone-detail" data-bind="zone-detail" style="display:none"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const zoneListEl = bodyEl.querySelector('[data-bind="zone-list"]');
        const zoneDetailEl = bodyEl.querySelector('[data-bind="zone-detail"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const createBtn = bodyEl.querySelector('[data-action="create-zone"]');

        let zones = [];
        let selectedZoneId = null;

        function renderZones() {
            if (!zoneListEl) return;
            if (zones.length === 0) {
                zoneListEl.innerHTML = '<li class="panel-empty">No zones defined</li>';
                return;
            }

            zoneListEl.innerHTML = zones.map(z => {
                const isActive = selectedZoneId === z.id;
                const dotClass = z.alert_active ? 'panel-dot-hostile'
                    : z.enabled ? 'panel-dot-green'
                    : 'panel-dot-neutral';
                const eventCount = z.event_count || 0;
                return `<li class="panel-list-item zone-item${isActive ? ' active' : ''}" data-zone-id="${z.id}" role="option">
                    <span class="panel-dot ${dotClass}"></span>
                    <span class="zone-item-info">
                        <span class="zone-item-name">${_esc(z.name || `Zone ${z.id}`)}</span>
                        <span class="zone-item-type mono" style="font-size:0.45rem;color:var(--text-ghost)">${_esc(z.zone_type || 'perimeter')}</span>
                    </span>
                    <span class="mono" style="font-size:0.5rem;color:var(--text-dim)">${eventCount} events</span>
                    <button class="panel-btn zone-delete-btn" data-action="delete-zone" data-zone-id="${z.id}" title="Delete zone">&times;</button>
                </li>`;
            }).join('');

            zoneListEl.querySelectorAll('.zone-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action="delete-zone"]')) return;
                    const zid = parseInt(item.dataset.zoneId, 10);
                    if (selectedZoneId === zid) {
                        selectedZoneId = null;
                        if (zoneDetailEl) zoneDetailEl.style.display = 'none';
                    } else {
                        selectedZoneId = zid;
                        showZoneDetail(zid);
                    }
                    renderZones();
                    EventBus.emit('zone:selected', { id: selectedZoneId });
                });
            });

            zoneListEl.querySelectorAll('[data-action="delete-zone"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const zid = btn.dataset.zoneId;
                    try {
                        await fetch(`/api/zones/${zid}`, { method: 'DELETE' });
                        if (selectedZoneId === parseInt(zid, 10)) {
                            selectedZoneId = null;
                            if (zoneDetailEl) zoneDetailEl.style.display = 'none';
                        }
                        fetchZones();
                    } catch (_) {}
                });
            });
        }

        async function showZoneDetail(zoneId) {
            if (!zoneDetailEl) return;
            const zone = zones.find(z => z.id === zoneId);
            if (!zone) {
                zoneDetailEl.style.display = 'none';
                return;
            }

            zoneDetailEl.style.display = '';
            const enabledColor = zone.enabled ? '#05ffa1' : '#ff2a6d';
            const enabledText = zone.enabled ? 'ENABLED' : 'DISABLED';
            const polygonPts = zone.polygon || zone.points || [];
            zoneDetailEl.innerHTML = `
                <div class="panel-section-label">ZONE DETAIL</div>
                <div class="panel-stat-row"><span class="panel-stat-label">NAME</span><span class="panel-stat-value">${_esc(zone.name)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">TYPE</span><span class="panel-stat-value">${_esc(zone.zone_type || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">STATUS</span><span class="panel-stat-value" style="color:${enabledColor}">${enabledText}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">EVENTS</span><span class="panel-stat-value">${zone.event_count || 0}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">VERTICES</span><span class="panel-stat-value">${polygonPts.length}</span></div>
                <div class="zone-detail-actions">
                    <button class="panel-action-btn" data-action="toggle-zone" title="Toggle zone enabled/disabled">${zone.enabled ? 'DISABLE' : 'ENABLE'}</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="center-zone" title="Center map on zone">CENTER</button>
                </div>
            `;

            // Toggle enabled
            zoneDetailEl.querySelector('[data-action="toggle-zone"]')?.addEventListener('click', async () => {
                try {
                    await fetch(`/api/zones/${zoneId}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: !zone.enabled }),
                    });
                    fetchZones();
                    EventBus.emit('toast:show', { message: `Zone ${zone.enabled ? 'disabled' : 'enabled'}`, type: 'info' });
                } catch (_) {}
            });

            // Center map on zone
            zoneDetailEl.querySelector('[data-action="center-zone"]')?.addEventListener('click', () => {
                if (polygonPts.length > 0) {
                    const cx = polygonPts.reduce((s, p) => s + (p[0] || p.x || 0), 0) / polygonPts.length;
                    const cy = polygonPts.reduce((s, p) => s + (p[1] || p.y || 0), 0) / polygonPts.length;
                    EventBus.emit('map:centerOnUnit', { id: null, x: cx, y: cy });
                } else if (zone.position) {
                    EventBus.emit('map:centerOnUnit', { id: null, x: zone.position.x || 0, y: zone.position.y || 0 });
                }
            });

            // Fetch events for this zone
            try {
                const resp = await fetch(`/api/zones/${zoneId}/events`);
                if (resp.ok) {
                    const events = await resp.json();
                    if (events.length > 0) {
                        const eventHtml = events.slice(0, 5).map(ev => {
                            const time = ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString().substr(0, 5) : '';
                            return `<div class="panel-stat-row" style="font-size:0.5rem">
                                <span style="color:var(--text-dim)">${_esc(ev.event_type || 'entry')}</span>
                                <span style="color:var(--text-ghost)">${time}</span>
                            </div>`;
                        }).join('');
                        zoneDetailEl.innerHTML += `
                            <div class="panel-section-label">RECENT EVENTS</div>
                            ${eventHtml}
                        `;
                    }
                }
            } catch (_) {}
        }

        async function fetchZones() {
            try {
                const resp = await fetch('/api/zones');
                if (!resp.ok) {
                    zones = [];
                    renderZones();
                    return;
                }
                zones = await resp.json();
                if (!Array.isArray(zones)) zones = zones.zones || [];
                renderZones();
            } catch (_) {
                zones = [];
                renderZones();
            }
        }

        async function createZone() {
            try {
                const resp = await fetch('/api/zones', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: `Zone ${zones.length + 1}`,
                        zone_type: 'perimeter',
                        points: [],
                        enabled: true,
                    }),
                });
                if (resp.ok) {
                    fetchZones();
                    EventBus.emit('toast:show', { message: 'Zone created', type: 'info' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to create zone', type: 'alert' });
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchZones);
        if (createBtn) createBtn.addEventListener('click', createZone);

        // Auto-refresh every 30s
        const refreshInterval = setInterval(fetchZones, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        fetchZones();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
