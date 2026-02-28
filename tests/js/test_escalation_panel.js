// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Escalation Panel tests
 * Tests EscalationPanelDef structure, DOM creation, threat level display,
 * stats, history, THREAT_LEVELS constant, and mount wiring.
 * Run: node tests/js/test_escalation_panel.js
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
            return null;
        },
        querySelectorAll(sel) { return []; }, closest(sel) { return null; },
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const escCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/escalation.js', 'utf8');
vm.runInContext(escCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const EscalationPanelDef = ctx.EscalationPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- EscalationPanelDef structure ---');

(function() { assert(EscalationPanelDef.id === 'escalation', 'id is "escalation"'); })();
(function() { assert(EscalationPanelDef.title === 'THREAT LEVEL', 'title is "THREAT LEVEL"'); })();
(function() { assert(typeof EscalationPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof EscalationPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof EscalationPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(EscalationPanelDef.defaultSize.w === 260, 'defaultSize.w is 260'); })();
(function() { assert(EscalationPanelDef.defaultSize.h === 300, 'defaultSize.h is 300'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(EscalationPanelDef.create({}).className === 'escalation-panel-inner', 'className is escalation-panel-inner'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="level-num"'), 'Has level number'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="level-label"'), 'Has level label'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="level-desc"'), 'Has level description'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="threat-display"'), 'Has threat display'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('>1<'), 'Default level is 1'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('GREEN'), 'Default label is GREEN'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('All clear'), 'Default desc is All clear'); })();

// ============================================================
// 3. Stats section
// ============================================================
console.log('\n--- Stats ---');

(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="hostile-count"'), 'Has hostile count'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="auto-dispatch"'), 'Has auto-dispatch status'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="last-change"'), 'Has last change time'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('HOSTILES'), 'Has HOSTILES label'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('AUTO-DISPATCH'), 'Has AUTO-DISPATCH label'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('LAST CHANGE'), 'Has LAST CHANGE label'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('ENABLED'), 'Auto-dispatch defaults to ENABLED'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('>---<'), 'Last change defaults to ---'); })();

// ============================================================
// 4. History section
// ============================================================
console.log('\n--- History ---');

(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('data-bind="history"'), 'Has history list'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('RECENT CHANGES'), 'Has RECENT CHANGES section label'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('role="log"'), 'History has role=log'); })();
(function() { const html = EscalationPanelDef.create({}).innerHTML; assert(html.includes('No escalation changes'), 'Has empty state'); })();

// ============================================================
// 5. THREAT_LEVELS constant
// ============================================================
console.log('\n--- THREAT_LEVELS ---');

(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(Array.isArray(levels), 'THREAT_LEVELS is an array'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels.length === 5, 'THREAT_LEVELS has 5 entries'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[0].label === 'GREEN', 'Level 1 is GREEN'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[1].label === 'BLUE', 'Level 2 is BLUE'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[2].label === 'YELLOW', 'Level 3 is YELLOW'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[3].label === 'ORANGE', 'Level 4 is ORANGE'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[4].label === 'RED', 'Level 5 is RED'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[4].color === '#ff2a6d', 'RED color is #ff2a6d'); })();
(function() { const levels = vm.runInContext('THREAT_LEVELS', ctx); assert(levels[0].color === '#05ffa1', 'GREEN color is #05ffa1'); })();

// ============================================================
// 6. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: EscalationPanelDef, _unsubs: [] };
    EscalationPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 3, 'mount() registers at least 3 subscriptions, got ' + panel._unsubs.length);
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: EscalationPanelDef, _unsubs: [] };
    let threw = false;
    try { EscalationPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 7. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() { let threw = false; try { EscalationPanelDef.unmount(createMockElement('div')); } catch (e) { threw = true; } assert(!threw, 'unmount() does not throw'); })();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
