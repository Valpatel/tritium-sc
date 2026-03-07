// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Device Control Modal System tests
 * Tests all device control types (Rover, Drone, Turret, Sensor, NPC, Camera,
 * MeshRadio, Generic), DeviceControlRegistry alias resolution, DeviceAPI
 * endpoints, DeviceModalManager open/close lifecycle, and button event wiring.
 * Run: node tests/js/test_device_controls.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM + browser mocks
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const attrs = {};

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        setAttribute(name, value) { attrs[name] = String(value); },
        getAttribute(name) { return attrs[name] !== undefined ? attrs[name] : null; },
        removeAttribute(name) { delete attrs[name]; },
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            el._parsedBinds = {};
            const bindMatches = val.matchAll(/data-bind="([^"]+)"/g);
            for (const m of bindMatches) el._parsedBinds[m[1]] = true;
        },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val);
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: '',
        disabled: false,
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classList.has(cls)) classList.delete(cls);
                        else classList.add(cls);
                    } else if (force) classList.add(cls);
                    else classList.delete(cls);
                },
            };
        },
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        removeChild(child) {
            const idx = children.indexOf(child);
            if (idx >= 0) children.splice(idx, 1);
            return child;
        },
        contains(child) { return children.includes(child); },
        remove() {},
        focus() {},
        click() {
            // Fire all click listeners
            if (eventListeners['click']) {
                eventListeners['click'].forEach(fn => fn({ target: el }));
            }
        },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        _trigger(evt, evtObj) {
            if (eventListeners[evt]) {
                eventListeners[evt].forEach(fn => fn(evtObj || { target: el }));
            }
        },
        // Build querySelectorAll from innerHTML: parse data-cmd buttons
        _childCache: {},
        _btnElements: null,
        querySelector(sel) {
            if (el._childCache[sel]) return el._childCache[sel];
            // Match .classname
            const classMatch = sel.match(/^\.([a-zA-Z0-9_-]+)/);
            if (classMatch && _innerHTML.includes(classMatch[1])) {
                const mock = createMockElement('div');
                mock.className = classMatch[1];
                el._childCache[sel] = mock;
                return mock;
            }
            // Match [data-cmd="xxx"]
            const cmdMatch = sel.match(/\[data-cmd="([^"]+)"\]/);
            if (cmdMatch) {
                // Return element from _btnElements if available
                if (el._btnElements) {
                    for (const b of el._btnElements) {
                        if (b.dataset.cmd === cmdMatch[1]) {
                            el._childCache[sel] = b;
                            return b;
                        }
                    }
                }
                const mock = createMockElement('button');
                mock.dataset.cmd = cmdMatch[1];
                el._childCache[sel] = mock;
                return mock;
            }
            // Match [data-bind="xxx"]
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement('div');
                el._childCache[sel] = mock;
                return mock;
            }
            // Match input[type="..."]
            if (sel.includes('input') || sel.includes('.dc-cmd-input') || sel.includes('.dc-mesh-text') || sel.includes('.dc-slider')) {
                const mock = createMockElement('input');
                mock.value = '';
                el._childCache[sel] = mock;
                return mock;
            }
            if (sel.includes('select') || sel.includes('.dc-npc-emotion-select')) {
                const mock = createMockElement('select');
                mock.value = 'neutral';
                el._childCache[sel] = mock;
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) {
            // Return the button elements we built
            if (sel === '.dc-btn' && el._btnElements) {
                return el._btnElements;
            }
            if (sel === '.dc-slider' && el._sliderElements) {
                return el._sliderElements;
            }
            return [];
        },
        closest(sel) { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

// ============================================================
// Track calls to mock APIs
// ============================================================

const _fetchCalls = [];
const _eventBusEmits = [];
const _eventBusListeners = {};

function resetTracking() {
    _fetchCalls.length = 0;
    _eventBusEmits.length = 0;
    for (const k of Object.keys(_eventBusListeners)) delete _eventBusListeners[k];
}

function mockFetch(url, opts) {
    _fetchCalls.push({ url, opts });
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
}

// ============================================================
// Load source into vm context
// ============================================================

const EventBusMock = {
    _handlers: new Map(),
    on(event, handler) {
        if (!this._handlers.has(event)) this._handlers.set(event, new Set());
        this._handlers.get(event).add(handler);
        if (!_eventBusListeners[event]) _eventBusListeners[event] = [];
        _eventBusListeners[event].push(handler);
        return () => this._handlers.get(event)?.delete(handler);
    },
    off(event, handler) {
        this._handlers.get(event)?.delete(handler);
    },
    emit(event, data) {
        _eventBusEmits.push({ event, data });
        this._handlers.get(event)?.forEach(handler => {
            try { handler(data); } catch (e) { /* ignore */ }
        });
    },
};

const mockBody = createMockElement('body');
mockBody.contains = () => true;

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    RegExp, encodeURIComponent,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        body: mockBody,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {
        open() {},
    },
    fetch: mockFetch,
    EventBus: EventBusMock,
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load device-modal.js (strip ES module syntax)
const srcCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
const plainCode = srcCode
    .replace(/^export\s+\{[^}]*\};?\s*$/m, '')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');

vm.runInContext(plainCode, ctx);

// Extract objects from context
const DeviceAPI = vm.runInContext('DeviceAPI', ctx);
const DeviceControlRegistry = vm.runInContext('DeviceControlRegistry', ctx);
const DeviceModalManager = vm.runInContext('DeviceModalManager', ctx);
const RoverControl = vm.runInContext('RoverControl', ctx);
const DroneControl = vm.runInContext('DroneControl', ctx);
const TurretControl = vm.runInContext('TurretControl', ctx);
const SensorControl = vm.runInContext('SensorControl', ctx);
const CameraControl = vm.runInContext('CameraControl', ctx);
const NPCControl = vm.runInContext('NPCControl', ctx);
const MeshRadioControl = vm.runInContext('MeshRadioControl', ctx);
const GenericControl = vm.runInContext('GenericControl', ctx);

// ============================================================
// Helper: build a container with buttons from rendered HTML
// ============================================================

function buildContainerWithButtons(control, device) {
    const container = createMockElement('div');
    const html = control.render(device);
    container.innerHTML = html;

    // Parse button data-cmd values from the HTML and build mock button elements
    const btnMatches = [...html.matchAll(/data-cmd="([^"]+)"/g)];
    const buttons = [];
    for (const m of btnMatches) {
        const btn = createMockElement('button');
        btn.dataset.cmd = m[1];
        btn.getAttribute = (name) => {
            if (name === 'data-cmd') return m[1];
            return null;
        };
        buttons.push(btn);
    }
    container._btnElements = buttons;

    // Parse slider elements
    const sliderMatches = [...html.matchAll(/data-axis="([^"]+)"/g)];
    const sliders = [];
    for (const sm of sliderMatches) {
        const slider = createMockElement('input');
        slider.dataset.axis = sm[1];
        slider.getAttribute = (name) => {
            if (name === 'data-axis') return sm[1];
            return null;
        };
        slider.value = '0';
        slider.parentElement = createMockElement('div');
        const valSpan = createMockElement('span');
        valSpan.textContent = '0';
        slider.parentElement.querySelector = () => valSpan;
        slider.parentElement._valSpan = valSpan;
        sliders.push(slider);
    }
    container._sliderElements = sliders;

    // Provide a querySelector that finds status, input, and select elements
    const statusEl = createMockElement('div');
    statusEl.className = 'dc-cmd-status';
    const inputEl = createMockElement('input');
    inputEl.value = '';
    const meshInputEl = createMockElement('input');
    meshInputEl.value = '';
    const thoughtInputEl = createMockElement('input');
    thoughtInputEl.value = '';
    const emotionSelect = createMockElement('select');
    emotionSelect.value = 'neutral';

    const origQs = container.querySelector.bind(container);
    container.querySelector = function(sel) {
        if (sel === '.dc-cmd-status') return statusEl;
        if (sel === '.dc-cmd-input') return inputEl;
        if (sel === '.dc-mesh-text') return meshInputEl;
        if (sel === '.dc-npc-thought-input') return thoughtInputEl;
        if (sel === '.dc-npc-emotion-select') return emotionSelect;
        if (sel === '.dc-npc-personality') return createMockElement('div');
        if (sel === '.dc-npc-brain') return createMockElement('div');
        // For [data-cmd="send"], search buttons
        const cmdMatch = sel.match(/\[data-cmd="([^"]+)"\]/);
        if (cmdMatch) {
            for (const b of buttons) {
                if (b.dataset.cmd === cmdMatch[1]) return b;
            }
        }
        const sliderMatch = sel.match(/\.dc-slider-val/);
        if (sliderMatch) return createMockElement('span');
        return origQs(sel);
    };

    container._statusEl = statusEl;
    container._inputEl = inputEl;
    container._meshInputEl = meshInputEl;
    container._thoughtInputEl = thoughtInputEl;
    container._emotionSelect = emotionSelect;

    return container;
}

