// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Mesh Radio Panel tests
 * Tests MeshPanelDef structure, DOM creation, tab switching, char limit,
 * node rendering, message rendering, and scan/radio tab presence.
 * Run: node tests/js/test_mesh_panel.js
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

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) {
            _innerHTML = val;
            el._parsedBinds = {};
            const bindMatches = val.matchAll(/data-bind="([^"]+)"/g);
            for (const m of bindMatches) el._parsedBinds[m[1]] = true;
            el._parsedActions = {};
            const actionMatches = val.matchAll(/data-action="([^"]+)"/g);
            for (const m of actionMatches) el._parsedActions[m[1]] = true;
        },
        textContent: '',
        style,
        dataset,
        children,
        scrollHeight: 0,
        scrollTop: 0,
        value: '',
        maxLength: -1,
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
        remove() {},
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement('div');
                mock._bindName = bindMatch[1];
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createMockElement('button');
                mock._actionName = actionMatch[1];
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createMockElement('div');
                mock.className = classMatch[1];
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) {
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch && el.className.includes(classMatch[1])) return el;
            return null;
        },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval,
    document: {
        createElement: createMockElement,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: false }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js (EventBus)
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load store.js (TritiumStore)
const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
const storePlain = storeCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(storePlain, ctx);

// Load mesh.js panel
const meshCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/mesh.js', 'utf8');
const meshPlain = meshCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(meshPlain, ctx);

const MeshPanelDef = ctx.MeshPanelDef;

// ============================================================
// 1. MeshPanelDef has required properties
// ============================================================

console.log('\n--- MeshPanelDef structure ---');

(function testHasId() {
    assert(MeshPanelDef.id === 'mesh', 'MeshPanelDef.id is "mesh"');
})();

(function testHasTitle() {
    assert(MeshPanelDef.title === 'MESHTASTIC', 'MeshPanelDef.title is "MESHTASTIC"');
})();

(function testHasCreate() {
    assert(typeof MeshPanelDef.create === 'function', 'MeshPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof MeshPanelDef.mount === 'function', 'MeshPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof MeshPanelDef.unmount === 'function', 'MeshPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(MeshPanelDef.defaultPosition !== undefined, 'MeshPanelDef has defaultPosition');
    assert(typeof MeshPanelDef.defaultPosition.x === 'number', 'defaultPosition.x is a number');
    assert(typeof MeshPanelDef.defaultPosition.y === 'number', 'defaultPosition.y is a number');
})();

(function testHasDefaultSize() {
    assert(MeshPanelDef.defaultSize !== undefined, 'MeshPanelDef has defaultSize');
    assert(MeshPanelDef.defaultSize.w > 0, 'defaultSize.w is positive');
    assert(MeshPanelDef.defaultSize.h > 0, 'defaultSize.h is positive');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = MeshPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'mesh-panel-inner', 'create() element has correct className');
})();

(function testCreateHasTabs() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="tabs"'), 'DOM contains tab bar');
    assert(html.includes('data-tab="nodes"'), 'DOM contains Nodes tab');
    assert(html.includes('data-tab="chat"'), 'DOM contains Chat tab');
    assert(html.includes('data-tab="radio"'), 'DOM contains Radio tab');
    assert(html.includes('data-tab="scan"'), 'DOM contains Scan tab');
})();

(function testCreateHasTabPanes() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-pane="nodes"'), 'DOM contains nodes pane');
    assert(html.includes('data-pane="chat"'), 'DOM contains chat pane');
    assert(html.includes('data-pane="radio"'), 'DOM contains radio pane');
    assert(html.includes('data-pane="scan"'), 'DOM contains scan pane');
})();

(function testCreateHasStatusBar() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="status"'), 'DOM contains status bar');
    assert(html.includes('data-bind="status-dot"'), 'DOM contains status dot');
    assert(html.includes('data-bind="status-label"'), 'DOM contains status label');
    assert(html.includes('data-bind="node-count"'), 'DOM contains node count');
    assert(html.includes('data-bind="msg-count"'), 'DOM contains message count');
})();

// ============================================================
// 3. Nodes tab elements
// ============================================================

console.log('\n--- Nodes tab ---');

(function testNodesTabHasNodeList() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="node-list"'), 'DOM contains node list');
    assert(html.includes('No nodes discovered'), 'DOM has empty node list placeholder');
})();

(function testNodesTabHasNodeDetail() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="node-detail"'), 'DOM contains node detail area');
})();

// ============================================================
// 4. Chat tab elements
// ============================================================

console.log('\n--- Chat tab ---');

(function testChatHasChannelSelector() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="channel-select"'), 'DOM contains channel selector');
    assert(html.includes('ch0 (primary)'), 'Channel selector has primary channel');
    assert(html.includes('value="7"'), 'Channel selector has ch7');
})();

(function testChatHasDmIndicator() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="dm-indicator"'), 'DOM contains DM indicator');
    assert(html.includes('data-bind="dm-target"'), 'DOM contains DM target label');
    assert(html.includes('data-action="clear-dm"'), 'DOM contains clear DM button');
})();

(function testChatHasMessages() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="messages"'), 'DOM contains messages area');
})();

(function testChatHasInput() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="input"'), 'DOM contains chat input');
    assert(html.includes('data-action="send"'), 'DOM contains send button');
    assert(html.includes('data-bind="char-count"'), 'DOM contains char counter');
})();

(function testInputMaxLength() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('maxlength="228"'), 'Input has maxlength="228" attribute');
})();

(function testCharCounterInitial() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('>228<'), 'Char counter shows 228 initially');
})();

// ============================================================
// 5. Radio tab elements
// ============================================================

console.log('\n--- Radio tab ---');

(function testRadioHasStatusDisplay() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="radio-status"'), 'DOM contains radio status');
    assert(html.includes('data-bind="radio-host"'), 'DOM contains radio host display');
})();

(function testRadioHasInputFields() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="radio-host-input"'), 'DOM contains host input');
    assert(html.includes('data-bind="radio-port-input"'), 'DOM contains port input');
    assert(html.includes('value="4403"'), 'Port input defaults to 4403');
})();

(function testRadioHasConnectButtons() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="connect"'), 'DOM contains CONNECT button');
    assert(html.includes('data-action="disconnect"'), 'DOM contains DISCONNECT button');
})();

(function testRadioHasChannelsArea() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="radio-channels"'), 'DOM contains channels area');
})();

// ============================================================
// 6. Scan tab elements
// ============================================================

console.log('\n--- Scan tab ---');

(function testScanHasScanButton() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="scan"'), 'DOM contains SCAN button');
    assert(html.includes('SCAN FOR DEVICES'), 'Scan button has correct label');
})();

(function testScanHasResultsArea() {
    const el = MeshPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="scan-status"'), 'DOM contains scan status');
    assert(html.includes('data-bind="scan-results"'), 'DOM contains scan results area');
})();

// ============================================================
// 7. MESH_MSG_LIMIT constant
// ============================================================

console.log('\n--- Constants ---');

(function testMeshMsgLimit() {
    const limit = vm.runInContext('MESH_MSG_LIMIT', ctx);
    assert(limit === 228, 'MESH_MSG_LIMIT is 228');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
