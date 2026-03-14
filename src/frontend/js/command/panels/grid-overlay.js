// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Map Grid Overlay — military-style grid (MGRS or lat/lng) over the tactical map.
 *
 * Toggle a coordinate reference grid for verbal position reports.
 * Supports:
 *   - Simple lat/lng grid with labeled lines
 *   - MGRS-style grid zones (approximate, for display only)
 */

import { EventBus } from '../events.js';
import { TritiumStore } from '../store.js';

// Grid overlay state
const gridState = {
    enabled: false,
    type: 'latlng',    // 'latlng' | 'mgrs'
    opacity: 0.4,
    color: '#00f0ff',
    labelColor: '#00f0ff',
    interval: 'auto',  // 'auto' | number (degrees)
    sourceId: 'tritium-grid-source',
    layerIdLines: 'tritium-grid-lines',
    layerIdLabels: 'tritium-grid-labels',
};

/**
 * Calculate appropriate grid interval based on zoom level.
 */
function getGridInterval(zoom) {
    if (zoom < 4) return 10;
    if (zoom < 6) return 5;
    if (zoom < 8) return 2;
    if (zoom < 10) return 1;
    if (zoom < 12) return 0.5;
    if (zoom < 14) return 0.1;
    if (zoom < 16) return 0.05;
    if (zoom < 18) return 0.01;
    return 0.005;
}

/**
 * Format coordinate for grid label.
 */
function formatCoord(value, isLat) {
    const dir = isLat ? (value >= 0 ? 'N' : 'S') : (value >= 0 ? 'E' : 'W');
    const abs = Math.abs(value);
    const deg = Math.floor(abs);
    const min = ((abs - deg) * 60).toFixed(2);
    return `${deg}\u00B0${min}'${dir}`;
}

/**
 * Generate grid GeoJSON for the current viewport.
 */
function generateGridGeoJSON(map) {
    const bounds = map.getBounds();
    const zoom = map.getZoom();
    const interval = gridState.interval === 'auto'
        ? getGridInterval(zoom)
        : parseFloat(gridState.interval);

    const features = [];

    // Snap bounds to grid
    const west = Math.floor(bounds.getWest() / interval) * interval;
    const east = Math.ceil(bounds.getEast() / interval) * interval;
    const south = Math.floor(bounds.getSouth() / interval) * interval;
    const north = Math.ceil(bounds.getNorth() / interval) * interval;

    // Vertical lines (longitude)
    for (let lng = west; lng <= east; lng += interval) {
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [[lng, south - 1], [lng, north + 1]],
            },
            properties: { label: formatCoord(lng, false), gridType: 'lng' },
        });
    }

    // Horizontal lines (latitude)
    for (let lat = south; lat <= north; lat += interval) {
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [[west - 1, lat], [east + 1, lat]],
            },
            properties: { label: formatCoord(lat, true), gridType: 'lat' },
        });
    }

    // Label points at intersections (every other line for readability)
    let labelCount = 0;
    for (let lng = west; lng <= east; lng += interval * 2) {
        for (let lat = south; lat <= north; lat += interval * 2) {
            if (labelCount > 200) break; // cap labels
            features.push({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [lng, lat] },
                properties: {
                    label: `${formatCoord(lat, true)}\n${formatCoord(lng, false)}`,
                    gridType: 'intersection',
                },
            });
            labelCount++;
        }
    }

    return { type: 'FeatureCollection', features };
}

/**
 * Add or update the grid overlay on the map.
 */
function updateGridOverlay() {
    const map = window._tritiumMapInstance;
    if (!map || !gridState.enabled) return;

    const geojson = generateGridGeoJSON(map);

    const source = map.getSource(gridState.sourceId);
    if (source) {
        source.setData(geojson);
    } else {
        // Add source and layers
        map.addSource(gridState.sourceId, {
            type: 'geojson',
            data: geojson,
        });

        map.addLayer({
            id: gridState.layerIdLines,
            type: 'line',
            source: gridState.sourceId,
            filter: ['!=', ['get', 'gridType'], 'intersection'],
            paint: {
                'line-color': gridState.color,
                'line-opacity': gridState.opacity,
                'line-width': 0.5,
                'line-dasharray': [4, 4],
            },
        });

        map.addLayer({
            id: gridState.layerIdLabels,
            type: 'symbol',
            source: gridState.sourceId,
            filter: ['==', ['get', 'gridType'], 'intersection'],
            layout: {
                'text-field': ['get', 'label'],
                'text-size': 9,
                'text-font': ['Open Sans Regular'],
                'text-anchor': 'top-left',
                'text-offset': [0.3, 0.3],
            },
            paint: {
                'text-color': gridState.labelColor,
                'text-opacity': gridState.opacity + 0.1,
                'text-halo-color': 'rgba(10, 10, 15, 0.8)',
                'text-halo-width': 1,
            },
        });
    }
}

/**
 * Remove the grid overlay from the map.
 */
function removeGridOverlay() {
    const map = window._tritiumMapInstance;
    if (!map) return;

    try {
        if (map.getLayer(gridState.layerIdLabels)) map.removeLayer(gridState.layerIdLabels);
        if (map.getLayer(gridState.layerIdLines)) map.removeLayer(gridState.layerIdLines);
        if (map.getSource(gridState.sourceId)) map.removeSource(gridState.sourceId);
    } catch (e) {
        // Layers may not exist
    }
}

