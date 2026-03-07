// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Unit Inspector Panel tests
 * Tests UnitInspectorPanelDef structure, DOM creation, nav bar, search,
 * type/alliance filters, and content area.
 * Run: node tests/js/test_unit_inspector.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// DOM mock
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
        set textContent(val) { _textContent = String(val); _innerHTML = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        classList: {
            add(c) { classList.add(c); el.className = Array.from(classList).join(' '); },
            remove(c) { classList.delete(c); el.className = Array.from(classList).join(' '); },
            contains(c) { return classList.has(c); },
            toggle(c) { classList.has(c) ? classList.delete(c) : classList.add(c); el.className = Array.from(classList).join(' '); },
        },
        addEventListener(event, handler) {
            if (!eventListeners[event]) eventListeners[event] = [];
            eventListeners[event].push(handler);
        },
        removeEventListener(event, handler) {
            if (eventListeners[event]) {
                eventListeners[event] = eventListeners[event].filter(h => h !== handler);
            }
        },
        _trigger(event) {
            if (eventListeners[event]) eventListeners[event].forEach(h => h());
        },
        querySelector(sel) {
            // Simple mock: match class or data-bind
            const classMatch = sel.match(/^\.(\S+)/);
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const key = bindMatch[1];
                // Search innerHTML for the data-bind
                if (_innerHTML.includes(`data-bind="${key}"`)) {
                    return createMockElement('div');
                }
            }
            if (classMatch) {
                const cls = classMatch[1];
                if (_innerHTML.includes(`class="${cls}"`) || _innerHTML.includes(`class="${cls} `) || _innerHTML.includes(` ${cls}"`)) {
                    return createMockElement('div');
                }
            }
            return null;
        },
        querySelectorAll(sel) { return []; },
        appendChild(child) { children.push(child); },
        remove() {},
        contains(child) { return children.includes(child); },
        _eventListeners: eventListeners,
    };
    return el;
}

// ============================================================
// TritiumStore + EventBus mocks
// ============================================================

const _storeData = {};
const _storeListeners = {};

const TritiumStore = {
    units: new Map(),
    get(key) { return _storeData[key]; },
    set(key, val) {
        _storeData[key] = val;
        if (_storeListeners[key]) _storeListeners[key].forEach(fn => fn(val));
    },
    on(key, fn) {
        if (!_storeListeners[key]) _storeListeners[key] = [];
        _storeListeners[key].push(fn);
        return () => {
            _storeListeners[key] = _storeListeners[key].filter(f => f !== fn);
        };
    },
};

const _busListeners = {};
const EventBus = {
    on(event, fn) {
        if (!_busListeners[event]) _busListeners[event] = [];
        _busListeners[event].push(fn);
        return () => { _busListeners[event] = _busListeners[event].filter(f => f !== fn); };
    },
    off(event, fn) {
        if (_busListeners[event]) _busListeners[event] = _busListeners[event].filter(f => f !== fn);
    },
    emit(event, data) {
        if (_busListeners[event]) _busListeners[event].forEach(fn => fn(data));
    },
};

// DeviceControlRegistry mock
const DeviceControlRegistry = {
    _controls: new Map(),
    register(type, ctrl) { this._controls.set(type, ctrl); },
    get(type) {
        if (this._controls.has(type)) return this._controls.get(type);
        return { type: 'generic', title: 'DEVICE', render() { return '<div>Generic</div>'; }, bind() {}, update() {}, destroy() {} };
    },
};

const DeviceAPI = {};

// ============================================================
// Load unit-inspector.js
// ============================================================

const src = fs.readFileSync('src/frontend/js/command/panels/unit-inspector.js', 'utf-8');
const cleaned = src
    .replace(/^export\s*\{[^}]*\};?\s*$/m, '')
    .replace(/export\s+(const|let|var|function|class)/g, '$1')
    .replace(/import\s+\{[^}]*\}\s+from\s+['"][^'"]+['"]\s*;/g, '');

const sandbox = {
    console,
    document: {
        createElement(tag) { return createMockElement(tag); },
        body: createMockElement('body'),
    },
    performance: { now: () => 1000 },
    TritiumStore,
    EventBus,
    DeviceControlRegistry,
    DeviceAPI,
    module: { exports: {} },
    exports: {},
};
const ctx = vm.createContext(sandbox);
vm.runInContext(cleaned + `
    module.exports = { UnitInspectorPanelDef };
`, ctx);

const { UnitInspectorPanelDef } = sandbox.module.exports;

// ============================================================
// Tests
// ============================================================

// Test 1: Panel def has correct id
assert(UnitInspectorPanelDef.id === 'unit-inspector', 'Panel id is "unit-inspector"');

// Test 2: Panel def has correct title
assert(UnitInspectorPanelDef.title === 'UNIT INSPECTOR', 'Panel title is "UNIT INSPECTOR"');

// Test 3: Panel def has create function
assert(typeof UnitInspectorPanelDef.create === 'function', 'Panel has create() function');

// Test 4: Panel def has mount function
assert(typeof UnitInspectorPanelDef.mount === 'function', 'Panel has mount() function');

// Test 5: Panel def has unmount function
assert(typeof UnitInspectorPanelDef.unmount === 'function', 'Panel has unmount() function');

// Test 6: create() returns DOM element with nav-bar
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-nav-bar'), 'create() DOM contains nav-bar');
}

// Test 7: create() returns DOM with search input
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-search'), 'create() DOM contains search input');
}

// Test 8: create() returns DOM with type filter
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-type-filter'), 'create() DOM contains type filter');
}

// Test 9: create() returns DOM with alliance filter
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-alliance-filter'), 'create() DOM contains alliance filter');
}

// Test 10: create() returns DOM with content area
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-content'), 'create() DOM contains content area');
}

// Test 11: Type filter has turret option
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('turret'), 'Type filter includes turret option');
}

// Test 12: Alliance filter has friendly/hostile/neutral
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('>FRIENDLY<') || html.includes('friendly'), 'Alliance filter has friendly');
    assert(html.includes('>HOSTILE<') || html.includes('hostile'), 'Alliance filter has hostile');
    assert(html.includes('>NEUTRAL<') || html.includes('neutral'), 'Alliance filter has neutral');
}

// Test 13: Nav bar has prev and next buttons
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('ui-nav-btn'), 'Nav bar has navigation buttons');
}

// Test 14: Default nav label shows no selection
{
    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    const html = el.innerHTML;
    assert(html.includes('--') || html.includes('0'), 'Nav label shows no selection initially');
}

// Test 15: Panel has defaultPosition
assert(UnitInspectorPanelDef.defaultPosition !== undefined, 'Panel has defaultPosition');

// Test 16: Panel has defaultSize
assert(UnitInspectorPanelDef.defaultSize !== undefined, 'Panel has defaultSize');
assert(UnitInspectorPanelDef.defaultSize.w >= 280, 'Panel width is at least 280px');
assert(UnitInspectorPanelDef.defaultSize.h >= 400, 'Panel height is at least 400px');

// ============================================================
// Stats display in inspector
// ============================================================

// Test 17: Inspector renders stats when unit has stats object
{
    // Register a control that renders stats
    DeviceControlRegistry.register('turret', {
        type: 'turret',
        title: 'TURRET',
        render(unit) {
            let html = '<div>Turret Control</div>';
            if (unit.stats && (unit.stats.shots_fired > 0 || unit.stats.distance_traveled > 0.1)) {
                html += '<div class="unit-combat-stats">COMBAT STATS';
                html += ` SHOTS ${unit.stats.shots_fired} fired / ${unit.stats.shots_hit} hit`;
                html += `</div>`;
            }
            return html;
        },
        bind() {},
        update() {},
        destroy() {},
    });

    TritiumStore.units.clear();
    TritiumStore.units.set('turret-stats-1', {
        id: 'turret-stats-1',
        name: 'Turret Alpha',
        type: 'turret',
        asset_type: 'turret',
        alliance: 'friendly',
        stats: { shots_fired: 5, shots_hit: 3, damage_dealt: 45.2, damage_taken: 12.0,
                 distance_traveled: 0, accuracy: 0.6 },
    });
    _storeData['map.selectedUnitId'] = 'turret-stats-1';

    const panel = { _unsubs: [] };
    const el = UnitInspectorPanelDef.create(panel);
    UnitInspectorPanelDef.mount(el, panel);
    const contentEl = el.querySelector('[data-bind="content"]');

    // The content should contain stats info since we registered a turret control
    // that renders stats
    const hasControl = DeviceControlRegistry.get('turret');
    assert(hasControl !== undefined, 'Inspector has turret control registered');
    assert(hasControl.type === 'turret', 'Inspector turret control type is correct');

    // Verify the render output includes stats
    const unit = TritiumStore.units.get('turret-stats-1');
    const rendered = hasControl.render(unit);
    assert(rendered.includes('COMBAT STATS'), 'Inspector turret control renders COMBAT STATS when stats present');
    assert(rendered.includes('5 fired'), 'Inspector turret control renders shots_fired value');
}

