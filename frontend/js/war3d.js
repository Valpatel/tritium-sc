/**
 * TRITIUM-SC War Room 3D Renderer
 * Three.js tactical view replacing Canvas 2D rendering in war.js
 *
 * The HTML HUD, game logic, selection state, dispatch, audio, keyboard,
 * and WebSocket handlers all remain in war.js.  This module owns ONLY
 * the 3D scene that fills the war-canvas container.
 *
 * Data flow:
 *   war.js reads assetState.simTargets (from assets.js / WebSocket)
 *   war.js calls updateWar3D() each frame
 *   war3d.js renders the Three.js scene
 *
 * Exports:
 *   initWar3D(container)  - create scene, camera, renderer
 *   updateWar3D()         - called from war.js render loop
 *   destroyWar3D()        - tear down renderer
 *   war3dSelectAt(sx, sy) - raycast pick at screen coords
 *   war3dDispatchTo(sx,sy)- world coords from screen for dispatch
 */

// ---------------------------------------------------------------------------
// Module state
// ---------------------------------------------------------------------------

const war3d = {
    scene: null,
    camera: null,
    renderer: null,
    container: null,
    clock: null,

    // Camera state (lerped)
    camState: { x: 0, y: 0, zoom: 15, tilt: false },

    // Object pools
    unitMeshes: {},        // target_id -> THREE.Group
    zoneMeshes: [],        // zone ring meshes
    dispatchArrowMeshes: [],
    effectMeshes: [],
    selectionRings: {},    // target_id -> THREE.Mesh

    // Reusable objects
    raycaster: null,
    mouseVec: null,
    groundPlane: null,
    gridHelper: null,
    mapBorder: null,
    minimap: null,          // rendered via drawMinimap in war.js (HTML overlay)

    // Materials (shared / reused)
    materials: {},

    // Lighting
    ambientLight: null,
    dirLight: null,

    // Animation data
    initialized: false,
    prevTargetPositions: {},  // for lerp

    // Ground texture
    groundMesh: null,
    satelliteTexture: null,
};

// Alliance colors (hex for Three.js)
const W3D_COLORS = {
    friendly: 0x05ffa1,
    hostile:  0xff2a6d,
    neutral:  0x00a0ff,
    unknown:  0xfcee0a,
    cyan:     0x00f0ff,
    magenta:  0xff2a6d,
    grid:     0x00f0ff,
    ground:   0x0a0a12,
    building: 0x1a1a2e,
};

// ---------------------------------------------------------------------------
// Init / Destroy
// ---------------------------------------------------------------------------

function initWar3D(container) {
    if (war3d.initialized) return;
    if (!container) return;

    war3d.container = container;
    war3d.clock = new THREE.Clock();

    // Scene
    war3d.scene = new THREE.Scene();
    war3d.scene.background = new THREE.Color(W3D_COLORS.ground);
    war3d.scene.fog = new THREE.Fog(W3D_COLORS.ground, 80, 120);

    // Orthographic camera (top-down tactical)
    const aspect = container.clientWidth / container.clientHeight;
    const frustum = 15;
    war3d.camera = new THREE.OrthographicCamera(
        -frustum * aspect, frustum * aspect,
        frustum, -frustum,
        0.1, 200
    );
    _setCameraTopDown();

    // Renderer — render into the existing war-canvas element or create one
    let canvas = container.querySelector('canvas');
    war3d.renderer = new THREE.WebGLRenderer({
        canvas: canvas || undefined,
        antialias: true,
        alpha: false,
    });
    war3d.renderer.setSize(container.clientWidth, container.clientHeight);
    war3d.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    war3d.renderer.shadowMap.enabled = true;
    war3d.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    if (!canvas) {
        war3d.renderer.domElement.id = 'war-3d-canvas';
        war3d.renderer.domElement.style.cssText = 'width:100%;height:100%;display:block;';
        container.prepend(war3d.renderer.domElement);
    }

    // Raycaster
    war3d.raycaster = new THREE.Raycaster();
    war3d.mouseVec = new THREE.Vector2();

    // Lighting
    war3d.ambientLight = new THREE.AmbientLight(0xffffff, 0.35);
    war3d.scene.add(war3d.ambientLight);

    war3d.dirLight = new THREE.DirectionalLight(0xffffff, 0.65);
    war3d.dirLight.position.set(20, 40, 15);
    war3d.dirLight.castShadow = true;
    war3d.dirLight.shadow.mapSize.width = 1024;
    war3d.dirLight.shadow.mapSize.height = 1024;
    war3d.dirLight.shadow.camera.near = 1;
    war3d.dirLight.shadow.camera.far = 100;
    war3d.dirLight.shadow.camera.left = -40;
    war3d.dirLight.shadow.camera.right = 40;
    war3d.dirLight.shadow.camera.top = 40;
    war3d.dirLight.shadow.camera.bottom = -40;
    war3d.scene.add(war3d.dirLight);

    // Build static scene elements
    _buildGround();
    _buildGrid();
    _buildMapBorder();
    _initMaterials();

    war3d.initialized = true;

    console.log('%c[WAR3D] Three.js tactical renderer initialized', 'color: #00f0ff;');
}

function destroyWar3D() {
    if (!war3d.initialized) return;

    // Dispose geometries and materials
    war3d.scene.traverse(obj => {
        if (obj.geometry) obj.geometry.dispose();
        if (obj.material) {
            if (Array.isArray(obj.material)) {
                obj.material.forEach(m => m.dispose());
            } else {
                obj.material.dispose();
            }
        }
    });

    if (war3d.renderer) {
        war3d.renderer.dispose();
    }

    war3d.scene = null;
    war3d.camera = null;
    war3d.renderer = null;
    war3d.unitMeshes = {};
    war3d.zoneMeshes = [];
    war3d.dispatchArrowMeshes = [];
    war3d.effectMeshes = [];
    war3d.selectionRings = {};
    war3d.materials = {};
    war3d.initialized = false;

    console.log('%c[WAR3D] Renderer destroyed', 'color: #ff2a6d;');
}

