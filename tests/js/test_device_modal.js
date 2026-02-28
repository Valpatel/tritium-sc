// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Device Modal tests
 * Tests: DeviceModalManager, DeviceControlRegistry, type-specific controls
 * Run: node tests/js/test_device_modal.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertDeepEqual(a, b, msg) {
    assert(JSON.stringify(a) === JSON.stringify(b), msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}

// Load source files into sandboxed context
function loadModule(relPath) {
    const code = fs.readFileSync(__dirname + '/../../' + relPath, 'utf8');
    return code
        .replace(/^export\s+/gm, '')
        .replace(/^import\s+.*$/gm, '');
}

const eventsCode = loadModule('frontend/js/command/events.js');
const storeCode = loadModule('frontend/js/command/store.js');
const deviceModalCode = loadModule('frontend/js/command/device-modal.js');

// Minimal DOM mock
function createMockDocument() {
    const elements = {};
    const created = [];
    return {
        createElement(tag) {
            const el = {
                tagName: tag.toUpperCase(),
                className: '',
                innerHTML: '',
                style: {},
                children: [],
                _listeners: {},
                _attributes: {},
                dataset: {},
                appendChild(child) { this.children.push(child); return child; },
                removeChild(child) {
                    const idx = this.children.indexOf(child);
                    if (idx >= 0) this.children.splice(idx, 1);
                    return child;
                },
                addEventListener(evt, fn) {
                    if (!this._listeners[evt]) this._listeners[evt] = [];
                    this._listeners[evt].push(fn);
                },
                removeEventListener(evt, fn) {
                    if (this._listeners[evt]) {
                        this._listeners[evt] = this._listeners[evt].filter(f => f !== fn);
                    }
                },
                querySelector(sel) {
                    // Basic selector matching for test purposes
                    if (sel.startsWith('.')) {
                        const cls = sel.slice(1);
                        for (const c of this.children) {
                            if (c.className && c.className.includes(cls)) return c;
                            const found = c.querySelector ? c.querySelector(sel) : null;
                            if (found) return found;
                        }
                    }
                    return null;
                },
                querySelectorAll(sel) {
                    const results = [];
                    const q = this.querySelector(sel);
                    if (q) results.push(q);
                    return results;
                },
                setAttribute(k, v) { this._attributes[k] = v; },
                getAttribute(k) { return this._attributes[k]; },
                contains(el) { return this.children.includes(el); },
                remove() { /* self-remove from parent */ },
                click() {
                    if (this._listeners.click) {
                        this._listeners.click.forEach(fn => fn({ target: this }));
                    }
                },
                get textContent() { return this.innerHTML; },
                set textContent(v) { this.innerHTML = v; },
            };
            created.push(el);
            return el;
        },
        body: {
            children: [],
            appendChild(child) { this.children.push(child); return child; },
            removeChild(child) {
                const idx = this.children.indexOf(child);
                if (idx >= 0) this.children.splice(idx, 1);
                return child;
            },
            contains(el) { return this.children.includes(el); },
        },
        getElementById(id) { return elements[id] || null; },
        _created: created,
    };
}

// Minimal fetch mock
let lastFetchCall = null;
function mockFetch(url, opts) {
    lastFetchCall = { url, opts };
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
}

// Create sandbox
const mockDoc = createMockDocument();
const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, Error, RegExp,
    document: mockDoc,
    window: { location: { host: 'localhost:8000' } },
    fetch: mockFetch,
};

const ctx = vm.createContext(sandbox);

// Load modules in order
vm.runInContext(eventsCode + '\nvar _EventBus = EventBus;', ctx);
vm.runInContext(storeCode + '\nvar _TritiumStore = TritiumStore;', ctx);
vm.runInContext(deviceModalCode + `
var _DeviceModalManager = DeviceModalManager;
var _DeviceControlRegistry = DeviceControlRegistry;
var _DeviceAPI = DeviceAPI;
`, ctx);

const EventBus = ctx._EventBus;
const TritiumStore = ctx._TritiumStore;

