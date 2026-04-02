// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Enrichment Panel — target intelligence enrichment lookup and forced re-enrichment.
// Shows enrichment results for any target, allows forced re-enrichment.
// Backend: GET /api/targets/{id}/enrichments, POST /api/targets/{id}/enrich
// Works with any tracked target (BLE, WiFi, camera, mesh).

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchTargets() {
    try {
        const resp = await fetch('/api/targets');
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.targets || data || [];
    } catch {
        return [];
    }
}

async function _fetchEnrichments(targetId) {
    try {
        const resp = await fetch(`/api/targets/${encodeURIComponent(targetId)}/enrichments`);
        if (!resp.ok) return { target_id: targetId, enrichments: [], error: `HTTP ${resp.status}` };
        return await resp.json();
    } catch (e) {
        return { target_id: targetId, enrichments: [], error: e.message };
    }
}

async function _forceEnrich(targetId) {
    try {
        const resp = await fetch(`/api/targets/${encodeURIComponent(targetId)}/enrich`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        if (!resp.ok) return { target_id: targetId, enrichments: [], error: `HTTP ${resp.status}` };
        return await resp.json();
    } catch (e) {
        return { target_id: targetId, enrichments: [], error: e.message };
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _sourceIcon(source) {
    const icons = {
        mac_lookup: 'MAC',
        oui: 'OUI',
        geo: 'GEO',
        dns: 'DNS',
        whois: 'WHOIS',
        reputation: 'REP',
        threat_intel: 'INTEL',
    };
    return icons[(source || '').toLowerCase()] || (source || 'SRC').toUpperCase().substring(0, 5);
}

function _sourceColor(source) {
    const colors = {
        mac_lookup: CYAN,
        oui: CYAN,
        geo: GREEN,
        dns: YELLOW,
        whois: YELLOW,
        reputation: MAGENTA,
        threat_intel: MAGENTA,
    };
    return colors[(source || '').toLowerCase()] || DIM;
}

function _confidenceBadge(confidence) {
    const pct = Math.round((confidence || 0) * 100);
    const color = pct >= 70 ? GREEN : pct >= 40 ? YELLOW : MAGENTA;
    return `<span style="color:${color};font-size:9px;font-family:monospace;">${pct}%</span>`;
}

// ---------------------------------------------------------------------------
// Render: target list for selection
// ---------------------------------------------------------------------------

function _targetSelector(targets) {
    if (!targets || targets.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No targets available. Start demo mode or connect sensors.</div>`;
    }

    return targets.slice(0, 50).map(t => {
        const tid = typeof t === 'string' ? t : (t.target_id || t.id || '--');
        const name = typeof t === 'string' ? '' : (t.name || '');
        const assetType = typeof t === 'string' ? '' : (t.asset_type || t.type || '');
        const alliance = typeof t === 'string' ? '' : (t.alliance || '');
        const allianceColor = alliance === 'hostile' ? MAGENTA : alliance === 'friendly' ? GREEN : DIM;

        return `<div class="enrichment-target-item" data-target-id="${_esc(tid)}"
                     style="display:flex;align-items:center;gap:6px;padding:4px 6px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.03);">
            <span class="mono" style="color:${CYAN};font-size:10px;min-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(tid)}</span>
            <span style="color:#999;font-size:10px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <span style="color:#555;font-size:9px;">${_esc(assetType)}</span>
            <span style="color:${allianceColor};font-size:9px;">${_esc(alliance)}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Render: enrichment results
// ---------------------------------------------------------------------------

function _enrichmentResults(data) {
    if (!data) return '';
    if (data.error) return `<div style="color:${MAGENTA};padding:8px;font-size:10px;">${_esc(data.error)}</div>`;

    const enrichments = data.enrichments || [];
    const cached = data.cached;

    if (enrichments.length === 0) {
        return `<div style="color:#555;padding:12px;text-align:center;font-size:10px;">
            No enrichment data available for this target.
            ${cached ? '<br><span style="color:#444;">Cached result</span>' : ''}
        </div>`;
    }

    const cacheLabel = cached ? `<span style="color:#444;font-size:8px;border:1px solid #333;padding:0 3px;border-radius:2px;">CACHED</span>` : '';

    const items = enrichments.map(e => {
        const source = e.source || 'unknown';
        const color = _sourceColor(source);
        const icon = _sourceIcon(source);
        const confidence = e.confidence || 0;
        const dataObj = e.data || {};
        const dataEntries = Object.entries(dataObj).slice(0, 8);

        let dataHtml = '';
        if (dataEntries.length > 0) {
            dataHtml = `<div style="margin-top:3px;padding-left:8px;">
                ${dataEntries.map(([k, v]) => {
                    const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
                    return `<div style="font-size:9px;display:flex;gap:4px;">
                        <span style="color:#555;min-width:80px;">${_esc(k)}</span>
                        <span style="color:#999;">${_esc(val)}</span>
                    </div>`;
                }).join('')}
            </div>`;
        }

        return `<div style="border:1px solid ${BORDER};padding:6px;margin-bottom:4px;border-left:3px solid ${color};">
            <div style="display:flex;align-items:center;gap:6px;">
                <span style="color:${color};font-size:9px;border:1px solid ${color};padding:1px 4px;border-radius:2px;font-family:monospace;">${icon}</span>
                <span style="color:#ccc;font-size:10px;flex:1;">${_esc(source)}</span>
                ${_confidenceBadge(confidence)}
            </div>
            ${dataHtml}
        </div>`;
    }).join('');

    return `<div style="margin-bottom:4px;display:flex;align-items:center;gap:6px;">
        <span style="font-size:10px;color:${GREEN};text-transform:uppercase;letter-spacing:0.5px;">${enrichments.length} ENRICHMENTS</span>
        ${cacheLabel}
    </div>${items}`;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const EnrichmentPanelDef = {
    id: 'enrichment',
    title: 'ENRICHMENT',
    defaultPosition: { x: 340, y: 120 },
    defaultSize: { w: 460, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'enrichment-panel';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="color:${MAGENTA};font-size:12px;font-weight:bold;">TARGET ENRICHMENT</span>
                <span data-bind="enrich-timestamp" style="font-size:10px;color:#555;font-family:monospace;margin-left:auto;">--</span>
            </div>

            <div style="border:1px solid ${BORDER};padding:6px;margin-bottom:8px;">
                <div style="display:flex;gap:6px;align-items:center;">
                    <input type="text" data-bind="enrich-target-id" placeholder="Enter target ID (e.g. ble_aabbccddeeff)"
                           style="flex:1;background:#0a0a0f;border:1px solid ${BORDER};color:#ccc;padding:4px 8px;font-size:10px;font-family:monospace;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="lookup-enrichment" style="font-size:0.42rem;">LOOKUP</button>
                    <button class="panel-action-btn" data-action="force-enrich" style="font-size:0.42rem;">FORCE</button>
                </div>
            </div>

            <div data-bind="enrich-results" style="margin-bottom:8px;">
                <div style="color:#555;padding:8px;text-align:center;font-size:10px;">Enter a target ID above or select from the list below.</div>
            </div>

            <div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
                <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
                    <span style="font-size:10px;color:${CYAN};text-transform:uppercase;letter-spacing:0.5px;">AVAILABLE TARGETS</span>
                    <button class="panel-action-btn" data-action="refresh-targets" style="font-size:0.42rem;margin-left:auto;">REFRESH</button>
                </div>
                <div data-bind="enrich-target-list" style="max-height:200px;overflow-y:auto;">
                    <div style="color:#555;padding:8px;text-align:center;font-size:10px;">Loading targets...</div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const resultsEl = bodyEl.querySelector('[data-bind="enrich-results"]');
        const targetListEl = bodyEl.querySelector('[data-bind="enrich-target-list"]');
        const timestampEl = bodyEl.querySelector('[data-bind="enrich-timestamp"]');
        const targetIdInput = bodyEl.querySelector('[data-bind="enrich-target-id"]');
        const lookupBtn = bodyEl.querySelector('[data-action="lookup-enrichment"]');
        const forceBtn = bodyEl.querySelector('[data-action="force-enrich"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-targets"]');

        async function loadTargetList() {
            const targets = await _fetchTargets();
            if (targetListEl) {
                targetListEl.innerHTML = _targetSelector(targets);

                // Wire click handlers
                targetListEl.querySelectorAll('.enrichment-target-item').forEach(item => {
                    item.addEventListener('click', () => {
                        const tid = item.dataset.targetId;
                        if (targetIdInput) targetIdInput.value = tid;
                        lookupEnrichment(tid);
                    });
                });
            }
        }

        async function lookupEnrichment(targetId) {
            if (!targetId) {
                if (resultsEl) resultsEl.innerHTML = `<div style="color:${MAGENTA};font-size:10px;">Enter a target ID</div>`;
                return;
            }
            if (resultsEl) resultsEl.innerHTML = `<div style="color:#555;padding:8px;text-align:center;">Looking up enrichments for ${_esc(targetId)}...</div>`;

            const data = await _fetchEnrichments(targetId);
            if (resultsEl) resultsEl.innerHTML = _enrichmentResults(data);
            if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
        }

        async function forceEnrichTarget(targetId) {
            if (!targetId) {
                if (resultsEl) resultsEl.innerHTML = `<div style="color:${MAGENTA};font-size:10px;">Enter a target ID</div>`;
                return;
            }
            if (resultsEl) resultsEl.innerHTML = `<div style="color:${YELLOW};padding:8px;text-align:center;">Forcing re-enrichment for ${_esc(targetId)}...</div>`;

            const data = await _forceEnrich(targetId);
            if (resultsEl) resultsEl.innerHTML = _enrichmentResults(data);
            if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
        }

        // Wire buttons
        if (lookupBtn) {
            lookupBtn.addEventListener('click', () => {
                const tid = targetIdInput ? targetIdInput.value.trim() : '';
                lookupEnrichment(tid);
            });
        }

        if (forceBtn) {
            forceBtn.addEventListener('click', () => {
                const tid = targetIdInput ? targetIdInput.value.trim() : '';
                forceEnrichTarget(tid);
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', loadTargetList);
        }

        // Enter key in input triggers lookup
        if (targetIdInput) {
            targetIdInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    lookupEnrichment(targetIdInput.value.trim());
                }
                e.stopPropagation(); // Prevent keyboard shortcuts from firing
            });
        }

        // Initial load
        loadTargetList();
    },

    unmount(_bodyEl, _panel) {
        // No timers to clean up — enrichment is on-demand
    },
};
