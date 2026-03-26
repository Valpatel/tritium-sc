// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Amy Daily Briefing Panel — shows Amy's natural-language daily briefing
// with threat assessment, target counts, notable events, and LLM/template source.
// Auto-refreshes every 60 seconds, caches the last briefing locally.

import { _esc } from '/lib/utils.js';

const REFRESH_MS = 60000; // 60 seconds

const THREAT_COLORS = {
    LOW:      '#05ffa1',
    MODERATE: '#fcee0a',
    HIGH:     '#ff2a6d',
    CRITICAL: '#ff2a6d',
    UNKNOWN:  '#666',
};

/**
 * Format an ISO timestamp to a short local string.
 */
function _fmtTime(iso) {
    if (!iso) return '--';
    try {
        const d = new Date(iso);
        return d.toLocaleString(undefined, {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    } catch { return '--'; }
}

/**
 * Render the briefing response data as HTML.
 */
function _renderBriefing(data) {
    if (!data || !data.text) {
        return '<div style="color:#555;padding:20px;text-align:center;">No briefing available. Click GENERATE to create one.</div>';
    }

    const threat = data.context_summary?.threat_level || 'UNKNOWN';
    const threatColor = THREAT_COLORS[threat] || THREAT_COLORS.UNKNOWN;
    const totalTargets = data.context_summary?.total_targets ?? 0;
    const newTargets = data.context_summary?.new_targets_24h ?? 0;
    const source = data.source || 'unknown';
    const generatedAt = _fmtTime(data.generated_at);
    const briefingId = data.briefing_id || '--';

    // Pre-format the briefing text — preserve line breaks
    const lines = String(data.text).split('\n');
    let textHtml = '';
    for (const line of lines) {
        textHtml += `<div style="margin-bottom:2px;">${_esc(line) || '&nbsp;'}</div>`;
    }

    return `
        <div class="ab-header" style="
            display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;
        ">
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">THREAT LEVEL</div>
                <div style="font-size:13px;color:${threatColor};margin-top:2px;font-family:monospace;font-weight:bold;">${_esc(threat)}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">TOTAL TARGETS</div>
                <div style="font-size:13px;color:#00f0ff;margin-top:2px;font-family:monospace;">${_esc(String(totalTargets))}</div>
            </div>
            <div style="background:#0e0e14;border:1px solid #1a1a2e;border-radius:3px;padding:5px;text-align:center;">
                <div style="font-size:9px;color:#666;text-transform:uppercase;letter-spacing:0.5px;">NEW (24H)</div>
                <div style="font-size:13px;color:#05ffa1;margin-top:2px;font-family:monospace;">${_esc(String(newTargets))}</div>
            </div>
        </div>
        <div class="ab-meta" style="
            display:flex;justify-content:space-between;align-items:center;
            padding:4px 8px;margin-bottom:8px;
            background:rgba(0,0,0,0.3);border:1px solid #1a1a2e;border-radius:3px;
        ">
            <span style="font-size:9px;color:#666;font-family:monospace;">${_esc(briefingId)}</span>
            <span style="font-size:9px;color:#888;">${_esc(generatedAt)}</span>
            <span style="font-size:9px;color:${source === 'ollama' ? '#05ffa1' : '#fcee0a'};text-transform:uppercase;">${_esc(source)}</span>
        </div>
        <div class="ab-text" style="
            font-family:'JetBrains Mono',monospace;font-size:10px;color:#ccc;
            line-height:1.5;padding:8px;
            background:#0a0a12;border:1px solid #1a1a2e;border-radius:3px;
            max-height:400px;overflow-y:auto;
        ">
            ${textHtml}
        </div>
    `;
}


export const AmyBriefingPanelDef = {
    id: 'amy-briefing',
    title: 'AMY DAILY BRIEFING',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 420, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'ab-panel-inner';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;font-family:"JetBrains Mono",monospace;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <button class="panel-action-btn panel-action-btn-primary" data-action="generate-briefing" style="font-size:0.42rem">GENERATE BRIEFING</button>
                <button class="panel-action-btn" data-action="refresh-briefing" style="font-size:0.42rem">REFRESH</button>
                <span data-bind="ab-status" style="font-size:9px;color:#555;margin-left:auto;font-family:monospace;">--</span>
            </div>
            <div data-bind="ab-content">
                <div style="color:#555;padding:20px;text-align:center;">Loading briefing...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="ab-content"]');
        const statusEl = bodyEl.querySelector('[data-bind="ab-status"]');
        const generateBtn = bodyEl.querySelector('[data-action="generate-briefing"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-briefing"]');
        let timer = null;
        let _cachedBriefing = null;

        async function fetchBriefing() {
            if (!contentEl) return;
            if (statusEl) statusEl.textContent = 'loading...';

            try {
                const resp = await fetch('/api/amy/briefing');
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const data = await resp.json();
                _cachedBriefing = data;
                contentEl.innerHTML = _renderBriefing(data);
                if (statusEl) statusEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                // Fall back to cached briefing if available
                if (_cachedBriefing) {
                    contentEl.innerHTML = _renderBriefing(_cachedBriefing);
                    if (statusEl) statusEl.textContent = 'cached (offline)';
                } else {
                    contentEl.innerHTML = '<div style="color:#ff2a6d;padding:20px;text-align:center;">Failed to load briefing</div>';
                    if (statusEl) statusEl.textContent = 'error';
                }
            }
        }

        async function generateBriefing() {
            if (!contentEl) return;
            if (statusEl) statusEl.textContent = 'generating...';
            if (generateBtn) generateBtn.disabled = true;

            try {
                const resp = await fetch('/api/amy/briefing', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                const data = await resp.json();
                _cachedBriefing = data;
                contentEl.innerHTML = _renderBriefing(data);
                if (statusEl) statusEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                contentEl.innerHTML = '<div style="color:#ff2a6d;padding:20px;text-align:center;">Failed to generate briefing</div>';
                if (statusEl) statusEl.textContent = 'error';
            } finally {
                if (generateBtn) generateBtn.disabled = false;
            }
        }

        if (generateBtn) {
            generateBtn.addEventListener('click', generateBriefing);
        }
        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchBriefing);
        }

        // Initial fetch
        fetchBriefing();

        // Auto-refresh every 60 seconds
        timer = setInterval(fetchBriefing, REFRESH_MS);
        panel._abTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._abTimer) {
            clearInterval(panel._abTimer);
            panel._abTimer = null;
        }
    },
};
