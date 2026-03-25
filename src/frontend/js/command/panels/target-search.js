// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Target Search Panel
// Search and filter tracked targets by name, MAC, source, alliance.
// Uses /api/targets/search, /api/targets/filter, /api/targets/stats endpoints.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

export const TargetSearchPanelDef = {
    id: 'target-search',
    title: 'TGT SEARCH',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 380, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'target-search-panel-inner';
        el.innerHTML = `
            <div class="ts-search-bar">
                <input type="text" class="ts-search-input" data-bind="ts-query"
                       placeholder="Search name, MAC, ID..." aria-label="Target search" spellcheck="false">
                <button class="panel-action-btn panel-action-btn-primary" data-action="ts-search">SEARCH</button>
            </div>
            <div class="ts-filters">
                <select class="ts-filter-select" data-bind="ts-source" aria-label="Source filter">
                    <option value="">All Sources</option>
                    <option value="simulation">Simulation</option>
                    <option value="yolo">YOLO</option>
                    <option value="ble">BLE</option>
                    <option value="manual">Manual</option>
                </select>
                <select class="ts-filter-select" data-bind="ts-alliance" aria-label="Alliance filter">
                    <option value="">All Alliances</option>
                    <option value="friendly">Friendly</option>
                    <option value="hostile">Hostile</option>
                    <option value="unknown">Unknown</option>
                </select>
                <select class="ts-filter-select" data-bind="ts-asset-type" aria-label="Asset type filter">
                    <option value="">All Types</option>
                    <option value="person">Person</option>
                    <option value="vehicle">Vehicle</option>
                    <option value="rover">Rover</option>
                    <option value="drone">Drone</option>
                    <option value="turret">Turret</option>
                    <option value="ble_device">BLE Device</option>
                </select>
            </div>
            <div class="ts-stats-row" data-bind="ts-stats">
                <span class="ts-badge ts-badge-total" title="Total targets">-- TOTAL</span>
                <span class="ts-badge ts-badge-friendly" title="Friendly">-- FRI</span>
                <span class="ts-badge ts-badge-hostile" title="Hostile">-- HOS</span>
                <span class="ts-badge ts-badge-unknown" title="Unknown">-- UNK</span>
                <span class="ts-badge ts-badge-active" title="Active last 5min">-- 5m</span>
            </div>
            <ul class="panel-list ts-results" data-bind="ts-results" role="listbox" aria-label="Target search results">
                <li class="panel-empty">Enter a search query or apply filters</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const queryInput = bodyEl.querySelector('[data-bind="ts-query"]');
        const searchBtn = bodyEl.querySelector('[data-action="ts-search"]');
        const sourceSelect = bodyEl.querySelector('[data-bind="ts-source"]');
        const allianceSelect = bodyEl.querySelector('[data-bind="ts-alliance"]');
        const assetTypeSelect = bodyEl.querySelector('[data-bind="ts-asset-type"]');
        const statsRow = bodyEl.querySelector('[data-bind="ts-stats"]');
        const resultsList = bodyEl.querySelector('[data-bind="ts-results"]');

        let typeaheadTimer = null;

        function allianceDot(alliance) {
            switch (alliance) {
                case 'friendly': return 'panel-dot-green';
                case 'hostile': return 'panel-dot-hostile';
                case 'unknown': return 'panel-dot-amber';
                default: return 'panel-dot-neutral';
            }
        }

        function renderResults(targets) {
            if (!resultsList) return;
            if (!targets || targets.length === 0) {
                resultsList.innerHTML = '<li class="panel-empty">No targets found</li>';
                return;
            }

            resultsList.innerHTML = targets.map(t => {
                const tid = _esc(t.target_id || '');
                const name = _esc(t.name || tid.substring(0, 12));
                const alliance = t.alliance || 'unknown';
                const atype = _esc(t.asset_type || '');
                const src = _esc(t.source || '');
                const dotClass = allianceDot(alliance);

                return `<li class="panel-list-item ts-result-item" data-target-id="${tid}" role="option">
                    <span class="panel-dot ${dotClass}"></span>
                    <div class="ts-item-info">
                        <span class="ts-item-name">${name}</span>
                        <span class="ts-item-meta mono">${atype} | ${src} | ${_esc(alliance)}</span>
                    </div>
                    <button class="panel-btn ts-center-btn" data-action="center" data-target-id="${tid}" title="Center on map">+</button>
                </li>`;
            }).join('');

            // Click handlers
            resultsList.querySelectorAll('.ts-result-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action="center"]')) return;
                    const targetId = el.dataset.targetId;
                    EventBus.emit('target:select', { target_id: targetId });
                });
            });

            resultsList.querySelectorAll('[data-action="center"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const targetId = btn.dataset.targetId;
                    const target = targets.find(t => t.target_id === targetId);
                    if (target) {
                        EventBus.emit('map:center', {
                            x: target.position?.x ?? 0,
                            y: target.position?.y ?? 0,
                            target_id: targetId,
                        });
                        EventBus.emit('target:select', { target_id: targetId });
                    }
                });
            });
        }

        async function doSearch() {
            const query = queryInput?.value?.trim();
            if (!query) {
                doFilter();
                return;
            }

            if (resultsList) resultsList.innerHTML = '<li class="panel-empty"><span class="panel-spinner"></span> Searching...</li>';

            try {
                const resp = await fetch(`/api/targets/search?q=${encodeURIComponent(query)}`);
                if (!resp.ok) {
                    renderResults([]);
                    return;
                }
                const data = await resp.json();
                renderResults(data.results || []);
            } catch (_) {
                renderResults([]);
            }
        }

        async function doFilter() {
            const source = sourceSelect?.value || '';
            const alliance = allianceSelect?.value || '';
            const assetType = assetTypeSelect?.value || '';

            const params = new URLSearchParams();
            if (source) params.set('source', source);
            if (alliance) params.set('alliance', alliance);
            if (assetType) params.set('asset_type', assetType);

            if (resultsList) resultsList.innerHTML = '<li class="panel-empty"><span class="panel-spinner"></span> Loading...</li>';

            try {
                const resp = await fetch(`/api/targets/filter?${params}`);
                if (!resp.ok) {
                    renderResults([]);
                    return;
                }
                const data = await resp.json();
                renderResults(data.targets || []);
            } catch (_) {
                renderResults([]);
            }
        }

        async function fetchStats() {
            if (!statsRow) return;
            try {
                const resp = await fetch('/api/targets/stats');
                if (!resp.ok) return;
                const data = await resp.json();
                const byAlliance = data.by_alliance || {};
                statsRow.innerHTML = `
                    <span class="ts-badge ts-badge-total" title="Total targets">${data.total || 0} TOTAL</span>
                    <span class="ts-badge ts-badge-friendly" title="Friendly">${byAlliance.friendly || 0} FRI</span>
                    <span class="ts-badge ts-badge-hostile" title="Hostile">${byAlliance.hostile || 0} HOS</span>
                    <span class="ts-badge ts-badge-unknown" title="Unknown">${byAlliance.unknown || 0} UNK</span>
                    <span class="ts-badge ts-badge-active" title="Active last 5min">${data.active_5min || 0} 5m</span>
                `;
            } catch (_) {
                // stats unavailable, keep existing
            }
        }

        // Wire events
        if (searchBtn) searchBtn.addEventListener('click', doSearch);
        if (queryInput) {
            queryInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    doSearch();
                }
                e.stopPropagation(); // prevent panel shortcuts
            });
            // Type-ahead: debounced search as user types
            queryInput.addEventListener('input', () => {
                clearTimeout(typeaheadTimer);
                typeaheadTimer = setTimeout(() => {
                    const val = queryInput.value.trim();
                    if (val.length >= 2) {
                        doSearch();
                    } else if (val.length === 0) {
                        doFilter();
                    }
                }, 300);
            });
        }

        // Filter dropdowns trigger filter on change
        [sourceSelect, allianceSelect, assetTypeSelect].forEach(sel => {
            if (sel) sel.addEventListener('change', () => {
                const query = queryInput?.value?.trim();
                if (query) {
                    doSearch();
                } else {
                    doFilter();
                }
            });
        });

        // Initial load
        fetchStats();
        doFilter();

        // Auto-refresh stats every 15s
        const statsInterval = setInterval(fetchStats, 15000);
        panel._unsubs.push(() => clearInterval(statsInterval));
        panel._unsubs.push(() => clearTimeout(typeaheadTimer));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};

// ---------------------------------------------------------------------------
// Inject panel-specific styles
// ---------------------------------------------------------------------------
const style = document.createElement('style');
style.textContent = `
.target-search-panel-inner {
    display: flex;
    flex-direction: column;
    height: 100%;
    gap: 6px;
    padding: 6px;
}

.ts-search-bar {
    display: flex;
    gap: 4px;
}

.ts-search-input {
    flex: 1;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.3);
    color: #e0e0e0;
    padding: 4px 8px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.7rem;
    border-radius: 2px;
    outline: none;
}

