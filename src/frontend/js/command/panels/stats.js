// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Battle Stats Panel
// Live during-battle stats: per-unit leaderboard, accuracy, damage, sparkline.
// Polls /api/game/stats every 3 seconds during active game phases.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

// ============================================================
// Pure helper functions -- exposed via window.BattleStatsHelpers
// ============================================================

/**
 * Format a ratio (0..1) as a percentage string.
 * @param {number} ratio 0..1
 * @returns {string} e.g. "85%"
 */
function formatAccuracy(ratio) {
    const r = typeof ratio === 'number' && !isNaN(ratio) ? ratio : 0;
    return `${Math.round(r * 100)}%`;
}

/**
 * Format a number with thousands separators.
 * @param {number} num
 * @returns {string} e.g. "1,234"
 */
function formatDamage(num) {
    const n = typeof num === 'number' && !isNaN(num) ? Math.round(num) : 0;
    return n.toLocaleString('en-US');
}

/**
 * Return a CSS color based on accuracy threshold.
 * Green >= 50%, amber >= 25%, red < 25%.
 * @param {number} ratio 0..1
 * @returns {string} hex color
 */
function accuracyColor(ratio) {
    const r = typeof ratio === 'number' && !isNaN(ratio) ? ratio : 0;
    if (r >= 0.50) return '#05ffa1';
    if (r >= 0.25) return '#fcee0a';
    return '#ff2a6d';
}

/**
 * Build HTML for a single stat card.
 * @param {string} label
 * @param {string} value
 * @param {string} color CSS color
 * @returns {string}
 */
function buildStatCardHTML(label, value, color) {
    return `<div class="bstats-card">` +
        `<div class="bstats-card-value" style="color:${color || '#00f0ff'}">${_esc(String(value))}</div>` +
        `<div class="bstats-card-label">${_esc(String(label))}</div>` +
        `</div>`;
}

/**
 * Build HTML for the per-unit leaderboard table.
 * Filters to friendly units only, sorted by kills descending.
 * @param {Array} units - array of unit stat objects from /api/game/stats
 * @returns {string}
 */
function buildLeaderboardHTML(units) {
    if (!units || units.length === 0) {
        return '<div class="bstats-table"><div class="bstats-empty">No unit data</div></div>';
    }

    // Filter to friendly only
    const friendlies = units.filter(u => u.alliance === 'friendly');
    if (friendlies.length === 0) {
        return '<div class="bstats-table"><div class="bstats-empty">No friendly units</div></div>';
    }

    // Sort by kills descending
    const sorted = [...friendlies].sort((a, b) => (b.kills || 0) - (a.kills || 0));

    let rows = '';
    sorted.forEach((u, i) => {
        const rank = i + 1;
        const mvpBadge = rank === 1 ? '<span class="bstats-mvp-badge">*</span>' : '';
        const shotsFired = typeof u.shots_fired === 'number' ? u.shots_fired : 0;
        const shotsHit = typeof u.shots_hit === 'number' ? u.shots_hit : 0;
        const acc = typeof u.accuracy === 'number'
            ? formatAccuracy(u.accuracy)
            : (shotsFired > 0 ? formatAccuracy(shotsHit / shotsFired) : '0%');
        const dmg = formatDamage(u.damage_dealt || 0);
        const rowOpacity = i % 2 === 0 ? '1' : '0.75';
        rows += `<tr style="opacity:${rowOpacity}">` +
            `<td class="bstats-rank">${rank}${mvpBadge}</td>` +
            `<td class="bstats-name">${_esc(u.name || u.target_id || 'Unit')}</td>` +
            `<td class="bstats-kills">${u.kills || 0}</td>` +
            `<td class="bstats-acc">${acc}</td>` +
            `<td class="bstats-dmg">${dmg}</td>` +
            `</tr>`;
    });

    return `<table class="bstats-table">` +
        `<thead><tr>` +
        `<th>RANK</th><th>NAME</th><th>KILLS</th><th>ACC%</th><th>DAMAGE</th>` +
        `</tr></thead>` +
        `<tbody>${rows}</tbody>` +
        `</table>`;
}