function findButton(container, cmdName) {
    if (!container._btnElements) return null;
    for (const b of container._btnElements) {
        if (b.dataset.cmd === cmdName) return b;
    }
    return null;
}

function makeDevice(overrides) {
    return Object.assign({
        id: 'test-unit-01',
        name: 'Test Unit',
        type: 'rover',
        status: 'idle',
        position: { x: 10.5, y: 20.3 },
        heading: 90,
        speed: 1.5,
        battery: 0.85,
        health: 100,
        maxHealth: 150,
    }, overrides);
}

// ============================================================
// 1. RoverControl structure
// ============================================================

console.log('\n--- RoverControl structure ---');

(function testRoverControlType() {
    assert(RoverControl.type === 'rover', 'RoverControl.type is "rover"');
})();

(function testRoverControlTitle() {
    assert(RoverControl.title === 'ROBOT CONTROL', 'RoverControl.title is "ROBOT CONTROL"');
})();

(function testRoverControlHasRender() {
    assert(typeof RoverControl.render === 'function', 'RoverControl has render()');
})();

(function testRoverControlHasBind() {
    assert(typeof RoverControl.bind === 'function', 'RoverControl has bind()');
})();

(function testRoverControlHasUpdate() {
    assert(typeof RoverControl.update === 'function', 'RoverControl has update()');
})();

(function testRoverControlHasDestroy() {
    assert(typeof RoverControl.destroy === 'function', 'RoverControl has destroy()');
})();

// ============================================================
// 2. RoverControl render output
// ============================================================

console.log('\n--- RoverControl render ---');

(function testRoverRenderContainsStats() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('dc-stats'), 'RoverControl render has dc-stats section');
    assert(html.includes('NAME'), 'RoverControl render has NAME label');
    assert(html.includes('TYPE'), 'RoverControl render has TYPE label');
    assert(html.includes('STATUS'), 'RoverControl render has STATUS label');
    assert(html.includes('POSITION'), 'RoverControl render has POSITION label');
    assert(html.includes('HEADING'), 'RoverControl render has HEADING label');
    assert(html.includes('SPEED'), 'RoverControl render has SPEED label');
    assert(html.includes('BATTERY'), 'RoverControl render has BATTERY label');
    assert(html.includes('HEALTH'), 'RoverControl render has HEALTH label');
})();

(function testRoverRenderContainsDispatchButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="dispatch"'), 'RoverControl render has DISPATCH button');
})();

(function testRoverRenderContainsPatrolButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="patrol"'), 'RoverControl render has PATROL button');
})();

(function testRoverRenderContainsRecallButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="recall"'), 'RoverControl render has RECALL button');
})();

(function testRoverRenderContainsStopButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="stop"'), 'RoverControl render has STOP button');
})();

(function testRoverRenderContainsFireButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="fire"'), 'RoverControl render has FIRE button');
})();

(function testRoverRenderContainsAimButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="aim"'), 'RoverControl render has AIM button');
})();

(function testRoverRenderContainsSendButton() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('data-cmd="send"'), 'RoverControl render has SEND button');
})();

(function testRoverRenderContainsLuaInput() {
    const html = RoverControl.render(makeDevice());
    assert(html.includes('dc-cmd-input'), 'RoverControl render has Lua command input');
    assert(html.includes('Lua command'), 'RoverControl input placeholder mentions Lua');
})();

(function testRoverRenderShowsDeviceName() {
    const html = RoverControl.render(makeDevice({ name: 'Rover Alpha' }));
    assert(html.includes('Rover Alpha'), 'RoverControl render shows device name');
})();

(function testRoverRenderShowsBattery() {
    // battery is already 0-100 in the store (websocket.js converts from 0-1)
    const html = RoverControl.render(makeDevice({ battery: 73 }));
    assert(html.includes('73%'), 'RoverControl render shows battery percentage');
})();

(function testRoverRenderHealthColor() {
    const htmlHigh = RoverControl.render(makeDevice({ health: 100, maxHealth: 100 }));
    assert(htmlHigh.includes('#05ffa1'), 'High health shows green color');

    const htmlMed = RoverControl.render(makeDevice({ health: 50, maxHealth: 100 }));
    assert(htmlMed.includes('#fcee0a'), 'Medium health shows yellow color');

    const htmlLow = RoverControl.render(makeDevice({ health: 10, maxHealth: 100 }));
    assert(htmlLow.includes('#ff2a6d'), 'Low health shows red color');
})();

// ============================================================
// 3. RoverControl button events
// ============================================================

console.log('\n--- RoverControl button events ---');

(function testRoverDispatchEmitsEvent() {
    resetTracking();
    const device = makeDevice({ id: 'rover-dispatch-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    const btn = findButton(container, 'dispatch');
    assert(btn !== null, 'DISPATCH button exists in container');
    btn.click();

    const emitted = _eventBusEmits.find(e => e.event === 'unit:dispatch-mode');
    assert(emitted !== undefined, 'DISPATCH emits unit:dispatch-mode event');
    assert(emitted && emitted.data.id === 'rover-dispatch-test', 'DISPATCH event has correct device id');
})();

(function testRoverDispatchSetsStatusText() {
    resetTracking();
    const device = makeDevice({ id: 'rover-dispatch-status' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'dispatch').click();
    assert(container._statusEl.textContent === 'Click map to set destination', 'DISPATCH sets status to destination prompt');
})();

(function testRoverPatrolEmitsEvent() {
    resetTracking();
    const device = makeDevice({ id: 'rover-patrol-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'patrol').click();

    const emitted = _eventBusEmits.find(e => e.event === 'unit:patrol-mode');
    assert(emitted !== undefined, 'PATROL emits unit:patrol-mode event');
    assert(emitted && emitted.data.id === 'rover-patrol-test', 'PATROL event has correct device id');
})();

(function testRoverPatrolSetsStatusText() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'patrol').click();
    assert(container._statusEl.textContent === 'Click map to set patrol points', 'PATROL sets status to patrol prompt');
})();

(function testRoverAimEmitsEvent() {
    resetTracking();
    const device = makeDevice({ id: 'rover-aim-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'aim').click();

    const emitted = _eventBusEmits.find(e => e.event === 'unit:aim-mode');
    assert(emitted !== undefined, 'AIM emits unit:aim-mode event');
    assert(emitted && emitted.data.id === 'rover-aim-test', 'AIM event has correct device id');
})();

(function testRoverAimSetsStatusText() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'aim').click();
    assert(container._statusEl.textContent === 'Click map to aim', 'AIM sets status to aim prompt');
})();

(function testRoverRecallCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'rover-recall-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'recall').click();

    const call = _fetchCalls.find(c => c.url === '/api/amy/command');
    assert(call !== undefined, 'RECALL calls /api/amy/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.action === 'recall', 'RECALL sends recall action');
    assert(Array.isArray(body.params) && body.params[0] === 'rover-recall-test', 'RECALL sends unit id in params array');
})();

(async function testRoverRecallSetsStatusText() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'recall').click();
    await Promise.resolve(); // let .then() fire
    assert(container._statusEl.textContent === 'Recall sent', 'RECALL sets status to confirmation');
})();

(function testRoverStopCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'rover-stop-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'stop').click();

    const call = _fetchCalls.find(c => c.url === '/api/devices/rover-stop-test/command');
    assert(call !== undefined, 'STOP calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'stop()', 'STOP sends stop() device command');
})();

(async function testRoverStopSetsStatusText() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'stop').click();
    await Promise.resolve(); // let .then() fire
    assert(container._statusEl.textContent === 'Stop sent', 'STOP sets status to confirmation');
})();

(function testRoverFireCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'rover-fire-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'fire').click();

    const call = _fetchCalls.find(c => c.url === '/api/devices/rover-fire-test/command');
    assert(call !== undefined, 'FIRE calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'fire_nerf()', 'FIRE sends fire_nerf() device command');
})();

(async function testRoverFireSetsStatusText() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    findButton(container, 'fire').click();
    await Promise.resolve(); // let .then() fire
    assert(container._statusEl.textContent === 'Fire command sent', 'FIRE sets status to confirmation');
})();

// ============================================================
// 4. RoverControl SEND custom Lua command
// ============================================================

console.log('\n--- RoverControl SEND custom Lua ---');

(function testRoverSendCallsAPIWithInputValue() {
    resetTracking();
    const device = makeDevice({ id: 'rover-send-test' });
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    container._inputEl.value = 'motor.rotate(45)';
    findButton(container, 'send').click();

    const call = _fetchCalls.find(c => c.url === '/api/devices/rover-send-test/command');
    assert(call !== undefined, 'SEND calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.rotate(45)', 'SEND sends the typed Lua command as device command');
})();

