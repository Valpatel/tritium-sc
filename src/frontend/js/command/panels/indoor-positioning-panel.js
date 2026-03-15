// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Indoor Positioning Panel — fused WiFi fingerprint + BLE trilateration
// Shows indoor position estimates, room assignments, uncertainty radius,
// and WiFi vs BLE contribution indicators.
// Backend API: /api/indoor (positions, position/{id}, status)

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';


const REFRESH_INTERVAL_MS = 5000;

function methodColor(method) {
    if (method === 'fused') return '#05ffa1';
    if (method === 'fingerprint') return '#00f0ff';
    if (method === 'trilateration') return '#ff2a6d';
    return '#888';
}

function methodLabel(method) {
    if (method === 'fused') return 'FUSED';
    if (method === 'fingerprint') return 'WIFI';
    if (method === 'trilateration') return 'BLE';
    return method ? method.toUpperCase() : '??';
}

function confidenceBar(confidence) {
    const pct = Math.round((confidence || 0) * 100);
    const color = pct >= 70 ? '#05ffa1' : pct >= 40 ? '#fcee0a' : '#ff2a6d';
    return `<span style="display:inline-flex;align-items:center;gap:4px">
        <span style="display:inline-block;width:50px;height:6px;background:#1a1a2e;border-radius:3px;overflow:hidden">
            <span style="display:block;width:${pct}%;height:100%;background:${color}"></span>
        </span>
        <span class="mono" style="color:${color};font-size:0.4rem">${pct}%</span>
    </span>`;
}

function uncertaintyBadge(meters) {
    if (meters === undefined || meters === null) return '';
    const color = meters <= 3 ? '#05ffa1' : meters <= 8 ? '#fcee0a' : '#ff2a6d';
    return `<span class="mono" style="color:${color};font-size:0.38rem" title="Uncertainty radius">&plusmn;${meters.toFixed(1)}m</span>`;
}

function contributionIndicator(pos) {
    const hasWifi = pos.wifi_estimate != null;
    const hasBle = pos.ble_estimate != null;
    const wifiConf = hasWifi ? Math.round((pos.wifi_estimate.confidence || 0) * 100) : 0;
    const bleConf = hasBle ? Math.round((pos.ble_estimate.confidence || 0) * 100) : 0;

    let parts = [];
    if (hasWifi) {
        parts.push(`<span style="color:#00f0ff" title="WiFi fingerprint ${wifiConf}%">W:${wifiConf}%</span>`);
    }
    if (hasBle) {
        parts.push(`<span style="color:#ff2a6d" title="BLE trilateration ${bleConf}%">B:${bleConf}%</span>`);
    }
    if (!parts.length) {
        parts.push(`<span style="color:#888">--</span>`);
    }
    return `<span class="mono" style="font-size:0.38rem;display:inline-flex;gap:6px">${parts.join('')}</span>`;
}

