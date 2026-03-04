// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// System / Infrastructure Panel
// NVR discovery, camera CRUD, telemetry health, fleet summary.
// Uses /api/discovery/*, /api/cameras/*, /api/telemetry/* endpoints.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

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

        // Button handlers
        bodyEl.querySelector('[data-action="refresh-cameras"]')?.addEventListener('click', fetchCameras);
        bodyEl.querySelector('[data-action="scan-nvr"]')?.addEventListener('click', scanNvr);
        bodyEl.querySelector('[data-action="auto-register"]')?.addEventListener('click', autoRegister);
        bodyEl.querySelector('[data-action="refresh-telemetry"]')?.addEventListener('click', fetchTelemetry);
        bodyEl.querySelector('[data-action="refresh-ai"]')?.addEventListener('click', fetchAiStatus);

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

        // Auto-refresh cameras every 30s
        const refreshInterval = setInterval(fetchCameras, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
