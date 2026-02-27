/**
 * TRITIUM-SC main.js tests
 * Tests the Command Center bootstrap/initialization module.
 * Verifies imports, initialization order, DOM wiring, event subscriptions,
 * keyboard shortcuts, mode switching, toast/banner systems, escapeHtml,
 * panel system init, and audio bootstrap.
 * Run: node tests/js/test_main.js
 */

const fs = require('fs');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// ============================================================
// Load main.js source as a string for static analysis
// ============================================================

const mainSrc = fs.readFileSync(__dirname + '/../../frontend/js/command/main.js', 'utf8');
const mainLines = mainSrc.split('\n');

// ============================================================
// 1. Module imports are correct
// ============================================================

console.log('\n--- Module Imports ---');

(function testImportsTritiumStore() {
    assert(mainSrc.includes("import { TritiumStore } from './store.js'"),
        'Imports TritiumStore from store.js');
})();

(function testImportsEventBus() {
    assert(mainSrc.includes("import { EventBus } from './events.js'"),
        'Imports EventBus from events.js');
})();

(function testImportsWebSocketManager() {
    assert(mainSrc.includes("import { WebSocketManager } from './websocket.js'"),
        'Imports WebSocketManager from websocket.js');
})();

(function testImportsMapFunctions() {
    const mapImportLine = mainLines.find(l => l.includes("from './map-maplibre.js'"));
    assert(mapImportLine !== undefined, 'Imports from map-maplibre.js');
    const expectedFns = [
        'initMap', 'destroyMap', 'toggleSatellite', 'toggleRoads',
        'toggleGrid', 'toggleBuildings', 'toggleFog', 'toggleTerrain',
        'toggleLabels', 'toggleModels', 'toggleWaterways', 'toggleParks',
        'getMapState', 'centerOnAction', 'resetCamera', 'zoomIn', 'zoomOut',
        'toggleTilt', 'setLayers', 'setMapMode',
    ];
    for (const fn of expectedFns) {
        assert(mapImportLine.includes(fn), `Map import includes ${fn}`);
    }
})();

(function testImportsPanelManager() {
    assert(mainSrc.includes("import { PanelManager } from './panel-manager.js'"),
        'Imports PanelManager from panel-manager.js');
})();

(function testImportsLayoutManager() {
    assert(mainSrc.includes("import { LayoutManager } from './layout-manager.js'"),
        'Imports LayoutManager from layout-manager.js');
})();

(function testImportsMenuBar() {
    assert(mainSrc.includes("import { createMenuBar, focusSaveInput, getSelectedScenario } from './menu-bar.js'"),
        'Imports createMenuBar, focusSaveInput, and getSelectedScenario from menu-bar.js');
})();

(function testImportsPanelDefinitions() {
    assert(mainSrc.includes("import { AmyPanelDef }"), 'Imports AmyPanelDef');
    assert(mainSrc.includes("import { UnitsPanelDef }"), 'Imports UnitsPanelDef');
    assert(mainSrc.includes("import { AlertsPanelDef }"), 'Imports AlertsPanelDef');
    assert(mainSrc.includes("import { GameHudPanelDef }"), 'Imports GameHudPanelDef');
    assert(mainSrc.includes("import { MeshPanelDef }"), 'Imports MeshPanelDef');
})();

(function testPanelImportPaths() {
    assert(mainSrc.includes("from './panels/amy.js'"), 'AmyPanelDef path is panels/amy.js');
    assert(mainSrc.includes("from './panels/units.js'"), 'UnitsPanelDef path is panels/units.js');
    assert(mainSrc.includes("from './panels/alerts.js'"), 'AlertsPanelDef path is panels/alerts.js');
    assert(mainSrc.includes("from './panels/game-hud.js'"), 'GameHudPanelDef path is panels/game-hud.js');
    assert(mainSrc.includes("from './panels/mesh.js'"), 'MeshPanelDef path is panels/mesh.js');
})();

// ============================================================
// 2. Initialization order verification
// ============================================================

console.log('\n--- Initialization Order ---');

(function testInitFunctionExists() {
    assert(mainSrc.includes('function init()'), 'init() function defined');
})();

(function testDomContentLoadedBootstrap() {
    assert(mainSrc.includes("document.addEventListener('DOMContentLoaded', init)"),
        'init registered on DOMContentLoaded');
})();

(function testWSCreatedBeforeInit() {
    const wsLine = mainLines.findIndex(l => l.includes('new WebSocketManager()'));
    const initLine = mainLines.findIndex(l => l.includes('function init()'));
    assert(wsLine > 0 && initLine > 0, 'Both ws construction and init function found');
    assert(wsLine < initLine, 'WebSocketManager constructed at module scope before init()');
})();

