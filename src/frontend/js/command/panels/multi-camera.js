// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Multi-Camera View Panel
// Grid layout showing 2x2 or 3x3 camera feeds simultaneously.
// Per-camera detection overlays. Click any feed to expand full-size.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


export const MultiCameraPanelDef = {
    id: 'multi-camera',
    title: 'MULTI-CAM VIEW',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 640, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'multicam-panel-inner';
        el.innerHTML = `
            <div class="multicam-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <select class="multicam-grid-select" data-bind="grid-select" title="Grid layout">
                    <option value="2">2x2</option>
                    <option value="3">3x3</option>
                    <option value="1">1x1</option>
                </select>
                <label class="multicam-overlay-toggle mono" style="font-size:0.6rem">
                    <input type="checkbox" data-bind="overlay-toggle" checked> DETECTIONS
                </label>
            </div>
            <div class="multicam-grid" data-bind="grid-container"></div>
            <div class="multicam-expanded" data-bind="expanded" style="display:none">
                <div class="multicam-expanded-header">
                    <span class="mono multicam-expanded-name" data-bind="expanded-name"></span>
                    <button class="panel-btn multicam-expanded-close" data-action="close-expanded">&times;</button>
                </div>
                <div class="multicam-expanded-container">
                    <img class="multicam-expanded-img" data-bind="expanded-img" alt="Expanded camera feed" />
                    <canvas class="multicam-expanded-overlay" data-bind="expanded-overlay"></canvas>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const gridEl = bodyEl.querySelector('[data-bind="grid-container"]');
        const gridSelect = bodyEl.querySelector('[data-bind="grid-select"]');
        const overlayToggle = bodyEl.querySelector('[data-bind="overlay-toggle"]');
        const expandedEl = bodyEl.querySelector('[data-bind="expanded"]');
        const expandedNameEl = bodyEl.querySelector('[data-bind="expanded-name"]');
        const expandedImg = bodyEl.querySelector('[data-bind="expanded-img"]');
        const expandedOverlay = bodyEl.querySelector('[data-bind="expanded-overlay"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const closeExpandedBtn = bodyEl.querySelector('[data-action="close-expanded"]');

        let feeds = [];
        let gridSize = 2;
        let showOverlays = true;
        let expandedFeedId = null;
        let detections = {};  // feedId -> array of detection boxes

        function updateGridLayout() {
            if (!gridEl) return;
            gridEl.style.gridTemplateColumns = `repeat(${gridSize}, 1fr)`;
            gridEl.style.gridTemplateRows = `repeat(${gridSize}, 1fr)`;
        }

        function renderGrid() {
            if (!gridEl) return;
            const slots = gridSize * gridSize;
            const displayFeeds = feeds.slice(0, slots);

            if (displayFeeds.length === 0) {
                gridEl.innerHTML = '<div class="multicam-empty mono">No camera feeds available</div>';
                return;
            }

            gridEl.innerHTML = displayFeeds.map(f => `
                <div class="multicam-cell" data-feed-id="${_esc(f.id)}">
                    <div class="multicam-cell-header mono">
                        <span class="multicam-cell-name">${_esc(f.name || f.id)}</span>
                        <span class="multicam-cell-scene" style="color:var(--text-dim);font-size:0.5rem">${_esc((f.scene_type || '').replace('_', ' '))}</span>
                    </div>
                    <div class="multicam-cell-feed">
                        <img class="multicam-cell-img" src="/api/synthetic/cameras/${encodeURIComponent(f.id)}/mjpeg" alt="${_esc(f.name || f.id)}" />
                        <canvas class="multicam-cell-overlay" data-overlay-id="${_esc(f.id)}"></canvas>
                    </div>
                </div>
            `).join('');

            // Pad remaining slots
            for (let i = displayFeeds.length; i < slots; i++) {
                gridEl.innerHTML += '<div class="multicam-cell multicam-cell-empty"><span class="mono" style="color:var(--text-dim)">NO FEED</span></div>';
            }

            updateGridLayout();

            // Click to expand
            gridEl.querySelectorAll('.multicam-cell[data-feed-id]').forEach(cell => {
                cell.addEventListener('click', () => {
                    expandFeed(cell.dataset.feedId);
                });
            });
        }

        function expandFeed(feedId) {
            expandedFeedId = feedId;
            if (expandedEl) expandedEl.style.display = '';
            if (gridEl) gridEl.style.display = 'none';

            const feed = feeds.find(f => f.id === feedId);
            if (expandedNameEl) expandedNameEl.textContent = feed?.name || feedId;
            if (expandedImg) {
                expandedImg.src = `/api/synthetic/cameras/${encodeURIComponent(feedId)}/mjpeg`;
            }
            drawExpandedOverlay();
        }

        function closeExpanded() {
            expandedFeedId = null;
            if (expandedEl) expandedEl.style.display = 'none';
            if (gridEl) gridEl.style.display = '';
            if (expandedImg) expandedImg.src = '';
        }

        function drawOverlay(canvas, feedId) {
            if (!canvas || !showOverlays) return;
            const ctx = canvas.getContext('2d');
            const dets = detections[feedId] || [];

            // Size canvas to match parent
            const parent = canvas.parentElement;
            if (parent) {
                canvas.width = parent.clientWidth;
                canvas.height = parent.clientHeight;
            }

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (dets.length === 0) return;

            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 2;
            ctx.font = '10px monospace';
            ctx.fillStyle = '#00f0ff';

            for (const det of dets) {
                const x = (det.x || 0) * canvas.width;
                const y = (det.y || 0) * canvas.height;
                const w = (det.w || 0.1) * canvas.width;
                const h = (det.h || 0.1) * canvas.height;

                ctx.strokeRect(x, y, w, h);
                const label = `${det.class || 'obj'} ${((det.confidence || 0) * 100).toFixed(0)}%`;
                ctx.fillText(label, x + 2, y - 3);
            }
        }

        function drawExpandedOverlay() {
            if (expandedFeedId && expandedOverlay) {
                drawOverlay(expandedOverlay, expandedFeedId);
            }
        }

        function updateAllOverlays() {
            if (!gridEl) return;
            gridEl.querySelectorAll('.multicam-cell-overlay').forEach(canvas => {
                const feedId = canvas.dataset.overlayId;
                if (feedId) drawOverlay(canvas, feedId);
            });
            drawExpandedOverlay();
        }

        async function fetchFeeds() {
            try {
                const resp = await fetch('/api/synthetic/cameras');
                if (!resp.ok) { feeds = []; renderGrid(); return; }
                const data = await resp.json();
                feeds = Array.isArray(data) ? data : (data.feeds || []);
                renderGrid();
            } catch (_) {
                feeds = [];
                renderGrid();
            }
        }

        // Wire events
        if (refreshBtn) refreshBtn.addEventListener('click', fetchFeeds);
        if (closeExpandedBtn) closeExpandedBtn.addEventListener('click', closeExpanded);

        if (gridSelect) {
            gridSelect.addEventListener('change', () => {
                gridSize = parseInt(gridSelect.value) || 2;
                renderGrid();
            });
        }

        if (overlayToggle) {
            overlayToggle.addEventListener('change', () => {
                showOverlays = overlayToggle.checked;
                updateAllOverlays();
            });
        }

        // Listen for detection events
        const onDetection = (data) => {
            const feedId = data.camera_id || data.feed_id;
            if (!feedId) return;
            detections[feedId] = data.detections || [];
            updateAllOverlays();
        };
        EventBus.on('detection', onDetection);
        panel._unsubs.push(() => EventBus.off('detection', onDetection));

        // Auto-refresh feed list every 30s
        const refreshInterval = setInterval(fetchFeeds, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Overlay redraw every 2s
        const overlayInterval = setInterval(updateAllOverlays, 2000);
        panel._unsubs.push(() => clearInterval(overlayInterval));

        // Stop all MJPEG streams on unmount
        panel._unsubs.push(() => {
            if (expandedImg) expandedImg.src = '';
            if (gridEl) {
                gridEl.querySelectorAll('.multicam-cell-img').forEach(img => { img.src = ''; });
            }
        });

        fetchFeeds();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
