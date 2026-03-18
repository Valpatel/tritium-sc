// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Game HUD Panel
// Shows wave/score/eliminations and BEGIN WAR button.
// Auto-opens on game state change, auto-hides when idle.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';


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

// ============================================================
// Upgrade & Ability helpers — exposed via window.UpgradeHelpers
// ============================================================

/**
 * Map upgrade_id to a unicode icon character.
 * @param {string} upgradeId
 * @returns {string}
 */
function upgradeIcon(upgradeId) {
    const icons = {
        armor_plating: '\u229E',      // squared plus (armor)
        enhanced_optics: '\u25CE',    // bullseye (optics)
        rapid_fire: '\u2604',         // comet (rapid fire)
        reinforced_chassis: '\u2B23', // hexagon (chassis)
        turbo_motor: '\u26A1',        // high voltage (speed)
        precision_targeting: '\u2316', // position indicator (targeting)
    };
    return icons[upgradeId] || '\u2B24'; // filled circle fallback
}

/**
 * Map ability_id to a unicode icon character.
 * @param {string} abilityId
 * @returns {string}
 */
function abilityIcon(abilityId) {
    const icons = {
        speed_boost: '\u26A1',        // high voltage
        emergency_repair: '\u2695',   // staff of aesculapius
        shield: '\u2B23',             // hexagon (shield)
        emp_burst: '\u2622',          // radioactive (EMP)
        overclock: '\u2699',          // gear (overclock)
    };
    return icons[abilityId] || '\u25C6'; // diamond fallback
}

/**
 * Format an upgrade cost for display.
 * @param {number} cost
 * @returns {string}
 */
function formatUpgradeCost(cost) {
    if (!cost || cost <= 0) return 'FREE';
    return String(cost);
}

/**
 * Format a cooldown remaining time.
 * @param {number} seconds
 * @returns {string} e.g. "12s" or "" if 0
 */
function formatCooldown(seconds) {
    if (!seconds || seconds <= 0) return '';
    return `${Math.floor(seconds)}s`;
}

/**
 * Check if the current game phase allows upgrade purchasing.
 * @param {string} phase
 * @returns {boolean}
 */
function isUpgradePhase(phase) {
    return phase === 'wave_complete';
}

/**
 * Check if an upgrade can be applied to a given unit type.
 * @param {Object} upgrade - { eligible_types: string[]|null }
 * @param {string} unitType
 * @returns {boolean}
 */
function canApplyUpgrade(upgrade, unitType) {
    if (!upgrade.eligible_types) return true;
    return upgrade.eligible_types.includes(unitType);
}

/**
 * Build HTML for a single upgrade card.
 * @param {Object} upgrade - { upgrade_id, name, description, cost, stat_modifiers }
 * @returns {string}
 */
function buildUpgradeCardHTML(upgrade) {
    const icon = upgradeIcon(upgrade.upgrade_id);
    const cost = formatUpgradeCost(upgrade.cost);
    const costClass = cost === 'FREE' ? 'ghud-upgrade-cost--free' : '';
    return `<div class="ghud-upgrade-card" data-upgrade-id="${_esc(upgrade.upgrade_id)}">` +
        `<div class="ghud-upgrade-icon">${icon}</div>` +
        `<div class="ghud-upgrade-info">` +
        `<div class="ghud-upgrade-name">${_esc(upgrade.name)}</div>` +
        `<div class="ghud-upgrade-desc">${_esc(upgrade.description)}</div>` +
        `</div>` +
        `<div class="ghud-upgrade-cost ${costClass}">${cost}</div>` +
        `</div>`;
}

/**
 * Build HTML for a grid of upgrade cards.
 * @param {Array} upgrades - array of upgrade objects
 * @returns {string}
 */
function buildUpgradeGridHTML(upgrades) {
    if (!upgrades || upgrades.length === 0) {
        return '<div class="ghud-empty">No upgrades available</div>';
    }
    return '<div class="ghud-upgrade-grid">' +
        upgrades.map(u => buildUpgradeCardHTML(u)).join('') +
        '</div>';
}

