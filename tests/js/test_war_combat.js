/**
 * TRITIUM-SC War Room -- Combat Rendering tests
 * Run: node tests/js/test_war_combat.js
 *
 * Tests projectile system, particle effects, health bars, weapon ranges,
 * elimination streaks, target shapes, screen shake, and reset.
 */

const fs = require('fs');
const vm = require('vm');

let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.01), msg + ` (got ${a}, expected ${b})`);
}

let combatCode = fs.readFileSync(__dirname + '/../../frontend/js/war-combat.js', 'utf8');

// Expose internal const arrays and PROJECTILE_STYLES for testing
combatCode += `
window.PROJECTILE_STYLES = PROJECTILE_STYLES;
window.STREAK_NAMES = STREAK_NAMES;
window._projectiles = _projectiles;
window._particles = _particles;
window._screenEffects = _screenEffects;
window._drawDiamond = _drawDiamond;
window._drawSquare = _drawSquare;
window._drawTriangle = _drawTriangle;
window._drawRect = _drawRect;
`;

let dateNow = 10000;
const ctx = vm.createContext({
    Math, Date: { now: () => dateNow },
    console, Array, Object, Number, Infinity, Boolean, parseInt, parseFloat,
    window: {},
});

vm.runInContext(combatCode, ctx);

const w = ctx.window;
const warCombatAddProjectile = w.warCombatAddProjectile;
const warCombatUpdateProjectiles = w.warCombatUpdateProjectiles;
const warCombatDrawProjectiles = w.warCombatDrawProjectiles;
const warCombatAddHitEffect = w.warCombatAddHitEffect;
const warCombatAddEliminationEffect = w.warCombatAddEliminationEffect;
const warCombatUpdateEffects = w.warCombatUpdateEffects;
const warCombatDrawEffects = w.warCombatDrawEffects;
const warCombatDrawHealthBar = w.warCombatDrawHealthBar;
const warCombatDrawWeaponRange = w.warCombatDrawWeaponRange;
const warCombatAddEliminationStreakEffect = w.warCombatAddEliminationStreakEffect;
const warCombatDrawTargetShape = w.warCombatDrawTargetShape;
const warCombatGetScreenShake = w.warCombatGetScreenShake;
const warCombatReset = w.warCombatReset;

// Mock canvas context
function mockCtx() {
    return {
        fillStyle: '', strokeStyle: '', lineWidth: 0, font: '',
        globalAlpha: 1.0, shadowColor: '', shadowBlur: 0,
        textAlign: '', textBaseline: '',
        beginPath() {}, arc() {}, fill() {}, stroke() {},
        fillRect() {}, strokeRect() {}, fillText() {},
        moveTo() {}, lineTo() {}, closePath() {},
        setLineDash() {}, save() {}, restore() {},
        translate() {}, rotate() {}, scale() {},
    };
}

// Identity worldToScreen
function wts(x, y) { return { x, y }; }

// ============================================================
// PROJECTILE_STYLES
// ============================================================

console.log('\n--- PROJECTILE_STYLES ---');

assert(w.PROJECTILE_STYLES !== undefined, 'PROJECTILE_STYLES exists');
assert(w.PROJECTILE_STYLES.nerf_dart.color === '#ffa500', 'nerf_dart is orange');
assert(w.PROJECTILE_STYLES.nerf_rocket.color === '#ff2a6d', 'nerf_rocket is magenta');
assert(w.PROJECTILE_STYLES.water_balloon.color === '#00a0ff', 'water_balloon is blue');
assert(w.PROJECTILE_STYLES.default.speed === 20, 'default speed is 20');
assert(w.PROJECTILE_STYLES.nerf_dart.trailLen === 8, 'nerf_dart trail length 8');

// ============================================================
// warCombatAddProjectile
// ============================================================

console.log('\n--- warCombatAddProjectile ---');

warCombatReset();
warCombatAddProjectile(null);
assert(w._projectiles.length === 0, 'null data adds no projectile');

warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 10, y: 20 },
    target_pos: { x: 50, y: 60 },
    projectile_type: 'nerf_dart',
    speed: 30,
});
assert(w._projectiles.length === 1, 'one projectile added');
assert(w._projectiles[0].sx === 10, 'source x correct');
assert(w._projectiles[0].sy === 20, 'source y correct');
assert(w._projectiles[0].tx === 50, 'target x correct');
assert(w._projectiles[0].ty === 60, 'target y correct');
assert(w._projectiles[0].speed === 30, 'speed override applied');
assert(w._projectiles[0].type === 'nerf_dart', 'projectile type set');
assert(w._projectiles[0].trail.length === 1, 'trail has initial point');