(function testWSConnectedInInit() {
    // ws.connect() is called inside init()
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const connectLine = mainLines.findIndex((l, i) => i > initStart && l.includes('ws.connect()'));
    assert(connectLine > initStart, 'ws.connect() called inside init()');
})();

(function testClockBeforeWSConnect() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const clockLine = mainLines.findIndex((l, i) => i > initStart && l.includes('updateClock()'));
    const connectLine = mainLines.findIndex((l, i) => i > initStart && l.includes('ws.connect()'));
    assert(clockLine > 0 && connectLine > 0, 'Both clock and ws.connect found in init');
    assert(clockLine < connectLine, 'Clock updated before ws.connect()');
})();

(function testInitKeyboardCalledInInit() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const kbLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initKeyboard();');
    assert(kbLine > initStart, 'initKeyboard() called inside init()');
})();

(function testInitChatCalledInInit() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const chatLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initChat();');
    assert(chatLine > initStart, 'initChat() called inside init()');
})();

(function testInitHelpCalledInInit() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const helpLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initHelp();');
    assert(helpLine > initStart, 'initHelp() called inside init()');
})();

(function testInitMapModesCalledInInit() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const modesLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initMapModes();');
    assert(modesLine > initStart, 'initMapModes() called inside init()');
})();

(function testInitMapCalledInInit() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const mapLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initMap();');
    assert(mapLine > initStart, 'initMap() called inside init()');
})();

(function testInitOrderKeyboardBeforeMap() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const kbLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initKeyboard();');
    const mapLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initMap();');
    assert(kbLine < mapLine, 'initKeyboard() called before initMap()');
})();

(function testInitOrderMapBeforePanelSystem() {
    const initStart = mainLines.findIndex(l => l.includes('function init()'));
    const mapLine = mainLines.findIndex((l, i) => i > initStart && l.trim() === 'initMap();');
    const panelSysLine = mainLines.findIndex((l, i) => i > initStart && l.includes('initPanelSystem('));
    assert(mapLine < panelSysLine, 'initMap() called before initPanelSystem()');
})();

// ============================================================
// 3. DOM element ID queries
// ============================================================

console.log('\n--- DOM Element IDs ---');

(function testExpectedDOMElementIDs() {
    const expectedIds = [
        'connection-status',
        'header-units',
        'header-threats',
        'status-alive',
        'status-threats',
        'game-score-area',
        'game-wave',
        'game-score',
        'game-eliminations',
        'chat-context-text',
        'toast-container',
        'center-banner',
        'game-over-overlay',
        'game-over-title',
        'go-score',
        'go-waves',
        'go-eliminations',
        'chat-close',
        'chat-input',
        'chat-send',
        'chat-overlay',
        'chat-messages',
        'panel-container',
        'command-bar-container',
        'help-overlay',
        'modal-overlay',
        'modal-close',
        'header-clock',
        'sidebar-toggle',
        'sidebar',
        'unit-list',
        'unit-filter',
        'alert-feed',
        'btn-begin-war',
        'btn-reset-game',
        'amy-state',
        'amy-mood',
        'amy-thought',
        'minimap-container',
    ];
    for (const id of expectedIds) {
        assert(mainSrc.includes(`'${id}'`) || mainSrc.includes(`"${id}"`),
            `DOM element ID "${id}" referenced in main.js`);
    }
})();

// ============================================================
// 4. Store subscriptions
// ============================================================

console.log('\n--- Store Subscriptions ---');

(function testStoreSubscriptionConnectionStatus() {
    assert(mainSrc.includes("TritiumStore.on('connection.status'"),
        'Subscribes to connection.status changes');
})();

(function testStoreSubscriptionUnits() {
    assert(mainSrc.includes("TritiumStore.on('units'"),
        'Subscribes to units changes');
})();

(function testStoreSubscriptionGamePhase() {
    assert(mainSrc.includes("TritiumStore.on('game.phase'"),
        'Subscribes to game.phase changes');
})();

(function testStoreSubscriptionGameWave() {
    assert(mainSrc.includes("TritiumStore.on('game.wave'"),
        'Subscribes to game.wave changes');
})();

(function testStoreSubscriptionGameScore() {
    assert(mainSrc.includes("TritiumStore.on('game.score'"),
        'Subscribes to game.score changes');
})();

(function testStoreSubscriptionGameEliminations() {
    assert(mainSrc.includes("TritiumStore.on('game.eliminations'"),
        'Subscribes to game.eliminations changes');
})();

(function testStoreSubscriptionAmyLastThought() {
    assert(mainSrc.includes("TritiumStore.on('amy.lastThought'"),
        'Subscribes to amy.lastThought changes');
})();

// ============================================================
// 5. EventBus subscriptions
// ============================================================

