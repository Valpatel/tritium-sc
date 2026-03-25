// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Setup Wizard Panel — first-launch configuration wizard
// Walks the user through: map center, demo mode, MQTT broker, default layout.
// Stores config in localStorage via ConfigStore.

import { EventBus } from '../events.js';
import { _esc } from '../panel-utils.js';

const CONFIG_KEY = 'tritium.config';
const WIZARD_COMPLETE_KEY = 'tritium.wizard.complete';

// ---------------------------------------------------------------------------
// ConfigStore — persists user configuration to localStorage
// ---------------------------------------------------------------------------

export const ConfigStore = {
    _data: null,

    _load() {
        if (this._data) return this._data;
        try {
            const raw = localStorage.getItem(CONFIG_KEY);
            this._data = raw ? JSON.parse(raw) : {};
        } catch (_) {
            this._data = {};
        }
        return this._data;
    },

    get(key, defaultValue) {
        const data = this._load();
        return data[key] !== undefined ? data[key] : defaultValue;
    },

    set(key, value) {
        const data = this._load();
        data[key] = value;
        this._data = data;
        try {
            localStorage.setItem(CONFIG_KEY, JSON.stringify(data));
        } catch (_) { /* storage full */ }
        EventBus.emit('config:changed', { key, value });
    },

    getAll() {
        return { ...this._load() };
    },

    isWizardComplete() {
        return localStorage.getItem(WIZARD_COMPLETE_KEY) === 'true';
    },

    markWizardComplete() {
        localStorage.setItem(WIZARD_COMPLETE_KEY, 'true');
    },
};

// Make ConfigStore available globally
if (typeof window !== 'undefined') {
    window.ConfigStore = ConfigStore;
}

// ---------------------------------------------------------------------------
// Wizard Steps
// ---------------------------------------------------------------------------

