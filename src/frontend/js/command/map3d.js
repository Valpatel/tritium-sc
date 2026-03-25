// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- 3D Tactical Map (Three.js)
 *
 * RTS-style 3D renderer for the Unified Command Center.
 * Replaces the Canvas 2D map.js with a Three.js scene using
 * procedural cyberpunk 3D models from models.js.
 *
 * Camera: perspective with RTS controls (pan, zoom, tilt).
 * Ground: satellite imagery tiles as texture, or dark grid.
 * Units: 3D procedural models (rover, drone, turret, person).
 *
 * Reads unit data from TritiumStore.units, responds to EventBus events.
 * Renders into #tactical-area container.
 *
 * Exports: initMap(), destroyMap(), toggleSatellite(), toggleRoads(),
 *          toggleGrid(), getMapState(), centerOnAction(), resetCamera(),
 *          zoomIn(), zoomOut()
 *
 * Coordinate system:
 *   Game world: 1 unit = 1 meter
 *   Three.js: X = East (game X), Z = -North (game -Y), Y = Up
 *   Camera looks down at ~45-55 degree angle (RTS perspective)
 */

import { TritiumStore } from './store.js';
import { EventBus } from '/lib/events.js';
import { CitySimManager } from './sim/city-sim-manager.js';
import { getScenarioById, loadScenario } from './sim/scenario-loader.js';
import { LODManager } from './sim/lod-manager.js';
import { WeatherVFX } from './sim/weather-vfx.js';

// ============================================================
// Constants
// ============================================================

const BG_COLOR = 0x060609;
const GRID_COLOR = 0x00f0ff;
const ZOOM_MIN = 5;       // closest (frustum half-size)
const ZOOM_MAX = 500;     // farthest
const ZOOM_DEFAULT = 30;  // initial frustum half-size (~60m visible
const CAM_LERP = 6;       // camera smoothing speed
const CAM_TILT_ANGLE = 50; // degrees from horizontal (90=top-down, 45=isometric)
const CAM_HEIGHT_FACTOR = 1.2; // camera height relative to frustum
const EDGE_SCROLL_THRESHOLD = 20; // pixels from edge
const EDGE_SCROLL_SPEED = 15; // world units per second
const FPS_UPDATE_INTERVAL = 500;
const DISPATCH_ARROW_LIFETIME = 3000;
const FONT_FAMILY = '"JetBrains Mono", monospace';

const ALLIANCE_COLORS = {
    friendly: 0x05ffa1,
    hostile:  0xff2a6d,
    neutral:  0x00a0ff,
    unknown:  0xfcee0a,
};

const ALLIANCE_HEX = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
};

// Dynamic satellite tile zoom levels: [maxCamZoom, tileZoom, radiusMeters]
// camZoom = orthographic frustum half-size in meters (5=close, 500=far)
const SAT_TILE_LEVELS = [
    [10,   20,  200],   // extreme close-up: max detail (~0.15m/px)
    [20,   19,  300],   // close-up: very high detail (~0.3m/px)
    [60,   18,  600],   // neighborhood
    [150,  17, 1200],   // district
    [300,  16, 2500],   // city block
    [Infinity, 15, 5000], // wide area
];

// ============================================================
// Module state
// ============================================================

const _state = {
    // Three.js core
    scene: null,
    camera: null,
    renderer: null,
    composer: null,
    bloomEnabled: true,
    clock: null,
    container: null,

    // Camera state (smoothed)
    cam: {
        x: 0, y: 0,       // target world position (game coords)
        zoom: ZOOM_DEFAULT, // orthographic frustum half-size
        targetX: 0, targetY: 0,
        targetZoom: ZOOM_DEFAULT,
    },

    // Render loop
    animFrame: null,
    lastFrameTime: 0,
    dt: 0.016,

    // FPS tracking
    frameTimes: [],
    lastFpsUpdate: 0,
    currentFps: 0,

    // Mouse state
    lastMouse: { x: 0, y: 0 },
    mouseOverCanvas: false,
    isPanning: false,
    panStart: null,
    hoveredUnit: null,

    // Dispatch mode
    dispatchMode: false,
    dispatchUnitId: null,

    // Dispatch arrows (3D line objects)
    dispatchArrows: [],

    // Auto-fit camera
    hasAutoFit: false,

    // Unit meshes: id -> THREE.Group
    unitMeshes: {},
    prevPositions: {},

    // Scene objects
    groundMesh: null,
    gridHelper: null,
    mapBorder: null,
    ambientLight: null,
    dirLight: null,
    zoneMeshes: [],
    selectionRings: {},
    effectMeshes: [],

    // Materials (shared)
    materials: {},

    // Satellite tiles
    satTiles: [],
    satTextureCanvas: null,
    satTexture: null,
    geoCenter: null,
    showSatellite: false,
    showRoads: false,
    showGrid: true,
    satTileLevel: -1,
    satReloadTimer: null,
    noLocationSet: false,

    // City simulation
    citySim: new CitySimManager(),
    lodManager: new LODManager(),
    weatherVFX: new WeatherVFX(),
    roadGraphGroup: null,

    // Zones
    zones: [],

    // Raycaster
    raycaster: null,
    mouseVec: null,

    // Minimap (Canvas 2D)
    minimapCanvas: null,
    minimapCtx: null,

    // Smooth headings
    smoothHeadings: new Map(),

    // Cleanup
    unsubs: [],
    boundHandlers: new Map(),
    resizeObserver: null,
    initialized: false,
};

// ============================================================
// Utility
// ============================================================

function _updateLayerHud() {
    if (!_state.layerHud) return;
    const layers = [];
    if (_state.showSatellite) layers.push('SAT');
    if (_state.buildingGroup?.visible) layers.push('BLDG');
    if (_state.showRoads) layers.push('ROADS');
    if (_state.showGrid !== false && _state.gridHelper?.visible) layers.push('GRID');
    if (_state.showUnits !== false) layers.push('UNITS');
    const tilt = _state.cam?.tiltTarget > 70 ? '2D' : '3D';
    const zoom = _state.cam?.zoom ? Math.round(_state.cam.zoom) : '?';

    // Add city sim stats if running
    let simInfo = '';
    if (_state.citySim?.running) {
        const s = _state.citySim.getStats();
        if (s) {
            simInfo = ` | SIM: ${s.vehicles}v ${s.pedestriansActive || 0}p ${s.avgSpeedKmh}km/h ${s.timeOfDay || ''}`;
        }
    }

    _state.layerHud.textContent = `${tilt} z${zoom} | ${layers.join(' + ') || 'ALL OFF'}${simInfo}`;
}

function fadeToward(current, target, speed, dt) {
    const t = 1 - Math.exp(-speed * dt);
    return current + (target - current) * t;
}

function lerpAngle(from, to, speed, dt) {
    let diff = to - from;
    while (diff > 180) diff -= 360;
    while (diff < -180) diff += 360;
    const t = 1 - Math.exp(-speed * dt);
    return from + diff * t;
}

/** Game coords (x=East, y=North) to Three.js (x=East, z=-North) */
function gameToThree(gx, gy) {
    return { x: gx, z: -gy };
}

// ============================================================
// Init / Destroy
// ============================================================

export function initMap() {
    if (_state.initialized) return;
    if (typeof THREE === 'undefined') {
        console.error('[MAP3D] Three.js not loaded');
        return;
    }

    _state.container = document.getElementById('tactical-area');
    _state.minimapCanvas = document.getElementById('minimap-canvas');
    if (!_state.container) {
        console.error('[MAP3D] #tactical-area not found');
        return;
    }

    _state.clock = new THREE.Clock();

    // Scene
    _state.scene = new THREE.Scene();
    _state.scene.background = new THREE.Color(BG_COLOR);
    _state.scene.fog = new THREE.FogExp2(BG_COLOR, 0.0008);

    // Orthographic camera (RTS view)
    const aspect = _state.container.clientWidth / Math.max(1, _state.container.clientHeight);
    const frustum = ZOOM_DEFAULT;
    _state.camera = new THREE.OrthographicCamera(
        -frustum * aspect, frustum * aspect,
        frustum, -frustum,
        0.1, 1000
    );
    _positionCamera();

    // Renderer
    _state.renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: false,
        powerPreference: 'high-performance',
    });
    _state.renderer.setSize(_state.container.clientWidth, _state.container.clientHeight);
    _state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    _state.renderer.shadowMap.enabled = true;
    _state.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    _state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    _state.renderer.toneMappingExposure = 1.1;

    _state.renderer.domElement.id = 'tactical-3d-canvas';
    _state.renderer.domElement.style.cssText =
        'position:absolute;inset:0;width:100%;height:100%;display:block;cursor:crosshair;z-index:1;';

    // Hide the 2D canvas if present, insert 3D canvas
    const canvas2d = document.getElementById('tactical-canvas');
    if (canvas2d) canvas2d.style.display = 'none';
    _state.container.prepend(_state.renderer.domElement);

    // Post-processing: bloom (UnrealBloomPass)
    _initBloom();

    // Layer status HUD overlay (top-center of map)
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

    // Raycaster
    _state.raycaster = new THREE.Raycaster();
    _state.mouseVec = new THREE.Vector2();

    // Lighting
    _state.ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
    _state.scene.add(_state.ambientLight);

    // Hemisphere light for sky/ground color
    const hemiLight = new THREE.HemisphereLight(0x8899cc, 0x224422, 0.3);
    _state.scene.add(hemiLight);

    _state.dirLight = new THREE.DirectionalLight(0xffffff, 0.7);
    _state.dirLight.position.set(30, 60, 20);
    _state.dirLight.castShadow = true;
    _state.dirLight.shadow.mapSize.width = 2048;
    _state.dirLight.shadow.mapSize.height = 2048;
    _state.dirLight.shadow.camera.near = 1;
    _state.dirLight.shadow.camera.far = 300;
    _state.dirLight.shadow.camera.left = -80;
    _state.dirLight.shadow.camera.right = 80;
    _state.dirLight.shadow.camera.top = 80;
    _state.dirLight.shadow.camera.bottom = -80;
    _state.scene.add(_state.dirLight);

    // Build scene
    _buildGround();
    _buildGrid();
    _buildMapBorder();
    _initMaterials();

    // Input events
    _bindEvents();

    // Resize observer
    if (typeof ResizeObserver !== 'undefined') {
        _state.resizeObserver = new ResizeObserver(() => _handleResize());
        _state.resizeObserver.observe(_state.container);
    }

    // EventBus subscriptions
    _state.unsubs.push(
        EventBus.on('units:updated', _onUnitsUpdated),
        EventBus.on('map:mode', _onMapMode),
        EventBus.on('city-sim:toggle', () => toggleCitySim()),
        EventBus.on('city-sim:add-vehicles', (count) => {
            if (_state.citySim?.loaded) {
                _state.citySim.initRendering(THREE, _state.scene);
                _state.citySim.spawnVehicles(count || 10);
            }
        }),
        EventBus.on('city-sim:add-peds', (count) => {
            if (_state.citySim?.loaded) {
                _state.citySim.initRendering(THREE, _state.scene);
                _state.citySim.spawnPedestrians(count || 10);
            }
        }),
        EventBus.on('city-sim:load-scenario', (scenarioId) => {
            if (_state.citySim?.loaded) {
                const scenario = getScenarioById(scenarioId);
                if (scenario) {
                    _state.citySim.initRendering(THREE, _state.scene);
                    loadScenario(_state.citySim, scenario);
                }
            }
        }),
        EventBus.on('unit:dispatch-mode', _onDispatchMode),
        EventBus.on('unit:dispatched', _onDispatched),
    );
    _state.unsubs.push(
        TritiumStore.on('map.selectedUnitId', _onSelectedUnitChanged),
    );

    // Load geo reference + satellite tiles (overlay loaded after geo reference)
    _loadGeoReference();
    _fetchZones();

    // Start render loop
    _state.lastFrameTime = performance.now();
    _renderLoop();

    _state.initialized = true;
    console.log('%c[MAP3D] Three.js tactical map initialized', 'color: #00f0ff; font-weight: bold;');
}

export function destroyMap() {
    if (!_state.initialized) return;

    if (_state.animFrame) cancelAnimationFrame(_state.animFrame);

    _state.unsubs.forEach(fn => { if (typeof fn === 'function') fn(); });
    _state.unsubs = [];

    if (_state.resizeObserver) {
        _state.resizeObserver.disconnect();
        _state.resizeObserver = null;
    }

    // Dispose Three.js
    if (_state.scene) {
        _state.scene.traverse(obj => {
            if (obj.geometry) obj.geometry.dispose();
            if (obj.material) {
                if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose());
                else obj.material.dispose();
            }
        });
    }
    if (_state.renderer) {
        _state.renderer.dispose();
        if (_state.renderer.domElement.parentNode) {
            _state.renderer.domElement.parentNode.removeChild(_state.renderer.domElement);
        }
    }

    _state.scene = null;
    _state.camera = null;
    _state.renderer = null;
    _state.composer = null;
    _state.bloomPass = null;
    _state.renderPass = null;
    _state.unitMeshes = {};
    _state.initialized = false;

    console.log('%c[MAP3D] Destroyed', 'color: #ff2a6d;');
}

// ============================================================
// Camera
// ============================================================

function _positionCamera() {
    const cam = _state.camera;
    const { x, y, zoom } = _state.cam;

    // Use dynamic tilt angle (smooth lerp between top-down and tilted)
    const tiltDeg = _state.cam.tiltAngle !== undefined ? _state.cam.tiltAngle : CAM_TILT_ANGLE;
    const tiltRad = tiltDeg * Math.PI / 180;
    const height = zoom * CAM_HEIGHT_FACTOR;
    const forward = height / Math.tan(tiltRad);

    const tp = gameToThree(x, y);
    cam.position.set(tp.x, height, tp.z + forward);
    cam.lookAt(tp.x, 0, tp.z);
    cam.up.set(0, 1, 0);

    // Update frustum for ortho
    const aspect = _state.container
        ? _state.container.clientWidth / Math.max(1, _state.container.clientHeight)
        : 1;
    cam.left = -zoom * aspect;
    cam.right = zoom * aspect;
    cam.top = zoom;
    cam.bottom = -zoom;
    cam.updateProjectionMatrix();
}