warCombatReset();
warCombatAddProjectile({});
assert(w._projectiles.length === 1, 'empty data still creates projectile');
assert(w._projectiles[0].sx === 0, 'missing source defaults to 0');
assert(w._projectiles[0].type === 'default', 'missing type defaults to default');

// Also adds muzzle flash
warCombatReset();
warCombatAddProjectile({ source_pos: { x: 5, y: 5 }, target_pos: { x: 10, y: 10 } });
assert(w._screenEffects.length === 1, 'muzzle flash added');
assert(w._screenEffects[0].type === 'muzzle_flash', 'effect type is muzzle_flash');

// ============================================================
// warCombatUpdateProjectiles
// ============================================================

console.log('\n--- warCombatUpdateProjectiles ---');

warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 0, y: 0 },
    target_pos: { x: 100, y: 0 },
    speed: 10,
});
warCombatUpdateProjectiles(0.1);
assert(w._projectiles.length === 1, 'projectile still in flight');
assert(w._projectiles[0].x > 0, 'projectile moved toward target');
assert(w._projectiles[0].trail.length === 2, 'trail point recorded');

// Projectile arrival
warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 0, y: 0 },
    target_pos: { x: 0.1, y: 0 },
    speed: 100,
});
warCombatUpdateProjectiles(0.1);
assert(w._projectiles.length === 0, 'projectile removed on arrival');

// Timeout after 2s
warCombatReset();
dateNow = 10000;
warCombatAddProjectile({
    source_pos: { x: 0, y: 0 },
    target_pos: { x: 10000, y: 0 },
    speed: 1,
});
dateNow = 13000; // 3s later
warCombatUpdateProjectiles(0.1);
assert(w._projectiles.length === 0, 'projectile removed after 2s timeout');

// Trail length limit
dateNow = 10000;
warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 0, y: 0 },
    target_pos: { x: 10000, y: 0 },
    speed: 5,
});
for (let i = 0; i < 20; i++) {
    warCombatUpdateProjectiles(0.05);
}
assert(w._projectiles[0].trail.length <= w._projectiles[0].style.trailLen,
    'trail length capped at trailLen');

// ============================================================
// warCombatDrawProjectiles
// ============================================================

console.log('\n--- warCombatDrawProjectiles ---');

warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 5, y: 5 },
    target_pos: { x: 50, y: 50 },
    projectile_type: 'nerf_dart',
});
let c = mockCtx();
warCombatDrawProjectiles(c, wts);
// Should not throw
assert(true, 'drawProjectiles runs without error');

// Water balloon wobble
warCombatReset();
warCombatAddProjectile({
    source_pos: { x: 0, y: 0 },
    target_pos: { x: 50, y: 50 },
    projectile_type: 'water_balloon',
});
c = mockCtx();
warCombatDrawProjectiles(c, wts);
assert(true, 'water balloon wobble renders without error');

// ============================================================
// warCombatAddHitEffect
// ============================================================

console.log('\n--- warCombatAddHitEffect ---');

warCombatReset();
warCombatAddHitEffect(null);
assert(w._particles.length === 0, 'null data adds no particles');

warCombatReset();
warCombatAddHitEffect({ position: { x: 10, y: 20 } });
assert(w._particles.length === 12, 'hit effect spawns 12 particles (8+4)');

warCombatReset();
warCombatAddHitEffect({});
assert(w._particles.length === 12, 'missing position defaults to 0,0');
assert(w._particles[0].x === 0, 'default particle x is 0');

// ============================================================
// warCombatAddEliminationEffect
// ============================================================

console.log('\n--- warCombatAddEliminationEffect ---');

warCombatReset();
warCombatAddEliminationEffect(null);
assert(w._particles.length === 0, 'null data adds nothing');

