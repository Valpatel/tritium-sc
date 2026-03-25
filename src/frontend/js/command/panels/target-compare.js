// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Comparison Panel
// Select 2+ targets and compare their properties, signal history,
// and position trails side-by-side. Useful for deciding if two
// targets should be merged (same physical entity, different sensor IDs).

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';
import { _esc } from '/lib/utils.js';


// Selected target IDs for comparison
let _selectedIds = [];
let _panelEl = null;

export const TargetComparePanelDef = {
    id: 'target-compare',
    title: 'TGT COMPARE',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 600, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'tgt-compare-inner';
        _panelEl = el;

        el.innerHTML = `
            <div class="tgc-toolbar">
                <span class="tgc-instruction mono">Select targets on map or enter IDs below</span>
                <button class="panel-action-btn" data-action="tgc-clear">CLEAR</button>
            </div>
            <div class="tgc-input-row">
                <input type="text" class="tgc-id-input" placeholder="Target ID (e.g. ble_AA:BB:CC)" spellcheck="false" data-bind="tgc-add-id">
                <button class="panel-action-btn panel-action-btn-primary" data-action="tgc-add">ADD</button>
            </div>
            <div class="tgc-comparison-area" data-bind="tgc-table"></div>
            <div class="tgc-actions" data-bind="tgc-actions" hidden>
                <button class="panel-action-btn panel-action-btn-primary" data-action="tgc-merge">SUGGEST MERGE</button>
                <span class="tgc-similarity mono" data-bind="tgc-similarity"></span>
            </div>
        `;

        // Wire add button
        const addBtn = el.querySelector('[data-action="tgc-add"]');
        const addInput = el.querySelector('[data-bind="tgc-add-id"]');
        addBtn.addEventListener('click', () => {
            const id = addInput.value.trim();
            if (id && !_selectedIds.includes(id)) {
                _selectedIds.push(id);
                addInput.value = '';
                _renderComparison(el);
            }
        });
        addInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                addBtn.click();
            }
            e.stopPropagation();
        });

        // Wire clear
        el.querySelector('[data-action="tgc-clear"]').addEventListener('click', () => {
            _selectedIds = [];
            _renderComparison(el);
        });

        // Wire merge suggestion
        el.querySelector('[data-action="tgc-merge"]').addEventListener('click', () => {
            if (_selectedIds.length >= 2) {
                EventBus.emit('toast:show', {
                    message: `Merge suggested for targets: ${_selectedIds.join(', ')}`,
                    type: 'info',
                });
            }
        });

        // Listen for map target selection events
        EventBus.on('target:compare-add', (data) => {
            const id = data.id || data.target_id;
            if (id && !_selectedIds.includes(id)) {
                _selectedIds.push(id);
                _renderComparison(el);
            }
        });

        // Listen for unit clicks on map to add to comparison
        EventBus.on('unit:selected', (data) => {
            if (data && data.id && _panelEl && !_panelEl.closest('[hidden]')) {
                if (!_selectedIds.includes(data.id)) {
                    _selectedIds.push(data.id);
                    _renderComparison(el);
                }
            }
        });

        _renderComparison(el);
        return el;
    },

    destroy() {
        _panelEl = null;
    },
};