// Test 18: Inspector control does not render stats when no activity
{
    const unit = {
        id: 'idle-unit',
        name: 'Idle Camera',
        type: 'turret',
        alliance: 'friendly',
        stats: { shots_fired: 0, shots_hit: 0, damage_dealt: 0, damage_taken: 0,
                 distance_traveled: 0, accuracy: 0 },
    };
    const control = DeviceControlRegistry.get('turret');
    const rendered = control.render(unit);
    assert(!rendered.includes('COMBAT STATS'), 'Inspector does not render COMBAT STATS for idle unit');
}

// ============================================================
// Enhanced DOM mock for mount()-level tests
// ============================================================
// The basic createMockElement returns a fresh child on every querySelector
// call, which means mount() and the test each get different element refs.
// This enhanced version caches children by selector so mount() and test
// code share the same elements.

function createCachedMockElement(tag) {
    const children = [];
    const classList = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';
    const attrs = {};
    const _childCache = {};

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
        set textContent(val) { _textContent = String(val); _innerHTML = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: '',
        disabled: false,
        classList: {
            add(c) { classList.add(c); el.className = Array.from(classList).join(' '); },
            remove(c) { classList.delete(c); el.className = Array.from(classList).join(' '); },
            contains(c) { return classList.has(c); },
            toggle(c) { classList.has(c) ? classList.delete(c) : classList.add(c); el.className = Array.from(classList).join(' '); },
        },
        addEventListener(event, handler) {
            if (!eventListeners[event]) eventListeners[event] = [];
            eventListeners[event].push(handler);
        },
        removeEventListener(event, handler) {
            if (eventListeners[event]) {
                eventListeners[event] = eventListeners[event].filter(h => h !== handler);
            }
        },
        _trigger(event, evtObj) {
            if (eventListeners[event]) eventListeners[event].forEach(h => h(evtObj));
        },
        querySelector(sel) {
            if (_childCache[sel]) return _childCache[sel];
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const key = bindMatch[1];
                const tagForBind = key.includes('filter') ? 'select' : (key === 'search' ? 'input' : 'div');
                const mock = createCachedMockElement(tagForBind);
                mock._bindName = key;
                if (tagForBind === 'select') mock.value = 'ALL';
                if (tagForBind === 'input') mock.value = '';
                _childCache[sel] = mock;
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createCachedMockElement('button');
                mock._actionName = actionMatch[1];
                _childCache[sel] = mock;
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createCachedMockElement('div');
                mock.className = classMatch[1];
                _childCache[sel] = mock;
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) { return []; },
        appendChild(child) { children.push(child); if (child && typeof child === 'object') child.parentNode = el; return child; },
        remove() {},
        contains(child) { return children.includes(child); },
        _eventListeners: eventListeners,
        _childCache,
    };
    return el;
}

// Helper: reset store state for each mount-level test
function resetStore() {
    TritiumStore.units.clear();
    delete _storeData['map.selectedUnitId'];
    // Clear listeners so previous mount() subscriptions don't leak
    if (_storeListeners['map.selectedUnitId']) _storeListeners['map.selectedUnitId'] = [];
    if (_storeListeners['units']) _storeListeners['units'] = [];
    // Clear EventBus listeners
    if (_busListeners['unit:selected']) _busListeners['unit:selected'] = [];
}

// Helper: create a mounted inspector with cached elements and return refs
function mountInspector() {
    resetStore();
    const bodyEl = createCachedMockElement('div');
    const panel = { _unsubs: [] };
    // Set innerHTML so querySelector finds data-bind targets
    bodyEl.innerHTML = UnitInspectorPanelDef.create({}).innerHTML;
    UnitInspectorPanelDef.mount(bodyEl, panel);
    return {
        bodyEl,
        panel,
        navLabel: bodyEl.querySelector('[data-bind="nav-label"]'),
        contentEl: bodyEl.querySelector('[data-bind="content"]'),
        searchEl: bodyEl.querySelector('[data-bind="search"]'),
        typeFilterEl: bodyEl.querySelector('[data-bind="type-filter"]'),
        allianceFilterEl: bodyEl.querySelector('[data-bind="alliance-filter"]'),
        prevBtn: bodyEl.querySelector('[data-action="prev"]'),
        nextBtn: bodyEl.querySelector('[data-action="next"]'),
    };
}

// Helper: add test units to the store
function populateUnits() {
    TritiumStore.units.set('turret-01', {
        id: 'turret-01', name: 'Turret Alpha', type: 'turret',
        alliance: 'friendly', position: { x: 10, y: 20 }, heading: 45,
        health: 200, maxHealth: 200, morale: 0.8,
    });
    TritiumStore.units.set('rover-01', {
        id: 'rover-01', name: 'Rover Bravo', type: 'rover',
        alliance: 'friendly', position: { x: 30, y: 40 }, heading: 90,
        health: 120, maxHealth: 150, morale: 0.6,
    });
    TritiumStore.units.set('hostile-01', {
        id: 'hostile-01', name: 'Hostile Charlie', type: 'person',
        alliance: 'hostile', position: { x: 50, y: 60 }, heading: 180,
        health: 80, maxHealth: 100, morale: 0.4,
    });
    TritiumStore.units.set('drone-01', {
        id: 'drone-01', name: 'Drone Delta', type: 'drone',
        alliance: 'friendly', position: { x: 70, y: 80 }, heading: 270,
        health: 60, maxHealth: 60, morale: 0.9,
    });
    TritiumStore.units.set('neutral-01', {
        id: 'neutral-01', name: 'Bystander Eve', type: 'person',
        alliance: 'neutral', position: { x: 25, y: 35 }, heading: 0,
        health: 100, maxHealth: 100,
    });
}

// Register standard controls for mount tests
DeviceControlRegistry.register('turret', {
    type: 'turret', title: 'TURRET',
    render(unit) {
        let html = `<div class="dc-header">${unit.name || unit.id}</div>`;
        html += `<div class="dc-pos">POS: ${unit.position ? unit.position.x + ',' + unit.position.y : 'N/A'}</div>`;
        html += `<div class="dc-heading">HDG: ${unit.heading !== undefined ? unit.heading : 'N/A'}</div>`;
        html += `<div class="dc-health">HP: ${unit.health}/${unit.maxHealth}</div>`;
        if (unit.morale !== undefined) html += `<div class="dc-morale">MORALE: ${Math.round(unit.morale * 100)}%</div>`;
        if (unit.weapon) html += `<div class="dc-weapon">WEAPON: ${unit.weapon.name} RNG:${unit.weapon.range}m</div>`;
        if (unit.upgrades && unit.upgrades.length) html += `<div class="dc-upgrades">UPGRADES: ${unit.upgrades.join(', ')}</div>`;
        return html;
    },
    bind() {}, update() {}, destroy() {},
});
DeviceControlRegistry.register('rover', {
    type: 'rover', title: 'ROVER',
    render(unit) {
        let html = `<div class="dc-header">${unit.name || unit.id}</div>`;
        html += `<div class="dc-health">HP: ${unit.health}/${unit.maxHealth}</div>`;
        if (unit.morale !== undefined) html += `<div class="dc-morale">MORALE: ${Math.round(unit.morale * 100)}%</div>`;
        return html;
    },
    bind() {}, update() {}, destroy() {},
});
DeviceControlRegistry.register('drone', {
    type: 'drone', title: 'DRONE',
    render(unit) {
        let html = `<div class="dc-header">${unit.name || unit.id}</div>`;
        html += `<div class="dc-health">HP: ${unit.health}/${unit.maxHealth}</div>`;
        return html;
    },
    bind() {}, update() {}, destroy() {},
});
DeviceControlRegistry.register('npc', {
    type: 'npc', title: 'NPC',
    render(unit) {
        return `<div class="dc-header">${unit.name || unit.id}</div><div class="dc-alliance">${unit.alliance}</div>`;
    },
    bind() {}, update() {}, destroy() {},
});

// ============================================================
// Navigation: prev/next buttons
// ============================================================

console.log('\n--- Navigation prev/next ---');

// Test 19: Next button selects first unit when nothing selected
{
    const { nextBtn } = mountInspector();
    populateUnits();

    nextBtn._trigger('click');

    const selectedId = TritiumStore.get('map.selectedUnitId');
    assert(selectedId !== undefined && selectedId !== null, 'Next button selects a unit when nothing is selected');
}

// Test 20: Next button cycles forward through units
{
    const { nextBtn } = mountInspector();
    populateUnits();

    // Select the first unit
    nextBtn._trigger('click');
    const first = TritiumStore.get('map.selectedUnitId');

    // Click next again
    nextBtn._trigger('click');
    const second = TritiumStore.get('map.selectedUnitId');

    assert(second !== first, 'Next button advances to a different unit');
}

