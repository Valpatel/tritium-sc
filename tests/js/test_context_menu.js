// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Context Menu Tests
 * Tests the right-click context menu on the MapLibre tactical map.
 * Verifies menu items, positioning, action dispatch, and close behavior.
 * Run: node tests/js/test_context_menu.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Load the context menu module (pure functions, no MapLibre)
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
        id: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) {
            _textContent = String(val);
            _innerHTML = String(val).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },
        style, dataset, children, childNodes: children, parentNode: null,
        hidden: false, value: '', disabled: false,
        get classList() {
            return {
                add(cls) { classList.add(cls); el.className = [...classList].join(' '); },
                remove(cls) { classList.delete(cls); el.className = [...classList].join(' '); },
                contains(cls) { return classList.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classList.has(cls)) classList.delete(cls);
                        else classList.add(cls);
                    } else if (force) classList.add(cls);
                    else classList.delete(cls);
                    el.className = [...classList].join(' ');
                },
            };
        },
        appendChild(child) { children.push(child); if (child) child.parentNode = el; return child; },
        removeChild(child) {
            const idx = children.indexOf(child);
            if (idx >= 0) children.splice(idx, 1);
            return child;
        },
        remove() {
            if (el.parentNode) {
                const idx = el.parentNode.children.indexOf(el);
                if (idx >= 0) el.parentNode.children.splice(idx, 1);
            }
        },
        contains(child) {
            if (child === el) return true;
            return children.some(c => c === child || (c.contains && c.contains(child)));
        },
        focus() {},
        getBoundingClientRect() {
            return {
                left: parseFloat(el.style.left) || 0,
                top: parseFloat(el.style.top) || 0,
                width: 200,
                height: 150,
                right: (parseFloat(el.style.left) || 0) + 200,
                bottom: (parseFloat(el.style.top) || 0) + 150,
            };
        },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
        },
        _childCache: {},
        querySelector(sel) {
            // Search children recursively
            for (const child of children) {
                if (sel.startsWith('.') && child.className && child.className.includes(sel.slice(1))) return child;
                if (sel.startsWith('#') && child.id === sel.slice(1)) return child;
                if (child.querySelector) {
                    const found = child.querySelector(sel);
                    if (found) return found;
                }
            }
            return null;
        },
        querySelectorAll(sel) {
            const results = [];
            for (const child of children) {
                if (sel.startsWith('.') && child.className && child.className.includes(sel.slice(1))) results.push(child);
                if (child.querySelectorAll) {
                    results.push(...child.querySelectorAll(sel));
                }
            }
            return results;
        },
        closest(sel) {
            let node = el;
            while (node) {
                if (sel.startsWith('.') && node.className && node.className.includes(sel.slice(1))) return node;
                if (sel.startsWith('#') && node.id === sel.slice(1)) return node;
                node = node.parentNode;
            }
            return null;
        },
        _eventListeners: eventListeners,
        _classList: classList,
    };
    return el;
}

let fetchCalls = [];
const keyListeners = {};
const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    document: {
        createElement(tag) { return createMockElement(tag); },
        getElementById() { return null; },
        querySelector() { return null; },
        addEventListener(evt, fn) {
            if (!keyListeners[evt]) keyListeners[evt] = [];
            keyListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (keyListeners[evt]) keyListeners[evt] = keyListeners[evt].filter(f => f !== fn);
        },
    },
    window: { innerWidth: 1920, innerHeight: 1080 },
    fetch(url, opts) {
        fetchCalls.push({ url, opts });
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'ok' }) });
    },
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load EventBus
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8')
    .replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsCode, ctx);

// Load TritiumStore
const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8')
    .replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(storeCode, ctx);

// Load context menu module
const contextMenuCode = fs.readFileSync(__dirname + '/../../frontend/js/command/context-menu.js', 'utf8')
    .replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, '');
vm.runInContext(contextMenuCode, ctx);

const ContextMenu = vm.runInContext('ContextMenu', ctx);
const EventBus = vm.runInContext('EventBus', ctx);
const TritiumStore = vm.runInContext('TritiumStore', ctx);

// ============================================================
// 1. Menu items for selected unit
// ============================================================

console.log('\n--- Menu items with unit selected ---');

(function testMenuItemsWithSelectedUnit() {
    const items = ContextMenu.getMenuItems('rover-01');
    const labels = items.map(i => i.label);
    assert(labels.includes('DISPATCH HERE'), 'Selected unit menu has DISPATCH HERE');
    assert(labels.includes('SUGGEST TO AMY'), 'Selected unit menu has SUGGEST TO AMY');
    assert(labels.includes('SET WAYPOINT'), 'Selected unit menu has SET WAYPOINT');
    assert(labels.includes('CANCEL'), 'Selected unit menu has CANCEL');
})();

(function testDispatchItemHasCorrectAction() {
    const items = ContextMenu.getMenuItems('rover-01');
    const dispatch = items.find(i => i.label === 'DISPATCH HERE');
    assert(dispatch && dispatch.action === 'dispatch', 'DISPATCH HERE has action "dispatch"');
})();

(function testSuggestItemHasCorrectAction() {
    const items = ContextMenu.getMenuItems('rover-01');
    const suggest = items.find(i => i.label === 'SUGGEST TO AMY');
    assert(suggest && suggest.action === 'suggest_dispatch', 'SUGGEST TO AMY has action "suggest_dispatch"');
})();

(function testWaypointItemHasCorrectAction() {
    const items = ContextMenu.getMenuItems('rover-01');
    const wp = items.find(i => i.label === 'SET WAYPOINT');
    assert(wp && wp.action === 'waypoint', 'SET WAYPOINT has action "waypoint"');
})();

// ============================================================
// 2. Menu items with no unit selected
// ============================================================

console.log('\n--- Menu items with no unit selected ---');

(function testMenuItemsNoSelection() {
    const items = ContextMenu.getMenuItems(null);
    const labels = items.map(i => i.label);
    assert(labels.includes('DROP MARKER'), 'No-selection menu has DROP MARKER');
    assert(labels.includes('SUGGEST TO AMY: INVESTIGATE'), 'No-selection menu has SUGGEST TO AMY: INVESTIGATE');
    assert(labels.includes('CANCEL'), 'No-selection menu has CANCEL');
})();