export const IndoorPositioningPanelDef = {
    id: 'indoor-positioning',
    title: 'INDOOR POSITIONING',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 400, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'indoor-pos-panel-inner';
        el.innerHTML = `
            <div class="indoor-pos-toolbar" style="display:flex;justify-content:space-between;align-items:center;padding:4px 6px;border-bottom:1px solid #1a1a2e">
                <span class="mono" style="color:#00f0ff;font-size:0.42rem" data-bind="engine-status">--</span>
                <div style="display:flex;gap:4px;align-items:center">
                    <span class="mono" style="color:#888;font-size:0.38rem" data-bind="target-count">0 targets</span>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.4rem">REFRESH</button>
                </div>
            </div>
            <div class="indoor-pos-legend" style="display:flex;gap:10px;padding:3px 6px;font-size:0.36rem;border-bottom:1px solid #0e0e14">
                <span style="color:#05ffa1">FUSED</span>
                <span style="color:#00f0ff">WIFI</span>
                <span style="color:#ff2a6d">BLE</span>
                <span style="color:#888">|</span>
                <span style="color:#888">W=WiFi B=BLE contribution</span>
            </div>
            <ul class="panel-list indoor-pos-list" data-bind="positions" role="listbox" aria-label="Indoor positions" style="flex:1;overflow-y:auto;margin:0;padding:0">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    init(panel) {
        const el = panel.contentEl;
        let pollTimer = null;

        const statusEl = el.querySelector('[data-bind="engine-status"]');
        const countEl = el.querySelector('[data-bind="target-count"]');
        const listEl = el.querySelector('[data-bind="positions"]');
        const refreshBtn = el.querySelector('[data-action="refresh"]');

        if (refreshBtn) {
            refreshBtn.addEventListener('click', refresh);
        }

        async function refresh() {
            try {
                await Promise.all([loadStatus(), loadPositions()]);
            } catch (err) {
                console.warn('[indoor-positioning] refresh error:', err);
            }
        }

        async function loadStatus() {
            try {
                const res = await fetch('/api/indoor/status');
                if (!res.ok) {
                    if (statusEl) statusEl.textContent = 'API unavailable';
                    return;
                }
                const data = await res.json();
                if (statusEl) {
                    const methods = (data.methods || []).join('+').toUpperCase();
                    statusEl.textContent = `ENGINE: ${data.engine || '--'} [${methods}]`;
                }
                if (countEl) {
                    countEl.textContent = `${data.tracked_targets || 0} targets`;
                }
            } catch (_) {
                if (statusEl) statusEl.textContent = 'Error';
            }
        }

        async function loadPositions() {
            try {
                const res = await fetch('/api/indoor/positions?limit=100');
                if (!res.ok) {
                    if (listEl) listEl.innerHTML = '<li class="panel-empty">API unavailable</li>';
                    return;
                }
                const data = await res.json();
                const positions = data.positions || [];

                if (!positions.length) {
                    if (listEl) listEl.innerHTML = '<li class="panel-empty">No indoor positions tracked</li>';
                    return;
                }

                // Sort by confidence descending
                positions.sort((a, b) => (b.confidence || 0) - (a.confidence || 0));

                if (listEl) {
                    listEl.innerHTML = positions.map(pos => {
                        const mColor = methodColor(pos.method);
                        const mLabel = methodLabel(pos.method);
                        const targetId = _esc(pos.target_id || '--');
                        const lat = pos.lat != null ? pos.lat.toFixed(6) : '--';
                        const lon = pos.lon != null ? pos.lon.toFixed(6) : '--';
                        const room = pos.room_name || pos.room_id || '';
                        const floor = pos.floor_level != null && pos.floor_level !== 0 ? `F${pos.floor_level}` : '';
                        const building = pos.building || '';
                        const locationParts = [building, floor, room].filter(Boolean);
                        const locationStr = locationParts.length ? locationParts.join(' / ') : '';
                        const ts = pos.timestamp ? new Date(pos.timestamp * 1000).toLocaleTimeString() : '';

                        return `<li class="panel-list-item" style="border-left:3px solid ${mColor};padding:4px 6px;margin-bottom:1px">
                            <div style="display:flex;justify-content:space-between;align-items:center">
                                <span class="mono" style="color:#ccc;font-size:0.44rem" title="${targetId}">${targetId.length > 24 ? targetId.slice(0, 24) + '..' : targetId}</span>
                                <span style="color:${mColor};font-size:0.38rem;font-weight:bold">[${mLabel}]</span>
                            </div>
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
                                <span class="mono" style="color:#888;font-size:0.38rem">${lat}, ${lon}</span>
                                ${uncertaintyBadge(pos.uncertainty_m)}
                            </div>
                            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:2px">
                                ${confidenceBar(pos.confidence)}
                                ${contributionIndicator(pos)}
                            </div>
                            ${locationStr ? `<div style="margin-top:2px;font-size:0.38rem;color:#05ffa1" title="Room assignment">${_esc(locationStr)}</div>` : ''}
                            <div style="text-align:right;margin-top:1px">
                                <span class="mono" style="color:#555;font-size:0.34rem">${ts}</span>
                            </div>
                        </li>`;
                    }).join('');
                }
            } catch (err) {
                if (listEl) listEl.innerHTML = '<li class="panel-empty">Error loading positions</li>';
            }
        }

        // Real-time updates via EventBus
        EventBus.on('indoor_positioning:fused_position', () => {
            refresh();
        });

        // Initial load
        refresh();

        // Poll every 5 seconds
        pollTimer = setInterval(refresh, REFRESH_INTERVAL_MS);

        panel._indoorPosCleanup = () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    destroy(panel) {
        if (panel._indoorPosCleanup) panel._indoorPosCleanup();
    },
};
