/**
 * TRITIUM-SC War Room — Game HUD
 * Elimination feed, wave banners, countdown, score, BEGIN WAR button, game over screen
 *
 * HTML overlay elements positioned over the canvas. Managed entirely here;
 * war.js calls our update functions from WebSocket event handlers.
 */

// ============================================================
// HUD state
// ============================================================

const _hudState = {
    score: 0,
    displayScore: 0, // for counting-up animation
    eliminations: 0,
    wave: 0,
    totalWaves: 10,
    gameState: 'idle', // idle | setup | countdown | active | wave_complete | game_over
    eliminationFeed: [],      // { text, interceptorColor, targetColor, time }
    announcements: [], // queued amy announcements
    countdownTimer: null,
    waveBannerTimer: null,
};

// ============================================================
// Audio helpers (reuse war.js audioCtx pattern)
// ============================================================

function _hudGetAudioCtx() {
    if (typeof warState !== 'undefined' && warState.audioCtx) return warState.audioCtx;
    return null;
}

function _hudPlayTone(freq, type, duration, volume) {
    const ctx = _hudGetAudioCtx();
    if (!ctx) return;
    try {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = type || 'sine';
        osc.frequency.setValueAtTime(freq, ctx.currentTime);
        gain.gain.setValueAtTime(volume || 0.06, ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0, ctx.currentTime + (duration || 0.2));
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + (duration || 0.2));
    } catch (e) { /* audio error, non-fatal */ }
}

// ============================================================
// Game state updates
// ============================================================

function warHudUpdateGameState(data) {
    if (!data) return;
    if (data.state !== undefined) _hudState.gameState = data.state;
    if (data.wave !== undefined) _hudState.wave = data.wave;
    if (data.total_waves !== undefined) _hudState.totalWaves = data.total_waves;
    if (data.score !== undefined) _hudState.score = data.score;
    if (data.total_eliminations !== undefined) _hudState.eliminations = data.total_eliminations;
    else if (data.total_kills !== undefined) _hudState.eliminations = data.total_kills;

    _updateScoreDisplay();

    // Show/hide BEGIN WAR button based on state
    if (_hudState.gameState === 'setup' || _hudState.gameState === 'idle') {
        warHudShowBeginWarButton();
    } else {
        warHudHideBeginWarButton();
    }

    // Trigger countdown overlay when entering countdown state
    if (_hudState.gameState === 'countdown') {
        warHudShowCountdown(data.countdown || 5);
    }

    // Show score panel during active play
    const scoreEl = document.getElementById('war-score');
    if (scoreEl) {
        scoreEl.style.display = (_hudState.gameState === 'active' || _hudState.gameState === 'wave_complete') ? 'block' : 'none';
    }
}

// ============================================================
// Countdown overlay
// ============================================================

function warHudShowCountdown(seconds) {
    const el = document.getElementById('war-countdown');
    if (!el) return;

    let count = Math.max(1, Math.round(seconds));
    el.style.display = 'flex';
    el.classList.add('active');

    function tick() {
        if (count > 0) {
            el.textContent = count;
            el.className = 'war-countdown active war-countdown-pulse';
            _hudPlayTone(440 - count * 40, 'sine', 0.15, 0.08);

            // Re-trigger animation
            void el.offsetWidth;
            el.classList.add('war-countdown-pulse');

            count--;
            _hudState.countdownTimer = setTimeout(tick, 1000);
        } else {
            el.textContent = 'ENGAGE!';
            el.className = 'war-countdown active war-countdown-engage';
            _hudPlayTone(880, 'sine', 0.4, 0.1);

            setTimeout(() => {
                el.style.display = 'none';
                el.classList.remove('active');
            }, 1200);
        }
    }

    tick();
}

// ============================================================
// Wave banner
// ============================================================

function warHudShowWaveBanner(waveNum, waveName, hostileCount) {
    const el = document.getElementById('war-wave-banner');
    if (!el) return;

    const name = waveName ? `: ${waveName.toUpperCase()}` : '';
    const hostiles = hostileCount ? ` -- ${hostileCount} HOSTILES INCOMING` : '';
    el.innerHTML = `<div class="war-wave-title">WAVE ${waveNum}${name}</div>
                     <div class="war-wave-sub">${hostiles}</div>`;
    el.style.display = 'block';
    el.className = 'war-wave-banner war-wave-slide-in';

    _hudPlayTone(220, 'sawtooth', 0.3, 0.05);
    setTimeout(() => _hudPlayTone(330, 'sawtooth', 0.2, 0.04), 150);

    clearTimeout(_hudState.waveBannerTimer);
    _hudState.waveBannerTimer = setTimeout(() => {
        el.className = 'war-wave-banner war-wave-slide-out';
        setTimeout(() => { el.style.display = 'none'; }, 500);
    }, 3000);
}