(function testNoDispatchWhenNoUnit() {
    const items = ContextMenu.getMenuItems(null);
    const labels = items.map(i => i.label);
    assert(!labels.includes('DISPATCH HERE'), 'No-selection menu has no DISPATCH HERE');
    assert(!labels.includes('SET WAYPOINT'), 'No-selection menu has no SET WAYPOINT');
})();

(function testMarkerAction() {
    const items = ContextMenu.getMenuItems(null);
    const marker = items.find(i => i.label === 'DROP MARKER');
    assert(marker && marker.action === 'marker', 'DROP MARKER has action "marker"');
})();

(function testInvestigateAction() {
    const items = ContextMenu.getMenuItems(null);
    const inv = items.find(i => i.label === 'SUGGEST TO AMY: INVESTIGATE');
    assert(inv && inv.action === 'suggest_investigate', 'SUGGEST TO AMY: INVESTIGATE has action "suggest_investigate"');
})();

// ============================================================
// 3. Menu positioning
// ============================================================

console.log('\n--- Menu positioning ---');

(function testMenuPositionNormal() {
    // Normal case: menu fits on screen
    const pos = ContextMenu.computePosition(100, 200, 200, 180, 1920, 1080);
    assert(pos.left === 100, 'Normal position left = click X');
    assert(pos.top === 200, 'Normal position top = click Y');
})();

(function testMenuFlipsAtRightEdge() {
    // Click near right edge — menu flips left
    const pos = ContextMenu.computePosition(1800, 200, 200, 180, 1920, 1080);
    assert(pos.left < 1800, 'Near right edge: menu flips left');
    assert(pos.left === 1800 - 200, 'Flipped to 1800 - menuWidth');
})();

(function testMenuFlipsAtBottomEdge() {
    // Click near bottom edge — menu flips up
    const pos = ContextMenu.computePosition(100, 950, 200, 180, 1920, 1080);
    assert(pos.top < 950, 'Near bottom edge: menu flips up');
    assert(pos.top === 950 - 180, 'Flipped to 950 - menuHeight');
})();

(function testMenuFlipsAtBothEdges() {
    // Click in bottom-right corner — menu flips both ways
    const pos = ContextMenu.computePosition(1800, 950, 200, 180, 1920, 1080);
    assert(pos.left === 1800 - 200, 'Corner: flips left');
    assert(pos.top === 950 - 180, 'Corner: flips up');
})();

(function testMenuPositionClamped() {
    // Even if clicked off-screen somehow, position is clamped to >= 0
    const pos = ContextMenu.computePosition(-50, -30, 200, 180, 1920, 1080);
    assert(pos.left >= 0, 'Left position clamped to >= 0');
    assert(pos.top >= 0, 'Top position clamped to >= 0');
})();

// ============================================================
// 4. Action dispatch formats
// ============================================================

console.log('\n--- Action dispatch ---');

(function testDispatchAction() {
    const events = [];
    const unsub = EventBus.on('unit:dispatch', (data) => events.push(data));
    ContextMenu.handleAction('dispatch', { x: 50, y: 100 }, 'rover-01');
    assert(events.length === 1, 'dispatch action emits unit:dispatch');
    assert(events[0].unitId === 'rover-01', 'dispatch event has correct unitId');
    assert(events[0].target.x === 50 && events[0].target.y === 100, 'dispatch event has correct target');
    unsub();
})();

(function testWaypointAction() {
    const events = [];
    const unsub = EventBus.on('map:waypoint', (data) => events.push(data));
    ContextMenu.handleAction('waypoint', { x: 30, y: 40 }, 'drone-01');
    assert(events.length === 1, 'waypoint action emits map:waypoint');
    assert(events[0].unitId === 'drone-01', 'waypoint event has correct unitId');
    assert(events[0].x === 30 && events[0].y === 40, 'waypoint event has correct position');
    unsub();
})();

(function testMarkerAction() {
    const events = [];
    const unsub = EventBus.on('map:marker', (data) => events.push(data));
    ContextMenu.handleAction('marker', { x: 10, y: 20 }, null);
    assert(events.length === 1, 'marker action emits map:marker');
    assert(events[0].x === 10 && events[0].y === 20, 'marker event has correct position');
    unsub();
})();

(function testSuggestDispatchAction() {
    fetchCalls = [];
    ContextMenu.handleAction('suggest_dispatch', { x: 55, y: 75 }, 'turret-01');
    assert(fetchCalls.length === 1, 'suggest_dispatch calls fetch');
    assert(fetchCalls[0].url === '/api/amy/chat', 'suggest_dispatch posts to /api/amy/chat');
    const body = JSON.parse(fetchCalls[0].opts.body);
    assert(body.text.includes('suggest'), 'suggest body text contains "suggest"');
    assert(body.text.includes('turret-01'), 'suggest body text contains unit ID');
    assert(body.text.includes('55'), 'suggest body text contains x coordinate');
    assert(body.text.includes('75'), 'suggest body text contains y coordinate');
})();

(function testSuggestInvestigateAction() {
    fetchCalls = [];
    ContextMenu.handleAction('suggest_investigate', { x: 100, y: 200 }, null);
    assert(fetchCalls.length === 1, 'suggest_investigate calls fetch');
    assert(fetchCalls[0].url === '/api/amy/chat', 'suggest_investigate posts to /api/amy/chat');
    const body = JSON.parse(fetchCalls[0].opts.body);
    assert(body.text.includes('suggest'), 'investigate body text contains "suggest"');
    assert(body.text.includes('investigate'), 'investigate body text contains "investigate"');
    assert(body.text.includes('100'), 'investigate body text contains x coordinate');
    assert(body.text.includes('200'), 'investigate body text contains y coordinate');
})();

