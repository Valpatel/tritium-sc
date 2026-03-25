// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Heatmap Panel
// Canvas overlay on the tactical map rendering activity heatmap.
// Color gradient: transparent (no activity) -> cyan (low) -> yellow (medium) -> magenta (high)
// Controls: layer selector, time window slider, opacity slider, auto-refresh.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

// Time window presets (minutes)
const TIME_WINDOWS = [
    { label: '15 MIN', value: 15 },
    { label: '1 HOUR', value: 60 },
    { label: '6 HOURS', value: 360 },
    { label: '24 HOURS', value: 1440 },
];

const LAYERS = [
    { id: 'all', label: 'ALL ACTIVITY' },
    { id: 'ble_activity', label: 'BLE SIGHTINGS' },
    { id: 'camera_activity', label: 'CAMERA DETECTIONS' },
    { id: 'motion_activity', label: 'MOTION SENSORS' },
];

// Color gradient stops: intensity 0..1 -> RGBA
function intensityToColor(t, opacity) {
    // 0.0 = transparent
    // 0.0-0.33 = transparent -> cyan (#00f0ff)
    // 0.33-0.66 = cyan -> yellow (#fcee0a)
    // 0.66-1.0 = yellow -> magenta (#ff2a6d)
    if (t <= 0) return [0, 0, 0, 0];
    const a = Math.round(opacity * 255 * Math.min(t * 3, 1.0));
    let r, g, b;
    if (t < 0.33) {
        const f = t / 0.33;
        r = 0;
        g = Math.round(240 * f);
        b = Math.round(255 * f);
    } else if (t < 0.66) {
        const f = (t - 0.33) / 0.33;
        r = Math.round(252 * f);
        g = Math.round(240 + (238 - 240) * f);
        b = Math.round(255 * (1 - f) + 10 * f);
    } else {
        const f = (t - 0.66) / 0.34;
        r = Math.round(252 + (255 - 252) * f);
        g = Math.round(238 * (1 - f) + 42 * f);
        b = Math.round(10 + (109 - 10) * f);
    }
    return [r, g, b, a];
}