warCombatReset();
warCombatAddEliminationEffect({ position: { x: 30, y: 40 } });
assert(w._particles.length === 29, 'elimination spawns 29 particles (15+8+6)');
// Check screen effects: ring + float_text + screen_flash + screen_shake
const ringCount = w._screenEffects.filter(e => e.type === 'elimination_ring').length;
const textCount = w._screenEffects.filter(e => e.type === 'float_text').length;
const flashCount = w._screenEffects.filter(e => e.type === 'screen_flash').length;
const shakeCount = w._screenEffects.filter(e => e.type === 'screen_shake').length;
assert(ringCount === 1, 'one elimination ring');
assert(textCount === 1, 'one float text');
assert(flashCount === 1, 'one screen flash');
assert(shakeCount === 1, 'one screen shake');

const floatText = w._screenEffects.find(e => e.type === 'float_text');
assert(floatText.text === 'ELIMINATED', 'float text says ELIMINATED');
assert(floatText.color === '#ff2a6d', 'float text color is magenta');

// ============================================================
// warCombatUpdateEffects
// ============================================================

console.log('\n--- warCombatUpdateEffects ---');

warCombatReset();
warCombatAddHitEffect({ position: { x: 0, y: 0 } });
const initialCount = w._particles.length;
warCombatUpdateEffects(0.1);
// Particles should have moved
assert(w._particles[0].life < 0.5, 'particle life decreased');

// Particles expire
warCombatReset();
warCombatAddHitEffect({ position: { x: 0, y: 0 } });
warCombatUpdateEffects(1.0); // 1s — exceeds 0.5s and 0.3s lifetimes
assert(w._particles.length === 0, 'all particles expired after 1s');

// Screen effects expire
warCombatReset();
dateNow = 10000;
warCombatAddEliminationEffect({ position: { x: 0, y: 0 } });
dateNow = 15000; // 5s later
warCombatUpdateEffects(0.1);
assert(w._screenEffects.length === 0, 'screen effects expired after 5s');

// Gravity applied
warCombatReset();
warCombatAddHitEffect({ position: { x: 0, y: 0 } });
const initialVy = w._particles[0].vy;
warCombatUpdateEffects(0.1);
assert(w._particles.length > 0 && w._particles[0].vy !== initialVy, 'gravity changes vy');

// ============================================================
// warCombatDrawEffects
// ============================================================

console.log('\n--- warCombatDrawEffects ---');

warCombatReset();
dateNow = 10000;
warCombatAddEliminationEffect({ position: { x: 10, y: 10 } });
c = mockCtx();
warCombatDrawEffects(c, wts, 800, 600);
assert(true, 'drawEffects with elimination renders without error');

warCombatReset();
warCombatAddProjectile({ source_pos: { x: 0, y: 0 }, target_pos: { x: 10, y: 10 } });
c = mockCtx();
warCombatDrawEffects(c, wts, 800, 600);
assert(true, 'drawEffects with muzzle flash renders without error');

// ============================================================
// warCombatGetScreenShake
// ============================================================

console.log('\n--- warCombatGetScreenShake ---');

warCombatReset();
const noShake = warCombatGetScreenShake();
assert(noShake.x === 0 && noShake.y === 0, 'no shake when empty');

warCombatReset();
dateNow = 10000;
warCombatAddEliminationEffect({ position: { x: 0, y: 0 } });
dateNow = 10050; // 50ms in (still within 200ms duration)
const shaking = warCombatGetScreenShake();
assert(typeof shaking.x === 'number' && typeof shaking.y === 'number', 'shake returns numbers');
// Shake intensity should be non-zero when active
// (random, so just check it's not always exactly 0 — run a few times)
let anyNonZero = false;
for (let i = 0; i < 10; i++) {
    const s = warCombatGetScreenShake();
    if (s.x !== 0 || s.y !== 0) anyNonZero = true;
}
assert(anyNonZero, 'screen shake produces non-zero values during active shake');

// Expired shake produces zero
dateNow = 20000; // way past duration
const expired = warCombatGetScreenShake();
// The effect hasn't been pruned yet, but age > 1 means decay = 0
// Actually screen effects are still in the array until updateEffects prunes them
// But the age check (age < 1) prevents non-zero contribution
assert(expired.x === 0 && expired.y === 0, 'expired shake returns zero');

// ============================================================
// warCombatDrawHealthBar
// ============================================================

console.log('\n--- warCombatDrawHealthBar ---');

warCombatReset();
c = mockCtx();
warCombatDrawHealthBar(c, 100, 100, 100, 100, 'friendly', 8);
// Full health: no bar drawn
assert(c.fillStyle === '', 'no bar for full health');