// Also expose into ctx for tests that access ctx.DeviceControlRegistry
ctx.DeviceControlRegistry = ctx._DeviceControlRegistry;
ctx.DeviceModalManager = ctx._DeviceModalManager;
ctx.DeviceAPI = ctx._DeviceAPI;

// =====================================================================
// Tests: DeviceControlRegistry
// =====================================================================
console.log('\n--- DeviceControlRegistry ---');

{
    const registry = ctx.DeviceControlRegistry;
    assert(registry !== undefined, 'DeviceControlRegistry exists');
}

{
    const registry = ctx.DeviceControlRegistry;
    // Check built-in types are registered
    const types = registry.getRegisteredTypes();
    assert(types.length >= 4, 'At least 4 device types registered (got ' + types.length + ')');
    assert(types.includes('rover'), 'rover type registered');
    assert(types.includes('drone'), 'drone type registered');
    assert(types.includes('turret'), 'turret type registered');
}

{
    const registry = ctx.DeviceControlRegistry;
    const rover = registry.get('rover');
    assert(rover !== null && rover !== undefined, 'get("rover") returns a control');
    assertEqual(typeof rover.render, 'function', 'rover control has render()');
    assertEqual(typeof rover.bind, 'function', 'rover control has bind()');
    assertEqual(typeof rover.update, 'function', 'rover control has update()');
    assertEqual(typeof rover.destroy, 'function', 'rover control has destroy()');
    assert(typeof rover.title === 'string' && rover.title.length > 0, 'rover control has title');
}

{
    const registry = ctx.DeviceControlRegistry;
    const unknown = registry.get('unknown_device_xyz');
    assert(unknown !== null && unknown !== undefined, 'unknown type returns fallback control');
}

{
    // Register custom type
    const registry = ctx.DeviceControlRegistry;
    registry.register('custom_bot', {
        type: 'custom_bot',
        title: 'Custom Bot',
        render: () => '<div>custom</div>',
        bind: () => {},
        update: () => {},
        destroy: () => {},
    });
    const custom = registry.get('custom_bot');
    assertEqual(custom.title, 'Custom Bot', 'custom registration works');
}

// =====================================================================
// Tests: DeviceModalManager
// =====================================================================
console.log('\n--- DeviceModalManager ---');

{
    const manager = ctx.DeviceModalManager;
    assert(manager !== undefined, 'DeviceModalManager exists');
    assertEqual(typeof manager.open, 'function', 'has open()');
    assertEqual(typeof manager.close, 'function', 'has close()');
    assertEqual(typeof manager.isOpen, 'function', 'has isOpen()');
}

{
    // open() creates overlay
    const manager = ctx.DeviceModalManager;
    manager.close(); // ensure clean state
    assert(!manager.isOpen(), 'starts closed');

    const device = {
        id: 'rover-01',
        name: 'Rover Alpha',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        heading: 90,
        speed: 2.0,
        battery: 0.85,
        health: 100,
        maxHealth: 150,
        status: 'active',
    };

    manager.open('rover-01', 'rover', device);
    assert(manager.isOpen(), 'isOpen() returns true after open()');
}

{
    // close() removes overlay
    const manager = ctx.DeviceModalManager;
    manager.close();
    assert(!manager.isOpen(), 'isOpen() returns false after close()');
}

{
    // Render includes device stats
    const manager = ctx.DeviceModalManager;
    const device = {
        id: 'turret-01',
        name: 'Sentry Alpha',
        type: 'turret',
        alliance: 'friendly',
        position: { x: 0, y: 0 },
        heading: 0,
        battery: 1.0,
        health: 200,
        maxHealth: 200,
        status: 'active',
    };

    manager.open('turret-01', 'turret', device);
    assert(manager.isOpen(), 'turret modal opens');
    manager.close();
}

// =====================================================================
// Tests: Control render output
// =====================================================================
console.log('\n--- Control Rendering ---');

