// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * AddonMapLayers — polls addon GeoJSON endpoints and renders them
 * as MapLibre GL sources/layers on the tactical map.
 *
 * Usage:
 *   import { AddonMapLayers } from './addon-map-layers.js';
 *   const addonLayers = new AddonMapLayers(map);
 *   await addonLayers.loadFromAddons();
 */

import { EventBus } from './events.js';

// Default colors by geometry hint / category
const CATEGORY_COLORS = {
    aircraft:   '#ffaa00',
    mesh_node:  '#00d4aa',
    rf_signal:  '#b060ff',
    mesh_link:  '#00d4aa50',
};

const DEFAULT_COLOR = '#00f0ff'; // cyan fallback

/**
 * Manages addon-contributed GeoJSON layers on the MapLibre map.
 */
export class AddonMapLayers {
    /**
     * @param {maplibregl.Map} map — initialized MapLibre map instance
     */
    constructor(map) {
        /** @type {maplibregl.Map} */
        this._map = map;
        /** @type {Map<string, {def: object, timer: number|null, visible: boolean}>} */
        this._layers = new Map();
    }

    // ------------------------------------------------------------------
    // Public API
    // ------------------------------------------------------------------

    /**
     * Fetch layer definitions from the backend and add them all to the map.
     */
    async loadFromAddons() {
        try {
            const resp = await fetch('/api/addons/geojson-layers');
            if (!resp.ok) {
                console.warn('[AddonMapLayers] Failed to fetch geojson-layers:', resp.status);
                return;
            }
            const layers = await resp.json();
            if (!Array.isArray(layers)) {
                console.warn('[AddonMapLayers] Expected array from geojson-layers, got:', typeof layers);
                return;
            }
            for (const layerDef of layers) {
                this.addLayer(layerDef);
            }
            console.log(`[AddonMapLayers] Loaded ${layers.length} addon GeoJSON layer(s)`);
        } catch (err) {
            console.warn('[AddonMapLayers] Error loading addon layers:', err);
        }
    }

    /**
     * Add a single GeoJSON layer to the map and start polling.
     *
     * @param {object} layerDef — layer definition from the backend:
     *   { layer_id, addon_id, label, category, color, geojson_endpoint,
     *     refresh_interval, visible_by_default }
     */
    addLayer(layerDef) {
        const id = layerDef.layer_id;
        if (!id || !layerDef.geojson_endpoint) {
            console.warn('[AddonMapLayers] Invalid layer definition, missing id or endpoint:', layerDef);
            return;
        }
        if (this._layers.has(id)) {
            console.warn(`[AddonMapLayers] Layer "${id}" already exists, skipping`);
            return;
        }

        const color = layerDef.color || CATEGORY_COLORS[layerDef.category] || DEFAULT_COLOR;
        const visible = layerDef.visible_by_default !== false;

        // Add empty GeoJSON source
        this._map.addSource(id, {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
        });

        // Add a circle layer for points
        this._map.addLayer({
            id: `${id}-circle`,
            type: 'circle',
            source: id,
            filter: ['==', '$type', 'Point'],
            paint: {
                'circle-radius': 6,
                'circle-color': color,
                'circle-stroke-width': 1,
                'circle-stroke-color': '#ffffff',
                'circle-opacity': 0.9,
            },
            layout: {
                visibility: visible ? 'visible' : 'none',
            },
        });

        // Add a line layer for LineStrings
        this._map.addLayer({
            id: `${id}-line`,
            type: 'line',
            source: id,
            filter: ['==', '$type', 'LineString'],
            paint: {
                'line-color': color,
                'line-width': 2,
                'line-opacity': 0.8,
            },
            layout: {
                visibility: visible ? 'visible' : 'none',
            },
        });

        // Add a fill layer for Polygons
        this._map.addLayer({
            id: `${id}-fill`,
            type: 'fill',
            source: id,
            filter: ['==', '$type', 'Polygon'],
            paint: {
                'fill-color': color,
                'fill-opacity': 0.25,
                'fill-outline-color': color,
            },
            layout: {
                visibility: visible ? 'visible' : 'none',
            },
        });

        const entry = { def: layerDef, timer: null, visible };
        this._layers.set(id, entry);

        // Initial fetch
        this.refreshLayer(id);

        // Start polling
        const intervalMs = (layerDef.refresh_interval || 5) * 1000;
        this._startPolling(id, intervalMs);

        EventBus.emit('addon-layers:added', { layer_id: id, label: layerDef.label });
    }

    /**
     * Remove a layer and its source from the map, stop polling.
     * @param {string} layerId
     */
    removeLayer(layerId) {
        const entry = this._layers.get(layerId);
        if (!entry) return;

        this._stopPolling(layerId);

        // Remove sub-layers (circle, line, fill)
        for (const suffix of ['-circle', '-line', '-fill']) {
            const subId = layerId + suffix;
            try {
                if (this._map.getLayer(subId)) {
                    this._map.removeLayer(subId);
                }
            } catch (_) { /* ignore */ }
        }

        // Remove source
        try {
            if (this._map.getSource(layerId)) {
                this._map.removeSource(layerId);
            }
        } catch (_) { /* ignore */ }

        this._layers.delete(layerId);
        EventBus.emit('addon-layers:removed', { layer_id: layerId });
    }

    /**
     * Toggle layer visibility.
     * @param {string} layerId
     * @param {boolean} visible
     */
    toggleLayer(layerId, visible) {
        const entry = this._layers.get(layerId);
        if (!entry) return;

        entry.visible = visible;
        const vis = visible ? 'visible' : 'none';
        for (const suffix of ['-circle', '-line', '-fill']) {
            try {
                this._map.setLayoutProperty(layerId + suffix, 'visibility', vis);
            } catch (_) { /* ignore */ }
        }
    }

    /**
     * Fetch fresh GeoJSON from the layer's endpoint and update the source.
     * @param {string} layerId
     */
    async refreshLayer(layerId) {
        const entry = this._layers.get(layerId);
        if (!entry) return;

        try {
            const resp = await fetch(entry.def.geojson_endpoint);
            if (!resp.ok) return;
            const geojson = await resp.json();
            const source = this._map.getSource(layerId);
            if (source && typeof source.setData === 'function') {
                source.setData(geojson);
            }
        } catch (_) {
            // Silently ignore fetch errors — the endpoint may be temporarily unavailable
        }
    }

    /**
     * Remove all layers and stop all polling timers.
     */
    destroy() {
        for (const layerId of [...this._layers.keys()]) {
            this.removeLayer(layerId);
        }
    }

    /**
     * Return current layer entries for external inspection.
     * @returns {Map<string, object>}
     */
    get layers() {
        return this._layers;
    }

    // ------------------------------------------------------------------
    // Internal
    // ------------------------------------------------------------------

    /**
     * @param {string} layerId
     * @param {number} intervalMs
     */
    _startPolling(layerId, intervalMs) {
        const entry = this._layers.get(layerId);
        if (!entry) return;
        this._stopPolling(layerId);
        entry.timer = setInterval(() => this.refreshLayer(layerId), intervalMs);
    }

    /**
     * @param {string} layerId
     */
    _stopPolling(layerId) {
        const entry = this._layers.get(layerId);
        if (!entry || entry.timer == null) return;
        clearInterval(entry.timer);
        entry.timer = null;
    }
}
