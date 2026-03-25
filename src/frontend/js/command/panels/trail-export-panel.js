// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Trail Export Panel
// Download target movement trails as GPX or KML files for
// post-analysis in Google Earth, ATAK, or any GIS application.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


let _targets = [];
let _refreshTimer = null;

async function _fetchTargets() {
    try {
        const resp = await fetch('/api/targets');
        if (!resp.ok) return [];
        const data = await resp.json();
        return (data.targets || []).filter(t => {
            // Only show targets that have position data
            const hasPos = (t.lat && t.lng) || (t.position && (t.position.x || t.position.y));
            return hasPos;
        });
    } catch (_) {
        return [];
    }
}

function _downloadFile(url, filename) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function _renderTargetList(el) {
    const listEl = el.querySelector('[data-bind="trail-target-list"]');
    if (!listEl) return;

    if (_targets.length === 0) {
        listEl.innerHTML = '<li class="panel-empty">No targets with position data</li>';
        return;
    }

    listEl.innerHTML = _targets.map(t => {
        const tid = _esc(t.target_id || t.id || 'unknown');
        const name = _esc(t.name || t.target_id || t.id || 'Unknown');
        const alliance = t.alliance || 'unknown';
        const allianceColor = alliance === 'hostile' ? 'var(--magenta)' :
                              alliance === 'friendly' ? 'var(--green)' : 'var(--dim)';
        const source = _esc(t.source || '');
        const classification = _esc(t.classification || t.asset_type || '');

        return `
            <li class="panel-list-item trail-export-item" data-target-id="${tid}">
                <div class="trail-export-info">
                    <span class="trail-export-name mono" style="color:var(--cyan)">${name}</span>
                    <span class="trail-export-meta mono" style="font-size:0.5rem; color:${allianceColor}">
                        ${alliance.toUpperCase()} ${source ? '/ ' + source : ''} ${classification ? '/ ' + classification : ''}
                    </span>
                </div>
                <div class="trail-export-actions">
                    <button class="panel-action-btn panel-action-btn-sm" data-action="trail-gpx" data-tid="${tid}" title="Download GPX">GPX</button>
                    <button class="panel-action-btn panel-action-btn-sm" data-action="trail-kml" data-tid="${tid}" title="Download KML">KML</button>
                </div>
            </li>
        `;
    }).join('');
}

async function _refresh(el) {
    _targets = await _fetchTargets();
    _renderTargetList(el);
}


export const TrailExportPanelDef = {
    id: 'trail-export',
    title: 'TRAIL EXPORT',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 380, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'trail-export-inner';
        el.innerHTML = `
            <div class="trail-export-toolbar">
                <button class="panel-action-btn" data-action="trail-refresh">REFRESH</button>
                <div class="trail-export-options" style="display:flex; gap:6px; align-items:center;">
                    <label class="mono" style="font-size:0.5rem; color:var(--dim)">
                        <input type="checkbox" data-bind="trail-simplify"> SIMPLIFY
                    </label>
                </div>
            </div>
            <div class="trail-export-time-filter" style="display:flex; gap:6px; margin:4px 0;">
                <input type="datetime-local" data-bind="trail-start" class="trail-time-input" placeholder="Start" title="Start time filter">
                <input type="datetime-local" data-bind="trail-end" class="trail-time-input" placeholder="End" title="End time filter">
            </div>
            <ul class="panel-list trail-target-list" data-bind="trail-target-list">
                <li class="panel-empty">Loading targets...</li>
            </ul>
        `;

        // Event delegation for buttons
        el.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;

            const action = btn.dataset.action;

            if (action === 'trail-refresh') {
                _refresh(el);
                return;
            }

            if (action === 'trail-gpx' || action === 'trail-kml') {
                const tid = btn.dataset.tid;
                const format = action === 'trail-gpx' ? 'gpx' : 'kml';
                const simplify = el.querySelector('[data-bind="trail-simplify"]')?.checked || false;
                const startInput = el.querySelector('[data-bind="trail-start"]');
                const endInput = el.querySelector('[data-bind="trail-end"]');

                let url = `/api/targets/${encodeURIComponent(tid)}/trail/${format}?`;
                if (simplify) url += 'simplify=true&';
                if (startInput && startInput.value) {
                    url += `start_time=${encodeURIComponent(new Date(startInput.value).toISOString())}&`;
                }
                if (endInput && endInput.value) {
                    url += `end_time=${encodeURIComponent(new Date(endInput.value).toISOString())}&`;
                }

                const safeName = tid.replace(/[/\\]/g, '_');
                _downloadFile(url, `${safeName}_trail.${format}`);
                EventBus.emit('toast:show', {
                    message: `Downloading ${format.toUpperCase()} for ${tid}`,
                    type: 'info',
                });
            }
        });

        // Initial load
        _refresh(el);

        // Auto-refresh every 30s
        _refreshTimer = setInterval(() => _refresh(el), 30000);

        return el;
    },

    destroy() {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
    },
};
