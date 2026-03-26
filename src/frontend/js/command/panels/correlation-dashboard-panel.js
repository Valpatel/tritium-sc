// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Correlation Dashboard Panel — visualizes target correlation engine status.
// Shows: active correlations, confidence scores, strategy breakdown, correlation graph.
// Backend: GET /api/correlations/status, GET /api/correlations, GET /api/correlations/summary
// Auto-refreshes every 10 seconds.

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 10000;

const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

const STRATEGY_PALETTE = [CYAN, GREEN, MAGENTA, YELLOW, '#a855f7', '#f97316', '#06b6d4', '#ec4899'];

// Confidence history for sparkline
const _confHistory = [];
const HISTORY_MAX = 60;

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchAll() {
    const [statusRes, listRes, summaryRes] = await Promise.allSettled([
        fetch('/api/correlations/status').then(r => r.ok ? r.json() : null),
        fetch('/api/correlations').then(r => r.ok ? r.json() : null),
        fetch('/api/correlations/summary').then(r => r.ok ? r.json() : null),
    ]);

    return {
        status: statusRes.status === 'fulfilled' ? statusRes.value : null,
        list: listRes.status === 'fulfilled' ? listRes.value : null,
        summary: summaryRes.status === 'fulfilled' ? summaryRes.value : null,
    };
}

// ---------------------------------------------------------------------------
// SVG sparkline
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
            <linearGradient id="corr-spark-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
            </linearGradient>
        </defs>
        <polygon points="${area}" fill="url(#corr-spark-grad)"/>
        <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
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
// Strategy breakdown horizontal bars
// ---------------------------------------------------------------------------