function _updateCamera(dt) {
    const c = _state.cam;

    // Smooth lerp
    c.x = fadeToward(c.x, c.targetX, CAM_LERP, dt);
    c.y = fadeToward(c.y, c.targetY, CAM_LERP, dt);
    c.zoom = fadeToward(c.zoom, c.targetZoom, CAM_LERP * 0.8, dt);

    // Smooth tilt angle lerp
    if (c.tiltTarget !== undefined) {
        if (c.tiltAngle === undefined) c.tiltAngle = CAM_TILT_ANGLE;
        c.tiltAngle = fadeToward(c.tiltAngle, c.tiltTarget, CAM_LERP * 0.6, dt);
    }

    // Edge scrolling — only when mouse is inside the canvas and recently moved
    if (!_state.isPanning && _state.mouseOverCanvas) {
        const rect = _state.renderer.domElement.getBoundingClientRect();
        const mx = _state.lastMouse.clientX;
        const my = _state.lastMouse.clientY;
        if (mx !== undefined && my !== undefined) {
            const t = EDGE_SCROLL_THRESHOLD;
            const speed = EDGE_SCROLL_SPEED * dt;

            if (mx < rect.left + t && mx >= rect.left) c.targetX -= speed;
            if (mx > rect.right - t && mx <= rect.right) c.targetX += speed;
            if (my < rect.top + t && my >= rect.top) c.targetY += speed;
            if (my > rect.bottom - t && my <= rect.bottom) c.targetY -= speed;
        }
    }

    _positionCamera();

    // Shadow camera follows main camera
    if (_state.dirLight) {
        const tp = gameToThree(c.x, c.y);
        _state.dirLight.position.set(tp.x + 30, 60, tp.z + 20);
        _state.dirLight.target.position.set(tp.x, 0, tp.z);
        _state.dirLight.target.updateMatrixWorld();

        const shadowSize = Math.min(c.zoom * 1.5, 120);
        _state.dirLight.shadow.camera.left = -shadowSize;
        _state.dirLight.shadow.camera.right = shadowSize;
        _state.dirLight.shadow.camera.top = shadowSize;
        _state.dirLight.shadow.camera.bottom = -shadowSize;
        _state.dirLight.shadow.camera.updateProjectionMatrix();
    }
}

// ============================================================
// Static scene elements
// ============================================================

function _buildGround() {
    // Large ground plane with satellite or dark texture
    const size = 5000;
    const geo = new THREE.PlaneGeometry(size, size, 1, 1);
    const mat = new THREE.MeshBasicMaterial({
        color: BG_COLOR,
        fog: false,  // Satellite imagery should not dim with distance
    });
    _state.groundMesh = new THREE.Mesh(geo, mat);
    _state.groundMesh.rotation.x = -Math.PI / 2;
    _state.groundMesh.position.y = -0.01;
    _state.scene.add(_state.groundMesh);
}

function _buildGrid() {
    // Tactical grid: 100m spacing, 5km range
    const range = 200;
    const divisions = 40; // 5m spacing
    const grid = new THREE.GridHelper(range, divisions, GRID_COLOR, GRID_COLOR);
    grid.material.opacity = 0.08;
    grid.material.transparent = true;
    grid.material.depthWrite = false;
    _state.gridHelper = grid;
    _state.scene.add(grid);
}