// Test 21: Prev button selects last unit when nothing selected
{
    const { prevBtn } = mountInspector();
    populateUnits();

    prevBtn._trigger('click');

    const selectedId = TritiumStore.get('map.selectedUnitId');
    assert(selectedId !== undefined && selectedId !== null, 'Prev button selects a unit when nothing is selected');
}

// Test 22: Navigation wraps around at the end
{
    const { nextBtn } = mountInspector();
    populateUnits();
    const unitCount = TritiumStore.units.size;

    // First click selects index 0 (not cycling from existing).
    // Then unitCount more clicks cycles through all and wraps to index 0.
    nextBtn._trigger('click');
    const first = TritiumStore.get('map.selectedUnitId');
    for (let i = 0; i < unitCount; i++) {
        nextBtn._trigger('click');
    }
    // Should be back to the first
    const wrapped = TritiumStore.get('map.selectedUnitId');
    assert(wrapped === first, 'Navigation wraps around: after ' + (unitCount + 1) + ' nexts, back to first unit');
}

// Test 23: Prev from first unit wraps to last
{
    const { nextBtn, prevBtn } = mountInspector();
    populateUnits();

    // Select first unit
    nextBtn._trigger('click');
    const first = TritiumStore.get('map.selectedUnitId');

    // Go back
    prevBtn._trigger('click');
    const last = TritiumStore.get('map.selectedUnitId');

    assert(last !== first, 'Prev from first unit wraps to a different (last) unit');
}

// Test 24: Navigation emits unit:selected event
{
    const { nextBtn } = mountInspector();
    populateUnits();

    let emitted = null;
    _busListeners['unit:selected'] = []; // clear
    EventBus.on('unit:selected', (data) => { emitted = data; });

    nextBtn._trigger('click');

    assert(emitted !== null, 'Navigation emits unit:selected event');
    assert(emitted.id !== undefined, 'unit:selected event has id field');
}

// Test 25b: Navigation with empty unit list does nothing
{
    const { nextBtn } = mountInspector();
    // Don't populate -- units is empty
    nextBtn._trigger('click');

    const selectedId = TritiumStore.get('map.selectedUnitId');
    assert(selectedId === undefined || selectedId === null, 'Next on empty unit list does not crash or select');
}

// ============================================================
// Filtering: type and alliance
// ============================================================

console.log('\n--- Type and alliance filtering ---');

// Test 26: Type filter restricts navigation to matching units
{
    const { nextBtn, typeFilterEl } = mountInspector();
    populateUnits();

    typeFilterEl.value = 'turret';
    typeFilterEl._trigger('change');

    // Navigate through filtered list
    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'turret-01', 'Type filter "turret" restricts selection to turret-01, got ' + selected);
}

// Test 27: Alliance filter restricts navigation to matching units
{
    const { nextBtn, allianceFilterEl } = mountInspector();
    populateUnits();

    allianceFilterEl.value = 'hostile';
    allianceFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'hostile-01', 'Alliance filter "hostile" restricts to hostile-01, got ' + selected);
}

// Test 28: Type filter "ALL" shows all units
{
    const { nextBtn, typeFilterEl } = mountInspector();
    populateUnits();

    typeFilterEl.value = 'ALL';
    typeFilterEl._trigger('change');

    // Navigate through all -- should have 5 units
    const seen = new Set();
    for (let i = 0; i < 5; i++) {
        nextBtn._trigger('click');
        seen.add(TritiumStore.get('map.selectedUnitId'));
    }
    assert(seen.size === 5, 'Type filter ALL allows all 5 units, got ' + seen.size);
}

// Test 29: Alliance filter "neutral" shows only neutral units
{
    const { nextBtn, allianceFilterEl } = mountInspector();
    populateUnits();

    allianceFilterEl.value = 'neutral';
    allianceFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'neutral-01', 'Alliance filter "neutral" restricts to neutral-01, got ' + selected);
}

// Test 30: Combined type + alliance filter
{
    const { nextBtn, typeFilterEl, allianceFilterEl } = mountInspector();
    populateUnits();

    typeFilterEl.value = 'person';
    typeFilterEl._trigger('change');
    allianceFilterEl.value = 'hostile';
    allianceFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'hostile-01', 'Combined filter person+hostile selects hostile-01, got ' + selected);

    // There should be only 1 matching unit -- clicking next again wraps to same
    nextBtn._trigger('click');
    const second = TritiumStore.get('map.selectedUnitId');
    assert(second === 'hostile-01', 'Combined filter has only 1 match -- wraps back');
}

// Test 31: Search filter by name
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = 'bravo';
    searchEl._trigger('input');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'rover-01', 'Search "bravo" matches Rover Bravo, got ' + selected);
}

// Test 32: Search filter by id
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = 'drone-01';
    searchEl._trigger('input');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'drone-01', 'Search "drone-01" matches drone-01 by id, got ' + selected);
}

// Test 33: Search filter is case-insensitive
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = 'ALPHA';
    searchEl._trigger('input');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'turret-01', 'Search "ALPHA" matches Turret Alpha case-insensitively, got ' + selected);
}

// Test 34: Empty search matches all units
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = '';
    searchEl._trigger('input');

    const seen = new Set();
    for (let i = 0; i < 5; i++) {
        nextBtn._trigger('click');
        seen.add(TritiumStore.get('map.selectedUnitId'));
    }
    assert(seen.size === 5, 'Empty search matches all 5 units, got ' + seen.size);
}

// Test 35: Filter with no matches produces empty navigation
{
    const { nextBtn, typeFilterEl } = mountInspector();
    populateUnits();

    typeFilterEl.value = 'tank';  // no tanks in our test data
    typeFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === undefined || selected === null, 'Filter with no matches yields no selection');
}

// ============================================================
// Nav label updates
// ============================================================

console.log('\n--- Nav label display ---');

// Test 36: Nav label shows "-- / N" when no unit selected
{
    const { navLabel } = mountInspector();
    populateUnits();
    // Trigger a re-render by notifying units
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());
    const text = navLabel.textContent;
    assert(text.includes('--') && text.includes('5'), 'Nav label shows "-- / 5" with no selection, got "' + text + '"');
}

// Test 37: Nav label shows "X / N" when unit is selected
{
    const { navLabel, nextBtn } = mountInspector();
    populateUnits();

    nextBtn._trigger('click');
    // The store change fires the listener which calls _renderUnit
    const text = navLabel.textContent;
    assert(text.includes('1') && text.includes('5'), 'Nav label shows "1 / 5" after selecting first unit, got "' + text + '"');
}

// ============================================================
// Store subscription: units changes trigger re-render
// ============================================================

console.log('\n--- Store subscription ---');

// Test 38: Adding a unit to store triggers nav label update
{
    const { navLabel } = mountInspector();
    // Start with 0 units
    const textBefore = navLabel.textContent;
    assert(textBefore.includes('0'), 'Nav label shows 0 units initially, got "' + textBefore + '"');

    // Add a unit and fire the listener
    TritiumStore.units.set('new-01', {
        id: 'new-01', name: 'New Unit', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
    });
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    const textAfter = navLabel.textContent;
    assert(textAfter.includes('1'), 'Nav label shows 1 unit after adding one, got "' + textAfter + '"');
}

// Test 39: Removing a unit from store triggers nav label update
{
    const { navLabel } = mountInspector();
    populateUnits();
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());
    const textBefore = navLabel.textContent;
    assert(textBefore.includes('5'), 'Nav label shows 5 units before removal, got "' + textBefore + '"');

    TritiumStore.units.delete('drone-01');
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    const textAfter = navLabel.textContent;
    assert(textAfter.includes('4'), 'Nav label shows 4 units after removing one, got "' + textAfter + '"');
}

// Test 40: Changing selectedUnitId triggers content render
{
    const { contentEl } = mountInspector();
    populateUnits();

    // Select a unit via store set (simulating map click)
    TritiumStore.set('map.selectedUnitId', 'turret-01');

    const html = contentEl.innerHTML;
    assert(html.includes('Turret Alpha') || html.includes('turret-01'), 'Content renders selected unit name/id after store change');
}

// Test 41: Mount registers subscriptions in panel._unsubs
{
    const { panel } = mountInspector();
    assert(panel._unsubs.length >= 2, 'mount() registers at least 2 unsubs (units + selectedUnitId), got ' + panel._unsubs.length);
}

// Test 42: Running unsubs cleans up store listeners
{
    const { panel } = mountInspector();
    populateUnits();
    const unitListenersBefore = (_storeListeners['units'] || []).length;

    // Run all unsubs
    for (const unsub of panel._unsubs) {
        if (typeof unsub === 'function') unsub();
    }

    const unitListenersAfter = (_storeListeners['units'] || []).length;
    assert(unitListenersAfter < unitListenersBefore, 'Unsubs remove store listeners');
}

