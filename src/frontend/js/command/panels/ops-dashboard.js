// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Operational Dashboard Panel — "War Room at a Glance"
// Single-screen view combining: target counter, active alerts, fleet status,
// Amy status, demo mode toggle, and active missions.
// Auto-refreshes every 5 seconds with live WebSocket data.

import { EventBus } from '../events.js';
import { TritiumStore } from '../store.js';
import { _esc, _timeAgo } from '../panel-utils.js';

// ============================================================
// Data fetchers
// ============================================================

async function _fetchFleetSummary() {
    try {
        const r = await fetch('/api/fleet/devices');
        if (!r.ok) return null;
        const devices = await r.json();
        const online = devices.filter(d => d.status === 'online').length;
        const stale = devices.filter(d => d.status === 'stale').length;
        const offline = devices.filter(d => d.status === 'offline').length;
        return { total: devices.length, online, stale, offline };
    } catch { return null; }
}

async function _fetchMissions() {
    try {
        const r = await fetch('/api/missions');
        if (!r.ok) return [];
        return await r.json();
    } catch { return []; }
}

async function _fetchDemoStatus() {
    try {
        const r = await fetch('/api/demo/status');
        if (!r.ok) return { active: false };
        return await r.json();
    } catch { return { active: false }; }
}

// ============================================================
// Panel Definition
// ============================================================

let _refreshTimer = null;
let _bodyEl = null;

// Sparkline history: target count samples over the last hour (one per 10s)
const SPARKLINE_MAX = 360; // 360 samples * 10s = 1 hour
const _sparklineData = [];

function _sampleSparkline() {
    const units = TritiumStore.units;
    const count = units ? units.size : 0;
    _sparklineData.push(count);
    if (_sparklineData.length > SPARKLINE_MAX) {
        _sparklineData.shift();
    }
}

function _renderSparkline(bodyEl) {
    const canvas = bodyEl.querySelector('[data-bind="sparkline-canvas"]');
    const label = bodyEl.querySelector('[data-bind="sparkline-label"]');
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    if (_sparklineData.length < 2) {
        if (label) label.textContent = 'Collecting...';
        return;
    }

    const data = _sparklineData;
    const max = Math.max(...data, 1);
    const min = Math.min(...data, 0);
    const range = Math.max(max - min, 1);
    const current = data[data.length - 1];

    if (label) label.textContent = `${current} targets (peak: ${max})`;

    // Draw filled area
    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let i = 0; i < data.length; i++) {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((data[i] - min) / range) * (h - 4) - 2;
        if (i === 0) ctx.lineTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0, 240, 255, 0.08)';
    ctx.fill();

    // Draw line
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((data[i] - min) / range) * (h - 4) - 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Draw current value dot
    const lastX = w;
    const lastY = h - ((current - min) / range) * (h - 4) - 2;
    ctx.beginPath();
    ctx.arc(lastX - 1, lastY, 3, 0, Math.PI * 2);
    ctx.fillStyle = '#00f0ff';
    ctx.fill();
}