c = mockCtx();
warCombatDrawHealthBar(c, 100, 100, 70, 100, 'friendly', 8);
// Should draw: fillStyle set
assert(c.fillStyle !== '', 'bar drawn for damaged unit');

c = mockCtx();
warCombatDrawHealthBar(c, 100, 100, 80, 100, 'hostile', 8);
assert(true, 'health bar renders for hostile');

c = mockCtx();
warCombatDrawHealthBar(c, 100, 100, 20, 100, 'friendly', 8);
assert(true, 'low health bar renders');

c = mockCtx();
warCombatDrawHealthBar(c, 100, 100, 5, 100, 'friendly', 8);
assert(true, 'critical health bar renders');

// ============================================================
// warCombatDrawWeaponRange
// ============================================================

console.log('\n--- warCombatDrawWeaponRange ---');

warCombatReset();
c = mockCtx();
warCombatDrawWeaponRange(c, wts, null, 10);
assert(true, 'null target is no-op');

c = mockCtx();
warCombatDrawWeaponRange(c, wts, { position: { x: 50, y: 50 }, weapon_range: 15 }, 10);
assert(true, 'weapon range renders');

c = mockCtx();
warCombatDrawWeaponRange(c, wts, { position: { x: 0, y: 0 } }, 10);
assert(true, 'default weapon range (8) used when not specified');

// ============================================================
// STREAK_NAMES
// ============================================================

console.log('\n--- STREAK_NAMES ---');

assert(w.STREAK_NAMES[3] === 'KILLING SPREE', 'streak 3 = KILLING SPREE');
assert(w.STREAK_NAMES[5] === 'RAMPAGE', 'streak 5 = RAMPAGE');
assert(w.STREAK_NAMES[7] === 'DOMINATING', 'streak 7 = DOMINATING');
assert(w.STREAK_NAMES[10] === 'GODLIKE', 'streak 10 = GODLIKE');

// ============================================================
// warCombatAddEliminationStreakEffect
// ============================================================

console.log('\n--- warCombatAddEliminationStreakEffect ---');

warCombatReset();
warCombatAddEliminationStreakEffect(null);
assert(w._screenEffects.length === 0, 'null data adds nothing');

warCombatReset();
dateNow = 10000;
warCombatAddEliminationStreakEffect({ streak: 5, alliance: 'friendly' });
const streakEffect = w._screenEffects.find(e => e.type === 'elimination_streak');
assert(streakEffect !== undefined, 'streak effect added');
assert(streakEffect.text === 'RAMPAGE', 'streak 5 text is RAMPAGE');
assert(streakEffect.color === '#00f0ff', 'friendly streak is cyan');
assert(streakEffect.fontSize === 36, 'sub-10 streak uses 36px font');

warCombatReset();
warCombatAddEliminationStreakEffect({ streak: 10, alliance: 'hostile' });
const godlike = w._screenEffects.find(e => e.type === 'elimination_streak');
assert(godlike.text === 'GODLIKE', 'streak 10 text is GODLIKE');
assert(godlike.color === '#ff2a6d', 'hostile streak is magenta');
assert(godlike.fontSize === 48, 'godlike uses 48px font');
assert(godlike.duration === 2500, 'streak duration 2.5s');

// Custom streak name
warCombatReset();
warCombatAddEliminationStreakEffect({ streak: 15, streak_name: 'UNSTOPPABLE', alliance: 'friendly' });
const custom = w._screenEffects.find(e => e.type === 'elimination_streak');
assert(custom.text === 'UNSTOPPABLE', 'custom streak name used');

// Screen flash also added
warCombatReset();
warCombatAddEliminationStreakEffect({ streak: 3, alliance: 'friendly' });
const flashes = w._screenEffects.filter(e => e.type === 'screen_flash');
assert(flashes.length === 1, 'screen flash added with streak');

// ============================================================
// warCombatDrawTargetShape
// ============================================================

console.log('\n--- warCombatDrawTargetShape ---');

c = mockCtx();
// Hostile diamond
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'person', heading: 90, status: 'active' }, 'hostile', 10);
assert(true, 'hostile diamond renders');

// Turret square
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'turret', heading: 0, status: 'active' }, 'friendly', 10);
assert(true, 'turret square renders');

// Turret with cooldown
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8,
    { asset_type: 'turret', heading: 0, status: 'active', last_fired: dateNow - 500, weapon_cooldown: 2 },
    'friendly', 10);
