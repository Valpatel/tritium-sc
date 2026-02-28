/**
 * Mission Generation Modal — shows LLM scenario generation progress.
 *
 * When the operator initiates a new game, this modal appears showing:
 * - Game mode selection
 * - LLM generation progress (prompts sent, responses received)
 * - Unit placement visualization
 * - Scenario briefing before countdown
 *
 * Events consumed (via WebSocket):
 *   mission_progress: {status, step, label, result, prompt, ...}
 *
 * Exports:
 *   MissionModal — modal controller
 *   initMissionModal() — setup function
 */

// -- Constants -----------------------------------------------------------------

const GAME_MODES = {
    battle: { label: 'BATTLE', description: '10-wave combat defense', icon: 'B' },
    defense: { label: 'DEFENSE', description: 'Hold position against assault', icon: 'D' },
    patrol: { label: 'PATROL', description: 'Patrol and secure perimeter', icon: 'P' },
    escort: { label: 'ESCORT', description: 'Escort VIP through hostile territory', icon: 'E' },
    civil_unrest: { label: 'CIVIL UNREST', description: 'Riots and crowd control scenario', icon: 'U' },
    drone_swarm: { label: 'DRONE SWARM', description: 'Mass drone attack defense', icon: 'S' },
};

const STEP_ICONS = {
    scenario_context: '\u25C8',     // diamond
    unit_composition: '\u25A0',     // square
    unit_motives: '\u25B6',         // play
    win_conditions: '\u2605',       // star
    weather_atmosphere: '\u2602',   // umbrella
    loading_messages: '\u25CB',     // circle
    wave_briefings: '\u25B2',       // triangle
    wave_composition: '\u2693',     // anchor
};


// -- State ---------------------------------------------------------------------

let _overlay = null;
let _panel = null;
let _stepsContainer = null;
let _briefingContainer = null;
let _statusLabel = null;
let _progressBar = null;
let _selectedMode = 'battle';
let _selectedModel = '';  // empty = auto
let _isGenerating = false;
let _scenario = null;
let _totalSteps = 8;


// -- DOM Creation --------------------------------------------------------------

function _createModal() {
    if (document.getElementById('mission-modal-overlay')) {
        _overlay = document.getElementById('mission-modal-overlay');
        _panel = _overlay.querySelector('.mission-modal-panel');
        _stepsContainer = _overlay.querySelector('.mission-steps');
        _briefingContainer = _overlay.querySelector('.mission-briefing');
        _statusLabel = _overlay.querySelector('.mission-status');
        _progressBar = _overlay.querySelector('.mission-progress-fill');
        return;
    }

    _overlay = document.createElement('div');
    _overlay.id = 'mission-modal-overlay';
    _overlay.className = 'mission-modal-overlay';
    _overlay.hidden = true;

    _overlay.innerHTML = `
        <div class="mission-modal-panel corner-marks">
            <div class="mission-modal-header">
                <div class="mission-modal-title mono">MISSION INITIALIZATION</div>
                <div class="mission-status mono">SELECT GAME MODE</div>
            </div>

            <div class="mission-mode-select" data-section="mode-select">
                ${Object.entries(GAME_MODES).map(([id, mode]) => `
                    <button class="mission-mode-btn mono ${id === 'battle' ? 'active' : ''}"
                            data-mode="${id}">
                        <span class="mode-icon">${mode.icon}</span>
                        <span class="mode-label">${mode.label}</span>
                        <span class="mode-desc">${mode.description}</span>
                    </button>
                `).join('')}
            </div>

            <div class="mission-model-select" data-section="model-select">
                <div class="model-select-label mono">AI MODEL</div>
                <select class="mission-model-dropdown mono" data-field="model">
                    <option value="">Auto (recommended)</option>
                </select>
                <div class="model-recommendation mono" data-field="recommendation"></div>
            </div>

            <div class="mission-progress-bar">
                <div class="mission-progress-fill" style="width: 0%"></div>
            </div>

            <div class="mission-steps" data-section="steps"></div>

            <div class="mission-briefing" data-section="briefing" hidden></div>

            <div class="mission-actions">
                <button class="game-btn mono mission-btn-generate" data-action="generate">
                    [ GENERATE SCENARIO ]
                </button>
                <button class="game-btn mono mission-btn-scripted" data-action="scripted">
                    [ QUICK START ]
                </button>
                <button class="game-btn mono mission-btn-launch" data-action="launch" hidden>
                    [ LAUNCH MISSION ]
                </button>
                <button class="game-btn mono mission-btn-cancel" data-action="cancel">
                    [ CANCEL ]
                </button>
            </div>
        </div>
    `;

    document.body.appendChild(_overlay);

    // Cache refs
    _panel = _overlay.querySelector('.mission-modal-panel');
    _stepsContainer = _overlay.querySelector('.mission-steps');
    _briefingContainer = _overlay.querySelector('.mission-briefing');
    _statusLabel = _overlay.querySelector('.mission-status');
    _progressBar = _overlay.querySelector('.mission-progress-fill');

    // Event handlers
    _overlay.querySelectorAll('.mission-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (_isGenerating) return;
            _overlay.querySelectorAll('.mission-mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            _selectedMode = btn.dataset.mode;
        });
    });

    _overlay.querySelector('[data-action="generate"]').addEventListener('click', () => {
        if (!_isGenerating) _startGeneration(true);
    });

    _overlay.querySelector('[data-action="scripted"]').addEventListener('click', () => {
        if (!_isGenerating) _startGeneration(false);
    });

    _overlay.querySelector('[data-action="launch"]').addEventListener('click', () => {
        _launchMission();
    });

    _overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => {
        hide();
    });

    // Model selector
    const modelDropdown = _overlay.querySelector('[data-field="model"]');
    if (modelDropdown) {
        modelDropdown.addEventListener('change', (e) => {
            _selectedModel = e.target.value;
        });
    }

    // Load available models
    _loadModels();
}