function _buildHTML() {
    return `
<div class="ops-dash" style="display:flex;flex-direction:column;gap:8px;padding:8px;height:100%;overflow-y:auto;font-family:var(--font-mono,'JetBrains Mono',monospace);font-size:0.75rem;">

    <!-- Target Summary -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Target Summary</div>
        <div style="display:flex;gap:12px;justify-content:space-around;" data-bind="targets">
            <div style="text-align:center;">
                <div class="ops-big-num" data-bind="target-total" style="font-size:1.6rem;color:var(--cyan,#00f0ff);font-weight:700;">0</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">TOTAL</div>
            </div>
            <div style="text-align:center;">
                <div class="ops-big-num" data-bind="target-friendly" style="font-size:1.2rem;color:var(--green,#05ffa1);">0</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">FRIENDLY</div>
            </div>
            <div style="text-align:center;">
                <div class="ops-big-num" data-bind="target-hostile" style="font-size:1.2rem;color:var(--magenta,#ff2a6d);">0</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">HOSTILE</div>
            </div>
            <div style="text-align:center;">
                <div class="ops-big-num" data-bind="target-unknown" style="font-size:1.2rem;color:var(--yellow,#fcee0a);">0</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">UNKNOWN</div>
            </div>
        </div>
    </div>

    <!-- Target Count Trend Sparkline -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
            <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;text-transform:uppercase;letter-spacing:1px;">Target Count Trend (1h)</div>
            <span data-bind="sparkline-label" style="font-size:0.6rem;color:var(--text-dim,#888);">--</span>
        </div>
        <canvas data-bind="sparkline-canvas" width="360" height="40" style="width:100%;height:40px;margin-top:4px;"></canvas>
    </div>

    <!-- Amy Status + Demo Mode -->
    <div style="display:flex;gap:8px;">
        <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;flex:1;">
            <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Amy Status</div>
            <div style="display:flex;align-items:center;gap:8px;">
                <div data-bind="amy-state-dot" style="width:10px;height:10px;border-radius:50%;background:var(--green,#05ffa1);flex-shrink:0;"></div>
                <div>
                    <div data-bind="amy-state" style="color:var(--text,#e0e0e0);text-transform:uppercase;">IDLE</div>
                    <div data-bind="amy-mood" style="color:var(--text-dim,#888);font-size:0.6rem;">CALM</div>
                </div>
            </div>
            <div data-bind="amy-thought" style="color:var(--text-dim,#888);font-size:0.65rem;margin-top:4px;font-style:italic;max-height:32px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">--</div>
        </div>
        <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;flex:1;">
            <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Demo Mode</div>
            <div style="display:flex;align-items:center;gap:8px;">
                <div data-bind="demo-dot" style="width:10px;height:10px;border-radius:50%;background:var(--text-dim,#888);flex-shrink:0;"></div>
                <span data-bind="demo-label" style="color:var(--text,#e0e0e0);">INACTIVE</span>
            </div>
            <div style="margin-top:6px;display:flex;gap:4px;">
                <button class="ops-btn" data-action="demo-start" style="padding:2px 8px;font-size:0.6rem;background:rgba(0,240,255,0.1);border:1px solid rgba(0,240,255,0.3);color:var(--cyan,#00f0ff);border-radius:3px;cursor:pointer;">START</button>
                <button class="ops-btn" data-action="demo-stop" style="padding:2px 8px;font-size:0.6rem;background:rgba(255,42,109,0.1);border:1px solid rgba(255,42,109,0.3);color:var(--magenta,#ff2a6d);border-radius:3px;cursor:pointer;">STOP</button>
            </div>
        </div>
    </div>

    <!-- Active Alerts -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Active Alerts <span data-bind="alert-count" style="color:var(--magenta,#ff2a6d);">0</span></div>
        <div data-bind="alert-list" style="max-height:80px;overflow-y:auto;">
            <div style="color:var(--text-dim,#888);font-size:0.65rem;">No active alerts</div>
        </div>
    </div>

    <!-- Fleet Status -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Fleet Status</div>
        <div style="display:flex;gap:12px;justify-content:space-around;" data-bind="fleet">
            <div style="text-align:center;">
                <div data-bind="fleet-total" style="font-size:1.2rem;color:var(--cyan,#00f0ff);font-weight:700;">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">TOTAL</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="fleet-online" style="font-size:1.2rem;color:var(--green,#05ffa1);">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">ONLINE</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="fleet-stale" style="font-size:1.2rem;color:var(--yellow,#fcee0a);">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">STALE</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="fleet-offline" style="font-size:1.2rem;color:var(--magenta,#ff2a6d);">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">OFFLINE</div>
            </div>
        </div>
    </div>

    <!-- Active Missions -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">Active Missions</div>
        <div data-bind="mission-list" style="max-height:80px;overflow-y:auto;">
            <div style="color:var(--text-dim,#888);font-size:0.65rem;">No active missions</div>
        </div>
    </div>

    <!-- System Uptime -->
    <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;">
        <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:6px;text-transform:uppercase;letter-spacing:1px;">System Uptime</div>
        <div style="display:flex;gap:12px;justify-content:space-around;">
            <div style="text-align:center;">
                <div data-bind="uptime-duration" style="font-size:1.2rem;color:var(--green,#05ffa1);font-weight:700;">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">UPTIME</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="uptime-started" style="font-size:0.75rem;color:var(--cyan,#00f0ff);">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">STARTED</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="uptime-targets-processed" style="font-size:1.2rem;color:var(--yellow,#fcee0a);font-weight:700;">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">TARGETS</div>
            </div>
            <div style="text-align:center;">
                <div data-bind="uptime-events-logged" style="font-size:1.2rem;color:var(--magenta,#ff2a6d);font-weight:700;">--</div>
                <div style="color:var(--text-dim,#888);font-size:0.6rem;">EVENTS</div>
            </div>
        </div>
    </div>

    <!-- Connection + Game State -->
    <div style="display:flex;gap:8px;">
        <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;flex:1;">
            <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px;">Connection</div>
            <div style="display:flex;align-items:center;gap:6px;">
                <div data-bind="conn-dot" style="width:8px;height:8px;border-radius:50%;background:var(--magenta,#ff2a6d);flex-shrink:0;"></div>
                <span data-bind="conn-label" style="color:var(--text,#e0e0e0);font-size:0.7rem;">OFFLINE</span>
            </div>
        </div>
        <div class="ops-section" style="border:1px solid rgba(0,240,255,0.2);border-radius:4px;padding:8px;flex:1;">
            <div class="ops-section-title" style="color:var(--cyan,#00f0ff);font-size:0.65rem;margin-bottom:4px;text-transform:uppercase;letter-spacing:1px;">Battle</div>
            <div style="display:flex;align-items:center;gap:6px;">
                <div data-bind="game-dot" style="width:8px;height:8px;border-radius:50%;background:var(--text-dim,#888);flex-shrink:0;"></div>
                <span data-bind="game-label" style="color:var(--text,#e0e0e0);font-size:0.7rem;">IDLE</span>
            </div>
        </div>
    </div>
</div>`;
}