// ---------------------------------------------------------------------------
// Camera helpers
// ---------------------------------------------------------------------------

function _setCameraTopDown() {
    const cam = war3d.camera;
    // Top-down: camera looks straight down from Y+
    cam.position.set(0, 60, 0);
    cam.lookAt(0, 0, 0);
    cam.up.set(0, 0, -1); // so that +X is right, +Z is down in screen
}

function _setCameraTilted() {
    const cam = war3d.camera;
    // Slight tilt (~20 degrees from vertical)
    cam.position.set(0, 55, 18);
    cam.lookAt(0, 0, 0);
    cam.up.set(0, 1, 0);
}

function _updateCamera() {
    if (!war3d.camera || typeof warState === 'undefined') return;

    const ws = warState.cam;
    const cam = war3d.camera;
    const s = war3d.camState;

    // Lerp towards warState camera target
    s.x += (ws.targetX - s.x) * 0.1;
    s.y += (ws.targetY - s.y) * 0.1;

    // Map warState zoom (pixels-per-unit in 2D) to ortho frustum half-size
    // warState zoom 1.0 ~= frustum 15 (show +-15 world units vertically)
    // Higher zoom -> smaller frustum -> closer view
    const targetFrustum = 15 / ws.targetZoom;
    s.zoom += (targetFrustum - s.zoom) * 0.1;

    const aspect = war3d.container
        ? war3d.container.clientWidth / Math.max(1, war3d.container.clientHeight)
        : 1;

    cam.left   = -s.zoom * aspect;
    cam.right  =  s.zoom * aspect;
    cam.top    =  s.zoom;
    cam.bottom = -s.zoom;
    cam.updateProjectionMatrix();

    // Position camera above the warState camera center
    // warState uses (x, y) as ground plane; Three.js: x = x, z = -y (y up)
    if (s.tilt) {
        cam.position.set(s.x, 55, -s.y + 18);
        cam.lookAt(s.x, 0, -s.y);
    } else {
        cam.position.set(s.x, 60, -s.y);
        cam.lookAt(s.x, 0, -s.y);
        cam.up.set(0, 0, -1);
    }
}

// ---------------------------------------------------------------------------
// Static scene: ground, grid, border
// ---------------------------------------------------------------------------

function _buildGround() {
    const size = 70; // slightly larger than map bounds
    const geo = new THREE.PlaneGeometry(size, size);
    const mat = new THREE.MeshStandardMaterial({
        color: W3D_COLORS.ground,
        roughness: 0.95,
        metalness: 0.0,
    });
    war3d.groundMesh = new THREE.Mesh(geo, mat);
    war3d.groundMesh.rotation.x = -Math.PI / 2;
    war3d.groundMesh.position.y = -0.01;
    war3d.groundMesh.receiveShadow = true;
    war3d.scene.add(war3d.groundMesh);
}

function _buildGrid() {
    // Subtle grid matching warState map range
    const range = 60; // -30 to 30
    const divisions = 12; // 5-unit spacing
    const grid = new THREE.GridHelper(range, divisions, W3D_COLORS.grid, W3D_COLORS.grid);
    grid.material.opacity = 0.06;
    grid.material.transparent = true;
    grid.material.depthWrite = false;
    war3d.gridHelper = grid;
    war3d.scene.add(grid);
}

