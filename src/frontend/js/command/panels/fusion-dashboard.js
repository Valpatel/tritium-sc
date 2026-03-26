// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Fusion Dashboard Panel — cross-sensor correlation pipeline health.
// Shows: sensor health (WiFi, BLE, YOLO, Meshtastic), fusion strategy
// performance, correlation confidence trends, fusion counts by source pair,
// engine overview with target breakdown, and strategy weight recommendations.
// Auto-refreshes every 5 seconds from /api/fusion/* endpoints.

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

// Distinct colors for source pairs and strategies
const PALETTE = [CYAN, GREEN, MAGENTA, YELLOW, '#a855f7', '#f97316', '#06b6d4', '#ec4899'];

// Known sensor sources and their display info
const SENSOR_INFO = {
    ble:        { label: 'BLE',        color: CYAN },
    wifi:       { label: 'WiFi',       color: GREEN },
    camera:     { label: 'Camera/YOLO', color: MAGENTA },
    yolo:       { label: 'YOLO',       color: MAGENTA },
    meshtastic: { label: 'Meshtastic', color: YELLOW },
    acoustic:   { label: 'Acoustic',   color: '#a855f7' },
    rf:         { label: 'RF Motion',  color: '#f97316' },
    espnow:     { label: 'ESP-NOW',    color: '#06b6d4' },
    unknown:    { label: 'Unknown',    color: DIM },
};

// Sparkline history for fusion rate
const _rateHistory = [];
const HISTORY_MAX = 60;

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchAll() {
    const [statusRes, strategiesRes, pairsRes, weightsRes, engineRes] =
        await Promise.allSettled([
            fetch('/api/fusion/status').then(r => r.ok ? r.json() : null),
            fetch('/api/fusion/strategies').then(r => r.ok ? r.json() : null),
            fetch('/api/fusion/pairs').then(r => r.ok ? r.json() : null),
            fetch('/api/fusion/weights').then(r => r.ok ? r.json() : null),
            fetch('/api/fusion/engine').then(r => r.ok ? r.json() : null),
        ]);

    return {
        status:     statusRes.status === 'fulfilled' ? statusRes.value : null,
        strategies: strategiesRes.status === 'fulfilled' ? strategiesRes.value : null,
        pairs:      pairsRes.status === 'fulfilled' ? pairsRes.value : null,
        weights:    weightsRes.status === 'fulfilled' ? weightsRes.value : null,
        engine:     engineRes.status === 'fulfilled' ? engineRes.value : null,
    };
}

// ---------------------------------------------------------------------------
// SVG sparkline (no chart library)
// ---------------------------------------------------------------------------

