// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- MapLibre GL JS Base Map + Three.js Tactical Overlay
 *
 * Replaces the hand-rolled tile renderer (map3d.js) with MapLibre GL JS
 * for proper Web Mercator projection, satellite imagery alignment, and
 * 3D building extrusion from OpenStreetMap vector tiles.
 *
 * Architecture:
 *   MapLibre GL JS = base map (tiles, buildings, roads, labels, GIS layers)
 *   Three.js = custom layer (units, projectiles, effects, fog of war)
 *
 * All coordinates pass through MapLibre's projection math, ensuring
 * perfect alignment between satellite imagery, building footprints,
 * and tactical overlays.
 *
 * Exports the same API surface as map3d.js for drop-in replacement.
 */

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';
import { drawMinimapContent } from './panels/minimap.js';
import { DeviceModalManager } from './device-modal.js';
import { FrontendVisionSystem } from './vision-system.js';
import { ContextMenu } from './context-menu.js';
import { _esc } from './panel-utils.js';

// ============================================================
// Constants
// ============================================================

const ZOOM_DEFAULT = 16;    // MapLibre zoom (16 = neighborhood)
const ZOOM_MIN = 10;        // Wide area
const ZOOM_MAX = 21;        // Max close-up
const PITCH_DEFAULT = 50;   // Degrees from vertical (0 = top-down, 60 = tilted)
const PITCH_TOPDOWN = 0;
const DISPATCH_ARROW_LIFETIME = 3000;

// Combat effect timing/sizing (meters unless noted)
// Sized for visibility at zoom 16 (neighborhood): 1 pixel ≈ 2.4m.
// A house is ~12-15m (5-6 pixels). Effects need to be many-house-sized
// to read as dramatic combat effects on the tactical map.
const FX = {
    TRACER_DURATION: 600,    // ms — projectile flight time
    TRACER_HEAD_R: 15,       // radius of glowing head (~1 house)
    TRACER_GLOW_R: 35,       // radius of outer glow (~3 houses)
    FLASH_DURATION: 400,     // ms — muzzle flash
    FLASH_R: 25,             // radius of flash sphere (~2 houses)
    HIT_DURATION: 600,       // ms — impact sparks
    HIT_R: 15,               // radius of impact sphere (~1 house)
    ELIM_DURATION: 1800,     // ms — elimination explosion
    ELIM_R_START: 20,        // starting ring radius
    ELIM_R_END: 120,         // final ring radius (~8 houses, dramatic)
    PARTICLE_COUNT: 30,      // particles per burst
    PARTICLE_DURATION: 1200, // ms — individual particles
    PARTICLE_SPEED: 60,      // meters/second spread speed
    PARTICLE_R: 5,           // particle sphere radius
    ALT: 2,                  // meters above ground (2m clears tiles + slight lift)
};

// 3D unit model sizing
// Geometry values below are in meters. SCALE converts them to final size.
// At SCALE=0.35, a turret (geometry r=8m diam=16m) becomes ~5.6m — about a car width.
// A suburban house is ~12-15m wide for comparison.
const UNIT_3D = {
    SCALE: 0.35,             // model multiplier: 0.35 makes units car-to-van sized
    ALT: 1,                  // ground units 1m above surface (prevents z-fighting with tiles at pitch=0)
    DRONE_ALT: 5,            // drones hover slightly above ground
    RING_PULSE: 2,           // ground ring pulse Hz
    ROTOR_SPEED: 15,         // drone rotor spin rad/s
    BEAM_PULSE: 1.5,         // light beam pulse Hz
};

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
};

// ============================================================
// Module state
// ============================================================

const _state = {
    map: null,                  // MapLibre Map instance
    container: null,            // DOM container
    threeRenderer: null,        // Three.js WebGLRenderer (shared context)
    threeScene: null,           // Three.js Scene
    threeCamera: null,          // Three.js Camera
    threeRoot: null,            // Three.js Group (ref-transformed root for tactical objects)
    threeEffectsRoot: null,     // Three.js Group (always visible — combat effects)
    geoCenter: null,            // { lat, lng } reference point
    initialized: false,
    layerHud: null,

    // Layer visibility — map base
    showSatellite: false,
    showBuildings: true,
    showRoads: false,
    showWaterways: true,       // waterway layers
    showParks: true,           // parks / green areas
    showTerrain: false,        // 3D terrain mesh (DEM)
    terrainExaggeration: 1.5,  // vertical exaggeration factor
    showGeoLayers: true,       // GIS data overlays

    // Layer visibility — tactical
    showGrid: false,
    showUnits: true,           // DOM unit markers (colored dots)
    allianceFilter: null,      // null = show all, or ['hostile','friendly','neutral']
    showLabels: true,          // DOM unit name labels
    showModels3d: false,       // 3D models — off by default (causes visual clutter with circles)
    showFog: false,            // fog of war
    showMesh: true,            // mesh radio overlay (master toggle)
    showMeshNodes: true,       // mesh node icons
    showMeshLinks: true,       // mesh link lines
    showMeshCoverage: false,   // mesh LoRa coverage circles
    showPredictionCones: false, // target prediction uncertainty cones
    showCoverageOverlap: false, // sensor coverage overlap analysis
    showPatrolRoutes: true,    // patrol route lines for friendly units

    // Layer visibility — combat FX (debug toggles)
    showTracers: true,         // Three.js projectile flight
    showExplosions: true,      // Three.js + DOM elimination effects
    showParticles: true,       // Three.js debris/sparks
    showHitFlashes: true,      // Three.js + DOM impact flashes
    showFloatingText: true,    // DOM damage numbers, ELIMINATED text

    // Layer visibility — unit decorations
    showHealthBars: true,      // DOM health bars + damage glow on units
    showSelectionFx: true,     // selection highlight glow + hostile pulse animation

    // Layer visibility — overlays
    showKillFeed: true,        // top-right combat log
    showScreenFx: true,        // screen shake + flash overlay
    showBanners: true,         // wave/game state announcements
    showLayerHud: false,       // top-center status bar (hidden by default — overlaps tactical banner)
    showThoughts: true,        // NPC thought bubbles above markers
    showWeaponRange: false,    // weapon range circle — off by default (visual clutter)
    showHeatmap: false,        // combat zone heatmap (off by default)
    showSwarmHull: false,      // swarm hull — off by default
    showSquadHulls: false,     // squad hulls — off by default (visual clutter)
    showHazardZones: false,    // hazard zones — off by default
    showGeofenceZones: true,   // geofence monitoring zones — on by default (Loop 5)
    showHostileObjectives: false, // hostile objectives — off by default
    showCrowdDensity: true,    // crowd density heatmap (civil_unrest mode only)
    showCoverPoints: false,    // tactical cover positions (off by default — too noisy during battle)
    showUnitSignals: false,    // unit signals — off by default
    showHostileIntel: false,   // hostile intel — off by default (visual clutter)

    // Cinematic auto-follow camera
    autoFollow: false,         // auto-follow camera mode
    autoFollowTimer: null,     // setInterval handle for periodic flyTo
    autoFollowFlyingNow: false,// true while an auto-triggered flyTo is in progress
    combatEventRing: [],       // last 20 combat event positions { lng, lat, time }
    streakHolder: null,        // { unitId, lng, lat, time } current streak holder

    tiltMode: 'tilted',        // 'tilted' or 'top-down'
    currentMode: 'observe',    // 'observe', 'tactical', or 'setup'

    // Unit tracking
    unitMarkers: {},            // id -> maplibregl.Marker
    unitMeshes: {},             // id -> THREE.Group (for Three.js layer)

    // GIS data layers
    geoLayerIds: [],            // IDs of added MapLibre layers

    // Selection
    selectedUnitId: null,

    // Thought bubble management — cap visible non-critical bubbles
    _visibleThoughtIds: new Set(),  // unit IDs with visible thought bubbles
    _maxThoughtBubbles: 5,          // max non-critical visible at once

    // Dispatch
    dispatchArrows: [],
    dispatchMode: false,    // true when waiting for map click to set destination
    dispatchUnitId: null,   // unit ID to dispatch on next click
    patrolMode: false,      // true when placing patrol waypoints
    patrolUnitId: null,     // unit ID for patrol mode
    patrolWaypoints: [],    // accumulated patrol waypoints
    patrolDrawMode: false,       // true when drawing a patrol route (multi-waypoint)
    patrolDrawUnitId: null,      // unit ID being assigned the drawn route
    patrolDrawWaypoints: [],     // [{x, y}, ...] game coords accumulated during drawing
    patrolDrawMarkers: [],       // MapLibre Marker instances for numbered waypoints
    patrolDrawHudEl: null,       // DOM element for drawing status HUD
    patrolDrawMouseLngLat: null, // current mouse position for rubber-band line
    geofenceDrawMode: false,     // true when drawing a geofence polygon
    geofenceDrawVertices: [],    // [[x,y], ...] game coords accumulated during drawing
    geofenceDrawMarkers: [],     // MapLibre Marker instances for vertices
    geofenceDrawMouseLngLat: null, // current mouse position for rubber-band line
    aimMode: false,         // true when setting aim direction
    aimUnitId: null,        // unit ID for aim mode

    // Unit update loop (adaptive interval)
    _unitUpdateTimer: null, // setInterval handle for _scheduleUnitUpdate()

    // Combat effects (Three.js)
    effects: [],            // active effect objects
    effectsActive: false,   // repaint loop running
    effectAnimId: null,     // rAF handle

    // Recently-fired tracker: unitId -> { time, targetId } (for combat ring + engagement lines)
    recentlyFired: {},      // { unitId: { time, targetId } }
    battleStartTime: 0,     // performance.now() when battle starts

    // Wave direction/countdown
    _waveDirection: null,          // current wave spawn_direction string
    _nextWaveDirection: null,      // next wave spawn_direction (from wave_complete)
    _nextWaveCountdown: 0,         // seconds until next wave
    _nextWaveCountdownStart: 0,    // performance.now() when countdown started
    _nextWaveName: null,           // name of next wave
    _nextHostileCount: 0,          // hostile count for next wave

    // Vision system (fog of war + cones)
    visionSystem: null,

    // FPS tracking
    _frameTimes: [],
    _lastFpsUpdate: 0,
    _currentFps: 0,
    _fpsLoopRunning: false,

    // --- Performance: GeoJSON change-detection caches ---
    _lastPatrolHash: null,
    _lastDispatchHash: null,
    _lastWeaponRangeHash: null,
    _lastEngagementHash: null,
    _lastSwarmHullHash: null,
    _lastSquadHullHash: null,
    _lastHazardHash: null,
    _lastHostileObjHash: null,
    _lastCrowdDensityHash: null,
    _lastCoverPointsHash: null,
    _lastSignalsHash: null,
    // Hostile objective polling (5s interval during active game)
    _hostileObjPollTimer: null,
    // Hostile intel DOM element (bottom-left HUD)
    _hostileIntelEl: null,
    // Throttle counters for overlays that rarely change (updated at 1Hz)
    _overlayTickCounter: 0,
};

// ============================================================
// Layer state persistence (localStorage)
// ============================================================

const _LAYER_STORAGE_KEY = 'tritium-map-layers';
const _PERSISTED_LAYERS = [
    'showFog', 'showGrid', 'showBuildings', 'showLabels', 'showUnits',
    'showPatrolRoutes', 'showHealthBars', 'showBanners', 'showKillFeed',
    'showHeatmap', 'showThoughts', 'showWeaponRange',
];

/** Load persisted layer prefs into _state. */
function _loadLayerPrefs() {
    try {
        const raw = localStorage.getItem(_LAYER_STORAGE_KEY);
        if (!raw) return;
        const saved = JSON.parse(raw);
        for (const key of _PERSISTED_LAYERS) {
            if (key in saved) _state[key] = !!saved[key];
        }
    } catch (_) { /* ignore corrupt data */ }
}

/** Save current layer toggles to localStorage. */
function _saveLayerPrefs() {
    try {
        const obj = {};
        for (const key of _PERSISTED_LAYERS) obj[key] = _state[key];
        localStorage.setItem(_LAYER_STORAGE_KEY, JSON.stringify(obj));
    } catch (_) { /* quota exceeded, ignore */ }
}

_loadLayerPrefs();

// Pre-allocated Matrix4 reused every frame to avoid GC pressure.
// The render() callback runs at 60Hz — allocating a new Matrix4 each
// frame generates ~60 short-lived objects/sec that the GC must collect.
const _tempMatrix = new THREE.Matrix4();

// Expose for automated testing (layer isolation, coordinate checks)
window._mapState = _state;

// ============================================================
// Initialization
// ============================================================

export function initMap() {
    // Check MapLibre is loaded
    if (typeof maplibregl === 'undefined') {
        console.error('[MAP-ML] MapLibre GL JS not loaded');
        return;
    }

    const container = document.getElementById('tactical-area');
    if (!container) return;
    _state.container = container;

    // Hide legacy canvas if present
    const legacyCanvas = document.getElementById('tactical-canvas');
    if (legacyCanvas) legacyCanvas.style.display = 'none';
    const legacyThreeCanvas = document.getElementById('tactical-3d-canvas');
    if (legacyThreeCanvas) legacyThreeCanvas.style.display = 'none';

    // Create map div inside container
    let mapDiv = document.getElementById('maplibre-map');
    if (!mapDiv) {
        mapDiv = document.createElement('div');
        mapDiv.id = 'maplibre-map';
        mapDiv.style.cssText = 'position:absolute; inset:0; width:100%; height:100%;';
        container.appendChild(mapDiv);
    }

    // Fetch geo reference then create map
    _fetchGeoReference().then(() => {
        _createMap(mapDiv);
    });
}

async function _fetchGeoReference() {
    try {
        const resp = await fetch('/api/geo/reference');
        if (resp.ok) {
            const data = await resp.json();
            if (data.initialized) {
                _state.geoCenter = { lat: data.lat, lng: data.lng };
                console.log(`[MAP-ML] Geo reference: ${data.lat.toFixed(6)}, ${data.lng.toFixed(6)}`);
                return;
            }
        }
    } catch (e) {
        console.warn('[MAP-ML] Geo reference fetch failed:', e.message);
    }
    // Default: Dublin, CA
    _state.geoCenter = { lat: 37.7159, lng: -121.8960 };
}

function _createMap(mapDiv) {
    const center = [_state.geoCenter.lng, _state.geoCenter.lat];

    // MapLibre style: dark basemap with satellite raster + vector buildings
    const style = _buildStyle();

    _state.map = new maplibregl.Map({
        container: mapDiv,
        style: style,
        center: center,
        zoom: ZOOM_DEFAULT,
        pitch: PITCH_DEFAULT,
        bearing: 0,
        maxZoom: ZOOM_MAX,
        minZoom: ZOOM_MIN,
        antialias: true,
        attributionControl: false,
    });

    // Add minimal attribution
    _state.map.addControl(
        new maplibregl.AttributionControl({ compact: true }),
        'bottom-right'
    );

    // Add navigation control
    _state.map.addControl(
        new maplibregl.NavigationControl({ showCompass: true, showZoom: false }),
        'top-right'
    );

    // Add scale bar control — shows map scale at current zoom
    _state.map.addControl(
        new maplibregl.ScaleControl({
            maxWidth: 150,
            unit: 'metric',
        }),
        'bottom-left'
    );

    // Add custom compass rose overlay (more visible than NavigationControl compass)
    _addCompassRose();

    // Start standalone FPS loop — uses rAF so it runs every browser frame
    // regardless of MapLibre repaint state (idle map = no 'render' events).
    _startFpsLoop();

    _state.map.on('error', (e) => {
        console.error('[MAP-ML] Map error:', e.error?.message || e.message || e);
    });

    console.log('[MAP-ML] Map created, waiting for load event...');

    // If the map is already loaded (cached tiles), the 'load' event won't fire again.
    // Check immediately and also register the callback.
    const _onMapLoaded = () => {
        if (_state.initialized) return; // prevent double-init
        console.log('[MAP-ML] Map loaded');
        _state.initialized = true;

        // Add Three.js custom layer for tactical overlays
        _addThreeJsLayer();

        // Add GIS data layers
        _loadGeoLayers();

        // Add tactical grid overlay
        _addGridOverlay();

        // Add layer HUD
        _createLayerHud();

        // Add compact map legend
        _createMapLegend();

        // Add patrol route drawing button
        _createPatrolDrawButton();

        // Combat effects system
        _initEffects();

        // Subscribe to store events
        TritiumStore.on('map.selectedUnitId', _onSelectionChanged);
        EventBus.on('units:updated', _onUnitsUpdated);
        EventBus.on('unit:dispatched', _onDispatched);
        EventBus.on('unit:dispatch', _onUnitDispatch);
        EventBus.on('unit:dispatch-mode', _onDispatchModeEnter);
        EventBus.on('minimap:pan', _onMinimapPan);
        EventBus.on('map:flyToMission', _onPanToMission);
        EventBus.on('map:centerOnUnit', _onCenterOnUnit);
        EventBus.on('map:marker', _onDropMarker);
        EventBus.on('map:waypoint', _onDropWaypoint);
        EventBus.on('unit:patrol-mode', _onPatrolModeEnter);
        EventBus.on('unit:aim-mode', _onAimModeEnter);
        EventBus.on('patrol:drawRoute', _onPatrolDrawRouteStart);
        EventBus.on('geofence:drawZone', _onGeofenceDrawStart);
        // Re-fetch geofence zones when enter/exit events fire or zones change
        // Also flash the zone border in magenta briefly on enter
        EventBus.on('geofence:enter', (data) => {
            _state._lastGeofenceFetch = 0;
            _updateGeofenceZones();
            _flashGeofenceAlert(data);
        });
        EventBus.on('geofence:exit', () => { _state._lastGeofenceFetch = 0; _updateGeofenceZones(); });
        EventBus.on('zone:selected', (data) => {
            if (data && data.polygon) { _state._lastGeofenceFetch = 0; _updateGeofenceZones(); }
        });
        EventBus.on('map:drawFinish', _onDrawFinishML);
        EventBus.on('map:drawCancel', _onDrawCancelML);
        EventBus.on('tak:center-on-client', (data) => {
            if (data && (data.lat !== undefined || data.x !== undefined)) {
                _onCenterOnUnit(data);
            }
        });
        EventBus.on('device:open-modal', (data) => {
            if (!data || !data.id) return;
            const u = TritiumStore.units.get(data.id);
            if (u) DeviceModalManager.open(data.id, _resolveModalType(u), u);
        });

        // Listen for map mode changes
        EventBus.on('map:mode', (data) => {
            if (data && data.mode) {
                setMapMode(data.mode);
            }
        });

        // Camera markers from camera-feeds plugin
        EventBus.on('cameras:changed', _onCamerasChanged);

        // Camera click-to-place: when camera panel requests location picking,
        // the next map click sends the coordinates back (Loop 8 drag-to-place)
        EventBus.on('camera:pick-location', _onCameraPickLocation);

        // Target trail and correlation overlay events
        EventBus.on('target:showTrail', _onShowTargetTrail);
        EventBus.on('target:hideTrail', _onHideTargetTrail);
        EventBus.on('target:showCorrelationLines', _onShowCorrelationLines);

        // Fetch cameras immediately on map load so markers appear without
        // needing to open the camera-feeds panel first.
        _fetchCamerasForMap();

        // Re-fetch cameras periodically (demo mode may register new cameras)
        // Also triggered when demo mode starts via the demo:started event
        setInterval(_fetchCamerasForMap, 15000);

        // Apply the initial mode (default: observe) so visual state matches
        setMapMode(_state.currentMode || 'observe');

        // Start unit update loop
        _startUnitLoop();
    };

    _state.map.on('load', _onMapLoaded);

    // Fallback: if map is already loaded (cached), fire immediately
    if (_state.map.loaded()) {
        console.log('[MAP-ML] Map already loaded (cached), initializing immediately');
        _onMapLoaded();
    }

    // Safety net: if load event never fires within 5s, force-init
    setTimeout(() => {
        if (!_state.initialized) {
            console.warn('[MAP-ML] Load event did not fire in 5s — force-initializing');
            _onMapLoaded();
        }
    }, 5000);

    _state.map.on('click', _onMapClick);
    _state.map.on('dblclick', _onMapDblClick);
    _state.map.on('contextmenu', _onMapRightClick);
    _state.map.on('mousemove', _onMapMouseMove);
    _state.map.on('moveend', _updateLayerHud);
    _state.map.on('moveend', _reportViewport);
    _state.map.on('zoomend', _updateLayerHud);
    _state.map.on('zoomend', _reportViewport);
    _state.map.on('pitchend', _updateLayerHud);
}

// ============================================================
// Compass Rose — always-visible compass showing north direction
// ============================================================

function _addCompassRose() {
    const rose = document.createElement('div');
    rose.id = 'tritium-compass-rose';
    rose.style.cssText = `
        position: absolute;
        bottom: 50px;
        left: 12px;
        width: 72px;
        height: 72px;
        pointer-events: none;
        z-index: 10;
        opacity: 0.85;
    `;

    const canvas = document.createElement('canvas');
    canvas.width = 144;
    canvas.height = 144;
    canvas.style.cssText = 'width:72px;height:72px;';
    rose.appendChild(canvas);

    const mapContainer = _state.map.getContainer();
    mapContainer.appendChild(rose);
    _state._compassCanvas = canvas;

    function drawCompass() {
        if (!_state.map) return;
        const bearing = _state.map.getBearing();
        const ctx = canvas.getContext('2d');
        const cx = 72, cy = 72, r = 60;

        ctx.clearRect(0, 0, 144, 144);
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(-bearing * Math.PI / 180);

        // Outer ring
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(0, 240, 255, 0.3)';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Cardinal ticks and labels
        const cardinals = [
            { angle: 0, label: 'N', color: '#ff2a6d' },
            { angle: 90, label: 'E', color: '#00f0ff' },
            { angle: 180, label: 'S', color: '#00f0ff' },
            { angle: 270, label: 'W', color: '#00f0ff' },
        ];
        for (const c of cardinals) {
            const a = (c.angle - 90) * Math.PI / 180;
            // Tick
            ctx.beginPath();
            ctx.moveTo(Math.cos(a) * (r - 10), Math.sin(a) * (r - 10));
            ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
            ctx.strokeStyle = c.color;
            ctx.lineWidth = c.label === 'N' ? 3 : 1.5;
            ctx.stroke();
            // Label
            ctx.fillStyle = c.color;
            ctx.font = c.label === 'N' ? 'bold 16px monospace' : '11px monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(c.label, Math.cos(a) * (r - 22), Math.sin(a) * (r - 22));
        }

        // Intercardinal ticks
        for (let deg = 45; deg < 360; deg += 90) {
            const a = (deg - 90) * Math.PI / 180;
            ctx.beginPath();
            ctx.moveTo(Math.cos(a) * (r - 5), Math.sin(a) * (r - 5));
            ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.2)';
            ctx.lineWidth = 1;
            ctx.stroke();
        }

        // North arrow (triangle pointing up)
        ctx.beginPath();
        ctx.moveTo(0, -36);
        ctx.lineTo(-6, -20);
        ctx.lineTo(6, -20);
        ctx.closePath();
        ctx.fillStyle = '#ff2a6d';
        ctx.fill();

        // South arrow (dimmer)
        ctx.beginPath();
        ctx.moveTo(0, 36);
        ctx.lineTo(-5, 20);
        ctx.lineTo(5, 20);
        ctx.closePath();
        ctx.fillStyle = 'rgba(0, 240, 255, 0.25)';
        ctx.fill();

        // Center dot
        ctx.beginPath();
        ctx.arc(0, 0, 3, 0, Math.PI * 2);
        ctx.fillStyle = '#00f0ff';
        ctx.fill();

        ctx.restore();
    }

    // Redraw on bearing change
    _state.map.on('rotate', drawCompass);
    _state.map.on('load', drawCompass);
    drawCompass();
}

// ============================================================
// MapLibre Style: Satellite + Vector overlays
// ============================================================

function _buildStyle() {
    return {
        version: 8,
        name: 'TRITIUM Tactical',
        glyphs: 'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
        sources: {
            // ESRI World Imagery satellite tiles
            'satellite': {
                type: 'raster',
                tiles: [
                    '/api/geo/tile/{z}/{x}/{y}',
                ],
                tileSize: 256,
                attribution: '&copy; ESRI World Imagery',
                maxzoom: 20,
            },
            // ESRI road overlay tiles (transparent)
            'road-overlay': {
                type: 'raster',
                tiles: [
                    '/api/geo/road-tile/{z}/{x}/{y}',
                ],
                tileSize: 256,
                maxzoom: 20,
            },
            // Mapzen Terrarium DEM tiles (AWS Public Dataset, no API key)
            'terrain-dem': {
                type: 'raster-dem',
                tiles: ['/api/geo/terrain-tile/{z}/{x}/{y}.png'],
                tileSize: 256,
                maxzoom: 15,
                encoding: 'terrarium',
                attribution: '&copy; <a href="https://registry.opendata.aws/terrain-tiles/">Mapzen/AWS Terrain Tiles</a>',
            },
            // OpenFreeMap vector tiles (buildings, roads, landuse, water)
            'openfree': {
                type: 'vector',
                url: 'https://tiles.openfreemap.org/planet',
            },
        },
        layers: [
            // Background (dark)
            {
                id: 'background',
                type: 'background',
                paint: { 'background-color': '#060609' },
            },
            // Satellite imagery base
            {
                id: 'satellite-layer',
                type: 'raster',
                source: 'satellite',
                paint: {
                    'raster-opacity': 1.0,
                    'raster-brightness-max': 1.0,
                    'raster-contrast': 0.1,
                    'raster-saturation': -0.1,
                },
                layout: { 'visibility': 'visible' },
            },
            // Road overlay (transparent labels/lines from ESRI)
            {
                id: 'road-overlay-layer',
                type: 'raster',
                source: 'road-overlay',
                paint: {
                    'raster-opacity': 0.6,
                },
                layout: { 'visibility': 'visible' },
            },
            // Water bodies from vector tiles
            {
                id: 'water-fill',
                type: 'fill',
                source: 'openfree',
                'source-layer': 'water',
                paint: {
                    'fill-color': '#0a2540',
                    'fill-opacity': 0.6,
                },
            },
            // Parks/green areas
            {
                id: 'park-fill',
                type: 'fill',
                source: 'openfree',
                'source-layer': 'landuse',
                filter: ['in', 'class', 'park', 'grass', 'cemetery'],
                paint: {
                    'fill-color': '#0a2a10',
                    'fill-opacity': 0.3,
                },
            },
            // 3D Buildings from vector tiles — THE KEY FEATURE
            // These are from OpenStreetMap data, properly aligned to the
            // same coordinate system as everything else via Web Mercator.
            {
                id: 'buildings-3d',
                type: 'fill-extrusion',
                source: 'openfree',
                'source-layer': 'building',
                minzoom: 14,
                paint: {
                    'fill-extrusion-color': '#0d1030',
                    'fill-extrusion-height': [
                        'coalesce',
                        ['get', 'render_height'],
                        8, // default 8m
                    ],
                    'fill-extrusion-base': [
                        'coalesce',
                        ['get', 'render_min_height'],
                        0,
                    ],
                    'fill-extrusion-opacity': 0.7,
                },
                layout: { 'visibility': 'visible' },
            },
            // Building outlines (cyan wireframe effect)
            {
                id: 'buildings-outline',
                type: 'line',
                source: 'openfree',
                'source-layer': 'building',
                minzoom: 14,
                paint: {
                    'line-color': '#00f0ff',
                    'line-width': 0.8,
                    'line-opacity': 0.5,
                },
                layout: { 'visibility': 'visible' },
            },
            // Road lines from vector tiles (subtle)
            {
                id: 'roads-line',
                type: 'line',
                source: 'openfree',
                'source-layer': 'transportation',
                paint: {
                    'line-color': [
                        'match', ['get', 'class'],
                        'motorway', '#445566',
                        'trunk', '#3a4a5a',
                        'primary', '#354555',
                        'secondary', '#304050',
                        '#283848',
                    ],
                    'line-width': [
                        'match', ['get', 'class'],
                        'motorway', 3,
                        'trunk', 2.5,
                        'primary', 2,
                        'secondary', 1.5,
                        1,
                    ],
                    'line-opacity': 0.4,
                },
            },
        ],
    };
}

// ============================================================
// Three.js Custom Layer (tactical overlays)
// ============================================================

function _addThreeJsLayer() {
    if (typeof THREE === 'undefined') {
        console.warn('[MAP-ML] Three.js not loaded, skipping tactical overlay');
        return;
    }
    if (!_state.showModels3d) {
        console.log('[MAP-ML] 3D models disabled, skipping Three.js layer');
        return;
    }

    // Precompute the reference-point transform.
    // All Three.js objects are positioned in game coordinates (meters from
    // geoCenter) inside a root Group. The meters-to-Mercator reference
    // transform is baked into the camera projection matrix each frame
    // (proj = MapLibreVP * refMatrix) rather than on the root Group.
    // This keeps object positions as small numbers (~tens of meters)
    // instead of huge Mercator values (~0.5), and ensures Three.js frustum
    // culling works correctly at all pitch angles including 0 (top-down).
    const refLngLat = [_state.geoCenter.lng, _state.geoCenter.lat];
    const refMc = maplibregl.MercatorCoordinate.fromLngLat(refLngLat, 0);
    const ms = refMc.meterInMercatorCoordinateUnits();
    _state._refMc = refMc;
    _state._ms = ms;

    const customLayer = {
        id: 'three-overlay',
        type: 'custom',
        renderingMode: '3d',

        onAdd(map, gl) {
            _state.threeScene = new THREE.Scene();
            _state.threeCamera = new THREE.Camera();
            _state.threeRenderer = new THREE.WebGLRenderer({
                canvas: map.getCanvas(),
                context: gl,
                antialias: true,
            });
            _state.threeRenderer.autoClear = false;

            // Root group for tactical objects (units, effects).
            // Children are positioned in game-meter coordinates.
            // The meters-to-Mercator transform is baked into the camera
            // projection matrix each frame (matching the official MapLibre
            // Three.js pattern) so that Three.js frustum culling works
            // correctly at all pitch angles including pitch=0 (top-down).
            _state.threeRoot = new THREE.Group();
            _state.threeRoot.frustumCulled = false;

            // Override add() to auto-disable frustum culling on all children.
            // MapLibre custom layers use a non-standard projection matrix that
            // makes Three.js frustum extraction unreliable, so we disable it
            // globally for all tactical objects.
            const origAdd = _state.threeRoot.add.bind(_state.threeRoot);
            _state.threeRoot.add = function(...objects) {
                for (const obj of objects) {
                    obj.traverse(child => { child.frustumCulled = false; });
                }
                return origAdd(...objects);
            };

            _state.threeScene.add(_state.threeRoot);

            // Separate always-visible group for combat effects.
            // threeRoot.visible is toggled by the "3D Models" layer switch,
            // but combat effects (tracers, explosions, particles) must
            // remain visible in ALL map modes including observe.
            _state.threeEffectsRoot = new THREE.Group();
            _state.threeEffectsRoot.frustumCulled = false;
            _state.threeEffectsRoot.name = 'effects-root';
            const origEffAdd = _state.threeEffectsRoot.add.bind(_state.threeEffectsRoot);
            _state.threeEffectsRoot.add = function(...objects) {
                for (const obj of objects) {
                    obj.traverse(child => { child.frustumCulled = false; });
                }
                return origEffAdd(...objects);
            };
            _state.threeScene.add(_state.threeEffectsRoot);

            // Pre-compute the meters-to-Mercator reference matrix.
            // Applied per-frame: camera.projectionMatrix = MapLibreVP * refMatrix
            _state._refMatrix = new THREE.Matrix4()
                .makeTranslation(refMc.x, refMc.y, refMc.z || 0)
                .scale(new THREE.Vector3(ms, -ms, ms));

            // Ambient light (scene-level, not inside root)
            _state.threeScene.add(new THREE.AmbientLight(0xffffff, 0.8));

            // Directional light — positioned in meter space
            const dirLight = new THREE.DirectionalLight(0xffffff, 0.5);
            dirLight.position.set(100, 200, 100);
            _state.threeScene.add(dirLight);

            // Vision system (fog of war overlay)
            _state.visionSystem = new FrontendVisionSystem();
            _state.visionSystem.init(_state.threeScene, _state);
        },

        render(gl, args) {
            if (!_state.threeScene || !_state.threeCamera) return;

            // Update vision system (fog of war overlay)
            if (_state.visionSystem) {
                const units = [...TritiumStore.units.values()];
                _state.visionSystem.update(units, TritiumStore.get('game.phase') || 'idle', 0.016);
            }

            // Update combat effects before rendering
            _tickEffects();

            // Animate 3D unit models (rotor spin, ring pulse)
            _animate3DUnits(performance.now());

            // MapLibre v4+ passes args.defaultProjectionData.mainMatrix
            const matrixData = (args && args.defaultProjectionData)
                ? args.defaultProjectionData.mainMatrix
                : args;

            // Bake the meters-to-Mercator reference transform into the
            // camera projection matrix:  proj = MapLibreVP * refMatrix.
            // This matches the official MapLibre Three.js example and
            // ensures Three.js frustum culling, depth sorting, and all
            // internal tests operate in the correct coordinate space.
            // Previously the ref transform lived on the root group, which
            // caused Three.js to extract a Mercator-space frustum from the
            // bare MapLibre matrix while objects reported meter-space
            // bounding volumes — at pitch=0 (top-down) the near/far planes
            // were so tight that every object was culled as out-of-frustum.
            _tempMatrix.fromArray(matrixData);
            _tempMatrix.multiply(_state._refMatrix);
            _state.threeCamera.projectionMatrix.copy(_tempMatrix);
            _state.threeCamera.projectionMatrixInverse.copy(_tempMatrix).invert();

            _state.threeRenderer.resetState();
            // Clear depth buffer so tactical objects render above map tiles.
            // At pitch=0 (top-down), tiles and 3D objects occupy nearly
            // identical depth values — MapLibre's depth rejects our fragments.
            // depthMask(true) ensures the clear actually writes.
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);
            _state.threeRenderer.render(_state.threeScene, _state.threeCamera);
            // NOTE: Do NOT call triggerRepaint() here unconditionally.
            // _repaintLoop() already manages triggerRepaint() via rAF when
            // there are active effects or 3D units.  An unconditional call
            // here creates an infinite repaint loop (~60 FPS GPU burn even
            // when nothing animates).
        },
    };

    _state.map.addLayer(customLayer);
}

/**
 * Convert game coordinates (meters from geo reference) to lat/lng.
 */
function _gameToLngLat(gx, gy) {
    if (!_state.geoCenter) return [0, 0];
    const R = 6378137;
    const latRad = _state.geoCenter.lat * Math.PI / 180;
    const dLng = gx / (R * Math.cos(latRad)) * (180 / Math.PI);
    const dLat = gy / R * (180 / Math.PI);
    return [_state.geoCenter.lng + dLng, _state.geoCenter.lat + dLat];
}

/**
 * Convert lng/lat back to game coordinates (meters from geo reference).
 */
function _lngLatToGame(lng, lat) {
    if (!_state.geoCenter) return { x: 0, y: 0 };
    const R = 6378137;
    const latRad = _state.geoCenter.lat * Math.PI / 180;
    const gx = (lng - _state.geoCenter.lng) * (Math.PI / 180) * R * Math.cos(latRad);
    const gy = (lat - _state.geoCenter.lat) * (Math.PI / 180) * R;
    return { x: gx, y: gy };
}

// ============================================================
// Minimap Integration
// ============================================================

/**
 * Draw minimap panel content — called from the 10Hz unit update loop.
 * Computes MapLibre viewport bounds in game coordinates and passes to
 * drawMinimapContent() which renders zones, units, and camera rectangle.
 */
function _drawMinimap() {
    if (!_state.map || !_state.initialized) return;

    // Compute MapLibre viewport bounds in game coordinates
    const bounds = _state.map.getBounds();
    const sw = _lngLatToGame(bounds.getWest(), bounds.getSouth());
    const ne = _lngLatToGame(bounds.getEast(), bounds.getNorth());

    drawMinimapContent({
        viewportBounds: {
            minX: sw.x,
            maxX: ne.x,
            minY: sw.y,
            maxY: ne.y,
        },
    });
}

/**
 * Handle minimap click-to-pan: receive game coordinates, pan MapLibre map.
 */
function _onMinimapPan(data) {
    if (!_state.map || !data) return;
    const lngLat = _gameToLngLat(data.x, data.y);
    _state.map.panTo(lngLat, { duration: 300 });
}

/**
 * Convert mission radius (meters) to MapLibre zoom level.
 * Formula: at zoom 16, ~920m fits the viewport width.
 * Doubling zoom halves the visible area, so log2(920/radius) adjusts.
 */
function _radiusToZoom(radiusM) {
    const z = 16 + Math.log2(920 / Math.max(radiusM, 50));
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, z));
}

/**
 * Handle map:flyToMission event — fly camera to mission area.
 * Accepts { center: {x, y}, radius, name } from mission-modal.js.
 * Also supports direct lat/lng for flexibility.
 */
function _onPanToMission(data) {
    if (!_state.map || !data) return;

    let lngLat;
    if (data.center && data.center.x !== undefined && data.center.y !== undefined) {
        lngLat = _gameToLngLat(data.center.x, data.center.y);
    } else if (data.lat !== undefined && data.lng !== undefined) {
        lngLat = [data.lng, data.lat];
    } else if (data.x !== undefined && data.y !== undefined) {
        lngLat = _gameToLngLat(data.x, data.y);
    } else {
        return;
    }

    const radius = data.radius || data.radius_m || 200;
    const zoom = _radiusToZoom(radius);
    const clampedZoom = Math.max(ZOOM_MIN, Math.min(19, zoom));

    _state.map.flyTo({
        center: lngLat,
        zoom: clampedZoom,
        pitch: PITCH_DEFAULT,
        bearing: 0,
        duration: 1500,
        essential: true,
    });

    // Draw combat radius circle overlay
    _drawCombatRadius(lngLat, radius);

    if (data.name) {
        console.log(`[MAP-ML] Flying to mission: ${data.name} radius=${radius}m zoom=${clampedZoom.toFixed(1)}`);
    }
}

/**
 * Handle map:centerOnUnit event — fly camera to a unit or coordinate.
 * Accepts { id } (unit ID lookup) or { x, y } (game coordinates).
 * Emitted by patrol.js and zones.js panels.
 */
function _onCenterOnUnit(data) {
    if (!_state.map || !data) return;

    let gx, gy;
    if (data.id) {
        const u = TritiumStore.units.get(data.id);
        if (!u || !u.position) return;
        gx = u.position.x || 0;
        gy = u.position.y || 0;
    } else if (data.x !== undefined && data.y !== undefined) {
        gx = data.x;
        gy = data.y;
    } else {
        return;
    }

    const lngLat = _gameToLngLat(gx, gy);
    _state.map.flyTo({
        center: lngLat,
        zoom: 17,
        pitch: PITCH_DEFAULT,
        bearing: 0,
        duration: 1000,
        essential: true,
    });
}

/**
 * Handle map:marker event — place a temporary marker on the map.
 * Emitted from context-menu.js when operator selects "DROP MARKER".
 * @param {Object} data - { x, y } game coordinates
 */
const _operatorMarkers = [];
function _onDropMarker(data) {
    if (!_state.map || !data || data.x === undefined || data.y === undefined) return;
    const lngLat = _gameToLngLat(data.x, data.y);

    const el = document.createElement('div');
    el.className = 'operator-marker';
    el.style.cssText = 'width:12px;height:12px;border:2px solid #fcee0a;border-radius:50%;background:rgba(252,238,10,0.3);pointer-events:none;';

    const marker = new maplibregl.Marker({ element: el })
        .setLngLat(lngLat)
        .addTo(_state.map);
    _operatorMarkers.push(marker);

    // Auto-remove after 30 seconds
    setTimeout(() => {
        marker.remove();
        const idx = _operatorMarkers.indexOf(marker);
        if (idx >= 0) _operatorMarkers.splice(idx, 1);
    }, 30000);
}

/**
 * Handle map:waypoint event — show a transient waypoint indicator.
 * Emitted from context-menu.js when operator selects "SET WAYPOINT".
 * @param {Object} data - { x, y, unitId } game coordinates
 */
function _onDropWaypoint(data) {
    if (!_state.map || !data || data.x === undefined || data.y === undefined) return;
    const lngLat = _gameToLngLat(data.x, data.y);

    const el = document.createElement('div');
    el.className = 'operator-waypoint';
    el.style.cssText = 'width:10px;height:10px;border:2px solid #05ffa1;background:rgba(5,255,161,0.3);transform:rotate(45deg);pointer-events:none;';

    const marker = new maplibregl.Marker({ element: el })
        .setLngLat(lngLat)
        .addTo(_state.map);

    // Auto-remove after 10 seconds (real waypoints come from telemetry)
    setTimeout(() => { marker.remove(); }, 10000);
}

// ============================================================
// Combat Radius Circle Overlay (GeoJSON)
// ============================================================

const COMBAT_RADIUS_SOURCE  = 'combat-radius-source';
const COMBAT_RADIUS_FILL    = 'combat-radius-fill';
const COMBAT_RADIUS_OUTLINE = 'combat-radius-outline';

// Weapon range circle overlay
const WEAPON_RANGE_SOURCE = 'weapon-range-source';
const WEAPON_RANGE_FILL   = 'weapon-range-fill';
const WEAPON_RANGE_STROKE = 'weapon-range-stroke';

// Combat zone heatmap overlay
const COMBAT_HEATMAP_SOURCE = 'combat-heatmap-source';
const COMBAT_HEATMAP_LAYER  = 'combat-heatmap';

// Drone swarm convex hull overlay
const SWARM_HULL_SOURCE = 'swarm-hull-source';
const SWARM_HULL_FILL   = 'swarm-hull-fill';
const SWARM_HULL_STROKE = 'swarm-hull-stroke';

// Squad formation convex hull overlay
const SQUAD_HULL_SOURCE = 'squad-hulls-source';
const SQUAD_HULL_FILL   = 'squad-hulls-fill';
const SQUAD_HULL_STROKE = 'squad-hulls-stroke';

// Squad tactical order colors
const SQUAD_ORDER_COLORS = {
    advance: '#ff2a6d',  // magenta
    hold:    '#fcee0a',  // amber/yellow
    flank:   '#00f0ff',  // cyan
    retreat: '#a08820',  // dim yellow
};
const SQUAD_DEFAULT_COLOR = '#ff2a6d';  // magenta

// Hazard zone overlay (environmental hazards: fire/flood/roadblock)
const HAZARD_ZONES_SOURCE = 'hazard-zones-source';
const HAZARD_ZONES_FILL   = 'hazard-zones-fill';
const HAZARD_ZONES_STROKE = 'hazard-zones-stroke';

// Hostile objective lines overlay
const HOSTILE_OBJ_SOURCE = 'hostile-obj-source';
const HOSTILE_OBJ_LINE   = 'hostile-obj-line';

// Crowd density heatmap overlay (civil_unrest mode)
const CROWD_DENSITY_SOURCE = 'crowd-density-source';
const CROWD_DENSITY_FILL   = 'crowd-density-fill';

// Cover points overlay
const COVER_POINTS_SOURCE = 'cover-points-source';
const COVER_POINTS_CIRCLE = 'cover-points-circle';
const COVER_POINTS_ICON   = 'cover-points-icon';

// Unit signals overlay (distress/contact/regroup/retreat)
const UNIT_SIGNALS_SOURCE = 'unit-signals-source';
const UNIT_SIGNALS_CIRCLE = 'unit-signals-circle';

const ENGAGEMENT_LINES_SOURCE = 'engagement-lines-source';
const ENGAGEMENT_LINES_LAYER  = 'engagement-lines-layer';

// Hazard type colors
const HAZARD_COLORS = {
    fire:      '#ff4400',
    flood:     '#0088ff',
    roadblock: '#ffcc00',
};

// Signal type colors
const SIGNAL_COLORS = {
    distress:          '#ff2a6d',
    contact:           '#ff8800',
    regroup:           '#00f0ff',
    retreat:           '#888888',
    instigator_marked: '#ff2a6d',
    emp_jamming:       '#fcee0a',
};

// Auto-follow timing
const AUTO_FOLLOW_INTERVAL = 7000;  // ms between evaluations (6-8s)
const AUTO_FOLLOW_FLY_DURATION = 2000;  // ms flyTo animation
const COMBAT_EVENT_RING_SIZE = 20;
const COMBAT_EVENT_MAX_AGE = 10000;  // 10 seconds

/**
 * Draw a translucent circle + dashed outline marking the combat zone.
 * @param {number[]} centerLngLat - [lng, lat]
 * @param {number} radiusMeters - combat radius
 */
function _drawCombatRadius(centerLngLat, radiusMeters) {
    const circle = _makeCircleGeoJSON(centerLngLat, radiusMeters, 64);

    if (_state.map.getSource(COMBAT_RADIUS_SOURCE)) {
        _state.map.getSource(COMBAT_RADIUS_SOURCE).setData(circle);
    } else {
        _state.map.addSource(COMBAT_RADIUS_SOURCE, {
            type: 'geojson',
            data: circle,
        });
        _state.map.addLayer({
            id: COMBAT_RADIUS_FILL,
            type: 'fill',
            source: COMBAT_RADIUS_SOURCE,
            paint: {
                'fill-color': '#ff2a6d',
                'fill-opacity': 0.08,
            },
        });
        _state.map.addLayer({
            id: COMBAT_RADIUS_OUTLINE,
            type: 'line',
            source: COMBAT_RADIUS_SOURCE,
            paint: {
                'line-color': '#ff2a6d',
                'line-width': 2,
                'line-opacity': 0.6,
                'line-dasharray': [4, 4],
            },
        });
    }
}

/**
 * Remove the combat radius circle overlay.
 */
function _clearCombatRadius() {
    try {
        if (_state.map && _state.map.getLayer(COMBAT_RADIUS_FILL))
            _state.map.removeLayer(COMBAT_RADIUS_FILL);
        if (_state.map && _state.map.getLayer(COMBAT_RADIUS_OUTLINE))
            _state.map.removeLayer(COMBAT_RADIUS_OUTLINE);
        if (_state.map && _state.map.getSource(COMBAT_RADIUS_SOURCE))
            _state.map.removeSource(COMBAT_RADIUS_SOURCE);
    } catch (_e) {
        // Layers may not exist yet
    }
}

/**
 * Generate a GeoJSON Polygon approximating a circle.
 * @param {number[]} centerLngLat - [lng, lat]
 * @param {number} radiusMeters
 * @param {number} points - number of polygon vertices
 * @returns {Object} GeoJSON Feature
 */
function _makeCircleGeoJSON(centerLngLat, radiusMeters, points) {
    const coords = [];
    const R = 6378137; // Earth radius in meters
    const lat = centerLngLat[1] * Math.PI / 180;
    const lng = centerLngLat[0] * Math.PI / 180;

    for (let i = 0; i <= points; i++) {
        const angle = (i / points) * 2 * Math.PI;
        const dLat = (radiusMeters * Math.cos(angle)) / R;
        const dLng = (radiusMeters * Math.sin(angle)) / (R * Math.cos(lat));
        coords.push([
            (lng + dLng) * 180 / Math.PI,
            (lat + dLat) * 180 / Math.PI,
        ]);
    }

    return {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [coords] },
    };
}

// ============================================================
// Setup Mode — Ghost Placement Preview
// ============================================================

const SETUP_GHOST_SOURCE = 'setup-ghost-source';
const SETUP_GHOST_FILL   = 'setup-ghost-fill';
const SETUP_GHOST_LINE   = 'setup-ghost-line';
const SETUP_GHOST_ICON   = 'setup-ghost-icon';

/** Weapon range per unit type (meters). */
const SETUP_UNIT_RANGES = {
    turret: 80,
    heavy_turret: 120,
    missile_turret: 150,
    rover: 60,
    drone: 50,
    scout_drone: 40,
    tank: 100,
    apc: 60,
};

/**
 * Update the ghost placement preview at the given lngLat.
 * Creates the GeoJSON source and layers on first call,
 * updates the data on subsequent calls.
 * @param {number[]} lngLat - [lng, lat]
 */
function _updateSetupGhost(lngLat) {
    if (!_state.map || !_state.initialized) return;

    const unitType = (typeof window !== 'undefined' && window._setupPlacementType) || 'turret';
    const radius = SETUP_UNIT_RANGES[unitType] || 20;
    const circle = _makeCircleGeoJSON(lngLat, radius, 48);

    if (_state.map.getSource(SETUP_GHOST_SOURCE)) {
        _state.map.getSource(SETUP_GHOST_SOURCE).setData(circle);
    } else {
        _state.map.addSource(SETUP_GHOST_SOURCE, {
            type: 'geojson',
            data: circle,
        });
        _state.map.addLayer({
            id: SETUP_GHOST_FILL,
            type: 'fill',
            source: SETUP_GHOST_SOURCE,
            paint: {
                'fill-color': '#00f0ff',
                'fill-opacity': 0.1,
            },
        });
        _state.map.addLayer({
            id: SETUP_GHOST_LINE,
            type: 'line',
            source: SETUP_GHOST_SOURCE,
            paint: {
                'line-color': '#00f0ff',
                'line-width': 1.5,
                'line-opacity': 0.4,
            },
        });
    }
}

/**
 * Remove ghost placement preview layers and source.
 */
function _clearSetupGhost() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(SETUP_GHOST_LINE))
                _state.map.removeLayer(SETUP_GHOST_LINE);
            if (_state.map.getLayer(SETUP_GHOST_FILL))
                _state.map.removeLayer(SETUP_GHOST_FILL);
            if (_state.map.getSource(SETUP_GHOST_SOURCE))
                _state.map.removeSource(SETUP_GHOST_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

/**
 * Handle mousemove on the map — update ghost preview in setup mode.
 */
function _onMapMouseMove(e) {
    // Geofence draw mode: update rubber-band line to mouse cursor
    if (_state.geofenceDrawMode && _state.geofenceDrawVertices.length > 0) {
        _state.geofenceDrawMouseLngLat = [e.lngLat.lng, e.lngLat.lat];
        _updateGeofenceDrawPreview();
    }

    // Patrol draw mode: update rubber-band line to mouse cursor
    if (_state.patrolDrawMode && _state.patrolDrawWaypoints.length > 0) {
        _state.patrolDrawMouseLngLat = [e.lngLat.lng, e.lngLat.lat];
        _updatePatrolDrawPreview();
    }

    if (_state.currentMode !== 'setup') return;
    const lngLat = [e.lngLat.lng, e.lngLat.lat];
    _updateSetupGhost(lngLat);
}

// ============================================================
// Patrol Route Overlay (GeoJSON lines for friendly patrol paths)
// ============================================================

const PATROL_ROUTES_SOURCE = 'patrol-routes-source';
const PATROL_ROUTES_LINE   = 'patrol-routes-line';
const PATROL_ROUTES_ARROWS = 'patrol-routes-arrows';
const PATROL_ROUTES_DOTS   = 'patrol-routes-dots';

const DISPATCH_ARROWS_SOURCE = 'dispatch-arrows-source';
const DISPATCH_ARROWS_LINE   = 'dispatch-arrows-line';

/**
 * Determine if a unit should show a patrol route.
 * Only friendly units with 2+ waypoints that are looping patrol or in a
 * patrolling FSM state qualify.
 */
function _isPatrolling(unit) {
    if (!unit) return false;
    if (unit.alliance !== 'friendly') return false;
    const wps = unit.waypoints;
    if (!Array.isArray(wps) || wps.length < 2) return false;
    // Show route if unit has looping waypoints or is in a patrol FSM state
    if (unit.loopWaypoints) return true;
    const state = (unit.fsmState || unit.fsm_state || '').toLowerCase();
    return state === 'patrolling' || state === 'scanning' || state === 'idle';
}

/**
 * Lightweight fingerprint of a GeoJSON FeatureCollection.
 * Concatenates feature count + all coordinates + property values into a
 * single string.  Used by overlay update functions to skip redundant
 * setData() calls when nothing changed.
 */
function _hashGeoJSONFeatures(geojson) {
    const feats = geojson.features || [];
    if (feats.length === 0) return '0';
    const parts = [feats.length];
    for (let i = 0; i < feats.length; i++) {
        const g = feats[i].geometry;
        if (!g) continue;
        const coords = g.coordinates;
        if (Array.isArray(coords)) {
            parts.push(JSON.stringify(coords));
        }
        // Include key properties that affect rendering
        const p = feats[i].properties;
        if (p) {
            if (p.opacity !== undefined) parts.push('o' + p.opacity.toFixed(2));
            if (p.color) parts.push(p.color);
            if (p.order) parts.push(p.order);
        }
    }
    return parts.join('|');
}

/**
 * Build a GeoJSON FeatureCollection of patrol route lines from all
 * qualifying friendly units.  Each unit's route is a separate Feature
 * so lines don't connect across units.
 */
function _buildPatrolRoutesGeoJSON() {
    const features = [];
    const units = TritiumStore.units;
    units.forEach((unit, _id) => {
        if (!_isPatrolling(unit)) return;
        const coords = unit.waypoints.map(wp => _gameToLngLat(wp.x, wp.y));
        // Close the loop for looping patrol routes
        if (unit.loopWaypoints && coords.length >= 2) {
            coords.push(coords[0]);
        }
        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: coords },
            properties: { unitId: _id, unitName: unit.name || _id },
        });
        // Add waypoint dot markers at each node
        for (const wp of unit.waypoints) {
            features.push({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: _gameToLngLat(wp.x, wp.y) },
                properties: { unitId: _id },
            });
        }
    });
    return { type: 'FeatureCollection', features };
}

/**
 * Create or update the patrol route MapLibre source and layers.
 * Called from the 10Hz _updateUnits() loop.
 */
function _updatePatrolRoutes() {
    if (!_state.map || !_state.initialized) return;

    const geojson = _buildPatrolRoutesGeoJSON();

    if (_state.map.getSource(PATROL_ROUTES_SOURCE)) {
        // Skip setData() if features unchanged
        const hash = _hashGeoJSONFeatures(geojson);
        if (hash === _state._lastPatrolHash) return;
        _state._lastPatrolHash = hash;
        _state.map.getSource(PATROL_ROUTES_SOURCE).setData(geojson);
    } else {
        // First call: create source and layers
        _state.map.addSource(PATROL_ROUTES_SOURCE, {
            type: 'geojson',
            data: geojson,
        });

        // Dashed route line
        _state.map.addLayer({
            id: PATROL_ROUTES_LINE,
            type: 'line',
            source: PATROL_ROUTES_SOURCE,
            filter: ['==', '$type', 'LineString'],
            layout: {
                'line-cap': 'round',
                'line-join': 'round',
                'visibility': _state.showPatrolRoutes ? 'visible' : 'none',
            },
            paint: {
                'line-color': '#05ffa1',
                'line-width': 2.5,
                'line-opacity': 0.5,
                'line-dasharray': [2, 3],
            },
        });

        // Direction arrows along the route (symbol layer with triangle glyphs)
        // MapLibre requires SDF icons or glyphs for symbol layers.
        // Use a simple circle layer at waypoint nodes instead for reliability.
        _state.map.addLayer({
            id: PATROL_ROUTES_DOTS,
            type: 'circle',
            source: PATROL_ROUTES_SOURCE,
            filter: ['==', '$type', 'Point'],
            layout: {
                'visibility': _state.showPatrolRoutes ? 'visible' : 'none',
            },
            paint: {
                'circle-radius': 4,
                'circle-color': '#05ffa1',
                'circle-opacity': 0.7,
                'circle-stroke-width': 1,
                'circle-stroke-color': '#003322',
                'circle-stroke-opacity': 0.9,
            },
        });
    }
}

// ============================================================
// Dispatch arrow layer (dashed cyan lines, fade after 3s)
// Also: persistent dispatch lines for robots actively en route.
// ============================================================

// Animated dash offset counter for robot dispatch lines
let _dispatchDashPhase = 0;

function _buildDispatchArrowsGeoJSON() {
    const now = Date.now();
    const cutoff = now - DISPATCH_ARROW_LIFETIME;
    // Prune expired temporary arrows
    _state.dispatchArrows = _state.dispatchArrows.filter(a => a.time > cutoff);

    const features = [];

    // 1) Temporary flash arrows (3s fade)
    for (const arrow of _state.dispatchArrows) {
        const fromLL = _gameToLngLat(arrow.fromX, arrow.fromY);
        const toLL = _gameToLngLat(arrow.toX, arrow.toY);
        const age = now - arrow.time;
        const opacity = Math.max(0, 1 - age / DISPATCH_ARROW_LIFETIME);
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [fromLL, toLL],
            },
            properties: { opacity, lineType: 'flash' },
        });
    }

    // 2) Persistent dispatch lines for robots actively moving to a target
    const units = TritiumStore.units;
    units.forEach((unit, id) => {
        if (unit.alliance !== 'friendly') return;
        const uType = (unit.type || '').toLowerCase();
        const isRobot = uType.includes('rover') || uType.includes('drone') || uType.includes('scout') || uType.includes('robot');
        if (!isRobot) return;
        // Check if the unit has a dispatch target and is actively moving
        const dt = unit.dispatch_target || unit.dispatchTarget;
        if (!dt) return;
        const fsmState = (unit.fsmState || unit.fsm_state || '').toLowerCase();
        const isMoving = fsmState === 'moving' || fsmState === 'dispatched' || fsmState === 'pursuing' || fsmState === 'navigating';
        if (!isMoving && !dt) return;
        const pos = unit.position;
        if (!pos) return;
        const fromLL = _gameToLngLat(pos.x || 0, pos.y || 0);
        const toLL = _gameToLngLat(dt.x || 0, dt.y || 0);
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [fromLL, toLL],
            },
            properties: { opacity: 0.8, lineType: 'active-dispatch' },
        });
    });

    return { type: 'FeatureCollection', features };
}

function _updateDispatchArrows() {
    if (!_state.map || !_state.initialized) return;

    // Advance animated dash phase for marching-ant effect
    _dispatchDashPhase = (_dispatchDashPhase + 0.3) % 100;

    const geojson = _buildDispatchArrowsGeoJSON();

    if (_state.map.getSource(DISPATCH_ARROWS_SOURCE)) {
        // Dispatch arrows change every tick (fade + robot position), always update
        _state.map.getSource(DISPATCH_ARROWS_SOURCE).setData(geojson);
        // Animate dash offset for marching-ant effect
        if (_state.map.getLayer(DISPATCH_ARROWS_LINE)) {
            _state.map.setPaintProperty(DISPATCH_ARROWS_LINE, 'line-dasharray',
                [4, 4]);
        }
    } else {
        _state.map.addSource(DISPATCH_ARROWS_SOURCE, {
            type: 'geojson',
            data: geojson,
        });

        _state.map.addLayer({
            id: DISPATCH_ARROWS_LINE,
            type: 'line',
            source: DISPATCH_ARROWS_SOURCE,
            layout: {
                'line-cap': 'round',
                'line-join': 'round',
            },
            paint: {
                'line-color': '#00f0ff',
                'line-width': 2,
                'line-opacity': ['get', 'opacity'],
                'line-dasharray': [4, 4],
            },
        });
    }
}

/**
 * Remove patrol route layers and source from the map.
 */
function _clearPatrolRoutes() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(PATROL_ROUTES_DOTS))
                _state.map.removeLayer(PATROL_ROUTES_DOTS);
            if (_state.map.getLayer(PATROL_ROUTES_LINE))
                _state.map.removeLayer(PATROL_ROUTES_LINE);
            if (_state.map.getSource(PATROL_ROUTES_SOURCE))
                _state.map.removeSource(PATROL_ROUTES_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

// ============================================================
// Weapon Range Circle Overlay (selected unit)
// ============================================================

/**
 * Draw a weapon range circle centered on the selected unit's position.
 * Fill color is alliance-based: cyan for friendly, magenta for hostile.
 * Only shown in tactical/setup modes when showWeaponRange is enabled.
 */
function _updateWeaponRange() {
    if (!_state.map || !_state.initialized) return;

    const selectedId = _state.selectedUnitId;
    const mode = _state.currentMode;

    // Show in all modes when a unit is selected and weapon range is enabled
    if (!_state.showWeaponRange || !selectedId) {
        _clearWeaponRange();
        return;
    }

    const unit = TritiumStore.units.get(selectedId);
    if (!unit || !unit.weaponRange || unit.weaponRange <= 0) {
        _clearWeaponRange();
        return;
    }

    const pos = unit.position || {};
    const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
    const circle = _makeCircleGeoJSON(lngLat, unit.weaponRange, 64);

    // Alliance-based colors
    const alliance = unit.alliance || 'unknown';
    const fillColor = alliance === 'hostile' ? '#ff2a6d' : '#00f0ff';
    const fillOpacity = 0.08;
    const strokeOpacity = 0.3;

    if (_state.map.getSource(WEAPON_RANGE_SOURCE)) {
        // Skip setData() if circle unchanged (same unit, position, range)
        const hash = `${selectedId}:${(pos.x||0).toFixed(1)},${(pos.y||0).toFixed(1)}:${unit.weaponRange}:${alliance}`;
        if (hash === _state._lastWeaponRangeHash) return;
        _state._lastWeaponRangeHash = hash;
        _state.map.getSource(WEAPON_RANGE_SOURCE).setData(circle);
    } else {
        _state.map.addSource(WEAPON_RANGE_SOURCE, {
            type: 'geojson',
            data: circle,
        });
        _state.map.addLayer({
            id: WEAPON_RANGE_FILL,
            type: 'fill',
            source: WEAPON_RANGE_SOURCE,
            paint: {
                'fill-color': fillColor,
                'fill-opacity': fillOpacity,
            },
        });
        _state.map.addLayer({
            id: WEAPON_RANGE_STROKE,
            type: 'line',
            source: WEAPON_RANGE_SOURCE,
            paint: {
                'line-color': fillColor,
                'line-width': 2,
                'line-opacity': strokeOpacity,
            },
        });
    }

    // Update paint properties if alliance changed (unit selection can switch between alliances)
    try {
        _state.map.setPaintProperty(WEAPON_RANGE_FILL, 'fill-color', fillColor);
        _state.map.setPaintProperty(WEAPON_RANGE_STROKE, 'line-color', fillColor);
    } catch (_e) { /* layer may not exist yet */ }
}

/**
 * Remove the weapon range circle overlay.
 */
function _clearWeaponRange() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(WEAPON_RANGE_FILL))
                _state.map.removeLayer(WEAPON_RANGE_FILL);
            if (_state.map.getLayer(WEAPON_RANGE_STROKE))
                _state.map.removeLayer(WEAPON_RANGE_STROKE);
            if (_state.map.getSource(WEAPON_RANGE_SOURCE))
                _state.map.removeSource(WEAPON_RANGE_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

// ============================================================
// Combat Zone Heatmap Overlay
// ============================================================

/**
 * Fetch heatmap data from the replay API and render as a MapLibre heatmap layer.
 * Called after each wave completes.
 */
async function _fetchAndRenderHeatmap() {
    if (!_state.map || !_state.initialized) return;

    try {
        const resp = await fetch('/api/game/replay/heatmap');
        if (!resp.ok) return;
        const data = await resp.json();

        // Build GeoJSON FeatureCollection from heatmap grid cells
        // data is { target_id: [ {x, y, count}, ... ] }
        const features = [];
        for (const [_tid, cells] of Object.entries(data)) {
            if (!Array.isArray(cells)) continue;
            for (const cell of cells) {
                const lngLat = _gameToLngLat(cell.x, cell.y);
                features.push({
                    type: 'Feature',
                    geometry: { type: 'Point', coordinates: lngLat },
                    properties: { weight: cell.count || 1 },
                });
            }
        }

        const geojson = { type: 'FeatureCollection', features };
        _renderHeatmap(geojson);
    } catch (e) {
        console.warn('[MAP-ML] Failed to fetch heatmap data:', e);
    }
}

/**
 * Render a GeoJSON FeatureCollection as a MapLibre heatmap layer.
 * @param {Object} geojson - GeoJSON FeatureCollection of Point features
 */
function _renderHeatmap(geojson) {
    if (!_state.map) return;

    if (_state.map.getSource(COMBAT_HEATMAP_SOURCE)) {
        _state.map.getSource(COMBAT_HEATMAP_SOURCE).setData(geojson);
    } else {
        _state.map.addSource(COMBAT_HEATMAP_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: COMBAT_HEATMAP_LAYER,
            type: 'heatmap',
            source: COMBAT_HEATMAP_SOURCE,
            layout: {
                'visibility': _state.showHeatmap ? 'visible' : 'none',
            },
            paint: {
                // Weight based on the count property
                'heatmap-weight': [
                    'interpolate', ['linear'], ['get', 'weight'],
                    0, 0,
                    10, 1,
                ],
                // Intensity scales with zoom
                'heatmap-intensity': [
                    'interpolate', ['linear'], ['zoom'],
                    10, 0.5,
                    18, 2,
                ],
                // Radius in pixels
                'heatmap-radius': [
                    'interpolate', ['linear'], ['zoom'],
                    10, 20,
                    18, 40,
                ],
                // Color gradient: transparent -> cyan -> magenta -> yellow
                'heatmap-color': [
                    'interpolate', ['linear'], ['heatmap-density'],
                    0, 'rgba(0,0,0,0)',
                    0.2, 'rgba(0,240,255,0.4)',
                    0.5, 'rgba(255,42,109,0.6)',
                    0.8, 'rgba(252,238,10,0.8)',
                    1.0, 'rgba(252,238,10,1.0)',
                ],
                'heatmap-opacity': 0.6,
            },
        });
    }
}

/**
 * Clear the combat zone heatmap overlay.
 */
function _clearHeatmap() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(COMBAT_HEATMAP_LAYER))
                _state.map.removeLayer(COMBAT_HEATMAP_LAYER);
            if (_state.map.getSource(COMBAT_HEATMAP_SOURCE))
                _state.map.removeSource(COMBAT_HEATMAP_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

// ============================================================
// Drone Swarm Convex Hull Overlay
// ============================================================

/**
 * Compute the convex hull of a set of 2D points using Graham scan.
 * @param {Array<number[]>} points - Array of [x, y] coordinate pairs
 * @returns {Array<number[]>} Convex hull vertices in counter-clockwise order
 */
function _convexHull(points) {
    if (points.length < 3) return points.slice();

    // Sort by x, then y
    const sorted = points.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);

    // Cross product of vectors OA and OB where O is origin
    function cross(O, A, B) {
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0]);
    }

    // Build lower hull
    const lower = [];
    for (const p of sorted) {
        while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0) {
            lower.pop();
        }
        lower.push(p);
    }

    // Build upper hull
    const upper = [];
    for (let i = sorted.length - 1; i >= 0; i--) {
        const p = sorted[i];
        while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0) {
            upper.pop();
        }
        upper.push(p);
    }

    // Remove last point of each half because it's repeated
    lower.pop();
    upper.pop();

    return lower.concat(upper);
}

/**
 * Update the drone swarm convex hull overlay.
 * Only active when game_mode_type is 'drone_swarm' and game is active.
 */
function _updateSwarmHull() {
    if (!_state.map || !_state.initialized) return;

    const modeType = TritiumStore.get('game.modeType');
    const phase = TritiumStore.get('game.phase');

    // Only show during active drone_swarm games
    if (!_state.showSwarmHull || modeType !== 'drone_swarm' || phase !== 'active') {
        _clearSwarmHull();
        return;
    }

    // Gather all hostile unit positions
    const hostilePoints = [];
    TritiumStore.units.forEach((unit) => {
        if (unit.alliance === 'hostile') {
            const pos = unit.position || {};
            const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
            hostilePoints.push(lngLat);
        }
    });

    if (hostilePoints.length < 3) {
        _clearSwarmHull();
        return;
    }

    // Compute convex hull
    const hull = _convexHull(hostilePoints);
    if (hull.length < 3) {
        _clearSwarmHull();
        return;
    }

    // Close the polygon ring
    const ring = hull.slice();
    ring.push(ring[0]);

    // Pulsing opacity: oscillate between 0.08 and 0.15
    const pulse = 0.08 + 0.07 * (0.5 + 0.5 * Math.sin(Date.now() / 500));

    const geojson = {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [ring] },
    };

    if (_state.map.getSource(SWARM_HULL_SOURCE)) {
        // Skip setData() if hull geometry unchanged
        const hash = ring.map(p => p[0].toFixed(6) + ',' + p[1].toFixed(6)).join(';');
        if (hash !== _state._lastSwarmHullHash) {
            _state._lastSwarmHullHash = hash;
            _state.map.getSource(SWARM_HULL_SOURCE).setData(geojson);
        }
        // Pulsing opacity always updates (cheap paint property, no re-parse)
        try {
            _state.map.setPaintProperty(SWARM_HULL_FILL, 'fill-opacity', pulse);
        } catch (_e) { /* layer may not exist yet */ }
    } else {
        _state.map.addSource(SWARM_HULL_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: SWARM_HULL_FILL,
            type: 'fill',
            source: SWARM_HULL_SOURCE,
            paint: {
                'fill-color': '#ff2a6d',
                'fill-opacity': pulse,
            },
        });
        _state.map.addLayer({
            id: SWARM_HULL_STROKE,
            type: 'line',
            source: SWARM_HULL_SOURCE,
            paint: {
                'line-color': '#ff2a6d',
                'line-width': 2,
                'line-opacity': 0.4,
            },
        });
    }
}

/**
 * Remove the swarm hull overlay.
 */
function _clearSwarmHull() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(SWARM_HULL_FILL))
                _state.map.removeLayer(SWARM_HULL_FILL);
            if (_state.map.getLayer(SWARM_HULL_STROKE))
                _state.map.removeLayer(SWARM_HULL_STROKE);
            if (_state.map.getSource(SWARM_HULL_SOURCE))
                _state.map.removeSource(SWARM_HULL_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

// ============================================================
// Squad Formation Hulls
// ============================================================

/**
 * Determine the squad hull color based on tactical order.
 * @param {string|undefined} order - tactical order (advance/hold/flank/retreat)
 * @returns {string} hex color
 */
function _squadColor(order) {
    return SQUAD_ORDER_COLORS[order] || SQUAD_DEFAULT_COLOR;
}

/**
 * Update squad formation convex hull overlays.
 * Groups hostile units by squadId, computes convex hulls for squads
 * with 3+ members, and renders them as GeoJSON polygons.
 * Called from the 10Hz _updateUnits() loop.
 */
function _updateSquadHulls() {
    if (!_state.map || !_state.initialized) return;

    const phase = TritiumStore.get('game.phase');
    if (!_state.showSquadHulls || (phase !== 'active' && phase !== 'countdown')) {
        _clearSquadHulls();
        return;
    }

    // Group units by squadId
    const squads = new Map(); // squadId -> [{ unit, lngLat }]
    TritiumStore.units.forEach((unit) => {
        if (!unit.squadId) return;
        const pos = unit.position || {};
        const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
        if (!squads.has(unit.squadId)) squads.set(unit.squadId, []);
        squads.get(unit.squadId).push({ unit, lngLat });
    });

    // Build GeoJSON features for squads with 3+ members
    const features = [];
    squads.forEach((members, squadId) => {
        if (members.length < 3) return;

        const points = members.map(m => m.lngLat);
        const hull = _convexHull(points);
        if (hull.length < 3) return;

        // Close the polygon ring
        const ring = hull.slice();
        ring.push(ring[0]);

        // Determine color from tactical order (use first member with a known order)
        let order = null;
        for (const m of members) {
            if (m.unit.tacticalOrder) { order = m.unit.tacticalOrder; break; }
        }
        const color = _squadColor(order);

        features.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [ring] },
            properties: { squadId, color, order: order || 'advance' },
        });
    });

    const geojson = { type: 'FeatureCollection', features };

    if (_state.map.getSource(SQUAD_HULL_SOURCE)) {
        // Skip setData() if squad hull features unchanged
        const hash = _hashGeoJSONFeatures(geojson);
        if (hash === _state._lastSquadHullHash) return;
        _state._lastSquadHullHash = hash;
        _state.map.getSource(SQUAD_HULL_SOURCE).setData(geojson);
    } else {
        _state.map.addSource(SQUAD_HULL_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: SQUAD_HULL_FILL,
            type: 'fill',
            source: SQUAD_HULL_SOURCE,
            paint: {
                'fill-color': ['get', 'color'],
                'fill-opacity': 0.12,
            },
        });
        _state.map.addLayer({
            id: SQUAD_HULL_STROKE,
            type: 'line',
            source: SQUAD_HULL_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 1.5,
                'line-opacity': 0.35,
            },
        });
    }
}

/**
 * Remove squad hull overlay layers and source.
 */
function _clearSquadHulls() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(SQUAD_HULL_FILL))
                _state.map.removeLayer(SQUAD_HULL_FILL);
            if (_state.map.getLayer(SQUAD_HULL_STROKE))
                _state.map.removeLayer(SQUAD_HULL_STROKE);
            if (_state.map.getSource(SQUAD_HULL_SOURCE))
                _state.map.removeSource(SQUAD_HULL_SOURCE);
        }
    } catch (_e) {
        // Layers may not exist yet
    }
}

// ============================================================
// Hazard Zones Overlay (fire/flood/roadblock)
// ============================================================

/**
 * Update environmental hazard zone overlay.
 * Reads hazard data from TritiumStore 'hazards' (Map).
 * Each hazard: { hazard_id, hazard_type, position, radius, duration, spawned_at }
 * Renders as GeoJSON circle polygons with type-based coloring.
 */
function _updateHazardZones() {
    if (!_state.map || !_state.initialized) return;

    if (!_state.showHazardZones) {
        _clearHazardZones();
        return;
    }

    const hazards = TritiumStore.get('hazards');
    if (!hazards || !(hazards instanceof Map) || hazards.size === 0) {
        _clearHazardZones();
        return;
    }

    const now = Date.now();
    const features = [];

    for (const [id, h] of hazards) {
        const pos = h.position;
        if (!pos) continue;
        const px = Array.isArray(pos) ? pos[0] : (pos.x !== undefined ? pos.x : undefined);
        const py = Array.isArray(pos) ? pos[1] : (pos.y !== undefined ? pos.y : undefined);
        if (px === undefined || py === undefined) continue;

        // Calculate remaining time fraction (1.0 = just spawned, 0.0 = expired)
        const totalMs = (h.duration || 60) * 1000;
        const elapsed = now - (h.spawned_at || now);
        const remaining = Math.max(0, Math.min(1, 1 - elapsed / totalMs));
        if (remaining <= 0) continue;

        const lngLat = _gameToLngLat(px, py);
        const radius = h.radius || 10;
        const color = HAZARD_COLORS[h.hazard_type] || '#ffffff';

        // Build circle polygon
        const circle = _makeCircleGeoJSON(lngLat, radius, 32);
        features.push({
            type: 'Feature',
            geometry: circle.geometry,
            properties: {
                hazard_id: id,
                hazard_type: h.hazard_type || 'unknown',
                color: color,
                opacity: 0.25 * remaining,
                stroke_opacity: 0.5 * remaining,
                label: (h.hazard_type || 'HAZARD').toUpperCase(),
            },
        });
    }

    if (features.length === 0) {
        _clearHazardZones();
        return;
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.map(f => f.properties.hazard_id + ':' + f.properties.opacity.toFixed(2)).join(';');

    if (_state.map.getSource(HAZARD_ZONES_SOURCE)) {
        if (hash !== _state._lastHazardHash) {
            _state._lastHazardHash = hash;
            _state.map.getSource(HAZARD_ZONES_SOURCE).setData(geojson);
        }
    } else {
        _state.map.addSource(HAZARD_ZONES_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: HAZARD_ZONES_FILL,
            type: 'fill',
            source: HAZARD_ZONES_SOURCE,
            paint: {
                'fill-color': ['get', 'color'],
                'fill-opacity': ['get', 'opacity'],
            },
        });
        _state.map.addLayer({
            id: HAZARD_ZONES_STROKE,
            type: 'line',
            source: HAZARD_ZONES_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 2,
                'line-opacity': ['get', 'stroke_opacity'],
                'line-dasharray': [4, 3],
            },
        });
    }
}

function _clearHazardZones() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(HAZARD_ZONES_FILL))
                _state.map.removeLayer(HAZARD_ZONES_FILL);
            if (_state.map.getLayer(HAZARD_ZONES_STROKE))
                _state.map.removeLayer(HAZARD_ZONES_STROKE);
            if (_state.map.getSource(HAZARD_ZONES_SOURCE))
                _state.map.removeSource(HAZARD_ZONES_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
    _state._lastHazardHash = null;
}

// ============================================================
// Geofence Zone Overlay (polygon zones + occupancy labels)
// ============================================================

const GEOFENCE_ZONES_SOURCE = 'geofence-zones-source';
const GEOFENCE_ZONES_FILL   = 'geofence-zones-fill';
const GEOFENCE_ZONES_STROKE = 'geofence-zones-stroke';
const GEOFENCE_ZONES_LABEL  = 'geofence-zones-label';
const GEOFENCE_LABEL_SOURCE = 'geofence-label-source';
const GEOFENCE_ALERT_SOURCE = 'geofence-alert-source';
const GEOFENCE_ALERT_BADGE  = 'geofence-alert-badge';

const GEOFENCE_ZONE_COLORS = {
    restricted: { fill: 'rgba(255,42,109,0.35)', stroke: '#ff2a6d' },
    monitored:  { fill: 'rgba(0,240,255,0.28)',  stroke: '#00f0ff' },
    safe:       { fill: 'rgba(5,255,161,0.25)',   stroke: '#05ffa1' },
};

// Geofence zone pulse animation state
let _geofencePulseRAF = null;
let _geofenceHasActiveZones = false;
let _geofenceHasMonitoringZones = false;

/**
 * Animate pulse effect on geofence zones.
 * - Monitoring zones (alert_on_enter/exit but no occupants): slow subtle cyan pulse on border
 * - Active zones (occupants inside): faster, stronger pulse on fill + border
 * Both states use sine wave oscillation for smooth animation.
 */
function _geofencePulseLoop() {
    if (!_state.map || !_state.initialized || (!_geofenceHasActiveZones && !_geofenceHasMonitoringZones)) {
        _geofencePulseRAF = null;
        return;
    }
    const t = Date.now() / 1000;

    // Active zones (occupants inside): fast strong pulse ~0.4Hz
    const sinActive = Math.sin(t * 2.5);
    const activeFillOpacity = 0.5 + 0.25 * sinActive;
    const activeLineWidth   = 3.5 + 1.5 * sinActive;
    const activeStrokeOp    = 0.7 + 0.3 * sinActive;

    // Monitoring zones (armed, no occupants): slow subtle pulse ~0.2Hz
    const sinMonitor = Math.sin(t * 1.2);
    const monitorLineWidth  = 2.5 + 0.8 * sinMonitor;   // 1.7 .. 3.3
    const monitorStrokeOp   = 0.5 + 0.2 * sinMonitor;   // 0.3 .. 0.7
    const monitorFillOp     = 0.15 + 0.05 * sinMonitor;  // 0.10 .. 0.20

    try {
        if (_state.map.getLayer(GEOFENCE_ZONES_FILL)) {
            _state.map.setPaintProperty(GEOFENCE_ZONES_FILL, 'fill-opacity', [
                'case',
                ['get', 'is_active'], activeFillOpacity,
                ['get', 'is_monitoring'], monitorFillOp,
                0.15
            ]);
        }
        if (_state.map.getLayer(GEOFENCE_ZONES_STROKE)) {
            _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-width', [
                'case',
                ['get', 'is_active'], activeLineWidth,
                ['get', 'is_monitoring'], monitorLineWidth,
                2
            ]);
            _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-opacity', [
                'case',
                ['get', 'is_active'], activeStrokeOp,
                ['get', 'is_monitoring'], monitorStrokeOp,
                0.6
            ]);
        }
        // Pulse the alert badge opacity
        if (_state.map.getLayer(GEOFENCE_ALERT_BADGE)) {
            const badgeOpacity = 0.7 + 0.3 * sinActive;
            _state.map.setPaintProperty(GEOFENCE_ALERT_BADGE, 'text-opacity', badgeOpacity);
        }
    } catch (_e) { /* layer may have been removed */ }

    _geofencePulseRAF = requestAnimationFrame(_geofencePulseLoop);
}

function _startGeofencePulse() {
    if (!_geofencePulseRAF) {
        _geofencePulseRAF = requestAnimationFrame(_geofencePulseLoop);
    }
}

function _stopGeofencePulse() {
    if (_geofencePulseRAF) {
        cancelAnimationFrame(_geofencePulseRAF);
        _geofencePulseRAF = null;
    }
}

/**
 * Fetch geofence zones + occupancy and render on the MapLibre map.
 * Called on slow tick (~1Hz).
 */
function _updateGeofenceZones() {
    if (!_state.map || !_state.initialized) return;
    if (!_state.showGeofenceZones) {
        _clearGeofenceZones();
        return;
    }

    // Use cached data, refresh periodically
    if (!_state._geofenceZones) _state._geofenceZones = [];
    if (!_state._geofenceOccupancy) _state._geofenceOccupancy = {};

    const now = Date.now();
    if (!_state._lastGeofenceFetch || now - _state._lastGeofenceFetch > 10000) {
        _state._lastGeofenceFetch = now;
        fetch('/api/geofence/zones')
            .then(r => r.ok ? r.json() : [])
            .then(data => {
                if (Array.isArray(data)) _state._geofenceZones = data;
                _renderGeofenceZones();
            })
            .catch(() => {});
        fetch('/api/geofence/occupancy')
            .then(r => r.ok ? r.json() : {})
            .then(data => {
                if (data && typeof data === 'object') _state._geofenceOccupancy = data;
                _renderGeofenceZones();
            })
            .catch(() => {});
    }
}

function _renderGeofenceZones() {
    if (!_state.map || !_state.initialized) return;
    const zones = _state._geofenceZones || [];
    const occupancy = _state._geofenceOccupancy || {};

    if (zones.length === 0) {
        _clearGeofenceZones();
        return;
    }

    console.log(`[MAP-ML] Rendering ${zones.length} geofence zone(s)`);

    const features = [];
    const labelFeatures = [];
    const alertFeatures = [];
    let hasAnyActive = false;

    for (const zone of zones) {
        const pts = zone.polygon;
        if (!pts || pts.length < 3) continue;

        const colors = GEOFENCE_ZONE_COLORS[zone.zone_type] || GEOFENCE_ZONE_COLORS.monitored;

        // Convert game coords to [lng, lat] ring
        const ring = pts.map(p => {
            const ll = _gameToLngLat(p[0], p[1]);
            return [ll[0], ll[1]];
        });
        // Close the ring
        if (ring.length > 0) ring.push(ring[0]);

        const occ = occupancy[zone.zone_id] || 0;
        const isActive = occ > 0;
        const isMonitoring = !!(zone.alert_on_enter || zone.alert_on_exit);

        features.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [ring] },
            properties: {
                zone_id: zone.zone_id,
                fill_color: colors.fill,
                stroke_color: colors.stroke,
                is_active: isActive,
                is_monitoring: isMonitoring && !isActive,
            },
        });

        // Centroid for label
        const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
        const ll = _gameToLngLat(cx, cy);
        const label = isActive
            ? `${zone.name.toUpperCase()}\n${occ} INSIDE`
            : isMonitoring
            ? `${zone.name.toUpperCase()}\nMONITORING`
            : zone.name.toUpperCase();

        labelFeatures.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [ll[0], ll[1]] },
            properties: {
                label: label,
                color: colors.stroke,
                zone_type: zone.zone_type.toUpperCase(),
            },
        });

        // Alert badge for active zones
        if (isActive) {
            hasAnyActive = true;
            alertFeatures.push({
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [ll[0], ll[1]] },
                properties: {
                    badge_text: '\u26A0 ALERT',
                    badge_color: zone.zone_type === 'restricted' ? '#ff2a6d' : '#fcee0a',
                },
            });
        }
    }

    const geojson = { type: 'FeatureCollection', features };
    const labelGeojson = { type: 'FeatureCollection', features: labelFeatures };

    if (_state.map.getSource(GEOFENCE_ZONES_SOURCE)) {
        _state.map.getSource(GEOFENCE_ZONES_SOURCE).setData(geojson);
    } else {
        _state.map.addSource(GEOFENCE_ZONES_SOURCE, { type: 'geojson', data: geojson });
        _state.map.addLayer({
            id: GEOFENCE_ZONES_FILL,
            type: 'fill',
            source: GEOFENCE_ZONES_SOURCE,
            paint: {
                'fill-color': ['get', 'fill_color'],
                'fill-opacity': 0.6,
            },
        });
        _state.map.addLayer({
            id: GEOFENCE_ZONES_STROKE,
            type: 'line',
            source: GEOFENCE_ZONES_SOURCE,
            paint: {
                'line-color': ['get', 'stroke_color'],
                'line-width': 3,
                'line-dasharray': [6, 4],
            },
        });
    }

    try {
        if (_state.map.getSource(GEOFENCE_LABEL_SOURCE)) {
            _state.map.getSource(GEOFENCE_LABEL_SOURCE).setData(labelGeojson);
        } else {
            _state.map.addSource(GEOFENCE_LABEL_SOURCE, { type: 'geojson', data: labelGeojson });
            _state.map.addLayer({
                id: GEOFENCE_ZONES_LABEL,
                type: 'symbol',
                source: GEOFENCE_LABEL_SOURCE,
                layout: {
                    'text-field': ['get', 'label'],
                    'text-font': ['Open Sans Semibold'],
                    'text-size': 11,
                    'text-anchor': 'center',
                    'text-allow-overlap': true,
                },
                paint: {
                    'text-color': ['get', 'color'],
                    'text-halo-color': 'rgba(10,10,20,0.8)',
                    'text-halo-width': 1.5,
                },
            });
        }
    } catch (_labelErr) {
        // Symbol layer can fail if fonts unavailable — fill/stroke still render
        console.warn('[MAP-ML] Geofence label layer failed:', _labelErr.message);
    }

    // Alert badge layer — warning icon at centroid of active zones
    const alertGeojson = { type: 'FeatureCollection', features: alertFeatures };
    try {
        if (_state.map.getSource(GEOFENCE_ALERT_SOURCE)) {
            _state.map.getSource(GEOFENCE_ALERT_SOURCE).setData(alertGeojson);
        } else {
            _state.map.addSource(GEOFENCE_ALERT_SOURCE, { type: 'geojson', data: alertGeojson });
            _state.map.addLayer({
                id: GEOFENCE_ALERT_BADGE,
                type: 'symbol',
                source: GEOFENCE_ALERT_SOURCE,
                layout: {
                    'text-field': ['get', 'badge_text'],
                    'text-font': ['Open Sans Semibold'],
                    'text-size': 13,
                    'text-anchor': 'top',
                    'text-offset': [0, 1.2],
                    'text-allow-overlap': true,
                },
                paint: {
                    'text-color': ['get', 'badge_color'],
                    'text-halo-color': 'rgba(10,10,20,0.9)',
                    'text-halo-width': 2,
                },
            });
        }
    } catch (_alertErr) {
        console.warn('[MAP-ML] Geofence alert badge layer failed:', _alertErr.message);
    }

    // Check if any zone is monitoring (armed with alert_on_enter/exit)
    const hasAnyMonitoring = zones.some(z => (z.alert_on_enter || z.alert_on_exit) && !(occupancy[z.zone_id] > 0));

    // Manage pulse animation based on active/monitoring zone state
    _geofenceHasActiveZones = hasAnyActive;
    _geofenceHasMonitoringZones = hasAnyMonitoring;
    if (hasAnyActive || hasAnyMonitoring) {
        _startGeofencePulse();
    } else {
        _stopGeofencePulse();
        // Reset paint properties to defaults when no zones need animation
        try {
            if (_state.map.getLayer(GEOFENCE_ZONES_FILL)) {
                _state.map.setPaintProperty(GEOFENCE_ZONES_FILL, 'fill-opacity', 0.15);
            }
            if (_state.map.getLayer(GEOFENCE_ZONES_STROKE)) {
                _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-width', 2);
                _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-opacity', 0.6);
            }
        } catch (_e) { /* ok */ }
    }
}

/**
 * Briefly flash geofence zone borders in magenta when a target enters.
 * Temporarily overrides stroke color to magenta, then restores after 800ms.
 */
function _flashGeofenceAlert(_data) {
    if (!_state.map || !_state.initialized) return;
    try {
        if (!_state.map.getLayer(GEOFENCE_ZONES_STROKE)) return;
        // Flash all zone strokes to magenta
        _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-color', '#ff2a6d');
        _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-width', 5);
        // Restore after 800ms
        setTimeout(() => {
            try {
                if (_state.map && _state.map.getLayer(GEOFENCE_ZONES_STROKE)) {
                    _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-color', ['get', 'stroke_color']);
                    // Width will be restored by the pulse loop or default
                    if (!_geofenceHasActiveZones && !_geofenceHasMonitoringZones) {
                        _state.map.setPaintProperty(GEOFENCE_ZONES_STROKE, 'line-width', 2);
                    }
                }
            } catch (_e) { /* ok */ }
        }, 800);
    } catch (_e) { /* ok */ }
}

function _clearGeofenceZones() {
    _stopGeofencePulse();
    _geofenceHasActiveZones = false;
    _geofenceHasMonitoringZones = false;
    try {
        if (_state.map) {
            if (_state.map.getLayer(GEOFENCE_ALERT_BADGE))
                _state.map.removeLayer(GEOFENCE_ALERT_BADGE);
            if (_state.map.getLayer(GEOFENCE_ZONES_LABEL))
                _state.map.removeLayer(GEOFENCE_ZONES_LABEL);
            if (_state.map.getLayer(GEOFENCE_ZONES_FILL))
                _state.map.removeLayer(GEOFENCE_ZONES_FILL);
            if (_state.map.getLayer(GEOFENCE_ZONES_STROKE))
                _state.map.removeLayer(GEOFENCE_ZONES_STROKE);
            if (_state.map.getSource(GEOFENCE_ALERT_SOURCE))
                _state.map.removeSource(GEOFENCE_ALERT_SOURCE);
            if (_state.map.getSource(GEOFENCE_ZONES_SOURCE))
                _state.map.removeSource(GEOFENCE_ZONES_SOURCE);
            if (_state.map.getSource(GEOFENCE_LABEL_SOURCE))
                _state.map.removeSource(GEOFENCE_LABEL_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
}

// ============================================================
// Hostile Objective Lines Overlay
// ============================================================

/**
 * Draw dashed lines from hostile units to their assigned objective targets.
 * Only renders when the game is active.
 * Reads objective data from TritiumStore 'game.hostileObjectives'.
 *
 * Color per objective type:
 *   assault -> #ff2a6d (magenta)
 *   flank   -> #ff8800 (orange)
 *   advance -> #fcee0a (yellow)
 *   retreat -> #888888 (grey)
 */
function _updateHostileObjectives() {
    if (!_state.map || !_state.initialized) return;

    const phase = TritiumStore.get('game.phase');
    if (!_state.showHostileObjectives || phase !== 'active') {
        _clearHostileObjectives();
        return;
    }

    const objectives = TritiumStore.get('game.hostileObjectives');
    if (!objectives || typeof objectives !== 'object') {
        _clearHostileObjectives();
        return;
    }

    const units = TritiumStore.units;
    const features = [];
    const OBJ_COLORS = {
        assault: '#ff2a6d',
        flank:   '#ff8800',
        advance: '#fcee0a',
        retreat: '#888888',
    };

    for (const [uid, obj] of Object.entries(objectives)) {
        const unit = units.get(uid);
        if (!unit || !unit.position) continue;

        const tp = obj.target_position;
        if (!tp || !Array.isArray(tp) || tp.length < 2) continue;

        const fromLngLat = _gameToLngLat(unit.position.x, unit.position.y);
        const toLngLat = _gameToLngLat(tp[0], tp[1]);
        const color = OBJ_COLORS[obj.type] || '#ff2a6d';

        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [fromLngLat, toLngLat],
            },
            properties: { color, type: obj.type || 'assault' },
        });
    }

    if (features.length === 0) {
        _clearHostileObjectives();
        return;
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.map(f => f.geometry.coordinates.flat().map(c => c.toFixed(5)).join(',')).join(';');

    if (_state.map.getSource(HOSTILE_OBJ_SOURCE)) {
        if (hash !== _state._lastHostileObjHash) {
            _state._lastHostileObjHash = hash;
            _state.map.getSource(HOSTILE_OBJ_SOURCE).setData(geojson);
        }
    } else {
        _state.map.addSource(HOSTILE_OBJ_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: HOSTILE_OBJ_LINE,
            type: 'line',
            source: HOSTILE_OBJ_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 1.5,
                'line-opacity': 0.4,
                'line-dasharray': [6, 4],
            },
        });
    }
}

function _clearHostileObjectives() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(HOSTILE_OBJ_LINE))
                _state.map.removeLayer(HOSTILE_OBJ_LINE);
            if (_state.map.getSource(HOSTILE_OBJ_SOURCE))
                _state.map.removeSource(HOSTILE_OBJ_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
    _state._lastHostileObjHash = null;
}

/**
 * Start polling /api/game/hostile-intel every 5 seconds.
 * Stores the objectives in TritiumStore 'game.hostileObjectives'.
 */
function _startHostileObjectivePoll() {
    if (_state._hostileObjPollTimer) return;
    _state._hostileObjPollTimer = setInterval(async () => {
        const phase = TritiumStore.get('game.phase');
        if (phase !== 'active') {
            _stopHostileObjectivePoll();
            return;
        }
        try {
            const resp = await fetch('/api/game/hostile-intel');
            if (resp.ok) {
                const data = await resp.json();
                if (data && data.objectives) {
                    TritiumStore.set('game.hostileObjectives', data.objectives);
                }
            }
        } catch (_e) { /* silently ignore fetch errors */ }
    }, 5000);
}

function _stopHostileObjectivePoll() {
    if (_state._hostileObjPollTimer) {
        clearInterval(_state._hostileObjPollTimer);
        _state._hostileObjPollTimer = null;
    }
    TritiumStore.set('game.hostileObjectives', null);
}

// ============================================================
// Crowd Density Heatmap Overlay (civil_unrest mode)
// ============================================================

/**
 * Update crowd density heatmap overlay.
 * Only active when game_mode_type is 'civil_unrest'.
 *
 * Reads grid data from TritiumStore 'game.crowdDensity':
 *   { grid: [[str,...]], cell_size, bounds: [xMin,yMin,xMax,yMax],
 *     max_density, critical_count }
 *
 * Density levels map to GeoJSON polygons:
 *   sparse   -> invisible (skip)
 *   moderate -> pale yellow (#fcee0a) at 0.20 opacity
 *   dense    -> orange (#ff8c00) at 0.40 opacity
 *   critical -> red (#ff2a32) at 0.55 opacity
 */
function _updateCrowdDensity() {
    if (!_state.map || !_state.initialized) return;

    const modeType = TritiumStore.get('game.modeType');
    if (!_state.showCrowdDensity || modeType !== 'civil_unrest') {
        _clearCrowdDensity();
        return;
    }

    const data = TritiumStore.get('game.crowdDensity');
    if (!data || !data.grid) {
        _clearCrowdDensity();
        return;
    }

    const grid = data.grid;
    if (!Array.isArray(grid) || grid.length === 0) {
        _clearCrowdDensity();
        return;
    }

    const cellSize = data.cell_size || 10;
    const bounds = data.bounds || [0, 0, 0, 0];
    const xMin = bounds[0];
    const yMin = bounds[1];
    const features = [];

    const DENSITY_COLORS = {
        moderate: '#fcee0a',
        dense:    '#ff8c00',
        critical: '#ff2a32',
    };
    const DENSITY_OPACITY = {
        moderate: 0.20,
        dense:    0.40,
        critical: 0.55,
    };

    for (let row = 0; row < grid.length; row++) {
        const cols = grid[row];
        if (!Array.isArray(cols)) continue;
        for (let col = 0; col < cols.length; col++) {
            const level = cols[col];
            if (level === 'sparse' || !level) continue;
            if (!DENSITY_COLORS[level]) continue;

            const wx = xMin + col * cellSize;
            const wy = yMin + row * cellSize;

            // Cell corners in lng/lat
            const sw = _gameToLngLat(wx, wy);
            const ne = _gameToLngLat(wx + cellSize, wy + cellSize);

            features.push({
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [[
                        [sw[0], sw[1]],
                        [ne[0], sw[1]],
                        [ne[0], ne[1]],
                        [sw[0], ne[1]],
                        [sw[0], sw[1]],
                    ]],
                },
                properties: {
                    level,
                    color: DENSITY_COLORS[level],
                    opacity: DENSITY_OPACITY[level],
                },
            });
        }
    }

    if (features.length === 0) {
        _clearCrowdDensity();
        return;
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.length + ':' + (data.max_density || '') + ':' + (data.critical_count || 0);

    if (_state.map.getSource(CROWD_DENSITY_SOURCE)) {
        if (hash !== _state._lastCrowdDensityHash) {
            _state._lastCrowdDensityHash = hash;
            _state.map.getSource(CROWD_DENSITY_SOURCE).setData(geojson);
        }
    } else {
        _state.map.addSource(CROWD_DENSITY_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: CROWD_DENSITY_FILL,
            type: 'fill',
            source: CROWD_DENSITY_SOURCE,
            paint: {
                'fill-color': ['get', 'color'],
                'fill-opacity': ['get', 'opacity'],
            },
        });
    }
}

function _clearCrowdDensity() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(CROWD_DENSITY_FILL))
                _state.map.removeLayer(CROWD_DENSITY_FILL);
            if (_state.map.getSource(CROWD_DENSITY_SOURCE))
                _state.map.removeSource(CROWD_DENSITY_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
    _state._lastCrowdDensityHash = null;
}

// ============================================================
// Cover Points Overlay
// ============================================================

/**
 * Update cover point markers on the map.
 * Reads from TritiumStore 'game.coverPoints' (array of cover point objects).
 * Each: { position: [x, y], radius, direction, reduction }
 * Renders as small cyan circles with shield-chevron icons.
 */
function _updateCoverPoints() {
    if (!_state.map || !_state.initialized) return;

    if (!_state.showCoverPoints) {
        _clearCoverPoints();
        return;
    }

    const points = TritiumStore.get('game.coverPoints');
    if (!Array.isArray(points) || points.length === 0) {
        _clearCoverPoints();
        return;
    }

    const features = [];
    for (const cp of points) {
        if (!cp.position || !Array.isArray(cp.position)) continue;
        const lngLat = _gameToLngLat(cp.position[0], cp.position[1]);
        features.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: lngLat },
            properties: {
                radius: cp.radius || 2,
                reduction: cp.reduction || 0,
            },
        });
    }

    if (features.length === 0) {
        _clearCoverPoints();
        return;
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.length + ':' + features[0].geometry.coordinates.join(',');

    if (_state.map.getSource(COVER_POINTS_SOURCE)) {
        if (hash !== _state._lastCoverPointsHash) {
            _state._lastCoverPointsHash = hash;
            _state.map.getSource(COVER_POINTS_SOURCE).setData(geojson);
        }
    } else {
        _state.map.addSource(COVER_POINTS_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: COVER_POINTS_CIRCLE,
            type: 'circle',
            source: COVER_POINTS_SOURCE,
            paint: {
                'circle-radius': [
                    'interpolate', ['linear'], ['zoom'],
                    14, 3,
                    18, 8,
                    20, 14,
                ],
                'circle-color': '#00f0ff',
                'circle-opacity': 0.15,
                'circle-stroke-color': '#00f0ff',
                'circle-stroke-width': 1,
                'circle-stroke-opacity': 0.35,
            },
        });
    }
}

function _clearCoverPoints() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(COVER_POINTS_CIRCLE))
                _state.map.removeLayer(COVER_POINTS_CIRCLE);
            if (_state.map.getSource(COVER_POINTS_SOURCE))
                _state.map.removeSource(COVER_POINTS_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
    _state._lastCoverPointsHash = null;
}

// ============================================================
// Unit Signals Overlay (distress/contact/regroup/retreat)
// ============================================================

/**
 * Update unit communication signal indicators.
 * Reads from TritiumStore 'game.signals' (array).
 * Each signal: { signal_type, sender_id, position, signal_range, ttl, received_at }
 * Renders as expanding circle rings that fade as they age.
 */
function _updateUnitSignals() {
    if (!_state.map || !_state.initialized) return;

    if (!_state.showUnitSignals) {
        _clearUnitSignals();
        return;
    }

    let signals = TritiumStore.get('game.signals');
    if (!Array.isArray(signals) || signals.length === 0) {
        _clearUnitSignals();
        return;
    }

    const now = Date.now();
    // Remove expired signals
    signals = signals.filter(s => now - s.received_at < (s.ttl || 10) * 1000);
    TritiumStore.set('game.signals', signals);

    if (signals.length === 0) {
        _clearUnitSignals();
        return;
    }

    const features = [];
    for (const sig of signals) {
        const pos = sig.position;
        if (!pos) continue;
        const px = Array.isArray(pos) ? pos[0] : pos.x;
        const py = Array.isArray(pos) ? pos[1] : pos.y;
        if (px === undefined || py === undefined) continue;

        const lngLat = _gameToLngLat(px, py);
        const color = SIGNAL_COLORS[sig.signal_type] || '#ffffff';
        const elapsed = (now - sig.received_at) / 1000;
        const ttl = sig.ttl || 10;
        const frac = Math.max(0, 1 - elapsed / ttl);
        const expansion = 1 - frac;
        const radiusMeters = (sig.signal_range || 50) * expansion;

        if (radiusMeters < 2) continue;

        const circle = _makeCircleGeoJSON(lngLat, radiusMeters, 24);
        features.push({
            type: 'Feature',
            geometry: circle.geometry,
            properties: {
                signal_type: sig.signal_type,
                color: color,
                opacity: frac * 0.35,
                stroke_opacity: frac * 0.6,
                label: sig.signal_type.toUpperCase(),
            },
        });
    }

    if (features.length === 0) {
        _clearUnitSignals();
        return;
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.map(f => f.properties.signal_type + ':' + f.properties.opacity.toFixed(2)).join(';');

    if (_state.map.getSource(UNIT_SIGNALS_SOURCE)) {
        if (hash !== _state._lastSignalsHash) {
            _state._lastSignalsHash = hash;
            _state.map.getSource(UNIT_SIGNALS_SOURCE).setData(geojson);
        }
    } else {
        _state.map.addSource(UNIT_SIGNALS_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: UNIT_SIGNALS_CIRCLE,
            type: 'line',
            source: UNIT_SIGNALS_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 2,
                'line-opacity': ['get', 'stroke_opacity'],
                'line-dasharray': [4, 4],
            },
        });
    }
}

function _clearUnitSignals() {
    try {
        if (_state.map) {
            if (_state.map.getLayer(UNIT_SIGNALS_CIRCLE))
                _state.map.removeLayer(UNIT_SIGNALS_CIRCLE);
            if (_state.map.getSource(UNIT_SIGNALS_SOURCE))
                _state.map.removeSource(UNIT_SIGNALS_SOURCE);
        }
    } catch (_e) { /* layers may not exist */ }
    _state._lastSignalsHash = null;
}

/**
 * Draw dashed engagement lines between units actively firing and their targets.
 * Uses the recentlyFired tracker populated by _onCombatProjectile().
 * Lines persist for 3s after last shot — much more visible in screenshots than
 * fast Three.js tracers (350-700ms).
 */
function _updateEngagementLines() {
    if (!_state.map || !_state.initialized) return;

    const now = performance.now();
    const features = [];

    for (const [srcId, entry] of Object.entries(_state.recentlyFired)) {
        if (now - entry.time > 3000) continue; // expired
        if (!entry.targetId) continue;

        const src = TritiumStore.units.get(srcId);
        const tgt = TritiumStore.units.get(entry.targetId);
        if (!src?.position || !tgt?.position) continue;

        const srcLL = _gameToLngLat(src.position.x || 0, src.position.y || 0);
        const tgtLL = _gameToLngLat(tgt.position.x || 0, tgt.position.y || 0);

        const alliance = src.alliance || 'unknown';
        const color = alliance === 'friendly' ? '#05ffa1' : alliance === 'hostile' ? '#ff2a6d' : '#ffa500';
        const age = now - entry.time;
        const opacity = Math.max(0.15, 0.6 * (1 - age / 3000));

        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [srcLL, tgtLL],
            },
            properties: { color, opacity: parseFloat(opacity.toFixed(2)) },
        });
    }

    const geojson = { type: 'FeatureCollection', features };
    const hash = features.map(f =>
        f.geometry.coordinates[0][0].toFixed(5) + ',' + f.properties.opacity
    ).join(';');

    if (_state.map.getSource(ENGAGEMENT_LINES_SOURCE)) {
        if (hash !== _state._lastEngagementHash) {
            _state._lastEngagementHash = hash;
            _state.map.getSource(ENGAGEMENT_LINES_SOURCE).setData(geojson);
        }
    } else {
        _state._lastEngagementHash = hash;
        _state.map.addSource(ENGAGEMENT_LINES_SOURCE, {
            type: 'geojson',
            data: geojson,
        });
        _state.map.addLayer({
            id: ENGAGEMENT_LINES_LAYER,
            type: 'line',
            source: ENGAGEMENT_LINES_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 2,
                'line-opacity': ['get', 'opacity'],
                'line-dasharray': [6, 4],
            },
        });
    }
}

// ============================================================
// Target Movement Trail Overlay (GeoJSON polyline from dossier)
// ============================================================

const TARGET_TRAIL_SOURCE = 'target-trail-source';
const TARGET_TRAIL_LINE   = 'target-trail-line';
const TARGET_TRAIL_DOTS   = 'target-trail-dots';

// State for currently displayed trail
const _trailState = {
    targetId: null,
    points: [],
    alliance: 'unknown',
};

const ALLIANCE_TRAIL_COLORS = {
    friendly: '#05ffa1',
    hostile: '#ff2a6d',
    unknown: '#00f0ff',
};

/**
 * Show a target's movement trail on the map.
 * Fetches trail from /api/targets/{id}/trail and draws a GeoJSON polyline.
 * Emitted by dossier panel "SHOW TRAIL ON MAP" button.
 * @param {Object} data - { targetId, alliance?, positions? }
 */
async function _onShowTargetTrail(data) {
    if (!_state.map || !_state.initialized || !data || !data.targetId) return;

    _trailState.targetId = data.targetId;
    _trailState.alliance = data.alliance || 'unknown';

    // Use provided positions (from dossier) or fetch from API
    let trail = data.positions || [];
    if (trail.length === 0) {
        try {
            const resp = await fetch(`/api/targets/${encodeURIComponent(data.targetId)}/trail?max_points=500`);
            if (resp.ok) {
                const result = await resp.json();
                trail = result.trail || [];
            }
        } catch (_) { /* trail API unavailable */ }
    }

    if (trail.length === 0) {
        console.log('[MAP-ML] No trail data for', data.targetId);
        return;
    }

    _trailState.points = trail;
    const lineColor = ALLIANCE_TRAIL_COLORS[_trailState.alliance] || '#00f0ff';

    // Sort by timestamp
    const sorted = [...trail].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));

    // Build GeoJSON LineString with per-segment opacity (newer = more opaque)
    const lineCoords = [];
    const dotFeatures = [];

    for (let i = 0; i < sorted.length; i++) {
        const pt = sorted[i];
        const gx = pt.x ?? pt.lng ?? 0;
        const gy = pt.y ?? pt.lat ?? 0;
        let lngLat;

        // If lat/lng provided directly, use them; otherwise convert from game coords
        if (pt.lat != null && pt.lng != null) {
            lngLat = [pt.lng, pt.lat];
        } else {
            lngLat = _gameToLngLat(gx, gy);
        }

        lineCoords.push(lngLat);

        // Dot opacity fades with age (index 0 = oldest, last = newest)
        const alpha = 0.2 + 0.8 * (i / Math.max(1, sorted.length - 1));
        const isLast = i === sorted.length - 1;

        dotFeatures.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: lngLat },
            properties: {
                opacity: alpha,
                radius: isLast ? 6 : 3,
                color: lineColor,
                isLatest: isLast ? 1 : 0,
            },
        });
    }

    // Line feature with gradient-like segments
    const lineFeature = {
        type: 'Feature',
        geometry: { type: 'LineString', coordinates: lineCoords },
        properties: { color: lineColor },
    };

    const lineGeojson = { type: 'FeatureCollection', features: [lineFeature] };
    const dotGeojson = { type: 'FeatureCollection', features: dotFeatures };

    // Update or create the trail line layer
    if (_state.map.getSource(TARGET_TRAIL_SOURCE)) {
        _state.map.getSource(TARGET_TRAIL_SOURCE).setData(lineGeojson);
    } else {
        _state.map.addSource(TARGET_TRAIL_SOURCE, { type: 'geojson', data: lineGeojson });
        _state.map.addLayer({
            id: TARGET_TRAIL_LINE,
            type: 'line',
            source: TARGET_TRAIL_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 2.5,
                'line-opacity': 0.7,
            },
            layout: {
                'line-cap': 'round',
                'line-join': 'round',
            },
        });
    }

    // Update or create the trail dots layer
    const dotSourceId = TARGET_TRAIL_SOURCE + '-dots';
    if (_state.map.getSource(dotSourceId)) {
        _state.map.getSource(dotSourceId).setData(dotGeojson);
    } else {
        _state.map.addSource(dotSourceId, { type: 'geojson', data: dotGeojson });
        _state.map.addLayer({
            id: TARGET_TRAIL_DOTS,
            type: 'circle',
            source: dotSourceId,
            paint: {
                'circle-color': ['get', 'color'],
                'circle-radius': ['get', 'radius'],
                'circle-opacity': ['get', 'opacity'],
                'circle-stroke-width': ['case', ['==', ['get', 'isLatest'], 1], 2, 0],
                'circle-stroke-color': '#ffffff',
            },
        });
    }

    // Fly to the trail bounds
    if (lineCoords.length > 1) {
        const bounds = lineCoords.reduce(
            (b, c) => [
                [Math.min(b[0][0], c[0]), Math.min(b[0][1], c[1])],
                [Math.max(b[1][0], c[0]), Math.max(b[1][1], c[1])],
            ],
            [[Infinity, Infinity], [-Infinity, -Infinity]]
        );
        _state.map.fitBounds(bounds, { padding: 60, maxZoom: 18, duration: 1000 });
    }

    EventBus.emit('toast:show', {
        message: `Trail shown for ${data.targetId.substring(0, 12)} (${sorted.length} points)`,
        type: 'info',
    });
}

/**
 * Hide the target movement trail from the map.
 */
function _onHideTargetTrail() {
    if (!_state.map) return;
    _trailState.targetId = null;
    _trailState.points = [];

    const empty = { type: 'FeatureCollection', features: [] };
    if (_state.map.getSource(TARGET_TRAIL_SOURCE)) {
        _state.map.getSource(TARGET_TRAIL_SOURCE).setData(empty);
    }
    const dotSourceId = TARGET_TRAIL_SOURCE + '-dots';
    if (_state.map.getSource(dotSourceId)) {
        _state.map.getSource(dotSourceId).setData(empty);
    }
}

// ============================================================
// Correlation Lines Overlay (GeoJSON lines between fused targets)
// ============================================================

const CORR_LINES_SOURCE = 'correlation-lines-source';
const CORR_LINES_LAYER  = 'correlation-lines-layer';
const CORR_LABELS_SOURCE = 'correlation-labels-source';
const CORR_LABELS_LAYER  = 'correlation-labels-layer';

const _corrLineState = {
    lastFetch: 0,
    fetchInterval: 5000,
    lastHash: '',
};

/**
 * Fetch correlations and draw lines between correlated targets on MapLibre.
 * Called from the slow-tick overlay update cycle.
 */
async function _updateCorrelationLines() {
    if (!_state.map || !_state.initialized) return;

    const now = Date.now();
    if (now - _corrLineState.lastFetch < _corrLineState.fetchInterval) return;
    _corrLineState.lastFetch = now;

    let records = [];
    try {
        const resp = await fetch('/api/correlations');
        if (resp.ok) {
            const data = await resp.json();
            records = data.correlations || [];
        }
    } catch (_) { /* correlations API unavailable */ }

    const features = [];
    const labelFeatures = [];
    const units = TritiumStore.units;

    for (const corr of records) {
        const idA = corr.primary_id || corr.target_a;
        const idB = corr.secondary_id || corr.target_b;
        const unitA = units.get(idA);
        const unitB = units.get(idB);
        if (!unitA || !unitB) continue;
        const posA = unitA.position;
        const posB = unitB.position;
        if (!posA || !posB) continue;
        if (posA.x === undefined || posB.x === undefined) continue;

        const llA = _gameToLngLat(posA.x || 0, posA.y || 0);
        const llB = _gameToLngLat(posB.x || 0, posB.y || 0);
        const conf = corr.confidence || corr.score || 0;
        const opacity = Math.max(0.2, conf);

        // Color: high confidence = cyan, low = yellow
        const color = conf > 0.7 ? '#00f0ff' : conf > 0.4 ? '#fcee0a' : '#ff8c00';

        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: [llA, llB] },
            properties: { color, opacity: parseFloat(opacity.toFixed(2)) },
        });

        // Label at midpoint
        const midLng = (llA[0] + llB[0]) / 2;
        const midLat = (llA[1] + llB[1]) / 2;
        labelFeatures.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [midLng, midLat] },
            properties: { label: `${Math.round(conf * 100)}%`, color },
        });
    }

    const lineGeojson = { type: 'FeatureCollection', features };
    const labelGeojson = { type: 'FeatureCollection', features: labelFeatures };

    // Check for changes
    const hash = features.map(f =>
        f.geometry.coordinates[0][0].toFixed(5) + ',' + f.properties.opacity
    ).join(';');

    if (hash === _corrLineState.lastHash) return;
    _corrLineState.lastHash = hash;

    // Update or create correlation line layer
    if (_state.map.getSource(CORR_LINES_SOURCE)) {
        _state.map.getSource(CORR_LINES_SOURCE).setData(lineGeojson);
    } else {
        _state.map.addSource(CORR_LINES_SOURCE, { type: 'geojson', data: lineGeojson });
        _state.map.addLayer({
            id: CORR_LINES_LAYER,
            type: 'line',
            source: CORR_LINES_SOURCE,
            paint: {
                'line-color': ['get', 'color'],
                'line-width': 1.5,
                'line-opacity': ['get', 'opacity'],
                'line-dasharray': [4, 4],
            },
        });
    }

    // Update or create correlation label layer
    if (_state.map.getSource(CORR_LABELS_SOURCE)) {
        _state.map.getSource(CORR_LABELS_SOURCE).setData(labelGeojson);
    } else {
        _state.map.addSource(CORR_LABELS_SOURCE, { type: 'geojson', data: labelGeojson });
        _state.map.addLayer({
            id: CORR_LABELS_LAYER,
            type: 'symbol',
            source: CORR_LABELS_SOURCE,
            layout: {
                'text-field': ['get', 'label'],
                'text-size': 10,
                'text-font': ['Open Sans Regular'],
                'text-allow-overlap': true,
            },
            paint: {
                'text-color': ['get', 'color'],
                'text-halo-color': 'rgba(10, 10, 15, 0.9)',
                'text-halo-width': 2,
            },
        });
    }
}

/**
 * Show correlation lines for a specific target on the map.
 * Highlights lines involving this target more prominently.
 * @param {Object} data - { targetId, correlatedIds: [{id, confidence}] }
 */
function _onShowCorrelationLines(data) {
    if (!_state.map || !_state.initialized || !data || !data.targetId) return;

    const units = TritiumStore.units;
    const mainUnit = units.get(data.targetId);
    if (!mainUnit || !mainUnit.position) return;

    const mainLL = _gameToLngLat(mainUnit.position.x || 0, mainUnit.position.y || 0);
    const features = [];
    const correlatedIds = data.correlatedIds || [];

    for (const corr of correlatedIds) {
        const other = units.get(corr.id);
        if (!other || !other.position) continue;
        const otherLL = _gameToLngLat(other.position.x || 0, other.position.y || 0);
        const conf = corr.confidence || 0;
        const color = conf > 0.7 ? '#00f0ff' : conf > 0.4 ? '#fcee0a' : '#ff8c00';

        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: [mainLL, otherLL] },
            properties: { color, opacity: Math.max(0.3, conf) },
        });
    }

    if (features.length > 0) {
        const geojson = { type: 'FeatureCollection', features };
        if (_state.map.getSource(CORR_LINES_SOURCE)) {
            _state.map.getSource(CORR_LINES_SOURCE).setData(geojson);
        }
    }
}

// ============================================================
// Hostile Intel HUD (DOM overlay in bottom-left corner)
// ============================================================

/**
 * Update the hostile intel HUD element.
 * Reads from TritiumStore 'game.hostileIntel'.
 * Shows enemy confidence, force ratio, and recommended action.
 */
function _updateHostileIntel() {
    if (!_state.map || !_state.initialized || !_state.container) return;

    const phase = TritiumStore.get('game.phase');
    const intel = TritiumStore.get('game.hostileIntel');

    if (!_state.showHostileIntel || !intel || (phase !== 'active' && phase !== 'wave_complete')) {
        if (_state._hostileIntelEl) {
            _state._hostileIntelEl.style.display = 'none';
        }
        return;
    }

    if (!_state._hostileIntelEl) {
        const el = document.createElement('div');
        el.className = 'hostile-intel-hud';
        el.style.cssText = [
            'position: absolute',
            'bottom: 16px',
            'left: 16px',
            'padding: 8px 12px',
            'background: rgba(0,0,0,0.75)',
            'border-left: 3px solid #ff2a6d',
            'font-family: "JetBrains Mono", monospace',
            'font-size: 11px',
            'color: #cccccc',
            'pointer-events: none',
            'z-index: 10',
            'line-height: 1.6',
        ].join(';');
        _state.container.appendChild(el);
        _state._hostileIntelEl = el;
    }

    const THREAT_COLORS = {
        low: '#05ffa1',
        moderate: '#fcee0a',
        high: '#ff8800',
        critical: '#ff2a6d',
    };

    const threat = (intel.threat_level || 'unknown').toUpperCase();
    const threatColor = THREAT_COLORS[intel.threat_level] || '#888888';
    const ratio = typeof intel.force_ratio === 'number' ? intel.force_ratio : 0;
    const ratioStr = ratio.toFixed(1) + ':1';
    const advantage = ratio >= 1.0 ? 'HOSTILE ADV' : 'FRIENDLY ADV';
    const advColor = ratio >= 1.0 ? '#ff2a6d' : '#05ffa1';
    const action = (intel.recommended_action || '').toUpperCase();

    let html = `<div style="color:#888">HOSTILE INTEL</div>`;
    html += `<div style="color:${threatColor};font-weight:bold">ENEMY CONF: ${threat}</div>`;
    html += `<div style="color:${advColor}">${ratioStr} ${advantage}</div>`;
    if (action) {
        html += `<div style="color:#00f0ff">ACTION: ${action}</div>`;
    }

    _state._hostileIntelEl.innerHTML = html;
    _state._hostileIntelEl.style.display = '';
}

// ============================================================
// Cinematic Auto-Follow Camera
// ============================================================

/**
 * Record a combat event position into the ring buffer.
 * @param {number} lng
 * @param {number} lat
 */
function _recordCombatEvent(lng, lat) {
    _state.combatEventRing.push({ lng, lat, time: Date.now() });
    if (_state.combatEventRing.length > COMBAT_EVENT_RING_SIZE) {
        _state.combatEventRing.shift();
    }
}

/**
 * Get recent combat events (within the last COMBAT_EVENT_MAX_AGE ms).
 * @returns {Array<{lng, lat, time}>}
 */
function _recentCombatEvents() {
    const cutoff = Date.now() - COMBAT_EVENT_MAX_AGE;
    return _state.combatEventRing.filter(e => e.time >= cutoff);
}

/**
 * Find the densest area of recent combat events.
 * Returns the centroid of recent events.
 * @returns {{lng: number, lat: number}|null}
 */
function _findActionHotspot() {
    const events = _recentCombatEvents();
    if (events.length === 0) return null;

    let sumLng = 0, sumLat = 0;
    for (const e of events) {
        sumLng += e.lng;
        sumLat += e.lat;
    }
    return { lng: sumLng / events.length, lat: sumLat / events.length };
}

/**
 * Evaluate where the camera should fly to next.
 * Priority:
 *   1. Active streak holder position
 *   2. Recent combat hotspot (elimination positions)
 *   3. Hostile unit centroid
 * @returns {{lng: number, lat: number, zoom: number}|null}
 */
function _evaluateAutoFollowTarget() {
    // Priority 1: active streak holder (within last 8 seconds)
    if (_state.streakHolder && (Date.now() - _state.streakHolder.time) < 8000) {
        const unit = TritiumStore.units.get(_state.streakHolder.unitId);
        if (unit && unit.position) {
            const lngLat = _gameToLngLat(unit.position.x || 0, unit.position.y || 0);
            return { lng: lngLat[0], lat: lngLat[1], zoom: 17.5 };
        }
        return { lng: _state.streakHolder.lng, lat: _state.streakHolder.lat, zoom: 17.5 };
    }

    // Priority 2: recent combat hotspot
    const hotspot = _findActionHotspot();
    if (hotspot) {
        return { lng: hotspot.lng, lat: hotspot.lat, zoom: 17 };
    }

    // Priority 3: hostile unit centroid
    let sumLng = 0, sumLat = 0, count = 0;
    TritiumStore.units.forEach(u => {
        if (u.alliance === 'hostile') {
            const pos = u.position || {};
            const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
            sumLng += lngLat[0];
            sumLat += lngLat[1];
            count++;
        }
    });
    if (count > 0) {
        return { lng: sumLng / count, lat: sumLat / count, zoom: 16.5 };
    }

    return null;
}

/**
 * Perform one auto-follow camera evaluation and fly.
 */
function _autoFollowTick() {
    if (!_state.autoFollow || !_state.map || _state.autoFollowFlyingNow) return;

    const target = _evaluateAutoFollowTarget();
    if (!target) return;

    _state.autoFollowFlyingNow = true;
    _state.map.flyTo({
        center: [target.lng, target.lat],
        zoom: target.zoom,
        duration: AUTO_FOLLOW_FLY_DURATION,
    });

    // Clear the flying flag after animation completes
    setTimeout(() => {
        _state.autoFollowFlyingNow = false;
    }, AUTO_FOLLOW_FLY_DURATION + 100);
}

/**
 * Handle an immediate flyTo for an elimination event.
 */
function _autoFollowOnElimination(data) {
    if (!_state.autoFollow || !_state.map) return;

    const pos = data.position || data;
    const gx = pos.x || 0;
    const gy = pos.y || 0;
    const lngLat = _gameToLngLat(gx, gy);

    _recordCombatEvent(lngLat[0], lngLat[1]);

    _state.autoFollowFlyingNow = true;
    _state.map.flyTo({
        center: lngLat,
        zoom: 17.5,
        duration: 1500,
    });
    setTimeout(() => { _state.autoFollowFlyingNow = false; }, 1600);
}

/**
 * Handle streak events for auto-follow focus.
 */
function _autoFollowOnStreak(data) {
    if (!_state.autoFollow) return;
    const unitId = data.unit_id || data.interceptor_id;
    if (!unitId) return;
    const unit = TritiumStore.units.get(unitId);
    if (unit && unit.position) {
        const lngLat = _gameToLngLat(unit.position.x || 0, unit.position.y || 0);
        _state.streakHolder = { unitId, lng: lngLat[0], lat: lngLat[1], time: Date.now() };
    }
}

/**
 * Record projectile hit events into the combat ring buffer.
 */
function _autoFollowOnHit(data) {
    if (!_state.autoFollow) return;
    const pos = data.position || data.target_position || data;
    const gx = pos.x || 0;
    const gy = pos.y || 0;
    if (gx === 0 && gy === 0) return;
    const lngLat = _gameToLngLat(gx, gy);
    _recordCombatEvent(lngLat[0], lngLat[1]);
}

/**
 * Create/remove the AUTO badge in the map container.
 */
function _updateAutoBadge() {
    const existing = document.getElementById('auto-follow-badge');
    if (_state.autoFollow) {
        if (!existing && _state.container) {
            const badge = document.createElement('div');
            badge.id = 'auto-follow-badge';
            badge.textContent = 'AUTO';
            badge.style.cssText = [
                'position:absolute; top:8px; right:60px; z-index:10;',
                'font-family:"JetBrains Mono",monospace; font-size:11px;',
                'color:#05ffa1; background:rgba(5,255,161,0.15);',
                'padding:3px 8px; border-radius:3px;',
                'border:1px solid rgba(5,255,161,0.4);',
                'text-transform:uppercase; letter-spacing:1px;',
                'pointer-events:none; animation:pulse-glow 2s ease-in-out infinite;',
            ].join('');
            _state.container.appendChild(badge);
        }
    } else {
        if (existing) existing.remove();
    }
}

/**
 * Start the auto-follow timer and subscribe to combat events.
 */
function _startAutoFollow() {
    _state.autoFollow = true;

    EventBus.on('combat:elimination', _autoFollowOnElimination);
    EventBus.on('combat:streak', _autoFollowOnStreak);
    EventBus.on('combat:hit', _autoFollowOnHit);

    // Disable auto-follow when user manually pans/zooms
    if (_state.map) {
        _state.map.on('movestart', _onUserMoveStart);
    }

    // Start periodic evaluation
    _state.autoFollowTimer = setInterval(_autoFollowTick, AUTO_FOLLOW_INTERVAL);

    // Immediate first evaluation
    _autoFollowTick();

    _updateAutoBadge();
    _updateLayerHud();
    console.log('[MAP-ML] Auto-follow ON');
}

/**
 * Stop the auto-follow timer and unsubscribe from combat events.
 */
function _stopAutoFollow() {
    _state.autoFollow = false;

    if (_state.autoFollowTimer) {
        clearInterval(_state.autoFollowTimer);
        _state.autoFollowTimer = null;
    }

    EventBus.off('combat:elimination', _autoFollowOnElimination);
    EventBus.off('combat:streak', _autoFollowOnStreak);
    EventBus.off('combat:hit', _autoFollowOnHit);

    if (_state.map) {
        _state.map.off('movestart', _onUserMoveStart);
    }

    _state.autoFollowFlyingNow = false;
    _state.streakHolder = null;

    _updateAutoBadge();
    _updateLayerHud();
    console.log('[MAP-ML] Auto-follow OFF');
}

/**
 * Handler for map movestart -- if the move was NOT triggered by auto-follow,
 * the user manually panned, so disable auto-follow.
 */
function _onUserMoveStart() {
    if (_state.autoFollowFlyingNow) return;
    if (_state.autoFollow) {
        _stopAutoFollow();
        console.log('[MAP-ML] Auto-follow disabled by user interaction');
    }
}

// ============================================================
// Unit Rendering (MapLibre markers with DOM elements)
// ============================================================

function _startUnitLoop() {
    _scheduleUnitUpdate();
}

/**
 * Adaptively schedule the unit update loop based on current unit count.
 * Fewer units = higher update rate (smoother); many units = throttled
 * to avoid burning CPU on DOM marker updates that humans can't perceive.
 *
 *   < 30 units  ->  10 Hz (100ms)  -- smooth, low cost
 *  30-50 units  ->   6 Hz (166ms)  -- still responsive
 *  50-80 units  ->   4 Hz (250ms)  -- saves CPU on mid-size battles
 *    80+ units  ->   2 Hz (500ms)  -- large battles, DOM is expensive
 */
function _scheduleUnitUpdate() {
    const unitCount = TritiumStore.units ? TritiumStore.units.size : 0;
    let interval = 100;  // 10 Hz default
    if (unitCount > 80)       interval = 500;   // 2 Hz
    else if (unitCount > 50)  interval = 250;   // 4 Hz
    else if (unitCount > 30)  interval = 166;   // 6 Hz

    clearInterval(_state._unitUpdateTimer);
    _state._unitUpdateTimer = setInterval(() => {
        _updateUnits();
        _drawMinimap();
        _scheduleUnitUpdate();  // re-evaluate interval as unit count changes
    }, interval);
}

function _updateUnits() {
    if (!_state.map || !_state.initialized) return;

    // Tick counter for throttling slow-changing overlays to ~1Hz
    _state._overlayTickCounter = (_state._overlayTickCounter + 1) % 10;
    const slowTick = _state._overlayTickCounter === 0; // true once per second

    const units = TritiumStore.units;
    const seenIds = new Set();

    // Debug: log unit count once per second
    if (slowTick && units.size > 0 && Object.keys(_state.unitMarkers).length === 0) {
        console.warn(`[MAP-ML] ${units.size} units in store but 0 markers rendered — checking first unit...`);
        units.forEach((u, id) => {
            if (seenIds.size === 0) {
                const pos = u.position || {};
                console.warn(`[MAP-ML] First unit: ${id}, pos=(${pos.x}, ${pos.y}), lngLat=${JSON.stringify(_gameToLngLat(pos.x || 0, pos.y || 0))}`);
            }
            seenIds.add(id); // temporary to break after first
        });
        seenIds.clear(); // reset for actual loop below
    }

    units.forEach((unit, id) => {
        seenIds.add(id);
        const pos = unit.position || {};
        const gx = pos.x || 0;
        const gy = pos.y || 0;
        const lngLat = _gameToLngLat(gx, gy);

        if (_state.unitMarkers[id]) {
            // Update existing marker position
            _state.unitMarkers[id].setLngLat(lngLat);
            _updateMarkerElement(_state.unitMarkers[id], unit);
        } else {
            // Create new marker
            _state.unitMarkers[id] = _createUnitMarker(id, unit, lngLat);
        }

        // Visibility: respect global toggle, alliance filter, and target filter overlay
        const el = _state.unitMarkers[id].getElement();
        const allianceOk = !_state.allianceFilter ||
            _state.allianceFilter.includes(unit.alliance || 'unknown');
        const filterOk = !window.matchesTargetFilter || window.matchesTargetFilter(unit);
        el.style.display = (_state.showUnits && allianceOk && filterOk) ? '' : 'none';

        // Fog of war: dim invisible hostiles, show radio ghosts
        if (unit.alliance === 'hostile' && unit.visible === false && _state.showFog) {
            if (unit.radio_detected) {
                // Radio-detected: show as uncertain position with signal indicator
                el.classList.remove('fog-hidden');
                el.classList.add('radio-ghost');
                // Update signal strength data attribute for CSS animation intensity
                el.dataset.signalStrength = (unit.radio_signal_strength || 0).toFixed(2);
            } else {
                el.classList.add('fog-hidden');
                el.classList.remove('radio-ghost');
            }
        } else {
            el.classList.remove('fog-hidden');
            el.classList.remove('radio-ghost');
        }
    });

    // Remove markers for deleted units
    for (const id of Object.keys(_state.unitMarkers)) {
        if (!seenIds.has(id)) {
            _state.unitMarkers[id].remove();
            delete _state.unitMarkers[id];
        }
    }

    // Sync Three.js 3D unit meshes
    _sync3DUnits();

    // Patrol routes and weapon range rarely change — update at 1Hz
    if (slowTick) {
        _updatePatrolRoutes();
        _updateWeaponRange();
    }

    // Dispatch arrows fade over 3s — need 10Hz for smooth opacity
    _updateDispatchArrows();

    // Weapon range removed from 10Hz — handled by slowTick above

    // Update drone swarm convex hull
    _updateSwarmHull();

    // Update squad formation hulls
    _updateSquadHulls();

    // Hazard zones need per-tick update (opacity fades with remaining time)
    _updateHazardZones();

    // Unit signals need per-tick update (expanding rings that fade)
    _updateUnitSignals();

    // Engagement lines — dashed lines between firing units and their targets
    _updateEngagementLines();

    // Combat status bar at bottom of map
    if (slowTick) _updateCombatStatusBar();

    // Slow-tick overlays: hostile objectives, crowd density, cover points, hostile intel, geofence zones
    if (slowTick) {
        _updateHostileObjectives();
        _updateCrowdDensity();
        _updateCoverPoints();
        _updateHostileIntel();
        _updateGeofenceZones();
        _updateCorrelationLines();

        // Prune stale recentlyFired entries (>5s old)
        const pruneThreshold = performance.now() - 5000;
        for (const uid of Object.keys(_state.recentlyFired)) {
            if (_state.recentlyFired[uid].time < pruneThreshold) {
                delete _state.recentlyFired[uid];
            }
        }
    }
}

function _resolveModalType(unit) {
    const type = unit.asset_type || unit.type || 'generic';
    const alliance = unit.alliance || 'unknown';
    const npcTypes = ['person', 'animal', 'vehicle'];
    return (npcTypes.includes(type) && alliance === 'neutral') ? 'npc' : type;
}

function _createUnitMarker(id, unit, lngLat) {
    // CRITICAL: MapLibre v4+ adds classes directly to the element passed to
    // Marker() and uses element.style.transform to position it.  If we set
    // style.cssText on that element (as _applyMarkerStyle does), we destroy
    // MapLibre's positioning transform, causing all markers to pile up at (0,0).
    //
    // Solution: use a thin outer wrapper for MapLibre positioning and put all
    // visual content inside an inner div that _applyMarkerStyle can restyle freely.

    const outer = document.createElement('div');
    outer.className = 'tritium-unit-marker';
    outer.dataset.unitId = id;
    outer.dataset.alliance = unit.alliance || 'unknown';
    // Outer must be transparent to MapLibre — no style.cssText on it!
    outer.style.pointerEvents = 'auto';
    outer.style.cursor = 'pointer';

    const inner = document.createElement('div');
    inner.className = 'tritium-unit-inner';
    outer.appendChild(inner);

    _applyMarkerStyle(inner, unit);

    const marker = new maplibregl.Marker({
        element: outer,
        anchor: 'center',
        rotationAlignment: 'viewport',  // labels always face the viewer
        pitchAlignment: 'viewport',
    })
        .setLngLat(lngLat)
        .addTo(_state.map);

    // Hover effect + tooltip
    const tooltip = document.createElement('div');
    tooltip.className = 'unit-tooltip';
    tooltip.style.cssText = 'position:absolute;bottom:calc(100% + 6px);left:50%;transform:translateX(-50%);' +
        'background:rgba(10,10,20,0.95);border:1px solid var(--cyan);border-radius:3px;padding:4px 8px;' +
        'font-size:0.55rem;white-space:nowrap;pointer-events:none;display:none;z-index:100;' +
        'font-family:var(--font-mono);color:var(--text);box-shadow:0 2px 8px rgba(0,0,0,0.5);';
    outer.appendChild(tooltip);

    outer.addEventListener('mouseenter', () => {
        outer.classList.add('unit-marker-hovered');
        // Raise z-index so hovered marker stays above overlapping neighbors
        const markerContainer = outer.closest('.maplibregl-marker');
        if (markerContainer) markerContainer.style.zIndex = '50';
        const u = TritiumStore.units.get(id);
        if (u) {
            const hpPct = u.maxHealth ? Math.round((u.health / u.maxHealth) * 100) : '?';
            const hpColor = hpPct > 60 ? 'var(--green)' : hpPct > 30 ? 'var(--amber)' : 'var(--magenta)';
            const fsm = u.fsmState ? ` <span style="color:var(--text-ghost)">${_esc(u.fsmState)}</span>` : '';
            const kills = u.kills ? ` <span style="color:var(--amber)">${u.kills} kills</span>` : '';
            const ammo = (u.ammoCount != null && u.ammoMax) ? ` <span style="color:#aaa">${u.ammoCount}/${u.ammoMax}</span>` : '';
            // Robot-specific tooltip extras: battery, speed, current task
            const uType = (u.type || '').toLowerCase();
            const isRobot = uType.includes('rover') || uType.includes('drone') || uType.includes('scout') || uType.includes('robot');
            let robotInfo = '';
            if (isRobot) {
                const bat = u.battery != null ? Math.round(u.battery) + '%' : '--';
                const spd = u.speed != null ? u.speed.toFixed(1) + ' m/s' : '';
                robotInfo = `<div style="color:var(--cyan);font-size:0.5rem">BAT: ${bat}${spd ? '  SPD: ' + spd : ''}</div>`;
            }
            tooltip.innerHTML = `<div style="color:${ALLIANCE_COLORS[u.alliance] || 'var(--cyan)'};font-weight:bold">${_esc(u.name || id)}</div>` +
                `<div>${_esc(u.type || '?')}${fsm}</div>` +
                `<div>HP: <span style="color:${hpColor}">${hpPct}%</span>${kills}${ammo}</div>` +
                robotInfo;
            tooltip.style.display = 'block';
        }
    });
    outer.addEventListener('mouseleave', () => {
        outer.classList.remove('unit-marker-hovered');
        // Restore default z-index unless this marker is selected
        const markerContainer = outer.closest('.maplibregl-marker');
        const isSelected = _state.selectedUnitId === id || TritiumStore.get('map.selectedUnitId') === id;
        if (markerContainer && !isSelected) markerContainer.style.zIndex = '';
        tooltip.style.display = 'none';
    });

    // Click handler for selection + open inspector
    outer.addEventListener('click', (e) => {
        e.stopPropagation();
        TritiumStore.set('map.selectedUnitId', id);
        EventBus.emit('unit:selected', { id });
        EventBus.emit('panel:request-open', { id: 'unit-inspector' });
        // Immediate visual feedback — don't wait for next telemetry cycle
        _onSelectionChanged(id);
    });

    // Double-click handler: fly-to unit
    outer.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        const u = TritiumStore.units.get(id);
        if (u && u.position) {
            const flyLngLat = _gameToLngLat(u.position.x, u.position.y);
            if (_state.map) _state.map.flyTo({ center: flyLngLat, zoom: Math.max(_state.map.getZoom(), 18) });
        }
    });

    // Double-click handler for device modal
    outer.addEventListener('dblclick', (e) => {
        e.stopPropagation();
        const u = TritiumStore.units.get(id);
        if (u) {
            const modalType = _resolveModalType(u);
            DeviceModalManager.open(id, modalType, u);
        }
    });

    return marker;
}

function _abbreviateName(name, iconLetter) {
    // "turret-a1b2c3" → "T-A1B", "Alpha-1" → "A-1", "hostile-test" → "P-TST"
    if (!name) return iconLetter;
    // Remove common prefixes that match the icon letter
    const parts = name.split('-');
    if (parts.length >= 2) {
        const suffix = parts.slice(1).join('-').toUpperCase().slice(0, 4);
        return iconLetter + '-' + suffix;
    }
    return name.slice(0, 5).toUpperCase();
}

/**
 * Determine morale state from a numeric morale value.
 * Matches backend thresholds in morale.py:
 *   broken < 0.1, suppressed < 0.3, emboldened > 0.9
 * @param {number|undefined|null} morale - morale value [0..1]
 * @returns {string|null} 'broken', 'suppressed', 'emboldened', or null (normal)
 */
function _getMoraleState(morale) {
    if (morale === undefined || morale === null || typeof morale !== 'number') return null;
    if (morale < 0.1) return 'broken';
    if (morale < 0.3) return 'suppressed';
    if (morale > 0.9) return 'emboldened';
    return null;
}

// Expose for testing
window._getMoraleState = _getMoraleState;

const _MORALE_BADGE_TEXT = {
    broken: '\u00AB\u00AB',       // "<<" (flee arrows)
    suppressed: '\u2304',          // downward chevron
    emboldened: '\u2303',          // upward chevron
};

const _MORALE_BADGE_COLORS = {
    broken: '#ff2a6d',
    suppressed: '#fcee0a',
    emboldened: '#00f0ff',
};

const _MORALE_TOOLTIP_TEXT = {
    broken: 'BROKEN',
    suppressed: 'SUPPRESSED',
    emboldened: 'EMBOLDENED',
};

function _applyMarkerStyle(el, unit) {
    const alliance = unit.alliance || 'unknown';
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const type = (unit.type || 'unknown').toLowerCase();
    const selected = _state.selectedUnitId === unit.id;
    const controlled = TritiumStore.get('controlledUnitId') === unit.id;
    const has3D = !!_state.threeRoot;
    const modelsVisible = _state.showModels3d;
    // Use 3D render path only when 3D models are both available AND enabled.
    // When models are toggled off, fall through to 2D large-icon path.
    const use3DPath = has3D && modelsVisible;

    // Icon letter — order matters: specific types before broad includes()
    let icon = '?';
    if (type.includes('turret')) icon = 'T';
    else if (type.includes('drone') || type.includes('scout')) icon = 'D';
    else if (type.includes('rover')) icon = 'R';
    else if (type.includes('tank')) icon = 'K';
    else if (type.includes('apc')) icon = 'A';
    else if (type === 'hostile_vehicle') icon = 'V';
    else if (type === 'hostile_leader') icon = 'L';
    else if (type.includes('person') || type.includes('hostile')) icon = 'P';
    else if (type.includes('vehicle')) icon = 'V';
    else if (type.includes('sensor')) icon = 'S';
    else if (type.includes('camera')) icon = 'C';

    // Health ratio
    const hp = unit.health || 0;
    const maxHp = unit.maxHealth || 100;
    const hpRatio = Math.max(0, Math.min(1, hp / maxHp));

    // Status
    const dead = unit.status === 'eliminated' || unit.status === 'neutralized';
    const opacity = dead ? 0.3 : 1.0;

    // --- Performance: skip full restyle if nothing visually changed ---
    // Build a compact fingerprint of all values that affect marker appearance.
    // Position is handled by setLngLat() so it's not included here.
    const moraleState = _getMoraleState(unit.morale);
    const unitSource = unit.source || 'sim';
    const fsmState = (unit.fsmState || unit.fsm_state || '').toLowerCase();
    const firedEntry = _state.recentlyFired[unit.id];
    const inCombat = firedEntry && (performance.now() - firedEntry.time) < 3000;
    const firedTime = firedEntry ? Math.round(firedEntry.time / 100) : 0;  // 100ms granularity for re-fire detection
    const gamePhaseCurrent = (typeof TritiumStore !== 'undefined') ? (TritiumStore.get('game.phase') || 'idle') : 'idle';
    const styleHash = `${alliance}|${type}|${hpRatio.toFixed(2)}|${dead}|${selected}|${has3D}|${modelsVisible}|${_state.showLabels}|${_state.showHealthBars}|${_state.showSelectionFx}|${moraleState}|${unitSource}|${unit.name || ''}|${inCombat}|${firedTime}|${gamePhaseCurrent}`;
    if (el._lastStyleHash === styleHash) return;
    el._lastStyleHash = styleHash;

    // Inject shared CSS (once)
    if (!document.getElementById('tritium-marker-css')) {
        const css = document.createElement('style');
        css.id = 'tritium-marker-css';
        css.textContent = [
            '@keyframes hostile-pulse {',
            '  0%, 100% { box-shadow: 0 0 8px #ff2a6d88; }',
            '  50% { box-shadow: 0 0 20px #ff2a6d, 0 0 40px #ff2a6d66; }',
            '}',
            '',
            '/* Morale state animations */',
            '@keyframes morale-suppressed-pulse {',
            '  0%, 100% { border-color: #fcee0a44; box-shadow: 0 0 4px #fcee0a22; }',
            '  50% { border-color: #fcee0a; box-shadow: 0 0 10px #fcee0a66; }',
            '}',
            '@keyframes morale-broken-pulse {',
            '  0%, 100% { border-color: #ff2a6d; box-shadow: 0 0 6px #ff2a6d66; }',
            '  50% { border-color: #fcee0a; box-shadow: 0 0 12px #fcee0a88; }',
            '}',
            '@keyframes morale-emboldened-glow {',
            '  0%, 100% { box-shadow: 0 0 8px #00f0ff44; }',
            '  50% { box-shadow: 0 0 18px #00f0ff, 0 0 30px #00f0ff44; }',
            '}',
            '',
            '/* Morale state classes on outer .tritium-unit-marker wrapper */',
            '.unit-marker-suppressed .tritium-unit-inner {',
            '  animation: morale-suppressed-pulse 1.5s ease-in-out infinite !important;',
            '}',
            '.unit-marker-broken .tritium-unit-inner {',
            '  animation: morale-broken-pulse 0.5s ease-in-out infinite !important;',
            '  transform: scale(0.85);',
            '}',
            '.unit-marker-emboldened .tritium-unit-inner {',
            '  animation: morale-emboldened-glow 2s ease-in-out infinite !important;',
            '  transform: scale(1.1);',
            '}',
            '',
            '/* Combat firing indicator */',
            '@keyframes combat-fire-pulse {',
            '  0%, 100% { box-shadow: 0 0 8px var(--fire-color), 0 0 16px var(--fire-color); transform: scale(1); }',
            '  50% { box-shadow: 0 0 16px var(--fire-color), 0 0 32px var(--fire-color), 0 0 48px var(--fire-color); transform: scale(1.15); }',
            '}',
            '.unit-combat-ring {',
            '  position: absolute; inset: -8px; border-radius: 50%;',
            '  border: 2px solid var(--fire-color);',
            '  pointer-events: none;',
            '  animation: combat-fire-pulse 0.6s ease-in-out infinite;',
            '}',
            '',
            '/* Morale badge positioning */',
            '.morale-badge {',
            '  position: absolute;',
            '  top: -6px;',
            '  right: -6px;',
            '  font-family: "JetBrains Mono", monospace;',
            '  font-size: 8px;',
            '  font-weight: bold;',
            '  line-height: 1;',
            '  padding: 1px 2px;',
            '  border-radius: 3px;',
            '  background: #000000cc;',
            '  pointer-events: none;',
            '  z-index: 5;',
            '  text-shadow: 0 0 3px currentColor;',
            '}',
            '',
            '/* YOLO camera detection ring — dashed orange border */',
            '@keyframes yolo-ring-pulse {',
            '  0%, 100% { opacity: 0.6; box-shadow: 0 0 4px #ffa50044; }',
            '  50% { opacity: 1.0; box-shadow: 0 0 10px #ffa50088, 0 0 20px #ffa50033; }',
            '}',
            '.unit-yolo-ring {',
            '  animation: yolo-ring-pulse 2s ease-in-out infinite;',
            '}',
        ].join('\n');
        document.head.appendChild(css);
    }

    if (use3DPath) {
        // ----- 3D mode: compact callsign tag below the 3D model -----
        // Labels are always viewport-aligned (never rotated) for readability.
        // Size is deliberately small so the 3D model is the primary visual.
        const hpColor = hpRatio > 0.5 ? '#05ffa1' : hpRatio > 0.25 ? '#fcee0a' : '#ff2a6d';
        el.style.cssText = `
            pointer-events: auto; cursor: pointer;
            display: inline-flex; flex-direction: column; align-items: center;
            position: relative; opacity: ${opacity};
            transform: translateY(12px);
            width: auto; max-width: 70px;
        `;
        el.textContent = ''; // clear any icon letter

        // Remove leftover 2D elements (loc dots) if switching from 2D path
        const locDot = el.querySelector('.unit-loc-dot');
        if (locDot) locDot.remove();

        // Callsign label — short, no-wrap, tiny (respects showLabels toggle)
        let nameLabel = el.querySelector('.unit-name-3d');
        if (_state.showLabels) {
            if (!nameLabel) {
                nameLabel = document.createElement('div');
                nameLabel.className = 'unit-name-3d';
                el.appendChild(nameLabel);
            }
            // Show short_id hex if available, else abbreviated name
            const unitShortId = (unit.identity && unit.identity.short_id) ? unit.identity.short_id : '';
            const shortName = unitShortId || _abbreviateName(unit.name || '', icon);
            nameLabel.textContent = shortName;
        } else if (nameLabel) {
            nameLabel.remove();
            nameLabel = null;
        }
        if (nameLabel) {
            nameLabel.style.cssText = `
                font-family: 'JetBrains Mono', monospace;
                font-size: 7px; font-weight: bold; letter-spacing: 0.3px;
                color: ${color}; white-space: nowrap;
                text-shadow: 0 0 3px #000, 0 0 6px #000;
                padding: 0px 3px; border-radius: 2px;
                background: #000000aa;
                border: 1px solid ${color}${(selected && _state.showSelectionFx) ? '' : '33'};
                max-width: 60px; overflow: hidden; text-overflow: ellipsis;
                line-height: 1.2;
                ${(selected && _state.showSelectionFx) ? 'box-shadow: 0 0 6px ' + color + '; border-color: ' + color + ';' : ''}
            `;
        }

        // Tiny health bar (respects showHealthBars toggle)
        let healthBar = el.querySelector('.unit-hp-bar-3d');
        if (_state.showHealthBars) {
            if (!healthBar) {
                healthBar = document.createElement('div');
                healthBar.className = 'unit-hp-bar-3d';
                healthBar.style.cssText = 'width: 100%; height: 1px; background: #333; border-radius: 1px; overflow: hidden; margin-top: 1px;';
                const fill = document.createElement('div');
                fill.className = 'unit-hp-fill-3d';
                fill.style.cssText = 'height: 100%; border-radius: 1px; transition: width 0.3s;';
                healthBar.appendChild(fill);
                el.appendChild(healthBar);
            }
            const fill3d = healthBar.querySelector('.unit-hp-fill-3d');
            if (fill3d) {
                fill3d.style.width = `${hpRatio * 100}%`;
                fill3d.style.background = hpColor;
            }
        } else if (healthBar) {
            healthBar.remove();
        }

        // Remove 2D-mode elements if switching
        const old2d = el.querySelector('.unit-damage-glow');
        if (old2d) old2d.remove();
        const oldHp = el.querySelector('.unit-hp-bar');
        if (oldHp) oldHp.remove();
        const oldName = el.querySelector('.unit-name');
        if (oldName) oldName.remove();

    } else {
        // ----- 2D mode: NATO APP-6 style symbology -----
        // hostile = red diamond (rotated 45deg), friendly = blue/green circle, unknown = yellow square
        // robots (rover/drone/scout) = larger hexagonal marker for visual distinction
        const isRobotType = type.includes('rover') || type.includes('drone') || type.includes('scout') || type.includes('robot');
        const combatActive = (typeof TritiumStore !== 'undefined') && (TritiumStore.get('game.phase') === 'active' || TritiumStore.get('game.phase') === 'countdown');
        const hostileSize = combatActive ? 28 : 22;
        const size = isRobotType ? 30 : (alliance === 'hostile' ? hostileSize : 26);
        const pulse = (_state.showSelectionFx && alliance === 'hostile' && !dead) ? 'animation: hostile-pulse 1.5s ease-in-out infinite;' : '';
        const selGlow = selected && _state.showSelectionFx;

        // NATO shape: hostile=diamond, friendly=circle, unknown/neutral=square, robot=hexagon
        let borderRadius, markerTransform, clipPath;
        clipPath = '';
        if (isRobotType) {
            // Hexagonal marker: use clip-path on a pseudo-element approach
            // Since clip-path clips borders too, use rounded hex (12-sided approximation)
            borderRadius = '4px';
            markerTransform = '';
            clipPath = 'clip-path: polygon(50% 0%, 85% 10%, 100% 35%, 100% 65%, 85% 90%, 50% 100%, 15% 90%, 0% 65%, 0% 35%, 15% 10%);';
        } else if (alliance === 'hostile') {
            borderRadius = '3px';
            markerTransform = 'rotate(45deg)';
        } else if (alliance === 'friendly') {
            borderRadius = '50%';
            markerTransform = '';
        } else {
            // unknown / neutral = square
            borderRadius = '3px';
            markerTransform = '';
        }
        if (selGlow) markerTransform = (markerTransform ? markerTransform + ' ' : '') + 'scale(1.3)';

        el.style.cssText = `
            width: ${size}px; height: ${size}px;
            border-radius: ${isRobotType ? '0' : borderRadius};
            ${clipPath}
            background: ${dead ? '#33333366' : (isRobotType ? `linear-gradient(135deg, ${color}99, ${color}22 50%, ${color}99)` : `radial-gradient(circle, ${color}55, ${color}22)`)};
            ${isRobotType ? '' : `border: 1.5px solid ${color};`}
            display: flex; align-items: center; justify-content: center;
            font-family: 'JetBrains Mono', monospace;
            font-size: ${isRobotType ? '13px' : (alliance === 'hostile' ? '10px' : '11px')}; font-weight: bold;
            color: ${color};
            cursor: pointer;
            opacity: ${opacity};
            transition: transform 0.15s, box-shadow 0.15s;
            box-shadow: 0 0 ${selGlow ? (isRobotType ? '20' : '14') : (isRobotType ? '12' : '5')}px ${color}${selGlow ? '' : (isRobotType ? '88' : '44')};
            ${markerTransform ? `transform: ${markerTransform};` : ''}
            ${pulse}
            position: relative;
            text-shadow: 0 0 ${isRobotType ? '6' : '4'}px ${color};
            ${isRobotType ? `filter: drop-shadow(0 0 3px ${color});` : ''}
        `;
        // For diamond (hostile), counter-rotate the icon letter so it stays upright
        if (alliance === 'hostile') {
            el.innerHTML = `<span style="display:inline-block;transform:rotate(-45deg)">${icon}</span>`;
        } else {
            el.textContent = icon;
        }

        // YOLO/camera-detected targets: orange outline ring to distinguish
        // from simulation or BLE-detected targets (Loop 8 camera detection viz)
        let yoloRing = el.querySelector('.unit-yolo-ring');
        if (unitSource === 'yolo' && !dead) {
            if (!yoloRing) {
                yoloRing = document.createElement('div');
                yoloRing.className = 'unit-yolo-ring';
                yoloRing.style.cssText = 'position:absolute;inset:-4px;border-radius:50%;' +
                    'border:2px dashed #ffa500;pointer-events:none;opacity:0.8;' +
                    'box-shadow:0 0 6px #ffa50066,inset 0 0 4px #ffa50033;';
                el.appendChild(yoloRing);
            }
        } else if (yoloRing) {
            yoloRing.remove();
        }

        // Remove 3D-mode elements if switching
        const old3dName = el.querySelector('.unit-name-3d');
        if (old3dName) old3dName.remove();
        const old3dHp = el.querySelector('.unit-hp-bar-3d');
        if (old3dHp) old3dHp.remove();
        const oldLocDot = el.querySelector('.unit-loc-dot');
        if (oldLocDot) oldLocDot.remove();

        // Damage state visual effects (respects showHealthBars toggle)
        let damageGlow = el.querySelector('.unit-damage-glow');
        if (_state.showHealthBars && hpRatio < 0.5 && !dead && alliance !== 'hostile') {
            if (!damageGlow) {
                damageGlow = document.createElement('div');
                damageGlow.className = 'unit-damage-glow';
                damageGlow.style.cssText = 'position:absolute; inset:-6px; border-radius:50%; pointer-events:none;';
                el.appendChild(damageGlow);
            }
            const glowColor = hpRatio < 0.25 ? '#ff2a6d' : '#fcee0a';
            damageGlow.style.boxShadow = '0 0 10px ' + glowColor + ', 0 0 20px ' + glowColor + '44';
            damageGlow.style.animation = 'hostile-pulse 1s ease-in-out infinite';
        } else if (damageGlow) {
            damageGlow.remove();
        }

        // Combat firing indicator — pulsing ring when unit is actively engaging
        let combatRing = el.querySelector('.unit-combat-ring');
        if (inCombat && !dead) {
            if (!combatRing) {
                combatRing = document.createElement('div');
                combatRing.className = 'unit-combat-ring';
                el.appendChild(combatRing);
            }
            const fireColor = alliance === 'hostile' ? '#ff2a6d' : '#ffa500';
            combatRing.style.setProperty('--fire-color', fireColor);
            combatRing.style.borderRadius = alliance === 'friendly' ? '50%' : '7px';
        } else if (combatRing) {
            combatRing.remove();
        }

        // Weapon cooldown arc — SVG circle that sweeps from 0→360° as weapon recharges
        let cdArc = el.querySelector('.unit-cd-arc');
        const weaponCooldown = unit.weapon_cooldown || unit.weaponCooldown || 0;
        if (inCombat && !dead && weaponCooldown > 0 && alliance !== 'hostile') {
            const arcSize = size + 16;
            const arcR = (arcSize - 4) / 2;  // radius inside the SVG
            const circumference = 2 * Math.PI * arcR;
            if (!cdArc) {
                cdArc = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                cdArc.setAttribute('class', 'unit-cd-arc');
                cdArc.style.cssText = `position:absolute; pointer-events:none; z-index:3;`;
                const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
                circle.setAttribute('class', 'cd-arc-circle');
                circle.setAttribute('fill', 'none');
                circle.setAttribute('stroke-linecap', 'round');
                cdArc.appendChild(circle);
                el.appendChild(cdArc);
            }
            cdArc.setAttribute('width', arcSize);
            cdArc.setAttribute('height', arcSize);
            cdArc.style.top = `${-(arcSize - size) / 2}px`;
            cdArc.style.left = `${-(arcSize - size) / 2}px`;
            const circle = cdArc.querySelector('.cd-arc-circle');
            circle.setAttribute('cx', arcSize / 2);
            circle.setAttribute('cy', arcSize / 2);
            circle.setAttribute('r', arcR);
            circle.setAttribute('stroke', '#05ffa1');
            circle.setAttribute('stroke-width', '2.5');
            circle.setAttribute('stroke-dasharray', circumference);
            // Animate: offset goes from circumference (empty) to 0 (full)
            circle.style.strokeDashoffset = circumference;
            circle.style.transition = 'none';
            circle.style.transform = 'rotate(-90deg)';
            circle.style.transformOrigin = '50% 50%';
            // Force reflow then animate
            void circle.offsetWidth;
            circle.style.transition = `stroke-dashoffset ${weaponCooldown}s linear`;
            circle.style.strokeDashoffset = '0';
        } else if (cdArc) {
            cdArc.remove();
        }

        // Operator control indicator — pulsing cyan ring
        let ctrlRing = el.querySelector('.unit-ctrl-ring');
        if (controlled) {
            if (!ctrlRing) {
                ctrlRing = document.createElement('div');
                ctrlRing.className = 'unit-ctrl-ring';
                ctrlRing.style.cssText = 'position:absolute; inset:-8px; border-radius:50%; pointer-events:none; border:2px dashed #00f0ff;';
                el.appendChild(ctrlRing);
            }
            ctrlRing.style.animation = 'hostile-pulse 1s ease-in-out infinite';
            ctrlRing.style.boxShadow = '0 0 8px #00f0ff, 0 0 16px #00f0ff44';
        } else if (ctrlRing) {
            ctrlRing.remove();
        }

        // Eliminated X overlay
        let elimX = el.querySelector('.unit-elim-x');
        if (dead) {
            if (!elimX) {
                elimX = document.createElement('div');
                elimX.className = 'unit-elim-x';
                elimX.textContent = '\u2716';
                elimX.style.cssText = [
                    'position:absolute; inset:0;',
                    'display:flex; align-items:center; justify-content:center;',
                    'font-size:24px; color:#ff2a6d; pointer-events:none;',
                    'text-shadow:0 0 6px #ff2a6d, 0 0 12px #000;',
                ].join('');
                el.appendChild(elimX);
            }
        } else if (elimX) {
            elimX.remove();
        }

        // Health bar below marker (respects showHealthBars toggle)
        let healthBar = el.querySelector('.unit-hp-bar');
        if (_state.showHealthBars) {
            if (!healthBar) {
                healthBar = document.createElement('div');
                healthBar.className = 'unit-hp-bar';
                healthBar.style.cssText = `
                    position: absolute; bottom: -5px; left: 0px; right: 0px; height: 3px;
                    background: #222; border-radius: 2px; overflow: hidden;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.5);
                `;
                const fill = document.createElement('div');
                fill.className = 'unit-hp-fill';
                fill.style.cssText = 'height: 100%; border-radius: 1px; transition: width 0.3s;';
                healthBar.appendChild(fill);
                el.appendChild(healthBar);
            }
            const fill = healthBar.querySelector('.unit-hp-fill');
            if (fill) {
                fill.style.width = `${hpRatio * 100}%`;
                fill.style.background = hpRatio > 0.5 ? '#05ffa1' : hpRatio > 0.25 ? '#fcee0a' : '#ff2a6d';
            }
        } else if (healthBar) {
            healthBar.remove();
        }

        // Name label (respects showLabels toggle)
        let nameLabel = el.querySelector('.unit-name');
        if (_state.showLabels) {
            if (!nameLabel) {
                nameLabel = document.createElement('div');
                nameLabel.className = 'unit-name';
                nameLabel.style.cssText = `
                    position: absolute; top: -14px; left: 50%; transform: translateX(-50%);
                    font-size: 8px; white-space: nowrap; color: ${color}; opacity: 0.8;
                    text-shadow: 0 0 3px #000, 0 0 6px #000;
                    max-width: 120px; overflow: hidden; text-overflow: ellipsis;
                `;
                el.appendChild(nameLabel);
            }
            const nameShortId = (unit.identity && unit.identity.short_id) ? `[${unit.identity.short_id}] ` : '';
            nameLabel.textContent = nameShortId + (unit.name || '');
        } else if (nameLabel) {
            nameLabel.remove();
        }
    }

    // --- Morale badge overlay (works in both 2D and 3D modes) ---
    // moraleState already declared above for style hash fingerprint
    let moraleBadge = el.querySelector('.morale-badge');
    if (moraleState) {
        if (!moraleBadge) {
            moraleBadge = document.createElement('div');
            moraleBadge.className = 'morale-badge';
            el.appendChild(moraleBadge);
        }
        moraleBadge.textContent = _MORALE_BADGE_TEXT[moraleState] || '';
        moraleBadge.style.color = _MORALE_BADGE_COLORS[moraleState] || '#fff';
        moraleBadge.style.display = 'block';
        moraleBadge.dataset.moraleState = moraleState;
    } else if (moraleBadge) {
        moraleBadge.style.display = 'none';
        delete moraleBadge.dataset.moraleState;
    }

    // --- Source indicator dot (real/graphling only — sim is default, no dot) ---
    // unitSource already declared above for style hash fingerprint
    let srcDot = el.querySelector('.unit-source-dot');
    if (unitSource !== 'sim') {
        if (!srcDot) {
            srcDot = document.createElement('div');
            srcDot.className = 'unit-source-dot';
            el.appendChild(srcDot);
        }
        const srcColor = unitSource === 'real' ? '#05ffa1' : unitSource === 'graphling' ? '#ff2a6d' : '#888';
        srcDot.style.cssText = `
            position: absolute; top: -2px; right: -2px;
            width: 5px; height: 5px; border-radius: 50%;
            background: ${srcColor};
            box-shadow: 0 0 4px ${srcColor};
            pointer-events: none;
        `;
    } else if (srcDot) {
        srcDot.remove();
    }
}

function _updateMarkerElement(marker, unit) {
    const el = marker.getElement();
    // Keep dataset.alliance in sync for allianceFilter
    const newAlliance = unit.alliance || 'unknown';
    if (el.dataset.alliance !== newAlliance) {
        el.dataset.alliance = newAlliance;
    }
    // Style the inner div, NOT the outer wrapper (which MapLibre positions via transform)
    // Cache the querySelector result on the element to avoid DOM lookup every tick
    if (!el._cachedInner) {
        el._cachedInner = el.querySelector('.tritium-unit-inner') || el;
    }
    const inner = el._cachedInner;
    _applyMarkerStyle(inner, unit);
    // No setRotation — labels stay screen-aligned for readability.
    // Heading is shown by the 3D model's orientation instead.

    // --- Morale state CSS classes on the outer wrapper ---
    const moraleState = _getMoraleState(unit.morale);
    const moraleClasses = ['unit-marker-suppressed', 'unit-marker-broken', 'unit-marker-emboldened'];
    for (const cls of moraleClasses) {
        el.classList.remove(cls);
    }
    if (moraleState) {
        el.classList.add('unit-marker-' + moraleState);
    }

    // --- Tooltip with morale state ---
    const name = unit.name || unit.id || '';
    const alliance = unit.alliance || 'unknown';
    const type = unit.type || 'unknown';
    let titleParts = [`${name} [${type}] (${alliance})`];
    if (moraleState) {
        titleParts.push(_MORALE_TOOLTIP_TEXT[moraleState]);
    }
    el.title = titleParts.join(' — ');

    // Thought bubble above marker
    _updateThoughtBubble(el, unit);
}

const _EMOTION_COLORS = {
    curious: '#00f0ff', afraid: '#fcee0a', angry: '#ff2a6d',
    happy: '#05ffa1', neutral: '#888888',
};

/**
 * Count how many visible thought bubbles are non-critical (and not the selected unit).
 * Critical and selected-unit bubbles are uncapped.
 */
function _countNonCriticalVisibleBubbles() {
    let count = 0;
    for (const uid of _state._visibleThoughtIds) {
        if (uid === _state.selectedUnitId) continue;
        const unit = typeof TritiumStore !== 'undefined' && TritiumStore.units
            ? TritiumStore.units.get(uid) : null;
        if (unit && unit.thoughtImportance === 'critical') continue;
        count++;
    }
    return count;
}

function _updateThoughtBubble(outerEl, unit) {
    let bubble = outerEl.querySelector('.thought-bubble');
    const now = Date.now();
    const unitId = unit.id || unit.target_id;

    // Determine if this thought should be visible.
    // A thought is visible if:
    //  1. showThoughts toggle is on AND
    //  2. The thought has not expired AND
    //  3. One of:
    //     a. This is the currently selected unit (click-to-view)
    //     b. The thought is critical importance (always shown)
    //     c. The thought is high importance AND we haven't hit the bubble cap
    const hasThought = unit.thoughtText && unit.thoughtExpires && unit.thoughtExpires > now;
    const isCritical = unit.thoughtImportance === 'critical';
    const isSelected = _state.selectedUnitId === unitId;

    // Remove from visible set if expired or hidden
    if (!hasThought || !_state.showThoughts) {
        if (bubble) bubble.style.display = 'none';
        _state._visibleThoughtIds.delete(unitId);
        return;
    }

    // Decide visibility: critical and selected always show.
    // Non-critical obey the max bubble cap.
    let shouldShow = false;
    if (isCritical || isSelected) {
        shouldShow = true;
    } else {
        // Check bubble cap (excluding critical and selected, which are uncapped)
        const nonCriticalCount = _countNonCriticalVisibleBubbles();
        if (_state._visibleThoughtIds.has(unitId)) {
            // Already visible — keep showing it
            shouldShow = true;
        } else if (nonCriticalCount < _state._maxThoughtBubbles) {
            shouldShow = true;
        }
        // else: cap reached, don't show this one
    }

    if (!shouldShow) {
        if (bubble) bubble.style.display = 'none';
        _state._visibleThoughtIds.delete(unitId);
        return;
    }

    _state._visibleThoughtIds.add(unitId);

    // Compute opacity (fade in/out)
    const duration = (unit.thoughtDuration || 5) * 1000;
    const created = unit.thoughtExpires - duration;
    const age = now - created;
    const timeLeft = unit.thoughtExpires - now;
    let alpha = 1.0;
    if (age < 300) alpha = age / 300;
    if (timeLeft < 1000) alpha = Math.min(alpha, timeLeft / 1000);
    alpha = Math.max(0, Math.min(1, alpha));

    const emotion = unit.thoughtEmotion || 'neutral';
    const borderColor = _EMOTION_COLORS[emotion] || '#888888';
    const text = unit.thoughtText;

    if (!bubble) {
        bubble = document.createElement('div');
        bubble.className = 'thought-bubble';
        outerEl.appendChild(bubble);
    }

    bubble.style.cssText = `
        position: absolute;
        bottom: 100%;
        left: 50%;
        transform: translateX(-50%);
        margin-bottom: 8px;
        padding: 6px 10px;
        background: rgba(18, 22, 36, 0.92);
        border: 2.5px solid ${borderColor};
        border-radius: 6px;
        box-shadow: 0 0 12px ${borderColor}88, 0 0 4px ${borderColor}44;
        font-family: 'JetBrains Mono', monospace;
        font-size: 11px;
        color: rgba(255, 255, 255, 0.95);
        max-width: 200px;
        white-space: normal;
        word-wrap: break-word;
        line-height: 1.3;
        pointer-events: none;
        z-index: 10;
        opacity: ${alpha};
        display: block;
    `;

    // Tail triangle (pure CSS, using ::after pseudo-element not possible in inline, so use a child)
    let tail = bubble.querySelector('.thought-tail');
    if (!tail) {
        tail = document.createElement('div');
        tail.className = 'thought-tail';
        bubble.appendChild(tail);
    }
    tail.style.cssText = `
        position: absolute;
        bottom: -8px;
        left: 50%;
        transform: translateX(-50%);
        width: 0; height: 0;
        border-left: 6px solid transparent;
        border-right: 6px solid transparent;
        border-top: 8px solid ${borderColor};
    `;

    // Content
    let content = bubble.querySelector('.thought-text');
    if (!content) {
        content = document.createElement('span');
        content.className = 'thought-text';
        bubble.insertBefore(content, tail);
    }
    content.textContent = text;
}

// ============================================================
// 3D Unit Models (Three.js procedural geometry)
// ============================================================

/**
 * Get Mercator scale factor (meters -> Mercator coord units).
 * Cached from geo center — all units in same neighborhood.
 */
/**
 * Return the meter scale for geometry sizing.
 * Since the reference transform is baked into the camera projection,
 * Three.js objects are in meter-space.  Return 1.0 so geometry values
 * represent real meters directly.
 */
function _getMeterScale() {
    return 1.0;
}

/**
 * Create a Three.js Group for a unit type.
 * Each type has a distinct procedural silhouette + holographic ground ring.
 */
function _build3DUnit(unitType, alliance, id) {
    if (typeof THREE === 'undefined') return null;
    const ms = _getMeterScale();
    if (!ms) return null;

    const colorHex = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const color = new THREE.Color(colorHex);
    const dark = new THREE.Color(colorHex).multiplyScalar(0.25);

    const group = new THREE.Group();
    group.name = 'unit-' + id;
    group.userData = { unitId: id, unitType: unitType, alliance: alliance, rotors: [] };

    const t = (unitType || '').toLowerCase();

    if (t.includes('heavy') && t.includes('turret')) {
        _addHeavyTurret3D(group, color, dark, ms);
    } else if (t.includes('missile') && t.includes('turret')) {
        _addMissileTurret3D(group, color, dark, ms);
    } else if (t.includes('turret')) {
        _addTurret3D(group, color, dark, ms);
    } else if (t.includes('scout') && t.includes('drone')) {
        _addDrone3D(group, color, dark, ms, 0.7);
    } else if (t.includes('drone')) {
        _addDrone3D(group, color, dark, ms, 1.0);
    } else if (t.includes('tank')) {
        _addTank3D(group, color, dark, ms);
    } else if (t.includes('apc')) {
        _addAPC3D(group, color, dark, ms);
    } else if (t.includes('rover')) {
        _addRover3D(group, color, dark, ms);
    } else if (t.includes('sensor')) {
        _addSensor3D(group, color, dark, ms);
    } else if (t.includes('camera')) {
        _addCamera3D(group, color, dark, ms);
    } else if (t.includes('person') || t.includes('hostile') || t.includes('leader')) {
        _addPerson3D(group, color, dark, ms);
    } else {
        _addGeneric3D(group, color, dark, ms);
    }

    // Holographic ground ring
    const ringR = t.includes('turret') || t.includes('tank') ? 16 : 12;
    _addGroundRing3D(group, color, ms, ringR);

    // Faint vertical light beam
    _addBeam3D(group, color, ms);

    // Scale up for dramatic visibility at neighborhood zoom levels
    const S = UNIT_3D.SCALE;
    group.scale.set(S, S, S);

    // Disable frustum culling on the entire unit group.
    // The MapLibre custom-layer projection matrix makes Three.js frustum
    // extraction unreliable at extreme pitch angles (especially pitch=0).
    group.frustumCulled = false;
    group.traverse(child => { child.frustumCulled = false; });

    return group;
}

// -- Turret: octagonal base + barrel + sensor dome --
function _addTurret3D(g, col, dk, ms) {
    const base = _mesh(
        new THREE.CylinderGeometry(ms * 8, ms * 9, ms * 6, 8),
        dk, col, 0.2
    );
    base.geometry.rotateX(Math.PI / 2);
    base.position.z = ms * 3;
    g.add(base);

    const barrel = _mesh(
        new THREE.CylinderGeometry(ms * 1.8, ms * 2.2, ms * 16, 6),
        new THREE.Color(0x555555), col, 0.1
    );
    barrel.geometry.rotateZ(Math.PI / 2);
    barrel.position.set(ms * 8, 0, ms * 5);
    g.add(barrel);

    const dome = _mesh(
        new THREE.SphereGeometry(ms * 3, 8, 6, 0, Math.PI * 2, 0, Math.PI / 2),
        col, col, 0.5, 0.7
    );
    dome.geometry.rotateX(-Math.PI / 2);
    dome.position.z = ms * 7;
    g.add(dome);
}

// -- Heavy Turret: larger base + twin barrels + armored cap --
function _addHeavyTurret3D(g, col, dk, ms) {
    const base = _mesh(
        new THREE.CylinderGeometry(ms * 11, ms * 12, ms * 7, 8),
        dk, col, 0.2
    );
    base.geometry.rotateX(Math.PI / 2);
    base.position.z = ms * 3.5;
    g.add(base);

    for (const dy of [-ms * 3.5, ms * 3.5]) {
        const barrel = _mesh(
            new THREE.CylinderGeometry(ms * 2, ms * 2.5, ms * 20, 6),
            new THREE.Color(0x555555), col, 0.1
        );
        barrel.geometry.rotateZ(Math.PI / 2);
        barrel.position.set(ms * 10, dy, ms * 5.5);
        g.add(barrel);
    }

    const cap = _mesh(
        new THREE.CylinderGeometry(ms * 7, ms * 9, ms * 3, 8),
        col, col, 0.35, 0.85
    );
    cap.geometry.rotateX(Math.PI / 2);
    cap.position.z = ms * 8.5;
    g.add(cap);
}

// -- Missile Turret: base + rectangular launch pod + missile tips --
function _addMissileTurret3D(g, col, dk, ms) {
    const base = _mesh(
        new THREE.CylinderGeometry(ms * 9, ms * 10, ms * 5, 8),
        dk, col, 0.2
    );
    base.geometry.rotateX(Math.PI / 2);
    base.position.z = ms * 2.5;
    g.add(base);

    const pod = _mesh(
        new THREE.BoxGeometry(ms * 18, ms * 9, ms * 7),
        new THREE.Color(0x444444), col, 0.15
    );
    pod.position.set(ms * 4, 0, ms * 7);
    g.add(pod);

    const red = new THREE.Color(0xff4444);
    for (let r = -1; r <= 1; r += 2) {
        for (let c = -1; c <= 1; c += 2) {
            const tip = _mesh(
                new THREE.ConeGeometry(ms * 1.2, ms * 4, 4),
                red, red, 0.6
            );
            tip.geometry.rotateZ(-Math.PI / 2);
            tip.position.set(ms * 14, r * ms * 2.5, ms * 7 + c * ms * 1.8);
            g.add(tip);
        }
    }
}

// -- Drone: flattened sphere body + 4 spinning rotor discs --
function _addDrone3D(g, col, dk, ms, scale) {
    const s = scale;
    const alt = ms * UNIT_3D.DRONE_ALT;

    const body = _mesh(
        new THREE.SphereGeometry(ms * 3.5 * s, 8, 6),
        dk, col, 0.35
    );
    body.scale.z = 0.45;
    body.position.z = alt;
    g.add(body);

    const armLen = ms * 7 * s;
    const angles = [Math.PI / 4, 3 * Math.PI / 4, 5 * Math.PI / 4, 7 * Math.PI / 4];
    for (const a of angles) {
        const ax = Math.cos(a) * armLen;
        const ay = Math.sin(a) * armLen;

        // Arm strut
        const arm = _mesh(
            new THREE.CylinderGeometry(ms * 0.6 * s, ms * 0.6 * s, armLen * 0.9, 4),
            new THREE.Color(0x333333), col, 0.05
        );
        arm.geometry.rotateZ(Math.PI / 2);
        arm.position.set(ax * 0.5, ay * 0.5, alt);
        arm.rotation.z = a;
        g.add(arm);

        // Rotor disc (spins in _animate3DUnits)
        const rotor = new THREE.Mesh(
            new THREE.CircleGeometry(ms * 4 * s, 12),
            new THREE.MeshBasicMaterial({
                color: col, transparent: true, opacity: 0.25,
                side: THREE.DoubleSide, depthWrite: false,
                blending: THREE.AdditiveBlending,
            })
        );
        rotor.position.set(ax, ay, alt + ms * 1.5);
        rotor.name = 'rotor';
        g.add(rotor);
        g.userData.rotors.push(rotor);
    }

    // Forward eye
    const eye = _mesh(
        new THREE.SphereGeometry(ms * 1.2 * s, 6, 4),
        new THREE.Color(0xffffff), col, 0.2, 0.9
    );
    eye.position.set(ms * 3.5 * s, 0, alt);
    g.add(eye);
}

// -- Tank: flat hull + turret box + main gun + treads --
function _addTank3D(g, col, dk, ms) {
    const hull = _mesh(new THREE.BoxGeometry(ms * 18, ms * 11, ms * 4), dk, col, 0.15);
    hull.position.z = ms * 2.5;
    g.add(hull);

    const turret = _mesh(new THREE.BoxGeometry(ms * 9, ms * 8, ms * 3.5), dk, col, 0.28);
    turret.position.set(-ms * 1, 0, ms * 6);
    g.add(turret);

    const barrel = _mesh(
        new THREE.CylinderGeometry(ms * 1.5, ms * 2, ms * 20, 6),
        new THREE.Color(0x555555), col, 0.1
    );
    barrel.geometry.rotateZ(Math.PI / 2);
    barrel.position.set(ms * 11, 0, ms * 6);
    g.add(barrel);

    for (const side of [-1, 1]) {
        const tread = _mesh(new THREE.BoxGeometry(ms * 20, ms * 2.5, ms * 3), new THREE.Color(0x1a1a1a), col, 0.03);
        tread.position.set(0, side * ms * 7, ms * 1.5);
        g.add(tread);
    }
}

// -- APC: armored box + small turret + wheels --
function _addAPC3D(g, col, dk, ms) {
    const body = _mesh(new THREE.BoxGeometry(ms * 20, ms * 11, ms * 7), dk, col, 0.18);
    body.position.z = ms * 4;
    g.add(body);

    const turret = _mesh(
        new THREE.CylinderGeometry(ms * 3.5, ms * 4, ms * 3, 6), dk, col, 0.25
    );
    turret.geometry.rotateX(Math.PI / 2);
    turret.position.set(ms * 3, 0, ms * 9);
    g.add(turret);

    const barrel = _mesh(
        new THREE.CylinderGeometry(ms * 0.9, ms * 1.2, ms * 12, 4),
        new THREE.Color(0x444444), col, 0.08
    );
    barrel.geometry.rotateZ(Math.PI / 2);
    barrel.position.set(ms * 10, 0, ms * 9);
    g.add(barrel);

    for (const xo of [-ms * 7, 0, ms * 7]) {
        for (const side of [-1, 1]) {
            const wheel = _mesh(
                new THREE.CylinderGeometry(ms * 2.5, ms * 2.5, ms * 1.8, 8),
                new THREE.Color(0x111111), col, 0.02
            );
            wheel.position.set(xo, side * ms * 6, ms * 0);
            g.add(wheel);
        }
    }
}

// -- Rover: compact box + sensor bar + gun + wheels --
function _addRover3D(g, col, dk, ms) {
    const body = _mesh(new THREE.BoxGeometry(ms * 14, ms * 9, ms * 5), dk, col, 0.28);
    body.position.z = ms * 3.5;
    g.add(body);

    const sensor = _mesh(new THREE.BoxGeometry(ms * 2, ms * 7, ms * 2.5), col, col, 0.5, 0.75);
    sensor.position.set(ms * 8, 0, ms * 5);
    g.add(sensor);

    const gun = _mesh(
        new THREE.CylinderGeometry(ms * 1, ms * 1.2, ms * 10, 4),
        new THREE.Color(0x444444), col, 0.1
    );
    gun.geometry.rotateZ(Math.PI / 2);
    gun.position.set(ms * 10, 0, ms * 6);
    g.add(gun);

    for (const xo of [-ms * 5, ms * 5]) {
        for (const side of [-1, 1]) {
            const wheel = _mesh(
                new THREE.CylinderGeometry(ms * 2.2, ms * 2.2, ms * 1.5, 8),
                new THREE.Color(0x111111), col, 0.02
            );
            wheel.position.set(xo, side * ms * 5, ms * 0);
            g.add(wheel);
        }
    }
}

// -- Person: cone body + sphere head + weapon --
function _addPerson3D(g, col, dk, ms) {
    const body = _mesh(new THREE.ConeGeometry(ms * 3.5, ms * 8, 6), dk, col, 0.35);
    body.geometry.rotateX(Math.PI); // point up
    body.position.z = ms * 4;
    g.add(body);

    const head = _mesh(new THREE.SphereGeometry(ms * 2.2, 8, 6), col, col, 0.45, 0.85);
    head.position.z = ms * 9.5;
    g.add(head);

    const weapon = _mesh(
        new THREE.CylinderGeometry(ms * 0.5, ms * 0.5, ms * 7, 3),
        new THREE.Color(0x444444), col, 0.05
    );
    weapon.geometry.rotateZ(Math.PI / 2);
    weapon.position.set(ms * 4, ms * 1.5, ms * 5);
    g.add(weapon);
}

// -- Sensor: post + glowing dome --
function _addSensor3D(g, col, dk, ms) {
    const post = _mesh(
        new THREE.CylinderGeometry(ms * 1.2, ms * 1.8, ms * 9, 6),
        new THREE.Color(0x333333), col, 0.05
    );
    post.geometry.rotateX(Math.PI / 2);
    post.position.z = ms * 4.5;
    g.add(post);

    const dome = _mesh(new THREE.SphereGeometry(ms * 3, 8, 8), col, col, 0.65, 0.8);
    dome.position.z = ms * 10;
    dome.name = 'sensorHead';
    g.add(dome);
}

// -- Camera: post + box camera + lens --
function _addCamera3D(g, col, dk, ms) {
    const post = _mesh(
        new THREE.CylinderGeometry(ms * 1, ms * 1.4, ms * 7, 4),
        new THREE.Color(0x333333), col, 0.05
    );
    post.geometry.rotateX(Math.PI / 2);
    post.position.z = ms * 3.5;
    g.add(post);

    const cam = _mesh(new THREE.BoxGeometry(ms * 5, ms * 3.5, ms * 3.5), dk, col, 0.3);
    cam.position.set(ms * 2, 0, ms * 8);
    g.add(cam);

    const lens = new THREE.Mesh(
        new THREE.CircleGeometry(ms * 1.2, 8),
        new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 })
    );
    lens.position.set(ms * 4.6, 0, ms * 8);
    lens.name = 'lens';
    g.add(lens);
}

// -- Generic fallback: glowing sphere --
function _addGeneric3D(g, col, dk, ms) {
    const sphere = _mesh(new THREE.SphereGeometry(ms * 5, 8, 6), dk, col, 0.35);
    sphere.position.z = ms * 5;
    g.add(sphere);
}

// -- Holographic ground ring --
function _addGroundRing3D(g, col, ms, radius) {
    const ring = new THREE.Mesh(
        new THREE.RingGeometry(ms * (radius - 2), ms * radius, 32),
        new THREE.MeshBasicMaterial({
            color: col, transparent: true, opacity: 0.3,
            side: THREE.DoubleSide, depthWrite: false,
            blending: THREE.AdditiveBlending,
        })
    );
    ring.position.z = ms * 0.3;
    ring.name = 'groundRing';
    g.add(ring);
}

// -- Faint vertical light beam --
function _addBeam3D(g, col, ms) {
    const beam = new THREE.Mesh(
        new THREE.CylinderGeometry(ms * 0.4, ms * 2.5, ms * 18, 6),
        new THREE.MeshBasicMaterial({
            color: col, transparent: true, opacity: 0.06,
            depthWrite: false, blending: THREE.AdditiveBlending,
        })
    );
    beam.geometry.rotateX(Math.PI / 2);
    beam.position.z = ms * 9;
    beam.name = 'lightBeam';
    g.add(beam);
}

/**
 * Helper: create a Phong mesh with strong emissive glow.
 * High emissiveIntensity ensures tactical models are bright at ALL view
 * angles including pitch=0 (top-down).  Without this, Phong shading makes
 * models too dark when viewed from directly above — the neon glow must
 * dominate ambient/diffuse so units are always visible.
 * polygonOffset prevents z-fighting against MapLibre tiles.
 */
function _mesh(geo, baseColor, emissive, emissiveIntensity, opacity) {
    // Enforce minimum emissive glow so models are bright at all pitch angles.
    // Many callers pass 0.1-0.2 which produces dim colors from above (pitch=0).
    // At 0.85, emissive dominates (neon-glow aesthetic) — the alliance color
    // is clearly visible from any camera angle.
    const ei = Math.max(emissiveIntensity || 0.7, 0.85);
    const mesh = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
        color: baseColor,
        emissive: emissive,
        emissiveIntensity: ei,
        transparent: true,
        opacity: opacity !== undefined ? opacity : 0.9,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: -1,
        polygonOffsetUnits: -1,
    }));
    mesh.frustumCulled = false;
    return mesh;
}

/**
 * Synchronize Three.js 3D meshes with the TritiumStore unit data.
 * Creates meshes for new units, updates position/heading, removes stale.
 *
 * Objects are positioned in game coordinates (meters from geoCenter).
 * The camera's projection matrix includes the reference transform that
 * maps these meter-space positions to Mercator → clip space.
 */
function _sync3DUnits() {
    if (!_state.threeScene || typeof THREE === 'undefined') return;

    const units = TritiumStore.units;
    const seenIds = new Set();

    units.forEach((unit, id) => {
        seenIds.add(id);
        const pos = unit.position || {};
        const gx = pos.x || 0;
        const gy = pos.y || 0;
        const heading = unit.heading || 0;
        const dead = unit.status === 'eliminated' || unit.status === 'neutralized';
        const type = (unit.type || '').toLowerCase();
        const alt = dead ? 0 : (type.includes('drone') ? UNIT_3D.DRONE_ALT : UNIT_3D.ALT);

        // Position in game meters (reference transform in camera handles
        // the conversion to Mercator + clip space)
        if (_state.unitMeshes[id]) {
            const group = _state.unitMeshes[id];
            group.position.set(gx, gy, alt);
            group.rotation.z = (heading - 90) * Math.PI / 180;

            // Death fade
            if (dead && !group.userData.dead) {
                group.userData.dead = true;
                group.traverse(child => {
                    if (child.material) {
                        child.material.opacity = Math.min(child.material.opacity, 0.12);
                        if (child.material.emissiveIntensity !== undefined) {
                            child.material.emissiveIntensity *= 0.2;
                        }
                    }
                });
            }
        } else {
            const alliance = unit.alliance || 'unknown';
            const group = _build3DUnit(unit.type || 'unknown', alliance, id);
            if (group) {
                group.position.set(gx, gy, alt);
                group.rotation.z = (heading - 90) * Math.PI / 180;
                _state.threeRoot.add(group);
                _state.unitMeshes[id] = group;
            }
        }
    });

    // Remove meshes for deleted units
    for (const id of Object.keys(_state.unitMeshes)) {
        if (!seenIds.has(id)) {
            _dispose3DUnit(_state.unitMeshes[id]);
            delete _state.unitMeshes[id];
        }
    }

    // Keep repaint loop alive for 3D animations
    if (Object.keys(_state.unitMeshes).length > 0) {
        _ensureRepaintLoop();
    }
}

/**
 * Per-frame animation for 3D unit meshes.
 * Spins drone rotors, pulses ground rings and beams.
 */
function _animate3DUnits(now) {
    const t = now * 0.001;

    for (const group of Object.values(_state.unitMeshes)) {
        if (group.userData.dead) continue;

        // Drone rotors
        for (const rotor of group.userData.rotors) {
            rotor.rotation.z = t * UNIT_3D.ROTOR_SPEED;
        }

        // Pulse ground ring
        const ring = group.getObjectByName('groundRing');
        if (ring) {
            ring.material.opacity = 0.2 + 0.12 * Math.sin(t * UNIT_3D.RING_PULSE * Math.PI * 2);
        }

        // Pulse light beam
        const beam = group.getObjectByName('lightBeam');
        if (beam) {
            beam.material.opacity = 0.04 + 0.03 * Math.sin(t * UNIT_3D.BEAM_PULSE);
        }

        // Pulse sensor dome
        const sensor = group.getObjectByName('sensorHead');
        if (sensor) {
            sensor.material.emissiveIntensity = 0.4 + 0.25 * Math.sin(t * 3);
        }
    }
}

/**
 * Dispose all children of a 3D unit group.
 */
function _dispose3DUnit(group) {
    if (!group) return;
    const parent = _state.threeRoot || _state.threeScene;
    if (parent) parent.remove(group);
    group.traverse(child => {
        if (child.geometry) child.geometry.dispose();
        if (child.material) child.material.dispose();
    });
}

// ============================================================
// GIS Data Layers (Dublin, CA government data)
// ============================================================

async function _loadGeoLayers() {
    // Fetch the layer catalog
    try {
        const resp = await fetch('/api/geo/layers/catalog');
        if (!resp.ok) return;
        const catalog = await resp.json();
        console.log(`[MAP-ML] Layer catalog: ${catalog.length} layers available`);

        // Load each layer
        for (const layer of catalog) {
            _loadGeoLayer(layer);
        }
    } catch (e) {
        console.warn('[MAP-ML] Layer catalog fetch failed:', e.message);
    }
}

async function _loadGeoLayer(layerMeta) {
    const { id, name, type: geomType, color, endpoint } = layerMeta;
    try {
        // Append geo center coordinates if the endpoint requires them
        const sep = endpoint.includes('?') ? '&' : '?';
        const url = _state.geoCenter
            ? `${endpoint}${sep}lat=${_state.geoCenter.lat}&lng=${_state.geoCenter.lng}`
            : endpoint;
        const resp = await fetch(url);
        if (!resp.ok) return;
        const geojson = await resp.json();
        if (!geojson.features || geojson.features.length === 0) return;

        const sourceId = `geo-${id}`;
        const layerId = `geo-${id}-layer`;

        // Add GeoJSON source
        _state.map.addSource(sourceId, {
            type: 'geojson',
            data: geojson,
        });

        // Add layer based on geometry type
        if (geomType === 'point') {
            _state.map.addLayer({
                id: layerId,
                type: 'circle',
                source: sourceId,
                minzoom: _pointMinZoom(id),
                paint: {
                    'circle-radius': _pointRadius(id),
                    'circle-color': color,
                    'circle-opacity': 0.7,
                    'circle-stroke-color': color,
                    'circle-stroke-width': 1,
                    'circle-stroke-opacity': 0.9,
                },
                layout: { 'visibility': _state.showGeoLayers ? 'visible' : 'none' },
            });
        } else if (geomType === 'line') {
            _state.map.addLayer({
                id: layerId,
                type: 'line',
                source: sourceId,
                paint: {
                    'line-color': color,
                    'line-width': _lineWidth(id),
                    'line-opacity': _lineOpacity(id),
                },
                layout: { 'visibility': _state.showGeoLayers ? 'visible' : 'none' },
            });
        } else if (geomType === 'polygon') {
            // Fill
            _state.map.addLayer({
                id: `${layerId}-fill`,
                type: 'fill',
                source: sourceId,
                paint: {
                    'fill-color': color,
                    'fill-opacity': 0.15,
                },
                layout: { 'visibility': _state.showGeoLayers ? 'visible' : 'none' },
            });
            // Outline
            _state.map.addLayer({
                id: `${layerId}-outline`,
                type: 'line',
                source: sourceId,
                paint: {
                    'line-color': color,
                    'line-width': 1.5,
                    'line-opacity': 0.6,
                },
                layout: { 'visibility': _state.showGeoLayers ? 'visible' : 'none' },
            });
            _state.geoLayerIds.push(`${layerId}-fill`, `${layerId}-outline`);
            console.log(`[MAP-ML] Layer: ${name} (${geojson.features.length} features)`);
            return;
        }

        _state.geoLayerIds.push(layerId);
        console.log(`[MAP-ML] Layer: ${name} (${geojson.features.length} features)`);

        // Tooltip on hover for GIS features
        _state.map.on('mouseenter', layerId, () => {
            _state.map.getCanvas().style.cursor = 'pointer';
        });
        _state.map.on('mouseleave', layerId, () => {
            _state.map.getCanvas().style.cursor = '';
        });
        _state.map.on('click', layerId, (e) => {
            const props = e.features?.[0]?.properties || {};
            const lines = [`<strong>${name}</strong>`];
            for (const [k, v] of Object.entries(props)) {
                if (k.startsWith('_') || k === 'id') continue;
                lines.push(`<span style="color:var(--text-ghost)">${k}:</span> ${v}`);
            }
            new maplibregl.Popup({ closeButton: true, maxWidth: '260px' })
                .setLngLat(e.lngLat)
                .setHTML(`<div style="font-family:var(--font-mono);font-size:0.65rem;line-height:1.5;color:var(--text)">${lines.join('<br>')}</div>`)
                .addTo(_state.map);
        });

    } catch (e) {
        console.warn(`[MAP-ML] Layer ${id} failed:`, e.message);
    }
}

function _pointMinZoom(layerId) {
    // High-density layers only visible when zoomed in
    switch (layerId) {
        case 'street-lights': return 17;  // 5000+ points, only show close-up
        case 'trees': return 16;          // 1000+ points
        case 'traffic-signals': return 14;
        case 'water-towers': return 12;   // sparse, show early
        case 'schools': return 12;
        case 'fire-stations': return 12;
        default: return 14;
    }
}

function _pointRadius(layerId) {
    switch (layerId) {
        case 'traffic-signals': return 4;
        case 'water-towers': return 5;
        case 'street-lights': return 2;
        case 'trees': return 2;
        case 'schools': return 6;
        case 'fire-stations': return 6;
        default: return 3;
    }
}

function _lineWidth(layerId) {
    switch (layerId) {
        case 'power-lines': return 2;
        case 'telecom-lines': return 1.2;
        case 'waterways': return 1.5;
        case 'streams': return 1;
        case 'water': return 1.2;
        default: return 1.5;
    }
}

function _lineOpacity(layerId) {
    switch (layerId) {
        case 'power-lines': return 0.6;
        case 'telecom-lines': return 0.4;
        case 'waterways': return 0.5;
        case 'streams': return 0.25;
        case 'water': return 0.25;
        default: return 0.7;
    }
}

// ============================================================
// Combat Effects System (Three.js on MapLibre)
// ============================================================

/**
 * Convert game coordinates to a position object for Three.js placement.
 * Since the camera projection includes the reference transform, objects
 * are positioned directly in game meters (x=east, y=north, z=up).
 * Returns an object matching the shape previously expected (x, y, z)
 * plus meterInMercatorCoordinateUnits() for backward compat.
 */
function _gameToMercator(gx, gy, altMeters) {
    return {
        x: gx,
        y: gy,
        z: altMeters || 0,
        meterInMercatorCoordinateUnits() { return 1.0; },
    };
}

/**
 * Initialize combat effects system.
 * Subscribes to EventBus combat events and starts the rendering pipeline.
 */
function _initEffects() {
    // Combat events
    EventBus.on('combat:projectile', _onCombatProjectile);
    EventBus.on('combat:hit', _onCombatHit);
    EventBus.on('combat:elimination', _onCombatElimination);
    EventBus.on('combat:streak', _onCombatStreak);

    // Game flow events
    EventBus.on('game:wave_start', _onWaveStart);
    EventBus.on('game:wave_complete', _onWaveComplete);
    EventBus.on('game:state', _onGameStateChange);

    _injectFxCss();
    console.log('[MAP-ML] Combat effects system initialized (FX + audio bridge + kill feed)');
}

// ------ Game flow overlays ------

function _onWaveStart(data) {
    const wave = data.wave || data.wave_number || '?';
    const name = data.wave_name || '';
    const hostiles = data.hostile_count || '?';
    const direction = data.spawn_direction || 'random';

    // Track wave direction for directional threat arrows
    _state._waveDirection = direction;
    // Clear between-wave countdown
    _state._nextWaveCountdown = 0;
    _state._nextWaveCountdownStart = 0;
    _state._nextWaveDirection = null;

    // Show directional threat indicators on map edges
    _showDirectionalThreatArrows(direction);

    _showMapBanner(
        'WAVE ' + wave,
        name ? name + ' // ' + hostiles + ' hostiles' : hostiles + ' hostiles incoming',
        '#ff2a6d',
        3500
    );
    _triggerScreenFlash('#ff2a6d', 200);
    _triggerScanLine('#ff2a6d');
}

function _onWaveComplete(data) {
    const wave = data.wave || data.wave_number || '?';
    const bonus = data.score_bonus || 0;

    _showMapBanner(
        'WAVE ' + wave + ' CLEAR',
        bonus ? '+' + bonus + ' points' : 'Area secured',
        '#05ffa1',
        3000
    );

    // Clear current wave direction arrows
    _state._waveDirection = null;
    _removeDirectionalThreatArrows();

    // Start countdown to next wave if info available
    const delay = data.next_wave_delay || 5;
    if (data.next_wave_name || data.next_hostile_count) {
        _state._nextWaveCountdown = delay;
        _state._nextWaveCountdownStart = performance.now();
        _state._nextWaveName = data.next_wave_name || '';
        _state._nextHostileCount = data.next_hostile_count || 0;
        _state._nextWaveDirection = data.next_spawn_direction || 'random';

        // Show preview direction arrows for next wave after banner clears
        setTimeout(() => {
            if (_state._nextWaveDirection) {
                _showDirectionalThreatArrows(_state._nextWaveDirection, true);
            }
        }, 3200);
    }

    // Fetch and render combat zone heatmap after wave completes
    _fetchAndRenderHeatmap();
}

function _onGameStateChange(data) {
    if (data.state === 'countdown') {
        _startCountdownOverlay(data.countdown || 5);
        // Clear heatmap when a new game starts
        _clearHeatmap();
    } else if (data.state === 'active') {
        // Start polling hostile objectives during active game
        _startHostileObjectivePoll();
        _showBattleVignette(true);
        if (!_state.battleStartTime) _state.battleStartTime = performance.now();
    } else if (data.state === 'victory') {
        _showMapBanner('VICTORY', 'All waves cleared', '#05ffa1', 8000);
        _triggerScreenFlash('#05ffa1', 600);
        _showGameOverOverlay('victory', data);
        _stopHostileObjectivePoll();
        _showBattleVignette(false);
        _removeDirectionalThreatArrows();
    } else if (data.state === 'defeat') {
        _showMapBanner('DEFEAT', 'Perimeter breached', '#ff2a6d', 8000);
        _triggerScreenFlash('#ff2a6d', 600);
        _triggerScreenShake(500, 8);
        _showGameOverOverlay('defeat', data);
        _stopHostileObjectivePoll();
        _showBattleVignette(false);
        _removeDirectionalThreatArrows();
    } else if (data.state === 'setup') {
        // Reset after a game — clear game-over overlay but keep effects initialized
        _removeGameOverOverlay();
        _showBattleVignette(false);
        _removeDirectionalThreatArrows();
        _state.battleStartTime = 0;
        _state._waveDirection = null;
        _state._nextWaveCountdown = 0;
        _state._nextWaveCountdownStart = 0;
    } else if (data.state === 'idle') {
        _stopHostileObjectivePoll();
        _showBattleVignette(false);
        _removeDirectionalThreatArrows();
        _removeGameOverOverlay();
        _state.battleStartTime = 0;
        _state._waveDirection = null;
        _state._nextWaveCountdown = 0;
        _state._nextWaveCountdownStart = 0;
        _clearHazardZones();
        _clearHostileObjectives();
        _clearCrowdDensity();
        _clearCoverPoints();
        _clearUnitSignals();
        if (_state._hostileIntelEl) {
            _state._hostileIntelEl.style.display = 'none';
        }
    }
}

/**
 * Show a banner overlay on the map (wave announcements, game state).
 */
function _showMapBanner(title, subtitle, color, durationMs) {
    if (!_state.showBanners) return;
    const container = _state.container;
    if (!container) return;

    let banner = container.querySelector('.fx-map-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.className = 'fx-map-banner';
        banner.style.cssText = [
            'position:absolute; top:25%; left:50%; transform:translate(-50%,-50%);',
            'z-index:150; pointer-events:none; text-align:center;',
        ].join('');
        container.appendChild(banner);
    }

    banner.innerHTML = [
        '<div style="',
        'font-family:Inter,sans-serif; font-weight:900; font-size:36px;',
        'letter-spacing:4px; text-transform:uppercase; color:' + color + ';',
        'text-shadow: 0 0 15px ' + color + ', 0 0 30px ' + color + '66, 0 2px 6px #000;',
        'animation: fx-streak-pop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;',
        '">' + _esc(title) + '</div>',
        '<div style="',
        'font-family:JetBrains Mono,monospace; font-size:14px;',
        'color:#aaa; letter-spacing:2px; margin-top:6px;',
        'animation: fx-streak-pop 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;',
        '">' + _esc(subtitle) + '</div>',
    ].join('');

    clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(() => {
        banner.style.animation = 'fx-vignette-flash 0.8s ease-out forwards';
        setTimeout(() => { banner.innerHTML = ''; banner.style.animation = ''; }, 800);
    }, durationMs);
}

/**
 * Show countdown numbers (5, 4, 3, 2, 1, GO!) on the map.
 */
function _startCountdownOverlay(seconds) {
    if (!_state.showBanners) return;
    const container = _state.container;
    if (!container) return;

    let cdEl = container.querySelector('.fx-countdown');
    if (!cdEl) {
        cdEl = document.createElement('div');
        cdEl.className = 'fx-countdown';
        cdEl.style.cssText = [
            'position:absolute; top:40%; left:50%; transform:translate(-50%,-50%);',
            'z-index:250; pointer-events:none; text-align:center;',
            'font-family:Inter,sans-serif; font-weight:900; font-size:72px;',
            'color:#00f0ff; letter-spacing:8px;',
            'text-shadow: 0 0 30px #00f0ff, 0 0 60px #00f0ff66, 0 4px 10px #000;',
        ].join('');
        container.appendChild(cdEl);
    }

    let count = seconds;
    const tick = () => {
        if (count <= 0) {
            cdEl.textContent = 'GO!';
            cdEl.style.color = '#05ffa1';
            cdEl.style.textShadow = '0 0 30px #05ffa1, 0 0 60px #05ffa166';
            cdEl.style.animation = 'fx-flash 0.8s ease-out forwards';
            _triggerScreenFlash('#05ffa1', 300);
            setTimeout(() => { cdEl.remove(); }, 900);
            return;
        }
        cdEl.textContent = count;
        cdEl.style.animation = 'none';
        cdEl.offsetHeight;
        cdEl.style.animation = 'fx-streak-pop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards';
        count--;
        setTimeout(tick, 1000);
    };
    tick();
}

// ------ Weapon visual config ------

const _WEAPON_VFX = {
    nerf_missile_launcher: {
        color: 0xff2a6d, glowColor: 0xff6644,
        headR: 10, glowR: 25, duration: 700, flashR: 18,
        trail: true, smoke: true, screenShake: true,
    },
    nerf_tank_cannon: {
        color: 0xffcc00, glowColor: 0xff8800,
        headR: 9, glowR: 22, duration: 550, flashR: 16,
        trail: true, smoke: false, screenShake: true,
    },
    nerf_heavy_turret: {
        color: 0x00f0ff, glowColor: 0x0088ff,
        headR: 8, glowR: 20, duration: 450, flashR: 14,
        trail: true, smoke: false, screenShake: false, twin: true,
    },
    nerf_turret_gun: {
        color: 0x05ffa1, glowColor: 0x00cc88,
        headR: 7, glowR: 18, duration: 500, flashR: 12,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_cannon: {
        color: 0xffa500, glowColor: 0xff8800,
        headR: 7, glowR: 18, duration: 500, flashR: 12,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_apc_mg: {
        color: 0xffa500, glowColor: 0xff6600,
        headR: 5, glowR: 14, duration: 350, flashR: 10,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_dart_gun: {
        color: 0x00f0ff, glowColor: 0x0088ff,
        headR: 5, glowR: 13, duration: 400, flashR: 9,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_scout_gun: {
        color: 0x00ccff, glowColor: 0x0066cc,
        headR: 4, glowR: 11, duration: 350, flashR: 8,
        trail: false, smoke: false, screenShake: false,
    },
    nerf_pistol: {
        color: 0xff2a6d, glowColor: 0xcc0044,
        headR: 5, glowR: 13, duration: 450, flashR: 9,
        trail: true, smoke: false, screenShake: false,
    },
};

function _getWeaponVFX(projectileType) {
    return _WEAPON_VFX[projectileType] || {
        color: 0xffa500, glowColor: 0xff8800,
        headR: FX.TRACER_HEAD_R, glowR: FX.TRACER_GLOW_R,
        duration: FX.TRACER_DURATION, flashR: FX.FLASH_R,
        trail: true, smoke: false, screenShake: false,
    };
}

// ------ Projectile tracer (source → target) ------

function _onCombatProjectile(data) {
    // Track recently-fired units for combat ring indicator + engagement lines
    if (data.source_id) {
        _state.recentlyFired[data.source_id] = {
            time: performance.now(),
            targetId: data.target_id || null,
        };
    }

    if (!_state.threeScene || !_state.map) return;
    if (!_state.showTracers) return;

    // Resolve source position: prefer the live unit position from
    // TritiumStore so the flash aligns exactly with the rendered mesh.
    // Fall back to event data if the unit is not (yet) in the store.
    let srcX, srcY, tgtX, tgtY;
    const srcUnit = data.source_id ? TritiumStore.units.get(data.source_id) : null;
    if (srcUnit && srcUnit.position) {
        srcX = srcUnit.position.x || 0;
        srcY = srcUnit.position.y || 0;
    } else {
        const src = data.source_pos || {};
        srcX = src.x || 0;
        srcY = src.y || 0;
    }
    const tgtUnit = data.target_id ? TritiumStore.units.get(data.target_id) : null;
    if (tgtUnit && tgtUnit.position) {
        tgtX = tgtUnit.position.x || 0;
        tgtY = tgtUnit.position.y || 0;
    } else {
        const tgt = data.target_pos || {};
        tgtX = tgt.x || 0;
        tgtY = tgt.y || 0;
    }

    const srcMc = _gameToMercator(srcX, srcY, FX.ALT);
    const tgtMc = _gameToMercator(tgtX, tgtY, FX.ALT);
    const ms = srcMc.meterInMercatorCoordinateUnits();

    const ptype = data.projectile_type || 'nerf_dart';
    const vfx = _getWeaponVFX(ptype);

    const srcV = new THREE.Vector3(srcMc.x, srcMc.y, srcMc.z || 0);
    const tgtV = new THREE.Vector3(tgtMc.x, tgtMc.y, tgtMc.z || 0);

    // Spawn tracer(s) — heavy turret fires twin bolts
    const offsets = vfx.twin ? [-ms * 1.5, ms * 1.5] : [0];
    for (const offset of offsets) {
        const oSrc = srcV.clone();
        const oTgt = tgtV.clone();
        if (offset !== 0) {
            // Perpendicular offset for twin shots
            const dx = tgtV.x - srcV.x;
            const dy = tgtV.y - srcV.y;
            const len = Math.hypot(dx, dy) || 1;
            oSrc.x += (-dy / len) * offset;
            oSrc.y += (dx / len) * offset;
            oTgt.x += (-dy / len) * offset;
            oTgt.y += (dx / len) * offset;
        }

        // Tracer head
        const headGeo = new THREE.SphereGeometry(ms * vfx.headR, 6, 6);
        const headMat = new THREE.MeshBasicMaterial({
            color: vfx.color, transparent: true, opacity: 0.95,
            depthWrite: false, blending: THREE.AdditiveBlending,
        });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.copy(oSrc);

        // Outer glow
        const glowGeo = new THREE.SphereGeometry(ms * vfx.glowR, 6, 6);
        const glowMat = new THREE.MeshBasicMaterial({
            color: vfx.glowColor, transparent: true, opacity: 0.6,
            depthWrite: false, blending: THREE.AdditiveBlending,
        });
        const glow = new THREE.Mesh(glowGeo, glowMat);
        glow.position.copy(oSrc);

        // Trail line
        const trailGeo = new THREE.BufferGeometry().setFromPoints([oSrc.clone(), oSrc.clone()]);
        const trailMat = new THREE.LineBasicMaterial({
            color: vfx.color, transparent: true,
            opacity: vfx.trail ? 0.6 : 0.3, depthWrite: false,
        });
        const trail = new THREE.Line(trailGeo, trailMat);

        _state.threeEffectsRoot.add(head);
        _state.threeEffectsRoot.add(glow);
        _state.threeEffectsRoot.add(trail);

        const fx = {
            type: 'tracer',
            meshes: [head, glow, trail],
            source: oSrc, target: oTgt,
            startTime: performance.now(),
            duration: vfx.duration,
        };

        // Smoke trail particles for missiles/heavy shots
        if (vfx.smoke) {
            fx.smoke = true;
            fx.smokeTimer = 0;
        }
        _state.effects.push(fx);
    }

    // Muzzle flash
    _spawnFlash(srcMc, ms, 0xffffff, vfx.flashR, FX.FLASH_DURATION);

    // Screen shake for heavy weapons
    if (vfx.screenShake) {
        _triggerScreenShake(200, 3);
    }

    // DOM muzzle flash
    _spawnDomFlash(srcX, srcY, vfx.color, 150);

    _ensureRepaintLoop();
}

// ------ Impact sparks (hit position) ------

function _onCombatHit(data) {
    if (!_state.map) return;

    const ptype = data.projectile_type || 'nerf_dart';
    const vfx = _getWeaponVFX(ptype);
    const dmg = data.damage || 0;

    // Resolve hit position: prefer TritiumStore target position so
    // the effect aligns with the rendered mesh, fall back to event data.
    let px, py;
    const hitUnit = data.target_id ? TritiumStore.units.get(data.target_id) : null;
    if (hitUnit && hitUnit.position) {
        px = hitUnit.position.x || 0;
        py = hitUnit.position.y || 0;
    } else {
        const pos = data.position || {};
        px = pos.x || 0;
        py = pos.y || 0;
    }

    if (_state.threeScene && _state.showHitFlashes) {
        const mc = _gameToMercator(px || 0, py || 0, FX.ALT);
        const ms = mc.meterInMercatorCoordinateUnits();

        // Impact flash — color matches weapon
        const hitColor = vfx.color;
        const hitR = Math.min(FX.HIT_R * 2, FX.HIT_R + dmg * 0.5);
        _spawnFlash(mc, ms, hitColor, hitR, FX.HIT_DURATION);

        // Particle count scales with damage
        if (_state.showParticles) {
            const pCount = Math.min(20, 6 + Math.floor(dmg / 5));
            _spawnParticleBurst(mc, ms, hitColor, pCount, FX.PARTICLE_DURATION * 0.6);
        }

        // Heavy weapons get extra orange sparks
        if (vfx.screenShake) {
            if (_state.showParticles) _spawnParticleBurst(mc, ms, 0xffa500, 8, FX.PARTICLE_DURATION * 0.5);
            _triggerScreenShake(150, 2);
        }

        _ensureRepaintLoop();
    }

    // Floating damage number
    if (dmg > 0) {
        const dmgColor = dmg >= 30 ? '#ff2a6d' : dmg >= 15 ? '#ffa500' : '#fcee0a';
        _spawnFloatingText(px || 0, py || 0, '-' + dmg, dmgColor, 1200);
    }

    // DOM hit flash
    _spawnDomFlash(px || 0, py || 0, vfx.color, 350);

    // Brief vignette pulse when a friendly takes heavy damage
    if (hitUnit && hitUnit.alliance === 'friendly' && dmg >= 20) {
        _pulseVignetteDamage();
    }
}

// ------ Elimination explosion ------

function _onCombatElimination(data) {
    if (!_state.map) return;

    // Resolve position from TritiumStore for pixel-perfect alignment
    // with the rendered unit mesh, falling back to event data.
    let pos;
    const elimUnit = data.target_id ? TritiumStore.units.get(data.target_id) : null;
    if (elimUnit && elimUnit.position) {
        pos = elimUnit.position;
    } else {
        pos = data.position || {};
    }
    const targetName = data.target_name || data.victim_name || '???';
    const killerName = data.interceptor_name || data.killer_name || 'SYSTEM';
    const method = data.method || 'nerf_dart';
    const methodVfx = _getWeaponVFX(method);
    // Heavy weapon kills get bigger explosions
    const isHeavyKill = methodVfx.screenShake;
    const sizeMult = isHeavyKill ? 1.5 : 1.0;

    if (_state.threeScene && _state.showExplosions) {
        const mc = _gameToMercator(pos.x || 0, pos.y || 0, FX.ALT * 0.5);
        const ms = mc.meterInMercatorCoordinateUnits();

        // Expanding explosion ring — scaled by kill method
        const rStart = FX.ELIM_R_START * sizeMult;
        const ringGeo = new THREE.RingGeometry(
            ms * rStart * 0.8, ms * rStart * 1.2, 32
        );
        const ringMat = new THREE.MeshBasicMaterial({
            color: methodVfx.color,
            transparent: true, opacity: 0.8,
            side: THREE.DoubleSide, depthWrite: false,
            blending: THREE.AdditiveBlending,
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.position.set(mc.x, mc.y, mc.z || 0);

        // Second ring (orange, slightly delayed)
        const ring2Geo = new THREE.RingGeometry(
            ms * rStart * 0.5, ms * rStart * 0.9, 32
        );
        const ring2Mat = new THREE.MeshBasicMaterial({
            color: 0xffa500, transparent: true, opacity: 0.6,
            side: THREE.DoubleSide, depthWrite: false,
            blending: THREE.AdditiveBlending,
        });
        const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
        ring2.position.set(mc.x, mc.y, mc.z || 0);

        // Core flash — bright white burst
        const coreGeo = new THREE.SphereGeometry(ms * 5 * sizeMult, 8, 8);
        const coreMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.95,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        });
        const core = new THREE.Mesh(coreGeo, coreMat);
        core.position.set(mc.x, mc.y, (mc.z || 0) + ms * 2);

        _state.threeEffectsRoot.add(ring);
        _state.threeEffectsRoot.add(ring2);
        _state.threeEffectsRoot.add(core);

        _state.effects.push({
            type: 'explosion',
            meshes: [ring, ring2, core],
            startTime: performance.now(),
            duration: FX.ELIM_DURATION,
            ms: ms,
        });

        // Scatter particles — weapon color + orange + yellow, scaled
        if (_state.showParticles) {
            const pBase = Math.floor(FX.PARTICLE_COUNT * sizeMult);
            _spawnParticleBurst(mc, ms, methodVfx.color, pBase, FX.PARTICLE_DURATION);
            _spawnParticleBurst(mc, ms, 0xffa500, Math.floor(12 * sizeMult), FX.PARTICLE_DURATION * 0.8);
            _spawnParticleBurst(mc, ms, 0xfcee0a, Math.floor(8 * sizeMult), FX.PARTICLE_DURATION * 0.6);
        }

        // Heavy kills spawn ground scorch mark (persistent dark circle)
        if (isHeavyKill) {
            const scorchGeo = new THREE.CircleGeometry(ms * 8, 16);
            const scorchMat = new THREE.MeshBasicMaterial({
                color: 0x111111, transparent: true, opacity: 0.3,
                side: THREE.DoubleSide, depthWrite: false,
            });
            const scorch = new THREE.Mesh(scorchGeo, scorchMat);
            scorch.position.set(mc.x, mc.y, (mc.z || 0) + ms * 0.2);
            _state.threeEffectsRoot.add(scorch);
            // Fade over 15 seconds
            _state.effects.push({
                type: 'flash', meshes: [scorch],
                startTime: performance.now(), duration: 15000,
            });
        }

        _ensureRepaintLoop();
    }

    // DOM explosion overlay (dramatic, multi-layered)
    _spawnDomExplosion(pos.x || 0, pos.y || 0, FX.ELIM_DURATION);

    // Screen shake — bigger for heavy kills
    if (isHeavyKill) {
        _triggerScreenShake(500, 10);
    }

    // Floating "ELIMINATED" text rising from the explosion
    _spawnFloatingText(pos.x || 0, pos.y || 0, 'ELIMINATED', '#ff2a6d', 2000);

    // Score popup slightly offset
    _spawnFloatingText(pos.x || 0, (pos.y || 0) + 5, '+100', '#fcee0a', 1500);

    // Kill feed entry with weapon method
    const methodLabel = _weaponDisplayName(method);
    _addKillFeedEntry(killerName, targetName, methodLabel);
}

// ------ Elimination streak (dramatic center announcement) ------

function _onCombatStreak(data) {
    if (!_state.map) return;

    const streak = data.streak || 3;
    const streakNames = { 3: 'KILLING SPREE', 5: 'RAMPAGE', 7: 'DOMINATING', 10: 'GODLIKE' };
    const streakName = streakNames[streak] || (streak + 'x STREAK');
    const color = streak >= 10 ? '#fcee0a' : streak >= 7 ? '#ff2a6d' : '#00f0ff';

    if (_state.threeScene && _state.showHitFlashes) {
        const center = _state.map.getCenter();
        const mc = maplibregl.MercatorCoordinate.fromLngLat(
            [center.lng, center.lat], FX.ALT * 2
        );
        const ms = mc.meterInMercatorCoordinateUnits();
        const radius = 50 + streak * 15;
        const threeColor = streak >= 10 ? 0xfcee0a : streak >= 7 ? 0xff2a6d : 0x00f0ff;
        _spawnFlash(mc, ms, threeColor, radius, 600);
        _ensureRepaintLoop();
    }

    // Big center streak banner
    _showStreakBanner(streakName, color, 3000);

    // Scan line sweep
    _triggerScanLine(color);

    // Screen shake (bigger for higher streaks)
    _triggerScreenShake(400, 4 + streak);
}

/**
 * Show a large streak announcement banner in the center of the map.
 */
function _showStreakBanner(text, color, durationMs) {
    if (!_state.showBanners) return;
    const container = _state.container;
    if (!container) return;

    let banner = container.querySelector('.fx-streak-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.className = 'fx-streak-banner';
        banner.style.cssText = [
            'position:absolute; top:35%; left:50%; transform:translate(-50%,-50%);',
            'z-index:200; pointer-events:none; text-align:center;',
        ].join('');
        container.appendChild(banner);
    }

    banner.innerHTML = '<div style="' + [
        'font-family:Inter,sans-serif; font-weight:900;',
        'font-size:48px; letter-spacing:6px; text-transform:uppercase;',
        'color:' + color + ';',
        'text-shadow: 0 0 20px ' + color + ', 0 0 40px ' + color + '88, 0 0 80px ' + color + '44, 0 4px 8px #000;',
        'animation: fx-streak-pop 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;',
    ].join('') + '">' + _esc(text) + '</div>';

    // Inject streak pop animation if not present
    if (!document.getElementById('tritium-fx-streak-css')) {
        const s = document.createElement('style');
        s.id = 'tritium-fx-streak-css';
        s.textContent = [
            '@keyframes fx-streak-pop {',
            '  0% { opacity: 0; transform: scale(0.3); }',
            '  50% { opacity: 1; transform: scale(1.1); }',
            '  100% { opacity: 1; transform: scale(1); }',
            '}',
        ].join('\n');
        document.head.appendChild(s);
    }

    clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(() => {
        banner.style.animation = 'fx-vignette-flash 0.5s ease-out forwards';
        setTimeout(() => { banner.innerHTML = ''; }, 500);
    }, durationMs);
}

// ------ Shared helpers ------

function _spawnFlash(mc, ms, color, radiusMeters, durationMs) {
    const geo = new THREE.SphereGeometry(ms * radiusMeters, 8, 8);
    const mat = new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(mc.x, mc.y, mc.z || 0);

    _state.threeEffectsRoot.add(mesh);
    _state.effects.push({
        type: 'flash',
        meshes: [mesh],
        startTime: performance.now(),
        duration: durationMs,
    });
}

function _spawnParticleBurst(mc, ms, color, count, durationMs) {
    const particles = [];
    for (let i = 0; i < count; i++) {
        const angle = (i / count) * Math.PI * 2 + Math.random() * 0.5;
        const speed = (0.5 + Math.random() * 0.5) * FX.PARTICLE_SPEED * ms;
        const vx = Math.cos(angle) * speed;
        const vy = Math.sin(angle) * speed;
        const vz = (0.3 + Math.random() * 0.7) * speed; // upward bias

        const geo = new THREE.SphereGeometry(ms * (FX.PARTICLE_R + Math.random() * FX.PARTICLE_R), 4, 4);
        const mat = new THREE.MeshBasicMaterial({
            color: color,
            transparent: true,
            opacity: 0.85,
            depthWrite: false,
            blending: THREE.AdditiveBlending,
        });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(mc.x, mc.y, mc.z || 0);

        _state.threeEffectsRoot.add(mesh);
        particles.push({ mesh, vx, vy, vz });
    }

    _state.effects.push({
        type: 'particles',
        particles: particles,
        meshes: particles.map(p => p.mesh),
        startTime: performance.now(),
        duration: durationMs,
        gravity: -FX.PARTICLE_SPEED * ms * 1.5, // downward acceleration
    });
}

// ------ Effect update loop ------

function _tickEffects() {
    const now = performance.now();

    for (let i = _state.effects.length - 1; i >= 0; i--) {
        const fx = _state.effects[i];
        const age = now - fx.startTime;
        const t = Math.min(1, age / fx.duration);

        if (t >= 1) {
            _disposeEffect(fx);
            _state.effects.splice(i, 1);
            continue;
        }

        switch (fx.type) {
            case 'tracer': {
                // Move head + glow along source→target path
                const pos = new THREE.Vector3().lerpVectors(fx.source, fx.target, t);
                fx.meshes[0].position.copy(pos); // head
                fx.meshes[1].position.copy(pos); // glow

                // Update trail endpoint
                const trailPositions = fx.meshes[2].geometry.attributes.position;
                trailPositions.setXYZ(1, pos.x, pos.y, pos.z);
                trailPositions.needsUpdate = true;

                // Fade trail as it progresses
                fx.meshes[2].material.opacity = 0.5 * (1 - t * 0.3);

                // Smoke trail for missiles — emit small grey/white particles along path
                if (fx.smoke && _state.threeScene) {
                    fx.smokeTimer = (fx.smokeTimer || 0) + 1;
                    if (fx.smokeTimer % 3 === 0) {
                        const ms = _getMeterScale() || 1e-8;
                        const sGeo = new THREE.SphereGeometry(ms * (1.5 + Math.random() * 1.5), 4, 4);
                        const sMat = new THREE.MeshBasicMaterial({
                            color: 0x888888, transparent: true, opacity: 0.35,
                            depthWrite: false, blending: THREE.NormalBlending,
                        });
                        const sMesh = new THREE.Mesh(sGeo, sMat);
                        sMesh.position.set(
                            pos.x + (Math.random() - 0.5) * ms * 1.5,
                            pos.y + (Math.random() - 0.5) * ms * 1.5,
                            pos.z + (Math.random() - 0.5) * ms * 1.5
                        );
                        _state.threeEffectsRoot.add(sMesh);
                        _state.effects.push({
                            type: 'flash', meshes: [sMesh],
                            startTime: performance.now(), duration: 600,
                        });
                    }
                }
                break;
            }

            case 'flash': {
                // Expand slightly + fade rapidly
                const scale = 1 + t * 0.5;
                const mesh = fx.meshes[0];
                mesh.scale.set(scale, scale, scale);
                mesh.material.opacity = 0.8 * (1 - t);
                break;
            }

            case 'explosion': {
                // Rings expand outward, core fades
                const expandT = _easeOutQuad(t);
                const scaleRing = 1 + expandT * (FX.ELIM_R_END / FX.ELIM_R_START - 1);

                // Ring 1 (magenta — primary)
                fx.meshes[0].scale.set(scaleRing, scaleRing, 1);
                fx.meshes[0].material.opacity = 0.7 * (1 - t);

                // Ring 2 (orange — slightly slower)
                const expandT2 = _easeOutQuad(Math.min(1, t * 0.8));
                const scaleRing2 = 1 + expandT2 * (FX.ELIM_R_END / FX.ELIM_R_START - 1) * 0.7;
                fx.meshes[1].scale.set(scaleRing2, scaleRing2, 1);
                fx.meshes[1].material.opacity = 0.5 * (1 - t);

                // Core flash (fade faster)
                const coreT = Math.min(1, t * 3);
                fx.meshes[2].scale.set(1 - coreT * 0.5, 1 - coreT * 0.5, 1 - coreT * 0.5);
                fx.meshes[2].material.opacity = 0.8 * (1 - coreT);
                break;
            }

            case 'particles': {
                const dt = 0.001 * fx.duration * (t - (fx._lastT || 0));
                fx._lastT = t;
                for (const p of fx.particles) {
                    p.mesh.position.x += p.vx * dt;
                    p.mesh.position.y += p.vy * dt;
                    p.vz += fx.gravity * dt;
                    p.mesh.position.z += p.vz * dt;
                    p.mesh.material.opacity = 0.8 * (1 - t);
                    const shrink = 1 - t * 0.5;
                    p.mesh.scale.set(shrink, shrink, shrink);
                }
                break;
            }
        }
    }
}

function _easeOutQuad(t) {
    return 1 - (1 - t) * (1 - t);
}

function _disposeEffect(fx) {
    if (!fx.meshes) return;
    for (const mesh of fx.meshes) {
        // Remove from whichever parent the mesh is actually in
        if (mesh.parent) mesh.parent.remove(mesh);
        if (mesh.geometry) mesh.geometry.dispose();
        if (mesh.material) mesh.material.dispose();
    }
}

// ------ DOM-based combat overlays (always visible, dramatic) ------

/**
 * Spawn a large DOM muzzle flash at a game-coordinate position.
 */
function _spawnDomFlash(gx, gy, color, durationMs) {
    if (!_state.map || !_state.showHitFlashes) return;
    const lngLat = _gameToLngLat(gx, gy);
    const hexColor = typeof color === 'number' ? '#' + color.toString(16).padStart(6, '0') : color;

    // Outer glow ring
    const outer = document.createElement('div');
    outer.style.cssText = [
        'width:120px; height:120px; border-radius:50%;',
        'pointer-events:none; position:relative;',
        'background:radial-gradient(circle, ' + hexColor + 'ee, ' + hexColor + '66 35%, transparent 70%);',
        'box-shadow: 0 0 40px ' + hexColor + ', 0 0 80px ' + hexColor + '88;',
        'animation: fx-hit-pulse ' + durationMs + 'ms ease-out forwards;',
    ].join('');

    // Inner bright core
    const inner = document.createElement('div');
    inner.style.cssText = [
        'position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);',
        'width:50px; height:50px; border-radius:50%;',
        'background:radial-gradient(circle, #ffffff, ' + hexColor + ' 60%, transparent);',
        'animation: fx-hit-pulse ' + (durationMs * 0.6) + 'ms ease-out forwards;',
    ].join('');
    outer.appendChild(inner);

    // Clip wrapper to prevent spill
    const wrap = document.createElement('div');
    wrap.style.cssText = 'width:240px; height:240px; overflow:hidden;'
        + ' border-radius:50%; pointer-events:none;'
        + ' display:flex; align-items:center; justify-content:center;';
    wrap.appendChild(outer);

    const marker = new maplibregl.Marker({ element: wrap, anchor: 'center' })
        .setLngLat(lngLat)
        .addTo(_state.map);

    setTimeout(() => marker.remove(), durationMs + 50);
}

/**
 * Spawn dramatic DOM explosion at a game-coordinate position.
 * Multi-layered: expanding ring + core flash + shockwave + sparks.
 */
function _spawnDomExplosion(gx, gy, durationMs) {
    if (!_state.map || !_state.showExplosions) return;
    const lngLat = _gameToLngLat(gx, gy);
    const CLIP = 300; // max visual diameter in px

    // Helper: wrap an animated element in a clipping circle so expanding
    // CSS animations don't spill across the entire viewport.
    function _clippedMarker(inner) {
        const wrap = document.createElement('div');
        wrap.style.cssText = 'width:' + CLIP + 'px; height:' + CLIP + 'px;'
            + ' overflow:hidden; border-radius:50%; pointer-events:none;'
            + ' display:flex; align-items:center; justify-content:center;';
        wrap.appendChild(inner);
        return new maplibregl.Marker({ element: wrap, anchor: 'center' })
            .setLngLat(lngLat).addTo(_state.map);
    }

    // Layer 1: Expanding magenta ring
    const ring = document.createElement('div');
    ring.style.cssText = [
        'width:50px; height:50px; border-radius:50%;',
        'pointer-events:none;',
        'border: 5px solid #ff2a6d;',
        'box-shadow: 0 0 40px #ff2a6d, 0 0 80px #ff2a6daa, inset 0 0 30px #ff2a6d66;',
        'animation: fx-explode ' + durationMs + 'ms ease-out forwards;',
    ].join('');
    const ringMarker = _clippedMarker(ring);

    // Layer 2: Orange secondary ring (slightly delayed via slower animation)
    const ring2 = document.createElement('div');
    ring2.style.cssText = [
        'width:35px; height:35px; border-radius:50%;',
        'pointer-events:none;',
        'border: 4px solid #ffa500;',
        'box-shadow: 0 0 30px #ffa500, 0 0 60px #ffa50088;',
        'animation: fx-explode ' + (durationMs * 1.2) + 'ms ease-out forwards;',
    ].join('');
    const ring2Marker = _clippedMarker(ring2);

    // Layer 3: Bright white core flash (fast)
    const core = document.createElement('div');
    core.style.cssText = [
        'width:120px; height:120px; border-radius:50%;',
        'pointer-events:none;',
        'background:radial-gradient(circle, #ffffff, #ffcc00 25%, #ff2a6d 55%, transparent 75%);',
        'box-shadow: 0 0 60px #ffffffaa, 0 0 120px #ff2a6d66;',
        'animation: fx-flash ' + (durationMs * 0.35) + 'ms ease-out forwards;',
    ].join('');
    const coreMarker = _clippedMarker(core);

    // Layer 4: Shockwave ring (thin, fast, wide)
    const shock = document.createElement('div');
    shock.style.cssText = [
        'width:15px; height:15px; border-radius:50%;',
        'pointer-events:none;',
        'border: 2px solid #ffffffaa;',
        'animation: fx-shockwave ' + (durationMs * 0.7) + 'ms ease-out forwards;',
    ].join('');
    const shockMarker = _clippedMarker(shock);

    // Screen shake
    _triggerScreenShake(300, 6);

    setTimeout(() => {
        ringMarker.remove(); ring2Marker.remove();
        coreMarker.remove(); shockMarker.remove();
    }, durationMs * 1.3 + 50);
}

/**
 * Spawn floating text that rises and fades (elimination name, damage, etc.)
 */
function _spawnFloatingText(gx, gy, text, color, durationMs) {
    if (!_state.map || !_state.showFloatingText) return;
    const lngLat = _gameToLngLat(gx, gy);

    const el = document.createElement('div');
    el.style.cssText = [
        'pointer-events:none; white-space:nowrap;',
        'font-family:"JetBrains Mono",monospace;',
        'font-size:20px; font-weight:bold; letter-spacing:2px;',
        'color:' + color + '; text-transform:uppercase;',
        'text-shadow: 0 0 12px ' + color + ', 0 0 24px ' + color + '88, 0 2px 6px #000;',
        'max-width:250px; overflow:hidden; text-overflow:ellipsis;',
        'animation: fx-float-text ' + durationMs + 'ms ease-out forwards;',
    ].join('');
    el.textContent = text;

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat(lngLat)
        .addTo(_state.map);

    setTimeout(() => marker.remove(), durationMs + 50);
}

/**
 * Trigger screen shake by applying CSS animation to the map container.
 */
function _triggerScreenShake(durationMs, intensity) {
    if (!_state.showScreenFx) return;
    const container = _state.container;
    if (!container) return;
    container.style.animation = 'none';
    container.offsetHeight; // force reflow
    container.style.setProperty('--shake-intensity', intensity + 'px');
    container.style.animation = 'fx-screen-shake ' + durationMs + 'ms ease-out';
    setTimeout(() => { container.style.animation = ''; }, durationMs);
}

/**
 * Render wave progress dots: filled for completed, pulsing for current, empty for future.
 */
function _waveProgressDots(currentWave, totalWaves) {
    const dots = [];
    for (let i = 1; i <= totalWaves; i++) {
        if (i < currentWave) {
            // Completed wave — solid cyan
            dots.push('<span style="width:6px;height:6px;border-radius:50%;background:#00f0ff;display:inline-block"></span>');
        } else if (i === currentWave) {
            // Current wave — pulsing
            dots.push('<span style="width:8px;height:8px;border-radius:50%;background:#00f0ff;display:inline-block;box-shadow:0 0 6px #00f0ff;animation:hostile-pulse 1s infinite"></span>');
        } else {
            // Future wave — dim outline
            dots.push('<span style="width:6px;height:6px;border-radius:50%;border:1px solid #333;display:inline-block"></span>');
        }
    }
    return dots.join('');
}

/**
 * Update the on-map combat status bar during active battle.
 * Shows: wave, hostiles alive, friendly health, threat level.
 */
function _updateCombatStatusBar() {
    const container = _state.container;
    if (!container) return;

    const gameState = TritiumStore.get('game.phase');
    if (gameState !== 'active' && gameState !== 'countdown' && gameState !== 'wave_complete') {
        const bar = container.querySelector('.fx-combat-status');
        if (bar) bar.style.display = 'none';
        return;
    }
    // Auto-detect active battle if we missed the state change event (late-joining browser)
    if (gameState === 'active' && !_state.battleStartTime) {
        _state.battleStartTime = performance.now();
        _showBattleVignette(true);
        // Restore directional arrows from store if we missed the wave_start event
        const storedDir = TritiumStore.get('game.waveDirection');
        if (storedDir && storedDir !== 'random' && !_state._waveDirection) {
            _state._waveDirection = storedDir;
            _showDirectionalThreatArrows(storedDir);
        }
    }

    let bar = container.querySelector('.fx-combat-status');
    if (!bar) {
        bar = document.createElement('div');
        bar.className = 'fx-combat-status';
        bar.style.cssText = [
            'position:absolute; bottom:12px; left:50%; transform:translateX(-50%);',
            'z-index:100; pointer-events:none;',
            'display:flex; align-items:center; gap:16px;',
            'background:rgba(6,6,9,0.85); border:1px solid rgba(0,240,255,0.25);',
            'border-radius:4px; padding:6px 16px;',
            'font-family:"JetBrains Mono",monospace; font-size:12px;',
            'box-shadow: 0 4px 12px rgba(0,0,0,0.4), inset 0 0 20px rgba(0,240,255,0.03);',
        ].join('');
        container.appendChild(bar);
    }
    bar.style.display = 'flex';

    // Count hostiles alive and friendly health
    let hostilesAlive = 0;
    let friendlyTotal = 0;
    let friendlyHealth = 0;
    let friendlyMaxHealth = 0;

    TritiumStore.units.forEach((u) => {
        if (u.status === 'eliminated' || u.status === 'destroyed') return;
        if (u.alliance === 'hostile') hostilesAlive++;
        if (u.alliance === 'friendly' && u.isCombatant) {
            friendlyTotal++;
            friendlyHealth += u.health || 0;
            friendlyMaxHealth += u.maxHealth || 100;
        }
    });

    const healthPct = friendlyMaxHealth > 0 ? Math.round((friendlyHealth / friendlyMaxHealth) * 100) : 100;
    const healthColor = healthPct > 60 ? '#05ffa1' : healthPct > 30 ? '#fcee0a' : '#ff2a6d';

    const wave = TritiumStore.get('game.wave') || '?';
    const totalWaves = TritiumStore.get('game.totalWaves') || 10;

    // Elapsed battle timer
    let timerStr = '0:00';
    if (_state.battleStartTime) {
        const elapsed = Math.floor((performance.now() - _state.battleStartTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        timerStr = mins + ':' + String(secs).padStart(2, '0');
    }

    // Pulse the border when hostiles are present
    if (hostilesAlive > 0) {
        bar.style.borderColor = 'rgba(255,42,109,0.5)';
        bar.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4), 0 0 15px rgba(255,42,109,0.15), inset 0 0 20px rgba(255,42,109,0.05)';
    } else {
        bar.style.borderColor = 'rgba(5,255,161,0.3)';
        bar.style.boxShadow = '0 4px 12px rgba(0,0,0,0.4), inset 0 0 20px rgba(0,240,255,0.03)';
    }

    // Between-wave countdown
    let countdownHtml = '';
    if (_state._nextWaveCountdownStart > 0 && hostilesAlive === 0) {
        const elapsed = (performance.now() - _state._nextWaveCountdownStart) / 1000;
        const remaining = Math.max(0, _state._nextWaveCountdown - elapsed);
        if (remaining > 0) {
            const nextName = _state._nextWaveName || 'NEXT';
            countdownHtml = [
                '<span style="color:#333">|</span>',
                '<span style="color:#fcee0a;letter-spacing:1px;animation:wave-countdown-pulse 1s ease-in-out infinite">NEXT WAVE</span>',
                '<span style="color:#fcee0a;font-weight:bold;font-size:14px">' + Math.ceil(remaining) + 's</span>',
            ].join(' ');
        }
    }

    bar.innerHTML = [
        '<span style="color:#ff2a6d;font-weight:bold;letter-spacing:1px">',
        hostilesAlive > 0 ? '\u26A0' : '\u2714',
        '</span>',
        '<span style="color:' + (hostilesAlive > 0 ? '#ff2a6d' : '#666') + ';letter-spacing:1px">' + (hostilesAlive > 0 ? 'THREAT' : 'CLEAR') + '</span>',
        '<span style="color:#ff2a6d;font-weight:bold;font-size:14px">' + (hostilesAlive > 0 ? hostilesAlive : '') + '</span>',
        '<span style="color:#333">|</span>',
        '<span style="color:#aaa;letter-spacing:1px">DEFENDERS</span>',
        '<span style="color:' + healthColor + ';font-weight:bold;font-size:14px">' + friendlyTotal + '</span>',
        '<span style="color:' + healthColor + ';font-size:10px">' + healthPct + '%</span>',
        '<span style="color:#333">|</span>',
        '<span style="color:#aaa;letter-spacing:1px">WAVE</span>',
        '<span style="color:#00f0ff;font-weight:bold;font-size:14px">' + wave + '/' + totalWaves + '</span>',
        '<span style="display:inline-flex;gap:3px;align-items:center">' + _waveProgressDots(wave, totalWaves) + '</span>',
        '<span style="color:#333">|</span>',
        '<span style="color:#fcee0a;font-weight:bold;font-size:13px">' + (TritiumStore.get('game.score') || 0).toLocaleString() + '</span>',
        '<span style="color:#333">|</span>',
        '<span style="color:#555;font-size:11px;letter-spacing:1px">' + timerStr + '</span>',
        countdownHtml,
    ].join(' ');
}

/**
 * Show/hide a subtle vignette border during active battle.
 * Darkens edges to focus attention on the tactical area.
 */
function _showBattleVignette(show) {
    const container = _state.container;
    if (!container) return;
    let vig = container.querySelector('.fx-battle-vignette');
    if (show) {
        if (!vig) {
            vig = document.createElement('div');
            vig.className = 'fx-battle-vignette';
            vig.style.cssText = [
                'position:absolute; inset:0; pointer-events:none; z-index:90;',
                'background:radial-gradient(ellipse at center, transparent 45%, rgba(0,0,0,0.5) 100%);',
                'border: 2px solid rgba(255,42,109,0.25);',
                'box-shadow: inset 0 0 60px rgba(255,42,109,0.08), inset 0 0 120px rgba(0,0,0,0.3);',
                'transition: opacity 1s ease-in;',
                'opacity:0;',
            ].join('');
            container.appendChild(vig);
        }
        // Fade in
        requestAnimationFrame(() => { vig.style.opacity = '1'; });
    } else if (vig) {
        vig.style.opacity = '0';
        setTimeout(() => vig.remove(), 1000);
    }
}

// ------ Scan line effect ------

function _triggerScanLine(color) {
    const container = _state.container;
    if (!container || !_state.showScreenFx) return;
    const line = document.createElement('div');
    line.style.cssText = [
        'position:absolute; left:0; right:0; top:0; height:3px;',
        'z-index:160; pointer-events:none;',
        'background:linear-gradient(90deg, transparent 0%, ' + color + ' 20%, ' + color + ' 80%, transparent 100%);',
        'box-shadow: 0 0 20px ' + color + ', 0 0 40px ' + color + '66;',
        'animation: fx-scan-line 0.8s ease-in-out forwards;',
    ].join('');
    container.appendChild(line);
    setTimeout(() => line.remove(), 850);
}

// ------ Damage vignette pulse ------

function _pulseVignetteDamage() {
    const container = _state.container;
    if (!container) return;
    let pulse = container.querySelector('.fx-damage-pulse');
    if (pulse) return; // Already pulsing
    pulse = document.createElement('div');
    pulse.className = 'fx-damage-pulse';
    pulse.style.cssText = [
        'position:absolute; inset:0; pointer-events:none; z-index:91;',
        'box-shadow: inset 0 0 80px rgba(255,42,109,0.25), inset 0 0 160px rgba(255,0,0,0.1);',
        'animation: fx-vignette-flash 0.4s ease-out forwards;',
    ].join('');
    container.appendChild(pulse);
    setTimeout(() => pulse.remove(), 450);
}

// ------ Directional threat indicators ------

/**
 * Direction-to-CSS-position map: where to place threat arrows on screen edges.
 * Each direction maps to an array of { position, rotation } entries.
 */
const _DIR_POSITIONS = {
    north:   [{ css: 'top:8px;left:50%;transform:translateX(-50%) rotate(180deg)', label: 'N' }],
    south:   [{ css: 'bottom:50px;left:50%;transform:translateX(-50%) rotate(0deg)', label: 'S' }],
    east:    [{ css: 'top:50%;right:8px;transform:translateY(-50%) rotate(270deg)', label: 'E' }],
    west:    [{ css: 'top:50%;left:8px;transform:translateY(-50%) rotate(90deg)', label: 'W' }],
    pincer:  [
        { css: 'top:50%;right:8px;transform:translateY(-50%) rotate(270deg)', label: 'E' },
        { css: 'top:50%;left:8px;transform:translateY(-50%) rotate(90deg)', label: 'W' },
    ],
    surround: [
        { css: 'top:8px;left:50%;transform:translateX(-50%) rotate(180deg)', label: 'N' },
        { css: 'bottom:50px;left:50%;transform:translateX(-50%) rotate(0deg)', label: 'S' },
        { css: 'top:50%;right:8px;transform:translateY(-50%) rotate(270deg)', label: 'E' },
        { css: 'top:50%;left:8px;transform:translateY(-50%) rotate(90deg)', label: 'W' },
    ],
};

function _showDirectionalThreatArrows(direction, preview) {
    _removeDirectionalThreatArrows();
    const container = _state.container;
    if (!container || !direction || direction === 'random') return;

    const positions = _DIR_POSITIONS[direction];
    if (!positions) return;

    const color = preview ? 'rgba(255,42,109,0.4)' : 'rgba(255,42,109,0.8)';
    const glowColor = preview ? 'rgba(255,42,109,0.15)' : 'rgba(255,42,109,0.3)';
    const animName = preview ? 'threat-arrow-pulse-preview' : 'threat-arrow-pulse';

    positions.forEach((pos) => {
        const arrow = document.createElement('div');
        arrow.className = 'fx-threat-arrow';
        arrow.style.cssText = [
            'position:absolute;', pos.css, ';',
            'z-index:120; pointer-events:none;',
            'width:0; height:0;',
            'border-left:20px solid transparent; border-right:20px solid transparent;',
            'border-top:30px solid ' + color + ';',
            'filter:drop-shadow(0 0 12px ' + glowColor + ');',
            'animation:' + animName + ' 1s ease-in-out infinite;',
        ].join('');
        container.appendChild(arrow);

        // Label below/beside arrow
        const label = document.createElement('div');
        label.className = 'fx-threat-arrow';
        label.style.cssText = [
            'position:absolute;', pos.css, ';',
            'z-index:119; pointer-events:none;',
            'font-family:"JetBrains Mono",monospace; font-size:10px;',
            'color:' + color + '; letter-spacing:2px; font-weight:bold;',
            'margin-top:34px;',
        ].join('');
        label.textContent = 'THREAT ' + pos.label;
        container.appendChild(label);
    });
}

function _removeDirectionalThreatArrows() {
    const container = _state.container;
    if (!container) return;
    container.querySelectorAll('.fx-threat-arrow').forEach(el => el.remove());
}

// ------ Game-over overlay ------

function _showGameOverOverlay(result, data) {
    _removeGameOverOverlay();
    const container = _state.container;
    if (!container) return;

    const isVictory = result === 'victory';
    const color = isVictory ? '#05ffa1' : '#ff2a6d';
    const bgColor = isVictory ? 'rgba(5,255,161,0.03)' : 'rgba(255,42,109,0.03)';
    const borderColor = isVictory ? 'rgba(5,255,161,0.3)' : 'rgba(255,42,109,0.3)';

    const score = data.score || data.final_score || TritiumStore.get('game.score') || 0;
    const wave = data.wave || TritiumStore.get('game.wave') || '?';
    const eliminations = data.total_eliminations || TritiumStore.get('game.eliminations') || 0;

    // Battle duration
    let durationStr = '';
    if (_state.battleStartTime) {
        const elapsed = Math.floor((performance.now() - _state.battleStartTime) / 1000);
        const mins = Math.floor(elapsed / 60);
        const secs = elapsed % 60;
        durationStr = mins + ':' + String(secs).padStart(2, '0');
    }

    const overlay = document.createElement('div');
    overlay.className = 'fx-game-over-overlay';
    overlay.style.cssText = [
        'position:absolute; inset:0; pointer-events:none; z-index:200;',
        'display:flex; flex-direction:column; align-items:center; justify-content:center;',
        'background:radial-gradient(ellipse at center, ' + bgColor + ' 0%, rgba(0,0,0,0.6) 100%);',
        'opacity:0; transition:opacity 1.5s ease-in;',
    ].join('');

    overlay.innerHTML = [
        '<div style="text-align:center;animation:fx-streak-pop 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards">',
        // Main result
        '<div style="font-family:Inter,sans-serif;font-weight:900;font-size:56px;letter-spacing:8px;',
        'color:' + color + ';text-shadow:0 0 30px ' + color + ',0 0 60px ' + color + '44,0 4px 12px #000;',
        'text-transform:uppercase">' + (isVictory ? 'VICTORY' : 'DEFEAT') + '</div>',
        // Subtitle
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:14px;color:#aaa;',
        'letter-spacing:3px;margin-top:8px">' + (isVictory ? 'ALL WAVES CLEARED' : 'PERIMETER BREACHED') + '</div>',
        // Divider
        '<div style="width:200px;height:1px;background:linear-gradient(90deg,transparent,' + color + ',transparent);',
        'margin:20px auto"></div>',
        // Stats grid
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px 32px;margin-top:8px">',
        _gameOverStat('SCORE', score.toLocaleString(), color),
        _gameOverStat('WAVES', wave, '#00f0ff'),
        _gameOverStat('ELIMINATIONS', eliminations, '#fcee0a'),
        _gameOverStat('TIME', durationStr || '--', '#aaa'),
        '</div>',
        // MVP slot (populated async)
        '<div class="fx-mvp-slot" style="text-align:center;margin-top:16px;min-height:40px"></div>',
        // PLAY AGAIN button
        '<div style="margin-top:24px">',
        '<button class="fx-play-again-btn" style="',
        'pointer-events:auto;cursor:pointer;',
        'font-family:Inter,sans-serif;font-weight:700;font-size:16px;letter-spacing:3px;',
        'color:' + color + ';background:transparent;',
        'border:2px solid ' + color + ';border-radius:4px;',
        'padding:10px 32px;text-transform:uppercase;',
        'text-shadow:0 0 8px ' + color + '44;',
        'box-shadow:0 0 12px ' + color + '33,inset 0 0 12px ' + color + '11;',
        'transition:all 0.2s;',
        '">PLAY AGAIN</button>',
        '</div>',
        '</div>',
    ].join('');

    container.appendChild(overlay);
    requestAnimationFrame(() => { overlay.style.opacity = '1'; });

    // Fetch MVP data and display it
    fetch('/api/game/stats/mvp')
        .then(r => r.json())
        .then(d => {
            if (d.status === 'ready' && d.mvp) {
                const mvpEl = overlay.querySelector('.fx-mvp-slot');
                if (mvpEl) {
                    const m = d.mvp;
                    mvpEl.innerHTML = '<span style="color:#666;font-size:10px;letter-spacing:2px">MVP</span>'
                        + '<br><span style="color:#fcee0a;font-weight:700;font-size:16px;text-shadow:0 0 8px #fcee0a44">'
                        + _esc(m.name || m.unit_name || 'Unknown') + '</span>'
                        + '<br><span style="color:#aaa;font-size:11px">'
                        + (m.kills || 0) + ' kills'
                        + (m.accuracy ? ' / ' + Math.round(m.accuracy * 100) + '% acc' : '')
                        + '</span>';
                }
            }
        })
        .catch(() => {});

    // PLAY AGAIN button handler
    const playAgainBtn = overlay.querySelector('.fx-play-again-btn');
    if (playAgainBtn) {
        playAgainBtn.addEventListener('mouseenter', () => {
            playAgainBtn.style.background = color + '22';
            playAgainBtn.style.boxShadow = '0 0 20px ' + color + '66, inset 0 0 20px ' + color + '22';
        });
        playAgainBtn.addEventListener('mouseleave', () => {
            playAgainBtn.style.background = 'transparent';
            playAgainBtn.style.boxShadow = '0 0 12px ' + color + '33, inset 0 0 12px ' + color + '11';
        });
        playAgainBtn.addEventListener('click', () => {
            _removeGameOverOverlay();
            if (window._mapActions) {
                window._mapActions.resetGame();
                setTimeout(() => window._mapActions.beginWar(), 500);
            }
        });
    }

    // Auto-dismiss after 30s (longer to allow PLAY AGAIN click)
    overlay._dismissTimer = setTimeout(() => _removeGameOverOverlay(), 30000);
}

function _gameOverStat(label, value, color) {
    return [
        '<div style="text-align:center">',
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:#666;letter-spacing:2px">' + label + '</div>',
        '<div style="font-family:Inter,sans-serif;font-weight:700;font-size:22px;color:' + color + ';',
        'text-shadow:0 0 8px ' + color + '44">' + value + '</div>',
        '</div>',
    ].join('');
}

function _removeGameOverOverlay() {
    const container = _state.container;
    if (!container) return;
    const overlay = container.querySelector('.fx-game-over-overlay');
    if (overlay) {
        clearTimeout(overlay._dismissTimer);
        overlay.style.opacity = '0';
        setTimeout(() => overlay.remove(), 1000);
    }
}

/**
 * Trigger a full-screen color flash overlay.
 */
function _triggerScreenFlash(color, durationMs) {
    if (!_state.showScreenFx) return;
    const container = _state.container;
    if (!container) return;

    let overlay = container.querySelector('.fx-screen-flash');
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'fx-screen-flash';
        overlay.style.cssText = [
            'position:absolute; inset:0; pointer-events:none; z-index:999;',
            'opacity:0;',
        ].join('');
        container.appendChild(overlay);
    }

    overlay.style.background = color + '22';
    overlay.style.animation = 'none';
    overlay.offsetHeight;
    overlay.style.animation = 'fx-vignette-flash ' + durationMs + 'ms ease-out forwards';
}

/**
 * Add an entry to the on-map kill feed.
 */
function _addKillFeedEntry(killerName, targetName, weaponLabel) {
    if (!_state.showKillFeed) return;
    let feed = _state.container?.querySelector('.fx-kill-feed');
    if (!feed && _state.container) {
        feed = document.createElement('div');
        feed.className = 'fx-kill-feed';
        feed.style.cssText = [
            'position:absolute; top:60px; right:12px; z-index:100;',
            'display:flex; flex-direction:column; gap:4px; pointer-events:none;',
            'max-width:340px;',
        ].join('');
        _state.container.appendChild(feed);
    }
    if (!feed) return;

    const entry = document.createElement('div');
    entry.style.cssText = [
        'background:rgba(6,6,9,0.9); border:1px solid #ff2a6d66;',
        'border-left:4px solid #ff2a6d; padding:6px 12px;',
        'font-family:"JetBrains Mono",monospace; font-size:13px;',
        'color:#eee; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;',
        'box-shadow: 0 2px 8px rgba(0,0,0,0.4), inset 0 0 20px rgba(255,42,109,0.05);',
        'animation: fx-killfeed-in 0.3s ease-out;',
    ].join('');
    const weaponTag = weaponLabel
        ? ' <span style="color:#fcee0a;font-size:10px;letter-spacing:1px">[' + _esc(weaponLabel) + ']</span> '
        : ' ';
    entry.innerHTML = '<span style="color:#05ffa1">' + _esc(killerName) + '</span>'
        + weaponTag
        + '<span style="color:#ff2a6d66">//</span> '
        + '<span style="color:#ff2a6d">' + _esc(targetName) + '</span>';

    feed.prepend(entry);

    // Max 6 entries
    while (feed.children.length > 6) {
        feed.lastChild.remove();
    }

    // Auto-remove after 8s
    setTimeout(() => {
        entry.style.animation = 'fx-killfeed-out 0.5s ease-in forwards';
        setTimeout(() => entry.remove(), 500);
    }, 8000);
}

function _weaponDisplayName(weaponType) {
    const names = {
        nerf_missile_launcher: 'MISSILE',
        nerf_tank_cannon: 'TANK SHELL',
        nerf_heavy_turret: 'HEAVY',
        nerf_turret_gun: 'TURRET',
        nerf_cannon: 'CANNON',
        nerf_apc_mg: 'MG',
        nerf_dart_gun: 'DART',
        nerf_scout_gun: 'SCOUT',
        nerf_pistol: 'PISTOL',
    };
    return names[weaponType] || 'DART';
}

/**
 * Inject combat effect CSS animations (once).
 * Includes all keyframes for DOM-based combat effects.
 */
function _injectFxCss() {
    if (document.getElementById('tritium-fx-css')) return;
    const style = document.createElement('style');
    style.id = 'tritium-fx-css';
    style.textContent = [
        '@keyframes fx-flash {',
        '  0% { opacity: 1; transform: scale(1); }',
        '  100% { opacity: 0; transform: scale(3); }',
        '}',
        '@keyframes fx-explode {',
        '  0% { opacity: 1; transform: scale(1); }',
        '  100% { opacity: 0; transform: scale(12); border-width: 1px; }',
        '}',
        '@keyframes fx-shockwave {',
        '  0% { opacity: 0.8; transform: scale(1); }',
        '  100% { opacity: 0; transform: scale(20); border-width: 0.5px; }',
        '}',
        '@keyframes fx-float-text {',
        '  0% { opacity: 1; transform: translateY(0) scale(1); }',
        '  30% { opacity: 1; transform: translateY(-30px) scale(1.1); }',
        '  100% { opacity: 0; transform: translateY(-80px) scale(0.8); }',
        '}',
        '@keyframes fx-screen-shake {',
        '  0%, 100% { transform: translate(0, 0); }',
        '  10% { transform: translate(var(--shake-intensity), calc(var(--shake-intensity) * -0.5)); }',
        '  20% { transform: translate(calc(var(--shake-intensity) * -0.8), var(--shake-intensity)); }',
        '  30% { transform: translate(calc(var(--shake-intensity) * 0.6), calc(var(--shake-intensity) * -0.7)); }',
        '  40% { transform: translate(calc(var(--shake-intensity) * -0.4), calc(var(--shake-intensity) * 0.5)); }',
        '  50% { transform: translate(calc(var(--shake-intensity) * 0.3), calc(var(--shake-intensity) * -0.3)); }',
        '  60% { transform: translate(calc(var(--shake-intensity) * -0.2), calc(var(--shake-intensity) * 0.2)); }',
        '}',
        '@keyframes fx-vignette-flash {',
        '  0% { opacity: 0.6; }',
        '  100% { opacity: 0; }',
        '}',
        '@keyframes fx-killfeed-in {',
        '  0% { opacity: 0; transform: translateX(20px); }',
        '  100% { opacity: 1; transform: translateX(0); }',
        '}',
        '@keyframes fx-killfeed-out {',
        '  0% { opacity: 1; }',
        '  100% { opacity: 0; transform: translateX(20px); }',
        '}',
        '@keyframes fx-hit-pulse {',
        '  0% { opacity: 1; transform: scale(1); }',
        '  50% { opacity: 0.8; transform: scale(1.5); }',
        '  100% { opacity: 0; transform: scale(0.5); }',
        '}',
        '@keyframes threat-arrow-pulse {',
        '  0%, 100% { opacity: 0.6; filter: drop-shadow(0 0 12px rgba(255,42,109,0.3)); }',
        '  50% { opacity: 1; filter: drop-shadow(0 0 24px rgba(255,42,109,0.6)); }',
        '}',
        '@keyframes threat-arrow-pulse-preview {',
        '  0%, 100% { opacity: 0.2; }',
        '  50% { opacity: 0.5; }',
        '}',
        '@keyframes wave-countdown-pulse {',
        '  0%, 100% { opacity: 0.7; }',
        '  50% { opacity: 1; }',
        '}',
        '@keyframes fx-scan-line {',
        '  0% { top: 0; opacity: 1; }',
        '  100% { top: 100%; opacity: 0.3; }',
        '}',
    ].join('\n');
    document.head.appendChild(style);
}

/**
 * Ensure the map continuously repaints while effects are active.
 * MapLibre only repaints on interaction by default; combat effects
 * need continuous animation frames.
 */
// ============================================================
// FPS counter
// ============================================================

const FPS_UPDATE_INTERVAL = 500;

function _updateFps() {
    const now = performance.now();
    _state._frameTimes.push(now);

    while (_state._frameTimes.length > 60) {
        _state._frameTimes.shift();
    }

    if (now - _state._lastFpsUpdate < FPS_UPDATE_INTERVAL) return;
    _state._lastFpsUpdate = now;

    if (_state._frameTimes.length >= 2) {
        const elapsed = _state._frameTimes[_state._frameTimes.length - 1] - _state._frameTimes[0];
        const frames = _state._frameTimes.length - 1;
        _state._currentFps = Math.round((frames / elapsed) * 1000);
    }

    const fpsEl = document.getElementById('map-fps');
    if (fpsEl) fpsEl.textContent = `${_state._currentFps} FPS`;
    const statusEl = document.getElementById('status-fps');
    if (statusEl) statusEl.textContent = `${_state._currentFps} FPS`;
}

function _startFpsLoop() {
    if (_state._fpsLoopRunning) return;
    _state._fpsLoopRunning = true;
    function tick() {
        _updateFps();
        requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
}

function _ensureRepaintLoop() {
    if (_state.effectsActive) return;
    _state.effectsActive = true;
    _repaintLoop();
}

function _repaintLoop() {
    const has3DUnits = Object.keys(_state.unitMeshes).length > 0;
    if (_state.effects.length === 0 && !has3DUnits) {
        _state.effectsActive = false;
        return;
    }
    if (_state.map) _state.map.triggerRepaint();
    _state.effectAnimId = requestAnimationFrame(_repaintLoop);
}

// ============================================================
// Layer HUD
// ============================================================

function _createLayerHud() {
    if (_state.layerHud) return;
    _state.layerHud = document.createElement('div');
    _state.layerHud.id = 'map-layer-hud';
    _state.layerHud.style.cssText = [
        'position:absolute; top:8px; left:50%; transform:translateX(-50%);',
        'z-index:10; pointer-events:none;',
        'font-family:"JetBrains Mono",monospace; font-size:11px;',
        'color:#00f0ff; background:rgba(6,6,9,0.75);',
        'padding:4px 12px; border-radius:3px;',
        'border:1px solid rgba(0,240,255,0.2);',
        'text-transform:uppercase; letter-spacing:1px;',
        'white-space:nowrap;',
        _state.showLayerHud ? '' : 'display:none;',
    ].join('');
    _state.container.appendChild(_state.layerHud);
    _updateLayerHud();
}

// ============================================================
// Compact Map Legend (bottom-left, always visible)
// ============================================================

function _createMapLegend() {
    if (document.getElementById('map-legend')) return;
    const legend = document.createElement('div');
    legend.id = 'map-legend';
    legend.title = 'Map Legend — click to expand/collapse';
    legend.style.cssText = [
        'position:absolute; bottom:28px; left:8px; z-index:10;',
        'font-family:"JetBrains Mono",monospace; font-size:9px;',
        'background:rgba(6,6,9,0.85); border:1px solid rgba(0,240,255,0.15);',
        'border-radius:4px; padding:0; cursor:pointer;',
        'pointer-events:auto; max-width:180px;',
        'backdrop-filter:blur(4px);',
    ].join('');

    const header = document.createElement('div');
    header.style.cssText = 'padding:4px 8px; color:#00f0ff; font-weight:bold; letter-spacing:0.5px; font-size:8px;';
    header.textContent = 'LEGEND';
    legend.appendChild(header);

    const body = document.createElement('div');
    body.style.cssText = 'padding:0 8px 6px; display:block;';

    const entries = [
        { color: '#05ffa1', shape: 'circle', label: 'Friendly' },
        { color: '#ff2a6d', shape: 'square', label: 'Hostile' },
        { color: '#00a0ff', shape: 'circle', label: 'Neutral' },
        { color: '#fcee0a', shape: 'circle', label: 'Unknown' },
        { type: 'sep' },
        { color: '#05ffa1', shape: 'dashed', label: 'Patrol Route' },
        { color: '#ff2a6d', shape: 'dashed', label: 'Hostile Objective' },
        { color: '#00f0ff', shape: 'line', label: 'Building Outline' },
    ];

    for (const e of entries) {
        if (e.type === 'sep') {
            const sep = document.createElement('div');
            sep.style.cssText = 'border-top:1px solid rgba(0,240,255,0.08); margin:3px 0;';
            body.appendChild(sep);
            continue;
        }
        const row = document.createElement('div');
        row.style.cssText = 'display:flex; align-items:center; gap:5px; padding:1px 0; color:#8a9aaa;';
        const icon = document.createElement('span');
        if (e.shape === 'circle') {
            icon.style.cssText = `width:7px; height:7px; border-radius:50%; background:${e.color}; flex-shrink:0;`;
        } else if (e.shape === 'square') {
            icon.style.cssText = `width:7px; height:7px; border-radius:1px; background:${e.color}; flex-shrink:0;`;
        } else if (e.shape === 'dashed') {
            icon.style.cssText = `width:14px; height:0; border-top:2px dashed ${e.color}; flex-shrink:0;`;
        } else if (e.shape === 'line') {
            icon.style.cssText = `width:14px; height:0; border-top:1.5px solid ${e.color}; flex-shrink:0;`;
        }
        const lbl = document.createElement('span');
        lbl.textContent = e.label;
        row.appendChild(icon);
        row.appendChild(lbl);
        body.appendChild(row);
    }

    legend.appendChild(body);

    // Collapse toggle
    let collapsed = false;
    header.addEventListener('click', (ev) => {
        ev.stopPropagation();
        collapsed = !collapsed;
        body.style.display = collapsed ? 'none' : 'block';
        header.textContent = collapsed ? 'LEGEND +' : 'LEGEND';
    });

    _state.container.appendChild(legend);
}

// ============================================================
// Patrol Route Drawing Toolbar Button
// ============================================================

function _createPatrolDrawButton() {
    if (document.getElementById('patrol-draw-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'patrol-draw-btn';
    btn.title = 'Draw Patrol Route (click to place waypoints on map)';
    btn.style.cssText = [
        'position:absolute; bottom:110px; left:12px; z-index:10;',
        'width:36px; height:36px; border-radius:6px;',
        'background:rgba(6,6,9,0.85); border:1px solid rgba(5,255,161,0.3);',
        'color:#05ffa1; cursor:pointer; pointer-events:auto;',
        'display:flex; align-items:center; justify-content:center;',
        'font-family:"JetBrains Mono",monospace; font-size:14px;',
        'backdrop-filter:blur(4px); transition:all 0.15s;',
    ].join('');
    // Use a simple path/route icon (Unicode)
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="#05ffa1" stroke-width="1.5">
        <circle cx="3" cy="3" r="2"/>
        <circle cx="15" cy="7" r="2"/>
        <circle cx="9" cy="15" r="2"/>
        <line x1="5" y1="3" x2="13" y2="7"/>
        <line x1="15" y1="9" x2="11" y2="15"/>
    </svg>`;

    btn.addEventListener('mouseenter', () => {
        btn.style.borderColor = '#05ffa1';
        btn.style.boxShadow = '0 0 8px rgba(5,255,161,0.4)';
    });
    btn.addEventListener('mouseleave', () => {
        btn.style.borderColor = 'rgba(5,255,161,0.3)';
        btn.style.boxShadow = 'none';
    });
    btn.addEventListener('click', () => {
        EventBus.emit('patrol:drawRoute', { unitId: null });
    });

    _state.container.appendChild(btn);
}

// ============================================================
// Viewport reporting (LOD system)
// ============================================================

/**
 * Estimate visible radius in meters from MapLibre zoom level.
 * At zoom 16, ~150m visible radius on a typical display.
 * Each zoom level halves the visible area (doubles the radius).
 */
function _estimateViewportRadius(zoom) {
    return 150.0 * Math.pow(2.0, 16.0 - zoom);
}

/**
 * Throttled viewport reporter.  Sends the current map center and zoom
 * to the backend via EventBus -> WebSocket so the LOD system can adjust
 * simulation fidelity for offscreen targets.
 *
 * Throttled to at most once per second to avoid flooding the WS during
 * smooth pan/zoom animations.
 */
let _lastViewportReport = 0;
const _VIEWPORT_REPORT_INTERVAL = 1000; // ms

function _reportViewport() {
    if (!_state.map) return;
    const now = Date.now();
    if (now - _lastViewportReport < _VIEWPORT_REPORT_INTERVAL) return;
    _lastViewportReport = now;

    const center = _state.map.getCenter();
    const zoom = _state.map.getZoom();
    const radius = _estimateViewportRadius(zoom);

    // Emit on EventBus for the WebSocket manager to pick up
    EventBus.emit('viewport:update', {
        center_lat: center.lat,
        center_lng: center.lng,
        zoom: zoom,
        radius: radius,
    });
}

function _updateLayerHud() {
    if (!_state.layerHud || !_state.map) return;
    const layers = [];
    if (_state.showSatellite) layers.push('SAT');
    if (_state.showBuildings) layers.push('BLDG');
    if (_state.showRoads) layers.push('ROADS');
    if (_state.showGrid) layers.push('GRID');
    if (_state.showUnits && _state.showLabels) layers.push('UNITS');
    if (_state.showModels3d) layers.push('3D');
    if (_state.showGeoLayers) layers.push('GIS');
    if (_state.showPatrolRoutes) layers.push('PATROL');
    if (_state.showTerrain) layers.push('TERRAIN');
    if (_state.showHeatmap) layers.push('HEAT');
    if (_state.showWeaponRange) layers.push('WPNRNG');
    if (_state.showSwarmHull) layers.push('SWARM');
    if (_state.showSquadHulls) layers.push('SQUAD');
    if (_state.showHazardZones) layers.push('HAZARD');
    if (_state.showGeofenceZones) layers.push('GEOFENCE');
    if (_state.showHostileObjectives) layers.push('HOBJ');
    if (_state.showCrowdDensity) layers.push('CROWD');
    if (_state.showCoverPoints) layers.push('COVER');
    if (_state.showUnitSignals) layers.push('SIG');
    if (_state.showHostileIntel) layers.push('INTEL');
    if (_state.autoFollow) layers.push('AUTO');
    if (_state.showFog) layers.push('FOG');

    // FX off indicators (only show when something is disabled for debugging)
    const fxOff = [];
    if (!_state.showTracers) fxOff.push('TRCR');
    if (!_state.showExplosions) fxOff.push('EXPL');
    if (!_state.showParticles) fxOff.push('PART');
    if (!_state.showHitFlashes) fxOff.push('FLASH');
    if (!_state.showFloatingText) fxOff.push('TEXT');
    if (!_state.showKillFeed) fxOff.push('FEED');
    if (!_state.showScreenFx) fxOff.push('SFX');
    if (!_state.showBanners) fxOff.push('BNR');
    if (!_state.showHealthBars) fxOff.push('HP');
    if (!_state.showSelectionFx) fxOff.push('SEL');

    const zoom = _state.map.getZoom().toFixed(1);
    const pitch = _state.map.getPitch();
    const tilt = pitch > 10 ? '3D' : '2D';
    const mode = (_state.currentMode || 'observe').toUpperCase();
    let text = `${mode} ${tilt} z${zoom} | ${layers.join(' + ') || 'ALL OFF'}`;
    if (fxOff.length > 0) text += ` | -${fxOff.join(' -')}`;
    _state.layerHud.textContent = text;

    // Persist layer prefs on every toggle
    _saveLayerPrefs();

    // Notify Layers panel of state change
    EventBus.emit('map:layers-changed');
}

// ============================================================
// Grid Overlay (tactical grid lines using GeoJSON)
// ============================================================

/**
 * Build a GeoJSON FeatureCollection of grid lines centered on geoCenter.
 * Grid covers ~500m in each direction, 50m spacing.
 */
function _buildGridGeoJSON() {
    const center = _state.geoCenter;
    if (!center) return { type: 'FeatureCollection', features: [] };

    const R = 6378137; // Earth radius in meters
    const latRad = center.lat * Math.PI / 180;
    const mPerDegLat = Math.PI * R / 180;
    const mPerDegLng = mPerDegLat * Math.cos(latRad);

    const gridSize = 500; // meters from center
    const spacing = 50;   // meters between lines
    const features = [];

    // Vertical lines (constant longitude)
    for (let dx = -gridSize; dx <= gridSize; dx += spacing) {
        const lng = center.lng + dx / mPerDegLng;
        const latN = center.lat + gridSize / mPerDegLat;
        const latS = center.lat - gridSize / mPerDegLat;
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [[lng, latS], [lng, latN]],
            },
            properties: { major: dx % 100 === 0 },
        });
    }

    // Horizontal lines (constant latitude)
    for (let dy = -gridSize; dy <= gridSize; dy += spacing) {
        const lat = center.lat + dy / mPerDegLat;
        const lngW = center.lng - gridSize / mPerDegLng;
        const lngE = center.lng + gridSize / mPerDegLng;
        features.push({
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates: [[lngW, lat], [lngE, lat]],
            },
            properties: { major: dy % 100 === 0 },
        });
    }

    return { type: 'FeatureCollection', features };
}

function _addGridOverlay() {
    if (!_state.map) return;
    if (_state.map.getSource('tactical-grid')) return; // already added

    _state.map.addSource('tactical-grid', {
        type: 'geojson',
        data: _buildGridGeoJSON(),
    });

    // Minor grid lines (50m spacing)
    _state.map.addLayer({
        id: 'grid-minor',
        type: 'line',
        source: 'tactical-grid',
        filter: ['==', ['get', 'major'], false],
        paint: {
            'line-color': '#00f0ff',
            'line-width': 0.5,
            'line-opacity': 0.15,
        },
        layout: { 'visibility': _state.showGrid ? 'visible' : 'none' },
    });

    // Major grid lines (100m spacing)
    _state.map.addLayer({
        id: 'grid-major',
        type: 'line',
        source: 'tactical-grid',
        filter: ['==', ['get', 'major'], true],
        paint: {
            'line-color': '#00f0ff',
            'line-width': 1.0,
            'line-opacity': 0.3,
        },
        layout: { 'visibility': _state.showGrid ? 'visible' : 'none' },
    });

    console.log('[MAP-ML] Grid overlay added');
}

// ============================================================
// Map Mode Switching
// ============================================================

/**
 * Switch map visual state for the given mode.
 *
 * - observe: Surveillance. Satellite, buildings, labels. No grid, no 3D models. Top-down.
 * - tactical: Combat. Satellite, buildings, 3D models, grid, labels. Tilted 3D view.
 * - setup: Deployment. Satellite, buildings, grid, labels. Top-down.
 */
export function setMapMode(mode) {
    // Clean up ghost preview when leaving setup mode
    if (_state.currentMode === 'setup' && mode !== 'setup') {
        _clearSetupGhost();
    }
    _state.currentMode = mode;
    switch (mode) {
        case 'observe':
            setLayers({
                satellite: true,
                buildings: true,
                roads: true,
                models3d: false,
                domMarkers: true,
                grid: false,
                waterways: true,
                parks: true,
                geoLayers: true,
            });
            if (_state.map) {
                _state.map.easeTo({ pitch: 0, duration: 500 });
                _state.tiltMode = 'top-down';
            }
            // Clear weapon range circle in observe mode
            _clearWeaponRange();
            break;
        case 'tactical':
            setLayers({
                satellite: true,
                buildings: true,
                roads: true,
                models3d: true,
                domMarkers: true,
                grid: true,
                waterways: true,
                parks: true,
                geoLayers: false,
            });
            if (_state.map) {
                _state.map.easeTo({ pitch: 45, duration: 500 });
                _state.tiltMode = 'tilted';
            }
            break;
        case 'setup':
            setLayers({
                satellite: true,
                buildings: true,
                roads: false,
                models3d: true,
                domMarkers: true,
                grid: true,
                waterways: false,
                parks: false,
                geoLayers: false,
            });
            if (_state.map) {
                _state.map.easeTo({ pitch: 0, duration: 500 });
                _state.tiltMode = 'top-down';
            }
            break;
        default:
            console.warn(`[MAP-ML] Unknown mode: ${mode}`);
            return;
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Mode: ${mode}`);
}

// ============================================================
// Event Handlers
// ============================================================

function _onSelectionChanged(unitId) {
    _state.selectedUnitId = unitId;

    // When a unit is selected, show its latest thought (click-to-view).
    // This makes the thought visible even if it was below broadcast threshold
    // (stored locally from latestThought).
    if (unitId) {
        const unit = TritiumStore.units.get(unitId);
        if (unit && unit.latestThought && !unit.thoughtText) {
            // Surface the stored thought for display (auto-dismiss after duration)
            const lt = unit.latestThought;
            unit.thoughtText = lt.text;
            unit.thoughtEmotion = lt.emotion || 'neutral';
            unit.thoughtImportance = lt.importance || 'normal';
            unit.thoughtDuration = lt.duration || 5;
            unit.thoughtExpires = Date.now() + (lt.duration || 5) * 1000;
        }
    }

    // Re-render all markers to update selection highlight + z-index
    for (const [id, marker] of Object.entries(_state.unitMarkers)) {
        const unit = TritiumStore.units.get(id);
        if (unit) _updateMarkerElement(marker, unit);
        // Raise selected marker above overlapping neighbors
        const el = marker.getElement();
        const container = el ? el.closest('.maplibregl-marker') : null;
        if (container) {
            container.style.zIndex = (id === unitId) ? '50' : '';
        }
    }
    // Update weapon range circle for new selection (or clear if deselected)
    _updateWeaponRange();
}

function _onUnitsUpdated() {
    _updateUnits();
}

/**
 * Enter dispatch mode — next click on the map sends the unit to that location.
 * Triggered by DISPATCH button in unit inspector / device modal.
 */
function _onDispatchModeEnter(data) {
    if (!data || !data.id) return;
    _state.dispatchMode = true;
    _state.dispatchUnitId = data.id;
    if (_state.container) _state.container.style.cursor = 'crosshair';
    console.log(`[MAP-ML] Dispatch mode: click map to send ${data.id}`);
}

/**
 * Handle unit:patrol-mode — enter patrol point placement mode.
 * Similar to dispatch mode but sets patrol waypoints.
 */
function _onPatrolModeEnter(data) {
    if (!data || !data.id) return;
    _state.patrolMode = true;
    _state.patrolUnitId = data.id;
    _state.patrolWaypoints = [];
    if (_state.container) _state.container.style.cursor = 'crosshair';
    console.log(`[MAP-ML] Patrol mode: click map to set patrol points for ${data.id}`);
}

// ============================================================
// Patrol Route Drawing Tool (multi-waypoint with live preview)
// ============================================================

const PATROL_DRAW_SOURCE = 'patrol-draw-source';
const PATROL_DRAW_LINE   = 'patrol-draw-line';
const PATROL_DRAW_RUBBER = 'patrol-draw-rubber';
const PATROL_DRAW_DOTS   = 'patrol-draw-dots';

// ============================================================
// Geofence Polygon Drawing Mode (MapLibre)
// ============================================================

const GEOFENCE_DRAW_SOURCE = 'geofence-draw-source';
const GEOFENCE_DRAW_LINE   = 'geofence-draw-line';
const GEOFENCE_DRAW_FILL   = 'geofence-draw-fill';

function _onGeofenceDrawStart() {
    if (_state.geofenceDrawMode) _geofenceDrawCleanup();

    _state.geofenceDrawMode = true;
    _state.geofenceDrawVertices = [];
    _state.geofenceDrawMarkers = [];
    _state.geofenceDrawMouseLngLat = null;

    if (_state.container) _state.container.style.cursor = 'crosshair';
    if (_state.map) _state.map.doubleClickZoom.disable();

    // Init GeoJSON source/layers for preview
    _initGeofenceDrawLayers();

    EventBus.emit('toast:show', {
        message: 'Click to place vertices. Double-click or Enter to finish. Escape to cancel.',
        type: 'info',
    });
    console.log('[MAP-ML] Geofence draw mode started');
}

function _geofenceDrawAddVertex(gamePos, lngLat) {
    const idx = _state.geofenceDrawVertices.length + 1;
    _state.geofenceDrawVertices.push([gamePos.x, gamePos.y]);

    // Place numbered DOM marker
    const el = document.createElement('div');
    el.className = 'geofence-draw-vertex-marker';
    el.style.cssText = `
        width: 20px; height: 20px;
        border-radius: 50%;
        background: #00f0ff;
        border: 2px solid #003344;
        color: #0a0a0f;
        font-family: "JetBrains Mono", monospace;
        font-size: 10px;
        font-weight: bold;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: none;
        box-shadow: 0 0 8px rgba(0, 240, 255, 0.6);
    `;
    el.textContent = String(idx);

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat(lngLat)
        .addTo(_state.map);
    _state.geofenceDrawMarkers.push(marker);

    _updateGeofenceDrawPreview();
}

function _updateGeofenceDrawPreview() {
    if (!_state.map || !_state.map.getSource(GEOFENCE_DRAW_SOURCE)) return;

    const verts = _state.geofenceDrawVertices;
    const coords = verts.map(v => _gameToLngLat(v[0], v[1]));

    // Build polygon outline (close the ring if 3+ vertices)
    const lineCoords = [...coords];
    if (_state.geofenceDrawMouseLngLat && coords.length > 0) {
        lineCoords.push(_state.geofenceDrawMouseLngLat);
    }
    // Close back to first vertex for polygon preview
    if (lineCoords.length >= 3) {
        lineCoords.push(lineCoords[0]);
    }

    const features = [];
    if (lineCoords.length >= 2) {
        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: lineCoords },
            properties: {},
        });
    }
    // Show semi-transparent fill for 3+ vertices
    if (lineCoords.length >= 4) { // 3 vertices + closing = 4 coords
        features.push({
            type: 'Feature',
            geometry: { type: 'Polygon', coordinates: [lineCoords] },
            properties: {},
        });
    }

    _state.map.getSource(GEOFENCE_DRAW_SOURCE).setData({
        type: 'FeatureCollection',
        features,
    });
}

function _initGeofenceDrawLayers() {
    if (!_state.map) return;

    if (!_state.map.getSource(GEOFENCE_DRAW_SOURCE)) {
        _state.map.addSource(GEOFENCE_DRAW_SOURCE, {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
        });
        _state.map.addLayer({
            id: GEOFENCE_DRAW_FILL,
            type: 'fill',
            source: GEOFENCE_DRAW_SOURCE,
            filter: ['==', '$type', 'Polygon'],
            paint: {
                'fill-color': 'rgba(0, 240, 255, 0.15)',
                'fill-opacity': 1,
            },
        });
        _state.map.addLayer({
            id: GEOFENCE_DRAW_LINE,
            type: 'line',
            source: GEOFENCE_DRAW_SOURCE,
            filter: ['==', '$type', 'LineString'],
            paint: {
                'line-color': '#00f0ff',
                'line-width': 2,
                'line-dasharray': [4, 3],
            },
        });
    }
}

function _geofenceDrawFinish() {
    const verts = _state.geofenceDrawVertices;
    _state.geofenceDrawMode = false;
    _state.geofenceDrawMouseLngLat = null;

    if (_state.container) _state.container.style.cursor = '';
    if (_state.map) _state.map.doubleClickZoom.enable();

    _geofenceDrawCleanup();

    if (verts.length >= 3) {
        // Show the prompt dialog from map.js's _showGeofencePrompt equivalent
        _showGeofencePromptML(verts);
    } else {
        EventBus.emit('toast:show', { message: 'Need at least 3 vertices for a geofence zone', type: 'alert' });
        EventBus.emit('geofence:drawEnd', {});
    }
}

function _geofenceDrawCancel() {
    _state.geofenceDrawMode = false;
    _state.geofenceDrawMouseLngLat = null;

    if (_state.container) _state.container.style.cursor = '';
    if (_state.map) _state.map.doubleClickZoom.enable();

    _geofenceDrawCleanup();

    EventBus.emit('toast:show', { message: 'Geofence drawing cancelled', type: 'info' });
    EventBus.emit('geofence:drawEnd', {});
    console.log('[MAP-ML] Geofence draw cancelled');
}

function _geofenceDrawCleanup() {
    // Remove vertex markers
    for (const m of _state.geofenceDrawMarkers) m.remove();
    _state.geofenceDrawMarkers = [];
    _state.geofenceDrawVertices = [];

    // Clear preview layers
    try {
        if (_state.map) {
            if (_state.map.getLayer(GEOFENCE_DRAW_LINE)) _state.map.removeLayer(GEOFENCE_DRAW_LINE);
            if (_state.map.getLayer(GEOFENCE_DRAW_FILL)) _state.map.removeLayer(GEOFENCE_DRAW_FILL);
            if (_state.map.getSource(GEOFENCE_DRAW_SOURCE)) _state.map.removeSource(GEOFENCE_DRAW_SOURCE);
        }
    } catch (_) {}
}

/**
 * Show a cyberpunk-styled prompt for geofence zone name and type (MapLibre version).
 */
function _showGeofencePromptML(polygon) {
    const existing = document.getElementById('geofence-prompt-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'geofence-prompt-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;display:flex;align-items:center;justify-content:center';

    overlay.innerHTML = `
        <div style="background:#12121a;border:1px solid #00f0ff;border-radius:8px;padding:16px 20px;min-width:280px;max-width:360px;box-shadow:0 0 30px rgba(0,240,255,0.2)">
            <div style="color:#00f0ff;font-size:0.65rem;font-weight:bold;margin-bottom:10px;text-transform:uppercase;letter-spacing:2px">New Geofence Zone</div>
            <input id="geofence-prompt-name" type="text" placeholder="e.g. Perimeter Alpha"
                   style="width:100%;box-sizing:border-box;background:#0a0a0f;border:1px solid #333;color:#e0e0e0;padding:6px 8px;border-radius:4px;margin-bottom:10px;font-size:0.55rem">
            <div style="display:flex;gap:6px;margin-bottom:12px">
                <button class="geofence-type-btn" data-type="monitored"
                        style="flex:1;padding:5px;border:1px solid #00f0ff;background:rgba(0,240,255,0.1);color:#00f0ff;border-radius:4px;cursor:pointer;font-size:0.45rem;font-weight:bold">MONITORED</button>
                <button class="geofence-type-btn" data-type="restricted"
                        style="flex:1;padding:5px;border:1px solid #ff2a6d;background:transparent;color:#ff2a6d;border-radius:4px;cursor:pointer;font-size:0.45rem;font-weight:bold">RESTRICTED</button>
                <button class="geofence-type-btn" data-type="safe"
                        style="flex:1;padding:5px;border:1px solid #05ffa1;background:transparent;color:#05ffa1;border-radius:4px;cursor:pointer;font-size:0.45rem;font-weight:bold">SAFE</button>
            </div>
            <div style="display:flex;gap:8px;justify-content:flex-end">
                <button id="geofence-prompt-cancel" style="padding:5px 12px;background:transparent;border:1px solid #555;color:#aaa;border-radius:4px;cursor:pointer;font-size:0.45rem">CANCEL</button>
                <button id="geofence-prompt-save" style="padding:5px 12px;background:#00f0ff;border:none;color:#0a0a0f;border-radius:4px;cursor:pointer;font-weight:bold;font-size:0.45rem">SAVE ZONE</button>
            </div>
        </div>
    `;

    document.body.appendChild(overlay);

    const nameInput = overlay.querySelector('#geofence-prompt-name');
    const typeBtns = overlay.querySelectorAll('.geofence-type-btn');
    const saveBtn = overlay.querySelector('#geofence-prompt-save');
    const cancelBtn = overlay.querySelector('#geofence-prompt-cancel');
    let selectedType = 'monitored';

    nameInput.focus();

    typeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            selectedType = btn.dataset.type;
            typeBtns.forEach(b => b.style.background = 'transparent');
            const colorMap = { monitored: 'rgba(0,240,255,0.1)', restricted: 'rgba(255,42,109,0.1)', safe: 'rgba(5,255,161,0.1)' };
            btn.style.background = colorMap[selectedType] || 'transparent';
        });
    });

    saveBtn.addEventListener('click', async () => {
        const name = nameInput.value.trim() || `Zone ${Date.now() % 10000}`;
        overlay.remove();
        // Save zone directly to backend API (geofence panel may not be open)
        try {
            const resp = await fetch('/api/geofence/zones', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name,
                    polygon,
                    zone_type: selectedType,
                    alert_on_enter: true,
                    alert_on_exit: true,
                }),
            });
            if (resp.ok) {
                EventBus.emit('toast:show', { message: `Zone "${name}" created`, type: 'info' });
            } else {
                EventBus.emit('toast:show', { message: 'Failed to create zone', type: 'alert' });
            }
        } catch (_) {
            EventBus.emit('toast:show', { message: 'Failed to create zone', type: 'alert' });
        }
        // Still emit event so geofence panel refreshes if open
        EventBus.emit('geofence:zoneDrawn', { polygon, zone_type: selectedType, name });
        EventBus.emit('geofence:drawEnd', {});
        // Trigger re-fetch to show the new zone on map
        setTimeout(() => {
            _state._lastGeofenceFetch = 0;
            _updateGeofenceZones();
        }, 500);
    });

    cancelBtn.addEventListener('click', () => {
        overlay.remove();
        EventBus.emit('geofence:drawEnd', {});
    });

    nameInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') saveBtn.click();
        if (e.key === 'Escape') cancelBtn.click();
    });
}

/**
 * Enter patrol route drawing mode.
 * Emitted by patrol panel "DRAW ROUTE" button or toolbar button.
 */
function _onPatrolDrawRouteStart(data) {
    // Cancel any existing draw mode
    if (_state.patrolDrawMode) _patrolDrawCleanup();

    _state.patrolDrawMode = true;
    _state.patrolDrawUnitId = data?.unitId || null;
    _state.patrolDrawWaypoints = [];
    _state.patrolDrawMarkers = [];
    _state.patrolDrawMouseLngLat = null;

    if (_state.container) _state.container.style.cursor = 'crosshair';

    // Disable map double-click zoom during drawing
    if (_state.map) _state.map.doubleClickZoom.disable();

    // Create the drawing preview GeoJSON source and layers
    _initPatrolDrawLayers();

    // Show HUD
    _showPatrolDrawHud();

    const unit = _state.patrolDrawUnitId || 'unassigned';
    EventBus.emit('toast:show', {
        message: `Drawing patrol route${unit !== 'unassigned' ? ' for ' + unit : ''}. Click to place waypoints. Double-click or Enter to finish. Escape to cancel.`,
        type: 'info',
    });
    console.log(`[MAP-ML] Patrol draw mode started for: ${unit}`);
}

/**
 * Add a waypoint during patrol draw mode.
 */
function _patrolDrawAddWaypoint(gamePos, lngLat) {
    const idx = _state.patrolDrawWaypoints.length + 1;
    _state.patrolDrawWaypoints.push({ x: gamePos.x, y: gamePos.y });

    // Add a numbered DOM marker at the waypoint position
    const el = document.createElement('div');
    el.className = 'patrol-draw-wp-marker';
    el.style.cssText = `
        width: 24px; height: 24px;
        border-radius: 50%;
        background: #05ffa1;
        border: 2px solid #003322;
        color: #0a0a0f;
        font-family: "JetBrains Mono", monospace;
        font-size: 11px;
        font-weight: bold;
        display: flex;
        align-items: center;
        justify-content: center;
        pointer-events: none;
        box-shadow: 0 0 8px rgba(5, 255, 161, 0.6);
    `;
    el.textContent = String(idx);

    const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
        .setLngLat(lngLat)
        .addTo(_state.map);

    _state.patrolDrawMarkers.push(marker);

    // Update preview line GeoJSON
    _updatePatrolDrawPreview();

    // Update HUD
    _updatePatrolDrawHud();
}

/**
 * Build GeoJSON for the patrol draw preview (placed waypoints + rubber-band to cursor).
 */
function _buildPatrolDrawGeoJSON() {
    const features = [];
    const wps = _state.patrolDrawWaypoints;

    if (wps.length >= 2) {
        // Solid line through placed waypoints
        const coords = wps.map(w => _gameToLngLat(w.x, w.y));
        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: coords },
            properties: { kind: 'placed' },
        });
    }

    // Rubber-band line from last waypoint to mouse cursor
    if (wps.length >= 1 && _state.patrolDrawMouseLngLat) {
        const lastWp = wps[wps.length - 1];
        const lastLL = _gameToLngLat(lastWp.x, lastWp.y);
        features.push({
            type: 'Feature',
            geometry: { type: 'LineString', coordinates: [lastLL, _state.patrolDrawMouseLngLat] },
            properties: { kind: 'rubber' },
        });
    }

    // Point features at each waypoint (for circle layer)
    for (let i = 0; i < wps.length; i++) {
        features.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: _gameToLngLat(wps[i].x, wps[i].y) },
            properties: { index: i },
        });
    }

    return { type: 'FeatureCollection', features };
}

/**
 * Initialize MapLibre source and layers for patrol draw preview.
 */
function _initPatrolDrawLayers() {
    if (!_state.map) return;

    // Clean up any leftover layers from a previous draw
    _removePatrolDrawLayers();

    _state.map.addSource(PATROL_DRAW_SOURCE, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
    });

    // Dashed line for placed waypoints
    _state.map.addLayer({
        id: PATROL_DRAW_LINE,
        type: 'line',
        source: PATROL_DRAW_SOURCE,
        filter: ['all', ['==', '$type', 'LineString'], ['==', ['get', 'kind'], 'placed']],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
            'line-color': '#05ffa1',
            'line-width': 3,
            'line-opacity': 0.85,
            'line-dasharray': [4, 3],
        },
    });

    // Rubber-band line (thinner, more transparent)
    _state.map.addLayer({
        id: PATROL_DRAW_RUBBER,
        type: 'line',
        source: PATROL_DRAW_SOURCE,
        filter: ['all', ['==', '$type', 'LineString'], ['==', ['get', 'kind'], 'rubber']],
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
            'line-color': '#05ffa1',
            'line-width': 2,
            'line-opacity': 0.4,
            'line-dasharray': [2, 4],
        },
    });

    // Glow dots at each waypoint
    _state.map.addLayer({
        id: PATROL_DRAW_DOTS,
        type: 'circle',
        source: PATROL_DRAW_SOURCE,
        filter: ['==', '$type', 'Point'],
        paint: {
            'circle-radius': 6,
            'circle-color': '#05ffa1',
            'circle-opacity': 0.9,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#003322',
        },
    });
}

/**
 * Remove patrol draw preview layers and source.
 */
function _removePatrolDrawLayers() {
    if (!_state.map) return;
    try {
        if (_state.map.getLayer(PATROL_DRAW_DOTS)) _state.map.removeLayer(PATROL_DRAW_DOTS);
        if (_state.map.getLayer(PATROL_DRAW_RUBBER)) _state.map.removeLayer(PATROL_DRAW_RUBBER);
        if (_state.map.getLayer(PATROL_DRAW_LINE)) _state.map.removeLayer(PATROL_DRAW_LINE);
        if (_state.map.getSource(PATROL_DRAW_SOURCE)) _state.map.removeSource(PATROL_DRAW_SOURCE);
    } catch (_e) { /* layers may not exist */ }
}

/**
 * Update the GeoJSON data for patrol draw preview.
 */
function _updatePatrolDrawPreview() {
    if (!_state.map || !_state.map.getSource(PATROL_DRAW_SOURCE)) return;
    const geojson = _buildPatrolDrawGeoJSON();
    _state.map.getSource(PATROL_DRAW_SOURCE).setData(geojson);
}

/**
 * Show the patrol drawing HUD (top-center status bar).
 */
function _showPatrolDrawHud() {
    if (_state.patrolDrawHudEl) _state.patrolDrawHudEl.remove();
    const hud = document.createElement('div');
    hud.id = 'patrol-draw-hud';
    hud.style.cssText = `
        position: absolute;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        z-index: 100;
        background: rgba(10, 10, 15, 0.9);
        border: 1px solid #05ffa1;
        border-radius: 6px;
        padding: 8px 18px;
        font-family: "JetBrains Mono", monospace;
        font-size: 12px;
        color: #05ffa1;
        pointer-events: none;
        text-align: center;
        box-shadow: 0 0 12px rgba(5, 255, 161, 0.3);
    `;
    hud.innerHTML = 'PATROL ROUTE: 0 waypoints placed &mdash; click to add &mdash; double-click/Enter to finish &mdash; Escape to cancel';
    const container = _state.container || document.getElementById('map-container');
    if (container) container.appendChild(hud);
    _state.patrolDrawHudEl = hud;
}

/**
 * Update the patrol drawing HUD with current waypoint count.
 */
function _updatePatrolDrawHud() {
    if (!_state.patrolDrawHudEl) return;
    const n = _state.patrolDrawWaypoints.length;
    const unit = _state.patrolDrawUnitId || 'unassigned';
    _state.patrolDrawHudEl.innerHTML =
        `PATROL ROUTE for <span style="color:#00f0ff">${unit}</span>: ` +
        `<span style="color:#fcee0a">${n}</span> waypoint${n !== 1 ? 's' : ''} placed &mdash; ` +
        (n < 2 ? 'click to add (need 2+)' : 'double-click/Enter to finish') +
        ' &mdash; Escape to cancel';
}

/**
 * Finish patrol route drawing: prompt for name and POST to API.
 */
function _patrolDrawFinish() {
    if (!_state.patrolDrawMode) return;
    const wps = _state.patrolDrawWaypoints.slice();
    const unitId = _state.patrolDrawUnitId;

    if (wps.length < 2) {
        EventBus.emit('toast:show', { message: 'Need at least 2 waypoints for a patrol route', type: 'alert' });
        return;
    }

    // Clean up drawing state and visuals
    _patrolDrawCleanup();

    // Show a name prompt modal
    _showPatrolRouteNamePrompt(wps, unitId);
}

/**
 * Show a modal dialog prompting for route name, loop preference, and speed.
 */
function _showPatrolRouteNamePrompt(waypoints, unitId) {
    const overlay = document.createElement('div');
    overlay.id = 'patrol-route-prompt-overlay';
    overlay.style.cssText = `
        position: fixed; inset: 0; z-index: 9999;
        background: rgba(0,0,0,0.6);
        display: flex; align-items: center; justify-content: center;
    `;

    const modal = document.createElement('div');
    modal.style.cssText = `
        background: #0e0e14;
        border: 1px solid #05ffa1;
        border-radius: 8px;
        padding: 24px;
        width: 360px;
        font-family: "JetBrains Mono", monospace;
        color: #e0e0e0;
        box-shadow: 0 0 30px rgba(5, 255, 161, 0.2);
    `;

    const defaultName = unitId ? `Patrol-${unitId}` : `Patrol-${Date.now().toString(36)}`;

    modal.innerHTML = `
        <div style="color:#05ffa1; font-size:14px; font-weight:bold; margin-bottom:16px;">SAVE PATROL ROUTE</div>
        <div style="margin-bottom:12px;">
            <label style="font-size:11px; color:#888;">ROUTE NAME</label><br>
            <input id="patrol-route-name" type="text" value="${defaultName}" style="
                width:100%; box-sizing:border-box; padding:6px 10px; margin-top:4px;
                background:#1a1a2e; border:1px solid #333; border-radius:4px;
                color:#e0e0e0; font-family:inherit; font-size:12px;
            ">
        </div>
        <div style="margin-bottom:12px; display:flex; gap:16px;">
            <label style="font-size:11px; color:#888; display:flex; align-items:center; gap:6px;">
                <input id="patrol-route-loop" type="checkbox" checked> LOOP
            </label>
            <div style="flex:1;">
                <label style="font-size:11px; color:#888;">SPEED</label><br>
                <input id="patrol-route-speed" type="number" value="1.0" min="0.1" max="20" step="0.1" style="
                    width:80px; padding:4px 8px; margin-top:4px;
                    background:#1a1a2e; border:1px solid #333; border-radius:4px;
                    color:#e0e0e0; font-family:inherit; font-size:12px;
                ">
            </div>
        </div>
        <div style="font-size:11px; color:#888; margin-bottom:16px;">
            ${waypoints.length} waypoints${unitId ? ' for <span style="color:#00f0ff">' + unitId + '</span>' : ''}
        </div>
        <div style="display:flex; gap:8px; justify-content:flex-end;">
            <button id="patrol-route-cancel-btn" style="
                padding:6px 16px; background:#1a1a2e; border:1px solid #555;
                border-radius:4px; color:#aaa; cursor:pointer; font-family:inherit; font-size:11px;
            ">CANCEL</button>
            <button id="patrol-route-save-btn" style="
                padding:6px 16px; background:#05ffa1; border:none;
                border-radius:4px; color:#0a0a0f; cursor:pointer; font-family:inherit; font-size:11px; font-weight:bold;
            ">SAVE ROUTE</button>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // Focus the name input
    const nameInput = document.getElementById('patrol-route-name');
    if (nameInput) { nameInput.focus(); nameInput.select(); }

    function close() { overlay.remove(); }

    function save() {
        const name = (document.getElementById('patrol-route-name')?.value || defaultName).trim();
        const loop = document.getElementById('patrol-route-loop')?.checked ?? true;
        const speed = parseFloat(document.getElementById('patrol-route-speed')?.value) || 1.0;
        close();

        // POST to patrol routes API
        const wpsArray = waypoints.map(w => [w.x, w.y]);
        fetch('/api/patrols/routes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, waypoints: wpsArray, loop, speed }),
        }).then(resp => {
            if (!resp.ok) throw new Error('API error');
            return resp.json();
        }).then(route => {
            EventBus.emit('toast:show', {
                message: `Patrol route "${name}" saved (${waypoints.length} waypoints)`,
                type: 'info',
            });
            console.log('[MAP-ML] Patrol route created:', route);

            // If a unit was specified, assign it to the route
            if (unitId && route.route_id) {
                fetch('/api/patrols/assign', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ route_id: route.route_id, asset_id: unitId }),
                }).then(r => {
                    if (r.ok) {
                        EventBus.emit('toast:show', {
                            message: `${unitId} assigned to patrol "${name}"`,
                            type: 'info',
                        });
                    }
                }).catch(() => {});

                // Also send the patrol command via Amy for simulation engine
                const wpsJson = JSON.stringify(wpsArray);
                fetch('/api/amy/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'patrol', params: [unitId, wpsJson] }),
                }).catch(() => {});
            }
        }).catch(err => {
            console.error('[MAP-ML] Failed to create patrol route:', err);
            EventBus.emit('toast:show', { message: 'Failed to save patrol route', type: 'alert' });
        });
    }

    document.getElementById('patrol-route-cancel-btn')?.addEventListener('click', close);
    document.getElementById('patrol-route-save-btn')?.addEventListener('click', save);

    // Enter in name input saves, Escape closes
    function onKey(e) {
        if (e.key === 'Enter') { e.preventDefault(); save(); }
        if (e.key === 'Escape') { e.preventDefault(); close(); }
    }
    overlay.addEventListener('keydown', onKey);
}

/**
 * Cancel patrol route drawing and clean up.
 */
function _patrolDrawCancel() {
    if (!_state.patrolDrawMode) return;
    _patrolDrawCleanup();
    EventBus.emit('toast:show', { message: 'Patrol route drawing cancelled', type: 'info' });
}

/**
 * Clean up all patrol draw state, markers, layers, and HUD.
 */
function _patrolDrawCleanup() {
    _state.patrolDrawMode = false;
    _state.patrolDrawUnitId = null;
    _state.patrolDrawWaypoints = [];
    _state.patrolDrawMouseLngLat = null;

    // Remove numbered markers
    for (const m of _state.patrolDrawMarkers) {
        m.remove();
    }
    _state.patrolDrawMarkers = [];

    // Remove preview layers
    _removePatrolDrawLayers();

    // Remove HUD
    if (_state.patrolDrawHudEl) {
        _state.patrolDrawHudEl.remove();
        _state.patrolDrawHudEl = null;
    }

    // Restore cursor
    if (_state.container) _state.container.style.cursor = '';

    // Re-enable double-click zoom
    if (_state.map) _state.map.doubleClickZoom.enable();
}

/**
 * Handle double-click on map: finish patrol draw if active.
 */
function _onMapDblClick(e) {
    if (_state.geofenceDrawMode && _state.geofenceDrawVertices.length >= 3) {
        e.preventDefault();
        _geofenceDrawFinish();
        return;
    }
    if (_state.patrolDrawMode && _state.patrolDrawWaypoints.length >= 2) {
        e.preventDefault();
        _patrolDrawFinish();
        return;
    }
}

/**
 * Handle map:drawFinish event (Enter key) in MapLibre context.
 */
function _onDrawFinishML() {
    if (_state.geofenceDrawMode) {
        _geofenceDrawFinish();
        return;
    }
    if (_state.patrolDrawMode) {
        _patrolDrawFinish();
    }
}

/**
 * Handle map:drawCancel event (Escape key) in MapLibre context.
 */
function _onDrawCancelML() {
    if (_state.geofenceDrawMode) {
        _geofenceDrawCancel();
        return;
    }
    if (_state.patrolDrawMode) {
        _patrolDrawCancel();
    }
}

/**
 * Handle unit:aim-mode — enter aim targeting mode.
 * Click on the map to set aim direction for the unit.
 */
function _onAimModeEnter(data) {
    if (!data || !data.id) return;
    _state.aimMode = true;
    _state.aimUnitId = data.id;
    if (_state.container) _state.container.style.cursor = 'crosshair';
    console.log(`[MAP-ML] Aim mode: click map to aim ${data.id}`);
}

function _onDispatched(data) {
    // Draw dispatch arrow from unit to target position
    if (!data || !data.target) return;
    const unit = data.id ? TritiumStore.units.get(data.id) : null;
    if (unit && unit.position) {
        _state.dispatchArrows.push({
            fromX: unit.position.x,
            fromY: unit.position.y,
            toX: data.target.x,
            toY: data.target.y,
            time: Date.now(),
        });
    }
    console.log('[MAP-ML] Unit dispatched:', data);
}

/**
 * Handle unit:dispatch — the request to dispatch a unit (from context menu
 * or other UI). Sends the API call and emits unit:dispatched on success.
 */
function _onUnitDispatch(data) {
    if (!data || !data.unitId || !data.target) return;
    const unitId = data.unitId;
    const tx = data.target.x;
    const ty = data.target.y;

    // Send dispatch command to backend
    fetch('/api/amy/simulation/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unit_id: unitId, target: { x: tx, y: ty } }),
    }).then(resp => {
        if (resp.ok) {
            EventBus.emit('unit:dispatched', { id: unitId, target: { x: tx, y: ty } });
        } else {
            // Fallback: emit via Lua command endpoint
            fetch('/api/amy/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'dispatch', params: [unitId, tx, ty] }),
            }).then(r => {
                if (r.ok) {
                    EventBus.emit('unit:dispatched', { id: unitId, target: { x: tx, y: ty } });
                } else {
                    r.json().then(d => {
                        EventBus.emit('toast:show', { message: (d && d.detail) || 'Dispatch failed', type: 'alert' });
                    }).catch(() => {
                        EventBus.emit('toast:show', { message: 'Dispatch failed', type: 'alert' });
                    });
                }
            }).catch(() => {
                EventBus.emit('toast:show', { message: 'Dispatch failed', type: 'alert' });
            });
        }
    }).catch(() => {
        EventBus.emit('toast:show', { message: 'Dispatch failed: network error', type: 'alert' });
    });
}

function _onMapClick(e) {
    // Close context menu on any left click
    if (ContextMenu.isVisible()) {
        ContextMenu.hide();
        return;
    }

    // Dispatch mode: send selected unit to clicked location
    if (_state.dispatchMode && _state.dispatchUnitId) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        EventBus.emit('unit:dispatch', {
            unitId: _state.dispatchUnitId,
            target: { x: game.x, y: game.y },
        });
        _state.dispatchMode = false;
        _state.dispatchUnitId = null;
        if (_state.container) _state.container.style.cursor = '';
        return;
    }

    // Patrol mode (legacy 2-click): add waypoint for patrol route
    if (_state.patrolMode && _state.patrolUnitId) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        if (!_state.patrolWaypoints) _state.patrolWaypoints = [];
        _state.patrolWaypoints.push({ x: game.x, y: game.y });
        _onDropWaypoint({ x: game.x, y: game.y, unitId: _state.patrolUnitId });
        if (_state.patrolWaypoints.length >= 2) {
            const wpsJson = JSON.stringify(_state.patrolWaypoints.map(w => [w.x, w.y]));
            fetch('/api/amy/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    action: 'patrol',
                    params: [_state.patrolUnitId, wpsJson],
                }),
            }).then(resp => {
                if (resp.ok) EventBus.emit('toast:show', { message: 'Patrol route set', type: 'info' });
                else EventBus.emit('toast:show', { message: 'Patrol command rejected', type: 'alert' });
            }).catch(() => {
                EventBus.emit('toast:show', { message: 'Failed to set patrol', type: 'alert' });
            });
            _state.patrolMode = false;
            _state.patrolUnitId = null;
            _state.patrolWaypoints = [];
            if (_state.container) _state.container.style.cursor = '';
        }
        return;
    }

    // Geofence draw mode: add vertex to polygon
    if (_state.geofenceDrawMode) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        _geofenceDrawAddVertex(game, [e.lngLat.lng, e.lngLat.lat]);
        return;
    }

    // Patrol draw mode: add waypoint to multi-point route drawing
    if (_state.patrolDrawMode) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        _patrolDrawAddWaypoint(game, [e.lngLat.lng, e.lngLat.lat]);
        return;
    }

    // Aim mode: set turret aim direction via device command
    if (_state.aimMode && _state.aimUnitId) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        fetch(`/api/devices/${_state.aimUnitId}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                command: `motor.aim(${game.x.toFixed(1)},${game.y.toFixed(1)})`,
            }),
        }).then(resp => {
            if (resp.ok) EventBus.emit('toast:show', { message: 'Aim set', type: 'info' });
            else EventBus.emit('toast:show', { message: 'Aim command rejected', type: 'alert' });
        }).catch(() => {
            EventBus.emit('toast:show', { message: 'Aim failed', type: 'alert' });
        });
        _state.aimMode = false;
        _state.aimUnitId = null;
        if (_state.container) _state.container.style.cursor = '';
        return;
    }

    // Operator control: click-to-dispatch the controlled unit
    const ctrlUnitId = TritiumStore.get('controlledUnitId');
    if (ctrlUnitId) {
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        fetch(`/api/npc/${encodeURIComponent(ctrlUnitId)}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: `move_to:${game.x.toFixed(1)},${game.y.toFixed(1)}` }),
        }).then(resp => {
            if (resp.ok) {
                EventBus.emit('unit:dispatched', { id: ctrlUnitId, target: { x: game.x, y: game.y } });
            }
        }).catch(() => {});
        return;
    }

    // Setup mode: place a unit at the click location
    if (_state.currentMode === 'setup') {
        const unitType = (typeof window !== 'undefined' && window._setupPlacementType) || 'turret';
        const game = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);
        const displayName = unitType.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
        fetch('/api/game/place', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: displayName,
                asset_type: unitType,
                position: { x: game.x, y: game.y },
            }),
        }).then(resp => {
            if (resp.ok) {
                EventBus.emit('toast:show', { message: `${displayName} placed`, type: 'info' });
            } else {
                resp.json().then(d => {
                    EventBus.emit('toast:show', { message: d.detail || 'Placement failed', type: 'alert' });
                }).catch(() => {
                    EventBus.emit('toast:show', { message: 'Placement failed', type: 'alert' });
                });
            }
        }).catch(() => {
            EventBus.emit('toast:show', { message: 'Placement failed: network error', type: 'alert' });
        });
        return;
    }
    // Deselect if clicking empty area
    TritiumStore.set('map.selectedUnitId', null);
}

function _onMapRightClick(e) {
    e.preventDefault();
    if (!_state.geoCenter) return;

    const selectedId = _state.selectedUnitId || TritiumStore.get('map.selectedUnitId');
    const gamePos = _lngLatToGame(e.lngLat.lng, e.lngLat.lat);

    // Show context menu at the click position
    const container = _state.container || document.body;
    ContextMenu.show(container, selectedId, gamePos, e.point.x, e.point.y);
}

// ============================================================
// Exports: Same API surface as map3d.js
// ============================================================

export function destroyMap() {
    // Close context menu
    ContextMenu.hide();
    // Clean up ghost preview
    _clearSetupGhost();
    if (_state.map) {
        _state.map.remove();
        _state.map = null;
    }
    // Clean up markers
    for (const marker of Object.values(_state.unitMarkers)) {
        marker.remove();
    }
    _state.unitMarkers = {};
    // Clean up 3D unit meshes
    for (const group of Object.values(_state.unitMeshes)) {
        _dispose3DUnit(group);
    }
    _state.unitMeshes = {};
    // Clean up vision system
    if (_state.visionSystem) {
        _state.visionSystem.dispose();
        _state.visionSystem = null;
    }
    // Stop adaptive unit update loop
    clearInterval(_state._unitUpdateTimer);
    _state._unitUpdateTimer = null;
    _state._meterScale = null;
    // Stop hostile objective polling
    _stopHostileObjectivePoll();
    // Clean up hostile intel HUD
    if (_state._hostileIntelEl) {
        _state._hostileIntelEl.remove();
        _state._hostileIntelEl = null;
    }
    _state.initialized = false;
    console.log('[MAP-ML] Map destroyed');
}

export function toggleSatellite() {
    _state.showSatellite = !_state.showSatellite;
    if (_state.map) {
        _state.map.setLayoutProperty('satellite-layer', 'visibility',
            _state.showSatellite ? 'visible' : 'none');
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Satellite ${_state.showSatellite ? 'ON' : 'OFF'}`);
}

export function toggleRoads() {
    _state.showRoads = !_state.showRoads;
    if (_state.map) {
        _state.map.setLayoutProperty('road-overlay-layer', 'visibility',
            _state.showRoads ? 'visible' : 'none');
        if (_state.map.getLayer('roads-line')) {
            _state.map.setLayoutProperty('roads-line', 'visibility',
                _state.showRoads ? 'visible' : 'none');
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Roads ${_state.showRoads ? 'ON' : 'OFF'}`);
}

export function toggleBuildings() {
    _state.showBuildings = !_state.showBuildings;
    if (_state.map) {
        _state.map.setLayoutProperty('buildings-3d', 'visibility',
            _state.showBuildings ? 'visible' : 'none');
        _state.map.setLayoutProperty('buildings-outline', 'visibility',
            _state.showBuildings ? 'visible' : 'none');
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Buildings ${_state.showBuildings ? 'ON' : 'OFF'}`);
}

export function toggleGrid() {
    _state.showGrid = !_state.showGrid;
    if (_state.map) {
        const vis = _state.showGrid ? 'visible' : 'none';
        if (_state.map.getLayer('grid-minor')) {
            _state.map.setLayoutProperty('grid-minor', 'visibility', vis);
        }
        if (_state.map.getLayer('grid-major')) {
            _state.map.setLayoutProperty('grid-major', 'visibility', vis);
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Grid ${_state.showGrid ? 'ON' : 'OFF'}`);
}

export function toggleFog() {
    _state.showFog = !_state.showFog;
    if (_state.visionSystem) {
        if (_state.showFog) {
            _state.visionSystem.enable();
        } else {
            _state.visionSystem.disable();
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Fog ${_state.showFog ? 'ON' : 'OFF'}`);
}

export function toggleTerrain() {
    if (_state.map && typeof _state.map.setTerrain !== 'function') {
        console.warn('[MAP-ML] Terrain API not available in this MapLibre version');
        return;
    }
    _state.showTerrain = !_state.showTerrain;
    if (_state.map) {
        if (_state.showTerrain) {
            _state.map.setTerrain({
                source: 'terrain-dem',
                exaggeration: _state.terrainExaggeration,
            });
            // Sky atmosphere for terrain horizon (matches CYBERCORE dark theme)
            if (typeof _state.map.setSky === 'function') {
                _state.map.setSky({
                    'sky-color': '#060609',
                    'horizon-color': '#0a1020',
                    'fog-color': '#060609',
                    'fog-ground-blend': 0.5,
                    'horizon-fog-blend': 0.8,
                    'sky-horizon-blend': 0.9,
                    'atmosphere-blend': 0.6,
                });
            }
        } else {
            _state.map.setTerrain(null);
            if (typeof _state.map.setSky === 'function') {
                _state.map.setSky(null);
            }
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Terrain ${_state.showTerrain ? 'ON' : 'OFF'} (exaggeration: ${_state.terrainExaggeration})`);
}

export function toggleUnits() {
    _state.showUnits = !_state.showUnits;
    // Immediately show/hide all DOM unit markers
    for (const marker of Object.values(_state.unitMarkers)) {
        const el = marker.getElement();
        if (el) el.style.display = _state.showUnits ? '' : 'none';
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Unit Markers ${_state.showUnits ? 'ON' : 'OFF'}`);
}

export function toggleLabels() {
    _state.showLabels = !_state.showLabels;
    // _updateUnits() runs at 10Hz and respects showLabels in its display condition
    _updateLayerHud();
    console.log(`[MAP-ML] Labels ${_state.showLabels ? 'ON' : 'OFF'}`);
}

export function toggleModels() {
    _state.showModels3d = !_state.showModels3d;
    if (_state.threeRoot) _state.threeRoot.visible = _state.showModels3d;
    _updateLayerHud();
    console.log(`[MAP-ML] 3D Models ${_state.showModels3d ? 'ON' : 'OFF'}`);
}

export function toggleWaterways() {
    _state.showWaterways = !_state.showWaterways;
    if (_state.map) {
        const style = _state.map.getStyle();
        if (style && style.layers) {
            for (const layer of style.layers) {
                if (layer.id.includes('water')) {
                    try { _state.map.setLayoutProperty(layer.id, 'visibility', _state.showWaterways ? 'visible' : 'none'); } catch (e) {}
                }
            }
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Waterways ${_state.showWaterways ? 'ON' : 'OFF'}`);
}

export function toggleParks() {
    _state.showParks = !_state.showParks;
    if (_state.map) {
        const style = _state.map.getStyle();
        if (style && style.layers) {
            for (const layer of style.layers) {
                if (layer.id.includes('park') || layer.id.includes('green') || layer.id.includes('landuse')) {
                    try { _state.map.setLayoutProperty(layer.id, 'visibility', _state.showParks ? 'visible' : 'none'); } catch (e) {}
                }
            }
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Parks ${_state.showParks ? 'ON' : 'OFF'}`);
}

export function toggleTilt() {
    if (!_state.map) return;
    const currentPitch = _state.map.getPitch();
    const targetPitch = currentPitch > 10 ? PITCH_TOPDOWN : PITCH_DEFAULT;
    _state.tiltMode = targetPitch > 10 ? 'tilted' : 'top-down';
    _state.map.easeTo({ pitch: targetPitch, duration: 500 });
    _updateLayerHud();
    console.log(`[MAP-ML] Tilt: ${_state.tiltMode}`);
}

export function toggleMesh() {
    _state.showMesh = !_state.showMesh;
    // Sync with meshState global if available
    if (typeof meshState !== 'undefined') {
        meshState.visible = _state.showMesh;
    }
    // Mesh overlay is drawn on the canvas overlay, not a MapLibre layer,
    // so just toggle the state flag and the render loop will pick it up.
    console.log(`[MAP-ML] Mesh network ${_state.showMesh ? 'ON' : 'OFF'}`);
}

export function toggleMeshNodes() {
    _state.showMeshNodes = !_state.showMeshNodes;
    if (typeof meshState !== 'undefined') meshState.showNodes = _state.showMeshNodes;
    console.log(`[MAP-ML] Mesh nodes ${_state.showMeshNodes ? 'ON' : 'OFF'}`);
}

export function toggleMeshLinks() {
    _state.showMeshLinks = !_state.showMeshLinks;
    if (typeof meshState !== 'undefined') meshState.showLinks = _state.showMeshLinks;
    console.log(`[MAP-ML] Mesh links ${_state.showMeshLinks ? 'ON' : 'OFF'}`);
}

export function toggleMeshCoverage() {
    _state.showMeshCoverage = !_state.showMeshCoverage;
    if (typeof meshState !== 'undefined') meshState.showCoverage = _state.showMeshCoverage;
    console.log(`[MAP-ML] Mesh coverage ${_state.showMeshCoverage ? 'ON' : 'OFF'}`);
}

export function togglePredictionCones() {
    _state.showPredictionCones = !_state.showPredictionCones;
    console.log(`[MAP-ML] Prediction cones ${_state.showPredictionCones ? 'ON' : 'OFF'}`);
}

export function togglePatrolRoutes() {
    _state.showPatrolRoutes = !_state.showPatrolRoutes;
    if (_state.map) {
        const vis = _state.showPatrolRoutes ? 'visible' : 'none';
        if (_state.map.getLayer(PATROL_ROUTES_LINE)) {
            _state.map.setLayoutProperty(PATROL_ROUTES_LINE, 'visibility', vis);
        }
        if (_state.map.getLayer(PATROL_ROUTES_DOTS)) {
            _state.map.setLayoutProperty(PATROL_ROUTES_DOTS, 'visibility', vis);
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Patrol Routes ${_state.showPatrolRoutes ? 'ON' : 'OFF'}`);
}

/**
 * Toggle GIS data layers (traffic signals, water towers, power lines, etc.)
 */
export function toggleGeoLayers() {
    _state.showGeoLayers = !_state.showGeoLayers;
    const vis = _state.showGeoLayers ? 'visible' : 'none';
    for (const id of _state.geoLayerIds) {
        if (_state.map && _state.map.getLayer(id)) {
            try { _state.map.setLayoutProperty(id, 'visibility', vis); } catch (e) {}
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] GIS Layers ${_state.showGeoLayers ? 'ON' : 'OFF'}`);
}

/**
 * Toggle NPC thought bubbles on/off.
 */
export function toggleThoughts() {
    _state.showThoughts = !_state.showThoughts;
    // Immediately hide/show existing bubbles
    if (!_state.showThoughts) {
        _state._visibleThoughtIds.clear();
    }
    for (const id of Object.keys(_state.unitMarkers)) {
        const el = _state.unitMarkers[id].getElement();
        const bubble = el.querySelector('.thought-bubble');
        if (bubble && !_state.showThoughts) bubble.style.display = 'none';
    }
    console.log(`[MAP-ML] Thought bubbles ${_state.showThoughts ? 'ON' : 'OFF'}`);
}

export function toggleAllLayers() {
    // Decide direction: if most default-on layers are currently on, turn OFF.
    const defaultOnKeys = [
        'showSatellite', 'showRoads', 'showBuildings', 'showWaterways', 'showParks',
        'showUnits', 'showLabels', 'showMesh', 'showPatrolRoutes',
        'showHealthBars', 'showSelectionFx', 'showWeaponRange',
        'showSquadHulls', 'showSwarmHull', 'showHostileObjectives', 'showHostileIntel',
        'showHazardZones', 'showUnitSignals', 'showCrowdDensity', 'showThoughts',
        'showTracers', 'showExplosions', 'showParticles', 'showHitFlashes', 'showFloatingText',
        'showKillFeed', 'showScreenFx', 'showBanners', 'showLayerHud',
    ];
    const onCount = defaultOnKeys.filter(k => _state[k]).length;
    const target = onCount <= defaultOnKeys.length / 2;

    // Use the proven setLayers(allMapLayers) path for base map + markers + 3D + GIS
    setLayers({ allMapLayers: target });

    // Set the FX/overlay/decoration flags that setLayers doesn't cover
    const fxKeys = [
        'showGrid', 'showMesh', 'showPatrolRoutes',
        'showHealthBars', 'showSelectionFx', 'showWeaponRange',
        'showSquadHulls', 'showSwarmHull', 'showHostileObjectives', 'showHostileIntel',
        'showCoverPoints', 'showHazardZones', 'showUnitSignals', 'showCrowdDensity',
        'showThoughts',
        'showTracers', 'showExplosions', 'showParticles', 'showHitFlashes', 'showFloatingText',
        'showKillFeed', 'showScreenFx', 'showBanners', 'showLayerHud',
        'showFog', 'showTerrain',
    ];
    for (const k of fxKeys) _state[k] = target;

    // Apply DOM side effects for overlays
    if (_state.threeEffectsRoot) _state.threeEffectsRoot.visible = target;
    const feed = _state.container?.querySelector('.fx-kill-feed');
    if (feed) feed.style.display = target ? '' : 'none';
    if (_state.layerHud) _state.layerHud.style.display = target ? '' : 'none';

    // Grid + patrol route layers
    if (_state.map) {
        const vis = target ? 'visible' : 'none';
        if (_state.map.getLayer('grid-minor')) {
            try { _state.map.setLayoutProperty('grid-minor', 'visibility', vis); } catch (e) {}
        }
        if (_state.map.getLayer('grid-major')) {
            try { _state.map.setLayoutProperty('grid-major', 'visibility', vis); } catch (e) {}
        }
        if (_state.map.getLayer(PATROL_ROUTES_LINE)) {
            try { _state.map.setLayoutProperty(PATROL_ROUTES_LINE, 'visibility', vis); } catch (e) {}
        }
        if (_state.map.getLayer(PATROL_ROUTES_DOTS)) {
            try { _state.map.setLayoutProperty(PATROL_ROUTES_DOTS, 'visibility', vis); } catch (e) {}
        }
    }

    _updateLayerHud();
    console.log(`[MAP-ML] All layers ${target ? 'ON' : 'OFF'}`);
}

export function toggleTracers() {
    _state.showTracers = !_state.showTracers;
    _updateLayerHud();
    console.log(`[MAP-ML] Tracers ${_state.showTracers ? 'ON' : 'OFF'}`);
}

export function toggleExplosions() {
    _state.showExplosions = !_state.showExplosions;
    _updateLayerHud();
    console.log(`[MAP-ML] Explosions ${_state.showExplosions ? 'ON' : 'OFF'}`);
}

export function toggleParticles() {
    _state.showParticles = !_state.showParticles;
    _updateLayerHud();
    console.log(`[MAP-ML] Particles ${_state.showParticles ? 'ON' : 'OFF'}`);
}

export function toggleHitFlashes() {
    _state.showHitFlashes = !_state.showHitFlashes;
    _updateLayerHud();
    console.log(`[MAP-ML] Hit Flashes ${_state.showHitFlashes ? 'ON' : 'OFF'}`);
}

export function toggleFloatingText() {
    _state.showFloatingText = !_state.showFloatingText;
    _updateLayerHud();
    console.log(`[MAP-ML] Floating Text ${_state.showFloatingText ? 'ON' : 'OFF'}`);
}

export function toggleKillFeed() {
    _state.showKillFeed = !_state.showKillFeed;
    const feed = _state.container?.querySelector('.fx-kill-feed');
    if (feed) feed.style.display = _state.showKillFeed ? '' : 'none';
    _updateLayerHud();
    console.log(`[MAP-ML] Kill Feed ${_state.showKillFeed ? 'ON' : 'OFF'}`);
}

export function toggleScreenFx() {
    _state.showScreenFx = !_state.showScreenFx;
    _updateLayerHud();
    console.log(`[MAP-ML] Screen FX ${_state.showScreenFx ? 'ON' : 'OFF'}`);
}

export function toggleBanners() {
    _state.showBanners = !_state.showBanners;
    _updateLayerHud();
    console.log(`[MAP-ML] Banners ${_state.showBanners ? 'ON' : 'OFF'}`);
}

export function toggleLayerHud() {
    _state.showLayerHud = !_state.showLayerHud;
    if (_state.layerHud) {
        _state.layerHud.style.display = _state.showLayerHud ? '' : 'none';
    }
    console.log(`[MAP-ML] Layer HUD ${_state.showLayerHud ? 'ON' : 'OFF'}`);
}

export function toggleHealthBars() {
    _state.showHealthBars = !_state.showHealthBars;
    _updateLayerHud();
    console.log(`[MAP-ML] Health Bars ${_state.showHealthBars ? 'ON' : 'OFF'}`);
}

export function toggleSelectionFx() {
    _state.showSelectionFx = !_state.showSelectionFx;
    _updateLayerHud();
    console.log(`[MAP-ML] Selection FX ${_state.showSelectionFx ? 'ON' : 'OFF'}`);
}

export function toggleWeaponRange() {
    _state.showWeaponRange = !_state.showWeaponRange;
    if (!_state.showWeaponRange) _clearWeaponRange();
    _updateLayerHud();
    console.log(`[MAP-ML] Weapon Range ${_state.showWeaponRange ? 'ON' : 'OFF'}`);
}

export function toggleHeatmap() {
    _state.showHeatmap = !_state.showHeatmap;
    if (_state.map) {
        if (_state.map.getLayer(COMBAT_HEATMAP_LAYER)) {
            _state.map.setLayoutProperty(COMBAT_HEATMAP_LAYER, 'visibility',
                _state.showHeatmap ? 'visible' : 'none');
        }
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Heatmap ${_state.showHeatmap ? 'ON' : 'OFF'}`);
}

export function toggleSwarmHull() {
    _state.showSwarmHull = !_state.showSwarmHull;
    if (!_state.showSwarmHull) _clearSwarmHull();
    _updateLayerHud();
    console.log(`[MAP-ML] Swarm Hull ${_state.showSwarmHull ? 'ON' : 'OFF'}`);
}

export function toggleSquadHulls() {
    _state.showSquadHulls = !_state.showSquadHulls;
    if (!_state.showSquadHulls) _clearSquadHulls();
    _updateLayerHud();
    console.log(`[MAP-ML] Squad Hulls ${_state.showSquadHulls ? 'ON' : 'OFF'}`);
}

export function toggleHazardZones() {
    _state.showHazardZones = !_state.showHazardZones;
    if (!_state.showHazardZones) _clearHazardZones();
    _updateLayerHud();
    console.log(`[MAP-ML] Hazard Zones ${_state.showHazardZones ? 'ON' : 'OFF'}`);
}

export function toggleGeofenceZones() {
    _state.showGeofenceZones = !_state.showGeofenceZones;
    if (!_state.showGeofenceZones) _clearGeofenceZones();
    _updateLayerHud();
    console.log(`[MAP-ML] Geofence Zones ${_state.showGeofenceZones ? 'ON' : 'OFF'}`);
}

export function toggleHostileObjectives() {
    _state.showHostileObjectives = !_state.showHostileObjectives;
    if (!_state.showHostileObjectives) _clearHostileObjectives();
    _updateLayerHud();
    console.log(`[MAP-ML] Hostile Objectives ${_state.showHostileObjectives ? 'ON' : 'OFF'}`);
}

export function toggleCrowdDensity() {
    _state.showCrowdDensity = !_state.showCrowdDensity;
    if (!_state.showCrowdDensity) _clearCrowdDensity();
    _updateLayerHud();
    console.log(`[MAP-ML] Crowd Density ${_state.showCrowdDensity ? 'ON' : 'OFF'}`);
}

export function toggleCoverPoints() {
    _state.showCoverPoints = !_state.showCoverPoints;
    if (!_state.showCoverPoints) _clearCoverPoints();
    _updateLayerHud();
    console.log(`[MAP-ML] Cover Points ${_state.showCoverPoints ? 'ON' : 'OFF'}`);
}

export function toggleUnitSignals() {
    _state.showUnitSignals = !_state.showUnitSignals;
    if (!_state.showUnitSignals) _clearUnitSignals();
    _updateLayerHud();
    console.log(`[MAP-ML] Unit Signals ${_state.showUnitSignals ? 'ON' : 'OFF'}`);
}

export function toggleHostileIntel() {
    _state.showHostileIntel = !_state.showHostileIntel;
    if (!_state.showHostileIntel && _state._hostileIntelEl) {
        _state._hostileIntelEl.style.display = 'none';
    }
    _updateLayerHud();
    console.log(`[MAP-ML] Hostile Intel ${_state.showHostileIntel ? 'ON' : 'OFF'}`);
}

export function toggleAutoFollow() {
    if (_state.autoFollow) {
        _stopAutoFollow();
    } else {
        _startAutoFollow();
    }
}

export function toggleCoverageOverlap() {
    _state.showCoverageOverlap = !_state.showCoverageOverlap;
    if (_state.showCoverageOverlap) {
        _fetchAndRenderCoverage();
    } else {
        _removeCoverageLayer();
    }
    console.log(`[MAP-ML] Coverage Overlap ${_state.showCoverageOverlap ? 'ON' : 'OFF'}`);
}

// Coverage overlap rendering
const COVERAGE_SOURCE = 'coverage-overlap-src';
const COVERAGE_FILL_1 = 'coverage-overlap-fill-1';
const COVERAGE_FILL_2 = 'coverage-overlap-fill-2';
const COVERAGE_FILL_3 = 'coverage-overlap-fill-3';

async function _fetchAndRenderCoverage() {
    if (!_state.map) return;

    try {
        const resp = await fetch('/api/fleet/coverage');
        const data = await resp.ok ? resp.json() : { coverage: [] };
        const coverage = (await data).coverage || data.coverage || [];

        // Build GeoJSON circles from sensor positions
        // Each sensor gets a coverage radius circle; overlaps are computed via layering
        const features = [];
        const sensorPositions = [];

        for (const sensor of coverage) {
            const lng = sensor.longitude || sensor.lng;
            const lat = sensor.latitude || sensor.lat;
            const radius = sensor.range_m || sensor.radius || 50;
            if (lng === undefined || lat === undefined) continue;
            sensorPositions.push({ lng, lat, radius, id: sensor.device_id || sensor.id });

            // Create a circle polygon (36 vertices)
            const circle = _createCirclePolygon(lng, lat, radius, 36);
            features.push({
                type: 'Feature',
                properties: { sensor_count: 1, sensor_id: sensor.device_id || sensor.id },
                geometry: { type: 'Polygon', coordinates: [circle] },
            });
        }

        // If no sensors have positions, generate grid-based coverage from unit positions
        if (features.length === 0) {
            // Fallback: use unit positions from store as sensor locations
            TritiumStore.units.forEach((u, id) => {
                const type = (u.asset_type || u.type || '').toLowerCase();
                if (type.includes('sensor') || type.includes('camera') || type === 'ble_device' || type === 'mesh_radio') {
                    const pos = u.position;
                    if (pos && pos.x !== undefined) {
                        const lngLat = _gameToLngLat(pos.x, pos.y);
                        const radius = type.includes('camera') ? 30 : type === 'mesh_radio' ? 100 : 50;
                        const circle = _createCirclePolygon(lngLat[0], lngLat[1], radius, 36);
                        features.push({
                            type: 'Feature',
                            properties: { sensor_count: 1 },
                            geometry: { type: 'Polygon', coordinates: [circle] },
                        });
                    }
                }
            });
        }

        const geojson = { type: 'FeatureCollection', features };

        // Remove old layers
        _removeCoverageLayer();

        // Add source and layers
        _state.map.addSource(COVERAGE_SOURCE, { type: 'geojson', data: geojson });

        // Single-coverage layer (subtle green)
        _state.map.addLayer({
            id: COVERAGE_FILL_1,
            type: 'fill',
            source: COVERAGE_SOURCE,
            paint: {
                'fill-color': '#05ffa1',
                'fill-opacity': 0.06,
            },
        });

        // For overlap detection, we add the same data again with different opacity
        // MapLibre renders overlapping polygons with additive opacity
        _state.map.addLayer({
            id: COVERAGE_FILL_2,
            type: 'fill',
            source: COVERAGE_SOURCE,
            paint: {
                'fill-color': '#00f0ff',
                'fill-opacity': 0.05,
            },
        });

        // Outline for each sensor coverage area
        _state.map.addLayer({
            id: COVERAGE_FILL_3,
            type: 'line',
            source: COVERAGE_SOURCE,
            paint: {
                'line-color': '#05ffa1',
                'line-opacity': 0.25,
                'line-width': 1,
                'line-dasharray': [4, 4],
            },
        });

    } catch (e) {
        console.warn('[MAP-ML] Coverage fetch failed:', e);
        // Render fallback with unit positions
    }
}

function _removeCoverageLayer() {
    if (!_state.map) return;
    for (const layerId of [COVERAGE_FILL_1, COVERAGE_FILL_2, COVERAGE_FILL_3]) {
        if (_state.map.getLayer(layerId)) {
            try { _state.map.removeLayer(layerId); } catch (e) {}
        }
    }
    if (_state.map.getSource(COVERAGE_SOURCE)) {
        try { _state.map.removeSource(COVERAGE_SOURCE); } catch (e) {}
    }
}

function _createCirclePolygon(lng, lat, radiusMeters, numVertices) {
    const coords = [];
    const earthRadius = 6371000;
    const angularDist = radiusMeters / earthRadius;
    const latRad = lat * Math.PI / 180;
    const lngRad = lng * Math.PI / 180;

    for (let i = 0; i <= numVertices; i++) {
        const bearing = (2 * Math.PI * i) / numVertices;
        const vertLat = Math.asin(
            Math.sin(latRad) * Math.cos(angularDist) +
            Math.cos(latRad) * Math.sin(angularDist) * Math.cos(bearing)
        );
        const vertLng = lngRad + Math.atan2(
            Math.sin(bearing) * Math.sin(angularDist) * Math.cos(latRad),
            Math.cos(angularDist) - Math.sin(latRad) * Math.sin(vertLat)
        );
        coords.push([vertLng * 180 / Math.PI, vertLat * 180 / Math.PI]);
    }
    return coords;
}

export function centerOnAction() {
    let sumLng = 0, sumLat = 0, count = 0;
    TritiumStore.units.forEach(u => {
        if (u.alliance === 'hostile') {
            const pos = u.position || {};
            const lngLat = _gameToLngLat(pos.x || 0, pos.y || 0);
            sumLng += lngLat[0];
            sumLat += lngLat[1];
            count++;
        }
    });
    if (count > 0 && _state.map) {
        _state.map.flyTo({
            center: [sumLng / count, sumLat / count],
            zoom: Math.max(_state.map.getZoom(), 17),
            duration: 1000,
        });
    }
}

// ── Camera Markers ─────────────────────────────────────────────────────
// Shows camera icons on the tactical map for cameras that have lat/lng.

const CAMERA_SOURCE_ID = 'tritium-camera-markers';
const CAMERA_FOV_SOURCE_ID = 'tritium-camera-fov';
const CAMERA_LAYER_CIRCLE = 'tritium-camera-circle';
const CAMERA_LAYER_GLOW = 'tritium-camera-glow';
const CAMERA_LAYER_LABEL = 'tritium-camera-label';
const CAMERA_LAYER_ICON = 'tritium-camera-icon';
const CAMERA_LAYER_FOV = 'tritium-camera-fov-fill';
const CAMERA_LAYER_FOV_LINE = 'tritium-camera-fov-line';

/**
 * Build a GeoJSON polygon for a camera FOV cone (sector shape).
 * heading: degrees clockwise from north, fovAngle: total FOV in degrees,
 * rangeMeterss: how far the cone extends from the camera.
 */
function _buildFovConePolygon(lng, lat, heading, fovAngle, rangeMeters) {
    const steps = 24;
    const halfFov = fovAngle / 2;
    const startBearing = heading - halfFov;
    const endBearing = heading + halfFov;
    const coords = [[lng, lat]]; // start at camera position

    for (let i = 0; i <= steps; i++) {
        const bearing = startBearing + (endBearing - startBearing) * (i / steps);
        const bearingRad = (bearing * Math.PI) / 180;
        // Approximate: 1 degree lat ~ 111320m, 1 degree lng ~ 111320 * cos(lat)
        const latRad = (lat * Math.PI) / 180;
        const dLat = (rangeMeters * Math.cos(bearingRad)) / 111320;
        const dLng = (rangeMeters * Math.sin(bearingRad)) / (111320 * Math.cos(latRad));
        coords.push([lng + dLng, lat + dLat]);
    }
    coords.push([lng, lat]); // close the polygon
    return coords;
}

/**
 * Fetch cameras from the REST API and emit cameras:changed so the map
 * renders camera markers.  Called on map load and when demo starts.
 */
let _cameraGeoSynced = false;

async function _fetchCamerasForMap() {
    try {
        const resp = await fetch('/api/camera-feeds/');
        if (!resp.ok) return;
        const data = await resp.json();
        const cameras = Array.isArray(data) ? data : (data.cameras || data.feeds || []);
        if (cameras.length > 0) {
            console.log(`[MAP-ML] Fetched ${cameras.length} camera(s) for map markers`);
            _onCamerasChanged({ cameras });

            // When cameras first appear (e.g. demo mode started after page load),
            // re-fetch geo reference in case demo mode updated it, then fly there.
            if (!_cameraGeoSynced && _state.map) {
                _cameraGeoSynced = true;
                try {
                    const geoResp = await fetch('/api/geo/reference');
                    if (geoResp.ok) {
                        const geoData = await geoResp.json();
                        if (geoData.initialized && geoData.lat && geoData.lng) {
                            const curCenter = _state.map.getCenter();
                            const dist = Math.abs(curCenter.lat - geoData.lat) + Math.abs(curCenter.lng - geoData.lng);
                            // Only fly if geo reference is significantly different from current center
                            if (dist > 0.01) {
                                console.log(`[MAP-ML] Geo reference changed, flying to ${geoData.lat.toFixed(4)}, ${geoData.lng.toFixed(4)}`);
                                _state.geoCenter = { lat: geoData.lat, lng: geoData.lng };
                                _state.map.flyTo({ center: [geoData.lng, geoData.lat], zoom: 17, duration: 1500 });
                            }
                        }
                    }
                } catch (_) { /* non-fatal */ }
            }
        }
    } catch (err) {
        console.warn('[MAP-ML] Camera marker fetch/render failed:', err.message || err);
    }
}

function _onCamerasChanged(data) {
    if (!_state.map || !data || !data.cameras) return;
    // Ensure the map style is ready to accept sources/layers.
    // isStyleLoaded() can stay false forever if tiles fail to load,
    // so we check getStyle() which returns the style object once parsed.
    // If no style exists yet, defer with a retry.
    try {
        const style = _state.map.getStyle();
        if (!style || !style.sources) {
            console.log('[MAP-ML] Style not ready yet, deferring camera markers (retry in 2s)');
            setTimeout(() => _onCamerasChanged(data), 2000);
            return;
        }
    } catch (e) {
        console.log('[MAP-ML] Style not ready yet, deferring camera markers (retry in 2s)');
        setTimeout(() => _onCamerasChanged(data), 2000);
        return;
    }
    const cameras = data.cameras.filter(c => c.lat != null && c.lng != null);
    if (cameras.length === 0) return;
    const geojson = {
        type: 'FeatureCollection',
        features: cameras.map(c => ({
            type: 'Feature',
            properties: {
                id: c.id || c.source_id || '',
                name: c.name || c.id || 'Camera',
                status: c.status || 'offline',
            },
            geometry: {
                type: 'Point',
                coordinates: [c.lng, c.lat],
            },
        })),
    };

    // Build FOV cone polygons for cameras that have heading info
    const fovFeatures = cameras.map(c => {
        const heading = c.heading != null ? c.heading : 0;
        const fovAngle = c.fov_angle || c.coverage_cone_angle || 60; // default 60 deg
        const rangeM = c.fov_range || c.coverage_radius_meters || 30; // default 30m
        const coords = _buildFovConePolygon(c.lng, c.lat, heading, fovAngle, rangeM);
        return {
            type: 'Feature',
            properties: {
                id: c.id || c.source_id || '',
                status: c.status || 'offline',
            },
            geometry: {
                type: 'Polygon',
                coordinates: [coords],
            },
        };
    });
    const fovGeojson = { type: 'FeatureCollection', features: fovFeatures };

    try {
        if (_state.map.getSource(CAMERA_SOURCE_ID)) {
            _state.map.getSource(CAMERA_SOURCE_ID).setData(geojson);
        } else {
            _state.map.addSource(CAMERA_SOURCE_ID, { type: 'geojson', data: geojson });

            // Camera outer glow ring — makes cameras visible at all zoom levels
            _state.map.addLayer({
                id: CAMERA_LAYER_GLOW,
                type: 'circle',
                source: CAMERA_SOURCE_ID,
                paint: {
                    'circle-radius': 18,
                    'circle-color': 'transparent',
                    'circle-stroke-width': 3,
                    'circle-stroke-color': [
                        'match', ['get', 'status'],
                        'streaming', '#00f0ff',
                        'connecting', '#fcee0a',
                        '#ff2a6d',
                    ],
                    'circle-stroke-opacity': 0.5,
                },
            });

            // Camera circle marker — larger, distinctive from targets
            _state.map.addLayer({
                id: CAMERA_LAYER_CIRCLE,
                type: 'circle',
                source: CAMERA_SOURCE_ID,
                paint: {
                    'circle-radius': 12,
                    'circle-color': [
                        'match', ['get', 'status'],
                        'streaming', '#05ffa1',
                        'connecting', '#fcee0a',
                        '#ff2a6d',
                    ],
                    'circle-stroke-width': 3,
                    'circle-stroke-color': '#00f0ff',
                    'circle-opacity': 0.9,
                },
            });

            // Camera icon letter "C" — always visible, overlaps allowed
            _state.map.addLayer({
                id: CAMERA_LAYER_ICON,
                type: 'symbol',
                source: CAMERA_SOURCE_ID,
                layout: {
                    'text-field': 'C',
                    'text-size': 14,
                    'text-font': ['Open Sans Semibold'],
                    'text-allow-overlap': true,
                    'text-ignore-placement': true,
                },
                paint: {
                    'text-color': '#0a0a0f',
                },
            });

            // Camera label — name below the marker
            _state.map.addLayer({
                id: CAMERA_LAYER_LABEL,
                type: 'symbol',
                source: CAMERA_SOURCE_ID,
                layout: {
                    'text-field': ['get', 'name'],
                    'text-size': 12,
                    'text-offset': [0, 2.0],
                    'text-anchor': 'top',
                    'text-font': ['Open Sans Semibold'],
                    'text-allow-overlap': true,
                    'text-ignore-placement': true,
                },
                paint: {
                    'text-color': '#00f0ff',
                    'text-halo-color': '#0a0a0f',
                    'text-halo-width': 2,
                },
            });

            // Click to fly and open camera panel
            _state.map.on('click', CAMERA_LAYER_CIRCLE, (e) => {
                if (e.features && e.features.length > 0) {
                    const props = e.features[0].properties;
                    const coords = e.features[0].geometry.coordinates;
                    _state.map.flyTo({ center: coords, zoom: 19, duration: 600 });
                    // Open the camera-feeds panel and focus on this camera
                    EventBus.emit('panel:request-open', { id: 'camera-feeds' });
                    setTimeout(() => {
                        EventBus.emit('camera:selected', { id: props.id, name: props.name });
                    }, 200);
                }
            });

            // Pointer cursor on hover
            _state.map.on('mouseenter', CAMERA_LAYER_CIRCLE, () => {
                _state.map.getCanvas().style.cursor = 'pointer';
            });
            _state.map.on('mouseleave', CAMERA_LAYER_CIRCLE, () => {
                _state.map.getCanvas().style.cursor = '';
            });
        }

        // FOV cone layer
        if (_state.map.getSource(CAMERA_FOV_SOURCE_ID)) {
            _state.map.getSource(CAMERA_FOV_SOURCE_ID).setData(fovGeojson);
        } else {
            _state.map.addSource(CAMERA_FOV_SOURCE_ID, { type: 'geojson', data: fovGeojson });

            // Semi-transparent fill for FOV cone
            _state.map.addLayer({
                id: CAMERA_LAYER_FOV,
                type: 'fill',
                source: CAMERA_FOV_SOURCE_ID,
                paint: {
                    'fill-color': [
                        'match', ['get', 'status'],
                        'streaming', 'rgba(0, 240, 255, 0.10)',
                        'connecting', 'rgba(252, 238, 10, 0.10)',
                        'rgba(255, 42, 109, 0.08)',
                    ],
                    'fill-opacity': 0.8,
                },
            }, CAMERA_LAYER_GLOW); // insert below the glow layer

            // Outline for FOV cone
            _state.map.addLayer({
                id: CAMERA_LAYER_FOV_LINE,
                type: 'line',
                source: CAMERA_FOV_SOURCE_ID,
                paint: {
                    'line-color': [
                        'match', ['get', 'status'],
                        'streaming', '#00f0ff',
                        'connecting', '#fcee0a',
                        '#ff2a6d',
                    ],
                    'line-width': 1.5,
                    'line-opacity': 0.6,
                    'line-dasharray': [4, 3],
                },
            }, CAMERA_LAYER_GLOW); // insert below the glow layer
        }
    } catch (err) {
        console.warn('[MAP-ML] Camera marker layer error:', err.message || err);
        return;
    }
    console.log(`[MAP-ML] Camera markers rendered: ${cameras.length} marker(s), ${fovFeatures.length} FOV cone(s)`);
}

// ── Camera Click-to-Place ───────────────────────────────────────────────
// When the camera-feeds panel requests a map location pick, register a
// one-shot click handler that captures the lngLat and sends it back.

function _onCameraPickLocation(data) {
    if (!_state.map || !data || !data.active) return;

    // Visual feedback: change cursor to crosshair
    _state.map.getCanvas().style.cursor = 'crosshair';

    function onMapClick(e) {
        // Remove the one-shot handler
        _state.map.off('click', onMapClick);
        _state.map.getCanvas().style.cursor = '';

        // Send coordinates back to the camera panel
        EventBus.emit('camera:location-picked', {
            lat: e.lngLat.lat,
            lng: e.lngLat.lng,
        });
    }

    // Register one-shot click handler
    _state.map.on('click', onMapClick);

    // Auto-cancel after 30 seconds if no click
    setTimeout(() => {
        _state.map.off('click', onMapClick);
        if (_state.map.getCanvas().style.cursor === 'crosshair') {
            _state.map.getCanvas().style.cursor = '';
        }
    }, 30000);
}

export function resetCamera() {
    if (_state.map && _state.geoCenter) {
        _state.map.flyTo({
            center: [_state.geoCenter.lng, _state.geoCenter.lat],
            zoom: ZOOM_DEFAULT,
            pitch: PITCH_DEFAULT,
            bearing: 0,
            duration: 800,
        });
        _clearCombatRadius();
    }
}

export function zoomIn() {
    if (_state.map) {
        _state.map.zoomIn({ duration: 300 });
    }
}

export function zoomOut() {
    if (_state.map) {
        _state.map.zoomOut({ duration: 300 });
    }
}

export function getMapState() {
    return {
        showSatellite: _state.showSatellite,
        showRoads: _state.showRoads,
        showGrid: _state.showGrid,
        showBuildings: _state.showBuildings,
        showUnits: _state.showUnits,
        showLabels: _state.showLabels,
        showModels3d: _state.showModels3d,
        showFog: _state.showFog,
        showTerrain: _state.showTerrain,
        showWaterways: _state.showWaterways,
        showParks: _state.showParks,
        showMesh: _state.showMesh,
        showMeshNodes: _state.showMeshNodes,
        showMeshLinks: _state.showMeshLinks,
        showMeshCoverage: _state.showMeshCoverage,
        showPredictionCones: _state.showPredictionCones,
        showCoverageOverlap: _state.showCoverageOverlap,
        showPatrolRoutes: _state.showPatrolRoutes,
        showThoughts: _state.showThoughts,
        showTracers: _state.showTracers,
        showExplosions: _state.showExplosions,
        showParticles: _state.showParticles,
        showHitFlashes: _state.showHitFlashes,
        showFloatingText: _state.showFloatingText,
        showKillFeed: _state.showKillFeed,
        showScreenFx: _state.showScreenFx,
        showBanners: _state.showBanners,
        showLayerHud: _state.showLayerHud,
        showHealthBars: _state.showHealthBars,
        showSelectionFx: _state.showSelectionFx,
        showWeaponRange: _state.showWeaponRange,
        showHeatmap: _state.showHeatmap,
        showSwarmHull: _state.showSwarmHull,
        showSquadHulls: _state.showSquadHulls,
        showHazardZones: _state.showHazardZones,
        showGeofenceZones: _state.showGeofenceZones,
        showHostileObjectives: _state.showHostileObjectives,
        showCrowdDensity: _state.showCrowdDensity,
        showCoverPoints: _state.showCoverPoints,
        showUnitSignals: _state.showUnitSignals,
        showHostileIntel: _state.showHostileIntel,
        autoFollow: _state.autoFollow,
        tiltMode: _state.tiltMode,
        currentMode: _state.currentMode,
    };
}

export function setLayers(layers) {
    // Nuclear option FIRST: hide/show ALL MapLibre layers except Three.js custom layer.
    // Processed before individual overrides so you can do:
    //   setLayers({allMapLayers: false, satellite: true})  -> hides all, then re-enables satellite
    if (layers.allMapLayers !== undefined) {
        const vis = layers.allMapLayers ? 'visible' : 'none';
        const style = _state.map.getStyle();
        if (style && style.layers) {
            for (const layer of style.layers) {
                if (layer.id === 'three-overlay') continue;  // keep Three.js
                try {
                    _state.map.setLayoutProperty(layer.id, 'visibility', vis);
                } catch (e) { /* some layers may not support visibility */ }
            }
        }
        // Sync state flags and hide DOM markers + Three.js models.
        // DOM markers (unit labels) are positioned via CSS transforms that
        // at high pitch angles create enormous bounding boxes, causing
        // visible border-line artifacts across the entire viewport.
        if (!layers.allMapLayers) {
            _state.showSatellite = false;
            _state.showBuildings = false;
            _state.showRoads = false;
            _state.showWaterways = false;
            _state.showParks = false;
            _state.showUnits = false;
            _state.showLabels = false;
            _state.showModels3d = false;
            _state.showGeoLayers = false;
        } else {
            _state.showSatellite = true;
            _state.showBuildings = true;
            _state.showRoads = true;
            _state.showWaterways = true;
            _state.showParks = true;
            _state.showUnits = true;
            _state.showLabels = true;
            _state.showModels3d = true;
            _state.showGeoLayers = true;
        }
        // Apply DOM marker visibility
        for (const marker of Object.values(_state.unitMarkers)) {
            marker.getElement().style.display = _state.showUnits ? '' : 'none';
        }
        // Apply Three.js model visibility
        if (_state.threeRoot) _state.threeRoot.visible = _state.showModels3d;
        // Apply GIS layer visibility
        const geoVis = _state.showGeoLayers ? 'visible' : 'none';
        for (const id of _state.geoLayerIds) {
            if (_state.map.getLayer(id)) {
                try { _state.map.setLayoutProperty(id, 'visibility', geoVis); } catch (e) {}
            }
        }
    }
    // Individual layer overrides (processed AFTER allMapLayers)
    if (layers.satellite !== undefined) {
        const want = !!layers.satellite;
        if (_state.showSatellite !== want) toggleSatellite();
    }
    if (layers.buildings !== undefined) {
        const want = !!layers.buildings;
        if (_state.showBuildings !== want) toggleBuildings();
    }
    if (layers.roads !== undefined) {
        const want = !!layers.roads;
        if (_state.showRoads !== want) toggleRoads();
    }
    if (layers.grid !== undefined) {
        const want = !!layers.grid;
        if (_state.showGrid !== want) toggleGrid();
    }
    if (layers.units !== undefined) {
        _state.showUnits = !!layers.units;
        for (const marker of Object.values(_state.unitMarkers)) {
            marker.getElement().style.display = _state.showUnits ? '' : 'none';
        }
    }
    // Fine-grained: toggle Three.js 3D models independently
    if (layers.models3d !== undefined) {
        _state.showModels3d = !!layers.models3d;
        if (_state.threeRoot) _state.threeRoot.visible = _state.showModels3d;
    }
    // Fine-grained: toggle DOM markers independently
    if (layers.domMarkers !== undefined) {
        for (const marker of Object.values(_state.unitMarkers)) {
            marker.getElement().style.display = layers.domMarkers ? '' : 'none';
        }
    }
    // Fine-grained: toggle GIS data layers (street graph, obstacles, zones)
    if (layers.geoLayers !== undefined) {
        _state.showGeoLayers = !!layers.geoLayers;
        const vis = _state.showGeoLayers ? 'visible' : 'none';
        for (const id of _state.geoLayerIds) {
            if (_state.map.getLayer(id)) {
                _state.map.setLayoutProperty(id, 'visibility', vis);
            }
        }
    }
    // Waterways
    if (layers.waterways !== undefined) {
        const want = !!layers.waterways;
        if (_state.showWaterways !== want) toggleWaterways();
    }
    // Parks / green areas
    if (layers.parks !== undefined) {
        const want = !!layers.parks;
        if (_state.showParks !== want) toggleParks();
    }
    // Fog
    if (layers.fog !== undefined) {
        const want = !!layers.fog;
        if (_state.showFog !== want) toggleFog();
    }
    // Terrain
    if (layers.terrain !== undefined) {
        const want = !!layers.terrain;
        if (_state.showTerrain !== want) toggleTerrain();
    }
    // Patrol routes
    if (layers.patrolRoutes !== undefined) {
        const want = !!layers.patrolRoutes;
        if (_state.showPatrolRoutes !== want) togglePatrolRoutes();
    }
    // Weapon range
    if (layers.weaponRange !== undefined) {
        const want = !!layers.weaponRange;
        if (_state.showWeaponRange !== want) toggleWeaponRange();
    }
    // Heatmap
    if (layers.heatmap !== undefined) {
        const want = !!layers.heatmap;
        if (_state.showHeatmap !== want) toggleHeatmap();
    }
    // Swarm hull
    if (layers.swarmHull !== undefined) {
        const want = !!layers.swarmHull;
        if (_state.showSwarmHull !== want) toggleSwarmHull();
    }
    // Squad hulls
    if (layers.squadHulls !== undefined) {
        const want = !!layers.squadHulls;
        if (_state.showSquadHulls !== want) toggleSquadHulls();
    }
    // Auto-follow
    if (layers.autoFollow !== undefined) {
        const want = !!layers.autoFollow;
        if (_state.autoFollow !== want) toggleAutoFollow();
    }
    _updateLayerHud();
    console.log('[MAP-ML] Layers set:', JSON.stringify(getMapState()));
    return getMapState();
}