(function testCancelAction() {
    // Cancel should not emit any events or make any fetch calls
    fetchCalls = [];
    const events = [];
    const unsubs = [
        EventBus.on('unit:dispatch', (d) => events.push(d)),
        EventBus.on('map:waypoint', (d) => events.push(d)),
        EventBus.on('map:marker', (d) => events.push(d)),
    ];
    ContextMenu.handleAction('cancel', { x: 0, y: 0 }, null);
    assert(events.length === 0, 'cancel emits no events');
    assert(fetchCalls.length === 0, 'cancel makes no fetch calls');
    unsubs.forEach(u => u());
})();

// ============================================================
// 5. DOM element creation
// ============================================================

console.log('\n--- DOM element creation ---');

(function testCreateMenuElement() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    assert(el !== null, 'createMenuElement returns an element');
    assert(el.className.includes('map-context-menu'), 'Menu element has map-context-menu class');
})();

(function testMenuElementHasItems() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    const items = el.querySelectorAll('.map-context-item');
    assert(items.length >= 3, 'Menu has at least 3 items for selected unit');
})();

(function testMenuElementNoUnit() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, null, { x: 50, y: 100 }, 400, 300);
    const items = el.querySelectorAll('.map-context-item');
    assert(items.length >= 2, 'Menu has at least 2 items when no unit selected');
})();

(function testMenuIsAppendedToContainer() {
    const container = createMockElement('div');
    ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    const menus = container.querySelectorAll('.map-context-menu');
    assert(menus.length === 1, 'Menu element is appended to container');
})();

// ============================================================
// 6. Menu close behavior
// ============================================================

console.log('\n--- Menu close behavior ---');

(function testHideMenuRemovesElement() {
    const container = createMockElement('div');
    ContextMenu.createMenuElement(container, null, { x: 50, y: 100 }, 400, 300);
    let menusBefore = container.querySelectorAll('.map-context-menu');
    assert(menusBefore.length === 1, 'Menu exists before hide');
    ContextMenu.hide();
    let menusAfter = container.querySelectorAll('.map-context-menu');
    assert(menusAfter.length === 0, 'Menu removed after hide');
})();

(function testHideWhenNoMenuIsNoop() {
    // Should not throw
    ContextMenu.hide();
    assert(true, 'hide() is safe to call when no menu exists');
})();

(function testEscapeKeyClosesMenu() {
    const container = createMockElement('div');
    ContextMenu.createMenuElement(container, null, { x: 50, y: 100 }, 400, 300);
    // Simulate escape key
    if (keyListeners['keydown']) {
        keyListeners['keydown'].forEach(fn => fn({ key: 'Escape' }));
    }
    const menus = container.querySelectorAll('.map-context-menu');
    assert(menus.length === 0, 'Escape key closes the menu');
})();

// ============================================================
// 7. Suggest command format validation
// ============================================================

console.log('\n--- Suggest command formats ---');

(function testSuggestDispatchFormat() {
    const cmd = ContextMenu.buildSuggestCommand('dispatch', 'rover-01', { x: 123.4, y: 567.8 });
    assert(typeof cmd === 'string', 'buildSuggestCommand returns a string');
    assert(cmd.includes('suggest'), 'Command contains "suggest"');
    assert(cmd.includes('dispatch'), 'Command contains "dispatch"');
    assert(cmd.includes('rover-01'), 'Command contains unit ID');
    assert(cmd.includes('123'), 'Command contains x coordinate');
    assert(cmd.includes('568'), 'Command contains y coordinate');
})();

(function testSuggestInvestigateFormat() {
    const cmd = ContextMenu.buildSuggestCommand('investigate', null, { x: 42, y: 99 });
    assert(typeof cmd === 'string', 'buildSuggestCommand returns a string');
    assert(cmd.includes('suggest'), 'Command contains "suggest"');
    assert(cmd.includes('investigate'), 'Command contains "investigate"');
    assert(cmd.includes('42'), 'Command contains x coordinate');
    assert(cmd.includes('99'), 'Command contains y coordinate');
})();

// ============================================================
// 8. Icon prefixes
// ============================================================

console.log('\n--- Menu item icons ---');

(function testMenuItemsHaveIcons() {
    const items = ContextMenu.getMenuItems('rover-01');
    for (const item of items) {
        assert(typeof item.icon === 'string' && item.icon.length > 0, `Item "${item.label}" has an icon`);
    }
})();

(function testNoSelectionItemsHaveIcons() {
    const items = ContextMenu.getMenuItems(null);
    for (const item of items) {
        assert(typeof item.icon === 'string' && item.icon.length > 0, `Item "${item.label}" has an icon`);
    }
})();

// ============================================================
// 9. Multiple menu management (only one at a time)
// ============================================================

console.log('\n--- Single menu enforcement ---');

(function testOnlyOneMenuAtATime() {
    const container = createMockElement('div');
    ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    ContextMenu.createMenuElement(container, null, { x: 200, y: 200 }, 400, 300);
    const menus = container.querySelectorAll('.map-context-menu');
    assert(menus.length === 1, 'Only one context menu exists at a time');
})();

// ============================================================
// 10. Dispatch action calls backend
// ============================================================

console.log('\n--- Dispatch backend call ---');

(function testDispatchCallsBackend() {
    fetchCalls = [];
    ContextMenu.handleAction('dispatch', { x: 100, y: 200 }, 'rover-01');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    assert(!!call, 'Dispatch action calls /api/amy/command');
    if (call) {
        const body = JSON.parse(call.opts.body);
        assert(body.action === 'dispatch', 'Dispatch body has action "dispatch"');
        assert(Array.isArray(body.params), 'Dispatch body has params array');
        assert(body.params[0] === 'rover-01', 'Dispatch params[0] is unit ID');
        assert(body.params[1] === 100, 'Dispatch params[1] is x');
        assert(body.params[2] === 200, 'Dispatch params[2] is y');
    }
})();

(function testDispatchEmitsEventBus() {
    let emitted = null;
    EventBus.on('unit:dispatch', (data) => { emitted = data; });
    ContextMenu.handleAction('dispatch', { x: 10, y: 20 }, 'drone-01');
    assert(emitted !== null, 'Dispatch emits unit:dispatch event');
    assert(emitted.unitId === 'drone-01', 'unit:dispatch has correct unitId');
    assert(emitted.target.x === 10, 'unit:dispatch has correct target.x');
})();

