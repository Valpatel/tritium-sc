// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Scenario Loader — built-in city simulation scenarios and load/export utilities.
 *
 * Scenarios define initial conditions for the city sim: vehicle/pedestrian counts,
 * time of day, weather, time scale, and optional sensor bridge toggle.
 */

export const BUILT_IN_SCENARIOS = [
    {
        id: 'rush_hour',
        name: 'Rush Hour',
        description: 'Morning commute, heavy traffic',
        vehicles: 200,
        pedestrians: 80,
        startTime: 8.0,
        timeScale: 60,
        weather: 'clear',
        emergencyVehicles: 0,
        sensorBridgeEnabled: false,
    },
    {
        id: 'night_patrol',
        name: 'Night Patrol',
        description: 'Late night, minimal traffic, surveillance mode',
        vehicles: 20,
        pedestrians: 5,
        startTime: 23.0,
        timeScale: 60,
        weather: 'clear',
        emergencyVehicles: 0,
        sensorBridgeEnabled: true,
    },
    {
        id: 'lunch_rush',
        name: 'Lunch Rush',
        description: 'Midday pedestrian activity near restaurants',
        vehicles: 100,
        pedestrians: 60,
        startTime: 12.0,
        timeScale: 60,
        weather: 'clear',
        emergencyVehicles: 0,
        sensorBridgeEnabled: false,
    },
    {
        id: 'emergency',
        name: 'Emergency Response',
        description: 'Active incident with emergency vehicles',
        vehicles: 50,
        pedestrians: 30,
        startTime: 14.0,
        timeScale: 30,
        weather: 'clear',
        emergencyVehicles: 3,
        sensorBridgeEnabled: true,
    },
    {
        id: 'rainy_commute',
        name: 'Rainy Commute',
        description: 'Evening rush in rain, reduced visibility',
        vehicles: 150,
        pedestrians: 40,
        startTime: 17.5,
        timeScale: 60,
        weather: 'rain',
        emergencyVehicles: 0,
        sensorBridgeEnabled: false,
    },
    {
        id: 'weekend_morning',
        name: 'Weekend Morning',
        description: 'Light traffic, joggers and dog walkers',
        vehicles: 30,
        pedestrians: 50,
        startTime: 9.0,
        timeScale: 120,
        weather: 'clear',
        emergencyVehicles: 0,
        sensorBridgeEnabled: false,
    },
    {
        id: 'dramatic_day',
        name: 'Dramatic Day',
        description: 'Full day: rush hour → accident → protest → riot → calm. Events auto-trigger.',
        vehicles: 200,
        pedestrians: 100,
        startTime: 7.0,
        timeScale: 60,
        weather: 'clear',
        emergencyVehicles: 0,
        sensorBridgeEnabled: true,
        dramaticDay: true,  // triggers event director's dramatic day sequence
    },
];

/**
 * Load a scenario into a CitySimManager instance.
 * Clears existing entities and applies scenario configuration.
 *
 * @param {CitySimManager} citySim — the manager to configure
 * @param {object} scenario — scenario object (from BUILT_IN_SCENARIOS or custom)
 */
export function loadScenario(citySim, scenario) {
    if (!citySim || !citySim.loaded) {
        console.warn('[ScenarioLoader] Cannot load scenario — city sim not loaded');
        return false;
    }

    // Clear existing entities
    citySim.clearVehicles();

    // Apply time and weather settings
    if (scenario.startTime !== undefined) {
        citySim.simHour = scenario.startTime;
        if (citySim.weather) {
            citySim.weather.hour = scenario.startTime;
        }
    }
    if (scenario.timeScale !== undefined) {
        citySim.timeScale = scenario.timeScale;
    }
    if (scenario.weather && citySim.weather) {
        citySim.weather.weather = scenario.weather;
    }

    // Apply entity limits
    if (scenario.vehicles !== undefined) {
        citySim.maxVehicles = Math.max(scenario.vehicles, citySim.maxVehicles);
    }
    if (scenario.pedestrians !== undefined) {
        citySim.maxPedestrians = Math.max(scenario.pedestrians, citySim.maxPedestrians);
    }

    // Sensor bridge
    if (scenario.sensorBridgeEnabled !== undefined && citySim.sensorBridge) {
        citySim.sensorBridge.enabled = scenario.sensorBridgeEnabled;
    }

    // Spawn entities
    if (scenario.vehicles > 0) {
        citySim.spawnVehicles(scenario.vehicles);
    }
    if (scenario.pedestrians > 0) {
        citySim.spawnPedestrians(scenario.pedestrians);
    }

    // Spawn emergency vehicles
    if (scenario.emergencyVehicles > 0) {
        for (let i = 0; i < scenario.emergencyVehicles; i++) {
            citySim.spawnEmergency();
        }
    }

    // Load dramatic day event sequence if flagged
    if (scenario.dramaticDay && citySim.eventDirector) {
        citySim.eventDirector.loadDramaticDay();
    }

    console.log(`[ScenarioLoader] Loaded scenario: ${scenario.name || scenario.id}`);
    return true;
}

/**
 * Export the current city sim state as a scenario JSON object.
 *
 * @param {CitySimManager} citySim — the manager to capture
 * @returns {object} scenario JSON
 */
export function exportScenario(citySim) {
    if (!citySim) return null;

    return {
        id: 'custom_' + Date.now(),
        name: 'Custom Scenario',
        description: 'Exported from current simulation state',
        vehicles: citySim.vehicles?.length || 0,
        pedestrians: citySim.pedestrians?.length || 0,
        startTime: citySim.simHour || 7,
        timeScale: citySim.timeScale || 60,
        weather: citySim.weather?.weather || 'clear',
        emergencyVehicles: citySim.vehicles?.filter(v => v.isEmergency).length || 0,
        sensorBridgeEnabled: citySim.sensorBridge?.enabled || false,
    };
}

/**
 * Find a built-in scenario by ID.
 *
 * @param {string} id — scenario ID
 * @returns {object|null} scenario or null
 */
export function getScenarioById(id) {
    return BUILT_IN_SCENARIOS.find(s => s.id === id) || null;
}
