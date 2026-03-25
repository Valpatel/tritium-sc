// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * OPERATIONS Container — tabbed panel for operations: units, fleet, alerts, missions, patrol, devices.
 * Merges former "Tactical" and "Fleet" categories — operators think in terms of deployments, not categories.
 * Addon/plugin tabs register via EventBus.emit('panel:register-tab', { container: 'tactical-container', ... })
 */

import { createTabbedContainer } from './tabbed-container.js';

export const TacticalContainerDef = createTabbedContainer(
    'tactical-container',
    'OPERATIONS',
    [
        {
            id: 'tactical-container-overview',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = '<div style="padding:8px;font-family:monospace;font-size:11px;color:#ccc">'
                    + '<div style="color:#00f0ff;font-size:12px;margin-bottom:8px">OPERATIONS</div>'
                    + '<p style="color:#555;font-size:10px">Units, fleet, alerts, missions, patrol, zones, devices — everything deployed and active.</p>'
                    + '<p style="color:#333;font-size:9px;margin-top:12px">Plugin tabs appear here when loaded.</p>'
                    + '</div>';
            },
        },
    ],
    {
        category: 'operations',
        defaultSize: { w: 340, h: 500 },
        defaultPosition: { x: 20, y: 80 },
    }
);