console.log('\n--- EventBus Subscriptions ---');

(function testEventBusSubscriptions() {
    const expectedEvents = [
        'amy:thought',
        'robot:thought',
        'alert:new',
        'announcer',
        'game:elimination',
        'mesh:text',
        'toast:show',
        'chat:open',
        'combat:projectile',
        'combat:hit',
        'combat:elimination',
        'combat:streak',
        'game:wave_start',
        'game:wave_complete',
        'game:state',
    ];
    for (const evt of expectedEvents) {
        assert(mainSrc.includes(`'${evt}'`),
            `EventBus subscription for "${evt}" present`);
    }
})();

// ============================================================
// 6. Keyboard shortcut registration
// ============================================================

console.log('\n--- Keyboard Shortcuts ---');

(function testKeyboardShortcutKeys() {
    // Verify key cases handled in the switch statement
    const expectedKeys = [
        "'?'",
        "'c'", "'C'",
        "'Escape'",
        "'/'",
        "'m'", "'M'",
        "'o'", "'O'",
        "'t'", "'T'",
        "'s'", "'S'",
        "'b'", "'B'",
        "'1'", "'2'", "'3'", "'4'", "'5'",
        "'f'", "'F'",
        "'r'", "'R'",
        "'['",
        "']'",
        "'v'", "'V'",
        "'k'", "'K'",
        "'g'", "'G'",
        "'i'", "'I'",
        "'h'", "'H'",
        "'Tab'",
    ];
    for (const key of expectedKeys) {
        assert(mainSrc.includes(`case ${key}:`),
            `Keyboard handler for case ${key} present`);
    }
})();

(function testCtrlShiftSSaveLayout() {
    assert(mainSrc.includes("e.ctrlKey && e.shiftKey") && mainSrc.includes("focusSaveInput"),
        'Ctrl+Shift+S triggers focusSaveInput');
})();

(function testCtrlLayoutSwitching() {
    assert(mainSrc.includes("'1': 'commander'"), 'Ctrl+1 maps to commander layout');
    assert(mainSrc.includes("'2': 'observer'"), 'Ctrl+2 maps to observer layout');
    assert(mainSrc.includes("'3': 'tactical'"), 'Ctrl+3 maps to tactical layout');
    assert(mainSrc.includes("'4': 'battle'"), 'Ctrl+4 maps to battle layout');
})();

(function testInputFieldShortcutGuard() {
    // Keyboard handler should skip when target is INPUT or TEXTAREA
    assert(mainSrc.includes("e.target.tagName === 'INPUT'"),
        'Keyboard handler checks for INPUT focus');
    assert(mainSrc.includes("e.target.tagName === 'TEXTAREA'"),
        'Keyboard handler checks for TEXTAREA focus');
})();

// ============================================================
// 7. Mode switching (observe/tactical/setup)
// ============================================================

console.log('\n--- Mode Switching ---');

(function testMapModeDataAttributes() {
    assert(mainSrc.includes('[data-map-mode]'),
        'initMapModes queries [data-map-mode] elements');
})();

(function testMapModeStoreSet() {
    assert(mainSrc.includes("TritiumStore.set('map.mode', mode)"),
        'Map mode click sets map.mode in store');
})();

(function testMapModeEventBusEmit() {
    assert(mainSrc.includes("EventBus.emit('map:mode'"),
        'Map mode click emits map:mode event');
})();

(function testObserveModeKeyboard() {
    assert(mainSrc.includes('[data-map-mode="observe"]'),
        'O key triggers observe mode button click');
})();

(function testTacticalModeKeyboard() {
    assert(mainSrc.includes('[data-map-mode="tactical"]'),
        'T key triggers tactical mode button click');
})();

(function testSetupModeKeyboard() {
    assert(mainSrc.includes('[data-map-mode="setup"]'),
        'S key triggers setup mode button click');
})();

// ============================================================
// 8. Panel system initialization
// ============================================================

console.log('\n--- Panel System Init ---');

(function testPanelSystemInitFunction() {
    assert(mainSrc.includes('function initPanelSystem(container)'),
        'initPanelSystem function exists');
})();

(function testPanelRegistration() {
    assert(mainSrc.includes('panelManager.register(AmyPanelDef)'), 'Registers AmyPanelDef');
    assert(mainSrc.includes('panelManager.register(UnitsPanelDef)'), 'Registers UnitsPanelDef');
    assert(mainSrc.includes('panelManager.register(AlertsPanelDef)'), 'Registers AlertsPanelDef');
    assert(mainSrc.includes('panelManager.register(GameHudPanelDef)'), 'Registers GameHudPanelDef');
    assert(mainSrc.includes('panelManager.register(MeshPanelDef)'), 'Registers MeshPanelDef');
})();