/**
 * Build SVG polyline points string for the elimination sparkline.
 * X-axis: game time. Y-axis: cumulative eliminations (inverted for SVG).
 * @param {Array} events - array of { time: number, alliance: string }
 * @param {number} width SVG width
 * @param {number} height SVG height
 * @returns {string} space-separated x,y pairs for SVG polyline points
 */
function buildSparklinePoints(events, width, height) {
    if (!events || events.length === 0) {
        return `0,${height} ${width},${height}`;
    }

    const maxTime = Math.max(...events.map(e => e.time || 0), 1);
    let cumulative = 0;
    const maxElims = events.length;

    // Start at origin (bottom-left)
    const points = [`0,${height}`];

    // Sort events by time
    const sorted = [...events].sort((a, b) => (a.time || 0) - (b.time || 0));

    for (const evt of sorted) {
        cumulative += 1;
        const x = Math.round(((evt.time || 0) / maxTime) * width);
        const y = Math.round(height - (cumulative / maxElims) * height);
        points.push(`${x},${y}`);
    }

    return points.join(' ');
}

// Expose helpers on window for testing and cross-module access
if (typeof window !== 'undefined') {
    window.BattleStatsHelpers = {
        formatAccuracy,
        formatDamage,
        accuracyColor,
        buildStatCardHTML,
        buildLeaderboardHTML,
        buildSparklinePoints,
    };
}

// ============================================================
// Panel Definition
// ============================================================

