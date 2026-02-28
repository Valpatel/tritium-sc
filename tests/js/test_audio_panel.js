// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Audio Panel tests
 * Tests AudioPanelDef structure, DOM creation, category buttons,
 * volume controls, effects list, _esc utility, and mount wiring.
 * Run: node tests/js/test_audio_panel.js
 */

const fs = require('fs');
const vm = require('vm');

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
        value: '80',
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
        querySelector(sel) {
            const bindMatch = sel.match(/\[data-bind="([^"]+)"\]/);
            if (bindMatch) {
                const mock = createMockElement('div');
                mock._bindName = bindMatch[1];
                if (bindMatch[1] === 'master-vol') mock.value = '80';
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load events.js
const eventsCode = fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8');
vm.runInContext(eventsCode.replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

// Load store.js
const storeCode = fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8');
vm.runInContext(storeCode.replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

// Load audio.js panel
const audioCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/audio.js', 'utf8');
const audioPlain = audioCode
    .replace(/^export\s+const\s+/gm, 'var ')
    .replace(/^export\s+/gm, '')
    .replace(/^import\s+.*$/gm, '');
vm.runInContext(audioPlain, ctx);

const AudioPanelDef = ctx.AudioPanelDef;

// ============================================================
// 1. AudioPanelDef has required properties
// ============================================================

console.log('\n--- AudioPanelDef structure ---');

(function testHasId() {
    assert(AudioPanelDef.id === 'audio', 'AudioPanelDef.id is "audio"');
})();

(function testHasTitle() {
    assert(AudioPanelDef.title === 'AUDIO', 'AudioPanelDef.title is "AUDIO"');
})();

(function testHasCreate() {
    assert(typeof AudioPanelDef.create === 'function', 'AudioPanelDef.create is a function');
})();

(function testHasMount() {
    assert(typeof AudioPanelDef.mount === 'function', 'AudioPanelDef.mount is a function');
})();

(function testHasUnmount() {
    assert(typeof AudioPanelDef.unmount === 'function', 'AudioPanelDef.unmount is a function');
})();

(function testHasDefaultPosition() {
    assert(AudioPanelDef.defaultPosition !== undefined, 'AudioPanelDef has defaultPosition');
    assert(AudioPanelDef.defaultPosition.x === 8, 'defaultPosition.x is 8');
    assert(AudioPanelDef.defaultPosition.y === 8, 'defaultPosition.y is 8');
})();

(function testHasDefaultSize() {
    assert(AudioPanelDef.defaultSize !== undefined, 'AudioPanelDef has defaultSize');
    assert(AudioPanelDef.defaultSize.w === 280, 'defaultSize.w is 280');
    assert(AudioPanelDef.defaultSize.h === 320, 'defaultSize.h is 320');
})();

// ============================================================
// 2. create() returns DOM element with expected structure
// ============================================================

console.log('\n--- create() DOM structure ---');

(function testCreateReturnsDomElement() {
    const el = AudioPanelDef.create({});
    assert(el !== null && el !== undefined, 'create() returns an element');
    assert(el.className === 'audio-panel-inner', 'create() element has correct className');
})();

(function testCreateHasMasterVolume() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="master-vol"'), 'DOM contains master volume slider');
    assert(html.includes('data-bind="master-vol-label"'), 'DOM contains master volume label');
    assert(html.includes('MASTER'), 'DOM contains "MASTER" label');
})();

(function testCreateHasMuteButton() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="mute"'), 'DOM contains MUTE action');
    assert(html.includes('MUTE'), 'DOM contains mute button label');
})();

(function testCreateHasStopAllButton() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-action="stop-all"'), 'DOM contains STOP ALL action');
    assert(html.includes('STOP ALL'), 'DOM contains stop all button label');
})();

(function testCreateHasSectionLabel() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('SOUND EFFECTS'), 'DOM contains SOUND EFFECTS section label');
    assert(html.includes('panel-section-label'), 'Section label has correct class');
})();

(function testCreateHasEffectsList() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-bind="effects-list"'), 'DOM contains effects list data-bind');
    assert(html.includes('panel-list'), 'Effects list has panel-list class');
})();

(function testCreateHasLoadingState() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('Loading effects...'), 'DOM contains loading state');
})();

// ============================================================
// 3. Category filter buttons
// ============================================================

console.log('\n--- Category filter ---');

