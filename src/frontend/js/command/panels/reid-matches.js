// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// ReID Cross-Camera Tracking Panel — person re-identification visualization
// with timeline view, person grouping, confidence scores, and camera snapshots.
// Backend API: /api/reid (matches, stats, persons)

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CAM_COLORS = [
    '#00f0ff', '#ff2a6d', '#05ffa1', '#fcee0a',
    '#c084fc', '#fb923c', '#22d3ee', '#f472b6',
];

function camColor(camId, camList) {
    const idx = camList.indexOf(camId);
    return CAM_COLORS[idx >= 0 ? idx % CAM_COLORS.length : 0];
}

function simColor(sim) {
    if (sim >= 0.95) return '#05ffa1';
    if (sim >= 0.85) return '#00f0ff';
    if (sim >= 0.75) return '#fcee0a';
    return '#888';
}

function simLabel(sim) {
    if (sim >= 0.95) return 'CERTAIN';
    if (sim >= 0.85) return 'HIGH';
    if (sim >= 0.75) return 'LIKELY';
    return 'LOW';
}

function fmtTime(ts) {
    if (!ts) return '--:--:--';
    return new Date(ts * 1000).toLocaleTimeString();
}

function fmtDuration(seconds) {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${(seconds / 3600).toFixed(1)}h`;
}


// ---------------------------------------------------------------------------
// Panel definition
// ---------------------------------------------------------------------------

export const ReIDMatchesPanelDef = {
    id: 'reid-matches',
    title: 'REID TRACKING',
    defaultPosition: { x: 360, y: 80 },
    defaultSize: { w: 420, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'reid-panel-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;overflow:hidden';
        el.innerHTML = `
            <div class="reid-toolbar" style="display:flex;gap:4px;padding:4px;align-items:center;flex-shrink:0">
                <button class="panel-action-btn reid-tab-btn" data-tab="persons" style="font-size:0.38rem;padding:2px 6px;border-color:#00f0ff;color:#00f0ff">PERSONS</button>
                <button class="panel-action-btn reid-tab-btn" data-tab="matches" style="font-size:0.38rem;padding:2px 6px">MATCHES</button>
                <button class="panel-action-btn" data-action="refresh" title="Refresh" style="font-size:0.38rem;padding:2px 6px;margin-left:auto">REFRESH</button>
                <span data-bind="stats" style="font-size:0.38rem;color:#888"></span>
            </div>
            <div class="reid-filter" style="padding:2px 4px;flex-shrink:0">
                <select data-bind="camera-filter" style="background:#12121a;border:1px solid #333;color:#ccc;padding:3px;font-size:0.40rem;width:100%;border-radius:2px">
                    <option value="">All cameras</option>
                </select>
            </div>
            <div data-bind="persons-view" style="flex:1;overflow-y:auto;overflow-x:hidden;min-height:0"></div>
            <div data-bind="matches-view" style="flex:1;overflow-y:auto;overflow-x:hidden;min-height:0;display:none"></div>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let pollTimer = null;
        let currentTab = 'persons';
        let allCameras = [];

        const cameraFilter = el.querySelector('[data-bind="camera-filter"]');
        const personsView = el.querySelector('[data-bind="persons-view"]');
        const matchesView = el.querySelector('[data-bind="matches-view"]');
        const tabBtns = el.querySelectorAll('.reid-tab-btn');

        // Tab switching
        tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                currentTab = btn.dataset.tab;
                tabBtns.forEach(b => {
                    const active = b.dataset.tab === currentTab;
                    b.style.borderColor = active ? '#00f0ff' : '#555';
                    b.style.color = active ? '#00f0ff' : '#ccc';
                });
                personsView.style.display = currentTab === 'persons' ? '' : 'none';
                matchesView.style.display = currentTab === 'matches' ? '' : 'none';
                refresh();
            });
        });

        cameraFilter.addEventListener('change', refresh);
        el.querySelector('[data-action="refresh"]').addEventListener('click', refresh);

        async function refresh() {
            try {
                await Promise.all([
                    loadStats(),
                    currentTab === 'persons' ? loadPersons() : loadMatches(),
                ]);
            } catch (err) {
                console.warn('[reid] refresh error:', err);
            }
        }

        // ---------------------------------------------------------------
        // Stats
        // ---------------------------------------------------------------
        async function loadStats() {
            try {
                const res = await fetch('/api/reid/stats');
                if (!res.ok) return;
                const data = await res.json();
                const statsEl = el.querySelector('[data-bind="stats"]');
                if (statsEl) {
                    statsEl.textContent = `${data.total_entries || 0} emb | `
                        + `${data.total_matches || 0} match | `
                        + `${(data.cameras || []).length} cam`;
                }
                allCameras = data.cameras || [];
                const current = cameraFilter.value;
                const options = ['<option value="">All cameras</option>'];
                allCameras.forEach(cam => {
                    options.push(`<option value="${_esc(cam)}"${cam === current ? ' selected' : ''}>${_esc(cam)}</option>`);
                });
                cameraFilter.innerHTML = options.join('');
            } catch (_) { /* ignore */ }
        }

        // ---------------------------------------------------------------
        // Persons timeline view
        // ---------------------------------------------------------------
        async function loadPersons() {
            try {
                const res = await fetch('/api/reid/persons?max_persons=20');
                if (!res.ok) {
                    personsView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">API unavailable</div>';
                    return;
                }
                const persons = await res.json();
                const camFilter = cameraFilter.value;

                // Filter by camera if set
                const filtered = camFilter
                    ? persons.filter(p => p.cameras.includes(camFilter))
                    : persons;

                if (!filtered.length) {
                    personsView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">No tracked persons</div>';
                    return;
                }

                personsView.innerHTML = filtered.map(p => renderPersonCard(p)).join('');
                wirePersonCards(personsView);
            } catch (err) {
                personsView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">Error loading persons</div>';
            }
        }

        function renderPersonCard(person) {
            const crossBadge = person.cross_camera
                ? `<span style="background:#ff2a6d;color:#fff;padding:1px 4px;border-radius:2px;font-size:0.34rem;font-weight:bold">CROSS-CAM</span>`
                : '';
            const confColor = simColor(person.match_confidence);
            const confPct = Math.round(person.match_confidence * 100);
            const duration = person.last_seen - person.first_seen;

            // Camera legend
            const camLegend = person.cameras.map(cam => {
                const color = camColor(cam, allCameras);
                return `<span style="display:inline-flex;align-items:center;gap:2px;margin-right:6px">
                    <span style="width:8px;height:8px;border-radius:50%;background:${color};display:inline-block"></span>
                    <span style="color:${color};font-size:0.36rem">${_esc(cam)}</span>
                </span>`;
            }).join('');

            // Timeline bar: visualize sightings over time range
            const timelineHtml = renderTimeline(person);

            // Sighting list (most recent first)
            const sightings = [...person.sightings].reverse().slice(0, 8);
            const sightingRows = sightings.map(s => {
                const color = camColor(s.camera_id, allCameras);
                return `<div class="reid-sighting-row" style="display:flex;justify-content:space-between;align-items:center;padding:2px 0;cursor:pointer"
                            data-camera="${_esc(s.camera_id)}" data-target="${_esc(s.target_id)}" data-ts="${s.timestamp}">
                    <span style="display:flex;align-items:center;gap:4px">
                        <span style="width:6px;height:6px;border-radius:50%;background:${color};display:inline-block"></span>
                        <span style="color:#ccc;font-size:0.36rem">${_esc(s.camera_id)}</span>
                    </span>
                    <span style="color:#888;font-size:0.34rem">${fmtTime(s.timestamp)}</span>
                    <span style="color:#aaa;font-size:0.34rem">${Math.round(s.confidence * 100)}%</span>
                </div>`;
            }).join('');

            const moreCount = person.sighting_count - sightings.length;
            const moreLabel = moreCount > 0
                ? `<div style="text-align:center;font-size:0.32rem;color:#555;padding:2px">+${moreCount} more sightings</div>`
                : '';

            // Dossier link from any sighting
            const dossierId = person.sightings.find(s => s.dossier_id)?.dossier_id || '';
            const dossierBtn = dossierId
                ? `<button class="panel-action-btn reid-dossier-btn" data-dossier="${_esc(dossierId)}"
                    style="font-size:0.32rem;padding:1px 4px;color:#00f0ff;border-color:#00f0ff" title="View dossier">DOSSIER</button>`
                : '';

            return `<div class="reid-person-card" data-person="${_esc(person.person_id)}"
                         style="margin:4px;padding:6px;background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;
                                ${person.cross_camera ? 'border-left:3px solid #ff2a6d;' : 'border-left:3px solid #333;'}">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
                    <div style="display:flex;align-items:center;gap:6px">
                        <span style="color:#ccc;font-size:0.42rem;font-weight:bold">${_esc(person.class_name.toUpperCase())}</span>
                        ${crossBadge}
                    </div>
                    <div style="display:flex;align-items:center;gap:6px">
                        ${dossierBtn}
                        <span style="color:${confColor};font-size:0.38rem;font-weight:bold">${confPct > 0 ? confPct + '% ' + simLabel(person.match_confidence) : 'SINGLE CAM'}</span>
                    </div>
                </div>
                <div style="margin-bottom:4px">${camLegend}</div>
                <div style="display:flex;justify-content:space-between;font-size:0.34rem;color:#666;margin-bottom:2px">
                    <span>First: ${fmtTime(person.first_seen)}</span>
                    <span>Last: ${fmtTime(person.last_seen)}</span>
                    <span>Duration: ${fmtDuration(duration)}</span>
                </div>
                ${timelineHtml}
                <div style="margin-top:4px">${sightingRows}</div>
                ${moreLabel}
            </div>`;
        }

        function renderTimeline(person) {
            if (person.sightings.length < 2) {
                return '<div style="height:16px;background:#12121a;border-radius:2px;margin:2px 0;position:relative;overflow:hidden"><div style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);font-size:0.30rem;color:#555">single sighting</div></div>';
            }

            const tMin = person.first_seen;
            const tMax = person.last_seen;
            const range = tMax - tMin || 1;

            // Render dots on a timeline bar, colored by camera
            const dots = person.sightings.map(s => {
                const pct = ((s.timestamp - tMin) / range) * 100;
                const color = camColor(s.camera_id, allCameras);
                return `<div style="position:absolute;left:${pct}%;top:50%;transform:translate(-50%,-50%);
                                    width:6px;height:6px;border-radius:50%;background:${color};
                                    border:1px solid rgba(0,0,0,0.5)" title="${_esc(s.camera_id)} @ ${fmtTime(s.timestamp)}"></div>`;
            }).join('');

            return `<div style="height:16px;background:#12121a;border-radius:2px;margin:2px 0;position:relative;overflow:hidden">
                ${dots}
            </div>`;
        }

        function wirePersonCards(container) {
            // Wire sighting row clicks — open camera snapshot or inspect target
            container.querySelectorAll('.reid-sighting-row').forEach(row => {
                row.addEventListener('click', () => {
                    const targetId = row.dataset.target;
                    const cameraId = row.dataset.camera;
                    if (targetId) {
                        EventBus.emit('panel:request-open', { id: 'unit-inspector' });
                        EventBus.emit('target:inspect', { id: targetId });
                    }
                    // Also try to show camera feed
                    if (cameraId) {
                        EventBus.emit('camera:focus', { id: cameraId });
                    }
                });
            });

            // Wire dossier buttons
            container.querySelectorAll('.reid-dossier-btn').forEach(btn => {
                btn.addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    EventBus.emit('panel:request-open', { id: 'dossiers' });
                    EventBus.emit('dossier:view', { id: btn.dataset.dossier });
                });
            });
        }

        // ---------------------------------------------------------------
        // Matches view (original flat list)
        // ---------------------------------------------------------------
        async function loadMatches() {
            const camId = cameraFilter.value;
            let url = '/api/reid/matches?count=40';
            if (camId) url += `&camera_id=${encodeURIComponent(camId)}`;

            try {
                const res = await fetch(url);
                if (!res.ok) {
                    matchesView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">API unavailable</div>';
                    return;
                }
                const data = await res.json();
                if (!data.length) {
                    matchesView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">No cross-camera matches</div>';
                    return;
                }
                matchesView.innerHTML = data.map(m => {
                    const color = simColor(m.similarity);
                    const label = simLabel(m.similarity);
                    const simPct = Math.round(m.similarity * 100);
                    const tsA = fmtTime(m.timestamp_a);
                    const tsB = fmtTime(m.timestamp_b);
                    const barWidth = Math.round(m.similarity * 100);
                    const dossierLink = m.dossier_id
                        ? `<button class="panel-action-btn reid-dossier-btn" data-dossier="${_esc(m.dossier_id)}"
                            style="font-size:0.32rem;padding:1px 4px;color:#00f0ff;border-color:#00f0ff;float:right" title="View dossier">DOSSIER</button>`
                        : '';

                    return `<div class="reid-match-item" style="margin:4px;padding:6px;background:#0e0e14;border:1px solid #1a1a2e;
                                 border-left:3px solid ${color};border-radius:3px;cursor:pointer"
                                 data-target-a="${_esc(m.target_a)}" data-target-b="${_esc(m.target_b)}">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <span style="color:#ccc;font-size:0.40rem">${_esc(m.class_name.toUpperCase())}</span>
                            <span style="color:${color};font-weight:bold;font-size:0.40rem">${simPct}% ${label}</span>
                            ${dossierLink}
                        </div>
                        <div style="margin:2px 0;height:4px;background:#1a1a2e;border-radius:2px;overflow:hidden">
                            <div style="width:${barWidth}%;height:100%;background:${color};transition:width 0.3s"></div>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.36rem;color:#888">
                            <span><span style="color:${camColor(m.camera_a, allCameras)}">${_esc(m.camera_a || '?')}</span> ${_esc(m.target_a)}</span>
                            <span style="color:#555">${tsA}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.36rem;color:#888">
                            <span><span style="color:${camColor(m.camera_b, allCameras)}">${_esc(m.camera_b || '?')}</span> ${_esc(m.target_b)}</span>
                            <span style="color:#555">${tsB}</span>
                        </div>
                    </div>`;
                }).join('');

                // Wire interactions
                matchesView.querySelectorAll('.reid-dossier-btn').forEach(btn => {
                    btn.addEventListener('click', (ev) => {
                        ev.stopPropagation();
                        EventBus.emit('panel:request-open', { id: 'dossiers' });
                        EventBus.emit('dossier:view', { id: btn.dataset.dossier });
                    });
                });

                matchesView.querySelectorAll('.reid-match-item[data-target-a]').forEach(item => {
                    item.addEventListener('click', () => {
                        EventBus.emit('panel:request-open', { id: 'unit-inspector' });
                        EventBus.emit('target:inspect', { id: item.dataset.targetA });
                    });
                });
            } catch (err) {
                matchesView.innerHTML = '<div class="panel-empty" style="padding:12px;color:#888">Error loading matches</div>';
            }
        }

        // ---------------------------------------------------------------
        // Event listeners & polling
        // ---------------------------------------------------------------
        EventBus.on('reid:match', () => refresh());

        refresh();
        pollTimer = setInterval(refresh, 8000);

        panel._reidCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._reidCleanup) panel._reidCleanup();
    },
};
