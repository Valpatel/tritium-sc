// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * WiFi CSI tab for the Sensing container.
 * Displays human presence detection via WiFi Channel State Information.
 * Self-registers into sensors-container via EventBus.
 *
 * Based on: https://github.com/ruvnet/RuView
 * Edge: tritium-edge hal_wifi_csi (future)
 * Backend: plugins/wifi_csi/
 */

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'sensors-container',
    id: 'wifi-csi-tab',
    title: 'WIFI CSI',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#00f0ff;margin-bottom:8px;font-size:12px">WIFI CSI — HUMAN DETECTION</div>
                <p style="color:#555;font-size:10px;margin-bottom:10px">
                    Through-wall human presence detection via WiFi Channel State Information.<br>
                    No cameras needed — works through concrete, wood, and drywall.
                </p>
                <div class="wc-row"><span class="wc-l">STATUS</span><span class="wc-v" data-bind="status" style="color:#666">NOT CONFIGURED</span></div>
                <div class="wc-row"><span class="wc-l">MODE</span><span class="wc-v" data-bind="mode">RSSI</span></div>
                <div class="wc-row"><span class="wc-l">DETECTIONS</span><span class="wc-v" data-bind="detections">0</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px;font-size:10px">DETECTION MODES</div>
                <div style="color:#444;font-size:9px;line-height:1.6">
                    <div><span style="color:#05ffa1">Phase 1 — RSSI Occupancy:</span> Detect presence via signal variance. Works with existing WiFi APs.</div>
                    <div><span style="color:#fcee0a">Phase 2 — CSI Pose:</span> 17-point skeletal tracking. Requires Intel 5300 or similar CSI-capable NIC.</div>
                    <div><span style="color:#ff2a6d">Phase 3 — CSI Vitals:</span> Breathing rate + heart rate via FFT. Research hardware required.</div>
                </div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px;font-size:10px">RECENT DETECTIONS</div>
                <div class="wc-feed" data-bind="feed" style="max-height:120px;overflow-y:auto;font-size:10px;color:#444">No detections yet</div>
            </div>
            <style>
                .wc-row{display:flex;justify-content:space-between;padding:2px 0}
                .wc-l{color:#666}.wc-v{color:#00f0ff}
            </style>
        `;

        const bind = (key, val) => {
            const e = el.querySelector(`[data-bind="${key}"]`);
            if (e) e.textContent = val;
        };

        el._interval = setInterval(() => {
            fetch('/api/wifi-csi/status')
                .then(r => r.json())
                .then(d => {
                    bind('status', d.healthy ? 'ACTIVE' : 'STANDBY');
                    bind('mode', (d.mode || 'rssi').toUpperCase());
                    bind('detections', d.detections || 0);
                    const statusEl = el.querySelector('[data-bind="status"]');
                    if (statusEl) statusEl.style.color = d.healthy ? '#05ffa1' : '#666';
                })
                .catch(() => {
                    bind('status', 'UNAVAILABLE');
                });
        }, 3000);
    },
});
