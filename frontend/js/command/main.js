// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// TRITIUM Command Center -- entry point
// Initializes store, event bus, WebSocket, panel system, and UI bindings.
// Serves both unified (floating panels) and legacy (sidebar+bottom bar) layouts.
//
// Include via: <script type="module" src="/static/js/command/main.js"></script>

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';
import { WebSocketManager } from './websocket.js';
import { initMap, destroyMap, toggleSatellite, toggleRoads, toggleGrid, toggleBuildings, toggleFog, toggleTerrain, toggleLabels, toggleModels, toggleWaterways, toggleParks, toggleMesh, toggleThoughts, toggleAllLayers, toggleTracers, toggleExplosions, toggleParticles, toggleHitFlashes, toggleFloatingText, toggleKillFeed, toggleScreenFx, toggleBanners, toggleLayerHud, toggleHealthBars, toggleSelectionFx, getMapState, centerOnAction, resetCamera, zoomIn, zoomOut, toggleTilt, setLayers, setMapMode } from './map-maplibre.js';
import { PanelManager } from './panel-manager.js';
import { LayoutManager } from './layout-manager.js';
import { createMenuBar, focusSaveInput } from './menu-bar.js';
import { AmyPanelDef } from './panels/amy.js';
import { UnitsPanelDef } from './panels/units.js';
import { AlertsPanelDef } from './panels/alerts.js';
import { GameHudPanelDef } from './panels/game-hud.js';
import { MeshPanelDef } from './panels/mesh.js';
import { AudioPanelDef } from './panels/audio.js';
import { EscalationPanelDef } from './panels/escalation.js';
import { EventsPanelDef } from './panels/events.js';
import { PatrolPanelDef } from './panels/patrol.js';
import { ScenariosPanelDef } from './panels/scenarios.js';
import { SystemPanelDef } from './panels/system.js';
import { MinimapPanelDef } from './panels/minimap.js';
import { MissionModal, initMissionModal } from './mission-modal.js';

// Make available on window for console debugging
window.TritiumStore = TritiumStore;
window.EventBus = EventBus;

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

const ws = new WebSocketManager();
let panelManager = null;
let layoutManager = null;
let menuBarEl = null;

