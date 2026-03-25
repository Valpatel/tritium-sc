// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Mesh Radio Panel — Tabbed Meshtastic client with real hardware support
// Tabs: Nodes | Chat | Radio | Scan
// Subscribes to: mesh:text, mesh:position, mesh:telemetry, mesh:connected, mesh:disconnected
// Enhanced for real Meshtastic hardware: 250+ nodes, signal quality, battery, environment

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


const MESH_MSG_LIMIT = 228;

function _formatAge(lastHeard) {
    if (!lastHeard) return '--';
    const now = Math.floor(Date.now() / 1000);
    const delta = now - lastHeard;
    if (delta < 0) return 'now';
    if (delta < 60) return `${delta}s`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h`;
    return `${Math.floor(delta / 86400)}d`;
}

function _signalClass(snr) {
    if (snr === null || snr === undefined) return 'neutral';
    if (snr >= 10) return 'green';
    if (snr >= 0) return 'cyan';
    if (snr >= -10) return 'yellow';
    return 'magenta';
}

function _batteryClass(bat) {
    if (bat === null || bat === undefined) return 'neutral';
    if (bat >= 60) return 'green';
    if (bat >= 30) return 'yellow';
    return 'magenta';
}

export const MeshPanelDef = {
    id: 'mesh',
    title: 'MESHTASTIC',
    defaultPosition: { x: 16, y: 400 },
    defaultSize: { w: 400, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mesh-panel-inner';
        el.innerHTML = `
            <div class="mesh-tabs" data-bind="tabs">
                <button class="mesh-tab active" data-tab="nodes">Nodes</button>
                <button class="mesh-tab" data-tab="chat">Chat</button>
                <button class="mesh-tab" data-tab="radio">Radio</button>
                <button class="mesh-tab" data-tab="scan">Scan</button>
            </div>
            <div class="mesh-tab-content" data-bind="tab-content">
                <div class="mesh-tab-pane active" data-pane="nodes">
                    <div class="mesh-node-header">
                        <div class="mesh-node-stats-bar" data-bind="stats-bar">
                            <span class="mono" data-bind="total-nodes">0 total</span>
                            <span class="mono" data-bind="gps-nodes">0 GPS</span>
                            <span class="mono" data-bind="recent-nodes">0 recent</span>
                        </div>
                        <div class="mesh-node-sort">
                            <select class="panel-filter mesh-sort-select" data-bind="sort-select">
                                <option value="last_heard">Last heard</option>
                                <option value="name">Name</option>
                                <option value="snr">Signal (SNR)</option>
                                <option value="battery">Battery</option>
                            </select>
                            <input type="text" class="panel-filter mesh-node-search" data-bind="node-search"
                                   placeholder="Filter nodes..." autocomplete="off" />
                        </div>
                    </div>
                    <ul class="panel-list mesh-node-list" data-bind="node-list" role="listbox" aria-label="Mesh nodes">
                        <li class="panel-empty">No nodes discovered</li>
                    </ul>
                    <div class="mesh-node-detail" data-bind="node-detail" style="display:none"></div>
                </div>
                <div class="mesh-tab-pane" data-pane="chat" style="display:none">
                    <div class="mesh-chat-controls">
                        <select class="mesh-channel-select panel-filter" data-bind="channel-select">
                            <option value="0">ch0 (primary)</option>
                            <option value="1">ch1</option>
                            <option value="2">ch2</option>
                            <option value="3">ch3</option>
                            <option value="4">ch4</option>
                            <option value="5">ch5</option>
                            <option value="6">ch6</option>
                            <option value="7">ch7</option>
                        </select>
                        <div class="mesh-dm-indicator" data-bind="dm-indicator" style="display:none">
                            <span class="mono" style="color:var(--magenta)">DM:</span>
                            <span class="mono" data-bind="dm-target"></span>
                            <button class="mesh-dm-clear" data-action="clear-dm" title="Clear DM target">x</button>
                        </div>
                    </div>
                    <div class="mesh-chat-messages" data-bind="messages"></div>
                    <div class="mesh-chat-input-row">
                        <input type="text" class="mesh-chat-input" data-bind="input"
                               maxlength="${MESH_MSG_LIMIT}" placeholder="Message (${MESH_MSG_LIMIT} chars)"
                               autocomplete="off" />
                        <span class="mono mesh-char-counter" data-bind="char-count">${MESH_MSG_LIMIT}</span>
                        <button class="panel-action-btn panel-action-btn-primary" data-action="send">SEND</button>
                    </div>
                </div>
                <div class="mesh-tab-pane" data-pane="radio" style="display:none">
                    <div class="mesh-radio-status">
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">STATUS</span>
                            <span class="panel-stat-value" data-bind="radio-status">DISCONNECTED</span>
                        </div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">BRIDGE</span>
                            <span class="panel-stat-value" data-bind="bridge-status">--</span>
                        </div>
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">HOST</span>
                            <span class="panel-stat-value" data-bind="radio-host">--</span>
                        </div>
                    </div>
                    <div class="panel-section-label">CONNECT</div>
                    <div class="mesh-radio-connect">
                        <div class="mesh-radio-input-row">
                            <input type="text" class="mesh-radio-input" data-bind="radio-host-input"
                                   placeholder="Host (e.g. 192.168.1.50)" autocomplete="off" />
                            <input type="number" class="mesh-radio-port-input" data-bind="radio-port-input"
                                   placeholder="4403" value="4403" min="1" max="65535" />
                        </div>
                        <div class="mesh-radio-actions">
                            <button class="panel-action-btn panel-action-btn-primary" data-action="connect">CONNECT</button>
                            <button class="panel-action-btn" data-action="disconnect">DISCONNECT</button>
                        </div>
                    </div>
                    <div class="panel-section-label">CHANNELS</div>
                    <div class="mesh-radio-channels" data-bind="radio-channels">
                        <span class="panel-empty">Not connected</span>
                    </div>
                </div>
                <div class="mesh-tab-pane" data-pane="scan" style="display:none">
                    <div class="mesh-scan-actions">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="scan">SCAN FOR DEVICES</button>
                    </div>
                    <div class="mesh-scan-status mono" data-bind="scan-status"></div>
                    <div class="mesh-scan-results" data-bind="scan-results">
                        <span class="panel-empty">No scan results</span>
                    </div>
                </div>
            </div>
            <div class="mesh-status-bar" data-bind="status">
                <span class="panel-dot panel-dot-neutral" data-bind="status-dot"></span>
                <span class="mono" data-bind="status-label">DISCONNECTED</span>
                <span class="mono" style="margin-left:auto" data-bind="node-count">0 nodes</span>
                <span class="mono" style="margin-left:8px" data-bind="msg-count">0 msgs</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // --- Element references ---
        const tabsEl = bodyEl.querySelector('[data-bind="tabs"]');
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusLabel = bodyEl.querySelector('[data-bind="status-label"]');
        const nodeCountEl = bodyEl.querySelector('[data-bind="node-count"]');
        const msgCountEl = bodyEl.querySelector('[data-bind="msg-count"]');
        const nodeListEl = bodyEl.querySelector('[data-bind="node-list"]');
        const nodeDetailEl = bodyEl.querySelector('[data-bind="node-detail"]');
        const messagesEl = bodyEl.querySelector('[data-bind="messages"]');
        const inputEl = bodyEl.querySelector('[data-bind="input"]');
        const charCountEl = bodyEl.querySelector('[data-bind="char-count"]');
        const sendBtn = bodyEl.querySelector('[data-action="send"]');
        const channelSelect = bodyEl.querySelector('[data-bind="channel-select"]');
        const dmIndicator = bodyEl.querySelector('[data-bind="dm-indicator"]');
        const dmTargetEl = bodyEl.querySelector('[data-bind="dm-target"]');
        const clearDmBtn = bodyEl.querySelector('[data-action="clear-dm"]');
        const radioStatusEl = bodyEl.querySelector('[data-bind="radio-status"]');
        const bridgeStatusEl = bodyEl.querySelector('[data-bind="bridge-status"]');
        const radioHostEl = bodyEl.querySelector('[data-bind="radio-host"]');
        const radioHostInput = bodyEl.querySelector('[data-bind="radio-host-input"]');
        const radioPortInput = bodyEl.querySelector('[data-bind="radio-port-input"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');
        const radioChannelsEl = bodyEl.querySelector('[data-bind="radio-channels"]');
        const scanBtn = bodyEl.querySelector('[data-action="scan"]');
        const scanStatusEl = bodyEl.querySelector('[data-bind="scan-status"]');
        const scanResultsEl = bodyEl.querySelector('[data-bind="scan-results"]');
        const totalNodesEl = bodyEl.querySelector('[data-bind="total-nodes"]');
        const gpsNodesEl = bodyEl.querySelector('[data-bind="gps-nodes"]');
        const recentNodesEl = bodyEl.querySelector('[data-bind="recent-nodes"]');
        const sortSelect = bodyEl.querySelector('[data-bind="sort-select"]');
        const searchInput = bodyEl.querySelector('[data-bind="node-search"]');

        let nodes = {};
        let messages = [];
        let msgCount = 0;
        let selectedNodeId = null;
        let activeTab = 'nodes';
        let searchFilter = '';

        // --- Tab switching ---
        function switchTab(tabName) {
            activeTab = tabName;
            if (tabsEl) {
                const tabs = tabsEl.querySelectorAll('.mesh-tab');
                tabs.forEach(t => {
                    if (t.dataset.tab === tabName) t.classList.add('active');
                    else t.classList.remove('active');
                });
            }
            const panes = bodyEl.querySelectorAll('.mesh-tab-pane');
            panes.forEach(p => {
                const isActive = p.dataset.pane === tabName;
                if (isActive) p.classList.add('active');
                else p.classList.remove('active');
                p.style.display = isActive ? '' : 'none';
            });
        }

        if (tabsEl) {
            tabsEl.addEventListener('click', (e) => {
                const tab = e.target.closest('.mesh-tab');
                if (tab && tab.dataset.tab) {
                    switchTab(tab.dataset.tab);
                }
            });
        }

        // --- Status updates ---
        function updateStatus(data) {
            const connected = data ? (data.connected || data.bridge_online) : TritiumStore.get('mesh.connected');
            if (statusDot) {
                statusDot.className = connected
                    ? 'panel-dot panel-dot-green'
                    : 'panel-dot panel-dot-neutral';
            }
            if (statusLabel) {
                statusLabel.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
                statusLabel.style.color = connected ? 'var(--green)' : 'var(--text-dim)';
            }
            if (radioStatusEl) {
                const directConnected = data ? data.connected : false;
                radioStatusEl.textContent = directConnected ? 'CONNECTED' : 'DISCONNECTED';
                radioStatusEl.style.color = directConnected ? 'var(--green)' : 'var(--text-dim)';
            }
            if (bridgeStatusEl) {
                const bridgeOnline = data ? data.bridge_online : false;
                bridgeStatusEl.textContent = bridgeOnline ? 'ONLINE' : 'OFFLINE';
                bridgeStatusEl.style.color = bridgeOnline ? 'var(--green)' : 'var(--text-dim)';
            }
        }

        // --- Node list rendering ---
        function renderNodes() {
            const nodeArr = Object.values(nodes);
            if (nodeCountEl) nodeCountEl.textContent = `${nodeArr.length} nodes`;

            // Update stats bar
            const now = Math.floor(Date.now() / 1000);
            const withGps = nodeArr.filter(n =>
                n.lat !== undefined && n.lat !== null && n.lng !== undefined && n.lng !== null &&
                (n.lat !== 0 || n.lng !== 0)
            ).length;
            const recent = nodeArr.filter(n =>
                n.last_heard && (now - n.last_heard) < 3600
            ).length;

            if (totalNodesEl) totalNodesEl.textContent = `${nodeArr.length} total`;
            if (gpsNodesEl) gpsNodesEl.textContent = `${withGps} GPS`;
            if (recentNodesEl) recentNodesEl.textContent = `${recent} recent`;

            if (!nodeListEl) return;

            // Apply search filter
            let filtered = nodeArr;
            if (searchFilter) {
                const q = searchFilter.toLowerCase();
                filtered = nodeArr.filter(n => {
                    const name = (n.long_name || n.short_name || n.name || n.node_id || '').toLowerCase();
                    const hw = (n.hw_model || n.hardware || '').toLowerCase();
                    const nid = (n.node_id || '').toLowerCase();
                    return name.includes(q) || hw.includes(q) || nid.includes(q);
                });
            }

            // Apply sort
            const sortBy = sortSelect ? sortSelect.value : 'last_heard';
            if (sortBy === 'last_heard') {
                filtered.sort((a, b) => (b.last_heard || 0) - (a.last_heard || 0));
            } else if (sortBy === 'name') {
                filtered.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
            } else if (sortBy === 'snr') {
                filtered.sort((a, b) => (b.snr || -999) - (a.snr || -999));
            } else if (sortBy === 'battery') {
                filtered.sort((a, b) => (b.battery || 0) - (a.battery || 0));
            }

            if (filtered.length === 0) {
                nodeListEl.innerHTML = `<li class="panel-empty">${searchFilter ? 'No matching nodes' : 'No nodes discovered'}</li>`;
                return;
            }

            nodeListEl.innerHTML = filtered.map(n => {
                const nodeId = n.node_id || n.id || '';
                const name = _esc(n.short_name || n.long_name || n.name || nodeId || '???');
                const longName = _esc(n.long_name || '');
                const bat = n.battery !== undefined && n.battery !== null
                    ? `${Math.round(n.battery)}%` : '--';
                const batClass = _batteryClass(n.battery);
                const snr = n.snr !== undefined && n.snr !== null
                    ? `${Number(n.snr).toFixed(1)}` : '--';
                const snrClass = _signalClass(n.snr);
                const age = _formatAge(n.last_heard);
                const hw = _esc(n.hw_model || n.hardware || '');
                const isSelected = selectedNodeId === nodeId;
                const hopsStr = n.hops_away !== undefined && n.hops_away !== null
                    ? `${n.hops_away}hop` : '';
                const favStar = n.is_favorite ? '<span style="color:var(--yellow)" title="Favorite">*</span>' : '';
                const mqttTag = n.via_mqtt ? '<span class="mono" style="color:var(--text-dim);font-size:0.7em" title="Via MQTT">MQTT</span>' : '';

                return `<li class="panel-list-item mesh-node-item${isSelected ? ' active' : ''}" data-node-id="${_esc(nodeId)}" role="option" title="${longName} [${hw}]">
                    <span class="panel-icon-badge" style="color:var(--cyan);border-color:var(--cyan)">M</span>
                    <span class="mesh-node-name">${favStar}${name}</span>
                    <span class="mono mesh-node-stats">
                        <span title="Battery" style="color:var(--${batClass})">${bat}</span>
                        <span title="SNR" style="color:var(--${snrClass})">${snr}dB</span>
                        <span title="Last heard">${age}</span>
                        ${hopsStr ? `<span title="Hops away" style="color:var(--text-dim)">${hopsStr}</span>` : ''}
                        ${mqttTag}
                    </span>
                </li>`;
            }).join('');

            // Click handler: expand node detail + set DM target
            nodeListEl.querySelectorAll('.mesh-node-item').forEach(item => {
                item.addEventListener('click', () => {
                    const nodeId = item.dataset.nodeId;
                    if (selectedNodeId === nodeId) {
                        selectedNodeId = null;
                        if (nodeDetailEl) nodeDetailEl.style.display = 'none';
                        if (dmIndicator) dmIndicator.style.display = 'none';
                    } else {
                        selectedNodeId = nodeId;
                        showNodeDetail(nodeId);
                        if (dmIndicator) dmIndicator.style.display = '';
                        if (dmTargetEl) dmTargetEl.textContent = _esc(nodeId);
                    }
                    renderNodes();

                    const node = nodes[nodeId];
                    if (node && node.lat !== undefined && node.lat !== null && node.lng !== undefined && node.lng !== null) {
                        EventBus.emit('mesh:center-on-node', {
                            id: nodeId,
                            lat: node.lat,
                            lng: node.lng,
                        });
                    }
                });
            });
        }

        // --- Sparkline drawing utility ---
        function drawSparkline(canvas, values, color, label) {
            if (!canvas || !values || values.length < 2) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            const filtered = values.filter(v => v !== null && v !== undefined);
            if (filtered.length < 2) return;

            const min = Math.min(...filtered);
            const max = Math.max(...filtered);
            const range = max - min || 1;

            // Fill area under curve
            ctx.beginPath();
            ctx.moveTo(0, h);
            for (let i = 0; i < values.length; i++) {
                const v = values[i];
                if (v === null || v === undefined) continue;
                const x = (i / (values.length - 1)) * w;
                const y = h - ((v - min) / range) * (h - 4) - 2;
                if (i === 0 || values[i - 1] === null) ctx.moveTo(x, h);
                ctx.lineTo(x, y);
            }
            ctx.lineTo(w, h);
            ctx.closePath();
            ctx.fillStyle = color + '15';
            ctx.fill();

            // Draw line
            ctx.beginPath();
            let started = false;
            for (let i = 0; i < values.length; i++) {
                const v = values[i];
                if (v === null || v === undefined) { started = false; continue; }
                const x = (i / (values.length - 1)) * w;
                const y = h - ((v - min) / range) * (h - 4) - 2;
                if (!started) { ctx.moveTo(x, y); started = true; }
                else ctx.lineTo(x, y);
            }
            ctx.strokeStyle = color;
            ctx.lineWidth = 1.5;
            ctx.stroke();

            // Label and current value
            const lastVal = filtered[filtered.length - 1];
            ctx.fillStyle = color;
            ctx.font = '9px monospace';
            ctx.fillText(label, 2, 9);
            ctx.textAlign = 'right';
            ctx.fillText(typeof lastVal === 'number' ? lastVal.toFixed(1) : String(lastVal), w - 2, 9);
            ctx.textAlign = 'left';
        }

        // --- Node detail display ---
        function showNodeDetail(nodeId) {
            if (!nodeDetailEl) return;
            const n = nodes[nodeId];
            if (!n) {
                nodeDetailEl.style.display = 'none';
                return;
            }

            const lat = n.lat !== undefined && n.lat !== null ? n.lat.toFixed(6) : '--';
            const lng = n.lng !== undefined && n.lng !== null ? n.lng.toFixed(6) : '--';
            const altStr = n.alt !== undefined && n.alt !== null ? `${Number(n.alt).toFixed(1)}m` : '--';
            const age = _formatAge(n.last_heard);

            // Extended telemetry rows
            let telemetryRows = '';
            if (n.voltage !== undefined && n.voltage !== null) {
                telemetryRows += `<div class="panel-stat-row"><span class="panel-stat-label">VOLTAGE</span><span class="panel-stat-value">${Number(n.voltage).toFixed(2)}V</span></div>`;
            }
            if (n.channel_utilization !== undefined && n.channel_utilization !== null) {
                telemetryRows += `<div class="panel-stat-row"><span class="panel-stat-label">CH UTIL</span><span class="panel-stat-value">${Number(n.channel_utilization).toFixed(1)}%</span></div>`;
            }
            if (n.air_util_tx !== undefined && n.air_util_tx !== null) {
                telemetryRows += `<div class="panel-stat-row"><span class="panel-stat-label">AIR UTIL TX</span><span class="panel-stat-value">${Number(n.air_util_tx).toFixed(1)}%</span></div>`;
            }

            // Environment rows
            let envRows = '';
            if (n.temperature !== undefined && n.temperature !== null) {
                envRows += `<div class="panel-stat-row"><span class="panel-stat-label">TEMP</span><span class="panel-stat-value">${Number(n.temperature).toFixed(1)}C</span></div>`;
            }
            if (n.humidity !== undefined && n.humidity !== null) {
                envRows += `<div class="panel-stat-row"><span class="panel-stat-label">HUMIDITY</span><span class="panel-stat-value">${Number(n.humidity).toFixed(0)}%</span></div>`;
            }
            if (n.pressure !== undefined && n.pressure !== null) {
                envRows += `<div class="panel-stat-row"><span class="panel-stat-label">PRESSURE</span><span class="panel-stat-value">${Number(n.pressure).toFixed(1)} hPa</span></div>`;
            }

            nodeDetailEl.style.display = '';
            nodeDetailEl.innerHTML = `
                <div class="panel-section-label">NODE DETAIL</div>
                <div class="panel-stat-row"><span class="panel-stat-label">LONG NAME</span><span class="panel-stat-value">${_esc(n.long_name || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">SHORT NAME</span><span class="panel-stat-value">${_esc(n.short_name || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">NODE ID</span><span class="panel-stat-value mono">${_esc(n.node_id || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">HARDWARE</span><span class="panel-stat-value">${_esc(n.hw_model || n.hardware || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">FIRMWARE</span><span class="panel-stat-value">${_esc(n.firmware_version || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">ROLE</span><span class="panel-stat-value">${_esc(n.role || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">BATTERY</span><span class="panel-stat-value">${n.battery !== undefined && n.battery !== null ? Math.round(n.battery) + '%' : '--'}</span></div>
                ${telemetryRows}
                <div class="panel-stat-row"><span class="panel-stat-label">SNR</span><span class="panel-stat-value">${n.snr !== undefined && n.snr !== null ? Number(n.snr).toFixed(1) + 'dB' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">RSSI</span><span class="panel-stat-value">${n.rssi !== undefined && n.rssi !== null ? n.rssi + 'dBm' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">HOPS</span><span class="panel-stat-value">${n.hops_away !== undefined && n.hops_away !== null ? n.hops_away : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">LAST HEARD</span><span class="panel-stat-value">${age}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">GPS</span><span class="panel-stat-value">${lat}, ${lng}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">ALTITUDE</span><span class="panel-stat-value">${altStr}</span></div>
                ${envRows}
                ${n.via_mqtt ? '<div class="panel-stat-row"><span class="panel-stat-label">VIA</span><span class="panel-stat-value" style="color:var(--text-dim)">MQTT</span></div>' : ''}
                ${n.is_favorite ? '<div class="panel-stat-row"><span class="panel-stat-label">FAVORITE</span><span class="panel-stat-value" style="color:var(--yellow)">YES</span></div>' : ''}
                <div class="panel-section-label" style="margin-top:8px">TELEMETRY CHARTS</div>
                <div class="mesh-sparkline-section" data-bind="sparklines">
                    <canvas class="mesh-sparkline" data-metric="battery" width="280" height="36"></canvas>
                    <canvas class="mesh-sparkline" data-metric="voltage" width="280" height="36"></canvas>
                    <canvas class="mesh-sparkline" data-metric="temperature" width="280" height="36"></canvas>
                </div>
            `;

            // Fetch and render telemetry sparklines
            fetchTelemetryHistory(nodeId);
        }

        // --- Fetch telemetry history and draw sparklines ---
        function fetchTelemetryHistory(nodeId) {
            const cleanId = encodeURIComponent(nodeId);
            fetch(`/api/meshtastic/nodes/${cleanId}/telemetry-history`)
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data || !data.points || data.points.length < 2) return;
                    const points = data.points;

                    const sparkSection = nodeDetailEl?.querySelector('[data-bind="sparklines"]');
                    if (!sparkSection) return;

                    const batteryCanvas = sparkSection.querySelector('[data-metric="battery"]');
                    const voltageCanvas = sparkSection.querySelector('[data-metric="voltage"]');
                    const tempCanvas = sparkSection.querySelector('[data-metric="temperature"]');

                    drawSparkline(batteryCanvas, points.map(p => p.battery), '#05ffa1', 'BATTERY %');
                    drawSparkline(voltageCanvas, points.map(p => p.voltage), '#00f0ff', 'VOLTAGE V');
                    drawSparkline(tempCanvas, points.map(p => p.temperature), '#fcee0a', 'TEMP C');
                })
                .catch(() => {});
        }

        // --- Chat rendering ---
        function renderMessages() {
            if (msgCountEl) msgCountEl.textContent = `${msgCount} msgs`;
            if (!messagesEl) return;

            if (messages.length === 0) {
                messagesEl.innerHTML = '';
                return;
            }

            messagesEl.innerHTML = messages.slice(-50).map(m => {
                const sender = _esc(m.from_short || m.from_id || m.from || 'Unknown');
                const text = _esc(m.text || '');
                const time = m.timestamp
                    ? new Date(m.timestamp).toLocaleTimeString().substr(0, 5)
                    : '';
                const ch = m.channel !== undefined ? ` ch${m.channel}` : '';
                return `<div class="mesh-chat-msg">
                    <span class="mesh-chat-sender mono" style="color:var(--cyan)">${sender}</span>
                    <span class="mesh-chat-text">${text}</span>
                    <span class="mesh-chat-meta mono">${time}${ch}</span>
                </div>`;
            }).join('');

            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        // --- Send message ---
        async function sendMessage() {
            if (!inputEl) return;
            const text = (inputEl.value || '').trim();
            if (!text) return;
            inputEl.value = '';
            if (charCountEl) charCountEl.textContent = String(MESH_MSG_LIMIT);

            const channel = channelSelect ? parseInt(channelSelect.value, 10) : 0;
            const destination = selectedNodeId || null;

            try {
                await fetch('/api/mesh/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, channel, destination }),
                });
            } catch (_) {
                // Silent failure -- toast handled elsewhere
            }
        }

        // --- Input char counter ---
        function onInput() {
            if (!inputEl || !charCountEl) return;
            const remaining = MESH_MSG_LIMIT - (inputEl.value || '').length;
            charCountEl.textContent = String(remaining);
            charCountEl.style.color = remaining < 20 ? 'var(--magenta)' : 'var(--text-dim)';
        }

        // --- Search filter ---
        if (searchInput) {
            searchInput.addEventListener('input', () => {
                searchFilter = (searchInput.value || '').trim();
                renderNodes();
            });
        }

        // --- Sort change ---
        if (sortSelect) {
            sortSelect.addEventListener('change', () => renderNodes());
        }

        // --- Clear DM target ---
        if (clearDmBtn) {
            clearDmBtn.addEventListener('click', () => {
                selectedNodeId = null;
                if (dmIndicator) dmIndicator.style.display = 'none';
                if (nodeDetailEl) nodeDetailEl.style.display = 'none';
                renderNodes();
            });
        }

        // --- Wire input events ---
        if (inputEl) {
            inputEl.addEventListener('input', onInput);
            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    sendMessage();
                }
            });
        }
        if (sendBtn) sendBtn.addEventListener('click', sendMessage);

        // --- Radio tab: connect/disconnect ---
        if (connectBtn) {
            connectBtn.addEventListener('click', async () => {
                const host = (radioHostInput && radioHostInput.value || '').trim();
                const port = radioPortInput ? parseInt(radioPortInput.value, 10) || 4403 : 4403;
                if (!host) return;

                connectBtn.disabled = true;
                connectBtn.textContent = 'CONNECTING...';
                try {
                    const res = await fetch('/api/mesh/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ host, port }),
                    });
                    if (res.ok) {
                        TritiumStore.set('mesh.connected', true);
                        if (radioHostEl) radioHostEl.textContent = `${host}:${port}`;
                        updateStatus({ connected: true, bridge_online: false });
                        fetchChannels();
                    }
                } catch (_) {}
                connectBtn.disabled = false;
                connectBtn.textContent = 'CONNECT';
            });
        }

        if (disconnectBtn) {
            disconnectBtn.addEventListener('click', async () => {
                try {
                    await fetch('/api/mesh/disconnect', { method: 'POST' });
                    TritiumStore.set('mesh.connected', false);
                    if (radioHostEl) radioHostEl.textContent = '--';
                    if (radioChannelsEl) radioChannelsEl.innerHTML = '<span class="panel-empty">Not connected</span>';
                    updateStatus({ connected: false, bridge_online: false });
                } catch (_) {}
            });
        }

        // --- Fetch channels ---
        async function fetchChannels() {
            if (!radioChannelsEl) return;
            try {
                const res = await fetch('/api/mesh/channels');
                if (!res.ok) return;
                const data = await res.json();
                const channels = data.channels || [];
                if (channels.length === 0) {
                    radioChannelsEl.innerHTML = '<span class="panel-empty">No channels</span>';
                    return;
                }
                radioChannelsEl.innerHTML = channels.map(ch => {
                    const name = _esc(ch.name || `ch${ch.index}`);
                    const role = _esc(ch.role || '--');
                    return `<div class="panel-stat-row">
                        <span class="panel-stat-label">${name}</span>
                        <span class="panel-stat-value">${role}</span>
                    </div>`;
                }).join('');

                // Also update channel selector in Chat tab
                if (channelSelect) {
                    channelSelect.innerHTML = channels.map(ch => {
                        const name = ch.name || `ch${ch.index}`;
                        const label = ch.role === 'PRIMARY' ? `${name} (primary)` : name;
                        return `<option value="${ch.index}">${_esc(label)}</option>`;
                    }).join('');
                }
            } catch (_) {}
        }

        // --- Scan tab ---
        if (scanBtn) {
            scanBtn.addEventListener('click', async () => {
                scanBtn.disabled = true;
                scanBtn.textContent = 'SCANNING...';
                if (scanStatusEl) scanStatusEl.textContent = 'Scanning for meshtastic devices via mDNS...';
                if (scanResultsEl) scanResultsEl.innerHTML = '';

                try {
                    const res = await fetch('/api/mesh/discover');
                    if (!res.ok) {
                        if (scanStatusEl) scanStatusEl.textContent = 'Scan failed';
                        return;
                    }
                    const data = await res.json();
                    const devices = data.devices || [];

                    if (devices.length === 0) {
                        if (scanStatusEl) scanStatusEl.textContent = 'No devices found';
                        if (scanResultsEl) scanResultsEl.innerHTML = '<span class="panel-empty">No devices found</span>';
                        return;
                    }

                    if (scanStatusEl) scanStatusEl.textContent = `Found ${devices.length} device(s)`;
                    if (scanResultsEl) {
                        scanResultsEl.innerHTML = devices.map(d => {
                            const host = _esc(d.host || '--');
                            const port = d.port || 4403;
                            const name = _esc(d.name || 'Unknown');
                            return `<div class="mesh-scan-device panel-list-item">
                                <span class="panel-icon-badge" style="color:var(--green);border-color:var(--green)">M</span>
                                <span class="mesh-scan-device-info">
                                    <span class="mono">${name}</span>
                                    <span class="mono" style="color:var(--text-dim)">${host}:${port}</span>
                                </span>
                                <button class="panel-action-btn panel-action-btn-primary mesh-scan-connect"
                                        data-host="${host}" data-port="${port}">CONNECT</button>
                            </div>`;
                        }).join('');

                        scanResultsEl.querySelectorAll('.mesh-scan-connect').forEach(btn => {
                            btn.addEventListener('click', async () => {
                                const h = btn.dataset.host;
                                const p = parseInt(btn.dataset.port, 10) || 4403;
                                btn.disabled = true;
                                btn.textContent = 'CONNECTING...';
                                try {
                                    const r = await fetch('/api/mesh/connect', {
                                        method: 'POST',
                                        headers: { 'Content-Type': 'application/json' },
                                        body: JSON.stringify({ host: h, port: p }),
                                    });
                                    if (r.ok) {
                                        TritiumStore.set('mesh.connected', true);
                                        if (radioHostEl) radioHostEl.textContent = `${h}:${p}`;
                                        updateStatus({ connected: true, bridge_online: false });
                                        fetchChannels();
                                        switchTab('radio');
                                    }
                                } catch (_) {}
                                btn.disabled = false;
                                btn.textContent = 'CONNECT';
                            });
                        });
                    }
                } catch (_) {
                    if (scanStatusEl) scanStatusEl.textContent = 'Scan failed';
                }

                scanBtn.disabled = false;
                scanBtn.textContent = 'SCAN FOR DEVICES';
            });
        }

        // --- EventBus subscriptions ---
        panel._unsubs.push(
            EventBus.on('mesh:text', (data) => {
                messages.push(data);
                msgCount++;
                renderMessages();
            }),

            EventBus.on('mesh:position', (data) => {
                if (data && data.id) {
                    nodes[data.id] = { ...nodes[data.id], ...data };
                    renderNodes();
                }
            }),

            EventBus.on('mesh:telemetry', (data) => {
                if (data && data.id) {
                    nodes[data.id] = { ...nodes[data.id], ...data };
                    renderNodes();
                }
            }),

            EventBus.on('mesh:connected', () => {
                TritiumStore.set('mesh.connected', true);
                updateStatus({ connected: true, bridge_online: false });
                fetchChannels();
            }),

            EventBus.on('mesh:disconnected', () => {
                TritiumStore.set('mesh.connected', false);
                updateStatus({ connected: false, bridge_online: false });
            }),
        );

        // Auto-refresh node list every 10s
        const refreshInterval = setInterval(() => {
            fetch('/api/meshtastic/nodes').then(r => r.ok ? r.json() : null).then(data => {
                if (!data) return;
                const nodeArr = Array.isArray(data) ? data : (data.nodes || []);
                nodes = {};
                for (const n of nodeArr) {
                    const id = n.node_id || n.id;
                    if (id) nodes[id] = n;
                }
                renderNodes();
            }).catch(() => {});
        }, 10000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Initial data fetch
        fetch('/api/meshtastic/nodes').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            const nodeArr = Array.isArray(data) ? data : (data.nodes || []);
            for (const n of nodeArr) {
                const id = n.node_id || n.id;
                if (id) nodes[id] = n;
            }
            renderNodes();
        }).catch(() => {});

        fetch('/api/meshtastic/messages').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            messages = Array.isArray(data) ? data : (data.messages || []);
            msgCount = messages.length;
            renderMessages();
        }).catch(() => {});

        fetch('/api/meshtastic/status').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            updateStatus(data);
            if (data.connected || data.bridge_online) {
                TritiumStore.set('mesh.connected', true);
                if (radioHostEl && data.host) radioHostEl.textContent = data.host;
                fetchChannels();
            }
        }).catch(() => {});

        // Apply current status
        updateStatus(null);
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
