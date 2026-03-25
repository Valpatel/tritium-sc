// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Heatmap Timeline Panel
// Temporal playback of target density heatmaps. Slide through time to see
// how activity patterns change over hours or days. Fetches time-bucketed
// heatmap snapshots and animates through them.

import { EventBus } from '/lib/events.js';
import { _esc, _fetchJson } from '/lib/utils.js';

const LAYERS = [
    { id: 'all', label: 'ALL ACTIVITY' },
    { id: 'ble_activity', label: 'BLE SIGHTINGS' },
    { id: 'camera_activity', label: 'CAMERA DETECTIONS' },
    { id: 'motion_activity', label: 'MOTION SENSORS' },
];

const SPAN_PRESETS = [
    { label: '1H', hours: 1, buckets: 12 },
    { label: '6H', hours: 6, buckets: 24 },
    { label: '24H', hours: 24, buckets: 48 },
    { label: '7D', hours: 168, buckets: 56 },
];

// Color gradient: intensity 0..1 -> RGBA
function intensityToColor(t, opacity) {
    if (t <= 0) return [0, 0, 0, 0];
    const a = Math.round(opacity * 255 * Math.min(t * 3, 1.0));
    let r, g, b;
    if (t < 0.33) {
        const f = t / 0.33;
        r = 0; g = Math.round(240 * f); b = Math.round(255 * f);
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

function formatTimestamp(ts) {
    const d = new Date(ts * 1000);
    const hh = String(d.getHours()).padStart(2, '0');
    const mm = String(d.getMinutes()).padStart(2, '0');
    const mon = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${mon}/${day} ${hh}:${mm}`;
}

export const HeatmapTimelinePanelDef = {
    id: 'heatmap-timeline',
    title: 'HEATMAP TIMELINE',
    defaultPosition: { x: 8, y: 400 },
    defaultSize: { w: 340, h: 420 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'heatmap-tl-inner';
        el.innerHTML = `
            <div class="heatmap-controls">
                <div class="heatmap-row">
                    <label class="heatmap-label">LAYER</label>
                    <select class="heatmap-select" data-bind="layer">
                        ${LAYERS.map(l => `<option value="${l.id}">${_esc(l.label)}</option>`).join('')}
                    </select>
                </div>
                <div class="heatmap-row">
                    <label class="heatmap-label">SPAN</label>
                    <div class="heatmap-window-btns" data-bind="span-btns">
                        ${SPAN_PRESETS.map((s, i) => `<button class="heatmap-window-btn${i === 2 ? ' active' : ''}" data-span="${i}">${s.label}</button>`).join('')}
                    </div>
                </div>
                <div class="heatmap-row">
                    <label class="heatmap-label">OPACITY</label>
                    <input type="range" class="heatmap-slider" data-bind="opacity" min="0" max="100" value="70" />
                    <span class="heatmap-value" data-bind="opacity-val">70%</span>
                </div>
            </div>
            <div class="heatmap-tl-transport" style="display:flex;align-items:center;gap:6px;padding:4px 8px">
                <button class="panel-action-btn" data-action="play" title="Play/Pause" style="font-size:0.6rem;padding:2px 8px">&#9654;</button>
                <button class="panel-action-btn" data-action="step-back" title="Previous frame" style="font-size:0.5rem;padding:2px 6px">&lt;</button>
                <input type="range" class="heatmap-slider" data-bind="timeline" min="0" max="47" value="0" style="flex:1" />
                <button class="panel-action-btn" data-action="step-fwd" title="Next frame" style="font-size:0.5rem;padding:2px 6px">&gt;</button>
                <span class="heatmap-value mono" data-bind="frame-label" style="min-width:80px;text-align:right;font-size:0.5rem">--</span>
            </div>
            <div class="heatmap-status" data-bind="status" style="font-size:0.5rem;padding:2px 8px;color:var(--text-ghost)">Ready</div>
            <canvas class="heatmap-preview" data-bind="preview" width="256" height="256" style="width:100%;image-rendering:pixelated"></canvas>
            <div class="heatmap-tl-sparkline" data-bind="sparkline" style="height:32px;padding:0 8px;position:relative">
                <canvas data-bind="sparkline-canvas" width="320" height="32" style="width:100%;height:100%"></canvas>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const layerSelect = bodyEl.querySelector('[data-bind="layer"]');
        const spanBtns = bodyEl.querySelector('[data-bind="span-btns"]');
        const opacitySlider = bodyEl.querySelector('[data-bind="opacity"]');
        const opacityVal = bodyEl.querySelector('[data-bind="opacity-val"]');
        const timelineSlider = bodyEl.querySelector('[data-bind="timeline"]');
        const frameLabelEl = bodyEl.querySelector('[data-bind="frame-label"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const canvas = bodyEl.querySelector('[data-bind="preview"]');
        const ctx = canvas ? canvas.getContext('2d') : null;
        const sparkCanvas = bodyEl.querySelector('[data-bind="sparkline-canvas"]');
        const sparkCtx = sparkCanvas ? sparkCanvas.getContext('2d') : null;
        const playBtn = bodyEl.querySelector('[data-action="play"]');
        const stepBackBtn = bodyEl.querySelector('[data-action="step-back"]');
        const stepFwdBtn = bodyEl.querySelector('[data-action="step-fwd"]');

        let currentLayer = 'all';
        let currentSpanIdx = 2; // 24H default
        let currentOpacity = 0.7;
        let frames = []; // Array of { timestamp, grid, resolution, max_value, event_count }
        let currentFrame = 0;
        let playing = false;
        let playTimer = null;
        let globalMax = 1;

        // Layer select
        if (layerSelect) {
            layerSelect.addEventListener('change', () => {
                currentLayer = layerSelect.value;
                fetchTimeline();
            });
        }

        // Span buttons
        if (spanBtns) {
            for (const btn of spanBtns.querySelectorAll('.heatmap-window-btn')) {
                btn.addEventListener('click', () => {
                    currentSpanIdx = parseInt(btn.dataset.span, 10);
                    for (const b of spanBtns.querySelectorAll('.heatmap-window-btn')) {
                        b.classList.toggle('active', b === btn);
                    }
                    fetchTimeline();
                });
            }
        }

        // Opacity
        if (opacitySlider) {
            opacitySlider.addEventListener('input', () => {
                currentOpacity = parseInt(opacitySlider.value, 10) / 100;
                if (opacityVal) opacityVal.textContent = `${opacitySlider.value}%`;
                renderFrame(currentFrame);
            });
        }

        // Timeline scrub
        if (timelineSlider) {
            timelineSlider.addEventListener('input', () => {
                currentFrame = parseInt(timelineSlider.value, 10);
                renderFrame(currentFrame);
            });
        }

        // Transport controls
        if (playBtn) {
            playBtn.addEventListener('click', () => {
                playing = !playing;
                playBtn.innerHTML = playing ? '&#9646;&#9646;' : '&#9654;';
                if (playing) startPlayback();
                else stopPlayback();
            });
        }

        if (stepBackBtn) {
            stepBackBtn.addEventListener('click', () => {
                if (frames.length === 0) return;
                currentFrame = Math.max(0, currentFrame - 1);
                if (timelineSlider) timelineSlider.value = currentFrame;
                renderFrame(currentFrame);
            });
        }

        if (stepFwdBtn) {
            stepFwdBtn.addEventListener('click', () => {
                if (frames.length === 0) return;
                currentFrame = Math.min(frames.length - 1, currentFrame + 1);
                if (timelineSlider) timelineSlider.value = currentFrame;
                renderFrame(currentFrame);
            });
        }

        function startPlayback() {
            stopPlayback();
            playTimer = setInterval(() => {
                if (frames.length === 0) return;
                currentFrame = (currentFrame + 1) % frames.length;
                if (timelineSlider) timelineSlider.value = currentFrame;
                renderFrame(currentFrame);
            }, 500);
        }

        function stopPlayback() {
            if (playTimer) {
                clearInterval(playTimer);
                playTimer = null;
            }
        }

        async function fetchTimeline() {
            if (statusEl) statusEl.textContent = 'Loading timeline...';
            stopPlayback();
            playing = false;
            if (playBtn) playBtn.innerHTML = '&#9654;';

            const preset = SPAN_PRESETS[currentSpanIdx];
            const endTs = Math.floor(Date.now() / 1000);
            const startTs = endTs - preset.hours * 3600;
            const bucketSize = Math.floor((preset.hours * 3600) / preset.buckets);

            try {
                // Fetch time-bucketed heatmap data
                const params = new URLSearchParams({
                    layer: currentLayer,
                    start: String(startTs),
                    end: String(endTs),
                    buckets: String(preset.buckets),
                    resolution: '30',
                });
                const resp = await fetch(`/api/heatmap/timeline?${params}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                if (data.frames && data.frames.length > 0) {
                    frames = data.frames;
                    globalMax = data.global_max || 1;
                } else {
                    // Fallback: generate synthetic empty frames
                    frames = [];
                    for (let i = 0; i < preset.buckets; i++) {
                        frames.push({
                            timestamp: startTs + i * bucketSize,
                            grid: [],
                            resolution: 30,
                            max_value: 0,
                            event_count: 0,
                        });
                    }
                    globalMax = 1;
                }

                currentFrame = 0;
                if (timelineSlider) {
                    timelineSlider.max = String(frames.length - 1);
                    timelineSlider.value = '0';
                }
                if (statusEl) statusEl.textContent = `${frames.length} frames | ${preset.label} span`;
                renderFrame(0);
                renderSparkline();
            } catch (err) {
                // If API not available, generate placeholder frames
                frames = [];
                const bucketSizeSec = Math.floor((preset.hours * 3600) / preset.buckets);
                for (let i = 0; i < preset.buckets; i++) {
                    frames.push({
                        timestamp: startTs + i * bucketSizeSec,
                        grid: [],
                        resolution: 30,
                        max_value: 0,
                        event_count: 0,
                    });
                }
                globalMax = 1;
                currentFrame = 0;
                if (timelineSlider) {
                    timelineSlider.max = String(frames.length - 1);
                    timelineSlider.value = '0';
                }
                if (statusEl) statusEl.textContent = `No data (${err.message})`;
                renderFrame(0);
                renderSparkline();
            }
        }

        function renderFrame(idx) {
            if (idx < 0 || idx >= frames.length) return;
            const frame = frames[idx];

            // Update frame label
            if (frameLabelEl) {
                frameLabelEl.textContent = formatTimestamp(frame.timestamp);
            }

            // Emit to map overlay
            EventBus.emit('heatmap:update', {
                opacity: currentOpacity,
                data: frame,
                timestamp: frame.timestamp,
            });

            // Render preview canvas
            if (!ctx) return;
            const res = frame.resolution || 30;
            const cellW = canvas.width / res;
            const cellH = canvas.height / res;

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            if (frame.grid && frame.grid.length > 0) {
                for (let row = 0; row < res && row < frame.grid.length; row++) {
                    for (let col = 0; col < res && col < (frame.grid[row] || []).length; col++) {
                        const val = frame.grid[row][col];
                        if (val <= 0) continue;
                        const t = Math.min(val / globalMax, 1.0);
                        const [r, g, b, a] = intensityToColor(t, currentOpacity);
                        ctx.fillStyle = `rgba(${r},${g},${b},${a / 255})`;
                        ctx.fillRect(col * cellW, (res - 1 - row) * cellH, cellW + 0.5, cellH + 0.5);
                    }
                }
            }

            // Border
            ctx.strokeStyle = '#00f0ff33';
            ctx.lineWidth = 1;
            ctx.strokeRect(0, 0, canvas.width, canvas.height);

            // Highlight current frame on sparkline
            renderSparkline();
        }

        function renderSparkline() {
            if (!sparkCtx || frames.length === 0) return;
            const w = sparkCanvas.width;
            const h = sparkCanvas.height;
            sparkCtx.clearRect(0, 0, w, h);

            // Background
            sparkCtx.fillStyle = '#0e0e14';
            sparkCtx.fillRect(0, 0, w, h);

            // Bar chart of event_count per frame
            const maxEvents = Math.max(1, ...frames.map(f => f.event_count || 0));
            const barW = w / frames.length;

            for (let i = 0; i < frames.length; i++) {
                const count = frames[i].event_count || 0;
                const barH = (count / maxEvents) * (h - 2);
                const isCurrent = i === currentFrame;

                if (isCurrent) {
                    sparkCtx.fillStyle = '#00f0ff';
                } else {
                    const intensity = count / maxEvents;
                    sparkCtx.fillStyle = intensity > 0.66 ? '#ff2a6d88' :
                                         intensity > 0.33 ? '#fcee0a88' : '#00f0ff44';
                }
                sparkCtx.fillRect(i * barW, h - barH - 1, Math.max(barW - 1, 1), barH);
            }

            // Current frame marker line
            const markerX = currentFrame * barW + barW / 2;
            sparkCtx.strokeStyle = '#00f0ff';
            sparkCtx.lineWidth = 1;
            sparkCtx.beginPath();
            sparkCtx.moveTo(markerX, 0);
            sparkCtx.lineTo(markerX, h);
            sparkCtx.stroke();
        }

        // Initial fetch
        fetchTimeline();

        return () => {
            stopPlayback();
        };
    },
};
