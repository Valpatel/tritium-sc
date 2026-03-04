// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Camera Feeds Panel
// Shows synthetic camera MJPEG feeds as PIP overlays.
// Lists feeds from /api/synthetic/cameras, click to view MJPEG stream.
// Subscribes to: EventBus 'detection' events for live detection overlays.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const CamerasPanelDef = {
    id: 'cameras',
    title: 'CAMERA FEEDS',
    defaultPosition: { x: null, y: 8 },
    defaultSize: { w: 320, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'cameras-panel-inner';
        el.innerHTML = `
            <div class="cam-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <select class="cam-scene-select" data-bind="scene-select" title="Scene type for new feed">
                    <option value="bird_eye">Bird Eye</option>
                    <option value="street_cam">Street Cam</option>
                    <option value="battle">Battle</option>
                    <option value="neighborhood">Neighborhood</option>
                </select>
                <button class="panel-action-btn" data-action="create-feed">+ NEW</button>
            </div>
            <ul class="panel-list cam-feed-list" data-bind="feed-list" role="listbox" aria-label="Camera feeds">
                <li class="panel-empty">Loading feeds...</li>
            </ul>
            <div class="cam-preview" data-bind="preview" style="display:none">
                <div class="cam-preview-header">
                    <span class="mono cam-preview-name" data-bind="preview-name"></span>
                    <button class="panel-btn cam-preview-close" data-action="close-preview">&times;</button>
                </div>
                <div class="cam-preview-container">
                    <img class="cam-preview-img" data-bind="preview-img" alt="Camera feed" />
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const feedListEl = bodyEl.querySelector('[data-bind="feed-list"]');
        const previewEl = bodyEl.querySelector('[data-bind="preview"]');
        const previewNameEl = bodyEl.querySelector('[data-bind="preview-name"]');
        const previewImg = bodyEl.querySelector('[data-bind="preview-img"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const createBtn = bodyEl.querySelector('[data-action="create-feed"]');
        const closePreviewBtn = bodyEl.querySelector('[data-action="close-preview"]');

        let feeds = [];
        let activeFeedId = null;

        // Position at right side if no saved layout
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            panel.x = cw - panel.w - 8;
            panel.y = 340;
            panel._applyTransform();
        }

        function renderFeedList() {
            if (!feedListEl) return;
            if (feeds.length === 0) {
                feedListEl.innerHTML = '<li class="panel-empty">No camera feeds</li>';
                return;
            }

            feedListEl.innerHTML = feeds.map(f => {
                const isActive = activeFeedId === f.id;
                const sceneLabel = (f.scene_type || 'unknown').replace('_', ' ');
                return `<li class="panel-list-item cam-feed-item${isActive ? ' active' : ''}" data-feed-id="${_esc(f.id)}" role="option">
                    <span class="panel-icon-badge" style="color:var(--cyan);border-color:var(--cyan)">C</span>
                    <span class="cam-feed-info">
                        <span class="cam-feed-name">${_esc(f.name || f.id)}</span>
                        <span class="cam-feed-scene mono" style="font-size:0.5rem;color:var(--text-dim)">${_esc(sceneLabel)}</span>
                    </span>
                    <button class="panel-btn cam-feed-snap" data-action="snapshot" data-feed-id="${_esc(f.id)}" title="Download snapshot">&#x1F4F7;</button>
                    <button class="panel-btn cam-feed-delete" data-action="delete-feed" data-feed-id="${_esc(f.id)}" title="Delete feed">&times;</button>
                </li>`;
            }).join('');

            // Click handler: select feed and show preview
            feedListEl.querySelectorAll('.cam-feed-item').forEach(item => {
                item.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action="delete-feed"]')) return;
                    const feedId = item.dataset.feedId;
                    showPreview(feedId);
                });
            });

            // Snapshot handlers
            feedListEl.querySelectorAll('[data-action="snapshot"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const feedId = btn.dataset.feedId;
                    try {
                        const resp = await fetch(`/api/synthetic/cameras/${feedId}/snapshot`);
                        if (!resp.ok) throw new Error('Snapshot failed');
                        const blob = await resp.blob();
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.href = url;
                        a.download = `snapshot_${feedId}_${Date.now()}.jpg`;
                        a.click();
                        URL.revokeObjectURL(url);
                        EventBus.emit('toast:show', { message: 'Snapshot saved', type: 'info' });
                    } catch (_) {
                        EventBus.emit('toast:show', { message: 'Snapshot failed', type: 'alert' });
                    }
                });
            });

            // Delete handlers
            feedListEl.querySelectorAll('[data-action="delete-feed"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const feedId = btn.dataset.feedId;
                    try {
                        await fetch(`/api/synthetic/cameras/${feedId}`, { method: 'DELETE' });
                        if (activeFeedId === feedId) hidePreview();
                        fetchFeeds();
                    } catch (_) {}
                });
            });
        }

        function showPreview(feedId) {
            activeFeedId = feedId;
            if (previewEl) previewEl.style.display = '';
            if (previewImg) {
                previewImg.src = `/api/synthetic/cameras/${feedId}/mjpeg`;
            }
            const feed = feeds.find(f => f.id === feedId);
            if (previewNameEl) previewNameEl.textContent = feed?.name || feedId;
            renderFeedList();
        }

        function hidePreview() {
            activeFeedId = null;
            if (previewEl) previewEl.style.display = 'none';
            if (previewImg) previewImg.src = '';
            renderFeedList();
        }

        async function fetchFeeds() {
            try {
                const resp = await fetch('/api/synthetic/cameras');
                if (!resp.ok) {
                    feeds = [];
                    renderFeedList();
                    return;
                }
                feeds = await resp.json();
                if (!Array.isArray(feeds)) feeds = feeds.feeds || [];
                renderFeedList();
            } catch (_) {
                feeds = [];
                renderFeedList();
            }
        }

        const sceneSelect = bodyEl.querySelector('[data-bind="scene-select"]');

        async function createFeed() {
            const scene = sceneSelect ? sceneSelect.value : 'bird_eye';
            try {
                const resp = await fetch('/api/synthetic/cameras', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scene_type: scene }),
                });
                if (resp.ok) {
                    fetchFeeds();
                    EventBus.emit('toast:show', { message: `Created ${scene} feed`, type: 'info' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to create feed', type: 'alert' });
            }
        }

        // Wire buttons
        if (refreshBtn) refreshBtn.addEventListener('click', fetchFeeds);
        if (createBtn) createBtn.addEventListener('click', createFeed);
        if (closePreviewBtn) closePreviewBtn.addEventListener('click', hidePreview);

        // Auto-refresh every 30s
        const refreshInterval = setInterval(fetchFeeds, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Stop MJPEG stream on close to prevent resource leak
        panel._unsubs.push(() => {
            if (previewImg) previewImg.src = '';
        });

        // Initial fetch
        fetchFeeds();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