function warHudShowWaveComplete(waveNum, eliminations, scoreBonus) {
    const el = document.getElementById('war-wave-banner');
    if (!el) return;

    el.innerHTML = `<div class="war-wave-title war-wave-complete-text">WAVE ${waveNum} COMPLETE</div>
                     <div class="war-wave-sub">${eliminations || 0} NEUTRALIZED -- +${scoreBonus || 0} PTS</div>`;
    el.style.display = 'block';
    el.className = 'war-wave-banner war-wave-complete war-wave-slide-in';

    _hudPlayTone(440, 'sine', 0.15, 0.06);
    setTimeout(() => _hudPlayTone(660, 'sine', 0.15, 0.06), 120);
    setTimeout(() => _hudPlayTone(880, 'sine', 0.3, 0.08), 240);

    clearTimeout(_hudState.waveBannerTimer);
    _hudState.waveBannerTimer = setTimeout(() => {
        el.className = 'war-wave-banner war-wave-complete war-wave-slide-out';
        setTimeout(() => { el.style.display = 'none'; }, 500);
    }, 3500);
}

// ============================================================
// Elimination feed
// ============================================================

function warHudAddEliminationFeedEntry(data) {
    if (!data) return;

    const interceptor = data.interceptor_name || data.killer_name || data.interceptor_id || 'Unit';
    const target = data.target_name || data.hostile_name || data.hostile_id || 'Hostile';
    const interceptorAlliance = (data.interceptor_alliance || data.killer_alliance || 'friendly').toLowerCase();
    const targetAlliance = (data.target_alliance || data.victim_alliance || 'hostile').toLowerCase();

    const interceptorColor = interceptorAlliance === 'friendly' ? '#00f0ff' : '#ff2a6d';
    const targetColor = targetAlliance === 'hostile' ? '#ff2a6d' : '#00f0ff';

    _hudState.eliminationFeed.push({
        interceptor,
        target,
        interceptorColor,
        targetColor,
        weapon: data.weapon || data.method || 'nerf_dart',
        time: Date.now(),
    });

    // Keep max 6
    if (_hudState.eliminationFeed.length > 6) _hudState.eliminationFeed.shift();

    _renderEliminationFeed();
}

// Backward compat alias
var warHudAddKillFeedEntry = warHudAddEliminationFeedEntry;

function _renderEliminationFeed() {
    const el = document.getElementById('war-elimination-feed') || document.getElementById('war-kill-feed');
    if (!el) return;

    const now = Date.now();
    // Remove entries older than 8s
    _hudState.eliminationFeed = _hudState.eliminationFeed.filter(k => now - k.time < 8000);

    el.innerHTML = _hudState.eliminationFeed.map(k => {
        const age = now - k.time;
        const opacity = age < 6000 ? 1 : Math.max(0, 1 - (age - 6000) / 2000);
        return `<div class="war-elimination-entry" style="opacity: ${opacity}">
            <span style="color: ${k.interceptorColor}">${_escHtml(k.interceptor)}</span>
            <span class="war-elimination-arrow">&gt;&gt;</span>
            <span style="color: ${k.targetColor}">${_escHtml(k.target)}</span>
        </div>`;
    }).join('');
}

// Periodically clean up faded elimination feed entries
setInterval(() => {
    if (_hudState.eliminationFeed.length > 0) _renderEliminationFeed();
}, 1000);

// ============================================================
// Score display
// ============================================================

function _updateScoreDisplay() {
    const el = document.getElementById('war-score');
    if (!el) return;

    // Animate score counting up
    if (_hudState.displayScore < _hudState.score) {
        const diff = _hudState.score - _hudState.displayScore;
        _hudState.displayScore += Math.max(1, Math.ceil(diff * 0.15));
        if (_hudState.displayScore > _hudState.score) _hudState.displayScore = _hudState.score;
    }

    el.innerHTML = `
        <div class="war-score-row"><span class="war-score-label">SCORE</span><span class="war-score-value">${_formatNum(_hudState.displayScore)}</span></div>
        <div class="war-score-row"><span class="war-score-label">ELIMS</span><span class="war-score-value war-score-elims">${_hudState.eliminations}</span></div>
        <div class="war-score-row"><span class="war-score-label">WAVE</span><span class="war-score-value">${_hudState.wave}/${_hudState.totalWaves}</span></div>
    `;
}

// Keep animating score count-up
setInterval(() => {
    if (_hudState.displayScore < _hudState.score) _updateScoreDisplay();
}, 50);

// ============================================================
// BEGIN WAR button
// ============================================================

function warHudShowBeginWarButton() {
    const el = document.getElementById('war-begin-btn');
    if (el) {
        el.style.display = 'block';
        el.onclick = _onBeginWar;
    }
}

function warHudHideBeginWarButton() {
    const el = document.getElementById('war-begin-btn');
    if (el) el.style.display = 'none';
}

function _onBeginWar() {
    warHudHideBeginWarButton();

    fetch('/api/game/begin', { method: 'POST' })
        .then(r => {
            if (!r.ok) throw new Error('Failed to begin war');
            return r.json();
        })
        .then(data => {
            if (data && data.countdown) {
                warHudShowCountdown(data.countdown);
            } else {
                warHudShowCountdown(5);
            }
        })
        .catch(err => {
            console.error('[WAR-HUD] Begin war failed:', err);
            // Show countdown anyway for visual feedback
            warHudShowCountdown(5);
        });
}

