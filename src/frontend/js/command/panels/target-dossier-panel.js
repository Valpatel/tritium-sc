// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Dossier Panel — focused single-target intelligence view
// Opens when a user clicks a target on the map. Shows identity, signals,
// history timeline, associations, threat assessment, and behavioral profile
// in collapsible sections. Fetches from /api/targets/{id}, /api/dossiers/by-target,
// /api/dossiers/{id}/signal-history, /api/dossiers/{id}/behavioral-profile,
// /api/dossiers/{id}/correlated-targets.

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';
import { _esc, _timeAgo } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile: '#ff2a6d',
    neutral: '#fcee0a',
    unknown: '#888',
};

const SOURCE_COLORS = {
    ble: '#00f0ff',
    wifi: '#05ffa1',
    yolo: '#ff2a6d',
    camera: '#ff2a6d',
    mesh: '#fcee0a',
    meshtastic: '#fcee0a',
    correlator: '#ff8c00',
    manual: '#e0e0e0',
    mqtt: '#9b59b6',
    acoustic: '#e74c3c',
    enrichment: '#3498db',
    simulation: '#00f0ff',
};

const THREAT_COLORS = {
    none: '#888',
    low: '#05ffa1',
    medium: '#fcee0a',
    high: '#ff8c00',
    critical: '#ff2a6d',
};

