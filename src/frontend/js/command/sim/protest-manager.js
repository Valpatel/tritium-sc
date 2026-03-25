// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * ProtestManager — wires the Epstein protest engine into the SC city sim.
 *
 * Manages the lifecycle of a protest event:
 * 1. Select NPCs as potential protestors (based on hardship/personality)
 * 2. Register them with the ProtestEngine
 * 3. Each tick: feed positions, get goals, override NPC routines
 * 4. Spawn police response when crowd grows
 * 5. Emit phase transition events for Commander/UI (Amy or any commander plugin)
 */

import { ProtestEngine } from '/lib/sim/protest-engine.js';
import { PHASES } from '/lib/sim/protest-scenario.js';
import { EventBus } from '/lib/events.js';

export class ProtestManager {
    constructor() {
        this.engine = null;
        this.active = false;
        this._lastPhase = null;
        this._protestorIds = new Set();
        this._policeIds = new Set();
        this._plazaCenter = null;
    }

    /**
     * Start a protest event.
     * @param {Object} config
     * @param {Array<SimPedestrian>} pedestrians — all city NPCs
     * @param {Object} config.plazaCenter — {x, z} gathering point
     * @param {number} config.participantCount — target number of protestors
     * @param {number} [config.legitimacy=0.5] — government legitimacy (lower = more unrest)
     * @param {number} [config.escalationSpeed=1.0]
     */
    start(pedestrians, config = {}) {
        const plazaCenter = config.plazaCenter || { x: 0, z: 0 };
        const participantCount = config.participantCount || Math.min(50, Math.floor(pedestrians.length * 0.5));
        const legitimacy = config.legitimacy ?? 0.5;

        this._plazaCenter = plazaCenter;

        this.engine = new ProtestEngine({
            legitimacy,
            threshold: 0.1,
            maxJailTerm: 120,
            plazaCenter,
            plazaRadius: 30,
            policeStation: config.policeStation || { x: plazaCenter.x + 100, z: plazaCenter.z - 100 },
        });

        // Select participants: NPCs with highest hardship (including those in buildings — they'll exit)
        const candidates = [...pedestrians]
            .filter(p => p.alive)
            .sort((a, b) => (b.personality?.hardship || 0) - (a.personality?.hardship || 0));

        const selected = candidates.slice(0, participantCount);
        this._protestorIds = new Set(selected.map(p => p.id));

        for (const ped of selected) {
            this.engine.registerAgent(ped.id, ped.personality?.hardship, ped.personality?.riskAversion);
            // Force NPCs out of buildings — they're heading to the protest
            if (ped.inBuilding) {
                ped.inBuilding = false;
                ped.visible = true;
                // Place them at their building entry
                ped.x = ped.homeEntry?.x || ped.x;
                ped.z = ped.homeEntry?.z || ped.z;
            }
            // Override: start marching to plaza immediately
            ped.overrideGoal = {
                action: 'go_to',
                target: plazaCenter,
                speed: 2.0,
                source: 'protest',
            };
            ped.mood = 'angry';
            ped.color = 0xff8844;
        }

        this.engine.start();
        this.active = true;
        this._lastPhase = null;

        console.log(`[ProtestManager] Protest started at (${plazaCenter.x.toFixed(0)}, ${plazaCenter.z.toFixed(0)}) with ${selected.length} potential participants, legitimacy=${legitimacy}`);
        EventBus.emit('city-sim:protest-started', {
            plazaCenter,
            participants: selected.length,
            legitimacy,
        });
    }