function _update(bodyEl) {
    if (!bodyEl) return;

    // Targets
    const units = TritiumStore.units;
    let total = 0, friendly = 0, hostile = 0, unknown = 0;
    units.forEach(u => {
        total++;
        if (u.alliance === 'friendly') friendly++;
        else if (u.alliance === 'hostile') hostile++;
        else unknown++;
    });
    _setText(bodyEl, 'target-total', total);
    _setText(bodyEl, 'target-friendly', friendly);
    _setText(bodyEl, 'target-hostile', hostile);
    _setText(bodyEl, 'target-unknown', unknown);

    // Sparkline
    _renderSparkline(bodyEl);

    // Amy
    const amyState = TritiumStore.amy?.state || 'idle';
    const amyMood = TritiumStore.amy?.mood || 'calm';
    const amyThought = TritiumStore.amy?.lastThought || '--';
    _setText(bodyEl, 'amy-state', amyState.toUpperCase());
    _setText(bodyEl, 'amy-mood', amyMood.toUpperCase());
    _setText(bodyEl, 'amy-thought', amyThought);
    const amyDot = bodyEl.querySelector('[data-bind="amy-state-dot"]');
    if (amyDot) {
        const color = amyState === 'thinking' ? 'var(--yellow,#fcee0a)'
                    : amyState === 'speaking' ? 'var(--cyan,#00f0ff)'
                    : 'var(--green,#05ffa1)';
        amyDot.style.background = color;
    }

    // Alerts
    const alerts = TritiumStore.alerts || [];
    _setText(bodyEl, 'alert-count', alerts.length);
    const alertList = bodyEl.querySelector('[data-bind="alert-list"]');
    if (alertList) {
        if (alerts.length === 0) {
            alertList.innerHTML = '<div style="color:var(--text-dim,#888);font-size:0.65rem;">No active alerts</div>';
        } else {
            alertList.innerHTML = alerts.slice(0, 5).map(a =>
                `<div style="color:var(--magenta,#ff2a6d);font-size:0.65rem;padding:1px 0;border-bottom:1px solid rgba(255,42,109,0.1);">${_esc(a.message || a.type || 'Alert')}</div>`
            ).join('');
        }
    }

    // Connection
    const connStatus = TritiumStore.connection?.status || 'disconnected';
    _setText(bodyEl, 'conn-label', connStatus === 'connected' ? 'ONLINE' : 'OFFLINE');
    const connDot = bodyEl.querySelector('[data-bind="conn-dot"]');
    if (connDot) {
        connDot.style.background = connStatus === 'connected' ? 'var(--green,#05ffa1)' : 'var(--magenta,#ff2a6d)';
    }

    // Game
    const phase = TritiumStore.game?.phase || 'idle';
    _setText(bodyEl, 'game-label', phase.toUpperCase());
    const gameDot = bodyEl.querySelector('[data-bind="game-dot"]');
    if (gameDot) {
        const color = phase === 'active' ? 'var(--magenta,#ff2a6d)'
                    : phase === 'countdown' ? 'var(--yellow,#fcee0a)'
                    : phase === 'victory' ? 'var(--green,#05ffa1)'
                    : 'var(--text-dim,#888)';
        gameDot.style.background = color;
    }
}