(function testDispatchNoUnitSkipsBackend() {
    fetchCalls = [];
    ContextMenu.handleAction('dispatch', { x: 100, y: 200 }, null);
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    assert(!call, 'Dispatch with no unit does not call backend');
})();

// ============================================================
// 11. Waypoint action calls backend
// ============================================================

console.log('\n--- Waypoint backend call ---');

(function testWaypointCallsBackend() {
    fetchCalls = [];
    ContextMenu.handleAction('waypoint', { x: 300, y: 400 }, 'rover-01');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    assert(!!call, 'Waypoint action calls /api/amy/command (Lua dispatch)');
    if (call) {
        const body = JSON.parse(call.opts.body);
        assert(body.action === 'dispatch', 'Waypoint body uses dispatch action');
        assert(Array.isArray(body.params), 'Waypoint body has params array');
        assert(body.params[0] === 'rover-01', 'Waypoint params has unit id');
        assert(body.params[1] === 300, 'Waypoint params has correct x');
        assert(body.params[2] === 400, 'Waypoint params has correct y');
    }
})();

(function testWaypointEmitsEventBus() {
    let emitted = null;
    EventBus.on('map:waypoint', (data) => { emitted = data; });
    ContextMenu.handleAction('waypoint', { x: 50, y: 60 }, 'drone-01');
    assert(emitted !== null, 'Waypoint emits map:waypoint event');
    assert(emitted.unitId === 'drone-01', 'map:waypoint has correct unitId');
    assert(emitted.x === 50, 'map:waypoint has correct x');
})();

(function testWaypointNoUnitSkipsBackend() {
    fetchCalls = [];
    ContextMenu.handleAction('waypoint', { x: 300, y: 400 }, null);
    const call = fetchCalls.find(c => c.url && c.url.includes('/api/npc/'));
    assert(!call, 'Waypoint with no unit does not call NPC backend');
})();

// ============================================================
// 12. map:marker and map:waypoint events subscribed in map-maplibre.js
// ============================================================

console.log('\n--- map:marker / map:waypoint subscription ---');

(function testMapLibreSubscribesMarkerEvent() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    assert(source.includes("'map:marker'"), 'map-maplibre.js subscribes to map:marker');
})();

(function testMapLibreSubscribesWaypointEvent() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    assert(source.includes("'map:waypoint'"), 'map-maplibre.js subscribes to map:waypoint');
})();

(function testOnDropMarkerHandlerExists() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    assert(source.includes('_onDropMarker'), 'map-maplibre.js has _onDropMarker handler');
})();

(function testOnDropWaypointHandlerExists() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    assert(source.includes('_onDropWaypoint'), 'map-maplibre.js has _onDropWaypoint handler');
})();

(function testMarkerHandlerChecksCoords() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const block = source.split('_onDropMarker')[1] || '';
    assert(block.includes('data.x') && block.includes('data.y'), 'marker handler checks x,y coords');
})();

(function testWaypointHandlerChecksCoords() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const block = source.split('_onDropWaypoint')[1] || '';
    assert(block.includes('data.x') && block.includes('data.y'), 'waypoint handler checks x,y coords');
})();

(function testMarkerHandlerCreatesMapElement() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    // Find the function definition, not the EventBus.on reference
    const funcStart = source.indexOf('function _onDropMarker');
    const block = funcStart >= 0 ? source.slice(funcStart, funcStart + 500) : '';
    assert(block.includes('operator-marker'), 'marker handler creates element with operator-marker class');
})();

(function testWaypointHandlerCreatesMapElement() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const funcStart = source.indexOf('function _onDropWaypoint');
    const block = funcStart >= 0 ? source.slice(funcStart, funcStart + 500) : '';
    assert(block.includes('operator-waypoint'), 'waypoint handler creates element with operator-waypoint class');
})();

(function testMarkerAutoRemove() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const funcStart = source.indexOf('function _onDropMarker');
    const block = funcStart >= 0 ? source.slice(funcStart, funcStart + 1000) : '';
    assert(block.includes('setTimeout'), 'marker handler has auto-remove timeout');
    assert(block.includes('30000'), 'marker auto-removes after 30 seconds');
})();

(function testWaypointAutoRemove() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const funcStart = source.indexOf('function _onDropWaypoint');
    const block = funcStart >= 0 ? source.slice(funcStart, funcStart + 1000) : '';
    assert(block.includes('setTimeout'), 'waypoint handler has auto-remove timeout');
    assert(block.includes('10000'), 'waypoint auto-removes after 10 seconds');
})();


// ============================================================
// Patrol/aim mode uses Amy command (no control lock needed)
// ============================================================

// Patrol mode should send via /api/amy/command not /api/npc/action
(function testPatrolModeUsesAmyCommand() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    // Find patrol mode click handler
    const patrolIdx = source.indexOf('patrolMode && _state.patrolUnitId');
    assert(patrolIdx >= 0, 'patrol mode click handler exists');
    const patrolBlock = source.slice(patrolIdx, patrolIdx + 800);
    // Should use /api/amy/command, NOT /api/npc/
    assert(patrolBlock.includes('/api/amy/command'), 'patrol mode sends via Amy command endpoint');
    assert(!patrolBlock.includes('/api/npc/'), 'patrol mode does NOT use NPC action endpoint (would need control lock)');
})();

// Aim mode should send via /api/devices/{id}/command (device route for hardware commands)
(function testAimModeUsesDeviceCommand() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const aimIdx = source.indexOf('aimMode && _state.aimUnitId');
    assert(aimIdx >= 0, 'aim mode click handler exists');
    const aimBlock = source.slice(aimIdx, aimIdx + 600);
    assert(aimBlock.includes('/api/devices/'), 'aim mode sends via device command endpoint');
    assert(aimBlock.includes('command:'), 'aim mode sends command field (not action)');
    assert(!aimBlock.includes('/api/npc/'), 'aim mode does NOT use NPC action endpoint (would need control lock)');
})();