(function testRoverSendIgnoresEmptyInput() {
    resetTracking();
    const device = makeDevice();
    const container = buildContainerWithButtons(RoverControl, device);
    RoverControl.bind(container, device, DeviceAPI);

    container._inputEl.value = '   ';
    findButton(container, 'send').click();

    assert(_fetchCalls.length === 0, 'SEND does not call API with empty/whitespace input');
})();

// ============================================================
// 5. DroneControl structure and buttons
// ============================================================

console.log('\n--- DroneControl ---');

(function testDroneControlType() {
    assert(DroneControl.type === 'drone', 'DroneControl.type is "drone"');
})();

(function testDroneControlTitle() {
    assert(DroneControl.title === 'DRONE CONTROL', 'DroneControl.title is "DRONE CONTROL"');
})();

(function testDroneRenderHasAltitude() {
    const html = DroneControl.render(makeDevice({ type: 'drone', altitude: 15.3 }));
    assert(html.includes('ALTITUDE'), 'DroneControl render has ALTITUDE label');
    assert(html.includes('15.3'), 'DroneControl render shows altitude value');
})();

(function testDroneRenderHasAllButtons() {
    const html = DroneControl.render(makeDevice({ type: 'drone' }));
    assert(html.includes('data-cmd="dispatch"'), 'DroneControl has DISPATCH button');
    assert(html.includes('data-cmd="patrol"'), 'DroneControl has PATROL button');
    assert(html.includes('data-cmd="recall"'), 'DroneControl has RECALL button');
    assert(html.includes('data-cmd="stop"'), 'DroneControl has STOP button');
    assert(html.includes('data-cmd="fire"'), 'DroneControl has FIRE button');
    assert(html.includes('data-cmd="send"'), 'DroneControl has SEND button');
})();

(function testDroneBindReusesRoverBind() {
    assert(DroneControl.bind === RoverControl.bind, 'DroneControl.bind is same as RoverControl.bind');
})();

(function testDroneUpdateReusesRoverUpdate() {
    assert(DroneControl.update === RoverControl.update, 'DroneControl.update is same as RoverControl.update');
})();

(function testDroneDestroyReusesRoverDestroy() {
    assert(DroneControl.destroy === RoverControl.destroy, 'DroneControl.destroy is same as RoverControl.destroy');
})();

(function testDroneDispatchEmitsEvent() {
    resetTracking();
    const device = makeDevice({ id: 'drone-dispatch-01', type: 'drone' });
    const container = buildContainerWithButtons(DroneControl, device);
    DroneControl.bind(container, device, DeviceAPI);

    findButton(container, 'dispatch').click();
    const emitted = _eventBusEmits.find(e => e.event === 'unit:dispatch-mode');
    assert(emitted !== undefined, 'Drone DISPATCH emits unit:dispatch-mode');
    assert(emitted && emitted.data.id === 'drone-dispatch-01', 'Drone DISPATCH event has correct id');
})();

(function testDroneRecallCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'drone-recall-01', type: 'drone' });
    const container = buildContainerWithButtons(DroneControl, device);
    DroneControl.bind(container, device, DeviceAPI);

    findButton(container, 'recall').click();
    const call = _fetchCalls.find(c => c.url === '/api/amy/command');
    assert(call !== undefined, 'Drone RECALL calls API');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.action === 'recall', 'Drone RECALL sends recall action');
})();

(function testDroneStopCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'drone-stop-01', type: 'drone' });
    const container = buildContainerWithButtons(DroneControl, device);
    DroneControl.bind(container, device, DeviceAPI);

    findButton(container, 'stop').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/drone-stop-01/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'stop()', 'Drone STOP sends stop()');
})();

// ============================================================
// 6. TurretControl structure and buttons
// ============================================================

console.log('\n--- TurretControl ---');

(function testTurretControlType() {
    assert(TurretControl.type === 'turret', 'TurretControl.type is "turret"');
})();

(function testTurretControlTitle() {
    assert(TurretControl.title === 'TURRET CONTROL', 'TurretControl.title is "TURRET CONTROL"');
})();

(function testTurretRenderHasWeaponRange() {
    const html = TurretControl.render(makeDevice({ type: 'turret', weaponRange: 80 }));
    assert(html.includes('WEAPON RANGE'), 'TurretControl render has WEAPON RANGE label');
    assert(html.includes('80'), 'TurretControl render shows weapon range value');
})();

(function testTurretRenderHasTargetingSliders() {
    const html = TurretControl.render(makeDevice({ type: 'turret' }));
    assert(html.includes('data-axis="pan"'), 'TurretControl has PAN slider');
    assert(html.includes('data-axis="tilt"'), 'TurretControl has TILT slider');
    assert(html.includes('PAN'), 'TurretControl render has PAN label');
    assert(html.includes('TILT'), 'TurretControl render has TILT label');
})();

(function testTurretRenderHasAutoTargetButton() {
    const html = TurretControl.render(makeDevice({ type: 'turret' }));
    assert(html.includes('data-cmd="auto"'), 'TurretControl has AUTO TARGET button');
    assert(html.includes('AUTO TARGET'), 'TurretControl button says AUTO TARGET');
})();

(function testTurretRenderHasManualButton() {
    const html = TurretControl.render(makeDevice({ type: 'turret' }));
    assert(html.includes('data-cmd="manual"'), 'TurretControl has MANUAL button');
    assert(html.includes('MANUAL'), 'TurretControl button says MANUAL');
})();

(function testTurretRenderHasFireButton() {
    const html = TurretControl.render(makeDevice({ type: 'turret' }));
    assert(html.includes('data-cmd="fire"'), 'TurretControl has FIRE button');
})();

(function testTurretRenderHasStopButton() {
    const html = TurretControl.render(makeDevice({ type: 'turret' }));
    assert(html.includes('data-cmd="stop"'), 'TurretControl has STOP button');
})();

(function testTurretAutoTargetCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'turret-auto-01', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'auto').click();

    const call = _fetchCalls.find(c => c.url === '/api/devices/turret-auto-01/command');
    assert(call !== undefined, 'AUTO TARGET calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'auto_target()', 'AUTO TARGET sends auto_target() device command');
})();

(function testTurretAutoTargetSetsStatus() {
    resetTracking();
    const device = makeDevice({ id: 'turret-auto-status', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'auto').click();
    assert(container._statusEl.textContent === 'Auto-targeting enabled', 'AUTO TARGET sets status text');
})();

(function testTurretManualCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'turret-manual-01', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'manual').click();

    const call = _fetchCalls.find(c => c.url === '/api/devices/turret-manual-01/command');
    assert(call !== undefined, 'MANUAL calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'manual_target()', 'MANUAL sends manual_target() device command');
})();

(function testTurretManualSetsStatus() {
    resetTracking();
    const device = makeDevice({ id: 'turret-manual-status', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'manual').click();
    assert(container._statusEl.textContent === 'Manual mode enabled', 'MANUAL sets status text');
})();

(function testTurretFireCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'turret-fire-01', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'fire').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/turret-fire-01/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'fire_nerf()', 'Turret FIRE sends fire_nerf()');
})();

(function testTurretStopCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'turret-stop-01', type: 'turret' });
    const container = buildContainerWithButtons(TurretControl, device);
    TurretControl.bind(container, device, DeviceAPI);

    findButton(container, 'stop').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/turret-stop-01/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'stop()', 'Turret STOP sends stop()');
})();

// ============================================================
// 7. SensorControl structure and buttons
// ============================================================

console.log('\n--- SensorControl ---');

(function testSensorControlType() {
    assert(SensorControl.type === 'sensor', 'SensorControl.type is "sensor"');
})();

(function testSensorControlTitle() {
    assert(SensorControl.title === 'SENSOR CONTROL', 'SensorControl.title is "SENSOR CONTROL"');
})();

(function testSensorRenderHasEnableButton() {
    const html = SensorControl.render(makeDevice({ type: 'sensor' }));
    assert(html.includes('data-cmd="enable"'), 'SensorControl has ENABLE button');
    assert(html.includes('ENABLE'), 'SensorControl button says ENABLE');
})();

(function testSensorRenderHasDisableButton() {
    const html = SensorControl.render(makeDevice({ type: 'sensor' }));
    assert(html.includes('data-cmd="disable"'), 'SensorControl has DISABLE button');
    assert(html.includes('DISABLE'), 'SensorControl button says DISABLE');
})();

(function testSensorRenderHasTestTriggerButton() {
    const html = SensorControl.render(makeDevice({ type: 'sensor' }));
    assert(html.includes('data-cmd="test"'), 'SensorControl has TEST TRIGGER button');
    assert(html.includes('TEST TRIGGER'), 'SensorControl button says TEST TRIGGER');
})();