function _strategyBars(strategyCounts) {
    const entries = Object.entries(strategyCounts || {}).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No strategy data</div>`;
    }
    const maxVal = Math.max(...entries.map(([, v]) => v), 1);
    return entries.map(([name, val], i) => {
        const pct = Math.max(2, Math.round((val / maxVal) * 100));
        const color = STRATEGY_PALETTE[i % STRATEGY_PALETTE.length];
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:100px;font-size:10px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
            <span style="color:${color};font-size:10px;min-width:30px;text-align:right;font-family:monospace;">${val}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Confidence distribution (mini histogram)
// ---------------------------------------------------------------------------

function _confidenceDistribution(correlations) {
    if (!correlations || correlations.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No correlations</div>`;
    }

    // Bucket into 5 ranges: 0-0.2, 0.2-0.4, 0.4-0.6, 0.6-0.8, 0.8-1.0
    const buckets = [0, 0, 0, 0, 0];
    const bucketLabels = ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%'];
    const bucketColors = [MAGENTA, '#ff8c00', YELLOW, CYAN, GREEN];

    for (const c of correlations) {
        const conf = c.confidence || 0;
        const idx = Math.min(4, Math.floor(conf * 5));
        buckets[idx]++;
    }

    const maxVal = Math.max(...buckets, 1);

    return `<div style="display:flex;gap:3px;align-items:flex-end;height:50px;">
        ${buckets.map((count, i) => {
            const h = Math.max(3, Math.round((count / maxVal) * 44));
            return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;">
                <span style="font-size:8px;color:${bucketColors[i]};font-family:monospace;">${count}</span>
                <div style="width:100%;height:${h}px;background:${bucketColors[i]};border-radius:2px 2px 0 0;opacity:0.8;"></div>
                <span style="font-size:7px;color:#555;">${bucketLabels[i]}</span>
            </div>`;
        }).join('')}
    </div>`;
}

// ---------------------------------------------------------------------------
// Correlation pair list
// ---------------------------------------------------------------------------

function _correlationList(correlations, limit) {
    if (!correlations || correlations.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No active correlations. Start demo mode or connect sensors.</div>`;
    }

    const sorted = correlations.slice().sort((a, b) => b.confidence - a.confidence);
    return sorted.slice(0, limit || 20).map(c => {
        const conf = c.confidence || 0;
        const confPct = (conf * 100).toFixed(1);
        const confColor = conf >= 0.7 ? GREEN : conf >= 0.4 ? YELLOW : MAGENTA;
        const stratCount = (c.strategies || []).length;
        const topStrat = (c.strategies && c.strategies.length > 0)
            ? c.strategies.sort((a, b) => b.score - a.score)[0].name
            : 'none';

        return `<div style="border:1px solid ${BORDER};padding:5px 6px;margin-bottom:3px;border-left:3px solid ${confColor};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div style="font-size:10px;">
                    <span style="color:${CYAN};font-family:monospace;">${_esc(c.primary_id || '--')}</span>
                    <span style="color:#555;margin:0 4px;">&harr;</span>
                    <span style="color:${CYAN};font-family:monospace;">${_esc(c.secondary_id || '--')}</span>
                </div>
                <span style="color:${confColor};font-size:11px;font-family:monospace;font-weight:bold;">${confPct}%</span>
            </div>
            <div style="display:flex;gap:8px;margin-top:2px;font-size:9px;color:#555;">
                <span>Top: ${_esc(topStrat)}</span>
                <span>${stratCount} strategies</span>
                ${c.reason ? `<span style="color:#888;">${_esc(c.reason)}</span>` : ''}
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _render(contentEl, data) {
    const status = data.status || {};
    const list = data.list || {};
    const summary = data.summary || {};

    const available = status.available;

    // Availability banner
    let availBanner = '';
    if (!available) {
        availBanner = `<div style="color:${MAGENTA};padding:12px;text-align:center;font-size:11px;border:1px solid rgba(255,42,109,0.3);background:rgba(255,42,109,0.05);margin-bottom:8px;">
            Correlation engine not initialized. Start demo mode or connect sensors.
        </div>`;
    }

    // Track avg confidence over time
    const avgConf = status.avg_confidence || summary.avg_confidence || 0;
    _confHistory.push(avgConf);
    if (_confHistory.length > HISTORY_MAX) _confHistory.shift();

    // Top stats row
    const totalCorrelations = status.total_correlations || summary.total || 0;
    const highConfidence = status.high_confidence || summary.high_confidence || 0;
    const avgConfPct = avgConf > 0 ? (avgConf * 100).toFixed(1) + '%' : '--';
    const engineStatus = status.status || 'unknown';
    const statusColor = engineStatus === 'running' ? GREEN : engineStatus === 'error' ? MAGENTA : YELLOW;

    const statsRow = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Status', engineStatus.toUpperCase(), statusColor)}
        ${_statCard('Total', totalCorrelations, CYAN)}
        ${_statCard('High Conf', highConfidence, GREEN)}
        ${_statCard('Avg Conf', avgConfPct, avgConf >= 0.5 ? GREEN : avgConf > 0 ? YELLOW : DIM)}
    </div>`;

    // Confidence trend sparkline
    const sparkHtml = `<div style="margin-bottom:10px;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">AVG CONFIDENCE TREND</div>
        ${_svgSparkline(_confHistory, 420, 36, GREEN)}
    </div>`;

    // Strategy breakdown
    const strategyCounts = status.strategy_counts || summary.strategy_counts || {};
    const stratSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">STRATEGY BREAKDOWN</div>
        ${_strategyBars(strategyCounts)}
    </div>`;

    // Confidence distribution
    const correlations = (list && list.correlations) || [];
    const distSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">CONFIDENCE DISTRIBUTION</div>
        ${_confidenceDistribution(correlations)}
    </div>`;

    // Correlation list
    const listSection = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">ACTIVE CORRELATIONS (${correlations.length})</div>
        <div style="max-height:200px;overflow-y:auto;">
            ${_correlationList(correlations, 20)}
        </div>
    </div>`;

    contentEl.innerHTML = availBanner + statsRow + sparkHtml + stratSection + distSection + listSection;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const CorrelationDashboardPanelDef = {
    id: 'correlation-dashboard',
    title: 'CORRELATION ENGINE',
    defaultPosition: { x: 260, y: 80 },
    defaultSize: { w: 480, h: 560 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'correlation-dashboard';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-corr" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="corr-timestamp" style="font-size:10px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="corr-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading correlation engine...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="corr-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="corr-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-corr"]');
        let timer = null;

        async function refresh() {
            try {
                const data = await _fetchAll();
                if (contentEl) _render(contentEl, data);
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                console.warn('[CorrelationDashboard] refresh error:', err);
                if (contentEl) {
                    contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to load correlation data</div>`;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', refresh);

        refresh();
        timer = setInterval(refresh, REFRESH_MS);
        panel._corrTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._corrTimer) {
            clearInterval(panel._corrTimer);
            panel._corrTimer = null;
        }
        _confHistory.length = 0;
    },
};
