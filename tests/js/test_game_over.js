// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Game Over stats rendering tests
 * Run: node tests/js/test_game_over.js
 *
 * Tests the helper functions used to render after-action stats
 * in the game-over overlay: MVP spotlight, combat stats, unit table,
 * and the enhanced war-hud game over with MVP data.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// Load main.js game-over helpers (we'll inject them as a separate module)
// For now, test the pure helper functions that we'll export from game-over-stats.js

const helpersCode = fs.readFileSync(
    __dirname + '/../../src/frontend/js/command/game-over-stats.js', 'utf8'
);

// Mock DOM
const mockElements = {};
function resetElements() {
    Object.keys(mockElements).forEach(k => delete mockElements[k]);
}

let fetchCalls = [];
let fetchResponses = {};

const ctx = vm.createContext({
    Math, console, Array, Object, Number, Boolean, parseInt, parseFloat,
    Infinity, String, JSON, Promise, Error, isNaN, isFinite, undefined,
    setTimeout: (fn, ms) => fn(),
    clearTimeout: () => {},
    fetch: (url, opts) => {
        fetchCalls.push({ url, opts });
        const resp = fetchResponses[url];
        if (resp) {
            return Promise.resolve({
                ok: true,
                json: () => Promise.resolve(resp),
            });
        }
        return Promise.resolve({
            ok: false,
            json: () => Promise.resolve({}),
        });
    },
    window: {},
    document: {
        getElementById(id) {
            if (!mockElements[id]) {
                mockElements[id] = {
                    style: { display: '', opacity: '' },
                    textContent: '',
                    innerHTML: '',
                    className: '',
                    hidden: false,
                    children: [],
                    querySelectorAll: () => [],
                    querySelector: () => null,
                    classList: {
                        _classes: [],
                        add(cls) { this._classes.push(cls); },
                        remove(cls) { this._classes = this._classes.filter(c => c !== cls); },
                        contains(cls) { return this._classes.includes(cls); },
                    },
                    addEventListener: () => {},
                };
            }
            return mockElements[id];
        },
        createElement(tag) {
            const el = {
                _text: '',
                className: '',
                style: {},
                children: [],
                innerHTML: '',
                appendChild(child) { this.children.push(child); },
            };
            Object.defineProperty(el, 'textContent', {
                get() { return el._text; },
                set(v) {
                el._text = String(v);
                // Mimic real browser: textContent setter escapes HTML in innerHTML
                el.innerHTML = String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
            },
            });
            return el;
        },
    },
});

vm.runInContext(helpersCode, ctx);
const w = ctx.window;

// ============================================================
// formatAccuracy
// ============================================================

console.log('\n--- formatAccuracy ---');

assert(w.goFormatAccuracy(0) === '0%', 'accuracy 0 => 0%');
assert(w.goFormatAccuracy(0.5) === '50%', 'accuracy 0.5 => 50%');
assert(w.goFormatAccuracy(1.0) === '100%', 'accuracy 1.0 => 100%');
assert(w.goFormatAccuracy(0.333) === '33%', 'accuracy 0.333 => 33%');
assert(w.goFormatAccuracy(0.999) === '100%', 'accuracy 0.999 => 100%');
assert(w.goFormatAccuracy(null) === '0%', 'accuracy null => 0%');
assert(w.goFormatAccuracy(undefined) === '0%', 'accuracy undefined => 0%');

// ============================================================
// formatDamage
// ============================================================

console.log('\n--- formatDamage ---');

assert(w.goFormatDamage(0) === '0', 'damage 0');
assert(w.goFormatDamage(1234.56) === '1,235', 'damage rounds and formats');
assert(w.goFormatDamage(999) === '999', 'damage 999');
assert(w.goFormatDamage(null) === '0', 'damage null => 0');

// ============================================================
// formatKD
// ============================================================

console.log('\n--- formatKD ---');

assert(w.goFormatKD(5, 2) === '2.50', 'KD 5/2 => 2.50');
assert(w.goFormatKD(5, 0) === '5.00', 'KD 5/0 => 5.00 (kills as ratio)');
assert(w.goFormatKD(0, 0) === '0.00', 'KD 0/0 => 0.00');
assert(w.goFormatKD(0, 3) === '0.00', 'KD 0/3 => 0.00');

// ============================================================
// unitStatusLabel
// ============================================================

console.log('\n--- unitStatusLabel ---');

assert(w.goUnitStatusLabel(100, 0) === 'SURVIVED', 'health > 0 and deaths 0 => SURVIVED');
assert(w.goUnitStatusLabel(0, 1) === 'ELIMINATED', 'health 0 and deaths > 0 => ELIMINATED');
assert(w.goUnitStatusLabel(50, 0) === 'SURVIVED', 'half health, no deaths => SURVIVED');
assert(w.goUnitStatusLabel(0, 0) === 'ELIMINATED', 'health 0 and deaths 0 => ELIMINATED');
assert(w.goUnitStatusLabel(1, 1) === 'SURVIVED', 'health > 0 even with death => SURVIVED');

// ============================================================
// unitStatusColor
// ============================================================

console.log('\n--- unitStatusColor ---');

assert(w.goUnitStatusColor('SURVIVED') === '#05ffa1', 'survived => green');
assert(w.goUnitStatusColor('ELIMINATED') === '#ff2a6d', 'eliminated => magenta');
assert(w.goUnitStatusColor('OTHER') === '#888888', 'unknown => gray');

// ============================================================
// buildMvpSpotlightHtml
// ============================================================