function _buildMapBorder() {
    const min = -30, max = 30;
    const pts = [
        new THREE.Vector3(min, 0.02, -max),
        new THREE.Vector3(max, 0.02, -max),
        new THREE.Vector3(max, 0.02, -min),
        new THREE.Vector3(min, 0.02, -min),
        new THREE.Vector3(min, 0.02, -max),
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const mat = new THREE.LineBasicMaterial({
        color: W3D_COLORS.cyan,
        opacity: 0.15,
        transparent: true,
    });
    war3d.mapBorder = new THREE.Line(geo, mat);
    war3d.scene.add(war3d.mapBorder);
}

// ---------------------------------------------------------------------------
// Shared materials
// ---------------------------------------------------------------------------

function _initMaterials() {
    // Per-alliance unit materials
    for (const [alliance, color] of Object.entries(W3D_COLORS)) {
        if (['cyan', 'magenta', 'grid', 'ground', 'building'].includes(alliance)) continue;
        war3d.materials[alliance] = new THREE.MeshStandardMaterial({
            color: color,
            roughness: 0.4,
            metalness: 0.3,
            emissive: color,
            emissiveIntensity: 0.15,
        });
    }

    // Selection ring material
    war3d.materials.selection = new THREE.MeshBasicMaterial({
        color: W3D_COLORS.cyan,
        transparent: true,
        opacity: 0.5,
        side: THREE.DoubleSide,
        depthWrite: false,
    });

    // Dispatch arrow material
    war3d.materials.dispatch = new THREE.MeshBasicMaterial({
        color: W3D_COLORS.magenta,
        transparent: true,
        opacity: 0.8,
    });

    // Zone materials
    war3d.materials.zoneRestricted = new THREE.MeshBasicMaterial({
        color: 0xff2a6d,
        transparent: true,
        opacity: 0.08,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
    war3d.materials.zonePerimeter = new THREE.MeshBasicMaterial({
        color: 0x00f0ff,
        transparent: true,
        opacity: 0.04,
        side: THREE.DoubleSide,
        depthWrite: false,
    });
    war3d.materials.zoneBorderRestricted = new THREE.LineBasicMaterial({
        color: 0xff2a6d,
        transparent: true,
        opacity: 0.35,
    });
    war3d.materials.zoneBorderPerimeter = new THREE.LineDashedMaterial({
        color: 0x00f0ff,
        transparent: true,
        opacity: 0.18,
        dashSize: 0.5,
        gapSize: 0.3,
    });

    // Neutralized overlay
    war3d.materials.neutralized = new THREE.MeshBasicMaterial({
        color: 0xff2a6d,
        transparent: true,
        opacity: 0.35,
    });

    // Ghost placement
    war3d.materials.ghost = new THREE.MeshBasicMaterial({
        color: 0xfcee0a,
        transparent: true,
        opacity: 0.4,
    });

    // Waypoint line
    war3d.materials.waypoint = new THREE.LineDashedMaterial({
        color: 0x05ffa1,
        transparent: true,
        opacity: 0.2,
        dashSize: 0.3,
        gapSize: 0.4,
    });

    // Effect ring
    war3d.materials.effectRing = new THREE.MeshBasicMaterial({
        color: 0xff2a6d,
        transparent: true,
        opacity: 0.6,
        side: THREE.DoubleSide,
        depthWrite: false,
    });

    // Threat ring materials
    war3d.materials.threat_unknown = new THREE.MeshBasicMaterial({
        color: 0xfcee0a, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
    });
    war3d.materials.threat_suspicious = new THREE.MeshBasicMaterial({
        color: 0xff9800, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
    });
    war3d.materials.threat_hostile = new THREE.MeshBasicMaterial({
        color: 0xff2a6d, transparent: true, opacity: 0.4,
        side: THREE.DoubleSide, depthWrite: false,
    });
}

// ---------------------------------------------------------------------------
// Unit mesh creation — uses models.js (TritiumModels) when available,
// falls back to simple shapes
// ---------------------------------------------------------------------------

function _createUnitMesh(tid, target) {
    const alliance = (target.alliance || 'unknown').toLowerCase();
    const assetType = (target.asset_type || '').toLowerCase();

    const group = new THREE.Group();
    group.userData.targetId = tid;
    group.userData.alliance = alliance;

    // Use models.js procedural models if available
    if (typeof TritiumModels !== 'undefined' && TritiumModels.getModelForType) {
        const model = TritiumModels.getModelForType(assetType || alliance, alliance);
        if (model) {
            group.add(model);
            model.userData.isBody = true;

            // Name label from models.js
            const colorMap = { friendly: '#05ffa1', hostile: '#ff2a6d', neutral: '#00a0ff', unknown: '#fcee0a' };
            if (TritiumModels.createNameLabel) {
                const label = TritiumModels.createNameLabel(target.name || tid, colorMap[alliance] || '#ffffff');
                label.userData.isLabel = true;
                group.add(label);
            }

            // Battery bar from models.js
            if (alliance === 'friendly' && TritiumModels.createBatteryBar) {
                const bar = TritiumModels.createBatteryBar(target.battery || 1.0);
                bar.userData.isBattery = true;
                group.add(bar);
            }

            return group;
        }
    }

    // Fallback: simple shapes
    const mat = war3d.materials[alliance] || war3d.materials.unknown;
    let bodyMesh;

    if (alliance === 'friendly') {
        if (assetType.includes('drone')) {
            const geo = new THREE.CylinderGeometry(0.5, 0.5, 0.12, 8);
            bodyMesh = new THREE.Mesh(geo, mat);
            bodyMesh.position.y = 3;
            const rotorGeo = new THREE.SphereGeometry(0.1, 6, 4);
            for (let i = 0; i < 4; i++) {
                const angle = (i / 4) * Math.PI * 2;
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
        } else {
            const geo = new THREE.CylinderGeometry(0.35, 0.45, 0.3, 8);
            bodyMesh = new THREE.Mesh(geo, mat);
            bodyMesh.position.y = 0.15;
            const domeGeo = new THREE.SphereGeometry(0.15, 8, 4, 0, Math.PI * 2, 0, Math.PI / 2);
            const dome = new THREE.Mesh(domeGeo, mat);
            dome.position.y = 0.3;
            group.add(dome);
        }
    } else if (alliance === 'hostile') {
        if (assetType.includes('vehicle')) {
            const geo = new THREE.BoxGeometry(0.8, 0.4, 0.5);
            bodyMesh = new THREE.Mesh(geo, mat);
            bodyMesh.position.y = 0.2;
        } else {
            const geo = new THREE.CylinderGeometry(0.2, 0.2, 0.6, 8);
            bodyMesh = new THREE.Mesh(geo, mat);
            bodyMesh.position.y = 0.3;
            const headGeo = new THREE.SphereGeometry(0.2, 8, 6);
            const head = new THREE.Mesh(headGeo, mat);
            head.position.y = 0.7;
            group.add(head);
        }
    } else if (alliance === 'neutral') {
        const neutralMat = mat.clone();
        neutralMat.transparent = true;
        neutralMat.opacity = 0.6;
        const geo = new THREE.CylinderGeometry(0.18, 0.18, 0.5, 8);
        bodyMesh = new THREE.Mesh(geo, neutralMat);
        bodyMesh.position.y = 0.25;
        const headGeo = new THREE.SphereGeometry(0.18, 8, 6);
        const head = new THREE.Mesh(headGeo, neutralMat);
        head.position.y = 0.6;
        group.add(head);
    } else {
        const geo = new THREE.SphereGeometry(0.3, 8, 6);
        bodyMesh = new THREE.Mesh(geo, mat);
        bodyMesh.position.y = 0.3;
    }

    if (bodyMesh) {
        bodyMesh.castShadow = true;
        group.add(bodyMesh);
    }

    // Shadow circle on ground
    const shadowGeo = new THREE.CircleGeometry(0.4, 16);
    const shadowMat = new THREE.MeshBasicMaterial({
        color: 0x000000, transparent: true, opacity: 0.25, depthWrite: false,
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.01;
    group.add(shadow);

    // Name label sprite (fallback)
    const label = _createTextSprite(target.name || tid, alliance);
    label.position.y = alliance === 'friendly' && assetType.includes('drone') ? 4.0 : 1.2;
    label.userData.isLabel = true;
    group.add(label);

    // Battery bar for friendlies (fallback)
    if (alliance === 'friendly') {
        const barGroup = new THREE.Group();
        barGroup.userData.isBattery = true;
        const bgGeo = new THREE.PlaneGeometry(0.8, 0.06);
        const bgMat = new THREE.MeshBasicMaterial({
            color: 0xffffff, transparent: true, opacity: 0.15, side: THREE.DoubleSide, depthWrite: false,
        });
        barGroup.add(new THREE.Mesh(bgGeo, bgMat));
        const fgGeo = new THREE.PlaneGeometry(0.8, 0.06);
        const fgMat = new THREE.MeshBasicMaterial({
            color: 0x05ffa1, side: THREE.DoubleSide, depthWrite: false,
        });
        const fg = new THREE.Mesh(fgGeo, fgMat);
        fg.userData.isBatteryFill = true;
        barGroup.add(fg);
        barGroup.position.y = assetType.includes('drone') ? 3.5 : 0.8;
        barGroup.rotation.x = -Math.PI / 2;
        group.add(barGroup);
    }

    return group;
}

function _createTextSprite(text, alliance) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 256;
    canvas.height = 64;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = 'bold 28px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    ctx.strokeStyle = 'rgba(0,0,0,0.8)';
    ctx.lineWidth = 4;
    ctx.strokeText(text.substring(0, 16), 128, 32);

    const colorMap = {
        friendly: '#05ffa1',
        hostile: '#ff2a6d',
        neutral: '#00a0ff',
        unknown: '#fcee0a',
    };
    ctx.fillStyle = colorMap[alliance] || '#ffffff';
    ctx.fillText(text.substring(0, 16), 128, 32);

    const tex = new THREE.CanvasTexture(canvas);
    tex.minFilter = THREE.LinearFilter;

    const spriteMat = new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        depthWrite: false,
        sizeAttenuation: false,
    });
    const sprite = new THREE.Sprite(spriteMat);
    sprite.scale.set(0.08, 0.02, 1);
    return sprite;
}

// ---------------------------------------------------------------------------
// Heading arrow (direction indicator attached to unit group)
// ---------------------------------------------------------------------------

function _updateHeading(group, heading) {
    // Remove old heading arrow
    const old = group.getObjectByName('headingArrow');
    if (old) group.remove(old);

    if (heading === undefined || heading === null) return;

    // heading: compass bearing (0=north=+Z in our coord system)
    // Convert to radians: Three.js Y rotation, 0=+Z, CW
    const rad = -heading * Math.PI / 180;

    const pts = [
        new THREE.Vector3(0, 0.1, 0),
        new THREE.Vector3(0, 0.1, -1.0),
    ];
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const alliance = group.userData.alliance || 'unknown';
    const color = W3D_COLORS[alliance] || W3D_COLORS.unknown;
    const mat = new THREE.LineBasicMaterial({ color: color, linewidth: 2 });
    const line = new THREE.Line(geo, mat);
    line.name = 'headingArrow';
    line.rotation.y = rad;
    group.add(line);
}

// ---------------------------------------------------------------------------
// Zone rendering
// ---------------------------------------------------------------------------

function _updateZones() {
    if (typeof warState === 'undefined') return;

    // Remove old zone meshes
    for (const m of war3d.zoneMeshes) {
        war3d.scene.remove(m);
        if (m.geometry) m.geometry.dispose();
    }
    war3d.zoneMeshes = [];

    for (const zone of warState.zones) {
        const pos = zone.position || {};
        const wx = pos.x || 0;
        const wy = pos.z !== undefined ? pos.z : (pos.y || 0);
        const radius = (zone.properties && zone.properties.radius) || 10;
        const isRestricted = (zone.type || '').includes('restricted');

        // Filled disc
        const discGeo = new THREE.CircleGeometry(radius, 48);
        const discMat = isRestricted ? war3d.materials.zoneRestricted : war3d.materials.zonePerimeter;
        const disc = new THREE.Mesh(discGeo, discMat);
        disc.rotation.x = -Math.PI / 2;
        disc.position.set(wx, 0.02, -wy);
        war3d.scene.add(disc);
        war3d.zoneMeshes.push(disc);

        // Border ring
        const ringPts = [];
        const segments = 64;
        for (let i = 0; i <= segments; i++) {
            const angle = (i / segments) * Math.PI * 2;
            ringPts.push(new THREE.Vector3(
                Math.cos(angle) * radius,
                0,
                Math.sin(angle) * radius
            ));
        }
        const ringGeo = new THREE.BufferGeometry().setFromPoints(ringPts);
        const ringMat = isRestricted
            ? war3d.materials.zoneBorderRestricted
            : war3d.materials.zoneBorderPerimeter;
        const ring = new THREE.Line(ringGeo, ringMat);
        ring.position.set(wx, 0.03, -wy);
        if (!isRestricted) ring.computeLineDistances();
        war3d.scene.add(ring);
        war3d.zoneMeshes.push(ring);

        // Zone label sprite
        const name = zone.name || zone.type || '';
        if (name) {
            const label = _createZoneLabel(name.toUpperCase(), isRestricted);
            label.position.set(wx, 0.5, -wy + radius + 1);
            war3d.scene.add(label);
            war3d.zoneMeshes.push(label);
        }
    }
}

function _createZoneLabel(text, isRestricted) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    canvas.width = 256;
    canvas.height = 48;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.font = '20px "JetBrains Mono", monospace';
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

// ---------------------------------------------------------------------------
// Dispatch arrows
// ---------------------------------------------------------------------------

function _updateDispatchArrows() {
    if (typeof warState === 'undefined') return;
    const now = Date.now();

    // Remove expired arrow meshes
    war3d.dispatchArrowMeshes = war3d.dispatchArrowMeshes.filter(m => {
        if (now - m.userData.time >= 3000) {
            war3d.scene.remove(m);
            if (m.geometry) m.geometry.dispose();
            return false;
        }
        return true;
    });

    // Create meshes for new arrows that don't have a mesh yet
    for (const arrow of warState.dispatchArrows) {
        const existing = war3d.dispatchArrowMeshes.find(m => m.userData.arrowRef === arrow);
        if (existing) {
            // Update opacity
            const alpha = Math.max(0, 1 - (now - arrow.time) / 3000);
            existing.material.opacity = alpha * 0.8;
            continue;
        }

        // Create line from -> to
        const from = new THREE.Vector3(arrow.fromX, 0.15, -arrow.fromY);
        const to = new THREE.Vector3(arrow.toX, 0.15, -arrow.toY);

        const pts = [from, to];
        const geo = new THREE.BufferGeometry().setFromPoints(pts);
        const mat = new THREE.LineDashedMaterial({
            color: W3D_COLORS.magenta,
            transparent: true,
            opacity: 0.8,
            dashSize: 0.5,
            gapSize: 0.3,
        });
        const line = new THREE.Line(geo, mat);
        line.computeLineDistances();
        line.userData.arrowRef = arrow;
        line.userData.time = arrow.time;

        war3d.scene.add(line);
        war3d.dispatchArrowMeshes.push(line);

        // Arrowhead (small cone at destination)
        const dir = to.clone().sub(from).normalize();
        const coneGeo = new THREE.ConeGeometry(0.25, 0.6, 6);
        const coneMat = new THREE.MeshBasicMaterial({
            color: W3D_COLORS.magenta,
            transparent: true,
            opacity: 0.8,
        });
        const cone = new THREE.Mesh(coneGeo, coneMat);
        cone.position.copy(to);
        // Orient cone to point in direction of arrow
        const axis = new THREE.Vector3(0, 1, 0);
        const quaternion = new THREE.Quaternion().setFromUnitVectors(axis, dir);
        cone.quaternion.copy(quaternion);
        cone.userData.arrowRef = arrow;
        cone.userData.time = arrow.time;

        war3d.scene.add(cone);
        war3d.dispatchArrowMeshes.push(cone);
    }
}

// ---------------------------------------------------------------------------
// Selection rings
// ---------------------------------------------------------------------------

function _updateSelectionRings() {
    if (typeof warState === 'undefined') return;

    // Remove rings that are no longer selected
    for (const [tid, ring] of Object.entries(war3d.selectionRings)) {
        if (!warState.selectedTargets.includes(tid)) {
            war3d.scene.remove(ring);
            if (ring.geometry) ring.geometry.dispose();
            delete war3d.selectionRings[tid];
        }
    }

    // Add rings for newly selected
    for (const tid of warState.selectedTargets) {
        if (war3d.selectionRings[tid]) continue;

        const ringGeo = new THREE.RingGeometry(0.55, 0.7, 32);
        const ring = new THREE.Mesh(ringGeo, war3d.materials.selection);
        ring.rotation.x = -Math.PI / 2;
        ring.position.y = 0.04;
        ring.userData.selectionFor = tid;

        war3d.scene.add(ring);
        war3d.selectionRings[tid] = ring;
    }

    // Position rings on their targets
    const targets = typeof getTargets === 'function' ? getTargets() : {};
    for (const [tid, ring] of Object.entries(war3d.selectionRings)) {
        const t = targets[tid];
        if (!t) continue;
        const pos = typeof getTargetPosition === 'function' ? getTargetPosition(t) : { x: t.x, y: t.y };
        if (pos.x !== undefined) {
            ring.position.x = pos.x;
            ring.position.z = -pos.y;
        }
    }

    // Pulse animation
    const pulse = 0.5 + Math.sin(Date.now() * 0.005) * 0.15;
    for (const ring of Object.values(war3d.selectionRings)) {
        ring.material.opacity = pulse;
    }
}

// ---------------------------------------------------------------------------
// Threat rings
// ---------------------------------------------------------------------------

function _updateThreatRings(group, tid) {
    // Remove existing threat ring
    const old = group.getObjectByName('threatRing');
    if (old) {
        group.remove(old);
        if (old.geometry) old.geometry.dispose();
    }

    if (typeof warState === 'undefined') return;
    const threat = warState.threats[tid];
    if (!threat || !threat.threat_level || threat.threat_level === 'none') return;

    const mat = war3d.materials['threat_' + threat.threat_level] || war3d.materials.threat_unknown;
    const ringGeo = new THREE.RingGeometry(0.6, 0.75, 24);
    const ring = new THREE.Mesh(ringGeo, mat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.05;
    ring.name = 'threatRing';

    // Animated rotation
    const rotSpeed = Date.now() * 0.002;
    ring.rotation.z = rotSpeed;

    group.add(ring);
}

// ---------------------------------------------------------------------------
// Waypoint paths
// ---------------------------------------------------------------------------

function _updateWaypoints(group, target) {
    // Remove old waypoint line
    const old = group.getObjectByName('waypointPath');
    if (old) {
        group.remove(old);
        if (old.geometry) old.geometry.dispose();
    }

    if (!target.waypoints || target.waypoints.length < 2) return;

    const pts = target.waypoints.map(wp =>
        new THREE.Vector3(wp.x, 0.08, -wp.y)
    );
    // Close the loop for patrol routes
    pts.push(pts[0].clone());

    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    const line = new THREE.Line(geo, war3d.materials.waypoint);
    line.computeLineDistances();
    line.name = 'waypointPath';

    // Waypoint lines are in world space, not relative to unit
    // So we add to scene, but track it on the group for cleanup
    war3d.scene.add(line);
    group.userData.waypointLine = line;
}

// ---------------------------------------------------------------------------
// Visual effects (neutralized ring, zone pulse)
// ---------------------------------------------------------------------------

function _updateEffects() {
    if (typeof warState === 'undefined') return;
    const now = Date.now();

    // Remove expired effect meshes
    war3d.effectMeshes = war3d.effectMeshes.filter(m => {
        if (now - m.userData.startTime >= 2000) {
            war3d.scene.remove(m);
            if (m.geometry) m.geometry.dispose();
            return false;
        }
        return true;
    });

    // Create/update effects from warState
    for (const effect of warState.effects) {
        const existing = war3d.effectMeshes.find(m => m.userData.effectRef === effect);
        if (existing) {
            // Animate existing
            const age = (now - effect.time) / 1000;
            if (effect.type === 'neutralized') {
                const scale = 1 + age * 6;
                existing.scale.set(scale, scale, scale);
                existing.material.opacity = Math.max(0, 0.6 * (1 - age / 1.5));
            } else if (effect.type === 'zone_pulse') {
                existing.material.opacity = Math.max(0, 0.4 * (1 - age / 1.5));
                const pulseScale = 1 + age * 1.5;
                existing.scale.set(pulseScale, 1, pulseScale);
            }
            continue;
        }

        // New effect
        if (effect.type === 'neutralized') {
            const geo = new THREE.RingGeometry(0.3, 0.5, 24);
            const mat = war3d.materials.effectRing.clone();
            const ring = new THREE.Mesh(geo, mat);
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(effect.x, 0.1, -effect.y);
            ring.userData.effectRef = effect;
            ring.userData.startTime = effect.time;
            war3d.scene.add(ring);
            war3d.effectMeshes.push(ring);
        } else if (effect.type === 'zone_pulse') {
            const radius = (effect.data && effect.data.radius) || 10;
            const geo = new THREE.RingGeometry(radius - 0.3, radius + 0.3, 48);
            const mat = war3d.materials.effectRing.clone();
            mat.opacity = 0.4;
            const ring = new THREE.Mesh(geo, mat);
            ring.rotation.x = -Math.PI / 2;
            ring.position.set(effect.x, 0.1, -effect.y);
            ring.userData.effectRef = effect;
            ring.userData.startTime = effect.time;
            war3d.scene.add(ring);
            war3d.effectMeshes.push(ring);
        }
    }
}

// ---------------------------------------------------------------------------
// Placing ghost (setup mode)
// ---------------------------------------------------------------------------

function _updatePlacingGhost() {
    // Remove old ghost
    const old = war3d.scene.getObjectByName('placingGhost');
    if (old) {
        war3d.scene.remove(old);
        if (old.geometry) old.geometry.dispose();
    }

    if (typeof warState === 'undefined' || !warState.placingAsset) return;

    // Convert canvas-local mouse coords to world position via raycasting
    const wp = _canvasToWorld(warState.lastMouse.x, warState.lastMouse.y);
    if (!wp) return;

    const geo = new THREE.SphereGeometry(0.5, 8, 6);
    const ghost = new THREE.Mesh(geo, war3d.materials.ghost);
    ghost.position.set(wp.x, 0.5, -wp.y);
    ghost.name = 'placingGhost';
    war3d.scene.add(ghost);
}

/**
 * Convert canvas-local (sx, sy) to warState world coords via ground raycast.
 */
function _canvasToWorld(sx, sy) {
    if (!war3d.renderer || !war3d.camera) return null;
    const canvas = war3d.renderer.domElement;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (w === 0 || h === 0) return null;

    war3d.mouseVec.x = (sx / w) * 2 - 1;
    war3d.mouseVec.y = -(sy / h) * 2 + 1;

    war3d.raycaster.setFromCamera(war3d.mouseVec, war3d.camera);
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const intersection = new THREE.Vector3();
    war3d.raycaster.ray.intersectPlane(groundPlane, intersection);
    if (intersection) {
        return { x: intersection.x, y: -intersection.z };
    }
    return null;
}

// ---------------------------------------------------------------------------
// Box select visualization
// ---------------------------------------------------------------------------

// Box select is drawn as an HTML overlay by war.js (screen-space rectangle).
// No 3D equivalent needed.

// ---------------------------------------------------------------------------
// Main update (called from war.js render loop)
// ---------------------------------------------------------------------------

function updateWar3D() {
    if (!war3d.initialized || !war3d.renderer || !war3d.scene || !war3d.camera) return;
    if (typeof warState === 'undefined') return;

    const dt = war3d.clock.getDelta();

    // Update camera
    _updateCamera();

    // Resize check
    _handleResize();

    // Update targets (units)
    _updateUnits();

    // Update zones (rebuild occasionally)
    _updateZonesThrottled();

    // Update selection rings
    _updateSelectionRings();

    // Update dispatch arrows
    _updateDispatchArrows();

    // Update effects
    _updateEffects();

    // Update placing ghost
    _updatePlacingGhost();

    // Render
    war3d.renderer.render(war3d.scene, war3d.camera);
}

// Throttle zone updates (they don't change every frame)
let _lastZoneUpdate = 0;
function _updateZonesThrottled() {
    const now = Date.now();
    if (now - _lastZoneUpdate > 2000) {
        _updateZones();
        _lastZoneUpdate = now;
    }
}

// ---------------------------------------------------------------------------
// Unit update (sync meshes with warState targets)
// ---------------------------------------------------------------------------

function _updateUnits() {
    const targets = typeof getTargets === 'function' ? getTargets() : {};

    // Remove meshes for targets that no longer exist
    for (const tid of Object.keys(war3d.unitMeshes)) {
        if (!targets[tid]) {
            const group = war3d.unitMeshes[tid];
            // Clean up waypoint line (in scene, not in group)
            if (group.userData.waypointLine) {
                war3d.scene.remove(group.userData.waypointLine);
                group.userData.waypointLine.geometry.dispose();
            }
            war3d.scene.remove(group);
            group.traverse(c => {
                if (c.geometry) c.geometry.dispose();
            });
            delete war3d.unitMeshes[tid];
        }
    }

    // Create or update meshes for current targets
    for (const [tid, target] of Object.entries(targets)) {
        let group = war3d.unitMeshes[tid];

        if (!group) {
            // Create new unit mesh
            group = _createUnitMesh(tid, target);
            war3d.scene.add(group);
            war3d.unitMeshes[tid] = group;
        }

        // Get position (with lerp for smooth movement)
        const pos = typeof getTargetPosition === 'function'
            ? getTargetPosition(target)
            : { x: target.x, y: target.y };

        if (pos.x === undefined || pos.y === undefined) continue;

        // Smooth lerp
        const prev = war3d.prevTargetPositions[tid] || { x: pos.x, z: -pos.y };
        const lerpFactor = 0.15;
        const nx = prev.x + (pos.x - prev.x) * lerpFactor;
        const nz = prev.z + (-pos.y - prev.z) * lerpFactor;
        war3d.prevTargetPositions[tid] = { x: nx, z: nz };

        group.position.x = nx;
        group.position.z = nz;

        // Heading
        _updateHeading(group, target.heading);

        // Animate model (rotor spin, etc.) via models.js
        if (typeof TritiumModels !== 'undefined' && TritiumModels.animateModel) {
            const elapsed = war3d.clock.elapsedTime;
            const dt = war3d.clock.getDelta ? 0.016 : 0.016; // ~60fps
            group.traverse(child => {
                if (child.userData && child.userData.isBody) {
                    TritiumModels.animateModel(child, 0.016, elapsed, {
                        speed: target.speed || 0,
                        battery: target.battery || 1,
                        heading: target.heading || 0,
                    });
                }
            });
        }

        // Waypoints
        // Clean up old waypoint line before creating new one
        if (group.userData.waypointLine) {
            war3d.scene.remove(group.userData.waypointLine);
            group.userData.waypointLine.geometry.dispose();
            group.userData.waypointLine = null;
        }
        _updateWaypoints(group, target);

        // Threat ring
        _updateThreatRings(group, tid);

        // Battery bar update
        if (target.battery !== undefined) {
            group.traverse(child => {
                if (child.userData && child.userData.isBatteryFill) {
                    const level = Math.max(0, Math.min(1, target.battery));
                    child.scale.x = level;
                    child.position.x = -(1 - level) * 0.4 * 0.5; // shift left as it shrinks
                    // Color: green -> yellow -> red
                    const r = Math.round(255 * (1 - level));
                    const g = Math.round(255 * level);
                    child.material.color.setRGB(r / 255, g / 255, 0);
                }
            });
        }

        // Neutralized visual
        const isNeutralized = (target.status || '').toLowerCase() === 'neutralized';
        if (isNeutralized) {
            group.traverse(child => {
                if (child.material && !child.userData.isLabel) {
                    if (!child.userData._origOpacity) {
                        child.userData._origOpacity = child.material.opacity || 1;
                    }
                    child.material.transparent = true;
                    child.material.opacity = 0.25;
                }
            });
        }

        // Hovered state
        const isHovered = warState.hoveredTarget === tid;
        const isSelected = warState.selectedTargets.includes(tid);
        const baseScale = 1.0;
        const targetScale = isSelected ? 1.25 : (isHovered ? 1.12 : baseScale);
        const currentScale = group.scale.x;
        const newScale = currentScale + (targetScale - currentScale) * 0.2;
        group.scale.set(newScale, newScale, newScale);
    }
}

// ---------------------------------------------------------------------------
// Raycasting (selection)
// ---------------------------------------------------------------------------

function war3dSelectAt(screenX, screenY) {
    if (!war3d.initialized || !war3d.camera || !war3d.renderer) return null;

    const rect = war3d.renderer.domElement.getBoundingClientRect();
    war3d.mouseVec.x = ((screenX - rect.left) / rect.width) * 2 - 1;
    war3d.mouseVec.y = -((screenY - rect.top) / rect.height) * 2 + 1;

    war3d.raycaster.setFromCamera(war3d.mouseVec, war3d.camera);

    // Collect all unit meshes for intersection
    const meshes = [];
    for (const group of Object.values(war3d.unitMeshes)) {
        group.traverse(child => {
            if (child.isMesh && !child.userData.isLabel) {
                meshes.push(child);
            }
        });
    }

    const intersects = war3d.raycaster.intersectObjects(meshes, false);
    if (intersects.length > 0) {
        // Walk up to find the group with targetId
        let obj = intersects[0].object;
        while (obj && !obj.userData.targetId) {
            obj = obj.parent;
        }
        if (obj && obj.userData.targetId) {
            return obj.userData.targetId;
        }
    }
    return null;
}

/**
 * Convert screen coordinates to world position on the ground plane.
 * Used by war.js for dispatch (right-click).
 */
function war3dDispatchTo(screenX, screenY) {
    if (!war3d.initialized || !war3d.camera || !war3d.renderer) return null;

    const rect = war3d.renderer.domElement.getBoundingClientRect();
    war3d.mouseVec.x = ((screenX - rect.left) / rect.width) * 2 - 1;
    war3d.mouseVec.y = -((screenY - rect.top) / rect.height) * 2 + 1;

    war3d.raycaster.setFromCamera(war3d.mouseVec, war3d.camera);

    // Intersect with ground plane at y=0
    const groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0);
    const intersection = new THREE.Vector3();
    war3d.raycaster.ray.intersectPlane(groundPlane, intersection);

    if (intersection) {
        // Convert back to warState coords: x = x, y = -z
        return { x: intersection.x, y: -intersection.z };
    }
    return null;
}

// ---------------------------------------------------------------------------
// Resize handler
// ---------------------------------------------------------------------------

let _lastResizeCheck = 0;
function _handleResize() {
    const now = Date.now();
    if (now - _lastResizeCheck < 250) return; // throttle
    _lastResizeCheck = now;

    const container = war3d.container;
    if (!container || !war3d.renderer) return;

    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w === 0 || h === 0) return;

    const canvas = war3d.renderer.domElement;
    if (canvas.width !== w || canvas.height !== h) {
        war3d.renderer.setSize(w, h);
        // Camera is updated every frame in _updateCamera, so no need here
    }
}

// ---------------------------------------------------------------------------
// Satellite texture integration
// ---------------------------------------------------------------------------

/**
 * Set a satellite image as the ground texture.
 * Called by geo.js when tiles are loaded.
 * @param {HTMLCanvasElement|HTMLImageElement} source - composited satellite image
 */
function war3dSetGroundTexture(source) {
    if (!war3d.groundMesh) return;

    if (war3d.satelliteTexture) {
        war3d.satelliteTexture.dispose();
    }

    war3d.satelliteTexture = new THREE.CanvasTexture(source);
    war3d.satelliteTexture.minFilter = THREE.LinearFilter;
    war3d.satelliteTexture.magFilter = THREE.LinearFilter;

    war3d.groundMesh.material.map = war3d.satelliteTexture;
    war3d.groundMesh.material.color.set(0xffffff); // remove tint
    war3d.groundMesh.material.needsUpdate = true;
}

/**
 * Add building extrusions from polygon data.
 * Called by geo.js with building footprints.
 * @param {Array} buildings - [{polygon: [{x,y},...], height: number}]
 */
function war3dAddBuildings(buildings) {
    if (!war3d.scene) return;

    // Remove old buildings
    const oldBuildings = war3d.scene.getObjectByName('buildingGroup');
    if (oldBuildings) {
        war3d.scene.remove(oldBuildings);
        oldBuildings.traverse(c => {
            if (c.geometry) c.geometry.dispose();
        });
    }

    const buildingGroup = new THREE.Group();
    buildingGroup.name = 'buildingGroup';

    const bodyMat = new THREE.MeshStandardMaterial({
        color: W3D_COLORS.building,
        transparent: true,
        opacity: 0.7,
        roughness: 0.8,
        metalness: 0.1,
    });
    const edgeMat = new THREE.LineBasicMaterial({
        color: W3D_COLORS.cyan,
        transparent: true,
        opacity: 0.3,
    });

    for (const bld of buildings) {
        if (!bld.polygon || bld.polygon.length < 3) continue;
        const height = bld.height || 5;

        // Create Shape from polygon (in XZ plane)
        const shape = new THREE.Shape();
        shape.moveTo(bld.polygon[0].x, -bld.polygon[0].y);
        for (let i = 1; i < bld.polygon.length; i++) {
            shape.lineTo(bld.polygon[i].x, -bld.polygon[i].y);
        }
        shape.closePath();

        const extrudeSettings = { depth: height, bevelEnabled: false };
        const geo = new THREE.ExtrudeGeometry(shape, extrudeSettings);
        // Rotate so extrusion goes up (Y axis)
        geo.rotateX(-Math.PI / 2);

        const mesh = new THREE.Mesh(geo, bodyMat);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        buildingGroup.add(mesh);

        // Edge wireframe for cyberpunk glow
        const edges = new THREE.EdgesGeometry(geo);
        const edgeLine = new THREE.LineSegments(edges, edgeMat);
        buildingGroup.add(edgeLine);
    }

    war3d.scene.add(buildingGroup);
}

// ---------------------------------------------------------------------------
// Tilt toggle (V key handled in war.js, calls this)
// ---------------------------------------------------------------------------

function war3dToggleTilt() {
    war3d.camState.tilt = !war3d.camState.tilt;
    if (war3d.camState.tilt) {
        if (war3d.camera) {
            war3d.camera.up.set(0, 1, 0);
        }
    }
}

// ---------------------------------------------------------------------------
// Expose globally
// ---------------------------------------------------------------------------

window.initWar3D = initWar3D;
window.updateWar3D = updateWar3D;
window.destroyWar3D = destroyWar3D;
window.war3dSelectAt = war3dSelectAt;
window.war3dDispatchTo = war3dDispatchTo;
window.war3dSetGroundTexture = war3dSetGroundTexture;
window.war3dAddBuildings = war3dAddBuildings;
window.war3dToggleTilt = war3dToggleTilt;
window.war3d = war3d;
