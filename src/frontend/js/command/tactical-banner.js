// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Tactical Situation Banner — persistent command strip below the menu bar.
 *
 * Two rows:
 *   Row 1 (top):  Mode buttons (OBSERVE|TACTICAL|SETUP) | Threat level | Targets | Alerts | Connection status | Amy status
 *   Row 2 (tools): Draw Geofence | Draw Patrol | Add Waypoint | Measure | collapse toggle
 *
 * Collapsible to a thin 6px bar showing just a colored threat stripe.
 * Updates live via WebSocket events through the EventBus/TritiumStore.
 */

import { TritiumStore } from './store.js';
import { EventBus } from '/lib/events.js';

export const THREAT_LEVELS = {
    GREEN:  { color: '#05ffa1', label: 'GREEN',  bg: '#05ffa110' },
    YELLOW: { color: '#fcee0a', label: 'YELLOW', bg: '#fcee0a10' },
    ORANGE: { color: '#ff8800', label: 'ORANGE', bg: '#ff880010' },
    RED:    { color: '#ff2a6d', label: 'RED',    bg: '#ff2a6d10' },
};

/**
 * Create and mount the tactical situation banner into the given container.
 * @param {HTMLElement} container - element to insert the banner into
 * @returns {{ destroy: Function, setMode: Function }} cleanup handle
 */
