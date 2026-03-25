// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * SimPedestrian — walks on sidewalks, follows daily routines, enters buildings.
 *
 * Social Force Model for ped-ped avoidance (simplified from Helbing 1995).
 * Position controlled directly (not path-based like vehicles).
 */

import { generateDailyRoutine, getCurrentGoal } from '/lib/sim/daily-routine.js';

let _nextPedId = 0;

/** Activity states for color coding. */
export const PED_ACTIVITY = {
    IDLE: 'idle',
    COMMUTING: 'commuting',
    AT_WORK: 'at_work',
    SHOPPING: 'shopping',
    GOING_HOME: 'going_home',
    IN_BUILDING: 'in_building',
};

/** Colors by activity. */
export const PED_COLORS = {
    idle: 0x44aa66,
    commuting: 0x4488cc,
    at_work: 0x888888,
    shopping: 0xccaa44,
    going_home: 0xff8844,
    in_building: 0x444444,
};

export class SimPedestrian {
    /**
     * @param {number} x — start X (local meters)
     * @param {number} z — start Z
     * @param {Object} homeEntry — {x, z} home building entry
     * @param {Object} workEntry — {x, z} work building entry
     * @param {Object} [config] — optional identity/role config
     */
    constructor(x, z, homeEntry, workEntry, config = {}) {
        this.id = `ped_${_nextPedId++}`;
        this.x = x;
        this.z = z;
        this.vx = 0;
        this.vz = 0;
        this.speed = 0;
        this.heading = 0;
        this.alive = true;
        this.visible = true;

        // Identity — name, background (deterministic from id)
        this.name = config.name || this.id;
        this.role = config.role || _randomRole();
        this.homeBuildingId = config.homeBuildingId || null;
        this.workBuildingId = config.workBuildingId || null;

        // Personality — drives behavior during events
        this.personality = {
            hardship: config.hardship ?? Math.random(),       // 0-1: economic hardship (drives protest activation)
            riskAversion: config.riskAversion ?? Math.random(), // 0-1: how risk-averse (affects riot participation)
            sociability: config.sociability ?? Math.random(),   // 0-1: likelihood of joining gatherings
        };

        // Mood — changes over time, affects behavior and color
        this.mood = 'calm'; // calm | anxious | angry | panicked

        // Transport preference based on role
        this.transportPref = config.transport || (this.role === 'jogger' ? 'walk' : (Math.random() < 0.4 ? 'car' : 'walk'));

        // Walking speed varies by role
        const speedByRole = { jogger: 2.5, police: 1.5, student: 1.2, resident: 1.0, worker: 1.1, shopkeeper: 0.9, dogwalker: 0.8 };
        this.desiredSpeed = (speedByRole[this.role] || 1.0) + Math.random() * 0.3;

        // Navigation
        this.goalX = x;
        this.goalZ = z;
        this.goalReached = true;
        this.activity = PED_ACTIVITY.IDLE;

        // Override target — set by protest engine, gathering system, or events
        // When set, overrides daily routine goal
        this.overrideGoal = null; // { action, target: {x,z}, speed, source }

        // Buildings
        this.homeEntry = homeEntry;
        this.workEntry = workEntry;
        this.inBuilding = false;
        this.buildingTimer = 0;
        this.currentBuildingId = null;

        // Daily routine
        this._schedule = this._generateSchedule();
        this._scheduleIdx = 0;
        this._simHour = 6;

        // Collision / stun state
        this.stunTimer = 0;

        // Rendering
        this.instanceIdx = -1;
        this.color = PED_COLORS.idle;
        this.bobPhase = Math.random() * Math.PI * 2;
    }

    /**
     * Generate daily schedule using role-based routine from tritium-lib.
     * @returns {Array<{hour, activity, goal}>}
     */
    _generateSchedule() {
        // POI map for the routine generator
        const pois = {
            home: this.homeEntry,
            work: this.workEntry,
            school: this.workEntry, // students treat work as school
            park: this._randomNearby(this.homeEntry, 80),
            commercial: this._randomNearby(this.workEntry, 40),
            police_station: this.homeEntry, // police station = their "home" for now
            patrol_route: this._randomNearby(this.homeEntry, 150),
            patrol_zone: this._randomNearby(this.homeEntry, 100),
        };

        // Generate the full daily routine from tritium-lib
        const routine = generateDailyRoutine(this.role, pois, Math.random);

        // Convert routine goals to our internal schedule format
        const schedule = [];
        for (const goal of routine) {
            const destMap = {
                home: this.homeEntry,
                work: this.workEntry,
                school: this.workEntry,
                park: pois.park,
                commercial: pois.commercial,
                police_station: pois.police_station,
                patrol_route: pois.patrol_route,
                patrol_zone: pois.patrol_zone,
            };

            const activityMap = {
                go_to: PED_ACTIVITY.COMMUTING,
                stay_at: goal.destination === 'home' ? PED_ACTIVITY.IN_BUILDING :
                         goal.destination === 'work' || goal.destination === 'school' ? PED_ACTIVITY.AT_WORK :
                         PED_ACTIVITY.SHOPPING,
                wander: PED_ACTIVITY.SHOPPING,
                idle: PED_ACTIVITY.IDLE,
            };

            const dest = destMap[goal.destination] || this.homeEntry;
            const goalPos = (goal.action === 'stay_at' || goal.action === 'idle') ? null : dest;

            schedule.push({
                hour: goal.startHour,
                activity: activityMap[goal.action] || PED_ACTIVITY.IDLE,
                goal: goalPos,
                transport: goal.transport || 'walk',
                mood: goal.mood || 'calm',
            });
        }

        return schedule;
    }

