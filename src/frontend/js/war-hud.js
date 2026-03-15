// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
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
    waveHostilesRemaining: 0,  // hostiles still alive in current wave
    waveName: '',              // current wave name from backend
    gameState: 'idle', // idle | setup | countdown | active | wave_complete | game_over
    eliminationFeed: [],      // { text, interceptorColor, targetColor, time }
    announcements: [], // queued amy announcements
    countdownTimer: null,
    countdownStarted: false,
    waveBannerTimer: null,
    loadingMessages: [],       // from scenario generation
    loadingMessageTimer: null,
    bonusObjectives: [],           // [{ name, description, reward, completed }]
    // Mission mode fields
    gameModeType: 'battle',        // battle | civil_unrest | drone_swarm
    infrastructureHealth: 0,
    infrastructureMax: 0,
    civilianHarmCount: 0,
    civilianHarmLimit: 5,
    deEscalationScore: 0,
    weightedTotalScore: 0,
};

// ============================================================
// Utility
// ============================================================

function _hudEscapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text || '');
    return div.innerHTML;
}


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
    if (data.wave_hostiles_remaining !== undefined) _hudState.waveHostilesRemaining = data.wave_hostiles_remaining;
    if (data.wave_name !== undefined) _hudState.waveName = data.wave_name;

    // Mission mode type and mode-specific fields
    if (data.game_mode_type !== undefined) _hudState.gameModeType = data.game_mode_type;
    if (data.infrastructure_health !== undefined) _hudState.infrastructureHealth = data.infrastructure_health;
    if (data.infrastructure_max !== undefined) _hudState.infrastructureMax = data.infrastructure_max;
    if (data.de_escalation_score !== undefined) _hudState.deEscalationScore = data.de_escalation_score;
    if (data.civilian_harm_count !== undefined) _hudState.civilianHarmCount = data.civilian_harm_count;
    if (data.civilian_harm_limit !== undefined) _hudState.civilianHarmLimit = data.civilian_harm_limit;
    if (data.weighted_total_score !== undefined) _hudState.weightedTotalScore = data.weighted_total_score;

    _updateScoreDisplay();

    // Show/hide BEGIN WAR button based on state
    if (_hudState.gameState === 'setup' || _hudState.gameState === 'idle') {
        warHudShowBeginWarButton();
        // Dismiss game-over overlay on reset
        const goEl = document.getElementById('war-game-over');
        if (goEl) goEl.style.display = 'none';
    } else {
        warHudHideBeginWarButton();
    }

    // Trigger countdown overlay ONCE when entering countdown state
    if (_hudState.gameState === 'countdown' && !_hudState.countdownStarted) {
        _hudState.countdownStarted = true;
        warHudShowCountdown(Math.ceil(data.countdown || 5));
        // Auto-open the game HUD panel so combat info is visible
        if (typeof window.panelManager !== 'undefined' && window.panelManager && typeof window.panelManager.open === 'function') {
            window.panelManager.open('game');
        }
    }
    if (_hudState.gameState !== 'countdown') {
        _hudState.countdownStarted = false;
    }

    // Show score panel during active play
    const scoreEl = document.getElementById('war-score');
    if (scoreEl) {
        scoreEl.style.display = (_hudState.gameState === 'active' || _hudState.gameState === 'wave_complete') ? 'block' : 'none';
    }

    // Show standalone wave counter at top-center during active play
    _updateWaveCounter();
}

// ============================================================
// Countdown overlay
// ============================================================

