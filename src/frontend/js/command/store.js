// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// TritiumStore -- single source of truth for all UI state
// Usage:
//   import { TritiumStore } from './store.js';
//   TritiumStore.set('game.phase', 'active');
//   const unsub = TritiumStore.on('game.phase', (val, old) => console.log(val));
//   unsub();  // unsubscribe

export const TritiumStore = {
    // Map/viewport state
    map: {
        viewport: { x: 0, y: 0, zoom: 1 },
        selectedUnitId: null,
        mode: 'observe',  // observe | tactical | setup
    },

    // Game state (from WebSocket game_state events)
    game: {
        phase: 'idle',  // idle | setup | countdown | active | wave_complete | game_over
        wave: 0,
        totalWaves: 10,
        score: 0,
        eliminations: 0,
        waveName: '',
        countdown: 0,
        waveHostilesRemaining: 0,
        difficultyMultiplier: 1.0,
        // Overlay data (reset per game)
        hostileIntel: null,
        hostileObjectives: null,
        crowdDensity: null,
        coverPoints: [],
        signals: [],
        // Mission-mode-specific state
        modeType: null,
        infrastructureHealth: null,
        infrastructureMax: null,
        deEscalationScore: null,
        civilianHarmCount: null,
        civilianHarmLimit: null,
        weightedTotalScore: null,
    },

    // Units -- single source of truth (from WebSocket sim_telemetry)
    // id -> { id, name, type, alliance, position:{x,y}, heading, health, maxHealth, battery, status, eliminations, lastThought }
    units: new Map(),

    // Amy state (from SSE /api/amy/thoughts and WebSocket amy_* events)
    amy: {
        state: 'idle',
        mood: 'calm',
        lastThought: '',
        speaking: false,
    },

    // Operator unit control (TAKE CONTROL / RELEASE)
    controlledUnitId: null,   // unit id when operator has direct control

    // Environmental hazards (from WebSocket hazard_spawned/hazard_expired events)
    hazards: new Map(),

    // Mesh radio state (from WebSocket mesh_* events)
    mesh: { connected: false },

    // Replay mode (from replay panel)
    replay: { active: false },

    // TAK state (from TAK panel)
    tak: { connected: false },

    // Connection state
    connection: {
        status: 'disconnected',  // connected | disconnected | error
    },

    // Alerts (from WebSocket escalation events)
    alerts: [],  // { id, type, message, time, source, read }

    // Pinned targets — always visible, never pruned (persisted to localStorage)
    pinnedTargets: new Set(
        typeof localStorage !== 'undefined' && localStorage.getItem('tritium.pinnedTargets')
            ? JSON.parse(localStorage.getItem('tritium.pinnedTargets'))
            : []
    ),

    // Cameras (from API /api/cameras)
    cameras: [],

    // Graphlings (from plugin SSE /api/graphlings/thoughts)
    graphlings: {
        deployed: [],   // soul_id strings
        agents: [],     // { soul_id, role_name, emotion, last_thought }
    },

    // -----------------------------------------------------------------------
    // Notification batching (requestAnimationFrame coalescing)
    // -----------------------------------------------------------------------
    _pendingNotify: null,   // Set of dirty keys awaiting RAF flush
    _notifyRAF: null,       // RAF handle (null when no flush scheduled)

    /**
     * Schedule a notification for a key, coalesced to one RAF frame.
     * Multiple updateUnit() calls within the same frame fire _notify once.
     * Falls back to synchronous _notify when requestAnimationFrame is
     * unavailable (Node.js test environment).
     * @param {string} key
     */
    _scheduleNotify(key) {
        // Fallback for non-browser (Node.js tests): notify synchronously
        if (typeof requestAnimationFrame === 'undefined') {
            this._notify(key, key === 'units' ? this.units : this[key]);
            return;
        }
        if (!this._pendingNotify) this._pendingNotify = new Set();
        this._pendingNotify.add(key);
        if (!this._notifyRAF) {
            this._notifyRAF = requestAnimationFrame(() => {
                this._notifyRAF = null;
                const keys = this._pendingNotify;
                this._pendingNotify = null;
                for (const k of keys) {
                    this._notify(k, k === 'units' ? this.units : this[k]);
                }
            });
        }
    },

    /**
     * Flush any pending RAF-batched notifications synchronously.
     * Useful in tests or when you need immediate consistency.
     */
    flushNotify() {
        if (this._notifyRAF && typeof cancelAnimationFrame !== 'undefined') {
            cancelAnimationFrame(this._notifyRAF);
            this._notifyRAF = null;
        }
        if (this._pendingNotify) {
            const keys = this._pendingNotify;
            this._pendingNotify = null;
            for (const k of keys) {
                this._notify(k, k === 'units' ? this.units : this[k]);
            }
        }
    },

    // -----------------------------------------------------------------------
    // Subscriber system
    // -----------------------------------------------------------------------
    _listeners: new Map(),

    /**
     * Subscribe to changes at a dot-path.
     * @param {string} path - e.g. 'game.phase', 'amy.state', or '*' for all
     * @param {Function} fn - callback(newValue, oldValue) or callback(path, value) for '*'
     * @returns {Function} unsubscribe function
     */
    on(path, fn) {
        if (!this._listeners.has(path)) this._listeners.set(path, new Set());
        this._listeners.get(path).add(fn);
        return () => this._listeners.get(path)?.delete(fn);
    },

    /**
     * Set a value at a dot-path and notify subscribers.
     * Creates intermediate objects if they don't exist.
     * @param {string} path - e.g. 'game.phase'
     * @param {*} value
     */
    set(path, value) {
        const parts = path.split('.');
        let obj = this;
        for (let i = 0; i < parts.length - 1; i++) {
            if (obj[parts[i]] === undefined || obj[parts[i]] === null) {
                obj[parts[i]] = {};
            }
            obj = obj[parts[i]];
        }
        const key = parts[parts.length - 1];
        const oldValue = obj[key];
        if (oldValue === value) return;  // no-op for identical primitives
        obj[key] = value;
        this._notify(path, value, oldValue);
    },

    /**
     * Get a value at a dot-path.
     * Handles both plain objects and Maps.
     * @param {string} path
     * @returns {*}
     */
    get(path) {
        const parts = path.split('.');
        let obj = this;
        for (const part of parts) {
            if (obj === undefined || obj === null) return undefined;
            obj = obj instanceof Map ? obj.get(part) : obj[part];
        }
        return obj;
    },

    /**
     * Update a unit (merge fields into existing entry).
     * Mutates in place to avoid object spread overhead on hot path.
     * Notification is batched via requestAnimationFrame (one notify per frame).
     * @param {string} id
     * @param {Object} data
     */
    updateUnit(id, data) {
        let unit = this.units.get(id);
        if (!unit) {
            unit = { id };
            this.units.set(id, unit);
        }
        Object.assign(unit, data);
        unit.id = id;  // ensure id cannot be overwritten by data
        this._scheduleNotify('units');
    },

    /**
     * Remove a unit by id.
     * Pinned targets are protected from removal.
     * @param {string} id
     */
    removeUnit(id) {
        // Pinned targets are never pruned
        if (this.pinnedTargets.has(id)) return;
        this.units.delete(id);
        // Clear selection if the removed unit was selected
        if (this.map.selectedUnitId === id) {
            this.set('map.selectedUnitId', null);
        }
        this._scheduleNotify('units');
    },

    /**
     * Add an alert to the front of the alerts list.
     * Caps at 100 alerts.
     * @param {Object} alert - { type, message, source }
     */
    addAlert(alert) {
        this.alerts.unshift({
            ...alert,
            id: Date.now(),
            time: new Date(),
            read: false,
        });
        if (this.alerts.length > 100) this.alerts.pop();
        this._notify('alerts', this.alerts);
    },

    /**
     * Reset all game-related state to initial values.
     * Call this when a game ends and a new one begins, or on explicit reset.
     * Clears: game counters, units, overlay data, selection, controlled unit.
     * Preserves: amy, map.mode, connection, alerts, cameras, graphlings.
     */
    resetGameState() {
        // Core game counters
        this.set('game.phase', 'idle');
        this.set('game.wave', 0);
        this.set('game.totalWaves', 10);
        this.set('game.score', 0);
        this.set('game.eliminations', 0);
        this.set('game.waveName', '');
        this.set('game.countdown', 0);
        this.set('game.waveHostilesRemaining', 0);
        this.set('game.difficultyMultiplier', 1.0);

        // Directional state
        this.set('game.waveDirection', null);

        // Per-game overlay data
        this.set('hazards', new Map());
        this.set('game.hostileIntel', null);
        this.set('game.hostileObjectives', null);
        this.set('game.crowdDensity', null);
        this.set('game.coverPoints', []);
        this.set('game.signals', []);

        // Mission-mode-specific state
        this.set('game.modeType', null);
        this.set('game.infrastructureHealth', null);
        this.set('game.infrastructureMax', null);
        this.set('game.deEscalationScore', null);
        this.set('game.civilianHarmCount', null);
        this.set('game.civilianHarmLimit', null);
        this.set('game.weightedTotalScore', null);

        // Clear all units (stale data from previous game)
        this.units.clear();
        this._notify('units', this.units);

        // Exit replay mode if active
        this.set('replay.active', false);

        // Deselect unit and release control
        this.set('map.selectedUnitId', null);
        this.set('controlledUnitId', null);
    },

    /**
     * Pin a target so it stays visible and is never pruned.
     * @param {string} id - target/unit ID
     */
    pinTarget(id) {
        this.pinnedTargets.add(id);
        this._persistPinnedTargets();
        this._notify('pinnedTargets', this.pinnedTargets);
    },

    /**
     * Unpin a target, allowing it to be pruned normally.
     * @param {string} id - target/unit ID
     */
    unpinTarget(id) {
        this.pinnedTargets.delete(id);
        this._persistPinnedTargets();
        this._notify('pinnedTargets', this.pinnedTargets);
    },

    /**
     * Check if a target is pinned.
     * @param {string} id
     * @returns {boolean}
     */
    isTargetPinned(id) {
        return this.pinnedTargets.has(id);
    },

    /**
     * Save pinned targets to localStorage for persistence across reloads.
     */
    _persistPinnedTargets() {
        if (typeof localStorage !== 'undefined') {
            localStorage.setItem(
                'tritium.pinnedTargets',
                JSON.stringify([...this.pinnedTargets])
            );
        }
    },

    /**
     * Notify subscribers for a path and wildcard listeners.
     * @param {string} path
     * @param {*} value
     * @param {*} oldValue
     */
    _notify(path, value, oldValue) {
        // Notify exact path subscribers
        this._listeners.get(path)?.forEach(fn => {
            try { fn(value, oldValue); } catch (e) { console.error('[Store] listener error:', e); }
        });
        // Notify wildcard '*' listeners with (path, value) signature
        this._listeners.get('*')?.forEach(fn => {
            try { fn(path, value); } catch (e) { console.error('[Store] wildcard error:', e); }
        });
    },

    // -- Operator cursor sharing ----------------------------------------

    /** @type {Map<string, Object>} session_id -> cursor data */
    _operatorCursors: new Map(),
    /** Cursor stale timeout: 15 seconds */
    _cursorStaleMs: 15000,

    /**
     * Update an operator's cursor position.
     * @param {string} sessionId
     * @param {Object} cursor - {session_id, username, display_name, role, color, lat, lng, timestamp}
     */
    setOperatorCursor(sessionId, cursor) {
        cursor._receivedAt = Date.now();
        this._operatorCursors.set(sessionId, cursor);
        this._notify('operatorCursors', this._operatorCursors);
    },

    /**
     * Remove an operator's cursor (e.g., on disconnect).
     * @param {string} sessionId
     */
    removeOperatorCursor(sessionId) {
        this._operatorCursors.delete(sessionId);
        this._notify('operatorCursors', this._operatorCursors);
    },

    /**
     * Get all active (non-stale) operator cursors.
     * @returns {Array<Object>} cursor data entries
     */
    getOperatorCursors() {
        const now = Date.now();
        const result = [];
        for (const [sid, cursor] of this._operatorCursors) {
            if (now - (cursor._receivedAt || 0) < this._cursorStaleMs) {
                result.push(cursor);
            } else {
                this._operatorCursors.delete(sid);
            }
        }
        return result;
    },
};
