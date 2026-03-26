// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Amy Briefing tab — registers the daily briefing as a tab in the Commander container.

import { EventBus } from '../../events.js';
import { _esc } from '/lib/utils.js';

const THREAT_COLORS = {
    LOW:      '#05ffa1',
    MODERATE: '#fcee0a',
    HIGH:     '#ff2a6d',
    CRITICAL: '#ff2a6d',
    UNKNOWN:  '#666',
};

function _fmtTime(iso) {
    if (!iso) return '--';
    try {
        const d = new Date(iso);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return '--'; }
}

EventBus.emit('panel:register-tab', {
    container: 'commander-container',
    id: 'amy-briefing-tab',
    title: 'BRIEFING',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                    <div style="color:#00f0ff;font-size:12px;font-weight:bold;">DAILY BRIEFING</div>
                    <button class="ab-btn" data-action="gen" style="margin-left:auto;color:#ff2a6d;border-color:#ff2a6d">GENERATE</button>
                    <button class="ab-btn" data-action="get">REFRESH</button>
                </div>
                <div data-bind="ab-metrics" style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;margin-bottom:8px;"></div>
                <div data-bind="ab-meta" style="font-size:9px;color:#555;margin-bottom:4px;"></div>
                <div data-bind="ab-text" style="font-size:10px;color:#aaa;line-height:1.5;max-height:280px;overflow-y:auto;background:#0a0a12;border:1px solid #1a1a2e;border-radius:3px;padding:6px;">
                    <span style="color:#555;">Click GENERATE or REFRESH to load briefing.</span>
                </div>
            </div>
            <style>
                .ab-btn{background:#0a0a12;border:1px solid #1a1a2e;padding:3px 8px;font-family:inherit;font-size:10px;cursor:pointer;color:#888}
                .ab-metric-card{background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:4px;text-align:center}
                .ab-metric-label{font-size:8px;color:#555;text-transform:uppercase;letter-spacing:0.5px}
                .ab-metric-val{font-size:12px;font-family:monospace;margin-top:1px}
            </style>
        `;

        let _cached = null;

        function render(data) {
            _cached = data;
            const metricsEl = el.querySelector('[data-bind="ab-metrics"]');
            const metaEl = el.querySelector('[data-bind="ab-meta"]');
            const textEl = el.querySelector('[data-bind="ab-text"]');
            if (!data || !data.text) {
                if (textEl) textEl.innerHTML = '<span style="color:#555;">No briefing available.</span>';
                return;
            }
            const threat = data.context_summary?.threat_level || 'UNKNOWN';
            const threatColor = THREAT_COLORS[threat] || '#666';
            const total = data.context_summary?.total_targets ?? 0;
            const newT = data.context_summary?.new_targets_24h ?? 0;
            if (metricsEl) {
                metricsEl.innerHTML = `
                    <div class="ab-metric-card"><div class="ab-metric-label">THREAT</div><div class="ab-metric-val" style="color:${threatColor}">${_esc(threat)}</div></div>
                    <div class="ab-metric-card"><div class="ab-metric-label">TARGETS</div><div class="ab-metric-val" style="color:#00f0ff">${_esc(String(total))}</div></div>
                    <div class="ab-metric-card"><div class="ab-metric-label">NEW 24H</div><div class="ab-metric-val" style="color:#05ffa1">${_esc(String(newT))}</div></div>
                `;
            }
            if (metaEl) {
                const src = data.source === 'ollama' ? '<span style="color:#05ffa1">LLM</span>' : '<span style="color:#fcee0a">TEMPLATE</span>';
                metaEl.innerHTML = `${_esc(data.briefing_id || '--')} | ${_esc(_fmtTime(data.generated_at))} | ${src}`;
            }
            if (textEl) {
                const lines = String(data.text).split('\n');
                textEl.innerHTML = lines.map(l => `<div>${_esc(l) || '&nbsp;'}</div>`).join('');
            }
        }

        function doFetch() {
            fetch('/api/amy/briefing').then(r => r.ok ? r.json() : null)
                .then(d => { if (d) render(d); })
                .catch(() => { if (_cached) render(_cached); });
        }

        function doGenerate() {
            const btn = el.querySelector('[data-action="gen"]');
            if (btn) btn.disabled = true;
            fetch('/api/amy/briefing', { method: 'POST', headers: { 'Content-Type': 'application/json' } })
                .then(r => r.ok ? r.json() : null)
                .then(d => { if (d) render(d); })
                .catch(() => {})
                .finally(() => { if (btn) btn.disabled = false; });
        }

        el.querySelector('[data-action="gen"]').addEventListener('click', doGenerate);
        el.querySelector('[data-action="get"]').addEventListener('click', doFetch);

        // Initial fetch
        doFetch();

        // Auto-refresh every 60s
        el._abInterval = setInterval(doFetch, 60000);
    },
    unmount(el) {
        if (el && el._abInterval) { clearInterval(el._abInterval); el._abInterval = null; }
    },
});
