// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// WiFi Fingerprint Panel
// Shows WiFi-BLE correlation links, probe fingerprints, and device dossier enrichment.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const REFRESH_INTERVAL_MS = 10000;

function scoreColor(score) {
    if (score >= 0.7) return '#05ffa1';   // green — strong
    if (score >= 0.4) return '#fcee0a';   // yellow — moderate
    return '#ff2a6d';                     // red — weak
}

export const WiFiFingerprintPanelDef = {
    id: 'wifi-fingerprint',
    title: 'WIFI FINGERPRINT',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 360, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'wifi-fingerprint-panel-inner';
        el.innerHTML = `
            <div class="wifi-fp-toolbar">
                <span class="wifi-fp-stat mono" data-bind="fp-status">Loading...</span>
                <button class="panel-action-btn" data-action="refresh" title="Refresh">REF</button>
            </div>
            <div class="wifi-fp-section">
                <div class="wifi-fp-section-title">CORRELATION LINKS</div>
                <ul class="panel-list wifi-fp-links" data-bind="fp-links" role="list" aria-label="Correlation links">
                    <li class="panel-empty">No correlations yet</li>
                </ul>
            </div>
        `;

        const statusEl = el.querySelector('[data-bind="fp-status"]');
        const linksEl = el.querySelector('[data-bind="fp-links"]');
        const refreshBtn = el.querySelector('[data-action="refresh"]');

        async function refresh() {
            try {
                const [statusResp, linksResp] = await Promise.all([
                    fetch('/api/wifi-fingerprint/status'),
                    fetch('/api/wifi-fingerprint/links?min_score=0.1'),
                ]);
                const status = await statusResp.json();
                const linksData = await linksResp.json();

                statusEl.textContent = `${status.unique_wifi_devices || 0} WiFi | ${status.strong_links || 0} strong links`;

                const links = linksData.links || [];
                if (links.length === 0) {
                    linksEl.innerHTML = '<li class="panel-empty">No correlations yet</li>';
                } else {
                    linksEl.innerHTML = links.slice(0, 30).map(l => {
                        const color = scoreColor(l.score);
                        const ssids = (l.ssids_seen || []).slice(0, 3).join(', ');
                        return `<li class="wifi-fp-link-item">
                            <div class="wifi-fp-link-macs">
                                <span class="mono" style="color:${color}">${_esc(l.wifi_mac)}</span>
                                <span class="wifi-fp-arrow">&rarr;</span>
                                <span class="mono">${_esc(l.ble_mac)}</span>
                            </div>
                            <div class="wifi-fp-link-meta">
                                <span style="color:${color}">${(l.score * 100).toFixed(0)}%</span>
                                <span class="wifi-fp-evidence">${l.evidence_count} evidence</span>
                                ${ssids ? `<span class="wifi-fp-ssids">${_esc(ssids)}</span>` : ''}
                            </div>
                        </li>`;
                    }).join('');
                }
            } catch (err) {
                statusEl.textContent = 'Error loading data';
            }
        }

        refreshBtn.addEventListener('click', refresh);

        // Auto-refresh
        refresh();
        const interval = setInterval(refresh, REFRESH_INTERVAL_MS);

        // Listen for correlation events
        const handler = EventBus.on('wifi_fingerprint.correlation', () => {
            refresh();
        });

        panel._fpCleanup = () => {
            clearInterval(interval);
            if (handler && handler.off) handler.off();
        };

        return el;
    },

    destroy(panel) {
        if (panel._fpCleanup) panel._fpCleanup();
    },
};