console.log('\n--- buildMvpSpotlightHtml ---');

{
    const mvp = {
        name: 'Turret Alpha',
        kills: 7,
        accuracy: 0.85,
        asset_type: 'turret',
    };
    const html = w.goBuildMvpSpotlightHtml(mvp);
    assert(html.includes('Turret Alpha'), 'MVP name in spotlight');
    assert(html.includes('7'), 'MVP kills in spotlight');
    assert(html.includes('85%'), 'MVP accuracy in spotlight');
    assert(html.includes('turret'), 'MVP asset_type in spotlight');
    assert(html.includes('go-mvp-spotlight'), 'spotlight CSS class present');
}

{
    const html = w.goBuildMvpSpotlightHtml(null);
    assert(html === '', 'null MVP returns empty string');
}

// ============================================================
// buildCombatStatsHtml
// ============================================================

console.log('\n--- buildCombatStatsHtml ---');

{
    const summary = {
        overall_accuracy: 0.72,
        total_damage_dealt: 5432.1,
        total_kills: 15,
        total_deaths: 3,
        total_shots_fired: 120,
        total_shots_hit: 86,
    };
    const html = w.goBuildCombatStatsHtml(summary);
    assert(html.includes('72%'), 'accuracy in combat stats');
    assert(html.includes('5,432'), 'damage in combat stats');
    assert(html.includes('15'), 'kills in combat stats');
    assert(html.includes('go-combat-stats'), 'combat stats CSS class');
    assert(html.includes('go-stat-card'), 'stat card CSS class');
}

{
    const html = w.goBuildCombatStatsHtml(null);
    assert(html === '', 'null summary returns empty string');
}

// ============================================================
// buildUnitTableHtml
// ============================================================

console.log('\n--- buildUnitTableHtml ---');

{
    const units = [
        {
            name: 'Turret Alpha', asset_type: 'turret',
            kills: 7, accuracy: 0.85,
            damage_dealt: 1200, health_remaining: 100, deaths: 0,
        },
        {
            name: 'Rover Beta', asset_type: 'rover',
            kills: 3, accuracy: 0.5,
            damage_dealt: 800, health_remaining: 0, deaths: 1,
        },
    ];
    const html = w.goBuildUnitTableHtml(units);
    assert(html.includes('Turret Alpha'), 'unit name in table');
    assert(html.includes('Rover Beta'), 'second unit in table');
    assert(html.includes('go-unit-table'), 'table CSS class');
    assert(html.includes('SURVIVED'), 'survived status in table');
    assert(html.includes('ELIMINATED'), 'eliminated status in table');
    assert(html.includes('85%'), 'accuracy in unit row');
    assert(html.includes('50%'), 'second unit accuracy');
}

{
    const html = w.goBuildUnitTableHtml([]);
    assert(html === '', 'empty units returns empty string');
}

{
    const html = w.goBuildUnitTableHtml(null);
    assert(html === '', 'null units returns empty string');
}

// Only show friendly units in table
{
    const units = [
        { name: 'Turret', asset_type: 'turret', alliance: 'friendly', kills: 2, accuracy: 0.5, damage_dealt: 100, health_remaining: 50, deaths: 0 },
        { name: 'Hostile', asset_type: 'hostile_kid', alliance: 'hostile', kills: 0, accuracy: 0, damage_dealt: 0, health_remaining: 0, deaths: 1 },
    ];
    const html = w.goBuildUnitTableHtml(units);
    assert(html.includes('Turret'), 'friendly unit in table');
    // The filter only keeps friendlies (alliance not hostile)
    assert(!html.includes('>Hostile<'), 'hostile unit excluded from table');
}

// ============================================================
// buildWarHudMvpHtml (for canvas overlay)
// ============================================================

console.log('\n--- buildWarHudMvpHtml ---');

{
    const mvp = { name: 'Drone-1', kills: 5 };
    const html = w.goBuildWarHudMvpHtml(mvp);
    assert(html.includes('Drone-1'), 'MVP name in war hud');
    assert(html.includes('5'), 'MVP kills in war hud');
    assert(html.includes('MVP'), 'MVP label present');
}

{
    const html = w.goBuildWarHudMvpHtml(null);
    assert(html === '', 'null MVP returns empty string for hud');
}

// ============================================================
// XSS prevention in _goEsc
// ============================================================

console.log('\n--- XSS prevention ---');

{
    // Test that HTML is properly escaped in builder output
    const units = [
        { name: '<script>alert("xss")</script>', alliance: 'friendly', kills: 1, accuracy: 0.5, damage_dealt: 100, deaths: 0 },
    ];
    const html = w.goBuildUnitTableHtml(units);
    assert(!html.includes('<script>'), 'XSS: unit table escapes <script> in unit name');
}

{
    const mvp = { name: '<img onerror=alert(1)>', kills: 1, asset_type: 'turret', accuracy: 0.5, damage_dealt: 100 };
    const html = w.goBuildMvpSpotlightHtml(mvp);
    assert(!html.includes('<img'), 'XSS: MVP spotlight escapes <img> in name');
}

{
    const summary = { overall_accuracy: 0.5, total_damage_dealt: 100, total_kills: 1, total_deaths: 0, total_shots_fired: 10, total_shots_hit: 5 };
    const html = w.goBuildCombatStatsHtml(summary);
    assert(typeof html === 'string' && html.length > 0, 'combat stats HTML renders');
}

// ============================================================
// Summary
// ============================================================

console.log(`\n=== test_game_over.js: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
