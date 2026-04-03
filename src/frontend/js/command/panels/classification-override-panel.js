// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Classification Override Panel
// Lets operators manually override target classifications (alliance and device type).
// Uses POST /api/targets/{id}/classify and GET /api/targets/{id}/classification.
// Listens for target:focus events to auto-populate the target ID.
// Logs all overrides with operator name and reason for audit trail.
// UX Loop 6 (Investigate Target) — step 7: tag/reclassify targets.

import { _esc } from '/lib/utils.js';
import { EventBus } from '/lib/events.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#888';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

const ALLIANCES = [
    { value: 'friendly', label: 'FRIENDLY', color: GREEN },
    { value: 'hostile', label: 'HOSTILE', color: MAGENTA },
    { value: 'neutral', label: 'NEUTRAL', color: YELLOW },
    { value: 'unknown', label: 'UNKNOWN', color: CYAN },
];

const DEVICE_TYPES = [
    'person', 'vehicle', 'phone', 'watch', 'computer', 'animal',
    'mesh_radio', 'ble_device', 'drone', 'sensor', 'unknown',
];

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchClassification(targetId) {
    try {
        const r = await fetch(`/api/targets/${encodeURIComponent(targetId)}/classification`);
        if (!r.ok) return null;
        return await r.json();
    } catch {
        return null;
    }
}

