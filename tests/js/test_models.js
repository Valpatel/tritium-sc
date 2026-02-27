/**
 * TRITIUM-SC 3D Unit Models (models.js) Tests
 * Tests all exported functions, classes, and constants from frontend/js/models.js
 * Run: node tests/js/test_models.js
 *
 * Uses a comprehensive Three.js mock layer so all model creation functions
 * can execute in Node.js without WebGL.
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}
function assertContains(str, sub, msg) {
    assert(typeof str === 'string' && str.includes(sub), msg);
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Three.js mock objects
// ============================================================

function mockVector3(x, y, z) {
    return {
        x: x || 0, y: y || 0, z: z || 0,
        set(nx, ny, nz) { this.x = nx; this.y = ny; this.z = nz; return this; },
        copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; },
    };
}

function mockEuler(x, y, z) {
    return {
        x: x || 0, y: y || 0, z: z || 0,
        set(nx, ny, nz) { this.x = nx; this.y = ny; this.z = nz; return this; },
        copy(v) { this.x = v.x; this.y = v.y; this.z = v.z; return this; },
    };
}

function mockScale(x, y, z) {
    return {
        x: x || 1, y: y || 1, z: z || 1,
        set(nx, ny, nz) { this.x = nx; this.y = ny; this.z = nz; return this; },
    };
}

function createMockMesh(geometry, material) {
    return {
        isMesh: true,
        geometry: geometry,
        material: material,
        position: mockVector3(),
        rotation: mockEuler(),
        scale: mockScale(),
        castShadow: false,
        userData: {},
    };
}

function createMockGroup() {
    const children = [];
    return {
        isGroup: true,
        children: children,
        position: mockVector3(),
        rotation: mockEuler(),
        scale: mockScale(),
        userData: {},
        add(child) { children.push(child); },
        parent: null,
    };
}

function createMockGeometry(type) {
    return { type: type, dispose() {} };
}

const THREE_MOCK = {
    DoubleSide: 2,
    LinearFilter: 1006,

    Group: function() {
        return createMockGroup();
    },

    Mesh: function(geometry, material) {
        return createMockMesh(geometry, material);
    },

    LineSegments: function(geometry, material) {
        return {
            isLineSegments: true,
            geometry: geometry,
            material: material,
            position: mockVector3(),
            rotation: mockEuler(),
            scale: mockScale(),
            userData: {},
        };
    },

    Sprite: function(material) {
        return {
            isSprite: true,
            material: material,
            position: mockVector3(),
            scale: mockScale(),
            userData: {},
        };
    },

    // Geometry constructors
    BoxGeometry: function(w, h, d) {
        return { type: 'BoxGeometry', parameters: { width: w, height: h, depth: d }, dispose() {} };
    },
    CylinderGeometry: function(rt, rb, h, rs) {
        return { type: 'CylinderGeometry', parameters: { radiusTop: rt, radiusBottom: rb, height: h, radialSegments: rs }, dispose() {} };
    },
    SphereGeometry: function(r, ws, hs, ps, pe, ts, te) {
        return { type: 'SphereGeometry', parameters: { radius: r }, dispose() {} };
    },
    OctahedronGeometry: function(r, d) {
        return { type: 'OctahedronGeometry', parameters: { radius: r, detail: d }, dispose() {} };
    },
    TorusGeometry: function(r, t, rs, ts, arc) {
        return { type: 'TorusGeometry', parameters: { radius: r, tube: t, arc: arc }, dispose() {} };
    },
    RingGeometry: function(ir, or, ts) {
        return { type: 'RingGeometry', parameters: { innerRadius: ir, outerRadius: or }, dispose() {} };
    },
    CircleGeometry: function(r, s) {
        return { type: 'CircleGeometry', parameters: { radius: r }, dispose() {} };
    },
    PlaneGeometry: function(w, h) {
        return { type: 'PlaneGeometry', parameters: { width: w, height: h }, dispose() {} };
    },
    ConeGeometry: function(r, h, rs, hs, openEnded) {
        return { type: 'ConeGeometry', parameters: { radius: r, height: h }, dispose() {} };
    },
    EdgesGeometry: function(geometry) {
        return { type: 'EdgesGeometry', sourceGeometry: geometry, dispose() {} };
    },

    // Material constructors
    MeshStandardMaterial: function(opts) {
        return { type: 'MeshStandardMaterial', ...opts, dispose() {} };
    },
    MeshBasicMaterial: function(opts) {
        return { type: 'MeshBasicMaterial', ...opts, dispose() {} };
    },
    LineBasicMaterial: function(opts) {
        return { type: 'LineBasicMaterial', ...opts, dispose() {} };
    },
    SpriteMaterial: function(opts) {
        return { type: 'SpriteMaterial', ...opts, dispose() {} };
    },

    // Texture
    CanvasTexture: function(canvas) {
        return { type: 'CanvasTexture', image: canvas, minFilter: null, dispose() {} };
    },
};

// ============================================================
// Mock canvas/document for createNameLabel
// ============================================================

const mockDocument = {
    createElement: function(tag) {
        if (tag === 'canvas') {
            return {
                tagName: 'canvas',
                width: 256,
                height: 64,
                getContext: function(type) {
                    return {
                        font: '',
                        textAlign: '',
                        textBaseline: '',
                        fillStyle: '',
                        strokeStyle: '',
                        lineWidth: 1,
                        globalAlpha: 1,
                        measureText: function(text) {
                            // Approximate: ~14px per char at font size 28
                            return { width: text.length * 14 };
                        },
                        beginPath() {},
                        moveTo() {},
                        lineTo() {},
                        quadraticCurveTo() {},
                        closePath() {},
                        fill() {},
                        stroke() {},
                        fillText() {},
                        strokeText() {},
                        clearRect() {},
                        fillRect() {},
                    };
                },
            };
        }
        return { tagName: tag, style: {} };
    },
};

// ============================================================
// Load models.js into VM context
// ============================================================

const srcPath = __dirname + '/../../frontend/js/models.js';
const source = fs.readFileSync(srcPath, 'utf8');

const ctx = vm.createContext({
    Math, console: { log() {}, error() {}, warn() {} },
    Array, Object, Number, String, Boolean, parseInt, parseFloat,
    THREE: THREE_MOCK,
    document: mockDocument,
    window: {},
});

vm.runInContext(source, ctx);
const M = ctx.window.TritiumModels;

// ============================================================
// SECTION 1: Exports exist
// ============================================================

console.log('\n--- Exports Exist ---');

assert(M !== undefined, 'window.TritiumModels is defined');
assert(typeof M.createRoverModel === 'function', 'createRoverModel exported');
assert(typeof M.createDroneModel === 'function', 'createDroneModel exported');
assert(typeof M.createTurretModel === 'function', 'createTurretModel exported');
assert(typeof M.createPersonModel === 'function', 'createPersonModel exported');
assert(typeof M.createVehicleModel === 'function', 'createVehicleModel exported');
assert(typeof M.createCameraModel === 'function', 'createCameraModel exported');
assert(typeof M.createSensorModel === 'function', 'createSensorModel exported');
assert(typeof M.createSelectionRing === 'function', 'createSelectionRing exported');
assert(typeof M.createBatteryBar === 'function', 'createBatteryBar exported');
assert(typeof M.createNameLabel === 'function', 'createNameLabel exported');
assert(typeof M.createThreatRing === 'function', 'createThreatRing exported');
assert(typeof M.getModelForType === 'function', 'getModelForType exported');
assert(typeof M.animateModel === 'function', 'animateModel exported');
assert(typeof M.animateSelectionRing === 'function', 'animateSelectionRing exported');
assert(typeof M.animateThreatRing === 'function', 'animateThreatRing exported');
assert(typeof M.MODEL_COLORS === 'object', 'MODEL_COLORS exported');

// ============================================================
// SECTION 2: MODEL_COLORS palette values
// ============================================================

console.log('\n--- MODEL_COLORS Palette ---');

const COLORS = M.MODEL_COLORS;
assertEqual(COLORS.friendly, 0x05ffa1, 'MODEL_COLORS.friendly = 0x05ffa1 (green)');
assertEqual(COLORS.friendlyAccent, 0x00f0ff, 'MODEL_COLORS.friendlyAccent = 0x00f0ff (cyan)');
assertEqual(COLORS.hostile, 0xff2a6d, 'MODEL_COLORS.hostile = 0xff2a6d (magenta)');
assertEqual(COLORS.hostileAccent, 0x660011, 'MODEL_COLORS.hostileAccent = 0x660011');
assertEqual(COLORS.neutral, 0x4488ff, 'MODEL_COLORS.neutral = 0x4488ff (blue)');
assertEqual(COLORS.neutralAccent, 0x2244aa, 'MODEL_COLORS.neutralAccent = 0x2244aa');
assertEqual(COLORS.unknown, 0xfcee0a, 'MODEL_COLORS.unknown = 0xfcee0a (yellow)');
assertEqual(COLORS.unknownAccent, 0x997700, 'MODEL_COLORS.unknownAccent = 0x997700');
assertEqual(COLORS.cyan, 0x00f0ff, 'MODEL_COLORS.cyan = 0x00f0ff');
assertEqual(COLORS.dark, 0x12121a, 'MODEL_COLORS.dark = 0x12121a');
assertEqual(COLORS.metal, 0x334455, 'MODEL_COLORS.metal = 0x334455');
assertEqual(COLORS.black, 0x111111, 'MODEL_COLORS.black = 0x111111');

// ============================================================
// SECTION 3: createRoverModel
// ============================================================

console.log('\n--- createRoverModel ---');

(function testRoverReturnGroup() {
    const g = M.createRoverModel('friendly');
    assert(g.isGroup, 'createRoverModel returns a Group');
})();

(function testRoverUserData() {
    const g = M.createRoverModel('friendly');
    assertEqual(g.userData.unitType, 'rover', 'Rover userData.unitType = "rover"');
})();

(function testRoverHasChildren() {
    const g = M.createRoverModel('friendly');
    assert(g.children.length > 0, 'Rover model has children (meshes)');
})();

(function testRoverHasWheels() {
    const g = M.createRoverModel('friendly');
    // 4 wheels + chassis + wedge + turret base + barrel + tip + antenna + ant tip + 2 neon strips + edges = many children
    assert(g.children.length >= 10, 'Rover model has 10+ children (chassis, wheels, turret, etc.)');
})();

(function testRoverFriendlyAlliance() {
    const g = M.createRoverModel('friendly');
    // Verify neon strip glow uses friendly base color
    const strips = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.friendly);
    assert(strips.length >= 2, 'Friendly rover has neon strips with friendly color');
})();

(function testRoverHostileAlliance() {
    const g = M.createRoverModel('hostile');
    assertEqual(g.userData.unitType, 'rover', 'Hostile rover still has unitType rover');
    const strips = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.hostile);
    assert(strips.length >= 2, 'Hostile rover has neon strips with hostile color');
})();

(function testRoverNullAlliance() {
    const g = M.createRoverModel(null);
    assertEqual(g.userData.unitType, 'rover', 'Rover with null alliance still returns valid model');
    // Should default to unknown palette
    const strips = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(strips.length >= 2, 'Null alliance rover uses unknown color');
})();

(function testRoverUndefinedAlliance() {
    const g = M.createRoverModel(undefined);
    assertEqual(g.userData.unitType, 'rover', 'Rover with undefined alliance still returns valid model');
})();

// ============================================================
// SECTION 4: createDroneModel
// ============================================================

console.log('\n--- createDroneModel ---');

(function testDroneReturnGroup() {
    const g = M.createDroneModel('friendly');
    assert(g.isGroup, 'createDroneModel returns a Group');
})();

(function testDroneUserData() {
    const g = M.createDroneModel('friendly');
    assertEqual(g.userData.unitType, 'drone', 'Drone userData.unitType = "drone"');
    assertEqual(g.userData.hoverY, 4.0, 'Drone userData.hoverY = 4.0');
})();

(function testDroneHasRotors() {
    const g = M.createDroneModel('friendly');
    const rotors = g.children.filter(c => c.userData && c.userData.isRotor);
    assertEqual(rotors.length, 4, 'Drone has 4 rotor meshes');
})();

(function testDroneHasChildren() {
    const g = M.createDroneModel('hostile');
    // body + bodyEdges + 4*(arm + rotor + hub + led) + gimbal + frontLed = 2 + 16 + 2 = 20
    assert(g.children.length >= 15, 'Drone model has 15+ children');
})();

(function testDroneNeutralOpacity() {
    const g = M.createDroneModel('neutral');
    // Neutral alliance has opacity 0.6
    const body = g.children.find(c => c.isMesh && c.material && c.material.type === 'MeshStandardMaterial' && c.material.opacity === 0.6);
    assert(body !== undefined, 'Neutral drone body has opacity 0.6');
})();

// ============================================================
// SECTION 5: createTurretModel
// ============================================================

console.log('\n--- createTurretModel ---');

(function testTurretReturnGroup() {
    const g = M.createTurretModel('friendly');
    assert(g.isGroup, 'createTurretModel returns a Group');
})();

(function testTurretUserData() {
    const g = M.createTurretModel('friendly');
    assertEqual(g.userData.unitType, 'turret', 'Turret userData.unitType = "turret"');
})();

(function testTurretHasTwinBarrels() {
    const g = M.createTurretModel('hostile');
    // Twin barrels: two CylinderGeometry meshes at y=0.87
    const barrels = g.children.filter(c =>
        c.isMesh && c.geometry && c.geometry.type === 'CylinderGeometry' &&
        Math.abs(c.position.y - 0.87) < 0.01);
    assert(barrels.length >= 2, 'Turret has twin barrels at y=0.87');
})();

(function testTurretHasBaseRing() {
    const g = M.createTurretModel('friendly');
    const rings = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'TorusGeometry');
    assert(rings.length >= 1, 'Turret has neon ring around base');
})();

(function testTurretHasSensorEye() {
    const g = M.createTurretModel('friendly');
    const sensors = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'SphereGeometry' && c.position.y > 1.0);
    assert(sensors.length >= 1, 'Turret has sensor eye on top');
})();

// ============================================================
// SECTION 6: createPersonModel
// ============================================================

console.log('\n--- createPersonModel ---');

(function testPersonReturnGroup() {
    const g = M.createPersonModel('friendly');
    assert(g.isGroup, 'createPersonModel returns a Group');
})();

(function testPersonUserData() {
    const g = M.createPersonModel('hostile');
    assertEqual(g.userData.unitType, 'person', 'Person userData.unitType = "person"');
})();

(function testPersonHasArms() {
    const g = M.createPersonModel('hostile');
    const arms = g.children.filter(c => c.userData && c.userData.isArm);
    assertEqual(arms.length, 2, 'Person has 2 arms');
})();

(function testPersonHasVisor() {
    const g = M.createPersonModel('friendly');
    const visors = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'BoxGeometry' && c.position.y > 1.3);
    assert(visors.length >= 1, 'Person has visor face plate');
})();

(function testPersonHasLegs() {
    const g = M.createPersonModel('friendly');
    // Two legs at y=0.25
    const legs = g.children.filter(c => c.isMesh && c.position && Math.abs(c.position.y - 0.25) < 0.01);
    assertEqual(legs.length, 2, 'Person has 2 legs');
})();

(function testPersonHasShadowRing() {
    const g = M.createPersonModel('friendly');
    const shadows = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'RingGeometry');
    assert(shadows.length >= 1, 'Person has ground shadow ring');
})();

(function testPersonAllAlliances() {
    for (const alliance of ['friendly', 'hostile', 'neutral', 'unknown']) {
        const g = M.createPersonModel(alliance);
        assertEqual(g.userData.unitType, 'person', `Person with alliance "${alliance}" has correct unitType`);
    }
})();

// ============================================================
// SECTION 7: createVehicleModel
// ============================================================

console.log('\n--- createVehicleModel ---');

(function testVehicleReturnGroup() {
    const g = M.createVehicleModel('neutral');
    assert(g.isGroup, 'createVehicleModel returns a Group');
})();

(function testVehicleUserData() {
    const g = M.createVehicleModel('neutral');
    assertEqual(g.userData.unitType, 'vehicle', 'Vehicle userData.unitType = "vehicle"');
})();

(function testVehicleHasHeadlights() {
    const g = M.createVehicleModel('friendly');
    const headlights = g.children.filter(c =>
        c.isMesh && c.geometry && c.geometry.type === 'SphereGeometry' &&
        Math.abs(c.position.z - 1.27) < 0.01);
    assertEqual(headlights.length, 2, 'Vehicle has 2 headlights');
})();

(function testVehicleHasTaillights() {
    const g = M.createVehicleModel('hostile');
    const taillights = g.children.filter(c =>
        c.isMesh && c.geometry && c.geometry.type === 'BoxGeometry' &&
        Math.abs(c.position.z - (-1.27)) < 0.01);
    assertEqual(taillights.length, 2, 'Vehicle has 2 taillights');
})();

(function testVehicleHas4Wheels() {
    const g = M.createVehicleModel('friendly');
    const wheels = g.children.filter(c =>
        c.isMesh && c.geometry && c.geometry.type === 'CylinderGeometry' &&
        Math.abs(c.position.y - 0.22) < 0.01);
    assertEqual(wheels.length, 4, 'Vehicle has 4 wheels');
})();

(function testVehicleHasWindshield() {
    const g = M.createVehicleModel('neutral');
    const windshields = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'PlaneGeometry');
    assert(windshields.length >= 1, 'Vehicle has windshield plane');
})();

// ============================================================
// SECTION 8: createCameraModel
// ============================================================

console.log('\n--- createCameraModel ---');

(function testCameraReturnGroup() {
    const g = M.createCameraModel();
    assert(g.isGroup, 'createCameraModel returns a Group');
})();

(function testCameraUserData() {
    const g = M.createCameraModel();
    assertEqual(g.userData.unitType, 'camera', 'Camera userData.unitType = "camera"');
})();

(function testCameraNoAllianceRequired() {
    // createCameraModel takes no arguments
    const g = M.createCameraModel();
    assert(g.children.length > 0, 'Camera model requires no alliance arg');
})();

(function testCameraHasFovCone() {
    const g = M.createCameraModel();
    const cones = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'ConeGeometry');
    assert(cones.length >= 1, 'Camera has FOV cone');
})();

(function testCameraHasLensRing() {
    const g = M.createCameraModel();
    const rings = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'TorusGeometry');
    assert(rings.length >= 1, 'Camera has lens glow ring');
})();

(function testCameraHasStatusLed() {
    const g = M.createCameraModel();
    const leds = g.children.filter(c =>
        c.isMesh && c.geometry && c.geometry.type === 'SphereGeometry' &&
        c.material && c.material.color === COLORS.friendly);
    assert(leds.length >= 1, 'Camera has green status LED');
})();

// ============================================================
// SECTION 9: createSensorModel
// ============================================================

console.log('\n--- createSensorModel ---');

(function testSensorReturnGroup() {
    const g = M.createSensorModel();
    assert(g.isGroup, 'createSensorModel returns a Group');
})();

(function testSensorUserData() {
    const g = M.createSensorModel();
    assertEqual(g.userData.unitType, 'sensor', 'Sensor userData.unitType = "sensor"');
})();

(function testSensorNoAllianceRequired() {
    const g = M.createSensorModel();
    assert(g.children.length > 0, 'Sensor model requires no alliance arg');
})();

(function testSensorHasDetectionDisc() {
    const g = M.createSensorModel();
    const rings = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'RingGeometry');
    assert(rings.length >= 1, 'Sensor has detection radius ring');
})();

(function testSensorHasNeonRing() {
    const g = M.createSensorModel();
    const torus = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'TorusGeometry');
    assert(torus.length >= 1, 'Sensor has neon ring around dome');
})();

(function testSensorHasDome() {
    const g = M.createSensorModel();
    const domes = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'SphereGeometry');
    assert(domes.length >= 1, 'Sensor has dome body');
})();

// ============================================================
// SECTION 10: createSelectionRing
// ============================================================

console.log('\n--- createSelectionRing ---');

(function testSelectionRingReturnGroup() {
    const g = M.createSelectionRing();
    assert(g.isGroup, 'createSelectionRing returns a Group');
})();

(function testSelectionRingUserData() {
    const g = M.createSelectionRing();
    assertEqual(g.userData.isSelectionRing, true, 'Selection ring has isSelectionRing = true');
})();

(function testSelectionRingHasRings() {
    const g = M.createSelectionRing();
    const rings = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'TorusGeometry');
    assertEqual(rings.length, 2, 'Selection ring has 2 torus rings (outer + inner)');
})();

(function testSelectionRingHasGlowDisc() {
    const g = M.createSelectionRing();
    const discs = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'CircleGeometry');
    assert(discs.length >= 1, 'Selection ring has ground glow disc');
})();

(function testSelectionRingColors() {
    const g = M.createSelectionRing();
    // All elements use cyan color
    const cyanItems = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.cyan);
    assertEqual(cyanItems.length, 3, 'Selection ring: all 3 elements (2 rings + disc) use cyan color');
})();

// ============================================================
// SECTION 11: createBatteryBar
// ============================================================

console.log('\n--- createBatteryBar ---');

(function testBatteryBarReturnGroup() {
    const g = M.createBatteryBar(0.5);
    assert(g.isGroup, 'createBatteryBar returns a Group');
})();

(function testBatteryBarUserData() {
    const g = M.createBatteryBar(0.5);
    assertEqual(g.userData.isBatteryBar, true, 'Battery bar has isBatteryBar = true');
})();

(function testBatteryBarHighLevel() {
    const g = M.createBatteryBar(0.8);
    // level > 0.5 -> green
    const fills = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.friendly);
    assert(fills.length >= 1, 'Battery bar > 0.5 uses green fill color');
})();

(function testBatteryBarMediumLevel() {
    const g = M.createBatteryBar(0.3);
    // level 0.2-0.5 -> yellow
    const fills = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(fills.length >= 1, 'Battery bar 0.2-0.5 uses yellow fill color');
})();

(function testBatteryBarLowLevel() {
    const g = M.createBatteryBar(0.1);
    // level < 0.2 -> red
    const fills = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.hostile);
    assert(fills.length >= 1, 'Battery bar < 0.2 uses red fill color');
})();

(function testBatteryBarZeroLevel() {
    const g = M.createBatteryBar(0);
    // fillWidth = 0, so no fill child, only background
    assertEqual(g.children.length, 1, 'Battery bar at 0 has only background (no fill)');
})();

(function testBatteryBarFullLevel() {
    const g = M.createBatteryBar(1.0);
    assertEqual(g.children.length, 2, 'Battery bar at 1.0 has background + fill');
})();

(function testBatteryBarClampedAboveOne() {
    const g = M.createBatteryBar(1.5);
    // Math.min(1, 1.5) = 1, so fillWidth = barWidth = 1.0
    assertEqual(g.children.length, 2, 'Battery bar > 1.0 is clamped (still has 2 children)');
})();

(function testBatteryBarNegativeLevel() {
    const g = M.createBatteryBar(-0.5);
    // Math.max(0, -0.5) = 0, no fill
    assertEqual(g.children.length, 1, 'Battery bar negative level has only background');
})();

(function testBatteryBarBoundaryHalf() {
    // level = 0.5 -> should NOT be green (> 0.5 required), so it should be yellow
    const g = M.createBatteryBar(0.5);
    const yellowFills = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(yellowFills.length >= 1, 'Battery bar at exactly 0.5 uses yellow (not green)');
})();

(function testBatteryBarBoundaryTwoTenths() {
    // level = 0.2 -> should NOT be red (> 0.2 required), so it should be yellow
    const g = M.createBatteryBar(0.2);
    const yellowFills = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(yellowFills.length >= 1, 'Battery bar at exactly 0.2 uses yellow (not red)');
})();

// ============================================================
// SECTION 12: createNameLabel
// ============================================================

console.log('\n--- createNameLabel ---');

(function testNameLabelReturnSprite() {
    const s = M.createNameLabel('ROVER-01', 0x00f0ff);
    assert(s.isSprite, 'createNameLabel returns a Sprite');
})();

(function testNameLabelUserData() {
    const s = M.createNameLabel('TEST', 0x00f0ff);
    assertEqual(s.userData.isNameLabel, true, 'Name label has isNameLabel = true');
})();

(function testNameLabelScale() {
    const s = M.createNameLabel('AB', 0x00f0ff);
    // Scale: aspect * 0.08, 0.08, 1
    assertClose(s.scale.y, 0.08, 0.001, 'Name label scale.y = 0.08');
    assert(s.scale.x > 0, 'Name label scale.x > 0 (aspect-corrected)');
    assertClose(s.scale.z, 1, 0.001, 'Name label scale.z = 1');
})();

(function testNameLabelWithStringColor() {
    const s = M.createNameLabel('TEST', '#ff0000');
    assert(s.isSprite, 'Name label accepts string color');
})();

(function testNameLabelWithNullColor() {
    const s = M.createNameLabel('TEST', null);
    assert(s.isSprite, 'Name label accepts null color (defaults to #00f0ff)');
})();

(function testNameLabelWithUndefinedColor() {
    const s = M.createNameLabel('TEST');
    assert(s.isSprite, 'Name label accepts no color argument');
})();

(function testNameLabelWithNumericColor() {
    const s = M.createNameLabel('TEST', 0xff2a6d);
    assert(s.isSprite, 'Name label accepts numeric color');
})();

// ============================================================
// SECTION 13: createThreatRing
// ============================================================

console.log('\n--- createThreatRing ---');

(function testThreatRingReturnGroup() {
    const g = M.createThreatRing('hostile');
    assert(g.isGroup, 'createThreatRing returns a Group');
})();

(function testThreatRingUserData() {
    const g = M.createThreatRing('hostile');
    assertEqual(g.userData.isThreatRing, true, 'Threat ring has isThreatRing = true');
    assertEqual(g.userData.threatLevel, 'hostile', 'Threat ring stores threatLevel');
})();

(function testThreatRingHostileColor() {
    const g = M.createThreatRing('hostile');
    const rings = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.hostile);
    assert(rings.length >= 1, 'Hostile threat ring uses hostile color (magenta)');
})();

(function testThreatRingSuspiciousColor() {
    const g = M.createThreatRing('suspicious');
    const rings = g.children.filter(c => c.isMesh && c.material && c.material.color === 0xff9800);
    assert(rings.length >= 1, 'Suspicious threat ring uses orange color');
})();

(function testThreatRingUnknownColor() {
    const g = M.createThreatRing('unknown');
    const rings = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(rings.length >= 1, 'Unknown threat ring uses unknown/yellow color');
})();

(function testThreatRingDefaultColor() {
    const g = M.createThreatRing('');
    const rings = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(rings.length >= 1, 'Empty string threat level defaults to unknown/yellow');
})();

(function testThreatRingNullLevel() {
    const g = M.createThreatRing(null);
    assertEqual(g.userData.threatLevel, null, 'Null level stored in userData');
    assert(g.children.length >= 2, 'Null level still creates rings');
})();

(function testThreatRingHasTwoArcs() {
    const g = M.createThreatRing('hostile');
    const torus = g.children.filter(c => c.isMesh && c.geometry && c.geometry.type === 'TorusGeometry');
    assertEqual(torus.length, 2, 'Threat ring has 2 torus arcs');
})();

(function testThreatRingCaseInsensitive() {
    const g = M.createThreatRing('HOSTILE');
    const rings = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.hostile);
    assert(rings.length >= 1, 'Threat ring is case-insensitive');
})();

// ============================================================
// SECTION 14: getModelForType — type mapping
// ============================================================

console.log('\n--- getModelForType ---');

(function testGetModelRover() {
    const g = M.getModelForType('rover', 'friendly');
    assertEqual(g.userData.unitType, 'rover', 'getModelForType("rover") returns rover');
})();

(function testGetModelInterceptor() {
    const g = M.getModelForType('interceptor', 'friendly');
    assertEqual(g.userData.unitType, 'rover', 'getModelForType("interceptor") returns rover');
})();

(function testGetModelGround() {
    const g = M.getModelForType('ground', 'friendly');
    assertEqual(g.userData.unitType, 'rover', 'getModelForType("ground") returns rover');
})();

(function testGetModelDrone() {
    const g = M.getModelForType('drone', 'friendly');
    assertEqual(g.userData.unitType, 'drone', 'getModelForType("drone") returns drone');
})();

(function testGetModelAerial() {
    const g = M.getModelForType('aerial', 'friendly');
    assertEqual(g.userData.unitType, 'drone', 'getModelForType("aerial") returns drone');
})();

(function testGetModelScout() {
    const g = M.getModelForType('scout', 'friendly');
    assertEqual(g.userData.unitType, 'drone', 'getModelForType("scout") returns drone');
})();

(function testGetModelTurret() {
    const g = M.getModelForType('turret', 'friendly');
    assertEqual(g.userData.unitType, 'turret', 'getModelForType("turret") returns turret');
})();

(function testGetModelSentry() {
    const g = M.getModelForType('sentry', 'friendly');
    assertEqual(g.userData.unitType, 'turret', 'getModelForType("sentry") returns turret');
})();

(function testGetModelPerson() {
    const g = M.getModelForType('person', 'hostile');
    assertEqual(g.userData.unitType, 'person', 'getModelForType("person") returns person');
})();

(function testGetModelIntruder() {
    const g = M.getModelForType('intruder', 'hostile');
    assertEqual(g.userData.unitType, 'person', 'getModelForType("intruder") returns person');
})();

(function testGetModelHuman() {
    const g = M.getModelForType('human', 'neutral');
    assertEqual(g.userData.unitType, 'person', 'getModelForType("human") returns person');
})();

(function testGetModelVehicle() {
    const g = M.getModelForType('vehicle', 'neutral');
    assertEqual(g.userData.unitType, 'vehicle', 'getModelForType("vehicle") returns vehicle');
})();

(function testGetModelCar() {
    const g = M.getModelForType('car', 'neutral');
    assertEqual(g.userData.unitType, 'vehicle', 'getModelForType("car") returns vehicle');
})();

(function testGetModelTruck() {
    const g = M.getModelForType('truck', 'neutral');
    assertEqual(g.userData.unitType, 'vehicle', 'getModelForType("truck") returns vehicle');
})();

(function testGetModelCamera() {
    const g = M.getModelForType('camera', 'friendly');
    assertEqual(g.userData.unitType, 'camera', 'getModelForType("camera") returns camera');
})();

(function testGetModelPtz() {
    const g = M.getModelForType('ptz', 'friendly');
    assertEqual(g.userData.unitType, 'camera', 'getModelForType("ptz") returns camera');
})();

(function testGetModelDome() {
    const g = M.getModelForType('dome', 'friendly');
    assertEqual(g.userData.unitType, 'camera', 'getModelForType("dome") returns camera');
})();

(function testGetModelSensor() {
    const g = M.getModelForType('sensor', 'friendly');
    assertEqual(g.userData.unitType, 'sensor', 'getModelForType("sensor") returns sensor');
})();

(function testGetModelMotion() {
    const g = M.getModelForType('motion', 'friendly');
    assertEqual(g.userData.unitType, 'sensor', 'getModelForType("motion") returns sensor');
})();

(function testGetModelMicrophone() {
    const g = M.getModelForType('microphone', 'friendly');
    assertEqual(g.userData.unitType, 'sensor', 'getModelForType("microphone") returns sensor');
})();

(function testGetModelCaseInsensitive() {
    const g = M.getModelForType('DRONE', 'friendly');
    assertEqual(g.userData.unitType, 'drone', 'getModelForType is case-insensitive');
})();

(function testGetModelSubstring() {
    const g = M.getModelForType('scout_drone_v2', 'friendly');
    assertEqual(g.userData.unitType, 'drone', 'getModelForType matches substrings ("scout_drone_v2" -> drone)');
})();

(function testGetModelDefaultHostile() {
    const g = M.getModelForType('', 'hostile');
    assertEqual(g.userData.unitType, 'person', 'Empty type + hostile alliance defaults to person');
})();

(function testGetModelDefaultFriendly() {
    const g = M.getModelForType('', 'friendly');
    assertEqual(g.userData.unitType, 'rover', 'Empty type + friendly alliance defaults to rover');
})();

(function testGetModelDefaultUnknown() {
    const g = M.getModelForType('', 'unknown');
    assertEqual(g.userData.unitType, 'person', 'Empty type + unknown alliance defaults to person');
})();

(function testGetModelDefaultNull() {
    const g = M.getModelForType(null, null);
    assertEqual(g.userData.unitType, 'person', 'Null type + null alliance defaults to person');
})();

(function testGetModelDefaultUndefined() {
    const g = M.getModelForType(undefined, undefined);
    assertEqual(g.userData.unitType, 'person', 'Undefined type + undefined alliance defaults to person');
})();

// ============================================================
// SECTION 15: animateModel
// ============================================================

console.log('\n--- animateModel ---');

(function testAnimateModelNull() {
    // Should not throw
    M.animateModel(null, 0.016, 1.0, {});
    assert(true, 'animateModel(null) does not throw');
})();

(function testAnimateModelUndefined() {
    M.animateModel(undefined, 0.016, 1.0, {});
    assert(true, 'animateModel(undefined) does not throw');
})();

(function testAnimateModelNoUserData() {
    M.animateModel({}, 0.016, 1.0, {});
    assert(true, 'animateModel with no userData does not throw');
})();

(function testAnimateRoverWheelSpin() {
    const g = M.createRoverModel('friendly');
    // Find a wheel child (CylinderGeometry at y~0.18)
    const wheel = g.children.find(c =>
        c.isMesh && c.geometry && c.geometry.type === 'CylinderGeometry' &&
        Math.abs(c.position.y - 0.18) < 0.1);
    if (wheel) {
        const origRotX = wheel.rotation.x;
        M.animateModel(g, 0.016, 1.0, { speed: 5 });
        assert(wheel.rotation.x !== origRotX, 'Rover wheels rotate when speed > 0');
    } else {
        assert(false, 'Could not find rover wheel to test animation');
    }
})();

(function testAnimateRoverWheelStill() {
    const g = M.createRoverModel('friendly');
    const wheel = g.children.find(c =>
        c.isMesh && c.geometry && c.geometry.type === 'CylinderGeometry' &&
        Math.abs(c.position.y - 0.18) < 0.1);
    if (wheel) {
        const origRotX = wheel.rotation.x;
        M.animateModel(g, 0.016, 1.0, { speed: 0 });
        assertClose(wheel.rotation.x, origRotX, 0.001, 'Rover wheels do not rotate at speed 0');
    } else {
        assert(false, 'Could not find rover wheel to test zero-speed animation');
    }
})();

(function testAnimateDroneRotors() {
    const g = M.createDroneModel('friendly');
    const rotor = g.children.find(c => c.userData && c.userData.isRotor);
    const origRotY = rotor.rotation.y;
    M.animateModel(g, 0.016, 1.0, {});
    assert(rotor.rotation.y !== origRotY, 'Drone rotors spin on animate');
})();

(function testAnimatePersonArmSwing() {
    const g = M.createPersonModel('hostile');
    const arm = g.children.find(c => c.userData && c.userData.isArm);
    const origRotX = arm.rotation.x;
    M.animateModel(g, 0.016, 1.0, { speed: 2 });
    // Arms should swing when speed > 0.1
    assert(arm.rotation.x !== origRotX, 'Person arms swing when moving (speed > 0.1)');
})();

(function testAnimatePersonArmsStillAtLowSpeed() {
    const g = M.createPersonModel('hostile');
    const arm = g.children.find(c => c.userData && c.userData.isArm);
    const origRotX = arm.rotation.x;
    M.animateModel(g, 0.016, 1.0, { speed: 0.05 });
    // Arms should NOT swing when speed <= 0.1
    assertClose(arm.rotation.x, origRotX, 0.001, 'Person arms do not swing at low speed (0.05 <= 0.1)');
})();

(function testAnimateVehicleWheelSpin() {
    const g = M.createVehicleModel('neutral');
    const wheel = g.children.find(c =>
        c.isMesh && c.geometry && c.geometry.type === 'CylinderGeometry' &&
        Math.abs(c.position.y - 0.22) < 0.1);
    if (wheel) {
        const origRotX = wheel.rotation.x;
        M.animateModel(g, 0.016, 1.0, { speed: 10 });
        assert(wheel.rotation.x !== origRotX, 'Vehicle wheels rotate when speed > 0');
    } else {
        assert(false, 'Could not find vehicle wheel to test animation');
    }
})();

(function testAnimateTurretNoThrow() {
    const g = M.createTurretModel('friendly');
    M.animateModel(g, 0.016, 1.0, { speed: 0 });
    assert(true, 'Turret animate does not throw (handled externally)');
})();

(function testAnimateWithEmptyState() {
    const g = M.createRoverModel('friendly');
    M.animateModel(g, 0.016, 1.0, {});
    assert(true, 'animateModel with empty state does not throw (speed defaults to 0)');
})();

// ============================================================
// SECTION 16: animateSelectionRing
// ============================================================

console.log('\n--- animateSelectionRing ---');

(function testAnimateSelectionRingNull() {
    M.animateSelectionRing(null, 1.0);
    assert(true, 'animateSelectionRing(null) does not throw');
})();

(function testAnimateSelectionRingUndefined() {
    M.animateSelectionRing(undefined, 1.0);
    assert(true, 'animateSelectionRing(undefined) does not throw');
})();

(function testAnimateSelectionRingPulsesScale() {
    const g = M.createSelectionRing();
    M.animateSelectionRing(g, 1.0);
    const expected = 1.0 + Math.sin(1.0 * 3) * 0.08;
    assertClose(g.scale.x, expected, 0.001, 'Selection ring scale.x pulses with sine');
    assertClose(g.scale.z, expected, 0.001, 'Selection ring scale.z pulses with sine');
    assertClose(g.scale.y, 1, 0.001, 'Selection ring scale.y stays at 1');
})();

(function testAnimateSelectionRingRotates() {
    const g = M.createSelectionRing();
    M.animateSelectionRing(g, 2.0);
    assertClose(g.rotation.y, 2.0 * 0.5, 0.001, 'Selection ring rotates at elapsed * 0.5');
})();

(function testAnimateSelectionRingPulsesOpacity() {
    const g = M.createSelectionRing();
    M.animateSelectionRing(g, 1.0);
    const expectedOpacity = 0.6 + Math.sin(1.0 * 4) * 0.2;
    assertClose(g.children[0].material.opacity, expectedOpacity, 0.001, 'Outer ring opacity pulses');
})();

// ============================================================
// SECTION 17: animateThreatRing
// ============================================================

console.log('\n--- animateThreatRing ---');

(function testAnimateThreatRingNull() {
    M.animateThreatRing(null, 1.0);
    assert(true, 'animateThreatRing(null) does not throw');
})();

(function testAnimateThreatRingRotates() {
    const g = M.createThreatRing('hostile');
    M.animateThreatRing(g, 2.0);
    assertClose(g.rotation.y, 2.0 * 1.5, 0.001, 'Threat ring rotates at elapsed * 1.5');
})();

(function testAnimateThreatRingPulsesInnerArc() {
    const g = M.createThreatRing('hostile');
    M.animateThreatRing(g, 1.0);
    const expectedOpacity = 0.2 + Math.sin(1.0 * 2) * 0.15;
    assertClose(g.children[1].material.opacity, expectedOpacity, 0.001, 'Inner arc opacity pulses');
})();

// ============================================================
// SECTION 18: Alliance color edge cases
// ============================================================

console.log('\n--- Alliance Color Edge Cases ---');

(function testAllianceCaseInsensitive() {
    const g1 = M.createRoverModel('FRIENDLY');
    const g2 = M.createRoverModel('friendly');
    // Both should use friendly palette — neon strips with friendly color
    const strips1 = g1.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.friendly);
    const strips2 = g2.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.friendly);
    assertEqual(strips1.length, strips2.length, 'Alliance case-insensitive: FRIENDLY == friendly');
})();

(function testAllianceGarbageStringDefaultsUnknown() {
    const g = M.createDroneModel('xyzzy');
    // Should use unknown palette — neon strips/LEDs with unknown color
    const items = g.children.filter(c => c.isMesh && c.material && c.material.color === COLORS.unknown);
    assert(items.length >= 1, 'Unrecognized alliance defaults to unknown palette');
})();

(function testNeutralAllianceTransparency() {
    const g = M.createTurretModel('neutral');
    // Neutral has opacity 0.6, so body material should be transparent
    const bodies = g.children.filter(c =>
        c.isMesh && c.material && c.material.type === 'MeshStandardMaterial' &&
        c.material.transparent === true && c.material.opacity === 0.6);
    assert(bodies.length >= 1, 'Neutral turret has transparent body (opacity 0.6)');
})();

// ============================================================
// SECTION 19: Model children integrity
// ============================================================

console.log('\n--- Model Children Integrity ---');

(function testAllModelsHaveShadowCasters() {
    const models = [
        M.createRoverModel('friendly'),
        M.createDroneModel('friendly'),
        M.createTurretModel('friendly'),
        M.createPersonModel('friendly'),
        M.createVehicleModel('friendly'),
        M.createCameraModel(),
        M.createSensorModel(),
    ];
    for (const g of models) {
        const casters = g.children.filter(c => c.castShadow === true);
        assert(casters.length >= 1, `${g.userData.unitType} model has at least 1 shadow caster`);
    }
})();

(function testAllUnitModelsHaveUnitType() {
    const types = ['rover', 'drone', 'turret', 'person', 'vehicle', 'camera', 'sensor'];
    const creators = [
        M.createRoverModel, M.createDroneModel, M.createTurretModel,
        M.createPersonModel, M.createVehicleModel, M.createCameraModel,
        M.createSensorModel,
    ];
    creators.forEach((fn, i) => {
        const alliance = (i < 5) ? 'friendly' : undefined;
        const g = alliance !== undefined ? fn(alliance) : fn();
        assertEqual(g.userData.unitType, types[i], `${types[i]} creator sets correct unitType`);
    });
})();

// ============================================================
// SECTION 20: getModelForType priority (first match wins)
// ============================================================

console.log('\n--- getModelForType Match Priority ---');

(function testGetModelRoverDroneConflict() {
    // "rover_drone" contains both "rover" and "drone" — rover should match first
    const g = M.getModelForType('rover_drone', 'friendly');
    assertEqual(g.userData.unitType, 'rover', '"rover_drone" matches rover first (checked before drone)');
})();

(function testGetModelDroneSentryConflict() {
    // "drone_sentry" contains both "drone" and "sentry" — drone should match first
    const g = M.getModelForType('drone_sentry', 'friendly');
    assertEqual(g.userData.unitType, 'drone', '"drone_sentry" matches drone first (checked before sentry)');
})();

(function testGetModelTurretPersonConflict() {
    // "turret_person" contains both "turret" and "person" — turret should match first
    const g = M.getModelForType('turret_person', 'friendly');
    assertEqual(g.userData.unitType, 'turret', '"turret_person" matches turret first (checked before person)');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(55));
console.log(`=== test_models.js: ${passed} passed, ${failed} failed ===`);
console.log('='.repeat(55));
if (failed > 0) process.exit(1);