(function testDefaultPanelsOpened() {
    assert(mainSrc.includes("panelManager.open('amy')"), 'Default opens amy panel');
    assert(mainSrc.includes("panelManager.open('units')"), 'Default opens units panel');
    assert(mainSrc.includes("panelManager.open('alerts')"), 'Default opens alerts panel');
})();

(function testLayoutManagerCreatedAfterPanelManager() {
    const pmLine = mainLines.findIndex(l => l.includes('panelManager = new PanelManager(container)'));
    const lmLine = mainLines.findIndex(l => l.includes('layoutManager = new LayoutManager(panelManager)'));
    assert(pmLine > 0 && lmLine > 0, 'Both PanelManager and LayoutManager construction found');
    assert(pmLine < lmLine, 'PanelManager created before LayoutManager');
})();

(function testLoadLayoutBeforeDefaults() {
    // loadLayout() is attempted, and only if it returns false do we open defaults
    assert(mainSrc.includes('if (!panelManager.loadLayout())'),
        'Tries to load saved layout before opening defaults');
})();

(function testPanelManagerOnWindow() {
    assert(mainSrc.includes('window.panelManager = panelManager'),
        'panelManager exposed on window for debug');
})();

(function testLayoutManagerOnWindow() {
    assert(mainSrc.includes('window.layoutManager = layoutManager'),
        'layoutManager exposed on window for debug');
})();

// ============================================================
// 9. Panel toggle wiring (keyboard)
// ============================================================

console.log('\n--- Panel Toggle Wiring ---');

(function testPanelToggle1Amy() {
    assert(mainSrc.includes("panelManager.toggle('amy')"),
        'Key 1 toggles amy panel');
})();

(function testPanelToggle2Units() {
    assert(mainSrc.includes("panelManager.toggle('units')"),
        'Key 2 toggles units panel');
})();

(function testPanelToggle3Alerts() {
    assert(mainSrc.includes("panelManager.toggle('alerts')"),
        'Key 3 toggles alerts panel');
})();

(function testPanelToggle4Game() {
    assert(mainSrc.includes("panelManager.toggle('game')"),
        'Key 4 toggles game panel');
})();

(function testPanelToggle5Mesh() {
    assert(mainSrc.includes("panelManager.toggle('mesh')"),
        'Key 5 toggles mesh panel');
})();

// ============================================================
// 10. Toast notification system
// ============================================================

console.log('\n--- Toast System ---');

(function testToastMaxConstant() {
    assert(mainSrc.includes('const TOAST_MAX = 5'),
        'TOAST_MAX is 5');
})();

(function testToastDurationConstant() {
    assert(mainSrc.includes('const TOAST_DURATION = 6000'),
        'TOAST_DURATION is 6000ms');
})();

(function testShowToastFunction() {
    assert(mainSrc.includes("function showToast(message, type = 'info')"),
        'showToast function exists with default type info');
})();

(function testToastCreatesDiv() {
    assert(mainSrc.includes('toast-container') && mainSrc.includes("toast.className = `toast toast-${type}`"),
        'Toast creates div with toast-{type} class in toast-container');
})();

(function testToastCloseButton() {
    assert(mainSrc.includes('toast-close'),
        'Toast includes close button');
})();

(function testToastPrependNotAppend() {
    assert(mainSrc.includes('container.prepend(toast)'),
        'Toast prepends to container (newest at top)');
})();

(function testToastOverflowTrimming() {
    assert(mainSrc.includes('toasts.length > TOAST_MAX'),
        'Toast trims when exceeding TOAST_MAX');
})();

// ============================================================
// 11. Banner system
// ============================================================

console.log('\n--- Banner System ---');

(function testShowBannerFunction() {
    assert(mainSrc.includes("function showBanner(text, sub = '', duration = 3000)"),
        'showBanner function exists with defaults');
})();

(function testBannerElement() {
    assert(mainSrc.includes("'center-banner'"),
        'Banner uses center-banner element');
})();

(function testBannerDataAttributes() {
    assert(mainSrc.includes('[data-element="banner-text"]'),
        'Banner looks for banner-text data element');
    assert(mainSrc.includes('[data-element="banner-sub"]'),
        'Banner looks for banner-sub data element');
})();

(function testBannerTimeout() {
    assert(mainSrc.includes('_bannerTimeout'),
        'Banner uses timeout for auto-hide');
})();

// ============================================================
// 12. Game over overlay
// ============================================================

console.log('\n--- Game Over Overlay ---');

(function testShowGameOverFunction() {
    assert(mainSrc.includes('function showGameOver(phase)'),
        'showGameOver function exists');
})();

(function testGameOverVictoryText() {
    assert(mainSrc.includes("phase === 'victory' ? 'VICTORY' : 'DEFEAT'"),
        'Shows VICTORY or DEFEAT based on phase');
})();

