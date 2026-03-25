// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Weather overlay widget — shows current weather on the tactical map.
// Fetches from /api/weather/current using the map center coordinates.
// Auto-refreshes every 10 minutes, updates on significant map pan.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';

// Weather icon CSS classes (text-based, no emoji)
const WEATHER_ICONS = {
    sun: '//',
    sun_cloud: '/~',
    cloud_sun: '~/',
    cloud: '~~',
    fog: '...',
    drizzle: ',.',
    rain: ',,',
    rain_heavy: ',,,',
    freezing: '**,',
    snow: '**',
    snow_heavy: '***',
    thunder: '/!\\',
    unknown: '??',
};

export class WeatherOverlay {
    constructor() {
        this._container = null;
        this._data = null;
        this._lastFetchLat = null;
        this._lastFetchLng = null;
        this._fetchTimer = null;
        this._meshTimer = null;
        this._visible = true;
        this._refreshInterval = 600000; // 10 min
        this._meshRefreshInterval = 60000; // 1 min for mesh env data
        this._panThreshold = 0.05; // degrees of lat/lng change to trigger re-fetch
        this._meshReadings = []; // environment readings from mesh nodes
        this._meshBadges = []; // DOM elements for mesh node badges on map
        this._mapContainer = null;
    }

    /**
     * Create and mount the weather widget on the map.
     * @param {HTMLElement} mapContainer - the map parent element
     */
    mount(mapContainer) {
        if (this._container) return;

        this._container = document.createElement('div');
        this._container.id = 'weather-overlay';
        this._container.className = 'weather-overlay';
        this._container.style.cssText = [
            'position: absolute',
            'top: 8px',
            'right: 8px',
            'z-index: 1000',
            'background: rgba(10, 10, 15, 0.85)',
            'border: 1px solid rgba(0, 240, 255, 0.3)',
            'border-radius: 4px',
            'padding: 6px 10px',
            'font-family: monospace',
            'font-size: 11px',
            'color: #b0b0c0',
            'pointer-events: auto',
            'cursor: pointer',
            'min-width: 120px',
            'backdrop-filter: blur(4px)',
            'transition: opacity 0.3s ease',
            'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5)',
        ].join(';');

        this._container.title = 'Current weather at map center (click to refresh)';
        this._container.innerHTML = '<span style="color:#555">WEATHER // loading...</span>';

        // Click to force refresh
        this._container.addEventListener('click', () => this._fetchNow());

        mapContainer.appendChild(this._container);
        this._mapContainer = mapContainer;

        // Listen for map move events to update location
        EventBus.on('map:moveend', (data) => this._onMapMove(data));
        EventBus.on('map:ready', () => this._initialFetch());

        // Start periodic refresh
        this._fetchTimer = setInterval(() => this._fetchNow(), this._refreshInterval);

        // Mesh environment data — refresh every minute
        this._meshTimer = setInterval(() => this._fetchMeshEnvironment(), this._meshRefreshInterval);

        // Initial fetch after short delay (let map initialize)
        setTimeout(() => this._initialFetch(), 2000);
        setTimeout(() => this._fetchMeshEnvironment(), 3000);
    }

    /**
     * Remove the weather widget from the DOM.
     */
    unmount() {
        if (this._container) {
            this._container.remove();
            this._container = null;
        }
        if (this._fetchTimer) {
            clearInterval(this._fetchTimer);
            this._fetchTimer = null;
        }
        if (this._meshTimer) {
            clearInterval(this._meshTimer);
            this._meshTimer = null;
        }
        this._clearMeshBadges();
        this._mapContainer = null;
    }

    /**
     * Toggle visibility of the weather widget.
     */
    toggle() {
        this._visible = !this._visible;
        if (this._container) {
            this._container.style.display = this._visible ? 'block' : 'none';
        }
    }

    // -----------------------------------------------------------------------
    // Internal
    // -----------------------------------------------------------------------

    _initialFetch() {
        // Try to get map center from store
        const center = TritiumStore.get('map.center');
        if (center && center.lat && center.lng) {
            this._fetchWeather(center.lat, center.lng);
        } else {
            // Default to a reasonable location (will update when map provides center)
            this._fetchWeather(40.7128, -74.0060);
        }
    }

    _onMapMove(data) {
        if (!data) return;
        const lat = data.lat || data.latitude;
        const lng = data.lng || data.longitude;
        if (lat == null || lng == null) return;

        // Only re-fetch if we moved significantly
        if (this._lastFetchLat != null && this._lastFetchLng != null) {
            const dLat = Math.abs(lat - this._lastFetchLat);
            const dLng = Math.abs(lng - this._lastFetchLng);
            if (dLat < this._panThreshold && dLng < this._panThreshold) {
                return;
            }
        }
        this._fetchWeather(lat, lng);
    }

