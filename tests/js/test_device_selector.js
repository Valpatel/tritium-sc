// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC DeviceSelector tests
 * Tests DOM structure, dropdown population, selection callbacks,
 * status dots, destroy cleanup, empty list, and API error handling.
 * Run: node tests/js/test_device_selector.js
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

// ============================================================
// Load DeviceSelector source via vm (strip ES module syntax)
// ============================================================

const srcPath = __dirname + '/../../src/frontend/js/addon-ui/device-selector.js';
let source = fs.readFileSync(srcPath, 'utf-8');

// Strip export/import statements so we can eval in CommonJS
source = source.replace(/^export\s*\{[^}]*\};?\s*$/gm, '');
source = source.replace(/^import\s.*$/gm, '');

// Wrap to capture the class and helpers
const wrappedSource = `
    ${source}
    _exports = { DeviceSelector, STATUS_MAP, statusFor, deviceInfoText };
`;

// Mock globals
let _timers = [];
const mockDocument = {
    createElement(tag) { return createMockElement(tag); },
};

const sandbox = {
    document: mockDocument,
    console,
    fetch: null, // set per test
    setInterval(fn, ms) { const id = { fn, ms, cleared: false }; _timers.push(id); return id; },
    clearInterval(id) { if (id) id.cleared = true; },
    setTimeout(fn, ms) { fn(); },
    _exports: null,
};

vm.createContext(sandbox);
vm.runInContext(wrappedSource, sandbox);

const { DeviceSelector, STATUS_MAP, statusFor, deviceInfoText } = sandbox._exports;

// ============================================================
// Helper: create a selector with mock fetch
// ============================================================

function makeSelector(devices, opts = {}) {
    _timers = [];
    const container = createMockElement('div');

    // Mock fetch that returns the device list
    const mockFetch = async (url) => {
        if (opts.fetchError) throw new Error('network error');
        if (opts.fetchStatus) {
            return { ok: false, status: opts.fetchStatus, json: async () => ({}) };
        }
        return {
            ok: true,
            json: async () => devices,
        };
    };

    // Patch fetch into sandbox for the constructor's refresh()
    sandbox.fetch = mockFetch;

    const selector = vm.runInContext(`
        (function(container, onSelect, mockFetch) {
            const sel = new DeviceSelector({
                addonId: 'test',
                container: container,
                onSelect: onSelect,
                pollInterval: ${opts.pollInterval != null ? opts.pollInterval : 0},
            });
            sel._fetch = mockFetch;
            return sel;
        })
    `, sandbox)(container, opts.onSelect || (() => {}), mockFetch);

    return { selector, container };
}

// ============================================================
// Tests -- wrapped in async main so awaits actually work
// ============================================================

