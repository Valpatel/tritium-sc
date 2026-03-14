// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Keyboard Macro System — record and replay sequences of keyboard actions.
 *
 * Power user feature: record a sequence of actions (open panel, toggle layer,
 * set mode) and replay with a single key. Macros persist in localStorage.
 */

import { EventBus } from '../events.js';

const STORAGE_KEY = 'tritium_keyboard_macros';
const MAX_MACROS = 20;
const MAX_STEPS = 50;

// Macro state
const macroState = {
    recording: false,
    currentMacro: null,  // { name, trigger, steps: [{action, args, delay}] }
    macros: new Map(),   // trigger -> { name, trigger, steps }
    lastStepTime: 0,
    playingBack: false,
};

/**
 * Available macro actions and their executors.
 */
const MACRO_ACTIONS = {
    'panel.toggle': (args) => EventBus.emit('panel:toggle', args),
    'panel.open': (args) => EventBus.emit('panel:open', args),
    'panel.close': (args) => EventBus.emit('panel:close', args),
    'layer.toggle': (args) => EventBus.emit('layer:toggle', args),
    'mode.set': (args) => {
        const btn = document.querySelector(`[data-map-mode="${args.mode}"]`);
        if (btn) btn.click();
    },
    'map.zoom': (args) => {
        const map = window._tritiumMapInstance;
        if (map) map.setZoom(args.zoom || map.getZoom());
    },
    'map.center': (args) => {
        EventBus.emit('map:centerOnAction');
    },
    'map.autoFollow': () => {
        EventBus.emit('map:toggleAutoFollow');
    },
    'key.press': (args) => {
        // Simulate a keypress event
        document.dispatchEvent(new KeyboardEvent('keydown', {
            key: args.key,
            ctrlKey: args.ctrlKey || false,
            shiftKey: args.shiftKey || false,
            altKey: args.altKey || false,
        }));
    },
    'toast.show': (args) => {
        EventBus.emit('toast:show', { message: args.message || 'Macro step', type: 'info' });
    },
};

/**
 * Load macros from localStorage.
 */
function loadMacros() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const arr = JSON.parse(raw);
            macroState.macros.clear();
            for (const m of arr) {
                macroState.macros.set(m.trigger, m);
            }
        }
    } catch (e) {
        console.warn('[MACROS] Failed to load macros:', e);
    }
}

/**
 * Save macros to localStorage.
 */
function saveMacros() {
    try {
        const arr = Array.from(macroState.macros.values());
        localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
    } catch (e) {
        console.warn('[MACROS] Failed to save macros:', e);
    }
}

/**
 * Start recording a new macro.
 */
function startRecording(name, trigger) {
    if (macroState.recording) {
        stopRecording();
    }
    macroState.recording = true;
    macroState.currentMacro = {
        name: name || `Macro ${macroState.macros.size + 1}`,
        trigger: trigger || `F${macroState.macros.size + 1}`,
        steps: [],
    };
    macroState.lastStepTime = Date.now();
    EventBus.emit('toast:show', { message: `Recording macro "${name}"... Press Ctrl+Shift+M to stop`, type: 'warning' });
    EventBus.emit('macro:recording-started', { name, trigger });
}

/**
 * Add a step to the current recording.
 */
function recordStep(action, args = {}) {
    if (!macroState.recording || !macroState.currentMacro) return;
    if (macroState.currentMacro.steps.length >= MAX_STEPS) return;

    const now = Date.now();
    const delay = Math.min(now - macroState.lastStepTime, 5000); // cap at 5s
    macroState.lastStepTime = now;

    macroState.currentMacro.steps.push({ action, args, delay });
}

/**
 * Stop recording and save the macro.
 */
function stopRecording() {
    if (!macroState.recording || !macroState.currentMacro) return;

    macroState.recording = false;
    const macro = macroState.currentMacro;

    if (macro.steps.length > 0) {
        if (macroState.macros.size >= MAX_MACROS) {
            // Remove oldest
            const firstKey = macroState.macros.keys().next().value;
            macroState.macros.delete(firstKey);
        }
        macroState.macros.set(macro.trigger, macro);
        saveMacros();
        EventBus.emit('toast:show', {
            message: `Macro "${macro.name}" saved (${macro.steps.length} steps, trigger: ${macro.trigger})`,
            type: 'success',
        });
    } else {
        EventBus.emit('toast:show', { message: 'Macro recording cancelled (no steps)', type: 'info' });
    }

    macroState.currentMacro = null;
    EventBus.emit('macro:recording-stopped', { macro });
}

/**
 * Play back a macro by its trigger key.
 */
async function playMacro(trigger) {
    const macro = macroState.macros.get(trigger);
    if (!macro || macroState.playingBack) return false;

    macroState.playingBack = true;
    EventBus.emit('toast:show', { message: `Playing macro "${macro.name}"...`, type: 'info' });

    for (const step of macro.steps) {
        if (step.delay > 50) {
            await new Promise(r => setTimeout(r, step.delay));
        }
        const executor = MACRO_ACTIONS[step.action];
        if (executor) {
            try {
                executor(step.args);
            } catch (e) {
                console.warn('[MACROS] Step failed:', step.action, e);
            }
        }
    }

    macroState.playingBack = false;
    EventBus.emit('macro:playback-complete', { name: macro.name });
    return true;
}

