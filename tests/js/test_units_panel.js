// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Units Panel tests
 * Tests UnitsPanelDef structure, DOM creation, filter select, unit list,
 * detail area, ALLIANCE_COLORS, TYPE_ICONS, and _esc utility.
 * Run: node tests/js/test_units_panel.js
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
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;');
        },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: 'all',
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
        focus() {},
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        // Cache child elements so repeated querySelector calls return the same reference
        _childCache: {},
        querySelector(sel) {
            // Return cached element if we have one for this selector
            if (el._childCache[sel]) return el._childCache[sel];
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement(bindMatch[1] === 'filter' ? 'select' : 'div');
                mock._bindName = bindMatch[1];
                // Give the filter select a default value
                if (bindMatch[1] === 'filter') mock.value = 'all';
                el._childCache[sel] = mock;
                return mock;
            }
            const actionMatch = sel.match(/\[data-action="([^"]+)"\]/);
            if (actionMatch) {
                const mock = createMockElement('button');
                mock._actionName = actionMatch[1];
                el._childCache[sel] = mock;
                return mock;
            }
            const classMatch = sel.match(/\.([a-zA-Z0-9_-]+)/);
            if (classMatch) {
                const mock = createMockElement('div');
                mock.className = classMatch[1];
                el._childCache[sel] = mock;
                return mock;
            }
            return null;
        },
        querySelectorAll(sel) { return []; },
        closest(sel) { return null; },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement: createMockElement,
        getElementById: () => null,
        querySelector: () => null,
        addEventListener() {},
        removeEventListener() {},
    },
    window: {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
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

// Load units.js panel
const unitsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/units.js', 'utf8');
const unitsPlain = unitsCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(unitsPlain, ctx);

const UnitsPanelDef = ctx.UnitsPanelDef;

// ============================================================
// 1. UnitsPanelDef has required properties
// ============================================================

console.log('\n--- UnitsPanelDef structure ---');

(function testHasId() {
    assert(UnitsPanelDef.id === 'units', 'UnitsPanelDef.id is "units"');
})();

(function testHasTitle() {
    assert(UnitsPanelDef.title === 'UNITS', 'UnitsPanelDef.title is "UNITS"');
})();

(function testHasCreate() {
    assert(typeof UnitsPanelDef.create === 'function', 'UnitsPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof UnitsPanelDef.mount === 'function', 'UnitsPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof UnitsPanelDef.unmount === 'function', 'UnitsPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(UnitsPanelDef.defaultPosition !== undefined, 'UnitsPanelDef has defaultPosition');
    assert(UnitsPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8');
    assert(UnitsPanelDef.defaultPosition.y === 44, 'defaultPosition.y is 44');
})();

(function testHasDefaultSize() {
    assert(UnitsPanelDef.defaultSize !== undefined, 'UnitsPanelDef has defaultSize');
    assert(UnitsPanelDef.defaultSize.w === 260, 'defaultSize.w is 260');
    assert(UnitsPanelDef.defaultSize.h === 420, 'defaultSize.h is 420');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = UnitsPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'units-panel-inner', 'create() element has correct className');
})();

(function testCreateHasFilterSelect() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="filter"'), 'DOM contains filter select');
    assert(html.includes('panel-filter'), 'Filter select has panel-filter class');
})();

(function testFilterHasAllOptions() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('value="all"'), 'Filter has ALL option');
    assert(html.includes('value="friendly"'), 'Filter has FRIENDLY option');
    assert(html.includes('value="hostile"'), 'Filter has HOSTILE option');
    assert(html.includes('value="neutral"'), 'Filter has NEUTRAL option');
    assert(html.includes('value="unknown"'), 'Filter has UNKNOWN option');
})();

(function testFilterOptionLabels() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('>ALL<'), 'Filter ALL has correct label');
    assert(html.includes('>FRIENDLY<'), 'Filter FRIENDLY has correct label');
    assert(html.includes('>HOSTILE<'), 'Filter HOSTILE has correct label');
    assert(html.includes('>NEUTRAL<'), 'Filter NEUTRAL has correct label');
    assert(html.includes('>UNKNOWN<'), 'Filter UNKNOWN has correct label');
})();

