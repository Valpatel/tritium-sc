/**
 * TRITIUM-SC War Room -- Editor tests
 * Run: node tests/js/test_war_editor.js
 *
 * Tests the war-editor.js module: asset definitions, palette selection,
 * ghost placement, keyboard handling, mouse interaction, config changes,
 * serialization, layout save/load, influence descriptions, and edge cases.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

let editorCode = fs.readFileSync(__dirname + '/../../frontend/js/war-editor.js', 'utf8');

// Expose internal functions for testing
editorCode += `
window._drawInfluence = _drawInfluence;
window._drawGhost = _drawGhost;
window._drawSelectedHighlight = _drawSelectedHighlight;
window._drawPlacedAssetOverlays = _drawPlacedAssetOverlays;
window._hitTestPlacedAsset = _hitTestPlacedAsset;
window._doPlaceAsset = _doPlaceAsset;
window._deleteAsset = _deleteAsset;
window._getDefaultConfig = _getDefaultConfig;
window._syncFromSimTargets = _syncFromSimTargets;
window._influenceDesc = _influenceDesc;
window._serializeLayout = _serializeLayout;
window._escapeHtml = _escapeHtml;
window._buildEditorPalette = _buildEditorPalette;
window._buildConfigPanel = _buildConfigPanel;
window._buildLayoutPanel = _buildLayoutPanel;
window._showEditorPalette = _showEditorPalette;
window._showConfigPanel = _showConfigPanel;
window._showLayoutPanel = _showLayoutPanel;
window._updateConfigPanel = _updateConfigPanel;
window._updatePaletteSelection = _updatePaletteSelection;
window.EDITOR_CATEGORIES = EDITOR_CATEGORIES;
`;

// ============================================================
// Mock environment
// ============================================================

const mockElements = {};
function resetElements() {
    Object.keys(mockElements).forEach(k => delete mockElements[k]);
}

let fetchCalls = [];
let fetchResponse = { ok: true, json: () => Promise.resolve({}) };

// Canvas 2D context mock that records draw calls
function createMockCtx() {
    const calls = [];
    return {
        _calls: calls,
        fillStyle: '',
        strokeStyle: '',
        lineWidth: 1,
        globalAlpha: 1.0,
        shadowColor: '',
        shadowBlur: 0,
        font: '',
        textAlign: '',
        textBaseline: '',
        beginPath() { calls.push('beginPath'); },
        moveTo(x, y) { calls.push(`moveTo(${x},${y})`); },
        lineTo(x, y) { calls.push(`lineTo`); },
        arc(x, y, r, s, e) { calls.push(`arc(${r})`); },
        closePath() { calls.push('closePath'); },
        fill() { calls.push('fill'); },
        stroke() { calls.push('stroke'); },
        fillText(text, x, y) { calls.push(`fillText(${text})`); },
        strokeRect(x, y, w, h) { calls.push('strokeRect'); },
        clearRect(x, y, w, h) { calls.push('clearRect'); },
        setLineDash(arr) { calls.push(`setLineDash(${arr.length})`); },
        roundRect(x, y, w, h, r) { calls.push('roundRect'); },
    };
}

let dateNow = 10000;
let timeoutFns = [];

const sandbox = vm.createContext({
    Math, console, Array, Object, Number, Boolean, parseInt, parseFloat, Infinity, String,
    JSON,
    Date: { now: () => dateNow },
    setTimeout: (fn, ms) => { timeoutFns.push({ fn, ms }); return timeoutFns.length; },
    clearTimeout: () => {},
    setInterval: () => 1,
    clearInterval: () => {},
    encodeURIComponent: encodeURIComponent,
    fetch: (url, opts) => {
        fetchCalls.push({ url, opts });
        return Promise.resolve(fetchResponse);
    },
    window: {},
    warState: {
        mode: 'setup',
        cam: { zoom: 2 },
        canvas: { style: { cursor: '' } },
        mapMin: -50,
        mapMax: 50,
    },
    // Mock coordinate transforms
    worldToScreen: (x, y) => ({ x: x * 2 + 400, y: y * 2 + 300 }),
    screenToWorld: (sx, sy) => ({ x: (sx - 400) / 2, y: (sy - 300) / 2 }),
    // Mock external functions
    getTargets: () => ({}),
    getTargetPosition: (t) => (t.position || { x: 0, y: 0 }),
    warPlaySound: () => {},
    warAddAlert: () => {},
    showNotification: () => {},
    geo: undefined,
    document: {
        getElementById(id) {
            if (!mockElements[id]) {
                mockElements[id] = {
                    id: id,
                    style: { display: '', opacity: '', cssText: '' },
                    textContent: '',
                    innerHTML: '',
                    className: '',
                    dataset: {},
                    classList: {
                        _classes: [],
                        add(cls) { if (!this._classes.includes(cls)) this._classes.push(cls); },
                        remove(cls) { this._classes = this._classes.filter(c => c !== cls); },
                        toggle(cls, force) {
                            if (force) this.add(cls); else this.remove(cls);
                        },
                        contains(cls) { return this._classes.includes(cls); },
                    },
                    children: [],
                    childNodes: [],
                    appendChild(child) { this.children.push(child); return child; },
                    querySelectorAll(sel) { return []; },
                    getContext() { return createMockCtx(); },
                };
            }
            return mockElements[id];
        },
        createElement(tag) {
            return {
                id: '',
                tagName: tag.toUpperCase(),
                style: { display: '', cssText: '' },
                textContent: '',
                innerHTML: '',
                dataset: {},
                children: [],
                childNodes: [],
                appendChild(child) { this.children.push(child); return child; },
                querySelectorAll(sel) { return []; },
                getContext() { return createMockCtx(); },
            };
        },
        querySelectorAll(sel) { return []; },
    },
});

vm.runInContext(editorCode, sandbox);

const w = sandbox.window;

// Helper: reset editor state for clean tests
function resetEditorState() {
    w.editorState.placing = null;
    w.editorState.ghostRotation = 0;
    w.editorState.ghostWorldPos = null;
    w.editorState.placedAssets = {};
    w.editorState.selectedAsset = null;
    w.editorState.hoveredAsset = null;
    w.editorState.configPanelVisible = false;
    w.editorState.currentLayoutName = '';
    w.editorState.initialized = false;
    sandbox.warState.mode = 'setup';
    fetchCalls = [];
    timeoutFns = [];
    resetElements();
}

// ============================================================
// EDITOR_ASSETS
// ============================================================

console.log('\n--- EDITOR_ASSETS definitions ---');

const assets = w.EDITOR_ASSETS;
assert(typeof assets === 'object' && assets !== null, 'EDITOR_ASSETS is an object');
assert(Object.keys(assets).length >= 16, 'EDITOR_ASSETS has at least 16 asset types (got ' + Object.keys(assets).length + ')');

// Check that every asset has required fields
const requiredFields = ['category', 'label', 'icon', 'color', 'influence', 'simType', 'simAlliance'];
for (const [type, def] of Object.entries(assets)) {
    for (const field of requiredFields) {
        assert(def[field] !== undefined, `${type} has ${field}`);
    }
}

// Check specific assets
assert(assets.camera.category === 'sensors', 'camera is in sensors category');
assert(assets.camera.icon === 'CAM', 'camera icon is CAM');
assert(assets.camera.influence.type === 'fov', 'camera has fov influence');
assert(assets.camera.influence.fov === 60, 'camera fov is 60');
assert(assets.camera.influence.range === 15, 'camera range is 15');
assert(assets.camera.color === '#00f0ff', 'camera color is cyan');

assert(assets.patrol_rover.category === 'robots', 'patrol_rover is in robots category');
assert(assets.patrol_rover.simAlliance === 'friendly', 'patrol_rover is friendly');

assert(assets.sentry_turret.category === 'infrastructure', 'sentry_turret is infrastructure');
assert(assets.sentry_turret.influence.type === 'arc', 'sentry_turret has arc influence');

assert(assets.dome_camera.influence.type === 'radius', 'dome_camera has radius influence');
assert(assets.dome_camera.influence.radius === 10, 'dome_camera radius is 10');

assert(assets.tank.category === 'heavy', 'tank is in heavy category');
assert(assets.tank.simType === 'tank', 'tank simType matches');

assert(assets.missile_turret.influence.arc === 360, 'missile_turret has 360 arc');
assert(assets.heavy_turret.influence.range === 30, 'heavy_turret range is 30');

assert(assets.speaker.config !== undefined, 'speaker has config object');
assert(Object.keys(assets.speaker.config).length === 0, 'speaker config is empty');

assert(assets.scout_drone.category === 'robots', 'scout_drone is in robots');
assert(assets.heavy_drone.simType === 'heavy_drone', 'heavy_drone simType');

// ============================================================
// EDITOR_CATEGORIES
// ============================================================

console.log('\n--- EDITOR_CATEGORIES ---');

const cats = w.EDITOR_CATEGORIES;
assert(Array.isArray(cats), 'EDITOR_CATEGORIES is an array');
assert(cats.length === 4, 'has 4 categories');
assert(cats[0].key === 'sensors', 'first category is sensors');
assert(cats[1].key === 'robots', 'second category is robots');
assert(cats[2].key === 'heavy', 'third category is heavy');
assert(cats[3].key === 'infrastructure', 'fourth category is infrastructure');

for (const cat of cats) {
    assert(typeof cat.label === 'string' && cat.label.length > 0, `category ${cat.key} has label`);
    assert(typeof cat.color === 'string' && cat.color.startsWith('#'), `category ${cat.key} has color`);
}

// ============================================================
// editorState initial values
// ============================================================

console.log('\n--- editorState initial values ---');

resetEditorState();
const es = w.editorState;
assert(es.placing === null, 'initial placing is null');
assert(es.ghostRotation === 0, 'initial ghostRotation is 0');
assert(es.ghostWorldPos === null, 'initial ghostWorldPos is null');
assert(typeof es.placedAssets === 'object', 'placedAssets is object');
assert(Object.keys(es.placedAssets).length === 0, 'placedAssets starts empty');
assert(es.selectedAsset === null, 'initial selectedAsset null');
assert(es.hoveredAsset === null, 'initial hoveredAsset null');
assert(es.configPanelVisible === false, 'initial configPanelVisible false');
assert(es.currentLayoutName === '', 'initial currentLayoutName empty');
assert(es.initialized === false, 'initial initialized false');

// ============================================================
// _getDefaultConfig
// ============================================================

console.log('\n--- _getDefaultConfig ---');

const camDefaults = w._getDefaultConfig(assets.camera);
assert(camDefaults.fov === 60, 'camera default fov is 60');
assert(camDefaults.range === 15, 'camera default range is 15');

const speakerDefaults = w._getDefaultConfig(assets.speaker);
assert(Object.keys(speakerDefaults).length === 0, 'speaker has no config defaults');

const turretDefaults = w._getDefaultConfig(assets.sentry_turret);
assert(turretDefaults.arc === 180, 'sentry_turret default arc is 180');
assert(turretDefaults.range === 20, 'sentry_turret default range is 20');

const emptyDef = w._getDefaultConfig({});
assert(Object.keys(emptyDef).length === 0, 'empty def yields empty config');

const nullConfigDef = w._getDefaultConfig({ config: null });
assert(Object.keys(nullConfigDef).length === 0, 'null config yields empty config');

// ============================================================
// _influenceDesc
// ============================================================

console.log('\n--- _influenceDesc ---');

assert(w._influenceDesc(assets.camera).includes('60'), 'camera desc includes fov 60');
assert(w._influenceDesc(assets.camera).includes('15'), 'camera desc includes range 15');

assert(w._influenceDesc(assets.dome_camera).includes('10'), 'dome_camera desc includes radius 10');

assert(w._influenceDesc(assets.sentry_turret).includes('180'), 'sentry_turret desc includes arc 180');
assert(w._influenceDesc(assets.sentry_turret).includes('20'), 'sentry_turret desc includes range 20');

const noInfluenceDef = { influence: { type: 'unknown' } };
assert(w._influenceDesc(noInfluenceDef) === '', 'unknown influence type returns empty string');

// ============================================================
// warEditorSelectPalette
// ============================================================

console.log('\n--- warEditorSelectPalette ---');

resetEditorState();

// Select camera
w.warEditorSelectPalette('camera');
assert(es.placing !== null, 'palette selection sets placing');
assert(es.placing.type === 'camera', 'placing type is camera');
assert(es.placing.category === 'sensors', 'placing category is sensors');
assert(es.placing.def === assets.camera, 'placing def matches asset definition');
assert(es.ghostRotation === 0, 'ghostRotation reset to 0 on select');

// Toggle off same type
w.warEditorSelectPalette('camera');
assert(es.placing === null, 'toggling same type deselects');

// Select different type
w.warEditorSelectPalette('tank');
assert(es.placing !== null, 'selecting new type sets placing');
assert(es.placing.type === 'tank', 'placing type is tank');

// Select clears selected asset
es.selectedAsset = 'some-id';
w.warEditorSelectPalette('patrol_rover');
assert(es.selectedAsset === null, 'selecting palette clears selectedAsset');
assert(es.placing.type === 'patrol_rover', 'now placing patrol_rover');

// Invalid type does nothing
const prevPlacing = es.placing;
w.warEditorSelectPalette('nonexistent_type');
assert(es.placing === prevPlacing, 'invalid type leaves placing unchanged');

// ============================================================
// warEditorKey
// ============================================================

console.log('\n--- warEditorKey ---');

resetEditorState();

// Not in setup mode -- returns false
sandbox.warState.mode = 'observe';
let result = w.warEditorKey({ key: 'r' });
assert(result === false, 'key handler returns false when not in setup mode');
sandbox.warState.mode = 'setup';

// R key rotates ghost when placing
w.warEditorSelectPalette('camera');
assert(es.ghostRotation === 0, 'ghost starts at 0');
result = w.warEditorKey({ key: 'r' });
assert(result === true, 'R key consumed when placing');
assert(es.ghostRotation === 45, 'ghost rotated to 45');

w.warEditorKey({ key: 'R' });
assert(es.ghostRotation === 90, 'R (uppercase) rotates to 90');

// Rotate through full circle
for (let i = 0; i < 6; i++) w.warEditorKey({ key: 'r' });
assert(es.ghostRotation === 0, 'ghost wraps around to 0 after 360');

// Escape cancels placement
result = w.warEditorKey({ key: 'Escape' });
assert(result === true, 'Escape consumed');
assert(es.placing === null, 'Escape cancels placement');

// R key rotates selected asset
es.placing = null;
es.selectedAsset = 'asset-1';
es.placedAssets['asset-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 10, y: 20 }, rotation: 0,
    config: {}, def: assets.camera,
};
result = w.warEditorKey({ key: 'r' });
assert(result === true, 'R key consumed for selected asset rotation');
assert(es.placedAssets['asset-1'].rotation === 45, 'selected asset rotated to 45');

// Delete key removes selected asset
result = w.warEditorKey({ key: 'Delete' });
assert(result === true, 'Delete key consumed');
// _deleteAsset calls fetch, so just verify it was called
assert(fetchCalls.length > 0, 'Delete triggers fetch call');
assert(fetchCalls[fetchCalls.length - 1].url.includes('asset-1'), 'Delete fetch targets correct asset');

// Escape deselects selected asset
resetEditorState();
es.selectedAsset = 'asset-2';
result = w.warEditorKey({ key: 'Escape' });
assert(result === true, 'Escape deselects asset');
assert(es.selectedAsset === null, 'selectedAsset cleared by Escape');

// Backspace also deletes
resetEditorState();
es.selectedAsset = 'asset-3';
es.placedAssets['asset-3'] = {
    type: 'tank', category: 'heavy',
    position: { x: 5, y: 5 }, rotation: 0,
    config: {}, def: assets.tank,
};
fetchCalls = [];
result = w.warEditorKey({ key: 'Backspace' });
assert(result === true, 'Backspace consumed');
assert(fetchCalls.length > 0, 'Backspace triggers delete fetch');

// Unhandled key returns false
resetEditorState();
result = w.warEditorKey({ key: 'x' });
assert(result === false, 'unhandled key returns false');

// ============================================================
// warEditorMouseMove
// ============================================================

console.log('\n--- warEditorMouseMove ---');

resetEditorState();

w.warEditorMouseMove(500, 400);
assert(es.ghostWorldPos !== null, 'ghostWorldPos set by mouse move');
assert(es.ghostWorldPos.x === 50, 'ghostWorldPos.x computed from screenToWorld');
assert(es.ghostWorldPos.y === 50, 'ghostWorldPos.y computed from screenToWorld');

// Not in setup mode -- does nothing
sandbox.warState.mode = 'observe';
es.ghostWorldPos = null;
w.warEditorMouseMove(500, 400);
assert(es.ghostWorldPos === null, 'mouseMove ignored when not setup mode');
sandbox.warState.mode = 'setup';

// Cursor changes when placing
es.placing = { type: 'camera', category: 'sensors', def: assets.camera };
w.warEditorMouseMove(450, 350);
assert(sandbox.warState.canvas.style.cursor === 'cell', 'cursor is cell when placing');

// Cursor changes when hovering over placed asset
resetEditorState();
es.placedAssets['hover-test'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: {}, def: assets.camera,
};
// worldToScreen(0, 0) = (400, 300), so clicking at (400, 300) should hit
w.warEditorMouseMove(400, 300);
assert(es.hoveredAsset === 'hover-test', 'hoveredAsset set on hover');
assert(sandbox.warState.canvas.style.cursor === 'pointer', 'cursor is pointer when hovering');

// ============================================================
// warEditorMouseDown
// ============================================================

console.log('\n--- warEditorMouseDown ---');

resetEditorState();

// Not in setup mode returns false
sandbox.warState.mode = 'observe';
result = w.warEditorMouseDown(400, 300, 0, false);
assert(result === false, 'mouseDown returns false when not setup');
sandbox.warState.mode = 'setup';

// Left click while placing triggers _doPlaceAsset
resetEditorState();
es.placing = { type: 'camera', category: 'sensors', def: assets.camera };
fetchCalls = [];
result = w.warEditorMouseDown(400, 300, 0, false);
assert(result === true, 'left click while placing is consumed');
assert(fetchCalls.length > 0, 'placing triggers spawn fetch');
assert(fetchCalls[0].url === '/api/amy/simulation/spawn', 'spawn URL correct');
const spawnBody = JSON.parse(fetchCalls[0].opts.body);
assert(spawnBody.asset_type === 'camera', 'spawn body has correct asset_type');
assert(spawnBody.alliance === 'friendly', 'spawn body has correct alliance');
assert(typeof spawnBody.position.x === 'number', 'spawn body has position.x');

// Left click selects placed asset when not placing
resetEditorState();
es.placedAssets['sel-test'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: { fov: 60, range: 15 }, def: assets.camera,
};
result = w.warEditorMouseDown(400, 300, 0, false);
assert(result === true, 'click on placed asset consumed');
assert(es.selectedAsset === 'sel-test', 'asset selected on click');

// Left click on empty deselects
resetEditorState();
es.selectedAsset = 'some-asset';
result = w.warEditorMouseDown(100, 100, 0, false);
assert(es.selectedAsset === null, 'click on empty deselects');

// Right click cancels placement
resetEditorState();
es.placing = { type: 'tank', category: 'heavy', def: assets.tank };
result = w.warEditorMouseDown(400, 300, 2, false);
assert(result === true, 'right click while placing consumed');
assert(es.placing === null, 'right click cancels placement');

// ============================================================
// _hitTestPlacedAsset
// ============================================================

console.log('\n--- _hitTestPlacedAsset ---');

resetEditorState();

// No placed assets returns null
let hit = w._hitTestPlacedAsset(400, 300);
assert(hit === null, 'no assets returns null');

// Asset within hit radius
es.placedAssets['hit-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: {}, def: assets.camera,
};
// worldToScreen(0,0) = (400, 300)
hit = w._hitTestPlacedAsset(400, 300);
assert(hit === 'hit-1', 'exact position hits asset');

hit = w._hitTestPlacedAsset(410, 300);
assert(hit === 'hit-1', 'within 16px hits asset (10px away)');

hit = w._hitTestPlacedAsset(420, 300);
assert(hit === null, 'beyond 16px returns null (20px away)');

// Multiple assets -- picks closest
es.placedAssets['hit-2'] = {
    type: 'tank', category: 'heavy',
    position: { x: 3, y: 0 }, rotation: 0,
    config: {}, def: assets.tank,
};
// worldToScreen(3, 0) = (406, 300)
hit = w._hitTestPlacedAsset(404, 300);
assert(hit === 'hit-2', 'closest asset selected when multiple overlap');

// ============================================================
// warEditorConfigChange
// ============================================================

console.log('\n--- warEditorConfigChange ---');

resetEditorState();
es.placedAssets['cfg-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: { fov: 60, range: 15 }, def: assets.camera,
};

w.warEditorConfigChange('cfg-1', 'fov', '90');
assert(es.placedAssets['cfg-1'].config.fov === 90, 'config fov updated to 90');

w.warEditorConfigChange('cfg-1', 'range', '25');
assert(es.placedAssets['cfg-1'].config.range === 25, 'config range updated to 25');

// Non-existent asset -- no crash
w.warEditorConfigChange('nonexistent', 'fov', '45');
assert(true, 'configChange on nonexistent asset does not crash');

// ============================================================
// warEditorDeleteSelected
// ============================================================

console.log('\n--- warEditorDeleteSelected ---');

resetEditorState();

// No selected asset does nothing
fetchCalls = [];
w.warEditorDeleteSelected();
assert(fetchCalls.length === 0, 'deleteSelected with no selection triggers no fetch');

// With selected asset triggers delete
es.selectedAsset = 'del-1';
es.placedAssets['del-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: {}, def: assets.camera,
};
fetchCalls = [];
w.warEditorDeleteSelected();
assert(fetchCalls.length === 1, 'deleteSelected triggers one fetch');
assert(fetchCalls[0].url.includes('del-1'), 'delete URL includes target id');
assert(fetchCalls[0].opts.method === 'DELETE', 'delete uses DELETE method');

// ============================================================
// _serializeLayout
// ============================================================

console.log('\n--- _serializeLayout ---');

resetEditorState();
es.placedAssets['s-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 10, y: 20 }, rotation: 90,
    config: { fov: 80, range: 25 }, def: assets.camera,
    name: 'cam-alpha',
};
es.placedAssets['s-2'] = {
    type: 'tank', category: 'heavy',
    position: { x: -5, y: 15 }, rotation: 180,
    config: { range: 30 }, def: assets.tank,
    name: 'tank-bravo',
};

const layout = w._serializeLayout('test-layout');
assert(layout.name === 'test-layout', 'layout name matches');
assert(typeof layout.id === 'string' && layout.id.startsWith('battlespace_'), 'layout id has prefix');
assert(layout.objects.length === 2, 'layout has 2 objects');

const obj1 = layout.objects.find(o => o.id === 's-1');
assert(obj1 !== undefined, 'object s-1 found in layout');
assert(obj1.type === 'camera', 'object type preserved');
assert(obj1.name === 'cam-alpha', 'object name preserved');
assert(obj1.position.x === 10, 'position.x = world x');
assert(obj1.position.y === 0, 'position.y = 0 (ground level)');
assert(obj1.position.z === 20, 'position.z = world y (ground plane mapping)');
assert(Math.abs(obj1.rotation.y - (90 * Math.PI / 180)) < 0.001, 'rotation converted to radians');
assert(obj1.rotation.x === 0, 'rotation.x is 0');
assert(obj1.rotation.z === 0, 'rotation.z is 0');
assert(obj1.scale.x === 1 && obj1.scale.y === 1 && obj1.scale.z === 1, 'scale is 1,1,1');
assert(obj1.properties.fov === 80, 'config properties included');
assert(obj1.properties.range === 25, 'config range property included');
assert(obj1.properties.name === 'cam-alpha', 'name in properties');

assert(layout.dimensions.width === 100, 'dimensions width = mapMax - mapMin');
assert(layout.dimensions.depth === 100, 'dimensions depth = mapMax - mapMin');
assert(layout.structures.houseWidth === 12, 'house width default');
assert(layout.environment.timeOfDay === 'night', 'environment timeOfDay');
assert(layout.amy.responseProtocol === 'alert', 'amy responseProtocol');

// Serialize with empty placed assets
resetEditorState();
const emptyLayout = w._serializeLayout('empty');
assert(emptyLayout.objects.length === 0, 'empty layout has 0 objects');
assert(emptyLayout.name === 'empty', 'empty layout name');

// Object with no name falls back to type
resetEditorState();
es.placedAssets['s-3'] = {
    type: 'speaker', category: 'infrastructure',
    position: { x: 0, y: 0 }, rotation: 0,
    config: {}, def: assets.speaker,
};
const layoutNoName = w._serializeLayout('no-name-test');
assert(layoutNoName.objects[0].name === 'speaker', 'name falls back to type when no name');

// ============================================================
// _escapeHtml
// ============================================================

console.log('\n--- _escapeHtml ---');

assert(w._escapeHtml('hello') === 'hello', 'plain string unchanged');
assert(w._escapeHtml('') === '', 'empty string returns empty');
// Note: our mock DOM textContent->innerHTML doesn't actually escape,
// but the function uses that mechanism. Test that it does not crash.
assert(typeof w._escapeHtml('<script>') === 'string', 'escapeHtml returns string for HTML input');
assert(typeof w._escapeHtml('a&b') === 'string', 'escapeHtml handles ampersand');

// ============================================================
// warEditorEnter / warEditorExit
// ============================================================

console.log('\n--- warEditorEnter / warEditorExit ---');

resetEditorState();

// Enter initializes on first call
w.warEditorEnter();
assert(es.initialized === true, 'initialized set to true after enter');

// Enter again does not reset initialized
const prevPalette = es.paletteEl;
w.warEditorEnter();
assert(es.initialized === true, 'still initialized on second enter');

// Exit clears state
es.placing = { type: 'camera', category: 'sensors', def: assets.camera };
es.selectedAsset = 'some-asset';
es.hoveredAsset = 'some-hover';
es.configPanelVisible = true;
w.warEditorExit();
assert(es.placing === null, 'exit clears placing');
assert(es.selectedAsset === null, 'exit clears selectedAsset');
assert(es.hoveredAsset === null, 'exit clears hoveredAsset');
assert(es.configPanelVisible === false, 'exit clears configPanelVisible');

// ============================================================
// warEditorDraw (smoke test -- no crash)
// ============================================================

console.log('\n--- warEditorDraw ---');

resetEditorState();

const drawCtx = createMockCtx();

// Not in setup mode -- early return, no drawing
sandbox.warState.mode = 'observe';
w.warEditorDraw(drawCtx);
assert(drawCtx._calls.length === 0, 'no drawing when not in setup mode');

// In setup mode with no assets/ghost -- runs without crash
sandbox.warState.mode = 'setup';
w.warEditorDraw(drawCtx);
assert(true, 'draw with empty state does not crash');

// With placed asset
es.placedAssets['draw-1'] = {
    type: 'camera', category: 'sensors',
    position: { x: 0, y: 0 }, rotation: 0,
    config: { fov: 60, range: 15 }, def: assets.camera,
};
const drawCtx2 = createMockCtx();
w.warEditorDraw(drawCtx2);
assert(drawCtx2._calls.length > 0, 'draw calls canvas methods for placed asset overlays');

// With ghost placement
es.placing = { type: 'tank', category: 'heavy', def: assets.tank };
es.ghostWorldPos = { x: 5, y: 5 };
const drawCtx3 = createMockCtx();
w.warEditorDraw(drawCtx3);
assert(drawCtx3._calls.length > 0, 'draw calls canvas methods for ghost');

// With selected asset
es.placing = null;
es.selectedAsset = 'draw-1';
const drawCtx4 = createMockCtx();
w.warEditorDraw(drawCtx4);
assert(drawCtx4._calls.length > 0, 'draw calls canvas methods for selected highlight');

// ============================================================
// _drawInfluence (all three types)
// ============================================================

console.log('\n--- _drawInfluence ---');

// FOV type
const fovCtx = createMockCtx();
w._drawInfluence(fovCtx, { x: 100, y: 100 }, 0, assets.camera, {}, 0.1);
assert(fovCtx._calls.includes('fill'), 'fov influence draws fill');
assert(fovCtx._calls.includes('stroke'), 'fov influence draws stroke');

// Radius type
const radCtx = createMockCtx();
w._drawInfluence(radCtx, { x: 100, y: 100 }, 0, assets.dome_camera, {}, 0.1);
assert(radCtx._calls.includes('fill'), 'radius influence draws fill');
assert(radCtx._calls.filter(c => c.startsWith('setLineDash')).length >= 1, 'radius uses dashed line');

// Arc type
const arcCtx = createMockCtx();
w._drawInfluence(arcCtx, { x: 100, y: 100 }, 90, assets.sentry_turret, {}, 0.1);
assert(arcCtx._calls.includes('fill'), 'arc influence draws fill');
assert(arcCtx._calls.includes('closePath'), 'arc influence closes path');

// Config overrides
const fovCtx2 = createMockCtx();
w._drawInfluence(fovCtx2, { x: 100, y: 100 }, 0, assets.camera, { fov: 90, range: 25 }, 0.1);
assert(fovCtx2._calls.length > 0, 'influence with config overrides draws correctly');

// ============================================================
// _syncFromSimTargets
// ============================================================

console.log('\n--- _syncFromSimTargets ---');

resetEditorState();

// With no targets, nothing synced
sandbox.getTargets = () => ({});
w._syncFromSimTargets();
assert(Object.keys(es.placedAssets).length === 0, 'no targets means no synced assets');

// Sync friendly camera target
sandbox.getTargets = () => ({
    'sim-1': { alliance: 'Friendly', asset_type: 'camera', heading: 45, name: 'cam-1', position: { x: 10, y: 20 } },
    'sim-2': { alliance: 'hostile', asset_type: 'tank', heading: 0, name: 'enemy-1', position: { x: 5, y: 5 } },
    'sim-3': { alliance: 'friendly', asset_type: 'nonexistent_type', heading: 0, name: 'unknown', position: { x: 0, y: 0 } },
});
sandbox.getTargetPosition = (t) => t.position || { x: 0, y: 0 };

w._syncFromSimTargets();
assert(es.placedAssets['sim-1'] !== undefined, 'friendly camera synced');
assert(es.placedAssets['sim-1'].type === 'camera', 'synced type matches');
assert(es.placedAssets['sim-1'].rotation === 45, 'synced rotation from heading');
assert(es.placedAssets['sim-1'].position.x === 10, 'synced position x');
assert(es.placedAssets['sim-1'].position.y === 20, 'synced position y');
assert(es.placedAssets['sim-2'] === undefined, 'hostile target not synced');
assert(es.placedAssets['sim-3'] === undefined, 'unknown type not synced');

// Already-synced assets not overwritten
es.placedAssets['sim-1'].rotation = 999;
w._syncFromSimTargets();
assert(es.placedAssets['sim-1'].rotation === 999, 'already synced asset not overwritten');

// ============================================================
// warEditorSaveLayout
// ============================================================

console.log('\n--- warEditorSaveLayout ---');

resetEditorState();
fetchCalls = [];
es.currentLayoutName = 'my-layout';
w.warEditorSaveLayout();
assert(fetchCalls.length === 1, 'save triggers one fetch');
assert(fetchCalls[0].url === '/api/amy/layouts', 'save URL correct');
assert(fetchCalls[0].opts.method === 'POST', 'save uses POST');
const saveBody = JSON.parse(fetchCalls[0].opts.body);
assert(saveBody.name === 'my-layout', 'save body has layout name');
assert(typeof saveBody.data === 'object', 'save body has data');

// Without layout name, generates one
resetEditorState();
fetchCalls = [];
w.warEditorSaveLayout();
const autoBody = JSON.parse(fetchCalls[0].opts.body);
assert(autoBody.name.startsWith('layout-'), 'auto-generated name starts with layout-');

// ============================================================
// warEditorLoadLayout / warEditorLoadLayoutMenu / warEditorCloseLayoutMenu
// ============================================================

console.log('\n--- layout menu ---');

resetEditorState();

// CloseLayoutMenu hides panel
es.layoutPanelEl = { style: { display: 'block' } };
w.warEditorCloseLayoutMenu();
assert(es.layoutPanelEl.style.display === 'none', 'close layout menu hides panel');

// CloseLayoutMenu with null panel does not crash
es.layoutPanelEl = null;
w.warEditorCloseLayoutMenu();
assert(true, 'close layout menu with null panel does not crash');

// LoadLayout triggers fetch
resetEditorState();
es.layoutPanelEl = { style: { display: 'block' } };
fetchCalls = [];
w.warEditorLoadLayout('my-level');
assert(es.layoutPanelEl.style.display === 'none', 'load layout closes menu');
assert(fetchCalls.length >= 1, 'load layout triggers fetch');
assert(fetchCalls[0].url.includes('my-level'), 'load fetch URL includes layout name');

// ============================================================
// _showEditorPalette
// ============================================================

console.log('\n--- _showEditorPalette ---');

resetEditorState();
// Test with paletteEl set
es.paletteEl = { style: { display: 'none' } };
w._showEditorPalette(true);
assert(es.paletteEl.style.display === 'block', 'show palette sets display block');
w._showEditorPalette(false);
assert(es.paletteEl.style.display === 'none', 'hide palette sets display none');

// Test fallback to getElementById
resetEditorState();
es.paletteEl = null;
mockElements['war-setup-palette'] = { style: { display: '' } };
w._showEditorPalette(true);
assert(mockElements['war-setup-palette'].style.display === 'block', 'fallback getElementById works');

// ============================================================
// _showConfigPanel
// ============================================================

console.log('\n--- _showConfigPanel ---');

resetEditorState();
es.configPanelEl = { style: { display: 'none' } };
w._showConfigPanel(true);
assert(es.configPanelEl.style.display === 'block', 'show config panel');
assert(es.configPanelVisible === true, 'configPanelVisible set true');
w._showConfigPanel(false);
assert(es.configPanelEl.style.display === 'none', 'hide config panel');
assert(es.configPanelVisible === false, 'configPanelVisible set false');

// No configPanelEl does not crash
es.configPanelEl = null;
w._showConfigPanel(true);
assert(true, 'showConfigPanel with null element does not crash');

// ============================================================
// Edge cases: rotation wrapping
// ============================================================

console.log('\n--- edge cases: rotation ---');

resetEditorState();
w.warEditorSelectPalette('camera');

// Rotate 8 times (8 * 45 = 360 -> wraps to 0)
for (let i = 0; i < 8; i++) {
    w.warEditorKey({ key: 'r' });
}
assert(es.ghostRotation === 0, 'rotation wraps at 360');

// After 7 rotations = 315
resetEditorState();
w.warEditorSelectPalette('camera');
for (let i = 0; i < 7; i++) {
    w.warEditorKey({ key: 'r' });
}
assert(es.ghostRotation === 315, '7 rotations = 315 degrees');

// ============================================================
// Edge cases: category/type counts
// ============================================================

console.log('\n--- edge cases: category type counts ---');

const sensorTypes = Object.entries(assets).filter(([, d]) => d.category === 'sensors');
assert(sensorTypes.length === 5, '5 sensor types');

const robotTypes = Object.entries(assets).filter(([, d]) => d.category === 'robots');
assert(robotTypes.length === 5, '5 robot types');

const heavyTypes = Object.entries(assets).filter(([, d]) => d.category === 'heavy');
assert(heavyTypes.length === 4, '4 heavy weapon types');

const infraTypes = Object.entries(assets).filter(([, d]) => d.category === 'infrastructure');
assert(infraTypes.length === 3, '3 infrastructure types');

// All assets are friendly
for (const [type, def] of Object.entries(assets)) {
    assert(def.simAlliance === 'friendly', `${type} is friendly alliance`);
}

// ============================================================
// Edge cases: mouse interaction with no canvas
// ============================================================

console.log('\n--- edge cases: no canvas ---');

resetEditorState();
sandbox.warState.canvas = null;
es.placing = { type: 'camera', category: 'sensors', def: assets.camera };
// Should not crash even without canvas
w.warEditorMouseMove(100, 100);
assert(es.ghostWorldPos !== null, 'ghostWorldPos set even without canvas');
sandbox.warState.canvas = { style: { cursor: '' } };

// ============================================================
// warState undefined guard in warEditorDraw
// ============================================================

console.log('\n--- warEditorDraw warState guard ---');

// Test that warEditorDraw early-returns when warState is undefined
// (In the actual code, it checks typeof warState === 'undefined')
// Since warState is defined in our sandbox, just verify no crash
const guardCtx = createMockCtx();
sandbox.warState.mode = 'tactical'; // not 'setup'
w.warEditorDraw(guardCtx);
assert(guardCtx._calls.length === 0, 'no draw calls when mode is not setup');
sandbox.warState.mode = 'setup';

// ============================================================
// Config defaults for all asset types
// ============================================================

console.log('\n--- config defaults for all types ---');

for (const [type, def] of Object.entries(assets)) {
    const cfg = w._getDefaultConfig(def);
    if (def.config) {
        for (const [key, spec] of Object.entries(def.config)) {
            assert(cfg[key] === spec.default, `${type} config ${key} default = ${spec.default}`);
        }
    }
}

// ============================================================
// Summary
// ============================================================

console.log(`\n========================================`);
console.log(`WAR EDITOR TESTS: ${passed} passed, ${failed} failed`);
console.log(`========================================\n`);

if (failed > 0) process.exit(1);
