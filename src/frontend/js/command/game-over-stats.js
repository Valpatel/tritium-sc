// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC -- Game Over after-action stats rendering helpers
 *
 * Pure functions that build HTML fragments for the game-over overlay.
 * No DOM manipulation -- callers set innerHTML on the appropriate elements.
 *
 * Used by:
 *   - main.js showGameOver() for the full-page overlay
 *   - war-hud.js warHudShowGameOver() for the canvas overlay
 */

// ============================================================
// Formatting helpers
// ============================================================

/**
 * Format accuracy ratio (0-1) as percentage string.
 * @param {number|null} acc - Accuracy ratio (0.0 to 1.0)
 * @returns {string} e.g. "85%"
 */
function goFormatAccuracy(acc) {
    if (acc == null || isNaN(acc)) return '0%';
    return Math.round(acc * 100) + '%';
}

/**
 * Format damage number with thousands separator, rounded to integer.
 * @param {number|null} dmg
 * @returns {string}
 */
function goFormatDamage(dmg) {
    if (dmg == null || isNaN(dmg)) return '0';
    return Math.round(dmg).toLocaleString('en-US');
}

/**
 * Format kill/death ratio.
 * @param {number} kills
 * @param {number} deaths
 * @returns {string} e.g. "2.50"
 */
function goFormatKD(kills, deaths) {
    if (deaths > 0) return (kills / deaths).toFixed(2);
    return (kills || 0).toFixed(2);
}

/**
 * Determine unit status label based on health and deaths.
 * @param {number} healthRemaining
 * @param {number} deaths
 * @returns {string} "SURVIVED" or "ELIMINATED"
 */
function goUnitStatusLabel(healthRemaining, deaths) {
    if (typeof healthRemaining === 'number' && healthRemaining > 0) return 'SURVIVED';
    if (healthRemaining === undefined || healthRemaining === null) {
        return deaths > 0 ? 'ELIMINATED' : 'SURVIVED';
    }
    return 'ELIMINATED';
}

/**
 * Get color for unit status label.
 * @param {string} status - "SURVIVED" or "ELIMINATED"
 * @returns {string} hex color
 */
function goUnitStatusColor(status) {
    if (status === 'SURVIVED') return '#05ffa1';
    if (status === 'ELIMINATED') return '#ff2a6d';
    return '#888888';
}

// ============================================================
// HTML builders
// ============================================================

/**
 * Build MVP spotlight HTML.
 * @param {object|null} mvp - MVP data: { name, kills, accuracy, asset_type }
 * @returns {string} HTML string
 */
function goBuildMvpSpotlightHtml(mvp) {
    if (!mvp) return '';
    const name = _goEsc(mvp.name || 'Unknown');
    const kills = mvp.kills || 0;
    const acc = goFormatAccuracy(mvp.accuracy);
    const type = _goEsc(mvp.asset_type || 'unit');

    return `<div class="go-mvp-spotlight">
        <div class="go-mvp-label mono">MOST VALUABLE UNIT</div>
        <div class="go-mvp-name">${name}</div>
        <div class="go-mvp-type mono">${type}</div>
        <div class="go-mvp-details">
            <span class="go-mvp-kills">${kills} KILLS</span>
            <span class="go-mvp-sep">//</span>
            <span class="go-mvp-acc">${acc} ACCURACY</span>
        </div>
    </div>`;
}

/**
 * Build combat stats grid HTML.
 * @param {object|null} summary - Summary data from /api/game/stats/summary
 * @returns {string} HTML string
 */
