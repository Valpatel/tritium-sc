// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Dossier Panel — persistent entity intelligence browser
// Split view: dossier list (left) + detail view (right).
// Fetches from /api/dossiers, /api/dossiers/search, /api/dossiers/{id}.
// Supports filtering, sorting, tags, notes, merge, position trail mini-map.

import { EventBus } from '../events.js';
import { _esc, _timeAgo } from '../panel-utils.js';



function _formatTimestamp(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

// Threat level -> color
const THREAT_COLORS = {
    none: '#888',
    low: '#05ffa1',
    medium: '#fcee0a',
    high: '#ff8c00',
    critical: '#ff2a6d',
};

// Entity type badges
const TYPE_BADGES = {
    person: { label: 'PER', color: '#00f0ff' },
    vehicle: { label: 'VEH', color: '#fcee0a' },
    device: { label: 'DEV', color: '#05ffa1' },
    animal: { label: 'ANM', color: '#ff8c00' },
    unknown: { label: 'UNK', color: '#888' },
};

// Source icons (Unicode)
const SOURCE_ICONS = {
    ble: '\u{1F4F6}',    // antenna
    wifi: '\u{1F4F6}',
    yolo: '\u{1F441}',   // eye
    mesh: '\u{1F517}',   // link
    manual: '\u{270D}',  // writing hand
    mqtt: '\u{1F4E1}',   // satellite
};

export const DossiersPanelDef = {
    id: 'dossiers',
    title: 'DOSSIERS',
    defaultPosition: { x: 16, y: 16 },
    defaultSize: { w: 720, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'dossier-panel-root';
        el.innerHTML = `
            <div class="dossier-list-pane">
                <div class="dossier-search-bar">
                    <input type="text" class="dossier-search-input" data-bind="dossier-query"
                           placeholder="Search dossiers..." spellcheck="false">
                </div>
                <div class="dossier-filters">
                    <select class="dossier-filter-select" data-bind="dossier-entity-type">
                        <option value="">All Types</option>
                        <option value="person">Person</option>
                        <option value="vehicle">Vehicle</option>
                        <option value="device">Device</option>
                        <option value="animal">Animal</option>
                        <option value="unknown">Unknown</option>
                    </select>
                    <select class="dossier-filter-select" data-bind="dossier-threat">
                        <option value="">All Threats</option>
                        <option value="none">None</option>
                        <option value="low">Low</option>
                        <option value="medium">Medium</option>
                        <option value="high">High</option>
                        <option value="critical">Critical</option>
                    </select>
                    <select class="dossier-filter-select" data-bind="dossier-alliance">
                        <option value="">All Alliances</option>
                        <option value="friendly">Friendly</option>
                        <option value="hostile">Hostile</option>
                        <option value="unknown">Unknown</option>
                    </select>
                    <select class="dossier-filter-select" data-bind="dossier-sort">
                        <option value="last_seen">Last Seen</option>
                        <option value="confidence">Confidence</option>
                        <option value="signals">Signals</option>
                    </select>
                </div>
                <ul class="dossier-list" data-bind="dossier-list" role="listbox">
                    <li class="dossier-empty">Loading dossiers...</li>
                </ul>
            </div>
            <div class="dossier-detail-pane" data-bind="dossier-detail">
                <div class="dossier-detail-placeholder">Select a dossier to view details</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const queryInput = bodyEl.querySelector('[data-bind="dossier-query"]');
        const entityTypeSelect = bodyEl.querySelector('[data-bind="dossier-entity-type"]');
        const threatSelect = bodyEl.querySelector('[data-bind="dossier-threat"]');
        const allianceSelect = bodyEl.querySelector('[data-bind="dossier-alliance"]');
        const sortSelect = bodyEl.querySelector('[data-bind="dossier-sort"]');
        const listEl = bodyEl.querySelector('[data-bind="dossier-list"]');
        const detailEl = bodyEl.querySelector('[data-bind="dossier-detail"]');

        let allDossiers = [];
        let selectedId = null;
        let typeaheadTimer = null;

        // ---------------------------------------------------------------
        // List rendering
        // ---------------------------------------------------------------

        function renderList(dossiers) {
            allDossiers = dossiers;
            if (!listEl) return;
            if (!dossiers || dossiers.length === 0) {
                listEl.innerHTML = '<li class="dossier-empty">No dossiers found</li>';
                return;
            }
            listEl.innerHTML = dossiers.map(d => {
                const id = _esc(d.dossier_id || '');
                const name = _esc(d.name || 'Unknown');
                const etype = d.entity_type || 'unknown';
                const badge = TYPE_BADGES[etype] || TYPE_BADGES.unknown;
                const threat = d.threat_level || 'none';
                const threatColor = THREAT_COLORS[threat] || '#888';
                const sigCount = d.signal_count || 0;
                const lastSeen = _timeAgo(d.last_seen);
                const isSelected = d.dossier_id === selectedId;

                return `<li class="dossier-list-item${isSelected ? ' dossier-list-item-selected' : ''}"
                            data-dossier-id="${id}" role="option">
                    <div class="dossier-item-header">
                        <span class="dossier-type-badge" style="color:${badge.color};border-color:${badge.color}">${badge.label}</span>
                        <span class="dossier-item-name">${name}</span>
                        <span class="dossier-threat-dot" style="background:${threatColor}" title="${_esc(threat)}"></span>
                    </div>
                    <div class="dossier-item-meta mono">
                        <span>${sigCount} signals</span>
                        <span>${lastSeen}</span>
                    </div>
                </li>`;
            }).join('');

            listEl.querySelectorAll('.dossier-list-item').forEach(el => {
                el.addEventListener('click', () => {
                    const did = el.dataset.dossierId;
                    selectedId = did;
                    // Highlight selected
                    listEl.querySelectorAll('.dossier-list-item').forEach(li =>
                        li.classList.toggle('dossier-list-item-selected', li.dataset.dossierId === did));
                    loadDetail(did);
                });
            });
        }

        // ---------------------------------------------------------------
        // Detail rendering
        // ---------------------------------------------------------------

        async function loadDetail(dossierId) {
            if (!detailEl) return;
            detailEl.innerHTML = '<div class="dossier-detail-placeholder"><span class="panel-spinner"></span> Loading...</div>';

            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}`);
                if (!resp.ok) {
                    detailEl.innerHTML = '<div class="dossier-detail-placeholder">Failed to load dossier</div>';
                    return;
                }
                const d = await resp.json();
                if (d.error) {
                    detailEl.innerHTML = `<div class="dossier-detail-placeholder">${_esc(d.error)}</div>`;
                    return;
                }
                renderDetail(d);
            } catch (e) {
                detailEl.innerHTML = '<div class="dossier-detail-placeholder">Network error</div>';
            }
        }

        function renderDetail(d) {
            if (!detailEl) return;
            const etype = d.entity_type || 'unknown';
            const badge = TYPE_BADGES[etype] || TYPE_BADGES.unknown;
            const threat = d.threat_level || 'none';
            const threatColor = THREAT_COLORS[threat] || '#888';
            const confidence = Math.round((d.confidence || 0) * 100);
            const identifiers = d.identifiers || {};
            const signals = d.signals || [];
            const enrichments = d.enrichments || [];
            const positions = d.position_history || [];
            const tags = d.tags || [];
            const notes = d.notes || [];

            // Build identifiers chips
            const idChips = Object.entries(identifiers).map(([k, v]) =>
                `<span class="dossier-id-chip" title="Click to copy" data-copy="${_esc(v)}">${_esc(k)}: ${_esc(v)}</span>`
            ).join('') || '<span class="dossier-dim">None</span>';

            // Build signal timeline
            const signalHtml = signals.slice(0, 50).map(s => {
                const icon = SOURCE_ICONS[s.source] || '\u{1F4CB}';
                return `<div class="dossier-signal-row">
                    <span class="dossier-signal-icon">${icon}</span>
                    <span class="dossier-signal-type">${_esc(s.signal_type)}</span>
                    <span class="dossier-signal-source mono">${_esc(s.source)}</span>
                    <span class="dossier-signal-conf">${Math.round((s.confidence || 0) * 100)}%</span>
                    <span class="dossier-signal-time mono">${_formatTimestamp(s.timestamp)}</span>
                </div>`;
            }).join('') || '<div class="dossier-dim">No signals</div>';

            // Build enrichment cards
            const enrichHtml = enrichments.map(e => {
                const dataEntries = Object.entries(e.data || {}).slice(0, 5)
                    .map(([k, v]) => `<div class="dossier-enrich-kv"><span class="dossier-enrich-key">${_esc(k)}</span> ${_esc(String(v))}</div>`)
                    .join('');
                return `<div class="dossier-enrich-card">
                    <div class="dossier-enrich-header">${_esc(e.provider)} / ${_esc(e.enrichment_type)}</div>
                    ${dataEntries}
                </div>`;
            }).join('') || '<div class="dossier-dim">No enrichments</div>';

            // Tags
            const tagChips = tags.map(t =>
                `<span class="dossier-tag-chip">${_esc(t)}<button class="dossier-tag-remove" data-tag="${_esc(t)}">&times;</button></span>`
            ).join('');

            // Notes
            const notesHtml = notes.map((n, i) =>
                `<div class="dossier-note">${_esc(n)}</div>`
            ).join('') || '<div class="dossier-dim">No notes</div>';

            detailEl.innerHTML = `
                <div class="dossier-detail-scroll">
                    <div class="dossier-detail-header">
                        <div class="dossier-detail-title-row">
                            <span class="dossier-type-badge" style="color:${badge.color};border-color:${badge.color}">${badge.label}</span>
                            <span class="dossier-detail-name">${_esc(d.name)}</span>
                            <span class="dossier-threat-badge" style="background:${threatColor}">${_esc(threat).toUpperCase()}</span>
                        </div>
                        <div class="dossier-detail-uuid mono">${_esc(d.dossier_id)}</div>
                        <div class="dossier-confidence-bar-wrap">
                            <div class="dossier-confidence-label">Confidence: ${confidence}%</div>
                            <div class="dossier-confidence-track">
                                <div class="dossier-confidence-fill" style="width:${confidence}%"></div>
                            </div>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">IDENTIFIERS</div>
                        <div class="dossier-id-chips">${idChips}</div>
                    </div>

                    ${positions.length > 0 ? `
                    <div class="dossier-section">
                        <div class="dossier-section-title">POSITION TRAIL</div>
                        <canvas class="dossier-minimap" data-bind="dossier-minimap" width="280" height="140"></canvas>
                    </div>
                    ` : ''}

                    <div class="dossier-section">
                        <div class="dossier-section-title">SIGNAL HISTORY</div>
                        <canvas class="dossier-signal-chart" data-bind="dossier-signal-chart" width="400" height="100"></canvas>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">BEHAVIORAL PROFILE</div>
                        <div class="dossier-behavioral-profile" data-bind="dossier-behavioral">
                            <div class="dossier-dim">Loading behavioral profile...</div>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">LOCATION SUMMARY</div>
                        <div class="dossier-location-summary" data-bind="dossier-location">
                            <div class="dossier-dim">Loading location data...</div>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">CORRELATIONS</div>
                        <div class="dossier-correlations" data-bind="dossier-correlations">
                            <div class="dossier-dim">Loading correlations...</div>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">SIGNALS (${signals.length})</div>
                        <div class="dossier-signal-timeline">${signalHtml}</div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">ENRICHMENTS</div>
                        ${enrichHtml}
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">TAGS</div>
                        <div class="dossier-tags-wrap">
                            ${tagChips}
                            <div class="dossier-tag-add-row">
                                <input type="text" class="dossier-tag-input" data-bind="dossier-new-tag" placeholder="Add tag..." spellcheck="false">
                                <button class="panel-action-btn panel-action-btn-primary dossier-tag-add-btn" data-action="add-tag">+</button>
                            </div>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">NOTES</div>
                        <div class="dossier-notes-list">${notesHtml}</div>
                        <div class="dossier-note-add-row">
                            <input type="text" class="dossier-note-input" data-bind="dossier-new-note" placeholder="Add note..." spellcheck="false">
                            <button class="panel-action-btn panel-action-btn-primary dossier-note-add-btn" data-action="add-note">+</button>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <button class="dossier-merge-btn" data-action="merge">MERGE WITH ANOTHER DOSSIER</button>
                    </div>
                </div>
            `;

            // Wire up interactions
            _wireDetailEvents(detailEl, d, positions);
        }

        function _wireDetailEvents(container, dossier, positions) {
            const dossierId = dossier.dossier_id;

            // Copy chips
            container.querySelectorAll('.dossier-id-chip').forEach(chip => {
                chip.addEventListener('click', () => {
                    const val = chip.dataset.copy;
                    if (val && navigator.clipboard) {
                        navigator.clipboard.writeText(val).catch(() => {});
                        chip.classList.add('dossier-id-chip-copied');
                        setTimeout(() => chip.classList.remove('dossier-id-chip-copied'), 1200);
                    }
                });
            });

            // Tag remove
            container.querySelectorAll('.dossier-tag-remove').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const tag = btn.dataset.tag;
                    try {
                        await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/tags/${encodeURIComponent(tag)}`, {
                            method: 'DELETE',
                        });
                        loadDetail(dossierId);
                    } catch (_) {}
                });
            });

            // Tag add
            const tagInput = container.querySelector('[data-bind="dossier-new-tag"]');
            const tagAddBtn = container.querySelector('[data-action="add-tag"]');
            if (tagAddBtn && tagInput) {
                const addTag = async () => {
                    const tag = tagInput.value.trim();
                    if (!tag) return;
                    try {
                        await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/tags`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ tag }),
                        });
                        loadDetail(dossierId);
                    } catch (_) {}
                };
                tagAddBtn.addEventListener('click', addTag);
                tagInput.addEventListener('keydown', (e) => {
                    e.stopPropagation();
                    if (e.key === 'Enter') addTag();
                });
            }

            // Note add
            const noteInput = container.querySelector('[data-bind="dossier-new-note"]');
            const noteAddBtn = container.querySelector('[data-action="add-note"]');
            if (noteAddBtn && noteInput) {
                const addNote = async () => {
                    const note = noteInput.value.trim();
                    if (!note) return;
                    try {
                        await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/notes`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ note }),
                        });
                        loadDetail(dossierId);
                    } catch (_) {}
                };
                noteAddBtn.addEventListener('click', addNote);
                noteInput.addEventListener('keydown', (e) => {
                    e.stopPropagation();
                    if (e.key === 'Enter') addNote();
                });
            }

            // Merge
            const mergeBtn = container.querySelector('[data-action="merge"]');
            if (mergeBtn) {
                mergeBtn.addEventListener('click', () => _openMergeDialog(dossierId));
            }

            // Position trail mini-map
            const canvas = container.querySelector('[data-bind="dossier-minimap"]');
            if (canvas && positions.length > 0) {
                _drawPositionTrail(canvas, positions);
            }

            // Signal history sparkline chart
            const signalChart = container.querySelector('[data-bind="dossier-signal-chart"]');
            if (signalChart) {
                _fetchAndDrawSignalHistory(signalChart, dossierId);
            }

            // Behavioral profile
            const behavioralEl = container.querySelector('[data-bind="dossier-behavioral"]');
            if (behavioralEl) {
                _fetchAndRenderBehavioral(behavioralEl, dossierId);
            }

            // Location summary
            const locationEl = container.querySelector('[data-bind="dossier-location"]');
            if (locationEl) {
                _fetchAndRenderLocation(locationEl, dossierId);
            }

            // Correlations
            const correlationsEl = container.querySelector('[data-bind="dossier-correlations"]');
            if (correlationsEl) {
                _fetchAndRenderCorrelations(correlationsEl, dossier);
            }

            // Stop keyboard propagation on inputs
            container.querySelectorAll('input').forEach(inp => {
                inp.addEventListener('keydown', (e) => e.stopPropagation());
            });
        }

        // ---------------------------------------------------------------
        // Position trail mini-map
        // ---------------------------------------------------------------

        function _drawPositionTrail(canvas, positions) {
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            const pad = 16;

            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            if (positions.length < 2) {
                // Single dot
                ctx.fillStyle = '#00f0ff';
                ctx.beginPath();
                ctx.arc(w / 2, h / 2, 4, 0, Math.PI * 2);
                ctx.fill();
                return;
            }

            // Find bounds
            let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
            for (const p of positions) {
                if (p.x < minX) minX = p.x;
                if (p.x > maxX) maxX = p.x;
                if (p.y < minY) minY = p.y;
                if (p.y > maxY) maxY = p.y;
            }
            const rangeX = maxX - minX || 1;
            const rangeY = maxY - minY || 1;

            function toCanvas(px, py) {
                return [
                    pad + ((px - minX) / rangeX) * (w - 2 * pad),
                    pad + ((py - minY) / rangeY) * (h - 2 * pad),
                ];
            }

            // Draw connecting lines
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.3)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            const sorted = [...positions].sort((a, b) => a.timestamp - b.timestamp);
            const [sx, sy] = toCanvas(sorted[0].x, sorted[0].y);
            ctx.moveTo(sx, sy);
            for (let i = 1; i < sorted.length; i++) {
                const [cx, cy] = toCanvas(sorted[i].x, sorted[i].y);
                ctx.lineTo(cx, cy);
            }
            ctx.stroke();

            // Draw dots (older = dimmer, newest = brightest)
            for (let i = 0; i < sorted.length; i++) {
                const alpha = 0.3 + 0.7 * (i / (sorted.length - 1));
                const radius = i === sorted.length - 1 ? 4 : 2.5;
                const [cx, cy] = toCanvas(sorted[i].x, sorted[i].y);
                ctx.fillStyle = `rgba(0, 240, 255, ${alpha})`;
                ctx.beginPath();
                ctx.arc(cx, cy, radius, 0, Math.PI * 2);
                ctx.fill();
            }

            // Latest position label
            const [lx, ly] = toCanvas(sorted[sorted.length - 1].x, sorted[sorted.length - 1].y);
            ctx.fillStyle = '#00f0ff';
            ctx.font = '9px monospace';
            ctx.fillText('NOW', lx + 6, ly + 3);
        }

        // ---------------------------------------------------------------
        // Signal history sparkline chart
        // ---------------------------------------------------------------

        async function _fetchAndDrawSignalHistory(canvas, dossierId) {
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;

            // Draw loading state
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = 'rgba(224, 224, 224, 0.3)';
            ctx.font = '9px monospace';
            ctx.fillText('Loading signal history...', 10, h / 2);

            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/signal-history?limit=200`);
                if (!resp.ok) {
                    _drawEmptyChart(ctx, w, h, 'No signal data available');
                    return;
                }
                const data = await resp.json();
                const timeline = data.timeline || [];
                if (timeline.length === 0) {
                    _drawEmptyChart(ctx, w, h, 'No signal data available');
                    return;
                }
                _drawSignalSparkline(ctx, w, h, timeline);
            } catch (_) {
                _drawEmptyChart(ctx, w, h, 'Failed to load signal data');
            }
        }

        function _drawEmptyChart(ctx, w, h, msg) {
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);
            ctx.fillStyle = 'rgba(224, 224, 224, 0.25)';
            ctx.font = '9px monospace';
            ctx.textAlign = 'center';
            ctx.fillText(msg, w / 2, h / 2);
            ctx.textAlign = 'start';
        }

        function _drawSignalSparkline(ctx, w, h, timeline) {
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            const pad = { top: 14, right: 10, bottom: 18, left: 36 };
            const plotW = w - pad.left - pad.right;
            const plotH = h - pad.top - pad.bottom;

            // Extract RSSI values; filter for numeric rssi entries
            const points = timeline
                .filter(t => t.rssi != null || (t.data && t.data.rssi != null))
                .map(t => ({
                    ts: t.timestamp || 0,
                    rssi: t.rssi ?? (t.data && t.data.rssi) ?? -80,
                }))
                .sort((a, b) => a.ts - b.ts);

            if (points.length === 0) {
                _drawEmptyChart(ctx, w, h, 'No RSSI data in signal history');
                return;
            }

            // Find bounds
            let minRssi = Infinity, maxRssi = -Infinity;
            let minTs = Infinity, maxTs = -Infinity;
            for (const p of points) {
                if (p.rssi < minRssi) minRssi = p.rssi;
                if (p.rssi > maxRssi) maxRssi = p.rssi;
                if (p.ts < minTs) minTs = p.ts;
                if (p.ts > maxTs) maxTs = p.ts;
            }
            // Ensure some range
            if (maxRssi === minRssi) { maxRssi += 5; minRssi -= 5; }
            if (maxTs === minTs) maxTs = minTs + 60;

            const tsRange = maxTs - minTs;
            const rssiRange = maxRssi - minRssi;

            function toX(ts) { return pad.left + ((ts - minTs) / tsRange) * plotW; }
            function toY(rssi) { return pad.top + plotH - ((rssi - minRssi) / rssiRange) * plotH; }

            // Draw grid lines (horizontal)
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.08)';
            ctx.lineWidth = 0.5;
            for (let r = Math.ceil(minRssi / 10) * 10; r <= maxRssi; r += 10) {
                const y = toY(r);
                ctx.beginPath();
                ctx.moveTo(pad.left, y);
                ctx.lineTo(w - pad.right, y);
                ctx.stroke();

                // Y-axis label
                ctx.fillStyle = 'rgba(224, 224, 224, 0.3)';
                ctx.font = '7px monospace';
                ctx.textAlign = 'right';
                ctx.fillText(`${r}`, pad.left - 3, y + 3);
            }

            // Title
            ctx.fillStyle = '#00f0ff';
            ctx.font = '8px monospace';
            ctx.textAlign = 'left';
            ctx.fillText('RSSI (dBm) over time', pad.left, 10);

            // Time axis labels
            ctx.fillStyle = 'rgba(224, 224, 224, 0.3)';
            ctx.font = '7px monospace';
            ctx.textAlign = 'center';
            const startDate = new Date(minTs * 1000);
            const endDate = new Date(maxTs * 1000);
            const fmt = (d) => d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
            ctx.fillText(fmt(startDate), pad.left, h - 3);
            ctx.fillText(fmt(endDate), w - pad.right, h - 3);

            // Draw gradient fill under the sparkline
            const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            gradient.addColorStop(0, 'rgba(0, 240, 255, 0.15)');
            gradient.addColorStop(1, 'rgba(0, 240, 255, 0.01)');

            ctx.beginPath();
            ctx.moveTo(toX(points[0].ts), toY(points[0].rssi));
            for (let i = 1; i < points.length; i++) {
                ctx.lineTo(toX(points[i].ts), toY(points[i].rssi));
            }
            // Close path for fill
            ctx.lineTo(toX(points[points.length - 1].ts), pad.top + plotH);
            ctx.lineTo(toX(points[0].ts), pad.top + plotH);
            ctx.closePath();
            ctx.fillStyle = gradient;
            ctx.fill();

            // Draw sparkline
            ctx.beginPath();
            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 1.5;
            ctx.moveTo(toX(points[0].ts), toY(points[0].rssi));
            for (let i = 1; i < points.length; i++) {
                ctx.lineTo(toX(points[i].ts), toY(points[i].rssi));
            }
            ctx.stroke();

            // Draw dots at each data point (limit to avoid clutter)
            const step = Math.max(1, Math.floor(points.length / 40));
            for (let i = 0; i < points.length; i += step) {
                const x = toX(points[i].ts);
                const y = toY(points[i].rssi);
                const rssiColor = points[i].rssi > -50 ? '#05ffa1' : points[i].rssi > -70 ? '#fcee0a' : '#ff2a6d';
                ctx.fillStyle = rssiColor;
                ctx.beginPath();
                ctx.arc(x, y, 2, 0, Math.PI * 2);
                ctx.fill();
            }
            // Always draw last point
            if (points.length > 1) {
                const last = points[points.length - 1];
                const lx = toX(last.ts);
                const ly = toY(last.rssi);
                ctx.fillStyle = '#00f0ff';
                ctx.beginPath();
                ctx.arc(lx, ly, 3, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = '#00f0ff';
                ctx.font = '7px monospace';
                ctx.textAlign = 'left';
                ctx.fillText(`${last.rssi} dBm`, lx + 5, ly + 3);
            }

            ctx.textAlign = 'start';
        }

        // ---------------------------------------------------------------
        // Behavioral profile
        // ---------------------------------------------------------------

        async function _fetchAndRenderBehavioral(el, dossierId) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/behavioral-profile`);
                if (!resp.ok) { el.innerHTML = '<div class="dossier-dim">Behavioral data unavailable</div>'; return; }
                const p = await resp.json();
                _renderBehavioralProfile(el, p);
            } catch (_) {
                el.innerHTML = '<div class="dossier-dim">Failed to load behavioral profile</div>';
            }
        }

        function _renderBehavioralProfile(el, profile) {
            const pattern = profile.movement_pattern || 'unknown';
            const patternColors = {
                stationary: '#05ffa1', mobile: '#00f0ff', erratic: '#ff2a6d',
                patrol: '#fcee0a', unknown: '#888',
            };
            const patternColor = patternColors[pattern] || '#888';

            const avgSpeed = (profile.average_speed || 0).toFixed(1);
            const maxSpeed = (profile.max_speed || 0).toFixed(1);
            const signalCount = profile.signal_count || 0;
            const activeDuration = profile.active_duration_s || 0;
            const durationStr = activeDuration > 3600
                ? `${(activeDuration / 3600).toFixed(1)}h`
                : activeDuration > 60 ? `${Math.round(activeDuration / 60)}m` : `${activeDuration}s`;

            // Source breakdown chips
            const srcBreakdown = profile.source_breakdown || {};
            const srcChips = Object.entries(srcBreakdown).map(([src, count]) => {
                const icon = SOURCE_ICONS[src] || '\u{1F4CB}';
                return `<span class="dossier-src-chip">${icon} ${_esc(src)}: ${count}</span>`;
            }).join('') || '<span class="dossier-dim">No sources</span>';

            // RSSI stats
            const rssi = profile.rssi_stats || {};
            const rssiHtml = (rssi.min != null && rssi.max != null)
                ? `<div class="dossier-rssi-stats mono">
                    <span>Min: <span style="color:#ff2a6d">${rssi.min} dBm</span></span>
                    <span>Avg: <span style="color:#fcee0a">${(rssi.mean || rssi.avg || 0).toFixed(0)} dBm</span></span>
                    <span>Max: <span style="color:#05ffa1">${rssi.max} dBm</span></span>
                   </div>`
                : '';

            // Activity hours bar chart (24 bins)
            const hours = profile.activity_hours || [];
            let activityBarsHtml = '';
            if (hours.length > 0) {
                // hours is an array of {hour, count} or just counts
                const hourCounts = new Array(24).fill(0);
                for (const h of hours) {
                    if (typeof h === 'object' && h.hour != null) {
                        hourCounts[h.hour] = h.count || 0;
                    } else if (typeof h === 'number') {
                        // index-based
                        const idx = hours.indexOf(h);
                        if (idx < 24) hourCounts[idx] = h;
                    }
                }
                const maxCount = Math.max(...hourCounts, 1);
                const bars = hourCounts.map((c, i) => {
                    const pct = (c / maxCount) * 100;
                    const label = i % 6 === 0 ? `${String(i).padStart(2, '0')}` : '';
                    return `<div class="dossier-hour-bar-col" title="${i}:00 — ${c} signals">
                        <div class="dossier-hour-bar" style="height:${pct}%"></div>
                        <span class="dossier-hour-label">${label}</span>
                    </div>`;
                }).join('');
                activityBarsHtml = `
                    <div class="dossier-activity-label">Activity by Hour</div>
                    <div class="dossier-activity-hours">${bars}</div>`;
            }

            el.innerHTML = `
                <div class="dossier-behavioral-grid">
                    <div class="dossier-behavior-badge" style="color:${patternColor};border-color:${patternColor}">
                        ${_esc(pattern).toUpperCase()}
                    </div>
                    <div class="dossier-behavior-stats mono">
                        <span>Avg: ${avgSpeed} m/s</span>
                        <span>Max: ${maxSpeed} m/s</span>
                        <span>Signals: ${signalCount}</span>
                        <span>Active: ${durationStr}</span>
                    </div>
                </div>
                ${rssiHtml}
                <div class="dossier-src-breakdown">${srcChips}</div>
                ${activityBarsHtml}
            `;
        }

        // ---------------------------------------------------------------
        // Location summary
        // ---------------------------------------------------------------

        async function _fetchAndRenderLocation(el, dossierId) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/location-summary`);
                if (!resp.ok) { el.innerHTML = '<div class="dossier-dim">Location data unavailable</div>'; return; }
                const data = await resp.json();
                _renderLocationSummary(el, data);
            } catch (_) {
                el.innerHTML = '<div class="dossier-dim">Failed to load location data</div>';
            }
        }

        function _renderLocationSummary(el, data) {
            const zones = data.zones_visited || [];
            const distance = data.total_distance || 0;
            const posCount = data.position_count || 0;

            let distStr;
            if (distance >= 1000) {
                distStr = `${(distance / 1000).toFixed(2)} km`;
            } else {
                distStr = `${distance.toFixed(1)} m`;
            }

            const zonesHtml = zones.length > 0
                ? zones.map(z => {
                    const name = _esc(z.name || z.zone_id || 'Unknown zone');
                    const timeInZone = z.duration_s || z.time_spent_s || 0;
                    const timeStr = timeInZone > 3600
                        ? `${(timeInZone / 3600).toFixed(1)}h`
                        : timeInZone > 60 ? `${Math.round(timeInZone / 60)}m` : `${timeInZone}s`;
                    const entries = z.entry_count || z.visits || 0;
                    return `<div class="dossier-zone-row">
                        <span class="dossier-zone-name">${name}</span>
                        <span class="dossier-zone-meta mono">${entries > 0 ? entries + ' visits' : ''} ${timeStr}</span>
                    </div>`;
                }).join('')
                : '<div class="dossier-dim">No zone data</div>';

            el.innerHTML = `
                <div class="dossier-location-stats mono">
                    <span>Distance: <span style="color:#00f0ff">${distStr}</span></span>
                    <span>Positions: <span style="color:#00f0ff">${posCount}</span></span>
                </div>
                <div class="dossier-zones-list">${zonesHtml}</div>
            `;
        }

        // ---------------------------------------------------------------
        // Correlations
        // ---------------------------------------------------------------

        async function _fetchAndRenderCorrelations(el, dossier) {
            try {
                // Get identifiers from dossier to find related target IDs
                const identifiers = dossier.identifiers || {};
                const dossierId = dossier.dossier_id || '';

                // Fetch correlations from the correlations API
                const resp = await fetch('/api/correlations');
                if (!resp.ok) {
                    // Fall back to showing identifiers as correlation indicators
                    _renderCorrelationsFallback(el, identifiers, dossierId);
                    return;
                }
                const data = await resp.json();
                const allCorrelations = data.correlations || [];

                // Filter for correlations involving any of this dossier's identifiers
                const myIds = new Set();
                // Add MAC-based target IDs
                if (identifiers.mac) {
                    const cleanMac = identifiers.mac.replace(/:/g, '');
                    myIds.add(`ble_${cleanMac}`);
                    myIds.add(`ble_${cleanMac.toLowerCase()}`);
                    myIds.add(`ble_${cleanMac.toUpperCase()}`);
                }
                // Add any target_ids from dossier
                if (dossier.target_ids) {
                    for (const tid of dossier.target_ids) myIds.add(tid);
                }
                if (dossier.primary_target_id) myIds.add(dossier.primary_target_id);

                const relevant = allCorrelations.filter(c =>
                    myIds.has(c.primary_id) || myIds.has(c.secondary_id) ||
                    myIds.has(c.target_a) || myIds.has(c.target_b)
                );

                _renderCorrelations(el, relevant, identifiers, dossierId, myIds);
            } catch (_) {
                _renderCorrelationsFallback(el, dossier.identifiers || {}, dossier.dossier_id || '');
            }
        }

        function _renderCorrelations(el, correlations, identifiers, dossierId, myIds) {
            if (correlations.length === 0 && Object.keys(identifiers).length === 0) {
                el.innerHTML = '<div class="dossier-dim">No correlations found</div>';
                return;
            }

            // Build correlation cards
            let corrHtml = '';
            if (correlations.length > 0) {
                corrHtml = correlations.slice(0, 20).map(c => {
                    const primaryId = c.primary_id || c.target_a || '';
                    const secondaryId = c.secondary_id || c.target_b || '';
                    const otherId = myIds.has(primaryId) ? secondaryId : primaryId;
                    const confidence = Math.round((c.confidence || c.score || 0) * 100);
                    const method = c.method || c.correlation_type || 'unknown';
                    const confColor = confidence > 70 ? '#05ffa1' : confidence > 40 ? '#fcee0a' : '#ff2a6d';

                    return `<div class="dossier-corr-card">
                        <span class="dossier-corr-id mono">${_esc(otherId)}</span>
                        <span class="dossier-corr-method">${_esc(method)}</span>
                        <span class="dossier-corr-conf mono" style="color:${confColor}">${confidence}%</span>
                    </div>`;
                }).join('');
            }

            // Show fused identifiers as implicit correlations
            const idEntries = Object.entries(identifiers);
            const idHtml = idEntries.length > 0
                ? `<div class="dossier-corr-ids-header">Fused Identifiers</div>` +
                  idEntries.map(([k, v]) =>
                    `<div class="dossier-corr-fused-row">
                        <span class="dossier-corr-fused-type">${_esc(k)}</span>
                        <span class="dossier-corr-fused-val mono">${_esc(String(v))}</span>
                    </div>`
                  ).join('')
                : '';

            el.innerHTML = `
                ${corrHtml ? `<div class="dossier-corr-list">${corrHtml}</div>` : ''}
                ${idHtml}
                ${!corrHtml && !idHtml ? '<div class="dossier-dim">No correlations found</div>' : ''}
            `;
        }

        function _renderCorrelationsFallback(el, identifiers, dossierId) {
            const entries = Object.entries(identifiers);
            if (entries.length === 0) {
                el.innerHTML = '<div class="dossier-dim">No correlation data available</div>';
                return;
            }
            el.innerHTML = `
                <div class="dossier-corr-ids-header">Fused Identifiers</div>
                ${entries.map(([k, v]) =>
                    `<div class="dossier-corr-fused-row">
                        <span class="dossier-corr-fused-type">${_esc(k)}</span>
                        <span class="dossier-corr-fused-val mono">${_esc(String(v))}</span>
                    </div>`
                ).join('')}
            `;
        }

        // ---------------------------------------------------------------
        // Merge dialog
        // ---------------------------------------------------------------

        function _openMergeDialog(primaryId) {
            // Simple prompt-based merge
            const secondaryId = prompt('Enter the dossier ID to merge INTO this dossier:');
            if (!secondaryId || !secondaryId.trim()) return;

            const confirmed = confirm(
                `Merge dossier ${secondaryId.trim().substring(0, 8)}... into ${primaryId.substring(0, 8)}...?\n\n` +
                'All signals, enrichments, tags, and notes from the secondary dossier will be moved to the primary. ' +
                'The secondary dossier will be deleted. This cannot be undone.'
            );
            if (!confirmed) return;

            fetch('/api/dossiers/merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ primary_id: primaryId, secondary_id: secondaryId.trim() }),
            })
            .then(resp => resp.json())
            .then(data => {
                if (data.ok) {
                    fetchList();
                    loadDetail(primaryId);
                } else {
                    alert('Merge failed: ' + (data.error || 'Unknown error'));
                }
            })
            .catch(() => alert('Merge request failed'));
        }

        // ---------------------------------------------------------------
        // Fetch list
        // ---------------------------------------------------------------

        async function fetchList() {
            const query = queryInput?.value?.trim() || '';
            const entityType = entityTypeSelect?.value || '';
            const threat = threatSelect?.value || '';
            const alliance = allianceSelect?.value || '';
            const sort = sortSelect?.value || 'last_seen';

            if (query.length > 0) {
                // Search mode
                try {
                    const resp = await fetch(`/api/dossiers/search?q=${encodeURIComponent(query)}`);
                    if (!resp.ok) { renderList([]); return; }
                    const data = await resp.json();
                    renderList(data.results || []);
                } catch (_) {
                    renderList([]);
                }
            } else {
                // List mode with filters
                const params = new URLSearchParams();
                params.set('limit', '100');
                params.set('sort', sort);
                if (entityType) params.set('entity_type', entityType);
                if (threat) params.set('threat_level', threat);
                if (alliance) params.set('alliance', alliance);

                try {
                    const resp = await fetch(`/api/dossiers?${params}`);
                    if (!resp.ok) { renderList([]); return; }
                    const data = await resp.json();
                    renderList(data.dossiers || []);
                } catch (_) {
                    renderList([]);
                }
            }
        }

        // ---------------------------------------------------------------
        // Event wiring
        // ---------------------------------------------------------------

        if (queryInput) {
            queryInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') fetchList();
                e.stopPropagation();
            });
            queryInput.addEventListener('input', () => {
                clearTimeout(typeaheadTimer);
                typeaheadTimer = setTimeout(() => {
                    const val = queryInput.value.trim();
                    if (val.length >= 2 || val.length === 0) fetchList();
                }, 350);
            });
        }

        [entityTypeSelect, threatSelect, allianceSelect, sortSelect].forEach(sel => {
            if (sel) sel.addEventListener('change', fetchList);
        });

        // Initial load
        fetchList();

        // Auto-refresh every 15s
        const refreshInterval = setInterval(fetchList, 15000);
        panel._unsubs.push(() => clearInterval(refreshInterval));
        panel._unsubs.push(() => clearTimeout(typeaheadTimer));

        // Listen for dossier:load-target event from unit inspector / target detail
        const _onLoadTarget = async (data) => {
            if (data && data.target_id) {
                // If a dossier_id was provided directly, load it
                if (data.dossier_id) {
                    selectedId = data.dossier_id;
                    loadDetail(data.dossier_id);
                } else {
                    // Look up dossier by target_id via the by-target API
                    try {
                        const resp = await fetch(`/api/dossiers/by-target?target_id=${encodeURIComponent(data.target_id)}`);
                        if (resp.ok) {
                            const dossier = await resp.json();
                            const did = dossier.dossier_id;
                            if (did) {
                                selectedId = did;
                                loadDetail(did);
                            }
                        } else {
                            // No dossier found — show placeholder with target info
                            if (detailEl) {
                                detailEl.innerHTML = `<div class="dossier-detail-placeholder">No dossier found for target: ${_esc(data.target_id)}</div>`;
                            }
                        }
                    } catch (_err) {
                        if (detailEl) {
                            detailEl.innerHTML = '<div class="dossier-detail-placeholder">Failed to look up dossier</div>';
                        }
                    }
                }
                // Highlight in the list after a short delay
                setTimeout(() => {
                    if (!selectedId || !listEl) return;
                    const item = listEl.querySelector(`[data-dossier-id="${selectedId}"]`);
                    if (item) {
                        listEl.querySelectorAll('.dossier-list-item').forEach(li =>
                            li.classList.toggle('dossier-list-item-selected', li.dataset.dossierId === selectedId));
                        item.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                    }
                }, 500);
            }
        };
        EventBus.on('dossier:load-target', _onLoadTarget);
        panel._unsubs.push(() => EventBus.off('dossier:load-target', _onLoadTarget));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};

