// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Ontology Explorer Panel — browse the Tritium data model interactively.
// Backend: GET /api/v1/ontology/types, /objects/{type}, /objects/{type}/{pk},
//          /objects/{type}/{pk}/links/{linkType}, POST /objects/{type}/search,
//          POST /actions/{actionType}/apply
// Shows entity types (Target, Dossier, BleDevice, Device), object lists with
// search/filter, object detail with link traversal, and typed actions.

import { _esc } from '/lib/utils.js';

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

const API_BASE = '/api/v1/ontology';

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchTypes() {
    try {
        const resp = await fetch(`${API_BASE}/types`);
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.types || [];
    } catch { return []; }
}

async function _fetchObjects(typeName, pageSize = 25, pageToken = null) {
    try {
        let url = `${API_BASE}/objects/${encodeURIComponent(typeName)}?pageSize=${pageSize}`;
        if (pageToken) url += `&pageToken=${encodeURIComponent(pageToken)}`;
        const resp = await fetch(url);
        if (!resp.ok) return { data: [], nextPageToken: null, totalCount: 0 };
        return await resp.json();
    } catch { return { data: [], nextPageToken: null, totalCount: 0 }; }
}

async function _fetchObject(typeName, pk) {
    try {
        const resp = await fetch(`${API_BASE}/objects/${encodeURIComponent(typeName)}/${encodeURIComponent(pk)}`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch { return null; }
}

async function _fetchLinks(typeName, pk, linkType, pageSize = 25) {
    try {
        const resp = await fetch(`${API_BASE}/objects/${encodeURIComponent(typeName)}/${encodeURIComponent(pk)}/links/${encodeURIComponent(linkType)}?pageSize=${pageSize}`);
        if (!resp.ok) return { data: [], totalCount: 0 };
        return await resp.json();
    } catch { return { data: [], totalCount: 0 }; }
}

async function _searchObjects(typeName, where, pageSize = 25) {
    try {
        const resp = await fetch(`${API_BASE}/objects/${encodeURIComponent(typeName)}/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ where, pageSize }),
        });
        if (!resp.ok) return { data: [], totalCount: 0 };
        return await resp.json();
    } catch { return { data: [], totalCount: 0 }; }
}

async function _applyAction(actionType, parameters) {
    try {
        const resp = await fetch(`${API_BASE}/actions/${encodeURIComponent(actionType)}/apply`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ parameters }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            return { ok: false, error: err.detail || `HTTP ${resp.status}` };
        }
        return await resp.json();
    } catch (e) { return { ok: false, error: e.message }; }
}

async function _fetchTypeSchema(typeName) {
    try {
        const resp = await fetch(`${API_BASE}/types/${encodeURIComponent(typeName)}`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch { return null; }
}

// ---------------------------------------------------------------------------
// Render helpers
// ---------------------------------------------------------------------------

const TYPE_ICONS = {
    'Target': '\u25C6',    // diamond
    'Dossier': '\u2588',   // block
    'BleDevice': '\u25CF', // circle
    'Device': '\u25A0',    // square
};

const TYPE_COLORS = {
    'Target': CYAN,
    'Dossier': MAGENTA,
    'BleDevice': GREEN,
    'Device': YELLOW,
};

function _badge(text, color) {
    return `<span style="display:inline-block;padding:1px 6px;border-radius:3px;font-size:0.36rem;background:${color}22;color:${color};border:1px solid ${color}44">${_esc(text)}</span>`;
}

function _pill(text, color) {
    return `<span style="display:inline-block;padding:0 5px;border-radius:8px;font-size:0.34rem;background:${color};color:#000;font-weight:600">${_esc(text)}</span>`;
}

function _truncate(str, max = 40) {
    if (!str) return '';
    const s = String(str);
    return s.length > max ? s.slice(0, max) + '...' : s;
}

// ---------------------------------------------------------------------------
// Panel state
// ---------------------------------------------------------------------------

function _createState() {
    return {
        view: 'types',       // types | objects | detail
        types: [],
        selectedType: null,
        typeSchema: null,
        objects: { data: [], nextPageToken: null, totalCount: 0 },
        selectedObject: null,
        links: {},
        searchField: '',
        searchValue: '',
        timer: null,
    };
}

// ---------------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------------

function _renderTypesView(state, container) {
    const types = state.types;
    let html = `<div style="padding:8px">
        <div style="color:${CYAN};font-size:0.42rem;font-weight:700;margin-bottom:8px;text-transform:uppercase;letter-spacing:0.08rem">Ontology Types</div>
        <div style="color:${DIM};font-size:0.36rem;margin-bottom:10px">${types.length} entity types in the Tritium data model</div>`;

    for (const t of types) {
        const icon = TYPE_ICONS[t.apiName] || '\u25CB';
        const color = TYPE_COLORS[t.apiName] || CYAN;
        html += `<div class="onto-type-card" data-type="${_esc(t.apiName)}" style="
            padding:8px 10px;margin-bottom:6px;border:1px solid ${BORDER};border-left:3px solid ${color};
            background:${SURFACE};cursor:pointer;border-radius:3px;transition:border-color 0.2s">
            <div style="display:flex;justify-content:space-between;align-items:center">
                <span style="color:${color};font-size:0.42rem;font-weight:600">${icon} ${_esc(t.displayName)}</span>
                <span style="color:${DIM};font-size:0.34rem">${t.propertyCount} props \u00B7 ${t.linkCount} links</span>
            </div>
            <div style="color:${DIM};font-size:0.34rem;margin-top:3px">${_esc(t.description)}</div>
        </div>`;
    }
    html += '</div>';
    container.innerHTML = html;

    container.querySelectorAll('.onto-type-card').forEach(card => {
        card.addEventListener('click', async () => {
            const typeName = card.dataset.type;
            state.selectedType = typeName;
            state.typeSchema = await _fetchTypeSchema(typeName);
            state.objects = await _fetchObjects(typeName);
            state.view = 'objects';
            _render(state, container);
        });
        card.addEventListener('mouseenter', () => { card.style.borderColor = CYAN; });
        card.addEventListener('mouseleave', () => { card.style.borderColor = BORDER; });
    });
}

function _renderObjectsView(state, container) {
    const { selectedType, objects, typeSchema } = state;
    const color = TYPE_COLORS[selectedType] || CYAN;
    const pkField = typeSchema ? typeSchema.primaryKey : 'id';
    const props = typeSchema ? Object.keys(typeSchema.properties || {}) : [];

    // Pick display columns: pk + up to 3 most useful fields
    const displayCols = [pkField];
    const preferred = ['name', 'alliance', 'status', 'entity_type', 'threat_level', 'mac', 'device_name', 'last_rssi'];
    for (const pref of preferred) {
        if (props.includes(pref) && !displayCols.includes(pref) && displayCols.length < 4) {
            displayCols.push(pref);
        }
    }

    let html = `<div style="padding:6px 8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
            <div>
                <button class="onto-back-btn" style="font-size:0.36rem;padding:2px 8px;cursor:pointer;background:${SURFACE};color:${CYAN};border:1px solid ${CYAN}44;border-radius:3px">\u25C0 BACK</button>
                <span style="color:${color};font-size:0.42rem;font-weight:600;margin-left:8px">${_esc(selectedType)}</span>
                <span style="color:${DIM};font-size:0.36rem;margin-left:6px">${objects.totalCount} objects</span>
            </div>
        </div>`;

    // Search bar
    html += `<div style="display:flex;gap:4px;margin-bottom:6px">
        <select class="onto-search-field" style="font-size:0.36rem;padding:2px 4px;background:${SURFACE};color:${CYAN};border:1px solid ${BORDER};border-radius:3px;flex:0 0 auto">
            <option value="">Filter by...</option>`;
    for (const p of props) {
        const sel = state.searchField === p ? ' selected' : '';
        html += `<option value="${_esc(p)}"${sel}>${_esc(p)}</option>`;
    }
    html += `</select>
        <input class="onto-search-input" type="text" placeholder="value..." value="${_esc(state.searchValue)}"
            style="flex:1;font-size:0.36rem;padding:2px 6px;background:${SURFACE};color:#ddd;border:1px solid ${BORDER};border-radius:3px">
        <button class="onto-search-btn" style="font-size:0.36rem;padding:2px 8px;background:${CYAN}22;color:${CYAN};border:1px solid ${CYAN}44;border-radius:3px;cursor:pointer">SEARCH</button>
    </div>`;

    // Table header
    html += `<div style="display:grid;grid-template-columns:repeat(${displayCols.length}, 1fr);gap:2px;padding:2px 4px;border-bottom:1px solid ${BORDER}">`;
    for (const col of displayCols) {
        html += `<span style="color:${DIM};font-size:0.32rem;text-transform:uppercase;font-weight:600">${_esc(col)}</span>`;
    }
    html += '</div>';

    // Table rows
    for (const obj of objects.data) {
        const pkVal = obj[pkField] || obj.target_id || obj.dossier_id || obj.mac || obj.device_id || '';
        html += `<div class="onto-obj-row" data-pk="${_esc(String(pkVal))}" style="
            display:grid;grid-template-columns:repeat(${displayCols.length}, 1fr);gap:2px;padding:3px 4px;
            border-bottom:1px solid ${BORDER}11;cursor:pointer;transition:background 0.15s"
            onmouseenter="this.style.background='${CYAN}11'" onmouseleave="this.style.background='transparent'">`;
        for (const col of displayCols) {
            const val = obj[col];
            let display = _truncate(val, 28);
            let style = `font-size:0.36rem;color:#ccc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap`;
            if (col === pkField) style += `;color:${color};font-family:monospace;font-size:0.34rem`;
            if (col === 'alliance') {
                const aColor = val === 'friendly' ? GREEN : val === 'hostile' ? MAGENTA : YELLOW;
                display = `<span style="color:${aColor}">${_esc(String(val || 'unknown'))}</span>`;
                html += `<span style="${style}">${display}</span>`;
                continue;
            }
            html += `<span style="${style}">${_esc(display)}</span>`;
        }
        html += '</div>';
    }

    // Pagination
    if (objects.nextPageToken || objects.totalCount > objects.data.length) {
        html += `<div style="padding:4px;text-align:center">
            <button class="onto-next-btn" style="font-size:0.36rem;padding:2px 12px;background:${CYAN}22;color:${CYAN};border:1px solid ${CYAN}44;border-radius:3px;cursor:pointer">LOAD MORE</button>
        </div>`;
    }

    html += '</div>';
    container.innerHTML = html;

    // Event listeners
    container.querySelector('.onto-back-btn')?.addEventListener('click', () => {
        state.view = 'types';
        state.searchField = '';
        state.searchValue = '';
        _render(state, container);
    });

    container.querySelector('.onto-search-btn')?.addEventListener('click', async () => {
        const field = container.querySelector('.onto-search-field').value;
        const value = container.querySelector('.onto-search-input').value.trim();
        state.searchField = field;
        state.searchValue = value;
        if (field && value) {
            state.objects = await _searchObjects(selectedType, { field, phrase: value });
        } else {
            state.objects = await _fetchObjects(selectedType);
        }
        _render(state, container);
    });

    container.querySelector('.onto-next-btn')?.addEventListener('click', async () => {
        if (objects.nextPageToken) {
            const more = await _fetchObjects(selectedType, 25, objects.nextPageToken);
            state.objects.data = state.objects.data.concat(more.data);
            state.objects.nextPageToken = more.nextPageToken;
            _render(state, container);
        }
    });

    container.querySelectorAll('.onto-obj-row').forEach(row => {
        row.addEventListener('click', async () => {
            const pk = row.dataset.pk;
            state.selectedObject = await _fetchObject(selectedType, pk);
            state.links = {};
            state.view = 'detail';
            _render(state, container);
        });
    });
}

function _renderDetailView(state, container) {
    const { selectedType, selectedObject, typeSchema, links } = state;
    const color = TYPE_COLORS[selectedType] || CYAN;
    const pkField = typeSchema ? typeSchema.primaryKey : 'id';
    const linkDefs = typeSchema ? typeSchema.links || {} : {};
    const obj = selectedObject || {};
    const pkVal = obj[pkField] || '';

    let html = `<div style="padding:6px 8px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
            <div>
                <button class="onto-back-list-btn" style="font-size:0.36rem;padding:2px 8px;cursor:pointer;background:${SURFACE};color:${CYAN};border:1px solid ${CYAN}44;border-radius:3px">\u25C0 LIST</button>
                <span style="color:${color};font-size:0.42rem;font-weight:600;margin-left:8px">${_esc(selectedType)}</span>
            </div>
            <span style="color:${DIM};font-size:0.34rem;font-family:monospace">${_esc(String(pkVal))}</span>
        </div>`;

    // Properties table
    html += `<div style="border:1px solid ${BORDER};border-radius:3px;margin-bottom:8px;overflow:hidden">
        <div style="padding:3px 8px;background:${BORDER};color:${DIM};font-size:0.34rem;text-transform:uppercase;font-weight:600">Properties</div>`;
    const entries = Object.entries(obj).filter(([k]) => typeof obj[k] !== 'object' || obj[k] === null);
    for (const [key, val] of entries) {
        let display = val === null || val === undefined ? '<i style="color:#555">null</i>' : _esc(_truncate(String(val), 60));
        if (key === 'alliance') {
            const aColor = val === 'friendly' ? GREEN : val === 'hostile' ? MAGENTA : YELLOW;
            display = `<span style="color:${aColor};font-weight:600">${_esc(String(val))}</span>`;
        }
        html += `<div style="display:flex;padding:2px 8px;border-bottom:1px solid ${BORDER}11">
            <span style="flex:0 0 140px;color:${DIM};font-size:0.34rem;font-family:monospace">${_esc(key)}</span>
            <span style="flex:1;color:#ccc;font-size:0.36rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${display}</span>
        </div>`;
    }
    html += '</div>';

    // Nested objects
    const nested = Object.entries(obj).filter(([, v]) => v !== null && typeof v === 'object');
    if (nested.length > 0) {
        html += `<div style="border:1px solid ${BORDER};border-radius:3px;margin-bottom:8px;overflow:hidden">
            <div style="padding:3px 8px;background:${BORDER};color:${DIM};font-size:0.34rem;text-transform:uppercase;font-weight:600">Nested Data</div>`;
        for (const [key, val] of nested) {
            const jsonStr = JSON.stringify(val, null, 2);
            html += `<div style="padding:4px 8px;border-bottom:1px solid ${BORDER}11">
                <div style="color:${CYAN};font-size:0.34rem;font-family:monospace;margin-bottom:2px">${_esc(key)}</div>
                <pre style="color:#aaa;font-size:0.32rem;margin:0;max-height:80px;overflow:auto;white-space:pre-wrap">${_esc(jsonStr)}</pre>
            </div>`;
        }
        html += '</div>';
    }

    // Links section
    const linkNames = Object.keys(linkDefs);
    if (linkNames.length > 0) {
        html += `<div style="border:1px solid ${BORDER};border-radius:3px;margin-bottom:8px;overflow:hidden">
            <div style="padding:3px 8px;background:${BORDER};color:${DIM};font-size:0.34rem;text-transform:uppercase;font-weight:600">Relationships</div>`;
        for (const linkName of linkNames) {
            const ld = linkDefs[linkName];
            const linkData = links[linkName];
            const targetColor = TYPE_COLORS[ld.targetType] || CYAN;
            html += `<div style="padding:4px 8px;border-bottom:1px solid ${BORDER}11">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="color:${targetColor};font-size:0.36rem">\u2192 ${_esc(linkName)} <span style="color:${DIM};font-size:0.32rem">(${_esc(ld.targetType)}, ${_esc(ld.cardinality)})</span></span>`;
            if (linkData) {
                html += `<span style="color:${DIM};font-size:0.34rem">${linkData.totalCount} found</span>`;
            } else {
                html += `<button class="onto-load-link" data-link="${_esc(linkName)}" style="font-size:0.34rem;padding:1px 8px;background:${targetColor}22;color:${targetColor};border:1px solid ${targetColor}44;border-radius:3px;cursor:pointer">LOAD</button>`;
            }
            html += '</div>';
            if (linkData && linkData.data.length > 0) {
                html += `<div style="margin-top:3px;max-height:120px;overflow-y:auto">`;
                for (const linked of linkData.data.slice(0, 10)) {
                    const preview = _truncate(JSON.stringify(linked), 80);
                    html += `<div style="padding:1px 0;color:#aaa;font-size:0.32rem;font-family:monospace">${_esc(preview)}</div>`;
                }
                if (linkData.data.length > 10) {
                    html += `<div style="color:${DIM};font-size:0.32rem">...and ${linkData.totalCount - 10} more</div>`;
                }
                html += '</div>';
            }
            html += '</div>';
        }
        html += '</div>';
    }

    // Actions section (only for Dossier type which has actions)
    if (selectedType === 'Dossier' && pkVal) {
        html += `<div style="border:1px solid ${BORDER};border-radius:3px;overflow:hidden">
            <div style="padding:3px 8px;background:${BORDER};color:${DIM};font-size:0.34rem;text-transform:uppercase;font-weight:600">Actions</div>
            <div style="padding:6px 8px;display:flex;flex-wrap:wrap;gap:4px">
                <button class="onto-action-btn" data-action="tag-dossier" style="font-size:0.34rem;padding:2px 8px;background:${GREEN}22;color:${GREEN};border:1px solid ${GREEN}44;border-radius:3px;cursor:pointer">+ TAG</button>
                <button class="onto-action-btn" data-action="note-dossier" style="font-size:0.34rem;padding:2px 8px;background:${CYAN}22;color:${CYAN};border:1px solid ${CYAN}44;border-radius:3px;cursor:pointer">+ NOTE</button>
                <button class="onto-action-btn" data-action="set-threat-level" style="font-size:0.34rem;padding:2px 8px;background:${YELLOW}22;color:${YELLOW};border:1px solid ${YELLOW}44;border-radius:3px;cursor:pointer">SET THREAT</button>
            </div>
            <div class="onto-action-result" style="padding:0 8px 4px;font-size:0.34rem;color:${DIM}"></div>
        </div>`;
    }

    html += '</div>';
    container.innerHTML = html;

    // Event listeners
    container.querySelector('.onto-back-list-btn')?.addEventListener('click', () => {
        state.view = 'objects';
        state.selectedObject = null;
        state.links = {};
        _render(state, container);
    });

    container.querySelectorAll('.onto-load-link').forEach(btn => {
        btn.addEventListener('click', async () => {
            const linkName = btn.dataset.link;
            state.links[linkName] = await _fetchLinks(selectedType, pkVal, linkName);
            _render(state, container);
        });
    });

    container.querySelectorAll('.onto-action-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const actionType = btn.dataset.action;
            const resultEl = container.querySelector('.onto-action-result');
            let params = { dossier_id: pkVal };

            if (actionType === 'tag-dossier') {
                const tag = prompt('Enter tag:');
                if (!tag) return;
                params.tag = tag;
            } else if (actionType === 'note-dossier') {
                const note = prompt('Enter note:');
                if (!note) return;
                params.note = note;
            } else if (actionType === 'set-threat-level') {
                const level = prompt('Threat level (none/low/medium/high/critical):');
                if (!level) return;
                params.level = level;
            }

            const result = await _applyAction(actionType, params);
            if (resultEl) {
                resultEl.style.color = result.ok ? GREEN : MAGENTA;
                resultEl.textContent = result.ok ? `\u2713 ${actionType} applied` : `\u2717 ${result.error}`;
            }
            // Refresh object after action
            if (result.ok) {
                state.selectedObject = await _fetchObject(selectedType, pkVal);
                setTimeout(() => _render(state, container), 800);
            }
        });
    });
}

// ---------------------------------------------------------------------------
// Main render dispatcher
// ---------------------------------------------------------------------------

function _render(state, container) {
    switch (state.view) {
        case 'types':   _renderTypesView(state, container); break;
        case 'objects':  _renderObjectsView(state, container); break;
        case 'detail':   _renderDetailView(state, container); break;
    }
}

// ---------------------------------------------------------------------------
// Panel definition
// ---------------------------------------------------------------------------

export const OntologyExplorerPanelDef = {
    id: 'ontology-explorer',
    title: 'ONTOLOGY EXPLORER',
    defaultPosition: { x: 40, y: 80 },
    defaultSize: { w: 420, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'ontology-explorer-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;background:#0a0a1a';

        const content = document.createElement('div');
        content.style.cssText = 'flex:1;overflow-y:auto';
        el.appendChild(content);

        const state = _createState();
        el._ontoState = state;

        // Initial load
        (async () => {
            state.types = await _fetchTypes();
            _render(state, content);
        })();

        return el;
    },

    destroy(el) {
        const state = el._ontoState;
        if (state && state.timer) {
            clearInterval(state.timer);
            state.timer = null;
        }
    },
};
