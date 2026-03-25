// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Weather Overlay Panel — toggle panel for the map weather widget.
// Shows current weather data and lets operators toggle the overlay on/off.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { weatherOverlay } from './weather-overlay.js';

const REFRESH_MS = 30000;

function _renderWeather() {
    const data = TritiumStore.get('weather.current');
    if (!data) {
        return '<div style="color:#555;padding:12px;text-align:center;">No weather data yet</div>';
    }

    const tempF = data.temperature_f != null ? `${Math.round(data.temperature_f)}F` : '--';
    const tempC = data.temperature_c != null ? `${Math.round(data.temperature_c)}C` : '--';
    const desc = data.weather_desc || 'Unknown';
    const wind = data.wind_speed_mph != null ? `${Math.round(data.wind_speed_mph)} mph` : '--';
    const humidity = data.humidity != null ? `${data.humidity}%` : '--';
    const windDir = data.wind_direction != null ? _degToCompass(data.wind_direction) : '';

    return `
        <div style="padding:4px 0;">
            <div style="color:#00f0ff;font-size:16px;font-weight:bold;margin-bottom:4px;">${tempF} <span style="color:#666;font-size:12px;">${tempC}</span></div>
            <div style="color:#b0b0c0;margin-bottom:4px;">${desc}</div>
            <div style="display:flex;gap:16px;color:#888;font-size:11px;">
                <span>WIND: ${windDir} ${wind}</span>
                <span>HUMIDITY: ${humidity}</span>
            </div>
        </div>
    `;
}

function _renderMeshReadings() {
    const readings = TritiumStore.get('weather.mesh_readings') || [];
    if (readings.length === 0) return '';

    const rows = readings.map(r => {
        const name = r.node_name || r.node_id || '?';
        const temp = r.temperature_f != null ? `${Math.round(r.temperature_f)}F` : '--';
        const hum = r.humidity_pct != null ? `${r.humidity_pct}%` : '--';
        return `<div style="display:flex;gap:8px;padding:2px 0;font-size:11px;">
            <span style="color:#05ffa1;min-width:80px;">${name}</span>
            <span style="color:#b0b0c0;">${temp}</span>
            <span style="color:#888;">H:${hum}</span>
        </div>`;
    }).join('');

    return `
        <div style="border-top:1px solid rgba(0,240,255,0.15);margin-top:6px;padding-top:6px;">
            <div style="color:#05ffa1;font-size:11px;margin-bottom:4px;">MESH ENVIRONMENT (${readings.length} nodes)</div>
            ${rows}
        </div>
    `;
}

function _degToCompass(deg) {
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    return dirs[Math.round(deg / 45) % 8];
}

export const WeatherOverlayPanelDef = {
    id: 'weather-overlay',
    title: 'WEATHER',
    defaultPosition: { x: 340, y: 80 },
    defaultSize: { w: 300, h: 280 },

    create(panel) {
        const el = document.createElement('div');
        el.style.padding = '8px';

        const visible = weatherOverlay._visible !== false;

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <label style="color:#b0b0c0;font-size:12px;cursor:pointer;">
                    <input type="checkbox" data-toggle="weather" ${visible ? 'checked' : ''} style="margin-right:6px;">
                    Show weather on map
                </label>
                <button class="panel-action-btn" data-action="refresh" style="font-size:0.42rem;margin-left:auto;">REFRESH</button>
            </div>
            <div data-bind="weather-data">${_renderWeather()}</div>
            <div data-bind="mesh-data">${_renderMeshReadings()}</div>
        `;

        const toggle = el.querySelector('[data-toggle="weather"]');
        if (toggle) {
            toggle.addEventListener('change', () => {
                weatherOverlay.toggle();
            });
        }

        const refreshBtn = el.querySelector('[data-action="refresh"]');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                weatherOverlay._fetchNow();
                setTimeout(() => {
                    const wd = el.querySelector('[data-bind="weather-data"]');
                    const md = el.querySelector('[data-bind="mesh-data"]');
                    if (wd) wd.innerHTML = _renderWeather();
                    if (md) md.innerHTML = _renderMeshReadings();
                }, 2000);
            });
        }

        // Periodic UI refresh
        const timer = setInterval(() => {
            const wd = el.querySelector('[data-bind="weather-data"]');
            const md = el.querySelector('[data-bind="mesh-data"]');
            if (wd) wd.innerHTML = _renderWeather();
            if (md) md.innerHTML = _renderMeshReadings();
        }, REFRESH_MS);

        panel._weatherTimer = timer;
        return el;
    },

    destroy(panel) {
        if (panel._weatherTimer) {
            clearInterval(panel._weatherTimer);
            panel._weatherTimer = null;
        }
    },
};
