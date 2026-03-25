// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * SYSTEM Container — tabbed panel for system health, deployment, configuration, testing.
 * Addon/plugin tabs register via EventBus.emit('panel:register-tab', { container: 'system-container', ... })
 */

import { createTabbedContainer } from './tabbed-container.js';

export const SystemContainerDef = createTabbedContainer(
    'system-container',
    'SYSTEM',
    [
        {
            id: 'system-container-overview',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = '<div style="padding:8px;font-family:monospace;font-size:11px;color:#ccc">'
                    + '<div style="color:#888888;font-size:12px;margin-bottom:8px">SYSTEM</div>'
                    + '<p style="color:#555;font-size:10px">System health, deployment, configuration, testing</p>'
                    + '<p style="color:#333;font-size:9px;margin-top:12px">Plugin tabs appear here when loaded.</p>'
                    + '</div>';
            },
        },
    ],
    {
        category: 'system',
        defaultSize: { w: 320, h: 450 },
        defaultPosition: { x: 50, y: 110 },
    }
);
