// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// WebSocketManager -- manages connection to /ws/live with auto-reconnect
// Routes incoming messages to TritiumStore and EventBus
// Extends TritiumWebSocket (tritium-lib) for connect/reconnect/keepalive/banner.
//
// Usage:
//   import { WebSocketManager } from './websocket.js';
//   const ws = new WebSocketManager();
//   ws.connect();
//   ws.send({ type: 'ping' });

import { TritiumStore } from './store.js';
import { EventBus } from '/lib/events.js';
import { TritiumWebSocket } from '/lib/websocket.js';

export class WebSocketManager extends TritiumWebSocket {
    constructor() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws/live`;
        super(url, {
            initialDelay: 1000,
            maxDelay: 16000,
            pingInterval: 25000,
            onOpen: () => {
                console.log('%c[WS] Connected', 'color: #05ffa1;');
                TritiumStore.set('connection.status', 'connected');
                EventBus.emit('ws:connected');
                // Sync full state on every connect (covers initial load and
                // reconnects — events may have been missed during the gap).
                this._refreshState();
            },
            onClose: () => {
                console.log('%c[WS] Disconnected', 'color: #ff2a6d;');
                TritiumStore.set('connection.status', 'disconnected');
                EventBus.emit('ws:disconnected');
            },
            onError: (e) => {
                console.error('[WS] Error:', e);
                TritiumStore.set('connection.status', 'error');
            },
        });
    }

    /**
     * Close the WebSocket connection. Does not auto-reconnect.
     * Unlike the base class, allows reconnecting later via connect().
     */
    disconnect() {
        super.disconnect();
        // Allow subsequent connect() calls — base class sets _destroyed
        // to permanently prevent reconnection, but SC supports
        // disconnect/connect cycling.
        this._destroyed = false;
        TritiumStore.set('connection.status', 'disconnected');
    }

    /**
     * @returns {boolean} true if the WebSocket is open
     */
    get connected() {
        return this.isConnected;
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
        // Skip live telemetry updates while replaying historical frames
        if (TritiumStore.get('replay.active')) return;
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
        if (t.vision_range !== undefined) update.vision_range = t.vision_range;
        if (t.is_combatant !== undefined) update.isCombatant = t.is_combatant;
        // Vision and squad fields
        if (t.visible !== undefined) update.visible = t.visible;
        if (t.squad_id !== undefined) update.squadId = t.squad_id;
        if (t.detected_by !== undefined) update.detectedBy = t.detected_by;
        if (t.detected !== undefined) update.detected = t.detected;
        // Mission-specific fields
        if (t.crowd_role !== undefined) update.crowdRole = t.crowd_role;
        if (t.drone_variant !== undefined) update.droneVariant = t.drone_variant;
        if (t.ammo_count !== undefined) {
            update.ammoCount = t.ammo_count;
            // Clear ammo flags when ammo state updates from telemetry
            if (t.ammo_count > 0) update.ammoDepleted = false;
            if (t.ammo_max && t.ammo_count / t.ammo_max > 0.2) update.ammoLow = false;
        }
        if (t.ammo_max !== undefined) update.ammoMax = t.ammo_max;
        if (t.weapon_cooldown !== undefined) update.weaponCooldown = t.weapon_cooldown;
        if (t.altitude !== undefined) update.altitude = t.altitude;
        if (t.instigator_state !== undefined) update.instigatorState = t.instigator_state;
        if (t.identified !== undefined) update.identified = t.identified;
        // Rich identity data
        if (t.identity !== undefined) update.identity = t.identity;
        // Radio detection (BLE/WiFi/cell through-wall tracking)
        if (t.radio_detected !== undefined) update.radio_detected = t.radio_detected;
        if (t.radio_signal_strength !== undefined) update.radio_signal_strength = t.radio_signal_strength;
        // Source classification (sim, real, graphling)
        if (t.source !== undefined) update.source = t.source;
        // Multi-source fusion fields (correlated targets)
        if (t.sources !== undefined) update.sources = t.sources;
        if (t.source_count !== undefined) update.source_count = t.source_count;
        if (t.confirming_sources !== undefined) {
            update.sources = t.confirming_sources;
            update.source_count = t.confirming_sources.length;
        }
        if (t.correlated_ids !== undefined) update.correlated_ids = t.correlated_ids;
        if (t.correlation_confidence !== undefined) update.correlation_confidence = t.correlation_confidence;
        // Position confidence for rendering
        if (t.position_confidence !== undefined) update.position_confidence = t.position_confidence;
        if (t.position_source !== undefined) update.position_source = t.position_source;
        // Patrol route fields
        if (t.waypoints !== undefined) update.waypoints = t.waypoints;
        if (t.loop_waypoints !== undefined) update.loopWaypoints = t.loop_waypoints;
        // Inventory system
        if (t.inventory !== undefined) update.inventory = t.inventory;
        // Per-unit combat stats from StatsTracker
        if (t.stats) update.stats = t.stats;
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

    /**
     * Fetch full game state and unit positions from the REST API.
     * Called on every WS connect to fill gaps from missed events during
     * disconnection (or to hydrate initial state on page load).
     */
    async _refreshState() {
        try {
            const [gameRes, targetsRes] = await Promise.all([
                fetch('/api/game/state'),
                fetch('/api/targets'),
            ]);
            if (gameRes.ok) {
                const game = await gameRes.json();
                if (game.state) TritiumStore.set('game.phase', game.state);
                if (game.wave !== undefined) TritiumStore.set('game.wave', game.wave);
                if (game.total_waves !== undefined) TritiumStore.set('game.totalWaves', game.total_waves);
                if (game.score !== undefined) TritiumStore.set('game.score', game.score);
                if (game.total_eliminations !== undefined) TritiumStore.set('game.eliminations', game.total_eliminations);
                if (game.wave_name !== undefined) TritiumStore.set('game.waveName', game.wave_name);
                if (game.countdown !== undefined) TritiumStore.set('game.countdown', game.countdown);
                if (game.wave_hostiles_remaining !== undefined) TritiumStore.set('game.waveHostilesRemaining', game.wave_hostiles_remaining);
                if (game.difficulty_multiplier !== undefined) TritiumStore.set('game.difficultyMultiplier', game.difficulty_multiplier);
                if (game.game_mode_type) TritiumStore.set('game.modeType', game.game_mode_type);
                // Mode-specific fields (civil_unrest, drone_swarm)
                if (game.de_escalation_score !== undefined) TritiumStore.set('game.deEscalationScore', game.de_escalation_score);
                if (game.civilian_harm_count !== undefined) TritiumStore.set('game.civilianHarmCount', game.civilian_harm_count);
                if (game.civilian_harm_limit !== undefined) TritiumStore.set('game.civilianHarmLimit', game.civilian_harm_limit);
                if (game.weighted_total_score !== undefined) TritiumStore.set('game.weightedTotalScore', game.weighted_total_score);
                if (game.infrastructure_health !== undefined) TritiumStore.set('game.infrastructureHealth', game.infrastructure_health);
                if (game.infrastructure_max !== undefined) TritiumStore.set('game.infrastructureMax', game.infrastructure_max);
            }
            if (targetsRes.ok) {
                const data = await targetsRes.json();
                // API returns { targets: [...], summary: "..." }
                const targets = Array.isArray(data) ? data : (data.targets || []);
                for (const t of targets) {
                    this._updateUnit(t);
                }
            }
        } catch (e) {
            console.warn('[WS] State refresh failed:', e);
        }
    }

    /**
     * Route an incoming WebSocket message to the store and event bus.
     * Overrides TritiumWebSocket._handleMessage for SC-specific routing.
     * @param {Object} msg - parsed JSON message
     */
    _handleMessage(msg) {
        const type = msg.type || msg.event;

        switch (type) {
            case 'ping':
                // Server-initiated heartbeat — respond with pong
                this.send({ type: 'pong' });
                return;

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

            case 'amy_transcript': {
                // Transcript events carry {speaker, text} from Amy's event bus.
                // When speaker is 'amy', route to chat as Amy's response.
                const td = msg.data || msg;
                if (td.speaker === 'amy') {
                    EventBus.emit('chat:amy_response', { text: td.text });
                }
                break;
            }

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
            case 'game_state_change':
            case 'amy_game_state_change': {
                const d = msg.data || msg;
                if (d.state) TritiumStore.set('game.phase', d.state);
                if (d.wave !== undefined) TritiumStore.set('game.wave', d.wave);
                if (d.total_waves !== undefined) TritiumStore.set('game.totalWaves', d.total_waves);
                if (d.score !== undefined) TritiumStore.set('game.score', d.score);
                if (d.total_eliminations !== undefined) TritiumStore.set('game.eliminations', d.total_eliminations);
                else if (d.total_kills !== undefined) TritiumStore.set('game.eliminations', d.total_kills);
                if (d.wave_name !== undefined) TritiumStore.set('game.waveName', d.wave_name);
                if (d.countdown !== undefined) TritiumStore.set('game.countdown', d.countdown);
                if (d.wave_hostiles_remaining !== undefined) TritiumStore.set('game.waveHostilesRemaining', d.wave_hostiles_remaining);
                if (d.difficulty_multiplier !== undefined) TritiumStore.set('game.difficultyMultiplier', d.difficulty_multiplier);
                if (d.spawn_direction) TritiumStore.set('game.waveDirection', d.spawn_direction);
                // Idle = initial state before any game.  Full reset clears
                // units, score, overlays, and all per-game state so stale
                // data from a previous session cannot leak into the next game.
                // Setup = backend reset after a game; do NOT clear units
                // because defenders are being placed, but still clear overlays.
                if (d.state === 'idle') {
                    TritiumStore.resetGameState();
                } else if (d.state === 'setup') {
                    // Exit replay mode so live telemetry is not blocked
                    TritiumStore.set('replay.active', false);
                    // Clear per-game overlays but preserve units
                    TritiumStore.set('hazards', new Map());
                    TritiumStore.set('game.hostileIntel', null);
                    TritiumStore.set('game.hostileObjectives', null);
                    TritiumStore.set('game.crowdDensity', null);
                    TritiumStore.set('game.coverPoints', []);
                    TritiumStore.set('game.signals', []);
                    TritiumStore.set('game.modeType', null);
                    TritiumStore.set('game.infrastructureHealth', null);
                    TritiumStore.set('game.infrastructureMax', null);
                    TritiumStore.set('game.deEscalationScore', null);
                    TritiumStore.set('game.civilianHarmCount', null);
                    TritiumStore.set('game.civilianHarmLimit', null);
                    TritiumStore.set('game.weightedTotalScore', null);
                }
                // Mission mode type and mode-specific fields
                if (d.game_mode_type) TritiumStore.set('game.modeType', d.game_mode_type);
                if (d.infrastructure_health !== undefined) TritiumStore.set('game.infrastructureHealth', d.infrastructure_health);
                if (d.infrastructure_max !== undefined) TritiumStore.set('game.infrastructureMax', d.infrastructure_max);
                if (d.de_escalation_score !== undefined) TritiumStore.set('game.deEscalationScore', d.de_escalation_score);
                if (d.civilian_harm_count !== undefined) TritiumStore.set('game.civilianHarmCount', d.civilian_harm_count);
                if (d.civilian_harm_limit !== undefined) TritiumStore.set('game.civilianHarmLimit', d.civilian_harm_limit);
                if (d.weighted_total_score !== undefined) TritiumStore.set('game.weightedTotalScore', d.weighted_total_score);
                EventBus.emit('game:state', d);
                // Route through warHandle* for audio hooks
                if (typeof window.warHandleGameState === 'function') {
                    window.warHandleGameState(d);
                }
                // Always update HUD state (warHandleGameState may not propagate to warHudUpdateGameState
                // when war.js is not loaded, e.g. in Command Center view)
                if (typeof window.warHudUpdateGameState === 'function') {
                    window.warHudUpdateGameState(d);
                }
                // Trigger countdown audio when entering countdown state
                if (d.state === 'countdown' && typeof window.warHandleCountdown === 'function') {
                    window.warHandleCountdown(d);
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
                const stateData = { ...d, state: phase };
                EventBus.emit('game:state', stateData);
                // Update HUD game state so _hudState.gameState reflects victory/defeat
                if (typeof window.warHandleGameState === 'function') {
                    window.warHandleGameState(stateData);
                }
                // Route through warHandle* for audio hooks (victory/defeat sounds)
                if (typeof window.warHandleGameOver === 'function') {
                    window.warHandleGameOver(d);
                }
                if (typeof window.warHudShowGameOver === 'function') {
                    // Pass mode-specific data as 5th argument for
                    // civil_unrest/drone_swarm game mode HUD rendering
                    const modeData = {
                        game_mode_type: d.game_mode_type,
                        reason: d.reason,
                        de_escalation_score: d.de_escalation_score,
                        civilian_harm_count: d.civilian_harm_count,
                        civilian_harm_limit: d.civilian_harm_limit,
                        weighted_total_score: d.weighted_total_score,
                        infrastructure_health: d.infrastructure_health,
                        infrastructure_max: d.infrastructure_max,
                    };
                    // Backend sends 'wave' (singular); normalize to support both
                    const wavesCompleted = d.waves || d.wave || 0;
                    window.warHudShowGameOver(d.result, d.score, wavesCompleted, d.total_eliminations || d.total_kills, modeData);
                }
                break;
            }

            case 'target_eliminated':
            case 'amy_target_eliminated':
            case 'game_elimination':
            case 'game_kill':
            case 'amy_game_elimination':
            case 'amy_game_kill':
                // Route through warHandle* for audio hooks (war-events.js patches
                // these even when war.js is absent, so this always fires audio)
                if (typeof window.warHandleTargetEliminated === 'function') {
                    window.warHandleTargetEliminated(msg.data || msg);
                }
                // Always add elimination effect + kill feed entry.
                // In Command Center (unified.html), war.js is NOT loaded so the
                // warHandle* above only fires audio via war-events.js.  The visual
                // effect + kill feed must be called unconditionally here.
                if (typeof window.warCombatAddEliminationEffect === 'function') {
                    window.warCombatAddEliminationEffect(msg.data || msg);
                }
                if (typeof window.warHudAddKillFeedEntry === 'function') {
                    window.warHudAddKillFeedEntry(msg.data || msg);
                }
                EventBus.emit('combat:elimination', msg.data || msg);
                EventBus.emit('game:elimination', msg.data || msg);
                {
                    const ed = msg.data || msg;
                    TritiumStore.addAlert({
                        type: 'combat',
                        message: `${ed.interceptor_name || 'Unit'} eliminated ${ed.target_name || 'hostile'}`,
                        source: 'combat',
                    });
                }
                break;

            case 'announcer':
            case 'amy_announcer':
            case 'amy_announcement': {
                const d = msg.data || msg;
                // Normalize: some messages use 'message' instead of 'text'
                if (!d.text && d.message) d.text = d.message;
                EventBus.emit('announcer', d);
                // Route through warHandle* for audio hooks
                if (typeof window.warHandleAmyAnnouncement === 'function') {
                    window.warHandleAmyAnnouncement(d);
                } else if (typeof window.warHudShowAmyAnnouncement === 'function') {
                    window.warHudShowAmyAnnouncement(d.text, d.category);
                }
                break;
            }

            case 'robot_thought':
            case 'amy_robot_thought':
                EventBus.emit('robot:thought', msg.data || msg);
                break;

            case 'npc_thought':
            case 'amy_npc_thought': {
                const d = msg.data || msg;
                const importance = d.importance || 'normal';
                const units = TritiumStore.units;
                const unit = units && units.get(d.unit_id);
                if (unit) {
                    // Always store the latest thought (accessible via click-to-view)
                    unit.latestThought = {
                        text: d.text,
                        emotion: d.emotion || 'neutral',
                        importance: importance,
                        duration: d.duration || 5,
                        time: Date.now(),
                    };

                    // Always append to history
                    if (!unit.thoughtHistory) unit.thoughtHistory = [];
                    unit.thoughtHistory.push({
                        text: d.text,
                        emotion: d.emotion || 'neutral',
                        importance: importance,
                        time: Date.now(),
                    });
                    if (unit.thoughtHistory.length > 10) unit.thoughtHistory.shift();

                    // Only auto-display thought bubbles for high/critical importance.
                    // The backend only broadcasts high+ thoughts, but double-check here.
                    const _VISIBLE_IMPORTANCE = { high: true, critical: true };
                    if (_VISIBLE_IMPORTANCE[importance]) {
                        unit.thoughtText = d.text;
                        unit.thoughtEmotion = d.emotion || 'neutral';
                        unit.thoughtImportance = importance;
                        unit.thoughtDuration = d.duration || 5;
                        unit.thoughtExpires = Date.now() + (d.duration || 5) * 1000;
                    }
                    // If this is the selected unit, always show it regardless of importance
                    const selectedId = TritiumStore.get('map.selectedUnitId');
                    if (selectedId === d.unit_id) {
                        unit.thoughtText = d.text;
                        unit.thoughtEmotion = d.emotion || 'neutral';
                        unit.thoughtImportance = importance;
                        unit.thoughtDuration = d.duration || 5;
                        unit.thoughtExpires = Date.now() + (d.duration || 5) * 1000;
                    }
                    // Trigger store notification so detail panel updates
                    TritiumStore._scheduleNotify('units');
                }
                EventBus.emit('npc:thought', d);
                break;
            }

            case 'npc_thought_clear':
            case 'amy_npc_thought_clear': {
                const d = msg.data || msg;
                const units = TritiumStore.units;
                const unit = units && units.get(d.unit_id);
                if (unit) {
                    delete unit.thoughtText;
                    delete unit.thoughtEmotion;
                    delete unit.thoughtExpires;
                    TritiumStore._scheduleNotify('units');
                }
                EventBus.emit('npc:thought_clear', d);
                break;
            }

            case 'escalation_change':
            case 'amy_escalation_change': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'escalation',
                    message: d.message || 'Threat level changed',
                    source: 'escalation',
                });
                // Route through warHandle* for audio hooks (escalation siren)
                if (typeof window.warHandleThreatEscalation === 'function') {
                    window.warHandleThreatEscalation(d);
                }
                EventBus.emit('alert:new', d);
                EventBus.emit('escalation:change', d);
                break;
            }

            case 'amy_alert': {
                const ad = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'amy_alert',
                    message: ad.message || 'Amy alert',
                    source: 'amy',
                });
                EventBus.emit('alert:new', ad);
                EventBus.emit('amy:alert', ad);
                break;
            }

            case 'amy_dispatch': {
                const dd = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'dispatch',
                    message: `Dispatched ${dd.name || dd.target_id || 'unit'}`,
                    source: 'amy',
                });
                EventBus.emit('alert:new', dd);
                EventBus.emit('amy:dispatch', dd);
                break;
            }

            case 'detection':
            case 'amy_detection':
            case 'amy_detections':
                // YOLO detection from camera
                EventBus.emit('detection', msg.data || msg);
                break;

            case 'projectile_fired':
            case 'amy_projectile_fired':
                // Route through warHandle* so war-events.js audio hooks fire
                if (typeof window.warHandleProjectileFired === 'function') {
                    window.warHandleProjectileFired(msg.data || msg);
                } else if (typeof window.warCombatAddProjectile === 'function') {
                    window.warCombatAddProjectile(msg.data || msg);
                }
                EventBus.emit('combat:projectile', msg.data || msg);
                break;

            case 'projectile_hit':
            case 'amy_projectile_hit':
                if (typeof window.warHandleProjectileHit === 'function') {
                    window.warHandleProjectileHit(msg.data || msg);
                } else if (typeof window.warCombatAddHitEffect === 'function') {
                    window.warCombatAddHitEffect(msg.data || msg);
                }
                EventBus.emit('combat:hit', msg.data || msg);
                break;

            case 'elimination_streak':
            case 'kill_streak':
            case 'amy_elimination_streak':
                if (typeof window.warHandleEliminationStreak === 'function') {
                    window.warHandleEliminationStreak(msg.data || msg);
                } else if (typeof window.warCombatAddEliminationStreakEffect === 'function') {
                    window.warCombatAddEliminationStreakEffect(msg.data || msg);
                }
                EventBus.emit('combat:streak', msg.data || msg);
                break;

            case 'wave_start':
            case 'amy_wave_start': {
                const d = msg.data || msg;
                // Route through warHandle* for audio hooks
                if (typeof window.warHandleWaveStart === 'function') {
                    window.warHandleWaveStart(d);
                }
                if (typeof window.warHudShowWaveBanner === 'function') {
                    const briefingData = (d.briefing || d.threat_level || d.intel)
                        ? { briefing: d.briefing, threat_level: d.threat_level, intel: d.intel }
                        : null;
                    window.warHudShowWaveBanner(d.wave || d.wave_number, d.wave_name, d.hostile_count, briefingData);
                }
                TritiumStore.addAlert({
                    type: 'warning',
                    message: `WAVE ${d.wave_number || d.wave || '?'} INCOMING — ${d.hostile_count || '?'} hostiles`,
                    source: 'game',
                });
                // Store wave direction for late-joining browsers
                if (d.spawn_direction) TritiumStore.set('game.waveDirection', d.spawn_direction);
                EventBus.emit('game:wave_start', d);
                break;
            }

            case 'wave_complete':
            case 'amy_wave_complete': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'info',
                    message: `WAVE ${d.wave_number || d.wave || '?'} CLEAR`,
                    source: 'game',
                });
                // Route through warHandle* for audio hooks
                if (typeof window.warHandleWaveComplete === 'function') {
                    window.warHandleWaveComplete(d);
                }
                if (typeof window.warHudShowWaveComplete === 'function') {
                    window.warHudShowWaveComplete(d.wave || d.wave_number, d.eliminations, d.score_bonus);
                }
                // Clear wave direction on completion, store next if available
                TritiumStore.set('game.waveDirection', d.next_spawn_direction || null);
                EventBus.emit('game:wave_complete', d);
                break;
            }

            case 'unit_dispatched':
            case 'amy_unit_dispatched': {
                const d = msg.data || msg;
                const unitId = d.unit_id || d.target_id;
                // Route through warHandle* for dispatch arrow + audio (legacy canvas)
                if (typeof window.warHandleDispatch === 'function') {
                    window.warHandleDispatch({
                        target_id: unitId,
                        destination: d.destination,
                    });
                }
                // Emit unit:dispatched so MapLibre map draws dispatch arrows
                if (d.destination) {
                    EventBus.emit('unit:dispatched', {
                        id: unitId,
                        target: { x: d.destination.x, y: d.destination.y },
                    });
                }
                EventBus.emit('game:dispatch', d);
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

            // -- TAK bridge events ------------------------------------------
            case 'tak_connected':
                EventBus.emit('tak:connected', msg.data || msg);
                break;

            case 'tak_disconnected':
                EventBus.emit('tak:disconnected', msg.data || msg);
                break;

            case 'tak_client_update':
                EventBus.emit('tak:client_update', msg.data || msg);
                break;

            case 'tak_geochat':
                EventBus.emit('tak:geochat', msg.data || msg);
                break;

            // -- Fleet bridge events (tritium-edge sensor nodes) --------
            case 'fleet_heartbeat':
                EventBus.emit('fleet:heartbeat', msg.data || msg);
                break;

            case 'fleet_device_update':
                EventBus.emit('fleet:device_update', msg.data || msg);
                break;

            case 'fleet_ble_presence':
                EventBus.emit('fleet:ble_presence', msg.data || msg);
                break;

            case 'fleet_registered':
                EventBus.emit('fleet:registered', msg.data || msg);
                break;

            case 'fleet_offline':
                EventBus.emit('fleet:offline', msg.data || msg);
                break;

            case 'fleet_connected':
                EventBus.emit('fleet:connected', msg.data || msg);
                break;

            case 'fleet_disconnected':
                EventBus.emit('fleet:disconnected', msg.data || msg);
                break;

            case 'mission_progress':
            case 'amy_mission_progress':
                EventBus.emit('mission:progress', msg.data || msg);
                break;

            case 'scenario_generated':
            case 'amy_scenario_generated':
                EventBus.emit('mission:scenario', msg.data || msg);
                break;

            case 'backstory_generated':
            case 'amy_backstory_generated': {
                const d = msg.data || msg;
                const targetId = d.target_id;
                const backstory = d.backstory;
                if (targetId && backstory) {
                    const update = {};
                    if (backstory.name) update.backstoryName = backstory.name;
                    if (backstory.background) update.backstoryBackground = backstory.background;
                    if (backstory.motivation) update.backstoryMotivation = backstory.motivation;
                    if (backstory.personality_traits) update.backstoryTraits = backstory.personality_traits;
                    if (backstory.speech_pattern) update.backstorySpeechPattern = backstory.speech_pattern;
                    if (backstory.tactical_preference) update.backstoryTacticalPref = backstory.tactical_preference;
                    if (backstory.neighborhood_relationship) update.backstoryNeighborhood = backstory.neighborhood_relationship;
                    if (backstory.daily_routine) update.backstoryRoutine = backstory.daily_routine;
                    // Update the unit name to the backstory-generated name
                    if (backstory.name) update.name = backstory.name;
                    // Rich identity data from backstory
                    if (backstory.identity) update.identity = backstory.identity;
                    TritiumStore.updateUnit(targetId, update);
                }
                EventBus.emit('unit:backstory', d);
                break;
            }

            // Mission-specific events (civil_unrest + drone_swarm)
            // Bridge sends these with amy_ prefix; handle both variants.
            case 'crowd_density':
            case 'amy_crowd_density': {
                const d = msg.data || msg;
                TritiumStore.set('game.crowdDensity', d);
                EventBus.emit('mission:crowd_density', d);
                break;
            }

            case 'infrastructure_damage':
            case 'amy_infrastructure_damage': {
                const d = msg.data || msg;
                if (d.infrastructure_health !== undefined) TritiumStore.set('game.infrastructureHealth', d.infrastructure_health);
                if (d.infrastructure_max !== undefined) TritiumStore.set('game.infrastructureMax', d.infrastructure_max);
                EventBus.emit('mission:infrastructure_damage', d);
                break;
            }

            case 'civilian_harmed':
            case 'amy_civilian_harmed': {
                const d = msg.data || msg;
                if (d.civilian_harm_count !== undefined) TritiumStore.set('game.civilianHarmCount', d.civilian_harm_count);
                if (d.civilian_harm_limit !== undefined) TritiumStore.set('game.civilianHarmLimit', d.civilian_harm_limit);
                EventBus.emit('mission:civilian_harmed', d);
                break;
            }

            case 'bomber_detonation':
            case 'amy_bomber_detonation':
                EventBus.emit('mission:bomber_detonation', msg.data || msg);
                break;

            case 'de_escalation':
            case 'amy_de_escalation': {
                const d = msg.data || msg;
                if (d.de_escalation_score !== undefined) TritiumStore.set('game.deEscalationScore', d.de_escalation_score);
                EventBus.emit('mission:de_escalation', d);
                break;
            }

            case 'infrastructure_overwhelmed':
            case 'amy_infrastructure_overwhelmed':
                EventBus.emit('mission:infrastructure_overwhelmed', msg.data || msg);
                break;

            case 'instigator_identified':
            case 'amy_instigator_identified':
                EventBus.emit('mission:instigator_identified', msg.data || msg);
                break;

            case 'emp_activated':
            case 'amy_emp_activated':
                EventBus.emit('mission:emp_activated', msg.data || msg);
                break;

            case 'auto_dispatch_speech':
            case 'amy_auto_dispatch_speech': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'dispatch',
                    message: d.text || 'Unit dispatched',
                    source: 'auto_dispatch',
                });
                EventBus.emit('dispatch:speech', d);
                break;
            }

            case 'zone_violation':
            case 'amy_zone_violation': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'zone',
                    message: `Zone breach: ${d.zone_name || 'unknown'} (${d.zone_type || ''})`,
                    source: 'zone',
                });
                EventBus.emit('zone:violation', d);
                break;
            }

            case 'amy_geofence:enter':
            case 'geofence:enter': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'geofence',
                    message: `ENTER: ${d.target_id || '?'} entered ${d.zone_name || d.zone_id || '?'} (${d.zone_type || 'monitored'})`,
                    source: 'geofence',
                    severity: d.zone_type === 'restricted' ? 'critical' : 'warning',
                    data: d,
                });
                EventBus.emit('geofence:enter', d);
                EventBus.emit('notification:geofence', {
                    direction: 'enter',
                    target_id: d.target_id,
                    zone_name: d.zone_name || d.zone_id,
                    zone_type: d.zone_type || 'monitored',
                    timestamp: d.timestamp,
                });
                break;
            }

            case 'amy_geofence:exit':
            case 'geofence:exit': {
                const d = msg.data || msg;
                TritiumStore.addAlert({
                    type: 'geofence',
                    message: `EXIT: ${d.target_id || '?'} exited ${d.zone_name || d.zone_id || '?'}`,
                    source: 'geofence',
                    severity: 'info',
                    data: d,
                });
                EventBus.emit('geofence:exit', d);
                EventBus.emit('notification:geofence', {
                    direction: 'exit',
                    target_id: d.target_id,
                    zone_name: d.zone_name || d.zone_id,
                    zone_type: d.zone_type || 'monitored',
                    timestamp: d.timestamp,
                });
                break;
            }

            case 'formation_created':
            case 'amy_formation_created':
                EventBus.emit('formation:created', msg.data || msg);
                break;

            case 'mode_change':
            case 'amy_mode_change':
                EventBus.emit('amy:mode_change', msg.data || msg);
                break;

            case 'upgrade_applied':
            case 'amy_upgrade_applied': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit) {
                        if (!unit.upgrades) unit.upgrades = [];
                        if (d.upgrade_id) unit.upgrades.push(d.upgrade_id);
                    }
                }
                EventBus.emit('upgrade:applied', d);
                break;
            }

            case 'ability_activated':
            case 'amy_ability_activated': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit) {
                        if (!unit.activeAbilities) unit.activeAbilities = [];
                        unit.activeAbilities.push({
                            ability_id: d.ability_id,
                            remaining: d.duration || 0,
                        });
                    }
                }
                EventBus.emit('ability:activated', d);
                break;
            }

            case 'ability_expired':
            case 'amy_ability_expired': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit && unit.activeAbilities) {
                        unit.activeAbilities = unit.activeAbilities.filter(
                            a => a.ability_id !== d.ability_id
                        );
                    }
                }
                EventBus.emit('ability:expired', d);
                break;
            }

            case 'npc_alliance_change':
            case 'amy_npc_alliance_change': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit && d.new_alliance) {
                        unit.alliance = d.new_alliance;
                    }
                }
                EventBus.emit('npc:alliance_change', d);
                break;
            }

            case 'weapon_jam':
            case 'amy_weapon_jam': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit) {
                        unit.weaponJammed = true;
                        // Auto-clear after 3s if not re-fired (jam is per-tick event)
                        unit._weaponJamTimer && clearTimeout(unit._weaponJamTimer);
                        unit._weaponJamTimer = setTimeout(() => {
                            unit.weaponJammed = false;
                            delete unit._weaponJamTimer;
                        }, 3000);
                    }
                }
                EventBus.emit('combat:weapon_jam', d);
                break;
            }

            case 'ammo_low':
            case 'amy_ammo_low': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit) {
                        unit.ammoLow = true;
                    }
                }
                EventBus.emit('combat:ammo_low', d);
                break;
            }

            case 'ammo_depleted':
            case 'amy_ammo_depleted': {
                const d = msg.data || msg;
                if (d.unit_id) {
                    const unit = TritiumStore.units.get(d.unit_id);
                    if (unit) {
                        unit.ammoDepleted = true;
                    }
                }
                EventBus.emit('combat:ammo_depleted', d);
                break;
            }

            // -- Environmental hazards --
            case 'hazard_spawned':
            case 'amy_hazard_spawned': {
                const d = msg.data || msg;
                const hid = d.hazard_id || d.id;
                if (hid) {
                    let hazards = TritiumStore.get('hazards');
                    if (!hazards) {
                        hazards = new Map();
                        TritiumStore.set('hazards', hazards);
                    }
                    hazards.set(hid, {
                        hazard_id: hid,
                        hazard_type: d.hazard_type,
                        position: d.position,
                        radius: d.radius,
                        duration: d.duration,
                        spawned_at: Date.now(),
                    });
                    TritiumStore._scheduleNotify('hazards');
                }
                EventBus.emit('hazard:spawned', d);
                break;
            }

            case 'hazard_expired':
            case 'amy_hazard_expired': {
                const d = msg.data || msg;
                const hid = d.hazard_id || d.id;
                if (hid) {
                    const hazards = TritiumStore.get('hazards');
                    if (hazards) {
                        hazards.delete(hid);
                        TritiumStore._scheduleNotify('hazards');
                    }
                }
                EventBus.emit('hazard:expired', d);
                break;
            }

            // -- Sensor network --
            case 'sensor_triggered':
            case 'amy_sensor_triggered':
                EventBus.emit('sensor:triggered', msg.data || msg);
                break;

            case 'sensor_cleared':
            case 'amy_sensor_cleared':
                EventBus.emit('sensor:cleared', msg.data || msg);
                break;

            case 'target_neutralized':
            case 'amy_target_neutralized': {
                const d = msg.data || msg;
                const tid = d.target_id || d.unit_id;
                if (tid) {
                    const unit = TritiumStore.units.get(tid);
                    if (unit) {
                        unit.status = 'neutralized';
                    }
                }
                EventBus.emit('combat:neutralized', d);
                break;
            }

            // -- Hostile Commander Intel --
            case 'hostile_intel':
            case 'amy_hostile_intel': {
                const d = msg.data || msg;
                if (d) TritiumStore.set('game.hostileIntel', d);
                EventBus.emit('hostile:intel', d);
                break;
            }

            // -- Bonus objective completion --
            case 'bonus_objective_completed':
            case 'amy_bonus_objective_completed': {
                const d = msg.data || msg;
                if (typeof window.warHudCompleteBonusObjective === 'function') {
                    window.warHudCompleteBonusObjective(d.name);
                }
                EventBus.emit('objective:completed', d);
                break;
            }

            case 'cover_points':
            case 'amy_cover_points': {
                const d = msg.data || msg;
                if (d && Array.isArray(d.points)) {
                    TritiumStore.set('game.coverPoints', d.points);
                }
                break;
            }

            case 'unit_signal':
            case 'amy_unit_signal': {
                const d = msg.data || msg;
                if (d && d.signal_type && d.position) {
                    // Store active signals as a list (auto-expire via TTL)
                    let signals = TritiumStore.get('game.signals');
                    if (!Array.isArray(signals)) signals = [];
                    signals.push({
                        signal_type: d.signal_type,
                        sender_id: d.sender_id,
                        sender_alliance: d.sender_alliance,
                        position: d.position,
                        target_position: d.target_position,
                        signal_range: d.signal_range || 50,
                        ttl: d.ttl || 10,
                        received_at: Date.now(),
                    });
                    TritiumStore.set('game.signals', signals);
                }
                EventBus.emit('unit:signal', d);
                break;
            }

            // -- City-sim sensor bridge sightings --------------------------
            case 'sim_sighting_batch': {
                const items = msg.data || [];
                if (Array.isArray(items)) {
                    EventBus.emit('sim:sightings', items);
                }
                break;
            }

            // -- Edge tracker BLE updates --------------------------------
            case 'amy_edge:ble_update':
                EventBus.emit('edge:ble_update', msg.data || msg);
                break;

            // -- Edge tracker WiFi updates --------------------------------
            case 'amy_edge:wifi_update':
                EventBus.emit('edge:wifi_update', msg.data || msg);
                break;

            // -- Notifications ------------------------------------
            case 'notification:new':
                EventBus.emit('notification:new', msg.data || msg);
                break;

            // -- Operator cursor sharing ----------------------------
            case 'cursor_position': {
                // Another operator's cursor position and viewport on the map
                const cursor = msg;
                const cursorData = {
                    session_id: cursor.session_id,
                    username: cursor.username,
                    display_name: cursor.display_name,
                    role: cursor.role,
                    color: cursor.color,
                    lat: cursor.lat,
                    lng: cursor.lng,
                    timestamp: cursor.timestamp,
                };
                // Include viewport data if present (zoom, bounds, label)
                if (cursor.zoom !== undefined) cursorData.zoom = cursor.zoom;
                if (cursor.bounds) cursorData.bounds = cursor.bounds;
                if (cursor.viewport_label) cursorData.viewport_label = cursor.viewport_label;
                TritiumStore.setOperatorCursor(cursor.session_id, cursorData);
                EventBus.emit('operator:cursor', cursorData);
                break;
            }

            default:
                // Forward unknown events for extensibility
                if (type) {
                    EventBus.emit(`ws:${type}`, msg.data || msg);
                }
                break;
        }
    }
}
