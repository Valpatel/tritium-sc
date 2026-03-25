// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * NPCs tab for the Simulation container.
 * Shows pedestrian roles, moods, building occupancy, daily routine progress.
 * Registers itself as a tab via EventBus.
 */

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'simulation-container',
    id: 'npcs-tab',
    title: 'PEOPLE',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#05ffa1;margin-bottom:8px;font-size:12px">NPCs</div>
                <div class="sn-row"><span class="sn-l">TOTAL</span><span class="sn-v" data-bind="total">--</span></div>
                <div class="sn-row"><span class="sn-l">ACTIVE</span><span class="sn-v" data-bind="active">--</span></div>
                <div class="sn-row"><span class="sn-l">IN BUILDING</span><span class="sn-v" data-bind="inBldg">--</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px">MOOD</div>
                <div class="sn-row"><span class="sn-l" style="color:#05ffa1">CALM</span><span class="sn-v" data-bind="calm">--</span></div>
                <div class="sn-row"><span class="sn-l" style="color:#aacc44">ANXIOUS</span><span class="sn-v" data-bind="anxious">--</span></div>
                <div class="sn-row"><span class="sn-l" style="color:#ff8844">ANGRY</span><span class="sn-v" data-bind="angry">--</span></div>
                <div class="sn-row"><span class="sn-l" style="color:#fcee0a">PANICKED</span><span class="sn-v" data-bind="panicked">--</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px">BUILDINGS</div>
                <div class="sn-row"><span class="sn-l">OCCUPIED</span><span class="sn-v" data-bind="occupied">--</span></div>
                <div class="sn-row"><span class="sn-l">PEAK</span><span class="sn-v" data-bind="peak">--</span></div>
            </div>
            <style>
                .sn-row{display:flex;justify-content:space-between;padding:2px 0}
                .sn-l{color:#666}.sn-v{color:#05ffa1}
            </style>
        `;

        const bind = (key, val) => {
            const e = el.querySelector(`[data-bind="${key}"]`);
            if (e) e.textContent = val;
        };

        el._interval = setInterval(() => {
            const stats = window._mapActions?.getCitySimStats?.();
            if (!stats) return;
            bind('total', stats.pedestrians || 0);
            bind('active', stats.pedestriansActive || 0);
            bind('inBldg', stats.pedestriansInBuilding || 0);

            // Count moods (would need to be in stats — approximate)
            bind('calm', '--');
            bind('anxious', '--');
            bind('angry', '--');
            bind('panicked', '--');

            const bldg = stats.buildingOccupancy || {};
            bind('occupied', bldg.totalOccupied || 0);
            bind('peak', bldg.peakCount ? `${bldg.peakCount} in Bldg#${bldg.peakBuildingId}` : '--');
        }, 1000);
    },
});