/**
 * Toggle the grid overlay on/off.
 */
function toggleGridOverlay(forceState) {
    gridState.enabled = forceState !== undefined ? forceState : !gridState.enabled;

    if (gridState.enabled) {
        updateGridOverlay();
        // Update on map move
        const map = window._tritiumMapInstance;
        if (map) {
            map.on('moveend', updateGridOverlay);
            map.on('zoomend', updateGridOverlay);
        }
    } else {
        removeGridOverlay();
        const map = window._tritiumMapInstance;
        if (map) {
            map.off('moveend', updateGridOverlay);
            map.off('zoomend', updateGridOverlay);
        }
    }

    EventBus.emit('grid:toggled', { enabled: gridState.enabled });
    return gridState.enabled;
}

/**
 * Set grid type (latlng or mgrs).
 */
function setGridType(type) {
    gridState.type = type;
    if (gridState.enabled) {
        removeGridOverlay();
        updateGridOverlay();
    }
}

// Panel definition
export const GridOverlayPanelDef = {
    id: 'grid-overlay',
    title: 'MAP GRID',
    icon: '\u{1F4CD}',
    width: 280,
    height: 240,
    render(container) {
        container.innerHTML = `
            <div style="padding: 8px; font-family: 'JetBrains Mono', monospace; color: #c0c0d0; font-size: 11px;">
                <div style="margin-bottom: 8px; display: flex; align-items: center; gap: 8px;">
                    <label style="color: #00f0ff;">Grid Overlay</label>
                    <button id="grid-toggle-btn" style="
                        padding: 4px 12px;
                        background: ${gridState.enabled ? 'rgba(5, 255, 161, 0.2)' : 'rgba(255,255,255,0.05)'};
                        border: 1px solid ${gridState.enabled ? '#05ffa1' : '#333'};
                        color: ${gridState.enabled ? '#05ffa1' : '#666'};
                        cursor: pointer; font-family: inherit; font-size: 10px;
                    ">${gridState.enabled ? 'ON' : 'OFF'}</button>
                </div>
                <div style="margin-bottom: 8px;">
                    <label style="color: #888; font-size: 10px;">Grid Type</label>
                    <select id="grid-type-select" style="
                        display: block; width: 100%; margin-top: 4px; padding: 4px;
                        background: rgba(255,255,255,0.05); border: 1px solid #333;
                        color: #c0c0d0; font-family: inherit; font-size: 10px;
                    ">
                        <option value="latlng" ${gridState.type === 'latlng' ? 'selected' : ''}>Lat/Lng Grid</option>
                        <option value="mgrs" ${gridState.type === 'mgrs' ? 'selected' : ''}>MGRS Grid</option>
                    </select>
                </div>
                <div style="margin-bottom: 8px;">
                    <label style="color: #888; font-size: 10px;">Opacity: ${(gridState.opacity * 100).toFixed(0)}%</label>
                    <input id="grid-opacity-range" type="range" min="10" max="80" value="${gridState.opacity * 100}"
                        style="width: 100%; margin-top: 4px;" />
                </div>
                <div style="margin-bottom: 8px;">
                    <label style="color: #888; font-size: 10px;">Grid Color</label>
                    <div style="display: flex; gap: 4px; margin-top: 4px;">
                        <button class="grid-color-btn" data-color="#00f0ff" style="width: 24px; height: 24px; background: #00f0ff; border: 1px solid #333; cursor: pointer;"></button>
                        <button class="grid-color-btn" data-color="#05ffa1" style="width: 24px; height: 24px; background: #05ffa1; border: 1px solid #333; cursor: pointer;"></button>
                        <button class="grid-color-btn" data-color="#ff2a6d" style="width: 24px; height: 24px; background: #ff2a6d; border: 1px solid #333; cursor: pointer;"></button>
                        <button class="grid-color-btn" data-color="#fcee0a" style="width: 24px; height: 24px; background: #fcee0a; border: 1px solid #333; cursor: pointer;"></button>
                        <button class="grid-color-btn" data-color="#ffffff" style="width: 24px; height: 24px; background: #ffffff; border: 1px solid #333; cursor: pointer;"></button>
                    </div>
                </div>
                <div style="color: #666; font-size: 9px; border-top: 1px solid #1a1a2e; padding-top: 6px;">
                    Grid auto-adjusts density with zoom level.<br/>
                    Keyboard shortcut: Ctrl+G to toggle.
                </div>
            </div>
        `;

        container.querySelector('#grid-toggle-btn').onclick = () => {
            toggleGridOverlay();
            // Re-render panel to update button state
            GridOverlayPanelDef.render(container);
        };

        container.querySelector('#grid-type-select').onchange = (e) => {
            setGridType(e.target.value);
        };

        container.querySelector('#grid-opacity-range').oninput = (e) => {
            gridState.opacity = parseInt(e.target.value) / 100;
            if (gridState.enabled) {
                removeGridOverlay();
                updateGridOverlay();
            }
            e.target.previousElementSibling.textContent = `Opacity: ${e.target.value}%`;
        };

        container.querySelectorAll('.grid-color-btn').forEach(btn => {
            btn.onclick = () => {
                gridState.color = btn.dataset.color;
                gridState.labelColor = btn.dataset.color;
                if (gridState.enabled) {
                    removeGridOverlay();
                    updateGridOverlay();
                }
            };
        });
    },
};

export { toggleGridOverlay, setGridType, gridState, updateGridOverlay };