    /**
     * Resume daily routine after an override (protest, event) ends.
     * Finds the correct schedule step for the current sim hour.
     */
    resumeRoutine() {
        this.overrideGoal = null;
        this.mood = 'calm';
        this.color = PED_COLORS.idle;

        // Find the current schedule step for the sim hour
        for (let i = this._schedule.length - 1; i >= 0; i--) {
            if (this._simHour >= this._schedule[i].hour) {
                this._scheduleIdx = i;
                const step = this._schedule[i];
                this.activity = step.activity;
                this.color = PED_COLORS[this.activity] || PED_COLORS.idle;
                if (step.goal) {
                    this.goalX = step.goal.x;
                    this.goalZ = step.goal.z;
                    this.goalReached = false;
                }
                break;
            }
        }

        // Reset speed to role default
        const speedByRole = { jogger: 2.5, police: 1.5, student: 1.2, resident: 1.0, worker: 1.1, shopkeeper: 0.9, dogwalker: 0.8 };
        this.desiredSpeed = (speedByRole[this.role] || 1.0) + Math.random() * 0.3;
    }

    _randomNearby(pt, radius) {
        return {
            x: pt.x + (Math.random() - 0.5) * radius,
            z: pt.z + (Math.random() - 0.5) * radius,
        };
    }

