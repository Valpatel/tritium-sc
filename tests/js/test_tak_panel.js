// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC TAK Panel tests
 * Tests TakPanelDef structure, DOM creation, tabs (status, clients, chat,
 * alert, server), data bindings, status bar, and mount wiring.
 * Run: node tests/js/test_tak_panel.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const el = {
        tagName: (tag || 'DIV').toUpperCase(), className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); _innerHTML = String(val).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
        style, dataset, children, childNodes: children, parentNode: null, hidden: false, value: '', disabled: false,
        scrollHeight: 0, scrollTop: 0,
        get classList() {
            return { add(cls) { classList.add(cls); }, remove(cls) { classList.delete(cls); }, contains(cls) { return classList.has(cls); },
                toggle(cls, force) { if (force === undefined) { if (classList.has(cls)) classList.delete(cls); else classList.add(cls); } else if (force) classList.add(cls); else classList.delete(cls); } };
        },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        remove() {}, focus() {},
        addEventListener(evt, fn) { if (!eventListeners[evt]) eventListeners[evt] = []; eventListeners[evt].push(fn); },
        removeEventListener(evt, fn) { if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn); },
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) { const mock = createMockElement('div'); mock._bindName = bindMatch[1]; return mock; }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) { const mock = createMockElement('button'); mock._actionName = actionMatch[1]; return mock; }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) { const mock = createMockElement('button'); mock.className = classMatch[1]; return mock; }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) {
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch && el.className.includes(classMatch[1])) return el;
            return null;
        },
        _eventListeners: eventListeners, _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: { createElement: createMockElement, getElementById: () => null, querySelector: () => null, addEventListener() {}, removeEventListener() {} },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({ clients: [] }) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const takCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/tak.js', 'utf8');
vm.runInContext(takCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const TakPanelDef = ctx.TakPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- TakPanelDef structure ---');

(function() { assert(TakPanelDef.id === 'tak', 'id is "tak"'); })();
(function() { assert(TakPanelDef.title === 'TAK', 'title is "TAK"'); })();
(function() { assert(typeof TakPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof TakPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof TakPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(TakPanelDef.defaultPosition.x === 16, 'defaultPosition.x is 16'); })();
(function() { assert(TakPanelDef.defaultPosition.y === 440, 'defaultPosition.y is 440'); })();
(function() { assert(TakPanelDef.defaultSize.w === 360, 'defaultSize.w is 360'); })();
(function() { assert(TakPanelDef.defaultSize.h === 420, 'defaultSize.h is 420'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(TakPanelDef.create({}).className === 'tak-panel-inner', 'className correct'); })();

// ============================================================
// 3. Tabs
// ============================================================
console.log('\n--- Tabs ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-tab="status"'), 'Has Status tab'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-tab="clients"'), 'Has Clients tab'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-tab="chat"'), 'Has Chat tab'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-tab="alert"'), 'Has Alert tab'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-tab="server"'), 'Has Server tab'); })();

// ============================================================
// 4. Status tab
// ============================================================
console.log('\n--- Status tab ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-enabled"'), 'Has enabled stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-connected"'), 'Has connected stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-cot-url"'), 'Has COT URL stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-callsign"'), 'Has callsign stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-team"'), 'Has team stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-role"'), 'Has role stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-sent"'), 'Has sent stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-received"'), 'Has received stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-queue"'), 'Has queue stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-clients"'), 'Has clients stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="stat-error"'), 'Has error stat'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('BRIDGE STATUS'), 'Has bridge status label'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('TRAFFIC'), 'Has traffic label'); })();

// ============================================================
// 5. Clients tab
// ============================================================
console.log('\n--- Clients tab ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="client-list"'), 'Has client list'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="client-detail"'), 'Has client detail'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('No TAK clients discovered'), 'Has empty client state'); })();

// ============================================================
// 6. Chat tab
// ============================================================
console.log('\n--- Chat tab ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="chat-messages"'), 'Has chat messages area'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="chat-input"'), 'Has chat input'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-action="send-chat"'), 'Has send chat button'); })();

// ============================================================
// 7. Alert tab
// ============================================================
console.log('\n--- Alert tab ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="alert-callsign"'), 'Has alert callsign input'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="alert-lat"'), 'Has alert lat input'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="alert-lng"'), 'Has alert lng input'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="alert-remarks"'), 'Has alert remarks input'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-action="send-alert"'), 'Has send alert button'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="alert-result"'), 'Has alert result area'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('SEND THREAT ALERT'), 'Has threat alert label'); })();

// ============================================================
// 8. Server tab
// ============================================================
console.log('\n--- Server tab ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="srv-protocol"'), 'Has server protocol'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="srv-host"'), 'Has server host'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="srv-port"'), 'Has server port'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="srv-tls"'), 'Has server TLS'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="cot-xml"'), 'Has CoT XML textarea'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-action="send-cot"'), 'Has send CoT button'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('SEND RAW COT'), 'Has raw CoT label'); })();

// ============================================================
// 9. Status bar
// ============================================================
console.log('\n--- Status bar ---');

(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="status-dot"'), 'Has status dot'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="status-label"'), 'Has status label'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="client-count"'), 'Has client count'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('data-bind="msg-total"'), 'Has message total'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('DISCONNECTED'), 'Default status is DISCONNECTED'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('0 clients'), 'Default client count is 0'); })();
(function() { const html = TakPanelDef.create({}).innerHTML; assert(html.includes('0 msgs'), 'Default message count is 0'); })();

// ============================================================
// 10. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: TakPanelDef, _unsubs: [] };
    TakPanelDef.mount(bodyEl, panel);
    // 4 EventBus subscriptions + 1 refresh interval = at least 5
    assert(panel._unsubs.length >= 5, 'mount() registers at least 5 cleanup fns, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: TakPanelDef, _unsubs: [] };
    let threw = false;
    try { TakPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 11. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { TakPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
