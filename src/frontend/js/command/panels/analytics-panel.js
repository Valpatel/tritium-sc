// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Analytics Panel — real-time analytics from the AnalyticsEngine.
// Fetches /api/sitaware/picture (analytics section) and displays:
//   - Detection rate (per minute) with sparkline history
//   - Zone activity horizontal bars
//   - Sensor utilization SVG pie chart
//   - Trend arrows (detection + alert trends)
//   - Time window selector (1min, 5min, 1hr, 24hr)
//   - Top-N targets and zones by activity

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _timer = null;
let _window = '5min';           // selected time horizon
const _rateHistory = [];        // detection rate samples for sparkline
const HISTORY_MAX = 60;         // 60 samples for sparkline
const REFRESH_MS = 5000;        // refresh every 5s

// Cyberpunk palette
const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// Distinct colors for pie slices and bars
const PALETTE = [CYAN, MAGENTA, GREEN, YELLOW, '#a855f7', '#f97316', '#06b6d4', '#ec4899'];

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchPicture() {
    try {
        const r = await fetch('/api/sitaware/picture');
        if (!r.ok) return null;
        return await r.json();
    } catch {
        return null;
    }
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
    // filled area
    const area = `${pts.join(' ')} ${w},${h} 0,${h}`;
    return `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <linearGradient id="anl-spark-grad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
                <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
            </linearGradient>
        </defs>
        <polygon points="${area}" fill="url(#anl-spark-grad)"/>
        <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
    </svg>`;
}

// ---------------------------------------------------------------------------
// SVG pie chart
// ---------------------------------------------------------------------------

function _svgPie(dist, size) {
    const entries = Object.entries(dist).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) {
        return `<svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">
            <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 4}" fill="none" stroke="${BORDER}" stroke-width="2"/>
            <text x="${size / 2}" y="${size / 2 + 3}" text-anchor="middle" fill="${DIM}" font-size="9">NO DATA</text>
        </svg>`;
    }
    const total = entries.reduce((s, [, v]) => s + v, 0);
    const cx = size / 2, cy = size / 2, r = size / 2 - 4;
    let angle = -Math.PI / 2; // start at top
    const paths = [];
    const labels = [];

    entries.forEach(([name, val], i) => {
        const frac = val / total;
        const sweep = frac * 2 * Math.PI;
        const x1 = cx + r * Math.cos(angle);
        const y1 = cy + r * Math.sin(angle);
        const x2 = cx + r * Math.cos(angle + sweep);
        const y2 = cy + r * Math.sin(angle + sweep);
        const large = sweep > Math.PI ? 1 : 0;
        const color = PALETTE[i % PALETTE.length];
        const pct = Math.round(frac * 100);

        if (entries.length === 1) {
            // Single slice = full circle
            paths.push(`<circle cx="${cx}" cy="${cy}" r="${r}" fill="${color}" opacity="0.7"/>`);
        } else {
            paths.push(`<path d="M${cx},${cy} L${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 ${large} 1 ${x2.toFixed(1)},${y2.toFixed(1)} Z" fill="${color}" opacity="0.7" stroke="#0a0a0f" stroke-width="1"/>`);
        }
        labels.push(`<span style="color:${color};font-size:10px;white-space:nowrap;"><span style="display:inline-block;width:6px;height:6px;background:${color};margin-right:3px;border-radius:1px;"></span>${_esc(name)} ${pct}%</span>`);
        angle += sweep;
    });

    const svg = `<svg width="${size}" height="${size}" xmlns="http://www.w3.org/2000/svg">${paths.join('')}</svg>`;
    return { svg, labels };
}

// ---------------------------------------------------------------------------
// Trend arrow
// ---------------------------------------------------------------------------

function _trendArrow(direction, confidence) {
    if (direction === 'increasing') {
        const opacity = Math.max(0.5, confidence);
        return `<span class="anl-trend-arrow" style="color:${GREEN};opacity:${opacity};" title="Increasing (${Math.round(confidence * 100)}% conf)">&#x25B2;</span>`;
    }
    if (direction === 'decreasing') {
        const opacity = Math.max(0.5, confidence);
        return `<span class="anl-trend-arrow" style="color:${MAGENTA};opacity:${opacity};" title="Decreasing (${Math.round(confidence * 100)}% conf)">&#x25BC;</span>`;
    }
    return `<span class="anl-trend-arrow" style="color:${DIM};" title="Stable">&#x25CF;</span>`;
}

// ---------------------------------------------------------------------------
// Horizontal bar chart (for zone activity)
// ---------------------------------------------------------------------------