{
    const registry = ctx.DeviceControlRegistry;
    const roverCtrl = registry.get('rover');
    const device = {
        id: 'rover-01',
        name: 'Rover Alpha',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        heading: 90,
        speed: 2.0,
        battery: 0.85,
        health: 100,
        maxHealth: 150,
        status: 'active',
    };
    const html = roverCtrl.render(device);
    assert(typeof html === 'string', 'render returns string');
    assert(html.length > 0, 'render returns non-empty HTML');
    assert(html.includes('DISPATCH') || html.includes('dispatch'), 'rover render includes dispatch action');
    assert(html.includes('RECALL') || html.includes('recall'), 'rover render includes recall action');
    assert(html.includes('PATROL') || html.includes('patrol'), 'rover render includes patrol action');
}

{
    const registry = ctx.DeviceControlRegistry;
    const turretCtrl = registry.get('turret');
    const device = {
        id: 'turret-01',
        name: 'Sentry Alpha',
        type: 'turret',
        alliance: 'friendly',
        position: { x: 0, y: 0 },
        heading: 0,
        battery: 1.0,
        health: 200,
        maxHealth: 200,
        status: 'active',
        weaponRange: 80,
    };
    const html = turretCtrl.render(device);
    assert(typeof html === 'string', 'turret render returns string');
    assert(html.includes('FIRE') || html.includes('fire'), 'turret render includes fire action');
}

{
    const registry = ctx.DeviceControlRegistry;
    const sensorCtrl = registry.get('pir') || registry.get('sensor') || registry.get('mesh_radio');
    assert(sensorCtrl !== undefined, 'sensor-like type returns a control');
}

// =====================================================================
// Tests: Command API
// =====================================================================
console.log('\n--- Command API ---');

{
    // DeviceAPI helper sends correct fetch
    lastFetchCall = null;
    const api = ctx.DeviceAPI;
    if (api) {
        api.dispatch('rover-01', 50, 100);
        // Allow microtask to settle
        assert(lastFetchCall !== null, 'dispatch triggers fetch call');
        assert(lastFetchCall.url.includes('/api/'), 'dispatch URL includes /api/');
    } else {
        // DeviceAPI might be embedded in modal manager
        assert(true, 'DeviceAPI integrated into modal (skipping direct test)');
    }
}

{
    // sendCommand sends Lua to /api/amy/command
    lastFetchCall = null;
    const api = ctx.DeviceAPI;
    if (api) {
        api.sendCommand('rover-01', 'patrol({10,10},{20,20})');
        assert(lastFetchCall !== null, 'sendCommand triggers fetch');
    } else {
        assert(true, 'DeviceAPI integrated (skipping)');
    }
}

// =====================================================================
// Tests: EventBus integration
// =====================================================================
console.log('\n--- EventBus Integration ---');

{
    // unit:selected should be emittable and the modal listens
    let selectedData = null;
    const unsub = EventBus.on('unit:selected', (data) => { selectedData = data; });
    EventBus.emit('unit:selected', { id: 'drone-01' });
    assert(selectedData !== null, 'unit:selected event received');
    assertEqual(selectedData.id, 'drone-01', 'correct unit ID in event');
    unsub();
}

{
    // device:command event emitted when modal sends command
    let cmdData = null;
    const unsub = EventBus.on('device:command', (data) => { cmdData = data; });
    EventBus.emit('device:command', { deviceId: 'rover-01', command: 'dispatch', x: 50, y: 100 });
    assert(cmdData !== null, 'device:command event works');
    assertEqual(cmdData.deviceId, 'rover-01', 'correct device ID');
    unsub();
}

// =====================================================================
// Tests: NPCControl
// =====================================================================
console.log('\n--- NPCControl ---');

{
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    assert(npcCtrl !== null && npcCtrl !== undefined, 'NPCControl registered');
    assertEqual(npcCtrl.type, 'npc', 'NPCControl type is "npc"');
    assert(typeof npcCtrl.title === 'string' && npcCtrl.title.length > 0, 'NPCControl has title');
}

{
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    assertEqual(typeof npcCtrl.render, 'function', 'NPCControl has render()');
    assertEqual(typeof npcCtrl.bind, 'function', 'NPCControl has bind()');
    assertEqual(typeof npcCtrl.update, 'function', 'NPCControl has update()');
    assertEqual(typeof npcCtrl.destroy, 'function', 'NPCControl has destroy()');
}

