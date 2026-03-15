// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Analytics Dashboard Panel
// Configurable drag-and-drop analytics widgets. Operators can rearrange,
// enable/disable, and resize widgets. Fetches widget definitions from
// /api/analytics/widgets and renders counter, chart, table, and timeline types.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let _widgets = [];
let _refreshTimer = null;
let _dragState = null;

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchWidgets() {
    try {
        const resp = await fetch('/api/analytics/widgets');
        if (!resp.ok) return [];
        const data = await resp.json();
        return data.widgets || [];
    } catch {
        return [];
    }
}

async function _fetchAnalytics(dataSource) {
    try {
        const resp = await fetch(dataSource);
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

async function _saveLayout(widgets) {
    try {
        await fetch('/api/analytics/widgets/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ operator_id: 'default', widgets }),
        });
    } catch { /* best-effort save */ }
}

// ---------------------------------------------------------------------------
// Widget renderers
// ---------------------------------------------------------------------------

function _renderCounter(widget, analytics) {
    let value = '—';
    if (analytics) {
        if (widget.widget_id === 'correlation_success_rate') {
            const stats = analytics.correlation_stats || {};
            const rate = stats.rate || 0;
            value = `${Math.round(rate * 100)}%`;
        } else {
            value = String(analytics.total_events || 0);
        }
    }
    return `<div class="adash-counter" style="color:${widget.config?.color || '#00f0ff'}">
        <div class="adash-counter-value">${_esc(value)}</div>
    </div>`;
}

function _renderChart(widget, analytics) {
    if (!analytics) return '<div class="adash-no-data">No data</div>';
    const hours = analytics.busiest_hours || {};
    const keys = Object.keys(hours).sort((a, b) => Number(a) - Number(b));
    if (keys.length === 0) return '<div class="adash-no-data">No data</div>';

    const vals = keys.map(k => hours[k] || 0);
    const maxVal = Math.max(...vals, 1);
    const color = widget.config?.color || '#00f0ff';
    const chartType = widget.config?.chart_type || 'bar';

    if (chartType === 'bar' || chartType === 'area') {
        const barW = Math.max(4, Math.floor(240 / keys.length) - 2);
        const bars = vals.map((v, i) => {
            const h = Math.max(2, Math.round((v / maxVal) * 60));
            return `<div class="adash-bar" style="width:${barW}px;height:${h}px;background:${color}" title="${keys[i]}h: ${v}"></div>`;
        }).join('');
        return `<div class="adash-bar-chart">${bars}</div>`;
    }

    // Line / sparkline: SVG polyline
    const w = 240, h = 60;
    const points = vals.map((v, i) => {
        const x = (i / Math.max(vals.length - 1, 1)) * w;
        const y = h - (v / maxVal) * h;
        return `${x},${y}`;
    }).join(' ');
    return `<svg class="adash-line-chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <polyline points="${points}" fill="none" stroke="${color}" stroke-width="2"/>
    </svg>`;
}

function _renderTable(widget, analytics) {
    if (!analytics) return '<div class="adash-no-data">No data</div>';
    const targets = analytics.top_targets || [];
    if (targets.length === 0) return '<div class="adash-no-data">No entries</div>';

    const maxItems = widget.config?.max_items || 10;
    const rows = targets.slice(0, maxItems).map((t, i) => {
        const id = typeof t === 'object' ? (t.target_id || t.id || '?') : String(t);
        const count = typeof t === 'object' ? (t.count || t.sighting_count || 0) : 0;
        return `<tr><td class="adash-td-rank">${i + 1}</td><td class="adash-td-id">${_esc(String(id))}</td><td class="adash-td-count">${count}</td></tr>`;
    }).join('');
    return `<table class="adash-table"><thead><tr><th>#</th><th>Target</th><th>Count</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function _renderTimeline(widget, analytics) {
    return _renderChart(widget, analytics); // reuse chart renderer for timeline
}

function _renderWidget(widget, analytics) {
    const type = widget.widget_type || 'counter';
    switch (type) {
        case 'counter':  return _renderCounter(widget, analytics);
        case 'chart':    return _renderChart(widget, analytics);
        case 'table':    return _renderTable(widget, analytics);
        case 'timeline': return _renderTimeline(widget, analytics);
        case 'map':      return '<div class="adash-no-data">Map widget (future)</div>';
        default:         return '<div class="adash-no-data">Unknown type</div>';
    }
}

// ---------------------------------------------------------------------------
// Drag and drop
// ---------------------------------------------------------------------------

function _onDragStart(e, idx) {
    _dragState = { fromIdx: idx };
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(idx));
    e.target.classList.add('adash-dragging');
}

function _onDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function _onDrop(e, toIdx) {
    e.preventDefault();
    if (!_dragState) return;
    const fromIdx = _dragState.fromIdx;
    if (fromIdx === toIdx) return;

    // Swap positions
    const moved = _widgets.splice(fromIdx, 1)[0];
    _widgets.splice(toIdx, 0, moved);

    // Update positions
    _widgets.forEach((w, i) => { w.position = { x: i % 3, y: Math.floor(i / 3) }; });

    _saveLayout(_widgets);
    EventBus.emit('analytics-dashboard:refresh');
}

function _onDragEnd(e) {
    _dragState = null;
    e.target.classList.remove('adash-dragging');
}

// ---------------------------------------------------------------------------
// Activity heatmap renderer
// ---------------------------------------------------------------------------

async function _fetchActivityHeatmap() {
    try {
        const resp = await fetch('/api/analytics/activity-heatmap?hours=24');
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

function _renderActivityHeatmap(data) {
    if (!data || !data.hourly_counts) return '<div class="adash-no-data">No heatmap data</div>';
    const counts = data.hourly_counts;
    const maxVal = Math.max(...counts, 1);

    const bars = counts.map((c, h) => {
        const pct = Math.max(2, Math.round((c / maxVal) * 60));
        const intensity = c / maxVal;
        // Color gradient: dim cyan to bright cyan
        const alpha = Math.max(0.15, intensity);
        const label = `${String(h).padStart(2, '0')}:00`;
        return `<div class="adash-heatmap-bar" title="${label}: ${c} sightings"
                     style="height:${pct}px;background:rgba(0,240,255,${alpha})">
            <span class="adash-heatmap-hour">${h}</span>
        </div>`;
    }).join('');

    const peakLabel = `${String(data.peak_hour).padStart(2, '0')}:00`;
    const quietList = (data.quiet_hours || []).map(h => `${String(h).padStart(2, '0')}:00`).join(', ') || 'none';

    return `<div class="adash-heatmap-wrap">
        <div class="adash-heatmap-title" style="color:#00f0ff">24-HOUR ACTIVITY HEATMAP</div>
        <div class="adash-heatmap-chart">${bars}</div>
        <div class="adash-heatmap-meta">
            <span>Peak: <b style="color:#05ffa1">${peakLabel}</b> (${data.peak_count})</span>
            <span>Total: <b>${data.total_sightings}</b></span>
            <span>Quiet: <span style="color:var(--text-dim)">${quietList}</span></span>
        </div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Full render
// ---------------------------------------------------------------------------

async function _renderDashboard(el) {
    if (!el) return;
    el.innerHTML = '<div class="adash-loading">Loading analytics...</div>';

    _widgets = await _fetchWidgets();
    if (_widgets.length === 0) {
        el.innerHTML = '<div class="adash-empty">No widgets configured</div>';
        return;
    }

    // Fetch analytics data for all unique data sources
    const sources = [...new Set(_widgets.map(w => w.data_source).filter(Boolean))];
    const analyticsMap = {};
    await Promise.all(sources.map(async (src) => {
        analyticsMap[src] = await _fetchAnalytics(src);
    }));

    const cards = _widgets.filter(w => w.enabled !== false).map((w, i) => {
        const analytics = analyticsMap[w.data_source] || null;
        const content = _renderWidget(w, analytics);
        const color = w.config?.color || '#00f0ff';
        return `<div class="adash-widget" draggable="true" data-idx="${i}"
                     style="border-color:${color}40;grid-column:span ${w.config?.width || 2}">
            <div class="adash-widget-header">
                <span class="adash-widget-title" style="color:${color}">${_esc(w.title || 'Widget')}</span>
                <button class="adash-widget-toggle" data-idx="${i}" title="Toggle widget">x</button>
            </div>
            <div class="adash-widget-body">${content}</div>
            ${w.description ? `<div class="adash-widget-desc">${_esc(w.description)}</div>` : ''}
        </div>`;
    }).join('');

    // Fetch and render activity heatmap
    const heatmapData = await _fetchActivityHeatmap();
    const heatmapHtml = _renderActivityHeatmap(heatmapData);

    el.innerHTML = `<div class="adash-toolbar">
        <span class="adash-toolbar-title">ANALYTICS DASHBOARD</span>
        <button class="adash-refresh-btn" title="Refresh all widgets">Refresh</button>
        <button class="adash-reset-btn" title="Reset to default layout">Reset</button>
    </div>
    ${heatmapHtml}
    <div class="adash-grid">${cards}</div>`;

    // Wire drag events
    el.querySelectorAll('.adash-widget').forEach(card => {
        const idx = parseInt(card.dataset.idx, 10);
        card.addEventListener('dragstart', e => _onDragStart(e, idx));
        card.addEventListener('dragover', _onDragOver);
        card.addEventListener('drop', e => _onDrop(e, idx));
        card.addEventListener('dragend', _onDragEnd);
    });

    // Wire toggle buttons
    el.querySelectorAll('.adash-widget-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const idx = parseInt(btn.dataset.idx, 10);
            if (_widgets[idx]) {
                _widgets[idx].enabled = false;
                _saveLayout(_widgets);
                _renderDashboard(el);
            }
        });
    });

    // Refresh button
    const refreshBtn = el.querySelector('.adash-refresh-btn');
    if (refreshBtn) refreshBtn.addEventListener('click', () => _renderDashboard(el));

    // Reset button
    const resetBtn = el.querySelector('.adash-reset-btn');
    if (resetBtn) resetBtn.addEventListener('click', async () => {
        await fetch('/api/analytics/widgets/layout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ operator_id: 'default', widgets: [] }),
        });
        _renderDashboard(el);
    });
}

// ---------------------------------------------------------------------------
// Panel definition
// ---------------------------------------------------------------------------

export const AnalyticsDashboardPanelDef = {
    id: 'analytics-dashboard',
    title: 'Analytics Dashboard',
    icon: 'chart',
    width: 700,
    height: 500,
    render(el) {
        el.className = 'analytics-dashboard-panel-inner';
        _renderDashboard(el);

        // Auto-refresh every 30s
        if (_refreshTimer) clearInterval(_refreshTimer);
        _refreshTimer = setInterval(() => _renderDashboard(el), 30000);

        EventBus.on('analytics-dashboard:refresh', () => _renderDashboard(el));
    },
    destroy() {
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
        EventBus.off('analytics-dashboard:refresh');
    },
};
