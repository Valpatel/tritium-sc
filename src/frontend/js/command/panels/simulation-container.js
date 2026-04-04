// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Simulation Container — unified launcher and monitor for all simulation modes.
 *
 * Modes:
 *   - CITY SIM: Living city with traffic, NPCs, daily routines, events
 *   - BATTLE: 10-wave combat exercise (was "Game")
 *   - PROTEST/RIOT: Civil unrest sub-mode of city sim (Epstein model)
 *   - CUSTOM: LLM-generated or saved scenarios
 *
 * Tab structure:
 *   MODES    — launcher for all sim types
 *   CITY SIM — controls and stats for city simulation
 *   TRAFFIC  — vehicle counts, speed, road stats
 *   NPCs     — pedestrian roles, moods, buildings
 *   EVENTS   — event director, triggers, log
 *
 * Protest/riot is NOT a separate tab — it's a sub-mode of city sim,
 * shown in the Events tab and the city sim controls when active.
 */

import { createTabbedContainer } from './tabbed-container.js';
import { CitySimPanelDef } from './city-sim.js';
import { SimEngineStatusPanelDef } from './sim-engine-status.js';

// Self-registering tab modules
import './tabs/sim-modes-tab.js';
import './tabs/sim-traffic-tab.js';
import './tabs/sim-npcs-tab.js';
import './tabs/sim-events-tab.js';

// Re-export city sim panel as a tab
function createCitySimTab(el) {
    const mockPanel = { _csimInterval: null };
    const content = CitySimPanelDef.create(mockPanel);
    if (typeof content === 'string') {
        el.innerHTML = content;
    } else if (content instanceof HTMLElement) {
        el.appendChild(content);
    }
    el._mockPanel = mockPanel;
}

// Re-export sim engine status as a tab
function createSimEngineTab(el) {
    const mockPanel = { _seTimer: null };
    const content = SimEngineStatusPanelDef.create(mockPanel);
    if (content instanceof HTMLElement) {
        el.appendChild(content);
    }
    // Mount the panel to start fetching data
    SimEngineStatusPanelDef.mount(el, mockPanel);
    el._mockPanel = mockPanel;
}

export const SimulationContainerDef = createTabbedContainer(
    'simulation-container',
    'SIMULATION',
    [
        {
            id: 'city-sim-tab',
            title: 'CITY SIM',
            create: createCitySimTab,
            unmount(el) {
                if (el._mockPanel && CitySimPanelDef.unmount) {
                    CitySimPanelDef.unmount(el._mockPanel);
                }
            },
        },
        {
            id: 'sim-engine-tab',
            title: 'ENGINE',
            create: createSimEngineTab,
            unmount(el) {
                if (el._mockPanel && SimEngineStatusPanelDef.unmount) {
                    SimEngineStatusPanelDef.unmount(el, el._mockPanel);
                }
            },
        },
    ],
    {
        category: 'simulation',
        defaultSize: { w: 340, h: 520 },
        defaultPosition: { x: 20, y: 100 },
    }
);