// ---------------------------------------------------------------------------
// Inject panel-specific styles
// ---------------------------------------------------------------------------
const style = document.createElement('style');
style.textContent = `
.dossier-panel-root {
    display: flex;
    height: 100%;
    gap: 0;
    overflow: hidden;
}

/* ---- List pane ---- */
.dossier-list-pane {
    width: 260px;
    min-width: 200px;
    display: flex;
    flex-direction: column;
    border-right: 1px solid rgba(0, 240, 255, 0.15);
    overflow: hidden;
}

.dossier-search-bar {
    padding: 6px;
}

.dossier-search-input {
    width: 100%;
    box-sizing: border-box;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.3);
    color: #e0e0e0;
    padding: 4px 8px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.7rem;
    border-radius: 2px;
    outline: none;
}

.dossier-search-input:focus {
    border-color: #00f0ff;
    box-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
}

.dossier-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 3px;
    padding: 0 6px 6px;
}

.dossier-filter-select {
    flex: 1 1 45%;
    min-width: 0;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 2px 3px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    border-radius: 2px;
    cursor: pointer;
}

.dossier-filter-select:focus {
    border-color: #00f0ff;
}

.dossier-list {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
    list-style: none;
    margin: 0;
    padding: 0;
}

.dossier-empty {
    padding: 16px;
    text-align: center;
    color: rgba(224, 224, 224, 0.4);
    font-size: 0.7rem;
}

.dossier-list-item {
    padding: 6px 8px;
    cursor: pointer;
    border-bottom: 1px solid rgba(0, 240, 255, 0.06);
    transition: background 0.15s;
}

.dossier-list-item:hover {
    background: rgba(0, 240, 255, 0.06);
}

.dossier-list-item-selected {
    background: rgba(0, 240, 255, 0.12);
    border-left: 2px solid #00f0ff;
}

.dossier-item-header {
    display: flex;
    align-items: center;
    gap: 6px;
}

.dossier-type-badge {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    font-weight: 700;
    padding: 1px 4px;
    border: 1px solid;
    border-radius: 2px;
    white-space: nowrap;
}

.dossier-item-name {
    flex: 1;
    font-size: 0.7rem;
    color: #e0e0e0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.dossier-threat-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
}

.dossier-item-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.4);
    margin-top: 2px;
    padding-left: 28px;
}

/* ---- Detail pane ---- */
.dossier-detail-pane {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.dossier-detail-scroll {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.dossier-detail-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: rgba(224, 224, 224, 0.3);
    font-size: 0.75rem;
}

/* Detail header */
.dossier-detail-header {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.dossier-detail-title-row {
    display: flex;
    align-items: center;
    gap: 8px;
}

.dossier-detail-name {
    font-size: 1rem;
    font-weight: 700;
    color: #e0e0e0;
    flex: 1;
}

.dossier-threat-badge {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 2px;
    color: #0a0a0f;
}

.dossier-detail-uuid {
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.35);
    word-break: break-all;
}

.dossier-confidence-bar-wrap {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.dossier-confidence-label {
    font-size: 0.6rem;
    color: rgba(224, 224, 224, 0.6);
}

.dossier-confidence-track {
    height: 4px;
    background: rgba(0, 240, 255, 0.1);
    border-radius: 2px;
    overflow: hidden;
}

.dossier-confidence-fill {
    height: 100%;
    background: #00f0ff;
    border-radius: 2px;
    transition: width 0.3s ease;
}

/* Sections */
.dossier-section {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.dossier-section-title {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    font-weight: 700;
    color: #00f0ff;
    letter-spacing: 0.08em;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
    padding-bottom: 2px;
}

.dossier-dim {
    font-size: 0.65rem;
    color: rgba(224, 224, 224, 0.3);
    font-style: italic;
}

/* Identifier chips */
.dossier-id-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}

.dossier-id-chip {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    padding: 2px 6px;
    background: rgba(0, 240, 255, 0.08);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 2px;
    color: #e0e0e0;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    user-select: all;
}

.dossier-id-chip:hover {
    background: rgba(0, 240, 255, 0.15);
    border-color: #00f0ff;
}

.dossier-id-chip-copied {
    background: rgba(5, 255, 161, 0.2);
    border-color: #05ffa1;
}

/* Signal timeline */
.dossier-signal-timeline {
    max-height: 200px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1px;
}

.dossier-signal-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px;
    font-size: 0.6rem;
    border-bottom: 1px solid rgba(0, 240, 255, 0.04);
}

.dossier-signal-row:hover {
    background: rgba(0, 240, 255, 0.04);
}

.dossier-signal-icon {
    font-size: 0.7rem;
    width: 16px;
    text-align: center;
}

.dossier-signal-type {
    color: #e0e0e0;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dossier-signal-source {
    color: rgba(0, 240, 255, 0.6);
    font-size: 0.5rem;
}

.dossier-signal-conf {
    color: rgba(224, 224, 224, 0.5);
    font-size: 0.5rem;
    width: 28px;
    text-align: right;
}

.dossier-signal-time {
    color: rgba(224, 224, 224, 0.4);
    font-size: 0.5rem;
    white-space: nowrap;
}

/* Enrichment cards */
.dossier-enrich-card {
    background: rgba(0, 240, 255, 0.04);
    border: 1px solid rgba(0, 240, 255, 0.1);
    border-radius: 3px;
    padding: 6px 8px;
    margin-bottom: 4px;
}

.dossier-enrich-header {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    color: #00f0ff;
    margin-bottom: 4px;
}

.dossier-enrich-kv {
    font-size: 0.6rem;
    color: #e0e0e0;
}

.dossier-enrich-key {
    color: rgba(0, 240, 255, 0.6);
    margin-right: 4px;
}

/* Tags */
.dossier-tags-wrap {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
}

.dossier-tag-chip {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    padding: 2px 6px;
    background: rgba(255, 42, 109, 0.1);
    border: 1px solid rgba(255, 42, 109, 0.3);
    border-radius: 2px;
    color: #ff2a6d;
    display: inline-flex;
    align-items: center;
    gap: 4px;
}

.dossier-tag-remove {
    background: none;
    border: none;
    color: rgba(255, 42, 109, 0.6);
    cursor: pointer;
    font-size: 0.7rem;
    padding: 0;
    line-height: 1;
}

.dossier-tag-remove:hover {
    color: #ff2a6d;
}

.dossier-tag-add-row,
.dossier-note-add-row {
    display: flex;
    gap: 4px;
    margin-top: 4px;
    width: 100%;
}

.dossier-tag-input,
.dossier-note-input {
    flex: 1;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 3px 6px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    border-radius: 2px;
    outline: none;
}

.dossier-tag-input:focus,
.dossier-note-input:focus {
    border-color: #00f0ff;
}

/* Notes */
.dossier-notes-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.dossier-note {
    font-size: 0.65rem;
    color: #e0e0e0;
    padding: 4px 6px;
    background: rgba(252, 238, 10, 0.04);
    border-left: 2px solid rgba(252, 238, 10, 0.3);
    border-radius: 2px;
}

/* Mini-map canvas */
.dossier-minimap {
    width: 100%;
    height: 140px;
    border: 1px solid rgba(0, 240, 255, 0.15);
    border-radius: 3px;
}

/* Signal history chart */
.dossier-signal-chart {
    width: 100%;
    height: 100px;
    border: 1px solid rgba(0, 240, 255, 0.15);
    border-radius: 3px;
}

/* Merge button */
.dossier-merge-btn {
    width: 100%;
    padding: 6px;
    background: rgba(255, 42, 109, 0.1);
    border: 1px solid rgba(255, 42, 109, 0.3);
    color: #ff2a6d;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.15s;
}

.dossier-merge-btn:hover {
    background: rgba(255, 42, 109, 0.2);
}

/* Behavioral profile */
.dossier-behavioral-grid {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
}

.dossier-behavior-badge {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    font-weight: 700;
    padding: 3px 10px;
    border: 1px solid;
    border-radius: 2px;
    letter-spacing: 0.08em;
}

.dossier-behavior-stats {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.6);
}

.dossier-rssi-stats {
    display: flex;
    gap: 12px;
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.5);
    margin-top: 4px;
}

.dossier-src-breakdown {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 4px;
}

.dossier-src-chip {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    padding: 1px 5px;
    background: rgba(0, 240, 255, 0.06);
    border: 1px solid rgba(0, 240, 255, 0.15);
    border-radius: 2px;
    color: rgba(224, 224, 224, 0.6);
}

.dossier-activity-label {
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.4);
    margin-top: 6px;
    margin-bottom: 2px;
}

.dossier-activity-hours {
    display: flex;
    align-items: flex-end;
    gap: 1px;
    height: 36px;
    background: rgba(0, 240, 255, 0.03);
    border: 1px solid rgba(0, 240, 255, 0.08);
    border-radius: 2px;
    padding: 2px 1px 12px;
    position: relative;
}

.dossier-hour-bar-col {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 100%;
    justify-content: flex-end;
    position: relative;
}

.dossier-hour-bar {
    width: 100%;
    background: rgba(0, 240, 255, 0.5);
    border-radius: 1px 1px 0 0;
    min-height: 0;
    transition: height 0.2s ease;
}

.dossier-hour-label {
    position: absolute;
    bottom: -11px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 6px;
    color: rgba(224, 224, 224, 0.3);
}

/* Location summary */
.dossier-location-stats {
    display: flex;
    gap: 16px;
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.5);
    margin-bottom: 4px;
}

.dossier-zones-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.dossier-zone-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 3px 6px;
    font-size: 0.6rem;
    background: rgba(0, 240, 255, 0.03);
    border-left: 2px solid rgba(0, 240, 255, 0.2);
    border-radius: 0 2px 2px 0;
}

.dossier-zone-name {
    color: #e0e0e0;
    flex: 1;
}

.dossier-zone-meta {
    color: rgba(224, 224, 224, 0.4);
    font-size: 0.5rem;
}

/* Correlations */
.dossier-corr-list {
    display: flex;
    flex-direction: column;
    gap: 3px;
    margin-bottom: 6px;
}

.dossier-corr-card {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 6px;
    background: rgba(5, 255, 161, 0.04);
    border: 1px solid rgba(5, 255, 161, 0.12);
    border-radius: 2px;
}

.dossier-corr-id {
    flex: 1;
    font-size: 0.55rem;
    color: #e0e0e0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.dossier-corr-method {
    font-size: 0.5rem;
    color: rgba(0, 240, 255, 0.6);
}

.dossier-corr-conf {
    font-size: 0.55rem;
    font-weight: 700;
}

.dossier-corr-ids-header {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    color: rgba(0, 240, 255, 0.5);
    margin-bottom: 3px;
    letter-spacing: 0.05em;
}

.dossier-corr-fused-row {
    display: flex;
    gap: 8px;
    padding: 2px 6px;
    font-size: 0.55rem;
}

.dossier-corr-fused-type {
    color: rgba(0, 240, 255, 0.6);
    min-width: 40px;
}

.dossier-corr-fused-val {
    color: #e0e0e0;
    word-break: break-all;
}

/* Scrollbar styling for detail pane */
.dossier-detail-scroll::-webkit-scrollbar,
.dossier-signal-timeline::-webkit-scrollbar,
.dossier-list::-webkit-scrollbar {
    width: 4px;
}

.dossier-detail-scroll::-webkit-scrollbar-track,
.dossier-signal-timeline::-webkit-scrollbar-track,
.dossier-list::-webkit-scrollbar-track {
    background: transparent;
}

.dossier-detail-scroll::-webkit-scrollbar-thumb,
.dossier-signal-timeline::-webkit-scrollbar-thumb,
.dossier-list::-webkit-scrollbar-thumb {
    background: rgba(0, 240, 255, 0.2);
    border-radius: 2px;
}
`;
document.head.appendChild(style);
