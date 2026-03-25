// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Enhanced Map Screenshot
// Captures the tactical map with annotations, measurements, geofence zones,
// and sensor coverage overlays. Exports as PNG with timestamp watermark.
// Hotkey: Ctrl+Shift+P (enhanced) vs P (basic canvas snapshot from war.js)

import { EventBus } from '/lib/events.js';

/**
 * Capture the full tactical area including MapLibre canvas, SVG overlays,
 * annotations, geofence zones, and sensor coverage. Composites everything
 * into a single PNG with a timestamp watermark.
 */
export async function captureEnhancedMapScreenshot() {
    const tacticalArea = document.getElementById('tactical-area');
    if (!tacticalArea) {
        console.error('[Screenshot] No tactical area found');
        EventBus.emit('toast:show', { message: 'No map to capture', type: 'warning' });
        return;
    }

    try {
        EventBus.emit('toast:show', { message: 'Capturing map screenshot...', type: 'info' });

        // Get the MapLibre canvas
        const mapCanvas = tacticalArea.querySelector('canvas.maplibregl-canvas') ||
                          tacticalArea.querySelector('canvas');

        if (!mapCanvas) {
            // Fallback to basic war.js canvas screenshot
            if (typeof window.captureMapSnapshot === 'function') {
                window.captureMapSnapshot();
                return;
            }
            EventBus.emit('toast:show', { message: 'No map canvas found', type: 'warning' });
            return;
        }

        // Create a composite canvas matching the tactical area size
        const rect = tacticalArea.getBoundingClientRect();
        const compositeCanvas = document.createElement('canvas');
        const dpr = window.devicePixelRatio || 1;
        compositeCanvas.width = rect.width * dpr;
        compositeCanvas.height = rect.height * dpr;
        const ctx = compositeCanvas.getContext('2d');
        ctx.scale(dpr, dpr);

        // 1. Draw the base map canvas
        try {
            ctx.drawImage(mapCanvas, 0, 0, rect.width, rect.height);
        } catch (e) {
            console.warn('[Screenshot] Could not draw map canvas (CORS?):', e);
            // Draw a dark background as fallback
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, rect.width, rect.height);
        }

        // 2. Draw SVG overlays (annotations, geofences, sensor coverage)
        const svgElements = tacticalArea.querySelectorAll('svg');
        for (const svg of svgElements) {
            await drawSvgToCanvas(ctx, svg, tacticalArea);
        }

        // 3. Draw HTML overlay elements (markers, labels, popups)
        drawHtmlOverlays(ctx, tacticalArea);

        // 4. Draw geofence zones from store
        await drawGeofenceZones(ctx, rect.width, rect.height);

        // 5. Add timestamp watermark
        drawTimestampWatermark(ctx, rect.width, rect.height);

        // 6. Add classification banner
        drawClassificationBanner(ctx, rect.width);

        // Export as PNG
        const dataUrl = compositeCanvas.toDataURL('image/png');
        const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

        // Show share dialog — download locally or share with other operators
        _showShareDialog(dataUrl, ts, rect.width, rect.height);

    } catch (err) {
        console.error('[Screenshot] Enhanced capture failed:', err);
        EventBus.emit('toast:show', { message: 'Screenshot failed: ' + err.message, type: 'warning' });

        // Fallback to basic screenshot
        if (typeof window.captureMapSnapshot === 'function') {
            window.captureMapSnapshot();
        }
    }
}

/**
 * Draw an SVG element onto the canvas at its position relative to parent.
 */
async function drawSvgToCanvas(ctx, svg, parent) {
    try {
        const svgRect = svg.getBoundingClientRect();
        const parentRect = parent.getBoundingClientRect();
        const x = svgRect.left - parentRect.left;
        const y = svgRect.top - parentRect.top;

        // Serialize SVG to string
        const svgData = new XMLSerializer().serializeToString(svg);
        const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(svgBlob);

        const img = new Image();
        await new Promise((resolve, reject) => {
            img.onload = resolve;
            img.onerror = reject;
            img.src = url;
        });

        ctx.drawImage(img, x, y, svgRect.width, svgRect.height);
        URL.revokeObjectURL(url);
    } catch (e) {
        console.warn('[Screenshot] SVG render failed:', e);
    }
}