export const BattleStatsPanelDef = {
    id: 'battle-stats',
    title: 'BATTLE STATS',
    defaultPosition: { x: 16, y: 580 },
    defaultSize: { w: 380, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'bstats-panel-inner';
        el.innerHTML = `
            <div class="bstats-header" data-section="header">
                ${buildStatCardHTML('ACCURACY', '--', '#00f0ff')}
                ${buildStatCardHTML('TOTAL DAMAGE', '--', '#00f0ff')}
                ${buildStatCardHTML('FRIENDLIES LOST', '0', '#05ffa1')}
            </div>
            <div class="bstats-leaderboard" data-section="leaderboard">
                <div class="bstats-section-label">UNIT LEADERBOARD</div>
                <div data-bind="leaderboard-body"></div>
            </div>
            <div class="bstats-sparkline-section" data-section="sparkline">
                <div class="bstats-section-label">ELIMINATION TIMELINE</div>
                <svg class="bstats-sparkline" viewBox="0 0 340 50" preserveAspectRatio="none">
                    <polyline class="bstats-sparkline-friendly" points="0,50 340,50" fill="none" stroke="#05ffa1" stroke-width="1.5"/>
                    <polyline class="bstats-sparkline-hostile" points="0,50 340,50" fill="none" stroke="#ff2a6d" stroke-width="1.5" stroke-dasharray="3,2"/>
                </svg>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const headerEl = bodyEl.querySelector('[data-section="header"]');
        const leaderboardBody = bodyEl.querySelector('[data-bind="leaderboard-body"]');
        const friendlyLine = bodyEl.querySelector('.bstats-sparkline-friendly');
        const hostileLine = bodyEl.querySelector('.bstats-sparkline-hostile');

        // Elimination events collected during the game
        let _friendlyElimEvents = [];   // hostile kills (we killed them)
        let _hostileElimEvents = [];    // friendly losses (they killed us)
        let _gameStartTime = 0;
        let _pollInterval = null;

        function _isActivePhase() {
            const phase = TritiumStore.game.phase;
            return phase === 'active' || phase === 'wave_complete';
        }

        /**
         * Fetch stats from /api/game/stats and update the panel.
         */
        async function pollStats(force = false) {
            if (!force && !_isActivePhase()) return;

            try {
                const resp = await fetch('/api/game/stats');
                if (!resp.ok) return;
                const data = await resp.json();
                renderStats(data);
            } catch (e) {
                // Network error -- silently skip this poll cycle
            }
        }

        /**
         * Render stats data into the panel DOM.
         * @param {Object} data - response from /api/game/stats
         */
        function renderStats(data) {
            const summary = data.summary || {};
            const units = data.units || [];

            // Header stat cards
            if (headerEl) {
                const accColor = accuracyColor(summary.overall_accuracy || 0);
                const accVal = formatAccuracy(summary.overall_accuracy || 0);
                const dmgVal = formatDamage(summary.total_damage_dealt || 0);

                // Count friendly losses
                const friendlyLost = units.filter(u =>
                    u.alliance === 'friendly' && u.deaths > 0
                ).length;
                const lostColor = friendlyLost > 0 ? '#ff2a6d' : '#05ffa1';

                headerEl.innerHTML =
                    buildStatCardHTML('ACCURACY', accVal, accColor) +
                    buildStatCardHTML('TOTAL DAMAGE', dmgVal, '#00f0ff') +
                    buildStatCardHTML('FRIENDLIES LOST', String(friendlyLost), lostColor);
            }

            // Leaderboard
            if (leaderboardBody) {
                leaderboardBody.innerHTML = buildLeaderboardHTML(units);
            }

            // Sparkline (use cumulative eliminations from wave stats or unit kills)
            if (friendlyLine) {
                const friendlyPoints = buildSparklinePoints(_friendlyElimEvents, 340, 50);
                friendlyLine.setAttribute('points', friendlyPoints);
            }
            if (hostileLine) {
                const hostilePoints = buildSparklinePoints(_hostileElimEvents, 340, 50);
                hostileLine.setAttribute('points', hostilePoints);
            }
        }

        // Listen for elimination events to build sparkline data
        const onElimination = (data) => {
            const elapsed = _gameStartTime > 0 ? (Date.now() - _gameStartTime) / 1000 : 0;
            if (data && data.target_alliance === 'hostile') {
                _friendlyElimEvents.push({ time: elapsed, alliance: 'hostile' });
            } else {
                _hostileElimEvents.push({ time: elapsed, alliance: 'friendly' });
            }
        };
        EventBus.on('combat:elimination', onElimination);
        panel._unsubs.push(() => EventBus.off('combat:elimination', onElimination));

        // Track game state for sparkline timing
        const onGameState = (data) => {
            if (data && (data.state === 'active' || data === 'active')) {
                _gameStartTime = Date.now();
                _friendlyElimEvents = [];
                _hostileElimEvents = [];
            }
        };
        EventBus.on('game:state', onGameState);
        panel._unsubs.push(() => EventBus.off('game:state', onGameState));

        // Subscribe to phase changes to start/stop polling
        panel._unsubs.push(
            TritiumStore.on('game.phase', (phase) => {
                if (phase === 'active' || phase === 'wave_complete') {
                    if (!_pollInterval) {
                        pollStats(); // Immediate fetch
                        _pollInterval = setInterval(pollStats, 3000);
                    }
                } else {
                    if (_pollInterval) {
                        clearInterval(_pollInterval);
                        _pollInterval = null;
                    }
                    // One last fetch on game over to show final stats
                    if (phase === 'victory' || phase === 'defeat') {
                        pollStats(true);
                    }
                }
            })
        );

        // If game is already active on mount, start polling immediately
        if (_isActivePhase()) {
            pollStats();
            _pollInterval = setInterval(pollStats, 3000);
        }

        // Cleanup polling on unmount
        panel._unsubs.push(() => {
            if (_pollInterval) {
                clearInterval(_pollInterval);
                _pollInterval = null;
            }
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class (includes clearInterval for polling)
    },
};