async function runTests() {

    // -- Pure helpers ---

    assert(statusFor('connected').cls === 'connected', 'statusFor connected');
    assert(statusFor('error').dot === '\u25CF', 'statusFor error returns filled circle');
    assert(statusFor('disconnected').dot === '\u25CB', 'statusFor disconnected returns open circle');
    assert(statusFor('bogus').cls === 'disconnected', 'statusFor unknown falls back to disconnected');

    assert(deviceInfoText({ model: 'HackRF One', hardware_rev: 'r9', firmware_version: '2024.02.1' })
        === 'HackRF One | r9 | v2024.02.1', 'deviceInfoText full');
    assert(deviceInfoText({ model: 'T-LoRa' }) === 'T-LoRa', 'deviceInfoText model only');
    assert(deviceInfoText({}) === '', 'deviceInfoText empty');

    // -- DOM structure ---

    {
        const { selector, container } = makeSelector([]);
        const root = container.children[0];
        assert(root, 'root element exists');
        assert(root._classList.has('device-selector'), 'root has device-selector class');

        // Should have 3 children: label, select, status
        assert(root.children.length === 3, 'root has 3 children (label, select, status)');

        const label = root.children[0];
        assert(label._classList.has('device-selector-label'), 'label has correct class');
        assert(label.textContent === 'DEVICE', 'label text is DEVICE');

        const dropdown = root.children[1];
        assert(dropdown.tagName === 'SELECT', 'dropdown is a select element');
        assert(dropdown._classList.has('device-selector-dropdown'), 'dropdown has correct class');

        const statusDiv = root.children[2];
        assert(statusDiv._classList.has('device-selector-status'), 'status div has correct class');
        assert(statusDiv.children.length === 2, 'status div has dot + info');
        assert(statusDiv.children[0]._classList.has('device-dot'), 'first child is device-dot');
        assert(statusDiv.children[1]._classList.has('device-info'), 'second child is device-info');

        selector.destroy();
    }

    // -- Dropdown populates from API response ---

    {
        const devices = [
            { device_id: 'hackrf-001', status: 'connected', model: 'HackRF One', hardware_rev: 'r9', firmware_version: '2024.02.1' },
            { device_id: 'hackrf-rpi', status: 'disconnected', model: 'HackRF One' },
        ];
        const { selector, container } = makeSelector(devices);

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        const dropdown = selector._dropdown;
        assert(dropdown.children.length === 2, 'dropdown has 2 options after refresh');

        const opt0 = dropdown.children[0];
        assert(opt0.value === 'hackrf-001', 'first option value is hackrf-001');
        assert(opt0.textContent.includes('hackrf-001'), 'first option text contains device id');
        assert(opt0.textContent.includes('CONNECTED'), 'first option text contains status');

        const opt1 = dropdown.children[1];
        assert(opt1.value === 'hackrf-rpi', 'second option value is hackrf-rpi');

        selector.destroy();
    }

    // -- onSelect callback fires on change ---

    {
        let selectedId = null;
        const devices = [
            { device_id: 'dev-a', status: 'connected' },
            { device_id: 'dev-b', status: 'disconnected' },
        ];
        const { selector } = makeSelector(devices, {
            onSelect: (id) => { selectedId = id; },
        });

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        // Simulate user selecting second device
        selector._dropdown.value = 'dev-b';
        selector._dropdown._fire('change');

        assert(selectedId === 'dev-b', 'onSelect callback received dev-b');
        assert(selector.getSelectedDeviceId() === 'dev-b', 'getSelectedDeviceId returns dev-b');

        selector.destroy();
    }

    // -- Status dots update based on device state ---

    {
        const devices = [
            { device_id: 'dev-1', status: 'connected', model: 'TestModel' },
            { device_id: 'dev-2', status: 'error' },
        ];
        const { selector } = makeSelector(devices);

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        // Auto-selects first device
        assert(selector._dot._classList.has('connected'), 'dot shows connected for first device');
        assert(selector._info.textContent === 'TestModel', 'info shows model text');

        // Switch to error device
        selector._dropdown.value = 'dev-2';
        selector._dropdown._fire('change');

        assert(selector._dot._classList.has('error'), 'dot shows error after switching');
        assert(!selector._dot._classList.has('connected'), 'connected class removed');

        selector.destroy();
    }

    // -- destroy() cleans up intervals ---

    {
        _timers = [];
        const { selector } = makeSelector([], { pollInterval: 5000 });

        // Polling timer should exist
        const timersBefore = _timers.filter(t => !t.cleared);
        assert(timersBefore.length >= 1, 'polling timer was created');

        selector.destroy();

        const timersAfter = _timers.filter(t => !t.cleared);
        assert(timersAfter.length === 0, 'all timers cleared after destroy');
        assert(selector._root === null, 'root nulled after destroy');
        assert(selector._dropdown === null, 'dropdown nulled after destroy');
    }

    // -- Empty device list ---

    {
        const { selector } = makeSelector([]);

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        const dropdown = selector._dropdown;
        assert(dropdown.children.length === 1, 'one placeholder option for empty list');
        assert(dropdown.children[0].textContent.includes('no devices'), 'placeholder says no devices');
        assert(selector.getSelectedDeviceId() === null, 'selectedId is null for empty list');

        selector.destroy();
    }

    // -- API error handling ---

    {
        const { selector } = makeSelector([], { fetchError: true });

        await new Promise(r => global.setTimeout(r, 10));

        // Should not throw; devices list stays empty
        await selector.refresh();
        assert(selector._devices.length === 0, 'devices empty after fetch error');
        assert(selector.getSelectedDeviceId() === null, 'selectedId null after fetch error');

        selector.destroy();
    }

    // -- HTTP error status ---

    {
        const { selector } = makeSelector([], { fetchStatus: 500 });

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();
        assert(selector._devices.length === 0, 'devices empty after HTTP 500');

        selector.destroy();
    }

    // -- Preserves selection on refresh ---

    {
        const devices = [
            { device_id: 'a', status: 'connected' },
            { device_id: 'b', status: 'connected' },
        ];
        const { selector } = makeSelector(devices);

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        // Select second device
        selector._dropdown.value = 'b';
        selector._dropdown._fire('change');
        assert(selector.getSelectedDeviceId() === 'b', 'selected b');

        // Refresh should preserve selection
        await selector.refresh();
        assert(selector.getSelectedDeviceId() === 'b', 'b still selected after refresh');

        selector.destroy();
    }

    // -- API returns { devices: [...] } wrapper ---

    {
        const container = createMockElement('div');
        const mockFetch = async () => ({
            ok: true,
            json: async () => ({ devices: [{ device_id: 'wrapped-1', status: 'connected' }] }),
        });

        sandbox.fetch = mockFetch;
        const selector = vm.runInContext(`
            (function(container, mockFetch) {
                const sel = new DeviceSelector({
                    addonId: 'test',
                    container: container,
                    onSelect: () => {},
                    pollInterval: 0,
                });
                sel._fetch = mockFetch;
                return sel;
            })
        `, sandbox)(container, mockFetch);

        await new Promise(r => global.setTimeout(r, 10));
        await selector.refresh();

        assert(selector._devices.length === 1, 'unwrapped {devices:[...]} format');
        assert(selector._devices[0].device_id === 'wrapped-1', 'correct device from wrapped response');

        selector.destroy();
    }
}

// ============================================================
// Run and summarize
// ============================================================

runTests().then(() => {
    console.log(`\n${'='.repeat(50)}`);
    console.log(`DeviceSelector tests: ${passed} passed, ${failed} failed`);
    console.log('='.repeat(50));
    process.exit(failed > 0 ? 1 : 0);
}).catch(err => {
    console.error('Test runner error:', err);
    process.exit(1);
});
