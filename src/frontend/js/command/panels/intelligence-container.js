// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Intelligence Container — tabbed panel for all analysis and investigation tools.
 *
 * Built-in tabs: Search, Dossiers, Timeline
 * Addon tabs: Graph Explorer, Behavioral Intelligence, Fusion, Reid
 */

import { createTabbedContainer } from './tabbed-container.js';

export const IntelligenceContainerDef = createTabbedContainer(
    'intelligence-container',
    'INTEL',
    [
        {
            id: 'intel-overview-tab',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = `
                    <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                        <div style="color:#ff2a6d;margin-bottom:8px;font-size:12px">INTEL</div>
                        <p style="color:#666;font-size:10px">
                            Target analysis, investigation, and pattern detection.<br>
                            Dossiers, signal histories, behavioral analysis, correlation.
                        </p>
                    </div>
                `;
            },
        },
    ],
    {
        category: 'intel',
        defaultSize: { w: 380, h: 500 },
        defaultPosition: { x: 60, y: 100 },
    }
);
