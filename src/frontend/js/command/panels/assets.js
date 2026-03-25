// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Asset Placement Panel
// Manage real-world assets (cameras, sensors, mesh radios, gateways).
// CRUD via /api/assets. Supports map placement mode via EventBus.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const ASSET_TYPES = [
    { value: 'camera', label: 'Camera', icon: 'C', color: '#00f0ff' },
    { value: 'sensor', label: 'Sensor', icon: 'S', color: '#05ffa1' },
    { value: 'mesh_radio', label: 'Mesh Radio', icon: 'M', color: '#fcee0a' },
    { value: 'gateway', label: 'Gateway', icon: 'G', color: '#ff2a6d' },
];

export const AssetsPanelDef = {
    id: 'assets',
    title: 'ASSETS',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 300, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'assets-panel-inner';
        el.innerHTML = `
            <div class="asset-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="add-asset">+ ADD ASSET</button>
            </div>
            <ul class="panel-list asset-list" data-bind="asset-list" role="listbox" aria-label="Placed assets">
                <li class="panel-empty">Loading assets...</li>
            </ul>
            <div class="asset-editor" data-bind="asset-editor" style="display:none">
                <div class="panel-section-label" data-bind="editor-title">NEW ASSET</div>
                <div class="asset-editor-form">
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-name">NAME</label>
                        <input type="text" id="asset-name" class="panel-input" data-bind="name" placeholder="Front Camera" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-type">TYPE</label>
                        <select id="asset-type" class="panel-input" data-bind="type">
                            ${ASSET_TYPES.map(t => `<option value="${t.value}">${t.label}</option>`).join('')}
                        </select>
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-height">HEIGHT (m)</label>
                        <input type="number" id="asset-height" class="panel-input" data-bind="height" value="3" min="0" max="100" step="0.1" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-floor">FLOOR LEVEL</label>
                        <input type="number" id="asset-floor" class="panel-input" data-bind="floor" value="0" min="-5" max="200" step="1" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-mounting">MOUNTING</label>
                        <select id="asset-mounting" class="panel-input" data-bind="mounting">
                            <option value="wall">Wall</option>
                            <option value="ceiling">Ceiling</option>
                            <option value="pole">Pole</option>
                            <option value="ground">Ground</option>
                        </select>
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-coverage-radius">RANGE (m)</label>
                        <input type="number" id="asset-coverage-radius" class="panel-input" data-bind="coverage_radius" value="15" min="0" max="500" step="1" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-fov">FOV (deg)</label>
                        <input type="number" id="asset-fov" class="panel-input" data-bind="fov" value="90" min="1" max="360" step="1" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label" for="asset-rotation">ROTATION (deg)</label>
                        <input type="number" id="asset-rotation" class="panel-input" data-bind="rotation" value="0" min="0" max="360" step="1" />
                    </div>
                    <div class="panel-stat-row">
                        <label class="panel-stat-label">POSITION</label>
                        <span class="panel-stat-value mono" data-bind="position" style="font-size:0.5rem">Click map to place</span>
                    </div>
                    <div class="asset-editor-actions">
                        <button class="panel-action-btn" data-action="place-on-map">PLACE ON MAP</button>
                        <button class="panel-action-btn panel-action-btn-primary" data-action="save-asset">SAVE</button>
                        <button class="panel-action-btn" data-action="cancel-edit">CANCEL</button>
                    </div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="asset-list"]');
        const editorEl = bodyEl.querySelector('[data-bind="asset-editor"]');
        const editorTitleEl = bodyEl.querySelector('[data-bind="editor-title"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const addBtn = bodyEl.querySelector('[data-action="add-asset"]');
        const placeBtn = bodyEl.querySelector('[data-action="place-on-map"]');
        const saveBtn = bodyEl.querySelector('[data-action="save-asset"]');
        const cancelBtn = bodyEl.querySelector('[data-action="cancel-edit"]');
        const positionLabel = bodyEl.querySelector('[data-bind="position"]');

        const nameInput = bodyEl.querySelector('[data-bind="name"]');
        const typeSelect = bodyEl.querySelector('[data-bind="type"]');
        const heightInput = bodyEl.querySelector('[data-bind="height"]');
        const floorInput = bodyEl.querySelector('[data-bind="floor"]');
        const mountingSelect = bodyEl.querySelector('[data-bind="mounting"]');
        const coverageRadiusInput = bodyEl.querySelector('[data-bind="coverage_radius"]');
        const fovInput = bodyEl.querySelector('[data-bind="fov"]');
        const rotationInput = bodyEl.querySelector('[data-bind="rotation"]');

        let assets = [];
        let editingAssetId = null; // null = new, string = editing existing
        let placementPos = null;   // { x, y } from map click
        let placementMode = false;

        function typeInfo(type) {
            return ASSET_TYPES.find(t => t.value === type) || ASSET_TYPES[0];
        }

        function renderList() {
            if (!listEl) return;
            if (assets.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No assets placed</li>';
                return;
            }

            listEl.innerHTML = assets.map(a => {
                const info = typeInfo(a.asset_class || a.asset_type);
                const posStr = (a.home_x != null && a.home_y != null)
                    ? `${a.home_x.toFixed(1)}, ${a.home_y.toFixed(1)}`
                    : '--';
                const heightStr = a.height_meters != null ? `${a.height_meters}m` : '';
                const floorStr = a.floor_level != null ? `F${a.floor_level}` : '';
                const mountStr = a.mounting_type ? a.mounting_type.toUpperCase() : '';
                const altLabel = [heightStr, floorStr, mountStr].filter(Boolean).join(' ');
                return `<li class="panel-list-item asset-item" data-asset-id="${_esc(a.asset_id)}" role="option">
                    <span class="panel-icon-badge" style="color:${info.color};border-color:${info.color}">${info.icon}</span>
                    <span class="asset-item-info">
                        <span class="asset-item-name">${_esc(a.name)}</span>
                        <span class="asset-item-meta mono" style="font-size:0.45rem;color:var(--text-ghost)">${_esc(info.label)} | ${posStr}${altLabel ? ' | ' + _esc(altLabel) : ''}</span>
                    </span>
                    <button class="panel-btn" data-action="edit-asset" data-asset-id="${_esc(a.asset_id)}" title="Edit">&#x270E;</button>
                    <button class="panel-btn" data-action="delete-asset" data-asset-id="${_esc(a.asset_id)}" title="Delete">&times;</button>
                </li>`;
            }).join('');

            // Click to center on map
            listEl.querySelectorAll('.asset-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action]')) return;
                    const a = assets.find(x => x.asset_id === item.dataset.assetId);
                    if (a && a.home_x != null && a.home_y != null) {
                        EventBus.emit('map:centerOnUnit', { id: null, x: a.home_x, y: a.home_y });
                    }
                });
            });

            // Edit handlers
            listEl.querySelectorAll('[data-action="edit-asset"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const a = assets.find(x => x.asset_id === btn.dataset.assetId);
                    if (a) openEditor(a);
                });
            });

            // Delete handlers
            listEl.querySelectorAll('[data-action="delete-asset"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const aid = btn.dataset.assetId;
                    try {
                        await fetch(`/api/assets/${aid}`, { method: 'DELETE' });
                        EventBus.emit('toast:show', { message: 'Asset deleted', type: 'info' });
                        fetchAssets();
                    } catch (_) {
                        EventBus.emit('toast:show', { message: 'Delete failed', type: 'alert' });
                    }
                });
            });
        }

        function openEditor(asset) {
            if (editorEl) editorEl.style.display = '';
            if (asset) {
                editingAssetId = asset.asset_id;
                if (editorTitleEl) editorTitleEl.textContent = 'EDIT ASSET';
                if (nameInput) nameInput.value = asset.name || '';
                if (typeSelect) typeSelect.value = asset.asset_class || asset.asset_type || 'camera';
                if (heightInput) heightInput.value = asset.height_meters ?? 3;
                if (floorInput) floorInput.value = asset.floor_level ?? 0;
                if (mountingSelect) mountingSelect.value = asset.mounting_type || 'wall';
                if (coverageRadiusInput) coverageRadiusInput.value = asset.coverage_radius_meters ?? 15;
                if (fovInput) fovInput.value = asset.coverage_cone_angle ?? 90;
                if (rotationInput) rotationInput.value = asset.heading ?? 0;
                placementPos = (asset.home_x != null && asset.home_y != null)
                    ? { x: asset.home_x, y: asset.home_y }
                    : null;
                updatePositionLabel();
            } else {
                editingAssetId = null;
                if (editorTitleEl) editorTitleEl.textContent = 'NEW ASSET';
                if (nameInput) nameInput.value = '';
                if (typeSelect) typeSelect.value = 'camera';
                if (heightInput) heightInput.value = 3;
                if (floorInput) floorInput.value = 0;
                if (mountingSelect) mountingSelect.value = 'wall';
                if (coverageRadiusInput) coverageRadiusInput.value = 15;
                if (fovInput) fovInput.value = 90;
                if (rotationInput) rotationInput.value = 0;
                placementPos = null;
                updatePositionLabel();
            }
        }

        function closeEditor() {
            if (editorEl) editorEl.style.display = 'none';
            editingAssetId = null;
            placementPos = null;
            exitPlacementMode();
        }

        function updatePositionLabel() {
            if (!positionLabel) return;
            if (placementPos) {
                positionLabel.textContent = `${placementPos.x.toFixed(1)}, ${placementPos.y.toFixed(1)}`;
                positionLabel.style.color = '#05ffa1';
            } else {
                positionLabel.textContent = 'Click map to place';
                positionLabel.style.color = '';
            }
        }

        function enterPlacementMode() {
            placementMode = true;
            EventBus.emit('asset:placementMode', { active: true });
            EventBus.emit('toast:show', { message: 'Click on the map to place asset', type: 'info' });
            if (placeBtn) {
                placeBtn.textContent = 'PLACING...';
                placeBtn.style.color = '#fcee0a';
            }
        }

        function exitPlacementMode() {
            placementMode = false;
            EventBus.emit('asset:placementMode', { active: false });
            if (placeBtn) {
                placeBtn.textContent = 'PLACE ON MAP';
                placeBtn.style.color = '';
            }
        }

        // Listen for map clicks during placement mode
        function onMapClick(data) {
            if (!placementMode) return;
            placementPos = { x: data.x, y: data.y };
            updatePositionLabel();
            exitPlacementMode();
        }
        EventBus.on('map:click', onMapClick);
        panel._unsubs.push(() => EventBus.off('map:click', onMapClick));

        async function saveAsset() {
            const name = nameInput?.value?.trim();
            const type = typeSelect?.value || 'camera';
            const height = parseFloat(heightInput?.value) || 3;
            const floor = parseInt(floorInput?.value) || 0;
            const mounting = mountingSelect?.value || 'wall';
            const coverageRadius = parseFloat(coverageRadiusInput?.value) || 15;
            const fov = parseFloat(fovInput?.value) || 90;
            const rotation = parseFloat(rotationInput?.value) || 0;

            if (!name) {
                EventBus.emit('toast:show', { message: 'Name is required', type: 'alert' });
                return;
            }

            const posX = placementPos?.x ?? 0;
            const posY = placementPos?.y ?? 0;

            if (editingAssetId) {
                // Update existing
                try {
                    await fetch(`/api/assets/${editingAssetId}`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            name,
                            position_x: posX,
                            position_y: posY,
                            heading: rotation,
                            height_meters: height,
                            floor_level: floor,
                            mounting_type: mounting,
                            coverage_radius_meters: coverageRadius,
                            coverage_cone_angle: fov,
                        }),
                    });
                    EventBus.emit('toast:show', { message: 'Asset updated', type: 'info' });
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Update failed', type: 'alert' });
                    return;
                }
            } else {
                // Create new
                const assetId = `${type.toUpperCase()}-${Date.now().toString(36).toUpperCase()}`;
                try {
                    const resp = await fetch('/api/assets', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            asset_id: assetId,
                            name,
                            asset_type: 'fixed',
                            asset_class: type,
                            capabilities: ['patrol', 'loiter', 'recall'],
                            home_x: posX,
                            home_y: posY,
                            height_meters: height,
                            floor_level: floor,
                            mounting_type: mounting,
                            coverage_radius_meters: coverageRadius,
                            coverage_cone_angle: fov,
                        }),
                    });
                    if (!resp.ok) {
                        const err = await resp.json().catch(() => ({}));
                        EventBus.emit('toast:show', { message: err.detail || 'Create failed', type: 'alert' });
                        return;
                    }
                    EventBus.emit('toast:show', { message: `Asset "${name}" created`, type: 'info' });
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Create failed', type: 'alert' });
                    return;
                }
            }

            closeEditor();
            fetchAssets();
        }

        async function fetchAssets() {
            try {
                const resp = await fetch('/api/assets');
                if (!resp.ok) {
                    assets = [];
                    renderList();
                    return;
                }
                assets = await resp.json();
                if (!Array.isArray(assets)) assets = [];
                renderList();
            } catch (_) {
                assets = [];
                renderList();
            }
        }

        // Wire buttons
        if (refreshBtn) refreshBtn.addEventListener('click', fetchAssets);
        if (addBtn) addBtn.addEventListener('click', () => openEditor(null));
        if (placeBtn) placeBtn.addEventListener('click', () => {
            if (placementMode) exitPlacementMode();
            else enterPlacementMode();
        });
        if (saveBtn) saveBtn.addEventListener('click', saveAsset);
        if (cancelBtn) cancelBtn.addEventListener('click', closeEditor);

        // Auto-refresh every 30s
        const refreshInterval = setInterval(fetchAssets, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Cleanup placement mode on unmount
        panel._unsubs.push(() => exitPlacementMode());

        // Initial fetch
        fetchAssets();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
