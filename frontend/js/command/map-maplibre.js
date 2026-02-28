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
    showSatellite: true,
    showBuildings: true,
    showRoads: true,
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
    showModels3d: true,        // Three.js 3D unit models
    showFog: false,            // fog of war
    showMesh: true,            // mesh radio overlay

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
    showLayerHud: true,        // top-center status bar
    showThoughts: true,        // NPC thought bubbles above markers

    tiltMode: 'tilted',        // 'tilted' or 'top-down'
    currentMode: 'observe',    // 'observe', 'tactical', or 'setup'

    // Unit tracking
    unitMarkers: {},            // id -> maplibregl.Marker
    unitMeshes: {},             // id -> THREE.Group (for Three.js layer)

    // GIS data layers
    geoLayerIds: [],            // IDs of added MapLibre layers

    // Selection
    selectedUnitId: null,

    // Dispatch
    dispatchArrows: [],

    // Combat effects (Three.js)
    effects: [],            // active effect objects
    effectsActive: false,   // repaint loop running
    effectAnimId: null,     // rAF handle

    // Vision system (fog of war + cones)
    visionSystem: null,
};

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

    _state.map.on('load', () => {
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

        // Combat effects system
        _initEffects();

        // Subscribe to store events
        TritiumStore.on('map.selectedUnitId', _onSelectionChanged);
        EventBus.on('units:updated', _onUnitsUpdated);
        EventBus.on('unit:dispatched', _onDispatched);
        EventBus.on('minimap:pan', _onMinimapPan);
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

        // Apply the initial mode (default: observe) so visual state matches
        setMapMode(_state.currentMode || 'observe');

        // Start unit update loop
        _startUnitLoop();
    });

    _state.map.on('click', _onMapClick);
    _state.map.on('contextmenu', _onMapRightClick);
    _state.map.on('moveend', _updateLayerHud);
    _state.map.on('zoomend', _updateLayerHud);
    _state.map.on('pitchend', _updateLayerHud);
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
            const m = new THREE.Matrix4().fromArray(matrixData);
            m.multiply(_state._refMatrix);
            _state.threeCamera.projectionMatrix.copy(m);
            _state.threeCamera.projectionMatrixInverse.copy(m).invert();

            _state.threeRenderer.resetState();
            // Clear depth buffer so tactical objects render above map tiles.
            // At pitch=0 (top-down), tiles and 3D objects occupy nearly
            // identical depth values — MapLibre's depth rejects our fragments.
            // depthMask(true) ensures the clear actually writes.
            gl.depthMask(true);
            gl.clear(gl.DEPTH_BUFFER_BIT);
            _state.threeRenderer.render(_state.threeScene, _state.threeCamera);
            _state.map.triggerRepaint();
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

// ============================================================
// Unit Rendering (MapLibre markers with DOM elements)
// ============================================================

function _startUnitLoop() {
    setInterval(() => {
        _updateUnits();
        _drawMinimap();
    }, 100); // 10 Hz update
}