    /**
     * Update pedestrian for one timestep.
     * @param {number} dt — delta time
     * @param {number} simHour — current simulation hour (0-24)
     * @param {Array<SimPedestrian>} nearbyPeds — pedestrians within range
     * @param {Array} nearbyVehicles — vehicles within range for avoidance
     */
    tick(dt, simHour, nearbyPeds, nearbyVehicles) {
        if (!this.alive) return;

        // Stunned by vehicle collision — lying on ground
        if (this.stunTimer > 0) {
            this.stunTimer -= dt;
            this.speed = 0;
            this.vx = 0;
            this.vz = 0;
            this.color = 0xff2a6d; // Magenta while stunned
            if (this.stunTimer <= 0) {
                this.stunTimer = 0;
                this.color = PED_COLORS[this.activity] || PED_COLORS.idle;
            }
            return;
        }

        this._simHour = simHour;

        // Check if override has expired (micro-gatherings have time limits)
        if (this.overrideGoal?._expiresAt && simHour >= this.overrideGoal._expiresAt) {
            this.resumeRoutine();
        }

        // Override goal from protest/event system takes priority over schedule
        if (this.overrideGoal) {
            if (this.overrideGoal.action === 'stay') {
                // Arrested or frozen — don't move
                return;
            }
            if (this.overrideGoal.action === 'go_to' && this.overrideGoal.target) {
                // Override walking destination — force NPC to walk to target
                this.goalX = this.overrideGoal.target.x;
                this.goalZ = this.overrideGoal.target.z;
                this.goalReached = false;
                this.desiredSpeed = this.overrideGoal.speed || 2.0;
                this.activity = PED_ACTIVITY.COMMUTING; // prevent re-entering buildings
                // Exit building if inside
                if (this.inBuilding) {
                    this.inBuilding = false;
                    this.visible = true;
                    this.buildingTimer = 0;
                }
            }
        } else {
            // Normal daily routine
            this._checkSchedule(simHour);
        }

        // In building — just count timer
        if (this.inBuilding) {
            this.buildingTimer -= dt;
            if (this.buildingTimer <= 0) {
                this.inBuilding = false;
                this.visible = true;
                this.currentBuildingId = null;
            }
            return;
        }

        // Goal reached — enter building or idle
        if (this.goalReached && (this.activity === PED_ACTIVITY.AT_WORK || this.activity === PED_ACTIVITY.IN_BUILDING)) {
            this.inBuilding = true;
            this.visible = false;
            this.buildingTimer = 60 + Math.random() * 300; // 1-6 minutes
            // Track which building we entered
            this.currentBuildingId = (this.activity === PED_ACTIVITY.AT_WORK)
                ? this.workBuildingId
                : this.homeBuildingId;
            return;
        }

        // Movement toward goal
        if (!this.goalReached) {
            const dx = this.goalX - this.x;
            const dz = this.goalZ - this.z;
            const dist = Math.sqrt(dx * dx + dz * dz);

            if (dist < 2.0) {
                this.goalReached = true;
                this.vx = 0;
                this.vz = 0;
                this.speed = 0;
            } else {
                // Desired velocity toward goal — clamp desiredSpeed to prevent zero division
                const speed = Math.max(0.1, this.desiredSpeed);
                let dvx = (dx / dist) * speed;
                let dvz = (dz / dist) * speed;

                // Social force: repulsion from nearby pedestrians + physical bumping
                for (const other of nearbyPeds) {
                    if (other === this || other.inBuilding || other.stunTimer > 0) continue;
                    const ox = this.x - other.x;
                    const oz = this.z - other.z;
                    const od = Math.sqrt(ox * ox + oz * oz);

                    if (od < 0.4 && od > 0.01) {
                        // Physical contact — pedestrians bump into each other
                        // Both get pushed apart, with some stumble
                        const pushStrength = (0.4 - od) * 2.0;
                        dvx += (ox / od) * pushStrength;
                        dvz += (oz / od) * pushStrength;

                        // Small chance of knockdown if both moving fast
                        const relSpeed = this.speed + other.speed;
                        if (relSpeed > 2.0 && Math.random() < 0.02) {
                            // One of them stumbles — random which one
                            const victim = Math.random() < 0.5 ? this : other;
                            victim.stunTimer = 0.5 + Math.random() * 1.5;
                            victim.speed = 0;
                            victim.vx = 0;
                            victim.vz = 0;
                        }
                    } else if (od < 1.5 && od > 0.01) {
                        // Soft avoidance zone
                        const repulsion = (1.5 - od) * 0.3;
                        dvx += (ox / od) * repulsion;
                        dvz += (oz / od) * repulsion;
                    }
                }

                // Vehicle avoidance: dodge perpendicular if a vehicle is heading toward us
                if (nearbyVehicles) {
                    for (const car of nearbyVehicles) {
                        const cx = this.x - car.x;
                        const cz = this.z - car.z;
                        const cd = Math.sqrt(cx * cx + cz * cz);
                        if (cd < 5 && cd > 0.01 && car.speed > 0.5) {
                            // Check if vehicle is heading toward pedestrian
                            const carDx = Math.sin(car.heading);
                            const carDz = Math.cos(car.heading);
                            const dot = -(cx * carDx + cz * carDz) / cd;
                            if (dot > 0.3) {
                                // Vehicle approaching — dodge perpendicular
                                const urgency = (5 - cd) * 0.8;
                                const perpX = -carDz;
                                const perpZ = carDx;
                                // Choose side based on which perpendicular is closer to current offset
                                const side = (cx * perpX + cz * perpZ) > 0 ? 1 : -1;
                                dvx += perpX * side * urgency;
                                dvz += perpZ * side * urgency;
                            }
                        }
                    }
                }

                // Velocity relaxation (tau = 0.5s)
                const tau = 0.5;
                this.vx += (dvx - this.vx) / tau * dt;
                this.vz += (dvz - this.vz) / tau * dt;

                // Clamp speed
                const s = Math.sqrt(this.vx * this.vx + this.vz * this.vz);
                if (s > this.desiredSpeed * 1.5) {
                    this.vx = (this.vx / s) * this.desiredSpeed * 1.5;
                    this.vz = (this.vz / s) * this.desiredSpeed * 1.5;
                }

                // Update position
                this.x += this.vx * dt;
                this.z += this.vz * dt;
                this.speed = Math.sqrt(this.vx * this.vx + this.vz * this.vz);
                this.heading = Math.atan2(this.vx, this.vz);

                // Walking bob
                this.bobPhase += dt * 8;
            }
        }
    }

    /**
     * Check and advance schedule.
     */
    _checkSchedule(simHour) {
        if (this._scheduleIdx >= this._schedule.length) return;

        const next = this._schedule[this._scheduleIdx];
        if (simHour >= next.hour) {
            this.activity = next.activity;
            this.color = PED_COLORS[this.activity] || PED_COLORS.idle;

            if (next.goal) {
                this.goalX = next.goal.x;
                this.goalZ = next.goal.z;
                this.goalReached = false;
            }

            this._scheduleIdx++;
        }
    }
}

// NPC role distribution (weighted)
const _ROLE_WEIGHTS = [
    ['resident', 4], ['worker', 3], ['student', 2],
    ['shopkeeper', 1], ['jogger', 1], ['dogwalker', 1], ['police', 0.5],
];
const _ROLE_TOTAL = _ROLE_WEIGHTS.reduce((s, [, w]) => s + w, 0);

function _randomRole() {
    let r = Math.random() * _ROLE_TOTAL;
    for (const [role, weight] of _ROLE_WEIGHTS) {
        r -= weight;
        if (r <= 0) return role;
    }
    return 'resident';
}
