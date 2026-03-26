// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Quick Start Panel
// Appears on first load to orient new users. Explains what Tritium is,
// shows how to enable demo mode, and links to key panels.

import { EventBus } from '/lib/events.js';

const QUICK_START_DISMISSED_KEY = 'tritium.quickstart.dismissed';

export const QuickStartPanelDef = {
    id: 'quick-start',
    title: 'QUICK START',
    defaultPosition: { x: 200, y: 100 },
    defaultSize: { w: 400, h: 480 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'quick-start-panel-inner';
        el.innerHTML = `
            <div class="qs-hero">
                <div class="qs-title">TRITIUM</div>
                <div class="qs-subtitle">Unified Operating Picture for Robotics &amp; Security</div>
            </div>
            <div class="qs-body">
                <div class="qs-section">
                    <div class="qs-section-title">WHAT IS THIS?</div>
                    <p class="qs-text">
                        Tritium tracks and identifies every target -- phones, vehicles, people, animals --
                        using BLE, WiFi, cameras, LoRa mesh, and more. All detections fuse into a single
                        tactical map with unique target IDs.
                    </p>
                </div>
                <div class="qs-section">
                    <div class="qs-section-title">GET STARTED</div>
                    <div class="qs-step">
                        <span class="qs-step-num">1</span>
                        <div class="qs-step-text">
                            <strong>Enable Demo Mode</strong> to see synthetic data flowing through the system.
                            <button class="panel-action-btn panel-action-btn-primary qs-demo-btn" data-action="start-demo">START DEMO</button>
                        </div>
                    </div>
                    <div class="qs-step">
                        <span class="qs-step-num">2</span>
                        <div class="qs-step-text">
                            <strong>Open panels</strong> from the menu bar to explore different views.
                        </div>
                    </div>
                    <div class="qs-step">
                        <span class="qs-step-num">3</span>
                        <div class="qs-step-text">
                            <strong>Toggle map layers</strong> using the Layers panel (satellite, buildings, targets).
                        </div>
                    </div>
                </div>
                <div class="qs-section">
                    <div class="qs-section-title">KEY PANELS</div>
                    <div class="qs-panel-links">
                        <button class="qs-link-btn" data-open-panel="edge-tracker">Edge Tracker</button>
                        <button class="qs-link-btn" data-open-panel="layers">Layers</button>
                        <button class="qs-link-btn" data-open-panel="fleet-dashboard">Fleet</button>
                        <button class="qs-link-btn" data-open-panel="system-health-dashboard">System Health</button>
                        <button class="qs-link-btn" data-open-panel="camera-feeds">Camera Feeds</button>
                        <button class="qs-link-btn" data-open-panel="amy">Amy (AI)</button>
                        <button class="qs-link-btn" data-open-panel="search">Target Search</button>
                        <button class="qs-link-btn" data-open-panel="dossiers">Dossiers</button>
                    </div>
                </div>
                <div class="qs-section">
                    <div class="qs-section-title">KEYBOARD</div>
                    <p class="qs-text">
                        Press <kbd>?</kbd> for keyboard shortcuts. <kbd>B</kbd> starts a battle.
                        <kbd>O</kbd>/<kbd>T</kbd>/<kbd>S</kbd> switch map modes.
                    </p>
                </div>
            </div>
            <div class="qs-footer">
                <label class="qs-dismiss-label">
                    <input type="checkbox" data-action="dismiss-forever" />
                    Don't show on startup
                </label>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Demo mode button
        bodyEl.querySelector('[data-action="start-demo"]')?.addEventListener('click', async () => {
            try {
                const resp = await fetch('/api/demo/start', { method: 'POST' });
                if (resp.ok) {
                    EventBus.emit('toast:show', { message: 'Demo mode started', type: 'info' });
                } else {
                    EventBus.emit('toast:show', { message: 'Failed to start demo', type: 'alert' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Demo start error', type: 'alert' });
            }
        });

        // Panel link buttons
        bodyEl.querySelectorAll('[data-open-panel]').forEach(btn => {
            btn.addEventListener('click', () => {
                const panelId = btn.dataset.openPanel;
                EventBus.emit('panel:request-open', { id: panelId });
            });
        });

        // Dismiss forever checkbox
        const dismissCheckbox = bodyEl.querySelector('[data-action="dismiss-forever"]');
        if (dismissCheckbox) {
            dismissCheckbox.checked = localStorage.getItem(QUICK_START_DISMISSED_KEY) === 'true';
            dismissCheckbox.addEventListener('change', () => {
                localStorage.setItem(QUICK_START_DISMISSED_KEY, dismissCheckbox.checked ? 'true' : 'false');
            });
        }
    },

    // Called by panel manager to check if panel should auto-open
    shouldAutoOpen() {
        return localStorage.getItem(QUICK_START_DISMISSED_KEY) !== 'true';
    },
};
