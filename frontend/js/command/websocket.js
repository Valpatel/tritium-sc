// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// WebSocketManager -- manages connection to /ws/live with auto-reconnect
// Routes incoming messages to TritiumStore and EventBus
//
// Usage:
//   import { WebSocketManager } from './websocket.js';
//   const ws = new WebSocketManager();
//   ws.connect();
//   ws.send({ type: 'ping' });

import { TritiumStore } from './store.js';
import { EventBus } from './events.js';

export class WebSocketManager {
    constructor() {
        this._ws = null;
        this._reconnectTimer = null;
        this._reconnectDelay = 2000;
        this._maxDelay = 30000;
    }

    /**
     * Open a WebSocket connection to the server.
     * Auto-reconnects on close with exponential backoff.
     */
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws/live`;
        console.log(`%c[WS] Connecting to ${url}`, 'color: #fcee0a;');

        try {
            this._ws = new WebSocket(url);

            this._ws.onopen = () => {
                console.log('%c[WS] Connected', 'color: #05ffa1;');
                TritiumStore.set('connection.status', 'connected');
                this._reconnectDelay = 2000;
                EventBus.emit('ws:connected');
            };

            this._ws.onclose = () => {
                console.log('%c[WS] Disconnected', 'color: #ff2a6d;');
                TritiumStore.set('connection.status', 'disconnected');
                EventBus.emit('ws:disconnected');
                this._scheduleReconnect();
            };

            this._ws.onerror = (e) => {
                console.error('[WS] Error:', e);
                TritiumStore.set('connection.status', 'error');
            };

            this._ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    this._handleMessage(msg);
                } catch (e) {
                    console.error('[WS] Parse error:', e);
                }
            };
        } catch (e) {
            console.error('[WS] Connection failed:', e);
            this._scheduleReconnect();
        }
    }

    /**
     * Send a JSON message over the WebSocket.
     * Silently drops if not connected.
     * @param {Object} data
     */
    send(data) {
        if (this._ws?.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify(data));
        }
    }

    /**
     * Close the WebSocket connection. Does not auto-reconnect.
     */
    disconnect() {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = null;
        if (this._ws) {
            // Remove onclose to prevent auto-reconnect
            this._ws.onclose = null;
            this._ws.close();
            this._ws = null;
        }
        TritiumStore.set('connection.status', 'disconnected');
    }

    /**
     * @returns {boolean} true if the WebSocket is open
     */
    get connected() {
        return this._ws?.readyState === WebSocket.OPEN;
    }

    // -----------------------------------------------------------------------
    // Internal
    // -----------------------------------------------------------------------

    /**
     * Update a single unit in the TritiumStore from telemetry data.
     * @param {Object} t - telemetry object with target_id, name, etc.
     */
    _updateUnit(t) {
        if (!t || !t.target_id) return;
        const update = {
            name: t.name || t.target_id,
            type: t.asset_type || t.type || 'unknown',
            alliance: t.alliance || 'unknown',
            position: t.position || { x: t.x || 0, y: t.y || 0 },
            heading: t.heading || 0,
            health: t.health,
            maxHealth: t.max_health,
            battery: typeof t.battery === 'number' ? Math.round(t.battery * 100) : undefined,
            status: t.status || 'active',
            eliminations: t.kills || t.eliminations || 0,
            speed: t.speed || 0,
        };
        // Extended combat telemetry fields
        if (t.kills !== undefined) update.kills = t.kills;
        if (t.morale !== undefined) update.morale = t.morale;
        if (t.fsm_state !== undefined) { update.fsmState = t.fsm_state; update.fsm_state = t.fsm_state; }
        if (t.degradation !== undefined) update.degradation = t.degradation;
        if (t.weapon_range !== undefined) update.weaponRange = t.weapon_range;
        if (t.is_combatant !== undefined) update.isCombatant = t.is_combatant;
        // Vision and squad fields
        if (t.visible !== undefined) update.visible = t.visible;
        if (t.squad_id !== undefined) update.squadId = t.squad_id;
        if (t.detected_by !== undefined) update.detectedBy = t.detected_by;
        if (t.detected !== undefined) update.detected = t.detected;
        TritiumStore.updateUnit(t.target_id, update);

        // Clean up terminal-state units after a delay so effects/animations complete.
        // Without this, eliminated/destroyed/despawned units accumulate forever in the
        // store, causing a memory leak (100+ dead units after 10 waves).
        const TERMINAL_STATES = ['eliminated', 'destroyed', 'despawned'];
        if (TERMINAL_STATES.includes(update.status)) {
            const id = t.target_id;
            // Schedule removal — 5s for eliminated (kill effects), 2s for others
            const delay = update.status === 'eliminated' ? 5000 : 2000;
            setTimeout(() => TritiumStore.removeUnit(id), delay);
        }
    }

    _scheduleReconnect() {
        clearTimeout(this._reconnectTimer);
        this._reconnectTimer = setTimeout(() => {
            this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, this._maxDelay);
            this.connect();
        }, this._reconnectDelay);
    }

    /**
     * Route an incoming WebSocket message to the store and event bus.
     * @param {Object} msg - parsed JSON message
     */
    _handleMessage(msg) {
        const type = msg.type || msg.event;

        switch (type) {
            case 'amy_thought':
                TritiumStore.set('amy.lastThought', msg.text || msg.data?.text || '');
                EventBus.emit('amy:thought', msg.data || msg);
                break;

            case 'amy_speech':
                TritiumStore.set('amy.speaking', true);
                EventBus.emit('amy:speech', msg.data || msg);
                // Auto-clear speaking flag after estimated duration
                setTimeout(() => TritiumStore.set('amy.speaking', false), 5000);
                break;

            case 'amy_state':
                if (msg.data?.state) TritiumStore.set('amy.state', msg.data.state);
                if (msg.data?.mood) TritiumStore.set('amy.mood', msg.data.mood);
                EventBus.emit('amy:state', msg.data || msg);
                break;

            case 'amy_sim_telemetry':
            case 'sim_telemetry': {
                // Single target telemetry update
                const t = msg.data || msg;
                if (t && t.target_id) {
                    this._updateUnit(t);
                }
                EventBus.emit('units:updated', [t]);
                break;
            }

            case 'amy_sim_telemetry_batch': {
                // Batch of individual target updates (array in msg.data)
                const items = msg.data || [];
                if (Array.isArray(items)) {
                    for (const t of items) {
                        this._updateUnit(t);
                    }
                    EventBus.emit('units:updated', items);
                }
                break;
            }

            case 'game_state':
            case 'amy_game_state_change': {
                const d = msg.data || msg;
                if (d.state) TritiumStore.set('game.phase', d.state);
                if (d.wave !== undefined) TritiumStore.set('game.wave', d.wave);
                if (d.total_waves !== undefined) TritiumStore.set('game.totalWaves', d.total_waves);
                if (d.score !== undefined) TritiumStore.set('game.score', d.score);
                if (d.total_eliminations !== undefined) TritiumStore.set('game.eliminations', d.total_eliminations);
                else if (d.total_kills !== undefined) TritiumStore.set('game.eliminations', d.total_kills);
                EventBus.emit('game:state', d);
                if (typeof warHudUpdateGameState === 'function') {
                    warHudUpdateGameState(d);
                }
                break;
            }

            case 'amy_game_over': {
                const d = msg.data || msg;
                const phase = d.result === 'victory' ? 'victory' : 'defeat';
                TritiumStore.set('game.phase', phase);
                if (d.score !== undefined) TritiumStore.set('game.score', d.score);
                if (d.total_eliminations !== undefined) TritiumStore.set('game.eliminations', d.total_eliminations);
                else if (d.total_kills !== undefined) TritiumStore.set('game.eliminations', d.total_kills);
                EventBus.emit('game:state', { ...d, state: phase });
                if (typeof warHudShowGameOver === 'function') {
                    warHudShowGameOver(d.result, d.score, d.waves || d.wave, d.total_eliminations || d.total_kills);
                }
                break;
            }

            case 'game_elimination':
            case 'game_kill':
                EventBus.emit('game:elimination', msg.data || msg);
                break;

            case 'announcer':
                EventBus.emit('announcer', msg.data || msg);
                if (typeof warHudShowAmyAnnouncement === 'function') {
                    const d = msg.data || msg;
                    warHudShowAmyAnnouncement(d.text || d.message, d.category);
                }
                break;

            case 'robot_thought':
                EventBus.emit('robot:thought', msg.data || msg);
                break;

            case 'amy_npc_thought': {
                const d = msg.data || msg;
                const units = TritiumStore.units;
                const unit = units && units.get(d.unit_id);
                if (unit) {
                    unit.thoughtText = d.text;
                    unit.thoughtEmotion = d.emotion || 'neutral';
                    unit.thoughtDuration = d.duration || 5;
                    unit.thoughtExpires = Date.now() + unit.thoughtDuration * 1000;
                    if (!unit.thoughtHistory) unit.thoughtHistory = [];
                    unit.thoughtHistory.push({
                        text: d.text,
                        emotion: d.emotion || 'neutral',
                        time: Date.now(),
                    });
                    if (unit.thoughtHistory.length > 10) unit.thoughtHistory.shift();
                }
                EventBus.emit('npc:thought', d);
                break;
            }

            case 'amy_npc_thought_clear': {
                const d = msg.data || msg;
                const units = TritiumStore.units;
                const unit = units && units.get(d.unit_id);
                if (unit) {
                    delete unit.thoughtText;
                    delete unit.thoughtEmotion;
                    delete unit.thoughtExpires;
                }
                EventBus.emit('npc:thought_clear', d);
                break;
            }

            case 'escalation_change':
                TritiumStore.addAlert({
                    type: 'escalation',
                    message: msg.data?.message || 'Threat level changed',
                    source: 'escalation',
                });
                EventBus.emit('alert:new', msg.data || msg);
                break;

            case 'detection':
                // YOLO detection from camera
                EventBus.emit('detection', msg.data || msg);
                break;

            case 'projectile_fired':
            case 'amy_projectile_fired':
                if (typeof warCombatAddProjectile === 'function') {
                    warCombatAddProjectile(msg.data || msg);
                }
                EventBus.emit('combat:projectile', msg.data || msg);
                break;

            case 'projectile_hit':
            case 'amy_projectile_hit':
                if (typeof warCombatAddHitEffect === 'function') {
                    warCombatAddHitEffect(msg.data || msg);
                }
                EventBus.emit('combat:hit', msg.data || msg);
                break;

            case 'target_eliminated':
            case 'amy_target_eliminated':
                if (typeof warCombatAddEliminationEffect === 'function') {
                    warCombatAddEliminationEffect(msg.data || msg);
                }
                if (typeof warHudAddKillFeedEntry === 'function') {
                    warHudAddKillFeedEntry(msg.data || msg);
                }
                EventBus.emit('combat:elimination', msg.data || msg);
                break;

            case 'elimination_streak':
            case 'kill_streak':
            case 'amy_elimination_streak':
                if (typeof warCombatAddEliminationStreakEffect === 'function') {
                    warCombatAddEliminationStreakEffect(msg.data || msg);
                }
                EventBus.emit('combat:streak', msg.data || msg);
                break;

            case 'wave_start':
            case 'amy_wave_start': {
                if (typeof warHudShowWaveBanner === 'function') {
                    const d = msg.data || msg;
                    const briefingData = (d.briefing || d.threat_level || d.intel)
                        ? { briefing: d.briefing, threat_level: d.threat_level, intel: d.intel }
                        : null;
                    warHudShowWaveBanner(d.wave || d.wave_number, d.wave_name, d.hostile_count, briefingData);
                }
                EventBus.emit('game:wave_start', msg.data || msg);
                break;
            }

            case 'wave_complete':
            case 'amy_wave_complete': {
                if (typeof warHudShowWaveComplete === 'function') {
                    const d = msg.data || msg;
                    warHudShowWaveComplete(d.wave || d.wave_number, d.eliminations, d.score_bonus);
                }
                EventBus.emit('game:wave_complete', msg.data || msg);
                break;
            }

            case 'mesh_text':
                EventBus.emit('mesh:text', msg.data || msg);
                break;

            case 'mesh_position':
                EventBus.emit('mesh:position', msg.data || msg);
                break;

            case 'mesh_telemetry':
                EventBus.emit('mesh:telemetry', msg.data || msg);
                break;

            case 'mesh_connected':
                TritiumStore.set('mesh.connected', true);
                EventBus.emit('mesh:connected', msg.data || msg);
                break;

            case 'mesh_disconnected':
                TritiumStore.set('mesh.connected', false);
                EventBus.emit('mesh:disconnected', msg.data || msg);
                break;

            case 'mission_progress':
            case 'amy_mission_progress':
                EventBus.emit('mission:progress', msg.data || msg);
                break;

            case 'scenario_generated':
            case 'amy_scenario_generated':
                EventBus.emit('mission:scenario', msg.data || msg);
                break;

            default:
                // Forward unknown events for extensibility
                EventBus.emit(`ws:${type}`, msg.data || msg);
                break;
        }
    }
}