// Patrol sends params-style patrol command
(function testPatrolSendsParamsCommand() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const patrolIdx = source.indexOf('patrolMode && _state.patrolUnitId');
    const patrolBlock = source.slice(patrolIdx, patrolIdx + 1000);
    assert(patrolBlock.includes("action: 'patrol'"), 'patrol sends action: patrol');
    assert(patrolBlock.includes('params: [_state.patrolUnitId, wpsJson]'), 'patrol sends unit ID and waypoints in params array');
})();

// Aim sends formatted Lua motor.aim command
(function testAimSendsLuaCommand() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/map-maplibre.js', 'utf8');
    const aimIdx = source.indexOf('aimMode && _state.aimUnitId');
    const aimBlock = source.slice(aimIdx, aimIdx + 600);
    assert(aimBlock.includes('motor.aim('), 'aim sends Lua motor.aim() command');
})();


// ============================================================
// Dispatch format: uses params array (not raw JSON fields)
// ============================================================

(function testDispatchUsesParamsArray() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/context-menu.js', 'utf8');
    const dispatchIdx = source.indexOf("case 'dispatch':");
    assert(dispatchIdx >= 0, 'dispatch case exists in context menu');
    const dispatchBlock = source.slice(dispatchIdx, dispatchIdx + 600);
    assert(
        dispatchBlock.includes("params: [selectedUnitId, gamePos.x, gamePos.y]"),
        'dispatch sends params array [unitId, x, y] (not raw JSON fields)'
    );
    assert(
        !dispatchBlock.includes("target_id:"),
        'dispatch does NOT send target_id as raw field (uses params instead)'
    );
})();

// Suggestions route through /api/amy/chat (not /api/amy/command)
(function testSuggestionsUseAmyChat() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/context-menu.js', 'utf8');
    const sugDispIdx = source.indexOf("case 'suggest_dispatch':");
    assert(sugDispIdx >= 0, 'suggest_dispatch case exists');
    const sugBlock = source.slice(sugDispIdx, sugDispIdx + 400);
    assert(sugBlock.includes('/api/amy/chat'), 'suggest_dispatch sends via /api/amy/chat');
    assert(!sugBlock.includes('/api/amy/command'), 'suggest_dispatch does NOT use /api/amy/command');

    const sugInvIdx = source.indexOf("case 'suggest_investigate':");
    assert(sugInvIdx >= 0, 'suggest_investigate case exists');
    const sugInvBlock = source.slice(sugInvIdx, sugInvIdx + 400);
    assert(sugInvBlock.includes('/api/amy/chat'), 'suggest_investigate sends via /api/amy/chat');
})();

// buildSuggestCommand returns natural language (not Lua syntax)
(function testBuildSuggestCommandNaturalLanguage() {
    const source = fs.readFileSync(__dirname + '/../../frontend/js/command/context-menu.js', 'utf8');
    const buildFnIdx = source.indexOf('function buildSuggestCommand');
    assert(buildFnIdx >= 0, 'buildSuggestCommand function exists');
    const fnBlock = source.slice(buildFnIdx, buildFnIdx + 400);
    assert(fnBlock.includes('Operator suggests'), 'buildSuggestCommand uses natural language');
    assert(!fnBlock.includes('suggest:'), 'buildSuggestCommand does NOT use invalid Lua "suggest:" prefix');
})();

// ============================================================
// 13. getMenuItems edge cases: falsy values
// ============================================================

console.log('\n--- getMenuItems falsy/edge values ---');

(function testMenuItemsUndefined() {
    const items = ContextMenu.getMenuItems(undefined);
    const labels = items.map(i => i.label);
    assert(labels.includes('DROP MARKER'), 'undefined selectedUnitId yields no-selection menu');
    assert(!labels.includes('DISPATCH HERE'), 'undefined selectedUnitId has no DISPATCH HERE');
})();

(function testMenuItemsEmptyString() {
    const items = ContextMenu.getMenuItems('');
    const labels = items.map(i => i.label);
    assert(labels.includes('DROP MARKER'), 'Empty string selectedUnitId yields no-selection menu');
    assert(!labels.includes('DISPATCH HERE'), 'Empty string selectedUnitId has no DISPATCH HERE');
})();

(function testMenuItemsZero() {
    const items = ContextMenu.getMenuItems(0);
    const labels = items.map(i => i.label);
    // 0 is falsy, so should yield no-selection menu
    assert(labels.includes('DROP MARKER'), 'Zero selectedUnitId yields no-selection menu');
    assert(!labels.includes('DISPATCH HERE'), 'Zero selectedUnitId has no DISPATCH HERE');
})();

(function testMenuItemCountWithUnit() {
    const items = ContextMenu.getMenuItems('rover-01');
    assert(items.length === 4, 'Selected unit menu has exactly 4 items, got ' + items.length);
})();

(function testMenuItemCountNoUnit() {
    const items = ContextMenu.getMenuItems(null);
    assert(items.length === 3, 'No-selection menu has exactly 3 items, got ' + items.length);
})();

(function testCancelIsAlwaysLast() {
    const withUnit = ContextMenu.getMenuItems('rover-01');
    const noUnit = ContextMenu.getMenuItems(null);
    assert(withUnit[withUnit.length - 1].action === 'cancel', 'CANCEL is last item in unit menu');
    assert(noUnit[noUnit.length - 1].action === 'cancel', 'CANCEL is last item in no-unit menu');
})();

// ============================================================
// 14. computePosition edge cases
// ============================================================

console.log('\n--- computePosition edge cases ---');

(function testMenuExactlyFitsScreen() {
    // Menu exactly fits: clickX + menuW === screenW (no overflow)
    const pos = ContextMenu.computePosition(1720, 900, 200, 180, 1920, 1080);
    assert(pos.left === 1720, 'Menu that exactly fits is not flipped, left = 1720');
    assert(pos.top === 900, 'Menu that exactly fits is not flipped, top = 900');
})();

(function testMenuOnePixelOverRight() {
    // clickX + menuW > screenW by 1 pixel
    const pos = ContextMenu.computePosition(1721, 100, 200, 180, 1920, 1080);
    assert(pos.left === 1721 - 200, 'Menu 1px over right edge flips, left = 1521');
})();

(function testMenuOnePixelOverBottom() {
    const pos = ContextMenu.computePosition(100, 901, 200, 180, 1920, 1080);
    assert(pos.top === 901 - 180, 'Menu 1px over bottom edge flips, top = 721');
})();

