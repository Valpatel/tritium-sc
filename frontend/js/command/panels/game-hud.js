// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
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

// ============================================================
// Pure helper functions — exposed via window.GameHudHelpers
// ============================================================

/**
 * Health ratio to color string.
 * Green >60%, yellow 30-60%, red <30%.
 * @param {number} ratio 0..1
 * @returns {string} hex color
 */
function healthColor(ratio) {
    const r = typeof ratio === 'number' && !isNaN(ratio) ? ratio : 0;
    if (r > 0.6) return '#05ffa1';
    if (r >= 0.3) return '#fcee0a';
    return '#ff2a6d';
}

/**
 * ASCII health bar using unicode block characters.
 * @param {number} ratio 0..1
 * @param {number} [width=20] total width in chars
 * @returns {string}
 */
function healthBar(ratio, width) {
    const w = width || 20;
    const clamped = Math.max(0, Math.min(1, typeof ratio === 'number' && !isNaN(ratio) ? ratio : 0));
    const filled = Math.round(clamped * w);
    return '\u2588'.repeat(filled) + '\u2591'.repeat(w - filled);
}

/**
 * Determine morale trend direction.
 * 'rising' if current > previous + 5%, 'falling' if current < previous - 5%, else 'steady'.
 * @param {number} current
 * @param {number} previous
 * @returns {'rising'|'falling'|'steady'}
 */
function moraleTrend(current, previous) {
    const diff = (current || 0) - (previous || 0);
    // Use > threshold with small epsilon to handle floating point
    const threshold = 0.05 + 1e-9;
    if (diff > threshold) return 'rising';
    if (diff < -threshold) return 'falling';
    return 'steady';
}

/**
 * Wave progress as percentage eliminated.
 * @param {number} remaining hostiles remaining
 * @param {number} total hostiles total
 * @returns {number} 0..100
 */
function waveProgressPct(remaining, total) {
    if (!total || total <= 0) return 0;
    const r = Math.max(0, remaining);
    const pct = ((total - r) / total) * 100;
    return Math.max(0, Math.min(100, Math.round(pct)));
}

/**
 * Compute hit accuracy percentage.
 * @param {number} hits
 * @param {number} shots
 * @returns {number} 0..100
 */
function computeAccuracy(hits, shots) {
    if (!shots || shots <= 0) return 0;
    return Math.round((hits / shots) * 100);
}

/**
 * Find the friendly unit with the most kills.
 * @param {Array} units
 * @returns {Object|null}
 */
function findMVP(units) {
    if (!units || units.length === 0) return null;
    const friendlies = units.filter(u => u.alliance === 'friendly');
    if (friendlies.length === 0) return null;
    return friendlies.reduce((best, u) => {
        const uKills = u.kills || u.eliminations || 0;
        const bKills = best.kills || best.eliminations || 0;
        return uKills > bKills ? u : best;
    }, friendlies[0]);
}

/**
 * Map unit type to a unicode symbol.
 * @param {string} type
 * @returns {string}
 */
function typeIcon(type) {
    const icons = {
        turret: '\u2302',       // house/turret
        heavy_turret: '\u2302',
        missile_turret: '\u2302',
        drone: '\u2708',        // airplane
        scout_drone: '\u2693',  // anchor (small drone variant)
        rover: '\u25A3',        // square with fill
        tank: '\u25C6',         // diamond
        apc: '\u25A0',          // solid square
        person: '\u2663',       // club suit (person)
        hostile: '\u2620',      // skull
        camera: '\u25CE',       // bullseye
        sensor: '\u25CE',
    };
    return icons[type] || '\u25CB'; // open circle fallback
}

/**
 * Format seconds as M:SS.
 * @param {number} seconds
 * @returns {string}
 */
