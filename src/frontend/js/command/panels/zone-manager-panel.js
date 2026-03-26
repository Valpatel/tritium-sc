// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Zone Manager Panel — unified geofence zone management with CRUD, editing,
// activity timeline, and real-time occupancy monitoring.
// Uses /api/geofence/zones for CRUD and /api/geofence/events for activity.
// Emits geofence:drawZone to enter polygon drawing mode on the map.
// Emits zone:selected when a zone is clicked (for map highlighting).

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';


const TYPE_COLORS = {
    restricted: '#ff2a6d',
    monitored: '#00f0ff',
    safe: '#05ffa1',
};

const TYPE_LABELS = {
    restricted: 'RESTRICTED',
    monitored: 'MONITORED',
    safe: 'PUBLIC',
};

const VALID_TYPES = ['restricted', 'monitored', 'safe'];

export const ZoneManagerPanelDef = {
    id: 'zone-manager',
    title: 'ZONE MANAGER',
    defaultPosition: { x: 8, y: 120 },
    defaultSize: { w: 340, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'zone-manager-panel-inner';
        el.innerHTML = `
            <div class="zone-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="draw-zone">+ DRAW ZONE</button>
            </div>
            <div class="zone-mgr-tab-bar" style="display:flex;gap:2px;margin:4px 0">
                <button class="panel-action-btn panel-action-btn-primary zone-mgr-tab" data-tab="zones" style="flex:1;font-size:0.45rem">ZONES</button>
                <button class="panel-action-btn zone-mgr-tab" data-tab="activity" style="flex:1;font-size:0.45rem">ACTIVITY</button>
            </div>
            <div class="zone-mgr-summary" data-bind="summary" style="display:flex;gap:6px;margin:4px 0;font-size:0.45rem">
                <span class="zone-mgr-stat" style="color:#ff2a6d" data-bind="count-restricted">0 RESTRICTED</span>
                <span class="zone-mgr-stat" style="color:#00f0ff" data-bind="count-monitored">0 MONITORED</span>
                <span class="zone-mgr-stat" style="color:#05ffa1" data-bind="count-safe">0 PUBLIC</span>
            </div>
            <ul class="panel-list zone-list" data-bind="zone-list" role="listbox" aria-label="Geofence zones">
                <li class="panel-empty">Loading zones...</li>
            </ul>
            <div class="zone-mgr-activity" data-bind="activity-list" style="display:none">
                <div class="zone-mgr-activity-filter" style="margin:4px 0">
                    <select class="zone-mgr-filter-select" data-bind="event-type-filter" style="background:#1a1a2e;color:#00f0ff;border:1px solid #333;font-size:0.45rem;padding:2px 4px;font-family:inherit">
                        <option value="">ALL EVENTS</option>
                        <option value="enter">ENTER ONLY</option>
                        <option value="exit">EXIT ONLY</option>
                    </select>
                </div>
                <ul class="panel-list" data-bind="event-items" role="list" aria-label="Zone activity timeline">
                    <li class="panel-empty">Loading activity...</li>
                </ul>
            </div>
            <div class="zone-mgr-edit" data-bind="edit-form" style="display:none">
                <div class="panel-section-label">EDIT ZONE</div>
                <div class="zone-mgr-edit-fields">
                    <label class="zone-mgr-edit-label" style="font-size:0.42rem;color:var(--text-ghost)">NAME
                        <input class="zone-mgr-edit-input" data-bind="edit-name" type="text" style="width:100%;background:#1a1a2e;color:#00f0ff;border:1px solid #333;padding:3px 6px;font-family:inherit;font-size:0.48rem;margin:2px 0" />
                    </label>
                    <label class="zone-mgr-edit-label" style="font-size:0.42rem;color:var(--text-ghost)">TYPE
                        <select class="zone-mgr-edit-input" data-bind="edit-type" style="width:100%;background:#1a1a2e;color:#00f0ff;border:1px solid #333;padding:3px 6px;font-family:inherit;font-size:0.48rem;margin:2px 0">
                            <option value="restricted">RESTRICTED</option>
                            <option value="monitored">MONITORED</option>
                            <option value="safe">PUBLIC</option>
                        </select>
                    </label>
                    <div style="display:flex;gap:8px;margin:4px 0;font-size:0.42rem;color:var(--text-ghost)">
                        <label><input type="checkbox" data-bind="edit-enter" /> Alert on Enter</label>
                        <label><input type="checkbox" data-bind="edit-exit" /> Alert on Exit</label>
                    </div>
                    <div style="display:flex;gap:4px;margin:4px 0">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="save-edit" style="flex:1;font-size:0.45rem">SAVE</button>
                        <button class="panel-action-btn" data-action="cancel-edit" style="flex:1;font-size:0.45rem">CANCEL</button>
                    </div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const zoneListEl = bodyEl.querySelector('[data-bind="zone-list"]');
        const activityListEl = bodyEl.querySelector('[data-bind="activity-list"]');
        const eventItemsEl = bodyEl.querySelector('[data-bind="event-items"]');
        const editFormEl = bodyEl.querySelector('[data-bind="edit-form"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const drawBtn = bodyEl.querySelector('[data-action="draw-zone"]');
        const tabs = bodyEl.querySelectorAll('.zone-mgr-tab');
        const eventTypeFilter = bodyEl.querySelector('[data-bind="event-type-filter"]');

        // Summary counters
        const countRestricted = bodyEl.querySelector('[data-bind="count-restricted"]');
        const countMonitored = bodyEl.querySelector('[data-bind="count-monitored"]');
        const countSafe = bodyEl.querySelector('[data-bind="count-safe"]');

        // Edit form fields
        const editNameInput = bodyEl.querySelector('[data-bind="edit-name"]');
        const editTypeSelect = bodyEl.querySelector('[data-bind="edit-type"]');
        const editEnterCheck = bodyEl.querySelector('[data-bind="edit-enter"]');
        const editExitCheck = bodyEl.querySelector('[data-bind="edit-exit"]');
        const saveEditBtn = bodyEl.querySelector('[data-action="save-edit"]');
        const cancelEditBtn = bodyEl.querySelector('[data-action="cancel-edit"]');

        let zones = [];
        let events = [];
        let zoneOccupancy = {};
        let activeTab = 'zones';
        let editingZoneId = null;
        let eventFilterType = '';

        // --- Tab switching ---
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeTab = tab.dataset.tab;
                tabs.forEach(t => t.classList.toggle('panel-action-btn-primary', t.dataset.tab === activeTab));
                if (zoneListEl) zoneListEl.style.display = activeTab === 'zones' ? '' : 'none';
                if (activityListEl) activityListEl.style.display = activeTab === 'activity' ? '' : 'none';
                if (activeTab === 'activity') fetchEvents();
                // Hide edit form when switching tabs
                if (editFormEl) editFormEl.style.display = 'none';
                editingZoneId = null;
            });
        });

        // --- Event type filter ---
        if (eventTypeFilter) {
            eventTypeFilter.addEventListener('change', () => {
                eventFilterType = eventTypeFilter.value;
                fetchEvents();
            });
        }

        // --- Summary counters ---
        function updateSummary() {
            const counts = { restricted: 0, monitored: 0, safe: 0 };
            zones.forEach(z => {
                if (counts[z.zone_type] !== undefined) counts[z.zone_type]++;
            });
            if (countRestricted) countRestricted.textContent = `${counts.restricted} RESTRICTED`;
            if (countMonitored) countMonitored.textContent = `${counts.monitored} MONITORED`;
            if (countSafe) countSafe.textContent = `${counts.safe} PUBLIC`;
        }

        // --- Zone list rendering ---
        function renderZones() {
            if (!zoneListEl) return;
            if (zones.length === 0) {
                zoneListEl.innerHTML = '<li class="panel-empty">No geofence zones defined. Click DRAW ZONE to create one.</li>';
                updateSummary();
                return;
            }

            zoneListEl.innerHTML = zones.map(z => {
                const color = TYPE_COLORS[z.zone_type] || '#00f0ff';
                const typeLabel = TYPE_LABELS[z.zone_type] || z.zone_type.toUpperCase();
                const vertices = (z.polygon || []).length;
                const occupancy = zoneOccupancy[z.zone_id] || 0;
                const hasAlerts = z.alert_on_enter || z.alert_on_exit;
                const isTriggered = hasAlerts && occupancy > 0;

                const alertFlags = [];
                if (z.alert_on_enter) alertFlags.push('ENTER');
                if (z.alert_on_exit) alertFlags.push('EXIT');

                let statusBadge = '';
                if (isTriggered) {
                    statusBadge = `<span class="zone-mgr-badge zone-mgr-badge-alert">${occupancy} INSIDE</span>`;
                } else if (!z.enabled) {
                    statusBadge = `<span class="zone-mgr-badge zone-mgr-badge-disabled">DISABLED</span>`;
                } else if (hasAlerts) {
                    statusBadge = `<span class="zone-mgr-badge zone-mgr-badge-monitoring">ARMED</span>`;
                }

                const pulseClass = isTriggered ? ' zone-mgr-triggered' : '';
                const enabledClass = z.enabled ? '' : ' zone-mgr-disabled';

                return `<li class="panel-list-item zone-mgr-item${pulseClass}${enabledClass}" data-zone-id="${_esc(z.zone_id)}" role="option">
                    <span class="panel-dot${isTriggered ? ' zone-dot-pulse-alert' : ''}" style="background:${isTriggered ? '#ff2a6d' : color}"></span>
                    <span class="zone-mgr-item-info" style="flex:1;min-width:0">
                        <span class="zone-mgr-item-name">${_esc(z.name)}${statusBadge}</span>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)">${typeLabel} | ${vertices} pts | ${alertFlags.join('+') || 'no alerts'}</span>
                    </span>
                    <span class="zone-mgr-item-actions" style="display:flex;gap:2px;align-items:center">
                        <button class="panel-btn" data-action="edit-zone" data-zone-id="${_esc(z.zone_id)}" title="Edit zone" style="font-size:0.5rem;padding:1px 4px">&#9998;</button>
                        <button class="panel-btn zone-delete-btn" data-action="delete-zone" data-zone-id="${_esc(z.zone_id)}" title="Delete zone">&times;</button>
                    </span>
                </li>`;
            }).join('');

            updateSummary();

            // --- Click: select zone / highlight on map ---
            zoneListEl.querySelectorAll('.zone-mgr-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action="delete-zone"]') || e.target.closest('[data-action="edit-zone"]')) return;
                    const zid = item.dataset.zoneId;
                    const zone = zones.find(z => z.zone_id === zid);
                    if (zone) {
                        EventBus.emit('zone:selected', { id: zid, polygon: zone.polygon });
                        const pts = zone.polygon || [];
                        if (pts.length > 0) {
                            const cx = pts.reduce((s, p) => s + (p[0] || 0), 0) / pts.length;
                            const cy = pts.reduce((s, p) => s + (p[1] || 0), 0) / pts.length;
                            EventBus.emit('map:centerOnUnit', { id: null, x: cx, y: cy });
                        }
                    }
                });
            });

            // --- Edit button ---
            zoneListEl.querySelectorAll('[data-action="edit-zone"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const zid = btn.dataset.zoneId;
                    openEditForm(zid);
                });
            });

            // --- Delete button ---
            zoneListEl.querySelectorAll('[data-action="delete-zone"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const zid = btn.dataset.zoneId;
                    const zone = zones.find(z => z.zone_id === zid);
                    const name = zone ? zone.name : zid;
                    try {
                        const resp = await fetch(`/api/geofence/zones/${encodeURIComponent(zid)}`, { method: 'DELETE' });
                        if (resp.ok) {
                            EventBus.emit('toast:show', { message: `Zone "${name}" deleted`, type: 'info' });
                            if (editingZoneId === zid) {
                                editingZoneId = null;
                                if (editFormEl) editFormEl.style.display = 'none';
                            }
                            fetchZones();
                        } else {
                            EventBus.emit('toast:show', { message: 'Failed to delete zone', type: 'alert' });
                        }
                    } catch (_) {
                        EventBus.emit('toast:show', { message: 'Failed to delete zone', type: 'alert' });
                    }
                });
            });
        }

        // --- Edit form ---
        function openEditForm(zoneId) {
            const zone = zones.find(z => z.zone_id === zoneId);
            if (!zone || !editFormEl) return;

            editingZoneId = zoneId;
            editFormEl.style.display = '';

            if (editNameInput) editNameInput.value = zone.name;
            if (editTypeSelect) editTypeSelect.value = zone.zone_type;
            if (editEnterCheck) editEnterCheck.checked = zone.alert_on_enter;
            if (editExitCheck) editExitCheck.checked = zone.alert_on_exit;
        }

        async function saveEdit() {
            if (!editingZoneId) return;

            const updates = {};
            if (editNameInput) updates.name = editNameInput.value.trim() || 'Unnamed Zone';
            if (editTypeSelect && VALID_TYPES.includes(editTypeSelect.value)) updates.zone_type = editTypeSelect.value;
            if (editEnterCheck) updates.alert_on_enter = editEnterCheck.checked;
            if (editExitCheck) updates.alert_on_exit = editExitCheck.checked;

            try {
                const resp = await fetch(`/api/geofence/zones/${encodeURIComponent(editingZoneId)}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updates),
                });
                if (resp.ok) {
                    EventBus.emit('toast:show', { message: `Zone "${updates.name}" updated`, type: 'info' });
                    editingZoneId = null;
                    if (editFormEl) editFormEl.style.display = 'none';
                    fetchZones();
                } else {
                    EventBus.emit('toast:show', { message: 'Failed to update zone', type: 'alert' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to update zone', type: 'alert' });
            }
        }

        function cancelEdit() {
            editingZoneId = null;
            if (editFormEl) editFormEl.style.display = 'none';
        }

        if (saveEditBtn) saveEditBtn.addEventListener('click', saveEdit);
        if (cancelEditBtn) cancelEditBtn.addEventListener('click', cancelEdit);

        // --- Activity timeline rendering ---
        function renderEvents() {
            if (!eventItemsEl) return;
            if (events.length === 0) {
                eventItemsEl.innerHTML = '<li class="panel-empty">No zone activity recorded</li>';
                return;
            }

            eventItemsEl.innerHTML = events.slice(0, 100).map(ev => {
                const ts = ev.timestamp;
                let timeStr = '';
                if (typeof ts === 'number') {
                    timeStr = new Date(ts * 1000).toLocaleTimeString().substring(0, 8);
                } else if (typeof ts === 'string') {
                    timeStr = new Date(ts).toLocaleTimeString().substring(0, 8);
                }

                const isEnter = ev.event_type === 'enter';
                const color = isEnter ? '#ff2a6d' : '#05ffa1';
                const arrow = isEnter ? '\u25B6' : '\u25C0';
                const typeLabel = (ev.event_type || '').toUpperCase();
                const zoneName = ev.zone_name || ev.zone_id || '';
                const zoneType = ev.zone_type || '';
                const zoneColor = TYPE_COLORS[zoneType] || '#00f0ff';
                const targetId = ev.target_id || '';
                const targetShort = targetId.length > 12 ? targetId.substring(0, 12) + '\u2026' : targetId;

                return `<li class="panel-list-item zone-mgr-event-item" style="font-size:0.46rem" data-zone-id="${_esc(ev.zone_id)}">
                    <span style="color:${color};font-weight:bold;width:14px;text-align:center">${arrow}</span>
                    <span style="flex:1;min-width:0">
                        <span style="color:var(--text-main)">${_esc(targetShort)}</span>
                        <span style="color:${color};font-weight:bold"> ${_esc(typeLabel)} </span>
                        <span style="color:${zoneColor}">${_esc(zoneName)}</span>
                    </span>
                    <span class="mono" style="color:var(--text-ghost);font-size:0.42rem;white-space:nowrap">${_esc(timeStr)}</span>
                </li>`;
            }).join('');

            // Click event row to select that zone on the map
            eventItemsEl.querySelectorAll('.zone-mgr-event-item').forEach(item => {
                item.addEventListener('click', () => {
                    const zid = item.dataset.zoneId;
                    const zone = zones.find(z => z.zone_id === zid);
                    if (zone) {
                        EventBus.emit('zone:selected', { id: zid, polygon: zone.polygon });
                    }
                });
            });
        }

        // --- Fetch data ---
        async function fetchOccupancy() {
            try {
                const resp = await fetch('/api/geofence/occupancy');
                if (resp.ok) {
                    const data = await resp.json();
                    if (data && typeof data === 'object') {
                        zoneOccupancy = data;
                    }
                }
            } catch (_) {
                // Occupancy endpoint may not exist; ignore gracefully
            }
        }

        async function fetchZones() {
            try {
                const resp = await fetch('/api/geofence/zones');
                if (!resp.ok) { zones = []; renderZones(); return; }
                zones = await resp.json();
                if (!Array.isArray(zones)) zones = [];
                await fetchOccupancy();
                renderZones();
            } catch (_) {
                zones = [];
                renderZones();
            }
        }

        async function fetchEvents() {
            try {
                let url = '/api/geofence/events?limit=100';
                if (eventFilterType) url += `&event_type=${encodeURIComponent(eventFilterType)}`;
                const resp = await fetch(url);
                if (!resp.ok) { events = []; renderEvents(); return; }
                events = await resp.json();
                if (!Array.isArray(events)) events = [];
                renderEvents();
            } catch (_) {
                events = [];
                renderEvents();
            }
        }

        // --- Draw zone ---
        let drawingActive = false;

        function enterDrawMode() {
            drawingActive = true;
            if (panel.minimize) panel.minimize();
            if (drawBtn) {
                drawBtn.textContent = 'DRAWING...';
                drawBtn.classList.add('panel-action-btn-primary');
            }
        }

        function exitDrawMode() {
            if (!drawingActive) return;
            drawingActive = false;
            if (panel.restore) panel.restore();
            if (drawBtn) {
                drawBtn.textContent = '+ DRAW ZONE';
                drawBtn.classList.remove('panel-action-btn-primary');
            }
        }

        function drawZone() {
            enterDrawMode();
            EventBus.emit('geofence:drawZone', {});
            EventBus.emit('toast:show', { message: 'Click to place vertices, double-click or Enter to finish, Escape to cancel', type: 'info' });
        }

        // Restore panel when geofence drawing ends
        const onDrawEnd = () => exitDrawMode();
        EventBus.on('geofence:drawEnd', onDrawEnd);
        panel._unsubs.push(() => EventBus.off('geofence:drawEnd', onDrawEnd));

        // Listen for completed polygon from map
        const onZoneDrawn = async (data) => {
            if (!data || !data.polygon || data.polygon.length < 3) return;
            try {
                const resp = await fetch('/api/geofence/zones', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: data.name || `Zone ${zones.length + 1}`,
                        polygon: data.polygon,
                        zone_type: data.zone_type || 'monitored',
                        alert_on_enter: true,
                        alert_on_exit: true,
                    }),
                });
                if (resp.ok) {
                    fetchZones();
                    EventBus.emit('toast:show', { message: `Zone "${data.name || 'Zone'}" created`, type: 'info' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to create zone', type: 'alert' });
            }
        };
        EventBus.on('geofence:zoneDrawn', onZoneDrawn);
        panel._unsubs.push(() => EventBus.off('geofence:zoneDrawn', onZoneDrawn));

        // --- Live occupancy updates via WebSocket ---
        const onGeofenceEnter = (data) => {
            const zid = data.zone_id;
            if (zid) {
                zoneOccupancy[zid] = (zoneOccupancy[zid] || 0) + 1;
                renderZones();
            }
        };
        const onGeofenceExit = (data) => {
            const zid = data.zone_id;
            if (zid) {
                zoneOccupancy[zid] = Math.max(0, (zoneOccupancy[zid] || 0) - 1);
                renderZones();
            }
        };
        EventBus.on('geofence:enter', onGeofenceEnter);
        EventBus.on('geofence:exit', onGeofenceExit);
        panel._unsubs.push(() => EventBus.off('geofence:enter', onGeofenceEnter));
        panel._unsubs.push(() => EventBus.off('geofence:exit', onGeofenceExit));

        // --- Toolbar ---
        if (refreshBtn) refreshBtn.addEventListener('click', () => {
            fetchZones();
            if (activeTab === 'activity') fetchEvents();
        });
        if (drawBtn) drawBtn.addEventListener('click', drawZone);

        // --- Auto-refresh every 30s ---
        const refreshInterval = setInterval(() => {
            fetchZones();
            if (activeTab === 'activity') fetchEvents();
        }, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // --- Initial load ---
        fetchZones();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
