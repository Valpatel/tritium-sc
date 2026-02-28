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
        nodeCount: 0,
    },

    // Connection state
    connection: {
        status: 'disconnected',  // connected | disconnected | error
    },

    // Alerts (from WebSocket escalation events)
    alerts: [],  // { id, type, message, time, source, read }

    // Cameras (from API /api/cameras)
    cameras: [],

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
     * @param {string} id
     * @param {Object} data
     */
    updateUnit(id, data) {
        const existing = this.units.get(id) || {};
        this.units.set(id, { ...existing, ...data, id });
        this._notify('units', this.units);
    },

    /**
     * Remove a unit by id.
     * @param {string} id
     */
    removeUnit(id) {
        this.units.delete(id);
        this._notify('units', this.units);
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
};