    /**
     * Tick the protest — called every physics step.
     * @param {number} dt
     * @param {Array<SimPedestrian>} pedestrians
     * @param {Array<SimVehicle>} vehicles — for police car dispatch
     */
    tick(dt, pedestrians, vehicles) {
        if (!this.active || !this.engine) return;

        // Build position array for the protest engine
        const positions = [];
        for (const ped of pedestrians) {
            if (ped.inBuilding) continue;
            positions.push({
                id: ped.id,
                x: ped.x,
                z: ped.z,
                type: ped.role === 'police' ? 'police' : 'civilian',
            });
        }

        const result = this.engine.tick(dt, positions);

        // Check for phase transitions
        if (result.phase !== this._lastPhase) {
            console.log(`[ProtestManager] Phase: ${this._lastPhase || 'NONE'} → ${result.phase} (${result.activeCount} active, ${result.arrestedCount} arrested, tension=${(result.tensionLevel * 100).toFixed(0)}%)`);
            EventBus.emit('city-sim:protest-phase', {
                phase: result.phase,
                previousPhase: this._lastPhase,
                activeCount: result.activeCount,
                arrestedCount: result.arrestedCount,
                tensionLevel: result.tensionLevel,
            });
            this._lastPhase = result.phase;
        }

        // Apply goals to NPCs — override their daily routine
        for (const ped of pedestrians) {
            if (!this._protestorIds.has(ped.id)) continue;

            const goal = this.engine.getAgentGoal(ped.id);
            if (!goal) {
                // Passive — follow normal routine
                ped.overrideGoal = null;
                continue;
            }

            // Convert protest goal to NPC override
            switch (goal.action) {
                case 'go_to':
                    ped.overrideGoal = {
                        action: 'go_to',
                        target: goal.target,
                        speed: goal.speed || 2.0,
                        source: 'protest',
                    };
                    ped.mood = 'angry';
                    ped.color = 0xff8844; // orange for marching protestor
                    break;

                case 'mill':
                    // Wander around the gathering point — pick new random target when near current
                    {
                        const pedDist = Math.sqrt((ped.x - (ped.overrideGoal?.target?.x || 0)) ** 2 +
                                                  (ped.z - (ped.overrideGoal?.target?.z || 0)) ** 2);
                        // Only update target if NPC reached previous one or has no target
                        if (!ped.overrideGoal || ped.overrideGoal.source !== 'protest_mill' || pedDist < 3) {
                            const angle = Math.random() * Math.PI * 2;
                            const r = Math.random() * (goal.radius || 20);
                            ped.overrideGoal = {
                                action: 'go_to',
                                target: {
                                    x: goal.target.x + Math.cos(angle) * r,
                                    z: goal.target.z + Math.sin(angle) * r,
                                },
                                speed: goal.speed || 0.5,
                                source: 'protest_mill',
                            };
                        }
                    }
                    ped.mood = 'angry';
                    ped.color = 0xff4444; // red for active protestor
                    break;

                case 'flee':
                    // Run away from plaza
                    const fx = ped.x - this._plazaCenter.x;
                    const fz = ped.z - this._plazaCenter.z;
                    const fd = Math.sqrt(fx * fx + fz * fz) || 1;
                    ped.overrideGoal = {
                        action: 'go_to',
                        target: {
                            x: ped.x + (fx / fd) * 100,
                            z: ped.z + (fz / fd) * 100,
                        },
                        speed: goal.speed || 3.5,
                        source: 'protest',
                    };
                    ped.mood = 'panicked';
                    ped.color = 0xfcee0a; // yellow for fleeing
                    break;

                case 'stay':
                    // Arrested — frozen in place
                    ped.overrideGoal = { action: 'stay', speed: 0, source: 'protest' };
                    ped.mood = 'panicked';
                    ped.color = 0xff2a6d; // magenta for arrested
                    ped.speed = 0;
                    ped.vx = 0;
                    ped.vz = 0;
                    break;
            }
        }

        // Dispatch police when tension rises
        if (result.activeCount >= 5 && this._policeIds.size === 0) {
            this._dispatchPolice(pedestrians, 6);
        }
        if (result.activeCount >= 15 && this._policeIds.size < 12) {
            this._dispatchPolice(pedestrians, 6);
        }

        // Mood contagion — angry NPCs make nearby calm NPCs anxious
        for (const ped of pedestrians) {
            if (ped.inBuilding || ped.mood === 'angry' || ped.mood === 'panicked') continue;
            if (this._protestorIds.has(ped.id)) continue; // protest participants already managed

            // Check if near angry NPCs
            let angryNearby = 0;
            for (const other of pedestrians) {
                if (other === ped || other.mood !== 'angry') continue;
                const dx = ped.x - other.x;
                const dz = ped.z - other.z;
                if (dx * dx + dz * dz < 400) angryNearby++; // 20m radius
            }

            if (angryNearby >= 2 && Math.random() < 0.01 * angryNearby) {
                ped.mood = 'anxious';
                ped.color = 0xaacc44; // yellow-green
            }
        }

        // If protest is over, clean up
        if (!this.engine.active) {
            this.stop(pedestrians);
        }
    }

    /**
     * Stop the protest, reset all NPC overrides.
     */
    stop(pedestrians) {
        if (pedestrians) {
            for (const ped of pedestrians) {
                if (this._protestorIds.has(ped.id) || this._policeIds.has(ped.id)) {
                    ped.resumeRoutine();
                }
            }
        }
        this.active = false;
        this._protestorIds.clear();
        this._policeIds.clear();
        console.log('[ProtestManager] Protest ended');
        EventBus.emit('city-sim:protest-ended');
    }

    /**
     * Dispatch police NPCs — convert existing patrol-role NPCs or spawn new ones near police station.
     */
    _dispatchPolice(pedestrians, count) {
        let dispatched = 0;
        const station = this.engine?.policeStation || { x: 100, z: -100 };

        // First: activate existing police-role NPCs
        for (const ped of pedestrians) {
            if (dispatched >= count) break;
            if (ped.role !== 'police' || this._policeIds.has(ped.id)) continue;

            this._policeIds.add(ped.id);
            ped.overrideGoal = {
                action: 'go_to',
                target: this._plazaCenter,
                speed: 1.8,
                source: 'police_dispatch',
            };
            ped.mood = 'calm';
            ped.color = 0x4488ff; // blue for police
            dispatched++;
        }

        // If not enough police-role NPCs, convert some random residents
        for (const ped of pedestrians) {
            if (dispatched >= count) break;
            if (this._policeIds.has(ped.id) || this._protestorIds.has(ped.id)) continue;
            if (ped.inBuilding) continue;

            // Convert to police response
            this._policeIds.add(ped.id);
            ped.overrideGoal = {
                action: 'go_to',
                target: {
                    x: this._plazaCenter.x + (Math.random() - 0.5) * 40,
                    z: this._plazaCenter.z - 30 - Math.random() * 20, // form line south of plaza
                },
                speed: 1.8,
                source: 'police_dispatch',
            };
            ped.mood = 'calm';
            ped.color = 0x4488ff; // blue for police
            dispatched++;
        }

        if (dispatched > 0) {
            console.log(`[ProtestManager] Police dispatched: ${dispatched} officers (total: ${this._policeIds.size})`);
            EventBus.emit('city-sim:police-dispatched', {
                count: dispatched,
                total: this._policeIds.size,
            });
        }
    }

    /**
     * Get debug info.
     */
    getDebugInfo() {
        if (!this.engine) return null;
        return {
            ...this.engine.getDebugInfo(),
            protestorCount: this._protestorIds.size,
            plazaCenter: this._plazaCenter,
        };
    }
}