function init() {
    console.log('%c[TRITIUM] Command Center initializing...', 'color: #00f0ff; font-weight: bold;');

    // Clock
    updateClock();
    setInterval(updateClock, 1000);

    // WebSocket
    ws.connect();

    // Connection status indicator
    TritiumStore.on('connection.status', (status) => {
        const el = document.getElementById('connection-status');
        if (el) {
            el.dataset.state = status;
            const label = el.querySelector('.conn-label');
            if (label) label.textContent = status === 'connected' ? 'ONLINE' : 'OFFLINE';
        }
        const wsStatus = document.getElementById('status-ws');
        if (wsStatus) wsStatus.textContent = `WS: ${status === 'connected' ? 'OK' : '--'}`;
    });

    // Header unit/threat counters
    TritiumStore.on('units', () => {
        const units = TritiumStore.units;
        let friendlyCount = 0;
        let hostileCount = 0;
        units.forEach(u => {
            if (u.alliance === 'hostile') hostileCount++;
            else friendlyCount++;
        });

        const unitEl = document.getElementById('header-units');
        if (unitEl) {
            const val = unitEl.querySelector('.stat-value');
            if (val) val.textContent = friendlyCount;
        }

        const threatEl = document.getElementById('header-threats');
        if (threatEl) {
            const val = threatEl.querySelector('.stat-value');
            if (val) val.textContent = hostileCount;
        }

        // Status bar
        const aliveEl = document.getElementById('status-alive');
        if (aliveEl) aliveEl.textContent = `${friendlyCount} alive`;
        const threatsEl = document.getElementById('status-threats');
        if (threatsEl) threatsEl.textContent = `${hostileCount} threats`;

        // Legacy sidebar unit list (if present)
        renderUnitList();
    });

    // Game state updates (header + game over overlay + auto-fog)
    TritiumStore.on('game.phase', (phase) => {
        // Show/hide game score in header
        const scoreArea = document.getElementById('game-score-area');
        if (scoreArea) scoreArea.hidden = (phase === 'idle' || !phase);

        // Game over overlay
        if (phase === 'victory' || phase === 'defeat') {
            showGameOver(phase);
        }

        // Auto-enable fog of war during battle, disable when idle
        const mapState = getMapState();
        if (phase === 'countdown' || phase === 'active') {
            if (!mapState.showFog) toggleFog();
        } else if (phase === 'idle' || phase === 'setup') {
            if (mapState.showFog) toggleFog();
        }
    });

    TritiumStore.on('game.wave', (wave) => {
        const header = document.getElementById('game-wave');
        if (header) header.textContent = `${wave}/${TritiumStore.game.totalWaves}`;
    });

    TritiumStore.on('game.score', (score) => {
        const header = document.getElementById('game-score');
        if (header) header.textContent = score;
    });

    TritiumStore.on('game.eliminations', (elims) => {
        const header = document.getElementById('game-eliminations');
        if (header) header.textContent = elims;
    });

    // Chat thought context
    TritiumStore.on('amy.lastThought', (thought) => {
        const ctx = document.getElementById('chat-context-text');
        if (ctx) ctx.textContent = thought || '--';
    });

    // Keyboard shortcuts
    initKeyboard();

    // Chat panel
    initChat();

    // Help overlay
    initHelp();

    // Modal
    initModal();

    // Mission generation modal
    initMissionModal(EventBus);

    // Map mode buttons
    initMapModes();

    // Subscribe to toasts from event bus
    EventBus.on('amy:thought', (data) => {
        showToast(data.text || data, 'amy');
    });

    EventBus.on('robot:thought', (data) => {
        showToast(`${data.name || data.robot_id}: ${data.text}`, 'robot');
    });

    EventBus.on('alert:new', (data) => {
        showToast(data.message, 'alert');
    });

    EventBus.on('announcer', (data) => {
        showBanner(data.text || data.message, data.sub || '');
    });

    EventBus.on('game:elimination', (data) => {
        const interceptor = data.interceptor_name || data.killer_name || '???';
        const target = data.target_name || data.victim_name || '???';
        showToast(`${interceptor} neutralized ${target}`, 'alert');
    });

    EventBus.on('mesh:text', (data) => {
        showToast(`[MESH] ${data.from_short || 'Unknown'}: ${data.text}`, 'info');
    });

    EventBus.on('toast:show', (data) => {
        showToast(data.message || data, data.type || 'info');
    });

    // Initialize tactical map
    initMap();

    // Initialize panel system (unified layout) or legacy sidebar
    const panelContainer = document.getElementById('panel-container');
    if (panelContainer) {
        initPanelSystem(panelContainer);
    } else {
        // Legacy layout: init sidebar and bottom bar
        initSidebarToggle();
        initSectionToggles();
        initGameControls();
        initAmyActions();
        TritiumStore.on('alerts', (alerts) => {
            renderAlertFeed(alerts);
        });
        TritiumStore.on('amy.state', (state) => {
            const el = document.getElementById('amy-state');
            if (el) el.textContent = (state || 'IDLE').toUpperCase();
            const portrait = document.querySelector('.amy-portrait');
            if (portrait) portrait.dataset.state = state || 'idle';
        });
        TritiumStore.on('amy.mood', (mood) => {
            const el = document.getElementById('amy-mood');
            if (el) {
                const label = el.querySelector('.mood-label');
                if (label) label.textContent = (mood || 'CALM').toUpperCase();
            }
        });
        TritiumStore.on('amy.lastThought', (thought) => {
            const el = document.getElementById('amy-thought');
            if (el) el.textContent = thought || '';
        });
        fetchAmyStatus();
    }

    // Audio: initialize on first user interaction and wire combat events
    let _audioInitialized = false;
    const _initAudio = () => {
        if (_audioInitialized) return;
        _audioInitialized = true;
        if (typeof window.WarAudioManager === 'function') {
            try {
                const audioMgr = new window.WarAudioManager();
                audioMgr.init();
                window._tritiumAudio = audioMgr;

                // Preload critical combat + game sounds
                audioMgr.preload([
                    'nerf_shot', 'impact_hit', 'explosion', 'explosion_small',
                    'turret_rotate', 'turret_lock_on', 'drone_buzz', 'drone_flyby',
                    'ricochet', 'shield_hit', 'reload',
                    'wave_start', 'wave_complete', 'countdown_tick', 'countdown_go',
                    'victory_fanfare', 'defeat_sting', 'dispatch_ack',
                    'hostile_detected', 'alert_tone', 'escalation_siren',
                    'killing_spree', 'rampage', 'dominating', 'godlike',
                    'ambient_wind',
                ]);

                // Wire EventBus combat events to weapon-specific audio
                // Uses projectile_type from backend for accurate weapon sounds
                EventBus.on('combat:projectile', (d) => {
                    const pos = d.source_pos || {};
                    const x = pos.x || 0, y = pos.y || 0;
                    const ptype = d.projectile_type || '';
                    if (ptype.includes('missile')) {
                        audioMgr.playAt('nerf_shot', x, y);
                        audioMgr.playAt('turret_lock_on', x, y);
                    } else if (ptype.includes('tank')) {
                        audioMgr.playAt('nerf_shot', x, y);
                        audioMgr.playAt('turret_rotate', x, y);
                    } else if (ptype.includes('heavy')) {
                        audioMgr.playAt('nerf_shot', x, y);
                        audioMgr.playAt('turret_rotate', x, y);
                    } else if (ptype.includes('scout') || ptype.includes('dart_gun')) {
                        audioMgr.playAt('nerf_shot', x, y);
                        audioMgr.playAt('drone_buzz', x, y);
                    } else if (ptype.includes('apc')) {
                        audioMgr.playAt('nerf_shot', x, y);
                    } else {
                        audioMgr.playAt('nerf_shot', x, y);
                    }
                });
                EventBus.on('combat:hit', (d) => {
                    const pos = d.position || {};
                    let x = pos.x, y = pos.y;
                    if (x === undefined) {
                        const unit = TritiumStore.units.get(d.target_id);
                        const upos = unit?.position || {};
                        x = upos.x || 0;
                        y = upos.y || 0;
                    }
                    const ptype = d.projectile_type || '';
                    // Heavy weapons get deeper impact, others get hit/ricochet mix
                    if (ptype.includes('missile') || ptype.includes('tank')) {
                        audioMgr.playAt('explosion', x, y);
                    } else {
                        const sound = Math.random() < 0.75 ? 'impact_hit' : 'ricochet';
                        audioMgr.playAt(sound, x, y);
                    }
                });
                EventBus.on('combat:elimination', (d) => {
                    const pos = d.position || {};
                    const x = pos.x || 0, y = pos.y || 0;
                    audioMgr.playAt('explosion', x, y);
                    if (d.interceptor_name) {
                        audioMgr.play('dispatch_ack');
                    }
                });
                EventBus.on('combat:streak', (d) => {
                    const streak = d.streak || 3;
                    const effect = streak >= 10 ? 'godlike'
                                 : streak >= 7 ? 'dominating'
                                 : streak >= 5 ? 'rampage'
                                 : 'killing_spree';
                    audioMgr.play(effect);
                });
                EventBus.on('game:wave_start', () => {
                    audioMgr.play('wave_start');
                });
                EventBus.on('game:wave_complete', () => {
                    audioMgr.play('wave_complete');
                });
                EventBus.on('game:state', (d) => {
                    if (d.state === 'active') {
                        audioMgr.startAmbient();
                        audioMgr.play('hostile_detected');
                    } else if (d.state === 'idle' || d.state === 'victory' || d.state === 'defeat') {
                        audioMgr.stopAmbient();
                    }
                    if (d.state === 'countdown') audioMgr.play('countdown_tick');
                    if (d.state === 'victory') audioMgr.play('victory_fanfare');
                    else if (d.state === 'defeat') audioMgr.play('defeat_sting');
                });

                console.log('[TRITIUM] Audio initialized + combat events wired');
            } catch (e) {
                console.warn('[TRITIUM] Audio init failed:', e);
            }
        }
    };
    document.addEventListener('click', _initAudio, { once: true });
    document.addEventListener('keydown', _initAudio, { once: true });

    console.log('%c[TRITIUM] Command Center ready', 'color: #05ffa1; font-weight: bold;');
}

