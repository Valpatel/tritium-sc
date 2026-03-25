// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * AmbientSoundBridge — emits EventBus events for ambient city sounds
 * based on simulation state (vehicles, pedestrians, weather).
 *
 * Ticked from CitySimManager. Every 5 seconds, emits 'audio:ambient'
 * events that downstream audio systems can subscribe to.
 */

import { EventBus } from '/lib/events.js';

export class AmbientSoundBridge {
    constructor() {
        this._timer = 0;
        this._interval = 5; // seconds between emissions
    }

    /**
     * @param {number} dt — delta time in seconds
     * @param {Array} vehicles — active SimVehicle array
     * @param {Array} pedestrians — active SimPedestrian array
     * @param {object} weather — CityWeather instance
     */
    tick(dt, vehicles, pedestrians, weather) {
        this._timer += dt;
        if (this._timer < this._interval) return;
        this._timer = 0;

        const vehicleCount = vehicles?.length || 0;
        const pedestrianCount = pedestrians?.length || 0;

        // Engine hum scales with vehicle density
        if (vehicleCount > 0) {
            EventBus.emit('audio:ambient', {
                type: 'engine_hum',
                intensity: Math.min(1.0, vehicleCount / 100),
            });
        }

        // Horns when vehicles are stopped (congestion)
        if (vehicleCount > 0) {
            const stoppedCount = vehicles.filter(v => v.speed < 0.5).length;
            const congestionLevel = stoppedCount / vehicleCount;
            if (congestionLevel > 0.1) {
                EventBus.emit('audio:ambient', {
                    type: 'horn',
                    probability: congestionLevel,
                });
            }
        }

        // Footsteps from pedestrians
        if (pedestrianCount > 0) {
            EventBus.emit('audio:ambient', {
                type: 'footsteps',
                intensity: Math.min(1.0, pedestrianCount / 50),
            });
        }

        // Rain ambience
        if (weather?.weather === 'rain') {
            EventBus.emit('audio:ambient', {
                type: 'rain',
                intensity: 1.0,
            });
        }
    }
}