function _buildMapBorder() {
    // Map boundary (60m x 60m default visible area)
    const half = 50;
    const pts = [
        new THREE.Vector3(-half, 0.02, -half),
        new THREE.Vector3(half, 0.02, -half),
        new THREE.Vector3(half, 0.02, half),
        new THREE.Vector3(-half, 0.02, half),
        new THREE.Vector3(-half, 0.02, -half),
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({
        color: 0x00f0ff,
        opacity: 0.15,
        transparent: true,
    });
    _state.mapBorder = new THREE.Line(geo, mat);
    _state.scene.add(_state.mapBorder);
}

function _initMaterials() {
    // Alliance materials
    for (const [alliance, color] of Object.entries(ALLIANCE_COLORS)) {
        _state.materials[alliance] = new THREE.MeshStandardMaterial({
            color,
            roughness: 0.4,
            metalness: 0.3,
            emissive: color,
            emissiveIntensity: 0.15,
        });
    }

    // Selection ring
    _state.materials.selection = new THREE.MeshBasicMaterial({
        color: 0x00f0ff,
        transparent: true,
        opacity: 0.5,
        side: THREE.DoubleSide,
        depthWrite: false,
    });

    // Dispatch arrow
    _state.materials.dispatch = new THREE.LineDashedMaterial({
        color: 0xff2a6d,
        transparent: true,
        opacity: 0.8,
        dashSize: 0.5,
        gapSize: 0.3,
    });

    // Zone materials
    // Zone fill discs removed — only border rings rendered for clean map
    _state.materials.zoneBorderRestricted = new THREE.LineBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.25,
    });
    _state.materials.zoneBorderPerimeter = new THREE.LineDashedMaterial({
        color: 0x00f0ff, transparent: true, opacity: 0.12,
        dashSize: 0.5, gapSize: 0.3,
    });

    // Effect ring
    _state.materials.effectRing = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.6,
        side: THREE.DoubleSide, depthWrite: false,
    });

    // Building wall materials — per-category cyberpunk colors
    _state.materials.building = new THREE.MeshStandardMaterial({
        color: 0x1a1a3e, roughness: 0.7, metalness: 0.2,
        transparent: true, opacity: 0.75, side: THREE.DoubleSide,
    });
    _state.materials.buildingResidential = new THREE.MeshStandardMaterial({
        color: 0x2a1a1a, roughness: 0.8, metalness: 0.1,
        transparent: true, opacity: 0.75, side: THREE.DoubleSide,
    });
    _state.materials.buildingCommercial = new THREE.MeshStandardMaterial({
        color: 0x1a2a3a, roughness: 0.5, metalness: 0.3,
        transparent: true, opacity: 0.78, side: THREE.DoubleSide,
    });
    _state.materials.buildingIndustrial = new THREE.MeshStandardMaterial({
        color: 0x2a2a1a, roughness: 0.9, metalness: 0.2,
        transparent: true, opacity: 0.7, side: THREE.DoubleSide,
    });
    _state.materials.buildingCivic = new THREE.MeshStandardMaterial({
        color: 0x1a1a2a, roughness: 0.5, metalness: 0.4,
        transparent: true, opacity: 0.8, side: THREE.DoubleSide,
    });
    _state.materials.buildingReligious = new THREE.MeshStandardMaterial({
        color: 0x2a1a2a, roughness: 0.6, metalness: 0.3,
        transparent: true, opacity: 0.8, side: THREE.DoubleSide,
    });
    _state.materials.buildingUtility = new THREE.MeshStandardMaterial({
        color: 0x1a1a1a, roughness: 0.9, metalness: 0.1,
        transparent: true, opacity: 0.6, side: THREE.DoubleSide,
    });

    // Building roof material
    _state.materials.buildingRoof = new THREE.MeshStandardMaterial({
        color: 0x151530, roughness: 0.8, metalness: 0.1,
        transparent: true, opacity: 0.8,
    });

    // Building outline — bright cyan edges for cyberpunk look
    _state.materials.buildingEdge = new THREE.LineBasicMaterial({
        color: 0x00f0ff, transparent: true, opacity: 0.5,
    });

    // Building window material — emissive yellow-orange glow
    _state.materials.buildingWindow = new THREE.MeshBasicMaterial({
        color: 0xffdd44, transparent: true, opacity: 0.7,
        side: THREE.DoubleSide, depthWrite: false,
    });

    // Road surface materials
    _state.materials.road = new THREE.MeshBasicMaterial({
        color: 0x3a3a4a, transparent: true, opacity: 0.5,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.roadPrimary = new THREE.MeshBasicMaterial({
        color: 0x444455, transparent: true, opacity: 0.6,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.roadFootway = new THREE.MeshBasicMaterial({
        color: 0x555566, transparent: true, opacity: 0.35,
        side: THREE.DoubleSide, depthWrite: false,
    });

    // Land use materials
    _state.materials.parkGround = new THREE.MeshBasicMaterial({
        color: 0x0a2a0a, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.waterSurface = new THREE.MeshBasicMaterial({
        color: 0x0044aa, transparent: true, opacity: 0.45,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.waterEdge = new THREE.LineBasicMaterial({
        color: 0x0088ff, transparent: true, opacity: 0.5,
    });

    // Tree materials
    _state.materials.treeTrunk = new THREE.MeshStandardMaterial({
        color: 0x3a2820, roughness: 0.9, metalness: 0.0,
    });
    _state.materials.treeCrown = new THREE.MeshStandardMaterial({
        color: 0x1a4a1a, roughness: 0.8, metalness: 0.0,
        transparent: true, opacity: 0.8,
    });

    // Barrier material
    _state.materials.barrier = new THREE.MeshStandardMaterial({
        color: 0x444444, roughness: 0.8, metalness: 0.1,
        transparent: true, opacity: 0.6,
    });

    // Entrance/door material — bright indicator
    _state.materials.entrance = new THREE.MeshBasicMaterial({
        color: 0x05ffa1, transparent: true, opacity: 0.8,
    });

    // POI marker material
    _state.materials.poi = new THREE.MeshBasicMaterial({
        color: 0xfcee0a, transparent: true, opacity: 0.7,
    });
}

// ============================================================
// Bloom post-processing
// ============================================================

function _initBloom() {
    if (typeof THREE.EffectComposer === 'undefined' ||
        typeof THREE.RenderPass === 'undefined' ||
        typeof THREE.UnrealBloomPass === 'undefined') {
        console.warn('[MAP3D] Bloom post-processing not available — missing Three.js addons');
        _state.bloomEnabled = false;
        return;
    }

    const w = _state.container.clientWidth;
    const h = _state.container.clientHeight;

    const composer = new THREE.EffectComposer(_state.renderer);

    const renderPass = new THREE.RenderPass(_state.scene, _state.camera);
    composer.addPass(renderPass);

    const bloomPass = new THREE.UnrealBloomPass(
        new THREE.Vector2(w, h),
        0.3,   // strength — subtle glow
        0.4,   // radius
        0.85   // threshold — only bright emissive objects bloom
    );
    composer.addPass(bloomPass);

    _state.composer = composer;
    _state.bloomPass = bloomPass;
    _state.renderPass = renderPass;
}

// ============================================================
// Unit mesh creation (uses TritiumModels from models.js)
// ============================================================

function _createUnitMesh(id, unit) {
    const alliance = (unit.alliance || 'unknown').toLowerCase();
    const assetType = (unit.type || '').toLowerCase();
    const group = new THREE.Group();
    group.userData.targetId = id;
    group.userData.alliance = alliance;

    // Use procedural models from models.js if available
    if (typeof TritiumModels !== 'undefined' && TritiumModels.getModelForType) {
        const model = TritiumModels.getModelForType(assetType || alliance, alliance);
        if (model) {
            group.add(model);
            model.userData.isBody = true;

            // Name label
            if (TritiumModels.createNameLabel) {
                const label = TritiumModels.createNameLabel(
                    unit.name || id,
                    ALLIANCE_HEX[alliance] || '#ffffff'
                );
                label.userData.isLabel = true;
                group.add(label);
            }

            // Battery bar for friendlies
            if (alliance === 'friendly' && TritiumModels.createBatteryBar) {
                const bar = TritiumModels.createBatteryBar(unit.battery || 1.0);
                bar.userData.isBattery = true;
                group.add(bar);
            }

            // Shadow circle
            const shadowGeo = new THREE.CircleGeometry(0.5, 16);
            const shadowMat = new THREE.MeshBasicMaterial({
                color: 0x000000, transparent: true, opacity: 0.3, depthWrite: false,
            });
            const shadow = new THREE.Mesh(shadowGeo, shadowMat);
            shadow.rotation.x = -Math.PI / 2;
            shadow.position.y = 0.01;
            group.add(shadow);

            return group;
        }
    }

    // Fallback: simple geometric shapes
    const mat = _state.materials[alliance] || _state.materials.unknown;
    let bodyMesh;

    if (assetType.includes('drone')) {
        const geo = new THREE.CylinderGeometry(0.5, 0.5, 0.12, 8);
        bodyMesh = new THREE.Mesh(geo, mat);
        bodyMesh.position.y = 3;
        for (let i = 0; i < 4; i++) {
            const angle = (i / 4) * Math.PI * 2;
            const rotorGeo = new THREE.SphereGeometry(0.1, 6, 4);
            const rotor = new THREE.Mesh(rotorGeo, mat);
            rotor.position.set(Math.cos(angle) * 0.4, 3, Math.sin(angle) * 0.4);
            group.add(rotor);
        }
    } else if (assetType.includes('turret') || assetType.includes('sentry')) {
        const geo = new THREE.CylinderGeometry(0.5, 0.6, 0.5, 6);
        bodyMesh = new THREE.Mesh(geo, mat);
        bodyMesh.position.y = 0.25;
        const barrelGeo = new THREE.CylinderGeometry(0.06, 0.06, 0.6, 6);
        const barrel = new THREE.Mesh(barrelGeo, mat);
        barrel.rotation.x = Math.PI / 2;
        barrel.position.set(0, 0.4, -0.4);
        group.add(barrel);
    } else if (alliance === 'hostile') {
        const geo = new THREE.CylinderGeometry(0.2, 0.2, 0.6, 8);
        bodyMesh = new THREE.Mesh(geo, mat);
        bodyMesh.position.y = 0.3;
        const headGeo = new THREE.SphereGeometry(0.2, 8, 6);
        const head = new THREE.Mesh(headGeo, mat);
        head.position.y = 0.7;
        group.add(head);
    } else {
        // Default rover shape
        const geo = new THREE.CylinderGeometry(0.35, 0.45, 0.3, 8);
        bodyMesh = new THREE.Mesh(geo, mat);
        bodyMesh.position.y = 0.15;
        const domeGeo = new THREE.SphereGeometry(0.15, 8, 4, 0, Math.PI * 2, 0, Math.PI / 2);
        const dome = new THREE.Mesh(domeGeo, mat);
        dome.position.y = 0.3;
        group.add(dome);
    }

    if (bodyMesh) {
        bodyMesh.castShadow = true;
        group.add(bodyMesh);
    }

    // Shadow
    const shadowGeo = new THREE.CircleGeometry(0.4, 16);
    const shadowMat = new THREE.MeshBasicMaterial({
        color: 0x000000, transparent: true, opacity: 0.25, depthWrite: false,
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.01;
    group.add(shadow);

    // Name label
    const label = _createTextSprite(unit.name || id, alliance);
    label.position.y = assetType.includes('drone') ? 4.0 : 1.2;
    label.userData.isLabel = true;
    group.add(label);

    return group;
}

function _createTextSprite(text, alliance) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 512;
    canvas.height = 128;
    ctx.clearRect(0, 0, 512, 128);

    ctx.font = `bold 48px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    ctx.strokeStyle = 'rgba(0,0,0,0.9)';
    ctx.lineWidth = 6;
    ctx.strokeText(text.substring(0, 20), 256, 64);

    ctx.fillStyle = ALLIANCE_HEX[alliance] || '#ffffff';
    ctx.fillText(text.substring(0, 20), 256, 64);

    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;

    const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false, sizeAttenuation: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(0.22, 0.055, 1);
    return sprite;
}

// ============================================================
// Heading arrow
// ============================================================

function _updateHeading(group, heading) {
    const old = group.getObjectByName('headingArrow');
    if (old) group.remove(old);
    if (heading === undefined || heading === null) return;

    const rad = -heading * Math.PI / 180;
    const pts = [
        new THREE.Vector3(0, 0.1, 0),
        new THREE.Vector3(0, 0.1, -1.0),
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const color = ALLIANCE_COLORS[group.userData.alliance] || ALLIANCE_COLORS.unknown;
    const mat = new THREE.LineBasicMaterial({ color, linewidth: 2 });
    const line = new THREE.Line(geo, mat);
    line.name = 'headingArrow';
    line.rotation.y = rad;
    group.add(line);
}

// ============================================================
// FOV cones (3D)
// ============================================================

function _updateFOVCone(group, unit) {
    const old = group.getObjectByName('fovCone');
    if (old) {
        group.remove(old);
        old.traverse(c => { if (c.geometry) c.geometry.dispose(); });
    }

    const range = unit.fov_range || unit.weapon_range;
    const angle = unit.fov_angle || 60;
    if (!range || range <= 0) return;

    const halfAngle = (angle / 2) * Math.PI / 180;
    const segments = 16;
    const pts = [new THREE.Vector3(0, 0, 0)];

    for (let i = 0; i <= segments; i++) {
        const a = -halfAngle + (i / segments) * halfAngle * 2;
        pts.push(new THREE.Vector3(Math.sin(a) * range, 0, -Math.cos(a) * range));
    }
    pts.push(new THREE.Vector3(0, 0, 0));

    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const alliance = group.userData.alliance;
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const mat = new THREE.MeshBasicMaterial({
        color, transparent: true, opacity: 0.06,
        side: THREE.DoubleSide, depthWrite: false,
    });

    // Create as a ShapeGeometry for the filled cone
    const shape = new THREE.Shape();
    shape.moveTo(0, 0);
    for (let i = 0; i <= segments; i++) {
        const a = -halfAngle + (i / segments) * halfAngle * 2;
        shape.lineTo(Math.sin(a) * range, -Math.cos(a) * range);
    }
    shape.lineTo(0, 0);

    const shapeGeo = new THREE.ShapeGeometry(shape);
    const cone = new THREE.Mesh(shapeGeo, mat);
    cone.rotation.x = -Math.PI / 2;
    cone.position.y = 0.03;
    cone.name = 'fovCone';

    // Apply heading rotation
    const heading = unit.heading || 0;
    cone.rotation.z = heading * Math.PI / 180;

    group.add(cone);
}

// ============================================================
// Health bar (3D floating bar above unit)
// ============================================================

function _updateHealthBar(group, unit) {
    let barGroup = null;
    group.traverse(c => {
        if (c.userData && c.userData.isHealthBar) barGroup = c;
    });

    const health = unit.health;
    const maxHealth = unit.maxHealth || unit.max_health;
    if (health === undefined || !maxHealth) {
        if (barGroup) { group.remove(barGroup); }
        return;
    }

    const pct = Math.max(0, Math.min(1, health / maxHealth));

    if (!barGroup) {
        barGroup = new THREE.Group();
        barGroup.userData.isHealthBar = true;

        // Background
        const bgGeo = new THREE.PlaneGeometry(1.2, 0.1);
        const bgMat = new THREE.MeshBasicMaterial({
            color: 0xffffff, transparent: true, opacity: 0.15,
            side: THREE.DoubleSide, depthWrite: false,
        });
        barGroup.add(new THREE.Mesh(bgGeo, bgMat));

        // Fill
        const fgGeo = new THREE.PlaneGeometry(1.2, 0.1);
        const fgMat = new THREE.MeshBasicMaterial({
            color: pct > 0.5 ? 0x05ffa1 : pct > 0.25 ? 0xfcee0a : 0xff2a6d,
            side: THREE.DoubleSide, depthWrite: false,
        });
        const fg = new THREE.Mesh(fgGeo, fgMat);
        fg.userData.isHealthFill = true;
        barGroup.add(fg);

        barGroup.position.y = 1.5;
        group.add(barGroup);
    }

    // Update fill scale
    barGroup.traverse(c => {
        if (c.userData && c.userData.isHealthFill) {
            c.scale.x = pct;
            c.position.x = -(1 - pct) * 0.6;
            c.material.color.setHex(
                pct > 0.5 ? 0x05ffa1 : pct > 0.25 ? 0xfcee0a : 0xff2a6d
            );
        }
    });

    // Billboard: face camera
    barGroup.lookAt(_state.camera.position);
}

// ============================================================
// Unit update (sync meshes with TritiumStore)
// ============================================================

function _updateUnits(dt) {
    const units = TritiumStore.units;

    // Remove meshes for units that no longer exist
    for (const id of Object.keys(_state.unitMeshes)) {
        if (!units.has(id)) {
            const group = _state.unitMeshes[id];
            _state.scene.remove(group);
            group.traverse(c => { if (c.geometry) c.geometry.dispose(); });
            delete _state.unitMeshes[id];
            delete _state.prevPositions[id];
        }
    }

    // Create or update
    for (const [id, unit] of units) {
        let group = _state.unitMeshes[id];
        const pos = unit.position || {};
        const gx = pos.x !== undefined ? pos.x : (unit.x || 0);
        const gy = pos.y !== undefined ? pos.y : (unit.y || 0);

        if (!group) {
            group = _createUnitMesh(id, unit);
            _state.scene.add(group);
            _state.unitMeshes[id] = group;
            _state.prevPositions[id] = { x: gx, z: -gy };
        }

        // Smooth position lerp
        const prev = _state.prevPositions[id];
        const lerpFactor = 0.15;
        const tp = gameToThree(gx, gy);
        const nx = prev.x + (tp.x - prev.x) * lerpFactor;
        const nz = prev.z + (tp.z - prev.z) * lerpFactor;
        _state.prevPositions[id] = { x: nx, z: nz };

        group.position.x = nx;
        group.position.z = nz;

        // Height: drones fly
        const assetType = (unit.type || '').toLowerCase();
        group.position.y = unit.altitude || (assetType.includes('drone') ? 3 : 0);

        // Heading (smooth)
        if (unit.heading !== undefined) {
            const prevH = _state.smoothHeadings.get(id) || unit.heading;
            const smoothH = lerpAngle(prevH, unit.heading, 5, dt);
            _state.smoothHeadings.set(id, smoothH);
            _updateHeading(group, smoothH);

            // Rotate FOV cone with heading
            const fovCone = group.getObjectByName('fovCone');
            if (fovCone) {
                fovCone.rotation.z = smoothH * Math.PI / 180;
            }
        }

        // Health bar
        _updateHealthBar(group, unit);

        // FOV cones (update occasionally)
        if (!group.getObjectByName('fovCone') && (unit.fov_range || unit.weapon_range)) {
            _updateFOVCone(group, unit);
        }

        // Animate procedural models
        if (typeof TritiumModels !== 'undefined' && TritiumModels.animateModel) {
            group.traverse(c => {
                if (c.userData && c.userData.isBody) {
                    TritiumModels.animateModel(c, dt, performance.now() / 1000, {
                        speed: unit.speed || 0,
                        heading: unit.heading || 0,
                        selected: id === TritiumStore.get('map.selectedUnitId'),
                        battery: unit.battery || 1.0,
                        alliance: (unit.alliance || 'unknown').toLowerCase(),
                    });
                }
            });
        }

        // Adaptive unit scale: body meshes grow when zoomed out so units stay visible
        // At zoom=30 (default) scale=1; at zoom=200 scale~3; at zoom=500 scale~5
        // Labels use sizeAttenuation:false so they maintain screen size automatically
        const zoomScale = Math.max(1, _state.cam.zoom / 30);
        group.children.forEach(c => {
            if (c.userData?.isBody || c.userData?.isBattery || c.isMesh) {
                c.scale.setScalar(zoomScale);
            }
        });

        // Neutralized visual
        if (unit.status === 'neutralized' || unit.health <= 0) {
            group.traverse(c => {
                if (c.material && !c.userData.isLabel) {
                    c.material.opacity = Math.max(0.3, c.material.opacity);
                }
            });
        }
    }
}

// ============================================================
// Zones
// ============================================================

let _lastZoneUpdate = 0;

function _updateZonesThrottled() {
    const now = Date.now();
    if (now - _lastZoneUpdate > 2000) {
        _updateZones();
        _lastZoneUpdate = now;
    }
}

function _updateZones() {
    // Remove old
    for (const m of _state.zoneMeshes) {
        _state.scene.remove(m);
        if (m.geometry) m.geometry.dispose();
    }
    _state.zoneMeshes = [];

    for (const zone of _state.zones) {
        const pos = zone.position || {};
        const wx = pos.x || 0;
        const wy = pos.z !== undefined ? pos.z : (pos.y || 0);
        const radius = (zone.properties && zone.properties.radius) || 10;
        const isRestricted = (zone.type || '').includes('restricted');

        // Zone filled disc removed — border ring only for clean NATO-style map
        const tp = gameToThree(wx, wy);

        // Border ring
        const ringPts = [];
        const segments = 64;
        for (let i = 0; i <= segments; i++) {
            const a = (i / segments) * Math.PI * 2;
            ringPts.push(new THREE.Vector3(
                Math.cos(a) * radius, 0, Math.sin(a) * radius
            ));
        }
        const ringGeo = new THREE.BufferGeometry().setFromPoints(ringPts);
        const ringMat = isRestricted
            ? _state.materials.zoneBorderRestricted
            : _state.materials.zoneBorderPerimeter;
        const ring = new THREE.Line(ringGeo, ringMat);
        ring.position.set(tp.x, 0.03, tp.z);
        if (!isRestricted) ring.computeLineDistances();
        _state.scene.add(ring);
        _state.zoneMeshes.push(ring);

        // Zone label
        const name = zone.name || zone.type || '';
        if (name) {
            const label = _createZoneLabel(name.toUpperCase(), isRestricted);
            label.position.set(tp.x, 0.5, tp.z - radius - 1);
            _state.scene.add(label);
            _state.zoneMeshes.push(label);
        }
    }
}

function _createZoneLabel(text, isRestricted) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 256;
    canvas.height = 48;
    ctx.clearRect(0, 0, 256, 48);
    ctx.font = `20px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = isRestricted ? 'rgba(255,42,109,0.5)' : 'rgba(0,240,255,0.3)';
    ctx.fillText(text.substring(0, 20), 128, 24);

    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false, sizeAttenuation: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(0.06, 0.012, 1);
    return sprite;
}

// ============================================================
// Selection ring
// ============================================================

function _updateSelection() {
    const selectedId = TritiumStore.get('map.selectedUnitId');

    // Remove rings for deselected
    for (const [id, ring] of Object.entries(_state.selectionRings)) {
        if (id !== selectedId) {
            _state.scene.remove(ring);
            if (ring.geometry) ring.geometry.dispose();
            delete _state.selectionRings[id];
        }
    }

    if (!selectedId) return;

    // Create or update ring
    if (!_state.selectionRings[selectedId]) {
        // Use TritiumModels if available
        let ring;
        if (typeof TritiumModels !== 'undefined' && TritiumModels.createSelectionRing) {
            ring = TritiumModels.createSelectionRing();
        } else {
            const ringGeo = new THREE.RingGeometry(0.55, 0.7, 32);
            ring = new THREE.Mesh(ringGeo, _state.materials.selection);
            ring.rotation.x = -Math.PI / 2;
        }
        ring.position.y = 0.04;
        _state.scene.add(ring);
        _state.selectionRings[selectedId] = ring;
    }

    // Position on target
    const group = _state.unitMeshes[selectedId];
    if (group) {
        const ring = _state.selectionRings[selectedId];
        ring.position.x = group.position.x;
        ring.position.z = group.position.z;
    }

    // Pulse animation
    const pulse = 0.5 + Math.sin(Date.now() * 0.005) * 0.15;
    for (const ring of Object.values(_state.selectionRings)) {
        if (ring.material) ring.material.opacity = pulse;
        // Animate if TritiumModels ring
        if (typeof TritiumModels !== 'undefined' && TritiumModels.animateSelectionRing) {
            TritiumModels.animateSelectionRing(ring, _state.dt);
        }
    }
}

// ============================================================
// Dispatch arrows (3D)
// ============================================================

function _updateDispatchArrows() {
    const now = Date.now();

    _state.dispatchArrows = _state.dispatchArrows.filter(arr => {
        if (now - arr.time >= DISPATCH_ARROW_LIFETIME) {
            _state.scene.remove(arr.line);
            if (arr.line.geometry) arr.line.geometry.dispose();
            if (arr.cone) {
                _state.scene.remove(arr.cone);
                arr.cone.geometry.dispose();
            }
            return false;
        }
        // Fade
        const alpha = Math.max(0, 1 - (now - arr.time) / DISPATCH_ARROW_LIFETIME);
        if (arr.line.material) arr.line.material.opacity = alpha * 0.8;
        if (arr.cone && arr.cone.material) arr.cone.material.opacity = alpha * 0.8;
        return true;
    });
}

function _addDispatchArrow(fromX, fromY, toX, toY) {
    const from3 = gameToThree(fromX, fromY);
    const to3 = gameToThree(toX, toY);
    const fromV = new THREE.Vector3(from3.x, 0.15, from3.z);
    const toV = new THREE.Vector3(to3.x, 0.15, to3.z);

    const geo = new THREE.BufferGeometry().setFromPoints([fromV, toV]);
    const mat = new THREE.LineDashedMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.8,
        dashSize: 0.5, gapSize: 0.3,
    });
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    _state.scene.add(line);

    // Arrowhead cone
    const dir = toV.clone().sub(fromV).normalize();
    const coneGeo = new THREE.ConeGeometry(0.25, 0.6, 6);
    const coneMat = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.8,
    });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.position.copy(toV);
    const axis = new THREE.Vector3(0, 1, 0);
    const quat = new THREE.Quaternion().setFromUnitVectors(axis, dir);
    cone.quaternion.copy(quat);
    _state.scene.add(cone);

    _state.dispatchArrows.push({ line, cone, time: Date.now() });
}

// ============================================================
// Render loop
// ============================================================

function _renderLoop() {
    _state.animFrame = requestAnimationFrame(_renderLoop);

    const now = performance.now();
    _state.dt = Math.min(0.1, (now - _state.lastFrameTime) / 1000);
    _state.lastFrameTime = now;

    // FPS tracking
    _state.frameTimes.push(now);
    if (now - _state.lastFpsUpdate > FPS_UPDATE_INTERVAL) {
        _state.lastFpsUpdate = now;
        const cutoff = now - 1000;
        _state.frameTimes = _state.frameTimes.filter(t => t > cutoff);
        _state.currentFps = _state.frameTimes.length;
        _updateFps();
    }

    // Update
    _updateCamera(_state.dt);
    _updateUnits(_state.dt);
    _updateZonesThrottled();
    _updateSelection();
    _updateDispatchArrows();
    _checkSatelliteTileReload();

    // City simulation tick + vehicle rendering
    if (_state.citySim?.running) {
        _state.citySim.tick(_state.dt);
        _state.citySim.updateRendering(gameToThree);
        _updateCongestionOverlay();
    }

    // LOD updates based on camera position (game coords: x=East, y=North)
    if (_state.lodManager?.sectors?.size > 0 && _state.cam) {
        _state.lodManager.updateLOD(_state.cam.x, _state.cam.y);
    }

    // Weather scene updates
    if (_state.citySim?.weather && _state.citySim.running) {
        const w = _state.citySim.weather;
        // Update window emissive intensity based on time of day
        if (_state.materials?.buildingWindow) {
            _state.materials.buildingWindow.emissiveIntensity = w.windowEmissive;
            _state.materials.buildingWindow.opacity = w.isNight ? 0.9 : 0.5;
        }
        // Update weather VFX (rain particles, street lights)
        const camX = _state.cam?.x || 0;
        const camZ = _state.cam?.z || 0;
        _state.weatherVFX.update(_state.dt, w, camX, -camZ);
    }

    // Render (bloom composer or direct)
    if (_state.renderer && _state.scene && _state.camera) {
        if (_state.bloomEnabled && _state.composer) {
            _state.composer.render();
        } else {
            _state.renderer.render(_state.scene, _state.camera);
        }
    }

    // Minimap
    _drawMinimap();

    // Update coords display
    _updateCoordsDisplay();

    // Update layer HUD (throttled to 2Hz)
    if (now - (_state.lastHudUpdate || 0) > 500) {
        _state.lastHudUpdate = now;
        _updateLayerHud();
    }
}

function _updateFps() {
    const el = document.getElementById('status-fps');
    if (el) el.textContent = `${_state.currentFps} FPS`;
    const mapFps = document.getElementById('map-fps');
    if (mapFps) mapFps.textContent = `${_state.currentFps} FPS`;
}

// ============================================================
// Resize
// ============================================================

function _handleResize() {
    if (!_state.container || !_state.renderer || !_state.camera) return;
    const w = _state.container.clientWidth;
    const h = _state.container.clientHeight;
    if (w === 0 || h === 0) return;

    _state.renderer.setSize(w, h);
    if (_state.composer) _state.composer.setSize(w, h);
    const aspect = w / h;
    const zoom = _state.cam.zoom;
    _state.camera.left = -zoom * aspect;
    _state.camera.right = zoom * aspect;
    _state.camera.top = zoom;
    _state.camera.bottom = -zoom;
    _state.camera.updateProjectionMatrix();
}

// ============================================================
// Input events
// ============================================================

function _bindEvents() {
    const el = _state.renderer.domElement;

    // Mouse move (coords display + edge scroll + hover)
    const onMouseMove = (e) => {
        const rect = el.getBoundingClientRect();
        _state.lastMouse = {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
            clientX: e.clientX,
            clientY: e.clientY,
        };

        if (_state.isPanning && _state.panStart) {
            const dx = (e.clientX - _state.panStart.clientX) / _state.cam.zoom * 2;
            const dy = (e.clientY - _state.panStart.clientY) / _state.cam.zoom * 2;
            _state.cam.targetX = _state.panStart.camX - dx;
            _state.cam.targetY = _state.panStart.camY + dy;
        }
    };

    // Mouse down (pan start or select)
    const onMouseDown = (e) => {
        if (e.button === 1 || (e.button === 0 && e.shiftKey)) {
            // Middle click or shift+left = pan
            _state.isPanning = true;
            _state.panStart = {
                clientX: e.clientX,
                clientY: e.clientY,
                camX: _state.cam.targetX,
                camY: _state.cam.targetY,
            };
            el.style.cursor = 'grabbing';
        } else if (e.button === 0) {
            // Left click = select
            _selectAtScreen(e);
        } else if (e.button === 2) {
            // Right click = dispatch
            if (_state.dispatchMode && _state.dispatchUnitId) {
                _dispatchToScreen(e);
            } else {
                const selectedId = TritiumStore.get('map.selectedUnitId');
                if (selectedId) {
                    _state.dispatchUnitId = selectedId;
                    _dispatchToScreen(e);
                }
            }
        }
    };

    const onMouseUp = (e) => {
        if (_state.isPanning) {
            _state.isPanning = false;
            _state.panStart = null;
            el.style.cursor = 'crosshair';
        }
    };

    // Wheel zoom
    const onWheel = (e) => {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 1.15 : 0.87;
        _state.cam.targetZoom = Math.max(ZOOM_MIN,
            Math.min(ZOOM_MAX, _state.cam.targetZoom * factor));
    };

    // Context menu (prevent default)
    const onContextMenu = (e) => e.preventDefault();

    el.addEventListener('mousemove', onMouseMove);
    el.addEventListener('mousedown', onMouseDown);
    el.addEventListener('mouseup', onMouseUp);
    el.addEventListener('wheel', onWheel, { passive: false });
    el.addEventListener('contextmenu', onContextMenu);

    // Track mouse enter/leave for edge scrolling guard
    const onMouseEnter = () => { _state.mouseOverCanvas = true; };
    const onMouseLeave = () => { _state.mouseOverCanvas = false; };
    el.addEventListener('mouseenter', onMouseEnter);
    el.addEventListener('mouseleave', onMouseLeave);

    _state.boundHandlers.set('mousemove', onMouseMove);
    _state.boundHandlers.set('mousedown', onMouseDown);
    _state.boundHandlers.set('mouseup', onMouseUp);
    _state.boundHandlers.set('wheel', onWheel);
    _state.boundHandlers.set('contextmenu', onContextMenu);
    _state.boundHandlers.set('mouseenter', onMouseEnter);
    _state.boundHandlers.set('mouseleave', onMouseLeave);
}

function _selectAtScreen(e) {
    const rect = _state.renderer.domElement.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    _state.raycaster.setFromCamera(new THREE.Vector2(x, y), _state.camera);

    // Collect all unit group meshes
    const meshes = [];
    for (const group of Object.values(_state.unitMeshes)) {
        group.traverse(c => { if (c.isMesh) meshes.push(c); });
    }

    const hits = _state.raycaster.intersectObjects(meshes, false);
    if (hits.length > 0) {
        // Walk up to find the unit group
        let obj = hits[0].object;
        while (obj.parent && !obj.userData.targetId) obj = obj.parent;
        if (obj.userData.targetId) {
            TritiumStore.set('map.selectedUnitId', obj.userData.targetId);
            EventBus.emit('unit:selected', { id: obj.userData.targetId });
            return;
        }
    }

    // Clicked empty space — deselect
    TritiumStore.set('map.selectedUnitId', null);
    EventBus.emit('unit:selected', { id: null });
}

function _dispatchToScreen(e) {
    const rect = _state.renderer.domElement.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    _state.raycaster.setFromCamera(new THREE.Vector2(x, y), _state.camera);
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const intersection = new THREE.Vector3();
    _state.raycaster.ray.intersectPlane(groundPlane, intersection);

    if (intersection) {
        const worldX = intersection.x;
        const worldY = -intersection.z; // Three.js Z -> game Y (inverted)
        const unitId = _state.dispatchUnitId || TritiumStore.get('map.selectedUnitId');

        if (unitId) {
            // Draw dispatch arrow
            const group = _state.unitMeshes[unitId];
            if (group) {
                const fromX = group.position.x;
                const fromY = -group.position.z;
                _addDispatchArrow(fromX, fromY, worldX, worldY);
            }

            // Send dispatch command
            EventBus.emit('unit:dispatched', { id: unitId, x: worldX, y: worldY });
            fetch('/api/amy/command', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'dispatch', params: [unitId, worldX, worldY] }),
            }).then(r => {
                if (!r.ok) {
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

        _state.dispatchMode = false;
        _state.dispatchUnitId = null;
    }
}

// ============================================================
// Coords display
// ============================================================

function _updateCoordsDisplay() {
    const coordsEl = document.getElementById('map-coords');
    if (!coordsEl) return;

    // Raycast from mouse to ground
    const mx = _state.lastMouse.x || 0;
    const my = _state.lastMouse.y || 0;
    const rect = _state.renderer?.domElement?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;

    const ndcX = ((mx) / rect.width) * 2 - 1;
    const ndcY = -((my) / rect.height) * 2 + 1;

    _state.raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), _state.camera);
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const intersection = new THREE.Vector3();
    _state.raycaster.ray.intersectPlane(groundPlane, intersection);

    if (intersection) {
        const xEl = coordsEl.querySelector('[data-coord="x"]');
        const yEl = coordsEl.querySelector('[data-coord="y"]');
        if (xEl) xEl.textContent = `X: ${intersection.x.toFixed(1)}`;
        if (yEl) yEl.textContent = `Y: ${(-intersection.z).toFixed(1)}`;
    }
}

// ============================================================
// EventBus handlers
// ============================================================

function _onUnitsUpdated() {
    // Auto-fit camera on first data
    if (!_state.hasAutoFit && TritiumStore.units.size > 0) {
        _state.hasAutoFit = true;
        _autoFitCamera();
    }
}

function _autoFitCamera() {
    const units = TritiumStore.units;
    if (units.size === 0) return;

    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    units.forEach(u => {
        const pos = u.position || {};
        const x = pos.x !== undefined ? pos.x : 0;
        const y = pos.y !== undefined ? pos.y : 0;
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
    });

    const cx = (minX + maxX) / 2;
    const cy = (minY + maxY) / 2;
    const rangeX = maxX - minX;
    const rangeY = maxY - minY;
    const padding = 1.3;
    const zoom = Math.max(ZOOM_MIN, Math.max(rangeX, rangeY) * padding / 2 + 5);

    _state.cam.targetX = cx;
    _state.cam.targetY = cy;
    _state.cam.targetZoom = Math.min(ZOOM_MAX, zoom);
}

function _onMapMode(data) {
    // Map mode changes (observe/tactical/setup)
    console.log('[MAP3D] Mode:', data.mode);
}

function _onDispatchMode(data) {
    _state.dispatchMode = true;
    _state.dispatchUnitId = data.id;
    if (_state.renderer) _state.renderer.domElement.style.cursor = 'cell';
}

function _onDispatched(data) {
    _state.dispatchMode = false;
    _state.dispatchUnitId = null;
    if (_state.renderer) _state.renderer.domElement.style.cursor = 'crosshair';
}

function _onSelectedUnitChanged(id) {
    // Selection handled in _updateSelection()
}

// ============================================================
// Minimap (Canvas 2D)
// ============================================================

function _drawMinimap() {
    const mc = _state.minimapCanvas;
    if (!mc) return;
    const ctx = mc.getContext('2d');
    if (!ctx) return;

    const w = mc.width;
    const h = mc.height;
    const mapRange = 100; // visible range on minimap

    ctx.fillStyle = 'rgba(6, 6, 9, 0.85)';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = 'rgba(0, 240, 255, 0.06)';
    ctx.lineWidth = 0.5;
    const gridStep = mapRange / 5;
    for (let g = -mapRange; g <= mapRange; g += gridStep) {
        const sx = (g / mapRange * 0.5 + 0.5) * w;
        const sy = (-g / mapRange * 0.5 + 0.5) * h;
        ctx.beginPath(); ctx.moveTo(sx, 0); ctx.lineTo(sx, h); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, sy); ctx.lineTo(w, sy); ctx.stroke();
    }

    // Units
    for (const [id, unit] of TritiumStore.units) {
        const pos = unit.position || {};
        const gx = pos.x !== undefined ? pos.x : 0;
        const gy = pos.y !== undefined ? pos.y : 0;

        const sx = (gx / mapRange * 0.5 + 0.5) * w;
        const sy = (-gy / mapRange * 0.5 + 0.5) * h;

        const alliance = (unit.alliance || 'unknown').toLowerCase();
        ctx.fillStyle = ALLIANCE_HEX[alliance] || '#fcee0a';

        ctx.beginPath();
        ctx.arc(sx, sy, alliance === 'hostile' ? 3 : 2, 0, Math.PI * 2);
        ctx.fill();
    }

    // Camera viewport indicator
    const aspect = _state.container
        ? _state.container.clientWidth / Math.max(1, _state.container.clientHeight)
        : 1;
    const camW = (_state.cam.zoom * 2 * aspect) / mapRange * 0.5 * w;
    const camH = (_state.cam.zoom * 2) / mapRange * 0.5 * h;
    const camSX = (_state.cam.x / mapRange * 0.5 + 0.5) * w;
    const camSY = (-_state.cam.y / mapRange * 0.5 + 0.5) * h;

    ctx.strokeStyle = 'rgba(0, 240, 255, 0.4)';
    ctx.lineWidth = 1;
    ctx.strokeRect(camSX - camW / 2, camSY - camH / 2, camW, camH);
}

// ============================================================
// Satellite tiles
// ============================================================

function _loadGeoReference() {
    fetch('/api/geo/reference')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data) return;
            if (!data.initialized) {
                _state.noLocationSet = true;
                _addNoLocationText();
                return;
            }
            _state.geoCenter = { lat: data.lat, lng: data.lng };
            _state.noLocationSet = false;
            _loadSatelliteTiles(data.lat, data.lng);
            _loadOverlayData();
        })
        .catch(err => console.warn('[MAP3D] Geo reference fetch failed:', err));
}