(function testSensorEnableCallsDeviceCommand() {
    resetTracking();
    const device = makeDevice({ id: 'sensor-enable-01', type: 'sensor' });
    const container = buildContainerWithButtons(SensorControl, device);
    SensorControl.bind(container, device, DeviceAPI);

    findButton(container, 'enable').click();

    const call = _fetchCalls.find(c => c.url.includes('/api/devices/'));
    assert(call !== undefined, 'ENABLE calls /api/devices/ endpoint');
    assert(call && call.url === '/api/devices/sensor-enable-01/command', 'ENABLE calls correct device endpoint');
    // sendDeviceCommand serializes payload directly (topicSuffix is not in body)
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'enable', 'ENABLE sends enable command in body');
})();

(function testSensorDisableCallsDeviceCommand() {
    resetTracking();
    const device = makeDevice({ id: 'sensor-disable-01', type: 'sensor' });
    const container = buildContainerWithButtons(SensorControl, device);
    SensorControl.bind(container, device, DeviceAPI);

    findButton(container, 'disable').click();

    const call = _fetchCalls.find(c => c.url.includes('/api/devices/'));
    assert(call !== undefined, 'DISABLE calls /api/devices/ endpoint');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'disable', 'DISABLE sends disable command in body');
})();

(function testSensorTestTriggerCallsDeviceCommand() {
    resetTracking();
    const device = makeDevice({ id: 'sensor-test-01', type: 'sensor' });
    const container = buildContainerWithButtons(SensorControl, device);
    SensorControl.bind(container, device, DeviceAPI);

    findButton(container, 'test').click();

    const call = _fetchCalls.find(c => c.url.includes('/api/devices/'));
    assert(call !== undefined, 'TEST TRIGGER calls /api/devices/ endpoint');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'test_trigger', 'TEST TRIGGER sends test_trigger command in body');
})();

// ============================================================
// 8. NPCControl structure and buttons
// ============================================================

console.log('\n--- NPCControl ---');

(function testNPCControlType() {
    assert(NPCControl.type === 'npc', 'NPCControl.type is "npc"');
})();

(function testNPCControlTitle() {
    assert(NPCControl.title === 'NPC INTEL', 'NPCControl.title is "NPC INTEL"');
})();

(function testNPCRenderShowsPersonalitySection() {
    const html = NPCControl.render(makeDevice({ type: 'person', alliance: 'neutral', fsm_state: 'wandering' }));
    assert(html.includes('PERSONALITY'), 'NPCControl render has PERSONALITY section');
})();

(function testNPCRenderShowsBrainStateSection() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('BRAIN STATE'), 'NPCControl render has BRAIN STATE section');
})();

(function testNPCRenderShowsThoughtSection() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('CURRENT THOUGHT'), 'NPCControl render has CURRENT THOUGHT section');
})();

(function testNPCRenderShowsThoughtText() {
    const html = NPCControl.render(makeDevice({ type: 'person', thoughtText: 'I wonder what that noise was', thoughtEmotion: 'curious' }));
    assert(html.includes('I wonder what that noise was'), 'NPCControl render shows thought text');
    assert(html.includes('curious'), 'NPCControl render shows thought emotion');
})();

(function testNPCRenderShowsNoActiveThought() {
    const html = NPCControl.render(makeDevice({ type: 'person', thoughtText: null }));
    assert(html.includes('No active thought'), 'NPCControl render shows no-thought placeholder');
})();

(function testNPCRenderShowsThoughtHistory() {
    const now = Date.now();
    const html = NPCControl.render(makeDevice({
        type: 'person',
        thoughtHistory: [
            { text: 'First thought', emotion: 'neutral', time: now - 5000 },
            { text: 'Second thought', emotion: 'afraid', time: now - 2000 },
        ],
    }));
    assert(html.includes('THOUGHT HISTORY'), 'NPCControl render has THOUGHT HISTORY section');
    assert(html.includes('First thought'), 'NPCControl render shows first thought');
    assert(html.includes('Second thought'), 'NPCControl render shows second thought');
})();

(function testNPCRenderHasTakeControlButton() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('data-cmd="take_control"'), 'NPCControl has TAKE CONTROL button');
    assert(html.includes('TAKE CONTROL'), 'NPCControl button says TAKE CONTROL');
})();

(function testNPCRenderHasReleaseButton() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('data-cmd="release_control"'), 'NPCControl has RELEASE button');
    assert(html.includes('RELEASE'), 'NPCControl button says RELEASE');
})();

(function testNPCRenderHasSetThoughtButton() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('data-cmd="set_thought"'), 'NPCControl has SET thought button');
    assert(html.includes('SET THOUGHT'), 'NPCControl has SET THOUGHT label');
})();

(function testNPCRenderHasEmotionSelect() {
    const html = NPCControl.render(makeDevice({ type: 'person' }));
    assert(html.includes('dc-npc-emotion-select'), 'NPCControl has emotion select');
    assert(html.includes('neutral'), 'NPCControl emotion select has neutral option');
    assert(html.includes('curious'), 'NPCControl emotion select has curious option');
    assert(html.includes('afraid'), 'NPCControl emotion select has afraid option');
    assert(html.includes('angry'), 'NPCControl emotion select has angry option');
    assert(html.includes('happy'), 'NPCControl emotion select has happy option');
})();

(function testNPCTakeControlCallsFetch() {
    resetTracking();
    const device = makeDevice({ id: 'npc-take-01', type: 'person' });
    const container = buildContainerWithButtons(NPCControl, device);
    NPCControl.bind(container, device, DeviceAPI);

    findButton(container, 'take_control').click();

    // Should call: POST /api/npc/{id}/control
    const call = _fetchCalls.find(c => c.url.includes('/api/npc/npc-take-01/control') && c.opts && c.opts.method === 'POST');
    assert(call !== undefined, 'TAKE CONTROL calls POST /api/npc/{id}/control');
    if (call) {
        const body = JSON.parse(call.opts.body);
        assert(body.controller_id === 'operator', 'TAKE CONTROL sends controller_id "operator"');
    }
})();

(function testNPCReleaseCallsFetch() {
    resetTracking();
    const device = makeDevice({ id: 'npc-release-01', type: 'person' });
    const container = buildContainerWithButtons(NPCControl, device);
    NPCControl.bind(container, device, DeviceAPI);

    findButton(container, 'release_control').click();

    // Should call: DELETE /api/npc/{id}/control
    const call = _fetchCalls.find(c => c.url.includes('/api/npc/npc-release-01/control') && c.opts && c.opts.method === 'DELETE');
    assert(call !== undefined, 'RELEASE calls DELETE /api/npc/{id}/control');
})();

(function testNPCSetThoughtCallsFetch() {
    resetTracking();
    const device = makeDevice({ id: 'npc-thought-01', type: 'person' });
    const container = buildContainerWithButtons(NPCControl, device);
    NPCControl.bind(container, device, DeviceAPI);

    container._thoughtInputEl.value = 'What is going on?';
    container._emotionSelect.value = 'curious';
    findButton(container, 'set_thought').click();

    // Should call: POST /api/npc/{id}/thought
    const call = _fetchCalls.find(c => c.url.includes('/api/npc/npc-thought-01/thought'));
    assert(call !== undefined, 'SET THOUGHT calls POST /api/npc/{id}/thought');
    if (call) {
        const body = JSON.parse(call.opts.body);
        assert(body.text === 'What is going on?', 'SET THOUGHT sends thought text');
        assert(body.emotion === 'curious', 'SET THOUGHT sends selected emotion');
        assert(body.duration === 5.0, 'SET THOUGHT sends duration 5.0');
    }
})();

(function testNPCSetThoughtIgnoresEmpty() {
    resetTracking();
    const device = makeDevice({ id: 'npc-thought-empty', type: 'person' });
    const container = buildContainerWithButtons(NPCControl, device);
    NPCControl.bind(container, device, DeviceAPI);

    container._thoughtInputEl.value = '';
    findButton(container, 'set_thought').click();

    // The NPC bind handler also fetches /api/npc/{id} on bind, so filter for /thought
    const call = _fetchCalls.find(c => c.url.includes('/thought'));
    assert(call === undefined, 'SET THOUGHT does not call API with empty input');
})();

(function testNPCBindFetchesDetail() {
    resetTracking();
    const device = makeDevice({ id: 'npc-detail-01', type: 'person' });
    const container = buildContainerWithButtons(NPCControl, device);
    NPCControl.bind(container, device, DeviceAPI);

    // Should call: GET /api/npc/{id} to fetch detail
    const call = _fetchCalls.find(c => c.url.includes('/api/npc/npc-detail-01') && !c.url.includes('/control') && !c.url.includes('/thought'));
    assert(call !== undefined, 'NPCControl.bind fetches /api/npc/{id} for detail');
})();

