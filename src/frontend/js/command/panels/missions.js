// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Missions Panel — create, edit, and manage coordinated operations.
// CRUD via /api/missions. Supports objective tracking, asset assignment,
// geofence zone definition, and lifecycle management (start/pause/complete/abort).

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const STATUS_COLORS = {
    draft: '#888',
    planned: '#00f0ff',
    active: '#05ffa1',
    paused: '#fcee0a',
    completed: '#05ffa1',
    aborted: '#ff2a6d',
    failed: '#ff2a6d',
};

const TYPE_LABELS = {
    patrol: 'PATROL',
    surveillance: 'SURVEILLANCE',
    investigation: 'INVESTIGATION',
    response: 'RESPONSE',
    escort: 'ESCORT',
    search: 'SEARCH',
    perimeter: 'PERIMETER',
    custom: 'CUSTOM',
};

export const MissionsPanelDef = {
    id: 'missions',
    title: 'MISSIONS',
    defaultPosition: { x: 8, y: 80 },
    defaultSize: { w: 340, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'missions-panel-inner';
        el.innerHTML = `
            <div class="zone-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="create">+ NEW MISSION</button>
            </div>
            <div class="missions-tab-bar" style="display:flex;gap:2px;margin:4px 0">
                <button class="panel-action-btn panel-action-btn-primary missions-tab" data-tab="list" style="flex:1;font-size:0.45rem">MISSIONS</button>
                <button class="panel-action-btn missions-tab" data-tab="form" style="flex:1;font-size:0.45rem">CREATE/EDIT</button>
            </div>
            <div class="missions-list-view" data-view="list">
                <ul class="panel-list mission-list" data-bind="mission-list" role="listbox" aria-label="Missions">
                    <li class="panel-empty">Loading missions...</li>
                </ul>
            </div>
            <div class="missions-form-view" data-view="form" style="display:none">
                <div class="mission-form" style="padding:4px">
                    <input type="hidden" data-field="mission-id" value="">
                    <label class="form-label mono">TITLE</label>
                    <input type="text" data-field="title" class="panel-input" placeholder="Mission name" style="width:100%;margin-bottom:4px">
                    <label class="form-label mono">TYPE</label>
                    <select data-field="type" class="panel-input" style="width:100%;margin-bottom:4px">
                        <option value="custom">Custom</option>
                        <option value="patrol">Patrol</option>
                        <option value="surveillance">Surveillance</option>
                        <option value="investigation">Investigation</option>
                        <option value="response">Response</option>
                        <option value="escort">Escort</option>
                        <option value="search">Search</option>
                        <option value="perimeter">Perimeter</option>
                    </select>
                    <label class="form-label mono">DESCRIPTION</label>
                    <textarea data-field="description" class="panel-input" rows="2" style="width:100%;margin-bottom:4px;resize:vertical"></textarea>
                    <label class="form-label mono">PRIORITY (1=highest)</label>
                    <input type="number" data-field="priority" class="panel-input" value="3" min="1" max="5" style="width:60px;margin-bottom:4px">
                    <label class="form-label mono">ASSETS (comma-separated IDs)</label>
                    <input type="text" data-field="assets" class="panel-input" placeholder="unit_1, drone_2" style="width:100%;margin-bottom:4px">
                    <label class="form-label mono">OBJECTIVES (one per line)</label>
                    <textarea data-field="objectives" class="panel-input" rows="3" placeholder="Patrol north perimeter\nCheck gate status\nReport findings" style="width:100%;margin-bottom:4px;resize:vertical"></textarea>
                    <label class="form-label mono">TAGS (comma-separated)</label>
                    <input type="text" data-field="tags" class="panel-input" placeholder="urgent, night-ops" style="width:100%;margin-bottom:8px">
                    <div style="display:flex;gap:4px">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="save" style="flex:1">SAVE</button>
                        <button class="panel-action-btn" data-action="cancel-form" style="flex:1">CANCEL</button>
                    </div>
                </div>
            </div>
            <div class="missions-detail-view" data-view="detail" style="display:none">
                <div class="mission-detail" data-bind="detail" style="padding:4px"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="mission-list"]');
        const listView = bodyEl.querySelector('[data-view="list"]');
        const formView = bodyEl.querySelector('[data-view="form"]');
        const detailView = bodyEl.querySelector('[data-view="detail"]');
        const detailEl = bodyEl.querySelector('[data-bind="detail"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const createBtn = bodyEl.querySelector('[data-action="create"]');
        const saveBtn = bodyEl.querySelector('[data-action="save"]');
        const cancelBtn = bodyEl.querySelector('[data-action="cancel-form"]');
        const tabs = bodyEl.querySelectorAll('.missions-tab');

        let _missions = [];
        let _editingId = null;

        function showView(name) {
            listView.style.display = name === 'list' ? '' : 'none';
            formView.style.display = name === 'form' ? '' : 'none';
            detailView.style.display = name === 'detail' ? '' : 'none';
            tabs.forEach(t => {
                t.classList.toggle('panel-action-btn-primary',
                    (name === 'list' && t.dataset.tab === 'list') ||
                    (name === 'form' && t.dataset.tab === 'form'));
            });
        }

        async function loadMissions() {
            try {
                const resp = await fetch('/api/missions');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                _missions = await resp.json();
                renderList();
            } catch (e) {
                listEl.innerHTML = '<li class="panel-empty">Failed to load missions</li>';
            }
        }

        function renderList() {
            if (_missions.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No missions</li>';
                return;
            }
            listEl.innerHTML = _missions.map(m => {
                const color = STATUS_COLORS[m.status] || '#888';
                const typeLabel = TYPE_LABELS[m.type] || m.type.toUpperCase();
                const pct = Math.round((m.progress || 0) * 100);
                return `
                    <li class="panel-list-item" data-id="${_esc(m.mission_id)}" role="option" style="cursor:pointer">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <span class="mono" style="color:${color};font-size:0.5rem">[${_esc(m.status.toUpperCase())}]</span>
                            <span class="mono" style="font-size:0.4rem;opacity:0.6">${_esc(typeLabel)}</span>
                        </div>
                        <div class="mono" style="font-size:0.55rem;margin:2px 0">${_esc(m.title)}</div>
                        <div style="display:flex;justify-content:space-between;font-size:0.4rem;opacity:0.7">
                            <span>${m.objectives?.length || 0} objectives</span>
                            <span>${m.assigned_assets?.length || 0} assets</span>
                            <span>${pct}% done</span>
                        </div>
                    </li>
                `;
            }).join('');
        }

        function showDetail(mission) {
            const color = STATUS_COLORS[mission.status] || '#888';
            const pct = Math.round((mission.progress || 0) * 100);
            let objHtml = '';
            if (mission.objectives && mission.objectives.length > 0) {
                objHtml = mission.objectives.map(o => {
                    const check = o.completed ? '[x]' : '[ ]';
                    const style = o.completed ? 'opacity:0.5;text-decoration:line-through' : '';
                    return `<div class="mono" style="font-size:0.45rem;margin:2px 0;${style}">
                        <span style="cursor:pointer" data-complete-obj="${_esc(o.objective_id)}">${check}</span>
                        ${_esc(o.description)}
                    </div>`;
                }).join('');
            } else {
                objHtml = '<div class="mono" style="font-size:0.4rem;opacity:0.5">No objectives</div>';
            }

            const assetList = (mission.assigned_assets || []).map(a =>
                `<span class="mono" style="font-size:0.4rem;background:#1a1a2e;padding:1px 4px;border-radius:2px">${_esc(a)}</span>`
            ).join(' ');

            const tagList = (mission.tags || []).map(t =>
                `<span class="mono" style="font-size:0.35rem;background:#0e0e14;padding:1px 3px;border-radius:2px;border:1px solid #333">${_esc(t)}</span>`
            ).join(' ');

            detailEl.innerHTML = `
                <div style="margin-bottom:6px">
                    <div class="mono" style="font-size:0.6rem;margin-bottom:2px">${_esc(mission.title)}</div>
                    <div style="display:flex;gap:6px;align-items:center">
                        <span class="mono" style="color:${color};font-size:0.5rem">${_esc(mission.status.toUpperCase())}</span>
                        <span class="mono" style="font-size:0.4rem;opacity:0.6">${_esc((TYPE_LABELS[mission.type] || mission.type).toUpperCase())}</span>
                        <span class="mono" style="font-size:0.4rem;opacity:0.6">P${mission.priority}</span>
                    </div>
                </div>
                ${mission.description ? `<div class="mono" style="font-size:0.45rem;margin-bottom:6px;opacity:0.8">${_esc(mission.description)}</div>` : ''}
                <div class="mono" style="font-size:0.45rem;margin-bottom:2px">PROGRESS: ${pct}%</div>
                <div style="height:4px;background:#1a1a2e;border-radius:2px;margin-bottom:6px">
                    <div style="height:100%;width:${pct}%;background:#05ffa1;border-radius:2px;transition:width 0.3s"></div>
                </div>
                <div class="mono" style="font-size:0.45rem;margin-bottom:2px">OBJECTIVES</div>
                ${objHtml}
                ${assetList ? `<div style="margin-top:6px"><div class="mono" style="font-size:0.45rem;margin-bottom:2px">ASSIGNED ASSETS</div>${assetList}</div>` : ''}
                ${tagList ? `<div style="margin-top:4px">${tagList}</div>` : ''}
                <div class="mission-targets-section" data-bind="mission-targets" style="margin-top:6px">
                    <div class="mono" style="font-size:0.45rem;margin-bottom:2px;color:#00f0ff">TARGETS IN ZONE</div>
                    <div class="mission-targets-list" style="font-size:0.4rem;opacity:0.7">Loading...</div>
                </div>
                <div style="display:flex;gap:4px;margin-top:8px;flex-wrap:wrap">
                    ${!['completed','aborted','failed'].includes(mission.status) ? `
                        ${mission.status !== 'active' ? `<button class="panel-action-btn panel-action-btn-primary" data-lifecycle="start" style="font-size:0.4rem">START</button>` : ''}
                        ${mission.status === 'active' ? `<button class="panel-action-btn" data-lifecycle="pause" style="font-size:0.4rem">PAUSE</button>` : ''}
                        ${['active','paused'].includes(mission.status) ? `<button class="panel-action-btn" data-lifecycle="complete" style="font-size:0.4rem">COMPLETE</button>` : ''}
                        <button class="panel-action-btn" data-lifecycle="abort" style="font-size:0.4rem;color:#ff2a6d">ABORT</button>
                    ` : ''}
                    <button class="panel-action-btn" data-lifecycle="edit" style="font-size:0.4rem">EDIT</button>
                    <button class="panel-action-btn" data-lifecycle="delete" style="font-size:0.4rem;color:#ff2a6d">DELETE</button>
                    <button class="panel-action-btn" data-lifecycle="back" style="font-size:0.4rem">BACK</button>
                </div>
            `;
            showView('detail');

            // Load mission-bound targets
            loadMissionTargets(mission.mission_id);
        }

        async function loadMissionTargets(missionId) {
            const section = detailEl.querySelector('.mission-targets-list');
            if (!section) return;
            try {
                const resp = await fetch(`/api/missions/${missionId}/targets`);
                if (!resp.ok) { section.textContent = 'N/A'; return; }
                const data = await resp.json();
                const targets = data.targets || [];
                if (targets.length === 0) {
                    section.innerHTML = '<span style="opacity:0.5">No targets in zone</span>';
                } else {
                    section.innerHTML = targets.map(t =>
                        `<span class="mono" style="font-size:0.4rem;background:#0e0e14;padding:1px 4px;border-radius:2px;border:1px solid #00f0ff33;margin:1px">${_esc(t)}</span>`
                    ).join(' ');
                }
            } catch {
                section.textContent = 'Error loading targets';
            }
        }

        function resetForm() {
            _editingId = null;
            bodyEl.querySelector('[data-field="mission-id"]').value = '';
            bodyEl.querySelector('[data-field="title"]').value = '';
            bodyEl.querySelector('[data-field="type"]').value = 'custom';
            bodyEl.querySelector('[data-field="description"]').value = '';
            bodyEl.querySelector('[data-field="priority"]').value = '3';
            bodyEl.querySelector('[data-field="assets"]').value = '';
            bodyEl.querySelector('[data-field="objectives"]').value = '';
            bodyEl.querySelector('[data-field="tags"]').value = '';
        }

        function populateForm(m) {
            _editingId = m.mission_id;
            bodyEl.querySelector('[data-field="mission-id"]').value = m.mission_id;
            bodyEl.querySelector('[data-field="title"]').value = m.title || '';
            bodyEl.querySelector('[data-field="type"]').value = m.type || 'custom';
            bodyEl.querySelector('[data-field="description"]').value = m.description || '';
            bodyEl.querySelector('[data-field="priority"]').value = m.priority || 3;
            bodyEl.querySelector('[data-field="assets"]').value = (m.assigned_assets || []).join(', ');
            bodyEl.querySelector('[data-field="objectives"]').value =
                (m.objectives || []).map(o => o.description).join('\n');
            bodyEl.querySelector('[data-field="tags"]').value = (m.tags || []).join(', ');
        }

        async function saveMission() {
            const title = bodyEl.querySelector('[data-field="title"]').value.trim();
            if (!title) {
                EventBus.emit('toast:show', { message: 'Mission title required', type: 'alert' });
                return;
            }

            const payload = {
                title,
                type: bodyEl.querySelector('[data-field="type"]').value,
                description: bodyEl.querySelector('[data-field="description"]').value,
                priority: parseInt(bodyEl.querySelector('[data-field="priority"]').value) || 3,
                assigned_assets: bodyEl.querySelector('[data-field="assets"]').value
                    .split(',').map(s => s.trim()).filter(Boolean),
                objectives: bodyEl.querySelector('[data-field="objectives"]').value
                    .split('\n').filter(s => s.trim()).map(s => ({ description: s.trim(), priority: 1 })),
                tags: bodyEl.querySelector('[data-field="tags"]').value
                    .split(',').map(s => s.trim()).filter(Boolean),
            };

            try {
                let resp;
                if (_editingId) {
                    resp = await fetch(`/api/missions/${_editingId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                } else {
                    resp = await fetch('/api/missions', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                }
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${resp.status}`);
                }
                EventBus.emit('toast:show', {
                    message: _editingId ? 'Mission updated' : 'Mission created',
                    type: 'info',
                });
                resetForm();
                showView('list');
                loadMissions();
            } catch (e) {
                EventBus.emit('toast:show', { message: `Save failed: ${e.message}`, type: 'alert' });
            }
        }

        async function lifecycleAction(missionId, action) {
            try {
                const opts = { method: 'POST' };
                if (action === 'delete') {
                    opts.method = 'DELETE';
                }
                let url = `/api/missions/${missionId}`;
                if (action !== 'delete') {
                    url += `/${action}`;
                }
                if (action === 'abort') {
                    opts.headers = { 'Content-Type': 'application/json' };
                    opts.body = JSON.stringify({ reason: 'Operator abort' });
                }
                const resp = await fetch(url, opts);
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.detail || `HTTP ${resp.status}`);
                }
                EventBus.emit('toast:show', { message: `Mission ${action}`, type: 'info' });
                if (action === 'delete') {
                    showView('list');
                    loadMissions();
                } else {
                    const data = await resp.json();
                    showDetail(data);
                    loadMissions();
                }
            } catch (e) {
                EventBus.emit('toast:show', { message: `${action} failed: ${e.message}`, type: 'alert' });
            }
        }

        // Event handlers
        refreshBtn.addEventListener('click', loadMissions);
        createBtn.addEventListener('click', () => { resetForm(); showView('form'); });
        saveBtn.addEventListener('click', saveMission);
        cancelBtn.addEventListener('click', () => { resetForm(); showView('list'); });

        tabs.forEach(t => t.addEventListener('click', () => {
            showView(t.dataset.tab);
        }));

        listEl.addEventListener('click', (e) => {
            const item = e.target.closest('[data-id]');
            if (!item) return;
            const m = _missions.find(m => m.mission_id === item.dataset.id);
            if (m) showDetail(m);
        });

        detailEl.addEventListener('click', async (e) => {
            // Lifecycle buttons
            const lcBtn = e.target.closest('[data-lifecycle]');
            if (lcBtn) {
                const action = lcBtn.dataset.lifecycle;
                const mId = bodyEl.querySelector('[data-field="mission-id"]')?.value ||
                    detailEl.closest('[data-view="detail"]')?.querySelector('[data-lifecycle="back"]')?.dataset?.missionId;
                // Get current mission from the rendered detail
                const titleEl = detailEl.querySelector('.mono');
                const currentMission = _missions.find(m => m.title === titleEl?.textContent);
                if (!currentMission) { showView('list'); return; }

                if (action === 'back') {
                    showView('list');
                } else if (action === 'edit') {
                    populateForm(currentMission);
                    showView('form');
                } else {
                    await lifecycleAction(currentMission.mission_id, action);
                }
                return;
            }

            // Complete objective
            const objBtn = e.target.closest('[data-complete-obj]');
            if (objBtn) {
                const objId = objBtn.dataset.completeObj;
                const titleEl = detailEl.querySelector('.mono');
                const currentMission = _missions.find(m => m.title === titleEl?.textContent);
                if (currentMission) {
                    try {
                        const resp = await fetch(
                            `/api/missions/${currentMission.mission_id}/objectives/${objId}/complete`,
                            { method: 'POST' }
                        );
                        if (resp.ok) {
                            const data = await resp.json();
                            showDetail(data);
                            loadMissions();
                        }
                    } catch { /* ignore */ }
                }
            }
        });

        // Initial load
        loadMissions();
    },
};