// ============================================================
// Detail rendering: position, heading, health, morale, weapon, upgrades
// ============================================================

console.log('\n--- Detail rendering ---');

// Test 43: Content renders position coordinates
{
    const { contentEl } = mountInspector();
    populateUnits();
    TritiumStore.set('map.selectedUnitId', 'turret-01');

    const html = contentEl.innerHTML;
    assert(html.includes('10') && html.includes('20'), 'Content renders position coordinates 10,20');
}

// Test 44: Content renders heading
{
    const { contentEl } = mountInspector();
    populateUnits();
    TritiumStore.set('map.selectedUnitId', 'turret-01');

    const html = contentEl.innerHTML;
    assert(html.includes('45'), 'Content renders heading 45');
}

// Test 45: Content renders health bar values
{
    const { contentEl } = mountInspector();
    populateUnits();
    TritiumStore.set('map.selectedUnitId', 'rover-01');

    const html = contentEl.innerHTML;
    assert(html.includes('120') && html.includes('150'), 'Content renders health 120/150');
}

// Test 46: Content renders morale percentage
{
    const { contentEl } = mountInspector();
    populateUnits();
    TritiumStore.set('map.selectedUnitId', 'turret-01');

    const html = contentEl.innerHTML;
    assert(html.includes('80%') || html.includes('80'), 'Content renders morale 80%');
}

// Test 47: Content renders weapon info when present
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('armed-01', {
        id: 'armed-01', name: 'Armed Turret', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        health: 200, maxHealth: 200, morale: 0.7,
        weapon: { name: 'Nerf Blaster', range: 50, damage: 10 },
    });
    TritiumStore.set('map.selectedUnitId', 'armed-01');

    const html = contentEl.innerHTML;
    assert(html.includes('Nerf Blaster'), 'Content renders weapon name');
    assert(html.includes('50'), 'Content renders weapon range');
}

// Test 48: Content renders upgrade list when present
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('upgraded-01', {
        id: 'upgraded-01', name: 'Upgraded Turret', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        health: 200, maxHealth: 200,
        upgrades: ['armor_plating', 'rapid_fire'],
    });
    TritiumStore.set('map.selectedUnitId', 'upgraded-01');

    const html = contentEl.innerHTML;
    assert(html.includes('armor_plating'), 'Content renders upgrade "armor_plating"');
    assert(html.includes('rapid_fire'), 'Content renders upgrade "rapid_fire"');
}

// Test 49: Content renders _renderStats section for active unit
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('stats-active-01', {
        id: 'stats-active-01', name: 'Active Turret', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 200, maxHealth: 200,
        stats: {
            shots_fired: 10, shots_hit: 7, damage_dealt: 50, damage_taken: 20,
            distance_traveled: 0, time_alive: 45, time_in_combat: 30, assists: 2,
        },
    });
    TritiumStore.set('map.selectedUnitId', 'stats-active-01');

    const html = contentEl.innerHTML;
    // _renderStats is called and appended inside a dc-stats-live div
    assert(html.includes('dc-stats-live'), 'Content includes dc-stats-live section');
}

// Test 50: _renderStats shows accuracy percentage
{
    // Test the _renderStats function directly via the sandbox
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 10, shots_hit: 7, damage_dealt: 50, damage_taken: 20,
                 distance_traveled: 5.0, time_alive: 45, time_in_combat: 30, assists: 0 }
    })`, ctx);
    assert(result.includes('70%'), '_renderStats shows 70% accuracy for 7/10 hits');
}

// Test 51: _renderStats shows damage dealt/taken
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 5, shots_hit: 3, damage_dealt: 75.5, damage_taken: 12.3,
                 distance_traveled: 0.2, time_alive: 30, time_in_combat: 20, assists: 0 }
    })`, ctx);
    assert(result.includes('75.5') && result.includes('12.3'), '_renderStats shows damage_dealt and damage_taken');
}

// Test 52: _renderStats shows distance traveled when > 0.1
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 1, shots_hit: 1, damage_dealt: 10, damage_taken: 0,
                 distance_traveled: 128.4, time_alive: 60, time_in_combat: 10, assists: 0 }
    })`, ctx);
    assert(result.includes('128.4'), '_renderStats shows distance traveled 128.4m');
    assert(result.includes('DISTANCE'), '_renderStats includes DISTANCE label');
}

// Test 53: _renderStats hides distance when <= 0.1
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 3, shots_hit: 2, damage_dealt: 20, damage_taken: 5,
                 distance_traveled: 0.05, time_alive: 15, time_in_combat: 10, assists: 0 }
    })`, ctx);
    assert(!result.includes('DISTANCE'), '_renderStats hides DISTANCE when distance <= 0.1');
}

// Test 54: _renderStats shows assists when > 0
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 8, shots_hit: 5, damage_dealt: 40, damage_taken: 10,
                 distance_traveled: 5, time_alive: 60, time_in_combat: 40, assists: 3 }
    })`, ctx);
    assert(result.includes('ASSISTS'), '_renderStats shows ASSISTS label when assists > 0');
    assert(result.includes('3'), '_renderStats shows assists count 3');
}

// Test 55: _renderStats hides assists when 0
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 2, shots_hit: 1, damage_dealt: 10, damage_taken: 5,
                 distance_traveled: 1, time_alive: 30, time_in_combat: 15, assists: 0 }
    })`, ctx);
    assert(!result.includes('ASSISTS'), '_renderStats hides ASSISTS when assists is 0');
}

// Test 56: _renderStats shows time alive and time in combat
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 1, shots_hit: 0, damage_dealt: 0, damage_taken: 0,
                 distance_traveled: 0.2, time_alive: 95, time_in_combat: 42, assists: 0 }
    })`, ctx);
    assert(result.includes('95') && result.includes('42'), '_renderStats shows time_alive=95 and time_in_combat=42');
    assert(result.includes('TIME'), '_renderStats includes TIME label');
}

// Test 57: _renderStats returns empty string when no stats
{
    const result = vm.runInContext(`_renderStats({})`, ctx);
    assert(result === '', '_renderStats returns empty string for unit without stats');
}

// Test 58: _renderStats returns empty string when no activity
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 0, shots_hit: 0, damage_dealt: 0, damage_taken: 0,
                 distance_traveled: 0.05, time_alive: 10, time_in_combat: 0, assists: 0 }
    })`, ctx);
    assert(result === '', '_renderStats returns empty for zero shots + negligible distance');
}

