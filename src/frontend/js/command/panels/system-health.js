// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// System Health Panel
// At-a-glance view of the entire Tritium system: plugin statuses,
// API endpoint counts, test results, notification counts, active
// targets, dossier counts. One panel to see everything.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


function _statusDot(healthy) {
    const cls = healthy ? 'panel-dot-green' : 'panel-dot-neutral';
    return `<span class="panel-dot ${cls}"></span>`;
}

/**
 * Render an SVG dependency graph showing which plugins depend on which
 * services/capabilities. Nodes are plugins, edges are dependency relationships.
 */
function _renderPluginDependencyGraph(plugins) {
    if (!plugins || plugins.length === 0) return '';

    // Build dependency map: plugin -> deps, plugin -> capabilities
    const nodes = [];
    const edges = [];
    const serviceNodes = new Set();

    for (const p of plugins) {
        const pid = p.id || p.name || '?';
        nodes.push({ id: pid, type: 'plugin', healthy: p.healthy });

        // Dependencies (other plugins this one needs)
        if (p.dependencies && p.dependencies.length > 0) {
            for (const dep of p.dependencies) {
                edges.push({ from: pid, to: dep, type: 'depends' });
                serviceNodes.add(dep);
            }
        }

        // Capabilities (services this plugin provides)
        if (p.capabilities && p.capabilities.length > 0) {
            for (const cap of p.capabilities) {
                edges.push({ from: pid, to: cap, type: 'provides' });
                serviceNodes.add(cap);
            }
        }
    }

    // Add service nodes that aren't also plugins
    const pluginIds = new Set(nodes.map(n => n.id));
    for (const svc of serviceNodes) {
        if (!pluginIds.has(svc)) {
            nodes.push({ id: svc, type: 'service', healthy: true });
        }
    }

    if (edges.length === 0) {
        return `<div style="color:var(--text-ghost);font-size:0.4rem;padding:2px 0">No dependencies declared</div>`;
    }

    // Layout: plugins on top row, services on bottom
    const pluginNodes = nodes.filter(n => n.type === 'plugin');
    const svcOnlyNodes = nodes.filter(n => n.type === 'service');

    const totalNodes = pluginNodes.length + svcOnlyNodes.length;
    const svgW = Math.max(300, totalNodes * 55);
    const svgH = svcOnlyNodes.length > 0 ? 100 : 50;

    // Position plugins evenly on top row
    const positions = {};
    const pluginSpacing = svgW / (pluginNodes.length + 1);
    pluginNodes.forEach((n, i) => {
        positions[n.id] = { x: pluginSpacing * (i + 1), y: 18 };
    });

    // Position services evenly on bottom row
    if (svcOnlyNodes.length > 0) {
        const svcSpacing = svgW / (svcOnlyNodes.length + 1);
        svcOnlyNodes.forEach((n, i) => {
            positions[n.id] = { x: svcSpacing * (i + 1), y: svgH - 18 };
        });
    }

    let svg = `<svg width="100%" viewBox="0 0 ${svgW} ${svgH}" style="display:block;max-height:120px;">`;
    svg += `<defs><marker id="arrow-dep" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="rgba(0,240,255,0.5)"/></marker>`;
    svg += `<marker id="arrow-prov" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10" fill="rgba(5,255,161,0.3)"/></marker></defs>`;

    // Draw edges
    for (const e of edges) {
        const from = positions[e.from];
        const to = positions[e.to];
        if (!from || !to) continue;

        const color = e.type === 'depends' ? 'rgba(0,240,255,0.4)' : 'rgba(5,255,161,0.25)';
        const marker = e.type === 'depends' ? 'url(#arrow-dep)' : 'url(#arrow-prov)';
        const dash = e.type === 'provides' ? ' stroke-dasharray="3,2"' : '';
        svg += `<line x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}" stroke="${color}" stroke-width="1"${dash} marker-end="${marker}"/>`;
    }

    // Draw nodes
    for (const n of nodes) {
        const pos = positions[n.id];
        if (!pos) continue;

        const isPlugin = n.type === 'plugin';
        const fill = isPlugin
            ? (n.healthy ? 'rgba(5,255,161,0.15)' : 'rgba(255,42,109,0.15)')
            : 'rgba(0,240,255,0.1)';
        const stroke = isPlugin
            ? (n.healthy ? 'rgba(5,255,161,0.5)' : 'rgba(255,42,109,0.5)')
            : 'rgba(0,240,255,0.3)';

        if (isPlugin) {
            svg += `<rect x="${pos.x - 24}" y="${pos.y - 8}" width="48" height="16" rx="3" fill="${fill}" stroke="${stroke}" stroke-width="1"/>`;
        } else {
            svg += `<ellipse cx="${pos.x}" cy="${pos.y}" rx="24" ry="8" fill="${fill}" stroke="${stroke}" stroke-width="1"/>`;
        }

        // Truncate label
        const label = _esc(n.id.length > 10 ? n.id.slice(0, 9) + '\u2026' : n.id);
        const textColor = isPlugin ? '#ccc' : '#00f0ff';
        svg += `<text x="${pos.x}" y="${pos.y + 3}" text-anchor="middle" fill="${textColor}" font-size="7" font-family="monospace">${label}</text>`;
    }

    svg += '</svg>';

    // Legend
    svg += `<div style="display:flex;gap:12px;font-size:0.35rem;color:var(--text-ghost);padding:2px 0">`;
    svg += `<span><span style="color:rgba(0,240,255,0.6)">\u2500\u25B6</span> depends on</span>`;
    svg += `<span><span style="color:rgba(5,255,161,0.5)">\u2504\u25B6</span> provides</span>`;
    svg += `<span><span style="display:inline-block;width:8px;height:8px;background:rgba(5,255,161,0.15);border:1px solid rgba(5,255,161,0.5);border-radius:2px;vertical-align:middle"></span> plugin</span>`;
    svg += `<span><span style="display:inline-block;width:8px;height:8px;background:rgba(0,240,255,0.1);border:1px solid rgba(0,240,255,0.3);border-radius:50%;vertical-align:middle"></span> service</span>`;
    svg += `</div>`;

    return svg;
}