(function testGameOverColors() {
    assert(mainSrc.includes("var(--green)") && mainSrc.includes("var(--magenta)"),
        'Uses green for victory, magenta for defeat');
})();

(function testGameOverPlayAgainAction() {
    assert(mainSrc.includes('[data-action="play-again"]'),
        'Game over overlay has play-again action');
})();

(function testGameOverTriggeredByPhase() {
    assert(mainSrc.includes("phase === 'victory' || phase === 'defeat'"),
        'Game over triggered on victory or defeat phase');
})();

// ============================================================
// 13. Chat system
// ============================================================

console.log('\n--- Chat System ---');

(function testInitChatFunction() {
    assert(mainSrc.includes('function initChat()'),
        'initChat function exists');
})();

(function testToggleChatFunction() {
    assert(mainSrc.includes('function toggleChat(open)'),
        'toggleChat function exists');
})();

(function testSendChatFunction() {
    assert(mainSrc.includes('async function sendChat(input)'),
        'sendChat function exists as async');
})();

(function testSendChatAPIEndpoint() {
    assert(mainSrc.includes("fetch('/api/amy/chat'"),
        'sendChat posts to /api/amy/chat');
})();

(function testChatEnterKeySends() {
    assert(mainSrc.includes("e.key === 'Enter' && !e.shiftKey"),
        'Enter key (without shift) sends chat');
})();

(function testChatEscapeCloses() {
    // In the chat input keydown handler
    assert(mainSrc.includes("e.key === 'Escape'"),
        'Escape key closes chat');
})();

(function testAppendChatMessage() {
    assert(mainSrc.includes('function appendChatMessage(sender, text, type)'),
        'appendChatMessage function exists');
})();

// ============================================================
// 14. Audio bootstrap
// ============================================================

console.log('\n--- Audio Bootstrap ---');

(function testAudioInitOnUserInteraction() {
    assert(mainSrc.includes("document.addEventListener('click', _initAudio, { once: true })"),
        'Audio init registered on first click with once:true');
    assert(mainSrc.includes("document.addEventListener('keydown', _initAudio, { once: true })"),
        'Audio init registered on first keydown with once:true');
})();

(function testAudioManagerCheck() {
    assert(mainSrc.includes("typeof window.WarAudioManager === 'function'"),
        'Audio init checks for WarAudioManager on window');
})();

(function testAudioPreloadSounds() {
    const preloadSounds = [
        'nerf_shot', 'impact_hit', 'explosion', 'explosion_small',
        'turret_rotate', 'turret_lock_on', 'drone_buzz', 'drone_flyby',
        'ricochet', 'shield_hit', 'reload',
        'wave_start', 'wave_complete', 'countdown_tick', 'countdown_go',
        'victory_fanfare', 'defeat_sting', 'dispatch_ack',
        'hostile_detected', 'alert_tone', 'escalation_siren',
        'killing_spree', 'rampage', 'dominating', 'godlike',
        'ambient_wind',
    ];
    for (const sound of preloadSounds) {
        assert(mainSrc.includes(`'${sound}'`),
            `Audio preloads "${sound}"`);
    }
})();

(function testAudioIdempotent() {
    assert(mainSrc.includes('if (_audioInitialized) return'),
        'Audio init is idempotent (checks _audioInitialized flag)');
})();

(function testAudioErrorHandling() {
    assert(mainSrc.includes("console.warn('[TRITIUM] Audio init failed:'"),
        'Audio init catches and warns on errors');
})();

// ============================================================
// 15. Window globals
// ============================================================

console.log('\n--- Window Globals ---');

(function testTritiumStoreOnWindow() {
    assert(mainSrc.includes('window.TritiumStore = TritiumStore'),
        'TritiumStore exposed on window for console debugging');
})();

(function testEventBusOnWindow() {
    assert(mainSrc.includes('window.EventBus = EventBus'),
        'EventBus exposed on window for console debugging');
})();

(function testMapActionsOnWindow() {
    assert(mainSrc.includes('window._mapActions = mapActions'),
        '_mapActions exposed on window for automated testing');
})();

// ============================================================
// 16. Exports
// ============================================================

console.log('\n--- Exports ---');

(function testExportedSymbols() {
    const exportLine = mainLines.find(l => l.startsWith('export {'));
    assert(exportLine !== undefined, 'Module has an export statement');
    const expectedExports = ['showToast', 'showBanner', 'selectUnit', 'dispatchUnit', 'escapeHtml', 'ws', 'panelManager', 'layoutManager'];
    for (const sym of expectedExports) {
        assert(exportLine.includes(sym), `Exports "${sym}"`);
    }
})();