(function testZeroSizeMenu() {
    const pos = ContextMenu.computePosition(500, 500, 0, 0, 1920, 1080);
    assert(pos.left === 500, 'Zero-width menu left = clickX');
    assert(pos.top === 500, 'Zero-height menu top = clickY');
})();

(function testFlipCausesNegativeThenClamp() {
    // Click at x=50 with menu width 200: flip yields 50-200 = -150, clamped to 0
    const pos = ContextMenu.computePosition(50, 50, 200, 180, 100, 100);
    assert(pos.left === 0, 'Flip that causes negative X is clamped to 0');
    assert(pos.top === 0, 'Flip that causes negative Y is clamped to 0');
})();

(function testMenuAtOrigin() {
    const pos = ContextMenu.computePosition(0, 0, 200, 180, 1920, 1080);
    assert(pos.left === 0, 'Click at (0,0) left = 0');
    assert(pos.top === 0, 'Click at (0,0) top = 0');
})();

(function testVeryLargeCoordinates() {
    const pos = ContextMenu.computePosition(10000, 10000, 200, 180, 1920, 1080);
    // Flips: 10000-200=9800, still > 0 so not clamped
    assert(pos.left === 9800, 'Large X flips to 9800');
    assert(pos.top === 9820, 'Large Y flips to 9820');
})();

// ============================================================
// 15. buildSuggestCommand edge cases
// ============================================================

console.log('\n--- buildSuggestCommand edge cases ---');

(function testBuildSuggestCommandRoundsCoords() {
    const cmd = ContextMenu.buildSuggestCommand('dispatch', 'rover-01', { x: 50.7, y: 99.3 });
    assert(cmd.includes('51'), 'buildSuggestCommand rounds x 50.7 to 51');
    assert(cmd.includes('99'), 'buildSuggestCommand rounds y 99.3 to 99');
})();

(function testBuildSuggestCommandNegativeCoords() {
    const cmd = ContextMenu.buildSuggestCommand('dispatch', 'rover-01', { x: -10, y: -20 });
    assert(cmd.includes('-10'), 'buildSuggestCommand handles negative x');
    assert(cmd.includes('-20'), 'buildSuggestCommand handles negative y');
})();

(function testBuildSuggestCommandZeroCoords() {
    const cmd = ContextMenu.buildSuggestCommand('dispatch', 'rover-01', { x: 0, y: 0 });
    assert(cmd.includes('(0, 0)'), 'buildSuggestCommand handles zero coords');
})();

(function testBuildSuggestCommandDispatchNoUnit() {
    // dispatch type but null unitId falls through to investigate format
    const cmd = ContextMenu.buildSuggestCommand('dispatch', null, { x: 10, y: 20 });
    assert(cmd.includes('investigate'), 'dispatch with null unitId falls back to investigate format');
    assert(!cmd.includes('null'), 'dispatch with null unitId does not include "null" literal');
})();

(function testBuildSuggestCommandUnknownType() {
    // Unknown type (neither dispatch nor investigate) still returns investigate format
    const cmd = ContextMenu.buildSuggestCommand('unknown', null, { x: 5, y: 5 });
    assert(cmd.includes('investigate'), 'Unknown type falls back to investigate format');
})();

(function testBuildSuggestCommandXssInUnitId() {
    // Unit ID with HTML/script injection characters
    const cmd = ContextMenu.buildSuggestCommand('dispatch', '<script>alert(1)</script>', { x: 10, y: 20 });
    assert(typeof cmd === 'string', 'buildSuggestCommand with XSS unitId returns a string');
    assert(cmd.includes('<script>'), 'buildSuggestCommand passes raw unitId (it is for backend, not DOM)');
})();

// ============================================================
// 16. handleAction edge cases
// ============================================================

console.log('\n--- handleAction edge cases ---');

(function testUnknownActionIsNoop() {
    fetchCalls = [];
    const events = [];
    const unsubs = [
        EventBus.on('unit:dispatch', (d) => events.push(d)),
        EventBus.on('map:waypoint', (d) => events.push(d)),
        EventBus.on('map:marker', (d) => events.push(d)),
        EventBus.on('toast:show', (d) => events.push(d)),
    ];
    ContextMenu.handleAction('nonexistent_action', { x: 0, y: 0 }, null);
    assert(events.length === 0, 'Unknown action emits no events');
    assert(fetchCalls.length === 0, 'Unknown action makes no fetch calls');
    unsubs.forEach(u => u());
})();

(function testDispatchNoUnitNoEvent() {
    const events = [];
    const unsub = EventBus.on('unit:dispatch', (d) => events.push(d));
    fetchCalls = [];
    ContextMenu.handleAction('dispatch', { x: 50, y: 100 }, null);
    assert(events.length === 0, 'Dispatch with null unitId emits no unit:dispatch event');
    assert(fetchCalls.length === 0, 'Dispatch with null unitId makes no fetch calls');
    unsub();
})();

(function testWaypointEmitsEvenWithoutUnit() {
    // waypoint always emits map:waypoint, but only calls backend if unitId exists
    const events = [];
    const unsub = EventBus.on('map:waypoint', (d) => events.push(d));
    fetchCalls = [];
    ContextMenu.handleAction('waypoint', { x: 10, y: 20 }, null);
    assert(events.length === 1, 'Waypoint emits map:waypoint even without unitId');
    assert(events[0].unitId === null, 'Waypoint event has null unitId when no unit selected');
    assert(fetchCalls.length === 0, 'Waypoint without unitId does not call backend');
    unsub();
})();

(function testCancelWithSelectedUnit() {
    fetchCalls = [];
    const events = [];
    const unsubs = [
        EventBus.on('unit:dispatch', (d) => events.push(d)),
        EventBus.on('map:waypoint', (d) => events.push(d)),
        EventBus.on('map:marker', (d) => events.push(d)),
    ];
    ContextMenu.handleAction('cancel', { x: 50, y: 100 }, 'rover-01');
    assert(events.length === 0, 'Cancel with selected unit emits no events');
    assert(fetchCalls.length === 0, 'Cancel with selected unit makes no fetch calls');
    unsubs.forEach(u => u());
})();

