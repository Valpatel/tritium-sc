// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Sensors Container — tabbed panel for all sensor feeds and monitoring.
 *
 * Built-in tabs: Edge Tracker, Cameras, Sensor Health
 * Addon tabs: Meshtastic, SDR, Radar, WiFi, Acoustic, LPR
 * (addon tabs self-register via EventBus when their plugins load)
 */

import { createTabbedContainer } from './tabbed-container.js';

// Self-registering sensor tabs
import './tabs/sensing-wifi-csi-tab.js';

export const SensorsContainerDef = createTabbedContainer(
    'sensors-container',
    'SENSORS',
    [
        {
            id: 'sensor-overview-tab',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = `
                    <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                        <div style="color:#00f0ff;margin-bottom:8px;font-size:12px">SENSOR OVERVIEW</div>
                        <p style="color:#666;font-size:10px">
                            Sensor-specific tabs appear here when plugins load.<br>
                            Each sensor addon contributes its own tab.
                        </p>
                        <div style="margin-top:12px;color:#888">
                            <div style="margin-bottom:4px">Available sensors:</div>
                            <div id="so-sensor-list" style="color:#444;font-size:10px">Loading...</div>
                        </div>
                    </div>
                `;
                // List loaded sensor plugins
                fetch('/api/plugins').then(r => r.json()).then(plugins => {
                    const sensorPlugins = (plugins || []).filter(p =>
                        p.capabilities?.includes('data_source') || p.name?.toLowerCase().includes('sensor')
                    );
                    const listEl = el.querySelector('#so-sensor-list');
                    if (listEl) {
                        listEl.innerHTML = sensorPlugins.length > 0
                            ? sensorPlugins.map(p => `<div style="color:#05ffa1">&#8226; ${p.name} (${p.healthy ? 'healthy' : 'offline'})</div>`).join('')
                            : '<div style="color:#444">No sensor plugins loaded</div>';
                    }
                }).catch(() => {});
            },
        },
    ],
    {
        category: 'sensors',
        defaultSize: { w: 340, h: 450 },
        defaultPosition: { x: 40, y: 120 },
    }
);