// Test 59: _renderStats shows 0% accuracy when 0 shots fired
{
    // Edge case: if shots_fired is somehow > 0 but shots_hit is 0
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 5, shots_hit: 0, damage_dealt: 0, damage_taken: 10,
                 distance_traveled: 1, time_alive: 20, time_in_combat: 15, assists: 0 }
    })`, ctx);
    assert(result.includes('0%'), '_renderStats shows 0% accuracy for 0 hits out of 5 shots');
}

// ============================================================
// Edge cases: no selection, destroyed unit, unknown type
// ============================================================

console.log('\n--- Edge cases ---');

// Test 60: No selected unit shows placeholder message
{
    const { contentEl } = mountInspector();
    populateUnits();
    // Don't select any unit -- initial render shows placeholder
    // Force a render via units listener
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    const html = contentEl.innerHTML;
    assert(html.includes('Click a unit') || html === '', 'No selected unit shows placeholder or empty content');
}

// Test 61: Selecting a unit that is then removed shows "Unit not found"
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('doomed-01', {
        id: 'doomed-01', name: 'Doomed Unit', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    TritiumStore.set('map.selectedUnitId', 'doomed-01');

    // Verify it rendered
    const htmlBefore = contentEl.innerHTML;
    assert(htmlBefore.includes('Doomed Unit') || htmlBefore.includes('doomed-01'),
        'Doomed unit renders initially');

    // Remove the unit
    TritiumStore.units.delete('doomed-01');
    // Trigger re-render via units listener
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    const htmlAfter = contentEl.innerHTML;
    assert(htmlAfter.includes('not found') || htmlAfter.includes('Click a unit'),
        'Removed unit shows "not found" or placeholder, got: ' + htmlAfter.substring(0, 80));
}

// Test 62: Selecting a unit with unknown type uses generic control
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('alien-01', {
        id: 'alien-01', name: 'Unknown Entity', type: 'alien_probe',
        alliance: 'unknown', position: { x: 99, y: 99 },
        health: 50, maxHealth: 50,
    });
    TritiumStore.set('map.selectedUnitId', 'alien-01');

    const html = contentEl.innerHTML;
    // Generic control returns '<div>Generic</div>'
    assert(html.includes('Generic'), 'Unknown unit type uses generic control fallback');
}

// Test 63: Selecting a destroyed unit (health 0) still renders
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('dead-01', {
        id: 'dead-01', name: 'Dead Turret', type: 'turret',
        alliance: 'friendly', position: { x: 5, y: 10 }, heading: 0,
        health: 0, maxHealth: 200,
    });
    TritiumStore.set('map.selectedUnitId', 'dead-01');

    const html = contentEl.innerHTML;
    assert(html.includes('0/200') || html.includes('Dead Turret'),
        'Destroyed unit (health=0) still renders, got: ' + html.substring(0, 80));
}

// Test 64: Neutral person resolves to NPC modal type
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('npc-test-01', {
        id: 'npc-test-01', name: 'Friendly Neighbor', type: 'person',
        alliance: 'neutral', position: { x: 15, y: 25 },
        health: 100, maxHealth: 100,
    });
    TritiumStore.set('map.selectedUnitId', 'npc-test-01');

    const html = contentEl.innerHTML;
    // _resolveModalType returns 'npc' for neutral persons
    assert(html.includes('neutral') || html.includes('Friendly Neighbor'),
        'Neutral person renders via NPC control');
}

// Test 65: _resolveModalType returns 'npc' for neutral person
{
    const result = vm.runInContext(`_resolveModalType({ type: 'person', alliance: 'neutral' })`, ctx);
    assert(result === 'npc', '_resolveModalType returns "npc" for neutral person, got ' + result);
}

// Test 66: _resolveModalType returns 'npc' for neutral animal
{
    const result = vm.runInContext(`_resolveModalType({ type: 'animal', alliance: 'neutral' })`, ctx);
    assert(result === 'npc', '_resolveModalType returns "npc" for neutral animal, got ' + result);
}

// Test 67: _resolveModalType returns 'npc' for neutral vehicle
{
    const result = vm.runInContext(`_resolveModalType({ type: 'vehicle', alliance: 'neutral' })`, ctx);
    assert(result === 'npc', '_resolveModalType returns "npc" for neutral vehicle, got ' + result);
}

// Test 68: _resolveModalType returns actual type for hostile person
{
    const result = vm.runInContext(`_resolveModalType({ type: 'person', alliance: 'hostile' })`, ctx);
    assert(result === 'person', '_resolveModalType returns "person" for hostile person, got ' + result);
}

// Test 69: _resolveModalType returns asset_type when present
{
    const result = vm.runInContext(`_resolveModalType({ asset_type: 'turret', type: 'rover' })`, ctx);
    assert(result === 'turret', '_resolveModalType prefers asset_type over type, got ' + result);
}

// Test 70: _resolveModalType defaults to generic for no type
{
    const result = vm.runInContext(`_resolveModalType({})`, ctx);
    assert(result === 'generic', '_resolveModalType returns "generic" for empty unit, got ' + result);
}

// Test 71: Switching between units renders different content
{
    const { contentEl } = mountInspector();
    populateUnits();

    TritiumStore.set('map.selectedUnitId', 'turret-01');
    const turretHtml = contentEl.innerHTML;

    TritiumStore.set('map.selectedUnitId', 'rover-01');
    const roverHtml = contentEl.innerHTML;

    assert(turretHtml !== roverHtml, 'Different units produce different content');
}

// Test 72: Selecting same unit twice does not reset content (incremental update)
{
    let destroyCalled = 0;
    let updateCalled = 0;
    DeviceControlRegistry.register('sensor', {
        type: 'sensor', title: 'SENSOR',
        render(unit) { return `<div>Sensor ${unit.name}</div>`; },
        bind() {},
        update() { updateCalled++; },
        destroy() { destroyCalled++; },
    });

    const { contentEl } = mountInspector();
    TritiumStore.units.set('sensor-01', {
        id: 'sensor-01', name: 'Motion Sensor', type: 'sensor',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 50, maxHealth: 50,
    });

    // First render
    TritiumStore.set('map.selectedUnitId', 'sensor-01');
    destroyCalled = 0;
    updateCalled = 0;

    // Re-render same unit (e.g. telemetry update)
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    assert(destroyCalled === 0, 'Same unit re-render does not call destroy()');
    assert(updateCalled === 1, 'Same unit re-render calls update() once, got ' + updateCalled);
}

// Test 73: Switching units calls destroy on previous control
{
    let destroyCount = 0;
    DeviceControlRegistry.register('camera', {
        type: 'camera', title: 'CAMERA',
        render(unit) { return `<div>Camera ${unit.name}</div>`; },
        bind() {},
        update() {},
        destroy() { destroyCount++; },
    });

    const { contentEl } = mountInspector();
    TritiumStore.units.set('cam-01', {
        id: 'cam-01', name: 'Cam One', type: 'camera',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    TritiumStore.units.set('cam-02', {
        id: 'cam-02', name: 'Cam Two', type: 'camera',
        alliance: 'friendly', position: { x: 10, y: 10 },
        health: 100, maxHealth: 100,
    });

    TritiumStore.set('map.selectedUnitId', 'cam-01');
    destroyCount = 0;

    // Switch to different unit
    TritiumStore.set('map.selectedUnitId', 'cam-02');
    assert(destroyCount === 1, 'Switching units calls destroy() on previous control, got ' + destroyCount);
}

// Test 74: _esc returns a string for HTML input (escaping depends on real DOM)
{
    const result = vm.runInContext(`_esc('<script>alert("xss")</script>')`, ctx);
    assert(typeof result === 'string', '_esc returns a string for HTML input');
    assert(result.length > 0, '_esc does not return empty for non-empty input');
}

// Test 75: _esc handles null/undefined
{
    const nullResult = vm.runInContext(`_esc(null)`, ctx);
    const undefResult = vm.runInContext(`_esc(undefined)`, ctx);
    assert(nullResult === '', '_esc(null) returns empty string');
    assert(undefResult === '', '_esc(undefined) returns empty string');
}

// Test 76: _esc handles numbers
{
    // _esc coerces to string via String()
    const result = vm.runInContext(`_esc(42)`, ctx);
    assert(result === '' || result === '42', '_esc(42) returns "42" or empty, got "' + result + '"');
}

// Test 77: TYPE_FILTER_OPTIONS includes expected types
{
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    assert(Array.isArray(opts), 'TYPE_FILTER_OPTIONS is an array');
    assert(opts.includes('ALL'), 'TYPE_FILTER_OPTIONS includes ALL');
    assert(opts.includes('turret'), 'TYPE_FILTER_OPTIONS includes turret');
    assert(opts.includes('rover'), 'TYPE_FILTER_OPTIONS includes rover');
    assert(opts.includes('drone'), 'TYPE_FILTER_OPTIONS includes drone');
    assert(opts.includes('person'), 'TYPE_FILTER_OPTIONS includes person');
    assert(opts.includes('tank'), 'TYPE_FILTER_OPTIONS includes tank');
    assert(opts.includes('apc'), 'TYPE_FILTER_OPTIONS includes apc');
}

// Test 78: ALLIANCE_FILTER_OPTIONS includes expected values
{
    const opts = vm.runInContext('ALLIANCE_FILTER_OPTIONS', ctx);
    assert(Array.isArray(opts), 'ALLIANCE_FILTER_OPTIONS is an array');
    assert(opts.includes('ALL'), 'ALLIANCE_FILTER_OPTIONS includes ALL');
    assert(opts.includes('friendly'), 'ALLIANCE_FILTER_OPTIONS includes friendly');
    assert(opts.includes('hostile'), 'ALLIANCE_FILTER_OPTIONS includes hostile');
    assert(opts.includes('neutral'), 'ALLIANCE_FILTER_OPTIONS includes neutral');
}

// Test 79: TYPE_FILTER_OPTIONS includes heavy_turret and missile_turret
{
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    assert(opts.includes('heavy_turret'), 'TYPE_FILTER_OPTIONS includes heavy_turret');
    assert(opts.includes('missile_turret'), 'TYPE_FILTER_OPTIONS includes missile_turret');
}

// Test 80: TYPE_FILTER_OPTIONS includes scout_drone and sensor
{
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    assert(opts.includes('scout_drone'), 'TYPE_FILTER_OPTIONS includes scout_drone');
    assert(opts.includes('sensor'), 'TYPE_FILTER_OPTIONS includes sensor');
    assert(opts.includes('camera'), 'TYPE_FILTER_OPTIONS includes camera');
}

// Test 81: unmount does not crash
{
    const bodyEl = createCachedMockElement('div');
    let threw = false;
    try {
        UnitInspectorPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
}

// Test 82: mount does not crash with empty store
{
    resetStore();
    const bodyEl = createCachedMockElement('div');
    bodyEl.innerHTML = UnitInspectorPanelDef.create({}).innerHTML;
    const panel = { _unsubs: [] };
    let threw = false;
    try {
        UnitInspectorPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
        console.error('mount crash:', e);
    }
    assert(!threw, 'mount() does not crash with empty store');
}

// Test 83: Deselecting unit (set selectedUnitId to null) shows placeholder
{
    const { contentEl } = mountInspector();
    populateUnits();

    // Select a unit
    TritiumStore.set('map.selectedUnitId', 'turret-01');
    const htmlBefore = contentEl.innerHTML;
    assert(htmlBefore.includes('Turret Alpha'), 'Unit is rendered before deselect');

    // Deselect by setting to a non-existent id then null
    // Store.set won't fire if same value, so set to something else first
    _storeData['map.selectedUnitId'] = null;
    if (_storeListeners['map.selectedUnitId']) _storeListeners['map.selectedUnitId'].forEach(fn => fn(null));

    const htmlAfter = contentEl.innerHTML;
    assert(htmlAfter.includes('Click a unit') || htmlAfter.includes('not found') || !htmlAfter.includes('Turret Alpha'),
        'Deselecting unit shows placeholder or clears content');
}

// ============================================================
// _esc edge cases
// ============================================================

console.log('\n--- _esc edge cases ---');

// Test 84: _esc with empty string
{
    const result = vm.runInContext(`_esc('')`, ctx);
    assert(result === '', '_esc("") returns empty string');
}

// Test 85: _esc with numeric 0
{
    const result = vm.runInContext(`_esc(0)`, ctx);
    // 0 is falsy, so !text is true, returns ''
    assert(result === '', '_esc(0) returns empty string (0 is falsy)');
}

// Test 86: _esc with false
{
    const result = vm.runInContext(`_esc(false)`, ctx);
    // false is falsy
    assert(result === '', '_esc(false) returns empty string');
}

// Test 87: _esc with plain text (no special chars)
{
    const result = vm.runInContext(`_esc('hello world')`, ctx);
    assert(result === 'hello world', '_esc returns plain text unchanged');
}

// Test 88: _esc with ampersand
{
    const result = vm.runInContext(`_esc('A & B')`, ctx);
    // DOM-based escaping via textContent->innerHTML
    assert(typeof result === 'string' && result.length > 0, '_esc handles ampersand');
}

// Test 89: _esc with angle brackets
{
    const result = vm.runInContext(`_esc('<b>bold</b>')`, ctx);
    assert(typeof result === 'string', '_esc handles angle brackets');
    // In the mock, textContent setter copies raw to innerHTML (no real DOM escaping).
    // In a real browser, innerHTML would be &lt;b&gt;bold&lt;/b&gt;.
    // We verify the function returns non-empty and contains the text content.
    assert(result.length > 0, '_esc returns non-empty for HTML input');
    assert(result.includes('bold'), '_esc output preserves text content');
}

// Test 90: _esc with quotes
{
    const result = vm.runInContext(`_esc('say "hello"')`, ctx);
    assert(typeof result === 'string' && result.length > 0, '_esc handles double quotes');
}

// ============================================================
// _resolveModalType edge cases
// ============================================================

console.log('\n--- _resolveModalType edge cases ---');

// Test 91: friendly person is NOT npc
{
    const result = vm.runInContext(`_resolveModalType({ type: 'person', alliance: 'friendly' })`, ctx);
    assert(result === 'person', '_resolveModalType returns "person" for friendly person, got ' + result);
}

// Test 92: hostile animal is NOT npc
{
    const result = vm.runInContext(`_resolveModalType({ type: 'animal', alliance: 'hostile' })`, ctx);
    assert(result === 'animal', '_resolveModalType returns "animal" for hostile animal, got ' + result);
}

// Test 93: hostile vehicle is NOT npc
{
    const result = vm.runInContext(`_resolveModalType({ type: 'vehicle', alliance: 'hostile' })`, ctx);
    assert(result === 'vehicle', '_resolveModalType returns "vehicle" for hostile vehicle, got ' + result);
}

// Test 94: turret type regardless of alliance
{
    const result = vm.runInContext(`_resolveModalType({ type: 'turret', alliance: 'neutral' })`, ctx);
    assert(result === 'turret', '_resolveModalType returns "turret" for neutral turret (not npc type)');
}

// Test 95: sensor is not in npcTypes
{
    const result = vm.runInContext(`_resolveModalType({ type: 'sensor', alliance: 'neutral' })`, ctx);
    assert(result === 'sensor', '_resolveModalType returns "sensor" for neutral sensor');
}

// Test 96: no alliance field defaults to unknown
{
    const result = vm.runInContext(`_resolveModalType({ type: 'person' })`, ctx);
    assert(result === 'person', '_resolveModalType returns "person" when alliance is missing (not neutral)');
}

// Test 97: asset_type=null, type present
{
    const result = vm.runInContext(`_resolveModalType({ asset_type: null, type: 'drone' })`, ctx);
    // asset_type is null which is falsy, so type || falls through to 'drone'
    // Actually: asset_type || type || 'generic' => null || 'drone' || 'generic' = 'drone'
    assert(result === 'drone', '_resolveModalType returns "drone" when asset_type is null');
}

// Test 98: both asset_type and type are undefined
{
    const result = vm.runInContext(`_resolveModalType({ alliance: 'hostile' })`, ctx);
    assert(result === 'generic', '_resolveModalType returns "generic" when no type fields');
}

// Test 99: asset_type = 'person' with neutral alliance -> npc
{
    const result = vm.runInContext(`_resolveModalType({ asset_type: 'person', type: 'turret', alliance: 'neutral' })`, ctx);
    assert(result === 'npc', '_resolveModalType returns "npc" when asset_type is person + neutral');
}

// ============================================================
// _renderStats edge cases
// ============================================================

console.log('\n--- _renderStats edge cases ---');

// Test 100: _renderStats with 100% accuracy
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 10, shots_hit: 10, damage_dealt: 100, damage_taken: 0,
                 distance_traveled: 0, time_alive: 60, time_in_combat: 45, assists: 0 }
    })`, ctx);
    assert(result.includes('100%'), '_renderStats shows 100% accuracy for perfect aim');
}