function _svgSparkline(data, w, h, color) {
    if (!data || data.length < 2) {
        return `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
            <text x="${w / 2}" y="${h / 2 + 3}" text-anchor="middle" fill="${DIM}" font-size="9">NO DATA</text>
        </svg>`;
    }
    const max = Math.max(...data, 0.01);
    const pts = data.map((v, i) => {
        const x = (i / (data.length - 1)) * w;
        const y = h - 2 - ((v / max) * (h - 4));
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const area = `${pts.join(' ')} ${w},${h} 0,${h}`;
    return `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="fus-spark-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
            </linearGradient>
        </defs>
        <polygon points="${area}" fill="url(#fus-spark-grad)"/>
        <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
}

// ---------------------------------------------------------------------------
// Horizontal bar chart
// ---------------------------------------------------------------------------

function _horizontalBars(entries, maxBars) {
    const sorted = entries.sort((a, b) => b[1] - a[1]).slice(0, maxBars || 8);
    if (sorted.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No data</div>`;
    }
    const maxVal = Math.max(...sorted.map(([, v]) => v), 1);
    return sorted.map(([name, val], i) => {
        const pct = Math.max(2, Math.round((val / maxVal) * 100));
        const color = PALETTE[i % PALETTE.length];
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:90px;font-size:10px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
            <span style="color:${color};font-size:10px;min-width:30px;text-align:right;font-family:monospace;">${val}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Sensor health dots
// ---------------------------------------------------------------------------

function _sensorHealthRow(targetsBySource) {
    if (!targetsBySource || Object.keys(targetsBySource).length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No sensors reporting</div>`;
    }

    return Object.entries(targetsBySource).map(([src, count]) => {
        const info = SENSOR_INFO[src] || SENSOR_INFO.unknown;
        const active = count > 0;
        const dotColor = active ? info.color : '#333';
        const statusText = active ? `${count} target${count !== 1 ? 's' : ''}` : 'IDLE';
        const statusColor = active ? info.color : '#555';

        return `<div style="display:flex;align-items:center;gap:6px;padding:3px 0;">
            <svg width="10" height="10" style="flex-shrink:0;">
                <circle cx="5" cy="5" r="4" fill="${dotColor}" opacity="0.9">
                    ${active ? '<animate attributeName="opacity" values="0.9;0.5;0.9" dur="2s" repeatCount="indefinite"/>' : ''}
                </circle>
            </svg>
            <span style="min-width:80px;font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:0.5px;">${_esc(info.label)}</span>
            <span style="font-size:10px;color:${statusColor};font-family:monospace;">${statusText}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Strategy performance table
// ---------------------------------------------------------------------------

function _strategyTable(strategies, currentWeights) {
    if (!strategies || strategies.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No strategy data</div>`;
    }

    let html = `<table style="width:100%;border-collapse:collapse;font-size:10px;">
        <thead><tr>
            <th style="text-align:left;color:#888;padding:3px 4px;border-bottom:1px solid ${BORDER};">Strategy</th>
            <th style="text-align:right;color:#888;padding:3px 4px;border-bottom:1px solid ${BORDER};">Evals</th>
            <th style="text-align:right;color:#888;padding:3px 4px;border-bottom:1px solid ${BORDER};">Accuracy</th>
            <th style="text-align:right;color:#888;padding:3px 4px;border-bottom:1px solid ${BORDER};">Weight</th>
        </tr></thead><tbody>`;

    for (const s of strategies) {
        const acc = s.accuracy != null ? s.accuracy : 0;
        const accColor = acc >= 0.8 ? GREEN : acc >= 0.5 ? YELLOW : MAGENTA;
        const accPct = (acc * 100).toFixed(1);
        const weight = currentWeights && currentWeights[s.name];
        const weightStr = weight != null ? weight.toFixed(2) : '--';

        html += `<tr>
            <td style="color:#ccc;padding:3px 4px;border-bottom:1px solid rgba(255,255,255,0.03);">${_esc(s.name || 'unknown')}</td>
            <td style="text-align:right;color:#aaa;padding:3px 4px;border-bottom:1px solid rgba(255,255,255,0.03);font-family:monospace;">${s.evaluations || 0}</td>
            <td style="text-align:right;color:${accColor};padding:3px 4px;border-bottom:1px solid rgba(255,255,255,0.03);font-family:monospace;">${accPct}%</td>
            <td style="text-align:right;color:#aaa;padding:3px 4px;border-bottom:1px solid rgba(255,255,255,0.03);font-family:monospace;">${weightStr}</td>
        </tr>`;
    }

    html += '</tbody></table>';
    return html;
}

// ---------------------------------------------------------------------------
// Weight recommendation bars with delta indicators
// ---------------------------------------------------------------------------

function _weightBars(recommendations, current) {
    const entries = Object.entries(recommendations || {});
    if (entries.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">Need more operator feedback</div>`;
    }

    return entries.map(([name, weight]) => {
        const curW = current ? current[name] : null;
        const delta = curW != null ? weight - curW : 0;
        const deltaStr = delta !== 0 ? (delta > 0 ? '+' : '') + delta.toFixed(3) : '';
        const deltaColor = delta > 0.02 ? GREEN : delta < -0.02 ? MAGENTA : DIM;

        return `<div style="display:flex;align-items:center;gap:6px;margin:3px 0;">
            <span style="color:#888;min-width:90px;font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;position:relative;">
                <div style="width:${Math.min(weight * 100, 100)}%;height:100%;background:${GREEN};border-radius:2px;transition:width 0.3s;"></div>
                ${curW != null ? `<div style="position:absolute;top:0;left:${Math.min(curW * 100, 100)}%;width:2px;height:100%;background:#fff;opacity:0.7;"></div>` : ''}
            </div>
            <span style="color:#aaa;font-size:10px;min-width:40px;text-align:right;font-family:monospace;">${(weight * 100).toFixed(1)}%</span>
            ${deltaStr ? `<span style="color:${deltaColor};font-size:9px;min-width:40px;font-family:monospace;">${deltaStr}</span>` : ''}
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Stat card helper
// ---------------------------------------------------------------------------

function _statCard(label, value, color) {
    return `<div style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;text-align:center;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;">${_esc(label)}</div>
        <div style="font-size:16px;color:${color};margin-top:2px;font-family:monospace;">${_esc(String(value))}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Correlator info row
// ---------------------------------------------------------------------------

function _correlatorInfo(status) {
    const items = [];
    if (status.correlator_threshold != null) {
        items.push(`Threshold: ${status.correlator_threshold.toFixed(2)}`);
    }
    if (status.correlator_strategies && status.correlator_strategies.length > 0) {
        items.push(`Strategies: ${status.correlator_strategies.map(s => _esc(s)).join(', ')}`);
    }
    if (items.length === 0) return '';
    return `<div style="font-size:9px;color:#555;padding:2px 0;border-top:1px solid rgba(255,255,255,0.03);margin-top:4px;padding-top:4px;">
        ${items.join(' &middot; ')}
    </div>`;
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _render(contentEl, data) {
    const status = data.status || {};
    const strategies = data.strategies || {};
    const pairs = data.pairs || {};
    const weights = data.weights || {};
    const engine = data.engine || {};

    const metricsAvail = status.metrics_available;
    const correlatorAvail = status.correlator_available;
    const engineAvail = engine.engine_available;

    // --- Availability banner ---
    let availBanner = '';
    if (!metricsAvail && !correlatorAvail && !engineAvail) {
        availBanner = `<div style="color:${MAGENTA};padding:12px;text-align:center;font-size:11px;border:1px solid rgba(255,42,109,0.3);background:rgba(255,42,109,0.05);margin-bottom:8px;">
            Fusion pipeline not initialized. Start demo mode or connect sensors.
        </div>`;
    }

    // --- Sparkline: track hourly fusion rate over time ---
    const hourlyRate = pairs.hourly_rate || 0;
    _rateHistory.push(hourlyRate);
    if (_rateHistory.length > HISTORY_MAX) _rateHistory.shift();

    // --- Top stats row ---
    const totalFusions = status.total_fusions ?? 0;
    const confirmRate = status.confirmation_rate != null
        ? (status.confirmation_rate * 100).toFixed(1) + '%' : '--';
    const activeCorrelations = status.active_correlations ?? 0;
    const multiSourceCount = engine.multi_source_count ?? 0;
    const pendingFeedback = status.total_pending_feedback ?? 0;
    const windowFusions = status.window_fusions ?? 0;

    const statsRow = `<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Fusions/Hr', hourlyRate.toFixed(1), GREEN)}
        ${_statCard('Active', activeCorrelations, CYAN)}
        ${_statCard('Total', totalFusions, GREEN)}
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Confirm Rate', confirmRate, confirmRate === '--' ? DIM : GREEN)}
        ${_statCard('Multi-Src', multiSourceCount, CYAN)}
        ${_statCard('Pending', pendingFeedback, pendingFeedback > 0 ? YELLOW : DIM)}
    </div>`;

    // --- Fusion rate sparkline ---
    const sparkHtml = `<div style="margin-bottom:10px;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">FUSION RATE TREND</div>
        ${_svgSparkline(_rateHistory, 420, 36, CYAN)}
    </div>`;

    // --- Sensor health (from engine targets_by_source) ---
    const targetsBySource = engine.targets_by_source || {};
    const sensorSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">SENSOR HEALTH</div>
        ${_sensorHealthRow(targetsBySource)}
    </div>`;

    // --- Source pair fusions (from /api/fusion/pairs) ---
    const pairEntries = Object.entries(pairs.pairs || {});
    const pairsSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">SOURCE PAIR FUSIONS</div>
        ${_horizontalBars(pairEntries, 8)}
    </div>`;

    // --- Strategy performance ---
    const stratList = (strategies.strategies || []);
    const curWeights = weights.current_weights || {};
    const stratSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">STRATEGY PERFORMANCE</div>
        ${_strategyTable(stratList, curWeights)}
    </div>`;

    // --- Weight recommendations ---
    const recs = weights.recommendations || {};
    const weightsSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">WEIGHT RECOMMENDATIONS</div>
        <div style="font-size:9px;color:#555;margin-bottom:4px;">White marker = current weight</div>
        ${_weightBars(recs, curWeights)}
    </div>`;

    // --- Correlator info ---
    const correlatorSection = correlatorAvail
        ? _correlatorInfo(status)
        : '';

    // --- Engine overview ---
    let engineSection = '';
    if (engineAvail && !engine.error) {
        const targetCount = engine.target_count ?? 0;
        const dossierCount = engine.dossier_count ?? 0;
        const correlationCount = engine.correlation_count ?? 0;
        const zoneCount = engine.zone_count ?? 0;

        engineSection = `<div style="margin-bottom:8px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
            <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">ENGINE OVERVIEW</div>
            <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;">
                <div style="background:${SURFACE};border:1px solid ${BORDER};padding:4px;text-align:center;">
                    <div style="font-size:8px;color:${DIM};text-transform:uppercase;">Targets</div>
                    <div style="font-size:13px;color:${CYAN};font-family:monospace;">${targetCount}</div>
                </div>
                <div style="background:${SURFACE};border:1px solid ${BORDER};padding:4px;text-align:center;">
                    <div style="font-size:8px;color:${DIM};text-transform:uppercase;">Dossiers</div>
                    <div style="font-size:13px;color:${GREEN};font-family:monospace;">${dossierCount}</div>
                </div>
                <div style="background:${SURFACE};border:1px solid ${BORDER};padding:4px;text-align:center;">
                    <div style="font-size:8px;color:${DIM};text-transform:uppercase;">Correlations</div>
                    <div style="font-size:13px;color:${MAGENTA};font-family:monospace;">${correlationCount}</div>
                </div>
                <div style="background:${SURFACE};border:1px solid ${BORDER};padding:4px;text-align:center;">
                    <div style="font-size:8px;color:${DIM};text-transform:uppercase;">Zones</div>
                    <div style="font-size:13px;color:${YELLOW};font-family:monospace;">${zoneCount}</div>
                </div>
            </div>
        </div>`;
    }

    contentEl.innerHTML = availBanner + statsRow + sparkHtml + sensorSection
        + pairsSection + stratSection + weightsSection + correlatorSection
        + engineSection;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const FusionDashboardPanelDef = {
    id: 'fusion-dashboard',
    title: 'FUSION PIPELINE',
    defaultPosition: { x: 240, y: 60 },
    defaultSize: { w: 480, h: 580 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'fusion-dashboard';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-fusion" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="fus-timestamp" style="font-size:10px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="fus-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading fusion pipeline...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="fus-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="fus-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-fusion"]');
        let timer = null;

        async function refresh() {
            try {
                const data = await _fetchAll();
                if (contentEl) _render(contentEl, data);
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                console.warn('[FusionDashboard] refresh error:', err);
                if (contentEl) {
                    contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to load fusion data</div>`;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', refresh);

        // Initial fetch
        refresh();

        // Auto-refresh every 5 seconds
        timer = setInterval(refresh, REFRESH_MS);
        panel._fusionTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._fusionTimer) {
            clearInterval(panel._fusionTimer);
            panel._fusionTimer = null;
        }
        // Clear sparkline history on unmount
        _rateHistory.length = 0;
    },
};
