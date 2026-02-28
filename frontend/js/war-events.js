// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room -- Event-to-Audio Mapper
 * Routes WebSocket game events to WarAudioManager.play() calls.
 *
 * Handles:
 *   - Event-to-effect name mapping
 *   - Priority system (game state > combat > ambient)
 *   - Kill streak name resolution
 *   - Ambient auto-play during active game
 *
 * This module is loaded AFTER war-audio.js and wired into the existing
 * warHandle* functions in war.js.
 */

// ============================================================
// Event priorities
// ============================================================

var _EVENT_PRIORITIES = {
    game: 3,     // game state changes (highest)
    combat: 2,   // projectiles, hits, eliminations
    ambient: 1,  // wind, birds (lowest)
};

// ============================================================
// Event -> effect name mapping
// ============================================================

var _EVENT_MAPPINGS = {
    projectile_fired:  'nerf_shot',
    projectile_hit:    'impact_hit',
    target_eliminated: 'explosion',
    wave_start:        'wave_start',
    wave_complete:     'wave_start',   // re-use wave stab (shorter)
    game_over_victory: 'victory_fanfare',
    game_over_defeat:  'defeat_sting',
    turret_rotate:     'turret_rotate',
    drone_move:        'drone_buzz',
    dispatch:          'dispatch_ack',
    alert:             'alert_tone',
    escalation:        'escalation_siren',
};

// Elimination streak thresholds -> effect names
var _ELIMINATION_STREAK_MAP = {
    3:  'elimination_streak_killing_spree',
    5:  'elimination_streak_rampage',
    7:  'elimination_streak_dominating',
    10: 'elimination_streak_godlike',
};

// ============================================================
// WarEventMapper
// ============================================================

function WarEventMapper(audioManager) {
    this._audio = audioManager || warAudio;
    this._gameActive = false;
}

WarEventMapper.prototype.getEventMappings = function() {
    // Return a copy
    var copy = {};
    for (var key in _EVENT_MAPPINGS) {
        if (_EVENT_MAPPINGS.hasOwnProperty(key)) {
            copy[key] = _EVENT_MAPPINGS[key];
        }
    }
    return copy;
};

WarEventMapper.prototype.getPriorities = function() {
    var copy = {};
    for (var key in _EVENT_PRIORITIES) {
        if (_EVENT_PRIORITIES.hasOwnProperty(key)) {
            copy[key] = _EVENT_PRIORITIES[key];
        }
    }
    return copy;
};

WarEventMapper.prototype.getEliminationStreakEffect = function(streak) {
    return _ELIMINATION_STREAK_MAP[streak] || null;
};

// Backwards compatibility alias
WarEventMapper.prototype.getKillStreakEffect = WarEventMapper.prototype.getEliminationStreakEffect;

WarEventMapper.prototype.handleEvent = function(eventType, data) {
    var effectName = _EVENT_MAPPINGS[eventType];
    if (effectName) {
        if (data && data.x !== undefined && data.y !== undefined) {
            this._audio.playAt(effectName, data.x, data.y);
        } else {
            this._audio.play(effectName);
        }
    }
};

// -- Game state tracking -------------------------------------------

WarEventMapper.prototype.onGameStateChange = function(data) {
    if (!data) return;
    var state = data.state || data.new_state;

    if (state === 'active') {
        this._gameActive = true;
        this._audio.startAmbient();
    } else if (state === 'setup' || state === 'idle') {
        this._gameActive = false;
        this._audio.stopAmbient();
    } else if (state === 'game_over' || state === 'victory' || state === 'defeat') {
        this._gameActive = false;
        this._audio.stopAmbient();
    }
};

WarEventMapper.prototype.onProjectileFired = function(data) {
    if (!data) return;
    var pos = data.source_pos || {};
    this._audio.playAt('nerf_shot', pos.x || 0, pos.y || 0);
};

WarEventMapper.prototype.onProjectileHit = function(data) {
    if (!data) return;
    var pos = data.target_pos || data.position || {};
    this._audio.playAt('impact_hit', pos.x || 0, pos.y || 0);
};

WarEventMapper.prototype.onTargetEliminated = function(data) {
    if (!data) return;
    var pos = data.position || {};
    this._audio.playAt('explosion', pos.x || 0, pos.y || 0);
};

WarEventMapper.prototype.onWaveStart = function(data) {
    this._audio.play('wave_start');
};

WarEventMapper.prototype.onKillStreak = function(data) {
    if (!data) return;
    var streak = data.streak || 0;
    var effectName = this.getKillStreakEffect(streak);
    if (effectName) {
        this._audio.play(effectName);
    }
};