function _addNoLocationText() {
    // Add a 3D text sprite at origin
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 512;
    canvas.height = 128;
    ctx.clearRect(0, 0, 512, 128);

    ctx.font = `bold 36px ${FONT_FAMILY}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(0, 240, 255, 0.15)';
    ctx.fillText('NO LOCATION SET', 256, 48);

    ctx.font = `18px ${FONT_FAMILY}`;
    ctx.fillStyle = 'rgba(0, 240, 255, 0.10)';
    ctx.fillText('Set MAP_CENTER_LAT / MAP_CENTER_LNG', 256, 88);

    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;
    const mat = new THREE.SpriteMaterial({
        map: tex, transparent: true, depthWrite: false, sizeAttenuation: false,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(0.3, 0.075, 1);
    sprite.position.set(0, 5, 0);
    sprite.name = 'noLocationLabel';
    _state.scene.add(sprite);
}

function _getSatTileLevelIndex() {
    const zoom = _state.cam.zoom;
    for (let i = 0; i < SAT_TILE_LEVELS.length; i++) {
        if (zoom < SAT_TILE_LEVELS[i][0]) return i;
    }
    return SAT_TILE_LEVELS.length - 1;
}

function _checkSatelliteTileReload() {
    if (!_state.geoCenter || !_state.showSatellite) return;
    const newLevel = _getSatTileLevelIndex();
    if (newLevel === _state.satTileLevel) return;

    // Update level immediately to stop retriggering on every frame
    _state.satTileLevel = newLevel;

    // Debounce the actual tile fetch (zoom may still be lerping)
    clearTimeout(_state.satReloadTimer);
    _state.satReloadTimer = setTimeout(() => {
        const idx = _getSatTileLevelIndex();
        _state.satTileLevel = idx;
        const [, tileZoom, radius] = SAT_TILE_LEVELS[idx];
        console.log(`[MAP3D] Reloading tiles: zoom=${tileZoom}, radius=${radius}m`);
        _fetchTilesFromApi(_state.geoCenter.lat, _state.geoCenter.lng, radius, tileZoom);
    }, 500);
}

function _loadSatelliteTiles(lat, lng) {
    const levelIdx = _getSatTileLevelIndex();
    _state.satTileLevel = levelIdx;
    const [, tileZoom, radius] = SAT_TILE_LEVELS[levelIdx];
    _fetchTilesFromApi(lat, lng, radius, tileZoom);
}

function _fetchTilesFromApi(centerLat, centerLng, radiusMeters, zoom) {
    // Calculate tile range
    const n = Math.pow(2, zoom);
    const latRad = centerLat * Math.PI / 180;

    const centerTX = Math.floor((centerLng + 180) / 360 * n);
    const centerTY = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);

    const tileSize = 40075016.686 * Math.cos(latRad) / n;
    const tilesNeeded = Math.ceil(radiusMeters / tileSize) + 1;

    const tiles = [];
    const roadTiles = [];
    let loaded = 0;
    let total = 0;

    // Helper: compute tile bounds in game coords
    function _tileBounds(tx, ty) {
        const tileLng = tx / n * 360 - 180;
        const tileLngEnd = (tx + 1) / n * 360 - 180;
        const tileLat = Math.atan(Math.sinh(Math.PI * (1 - 2 * ty / n))) * 180 / Math.PI;
        const tileLatEnd = Math.atan(Math.sinh(Math.PI * (1 - 2 * (ty + 1) / n))) * 180 / Math.PI;
        const R = 6378137;
        return {
            minX: (tileLng - centerLng) * Math.PI / 180 * R * Math.cos(latRad),
            maxX: (tileLngEnd - centerLng) * Math.PI / 180 * R * Math.cos(latRad),
            minY: (tileLatEnd - centerLat) * Math.PI / 180 * R,
            maxY: (tileLat - centerLat) * Math.PI / 180 * R,
        };
    }

    for (let dx = -tilesNeeded; dx <= tilesNeeded; dx++) {
        for (let dy = -tilesNeeded; dy <= tilesNeeded; dy++) {
            const tx = centerTX + dx;
            const ty = centerTY + dy;
            if (ty < 0 || ty >= n) continue;
            total += 2;  // satellite + road overlay

            const bounds = _tileBounds(tx, ty);

            // Satellite tile
            const satImg = new Image();
            satImg.crossOrigin = 'anonymous';
            satImg.onload = () => {
                loaded++;
                tiles.push({ image: satImg, bounds });
                if (loaded === total) _applySatelliteTexture(tiles, roadTiles, centerLat, centerLng, radiusMeters);
            };
            satImg.onerror = () => {
                loaded++;
                if (loaded === total && tiles.length > 0) _applySatelliteTexture(tiles, roadTiles, centerLat, centerLng, radiusMeters);
            };
            satImg.src = `/api/geo/tile/${zoom}/${tx}/${ty}`;

            // Road overlay tile (transparent PNG, aligned with satellite)
            const roadImg = new Image();
            roadImg.crossOrigin = 'anonymous';
            roadImg.onload = () => {
                loaded++;
                roadTiles.push({ image: roadImg, bounds });
                if (loaded === total) _applySatelliteTexture(tiles, roadTiles, centerLat, centerLng, radiusMeters);
            };
            roadImg.onerror = () => {
                loaded++;
                if (loaded === total && tiles.length > 0) _applySatelliteTexture(tiles, roadTiles, centerLat, centerLng, radiusMeters);
            };
            roadImg.src = `/api/geo/road-tile/${zoom}/${tx}/${ty}`;
        }
    }
}

function _applySatelliteTexture(tiles, roadOverlayTiles, centerLat, centerLng, radiusMeters) {
    if (tiles.length === 0) return;

    // Remove "no location" label if present
    const noLocLabel = _state.scene.getObjectByName('noLocationLabel');
    if (noLocLabel) _state.scene.remove(noLocLabel);

    // Compute bounding box of all tiles in game coords
    let bMinX = Infinity, bMaxX = -Infinity;
    let bMinY = Infinity, bMaxY = -Infinity;
    for (const t of tiles) {
        bMinX = Math.min(bMinX, t.bounds.minX);
        bMaxX = Math.max(bMaxX, t.bounds.maxX);
        bMinY = Math.min(bMinY, t.bounds.minY);
        bMaxY = Math.max(bMaxY, t.bounds.maxY);
    }

    const rangeX = bMaxX - bMinX;
    const rangeY = bMaxY - bMinY;

    // Composite all tiles onto a single canvas (4096 for sharp satellite detail)
    const canvasSize = 4096;
    const canvas = document.createElement('canvas');
    canvas.width = canvasSize;
    canvas.height = canvasSize;
    const ctx = canvas.getContext('2d');

    ctx.fillStyle = '#060609';
    ctx.fillRect(0, 0, canvasSize, canvasSize);

    // Layer 1: satellite imagery
    for (const t of tiles) {
        const px = ((t.bounds.minX - bMinX) / rangeX) * canvasSize;
        const py = ((bMaxY - t.bounds.maxY) / rangeY) * canvasSize;
        const pw = ((t.bounds.maxX - t.bounds.minX) / rangeX) * canvasSize;
        const ph = ((t.bounds.maxY - t.bounds.minY) / rangeY) * canvasSize;
        ctx.drawImage(t.image, px, py, pw, ph);
    }

    // Layer 2: ESRI road overlay (transparent PNGs, pixel-aligned with satellite)
    if (roadOverlayTiles && roadOverlayTiles.length > 0) {
        ctx.globalAlpha = 0.7;
        for (const t of roadOverlayTiles) {
            const px = ((t.bounds.minX - bMinX) / rangeX) * canvasSize;
            const py = ((bMaxY - t.bounds.maxY) / rangeY) * canvasSize;
            const pw = ((t.bounds.maxX - t.bounds.minX) / rangeX) * canvasSize;
            const ph = ((t.bounds.maxY - t.bounds.minY) / rangeY) * canvasSize;
            ctx.drawImage(t.image, px, py, pw, ph);
        }
        ctx.globalAlpha = 1.0;
        console.log(`[MAP3D] Road overlay: ${roadOverlayTiles.length} tiles composited`);
    }

    // Create or update ground texture with high-quality filtering
    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearMipMapLinearFilter;
    tex.magFilter = THREE.LinearFilter;
    tex.generateMipmaps = true;
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.wrapT = THREE.ClampToEdgeWrapping;
    // Anisotropic filtering for sharp texture at oblique angles
    if (_state.renderer) {
        tex.anisotropy = _state.renderer.capabilities.getMaxAnisotropy();
    }

    if (_state.satTexture) _state.satTexture.dispose();
    _state.satTexture = tex;

    // Update ground mesh to show satellite
    if (_state.groundMesh) {
        _state.groundMesh.material.map = tex;
        _state.groundMesh.material.color.setHex(0xffffff);
        _state.groundMesh.material.needsUpdate = true;

        // Resize and position ground to match tile bounds
        _state.groundMesh.scale.set(rangeX / 5000, 1, rangeY / 5000);
        const centerGX = (bMinX + bMaxX) / 2;
        const centerGY = (bMinY + bMaxY) / 2;
        const tp = gameToThree(centerGX, centerGY);
        _state.groundMesh.position.x = tp.x;
        _state.groundMesh.position.z = tp.z;
    }

    console.log(`[MAP3D] Satellite texture applied: ${tiles.length} tiles, ${rangeX.toFixed(0)}x${rangeY.toFixed(0)}m`);
}

// ============================================================
// Zones fetch
// ============================================================

function _fetchZones() {
    fetch('/api/zones')
        .then(r => r.ok ? r.json() : [])
        .then(data => {
            if (Array.isArray(data)) {
                _state.zones = data;
            } else if (data && Array.isArray(data.zones)) {
                _state.zones = data.zones;
            }
        })
        .catch(() => {});
}

// ============================================================
// Overlay: buildings + roads from /api/geo/overlay
// ============================================================

async function _loadOverlayData() {
    // Load legacy overlay first (startup-cached roads/buildings)
    try {
        const resp = await fetch('/api/geo/overlay');
        if (resp.ok) {
            _state.overlayData = await resp.json();
        }
    } catch (e) {
        console.warn('[MAP3D] Overlay fetch failed:', e.message);
    }

    // Try comprehensive city data endpoint (buildings, roads, trees, landuse, barriers, water)
    if (_state.geoCenter) {
        const { lat, lng } = _state.geoCenter;

        try {
            const resp = await fetch(`/api/geo/city-data?lat=${lat}&lng=${lng}&radius=500`);
            if (resp.ok) {
                const cityData = await resp.json();
                _state.overlayData = _state.overlayData || {};

                // City data is already in local meters from backend
                if (cityData.buildings?.length) {
                    _state.overlayData.buildings = cityData.buildings;
                    console.log(`[MAP3D] City data: ${cityData.buildings.length} buildings`);
                }
                if (cityData.roads?.length) {
                    _state.overlayData.roads = cityData.roads;
                    console.log(`[MAP3D] City data: ${cityData.roads.length} roads`);
                }
                if (cityData.trees?.length) {
                    _state.overlayData.trees = cityData.trees;
                    console.log(`[MAP3D] City data: ${cityData.trees.length} trees`);
                }
                if (cityData.landuse?.length) {
                    _state.overlayData.landuse = cityData.landuse;
                }
                if (cityData.water?.length) {
                    _state.overlayData.water = cityData.water;
                }
                if (cityData.barriers?.length) {
                    _state.overlayData.barriers = cityData.barriers;
                }
                if (cityData.entrances?.length) {
                    _state.overlayData.entrances = cityData.entrances;
                }
                if (cityData.pois?.length) {
                    _state.overlayData.pois = cityData.pois;
                }
                if (cityData.furniture?.length) {
                    _state.overlayData.furniture = cityData.furniture;
                }

                // Build road network graph for simulation
                if (cityData.roads?.length) {
                    _state.citySim.roadNetwork = null;  // Reset
                    _state.citySim.cityData = cityData;
                    const { RoadNetwork } = await import('./sim/road-network.js');
                    _state.citySim.roadNetwork = new RoadNetwork();
                    _state.citySim.roadNetwork.buildFromOSM(cityData.roads);
                    _state.citySim.loaded = true;
                    const stats = _state.citySim.roadNetwork.stats();
                    console.log(
                        `[MAP3D] Road graph: ${stats.nodes} nodes, ${stats.edges} edges, ` +
                        `${stats.totalLengthM}m total`
                    );

                    // Initialize rendering and spawn entities
                    if (_state.scene && stats.edges > 0) {
                        _state.citySim.initRendering(THREE, _state.scene);
                        _state.citySim.spawnVehicles(Math.min(100, stats.edges * 2));
                        _state.citySim.spawnPedestrians(Math.min(50, stats.edges));

                        // Initialize weather VFX with street lights at intersections
                        const lightPositions = WeatherVFX.generateLightPositions(
                            _state.citySim.roadNetwork, gameToThree
                        );
                        _state.weatherVFX.init(THREE, _state.scene, lightPositions);
                    }
                }
            }
        } catch (e) {
            console.warn('[MAP3D] City data fetch failed, trying fallbacks:', e.message);
        }

        // Fallback: Microsoft Buildings → OSM Buildings if city-data didn't provide buildings
        if (!_state.overlayData?.buildings?.length) {
            const R = 6378137;
            const latRad = lat * Math.PI / 180;
            const cosFactor = Math.cos(latRad);
            const convertToLocal = (rawBuildings) => rawBuildings.map(b => ({
                polygon: b.polygon.map(([plat, plng]) => [
                    (plng - lng) * Math.PI / 180 * R * cosFactor,
                    (plat - lat) * Math.PI / 180 * R,
                ]),
                height: b.tags?.height ? parseFloat(b.tags.height) || 8 : 8,
            }));

            try {
                const resp = await fetch(`/api/geo/msft-buildings?lat=${lat}&lng=${lng}&radius=500`);
                if (resp.ok) {
                    const rawBuildings = await resp.json();
                    if (rawBuildings.length > 0) {
                        _state.overlayData = _state.overlayData || {};
                        _state.overlayData.buildings = convertToLocal(rawBuildings);
                        console.log(`[MAP3D] Fallback: ${rawBuildings.length} Microsoft buildings`);
                    }
                }
            } catch (e) { /* silent */ }

            if (!_state.overlayData?.buildings?.length) {
                try {
                    const resp = await fetch(`/api/geo/buildings?lat=${lat}&lng=${lng}&radius=500`);
                    if (resp.ok) {
                        const rawBuildings = await resp.json();
                        _state.overlayData = _state.overlayData || {};
                        _state.overlayData.buildings = convertToLocal(rawBuildings);
                        console.log(`[MAP3D] Fallback: ${rawBuildings.length} OSM buildings`);
                    }
                } catch (e) { /* silent */ }
            }
        }
    }

    _buildBuildings();
    await _buildRoads();
    _buildTrees();
    _buildLanduse();
    _buildWater();
    _buildBarriers();
    _buildEntrances();
    _buildPOIs();
    _buildFurniture();
    _loadElevation();
}

async function _loadElevation() {
    if (!_state.geoCenter) return;
    const { lat, lng } = _state.geoCenter;

    try {
        const resp = await fetch(`/api/geo/elevation-grid?lat=${lat}&lng=${lng}&radius=400&resolution=64`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (!data.grid?.length) return;

        _buildTerrainMesh(data);
    } catch (e) {
        console.warn('[MAP3D] Elevation load failed:', e.message);
    }
}

function _buildTerrainMesh(elevData) {
    const { grid, resolution, radius, min_elev, max_elev } = elevData;
    if (!grid.length || resolution < 2) return;

    // Remove existing terrain mesh if any
    if (_state.terrainMesh) {
        _state.scene.remove(_state.terrainMesh);
        _state.terrainMesh.geometry.dispose();
        _state.terrainMesh.material.dispose();
    }

    const size = radius * 2;
    const geo = new THREE.PlaneGeometry(size, size, resolution - 1, resolution - 1);
    const pos = geo.attributes.position;

    // Normalize elevation: map min_elev→0, scale so terrain is visible but not overwhelming
    const elevRange = max_elev - min_elev;
    const elevScale = elevRange > 0 ? Math.min(elevRange * 0.5, 20.0) / elevRange : 0;

    for (let i = 0; i < pos.count; i++) {
        const h = grid[i] !== undefined ? (grid[i] - min_elev) * elevScale : 0;
        pos.setZ(i, h);
    }

    geo.computeVertexNormals();

    // Rotate to XZ plane (PlaneGeometry is in XY by default)
    geo.rotateX(-Math.PI / 2);

    const mat = new THREE.MeshStandardMaterial({
        color: 0x1a2a1a,
        roughness: 0.95,
        metalness: 0.0,
        transparent: true,
        opacity: 0.3,
        wireframe: false,
        side: THREE.DoubleSide,
        depthWrite: false,
    });

    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.y = -0.1;  // Slightly below ground plane
    mesh.receiveShadow = true;

    _state.scene.add(mesh);
    _state.terrainMesh = mesh;

    console.log(
        `[MAP3D] Terrain: ${resolution}x${resolution} mesh, ` +
        `elevation ${min_elev.toFixed(0)}-${max_elev.toFixed(0)}m (scale: ${elevScale.toFixed(2)})`
    );
}

function _buildBuildings() {
    const buildings = _state.overlayData?.buildings;
    if (!buildings?.length) return;

    const group = new THREE.Group();
    group.name = 'buildings';

    // Material lookup by category
    const categoryMats = {
        residential: _state.materials.buildingResidential,
        commercial: _state.materials.buildingCommercial,
        industrial: _state.materials.buildingIndustrial,
        civic: _state.materials.buildingCivic,
        religious: _state.materials.buildingReligious,
        utility: _state.materials.buildingUtility,
    };

    // Deterministic hash for per-building variation
    const bldgHash = (id) => ((id * 2654435761) >>> 0) % 1000 / 1000;

    for (const bldg of buildings) {
        const poly = bldg.polygon;
        if (!poly || poly.length < 3) continue;

        const height = bldg.height || 8;
        const category = bldg.category || 'residential';
        const hash = bldgHash(bldg.id || 0);

        // Material selection: use building colour tag, else category default with hash variation
        let wallMat;
        if (bldg.colour) {
            // OSM building:colour — create tinted material
            const tinted = (categoryMats[category] || _state.materials.building).clone();
            try {
                const c = new THREE.Color(bldg.colour);
                tinted.color.lerp(c, 0.5);  // Blend OSM colour with base
            } catch (_) { /* invalid colour string */ }
            wallMat = tinted;
        } else {
            // Hash-based variation: slightly shift hue/brightness per building
            const baseMat = categoryMats[category] || _state.materials.building;
            if (hash > 0.7) {
                // 30% of buildings get a slight color variation
                const varied = baseMat.clone();
                const hsl = {};
                varied.color.getHSL(hsl);
                hsl.l = Math.max(0.05, Math.min(0.3, hsl.l + (hash - 0.85) * 0.15));
                varied.color.setHSL(hsl.h, hsl.s, hsl.l);
                wallMat = varied;
            } else {
                wallMat = baseMat;
            }
        }

        // Create 2D shape from polygon (game coordinates)
        const shape = new THREE.Shape();
        for (let i = 0; i < poly.length; i++) {
            const [gx, gy] = poly[i];
            if (i === 0) shape.moveTo(gx, gy);
            else shape.lineTo(gx, gy);
        }
        shape.closePath();

        // Extrude into 3D building
        const extGeo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
        // ExtrudeGeometry: shape in XY, extrudes along Z → rotate to XZ ground, Y up
        const wallMesh = new THREE.Mesh(extGeo, wallMat);
        wallMesh.rotation.x = -Math.PI / 2;
        wallMesh.position.y = 0;
        wallMesh.castShadow = true;
        wallMesh.receiveShadow = true;
        group.add(wallMesh);

        // Roof cap
        const roofGeo = new THREE.ShapeGeometry(shape);
        const roofMesh = new THREE.Mesh(roofGeo, _state.materials.buildingRoof);
        roofMesh.rotation.x = -Math.PI / 2;
        roofMesh.position.y = height;
        roofMesh.receiveShadow = true;
        group.add(roofMesh);

        // Edge outlines (ground + roofline + verticals)
        const outlineGround = [], outlineRoof = [];
        for (const [gx, gy] of poly) {
            const tp = gameToThree(gx, gy);
            outlineGround.push(new THREE.Vector3(tp.x, 0.15, tp.z));
            outlineRoof.push(new THREE.Vector3(tp.x, height, tp.z));
        }
        if (outlineGround.length > 0) {
            outlineGround.push(outlineGround[0].clone());
            outlineRoof.push(outlineRoof[0].clone());
        }
        group.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(outlineGround), _state.materials.buildingEdge));
        group.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(outlineRoof), _state.materials.buildingEdge));
        for (let i = 0; i < outlineGround.length - 1; i += Math.max(2, Math.floor(outlineGround.length / 6))) {
            group.add(new THREE.Line(
                new THREE.BufferGeometry().setFromPoints([outlineGround[i].clone(), outlineRoof[i].clone()]),
                _state.materials.buildingEdge));
        }

        // Windows — skip utility/low buildings
        if (height > 4 && category !== 'utility') {
            const floors = Math.floor(height / 3);
            // Walk polygon edges to place windows on walls
            for (let ei = 0; ei < poly.length - 1; ei++) {
                const [ax, ay] = poly[ei];
                const [bx, by] = poly[(ei + 1) % poly.length];
                const wallLen = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
                if (wallLen < 3) continue;

                // Direction along wall & perpendicular (outward normal)
                const dx = (bx - ax) / wallLen;
                const dy = (by - ay) / wallLen;
                // Normal pointing outward (left-hand for CW winding)
                const nx = -dy, ny = dx;

                const winSpacing = category === 'commercial' ? 2.5 : 3.5;
                const numWins = Math.max(1, Math.floor((wallLen - 2) / winSpacing));

                for (let f = 0; f < floors; f++) {
                    const wy = f * 3 + 2;
                    if (wy > height - 1.5) break;
                    for (let w = 0; w < numWins; w++) {
                        // Deterministic skip for variety
                        const wHash = bldgHash((bldg.id || 0) + ei * 100 + f * 10 + w);
                        if (wHash > 0.65) continue;

                        const t = (w + 1) / (numWins + 1);
                        const wx = ax + dx * wallLen * t + nx * 0.05;
                        const wz = ay + dy * wallLen * t + ny * 0.05;
                        const tp = gameToThree(wx, wz);

                        const winGeo = new THREE.PlaneGeometry(1.0, 1.2);
                        const winMesh = new THREE.Mesh(winGeo, _state.materials.buildingWindow);
                        winMesh.position.set(tp.x, wy, tp.z);
                        // Rotate window to face outward along wall normal
                        winMesh.rotation.y = Math.atan2(nx, ny);
                        group.add(winMesh);
                    }
                }
            }
        }
    }

    // Always use LOD manager for consistent rendering path (fixes n=51 discontinuity)
    // The individual meshes in `group` above are NOT used — LOD handles everything.
    // categoryMats already declared above

    _state.lodManager = new LODManager();
    for (const bldg of buildings) {
        _state.lodManager.assignSector(bldg);
    }

    const lodRoot = _state.lodManager.buildGeometry(THREE, gameToThree, _state.materials, categoryMats);
    _state.scene.add(lodRoot);
    _state.buildingGroup = lodRoot;

    const lodStats = _state.lodManager.getStats();
    console.log(`[MAP3D] Buildings: ${buildings.length} in ${lodStats.sectors} LOD sectors`);
}

async function _buildRoads() {
    const roads = _state.overlayData?.roads;
    if (!roads?.length) return;

    const group = new THREE.Group();
    group.name = 'roads';

    const primaryTypes = new Set(['motorway', 'trunk', 'primary', 'secondary', 'tertiary',
        'motorway_link', 'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link']);
    const footTypes = new Set(['footway', 'cycleway', 'path', 'pedestrian']);

    for (const road of roads) {
        const roadClass = road.class || 'residential';
        const isPrimary = primaryTypes.has(roadClass);
        const isFoot = footTypes.has(roadClass);
        // Use actual width from OSM data if available
        const width = road.width || (isPrimary ? 5.0 : isFoot ? 1.5 : 3.0);

        const points = (road.points || []).map(([gx, gy]) => {
            const tp = gameToThree(gx, gy);
            return new THREE.Vector3(tp.x, road.bridge ? 3.0 : 0.05, tp.z);
        });

        if (points.length < 2) continue;

        // Road ribbon with proper width
        const mat = isPrimary ? _state.materials.roadPrimary
            : isFoot ? _state.materials.roadFootway
            : _state.materials.road;
        const ribbon = _createRoadRibbon(points, width, mat);
        if (ribbon) group.add(ribbon);

        // Center line for primary roads
        if (isPrimary && !isFoot) {
            const lineGeo = new THREE.BufferGeometry().setFromPoints(
                points.map(p => new THREE.Vector3(p.x, p.y + 0.02, p.z)));
            const lineMat = new THREE.LineBasicMaterial({
                color: 0xccaa00, transparent: true, opacity: 0.3,
            });
            group.add(new THREE.Line(lineGeo, lineMat));
        }

        // Bridge pillars
        if (road.bridge) {
            for (let i = 0; i < points.length; i += 4) {
                const p = points[i];
                const pillarGeo = new THREE.CylinderGeometry(0.15, 0.2, 3.0, 6);
                const pillar = new THREE.Mesh(pillarGeo, _state.materials.barrier);
                pillar.position.set(p.x, 1.5, p.z);
                group.add(pillar);
            }
        }
    }

    // Lane markings — center lines on multi-lane roads, dashed
    const markingGeos = [];
    const markingMat = new THREE.MeshBasicMaterial({
        color: 0xccaa00, transparent: true, opacity: 0.3,
        side: THREE.DoubleSide, depthWrite: false,
    });

    for (const road of roads) {
        const roadClass = road.class || 'residential';
        const isMultiLane = (road.lanes || 2) > 1;
        const isFoot = new Set(['footway', 'cycleway', 'path', 'pedestrian']).has(roadClass);
        if (!isMultiLane || isFoot) continue;

        const pts = (road.points || []);
        if (pts.length < 2) continue;

        // Dashed center line
        const DASH = 2, GAP = 3;
        for (let i = 0; i < pts.length - 1; i++) {
            const [ax, ay] = pts[i];
            const [bx, by] = pts[i + 1];
            const segLen = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
            if (segLen < DASH + GAP) continue;

            const dx = (bx - ax) / segLen;
            const dy = (by - ay) / segLen;
            const numDashes = Math.floor(segLen / (DASH + GAP));

            for (let d = 0; d < numDashes; d++) {
                const startT = d * (DASH + GAP);
                const cx = ax + dx * (startT + DASH / 2);
                const cy = ay + dy * (startT + DASH / 2);
                const tp = gameToThree(cx, cy);
                const angle = Math.atan2(dx, dy);

                const dashGeo = new THREE.PlaneGeometry(0.15, DASH);
                dashGeo.rotateX(-Math.PI / 2);
                dashGeo.rotateY(angle);
                dashGeo.translate(tp.x, (road.bridge ? 3.02 : 0.06), tp.z);
                markingGeos.push(dashGeo);
            }
        }
    }

    // Crosswalks at intersections (degree >= 3)
    const crosswalkGeos = [];
    const crosswalkMat = new THREE.MeshBasicMaterial({
        color: 0xffffff, transparent: true, opacity: 0.5,
        side: THREE.DoubleSide, depthWrite: false,
    });

    const rn = _state.citySim?.roadNetwork;
    if (rn) {
        for (const nodeId in rn.nodes) {
            const node = rn.nodes[nodeId];
            if (node.degree < 3) continue;

            const edgeIndices = rn.adjList[nodeId] || [];
            for (const ei of edgeIndices) {
                const edge = rn.edges[ei];
                if (!edge) continue;

                // Direction from intersection toward the road
                const isFrom = edge.from === nodeId;
                const dx = isFrom ? (edge.bx - edge.ax) : (edge.ax - edge.bx);
                const dz = isFrom ? (edge.bz - edge.az) : (edge.az - edge.bz);
                const len = Math.sqrt(dx * dx + dz * dz);
                if (len < 1) continue;

                const dirX = dx / len;
                const dirZ = dz / len;
                const perpX = -dirZ;
                const perpZ = dirX;

                // Road width estimate
                const roadWidth = edge.laneWidth * edge.lanesPerDir * 2;
                const offset = roadWidth / 2 + 1.5; // offset from intersection center

                const cx = node.x + dirX * offset;
                const cz = node.z + dirZ * offset;
                const tp = gameToThree(cx, cz);
                const angle = Math.atan2(dirX, dirZ);

                // 7 white stripes across the road
                const STRIPE_COUNT = 7;
                const STRIPE_W = 1.2;
                const STRIPE_H = 0.4;
                const totalSpan = roadWidth - 0.5;
                const spacing = totalSpan / (STRIPE_COUNT - 1);
                const startOffset = -totalSpan / 2;

                for (let s = 0; s < STRIPE_COUNT; s++) {
                    const off = startOffset + s * spacing;
                    const sx = tp.x + perpX * off;
                    const sz = tp.z + perpZ * off;

                    const stripeGeo = new THREE.PlaneGeometry(STRIPE_W, STRIPE_H);
                    stripeGeo.rotateX(-Math.PI / 2);
                    stripeGeo.rotateY(angle);
                    stripeGeo.translate(sx, 0.07, sz);
                    crosswalkGeos.push(stripeGeo);
                }
            }
        }
    }

    if (markingGeos.length > 0 || crosswalkGeos.length > 0) {
        const { mergeGeometries } = await import('three/addons/utils/BufferGeometryUtils.js');
        if (markingGeos.length > 0) {
            const merged = mergeGeometries(markingGeos, false);
            if (merged) {
                group.add(new THREE.Mesh(merged, markingMat));
            }
        }
        if (crosswalkGeos.length > 0) {
            const merged = mergeGeometries(crosswalkGeos, false);
            if (merged) {
                group.add(new THREE.Mesh(merged, crosswalkMat));
            }
        }
    }

    _state.scene.add(group);
    _state.roadGroup = group;
    _state.roadGroup.visible = _state.showRoads;
    console.log(`[MAP3D] Roads: ${roads.length} segments, ${markingGeos.length} lane markings, ${crosswalkGeos.length} crosswalk stripes`);

    // Build congestion overlay on top of roads
    _buildCongestionOverlay();
}

/**
 * Build congestion overlay — one colored line segment per road network edge.
 * Colors update each frame based on CitySimManager congestion data.
 */
function _buildCongestionOverlay() {
    const rn = _state.citySim?.roadNetwork;
    if (!rn || rn.edges.length === 0) return;

    const edges = rn.edges;
    const positions = [];
    const colors = [];

    // Store edge-to-index mapping for per-frame color updates
    _state.congestionEdgeMap = new Map(); // edgeId → index into vertex array

    for (let i = 0; i < edges.length; i++) {
        const edge = edges[i];
        const tpA = gameToThree(edge.ax, edge.az);
        const tpB = gameToThree(edge.bx, edge.bz);

        _state.congestionEdgeMap.set(edge.id, i);

        // Two vertices per edge (line segment)
        positions.push(tpA.x, 0.15, tpA.z);
        positions.push(tpB.x, 0.15, tpB.z);

        // Default: transparent gray (no data)
        colors.push(0.3, 0.3, 0.3);
        colors.push(0.3, 0.3, 0.3);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    const mat = new THREE.LineBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: 0.7,
        linewidth: 1,
        depthWrite: false,
    });

    _state.congestionMesh = new THREE.LineSegments(geo, mat);
    _state.congestionMesh.name = 'congestion-overlay';
    _state.congestionMesh.frustumCulled = false;
    _state.congestionMesh.visible = true;
    _state.scene.add(_state.congestionMesh);

    console.log(`[MAP3D] Congestion overlay: ${edges.length} edge segments`);
}

/**
 * Update congestion overlay colors from CitySimManager data.
 */
function _updateCongestionOverlay() {
    if (!_state.congestionMesh || !_state.citySim) return;

    const congestion = _state.citySim.getCongestionData();
    if (!congestion || congestion.size === 0) {
        _state.congestionMesh.visible = false;
        return;
    }

    _state.congestionMesh.visible = true;
    const colorAttr = _state.congestionMesh.geometry.getAttribute('color');
    const arr = colorAttr.array;

    // Reset all to dim gray
    for (let i = 0; i < arr.length; i += 3) {
        arr[i] = 0.15; arr[i + 1] = 0.15; arr[i + 2] = 0.15;
    }

    // Color edges with congestion data
    for (const [edgeId, data] of congestion) {
        const idx = _state.congestionEdgeMap?.get(edgeId);
        if (idx === undefined) continue;

        let r, g, b;
        if (data.ratio > 0.7) {
            // Free flow — green
            r = 0.02; g = 1.0; b = 0.4;
        } else if (data.ratio > 0.3) {
            // Slow — yellow to orange
            const t = (data.ratio - 0.3) / 0.4;
            r = 1.0; g = 0.6 + t * 0.4; b = 0.0;
        } else {
            // Congested — red
            r = 1.0; g = 0.1; b = 0.1;
        }

        // Both vertices of the line segment
        const vi = idx * 6; // 2 vertices * 3 components
        arr[vi] = r;     arr[vi + 1] = g;     arr[vi + 2] = b;
        arr[vi + 3] = r; arr[vi + 4] = g; arr[vi + 5] = b;
    }

    colorAttr.needsUpdate = true;
}

function _createRoadRibbon(points, width, material) {
    const positions = [];
    const half = width / 2;

    for (let i = 0; i < points.length; i++) {
        const p = points[i];
        let dir;
        if (i < points.length - 1) {
            dir = points[i + 1].clone().sub(p).normalize();
        } else {
            dir = p.clone().sub(points[i - 1]).normalize();
        }
        // Perpendicular in XZ plane
        const perp = new THREE.Vector3(-dir.z, 0, dir.x);
        positions.push(
            p.x + perp.x * half, p.y || 0.04, p.z + perp.z * half,
            p.x - perp.x * half, p.y || 0.04, p.z - perp.z * half,
        );
    }

    const indices = [];
    for (let i = 0; i < points.length - 1; i++) {
        const a = i * 2, b = a + 1, c = a + 2, d = a + 3;
        indices.push(a, b, c, b, d, c);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geo.setIndex(indices);
    geo.computeVertexNormals();

    return new THREE.Mesh(geo, material || _state.materials.road);
}

// ============================================================
// City features: trees, land use, barriers, water
// ============================================================

function _buildTrees() {
    const trees = _state.overlayData?.trees;
    if (!trees?.length) return;

    const group = new THREE.Group();
    group.name = 'trees';

    // Instanced meshes for performance
    const maxTrees = Math.min(trees.length, 2000);
    const trunkGeo = new THREE.CylinderGeometry(0.15, 0.2, 3.0, 5);
    const crownGeo = new THREE.SphereGeometry(1.0, 6, 5);
    const trunkMesh = new THREE.InstancedMesh(trunkGeo, _state.materials.treeTrunk, maxTrees);
    const crownMesh = new THREE.InstancedMesh(crownGeo, _state.materials.treeCrown, maxTrees);
    trunkMesh.castShadow = true;
    crownMesh.castShadow = true;

    const dummy = new THREE.Object3D();
    let count = 0;

    for (let i = 0; i < maxTrees; i++) {
        const tree = trees[i];
        const tp = gameToThree(tree.pos[0], tree.pos[1]);
        const h = tree.height || 6;
        const isNeedle = tree.leaf_type === 'needleleaved';
        const crownR = isNeedle ? h * 0.2 : h * 0.35;
        const trunkH = h * 0.45;

        // Trunk
        dummy.position.set(tp.x, trunkH / 2, tp.z);
        dummy.scale.set(1, trunkH / 3, 1);
        dummy.updateMatrix();
        trunkMesh.setMatrixAt(count, dummy.matrix);

        // Crown
        dummy.position.set(tp.x, trunkH + crownR * 0.6, tp.z);
        dummy.scale.set(crownR, crownR * (isNeedle ? 1.5 : 1.0), crownR);
        dummy.updateMatrix();
        crownMesh.setMatrixAt(count, dummy.matrix);

        count++;
    }

    trunkMesh.count = count;
    crownMesh.count = count;
    trunkMesh.instanceMatrix.needsUpdate = true;
    crownMesh.instanceMatrix.needsUpdate = true;

    group.add(trunkMesh);
    group.add(crownMesh);
    _state.scene.add(group);
    _state.treeGroup = group;
    console.log(`[MAP3D] Trees: ${count} instanced`);
}

function _buildLanduse() {
    const landuse = _state.overlayData?.landuse;
    if (!landuse?.length) return;

    const group = new THREE.Group();
    group.name = 'landuse';

    const parkTypes = new Set(['park', 'garden', 'grass', 'meadow', 'recreation_ground', 'forest']);

    for (const lu of landuse) {
        const poly = lu.polygon;
        if (!poly || poly.length < 3) continue;

        const isPark = parkTypes.has(lu.type);
        if (!isPark) continue;  // Only render parks/green for now

        const shape = new THREE.Shape();
        for (let i = 0; i < poly.length; i++) {
            const [gx, gy] = poly[i];
            if (i === 0) shape.moveTo(gx, gy);
            else shape.lineTo(gx, gy);
        }
        shape.closePath();

        const geo = new THREE.ShapeGeometry(shape);
        const mesh = new THREE.Mesh(geo, _state.materials.parkGround);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.y = 0.02;
        group.add(mesh);
    }

    _state.scene.add(group);
    _state.landuseGroup = group;
    console.log(`[MAP3D] Land use: ${landuse.length} zones`);
}

function _buildWater() {
    const water = _state.overlayData?.water;
    if (!water?.length) return;

    const group = new THREE.Group();
    group.name = 'water';

    for (const w of water) {
        const poly = w.polygon;
        if (!poly || poly.length < 3) continue;

        const shape = new THREE.Shape();
        for (let i = 0; i < poly.length; i++) {
            const [gx, gy] = poly[i];
            if (i === 0) shape.moveTo(gx, gy);
            else shape.lineTo(gx, gy);
        }
        shape.closePath();

        const geo = new THREE.ShapeGeometry(shape);
        const mesh = new THREE.Mesh(geo, _state.materials.waterSurface);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.y = 0.03;
        group.add(mesh);

        // Water edge outline
        const edgePts = poly.map(([gx, gy]) => {
            const tp = gameToThree(gx, gy);
            return new THREE.Vector3(tp.x, 0.04, tp.z);
        });
        if (edgePts.length > 0) edgePts.push(edgePts[0].clone());
        group.add(new THREE.Line(
            new THREE.BufferGeometry().setFromPoints(edgePts), _state.materials.waterEdge));
    }

    _state.scene.add(group);
    _state.waterGroup = group;
    console.log(`[MAP3D] Water: ${water.length} bodies`);
}

function _buildBarriers() {
    const barriers = _state.overlayData?.barriers;
    if (!barriers?.length) return;

    const group = new THREE.Group();
    group.name = 'barriers';

    for (const bar of barriers) {
        const pts = bar.points;
        if (!pts || pts.length < 2) continue;
        const h = bar.height || 1.5;
        const thick = 0.15;

        for (let i = 0; i < pts.length - 1; i++) {
            const [ax, ay] = pts[i];
            const [bx, by] = pts[i + 1];
            const len = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
            if (len < 0.1) continue;

            const cx = (ax + bx) / 2, cy = (ay + by) / 2;
            const angle = Math.atan2(bx - ax, by - ay);
            const tp = gameToThree(cx, cy);

            const geo = new THREE.BoxGeometry(thick, h, len);
            const mesh = new THREE.Mesh(geo, _state.materials.barrier);
            mesh.position.set(tp.x, h / 2, tp.z);
            mesh.rotation.y = angle;
            group.add(mesh);
        }
    }

    _state.scene.add(group);
    _state.barrierGroup = group;
    console.log(`[MAP3D] Barriers: ${barriers.length} segments`);
}

function _buildEntrances() {
    const entrances = _state.overlayData?.entrances;
    if (!entrances?.length) return;

    const group = new THREE.Group();
    group.name = 'entrances';

    // Instanced small door indicators
    const maxEntrances = Math.min(entrances.length, 500);
    const doorGeo = new THREE.BoxGeometry(0.8, 2.0, 0.15);
    const doorMesh = new THREE.InstancedMesh(doorGeo, _state.materials.entrance, maxEntrances);
    doorMesh.count = maxEntrances;

    const dummy = new THREE.Object3D();
    for (let i = 0; i < maxEntrances; i++) {
        const e = entrances[i];
        const tp = gameToThree(e.pos[0], e.pos[1]);
        dummy.position.set(tp.x, 1.0, tp.z);
        dummy.updateMatrix();
        doorMesh.setMatrixAt(i, dummy.matrix);
    }
    doorMesh.instanceMatrix.needsUpdate = true;
    group.add(doorMesh);

    _state.scene.add(group);
    _state.entranceGroup = group;
    console.log(`[MAP3D] Entrances: ${maxEntrances} door indicators`);
}

function _buildPOIs() {
    const pois = _state.overlayData?.pois;
    if (!pois?.length) return;

    const group = new THREE.Group();
    group.name = 'pois';

    // Instanced small marker diamonds
    const maxPois = Math.min(pois.length, 300);
    const poiGeo = new THREE.OctahedronGeometry(0.4, 0);
    const poiMesh = new THREE.InstancedMesh(poiGeo, _state.materials.poi, maxPois);
    poiMesh.count = maxPois;

    const dummy = new THREE.Object3D();
    for (let i = 0; i < maxPois; i++) {
        const p = pois[i];
        const tp = gameToThree(p.pos[0], p.pos[1]);
        dummy.position.set(tp.x, 1.5, tp.z);
        dummy.scale.set(1, 1.5, 1);
        dummy.updateMatrix();
        poiMesh.setMatrixAt(i, dummy.matrix);
    }
    poiMesh.instanceMatrix.needsUpdate = true;
    group.add(poiMesh);

    _state.scene.add(group);
    _state.poiGroup = group;
    console.log(`[MAP3D] POIs: ${maxPois} markers`);
}

function _buildFurniture() {
    const furniture = _state.overlayData?.furniture;
    if (!furniture?.length) return;

    const group = new THREE.Group();
    group.name = 'furniture';

    // Sort items by type
    const byType = { bench: [], hydrant: [], lamp: [], bin: [] };
    for (const f of furniture) {
        if (byType[f.type]) byType[f.type].push(f);
    }

    const dummy = new THREE.Object3D();

    // Benches — brown boxes
    if (byType.bench.length > 0) {
        const geo = new THREE.BoxGeometry(1.5, 0.5, 0.5);
        const mat = new THREE.MeshStandardMaterial({ color: 0x8B4513, roughness: 0.8 });
        const mesh = new THREE.InstancedMesh(geo, mat, byType.bench.length);
        mesh.count = byType.bench.length;
        mesh.castShadow = true;
        mesh.frustumCulled = false;
        for (let i = 0; i < byType.bench.length; i++) {
            const tp = gameToThree(byType.bench[i].pos[0], byType.bench[i].pos[1]);
            dummy.position.set(tp.x, 0.25, tp.z);
            dummy.scale.set(1, 1, 1);
            dummy.rotation.set(0, 0, 0);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
        }
        mesh.instanceMatrix.needsUpdate = true;
        group.add(mesh);
    }

    // Hydrants — red cylinders
    if (byType.hydrant.length > 0) {
        const geo = new THREE.CylinderGeometry(0.15, 0.15, 0.6, 6);
        const mat = new THREE.MeshStandardMaterial({ color: 0xff0000, roughness: 0.5 });
        const mesh = new THREE.InstancedMesh(geo, mat, byType.hydrant.length);
        mesh.count = byType.hydrant.length;
        mesh.castShadow = true;
        mesh.frustumCulled = false;
        for (let i = 0; i < byType.hydrant.length; i++) {
            const tp = gameToThree(byType.hydrant[i].pos[0], byType.hydrant[i].pos[1]);
            dummy.position.set(tp.x, 0.3, tp.z);
            dummy.scale.set(1, 1, 1);
            dummy.rotation.set(0, 0, 0);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
        }
        mesh.instanceMatrix.needsUpdate = true;
        group.add(mesh);
    }

    // Lamps — dark gray poles with sphere on top
    if (byType.lamp.length > 0) {
        const poleGeo = new THREE.CylinderGeometry(0.08, 0.08, 4, 6);
        const poleMat = new THREE.MeshStandardMaterial({ color: 0x444444, roughness: 0.6 });
        const poleMesh = new THREE.InstancedMesh(poleGeo, poleMat, byType.lamp.length);
        poleMesh.count = byType.lamp.length;
        poleMesh.castShadow = true;
        poleMesh.frustumCulled = false;

        const bulbGeo = new THREE.SphereGeometry(0.2, 6, 4);
        const bulbMat = new THREE.MeshBasicMaterial({ color: 0xffffcc });
        const bulbMesh = new THREE.InstancedMesh(bulbGeo, bulbMat, byType.lamp.length);
        bulbMesh.count = byType.lamp.length;
        bulbMesh.frustumCulled = false;

        for (let i = 0; i < byType.lamp.length; i++) {
            const tp = gameToThree(byType.lamp[i].pos[0], byType.lamp[i].pos[1]);
            // Pole
            dummy.position.set(tp.x, 2, tp.z);
            dummy.scale.set(1, 1, 1);
            dummy.rotation.set(0, 0, 0);
            dummy.updateMatrix();
            poleMesh.setMatrixAt(i, dummy.matrix);
            // Bulb on top
            dummy.position.set(tp.x, 4.1, tp.z);
            dummy.updateMatrix();
            bulbMesh.setMatrixAt(i, dummy.matrix);
        }
        poleMesh.instanceMatrix.needsUpdate = true;
        bulbMesh.instanceMatrix.needsUpdate = true;
        group.add(poleMesh);
        group.add(bulbMesh);
    }

    // Bins — dark green cylinders
    if (byType.bin.length > 0) {
        const geo = new THREE.CylinderGeometry(0.2, 0.2, 0.8, 6);
        const mat = new THREE.MeshStandardMaterial({ color: 0x006400, roughness: 0.7 });
        const mesh = new THREE.InstancedMesh(geo, mat, byType.bin.length);
        mesh.count = byType.bin.length;
        mesh.castShadow = true;
        mesh.frustumCulled = false;
        for (let i = 0; i < byType.bin.length; i++) {
            const tp = gameToThree(byType.bin[i].pos[0], byType.bin[i].pos[1]);
            dummy.position.set(tp.x, 0.4, tp.z);
            dummy.scale.set(1, 1, 1);
            dummy.rotation.set(0, 0, 0);
            dummy.updateMatrix();
            mesh.setMatrixAt(i, dummy.matrix);
        }
        mesh.instanceMatrix.needsUpdate = true;
        group.add(mesh);
    }

    _state.scene.add(group);
    _state.furnitureGroup = group;
    const total = furniture.length;
    console.log(`[MAP3D] Furniture: ${total} items (${byType.bench.length} benches, ${byType.hydrant.length} hydrants, ${byType.lamp.length} lamps, ${byType.bin.length} bins)`);
}


// ============================================================
// Exported API
// ============================================================

/**
 * Toggle satellite imagery on/off.
 */
export function toggleSatellite() {
    _state.showSatellite = !_state.showSatellite;
    console.log(`[MAP3D] Satellite imagery ${_state.showSatellite ? 'ON' : 'OFF'}`);

    if (_state.groundMesh) {
        if (_state.showSatellite && _state.satTexture) {
            _state.groundMesh.material.map = _state.satTexture;
            _state.groundMesh.material.color.setHex(0xffffff);
        } else {
            _state.groundMesh.material.map = null;
            _state.groundMesh.material.color.setHex(BG_COLOR);
        }
        _state.groundMesh.material.needsUpdate = true;
    }

    if (_state.showSatellite && _state.geoCenter && !_state.satTexture) {
        _loadSatelliteTiles(_state.geoCenter.lat, _state.geoCenter.lng);
    }
}

/**
 * Center camera on hostile units centroid.
 */
export function centerOnAction() {
    let sumX = 0, sumY = 0, count = 0;
    TritiumStore.units.forEach(u => {
        if (u.alliance === 'hostile') {
            const pos = u.position || {};
            sumX += (pos.x || 0);
            sumY += (pos.y || 0);
            count++;
        }
    });
    if (count > 0) {
        _state.cam.targetX = sumX / count;
        _state.cam.targetY = sumY / count;
        _state.cam.targetZoom = Math.max(10, _state.cam.zoom * 0.7);
    } else {
        _state.cam.targetX = 0;
        _state.cam.targetY = 0;
    }
    console.log(`[MAP3D] Center on action: (${_state.cam.targetX.toFixed(1)}, ${_state.cam.targetY.toFixed(1)})`);
}

/**
 * Reset camera to origin with default zoom.
 */
export function resetCamera() {
    _state.cam.targetX = 0;
    _state.cam.targetY = 0;
    _state.cam.targetZoom = ZOOM_DEFAULT;
    console.log('[MAP3D] Camera reset');
}

/**
 * Zoom in by factor 1.5.
 */
export function zoomIn() {
    _state.cam.targetZoom = Math.max(ZOOM_MIN, _state.cam.targetZoom / 1.5);
}

/**
 * Zoom out by factor 1.5.
 */
export function zoomOut() {
    _state.cam.targetZoom = Math.min(ZOOM_MAX, _state.cam.targetZoom * 1.5);
}

/**
 * Toggle road overlay on/off.
 */
export function toggleRoads() {
    _state.showRoads = !_state.showRoads;
    console.log(`[MAP3D] Road overlay ${_state.showRoads ? 'ON' : 'OFF'}`);
    if (_state.roadGroup) {
        _state.roadGroup.visible = _state.showRoads;
    }
}

/**
 * Toggle building visibility.
 */
export function toggleBuildings() {
    if (_state.buildingGroup) {
        _state.buildingGroup.visible = !_state.buildingGroup.visible;
        console.log(`[MAP3D] Buildings ${_state.buildingGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle tree visibility.
 */
export function toggleTrees() {
    if (_state.treeGroup) {
        _state.treeGroup.visible = !_state.treeGroup.visible;
        console.log(`[MAP3D] Trees ${_state.treeGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle water visibility.
 */
export function toggleWater() {
    if (_state.waterGroup) {
        _state.waterGroup.visible = !_state.waterGroup.visible;
        console.log(`[MAP3D] Water ${_state.waterGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle barrier visibility.
 */
export function toggleBarriers() {
    if (_state.barrierGroup) {
        _state.barrierGroup.visible = !_state.barrierGroup.visible;
        console.log(`[MAP3D] Barriers ${_state.barrierGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle entrance visibility.
 */
export function toggleEntrances() {
    if (_state.entranceGroup) {
        _state.entranceGroup.visible = !_state.entranceGroup.visible;
        console.log(`[MAP3D] Entrances ${_state.entranceGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle POI visibility.
 */
export function togglePOIs() {
    if (_state.poiGroup) {
        _state.poiGroup.visible = !_state.poiGroup.visible;
        console.log(`[MAP3D] POIs ${_state.poiGroup.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle terrain mesh visibility.
 */
export function toggleTerrain() {
    if (_state.terrainMesh) {
        _state.terrainMesh.visible = !_state.terrainMesh.visible;
        console.log(`[MAP3D] Terrain ${_state.terrainMesh.visible ? 'ON' : 'OFF'}`);
    }
}

/**
 * Toggle city simulation on/off. If not loaded, loads city data first.
 */
export async function toggleCitySim() {
    if (_state.citySim?.running) {
        _state.citySim.clearVehicles();
        _state.citySim.anomalyDetector?.reset();
        console.log('[MAP3D] City sim stopped');
        EventBus.emit('city-sim:stopped');
        return;
    }

    // Load city data if not already loaded
    if (!_state.citySim?.loaded) {
        if (!_state.geoCenter) {
            console.warn('[MAP3D] No geo reference — cannot start city sim');
            return;
        }
        console.log('[MAP3D] Loading city data for simulation...');
        const ok = await _state.citySim.loadCityData(
            _state.geoCenter.lat, _state.geoCenter.lng, 400
        );
        if (!ok) {
            console.warn('[MAP3D] Failed to load city data for sim');
            return;
        }
    }

    const stats = _state.citySim.roadNetwork?.stats();
    if (stats?.edges > 0) {
        _state.citySim.initRendering(THREE, _state.scene);
        _state.citySim.spawnVehicles(Math.min(100, stats.edges * 2));
        _state.citySim.spawnPedestrians(Math.min(50, stats.edges));
        console.log(`[MAP3D] City sim started`);
        EventBus.emit('city-sim:started');
    }
}

/**
 * Get city simulation stats.
 */
export function getCitySimStats() {
    return _state.citySim?.getStats() || null;
}

/**
 * Cycle through simulation time scales: 1x → 10x → 60x → 300x → pause → 1x.
 */
export function cycleSimTimeScale() {
    if (!_state.citySim) return;
    const scales = [1, 10, 60, 300, 0];  // 0 = pause
    const current = _state.citySim.timeScale;
    const idx = scales.indexOf(current);
    const next = scales[(idx + 1) % scales.length];
    _state.citySim.timeScale = next;
    console.log(`[MAP3D] Sim time scale: ${next === 0 ? 'PAUSED' : next + 'x'}`);
}

/**
 * Set simulation time scale directly.
 * @param {number} scale — 0=pause, 1=realtime, 60=1min/sec, etc.
 */
export function setSimTimeScale(scale) {
    if (!_state.citySim) return;
    _state.citySim.timeScale = scale;
}

/**
 * Toggle road graph debug overlay (intersection nodes + edges).
 */
export function toggleRoadGraph() {
    if (_state.roadGraphGroup) {
        _state.roadGraphGroup.visible = !_state.roadGraphGroup.visible;
        console.log(`[MAP3D] Road graph ${_state.roadGraphGroup.visible ? 'ON' : 'OFF'}`);
        return;
    }

    // Build debug overlay on first toggle
    if (_state.citySim?.loaded) {
        const group = _state.citySim.buildDebugOverlay(THREE, gameToThree);
        if (group) {
            _state.scene.add(group);
            _state.roadGraphGroup = group;
            console.log('[MAP3D] Road graph debug overlay created');
        }
    }
}

/**
 * Toggle grid overlay on/off.
 */
export function toggleGrid() {
    _state.showGrid = !_state.showGrid;
    console.log(`[MAP3D] Grid ${_state.showGrid ? 'ON' : 'OFF'}`);
    if (_state.gridHelper) _state.gridHelper.visible = _state.showGrid;
}

/**
 * Toggle fog of war density.
 */
export function toggleBloom() {
    _state.bloomEnabled = !_state.bloomEnabled;
    console.log(`%c[MAP3D] Bloom ${_state.bloomEnabled ? 'ON' : 'OFF'}`, 'color: #00f0ff;');
    return _state.bloomEnabled;
}

export function toggleFog() {
    if (_state.scene) {
        if (_state.scene.fog && _state.scene.fog.density > 0) {
            _state.scene.fog.density = 0;
        } else {
            _state.scene.fog = new THREE.FogExp2(BG_COLOR, 0.0008);
        }
    }
}

/**
 * Toggle camera between tilted RTS view and top-down orthographic.
 */
export function toggleTilt() {
    if (!_state.cam) return;
    if (_state.cam.tiltTarget === undefined) {
        _state.cam.tiltTarget = CAM_TILT_ANGLE;
        _state.cam.tiltAngle = CAM_TILT_ANGLE;
    }
    // Toggle between tilted (50) and top-down (89)
    _state.cam.tiltTarget = _state.cam.tiltTarget > 70 ? CAM_TILT_ANGLE : 89;
    console.log(`[MAP3D] Camera tilt: ${_state.cam.tiltTarget === 89 ? 'TOP-DOWN' : 'TILTED'}`);
}

/**
 * Return current map state for menu checkmarks.
 */
export function getMapState() {
    return {
        showSatellite: _state.showSatellite,
        showRoads: !!_state.showRoads,
        showGrid: _state.showGrid !== false,
        showBuildings: _state.buildingGroup ? _state.buildingGroup.visible : false,
        showTrees: _state.treeGroup ? _state.treeGroup.visible : false,
        showWater: _state.waterGroup ? _state.waterGroup.visible : false,
        showBarriers: _state.barrierGroup ? _state.barrierGroup.visible : false,
        showEntrances: _state.entranceGroup ? _state.entranceGroup.visible : false,
        showPOIs: _state.poiGroup ? _state.poiGroup.visible : false,
        showTerrain: _state.terrainMesh ? _state.terrainMesh.visible : false,
        showRoadGraph: _state.roadGraphGroup ? _state.roadGraphGroup.visible : false,
        showCitySim: _state.citySim?.running || false,
        showUnits: _state.showUnits !== false,
        tiltMode: _state.cam.tiltTarget > 70 ? 'top-down' : 'tilted',
    };
}

/**
 * Set specific layer visibility (deterministic, not toggle).
 * @param {Object} layers - { satellite, buildings, roads, grid, units }
 */
export function setLayers(layers) {
    if (layers.satellite !== undefined) {
        const want = !!layers.satellite;
        if (_state.showSatellite !== want) toggleSatellite();
    }
    if (layers.buildings !== undefined) {
        const want = !!layers.buildings;
        const current = _state.buildingGroup ? _state.buildingGroup.visible : false;
        if (current !== want) toggleBuildings();
    }
    if (layers.roads !== undefined) {
        const want = !!layers.roads;
        if (!!_state.showRoads !== want) toggleRoads();
    }
    if (layers.grid !== undefined) {
        const want = !!layers.grid;
        if ((_state.showGrid !== false) !== want) toggleGrid();
    }
    if (layers.units !== undefined) {
        // Show/hide all unit meshes
        _state.showUnits = !!layers.units;
        for (const group of Object.values(_state.unitMeshes)) {
            group.visible = _state.showUnits;
        }
    }
    console.log('[MAP3D] Layers set:', JSON.stringify(getMapState()));
    return getMapState();
}
