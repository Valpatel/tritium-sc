// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// TRITIUM Command Center -- entry point
// Initializes store, event bus, WebSocket, panel system, and UI bindings.
// Serves both unified (floating panels) and legacy (sidebar+bottom bar) layouts.
//
// Include via: <script type="module" src="/static/js/command/main.js"></script>

import { _esc } from '/lib/utils.js';
import { TritiumStore } from './store.js';
import { EventBus } from '/lib/events.js';
import { WebSocketManager } from './websocket.js';
import { initMap, destroyMap, toggleSatellite, toggleRoads, toggleGrid, toggleBuildings, toggleFog, toggleTerrain, toggleUnits, toggleLabels, toggleModels, toggleWaterways, toggleParks, toggleMesh, toggleMeshNodes, toggleMeshLinks, toggleMeshCoverage, toggleThoughts, toggleAllLayers, setAllLayers, toggleTracers, toggleExplosions, toggleParticles, toggleHitFlashes, toggleFloatingText, toggleKillFeed, toggleScreenFx, toggleBanners, toggleLayerHud, toggleHealthBars, toggleSelectionFx, getMapState, centerOnAction, resetCamera, zoomIn, zoomOut, toggleTilt, setLayers, setMapMode, toggleSquadHulls, toggleAutoFollow, toggleGeoLayers, togglePatrolRoutes, toggleWeaponRange, toggleHeatmap, toggleSwarmHull, toggleHazardZones, toggleHostileObjectives, toggleCrowdDensity, toggleCoverPoints, toggleUnitSignals, toggleHostileIntel, togglePredictionCones, toggleCoverageOverlap, toggleGeofenceZones, toggleCitySim, getCitySimStats, cycleSimTimeScale, spawnEmergencyVehicle, toggleRoadGraph, toggleBloom } from './map-maplibre.js';
import { PanelManager } from './panel-manager.js';
import { LayoutManager } from './layout-manager.js';
import { createMenuBar, focusSaveInput } from './menu-bar.js';
import { AmyPanelDef } from './panels/amy.js';
import { UnitsPanelDef } from './panels/units.js';
// REMOVED (duplicate — unified-alerts kept): import { AlertsPanelDef } from './panels/alerts.js';
import { GameHudPanelDef } from './panels/game-hud.js';
import { CitySimPanelDef } from './panels/city-sim.js';
import { SimulationContainerDef } from './panels/simulation-container.js';
import { SensorsContainerDef } from './panels/sensors-container.js';
import { IntelligenceContainerDef } from './panels/intelligence-container.js';
import { CommsContainerDef } from './panels/comms-container.js';
import { TacticalContainerDef } from './panels/tactical-container.js';
import { FleetContainerDef } from './panels/fleet-container.js';
import { CommanderContainerDef } from './panels/commander-container.js';
import { SystemContainerDef } from './panels/system-container.js';
// MeshPanelDef replaced by meshtastic addon's unified tabbed panel
// import { MeshPanelDef } from './panels/mesh.js';
import { AudioPanelDef } from './panels/audio.js';
import { EscalationPanelDef } from './panels/escalation.js';
import { EventsPanelDef } from './panels/events.js';
import { PatrolPanelDef } from './panels/patrol.js';
import { ScenariosPanelDef } from './panels/scenarios.js';
import { SystemPanelDef } from './panels/system.js';
import { MinimapPanelDef } from './panels/minimap.js';
import { GraphlingsPanelDef } from './panels/graphlings.js';
import { ReplayPanelDef } from './panels/replay.js';
import { BattleStatsPanelDef } from './panels/stats.js';
import { SensorNetPanelDef } from './panels/sensors.js';
import { UnitInspectorPanelDef } from './panels/unit-inspector.js';
import { CamerasPanelDef } from './panels/cameras.js';
import { CameraFeedsPanelDef } from './panels/camera-feeds.js';
import { SearchPanelDef } from './panels/search.js';
import { TakPanelDef } from './panels/tak.js';
import { VideosPanelDef } from './panels/videos.js';
// REMOVED (duplicate — zone-manager kept): import { ZonesPanelDef } from './panels/zones.js';
import { LayersPanelDef } from './panels/layers.js';
// REMOVED (duplicate — fleet-dashboard + edge-tracker kept): import { FleetPanelDef } from './panels/fleet.js';
import { EdgeTrackerPanelDef } from './panels/edge-tracker.js';
import { AssetsPanelDef } from './panels/assets.js';
import { FleetDashboardPanelDef } from './panels/fleet-dashboard.js';
// REMOVED (duplicate — zone-manager kept): import { GeofencePanelDef } from './panels/geofence.js';
// REMOVED (duplicate — search kept): import { TargetSearchPanelDef } from './panels/target-search.js';
import { DossiersPanelDef } from './panels/dossiers.js';
import { GraphExplorerPanelDef } from './panels/graph-explorer.js';
import { TimelinePanelDef } from './panels/timeline.js';
import { NotificationsPanelDef } from './panels/notifications.js';
import { HeatmapPanelDef } from './panels/heatmap.js';
// REMOVED (duplicate — heatmap kept): import { HeatmapTimelinePanelDef } from './panels/heatmap-timeline.js';
import { TestingPanelDef } from './panels/testing.js';
import { DeviceManagerPanelDef } from './panels/device-manager.js';
// REMOVED (duplicate — device-manager kept): import { DeviceCapabilitiesPanelDef } from './panels/device-capabilities.js';
import { AutomationPanelDef } from './panels/automation.js';
import { RfMotionPanelDef } from './panels/rf-motion.js';
import { EdgeIntelligencePanelDef } from './panels/edge-intelligence.js';
// REMOVED (duplicate — system-health-dashboard kept): import { SystemHealthPanelDef } from './panels/system-health.js';
import { QuickStartPanelDef } from './panels/quick-start.js';
import { BookmarksPanelDef } from './panels/bookmarks.js';
import { MissionsPanelDef } from './panels/missions.js';
import { TargetComparePanelDef } from './panels/target-compare.js';
import { MultiCameraPanelDef } from './panels/multi-camera.js';
import { TargetMergePanelDef } from './panels/target-merge.js';
import { AmyConversationPanelDef } from './panels/amy-conversation.js';
import { ExportSchedulerPanelDef } from './panels/export-scheduler.js';
import { OpsDashboardPanelDef } from './panels/ops-dashboard.js';
import { DossierGroupsPanelDef } from './panels/dossier-groups.js';
// REMOVED (duplicate — dossiers kept): import { DossierTimelinePanelDef } from './panels/dossier-timeline.js';
import { SetupWizardPanelDef, ConfigStore } from './panels/setup-wizard.js';
import { ActivityFeedPanelDef } from './panels/activity-feed.js';
import { MqttInspectorPanelDef } from './panels/mqtt-inspector.js';
import { AnnotationsPanelDef } from './panels/annotations.js';
import { NotificationPrefsPanelDef } from './panels/notification_prefs.js';
import { WatchlistPanelDef } from './panels/watchlist.js';
import { MapSharePanelDef, checkShareHash } from './panels/map-share.js';
import { KeyboardMacrosPanelDef } from './panels/keyboard-macros.js';
import { GridOverlayPanelDef, toggleGridOverlay } from './panels/grid-overlay.js';
import { DeploymentPanelDef } from './panels/deployment.js';
import { FloorPlanPanelDef } from './panels/floorplan.js';
import { BuildingOccupancyPanelDef } from './panels/building-occupancy.js';
// REMOVED (duplicate — analytics-panel kept): import { AnalyticsDashboardPanelDef } from './panels/analytics-dashboard.js';
import { SensorHealthPanelDef } from './panels/sensor-health.js';
import { AcousticIntelligencePanelDef } from './panels/acoustic-intelligence.js';
import { BehavioralIntelligencePanelDef } from './panels/behavioral-intelligence.js';
import { MapReplayPanelDef } from './panels/map-replay.js';
import { VoiceCommandPanelDef } from './panels/voice-command.js';
import { WiFiFingerprintPanelDef } from './panels/wifi-fingerprint.js';
import { CommandHistoryPanelDef } from './panels/command-history.js';
import { SecurityAuditPanelDef } from './panels/security-audit.js';
import { DwellMonitorPanelDef } from './panels/dwell-monitor.js';
import { FederationPanelDef } from './panels/federation.js';
import { LprPanelDef } from './panels/lpr.js';
import { ReIDMatchesPanelDef } from './panels/reid-matches.js';
import { EdgeDiagnosticsPanelDef } from './panels/edge-diagnostics.js';
import { FusionDashboardPanelDef } from './panels/fusion-dashboard.js';
import { OperatorActivityPanelDef } from './panels/operator-activity.js';
import { SwarmCoordinationPanelDef } from './panels/swarm-coordination.js';
import { TrainingDashboardPanelDef } from './panels/training-dashboard.js';
import { ConvoyPanelDef } from './panels/convoy-panel.js';
import { OperatorCursorsPanelDef } from './panels/operator-cursors-panel.js';
import { WeatherOverlayPanelDef } from './panels/weather-overlay-panel.js';
import { TrailExportPanelDef } from './panels/trail-export-panel.js';
import { MapLayerSwitcherPanelDef } from './panels/map-layer-switcher.js';
import { CollaborationHubPanelDef } from './panels/collaboration-hub.js';
import { IndoorPositioningPanelDef } from './panels/indoor-positioning-panel.js';
import { UnifiedAlertsPanelDef } from './panels/alerts-panel.js';
// REMOVED (duplicate — dossiers kept): import { TargetDossierPanelDef } from './panels/target-dossier-panel.js';
import { RadarScopePanelDef } from './panels/radar-scope.js';
import { SdrWaterfallPanelDef } from './panels/sdr-waterfall.js';
import { AdsbTablePanelDef } from './panels/adsb-table.js';
import { AddonsManagerPanelDef } from './panels/addons-manager.js';
import { SitAwarePanelDef } from './panels/sitaware-panel.js';
import { SystemHealthDashboardPanelDef } from './panels/system-health-panel.js';
import { ZoneManagerPanelDef } from './panels/zone-manager-panel.js';
import { AnalyticsPanelDef } from './panels/analytics-panel.js';
import { AmyBriefingPanelDef } from './panels/amy-briefing-panel.js';
import { ThreatFeedsPanelDef } from './panels/threat-feeds-panel.js';
import { loadAddons } from './addon-loader.js';
import { PredictionEllipseManager } from './prediction-ellipses.js';
import { initScreenshotHotkey } from './panels/map-screenshot.js';
import { MissionModal, initMissionModal } from './mission-modal.js';
import { initTargetCounter } from './target-counter.js';
import { initTargetFilter, matchesFilter, getTargetFilters } from './target-filter.js';
import { initCommandPalette, openCommandPalette } from './command-palette.js';
import { createTacticalBanner } from './tactical-banner.js';
import { createMapQuickToggles } from './map-quick-toggles.js';
import { TargetTrailManager } from './target-trails.js';
import { HandoffLineManager } from './handoff-lines.js';
import { ConvoyOverlayManager } from './convoy-overlay.js';
import { startAdsbOverlay, toggleAdsbOverlay } from './adsb-overlay.js';
import { AddonMapLayers } from './addon-map-layers.js';

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

    // Target counter widget (live target counts in header)
    initTargetCounter();

    // WebSocket
    ws.connect();

    // Forward viewport updates from the map to the backend for LOD fidelity
    EventBus.on('viewport:update', (data) => {
        ws.send({
            type: 'viewport_update',
            center_lat: data.center_lat,
            center_lng: data.center_lng,
            zoom: data.zoom,
            radius: data.radius,
        });
    });

    // Forward city-sim sensor bridge sightings to backend via WebSocket
    EventBus.on('sim:sighting_batch', (data) => {
        if (!data) return;
        const sightings = data.sightings || [];
        const detections = data.detections || [];
        const batch = [...sightings, ...detections];
        if (batch.length > 0) {
            ws.send({ type: 'sim_sighting_batch', data: batch });
        }
    });

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
            // Toggle pulsing threat indicator when threats are active
            threatEl.classList.toggle('has-threats', hostileCount > 0);
        }

        // Status bar
        const aliveEl = document.getElementById('status-alive');
        if (aliveEl) aliveEl.textContent = `${friendlyCount} alive`;
        const threatsEl = document.getElementById('status-threats');
        if (threatsEl) threatsEl.textContent = `${hostileCount} threats`;

        // Legacy sidebar unit list (if present)
        renderUnitList();
    });

    // Game state updates (header + game over overlay + auto-fog + auto-panels)
    TritiumStore.on('game.phase', (phase) => {
        // Show/hide game score in header
        const scoreArea = document.getElementById('game-score-area');
        if (scoreArea) scoreArea.hidden = (phase === 'idle' || phase === 'setup' || !phase);

        // Game over overlay
        if (phase === 'victory' || phase === 'defeat') {
            showGameOver(phase);
        } else if (phase === 'idle' || phase === 'setup') {
            // Dismiss game-over overlay on reset
            const goOverlay = document.getElementById('game-over-overlay');
            if (goOverlay) goOverlay.hidden = true;
        }

        // Auto-open Game HUD panel when battle starts (countdown or active)
        // so the operator can see wave/score/elimination stats and kill feed
        if ((phase === 'countdown' || phase === 'active') && panelManager && !panelManager.isOpen('game')) {
            panelManager.open('game');
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
        if (header) {
            header.textContent = score.toLocaleString();
            // Brief glow pulse on score change
            header.style.color = '#fcee0a';
            header.style.textShadow = '0 0 8px #fcee0a';
            clearTimeout(header._pulseTimer);
            header._pulseTimer = setTimeout(() => {
                header.style.color = '';
                header.style.textShadow = '';
            }, 400);
        }
    });

    TritiumStore.on('game.eliminations', (elims) => {
        const header = document.getElementById('game-eliminations');
        if (header) header.textContent = elims;
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

    // Geofence enter/exit push notifications — toast + notification bell
    // Restricted zones = magenta (alert), monitored = cyan (amy), safe = green (robot)
    EventBus.on('notification:geofence', (data) => {
        const dir = data.direction === 'enter' ? 'ENTERED' : 'EXITED';
        const zone = data.zone_name || data.zone_id || '?';
        const target = (data.target_id || '?').substring(0, 16);
        const zoneType = data.zone_type || 'monitored';
        const severity = zoneType === 'restricted' ? 'alert'
            : zoneType === 'safe' ? 'robot'
            : 'amy';
        showToast(`GEOFENCE: Target ${target} ${dir} zone ${zone}`, severity);
        // Push as a notification for the bell badge
        EventBus.emit('notification:new', {
            id: `gf_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            title: `GEOFENCE ${dir}`,
            message: `${target} ${dir.toLowerCase()} zone "${zone}" (${data.zone_type || 'monitored'})`,
            severity: data.zone_type === 'restricted' ? 'critical' : 'warning',
            source: 'geofence',
            entity_id: data.target_id,
            timestamp: data.timestamp || (Date.now() / 1000),
            read: false,
        });
    });

    // Initialize tactical map
    initMap();

    // Dismiss loading screen once map is fully loaded
    EventBus.on('map:ready', () => {
        if (window.hideLoading) window.hideLoading();
    });

    // Target trail manager (speed-colored movement trails on map)
    const trailManager = new TargetTrailManager();
    trailManager.start();

    // Handoff line visualization — animated arcs when targets move between sensors
    const handoffManager = new HandoffLineManager();
    handoffManager.start();

    // Check URL for shared map view
    checkShareHash();

    // Target filter overlay (on tactical map)
    const tacticalArea = document.getElementById('tactical-area');
    if (tacticalArea) {
        initTargetFilter(tacticalArea);

        // Map layer quick toggles (floating buttons on map right edge)
        createMapQuickToggles(tacticalArea);
    }

    // Expose filter functions for map renderers
    window.matchesTargetFilter = matchesFilter;
    window.getTargetFilters = getTargetFilters;

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

    // WASD control mode indicator
    TritiumStore.on('controlledUnitId', (id) => {
        let indicator = document.getElementById('wasd-control-indicator');
        if (id) {
            const unit = TritiumStore.units.get(id);
            const name = unit?.name || id;
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.id = 'wasd-control-indicator';
                indicator.className = 'wasd-control-indicator';
                document.body.appendChild(indicator);
            }
            indicator.innerHTML =
                `<span class="wasd-label mono">CONTROLLING: ${_esc(name)}</span>` +
                `<span class="wasd-hint mono">WASD move // ESC release</span>`;
            indicator.hidden = false;
        } else if (indicator) {
            indicator.hidden = true;
        }
    });

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
                    'weapon_jam', 'sensor_triggered',
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
                        audioMgr.play('countdown_go');
                    } else if (d.state === 'idle' || d.state === 'victory' || d.state === 'defeat') {
                        audioMgr.stopAmbient();
                    }
                    if (d.state === 'countdown') audioMgr.play('countdown_tick');
                    if (d.state === 'victory') audioMgr.play('victory_fanfare');
                    else if (d.state === 'defeat') audioMgr.play('defeat_sting');
                });

                // Weapon malfunction audio cues
                EventBus.on('combat:weapon_jam', () => {
                    audioMgr.play('weapon_jam');
                });
                EventBus.on('combat:ammo_low', () => {
                    audioMgr.play('reload');
                });
                EventBus.on('combat:ammo_depleted', () => {
                    audioMgr.play('weapon_jam');
                });

                // Environment and tactical audio cues
                EventBus.on('hazard:spawned', () => {
                    audioMgr.play('alert_tone');
                });
                EventBus.on('sensor:triggered', () => {
                    audioMgr.play('sensor_triggered');
                });
                EventBus.on('dispatch:speech', () => {
                    audioMgr.play('dispatch_ack');
                });
                EventBus.on('alert:new', () => {
                    audioMgr.play('alert_tone');
                });
                EventBus.on('announcer', () => {
                    audioMgr.play('dispatch_ack');
                });
                EventBus.on('escalation:change', () => {
                    audioMgr.play('escalation_siren');
                });

                // ---- Notification sound effects ----
                // Play subtle audio cues for critical notifications.
                // Respects a mute toggle stored in TritiumStore.
                EventBus.on('notification:new', (data) => {
                    if (TritiumStore.get('notifications.muted')) return;
                    const severity = data.severity || data.level || 'info';
                    const source = data.source || '';
                    // Map notification types to appropriate sounds
                    if (source === 'geofence' || severity === 'critical') {
                        audioMgr.play('perimeter_breach');
                    } else if (source === 'threat' || source === 'escalation') {
                        audioMgr.play('hostile_detected');
                    } else if (source === 'suspicious_device' || source === 'new_device') {
                        audioMgr.play('sensor_triggered');
                    } else if (severity === 'warning') {
                        audioMgr.play('alert_tone');
                    } else if (severity === 'error') {
                        audioMgr.play('alert_critical');
                    }
                    // info-level notifications are silent by default
                });

                // Geofence breach gets its own dedicated sound
                EventBus.on('geofence:breach', () => {
                    if (!TritiumStore.get('notifications.muted')) {
                        audioMgr.play('perimeter_breach');
                    }
                });

                // Threat escalation sound
                EventBus.on('threat:escalated', () => {
                    if (!TritiumStore.get('notifications.muted')) {
                        audioMgr.play('escalation_siren');
                    }
                });

                console.log('[TRITIUM] Audio initialized + combat events wired');
            } catch (e) {
                console.warn('[TRITIUM] Audio init failed:', e);
            }
        }
    };
    document.addEventListener('click', _initAudio, { once: true });
    document.addEventListener('keydown', _initAudio, { once: true });
    // Audio init only on user gesture (click/keydown). Do NOT init on
    // game:state events — WebSocket delivers state before user gesture,
    // causing "AudioContext not allowed to start" browser warnings.

    // Demo start button — centered on map, visible when no targets, fades when targets appear
    const demoOverlay = document.getElementById('demo-start-overlay');
    const demoBtn = document.getElementById('demo-start-btn');
    if (demoBtn && demoOverlay) {
        const _fadeDemoOverlay = () => {
            demoOverlay.style.opacity = '0';
            demoOverlay.style.pointerEvents = 'none';
            setTimeout(() => { demoOverlay.classList.add('hidden'); }, 400);
        };

        demoBtn.addEventListener('click', async () => {
            demoBtn.disabled = true;
            demoBtn.textContent = '[ STARTING... ]';
            try {
                const res = await fetch('/api/demo/start', { method: 'POST' });
                const data = await res.json();
                if (res.ok) {
                    EventBus.emit('toast:show', { message: 'Demo mode started', type: 'info' });
                    _fadeDemoOverlay();
                } else {
                    EventBus.emit('toast:show', { message: data.error || 'Failed to start demo', type: 'alert' });
                    demoBtn.disabled = false;
                    demoBtn.textContent = '[ START DEMO ]';
                }
            } catch (e) {
                EventBus.emit('toast:show', { message: 'Demo start failed: ' + e.message, type: 'alert' });
                demoBtn.disabled = false;
                demoBtn.textContent = '[ START DEMO ]';
            }
        });

        // Fade demo overlay once targets appear on the map
        TritiumStore.on('units', () => {
            if (TritiumStore.units.size > 0) _fadeDemoOverlay();
        });

        // Hide immediately if demo already running (no need to fade on reload)
        fetch('/api/demo/status').then(r => r.ok ? r.json() : {}).then(d => {
            if (d.active) demoOverlay.classList.add('hidden');
        }).catch(() => {});
    }

    // Start Battle button — visible when targets on map and game is idle
    const battleOverlay = document.getElementById('war-begin-btn');
    const battleBtn = document.getElementById('battle-start-btn');
    if (battleBtn && battleOverlay) {
        battleBtn.addEventListener('click', () => {
            beginWar();
        });

        // Show battle button when targets appear and game is idle
        function _updateBattleBtn() {
            const phase = TritiumStore.game.phase;
            const hasTargets = TritiumStore.units && TritiumStore.units.size > 0;
            const isIdle = !phase || phase === 'idle' || phase === 'setup';
            if (hasTargets && isIdle) {
                battleOverlay.style.display = '';
            } else {
                battleOverlay.style.display = 'none';
            }
        }
        TritiumStore.on('units', _updateBattleBtn);
        TritiumStore.on('game.phase', _updateBattleBtn);
        // Initial check
        _updateBattleBtn();
    }

    // Welcome tooltip — show once on first visit
    _showWelcomeTooltip();

    console.log('%c[TRITIUM] Command Center ready', 'color: #05ffa1; font-weight: bold;');
}