/**
 * Draw visible HTML overlay elements (markers, labels) onto canvas.
 */
function drawHtmlOverlays(ctx, parent) {
    const parentRect = parent.getBoundingClientRect();

    // MapLibre markers
    const markers = parent.querySelectorAll('.maplibregl-marker, .map-marker, .target-marker');
    markers.forEach(marker => {
        const mRect = marker.getBoundingClientRect();
        const x = mRect.left - parentRect.left + mRect.width / 2;
        const y = mRect.top - parentRect.top + mRect.height / 2;

        // Draw a simple marker indicator
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fillStyle = getComputedStyle(marker).color || '#00f0ff';
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.5)';
        ctx.lineWidth = 1;
        ctx.stroke();
    });

    // Text labels
    const labels = parent.querySelectorAll('.unit-label, .target-label, .annotation-label');
    labels.forEach(label => {
        const lRect = label.getBoundingClientRect();
        const x = lRect.left - parentRect.left;
        const y = lRect.top - parentRect.top + lRect.height;

        ctx.font = '10px monospace';
        ctx.fillStyle = getComputedStyle(label).color || '#ccc';
        ctx.fillText(label.textContent || '', x, y);
    });
}

/**
 * Draw geofence zones from API data.
 */
async function drawGeofenceZones(ctx, width, height) {
    try {
        const res = await fetch('/api/zones');
        if (!res.ok) return;
        const zones = await res.json();
        if (!zones || zones.length === 0) return;

        // Draw zone indicators in bottom-left
        ctx.font = '9px monospace';
        ctx.fillStyle = 'rgba(255, 42, 109, 0.8)';
        let yOffset = height - 40;
        zones.slice(0, 5).forEach(zone => {
            ctx.fillText(`[ZONE] ${zone.name || zone.id}`, 10, yOffset);
            yOffset -= 12;
        });
    } catch {
        // Zones API not available
    }
}

/**
 * Draw timestamp watermark in bottom-right corner.
 */
function drawTimestampWatermark(ctx, width, height) {
    const now = new Date();
    const ts = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
    const label = `TRITIUM-SC // ${ts}`;

    ctx.font = 'bold 11px monospace';
    const metrics = ctx.measureText(label);
    const padding = 8;
    const boxW = metrics.width + padding * 2;
    const boxH = 18;
    const x = width - boxW - 10;
    const y = height - boxH - 10;

    // Semi-transparent background
    ctx.fillStyle = 'rgba(10, 10, 15, 0.85)';
    ctx.fillRect(x, y, boxW, boxH);

    // Border
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.4)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, y, boxW, boxH);

    // Text
    ctx.fillStyle = '#00f0ff';
    ctx.fillText(label, x + padding, y + 13);
}

/**
 * Draw classification banner at top of image.
 */
function drawClassificationBanner(ctx, width) {
    const label = 'UNCLASSIFIED // FOR TRAINING USE ONLY';
    ctx.font = 'bold 9px monospace';
    const metrics = ctx.measureText(label);
    const x = (width - metrics.width) / 2;

    // Background bar
    ctx.fillStyle = 'rgba(10, 10, 15, 0.7)';
    ctx.fillRect(0, 0, width, 16);

    // Text
    ctx.fillStyle = 'rgba(252, 238, 10, 0.7)';
    ctx.fillText(label, x, 11);
}

/**
 * Show a dialog offering to download or share the screenshot.
 */
