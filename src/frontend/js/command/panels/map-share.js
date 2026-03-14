// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Map Share Panel — share current map view with other operators.
 *
 * "Look at what I'm seeing" — broadcasts map position, zoom, layers,
 * and selected targets to all connected operators.
 */

import { EventBus } from '../events.js';
import { TritiumStore } from '../store.js';
import { getMapState } from '../map-maplibre.js';

/**
 * Get the current map view state for sharing.
 */
function getCurrentViewState() {
    const mapState = getMapState();
    const map = window._tritiumMapInstance;
    let center = { lat: 0, lng: 0 };
    let zoom = 1;
    let bearing = 0;
    let pitch = 0;

    if (map) {
        const c = map.getCenter();
        center = { lat: c.lat, lng: c.lng };
        zoom = map.getZoom();
        bearing = map.getBearing();
        pitch = map.getPitch();
    }

    // Collect active layers
    const activeLayers = [];
    for (const [key, val] of Object.entries(mapState)) {
        if (key.startsWith('show') && val === true) {
            activeLayers.push(key);
        }
    }

    // Collect selected targets
    const selectedId = TritiumStore.get('map.selectedUnitId');
    const selectedTargets = selectedId ? [selectedId] : [];

    return {
        center_lat: center.lat,
        center_lng: center.lng,
        zoom,
        bearing,
        pitch,
        active_layers: activeLayers,
        selected_targets: selectedTargets,
        mode: TritiumStore.get('map.mode') || 'observe',
        operator: '',
        message: '',
    };
}

/**
 * Create a share link for the current view.
 */
async function createShareLink() {
    const view = getCurrentViewState();
    try {
        const resp = await fetch('/api/map-share/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(view),
        });
        if (resp.ok) {
            const data = await resp.json();
            const url = `${window.location.origin}${window.location.pathname}${data.url_fragment}`;
            // Copy to clipboard
            try {
                await navigator.clipboard.writeText(url);
                EventBus.emit('toast:show', { message: 'Share link copied to clipboard', type: 'success' });
            } catch {
                EventBus.emit('toast:show', { message: `Share link: ${url}`, type: 'info' });
            }
            return data;
        }
    } catch (e) {
        console.error('[MAP-SHARE] Failed to create share link:', e);
        EventBus.emit('toast:show', { message: 'Failed to create share link', type: 'error' });
    }
    return null;
}

/**
 * Broadcast current view to all connected operators.
 */
async function broadcastView(message = '') {
    const view = getCurrentViewState();
    view.message = message;
    try {
        const resp = await fetch('/api/map-share/broadcast', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(view),
        });
        if (resp.ok) {
            EventBus.emit('toast:show', { message: 'View broadcast to all operators', type: 'success' });
        }
    } catch (e) {
        console.error('[MAP-SHARE] Broadcast failed:', e);
        EventBus.emit('toast:show', { message: 'Failed to broadcast view', type: 'error' });
    }
}

/**
 * Apply a received shared view to the local map.
 */
function applySharedView(data) {
    const map = window._tritiumMapInstance;
    if (!map) return;

    map.flyTo({
        center: [data.center_lng, data.center_lat],
        zoom: data.zoom,
        bearing: data.bearing || 0,
        pitch: data.pitch || 0,
        duration: 2000,
    });

    if (data.operator) {
        const msg = data.message
            ? `${data.operator}: "${data.message}"`
            : `${data.operator} shared their view`;
        EventBus.emit('toast:show', { message: msg, type: 'info' });
    }
}

/**
 * Check URL hash for share parameter on load.
 */
function checkShareHash() {
    const hash = window.location.hash;
    const match = hash.match(/share=([a-f0-9]+)/);
    if (match) {
        const shareId = match[1];
        fetch(`/api/map-share/${shareId}`)
            .then(r => r.json())
            .then(data => {
                if (data.view) {
                    applySharedView(data.view);
                }
            })
            .catch(e => console.error('[MAP-SHARE] Failed to load shared view:', e));
    }
}

// Listen for incoming shared views via WebSocket
EventBus.on('ws:map_view_shared', (data) => {
    applySharedView(data);
});

// Panel definition
export const MapSharePanelDef = {
    id: 'map-share',
    title: 'MAP SHARE',
    icon: '\u{1F4E1}',
    width: 320,
    height: 220,
    render(container) {
        container.innerHTML = `
            <div style="padding: 8px; font-family: 'JetBrains Mono', monospace; color: #c0c0d0;">
                <div style="margin-bottom: 12px; color: #00f0ff; font-size: 11px;">
                    Share your current map view with other operators
                </div>
                <button id="map-share-link-btn" style="
                    width: 100%; padding: 8px; margin-bottom: 8px;
                    background: rgba(0, 240, 255, 0.1); border: 1px solid #00f0ff;
                    color: #00f0ff; cursor: pointer; font-family: inherit; font-size: 11px;
                ">COPY SHARE LINK</button>
                <div style="display: flex; gap: 4px; margin-bottom: 8px;">
                    <input id="map-share-msg" type="text" placeholder="Message (optional)"
                        style="flex: 1; padding: 6px; background: rgba(255,255,255,0.05);
                        border: 1px solid #333; color: #c0c0d0; font-family: inherit; font-size: 10px;" />
                </div>
                <button id="map-share-broadcast-btn" style="
                    width: 100%; padding: 8px;
                    background: rgba(255, 42, 109, 0.15); border: 1px solid #ff2a6d;
                    color: #ff2a6d; cursor: pointer; font-family: inherit; font-size: 11px;
                ">BROADCAST VIEW TO ALL</button>
            </div>
        `;

        container.querySelector('#map-share-link-btn').onclick = () => createShareLink();
        container.querySelector('#map-share-broadcast-btn').onclick = () => {
            const msg = container.querySelector('#map-share-msg').value || '';
            broadcastView(msg);
        };
    },
};

export { createShareLink, broadcastView, applySharedView, checkShareHash };