(function testMarkerWithSelectedUnit() {
    // marker action ignores selectedUnitId -- event has x,y only
    const events = [];
    const unsub = EventBus.on('map:marker', (d) => events.push(d));
    ContextMenu.handleAction('marker', { x: 42, y: 84 }, 'rover-01');
    assert(events.length === 1, 'Marker emits event even with selectedUnitId');
    assert(events[0].x === 42, 'Marker event x is correct');
    assert(events[0].y === 84, 'Marker event y is correct');
    assert(events[0].unitId === undefined, 'Marker event does not include unitId');
    unsub();
})();

(function testDispatchFetchMethod() {
    fetchCalls = [];
    ContextMenu.handleAction('dispatch', { x: 10, y: 20 }, 'rover-01');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    assert(call.opts.method === 'POST', 'Dispatch fetch uses POST method');
    assert(call.opts.headers['Content-Type'] === 'application/json', 'Dispatch fetch uses JSON content type');
})();

(function testWaypointFetchUrl() {
    fetchCalls = [];
    ContextMenu.handleAction('waypoint', { x: 10, y: 20 }, 'special/unit');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    assert(!!call, 'Waypoint calls /api/amy/command for unit with special chars');
    if (call) {
        const body = JSON.parse(call.opts.body);
        assert(body.params[0] === 'special/unit', 'Waypoint params includes unit id');
    }
})();

(function testSuggestDispatchFetchMethod() {
    fetchCalls = [];
    ContextMenu.handleAction('suggest_dispatch', { x: 10, y: 20 }, 'rover-01');
    const call = fetchCalls.find(c => c.url === '/api/amy/chat');
    assert(call.opts.method === 'POST', 'Suggest dispatch fetch uses POST method');
    assert(call.opts.headers['Content-Type'] === 'application/json', 'Suggest dispatch uses JSON content type');
})();

(function testSuggestInvestigateFetchBody() {
    fetchCalls = [];
    ContextMenu.handleAction('suggest_investigate', { x: 77, y: 88 }, null);
    const call = fetchCalls.find(c => c.url === '/api/amy/chat');
    const body = JSON.parse(call.opts.body);
    assert(typeof body.text === 'string', 'Investigate body has text string');
    assert(!body.text.includes('null'), 'Investigate body does not include "null" unit');
})();

// ============================================================
// 17. isVisible state tracking
// ============================================================

console.log('\n--- isVisible state tracking ---');

(function testIsVisibleFalseInitially() {
    ContextMenu.hide(); // ensure clean state
    assert(!ContextMenu.isVisible(), 'isVisible() is false when no menu exists');
})();

(function testIsVisibleTrueAfterShow() {
    const container = createMockElement('div');
    ContextMenu.show(container, null, { x: 0, y: 0 }, 100, 100);
    assert(ContextMenu.isVisible(), 'isVisible() is true after show()');
    ContextMenu.hide();
})();

(function testIsVisibleFalseAfterHide() {
    const container = createMockElement('div');
    ContextMenu.show(container, 'rover-01', { x: 0, y: 0 }, 100, 100);
    ContextMenu.hide();
    assert(!ContextMenu.isVisible(), 'isVisible() is false after hide()');
})();

(function testIsVisibleAfterReshow() {
    const container = createMockElement('div');
    ContextMenu.show(container, null, { x: 0, y: 0 }, 100, 100);
    ContextMenu.hide();
    ContextMenu.show(container, 'drone-01', { x: 0, y: 0 }, 200, 200);
    assert(ContextMenu.isVisible(), 'isVisible() is true after re-show');
    ContextMenu.hide();
})();

// ============================================================
// 18. DOM element details
// ============================================================

console.log('\n--- DOM element details ---');

(function testMenuHasFixedPosition() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    assert(el.style.position === 'fixed', 'Menu has position: fixed');
})();

(function testMenuHasHighZIndex() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, null, { x: 50, y: 100 }, 400, 300);
    assert(el.style.zIndex === '9999', 'Menu has z-index 9999');
})();

(function testMenuItemTextContentFormat() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    const items = el.querySelectorAll('.map-context-item');
    if (items.length > 0) {
        const first = items[0];
        assert(first.textContent.includes('DISPATCH HERE'), 'First item textContent includes label');
        assert(first.textContent.startsWith('>'), 'First item textContent starts with icon');
    }
})();

(function testMenuItemDatasetAction() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    const items = el.querySelectorAll('.map-context-item');
    if (items.length > 0) {
        assert(items[0].dataset.action === 'dispatch', 'First item has data-action="dispatch"');
        assert(items[items.length - 1].dataset.action === 'cancel', 'Last item has data-action="cancel"');
    }
})();

(function testMenuPositionInPixels() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, null, { x: 0, y: 0 }, 500, 300);
    assert(el.style.left === '500px', 'Menu left style includes px units');
    assert(el.style.top === '300px', 'Menu top style includes px units');
})();

(function testShowIsProxyForCreateMenuElement() {
    const container = createMockElement('div');
    ContextMenu.hide();
    const el = ContextMenu.show(container, 'rover-01', { x: 0, y: 0 }, 100, 100);
    assert(el !== null, 'show() returns an element');
    assert(el.className.includes('map-context-menu'), 'show() returns the menu element');
    assert(ContextMenu.isVisible(), 'show() makes menu visible');
    ContextMenu.hide();
})();

// ============================================================
// 19. Escape key handler cleanup
// ============================================================

console.log('\n--- Escape key handler cleanup ---');

(function testEscapeHandlerRemovedAfterHide() {
    const container = createMockElement('div');
    const keydownBefore = (keyListeners['keydown'] || []).length;
    ContextMenu.show(container, null, { x: 0, y: 0 }, 100, 100);
    const keydownDuring = (keyListeners['keydown'] || []).length;
    assert(keydownDuring > keydownBefore, 'show() adds a keydown listener');
    ContextMenu.hide();
    const keydownAfter = (keyListeners['keydown'] || []).length;
    assert(keydownAfter === keydownBefore, 'hide() removes the keydown listener');
})();

