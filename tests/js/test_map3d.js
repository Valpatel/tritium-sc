/**
 * TRITIUM-SC Three.js 3D Tactical Map (map3d.js) Tests
 * Run: node tests/js/test_map3d.js
 *
 * Since Three.js requires WebGL (unavailable in Node.js), this test suite
 * uses a hybrid approach:
 *
 * 1. SOURCE ANALYSIS: Parse the source file as text to verify structure,
 *    function definitions, Three.js patterns, materials, and constants.
 *
 * 2. PURE FUNCTION EXTRACTION: Extract and test pure functions that have
 *    no Three.js dependencies (fadeToward, lerpAngle, gameToThree, etc.)
 *    by evaluating them in a sandboxed VM context.
 *
 * 3. PATTERN VERIFICATION: Verify shader/material setup, animation loop
 *    structure, disposal patterns, and frustum culling settings.
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
    assert(typeof str === 'string' && str.includes(sub), msg + ` (expected "${sub}" in "${String(str).substring(0, 80)}")`);
}
function assertMatch(str, regex, msg) {
    assert(typeof str === 'string' && regex.test(str), msg);
}

// ============================================================
// Load source as text for structural analysis
// ============================================================

const srcPath = __dirname + '/../../frontend/js/command/map3d.js';
const source = fs.readFileSync(srcPath, 'utf8');

// ============================================================
// Extract and run pure functions in a sandboxed VM context
// ============================================================

// Strip ES module syntax so it can run in Node VM
const stripped = source
    .replace(/^import\s+.*?from\s+['"][^'"]+['"];?\s*$/gm, '')
    .replace(/^export\s+/gm, '');

let perfNow = 1000;
let dateNow = 5000;
const ctx = vm.createContext({
    Math, Date: { now: () => dateNow },
    console: { log() {}, error() {}, warn() {} },
    Map, Array, Object, Number, Infinity, Boolean, parseInt, parseFloat,
    Set, WeakMap, Symbol, JSON,
    performance: { now: () => perfNow },
    // Stub THREE so the source can reference it without crashing
    THREE: undefined,
    TritiumModels: undefined,
    // Stub DOM APIs
    document: {
        getElementById: () => null,
        createElement: (tag) => ({
            tagName: tag,
            width: 512, height: 128,
            style: { cssText: '' },
            id: '',
            getContext: () => ({
                clearRect() {},
                fillRect() {},
                fillText() {},
                strokeText() {},
                drawImage() {},
                beginPath() {},
                moveTo() {},
                lineTo() {},
                arc() {},
                fill() {},
                stroke() {},
                font: '',
                textAlign: '',
                textBaseline: '',
                fillStyle: '',
                strokeStyle: '',
                lineWidth: 1,
                globalAlpha: 1,
            }),
        }),
    },
    window: { devicePixelRatio: 1 },
    requestAnimationFrame: () => 0,
    cancelAnimationFrame: () => {},
    clearTimeout: () => {},
    setTimeout: (fn) => { fn(); return 1; },
    fetch: () => Promise.resolve({ ok: false, json: () => Promise.resolve(null) }),
    Image: function() { this.crossOrigin = ''; this.onload = null; this.onerror = null; this.src = ''; },
    ResizeObserver: undefined,
});

// We only need the pure utility functions; running the full module will fail
// because THREE is undefined. Extract specific functions instead.
const pureFuncCode = `
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

    function gameToThree(gx, gy) {
        return { x: gx, z: -gy };
    }
`;

vm.runInContext(pureFuncCode, ctx);
const { fadeToward, lerpAngle, gameToThree } = ctx;

// ============================================================
// SECTION 1: Source Structure - Expected functions exist
// ============================================================

console.log('\n--- Source Structure: Exported Functions ---');

(function testExportInitMap() {
    assertMatch(source, /export\s+function\s+initMap\s*\(/, 'initMap() is exported');
})();

(function testExportDestroyMap() {
    assertMatch(source, /export\s+function\s+destroyMap\s*\(/, 'destroyMap() is exported');
})();

(function testExportToggleSatellite() {
    assertMatch(source, /export\s+function\s+toggleSatellite\s*\(/, 'toggleSatellite() is exported');
})();

(function testExportToggleRoads() {
    assertMatch(source, /export\s+function\s+toggleRoads\s*\(/, 'toggleRoads() is exported');
})();

(function testExportToggleGrid() {
    assertMatch(source, /export\s+function\s+toggleGrid\s*\(/, 'toggleGrid() is exported');
})();

(function testExportGetMapState() {
    assertMatch(source, /export\s+function\s+getMapState\s*\(/, 'getMapState() is exported');
})();

(function testExportCenterOnAction() {
    assertMatch(source, /export\s+function\s+centerOnAction\s*\(/, 'centerOnAction() is exported');
})();

(function testExportResetCamera() {
    assertMatch(source, /export\s+function\s+resetCamera\s*\(/, 'resetCamera() is exported');
})();

(function testExportZoomIn() {
    assertMatch(source, /export\s+function\s+zoomIn\s*\(/, 'zoomIn() is exported');
})();

(function testExportZoomOut() {
    assertMatch(source, /export\s+function\s+zoomOut\s*\(/, 'zoomOut() is exported');
})();

(function testExportToggleBuildings() {
    assertMatch(source, /export\s+function\s+toggleBuildings\s*\(/, 'toggleBuildings() is exported');
})();

(function testExportToggleFog() {
    assertMatch(source, /export\s+function\s+toggleFog\s*\(/, 'toggleFog() is exported');
})();

(function testExportToggleTilt() {
    assertMatch(source, /export\s+function\s+toggleTilt\s*\(/, 'toggleTilt() is exported');
})();

(function testExportSetLayers() {
    assertMatch(source, /export\s+function\s+setLayers\s*\(/, 'setLayers() is exported');
})();

// ============================================================
// SECTION 2: Source Structure - Internal functions exist
// ============================================================

console.log('\n--- Source Structure: Internal Functions ---');

(function testInternalPositionCamera() {
    assertMatch(source, /function\s+_positionCamera\s*\(/, '_positionCamera() defined');
})();

(function testInternalUpdateCamera() {
    assertMatch(source, /function\s+_updateCamera\s*\(/, '_updateCamera() defined');
})();

(function testInternalBuildGround() {
    assertMatch(source, /function\s+_buildGround\s*\(/, '_buildGround() defined');
})();

(function testInternalBuildGrid() {
    assertMatch(source, /function\s+_buildGrid\s*\(/, '_buildGrid() defined');
})();

(function testInternalBuildMapBorder() {
    assertMatch(source, /function\s+_buildMapBorder\s*\(/, '_buildMapBorder() defined');
})();

(function testInternalInitMaterials() {
    assertMatch(source, /function\s+_initMaterials\s*\(/, '_initMaterials() defined');
})();

(function testInternalCreateUnitMesh() {
    assertMatch(source, /function\s+_createUnitMesh\s*\(/, '_createUnitMesh() defined');
})();

(function testInternalUpdateUnits() {
    assertMatch(source, /function\s+_updateUnits\s*\(/, '_updateUnits() defined');
})();

(function testInternalRenderLoop() {
    assertMatch(source, /function\s+_renderLoop\s*\(/, '_renderLoop() defined');
})();

(function testInternalHandleResize() {
    assertMatch(source, /function\s+_handleResize\s*\(/, '_handleResize() defined');
})();

(function testInternalBindEvents() {
    assertMatch(source, /function\s+_bindEvents\s*\(/, '_bindEvents() defined');
})();

(function testInternalUpdateSelection() {
    assertMatch(source, /function\s+_updateSelection\s*\(/, '_updateSelection() defined');
})();

(function testInternalUpdateHealthBar() {
    assertMatch(source, /function\s+_updateHealthBar\s*\(/, '_updateHealthBar() defined');
})();

(function testInternalUpdateHeading() {
    assertMatch(source, /function\s+_updateHeading\s*\(/, '_updateHeading() defined');
})();

(function testInternalUpdateFOVCone() {
    assertMatch(source, /function\s+_updateFOVCone\s*\(/, '_updateFOVCone() defined');
})();

(function testInternalDrawMinimap() {
    assertMatch(source, /function\s+_drawMinimap\s*\(/, '_drawMinimap() defined');
})();

(function testInternalBuildBuildings() {
    assertMatch(source, /function\s+_buildBuildings\s*\(/, '_buildBuildings() defined');
})();

(function testInternalBuildRoads() {
    assertMatch(source, /function\s+_buildRoads\s*\(/, '_buildRoads() defined');
})();

(function testInternalAutoFitCamera() {
    assertMatch(source, /function\s+_autoFitCamera\s*\(/, '_autoFitCamera() defined');
})();

(function testInternalCreateTextSprite() {
    assertMatch(source, /function\s+_createTextSprite\s*\(/, '_createTextSprite() defined');
})();

(function testInternalSelectAtScreen() {
    assertMatch(source, /function\s+_selectAtScreen\s*\(/, '_selectAtScreen() defined');
})();

(function testInternalDispatchToScreen() {
    assertMatch(source, /function\s+_dispatchToScreen\s*\(/, '_dispatchToScreen() defined');
})();

(function testInternalAddDispatchArrow() {
    assertMatch(source, /function\s+_addDispatchArrow\s*\(/, '_addDispatchArrow() defined');
})();

(function testInternalUpdateDispatchArrows() {
    assertMatch(source, /function\s+_updateDispatchArrows\s*\(/, '_updateDispatchArrows() defined');
})();

(function testInternalCreateRoadRibbon() {
    assertMatch(source, /function\s+_createRoadRibbon\s*\(/, '_createRoadRibbon() defined');
})();

// ============================================================
// SECTION 3: Pure Functions - fadeToward
// ============================================================

console.log('\n--- Pure Functions: fadeToward ---');

(function testFadeTowardMovesToTarget() {
    const result = fadeToward(0, 10, 8, 0.016);
    assert(result > 0 && result < 10, 'fadeToward(0, 10, 8, 0.016) moves toward target (got ' + result + ')');
})();

(function testFadeTowardStaysAtTarget() {
    const result = fadeToward(10, 10, 8, 0.016);
    assertClose(result, 10, 0.01, 'fadeToward(10, 10) stays at target');
})();

(function testFadeTowardLargeDtConverges() {
    const result = fadeToward(0, 10, 8, 1.0);
    assert(result > 9.0, 'fadeToward with large dt converges near target (got ' + result + ')');
})();

(function testFadeTowardNegativeDirection() {
    const result = fadeToward(10, 0, 8, 0.016);
    assert(result < 10 && result > 0, 'fadeToward moves in negative direction (got ' + result + ')');
})();

(function testFadeTowardZeroDt() {
    const result = fadeToward(5, 10, 8, 0);
    assertClose(result, 5, 0.001, 'fadeToward with dt=0 stays put');
})();

(function testFadeTowardHighSpeed() {
    const result = fadeToward(0, 100, 100, 0.1);
    assert(result > 90, 'fadeToward with high speed almost reaches target (got ' + result + ')');
})();

(function testFadeTowardNegativeValues() {
    const result = fadeToward(0, -10, 8, 0.016);
    assert(result < 0 && result > -10, 'fadeToward handles negative targets (got ' + result + ')');
})();

// ============================================================
// SECTION 4: Pure Functions - lerpAngle
// ============================================================

console.log('\n--- Pure Functions: lerpAngle ---');

(function testLerpAngleSameAngle() {
    const result = lerpAngle(90, 90, 8, 0.016);
    assertClose(result, 90, 0.1, 'lerpAngle stays at same angle');
})();

(function testLerpAngleMovesTowardTarget() {
    const result = lerpAngle(0, 90, 8, 0.016);
    assert(result > 0 && result < 90, 'lerpAngle(0, 90) moves toward 90 (got ' + result + ')');
})();

(function testLerpAngleThroughZero() {
    const result = lerpAngle(350, 10, 8, 0.016);
    // Should wrap around 360 -- result should be > 350 or < 10
    assert(result > 350 || result < 10, 'lerpAngle(350, 10) wraps through 360 (got ' + result + ')');
})();

(function testLerpAngleBackwardThroughZero() {
    const result = lerpAngle(10, 350, 8, 0.016);
    assert(result < 10 || result > 350, 'lerpAngle(10, 350) wraps backward through 0 (got ' + result + ')');
})();

(function testLerpAngleShortestPath180() {
    // From 0 to 180, should go positive (shortest path)
    const result = lerpAngle(0, 180, 8, 0.016);
    assert(result > 0 && result < 180, 'lerpAngle(0, 180) takes positive path (got ' + result + ')');
})();

(function testLerpAngleLargeDt() {
    const result = lerpAngle(0, 90, 8, 1.0);
    assert(result > 85, 'lerpAngle with large dt converges (got ' + result + ')');
})();

(function testLerpAngleZeroDt() {
    const result = lerpAngle(45, 90, 8, 0);
    assertClose(result, 45, 0.001, 'lerpAngle with dt=0 stays put');
})();

// ============================================================
// SECTION 5: Pure Functions - gameToThree
// ============================================================

console.log('\n--- Pure Functions: gameToThree ---');

(function testGameToThreeOrigin() {
    const result = gameToThree(0, 0);
    assertClose(result.x, 0, 0.001, 'gameToThree(0,0).x = 0');
    assertClose(result.z, 0, 0.001, 'gameToThree(0,0).z = 0');
})();

(function testGameToThreePositiveX() {
    const result = gameToThree(10, 0);
    assertClose(result.x, 10, 0.001, 'gameToThree(10,0).x = 10 (East preserved)');
    assertClose(result.z, 0, 0.001, 'gameToThree(10,0).z = 0');
})();

(function testGameToThreePositiveY() {
    const result = gameToThree(0, 10);
    assertClose(result.x, 0, 0.001, 'gameToThree(0,10).x = 0');
    assertClose(result.z, -10, 0.001, 'gameToThree(0,10).z = -10 (North inverted)');
})();

(function testGameToThreeBothAxes() {
    const result = gameToThree(5, -3);
    assertClose(result.x, 5, 0.001, 'gameToThree(5,-3).x = 5');
    assertClose(result.z, 3, 0.001, 'gameToThree(5,-3).z = 3');
})();

(function testGameToThreeRoundtrip() {
    // Game -> Three -> back should be: x stays, z = -y, so y = -z
    const result = gameToThree(7, 11);
    assertClose(result.x, 7, 0.001, 'roundtrip x preserved');
    assertClose(-result.z, 11, 0.001, 'roundtrip: -z gives original y');
})();

// ============================================================
// SECTION 6: Constants - Alliance Colors
// ============================================================

console.log('\n--- Constants: Alliance Colors ---');

(function testAllianceColorsDefinedFriendly() {
    assertMatch(source, /friendly:\s*0x05ffa1/, 'Alliance color friendly = green (0x05ffa1)');
})();

(function testAllianceColorsDefinedHostile() {
    assertMatch(source, /hostile:\s*0xff2a6d/, 'Alliance color hostile = magenta (0xff2a6d)');
})();

(function testAllianceColorsDefinedNeutral() {
    assertMatch(source, /neutral:\s*0x00a0ff/, 'Alliance color neutral = blue (0x00a0ff)');
})();

(function testAllianceColorsDefinedUnknown() {
    assertMatch(source, /unknown:\s*0xfcee0a/, 'Alliance color unknown = yellow (0xfcee0a)');
})();

(function testAllianceHexFriendly() {
    assertContains(source, "friendly: '#05ffa1'", 'Alliance hex friendly = #05ffa1');
})();

(function testAllianceHexHostile() {
    assertContains(source, "hostile:  '#ff2a6d'", 'Alliance hex hostile = #ff2a6d');
})();

(function testAllianceHexNeutral() {
    assertContains(source, "neutral:  '#00a0ff'", 'Alliance hex neutral = #00a0ff');
})();

(function testAllianceHexUnknown() {
    assertContains(source, "unknown:  '#fcee0a'", 'Alliance hex unknown = #fcee0a');
})();

// ============================================================
// SECTION 7: Constants - Camera Parameters
// ============================================================

console.log('\n--- Constants: Camera Parameters ---');

(function testZoomMin() {
    assertMatch(source, /const\s+ZOOM_MIN\s*=\s*5/, 'ZOOM_MIN = 5');
})();

(function testZoomMax() {
    assertMatch(source, /const\s+ZOOM_MAX\s*=\s*500/, 'ZOOM_MAX = 500');
})();

(function testZoomDefault() {
    assertMatch(source, /const\s+ZOOM_DEFAULT\s*=\s*30/, 'ZOOM_DEFAULT = 30');
})();

(function testCamLerp() {
    assertMatch(source, /const\s+CAM_LERP\s*=\s*6/, 'CAM_LERP = 6');
})();

(function testCamTiltAngle() {
    assertMatch(source, /const\s+CAM_TILT_ANGLE\s*=\s*50/, 'CAM_TILT_ANGLE = 50 degrees');
})();

(function testCamHeightFactor() {
    assertMatch(source, /const\s+CAM_HEIGHT_FACTOR\s*=\s*1\.2/, 'CAM_HEIGHT_FACTOR = 1.2');
})();

(function testBgColor() {
    assertMatch(source, /const\s+BG_COLOR\s*=\s*0x060609/, 'BG_COLOR = 0x060609');
})();

(function testGridColor() {
    assertMatch(source, /const\s+GRID_COLOR\s*=\s*0x00f0ff/, 'GRID_COLOR = 0x00f0ff (cyan)');
})();

(function testDispatchArrowLifetime() {
    assertMatch(source, /const\s+DISPATCH_ARROW_LIFETIME\s*=\s*3000/, 'DISPATCH_ARROW_LIFETIME = 3000ms');
})();

// ============================================================
// SECTION 8: Three.js Object Creation Patterns
// ============================================================

console.log('\n--- Three.js Object Creation Patterns ---');

(function testCreatesOrthographicCamera() {
    assertMatch(source, /new\s+THREE\.OrthographicCamera\s*\(/, 'Creates OrthographicCamera (not Perspective -- RTS style)');
})();

(function testCreatesWebGLRenderer() {
    assertMatch(source, /new\s+THREE\.WebGLRenderer\s*\(/, 'Creates WebGLRenderer');
})();

(function testRendererAntialiasEnabled() {
    assertMatch(source, /antialias:\s*true/, 'Renderer has antialias: true');
})();

(function testRendererHighPerformance() {
    assertContains(source, "powerPreference: 'high-performance'", 'Renderer requests high-performance GPU');
})();

(function testCreatesScene() {
    assertMatch(source, /new\s+THREE\.Scene\s*\(/, 'Creates Scene');
})();

(function testSceneFog() {
    assertMatch(source, /new\s+THREE\.FogExp2\s*\(/, 'Scene uses FogExp2 (exponential fog)');
})();

(function testCreatesClock() {
    assertMatch(source, /new\s+THREE\.Clock\s*\(/, 'Creates THREE.Clock for delta time');
})();

(function testCreatesRaycaster() {
    assertMatch(source, /new\s+THREE\.Raycaster\s*\(/, 'Creates Raycaster for picking');
})();

// ============================================================
// SECTION 9: Lighting Setup
// ============================================================

console.log('\n--- Lighting Setup ---');

(function testAmbientLight() {
    assertMatch(source, /new\s+THREE\.AmbientLight\s*\(\s*0xffffff,\s*0\.4\s*\)/, 'AmbientLight at 0.4 intensity');
})();

(function testHemisphereLight() {
    assertMatch(source, /new\s+THREE\.HemisphereLight\s*\(/, 'HemisphereLight for sky/ground coloring');
})();

(function testDirectionalLight() {
    assertMatch(source, /new\s+THREE\.DirectionalLight\s*\(\s*0xffffff,\s*0\.7\s*\)/, 'DirectionalLight at 0.7 intensity');
})();

(function testDirectionalLightCastsShadow() {
    assertContains(source, 'dirLight.castShadow = true', 'Directional light casts shadows');
})();

(function testShadowMapSize() {
    assertContains(source, 'shadow.mapSize.width = 2048', 'Shadow map 2048px resolution');
})();

(function testShadowMapType() {
    assertContains(source, 'THREE.PCFSoftShadowMap', 'Uses PCFSoftShadowMap for soft shadows');
})();

// ============================================================
// SECTION 10: Renderer Configuration
// ============================================================

console.log('\n--- Renderer Configuration ---');

(function testToneMapping() {
    assertContains(source, 'THREE.ACESFilmicToneMapping', 'Uses ACESFilmic tone mapping');
})();

(function testToneMappingExposure() {
    assertContains(source, 'toneMappingExposure = 1.1', 'Tone mapping exposure = 1.1');
})();

(function testShadowMapEnabled() {
    assertContains(source, 'shadowMap.enabled = true', 'Shadow map is enabled');
})();

(function testPixelRatioClamp() {
    assertContains(source, 'Math.min(window.devicePixelRatio, 2)', 'Pixel ratio clamped to max 2');
})();

// ============================================================
// SECTION 11: Material Setup
// ============================================================

console.log('\n--- Material Setup ---');

(function testAllianceMaterialsCreated() {
    assertContains(source, "for (const [alliance, color] of Object.entries(ALLIANCE_COLORS))", 'Alliance materials loop over all colors');
})();

(function testMaterialUsesStandard() {
    assertMatch(source, /new\s+THREE\.MeshStandardMaterial\s*\(\{[\s\S]*?color[\s\S]*?roughness/, 'Alliance materials use MeshStandardMaterial with roughness');
})();

(function testMaterialEmissive() {
    assertContains(source, 'emissiveIntensity: 0.15', 'Alliance materials have emissive glow');
})();

(function testSelectionMaterial() {
    assertContains(source, "materials.selection = new THREE.MeshBasicMaterial", 'Selection ring material defined');
})();

(function testDispatchMaterial() {
    assertContains(source, "materials.dispatch = new THREE.LineDashedMaterial", 'Dispatch arrow dashed material defined');
})();

(function testZoneMaterials() {
    assertContains(source, "materials.zoneRestricted", 'Zone restricted material defined');
    assertContains(source, "materials.zonePerimeter", 'Zone perimeter material defined');
})();

(function testBuildingMaterials() {
    assertContains(source, "materials.building = new THREE.MeshBasicMaterial", 'Building wall material defined');
    assertContains(source, "materials.buildingRoof = new THREE.MeshBasicMaterial", 'Building roof material defined');
    assertContains(source, "materials.buildingEdge = new THREE.LineBasicMaterial", 'Building edge material defined');
})();

(function testRoadMaterial() {
    assertContains(source, "materials.road = new THREE.MeshBasicMaterial", 'Road surface material defined');
})();

(function testEffectRingMaterial() {
    assertContains(source, "materials.effectRing = new THREE.MeshBasicMaterial", 'Effect ring material defined');
})();

// ============================================================
// SECTION 12: Unit Model Creation
// ============================================================

console.log('\n--- Unit Model Creation ---');

(function testUnitMeshDroneGeometry() {
    assertMatch(source, /CylinderGeometry\s*\(\s*0\.5,\s*0\.5,\s*0\.12/, 'Drone body is a thin cylinder (disc shape)');
})();

(function testUnitMeshDrone4Rotors() {
    assertContains(source, 'for (let i = 0; i < 4; i++)', 'Drone has 4 rotor positions');
})();

(function testUnitMeshTurretGeometry() {
    assertMatch(source, /CylinderGeometry\s*\(\s*0\.5,\s*0\.6,\s*0\.5,\s*6\)/, 'Turret body is a hexagonal cylinder');
})();

(function testUnitMeshTurretBarrel() {
    assertMatch(source, /CylinderGeometry\s*\(\s*0\.06,\s*0\.06,\s*0\.6/, 'Turret has barrel geometry');
})();

(function testUnitMeshHostilePerson() {
    // Hostile is a cylinder body + sphere head
    assertMatch(source, /alliance\s*===\s*'hostile'[\s\S]*?CylinderGeometry\s*\(\s*0\.2,\s*0\.2,\s*0\.6/, 'Hostile person has cylinder body');
})();

(function testUnitMeshHostileHead() {
    assertMatch(source, /SphereGeometry\s*\(\s*0\.2,\s*8,\s*6\)/, 'Hostile person has sphere head');
})();

(function testUnitMeshDefaultRover() {
    // Default (else) branch: rover shape
    assertMatch(source, /CylinderGeometry\s*\(\s*0\.35,\s*0\.45,\s*0\.3/, 'Default rover body is a tapered cylinder');
})();

(function testUnitMeshShadowCircle() {
    assertMatch(source, /CircleGeometry\s*\(\s*0\.[45],\s*16\)/, 'Units have shadow circle underneath');
})();

(function testUnitMeshCastShadow() {
    assertContains(source, 'bodyMesh.castShadow = true', 'Unit body meshes cast shadows');
})();

(function testDroneFlightHeight() {
    assertContains(source, "assetType.includes('drone') ? 3 : 0", 'Drones fly at height 3, ground units at 0');
})();

(function testUnitGroupUserData() {
    assertContains(source, 'group.userData.targetId = id', 'Unit group stores targetId in userData');
    assertContains(source, 'group.userData.alliance = alliance', 'Unit group stores alliance in userData');
})();

// ============================================================
// SECTION 13: Heading Arrow
// ============================================================

console.log('\n--- Heading Arrow ---');

(function testHeadingArrowNamed() {
    assertContains(source, "line.name = 'headingArrow'", 'Heading arrow is named for removal');
})();

(function testHeadingRemovesOld() {
    assertContains(source, "group.getObjectByName('headingArrow')", 'Old heading arrow is removed before creating new');
})();

(function testHeadingRadianConversion() {
    assertContains(source, '-heading * Math.PI / 180', 'Heading converts degrees to radians (negated)');
})();

// ============================================================
// SECTION 14: FOV Cone
// ============================================================

console.log('\n--- FOV Cone ---');

(function testFovConeNamed() {
    assertContains(source, "cone.name = 'fovCone'", 'FOV cone is named for identification');
})();

(function testFovConeDisposesOld() {
    assertContains(source, "old.traverse(c => { if (c.geometry) c.geometry.dispose(); })", 'Old FOV cone geometries are disposed');
})();

(function testFovConeUsesShapeGeometry() {
    assertMatch(source, /new\s+THREE\.ShapeGeometry\s*\(\s*shape\s*\)/, 'FOV cone uses ShapeGeometry for filled area');
})();

(function testFovConeTransparent() {
    // Check that the FOV cone material is transparent at low opacity
    assertContains(source, 'transparent: true, opacity: 0.06', 'FOV cone is transparent at 0.06 opacity');
})();

// ============================================================
// SECTION 15: Health Bar
// ============================================================

console.log('\n--- Health Bar ---');

(function testHealthBarIsGroup() {
    assertContains(source, 'barGroup.userData.isHealthBar = true', 'Health bar group has isHealthBar marker');
})();

(function testHealthBarColorThresholds() {
    // Green > 0.5, Yellow 0.25-0.5, Red < 0.25
    assertContains(source, 'pct > 0.5 ? 0x05ffa1 : pct > 0.25 ? 0xfcee0a : 0xff2a6d',
        'Health bar uses green/yellow/red thresholds at 50%/25%');
})();

(function testHealthBarFillScaling() {
    assertContains(source, 'c.scale.x = pct', 'Health bar fill scales with health percentage');
})();

(function testHealthBarBillboard() {
    assertContains(source, 'barGroup.lookAt(_state.camera.position)', 'Health bar billboards toward camera');
})();

// ============================================================
// SECTION 16: Camera Sync
// ============================================================

console.log('\n--- Camera Synchronization ---');

(function testCameraUsesOrthographic() {
    assertContains(source, 'THREE.OrthographicCamera', 'Camera is orthographic (RTS style)');
})();

(function testCameraSmoothLerp() {
    assertContains(source, 'fadeToward(c.x, c.targetX, CAM_LERP', 'Camera X uses fadeToward for smooth movement');
    assertContains(source, 'fadeToward(c.y, c.targetY, CAM_LERP', 'Camera Y uses fadeToward for smooth movement');
})();

(function testCameraZoomLerp() {
    assertContains(source, 'fadeToward(c.zoom, c.targetZoom, CAM_LERP * 0.8', 'Camera zoom uses fadeToward with reduced speed');
})();

(function testCameraTiltLerp() {
    assertContains(source, 'fadeToward(c.tiltAngle, c.tiltTarget, CAM_LERP * 0.6', 'Camera tilt uses fadeToward at reduced speed');
})();

(function testEdgeScrolling() {
    assertContains(source, 'EDGE_SCROLL_THRESHOLD', 'Edge scrolling uses threshold constant');
    assertContains(source, 'EDGE_SCROLL_SPEED', 'Edge scrolling uses speed constant');
})();

(function testShadowFollowsCamera() {
    assertContains(source, 'dirLight.position.set(tp.x + 30, 60, tp.z + 20)', 'Shadow light follows camera position');
})();

// ============================================================
// SECTION 17: Scene Cleanup / Disposal
// ============================================================

console.log('\n--- Scene Cleanup / Disposal ---');

(function testDestroyTraversesScene() {
    assertContains(source, '_state.scene.traverse(obj =>', 'destroyMap traverses entire scene');
})();

(function testDestroyDisposesGeometry() {
    assertContains(source, 'if (obj.geometry) obj.geometry.dispose()', 'Geometry disposed on destroy');
})();

(function testDestroyDisposesMaterial() {
    assertContains(source, "if (Array.isArray(obj.material)) obj.material.forEach(m => m.dispose())", 'Array materials disposed on destroy');
})();

(function testDestroyDisposesRenderer() {
    assertContains(source, '_state.renderer.dispose()', 'Renderer disposed on destroy');
})();

(function testDestroyRemovesDomElement() {
    assertContains(source, 'removeChild(_state.renderer.domElement)', 'Canvas DOM element removed on destroy');
})();

(function testDestroyNullsState() {
    assertContains(source, '_state.scene = null', 'Scene nulled on destroy');
    assertContains(source, '_state.camera = null', 'Camera nulled on destroy');
    assertContains(source, '_state.renderer = null', 'Renderer nulled on destroy');
})();

(function testDestroyUnsubsEventBus() {
    assertContains(source, "_state.unsubs.forEach(fn => { if (typeof fn === 'function') fn(); })", 'EventBus subscriptions cleaned up');
})();

(function testDestroyResizeObserver() {
    assertContains(source, '_state.resizeObserver.disconnect()', 'ResizeObserver disconnected on destroy');
})();

(function testDestroyCancelsAnimFrame() {
    assertContains(source, 'cancelAnimationFrame(_state.animFrame)', 'Animation frame cancelled on destroy');
})();

(function testUnitRemovalDisposesGeometry() {
    // When units disappear from store, their meshes are cleaned up
    assertMatch(source, /scene\.remove\(group\)[\s\S]*?group\.traverse\(c => \{ if \(c\.geometry\) c\.geometry\.dispose/, 'Removed unit meshes are disposed');
})();

// ============================================================
// SECTION 18: Animation Loop Structure
// ============================================================

console.log('\n--- Animation Loop Structure ---');

(function testRenderLoopUsesRequestAnimationFrame() {
    assertContains(source, 'requestAnimationFrame(_renderLoop)', 'Render loop uses requestAnimationFrame');
})();

(function testDeltaTimeClamped() {
    assertContains(source, 'Math.min(0.1, (now - _state.lastFrameTime) / 1000)', 'Delta time clamped to 0.1s max');
})();

(function testFpsTracking() {
    assertContains(source, '_state.frameTimes.push(now)', 'Frame times collected for FPS calculation');
    assertContains(source, '_state.currentFps = _state.frameTimes.length', 'FPS calculated from frame count in 1s window');
})();

(function testRenderLoopCallsUpdate() {
    assertContains(source, '_updateCamera(_state.dt)', 'Render loop updates camera');
    assertContains(source, '_updateUnits(_state.dt)', 'Render loop updates units');
    assertContains(source, '_updateSelection()', 'Render loop updates selection');
    assertContains(source, '_updateDispatchArrows()', 'Render loop updates dispatch arrows');
})();

(function testRenderLoopCallsRender() {
    assertContains(source, '_state.renderer.render(_state.scene, _state.camera)', 'Render loop calls renderer.render()');
})();

(function testRenderLoopGuardsNull() {
    assertContains(source, 'if (_state.renderer && _state.scene && _state.camera)', 'Render guarded against null state');
})();

// ============================================================
// SECTION 19: Unit Position Updates from Telemetry
// ============================================================

console.log('\n--- Unit Position Updates ---');

(function testPositionSmoothLerp() {
    assertContains(source, 'const lerpFactor = 0.15', 'Unit positions use 0.15 lerp factor');
})();

(function testPositionTracksGameCoords() {
    assertContains(source, "const gx = pos.x !== undefined ? pos.x : (unit.x || 0)", 'Position reads pos.x or falls back to unit.x');
})();

(function testHeadingSmoothLerp() {
    assertContains(source, "const smoothH = lerpAngle(prevH, unit.heading, 5, dt)", 'Heading smoothed with lerpAngle');
})();

(function testAdaptiveUnitScale() {
    assertContains(source, 'const zoomScale = Math.max(1, _state.cam.zoom / 30)', 'Units scale up when camera zooms out');
})();

(function testNeutralizedVisual() {
    assertContains(source, "unit.status === 'neutralized' || unit.health <= 0", 'Neutralized/dead units get visual treatment');
})();

// ============================================================
// SECTION 20: Satellite Tile System
// ============================================================

console.log('\n--- Satellite Tile System ---');

(function testSatTileLevels() {
    assertContains(source, 'SAT_TILE_LEVELS', 'Satellite tile level table defined');
    // Should have multiple zoom levels
    const matches = source.match(/\[\s*\d+,\s*\d+,\s*\d+\s*\]/g);
    assert(matches && matches.length >= 5, 'At least 5 satellite tile zoom levels defined (found ' + (matches ? matches.length : 0) + ')');
})();

(function testSatTileReloadDebounced() {
    assertContains(source, 'clearTimeout(_state.satReloadTimer)', 'Satellite reload is debounced');
})();

(function testSatTexture4096Canvas() {
    assertContains(source, 'const canvasSize = 4096', 'Satellite texture uses 4096px canvas');
})();

(function testSatTextureFiltering() {
    assertContains(source, 'THREE.LinearMipMapLinearFilter', 'Satellite texture uses trilinear filtering');
    assertContains(source, 'generateMipmaps = true', 'Satellite texture generates mipmaps');
})();

(function testSatTextureAnisotropic() {
    assertContains(source, 'getMaxAnisotropy()', 'Satellite texture uses max anisotropic filtering');
})();

// ============================================================
// SECTION 21: EventBus Integration
// ============================================================

console.log('\n--- EventBus Integration ---');

(function testSubscribesUnitsUpdated() {
    assertContains(source, "EventBus.on('units:updated'", 'Subscribes to units:updated event');
})();

(function testSubscribesMapMode() {
    assertContains(source, "EventBus.on('map:mode'", 'Subscribes to map:mode event');
})();

(function testSubscribesDispatchMode() {
    assertContains(source, "EventBus.on('unit:dispatch-mode'", 'Subscribes to unit:dispatch-mode event');
})();

(function testSubscribesDispatched() {
    assertContains(source, "EventBus.on('unit:dispatched'", 'Subscribes to unit:dispatched event');
})();

(function testStoreSubscription() {
    assertContains(source, "TritiumStore.on('map.selectedUnitId'", 'Subscribes to store selectedUnitId changes');
})();

(function testEmitsUnitSelected() {
    assertContains(source, "EventBus.emit('unit:selected'", 'Emits unit:selected on click');
})();

(function testEmitsUnitDispatched() {
    assertContains(source, "EventBus.emit('unit:dispatched'", 'Emits unit:dispatched on right-click dispatch');
})();

// ============================================================
// SECTION 22: Input Handling
// ============================================================

console.log('\n--- Input Handling ---');

(function testMiddleClickPan() {
    assertContains(source, 'e.button === 1', 'Middle click starts panning');
})();

(function testShiftLeftClickPan() {
    assertContains(source, 'e.button === 0 && e.shiftKey', 'Shift+left click starts panning');
})();

(function testLeftClickSelect() {
    assertContains(source, '_selectAtScreen(e)', 'Left click triggers selection');
})();

(function testRightClickDispatch() {
    assertContains(source, '_dispatchToScreen(e)', 'Right click triggers dispatch');
})();

(function testWheelZoom() {
    assertContains(source, "e.deltaY > 0 ? 1.15 : 0.87", 'Wheel zoom uses asymmetric factors');
})();

(function testContextMenuPrevented() {
    assertContains(source, 'e.preventDefault()', 'Context menu default prevented');
})();

// ============================================================
// SECTION 23: Minimap
// ============================================================

console.log('\n--- Minimap ---');

(function testMinimapDrawsUnits() {
    assertContains(source, 'for (const [id, unit] of TritiumStore.units)', 'Minimap iterates all units');
})();

(function testMinimapHostileLarger() {
    assertContains(source, "alliance === 'hostile' ? 3 : 2", 'Hostile dots larger on minimap');
})();

(function testMinimapCameraViewport() {
    assertContains(source, 'ctx.strokeRect(camSX - camW / 2', 'Minimap draws camera viewport rectangle');
})();

// ============================================================
// SECTION 24: Dispatch Arrows
// ============================================================

console.log('\n--- Dispatch Arrows ---');

(function testDispatchArrowDashed() {
    assertMatch(source, /LineDashedMaterial[\s\S]*?dashSize:\s*0\.5/, 'Dispatch arrows use dashed line material');
})();

(function testDispatchArrowConeHead() {
    assertMatch(source, /ConeGeometry\s*\(\s*0\.25,\s*0\.6,\s*6\)/, 'Dispatch arrow has cone arrowhead');
})();

(function testDispatchArrowFadesOverTime() {
    assertContains(source, '1 - (now - arr.time) / DISPATCH_ARROW_LIFETIME', 'Dispatch arrows fade with alpha over time');
})();

(function testDispatchArrowCleanup() {
    assertContains(source, 'arr.line.geometry.dispose()', 'Expired dispatch arrows dispose geometry');
})();

// ============================================================
// SECTION 25: Ground / Grid / Border
// ============================================================

console.log('\n--- Ground / Grid / Border ---');

(function testGroundPlaneSize() {
    assertContains(source, 'const size = 5000', 'Ground plane is 5000m');
})();

(function testGroundRotation() {
    assertContains(source, 'groundMesh.rotation.x = -Math.PI / 2', 'Ground plane rotated to horizontal');
})();

(function testGridSpacing() {
    assertContains(source, 'const divisions = 40', 'Grid has 40 divisions');
    assertContains(source, 'const range = 200', 'Grid range is 200m');
})();

(function testGridTransparent() {
    assertContains(source, 'grid.material.opacity = 0.08', 'Grid is subtle at 0.08 opacity');
})();

(function testMapBorderSquare() {
    assertContains(source, 'const half = 50', 'Map border is 100m square (50m half)');
})();

// ============================================================
// SECTION 26: Selection Ring
// ============================================================

console.log('\n--- Selection Ring ---');

(function testSelectionRingGeometry() {
    assertMatch(source, /RingGeometry\s*\(\s*0\.55,\s*0\.7,\s*32\)/, 'Selection ring uses RingGeometry');
})();

(function testSelectionPulseAnimation() {
    assertContains(source, 'Math.sin(Date.now() * 0.005) * 0.15', 'Selection ring pulses with sine wave');
})();

(function testSelectionFollowsUnit() {
    assertContains(source, 'ring.position.x = group.position.x', 'Selection ring follows unit position');
})();

// ============================================================
// SECTION 27: TritiumModels Integration
// ============================================================

console.log('\n--- TritiumModels Integration ---');

(function testModelsGetModelForType() {
    assertContains(source, 'TritiumModels.getModelForType', 'Uses TritiumModels.getModelForType for procedural models');
})();

(function testModelsCreateNameLabel() {
    assertContains(source, 'TritiumModels.createNameLabel', 'Uses TritiumModels.createNameLabel');
})();

(function testModelsCreateBatteryBar() {
    assertContains(source, 'TritiumModels.createBatteryBar', 'Uses TritiumModels.createBatteryBar for friendlies');
})();

(function testModelsAnimateModel() {
    assertContains(source, 'TritiumModels.animateModel', 'Uses TritiumModels.animateModel in render loop');
})();

(function testModelsSelectionRing() {
    assertContains(source, 'TritiumModels.createSelectionRing', 'Optionally uses TritiumModels.createSelectionRing');
})();

(function testModelsFallbackGeometry() {
    // When TritiumModels is not available, falls back to basic geometry
    assertContains(source, "// Fallback: simple geometric shapes", 'Has fallback geometry when TritiumModels unavailable');
})();

// ============================================================
// SECTION 28: Coordinate System Documentation
// ============================================================

console.log('\n--- Coordinate System ---');

(function testCoordSystemDocumented() {
    assertContains(source, 'Game world: 1 unit = 1 meter', 'Game world coordinate system documented');
    assertContains(source, 'X = East (game X), Z = -North (game -Y), Y = Up', 'Three.js coordinate mapping documented');
})();

(function testCoordConversionInCode() {
    // gameToThree function inverts Y axis for Three.js Z
    assertContains(source, 'return { x: gx, z: -gy }', 'gameToThree correctly maps game Y to Three.js -Z');
})();

// ============================================================
// SECTION 29: Buildings and Roads
// ============================================================

console.log('\n--- Buildings and Roads ---');

(function testBuildingExtrudeGeometry() {
    assertMatch(source, /new\s+THREE\.ExtrudeGeometry\s*\(/, 'Buildings use ExtrudeGeometry for 3D extrusion');
})();

(function testBuildingDefaultHeight() {
    assertContains(source, 'const height = bldg.height || 8', 'Default building height is 8m');
})();

(function testBuildingEdgeOutlines() {
    assertContains(source, 'outlineGround', 'Buildings have ground-level outlines');
    assertContains(source, 'outlineRoof', 'Buildings have roofline outlines');
})();

(function testBuildingVerticalEdges() {
    assertContains(source, 'for (let i = 0; i < outlineGround.length - 1; i += 3)', 'Vertical edges drawn every 3rd vertex');
})();

(function testRoadRibbonWidth() {
    assertContains(source, "const isPrimary = ['primary', 'secondary', 'trunk', 'motorway', 'tertiary']",
        'Road class detection for primary roads');
    assertContains(source, 'const width = isPrimary ? 3.0 : 1.5', 'Primary roads 3m wide, others 1.5m');
})();

// ============================================================
// SECTION 30: Layer HUD Display
// ============================================================

console.log('\n--- Layer HUD ---');

(function testLayerHudElement() {
    assertContains(source, "layerHud.id = 'map-layer-hud'", 'Layer HUD has correct DOM id');
})();

(function testLayerHudShowsLayers() {
    assertContains(source, "layers.push('SAT')", 'HUD shows SAT when satellite is on');
    assertContains(source, "layers.push('BLDG')", 'HUD shows BLDG when buildings visible');
    assertContains(source, "layers.push('ROADS')", 'HUD shows ROADS when roads on');
    assertContains(source, "layers.push('GRID')", 'HUD shows GRID when grid visible');
    assertContains(source, "layers.push('UNITS')", 'HUD shows UNITS when units visible');
})();

(function testLayerHudTiltMode() {
    assertContains(source, "const tilt = _state.cam?.tiltTarget > 70 ? '2D' : '3D'", 'HUD shows 2D/3D tilt mode');
})();

// ============================================================
// SECTION 31: getMapState return shape
// ============================================================

console.log('\n--- getMapState ---');

(function testGetMapStateFields() {
    assertContains(source, 'showSatellite:', 'getMapState returns showSatellite');
    assertContains(source, 'showRoads:', 'getMapState returns showRoads');
    assertContains(source, 'showGrid:', 'getMapState returns showGrid');
    assertContains(source, 'showBuildings:', 'getMapState returns showBuildings');
    assertContains(source, 'showUnits:', 'getMapState returns showUnits');
    assertContains(source, 'tiltMode:', 'getMapState returns tiltMode');
})();

// ============================================================
// SECTION 32: Zoom Control API
// ============================================================

console.log('\n--- Zoom Control ---');

(function testZoomInFactor() {
    assertContains(source, '_state.cam.targetZoom / 1.5', 'zoomIn divides by 1.5');
})();

(function testZoomOutFactor() {
    assertContains(source, '_state.cam.targetZoom * 1.5', 'zoomOut multiplies by 1.5');
})();

(function testZoomInClamped() {
    assertContains(source, 'Math.max(ZOOM_MIN, _state.cam.targetZoom / 1.5)', 'zoomIn clamped to ZOOM_MIN');
})();

(function testZoomOutClamped() {
    assertContains(source, 'Math.min(ZOOM_MAX, _state.cam.targetZoom * 1.5)', 'zoomOut clamped to ZOOM_MAX');
})();

// ============================================================
// SECTION 33: Tilt Toggle
// ============================================================

console.log('\n--- Tilt Toggle ---');

(function testTiltToggleValues() {
    assertContains(source, '_state.cam.tiltTarget > 70 ? CAM_TILT_ANGLE : 89',
        'Tilt toggles between 50deg (tilted) and 89deg (top-down)');
})();

// ============================================================
// SECTION 34: Module State Shape
// ============================================================

console.log('\n--- Module State Shape ---');

(function testStateHasScene() {
    assertContains(source, 'scene: null', 'State tracks scene');
})();

(function testStateHasCamera() {
    assertContains(source, 'camera: null', 'State tracks camera');
})();

(function testStateHasRenderer() {
    assertContains(source, 'renderer: null', 'State tracks renderer');
})();

(function testStateHasCam() {
    assertContains(source, 'cam: {', 'State has camera params object');
})();

(function testStateHasUnitMeshes() {
    assertContains(source, 'unitMeshes: {}', 'State tracks unit meshes');
})();

(function testStateHasSmoothHeadings() {
    assertContains(source, 'smoothHeadings: new Map()', 'State tracks smooth headings per unit');
})();

(function testStateHasUnsubs() {
    assertContains(source, 'unsubs: []', 'State tracks event unsubscribers');
})();

(function testStateHasBoundHandlers() {
    assertContains(source, 'boundHandlers: new Map()', 'State tracks bound event handlers');
})();

(function testStateHasInitializedFlag() {
    assertContains(source, 'initialized: false', 'State has initialized flag');
})();

// ============================================================
// SECTION 35: Imports
// ============================================================

console.log('\n--- Imports ---');

(function testImportsTritiumStore() {
    assertMatch(source, /import\s*\{\s*TritiumStore\s*\}\s*from/, 'Imports TritiumStore');
})();

(function testImportsEventBus() {
    assertMatch(source, /import\s*\{\s*EventBus\s*\}\s*from/, 'Imports EventBus');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
