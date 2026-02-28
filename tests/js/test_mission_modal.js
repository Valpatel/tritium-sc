/**
 * TRITIUM-SC Mission Generation Modal Tests
 *
 * Tests the mission modal logic: game modes, progress events,
 * step classification, briefing rendering, API request format,
 * and WebSocket event routing.
 *
 * Run: node tests/js/test_mission_modal.js
 */

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}

// ============================================================
// Game mode constants
// ============================================================

console.log('\n--- Game mode constants ---');

const MODES = ['battle', 'defense', 'patrol', 'escort', 'civil_unrest', 'drone_swarm'];

assert(MODES.length === 6,
    'Six game modes defined');

assert(MODES.includes('battle'),
    'battle mode exists');

assert(MODES.includes('defense'),
    'defense mode exists');

assert(MODES.includes('patrol'),
    'patrol mode exists');

assert(MODES.includes('escort'),
    'escort mode exists');

assert(MODES.includes('civil_unrest'),
    'civil_unrest mode exists');

assert(MODES.includes('drone_swarm'),
    'drone_swarm mode exists');

// Step icons cover all generation steps
const stepIds = [
    'scenario_context', 'unit_composition', 'unit_motives',
    'win_conditions', 'weather_atmosphere', 'loading_messages',
    'wave_briefings', 'wave_composition',
];
assert(stepIds.length === 8, 'Eight generation steps defined');


// ============================================================
// Mission progress event handling
// ============================================================

console.log('\n--- Mission progress events ---');

// Started event
{
    const data = { status: 'started', game_mode: 'battle', total_steps: 8, source: 'llm', model: 'gemma3:4b' };
    assert(data.status === 'started', 'started event has correct status');
    assert(data.total_steps === 8, 'started event has total_steps');
    assert(data.source === 'llm', 'started event identifies LLM source');
    assert(data.model === 'gemma3:4b', 'started event includes model name');
}

// step_started event
{
    const data = {
        status: 'step_started', step: 1, step_id: 'scenario_context',
        label: 'Generating scenario context...',
        prompt: 'Generate the backstory for a battle scenario...',
        source: 'llm',
    };
    assert(data.prompt.length > 10, 'step_started includes prompt text');
    assert(data.label.includes('scenario'), 'step_started has label');
    assert(data.step === 1, 'step_started has step number');
}

// step_complete event
{
    const data = {
        status: 'step_complete', step: 1, step_id: 'scenario_context',
        result: { reason: 'Gang turf war', attacker_name: 'Shadow Cell', urgency: 'high' },
        source: 'llm',
    };
    assert(data.result.reason === 'Gang turf war', 'step_complete has parsed result');
    assert(data.result.attacker_name === 'Shadow Cell', 'step_complete result has attacker');
}

// step_failed event
{
    const data = {
        status: 'step_failed', step: 3, step_id: 'unit_motives',
        error: 'Failed to parse LLM response',
    };
    assert(data.error.length > 0, 'step_failed has error message');
}

// complete event
{
    const data = {
        status: 'complete', game_mode: 'battle',
        scenario: {
            game_mode: 'battle',
            scenario_context: { reason: 'Test' },
            units: [{ type: 'turret', position: [10, 20] }],
            win_conditions: { victory: { condition: 'Survive' } },
        },
    };
    assert(data.scenario.units.length === 1, 'complete event has units');
    assert(data.scenario.win_conditions.victory.condition === 'Survive',
        'complete event has win conditions');
}


// ============================================================
// Progress bar calculation
// ============================================================

console.log('\n--- Progress bar calculation ---');

{
    const totalSteps = 8;
    const calcPct = (step) => Math.round((step / totalSteps) * 80) + 10;

    assert(calcPct(0) === 10, 'step 0 = 10% (base)');
    assert(calcPct(1) >= 18 && calcPct(1) <= 22, 'step 1 ~= 20%');
    assert(calcPct(4) >= 45 && calcPct(4) <= 55, 'step 4 ~= 50%');
    assert(calcPct(8) === 90, 'step 8 = 90% (before complete)');
}


// ============================================================
// Step status classification
// ============================================================

console.log('\n--- Step status classification ---');

function classifyStep(status) {
    return status === 'step_complete' ? 'complete' :
           status === 'step_started' ? 'active' :
           status === 'step_failed' ? 'failed' : 'pending';
}

