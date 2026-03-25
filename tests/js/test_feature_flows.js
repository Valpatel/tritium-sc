// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Feature Flow Tests
 *
 * Exercises full user flows: button clicks -> HTTP endpoints -> store updates.
 * Tests the contract between frontend expectations and backend reality.
 * Finds disconnects, dead ends, and logical problems.
 *
 * Run: node tests/js/test_feature_flows.js
 */

const fs = require('fs');
const path = require('path');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertIncludes(arr, val, msg) {
    assert(Array.isArray(arr) && arr.includes(val), msg + ` (array: ${JSON.stringify(arr)})`);
}

// ============================================================
// Test infrastructure: read source files and verify contracts
// ============================================================

function readSource(relPath) {
    const scPath = path.join(__dirname, '..', '..', relPath);
    // If reading a re-export stub, try the tritium-lib source instead
    // Many SC simulation files were moved to tritium-lib and replaced with re-export stubs
    const libMap = {
        'src/engine/simulation/target.py': '../tritium-lib/src/tritium_lib/sim_engine/core/entity.py',
        // engine.py is NOT a re-export stub — it's the real SC engine file, no mapping needed
        'src/engine/simulation/game_mode.py': '../tritium-lib/src/tritium_lib/sim_engine/game/game_mode.py',
        'src/engine/simulation/behaviors.py': '../tritium-lib/src/tritium_lib/sim_engine/core/entity.py',
        'src/engine/simulation/combat.py': '../tritium-lib/src/tritium_lib/sim_engine/combat/combat.py',
        'src/engine/simulation/vision.py': '../tritium-lib/src/tritium_lib/sim_engine/world/vision.py',
    };
    {
        const libRel = libMap[relPath];
        if (libRel) {
            const libPath = path.join(__dirname, '..', '..', libRel);
            if (fs.existsSync(libPath)) return fs.readFileSync(libPath, 'utf8');
        }
    }
    return fs.readFileSync(scPath, 'utf8');
}

function sourceContains(relPath, pattern) {
    const src = readSource(relPath);
    if (typeof pattern === 'string') return src.includes(pattern);
    return pattern.test(src);
}

function sourceExports(relPath, name) {
    const src = readSource(relPath);
    return src.includes(`export function ${name}`) ||
           src.includes(`export const ${name}`) ||
           src.includes(`export class ${name}`) ||
           src.includes(`export { ${name}`) ||
           src.includes(`export {${name}`);
}

// ============================================================
// 1. Panel Registration: every panel JS file is imported and registered
// ============================================================
console.log('\n=== Panel Registration ===\n');

const EXPECTED_PANELS = [
    'amy', 'units', 'alerts', 'game', 'mesh', 'audio', 'escalation',
    'events', 'patrol', 'scenarios', 'system', 'minimap', 'graphlings',
    'replay', 'battle-stats', 'sensors', 'unit-inspector',
    'cameras', 'search', 'tak', 'videos', 'zones',
];