// ============================================================
// 9. CameraControl structure and buttons
// ============================================================

console.log('\n--- CameraControl ---');

(function testCameraControlType() {
    assert(CameraControl.type === 'camera', 'CameraControl.type is "camera"');
})();

(function testCameraControlTitle() {
    assert(CameraControl.title === 'CAMERA CONTROL', 'CameraControl.title is "CAMERA CONTROL"');
})();

(function testCameraRenderShowsStream() {
    const html = CameraControl.render(makeDevice({ id: 'cam-01', type: 'camera' }));
    assert(html.includes('dc-stream'), 'CameraControl has stream section');
    assert(html.includes('dc-stream-img'), 'CameraControl has stream img element');
    assert(html.includes('/api/amy/nodes/cam-01/video'), 'CameraControl stream points to correct endpoint');
})();

(function testCameraRenderShowsPtzWhenHasPtz() {
    const html = CameraControl.render(makeDevice({ type: 'camera', hasPtz: true }));
    assert(html.includes('PTZ'), 'CameraControl shows PTZ section when hasPtz is true');
    assert(html.includes('data-cmd="ptz_left"'), 'CameraControl has LEFT PTZ button');
    assert(html.includes('data-cmd="ptz_up"'), 'CameraControl has UP PTZ button');
    assert(html.includes('data-cmd="ptz_down"'), 'CameraControl has DOWN PTZ button');
    assert(html.includes('data-cmd="ptz_right"'), 'CameraControl has RIGHT PTZ button');
})();

(function testCameraRenderNoPtzWhenNotPtz() {
    const html = CameraControl.render(makeDevice({ type: 'camera', hasPtz: false }));
    assert(!html.includes('data-cmd="ptz_left"'), 'CameraControl hides PTZ buttons when hasPtz is false');
})();

(function testCameraRenderHasSnapshotButton() {
    const html = CameraControl.render(makeDevice({ type: 'camera' }));
    assert(html.includes('data-cmd="snapshot"'), 'CameraControl has SNAPSHOT button');
    assert(html.includes('SNAPSHOT'), 'CameraControl button says SNAPSHOT');
})();

(function testCameraRenderHasOffButton() {
    const html = CameraControl.render(makeDevice({ type: 'camera' }));
    assert(html.includes('data-cmd="camera_off"'), 'CameraControl has OFF button');
    assert(html.includes('OFF'), 'CameraControl button says OFF');
})();

(function testCameraPtzLeftCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'cam-ptz-left', type: 'camera', hasPtz: true });
    const container = buildContainerWithButtons(CameraControl, device);
    CameraControl.bind(container, device, DeviceAPI);

    findButton(container, 'ptz_left').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/cam-ptz-left/command');
    assert(call !== undefined, 'PTZ LEFT calls /api/devices/{id}/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.aim(-10,0)', 'PTZ LEFT sends motor.aim(-10,0)');
})();

(function testCameraPtzRightCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'cam-ptz-right', type: 'camera', hasPtz: true });
    const container = buildContainerWithButtons(CameraControl, device);
    CameraControl.bind(container, device, DeviceAPI);

    findButton(container, 'ptz_right').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/cam-ptz-right/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.aim(10,0)', 'PTZ RIGHT sends motor.aim(10,0)');
})();

(function testCameraPtzUpCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'cam-ptz-up', type: 'camera', hasPtz: true });
    const container = buildContainerWithButtons(CameraControl, device);
    CameraControl.bind(container, device, DeviceAPI);

    findButton(container, 'ptz_up').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/cam-ptz-up/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.aim(0,10)', 'PTZ UP sends motor.aim(0,10)');
})();

(function testCameraPtzDownCallsAPI() {
    resetTracking();
    const device = makeDevice({ id: 'cam-ptz-down', type: 'camera', hasPtz: true });
    const container = buildContainerWithButtons(CameraControl, device);
    CameraControl.bind(container, device, DeviceAPI);

    findButton(container, 'ptz_down').click();
    const call = _fetchCalls.find(c => c.url === '/api/devices/cam-ptz-down/command');
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.aim(0,-10)', 'PTZ DOWN sends motor.aim(0,-10)');
})();

(function testCameraOffCallsDeviceCommand() {
    resetTracking();
    const device = makeDevice({ id: 'cam-off-01', type: 'camera' });
    const container = buildContainerWithButtons(CameraControl, device);
    CameraControl.bind(container, device, DeviceAPI);

    findButton(container, 'camera_off').click();
    const call = _fetchCalls.find(c => c.url.includes('/api/devices/'));
    assert(call !== undefined, 'Camera OFF calls /api/devices/ endpoint');
    assert(call && call.url === '/api/devices/cam-off-01/command', 'Camera OFF calls correct device endpoint');
    // sendDeviceCommand serializes payload directly
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'camera_off', 'Camera OFF sends camera_off command in body');
})();

(function testCameraDestroyStopsMjpegStream() {
    // Build a container with a mock .dc-stream-img that CameraControl.destroy can find
    const imgEl = createMockElement('img');
    imgEl.className = 'dc-stream-img';
    imgEl.src = '/api/amy/nodes/cam-destroy-01/video';
    const container = createMockElement('div');
    const origQs = container.querySelector.bind(container);
    container.querySelector = function(sel) {
        if (sel === '.dc-stream-img') return imgEl;
        return origQs(sel);
    };
    assert(imgEl.src.includes('/api/amy/nodes/'), 'MJPEG src is set before destroy');
    CameraControl.destroy(container);
    assert(imgEl.src === '', 'CameraControl.destroy clears MJPEG img src to stop stream');
})();

// ============================================================
// 10. MeshRadioControl structure and buttons
// ============================================================

console.log('\n--- MeshRadioControl ---');

(function testMeshRadioControlType() {
    assert(MeshRadioControl.type === 'mesh_radio', 'MeshRadioControl.type is "mesh_radio"');
})();

(function testMeshRadioControlTitle() {
    assert(MeshRadioControl.title === 'MESH RADIO', 'MeshRadioControl.title is "MESH RADIO"');
})();

(function testMeshRadioRenderShowsProtocol() {
    const html = MeshRadioControl.render(makeDevice({ type: 'mesh_radio', meshProtocol: 'meshtastic' }));
    assert(html.includes('PROTOCOL'), 'MeshRadioControl has PROTOCOL label');
    assert(html.includes('meshtastic'), 'MeshRadioControl shows protocol value');
})();

(function testMeshRadioRenderShowsSignalStats() {
    const html = MeshRadioControl.render(makeDevice({ type: 'mesh_radio', snr: 12, rssi: -65, hops: 2 }));
    assert(html.includes('SNR'), 'MeshRadioControl has SNR label');
    assert(html.includes('RSSI'), 'MeshRadioControl has RSSI label');
    assert(html.includes('HOPS'), 'MeshRadioControl has HOPS label');
})();

(function testMeshRadioRenderHasSendButton() {
    const html = MeshRadioControl.render(makeDevice({ type: 'mesh_radio' }));
    assert(html.includes('data-cmd="send_text"'), 'MeshRadioControl has SEND button');
    assert(html.includes('dc-mesh-text'), 'MeshRadioControl has text input');
    assert(html.includes('maxlength="228"'), 'MeshRadioControl input has 228 char limit');
})();

(function testMeshRadioRenderHasCenterButton() {
    const html = MeshRadioControl.render(makeDevice({ type: 'mesh_radio' }));
    assert(html.includes('data-cmd="center"'), 'MeshRadioControl has CENTER ON MAP button');
    assert(html.includes('CENTER ON MAP'), 'MeshRadioControl button says CENTER ON MAP');
})();

(function testMeshRadioSendTextCallsDeviceCommand() {
    resetTracking();
    const device = makeDevice({ id: 'mesh-send-01', type: 'mesh_radio' });
    const container = buildContainerWithButtons(MeshRadioControl, device);
    MeshRadioControl.bind(container, device, DeviceAPI);

    container._meshInputEl.value = 'Hello mesh network';
    findButton(container, 'send_text').click();

    const call = _fetchCalls.find(c => c.url.includes('/api/devices/'));
    assert(call !== undefined, 'SEND TEXT calls /api/devices/ endpoint');
    // sendDeviceCommand serializes payload directly
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.text === 'Hello mesh network', 'SEND TEXT sends the message text in body');
})();

