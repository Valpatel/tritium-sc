// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Merge Workflow Panel
// When the correlator or user identifies two targets as the same entity,
// show both side-by-side, confirm merge, combine signals into one dossier,
// and remove the duplicate.

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';
import { _esc } from '/lib/utils.js';


let _primaryId = null;
let _secondaryId = null;

export const TargetMergePanelDef = {
    id: 'target-merge',
    title: 'TGT MERGE',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 620, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'tgt-merge-inner';
        el.innerHTML = `
            <div class="tgm-toolbar">
                <span class="tgm-instruction mono">Select two targets to merge into one dossier</span>
                <button class="panel-action-btn" data-action="tgm-clear">CLEAR</button>
            </div>
            <div class="tgm-input-row">
                <div class="tgm-input-group">
                    <label class="mono" style="font-size:0.55rem;color:var(--cyan)">PRIMARY (survives)</label>
                    <input type="text" class="tgm-id-input" placeholder="ble_AA:BB:CC..." spellcheck="false" data-bind="tgm-primary-id">
                </div>
                <span class="tgm-arrow mono" style="color:var(--magenta);font-size:1.2rem">&#x2190;</span>
                <div class="tgm-input-group">
                    <label class="mono" style="font-size:0.55rem;color:var(--text-dim)">SECONDARY (merges in)</label>
                    <input type="text" class="tgm-id-input" placeholder="det_person_3..." spellcheck="false" data-bind="tgm-secondary-id">
                </div>
                <button class="panel-action-btn panel-action-btn-primary" data-action="tgm-load">LOAD</button>
            </div>
            <div class="tgm-comparison" data-bind="tgm-comparison"></div>
            <div class="tgm-merge-preview" data-bind="tgm-preview" hidden>
                <div class="tgm-preview-header mono" style="color:var(--green)">MERGE PREVIEW</div>
                <div class="tgm-preview-body" data-bind="tgm-preview-body"></div>
            </div>
            <div class="tgm-actions" data-bind="tgm-actions" hidden>
                <button class="panel-action-btn" data-action="tgm-preview-merge" style="border-color:var(--yellow);color:var(--yellow)">PREVIEW MERGE</button>
                <button class="panel-action-btn panel-action-btn-primary" data-action="tgm-confirm" style="background:var(--green);color:#0a0a0f;border-color:var(--green)">CONFIRM MERGE</button>
                <span class="tgm-status mono" data-bind="tgm-status"></span>
            </div>
        `;

        // Wire load button
        const loadBtn = el.querySelector('[data-action="tgm-load"]');
        const primaryInput = el.querySelector('[data-bind="tgm-primary-id"]');
        const secondaryInput = el.querySelector('[data-bind="tgm-secondary-id"]');

        loadBtn.addEventListener('click', () => {
            _primaryId = primaryInput.value.trim();
            _secondaryId = secondaryInput.value.trim();
            if (_primaryId && _secondaryId) {
                _renderComparison(el);
            }
        });

        [primaryInput, secondaryInput].forEach(input => {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') loadBtn.click();
                e.stopPropagation();
            });
        });

        // Wire clear
        el.querySelector('[data-action="tgm-clear"]').addEventListener('click', () => {
            _primaryId = null;
            _secondaryId = null;
            primaryInput.value = '';
            secondaryInput.value = '';
            _clearAll(el);
        });

        // Wire preview
        el.querySelector('[data-action="tgm-preview-merge"]').addEventListener('click', () => {
            _showPreview(el);
        });

        // Wire confirm merge
        el.querySelector('[data-action="tgm-confirm"]').addEventListener('click', () => {
            _executeMerge(el);
        });

        // Listen for merge suggestions from target-compare panel
        EventBus.on('target:merge-request', (data) => {
            if (data.ids && data.ids.length >= 2) {
                _primaryId = data.ids[0];
                _secondaryId = data.ids[1];
                primaryInput.value = _primaryId;
                secondaryInput.value = _secondaryId;
                _renderComparison(el);
            }
        });

        _clearAll(el);
        return el;
    },

    destroy() {
        _primaryId = null;
        _secondaryId = null;
    },
};

function _clearAll(el) {
    const comp = el.querySelector('[data-bind="tgm-comparison"]');
    const preview = el.querySelector('[data-bind="tgm-preview"]');
    const actions = el.querySelector('[data-bind="tgm-actions"]');
    const status = el.querySelector('[data-bind="tgm-status"]');

    if (comp) comp.innerHTML = '<div class="tgm-empty mono">No targets loaded for merge.</div>';
    if (preview) preview.hidden = true;
    if (actions) actions.hidden = true;
    if (status) status.textContent = '';
}

function _getTargetData(id) {
    const unit = TritiumStore.units.get(id);
    if (unit) return { id, ...unit, source: unit.source || 'simulation' };
    const targets = TritiumStore.get('targets') || {};
    if (targets[id]) return { id, ...targets[id] };
    return { id, name: id, type: 'unknown', alliance: 'unknown', source: 'unknown', status: 'unknown' };
}

