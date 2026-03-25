// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Convoy Panel — visualize detected convoy groups on the tactical map.
// Backend API: /api/convoys
// Polls for active convoys and renders member groups, heading, speed, suspicious score.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const SCORE_COLORS = {
    low: '#05ffa1',     // green — low suspicion
    medium: '#fcee0a',  // yellow — medium suspicion
    high: '#ff2a6d',    // magenta — high suspicion
};

function scoreColor(score) {
    if (score >= 0.7) return SCORE_COLORS.high;
    if (score >= 0.4) return SCORE_COLORS.medium;
    return SCORE_COLORS.low;
}

function formatSpeed(mps) {
    return (mps * 3.6).toFixed(1) + ' km/h';
}

function formatHeading(deg) {
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    const idx = Math.round(deg / 45) % 8;
    return dirs[idx] + ' (' + Math.round(deg) + ')';
}

function formatDuration(seconds) {
    if (!seconds || seconds < 0) return '--';
    if (seconds < 60) return Math.round(seconds) + 's';
    if (seconds < 3600) return Math.round(seconds / 60) + 'm';
    return (seconds / 3600).toFixed(1) + 'h';
}

export const ConvoyPanelDef = {
    id: 'convoy',
    title: 'CONVOYS',
    defaultPosition: { x: 8, y: 480 },
    defaultSize: { w: 320, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'convoy-panel-inner';
        el.innerHTML = `
            <div class="convoy-toolbar" style="display:flex;gap:4px;margin-bottom:4px;align-items:center">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.45rem">REFRESH</button>
                <span style="flex:1"></span>
                <span class="convoy-summary" data-bind="summary" style="font-size:0.45rem;color:#00f0ff">--</span>
            </div>
            <ul class="panel-list convoy-list" data-bind="list" role="listbox" aria-label="Active convoys">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const summaryEl = bodyEl.querySelector('[data-bind="summary"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');

        let convoys = [];
        let selectedConvoyId = null;
        let pollTimer = null;

        async function fetchConvoys() {
            try {
                const resp = await fetch('/api/convoys');
                if (!resp.ok) return;
                const data = await resp.json();
                convoys = data.convoys || [];
                const summary = data.summary || {};
                if (summaryEl) {
                    const active = summary.active_convoys || 0;
                    const members = summary.total_members || 0;
                    const highest = summary.highest_suspicious_score || 0;
                    const hColor = scoreColor(highest);
                    summaryEl.innerHTML =
                        _esc(active + '') + ' active | ' +
                        _esc(members + '') + ' targets | ' +
                        'max <span style="color:' + hColor + '">' +
                        (highest * 100).toFixed(0) + '%</span>';
                }
                renderList();
            } catch (err) {
                // Network error, keep existing data
            }
        }

        function renderList() {
            if (!listEl) return;
            if (convoys.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No active convoys</li>';
                return;
            }

            listEl.innerHTML = convoys.map(c => {
                const id = _esc(c.convoy_id || '');
                const memberCount = (c.member_target_ids || []).length;
                const score = c.suspicious_score || 0;
                const color = scoreColor(score);
                const speed = formatSpeed(c.speed_avg_mps || 0);
                const heading = formatHeading(c.heading_avg_deg || 0);
                const duration = formatDuration(c.duration_s);
                const selected = c.convoy_id === selectedConvoyId;
                const borderStyle = selected ? 'border-left:2px solid ' + color : 'border-left:2px solid transparent';

                // Member IDs (truncated)
                const memberIds = (c.member_target_ids || []).slice(0, 5);
                const memberStr = memberIds.map(m => _esc(m.substring(0, 12))).join(', ');
                const moreStr = memberCount > 5 ? ' +' + (memberCount - 5) + ' more' : '';

                return `
                    <li class="panel-list-item convoy-item" data-convoy="${id}"
                        style="${borderStyle};padding:4px 6px;margin-bottom:2px;cursor:pointer"
                        role="option" aria-selected="${selected}">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <span style="font-size:0.5rem;color:#00f0ff;font-weight:bold">${id}</span>
                            <span style="font-size:0.45rem;padding:1px 4px;border-radius:2px;background:${color}22;color:${color};border:1px solid ${color}44">
                                ${(score * 100).toFixed(0)}% SUSPICIOUS
                            </span>
                        </div>
                        <div style="display:flex;gap:8px;margin-top:2px;font-size:0.45rem;color:#888">
                            <span>${memberCount} targets</span>
                            <span>${speed}</span>
                            <span>${heading}</span>
                            <span>${duration}</span>
                        </div>
                        <div style="font-size:0.4rem;color:#555;margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                            ${memberStr}${_esc(moreStr)}
                        </div>
                    </li>
                `;
            }).join('');

            // Click handler for each convoy item
            listEl.querySelectorAll('.convoy-item').forEach(item => {
                item.addEventListener('click', () => {
                    const cid = item.dataset.convoy;
                    selectedConvoyId = (selectedConvoyId === cid) ? null : cid;
                    renderList();

                    // Find the convoy and emit center event for map
                    const convoy = convoys.find(c => c.convoy_id === cid);
                    if (convoy && convoy.bbox) {
                        EventBus.emit('map:center', {
                            lat: convoy.bbox.center_lat,
                            lng: convoy.bbox.center_lng,
                            zoom: 17,
                        });
                    }

                    // Emit convoy selection for map overlay
                    EventBus.emit('convoy:selected', {
                        convoy_id: selectedConvoyId,
                        convoy: selectedConvoyId ? convoy : null,
                    });
                });
            });
        }

        if (refreshBtn) {
            refreshBtn.addEventListener('click', fetchConvoys);
        }

        // Initial fetch and poll
        fetchConvoys();
        pollTimer = setInterval(fetchConvoys, 15000);

        // Cleanup
        panel._convoyCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    unmount(bodyEl, panel) {
        if (panel._convoyCleanup) {
            panel._convoyCleanup();
            panel._convoyCleanup = null;
        }
    },
};
