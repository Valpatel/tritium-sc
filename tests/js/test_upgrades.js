// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Upgrade & Ability UI Tests
 * Tests upgrade card rendering, ability button states, cost formatting,
 * phase visibility, and cooldown display.
 * Run: node tests/js/test_upgrades.js
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertContains(str, sub, msg) {
    assert(typeof str === 'string' && str.includes(sub), msg + ` (expected "${sub}" in output)`);
}

// ============================================================
// Load game-hud.js to get access to window.UpgradeHelpers
// ============================================================

function createMockElement(tag) {
    let _textContent = '';
    let _innerHTML = '';
    const style = {};
    const el = {
        tagName: tag || 'DIV',
        className: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(v) { _innerHTML = v; },
        get textContent() { return _textContent; },
        set textContent(v) {
            _textContent = String(v);
            _innerHTML = String(v)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;');
        },
        style,
        children: [],
        childNodes: [],
        classList: {
            _set: new Set(),
            add(cls) { this._set.add(cls); },
            remove(cls) { this._set.delete(cls); },
            contains(cls) { return this._set.has(cls); },
            toggle(cls) { this._set.has(cls) ? this._set.delete(cls) : this._set.add(cls); },
        },
        appendChild(c) { el.children.push(c); return c; },
        removeChild(c) { el.children = el.children.filter(x => x !== c); return c; },
        querySelector(sel) { return null; },
        querySelectorAll(sel) { return []; },
        addEventListener() {},
        removeEventListener() {},
        setAttribute(k, v) { el[k] = v; },
        getAttribute(k) { return el[k]; },
        getBoundingClientRect() { return { top: 0, left: 0, width: 100, height: 100 }; },
    };
    return el;
}

const ctx = vm.createContext({
    Math, console, Array, Object, Number, Boolean, String, parseInt, parseFloat, Infinity, JSON,
    Date: { now: () => 10000 },
    setTimeout: (fn, ms) => 1,
    clearTimeout: () => {},
    setInterval: (fn, ms) => 1,
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    window: {},
    document: {
        getElementById(id) { return createMockElement('div'); },
        createElement(tag) { return createMockElement(tag); },
        createTextNode(t) { return { textContent: t }; },
    },
    exports: {},
    module: { exports: {} },
});

// Load the game-hud.js file (it will register helpers on window)
const hudCode = fs.readFileSync(__dirname + '/../../src/frontend/js/command/panels/game-hud.js', 'utf8');
// Strip ES module syntax for Node.js
const hudClean = hudCode
    .replace(/import\s*\{[^}]*\}\s*from\s*['"][^'"]*['"];?/g, '')
    .replace(/export\s+/g, '');
vm.runInContext(hudClean, ctx);

// Verify UpgradeHelpers is exposed
const helpers = ctx.window.UpgradeHelpers;

// ============================================================
// Tests for buildUpgradeCardHTML
// ============================================================

console.log('\n--- buildUpgradeCardHTML tests ---');

assert(typeof helpers === 'object' && helpers !== null, 'UpgradeHelpers should be exposed on window');

assert(typeof helpers.buildUpgradeCardHTML === 'function', 'buildUpgradeCardHTML should be a function');

{
    const html = helpers.buildUpgradeCardHTML({
        upgrade_id: 'armor_plating',
        name: 'Armor Plating',
        description: 'Increase max health by 25%',
        cost: 100,
        stat_modifiers: { max_health: 1.25 },
    });
    assertContains(html, 'ghud-upgrade-card', 'upgrade card has CSS class');
    assertContains(html, 'Armor Plating', 'upgrade card shows name');
    assertContains(html, 'Increase max health by 25%', 'upgrade card shows description');
    assertContains(html, '100', 'upgrade card shows cost');
    assertContains(html, 'armor_plating', 'upgrade card has data attribute or id');
}

{
    const html = helpers.buildUpgradeCardHTML({
        upgrade_id: 'turbo_motor',
        name: 'Turbo Motor',
        description: 'Increase speed by 20%',
        cost: 0,
        stat_modifiers: { speed: 1.2 },
    });
    assertContains(html, 'Turbo Motor', 'turbo motor card shows name');
    assertContains(html, 'ghud-upgrade-card', 'turbo motor card has CSS class');
}

// ============================================================
// Tests for buildUpgradeGridHTML
// ============================================================

console.log('\n--- buildUpgradeGridHTML tests ---');

assert(typeof helpers.buildUpgradeGridHTML === 'function', 'buildUpgradeGridHTML should be a function');

