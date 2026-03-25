// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Acoustic Intelligence Panel — ML sound classification, event timeline,
// expanding ring visualization, and source localization.
// Backend API: /api/acoustic (classify, timeline, localizations, stats)

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const SEVERITY_COLORS = {
    high: '#ff2a6d',
    medium: '#fcee0a',
    low: '#00f0ff',
};

const EVENT_ICONS = {
    gunshot: '!',
    explosion: '*',
    glass_break: '#',
    siren: '~',
    alarm: '^',
    vehicle: 'V',
    voice: 'S',
    animal: 'A',
    footsteps: '.',
    machinery: 'M',
    music: 'N',
    unknown: '?',
};

export const AcousticIntelligencePanelDef = {
    id: 'acoustic-intelligence',
    title: 'ACOUSTIC INTEL',
    defaultPosition: { x: 8, y: 440 },
    defaultSize: { w: 320, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'acoustic-intel-panel-inner';
        el.innerHTML = `
            <div class="aci-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <span class="aci-ml-badge" data-bind="ml-status" style="font-size:0.42rem;color:#05ffa1">--</span>
            </div>
            <div class="aci-stats" data-bind="stats" style="padding:2px 4px;font-size:0.45rem;color:#888"></div>
            <div class="aci-tab-bar" style="display:flex;gap:2px;margin:4px 0">
                <button class="panel-action-btn panel-action-btn-primary aci-tab" data-tab="timeline" style="flex:1;font-size:0.43rem">TIMELINE</button>
                <button class="panel-action-btn aci-tab" data-tab="localize" style="flex:1;font-size:0.43rem">LOCALIZE</button>
                <button class="panel-action-btn aci-tab" data-tab="counts" style="flex:1;font-size:0.43rem">COUNTS</button>
            </div>
            <ul class="panel-list aci-list" data-bind="list" role="listbox" aria-label="Acoustic events">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let activeTab = 'timeline';
        let pollTimer = null;

        // Tab switching
        el.querySelectorAll('.aci-tab').forEach(btn => {
            btn.addEventListener('click', () => {
                el.querySelectorAll('.aci-tab').forEach(b =>
                    b.classList.remove('panel-action-btn-primary')
                );
                btn.classList.add('panel-action-btn-primary');
                activeTab = btn.dataset.tab;
                refresh();
            });
        });

        // Toolbar actions
        el.querySelector('[data-action="refresh"]')
            .addEventListener('click', refresh);

        async function refresh() {
            try {
                if (activeTab === 'timeline') {
                    await loadTimeline();
                } else if (activeTab === 'localize') {
                    await loadLocalizations();
                } else if (activeTab === 'counts') {
                    await loadCounts();
                }
                await loadStats();
            } catch (err) {
                console.warn('[acoustic-intel] refresh error:', err);
            }
        }

        async function loadStats() {
            try {
                const res = await fetch('/api/acoustic/stats');
                if (!res.ok) return;
                const data = await res.json();
                const statsEl = el.querySelector('[data-bind="stats"]');
                const mlEl = el.querySelector('[data-bind="ml-status"]');
                if (statsEl) {
                    statsEl.textContent = `Events: ${data.events_classified || 0} | `
                        + `Targets: ${data.active_targets || 0} | `
                        + `High: ${data.high_severity_count || 0} | `
                        + `Loc: ${data.localizations || 0}`;
                }
                if (mlEl) {
                    if (data.ml_available) {
                        mlEl.textContent = 'ML ACTIVE';
                        mlEl.style.color = '#05ffa1';
                    } else {
                        mlEl.textContent = 'RULES ONLY';
                        mlEl.style.color = '#fcee0a';
                    }
                }
            } catch (_) { /* ignore */ }
        }

        async function loadTimeline() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/acoustic/timeline?count=50');
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                const events = data.events || [];
                if (!events.length) {
                    list.innerHTML = '<li class="panel-empty">No acoustic events</li>';
                    return;
                }
                list.innerHTML = events.slice().reverse().map(e => {
                    const icon = EVENT_ICONS[e.event_type] || '?';
                    const color = e.color || '#00f0ff';
                    const ts = new Date(e.timestamp * 1000).toLocaleTimeString();
                    const conf = Math.round((e.confidence || 0) * 100);
                    const model = (e.model_version || '').includes('knn') ? ' [ML]' : '';
                    const loc = e.location ? ` @ ${e.location[0].toFixed(4)},${e.location[1].toFixed(4)}` : '';
                    return `<li class="panel-list-item" style="border-left:3px solid ${_esc(color)};padding-left:6px">
                        <span style="color:${_esc(color)};font-weight:bold">[${_esc(icon)}]</span>
                        <span style="color:#ccc">${_esc(e.event_type)}</span>
                        <span style="color:#888;font-size:0.4rem">${conf}%${model}${loc}</span>
                        <span style="color:#555;font-size:0.38rem;float:right">${ts}</span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading timeline</li>';
            }
        }

        async function loadLocalizations() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/acoustic/localizations?count=30');
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                const locs = data.localizations || [];
                if (!locs.length) {
                    list.innerHTML = '<li class="panel-empty">No localizations yet (need 2+ sensors)</li>';
                    return;
                }
                list.innerHTML = locs.slice().reverse().map(loc => {
                    const ts = new Date(loc.timestamp * 1000).toLocaleTimeString();
                    const conf = Math.round((loc.confidence || 0) * 100);
                    const color = SEVERITY_COLORS.high;
                    return `<li class="panel-list-item" style="border-left:3px solid ${color};padding-left:6px">
                        <span style="color:${color}">${_esc(loc.event_type)}</span>
                        <span style="color:#05ffa1">${loc.estimated_lat.toFixed(5)}, ${loc.estimated_lon.toFixed(5)}</span>
                        <span style="color:#888;font-size:0.4rem">${conf}% | ${loc.observers} nodes</span>
                        <span style="color:#555;font-size:0.38rem;float:right">${ts}</span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading localizations</li>';
            }
        }

        async function loadCounts() {
            const list = el.querySelector('[data-bind="list"]');
            try {
                const res = await fetch('/api/acoustic/counts');
                if (!res.ok) { list.innerHTML = '<li class="panel-empty">API unavailable</li>'; return; }
                const data = await res.json();
                const counts = data.counts || {};
                const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
                if (!entries.length) {
                    list.innerHTML = '<li class="panel-empty">No events classified yet</li>';
                    return;
                }
                list.innerHTML = entries.map(([type, count]) => {
                    const icon = EVENT_ICONS[type] || '?';
                    const barWidth = Math.min(100, (count / Math.max(...entries.map(e => e[1]))) * 100);
                    return `<li class="panel-list-item">
                        <span style="color:#00f0ff;width:20px;display:inline-block">[${_esc(icon)}]</span>
                        <span style="color:#ccc;width:90px;display:inline-block">${_esc(type)}</span>
                        <span style="color:#05ffa1;width:40px;display:inline-block;text-align:right">${count}</span>
                        <span style="display:inline-block;width:${barWidth}px;height:6px;background:#00f0ff44;margin-left:8px;vertical-align:middle"></span>
                    </li>`;
                }).join('');
            } catch (err) {
                list.innerHTML = '<li class="panel-empty">Error loading counts</li>';
            }
        }

        // WebSocket events for real-time acoustic updates
        EventBus.on('acoustic:classified', (data) => {
            if (activeTab === 'timeline') {
                refresh();
            }
        });

        EventBus.on('acoustic:localized', (data) => {
            if (activeTab === 'localize') {
                refresh();
            }
            // Emit map ring event for expanding ring visualization
            if (data && data.estimated_lat && data.estimated_lon) {
                EventBus.emit('map:acoustic_ring', {
                    lat: data.estimated_lat,
                    lon: data.estimated_lon,
                    event_type: data.event_type,
                    confidence: data.confidence,
                    color: SEVERITY_COLORS[
                        ['gunshot', 'explosion', 'glass_break'].includes(data.event_type) ? 'high'
                        : ['siren', 'alarm', 'vehicle'].includes(data.event_type) ? 'medium'
                        : 'low'
                    ],
                });
            }
        });

        // Initial load
        refresh();

        // Poll every 5 seconds
        pollTimer = setInterval(refresh, 5000);

        panel._acousticCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._acousticCleanup) panel._acousticCleanup();
    },
};