export function createTacticalBanner(container) {
    const banner = document.createElement('div');
    banner.id = 'tactical-banner';
    banner.className = 'tactical-banner';

    banner.innerHTML = `
        <div class="tb-collapsed-label">TACTICAL PANEL <span class="tb-expand-arrow">&darr;</span></div>
        <div class="tb-row tb-row-top">
            <div class="tb-group tb-modes">
                <button class="tb-mode-btn active" data-tb-mode="observe" title="Observe Mode (O)">
                    <span class="tb-mode-key">O</span>BSERVE
                </button>
                <button class="tb-mode-btn" data-tb-mode="tactical" title="Tactical Mode (T)">
                    <span class="tb-mode-key">T</span>ACTICAL
                </button>
                <button class="tb-mode-btn" data-tb-mode="setup" title="Setup Mode (S)">
                    <span class="tb-mode-key">S</span>ETUP
                </button>
            </div>

            <span class="tb-sep-v"></span>

            <div class="tb-group tb-threat">
                <span class="tb-threat-dot" data-bind="threat-dot"></span>
                <span class="tb-label mono">THREAT</span>
                <span class="tb-threat-level mono" data-bind="threat-level">GREEN</span>
            </div>

            <span class="tb-sep-v"></span>

            <div class="tb-group">
                <span class="tb-label mono">TGT</span>
                <span class="tb-value mono" data-bind="target-count">0</span>
            </div>

            <span class="tb-sep-v"></span>

            <div class="tb-group">
                <span class="tb-label mono">ALERTS</span>
                <span class="tb-value tb-alert-value mono" data-bind="alert-count">0</span>
            </div>

            <div class="tb-spacer"></div>

            <div class="tb-group tb-connections">
                <span class="tb-conn-icon" data-bind="conn-ws" title="WebSocket">
                    <span class="tb-conn-dot"></span>
                    <span class="tb-conn-label mono">WS</span>
                </span>
                <span class="tb-conn-icon" data-bind="conn-mqtt" title="MQTT Broker">
                    <span class="tb-conn-dot"></span>
                    <span class="tb-conn-label mono">MQTT</span>
                </span>
                <span class="tb-conn-icon" data-bind="conn-mesh" title="Meshtastic">
                    <span class="tb-conn-dot"></span>
                    <span class="tb-conn-label mono">MESH</span>
                </span>
                <span class="tb-conn-icon" data-bind="conn-cam" title="Cameras">
                    <span class="tb-conn-dot"></span>
                    <span class="tb-conn-label mono">CAM</span>
                </span>
            </div>

            <span class="tb-sep-v"></span>

            <div class="tb-group tb-amy-group">
                <span class="tb-amy-dot" data-bind="amy-dot"></span>
                <span class="tb-label mono">AMY</span>
                <span class="tb-value mono" data-bind="amy-status">IDLE</span>
            </div>
        </div>

        <div class="tb-row tb-row-tools">
            <div class="tb-group tb-tool-buttons">
                <button class="tb-tool-btn" data-tb-tool="geofence" title="Draw Geofence (polygon zone)">
                    <span class="tb-tool-icon">[G]</span> GEOFENCE
                </button>
                <button class="tb-tool-btn" data-tb-tool="patrol" title="Draw Patrol Route">
                    <span class="tb-tool-icon">[P]</span> PATROL
                </button>
                <button class="tb-tool-btn" data-tb-tool="waypoint" title="Add Waypoint">
                    <span class="tb-tool-icon">[W]</span> WAYPOINT
                </button>
                <button class="tb-tool-btn" data-tb-tool="measure" title="Measure Distance">
                    <span class="tb-tool-icon">[~]</span> MEASURE
                </button>
            </div>

            <div class="tb-spacer"></div>

            <div class="tb-group tb-clock-group">
                <span class="tb-clock mono" data-bind="clock"></span>
            </div>

            <button class="tb-collapse-btn" data-bind="collapse-btn" title="Collapse banner">
                <span class="tb-collapse-arrow" data-bind="collapse-arrow">&and;</span>
            </button>
        </div>
    `;

    container.appendChild(banner);

    // Hide the old map-mode-indicator if present (modes now live in banner)
    const oldModeIndicator = document.getElementById('map-mode');
    if (oldModeIndicator) {
        oldModeIndicator.style.display = 'none';
    }

    // --- Collapse/expand ---
    const collapseBtn = banner.querySelector('[data-bind="collapse-btn"]');
    const collapseArrow = banner.querySelector('[data-bind="collapse-arrow"]');

    function toggleCollapse(e) {
        e.stopPropagation();
        const isCollapsed = banner.classList.toggle('collapsed');
        if (collapseArrow) {
            collapseArrow.innerHTML = isCollapsed ? '&or;' : '&and;';
        }
        // Update the CSS variable on the layout so the map adjusts
        EventBus.emit('tactical-banner:resize', { collapsed: isCollapsed });
    }

    if (collapseBtn) {
        collapseBtn.addEventListener('click', toggleCollapse);
    }

    // Allow clicking anywhere on the collapsed bar to expand
    banner.addEventListener('click', (e) => {
        if (banner.classList.contains('collapsed')) {
            banner.classList.remove('collapsed');
            if (collapseArrow) collapseArrow.innerHTML = '&and;';
            EventBus.emit('tactical-banner:resize', { collapsed: false });
        }
    });

    // --- State ---
    let currentThreatLevel = 'GREEN';
    let activeTool = null;

    // --- DOM refs ---
    const threatDot = banner.querySelector('[data-bind="threat-dot"]');
    const threatLevel = banner.querySelector('[data-bind="threat-level"]');
    const targetCount = banner.querySelector('[data-bind="target-count"]');
    const alertCountEl = banner.querySelector('[data-bind="alert-count"]');
    const amyDot = banner.querySelector('[data-bind="amy-dot"]');
    const amyStatus = banner.querySelector('[data-bind="amy-status"]');
    const clockEl = banner.querySelector('[data-bind="clock"]');
    const connWs = banner.querySelector('[data-bind="conn-ws"]');
    const connMqtt = banner.querySelector('[data-bind="conn-mqtt"]');
    const connMesh = banner.querySelector('[data-bind="conn-mesh"]');
    const connCam = banner.querySelector('[data-bind="conn-cam"]');

    // --- Mode buttons ---
    const modeBtns = banner.querySelectorAll('[data-tb-mode]');
    modeBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const mode = btn.dataset.tbMode;
            setMode(mode);
        });
    });

    function setMode(mode) {
        TritiumStore.set('map.mode', mode);
        modeBtns.forEach(b => b.classList.remove('active'));
        const target = banner.querySelector(`[data-tb-mode="${mode}"]`);
        if (target) target.classList.add('active');
        EventBus.emit('map:mode', { mode });

        // Sync the old HTML mode buttons too (if they exist)
        document.querySelectorAll('[data-map-mode]').forEach(b => b.classList.remove('active'));
        const oldBtn = document.querySelector(`[data-map-mode="${mode}"]`);
        if (oldBtn) oldBtn.classList.add('active');
    }

    // Listen for mode changes from keyboard shortcuts or old buttons
    const onModeChange = (data) => {
        if (data && data.mode) {
            modeBtns.forEach(b => b.classList.remove('active'));
            const target = banner.querySelector(`[data-tb-mode="${data.mode}"]`);
            if (target) target.classList.add('active');
        }
    };
    EventBus.on('map:mode', onModeChange);

    // --- Tool buttons ---
    const toolBtns = banner.querySelectorAll('[data-tb-tool]');
    toolBtns.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const tool = btn.dataset.tbTool;
            activateTool(tool, btn);
        });
    });

    function activateTool(tool, btn) {
        // Deactivate current tool if re-clicking same one
        if (activeTool === tool) {
            deactivateTools();
            return;
        }
        deactivateTools();
        activeTool = tool;
        if (btn) btn.classList.add('tb-tool-active');

        switch (tool) {
            case 'geofence':
                EventBus.emit('geofence:drawZone', {});
                break;
            case 'patrol':
                EventBus.emit('patrol:drawRoute', { unitId: null });
                break;
            case 'waypoint':
                EventBus.emit('patrol:addWaypoint', {});
                break;
            case 'measure':
                EventBus.emit('map:measureStart', {});
                break;
        }
    }

    function deactivateTools() {
        activeTool = null;
        toolBtns.forEach(b => b.classList.remove('tb-tool-active'));
    }

    // Deactivate tool when drawing ends
    EventBus.on('geofence:drawEnd', deactivateTools);
    EventBus.on('patrol:drawEnd', deactivateTools);

    // --- Threat level ---
    function updateThreatLevel(level) {
        const key = (level || 'GREEN').toUpperCase();
        const config = THREAT_LEVELS[key] || THREAT_LEVELS.GREEN;
        currentThreatLevel = key;
        threatLevel.textContent = config.label;
        threatLevel.style.color = config.color;
        threatDot.style.background = config.color;
        threatDot.style.boxShadow = `0 0 6px ${config.color}`;
        banner.style.borderBottomColor = `${config.color}44`;

        if (key === 'RED') {
            threatDot.classList.add('tb-pulse');
        } else {
            threatDot.classList.remove('tb-pulse');
        }
    }

    // --- Target count ---
    function updateTargetCount() {
        const units = TritiumStore.units;
        let total = 0;
        units.forEach(() => total++);
        targetCount.textContent = total;
    }

    // --- Alerts ---
    function updateAlertCount() {
        const alerts = TritiumStore.alerts || [];
        const unread = alerts.filter(a => a && (a.read === false || a.read === undefined)).length;
        alertCountEl.textContent = unread;
        alertCountEl.classList.toggle('tb-alert-active', unread > 0);
    }

    // --- Amy status ---
    function updateAmyStatus() {
        const state = TritiumStore.amy?.state || 'idle';
        amyStatus.textContent = state.toUpperCase();

        const amyColors = {
            idle: '#666',
            thinking: '#fcee0a',
            speaking: '#05ffa1',
            listening: '#00f0ff',
            commanding: '#ff8800',
            observing: '#00a0ff',
        };
        const color = amyColors[state] || '#666';
        amyDot.style.background = color;
        amyDot.style.boxShadow = `0 0 4px ${color}`;
    }

    // --- Connection indicators ---
    function setConnStatus(el, connected) {
        if (!el) return;
        const dot = el.querySelector('.tb-conn-dot');
        if (dot) {
            dot.style.background = connected ? '#05ffa1' : '#ff2a6d';
            dot.style.boxShadow = connected ? '0 0 4px #05ffa1' : '0 0 4px #ff2a6d';
        }
    }

    function updateConnections() {
        // WebSocket
        const wsConnected = TritiumStore.get('ws.connected') || false;
        setConnStatus(connWs, wsConnected);

        // MQTT
        const mqttConnected = TritiumStore.get('mqtt.connected') || false;
        setConnStatus(connMqtt, mqttConnected);

        // Mesh
        const meshNodes = TritiumStore.get('mesh.nodes');
        const meshConnected = meshNodes && (Array.isArray(meshNodes) ? meshNodes.length > 0 : true);
        setConnStatus(connMesh, meshConnected);

        // Cameras
        const cameras = TritiumStore.get('cameras');
        const camConnected = cameras && (Array.isArray(cameras) ? cameras.length > 0 : true);
        setConnStatus(connCam, camConnected);
    }

    // --- Derive threat from state ---
    function deriveThreatLevel() {
        const units = TritiumStore.units;
        let hostileCount = 0;
        units.forEach(u => {
            if (u.alliance === 'hostile') hostileCount++;
        });

        const alerts = TritiumStore.alerts || [];
        const recentAlerts = alerts.filter(a => {
            const age = Date.now() - (a.time || 0);
            return age < 300000;
        }).length;

        let level = 'GREEN';
        if (hostileCount > 0 || recentAlerts > 5) level = 'YELLOW';
        if (hostileCount > 3 || recentAlerts > 10) level = 'ORANGE';
        if (hostileCount > 8 || recentAlerts > 20) level = 'RED';

        const phase = TritiumStore.game?.phase;
        if (phase === 'active') {
            level = hostileCount > 5 ? 'RED' : hostileCount > 0 ? 'ORANGE' : 'YELLOW';
        }

        updateThreatLevel(level);
    }

    // --- Clock ---
    function updateClock() {
        if (!clockEl) return;
        const now = new Date();
        const h = String(now.getHours()).padStart(2, '0');
        const m = String(now.getMinutes()).padStart(2, '0');
        const s = String(now.getSeconds()).padStart(2, '0');
        clockEl.textContent = `${h}:${m}:${s}Z`;
    }
    const clockInterval = setInterval(updateClock, 1000);
    updateClock();

    // --- Subscribe to store changes ---
    const unsubs = [];
    unsubs.push(TritiumStore.on('units', () => {
        updateTargetCount();
        deriveThreatLevel();
    }));
    unsubs.push(TritiumStore.on('alerts', () => {
        updateAlertCount();
        deriveThreatLevel();
    }));
    unsubs.push(TritiumStore.on('amy.state', () => {
        updateAmyStatus();
    }));
    unsubs.push(TritiumStore.on('game.phase', () => {
        deriveThreatLevel();
    }));

    // Connection status updates
    const connEvents = ['ws.connected', 'mqtt.connected', 'mesh.nodes', 'cameras'];
    for (const evt of connEvents) {
        unsubs.push(TritiumStore.on(evt, updateConnections));
    }

    // Listen for explicit escalation events
    const onEscalation = (data) => {
        if (data && data.level) {
            updateThreatLevel(data.level);
        }
    };
    EventBus.on('escalation:change', onEscalation);

    // --- Initial render ---
    updateThreatLevel('GREEN');
    updateTargetCount();
    updateAlertCount();
    updateAmyStatus();
    updateConnections();
    // Default all connections to disconnected
    setConnStatus(connWs, false);
    setConnStatus(connMqtt, false);
    setConnStatus(connMesh, false);
    setConnStatus(connCam, false);

    return {
        destroy() {
            clearInterval(clockInterval);
            for (const unsub of unsubs) unsub();
            EventBus.off('escalation:change', onEscalation);
            EventBus.off('map:mode', onModeChange);
            EventBus.off('geofence:drawEnd', deactivateTools);
            EventBus.off('patrol:drawEnd', deactivateTools);
            banner.remove();
        },
        setMode,
        getElement() { return banner; },
    };
}
