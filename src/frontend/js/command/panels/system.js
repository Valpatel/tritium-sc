// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// System / Infrastructure Panel
// NVR discovery, camera CRUD, telemetry health, fleet summary.
// Uses /api/discovery/*, /api/cameras/*, /api/telemetry/* endpoints.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


export const SystemPanelDef = {
    id: 'system',
    title: 'SYSTEM',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 320, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'system-panel-inner';
        el.innerHTML = `
            <div class="sys-tabs" role="tablist">
                <button class="sys-tab active" data-tab="cameras" role="tab">CAMERAS</button>
                <button class="sys-tab" data-tab="discovery" role="tab">DISCOVERY</button>
                <button class="sys-tab" data-tab="telemetry" role="tab">TELEMETRY</button>
                <button class="sys-tab" data-tab="perf" role="tab">PERF</button>
                <button class="sys-tab" data-tab="ai" role="tab">AI</button>
                <button class="sys-tab" data-tab="readiness" role="tab">READY</button>
                <button class="sys-tab" data-tab="ratelimits" role="tab">RATES</button>
                <button class="sys-tab" data-tab="opsummary" role="tab">OPS</button>
            </div>
            <div class="sys-tab-content">
                <div class="sys-tab-pane" data-pane="cameras" style="display:block">
                    <div class="sys-cam-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-cameras">REFRESH</button>
                    </div>
                    <ul class="panel-list sys-cam-list" data-bind="camera-list" role="listbox" aria-label="Registered cameras">
                        <li class="panel-empty">Loading cameras...</li>
                    </ul>
                </div>
                <div class="sys-tab-pane" data-pane="discovery" style="display:none">
                    <div class="sys-disc-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="scan-nvr">SCAN NVR</button>
                        <button class="panel-action-btn" data-action="auto-register">AUTO-REGISTER</button>
                    </div>
                    <div class="sys-nvr-status" data-bind="nvr-status"></div>
                    <ul class="panel-list sys-disc-list" data-bind="discovery-list" role="listbox" aria-label="Discovered cameras">
                        <li class="panel-empty">Click SCAN to discover cameras</li>
                    </ul>
                </div>
                <div class="sys-tab-pane" data-pane="telemetry" style="display:none">
                    <div class="sys-telem-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-telemetry">REFRESH</button>
                    </div>
                    <div class="sys-telem-content" data-bind="telemetry-content">
                        <div class="panel-empty">Loading...</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="perf" style="display:none">
                    <canvas class="sys-perf-sparkline" data-bind="fps-sparkline" width="280" height="40"></canvas>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">FPS</span>
                        <span class="panel-stat-value mono" data-bind="perf-fps" style="color:var(--cyan)">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">UNITS</span>
                        <span class="panel-stat-value mono" data-bind="perf-units">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">PANELS</span>
                        <span class="panel-stat-value mono" data-bind="perf-panels">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">WS LATENCY</span>
                        <span class="panel-stat-value mono" data-bind="perf-ws-latency">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">HEAP (est.)</span>
                        <span class="panel-stat-value mono" data-bind="perf-memory">--</span>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="ai" style="display:none">
                    <div class="sys-ai-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-ai">REFRESH</button>
                    </div>
                    <div class="sys-ai-content" data-bind="ai-content">
                        <div class="panel-empty">Loading AI status...</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="readiness" style="display:none">
                    <div class="sys-readiness-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-readiness">REFRESH</button>
                    </div>
                    <div class="sys-readiness-content" data-bind="readiness-content">
                        <div class="panel-empty">Loading readiness...</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="ratelimits" style="display:none">
                    <div class="sys-ratelimits-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-ratelimits">REFRESH</button>
                    </div>
                    <div class="sys-ratelimits-content" data-bind="ratelimits-content">
                        <div class="panel-empty">Loading rate limits...</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="opsummary" style="display:none">
                    <div class="sys-opsummary-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-opsummary">REFRESH</button>
                    </div>
                    <div class="sys-opsummary-content" data-bind="opsummary-content">
                        <div class="panel-empty">Loading ops summary...</div>
                    </div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const tabs = bodyEl.querySelectorAll('.sys-tab');
        const panes = bodyEl.querySelectorAll('.sys-tab-pane');
        const cameraList = bodyEl.querySelector('[data-bind="camera-list"]');
        const discoveryList = bodyEl.querySelector('[data-bind="discovery-list"]');
        const nvrStatus = bodyEl.querySelector('[data-bind="nvr-status"]');
        const telemContent = bodyEl.querySelector('[data-bind="telemetry-content"]');

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const tabName = tab.dataset.tab;
                panes.forEach(p => {
                    p.style.display = p.dataset.pane === tabName ? 'block' : 'none';
                });
            });
        });

        // --- Cameras tab ---
        function renderCameras(cameras) {
            if (!cameraList) return;
            if (!cameras || cameras.length === 0) {
                cameraList.innerHTML = '<li class="panel-empty">No cameras registered</li>';
                return;
            }

            cameraList.innerHTML = cameras.map(cam => {
                const dotClass = cam.enabled ? 'panel-dot-green' : 'panel-dot-neutral';
                return `<li class="panel-list-item sys-cam-item" data-cam-id="${cam.id}" role="option">
                    <span class="panel-dot ${dotClass}"></span>
                    <div class="sys-cam-info">
                        <span class="sys-cam-name">${_esc(cam.name)}</span>
                        <span class="sys-cam-meta mono" style="font-size:0.45rem;color:var(--text-ghost)">CH ${cam.channel} | ${cam.enabled ? 'ONLINE' : 'OFFLINE'}</span>
                    </div>
                    <button class="panel-btn sys-cam-delete" data-action="delete-cam" data-cam-id="${cam.id}" title="Delete">&times;</button>
                </li>`;
            }).join('');

            cameraList.querySelectorAll('[data-action="delete-cam"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    try {
                        await fetch(`/api/cameras/${btn.dataset.camId}`, { method: 'DELETE' });
                        fetchCameras();
                        EventBus.emit('toast:show', { message: 'Camera removed', type: 'info' });
                    } catch (_) {}
                });
            });
        }

        async function fetchCameras() {
            try {
                const resp = await fetch('/api/cameras');
                if (!resp.ok) { renderCameras([]); return; }
                const data = await resp.json();
                renderCameras(Array.isArray(data) ? data : []);
            } catch (_) {
                renderCameras([]);
            }
        }

        // --- Discovery tab ---
        async function fetchNvrStatus() {
            if (!nvrStatus) return;
            try {
                const resp = await fetch('/api/discovery/status');
                if (!resp.ok) {
                    nvrStatus.innerHTML = '<div class="panel-stat-row"><span class="panel-stat-label">NVR</span><span class="panel-stat-value" style="color:var(--text-ghost)">Unavailable</span></div>';
                    return;
                }
                const data = await resp.json();
                const statusColor = data.status === 'connected' ? 'var(--green)' : data.status === 'not_configured' ? 'var(--text-ghost)' : 'var(--magenta)';
                nvrStatus.innerHTML = `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">STATUS</span>
                        <span class="panel-stat-value" style="color:${statusColor}">${_esc(data.status?.toUpperCase())}</span>
                    </div>
                    ${data.host ? `<div class="panel-stat-row"><span class="panel-stat-label">HOST</span><span class="panel-stat-value">${_esc(data.host)}</span></div>` : ''}
                    ${data.online !== undefined ? `<div class="panel-stat-row"><span class="panel-stat-label">ONLINE</span><span class="panel-stat-value">${data.online}/${data.total_channels}</span></div>` : ''}
                `;
            } catch (_) {
                if (nvrStatus) nvrStatus.innerHTML = '';
            }
        }

        async function scanNvr() {
            if (discoveryList) discoveryList.innerHTML = '<li class="panel-empty">Scanning...</li>';
            try {
                const resp = await fetch('/api/discovery/scan');
                if (!resp.ok) {
                    if (discoveryList) discoveryList.innerHTML = '<li class="panel-empty">Scan failed — check NVR config</li>';
                    return;
                }
                const data = await resp.json();
                const cameras = data.cameras || [];
                if (cameras.length === 0) {
                    if (discoveryList) discoveryList.innerHTML = '<li class="panel-empty">No cameras discovered</li>';
                    return;
                }

                discoveryList.innerHTML = cameras.map(cam => {
                    const dotClass = cam.online ? (cam.registered ? 'panel-dot-green' : 'panel-dot-amber') : 'panel-dot-neutral';
                    const status = cam.registered ? 'REGISTERED' : cam.online ? 'AVAILABLE' : 'OFFLINE';
                    return `<li class="panel-list-item" role="option">
                        <span class="panel-dot ${dotClass}"></span>
                        <div class="sys-cam-info">
                            <span class="sys-cam-name">${_esc(cam.name)}</span>
                            <span class="sys-cam-meta mono" style="font-size:0.45rem;color:var(--text-ghost)">CH ${cam.channel} | ${status}</span>
                        </div>
                    </li>`;
                }).join('');

                EventBus.emit('toast:show', { message: `Discovered ${cameras.length} cameras`, type: 'info' });
            } catch (_) {
                if (discoveryList) discoveryList.innerHTML = '<li class="panel-empty">Scan error</li>';
            }
        }

        async function autoRegister() {
            try {
                const resp = await fetch('/api/discovery/register', { method: 'POST' });
                if (!resp.ok) {
                    EventBus.emit('toast:show', { message: 'Auto-register failed', type: 'alert' });
                    return;
                }
                const data = await resp.json();
                EventBus.emit('toast:show', {
                    message: `Registered: ${data.added} new, ${data.updated} updated`,
                    type: 'info',
                });
                fetchCameras();
                fetchNvrStatus();
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Auto-register error', type: 'alert' });
            }
        }

        // --- Telemetry tab ---
        async function fetchTelemetry() {
            if (!telemContent) return;
            telemContent.innerHTML = '<div class="panel-empty">Loading...</div>';

            try {
                // Fetch health, summary, and system metrics in parallel
                const [healthResp, summaryResp, systemResp, detectionsResp] = await Promise.all([
                    fetch('/api/telemetry/health'),
                    fetch('/api/telemetry/summary'),
                    fetch('/api/telemetry/system'),
                    fetch('/api/telemetry/detections'),
                ]);

                let html = '';

                // System metrics (CPU, memory, disk)
                if (systemResp.ok) {
                    const sys = await systemResp.json();
                    const cpuPct = sys.cpu_percent || sys.cpu || 0;
                    const memPct = sys.memory_percent || sys.mem || 0;
                    const diskPct = sys.disk_percent || sys.disk || 0;
                    const cpuColor = cpuPct > 80 ? 'var(--magenta)' : cpuPct > 60 ? 'var(--amber)' : 'var(--green)';
                    const memColor = memPct > 80 ? 'var(--magenta)' : memPct > 60 ? 'var(--amber)' : 'var(--green)';
                    const diskColor = diskPct > 90 ? 'var(--magenta)' : diskPct > 75 ? 'var(--amber)' : 'var(--green)';
                    html += `
                        <div class="panel-section-label">SYSTEM</div>
                        <div class="sys-metric-bar">
                            <span class="panel-stat-label">CPU</span>
                            <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${cpuPct}%;background:${cpuColor}"></div></div>
                            <span class="mono" style="font-size:0.5rem;min-width:32px;text-align:right;color:${cpuColor}">${cpuPct.toFixed(0)}%</span>
                        </div>
                        <div class="sys-metric-bar">
                            <span class="panel-stat-label">MEM</span>
                            <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${memPct}%;background:${memColor}"></div></div>
                            <span class="mono" style="font-size:0.5rem;min-width:32px;text-align:right;color:${memColor}">${memPct.toFixed(0)}%</span>
                        </div>
                        <div class="sys-metric-bar">
                            <span class="panel-stat-label">DISK</span>
                            <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${diskPct}%;background:${diskColor}"></div></div>
                            <span class="mono" style="font-size:0.5rem;min-width:32px;text-align:right;color:${diskColor}">${diskPct.toFixed(0)}%</span>
                        </div>
                        ${sys.uptime ? `<div class="panel-stat-row"><span class="panel-stat-label">UPTIME</span><span class="panel-stat-value mono">${_esc(sys.uptime)}</span></div>` : ''}
                        ${sys.load_avg ? `<div class="panel-stat-row"><span class="panel-stat-label">LOAD</span><span class="panel-stat-value mono">${Array.isArray(sys.load_avg) ? sys.load_avg.map(v => v.toFixed(2)).join(' ') : sys.load_avg}</span></div>` : ''}
                    `;
                }

                if (healthResp.ok) {
                    const health = await healthResp.json();
                    const statusColor = health.status === 'ready' ? 'var(--green)' : health.status === 'disabled' ? 'var(--text-ghost)' : 'var(--amber)';
                    html += `
                        <div class="panel-section-label">INFLUXDB</div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">STATUS</span>
                            <span class="panel-stat-value" style="color:${statusColor}">${_esc(health.status?.toUpperCase())}</span>
                        </div>
                        ${health.bucket ? `<div class="panel-stat-row"><span class="panel-stat-label">BUCKET</span><span class="panel-stat-value">${_esc(health.bucket)}</span></div>` : ''}
                    `;
                }

                // Detection counts
                if (detectionsResp.ok) {
                    const detections = await detectionsResp.json();
                    const cameras = detections.cameras || detections.channels || [];
                    if (cameras.length > 0) {
                        html += `<div class="panel-section-label">DETECTION RATES</div>`;
                        html += cameras.slice(0, 8).map(cam => {
                            const label = cam.name || cam.camera_id || cam.channel || '?';
                            const count = cam.count || cam.detections || 0;
                            return `<div class="panel-stat-row">
                                <span class="panel-stat-label">${_esc(label)}</span>
                                <span class="panel-stat-value">${count}/min</span>
                            </div>`;
                        }).join('');
                    }
                }

                if (summaryResp.ok) {
                    const summary = await summaryResp.json();
                    html += `
                        <div class="panel-section-label">FLEET</div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">ROBOTS ONLINE</span>
                            <span class="panel-stat-value">${summary.robots_online || 0}</span>
                        </div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">DETECTIONS (1h)</span>
                            <span class="panel-stat-value">${summary.detections_last_hour || 0}</span>
                        </div>
                    `;

                    if (summary.robot_ids && summary.robot_ids.length > 0) {
                        html += `<div class="panel-section-label">ACTIVE ROBOTS</div>`;
                        html += summary.robot_ids.map(id =>
                            `<div class="panel-stat-row"><span class="panel-stat-label">${_esc(id)}</span><span class="panel-stat-value" style="color:var(--green)">ONLINE</span></div>`
                        ).join('');
                    }
                }

                telemContent.innerHTML = html || '<div class="panel-empty">Telemetry unavailable</div>';
            } catch (_) {
                telemContent.innerHTML = '<div class="panel-empty">Telemetry unavailable</div>';
            }
        }

        // --- AI tab ---
        const aiContent = bodyEl.querySelector('[data-bind="ai-content"]');

        async function fetchAiStatus() {
            if (!aiContent) return;
            aiContent.innerHTML = '<div class="panel-empty">Loading...</div>';
            try {
                const resp = await fetch('/api/ai/status');
                if (!resp.ok) {
                    aiContent.innerHTML = '<div class="panel-empty">AI status unavailable</div>';
                    return;
                }
                const data = await resp.json();
                let html = '';

                // YOLO model status
                const yoloColor = data.yolo_available || data.yolo_loaded ? 'var(--green)' : 'var(--text-ghost)';
                const yoloStatus = data.yolo_available || data.yolo_loaded ? 'LOADED' : 'OFFLINE';
                html += `<div class="panel-section-label">DETECTION</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">YOLO</span>
                        <span class="panel-stat-value" style="color:${yoloColor}">${_esc(yoloStatus)}</span>
                    </div>`;
                if (data.yolo_model || data.model) {
                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">MODEL</span>
                        <span class="panel-stat-value mono" style="font-size:0.45rem">${_esc(data.yolo_model || data.model)}</span>
                    </div>`;
                }

                // GPU status
                const gpuColor = data.gpu_available || data.cuda ? 'var(--green)' : 'var(--amber)';
                const gpuStatus = data.gpu_available || data.cuda ? 'CUDA' : 'CPU';
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">COMPUTE</span>
                    <span class="panel-stat-value" style="color:${gpuColor}">${gpuStatus}</span>
                </div>`;
                if (data.gpu_name || data.device) {
                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">DEVICE</span>
                        <span class="panel-stat-value mono" style="font-size:0.45rem">${_esc(data.gpu_name || data.device)}</span>
                    </div>`;
                }

                // Tracker
                const trackerColor = data.tracker_available || data.tracker ? 'var(--green)' : 'var(--text-ghost)';
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TRACKER</span>
                    <span class="panel-stat-value" style="color:${trackerColor}">${data.tracker_available || data.tracker ? 'ByteTrack' : 'OFF'}</span>
                </div>`;

                // Ollama (LLM)
                html += `<div class="panel-section-label">LLM / VISION</div>`;
                const ollamaColor = data.ollama_available || data.ollama ? 'var(--green)' : 'var(--text-ghost)';
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">OLLAMA</span>
                    <span class="panel-stat-value" style="color:${ollamaColor}">${data.ollama_available || data.ollama ? 'ONLINE' : 'OFFLINE'}</span>
                </div>`;
                if (data.ollama_models || data.models) {
                    const models = data.ollama_models || data.models || [];
                    if (Array.isArray(models) && models.length > 0) {
                        html += models.slice(0, 5).map(m => {
                            const name = typeof m === 'string' ? m : (m.name || m.model || '?');
                            return `<div class="panel-stat-row">
                                <span class="panel-stat-label" style="padding-left:8px">${_esc(name)}</span>
                                <span class="panel-stat-value" style="color:var(--cyan)">READY</span>
                            </div>`;
                        }).join('');
                    }
                }

                // Whisper (STT)
                const sttColor = data.whisper_available || data.stt ? 'var(--green)' : 'var(--text-ghost)';
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">WHISPER</span>
                    <span class="panel-stat-value" style="color:${sttColor}">${data.whisper_available || data.stt ? 'ONLINE' : 'OFFLINE'}</span>
                </div>`;

                // TTS
                const ttsColor = data.tts_available || data.tts ? 'var(--green)' : 'var(--text-ghost)';
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">TTS (Piper)</span>
                    <span class="panel-stat-value" style="color:${ttsColor}">${data.tts_available || data.tts ? 'ONLINE' : 'OFFLINE'}</span>
                </div>`;

                aiContent.innerHTML = html;
            } catch (_) {
                aiContent.innerHTML = '<div class="panel-empty">AI status unavailable</div>';
            }
        }

        // --- Readiness tab ---
        const readinessContent = bodyEl.querySelector('[data-bind="readiness-content"]');

        async function fetchReadiness() {
            if (!readinessContent) return;
            readinessContent.innerHTML = '<div class="panel-empty">Loading...</div>';
            try {
                const resp = await fetch('/api/system/readiness');
                if (!resp.ok) {
                    readinessContent.innerHTML = '<div class="panel-empty">Readiness unavailable</div>';
                    return;
                }
                const data = await resp.json();
                let html = '';

                // Overall status banner
                const overallColor = data.overall === 'ready' ? 'var(--green)' : data.overall === 'partially_ready' ? 'var(--amber)' : 'var(--magenta)';
                const overallLabel = (data.overall || 'unknown').toUpperCase().replace('_', ' ');
                html += `<div class="panel-stat-row" style="margin-bottom:8px">
                    <span class="panel-stat-label">STATUS</span>
                    <span class="panel-stat-value" style="color:${overallColor};font-weight:bold">${_esc(overallLabel)} (${_esc(data.score || '')})</span>
                </div>`;

                // Per-item checklist
                const items = data.items || [];
                for (const item of items) {
                    const color = item.status === 'green' ? 'var(--green)' : item.status === 'yellow' ? 'var(--amber)' : 'var(--magenta)';
                    const dot = item.status === 'green' ? 'panel-dot-green' : item.status === 'yellow' ? 'panel-dot-amber' : 'panel-dot-red';
                    html += `<div class="panel-stat-row">
                        <span class="panel-dot ${dot}" style="margin-right:6px"></span>
                        <span class="panel-stat-label" style="flex:1">${_esc((item.name || '').toUpperCase().replace(/_/g, ' '))}</span>
                    </div>`;
                    if (item.detail) {
                        html += `<div style="padding-left:18px;font-size:0.45rem;color:var(--text-ghost);margin-bottom:4px">${_esc(item.detail)}</div>`;
                    }
                    if (item.hint) {
                        html += `<div style="padding-left:18px;font-size:0.4rem;color:var(--cyan);margin-bottom:6px">TIP: ${_esc(item.hint)}</div>`;
                    }
                }

                readinessContent.innerHTML = html || '<div class="panel-empty">No readiness data</div>';
            } catch (_) {
                readinessContent.innerHTML = '<div class="panel-empty">Readiness unavailable</div>';
            }
        }

        // --- Rate Limits tab ---
        const ratelimitsContent = bodyEl.querySelector('[data-bind="ratelimits-content"]');

        async function fetchRateLimits() {
            if (!ratelimitsContent) return;
            ratelimitsContent.innerHTML = '<div class="panel-empty">Loading...</div>';
            try {
                const [dashResp, statusResp] = await Promise.all([
                    fetch('/api/rate-limits/dashboard'),
                    fetch('/api/rate-limits/status'),
                ]);

                let html = '';

                // Status section
                if (statusResp.ok) {
                    const status = await statusResp.json();
                    const enabledColor = status.enabled ? 'var(--green)' : 'var(--text-ghost)';
                    html += `<div class="panel-section-label">CONFIGURATION</div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">RATE LIMITING</span>
                            <span class="panel-stat-value" style="color:${enabledColor}">${status.enabled ? 'ENABLED' : 'DISABLED'}</span>
                        </div>`;
                    if (status.enabled) {
                        html += `<div class="panel-stat-row">
                            <span class="panel-stat-label">MAX REQ/WINDOW</span>
                            <span class="panel-stat-value mono">${status.max_requests_per_window || 0}</span>
                        </div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">WINDOW (s)</span>
                            <span class="panel-stat-value mono">${status.window_seconds || 0}</span>
                        </div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">ACTIVE KEYS</span>
                            <span class="panel-stat-value mono">${status.active_keys || 0}</span>
                        </div>`;
                    }
                }

                // Dashboard section — busiest endpoints
                if (dashResp.ok) {
                    const dash = await dashResp.json();
                    const endpoints = dash.endpoints || [];
                    html += `<div class="panel-section-label">TOP ENDPOINTS (${dash.window_minutes || 15}min)</div>`;
                    if (endpoints.length === 0) {
                        html += '<div class="panel-empty" style="padding:4px 0">No request data</div>';
                    } else {
                        html += `<div class="panel-stat-row" style="margin-bottom:2px">
                            <span class="panel-stat-label">TOTAL REQUESTS</span>
                            <span class="panel-stat-value mono">${dash.total_requests || 0}</span>
                        </div>`;
                        for (const ep of endpoints.slice(0, 15)) {
                            const pctColor = (ep.rate_limit_pct || 0) > 80 ? 'var(--magenta)' : (ep.rate_limit_pct || 0) > 50 ? 'var(--amber)' : 'var(--green)';
                            const errCount = (ep.errors_4xx || 0) + (ep.errors_5xx || 0);
                            const errBadge = errCount > 0 ? ` <span style="color:var(--magenta)">${errCount}err</span>` : '';
                            html += `<div class="panel-stat-row">
                                <span class="panel-stat-label mono" style="font-size:0.4rem;flex:2">${_esc(ep.method || '')} ${_esc(ep.path || '')}</span>
                                <span class="panel-stat-value mono" style="font-size:0.4rem;color:${pctColor}">${ep.request_count || 0} (${ep.avg_response_ms || 0}ms)${errBadge}</span>
                            </div>`;
                        }
                    }
                } else {
                    html += '<div class="panel-empty">Rate limit dashboard unavailable (auth required)</div>';
                }

                ratelimitsContent.innerHTML = html || '<div class="panel-empty">Rate limit data unavailable</div>';
            } catch (_) {
                ratelimitsContent.innerHTML = '<div class="panel-empty">Rate limit data unavailable</div>';
            }
        }

        // --- Ops Summary tab (Picture of the Day) ---
        const opsummaryContent = bodyEl.querySelector('[data-bind="opsummary-content"]');

        async function fetchOpsSummary() {
            if (!opsummaryContent) return;
            opsummaryContent.innerHTML = '<div class="panel-empty">Loading...</div>';
            try {
                const resp = await fetch('/api/picture-of-day');
                if (!resp.ok) {
                    opsummaryContent.innerHTML = '<div class="panel-empty">Ops summary unavailable</div>';
                    return;
                }
                const data = await resp.json();
                let html = '';

                // Threat level banner
                const threatColors = { GREEN: 'var(--green)', YELLOW: 'var(--amber)', ORANGE: '#ff8800', RED: 'var(--magenta)' };
                const tlColor = threatColors[data.threat_level] || 'var(--text-ghost)';
                html += `<div class="panel-stat-row" style="margin-bottom:8px">
                    <span class="panel-stat-label">THREAT LEVEL</span>
                    <span class="panel-stat-value" style="color:${tlColor};font-weight:bold">${_esc(data.threat_level || 'UNKNOWN')}</span>
                </div>`;

                // Date and period
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">REPORT DATE</span>
                    <span class="panel-stat-value mono">${_esc(data.report_date || '--')}</span>
                </div>`;

                // Key stats
                html += `<div class="panel-section-label">24-HOUR SUMMARY</div>`;
                const statRows = [
                    ['NEW TARGETS', data.new_targets || 0],
                    ['CORRELATIONS', data.correlations || 0],
                    ['THREATS', data.threats || 0],
                    ['ZONE EVENTS', data.zone_events || 0],
                    ['INVESTIGATIONS', data.investigations_opened || 0],
                    ['TOTAL SIGHTINGS', data.total_sightings || 0],
                    ['UPTIME', (data.uptime_percent || 0) + '%'],
                ];
                for (const [label, value] of statRows) {
                    const valColor = label === 'THREATS' && value > 0 ? 'var(--magenta)' : 'var(--cyan)';
                    html += `<div class="panel-stat-row">
                        <span class="panel-stat-label">${label}</span>
                        <span class="panel-stat-value mono" style="color:${valColor}">${value}</span>
                    </div>`;
                }

                // Sightings by source
                const bySource = data.sightings_by_source || {};
                const sourceKeys = Object.keys(bySource);
                if (sourceKeys.length > 0) {
                    html += `<div class="panel-section-label">SIGHTINGS BY SOURCE</div>`;
                    for (const src of sourceKeys) {
                        html += `<div class="panel-stat-row">
                            <span class="panel-stat-label">${_esc(src.toUpperCase())}</span>
                            <span class="panel-stat-value mono">${bySource[src]}</span>
                        </div>`;
                    }
                }

                // Top devices
                const topDevices = data.top_devices || [];
                if (topDevices.length > 0) {
                    html += `<div class="panel-section-label">TOP DEVICES</div>`;
                    for (const dev of topDevices.slice(0, 5)) {
                        html += `<div class="panel-stat-row">
                            <span class="panel-stat-label mono" style="font-size:0.4rem">${_esc(dev.device_id || '?')}</span>
                            <span class="panel-stat-value mono" style="font-size:0.4rem">${dev.sighting_count || 0} sightings</span>
                        </div>`;
                    }
                }

                opsummaryContent.innerHTML = html || '<div class="panel-empty">No ops data</div>';
            } catch (_) {
                opsummaryContent.innerHTML = '<div class="panel-empty">Ops summary unavailable</div>';
            }
        }

        // Button handlers
        bodyEl.querySelector('[data-action="refresh-cameras"]')?.addEventListener('click', fetchCameras);
        bodyEl.querySelector('[data-action="scan-nvr"]')?.addEventListener('click', scanNvr);
        bodyEl.querySelector('[data-action="auto-register"]')?.addEventListener('click', autoRegister);
        bodyEl.querySelector('[data-action="refresh-telemetry"]')?.addEventListener('click', fetchTelemetry);
        bodyEl.querySelector('[data-action="refresh-ai"]')?.addEventListener('click', fetchAiStatus);
        bodyEl.querySelector('[data-action="refresh-readiness"]')?.addEventListener('click', fetchReadiness);
        bodyEl.querySelector('[data-action="refresh-ratelimits"]')?.addEventListener('click', fetchRateLimits);
        bodyEl.querySelector('[data-action="refresh-opsummary"]')?.addEventListener('click', fetchOpsSummary);

        // --- Performance tab ---
        const fpsSparkline = bodyEl.querySelector('[data-bind="fps-sparkline"]');
        const perfFps = bodyEl.querySelector('[data-bind="perf-fps"]');
        const perfUnits = bodyEl.querySelector('[data-bind="perf-units"]');
        const perfPanels = bodyEl.querySelector('[data-bind="perf-panels"]');
        const perfWsLatency = bodyEl.querySelector('[data-bind="perf-ws-latency"]');
        const perfMemory = bodyEl.querySelector('[data-bind="perf-memory"]');
        const fpsHistory = [];
        const MAX_FPS_HISTORY = 60;

        function updatePerf() {
            // FPS from status bar
            const fpsEl = document.getElementById('status-fps');
            const fpsText = fpsEl?.textContent || '0';
            const fps = parseInt(fpsText, 10) || 0;
            fpsHistory.push(fps);
            if (fpsHistory.length > MAX_FPS_HISTORY) fpsHistory.shift();

            if (perfFps) perfFps.textContent = fps;

            // Unit count from store
            const unitCount = window.TritiumStore?.units?.size || 0;
            if (perfUnits) perfUnits.textContent = unitCount;

            // Active panels
            const openPanels = document.querySelectorAll('.panel:not([style*="display: none"])').length;
            if (perfPanels) perfPanels.textContent = openPanels;

            // WebSocket latency (estimate from store)
            const wsLat = window.TritiumStore?.get?.('ws.latency');
            if (perfWsLatency) perfWsLatency.textContent = wsLat ? `${wsLat}ms` : 'N/A';

            // Memory
            if (perfMemory && performance.memory) {
                const mb = (performance.memory.usedJSHeapSize / (1024 * 1024)).toFixed(1);
                perfMemory.textContent = `${mb} MB`;
            } else if (perfMemory) {
                perfMemory.textContent = 'N/A';
            }

            // Draw FPS sparkline
            if (fpsSparkline) {
                const ctx = fpsSparkline.getContext('2d');
                const w = fpsSparkline.width;
                const h = fpsSparkline.height;
                ctx.clearRect(0, 0, w, h);

                if (fpsHistory.length >= 2) {
                    const maxFps = Math.max(60, ...fpsHistory);
                    const step = w / (MAX_FPS_HISTORY - 1);
                    ctx.strokeStyle = '#00f0ff';
                    ctx.lineWidth = 1.5;
                    ctx.beginPath();
                    for (let i = 0; i < fpsHistory.length; i++) {
                        const x = i * step;
                        const y = h - (fpsHistory[i] / maxFps) * (h - 4) - 2;
                        if (i === 0) ctx.moveTo(x, y);
                        else ctx.lineTo(x, y);
                    }
                    ctx.stroke();

                    // 60fps reference line
                    ctx.strokeStyle = 'rgba(5, 255, 161, 0.2)';
                    ctx.lineWidth = 0.5;
                    ctx.setLineDash([4, 4]);
                    const refY = h - (60 / maxFps) * (h - 4) - 2;
                    ctx.beginPath();
                    ctx.moveTo(0, refY);
                    ctx.lineTo(w, refY);
                    ctx.stroke();
                    ctx.setLineDash([]);
                }
            }
        }

        const perfInterval = setInterval(updatePerf, 2000);
        panel._unsubs.push(() => clearInterval(perfInterval));
        updatePerf(); // Initial

        // Initial data
        fetchCameras();
        fetchNvrStatus();
        fetchTelemetry();
        fetchAiStatus();
        fetchReadiness();
        fetchRateLimits();
        fetchOpsSummary();

        // Auto-refresh cameras every 30s
        const refreshInterval = setInterval(fetchCameras, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