// ---------------------------------------------------------------------------
// Panel System (unified layout)
// ---------------------------------------------------------------------------

function initPanelSystem(container) {
    panelManager = new PanelManager(container);
    window.panelManager = panelManager; // Debug access

    // Register panels
    panelManager.register(AmyPanelDef);
    panelManager.register(UnitsPanelDef);
    panelManager.register(AlertsPanelDef);
    panelManager.register(GameHudPanelDef);
    panelManager.register(MeshPanelDef);
    panelManager.register(AudioPanelDef);
    panelManager.register(EscalationPanelDef);
    panelManager.register(EventsPanelDef);
    panelManager.register(PatrolPanelDef);
    panelManager.register(ScenariosPanelDef);
    panelManager.register(SystemPanelDef);
    panelManager.register(MinimapPanelDef);

    // Try loading saved layout; if none, open defaults
    if (!panelManager.loadLayout()) {
        panelManager.open('amy');
        panelManager.open('units');
        panelManager.open('alerts');
        panelManager.open('minimap');
    }

    // Layout manager
    layoutManager = new LayoutManager(panelManager);
    window.layoutManager = layoutManager; // Debug access

    // Menu bar (replaces command-bar)
    const barContainer = document.getElementById('command-bar-container');
    if (barContainer) {
        const mapActions = {
            toggleSatellite: () => (_activeMapModule ? _activeMapModule.toggleSatellite() : toggleSatellite()),
            toggleRoads: () => (_activeMapModule ? _activeMapModule.toggleRoads() : toggleRoads()),
            toggleGrid: () => (_activeMapModule ? _activeMapModule.toggleGrid() : toggleGrid()),
            toggleFog: () => (_activeMapModule ? _activeMapModule.toggleFog() : toggleFog()),
            toggleTerrain: () => (_activeMapModule ? _activeMapModule.toggleTerrain() : toggleTerrain()),
            toggleLabels: () => (_activeMapModule ? _activeMapModule.toggleLabels() : toggleLabels()),
            toggleModels: () => (_activeMapModule ? _activeMapModule.toggleModels() : toggleModels()),
            toggleWaterways: () => (_activeMapModule ? _activeMapModule.toggleWaterways() : toggleWaterways()),
            toggleParks: () => (_activeMapModule ? _activeMapModule.toggleParks() : toggleParks()),
            toggleTilt: () => (_activeMapModule ? _activeMapModule.toggleTilt() : toggleTilt()),
            toggleBuildings: () => (_activeMapModule ? _activeMapModule.toggleBuildings() : toggleBuildings()),
            toggleMesh: () => (_activeMapModule ? _activeMapModule.toggleMesh() : toggleMesh()),
            toggleThoughts: () => (_activeMapModule ? _activeMapModule.toggleThoughts() : toggleThoughts()),
            toggleAllLayers: () => (_activeMapModule ? _activeMapModule.toggleAllLayers() : toggleAllLayers()),
            toggleTracers: () => (_activeMapModule ? _activeMapModule.toggleTracers() : toggleTracers()),
            toggleExplosions: () => (_activeMapModule ? _activeMapModule.toggleExplosions() : toggleExplosions()),
            toggleParticles: () => (_activeMapModule ? _activeMapModule.toggleParticles() : toggleParticles()),
            toggleHitFlashes: () => (_activeMapModule ? _activeMapModule.toggleHitFlashes() : toggleHitFlashes()),
            toggleFloatingText: () => (_activeMapModule ? _activeMapModule.toggleFloatingText() : toggleFloatingText()),
            toggleKillFeed: () => (_activeMapModule ? _activeMapModule.toggleKillFeed() : toggleKillFeed()),
            toggleScreenFx: () => (_activeMapModule ? _activeMapModule.toggleScreenFx() : toggleScreenFx()),
            toggleBanners: () => (_activeMapModule ? _activeMapModule.toggleBanners() : toggleBanners()),
            toggleLayerHud: () => (_activeMapModule ? _activeMapModule.toggleLayerHud() : toggleLayerHud()),
            toggleHealthBars: () => (_activeMapModule ? _activeMapModule.toggleHealthBars() : toggleHealthBars()),
            toggleSelectionFx: () => (_activeMapModule ? _activeMapModule.toggleSelectionFx() : toggleSelectionFx()),
            centerOnAction: () => (_activeMapModule ? _activeMapModule.centerOnAction() : centerOnAction()),
            resetCamera: () => (_activeMapModule ? _activeMapModule.resetCamera() : resetCamera()),
            zoomIn: () => (_activeMapModule ? _activeMapModule.zoomIn() : zoomIn()),
            zoomOut: () => (_activeMapModule ? _activeMapModule.zoomOut() : zoomOut()),
            getMapState: () => (_activeMapModule ? _activeMapModule.getMapState() : getMapState()),
            setLayers: (layers) => (_activeMapModule ? _activeMapModule.setLayers(layers) : setLayers(layers)),
            setMapMode: (mode) => (_activeMapModule ? _activeMapModule.setMapMode(mode) : setMapMode(mode)),
            beginWar: () => beginWar(),
            resetGame: () => resetGame(),
        };
        // Store on module scope so keyboard handlers can access it
        _mapActions = mapActions;
        // Expose for automated testing
        window._mapActions = mapActions;
        menuBarEl = createMenuBar(barContainer, panelManager, layoutManager, mapActions);
    }

    console.log('%c[TRITIUM] Panel system initialized', 'color: #00f0ff;');
}