const TYPE_BADGES = {
    person: { label: 'PER', color: '#00f0ff' },
    vehicle: { label: 'VEH', color: '#fcee0a' },
    device: { label: 'DEV', color: '#05ffa1' },
    animal: { label: 'ANM', color: '#ff8c00' },
    unknown: { label: 'UNK', color: '#888' },
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _formatTs(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleString(undefined, {
        month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
}

function _sourceColor(source) {
    return SOURCE_COLORS[source] || '#888';
}

function _confColor(pct) {
    if (pct >= 80) return '#05ffa1';
    if (pct >= 50) return '#fcee0a';
    return '#ff2a6d';
}

function _threatLabel(level) {
    return (level || 'none').toUpperCase();
}

// ---------------------------------------------------------------------------
// Panel definition
// ---------------------------------------------------------------------------

export const TargetDossierPanelDef = {
    id: 'target-dossier',
    title: 'TARGET DOSSIER',
    defaultPosition: { x: null, y: 16 },
    defaultSize: { w: 420, h: 600 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'tdp-root';
        el.innerHTML = `
            <div class="tdp-placeholder" data-bind="tdp-placeholder">
                <div class="tdp-placeholder-icon">&#x1F50D;</div>
                <div class="tdp-placeholder-text">Click a target on the map to view its dossier</div>
            </div>
            <div class="tdp-content" data-bind="tdp-content" style="display:none">
                <div class="tdp-header" data-bind="tdp-header"></div>
                <div class="tdp-scroll" data-bind="tdp-scroll"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const placeholderEl = bodyEl.querySelector('[data-bind="tdp-placeholder"]');
        const contentEl = bodyEl.querySelector('[data-bind="tdp-content"]');
        const headerEl = bodyEl.querySelector('[data-bind="tdp-header"]');
        const scrollEl = bodyEl.querySelector('[data-bind="tdp-scroll"]');

        let currentTargetId = null;
        let refreshTimer = null;

        // -----------------------------------------------------------------
        // Load target dossier
        // -----------------------------------------------------------------
        async function loadTarget(targetId) {
            if (!targetId) return;
            currentTargetId = targetId;

            placeholderEl.style.display = 'none';
            contentEl.style.display = 'flex';

            // Show loading state
            headerEl.innerHTML = `<div class="tdp-loading"><span class="panel-spinner"></span> Loading dossier for ${_esc(targetId.substring(0, 24))}...</div>`;
            scrollEl.innerHTML = '';

            // Get live unit data from store
            const unit = TritiumStore.units.get(targetId);

            // Fetch dossier data in parallel
            const [dossier, target] = await Promise.all([
                _fetchDossier(targetId),
                _fetchTarget(targetId),
            ]);

            // Merge data sources: live unit > API target > dossier
            const data = _mergeData(targetId, unit, target, dossier);
            renderHeader(data);
            renderSections(data, scrollEl);
        }

        async function _fetchDossier(targetId) {
            try {
                const resp = await fetch(`/api/dossiers/by-target?target_id=${encodeURIComponent(targetId)}`);
                if (resp.ok) return await resp.json();
            } catch (_) { /* skip */ }
            return null;
        }

        async function _fetchTarget(targetId) {
            try {
                const resp = await fetch(`/api/targets/${encodeURIComponent(targetId)}`);
                if (resp.ok) return await resp.json();
            } catch (_) { /* skip */ }
            return null;
        }

        function _mergeData(targetId, unit, target, dossier) {
            const d = {
                targetId,
                // Identity
                name: unit?.name || target?.name || dossier?.name || targetId,
                alliance: unit?.alliance || target?.alliance || dossier?.alliance || 'unknown',
                assetType: unit?.asset_type || unit?.type || target?.asset_type || dossier?.entity_type || 'unknown',
                source: unit?.source || target?.source || 'unknown',
                classification: unit?.classification || unit?.device_class || target?.classification || dossier?.entity_type || '',
                manufacturer: unit?.manufacturer || unit?.oui || target?.manufacturer || '',

                // Identifiers
                mac: unit?.mac || '',
                ssid: unit?.ssid || '',
                bssid: unit?.bssid || '',
                deviceId: unit?.device_id || '',
                dossierIdentifiers: dossier?.identifiers || {},

                // Signal
                rssi: unit?.rssi ?? unit?.signal_strength ?? target?.rssi ?? null,
                confidence: unit?.confidence ?? target?.confidence ?? dossier?.confidence ?? null,
                speed: unit?.speed ?? target?.speed ?? null,
                heading: unit?.heading ?? target?.heading ?? null,
                lat: unit?.lat ?? target?.lat ?? null,
                lng: unit?.lng ?? target?.lng ?? null,

                // Status
                health: unit?.health ?? null,
                fsmState: unit?.fsm_state || unit?.state || '',
                correlatedIds: unit?.correlated_ids || target?.correlated_ids || [],
                correlationConfidence: unit?.correlation_confidence ?? null,

                // Dossier
                dossierId: dossier?.dossier_id || null,
                threatLevel: dossier?.threat_level || 'none',
                signals: dossier?.signals || [],
                enrichments: dossier?.enrichments || [],
                positionHistory: dossier?.position_history || [],
                tags: dossier?.tags || [],
                notes: dossier?.notes || [],
                firstSeen: dossier?.first_seen || null,
                lastSeen: dossier?.last_seen || null,
                signalCount: dossier?.signal_count || dossier?.signal_total || (dossier?.signals || []).length,

                // Raw refs
                _unit: unit,
                _dossier: dossier,
                _target: target,
            };
            return d;
        }

        // -----------------------------------------------------------------
        // Render header
        // -----------------------------------------------------------------
        function renderHeader(data) {
            const allianceColor = ALLIANCE_COLORS[data.alliance.toLowerCase()] || '#888';
            const threatColor = THREAT_COLORS[data.threatLevel] || '#888';
            const badge = TYPE_BADGES[data.assetType] || TYPE_BADGES.unknown;
            const confPct = data.confidence != null ? Math.round(data.confidence * 100) : null;

            headerEl.innerHTML = `
                <div class="tdp-header-main" style="border-left: 3px solid ${allianceColor}">
                    <div class="tdp-header-top">
                        <span class="tdp-type-badge" style="color:${badge.color};border-color:${badge.color}">${badge.label}</span>
                        <span class="tdp-name">${_esc(data.name)}</span>
                        <span class="tdp-threat-badge" style="background:${threatColor}">${_threatLabel(data.threatLevel)}</span>
                    </div>
                    <div class="tdp-header-sub">
                        <span class="tdp-alliance-badge" style="color:${allianceColor}">${data.alliance.toUpperCase()}</span>
                        <span class="tdp-source-badge">${_esc(data.source)}</span>
                        ${data.classification ? `<span class="tdp-class-badge">${_esc(data.classification)}</span>` : ''}
                        ${confPct != null ? `<span class="tdp-conf-badge" style="color:${_confColor(confPct)}">${confPct}%</span>` : ''}
                    </div>
                    <div class="tdp-target-id mono">${_esc(data.targetId)}</div>
                </div>
            `;
        }

        // -----------------------------------------------------------------
        // Render all collapsible sections
        // -----------------------------------------------------------------
        function renderSections(data, container) {
            container.innerHTML = '';

            // Section 1: Identity & Identifiers
            container.appendChild(_buildSection('IDENTITY', true, () => _renderIdentity(data)));

            // Section 2: Live Signal & Status
            container.appendChild(_buildSection('SIGNAL & STATUS', true, () => _renderSignalStatus(data)));

            // Section 3: Signal History (async)
            if (data.dossierId) {
                const historySection = _buildSection('SIGNAL HISTORY', true, () => {
                    const el = document.createElement('div');
                    el.className = 'tdp-signal-history';
                    el.innerHTML = '<div class="tdp-dim"><span class="panel-spinner"></span> Loading...</div>';
                    _loadSignalHistory(el, data.dossierId);
                    return el;
                });
                container.appendChild(historySection);
            }

            // Section 4: Sighting Timeline
            if (data.signals.length > 0) {
                container.appendChild(_buildSection(`SIGHTINGS (${data.signals.length})`, false, () => _renderTimeline(data)));
            }

            // Section 5: Associations / Correlations
            container.appendChild(_buildSection('ASSOCIATIONS', true, () => {
                const el = document.createElement('div');
                el.className = 'tdp-associations';
                _renderAssociations(el, data);
                return el;
            }));

            // Section 6: Behavioral Profile (async)
            if (data.dossierId) {
                container.appendChild(_buildSection('BEHAVIORAL PROFILE', false, () => {
                    const el = document.createElement('div');
                    el.className = 'tdp-behavioral';
                    el.innerHTML = '<div class="tdp-dim"><span class="panel-spinner"></span> Loading...</div>';
                    _loadBehavioralProfile(el, data.dossierId);
                    return el;
                }));
            }

            // Section 7: Threat Assessment
            container.appendChild(_buildSection('THREAT ASSESSMENT', true, () => _renderThreatAssessment(data)));

            // Section 8: Enrichments
            if (data.enrichments.length > 0) {
                container.appendChild(_buildSection(`ENRICHMENTS (${data.enrichments.length})`, false, () => _renderEnrichments(data)));
            }

            // Section 9: Tags & Notes
            if (data.dossierId) {
                container.appendChild(_buildSection('TAGS & NOTES', false, () => _renderTagsNotes(data)));
            }

            // Section 10: Quick Actions
            container.appendChild(_buildSection('ACTIONS', true, () => _renderActions(data)));
        }

        // -----------------------------------------------------------------
        // Collapsible section builder
        // -----------------------------------------------------------------
        function _buildSection(title, expanded, contentFn) {
            const section = document.createElement('div');
            section.className = 'tdp-section';

            const header = document.createElement('div');
            header.className = 'tdp-section-header';
            header.innerHTML = `
                <span class="tdp-section-arrow">${expanded ? '\u25BC' : '\u25B6'}</span>
                <span class="tdp-section-title">${_esc(title)}</span>
            `;

            const body = document.createElement('div');
            body.className = 'tdp-section-body';
            body.style.display = expanded ? 'block' : 'none';

            let loaded = false;

            function ensureContent() {
                if (!loaded) {
                    const content = contentFn();
                    if (content instanceof HTMLElement) {
                        body.appendChild(content);
                    } else {
                        body.innerHTML = content;
                    }
                    loaded = true;
                }
            }

            if (expanded) ensureContent();

            header.addEventListener('click', () => {
                const isOpen = body.style.display !== 'none';
                body.style.display = isOpen ? 'none' : 'block';
                header.querySelector('.tdp-section-arrow').textContent = isOpen ? '\u25B6' : '\u25BC';
                if (!isOpen) ensureContent();
            });

            section.appendChild(header);
            section.appendChild(body);
            return section;
        }

        // -----------------------------------------------------------------
        // Section renderers
        // -----------------------------------------------------------------

        function _renderIdentity(data) {
            const el = document.createElement('div');
            el.className = 'tdp-identity';

            const rows = [];
            rows.push(_kvRow('TARGET ID', data.targetId));
            if (data.mac) rows.push(_kvRow('MAC', data.mac));
            if (data.deviceId) rows.push(_kvRow('DEVICE ID', data.deviceId));
            if (data.manufacturer) rows.push(_kvRow('MANUFACTURER', data.manufacturer));
            if (data.ssid) rows.push(_kvRow('SSID', data.ssid));
            if (data.bssid) rows.push(_kvRow('BSSID', data.bssid));
            if (data.classification) rows.push(_kvRow('CLASS', data.classification));

            // Dossier identifiers
            for (const [k, v] of Object.entries(data.dossierIdentifiers)) {
                rows.push(_kvRow(k.toUpperCase(), String(v)));
            }

            if (data.firstSeen) rows.push(_kvRow('FIRST SEEN', _formatTs(data.firstSeen)));
            if (data.lastSeen) rows.push(_kvRow('LAST SEEN', _formatTs(data.lastSeen)));

            el.innerHTML = rows.join('');
            return el;
        }

        function _renderSignalStatus(data) {
            const el = document.createElement('div');
            el.className = 'tdp-signal-status';

            const rssiVal = data.rssi != null ? `${data.rssi} dBm` : '--';
            const confVal = data.confidence != null ? `${Math.round(data.confidence * 100)}%` : '--';
            const speedVal = data.speed != null ? `${data.speed.toFixed(1)} m/s` : '--';
            const hdgVal = data.heading != null ? `${Math.round(data.heading)}\u00B0` : '--';
            const healthVal = data.health != null ? `${Math.round(data.health)}%` : '--';
            const posVal = data.lat != null ? `${data.lat.toFixed(6)}, ${data.lng.toFixed(6)}` : '--';

            el.innerHTML = `
                <div class="tdp-stats-grid">
                    <div class="tdp-stat"><div class="tdp-stat-label">RSSI</div><div class="tdp-stat-value mono">${rssiVal}</div></div>
                    <div class="tdp-stat"><div class="tdp-stat-label">CONFIDENCE</div><div class="tdp-stat-value mono">${confVal}</div></div>
                    <div class="tdp-stat"><div class="tdp-stat-label">SPEED</div><div class="tdp-stat-value mono">${speedVal}</div></div>
                    <div class="tdp-stat"><div class="tdp-stat-label">HEADING</div><div class="tdp-stat-value mono">${hdgVal}</div></div>
                    <div class="tdp-stat"><div class="tdp-stat-label">HEALTH</div><div class="tdp-stat-value mono">${healthVal}</div></div>
                    <div class="tdp-stat"><div class="tdp-stat-label">STATE</div><div class="tdp-stat-value mono">${_esc(data.fsmState || '--')}</div></div>
                </div>
                <div class="tdp-pos-row">
                    <span class="tdp-pos-label">POSITION</span>
                    <span class="tdp-pos-value mono">${posVal}</span>
                </div>
            `;
            return el;
        }

        async function _loadSignalHistory(el, dossierId) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/signal-history?limit=200`);
                if (!resp.ok) {
                    if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Signal history unavailable</div>';
                    return;
                }
                const data = await resp.json();
                const timeline = data.timeline || [];
                if (timeline.length === 0) {
                    if (el.isConnected) el.innerHTML = '<div class="tdp-dim">No signal history data</div>';
                    return;
                }
                if (el.isConnected) _drawSparkline(el, timeline);
            } catch (_) {
                if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Failed to load signal history</div>';
            }
        }

        function _drawSparkline(container, timeline) {
            const canvas = document.createElement('canvas');
            canvas.className = 'tdp-sparkline-canvas';
            canvas.width = 380;
            canvas.height = 100;
            container.innerHTML = '';
            container.appendChild(canvas);

            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            const pad = { top: 14, right: 10, bottom: 18, left: 36 };
            const plotW = w - pad.left - pad.right;
            const plotH = h - pad.top - pad.bottom;

            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            // Determine RSSI vs confidence
            const rssiPoints = timeline.filter(t => t.rssi != null).map(t => ({ ts: t.timestamp, value: t.rssi })).sort((a, b) => a.ts - b.ts);
            const confPoints = timeline.filter(t => t.confidence != null).map(t => ({ ts: t.timestamp, value: Math.round(t.confidence * 100) })).sort((a, b) => a.ts - b.ts);
            const useRssi = rssiPoints.length > 0;
            const points = useRssi ? rssiPoints : confPoints;
            const chartColor = useRssi ? '#00f0ff' : '#05ffa1';
            const unitLabel = useRssi ? 'dBm' : '%';
            const chartTitle = useRssi ? 'RSSI (dBm) over time' : 'Detection Confidence (%) over time';

            if (points.length === 0) {
                ctx.fillStyle = 'rgba(224,224,224,0.25)';
                ctx.font = '9px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('No signal data', w / 2, h / 2);
                return;
            }

            let minVal = Infinity, maxVal = -Infinity, minTs = Infinity, maxTs = -Infinity;
            for (const p of points) {
                if (p.value < minVal) minVal = p.value;
                if (p.value > maxVal) maxVal = p.value;
                if (p.ts < minTs) minTs = p.ts;
                if (p.ts > maxTs) maxTs = p.ts;
            }
            if (maxVal === minVal) { maxVal += 5; minVal -= 5; }
            if (maxTs === minTs) maxTs = minTs + 60;

            const tsRange = maxTs - minTs;
            const valRange = maxVal - minVal;
            function toX(ts) { return pad.left + ((ts - minTs) / tsRange) * plotW; }
            function toY(val) { return pad.top + plotH - ((val - minVal) / valRange) * plotH; }

            // Title
            ctx.fillStyle = chartColor;
            ctx.font = '8px monospace';
            ctx.textAlign = 'left';
            ctx.fillText(chartTitle, pad.left, 10);

            // Grid
            ctx.strokeStyle = `rgba(${useRssi ? '0,240,255' : '5,255,161'}, 0.08)`;
            ctx.lineWidth = 0.5;
            const gridStep = useRssi ? 10 : 20;
            for (let r = Math.ceil(minVal / gridStep) * gridStep; r <= maxVal; r += gridStep) {
                const y = toY(r);
                ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(w - pad.right, y); ctx.stroke();
                ctx.fillStyle = 'rgba(224,224,224,0.3)';
                ctx.font = '7px monospace';
                ctx.textAlign = 'right';
                ctx.fillText(`${r}`, pad.left - 3, y + 3);
            }

            // Time labels
            const nowTs = Date.now() / 1000;
            const _relTime = (ts) => {
                const diff = nowTs - ts;
                if (diff < 60) return `${Math.round(diff)}s`;
                if (diff < 3600) return `${Math.round(diff / 60)}m`;
                if (diff < 86400) return `${(diff / 3600).toFixed(1)}h`;
                return `${Math.round(diff / 86400)}d`;
            };
            ctx.fillStyle = 'rgba(224,224,224,0.3)';
            ctx.font = '7px monospace';
            ctx.textAlign = 'center';
            for (let i = 0; i < 4; i++) {
                const frac = i / 3;
                const ts = minTs + frac * tsRange;
                ctx.fillText(_relTime(ts) + ' ago', toX(ts), h - 3);
            }

            // Gradient fill
            const gradRgb = useRssi ? '0,240,255' : '5,255,161';
            const gradient = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
            gradient.addColorStop(0, `rgba(${gradRgb}, 0.15)`);
            gradient.addColorStop(1, `rgba(${gradRgb}, 0.01)`);
            ctx.beginPath();
            ctx.moveTo(toX(points[0].ts), toY(points[0].value));
            for (let i = 1; i < points.length; i++) ctx.lineTo(toX(points[i].ts), toY(points[i].value));
            ctx.lineTo(toX(points[points.length - 1].ts), pad.top + plotH);
            ctx.lineTo(toX(points[0].ts), pad.top + plotH);
            ctx.closePath();
            ctx.fillStyle = gradient;
            ctx.fill();

            // Line
            ctx.beginPath();
            ctx.strokeStyle = chartColor;
            ctx.lineWidth = 1.5;
            ctx.moveTo(toX(points[0].ts), toY(points[0].value));
            for (let i = 1; i < points.length; i++) ctx.lineTo(toX(points[i].ts), toY(points[i].value));
            ctx.stroke();

            // Dots
            const step = Math.max(1, Math.floor(points.length / 30));
            for (let i = 0; i < points.length; i += step) {
                const x = toX(points[i].ts), y = toY(points[i].value);
                ctx.fillStyle = useRssi
                    ? (points[i].value > -50 ? '#05ffa1' : points[i].value > -70 ? '#fcee0a' : '#ff2a6d')
                    : (points[i].value > 70 ? '#05ffa1' : points[i].value > 40 ? '#fcee0a' : '#ff2a6d');
                ctx.beginPath(); ctx.arc(x, y, 2, 0, Math.PI * 2); ctx.fill();
            }
            // Last point
            if (points.length > 1) {
                const last = points[points.length - 1];
                ctx.fillStyle = chartColor;
                ctx.beginPath(); ctx.arc(toX(last.ts), toY(last.value), 3, 0, Math.PI * 2); ctx.fill();
                ctx.font = '7px monospace';
                ctx.textAlign = 'left';
                ctx.fillText(`${last.value} ${unitLabel}`, toX(last.ts) + 5, toY(last.value) + 3);
            }
        }

        function _renderTimeline(data) {
            const el = document.createElement('div');
            el.className = 'tdp-timeline';

            const signals = data.signals.slice(0, 50);
            el.innerHTML = signals.map((s, i) => {
                const color = _sourceColor(s.source || 'unknown');
                const confPct = Math.round((s.confidence || 0) * 100);
                const isLast = i === signals.length - 1;
                return `<div class="tdp-tl-event">
                    <div class="tdp-tl-marker-col">
                        <div class="tdp-tl-dot" style="background:${color};box-shadow:0 0 6px ${color}"></div>
                        ${!isLast ? '<div class="tdp-tl-line"></div>' : ''}
                    </div>
                    <div class="tdp-tl-content">
                        <div class="tdp-tl-header">
                            <span style="color:${color};font-weight:700;text-transform:uppercase;font-size:0.5rem">${_esc(s.source || 'unknown')}</span>
                            <span class="tdp-tl-type">${_esc(s.signal_type || '')}</span>
                            <span class="tdp-tl-conf">${confPct}%</span>
                        </div>
                        <div class="tdp-tl-time mono">${_formatTs(s.timestamp)}</div>
                    </div>
                </div>`;
            }).join('');

            if (data.signalCount > 50) {
                el.innerHTML += `<div class="tdp-tl-more">... and ${data.signalCount - 50} more signals</div>`;
            }

            return el;
        }

        function _renderAssociations(el, data) {
            // Correlated IDs from live data
            const correlatedIds = data.correlatedIds || [];
            let html = '';

            if (correlatedIds.length > 0) {
                html += '<div class="tdp-assoc-header">CORRELATED TARGETS</div>';
                html += correlatedIds.map(cid => {
                    const linkedUnit = TritiumStore.units.get(cid);
                    const srcBadge = linkedUnit ? `<span class="tdp-assoc-badge" style="color:${_sourceColor(linkedUnit.source)}">${_esc(linkedUnit.source || '')}</span>` : '';
                    const typeBadge = linkedUnit ? `<span class="tdp-assoc-badge">${_esc(linkedUnit.asset_type || linkedUnit.type || '')}</span>` : '';
                    const name = linkedUnit?.name || cid;
                    const truncId = cid.length > 28 ? cid.substring(0, 26) + '..' : cid;
                    return `<div class="tdp-assoc-card" data-target-id="${_esc(cid)}" title="Click to view ${_esc(cid)}">
                        <span class="tdp-assoc-id mono">${_esc(truncId)}</span>
                        ${srcBadge}${typeBadge}
                    </div>`;
                }).join('');
            }

            // Also try fetching full correlation data from API if we have a dossier
            if (data.dossierId) {
                _fetchCorrelations(el, data);
            } else if (correlatedIds.length === 0) {
                el.innerHTML = '<div class="tdp-dim">No associations found</div>';
            } else {
                el.innerHTML = html;
                _wireAssociationClicks(el);
            }
        }

        async function _fetchCorrelations(el, data) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(data.dossierId)}/correlated-targets`);
                if (!resp.ok) {
                    if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Correlation data unavailable</div>';
                    return;
                }
                const corrData = await resp.json();
                if (!el.isConnected) return;
                _renderFullCorrelations(el, corrData, data);
            } catch (_) {
                if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Failed to load correlations</div>';
            }
        }

        function _renderFullCorrelations(el, corrData, data) {
            const confirmed = corrData.correlator_records || [];
            const linked = corrData.linked || [];
            const nearby = corrData.nearby_cross_source || [];
            const total = confirmed.length + linked.length + nearby.length;

            if (total === 0 && (data.correlatedIds || []).length === 0) {
                el.innerHTML = '<div class="tdp-dim">No associations found -- target has not been fused with other sensors yet</div>';
                return;
            }

            let html = '';

            if (confirmed.length > 0) {
                html += '<div class="tdp-assoc-header">CONFIRMED CORRELATIONS</div>';
                html += confirmed.map(c => _corrCard(c)).join('');
            }

            if (linked.length > 0) {
                html += '<div class="tdp-assoc-header">LINKED TARGETS</div>';
                html += linked.map(c => _corrCard(c)).join('');
            }

            if (nearby.length > 0) {
                html += '<div class="tdp-assoc-header">NEARBY CROSS-SOURCE</div>';
                html += nearby.map(c => _corrCard(c)).join('');
            }

            // Include live correlated IDs not already shown
            const shownIds = new Set([...confirmed, ...linked, ...nearby].map(c => c.target_id));
            const extra = (data.correlatedIds || []).filter(id => !shownIds.has(id));
            if (extra.length > 0) {
                html += '<div class="tdp-assoc-header">LIVE CORRELATED IDS</div>';
                html += extra.map(cid => {
                    const u = TritiumStore.units.get(cid);
                    return `<div class="tdp-assoc-card" data-target-id="${_esc(cid)}">
                        <span class="tdp-assoc-id mono">${_esc(cid.length > 28 ? cid.substring(0, 26) + '..' : cid)}</span>
                        ${u ? `<span class="tdp-assoc-badge">${_esc(u.source || '')}</span>` : ''}
                    </div>`;
                }).join('');
            }

            el.innerHTML = html;
            _wireAssociationClicks(el);
        }

        function _corrCard(c) {
            const confPct = Math.round((c.confidence || 0) * 100);
            const confColor = _confColor(confPct);
            const srcColor = _sourceColor(c.source);
            return `<div class="tdp-assoc-card" data-target-id="${_esc(c.target_id || '')}">
                <span class="tdp-assoc-id mono" style="color:${srcColor}">${_esc(c.name || c.target_id || '')}</span>
                <span class="tdp-assoc-badge">${_esc(c.source || '')}</span>
                <span class="tdp-assoc-badge">${_esc(c.asset_type || '')}</span>
                ${confPct > 0 ? `<span class="tdp-assoc-conf mono" style="color:${confColor}">${confPct}%</span>` : ''}
                ${c.reason ? `<div class="tdp-assoc-reason mono">${_esc(c.reason)}</div>` : ''}
            </div>`;
        }

        function _wireAssociationClicks(container) {
            container.querySelectorAll('.tdp-assoc-card[data-target-id]').forEach(card => {
                card.style.cursor = 'pointer';
                card.addEventListener('click', () => {
                    const tid = card.dataset.targetId;
                    if (!tid) return;
                    EventBus.emit('map:centerOnUnit', { id: tid });
                    loadTarget(tid);
                });
            });
        }

        async function _loadBehavioralProfile(el, dossierId) {
            try {
                const resp = await fetch(`/api/dossiers/${encodeURIComponent(dossierId)}/behavioral-profile`);
                if (!resp.ok) {
                    if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Behavioral data unavailable</div>';
                    return;
                }
                const profile = await resp.json();
                if (!el.isConnected) return;

                const pattern = profile.movement_pattern || 'unknown';
                const patternColors = { stationary: '#05ffa1', mobile: '#00f0ff', erratic: '#ff2a6d', patrol: '#fcee0a', unknown: '#888' };
                const patternColor = patternColors[pattern] || '#888';
                const avgSpeed = (profile.average_speed || 0).toFixed(1);
                const maxSpeed = (profile.max_speed || 0).toFixed(1);
                const sigCount = profile.signal_count || 0;
                const duration = profile.active_duration_s || 0;
                const durStr = duration > 3600 ? `${(duration / 3600).toFixed(1)}h` : duration > 60 ? `${Math.round(duration / 60)}m` : `${duration}s`;

                const srcBreakdown = profile.source_breakdown || {};
                const srcChips = Object.entries(srcBreakdown).map(([src, count]) =>
                    `<span class="tdp-src-chip" style="border-color:${_sourceColor(src)}">${_esc(src)}: ${count}</span>`
                ).join('') || '';

                const rssi = profile.rssi_stats || {};
                const rssiHtml = rssi.min != null
                    ? `<div class="tdp-rssi-stats mono">
                        Min: <span style="color:#ff2a6d">${rssi.min}dBm</span>
                        Avg: <span style="color:#fcee0a">${(rssi.mean || rssi.avg || 0).toFixed(0)}dBm</span>
                        Max: <span style="color:#05ffa1">${rssi.max}dBm</span>
                    </div>`
                    : '';

                el.innerHTML = `
                    <div class="tdp-behavior-badge" style="color:${patternColor};border-color:${patternColor}">${_esc(pattern).toUpperCase()}</div>
                    <div class="tdp-behavior-stats mono">
                        <span>Avg Speed: ${avgSpeed} m/s</span>
                        <span>Max Speed: ${maxSpeed} m/s</span>
                        <span>Signals: ${sigCount}</span>
                        <span>Active: ${durStr}</span>
                    </div>
                    ${rssiHtml}
                    ${srcChips ? `<div class="tdp-src-breakdown">${srcChips}</div>` : ''}
                `;
            } catch (_) {
                if (el.isConnected) el.innerHTML = '<div class="tdp-dim">Failed to load behavioral profile</div>';
            }
        }

        function _renderThreatAssessment(data) {
            const el = document.createElement('div');
            el.className = 'tdp-threat';

            const threatColor = THREAT_COLORS[data.threatLevel] || '#888';
            const confPct = data.confidence != null ? Math.round(data.confidence * 100) : 0;

            // Compute a threat score from available data
            let threatScore = 0;
            const indicators = [];

            // Alliance-based
            if (data.alliance === 'hostile') { threatScore += 40; indicators.push('Classified hostile'); }
            else if (data.alliance === 'unknown') { threatScore += 10; indicators.push('Unknown alliance'); }

            // Dossier threat level
            if (data.threatLevel === 'critical') { threatScore += 30; indicators.push('Critical threat level'); }
            else if (data.threatLevel === 'high') { threatScore += 20; indicators.push('High threat level'); }
            else if (data.threatLevel === 'medium') { threatScore += 10; indicators.push('Medium threat level'); }

            // Low confidence
            if (confPct > 0 && confPct < 40) { threatScore += 10; indicators.push('Low identification confidence'); }

            // High speed (evasive behavior)
            if (data.speed != null && data.speed > 5) { threatScore += 10; indicators.push(`High speed: ${data.speed.toFixed(1)} m/s`); }

            // Signal count (persistence)
            if (data.signalCount > 100) { threatScore += 5; indicators.push(`${data.signalCount} signals (persistent presence)`); }

            // Correlated targets
            if (data.correlatedIds.length > 3) { threatScore += 5; indicators.push(`${data.correlatedIds.length} correlated targets`); }

            threatScore = Math.min(100, threatScore);
            const scoreColor = threatScore >= 70 ? '#ff2a6d' : threatScore >= 40 ? '#fcee0a' : '#05ffa1';

            el.innerHTML = `
                <div class="tdp-threat-header">
                    <div class="tdp-threat-score-wrap">
                        <div class="tdp-threat-score-label">THREAT SCORE</div>
                        <div class="tdp-threat-score" style="color:${scoreColor}">${threatScore}</div>
                    </div>
                    <div class="tdp-threat-level-wrap">
                        <div class="tdp-threat-level-label">LEVEL</div>
                        <div class="tdp-threat-level-val" style="color:${threatColor}">${_threatLabel(data.threatLevel)}</div>
                    </div>
                </div>
                <div class="tdp-threat-bar-track">
                    <div class="tdp-threat-bar-fill" style="width:${threatScore}%;background:${scoreColor}"></div>
                </div>
                ${indicators.length > 0 ? `
                <div class="tdp-threat-indicators">
                    <div class="tdp-threat-ind-title">INDICATORS</div>
                    ${indicators.map(ind => `<div class="tdp-threat-ind">\u2022 ${_esc(ind)}</div>`).join('')}
                </div>` : ''}
            `;
            return el;
        }

        function _renderEnrichments(data) {
            const el = document.createElement('div');
            el.className = 'tdp-enrichments';

            el.innerHTML = data.enrichments.map(e => {
                const dataEntries = Object.entries(e.data || {}).slice(0, 6)
                    .map(([k, v]) => `<div class="tdp-enrich-kv"><span class="tdp-enrich-key">${_esc(k)}</span><span class="tdp-enrich-val">${_esc(String(v).substring(0, 80))}</span></div>`)
                    .join('');
                return `<div class="tdp-enrich-card">
                    <div class="tdp-enrich-header">${_esc(e.provider || '')} / ${_esc(e.enrichment_type || '')}</div>
                    ${dataEntries}
                </div>`;
            }).join('');

            return el;
        }

        function _renderTagsNotes(data) {
            const el = document.createElement('div');
            el.className = 'tdp-tags-notes';

            const tagChips = data.tags.map(t =>
                `<span class="tdp-tag-chip">${_esc(t)}</span>`
            ).join('') || '<span class="tdp-dim">No tags</span>';

            const notesHtml = data.notes.length > 0
                ? data.notes.map(n => `<div class="tdp-note">${_esc(n)}</div>`).join('')
                : '<div class="tdp-dim">No notes</div>';

            el.innerHTML = `
                <div class="tdp-subsection-title">TAGS</div>
                <div class="tdp-tag-wrap">${tagChips}</div>
                <div class="tdp-subsection-title" style="margin-top:8px">NOTES</div>
                <div class="tdp-notes-list">${notesHtml}</div>
            `;
            return el;
        }

        function _renderActions(data) {
            const el = document.createElement('div');
            el.className = 'tdp-actions';
            el.innerHTML = `
                <div class="tdp-action-grid">
                    <button class="tdp-action-btn tdp-action-dossier" data-action="full-dossier">FULL DOSSIER</button>
                    <button class="tdp-action-btn tdp-action-graph" data-action="graph">GRAPH</button>
                    <button class="tdp-action-btn tdp-action-inspect" data-action="inspect">INSPECT</button>
                    <button class="tdp-action-btn tdp-action-watch" data-action="watch">WATCH</button>
                    <button class="tdp-action-btn tdp-action-track" data-action="track">TRACK</button>
                    <button class="tdp-action-btn tdp-action-center" data-action="center">CENTER MAP</button>
                </div>
            `;

            el.querySelector('[data-action="full-dossier"]').addEventListener('click', () => {
                EventBus.emit('panel:request-open', { id: 'dossiers' });
                setTimeout(() => EventBus.emit('dossier:load-target', { target_id: data.targetId, dossier_id: data.dossierId }), 200);
            });

            el.querySelector('[data-action="graph"]').addEventListener('click', () => {
                EventBus.emit('panel:request-open', { id: 'graph-explorer' });
            });

            el.querySelector('[data-action="inspect"]').addEventListener('click', () => {
                EventBus.emit('panel:request-open', { id: 'unit-inspector' });
            });

            el.querySelector('[data-action="watch"]').addEventListener('click', () => {
                TritiumStore.pinTarget(data.targetId);
                EventBus.emit('toast:show', { message: `Watching: ${data.targetId}`, type: 'info' });
            });

            el.querySelector('[data-action="track"]').addEventListener('click', () => {
                EventBus.emit('prediction:toggle', { targetId: data.targetId });
                EventBus.emit('toast:show', { message: `Tracking: ${data.targetId}`, type: 'info' });
            });

            el.querySelector('[data-action="center"]').addEventListener('click', () => {
                EventBus.emit('map:centerOnUnit', { id: data.targetId });
            });

            return el;
        }

        // -----------------------------------------------------------------
        // Helper: key-value row
        // -----------------------------------------------------------------
        function _kvRow(key, value) {
            return `<div class="tdp-kv-row"><span class="tdp-kv-key">${_esc(key)}</span><span class="tdp-kv-val mono">${_esc(value)}</span></div>`;
        }

        // -----------------------------------------------------------------
        // Event wiring
        // -----------------------------------------------------------------

        // Open when target is clicked on the map
        const _onTargetSelected = (data) => {
            if (data && data.target_id) {
                loadTarget(data.target_id);
            }
        };

        // Open from dossier:load-target event
        const _onDossierLoad = (data) => {
            if (data && data.target_id) {
                loadTarget(data.target_id);
            }
        };

        // Open from context menu investigate
        const _onInvestigate = (data) => {
            if (data && data.target_id) {
                loadTarget(data.target_id);
            }
        };

        EventBus.on('target-dossier:open', _onTargetSelected);
        EventBus.on('target-dossier:load', _onDossierLoad);
        panel._unsubs.push(() => EventBus.off('target-dossier:open', _onTargetSelected));
        panel._unsubs.push(() => EventBus.off('target-dossier:load', _onDossierLoad));

        // Auto-refresh current target every 30s
        refreshTimer = setInterval(() => {
            if (currentTargetId) loadTarget(currentTargetId);
        }, 30000);
        panel._unsubs.push(() => clearInterval(refreshTimer));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};


// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------
const style = document.createElement('style');
style.textContent = `
/* Root */
.tdp-root {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

/* Placeholder */
.tdp-placeholder {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 8px;
    color: rgba(224, 224, 224, 0.3);
}
.tdp-placeholder-icon { font-size: 2rem; opacity: 0.4; }
.tdp-placeholder-text { font-size: 0.65rem; }

/* Content wrapper */
.tdp-content {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
}

/* Loading */
.tdp-loading {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    color: rgba(224, 224, 224, 0.5);
    font-size: 0.6rem;
}

/* Header */
.tdp-header { flex-shrink: 0; }
.tdp-header-main {
    padding: 8px 10px;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
}
.tdp-header-top {
    display: flex;
    align-items: center;
    gap: 6px;
}
.tdp-type-badge {
    font-size: 0.5rem;
    font-weight: 700;
    padding: 1px 5px;
    border: 1px solid;
    border-radius: 2px;
    letter-spacing: 0.08em;
}
.tdp-name {
    font-size: 0.75rem;
    font-weight: 700;
    color: #e0e0e0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.tdp-threat-badge {
    font-size: 0.4rem;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 2px;
    color: #0a0a0f;
    letter-spacing: 0.08em;
}
.tdp-header-sub {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
}
.tdp-alliance-badge {
    font-size: 0.45rem;
    font-weight: 700;
    letter-spacing: 0.08em;
}
.tdp-source-badge, .tdp-class-badge {
    font-size: 0.45rem;
    color: rgba(224, 224, 224, 0.5);
    padding: 1px 4px;
    border: 1px solid rgba(224, 224, 224, 0.15);
    border-radius: 2px;
}
.tdp-conf-badge {
    font-size: 0.5rem;
    font-weight: 700;
    margin-left: auto;
}
.tdp-target-id {
    font-size: 0.45rem;
    color: rgba(0, 240, 255, 0.4);
    margin-top: 4px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Scrollable body */
.tdp-scroll {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    padding: 4px 0;
}
.tdp-scroll::-webkit-scrollbar { width: 4px; }
.tdp-scroll::-webkit-scrollbar-track { background: transparent; }
.tdp-scroll::-webkit-scrollbar-thumb { background: rgba(0, 240, 255, 0.2); border-radius: 2px; }

/* Collapsible sections */
.tdp-section {
    border-bottom: 1px solid rgba(0, 240, 255, 0.08);
}
.tdp-section-header {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 10px;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s;
}
.tdp-section-header:hover {
    background: rgba(0, 240, 255, 0.04);
}
.tdp-section-arrow {
    font-size: 0.5rem;
    color: rgba(0, 240, 255, 0.5);
    width: 10px;
    text-align: center;
}
.tdp-section-title {
    font-size: 0.5rem;
    font-weight: 700;
    color: #00f0ff;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.tdp-section-body {
    padding: 4px 10px 8px;
}

/* Key-value rows */
.tdp-kv-row {
    display: flex;
    gap: 8px;
    padding: 2px 0;
    font-size: 0.55rem;
}
.tdp-kv-key {
    color: rgba(0, 240, 255, 0.5);
    min-width: 80px;
    flex-shrink: 0;
    font-weight: 600;
    font-size: 0.45rem;
    letter-spacing: 0.06em;
}
.tdp-kv-val {
    color: #e0e0e0;
    word-break: break-all;
}

/* Stats grid */
.tdp-stats-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
}
.tdp-stat {
    background: rgba(0, 240, 255, 0.03);
    border: 1px solid rgba(0, 240, 255, 0.08);
    border-radius: 2px;
    padding: 4px 6px;
    text-align: center;
}
.tdp-stat-label {
    font-size: 0.4rem;
    color: rgba(0, 240, 255, 0.5);
    letter-spacing: 0.08em;
    font-weight: 600;
}
.tdp-stat-value {
    font-size: 0.6rem;
    color: #e0e0e0;
    font-weight: 700;
    margin-top: 2px;
}
.tdp-pos-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 6px;
    padding: 3px 6px;
    background: rgba(0, 240, 255, 0.03);
    border: 1px solid rgba(0, 240, 255, 0.08);
    border-radius: 2px;
}
.tdp-pos-label {
    font-size: 0.4rem;
    color: rgba(0, 240, 255, 0.5);
    letter-spacing: 0.08em;
    font-weight: 600;
}
.tdp-pos-value {
    font-size: 0.55rem;
    color: #e0e0e0;
}

/* Signal history sparkline */
.tdp-signal-history { position: relative; }
.tdp-sparkline-canvas {
    width: 100%;
    height: 100px;
    border-radius: 2px;
}

/* Sighting timeline */
.tdp-timeline { display: flex; flex-direction: column; }
.tdp-tl-event { display: flex; gap: 8px; padding: 1px 0; }
.tdp-tl-marker-col {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 12px;
    flex-shrink: 0;
}
.tdp-tl-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
    margin-top: 3px;
}
.tdp-tl-line {
    flex: 1;
    width: 1px;
    background: rgba(0, 240, 255, 0.12);
    min-height: 10px;
}
.tdp-tl-content {
    flex: 1;
    min-width: 0;
    padding-bottom: 4px;
}
.tdp-tl-header {
    display: flex;
    gap: 6px;
    align-items: center;
}
.tdp-tl-type {
    font-size: 0.5rem;
    color: #e0e0e0;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.tdp-tl-conf {
    font-size: 0.45rem;
    color: rgba(224, 224, 224, 0.4);
}
.tdp-tl-time {
    font-size: 0.45rem;
    color: rgba(224, 224, 224, 0.3);
}
.tdp-tl-more {
    font-size: 0.5rem;
    color: rgba(0, 240, 255, 0.4);
    padding: 4px 0;
    text-align: center;
}