async function _updateAsync(bodyEl) {
    if (!bodyEl) return;

    // Fleet
    const fleet = await _fetchFleetSummary();
    if (fleet && bodyEl.isConnected) {
        _setText(bodyEl, 'fleet-total', fleet.total);
        _setText(bodyEl, 'fleet-online', fleet.online);
        _setText(bodyEl, 'fleet-stale', fleet.stale);
        _setText(bodyEl, 'fleet-offline', fleet.offline);
    }

    // Demo
    const demo = await _fetchDemoStatus();
    if (bodyEl.isConnected) {
        const active = demo?.active || false;
        _setText(bodyEl, 'demo-label', active ? 'ACTIVE' : 'INACTIVE');
        const demoDot = bodyEl.querySelector('[data-bind="demo-dot"]');
        if (demoDot) {
            demoDot.style.background = active ? 'var(--green,#05ffa1)' : 'var(--text-dim,#888)';
        }
    }

    // Missions
    const missions = await _fetchMissions();
    const activeMissions = missions.filter(m => m.status === 'active' || m.status === 'in_progress');
    const missionList = bodyEl.querySelector('[data-bind="mission-list"]');
    if (missionList && bodyEl.isConnected) {
        if (activeMissions.length === 0) {
            missionList.innerHTML = '<div style="color:var(--text-dim,#888);font-size:0.65rem;">No active missions</div>';
        } else {
            missionList.innerHTML = activeMissions.slice(0, 4).map(m =>
                `<div style="color:var(--green,#05ffa1);font-size:0.65rem;padding:1px 0;border-bottom:1px solid rgba(5,255,161,0.1);">${_esc(m.name || m.id || 'Mission')}</div>`
            ).join('');
        }
    }

    // System uptime (from /api/health)
    try {
        const healthResp = await fetch('/api/health');
        if (healthResp.ok && bodyEl.isConnected) {
            const health = await healthResp.json();
            const uptimeSec = health.uptime_seconds || 0;
            _setText(bodyEl, 'uptime-duration', _formatUptime(uptimeSec));
            _setText(bodyEl, 'uptime-started', health.started_at ? new Date(health.started_at).toLocaleTimeString() : '--');
            _setText(bodyEl, 'uptime-targets-processed', health.targets_processed ?? '--');
            _setText(bodyEl, 'uptime-events-logged', health.events_logged ?? '--');
        }
    } catch { /* silent */ }
}

function _formatUptime(totalSeconds) {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
}

function _setText(root, bind, value) {
    const el = root.querySelector(`[data-bind="${bind}"]`);
    if (el) el.textContent = String(value);
}

export const OpsDashboardPanelDef = {
    id: 'ops-dashboard',
    title: 'OPS DASHBOARD',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 400, h: 600 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = _buildHTML();
        return el;
    },

    mount(bodyEl, panel) {
        _bodyEl = bodyEl;

        // Wire demo buttons
        bodyEl.addEventListener('click', (e) => {
            const action = e.target.dataset?.action;
            if (action === 'demo-start') {
                fetch('/api/demo/start', { method: 'POST' }).catch(() => {});
            } else if (action === 'demo-stop') {
                fetch('/api/demo/stop', { method: 'POST' }).catch(() => {});
            }
        });

        // Immediate sync update
        _update(bodyEl);

        // Async data
        _updateAsync(bodyEl);

        // Live reactive updates from store
        const unsubs = [];
        unsubs.push(TritiumStore.on('units', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('amy.state', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('amy.mood', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('amy.lastThought', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('alerts', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('connection.status', () => _update(bodyEl)));
        unsubs.push(TritiumStore.on('game.phase', () => _update(bodyEl)));
        panel._opsDashUnsubs = unsubs;

        // Sample sparkline immediately and every 10 seconds
        _sampleSparkline();
        panel._sparklineTimer = setInterval(() => {
            _sampleSparkline();
            _renderSparkline(bodyEl);
        }, 10000);

        // Periodic async refresh for fleet/demo/missions
        _refreshTimer = setInterval(() => {
            _update(bodyEl);
            _updateAsync(bodyEl);
        }, 5000);
    },

    unmount(bodyEl, panel) {
        _bodyEl = null;
        if (_refreshTimer) {
            clearInterval(_refreshTimer);
            _refreshTimer = null;
        }
        if (panel && panel._sparklineTimer) {
            clearInterval(panel._sparklineTimer);
            panel._sparklineTimer = null;
        }
    },
};
