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
import { EventBus } from './events.js';

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
    showSatellite: true,
    showRoads: false,
    showGrid: true,
    satTileLevel: -1,
    satReloadTimer: null,
    noLocationSet: false,

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
    _state.layerHud.textContent = `${tilt} z${zoom} | ${layers.join(' + ') || 'ALL OFF'}`;
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
    _state.materials.zoneRestricted = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.08,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.zonePerimeter = new THREE.MeshBasicMaterial({
        color: 0x00f0ff, transparent: true, opacity: 0.04,
        side: THREE.DoubleSide, depthWrite: false,
    });
    _state.materials.zoneBorderRestricted = new THREE.LineBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.35,
    });
    _state.materials.zoneBorderPerimeter = new THREE.LineDashedMaterial({
        color: 0x00f0ff, transparent: true, opacity: 0.18,
        dashSize: 0.5, gapSize: 0.3,
    });

    // Effect ring
    _state.materials.effectRing = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.6,
        side: THREE.DoubleSide, depthWrite: false,
    });

    // Building wall material — semi-transparent dark blue with edge glow
    _state.materials.building = new THREE.MeshBasicMaterial({
        color: 0x0a0a2e,
        transparent: true,
        opacity: 0.55,
        fog: false,
        side: THREE.DoubleSide,
    });
    // Building roof material — slightly lighter, more visible from above
    _state.materials.buildingRoof = new THREE.MeshBasicMaterial({
        color: 0x0d1030,
        transparent: true,
        opacity: 0.7,
        fog: false,
    });
    // Building outline material — bright cyan edges for cyberpunk look
    _state.materials.buildingEdge = new THREE.LineBasicMaterial({
        color: 0x00f0ff,
        transparent: true,
        opacity: 0.6,
    });

    // Road surface material
    _state.materials.road = new THREE.MeshBasicMaterial({
        color: 0x3a3a4a,
        transparent: true,
        opacity: 0.5,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
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
        group.position.y = assetType.includes('drone') ? 3 : 0;

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

        // Filled disc
        const discGeo = new THREE.CircleGeometry(radius, 48);
        const discMat = isRestricted
            ? _state.materials.zoneRestricted
            : _state.materials.zonePerimeter;
        const disc = new THREE.Mesh(discGeo, discMat);
        disc.rotation.x = -Math.PI / 2;
        const tp = gameToThree(wx, wy);
        disc.position.set(tp.x, 0.02, tp.z);
        _state.scene.add(disc);
        _state.zoneMeshes.push(disc);

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

    // Render
    if (_state.renderer && _state.scene && _state.camera) {
        _state.renderer.render(_state.scene, _state.camera);
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
                body: JSON.stringify({ action: 'dispatch', target_id: unitId, x: worldX, y: worldY }),
            }).catch(() => {});
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
    try {
        const resp = await fetch('/api/geo/overlay');
        if (resp.ok) {
            _state.overlayData = await resp.json();
        }
    } catch (e) {
        console.warn('[MAP3D] Overlay fetch failed:', e.message);
    }

    // Always try Microsoft Building Footprints for visual overlay
    // (satellite-derived, much better alignment than OSM data)
    if (_state.geoCenter) {
        const { lat, lng } = _state.geoCenter;
        // Use same coordinate conversion as satellite tiles for consistency
        const R = 6378137;  // WGS84 equatorial radius (matches satellite tile conversion)
        const latRad = lat * Math.PI / 180;
        const cosFactor = Math.cos(latRad);
        const convertToLocal = (rawBuildings) => rawBuildings.map(b => ({
            polygon: b.polygon.map(([plat, plng]) => [
                (plng - lng) * Math.PI / 180 * R * cosFactor,
                (plat - lat) * Math.PI / 180 * R,
            ]),
            height: b.tags?.height ? parseFloat(b.tags.height) || 8 : 8,
        }));

        // Try Microsoft satellite-derived footprints first
        try {
            const resp = await fetch(`/api/geo/msft-buildings?lat=${lat}&lng=${lng}&radius=500`);
            if (resp.ok) {
                const rawBuildings = await resp.json();
                if (rawBuildings.length > 0) {
                    _state.overlayData = _state.overlayData || {};
                    _state.overlayData.buildings = convertToLocal(rawBuildings);
                    console.log(`[MAP3D] Fetched ${rawBuildings.length} Microsoft buildings (satellite-aligned)`);
                }
            }
        } catch (e) {
            console.warn('[MAP3D] Microsoft buildings fetch failed:', e.message);
        }

        // Fallback to OSM Overpass if Microsoft didn't return results
        if (!_state.overlayData?.buildings?.length) {
            try {
                const resp = await fetch(`/api/geo/buildings?lat=${lat}&lng=${lng}&radius=500`);
                if (resp.ok) {
                    const rawBuildings = await resp.json();
                    _state.overlayData = _state.overlayData || {};
                    _state.overlayData.buildings = convertToLocal(rawBuildings);
                    console.log(`[MAP3D] Fetched ${rawBuildings.length} buildings from OSM (fallback)`);
                }
            } catch (e) {
                console.warn('[MAP3D] OSM buildings fallback failed:', e.message);
            }
        }
    }

    _buildBuildings();
    _buildRoads();
}

