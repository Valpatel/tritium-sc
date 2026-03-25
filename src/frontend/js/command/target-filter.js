// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// TargetFilter -- overlay on the tactical map that filters visible targets
// by source (BLE/Camera/Mesh/RF/All), alliance (Friendly/Hostile/Unknown/All),
// and asset type. Filters are applied client-side on WebSocket updates.
//
// Usage:
//   import { initTargetFilter, getTargetFilters, matchesFilter } from './target-filter.js';
//   initTargetFilter(document.getElementById('tactical-area'));

import { TritiumStore } from './store.js';
import { EventBus } from '/lib/events.js';

// Current filter state
const _filters = {
    source: 'all',
    alliance: 'all',
    assetType: 'all',
};

/**
 * Get the current filter state.
 * @returns {{ source: string, alliance: string, assetType: string }}
 */
export function getTargetFilters() {
    return { ..._filters };
}

/**
 * Check if a target matches the current filters.
 * @param {object} target - target object with source, alliance, type/asset_type fields
 * @returns {boolean} true if target should be visible
 */
export function matchesFilter(target) {
    if (!target) return false;

    // Source filter
    if (_filters.source !== 'all') {
        const src = (target.source || '').toLowerCase();
        if (src !== _filters.source) return false;
    }

    // Alliance filter
    if (_filters.alliance !== 'all') {
        const alliance = (target.alliance || '').toLowerCase();
        if (alliance !== _filters.alliance) return false;
    }

    // Asset type filter
    if (_filters.assetType !== 'all') {
        const type = (target.type || target.asset_type || target.unit_type || '').toLowerCase();
        if (type !== _filters.assetType) return false;
    }

    return true;
}

/**
 * Initialize the target filter overlay and mount it into the tactical area.
 * @param {HTMLElement} container - the tactical-area element
 * @returns {HTMLElement} the filter overlay element
 */
export function initTargetFilter(container) {
    if (!container) return null;

    const overlay = document.createElement('div');
    overlay.id = 'target-filter-overlay';
    overlay.className = 'target-filter-overlay';

    // Toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.className = 'target-filter-toggle';
    toggleBtn.title = 'Filter targets on map (F key)';
    toggleBtn.textContent = 'FILTER';
    toggleBtn.setAttribute('aria-expanded', 'false');

    // Dropdown panel
    const dropdown = document.createElement('div');
    dropdown.className = 'target-filter-dropdown';
    dropdown.hidden = true;

    dropdown.innerHTML = `
        <div class="tfl-header mono">TARGET FILTERS</div>
        <div class="tfl-row">
            <label class="tfl-label mono" for="tfl-source">SOURCE</label>
            <select id="tfl-source" class="tfl-select" data-filter="source">
                <option value="all">All Sources</option>
                <option value="ble">BLE</option>
                <option value="wifi">WiFi</option>
                <option value="yolo">Camera/YOLO</option>
                <option value="mesh">Mesh/LoRa</option>
                <option value="simulation">Simulation</option>
                <option value="rf">RF</option>
                <option value="manual">Manual</option>
            </select>
        </div>
        <div class="tfl-row">
            <label class="tfl-label mono" for="tfl-alliance">ALLIANCE</label>
            <select id="tfl-alliance" class="tfl-select" data-filter="alliance">
                <option value="all">All</option>
                <option value="friendly">Friendly</option>
                <option value="hostile">Hostile</option>
                <option value="neutral">Neutral</option>
                <option value="unknown">Unknown</option>
            </select>
        </div>
        <div class="tfl-row">
            <label class="tfl-label mono" for="tfl-type">ASSET TYPE</label>
            <select id="tfl-type" class="tfl-select" data-filter="assetType">
                <option value="all">All Types</option>
                <option value="person">Person</option>
                <option value="vehicle">Vehicle</option>
                <option value="drone">Drone</option>
                <option value="rover">Rover</option>
                <option value="turret">Turret</option>
                <option value="ble_device">BLE Device</option>
                <option value="mesh_radio">Mesh Radio</option>
                <option value="phone">Phone</option>
                <option value="watch">Watch</option>
                <option value="animal">Animal</option>
            </select>
        </div>
        <div class="tfl-row tfl-actions">
            <button class="tfl-reset-btn" data-action="tfl-reset">RESET</button>
            <span class="tfl-count mono" data-bind="tfl-active">0 active filters</span>
        </div>
    `;

    // Wire toggle
    toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const wasHidden = dropdown.hidden;
        dropdown.hidden = !wasHidden;
        toggleBtn.setAttribute('aria-expanded', String(!wasHidden));
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
        if (!overlay.contains(e.target)) {
            dropdown.hidden = true;
            toggleBtn.setAttribute('aria-expanded', 'false');
        }
    });

    // Wire selects
    dropdown.querySelectorAll('.tfl-select').forEach(sel => {
        sel.addEventListener('change', () => {
            const key = sel.dataset.filter;
            _filters[key] = sel.value;
            _updateActiveCount(dropdown);
            _updateToggleIndicator(toggleBtn);
            EventBus.emit('target-filter:changed', getTargetFilters());
        });
    });

    // Wire reset
    dropdown.querySelector('[data-action="tfl-reset"]').addEventListener('click', () => {
        _filters.source = 'all';
        _filters.alliance = 'all';
        _filters.assetType = 'all';
        dropdown.querySelectorAll('.tfl-select').forEach(sel => {
            sel.value = 'all';
        });
        _updateActiveCount(dropdown);
        _updateToggleIndicator(toggleBtn);
        EventBus.emit('target-filter:changed', getTargetFilters());
    });

    overlay.appendChild(toggleBtn);
    overlay.appendChild(dropdown);
    container.appendChild(overlay);

    // Listen for filter changes from the Layers panel
    EventBus.on('target-filter:set', (data) => {
        if (data.source !== undefined) _filters.source = data.source;
        if (data.alliance !== undefined) _filters.alliance = data.alliance;
        if (data.assetType !== undefined) _filters.assetType = data.assetType;
        // Sync the dropdowns in the target filter overlay
        dropdown.querySelectorAll('.tfl-select').forEach(sel => {
            const key = sel.dataset.filter;
            if (key && _filters[key]) sel.value = _filters[key];
        });
        _updateActiveCount(dropdown);
        _updateToggleIndicator(toggleBtn);
        EventBus.emit('target-filter:changed', getTargetFilters());
    });

    return overlay;
}

function _updateActiveCount(dropdown) {
    const count = (
        (_filters.source !== 'all' ? 1 : 0) +
        (_filters.alliance !== 'all' ? 1 : 0) +
        (_filters.assetType !== 'all' ? 1 : 0)
    );
    const el = dropdown.querySelector('[data-bind="tfl-active"]');
    if (el) {
        el.textContent = count === 0 ? 'no active filters' : `${count} active filter${count > 1 ? 's' : ''}`;
    }
}

function _updateToggleIndicator(btn) {
    const active = _filters.source !== 'all' || _filters.alliance !== 'all' || _filters.assetType !== 'all';
    btn.classList.toggle('tfl-active', active);
    btn.textContent = active ? 'FILTER *' : 'FILTER';
}