export const HeatmapPanelDef = {
    id: 'heatmap',
    title: 'HEATMAP',
    defaultPosition: { x: 8, y: 360 },
    defaultSize: { w: 280, h: 340 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'heatmap-panel-inner';
        el.innerHTML = `
            <div class="heatmap-controls">
                <div class="heatmap-row">
                    <label class="heatmap-label">LAYER</label>
                    <select class="heatmap-select" data-bind="layer">
                        ${LAYERS.map(l => `<option value="${l.id}">${_esc(l.label)}</option>`).join('')}
                    </select>
                </div>
                <div class="heatmap-row">
                    <label class="heatmap-label">WINDOW</label>
                    <div class="heatmap-window-btns" data-bind="window-btns">
                        ${TIME_WINDOWS.map(tw => `<button class="heatmap-window-btn${tw.value === 60 ? ' active' : ''}" data-window="${tw.value}">${tw.label}</button>`).join('')}
                    </div>
                </div>
                <div class="heatmap-row">
                    <label class="heatmap-label">OPACITY</label>
                    <input type="range" class="heatmap-slider" data-bind="opacity" min="0" max="100" value="70" />
                    <span class="heatmap-value" data-bind="opacity-val">70%</span>
                </div>
                <div class="heatmap-row">
                    <label class="heatmap-label">RESOLUTION</label>
                    <input type="range" class="heatmap-slider" data-bind="resolution" min="10" max="100" value="50" step="5" />
                    <span class="heatmap-value" data-bind="res-val">50</span>
                </div>
            </div>
            <div class="heatmap-status" data-bind="status">Idle</div>
            <canvas class="heatmap-preview" data-bind="preview" width="256" height="256"></canvas>
        `;
        return el;
    },

    mount(bodyEl, _panel) {
        const layerSelect = bodyEl.querySelector('[data-bind="layer"]');
        const windowBtns = bodyEl.querySelector('[data-bind="window-btns"]');
        const opacitySlider = bodyEl.querySelector('[data-bind="opacity"]');
        const opacityVal = bodyEl.querySelector('[data-bind="opacity-val"]');
        const resSlider = bodyEl.querySelector('[data-bind="resolution"]');
        const resVal = bodyEl.querySelector('[data-bind="res-val"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const canvas = bodyEl.querySelector('[data-bind="preview"]');
        const ctx = canvas ? canvas.getContext('2d') : null;

        let currentLayer = 'all';
        let currentWindow = 60;
        let currentOpacity = 0.7;
        let currentResolution = 50;
        let refreshTimer = null;
        let lastData = null;

        // Layer select
        if (layerSelect) {
            layerSelect.addEventListener('change', () => {
                currentLayer = layerSelect.value;
                fetchHeatmap();
            });
        }

        // Window buttons
        if (windowBtns) {
            for (const btn of windowBtns.querySelectorAll('.heatmap-window-btn')) {
                btn.addEventListener('click', () => {
                    currentWindow = parseInt(btn.dataset.window, 10);
                    for (const b of windowBtns.querySelectorAll('.heatmap-window-btn')) {
                        b.classList.toggle('active', b === btn);
                    }
                    fetchHeatmap();
                });
            }
        }

        // Opacity slider
        if (opacitySlider) {
            opacitySlider.addEventListener('input', () => {
                currentOpacity = parseInt(opacitySlider.value, 10) / 100;
                if (opacityVal) opacityVal.textContent = `${opacitySlider.value}%`;
                if (lastData) renderPreview(lastData);
                EventBus.emit('heatmap:update', { opacity: currentOpacity, data: lastData });
            });
        }

        // Resolution slider
        if (resSlider) {
            resSlider.addEventListener('input', () => {
                currentResolution = parseInt(resSlider.value, 10);
                if (resVal) resVal.textContent = `${currentResolution}`;
            });
            resSlider.addEventListener('change', () => {
                fetchHeatmap();
            });
        }

        async function fetchHeatmap() {
            if (statusEl) statusEl.textContent = 'Fetching...';
            try {
                const params = new URLSearchParams({
                    layer: currentLayer,
                    window: String(currentWindow),
                    resolution: String(currentResolution),
                });
                const resp = await fetch(`/api/heatmap?${params}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                lastData = await resp.json();
                if (statusEl) {
                    statusEl.textContent = `${lastData.event_count} events | peak ${lastData.max_value.toFixed(1)}`;
                }
                renderPreview(lastData);
                EventBus.emit('heatmap:update', { opacity: currentOpacity, data: lastData });
            } catch (err) {
                if (statusEl) statusEl.textContent = `Error: ${err.message}`;
            }
        }

        function renderPreview(data) {
            if (!ctx || !data || !data.grid) return;
            const res = data.resolution;
            const cellW = canvas.width / res;
            const cellH = canvas.height / res;
            const maxVal = data.max_value || 1;

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Dark background
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            for (let row = 0; row < res; row++) {
                for (let col = 0; col < res; col++) {
                    const val = data.grid[row][col];
                    if (val <= 0) continue;
                    const t = Math.min(val / maxVal, 1.0);
                    const [r, g, b, a] = intensityToColor(t, currentOpacity);
                    ctx.fillStyle = `rgba(${r},${g},${b},${a / 255})`;
                    // Flip Y so row 0 is bottom (south)
                    ctx.fillRect(col * cellW, (res - 1 - row) * cellH, cellW + 0.5, cellH + 0.5);
                }
            }

            // Border
            ctx.strokeStyle = '#00f0ff33';
            ctx.lineWidth = 1;
            ctx.strokeRect(0, 0, canvas.width, canvas.height);
        }

        // Auto-refresh every 30s
        fetchHeatmap();
        refreshTimer = setInterval(fetchHeatmap, 30000);

        return () => {
            if (refreshTimer) clearInterval(refreshTimer);
        };
    },
};