async function _submitOverride(targetId, alliance, deviceType, reason, operator) {
    const body = {
        target_id: targetId,
        reason: reason || '',
        operator: operator || 'operator',
    };
    if (alliance) body.alliance = alliance;
    if (deviceType) body.device_type = deviceType;

    const r = await fetch(`/api/targets/${encodeURIComponent(targetId)}/classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: `HTTP ${r.status}` }));
        throw new Error(err.detail || `HTTP ${r.status}`);
    }
    return await r.json();
}

async function _fetchTargets() {
    try {
        const r = await fetch('/api/targets?limit=50');
        if (!r.ok) return [];
        const data = await r.json();
        return Array.isArray(data) ? data : (data.targets || []);
    } catch {
        return [];
    }
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------

function _allianceBadge(alliance) {
    const info = ALLIANCES.find(a => a.value === alliance) || { label: (alliance || 'UNKNOWN').toUpperCase(), color: DIM };
    return `<span style="background:${info.color};color:#0a0a0f;font-size:0.42rem;padding:1px 8px;border-radius:3px;font-weight:bold">${info.label}</span>`;
}

function _allianceButtons(selected) {
    return ALLIANCES.map(a => {
        const isSelected = selected === a.value;
        const bg = isSelected ? a.color : 'transparent';
        const fg = isSelected ? '#0a0a0f' : a.color;
        const border = a.color;
        return `<button class="co-alliance-btn" data-alliance="${a.value}" style="flex:1;padding:4px 2px;font-size:0.42rem;font-weight:bold;background:${bg};color:${fg};border:1px solid ${border};border-radius:3px;cursor:pointer;transition:all 0.15s;letter-spacing:0.5px">${a.label}</button>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------

function _renderPanel(bodyEl, state) {
    const content = bodyEl.querySelector('[data-bind="override-content"]');
    if (!content) return;

    let html = '';

    // Target ID input with datalist
    html += `<div style="padding:8px 10px;border-bottom:1px solid ${BORDER}">
        <label style="font-size:0.38rem;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:3px">Target ID</label>
        <div style="display:flex;gap:4px">
            <input type="text" data-bind="target-id" list="co-target-list" placeholder="Enter or select target ID..." value="${_esc(state.targetId || '')}"
                style="flex:1;background:${SURFACE};border:1px solid ${BORDER};color:${CYAN};padding:4px 8px;font-size:0.42rem;font-family:var(--font-mono);border-radius:2px;outline:none" />
            <button class="panel-action-btn" data-action="load" style="font-size:0.38rem;padding:4px 8px">LOAD</button>
        </div>
        <datalist id="co-target-list">
            ${(state.targetOptions || []).map(t => `<option value="${_esc(t)}">`).join('')}
        </datalist>
    </div>`;

    // Current classification (if loaded)
    if (state.current) {
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.38rem;color:${DIM};text-transform:uppercase;margin-bottom:4px">Current Classification</div>
            <div style="display:flex;gap:8px;align-items:center">
                ${_allianceBadge(state.current.alliance)}
                <span class="mono" style="font-size:0.42rem;color:#ccc">${_esc((state.current.device_type || 'unknown').toUpperCase())}</span>
                <span class="mono" style="font-size:0.38rem;color:${DIM}">src: ${_esc(state.current.source || '?')}</span>
            </div>
        </div>`;
    }

    // Override form
    html += `<div style="padding:8px 10px;border-bottom:1px solid ${BORDER}">
        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px">Set Alliance</div>
        <div style="display:flex;gap:4px;margin-bottom:8px">
            ${_allianceButtons(state.newAlliance)}
        </div>

        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Set Device Type</div>
        <select data-bind="device-type" style="width:100%;background:${SURFACE};border:1px solid ${BORDER};color:#ccc;padding:4px 8px;font-size:0.42rem;font-family:var(--font-mono);border-radius:2px;margin-bottom:8px">
            <option value="">-- No change --</option>
            ${DEVICE_TYPES.map(dt => `<option value="${dt}" ${state.newDeviceType === dt ? 'selected' : ''}>${dt.toUpperCase()}</option>`).join('')}
        </select>

        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Reason</div>
        <input type="text" data-bind="reason" placeholder="Why are you overriding? (optional)" value="${_esc(state.reason || '')}"
            style="width:100%;background:${SURFACE};border:1px solid ${BORDER};color:#ccc;padding:4px 8px;font-size:0.42rem;font-family:var(--font-mono);border-radius:2px;margin-bottom:8px;box-sizing:border-box" />

        <div style="font-size:0.42rem;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px">Operator</div>
        <input type="text" data-bind="operator" placeholder="Your name" value="${_esc(state.operator || 'operator')}"
            style="width:100%;background:${SURFACE};border:1px solid ${BORDER};color:#ccc;padding:4px 8px;font-size:0.42rem;font-family:var(--font-mono);border-radius:2px;margin-bottom:8px;box-sizing:border-box" />
    </div>`;

    // Submit button
    html += `<div style="padding:8px 10px;border-bottom:1px solid ${BORDER}">
        <button class="panel-action-btn panel-action-btn-primary" data-action="submit" style="width:100%;padding:6px;font-size:0.5rem;font-weight:bold;letter-spacing:1px" ${!state.targetId ? 'disabled' : ''}>
            APPLY OVERRIDE
        </button>
    </div>`;

    // Status message
    if (state.statusMessage) {
        const statusColor = state.statusType === 'success' ? GREEN : state.statusType === 'error' ? MAGENTA : CYAN;
        html += `<div style="padding:6px 10px;border-bottom:1px solid ${BORDER}">
            <div style="font-size:0.42rem;color:${statusColor};padding:4px 6px;border-left:2px solid ${statusColor};background:${statusColor}11">${_esc(state.statusMessage)}</div>
        </div>`;
    }

    // Recent overrides log
    if (state.history && state.history.length > 0) {
        html += `<div style="padding:6px 10px">
            <div style="font-size:0.38rem;color:${DIM};text-transform:uppercase;margin-bottom:4px">Recent Overrides</div>`;
        for (const entry of state.history.slice(0, 10)) {
            html += `<div style="font-size:0.38rem;color:#999;padding:2px 4px;border-left:2px solid ${BORDER};margin:2px 0">
                <span style="color:${CYAN}">${_esc(entry.target_id)}</span>
                ${entry.changes?.alliance ? `alliance \u2192 <span style="color:${(ALLIANCES.find(a => a.value === entry.changes.alliance) || {}).color || DIM}">${_esc(entry.changes.alliance)}</span>` : ''}
                ${entry.changes?.device_type ? `type \u2192 ${_esc(entry.changes.device_type)}` : ''}
                <span style="color:${DIM}">${_esc(entry.time || '')}</span>
            </div>`;
        }
        html += `</div>`;
    }

    content.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const ClassificationOverridePanelDef = {
    id: 'classification-override',
    title: 'CLASSIFICATION OVERRIDE',
    defaultPosition: { x: 60, y: 100 },
    defaultSize: { w: 360, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'classification-override-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;background:#0a0a1a';
        el.innerHTML = `
            <div data-bind="override-content" style="flex:1;overflow-y:auto">
                <div style="padding:20px;text-align:center;color:${DIM};font-size:0.5rem">Loading...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const state = {
            targetId: '',
            current: null,
            newAlliance: '',
            newDeviceType: '',
            reason: '',
            operator: 'operator',
            statusMessage: '',
            statusType: '',
            history: [],
            targetOptions: [],
        };

        // Load available targets for datalist
        _fetchTargets().then(targets => {
            state.targetOptions = targets.map(t => t.target_id || t.id).filter(Boolean).slice(0, 100);
            _renderPanel(bodyEl, state);
        });

        // Initial render
        _renderPanel(bodyEl, state);

        // Listen for target:focus events to auto-populate
        function onTargetFocus(data) {
            if (data && data.id) {
                state.targetId = data.id;
                loadTarget(data.id);
            }
        }
        EventBus.on('target:focus', onTargetFocus);
        panel._coUnsub = () => EventBus.off('target:focus', onTargetFocus);

        async function loadTarget(targetId) {
            state.targetId = targetId;
            state.current = null;
            state.newAlliance = '';
            state.newDeviceType = '';
            state.statusMessage = '';
            _renderPanel(bodyEl, state);

            const classification = await _fetchClassification(targetId);
            if (classification) {
                state.current = classification;
                state.newAlliance = classification.alliance || '';
            } else {
                state.statusMessage = `Could not load classification for ${targetId}`;
                state.statusType = 'error';
            }
            _renderPanel(bodyEl, state);
            wireEvents();
        }

        function wireEvents() {
            // Target ID input + load button
            const targetInput = bodyEl.querySelector('[data-bind="target-id"]');
            const loadBtn = bodyEl.querySelector('[data-action="load"]');
            const deviceTypeSelect = bodyEl.querySelector('[data-bind="device-type"]');
            const reasonInput = bodyEl.querySelector('[data-bind="reason"]');
            const operatorInput = bodyEl.querySelector('[data-bind="operator"]');
            const submitBtn = bodyEl.querySelector('[data-action="submit"]');

            if (loadBtn && targetInput) {
                loadBtn.addEventListener('click', () => {
                    const tid = targetInput.value.trim();
                    if (tid) loadTarget(tid);
                });
            }
            if (targetInput) {
                targetInput.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        const tid = targetInput.value.trim();
                        if (tid) loadTarget(tid);
                    }
                });
            }

            // Alliance buttons
            bodyEl.querySelectorAll('.co-alliance-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    state.newAlliance = btn.dataset.alliance;
                    _renderPanel(bodyEl, state);
                    wireEvents();
                });
            });

            // Device type, reason, operator sync
            if (deviceTypeSelect) {
                deviceTypeSelect.addEventListener('change', () => {
                    state.newDeviceType = deviceTypeSelect.value;
                });
            }
            if (reasonInput) {
                reasonInput.addEventListener('input', () => {
                    state.reason = reasonInput.value;
                });
            }
            if (operatorInput) {
                operatorInput.addEventListener('input', () => {
                    state.operator = operatorInput.value;
                });
            }

            // Submit
            if (submitBtn) {
                submitBtn.addEventListener('click', async () => {
                    if (!state.targetId) return;
                    // Read current values from DOM (in case render hasn't synced)
                    const dtSel = bodyEl.querySelector('[data-bind="device-type"]');
                    const rsn = bodyEl.querySelector('[data-bind="reason"]');
                    const op = bodyEl.querySelector('[data-bind="operator"]');
                    const alliance = state.newAlliance;
                    const deviceType = dtSel?.value || '';
                    const reason = rsn?.value || '';
                    const operator = op?.value || 'operator';

                    if (!alliance && !deviceType) {
                        state.statusMessage = 'Select an alliance or device type to override';
                        state.statusType = 'error';
                        _renderPanel(bodyEl, state);
                        wireEvents();
                        return;
                    }

                    submitBtn.textContent = 'APPLYING...';
                    submitBtn.disabled = true;

                    try {
                        const result = await _submitOverride(state.targetId, alliance, deviceType, reason, operator);
                        state.statusMessage = `Override applied: ${JSON.stringify(result.changes)}`;
                        state.statusType = 'success';

                        // Add to history
                        state.history.unshift({
                            target_id: state.targetId,
                            changes: result.changes,
                            old_values: result.old_values,
                            time: new Date().toLocaleTimeString(),
                        });

                        // Reload current classification
                        const updated = await _fetchClassification(state.targetId);
                        if (updated) state.current = updated;
                    } catch (err) {
                        state.statusMessage = `Override failed: ${err.message}`;
                        state.statusType = 'error';
                    }

                    _renderPanel(bodyEl, state);
                    wireEvents();
                });
            }
        }

        wireEvents();
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._coUnsub) {
            panel._coUnsub();
            panel._coUnsub = null;
        }
    },
};
