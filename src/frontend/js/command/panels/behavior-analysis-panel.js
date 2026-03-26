// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Behavior Analysis Panel — visualizes behavioral patterns, anomalies, and co-presence events.
// Backend: GET /api/behavior/patterns, GET /api/behavior/anomalies, GET /api/behavior/stats
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

const SEVERITY_COLORS = {
    critical: MAGENTA,
    high: '#ff6b35',
    warning: YELLOW,
    medium: YELLOW,
    low: GREEN,
    info: CYAN,
};

const BEHAVIOR_TYPE_COLORS = {
    loitering: YELLOW,
    patrol: GREEN,
    transit: CYAN,
    stationary: '#888',
    erratic: MAGENTA,
    unknown: DIM,
};

// Anomaly count history for sparkline
const _anomalyHistory = [];
const HISTORY_MAX = 60;

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchBehaviorData() {
    const [patternsRes, anomaliesRes, statsRes] = await Promise.allSettled([
        fetch('/api/behavior/patterns?limit=50').then(r => r.ok ? r.json() : null),
        fetch('/api/behavior/anomalies?limit=50').then(r => r.ok ? r.json() : null),
        fetch('/api/behavior/stats').then(r => r.ok ? r.json() : null),
    ]);

    return {
        patterns: patternsRes.status === 'fulfilled' ? patternsRes.value : null,
        anomalies: anomaliesRes.status === 'fulfilled' ? anomaliesRes.value : null,
        stats: statsRes.status === 'fulfilled' ? statsRes.value : null,
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
            <linearGradient id="behav-spark-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
            </linearGradient>
        </defs>
        <polygon points="${area}" fill="url(#behav-spark-grad)"/>
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
// Behavior type breakdown bars
// ---------------------------------------------------------------------------

function _typeBars(patternTypes) {
    const entries = Object.entries(patternTypes || {}).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No pattern types detected</div>`;
    }
    const maxVal = Math.max(...entries.map(([, v]) => v), 1);
    return entries.map(([name, val]) => {
        const pct = Math.max(2, Math.round((val / maxVal) * 100));
        const color = BEHAVIOR_TYPE_COLORS[name] || CYAN;
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:80px;font-size:10px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
            <span style="color:${color};font-size:10px;min-width:30px;text-align:right;font-family:monospace;">${val}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Severity breakdown horizontal bars
// ---------------------------------------------------------------------------

function _severityBars(severityCounts) {
    const entries = Object.entries(severityCounts || {}).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No anomalies</div>`;
    }
    const maxVal = Math.max(...entries.map(([, v]) => v), 1);
    return entries.map(([name, val]) => {
        const pct = Math.max(2, Math.round((val / maxVal) * 100));
        const color = SEVERITY_COLORS[name] || DIM;
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:80px;font-size:10px;text-transform:uppercase;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(name)}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:${color};border-radius:2px;transition:width 0.3s;"></div>
            </div>
            <span style="color:${color};font-size:10px;min-width:30px;text-align:right;font-family:monospace;">${val}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Pattern list
// ---------------------------------------------------------------------------

function _patternList(patterns, limit) {
    if (!patterns || !Array.isArray(patterns) || patterns.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No patterns detected. Patterns emerge as targets are tracked over time.</div>`;
    }

    return patterns.slice(0, limit || 15).map(p => {
        const conf = p.confidence || 0;
        const confPct = (conf * 100).toFixed(0);
        const confColor = conf >= 0.7 ? GREEN : conf >= 0.4 ? YELLOW : MAGENTA;
        const typeColor = BEHAVIOR_TYPE_COLORS[p.behavior_type] || CYAN;

        return `<div style="border:1px solid ${BORDER};padding:5px 6px;margin-bottom:3px;border-left:3px solid ${typeColor};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="color:${typeColor};font-size:10px;font-weight:bold;text-transform:uppercase;">${_esc(p.behavior_type || 'unknown')}</span>
                <span style="color:${confColor};font-size:10px;font-family:monospace;">${confPct}%</span>
            </div>
            <div style="font-size:9px;color:#888;margin-top:2px;">
                Target: <span style="color:${CYAN};font-family:monospace;">${_esc(p.target_id || '--')}</span>
                ${p.samples ? `<span style="margin-left:8px;">${p.samples} samples</span>` : ''}
                ${p.duration_s ? `<span style="margin-left:8px;">${Math.round(p.duration_s)}s</span>` : ''}
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Anomaly list
// ---------------------------------------------------------------------------

function _anomalyList(anomalies, limit) {
    if (!anomalies || !Array.isArray(anomalies) || anomalies.length === 0) {
        return `<div style="color:#555;padding:8px;text-align:center;font-size:10px;">No anomalies detected. Anomalies appear when established patterns are broken.</div>`;
    }

    return anomalies.slice(0, limit || 15).map(a => {
        const sevColor = SEVERITY_COLORS[a.severity] || DIM;

        return `<div style="border:1px solid ${BORDER};padding:5px 6px;margin-bottom:3px;border-left:3px solid ${sevColor};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="color:${sevColor};font-size:10px;font-weight:bold;text-transform:uppercase;">${_esc(a.anomaly_type || 'unknown')}</span>
                <span style="color:${sevColor};font-size:9px;border:1px solid ${sevColor};padding:1px 4px;border-radius:2px;">${_esc((a.severity || 'info').toUpperCase())}</span>
            </div>
            <div style="font-size:9px;color:#888;margin-top:2px;">
                Target: <span style="color:${CYAN};font-family:monospace;">${_esc(a.target_id || '--')}</span>
            </div>
            ${a.description ? `<div style="font-size:9px;color:#aaa;margin-top:2px;">${_esc(a.description)}</div>` : ''}
            ${(a.baseline_value || a.observed_value) ? `<div style="font-size:9px;color:#555;margin-top:2px;">
                ${a.baseline_value ? `Baseline: ${_esc(a.baseline_value)}` : ''}
                ${a.observed_value ? ` Observed: <span style="color:${YELLOW};">${_esc(a.observed_value)}</span>` : ''}
            </div>` : ''}
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Activity heatmap (7x24 grid)
// ---------------------------------------------------------------------------

function _activityHeatmap(patterns) {
    if (!patterns || !Array.isArray(patterns) || patterns.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No activity data for heatmap</div>`;
    }

    // Build a 7x24 matrix from pattern timestamps
    const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    const matrix = Array.from({ length: 7 }, () => Array(24).fill(0));

    for (const p of patterns) {
        if (p.timestamp) {
            const d = new Date(p.timestamp * 1000);
            const day = (d.getDay() + 6) % 7; // Mon=0
            const hour = d.getHours();
            matrix[day][hour]++;
        }
    }

    const maxVal = Math.max(1, ...matrix.flat());

    let html = '<div style="display:grid;grid-template-columns:32px repeat(24,1fr);gap:1px;font-size:8px;">';
    // Header
    html += '<div></div>';
    for (let h = 0; h < 24; h++) {
        html += `<div style="text-align:center;color:#555;">${h}</div>`;
    }
    // Rows
    for (let d = 0; d < 7; d++) {
        html += `<div style="color:#666;line-height:12px;font-size:8px;">${DAYS[d]}</div>`;
        for (let h = 0; h < 24; h++) {
            const val = matrix[d][h];
            const intensity = val / maxVal;
            const bg = intensity === 0 ? 'transparent'
                : intensity < 0.3 ? 'rgba(0,240,255,0.15)'
                : intensity < 0.6 ? 'rgba(0,240,255,0.35)'
                : intensity < 0.8 ? 'rgba(0,240,255,0.6)'
                : 'rgba(0,240,255,0.9)';
            html += `<div style="background:${bg};height:12px;border-radius:1px;" title="${DAYS[d]} ${h}:00 - ${val} events"></div>`;
        }
    }
    html += '</div>';
    return html;
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _renderBehavior(contentEl, data) {
    const stats = data.stats || {};
    const patterns = Array.isArray(data.patterns) ? data.patterns : [];
    const anomalies = Array.isArray(data.anomalies) ? data.anomalies : [];

    const totalPatterns = stats.total_patterns || patterns.length || 0;
    const targetsWithPatterns = stats.targets_with_patterns || 0;
    const totalAnomalies = stats.total_anomalies || anomalies.length || 0;
    const highScoreCorrelations = stats.high_score_correlations || 0;

    // Track anomaly count over time
    _anomalyHistory.push(totalAnomalies);
    if (_anomalyHistory.length > HISTORY_MAX) _anomalyHistory.shift();

    // Stats row
    const statsRow = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Patterns', totalPatterns, CYAN)}
        ${_statCard('Targets', targetsWithPatterns, GREEN)}
        ${_statCard('Anomalies', totalAnomalies, totalAnomalies > 0 ? YELLOW : DIM)}
        ${_statCard('Hi-Score', highScoreCorrelations, highScoreCorrelations > 0 ? MAGENTA : DIM)}
    </div>`;

    // Anomaly trend sparkline
    const sparkHtml = `<div style="margin-bottom:10px;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">ANOMALY TREND</div>
        ${_svgSparkline(_anomalyHistory, 420, 36, YELLOW)}
    </div>`;

    // Pattern type breakdown
    const patternTypes = stats.pattern_types || {};
    const typeSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">BEHAVIOR TYPES</div>
        ${_typeBars(patternTypes)}
    </div>`;

    // Anomaly severity breakdown
    const severityCounts = stats.anomaly_severities || {};
    const sevSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${MAGENTA};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">ANOMALY SEVERITY</div>
        ${_severityBars(severityCounts)}
    </div>`;

    // Activity heatmap
    const heatmapSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">ACTIVITY HEATMAP</div>
        ${_activityHeatmap(patterns)}
    </div>`;

    // Recent patterns list
    const patternSection = `<div style="margin-bottom:10px;border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">RECENT PATTERNS (${patterns.length})</div>
        <div style="max-height:160px;overflow-y:auto;">
            ${_patternList(patterns, 10)}
        </div>
    </div>`;

    // Recent anomalies list
    const anomalySection = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;">
        <div style="font-size:10px;color:${YELLOW};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">RECENT ANOMALIES (${anomalies.length})</div>
        <div style="max-height:160px;overflow-y:auto;">
            ${_anomalyList(anomalies, 10)}
        </div>
    </div>`;

    contentEl.innerHTML = statsRow + sparkHtml + typeSection + sevSection + heatmapSection + patternSection + anomalySection;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const BehaviorAnalysisPanelDef = {
    id: 'behavior-analysis',
    title: 'BEHAVIOR ANALYSIS',
    defaultPosition: { x: 280, y: 100 },
    defaultSize: { w: 480, h: 620 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'behavior-analysis';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-behavior" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="behav-timestamp" style="font-size:10px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="behav-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading behavior analysis...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="behav-content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="behav-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-behavior"]');
        let timer = null;

        async function refresh() {
            try {
                const data = await _fetchBehaviorData();
                if (contentEl) _renderBehavior(contentEl, data);
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                console.warn('[BehaviorAnalysis] refresh error:', err);
                if (contentEl) {
                    contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to load behavior data</div>`;
                }
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', refresh);

        refresh();
        timer = setInterval(refresh, REFRESH_MS);
        panel._behavTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._behavTimer) {
            clearInterval(panel._behavTimer);
            panel._behavTimer = null;
        }
        _anomalyHistory.length = 0;
    },
};
