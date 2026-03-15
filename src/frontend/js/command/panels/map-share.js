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

                <div style="margin-top: 12px; border-top: 1px solid rgba(0,240,255,0.15); padding-top: 8px;">
                    <div style="color: #fcee0a; font-size: 10px; margin-bottom: 6px;">COLLABORATIVE DRAWINGS</div>
                    <div id="map-share-draw-count" style="color: #888; font-size: 10px; margin-bottom: 6px;">Loading...</div>
                    <div style="display: flex; gap: 4px; flex-wrap: wrap;">
                        <button class="map-share-draw-btn" data-draw-type="freehand" style="
                            padding: 4px 8px; background: rgba(0,240,255,0.08); border: 1px solid rgba(0,240,255,0.3);
                            color: #00f0ff; cursor: pointer; font-family: inherit; font-size: 10px;">FREEHAND</button>
                        <button class="map-share-draw-btn" data-draw-type="circle" style="
                            padding: 4px 8px; background: rgba(5,255,161,0.08); border: 1px solid rgba(5,255,161,0.3);
                            color: #05ffa1; cursor: pointer; font-family: inherit; font-size: 10px;">CIRCLE</button>
                        <button class="map-share-draw-btn" data-draw-type="arrow" style="
                            padding: 4px 8px; background: rgba(252,238,10,0.08); border: 1px solid rgba(252,238,10,0.3);
                            color: #fcee0a; cursor: pointer; font-family: inherit; font-size: 10px;">ARROW</button>
                        <button class="map-share-draw-btn" data-draw-type="text" style="
                            padding: 4px 8px; background: rgba(255,42,109,0.08); border: 1px solid rgba(255,42,109,0.3);
                            color: #ff2a6d; cursor: pointer; font-family: inherit; font-size: 10px;">TEXT</button>
                    </div>
                    <button id="map-share-clear-drawings" style="
                        width: 100%; padding: 4px; margin-top: 6px;
                        background: rgba(255,42,109,0.08); border: 1px solid rgba(255,42,109,0.2);
                        color: #ff2a6d; cursor: pointer; font-family: inherit; font-size: 10px;">CLEAR ALL DRAWINGS</button>
                </div>
            </div>
        `;

        container.querySelector('#map-share-link-btn').onclick = () => createShareLink();
        container.querySelector('#map-share-broadcast-btn').onclick = () => {
            const msg = container.querySelector('#map-share-msg').value || '';
            broadcastView(msg);
        };

        // Collaborative drawings — wire /api/collaboration/drawings
        const drawCountEl = container.querySelector('#map-share-draw-count');

        async function refreshDrawCount() {
            try {
                const r = await fetch('/api/collaboration/drawings');
                if (r.ok) {
                    const data = await r.json();
                    const count = (data.drawings || []).length;
                    if (drawCountEl) drawCountEl.textContent = `${count} shared drawing(s) on map`;
                }
            } catch { /* silent */ }
        }
        refreshDrawCount();

        container.querySelectorAll('.map-share-draw-btn').forEach(btn => {
            btn.onclick = async () => {
                const drawType = btn.dataset.drawType;
                const map = window._tritiumMapInstance;
                const center = map ? map.getCenter() : { lng: 0, lat: 0 };
                let drawReq = {
                    drawing_type: drawType,
                    operator_id: 'local_op',
                    operator_name: 'Operator',
                    color: '#00f0ff',
                    coordinates: [[center.lat, center.lng]],
                    layer: 'default',
                };
                if (drawType === 'circle') {
                    drawReq.radius = 50;
                }
                if (drawType === 'text') {
                    const text = prompt('Drawing text:');
                    if (!text) return;
                    drawReq.text = text;
                }
                if (drawType === 'arrow') {
                    drawReq.coordinates = [
                        [center.lat, center.lng],
                        [center.lat + 0.001, center.lng + 0.001],
                    ];
                }
                try {
                    const r = await fetch('/api/collaboration/drawings', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(drawReq),
                    });
                    if (r.ok) {
                        EventBus.emit('toast:show', { message: `${drawType} drawing added`, type: 'success' });
                        refreshDrawCount();
                    }
                } catch (e) {
                    console.error('[MAP-SHARE] Draw failed:', e);
                }
            };
        });

        container.querySelector('#map-share-clear-drawings').onclick = async () => {
            if (!confirm('Clear all shared drawings?')) return;
            try {
                await fetch('/api/collaboration/drawings', { method: 'DELETE' });
                EventBus.emit('toast:show', { message: 'All drawings cleared', type: 'success' });
                refreshDrawCount();
            } catch {}
        };

        // Stop keyboard propagation from inputs
        container.querySelectorAll('input').forEach(inp => {
            inp.addEventListener('keydown', (e) => e.stopPropagation());
        });
    },
};

export { createShareLink, broadcastView, applySharedView, checkShareHash };
