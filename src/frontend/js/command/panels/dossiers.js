// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Dossier Panel — persistent entity intelligence browser
// Split view: dossier list (left) + detail view (right).
// Fetches from /api/dossiers, /api/dossiers/search, /api/dossiers/{id}.
// Supports filtering, sorting, tags, notes, merge, position trail mini-map.

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';
import { _esc, _timeAgo } from '/lib/utils.js';



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
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}?signal_limit=100`);
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
            const dossierAlliance = (d.alliance || 'unknown').toLowerCase();
            const ALLIANCE_COLORS = { friendly: '#05ffa1', hostile: '#ff2a6d', unknown: '#888', neutral: '#fcee0a' };
            const dossierAllianceColor = ALLIANCE_COLORS[dossierAlliance] || '#888';

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
                        <div class="dossier-alliance-row" style="margin-top:8px;display:flex;align-items:center;gap:8px">
                            <span style="font-size:0.45rem;color:var(--text-ghost);text-transform:uppercase;letter-spacing:1px">ALLIANCE:</span>
                            <span class="dossier-alliance-badge" style="color:${dossierAllianceColor};font-weight:700;font-size:0.5rem;letter-spacing:0.08em">${_esc(dossierAlliance).toUpperCase()}</span>
                            <span style="flex:1"></span>
                            <button class="tag-btn tag-btn-friendly${dossierAlliance === 'friendly' ? ' active' : ''}" data-dossier-tag="friendly" style="font-size:0.4rem;padding:3px 8px">FRIENDLY</button>
                            <button class="tag-btn tag-btn-hostile${dossierAlliance === 'hostile' ? ' active' : ''}" data-dossier-tag="hostile" style="font-size:0.4rem;padding:3px 8px">HOSTILE</button>
                            <button class="tag-btn tag-btn-vip${tags.includes('VIP') ? ' active' : ''}" data-dossier-tag="vip" style="font-size:0.4rem;padding:3px 8px">VIP</button>
                        </div>
                    </div>

                    <div class="dossier-section">
                        <div class="dossier-section-title">IDENTIFIERS</div>
                        <div class="dossier-id-chips">${idChips}</div>
                    </div>

                    ${positions.length > 0 ? `
                    <div class="dossier-section">
                        <div class="dossier-section-title" style="display:flex;align-items:center;gap:8px">
                            POSITION TRAIL
                            <button class="panel-action-btn panel-action-btn-sm dossier-show-trail-btn" data-action="show-trail-on-map" title="Show movement trail on tactical map">SHOW ON MAP</button>
                        </div>
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
                        <div class="dossier-section-title" style="display:flex;align-items:center;gap:8px">
                            CORRELATIONS
                            <button class="panel-action-btn panel-action-btn-sm dossier-show-corr-btn" data-action="show-corr-on-map" title="Show correlation lines on tactical map">SHOW ON MAP</button>
                        </div>
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

            // Dossier alliance tag buttons (FRIENDLY / HOSTILE / VIP)
            const dossierTagBtns = container.querySelectorAll('[data-dossier-tag]');
            dossierTagBtns.forEach(btn => {
                btn.addEventListener('click', async () => {
                    const tag = btn.dataset.dossierTag;
                    const targetId = dossier.target_id || dossier.dossier_id;
                    if (!targetId) return;
                    try {
                        if (tag === 'vip') {
                            const isVip = btn.classList.contains('active');
                            if (!isVip) {
                                await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/tags`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ tag: 'VIP' }),
                                });
                            } else {
                                await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/tags/VIP`, {
                                    method: 'DELETE',
                                });
                            }
                            loadDetail(dossierId);
                        } else {
                            await fetch(`/api/targets/${encodeURIComponent(targetId)}/classify`, {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    target_id: targetId,
                                    alliance: tag,
                                    reason: `Operator tagged as ${tag} via dossier`,
                                }),
                            });
                            loadDetail(dossierId);
                        }
                    } catch (_) {}
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

            // Show Trail on Map button
            const showTrailBtn = container.querySelector('[data-action="show-trail-on-map"]');
            if (showTrailBtn && positions.length > 0) {
                let trailVisible = false;
                showTrailBtn.addEventListener('click', () => {
                    if (trailVisible) {
                        EventBus.emit('target:hideTrail', {});
                        showTrailBtn.textContent = 'SHOW ON MAP';
                        showTrailBtn.classList.remove('panel-action-btn-primary');
                        trailVisible = false;
                    } else {
                        // Find the best target ID for this dossier
                        const targetId = dossier.primary_target_id
                            || (dossier.target_ids && dossier.target_ids[0])
                            || dossierId;
                        EventBus.emit('target:showTrail', {
                            targetId: targetId,
                            alliance: dossier.alliance || 'unknown',
                            positions: positions,
                        });
                        showTrailBtn.textContent = 'HIDE TRAIL';
                        showTrailBtn.classList.add('panel-action-btn-primary');
                        trailVisible = true;
                    }
                });
            }

            // Show Correlations on Map button
            const showCorrBtn = container.querySelector('[data-action="show-corr-on-map"]');
            if (showCorrBtn) {
                showCorrBtn.addEventListener('click', () => {
                    const targetId = dossier.primary_target_id
                        || (dossier.target_ids && dossier.target_ids[0])
                        || dossierId;
                    // Gather correlated IDs from linked targets + correlations
                    const correlatedIds = [];
                    const myIds = new Set();
                    if (dossier.target_ids) dossier.target_ids.forEach(id => myIds.add(id));
                    if (dossier.primary_target_id) myIds.add(dossier.primary_target_id);

                    // Find linked targets from TritiumStore
                    if (typeof TritiumStore !== 'undefined' && TritiumStore.units) {
                        TritiumStore.units.forEach((unit, uid) => {
                            if (myIds.has(uid)) return;
                            const corrIds = unit.correlated_ids || [];
                            for (const cid of corrIds) {
                                if (myIds.has(cid)) {
                                    correlatedIds.push({
                                        id: uid,
                                        confidence: unit.correlation_confidence || 0.5,
                                    });
                                    break;
                                }
                            }
                        });
                    }

                    if (correlatedIds.length > 0) {
                        EventBus.emit('target:showCorrelationLines', {
                            targetId: targetId,
                            correlatedIds: correlatedIds,
                        });
                        EventBus.emit('toast:show', {
                            message: `Showing ${correlatedIds.length} correlation lines`,
                            type: 'info',
                        });
                    } else {
                        EventBus.emit('toast:show', {
                            message: 'No correlated targets with positions found',
                            type: 'alert',
                        });
                    }
                });
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
                const chartMeta = _drawSignalSparkline(ctx, w, h, timeline);
                // Set up hover tooltip if chart drew successfully
                if (chartMeta) {
                    _setupSignalChartTooltip(canvas, chartMeta);
                }
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

            // Try RSSI values first; fall back to confidence if no RSSI data
            const rssiPoints = timeline
                .filter(t => t.rssi != null || (t.data && t.data.rssi != null))
                .map(t => ({
                    ts: t.timestamp || 0,
                    value: t.rssi ?? (t.data && t.data.rssi) ?? -80,
                }))
                .sort((a, b) => a.ts - b.ts);

            const confPoints = timeline
                .filter(t => t.confidence != null)
                .map(t => ({
                    ts: t.timestamp || 0,
                    value: Math.round((t.confidence || 0) * 100),
                }))
                .sort((a, b) => a.ts - b.ts);

            // Use RSSI if available, else confidence
            const useRssi = rssiPoints.length > 0;
            const points = useRssi ? rssiPoints : confPoints;
            const chartTitle = useRssi ? 'RSSI (dBm) over time' : 'Detection Confidence (%) over time';
            const chartColor = useRssi ? '#00f0ff' : '#05ffa1';
            const unitLabel = useRssi ? 'dBm' : '%';

            if (points.length === 0) {
                _drawEmptyChart(ctx, w, h, 'No signal data in history');
                return;
            }

            // Find bounds
            let minVal = Infinity, maxVal = -Infinity;
            let minTs = Infinity, maxTs = -Infinity;
            for (const p of points) {
                if (p.value < minVal) minVal = p.value;
                if (p.value > maxVal) maxVal = p.value;
                if (p.ts < minTs) minTs = p.ts;
                if (p.ts > maxTs) maxTs = p.ts;
            }
            // Ensure some range
            if (maxVal === minVal) { maxVal += 5; minVal -= 5; }
            if (!useRssi) { minVal = Math.max(0, minVal - 5); maxVal = Math.min(100, maxVal + 5); }
            if (maxTs === minTs) maxTs = minTs + 60;

            const tsRange = maxTs - minTs;
            const valRange = maxVal - minVal;

            function toX(ts) { return pad.left + ((ts - minTs) / tsRange) * plotW; }
            function toY(val) { return pad.top + plotH - ((val - minVal) / valRange) * plotH; }

            // Determine grid step
            const gridStep = useRssi ? 10 : (valRange > 50 ? 20 : 10);

            // Draw grid lines (horizontal)
            ctx.strokeStyle = `rgba(${useRssi ? '0, 240, 255' : '5, 255, 161'}, 0.08)`;
            ctx.lineWidth = 0.5;
            for (let r = Math.ceil(minVal / gridStep) * gridStep; r <= maxVal; r += gridStep) {
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
            ctx.fillStyle = chartColor;
            ctx.font = '8px monospace';
            ctx.textAlign = 'left';
            ctx.fillText(chartTitle, pad.left, 10);

            // Time axis labels — relative times ("5m ago", "1m ago", "now")
            ctx.fillStyle = 'rgba(224, 224, 224, 0.3)';
            ctx.font = '7px monospace';
            ctx.textAlign = 'center';
            const nowTs = Date.now() / 1000;
            const _relTime = (ts) => {
                const diff = nowTs - ts;
                if (diff < 5) return 'now';
                if (diff < 60) return `${Math.round(diff)}s ago`;
                if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
                if (diff < 86400) return `${(diff / 3600).toFixed(1)}h ago`;
                return `${Math.round(diff / 86400)}d ago`;
            };
            // Draw 3-5 time labels along the x-axis
            const numTimeLabels = Math.min(5, Math.max(3, Math.floor(plotW / 60)));
            for (let i = 0; i < numTimeLabels; i++) {
                const frac = i / (numTimeLabels - 1);
                const ts = minTs + frac * tsRange;
                const x = toX(ts);
                ctx.fillText(_relTime(ts), x, h - 3);
            }

            // Draw gradient fill under the sparkline
            const gradRgb = useRssi ? '0, 240, 255' : '5, 255, 161';
            const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            gradient.addColorStop(0, `rgba(${gradRgb}, 0.15)`);
            gradient.addColorStop(1, `rgba(${gradRgb}, 0.01)`);

            ctx.beginPath();
            ctx.moveTo(toX(points[0].ts), toY(points[0].value));
            for (let i = 1; i < points.length; i++) {
                ctx.lineTo(toX(points[i].ts), toY(points[i].value));
            }
            // Close path for fill
            ctx.lineTo(toX(points[points.length - 1].ts), pad.top + plotH);
            ctx.lineTo(toX(points[0].ts), pad.top + plotH);
            ctx.closePath();
            ctx.fillStyle = gradient;
            ctx.fill();

            // Draw sparkline
            ctx.beginPath();
            ctx.strokeStyle = chartColor;
            ctx.lineWidth = 1.5;
            ctx.moveTo(toX(points[0].ts), toY(points[0].value));
            for (let i = 1; i < points.length; i++) {
                ctx.lineTo(toX(points[i].ts), toY(points[i].value));
            }
            ctx.stroke();

            // Draw dots at each data point (limit to avoid clutter)
            const step = Math.max(1, Math.floor(points.length / 40));
            for (let i = 0; i < points.length; i += step) {
                const x = toX(points[i].ts);
                const y = toY(points[i].value);
                let dotColor;
                if (useRssi) {
                    dotColor = points[i].value > -50 ? '#05ffa1' : points[i].value > -70 ? '#fcee0a' : '#ff2a6d';
                } else {
                    dotColor = points[i].value > 70 ? '#05ffa1' : points[i].value > 40 ? '#fcee0a' : '#ff2a6d';
                }
                ctx.fillStyle = dotColor;
                ctx.beginPath();
                ctx.arc(x, y, 2, 0, Math.PI * 2);
                ctx.fill();
            }
            // Always draw last point
            if (points.length > 1) {
                const last = points[points.length - 1];
                const lx = toX(last.ts);
                const ly = toY(last.value);
                ctx.fillStyle = chartColor;
                ctx.beginPath();
                ctx.arc(lx, ly, 3, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = chartColor;
                ctx.font = '7px monospace';
                ctx.textAlign = 'left';
                ctx.fillText(`${last.value} ${unitLabel}`, lx + 5, ly + 3);
            }

            ctx.textAlign = 'start';

            // Return chart metadata for tooltip
            return { points, pad, minTs, maxTs, minVal, maxVal, tsRange, valRange, useRssi, unitLabel, chartColor, w, h };
        }

        /**
         * Set up a hover tooltip on the signal chart canvas.
         * Shows exact value and relative time at the cursor position.
         */
        function _setupSignalChartTooltip(canvas, meta) {
            const { points, pad, minTs, tsRange, minVal, valRange, useRssi, unitLabel, w, h } = meta;
            const plotW = w - pad.left - pad.right;
            const plotH = h - pad.top - pad.bottom;

            // Create tooltip element
            let tooltip = canvas.parentElement.querySelector('.dossier-signal-tooltip');
            if (!tooltip) {
                tooltip = document.createElement('div');
                tooltip.className = 'dossier-signal-tooltip';
                tooltip.style.cssText = [
                    'position: absolute',
                    'pointer-events: none',
                    'background: rgba(10, 10, 15, 0.92)',
                    'border: 1px solid rgba(0, 240, 255, 0.3)',
                    'padding: 3px 6px',
                    'font-family: "JetBrains Mono", monospace',
                    'font-size: 0.45rem',
                    'color: #e0e0e0',
                    'white-space: nowrap',
                    'display: none',
                    'z-index: 10',
                    'border-radius: 2px',
                ].join(';');
                canvas.parentElement.style.position = 'relative';
                canvas.parentElement.appendChild(tooltip);
            }

            const scaleX = canvas.offsetWidth / w;
            const scaleY = canvas.offsetHeight / h;

            canvas.addEventListener('mousemove', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mx = (e.clientX - rect.left) / scaleX;
                const my = (e.clientY - rect.top) / scaleY;

                // Check if within plot area
                if (mx < pad.left || mx > w - pad.right || my < pad.top || my > pad.top + plotH) {
                    tooltip.style.display = 'none';
                    return;
                }

                // Map mouse X to timestamp
                const hoverTs = minTs + ((mx - pad.left) / plotW) * tsRange;

                // Find nearest point
                let nearest = points[0];
                let nearestDist = Infinity;
                for (const p of points) {
                    const d = Math.abs(p.ts - hoverTs);
                    if (d < nearestDist) {
                        nearestDist = d;
                        nearest = p;
                    }
                }

                // Relative time
                const nowTs = Date.now() / 1000;
                const diff = nowTs - nearest.ts;
                let relLabel;
                if (diff < 5) relLabel = 'now';
                else if (diff < 60) relLabel = `${Math.round(diff)}s ago`;
                else if (diff < 3600) relLabel = `${Math.round(diff / 60)}m ago`;
                else if (diff < 86400) relLabel = `${(diff / 3600).toFixed(1)}h ago`;
                else relLabel = `${Math.round(diff / 86400)}d ago`;

                tooltip.textContent = `${nearest.value} ${unitLabel} | ${relLabel}`;
                tooltip.style.display = 'block';
                tooltip.style.left = `${e.clientX - rect.left + 8}px`;
                tooltip.style.top = `${e.clientY - rect.top - 20}px`;
            });

            canvas.addEventListener('mouseleave', () => {
                tooltip.style.display = 'none';
            });
        }

        // ---------------------------------------------------------------
        // Behavioral profile
        // ---------------------------------------------------------------

        async function _fetchAndRenderBehavioral(el, dossierId) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/behavioral-profile`);
                if (!resp.ok) {
                    if (el.isConnected) el.innerHTML = '<div class="dossier-dim">Behavioral data unavailable</div>';
                    return;
                }
                const p = await resp.json();
                if (el.isConnected) _renderBehavioralProfile(el, p);
            } catch (err) {
                console.warn('[Dossier] behavioral profile fetch failed:', err.message || err);
                if (el.isConnected) el.innerHTML = '<div class="dossier-dim">Failed to load behavioral profile</div>';
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
                // hours can be: [{hour, count}], [count, count, ...] (24 bins), or [hour, hour, ...] (active hour markers)
                const hourCounts = new Array(24).fill(0);
                for (const h of hours) {
                    if (typeof h === 'object' && h.hour != null) {
                        hourCounts[h.hour] = h.count || 1;
                    } else if (typeof h === 'number') {
                        if (hours.length <= 24 && h >= 0 && h <= 23 && Number.isInteger(h)) {
                            // Active hour markers (e.g. [8, 14, 20]) — mark those hours
                            hourCounts[h] = (hourCounts[h] || 0) + 1;
                        } else {
                            // Index-based counts (24-element array of counts)
                            const idx = hours.indexOf(h);
                            if (idx < 24) hourCounts[idx] = h;
                        }
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
                if (!resp.ok) {
                    if (el.isConnected) el.innerHTML = '<div class="dossier-dim">Location data unavailable</div>';
                    return;
                }
                const data = await resp.json();
                if (el.isConnected) _renderLocationSummary(el, data);
            } catch (err) {
                console.warn('[Dossier] location summary fetch failed:', err.message || err);
                if (el.isConnected) el.innerHTML = '<div class="dossier-dim">Failed to load location data</div>';
            }
        }

        function _renderLocationSummary(el, data) {
            const zones = data.zones_visited || [];
            const distance = data.total_distance || 0;
            const posCount = data.position_count || 0;
            const positions = data.positions || [];

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
                : '';

            // If no zones but we have position data, show last known position
            let positionHtml = '';
            if (positions.length > 0) {
                const lastPos = positions[positions.length - 1];
                const x = (lastPos.x || lastPos.lng || 0).toFixed(5);
                const y = (lastPos.y || lastPos.lat || 0).toFixed(5);
                positionHtml = `<div class="dossier-location-pos mono" style="margin-top:4px;color:rgba(224,224,224,0.5);font-size:0.55rem">
                    Last known: ${y}, ${x}
                </div>`;
            }

            // Status message when no detailed data
            const noDataMsg = (!zonesHtml && posCount === 0)
                ? '<div class="dossier-dim">No movement data recorded -- target may be stationary or position tracking unavailable</div>'
                : (!zonesHtml ? '<div class="dossier-dim" style="font-size:0.55rem">No zone crossings detected</div>' : '');

            el.innerHTML = `
                <div class="dossier-location-stats mono">
                    <span>Distance: <span style="color:#00f0ff">${distStr}</span></span>
                    <span>Positions: <span style="color:#00f0ff">${posCount}</span></span>
                </div>
                ${zonesHtml ? `<div class="dossier-zones-list">${zonesHtml}</div>` : ''}
                ${positionHtml}
                ${noDataMsg}
            `;
        }

        // ---------------------------------------------------------------
        // Correlations
        // ---------------------------------------------------------------

        async function _fetchAndRenderCorrelations(el, dossier) {
            const dossierId = dossier.dossier_id || '';
            const identifiers = dossier.identifiers || {};

            try {
                // Use the dedicated correlated-targets endpoint
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/correlated-targets`);
                if (resp.ok) {
                    const data = await resp.json();
                    _renderCorrelatedTargets(el, data, identifiers, dossierId);
                    return;
                }
            } catch (_) { /* endpoint unavailable, fall back */ }

            // Fallback: use old approach with client-side proximity matching
            try {
                const myIds = new Set();
                if (identifiers.mac) {
                    const cleanMac = identifiers.mac.replace(/:/g, '');
                    myIds.add(`ble_${cleanMac}`);
                    myIds.add(`ble_${cleanMac.toLowerCase()}`);
                    myIds.add(`ble_${cleanMac.toUpperCase()}`);
                }
                if (dossier.target_ids) {
                    for (const tid of dossier.target_ids) myIds.add(tid);
                }
                if (dossier.primary_target_id) myIds.add(dossier.primary_target_id);

                const nearbyTargets = _findNearbyTargetsFromStore(dossier, myIds);
                const linkedTargets = await _fetchLinkedTargets(myIds);

                _renderCorrelatedTargetsFallback(el, identifiers, linkedTargets, nearbyTargets);
            } catch (_) {
                _renderCorrelationsFallback(el, identifiers);
            }
        }

        async function _fetchLinkedTargets(myIds) {
            const linked = [];
            try {
                const resp = await fetch('/api/targets');
                if (!resp.ok) return linked;
                const data = await resp.json();
                const targets = data.targets || [];
                for (const t of targets) {
                    const tid = t.target_id || '';
                    const corrIds = t.correlated_ids || [];
                    if (myIds.has(tid)) {
                        for (const cid of corrIds) {
                            const ct = targets.find(x => x.target_id === cid);
                            if (ct && !myIds.has(cid)) {
                                linked.push({
                                    target_id: cid,
                                    name: ct.name || cid,
                                    source: ct.source || 'unknown',
                                    asset_type: ct.asset_type || ct.classification || 'unknown',
                                    alliance: ct.alliance || 'unknown',
                                    confidence: t.correlation_confidence || 0,
                                });
                            }
                        }
                        continue;
                    }
                    if (corrIds.some(cid => myIds.has(cid))) {
                        linked.push({
                            target_id: tid,
                            name: t.name || tid,
                            source: t.source || 'unknown',
                            asset_type: t.asset_type || t.classification || 'unknown',
                            alliance: t.alliance || 'unknown',
                            confidence: t.correlation_confidence || 0,
                        });
                    }
                }
            } catch (_) {}
            const seen = new Set();
            return linked.filter(t => {
                if (seen.has(t.target_id)) return false;
                seen.add(t.target_id);
                return true;
            }).slice(0, 15);
        }

        function _findNearbyTargetsFromStore(dossier, myIds) {
            const nearby = [];
            if (typeof TritiumStore === 'undefined' || !TritiumStore.units) return nearby;

            const signals = dossier.signals || [];
            let myLat = null, myLng = null;
            for (const s of signals) {
                if (s.position_x != null && s.position_y != null) {
                    myLat = s.position_y;
                    myLng = s.position_x;
                    break;
                }
            }

            TritiumStore.units.forEach((unit, unitId) => {
                if (myIds.has(unitId)) return;
                const unitSource = unit.source || '';
                const dossierTags = dossier.tags || [];
                const isSameSource = dossierTags.includes(unitSource);
                if (!isSameSource && unit.lat != null && myLat != null) {
                    const dist = Math.sqrt(Math.pow(unit.lat - myLat, 2) + Math.pow((unit.lng || 0) - (myLng || 0), 2));
                    if (dist < 0.001) {
                        nearby.push({
                            target_id: unitId,
                            source: unitSource,
                            name: unit.name || unitId,
                            asset_type: unit.classification || unit.type || 'unknown',
                            distance_m: Math.round(dist * 111320),
                        });
                    }
                }
            });
            return nearby.slice(0, 10);
        }

        function _renderCorrelatedTargets(el, data, identifiers, dossierId) {
            const confirmed = data.correlator_records || [];
            const linked = data.linked || [];
            const nearby = data.nearby_cross_source || [];
            const myTargetIds = data.my_target_ids || [];

            const allianceColors = { friendly: '#05ffa1', hostile: '#ff2a6d', unknown: '#fcee0a' };

            // Build confirmed correlations section
            let confirmedHtml = '';
            if (confirmed.length > 0) {
                confirmedHtml = '<div class="dossier-corr-section-header">CONFIRMED CORRELATIONS</div>' +
                    confirmed.map(c => {
                        const confPct = Math.round((c.confidence || 0) * 100);
                        const confColor = confPct > 70 ? '#05ffa1' : confPct > 40 ? '#fcee0a' : '#ff2a6d';
                        const srcIcon = SOURCE_ICONS[c.source] || '\u{1F4CB}';
                        const strategies = (c.strategies || []).map(s =>
                            `<span class="dossier-corr-strategy">${_esc(s.name)}: ${Math.round(s.score * 100)}%</span>`
                        ).join('');
                        return `<div class="dossier-corr-card dossier-corr-clickable" data-target-id="${_esc(c.target_id)}" title="Click to view dossier">
                            <div class="dossier-corr-card-main">
                                <span class="dossier-corr-icon">${srcIcon}</span>
                                <span class="dossier-corr-id mono">${_esc(c.name || c.target_id)}</span>
                                <span class="dossier-corr-badge">${_esc(c.source)}</span>
                                <span class="dossier-corr-badge">${_esc(c.asset_type)}</span>
                                <span class="dossier-corr-conf mono" style="color:${confColor}">${confPct}%</span>
                            </div>
                            ${strategies ? `<div class="dossier-corr-strategies">${strategies}</div>` : ''}
                            <div class="dossier-corr-reason mono">${_esc(c.reason || '')}</div>
                        </div>`;
                    }).join('');
            }

            // Build linked targets section
            let linkedHtml = '';
            if (linked.length > 0) {
                linkedHtml = '<div class="dossier-corr-section-header">LINKED TARGETS</div>' +
                    linked.map(t => {
                        const srcIcon = SOURCE_ICONS[t.source] || '\u{1F4CB}';
                        const allyColor = allianceColors[t.alliance] || '#888';
                        const confPct = Math.round((t.confidence || 0) * 100);
                        const confColor = confPct > 70 ? '#05ffa1' : confPct > 40 ? '#fcee0a' : '#ff2a6d';
                        return `<div class="dossier-corr-card dossier-corr-clickable" data-target-id="${_esc(t.target_id)}" title="Click to view dossier">
                            <div class="dossier-corr-card-main">
                                <span class="dossier-corr-icon">${srcIcon}</span>
                                <span class="dossier-corr-id mono" style="color:${allyColor}">${_esc(t.name)}</span>
                                <span class="dossier-corr-badge">${_esc(t.source)}</span>
                                <span class="dossier-corr-badge">${_esc(t.asset_type)}</span>
                                ${confPct > 0 ? `<span class="dossier-corr-conf mono" style="color:${confColor}">${confPct}%</span>` : ''}
                            </div>
                            <div class="dossier-corr-reason mono">${_esc(t.reason || '')}</div>
                        </div>`;
                    }).join('');
            }

            // Build nearby cross-source targets section
            let nearbyHtml = '';
            if (nearby.length > 0) {
                nearbyHtml = '<div class="dossier-corr-section-header">NEARBY CROSS-SOURCE TARGETS</div>' +
                    '<div class="dossier-corr-section-desc">Different sensor types detected at the same location — likely the same entity</div>' +
                    nearby.map(t => {
                        const srcIcon = SOURCE_ICONS[t.source] || '\u{1F4CB}';
                        const distLabel = t.distance_m != null ? `${t.distance_m}m` : '';
                        return `<div class="dossier-corr-card dossier-corr-clickable dossier-corr-candidate" data-target-id="${_esc(t.target_id)}" data-dossier-id="${_esc(t.dossier_id || '')}" title="Click to view dossier">
                            <div class="dossier-corr-card-main">
                                <span class="dossier-corr-icon">${srcIcon}</span>
                                <span class="dossier-corr-id mono">${_esc(t.name || t.target_id)}</span>
                                <span class="dossier-corr-badge">${_esc(t.source)}</span>
                                <span class="dossier-corr-badge">${_esc(t.asset_type)}</span>
                                ${distLabel ? `<span class="dossier-corr-dist mono">${distLabel}</span>` : ''}
                            </div>
                            <div class="dossier-corr-reason mono">${_esc(t.reason || '')}</div>
                        </div>`;
                    }).join('');
            }

            // Fused identifiers
            const idEntries = Object.entries(identifiers);
            const idHtml = idEntries.length > 0
                ? `<div class="dossier-corr-section-header" style="margin-top:8px">FUSED IDENTIFIERS</div>` +
                  idEntries.map(([k, v]) =>
                    `<div class="dossier-corr-fused-row">
                        <span class="dossier-corr-fused-type">${_esc(k)}</span>
                        <span class="dossier-corr-fused-val mono">${_esc(String(v))}</span>
                    </div>`
                  ).join('')
                : '';

            // My target IDs
            const myIdsHtml = myTargetIds.length > 0
                ? `<div class="dossier-corr-section-header" style="margin-top:8px">TRACKER TARGET IDS</div>` +
                  myTargetIds.map(tid =>
                    `<div class="dossier-corr-fused-row">
                        <span class="dossier-corr-fused-val mono" style="color:#00f0ff">${_esc(tid)}</span>
                    </div>`
                  ).join('')
                : '';

            const hasContent = confirmedHtml || linkedHtml || nearbyHtml || idHtml;
            el.innerHTML = `
                ${confirmedHtml}
                ${linkedHtml}
                ${nearbyHtml}
                ${idHtml}
                ${myIdsHtml}
                ${!hasContent ? '<div class="dossier-dim">No correlations found -- target has not been fused with other sensor data yet</div>' : ''}
            `;

            // Wire ALL clickable correlation cards
            _wireCorrelationCardClicks(el);
        }

        function _renderCorrelatedTargetsFallback(el, identifiers, linkedTargets, nearbyTargets) {
            const allianceColors = { friendly: '#05ffa1', hostile: '#ff2a6d', unknown: '#fcee0a' };

            let linkedHtml = '';
            if (linkedTargets && linkedTargets.length > 0) {
                linkedHtml = '<div class="dossier-corr-section-header">LINKED TARGETS</div>' +
                    linkedTargets.map(t => {
                        const srcIcon = SOURCE_ICONS[t.source] || '\u{1F4CB}';
                        const allyColor = allianceColors[t.alliance] || '#888';
                        const confPct = Math.round((t.confidence || 0) * 100);
                        const confColor = confPct > 70 ? '#05ffa1' : confPct > 40 ? '#fcee0a' : '#ff2a6d';
                        return `<div class="dossier-corr-card dossier-corr-clickable" data-target-id="${_esc(t.target_id)}" title="Click to view dossier">
                            <div class="dossier-corr-card-main">
                                <span class="dossier-corr-icon">${srcIcon}</span>
                                <span class="dossier-corr-id mono" style="color:${allyColor}">${_esc(t.name)}</span>
                                <span class="dossier-corr-badge">${_esc(t.source)}</span>
                                <span class="dossier-corr-badge">${_esc(t.asset_type)}</span>
                                ${confPct > 0 ? `<span class="dossier-corr-conf mono" style="color:${confColor}">${confPct}%</span>` : ''}
                            </div>
                        </div>`;
                    }).join('');
            }

            let nearbyHtml = '';
            if (nearbyTargets && nearbyTargets.length > 0) {
                nearbyHtml = '<div class="dossier-corr-section-header">NEARBY CROSS-SOURCE TARGETS</div>' +
                    nearbyTargets.map(t => {
                        const srcIcon = SOURCE_ICONS[t.source] || '\u{1F4CB}';
                        const distLabel = t.distance_m != null ? `${t.distance_m}m` : '';
                        return `<div class="dossier-corr-card dossier-corr-clickable dossier-corr-candidate" data-target-id="${_esc(t.target_id)}" title="Click to view dossier">
                            <div class="dossier-corr-card-main">
                                <span class="dossier-corr-icon">${srcIcon}</span>
                                <span class="dossier-corr-id mono">${_esc(t.name || t.target_id)}</span>
                                <span class="dossier-corr-badge">${_esc(t.source)}</span>
                                <span class="dossier-corr-badge">${_esc(t.asset_type)}</span>
                                ${distLabel ? `<span class="dossier-corr-dist mono">${distLabel}</span>` : ''}
                            </div>
                        </div>`;
                    }).join('');
            }

            const idEntries = Object.entries(identifiers);
            const idHtml = idEntries.length > 0
                ? `<div class="dossier-corr-section-header" style="margin-top:8px">FUSED IDENTIFIERS</div>` +
                  idEntries.map(([k, v]) =>
                    `<div class="dossier-corr-fused-row">
                        <span class="dossier-corr-fused-type">${_esc(k)}</span>
                        <span class="dossier-corr-fused-val mono">${_esc(String(v))}</span>
                    </div>`
                  ).join('')
                : '';

            const hasContent = linkedHtml || nearbyHtml || idHtml;
            el.innerHTML = `
                ${linkedHtml}
                ${nearbyHtml}
                ${idHtml}
                ${!hasContent ? '<div class="dossier-dim">No correlations found</div>' : ''}
            `;

            _wireCorrelationCardClicks(el);
        }

        function _wireCorrelationCardClicks(container) {
            container.querySelectorAll('.dossier-corr-clickable').forEach(card => {
                card.style.cursor = 'pointer';
                card.addEventListener('click', async () => {
                    const tid = card.dataset.targetId;
                    const directDossierId = card.dataset.dossierId;
                    if (!tid && !directDossierId) return;

                    // Center the map on this target
                    if (tid) {
                        EventBus.emit('map:centerOnUnit', { id: tid });
                    }

                    // Navigate to the correlated target's dossier
                    if (directDossierId) {
                        loadDetail(directDossierId);
                        EventBus.emit('toast:show', {
                            message: `Navigated to correlated dossier`,
                            type: 'info',
                        });
                        return;
                    }

                    // Search for dossier by target ID
                    if (tid) {
                        try {
                            const resp = await fetch(`/api/dossiers/search?q=${encodeURIComponent(tid)}`);
                            if (resp.ok) {
                                const data = await resp.json();
                                const results = data.results || [];
                                if (results.length > 0) {
                                    loadDetail(results[0].dossier_id);
                                    EventBus.emit('toast:show', {
                                        message: `Navigated to dossier for ${tid.substring(0, 20)}`,
                                        type: 'info',
                                    });
                                } else {
                                    EventBus.emit('toast:show', {
                                        message: `No dossier found for ${tid.substring(0, 20)}`,
                                        type: 'alert',
                                    });
                                }
                            }
                        } catch (_) {}
                    }
                });
            });
        }

        function _renderCorrelationsFallback(el, identifiers) {
            const entries = Object.entries(identifiers);
            if (entries.length === 0) {
                el.innerHTML = '<div class="dossier-dim">No correlation data available</div>';
                return;
            }
            el.innerHTML = `
                <div class="dossier-corr-section-header">FUSED IDENTIFIERS</div>
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
                    // Look up dossier by target_id — use fields=summary to avoid
                    // loading thousands of signals just to get the dossier_id
                    try {
                        const resp = await fetch(`/api/dossiers/by-target?target_id=${encodeURIComponent(data.target_id)}&fields=summary`);
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

.dossier-corr-candidate {
    background: rgba(252, 238, 10, 0.04);
    border-color: rgba(252, 238, 10, 0.12);
}

.dossier-corr-icon {
    font-size: 0.65rem;
    flex-shrink: 0;
}

.dossier-linked-target {
    background: rgba(0, 240, 255, 0.06);
    border-color: rgba(0, 240, 255, 0.18);
    transition: background 0.15s;
}
.dossier-linked-target:hover {
    background: rgba(0, 240, 255, 0.14);
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

/* Show Trail / Show Correlations buttons in section headers */
.dossier-show-trail-btn,
.dossier-show-corr-btn {
    font-size: 0.4rem !important;
    padding: 1px 6px !important;
    line-height: 1.4;
    letter-spacing: 0.03em;
}

/* Clickable correlation cards */
.dossier-corr-clickable {
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
}
.dossier-corr-clickable:hover {
    background: rgba(0, 240, 255, 0.12);
    border-color: rgba(0, 240, 255, 0.5);
    box-shadow: 0 0 6px rgba(0, 240, 255, 0.15);
}

/* Correlation section header */
.dossier-corr-section-header {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    color: #00f0ff;
    margin: 6px 0 3px 0;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
    padding-bottom: 2px;
}

/* Section description text */
.dossier-corr-section-desc {
    font-size: 0.45rem;
    color: rgba(224, 224, 224, 0.5);
    margin-bottom: 4px;
    font-style: italic;
}

/* Card main row layout */
.dossier-corr-card-main {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
}

/* Source/type badge */
.dossier-corr-badge {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.45rem;
    color: rgba(0, 240, 255, 0.7);
    background: rgba(0, 240, 255, 0.08);
    border: 1px solid rgba(0, 240, 255, 0.15);
    border-radius: 3px;
    padding: 0 4px;
    letter-spacing: 0.03em;
}

/* Strategy breakdown */
.dossier-corr-strategies {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
    margin-top: 2px;
}

.dossier-corr-strategy {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.4rem;
    color: rgba(5, 255, 161, 0.7);
    background: rgba(5, 255, 161, 0.06);
    border: 1px solid rgba(5, 255, 161, 0.12);
    border-radius: 2px;
    padding: 0 3px;
}

/* Reason text */
.dossier-corr-reason {
    font-size: 0.42rem;
    color: rgba(224, 224, 224, 0.4);
    margin-top: 1px;
    word-break: break-all;
}

/* Distance label */
.dossier-corr-dist {
    font-size: 0.5rem;
    color: #fcee0a;
    font-weight: 600;
}

/* Candidate (nearby cross-source) — yellow tint */
.dossier-corr-candidate.dossier-corr-clickable:hover {
    background: rgba(252, 238, 10, 0.12);
    border-color: rgba(252, 238, 10, 0.4);
    box-shadow: 0 0 6px rgba(252, 238, 10, 0.12);
}

/* Signal chart canvas hover */
.dossier-signal-chart {
    cursor: crosshair;
}
`;
document.head.appendChild(style);
