// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Addon UI Component tests
 * Tests AddonTabs, ConnectionBar, StatusBar, and spinner.
 * Run: node tests/js/test_addon_ui_components.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Mock DOM
// ============================================================

function createMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const style = {};
    let _textContent = '';
    let _value = '';

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); },
        get value() { return _value; },
        set value(val) { _value = String(val); },
        style,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        disabled: false,
        get firstChild() { return children[0] || null; },
        get classList() {
            return {
                add(cls) { classList.add(cls); },
                remove(cls) { classList.delete(cls); },
                contains(cls) { return classList.has(cls); },
                _set: classList,
            };
        },
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        removeChild(child) {
            const i = children.indexOf(child);
            if (i >= 0) children.splice(i, 1);
        },
        querySelector(sel) {
            // Simple class selector support
            const cls = sel.startsWith('.') ? sel.slice(1) : null;
            if (cls) {
                for (const c of children) {
                    if (c && c.classList && c.classList.contains(cls)) return c;
                }
            }
            return null;
        },
        setAttribute(k, v) { el['_attr_' + k] = v; },
        getAttribute(k) { return el['_attr_' + k] || null; },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
        },
        _fire(evt) {
            (eventListeners[evt] || []).forEach(fn => fn());
        },
        _listeners: eventListeners,
        _classList: classList,
    };
    return el;
}

const mockDocument = {
    createElement(tag) { return createMockElement(tag); },
};

// ============================================================
// Load and eval component sources
// ============================================================

function loadComponent(filename, exportNames) {
    const srcPath = __dirname + '/../../src/frontend/js/addon-ui/' + filename;
    let source = fs.readFileSync(srcPath, 'utf-8');
    // Strip ES module syntax
    source = source.replace(/^export\s*\{[^}]*\};?\s*$/gm, '');
    source = source.replace(/^import\s.*$/gm, '');

    const exportLine = exportNames.map(n => `${n}: typeof ${n} !== 'undefined' ? ${n} : undefined`).join(', ');
    const wrapped = `${source}\n_exports = { ${exportLine} };`;

    const sandbox = {
        document: mockDocument,
        console,
        Math,
        String,
        _exports: null,
    };
    vm.createContext(sandbox);
    vm.runInContext(wrapped, sandbox);
    return sandbox._exports;
}

const { AddonTabs } = loadComponent('tabs.js', ['AddonTabs']);
const { ConnectionBar } = loadComponent('conn-bar.js', ['ConnectionBar']);
const { StatusBar } = loadComponent('status-bar.js', ['StatusBar']);
const { showSpinner, hideSpinner } = loadComponent('spinner.js', ['showSpinner', 'hideSpinner']);

// ============================================================
// AddonTabs tests
// ============================================================

console.log('\n--- AddonTabs ---');

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'radio', label: 'RADIO' },
        { id: 'spectrum', label: 'SPECTRUM' },
    ]);
    assert(tabs.getActiveTab() === 'radio', 'Default active tab is first tab');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
    ], { activeTab: 'b' });
    assert(tabs.getActiveTab() === 'b', 'Active tab respects options.activeTab');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'x', label: 'X' },
        { id: 'y', label: 'Y' },
    ]);
    tabs.switchTo('y');
    assert(tabs.getActiveTab() === 'y', 'switchTo changes active tab');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
    ]);
    let cbTabId = null;
    let cbPrev = null;
    tabs.onSwitch((id, prev) => { cbTabId = id; cbPrev = prev; });
    tabs.switchTo('b');
    assert(cbTabId === 'b', 'onSwitch callback receives new tab ID');
    assert(cbPrev === 'a', 'onSwitch callback receives previous tab ID');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'a', label: 'A' },
    ]);
    let callCount = 0;
    tabs.onSwitch(() => callCount++);
    tabs.switchTo('a'); // same tab
    assert(callCount === 0, 'onSwitch not called when switching to same tab');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'a', label: 'A' },
    ]);
    tabs.addTab('b', 'B');
    tabs.switchTo('b');
    assert(tabs.getActiveTab() === 'b', 'addTab adds a new tab that can be switched to');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [
        { id: 'a', label: 'A' },
    ]);
    tabs.switchTo('nonexistent');
    assert(tabs.getActiveTab() === 'a', 'switchTo ignores invalid tab ID');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, []);
    assert(tabs.getActiveTab() === null, 'Empty tabs has null active tab');
}