// ============================================================
// Game over screen
// ============================================================

function warHudShowGameOver(result, score, waves, eliminations) {
    const el = document.getElementById('war-game-over');
    if (!el) return;

    const isVictory = (result || '').toLowerCase() === 'victory';
    const title = isVictory ? 'NEIGHBORHOOD SECURED' : 'NEIGHBORHOOD OVERRUN';
    const titleColor = isVictory ? '#05ffa1' : '#ff2a6d';
    const resultText = isVictory ? 'VICTORY' : 'DEFEAT';

    el.innerHTML = `
        <div class="war-gameover-content">
            <div class="war-gameover-result" style="color: ${titleColor}">${resultText}</div>
            <div class="war-gameover-title" style="color: ${titleColor}">${title}</div>
            <div class="war-gameover-stats">
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value">${_formatNum(score || 0)}</div>
                    <div class="war-gameover-stat-label">SCORE</div>
                </div>
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value">${eliminations || 0}</div>
                    <div class="war-gameover-stat-label">ELIMINATIONS</div>
                </div>
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value">${waves || 0}</div>
                    <div class="war-gameover-stat-label">WAVES</div>
                </div>
            </div>
            <button class="war-gameover-btn" onclick="warHudPlayAgain()">PLAY AGAIN</button>
        </div>
    `;
    el.style.display = 'flex';
    el.className = 'war-game-over war-gameover-fade-in';

    // Dramatic sound
    if (isVictory) {
        _hudPlayTone(440, 'sine', 0.2, 0.06);
        setTimeout(() => _hudPlayTone(554, 'sine', 0.2, 0.06), 150);
        setTimeout(() => _hudPlayTone(660, 'sine', 0.4, 0.08), 300);
    } else {
        _hudPlayTone(330, 'sawtooth', 0.4, 0.05);
        setTimeout(() => _hudPlayTone(220, 'sawtooth', 0.6, 0.05), 300);
    }
}

function warHudPlayAgain() {
    const el = document.getElementById('war-game-over');
    if (el) el.style.display = 'none';

    fetch('/api/game/reset', { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .catch(err => console.error('[WAR-HUD] Reset failed:', err));

    // Reset local state
    _hudState.score = 0;
    _hudState.displayScore = 0;
    _hudState.eliminations = 0;
    _hudState.wave = 0;
    _hudState.gameState = 'idle';
    _hudState.eliminationFeed = [];
    _renderEliminationFeed();
    _updateScoreDisplay();

    // Reset combat effects
    if (typeof warCombatReset === 'function') warCombatReset();

    // Reset warState selections and effects
    if (typeof warState !== 'undefined') {
        warState.selectedTargets = [];
        warState.effects = [];
        warState.dispatchArrows = [];
        warState.stats.eliminations = 0;
        warState.stats.breaches = 0;
        warState.stats.dispatches = 0;
    }

    // Re-show BEGIN button after short delay (wait for backend reset)
    setTimeout(() => warHudShowBeginWarButton(), 500);
}

// ============================================================
// Amy announcement toast (enhanced)
// ============================================================

const _announcementQueue = [];
let _announcementActive = false;

function warHudShowAmyAnnouncement(text, category) {
    if (!text) return;
    _announcementQueue.push({ text, category: category || 'tactical' });
    _processAnnouncementQueue();
}

function _processAnnouncementQueue() {
    if (_announcementActive || _announcementQueue.length === 0) return;
    _announcementActive = true;

    const item = _announcementQueue.shift();
    const el = document.getElementById('war-amy-toast');
    if (!el) { _announcementActive = false; return; }

    // Style based on category
    el.className = 'war-announcement';
    el.classList.add(`war-announce-${item.category}`);
    el.textContent = item.text;
    el.style.opacity = '1';

    const holdTime = item.category === 'wave' ? 3000 : (item.category === 'elimination' || item.category === 'kill' ? 2000 : 4000);

    setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => {
            _announcementActive = false;
            _processAnnouncementQueue();
        }, 400);
    }, holdTime);
}

// ============================================================
// Utility
// ============================================================

function _escHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

function _formatNum(n) {
    return n.toLocaleString('en-US');
}

// ============================================================
// Expose globally
// ============================================================

window.warHudUpdateGameState = warHudUpdateGameState;
window.warHudShowCountdown = warHudShowCountdown;
window.warHudShowWaveBanner = warHudShowWaveBanner;
window.warHudShowWaveComplete = warHudShowWaveComplete;
window.warHudAddKillFeedEntry = warHudAddKillFeedEntry;
window.warHudShowBeginWarButton = warHudShowBeginWarButton;
window.warHudHideBeginWarButton = warHudHideBeginWarButton;
window.warHudShowGameOver = warHudShowGameOver;
window.warHudPlayAgain = warHudPlayAgain;
window.warHudShowAmyAnnouncement = warHudShowAmyAnnouncement;
