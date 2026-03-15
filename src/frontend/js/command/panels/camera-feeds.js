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
                        <label class="cf-form-label">
                            <span class="mono">HEADING (deg, 0=North)</span>
                            <input type="number" name="heading" step="any" min="0" max="360" placeholder="0" class="cf-form-input" />
                        </label>
                        <button type="button" class="panel-action-btn cf-pick-map-btn" data-action="cf-pick-map" style="margin-bottom:8px;width:100%;color:#00f0ff;border-color:#00f0ff33">
                            PICK LOCATION FROM MAP
                        </button>
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
        const pickMapBtn = bodyEl.querySelector('[data-action="cf-pick-map"]');

        let cameras = [];
        let activeStreamImgs = [];
        let pickingLocation = false;

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
            const headingVal = fd.get('heading');
            if (latVal && latVal.trim()) payload.lat = parseFloat(latVal);
            if (lngVal && lngVal.trim()) payload.lng = parseFloat(lngVal);
            if (headingVal && headingVal.trim()) payload.heading = parseFloat(headingVal);

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

        // -- Pick location from map (click-to-place) --
        function startPickingLocation() {
            pickingLocation = true;
            if (pickMapBtn) {
                pickMapBtn.textContent = 'CLICK THE MAP TO SET LOCATION...';
                pickMapBtn.style.color = '#fcee0a';
                pickMapBtn.style.borderColor = '#fcee0a';
            }
            EventBus.emit('camera:pick-location', { active: true });
        }

        // -- Edit existing camera position (click map to reposition) --
        let editingCamId = null;

        function onLocationPicked(data) {
            if (!data) return;

            // Route to add-modal picker if active
            if (pickingLocation) {
                pickingLocation = false;
                if (pickMapBtn) {
                    pickMapBtn.textContent = 'PICK LOCATION FROM MAP';
                    pickMapBtn.style.color = '#00f0ff';
                    pickMapBtn.style.borderColor = '#00f0ff33';
                }
                const latInput = addForm ? addForm.querySelector('[name="lat"]') : null;
                const lngInput = addForm ? addForm.querySelector('[name="lng"]') : null;
                if (latInput && data.lat != null) latInput.value = data.lat.toFixed(6);
                if (lngInput && data.lng != null) lngInput.value = data.lng.toFixed(6);
                return;
            }

            // Route to existing camera position edit if active
            if (editingCamId) {
                const camId = editingCamId;
                editingCamId = null;

                // Reset button style
                const btn = bodyEl.querySelector(`.cf-set-pos-btn[data-cam-id="${camId}"]`);
                if (btn) {
                    btn.textContent = 'SET POS';
                    btn.style.color = '#00f0ff';
                    btn.style.borderColor = '#00f0ff33';
                }

                // PATCH the position to the backend
                fetch(`/api/camera-feeds/sources/${encodeURIComponent(camId)}/position`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lat: data.lat, lng: data.lng }),
                }).then(resp => {
                    if (resp.ok) {
                        // Refresh cameras to update map markers and card display
                        fetchCameras();
                    }
                }).catch(() => {});
                return;
            }
        }

        function startEditingPosition(camId) {
            editingCamId = camId;
            // Highlight the button
            const btn = bodyEl.querySelector(`.cf-set-pos-btn[data-cam-id="${camId}"]`);
            if (btn) {
                btn.textContent = 'CLICK MAP...';
                btn.style.color = '#fcee0a';
                btn.style.borderColor = '#fcee0a';
            }
            EventBus.emit('camera:pick-location', { active: true });
        }

        if (pickMapBtn) pickMapBtn.addEventListener('click', startPickingLocation);
        EventBus.on('camera:location-picked', onLocationPicked);
        panel._unsubs.push(() => EventBus.off('camera:location-picked', onLocationPicked));

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
                const hasPos = cam.lat != null && cam.lng != null;
                const posLabel = hasPos
                    ? `${Number(cam.lat).toFixed(4)}, ${Number(cam.lng).toFixed(4)}`
                    : 'No position';

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
                        <div class="cf-card-footer" style="display:flex;align-items:center;gap:4px;padding:2px 6px;font-size:10px;">
                            <span class="mono" style="color:${hasPos ? '#05ffa1' : '#888'};flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${posLabel}</span>
                            <button class="cf-set-pos-btn" data-cam-id="${_esc(cam.id)}" title="Click map to set camera position" style="
                                font-family:'JetBrains Mono',monospace;font-size:9px;padding:1px 5px;
                                background:transparent;border:1px solid #00f0ff33;color:#00f0ff;
                                cursor:pointer;border-radius:2px;white-space:nowrap;
                            ">SET POS</button>
                        </div>
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

            // Click to expand (on card, but not on the SET POS button)
            gridEl.querySelectorAll('.cf-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    if (e.target.closest('.cf-set-pos-btn')) return;
                    const camId = card.dataset.cameraId;
                    showOverlay(camId);
                });
            });

            // SET POS buttons — click map to set/update camera position
            gridEl.querySelectorAll('.cf-set-pos-btn').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    startEditingPosition(btn.dataset.camId);
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
                const newCams = Array.isArray(data) ? data : (data.cameras || data.feeds || []);
                // Preserve latest_detection from previous state (server returns null)
                const detMap = {};
                for (const c of cameras) {
                    if (c.latest_detection) detMap[c.id] = c.latest_detection;
                }
                for (const c of newCams) {
                    if (!c.latest_detection && detMap[c.id]) {
                        c.latest_detection = detMap[c.id];
                    }
                }
                cameras = newCams;
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

        // Listen for detection events from EventBus — update inline without full re-render
        function onDetection(evt) {
            if (!evt || !evt.camera_id) return;
            const cam = cameras.find(c => c.id === evt.camera_id);
            if (!cam) return;

            cam.latest_detection = {
                class_name: evt.class_name || evt.label,
                confidence: evt.confidence,
                timestamp: evt.timestamp || new Date().toISOString(),
            };

            // Update just the detection display on the specific card
            const card = gridEl ? gridEl.querySelector(`.cf-card[data-camera-id="${cam.id}"]`) : null;
            if (card) {
                let detEl = card.querySelector('.cf-card-detection');
                const det = cam.latest_detection;
                const conf = det.confidence != null ? `${Math.round(det.confidence * 100)}%` : '';
                const html = `
                    <span class="cf-det-class">${_esc(det.class_name || '')}</span>
                    ${conf ? `<span class="cf-det-conf">${conf}</span>` : ''}
                    ${det.timestamp ? `<span class="cf-det-time">${_timeAgo(det.timestamp)}</span>` : ''}
                `;
                if (!detEl) {
                    detEl = document.createElement('div');
                    detEl.className = 'cf-card-detection';
                    // Insert before the footer
                    const footer = card.querySelector('.cf-card-footer');
                    if (footer) {
                        card.insertBefore(detEl, footer);
                    } else {
                        card.appendChild(detEl);
                    }
                }
                detEl.innerHTML = html;
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