(function testCreateHasUnitCount() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="count"'), 'DOM contains unit count data-bind');
    assert(html.includes('UNITS'), 'DOM contains "UNITS" label');
})();

(function testCreateHasUnitList() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="list"'), 'DOM contains unit list data-bind');
    assert(html.includes('panel-list'), 'Unit list has panel-list class');
    assert(html.includes('role="listbox"'), 'Unit list has listbox role');
    assert(html.includes('aria-label="Unit list"'), 'Unit list has aria-label');
})();

(function testCreateHasEmptyState() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('No units detected'), 'DOM contains empty state text');
    assert(html.includes('panel-empty'), 'Empty state has panel-empty class');
})();

(function testCreateHasDetailArea() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="detail"'), 'DOM contains detail area data-bind');
    assert(html.includes('display:none'), 'Detail area is hidden by default');
})();

// ============================================================
// 3. ALLIANCE_COLORS constant
// ============================================================

console.log('\n--- ALLIANCE_COLORS ---');

(function testAllianceColorsExists() {
    const colors = vm.runInContext('ALLIANCE_COLORS', ctx);
    assert(typeof colors === 'object' && colors !== null, 'ALLIANCE_COLORS exists');
})();

(function testAllianceColorFriendly() {
    const color = vm.runInContext('ALLIANCE_COLORS.friendly', ctx);
    assert(color === 'var(--green)', 'ALLIANCE_COLORS.friendly is var(--green), got ' + color);
})();

(function testAllianceColorHostile() {
    const color = vm.runInContext('ALLIANCE_COLORS.hostile', ctx);
    assert(color === 'var(--magenta)', 'ALLIANCE_COLORS.hostile is var(--magenta), got ' + color);
})();

(function testAllianceColorNeutral() {
    const color = vm.runInContext('ALLIANCE_COLORS.neutral', ctx);
    assert(color === 'var(--cyan)', 'ALLIANCE_COLORS.neutral is var(--cyan), got ' + color);
})();

(function testAllianceColorUnknown() {
    const color = vm.runInContext('ALLIANCE_COLORS.unknown', ctx);
    assert(color === 'var(--amber)', 'ALLIANCE_COLORS.unknown is var(--amber), got ' + color);
})();

// ============================================================
// 4. TYPE_ICONS constant
// ============================================================

console.log('\n--- TYPE_ICONS ---');

(function testTypeIconsExists() {
    const icons = vm.runInContext('TYPE_ICONS', ctx);
    assert(typeof icons === 'object' && icons !== null, 'TYPE_ICONS exists');
})();

(function testTypeIconRover() {
    const icon = vm.runInContext('TYPE_ICONS.rover', ctx);
    assert(icon === 'R', 'TYPE_ICONS.rover is "R"');
})();

(function testTypeIconDrone() {
    const icon = vm.runInContext('TYPE_ICONS.drone', ctx);
    assert(icon === 'D', 'TYPE_ICONS.drone is "D"');
})();

(function testTypeIconTurret() {
    const icon = vm.runInContext('TYPE_ICONS.turret', ctx);
    assert(icon === 'T', 'TYPE_ICONS.turret is "T"');
})();

(function testTypeIconPerson() {
    const icon = vm.runInContext('TYPE_ICONS.person', ctx);
    assert(icon === 'P', 'TYPE_ICONS.person is "P"');
})();

(function testTypeIconHostileKid() {
    const icon = vm.runInContext('TYPE_ICONS.hostile_kid', ctx);
    assert(icon === 'H', 'TYPE_ICONS.hostile_kid is "H"');
})();

(function testTypeIconCamera() {
    const icon = vm.runInContext('TYPE_ICONS.camera', ctx);
    assert(icon === 'C', 'TYPE_ICONS.camera is "C"');
})();