/**
 * Build HTML for an ability button.
 * @param {Object} ability - { ability_id, name, description, cooldown, duration }
 * @param {Object} state - { ready: boolean, cooldownRemaining: number }
 * @returns {string}
 */
function buildAbilityButtonHTML(ability, state) {
    const icon = abilityIcon(ability.ability_id);
    const ready = state && state.ready;
    const cdRemaining = state && state.cooldownRemaining ? Math.floor(state.cooldownRemaining) : 0;
    const stateClass = ready ? 'unit-ability-btn--ready' : 'unit-ability-btn--cooldown';
    const cdLabel = !ready && cdRemaining > 0 ? `<span class="unit-ability-cd">${cdRemaining}s</span>` : '';
    return `<button class="unit-ability-btn ${stateClass}" data-ability-id="${_esc(ability.ability_id)}" ` +
        `title="${_esc(ability.description)}" ${ready ? '' : 'disabled'}>` +
        `<span class="unit-ability-icon">${icon}</span>` +
        `<span class="unit-ability-name">${_esc(ability.name)}</span>` +
        `${cdLabel}` +
        `</button>`;
}

/**
 * Build HTML for a row of ability buttons.
 * @param {Array} abilities - array of ability objects
 * @param {Object} cooldowns - { ability_id: remaining_seconds }
 * @returns {string}
 */