{
    const html = helpers.buildUpgradeGridHTML([
        { upgrade_id: 'armor_plating', name: 'Armor Plating', description: 'desc1', cost: 100, stat_modifiers: {} },
        { upgrade_id: 'rapid_fire', name: 'Rapid Fire', description: 'desc2', cost: 200, stat_modifiers: {} },
    ]);
    assertContains(html, 'Armor Plating', 'grid shows first upgrade');
    assertContains(html, 'Rapid Fire', 'grid shows second upgrade');
    assertContains(html, 'ghud-upgrade-grid', 'grid has container class');
}

{
    const html = helpers.buildUpgradeGridHTML([]);
    assertContains(html, 'ghud-empty', 'empty grid shows empty message');
}

// ============================================================
// Tests for buildAbilityButtonHTML
// ============================================================

console.log('\n--- buildAbilityButtonHTML tests ---');

assert(typeof helpers.buildAbilityButtonHTML === 'function', 'buildAbilityButtonHTML should be a function');

{
    const html = helpers.buildAbilityButtonHTML({
        ability_id: 'speed_boost',
        name: 'Speed Boost',
        description: 'Double speed for 5s',
        cooldown: 30,
        duration: 5,
    }, { ready: true });
    assertContains(html, 'unit-ability-btn', 'ability button has CSS class');
    assertContains(html, 'unit-ability-btn--ready', 'ready ability has ready class');
    assertContains(html, 'Speed Boost', 'ability button shows name');
    assertContains(html, 'speed_boost', 'ability button has data attribute');
}

{
    const html = helpers.buildAbilityButtonHTML({
        ability_id: 'shield',
        name: 'Energy Shield',
        description: 'Block 50% damage for 8s',
        cooldown: 45,
        duration: 8,
    }, { ready: false, cooldownRemaining: 12.5 });
    assertContains(html, 'unit-ability-btn--cooldown', 'cooldown ability has cooldown class');
    assertContains(html, '12', 'cooldown shows remaining seconds');
    assert(!html.includes('unit-ability-btn--ready'), 'cooldown ability should not have ready class');
}

{
    const html = helpers.buildAbilityButtonHTML({
        ability_id: 'emergency_repair',
        name: 'Emergency Repair',
        description: 'Restore 30% health',
        cooldown: 60,
        duration: 0,
    }, { ready: true });
    assertContains(html, 'Emergency Repair', 'repair ability shows name');
    assertContains(html, 'unit-ability-btn--ready', 'repair ability is ready');
}

// ============================================================
// Tests for buildAbilityBarHTML
// ============================================================

console.log('\n--- buildAbilityBarHTML tests ---');

assert(typeof helpers.buildAbilityBarHTML === 'function', 'buildAbilityBarHTML should be a function');

{
    const abilities = [
        { ability_id: 'speed_boost', name: 'Speed Boost', description: 'd', cooldown: 30, duration: 5 },
        { ability_id: 'shield', name: 'Energy Shield', description: 'd', cooldown: 45, duration: 8 },
    ];
    const cooldowns = { speed_boost: 0, shield: 10 };
    const html = helpers.buildAbilityBarHTML(abilities, cooldowns);
    assertContains(html, 'Speed Boost', 'bar shows speed boost');
    assertContains(html, 'Energy Shield', 'bar shows shield');
    assertContains(html, 'unit-ability-btn--ready', 'speed boost is ready (cooldown 0)');
    assertContains(html, 'unit-ability-btn--cooldown', 'shield is on cooldown');
}

{
    const html = helpers.buildAbilityBarHTML([], {});
    assert(html === '' || html.trim() === '', 'empty ability list renders empty string');
}

// ============================================================
// Tests for formatUpgradeCost
// ============================================================

console.log('\n--- formatUpgradeCost tests ---');

assert(typeof helpers.formatUpgradeCost === 'function', 'formatUpgradeCost should be a function');

{
    assert(helpers.formatUpgradeCost(0) === 'FREE', 'zero cost is FREE');
    assert(helpers.formatUpgradeCost(100) === '100', 'numeric cost renders as string');
    assert(helpers.formatUpgradeCost(1500) === '1500', 'large cost renders correctly');
}

// ============================================================
// Tests for upgradeIcon
// ============================================================

console.log('\n--- upgradeIcon tests ---');

assert(typeof helpers.upgradeIcon === 'function', 'upgradeIcon should be a function');

