// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Traffic tab for the Simulation container.
 * Shows vehicle stats, road network info, congestion metrics.
 * Registers itself as a tab via EventBus.
 */

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'simulation-container',
    id: 'traffic-tab',
    title: 'TRAFFIC',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#00f0ff;margin-bottom:8px;font-size:12px">TRAFFIC</div>
                <div class="st-row"><span class="st-l">VEHICLES</span><span class="st-v" data-bind="veh">--</span></div>
                <div class="st-row"><span class="st-l">AVG SPEED</span><span class="st-v" data-bind="speed">--</span></div>
                <div class="st-row"><span class="st-l">COMMUTE</span><span class="st-v" data-bind="commute">--</span></div>
                <div class="st-row"><span class="st-l">DELIVERY</span><span class="st-v" data-bind="delivery">--</span></div>
                <div class="st-row"><span class="st-l">TAXI</span><span class="st-v" data-bind="taxi">--</span></div>
                <div class="st-row"><span class="st-l">PATROL</span><span class="st-v" data-bind="patrol">--</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px">NETWORK</div>
                <div class="st-row"><span class="st-l">NODES</span><span class="st-v" data-bind="nodes">--</span></div>
                <div class="st-row"><span class="st-l">EDGES</span><span class="st-v" data-bind="edges">--</span></div>
                <div class="st-row"><span class="st-l">CONTROLLERS</span><span class="st-v" data-bind="ctrl">--</span></div>
                <div class="st-row"><span class="st-l">COLLISIONS</span><span class="st-v" data-bind="coll">--</span></div>
            </div>
            <style>
                .st-row{display:flex;justify-content:space-between;padding:2px 0}
                .st-l{color:#666}.st-v{color:#00f0ff}
            </style>
        `;

        const bind = (key, val) => {
            const e = el.querySelector(`[data-bind="${key}"]`);
            if (e) e.textContent = val;
        };

        el._interval = setInterval(() => {
            const stats = window._mapActions?.getCitySimStats?.();
            if (!stats) return;
            bind('veh', stats.vehicles || 0);
            bind('speed', (stats.avgSpeedKmh || 0) + ' km/h');
            // Count by purpose would need to be in stats — for now show total
            bind('commute', '--');
            bind('delivery', '--');
            bind('taxi', '--');
            bind('patrol', '--');
            bind('nodes', stats.nodes || 0);
            bind('edges', stats.edges || 0);
            bind('ctrl', stats.trafficControllers || 0);
            bind('coll', '--');
        }, 1000);
    },
    unmount() {
        // Cleanup handled by container
    },
});