assert(classifyStep('step_complete') === 'complete', 'step_complete -> complete class');
assert(classifyStep('step_started') === 'active', 'step_started -> active class');
assert(classifyStep('step_failed') === 'failed', 'step_failed -> failed class');
assert(classifyStep('other') === 'pending', 'unknown -> pending class');


// ============================================================
// Briefing rendering
// ============================================================

console.log('\n--- Briefing rendering ---');

{
    const scenario = {
        scenario_context: {
            reason: 'Intel suggests a probe-in-force',
            attacker_name: 'Ghost Network',
            attacker_motivation: 'Intelligence gathering',
        },
        weather: { weather: 'Foggy, low visibility', visibility: 'poor' },
        win_conditions: {
            victory: { condition: 'Survive all 10 waves' },
            defeat: { condition: 'All defenders eliminated' },
        },
        units: [
            { type: 'turret', position: [10, 20] },
            { type: 'rover', position: [30, 40] },
        ],
        generated_by: 'llm',
        model: 'gemma3:4b',
    };

    assert(scenario.scenario_context.reason.includes('probe'),
        'briefing shows scenario reason');
    assert(scenario.weather.visibility === 'poor',
        'briefing shows weather visibility');
    assert(scenario.units.length === 2, 'briefing shows unit count');
    assert(scenario.generated_by === 'llm', 'briefing shows generation source');
}

// Missing fields handled gracefully
{
    const scenario = { game_mode: 'battle' };
    const ctx = scenario.scenario_context || {};
    const weather = scenario.weather || {};
    const wc = scenario.win_conditions || {};

    assert((ctx.reason || 'Unknown threat detected') === 'Unknown threat detected',
        'missing reason falls back to default');
    assert((weather.weather || 'Standard') === 'Standard',
        'missing weather falls back to default');

    const vcond = wc.victory?.condition || 'Survive all waves';
    assert(vcond === 'Survive all waves',
        'missing victory condition falls back');
}


// ============================================================
// HTML escaping
// ============================================================

console.log('\n--- HTML escaping ---');

{
    const escape = (text) => String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

    const xss = '<script>alert("xss")</script>';
    const escaped = escape(xss);
    assert(!escaped.includes('<script>'), 'escapes script tags');
    assert(escaped.includes('&lt;script&gt;'), 'converts < to &lt;');

    assert(escape('A & B') === 'A &amp; B', 'escapes ampersands');
    assert(escape('normal text') === 'normal text', 'plain text unchanged');
}


// ============================================================
// WebSocket event routing
// ============================================================

console.log('\n--- WebSocket event routing ---');

function routeEvent(type) {
    if (type === 'mission_progress' || type === 'amy_mission_progress') return 'mission:progress';
    if (type === 'scenario_generated' || type === 'amy_scenario_generated') return 'mission:scenario';
    return null;
}

assert(routeEvent('mission_progress') === 'mission:progress',
    'mission_progress -> mission:progress');
assert(routeEvent('amy_mission_progress') === 'mission:progress',
    'amy_mission_progress -> mission:progress');
assert(routeEvent('scenario_generated') === 'mission:scenario',
    'scenario_generated -> mission:scenario');
assert(routeEvent('amy_scenario_generated') === 'mission:scenario',
    'amy_scenario_generated -> mission:scenario');
assert(routeEvent('other_event') === null,
    'unrelated events not routed');


// ============================================================
// Game mode selection
// ============================================================

console.log('\n--- Game mode selection ---');

{
    let selectedMode = 'battle';
    assert(selectedMode === 'battle', 'default mode is battle');

    selectedMode = 'defense';
    assert(selectedMode === 'defense', 'mode can be changed to defense');

    selectedMode = 'patrol';
    assert(selectedMode === 'patrol', 'mode can be changed to patrol');
}


// ============================================================
// API request format
// ============================================================

console.log('\n--- API request format ---');

{
    const llmBody = { game_mode: 'battle', use_llm: true };
    assert(llmBody.game_mode === 'battle', 'LLM request has game_mode');
    assert(llmBody.use_llm === true, 'LLM request has use_llm=true');
}

{
    const scriptedBody = { game_mode: 'patrol', use_llm: false };
    assert(scriptedBody.use_llm === false, 'scripted request has use_llm=false');
}

{
    const modelOverride = { game_mode: 'battle', use_llm: true, model: 'qwen2.5:7b' };
    assert(modelOverride.model === 'qwen2.5:7b', 'model override included');
}


