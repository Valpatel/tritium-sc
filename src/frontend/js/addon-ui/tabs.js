// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// AddonTabs -- shared tabbed interface component for addon panels.
// Renders a horizontal tab bar with cyberpunk styling.

/**
 * Tabbed interface component for addon panels.
 *
 * Usage:
 *   const tabs = new AddonTabs(container, [
 *       { id: 'radio', label: 'RADIO' },
 *       { id: 'spectrum', label: 'SPECTRUM' },
 *   ]);
 *   tabs.onSwitch(tabId => console.log('Switched to', tabId));
 */
class AddonTabs {
    /**
     * @param {HTMLElement} container - DOM element to render into
     * @param {Array<{id: string, label: string}>} tabs - Tab definitions
     * @param {Object} [options]
     * @param {string} [options.activeTab] - Initial active tab ID (defaults to first)
     */
    constructor(container, tabs = [], options = {}) {
        this.container = container;
        this._tabs = [];
        this._activeTab = null;
        this._callbacks = [];
        this._root = null;
        this._tabEls = {};

        // Add initial tabs
        for (const tab of tabs) {
            this._tabs.push({ id: tab.id, label: tab.label });
        }

        this.render();

        // Set initial active tab
        const initial = options.activeTab || (this._tabs.length > 0 ? this._tabs[0].id : null);
        if (initial) {
            this.switchTo(initial);
        }
    }

    /**
     * Add a tab dynamically.
     * @param {string} id
     * @param {string} label
     */
    addTab(id, label) {
        if (this._tabs.some(t => t.id === id)) return;
        this._tabs.push({ id, label });
        this.render();
        if (!this._activeTab && this._tabs.length === 1) {
            this.switchTo(id);
        }
    }

    /**
     * Switch to a tab by ID.
     * @param {string} tabId
     */
    switchTo(tabId) {
        if (!this._tabs.some(t => t.id === tabId)) return;
        const prev = this._activeTab;
        this._activeTab = tabId;

        // Update visual state
        for (const [id, el] of Object.entries(this._tabEls)) {
            if (id === tabId) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        }

        // Fire callbacks
        if (prev !== tabId) {
            for (const cb of this._callbacks) {
                try { cb(tabId, prev); } catch (_) { /* ignore */ }
            }
        }
    }

    /**
     * Get the active tab ID.
     * @returns {string|null}
     */
    getActiveTab() {
        return this._activeTab;
    }

    /**
     * Register a callback for tab switches.
     * @param {Function} callback - (newTabId, prevTabId) => void
     */
    onSwitch(callback) {
        if (typeof callback === 'function') {
            this._callbacks.push(callback);
        }
    }

    /**
     * Re-render the tab bar.
     */
    render() {
        // Clear container
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const root = document.createElement('div');
        root.classList.add('addon-tabs');
        this._tabEls = {};

        for (const tab of this._tabs) {
            const el = document.createElement('button');
            el.classList.add('addon-tab');
            if (tab.id === this._activeTab) {
                el.classList.add('active');
            }
            el.textContent = tab.label;
            el.setAttribute('data-tab-id', tab.id);
            el.addEventListener('click', () => this.switchTo(tab.id));
            this._tabEls[tab.id] = el;
            root.appendChild(el);
        }

        this._root = root;
        this.container.appendChild(root);
    }

    /**
     * Remove all DOM elements.
     */
    destroy() {
        if (this._root && this._root.parentNode) {
            this._root.parentNode.removeChild(this._root);
        }
        this._root = null;
        this._tabEls = {};
        this._callbacks = [];
    }
}

export { AddonTabs };