function warHudShowCountdown(seconds) {
    const el = document.getElementById('war-countdown');
    if (!el) return;

    // Clear any existing countdown to prevent double-speed ticking
    if (_hudState.countdownTimer) clearTimeout(_hudState.countdownTimer);
    let count = Math.max(1, Math.round(seconds));
    el.style.display = 'flex';
    el.classList.add('active');

    // Start rotating loading messages if available
    let msgIdx = 0;
    const msgs = _hudState.loadingMessages;
    clearInterval(_hudState.loadingMessageTimer);
    if (msgs.length > 0) {
        _hudState.loadingMessageTimer = setInterval(() => {
            msgIdx = (msgIdx + 1) % msgs.length;
        }, 800);
    }

    function tick() {
        if (count > 0) {
            const msgLine = msgs.length > 0
                ? `<div class="war-countdown-msg">${_hudEscapeHtml(msgs[msgIdx])}</div>`
                : '';
            el.innerHTML = `<div class="war-countdown-number">${count}</div>${msgLine}`;
            el.className = 'war-countdown active war-countdown-pulse';
            _hudPlayTone(440 - count * 40, 'sine', 0.15, 0.08);

            // Re-trigger animation
            void el.offsetWidth;
            el.classList.add('war-countdown-pulse');

            count--;
            _hudState.countdownTimer = setTimeout(tick, 1000);
        } else {
            clearInterval(_hudState.loadingMessageTimer);
            el.innerHTML = '<div class="war-countdown-number">ENGAGE!</div>';
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

/**
 * Set loading messages for display during countdown.
 * Called when a scenario is generated/applied.
 */
function warHudSetLoadingMessages(messages) {
    _hudState.loadingMessages = Array.isArray(messages) ? messages : [];
}

// ============================================================
// Wave banner
// ============================================================

function warHudShowWaveBanner(waveNum, waveName, hostileCount, briefingData) {
    const el = document.getElementById('war-wave-banner');
    if (!el) return;

    const name = waveName ? `: ${_hudEscapeHtml(waveName.toUpperCase())}` : '';
    const hostiles = hostileCount ? ` -- ${hostileCount} HOSTILES INCOMING` : '';

    // Mode-specific wave label and color
    const mode = _hudState.gameModeType;
    let waveLabel = 'WAVE';
    let modeColorClass = 'war-wave-mode-battle';
    if (mode === 'civil_unrest') {
        waveLabel = 'CROWD SURGE';
        modeColorClass = 'war-wave-mode-civil';
    } else if (mode === 'drone_swarm') {
        waveLabel = 'SWARM WAVE';
        modeColorClass = 'war-wave-mode-swarm';
    }

    // Build briefing lines if available
    let briefingHtml = '';
    if (briefingData) {
        if (briefingData.briefing) {
            briefingHtml += `<div class="war-wave-briefing-text">${_hudEscapeHtml(briefingData.briefing)}</div>`;
        }
        if (briefingData.threat_level) {
            const threatClass = briefingData.threat_level === 'heavy' ? 'threat-heavy' :
                               briefingData.threat_level === 'moderate' ? 'threat-moderate' : 'threat-light';
            briefingHtml += `<div class="war-wave-threat ${threatClass}">THREAT: ${_hudEscapeHtml(briefingData.threat_level).toUpperCase()}</div>`;
        }
        if (briefingData.intel) {
            briefingHtml += `<div class="war-wave-intel">${_hudEscapeHtml(briefingData.intel)}</div>`;
        }
    }

    el.innerHTML = `<div class="war-wave-title ${modeColorClass}">${waveLabel} ${waveNum}${name}</div>
                     <div class="war-wave-sub">${hostiles}</div>
                     ${briefingHtml}`;
    el.style.display = 'block';
    el.className = 'war-wave-banner war-wave-slide-in';

    _hudPlayTone(220, 'sawtooth', 0.3, 0.05);
    setTimeout(() => _hudPlayTone(330, 'sawtooth', 0.2, 0.04), 150);

    // Extended display time when briefing is present (5s vs 3s)
    const displayTime = briefingData ? 5000 : 3000;
    clearTimeout(_hudState.waveBannerTimer);
    _hudState.waveBannerTimer = setTimeout(() => {
        el.className = 'war-wave-banner war-wave-slide-out';
        setTimeout(() => { el.style.display = 'none'; }, 500);
    }, displayTime);
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
            <span style="color: ${k.interceptorColor}">${_hudEscapeHtml(k.interceptor)}</span>
            <span class="war-elimination-arrow">&gt;&gt;</span>
            <span style="color: ${k.targetColor}">${_hudEscapeHtml(k.target)}</span>
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

    const mode = _hudState.gameModeType;
    let modeRows = '';

    if (mode === 'drone_swarm') {
        const hp = _hudState.infrastructureHealth || 0;
        const max = _hudState.infrastructureMax || 1;
        const color = hp / max > 0.6 ? '#05ffa1' : hp / max >= 0.3 ? '#fcee0a' : '#ff2a6d';
        modeRows = `
        <div class="war-score-row"><span class="war-score-label">INFRA</span><span class="war-score-value" style="color:${color}">${hp}/${max}</span></div>`;
    } else if (mode === 'civil_unrest') {
        const harmCount = _hudState.civilianHarmCount || 0;
        const harmLimit = _hudState.civilianHarmLimit || 5;
        const harmColor = harmCount >= 4 ? '#ff2a6d' : harmCount >= 3 ? '#ffa500' : '#00f0ff';
        modeRows = `
        <div class="war-score-row"><span class="war-score-label">DE-ESC</span><span class="war-score-value" style="color:#05ffa1">${_formatNum(_hudState.deEscalationScore || 0)}</span></div>
        <div class="war-score-row"><span class="war-score-label">HARM</span><span class="war-score-value" style="color:${harmColor}">${harmCount}/${harmLimit}</span></div>`;
    }

    el.innerHTML = `
        <div class="war-score-row"><span class="war-score-label">SCORE</span><span class="war-score-value">${_formatNum(_hudState.displayScore)}</span></div>
        <div class="war-score-row"><span class="war-score-label">ELIMS</span><span class="war-score-value war-score-elims">${_hudState.eliminations}</span></div>
        <div class="war-score-row"><span class="war-score-label">WAVE</span><span class="war-score-value">${_hudState.wave}/${_hudState.totalWaves}</span></div>${modeRows}
    `;
}

// Keep animating score count-up
setInterval(() => {
    if (_hudState.displayScore < _hudState.score) _updateScoreDisplay();
}, 50);

// ============================================================
// Wave counter (top-center, always visible during battle)
// ============================================================

function _updateWaveCounter() {
    const el = document.getElementById('war-wave-counter');
    if (!el) return;

    const isActive = _hudState.gameState === 'active' || _hudState.gameState === 'wave_complete' || _hudState.gameState === 'countdown';
    if (!isActive) {
        el.style.display = 'none';
        return;
    }

    el.style.display = 'block';
    let text = 'WAVE ' + _hudState.wave + '/' + _hudState.totalWaves;
    // Show hostiles remaining during active wave
    if (_hudState.gameState === 'active' && _hudState.waveHostilesRemaining > 0) {
        text += '  //  ' + _hudState.waveHostilesRemaining + ' HOSTILES';
    } else if (_hudState.gameState === 'wave_complete') {
        text += '  //  CLEARED';
    }
    el.textContent = text;
}

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

function warHudShowGameOver(result, score, waves, eliminations, modeData) {
    const el = document.getElementById('war-game-over');
    if (!el) return;

    const isVictory = (result || '').toLowerCase() === 'victory';
    const mode = (modeData && modeData.game_mode_type) || _hudState.gameModeType || 'battle';

    // Mode-specific titles
    let title, defeatReason;
    if (mode === 'civil_unrest') {
        title = isVictory ? 'ORDER RESTORED' : 'SITUATION ESCALATED';
        defeatReason = !isVictory && modeData && modeData.reason === 'civilian_casualties'
            ? 'TOO MANY CIVILIAN CASUALTIES' : '';
    } else if (mode === 'drone_swarm') {
        title = isVictory ? 'AIRSPACE SECURED' : 'INFRASTRUCTURE DESTROYED';
        defeatReason = !isVictory && modeData && modeData.reason === 'infrastructure_destroyed'
            ? 'CRITICAL INFRASTRUCTURE LOST' : '';
    } else {
        title = isVictory ? 'NEIGHBORHOOD SECURED' : 'NEIGHBORHOOD OVERRUN';
        if (!isVictory && modeData && modeData.reason === 'all_friendlies_eliminated') {
            defeatReason = 'ALL DEFENDERS ELIMINATED';
        } else {
            defeatReason = '';
        }
    }

    const titleColor = isVictory ? '#05ffa1' : '#ff2a6d';
    const resultText = isVictory ? 'VICTORY' : 'DEFEAT';

    // Mode-specific stat rows
    let modeStatsHtml = '';
    if (mode === 'civil_unrest' && modeData) {
        const deesc = modeData.de_escalation_score || _hudState.deEscalationScore || 0;
        const harmCount = modeData.civilian_harm_count !== undefined ? modeData.civilian_harm_count : _hudState.civilianHarmCount;
        const harmLimit = modeData.civilian_harm_limit || _hudState.civilianHarmLimit || 5;
        const weighted = modeData.weighted_total_score || _hudState.weightedTotalScore || 0;
        modeStatsHtml = `
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value" style="color:#05ffa1">${_formatNum(deesc)}</div>
                    <div class="war-gameover-stat-label">DE-ESCALATION</div>
                </div>
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value" style="color:${harmCount >= 4 ? '#ff2a6d' : '#00f0ff'}">${harmCount}/${harmLimit}</div>
                    <div class="war-gameover-stat-label">CIVILIAN HARM</div>
                </div>`;
    } else if (mode === 'drone_swarm' && modeData) {
        const infraHp = modeData.infrastructure_health !== undefined ? modeData.infrastructure_health : _hudState.infrastructureHealth;
        const infraMax = modeData.infrastructure_max || _hudState.infrastructureMax || 1000;
        const infraColor = infraHp <= 0 ? '#ff2a6d' : infraHp / infraMax > 0.6 ? '#05ffa1' : '#fcee0a';
        modeStatsHtml = `
                <div class="war-gameover-stat">
                    <div class="war-gameover-stat-value" style="color:${infraColor}">${infraHp}/${infraMax}</div>
                    <div class="war-gameover-stat-label">INFRASTRUCTURE</div>
                </div>`;
    }

    const defeatReasonHtml = defeatReason
        ? `<div class="war-gameover-reason" style="color:#ffa500;margin:8px 0">${defeatReason}</div>`
        : '';

    // Bonus objectives summary
    let bonusHtml = '';
    if (_hudState.bonusObjectives && _hudState.bonusObjectives.length > 0) {
        const lines = _hudState.bonusObjectives.map(o => {
            const marker = o.completed ? '\u2713' : '\u2717';
            const color = o.completed ? '#05ffa1' : '#666666';
            const rewardText = o.completed ? ` +${_formatNum(o.reward)}` : '';
            return `<div style="font-family:var(--font-mono,'monospace');font-size:0.5rem;color:${color};margin:2px 0">${marker} ${_hudEscapeHtml(o.name)}${rewardText}</div>`;
        }).join('');
        bonusHtml = `<div style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);text-align:center">${lines}</div>`;
    }

    el.innerHTML = `
        <div class="war-gameover-content">
            <div class="war-gameover-result" style="color: ${titleColor}">${resultText}</div>
            <div class="war-gameover-title" style="color: ${titleColor}">${title}</div>
            ${defeatReasonHtml}
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
                </div>${modeStatsHtml}
            </div>${bonusHtml}
            <div id="war-gameover-mvp-slot" class="war-gameover-mvp-slot"></div>
            <div style="display:flex;gap:12px;justify-content:center;margin-top:8px">
                <button class="war-gameover-btn" onclick="warHudPlayAgain()">PLAY AGAIN</button>
                <button class="war-gameover-btn" onclick="warHudWatchReplay()" style="background:rgba(0,240,255,0.15);border-color:#00f0ff;color:#00f0ff">WATCH REPLAY</button>
            </div>
        </div>
    `;
    el.style.display = 'flex';
    el.className = 'war-game-over war-gameover-fade-in';

    // Fetch MVP for canvas overlay
    _warHudFetchMvp();

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

/**
 * Fetch MVP data and inject into the war-hud game over overlay.
 * Uses goBuildWarHudMvpHtml from game-over-stats.js if available.
 */
function _warHudFetchMvp() {
    fetch('/api/game/stats/mvp')
        .then(r => r.ok ? r.json() : null)
        .then(data => {
            if (!data || data.status !== 'ready' || !data.mvp) return;
            const slot = document.getElementById('war-gameover-mvp-slot');
            if (slot && typeof goBuildWarHudMvpHtml === 'function') {
                slot.innerHTML = goBuildWarHudMvpHtml(data.mvp);
            }
        })
        .catch(() => { /* MVP fetch failed, non-fatal */ });
}

function warHudPlayAgain() {
    const el = document.getElementById('war-game-over');
    if (el) el.style.display = 'none';
    // Also dismiss the main game-over overlay if visible
    const goOverlay = document.getElementById('game-over-overlay');
    if (goOverlay) goOverlay.hidden = true;

    fetch('/api/game/reset', { method: 'POST' })
        .then(r => r.ok ? r.json() : null)
        .catch(err => console.error('[WAR-HUD] Reset failed:', err));

    // Clear store state so stale overlay data does not leak into next game
    if (typeof TritiumStore !== 'undefined' && typeof TritiumStore.resetGameState === 'function') {
        TritiumStore.resetGameState();
    }

    // Reset local state
    _hudState.score = 0;
    _hudState.displayScore = 0;
    _hudState.eliminations = 0;
    _hudState.wave = 0;
    _hudState.totalWaves = 10;
    _hudState.waveHostilesRemaining = 0;
    _hudState.waveName = '';
    _hudState.gameState = 'idle';
    _hudState.eliminationFeed = [];
    // Reset mission mode fields
    _hudState.gameModeType = 'battle';
    _hudState.infrastructureHealth = 0;
    _hudState.infrastructureMax = 0;
    _hudState.civilianHarmCount = 0;
    _hudState.civilianHarmLimit = 5;
    _hudState.deEscalationScore = 0;
    _hudState.weightedTotalScore = 0;
    _hudState.loadingMessages = [];
    _hudState.bonusObjectives = [];
    // Clear countdown timers to prevent stale ticks
    if (_hudState.countdownTimer) { clearTimeout(_hudState.countdownTimer); _hudState.countdownTimer = null; }
    if (_hudState.loadingMessageTimer) { clearInterval(_hudState.loadingMessageTimer); _hudState.loadingMessageTimer = null; }
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

/**
 * Open the replay panel for the most recent game.
 * Dismisses the game-over overlay and triggers the panel to load.
 */
function warHudWatchReplay() {
    const el = document.getElementById('war-game-over');
    if (el) el.style.display = 'none';
    // Also dismiss the main game-over overlay
    const goOverlay = document.getElementById('game-over-overlay');
    if (goOverlay) goOverlay.hidden = true;

    // Notify the replay panel that we want to enter replay mode
    TritiumStore.set('replay.active', true);

    // Toggle the replay panel open if PanelManager is available
    if (typeof panelManager !== 'undefined' && panelManager && typeof panelManager.toggle === 'function') {
        panelManager.toggle('replay');
    }
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

function _hudEscapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str || '';
    return div.innerHTML;
}

function _formatNum(n) {
    return n.toLocaleString('en-US');
}

// ============================================================
// Canvas overlay: countdown (drawn directly on map canvas)
// ============================================================

/**
 * Draw a large centered countdown number on the canvas.
 * Called from the map render loop when game is in countdown state.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} canvasW
 * @param {number} canvasH
 */
function warHudDrawCanvasCountdown(ctx, canvasW, canvasH) {
    if (!ctx || _hudState.gameState !== 'countdown') return;

    const el = document.getElementById('war-countdown');
    const text = (el && el.textContent) || '';
    if (!text) return;

    const cx = canvasW / 2;
    const cy = canvasH / 2;

    // Large translucent background circle
    ctx.save();
    ctx.globalAlpha = 0.25;
    ctx.fillStyle = '#000';
    ctx.beginPath();
    ctx.arc(cx, cy, 80, 0, Math.PI * 2);
    ctx.fill();

    // Countdown number
    ctx.globalAlpha = 1.0;
    ctx.font = 'bold 72px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#00f0ff';
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 20;
    ctx.fillText(text, cx, cy);
    ctx.shadowBlur = 0;

    ctx.restore();
}

// ============================================================
// Canvas overlay: friendly health bars (drawn above units on map)
// ============================================================

/**
 * Draw thin 2px health bars above friendly units on the canvas.
 * Reads units from TritiumStore.units (Command Center) with fallback
 * to warState.targets (legacy war.js).
 * @param {CanvasRenderingContext2D} ctx
 * @param {Function} worldToScreen (x, y) => { x, y }
 * @param {number} zoom current map zoom level
 */
function warHudDrawFriendlyHealthBars(ctx, worldToScreen, zoom) {
    if (!ctx || !worldToScreen) return;
    if (_hudState.gameState !== 'active' && _hudState.gameState !== 'wave_complete') return;

    // Read units from TritiumStore (Command Center) or warState (legacy)
    let targets;
    if (typeof TritiumStore !== 'undefined' && TritiumStore.units) {
        targets = Array.from(TritiumStore.units.values());
    } else if (typeof warState !== 'undefined' && warState.targets) {
        targets = warState.targets;
    } else {
        return;
    }

    const barWidth = Math.max(16, Math.min(40, zoom * 2.5));
    const barHeight = 2;
    const yOffset = -12; // pixels above unit center

    for (const t of targets) {
        if (!t || t.alliance !== 'friendly') continue;
        if (t.status === 'eliminated' || t.status === 'dead') continue;

        const hp = typeof t.health === 'number' ? t.health : 100;
        const maxHp = t.max_health || t.maxHealth || 100;
        if (maxHp <= 0) continue;
        const ratio = Math.max(0, Math.min(1, hp / maxHp));
        // Skip drawing full-health bars to reduce clutter
        if (ratio >= 1.0) continue;

        const pos = t.position || t;
        const screen = worldToScreen(pos.x || 0, pos.y || 0);
        if (!screen) continue;

        // Support both {x,y} (map.js) and {sx,sy} (legacy war.js) formats
        const sx = screen.x !== undefined ? screen.x : screen.sx;
        const sy = screen.y !== undefined ? screen.y : screen.sy;
        if (sx === undefined || sy === undefined) continue;

        const bx = sx - barWidth / 2;
        const by = sy + yOffset;

        ctx.save();

        // Background bar
        ctx.fillStyle = 'rgba(0,0,0,0.5)';
        ctx.fillRect(bx - 1, by - 1, barWidth + 2, barHeight + 2);

        // Health fill
        const color = ratio > 0.6 ? '#05ffa1' : ratio >= 0.3 ? '#fcee0a' : '#ff2a6d';
        ctx.fillStyle = color;
        ctx.fillRect(bx, by, barWidth * ratio, barHeight);

        ctx.restore();
    }
}

// ============================================================
// Canvas overlay: mode-specific HUD (drone_swarm / civil_unrest)
// ============================================================

/**
 * Draw mode-specific HUD elements on the canvas.
 * - Drone Swarm: infrastructure health bar + mode indicator
 * - Civil Unrest: civilian harm counter, de-escalation score, mode indicator
 * Called from the map render loop during active gameplay.
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} canvasW
 * @param {number} canvasH
 */
function warHudDrawModeHud(ctx, canvasW, canvasH) {
    if (!ctx) return;
    if (_hudState.gameState !== 'active' && _hudState.gameState !== 'wave_complete') return;

    const mode = _hudState.gameModeType;
    if (mode === 'battle' || !mode) return;

    ctx.save();

    // Mode indicator badge — top center
    const modeLabel = mode === 'drone_swarm' ? 'DRONE SWARM' : 'CIVIL UNREST';
    ctx.font = 'bold 11px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = mode === 'drone_swarm' ? '#ff2a6d' : '#ffa500';
    ctx.fillText(modeLabel, canvasW / 2, 8);

    if (mode === 'drone_swarm') {
        _drawInfrastructureBar(ctx, canvasW, canvasH);
    } else if (mode === 'civil_unrest') {
        _drawCivilUnrestHud(ctx, canvasW, canvasH);
    }

    ctx.restore();
}

/**
 * Draw infrastructure health bar for drone_swarm mode.
 * Color: green >60%, yellow 30-60%, red <30%
 */
function _drawInfrastructureBar(ctx, canvasW, canvasH) {
    const barWidth = 200;
    const barHeight = 10;
    const x = canvasW / 2 - barWidth / 2;
    const y = 24;

    const max = _hudState.infrastructureMax || 1;
    const hp = Math.max(0, _hudState.infrastructureHealth);
    const ratio = Math.min(1, hp / max);

    // Label
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#aaaaaa';
    ctx.fillText(`INFRASTRUCTURE ${hp}/${max}`, canvasW / 2, y - 1);

    const barY = y + 12;

    // Background
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(x - 1, barY - 1, barWidth + 2, barHeight + 2);

    // Health fill with color gradient
    const color = ratio > 0.6 ? '#05ffa1' : ratio >= 0.3 ? '#fcee0a' : '#ff2a6d';
    ctx.fillStyle = color;
    ctx.fillRect(x, barY, barWidth * ratio, barHeight);

    // Border
    ctx.strokeStyle = '#333333';
    ctx.lineWidth = 1;
    ctx.strokeRect(x, barY, barWidth, barHeight);
}

/**
 * Draw civil unrest HUD: harm counter, de-escalation score, weighted score.
 */
function _drawCivilUnrestHud(ctx, canvasW, canvasH) {
    const harmCount = _hudState.civilianHarmCount || 0;
    const harmLimit = _hudState.civilianHarmLimit || 5;
    const deescScore = _hudState.deEscalationScore || 0;
    const totalScore = _hudState.weightedTotalScore || 0;

    // Civilian harm counter — top right area
    const rightX = canvasW - 20;
    const y = 8;

    ctx.font = 'bold 11px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';

    // Harm counter color: normal < 3, amber at 3, red at 4+
    const harmColor = harmCount >= 4 ? '#ff2a6d' : harmCount >= 3 ? '#ffa500' : '#00f0ff';
    ctx.fillStyle = harmColor;
    ctx.fillText(`CIVILIAN HARM: ${harmCount}/${harmLimit}`, rightX, y);

    // De-escalation score
    ctx.fillStyle = '#05ffa1';
    ctx.fillText(`DE-ESCALATION: ${_formatNum(deescScore)} pts`, rightX, y + 16);

    // Weighted total score (if available)
    if (totalScore > 0) {
        ctx.fillStyle = '#00f0ff';
        ctx.fillText(`SCORE: ${_formatNum(totalScore)}`, rightX, y + 32);
    }
}

// ============================================================
// Canvas overlay: hostile commander intel readout
// ============================================================

/**
 * Threat level color map.
 * low = green, moderate = yellow, high = orange, critical = red.
 */
const _THREAT_COLORS = {
    low: '#05ffa1',
    moderate: '#fcee0a',
    high: '#ffa500',
    critical: '#ff2a6d',
};

/**
 * Draw the hostile commander intel readout on the canvas.
 * Shows force ratio, threat level (color-coded), and recommended action.
 * Positioned bottom-left to avoid overlap with score (top-right)
 * and mode HUD (top-center).
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} canvasW
 * @param {number} canvasH
 * @param {Object|null} intel - hostile intel data from TritiumStore.game.hostileIntel
 */
function warHudDrawHostileIntel(ctx, canvasW, canvasH, intel) {
    if (!ctx || !intel) return;
    if (_hudState.gameState !== 'active' && _hudState.gameState !== 'wave_complete') return;

    ctx.save();

    const x = 16;
    const y = canvasH - 80;
    const lineH = 16;

    // Header
    ctx.font = 'bold 10px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#888888';
    ctx.fillText('HOSTILE INTEL', x, y);

    // Enemy confidence level with color coding
    // (hostile_commander threat_level is from enemy perspective:
    //  "low" = enemy feels safe, "critical" = enemy feels threatened)
    const threat = (intel.threat_level || 'unknown').toUpperCase();
    const threatColor = _THREAT_COLORS[intel.threat_level] || '#888888';
    ctx.font = 'bold 11px monospace';
    ctx.fillStyle = threatColor;
    ctx.fillText('ENEMY CONF: ' + threat, x, y + lineH);

    // Force ratio readout
    const ratio = typeof intel.force_ratio === 'number' ? intel.force_ratio : 0;
    const ratioStr = ratio.toFixed(1) + ':1';
    const advantage = ratio >= 1.0 ? 'HOSTILE ADV' : 'FRIENDLY ADV';
    ctx.fillStyle = ratio >= 1.0 ? '#ff2a6d' : '#05ffa1';
    ctx.fillText(ratioStr + ' ' + advantage, x, y + lineH * 2);

    // Recommended action
    const action = (intel.recommended_action || '').toUpperCase();
    if (action) {
        ctx.font = '10px monospace';
        ctx.fillStyle = '#00f0ff';
        ctx.fillText('ACTION: ' + action, x, y + lineH * 3);
    }

    ctx.restore();
}

// ============================================================
// Canvas overlay: bonus objectives checklist
// ============================================================

/**
 * Store bonus objectives from scenario win_conditions.
 * Each objective gets a `completed` flag defaulting to false.
 *
 * @param {Array|null} objectives - [{ name, description, reward }]
 */
function warHudSetBonusObjectives(objectives) {
    if (!objectives || !Array.isArray(objectives)) {
        _hudState.bonusObjectives = [];
        return;
    }
    _hudState.bonusObjectives = objectives.map(o => ({
        name: o.name,
        description: o.description || '',
        reward: o.reward || 0,
        completed: false,
    }));
}

/**
 * Mark a bonus objective as completed by name.
 * @param {string} name - exact objective name
 */
function warHudCompleteBonusObjective(name) {
    if (!_hudState.bonusObjectives) return;
    const obj = _hudState.bonusObjectives.find(o => o.name === name);
    if (obj) obj.completed = true;
}

/**
 * Draw bonus objectives checklist on the canvas.
 * Positioned bottom-right, compact list of objective names with check/dash indicators.
 * Only renders during active or wave_complete game states.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {number} canvasW
 * @param {number} canvasH
 */
function warHudDrawBonusObjectives(ctx, canvasW, canvasH) {
    if (!ctx) return;
    if (_hudState.gameState !== 'active' && _hudState.gameState !== 'wave_complete') return;
    if (!_hudState.bonusObjectives || _hudState.bonusObjectives.length === 0) return;

    ctx.save();

    const objectives = _hudState.bonusObjectives;
    const lineH = 16;
    const rightX = canvasW - 14;
    const startY = canvasH - 14 - objectives.length * lineH;

    // Header
    ctx.font = 'bold 9px monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#888888';
    ctx.fillText('BONUS OBJECTIVES', rightX, startY - lineH);

    // Objective lines
    ctx.font = '9px monospace';
    for (let i = 0; i < objectives.length; i++) {
        const o = objectives[i];
        const y = startY + i * lineH;
        const marker = o.completed ? '\u2713' : '\u2022';
        ctx.fillStyle = o.completed ? '#05ffa1' : '#666666';
        ctx.fillText(`${marker} ${o.name} (${_formatNum(o.reward)} pts)`, rightX, y);
    }

    ctx.restore();
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
window.warHudWatchReplay = warHudWatchReplay;
window.warHudShowAmyAnnouncement = warHudShowAmyAnnouncement;
window.warHudDrawCanvasCountdown = warHudDrawCanvasCountdown;
window.warHudDrawFriendlyHealthBars = warHudDrawFriendlyHealthBars;
window.warHudDrawModeHud = warHudDrawModeHud;
window.warHudSetLoadingMessages = warHudSetLoadingMessages;
window.warHudDrawHostileIntel = warHudDrawHostileIntel;
window.warHudSetBonusObjectives = warHudSetBonusObjectives;
window.warHudCompleteBonusObjective = warHudCompleteBonusObjective;
window.warHudDrawBonusObjectives = warHudDrawBonusObjectives;