/* Associations */
.tdp-assoc-header {
    font-size: 0.45rem;
    font-weight: 700;
    color: rgba(0, 240, 255, 0.6);
    letter-spacing: 0.08em;
    margin: 6px 0 4px;
}
.tdp-assoc-card {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border: 1px solid rgba(0, 240, 255, 0.1);
    border-radius: 2px;
    margin-bottom: 3px;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
}
.tdp-assoc-card:hover {
    background: rgba(0, 240, 255, 0.06);
    border-color: rgba(0, 240, 255, 0.25);
}
.tdp-assoc-id {
    font-size: 0.5rem;
    color: #e0e0e0;
}
.tdp-assoc-badge {
    font-size: 0.4rem;
    padding: 1px 4px;
    border: 1px solid rgba(224, 224, 224, 0.15);
    border-radius: 2px;
    color: rgba(224, 224, 224, 0.5);
    text-transform: uppercase;
}
.tdp-assoc-conf {
    font-size: 0.45rem;
    font-weight: 700;
    margin-left: auto;
}
.tdp-assoc-reason {
    width: 100%;
    font-size: 0.4rem;
    color: rgba(224, 224, 224, 0.35);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Behavioral profile */
.tdp-behavior-badge {
    display: inline-block;
    font-size: 0.55rem;
    font-weight: 700;
    padding: 2px 8px;
    border: 1px solid;
    border-radius: 3px;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
}
.tdp-behavior-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.6);
}
.tdp-rssi-stats {
    margin-top: 4px;
    font-size: 0.5rem;
    display: flex;
    gap: 10px;
}
.tdp-src-breakdown {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 6px;
}
.tdp-src-chip {
    font-size: 0.4rem;
    padding: 1px 5px;
    border: 1px solid rgba(224, 224, 224, 0.2);
    border-radius: 2px;
    color: rgba(224, 224, 224, 0.5);
}