function _horizontalBars(dist, maxBars) {
    const entries = Object.entries(dist).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).slice(0, maxBars || 8);
    if (entries.length === 0) {
        return '<div style="color:#444;font-size:10px;padding:4px 0;">No zone activity</div>';
    }
    const maxVal = Math.max(...entries.map(([, v]) => v), 1);
    return entries.map(([name, val], i) => {
        const pct = Math.max(2, Math.round((val / maxVal) * 100));
        const color = PALETTE[i % PALETTE.length];
        return `<div class="anl-bar-row">
            <span class="anl-bar-label">${_esc(name)}</span>
            <div class="anl-bar-track">
                <div class="anl-bar-fill" style="width:${pct}%;background:${color};"></div>
            </div>
            <span class="anl-bar-value" style="color:${color}">${Math.round(val)}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Top-N list
// ---------------------------------------------------------------------------

function _topNList(items, label, color) {
    if (!items || items.length === 0) {
        return `<div style="color:#444;font-size:10px;padding:4px 0;">No ${label}</div>`;
    }
    return items.map((entry, i) => {
        const name = entry.item || entry[0] || '?';
        const count = Math.round(entry.count ?? entry[1] ?? 0);
        return `<div class="anl-topn-row">
            <span class="anl-topn-rank" style="color:${color}">${i + 1}</span>
            <span class="anl-topn-id">${_esc(String(name))}</span>
            <span class="anl-topn-count">${count}</span>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Rate display with selected window
// ---------------------------------------------------------------------------

function _rateValue(counterExport) {
    if (!counterExport) return '--';
    const rates = counterExport.rates_per_minute || {};
    const val = rates[_window];
    if (val === undefined || val === null) return '--';
    return val < 1 ? val.toFixed(2) : Math.round(val).toLocaleString();
}

function _windowCount(counterExport) {
    if (!counterExport) return '--';
    const counts = counterExport.window_counts || {};
    const val = counts[_window];
    if (val === undefined || val === null) return '--';
    return Math.round(val).toLocaleString();
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

function _render(bodyEl, analytics) {
    if (!analytics || typeof analytics !== 'object') {
        bodyEl.querySelector('[data-bind="anl-content"]').innerHTML =
            '<div style="color:#444;padding:16px;text-align:center;">Waiting for analytics data...</div>';
        return;
    }

    const detRate = analytics.detection_rate || {};
    const alertRate = analytics.alert_rate || {};
    const corr = analytics.correlation || {};
    const zone = analytics.zone_activity || {};
    const sensor = analytics.sensor_utilization || {};
    const trends = analytics.trends || {};
    const topTargets = analytics.top_targets || {};
    const topZones = analytics.top_zones || {};

    // Record current rate for sparkline
    const currentRate = (detRate.rates_per_minute || {})[_window] || 0;
    _rateHistory.push(currentRate);
    if (_rateHistory.length > HISTORY_MAX) _rateHistory.shift();

    // Detection trend
    const detTrend = trends.detections || {};
    const alertTrend = trends.alerts || {};

    // Correlation success
    const corrRate = corr.success_rate_5min;
    const corrPct = corrRate != null ? `${Math.round(corrRate * 100)}%` : '--';

    // Sparkline
    const sparkHtml = _svgSparkline(_rateHistory, 240, 40, CYAN);

    // Pie chart for sensor utilization
    const sensorDist = sensor.distribution || sensor.percentages || {};
    const pieResult = _svgPie(sensorDist, 100);
    const pieSvg = typeof pieResult === 'string' ? pieResult : pieResult.svg;
    const pieLabels = typeof pieResult === 'string' ? '' : pieResult.labels.join('<br>');

    // Zone activity bars
    const zoneDist = zone.distribution || {};
    const zoneBars = _horizontalBars(zoneDist, 8);

    // Top-N
    const topTargetItems = topTargets.top || [];
    const topZoneItems = topZones.top || [];

    const content = bodyEl.querySelector('[data-bind="anl-content"]');
    content.innerHTML = `
        <div class="anl-section">
            <div class="anl-section-title">DETECTION RATE ${_trendArrow(detTrend.direction, detTrend.confidence || 0)}</div>
            <div class="anl-stat-row">
                <div class="anl-stat-card">
                    <div class="anl-stat-label">RATE/MIN</div>
                    <div class="anl-stat-value" style="color:${CYAN}">${_rateValue(detRate)}</div>
                </div>
                <div class="anl-stat-card">
                    <div class="anl-stat-label">WINDOW COUNT</div>
                    <div class="anl-stat-value" style="color:${GREEN}">${_windowCount(detRate)}</div>
                </div>
                <div class="anl-stat-card">
                    <div class="anl-stat-label">LIFETIME</div>
                    <div class="anl-stat-value" style="color:${DIM}">${detRate.lifetime_count != null ? detRate.lifetime_count.toLocaleString() : '--'}</div>
                </div>
            </div>
            <div class="anl-sparkline-wrap">${sparkHtml}</div>
        </div>

        <div class="anl-section">
            <div class="anl-section-title">ALERTS ${_trendArrow(alertTrend.direction, alertTrend.confidence || 0)}</div>
            <div class="anl-stat-row">
                <div class="anl-stat-card">
                    <div class="anl-stat-label">RATE/MIN</div>
                    <div class="anl-stat-value" style="color:${YELLOW}">${_rateValue(alertRate)}</div>
                </div>
                <div class="anl-stat-card">
                    <div class="anl-stat-label">WINDOW</div>
                    <div class="anl-stat-value" style="color:${YELLOW}">${_windowCount(alertRate)}</div>
                </div>
                <div class="anl-stat-card">
                    <div class="anl-stat-label">CORRELATION</div>
                    <div class="anl-stat-value" style="color:${GREEN}">${corrPct}</div>
                </div>
            </div>
        </div>

        <div class="anl-two-col">
            <div class="anl-section" style="flex:1;">
                <div class="anl-section-title">SENSOR UTILIZATION</div>
                <div class="anl-pie-wrap">
                    ${pieSvg}
                    <div class="anl-pie-legend">${pieLabels}</div>
                </div>
            </div>
            <div class="anl-section" style="flex:1;">
                <div class="anl-section-title">ZONE ACTIVITY</div>
                ${zoneBars}
            </div>
        </div>

        <div class="anl-two-col">
            <div class="anl-section" style="flex:1;">
                <div class="anl-section-title">TOP TARGETS</div>
                ${_topNList(topTargetItems, 'targets', CYAN)}
            </div>
            <div class="anl-section" style="flex:1;">
                <div class="anl-section-title">TOP ZONES</div>
                ${_topNList(topZoneItems, 'zones', GREEN)}
            </div>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const AnalyticsPanelDef = {
    id: 'analytics-panel',
    title: 'ANALYTICS',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 520, h: 560 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'anl-panel-inner';
        el.innerHTML = `
            <div class="anl-toolbar">
                <div class="anl-window-selector">
                    <button class="anl-win-btn${_window === '1min' ? ' anl-win-active' : ''}" data-win="1min">1M</button>
                    <button class="anl-win-btn${_window === '5min' ? ' anl-win-active' : ''}" data-win="5min">5M</button>
                    <button class="anl-win-btn${_window === '1hr' ? ' anl-win-active' : ''}" data-win="1hr">1H</button>
                    <button class="anl-win-btn${_window === '24hr' ? ' anl-win-active' : ''}" data-win="24hr">24H</button>
                </div>
                <button class="anl-refresh-btn" data-action="refresh" title="Refresh now">REFRESH</button>
            </div>
            <div data-bind="anl-content" class="anl-content">
                <div style="color:#444;padding:16px;text-align:center;">Loading analytics...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, _panel) {
        // Wire window selector buttons
        bodyEl.querySelectorAll('.anl-win-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                _window = btn.dataset.win;
                bodyEl.querySelectorAll('.anl-win-btn').forEach(b => b.classList.remove('anl-win-active'));
                btn.classList.add('anl-win-active');
                _doRefresh(bodyEl);
            });
        });

        // Wire refresh button
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        if (refreshBtn) refreshBtn.addEventListener('click', () => _doRefresh(bodyEl));

        // Initial fetch
        _doRefresh(bodyEl);

        // Auto-refresh
        if (_timer) clearInterval(_timer);
        _timer = setInterval(() => _doRefresh(bodyEl), REFRESH_MS);
    },

    unmount(_bodyEl, _panel) {
        if (_timer) {
            clearInterval(_timer);
            _timer = null;
        }
        _rateHistory.length = 0;
    },
};

async function _doRefresh(bodyEl) {
    const pic = await _fetchPicture();
    if (!pic || !pic.available) {
        const content = bodyEl.querySelector('[data-bind="anl-content"]');
        if (content) {
            content.innerHTML = '<div style="color:#444;padding:16px;text-align:center;">SitAware engine not available</div>';
        }
        return;
    }
    _render(bodyEl, pic.analytics || {});
}
