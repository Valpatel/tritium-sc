// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Deployment Status Panel
// Shows all Tritium services (SC server, MQTT broker, Meshtastic bridge,
// Ollama, edge fleet) with start/stop buttons and live status updates.

import { _esc } from '/lib/utils.js';


function _stateColor(state) {
    switch (state) {
        case 'running': return 'var(--green)';
        case 'stopped': return 'var(--magenta)';
        case 'starting': return 'var(--amber)';
        case 'error': return 'var(--magenta)';
        default: return 'var(--text-ghost)';
    }
}

function _stateIcon(state) {
    switch (state) {
        case 'running': return '&#x25CF;'; // filled circle
        case 'stopped': return '&#x25CB;'; // empty circle
        case 'starting': return '&#x25D4;'; // half circle
        case 'error': return '&#x25C6;'; // diamond
        default: return '&#x25CB;';
    }
}

function _formatUptime(seconds) {
    if (!seconds || seconds <= 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}


export const DeploymentPanelDef = {
    id: 'deployment',
    title: 'DEPLOYMENT STATUS',
    defaultPosition: { x: 10, y: 50 },
    defaultSize: { w: 380, h: 480 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'deployment-panel-inner';
        el.innerHTML = `
            <div class="sys-health-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-deploy">REFRESH</button>
                <span class="mono" data-bind="timestamp" style="font-size:0.4rem;color:var(--text-ghost);margin-left:auto"></span>
            </div>
            <div data-bind="content">
                <div class="panel-empty">Loading deployment status...</div>
            </div>
            <div data-bind="requirements" style="display:none"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="content"]');
        const timestampEl = bodyEl.querySelector('[data-bind="timestamp"]');
        const requirementsEl = bodyEl.querySelector('[data-bind="requirements"]');
        let _actionInProgress = false;

        async function doAction(action, service) {
            if (_actionInProgress) return;
            _actionInProgress = true;
            try {
                const resp = await fetch(`/api/deployment/services/${action}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ service }),
                });
                const data = await resp.json();
                if (!resp.ok) {
                    console.error(`[DEPLOY] ${action} ${service} failed:`, data);
                }
            } catch (err) {
                console.error(`[DEPLOY] ${action} ${service} error:`, err);
            } finally {
                _actionInProgress = false;
                // Refresh after action
                setTimeout(fetchStatus, 500);
            }
        }

        async function fetchStatus() {
            if (!contentEl) return;

            try {
                const [servicesResp, reqResp] = await Promise.allSettled([
                    fetch('/api/deployment/services'),
                    fetch('/api/deployment/requirements'),
                ]);

                let services = [];
                let svcData = {};
                if (servicesResp.status === 'fulfilled' && servicesResp.value.ok) {
                    svcData = await servicesResp.value.json();
                    services = svcData.services || [];
                }

                let requirements = null;
                if (reqResp.status === 'fulfilled' && reqResp.value.ok) {
                    requirements = await reqResp.value.json();
                }

                // Render services
                let html = '';

                // Summary bar
                const running = svcData.running || 0;
                const total = svcData.total || 0;
                const healthColor = svcData.healthy ? 'var(--green)' : 'var(--amber)';
                html += `<div class="panel-section-label" style="display:flex;align-items:center;gap:8px">
                    SERVICES
                    <span class="mono" style="font-size:0.4rem;color:${healthColor}">${running}/${total} RUNNING</span>
                </div>`;

                for (const svc of services) {
                    const state = svc.state || 'unknown';
                    const color = _stateColor(state);
                    const icon = _stateIcon(state);
                    const name = _esc(svc.display_name || svc.name || '?');
                    const uptime = _formatUptime(svc.uptime_s);
                    const pid = svc.pid ? `PID ${svc.pid}` : '';
                    const port = svc.port ? `:${svc.port}` : '';

                    html += `<div class="panel-stat-row" style="align-items:flex-start;padding:4px 8px;border-bottom:1px solid rgba(255,255,255,0.03)">
                        <div style="flex:1;min-width:0">
                            <div style="display:flex;align-items:center;gap:6px">
                                <span style="color:${color};font-size:0.5rem">${icon}</span>
                                <span class="panel-stat-label" style="flex:1">${name}</span>
                                <span class="panel-stat-value mono" style="color:${color};font-size:0.4rem">${_esc(state.toUpperCase())}</span>
                            </div>
                            <div style="display:flex;gap:12px;font-size:0.35rem;color:var(--text-ghost);padding-left:18px;margin-top:2px">
                                ${uptime !== '--' ? `<span>Uptime: ${uptime}</span>` : ''}
                                ${pid ? `<span>${pid}</span>` : ''}
                                ${port ? `<span>Port${port}</span>` : ''}
                            </div>
                            ${svc.error_message ? `<div style="font-size:0.35rem;color:var(--amber);padding-left:18px;margin-top:2px">${_esc(svc.error_message)}</div>` : ''}
                        </div>
                        <div style="display:flex;gap:4px;margin-left:8px;flex-shrink:0">
                            ${svc.can_start ? `<button class="panel-action-btn" data-svc-start="${_esc(svc.name)}" style="font-size:0.35rem;padding:2px 6px">START</button>` : ''}
                            ${svc.can_stop ? `<button class="panel-action-btn" data-svc-stop="${_esc(svc.name)}" style="font-size:0.35rem;padding:2px 6px;border-color:var(--magenta);color:var(--magenta)">STOP</button>` : ''}
                        </div>
                    </div>`;
                }

                // Requirements section
                if (requirements) {
                    html += `<div class="panel-section-label" style="margin-top:8px">SYSTEM</div>`;

                    const pyOk = requirements.python?.ok;
                    const pyColor = pyOk ? 'var(--green)' : 'var(--magenta)';
                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">PYTHON</span>
                        <span class="panel-stat-value mono" style="color:${pyColor};font-size:0.35rem">${_esc((requirements.python?.current || '?').split(' ')[0])}</span>
                    </div>`;

                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">HOST</span>
                        <span class="panel-stat-value mono" style="font-size:0.35rem">${_esc(requirements.hostname || '?')}</span>
                    </div>`;

                    // System packages
                    const pkgs = requirements.system_packages || {};
                    const pkgKeys = Object.keys(pkgs);
                    if (pkgKeys.length > 0) {
                        html += `<div class="panel-stat-row" style="flex-wrap:wrap;gap:4px">
                            <span class="panel-stat-label" style="width:100%">PACKAGES</span>`;
                        for (const pkg of pkgKeys) {
                            const installed = pkgs[pkg];
                            const c = installed ? 'var(--green)' : 'var(--text-ghost)';
                            html += `<span class="mono" style="font-size:0.35rem;color:${c};padding:1px 4px;border:1px solid ${c}33;border-radius:2px">${_esc(pkg)}</span>`;
                        }
                        html += `</div>`;
                    }
                }

                contentEl.innerHTML = html || '<div class="panel-empty">No deployment data</div>';

                // Bind start/stop buttons
                contentEl.querySelectorAll('[data-svc-start]').forEach(btn => {
                    btn.addEventListener('click', () => doAction('start', btn.dataset.svcStart));
                });
                contentEl.querySelectorAll('[data-svc-stop]').forEach(btn => {
                    btn.addEventListener('click', () => doAction('stop', btn.dataset.svcStop));
                });

            } catch (err) {
                contentEl.innerHTML = `<div class="panel-empty">Error: ${_esc(err.message)}</div>`;
            }

            if (timestampEl) {
                timestampEl.textContent = `Updated ${new Date().toLocaleTimeString()}`;
            }
        }

        bodyEl.querySelector('[data-action="refresh-deploy"]')?.addEventListener('click', fetchStatus);

        // Initial fetch
        fetchStatus();

        // Auto-refresh every 15s
        const interval = setInterval(fetchStatus, 15000);
        panel._unsubs.push(() => clearInterval(interval));
    },
};