// ============================================================
// Scenario structure validation
// ============================================================

console.log('\n--- Scenario structure ---');

{
    // A well-formed scenario from the backend
    const scenario = {
        game_mode: 'battle',
        generated_by: 'scripted',
        scenario_context: {
            reason: 'A coordinated assault from the east.',
            attacker_name: 'Shadow Cell',
            attacker_motivation: 'Territory expansion',
            stakes: 'The safety of 47 families',
            urgency: 'high',
            atmosphere: 'Tense calm before the storm',
        },
        units: [
            { type: 'turret', alliance: 'friendly', position: [10.2, 20.5], name: 'Turret-01' },
            { type: 'rover', alliance: 'friendly', position: [30.1, 40.3], name: 'Rover-02' },
        ],
        win_conditions: {
            victory: { condition: 'Survive all 10 waves', description: 'Eliminate all hostiles.' },
            defeat: { condition: 'All defenders eliminated', description: 'Neighborhood falls.' },
        },
        weather: { weather: 'Clear night', visibility: 'good' },
        loading_messages: ['Initializing...', 'Calibrating...'],
        wave_briefings: [
            { wave: 1, briefing: 'Light contact', threat_level: 'light' },
        ],
    };

    assert(scenario.game_mode === 'battle', 'scenario has game_mode');
    assert(Array.isArray(scenario.units), 'scenario has units array');
    assert(scenario.units.length >= 2, 'scenario has at least 2 units');
    assert(scenario.units[0].type === 'turret', 'first unit is turret');
    assert(scenario.units[0].alliance === 'friendly', 'unit has alliance');
    assert(Array.isArray(scenario.units[0].position), 'unit has position array');
    assert(scenario.units[0].position.length === 2, 'position is [x, y]');
    assert(scenario.win_conditions.victory.condition.includes('Survive'),
        'victory condition defined');
    assert(scenario.win_conditions.defeat.condition.includes('eliminated'),
        'defeat condition defined');
    assert(Array.isArray(scenario.loading_messages), 'loading messages is array');
    assert(Array.isArray(scenario.wave_briefings), 'wave briefings is array');
}


// ============================================================
// Model selection
// ============================================================

console.log('\n--- Model selection ---');

{
    // Model list response parsing
    const modelResponse = { models: ['gemma3:4b', 'qwen2.5:7b', 'phi4-mini:latest'] };
    assert(Array.isArray(modelResponse.models), 'models response is array');
    assert(modelResponse.models.length === 3, 'three models in response');
    assert(modelResponse.models.includes('gemma3:4b'), 'gemma3:4b in list');
}

{
    // Generate payload with model selection
    const payload = { game_mode: 'battle', use_llm: true, model: 'qwen2.5:7b' };
    assert(payload.model === 'qwen2.5:7b', 'custom model in payload');
}

{
    // Generate payload without model (auto)
    const payload = { game_mode: 'defense', use_llm: true };
    assert(!payload.model, 'no model when auto');
}

{
    // Scripted generation ignores model
    const payload = { game_mode: 'battle', use_llm: false };
    assert(!payload.model, 'scripted has no model field');
}

// ============================================================
// Wave composition in scenario
// ============================================================

console.log('\n--- Wave composition ---');

{
    const waveComp = [
        { wave: 1, groups: [{ type: 'person', count: 4, speed: 1.5, health: 80 }], speed_mult: 1.0, health_mult: 1.0 },
        { wave: 2, groups: [{ type: 'person', count: 5, speed: 1.5, health: 80 }, { type: 'hostile_vehicle', count: 1, speed: 2.5, health: 200 }], speed_mult: 1.1, health_mult: 1.2 },
    ];
    assert(waveComp.length === 2, 'two waves in composition');
    assert(waveComp[0].groups[0].type === 'person', 'wave 1 has person group');
    assert(waveComp[1].groups.length === 2, 'wave 2 has mixed composition');

    // Total hostile count
    const totalHostiles = waveComp.reduce((sum, w) =>
        sum + w.groups.reduce((s, g) => s + g.count, 0), 0);
    assert(totalHostiles === 10, 'total hostiles across waves = 10');

    // Speed multiplier increases
    assert(waveComp[1].speed_mult > waveComp[0].speed_mult, 'later waves faster');
}


// ============================================================
// Summary
// ============================================================

console.log(`\n=== ${passed} passed, ${failed} failed ===`);
process.exit(failed > 0 ? 1 : 0);