(function testTypeIconSensor() {
    const icon = vm.runInContext('TYPE_ICONS.sensor', ctx);
    assert(icon === 'S', 'TYPE_ICONS.sensor is "S"');
})();

// 4b. TYPE_ICONS should match all types the map renderer handles
// Map renderer (map-maplibre.js) handles: turret, drone, scout_drone, rover,
// tank, apc, hostile_vehicle, hostile_leader, person, vehicle, sensor, camera
// Units panel must match.

(function testTypeIconTank() {
    const icon = vm.runInContext('TYPE_ICONS.tank', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.tank should be defined, got ' + icon);
    assert(icon === 'K', 'TYPE_ICONS.tank should be "K", got ' + icon);
})();

(function testTypeIconApc() {
    const icon = vm.runInContext('TYPE_ICONS.apc', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.apc should be defined, got ' + icon);
    assert(icon === 'A', 'TYPE_ICONS.apc should be "A", got ' + icon);
})();

(function testTypeIconHostileVehicle() {
    const icon = vm.runInContext('TYPE_ICONS.hostile_vehicle', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.hostile_vehicle should be defined, got ' + icon);
    assert(icon === 'V', 'TYPE_ICONS.hostile_vehicle should be "V", got ' + icon);
})();

(function testTypeIconHostileLeader() {
    const icon = vm.runInContext('TYPE_ICONS.hostile_leader', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.hostile_leader should be defined, got ' + icon);
    assert(icon === 'L', 'TYPE_ICONS.hostile_leader should be "L", got ' + icon);
})();

(function testTypeIconScoutDrone() {
    const icon = vm.runInContext('TYPE_ICONS.scout_drone', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.scout_drone should be defined, got ' + icon);
    assert(icon === 'D', 'TYPE_ICONS.scout_drone should be "D", got ' + icon);
})();

(function testTypeIconVehicle() {
    const icon = vm.runInContext('TYPE_ICONS.vehicle', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.vehicle should be defined, got ' + icon);
    assert(icon === 'V', 'TYPE_ICONS.vehicle should be "V", got ' + icon);
})();

(function testTypeIconHeavyTurret() {
    const icon = vm.runInContext('TYPE_ICONS.heavy_turret', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.heavy_turret should be defined, got ' + icon);
    assert(icon === 'T', 'TYPE_ICONS.heavy_turret should be "T", got ' + icon);
})();

(function testTypeIconMissileTurret() {
    const icon = vm.runInContext('TYPE_ICONS.missile_turret', ctx);
    assert(icon !== undefined, 'TYPE_ICONS.missile_turret should be defined, got ' + icon);
    assert(icon === 'T', 'TYPE_ICONS.missile_turret should be "T", got ' + icon);
})();

// ============================================================
// 5. _esc utility function
// ============================================================

console.log('\n--- _esc utility ---');

(function testEscExists() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function exists');
})();

(function testEscEmpty() {
    const result = vm.runInContext('_esc("")', ctx);
    assert(result === '', '_esc("") returns empty string');
})();

(function testEscNull() {
    const result = vm.runInContext('_esc(null)', ctx);
    assert(result === '', '_esc(null) returns empty string');
})();

(function testEscHtml() {
    const result = vm.runInContext('_esc("<b>bold</b>")', ctx);
    assert(!result.includes('<b>'), '_esc escapes HTML tags');
})();

// ============================================================
// 6. mount() wires subscriptions and renders
// ============================================================

console.log('\n--- mount() ---');

(function testMountSubscribes() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: UnitsPanelDef,
        _unsubs: [],
    };

    UnitsPanelDef.mount(bodyEl, panel);
    // Should subscribe to 'units', 'map.selectedUnitId', filter change, and unit:selected
    assert(panel._unsubs.length >= 3, 'mount() registers at least 3 subscriptions/cleanup, got ' + panel._unsubs.length);
})();

(function testMountDoesNotCrashWithEmptyUnits() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: UnitsPanelDef,
        _unsubs: [],
    };

    let threw = false;
    try {
        UnitsPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'mount() does not crash with empty units map');
})();

// ============================================================
// 7. unmount() exists and does not crash
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        UnitsPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 8. Section label structure
// ============================================================

console.log('\n--- Section label ---');

(function testSectionLabelExists() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('panel-section-label'), 'DOM contains panel-section-label');
})();

