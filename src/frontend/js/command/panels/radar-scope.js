// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Radar PPI (Plan Position Indicator) Scope Panel
// Classic circular radar display with rotating sweep line, range rings,
// cardinal directions, and live track dots with trails.
// Fetches from /api/radar/tracks every 1s. Canvas 2D rendered.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

// ============================================================
// Constants
// ============================================================

const CYAN = '#00f0ff';
const GREEN = '#05ffa1';
const RED = '#ff2a6d';
const YELLOW = '#fcee0a';
const DIM = '#334';
const BG = '#0a0a0f';
const TEXT_DIM = '#556';

const SWEEP_PERIOD_MS = 3000;  // full rotation time
const FETCH_INTERVAL_MS = 1000;
const TRAIL_LENGTH = 10;

const RANGE_PRESETS = [5000, 10000, 20000, 50000];  // meters
const RANGE_LABELS = ['5 km', '10 km', '20 km', '50 km'];

const ALLIANCE_COLORS = {
    friendly: GREEN,
    hostile: RED,
    unknown: CYAN,
};

const CLASS_ICONS = {
    vehicle: 'V',
    aircraft: 'A',
    uav: 'U',
    person: 'P',
    ship: 'S',
    animal: 'a',
};

// ============================================================
// Helpers
// ============================================================

function degToRad(deg) {
    return deg * Math.PI / 180;
}

function formatRange(m) {
    if (m >= 1000) return (m / 1000).toFixed(1) + ' km';
    return m.toFixed(0) + ' m';
}

function formatVelocity(mps) {
    return mps.toFixed(1) + ' m/s';
}

// ============================================================
// Panel Definition
// ============================================================