const STEPS = [
    {
        id: 'welcome',
        title: 'WELCOME TO TRITIUM',
        render: () => `
            <div class="wiz-hero">
                <div class="wiz-logo">TRITIUM</div>
                <div class="wiz-tagline">Unified Operating Picture</div>
            </div>
            <p class="wiz-text">
                This wizard will help you configure your Command Center.
                You can change these settings later in the System panel.
            </p>
        `,
    },
    {
        id: 'map-center',
        title: 'MAP CENTER',
        render: () => {
            const lat = ConfigStore.get('map.centerLat', 33.749);
            const lng = ConfigStore.get('map.centerLng', -84.388);
            return `
                <p class="wiz-text">Set the default map center for your area of operations. Move the map and click "Use Current" or pick a city.</p>
                <div class="wiz-field">
                    <label class="wiz-label">Latitude</label>
                    <input type="number" step="0.0001" class="wiz-input" data-key="map.centerLat" value="${lat}" />
                </div>
                <div class="wiz-field">
                    <label class="wiz-label">Longitude</label>
                    <input type="number" step="0.0001" class="wiz-input" data-key="map.centerLng" value="${lng}" />
                </div>
                <div class="wiz-presets">
                    <button class="wiz-preset-btn wiz-use-current" data-lat="" data-lng="">USE CURRENT</button>
                    <button class="wiz-preset-btn" data-lat="33.749" data-lng="-84.388">Atlanta</button>
                    <button class="wiz-preset-btn" data-lat="40.7128" data-lng="-74.006">New York</button>
                    <button class="wiz-preset-btn" data-lat="37.7749" data-lng="-122.4194">San Francisco</button>
                    <button class="wiz-preset-btn" data-lat="51.5074" data-lng="-0.1278">London</button>
                    <button class="wiz-preset-btn" data-lat="34.0522" data-lng="-118.2437">Los Angeles</button>
                    <button class="wiz-preset-btn" data-lat="41.8781" data-lng="-87.6298">Chicago</button>
                    <button class="wiz-preset-btn" data-lat="48.8566" data-lng="2.3522">Paris</button>
                    <button class="wiz-preset-btn" data-lat="35.6762" data-lng="139.6503">Tokyo</button>
                </div>
                <p class="wiz-hint" id="wiz-live-coords" style="margin-top:8px;color:#00f0ff88"></p>
            `;
        },
        save: (bodyEl) => {
            bodyEl.querySelectorAll('.wiz-input').forEach(inp => {
                const key = inp.dataset.key;
                if (key) ConfigStore.set(key, parseFloat(inp.value) || 0);
            });
        },
    },
    {
        id: 'demo-mode',
        title: 'DEMO MODE',
        render: () => {
            const enabled = ConfigStore.get('demo.autoStart', false);
            return `
                <p class="wiz-text">
                    Demo mode generates synthetic BLE, WiFi, camera, and mesh data
                    so you can explore Tritium without hardware.
                </p>
                <div class="wiz-field">
                    <label class="wiz-toggle-label">
                        <input type="checkbox" class="wiz-checkbox" data-key="demo.autoStart" ${enabled ? 'checked' : ''} />
                        <span>Auto-start demo mode on launch</span>
                    </label>
                </div>
            `;
        },
        save: (bodyEl) => {
            const cb = bodyEl.querySelector('[data-key="demo.autoStart"]');
            if (cb) ConfigStore.set('demo.autoStart', cb.checked);
        },
    },
    {
        id: 'mqtt',
        title: 'MQTT BROKER',
        render: () => {
            const host = ConfigStore.get('mqtt.host', 'localhost');
            const port = ConfigStore.get('mqtt.port', 1883);
            const enabled = ConfigStore.get('mqtt.enabled', false);
            return `
                <p class="wiz-text">
                    MQTT connects edge devices (ESP32 sensors, mesh radios) to the
                    Command Center. Skip if you don't have hardware yet.
                </p>
                <div class="wiz-field">
                    <label class="wiz-toggle-label">
                        <input type="checkbox" class="wiz-checkbox" data-key="mqtt.enabled" ${enabled ? 'checked' : ''} />
                        <span>Enable MQTT connection</span>
                    </label>
                </div>
                <div class="wiz-field">
                    <label class="wiz-label">Broker Host</label>
                    <input type="text" class="wiz-input" data-key="mqtt.host" value="${_esc(host)}" />
                </div>
                <div class="wiz-field">
                    <label class="wiz-label">Broker Port</label>
                    <input type="number" class="wiz-input" data-key="mqtt.port" value="${port}" />
                </div>
            `;
        },
        save: (bodyEl) => {
            const cb = bodyEl.querySelector('[data-key="mqtt.enabled"]');
            if (cb) ConfigStore.set('mqtt.enabled', cb.checked);
            bodyEl.querySelectorAll('.wiz-input').forEach(inp => {
                const key = inp.dataset.key;
                if (key && key.startsWith('mqtt.')) {
                    const val = inp.type === 'number' ? parseInt(inp.value, 10) : inp.value;
                    ConfigStore.set(key, val);
                }
            });
        },
    },
    {
        id: 'layout',
        title: 'DEFAULT LAYOUT',
        render: () => {
            const layout = ConfigStore.get('defaultLayout', 'commander');
            return `
                <p class="wiz-text">Choose your default panel layout.</p>
                <div class="wiz-layout-options">
                    <label class="wiz-radio-card ${layout === 'commander' ? 'selected' : ''}">
                        <input type="radio" name="wiz-layout" value="commander" ${layout === 'commander' ? 'checked' : ''} />
                        <div class="wiz-radio-title">COMMANDER</div>
                        <div class="wiz-radio-desc">Commander + Units + Alerts + Minimap. Full tactical awareness.</div>
                    </label>
                    <label class="wiz-radio-card ${layout === 'observer' ? 'selected' : ''}">
                        <input type="radio" name="wiz-layout" value="observer" ${layout === 'observer' ? 'checked' : ''} />
                        <div class="wiz-radio-title">OBSERVER</div>
                        <div class="wiz-radio-desc">Minimal panels. Clean map view with alerts only.</div>
                    </label>
                    <label class="wiz-radio-card ${layout === 'tactical' ? 'selected' : ''}">
                        <input type="radio" name="wiz-layout" value="tactical" ${layout === 'tactical' ? 'checked' : ''} />
                        <div class="wiz-radio-title">TACTICAL</div>
                        <div class="wiz-radio-desc">Units + Alerts + Minimap. No AI commander panel.</div>
                    </label>
                </div>
            `;
        },
        save: (bodyEl) => {
            const checked = bodyEl.querySelector('input[name="wiz-layout"]:checked');
            if (checked) ConfigStore.set('defaultLayout', checked.value);
        },
    },
    {
        id: 'complete',
        title: 'SETUP COMPLETE',
        render: () => `
            <div class="wiz-hero">
                <div class="wiz-check-icon">&#10003;</div>
                <div class="wiz-tagline">Configuration saved</div>
            </div>
            <p class="wiz-text">
                Your settings have been saved. You can modify them anytime
                from the System panel or by reopening this wizard from
                VIEW &gt; System &gt; Setup Wizard.
            </p>
            <p class="wiz-text wiz-hint">
                Tip: Press <kbd>?</kbd> for keyboard shortcuts. Open panels from the VIEW menu.
            </p>
        `,
    },
];

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const SetupWizardPanelDef = {
    id: 'setup-wizard',
    title: 'SETUP WIZARD',
    defaultPosition: { x: 250, y: 80 },
    defaultSize: { w: 520, h: 560 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'setup-wizard-inner';
        el.innerHTML = `
            <div class="wiz-progress"></div>
            <div class="wiz-step-title"></div>
            <div class="wiz-content"></div>
            <div class="wiz-nav">
                <button class="panel-action-btn wiz-btn-back">BACK</button>
                <span class="wiz-step-indicator"></span>
                <button class="panel-action-btn panel-action-btn-primary wiz-btn-next">NEXT</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        let step = 0;

        const progressEl = bodyEl.querySelector('.wiz-progress');
        const titleEl = bodyEl.querySelector('.wiz-step-title');
        const contentEl = bodyEl.querySelector('.wiz-content');
        const backBtn = bodyEl.querySelector('.wiz-btn-back');
        const nextBtn = bodyEl.querySelector('.wiz-btn-next');
        const indicatorEl = bodyEl.querySelector('.wiz-step-indicator');

        function renderStep() {
            const s = STEPS[step];
            const pct = ((step + 1) / STEPS.length) * 100;
            progressEl.innerHTML = `<div class="wiz-progress-bar" style="width:${pct}%"></div>`;
            titleEl.textContent = s.title;
            contentEl.innerHTML = s.render();
            indicatorEl.textContent = `${step + 1} / ${STEPS.length}`;

            backBtn.style.display = step === 0 ? 'none' : '';
            nextBtn.textContent = step === STEPS.length - 1 ? 'FINISH' : 'NEXT';

            // Show crosshairs when on map-center step
            EventBus.emit('map:crosshairs', { show: s.id === 'map-center' });

            // Wire preset buttons for map center step
            contentEl.querySelectorAll('.wiz-preset-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const latInput = contentEl.querySelector('[data-key="map.centerLat"]');
                    const lngInput = contentEl.querySelector('[data-key="map.centerLng"]');

                    // "Use Current" — read map's current center
                    if (btn.classList.contains('wiz-use-current')) {
                        // Try to get map center from maplibre instance
                        const mapEl = document.querySelector('.maplibregl-map');
                        const mapInstance = mapEl && mapEl.__map;
                        if (mapInstance) {
                            const center = mapInstance.getCenter();
                            if (latInput) latInput.value = center.lat.toFixed(4);
                            if (lngInput) lngInput.value = center.lng.toFixed(4);
                        } else {
                            // Fallback: emit event to get map center
                            EventBus.emit('map:get-center', (center) => {
                                if (center && latInput && lngInput) {
                                    latInput.value = center.lat.toFixed(4);
                                    lngInput.value = center.lng.toFixed(4);
                                }
                            });
                        }
                        return;
                    }

                    // City preset — update inputs AND fly map there
                    if (latInput) latInput.value = btn.dataset.lat;
                    if (lngInput) lngInput.value = btn.dataset.lng;

                    // Fly the map to the selected location
                    const lat = parseFloat(btn.dataset.lat);
                    const lng = parseFloat(btn.dataset.lng);
                    if (!isNaN(lat) && !isNaN(lng)) {
                        EventBus.emit('map:fly-to', { lat, lng, zoom: 12 });
                    }
                });
            });

            // Live coordinate display — update as user moves the map
            const liveCoordsEl = contentEl.querySelector('#wiz-live-coords');
            if (liveCoordsEl) {
                const mapEl = document.querySelector('.maplibregl-map');
                const mapInstance = mapEl && mapEl.__map;
                if (mapInstance) {
                    const updateCoords = () => {
                        const c = mapInstance.getCenter();
                        liveCoordsEl.textContent = `Map center: ${c.lat.toFixed(4)}, ${c.lng.toFixed(4)}`;
                    };
                    mapInstance.on('moveend', updateCoords);
                    updateCoords();
                    // Store cleanup ref
                    panel._wizMapListener = { map: mapInstance, fn: updateCoords };
                }
            }

            // Wire radio card selection highlight
            contentEl.querySelectorAll('.wiz-radio-card input[type="radio"]').forEach(radio => {
                radio.addEventListener('change', () => {
                    contentEl.querySelectorAll('.wiz-radio-card').forEach(c => c.classList.remove('selected'));
                    radio.closest('.wiz-radio-card').classList.add('selected');
                });
            });
        }

        backBtn.addEventListener('click', () => {
            if (step > 0) {
                // Save current step before going back
                const s = STEPS[step];
                if (s.save) s.save(contentEl);
                step--;
                renderStep();
            }
        });

        nextBtn.addEventListener('click', () => {
            const s = STEPS[step];
            if (s.save) s.save(contentEl);

            if (step < STEPS.length - 1) {
                step++;
                renderStep();
            } else {
                // Finish — mark wizard complete and apply settings
                ConfigStore.markWizardComplete();
                EventBus.emit('toast:show', { message: 'Setup complete! Configuration saved.', type: 'info' });

                // Apply layout if configured
                const layout = ConfigStore.get('defaultLayout', 'commander');
                EventBus.emit('layout:apply', { name: layout });

                // Start demo if configured
                if (ConfigStore.get('demo.autoStart', false)) {
                    fetch('/api/demo/start', { method: 'POST' }).catch(() => {});
                }

                // Close wizard panel
                if (panel && panel.manager) {
                    panel.manager.close('setup-wizard');
                }
            }
        });

        renderStep();
    },

    unmount(_bodyEl, panel) {
        // Clean up map moveend listener
        if (panel._wizMapListener) {
            panel._wizMapListener.map.off('moveend', panel._wizMapListener.fn);
            panel._wizMapListener = null;
        }
        // Hide crosshairs when wizard closes
        EventBus.emit('map:crosshairs', { show: false });
    },

    shouldAutoOpen() {
        return !ConfigStore.isWizardComplete();
    },
};