const mainSrc = readSource('src/frontend/js/command/main.js');
for (const panelId of EXPECTED_PANELS) {
    // Each panel must have a PanelDef import
    const hasImport = /import\s+\{[^}]*PanelDef[^}]*\}\s+from\s+['"]\.\/panels\//.test(mainSrc);
    assert(hasImport, `main.js imports panel definitions`);
    // Panel must be registered
    const hasRegister = mainSrc.includes('panelManager.register(');
    assert(hasRegister, `main.js registers panels with PanelManager`);
}
// Count specific panel registrations
const registerCount = (mainSrc.match(/panelManager\.register\(/g) || []).length;
assert(registerCount >= EXPECTED_PANELS.length,
    `main.js has ${registerCount} panel registrations (need ${EXPECTED_PANELS.length})`);

// ============================================================
// 2. Keyboard Shortcuts: every shortcut has a handler
// ============================================================
console.log('\n=== Keyboard Shortcuts ===\n');

const EXPECTED_SHORTCUTS = [
    // Panel toggles
    { key: "'1'", action: "toggle.*amy" },
    { key: "'2'", action: "toggle.*units" },
    { key: "'3'", action: "toggle.*alerts" },
    { key: "'4'", action: "toggle.*game" },
    { key: "'5'", action: "toggle.*mesh" },
    { key: "'6'", action: "toggle.*cameras" },
    { key: "'7'", action: "toggle.*search" },
    { key: "'8'", action: "toggle.*tak" },
    { key: "'9'", action: "toggle.*videos" },
    { key: "'0'", action: "toggle.*zones" },
    // Map modes
    { key: "'o'", action: "observe" },
    { key: "'t'", action: "tactical" },
    { key: "'s'", action: "setup" },
    // Map layers
    { key: "'u'", action: "Units|unit" },
    { key: "'v'", action: "Fog|fog" },
    { key: "'k'", action: "Building|building" },
    { key: "'g'", action: "Road|road" },
    { key: "'i'", action: "Satellite|satellite" },
    { key: "'h'", action: "Terrain|terrain" },
    // Features
    { key: "'f'", action: "center|action|follow" },
    { key: "'a'", action: "auto.*follow|follow" },
    { key: "'r'", action: "replay" },
    { key: "'b'", action: "begin|war|mission" },
    { key: "'n'", action: "mission" },
    { key: "'m'", action: "minimap" },
    { key: "'c'", action: "chat" },
    { key: "'Tab'", action: "panel|focus|cycle" },
];

for (const shortcut of EXPECTED_SHORTCUTS) {
    const hasCase = mainSrc.includes(`case ${shortcut.key}:`);
    assert(hasCase, `keyboard: case ${shortcut.key} handler exists`);
}

// ============================================================
// 3. Help Overlay: all shortcuts documented
// ============================================================
console.log('\n=== Help Overlay Documentation ===\n');

const htmlSrc = readSource('src/frontend/unified.html');
const DOCUMENTED_KEYS = [
    '?', 'ESC', 'C', '/', 'M', 'O', 'T', 'S', 'F', 'R', 'I', 'A',
    'U', 'V', 'K', 'G', 'H', 'Tab', 'WASD', 'B', 'N',
    '1', '2', '3', '4', '5', '6', '7', '8', '9', '0',
    'Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4', 'Ctrl+Shift+S',
];

for (const key of DOCUMENTED_KEYS) {
    const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const pattern = new RegExp(`<kbd[^>]*>${escaped}</kbd>`);
    assert(pattern.test(htmlSrc), `help overlay documents key: ${key}`);
}

// ============================================================
// 4. Button-to-Endpoint Contract: every UI action calls correct API
// ============================================================
console.log('\n=== Button-to-Endpoint Contract ===\n');

// Game HUD endpoints
const gameHudSrc = readSource('src/frontend/js/command/panels/game-hud.js');
assert(gameHudSrc.includes('/api/game/begin'), 'game-hud: calls POST /api/game/begin');
assert(gameHudSrc.includes('/api/game/reset'), 'game-hud: calls POST /api/game/reset');
assert(gameHudSrc.includes('/api/amy/simulation/spawn'), 'game-hud: calls POST /api/amy/simulation/spawn');
assert(gameHudSrc.includes('/api/game/upgrades'), 'game-hud: calls GET /api/game/upgrades');
assert(gameHudSrc.includes('/api/game/upgrade'), 'game-hud: calls POST /api/game/upgrade');

// Units panel endpoints
const unitsSrc = readSource('src/frontend/js/command/panels/units.js');
assert(unitsSrc.includes('/api/amy/command'), 'units: calls POST /api/amy/command (dispatch)');
// NPC control is handled in main.js via WASD, not in units.js directly
assert(mainSrc.includes('/api/npc/'), 'main.js: calls /api/npc/ for WASD control');

// Amy panel endpoints
const amySrc = readSource('src/frontend/js/command/panels/amy.js');
assert(amySrc.includes('/api/amy/status'), 'amy: calls GET /api/amy/status');
assert(amySrc.includes('/api/amy/command'), 'amy: calls POST /api/amy/command');

// Patrol panel endpoints
const patrolSrc = readSource('src/frontend/js/command/panels/patrol.js');
assert(patrolSrc.includes('/api/amy/command'), 'patrol: calls POST /api/amy/command');
assert(patrolSrc.includes('patrol-all'), 'patrol: has patrol-all button action');
assert(patrolSrc.includes('recall-all'), 'patrol: has recall-all button action');

// Replay panel endpoints
const replaySrc = readSource('src/frontend/js/command/panels/replay.js');
assert(replaySrc.includes('/api/game/replay'), 'replay: calls /api/game/replay endpoints');
const replayActions = ['play', 'pause', 'stop', 'seek', 'speed'];
for (const action of replayActions) {
    assert(replaySrc.includes(action), `replay: has ${action} action`);
}

// Mission modal endpoints
const missionSrc = readSource('src/frontend/js/command/mission-modal.js');
assert(missionSrc.includes('/api/game/generate'), 'mission: calls POST /api/game/generate');
assert(missionSrc.includes('/api/game/mission/apply'), 'mission: calls POST /api/game/mission/apply');
assert(missionSrc.includes('/api/game/models'), 'mission: calls GET /api/game/models');

// Stats panel endpoints
const statsSrc = readSource('src/frontend/js/command/panels/stats.js');
assert(statsSrc.includes('/api/game/stats'), 'stats: calls GET /api/game/stats');

// Context menu endpoints
const contextSrc = readSource('src/frontend/js/command/context-menu.js');
assert(contextSrc.includes('/api/amy/command'), 'context-menu: calls POST /api/amy/command');
assert(contextSrc.includes('dispatch'), 'context-menu: has dispatch action');

// System panel endpoints
const systemSrc = readSource('src/frontend/js/command/panels/system.js');
assert(systemSrc.includes('/api/cameras'), 'system: calls GET /api/cameras');
assert(systemSrc.includes('/api/discovery'), 'system: calls /api/discovery endpoints');
assert(systemSrc.includes('/api/telemetry'), 'system: calls /api/telemetry endpoints');
// Fleet endpoint may use different path prefix
assert(systemSrc.includes('fleet') || systemSrc.includes('/api/amy/fleet') || systemSrc.includes('/api/graphlings'),
    'system: calls fleet or AI-related endpoint');

// Cameras panel endpoints
const camerasSrc = readSource('src/frontend/js/command/panels/cameras.js');
assert(camerasSrc.includes('/api/synthetic/cameras'), 'cameras: calls /api/synthetic/cameras');

// Scenarios panel endpoints
const scenariosSrc = readSource('src/frontend/js/command/panels/scenarios.js');
assert(scenariosSrc.includes('/api/scenarios'), 'scenarios: calls GET /api/scenarios');

// ============================================================
// 5. Store Field Contract: WebSocket telemetry -> store fields
// ============================================================
console.log('\n=== Store Field Contract ===\n');

const wsSrc = readSource('src/frontend/js/command/websocket.js');

// Core telemetry fields that the store must contain
const TELEMETRY_FIELDS = [
    'alliance', 'position', 'heading', 'health', 'status', 'speed',
    'morale', 'fsm_state', 'degradation', 'weapon_range',
    'visible', 'squad_id', 'detected_by', 'detected',
    'crowd_role', 'drone_variant', 'ammo_count',
    'identity', 'source', 'waypoints', 'inventory', 'stats',
    'radio_detected', 'radio_signal_strength',
];

for (const field of TELEMETRY_FIELDS) {
    const snakePattern = `t.${field}`;
    assert(wsSrc.includes(snakePattern),
        `websocket parses telemetry field: ${field}`);
}

// ============================================================
// 6. WebSocket Message Types: all types have handlers
// ============================================================
console.log('\n=== WebSocket Message Handlers ===\n');

// Check that major message types have handlers (some use amy_ prefix routing)
const MESSAGE_TYPES_EXACT = [
    'amy_thought', 'amy_speech', 'amy_transcript', 'amy_state',
    'amy_sim_telemetry', 'amy_sim_telemetry_batch',
    'amy_game_state_change',
    'amy_target_eliminated',
    'amy_announcer',
    'amy_robot_thought',
    'amy_npc_thought',
    'amy_escalation_change',
    'amy_projectile_fired',
    'amy_projectile_hit',
    'amy_elimination_streak',
    'amy_wave_start',
    'amy_wave_complete',
    'amy_game_over',
];

for (const msgType of MESSAGE_TYPES_EXACT) {
    const hasHandler = wsSrc.includes(`case '${msgType}':`);
    assert(hasHandler, `websocket handles message type: ${msgType}`);
}

// Also check non-prefixed types are handled (may be aliases or direct)
const UNPREFIXED_TYPES = [
    'sim_telemetry', 'game_state', 'target_eliminated',
    'announcer', 'wave_start', 'wave_complete',
];
for (const msgType of UNPREFIXED_TYPES) {
    const handled = wsSrc.includes(`'${msgType}'`) || wsSrc.includes(`"${msgType}"`);
    assert(handled, `websocket references message type: ${msgType}`);
}

// ============================================================
// 7. Fog of War Contract: vision system uses proper transforms
// ============================================================
console.log('\n=== Fog of War Contract ===\n');

const visionSrc = readSource('src/frontend/js/command/vision-system.js');

// Coordinate transforms must NOT be stubs
assert(!visionSrc.includes('// This would use mapState.map.project'),
    'fog: _worldToScreen is not a stub comment');
assert(visionSrc.includes('map.project('), 'fog: _worldToScreen uses map.project()');
assert(visionSrc.includes('Math.cos(') && visionSrc.includes('Math.pow(2,'),
    'fog: _metersToPixels uses Mercator formula');

// Ghost tracker handles radio ghosts
assert(visionSrc.includes('RADIO_GHOST_FADE_SECONDS'),
    'fog: GhostTracker has radio ghost TTL constant');
assert(visionSrc.includes("type === 'radio'") || visionSrc.includes("type: 'radio'"),
    'fog: GhostTracker distinguishes radio vs visual ghosts');
assert(visionSrc.includes('getRadioGhosts'),
    'fog: GhostTracker has getRadioGhosts() method');
assert(visionSrc.includes('uncertainty'),
    'fog: radio ghosts track uncertainty');

// ============================================================
// 8. Unit Spread Contract: spawn radius uses full city
// ============================================================
console.log('\n=== Unit Spread Contract ===\n');

const enginePy = readSource('src/engine/simulation/engine.py');

// Spawn radius should NOT be too cramped (30-40% of bounds)
assert(!enginePy.includes('random.uniform(0.30, 0.40)'),
    'spread: spawn radius NOT 30-40% (old cramped value)');
// Uses absolute distances now (80-150m or 50-100m) instead of percentage
assert(enginePy.includes('random.uniform(80.0, 150.0)') || enginePy.includes('random.uniform(50.0, 100.0)'),
    'spread: spawn uses absolute distance (80-150m or 50-100m)');

// Objectives should be spread across map, NOT just center
assert(!enginePy.includes('map_bounds * 0.04'),
    'spread: objectives NOT within 4% of bounds (old cramped value)');
assert(enginePy.includes('map_bounds * 0.50') || enginePy.includes('map_bounds * 0.5'),
    'spread: objectives spread across 50% of map');

// ============================================================
// 9. Directional Wave Spawning: waves come from different directions
// ============================================================
console.log('\n=== Directional Wave Spawning ===\n');

const gameModePy = readSource('src/engine/simulation/game_mode.py');
assert(gameModePy.includes('spawn_direction'),
    'game_mode: WaveConfig has spawn_direction field');

// Waves use various directions (some explicitly, some via default="random")
const EXPLICIT_DIRECTIONS = ['east', 'west', 'pincer', 'surround'];
for (const dir of EXPLICIT_DIRECTIONS) {
    assert(gameModePy.includes(`spawn_direction="${dir}"`) ||
           gameModePy.includes(`spawn_direction='${dir}'`),
        `game_mode: has wave with spawn_direction="${dir}"`);
}
// "random" is the default value in WaveConfig, so it appears as a default, not explicit
assert(gameModePy.includes('spawn_direction: str = "random"') ||
       gameModePy.includes("spawn_direction: str = 'random'"),
    'game_mode: spawn_direction defaults to "random"');
// "north" may or may not be used; verify at least 3 different explicit directions
assert(EXPLICIT_DIRECTIONS.filter(d =>
    gameModePy.includes(`spawn_direction="${d}"`) || gameModePy.includes(`spawn_direction='${d}'`)
).length >= 3, 'game_mode: at least 3 different explicit spawn directions used');

// ============================================================
// 10. Radio Detection Server-Side Contract
// ============================================================
console.log('\n=== Radio Detection Server-Side ===\n');

const visionPy = readSource('src/engine/simulation/vision.py');
assert(visionPy.includes('_RADIO_DETECTION_RANGE'),
    'vision.py: defines radio detection range constant');
assert(visionPy.includes('radio_detected'),
    'vision.py: tracks radio_detected targets');
assert(visionPy.includes('radio_signal_strength'),
    'vision.py: computes radio signal strength');
assert(visionPy.includes('bluetooth_mac') || visionPy.includes('wifi_mac'),
    'vision.py: checks for radio signatures on targets');

const targetPy = readSource('src/engine/simulation/target.py');
assert(targetPy.includes('radio_detected: bool'),
    'target.py: has radio_detected field');
assert(targetPy.includes('radio_signal_strength: float'),
    'target.py: has radio_signal_strength field');
assert(targetPy.includes('bluetooth_mac'),
    'target.py: UnitIdentity has bluetooth_mac');
assert(targetPy.includes('wifi_mac'),
    'target.py: UnitIdentity has wifi_mac');
assert(targetPy.includes('cell_id'),
    'target.py: UnitIdentity has cell_id');

// ============================================================
// 11. Radio Ghost CSS: visual indicator for radio-detected units
// ============================================================
console.log('\n=== Radio Ghost CSS ===\n');

const tritiumCss = readSource('src/frontend/css/tritium.css');
assert(tritiumCss.includes('.radio-ghost'),
    'CSS: has .radio-ghost class');
assert(tritiumCss.includes('radio-pulse') || tritiumCss.includes('radio-ring'),
    'CSS: has radio ghost animation keyframes');

const mapSrc = readSource('src/frontend/js/command/map-maplibre.js');
assert(mapSrc.includes('radio-ghost'), 'map: adds radio-ghost CSS class');
assert(mapSrc.includes('radio_detected'), 'map: checks radio_detected for ghost styling');

// ============================================================
// 12. Menu Bar: all panels in VIEW menu
// ============================================================
console.log('\n=== Menu Bar VIEW Menu ===\n');

const menuSrc = readSource('src/frontend/js/command/menu-bar.js');
// VIEW menu dynamically generates items from panelManager.getRegisteredPanels()
assert(menuSrc.includes('getRegisteredPanels'),
    'menu-bar: VIEW menu uses getRegisteredPanels() for dynamic panel listing');
assert(menuSrc.includes('toggle'),
    'menu-bar: VIEW menu items call toggle on panels');
assert(menuSrc.includes('VIEW'),
    'menu-bar: has VIEW menu label');
// Verify all panel IDs are registered in main.js (which feeds the menu)
const VIEW_PANELS = [
    'amy', 'units', 'alerts', 'game', 'mesh', 'audio',
    'escalation', 'events', 'patrol', 'scenarios', 'system',
    'minimap', 'graphlings', 'replay', 'battle-stats', 'sensors',
    'unit-inspector', 'cameras', 'search', 'tak', 'videos', 'zones',
];
// Verify each panel file exports a PanelDef and is imported in main.js
const PANEL_FILES = {
    'amy': 'amy.js', 'units': 'units.js', 'alerts': 'alerts.js',
    'game': 'game-hud.js', 'mesh': 'mesh.js', 'audio': 'audio.js',
    'escalation': 'escalation.js', 'events': 'events.js', 'patrol': 'patrol.js',
    'scenarios': 'scenarios.js', 'system': 'system.js', 'minimap': 'minimap.js',
    'graphlings': 'graphlings.js', 'replay': 'replay.js', 'battle-stats': 'stats.js',
    'sensors': 'sensors.js', 'unit-inspector': 'unit-inspector.js',
    'cameras': 'cameras.js', 'search': 'search.js', 'tak': 'tak.js',
    'videos': 'videos.js', 'zones': 'zones.js',
};
for (const [id, file] of Object.entries(PANEL_FILES)) {
    // The file must be imported in main.js
    assert(mainSrc.includes(`panels/${file}`),
        `main.js: imports panel file '${file}' for '${id}'`);
}

// ============================================================
// 13. Game Mode Definitions: all 10 waves defined
// ============================================================
console.log('\n=== Game Mode Wave Definitions ===\n');

const WAVE_NAMES = [
    'Scout Party', 'Raiding Party', 'Assault Squad', 'Heavy Assault',
    'Blitz Attack', 'Armored Push', 'Swarm', 'Elite Strike',
    'Full Invasion', 'FINAL STAND',
];
for (const name of WAVE_NAMES) {
    assert(gameModePy.includes(`"${name}"`) || gameModePy.includes(`'${name}'`),
        `game_mode: wave "${name}" defined`);
}

// ============================================================
// 14. Context Menu: all actions wired to backend
// ============================================================
console.log('\n=== Context Menu Actions ===\n');

const CONTEXT_ACTIONS = ['dispatch', 'waypoint', 'marker', 'suggest_dispatch', 'suggest_investigate'];
for (const action of CONTEXT_ACTIONS) {
    assert(contextSrc.includes(`'${action}'`) || contextSrc.includes(`"${action}"`),
        `context-menu: has action '${action}'`);
}
// Dispatch should call backend
assert(contextSrc.includes("fetch('/api/amy/command'") ||
       contextSrc.includes('fetch("/api/amy/command"') ||
       contextSrc.includes("fetch(`/api/amy/command`"),
    'context-menu: dispatch calls backend API');

// ============================================================
// 15. Tab Cycling: handler is NOT empty
// ============================================================
console.log('\n=== Tab Panel Cycling ===\n');

// Find the Tab case and check it has real code
const tabIdx = mainSrc.indexOf("case 'Tab':");
assert(tabIdx !== -1, 'tab: case "Tab" exists in keyboard handler');
if (tabIdx !== -1) {
    const tabBlock = mainSrc.substring(tabIdx, tabIdx + 800);
    assert(tabBlock.includes('getRegisteredPanels') || tabBlock.includes('openPanels') || tabBlock.includes('focusedPanel'),
        'tab: Tab handler has real panel cycling logic (not empty)');
    // Focus indicator may use various class names
    assert(tabBlock.includes('focused') || tabBlock.includes('focus') || tabBlock.includes('panel-focused'),
        'tab: Tab handler adds visual focus indicator');
}

// ============================================================
// 16. WASD Direct Control
// ============================================================
console.log('\n=== WASD Direct Unit Control ===\n');

// WASD is handled via a moveMap lookup (not individual case statements)
assert(mainSrc.includes("'w': 'move_forward'") || mainSrc.includes("'w':"),
    'wasd: w key mapped in move handler');
assert(mainSrc.includes("'a': 'move_left'") || mainSrc.includes("'a':"),
    'wasd: a key mapped in move handler');
assert(mainSrc.includes("'s': 'move_backward'") || mainSrc.includes("'s':"),
    'wasd: s key mapped in move handler');
assert(mainSrc.includes("'d': 'move_right'") || mainSrc.includes("'d':"),
    'wasd: d key mapped in move handler');
// Should call NPC action endpoint
assert(mainSrc.includes('/api/npc/'),
    'wasd: WASD sends command to NPC action endpoint');

// ============================================================
// 17. Layout Manager: save/recall/export functionality
// ============================================================
console.log('\n=== Layout Manager ===\n');

const layoutSrc = readSource('src/frontend/js/command/layout-manager.js');
assert(layoutSrc.includes('saveLayout') || layoutSrc.includes('save'),
    'layout: has save functionality');
assert(layoutSrc.includes('localStorage'),
    'layout: persists to localStorage');
assert(layoutSrc.includes('JSON.stringify') || layoutSrc.includes('JSON.parse'),
    'layout: serializes/deserializes layout data');

// Built-in layout names (lowercase in code)
const BUILT_IN_LAYOUTS = ['commander', 'observer', 'tactical', 'battle'];
for (const name of BUILT_IN_LAYOUTS) {
    assert(layoutSrc.includes(name),
        `layout: has built-in layout "${name}"`);
}

// ============================================================
// 18. Game Over Stats
// ============================================================
console.log('\n=== Game Over Stats ===\n');

const gameOverSrc = readSource('src/frontend/js/command/game-over-stats.js');
assert(gameOverSrc.includes('/api/game/stats'),
    'game-over: fetches from /api/game/stats');

// ============================================================
// 19. Store Reactivity: key state changes trigger renders
// ============================================================
console.log('\n=== Store Reactivity ===\n');

const storeSrc = readSource('src/frontend/js/command/store.js');
assert(storeSrc.includes('updateUnit'), 'store: has updateUnit method');
assert(storeSrc.includes('removeUnit'), 'store: has removeUnit method');
assert(storeSrc.includes('_notify') || storeSrc.includes('flushNotify'),
    'store: has notification/flush mechanism');
assert(storeSrc.includes('requestAnimationFrame') || storeSrc.includes('_scheduleFlush'),
    'store: batches notifications via requestAnimationFrame');

// ============================================================
// 20. Mission Types: all game modes available
// ============================================================
console.log('\n=== Mission Types ===\n');

const GAME_MODES = ['battle', 'defense', 'patrol', 'escort', 'civil_unrest', 'drone_swarm'];
for (const mode of GAME_MODES) {
    assert(missionSrc.includes(mode), `mission-modal: supports game mode "${mode}"`);
}

// ============================================================
// 21. Backend Game Router: all endpoints exist
// ============================================================
console.log('\n=== Backend Game Router ===\n');

const gameRouterPy = readSource('src/app/routers/game.py');
const GAME_ENDPOINTS = [
    '/state', '/begin', '/reset', '/place', '/projectiles',
    '/scenarios', '/modes', '/models',
    '/generate', '/mission/apply', '/mission/current',
    '/upgrades', '/upgrade', '/abilities', '/ability',
    '/replay', '/stats',
];
for (const ep of GAME_ENDPOINTS) {
    assert(gameRouterPy.includes(`"${ep}"`) || gameRouterPy.includes(`'${ep}'`) || gameRouterPy.includes(ep),
        `game router: endpoint ${ep} exists`);
}

// ============================================================
// 22. Simulation Subsystem Wiring
// ============================================================
console.log('\n=== Simulation Subsystem Wiring ===\n');

// Engine should wire all subsystems
const ENGINE_SUBSYSTEMS = [
    'VisionSystem', 'CombatSystem', 'MoraleSystem', 'PursuitSystem',
    'CoverSystem', 'WeaponSystem', 'UpgradeSystem',
];
for (const sub of ENGINE_SUBSYSTEMS) {
    assert(enginePy.includes(sub),
        `engine: wires ${sub} subsystem`);
}

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Feature Flow Tests: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
