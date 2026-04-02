// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// AR Export Panel — view and export target data for augmented reality overlays.
// Shows AR-formatted target data with alliance/confidence filters.
// Provides copy-to-clipboard and download options for AR device consumption.
// Backend: GET /api/targets/ar-export?alliance=&max_targets=&min_confidence=

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 5000;

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

async function _fetchArExport(alliance, maxTargets, minConfidence) {
    try {
        const params = new URLSearchParams();
        if (alliance) params.set('alliance', alliance);
        if (maxTargets) params.set('max_targets', String(maxTargets));
        if (minConfidence > 0) params.set('min_confidence', String(minConfidence));

        const url = '/api/targets/ar-export' + (params.toString() ? '?' + params.toString() : '');
        const resp = await fetch(url);
        if (!resp.ok) return { version: '1.0', target_count: 0, targets: [], error: `HTTP ${resp.status}` };
        return await resp.json();
    } catch (e) {
        return { version: '1.0', target_count: 0, targets: [], error: e.message };
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _allianceColor(alliance) {
    const colors = {
        friendly: GREEN,
        hostile: MAGENTA,
        neutral: YELLOW,
        unknown: DIM,
    };
    return colors[(alliance || '').toLowerCase()] || DIM;
}

function _statCard(label, value, color) {
    return `<div style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;text-align:center;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;">${_esc(label)}</div>
        <div style="font-size:16px;color:${color};margin-top:2px;font-family:monospace;">${_esc(String(value))}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Render: target list
// ---------------------------------------------------------------------------

function _arTargetList(targets) {
    if (!targets || targets.length === 0) {
        return `<div style="color:#555;padding:12px;text-align:center;font-size:10px;">No targets available for AR export. Start demo mode or connect sensors.</div>`;
    }

    return targets.map(t => {
        const alliance = (t.alliance || 'unknown').toLowerCase();
        const color = _allianceColor(alliance);
        const conf = Math.round((t.confidence || 0) * 100);
        const confColor = conf >= 70 ? GREEN : conf >= 40 ? YELLOW : MAGENTA;
        const speed = (t.speed || 0).toFixed(1);
        const heading = Math.round(t.heading || 0);

        return `<div style="border:1px solid ${BORDER};padding:4px 6px;margin-bottom:3px;border-left:3px solid ${color};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-size:10px;">
                    <span class="mono" style="color:${CYAN};">${_esc(t.id || '--')}</span>
                    <span style="color:#888;margin-left:6px;font-size:9px;">${_esc(t.type || '')}</span>
                </div>
                <span style="color:${color};font-size:9px;border:1px solid ${color};padding:1px 4px;border-radius:2px;">${_esc(alliance.toUpperCase())}</span>
            </div>
            <div style="display:flex;gap:10px;margin-top:2px;font-size:9px;color:#888;">
                <span>${_esc(t.name || '--')}</span>
                <span style="color:${confColor};">${conf}%</span>
                <span>${speed} m/s</span>
                <span>${heading}&deg;</span>
                <span style="color:#555;">${(t.lat || 0).toFixed(5)}, ${(t.lng || 0).toFixed(5)}</span>
                <span style="color:#555;">${(t.alt || 0).toFixed(1)}m</span>
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _renderArExport(contentEl, data) {
    if (!data) {
        contentEl.innerHTML = `<div style="color:#555;padding:12px;text-align:center;">No data</div>`;
        return;
    }
    if (data.error) {
        contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">${_esc(data.error)}</div>`;
        return;
    }

    const targets = data.targets || [];
    const count = data.target_count || targets.length;

    // Count by alliance
    const allianceCounts = {};
    for (const t of targets) {
        const a = (t.alliance || 'unknown').toLowerCase();
        allianceCounts[a] = (allianceCounts[a] || 0) + 1;
    }

    const statsRow = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Total', count, CYAN)}
        ${_statCard('Friendly', allianceCounts.friendly || 0, GREEN)}
        ${_statCard('Hostile', allianceCounts.hostile || 0, MAGENTA)}
        ${_statCard('Unknown', allianceCounts.unknown || 0, DIM)}
    </div>`;

    const listSection = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">AR TARGETS (${count})</div>
        <div style="max-height:300px;overflow-y:auto;">${_arTargetList(targets)}</div>
    </div>`;

    contentEl.innerHTML = statsRow + listSection;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const ArExportPanelDef = {
    id: 'ar-export',
    title: 'AR EXPORT',
    defaultPosition: { x: 380, y: 140 },
    defaultSize: { w: 480, h: 500 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'ar-export-panel';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="color:${GREEN};font-size:12px;font-weight:bold;">AR EXPORT</span>
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-ar" style="font-size:0.42rem;margin-left:auto;">REFRESH</button>
                <span data-bind="ar-timestamp" style="font-size:10px;color:#555;font-family:monospace;">--</span>
            </div>

            <div style="border:1px solid ${BORDER};padding:6px;margin-bottom:8px;">
                <div style="font-size:9px;color:${DIM};margin-bottom:4px;">FILTERS</div>
                <div style="display:flex;gap:6px;align-items:center;">
                    <select data-bind="ar-alliance"
                            style="background:#0a0a0f;border:1px solid ${BORDER};color:#ccc;padding:3px 6px;font-size:10px;">
                        <option value="">All Alliances</option>
                        <option value="friendly">Friendly</option>
                        <option value="hostile">Hostile</option>
                        <option value="unknown">Unknown</option>
                    </select>
                    <input type="number" data-bind="ar-max" placeholder="Max" value="100" min="1" max="1000"
                           style="width:60px;background:#0a0a0f;border:1px solid ${BORDER};color:#ccc;padding:3px 6px;font-size:10px;">
                    <label style="font-size:9px;color:#888;">Min conf:</label>
                    <input type="range" data-bind="ar-confidence" min="0" max="100" value="0"
                           style="flex:1;accent-color:${CYAN};">
                    <span data-bind="ar-conf-label" style="font-size:9px;color:${CYAN};min-width:28px;">0%</span>
                </div>
                <div style="display:flex;gap:6px;margin-top:6px;">
                    <button class="panel-action-btn" data-action="copy-ar-json" style="font-size:0.42rem;">COPY JSON</button>
                    <button class="panel-action-btn" data-action="download-ar-json" style="font-size:0.42rem;">DOWNLOAD</button>
                    <label style="font-size:9px;color:#555;margin-left:auto;display:flex;align-items:center;gap:4px;">
                        <input type="checkbox" data-bind="ar-auto-refresh"> Auto-refresh
                    </label>
                </div>
            </div>

            <div data-bind="ar-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading AR export data...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="ar-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="ar-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-ar"]');
        const copyBtn = bodyEl.querySelector('[data-action="copy-ar-json"]');
        const downloadBtn = bodyEl.querySelector('[data-action="download-ar-json"]');
        const allianceSelect = bodyEl.querySelector('[data-bind="ar-alliance"]');
        const maxInput = bodyEl.querySelector('[data-bind="ar-max"]');
        const confSlider = bodyEl.querySelector('[data-bind="ar-confidence"]');
        const confLabel = bodyEl.querySelector('[data-bind="ar-conf-label"]');
        const autoRefreshCheck = bodyEl.querySelector('[data-bind="ar-auto-refresh"]');

        let timer = null;
        let lastData = null;

        // Update confidence label when slider changes
        if (confSlider && confLabel) {
            confSlider.addEventListener('input', () => {
                confLabel.textContent = confSlider.value + '%';
            });
        }

        async function refresh() {
            const alliance = allianceSelect ? allianceSelect.value : '';
            const max = maxInput ? parseInt(maxInput.value, 10) || 100 : 100;
            const minConf = confSlider ? parseInt(confSlider.value, 10) / 100 : 0;

            try {
                const data = await _fetchArExport(alliance, max, minConf);
                lastData = data;
                if (contentEl) _renderArExport(contentEl, data);
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                if (contentEl) contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to fetch AR data</div>`;
            }
        }

        // Wire buttons
        if (refreshBtn) refreshBtn.addEventListener('click', refresh);

        if (copyBtn) {
            copyBtn.addEventListener('click', () => {
                if (lastData) {
                    try {
                        navigator.clipboard.writeText(JSON.stringify(lastData, null, 2));
                    } catch {
                        // Fallback: create textarea
                        const ta = document.createElement('textarea');
                        ta.value = JSON.stringify(lastData, null, 2);
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        ta.remove();
                    }
                }
            });
        }

        if (downloadBtn) {
            downloadBtn.addEventListener('click', () => {
                if (lastData) {
                    const blob = new Blob([JSON.stringify(lastData, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `tritium-ar-export-${Date.now()}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                }
            });
        }

        // Auto-refresh toggle
        if (autoRefreshCheck) {
            autoRefreshCheck.addEventListener('change', () => {
                if (autoRefreshCheck.checked) {
                    timer = setInterval(refresh, REFRESH_MS);
                } else {
                    if (timer) { clearInterval(timer); timer = null; }
                }
            });
        }

        // Filter changes trigger refresh
        if (allianceSelect) allianceSelect.addEventListener('change', refresh);

        // Initial load
        refresh();
        panel._arTimer = timer; // May be null until auto-refresh is checked
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._arTimer) {
            clearInterval(panel._arTimer);
            panel._arTimer = null;
        }
    },
};
