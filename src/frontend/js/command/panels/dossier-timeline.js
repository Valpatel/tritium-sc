// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Dossier Timeline Panel — visual chronological timeline of all signals
// for a selected dossier. Source-colored markers, click for details.
// Fetches from /api/dossiers/{id} and renders a scrollable timeline.

import { _esc, _timeAgo } from '/lib/utils.js';

// Source -> color mapping for timeline markers
const SOURCE_COLORS = {
    ble: '#00f0ff',       // cyan
    wifi: '#05ffa1',      // green
    yolo: '#ff2a6d',      // magenta
    camera: '#ff2a6d',
    mesh: '#fcee0a',      // yellow
    meshtastic: '#fcee0a',
    correlator: '#ff8c00', // orange
    manual: '#e0e0e0',    // white
    mqtt: '#9b59b6',      // purple
    acoustic: '#e74c3c',  // red
    enrichment: '#3498db', // blue
};

function _sourceColor(source) {
    return SOURCE_COLORS[source] || '#888';
}

function _formatTimestamp(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

function _formatTime(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString(undefined, {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

export const DossierTimelinePanelDef = {
    id: 'dossier-timeline',
    title: 'DOSSIER TIMELINE',
    defaultPosition: { x: 740, y: 16 },
    defaultSize: { w: 520, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'dtl-root';
        el.innerHTML = `
            <div class="dtl-selector">
                <label class="dtl-label">DOSSIER:</label>
                <select class="dtl-select" data-bind="dtl-dossier-select">
                    <option value="">Select a dossier...</option>
                </select>
                <button class="panel-action-btn panel-action-btn-primary dtl-refresh-btn"
                        data-action="dtl-refresh" title="Refresh">&#x21bb;</button>
            </div>
            <div class="dtl-legend" data-bind="dtl-legend"></div>
            <div class="dtl-timeline-wrap" data-bind="dtl-timeline">
                <div class="dtl-placeholder">Select a dossier to view its signal timeline</div>
            </div>
            <div class="dtl-detail-pane" data-bind="dtl-detail">
                <div class="dtl-detail-placeholder">Click a signal marker for details</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const selectEl = bodyEl.querySelector('[data-bind="dtl-dossier-select"]');
        const legendEl = bodyEl.querySelector('[data-bind="dtl-legend"]');
        const timelineEl = bodyEl.querySelector('[data-bind="dtl-timeline"]');
        const detailEl = bodyEl.querySelector('[data-bind="dtl-detail"]');
        const refreshBtn = bodyEl.querySelector('[data-action="dtl-refresh"]');

        let currentDossier = null;

        // Build legend
        const uniqueSources = Object.keys(SOURCE_COLORS);
        legendEl.innerHTML = uniqueSources.map(src =>
            `<span class="dtl-legend-item">
                <span class="dtl-legend-dot" style="background:${SOURCE_COLORS[src]}"></span>
                <span class="dtl-legend-name">${_esc(src)}</span>
            </span>`
        ).join('');

        // Load dossier list for selector
        async function loadDossierList() {
            try {
                const resp = await fetch('/api/dossiers?limit=100&sort=last_seen');
                if (!resp.ok) return;
                const data = await resp.json();
                const dossiers = data.dossiers || [];
                selectEl.innerHTML = '<option value="">Select a dossier...</option>' +
                    dossiers.map(d => {
                        const name = _esc(d.name || d.dossier_id.substring(0, 8));
                        const id = _esc(d.dossier_id);
                        return `<option value="${id}">${name}</option>`;
                    }).join('');
            } catch (e) {
                // ignore
            }
        }

        // Load and render timeline for a dossier
        async function loadTimeline(dossierId) {
            if (!dossierId) {
                timelineEl.innerHTML = '<div class="dtl-placeholder">Select a dossier to view its signal timeline</div>';
                detailEl.innerHTML = '<div class="dtl-detail-placeholder">Click a signal marker for details</div>';
                currentDossier = null;
                return;
            }

            timelineEl.innerHTML = '<div class="dtl-placeholder"><span class="panel-spinner"></span> Loading...</div>';

            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}`);
                if (!resp.ok) {
                    timelineEl.innerHTML = '<div class="dtl-placeholder">Failed to load dossier</div>';
                    return;
                }
                const dossier = await resp.json();
                currentDossier = dossier;
                renderTimeline(dossier);
            } catch (e) {
                timelineEl.innerHTML = '<div class="dtl-placeholder">Network error</div>';
            }
        }

        function renderTimeline(dossier) {
            const signals = dossier.signals || [];
            const enrichments = dossier.enrichments || [];

            if (signals.length === 0 && enrichments.length === 0) {
                timelineEl.innerHTML = '<div class="dtl-placeholder">No signals recorded</div>';
                return;
            }

            // Combine signals and enrichments into unified timeline items
            const items = [];
            for (const s of signals) {
                items.push({
                    type: 'signal',
                    timestamp: s.timestamp || 0,
                    source: s.source || 'unknown',
                    signal_type: s.signal_type || '',
                    confidence: s.confidence || 0,
                    data: s.data || {},
                    raw: s,
                });
            }
            for (const e of enrichments) {
                items.push({
                    type: 'enrichment',
                    timestamp: e.timestamp || 0,
                    source: e.provider || 'enrichment',
                    signal_type: e.enrichment_type || 'enrichment',
                    confidence: 1.0,
                    data: e.data || {},
                    raw: e,
                });
            }

            // Sort chronologically
            items.sort((a, b) => a.timestamp - b.timestamp);

            // Render vertical timeline
            let html = '<div class="dtl-timeline-inner">';

            // Header showing dossier name + total count
            html += `<div class="dtl-header">
                <span class="dtl-header-name">${_esc(dossier.name || 'Unknown')}</span>
                <span class="dtl-header-count">${items.length} events</span>
            </div>`;

            // Timeline axis
            html += '<div class="dtl-axis">';
            for (let i = 0; i < items.length; i++) {
                const item = items[i];
                const color = _sourceColor(item.source);
                const isLast = i === items.length - 1;
                const confPct = Math.round(item.confidence * 100);

                html += `<div class="dtl-event" data-idx="${i}">
                    <div class="dtl-event-marker-col">
                        <div class="dtl-event-dot" style="background:${color};box-shadow:0 0 6px ${color}"></div>
                        ${!isLast ? '<div class="dtl-event-line"></div>' : ''}
                    </div>
                    <div class="dtl-event-content">
                        <div class="dtl-event-header">
                            <span class="dtl-event-source" style="color:${color}">${_esc(item.source)}</span>
                            <span class="dtl-event-type">${_esc(item.signal_type)}</span>
                            <span class="dtl-event-conf">${confPct}%</span>
                        </div>
                        <div class="dtl-event-time mono">${_formatTimestamp(item.timestamp)}</div>
                    </div>
                </div>`;
            }
            html += '</div></div>';

            timelineEl.innerHTML = html;

            // Wire click handlers on events
            timelineEl.querySelectorAll('.dtl-event').forEach(ev => {
                ev.addEventListener('click', () => {
                    const idx = parseInt(ev.dataset.idx, 10);
                    if (idx >= 0 && idx < items.length) {
                        // Highlight selected
                        timelineEl.querySelectorAll('.dtl-event').forEach(e =>
                            e.classList.toggle('dtl-event-selected', e === ev));
                        showDetail(items[idx]);
                    }
                });
            });
        }

        function showDetail(item) {
            const color = _sourceColor(item.source);
            const confPct = Math.round(item.confidence * 100);

            let dataHtml = '';
            if (item.data && typeof item.data === 'object') {
                const entries = Object.entries(item.data).slice(0, 12);
                dataHtml = entries.map(([k, v]) => {
                    let val = v;
                    if (typeof v === 'object' && v !== null) {
                        val = JSON.stringify(v).substring(0, 80);
                    }
                    return `<div class="dtl-detail-kv">
                        <span class="dtl-detail-key">${_esc(k)}</span>
                        <span class="dtl-detail-val">${_esc(String(val))}</span>
                    </div>`;
                }).join('');
            }

            detailEl.innerHTML = `
                <div class="dtl-detail-content">
                    <div class="dtl-detail-header">
                        <span class="dtl-detail-dot" style="background:${color}"></span>
                        <span class="dtl-detail-source" style="color:${color}">${_esc(item.source)}</span>
                        <span class="dtl-detail-type">${_esc(item.signal_type)}</span>
                    </div>
                    <div class="dtl-detail-row">
                        <span class="dtl-detail-label">Time:</span>
                        <span class="mono">${_formatTimestamp(item.timestamp)}</span>
                    </div>
                    <div class="dtl-detail-row">
                        <span class="dtl-detail-label">Confidence:</span>
                        <span>${confPct}%</span>
                    </div>
                    <div class="dtl-detail-row">
                        <span class="dtl-detail-label">Type:</span>
                        <span>${_esc(item.type)}</span>
                    </div>
                    ${dataHtml ? `
                    <div class="dtl-detail-section">
                        <div class="dtl-detail-section-title">DATA</div>
                        ${dataHtml}
                    </div>
                    ` : ''}
                </div>
            `;
        }

        // Event wiring
        selectEl.addEventListener('change', () => {
            loadTimeline(selectEl.value);
        });

        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                loadDossierList();
                if (selectEl.value) {
                    loadTimeline(selectEl.value);
                }
            });
        }

        // Initial load
        loadDossierList();

        // Auto-refresh every 30s
        const refreshInterval = setInterval(() => {
            if (selectEl.value) {
                loadTimeline(selectEl.value);
            }
        }, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};