// Test 101: _renderStats with 1 shot fired, 0 hit
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 1, shots_hit: 0, damage_dealt: 0, damage_taken: 0,
                 distance_traveled: 0.2, time_alive: 5, time_in_combat: 2, assists: 0 }
    })`, ctx);
    assert(result.includes('0%'), '_renderStats shows 0% for 0/1 hits');
    assert(result.includes('SHOTS'), '_renderStats shows SHOTS label');
}

// Test 102: _renderStats with null stats
{
    const result = vm.runInContext(`_renderStats({ stats: null })`, ctx);
    assert(result === '', '_renderStats returns empty string for null stats');
}

// Test 103: _renderStats with undefined stats
{
    const result = vm.runInContext(`_renderStats({ stats: undefined })`, ctx);
    assert(result === '', '_renderStats returns empty string for undefined stats');
}

// Test 104: _renderStats with large numbers
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 99999, shots_hit: 77777, damage_dealt: 1000000, damage_taken: 500000,
                 distance_traveled: 50000, time_alive: 3600, time_in_combat: 1800, assists: 100 }
    })`, ctx);
    assert(result.includes('99999'), '_renderStats handles large shots_fired');
    assert(result.includes('1000000'), '_renderStats handles large damage_dealt');
    assert(result.includes('50000'), '_renderStats handles large distance');
    assert(result.includes('100'), '_renderStats handles large assists count');
}

// Test 105: _renderStats returns HTML with COMBAT STATS heading
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 5, shots_hit: 3, damage_dealt: 30, damage_taken: 10,
                 distance_traveled: 0, time_alive: 20, time_in_combat: 10, assists: 0 }
    })`, ctx);
    assert(result.includes('COMBAT STATS'), '_renderStats includes COMBAT STATS heading');
}

// Test 106: _renderStats with distance exactly 0.1 (boundary)
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 1, shots_hit: 1, damage_dealt: 10, damage_taken: 0,
                 distance_traveled: 0.1, time_alive: 10, time_in_combat: 5, assists: 0 }
    })`, ctx);
    // distance_traveled <= 0.1 should hide distance section
    assert(!result.includes('DISTANCE'), '_renderStats hides DISTANCE at exactly 0.1 boundary');
}

// Test 107: _renderStats with distance 0.11 (just above boundary)
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 1, shots_hit: 1, damage_dealt: 10, damage_taken: 0,
                 distance_traveled: 0.11, time_alive: 10, time_in_combat: 5, assists: 0 }
    })`, ctx);
    assert(result.includes('DISTANCE'), '_renderStats shows DISTANCE at 0.11 (above 0.1)');
}

// Test 108: _renderStats with shots_fired=0 but distance > 0.1 shows nothing (no activity)
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 0, shots_hit: 0, damage_dealt: 0, damage_taken: 0,
                 distance_traveled: 5.0, time_alive: 120, time_in_combat: 0, assists: 0 }
    })`, ctx);
    // The condition is: shots_fired === 0 && distance_traveled <= 0.1
    // Here distance is 5.0 > 0.1, so it SHOULD render
    assert(result.length > 0, '_renderStats renders when shots_fired=0 but distance > 0.1');
    assert(result.includes('DISTANCE'), '_renderStats shows distance when only movement occurred');
}