(function testNonEscapeKeyDoesNotCloseMenu() {
    const container = createMockElement('div');
    ContextMenu.show(container, null, { x: 0, y: 0 }, 100, 100);
    // Simulate pressing a non-Escape key
    if (keyListeners['keydown']) {
        keyListeners['keydown'].forEach(fn => fn({ key: 'Enter' }));
    }
    assert(ContextMenu.isVisible(), 'Enter key does not close menu');
    ContextMenu.hide();
})();

(function testOtherKeysIgnored() {
    const container = createMockElement('div');
    ContextMenu.show(container, null, { x: 0, y: 0 }, 100, 100);
    // Try various keys that should not close the menu
    const keys = ['Tab', 'ArrowUp', 'ArrowDown', 'a', ' ', 'Control', 'Shift'];
    for (const key of keys) {
        if (keyListeners['keydown']) {
            keyListeners['keydown'].forEach(fn => fn({ key }));
        }
    }
    assert(ContextMenu.isVisible(), 'Non-Escape keys do not close menu');
    ContextMenu.hide();
})();

// ============================================================
// 20. Menu click handler behavior
// ============================================================

console.log('\n--- Menu click handler ---');

(function testMenuClickOnNonItemIgnored() {
    const container = createMockElement('div');
    const el = ContextMenu.createMenuElement(container, 'rover-01', { x: 50, y: 100 }, 400, 300);
    fetchCalls = [];
    const events = [];
    const unsub = EventBus.on('unit:dispatch', (d) => events.push(d));
    // Simulate clicking on the menu background (no data-action)
    const fakeTarget = { closest: () => null, dataset: {} };
    if (el._eventListeners && el._eventListeners['click']) {
        el._eventListeners['click'].forEach(fn => fn({ target: fakeTarget }));
    }
    assert(events.length === 0, 'Clicking menu background emits no events');
    assert(fetchCalls.length === 0, 'Clicking menu background makes no fetch calls');
    unsub();
    ContextMenu.hide();
})();

(function testMenuClickHidesMenuAfterAction() {
    const container = createMockElement('div');
    ContextMenu.createMenuElement(container, null, { x: 0, y: 0 }, 100, 100);
    assert(ContextMenu.isVisible(), 'Menu is visible before action click');
    // Simulate clicking the marker item
    const items = container.querySelectorAll('.map-context-menu');
    if (items.length > 0) {
        const menuEl = items[0];
        const menuItems = menuEl.querySelectorAll('.map-context-item');
        if (menuItems.length > 0) {
            const markerItem = menuItems[0]; // DROP MARKER
            const fakeTarget = {
                closest: (sel) => {
                    if (sel === '.map-context-item') return markerItem;
                    return null;
                },
                dataset: markerItem.dataset,
            };
            if (menuEl._eventListeners && menuEl._eventListeners['click']) {
                menuEl._eventListeners['click'].forEach(fn => fn({ target: fakeTarget }));
            }
        }
    }
    // After clicking an item, menu should be hidden
    assert(!ContextMenu.isVisible(), 'Menu is hidden after item click');
})();

// ============================================================
// 21. Multiple show() calls replace previous menu
// ============================================================

console.log('\n--- Multiple show calls ---');

(function testMultipleShowCallsOnDifferentContainers() {
    const container1 = createMockElement('div');
    const container2 = createMockElement('div');
    ContextMenu.show(container1, 'rover-01', { x: 0, y: 0 }, 100, 100);
    assert(ContextMenu.isVisible(), 'First show makes menu visible');
    ContextMenu.show(container2, 'drone-01', { x: 0, y: 0 }, 200, 200);
    assert(ContextMenu.isVisible(), 'Second show keeps menu visible');
    const menus1 = container1.querySelectorAll('.map-context-menu');
    // First container's menu should have been removed
    assert(menus1.length === 0, 'First container has no menu after second show()');
    const menus2 = container2.querySelectorAll('.map-context-menu');
    assert(menus2.length === 1, 'Second container has exactly one menu');
    ContextMenu.hide();
})();

// ============================================================
// 22. Dispatch and waypoint fetch body details
// ============================================================

console.log('\n--- Fetch body validation ---');

(function testDispatchFetchBodyStructure() {
    fetchCalls = [];
    ContextMenu.handleAction('dispatch', { x: 123.456, y: 789.012 }, 'tank-01');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    const body = JSON.parse(call.opts.body);
    assert(body.action === 'dispatch', 'Dispatch body action field is "dispatch"');
    assert(body.params.length === 3, 'Dispatch params has 3 elements');
    assert(body.params[0] === 'tank-01', 'Dispatch params[0] is unit id');
    assert(body.params[1] === 123.456, 'Dispatch params[1] is raw x (not rounded)');
    assert(body.params[2] === 789.012, 'Dispatch params[2] is raw y (not rounded)');
})();

(function testWaypointFetchBodyStructure() {
    fetchCalls = [];
    ContextMenu.handleAction('waypoint', { x: 55.5, y: 66.6 }, 'rover-02');
    const call = fetchCalls.find(c => c.url === '/api/amy/command');
    const body = JSON.parse(call.opts.body);
    assert(body.action === 'dispatch', 'Waypoint body uses Lua dispatch action');
    assert(body.params[0] === 'rover-02', 'Waypoint params[0] is unit id');
    assert(body.params[1] === 55.5, 'Waypoint params[1] is x');
    assert(body.params[2] === 66.6, 'Waypoint params[2] is y');
})();

(function testSuggestDispatchBodyText() {
    fetchCalls = [];
    ContextMenu.handleAction('suggest_dispatch', { x: 12.9, y: 34.1 }, 'drone-02');
    const call = fetchCalls.find(c => c.url === '/api/amy/chat');
    const body = JSON.parse(call.opts.body);
    // buildSuggestCommand rounds coordinates
    assert(body.text.includes('13'), 'Suggest dispatch body rounds x 12.9 to 13');
    assert(body.text.includes('34'), 'Suggest dispatch body rounds y 34.1 to 34');
    assert(body.text.includes('drone-02'), 'Suggest dispatch body includes unit ID');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
