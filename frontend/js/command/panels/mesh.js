// Mesh Radio Panel — Tabbed Meshtastic client
// Tabs: Nodes | Chat | Radio | Scan
// Subscribes to: mesh:text, mesh:position, mesh:telemetry, mesh:connected, mesh:disconnected

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const MESH_MSG_LIMIT = 228;

export const MeshPanelDef = {
    id: 'mesh',
    title: 'MESHTASTIC',
    defaultPosition: { x: 16, y: 400 },
    defaultSize: { w: 360, h: 460 },

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
        const radioHostEl = bodyEl.querySelector('[data-bind="radio-host"]');
        const radioHostInput = bodyEl.querySelector('[data-bind="radio-host-input"]');
        const radioPortInput = bodyEl.querySelector('[data-bind="radio-port-input"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');
        const radioChannelsEl = bodyEl.querySelector('[data-bind="radio-channels"]');
        const scanBtn = bodyEl.querySelector('[data-action="scan"]');
        const scanStatusEl = bodyEl.querySelector('[data-bind="scan-status"]');
        const scanResultsEl = bodyEl.querySelector('[data-bind="scan-results"]');

        let nodes = {};
        let messages = [];
        let msgCount = 0;
        let selectedNodeId = null;
        let activeTab = 'nodes';

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
        function updateStatus() {
            const connected = TritiumStore.get('mesh.connected');
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
                radioStatusEl.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
                radioStatusEl.style.color = connected ? 'var(--green)' : 'var(--text-dim)';
            }
        }

        // --- Node list rendering ---
        function renderNodes() {
            const nodeArr = Object.values(nodes);
            if (nodeCountEl) nodeCountEl.textContent = `${nodeArr.length} nodes`;

            if (!nodeListEl) return;

            if (nodeArr.length === 0) {
                nodeListEl.innerHTML = '<li class="panel-empty">No nodes discovered</li>';
                return;
            }

            nodeListEl.innerHTML = nodeArr.map(n => {
                const nodeId = n.node_id || n.id || '';
                const name = _esc(n.short_name || n.long_name || nodeId || '???');
                const bat = n.battery !== undefined && n.battery !== null
                    ? `${Math.round(n.battery)}%` : '--';
                const snr = n.snr !== undefined && n.snr !== null
                    ? `${Number(n.snr).toFixed(1)}dB` : '--';
                const lastHeard = n.last_heard
                    ? new Date(n.last_heard * 1000).toLocaleTimeString().substr(0, 5)
                    : '--';
                const isSelected = selectedNodeId === nodeId;
                return `<li class="panel-list-item mesh-node-item${isSelected ? ' active' : ''}" data-node-id="${_esc(nodeId)}" role="option">
                    <span class="panel-icon-badge" style="color:var(--cyan);border-color:var(--cyan)">M</span>
                    <span class="mesh-node-name">${name}</span>
                    <span class="mono mesh-node-stats">
                        <span title="Battery">${bat}</span>
                        <span title="SNR">${snr}</span>
                        <span title="Last heard">${lastHeard}</span>
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
                    if (node && node.latitude !== undefined && node.longitude !== undefined) {
                        EventBus.emit('mesh:center-on-node', {
                            id: nodeId,
                            lat: node.latitude,
                            lng: node.longitude,
                        });
                    }
                });
            });
        }

        // --- Node detail display ---
        function showNodeDetail(nodeId) {
            if (!nodeDetailEl) return;
            const n = nodes[nodeId];
            if (!n) {
                nodeDetailEl.style.display = 'none';
                return;
            }

            const pos = n.position;
            const gpsStr = pos
                ? `${pos.lat !== undefined ? pos.lat.toFixed(6) : '--'}, ${pos.lng !== undefined ? pos.lng.toFixed(6) : '--'}`
                : '--';
            const altStr = pos && pos.alt !== undefined ? `${pos.alt.toFixed(1)}m` : '--';

            nodeDetailEl.style.display = '';
            nodeDetailEl.innerHTML = `
                <div class="panel-section-label">NODE DETAIL</div>
                <div class="panel-stat-row"><span class="panel-stat-label">LONG NAME</span><span class="panel-stat-value">${_esc(n.long_name || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">SHORT NAME</span><span class="panel-stat-value">${_esc(n.short_name || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">HARDWARE</span><span class="panel-stat-value">${_esc(n.hardware || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">BATTERY</span><span class="panel-stat-value">${n.battery !== undefined && n.battery !== null ? Math.round(n.battery) + '%' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">VOLTAGE</span><span class="panel-stat-value">${n.voltage !== undefined && n.voltage !== null ? n.voltage.toFixed(2) + 'V' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">SNR</span><span class="panel-stat-value">${n.snr !== undefined && n.snr !== null ? Number(n.snr).toFixed(1) + 'dB' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">RSSI</span><span class="panel-stat-value">${n.rssi !== undefined && n.rssi !== null ? n.rssi + 'dBm' : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">HOPS</span><span class="panel-stat-value">${n.hops !== undefined ? n.hops : '--'}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">GPS</span><span class="panel-stat-value">${gpsStr}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">ALTITUDE</span><span class="panel-stat-value">${altStr}</span></div>
            `;
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
                const sender = _esc(m.from_short || m.from || 'Unknown');
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
                        updateStatus();
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
                    updateStatus();
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
                                        updateStatus();
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
                updateStatus();
                fetchChannels();
            }),

            EventBus.on('mesh:disconnected', () => {
                TritiumStore.set('mesh.connected', false);
                updateStatus();
            }),
        );

        // Auto-refresh node list every 10s
        const refreshInterval = setInterval(() => {
            fetch('/api/mesh/nodes').then(r => r.ok ? r.json() : null).then(data => {
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
        fetch('/api/mesh/nodes').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            const nodeArr = Array.isArray(data) ? data : (data.nodes || []);
            for (const n of nodeArr) {
                const id = n.node_id || n.id;
                if (id) nodes[id] = n;
            }
            renderNodes();
        }).catch(() => {});

        fetch('/api/mesh/messages').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            messages = Array.isArray(data) ? data : (data.messages || []);
            msgCount = messages.length;
            renderMessages();
        }).catch(() => {});

        fetch('/api/mesh/status').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            if (data.connected) {
                TritiumStore.set('mesh.connected', true);
                if (radioHostEl) radioHostEl.textContent = data.host || '--';
                fetchChannels();
            }
        }).catch(() => {});

        // Apply current status
        updateStatus();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
