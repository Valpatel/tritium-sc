// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC War Room -- Audio Manager
 * Pre-loads procedural sound effects via Web Audio API.
 *
 * Fetches WAV files from /api/audio/effects/{name} and decodes them
 * into AudioBuffers. Provides play(), playAt(), setVolume(), mute
 * controls.
 *
 * Design constraints:
 *   - No frameworks (vanilla JS, Web Audio API only)
 *   - Non-blocking: preloading is async, play() is fire-and-forget
 *   - Debouncing: rapid-fire same effect is rate-limited
 *   - Concurrent limit: max 12 simultaneous sounds
 *   - Positional audio: playAt(name, x, y) pans based on camera
 */

// ============================================================
// AudioManager
// ============================================================

function WarAudioManager() {
    this._ctx = null;          // AudioContext (lazy init on user gesture)
    this._buffers = {};        // name -> AudioBuffer
    this._volume = 0.7;
    this._muted = false;
    this._masterGain = null;
    this._activeSources = [];  // { source, startTime }
    this.maxConcurrent = 12;
    this._debounceMap = {};    // name -> last play timestamp
    this._debounceMs = 80;     // minimum ms between same effect
    this._loading = false;
    this._loaded = false;
    this._ambientSource = null;
    this._ambientGain = null;
}

// -- Init / lifecycle -----------------------------------------------

WarAudioManager.prototype.init = function() {
    if (this._ctx) return;
    try {
        this._ctx = new (window.AudioContext || window.webkitAudioContext)();
        this._masterGain = this._ctx.createGain();
        this._masterGain.gain.value = this._muted ? 0 : this._volume;
        this._masterGain.connect(this._ctx.destination);
    } catch (e) {
        console.warn('[WAR-AUDIO] Web Audio API unavailable:', e);
    }
};

WarAudioManager.prototype._ensureCtx = function() {
    if (!this._ctx) this.init();
    if (this._ctx && this._ctx.state === 'suspended') {
        this._ctx.resume().catch(function() {});
    }
    return this._ctx;
};

// -- Preloading -----------------------------------------------------

WarAudioManager.prototype.preload = function(effectNames) {
    var self = this;
    if (!effectNames || effectNames.length === 0) return Promise.resolve();
    if (!this._ensureCtx()) return Promise.resolve();

    var promises = effectNames.map(function(name) {
        if (self._buffers[name]) return Promise.resolve();
        return fetch('/api/audio/effects/' + name)
            .then(function(resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return resp.arrayBuffer();
            })
            .then(function(buf) {
                return self._ctx.decodeAudioData(buf);
            })
            .then(function(audioBuffer) {
                self._buffers[name] = audioBuffer;
            })
            .catch(function(err) {
                console.warn('[WAR-AUDIO] Failed to load ' + name + ':', err);
            });
    });

    return Promise.all(promises);
};

WarAudioManager.prototype.preloadAll = function() {
    var self = this;
    if (this._loading || this._loaded) return Promise.resolve();
    this._loading = true;

    return fetch('/api/audio/effects')
        .then(function(resp) { return resp.json(); })
        .then(function(effects) {
            var names = effects.map(function(e) { return e.name; });
            return self.preload(names);
        })
        .then(function() {
            self._loaded = true;
            self._loading = false;
            console.log('[WAR-AUDIO] All effects loaded');
        })
        .catch(function(err) {
            self._loading = false;
            console.warn('[WAR-AUDIO] Preload failed:', err);
        });
};

// -- Volume control -------------------------------------------------

WarAudioManager.prototype.getVolume = function() {
    return this._volume;
};

WarAudioManager.prototype.setVolume = function(level) {
    this._volume = Math.max(0, Math.min(1, level));
    if (this._masterGain) {
        this._masterGain.gain.value = this._muted ? 0 : this._volume;
    }
};

WarAudioManager.prototype.isMuted = function() {
    return this._muted;
};

WarAudioManager.prototype.setMuted = function(muted) {
    this._muted = !!muted;
    if (this._masterGain) {
        this._masterGain.gain.value = this._muted ? 0 : this._volume;
    }
};

WarAudioManager.prototype.toggleMute = function() {
    this.setMuted(!this._muted);
};

// -- Playback -------------------------------------------------------