.ts-search-input:focus {
    border-color: #00f0ff;
    box-shadow: 0 0 4px rgba(0, 240, 255, 0.3);
}

.ts-filters {
    display: flex;
    gap: 4px;
}

.ts-filter-select {
    flex: 1;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 3px 4px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.6rem;
    border-radius: 2px;
    cursor: pointer;
}

.ts-filter-select:focus {
    border-color: #00f0ff;
}

.ts-stats-row {
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
}

.ts-badge {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.55rem;
    padding: 2px 6px;
    border-radius: 2px;
    white-space: nowrap;
}

.ts-badge-total {
    background: rgba(0, 240, 255, 0.15);
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.3);
}

.ts-badge-friendly {
    background: rgba(5, 255, 161, 0.15);
    color: #05ffa1;
    border: 1px solid rgba(5, 255, 161, 0.3);
}

.ts-badge-hostile {
    background: rgba(255, 42, 109, 0.15);
    color: #ff2a6d;
    border: 1px solid rgba(255, 42, 109, 0.3);
}

.ts-badge-unknown {
    background: rgba(252, 238, 10, 0.15);
    color: #fcee0a;
    border: 1px solid rgba(252, 238, 10, 0.3);
}

.ts-badge-active {
    background: rgba(0, 240, 255, 0.1);
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.2);
}

.ts-results {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
}

.ts-result-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    cursor: pointer;
    border-bottom: 1px solid rgba(0, 240, 255, 0.08);
    transition: background 0.15s;
}

.ts-result-item:hover {
    background: rgba(0, 240, 255, 0.08);
}

.ts-item-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
}

.ts-item-name {
    font-size: 0.7rem;
    color: #e0e0e0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.ts-item-meta {
    font-size: 0.55rem;
    color: rgba(224, 224, 224, 0.5);
}

.ts-center-btn {
    font-size: 0.6rem;
    padding: 2px 6px;
    color: #00f0ff;
    border: 1px solid rgba(0, 240, 255, 0.3);
    background: transparent;
    cursor: pointer;
    border-radius: 2px;
}

.ts-center-btn:hover {
    background: rgba(0, 240, 255, 0.15);
}
`;
document.head.appendChild(style);
