// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Map Bookmarks panel — save, list, and jump to named map positions.
 *
 * Bookmarks store lat/lng/zoom/pitch/bearing plus optional target
 * filters (alliance, asset type).  Click a bookmark to fly the map
 * to that position.
 */

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

let _container = null;
let _bookmarks = [];

/**
 * Initialize the bookmarks panel inside a container element.
 * @param {HTMLElement} container
 */
export function initBookmarksPanel(container) {
    _container = container;
    _container.innerHTML = `
        <div class="panel-header">
            <span class="panel-title">MAP BOOKMARKS</span>
            <button id="bookmark-save-btn" class="btn-cyber btn-sm"
                    title="Save current view">+ SAVE VIEW</button>
        </div>
        <div id="bookmark-list" class="bookmark-list"></div>
    `;

    const saveBtn = container.querySelector('#bookmark-save-btn');
    saveBtn.addEventListener('click', _saveCurrentView);

    _loadBookmarks();
}

async function _loadBookmarks() {
    try {
        const resp = await fetch('/api/bookmarks');
        const data = await resp.json();
        _bookmarks = data.bookmarks || [];
        _renderList();
    } catch (e) {
        console.error('[Bookmarks] Failed to load:', e);
    }
}

async function _saveCurrentView() {
    const name = prompt('Bookmark name:');
    if (!name) return;

    // Get current map state from the map module
    const mapState = EventBus.request('map:getState') || {};
    const lat = mapState.lat || 0;
    const lng = mapState.lng || 0;
    const zoom = mapState.zoom || 16;
    const pitch = mapState.pitch || 0;
    const bearing = mapState.bearing || 0;

    try {
        const resp = await fetch('/api/bookmarks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, lat, lng, zoom, pitch, bearing }),
        });
        if (resp.ok) {
            _loadBookmarks();
        }
    } catch (e) {
        console.error('[Bookmarks] Save failed:', e);
    }
}

function _renderList() {
    const list = _container?.querySelector('#bookmark-list');
    if (!list) return;

    if (_bookmarks.length === 0) {
        list.innerHTML = '<div class="empty-state">No bookmarks saved. Click + SAVE VIEW to add one.</div>';
        return;
    }

    list.innerHTML = _bookmarks.map(bm => `
        <div class="bookmark-item" data-id="${bm.id}">
            <div class="bookmark-info" title="Click to fly to this position">
                <span class="bookmark-name">${_esc(bm.name)}</span>
                <span class="bookmark-coords">${bm.lat.toFixed(5)}, ${bm.lng.toFixed(5)} z${bm.zoom.toFixed(1)}</span>
            </div>
            <button class="bookmark-delete" data-id="${bm.id}" title="Delete">&times;</button>
        </div>
    `).join('');

    // Click to fly
    list.querySelectorAll('.bookmark-info').forEach(el => {
        el.addEventListener('click', () => {
            const id = el.closest('.bookmark-item').dataset.id;
            const bm = _bookmarks.find(b => b.id === id);
            if (bm) {
                EventBus.emit('map:flyTo', {
                    lat: bm.lat,
                    lng: bm.lng,
                    zoom: bm.zoom,
                    pitch: bm.pitch || 0,
                    bearing: bm.bearing || 0,
                });
            }
        });
    });

    // Delete buttons
    list.querySelectorAll('.bookmark-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const id = btn.dataset.id;
            try {
                await fetch(`/api/bookmarks/${id}`, { method: 'DELETE' });
                _loadBookmarks();
            } catch (err) {
                console.error('[Bookmarks] Delete failed:', err);
            }
        });
    });
}

/**
 * Clean up the panel.
 */
export function destroyBookmarksPanel() {
    _container = null;
    _bookmarks = [];
}

/**
 * PanelDef for the panel manager registration system.
 */
export const BookmarksPanelDef = {
    id: 'bookmarks',
    title: 'MAP BOOKMARKS',
    defaultPosition: { x: 100, y: 340 },
    defaultSize: { w: 320, h: 300 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'bookmarks-panel-inner';
        initBookmarksPanel(el);
        return el;
    },

    destroy() {
        destroyBookmarksPanel();
    },
};
