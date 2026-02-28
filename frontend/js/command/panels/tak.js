// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// TAK Panel — Team Awareness Kit server management
// Tabs: Status | Clients | Chat | Alert | Server
// Subscribes to: tak:connected, tak:disconnected, tak:client_update, tak:geochat

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const TakPanelDef = {
    id: 'tak',
    title: 'TAK',
    defaultPosition: { x: 16, y: 440 },
    defaultSize: { w: 360, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'tak-panel-inner';
        el.innerHTML = `
            <div class="tak-tabs" data-bind="tabs">
                <button class="tak-tab active" data-tab="status">Status</button>
                <button class="tak-tab" data-tab="clients">Clients</button>
                <button class="tak-tab" data-tab="chat">Chat</button>
                <button class="tak-tab" data-tab="alert">Alert</button>
                <button class="tak-tab" data-tab="server">Server</button>
            </div>
            <div class="tak-tab-content" data-bind="tab-content">
                <div class="tak-tab-pane active" data-pane="status">
                    <div class="panel-section-label">BRIDGE STATUS</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">ENABLED</span>
                        <span class="panel-stat-value" data-bind="stat-enabled">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">CONNECTED</span>
                        <span class="panel-stat-value" data-bind="stat-connected">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">COT URL</span>
                        <span class="panel-stat-value" data-bind="stat-cot-url">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">CALLSIGN</span>
                        <span class="panel-stat-value" data-bind="stat-callsign">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">TEAM</span>
                        <span class="panel-stat-value" data-bind="stat-team">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">ROLE</span>
                        <span class="panel-stat-value" data-bind="stat-role">--</span>
                    </div>
                    <div class="panel-section-label" style="margin-top:8px">TRAFFIC</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">SENT</span>
                        <span class="panel-stat-value" data-bind="stat-sent">0</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">RECEIVED</span>
                        <span class="panel-stat-value" data-bind="stat-received">0</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">TX QUEUE</span>
                        <span class="panel-stat-value" data-bind="stat-queue">0</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">CLIENTS</span>
                        <span class="panel-stat-value" data-bind="stat-clients">0</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">LAST ERROR</span>
                        <span class="panel-stat-value" data-bind="stat-error" style="color:var(--text-ghost)">--</span>
                    </div>
                </div>
                <div class="tak-tab-pane" data-pane="clients" style="display:none">
                    <ul class="panel-list tak-client-list" data-bind="client-list" role="listbox" aria-label="TAK clients">
                        <li class="panel-empty">No TAK clients discovered</li>
                    </ul>
                    <div class="tak-client-detail" data-bind="client-detail" style="display:none"></div>
                </div>
                <div class="tak-tab-pane" data-pane="chat" style="display:none">
                    <div class="tak-chat-messages" data-bind="chat-messages"></div>
                    <div class="tak-chat-input-row">
                        <input type="text" class="tak-form-input tak-chat-input" data-bind="chat-input"
                               placeholder="Type a message..." autocomplete="off" />
                        <button class="panel-action-btn panel-action-btn-primary tak-chat-send" data-action="send-chat">SEND</button>
                    </div>
                </div>
                <div class="tak-tab-pane" data-pane="alert" style="display:none">
                    <div class="panel-section-label">SEND THREAT ALERT</div>
                    <div class="tak-alert-form">
                        <div class="tak-form-row">
                            <label class="tak-form-label mono">CALLSIGN</label>
                            <input type="text" class="tak-form-input" data-bind="alert-callsign"
                                   placeholder="e.g. THREAT-1" autocomplete="off" />
                        </div>
                        <div class="tak-form-row">
                            <label class="tak-form-label mono">LAT</label>
                            <input type="number" class="tak-form-input" data-bind="alert-lat"
                                   step="0.000001" placeholder="37.7749" />
                        </div>
                        <div class="tak-form-row">
                            <label class="tak-form-label mono">LNG</label>
                            <input type="number" class="tak-form-input" data-bind="alert-lng"
                                   step="0.000001" placeholder="-122.4194" />
                        </div>
                        <div class="tak-form-row">
                            <label class="tak-form-label mono">REMARKS</label>
                            <input type="text" class="tak-form-input" data-bind="alert-remarks"
                                   placeholder="Optional description" autocomplete="off" />
                        </div>
                        <div class="tak-alert-actions">
                            <button class="panel-action-btn panel-action-btn-primary" data-action="send-alert">SEND ALERT</button>
                        </div>
                        <div class="tak-alert-result mono" data-bind="alert-result" style="font-size:0.5rem;margin-top:4px;color:var(--text-ghost)"></div>
                    </div>
                </div>
                <div class="tak-tab-pane" data-pane="server" style="display:none">
                    <div class="panel-section-label">TAK SERVER</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">PROTOCOL</span>
                        <span class="panel-stat-value" data-bind="srv-protocol">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">HOST</span>
                        <span class="panel-stat-value" data-bind="srv-host">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">PORT</span>
                        <span class="panel-stat-value" data-bind="srv-port">--</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">TLS</span>
                        <span class="panel-stat-value" data-bind="srv-tls">--</span>
                    </div>
                    <div class="panel-section-label" style="margin-top:8px">SEND RAW COT</div>
                    <div class="tak-raw-cot">
                        <textarea class="tak-cot-textarea" data-bind="cot-xml"
                                  rows="6" placeholder="<event version='2.0' ...></event>"></textarea>
                        <div class="tak-raw-actions">
                            <button class="panel-action-btn panel-action-btn-primary" data-action="send-cot">SEND COT XML</button>
                        </div>
                        <div class="tak-raw-result mono" data-bind="cot-result" style="font-size:0.5rem;margin-top:4px;color:var(--text-ghost)"></div>
                    </div>
                </div>
            </div>
            <div class="tak-status-bar" data-bind="status">
                <span class="panel-dot panel-dot-neutral" data-bind="status-dot"></span>
                <span class="mono" data-bind="status-label">DISCONNECTED</span>
                <span class="mono" style="margin-left:auto" data-bind="client-count">0 clients</span>
                <span class="mono" style="margin-left:8px" data-bind="msg-total">0 msgs</span>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // --- Element references ---
        const tabsEl = bodyEl.querySelector('[data-bind="tabs"]');
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusLabel = bodyEl.querySelector('[data-bind="status-label"]');
        const clientCountEl = bodyEl.querySelector('[data-bind="client-count"]');
        const msgTotalEl = bodyEl.querySelector('[data-bind="msg-total"]');
        const clientListEl = bodyEl.querySelector('[data-bind="client-list"]');
        const clientDetailEl = bodyEl.querySelector('[data-bind="client-detail"]');

        // Status tab elements
        const statEnabled = bodyEl.querySelector('[data-bind="stat-enabled"]');
        const statConnected = bodyEl.querySelector('[data-bind="stat-connected"]');
        const statCotUrl = bodyEl.querySelector('[data-bind="stat-cot-url"]');
        const statCallsign = bodyEl.querySelector('[data-bind="stat-callsign"]');
        const statTeam = bodyEl.querySelector('[data-bind="stat-team"]');
        const statRole = bodyEl.querySelector('[data-bind="stat-role"]');
        const statSent = bodyEl.querySelector('[data-bind="stat-sent"]');
        const statReceived = bodyEl.querySelector('[data-bind="stat-received"]');
        const statQueue = bodyEl.querySelector('[data-bind="stat-queue"]');
        const statClients = bodyEl.querySelector('[data-bind="stat-clients"]');
        const statError = bodyEl.querySelector('[data-bind="stat-error"]');

        // Server tab elements
        const srvProtocol = bodyEl.querySelector('[data-bind="srv-protocol"]');
        const srvHost = bodyEl.querySelector('[data-bind="srv-host"]');
        const srvPort = bodyEl.querySelector('[data-bind="srv-port"]');
        const srvTls = bodyEl.querySelector('[data-bind="srv-tls"]');

        // Alert form elements
        const alertCallsign = bodyEl.querySelector('[data-bind="alert-callsign"]');
        const alertLat = bodyEl.querySelector('[data-bind="alert-lat"]');
        const alertLng = bodyEl.querySelector('[data-bind="alert-lng"]');
        const alertRemarks = bodyEl.querySelector('[data-bind="alert-remarks"]');
        const alertBtn = bodyEl.querySelector('[data-action="send-alert"]');
        const alertResult = bodyEl.querySelector('[data-bind="alert-result"]');

        // Raw CoT elements
        const cotXml = bodyEl.querySelector('[data-bind="cot-xml"]');
        const cotBtn = bodyEl.querySelector('[data-action="send-cot"]');
        const cotResult = bodyEl.querySelector('[data-bind="cot-result"]');

        // Chat tab elements
        const chatMessagesEl = bodyEl.querySelector('[data-bind="chat-messages"]');
        const chatInput = bodyEl.querySelector('[data-bind="chat-input"]');
        const chatSendBtn = bodyEl.querySelector('[data-action="send-chat"]');

        let clients = {};
        let selectedClientUid = null;
        let chatMessages = [];

        // --- Tab switching ---
        function switchTab(tabName) {
            if (tabsEl) {
                const tabs = tabsEl.querySelectorAll('.tak-tab');
                tabs.forEach(t => {
                    if (t.dataset.tab === tabName) t.classList.add('active');
                    else t.classList.remove('active');
                });
            }
            const panes = bodyEl.querySelectorAll('.tak-tab-pane');
            panes.forEach(p => {
                const isActive = p.dataset.pane === tabName;
                if (isActive) p.classList.add('active');
                else p.classList.remove('active');
                p.style.display = isActive ? '' : 'none';
            });
        }

        if (tabsEl) {
            tabsEl.addEventListener('click', (e) => {
                const tab = e.target.closest('.tak-tab');
                if (tab && tab.dataset.tab) {
                    switchTab(tab.dataset.tab);
                }
            });
        }

        // --- Status updates ---
        function updateConnectionStatus(connected) {
            TritiumStore.set('tak.connected', connected);
            if (statusDot) {
                statusDot.className = connected
                    ? 'panel-dot panel-dot-green'
                    : 'panel-dot panel-dot-neutral';
            }
            if (statusLabel) {
                statusLabel.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
                statusLabel.style.color = connected ? 'var(--green)' : 'var(--text-dim)';
            }
            if (statConnected) {
                statConnected.textContent = connected ? 'YES' : 'NO';
                statConnected.style.color = connected ? 'var(--green)' : 'var(--magenta)';
            }
        }

        // --- Fetch and render status ---
        async function fetchStatus() {
            try {
                const res = await fetch('/api/tak/status');
                if (!res.ok) return;
                const data = await res.json();

                const connected = !!data.connected;
                updateConnectionStatus(connected);

                if (statEnabled) {
                    statEnabled.textContent = data.enabled ? 'YES' : 'NO';
                    statEnabled.style.color = data.enabled ? 'var(--green)' : 'var(--text-ghost)';
                }
                if (statCotUrl) statCotUrl.textContent = data.cot_url || '--';
                if (statCallsign) statCallsign.textContent = data.callsign || '--';
                if (statTeam) {
                    const teamColors = {
                        Cyan: 'var(--cyan)', Red: 'var(--magenta)',
                        White: 'var(--fg)', Yellow: 'var(--yellow)',
                    };
                    statTeam.textContent = data.team || '--';
                    statTeam.style.color = teamColors[data.team] || 'var(--fg)';
                }
                if (statRole) statRole.textContent = data.role || '--';
                if (statSent) statSent.textContent = data.messages_sent ?? 0;
                if (statReceived) statReceived.textContent = data.messages_received ?? 0;
                if (statQueue) statQueue.textContent = data.tx_queue_size ?? 0;
                if (statClients) statClients.textContent = data.clients ?? 0;
                if (statError) {
                    const err = data.last_error || '--';
                    statError.textContent = err;
                    statError.style.color = (err && err !== '--') ? 'var(--magenta)' : 'var(--text-ghost)';
                }
                if (msgTotalEl) {
                    const total = (data.messages_sent ?? 0) + (data.messages_received ?? 0);
                    msgTotalEl.textContent = `${total} msgs`;
                }

                // Parse COT URL for server tab
                const cotUrl = data.cot_url || '';
                if (cotUrl) {
                    const match = cotUrl.match(/^(tcp|ssl|tls|udp):\/\/([^:]+):?(\d+)?$/);
                    if (match) {
                        if (srvProtocol) srvProtocol.textContent = match[1].toUpperCase();
                        if (srvHost) srvHost.textContent = match[2];
                        if (srvPort) srvPort.textContent = match[3] || (match[1] === 'ssl' || match[1] === 'tls' ? '8089' : '8088');
                        if (srvTls) {
                            const isTls = match[1] === 'ssl' || match[1] === 'tls';
                            srvTls.textContent = isTls ? 'ENABLED' : 'DISABLED';
                            srvTls.style.color = isTls ? 'var(--green)' : 'var(--text-ghost)';
                        }
                    }
                }
            } catch (_) {}
        }

        // --- Client list rendering ---
        function renderClients() {
            const clientArr = Object.values(clients);
            if (clientCountEl) clientCountEl.textContent = `${clientArr.length} clients`;

            if (!clientListEl) return;

            if (clientArr.length === 0) {
                clientListEl.innerHTML = '<li class="panel-empty">No TAK clients discovered</li>';
                return;
            }

            clientListEl.innerHTML = clientArr.map(c => {
                const uid = _esc(c.uid || '');
                const callsign = _esc(c.callsign || uid || '???');
                const alliance = (c.alliance || 'unknown').toLowerCase();
                const allianceColor = {
                    friendly: 'var(--cyan)', hostile: 'var(--magenta)',
                    neutral: 'var(--fg)', unknown: 'var(--yellow)',
                }[alliance] || 'var(--text-dim)';
                const lastSeen = c.last_seen
                    ? new Date(c.last_seen * 1000).toLocaleTimeString().substr(0, 5)
                    : '--';
                const assetType = _esc(c.asset_type || 'person');
                const cotType = _esc(c.cot_type || '');
                const isSelected = selectedClientUid === uid;
                return `<li class="panel-list-item tak-client-item${isSelected ? ' active' : ''}" data-uid="${uid}" role="option">
                    <span class="panel-icon-badge" style="color:${allianceColor};border-color:${allianceColor}">T</span>
                    <span class="tak-client-name">${callsign}</span>
                    <span class="mono tak-client-stats">
                        <span title="Type">${assetType}${cotType ? ' (' + cotType + ')' : ''}</span>
                        <span title="Last seen">${lastSeen}</span>
                    </span>
                </li>`;
            }).join('');

            // Click handler: expand client detail
            clientListEl.querySelectorAll('.tak-client-item').forEach(item => {
                item.addEventListener('click', () => {
                    const uid = item.dataset.uid;
                    if (selectedClientUid === uid) {
                        selectedClientUid = null;
                        if (clientDetailEl) clientDetailEl.style.display = 'none';
                    } else {
                        selectedClientUid = uid;
                        showClientDetail(uid);
                    }
                    renderClients();
                });
            });
        }

        // --- Client detail display ---
        function showClientDetail(uid) {
            if (!clientDetailEl) return;
            const c = clients[uid];
            if (!c) {
                clientDetailEl.style.display = 'none';
                return;
            }

            const lat = c.lat !== undefined ? Number(c.lat).toFixed(6) : '--';
            const lng = c.lng !== undefined ? Number(c.lng).toFixed(6) : '--';
            const alt = c.alt !== undefined ? `${Number(c.alt).toFixed(1)}m` : '--';
            const speed = c.speed !== undefined ? `${Number(c.speed).toFixed(1)} m/s` : '--';
            const heading = c.heading !== undefined ? `${Number(c.heading).toFixed(0)}deg` : '--';
            const lastSeen = c.last_seen
                ? new Date(c.last_seen * 1000).toLocaleString()
                : '--';

            clientDetailEl.style.display = '';
            clientDetailEl.innerHTML = `
                <div class="panel-section-label">CLIENT DETAIL</div>
                <div class="panel-stat-row"><span class="panel-stat-label">UID</span><span class="panel-stat-value" style="font-size:0.45rem">${_esc(uid)}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">CALLSIGN</span><span class="panel-stat-value">${_esc(c.callsign || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">ALLIANCE</span><span class="panel-stat-value">${_esc(c.alliance || 'unknown')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">TYPE</span><span class="panel-stat-value">${_esc(c.asset_type || 'person')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">COT TYPE</span><span class="panel-stat-value" style="font-size:0.45rem">${_esc(c.cot_type || '--')}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">LAT</span><span class="panel-stat-value">${lat}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">LNG</span><span class="panel-stat-value">${lng}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">ALT</span><span class="panel-stat-value">${alt}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">SPEED</span><span class="panel-stat-value">${speed}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">HEADING</span><span class="panel-stat-value">${heading}</span></div>
                <div class="panel-stat-row"><span class="panel-stat-label">LAST SEEN</span><span class="panel-stat-value">${_esc(lastSeen)}</span></div>
            `;

            // Center map on client if they have coordinates
            if (c.lat !== undefined && c.lng !== undefined) {
                EventBus.emit('tak:center-on-client', {
                    uid: uid,
                    lat: c.lat,
                    lng: c.lng,
                });
            }
        }

        // --- Fetch clients from API ---
        async function fetchClients() {
            try {
                const res = await fetch('/api/tak/clients');
                if (!res.ok) return;
                const data = await res.json();
                const clientArr = data.clients || [];
                clients = {};
                for (const c of clientArr) {
                    const uid = c.uid || c.id;
                    if (uid) clients[uid] = c;
                }
                renderClients();
            } catch (_) {}
        }

        // --- Send threat alert ---
        if (alertBtn) {
            alertBtn.addEventListener('click', async () => {
                const callsign = (alertCallsign?.value || '').trim();
                const lat = parseFloat(alertLat?.value);
                const lng = parseFloat(alertLng?.value);
                const remarks = (alertRemarks?.value || '').trim();

                if (!callsign || isNaN(lat) || isNaN(lng)) {
                    if (alertResult) {
                        alertResult.textContent = 'Callsign, lat, and lng are required';
                        alertResult.style.color = 'var(--magenta)';
                    }
                    return;
                }

                alertBtn.disabled = true;
                alertBtn.textContent = 'SENDING...';
                try {
                    const res = await fetch('/api/tak/alert', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ callsign, lat, lng, remarks }),
                    });
                    const data = await res.json();
                    if (res.ok) {
                        if (alertResult) {
                            alertResult.textContent = `Alert sent: ${data.callsign}`;
                            alertResult.style.color = 'var(--green)';
                        }
                        // Clear form
                        if (alertCallsign) alertCallsign.value = '';
                        if (alertRemarks) alertRemarks.value = '';
                    } else {
                        if (alertResult) {
                            alertResult.textContent = data.error || 'Send failed';
                            alertResult.style.color = 'var(--magenta)';
                        }
                    }
                } catch (_) {
                    if (alertResult) {
                        alertResult.textContent = 'Network error';
                        alertResult.style.color = 'var(--magenta)';
                    }
                }
                alertBtn.disabled = false;
                alertBtn.textContent = 'SEND ALERT';
            });
        }

        // --- Send raw CoT XML ---
        if (cotBtn) {
            cotBtn.addEventListener('click', async () => {
                const xml = (cotXml?.value || '').trim();
                if (!xml) {
                    if (cotResult) {
                        cotResult.textContent = 'Enter CoT XML to send';
                        cotResult.style.color = 'var(--magenta)';
                    }
                    return;
                }

                cotBtn.disabled = true;
                cotBtn.textContent = 'SENDING...';
                try {
                    const res = await fetch('/api/tak/send', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ cot_xml: xml }),
                    });
                    const data = await res.json();
                    if (res.ok) {
                        if (cotResult) {
                            cotResult.textContent = 'CoT XML queued for transmission';
                            cotResult.style.color = 'var(--green)';
                        }
                    } else {
                        if (cotResult) {
                            cotResult.textContent = data.error || 'Send failed';
                            cotResult.style.color = 'var(--magenta)';
                        }
                    }
                } catch (_) {
                    if (cotResult) {
                        cotResult.textContent = 'Network error';
                        cotResult.style.color = 'var(--magenta)';
                    }
                }
                cotBtn.disabled = false;
                cotBtn.textContent = 'SEND COT XML';
            });
        }

        // --- Chat tab ---
        const MAX_CHAT_MESSAGES = 200;

        function renderChatMessages() {
            if (!chatMessagesEl) return;
            if (chatMessages.length === 0) {
                chatMessagesEl.innerHTML = '<div class="panel-empty">No messages yet</div>';
                return;
            }
            chatMessagesEl.innerHTML = chatMessages.map(m => {
                const callsign = _esc(m.callsign || m.sender || 'Unknown');
                const text = _esc(m.message || m.text || '');
                const time = m.time
                    ? new Date(typeof m.time === 'number' ? m.time * 1000 : m.time).toLocaleTimeString().substr(0, 5)
                    : '';
                const alliance = (m.alliance || 'unknown').toLowerCase();
                const color = {
                    friendly: 'var(--cyan)', hostile: 'var(--magenta)',
                    neutral: 'var(--fg)', unknown: 'var(--yellow)',
                }[alliance] || 'var(--text-dim)';
                return `<div class="tak-chat-message">
                    <span class="tak-chat-sender" style="color:${color}">${callsign}</span>
                    <span>${text}</span>
                    <span class="tak-chat-time">${time}</span>
                </div>`;
            }).join('');
            chatMessagesEl.scrollTop = chatMessagesEl.scrollHeight;
        }

        function addChatMessage(data) {
            chatMessages.push(data);
            if (chatMessages.length > MAX_CHAT_MESSAGES) {
                chatMessages.shift();
            }
            renderChatMessages();
        }

        async function sendChatMessage() {
            const text = (chatInput?.value || '').trim();
            if (!text) return;
            chatInput.value = '';
            try {
                await fetch('/api/tak/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: text, channel: 'All' }),
                });
            } catch (_) {}
        }

        if (chatSendBtn) {
            chatSendBtn.addEventListener('click', sendChatMessage);
        }
        if (chatInput) {
            chatInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendChatMessage();
                }
            });
        }

        // --- EventBus subscriptions ---
        panel._unsubs.push(
            EventBus.on('tak:connected', () => {
                updateConnectionStatus(true);
                fetchStatus();
                fetchClients();
            }),

            EventBus.on('tak:disconnected', () => {
                updateConnectionStatus(false);
            }),

            EventBus.on('tak:client_update', (data) => {
                if (data && data.uid) {
                    clients[data.uid] = { ...clients[data.uid], ...data };
                    renderClients();
                }
                // Refresh full client list periodically for removals
            }),

            EventBus.on('tak:geochat', (data) => {
                if (data) addChatMessage(data);
            }),
        );

        // Auto-refresh every 10s
        const refreshInterval = setInterval(() => {
            fetchStatus();
            fetchClients();
        }, 10000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        // Initial data fetch
        fetchStatus();
        fetchClients();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