function _showShareDialog(dataUrl, ts, width, height) {
    // Remove any existing dialog
    const old = document.getElementById('screenshot-share-dialog');
    if (old) old.remove();

    const dialog = document.createElement('div');
    dialog.id = 'screenshot-share-dialog';
    dialog.style.cssText = `
        position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: #0e0e14; border: 1px solid rgba(0,240,255,0.3);
        padding: 20px; border-radius: 4px; z-index: 10000;
        min-width: 320px; font-family: monospace; color: #ccc;
        box-shadow: 0 0 30px rgba(0,240,255,0.1);
    `;

    // Thumbnail preview
    const preview = document.createElement('img');
    preview.src = dataUrl;
    preview.style.cssText = 'width:100%;max-height:180px;object-fit:contain;border:1px solid #1a1a2e;margin-bottom:12px;';

    const title = document.createElement('div');
    title.textContent = 'MAP SCREENSHOT';
    title.style.cssText = 'color:#00f0ff;font-size:12px;font-weight:bold;margin-bottom:12px;';

    // Description input
    const descLabel = document.createElement('div');
    descLabel.textContent = 'DESCRIPTION';
    descLabel.style.cssText = 'font-size:9px;color:#666;margin-bottom:4px;';

    const descInput = document.createElement('input');
    descInput.type = 'text';
    descInput.placeholder = 'Optional description...';
    descInput.style.cssText = `
        width:100%;box-sizing:border-box;background:#12121a;border:1px solid #1a1a2e;
        color:#ccc;padding:6px 8px;font-family:monospace;font-size:11px;
        margin-bottom:12px;outline:none;
    `;

    // Buttons
    const btnRow = document.createElement('div');
    btnRow.style.cssText = 'display:flex;gap:8px;';

    const downloadBtn = document.createElement('button');
    downloadBtn.textContent = 'DOWNLOAD';
    downloadBtn.style.cssText = `
        flex:1;background:#1a1a2e;border:1px solid rgba(0,240,255,0.3);
        color:#00f0ff;padding:8px;cursor:pointer;font-family:monospace;font-size:11px;
    `;
    downloadBtn.onclick = () => {
        const link = document.createElement('a');
        link.download = `tritium-tactical-${ts}.png`;
        link.href = dataUrl;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        dialog.remove();
        EventBus.emit('toast:show', { message: `Downloaded: tritium-tactical-${ts}.png`, type: 'info' });
    };

    const shareBtn = document.createElement('button');
    shareBtn.textContent = 'SHARE';
    shareBtn.style.cssText = `
        flex:1;background:#1a1a2e;border:1px solid rgba(5,255,161,0.3);
        color:#05ffa1;padding:8px;cursor:pointer;font-family:monospace;font-size:11px;
    `;
    shareBtn.onclick = async () => {
        shareBtn.textContent = 'SHARING...';
        shareBtn.disabled = true;
        try {
            const resp = await fetch('/api/screenshots/base64', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    png_base64: dataUrl,
                    operator: window._tritiumOperator || 'operator',
                    description: descInput.value || `Tactical screenshot ${ts}`,
                    width: width,
                    height: height,
                }),
            });
            if (resp.ok) {
                const meta = await resp.json();
                EventBus.emit('toast:show', {
                    message: `Screenshot shared (${meta.screenshot_id.slice(0, 8)})`,
                    type: 'info',
                });
            } else {
                EventBus.emit('toast:show', { message: 'Share failed: ' + resp.statusText, type: 'warning' });
            }
        } catch (err) {
            EventBus.emit('toast:show', { message: 'Share failed: ' + err.message, type: 'warning' });
        }
        dialog.remove();
    };

    const cancelBtn = document.createElement('button');
    cancelBtn.textContent = 'CANCEL';
    cancelBtn.style.cssText = `
        flex:1;background:#1a1a2e;border:1px solid rgba(255,42,109,0.3);
        color:#ff2a6d;padding:8px;cursor:pointer;font-family:monospace;font-size:11px;
    `;
    cancelBtn.onclick = () => dialog.remove();

    btnRow.appendChild(downloadBtn);
    btnRow.appendChild(shareBtn);
    btnRow.appendChild(cancelBtn);

    dialog.appendChild(title);
    dialog.appendChild(preview);
    dialog.appendChild(descLabel);
    dialog.appendChild(descInput);
    dialog.appendChild(btnRow);
    document.body.appendChild(dialog);

    // Auto-focus description
    descInput.focus();

    // Close on Escape
    const onKey = (e) => {
        if (e.key === 'Escape') {
            dialog.remove();
            document.removeEventListener('keydown', onKey);
        }
    };
    document.addEventListener('keydown', onKey);
}

/**
 * Initialize the enhanced screenshot hotkey (Ctrl+Shift+P).
 * Does not conflict with the existing P key (battle-stats toggle).
 */
export function initScreenshotHotkey() {
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && (e.key === 'p' || e.key === 'P')) {
            e.preventDefault();
            captureEnhancedMapScreenshot();
        }
    });
}