// -- Model Loading -------------------------------------------------------------

async function _loadModels() {
    try {
        const resp = await fetch('/api/game/models');
        const data = await resp.json();
        const dropdown = _overlay?.querySelector('[data-field="model"]');
        const recEl = _overlay?.querySelector('[data-field="recommendation"]');
        if (!dropdown) return;

        const models = data.models || [];
        // Keep the "Auto" option, add discovered models
        models.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            dropdown.appendChild(opt);
        });

        if (recEl) {
            recEl.textContent = models.length > 0
                ? `${models.length} models available`
                : 'No Ollama models detected';
        }
    } catch {
        const recEl = _overlay?.querySelector('[data-field="recommendation"]');
        if (recEl) recEl.textContent = 'Ollama offline — scripted only';
    }
}


// -- Generation Flow -----------------------------------------------------------

async function _startGeneration(useLLM) {
    _isGenerating = true;
    _stepsContainer.innerHTML = '';
    _briefingContainer.hidden = true;
    _progressBar.style.width = '0%';
    _statusLabel.textContent = useLLM ? 'CONNECTING TO LLM...' : 'GENERATING SCENARIO...';

    // Hide mode select, show progress
    const modeSelect = _overlay.querySelector('[data-section="mode-select"]');
    if (modeSelect) modeSelect.hidden = true;

    // Hide generate/scripted buttons, show cancel only
    _overlay.querySelector('[data-action="generate"]').hidden = true;
    _overlay.querySelector('[data-action="scripted"]').hidden = true;
    _overlay.querySelector('[data-action="launch"]').hidden = true;

    // Also hide model select during generation
    const modelSelect = _overlay.querySelector('[data-section="model-select"]');
    if (modelSelect) modelSelect.hidden = true;

    try {
        const payload = {
            game_mode: _selectedMode,
            use_llm: useLLM,
        };
        if (useLLM && _selectedModel) {
            payload.model = _selectedModel;
        }

        const resp = await fetch('/api/game/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await resp.json();

        if (data.status === 'complete') {
            // Scripted generation returned immediately
            _scenario = data.scenario;
            _onGenerationComplete(data.scenario);
        }
        // For LLM generation, progress comes via WebSocket events
    } catch (e) {
        _statusLabel.textContent = 'GENERATION FAILED';
        _isGenerating = false;
        _resetButtons();
    }
}


function _addStep(stepData) {
    const stepEl = document.createElement('div');
    stepEl.className = 'mission-step';
    stepEl.dataset.stepId = stepData.step_id || '';

    const icon = STEP_ICONS[stepData.step_id] || '\u25CF';
    const status = stepData.status === 'step_complete' ? 'complete' :
                   stepData.status === 'step_started' ? 'active' :
                   stepData.status === 'step_failed' ? 'failed' : 'pending';

    stepEl.classList.add(`step-${status}`);

    let resultHtml = '';
    if (stepData.result && typeof stepData.result === 'object') {
        const preview = JSON.stringify(stepData.result, null, 1).substring(0, 200);
        resultHtml = `<div class="step-result mono">${_escapeHtml(preview)}</div>`;
    }

    let promptHtml = '';
    if (stepData.prompt) {
        const truncated = stepData.prompt.substring(0, 150);
        promptHtml = `<div class="step-prompt mono">${_escapeHtml(truncated)}...</div>`;
    }

    stepEl.innerHTML = `
        <div class="step-header">
            <span class="step-icon">${icon}</span>
            <span class="step-label">${stepData.label || stepData.step_id || 'Processing'}</span>
            <span class="step-status-indicator ${status}"></span>
        </div>
        ${promptHtml}
        ${resultHtml}
    `;

    // Replace existing step with same ID or append
    const existing = _stepsContainer.querySelector(`[data-step-id="${stepData.step_id}"]`);
    if (existing) {
        existing.replaceWith(stepEl);
    } else {
        _stepsContainer.appendChild(stepEl);
    }

    // Auto-scroll
    _stepsContainer.scrollTop = _stepsContainer.scrollHeight;
}


function _onGenerationComplete(scenario) {
    _isGenerating = false;
    _scenario = scenario;
    _progressBar.style.width = '100%';
    _statusLabel.textContent = 'SCENARIO READY';

    // Show briefing
    _briefingContainer.hidden = false;
    const ctx = scenario.scenario_context || {};
    const weather = scenario.weather || {};
    const wc = scenario.win_conditions || {};

    // Build wave summary
    const waveComp = scenario.wave_composition || [];
    let waveSummaryHtml = '';
    if (waveComp.length > 0) {
        const totalHostiles = waveComp.reduce((sum, w) =>
            sum + (w.groups || []).reduce((s, g) => s + (g.count || 0), 0), 0);
        const waveLines = waveComp.slice(0, 5).map(w => {
            const types = (w.groups || []).map(g =>
                `${g.count} ${g.type || 'person'}`).join(', ');
            return `<div class="wave-line mono">W${w.wave}: ${types}</div>`;
        }).join('');
        const moreWaves = waveComp.length > 5
            ? `<div class="wave-line mono">... +${waveComp.length - 5} more waves</div>` : '';
        waveSummaryHtml = `
            <div class="briefing-section">
                <div class="briefing-label mono">THREAT ANALYSIS</div>
                <div class="briefing-text">${waveComp.length} waves / ${totalHostiles} total hostiles</div>
                <div class="wave-breakdown">${waveLines}${moreWaves}</div>
            </div>
        `;
    }

    // Build bonus objectives
    const bonuses = wc.bonus_objectives || [];
    let bonusHtml = '';
    if (bonuses.length > 0) {
        bonusHtml = bonuses.map(b =>
            `<div class="bonus-line mono">+ ${_escapeHtml(b.name)} (${b.reward} pts)</div>`
        ).join('');
        bonusHtml = `
            <div class="briefing-section">
                <div class="briefing-label mono">BONUS OBJECTIVES</div>
                ${bonusHtml}
            </div>
        `;
    }

    _briefingContainer.innerHTML = `
        <div class="briefing-title mono">MISSION BRIEFING</div>
        <div class="briefing-section">
            <div class="briefing-label mono">SITUATION</div>
            <div class="briefing-text">${_escapeHtml(ctx.reason || 'Unknown threat detected')}</div>
            <div class="briefing-sub mono">Stakes: ${_escapeHtml(ctx.stakes || 'Unknown')}</div>
        </div>
        <div class="briefing-section">
            <div class="briefing-label mono">HOSTILE FORCE</div>
            <div class="briefing-text">${_escapeHtml(ctx.attacker_name || 'Unknown')} — ${_escapeHtml(ctx.attacker_motivation || 'Unknown motives')}</div>
            <div class="briefing-sub mono">Urgency: ${_escapeHtml(ctx.urgency || 'medium').toUpperCase()}</div>
        </div>
        <div class="briefing-section">
            <div class="briefing-label mono">CONDITIONS</div>
            <div class="briefing-text">${_escapeHtml(weather.weather || 'Standard')} / Visibility: ${_escapeHtml(weather.visibility || 'good')}</div>
            ${weather.mood_description ? `<div class="briefing-sub">${_escapeHtml(weather.mood_description)}</div>` : ''}
        </div>
        ${waveSummaryHtml}
        <div class="briefing-section">
            <div class="briefing-label mono">VICTORY CONDITION</div>
            <div class="briefing-text">${_escapeHtml(wc.victory?.condition || wc.victory?.description || 'Survive all waves')}</div>
        </div>
        ${bonusHtml}
        <div class="briefing-section">
            <div class="briefing-label mono">YOUR FORCES</div>
            <div class="briefing-text">${(scenario.units || []).length} units deployed</div>
            <div class="briefing-sub mono">${(scenario.units || []).map(u => u.type || u.name).join(', ')}</div>
        </div>
        <div class="briefing-source mono">Generated by: ${scenario.generated_by || 'scripted'}${scenario.model ? ` (${scenario.model})` : ''}</div>
    `;

    // Show launch button
    _overlay.querySelector('[data-action="launch"]').hidden = false;
    _overlay.querySelector('[data-action="cancel"]').hidden = false;
}


async function _launchMission() {
    _statusLabel.textContent = 'DEPLOYING FORCES...';
    _overlay.querySelector('[data-action="launch"]').hidden = true;

    // Pass loading messages to HUD for countdown display
    if (_scenario && _scenario.loading_messages && typeof warHudSetLoadingMessages === 'function') {
        warHudSetLoadingMessages(_scenario.loading_messages);
    }

    try {
        const resp = await fetch('/api/game/mission/apply', { method: 'POST' });
        const data = await resp.json();
        if (data.status === 'scenario_applied') {
            _statusLabel.textContent = 'MISSION LAUNCHED';
            setTimeout(() => hide(), 1500);
        } else {
            _statusLabel.textContent = 'DEPLOYMENT FAILED';
            _overlay.querySelector('[data-action="launch"]').hidden = false;
        }
    } catch (e) {
        _statusLabel.textContent = 'DEPLOYMENT FAILED';
        _overlay.querySelector('[data-action="launch"]').hidden = false;
    }
}


function _resetButtons() {
    const modeSelect = _overlay.querySelector('[data-section="mode-select"]');
    if (modeSelect) modeSelect.hidden = false;
    const modelSelect = _overlay.querySelector('[data-section="model-select"]');
    if (modelSelect) modelSelect.hidden = false;
    _overlay.querySelector('[data-action="generate"]').hidden = false;
    _overlay.querySelector('[data-action="scripted"]').hidden = false;
    _overlay.querySelector('[data-action="launch"]').hidden = true;
}


// -- WebSocket event handler ---------------------------------------------------

function handleMissionProgress(data) {
    if (!_overlay || _overlay.hidden) return;

    if (data.status === 'started') {
        _totalSteps = data.total_steps || 7;
        _statusLabel.textContent = data.source === 'llm'
            ? `LLM GENERATION (${data.model || 'gemma3:4b'})`
            : 'SCRIPTED GENERATION';
        _progressBar.style.width = '5%';
    }
    else if (data.status === 'step_started') {
        _statusLabel.textContent = data.label || 'Processing...';
        const pct = Math.round(((data.step || 0) / _totalSteps) * 80) + 10;
        _progressBar.style.width = `${pct}%`;
        _addStep(data);
    }
    else if (data.status === 'step_complete') {
        const pct = Math.round(((data.step || 0) / _totalSteps) * 80) + 10;
        _progressBar.style.width = `${pct}%`;
        _addStep(data);
    }
    else if (data.status === 'step_failed') {
        _addStep(data);
    }
    else if (data.status === 'complete') {
        _onGenerationComplete(data.scenario);
    }
}


// -- Public API ----------------------------------------------------------------

function show() {
    _createModal();
    _overlay.hidden = false;
    _isGenerating = false;
    _scenario = null;
    _stepsContainer.innerHTML = '';
    _briefingContainer.hidden = true;
    _progressBar.style.width = '0%';
    _statusLabel.textContent = 'SELECT GAME MODE';
    _resetButtons();
}

function hide() {
    if (_overlay) {
        _overlay.hidden = true;
        _isGenerating = false;
    }
}

function isVisible() {
    return _overlay && !_overlay.hidden;
}

function getScenario() {
    return _scenario;
}


// -- Escape utility ------------------------------------------------------------

function _escapeHtml(text) {
    const div = typeof document !== 'undefined' ? document.createElement('div') : null;
    if (div) {
        div.textContent = text;
        return div.innerHTML;
    }
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}


// -- Init ----------------------------------------------------------------------

function initMissionModal(eventBus) {
    _createModal();

    // Listen for WebSocket mission_progress events
    if (eventBus) {
        eventBus.on('mission:progress', (data) => {
            handleMissionProgress(data);
        });
    }
}


// -- Exports -------------------------------------------------------------------

export const MissionModal = {
    show,
    hide,
    isVisible,
    getScenario,
    handleMissionProgress,
};

export { initMissionModal };
export default MissionModal;