    _fetchNow() {
        if (this._lastFetchLat != null && this._lastFetchLng != null) {
            this._fetchWeather(this._lastFetchLat, this._lastFetchLng);
        } else {
            this._initialFetch();
        }
    }

    async _fetchWeather(lat, lng) {
        this._lastFetchLat = lat;
        this._lastFetchLng = lng;

        try {
            const url = `/api/weather/current?lat=${lat.toFixed(4)}&lng=${lng.toFixed(4)}`;
            const resp = await fetch(url);
            if (!resp.ok) {
                this._renderError('API error');
                return;
            }
            const data = await resp.json();
            this._data = data;
            this._render(data);

            // Store weather data for other components
            TritiumStore.set('weather.current', data);
        } catch (err) {
            console.warn('[Weather] Fetch failed:', err);
            this._renderError('offline');
        }
    }

    _render(data) {
        if (!this._container) return;

        const icon = WEATHER_ICONS[data.weather_icon] || WEATHER_ICONS.unknown;
        const tempF = data.temperature_f != null ? `${Math.round(data.temperature_f)}F` : '--';
        const tempC = data.temperature_c != null ? `${Math.round(data.temperature_c)}C` : '--';
        const desc = data.weather_desc || 'Unknown';
        const wind = data.wind_speed_mph != null ? `${Math.round(data.wind_speed_mph)}mph` : '';
        const humidity = data.humidity != null ? `${data.humidity}%` : '';
        const windDir = data.wind_direction != null ? this._degToCompass(data.wind_direction) : '';

        // Build compact display
        const lines = [];
        lines.push(`<span style="color:#00f0ff;font-weight:bold">${icon}</span> ${tempF} <span style="color:#666">${tempC}</span>`);
        lines.push(`<span style="color:#888">${desc}</span>`);

        const details = [];
        if (wind) details.push(`${windDir} ${wind}`);
        if (humidity) details.push(`H:${humidity}`);
        if (details.length > 0) {
            lines.push(`<span style="color:#555">${details.join(' | ')}</span>`);
        }

        this._container.innerHTML = lines.join('<br>');
    }

    _renderError(msg) {
        if (!this._container) return;
        this._container.innerHTML = `<span style="color:#555">WEATHER // ${msg}</span>`;
    }

    async _fetchMeshEnvironment() {
        try {
            const resp = await fetch('/api/mesh/environment');
            if (!resp.ok) return;
            const data = await resp.json();
            this._meshReadings = data.readings || [];

            // Update the weather widget to show mesh sensor count
            this._updateMeshIndicator();

            // Store for other components
            TritiumStore.set('weather.mesh_readings', this._meshReadings);
        } catch (err) {
            // Silently ignore — mesh data is supplementary
        }
    }

    _updateMeshIndicator() {
        if (!this._container || this._meshReadings.length === 0) return;

        // Add or update the mesh sensor line in the weather widget
        let meshLine = this._container.querySelector('[data-mesh-env]');
        if (!meshLine) {
            meshLine = document.createElement('div');
            meshLine.setAttribute('data-mesh-env', '1');
            meshLine.style.cssText = 'margin-top:2px;border-top:1px solid rgba(0,240,255,0.15);padding-top:2px';
            this._container.appendChild(meshLine);
        }

        const count = this._meshReadings.length;
        const temps = this._meshReadings
            .filter(r => r.temperature_f != null)
            .map(r => r.temperature_f);
        const avgTemp = temps.length > 0
            ? Math.round(temps.reduce((a, b) => a + b, 0) / temps.length)
            : null;

        const humids = this._meshReadings
            .filter(r => r.humidity_pct != null)
            .map(r => r.humidity_pct);
        const avgHumid = humids.length > 0
            ? Math.round(humids.reduce((a, b) => a + b, 0) / humids.length)
            : null;

        const parts = [`<span style="color:#05ffa1">MESH</span> ${count} node${count !== 1 ? 's' : ''}`];
        if (avgTemp != null) parts.push(`${avgTemp}F`);
        if (avgHumid != null) parts.push(`H:${avgHumid}%`);

        meshLine.innerHTML = `<span style="font-size:10px;color:#888">${parts.join(' | ')}</span>`;
    }

    _clearMeshBadges() {
        for (const badge of this._meshBadges) {
            badge.remove();
        }
        this._meshBadges = [];
    }

    _degToCompass(deg) {
        const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const idx = Math.round(deg / 45) % 8;
        return dirs[idx];
    }
}

// Singleton instance
export const weatherOverlay = new WeatherOverlay();
