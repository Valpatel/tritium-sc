// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// RF Motion Panel — shows RF-based motion detection events and zone occupancy.
// Backend API: /api/rf-motion (events, baselines, zones, active)
// Polls /api/rf-motion/active for live motion indicators.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const DIRECTION_ICONS = {
    approaching: '>',
    departing: '<',
    crossing: 'X',
    unknown: '?',
};

const DIRECTION_COLORS = {
    approaching: '#ff2a6d',
    departing: '#05ffa1',
    crossing: '#fcee0a',
    unknown: '#00f0ff',
};

export const RfMotionPanelDef = {
    id: 'rf-motion',
    title: 'RF MOTION',
    defaultPosition: { x: 8, y: 440 },
    defaultSize: { w: 300, h: 380 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'rf-motion-panel-inner';
        el.innerHTML = `
            <div class="rfm-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="detect">DETECT NOW</button>
            </div>
            <div class="rfm-status" data-bind="status" style="padding:2px 4px;font-size:0.48rem"></div>
            <div class="rfm-tab-bar" style="display:flex;gap:2px;margin:4px 0">
                <button class="panel-action-btn panel-action-btn-primary rfm-tab" data-tab="active" style="flex:1;font-size:0.45rem">ACTIVE</button>
                <button class="panel-action-btn rfm-tab" data-tab="baselines" style="flex:1;font-size:0.45rem">BASELINES</button>
                <button class="panel-action-btn rfm-tab" data-tab="zones" style="flex:1;font-size:0.45rem">ZONES</button>
            </div>
            <ul class="panel-list rfm-list" data-bind="list" role="listbox" aria-label="RF motion events">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const detectBtn = bodyEl.querySelector('[data-action="detect"]');
        const tabs = bodyEl.querySelectorAll('.rfm-tab');

        let activeTab = 'active';
        let activeData = null;
        let baselines = [];
        let zones = [];

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeTab = tab.dataset.tab;
                tabs.forEach(t => t.classList.toggle('panel-action-btn-primary', t.dataset.tab === activeTab));
                renderTab();
            });
        });

        function renderTab() {
            if (activeTab === 'active') renderActive();
            else if (activeTab === 'baselines') renderBaselines();
            else if (activeTab === 'zones') renderZones();
        }

        function renderActive() {
            if (!listEl || !activeData) {
                if (listEl) listEl.innerHTML = '<li class="panel-empty">No data</li>';
                return;
            }
            const pairs = activeData.active_pairs || [];
            const occ = activeData.occupied_zones || [];
            const motionDetected = activeData.motion_detected;

            if (statusEl) {
                const color = motionDetected ? '#ff2a6d' : '#05ffa1';
                const label = motionDetected ? 'MOTION DETECTED' : 'ALL CLEAR';
                statusEl.innerHTML = `<span style="color:${color};font-weight:bold">${label}</span>
                    <span class="mono" style="color:var(--text-ghost);margin-left:8px">${pairs.length} pairs | ${occ.length} zones</span>`;
            }

            // Publish to map for rendering
            EventBus.emit('rfMotion:update', { pairs, zones: occ, motionDetected });

            if (pairs.length === 0 && occ.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No active motion</li>';
                return;
            }

            let html = '';
            for (const p of pairs) {
                const dir = p.direction_hint || 'unknown';
                const icon = DIRECTION_ICONS[dir] || '?';
                const color = DIRECTION_COLORS[dir] || '#00f0ff';
                const var_str = p.variance != null ? p.variance.toFixed(1) : '?';
                const conf = p.confidence != null ? Math.round(p.confidence * 100) : '?';
                html += `<li class="panel-list-item" style="font-size:0.48rem">
                    <span style="color:${color};font-weight:bold;width:14px;text-align:center">${icon}</span>
                    <span style="flex:1;min-width:0">
                        <span style="color:var(--text-main)">${_esc(p.node_a)} - ${_esc(p.node_b)}</span><br>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)">var:${var_str} | ${conf}% | ${_esc(p.mean_rssi?.toFixed(0) || '?')}dBm</span>
                    </span>
                </li>`;
            }

            for (const z of occ) {
                html += `<li class="panel-list-item" style="font-size:0.48rem">
                    <span style="color:#ff2a6d;font-weight:bold;width:14px;text-align:center">Z</span>
                    <span style="flex:1">
                        <span style="color:var(--text-main)">${_esc(z.name || z.zone_id)}</span>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)"> occupied</span>
                    </span>
                </li>`;
            }

            listEl.innerHTML = html;
        }

        function renderBaselines() {
            if (!listEl) return;
            if (baselines.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No baselines recorded</li>';
                return;
            }
            listEl.innerHTML = baselines.map(b => {
                const motionColor = b.motion_active ? '#ff2a6d' : '#05ffa1';
                const motionLabel = b.motion_active ? 'MOTION' : 'STATIC';
                return `<li class="panel-list-item" style="font-size:0.48rem">
                    <span class="panel-dot" style="background:${motionColor}"></span>
                    <span style="flex:1;min-width:0">
                        <span style="color:var(--text-main)">${_esc(b.pair_id)}</span><br>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)">
                            mean:${b.mean_rssi?.toFixed(0) || '?'}dBm | var:${b.variance?.toFixed(1) || '?'} | ${b.sample_count} samples | ${motionLabel}
                        </span>
                    </span>
                </li>`;
            }).join('');
        }

        function renderZones() {
            if (!listEl) return;
            if (zones.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No RF motion zones</li>';
                return;
            }
            listEl.innerHTML = zones.map(z => {
                const occ = z.occupied ? '#ff2a6d' : '#05ffa1';
                return `<li class="panel-list-item" style="font-size:0.48rem">
                    <span class="panel-dot" style="background:${occ}"></span>
                    <span style="flex:1">
                        <span style="color:var(--text-main)">${_esc(z.name || z.zone_id)}</span>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)"> ${z.occupied ? 'OCCUPIED' : 'VACANT'} | ${(z.pair_ids || []).length} pairs</span>
                    </span>
                </li>`;
            }).join('');
        }

        async function fetchActive() {
            try {
                const resp = await fetch('/api/rf-motion/active');
                if (!resp.ok) { activeData = { active_pairs: [], occupied_zones: [], motion_detected: false }; renderTab(); return; }
                activeData = await resp.json();
                if (activeTab === 'active') renderActive();
            } catch (_) {
                activeData = { active_pairs: [], occupied_zones: [], motion_detected: false };
                if (activeTab === 'active') renderActive();
            }
        }

        async function fetchBaselines() {
            try {
                const resp = await fetch('/api/rf-motion/baselines');
                if (!resp.ok) { baselines = []; return; }
                const data = await resp.json();
                baselines = data.baselines || [];
                if (activeTab === 'baselines') renderBaselines();
            } catch (_) {
                baselines = [];
            }
        }

        async function fetchZones() {
            try {
                const resp = await fetch('/api/rf-motion/zones');
                if (!resp.ok) { zones = []; return; }
                const data = await resp.json();
                zones = data.zones || [];
                if (activeTab === 'zones') renderZones();
            } catch (_) {
                zones = [];
            }
        }

        async function fetchAll() {
            await Promise.all([fetchActive(), fetchBaselines(), fetchZones()]);
            renderTab();
        }

        async function triggerDetect() {
            try {
                const resp = await fetch('/api/rf-motion/detect', { method: 'POST' });
                if (resp.ok) {
                    EventBus.emit('toast:show', { message: 'Detection cycle triggered', type: 'info' });
                    fetchActive();
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Detection failed', type: 'alert' });
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchAll);
        if (detectBtn) detectBtn.addEventListener('click', triggerDetect);

        // Poll active every 5s for live updates
        const pollInterval = setInterval(fetchActive, 5000);
        panel._unsubs.push(() => clearInterval(pollInterval));

        fetchAll();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