// ---------------------------------------------------------------------------
// Clock
// ---------------------------------------------------------------------------

function updateClock() {
    const el = document.getElementById('header-clock');
    if (el) el.textContent = new Date().toISOString().substr(11, 8) + ' UTC';
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------

const TOAST_MAX = 5;
const TOAST_DURATION = 6000;

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-header">
            <span class="toast-label mono">${escapeHtml(type.toUpperCase())}</span>
            <span class="toast-time mono">${new Date().toLocaleTimeString().substr(0, 5)}</span>
            <button class="toast-close" aria-label="Dismiss">&times;</button>
        </div>
        <div class="toast-body">${escapeHtml(message)}</div>
    `;

    toast.querySelector('.toast-close')?.addEventListener('click', () => {
        toast.classList.add('toast-fade');
        setTimeout(() => toast.remove(), 300);
    });

    container.prepend(toast);

    const toasts = container.querySelectorAll('.toast');
    if (toasts.length > TOAST_MAX) {
        toasts[toasts.length - 1].remove();
    }

    setTimeout(() => {
        toast.classList.add('toast-fade');
        setTimeout(() => toast.remove(), 300);
    }, TOAST_DURATION);
}

// ---------------------------------------------------------------------------
// Center banner (announcer: wave banners, elimination streaks)
// ---------------------------------------------------------------------------

let _bannerTimeout = null;

function showBanner(text, sub = '', duration = 3000) {
    const banner = document.getElementById('center-banner');
    if (!banner) return;

    const textEl = banner.querySelector('[data-element="banner-text"]');
    const subEl = banner.querySelector('[data-element="banner-sub"]');
    if (textEl) textEl.textContent = text;
    if (subEl) subEl.textContent = sub;

    banner.hidden = false;
    banner.style.animation = 'v2-fadeIn 0.3s ease forwards';

    clearTimeout(_bannerTimeout);
    _bannerTimeout = setTimeout(() => {
        banner.style.animation = 'v2-fadeOut 0.5s ease forwards';
        setTimeout(() => { banner.hidden = true; }, 500);
    }, duration);
}

// ---------------------------------------------------------------------------
// Game over overlay
// ---------------------------------------------------------------------------

function showGameOver(phase) {
    const overlay = document.getElementById('game-over-overlay');
    if (!overlay) return;

    const title = document.getElementById('game-over-title');
    if (title) {
        title.textContent = phase === 'victory' ? 'VICTORY' : 'DEFEAT';
        title.style.color = phase === 'victory' ? 'var(--green)' : 'var(--magenta)';
    }

    const scoreEl = document.getElementById('go-score');
    if (scoreEl) scoreEl.textContent = TritiumStore.game.score || 0;

    const wavesEl = document.getElementById('go-waves');
    if (wavesEl) wavesEl.textContent = `${TritiumStore.game.wave}/${TritiumStore.game.totalWaves}`;

    const elimsEl = document.getElementById('go-eliminations');
    if (elimsEl) elimsEl.textContent = TritiumStore.game.eliminations || 0;

    overlay.hidden = false;

    overlay.querySelector('[data-action="play-again"]')?.addEventListener('click', () => {
        overlay.hidden = true;
        resetGame();
    }, { once: true });
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

function initChat() {
    const chatClose = document.getElementById('chat-close');
    if (chatClose) {
        chatClose.addEventListener('click', () => toggleChat(false));
    }

    document.querySelectorAll('[data-action="chat"]').forEach(btn => {
        btn.addEventListener('click', () => toggleChat(true));
    });

    const chatInput = document.getElementById('chat-input');
    const chatSend = document.getElementById('chat-send');
    if (chatInput && chatSend) {
        chatSend.addEventListener('click', () => sendChat(chatInput));
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChat(chatInput);
            } else if (e.key === 'Escape') {
                e.preventDefault();
                chatInput.blur();
                toggleChat(false);
            }
        });
    }

    // Listen for chat:open events from panels
    EventBus.on('chat:open', () => {
        const overlay = document.getElementById('chat-overlay');
        if (overlay && overlay.hidden) {
            overlay.hidden = false;
            document.getElementById('chat-input')?.focus();
        }
    });
}

function toggleChat(open) {
    const overlay = document.getElementById('chat-overlay');
    if (!overlay) return;
    if (open === undefined) open = overlay.hidden;
    overlay.hidden = !open;
    if (open) {
        document.getElementById('chat-input')?.focus();
        EventBus.emit('chat:open');
    } else {
        EventBus.emit('chat:close');
    }
}

async function sendChat(input) {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    appendChatMessage('YOU', text, 'user');

    try {
        const resp = await fetch('/api/amy/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: text }),
        });
        const data = await resp.json();
        appendChatMessage('AMY', data.response || data.text || '...', 'amy');
    } catch (e) {
        appendChatMessage('SYSTEM', 'Failed to reach Amy', 'error');
    }
}

function appendChatMessage(sender, text, type) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;

    const msg = document.createElement('div');
    msg.className = `chat-msg chat-msg-${type}`;
    msg.innerHTML = `<span class="chat-msg-sender mono">${escapeHtml(sender)}</span><span class="chat-msg-text">${escapeHtml(text)}</span>`;
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;
}

// ---------------------------------------------------------------------------
// Legacy sidebar (only used by command.html)
// ---------------------------------------------------------------------------

function initSidebarToggle() {
    const btn = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (btn && sidebar) {
        btn.addEventListener('click', () => {
            const collapsed = sidebar.dataset.collapsed === 'true';
            sidebar.dataset.collapsed = collapsed ? 'false' : 'true';
            if (collapsed) sidebar.classList.remove('collapsed');
            else sidebar.classList.add('collapsed');
            EventBus.emit('sidebar:toggle');
        });
    }
}

function initSectionToggles() {
    document.querySelectorAll('[data-element="section-toggle"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const section = btn.closest('.sidebar-section');
            if (!section) return;
            const expanded = section.dataset.expanded === 'true';
            section.dataset.expanded = expanded ? 'false' : 'true';
            btn.setAttribute('aria-expanded', !expanded);
            const body = section.querySelector('.section-body');
            if (body) body.hidden = expanded;
        });
    });
}

function renderUnitList() {
    const list = document.getElementById('unit-list');
    if (!list) return;

    const filter = document.getElementById('unit-filter')?.value || 'all';
    const units = [];
    TritiumStore.units.forEach((u) => {
        if (filter === 'all' || u.alliance === filter) units.push(u);
    });

    if (units.length === 0) {
        list.innerHTML = '<li class="unit-list-empty">No units detected</li>';
        return;
    }

    list.innerHTML = units.map(u => {
        const alliance = u.alliance || 'unknown';
        const allianceColor = {
            friendly: 'var(--green)', hostile: 'var(--magenta)',
            neutral: 'var(--cyan)', unknown: 'var(--amber)',
        }[alliance] || 'var(--text-dim)';
        const icon = { rover: 'R', drone: 'D', turret: 'T', person: 'P', hostile_kid: 'H' }[u.type] || '?';
        const hp = u.health !== undefined && u.maxHealth ? `${Math.round(u.health)}/${u.maxHealth}` : '';
        return `<li class="unit-list-item" data-unit-id="${escapeHtml(u.id)}" role="option">
            <span class="unit-icon-mini" style="color:${allianceColor}">${icon}</span>
            <span class="unit-item-name">${escapeHtml(u.name || u.id)}</span>
            <span class="unit-item-hp mono" style="font-size:0.55rem;color:var(--text-dim)">${hp}</span>
        </li>`;
    }).join('');

    list.querySelectorAll('.unit-list-item').forEach(item => {
        item.addEventListener('click', () => {
            selectUnit(item.dataset.unitId);
        });
    });
}

document.getElementById('unit-filter')?.addEventListener('change', renderUnitList);

function renderAlertFeed(alerts) {
    const feed = document.getElementById('alert-feed');
    if (!feed) return;

    if (!alerts || alerts.length === 0) {
        feed.innerHTML = '<li class="alert-feed-empty">No alerts</li>';
        return;
    }

    feed.innerHTML = alerts.slice(0, 20).map(a => {
        const cls = a.type === 'escalation' ? 'alert-critical' :
                    a.type === 'warning' ? 'alert-warning' : 'alert-info';
        const time = a.time ? new Date(a.time).toLocaleTimeString().substr(0, 5) : '';
        return `<li class="alert-item ${cls}">
            <span class="alert-text">${escapeHtml(a.message)}</span>
            <span class="alert-time mono">${time}</span>
        </li>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Unit selection
// ---------------------------------------------------------------------------

function selectUnit(id) {
    TritiumStore.set('map.selectedUnitId', id);
    EventBus.emit('unit:selected', { id });
}

// ---------------------------------------------------------------------------
// Game controls
// ---------------------------------------------------------------------------

function initGameControls() {
    document.getElementById('btn-begin-war')?.addEventListener('click', beginWar);
    document.getElementById('btn-reset-game')?.addEventListener('click', resetGame);

    document.querySelectorAll('[data-action="dispatch"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = TritiumStore.get('map.selectedUnitId');
            if (id) EventBus.emit('unit:dispatch-mode', { id });
        });
    });

    document.querySelectorAll('[data-action="recall"]').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = TritiumStore.get('map.selectedUnitId');
            if (id) dispatchUnit(id, 0, 0);
        });
    });
}