(async function testMeshRadioSendTextClearsInput() {
    resetTracking();
    const device = makeDevice({ id: 'mesh-clear-01', type: 'mesh_radio' });
    const container = buildContainerWithButtons(MeshRadioControl, device);
    MeshRadioControl.bind(container, device, DeviceAPI);

    container._meshInputEl.value = 'Test message';
    findButton(container, 'send_text').click();
    await Promise.resolve(); // let .then() fire
    assert(container._meshInputEl.value === '', 'SEND TEXT clears the input after sending');
})();

(function testMeshRadioSendTextIgnoresEmpty() {
    resetTracking();
    const device = makeDevice({ id: 'mesh-empty-01', type: 'mesh_radio' });
    const container = buildContainerWithButtons(MeshRadioControl, device);
    MeshRadioControl.bind(container, device, DeviceAPI);

    container._meshInputEl.value = '';
    findButton(container, 'send_text').click();
    assert(_fetchCalls.length === 0, 'SEND TEXT does not call API with empty input');
})();

(function testMeshRadioCenterEmitsEvent() {
    resetTracking();
    const device = makeDevice({ id: 'mesh-center-01', type: 'mesh_radio' });
    const container = buildContainerWithButtons(MeshRadioControl, device);
    MeshRadioControl.bind(container, device, DeviceAPI);

    findButton(container, 'center').click();
    const emitted = _eventBusEmits.find(e => e.event === 'mesh:center-on-node');
    assert(emitted !== undefined, 'CENTER ON MAP emits mesh:center-on-node event');
    assert(emitted && emitted.data.id === 'mesh-center-01', 'CENTER ON MAP event has correct device id');
})();

// ============================================================
// 11. GenericControl structure
// ============================================================

console.log('\n--- GenericControl ---');

(function testGenericControlType() {
    assert(GenericControl.type === '_generic', 'GenericControl.type is "_generic"');
})();

(function testGenericControlTitle() {
    assert(GenericControl.title === 'DEVICE', 'GenericControl.title is "DEVICE"');
})();

(function testGenericRenderShowsBasicInfo() {
    const html = GenericControl.render(makeDevice({ name: 'Unknown Gadget', type: 'widget' }));
    assert(html.includes('Unknown Gadget'), 'GenericControl shows device name');
    assert(html.includes('widget'), 'GenericControl shows device type');
})();

(function testGenericRenderHasSendButton() {
    const html = GenericControl.render(makeDevice());
    assert(html.includes('data-cmd="send"'), 'GenericControl has SEND button');
    assert(html.includes('dc-cmd-input'), 'GenericControl has Lua command input');
})();

(function testGenericBindIsRoverBind() {
    assert(GenericControl.bind === RoverControl.bind, 'GenericControl.bind reuses RoverControl.bind');
})();

// ============================================================
// 12. DeviceControlRegistry -- direct type lookups
// ============================================================

console.log('\n--- DeviceControlRegistry direct lookups ---');

(function testRegistryRover() {
    const ctrl = DeviceControlRegistry.get('rover');
    assert(ctrl === RoverControl, 'Registry "rover" returns RoverControl');
})();

(function testRegistryDrone() {
    const ctrl = DeviceControlRegistry.get('drone');
    assert(ctrl === DroneControl, 'Registry "drone" returns DroneControl');
})();

(function testRegistryTurret() {
    const ctrl = DeviceControlRegistry.get('turret');
    assert(ctrl === TurretControl, 'Registry "turret" returns TurretControl');
})();

(function testRegistrySensor() {
    const ctrl = DeviceControlRegistry.get('sensor');
    assert(ctrl === SensorControl, 'Registry "sensor" returns SensorControl');
})();

(function testRegistryNpc() {
    const ctrl = DeviceControlRegistry.get('npc');
    assert(ctrl === NPCControl, 'Registry "npc" returns NPCControl');
})();

(function testRegistryCamera() {
    const ctrl = DeviceControlRegistry.get('camera');
    assert(ctrl === CameraControl, 'Registry "camera" returns CameraControl');
})();

(function testRegistryMeshRadio() {
    const ctrl = DeviceControlRegistry.get('mesh_radio');
    assert(ctrl === MeshRadioControl, 'Registry "mesh_radio" returns MeshRadioControl');
})();

// ============================================================
// 13. DeviceControlRegistry -- alias lookups
// ============================================================

console.log('\n--- DeviceControlRegistry aliases ---');

(function testAliasScoutDrone() {
    const ctrl = DeviceControlRegistry.get('scout_drone');
    assert(ctrl === DroneControl, 'Alias "scout_drone" resolves to DroneControl');
})();

(function testAliasSwarmDrone() {
    const ctrl = DeviceControlRegistry.get('swarm_drone');
    assert(ctrl === DroneControl, 'Alias "swarm_drone" resolves to DroneControl');
})();

(function testAliasHeavyTurret() {
    const ctrl = DeviceControlRegistry.get('heavy_turret');
    assert(ctrl === TurretControl, 'Alias "heavy_turret" resolves to TurretControl');
})();

(function testAliasMissileTurret() {
    const ctrl = DeviceControlRegistry.get('missile_turret');
    assert(ctrl === TurretControl, 'Alias "missile_turret" resolves to TurretControl');
})();

(function testAliasTank() {
    const ctrl = DeviceControlRegistry.get('tank');
    assert(ctrl === RoverControl, 'Alias "tank" resolves to RoverControl');
})();

(function testAliasApc() {
    const ctrl = DeviceControlRegistry.get('apc');
    assert(ctrl === RoverControl, 'Alias "apc" resolves to RoverControl');
})();

(function testAliasPerson() {
    const ctrl = DeviceControlRegistry.get('person');
    assert(ctrl === NPCControl, 'Alias "person" resolves to NPCControl');
})();

(function testAliasAnimal() {
    const ctrl = DeviceControlRegistry.get('animal');
    assert(ctrl === NPCControl, 'Alias "animal" resolves to NPCControl');
})();

(function testAliasVehicle() {
    const ctrl = DeviceControlRegistry.get('vehicle');
    assert(ctrl === NPCControl, 'Alias "vehicle" resolves to NPCControl');
})();

(function testAliasPir() {
    const ctrl = DeviceControlRegistry.get('pir');
    assert(ctrl === SensorControl, 'Alias "pir" resolves to SensorControl');
})();

(function testAliasMicrowave() {
    const ctrl = DeviceControlRegistry.get('microwave');
    assert(ctrl === SensorControl, 'Alias "microwave" resolves to SensorControl');
})();

(function testAliasAcoustic() {
    const ctrl = DeviceControlRegistry.get('acoustic');
    assert(ctrl === SensorControl, 'Alias "acoustic" resolves to SensorControl');
})();

(function testAliasTripwire() {
    const ctrl = DeviceControlRegistry.get('tripwire');
    assert(ctrl === SensorControl, 'Alias "tripwire" resolves to SensorControl');
})();

(function testAliasMeshtastic() {
    const ctrl = DeviceControlRegistry.get('meshtastic');
    assert(ctrl === MeshRadioControl, 'Alias "meshtastic" resolves to MeshRadioControl');
})();

(function testAliasMeshcore() {
    const ctrl = DeviceControlRegistry.get('meshcore');
    assert(ctrl === MeshRadioControl, 'Alias "meshcore" resolves to MeshRadioControl');
})();

(function testAliasIpCamera() {
    const ctrl = DeviceControlRegistry.get('ip_camera');
    assert(ctrl === CameraControl, 'Alias "ip_camera" resolves to CameraControl');
})();

(function testAliasPtzCamera() {
    const ctrl = DeviceControlRegistry.get('ptz_camera');
    assert(ctrl === CameraControl, 'Alias "ptz_camera" resolves to CameraControl');
})();

(function testAliasSyntheticCamera() {
    const ctrl = DeviceControlRegistry.get('synthetic_camera');
    assert(ctrl === CameraControl, 'Alias "synthetic_camera" resolves to CameraControl');
})();

// ============================================================
// 14. DeviceControlRegistry -- unknown type fallback
// ============================================================

console.log('\n--- DeviceControlRegistry fallback ---');

(function testUnknownTypeFallsBackToGeneric() {
    const ctrl = DeviceControlRegistry.get('completely_unknown_device');
    assert(ctrl === GenericControl, 'Unknown type "completely_unknown_device" returns GenericControl');
})();

(function testEmptyStringFallsBackToGeneric() {
    const ctrl = DeviceControlRegistry.get('');
    assert(ctrl === GenericControl, 'Empty string returns GenericControl');
})();

(function testUndefinedFallsBackToGeneric() {
    const ctrl = DeviceControlRegistry.get(undefined);
    assert(ctrl === GenericControl, 'Undefined type returns GenericControl');
})();

// ============================================================
// 15. DeviceControlRegistry -- getRegisteredTypes
// ============================================================

console.log('\n--- DeviceControlRegistry getRegisteredTypes ---');

