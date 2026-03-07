// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Inventory Panel tests
 * Tests _renderInventory() function: friendly full items, hostile classified,
 * empty/null inventory, active weapon badge, armor durability bar, ammo counter.
 * Run: node tests/js/test_inventory_panel.js
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
        _childCache: {},
        querySelector(sel) {
            if (el._childCache[sel]) return el._childCache[sel];
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement(bindMatch[1] === 'filter' ? 'select' : 'div');
                mock._bindName = bindMatch[1];
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
const eventsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/events.js', 'utf8');
const eventsPlain = eventsCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(eventsPlain, ctx);

// Load store.js (TritiumStore)
const storeCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/store.js', 'utf8');
const storePlain = storeCode
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(storePlain, ctx);

// Load units.js panel
const unitsCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/units.js', 'utf8');
const unitsPlain = unitsCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(unitsPlain, ctx);

// Get references
const _renderInventory = vm.runInContext('_renderInventory', ctx);
const UnitsPanelDef = ctx.UnitsPanelDef;

// ============================================================
// Helper: get detail HTML for a unit with given data
// ============================================================

function getDetailHtml(unitData) {
    const TritiumStore = vm.runInContext('TritiumStore', ctx);
    TritiumStore.units.clear();

    const bodyEl = UnitsPanelDef.create({});
    const panel = { def: UnitsPanelDef, _unsubs: [] };

    TritiumStore.updateUnit(unitData.id, unitData);
    TritiumStore.set('map.selectedUnitId', unitData.id);

    UnitsPanelDef.mount(bodyEl, panel);

    const detailEl = bodyEl.querySelector('[data-bind="detail"]');
    return detailEl ? detailEl.innerHTML : '';
}


// ============================================================
// 1. _renderInventory function exists
// ============================================================

console.log('\n--- _renderInventory function ---');

(function test_renderInventory_exists() {
    assert(typeof _renderInventory === 'function', '_renderInventory is a function');
})();

// ============================================================
// 2. Friendly inventory: full item rendering
// ============================================================

console.log('\n--- Friendly inventory rendering ---');

(function test_render_inventory_friendly() {
    const inventory = {
        items: [
            { item_id: 'nerf_rifle_1', item_type: 'weapon', name: 'Nerf Rifle', damage: 12, range: 40, ammo: 18, max_ammo: 20 },
            { item_id: 'medium_vest_1', item_type: 'armor', name: 'Medium Vest', damage_reduction: 0.2, durability: 45, max_durability: 50 },
            { item_id: 'frag_grenade_1', item_type: 'grenade', name: 'Frag Grenade', grenade_damage: 40, blast_radius: 5.0, count: 2 },
        ],
        active_weapon_id: 'nerf_rifle_1',
    };
    const html = _renderInventory(inventory);
    assert(html.includes('INVENTORY'), 'Friendly inventory shows INVENTORY header');
    assert(html.includes('Nerf Rifle'), 'Friendly inventory shows weapon name');
    assert(html.includes('Medium Vest'), 'Friendly inventory shows armor name');
    assert(html.includes('Frag Grenade'), 'Friendly inventory shows grenade name');
    assert(html.includes('unit-inv-weapon'), 'Weapon row has unit-inv-weapon class');
    assert(html.includes('unit-inv-armor'), 'Armor row has unit-inv-armor class');
    assert(html.includes('unit-inv-grenade'), 'Grenade row has unit-inv-grenade class');
})();

(function test_render_inventory_friendly_type_labels() {
    const inventory = {
        items: [
            { item_id: 'w1', item_type: 'weapon', name: 'Blaster', ammo: 10, max_ammo: 10 },
            { item_id: 'a1', item_type: 'armor', name: 'Vest', durability: 50, max_durability: 50 },
            { item_id: 'g1', item_type: 'grenade', name: 'Smoke', count: 1 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('[GUN]'), 'Weapon type label is [GUN]');
    assert(html.includes('[SHIELD]'), 'Armor type label is [SHIELD]');
    assert(html.includes('[BOMB]'), 'Grenade type label is [BOMB]');
})();

// ============================================================
// 3. Hostile inventory: CLASSIFIED view
// ============================================================

console.log('\n--- Hostile/classified inventory ---');

(function test_render_inventory_hostile() {
    const inventory = { status: 'unknown', item_count: 4 };
    const html = _renderInventory(inventory);
    assert(html.includes('INVENTORY'), 'Hostile inventory shows INVENTORY header');
    assert(html.includes('CLASSIFIED'), 'Hostile inventory shows CLASSIFIED label');
    assert(html.includes('unit-inv-classified'), 'Hostile inventory uses classified class');
    assert(html.includes('4'), 'Hostile inventory shows item count 4');
    assert(html.includes('unidentified'), 'Hostile inventory shows unidentified text');
})();

(function test_render_inventory_hostile_single_item() {
    const inventory = { status: 'unknown', item_count: 1 };
    const html = _renderInventory(inventory);
    assert(html.includes('1 item'), 'Single item shows singular "item"');
    assert(!html.includes('1 items'), 'Single item does not show plural "items"');
})();

(function test_render_inventory_hostile_classified_bar() {
    const inventory = { status: 'unknown', item_count: 3 };
    const html = _renderInventory(inventory);
    assert(html.includes('\u2588\u2588\u2588'), 'Classified view has redacted bar characters');
    assert(html.includes('unit-inv-classified-bar'), 'Classified bar has correct class');
})();

// ============================================================
// 4. Empty/null inventory
// ============================================================

console.log('\n--- Empty/null inventory ---');

(function test_render_inventory_null() {
    const html = _renderInventory(null);
    assert(html === '', 'null inventory returns empty string');
})();

(function test_render_inventory_undefined() {
    const html = _renderInventory(undefined);
    assert(html === '', 'undefined inventory returns empty string');
})();

(function test_render_inventory_empty_items() {
    const html = _renderInventory({ items: [] });
    assert(html === '', 'Empty items array returns empty string');
})();

(function test_render_inventory_no_items_key() {
    const html = _renderInventory({});
    assert(html === '', 'Object with no items or status returns empty string');
})();

// ============================================================
// 5. Active weapon badge
// ============================================================

console.log('\n--- Active weapon badge ---');

(function test_render_active_weapon_badge() {
    const inventory = {
        items: [
            { item_id: 'rifle_1', item_type: 'weapon', name: 'Rifle', ammo: 20, max_ammo: 20 },
            { item_id: 'pistol_1', item_type: 'weapon', name: 'Pistol', ammo: 10, max_ammo: 10 },
        ],
        active_weapon_id: 'rifle_1',
    };
    const html = _renderInventory(inventory);
    assert(html.includes('unit-inv-active'), 'Active weapon has active badge class');
    assert(html.includes('ACTIVE'), 'Active weapon shows ACTIVE text');
})();

(function test_render_inactive_weapon_no_badge() {
    const inventory = {
        items: [
            { item_id: 'rifle_1', item_type: 'weapon', name: 'Rifle', ammo: 20, max_ammo: 20 },
            { item_id: 'pistol_1', item_type: 'weapon', name: 'Pistol', ammo: 10, max_ammo: 10 },
        ],
        active_weapon_id: 'rifle_1',
    };
    const html = _renderInventory(inventory);
    // The Pistol line should not have ACTIVE badge
    // Split by item rows and check
    const lines = html.split('unit-inv-item');
    // Find the Pistol line
    const pistolLine = lines.find(l => l.includes('Pistol'));
    assert(pistolLine && !pistolLine.includes('ACTIVE'), 'Inactive weapon does not have ACTIVE badge');
})();

(function test_render_no_active_weapon() {
    const inventory = {
        items: [
            { item_id: 'rifle_1', item_type: 'weapon', name: 'Rifle', ammo: 20, max_ammo: 20 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(!html.includes('ACTIVE'), 'No ACTIVE badge when active_weapon_id is null');
})();

// ============================================================
// 6. Armor durability bar
// ============================================================

console.log('\n--- Armor durability bar ---');

(function test_render_armor_durability() {
    const inventory = {
        items: [
            { item_id: 'vest_1', item_type: 'armor', name: 'Heavy Vest', damage_reduction: 0.3, durability: 30, max_durability: 50 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('unit-inv-durability'), 'Armor has durability class');
    assert(html.includes('60%'), 'Armor shows 60% durability (30/50)');
    assert(html.includes('0.3 DR'), 'Armor shows damage reduction');
})();

(function test_render_armor_full_durability() {
    const inventory = {
        items: [
            { item_id: 'vest_2', item_type: 'armor', name: 'Light Vest', damage_reduction: 0.1, durability: 50, max_durability: 50 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('100%'), 'Full durability shows 100%');
})();

(function test_render_armor_durability_bar_chars() {
    const inventory = {
        items: [
            { item_id: 'vest_3', item_type: 'armor', name: 'Test Vest', durability: 25, max_durability: 50 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    // 50% durability = 3 filled + 3 empty in a 6-char bar
    assert(html.includes('\u2588'), 'Durability bar has filled characters');
    assert(html.includes('\u2591'), 'Durability bar has empty characters');
})();

// ============================================================
// 7. Ammo counter
// ============================================================

console.log('\n--- Ammo counter ---');

(function test_render_ammo_counter() {
    const inventory = {
        items: [
            { item_id: 'gun_1', item_type: 'weapon', name: 'Blaster', ammo: 18, max_ammo: 20 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('18/20'), 'Ammo counter shows 18/20');
    assert(html.includes('unit-inv-ammo'), 'Ammo has correct class');
})();

(function test_render_ammo_counter_full() {
    const inventory = {
        items: [
            { item_id: 'gun_2', item_type: 'weapon', name: 'Shotgun', ammo: 6, max_ammo: 6 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('6/6'), 'Full ammo shows 6/6');
})();

(function test_render_ammo_counter_empty() {
    const inventory = {
        items: [
            { item_id: 'gun_3', item_type: 'weapon', name: 'SMG', ammo: 0, max_ammo: 30 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('0/30'), 'Empty ammo shows 0/30');
})();

// ============================================================
// 8. Grenade count
// ============================================================

console.log('\n--- Grenade count ---');

(function test_render_grenade_count() {
    const inventory = {
        items: [
            { item_id: 'nade_1', item_type: 'grenade', name: 'Flash Bang', count: 3 },
        ],
        active_weapon_id: null,
    };
    const html = _renderInventory(inventory);
    assert(html.includes('x3'), 'Grenade shows count x3');
})();

// ============================================================
// 9. Integration: inventory in detail panel
// ============================================================

console.log('\n--- Detail panel integration ---');

(function test_detail_shows_friendly_inventory() {
    const html = getDetailHtml({
        id: 'inv-test-1',
        name: 'Rover-Alpha',
        type: 'rover',
        alliance: 'friendly',
        position: { x: 10, y: 20 },
        health: 150, maxHealth: 150,
        inventory: {
            items: [
                { item_id: 'gun_x', item_type: 'weapon', name: 'Nerf Mega', ammo: 5, max_ammo: 8 },
            ],
            active_weapon_id: 'gun_x',
        },
    });
    assert(html.includes('INVENTORY'), 'Detail panel renders INVENTORY section for friendly unit');
    assert(html.includes('Nerf Mega'), 'Detail panel shows weapon name');
    assert(html.includes('5/8'), 'Detail panel shows ammo counter');
    assert(html.includes('ACTIVE'), 'Detail panel shows ACTIVE badge');
})();

(function test_detail_shows_hostile_classified() {
    const html = getDetailHtml({
        id: 'inv-test-2',
        name: 'Hostile-Bravo',
        type: 'person',
        alliance: 'hostile',
        position: { x: 30, y: 40 },
        health: 100, maxHealth: 100,
        inventory: { status: 'unknown', item_count: 3 },
    });
    assert(html.includes('INVENTORY'), 'Detail panel renders INVENTORY section for hostile unit');
    assert(html.includes('CLASSIFIED'), 'Detail panel shows CLASSIFIED for hostile');
    assert(html.includes('3'), 'Detail panel shows item count');
})();

(function test_detail_no_inventory_when_null() {
    const html = getDetailHtml({
        id: 'inv-test-3',
        name: 'Drone-Charlie',
        type: 'drone',
        alliance: 'friendly',
        position: { x: 0, y: 0 },
        health: 60, maxHealth: 60,
    });
    assert(!html.includes('INVENTORY'), 'No INVENTORY section when inventory is not set');
})();

// ============================================================
// 10. INV_TYPE_LABELS constant
// ============================================================

console.log('\n--- INV_TYPE_LABELS ---');

(function test_inv_type_labels_exists() {
    const labels = vm.runInContext('INV_TYPE_LABELS', ctx);
    assert(typeof labels === 'object' && labels !== null, 'INV_TYPE_LABELS exists');
})();

(function test_inv_type_labels_weapon() {
    const label = vm.runInContext('INV_TYPE_LABELS.weapon', ctx);
    assert(label === 'GUN', 'INV_TYPE_LABELS.weapon is GUN');
})();

(function test_inv_type_labels_armor() {
    const label = vm.runInContext('INV_TYPE_LABELS.armor', ctx);
    assert(label === 'SHIELD', 'INV_TYPE_LABELS.armor is SHIELD');
})();

(function test_inv_type_labels_grenade() {
    const label = vm.runInContext('INV_TYPE_LABELS.grenade', ctx);
    assert(label === 'BOMB', 'INV_TYPE_LABELS.grenade is BOMB');
})();

// ============================================================
// 11. Multiple weapons, only one is active
// ============================================================

console.log('\n--- Multiple weapons active check ---');

(function test_render_multiple_weapons_one_active() {
    const inventory = {
        items: [
            { item_id: 'w1', item_type: 'weapon', name: 'Primary', ammo: 20, max_ammo: 20 },
            { item_id: 'w2', item_type: 'weapon', name: 'Secondary', ammo: 10, max_ammo: 10 },
            { item_id: 'w3', item_type: 'weapon', name: 'Sidearm', ammo: 6, max_ammo: 6 },
        ],
        active_weapon_id: 'w2',
    };
    const html = _renderInventory(inventory);
    // Count ACTIVE occurrences
    const activeCount = (html.match(/ACTIVE/g) || []).length;
    assert(activeCount === 1, 'Only one weapon is marked ACTIVE (count: ' + activeCount + ')');
    // The active one should be near "Secondary"
    const secondaryIdx = html.indexOf('Secondary');
    const activeIdx = html.indexOf('ACTIVE');
    assert(activeIdx > secondaryIdx, 'ACTIVE badge appears after Secondary weapon name');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