// -----------------------------------------------------------------------
// Inject panel-specific styles
// -----------------------------------------------------------------------
const style = document.createElement('style');
style.textContent = `
.dtl-root {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    gap: 4px;
}

.dtl-selector {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 8px;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
}

.dtl-label {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    font-weight: 700;
    color: #00f0ff;
    letter-spacing: 0.08em;
    white-space: nowrap;
}

.dtl-select {
    flex: 1;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.3);
    color: #e0e0e0;
    padding: 3px 6px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    border-radius: 2px;
    cursor: pointer;
}

.dtl-select:focus {
    border-color: #00f0ff;
}

.dtl-refresh-btn {
    font-size: 0.8rem;
    padding: 2px 6px;
}

.dtl-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    padding: 2px 8px;
}

.dtl-legend-item {
    display: flex;
    align-items: center;
    gap: 3px;
}

.dtl-legend-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}

.dtl-legend-name {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.45rem;
    color: rgba(224, 224, 224, 0.5);
    text-transform: uppercase;
}

.dtl-timeline-wrap {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 4px 8px;
}

.dtl-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: rgba(224, 224, 224, 0.3);
    font-size: 0.7rem;
}

.dtl-timeline-inner {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.dtl-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
    margin-bottom: 4px;
    border-bottom: 1px solid rgba(0, 240, 255, 0.1);
}

.dtl-header-name {
    font-size: 0.75rem;
    font-weight: 700;
    color: #e0e0e0;
}

.dtl-header-count {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    color: rgba(0, 240, 255, 0.6);
}

.dtl-axis {
    display: flex;
    flex-direction: column;
}

.dtl-event {
    display: flex;
    gap: 8px;
    cursor: pointer;
    padding: 2px 4px;
    border-radius: 2px;
    transition: background 0.15s;
}

.dtl-event:hover {
    background: rgba(0, 240, 255, 0.04);
}

.dtl-event-selected {
    background: rgba(0, 240, 255, 0.1);
}

.dtl-event-marker-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 14px;
    flex-shrink: 0;
}

.dtl-event-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 3px;
}

.dtl-event-line {
    flex: 1;
    width: 2px;
    background: rgba(0, 240, 255, 0.12);
    min-height: 12px;
}

.dtl-event-content {
    flex: 1;
    min-width: 0;
    padding-bottom: 6px;
}

.dtl-event-header {
    display: flex;
    gap: 6px;
    align-items: center;
}

.dtl-event-source {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    font-weight: 700;
    text-transform: uppercase;
}

.dtl-event-type {
    font-size: 0.6rem;
    color: #e0e0e0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dtl-event-conf {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.4);
}

.dtl-event-time {
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.35);
    margin-top: 1px;
}

/* Detail pane */
.dtl-detail-pane {
    max-height: 140px;
    overflow-y: auto;
    border-top: 1px solid rgba(0, 240, 255, 0.15);
    padding: 6px 8px;
}

.dtl-detail-placeholder {
    font-size: 0.6rem;
    color: rgba(224, 224, 224, 0.3);
    text-align: center;
    padding: 8px;
}

.dtl-detail-content {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.dtl-detail-header {
    display: flex;
    align-items: center;
    gap: 6px;
}

.dtl-detail-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.dtl-detail-source {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
}

.dtl-detail-type {
    font-size: 0.6rem;
    color: #e0e0e0;
}

.dtl-detail-row {
    display: flex;
    gap: 8px;
    font-size: 0.6rem;
}

.dtl-detail-label {
    color: rgba(0, 240, 255, 0.6);
    min-width: 70px;
}

.dtl-detail-section {
    margin-top: 4px;
}

.dtl-detail-section-title {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    font-weight: 700;
    color: #00f0ff;
    letter-spacing: 0.08em;
    border-bottom: 1px solid rgba(0, 240, 255, 0.1);
    padding-bottom: 2px;
    margin-bottom: 4px;
}

.dtl-detail-kv {
    display: flex;
    gap: 6px;
    font-size: 0.55rem;
    padding: 1px 0;
}

.dtl-detail-key {
    color: rgba(0, 240, 255, 0.5);
    min-width: 80px;
    flex-shrink: 0;
}

.dtl-detail-val {
    color: #e0e0e0;
    word-break: break-all;
}

/* Scrollbar */
.dtl-timeline-wrap::-webkit-scrollbar,
.dtl-detail-pane::-webkit-scrollbar {
    width: 4px;
}

.dtl-timeline-wrap::-webkit-scrollbar-track,
.dtl-detail-pane::-webkit-scrollbar-track {
    background: transparent;
}

.dtl-timeline-wrap::-webkit-scrollbar-thumb,
.dtl-detail-pane::-webkit-scrollbar-thumb {
    background: rgba(0, 240, 255, 0.2);
    border-radius: 2px;
}
`;
document.head.appendChild(style);
