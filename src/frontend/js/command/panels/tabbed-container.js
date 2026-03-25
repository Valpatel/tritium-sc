// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * TabbedContainer — a panel that holds multiple sub-panels as tabs.
 *
 * Instead of each feature getting its own floating window, features
 * contribute tabs to a container. The Windows dropdown shows containers,
 * not individual panels. Plugins/addons register tabs via EventBus.
 *
 * Usage:
 *   const container = createTabbedContainer('simulation', 'SIMULATION', [
 *       { id: 'city-sim', title: 'CITY SIM', create: (el) => { ... } },
 *       { id: 'game', title: 'GAME', create: (el) => { ... } },
 *   ]);
 *   panelManager.register(container);
 *
 * Addons add tabs dynamically:
 *   EventBus.emit('panel:register-tab', {
 *       container: 'simulation',
 *       id: 'my-addon-tab',
 *       title: 'MY ADDON',
 *       create: (el) => { el.innerHTML = '<p>Hello from addon</p>'; },
 *   });
 */

import { EventBus } from '/lib/events.js';

// Registry of tab definitions per container
const _tabRegistry = new Map(); // containerId → Map<tabId, tabDef>
const _containerInstances = new Map(); // containerId → { el, activeTab }

/**
 * Register a tab for a container. Can be called before or after the container is created.
 */
export function registerTab(containerId, tabDef) {
    if (!_tabRegistry.has(containerId)) _tabRegistry.set(containerId, new Map());
    _tabRegistry.get(containerId).set(tabDef.id, tabDef);

    // If container already exists, hot-add the tab
    const instance = _containerInstances.get(containerId);
    if (instance) {
        _addTabToDOM(instance, tabDef);
    }
}

/**
 * Create a panel definition for a tabbed container.
 * Returns a PanelDef compatible with PanelManager.register().
 *
 * @param {string} containerId — unique container ID (e.g., 'simulation')
 * @param {string} title — display title (e.g., 'SIMULATION')
 * @param {Array<{id, title, create, unmount?}>} initialTabs — built-in tabs
 * @param {Object} [options] — { defaultSize, defaultPosition }
 */
export function createTabbedContainer(containerId, title, initialTabs = [], options = {}) {
    // Pre-register initial tabs
    for (const tab of initialTabs) {
        registerTab(containerId, tab);
    }

    return {
        id: containerId,
        title,
        category: options.category || 'simulation',
        defaultPosition: options.defaultPosition || { x: 20, y: 100 },
        defaultSize: options.defaultSize || { w: 320, h: 480 },

        create(panel) {
            const el = document.createElement('div');
            el.className = 'tabbed-container';

            // Tab bar
            const tabBar = document.createElement('div');
            tabBar.className = 'tc-tab-bar';
            el.appendChild(tabBar);

            // Content area
            const content = document.createElement('div');
            content.className = 'tc-content';
            el.appendChild(content);

            // Style
            const style = document.createElement('style');
            style.textContent = `
                .tabbed-container { display: flex; flex-direction: column; height: 100%; }
                .tc-tab-bar {
                    display: flex; gap: 0; flex-shrink: 0; overflow-x: auto;
                    background: #0a0a12; border-bottom: 1px solid #1a1a2e;
                    scrollbar-width: none;
                }
                .tc-tab-bar::-webkit-scrollbar { display: none; }
                .tc-tab {
                    padding: 5px 12px; font-family: 'JetBrains Mono', monospace;
                    font-size: 10px; color: #666; cursor: pointer;
                    border-bottom: 2px solid transparent;
                    white-space: nowrap; user-select: none;
                    transition: color 0.15s, border-color 0.15s;
                }
                .tc-tab:hover { color: #888; }
                .tc-tab.active { color: #00f0ff; border-bottom-color: #00f0ff; }
                .tc-tab.addon { color: #888; font-style: italic; }
                .tc-tab.addon.active { color: #05ffa1; border-bottom-color: #05ffa1; }
                .tc-content {
                    flex: 1; overflow-y: auto; overflow-x: hidden;
                    min-height: 0;
                }
                .tc-tab-content { display: none; height: 100%; }
                .tc-tab-content.active { display: block; }
            `;
            el.appendChild(style);

            // Store instance
            const instance = { el, tabBar, content, activeTab: null, tabEls: new Map(), contentEls: new Map() };
            _containerInstances.set(containerId, instance);

            // Build tabs from registry
            const tabs = _tabRegistry.get(containerId);
            if (tabs) {
                for (const [, tabDef] of tabs) {
                    _addTabToDOM(instance, tabDef);
                }
            }

            // Activate first tab
            if (tabs && tabs.size > 0) {
                const firstId = tabs.keys().next().value;
                _activateTab(instance, firstId);
            }

            // Listen for dynamic tab registration
            panel._tabUnsub = EventBus.on('panel:register-tab', (data) => {
                if (data.container === containerId) {
                    registerTab(containerId, data);
                }
            });

            return el;
        },

        unmount(bodyEl) {
            // Unmount all active tab content, passing content element to each tab's unmount
            const instance = _containerInstances.get(containerId);
            if (instance) {
                const tabs = _tabRegistry.get(containerId);
                if (tabs) {
                    for (const [tabId, tabDef] of tabs) {
                        if (tabDef.unmount) {
                            const contentEl = instance.contentEls?.get(tabId);
                            tabDef.unmount(contentEl || bodyEl);
                        }
                    }
                }
            }
            _containerInstances.delete(containerId);
        },
    };
}

function _addTabToDOM(instance, tabDef) {
    if (instance.tabEls.has(tabDef.id)) return; // already added

    // Tab button
    const tabEl = document.createElement('div');
    tabEl.className = `tc-tab${tabDef.addon ? ' addon' : ''}`;
    tabEl.textContent = tabDef.title;
    tabEl.dataset.tabId = tabDef.id;
    tabEl.addEventListener('click', () => _activateTab(instance, tabDef.id));
    instance.tabBar.appendChild(tabEl);
    instance.tabEls.set(tabDef.id, tabEl);

    // Content area (lazy — created on first activation)
    const contentEl = document.createElement('div');
    contentEl.className = 'tc-tab-content';
    contentEl.dataset.tabId = tabDef.id;
    instance.content.appendChild(contentEl);
    instance.contentEls.set(tabDef.id, contentEl);
}

function _activateTab(instance, tabId) {
    if (instance.activeTab === tabId) return;

    // Deactivate current
    if (instance.activeTab) {
        instance.tabEls.get(instance.activeTab)?.classList.remove('active');
        instance.contentEls.get(instance.activeTab)?.classList.remove('active');
    }

    // Activate new
    const tabEl = instance.tabEls.get(tabId);
    const contentEl = instance.contentEls.get(tabId);
    if (!tabEl || !contentEl) return;

    tabEl.classList.add('active');
    contentEl.classList.add('active');
    instance.activeTab = tabId;

    // Lazy create content on first activation
    if (!contentEl._created) {
        const tabs = _tabRegistry.get(Array.from(_containerInstances.entries()).find(([, v]) => v === instance)?.[0]);
        const tabDef = tabs?.get(tabId);
        if (tabDef?.create) {
            tabDef.create(contentEl);
            contentEl._created = true;
        }
    }
}

// Global listener for addon tab registration
EventBus.on('panel:register-tab', (data) => {
    if (data.container && data.id && data.title) {
        registerTab(data.container, { ...data, addon: true });
    }
});