function _renderComparison(el) {
    const comp = el.querySelector('[data-bind="tgm-comparison"]');
    const actions = el.querySelector('[data-bind="tgm-actions"]');

    if (!_primaryId || !_secondaryId) {
        comp.innerHTML = '<div class="tgm-empty mono">Enter two target IDs above.</div>';
        if (actions) actions.hidden = true;
        return;
    }

    const primary = _getTargetData(_primaryId);
    const secondary = _getTargetData(_secondaryId);

    const fields = [
        { key: 'id', label: 'TARGET ID' },
        { key: 'name', label: 'NAME' },
        { key: 'type', label: 'TYPE' },
        { key: 'alliance', label: 'ALLIANCE' },
        { key: 'source', label: 'SOURCE' },
        { key: 'status', label: 'STATUS' },
        { key: 'position', label: 'POSITION', fmt: (v) => v ? `${(v.x || 0).toFixed(1)}, ${(v.y || 0).toFixed(1)}` : '--' },
        { key: 'battery', label: 'BATTERY', fmt: (v) => v !== undefined ? `${v}%` : '--' },
        { key: 'speed', label: 'SPEED', fmt: (v) => v !== undefined ? `${(v || 0).toFixed(1)}` : '--' },
    ];

    let html = '<table class="tgm-table"><thead><tr>';
    html += '<th class="tgm-prop-col">PROPERTY</th>';
    html += `<th class="tgm-col-primary"><span style="color:var(--cyan)">PRIMARY</span><br>${_esc(primary.name || primary.id)}</th>`;
    html += `<th class="tgm-col-secondary"><span style="color:var(--text-dim)">SECONDARY</span><br>${_esc(secondary.name || secondary.id)}</th>`;
    html += '<th class="tgm-col-merged"><span style="color:var(--green)">MERGED</span></th>';
    html += '</tr></thead><tbody>';

    for (const f of fields) {
        const pv = f.fmt ? f.fmt(primary[f.key]) : (primary[f.key] ?? '--');
        const sv = f.fmt ? f.fmt(secondary[f.key]) : (secondary[f.key] ?? '--');
        // Merge logic: prefer primary, fallback to secondary
        const mv = (pv && pv !== '--' && pv !== 'unknown') ? pv : sv;
        const diff = String(pv) !== String(sv) ? ' tgm-diff' : '';

        html += `<tr>`;
        html += `<td class="tgm-prop-label mono">${f.label}</td>`;
        html += `<td class="tgm-val${diff}">${_esc(String(pv))}</td>`;
        html += `<td class="tgm-val${diff}">${_esc(String(sv))}</td>`;
        html += `<td class="tgm-val-merged">${_esc(String(mv))}</td>`;
        html += `</tr>`;
    }

    // Signal merge row
    html += `<tr>`;
    html += `<td class="tgm-prop-label mono">SIGNALS</td>`;
    html += `<td class="tgm-val">${_esc(primary.source || '--')}</td>`;
    html += `<td class="tgm-val">${_esc(secondary.source || '--')}</td>`;
    html += `<td class="tgm-val-merged" style="color:var(--green)">${_esc(primary.source || '--')} + ${_esc(secondary.source || '--')}</td>`;
    html += `</tr>`;

    html += '</tbody></table>';
    comp.innerHTML = html;

    if (actions) actions.hidden = false;
}

function _showPreview(el) {
    const preview = el.querySelector('[data-bind="tgm-preview"]');
    const previewBody = el.querySelector('[data-bind="tgm-preview-body"]');
    if (!preview || !previewBody) return;

    const primary = _getTargetData(_primaryId);
    const secondary = _getTargetData(_secondaryId);

    previewBody.innerHTML = `
        <div class="tgm-preview-item mono">
            <span style="color:var(--green)">SURVIVING TARGET:</span> ${_esc(_primaryId)}<br>
            <span style="color:var(--cyan)">Inherits signals from:</span> ${_esc(_secondaryId)}<br>
            <span style="color:var(--magenta)">REMOVED:</span> ${_esc(_secondaryId)} (redirected to ${_esc(_primaryId)})<br>
            <span style="color:var(--yellow)">Combined sources:</span> ${_esc(primary.source || 'unknown')} + ${_esc(secondary.source || 'unknown')}<br>
        </div>
    `;
    preview.hidden = false;
}

async function _executeMerge(el) {
    const status = el.querySelector('[data-bind="tgm-status"]');
    if (!_primaryId || !_secondaryId) {
        if (status) status.textContent = 'ERROR: Select two targets';
        return;
    }

    if (status) {
        status.textContent = 'MERGING...';
        status.style.color = 'var(--yellow)';
    }

    try {
        const resp = await fetch('/api/dossiers/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                primary_id: _primaryId,
                secondary_id: _secondaryId,
            }),
        });

        if (resp.ok) {
            const result = await resp.json();
            if (status) {
                status.textContent = 'MERGE COMPLETE';
                status.style.color = 'var(--green)';
            }
            EventBus.emit('toast:show', {
                message: `Targets merged: ${_secondaryId} -> ${_primaryId}`,
                type: 'info',
            });
            EventBus.emit('target:merged', {
                primary_id: _primaryId,
                secondary_id: _secondaryId,
            });
        } else {
            const err = await resp.text();
            if (status) {
                status.textContent = `FAILED: ${err.substring(0, 60)}`;
                status.style.color = 'var(--magenta)';
            }
            EventBus.emit('toast:show', {
                message: `Merge failed: ${err.substring(0, 80)}`,
                type: 'alert',
            });
        }
    } catch (e) {
        if (status) {
            status.textContent = 'NETWORK ERROR';
            status.style.color = 'var(--magenta)';
        }
        EventBus.emit('toast:show', { message: 'Merge request failed', type: 'alert' });
    }
}