function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? '0' : ''}${sec}`;
}

/**
 * Count active hostile units.
 * @param {Array} units
 * @returns {number}
 */
function countThreats(units) {
    if (!units) return 0;
    return units.filter(u =>
        u.alliance === 'hostile' &&
        (u.status || 'active') === 'active'
    ).length;
}

/**
 * Average morale of friendly units. Defaults to 1.0 for missing morale.
 * @param {Array} units
 * @returns {number}
 */
function avgMorale(units) {
    if (!units || units.length === 0) return 1.0;
    const friendlies = units.filter(u => u.alliance === 'friendly');
    if (friendlies.length === 0) return 1.0;
    const sum = friendlies.reduce((acc, u) => {
        const m = (typeof u.morale === 'number' && !isNaN(u.morale)) ? u.morale : 1.0;
        return acc + m;
    }, 0);
    return sum / friendlies.length;
}

/**
 * Build HTML for the friendly unit roster.
 * @param {Array} units
 * @returns {string}
 */
function buildRosterHTML(units) {
    if (!units || units.length === 0) return '<div class="ghud-empty">No units deployed</div>';
    const friendlies = units.filter(u => u.alliance === 'friendly');
    if (friendlies.length === 0) return '<div class="ghud-empty">No friendly units</div>';
    return '<div class="ghud-roster">' + friendlies.map(u => {
        const hp = typeof u.health === 'number' ? u.health : (u.max_health || 100);
        const maxHp = u.max_health || 100;
        const ratio = maxHp > 0 ? hp / maxHp : 1;
        const color = healthColor(ratio);
        const icon = typeIcon(u.type || 'unknown');
        const bar = healthBar(ratio, 8);
        const name = _esc(u.name || u.target_id || 'Unit');
        return `<div class="ghud-roster-unit">` +
            `<span class="ghud-roster-icon">${icon}</span>` +
            `<span class="ghud-roster-name">${name}</span>` +
            `<span class="ghud-roster-hp" style="color:${color}">${bar}</span>` +
            `</div>`;
    }).join('') + '</div>';
}

/**
 * Build HTML for wave progress bar.
 * @param {number} wave
 * @param {number} remaining
 * @param {number} total
 * @param {number} elapsed seconds
 * @returns {string}
 */
function buildWaveProgressHTML(wave, remaining, total, elapsed) {
    const pct = waveProgressPct(remaining, total);
    const time = formatTime(elapsed || 0);
    return `<div class="ghud-wave-progress">` +
        `<div class="ghud-wave-header">` +
        `<span class="ghud-label mono">WAVE ${wave || 0}</span>` +
        `<span class="ghud-value mono">${time}</span>` +
        `</div>` +
        `<div class="panel-bar">` +
        `<div class="panel-bar-fill" style="width:${pct}%;background:${pct >= 75 ? '#05ffa1' : pct >= 40 ? '#fcee0a' : '#00f0ff'}"></div>` +
        `<div class="panel-bar-label">${pct}%</div>` +
        `</div>` +
        `</div>`;
}

/**
 * Build HTML for combat metrics display.
 * @param {Object} data { accuracy, dps, threats, morale, moraleTrend }
 * @returns {string}
 */
function buildCombatMetricsHTML(data) {
    const d = data || {};
    const acc = typeof d.accuracy === 'number' ? d.accuracy : 0;
    const dps = typeof d.dps === 'number' ? d.dps : 0;
    const threats = typeof d.threats === 'number' ? d.threats : 0;
    const mor = typeof d.morale === 'number' ? Math.round(d.morale * 100) : 100;
    const trend = d.moraleTrend || 'steady';
    const trendArrow = trend === 'rising' ? '\u2191' : trend === 'falling' ? '\u2193' : '\u2194';
    const trendColor = trend === 'rising' ? '#05ffa1' : trend === 'falling' ? '#ff2a6d' : '#fcee0a';
    return `<div class="ghud-combat-metrics">` +
        `<div class="ghud-row"><span class="ghud-label mono">ACCURACY</span><span class="ghud-value mono">${acc}%</span></div>` +
        `<div class="ghud-row"><span class="ghud-label mono">DPS</span><span class="ghud-value mono">${dps.toFixed(1)}</span></div>` +
        `<div class="ghud-row"><span class="ghud-label mono">THREATS</span><span class="ghud-value mono" style="color:${threats > 0 ? '#ff2a6d' : '#05ffa1'}">${threats}</span></div>` +
        `<div class="ghud-row"><span class="ghud-label mono">MORALE</span><span class="ghud-value mono">${mor}% <span style="color:${trendColor}">${trendArrow}</span></span></div>` +
        `</div>`;
}

/**
 * Build HTML for MVP tracker.
 * @param {Object|null} mvp
 * @returns {string}
 */
function buildMVPHTML(mvp) {
    if (!mvp) return '<div class="ghud-mvp ghud-empty">No MVP yet</div>';
    const icon = typeIcon(mvp.type || 'unknown');
    const name = _esc(mvp.name || 'Unknown');
    const kills = mvp.kills || mvp.eliminations || 0;
    return `<div class="ghud-mvp">` +
        `<span class="ghud-mvp-icon">${icon}</span>` +
        `<span class="ghud-mvp-name">${name}</span>` +
        `<span class="ghud-mvp-kills">${kills} KILLS</span>` +
        `</div>`;
}

// Expose helpers on window for testing and cross-module access
if (typeof window !== 'undefined') {
    window.GameHudHelpers = {
        healthColor,
        healthBar,
        moraleTrend,
        waveProgressPct,
        computeAccuracy,
        findMVP,
        typeIcon,
        formatTime,
        countThreats,
        avgMorale,
        buildRosterHTML,
        buildWaveProgressHTML,
        buildCombatMetricsHTML,
        buildMVPHTML,
    };
}

// ============================================================
// CombatStatsTracker — tracks combat statistics over a session
// ============================================================

class CombatStatsTracker {
    constructor() {
        this.shotsFired = 0;
        this.shotsHit = 0;
        this.totalDamage = 0;
        this.totalEliminations = 0;
        this._startTime = Date.now();
    }

    recordShot() { this.shotsFired += 1; }
    recordHit() { this.shotsHit += 1; }
    recordDamage(amt) { this.totalDamage += (amt || 0); }
    recordElimination() { this.totalEliminations += 1; }

    accuracy() {
        if (this.shotsFired === 0) return 0;
        return Math.round((this.shotsHit / this.shotsFired) * 100);
    }

    dps() {
        if (this.totalDamage === 0) return 0;
        const elapsed = (Date.now() - this._startTime) / 1000;
        if (elapsed <= 0) return 0;
        return this.totalDamage / elapsed;
    }

    reset() {
        this.shotsFired = 0;
        this.shotsHit = 0;
        this.totalDamage = 0;
        this.totalEliminations = 0;
        this._startTime = Date.now();
    }
}

if (typeof window !== 'undefined') {
    window.CombatStatsTracker = CombatStatsTracker;
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