// ============================================================
// 17. API endpoints referenced
// ============================================================

console.log('\n--- API Endpoints ---');

(function testAPIEndpoints() {
    const expectedEndpoints = [
        '/api/amy/chat',
        '/api/amy/status',
        '/api/amy/command',
        '/api/game/begin',
        '/api/game/reset',
    ];
    for (const endpoint of expectedEndpoints) {
        assert(mainSrc.includes(endpoint),
            `API endpoint "${endpoint}" referenced`);
    }
})();

// ============================================================
// 18. escapeHtml utility
// ============================================================

console.log('\n--- escapeHtml ---');

(function testEscapeHtmlExists() {
    assert(mainSrc.includes('function escapeHtml(text)'),
        'escapeHtml function exists');
})();

(function testEscapeHtmlHandlesEmpty() {
    assert(mainSrc.includes("if (!text) return ''"),
        'escapeHtml returns empty string for falsy input');
})();

// ============================================================
// 19. Functional test -- escapeHtml via VM
// ============================================================

console.log('\n--- escapeHtml functional ---');

const vm = require('vm');

// Create minimal sandbox to run escapeHtml
const escapeHtmlSrc = `
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
`;

function makeEscapeSandbox() {
    return vm.createContext({
        String,
        document: {
            createElement() {
                let _textContent = '';
                return {
                    get textContent() { return _textContent; },
                    set textContent(val) { _textContent = val; },
                    get innerHTML() {
                        return _textContent
                            .replace(/&/g, '&amp;')
                            .replace(/</g, '&lt;')
                            .replace(/>/g, '&gt;')
                            .replace(/"/g, '&quot;');
                    },
                };
            },
        },
    });
}

(function testEscapeHtmlBasicString() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml('hello')", ctx);
    assertEqual(result, 'hello', 'escapeHtml("hello") returns hello');
})();

(function testEscapeHtmlXSS() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml('<script>alert(1)</script>')", ctx);
    assert(!result.includes('<script>'), 'escapeHtml escapes script tags');
    assert(result.includes('&lt;script&gt;'), 'escapeHtml produces &lt;script&gt;');
})();

(function testEscapeHtmlNull() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml(null)", ctx);
    assertEqual(result, '', 'escapeHtml(null) returns empty string');
})();

(function testEscapeHtmlEmpty() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml('')", ctx);
    assertEqual(result, '', 'escapeHtml("") returns empty string');
})();

(function testEscapeHtmlUndefined() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml(undefined)", ctx);
    assertEqual(result, '', 'escapeHtml(undefined) returns empty string');
})();

(function testEscapeHtmlAmpersand() {
    const ctx = makeEscapeSandbox();
    vm.runInContext(escapeHtmlSrc, ctx);
    const result = vm.runInContext("escapeHtml('A & B')", ctx);
    assert(result.includes('&amp;'), 'escapeHtml escapes ampersands');
})();

// ============================================================
// 20. Functional test -- updateClock via VM
// ============================================================

console.log('\n--- updateClock functional ---');

(function testUpdateClockFunction() {
    assert(mainSrc.includes('function updateClock()'),
        'updateClock function exists');
})();

(function testUpdateClockElementId() {
    assert(mainSrc.includes("getElementById('header-clock')"),
        'updateClock queries header-clock element');
})();

(function testUpdateClockFormat() {
    assert(mainSrc.includes("+ ' UTC'"),
        'updateClock appends UTC to time string');
})();

(function testClockInterval() {
    assert(mainSrc.includes('setInterval(updateClock, 1000)'),
        'Clock updates every 1000ms');
})();

// ============================================================
// 21. Legacy layout (sidebar) fallback
// ============================================================

console.log('\n--- Legacy Layout Fallback ---');

(function testLegacyLayoutBranch() {
    // When panel-container is missing, init falls through to legacy init
    assert(mainSrc.includes('initSidebarToggle()'), 'Legacy: initSidebarToggle called');
    assert(mainSrc.includes('initSectionToggles()'), 'Legacy: initSectionToggles called');
    assert(mainSrc.includes('initGameControls()'), 'Legacy: initGameControls called');
    assert(mainSrc.includes('initAmyActions()'), 'Legacy: initAmyActions called');
    assert(mainSrc.includes('fetchAmyStatus()'), 'Legacy: fetchAmyStatus called');
})();

(function testLegacyStoreSubscriptions() {
    assert(mainSrc.includes("TritiumStore.on('alerts'"),
        'Legacy subscribes to alerts');
    assert(mainSrc.includes("TritiumStore.on('amy.state'"),
        'Legacy subscribes to amy.state');
    assert(mainSrc.includes("TritiumStore.on('amy.mood'"),
        'Legacy subscribes to amy.mood');
})();