WarEventMapper.prototype.onGameOver = function(data) {
    if (!data) return;
    this._audio.stopAmbient();
    this._gameActive = false;
    var result = (data.result || '').toLowerCase();
    if (result === 'victory') {
        this._audio.play('victory_fanfare');
    } else {
        this._audio.play('defeat_sting');
    }
};

WarEventMapper.prototype.onDispatch = function(data) {
    this._audio.play('dispatch_ack');
};

WarEventMapper.prototype.onAlert = function(data) {
    this._audio.play('alert_tone');
};

WarEventMapper.prototype.onEscalation = function(data) {
    this._audio.play('escalation_siren');
};

WarEventMapper.prototype.onWaveComplete = function(data) {
    this._audio.play('wave_start');
};

WarEventMapper.prototype.onCountdown = function(data) {
    this._audio.play('alert_tone');
};

WarEventMapper.prototype.onAmyAnnouncement = function(data) {
    this._audio.play('dispatch_ack');
};

// ============================================================
// Global singleton + hook into existing war.js event handlers
// ============================================================

var warEventMapper = new WarEventMapper();

// Preload combat + game effects on first user interaction
// (browser requires user gesture before AudioContext can play)
var _audioInitialized = false;

function _initWarAudioOnGesture() {
    if (_audioInitialized) return;
    _audioInitialized = true;

    warAudio.init();

    // Preload critical effects first, then the rest
    var critical = [
        'nerf_shot', 'impact_hit', 'explosion', 'wave_start',
        'victory_fanfare', 'defeat_sting', 'dispatch_ack', 'alert_tone',
    ];
    warAudio.preload(critical).then(function() {
        // Load remaining in background
        warAudio.preloadAll();
    });
}

if (typeof document !== 'undefined') {
    document.addEventListener('click', _initWarAudioOnGesture, { once: false });
    document.addEventListener('keydown', _initWarAudioOnGesture, { once: false });
}

// ============================================================
// Wire into existing warHandle* functions
// ============================================================

// We patch the existing handlers by storing original refs and wrapping.
// This avoids modifying war.js directly and follows the module pattern.

function _patchWarHandler(fnName, callback) {
    if (typeof window === 'undefined') return;

    var original = window[fnName];
    window[fnName] = function(data) {
        // Call original handler first
        if (typeof original === 'function') original(data);
        // Then our audio callback
        try { callback(data); } catch (e) {
            console.warn('[WAR-EVENTS] Audio error in ' + fnName + ':', e);
        }
    };
}

// Apply patches after all scripts are loaded
function _wireWarAudioEvents() {
    _patchWarHandler('warHandleProjectileFired', function(data) {
        warEventMapper.onProjectileFired(data);
    });
    _patchWarHandler('warHandleProjectileHit', function(data) {
        warEventMapper.onProjectileHit(data);
    });
    _patchWarHandler('warHandleTargetEliminated', function(data) {
        warEventMapper.onTargetEliminated(data);
    });
    _patchWarHandler('warHandleWaveStart', function(data) {
        warEventMapper.onWaveStart(data);
    });
    _patchWarHandler('warHandleKillStreak', function(data) {
        warEventMapper.onKillStreak(data);
    });
    _patchWarHandler('warHandleGameOver', function(data) {
        warEventMapper.onGameOver(data);
    });
    _patchWarHandler('warHandleGameState', function(data) {
        warEventMapper.onGameStateChange(data);
    });
    _patchWarHandler('warHandleDispatch', function(data) {
        warEventMapper.onDispatch(data);
    });
    _patchWarHandler('warHandleThreatEscalation', function(data) {
        warEventMapper.onEscalation(data);
    });
    _patchWarHandler('warHandleWaveComplete', function(data) {
        warEventMapper.onWaveComplete(data);
    });
    _patchWarHandler('warHandleCountdown', function(data) {
        warEventMapper.onCountdown(data);
    });
    _patchWarHandler('warHandleAmyAnnouncement', function(data) {
        warEventMapper.onAmyAnnouncement(data);
    });
}

// Wire after DOM is ready (all scripts loaded)
if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _wireWarAudioEvents);
    } else {
        // Scripts already loaded, wire immediately
        // Use setTimeout to ensure war.js globals are set
        setTimeout(_wireWarAudioEvents, 0);
    }
}

// ============================================================
// Expose globally
// ============================================================

if (typeof window !== 'undefined') {
    window.WarEventMapper = WarEventMapper;
    window.warEventMapper = warEventMapper;
    window._initWarAudioOnGesture = _initWarAudioOnGesture;
}