export const RadarScopePanelDef = {
    id: 'radar-scope',
    title: 'RADAR PPI SCOPE',
    defaultPosition: { x: 60, y: 60 },
    defaultSize: { w: 520, h: 600 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'radar-scope-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;background:' + BG + ';overflow:hidden;';

        el.innerHTML = `
            <div class="radar-scope-header" style="display:flex;align-items:center;justify-content:space-between;padding:4px 8px;border-bottom:1px solid ${DIM};flex-shrink:0;font-family:monospace;font-size:11px;">
                <div style="display:flex;gap:12px;align-items:center;">
                    <span data-bind="status" style="color:${GREEN};font-weight:bold;">ACTIVE</span>
                    <span style="color:${TEXT_DIM};">TRACKS:</span>
                    <span data-bind="track-count" style="color:${CYAN};">0</span>
                </div>
                <div style="display:flex;gap:12px;align-items:center;">
                    <span style="color:${TEXT_DIM};">UPDATED:</span>
                    <span data-bind="last-update" style="color:${TEXT_DIM};">--</span>
                </div>
            </div>
            <div class="radar-scope-controls" style="display:flex;align-items:center;gap:8px;padding:4px 8px;border-bottom:1px solid ${DIM};flex-shrink:0;font-family:monospace;font-size:10px;">
                <span style="color:${TEXT_DIM};">RANGE:</span>
                <select data-bind="range-select" style="background:#12121a;color:${CYAN};border:1px solid ${DIM};font-family:monospace;font-size:10px;padding:1px 4px;cursor:pointer;">
                    <option value="5000">5 km</option>
                    <option value="10000">10 km</option>
                    <option value="20000" selected>20 km</option>
                    <option value="50000">50 km</option>
                </select>
                <span style="color:${TEXT_DIM};margin-left:8px;">FILTER:</span>
                <select data-bind="filter-select" style="background:#12121a;color:${CYAN};border:1px solid ${DIM};font-family:monospace;font-size:10px;padding:1px 4px;cursor:pointer;">
                    <option value="all">ALL</option>
                    <option value="hostile">HOSTILE</option>
                    <option value="unknown">UNKNOWN</option>
                    <option value="friendly">FRIENDLY</option>
                </select>
            </div>
            <div class="radar-scope-canvas-wrap" style="flex:1;min-height:0;position:relative;">
                <canvas data-bind="canvas" style="width:100%;height:100%;display:block;"></canvas>
                <div data-bind="tooltip" style="display:none;position:absolute;background:#12121a;border:1px solid ${CYAN};padding:6px 10px;font-family:monospace;font-size:10px;color:${CYAN};pointer-events:none;z-index:10;white-space:nowrap;box-shadow:0 0 8px rgba(0,240,255,0.3);"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const canvas = bodyEl.querySelector('[data-bind="canvas"]');
        const tooltip = bodyEl.querySelector('[data-bind="tooltip"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const trackCountEl = bodyEl.querySelector('[data-bind="track-count"]');
        const lastUpdateEl = bodyEl.querySelector('[data-bind="last-update"]');
        const rangeSelect = bodyEl.querySelector('[data-bind="range-select"]');
        const filterSelect = bodyEl.querySelector('[data-bind="filter-select"]');
        const ctx = canvas.getContext('2d');

        let maxRange = 20000;  // meters
        let trackFilter = 'all';
        let tracks = [];
        let trailHistory = {};  // track_id -> array of {range_m, azimuth_deg}
        let sweepAngle = 0;
        let animFrameId = null;
        let fetchTimerId = null;
        let lastFetchTime = 0;
        let hoveredTrack = null;
        let destroyed = false;

        // -- Range/Filter controls --
        rangeSelect.addEventListener('change', () => {
            maxRange = parseInt(rangeSelect.value, 10);
        });
        filterSelect.addEventListener('change', () => {
            trackFilter = filterSelect.value;
        });

        // -- Canvas sizing --
        function resizeCanvas() {
            const rect = canvas.parentElement.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        }
        resizeCanvas();

        const resizeObs = new ResizeObserver(() => {
            if (destroyed) return;
            resizeCanvas();
        });
        resizeObs.observe(canvas.parentElement);

        // -- Coordinate conversion --
        function trackToCanvas(range_m, azimuth_deg, cx, cy, radius) {
            // Azimuth: 0=North (up), clockwise
            const r = (range_m / maxRange) * radius;
            const angle = degToRad(azimuth_deg) - Math.PI / 2;  // rotate so 0=up
            // In canvas coords: 0 deg = up = -PI/2
            const rad = degToRad(azimuth_deg - 90);
            const x = cx + r * Math.cos(rad);
            const y = cy + r * Math.sin(rad);
            return { x, y, r };
        }

        // -- Hit testing for hover --
        function findTrackAt(mx, my, cx, cy, radius) {
            const HIT_RADIUS = 8;
            for (const t of tracks) {
                if (trackFilter !== 'all' && (t.alliance || 'unknown') !== trackFilter) continue;
                if (t.range_m > maxRange) continue;
                const pos = trackToCanvas(t.range_m, t.azimuth_deg, cx, cy, radius);
                const dx = mx - pos.x;
                const dy = my - pos.y;
                if (dx * dx + dy * dy < HIT_RADIUS * HIT_RADIUS) return t;
            }
            return null;
        }

        // -- Mouse move for tooltip --
        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;
            const w = rect.width;
            const h = rect.height;
            const size = Math.min(w, h);
            const cx = w / 2;
            const cy = h / 2;
            const radius = size * 0.42;

            const t = findTrackAt(mx, my, cx, cy, radius);
            if (t) {
                hoveredTrack = t;
                const alliance = t.alliance || 'unknown';
                const color = ALLIANCE_COLORS[alliance] || CYAN;
                tooltip.style.display = 'block';
                tooltip.style.left = (mx + 12) + 'px';
                tooltip.style.top = (my - 8) + 'px';
                tooltip.style.borderColor = color;
                tooltip.innerHTML = [
                    `<div style="color:${color};font-weight:bold;">${_esc(t.track_id)} [${_esc(t.classification || 'unknown').toUpperCase()}]</div>`,
                    `<div>RANGE: ${formatRange(t.range_m)}</div>`,
                    `<div>AZ: ${t.azimuth_deg.toFixed(1)}\u00b0</div>`,
                    `<div>VEL: ${formatVelocity(t.velocity_mps)}</div>`,
                    `<div>RCS: ${t.rcs_dbsm.toFixed(1)} dBsm</div>`,
                    `<div>CONF: ${(t.confidence * 100).toFixed(0)}%</div>`,
                ].join('');
            } else {
                hoveredTrack = null;
                tooltip.style.display = 'none';
            }
        });

        canvas.addEventListener('mouseleave', () => {
            hoveredTrack = null;
            tooltip.style.display = 'none';
        });

        // -- Data fetch --
        async function fetchTracks() {
            if (destroyed) return;
            try {
                const res = await fetch('/api/radar/tracks?limit=200');
                if (res.ok) {
                    const data = await res.json();
                    tracks = data.tracks || [];
                    lastFetchTime = Date.now();

                    // Update trail history
                    for (const t of tracks) {
                        const tid = t.track_id;
                        if (trailHistory[tid] === undefined) {
                            trailHistory[tid] = [];
                        }
                        const trail = trailHistory[tid];
                        trail.push({ range_m: t.range_m, azimuth_deg: t.azimuth_deg });
                        if (trail.length > TRAIL_LENGTH) {
                            trail.shift();
                        }
                    }

                    // Prune old trails
                    const activeTids = new Set(tracks.map(t => t.track_id));
                    for (const tid of Object.keys(trailHistory)) {
                        if (!activeTids.has(tid)) {
                            delete trailHistory[tid];
                        }
                    }

                    // Update header
                    if (trackCountEl) trackCountEl.textContent = tracks.length;
                    if (lastUpdateEl) lastUpdateEl.textContent = new Date().toLocaleTimeString();
                    if (statusEl) {
                        statusEl.textContent = 'ACTIVE';
                        statusEl.style.color = GREEN;
                    }
                } else {
                    if (statusEl) {
                        statusEl.textContent = 'STANDBY';
                        statusEl.style.color = YELLOW;
                    }
                }
            } catch (_err) {
                if (statusEl) {
                    statusEl.textContent = 'OFFLINE';
                    statusEl.style.color = RED;
                }
            }
        }

        fetchTracks();
        fetchTimerId = setInterval(fetchTracks, FETCH_INTERVAL_MS);

        // -- Render loop --
        function render(timestamp) {
            if (destroyed) return;

            const w = canvas.width / (window.devicePixelRatio || 1);
            const h = canvas.height / (window.devicePixelRatio || 1);
            if (w === 0 || h === 0) {
                animFrameId = requestAnimationFrame(render);
                return;
            }

            const size = Math.min(w, h);
            const cx = w / 2;
            const cy = h / 2;
            const radius = size * 0.42;

            // Update sweep angle
            sweepAngle = ((timestamp % SWEEP_PERIOD_MS) / SWEEP_PERIOD_MS) * 360;

            ctx.clearRect(0, 0, w, h);

            // -- Background --
            ctx.fillStyle = BG;
            ctx.fillRect(0, 0, w, h);

            // -- Scope circle (outer boundary) --
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.strokeStyle = CYAN;
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Dim fill inside scope
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.fillStyle = '#0c0c14';
            ctx.fill();

            // -- Range rings --
            const ringCount = 4;
            ctx.setLineDash([2, 4]);
            for (let i = 1; i <= ringCount; i++) {
                const ringR = (i / ringCount) * radius;
                const ringRange = (i / ringCount) * maxRange;
                ctx.beginPath();
                ctx.arc(cx, cy, ringR, 0, Math.PI * 2);
                ctx.strokeStyle = DIM;
                ctx.lineWidth = 0.7;
                ctx.stroke();

                // Range label
                ctx.fillStyle = TEXT_DIM;
                ctx.font = '9px monospace';
                ctx.textAlign = 'center';
                ctx.fillText(formatRange(ringRange), cx, cy - ringR - 3);
            }
            ctx.setLineDash([]);

            // -- Cross hairs (N-S, E-W lines) --
            ctx.beginPath();
            ctx.moveTo(cx, cy - radius);
            ctx.lineTo(cx, cy + radius);
            ctx.moveTo(cx - radius, cy);
            ctx.lineTo(cx + radius, cy);
            ctx.strokeStyle = DIM;
            ctx.lineWidth = 0.5;
            ctx.stroke();

            // -- Cardinal labels --
            ctx.fillStyle = TEXT_DIM;
            ctx.font = 'bold 11px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';
            ctx.fillText('N', cx, cy - radius - 6);
            ctx.textBaseline = 'top';
            ctx.fillText('S', cx, cy + radius + 6);
            ctx.textBaseline = 'middle';
            ctx.textAlign = 'left';
            ctx.fillText('E', cx + radius + 6, cy);
            ctx.textAlign = 'right';
            ctx.fillText('W', cx - radius - 6, cy);

            // -- Sweep line --
            const sweepRad = degToRad(sweepAngle - 90);  // 0=up
            const sweepEndX = cx + radius * Math.cos(sweepRad);
            const sweepEndY = cy + radius * Math.sin(sweepRad);

            // Sweep trail (fading arc behind sweep)
            const sweepTrailDeg = 30;
            const sweepStartRad = degToRad(sweepAngle - sweepTrailDeg - 90);
            const sweepEndRad = degToRad(sweepAngle - 90);
            const grad = ctx.createConicGradient(sweepStartRad, cx, cy);
            // The conic gradient goes from the start angle CW.
            // We want transparent at the start, bright at the end.
            grad.addColorStop(0, 'rgba(0, 240, 255, 0)');
            grad.addColorStop(0.7, 'rgba(0, 240, 255, 0.04)');
            grad.addColorStop(1, 'rgba(0, 240, 255, 0.12)');

            ctx.save();
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            // Draw arc from sweep-trail to sweep
            const arcStart = sweepStartRad;
            const arcEnd = sweepEndRad;
            ctx.arc(cx, cy, radius, arcStart, arcEnd);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();
            ctx.restore();

            // Bright sweep line
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(sweepEndX, sweepEndY);
            ctx.strokeStyle = CYAN;
            ctx.lineWidth = 1.5;
            ctx.globalAlpha = 0.9;
            ctx.stroke();
            ctx.globalAlpha = 1.0;

            // Sweep line glow
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(sweepEndX, sweepEndY);
            ctx.strokeStyle = CYAN;
            ctx.lineWidth = 4;
            ctx.globalAlpha = 0.15;
            ctx.stroke();
            ctx.globalAlpha = 1.0;

            // -- Center dot --
            ctx.beginPath();
            ctx.arc(cx, cy, 3, 0, Math.PI * 2);
            ctx.fillStyle = CYAN;
            ctx.fill();

            // -- Tracks --
            for (const t of tracks) {
                // Alliance filter
                const alliance = t.alliance || 'unknown';
                if (trackFilter !== 'all' && alliance !== trackFilter) continue;
                if (t.range_m > maxRange) continue;

                const color = ALLIANCE_COLORS[alliance] || CYAN;
                const pos = trackToCanvas(t.range_m, t.azimuth_deg, cx, cy, radius);

                // Trail dots (fading older positions)
                const trail = trailHistory[t.track_id];
                if (trail && trail.length > 1) {
                    for (let i = 0; i < trail.length - 1; i++) {
                        const tp = trail[i];
                        if (tp.range_m > maxRange) continue;
                        const tpos = trackToCanvas(tp.range_m, tp.azimuth_deg, cx, cy, radius);
                        const alpha = 0.1 + 0.3 * (i / trail.length);
                        ctx.beginPath();
                        ctx.arc(tpos.x, tpos.y, 2, 0, Math.PI * 2);
                        ctx.fillStyle = color;
                        ctx.globalAlpha = alpha;
                        ctx.fill();
                    }
                    ctx.globalAlpha = 1.0;
                }

                // Main track dot
                const isHovered = hoveredTrack && hoveredTrack.track_id === t.track_id;
                const dotRadius = isHovered ? 6 : 4;

                // Glow
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, dotRadius + 4, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.globalAlpha = 0.15;
                ctx.fill();
                ctx.globalAlpha = 1.0;

                // Dot
                ctx.beginPath();
                ctx.arc(pos.x, pos.y, dotRadius, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();

                // Classification letter
                const icon = CLASS_ICONS[t.classification] || '?';
                ctx.fillStyle = BG;
                ctx.font = 'bold 7px monospace';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(icon, pos.x, pos.y);

                // Track ID label (small, to the right)
                ctx.fillStyle = color;
                ctx.globalAlpha = 0.6;
                ctx.font = '8px monospace';
                ctx.textAlign = 'left';
                ctx.textBaseline = 'middle';
                ctx.fillText(t.track_id, pos.x + dotRadius + 3, pos.y);
                ctx.globalAlpha = 1.0;
            }

            // -- Scope border glow --
            ctx.beginPath();
            ctx.arc(cx, cy, radius + 1, 0, Math.PI * 2);
            ctx.strokeStyle = CYAN;
            ctx.lineWidth = 2;
            ctx.globalAlpha = 0.2;
            ctx.stroke();
            ctx.globalAlpha = 1.0;

            animFrameId = requestAnimationFrame(render);
        }

        animFrameId = requestAnimationFrame(render);

        // -- Cleanup --
        panel._unsubs.push(() => {
            destroyed = true;
            if (animFrameId) cancelAnimationFrame(animFrameId);
            if (fetchTimerId) clearInterval(fetchTimerId);
            resizeObs.disconnect();
        });

        // Listen for radar events
        const unsub = EventBus.on('radar:tracks_updated', () => {
            fetchTracks();
        });
        if (unsub) panel._unsubs.push(unsub);
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },

    onResize() {
        // Canvas auto-resizes via ResizeObserver
    },
};