WarAudioManager.prototype.play = function(name) {
    // Debounce rapid-fire of the same effect
    var now = Date.now();
    var lastTime = this._debounceMap[name] || 0;
    if (now - lastTime < this._debounceMs) return;
    this._debounceMap[name] = now;

    this._playInternal(name);
};

WarAudioManager.prototype._playInternal = function(name) {
    var ctx = this._ensureCtx();
    if (!ctx || this._muted) return;

    var buffer = this._buffers[name];
    if (!buffer) return;  // Not loaded yet -- skip silently

    // Evict oldest if at concurrent limit
    this._cleanupSources();
    if (this._activeSources.length >= this.maxConcurrent) {
        var oldest = this._activeSources.shift();
        try { oldest.source.stop(); } catch (e) {}
    }

    var source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(this._masterGain);
    source.start(0);

    var entry = { source: source, startTime: Date.now() };
    this._activeSources.push(entry);

    var self = this;
    source.onended = function() {
        var idx = self._activeSources.indexOf(entry);
        if (idx >= 0) self._activeSources.splice(idx, 1);
    };
};

WarAudioManager.prototype.playAt = function(name, worldX, worldY) {
    // Positional audio: pan based on world position relative to camera
    var ctx = this._ensureCtx();
    if (!ctx || this._muted) return;

    var buffer = this._buffers[name];
    if (!buffer) return;

    // Debounce
    var now = Date.now();
    var lastTime = this._debounceMap[name] || 0;
    if (now - lastTime < this._debounceMs) return;
    this._debounceMap[name] = now;

    this._cleanupSources();
    if (this._activeSources.length >= this.maxConcurrent) {
        var oldest = this._activeSources.shift();
        try { oldest.source.stop(); } catch (e) {}
    }

    // Calculate pan from world position (-1 left, +1 right)
    var camX = 0;
    if (typeof warState !== 'undefined') camX = warState.cam.x;
    var dx = worldX - camX;
    var pan = Math.max(-1, Math.min(1, dx / 30));  // normalize to map range

    var source = ctx.createBufferSource();
    source.buffer = buffer;

    var panner = ctx.createStereoPanner();
    panner.pan.setValueAtTime(pan, ctx.currentTime);
    source.connect(panner);
    panner.connect(this._masterGain);

    source.start(0);

    var entry = { source: source, startTime: Date.now() };
    this._activeSources.push(entry);

    var self = this;
    source.onended = function() {
        var idx = self._activeSources.indexOf(entry);
        if (idx >= 0) self._activeSources.splice(idx, 1);
    };
};

// -- Ambient loop ---------------------------------------------------

WarAudioManager.prototype.startAmbient = function() {
    if (this._ambientSource) return;

    var ctx = this._ensureCtx();
    if (!ctx) return;

    var buffer = this._buffers['ambient_wind'];
    if (!buffer) return;

    this._ambientGain = ctx.createGain();
    this._ambientGain.gain.value = 0.3;
    this._ambientGain.connect(this._masterGain);

    this._ambientSource = ctx.createBufferSource();
    this._ambientSource.buffer = buffer;
    this._ambientSource.loop = true;
    this._ambientSource.connect(this._ambientGain);
    this._ambientSource.start(0);
};

WarAudioManager.prototype.stopAmbient = function() {
    if (this._ambientSource) {
        try { this._ambientSource.stop(); } catch (e) {}
        this._ambientSource = null;
    }
    if (this._ambientGain) {
        this._ambientGain.disconnect();
        this._ambientGain = null;
    }
};

// -- Cleanup --------------------------------------------------------

WarAudioManager.prototype._cleanupSources = function() {
    var now = Date.now();
    this._activeSources = this._activeSources.filter(function(entry) {
        // Remove sources older than 10 seconds (safety net)
        return (now - entry.startTime) < 10000;
    });
};

WarAudioManager.prototype.destroy = function() {
    this.stopAmbient();
    for (var i = 0; i < this._activeSources.length; i++) {
        try { this._activeSources[i].source.stop(); } catch (e) {}
    }
    this._activeSources = [];
    this._buffers = {};
    if (this._ctx) {
        this._ctx.close().catch(function() {});
        this._ctx = null;
    }
};

// ============================================================
// Global singleton + exports
// ============================================================

var warAudio = new WarAudioManager();

// Expose globally
if (typeof window !== 'undefined') {
    window.WarAudioManager = WarAudioManager;
    window.warAudio = warAudio;
}
