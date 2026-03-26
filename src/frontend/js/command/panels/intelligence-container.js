// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Intelligence Container — tabbed panel for all analysis and investigation tools.
 *
 * Built-in tabs: Overview, Threat Feeds
 * Addon tabs: Graph Explorer, Behavioral Intelligence, Fusion, Reid
 */

import { createTabbedContainer } from './tabbed-container.js';

function _esc(str) {
    if (!str) return '';
    const d = document.createElement('div');
    d.textContent = String(str);
    return d.innerHTML;
}

export const IntelligenceContainerDef = createTabbedContainer(
    'intelligence-container',
    'INTEL',
    [
        {
            id: 'intel-overview-tab',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = `
                    <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                        <div style="color:#ff2a6d;margin-bottom:8px;font-size:12px">INTEL</div>
                        <p style="color:#666;font-size:10px">
                            Target analysis, investigation, and pattern detection.<br>
                            Dossiers, signal histories, behavioral analysis, correlation.
                        </p>
                    </div>
                `;
            },
        },
        {
            id: 'intel-threat-feeds-tab',
            title: 'THREATS',
            create(el) {
                el.innerHTML = `
                    <div style="padding:6px;font-family:'JetBrains Mono',monospace;font-size:10px;color:#ccc">
                        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                            <span style="color:#ff2a6d;font-size:11px;font-weight:bold">THREAT INDICATORS</span>
                            <button class="panel-action-btn panel-action-btn-primary" data-action="tf-refresh" style="font-size:0.42rem;padding:2px 6px">REFRESH</button>
                        </div>
                        <div data-bind="tf-stats" style="margin-bottom:6px">
                            <div style="color:#555;text-align:center;padding:4px">Loading...</div>
                        </div>
                        <div data-bind="tf-list" style="max-height:300px;overflow-y:auto">
                            <div style="color:#555;text-align:center;padding:8px">Loading threat indicators...</div>
                        </div>
                    </div>
                `;

                // Auto-fetch when tab is created
                const statsEl = el.querySelector('[data-bind="tf-stats"]');
                const listEl = el.querySelector('[data-bind="tf-list"]');
                const refreshBtn = el.querySelector('[data-action="tf-refresh"]');

                async function fetchThreats() {
                    try {
                        const [indResp, statsResp] = await Promise.all([
                            fetch('/api/threats/'),
                            fetch('/api/threats/stats'),
                        ]);
                        if (!indResp.ok || !statsResp.ok) throw new Error('HTTP error');
                        const indData = await indResp.json();
                        const statsData = await statsResp.json();

                        // Render stats
                        const hostile = (statsData.by_level && statsData.by_level.hostile) || 0;
                        const suspicious = (statsData.by_level && statsData.by_level.suspicious) || 0;
                        if (statsEl) {
                            statsEl.innerHTML = `
                                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px">
                                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;text-align:center">
                                        <div style="font-size:8px;color:#666;text-transform:uppercase">Total</div>
                                        <div style="font-size:14px;color:#00f0ff">${statsData.total || 0}</div>
                                    </div>
                                    <div style="background:#0e0e14;border:1px solid #ff2a6d33;padding:4px;text-align:center">
                                        <div style="font-size:8px;color:#666;text-transform:uppercase">Hostile</div>
                                        <div style="font-size:14px;color:#ff2a6d">${hostile}</div>
                                    </div>
                                    <div style="background:#0e0e14;border:1px solid #fcee0a33;padding:4px;text-align:center">
                                        <div style="font-size:8px;color:#666;text-transform:uppercase">Suspicious</div>
                                        <div style="font-size:14px;color:#fcee0a">${suspicious}</div>
                                    </div>
                                </div>
                            `;
                        }

                        // Render indicator list
                        const indicators = indData.indicators || [];
                        if (listEl) {
                            if (indicators.length === 0) {
                                listEl.innerHTML = '<div style="color:#555;text-align:center;padding:8px">No threat indicators loaded</div>';
                            } else {
                                const LEVEL_COLORS = { hostile: '#ff2a6d', suspicious: '#fcee0a' };
                                listEl.innerHTML = indicators.slice(0, 50).map(ind => {
                                    const color = LEVEL_COLORS[ind.threat_level] || '#888';
                                    return `<div style="border-left:3px solid ${color};padding:3px 6px;margin-bottom:2px;font-size:10px">
                                        <span class="mono" style="color:#ddd">${_esc(ind.value)}</span>
                                        <span style="color:#666;margin-left:6px">${_esc(ind.indicator_type)}</span>
                                        <span style="color:#555;margin-left:6px;font-size:9px">${_esc(ind.description || '')}</span>
                                    </div>`;
                                }).join('');
                            }
                        }
                    } catch (e) {
                        if (listEl) listEl.innerHTML = '<div style="color:#ff2a6d;text-align:center;padding:8px">Failed to load</div>';
                    }
                }

                if (refreshBtn) refreshBtn.addEventListener('click', fetchThreats);
                fetchThreats();
            },
        },
    ],
    {
        category: 'intel',
        defaultSize: { w: 380, h: 500 },
        defaultPosition: { x: 60, y: 100 },
    }
);