/* Threat assessment */
.tdp-threat-header {
    display: flex;
    gap: 16px;
    align-items: flex-end;
    margin-bottom: 6px;
}
.tdp-threat-score-wrap, .tdp-threat-level-wrap { text-align: center; }
.tdp-threat-score-label, .tdp-threat-level-label {
    font-size: 0.4rem;
    color: rgba(224, 224, 224, 0.4);
    letter-spacing: 0.08em;
}
.tdp-threat-score {
    font-size: 1.4rem;
    font-weight: 900;
    line-height: 1;
}
.tdp-threat-level-val {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.08em;
}
.tdp-threat-bar-track {
    height: 4px;
    background: rgba(224, 224, 224, 0.1);
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 6px;
}
.tdp-threat-bar-fill {
    height: 100%;
    border-radius: 2px;
    transition: width 0.5s ease;
}
.tdp-threat-indicators { margin-top: 4px; }
.tdp-threat-ind-title {
    font-size: 0.4rem;
    font-weight: 700;
    color: rgba(0, 240, 255, 0.5);
    letter-spacing: 0.08em;
    margin-bottom: 3px;
}
.tdp-threat-ind {
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.5);
    padding: 1px 0;
}

/* Enrichments */
.tdp-enrich-card {
    border: 1px solid rgba(0, 240, 255, 0.1);
    border-radius: 2px;
    padding: 4px 6px;
    margin-bottom: 4px;
}
.tdp-enrich-header {
    font-size: 0.45rem;
    font-weight: 700;
    color: rgba(0, 240, 255, 0.6);
    margin-bottom: 3px;
}
.tdp-enrich-kv {
    display: flex;
    gap: 6px;
    font-size: 0.45rem;
    padding: 1px 0;
}
.tdp-enrich-key {
    color: rgba(0, 240, 255, 0.4);
    min-width: 70px;
    flex-shrink: 0;
}
.tdp-enrich-val {
    color: #e0e0e0;
    word-break: break-all;
}

