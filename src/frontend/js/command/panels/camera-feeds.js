// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Camera Feeds Panel — Live camera feed grid with MJPEG streaming
// Fetches camera list from /api/camera-feeds/, shows grid of thumbnails
// with live MJPEG preview, status indicators, and latest detection info.
// Includes Add Camera modal for UX Loop 8.

import { EventBus } from '../events.js';
import { _esc, _timeAgo } from '../panel-utils.js';

function _statusDot(status) {
    const colors = {
        streaming: 'var(--green, #05ffa1)',
        connecting: 'var(--yellow, #fcee0a)',
        offline: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[status] || colors.offline;
    const label = (status || 'offline').toUpperCase();
    return `<span class="cf-status-dot" style="background:${color}" title="${label}"></span>`;
}

export const CameraFeedsPanelDef = {
    id: 'camera-feeds',
    title: 'CAMERA FEEDS',
    defaultPosition: { x: null, y: 8 },
    defaultSize: { w: 420, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'camera-feeds-panel-inner';
        el.innerHTML = `
            <div class="cf-toolbar">
                <span class="cf-count mono" data-bind="cf-count">0 feeds</span>
                <div class="cf-toolbar-actions">
                    <button class="panel-action-btn" data-action="cf-add" title="Add a new camera source">+ ADD CAMERA</button>
                    <button class="panel-action-btn panel-action-btn-primary" data-action="cf-refresh">REFRESH</button>
                </div>
            </div>
            <div class="cf-grid" data-bind="cf-grid">
                <div class="panel-empty">Loading camera feeds...</div>
            </div>
            <div class="cf-overlay" data-bind="cf-overlay" style="display:none">
                <div class="cf-overlay-header">
                    <span class="mono cf-overlay-name" data-bind="cf-overlay-name"></span>
                    <button class="panel-btn cf-overlay-close" data-action="cf-close-overlay">&times;</button>
                </div>
                <div class="cf-overlay-video">
                    <img class="cf-overlay-img" data-bind="cf-overlay-img" alt="Camera feed" />
                </div>
                <div class="cf-overlay-detection mono" data-bind="cf-overlay-detection"></div>
            </div>
            <div class="cf-add-modal" data-bind="cf-add-modal" style="display:none">
                <div class="cf-add-modal-content">
                    <div class="cf-add-modal-header">
                        <span class="mono">ADD CAMERA</span>
                        <button class="panel-btn cf-overlay-close" data-action="cf-add-close">&times;</button>
                    </div>
                    <form class="cf-add-form" data-bind="cf-add-form">
                        <label class="cf-form-label">
                            <span class="mono">NAME</span>
                            <input type="text" name="name" placeholder="Front Door Camera" required class="cf-form-input" />
                        </label>
                        <label class="cf-form-label">
                            <span class="mono">TYPE</span>
                            <select name="source_type" class="cf-form-input">
                                <option value="rtsp">RTSP</option>
                                <option value="mjpeg">MJPEG</option>
                                <option value="mqtt">MQTT</option>
                                <option value="usb">USB</option>
                                <option value="synthetic">Synthetic</option>
                            </select>
                        </label>
                        <label class="cf-form-label">
                            <span class="mono">URL / URI</span>
                            <input type="text" name="uri" placeholder="rtsp://192.168.1.100:554/stream" class="cf-form-input" />
                        </label>
                        <div class="cf-form-row">
                            <label class="cf-form-label cf-form-half">
                                <span class="mono">LATITUDE</span>
                                <input type="number" name="lat" step="any" placeholder="33.1234" class="cf-form-input" />
                            </label>
                            <label class="cf-form-label cf-form-half">
                                <span class="mono">LONGITUDE</span>
                                <input type="number" name="lng" step="any" placeholder="-97.5678" class="cf-form-input" />
                            </label>
                        </div>
                        <div class="cf-form-row">
                            <label class="cf-form-label cf-form-half">
                                <span class="mono">WIDTH</span>
                                <input type="number" name="width" value="640" min="160" max="3840" class="cf-form-input" />
                            </label>
                            <label class="cf-form-label cf-form-half">
                                <span class="mono">HEIGHT</span>
                                <input type="number" name="height" value="480" min="120" max="2160" class="cf-form-input" />
                            </label>
                        </div>
                        <div class="cf-add-error mono" data-bind="cf-add-error" style="display:none"></div>
                        <button type="submit" class="panel-action-btn panel-action-btn-primary cf-add-submit">REGISTER CAMERA</button>
                    </form>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const gridEl = bodyEl.querySelector('[data-bind="cf-grid"]');
        const countEl = bodyEl.querySelector('[data-bind="cf-count"]');
        const overlayEl = bodyEl.querySelector('[data-bind="cf-overlay"]');
        const overlayNameEl = bodyEl.querySelector('[data-bind="cf-overlay-name"]');
        const overlayImg = bodyEl.querySelector('[data-bind="cf-overlay-img"]');
        const overlayDetectionEl = bodyEl.querySelector('[data-bind="cf-overlay-detection"]');
        const refreshBtn = bodyEl.querySelector('[data-action="cf-refresh"]');
        const closeOverlayBtn = bodyEl.querySelector('[data-action="cf-close-overlay"]');
        const addBtn = bodyEl.querySelector('[data-action="cf-add"]');
        const addModal = bodyEl.querySelector('[data-bind="cf-add-modal"]');
        const addCloseBtn = bodyEl.querySelector('[data-action="cf-add-close"]');
        const addForm = bodyEl.querySelector('[data-bind="cf-add-form"]');
        const addError = bodyEl.querySelector('[data-bind="cf-add-error"]');

        let cameras = [];
        let activeStreamImgs = [];

        // Position at right side if no saved layout
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            panel.x = cw - panel.w - 8;
            panel.y = 8;
            panel._applyTransform();
        }

        // --- Add Camera Modal ---
        function showAddModal() {
            if (addModal) addModal.style.display = '';
            if (addForm) addForm.reset();
            if (addError) addError.style.display = 'none';
        }

        function hideAddModal() {
            if (addModal) addModal.style.display = 'none';
        }

        async function submitAddCamera(e) {
            e.preventDefault();
            if (addError) addError.style.display = 'none';
            const fd = new FormData(addForm);
            const name = (fd.get('name') || '').trim();
            if (!name) {
                showAddError('Name is required');
                return;
            }
            // Generate a source_id from the name
            const sourceId = name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || ('cam_' + Date.now());
            const payload = {
                source_id: sourceId,
                source_type: fd.get('source_type') || 'rtsp',
                name: name,
                uri: (fd.get('uri') || '').trim(),
                width: parseInt(fd.get('width'), 10) || 640,
                height: parseInt(fd.get('height'), 10) || 480,
                fps: 10,
                extra: {},
            };
            const latVal = fd.get('lat');
            const lngVal = fd.get('lng');
            if (latVal && latVal.trim()) payload.lat = parseFloat(latVal);
            if (lngVal && lngVal.trim()) payload.lng = parseFloat(lngVal);

            try {
                const resp = await fetch('/api/camera-feeds/sources', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    showAddError(err.detail || `Error ${resp.status}`);
                    return;
                }
                hideAddModal();
                // Refresh the camera list and emit event for map markers
                await fetchCameras();
                EventBus.emit('cameras:changed', { cameras });
            } catch (ex) {
                showAddError(ex.message || 'Network error');
            }
        }

        function showAddError(msg) {
            if (addError) {
                addError.textContent = msg;
                addError.style.display = '';
            }
        }

        if (addBtn) addBtn.addEventListener('click', showAddModal);
        if (addCloseBtn) addCloseBtn.addEventListener('click', hideAddModal);
        if (addForm) addForm.addEventListener('submit', submitAddCamera);

        function renderGrid() {
            if (!gridEl) return;

            if (cameras.length === 0) {
                gridEl.innerHTML = '<div class="panel-empty">No camera feeds available.<br><span class="mono" style="color:var(--cyan,#00f0ff);cursor:pointer" data-action="cf-add-inline">+ Add a camera</span></div>';
                const inlineAdd = gridEl.querySelector('[data-action="cf-add-inline"]');
                if (inlineAdd) inlineAdd.addEventListener('click', showAddModal);
                if (countEl) countEl.textContent = '0 feeds';
                return;
            }

            if (countEl) countEl.textContent = `${cameras.length} feed${cameras.length !== 1 ? 's' : ''}`;

            // Stop existing streams before re-rendering
            stopAllStreams();

            gridEl.innerHTML = cameras.map(cam => {
                const status = cam.status || 'offline';
                const detection = cam.latest_detection;
                let detectionHtml = '';
                if (detection) {
                    const conf = detection.confidence != null
                        ? `${Math.round(detection.confidence * 100)}%`
                        : '';
                    detectionHtml = `
                        <div class="cf-card-detection">
                            <span class="cf-det-class">${_esc(detection.class_name || detection.label || '')}</span>
                            ${conf ? `<span class="cf-det-conf">${conf}</span>` : ''}
                            ${detection.timestamp ? `<span class="cf-det-time">${_timeAgo(detection.timestamp)}</span>` : ''}
                        </div>`;
                }

                const streamUrl = cam.stream_url || `/api/camera-feeds/sources/${cam.id}/mjpeg`;

                return `
                    <div class="cf-card" data-camera-id="${_esc(cam.id)}" data-status="${_esc(status)}">
                        <div class="cf-card-header">
                            ${_statusDot(status)}
                            <span class="cf-card-name mono">${_esc(cam.name || cam.id)}</span>
                        </div>
                        <div class="cf-card-thumb">
                            ${status !== 'offline'
                                ? `<img class="cf-thumb-img" data-stream-src="${_esc(streamUrl)}" alt="${_esc(cam.name || cam.id)}" />`
                                : '<div class="cf-thumb-offline">OFFLINE</div>'
                            }
                        </div>
                        ${detectionHtml}
                    </div>`;
            }).join('');

            // Start MJPEG streams for non-offline cameras
            activeStreamImgs = [];
            gridEl.querySelectorAll('.cf-thumb-img').forEach(img => {
                const src = img.dataset.streamSrc;
                if (src) {
                    img.src = src;
                    activeStreamImgs.push(img);
                }
            });

            // Click to expand
            gridEl.querySelectorAll('.cf-card').forEach(card => {
                card.addEventListener('click', () => {
                    const camId = card.dataset.cameraId;
                    showOverlay(camId);
                });
            });
        }

        function stopAllStreams() {
            activeStreamImgs.forEach(img => { img.src = ''; });
            activeStreamImgs = [];
        }

        function showOverlay(camId) {
            const cam = cameras.find(c => c.id === camId);
            if (!cam) return;
            if (overlayEl) overlayEl.style.display = '';
            if (overlayNameEl) overlayNameEl.textContent = cam.name || cam.id;
            if (overlayImg) {
                overlayImg.src = cam.stream_url || `/api/camera-feeds/sources/${camId}/mjpeg`;
            }
            if (overlayDetectionEl && cam.latest_detection) {
                const d = cam.latest_detection;
                const conf = d.confidence != null ? ` ${Math.round(d.confidence * 100)}%` : '';
                overlayDetectionEl.textContent = `${d.class_name || d.label || 'unknown'}${conf}${d.timestamp ? ' | ' + _timeAgo(d.timestamp) : ''}`;
            } else if (overlayDetectionEl) {
                overlayDetectionEl.textContent = '';
            }
        }

        function hideOverlay() {
            if (overlayEl) overlayEl.style.display = 'none';
            if (overlayImg) overlayImg.src = '';
            if (overlayDetectionEl) overlayDetectionEl.textContent = '';
        }

        async function fetchCameras() {
            try {
                const resp = await fetch('/api/camera-feeds/');
                if (!resp.ok) {
                    cameras = [];
                    renderGrid();
                    return;
                }
                const data = await resp.json();
                cameras = Array.isArray(data) ? data : (data.cameras || data.feeds || []);
                renderGrid();
                // Notify map layer about camera positions
                EventBus.emit('cameras:changed', { cameras });
            } catch (_) {
                cameras = [];
                renderGrid();
            }
        }

        // Wire controls
        if (refreshBtn) refreshBtn.addEventListener('click', fetchCameras);
        if (closeOverlayBtn) closeOverlayBtn.addEventListener('click', hideOverlay);

        // Close overlay/modal on Escape
        function onKeyDown(e) {
            if (e.key === 'Escape') {
                if (addModal && addModal.style.display !== 'none') {
                    hideAddModal();
                } else if (overlayEl && overlayEl.style.display !== 'none') {
                    hideOverlay();
                }
            }
        }
        document.addEventListener('keydown', onKeyDown);
        panel._unsubs.push(() => document.removeEventListener('keydown', onKeyDown));

        // Auto-refresh every 30s
        const refreshInterval = setInterval(fetchCameras, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Stop all MJPEG streams on panel close
        panel._unsubs.push(() => {
            stopAllStreams();
            if (overlayImg) overlayImg.src = '';
        });

        // Listen for detection events from EventBus
        function onDetection(evt) {
            if (!evt || !evt.camera_id) return;
            const cam = cameras.find(c => c.id === evt.camera_id);
            if (cam) {
                cam.latest_detection = {
                    class_name: evt.class_name || evt.label,
                    confidence: evt.confidence,
                    timestamp: evt.timestamp || new Date().toISOString(),
                };
                renderGrid();
            }
        }
        EventBus.on('detection', onDetection);
        panel._unsubs.push(() => EventBus.off('detection', onDetection));

        // Listen for camera:selected from map click — open the overlay for that camera
        function onCameraSelected(evt) {
            if (!evt || !evt.id) return;
            // If cameras not loaded yet, wait and retry
            if (cameras.length === 0) {
                fetchCameras().then(() => {
                    const camId = evt.id;
                    if (cameras.find(c => c.id === camId)) {
                        showOverlay(camId);
                    }
                });
            } else {
                const camId = evt.id;
                if (cameras.find(c => c.id === camId)) {
                    showOverlay(camId);
                }
            }
        }
        EventBus.on('camera:selected', onCameraSelected);
        panel._unsubs.push(() => EventBus.off('camera:selected', onCameraSelected));

        // Initial fetch
        fetchCameras();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
