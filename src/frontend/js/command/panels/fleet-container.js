// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * FLEET Container — tabbed panel for fleet management — devices, assets, edge diagnostics.
 * Addon/plugin tabs register via EventBus.emit('panel:register-tab', { container: 'fleet-container', ... })
 */

import { createTabbedContainer } from './tabbed-container.js';

export const FleetContainerDef = createTabbedContainer(
    'fleet-container',
    'FLEET',
    [
        {
            id: 'fleet-container-overview',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = '<div style="padding:8px;font-family:monospace;font-size:11px;color:#ccc">'
                    + '<div style="color:#ff8844;font-size:12px;margin-bottom:8px">FLEET</div>'
                    + '<p style="color:#555;font-size:10px">Fleet management — devices, assets, edge diagnostics</p>'
                    + '<p style="color:#333;font-size:9px;margin-top:12px">Plugin tabs appear here when loaded.</p>'
                    + '</div>';
            },
        },
    ],
    {
        category: 'fleet',
        defaultSize: { w: 320, h: 450 },
        defaultPosition: { x: 40, y: 100 },
    }
);