async function beginWar() {
    MissionModal.show();
}

async function resetGame() {
    try {
        await fetch('/api/game/reset', { method: 'POST' });
        const overlay = document.getElementById('game-over-overlay');
        if (overlay) overlay.hidden = true;
    } catch (e) {
        showToast('Failed to reset game', 'alert');
    }
}

async function dispatchUnit(targetId, x, y) {
    try {
        await fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'dispatch', target_id: targetId, x, y }),
        });
    } catch (e) {
        showToast('Dispatch failed', 'alert');
    }
}

// ---------------------------------------------------------------------------
// Map mode buttons
// ---------------------------------------------------------------------------

function initMapModes() {
    document.querySelectorAll('[data-map-mode]').forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mapMode;
            TritiumStore.set('map.mode', mode);
            document.querySelectorAll('[data-map-mode]').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            EventBus.emit('map:mode', { mode });
        });
    });
}

// ---------------------------------------------------------------------------
// Legacy Amy action buttons (only used by command.html)
// ---------------------------------------------------------------------------

function initAmyActions() {
    document.querySelectorAll('[data-action="attend"]').forEach(btn => {
        btn.addEventListener('click', async () => {
            try {
                await fetch('/api/amy/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'attend' }),
                });
            } catch (e) {
                showToast('Command failed', 'alert');
            }
        });
    });
}