(function testCountDefaultsToZero() {
    const el = UnitsPanelDef.create({});
    const html = el.innerHTML;
    // The count element should start at 0
    assert(html.includes('>0<'), 'Count element defaults to 0');
})();

// ============================================================
// 9. Detail panel shows combat stats (morale, degradation, weapon_range, kills)
// ============================================================

console.log('\n--- Detail panel combat stats ---');

// Helper: mount panel, populate store with a unit, select it, return detail HTML
function getDetailHtml(unitData) {
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    // Clear previous units
    TritiumStore.units.clear();

    const bodyEl = UnitsPanelDef.create({});
    const panel = { def: UnitsPanelDef, _unsubs: [] };

    // Add unit to store BEFORE mount so initial render sees it
    TritiumStore.updateUnit(unitData.id, unitData);
    TritiumStore.set('map.selectedUnitId', unitData.id);

    UnitsPanelDef.mount(bodyEl, panel);

    // The detail element is cached in bodyEl's querySelector cache
    const detailEl = bodyEl.querySelector('[data-bind="detail"]');
    return detailEl ? detailEl.innerHTML : '';
}

(function testDetailShowsMorale() {
    const html = getDetailHtml({
        id: 'test-morale-1',
        name: 'Rover-1',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        health: 150, maxHealth: 150,
        morale: 0.75,
    });
    assert(html.includes('MORALE'), 'Detail panel shows MORALE label');
})();

(function testDetailShowsDegradation() {
    const html = getDetailHtml({
        id: 'test-deg-1',
        name: 'Rover-2',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        health: 80, maxHealth: 150,
        degradation: 0.35,
    });
    assert(html.includes('DEGRADATION'), 'Detail panel shows DEGRADATION label');
})();

(function testDetailShowsWeaponRange() {
    const html = getDetailHtml({
        id: 'test-wr-1',
        name: 'Turret-1',
        type: 'turret',
        alliance: 'friendly',
        position: { x: 0, y: 0 },
        health: 200, maxHealth: 200,
        weaponRange: 80.0,
        isCombatant: true,
    });
    assert(html.includes('WEAPON'), 'Detail panel shows WEAPON RANGE label');
})();

(function testDetailShowsKills() {
    const html = getDetailHtml({
        id: 'test-kills-1',
        name: 'Drone-1',
        type: 'drone',
        alliance: 'friendly',
        position: { x: 5, y: 5 },
        health: 60, maxHealth: 60,
        kills: 3,
    });
    assert(html.includes('KILLS'), 'Detail panel shows KILLS label');
})();

(function testDetailMoraleValue() {
    const html = getDetailHtml({
        id: 'test-morale-val',
        name: 'Rover-Val',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        health: 150, maxHealth: 150,
        morale: 0.75,
    });
    // Should display the morale value (0.75 or 75% or similar)
    assert(html.includes('75') || html.includes('0.75'), 'Detail panel shows morale value');
})();

(function testDetailWeaponRangeValue() {
    const html = getDetailHtml({
        id: 'test-wr-val',
        name: 'Turret-Val',
        type: 'turret',
        alliance: 'friendly',
        position: { x: 0, y: 0 },
        health: 200, maxHealth: 200,
        weaponRange: 80.0,
        isCombatant: true,
    });
    assert(html.includes('80'), 'Detail panel shows weapon range value 80');
})();

(function testDetailKillsValue() {
    const html = getDetailHtml({
        id: 'test-kills-val',
        name: 'Drone-Val',
        type: 'drone',
        alliance: 'friendly',
        position: { x: 5, y: 5 },
        health: 60, maxHealth: 60,
        kills: 7,
    });
    assert(html.includes('7'), 'Detail panel shows kills count 7');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