function buildAbilityBarHTML(abilities, cooldowns) {
    if (!abilities || abilities.length === 0) return '';
    const cd = cooldowns || {};
    return '<div class="unit-ability-bar">' +
        abilities.map(a => {
            const remaining = cd[a.ability_id] || 0;
            const ready = remaining <= 0;
            return buildAbilityButtonHTML(a, { ready, cooldownRemaining: remaining });
        }).join('') +
        '</div>';
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
    window.UpgradeHelpers = {
        upgradeIcon,
        abilityIcon,
        formatUpgradeCost,
        formatCooldown,
        isUpgradePhase,
        canApplyUpgrade,
        buildUpgradeCardHTML,
        buildUpgradeGridHTML,
        buildAbilityButtonHTML,
        buildAbilityBarHTML,
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
    defaultSize: { w: 260, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'game-hud-panel-inner';
        el.innerHTML = `
            <div class="ghud-status">
                <div class="ghud-countdown" data-bind="countdown" style="display:none"></div>
                <div class="ghud-row">
                    <span class="ghud-label mono">PHASE</span>
                    <span class="ghud-value mono" data-bind="phase">IDLE</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">WAVE</span>
                    <span class="ghud-value mono" data-bind="wave">0/10</span>
                </div>
                <div class="ghud-row ghud-row--wavename" style="display:none">
                    <span class="ghud-value mono ghud-wavename" data-bind="waveName"></span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">SCORE</span>
                    <span class="ghud-value mono" data-bind="score">0</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">ELIMS</span>
                    <span class="ghud-value mono" data-bind="elims">0</span>
                </div>
                <div class="ghud-row">
                    <span class="ghud-label mono">DIFFICULTY</span>
                    <span class="ghud-value mono" data-bind="difficulty">1.0x</span>
                </div>
            </div>
            <div data-section="mission-metrics"></div>
            <div data-section="wave-progress"></div>
            <div data-section="roster"></div>
            <div data-section="combat-metrics"></div>
            <div data-section="mvp"></div>
            <div data-section="game-metrics"></div>
            <div data-section="upgrades" style="display:none"></div>
            <div class="ghud-placement-toolbar" data-section="placement-toolbar">
                <div class="ghud-section-label">PLACE UNIT</div>
                <div class="ghud-placement-btns">
                    <button class="ghud-place-btn ghud-place-btn--active" data-place-type="turret" title="Turret (80m range)">T</button>
                    <button class="ghud-place-btn" data-place-type="heavy_turret" title="Heavy Turret (120m range)">H</button>
                    <button class="ghud-place-btn" data-place-type="missile_turret" title="Missile Turret (150m range)">M</button>
                    <button class="ghud-place-btn" data-place-type="rover" title="Rover (60m range)">R</button>
                    <button class="ghud-place-btn" data-place-type="drone" title="Drone (50m range)">D</button>
                    <button class="ghud-place-btn" data-place-type="scout_drone" title="Scout Drone (40m range)">S</button>
                    <button class="ghud-place-btn" data-place-type="tank" title="Tank (100m range)">K</button>
                    <button class="ghud-place-btn" data-place-type="apc" title="APC (60m range)">A</button>
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

        const countdownEl = bodyEl.querySelector('[data-bind="countdown"]');
        const phaseEl = bodyEl.querySelector('[data-bind="phase"]');
        const waveEl = bodyEl.querySelector('[data-bind="wave"]');
        const waveNameEl = bodyEl.querySelector('[data-bind="waveName"]');
        const waveNameRow = bodyEl.querySelector('.ghud-row--wavename');
        const scoreEl = bodyEl.querySelector('[data-bind="score"]');
        const elimsEl = bodyEl.querySelector('[data-bind="elims"]');
        const difficultyEl = bodyEl.querySelector('[data-bind="difficulty"]');
        const beginBtn = bodyEl.querySelector('[data-action="begin-war"]');
        const spawnBtn = bodyEl.querySelector('[data-action="spawn-hostile"]');
        const resetBtn = bodyEl.querySelector('[data-action="reset-game"]');

        // Combat dashboard section containers
        const waveProgressEl = bodyEl.querySelector('[data-section="wave-progress"]');
        const rosterEl = bodyEl.querySelector('[data-section="roster"]');
        const metricsEl = bodyEl.querySelector('[data-section="combat-metrics"]');
        const mvpEl = bodyEl.querySelector('[data-section="mvp"]');

        // Mission-mode-specific metrics (civil_unrest / drone_swarm)
        const missionMetricsEl = bodyEl.querySelector('[data-section="mission-metrics"]');

        // Game metrics section (aggregate per-unit stats)
        const gameMetricsEl = bodyEl.querySelector('[data-section="game-metrics"]');

        // Upgrades section (wave_complete phase)
        const upgradesEl = bodyEl.querySelector('[data-section="upgrades"]');
        let _cachedUpgrades = null;

        // Placement toolbar (setup mode)
        const placementToolbar = bodyEl.querySelector('[data-section="placement-toolbar"]');
        const placeBtns = bodyEl.querySelectorAll('.ghud-place-btn');

        // Initialize placement type
        if (typeof window !== 'undefined') {
            window._setupPlacementType = window._setupPlacementType || 'turret';
        }

        // Wire placement button clicks
        if (placeBtns && placeBtns.length > 0) {
            placeBtns.forEach(btn => {
                btn.addEventListener('click', () => {
                    const type = btn.getAttribute('data-place-type');
                    if (!type) return;
                    if (typeof window !== 'undefined') {
                        window._setupPlacementType = type;
                    }
                    // Update active state on all buttons
                    placeBtns.forEach(b => b.classList.remove('ghud-place-btn--active'));
                    btn.classList.add('ghud-place-btn--active');
                });
            });
        }

        // Create a CombatStatsTracker for this panel session
        const tracker = new CombatStatsTracker();
        let _previousMorale = 1.0;
        let _waveHostileTotal = 0;
        let _waveStartTime = 0;

        function _getUnitsArray() {
            const units = TritiumStore.units;
            if (!units || typeof units.forEach !== 'function') return [];
            const arr = [];
            units.forEach(u => arr.push(u));
            return arr;
        }

        function _isActivePhase() {
            const phase = TritiumStore.game.phase;
            return phase === 'active' || phase === 'wave_complete' || phase === 'countdown';
        }

        /**
         * Re-render the combat dashboard sections using the helper functions.
         * Called every 2 seconds during active play.
         */
        function _renderGameMetrics() {
            if (!gameMetricsEl) return;
            const allUnits = _getUnitsArray();
            let totalShots = 0, totalHits = 0, totalDist = 0;
            let totalDmgDealt = 0, totalDmgTaken = 0;
            for (const u of allUnits) {
                if (u.alliance !== 'friendly' || !u.stats) continue;
                totalShots += u.stats.shots_fired || 0;
                totalHits += u.stats.shots_hit || 0;
                totalDist += u.stats.distance_traveled || 0;
                totalDmgDealt += u.stats.damage_dealt || 0;
                totalDmgTaken += u.stats.damage_taken || 0;
            }
            if (totalShots === 0 && totalDist < 0.1 && totalDmgDealt === 0) {
                gameMetricsEl.innerHTML = '';
                return;
            }
            const accPct = totalShots > 0 ? Math.round((totalHits / totalShots) * 100) : 0;
            gameMetricsEl.innerHTML =
                '<div class="ghud-section-label">GAME METRICS</div>' +
                '<div class="ghud-combat-metrics">' +
                `<div class="ghud-row"><span class="ghud-label mono">SHOTS</span><span class="ghud-value mono">${totalShots} fired / ${totalHits} hit (${accPct}%)</span></div>` +
                `<div class="ghud-row"><span class="ghud-label mono">DISTANCE</span><span class="ghud-value mono">${Math.round(totalDist)}m total</span></div>` +
                `<div class="ghud-row"><span class="ghud-label mono">DAMAGE</span><span class="ghud-value mono">${totalDmgDealt.toFixed(1)} dealt / ${totalDmgTaken.toFixed(1)} taken</span></div>` +
                '</div>';
        }

        /**
         * Render mission-mode-specific metrics (civil_unrest, drone_swarm).
         * Shows infrastructure health, de-escalation score, civilian harm, etc.
         */
        function _renderMissionMetrics() {
            if (!missionMetricsEl) return;
            const modeType = TritiumStore.get('game.modeType');
            if (!modeType || modeType === 'battle') {
                missionMetricsEl.innerHTML = '';
                return;
            }

            let rows = '';
            if (modeType === 'civil_unrest') {
                const deEsc = TritiumStore.get('game.deEscalationScore');
                const civHarm = TritiumStore.get('game.civilianHarmCount');
                const civLimit = TritiumStore.get('game.civilianHarmLimit');
                const infraHp = TritiumStore.get('game.infrastructureHealth');
                const infraMax = TritiumStore.get('game.infrastructureMax');
                if (deEsc != null) {
                    rows += `<div class="ghud-row"><span class="ghud-label mono">DE-ESCALATION</span><span class="ghud-value mono" style="color:#05ffa1">${Math.round(deEsc)}</span></div>`;
                }
                if (civHarm != null) {
                    const limitStr = civLimit != null ? `/${civLimit}` : '';
                    const color = civLimit && civHarm >= civLimit * 0.8 ? '#ff2a6d' : '#fcee0a';
                    rows += `<div class="ghud-row"><span class="ghud-label mono">CIV HARM</span><span class="ghud-value mono" style="color:${color}">${civHarm}${limitStr}</span></div>`;
                }
                if (infraHp != null) {
                    const maxHp = infraMax || 100;
                    const pct = Math.round((infraHp / maxHp) * 100);
                    const color = pct > 50 ? '#05ffa1' : pct > 25 ? '#fcee0a' : '#ff2a6d';
                    rows += `<div class="ghud-row"><span class="ghud-label mono">INFRASTRUCTURE</span><span class="ghud-value mono" style="color:${color}">${pct}%</span></div>`;
                }
            } else if (modeType === 'drone_swarm') {
                const infraHp = TritiumStore.get('game.infrastructureHealth');
                const infraMax = TritiumStore.get('game.infrastructureMax');
                if (infraHp != null) {
                    const maxHp = infraMax || 100;
                    const pct = Math.round((infraHp / maxHp) * 100);
                    const color = pct > 50 ? '#05ffa1' : pct > 25 ? '#fcee0a' : '#ff2a6d';
                    rows += `<div class="ghud-row"><span class="ghud-label mono">INFRASTRUCTURE</span><span class="ghud-value mono" style="color:${color}">${pct}%</span></div>`;
                }
            }

            if (rows) {
                const label = modeType === 'civil_unrest' ? 'CIVIL UNREST' : 'DRONE SWARM';
                missionMetricsEl.innerHTML =
                    `<div class="ghud-section-label">${label}</div>` +
                    `<div class="ghud-combat-metrics">${rows}</div>`;
            } else {
                missionMetricsEl.innerHTML = '';
            }
        }

        function refreshDashboard() {
            // Game metrics always render (visible proof of combat activity)
            _renderGameMetrics();
            // Mission-mode-specific metrics
            _renderMissionMetrics();

            if (!_isActivePhase()) {
                // Hide dashboard sections when not in active play
                if (waveProgressEl) waveProgressEl.innerHTML = '';
                if (rosterEl) rosterEl.innerHTML = '';
                if (metricsEl) metricsEl.innerHTML = '';
                if (mvpEl) mvpEl.innerHTML = '';
                return;
            }

            const allUnits = _getUnitsArray();
            const hostileCount = countThreats(allUnits);

            // Wave progress
            if (waveProgressEl) {
                const elapsed = _waveStartTime > 0 ? (Date.now() - _waveStartTime) / 1000 : 0;
                waveProgressEl.innerHTML =
                    '<div class="ghud-section-label">WAVE PROGRESS</div>' +
                    buildWaveProgressHTML(
                        TritiumStore.game.wave,
                        hostileCount,
                        _waveHostileTotal || hostileCount || 1,
                        elapsed
                    );
            }

            // Friendly roster with health bars
            if (rosterEl) {
                rosterEl.innerHTML =
                    '<div class="ghud-section-label">FRIENDLY ROSTER</div>' +
                    buildRosterHTML(allUnits);
            }

            // Combat metrics (accuracy, DPS, threats, morale)
            if (metricsEl) {
                const currentMorale = avgMorale(allUnits);
                const trend = moraleTrend(currentMorale, _previousMorale);
                _previousMorale = currentMorale;
                metricsEl.innerHTML =
                    '<div class="ghud-section-label">COMBAT METRICS</div>' +
                    buildCombatMetricsHTML({
                        accuracy: tracker.accuracy(),
                        dps: tracker.dps(),
                        threats: hostileCount,
                        morale: currentMorale,
                        moraleTrend: trend,
                    });
            }

            // MVP tracker
            if (mvpEl) {
                const mvp = findMVP(allUnits);
                mvpEl.innerHTML =
                    '<div class="ghud-section-label">MVP</div>' +
                    buildMVPHTML(mvp);
            }
        }

        /**
         * Fetch available upgrades from the API and render the upgrade picker.
         * Called when entering wave_complete phase.
         */
        async function showUpgradePicker() {
            if (!upgradesEl) return;
            upgradesEl.style.display = '';

            // Fetch upgrades list (cached after first call)
            if (!_cachedUpgrades) {
                try {
                    const resp = await fetch('/api/game/upgrades');
                    if (resp.ok) {
                        _cachedUpgrades = await resp.json();
                    } else {
                        _cachedUpgrades = [];
                    }
                } catch (e) {
                    console.error('[GAME] Failed to fetch upgrades:', e);
                    _cachedUpgrades = [];
                }
            }

            const currentScore = TritiumStore.game.score || 0;
            upgradesEl.innerHTML =
                '<div class="ghud-section-label">UPGRADES</div>' +
                '<div class="ghud-upgrade-hint">Select an upgrade, then click a friendly unit</div>' +
                buildUpgradeGridHTML(_cachedUpgrades);

            // Wire up click handlers for upgrade cards
            upgradesEl.querySelectorAll('.ghud-upgrade-card').forEach(card => {
                card.addEventListener('click', () => {
                    const upgradeId = card.dataset.upgradeId;
                    if (!upgradeId) return;

                    // Toggle selection
                    const wasSelected = card.classList.contains('ghud-upgrade-card--selected');
                    upgradesEl.querySelectorAll('.ghud-upgrade-card').forEach(c =>
                        c.classList.remove('ghud-upgrade-card--selected')
                    );

                    if (!wasSelected) {
                        card.classList.add('ghud-upgrade-card--selected');
                        // Store selected upgrade for unit click handler
                        if (typeof window !== 'undefined') {
                            window._selectedUpgradeId = upgradeId;
                        }
                        EventBus.emit('toast:show', {
                            message: 'Click a friendly unit to apply upgrade',
                            type: 'info',
                        });
                    } else {
                        if (typeof window !== 'undefined') {
                            window._selectedUpgradeId = null;
                        }
                    }
                });
            });
        }

        function hideUpgradePicker() {
            if (upgradesEl) {
                upgradesEl.style.display = 'none';
                upgradesEl.innerHTML = '';
            }
            if (typeof window !== 'undefined') {
                window._selectedUpgradeId = null;
            }
        }

        // Listen for unit selection during upgrade phase — apply the selected upgrade
        const onUpgradeUnitSelect = async (data) => {
            if (typeof window === 'undefined' || !window._selectedUpgradeId) return;
            const phase = TritiumStore.game.phase;
            if (!isUpgradePhase(phase)) return;
            const unitId = data.id || data.unit_id;
            if (!unitId) return;

            const upgradeId = window._selectedUpgradeId;
            try {
                const resp = await fetch('/api/game/upgrade', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ unit_id: unitId, upgrade_id: upgradeId }),
                });
                if (resp.ok) {
                    const result = await resp.json();
                    EventBus.emit('toast:show', {
                        message: `Upgrade applied: ${upgradeId.replace(/_/g, ' ')}`,
                        type: 'success',
                    });
                    // Clear selection
                    window._selectedUpgradeId = null;
                    if (upgradesEl) {
                        upgradesEl.querySelectorAll('.ghud-upgrade-card').forEach(c =>
                            c.classList.remove('ghud-upgrade-card--selected')
                        );
                    }
                } else {
                    const err = await resp.json().catch(() => ({}));
                    EventBus.emit('toast:show', {
                        message: err.detail || 'Upgrade failed',
                        type: 'alert',
                    });
                }
            } catch (e) {
                console.error('[GAME] Apply upgrade failed:', e);
                EventBus.emit('toast:show', { message: 'Upgrade failed: network error', type: 'alert' });
            }
        };
        EventBus.on('unit:selected', onUpgradeUnitSelect);
        panel._unsubs.push(() => EventBus.off('unit:selected', onUpgradeUnitSelect));

        function updateVisibility() {
            const phase = TritiumStore.game.phase;
            if (beginBtn) {
                beginBtn.style.display = (phase === 'idle' || phase === 'setup') ? '' : 'none';
            }
            if (resetBtn) {
                resetBtn.style.display = (phase === 'victory' || phase === 'defeat') ? '' : 'none';
            }
            // Placement toolbar only visible during idle/setup
            if (placementToolbar) {
                placementToolbar.style.display = (phase === 'idle' || phase === 'setup') ? '' : 'none';
            }
            // Upgrade picker visible during wave_complete
            if (isUpgradePhase(phase)) {
                showUpgradePicker();
            } else {
                hideUpgradePicker();
            }
        }

        // Subscribe to store changes for the static header
        panel._unsubs.push(
            TritiumStore.on('game.phase', (phase) => {
                if (phaseEl) phaseEl.textContent = (phase || 'IDLE').toUpperCase();
                // Show/hide countdown overlay based on phase
                if (countdownEl) {
                    countdownEl.style.display = phase === 'countdown' ? '' : 'none';
                }
                updateVisibility();
                // Trigger immediate dashboard refresh on phase change
                refreshDashboard();
            }),
            TritiumStore.on('game.countdown', (count) => {
                if (countdownEl) {
                    const n = typeof count === 'number' ? count : 0;
                    if (n > 0) {
                        countdownEl.textContent = String(n);
                        countdownEl.style.display = '';
                    } else {
                        countdownEl.style.display = 'none';
                    }
                }
            }),
            TritiumStore.on('game.wave', (wave) => {
                if (waveEl) waveEl.textContent = `${wave}/${TritiumStore.game.totalWaves}`;
            }),
            TritiumStore.on('game.waveName', (name) => {
                if (waveNameEl) waveNameEl.textContent = name || '';
                if (waveNameRow) waveNameRow.style.display = name ? '' : 'none';
            }),
            TritiumStore.on('game.score', (score) => {
                if (scoreEl) scoreEl.textContent = score;
            }),
            TritiumStore.on('game.eliminations', (elims) => {
                if (elimsEl) elimsEl.textContent = elims;
            }),
            TritiumStore.on('game.difficultyMultiplier', (mult) => {
                if (difficultyEl) {
                    const m = typeof mult === 'number' ? mult : 1.0;
                    difficultyEl.textContent = m.toFixed(1) + 'x';
                    // Color code: green=easy, yellow=normal, red=hard
                    difficultyEl.style.color = m < 0.8 ? '#05ffa1' : m > 1.3 ? '#ff2a6d' : '#fcee0a';
                }
            })
        );

        // Subscribe to combat events to feed the CombatStatsTracker
        panel._unsubs.push(
            EventBus.on('combat:projectile', () => {
                tracker.recordShot();
            }),
            EventBus.on('combat:hit', (d) => {
                tracker.recordHit();
                tracker.recordDamage(d.damage || d.dmg || 10);
            }),
            EventBus.on('combat:elimination', () => {
                tracker.recordElimination();
            }),
            EventBus.on('game:wave_start', (d) => {
                _waveHostileTotal = d.hostile_count || d.hostiles || 0;
                _waveStartTime = Date.now();
            }),
            EventBus.on('game:state', (d) => {
                // Reset tracker on new game
                if (d.state === 'active' && (TritiumStore.game.wave === 1 || d.wave === 1)) {
                    tracker.reset();
                    _previousMorale = 1.0;
                }
            })
        );

        // Mission-critical event announcements (bomber, EMP, instigator, infrastructure)
        panel._unsubs.push(
            EventBus.on('mission:bomber_detonation', (d) => {
                if (typeof warHudShowAmyAnnouncement === 'function') {
                    warHudShowAmyAnnouncement('BOMBER DETONATION -- infrastructure damaged!', 'alert');
                }
            }),
            EventBus.on('mission:emp_activated', (d) => {
                const count = d && d.drones_disabled ? d.drones_disabled : '?';
                if (typeof warHudShowAmyAnnouncement === 'function') {
                    warHudShowAmyAnnouncement(`EMP BURST -- ${count} drones disabled`, 'tactical');
                }
            }),
            EventBus.on('mission:instigator_identified', (d) => {
                const who = d && d.unit_id ? d.unit_id : 'unknown';
                if (typeof warHudShowAmyAnnouncement === 'function') {
                    warHudShowAmyAnnouncement(`INSTIGATOR IDENTIFIED: ${who}`, 'alert');
                }
            }),
            EventBus.on('mission:infrastructure_overwhelmed', () => {
                if (typeof warHudShowAmyAnnouncement === 'function') {
                    warHudShowAmyAnnouncement('INFRASTRUCTURE CRITICAL -- imminent collapse!', 'alert');
                }
            })
        );

        // Combat status events — wire orphan EventBus events to toast/HUD feedback
        panel._unsubs.push(
            EventBus.on('combat:ammo_low', (d) => {
                const who = d && d.unit_name ? d.unit_name : 'Unit';
                EventBus.emit('toast:show', { message: `${who}: AMMO LOW`, type: 'alert', duration: 3000 });
            }),
            EventBus.on('combat:ammo_depleted', (d) => {
                const who = d && d.unit_name ? d.unit_name : 'Unit';
                EventBus.emit('toast:show', { message: `${who}: AMMO DEPLETED`, type: 'alert', duration: 4000 });
            }),
            EventBus.on('combat:weapon_jam', (d) => {
                const who = d && d.unit_name ? d.unit_name : 'Unit';
                EventBus.emit('toast:show', { message: `${who}: WEAPON JAM`, type: 'alert', duration: 3000 });
            }),
            EventBus.on('combat:neutralized', (d) => {
                const who = d && d.target_name ? d.target_name : 'Target';
                EventBus.emit('toast:show', { message: `${who} NEUTRALIZED`, type: 'info', duration: 3000 });
            }),
            EventBus.on('ability:activated', (d) => {
                const name = d && d.ability_name ? d.ability_name.toUpperCase().replace(/_/g, ' ') : 'ABILITY';
                const who = d && d.unit_name ? d.unit_name : '';
                EventBus.emit('toast:show', { message: `${who ? who + ': ' : ''}${name} ACTIVATED`, type: 'info', duration: 3000 });
            }),
            EventBus.on('ability:expired', (d) => {
                const name = d && d.ability_name ? d.ability_name.toUpperCase().replace(/_/g, ' ') : 'ABILITY';
                EventBus.emit('toast:show', { message: `${name} expired`, type: 'info', duration: 2000 });
            }),
            EventBus.on('npc:thought', (d) => {
                // NPC thoughts surfaced as subtle toast (not intrusive)
                if (d && d.text && d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    const name = (unit && unit.name) ? unit.name : d.unit_id;
                    EventBus.emit('toast:show', { message: `${name}: "${d.text}"`, type: 'npc', duration: 5000 });
                }
            }),
            EventBus.on('npc:alliance_change', (d) => {
                const who = d && d.unit_name ? d.unit_name : 'NPC';
                const to = d && d.new_alliance ? d.new_alliance : '?';
                EventBus.emit('toast:show', { message: `${who} changed alliance to ${to}`, type: 'alert', duration: 3000 });
            })
        );

        // Refresh dashboard every 2 seconds during active play
        const dashboardInterval = setInterval(refreshDashboard, 2000);
        panel._unsubs.push(() => clearInterval(dashboardInterval));

        // Apply current state
        if (phaseEl) phaseEl.textContent = (TritiumStore.game.phase || 'IDLE').toUpperCase();
        if (waveEl) waveEl.textContent = `${TritiumStore.game.wave}/${TritiumStore.game.totalWaves}`;
        if (scoreEl) scoreEl.textContent = TritiumStore.game.score || 0;
        if (elimsEl) elimsEl.textContent = TritiumStore.game.eliminations || 0;
        updateVisibility();
        // Initial dashboard render
        refreshDashboard();

        // Button handlers (with double-click protection)
        function guardClick(btn, handler) {
            if (!btn) return;
            btn.addEventListener('click', async () => {
                if (btn.disabled) return;
                btn.disabled = true;
                try {
                    await handler();
                } finally {
                    btn.disabled = false;
                }
            });
        }

        guardClick(beginBtn, async () => {
            try {
                const resp = await fetch('/api/game/begin', { method: 'POST' });
                const data = await resp.json();
                if (data.error) console.warn('[GAME] Begin war error:', data.error);
            } catch (e) {
                console.error('[GAME] Begin war failed:', e);
            }
        });

        guardClick(spawnBtn, async () => {
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

        guardClick(resetBtn, async () => {
            try {
                await fetch('/api/game/reset', { method: 'POST' });
                if (typeof warCombatReset === 'function') warCombatReset();
                // Reset combat tracker on manual reset
                tracker.reset();
                _previousMorale = 1.0;
                _waveHostileTotal = 0;
                _waveStartTime = 0;
                refreshDashboard();
            } catch (e) {
                console.error('[GAME] Reset failed:', e);
            }
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class (includes clearInterval for dashboard)
    },
};