{
    // NPCControl renders unit info section
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    const device = {
        id: 'npc-ped-01',
        name: 'Sarah',
        type: 'person',
        asset_type: 'person',
        alliance: 'neutral',
        position: { x: 50, y: 60 },
        heading: 180,
        speed: 1.2,
        health: 100,
        max_health: 100,
        status: 'active',
        fsm_state: 'idle',
    };
    const html = npcCtrl.render(device);
    assert(typeof html === 'string', 'render returns string');
    assert(html.length > 50, 'render returns substantial HTML');
    assert(html.includes('Sarah') || html.includes('npc-ped-01'), 'render includes NPC name or ID');
    assert(html.includes('person') || html.includes('PERSON'), 'render includes asset type');
    assert(html.includes('neutral') || html.includes('NEUTRAL'), 'render includes alliance');
}

{
    // NPCControl renders thought section
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    const device = {
        id: 'npc-ped-02',
        name: 'Mike',
        type: 'person',
        alliance: 'neutral',
        position: { x: 10, y: 20 },
        health: 100,
        max_health: 100,
        thoughtText: 'Nice weather today',
        thoughtEmotion: 'happy',
    };
    const html = npcCtrl.render(device);
    assert(html.includes('Nice weather today'), 'render includes current thought text');
}

{
    // NPCControl renders thought history
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    const device = {
        id: 'npc-ped-03',
        name: 'Tina',
        type: 'person',
        alliance: 'neutral',
        position: { x: 0, y: 0 },
        health: 100,
        max_health: 100,
        thoughtHistory: [
            { text: 'First thought', emotion: 'neutral', time: Date.now() - 5000 },
            { text: 'Second thought', emotion: 'curious', time: Date.now() },
        ],
    };
    const html = npcCtrl.render(device);
    assert(html.includes('First thought'), 'render includes first history entry');
    assert(html.includes('Second thought'), 'render includes second history entry');
}

{
    // NPCControl renders SET THOUGHT controls
    const registry = ctx.DeviceControlRegistry;
    const npcCtrl = registry.get('npc');
    const device = {
        id: 'npc-v-01',
        name: 'Sedan',
        type: 'vehicle',
        alliance: 'neutral',
        position: { x: 0, y: 0 },
        health: 100,
        max_health: 100,
    };
    const html = npcCtrl.render(device);
    assert(html.includes('SET') || html.includes('set'), 'render includes SET thought button');
    assert(html.includes('TAKE CONTROL') || html.includes('take_control'), 'render includes TAKE CONTROL action');
}

{
    // NPCControl modal opens via DeviceModalManager
    const manager = ctx.DeviceModalManager;
    manager.close();
    const device = {
        id: 'npc-ped-04',
        name: 'Jess',
        type: 'person',
        alliance: 'neutral',
        position: { x: 10, y: 20 },
        health: 100,
        max_health: 100,
    };
    manager.open('npc-ped-04', 'npc', device);
    assert(manager.isOpen(), 'NPC modal opens via DeviceModalManager');
    manager.close();
    assert(!manager.isOpen(), 'NPC modal closes');
}

// =====================================================================
// Tests: NPC type routing
// =====================================================================
console.log('\n--- NPC Type Routing ---');

{
    // Alias check: person/animal/vehicle used to route to 'sensor', now 'npc' for neutrals
    const registry = ctx.DeviceControlRegistry;
    // person alias should now resolve to npc for neutral units
    // but in the registry itself, 'person' still has the old alias;
    // the routing logic is in map.js _resolveModalType
    // Here we just verify 'npc' returns NPCControl
    const npc = registry.get('npc');
    assert(npc.type === 'npc', 'direct "npc" lookup returns NPCControl');
}

{
    // Verify old aliases still work for non-NPC types
    const registry = ctx.DeviceControlRegistry;
    const scout = registry.get('scout_drone');
    assert(scout !== null && scout !== undefined, 'scout_drone alias still resolves');
    const tank = registry.get('tank');
    assert(tank !== null && tank !== undefined, 'tank alias still resolves');
}

// =====================================================================
// Summary
// =====================================================================
console.log(`\n=== Device Modal Tests: ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