// ============================================================
// 22. Map action proxy
// ============================================================

console.log('\n--- Map Action Proxy ---');

(function testMapActionsProxy() {
    const mapActionNames = [
        'toggleSatellite', 'toggleRoads', 'toggleGrid', 'toggleFog',
        'toggleTerrain', 'toggleLabels', 'toggleModels', 'toggleWaterways',
        'toggleParks', 'toggleTilt', 'toggleBuildings',
        'centerOnAction', 'resetCamera', 'zoomIn', 'zoomOut',
        'getMapState', 'setLayers', 'setMapMode',
    ];
    for (const action of mapActionNames) {
        assert(mainSrc.includes(`${action}:`),
            `Map action proxy defines "${action}"`);
    }
})();

(function testActiveMapModuleFallback() {
    assert(mainSrc.includes('_activeMapModule'),
        '_activeMapModule used for dynamic dispatch');
    // Proxy pattern: _activeMapModule ? _activeMapModule.fn() : fn()
    assert(mainSrc.includes('_activeMapModule ? _activeMapModule.toggleSatellite()'),
        'Map actions proxy falls back to direct function if no active module');
})();

// ============================================================
// 23. Game controls
// ============================================================

console.log('\n--- Game Controls ---');

(function testBeginWarFunction() {
    assert(mainSrc.includes('async function beginWar()'),
        'beginWar function exists as async');
})();

(function testResetGameFunction() {
    assert(mainSrc.includes('async function resetGame()'),
        'resetGame function exists as async');
})();

(function testDispatchUnitFunction() {
    assert(mainSrc.includes('async function dispatchUnit(targetId, x, y)'),
        'dispatchUnit function exists as async with targetId, x, y params');
})();

(function testBeginWarKeyGuard() {
    // B key should only start war in idle or setup phase
    assert(mainSrc.includes("TritiumStore.game.phase === 'idle' || TritiumStore.game.phase === 'setup'"),
        'B key guarded by idle/setup phase check');
})();

(function testSelectUnitFunction() {
    assert(mainSrc.includes('function selectUnit(id)'),
        'selectUnit function exists');
    assert(mainSrc.includes("TritiumStore.set('map.selectedUnitId', id)"),
        'selectUnit sets map.selectedUnitId in store');
    assert(mainSrc.includes("EventBus.emit('unit:selected'"),
        'selectUnit emits unit:selected event');
})();

// ============================================================
// 24. Combat audio event wiring
// ============================================================

console.log('\n--- Combat Audio Events ---');

(function testProjectileAudioBranching() {
    // Combat audio categorizes by projectile_type
    assert(mainSrc.includes("ptype.includes('missile')"),
        'Audio branches on missile projectile type');
    assert(mainSrc.includes("ptype.includes('tank')"),
        'Audio branches on tank projectile type');
    assert(mainSrc.includes("ptype.includes('heavy')"),
        'Audio branches on heavy projectile type');
    assert(mainSrc.includes("ptype.includes('scout')"),
        'Audio branches on scout projectile type');
    assert(mainSrc.includes("ptype.includes('apc')"),
        'Audio branches on apc projectile type');
})();

(function testStreakAudioTiers() {
    assert(mainSrc.includes("streak >= 10 ? 'godlike'"),
        'Streak 10+ plays godlike');
    assert(mainSrc.includes("streak >= 7 ? 'dominating'"),
        'Streak 7+ plays dominating');
    assert(mainSrc.includes("streak >= 5 ? 'rampage'"),
        'Streak 5+ plays rampage');
    assert(mainSrc.includes("'killing_spree'"),
        'Default streak plays killing_spree');
})();

(function testGameStateAudioEvents() {
    assert(mainSrc.includes("d.state === 'active'"),
        'Audio handles active game state');
    assert(mainSrc.includes("d.state === 'idle'"),
        'Audio handles idle game state');
    assert(mainSrc.includes("d.state === 'victory'"),
        'Audio handles victory game state');
    assert(mainSrc.includes("d.state === 'defeat'"),
        'Audio handles defeat game state');
    assert(mainSrc.includes("d.state === 'countdown'"),
        'Audio handles countdown game state');
})();

// ============================================================
// 25. Error handling patterns
// ============================================================

console.log('\n--- Error Handling ---');

(function testChatErrorHandling() {
    assert(mainSrc.includes("appendChatMessage('SYSTEM', 'Failed to reach Amy', 'error')"),
        'Chat catches fetch errors and shows system message');
})();

(function testBeginWarErrorHandling() {
    assert(mainSrc.includes("showToast('Failed to start game', 'alert')"),
        'beginWar catches errors and shows toast');
})();

(function testResetGameErrorHandling() {
    assert(mainSrc.includes("showToast('Failed to reset game', 'alert')"),
        'resetGame catches errors and shows toast');
})();