function _updateUnits() {
    if (!_state.map || !_state.initialized) return;

    const units = TritiumStore.units;
    const seenIds = new Set();

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

        // Visibility: respect global toggle and optional alliance filter
        const el = _state.unitMarkers[id].getElement();
        const allianceOk = !_state.allianceFilter ||
            _state.allianceFilter.includes(unit.alliance || 'unknown');
        el.style.display = (_state.showUnits && allianceOk) ? '' : 'none';

        // Fog of war: dim invisible hostiles
        if (unit.alliance === 'hostile' && unit.visible === false && _state.showFog) {
            el.classList.add('fog-hidden');
        } else {
            el.classList.remove('fog-hidden');
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

    // Click handler for selection
    outer.addEventListener('click', (e) => {
        e.stopPropagation();
        TritiumStore.set('map.selectedUnitId', id);
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

function _applyMarkerStyle(el, unit) {
    const alliance = unit.alliance || 'unknown';
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const type = (unit.type || 'unknown').toLowerCase();
    const selected = _state.selectedUnitId === unit.id;
    const has3D = !!_state.threeRoot;
    const modelsVisible = _state.showModels3d;

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

    // Inject shared CSS (once)
    if (!document.getElementById('tritium-marker-css')) {
        const css = document.createElement('style');
        css.id = 'tritium-marker-css';
        css.textContent = [
            '@keyframes hostile-pulse {',
            '  0%, 100% { box-shadow: 0 0 6px #ff2a6d66; }',
            '  50% { box-shadow: 0 0 16px #ff2a6d, 0 0 30px #ff2a6d44; }',
            '}',
        ].join('\n');
        document.head.appendChild(css);
    }

    if (has3D) {
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

        // Location dot — small map point visible when 3D models are hidden
        let locDot = el.querySelector('.unit-loc-dot');
        if (!modelsVisible) {
            if (!locDot) {
                locDot = document.createElement('div');
                locDot.className = 'unit-loc-dot';
                el.insertBefore(locDot, el.firstChild);
            }
            const dotSize = 6;
            const selGlow = selected && _state.showSelectionFx;
            locDot.style.cssText = `
                width: ${dotSize}px; height: ${dotSize}px;
                border-radius: 50%;
                background: ${color};
                box-shadow: 0 0 ${selGlow ? '8' : '3'}px ${color};
                margin-bottom: 2px;
                flex-shrink: 0;
            `;
        } else if (locDot) {
            locDot.remove();
        }

        // Callsign label — short, no-wrap, tiny (respects showLabels toggle)
        let nameLabel = el.querySelector('.unit-name-3d');
        if (_state.showLabels) {
            if (!nameLabel) {
                nameLabel = document.createElement('div');
                nameLabel.className = 'unit-name-3d';
                el.appendChild(nameLabel);
            }
            // Show abbreviated name: "turret-a1b2c3" → "T-A1B"
            const shortName = _abbreviateName(unit.name || '', icon);
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
        // ----- 2D mode: classic circle icon with health bar -----
        const size = alliance === 'hostile' ? 28 : 32;
        const pulse = (_state.showSelectionFx && alliance === 'hostile' && !dead) ? 'animation: hostile-pulse 1.5s ease-in-out infinite;' : '';
        const selGlow = selected && _state.showSelectionFx;
        el.style.cssText = `
            width: ${size}px; height: ${size}px;
            border-radius: ${alliance === 'hostile' ? '4px' : '50%'};
            background: ${dead ? '#33333366' : `radial-gradient(circle, ${color}55, ${color}22)`};
            border: 2px solid ${color};
            display: flex; align-items: center; justify-content: center;
            font-family: 'JetBrains Mono', monospace;
            font-size: ${alliance === 'hostile' ? '12px' : '13px'}; font-weight: bold;
            color: ${color};
            cursor: pointer;
            opacity: ${opacity};
            transition: transform 0.15s, box-shadow 0.15s;
            box-shadow: 0 0 ${selGlow ? '15' : '6'}px ${color}${selGlow ? '' : '44'};
            ${selGlow ? 'transform: scale(1.4);' : ''}
            ${pulse}
            position: relative;
            text-shadow: 0 0 4px ${color};
        `;
        el.textContent = icon;

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

        // Health bar below marker (respects showHealthBars toggle)
        let healthBar = el.querySelector('.unit-hp-bar');
        if (_state.showHealthBars) {
            if (!healthBar) {
                healthBar = document.createElement('div');
                healthBar.className = 'unit-hp-bar';
                healthBar.style.cssText = `
                    position: absolute; bottom: -4px; left: 1px; right: 1px; height: 2px;
                    background: #333; border-radius: 1px; overflow: hidden;
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
            nameLabel.textContent = unit.name || '';
        } else if (nameLabel) {
            nameLabel.remove();
        }
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
    const inner = el.querySelector('.tritium-unit-inner') || el;
    _applyMarkerStyle(inner, unit);
    // No setRotation — labels stay screen-aligned for readability.
    // Heading is shown by the 3D model's orientation instead.

    // Thought bubble above marker
    _updateThoughtBubble(el, unit);
}

const _EMOTION_COLORS = {
    curious: '#00f0ff', afraid: '#fcee0a', angry: '#ff2a6d',
    happy: '#05ffa1', neutral: '#888888',
};

function _updateThoughtBubble(outerEl, unit) {
    let bubble = outerEl.querySelector('.thought-bubble');

    // Should we show a thought?
    const now = Date.now();
    const hasThought = _state.showThoughts && unit.thoughtText && unit.thoughtExpires && unit.thoughtExpires > now;

    if (!hasThought) {
        if (bubble) bubble.style.display = 'none';
        return;
    }

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
        const resp = await fetch(endpoint);
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

    _showMapBanner(
        'WAVE ' + wave,
        name ? name + ' // ' + hostiles + ' hostiles' : hostiles + ' hostiles incoming',
        '#ff2a6d',
        3500
    );
    _triggerScreenFlash('#ff2a6d', 200);
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
}

function _onGameStateChange(data) {
    if (data.state === 'countdown') {
        _startCountdownOverlay(data.countdown || 5);
    } else if (data.state === 'victory') {
        _showMapBanner('VICTORY', 'All waves cleared', '#05ffa1', 5000);
        _triggerScreenFlash('#05ffa1', 400);
    } else if (data.state === 'defeat') {
        _showMapBanner('DEFEAT', 'Perimeter breached', '#ff2a6d', 5000);
        _triggerScreenFlash('#ff2a6d', 400);
        _triggerScreenShake(500, 8);
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
        '">' + _escFx(title) + '</div>',
        '<div style="',
        'font-family:JetBrains Mono,monospace; font-size:14px;',
        'color:#aaa; letter-spacing:2px; margin-top:6px;',
        'animation: fx-streak-pop 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;',
        '">' + _escFx(subtitle) + '</div>',
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
        headR: 6, glowR: 14, duration: 700, flashR: 12,
        trail: true, smoke: true, screenShake: true,
    },
    nerf_tank_cannon: {
        color: 0xffcc00, glowColor: 0xff8800,
        headR: 5, glowR: 12, duration: 550, flashR: 10,
        trail: true, smoke: false, screenShake: true,
    },
    nerf_heavy_turret: {
        color: 0x00f0ff, glowColor: 0x0088ff,
        headR: 5, glowR: 11, duration: 450, flashR: 10,
        trail: true, smoke: false, screenShake: false, twin: true,
    },
    nerf_turret_gun: {
        color: 0x05ffa1, glowColor: 0x00cc88,
        headR: 4, glowR: 10, duration: 500, flashR: 8,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_cannon: {
        color: 0xffa500, glowColor: 0xff8800,
        headR: 4, glowR: 10, duration: 500, flashR: 8,
        trail: true, smoke: false, screenShake: false,
    },
    nerf_apc_mg: {
        color: 0xffa500, glowColor: 0xff6600,
        headR: 2.5, glowR: 7, duration: 350, flashR: 6,
        trail: false, smoke: false, screenShake: false,
    },
    nerf_dart_gun: {
        color: 0x00f0ff, glowColor: 0x0088ff,
        headR: 2.5, glowR: 6, duration: 400, flashR: 5,
        trail: false, smoke: false, screenShake: false,
    },
    nerf_scout_gun: {
        color: 0x00ccff, glowColor: 0x0066cc,
        headR: 2, glowR: 5, duration: 350, flashR: 4,
        trail: false, smoke: false, screenShake: false,
    },
    nerf_pistol: {
        color: 0xff2a6d, glowColor: 0xcc0044,
        headR: 2.5, glowR: 6, duration: 450, flashR: 5,
        trail: false, smoke: false, screenShake: false,
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

    console.log('[FX-PROJ] src=(' + srcX.toFixed(1) + ',' + srcY.toFixed(1) + ')'
        + ' tgt=(' + tgtX.toFixed(1) + ',' + tgtY.toFixed(1) + ')'
        + ' srcStore=' + !!srcUnit + ' tgtStore=' + !!tgtUnit);

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
            depthWrite: false, blending: THREE.NormalBlending,
        });
        const head = new THREE.Mesh(headGeo, headMat);
        head.position.copy(oSrc);

        // Outer glow
        const glowGeo = new THREE.SphereGeometry(ms * vfx.glowR, 6, 6);
        const glowMat = new THREE.MeshBasicMaterial({
            color: vfx.glowColor, transparent: true, opacity: 0.4,
            depthWrite: false, blending: THREE.NormalBlending,
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

    // DOM flash at the hit location provides positioned feedback;
    // skip the full-screen overlay to avoid distracting edge artifacts.
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

    console.log('[FX-ELIM] ' + targetName + ' at (' + (pos.x||0).toFixed(1) + ',' + (pos.y||0).toFixed(1) + ')'
        + ' fromStore=' + !!elimUnit + ' method=' + method);

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
            transparent: true, opacity: 0.7,
            side: THREE.DoubleSide, depthWrite: false,
            blending: THREE.NormalBlending,
        });
        const ring = new THREE.Mesh(ringGeo, ringMat);
        ring.position.set(mc.x, mc.y, mc.z || 0);

        // Second ring (orange, slightly delayed)
        const ring2Geo = new THREE.RingGeometry(
            ms * rStart * 0.5, ms * rStart * 0.9, 32
        );
        const ring2Mat = new THREE.MeshBasicMaterial({
            color: 0xffa500, transparent: true, opacity: 0.5,
            side: THREE.DoubleSide, depthWrite: false,
            blending: THREE.NormalBlending,
        });
        const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
        ring2.position.set(mc.x, mc.y, mc.z || 0);

        // Core flash — bright white burst
        const coreGeo = new THREE.SphereGeometry(ms * 5 * sizeMult, 8, 8);
        const coreMat = new THREE.MeshBasicMaterial({
            color: 0xffffff,
            transparent: true,
            opacity: 0.9,
            depthWrite: false,
            blending: THREE.NormalBlending,
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
    ].join('') + '">' + _escFx(text) + '</div>';

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
        opacity: 0.8,
        depthWrite: false,
        blending: THREE.NormalBlending,
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
            opacity: 0.8,
            depthWrite: false,
            blending: THREE.NormalBlending,
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
        'width:80px; height:80px; border-radius:50%;',
        'pointer-events:none; position:relative;',
        'background:radial-gradient(circle, ' + hexColor + 'cc, ' + hexColor + '44 40%, transparent 70%);',
        'box-shadow: 0 0 30px ' + hexColor + ', 0 0 60px ' + hexColor + '66;',
        'animation: fx-hit-pulse ' + durationMs + 'ms ease-out forwards;',
    ].join('');

    // Inner bright core
    const inner = document.createElement('div');
    inner.style.cssText = [
        'position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);',
        'width:30px; height:30px; border-radius:50%;',
        'background:radial-gradient(circle, #ffffff, ' + hexColor + ' 60%, transparent);',
        'animation: fx-hit-pulse ' + (durationMs * 0.6) + 'ms ease-out forwards;',
    ].join('');
    outer.appendChild(inner);

    // Clip wrapper to prevent spill
    const wrap = document.createElement('div');
    wrap.style.cssText = 'width:160px; height:160px; overflow:hidden;'
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
    const CLIP = 200; // max visual diameter in px

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
        'width:30px; height:30px; border-radius:50%;',
        'pointer-events:none;',
        'border: 4px solid #ff2a6d;',
        'box-shadow: 0 0 30px #ff2a6d, 0 0 60px #ff2a6d88, inset 0 0 20px #ff2a6d44;',
        'animation: fx-explode ' + durationMs + 'ms ease-out forwards;',
    ].join('');
    const ringMarker = _clippedMarker(ring);

    // Layer 2: Orange secondary ring (slightly delayed via slower animation)
    const ring2 = document.createElement('div');
    ring2.style.cssText = [
        'width:20px; height:20px; border-radius:50%;',
        'pointer-events:none;',
        'border: 3px solid #ffa500;',
        'box-shadow: 0 0 20px #ffa500, 0 0 40px #ffa50066;',
        'animation: fx-explode ' + (durationMs * 1.2) + 'ms ease-out forwards;',
    ].join('');
    const ring2Marker = _clippedMarker(ring2);

    // Layer 3: Bright white core flash (fast)
    const core = document.createElement('div');
    core.style.cssText = [
        'width:80px; height:80px; border-radius:50%;',
        'pointer-events:none;',
        'background:radial-gradient(circle, #ffffff, #ffcc00 30%, #ff2a6d 60%, transparent 80%);',
        'box-shadow: 0 0 40px #ffffff88, 0 0 80px #ff2a6d44;',
        'animation: fx-flash ' + (durationMs * 0.35) + 'ms ease-out forwards;',
    ].join('');
    const coreMarker = _clippedMarker(core);

    // Layer 4: Shockwave ring (thin, fast, wide)
    const shock = document.createElement('div');
    shock.style.cssText = [
        'width:10px; height:10px; border-radius:50%;',
        'pointer-events:none;',
        'border: 2px solid #ffffff88;',
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
        'font-size:16px; font-weight:bold; letter-spacing:2px;',
        'color:' + color + '; text-transform:uppercase;',
        'text-shadow: 0 0 8px ' + color + ', 0 0 16px ' + color + '66, 0 2px 4px #000;',
        'max-width:200px; overflow:hidden; text-overflow:ellipsis;',
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
        'background:rgba(6,6,9,0.85); border:1px solid #ff2a6d44;',
        'border-left:3px solid #ff2a6d; padding:4px 10px;',
        'font-family:"JetBrains Mono",monospace; font-size:11px;',
        'color:#eee; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;',
        'animation: fx-killfeed-in 0.3s ease-out;',
    ].join('');
    const weaponTag = weaponLabel
        ? ' <span style="color:#fcee0a88;font-size:9px;letter-spacing:1px">[' + _escFx(weaponLabel) + ']</span> '
        : ' ';
    entry.innerHTML = '<span style="color:#05ffa1">' + _escFx(killerName) + '</span>'
        + weaponTag
        + '<span style="color:#ff2a6d66">//</span> '
        + '<span style="color:#ff2a6d">' + _escFx(targetName) + '</span>';

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

function _escFx(text) {
    if (!text) return '';
    return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
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
    ].join('\n');
    document.head.appendChild(style);
}

/**
 * Ensure the map continuously repaints while effects are active.
 * MapLibre only repaints on interaction by default; combat effects
 * need continuous animation frames.
 */
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
    ].join('');
    _state.container.appendChild(_state.layerHud);
    _updateLayerHud();
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
    if (_state.showTerrain) layers.push('TERRAIN');

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
            });
            if (_state.map) {
                _state.map.easeTo({ pitch: 0, duration: 500 });
                _state.tiltMode = 'top-down';
            }
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
    // Re-render all markers to update selection highlight
    for (const [id, marker] of Object.entries(_state.unitMarkers)) {
        const unit = TritiumStore.units.get(id);
        if (unit) _updateMarkerElement(marker, unit);
    }
}

function _onUnitsUpdated() {
    _updateUnits();
}

function _onDispatched(data) {
    // Could draw dispatch arrow on map
    console.log('[MAP-ML] Unit dispatched:', data);
}

function _onMapClick(e) {
    // Deselect if clicking empty area
    TritiumStore.set('map.selectedUnitId', null);
}

function _onMapRightClick(e) {
    e.preventDefault();
    // Dispatch selected unit to clicked location
    const selectedId = _state.selectedUnitId || TritiumStore.get('map.selectedUnitId');
    if (!selectedId) return;

    const lngLat = e.lngLat;
    // Convert to game coordinates
    if (!_state.geoCenter) return;
    const R = 6378137;
    const latRad = _state.geoCenter.lat * Math.PI / 180;
    const gx = (lngLat.lng - _state.geoCenter.lng) * Math.PI / 180 * R * Math.cos(latRad);
    const gy = (lngLat.lat - _state.geoCenter.lat) * Math.PI / 180 * R;

    EventBus.emit('unit:dispatch', {
        unitId: selectedId,
        target: { x: gx, y: gy },
    });
}

// ============================================================
// Exports: Same API surface as map3d.js
// ============================================================

export function destroyMap() {
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
    _state._meterScale = null;
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
    // Mesh overlay is drawn on the canvas overlay, not a MapLibre layer,
    // so just toggle the state flag and the render loop will pick it up.
    console.log(`[MAP-ML] Mesh network ${_state.showMesh ? 'ON' : 'OFF'}`);
}

/**
 * Toggle NPC thought bubbles on/off.
 */
export function toggleThoughts() {
    _state.showThoughts = !_state.showThoughts;
    // Immediately hide/show existing bubbles
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
        'showUnits', 'showLabels', 'showMesh',
        'showTracers', 'showExplosions', 'showParticles', 'showHitFlashes', 'showFloatingText',
        'showKillFeed', 'showScreenFx', 'showBanners', 'showLayerHud',
        'showHealthBars', 'showSelectionFx',
    ];
    const onCount = defaultOnKeys.filter(k => _state[k]).length;
    const target = onCount <= defaultOnKeys.length / 2;

    // Use the proven setLayers(allMapLayers) path for base map + markers + 3D + GIS
    setLayers({ allMapLayers: target });

    // Set the FX/overlay/decoration flags that setLayers doesn't cover
    const fxKeys = [
        'showGrid', 'showMesh',
        'showHealthBars', 'showSelectionFx',
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

    // Grid layers
    if (_state.map) {
        const vis = target ? 'visible' : 'none';
        if (_state.map.getLayer('grid-minor')) {
            try { _state.map.setLayoutProperty('grid-minor', 'visibility', vis); } catch (e) {}
        }
        if (_state.map.getLayer('grid-major')) {
            try { _state.map.setLayoutProperty('grid-major', 'visibility', vis); } catch (e) {}
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

export function resetCamera() {
    if (_state.map && _state.geoCenter) {
        _state.map.flyTo({
            center: [_state.geoCenter.lng, _state.geoCenter.lat],
            zoom: ZOOM_DEFAULT,
            pitch: PITCH_DEFAULT,
            bearing: 0,
            duration: 800,
        });
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
    _updateLayerHud();
    console.log('[MAP-ML] Layers set:', JSON.stringify(getMapState()));
    return getMapState();
}