(function testGetRegisteredTypesReturnsAllDirectTypes() {
    const types = DeviceControlRegistry.getRegisteredTypes();
    assert(types.includes('rover'), 'Registered types includes rover');
    assert(types.includes('drone'), 'Registered types includes drone');
    assert(types.includes('turret'), 'Registered types includes turret');
    assert(types.includes('sensor'), 'Registered types includes sensor');
    assert(types.includes('npc'), 'Registered types includes npc');
    assert(types.includes('camera'), 'Registered types includes camera');
    assert(types.includes('mesh_radio'), 'Registered types includes mesh_radio');
    assert(types.length === 7, 'Registered types has exactly 7 entries, got ' + types.length);
})();

// ============================================================
// 16. DeviceAPI -- sendCommand
// ============================================================

console.log('\n--- DeviceAPI sendCommand ---');

(function testSendCommandCallsCorrectEndpoint() {
    resetTracking();
    DeviceAPI.sendCommand('unit-42', 'fire_nerf()');
    const call = _fetchCalls[0];
    assert(call !== undefined, 'sendCommand makes a fetch call');
    assert(call && call.url === '/api/devices/unit-42/command', 'sendCommand delegates to /api/devices/{id}/command');
    assert(call && call.opts.method === 'POST', 'sendCommand uses POST method');
})();

(function testSendCommandBody() {
    resetTracking();
    DeviceAPI.sendCommand('rover-07', 'patrol({10,20},{30,40})');
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'patrol({10,20},{30,40})', 'sendCommand body.command contains Lua string');
    assert(!body.target_id, 'sendCommand does not send target_id (device id is in URL)');
})();

(function testSendCommandHeaders() {
    resetTracking();
    DeviceAPI.sendCommand('x', 'y');
    const call = _fetchCalls[0];
    assert(call && call.opts.headers['Content-Type'] === 'application/json', 'sendCommand sends JSON content type');
})();

// ============================================================
// 17. DeviceAPI -- sendDeviceCommand
// ============================================================

console.log('\n--- DeviceAPI sendDeviceCommand ---');

(function testSendDeviceCommandCallsCorrectEndpoint() {
    resetTracking();
    DeviceAPI.sendDeviceCommand('sensor-05', 'command', { command: 'enable' });
    const call = _fetchCalls[0];
    assert(call !== undefined, 'sendDeviceCommand makes a fetch call');
    assert(call && call.url === '/api/devices/sensor-05/command', 'sendDeviceCommand calls /api/devices/{id}/command');
    assert(call && call.opts.method === 'POST', 'sendDeviceCommand uses POST method');
})();

(function testSendDeviceCommandBody() {
    resetTracking();
    DeviceAPI.sendDeviceCommand('mesh-03', 'text', { text: 'Hello' });
    const call = _fetchCalls[0];
    // sendDeviceCommand serializes the payload directly, topicSuffix is not in the body
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.text === 'Hello', 'sendDeviceCommand body contains payload fields directly');
})();

// ============================================================
// 18. DeviceAPI -- dispatch
// ============================================================

console.log('\n--- DeviceAPI dispatch ---');

(function testDispatchCallsCorrectEndpoint() {
    resetTracking();
    DeviceAPI.dispatch('rover-01', 50.5, 100.2);
    const call = _fetchCalls[0];
    assert(call !== undefined, 'dispatch makes a fetch call');
    assert(call && call.url === '/api/amy/simulation/dispatch', 'dispatch calls /api/amy/simulation/dispatch');
    assert(call && call.opts.method === 'POST', 'dispatch uses POST method');
})();

(function testDispatchBody() {
    resetTracking();
    DeviceAPI.dispatch('drone-02', 10, 20);
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.unit_id === 'drone-02', 'dispatch body has correct unit_id');
    assert(body.target && body.target.x === 10, 'dispatch body has target.x');
    assert(body.target && body.target.y === 20, 'dispatch body has target.y');
})();

// ============================================================
// 19. DeviceAPI -- recall, stop, fire, aim, patrol
// ============================================================

console.log('\n--- DeviceAPI convenience methods ---');

(function testRecallUsesParamsFormat() {
    resetTracking();
    DeviceAPI.recall('unit-r1');
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.action === 'recall', 'DeviceAPI.recall sends recall action');
    assert(Array.isArray(body.params) && body.params[0] === 'unit-r1', 'DeviceAPI.recall sends unit id in params array');
    assert(!body.target_id, 'DeviceAPI.recall does not send target_id (Pydantic drops it)');
})();

(function testStopCallsSendCommand() {
    resetTracking();
    DeviceAPI.stop('unit-s1');
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'stop()', 'DeviceAPI.stop sends stop() via device route');
    assert(call && call.url === '/api/devices/unit-s1/command', 'DeviceAPI.stop routes to device endpoint');
})();

(function testFireCallsSendCommand() {
    resetTracking();
    DeviceAPI.fire('unit-f1', 10, 20);
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'fire_nerf()', 'DeviceAPI.fire sends fire_nerf() via device route');
    assert(call && call.url === '/api/devices/unit-f1/command', 'DeviceAPI.fire routes to device endpoint');
})();

(function testAimCallsSendCommand() {
    resetTracking();
    DeviceAPI.aim('unit-a1', 45, -10);
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.command === 'motor.aim(45,-10)', 'DeviceAPI.aim sends motor.aim(45,-10) via device route');
    assert(call && call.url === '/api/devices/unit-a1/command', 'DeviceAPI.aim routes to device endpoint');
})();

(function testPatrolUsesParamsFormat() {
    resetTracking();
    DeviceAPI.patrol('unit-p1', [{ x: 10, y: 20 }, { x: 30, y: 40 }]);
    const call = _fetchCalls[0];
    const body = call ? JSON.parse(call.opts.body) : {};
    assert(body.action === 'patrol', 'DeviceAPI.patrol sends patrol action');
    assert(Array.isArray(body.params), 'DeviceAPI.patrol sends params array');
    assert(body.params && body.params[0] === 'unit-p1', 'DeviceAPI.patrol sends unit id as first param');
    const wpsParsed = body.params ? JSON.parse(body.params[1]) : [];
    assert(Array.isArray(wpsParsed) && wpsParsed[0][0] === 10 && wpsParsed[0][1] === 20, 'DeviceAPI.patrol sends waypoints as JSON array [[x,y],...]');
    assert(!body.target_id, 'DeviceAPI.patrol does not send target_id');
})();

// ============================================================
// 20. DeviceModalManager -- open / close lifecycle
// ============================================================

console.log('\n--- DeviceModalManager lifecycle ---');

(function testModalManagerStartsClosed() {
    DeviceModalManager.close();
    assert(DeviceModalManager.isOpen() === false, 'ModalManager starts closed');
    assert(DeviceModalManager.getCurrentDeviceId() === null, 'ModalManager has no current device id');
})();

(function testModalManagerOpens() {
    resetTracking();
    DeviceModalManager.close();
    DeviceModalManager.open('rover-01', 'rover', makeDevice({ id: 'rover-01' }));
    assert(DeviceModalManager.isOpen() === true, 'ModalManager is open after open()');
    assert(DeviceModalManager.getCurrentDeviceId() === 'rover-01', 'ModalManager tracks current device id');
    DeviceModalManager.close();
})();

(function testModalManagerEmitsOpenEvent() {
    resetTracking();
    DeviceModalManager.close();
    DeviceModalManager.open('drone-02', 'drone', makeDevice({ id: 'drone-02', type: 'drone' }));
    const emitted = _eventBusEmits.find(e => e.event === 'device:modal_opened');
    assert(emitted !== undefined, 'ModalManager open emits device:modal_opened');
    assert(emitted && emitted.data.deviceId === 'drone-02', 'device:modal_opened has correct deviceId');
    assert(emitted && emitted.data.deviceType === 'drone', 'device:modal_opened has correct deviceType');
    DeviceModalManager.close();
})();

(function testModalManagerCloses() {
    DeviceModalManager.open('rover-01', 'rover', makeDevice());
    DeviceModalManager.close();
    assert(DeviceModalManager.isOpen() === false, 'ModalManager is closed after close()');
    assert(DeviceModalManager.getCurrentDeviceId() === null, 'Device id is null after close');
})();

(function testModalManagerEmitsCloseEvent() {
    resetTracking();
    DeviceModalManager.open('rover-01', 'rover', makeDevice());
    resetTracking();
    DeviceModalManager.close();
    const emitted = _eventBusEmits.find(e => e.event === 'device:modal_closed');
    assert(emitted !== undefined, 'ModalManager close emits device:modal_closed');
})();