/**
 * Delete a macro by trigger.
 */
function deleteMacro(trigger) {
    macroState.macros.delete(trigger);
    saveMacros();
}

/**
 * Get all macros as an array.
 */
function listMacros() {
    return Array.from(macroState.macros.values());
}

// Initialize on load
loadMacros();

// Listen for panel/layer events when recording
EventBus.on('panel:toggled', (data) => {
    if (macroState.recording) recordStep('panel.toggle', data);
});
EventBus.on('layer:toggled', (data) => {
    if (macroState.recording) recordStep('layer.toggle', data);
});
EventBus.on('map:modeChanged', (data) => {
    if (macroState.recording) recordStep('mode.set', data);
});

// Panel definition
export const KeyboardMacrosPanelDef = {
    id: 'keyboard-macros',
    title: 'KEYBOARD MACROS',
    icon: '\u{2328}',
    width: 360,
    height: 400,
    render(container) {
        const renderList = () => {
            const macros = listMacros();
            let html = `
                <div style="padding: 8px; font-family: 'JetBrains Mono', monospace; color: #c0c0d0;">
                    <div style="margin-bottom: 8px; display: flex; gap: 4px;">
                        <input id="macro-name-input" type="text" placeholder="Macro name"
                            style="flex: 1; padding: 6px; background: rgba(255,255,255,0.05);
                            border: 1px solid #333; color: #c0c0d0; font-family: inherit; font-size: 10px;" />
                        <input id="macro-trigger-input" type="text" placeholder="Key (e.g. F5)"
                            style="width: 60px; padding: 6px; background: rgba(255,255,255,0.05);
                            border: 1px solid #333; color: #c0c0d0; font-family: inherit; font-size: 10px;" />
                    </div>
                    <div style="display: flex; gap: 4px; margin-bottom: 12px;">
                        <button id="macro-record-btn" style="
                            flex: 1; padding: 6px;
                            background: ${macroState.recording ? 'rgba(255, 42, 109, 0.3)' : 'rgba(0, 240, 255, 0.1)'};
                            border: 1px solid ${macroState.recording ? '#ff2a6d' : '#00f0ff'};
                            color: ${macroState.recording ? '#ff2a6d' : '#00f0ff'};
                            cursor: pointer; font-family: inherit; font-size: 10px;
                        ">${macroState.recording ? 'STOP RECORDING' : 'START RECORDING'}</button>
                    </div>
                    <div style="color: #00f0ff; font-size: 10px; margin-bottom: 8px; border-bottom: 1px solid #222; padding-bottom: 4px;">
                        SAVED MACROS (${macros.length})
                    </div>
            `;

            if (macros.length === 0) {
                html += '<div style="color: #666; font-size: 10px; padding: 8px;">No macros saved. Record one above.</div>';
            } else {
                for (const m of macros) {
                    html += `
                        <div style="display: flex; align-items: center; padding: 4px 0; border-bottom: 1px solid #1a1a2e; gap: 6px;">
                            <span style="color: #05ffa1; font-size: 10px; min-width: 40px;">[${m.trigger}]</span>
                            <span style="flex: 1; font-size: 10px; color: #c0c0d0;">${m.name}</span>
                            <span style="color: #666; font-size: 9px;">${m.steps.length} steps</span>
                            <button class="macro-play-btn" data-trigger="${m.trigger}" style="
                                padding: 2px 8px; background: rgba(5, 255, 161, 0.1); border: 1px solid #05ffa1;
                                color: #05ffa1; cursor: pointer; font-family: inherit; font-size: 9px;
                            ">PLAY</button>
                            <button class="macro-del-btn" data-trigger="${m.trigger}" style="
                                padding: 2px 6px; background: rgba(255, 42, 109, 0.1); border: 1px solid #ff2a6d;
                                color: #ff2a6d; cursor: pointer; font-family: inherit; font-size: 9px;
                            ">X</button>
                        </div>
                    `;
                }
            }

            html += '</div>';
            container.innerHTML = html;

            // Wire buttons
            container.querySelector('#macro-record-btn').onclick = () => {
                if (macroState.recording) {
                    stopRecording();
                } else {
                    const name = container.querySelector('#macro-name-input').value || 'Untitled';
                    const trigger = container.querySelector('#macro-trigger-input').value || 'F5';
                    startRecording(name, trigger);
                }
                renderList();
            };

            container.querySelectorAll('.macro-play-btn').forEach(btn => {
                btn.onclick = () => playMacro(btn.dataset.trigger);
            });

            container.querySelectorAll('.macro-del-btn').forEach(btn => {
                btn.onclick = () => {
                    deleteMacro(btn.dataset.trigger);
                    renderList();
                };
            });
        };

        renderList();
    },
};

export { startRecording, stopRecording, recordStep, playMacro, deleteMacro, listMacros, macroState };