{
    const container = createMockElement('div');
    const tabs = new AddonTabs(container, [{ id: 'a', label: 'A' }]);
    assert(container.children.length > 0, 'Tabs renders DOM into container');
    tabs.destroy();
    // After destroy, internal state is cleared
    assert(tabs._root === null, 'destroy clears internal root');
}

// ============================================================
// ConnectionBar tests
// ============================================================

console.log('\n--- ConnectionBar ---');

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    assert(container.children.length > 0, 'ConnectionBar renders DOM into container');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.setConnected(true, 'HackRF-001');
    assert(bar._connected === true, 'setConnected sets connected state');
    assert(bar._deviceName === 'HackRF-001', 'setConnected sets device name');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.setConnected(false);
    assert(bar._connected === false, 'setConnected(false) sets disconnected state');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.setSignal(3);
    assert(bar._signal === 3, 'setSignal stores signal level');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.setSignal(-1);
    assert(bar._signal === 0, 'setSignal clamps to 0 minimum');
    bar.setSignal(10);
    assert(bar._signal === 4, 'setSignal clamps to 4 maximum');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.setStatus('SCANNING', 'warn');
    assert(bar._statusText === 'SCANNING', 'setStatus stores text');
    assert(bar._statusType === 'warn', 'setStatus stores type');
}

{
    const container = createMockElement('div');
    const bar = new ConnectionBar(container);
    bar.destroy();
    assert(bar._root === null, 'destroy clears internal root');
}

// ============================================================
// StatusBar tests
// ============================================================

console.log('\n--- StatusBar ---');

{
    const container = createMockElement('div');
    const bar = new StatusBar(container);
    assert(container.children.length > 0, 'StatusBar renders DOM into container');
}

{
    const container = createMockElement('div');
    const bar = new StatusBar(container);
    bar.setText('Scanning...');
    assert(bar._text === 'Scanning...', 'setText stores text');
    assert(bar._textEl.textContent === 'Scanning...', 'setText updates DOM');
}

{
    const container = createMockElement('div');
    const bar = new StatusBar(container);
    bar.setMeasurements(1024);
    assert(bar._measurements === 1024, 'setMeasurements stores count');
}

{
    const container = createMockElement('div');
    const bar = new StatusBar(container);
    bar.setUptime(3661);
    assert(bar._uptime === 3661, 'setUptime stores seconds');
    assert(bar._uptimeEl.textContent === '01:01:01', 'setUptime formats HH:MM:SS');
}

{
    assert(StatusBar.formatUptime(0) === '00:00:00', 'formatUptime(0) = 00:00:00');
    assert(StatusBar.formatUptime(59) === '00:00:59', 'formatUptime(59) = 00:00:59');
    assert(StatusBar.formatUptime(3600) === '01:00:00', 'formatUptime(3600) = 01:00:00');
    assert(StatusBar.formatUptime(86399) === '23:59:59', 'formatUptime(86399) = 23:59:59');
}

{
    const container = createMockElement('div');
    const bar = new StatusBar(container);
    bar.destroy();
    assert(bar._root === null, 'destroy clears internal root');
}

// ============================================================
// Spinner tests
// ============================================================

console.log('\n--- Spinner ---');

{
    const container = createMockElement('div');
    showSpinner(container, 'Loading HackRF...');
    assert(container.children.length === 1, 'showSpinner adds one child');
    assert(container.children[0].classList.contains('addon-spinner'),
        'showSpinner child has addon-spinner class');
}

{
    const container = createMockElement('div');
    showSpinner(container);
    hideSpinner(container);
    assert(container.children.length === 0, 'hideSpinner removes spinner');
}

{
    const container = createMockElement('div');
    showSpinner(container, 'First');
    showSpinner(container, 'Second');
    // Should only have one spinner (the second call removes the first)
    let spinnerCount = 0;
    for (const c of container.children) {
        if (c.classList.contains('addon-spinner')) spinnerCount++;
    }
    assert(spinnerCount === 1, 'showSpinner replaces existing spinner');
}

{
    const container = createMockElement('div');
    // hideSpinner on empty container should not throw
    hideSpinner(container);
    assert(container.children.length === 0, 'hideSpinner on empty container is safe');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n${'='.repeat(50)}`);
console.log(`TOTAL: ${passed + failed} | PASSED: ${passed} | FAILED: ${failed}`);
if (failed > 0) {
    process.exit(1);
} else {
    console.log('All addon UI component tests passed.');
}
