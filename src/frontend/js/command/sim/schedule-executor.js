// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Schedule Executor — drives NPC daily routines based on sim clock.
 *
 * The sim clock runs at accelerated speed (default: 1 real second = 1 sim minute).
 * Each NPC has a daily routine (from daily-routine.js) that the executor checks
 * each tick. When the sim time crosses a goal's startHour, the executor triggers
 * the NPC to transition to that activity.
 *
 * This is a pure logic module — no rendering dependencies.
 */

import { generateDailyRoutine } from '/lib/sim/daily-routine.js';

// ============================================================
// SIM CLOCK
// ============================================================

export class SimClock {
    /**
     * @param {number} startHour - Starting hour (0-24, e.g., 7.5 = 7:30am)
     * @param {number} timeScale - How many sim minutes per real second (default 1)
     */
    constructor(startHour = 7, timeScale = 1) {
        this.simHour = startHour;
        this.simDay = 0;
        this.timeScale = timeScale; // sim minutes per real second
        this.totalElapsed = 0;
    }

    /**
     * Advance the clock by dt real seconds.
     * @param {number} dt - Real seconds elapsed
     */
    tick(dt) {
        const simMinutes = dt * this.timeScale;
        this.simHour += simMinutes / 60;
        this.totalElapsed += dt;

        // Wrap day
        if (this.simHour >= 24) {
            this.simHour -= 24;
            this.simDay++;
        }
    }

    /** Get current hour as float (0-24) */
    getHour() { return this.simHour; }

    /** Get formatted time string "HH:MM" */
    getTimeString() {
        const h = Math.floor(this.simHour);
        const m = Math.floor((this.simHour - h) * 60);
        return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
    }

    /** Get day count */
    getDay() { return this.simDay; }

    /** Is it daytime? (6am - 10pm) */
    isDaytime() { return this.simHour >= 6 && this.simHour < 22; }

    /** Is it rush hour? (7-9am or 5-7pm) */
    isRushHour() {
        return (this.simHour >= 7 && this.simHour < 9) ||
               (this.simHour >= 17 && this.simHour < 19);
    }

    /** Set time scale */
    setTimeScale(scale) { this.timeScale = scale; }
}

// ============================================================
// NPC ROLES
// ============================================================

const NPC_ROLES = ['resident', 'worker', 'worker', 'worker', 'student', 'shopkeeper', 'jogger'];

// ============================================================
// SCHEDULE EXECUTOR
// ============================================================

export class ScheduleExecutor {
    /**
     * @param {SimClock} clock - Sim clock instance
     */
    constructor(clock) {
        this.clock = clock;
        this.schedules = new Map(); // npcId → { role, routine, currentGoalIndex, pois }
    }

    /**
     * Assign a daily routine to an NPC.
     *
     * @param {string} npcId - NPC identifier
     * @param {string} [role] - NPC role (random if omitted)
     * @param {Object} pois - Points of interest: { home, work, school, park, ... }
     * @param {function} [rng] - Random number generator
     */
    assignSchedule(npcId, role = null, pois = {}, rng = Math.random) {
        if (!role) {
            role = NPC_ROLES[Math.floor(rng() * NPC_ROLES.length)];
        }

        const routine = generateDailyRoutine(role, pois, rng);
        this.schedules.set(npcId, {
            role,
            routine,
            currentGoalIndex: -1,
            pois,
            lastTransitionHour: -1,
        });
    }

    /**
     * Check if an NPC should transition to a new activity.
     *
     * @param {string} npcId
     * @returns {{ shouldTransition: boolean, goal: Object|null, role: string }}
     */
    checkTransition(npcId) {
        const sched = this.schedules.get(npcId);
        if (!sched) return { shouldTransition: false, goal: null, role: 'resident' };

        const hour = this.clock.getHour();
        const routine = sched.routine;

        // Find the current goal based on sim time
        let targetIndex = 0;
        for (let i = 0; i < routine.length; i++) {
            if (hour >= routine[i].startHour) {
                targetIndex = i;
            }
        }

        if (targetIndex !== sched.currentGoalIndex) {
            sched.currentGoalIndex = targetIndex;
            sched.lastTransitionHour = hour;
            return {
                shouldTransition: true,
                goal: routine[targetIndex],
                role: sched.role,
            };
        }

        return { shouldTransition: false, goal: routine[sched.currentGoalIndex], role: sched.role };
    }

    /**
     * Get the current activity for an NPC.
     */
    getCurrentActivity(npcId) {
        const sched = this.schedules.get(npcId);
        if (!sched || sched.currentGoalIndex < 0) return null;
        return sched.routine[sched.currentGoalIndex];
    }

    /**
     * Get the role for an NPC.
     */
    getRole(npcId) {
        const sched = this.schedules.get(npcId);
        return sched ? sched.role : 'resident';
    }

    /**
     * Get debug info for an NPC.
     */
    getDebugInfo(npcId) {
        const sched = this.schedules.get(npcId);
        if (!sched) return 'no schedule';
        const goal = sched.routine[sched.currentGoalIndex];
        return `${sched.role}: ${goal ? `${goal.action} → ${goal.destination}` : 'idle'}`;
    }
}