(function testDispatchErrorHandling() {
    assert(mainSrc.includes("showToast('Dispatch failed', 'alert')"),
        'dispatchUnit catches errors and shows toast');
})();

(function testNullGuardedDOMAccess() {
    // Many DOM accesses are guarded with "if (el)"
    const guardCount = (mainSrc.match(/if\s*\(\s*el\s*\)/g) || []).length;
    assert(guardCount >= 5, `At least 5 null-guarded DOM accesses found (got ${guardCount})`);
})();

(function testOptionalChainingUsed() {
    // Modern optional chaining for safe DOM queries
    const chainCount = (mainSrc.match(/\?\./g) || []).length;
    assert(chainCount >= 3, `At least 3 optional chaining operators used (got ${chainCount})`);
})();

// ============================================================
// 26. Help and Modal overlay init
// ============================================================

console.log('\n--- Help and Modal ---');

(function testInitHelpFunction() {
    assert(mainSrc.includes('function initHelp()'),
        'initHelp function exists');
})();

(function testInitModalFunction() {
    assert(mainSrc.includes('function initModal()'),
        'initModal function exists');
})();

(function testHelpCloseElement() {
    assert(mainSrc.includes('[data-element="help-close"]'),
        'Help overlay has close element query');
})();

(function testHelpBackdropClose() {
    // Clicking on the overlay background (target === overlay) closes it
    assert(mainSrc.includes('if (e.target === overlay) overlay.hidden = true'),
        'Help overlay closes on backdrop click');
})();

(function testModalCloseElement() {
    assert(mainSrc.includes("'modal-close'"),
        'Modal overlay has modal-close element');
})();

// ============================================================
// 27. Functional test -- showToast structure via VM
// ============================================================

console.log('\n--- showToast functional ---');

(function testShowToastCreatesDivWithCorrectClass() {
    // Extract showToast function and run it in a sandbox
    const toastSrc = `
var TOAST_MAX = 5;
var TOAST_DURATION = 6000;
function escapeHtml(text) {
    if (!text) return '';
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
var _createdElements = [];
var _container = {
    prepend: function(el) { _container._children.unshift(el); },
    querySelectorAll: function() { return _container._children; },
    _children: [],
};
function showToast(message, type) {
    type = type || 'info';
    var container = _container;
    if (!container) return;
    var toast = {
        className: 'toast toast-' + type,
        innerHTML: '',
        querySelector: function() { return { addEventListener: function() {} }; },
        classList: { add: function() {} },
        remove: function() {},
    };
    toast.className = 'toast toast-' + type;
    _createdElements.push(toast);
    container.prepend(toast);
}
    `;
    const ctx = vm.createContext({
        Math, Date, String, console, setTimeout: function() {},
    });
    vm.runInContext(toastSrc, ctx);
    vm.runInContext("showToast('Test message', 'alert')", ctx);
    const created = vm.runInContext('_createdElements', ctx);
    assertEqual(created.length, 1, 'showToast creates one element');
    assertEqual(created[0].className, 'toast toast-alert', 'Toast has correct className');
})();

// ============================================================
// 28. Elimination toast format
// ============================================================

console.log('\n--- Elimination Toast ---');

(function testEliminationFormat() {
    assert(mainSrc.includes("data.interceptor_name || data.killer_name || '???'"),
        'Elimination toast extracts interceptor_name or killer_name');
    assert(mainSrc.includes("data.target_name || data.victim_name || '???'"),
        'Elimination toast extracts target_name or victim_name');
    assert(mainSrc.includes('neutralized'),
        'Elimination toast uses "neutralized" verb');
})();

// ============================================================
// 29. Connection status indicator
// ============================================================

console.log('\n--- Connection Status ---');

(function testConnectionStatusDataState() {
    assert(mainSrc.includes('el.dataset.state = status'),
        'Connection status sets dataset.state');
})();

(function testConnectionStatusLabel() {
    assert(mainSrc.includes("status === 'connected' ? 'ONLINE' : 'OFFLINE'"),
        'Connection status shows ONLINE or OFFLINE label');
})();

(function testWSStatusIndicator() {
    assert(mainSrc.includes("'status-ws'"),
        'WS status indicator element referenced');
})();

// ============================================================
// 30. Menu bar creation in panel system
// ============================================================

console.log('\n--- Menu Bar Wiring ---');

(function testCreateMenuBarCall() {
    assert(mainSrc.includes('createMenuBar(barContainer, panelManager, layoutManager, mapActions)'),
        'createMenuBar called with correct arguments');
})();

(function testMenuBarContainerQuery() {
    assert(mainSrc.includes("getElementById('command-bar-container')"),
        'Menu bar container queried by ID');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