/* Tags & Notes */
.tdp-subsection-title {
    font-size: 0.4rem;
    font-weight: 700;
    color: rgba(0, 240, 255, 0.5);
    letter-spacing: 0.08em;
    margin-bottom: 4px;
}
.tdp-tag-wrap {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
}
.tdp-tag-chip {
    font-size: 0.45rem;
    padding: 2px 6px;
    background: rgba(0, 240, 255, 0.08);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 2px;
    color: #00f0ff;
}
.tdp-notes-list { display: flex; flex-direction: column; gap: 3px; }
.tdp-note {
    font-size: 0.5rem;
    color: rgba(224, 224, 224, 0.6);
    padding: 3px 6px;
    background: rgba(224, 224, 224, 0.03);
    border-left: 2px solid rgba(0, 240, 255, 0.15);
    border-radius: 2px;
}

/* Actions */
.tdp-action-grid {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 4px;
}
.tdp-action-btn {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.45rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    padding: 5px 4px;
    border: 1px solid rgba(0, 240, 255, 0.3);
    border-radius: 2px;
    background: rgba(0, 240, 255, 0.05);
    color: #00f0ff;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
    text-align: center;
}
.tdp-action-btn:hover {
    background: rgba(0, 240, 255, 0.12);
    border-color: #00f0ff;
}
.tdp-action-dossier {
    border-color: rgba(255, 42, 109, 0.3);
    color: #ff2a6d;
    background: rgba(255, 42, 109, 0.05);
}
.tdp-action-dossier:hover {
    background: rgba(255, 42, 109, 0.12);
    border-color: #ff2a6d;
}

/* Dim text */
.tdp-dim {
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.3);
    padding: 4px 0;
}
`;
document.head.appendChild(style);