function _buildBuildings() {
    const buildings = _state.overlayData?.buildings;
    if (!buildings?.length) return;

    const group = new THREE.Group();
    group.name = 'buildings';

    for (const bldg of buildings) {
        const poly = bldg.polygon;
        if (!poly || poly.length < 3) continue;

        // Building height: use tag data if available, else default 8m
        const height = bldg.height || 8;

        // Create 2D shape from polygon (game coordinates)
        const shape = new THREE.Shape();
        for (let i = 0; i < poly.length; i++) {
            const [gx, gy] = poly[i];
            if (i === 0) shape.moveTo(gx, gy);
            else shape.lineTo(gx, gy);
        }
        shape.closePath();

        // Extrude into 3D building
        const extrudeSettings = {
            depth: height,
            bevelEnabled: false,
        };
        const extGeo = new THREE.ExtrudeGeometry(shape, extrudeSettings);

        // ExtrudeGeometry creates shape in XY, extrudes along Z.
        // We need: shape in XZ (ground), extrude along Y (up).
        // Rotate -90deg around X to put XY→XZ, then Z extrusion becomes Y.
        const wallMesh = new THREE.Mesh(extGeo, _state.materials.building);
        wallMesh.rotation.x = -Math.PI / 2;
        wallMesh.position.y = 0;
        group.add(wallMesh);

        // Roof cap (flat on top) — use ShapeGeometry for clean top
        const roofGeo = new THREE.ShapeGeometry(shape);
        const roofMesh = new THREE.Mesh(roofGeo, _state.materials.buildingRoof);
        roofMesh.rotation.x = -Math.PI / 2;
        roofMesh.position.y = height;
        group.add(roofMesh);

        // Cyan edge outlines at ground level and roofline
        const outlineGround = [];
        const outlineRoof = [];
        for (const [gx, gy] of poly) {
            const tp = gameToThree(gx, gy);
            outlineGround.push(new THREE.Vector3(tp.x, 0.15, tp.z));
            outlineRoof.push(new THREE.Vector3(tp.x, height, tp.z));
        }
        if (outlineGround.length > 0) {
            outlineGround.push(outlineGround[0].clone());
            outlineRoof.push(outlineRoof[0].clone());
        }

        // Ground outline
        const groundLineGeo = new THREE.BufferGeometry().setFromPoints(outlineGround);
        group.add(new THREE.Line(groundLineGeo, _state.materials.buildingEdge));

        // Roofline outline
        const roofLineGeo = new THREE.BufferGeometry().setFromPoints(outlineRoof);
        group.add(new THREE.Line(roofLineGeo, _state.materials.buildingEdge));

        // Vertical corner edges (every 3rd vertex to avoid clutter)
        for (let i = 0; i < outlineGround.length - 1; i += 3) {
            const verts = [outlineGround[i].clone(), outlineRoof[i].clone()];
            const vertGeo = new THREE.BufferGeometry().setFromPoints(verts);
            group.add(new THREE.Line(vertGeo, _state.materials.buildingEdge));
        }
    }

    _state.scene.add(group);
    _state.buildingGroup = group;
    console.log(`[MAP3D] Buildings: ${buildings.length} extruded 3D meshes`);
}

function _buildRoads() {
    const roads = _state.overlayData?.roads;
    if (!roads?.length) return;

    const group = new THREE.Group();
    group.name = 'roads';

    for (const road of roads) {
        const isPrimary = ['primary', 'secondary', 'trunk', 'motorway', 'tertiary'].includes(road.class);
        const width = isPrimary ? 3.0 : 1.5;

        const points = (road.points || []).map(([gx, gy]) => {
            const tp = gameToThree(gx, gy);
            return new THREE.Vector3(tp.x, 0.05, tp.z);
        });

        if (points.length < 2) continue;

        // Thin line (always visible even at distance)
        const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
        const lineMat = new THREE.LineBasicMaterial({
            color: isPrimary ? 0x445566 : 0x334455,
            transparent: true,
            opacity: isPrimary ? 0.6 : 0.4,
        });
        group.add(new THREE.Line(lineGeo, lineMat));

        // Flat ribbon mesh for wider primary roads
        if (isPrimary && points.length >= 2) {
            const ribbon = _createRoadRibbon(points, width);
            if (ribbon) group.add(ribbon);
        }
    }

    _state.scene.add(group);
    _state.roadGroup = group;
    _state.roadGroup.visible = _state.showRoads;
    console.log(`[MAP3D] Roads: ${roads.length} segments`);
}

function _createRoadRibbon(points, width) {
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
            p.x + perp.x * half, 0.04, p.z + perp.z * half,
            p.x - perp.x * half, 0.04, p.z - perp.z * half,
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

    return new THREE.Mesh(geo, _state.materials.road);
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