function _renderComparison(el) {
    const area = el.querySelector('[data-bind="tgc-table"]');
    const actions = el.querySelector('[data-bind="tgc-actions"]');

    if (_selectedIds.length === 0) {
        area.innerHTML = `
            <div class="tgc-empty mono">
                No targets selected for comparison.<br>
                Add target IDs above or click targets on the map.
            </div>
        `;
        actions.hidden = true;
        return;
    }

    // Fetch target data
    const targets = _selectedIds.map(id => _getTargetData(id));

    // Build comparison table
    const properties = [
        { key: 'id', label: 'TARGET ID' },
        { key: 'name', label: 'NAME' },
        { key: 'type', label: 'TYPE' },
        { key: 'alliance', label: 'ALLIANCE' },
        { key: 'source', label: 'SOURCE' },
        { key: 'status', label: 'STATUS' },
        { key: 'position', label: 'POSITION', fmt: (v) => v ? `${(v.x || 0).toFixed(1)}, ${(v.y || 0).toFixed(1)}` : '--' },
        { key: 'heading', label: 'HEADING', fmt: (v) => v !== undefined ? `${(v || 0).toFixed(0)}deg` : '--' },
        { key: 'health', label: 'HEALTH', fmt: (v) => v !== undefined ? `${v}` : '--' },
        { key: 'battery', label: 'BATTERY', fmt: (v) => v !== undefined ? `${v}%` : '--' },
        { key: 'speed', label: 'SPEED', fmt: (v) => v !== undefined ? `${(v || 0).toFixed(1)}` : '--' },
        { key: 'eliminations', label: 'ELIMINATIONS' },
        { key: 'squadId', label: 'SQUAD' },
        { key: 'fsmState', label: 'FSM STATE' },
    ];

    let html = '<table class="tgc-table"><thead><tr><th class="tgc-prop-col">PROPERTY</th>';
    for (let i = 0; i < targets.length; i++) {
        const t = targets[i];
        const allianceClass = t.alliance === 'friendly' ? 'tgc-friendly' :
                              t.alliance === 'hostile' ? 'tgc-hostile' : 'tgc-unknown';
        html += `<th class="tgc-target-col ${allianceClass}">
            ${_esc(t.name || t.id || `Target ${i + 1}`)}
            <button class="tgc-remove-btn" data-remove="${i}" title="Remove from comparison">x</button>
        </th>`;
    }
    html += '</tr></thead><tbody>';

    for (const prop of properties) {
        html += `<tr><td class="tgc-prop-label mono">${prop.label}</td>`;
        const values = targets.map(t => {
            const v = t[prop.key];
            if (prop.fmt) return prop.fmt(v);
            return v !== undefined && v !== null ? String(v) : '--';
        });

        // Highlight differences
        const allSame = values.every(v => v === values[0]);

        for (const v of values) {
            const cls = allSame ? '' : 'tgc-diff';
            html += `<td class="tgc-val ${cls}">${_esc(v)}</td>`;
        }
        html += '</tr>';
    }

    // Distance row (if 2+ targets with positions)
    if (targets.length >= 2) {
        html += `<tr><td class="tgc-prop-label mono">DISTANCE</td>`;
        for (let i = 0; i < targets.length; i++) {
            if (i === 0) {
                html += '<td class="tgc-val">--</td>';
            } else {
                const dist = _calcDistance(targets[0], targets[i]);
                html += `<td class="tgc-val">${dist}</td>`;
            }
        }
        html += '</tr>';
    }

    html += '</tbody></table>';
    area.innerHTML = html;

    // Wire remove buttons
    area.querySelectorAll('.tgc-remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const idx = parseInt(btn.dataset.remove);
            _selectedIds.splice(idx, 1);
            _renderComparison(el);
        });
    });

    // Show actions and similarity
    if (targets.length >= 2) {
        actions.hidden = false;
        const sim = _calcSimilarity(targets);
        const simEl = el.querySelector('[data-bind="tgc-similarity"]');
        if (simEl) {
            const simColor = sim > 70 ? '#05ffa1' : sim > 40 ? '#fcee0a' : '#ff2a6d';
            simEl.innerHTML = `Similarity: <span style="color:${simColor};font-weight:bold">${sim}%</span>`;
        }
    } else {
        actions.hidden = true;
    }
}

function _getTargetData(id) {
    // Try TritiumStore.units first (simulation/game targets)
    const unit = TritiumStore.units.get(id);
    if (unit) return { id, ...unit, source: unit.source || 'simulation' };

    // Try targets store
    const targets = TritiumStore.get('targets') || {};
    if (targets[id]) return { id, ...targets[id] };

    // Return stub
    return { id, name: id, type: 'unknown', alliance: 'unknown', source: 'unknown', status: 'unknown' };
}

function _calcDistance(t1, t2) {
    const p1 = t1.position || {};
    const p2 = t2.position || {};
    const dx = (p1.x || 0) - (p2.x || 0);
    const dy = (p1.y || 0) - (p2.y || 0);
    const dist = Math.sqrt(dx * dx + dy * dy);
    return `${dist.toFixed(1)}m`;
}

function _calcSimilarity(targets) {
    if (targets.length < 2) return 0;
    const t1 = targets[0];
    const t2 = targets[1];
    let score = 0;
    let checks = 0;

    // Type match
    checks++;
    if (t1.type === t2.type && t1.type !== 'unknown') score++;

    // Alliance match
    checks++;
    if (t1.alliance === t2.alliance) score++;

    // Proximity (within 5m)
    checks++;
    const p1 = t1.position || {};
    const p2 = t2.position || {};
    const dx = (p1.x || 0) - (p2.x || 0);
    const dy = (p1.y || 0) - (p2.y || 0);
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist < 5) score++;
    else if (dist < 15) score += 0.5;

    // Source diversity (different sources = more likely same entity)
    checks++;
    if (t1.source !== t2.source) score++;

    // Status match
    checks++;
    if (t1.status === t2.status) score += 0.5;

    return Math.round((score / checks) * 100);
}
