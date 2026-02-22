// Game HUD Panel
// Shows wave/score/eliminations and BEGIN WAR button.
// Auto-opens on game state change, auto-hides when idle.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const GameHudPanelDef = {
    id: 'game',
    title: 'GAME STATUS',
    defaultPosition: { x: null, y: 8 },  // x calculated (top-right)
    defaultSize: { w: 240, h: 180 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'game-hud-panel-inner';
        el.innerHTML = `
            <div class="ghud-status">
                <div class="ghud-row">
                    <span class="ghud-label mono">PHASE</span>
                    <span class="ghud-value mono" data-bind="phase">IDLE</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">WAVE</span>
                    <span class="ghud-value mono" data-bind="wave">0/10</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">SCORE</span>
                    <span class="ghud-value mono" data-bind="score">0</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">ELIMS</span>
                    <span class="ghud-value mono" data-bind="elims">0</span>
                </div>
            </div>
            <div class="ghud-actions">
                <button class="panel-action-btn panel-action-btn-primary" data-action="begin-war">BEGIN WAR</button>
                <button class="panel-action-btn" data-action="spawn-hostile">SPAWN HOSTILE</button>
                <button class="panel-action-btn" data-action="reset-game">RESET</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at top-right if no saved layout
        if (panel.def.defaultPosition.x === null) {
            const cw = panel.manager.container.clientWidth || 1200;
            // Offset left to avoid overlapping the Alerts panel header in top-right
            const alertsPanel = panel.manager.getPanel('alerts');
            const offset = alertsPanel && alertsPanel._visible ? alertsPanel.w + 8 : 0;
            panel.x = cw - panel.w - 8 - offset;
            panel._applyTransform();
        }

        const phaseEl = bodyEl.querySelector('[data-bind="phase"]');
        const waveEl = bodyEl.querySelector('[data-bind="wave"]');
        const scoreEl = bodyEl.querySelector('[data-bind="score"]');
        const elimsEl = bodyEl.querySelector('[data-bind="elims"]');
        const beginBtn = bodyEl.querySelector('[data-action="begin-war"]');
        const spawnBtn = bodyEl.querySelector('[data-action="spawn-hostile"]');
        const resetBtn = bodyEl.querySelector('[data-action="reset-game"]');

        function updateVisibility() {
            const phase = TritiumStore.game.phase;
            if (beginBtn) {
                beginBtn.style.display = (phase === 'idle' || phase === 'setup') ? '' : 'none';
            }
            if (resetBtn) {
                resetBtn.style.display = (phase === 'victory' || phase === 'defeat') ? '' : 'none';
            }
        }

        panel._unsubs.push(
            TritiumStore.on('game.phase', (phase) => {
                if (phaseEl) phaseEl.textContent = (phase || 'IDLE').toUpperCase();
                updateVisibility();
            }),
            TritiumStore.on('game.wave', (wave) => {
                if (waveEl) waveEl.textContent = `${wave}/${TritiumStore.game.totalWaves}`;
            }),
            TritiumStore.on('game.score', (score) => {
                if (scoreEl) scoreEl.textContent = score;
            }),
            TritiumStore.on('game.eliminations', (elims) => {
                if (elimsEl) elimsEl.textContent = elims;
            })
        );

        // Apply current state
        if (phaseEl) phaseEl.textContent = (TritiumStore.game.phase || 'IDLE').toUpperCase();
        if (waveEl) waveEl.textContent = `${TritiumStore.game.wave}/${TritiumStore.game.totalWaves}`;
        if (scoreEl) scoreEl.textContent = TritiumStore.game.score || 0;
        if (elimsEl) elimsEl.textContent = TritiumStore.game.eliminations || 0;
        updateVisibility();

        // Button handlers
        if (beginBtn) {
            beginBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/game/begin', { method: 'POST' });
                    const data = await resp.json();
                    if (data.error) console.warn('[GAME] Begin war error:', data.error);
                } catch (e) {
                    console.error('[GAME] Begin war failed:', e);
                }
            });
        }

        if (spawnBtn) {
            spawnBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/amy/simulation/spawn', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({}),
                    });
                    if (resp.ok) {
                        EventBus.emit('toast:show', { message: 'Hostile spawned', type: 'alert' });
                    } else {
                        const data = await resp.json().catch(() => ({}));
                        EventBus.emit('toast:show', { message: data.detail || 'Spawn failed', type: 'alert' });
                    }
                } catch (e) {
                    console.error('[GAME] Spawn hostile failed:', e);
                    EventBus.emit('toast:show', { message: 'Spawn failed: network error', type: 'alert' });
                }
            });
        }

        if (resetBtn) {
            resetBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/game/reset', { method: 'POST' });
                    if (typeof warCombatReset === 'function') warCombatReset();
                } catch (e) {
                    console.error('[GAME] Reset failed:', e);
                }
            });
        }
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