(function testModalManagerClosesExistingBeforeOpening() {
    resetTracking();
    DeviceModalManager.close();
    DeviceModalManager.open('rover-01', 'rover', makeDevice({ id: 'rover-01' }));
    DeviceModalManager.open('drone-02', 'drone', makeDevice({ id: 'drone-02', type: 'drone' }));
    assert(DeviceModalManager.getCurrentDeviceId() === 'drone-02', 'Opening new modal replaces previous');
    DeviceModalManager.close();
})();

(function testModalManagerDoubleCloseIsSafe() {
    DeviceModalManager.close();
    let threw = false;
    try {
        DeviceModalManager.close();
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'Double close does not throw');
})();

(function testModalManagerUpdateDoesNotCrashWhenClosed() {
    DeviceModalManager.close();
    let threw = false;
    try {
        DeviceModalManager.update(makeDevice());
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'update() when closed does not throw');
})();

// ============================================================
// 21. Helper functions (_esc, _pct, _healthColor, _batteryStr)
// ============================================================

console.log('\n--- Helper functions ---');

(function testEscFunction() {
    const _esc = vm.runInContext('_esc', ctx);
    assert(_esc('<script>alert(1)</script>').includes('&lt;'), '_esc escapes < to &lt;');
    assert(_esc('"quoted"').includes('&quot;'), '_esc escapes " to &quot;');
    assert(_esc('normal text') === 'normal text', '_esc passes normal text through');
    assert(_esc(null) === '', '_esc handles null');
    assert(_esc(undefined) === '', '_esc handles undefined');
    assert(_esc(42) === '42', '_esc handles numbers');
})();

(function testPctFunction() {
    const _pct = vm.runInContext('_pct', ctx);
    assert(_pct(50, 100) === 50, '_pct(50,100) is 50');
    assert(_pct(0, 100) === 0, '_pct(0,100) is 0');
    assert(_pct(100, 100) === 100, '_pct(100,100) is 100');
    assert(_pct(1, 3) === 33, '_pct(1,3) rounds to 33');
    assert(_pct(10, 0) === 0, '_pct with max=0 returns 0');
    assert(_pct(10, null) === 0, '_pct with null max returns 0');
})();

(function testHealthColorFunction() {
    const _healthColor = vm.runInContext('_healthColor', ctx);
    assert(_healthColor(100) === '#05ffa1', '_healthColor(100) is green');
    assert(_healthColor(61) === '#05ffa1', '_healthColor(61) is green');
    assert(_healthColor(60) === '#fcee0a', '_healthColor(60) is yellow');
    assert(_healthColor(31) === '#fcee0a', '_healthColor(31) is yellow');
    assert(_healthColor(30) === '#ff2a6d', '_healthColor(30) is red');
    assert(_healthColor(0) === '#ff2a6d', '_healthColor(0) is red');
})();

(function testBatteryStrFunction() {
    // battery values are already 0-100 in the store (websocket.js converts from backend 0-1)
    const _batteryStr = vm.runInContext('_batteryStr', ctx);
    assert(_batteryStr(85) === '85%', '_batteryStr(85) is "85%"');
    assert(_batteryStr(100) === '100%', '_batteryStr(100) is "100%"');
    assert(_batteryStr(0) === '0%', '_batteryStr(0) is "0%"');
    assert(_batteryStr(null) === '--', '_batteryStr(null) is "--"');
    assert(_batteryStr(undefined) === '--', '_batteryStr(undefined) is "--"');
})();

// ============================================================
// 22. Edge cases
// ============================================================

console.log('\n--- Edge cases ---');

(function testRenderWithMissingPosition() {
    let threw = false;
    try {
        RoverControl.render({ id: 'no-pos', name: 'No Pos', health: 100, maxHealth: 100 });
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'RoverControl.render handles missing position gracefully');
})();

(function testRenderWithNullBattery() {
    const html = RoverControl.render(makeDevice({ battery: null }));
    assert(html.includes('--'), 'RoverControl shows "--" for null battery');
})();

(function testRenderWithZeroHealth() {
    const html = RoverControl.render(makeDevice({ health: 0, maxHealth: 100 }));
    assert(html.includes('#ff2a6d'), 'Zero health shows red color');
    assert(html.includes('0/100'), 'Zero health shows 0/100');
})();

(function testNPCRenderWithAlliance() {
    const html = NPCControl.render(makeDevice({ type: 'person', alliance: 'hostile' }));
    assert(html.includes('HOSTILE'), 'NPCControl shows HOSTILE alliance');
})();

(function testCameraRenderEscapesDeviceId() {
    const html = CameraControl.render(makeDevice({ id: '<bad-id>', type: 'camera' }));
    assert(!html.includes('<bad-id>'), 'CameraControl escapes device id in URLs');
})();

(function testSensorRenderShowsPosition() {
    const html = SensorControl.render(makeDevice({ type: 'sensor', position: { x: 12.3, y: 45.6 } }));
    assert(html.includes('12.3'), 'SensorControl shows x position');
    assert(html.includes('45.6'), 'SensorControl shows y position');
})();

(function testGenericRenderWithNullName() {
    const html = GenericControl.render({ id: 'test-null-name', position: { x: 0, y: 0 }, status: 'idle' });
    assert(html.includes('test-null-name'), 'GenericControl falls back to id when name is null');
})();

// ============================================================
// 16. Turret PAN/TILT sliders send motor.aim() (debounced)
// ============================================================

console.log('\n--- Turret PAN/TILT sliders send aim commands ---');

(function testTurretSliderBindListensToInput() {
    // Verify the turret bind code references 'data-axis' in slider event handler
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes('api.aim(device.id, pan, tilt)'), 'TurretControl.bind sends api.aim() on slider input');
})();

(function testTurretSliderHasDebounce() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes('_aimTimer') && code.includes('clearTimeout'), 'TurretControl slider uses debounce timer');
})();

(function testTurretSliderReadsAxisFromDOM() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes('[data-axis="pan"]') && code.includes('[data-axis="tilt"]'),
        'TurretControl slider reads pan/tilt axis from DOM');
})();

// ============================================================
// 17. TAKE CONTROL sets controlledUnitId and emits event
// ============================================================

console.log('\n--- TAKE CONTROL sets store + emits event ---');

(function testTakeControlSetsControlledUnitId() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes("TritiumStore.set('controlledUnitId'"),
        'TAKE CONTROL handler sets controlledUnitId in store');
})();

(function testTakeControlEmitsEvent() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes("EventBus.emit('unit:control-acquired'"),
        'TAKE CONTROL handler emits unit:control-acquired event');
})();

(function testReleaseControlClearsStore() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes("TritiumStore.set('controlledUnitId', null)"),
        'RELEASE handler clears controlledUnitId to null');
})();

(function testReleaseControlEmitsEvent() {
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    assert(code.includes("EventBus.emit('unit:control-released'"),
        'RELEASE handler emits unit:control-released event');
})();

// ============================================================
// Battery display (double-multiplication regression)
// ============================================================

console.log('\n--- Battery display ---');

(function testBatteryStrNotDoubleMultiplied() {
    // websocket.js converts 0-1 to 0-100 before storing.
    // _batteryStr must NOT multiply by 100 again.
    const code = fs.readFileSync(__dirname + '/../../src/frontend/js/command/device-modal.js', 'utf8');
    // The function should use Math.round(bat) not Math.round(bat * 100)
    assert(!code.includes('Math.round(bat * 100)'),
        '_batteryStr does not double-multiply battery by 100');
    assert(code.includes('Math.round(bat)'),
        '_batteryStr uses Math.round(bat) for already-converted percentage');
})();

(function testBatteryStrRendersCorrectValue() {
    // Render a rover with battery=75 (already 0-100 from websocket.js)
    const roverControl = DeviceControlRegistry.get('rover');
    const html = roverControl.render({
        id: 'rover-bat', name: 'Rover Battery Test', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        speed: 0, battery: 75, health: 100, maxHealth: 100, status: 'active',
    });
    // Should show "75%" not "7500%"
    assert(html.includes('75%'), 'Rover battery renders as 75% not 7500%');
    assert(!html.includes('7500%'), 'Battery is not doubled to 7500%');
})();

(function testBatteryStrNull() {
    const roverControl = DeviceControlRegistry.get('rover');
    const html = roverControl.render({
        id: 'rover-no-bat', name: 'No Battery', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        speed: 0, battery: null, health: 100, maxHealth: 100, status: 'active',
    });
    assert(html.includes('--'), 'Null battery shows -- placeholder');
})();

(function testBatteryStrUndefined() {
    const roverControl = DeviceControlRegistry.get('rover');
    const html = roverControl.render({
        id: 'rover-undef-bat', name: 'Undef Battery', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        speed: 0, health: 100, maxHealth: 100, status: 'active',
    });
    assert(html.includes('--'), 'Undefined battery shows -- placeholder');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(50));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(50));
process.exit(failed > 0 ? 1 : 0);
