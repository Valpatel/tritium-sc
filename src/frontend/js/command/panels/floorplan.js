// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Floor Plan Panel
// Upload, geo-reference, and manage indoor floor plans.
// SVG/PNG upload with bounds and room definition.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';

export const FloorPlanPanelDef = {
    id: 'floorplan',
    title: 'FLOOR PLANS',
    defaultPosition: { x: 8, y: 60 },
    defaultSize: { w: 340, h: 480 },

    render(container) {
        container.innerHTML = `
            <div class="floorplan-panel" style="display:flex;flex-direction:column;height:100%;font-family:'Courier New',monospace;">
                <div class="fp-toolbar" style="padding:6px 8px;border-bottom:1px solid #1a1a2e;display:flex;gap:6px;">
                    <button id="fp-upload-btn" style="background:#1a1a2e;color:#05ffa1;border:1px solid #05ffa133;padding:4px 10px;cursor:pointer;font-size:10px;font-family:inherit;">
                        + UPLOAD
                    </button>
                    <button id="fp-refresh-btn" style="background:#1a1a2e;color:#00f0ff;border:1px solid #00f0ff33;padding:4px 10px;cursor:pointer;font-size:10px;font-family:inherit;">
                        REFRESH
                    </button>
                    <input type="file" id="fp-file-input" accept=".png,.svg,.jpg,.jpeg" style="display:none;">
                </div>
                <div class="fp-list" id="fp-list" style="flex:1;overflow-y:auto;padding:4px 0;"></div>
                <div class="fp-detail" id="fp-detail" style="display:none;flex:1;overflow-y:auto;padding:8px;"></div>
            </div>
        `;

        const uploadBtn = container.querySelector('#fp-upload-btn');
        const refreshBtn = container.querySelector('#fp-refresh-btn');
        const fileInput = container.querySelector('#fp-file-input');
        const listEl = container.querySelector('#fp-list');
        const detailEl = container.querySelector('#fp-detail');

        let plans = [];
        let selectedPlan = null;

        async function loadPlans() {
            try {
                const resp = await fetch('/api/floorplans');
                if (!resp.ok) return;
                const data = await resp.json();
                plans = data.floorplans || [];
                renderList();
            } catch (err) {
                listEl.innerHTML = '<div style="padding:8px;color:#ff2a6d;font-size:11px;">Failed to load</div>';
            }
        }

        function renderList() {
            if (plans.length === 0) {
                listEl.innerHTML = `
                    <div style="padding:16px 8px;color:#555;font-size:11px;text-align:center;">
                        No floor plans uploaded.<br>
                        Click + UPLOAD to add one.
                    </div>
                `;
                return;
            }

            listEl.innerHTML = plans.map(p => {
                const statusColor = {
                    draft: '#fcee0a',
                    active: '#05ffa1',
                    archived: '#555',
                }[p.status] || '#888';

                return `
                    <div class="fp-item" data-id="${_esc(p.plan_id)}" style="
                        margin:2px 8px;padding:8px 10px;
                        background:#0e0e14;border:1px solid #1a1a2e;
                        cursor:pointer;font-size:11px;
                    ">
                        <div style="display:flex;justify-content:space-between;">
                            <span style="color:#00f0ff;">${_esc(p.name)}</span>
                            <span style="color:${statusColor};font-size:9px;text-transform:uppercase;">${_esc(p.status)}</span>
                        </div>
                        <div style="color:#555;font-size:10px;margin-top:2px;">
                            ${_esc(p.building || 'No building')} | Floor ${p.floor_level || 0} | ${(p.rooms || []).length} rooms
                        </div>
                    </div>
                `;
            }).join('');

            listEl.querySelectorAll('.fp-item').forEach(el => {
                el.addEventListener('click', () => {
                    const id = el.dataset.id;
                    showDetail(id);
                });
            });
        }

        async function showDetail(planId) {
            try {
                const resp = await fetch(`/api/floorplans/${encodeURIComponent(planId)}`);
                if (!resp.ok) return;
                const data = await resp.json();
                selectedPlan = data.floorplan;
                renderDetail();
                listEl.style.display = 'none';
                detailEl.style.display = 'block';
            } catch (err) {
                // ignore
            }
        }

        function renderDetail() {
            if (!selectedPlan) return;
            const p = selectedPlan;
            const rooms = p.rooms || [];
            const bounds = p.bounds || {};

            detailEl.innerHTML = `
                <div style="font-size:11px;">
                    <div style="display:flex;justify-content:space-between;margin-bottom:8px;">
                        <button id="fp-back-btn" style="background:none;color:#00f0ff;border:none;cursor:pointer;font-size:11px;font-family:inherit;">
                            &lt; BACK
                        </button>
                        <div style="display:flex;gap:6px;">
                            <button id="fp-activate-btn" style="background:#1a1a2e;color:#05ffa1;border:1px solid #05ffa133;padding:2px 8px;cursor:pointer;font-size:10px;font-family:inherit;">
                                ACTIVATE
                            </button>
                            <button id="fp-delete-btn" style="background:#1a1a2e;color:#ff2a6d;border:1px solid #ff2a6d33;padding:2px 8px;cursor:pointer;font-size:10px;font-family:inherit;">
                                DELETE
                            </button>
                        </div>
                    </div>
                    <div style="color:#00f0ff;font-size:13px;margin-bottom:4px;">${_esc(p.name)}</div>
                    <div style="color:#555;margin-bottom:8px;">
                        Building: ${_esc(p.building || 'N/A')} | Floor: ${p.floor_level} | Format: ${_esc(p.image_format)}
                    </div>
                    ${p.image_path ? `
                        <div style="margin-bottom:8px;border:1px solid #1a1a2e;overflow:hidden;max-height:150px;">
                            <img src="/api/floorplans/${encodeURIComponent(p.plan_id)}/image"
                                 style="width:100%;height:auto;display:block;opacity:0.8;"
                                 alt="Floor plan"
                                 onerror="this.style.display='none'">
                        </div>
                    ` : ''}
                    ${bounds.north !== undefined ? `
                        <div style="color:#888;font-size:10px;margin-bottom:6px;">
                            Bounds: N${bounds.north?.toFixed(6)} S${bounds.south?.toFixed(6)} E${bounds.east?.toFixed(6)} W${bounds.west?.toFixed(6)}
                        </div>
                    ` : '<div style="color:#fcee0a;font-size:10px;margin-bottom:6px;">Not geo-referenced</div>'}
                    <div style="color:#00f0ff;margin-top:8px;margin-bottom:4px;">ROOMS (${rooms.length})</div>
                    ${rooms.length === 0 ? '<div style="color:#555;font-size:10px;">No rooms defined</div>' :
                        rooms.map(r => `
                            <div style="margin:2px 0;padding:4px 6px;background:#12121a;border-left:2px solid ${_esc(r.color || '#00f0ff')};font-size:10px;">
                                <span style="color:#00f0ff;">${_esc(r.name)}</span>
                                <span style="color:#555;"> [${_esc(r.room_type || 'other')}]</span>
                                ${r.capacity ? `<span style="color:#888;"> cap:${r.capacity}</span>` : ''}
                                <span style="color:#333;"> (${(r.polygon || []).length} pts)</span>
                            </div>
                        `).join('')
                    }
                </div>
            `;

            detailEl.querySelector('#fp-back-btn').addEventListener('click', () => {
                selectedPlan = null;
                detailEl.style.display = 'none';
                listEl.style.display = 'block';
            });

            detailEl.querySelector('#fp-activate-btn').addEventListener('click', async () => {
                try {
                    await fetch(`/api/floorplans/${encodeURIComponent(p.plan_id)}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status: 'active' }),
                    });
                    loadPlans();
                    showDetail(p.plan_id);
                } catch (err) { /* ignore */ }
            });

            detailEl.querySelector('#fp-delete-btn').addEventListener('click', async () => {
                if (!confirm('Delete this floor plan?')) return;
                try {
                    await fetch(`/api/floorplans/${encodeURIComponent(p.plan_id)}`, {
                        method: 'DELETE',
                    });
                    selectedPlan = null;
                    detailEl.style.display = 'none';
                    listEl.style.display = 'block';
                    loadPlans();
                } catch (err) { /* ignore */ }
            });
        }

        // Upload
        uploadBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', async () => {
            const file = fileInput.files[0];
            if (!file) return;

            const form = new FormData();
            form.append('file', file);
            form.append('name', file.name.replace(/\.[^.]+$/, ''));

            try {
                const resp = await fetch('/api/floorplans/upload', {
                    method: 'POST',
                    body: form,
                });
                if (resp.ok) {
                    loadPlans();
                }
            } catch (err) {
                // ignore
            }
            fileInput.value = '';
        });

        refreshBtn.addEventListener('click', loadPlans);

        // Initial load
        loadPlans();
    }
};
