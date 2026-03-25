// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Edge Tracker Panel
// Displays live BLE device and WiFi network tracking from tritium-edge sensor nodes.
// Subscribes to edge:ble_update and edge:wifi_update EventBus events for live updates.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// ============================================================
// RSSI color helpers
// ============================================================

function rssiColor(rssi) {
    if (rssi > -50) return '#05ffa1';   // green — strong
    if (rssi > -70) return '#fcee0a';   // yellow — moderate
    return '#ff2a6d';                   // red/magenta — weak
}

function rssiBar(rssi) {
    // Normalize RSSI (-100 to -30) to 0-100%
    const pct = Math.max(0, Math.min(100, ((rssi + 100) / 70) * 100));
    return pct;
}

// ============================================================
// Panel Definition
// ============================================================

const REFRESH_INTERVAL_MS = 5000;

export const EdgeTrackerPanelDef = {
    id: 'edge-tracker',
    title: 'EDGE TRACKER',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 340, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'edge-tracker-panel-inner';
        el.innerHTML = `
            <div class="edge-tracker-tabs">
                <button class="edge-tracker-tab active" data-tab="ble">BLE</button>
                <button class="edge-tracker-tab" data-tab="wifi">WIFI</button>
            </div>
            <div class="edge-tracker-tab-content" data-tab-content="ble">
                <div class="edge-tracker-toolbar">
                    <span class="edge-tracker-stat mono" data-bind="ble-active-count">0 active</span>
                    <span class="edge-tracker-sep">|</span>
                    <span class="edge-tracker-stat mono" data-bind="ble-tracked-count">0 tracked</span>
                    <button class="panel-action-btn" data-action="refresh-ble" title="Refresh BLE data">REF</button>
                </div>
                <ul class="panel-list edge-tracker-list" data-bind="ble-device-list" role="list" aria-label="BLE device list">
                    <li class="panel-empty">Scanning for BLE devices...</li>
                </ul>
            </div>
            <div class="edge-tracker-tab-content" data-tab-content="wifi" style="display:none">
                <div class="edge-tracker-toolbar">
                    <span class="edge-tracker-stat mono" data-bind="wifi-active-count">0 active</span>
                    <span class="edge-tracker-sep">|</span>
                    <span class="edge-tracker-stat mono" data-bind="wifi-tracked-count">0 tracked</span>
                    <button class="panel-action-btn" data-action="refresh-wifi" title="Refresh WiFi data">REF</button>
                </div>
                <ul class="panel-list edge-tracker-list" data-bind="wifi-network-list" role="list" aria-label="WiFi network list">
                    <li class="panel-empty">Scanning for WiFi networks...</li>
                </ul>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // -- Tab switching ------------------------------------------------
        const tabs = bodyEl.querySelectorAll('.edge-tracker-tab');
        const tabContents = bodyEl.querySelectorAll('.edge-tracker-tab-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const target = tab.getAttribute('data-tab');
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                tabContents.forEach(tc => {
                    tc.style.display = tc.getAttribute('data-tab-content') === target ? '' : 'none';
                });
            });
        });

        // -- BLE section --------------------------------------------------
        const bleListEl = bodyEl.querySelector('[data-bind="ble-device-list"]');
        const bleActiveCountEl = bodyEl.querySelector('[data-bind="ble-active-count"]');
        const bleTrackedCountEl = bodyEl.querySelector('[data-bind="ble-tracked-count"]');
        const bleRefreshBtn = bodyEl.querySelector('[data-action="refresh-ble"]');

        let bleDevices = [];

        function renderBle() {
            if (!bleListEl) return;

            const activeCount = bleDevices.length;
            const trackedCount = bleDevices.filter(d => d.tracked).length;
            if (bleActiveCountEl) bleActiveCountEl.textContent = `${activeCount} active`;
            if (bleTrackedCountEl) bleTrackedCountEl.textContent = `${trackedCount} tracked`;

            if (bleDevices.length === 0) {
                bleListEl.innerHTML = '<li class="panel-empty">Scanning for BLE devices...</li>';
                return;
            }

            const sorted = bleDevices.slice().sort((a, b) => {
                return (b.strongest_rssi || b.last_rssi || -100) - (a.strongest_rssi || a.last_rssi || -100);
            });

            bleListEl.innerHTML = sorted.map(dev => {
                const mac = _esc(dev.mac || '??:??:??:??:??:??');
                const name = dev.name ? `"${_esc(dev.name)}"` : '';
                const rssi = dev.strongest_rssi || dev.last_rssi || -100;
                const color = rssiColor(rssi);
                const nodeCount = dev.node_count || 0;
                const isTracked = dev.tracked;
                const targetColor = dev.target_color || '#05ffa1';

                const trackBtn = isTracked
                    ? `<span class="edge-tracker-tracked-indicator" style="color:${_esc(targetColor)}">&#9679;</span>`
                    : `<button class="edge-tracker-track-btn" data-mac="${_esc(mac)}" data-name="${_esc(dev.name || mac)}" title="Track this device">TRACK</button>`;

                const posInfo = dev.position
                    ? `<span class="edge-tracker-pos mono" title="Estimated position">[${dev.position.lat.toFixed(6)}, ${dev.position.lon.toFixed(6)}]</span>`
                    : '';

                return `<li class="edge-tracker-device${isTracked ? ' tracked' : ''}">
                    <div class="edge-tracker-device-header">
                        <span class="edge-tracker-mac mono">${mac}</span>
                        <span class="edge-tracker-name">${name}</span>
                    </div>
                    <div class="edge-tracker-device-detail">
                        <span class="edge-tracker-rssi mono" style="color:${color}">${rssi} dBm</span>
                        <span class="edge-tracker-sep">|</span>
                        <span class="edge-tracker-nodes mono">${nodeCount} node${nodeCount !== 1 ? 's' : ''}</span>
                        ${trackBtn}
                    </div>
                    ${posInfo}
                </li>`;
            }).join('');

            bleListEl.querySelectorAll('.edge-tracker-track-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const mac = btn.getAttribute('data-mac');
                    const name = btn.getAttribute('data-name');
                    trackBleDevice(mac, name);
                });
            });
        }

        function trackBleDevice(mac, label) {
            fetch('/api/edge/ble/targets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mac, label: label || mac }),
            })
                .then(r => r.json())
                .then(() => fetchBleDevices())
                .catch(err => console.error('[EdgeTracker] BLE track error:', err));
        }

        function fetchBleDevices() {
            fetch('/api/edge/ble/active')
                .then(r => r.json())
                .then(data => {
                    bleDevices = data.devices || [];
                    renderBle();
                })
                .catch(err => {
                    console.error('[EdgeTracker] BLE fetch error:', err);
                });
        }

        function onBleUpdate(data) {
            if (data && Array.isArray(data.devices)) {
                bleDevices = data.devices;
                renderBle();
            } else {
                fetchBleDevices();
            }
        }

        // -- WiFi section -------------------------------------------------
        const wifiListEl = bodyEl.querySelector('[data-bind="wifi-network-list"]');
        const wifiActiveCountEl = bodyEl.querySelector('[data-bind="wifi-active-count"]');
        const wifiTrackedCountEl = bodyEl.querySelector('[data-bind="wifi-tracked-count"]');
        const wifiRefreshBtn = bodyEl.querySelector('[data-action="refresh-wifi"]');

        let wifiNetworks = [];

        function renderWifi() {
            if (!wifiListEl) return;

            const activeCount = wifiNetworks.length;
            const trackedCount = wifiNetworks.filter(n => n.tracked).length;
            if (wifiActiveCountEl) wifiActiveCountEl.textContent = `${activeCount} active`;
            if (wifiTrackedCountEl) wifiTrackedCountEl.textContent = `${trackedCount} tracked`;

            if (wifiNetworks.length === 0) {
                wifiListEl.innerHTML = '<li class="panel-empty">Scanning for WiFi networks...</li>';
                return;
            }

            const sorted = wifiNetworks.slice().sort((a, b) => {
                return (b.strongest_rssi || -100) - (a.strongest_rssi || -100);
            });

            wifiListEl.innerHTML = sorted.map(net => {
                const bssid = _esc(net.bssid || '??:??:??:??:??:??');
                const ssid = net.ssid ? _esc(net.ssid) : '<hidden>';
                const rssi = net.strongest_rssi || -100;
                const color = rssiColor(rssi);
                const channel = net.channel || 0;
                const authType = net.auth_type ? _esc(net.auth_type) : '';
                const nodeCount = net.node_count || 0;
                const isTracked = net.tracked;
                const targetColor = net.target_color || '#05ffa1';

                const trackBtn = isTracked
                    ? `<span class="edge-tracker-tracked-indicator" style="color:${_esc(targetColor)}">&#9679;</span>`
                    : `<button class="edge-tracker-wifi-track-btn" data-bssid="${_esc(bssid)}" data-ssid="${_esc(net.ssid || '')}" title="Track this network">TRACK</button>`;

                const channelInfo = channel > 0 ? `CH ${channel}` : '';
                const authInfo = authType ? `${authType}` : '';
                const metaParts = [channelInfo, authInfo].filter(Boolean).join(' ');

                return `<li class="edge-tracker-device${isTracked ? ' tracked' : ''}">
                    <div class="edge-tracker-device-header">
                        <span class="edge-tracker-mac mono">${bssid}</span>
                        <span class="edge-tracker-name">${ssid}</span>
                    </div>
                    <div class="edge-tracker-device-detail">
                        <span class="edge-tracker-rssi mono" style="color:${color}">${rssi} dBm</span>
                        <span class="edge-tracker-sep">|</span>
                        <span class="edge-tracker-nodes mono">${metaParts}</span>
                        <span class="edge-tracker-sep">|</span>
                        <span class="edge-tracker-nodes mono">${nodeCount} node${nodeCount !== 1 ? 's' : ''}</span>
                        ${trackBtn}
                    </div>
                </li>`;
            }).join('');

            wifiListEl.querySelectorAll('.edge-tracker-wifi-track-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const bssid = btn.getAttribute('data-bssid');
                    const ssid = btn.getAttribute('data-ssid');
                    trackWifiNetwork(bssid, ssid);
                });
            });
        }

        function trackWifiNetwork(bssid, ssid) {
            fetch('/api/edge/wifi/targets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bssid, ssid: ssid || '', label: ssid || bssid }),
            })
                .then(r => r.json())
                .then(() => fetchWifiNetworks())
                .catch(err => console.error('[EdgeTracker] WiFi track error:', err));
        }

        function fetchWifiNetworks() {
            fetch('/api/edge/wifi/active')
                .then(r => r.json())
                .then(data => {
                    wifiNetworks = data.networks || [];
                    renderWifi();
                })
                .catch(err => {
                    console.error('[EdgeTracker] WiFi fetch error:', err);
                });
        }

        function onWifiUpdate(data) {
            if (data && Array.isArray(data.networks)) {
                wifiNetworks = data.networks;
                renderWifi();
            } else {
                fetchWifiNetworks();
            }
        }

        // -- Subscriptions and timers -------------------------------------

        const unsubBle = EventBus.on('edge:ble_update', onBleUpdate);
        panel._unsubs.push(unsubBle);

        const unsubWifi = EventBus.on('edge:wifi_update', onWifiUpdate);
        panel._unsubs.push(unsubWifi);

        if (bleRefreshBtn) {
            bleRefreshBtn.addEventListener('click', fetchBleDevices);
        }
        if (wifiRefreshBtn) {
            wifiRefreshBtn.addEventListener('click', fetchWifiNetworks);
        }

        // Initial fetch for both
        fetchBleDevices();
        fetchWifiNetworks();

        // Auto-refresh every 5 seconds
        const bleTimer = setInterval(fetchBleDevices, REFRESH_INTERVAL_MS);
        const wifiTimer = setInterval(fetchWifiNetworks, REFRESH_INTERVAL_MS);
        panel._unsubs.push(() => {
            clearInterval(bleTimer);
            clearInterval(wifiTimer);
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