(function testHasCategoryButtons() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('data-cat="all"'), 'Has ALL category button');
    assert(html.includes('data-cat="combat"'), 'Has COMBAT category button');
    assert(html.includes('data-cat="ambient"'), 'Has AMBIENT category button');
    assert(html.includes('data-cat="ui"'), 'Has UI category button');
    assert(html.includes('data-cat="voice"'), 'Has VOICE category button');
    assert(html.includes('data-cat="alert"'), 'Has ALERT category button');
})();

(function testAllCategoryDefaultActive() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('audio-cat-btn mono active'), 'ALL category is active by default');
})();

(function testCategoryLabelsUppercase() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('>ALL<'), 'Category ALL has uppercase label');
    assert(html.includes('>COMBAT<'), 'Category COMBAT has uppercase label');
    assert(html.includes('>AMBIENT<'), 'Category AMBIENT has uppercase label');
    assert(html.includes('>UI<'), 'Category UI has uppercase label');
})();

// ============================================================
// 4. Accessibility
// ============================================================

console.log('\n--- Accessibility ---');

(function testEffectsListRole() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('role="listbox"'), 'Effects list has role="listbox"');
})();

(function testEffectsListAriaLabel() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('aria-label="Sound effects"'), 'Effects list has aria-label');
})();

// ============================================================
// 5. Volume slider attributes
// ============================================================

console.log('\n--- Volume slider ---');

(function testVolumeSliderRange() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('type="range"'), 'Volume slider is type=range');
    assert(html.includes('min="0"'), 'Volume slider min is 0');
    assert(html.includes('max="100"'), 'Volume slider max is 100');
    assert(html.includes('value="80"'), 'Volume slider default is 80');
})();

(function testDefaultVolumeLabel() {
    const el = AudioPanelDef.create({});
    const html = el.innerHTML;
    assert(html.includes('80%'), 'Default volume label shows 80%');
})();

// ============================================================
// 6. CATEGORIES constant
// ============================================================

console.log('\n--- CATEGORIES constant ---');

(function testCategoriesExists() {
    const cats = vm.runInContext('CATEGORIES', ctx);
    assert(Array.isArray(cats), 'CATEGORIES is an array');
})();

(function testCategoriesCount() {
    const cats = vm.runInContext('CATEGORIES', ctx);
    assert(cats.length === 6, 'CATEGORIES has 6 entries, got ' + cats.length);
})();

(function testCategoriesFirstIsAll() {
    const cats = vm.runInContext('CATEGORIES', ctx);
    assert(cats[0] === 'all', 'First category is "all"');
})();

// ============================================================
// 7. mount() wires cleanup and fetches
// ============================================================

console.log('\n--- mount() ---');

(function testMountRegistersCleanup() {
    const bodyEl = createMockElement('div');
    const panel = {
        def: AudioPanelDef,
        _unsubs: [],
    };

    AudioPanelDef.mount(bodyEl, panel);
    assert(panel._unsubs.length >= 1, 'mount() registers at least 1 cleanup fn, got ' + panel._unsubs.length);
})();

(function testMountFetchesEffects() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => {
        if (typeof url === 'string' && url.includes('/api/audio/effects')) fetchCalled = true;
        return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    };

    const bodyEl = createMockElement('div');
    const panel = {
        def: AudioPanelDef,
        _unsubs: [],
    };

    AudioPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/audio/effects');
    ctx.fetch = origFetch;
})();

(function testMountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    const panel = { def: AudioPanelDef, _unsubs: [] };

    let threw = false;
    try {
        AudioPanelDef.mount(bodyEl, panel);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 8. unmount()
// ============================================================

console.log('\n--- unmount() ---');

(function testUnmountDoesNotCrash() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try {
        AudioPanelDef.unmount(bodyEl);
    } catch (e) {
        threw = true;
    }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// 9. _esc utility
// ============================================================

console.log('\n--- _esc utility ---');

(function testEscExists() {
    const fn = vm.runInContext('typeof _esc', ctx);
    assert(fn === 'function', '_esc function exists');
})();

(function testEscNull() {
    const result = vm.runInContext('_esc(null)', ctx);
    assert(result === '', '_esc(null) returns empty string');
})();

(function testEscHtml() {
    const result = vm.runInContext('_esc("<script>")', ctx);
    assert(!result.includes('<script>'), '_esc escapes HTML tags');
})();

// ============================================================
// Summary
// ============================================================

console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