{
    // Each upgrade type should return a string icon
    const armorIcon = helpers.upgradeIcon('armor_plating');
    assert(typeof armorIcon === 'string' && armorIcon.length > 0, 'armor_plating has icon');
    const opticsIcon = helpers.upgradeIcon('enhanced_optics');
    assert(typeof opticsIcon === 'string' && opticsIcon.length > 0, 'enhanced_optics has icon');
    const unknownIcon = helpers.upgradeIcon('nonexistent');
    assert(typeof unknownIcon === 'string' && unknownIcon.length > 0, 'unknown upgrade has fallback icon');
}

// ============================================================
// Tests for abilityIcon
// ============================================================

console.log('\n--- abilityIcon tests ---');

assert(typeof helpers.abilityIcon === 'function', 'abilityIcon should be a function');

{
    const speedIcon = helpers.abilityIcon('speed_boost');
    assert(typeof speedIcon === 'string' && speedIcon.length > 0, 'speed_boost has icon');
    const repairIcon = helpers.abilityIcon('emergency_repair');
    assert(typeof repairIcon === 'string' && repairIcon.length > 0, 'emergency_repair has icon');
    const shieldIcon = helpers.abilityIcon('shield');
    assert(typeof shieldIcon === 'string' && shieldIcon.length > 0, 'shield has icon');
    const empIcon = helpers.abilityIcon('emp_burst');
    assert(typeof empIcon === 'string' && empIcon.length > 0, 'emp_burst has icon');
    const overclockIcon = helpers.abilityIcon('overclock');
    assert(typeof overclockIcon === 'string' && overclockIcon.length > 0, 'overclock has icon');
}

// ============================================================
// Tests for isUpgradePhase
// ============================================================

console.log('\n--- isUpgradePhase tests ---');

assert(typeof helpers.isUpgradePhase === 'function', 'isUpgradePhase should be a function');

{
    assert(helpers.isUpgradePhase('wave_complete') === true, 'wave_complete is upgrade phase');
    assert(helpers.isUpgradePhase('active') === false, 'active is NOT upgrade phase');
    assert(helpers.isUpgradePhase('idle') === false, 'idle is NOT upgrade phase');
    assert(helpers.isUpgradePhase('setup') === false, 'setup is NOT upgrade phase');
    assert(helpers.isUpgradePhase('countdown') === false, 'countdown is NOT upgrade phase');
    assert(helpers.isUpgradePhase('victory') === false, 'victory is NOT upgrade phase');
    assert(helpers.isUpgradePhase('defeat') === false, 'defeat is NOT upgrade phase');
}

// ============================================================
// Tests for formatCooldown
// ============================================================

console.log('\n--- formatCooldown tests ---');

assert(typeof helpers.formatCooldown === 'function', 'formatCooldown should be a function');

{
    assert(helpers.formatCooldown(0) === '', 'zero cooldown is empty string');
    assert(helpers.formatCooldown(5) === '5s', 'small cooldown in seconds');
    assert(helpers.formatCooldown(12.7) === '12s', 'fractional cooldown rounds down');
    assert(helpers.formatCooldown(60) === '60s', 'one minute cooldown');
    assert(helpers.formatCooldown(-1) === '', 'negative cooldown is empty string');
}

// ============================================================
// Tests for upgrade eligibility check
// ============================================================

console.log('\n--- canApplyUpgrade tests ---');

assert(typeof helpers.canApplyUpgrade === 'function', 'canApplyUpgrade should be a function');

{
    const upgrade = { eligible_types: ['turret', 'rover'] };
    assert(helpers.canApplyUpgrade(upgrade, 'turret') === true, 'turret eligible for turret+rover upgrade');
    assert(helpers.canApplyUpgrade(upgrade, 'rover') === true, 'rover eligible for turret+rover upgrade');
    assert(helpers.canApplyUpgrade(upgrade, 'drone') === false, 'drone NOT eligible for turret+rover upgrade');
}

{
    const upgrade = { eligible_types: null };
    assert(helpers.canApplyUpgrade(upgrade, 'anything') === true, 'null eligible_types means all types allowed');
}

{
    const upgrade = {};
    assert(helpers.canApplyUpgrade(upgrade, 'turret') === true, 'missing eligible_types means all types allowed');
}

// ============================================================
// Summary
// ============================================================
console.log(`\n${'='.repeat(50)}`);
console.log(`UPGRADES TESTS: ${passed} passed, ${failed} failed`);
process.exit(failed > 0 ? 1 : 0);
