// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * EventDirector — schedules and triggers city-wide events.
 *
 * Events modify NPC behavior by injecting temporary goals. The director
 * manages a queue of events with start times and handles random event
 * generation based on configurable probabilities.
 *
 * Built-in event types: protest, emergency, rush_hour, lunch_crowd,
 * evening_leisure, concert, car_accident, fire
 */

import { EventBus } from '/lib/events.js';

const BUILT_IN_EVENTS = {
    protest: {
        name: 'Protest at Central Plaza',
        duration: 300, // 5 min real time
        setup: (mgr, params) => {
            const plaza = params.plazaCenter || { x: 0, z: 0 };
            mgr.protestManager.start(mgr.pedestrians, {
                plazaCenter: plaza,
                participantCount: params.participantCount || 50,
                legitimacy: params.legitimacy ?? 0.3,
            });
        },
    },
    car_accident: {
        name: 'Car Accident',
        duration: 120,
        setup: (mgr, params) => {
            // Force-collide two random vehicles
            if (mgr.vehicles.length >= 2) {
                const v1 = mgr.vehicles[Math.floor(Math.random() * mgr.vehicles.length)];
                v1.inAccident = true;
                v1.speed = 0;
                v1.accidentTimer = 60 + Math.random() * 60;
                // Spawn emergency response
                mgr.spawnEmergency();
            }
        },
    },
    emergency_response: {
        name: 'Emergency Response',
        duration: 180,
        setup: (mgr) => {
            for (let i = 0; i < 3; i++) mgr.spawnEmergency();
        },
    },
};

export class EventDirector {
    constructor() {
        this._eventQueue = [];     // [{type, startHour, params, triggered}]
        this._activeEvents = [];   // [{type, name, startTime, endTime}]
        this._randomEventProb = 0.05; // 5% chance per sim-hour
        this._lastRandomCheck = -1;
        this._simManager = null;
    }

    /**
     * Bind to a CitySimManager.
     */
    bind(simManager) {
        this._simManager = simManager;
    }

    /**
     * Load a pre-built event sequence for a dramatic day.
     * Schedules: morning rush → lunch crowd → afternoon protest → evening calm
     */
    loadDramaticDay() {
        this.scheduleEvent('car_accident', 8.5);        // 8:30am fender bender during rush
        this.scheduleEvent('emergency_response', 10.0);  // 10am medical emergency
        this.scheduleEvent('protest', 14.0, {            // 2pm protest at city center
            plazaCenter: { x: 0, z: 0 },
            participantCount: 50,
            legitimacy: 0.25,
        });
        this.scheduleEvent('car_accident', 17.5);        // 5:30pm rush hour accident
        console.log('[EventDirector] Dramatic day loaded — 4 events scheduled');
    }

    /**
     * Schedule an event at a specific sim hour.
     */
    scheduleEvent(type, simHour, params = {}) {
        this._eventQueue.push({ type, startHour: simHour, params, triggered: false });
        this._eventQueue.sort((a, b) => a.startHour - b.startHour);
        console.log(`[EventDirector] Scheduled: ${type} at ${simHour.toFixed(1)}`);
    }

    /**
     * Trigger an event immediately.
     */
    triggerEvent(type, params = {}) {
        const eventDef = BUILT_IN_EVENTS[type];
        if (!eventDef) {
            console.warn(`[EventDirector] Unknown event type: ${type}`);
            return false;
        }
        if (!this._simManager) {
            console.warn(`[EventDirector] No sim manager bound`);
            return false;
        }

        console.log(`[EventDirector] EVENT: ${eventDef.name}`);
        eventDef.setup(this._simManager, params);

        this._activeEvents.push({
            type,
            name: eventDef.name,
            startTime: performance.now(),
            duration: eventDef.duration * 1000,
        });

        EventBus.emit('city-sim:event-triggered', { type, name: eventDef.name, params });
        return true;
    }

    /**
     * Tick — check scheduled events and random events.
     */
    tick(dt, simHour) {
        if (!this._simManager) return;

        // Check scheduled events
        for (const evt of this._eventQueue) {
            if (!evt.triggered && simHour >= evt.startHour) {
                evt.triggered = true;
                this.triggerEvent(evt.type, evt.params);
            }
        }

        // Random event check (once per sim hour)
        const currentHourInt = Math.floor(simHour);
        if (currentHourInt !== this._lastRandomCheck && simHour > 8 && simHour < 22) {
            this._lastRandomCheck = currentHourInt;
            if (Math.random() < this._randomEventProb) {
                const types = ['car_accident', 'emergency_response'];
                const type = types[Math.floor(Math.random() * types.length)];
                this.triggerEvent(type);
            }
        }

        // Clean up expired active events
        const now = performance.now();
        this._activeEvents = this._activeEvents.filter(e => now - e.startTime < e.duration);
    }

    /**
     * Get active events for UI display.
     */
    getActiveEvents() {
        return this._activeEvents.map(e => ({
            type: e.type,
            name: e.name,
            elapsed: ((performance.now() - e.startTime) / 1000).toFixed(0),
        }));
    }
}
