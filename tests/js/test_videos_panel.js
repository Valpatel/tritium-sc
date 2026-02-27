/**
 * TRITIUM-SC Videos Panel tests
 * Tests VideosPanelDef structure, DOM creation, navigation, breadcrumb,
 * player area, formatBytes utility, and mount wiring.
 * Run: node tests/js/test_videos_panel.js
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
        src: '',
        play() { return Promise.resolve(); },
        pause() {},
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
            if (bindMatch) { const mock = createMockElement(bindMatch[1] === 'video' ? 'video' : 'div'); mock._bindName = bindMatch[1]; return mock; }
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
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve([]) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/events.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);
vm.runInContext(fs.readFileSync(__dirname + '/../../frontend/js/command/store.js', 'utf8').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const vidCode = fs.readFileSync(__dirname + '/../../frontend/js/command/panels/videos.js', 'utf8');
vm.runInContext(vidCode.replace(/^export\s+const\s+/gm, 'var ').replace(/^export\s+/gm, '').replace(/^import\s+.*$/gm, ''), ctx);

const VideosPanelDef = ctx.VideosPanelDef;

// ============================================================
// 1. Structure
// ============================================================
console.log('\n--- VideosPanelDef structure ---');

(function() { assert(VideosPanelDef.id === 'videos', 'id is "videos"'); })();
(function() { assert(VideosPanelDef.title === 'RECORDINGS', 'title is "RECORDINGS"'); })();
(function() { assert(typeof VideosPanelDef.create === 'function', 'create is a function'); })();
(function() { assert(typeof VideosPanelDef.mount === 'function', 'mount is a function'); })();
(function() { assert(typeof VideosPanelDef.unmount === 'function', 'unmount is a function'); })();
(function() { assert(VideosPanelDef.defaultSize.w === 340, 'defaultSize.w is 340'); })();
(function() { assert(VideosPanelDef.defaultSize.h === 460, 'defaultSize.h is 460'); })();

// ============================================================
// 2. create() DOM
// ============================================================
console.log('\n--- create() DOM ---');

(function() { assert(VideosPanelDef.create({}).className === 'videos-panel-inner', 'className correct'); })();

// ============================================================
// 3. Navigation
// ============================================================
console.log('\n--- Navigation ---');

(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="nav"'), 'Has nav area'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-action="refresh"'), 'Has REFRESH button'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-action="back"'), 'Has BACK button'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="breadcrumb"'), 'Has breadcrumb'); })();

// ============================================================
// 4. Video list
// ============================================================
console.log('\n--- Video list ---');

(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="list"'), 'Has video list'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('Loading channels...'), 'Has loading state'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('role="listbox"'), 'List has role=listbox'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('aria-label="Video recordings"'), 'List has aria-label'); })();

// ============================================================
// 5. Player area
// ============================================================
console.log('\n--- Player ---');

(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="player"'), 'Has player area'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="video"'), 'Has video element'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="player-name"'), 'Has player name'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-bind="player-info"'), 'Has player info'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('data-action="close-player"'), 'Has close player button'); })();
(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('controls'), 'Video has controls attribute'); })();

// ============================================================
// 6. Player hidden by default
// ============================================================
console.log('\n--- Player state ---');

(function() { const html = VideosPanelDef.create({}).innerHTML; assert(html.includes('vid-player') && html.includes('display:none'), 'Player is hidden by default'); })();

// ============================================================
// 7. formatBytes utility
// ============================================================
console.log('\n--- formatBytes ---');

(function() { const fn = vm.runInContext('typeof formatBytes', ctx); assert(fn === 'function', 'formatBytes exists'); })();
(function() { const r = vm.runInContext('formatBytes(0)', ctx); assert(r === '--', 'formatBytes(0) returns "--"'); })();
(function() { const r = vm.runInContext('formatBytes(null)', ctx); assert(r === '--', 'formatBytes(null) returns "--"'); })();
(function() { const r = vm.runInContext('formatBytes(512)', ctx); assert(r === '512 B', 'formatBytes(512) returns "512 B"'); })();
(function() { const r = vm.runInContext('formatBytes(2048)', ctx); assert(r === '2.0 KB', 'formatBytes(2048) returns "2.0 KB"'); })();
(function() { const r = vm.runInContext('formatBytes(5242880)', ctx); assert(r === '5.0 MB', 'formatBytes(5242880) returns "5.0 MB"'); })();

// ============================================================
// 8. mount()
// ============================================================
console.log('\n--- mount() ---');

(function() {
    let fetchCalled = false;
    const origFetch = ctx.fetch;
    ctx.fetch = (url) => { if (typeof url === 'string' && url.includes('/api/videos/channels')) fetchCalled = true; return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }); };
    const bodyEl = createMockElement('div');
    const panel = { def: VideosPanelDef, _unsubs: [] };
    VideosPanelDef.mount(bodyEl, panel);
    assert(fetchCalled, 'mount() fetches /api/videos/channels');
    ctx.fetch = origFetch;
})();

(function() {
    const bodyEl = createMockElement('div');
    const panel = { def: VideosPanelDef, _unsubs: [] };
    let threw = false;
    try { VideosPanelDef.mount(bodyEl, panel); } catch (e) { threw = true; }
    assert(!threw, 'mount() does not crash');
})();

// ============================================================
// 9. unmount()
// ============================================================
console.log('\n--- unmount() ---');

(function() {
    const bodyEl = createMockElement('div');
    let threw = false;
    try { VideosPanelDef.unmount(bodyEl); } catch (e) { threw = true; }
    assert(!threw, 'unmount() does not throw');
})();

// ============================================================
// Summary
// ============================================================
console.log('\n' + '='.repeat(40));
console.log(`Results: ${passed} passed, ${failed} failed`);
console.log('='.repeat(40));
process.exit(failed > 0 ? 1 : 0);