// ---------------------------------------------------------------------------
// Welcome Tooltip (first visit only)
// ---------------------------------------------------------------------------

function _showWelcomeTooltip() {
    const STORAGE_KEY = 'tritium-welcome-shown';
    if (localStorage.getItem(STORAGE_KEY)) return;

    const tip = document.createElement('div');
    tip.id = 'welcome-tooltip';
    tip.style.cssText = `
        position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%) translateY(12px); z-index: 10000;
        max-width: 360px; padding: 14px 20px;
        background: rgba(10, 10, 20, 0.92);
        border: 1px solid rgba(0, 240, 255, 0.2);
        border-radius: 6px;
        font-family: 'JetBrains Mono', 'Inter', monospace;
        font-size: 11px; line-height: 1.6;
        color: #c0c0d0;
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5), 0 0 12px rgba(0, 240, 255, 0.06);
        opacity: 0;
        transition: opacity 0.4s ease, transform 0.4s ease;
        pointer-events: auto;
    `;
    tip.innerHTML = `
        <div style="color:#00f0ff;font-weight:bold;font-size:11px;margin-bottom:8px;letter-spacing:1.5px">UNIFIED OPERATING PICTURE</div>
        <div style="margin-bottom:5px;color:#888">Track every target across all sensors. Click <span style="color:#05ffa1;font-weight:bold">START DEMO</span> above to begin.</div>
        <div style="margin-bottom:5px;color:#888">Click targets on the map to <span style="color:#00f0ff">inspect</span> them.</div>
        <div style="margin-bottom:8px;color:#888">Open <span style="color:#fcee0a">SIM</span> menu for battles, city sim, and more.</div>
        <button id="welcome-dismiss" style="
            background: transparent; border: 1px solid rgba(0, 240, 255, 0.2); color: rgba(0, 240, 255, 0.7);
            font-family: 'JetBrains Mono', monospace; font-size: 10px;
            padding: 3px 12px; border-radius: 3px; cursor: pointer;
            transition: background 0.2s, border-color 0.2s;
        ">GOT IT</button>
    `;
    document.body.appendChild(tip);

    // Animate in
    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            tip.style.opacity = '1';
            tip.style.transform = 'translateX(-50%) translateY(0)';
        });
    });

    let dismissed = false;
    const dismiss = () => {
        if (dismissed) return;
        dismissed = true;
        localStorage.setItem(STORAGE_KEY, '1');
        tip.style.opacity = '0';
        tip.style.transform = 'translateX(-50%) translateY(12px)';
        setTimeout(() => tip.remove(), 400);
    };

    tip.querySelector('#welcome-dismiss').addEventListener('click', dismiss);

    // Auto-dismiss after 12 seconds or when demo starts (targets appear)
    setTimeout(dismiss, 12000);
    TritiumStore.on('units', () => {
        if (TritiumStore.units.size > 0) dismiss();
    });
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
    // REMOVED (duplicate — unified-alerts kept): panelManager.register(AlertsPanelDef);
    panelManager.register(GameHudPanelDef);
    panelManager.register(CitySimPanelDef);
    panelManager.register(SimulationContainerDef);
    panelManager.register(SensorsContainerDef);
    panelManager.register(IntelligenceContainerDef);
    panelManager.register(CommsContainerDef);
    panelManager.register(TacticalContainerDef);
    panelManager.register(FleetContainerDef);
    panelManager.register(CommanderContainerDef);
    panelManager.register(SystemContainerDef);
    // MeshPanelDef replaced by meshtastic addon — loaded dynamically via addon-loader
    panelManager.register(AudioPanelDef);
    panelManager.register(EscalationPanelDef);
    panelManager.register(EventsPanelDef);
    panelManager.register(PatrolPanelDef);
    panelManager.register(ScenariosPanelDef);
    panelManager.register(SystemPanelDef);
    panelManager.register(MinimapPanelDef);
    panelManager.register(GraphlingsPanelDef);
    panelManager.register(ReplayPanelDef);
    panelManager.register(BattleStatsPanelDef);
    panelManager.register(SensorNetPanelDef);
    panelManager.register(UnitInspectorPanelDef);
    panelManager.register(CamerasPanelDef);
    panelManager.register(CameraFeedsPanelDef);
    panelManager.register(SearchPanelDef);
    panelManager.register(TakPanelDef);
    panelManager.register(VideosPanelDef);
    // REMOVED (duplicate — zone-manager kept): panelManager.register(ZonesPanelDef);
    panelManager.register(LayersPanelDef);
    // REMOVED (duplicate — fleet-dashboard + edge-tracker kept): panelManager.register(FleetPanelDef);
    panelManager.register(EdgeTrackerPanelDef);
    panelManager.register(AssetsPanelDef);
    panelManager.register(FleetDashboardPanelDef);
    // REMOVED (duplicate — zone-manager kept): panelManager.register(GeofencePanelDef);
    // REMOVED (duplicate — search kept): panelManager.register(TargetSearchPanelDef);
    panelManager.register(DossiersPanelDef);
    panelManager.register(GraphExplorerPanelDef);
    panelManager.register(TimelinePanelDef);
    panelManager.register(NotificationsPanelDef);
    panelManager.register(HeatmapPanelDef);
    // REMOVED (duplicate — heatmap kept): panelManager.register(HeatmapTimelinePanelDef);
    panelManager.register(TestingPanelDef);
    panelManager.register(DeviceManagerPanelDef);
    // REMOVED (duplicate — device-manager kept): panelManager.register(DeviceCapabilitiesPanelDef);
    panelManager.register(AutomationPanelDef);
    panelManager.register(RfMotionPanelDef);
    panelManager.register(EdgeIntelligencePanelDef);
    // REMOVED (duplicate — system-health-dashboard kept): panelManager.register(SystemHealthPanelDef);
    panelManager.register(QuickStartPanelDef);
    panelManager.register(BookmarksPanelDef);
    panelManager.register(TargetComparePanelDef);
    panelManager.register(MissionsPanelDef);
    panelManager.register(MultiCameraPanelDef);
    panelManager.register(TargetMergePanelDef);
    panelManager.register(AmyConversationPanelDef);
    panelManager.register(ExportSchedulerPanelDef);
    panelManager.register(OpsDashboardPanelDef);
    panelManager.register(DossierGroupsPanelDef);
    // REMOVED (duplicate — dossiers kept): panelManager.register(DossierTimelinePanelDef);
    // REMOVED (duplicate — dossiers kept): panelManager.register(TargetDossierPanelDef);
    panelManager.register(SetupWizardPanelDef);
    panelManager.register(ActivityFeedPanelDef);
    panelManager.register(MqttInspectorPanelDef);
    panelManager.register(AnnotationsPanelDef);
    panelManager.register(NotificationPrefsPanelDef);
    panelManager.register(WatchlistPanelDef);
    panelManager.register(MapSharePanelDef);
    panelManager.register(KeyboardMacrosPanelDef);
    panelManager.register(GridOverlayPanelDef);
    panelManager.register(DeploymentPanelDef);
    panelManager.register(FloorPlanPanelDef);
    panelManager.register(BuildingOccupancyPanelDef);
    // REMOVED (duplicate — analytics-panel kept): panelManager.register(AnalyticsDashboardPanelDef);
    panelManager.register(SensorHealthPanelDef);
    panelManager.register(AcousticIntelligencePanelDef);
    panelManager.register(BehavioralIntelligencePanelDef);
    panelManager.register(MapReplayPanelDef);
    panelManager.register(VoiceCommandPanelDef);
    panelManager.register(WiFiFingerprintPanelDef);
    panelManager.register(CommandHistoryPanelDef);
    panelManager.register(SecurityAuditPanelDef);
    panelManager.register(DwellMonitorPanelDef);
    panelManager.register(FederationPanelDef);
    panelManager.register(LprPanelDef);
    panelManager.register(ReIDMatchesPanelDef);
    panelManager.register(EdgeDiagnosticsPanelDef);
    panelManager.register(FusionDashboardPanelDef);
    panelManager.register(OperatorActivityPanelDef);
    panelManager.register(SwarmCoordinationPanelDef);
    panelManager.register(TrainingDashboardPanelDef);
    panelManager.register(ConvoyPanelDef);
    panelManager.register(OperatorCursorsPanelDef);
    panelManager.register(WeatherOverlayPanelDef);
    panelManager.register(TrailExportPanelDef);
    panelManager.register(MapLayerSwitcherPanelDef);
    panelManager.register(CollaborationHubPanelDef);
    panelManager.register(IndoorPositioningPanelDef);
    panelManager.register(UnifiedAlertsPanelDef);
    panelManager.register(RadarScopePanelDef);
    panelManager.register(SdrWaterfallPanelDef);
    panelManager.register(AdsbTablePanelDef);
    panelManager.register(AddonsManagerPanelDef);
    panelManager.register(SitAwarePanelDef);
    panelManager.register(SystemHealthDashboardPanelDef);
    panelManager.register(ZoneManagerPanelDef);
    panelManager.register(AnalyticsPanelDef);
    panelManager.register(AmyBriefingPanelDef);
    panelManager.register(ThreatFeedsPanelDef);

    // Dynamically load addon panels from /api/addons/manifests
    loadAddons(panelManager).catch(err => {
        console.warn('[TRITIUM] Addon loading failed:', err);
    });

    // Start prediction confidence ellipses on the map
    const predictionEllipses = new PredictionEllipseManager();
    predictionEllipses.start();

    // Start ADS-B aircraft overlay (auto-polls /api/sdr/adsb)
    startAdsbOverlay();

    // Start convoy bounding box overlay on the map
    const convoyOverlay = new ConvoyOverlayManager();
    // Wait for map load event then attach
    EventBus.on('map:ready', (mapInstance) => {
        convoyOverlay.start(mapInstance);
    });
    // If map is already ready, try to start with window._tritiumMap
    if (window._tritiumMap) {
        convoyOverlay.start(window._tritiumMap);
    }

    // Addon GeoJSON map layers (polls addon endpoints, renders on map)
    EventBus.on('map:ready', (mapInstance) => {
        const addonLayers = new AddonMapLayers(mapInstance);
        addonLayers.loadFromAddons().catch(err => {
            console.warn('[TRITIUM] Addon map layer loading failed:', err);
        });
        window._addonMapLayers = addonLayers;
    });
    if (window._tritiumMap) {
        const addonLayers = new AddonMapLayers(window._tritiumMap);
        addonLayers.loadFromAddons().catch(err => {
            console.warn('[TRITIUM] Addon map layer loading failed:', err);
        });
        window._addonMapLayers = addonLayers;
    }

    // Enhanced map screenshot hotkey (Ctrl+Shift+P)
    initScreenshotHotkey();

    // panel:request-open — allows map click to open panels by id
    EventBus.on('panel:request-open', (data) => {
        if (data && data.id && panelManager) {
            panelManager.open(data.id);
        }
    });

    // Notification bell in header — click opens notifications panel
    const notifBellBtn = document.getElementById('notif-bell-btn');
    const notifBellCount = document.getElementById('notif-bell-count');
    let _notifUnreadCount = 0;

    function _updateBellBadge(count) {
        _notifUnreadCount = count;
        if (notifBellCount) {
            notifBellCount.textContent = String(count);
            notifBellCount.hidden = count <= 0;
        }
    }

    if (notifBellBtn) {
        notifBellBtn.addEventListener('click', () => {
            if (panelManager) panelManager.toggle('notifications');
        });
    }

    // Track unread notification count
    EventBus.on('notification:new', () => {
        _updateBellBadge(_notifUnreadCount + 1);
    });
    // When notifications panel marks all read
    EventBus.on('notifications:all-read', () => {
        _updateBellBadge(0);
    });
    // Fetch initial count
    fetch('/api/notifications?limit=100').then(r => r.ok ? r.json() : []).then(notifications => {
        const unread = (notifications || []).filter(n => !n.read).length;
        _updateBellBadge(unread);
    }).catch(() => {});

    // Try loading saved layout; if none, open minimal defaults.
    // Users open additional panels via VIEW menu (organized by category).
    if (!panelManager.loadLayout()) {
        panelManager.open('amy');
        panelManager.open('minimap');
    }

    // Setup wizard — available from HELP menu, not auto-opened.
    // Was blocking the map on first load with no obvious close mechanism.

    // Auto-start demo mode if configured
    if (ConfigStore.get('demo.autoStart', false)) {
        fetch('/api/demo/start', { method: 'POST' }).catch(() => {});
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
            toggleAssetCoverage: () => (_activeMapModule ? _activeMapModule.toggleAssetCoverage() : null),
            toggleEditMode: () => (_activeMapModule ? _activeMapModule.toggleEditMode() : null),
            isEditMode: () => (_activeMapModule ? _activeMapModule.isEditMode() : false),
            toggleUnits: () => (_activeMapModule ? _activeMapModule.toggleUnits() : toggleUnits()),
            toggleLabels: () => (_activeMapModule ? _activeMapModule.toggleLabels() : toggleLabels()),
            toggleModels: () => (_activeMapModule ? _activeMapModule.toggleModels() : toggleModels()),
            toggleWaterways: () => (_activeMapModule ? _activeMapModule.toggleWaterways() : toggleWaterways()),
            toggleParks: () => (_activeMapModule ? _activeMapModule.toggleParks() : toggleParks()),
            toggleTilt: () => (_activeMapModule ? _activeMapModule.toggleTilt() : toggleTilt()),
            toggleBuildings: () => (_activeMapModule ? _activeMapModule.toggleBuildings() : toggleBuildings()),
            toggleTrees: () => (_activeMapModule?.toggleTrees ? _activeMapModule.toggleTrees() : null),
            toggleWater: () => (_activeMapModule?.toggleWater ? _activeMapModule.toggleWater() : null),
            toggleBarriers: () => (_activeMapModule?.toggleBarriers ? _activeMapModule.toggleBarriers() : null),
            toggleEntrances: () => (_activeMapModule?.toggleEntrances ? _activeMapModule.toggleEntrances() : null),
            togglePOIs: () => (_activeMapModule?.togglePOIs ? _activeMapModule.togglePOIs() : null),
            toggleRoadGraph: () => (_activeMapModule?.toggleRoadGraph ? _activeMapModule.toggleRoadGraph() : null),
            toggleCitySim: () => toggleCitySim(),
            getCitySimStats: () => getCitySimStats(),
            toggleMesh: () => (_activeMapModule ? _activeMapModule.toggleMesh() : toggleMesh()),
            toggleMeshNodes: () => (_activeMapModule ? _activeMapModule.toggleMeshNodes() : toggleMeshNodes()),
            toggleMeshLinks: () => (_activeMapModule ? _activeMapModule.toggleMeshLinks() : toggleMeshLinks()),
            toggleMeshCoverage: () => (_activeMapModule ? _activeMapModule.toggleMeshCoverage() : toggleMeshCoverage()),
            toggleThoughts: () => (_activeMapModule ? _activeMapModule.toggleThoughts() : toggleThoughts()),
            toggleAllLayers: () => (_activeMapModule ? _activeMapModule.toggleAllLayers() : toggleAllLayers()),
            setAllLayers: (v) => (_activeMapModule ? _activeMapModule.setAllLayers(v) : setAllLayers(v)),
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
            toggleSquadHulls: () => (_activeMapModule ? _activeMapModule.toggleSquadHulls() : toggleSquadHulls()),
            toggleAutoFollow: () => (_activeMapModule ? _activeMapModule.toggleAutoFollow() : toggleAutoFollow()),
            toggleGeoLayers: () => (_activeMapModule ? _activeMapModule.toggleGeoLayers() : toggleGeoLayers()),
            togglePatrolRoutes: () => (_activeMapModule ? _activeMapModule.togglePatrolRoutes() : togglePatrolRoutes()),
            toggleWeaponRange: () => (_activeMapModule ? _activeMapModule.toggleWeaponRange() : toggleWeaponRange()),
            toggleHeatmap: () => (_activeMapModule ? _activeMapModule.toggleHeatmap() : toggleHeatmap()),
            toggleSwarmHull: () => (_activeMapModule ? _activeMapModule.toggleSwarmHull() : toggleSwarmHull()),
            toggleHazardZones: () => (_activeMapModule ? _activeMapModule.toggleHazardZones() : toggleHazardZones()),
            toggleGeofenceZones: () => (_activeMapModule ? _activeMapModule.toggleGeofenceZones() : toggleGeofenceZones()),
            toggleHostileObjectives: () => (_activeMapModule ? _activeMapModule.toggleHostileObjectives() : toggleHostileObjectives()),
            toggleCrowdDensity: () => (_activeMapModule ? _activeMapModule.toggleCrowdDensity() : toggleCrowdDensity()),
            toggleCoverPoints: () => (_activeMapModule ? _activeMapModule.toggleCoverPoints() : toggleCoverPoints()),
            toggleUnitSignals: () => (_activeMapModule ? _activeMapModule.toggleUnitSignals() : toggleUnitSignals()),
            toggleHostileIntel: () => (_activeMapModule ? _activeMapModule.toggleHostileIntel() : toggleHostileIntel()),
            togglePredictionCones: () => (_activeMapModule ? _activeMapModule.togglePredictionCones() : togglePredictionCones()),
            toggleCoverageOverlap: () => (_activeMapModule ? _activeMapModule.toggleCoverageOverlap() : toggleCoverageOverlap()),
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

        // Tactical situation banner (persistent bar below menu)
        createTacticalBanner(barContainer);

        // Command palette (Ctrl+K or /)
        initCommandPalette(panelManager, mapActions);
        window.openCommandPalette = openCommandPalette;

        // Bridge map actions to Layers panel
        EventBus.on('layers:request-map-actions', () => {
            EventBus.emit('layers:set-map-actions', mapActions);
        });
        EventBus.emit('layers:set-map-actions', mapActions);
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

const TOAST_MAX = 2;
const TOAST_DURATION = 3500;
const TOAST_DEDUP_MS = 5000;  // Suppress duplicate messages within 5 seconds
const _recentToasts = new Map();  // message -> timestamp

function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    // Debounce: suppress duplicate messages within TOAST_DEDUP_MS
    const dedupKey = `${type}:${message}`;
    const now = Date.now();
    const lastShown = _recentToasts.get(dedupKey);
    if (lastShown && (now - lastShown) < TOAST_DEDUP_MS) return;
    _recentToasts.set(dedupKey, now);
    // Prune old entries to prevent memory leak
    if (_recentToasts.size > 100) {
        for (const [k, t] of _recentToasts) {
            if (now - t > TOAST_DEDUP_MS * 2) _recentToasts.delete(k);
        }
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <div class="toast-header">
            <span class="toast-label mono">${_esc(type.toUpperCase())}</span>
            <span class="toast-time mono">${new Date().toLocaleTimeString().substr(0, 5)}</span>
            <button class="toast-close" aria-label="Dismiss">&times;</button>
        </div>
        <div class="toast-body">${_esc(message)}</div>
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
    const wavesEl = document.getElementById('go-waves');
    const elimsEl = document.getElementById('go-eliminations');

    // Use store values first, then backfill from API if empty
    if (scoreEl) scoreEl.textContent = TritiumStore.game.score || 0;
    const totalW = TritiumStore.game.totalWaves || 10;
    const displayWave = Math.min(TritiumStore.game.wave || 0, totalW);
    if (wavesEl) wavesEl.textContent = `${displayWave}/${totalW}`;
    if (elimsEl) elimsEl.textContent = TritiumStore.game.eliminations || 0;

    // Backfill from API if store values are empty (e.g., late-joining session)
    if (!TritiumStore.game.score) {
        fetch('/api/game/state').then(r => r.json()).then(gs => {
            if (scoreEl && gs.score) scoreEl.textContent = gs.score;
            if (wavesEl && gs.wave) wavesEl.textContent = `${gs.wave}/${gs.total_waves || 10}`;
            if (elimsEl && gs.total_eliminations) elimsEl.textContent = gs.total_eliminations;
        }).catch(() => {});
    }

    // Clear previous stats sections
    const mvpSection = document.getElementById('go-mvp-section');
    const combatSection = document.getElementById('go-combat-section');
    const unitsSection = document.getElementById('go-units-section');
    if (mvpSection) mvpSection.innerHTML = '';
    if (combatSection) combatSection.innerHTML = '';
    if (unitsSection) unitsSection.innerHTML = '';

    overlay.hidden = false;

    // Fetch after-action stats from backend (parallel requests)
    _fetchGameOverStats(mvpSection, combatSection, unitsSection);

    overlay.querySelector('[data-action="play-again"]')?.addEventListener('click', () => {
        overlay.hidden = true;
        try { resetGame(); } catch (_) {}
        setTimeout(() => { try { beginWar(); } catch (_) {} }, 500);
    }, { once: true });

    overlay.querySelector('[data-action="exit-game"]')?.addEventListener('click', () => {
        overlay.hidden = true;
        try { resetGame(); } catch (_) {}
    }, { once: true });
}

/**
 * Fetch after-action stats and populate game-over overlay sections.
 * Uses game-over-stats.js helper functions to build HTML.
 * Gracefully handles API failures by leaving sections empty.
 */
async function _fetchGameOverStats(mvpSection, combatSection, unitsSection) {
    try {
        // Parallel fetch: summary (includes MVP) and full unit stats
        const [summaryResp, statsResp] = await Promise.all([
            fetch('/api/game/stats/summary').catch(() => null),
            fetch('/api/game/stats').catch(() => null),
        ]);

        // Process summary response (includes MVP data)
        if (summaryResp && summaryResp.ok) {
            const summary = await summaryResp.json();

            // MVP spotlight
            if (mvpSection && summary.mvp && typeof goBuildMvpSpotlightHtml === 'function') {
                mvpSection.innerHTML = goBuildMvpSpotlightHtml(summary.mvp);
            }

            // Combat stats grid
            if (combatSection && typeof goBuildCombatStatsHtml === 'function') {
                combatSection.innerHTML = goBuildCombatStatsHtml(summary);
            }
        }

        // Process full stats response (per-unit table)
        if (statsResp && statsResp.ok) {
            const stats = await statsResp.json();
            if (unitsSection && stats.units && typeof goBuildUnitTableHtml === 'function') {
                unitsSection.innerHTML = goBuildUnitTableHtml(stats.units);
            }
        }
    } catch (e) {
        console.warn('[TRITIUM] Failed to fetch after-action stats:', e);
        // Graceful degradation: overlay still shows basic score/wave/elims
    }
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

// In-memory chat history for the session
const _chatHistory = [];
// Track whether Amy is currently thinking (typing indicator)
let _amyThinking = false;

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

    // Amy's response arrives asynchronously via WebSocket transcript events.
    // When Amy speaks (speaker === 'amy'), show it in the chat and clear the
    // typing indicator.
    EventBus.on('chat:amy_response', (data) => {
        _hideTypingIndicator();
        appendChatMessage('AMY', data.text || '...', 'amy');
    });

    // Optionally show Amy's autonomous thoughts as dimmed system messages in
    // the chat so the operator sees she is alive even when not talking.
    EventBus.on('amy:thought', (data) => {
        const overlay = document.getElementById('chat-overlay');
        // Only show thoughts when the chat is open
        if (overlay && !overlay.hidden) {
            appendChatMessage('AMY', data.text || '', 'system');
        }
    });

    // Wire context hint: show Amy's last thought above the chat input
    TritiumStore.on('amy.lastThought', (thought) => {
        const ctx = document.getElementById('chat-context-text');
        if (ctx) ctx.textContent = thought || '--';
    });

    // Show Amy's mood in the context area when it changes
    TritiumStore.on('amy.mood', (mood) => {
        const label = document.querySelector('.chat-context-label');
        if (label) {
            const moodStr = mood ? ` // ${mood.toUpperCase()}` : '';
            label.textContent = `LATEST THOUGHT${moodStr}`;
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
    _showTypingIndicator();

    try {
        const resp = await fetch('/api/amy/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: text }),
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(() => ({}));
            _hideTypingIndicator();
            appendChatMessage('SYSTEM', errData.error || `Error ${resp.status}`, 'error');
        }
        // Amy's actual response will arrive via WebSocket (amy_transcript event).
        // The typing indicator stays visible until that event arrives.
        // Safety timeout: clear typing indicator after 30s if no response.
        setTimeout(() => _hideTypingIndicator(), 30000);
    } catch (e) {
        _hideTypingIndicator();
        appendChatMessage('SYSTEM', 'Failed to reach Amy', 'error');
    }
}

function _showTypingIndicator() {
    if (_amyThinking) return;
    _amyThinking = true;
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    // Remove any existing indicator first
    messages.querySelector('.chat-typing-indicator')?.remove();
    const indicator = document.createElement('div');
    indicator.className = 'chat-typing-indicator';
    indicator.innerHTML = '<span class="chat-typing-label mono">AMY</span><span class="chat-typing-dots"><span></span><span></span><span></span></span>';
    messages.appendChild(indicator);
    messages.scrollTop = messages.scrollHeight;
}

function _hideTypingIndicator() {
    _amyThinking = false;
    const messages = document.getElementById('chat-messages');
    if (!messages) return;
    messages.querySelector('.chat-typing-indicator')?.remove();
}

/**
 * Format a timestamp for display in chat bubbles.
 * @param {Date} date
 * @returns {string} e.g. "14:32"
 */
function _formatChatTime(date) {
    const h = String(date.getHours()).padStart(2, '0');
    const m = String(date.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
}

/**
 * Append a message bubble to the chat messages container.
 * @param {string} sender - display name (YOU, AMY, SYSTEM)
 * @param {string} text - message text
 * @param {string} type - 'user' | 'amy' | 'system' | 'error'
 */
function appendChatMessage(sender, text, type) {
    const messages = document.getElementById('chat-messages');
    if (!messages) return;

    const now = new Date();
    const timeStr = _formatChatTime(now);

    // Store in session history
    _chatHistory.push({ role: type, text, time: now.toISOString() });

    const msg = document.createElement('div');
    msg.className = `chat-msg chat-msg-${type}`;
    msg.innerHTML =
        `<div class="chat-msg-header"><span class="chat-msg-sender mono">${_esc(sender)}</span><span class="chat-msg-time mono">${timeStr}</span></div>` +
        `<div class="chat-msg-text">${_esc(text)}</div>`;
    messages.appendChild(msg);
    messages.scrollTop = messages.scrollHeight;
}

/**
 * Get the in-memory chat history for the current session.
 * @returns {Array<{role: string, text: string, time: string}>}
 */
function getChatHistory() {
    return _chatHistory.slice();
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
        return `<li class="unit-list-item" data-unit-id="${_esc(u.id)}" role="option">
            <span class="unit-icon-mini" style="color:${allianceColor}">${icon}</span>
            <span class="unit-item-name">${_esc(u.name || u.id)}</span>
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
            <span class="alert-text">${_esc(a.message)}</span>
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
        // Also dismiss the war-hud canvas overlay if visible
        const warOverlay = document.getElementById('war-game-over');
        if (warOverlay) warOverlay.style.display = 'none';
        // Clear all game-related state so stale data does not leak into the next game
        TritiumStore.resetGameState();
        // Clear projectiles, particles, and screen effects from previous game
        if (typeof window.warCombatReset === 'function') window.warCombatReset();
    } catch (e) {
        showToast('Failed to reset game', 'alert');
    }
}

async function dispatchUnit(targetId, x, y) {
    try {
        await fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'dispatch', params: [targetId, x, y] }),
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

            // Auto-open Game HUD in setup mode (contains PLACE UNIT toolbar)
            if (mode === 'setup' && panelManager && !panelManager.isOpen('game')) {
                panelManager.open('game');
            }
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

        // WASD operator control — when controlling a unit, intercept movement keys
        const controlledId = TritiumStore.get('controlledUnitId');
        if (controlledId && !e.ctrlKey && !e.altKey) {
            const moveMap = {
                'w': 'move_forward', 'W': 'move_forward',
                's': 'move_backward', 'S': 'move_backward',
                'a': 'move_left',    'A': 'move_left',
                'd': 'move_right',   'D': 'move_right',
            };
            const action = moveMap[e.key];
            if (action) {
                e.preventDefault();
                fetch(`/api/npc/${encodeURIComponent(controlledId)}/action`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action }),
                }).catch(() => {});
                return;
            }
            // Escape releases control
            if (e.key === 'Escape') {
                fetch(`/api/npc/${encodeURIComponent(controlledId)}/control`, {
                    method: 'DELETE',
                }).then(() => {
                    TritiumStore.set('controlledUnitId', null);
                    EventBus.emit('unit:control-released', { id: controlledId });
                    EventBus.emit('toast:show', { message: 'Unit control released', type: 'info' });
                }).catch(() => {
                    // Release locally even on network error to avoid stuck WASD state
                    TritiumStore.set('controlledUnitId', null);
                    EventBus.emit('unit:control-released', { id: controlledId });
                    EventBus.emit('toast:show', { message: 'Control released (server unreachable)', type: 'warning' });
                });
                return;
            }
        }

        // Ctrl+Shift+S: save layout
        if (e.ctrlKey && e.shiftKey && (e.key === 'S' || e.key === 's')) {
            e.preventDefault();
            if (menuBarEl) focusSaveInput(menuBarEl);
            return;
        }

        // Ctrl+G: toggle military grid overlay
        if (e.ctrlKey && !e.shiftKey && (e.key === 'G' || e.key === 'g')) {
            e.preventDefault();
            toggleGridOverlay();
            return;
        }

        // Ctrl+Shift+M: toggle macro recording
        if (e.ctrlKey && e.shiftKey && (e.key === 'M' || e.key === 'm')) {
            e.preventDefault();
            if (panelManager) panelManager.toggle('keyboard-macros');
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

        // Drawing mode keys (geofence polygon / patrol waypoints)
        if (e.key === 'Enter') {
            EventBus.emit('map:drawFinish', {});
        }
        if (e.key === 'Escape') {
            EventBus.emit('map:drawCancel', {});
        }

        // Shift+E: Toggle edit mode (asset placement/editing)
        if (e.key === 'E' && e.shiftKey) {
            e.preventDefault();
            _mapActions?.toggleEditMode?.();
            return;
        }

        switch (e.key) {
            case '?': {
                const helpEl = document.getElementById('help-overlay');
                if (helpEl) helpEl.hidden = !helpEl.hidden;
                break;
            }
            case 'c':
            case 'C':
                toggleChat();
                break;
            case 'Escape': {
                toggleChat(false);
                const helpOverlay = document.getElementById('help-overlay');
                const modalOverlay = document.getElementById('modal-overlay');
                const gameOverOverlay = document.getElementById('game-over-overlay');
                if (helpOverlay) helpOverlay.hidden = true;
                if (modalOverlay) modalOverlay.hidden = true;
                if (gameOverOverlay) gameOverOverlay.hidden = true;
                MissionModal.hide();
                if (TritiumStore.get('map.mode') === 'setup') {
                    document.querySelector('[data-map-mode="observe"]')?.click();
                }
                break;
            }
            case '/':
                e.preventDefault();
                toggleChat(true);
                break;
            case 'm':
            case 'M':
                if (panelManager) panelManager.toggle('minimap');
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
                if (panelManager) panelManager.toggle('unified-alerts');
                break;
            case '4':
                if (panelManager) panelManager.toggle('game');
                break;
            case '5':
                if (panelManager) panelManager.toggle('meshtastic');
                break;
            case '6':
                if (panelManager) panelManager.toggle('cameras');
                break;
            case '7':
                if (panelManager) panelManager.toggle('search');
                break;
            case '8':
                if (panelManager) panelManager.toggle('tak');
                break;
            case '9':
                if (panelManager) panelManager.toggle('videos');
                break;
            case '0':
                if (panelManager) panelManager.toggle('zone-manager');
                break;
            case 'a':
            case 'A':
                _mapActions ? _mapActions.toggleAutoFollow() : toggleAutoFollow();
                break;
            case 'f':
            case 'F':
                _mapActions ? _mapActions.centerOnAction() : centerOnAction();
                break;
            case 'r':
            case 'R':
                if (panelManager) panelManager.toggle('replay');
                break;
            case 'e':
            case 'E':
                if (panelManager) panelManager.toggle('sensors');
                break;
            case 'p':
            case 'P':
                if (panelManager) panelManager.toggle('battle-stats');
                break;
            case 'd':
            case 'D':
                // Toggle demo mode (start if idle, stop if running)
                fetch('/api/demo/status').then(r => r.ok ? r.json() : {}).then(status => {
                    const endpoint = status.active ? '/api/demo/stop' : '/api/demo/start';
                    fetch(endpoint, { method: 'POST' }).then(r => r.json()).then(d => {
                        EventBus.emit('toast:show', {
                            message: status.active ? 'Demo mode stopped' : 'Demo mode started',
                            type: 'info',
                        });
                    }).catch(() => {});
                }).catch(() => {});
                break;
            case 'j':
            case 'J':
                _mapActions ? _mapActions.toggleCitySim() : toggleCitySim();
                break;
            case '[':
                _mapActions ? _mapActions.cycleSimTimeScale() : cycleSimTimeScale();
                break;
            case ']':
                _mapActions ? _mapActions.spawnEmergencyVehicle() : spawnEmergencyVehicle();
                break;
            case '\\':
                // Start a protest at city center (backslash key)
                EventBus.emit('city-sim:start-protest', {
                    plazaCenter: { x: 0, z: 0 },
                    participantCount: 50,
                    legitimacy: 0.3,
                });
                break;
            case 'u':
            case 'U':
                _mapActions ? _mapActions.toggleUnits() : toggleUnits();
                break;
            case 'v':
            case 'V':
                _mapActions ? _mapActions.toggleFog() : toggleFog();
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
            case 'l':
            case 'L':
                if (panelManager) panelManager.toggle('layers');
                break;
            case 'x':
            case 'X': {
                // Toggle notification sound mute
                const muted = !TritiumStore.get('notifications.muted');
                TritiumStore.set('notifications.muted', muted);
                EventBus.emit('toast:show', {
                    message: muted ? 'Notification sounds MUTED' : 'Notification sounds UNMUTED',
                    type: 'info',
                });
                break;
            }
            case 'Tab':
                if (panelManager) {
                    e.preventDefault();
                    const openPanels = panelManager.getRegisteredPanels().filter(p => p.isOpen);
                    if (openPanels.length > 0) {
                        const currentFocus = panelManager._focusedPanelId || null;
                        let idx = openPanels.findIndex(p => p.id === currentFocus);
                        idx = (idx + 1) % openPanels.length;
                        const nextId = openPanels[idx].id;
                        // Remove focus indicator from all panels
                        if (panelManager._panels) {
                            for (const [, panel] of panelManager._panels) {
                                if (panel.el) panel.el.classList.remove('panel-focused');
                            }
                        }
                        // Add focus indicator to next panel
                        const nextPanel = panelManager._panels?.get(nextId);
                        if (nextPanel && nextPanel.el) {
                            nextPanel.el.classList.add('panel-focused');
                        }
                        panelManager._focusedPanelId = nextId;
                        EventBus.emit('panel:focused', { id: nextId });
                    }
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

// Export for use by other modules
const escapeHtml = _esc;
export { showToast, showBanner, selectUnit, dispatchUnit, escapeHtml, ws, panelManager, layoutManager, appendChatMessage, getChatHistory, toggleChat };

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', init);