function goBuildCombatStatsHtml(summary) {
    if (!summary) return '';

    const acc = goFormatAccuracy(summary.overall_accuracy);
    const dmg = goFormatDamage(summary.total_damage_dealt);
    const kills = summary.total_kills || 0;
    const deaths = summary.total_deaths || 0;
    const shotsFired = summary.total_shots_fired || 0;
    const shotsHit = summary.total_shots_hit || 0;

    return `<div class="go-combat-stats">
        <div class="go-stat-card">
            <span class="go-stat-card-value">${acc}</span>
            <span class="go-stat-card-label mono">ACCURACY</span>
        </div>
        <div class="go-stat-card">
            <span class="go-stat-card-value">${dmg}</span>
            <span class="go-stat-card-label mono">DAMAGE DEALT</span>
        </div>
        <div class="go-stat-card">
            <span class="go-stat-card-value">${kills}</span>
            <span class="go-stat-card-label mono">TOTAL KILLS</span>
        </div>
        <div class="go-stat-card">
            <span class="go-stat-card-value">${goFormatKD(kills, deaths)}</span>
            <span class="go-stat-card-label mono">K/D RATIO</span>
        </div>
        <div class="go-stat-card">
            <span class="go-stat-card-value">${shotsFired}</span>
            <span class="go-stat-card-label mono">SHOTS FIRED</span>
        </div>
        <div class="go-stat-card">
            <span class="go-stat-card-value">${shotsHit}</span>
            <span class="go-stat-card-label mono">SHOTS HIT</span>
        </div>
    </div>`;
}

/**
 * Build unit performance table HTML.
 * Filters to only show friendly units (excludes hostiles).
 * @param {Array|null} units - Array of unit stats from /api/game/stats
 * @returns {string} HTML string
 */
function goBuildUnitTableHtml(units) {
    if (!units || units.length === 0) return '';

    // Filter to friendly units only (exclude hostile/neutral)
    const friendlies = units.filter(u => u.alliance !== 'hostile');
    if (friendlies.length === 0) return '';

    const rows = friendlies.map(u => {
        const name = _goEsc(u.name || u.target_id || 'Unknown');
        const type = _goEsc(u.asset_type || 'unit');
        const kills = u.kills || 0;
        const acc = goFormatAccuracy(u.accuracy);
        const dmg = goFormatDamage(u.damage_dealt);
        const status = goUnitStatusLabel(u.health_remaining, u.deaths || 0);
        const statusColor = goUnitStatusColor(status);
        return `<tr>
            <td class="go-unit-name">${name}</td>
            <td class="go-unit-type mono">${type}</td>
            <td class="go-unit-kills">${kills}</td>
            <td class="go-unit-acc">${acc}</td>
            <td class="go-unit-dmg">${dmg}</td>
            <td class="go-unit-status" style="color:${statusColor}">${status}</td>
        </tr>`;
    }).join('');

    return `<table class="go-unit-table">
        <thead>
            <tr>
                <th>UNIT</th>
                <th>TYPE</th>
                <th>KILLS</th>
                <th>ACC</th>
                <th>DMG</th>
                <th>STATUS</th>
            </tr>
        </thead>
        <tbody>${rows}</tbody>
    </table>`;
}

/**
 * Build MVP line for the war-hud canvas overlay.
 * Simpler than the full spotlight -- just name + kills.
 * @param {object|null} mvp
 * @returns {string} HTML string
 */
function goBuildWarHudMvpHtml(mvp) {
    if (!mvp) return '';
    const name = _goEsc(mvp.name || 'Unknown');
    const kills = mvp.kills || 0;
    return `<div class="war-gameover-mvp">MVP: ${name} -- ${kills} KILLS</div>`;
}

// ============================================================
// Internal utility
// ============================================================

function _goEsc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

// ============================================================
// Expose for testing (global script) and module usage
// ============================================================

if (typeof window !== 'undefined') {
    window.goFormatAccuracy = goFormatAccuracy;
    window.goFormatDamage = goFormatDamage;
    window.goFormatKD = goFormatKD;
    window.goUnitStatusLabel = goUnitStatusLabel;
    window.goUnitStatusColor = goUnitStatusColor;
    window.goBuildMvpSpotlightHtml = goBuildMvpSpotlightHtml;
    window.goBuildCombatStatsHtml = goBuildCombatStatsHtml;
    window.goBuildUnitTableHtml = goBuildUnitTableHtml;
    window.goBuildWarHudMvpHtml = goBuildWarHudMvpHtml;
}