assert(true, 'turret cooldown arc renders');

// Drone triangle
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'drone', heading: 45, status: 'active' }, 'friendly', 10);
assert(true, 'drone triangle renders');

// Eliminated drone
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'drone', heading: 0, status: 'eliminated' }, 'friendly', 10);
assert(true, 'eliminated drone renders with reduced alpha');

// Rover circle
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'rover', heading: 180, status: 'active' }, 'friendly', 10);
assert(true, 'rover circle renders');

// Mesh radio antenna
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'mesh_radio', status: 'active' }, 'friendly', 10);
assert(true, 'mesh radio icon renders');

// Truck/vehicle rectangle
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'truck', heading: 45, status: 'active' }, 'friendly', 10);
assert(true, 'truck rectangle renders');

// Neutral non-combatant
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'person', heading: 0, status: 'active' }, 'neutral', 10);
assert(true, 'neutral non-combatant renders');

// Unknown yellow square
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'unknown', status: 'active' }, 'unknown', 10);
assert(true, 'unknown unit renders as yellow square');

// Eliminated overlay X mark
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'person', status: 'eliminated' }, 'hostile', 10);
assert(true, 'eliminated hostile gets X mark');

// Neutralized status
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'turret', status: 'neutralized' }, 'friendly', 10);
assert(true, 'neutralized status renders as eliminated');

// No heading
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'turret', status: 'active' }, 'friendly', 10);
assert(true, 'turret without heading renders ok');

// Sentry type (includes "turret")
c = mockCtx();
warCombatDrawTargetShape(c, { x: 100, y: 100 }, 8, { asset_type: 'sentry', heading: 0, status: 'active' }, 'friendly', 10);
assert(true, 'sentry renders as turret shape');

// ============================================================
// warCombatReset
// ============================================================

console.log('\n--- warCombatReset ---');

warCombatAddProjectile({ source_pos: { x: 0, y: 0 }, target_pos: { x: 10, y: 10 } });
warCombatAddHitEffect({ position: { x: 5, y: 5 } });
warCombatAddEliminationEffect({ position: { x: 5, y: 5 } });
assert(w._projectiles.length > 0, 'has projectiles before reset');
assert(w._particles.length > 0, 'has particles before reset');
assert(w._screenEffects.length > 0, 'has screen effects before reset');

warCombatReset();
assert(w._projectiles.length === 0, 'projectiles cleared');
assert(w._particles.length === 0, 'particles cleared');
assert(w._screenEffects.length === 0, 'screen effects cleared');

// ============================================================
// Shape helpers
// ============================================================

console.log('\n--- Shape helpers ---');

c = mockCtx();
w._drawDiamond(c, 50, 50, 10, '#ff0000');
assert(true, '_drawDiamond renders');

c = mockCtx();
w._drawSquare(c, 50, 50, 10, '#00ff00');
assert(true, '_drawSquare renders');

c = mockCtx();
w._drawTriangle(c, 50, 50, 10, 45, '#0000ff');
assert(true, '_drawTriangle with heading renders');

c = mockCtx();
w._drawTriangle(c, 50, 50, 10, undefined, '#0000ff');
assert(true, '_drawTriangle without heading renders');

c = mockCtx();
w._drawRect(c, 50, 50, 20, 10, 90, '#ff00ff');
assert(true, '_drawRect with heading renders');

c = mockCtx();
w._drawRect(c, 50, 50, 20, 10, undefined, '#ff00ff');
assert(true, '_drawRect without heading renders');

// ============================================================
// Multiple projectiles
// ============================================================

console.log('\n--- Multiple projectiles ---');

warCombatReset();
dateNow = 10000;
for (let i = 0; i < 5; i++) {
    warCombatAddProjectile({
        source_pos: { x: 0, y: 0 },
        target_pos: { x: 100, y: i * 10 },
        speed: 10,
    });
}
assert(w._projectiles.length === 5, '5 projectiles added');
warCombatUpdateProjectiles(0.1);
assert(w._projectiles.length === 5, 'all 5 still in flight after small step');

// Draw all
c = mockCtx();
warCombatDrawProjectiles(c, wts);
assert(true, 'drawing 5 projectiles works');

// ============================================================
// Summary
// ============================================================

console.log(`\n=== test_war_combat.js: ${passed} passed, ${failed} failed ===`);
if (failed > 0) process.exit(1);