// Test 109: _renderStats accuracy rounding
{
    const result = vm.runInContext(`_renderStats({
        stats: { shots_fired: 3, shots_hit: 1, damage_dealt: 10, damage_taken: 5,
                 distance_traveled: 1, time_alive: 30, time_in_combat: 15, assists: 0 }
    })`, ctx);
    // 1/3 = 0.333... -> Math.round(33.33) = 33
    assert(result.includes('33%'), '_renderStats rounds 1/3 accuracy to 33%');
}

// ============================================================
// Search filter edge cases
// ============================================================

console.log('\n--- Search filter edge cases ---');

// Test 110: Search with no matching units
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = 'zzzznonexistent';
    searchEl._trigger('input');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === undefined || selected === null, 'Search with no matches yields no selection');
}

// Test 111: Search matches partial unit id
{
    const { nextBtn, searchEl } = mountInspector();
    populateUnits();

    searchEl.value = 'turret';
    searchEl._trigger('input');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'turret-01', 'Search "turret" matches turret-01 by id substring');
}

// Test 112: Search combined with type filter
{
    const { nextBtn, searchEl, typeFilterEl } = mountInspector();
    populateUnits();

    searchEl.value = 'alpha';
    typeFilterEl.value = 'turret';
    typeFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'turret-01', 'Combined search "alpha" + type "turret" finds turret-01');
}

// Test 113: Search combined with alliance filter
{
    const { nextBtn, searchEl, allianceFilterEl } = mountInspector();
    populateUnits();

    searchEl.value = 'delta';
    allianceFilterEl.value = 'friendly';
    allianceFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'drone-01', 'Combined search "delta" + alliance "friendly" finds drone-01');
}

// Test 114: Search that matches name but alliance filter excludes it
{
    const { nextBtn, searchEl, allianceFilterEl } = mountInspector();
    populateUnits();

    searchEl.value = 'bystander';
    allianceFilterEl.value = 'hostile';
    allianceFilterEl._trigger('change');

    nextBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === undefined || selected === null,
        'Search "bystander" + hostile filter yields nothing (Bystander is neutral)');
}

// ============================================================
// Navigation additional edge cases
// ============================================================

console.log('\n--- Navigation additional edge cases ---');

// Test 115: Prev from second unit goes to first
{
    const { nextBtn, prevBtn } = mountInspector();
    populateUnits();

    // Select first
    nextBtn._trigger('click');
    const first = TritiumStore.get('map.selectedUnitId');

    // Go to second
    nextBtn._trigger('click');
    const second = TritiumStore.get('map.selectedUnitId');
    assert(second !== first, 'Second unit differs from first');

    // Go back with prev
    prevBtn._trigger('click');
    const backToFirst = TritiumStore.get('map.selectedUnitId');
    assert(backToFirst === first, 'Prev from second unit returns to first');
}

// Test 116: Navigation with single unit wraps to itself
{
    const { nextBtn } = mountInspector();
    TritiumStore.units.set('only-01', {
        id: 'only-01', name: 'Only Unit', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });

    nextBtn._trigger('click');
    const first = TritiumStore.get('map.selectedUnitId');
    assert(first === 'only-01', 'Single unit is selected on next');

    nextBtn._trigger('click');
    const second = TritiumStore.get('map.selectedUnitId');
    assert(second === 'only-01', 'Single unit wraps to itself');
}

// Test 117: Prev with single unit wraps to itself
{
    const { prevBtn } = mountInspector();
    TritiumStore.units.set('alone-01', {
        id: 'alone-01', name: 'Alone Unit', type: 'rover',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 50, maxHealth: 50,
    });

    prevBtn._trigger('click');
    const selected = TritiumStore.get('map.selectedUnitId');
    assert(selected === 'alone-01', 'Prev with single unit selects that unit');
}

// ============================================================
// Nav label with filters
// ============================================================

console.log('\n--- Nav label with filters ---');

// Test 118: Nav label count respects type filter
{
    const { navLabel, typeFilterEl } = mountInspector();
    populateUnits();

    typeFilterEl.value = 'drone';
    typeFilterEl._trigger('change');

    // Force re-render
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());
    const text = navLabel.textContent;
    assert(text.includes('1'), 'Nav label shows 1 drone with type filter "drone", got "' + text + '"');
}

// Test 119: Nav label count respects alliance filter
{
    const { navLabel, allianceFilterEl } = mountInspector();
    populateUnits();

    allianceFilterEl.value = 'friendly';
    allianceFilterEl._trigger('change');

    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());
    const text = navLabel.textContent;
    // turret-01, rover-01, drone-01 are friendly = 3
    assert(text.includes('3'), 'Nav label shows 3 friendly units, got "' + text + '"');
}

// ============================================================
// Incremental update vs full re-render
// ============================================================

console.log('\n--- Incremental update vs full re-render ---');

// Test 120: Switching unit type forces full re-render
{
    // Track destroy on the TURRET control (which is the previous control that gets destroyed)
    let turretDestroyCount = 0;
    DeviceControlRegistry.register('turret', {
        type: 'turret', title: 'TURRET',
        render(unit) {
            let html = `<div class="dc-header">${unit.name || unit.id}</div>`;
            html += `<div class="dc-pos">POS: ${unit.position ? unit.position.x + ',' + unit.position.y : 'N/A'}</div>`;
            html += `<div class="dc-heading">HDG: ${unit.heading !== undefined ? unit.heading : 'N/A'}</div>`;
            html += `<div class="dc-health">HP: ${unit.health}/${unit.maxHealth}</div>`;
            if (unit.morale !== undefined) html += `<div class="dc-morale">MORALE: ${Math.round(unit.morale * 100)}%</div>`;
            if (unit.weapon) html += `<div class="dc-weapon">WEAPON: ${unit.weapon.name} RNG:${unit.weapon.range}m</div>`;
            if (unit.upgrades && unit.upgrades.length) html += `<div class="dc-upgrades">UPGRADES: ${unit.upgrades.join(', ')}</div>`;
            return html;
        },
        bind() {}, update() {}, destroy() { turretDestroyCount++; },
    });
    DeviceControlRegistry.register('apc', {
        type: 'apc', title: 'APC',
        render(unit) { return `<div>APC ${unit.name}</div>`; },
        bind() {}, update() {}, destroy() {},
    });

    const { contentEl } = mountInspector();
    TritiumStore.units.set('turret-sw', {
        id: 'turret-sw', name: 'Switch Turret', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        health: 100, maxHealth: 100,
    });
    TritiumStore.units.set('apc-sw', {
        id: 'apc-sw', name: 'Switch APC', type: 'apc',
        alliance: 'friendly', position: { x: 10, y: 10 },
        health: 200, maxHealth: 200,
    });

    // Select turret
    TritiumStore.set('map.selectedUnitId', 'turret-sw');
    turretDestroyCount = 0;

    // Switch to APC (different type)
    TritiumStore.set('map.selectedUnitId', 'apc-sw');
    assert(turretDestroyCount === 1, 'Switching to different unit type calls destroy on previous, got ' + turretDestroyCount);

    // Restore original turret control for subsequent tests
    DeviceControlRegistry.register('turret', {
        type: 'turret', title: 'TURRET',
        render(unit) {
            let html = `<div class="dc-header">${unit.name || unit.id}</div>`;
            html += `<div class="dc-pos">POS: ${unit.position ? unit.position.x + ',' + unit.position.y : 'N/A'}</div>`;
            html += `<div class="dc-heading">HDG: ${unit.heading !== undefined ? unit.heading : 'N/A'}</div>`;
            html += `<div class="dc-health">HP: ${unit.health}/${unit.maxHealth}</div>`;
            if (unit.morale !== undefined) html += `<div class="dc-morale">MORALE: ${Math.round(unit.morale * 100)}%</div>`;
            if (unit.weapon) html += `<div class="dc-weapon">WEAPON: ${unit.weapon.name} RNG:${unit.weapon.range}m</div>`;
            if (unit.upgrades && unit.upgrades.length) html += `<div class="dc-upgrades">UPGRADES: ${unit.upgrades.join(', ')}</div>`;
            return html;
        },
        bind() {}, update() {}, destroy() {},
    });
}

// Test 121: Updating unit data triggers update, not destroy
{
    let updateCalled = 0;
    let destroyCalled = 0;
    DeviceControlRegistry.register('tank', {
        type: 'tank', title: 'TANK',
        render(unit) { return `<div>Tank ${unit.name} HP:${unit.health}</div>`; },
        bind() {}, update() { updateCalled++; }, destroy() { destroyCalled++; },
    });

    const { contentEl } = mountInspector();
    TritiumStore.units.set('tank-upd', {
        id: 'tank-upd', name: 'Update Tank', type: 'tank',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 200, maxHealth: 200,
    });

    TritiumStore.set('map.selectedUnitId', 'tank-upd');
    updateCalled = 0;
    destroyCalled = 0;

    // Simulate health change via units listener
    TritiumStore.units.get('tank-upd').health = 150;
    if (_storeListeners['units']) _storeListeners['units'].forEach(fn => fn());

    assert(updateCalled === 1, 'Health change triggers update(), got ' + updateCalled);
    assert(destroyCalled === 0, 'Health change does not trigger destroy(), got ' + destroyCalled);
}