export const SystemHealthPanelDef = {
    id: 'system-health',
    title: 'SYSTEM HEALTH',
    defaultPosition: { x: 8, y: 60 },
    defaultSize: { w: 340, h: 520 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'system-health-panel-inner';
        el.innerHTML = `
            <div class="sys-health-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-health">REFRESH</button>
                <span class="sys-health-timestamp mono" data-bind="timestamp" style="font-size:0.4rem;color:var(--text-ghost);margin-left:auto"></span>
            </div>
            <div class="sys-health-content" data-bind="content">
                <div class="panel-empty">Loading system health...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="timestamp"]');

        async function fetchHealth() {
            if (!contentEl) return;
            contentEl.innerHTML = '<div class="panel-empty">Scanning...</div>';

            // Fetch from all available endpoints in parallel
            const results = {};
            const fetches = [
                ['plugins', '/api/plugins'],
                ['pluginHealth', '/api/plugins/health'],
                ['targets', '/api/targets'],
                ['dossiers', '/api/dossiers'],
                ['notifications', '/api/notifications'],
                ['health', '/api/health'],
                ['demo', '/api/demo/status'],
                ['testing', '/api/testing/report'],
                ['amy', '/api/amy/status'],
            ];

            await Promise.allSettled(
                fetches.map(async ([key, url]) => {
                    try {
                        const resp = await fetch(url);
                        if (resp.ok) {
                            results[key] = await resp.json();
                        }
                    } catch (_) { /* endpoint unavailable */ }
                })
            );

            let html = '';

            // --- Overall status ---
            const healthData = results.health || {};
            const serverStatus = healthData.status || 'unknown';
            const serverColor = serverStatus === 'ok' || serverStatus === 'healthy'
                ? 'var(--green)' : 'var(--amber)';
            html += `<div class="panel-section-label">SERVER</div>`;
            html += `<div class="panel-stat-row">
                <span class="panel-stat-label">STATUS</span>
                <span class="panel-stat-value" style="color:${serverColor}">${_esc(serverStatus.toUpperCase())}</span>
            </div>`;
            if (healthData.uptime) {
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">UPTIME</span>
                    <span class="panel-stat-value mono">${_esc(healthData.uptime)}</span>
                </div>`;
            }
            if (healthData.version) {
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">VERSION</span>
                    <span class="panel-stat-value mono">${_esc(healthData.version)}</span>
                </div>`;
            }

            // --- MQTT Broker ---
            const subsystems = healthData.subsystems || {};
            const mqttBridge = subsystems.mqtt || 'disabled';
            const mqttBroker = subsystems.mqtt_broker || 'unknown';
            const mqttHint = subsystems.mqtt_broker_hint || '';
            const brokerReachable = mqttBroker === 'reachable';
            const brokerColor = brokerReachable ? 'var(--green)' : 'var(--magenta)';
            const bridgeColor = mqttBridge === 'connected' ? 'var(--green)'
                : mqttBridge === 'disabled' ? 'var(--text-ghost)' : 'var(--magenta)';

            html += `<div class="panel-section-label">MQTT</div>`;
            html += `<div class="panel-stat-row">
                <span class="panel-stat-label">BROKER</span>
                <span class="panel-stat-value" style="color:${brokerColor}">${_esc(mqttBroker.toUpperCase())}</span>
            </div>`;
            html += `<div class="panel-stat-row">
                <span class="panel-stat-label">BRIDGE</span>
                <span class="panel-stat-value" style="color:${bridgeColor}">${_esc(mqttBridge.toUpperCase())}</span>
            </div>`;
            if (!brokerReachable) {
                if (mqttHint) {
                    html += `<div style="padding:2px 8px;font-size:0.35rem;color:var(--amber);font-family:monospace;word-break:break-word">${_esc(mqttHint)}</div>`;
                }
                html += `<div style="padding:4px 8px">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="start-mqtt" style="font-size:0.35rem;padding:2px 8px">START MQTT BROKER</button>
                </div>`;
            }

            // --- Meshtastic Bridge ---
            const meshBridge = subsystems.meshtastic || 'disabled';
            const meshConnected = meshBridge === 'connected';
            const meshColor = meshConnected ? 'var(--green)' : 'var(--text-ghost)';
            html += `<div class="panel-section-label">MESHTASTIC</div>`;
            html += `<div class="panel-stat-row">
                <span class="panel-stat-label">BRIDGE</span>
                <span class="panel-stat-value" style="color:${meshColor}">${_esc(meshBridge.toUpperCase())}</span>
            </div>`;
            if (!meshConnected) {
                html += `<div style="padding:4px 8px">
                    <button class="panel-action-btn" data-action="start-mesh-bridge" style="font-size:0.35rem;padding:2px 8px">START BRIDGE</button>
                </div>`;
            }

            // --- Plugins ---
            const plugins = results.plugins || [];
            const pluginHealth = results.pluginHealth || {};
            if (plugins.length > 0) {
                const healthyCount = plugins.filter(p => p.healthy).length;
                const totalCount = plugins.length;
                const allHealthy = healthyCount === totalCount;
                const summaryColor = allHealthy ? 'var(--green)' : 'var(--amber)';

                html += `<div class="panel-section-label">PLUGINS (${healthyCount}/${totalCount})</div>`;
                for (const p of plugins) {
                    const dot = _statusDot(p.healthy);
                    const name = p.name || p.id || '?';
                    const version = p.version || '';
                    const statusText = p.healthy ? 'OK' : 'DOWN';
                    const statusColor = p.healthy ? 'var(--green)' : 'var(--magenta)';
                    html += `<div class="panel-stat-row">
                        ${dot}
                        <span class="panel-stat-label" style="flex:1">${_esc(name)}</span>
                        <span class="mono" style="font-size:0.4rem;color:var(--text-ghost);margin-right:8px">${_esc(version)}</span>
                        <span class="panel-stat-value" style="color:${statusColor};min-width:30px">${statusText}</span>
                    </div>`;
                }

                // --- Plugin Dependency Graph ---
                const hasAnyDeps = plugins.some(p => p.dependencies && p.dependencies.length > 0);
                const hasAnyCaps = plugins.some(p => p.capabilities && p.capabilities.length > 0);
                if (hasAnyDeps || hasAnyCaps) {
                    html += `<div class="panel-section-label">PLUGIN DEPENDENCIES</div>`;
                    html += `<div style="padding:4px 0;">`;
                    html += _renderPluginDependencyGraph(plugins);
                    html += `</div>`;
                }
            }

            // --- Targets ---
            const targets = results.targets;
            if (targets) {
                const targetList = Array.isArray(targets) ? targets : (targets.targets || []);
                const hostiles = targetList.filter(t => t.alliance === 'hostile').length;
                const friendlies = targetList.filter(t => t.alliance === 'friendly').length;
                const unknowns = targetList.filter(t => t.alliance === 'unknown' || !t.alliance).length;

                html += `<div class="panel-section-label">TARGETS</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TOTAL</span>
                    <span class="panel-stat-value" style="color:var(--cyan)">${targetList.length}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">FRIENDLY</span>
                    <span class="panel-stat-value" style="color:var(--green)">${friendlies}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">HOSTILE</span>
                    <span class="panel-stat-value" style="color:var(--magenta)">${hostiles}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">UNKNOWN</span>
                    <span class="panel-stat-value" style="color:var(--amber)">${unknowns}</span>
                </div>`;
            }

            // --- Dossiers ---
            const dossiers = results.dossiers;
            if (dossiers) {
                const dossierList = Array.isArray(dossiers) ? dossiers : (dossiers.dossiers || []);
                html += `<div class="panel-section-label">DOSSIERS</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TOTAL</span>
                    <span class="panel-stat-value" style="color:var(--cyan)">${dossierList.length}</span>
                </div>`;
            }

            // --- Notifications ---
            const notifications = results.notifications;
            if (notifications) {
                const notifList = Array.isArray(notifications) ? notifications
                    : (notifications.notifications || []);
                const unread = notifList.filter(n => !n.read).length;
                html += `<div class="panel-section-label">NOTIFICATIONS</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TOTAL</span>
                    <span class="panel-stat-value">${notifList.length}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">UNREAD</span>
                    <span class="panel-stat-value" style="color:${unread > 0 ? 'var(--amber)' : 'var(--green)'}">${unread}</span>
                </div>`;
            }

            // --- Amy ---
            const amy = results.amy;
            if (amy) {
                const amyStatus = amy.status || amy.state || 'unknown';
                const amyColor = amyStatus === 'active' || amyStatus === 'thinking'
                    ? 'var(--cyan)' : 'var(--text-ghost)';
                html += `<div class="panel-section-label">AMY (AI COMMANDER)</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">STATUS</span>
                    <span class="panel-stat-value" style="color:${amyColor}">${_esc(amyStatus.toUpperCase())}</span>
                </div>`;
                if (amy.mood) {
                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">MOOD</span>
                        <span class="panel-stat-value">${_esc(amy.mood)}</span>
                    </div>`;
                }
            }

            // --- Demo mode ---
            const demo = results.demo;
            if (demo) {
                const demoActive = demo.running || demo.active || false;
                const demoColor = demoActive ? 'var(--green)' : 'var(--text-ghost)';
                html += `<div class="panel-section-label">DEMO MODE</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">STATUS</span>
                    <span class="panel-stat-value" style="color:${demoColor}">${demoActive ? 'ACTIVE' : 'OFF'}</span>
                </div>`;
            }

            // --- Test Results ---
            const testing = results.testing;
            if (testing) {
                const passed = testing.passed || testing.tests_passed || 0;
                const failed = testing.failed || testing.tests_failed || 0;
                const total = testing.total || testing.tests_total || (passed + failed);
                const testColor = failed > 0 ? 'var(--magenta)' : 'var(--green)';
                html += `<div class="panel-section-label">TEST RESULTS</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">PASSED</span>
                    <span class="panel-stat-value" style="color:var(--green)">${passed}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">FAILED</span>
                    <span class="panel-stat-value" style="color:${testColor}">${failed}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TOTAL</span>
                    <span class="panel-stat-value">${total}</span>
                </div>`;
            }

            contentEl.innerHTML = html || '<div class="panel-empty">No health data available</div>';

            // Update timestamp
            if (timestampEl) {
                const now = new Date();
                timestampEl.textContent = `Updated ${now.toLocaleTimeString()}`;
            }
        }

        bodyEl.querySelector('[data-action="refresh-health"]')?.addEventListener('click', fetchHealth);

        // Service start actions (delegated)
        bodyEl.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-action]');
            if (!btn) return;
            const action = btn.dataset.action;

            if (action === 'start-mqtt') {
                btn.disabled = true;
                btn.textContent = 'STARTING...';
                try {
                    const resp = await fetch('/api/deployment/services/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ service: 'mqtt_broker' }),
                    });
                    const data = await resp.json();
                    btn.textContent = data.ok ? 'STARTED' : 'FAILED';
                    setTimeout(fetchHealth, 1500);
                } catch (_) {
                    btn.textContent = 'ERROR';
                }
            }

            if (action === 'start-mesh-bridge') {
                btn.disabled = true;
                btn.textContent = 'STARTING...';
                try {
                    const resp = await fetch('/api/deployment/services/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ service: 'meshtastic_bridge' }),
                    });
                    const data = await resp.json();
                    btn.textContent = data.ok ? `STARTED (PID ${data.pid || '?'})` : 'FAILED';
                    setTimeout(fetchHealth, 1500);
                } catch (_) {
                    btn.textContent = 'ERROR';
                }
            }
        });

        // Initial fetch
        fetchHealth();

        // Auto-refresh every 30s
        const interval = setInterval(fetchHealth, 30000);
        panel._unsubs.push(() => clearInterval(interval));
    },
};