// ---------------------------------------------------------------------------
// Help overlay
// ---------------------------------------------------------------------------

function initHelp() {
    const overlay = document.getElementById('help-overlay');
    if (!overlay) return;

    overlay.querySelector('[data-element="help-close"]')?.addEventListener('click', () => {
        overlay.hidden = true;
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.hidden = true;
    });
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

function initModal() {
    const overlay = document.getElementById('modal-overlay');
    if (!overlay) return;

    document.getElementById('modal-close')?.addEventListener('click', () => {
        overlay.hidden = true;
    });

    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.hidden = true;
    });
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts
// ---------------------------------------------------------------------------

function initKeyboard() {
    document.addEventListener('keydown', (e) => {
        // Allow Escape even when focused on an input/textarea (to close overlays)
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
            if (e.key === 'Escape') {
                e.target.blur();
                // Fall through to Escape handler below
            } else {
                return;
            }
        }

        // Ctrl+Shift+S: save layout
        if (e.ctrlKey && e.shiftKey && (e.key === 'S' || e.key === 's')) {
            e.preventDefault();
            if (menuBarEl) focusSaveInput(menuBarEl);
            return;
        }

        // Ctrl+1-4: switch layouts
        if (e.ctrlKey && !e.shiftKey && layoutManager) {
            const layoutMap = { '1': 'commander', '2': 'observer', '3': 'tactical', '4': 'battle' };
            if (layoutMap[e.key]) {
                e.preventDefault();
                layoutManager.apply(layoutMap[e.key]);
                return;
            }
        }

        switch (e.key) {
            case '?':
                document.getElementById('help-overlay').hidden =
                    !document.getElementById('help-overlay')?.hidden;
                break;
            case 'c':
            case 'C':
                toggleChat();
                break;
            case 'Escape':
                toggleChat(false);
                document.getElementById('help-overlay').hidden = true;
                document.getElementById('modal-overlay').hidden = true;
                document.getElementById('game-over-overlay').hidden = true;
                MissionModal.hide();
                break;
            case '/':
                e.preventDefault();
                toggleChat(true);
                break;
            case 'm':
            case 'M':
                panelManager.toggle('minimap');
                break;
            case 'o':
            case 'O':
                document.querySelector('[data-map-mode="observe"]')?.click();
                break;
            case 't':
            case 'T':
                document.querySelector('[data-map-mode="tactical"]')?.click();
                break;
            case 's':
            case 'S':
                document.querySelector('[data-map-mode="setup"]')?.click();
                break;
            case 'b':
            case 'B':
                if (TritiumStore.game.phase === 'idle' || TritiumStore.game.phase === 'setup') {
                    beginWar();
                }
                break;
            case 'n':
            case 'N':
                // Mission generation modal (open/close)
                if (MissionModal.isVisible()) {
                    MissionModal.hide();
                } else if (TritiumStore.game.phase === 'idle' || TritiumStore.game.phase === 'setup') {
                    MissionModal.show();
                }
                break;
            // Panel toggles (unified layout)
            case '1':
                if (panelManager) panelManager.toggle('amy');
                break;
            case '2':
                if (panelManager) panelManager.toggle('units');
                break;
            case '3':
                if (panelManager) panelManager.toggle('alerts');
                break;
            case '4':
                if (panelManager) panelManager.toggle('game');
                break;
            case '5':
                if (panelManager) panelManager.toggle('mesh');
                break;
            case 'f':
            case 'F':
                _mapActions ? _mapActions.centerOnAction() : centerOnAction();
                break;
            case 'r':
            case 'R':
                _mapActions ? _mapActions.resetCamera() : resetCamera();
                break;
            case '[':
                _mapActions ? _mapActions.zoomOut() : zoomOut();
                break;
            case ']':
                _mapActions ? _mapActions.zoomIn() : zoomIn();
                break;
            case 'v':
            case 'V':
                if (_activeMapModule && _activeMapModule.toggleTilt) {
                    _activeMapModule.toggleTilt();
                } else if (typeof toggleTilt === 'function') {
                    toggleTilt();
                }
                break;
            case 'k':
            case 'K':
                _mapActions ? _mapActions.toggleBuildings() : toggleBuildings();
                break;
            case 'g':
            case 'G':
                _mapActions ? _mapActions.toggleRoads() : toggleRoads();
                break;
            case 'i':
            case 'I':
                _mapActions ? _mapActions.toggleSatellite() : toggleSatellite();
                break;
            case 'h':
            case 'H':
                _mapActions ? _mapActions.toggleTerrain() : toggleTerrain();
                break;
            case 'Tab':
                if (panelManager) {
                    // In unified layout, Tab cycles panel focus
                    e.preventDefault();
                } else {
                    // Legacy: toggle sidebar
                    e.preventDefault();
                    document.getElementById('sidebar-toggle')?.click();
                }
                break;
        }
    });
}

// ---------------------------------------------------------------------------
// Fetch initial Amy status
// ---------------------------------------------------------------------------

async function fetchAmyStatus() {
    try {
        const resp = await fetch('/api/amy/status');
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.state) TritiumStore.set('amy.state', data.state);
        if (data.mood) TritiumStore.set('amy.mood', data.mood);
        if (data.last_thought) TritiumStore.set('amy.lastThought', data.last_thought);
    } catch (e) {
        // Amy might not be running
    }
}

// Active map module reference for dynamic dispatch after renderer switch
let _activeMapModule = null;
// Module-scoped reference so keyboard handlers can call through the proxy
let _mapActions = null;

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

// Export for use by other modules
export { showToast, showBanner, selectUnit, dispatchUnit, escapeHtml, ws, panelManager, layoutManager };

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