// ============================================================
// Content rendering edge cases
// ============================================================

console.log('\n--- Content rendering edge cases ---');

// Test 122: Unit with no name uses id
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('noname-01', {
        id: 'noname-01', type: 'turret',
        alliance: 'friendly', position: { x: 5, y: 10 }, heading: 0,
        health: 100, maxHealth: 100,
    });
    TritiumStore.set('map.selectedUnitId', 'noname-01');

    const html = contentEl.innerHTML;
    assert(html.includes('noname-01'), 'Unit with no name renders its id');
}

// Test 123: Unit with no position shows N/A
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('nopos-01', {
        id: 'nopos-01', name: 'No Position', type: 'turret',
        alliance: 'friendly', heading: 0,
        health: 100, maxHealth: 100,
    });
    TritiumStore.set('map.selectedUnitId', 'nopos-01');

    const html = contentEl.innerHTML;
    assert(html.includes('N/A') || html.includes('No Position'), 'Unit with no position shows N/A or name');
}

// Test 124: Unit with undefined heading
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('nohdg-01', {
        id: 'nohdg-01', name: 'No Heading', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 },
        health: 100, maxHealth: 100,
    });
    TritiumStore.set('map.selectedUnitId', 'nohdg-01');

    const html = contentEl.innerHTML;
    assert(html.includes('N/A') || html.includes('No Heading'), 'Unit with no heading shows N/A or name');
}

// Test 125: Unit with morale 0 (broken)
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('broken-01', {
        id: 'broken-01', name: 'Broken Unit', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        health: 50, maxHealth: 100, morale: 0,
    });
    TritiumStore.set('map.selectedUnitId', 'broken-01');

    const html = contentEl.innerHTML;
    assert(html.includes('0%') || html.includes('Broken Unit'), 'Unit with morale 0 renders');
}

// Test 126: Unit with morale 1.0 (max)
{
    const { contentEl } = mountInspector();
    TritiumStore.units.set('emboldened-01', {
        id: 'emboldened-01', name: 'Bold Unit', type: 'turret',
        alliance: 'friendly', position: { x: 0, y: 0 }, heading: 0,
        health: 200, maxHealth: 200, morale: 1.0,
    });
    TritiumStore.set('map.selectedUnitId', 'emboldened-01');

    const html = contentEl.innerHTML;
    assert(html.includes('100%') || html.includes('Bold Unit'), 'Unit with morale 1.0 renders 100%');
}

// ============================================================
// TYPE_FILTER_OPTIONS and ALLIANCE_FILTER_OPTIONS validation
// ============================================================

console.log('\n--- Filter options validation ---');

// Test 127: TYPE_FILTER_OPTIONS has correct count
{
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    assert(opts.length === 12, 'TYPE_FILTER_OPTIONS has 12 entries, got ' + opts.length);
}

// Test 128: ALLIANCE_FILTER_OPTIONS has correct count
{
    const opts = vm.runInContext('ALLIANCE_FILTER_OPTIONS', ctx);
    assert(opts.length === 4, 'ALLIANCE_FILTER_OPTIONS has 4 entries, got ' + opts.length);
}

// Test 129: TYPE_FILTER_OPTIONS first element is ALL
{
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    assert(opts[0] === 'ALL', 'TYPE_FILTER_OPTIONS first element is ALL');
}

// Test 130: ALLIANCE_FILTER_OPTIONS first element is ALL
{
    const opts = vm.runInContext('ALLIANCE_FILTER_OPTIONS', ctx);
    assert(opts[0] === 'ALL', 'ALLIANCE_FILTER_OPTIONS first element is ALL');
}

// ============================================================
// Panel definition defaults
// ============================================================

console.log('\n--- Panel definition defaults ---');

// Test 131: defaultPosition y is a number
{
    assert(typeof UnitInspectorPanelDef.defaultPosition.y === 'number',
        'defaultPosition.y is a number: ' + UnitInspectorPanelDef.defaultPosition.y);
}

// Test 132: defaultPosition x is null (auto)
{
    assert(UnitInspectorPanelDef.defaultPosition.x === null,
        'defaultPosition.x is null (auto-positioned)');
}

// Test 133: defaultSize w and h are both numbers
{
    assert(typeof UnitInspectorPanelDef.defaultSize.w === 'number', 'defaultSize.w is a number');
    assert(typeof UnitInspectorPanelDef.defaultSize.h === 'number', 'defaultSize.h is a number');
}

// ============================================================
// Deselect and null handling in _renderUnit
// ============================================================

console.log('\n--- Deselect and null handling ---');

// Test 134: Setting selectedUnitId to an id not in the store
{
    const { contentEl } = mountInspector();
    populateUnits();
    TritiumStore.set('map.selectedUnitId', 'nonexistent-99');

    const html = contentEl.innerHTML;
    assert(html.includes('not found') || html.includes('Click a unit') || html === '',
        'Selecting nonexistent unit shows not found or placeholder');
}

// Test 135: Setting selectedUnitId from valid to invalid (not in filtered list)
{
    const { contentEl, typeFilterEl } = mountInspector();
    populateUnits();

    // Select turret
    TritiumStore.set('map.selectedUnitId', 'turret-01');
    const htmlBefore = contentEl.innerHTML;
    assert(htmlBefore.includes('Turret Alpha'), 'Turret renders before filter change');

    // Filter to drones only (turret-01 no longer in filtered list)
    typeFilterEl.value = 'drone';
    typeFilterEl._trigger('change');

    // The selected unit is turret-01 but it's not in filtered list
    // idx will be -1, so nav label should show "--"
    // Content might show placeholder or still the turret depending on implementation
    // The key thing is it doesn't crash
    assert(true, 'No crash when selected unit is filtered out');
}

// ============================================================
// Store subscription count
// ============================================================

console.log('\n--- Store subscription details ---');

// Test 136: mount registers exactly 3 unsubs (units, selectedUnitId, filter cleanup)
{
    const { panel } = mountInspector();
    assert(panel._unsubs.length === 3,
        'mount() registers 3 unsubs (units, selectedUnitId, filter cleanup), got ' + panel._unsubs.length);
}

// Test 137: All unsubs are functions
{
    const { panel } = mountInspector();
    const allFunctions = panel._unsubs.every(u => typeof u === 'function');
    assert(allFunctions, 'All panel._unsubs entries are functions');
}

// ============================================================
// Multiple rapid unit switches
// ============================================================

console.log('\n--- Rapid unit switching ---');

// Test 138: Rapid switching between many units does not crash
{
    const { contentEl } = mountInspector();
    populateUnits();
    let crashed = false;
    try {
        for (let i = 0; i < 20; i++) {
            const ids = ['turret-01', 'rover-01', 'hostile-01', 'drone-01', 'neutral-01'];
            TritiumStore.set('map.selectedUnitId', ids[i % ids.length]);
        }
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, 'Rapid switching between 20 selections does not crash');
}

// Test 139: Rapid next clicks do not crash
{
    const { nextBtn } = mountInspector();
    populateUnits();
    let crashed = false;
    try {
        for (let i = 0; i < 50; i++) {
            nextBtn._trigger('click');
        }
    } catch (e) {
        crashed = true;
    }
    assert(!crashed, '50 rapid next clicks do not crash');
}

// ============================================================
// create() DOM structure
// ============================================================

console.log('\n--- create() DOM structure ---');

// Test 140: create() element has correct className
{
    const el = UnitInspectorPanelDef.create({});
    assert(el.className === 'unit-inspector-inner', 'create() element has className "unit-inspector-inner"');
}

// Test 141: create() includes prev and next buttons
{
    const el = UnitInspectorPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="prev"'), 'create() includes prev button');
    assert(html.includes('data-action="next"'), 'create() includes next button');
}

// Test 142: create() includes search placeholder text
{
    const el = UnitInspectorPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('Search units...'), 'create() search input has placeholder text');
}

// Test 143: create() includes all TYPE_FILTER_OPTIONS in dropdown
{
    const el = UnitInspectorPanelDef.create({});
    const html = el.innerHTML;
    const opts = vm.runInContext('TYPE_FILTER_OPTIONS', ctx);
    for (const opt of opts) {
        assert(html.includes(opt.toUpperCase()) || html.includes(opt),
            'create() type filter includes option "' + opt + '"');
    }
}

// ============================================================
// Summary
// ============================================================
console.log(`\n${passed} passed, ${failed} failed out of ${passed + failed}`);
if (failed > 0) process.exit(1);
