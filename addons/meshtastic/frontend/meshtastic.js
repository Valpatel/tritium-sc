// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// MESHTASTIC — Full-featured management panel modeled on official Meshtastic apps.
// Tabs: RADIO | MESSAGES | NODES | CHANNELS | CONFIG | MODULES
// Auto-detects serial ports on open; auto-connects if exactly one radio found.

import { EventBus } from '/static/js/command/events.js';
import { _esc } from '/static/js/command/panel-utils.js';

const API = '/api/addons/meshtastic';
const REFRESH_MS = 5000;
const MSG_CHAR_LIMIT = 228;

// ─── Tab definitions ────────────────────────────────────────────────
const TABS = [
    { id: 'radio',    label: 'RADIO' },
    { id: 'messages', label: 'MESSAGES' },
    { id: 'nodes',    label: 'NODES' },
    { id: 'channels', label: 'CHANNELS' },
    { id: 'config',   label: 'CONFIG' },
    { id: 'modules',  label: 'MODULES' },
];

// ─── Node table columns ─────────────────────────────────────────────
const NODE_COLS = [
    { key: 'short_name', label: 'NAME',     width: '70px' },
    { key: 'long_name',  label: 'LONG NAME', width: '120px' },
    { key: 'hw_model',   label: 'HARDWARE',  width: '90px' },
    { key: 'snr',        label: 'SNR',       width: '50px',  align: 'right' },
    { key: 'battery',    label: 'BAT',       width: '50px',  align: 'right' },
    { key: 'last_heard', label: 'LAST',      width: '60px',  align: 'right' },
    { key: 'hopsAway',   label: 'HOPS',      width: '40px',  align: 'right' },
    { key: 'distance',   label: 'DIST',      width: '60px',  align: 'right' },
];

// ─── Device role options (from meshtastic protobuf) ──────────────────
const DEVICE_ROLES = [
    'CLIENT', 'CLIENT_MUTE', 'ROUTER', 'ROUTER_CLIENT', 'REPEATER',
    'TRACKER', 'SENSOR', 'TAK', 'CLIENT_HIDDEN', 'LOST_AND_FOUND', 'TAK_TRACKER',
];

const REGIONS = [
    'UNSET', 'US', 'EU_433', 'EU_868', 'CN', 'JP', 'ANZ', 'KR', 'TW', 'RU',
    'IN', 'NZ_865', 'TH', 'LORA_24', 'UA_433', 'UA_868', 'MY_433', 'MY_919',
    'SG_923',
];

const MODEM_PRESETS = [
    'LONG_FAST', 'LONG_SLOW', 'LONG_MODERATE', 'VERY_LONG_SLOW',
    'SHORT_FAST', 'SHORT_SLOW', 'MEDIUM_FAST', 'MEDIUM_SLOW',
];

// ─── Panel definition ────────────────────────────────────────────────
export const MeshtasticPanelDef = {
    id: 'meshtastic',
    title: 'MESHTASTIC',
    defaultPosition: { x: 60, y: 80 },
    defaultSize: { w: 600, h: 700 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'msh-panel';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;font-family:var(--font-mono,"JetBrains Mono",monospace);';

        const tabHtml = TABS.map((t, i) =>
            `<button class="msh-tab${i === 0 ? ' msh-tab-active' : ''}" data-tab="${t.id}">${t.label}</button>`
        ).join('');

        el.innerHTML = `
            <div class="msh-conn-bar">
                <span class="msh-dot" data-bind="dot"></span>
                <span class="msh-conn-label" data-bind="conn-label">DISCONNECTED</span>
                <span style="flex:1"></span>
                <span class="msh-conn-device" data-bind="conn-device"></span>
                <span class="msh-conn-transport" data-bind="conn-transport"></span>
                <select class="msh-port-select" data-bind="port-select" style="display:none"></select>
                <button class="msh-btn msh-btn-connect" data-action="connect">CONNECT</button>
                <button class="msh-btn msh-btn-disconnect" data-action="disconnect" style="display:none">DISCONNECT</button>
            </div>
            <div class="msh-tabs">${tabHtml}</div>
            <div class="msh-body" data-bind="body"></div>
        `;

        return el;
    },

    mount(bodyEl, panel) {
        const dot = bodyEl.querySelector('[data-bind="dot"]');
        const connLabel = bodyEl.querySelector('[data-bind="conn-label"]');
        const connDevice = bodyEl.querySelector('[data-bind="conn-device"]');
        const connTransport = bodyEl.querySelector('[data-bind="conn-transport"]');
        const portSelect = bodyEl.querySelector('[data-bind="port-select"]');
        const connectBtn = bodyEl.querySelector('[data-action="connect"]');
        const disconnectBtn = bodyEl.querySelector('[data-action="disconnect"]');
        const tabContainer = bodyEl.querySelector('.msh-tabs');
        const body = bodyEl.querySelector('[data-bind="body"]');

        let activeTab = 'radio';
        let connected = false;
        let status = {};
        let nodes = [];
        let messages = [];
        let deviceInfo = {};
        let channels = [];
        let moduleConfig = {};
        let ports = [];
        let firmwareInfo = {};
        let firmwareVersions = [];
        let nodeSortKey = 'last_heard';
        let nodeSortDir = -1;
        let selectedChannel = 0; // for message channel selector
        let channelEditIndex = -1; // which channel slot is being edited
        let chatOnlyFilter = true; // filter system messages by default
        let deviceInfoFetched = false; // track if we've fetched device info this session

        _injectStyles();

        // Load cached data from localStorage
        const cached = localStorage.getItem('tritium.meshtastic.cache');
        if (cached) {
            try {
                const c = JSON.parse(cached);
                if (c.deviceInfo) deviceInfo = c.deviceInfo;
                if (c.nodes) nodes = c.nodes;
                if (c.status) updateConnection(c.status);
            } catch (_) {}
        }

        // ── Tab switching ───────────────────────────────────────
        tabContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.msh-tab');
            if (btn === null) return;
            activeTab = btn.dataset.tab;
            tabContainer.querySelectorAll('.msh-tab').forEach(t =>
                t.classList.toggle('msh-tab-active', t.dataset.tab === activeTab)
            );
            renderBody();
        });

        // ── Connect button ──────────────────────────────────────
        connectBtn.addEventListener('click', async () => {
            connectBtn.disabled = true;
            connectBtn.textContent = 'CONNECTING...';
            try {
                const payload = { transport: 'serial', timeout: 60 };
                if (portSelect.style.display !== 'none' && portSelect.value) {
                    payload.port = portSelect.value;
                }
                const r = await fetch(API + '/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (r.ok) {
                    const d = await r.json();
                    updateConnection(d);
                    fetchAll();
                    fetchDeviceInfo();
                    fetchChannels();
                    fetchModuleConfig();
                }
            } catch (_) { /* network error */ }
            connectBtn.disabled = false;
            connectBtn.textContent = 'CONNECT';
        });

        disconnectBtn.addEventListener('click', async () => {
            try { await fetch(API + '/disconnect', { method: 'POST' }); } catch (_) { /* ok */ }
            updateConnection({ connected: false, transport: 'none', port: '', device: {} });
        });

        // ── Connection state ────────────────────────────────────
        function updateConnection(d) {
            if (d === null || d === undefined) return;
            connected = d.connected || false;
            status = d;
            dot.className = connected ? 'msh-dot msh-dot-on' : 'msh-dot';
            connLabel.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
            connLabel.style.color = connected ? '#05ffa1' : '#888';
            const dev = d.device || {};
            connDevice.textContent = connected ? _esc(dev.long_name || dev.short_name || dev.hw_model || '') : '';
            connTransport.textContent = connected ? `${_esc(d.transport || '')} ${_esc(d.port || '')}` : '';
            connectBtn.style.display = connected ? 'none' : '';
            disconnectBtn.style.display = connected ? '' : 'none';
            portSelect.style.display = (connected || ports.length <= 1) ? 'none' : '';
        }

        // ── Data fetching ───────────────────────────────────────
        function _saveCache() {
            try {
                localStorage.setItem('tritium.meshtastic.cache', JSON.stringify({
                    status, deviceInfo, nodes, timestamp: Date.now(),
                }));
            } catch (_) {}
        }

        async function fetchAll() {
            try {
                const [sRes, nRes] = await Promise.all([
                    fetch(API + '/status').then(r => r.ok ? r.json() : null),
                    fetch(API + '/nodes').then(r => r.ok ? r.json() : null),
                ]);
                if (sRes) updateConnection(sRes);
                if (nRes) { nodes = nRes.nodes || []; }
                _saveCache();
                renderBody();
            } catch (_) { /* network error */ }
        }

        async function fetchMessages() {
            try {
                const r = await fetch(API + '/messages?limit=100');
                if (r.ok) {
                    const d = await r.json();
                    messages = d.messages || [];
                }
            } catch (_) { /* ok */ }
        }

        async function fetchDeviceInfo() {
            try {
                const r = await fetch(API + '/device/info');
                if (r.ok) {
                    deviceInfo = await r.json();
                    deviceInfoFetched = true;
                    _saveCache();
                }
            } catch (_) { /* ok */ }
        }

        async function fetchChannels() {
            try {
                const r = await fetch(API + '/device/channels');
                if (r.ok) {
                    const d = await r.json();
                    channels = d.channels || d || [];
                }
            } catch (_) { /* ok */ }
        }

        async function fetchModuleConfig() {
            try {
                const r = await fetch(API + '/device/modules');
                if (r.ok) moduleConfig = await r.json();
            } catch (_) { /* ok */ }
        }

        async function fetchFirmware() {
            try {
                const [fwRes, versRes] = await Promise.all([
                    fetch(API + '/device/firmware').then(r => r.ok ? r.json() : null),
                    fetch(API + '/device/firmware/versions').then(r => r.ok ? r.json() : null),
                ]);
                if (fwRes) firmwareInfo = fwRes;
                if (versRes) firmwareVersions = versRes.versions || versRes || [];
            } catch (_) { /* ok */ }
        }

        async function fetchPorts() {
            try {
                const r = await fetch(API + '/ports');
                if (r.ok) {
                    const d = await r.json();
                    ports = d.ports || [];
                }
            } catch (_) { /* ok */ }
        }

        // ── Port auto-detect on open ────────────────────────────
        async function initAutoDetect() {
            const sRes = await fetch(API + '/status').then(r => r.ok ? r.json() : null).catch(() => null);
            if (sRes && sRes.connected) {
                updateConnection(sRes);
                fetchAll();
                fetchDeviceInfo();
                fetchChannels();
                fetchModuleConfig();
                fetchFirmware();
                return;
            }
            await fetchPorts();
            if (ports.length === 0) {
                connDevice.textContent = '';
                connTransport.textContent = 'No radio found';
                connTransport.style.color = '#ff2a6d';
            } else if (ports.length === 1) {
                connLabel.textContent = 'AUTO-CONNECTING...';
                connLabel.style.color = '#fcee0a';
                try {
                    const cr = await fetch(API + '/connect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ transport: 'serial', port: ports[0].port || ports[0], timeout: 60 }),
                    });
                    if (cr.ok) {
                        const cd = await cr.json();
                        updateConnection(cd);
                        fetchAll();
                        fetchDeviceInfo();
                        fetchChannels();
                        fetchModuleConfig();
                        fetchFirmware();
                    } else {
                        connLabel.textContent = 'DISCONNECTED';
                        connLabel.style.color = '#888';
                    }
                } catch (_) {
                    connLabel.textContent = 'DISCONNECTED';
                    connLabel.style.color = '#888';
                }
            } else {
                // Multiple ports - show dropdown
                portSelect.innerHTML = ports.map(p => {
                    const port = typeof p === 'string' ? p : (p.port || '');
                    const desc = typeof p === 'object' && p.description ? ` (${_esc(p.description)})` : '';
                    return `<option value="${_esc(port)}">${_esc(port)}${desc}</option>`;
                }).join('');
                portSelect.style.display = '';
                connTransport.textContent = `${ports.length} radios found`;
                connTransport.style.color = '#fcee0a';
            }
        }

        // ── Render active tab ───────────────────────────────────
        function renderBody() {
            if (body === null) return;
            switch (activeTab) {
                case 'radio':    renderRadio(); break;
                case 'messages': renderMessages(); break;
                case 'nodes':    renderNodes(); break;
                case 'channels': renderChannels(); break;
                case 'config':   renderConfig(); break;
                case 'modules':  renderModules(); break;
            }
        }

        // =====================================================================
        //  RADIO TAB
        // =====================================================================
        function renderRadio() {
            const di = deviceInfo;
            const connStatus = connected ? 'CONNECTED' : 'DISCONNECTED';
            const connColor = connected ? '#05ffa1' : '#ff2a6d';
            const withGps = nodes.filter(n => n.lat != null && (n.lat !== 0 || n.lng !== 0)).length;
            const batts = nodes.map(n => n.battery).filter(b => b != null && b > 0);
            const avgBat = batts.length ? Math.round(batts.reduce((a, b) => a + b, 0) / batts.length) : null;
            const utils = nodes.map(n => n.channel_util).filter(u => u != null);
            const avgUtil = utils.length ? (utils.reduce((a, b) => a + b, 0) / utils.length).toFixed(1) : null;
            const airUtils = nodes.map(n => n.air_util_tx).filter(u => u != null);
            const avgAirUtil = airUtils.length ? (airUtils.reduce((a, b) => a + b, 0) / airUtils.length).toFixed(1) : null;

            body.innerHTML = `
                <div class="msh-radio-status">
                    <div class="msh-radio-indicator" style="border-color:${connColor}">
                        <div class="msh-radio-dot-big" style="background:${connColor};box-shadow:0 0 12px ${connColor}88;"></div>
                        <div class="msh-radio-status-text" style="color:${connColor}">${connStatus}</div>
                    </div>
                </div>
                ${connected ? `
                <div class="msh-section-label">DEVICE INFO</div>
                <div class="msh-config-grid">
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Node ID</span><span class="msh-cfg-val">${_esc(di.node_id || di.nodeId || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Long Name</span><span class="msh-cfg-val">${_esc(di.long_name || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Short Name</span><span class="msh-cfg-val">${_esc(di.short_name || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Hardware</span><span class="msh-cfg-val">${_esc(di.hw_model || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Firmware</span><span class="msh-cfg-val">${_esc(di.firmware_version || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Role</span><span class="msh-cfg-val">${_esc(di.role || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Region</span><span class="msh-cfg-val">${_esc(di.region || '--')}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Modem Preset</span><span class="msh-cfg-val${_isModemPresetRecommended(di.modem_preset) ? '' : ' msh-cfg-warn'}">${_esc(di.modem_preset || '--')}</span></div>
                    ${!_isModemPresetRecommended(di.modem_preset) && di.modem_preset && di.modem_preset !== '--' ? '<div class="msh-preset-warning">Bay Area Meshtastic recommends MEDIUM_FAST for this region</div>' : ''}
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">TX Power</span><span class="msh-cfg-val">${di.tx_power != null ? di.tx_power + ' dBm' : '--'}</span></div>
                    <div class="msh-cfg-row"><span class="msh-cfg-lbl">Channels</span><span class="msh-cfg-val">${di.num_channels || channels.length || '--'}</span></div>
                </div>
                <div class="msh-section-label" style="margin-top:10px">MESH OVERVIEW</div>
                <div class="msh-stats">
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#00f0ff">${nodes.length}</div><div class="msh-stat-lbl">NODES</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#05ffa1">${withGps}</div><div class="msh-stat-lbl">WITH GPS</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#fcee0a">${avgBat != null ? avgBat + '%' : '--'}</div><div class="msh-stat-lbl">AVG BATTERY</div></div>
                    <div class="msh-stat"><div class="msh-stat-val" style="color:#ff2a6d">${avgUtil != null ? avgUtil + '%' : '--'}</div><div class="msh-stat-lbl">CH UTIL</div></div>
                </div>
                <div class="msh-radio-actions">
                    <button class="msh-btn" data-action="refresh-all">REFRESH</button>
                    <button class="msh-btn msh-btn-warn" data-action="reboot">REBOOT DEVICE</button>
                </div>
                ` : `
                <div class="msh-radio-ports">
                    <div class="msh-section-label">AVAILABLE PORTS</div>
                    ${ports.length === 0 ? '<div class="msh-empty" style="padding:12px 10px">No serial ports detected. Plug in a Meshtastic radio via USB.</div>' :
                    `<div class="msh-port-list">
                        ${ports.map(p => {
                            const port = typeof p === 'string' ? p : (p.port || '');
                            const desc = typeof p === 'object' ? (p.description || p.manufacturer || '') : '';
                            return `<div class="msh-port-row" data-port="${_esc(port)}">
                                <span class="msh-port-name">${_esc(port)}</span>
                                <span class="msh-port-desc">${_esc(desc)}</span>
                                <button class="msh-btn msh-btn-connect msh-btn-sm" data-action="connect-port" data-port="${_esc(port)}">CONNECT</button>
                            </div>`;
                        }).join('')}
                    </div>`}
                    <div style="padding:8px 10px">
                        <button class="msh-btn" data-action="scan-ports">SCAN FOR RADIOS</button>
                    </div>
                </div>
                `}
            `;

            // Wire radio tab actions
            body.querySelectorAll('[data-action="connect-port"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const port = btn.dataset.port;
                    btn.disabled = true;
                    btn.textContent = 'CONNECTING...';
                    try {
                        const cr = await fetch(API + '/connect', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ transport: 'serial', port, timeout: 60 }),
                        });
                        if (cr.ok) {
                            const cd = await cr.json();
                            updateConnection(cd);
                            fetchAll();
                            fetchDeviceInfo();
                            fetchChannels();
                            fetchModuleConfig();
                            fetchFirmware();
                        }
                    } catch (_) { /* ok */ }
                    btn.disabled = false;
                    btn.textContent = 'CONNECT';
                });
            });
            body.querySelector('[data-action="scan-ports"]')?.addEventListener('click', async () => {
                await fetchPorts();
                renderRadio();
            });
            body.querySelector('[data-action="refresh-all"]')?.addEventListener('click', () => {
                fetchAll();
                fetchDeviceInfo();
                fetchChannels();
                fetchModuleConfig();
            });
            body.querySelector('[data-action="reboot"]')?.addEventListener('click', async () => {
                if (confirm('Reboot the Meshtastic device?') === false) return;
                try {
                    await fetch(API + '/device/reboot', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ delay: 5 }),
                    });
                } catch (_) { /* ok */ }
                EventBus.emit('toast:show', { message: 'Reboot command sent (5s delay)', type: 'info' });
            });
        }

        // =====================================================================
        //  MESSAGES TAB
        // =====================================================================
        function renderMessages() {
            const now = Math.floor(Date.now() / 1000);
            const SYSTEM_TYPES = ['position', 'telemetry', 'nodeinfo', 'routing', 'admin'];
            // Filter messages by selected channel
            let filtered = messages.filter(m => {
                if (m.channel == null) return selectedChannel === 0;
                return m.channel === selectedChannel;
            });
            // Apply chat-only filter (hide system/position/telemetry packets)
            if (chatOnlyFilter) {
                filtered = filtered.filter(m => !m.type || m.type === 'text');
            }
            const visible = filtered.slice(-80);

            // Channel selector options
            const chOptions = [];
            for (let i = 0; i < Math.max(channels.length, 1); i++) {
                const ch = channels[i];
                const name = ch ? (ch.name || (i === 0 ? 'Primary' : `Ch ${i}`)) : (i === 0 ? 'Primary' : `Ch ${i}`);
                chOptions.push(`<option value="${i}"${i === selectedChannel ? ' selected' : ''}>${_esc(name)}</option>`);
            }
            // Add DM option
            chOptions.push(`<option value="-1"${selectedChannel === -1 ? ' selected' : ''}>Direct Messages</option>`);

            body.innerHTML = `
                <div class="msh-msg-header">
                    <select class="msh-channel-select" data-bind="channel-select">${chOptions.join('')}</select>
                    <button class="msh-btn msh-btn-sm msh-msg-filter-btn${chatOnlyFilter ? ' msh-msg-filter-active' : ''}" data-action="toggle-msg-filter">${chatOnlyFilter ? 'CHAT ONLY' : 'ALL MESSAGES'}</button>
                    <span class="msh-msg-count">${filtered.length} message${filtered.length !== 1 ? 's' : ''}</span>
                </div>
                <div class="msh-chat-log" data-bind="chat-log">
                    ${visible.length === 0
                        ? '<div class="msh-empty" style="padding:30px;text-align:center">No messages on this channel</div>'
                        : visible.map(m => {
                            const isSystem = m.type && SYSTEM_TYPES.includes(m.type);
                            const sender = _esc(m.from_short || m.from_name || m.from || 'Unknown');
                            const text = _esc(m.text || '');
                            const time = m.timestamp
                                ? new Date(m.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                                : '';
                            const self = m.is_self;
                            const ack = m.ack === true ? 'msh-msg-acked' : (m.ack === false ? 'msh-msg-nack' : '');
                            const hops = m.hop_limit != null ? `<span class="msh-msg-hops">${m.hop_limit}h</span>` : '';
                            const typeBadge = isSystem ? `<span class="msh-msg-type-badge">${_esc(m.type.toUpperCase())}</span>` : '';
                            return `<div class="msh-msg${self ? ' msh-msg-self' : ''} ${ack}${isSystem ? ' msh-msg-system' : ''}">
                                <div class="msh-msg-meta">
                                    <span class="msh-msg-from">${sender}</span>
                                    ${typeBadge}
                                    ${hops}
                                    <span class="msh-msg-time">${time}</span>
                                    ${self && m.ack === true ? '<span class="msh-msg-delivery" title="Delivered">OK</span>' : ''}
                                    ${self && m.ack === false ? '<span class="msh-msg-delivery msh-msg-delivery-fail" title="Not delivered">FAIL</span>' : ''}
                                </div>
                                <div class="msh-msg-text">${text}</div>
                            </div>`;
                        }).join('')}
                </div>
                <div class="msh-chat-input">
                    <input type="text" class="msh-input" data-bind="chat-input" maxlength="${MSG_CHAR_LIMIT}" placeholder="${connected ? 'Type a message...' : 'Connect a radio to send'}" autocomplete="off" ${connected ? '' : 'disabled'} />
                    <span class="msh-char-count" data-bind="char-count">${MSG_CHAR_LIMIT}</span>
                    <button class="msh-btn msh-btn-send" data-action="send" ${connected ? '' : 'disabled'}>SEND</button>
                </div>
            `;

            // Scroll chat to bottom
            const log = body.querySelector('[data-bind="chat-log"]');
            if (log) log.scrollTop = log.scrollHeight;

            // Channel selector
            const chSel = body.querySelector('[data-bind="channel-select"]');
            if (chSel) {
                chSel.addEventListener('change', () => {
                    selectedChannel = parseInt(chSel.value, 10);
                    renderMessages();
                });
            }

            // Message filter toggle
            body.querySelector('[data-action="toggle-msg-filter"]')?.addEventListener('click', () => {
                chatOnlyFilter = !chatOnlyFilter;
                renderMessages();
            });

            // Wire send
            const input = body.querySelector('[data-bind="chat-input"]');
            const sendBtn = body.querySelector('[data-action="send"]');
            const charCount = body.querySelector('[data-bind="char-count"]');

            if (input) {
                input.focus();
                input.addEventListener('input', () => {
                    const rem = MSG_CHAR_LIMIT - input.value.length;
                    if (charCount) {
                        charCount.textContent = rem;
                        charCount.style.color = rem < 20 ? '#ff2a6d' : '#888';
                    }
                });
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' && e.shiftKey === false) {
                        e.preventDefault();
                        e.stopPropagation();
                        doSend(input);
                    }
                });
            }
            if (sendBtn) sendBtn.addEventListener('click', () => doSend(input));
        }

        async function doSend(input) {
            if (input === null || input === undefined) return;
            const text = input.value.trim();
            if (text === '') return;
            input.value = '';
            const payload = { text };
            if (selectedChannel >= 0) payload.channel = selectedChannel;
            messages.push({
                from: 'You', from_short: 'You', text,
                timestamp: Math.floor(Date.now() / 1000),
                is_self: true, channel: selectedChannel >= 0 ? selectedChannel : null,
            });
            renderMessages();
            try {
                await fetch(API + '/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
            } catch (_) { /* ok */ }
        }

        // =====================================================================
        //  NODES TAB
        // =====================================================================
        function renderNodes() {
            const sorted = [...nodes].sort((a, b) => {
                let va = a[nodeSortKey], vb = b[nodeSortKey];
                if (typeof va === 'string') return (va || '').localeCompare(vb || '') * nodeSortDir;
                if (va == null) va = -Infinity;
                if (vb == null) vb = -Infinity;
                return (va - vb) * nodeSortDir;
            });

            const now = Math.floor(Date.now() / 1000);
            const headerCells = NODE_COLS.map(c =>
                `<th class="msh-th" data-sort="${c.key}" style="width:${c.width};text-align:${c.align || 'left'}">${c.label}${nodeSortKey === c.key ? (nodeSortDir < 0 ? ' \u25BC' : ' \u25B2') : ''}</th>`
            ).join('');

            const rows = sorted.map(n => {
                const age = _age(now - (n.last_heard || 0));
                const bat = n.battery != null ? Math.round(n.battery) + '%' : '';
                const batColor = n.battery != null ? (n.battery > 50 ? '#05ffa1' : n.battery > 20 ? '#fcee0a' : '#ff2a6d') : '#888';
                const snr = n.snr != null ? n.snr.toFixed(1) : '';
                const snrColor = n.snr != null ? (n.snr > 5 ? '#05ffa1' : n.snr > 0 ? '#fcee0a' : '#ff2a6d') : '#888';
                const hops = n.hopsAway != null ? String(n.hopsAway) : '';
                const dist = n.distance != null ? _formatDist(n.distance) : '';
                return `<tr class="msh-tr" data-node-id="${_esc(n.node_id || n.num || '')}">
                    <td class="msh-td">${_esc(n.short_name || '')}</td>
                    <td class="msh-td msh-td-long">${_esc(n.long_name || '')}</td>
                    <td class="msh-td msh-td-hw">${_esc(n.hw_model || '')}</td>
                    <td class="msh-td" style="text-align:right;color:${snrColor}">${snr}</td>
                    <td class="msh-td" style="text-align:right;color:${batColor}">${bat}</td>
                    <td class="msh-td" style="text-align:right">${age}</td>
                    <td class="msh-td" style="text-align:right">${hops}</td>
                    <td class="msh-td" style="text-align:right">${dist}</td>
                </tr>`;
            }).join('');

            const online = nodes.filter(n => {
                if (n.last_heard == null) return false;
                return (now - n.last_heard) < 900; // 15 min
            }).length;

            body.innerHTML = `
                <div class="msh-node-header">
                    <span class="msh-node-count">${nodes.length} node${nodes.length !== 1 ? 's' : ''}</span>
                    <span class="msh-node-online" style="color:#05ffa1">${online} online</span>
                </div>
                <div style="flex:1;overflow:auto;min-height:0;">
                    <table class="msh-table">
                        <thead><tr>${headerCells}</tr></thead>
                        <tbody>${rows || '<tr><td colspan="8" class="msh-empty" style="text-align:center;padding:30px">No nodes discovered</td></tr>'}</tbody>
                    </table>
                </div>
            `;

            body.querySelector('thead')?.addEventListener('click', (e) => {
                const th = e.target.closest('[data-sort]');
                if (th === null) return;
                if (nodeSortKey === th.dataset.sort) nodeSortDir *= -1;
                else { nodeSortKey = th.dataset.sort; nodeSortDir = -1; }
                renderNodes();
            });
        }

        // =====================================================================
        //  CHANNELS TAB
        // =====================================================================
        function renderChannels() {
            // Always show 8 channel slots
            const slots = [];
            for (let i = 0; i < 8; i++) {
                slots.push(channels[i] || { index: i, name: '', role: 'DISABLED', psk: null });
            }

            body.innerHTML = `
                <div class="msh-section-label">CHANNEL SLOTS (8)</div>
                <div class="msh-channel-list">
                    ${slots.map((ch, i) => {
                        const name = ch.name || (i === 0 ? 'Default' : '');
                        const role = _normalizeRole(ch.role, i);
                        const roleColor = role === 'PRIMARY' ? '#05ffa1' : (role === 'SECONDARY' ? '#00f0ff' : '#555');
                        const hasPsk = ch.psk && ch.psk !== '' && ch.psk !== 'AQ==';
                        const pskLabel = hasPsk ? 'CUSTOM PSK' : (role !== 'DISABLED' ? 'DEFAULT PSK' : '--');
                        const pskColor = hasPsk ? '#fcee0a' : '#666';
                        const isEditing = channelEditIndex === i;

                        if (isEditing) {
                            return `<div class="msh-channel-slot msh-channel-editing">
                                <div class="msh-channel-slot-header">
                                    <span class="msh-channel-idx">${i}</span>
                                    <span class="msh-channel-role" style="color:${roleColor}">${role}</span>
                                </div>
                                <div class="msh-channel-edit-form">
                                    <label class="msh-edit-label">Name</label>
                                    <input class="msh-input msh-edit-input" data-field="ch-name" value="${_esc(ch.name || '')}" placeholder="Channel name" maxlength="11" />
                                    <label class="msh-edit-label">PSK (base64)</label>
                                    <input class="msh-input msh-edit-input" data-field="ch-psk" value="${_esc(ch.psk || '')}" placeholder="Leave blank for default" />
                                    <label class="msh-edit-label">Role</label>
                                    <select class="msh-input msh-edit-input" data-field="ch-role">
                                        ${i === 0 ? '<option value="PRIMARY" selected>PRIMARY</option>' : `
                                        <option value="SECONDARY"${role === 'SECONDARY' ? ' selected' : ''}>SECONDARY</option>
                                        <option value="DISABLED"${role === 'DISABLED' ? ' selected' : ''}>DISABLED</option>
                                        `}
                                    </select>
                                    <div class="msh-channel-edit-actions">
                                        <button class="msh-btn msh-btn-save" data-action="save-channel" data-idx="${i}">SAVE</button>
                                        <button class="msh-btn" data-action="cancel-channel-edit">CANCEL</button>
                                    </div>
                                </div>
                            </div>`;
                        }

                        return `<div class="msh-channel-slot${role === 'DISABLED' ? ' msh-channel-disabled' : ''}">
                            <div class="msh-channel-slot-header">
                                <span class="msh-channel-idx">${i}</span>
                                <span class="msh-channel-name">${_esc(name) || '<span style="color:#555">unnamed</span>'}</span>
                                <span class="msh-channel-role" style="color:${roleColor}">${role}</span>
                            </div>
                            <div class="msh-channel-slot-detail">
                                <span class="msh-channel-psk" style="color:${pskColor}">${pskLabel}</span>
                                <span style="flex:1"></span>
                                ${connected ? `<button class="msh-btn msh-btn-sm" data-action="edit-channel" data-idx="${i}">EDIT</button>` : ''}
                            </div>
                        </div>`;
                    }).join('')}
                </div>
                ${connected ? `
                <div class="msh-channel-actions">
                    <button class="msh-btn" data-action="share-url">SHARE CHANNEL URL</button>
                    <button class="msh-btn" data-action="refresh-channels">REFRESH</button>
                </div>` : ''}
            `;

            // Wire edit buttons
            body.querySelectorAll('[data-action="edit-channel"]').forEach(btn => {
                btn.addEventListener('click', () => {
                    channelEditIndex = parseInt(btn.dataset.idx, 10);
                    renderChannels();
                });
            });
            body.querySelector('[data-action="cancel-channel-edit"]')?.addEventListener('click', () => {
                channelEditIndex = -1;
                renderChannels();
            });
            body.querySelector('[data-action="save-channel"]')?.addEventListener('click', async (e) => {
                const idx = parseInt(e.target.dataset.idx, 10);
                const nameInput = body.querySelector('[data-field="ch-name"]');
                const pskInput = body.querySelector('[data-field="ch-psk"]');
                const roleSelect = body.querySelector('[data-field="ch-role"]');
                const payload = {
                    channel_index: idx,
                    name: nameInput ? nameInput.value : '',
                    psk: pskInput ? pskInput.value : '',
                    role: roleSelect ? roleSelect.value : 'DISABLED',
                };
                e.target.disabled = true;
                e.target.textContent = 'SAVING...';
                try {
                    await fetch(API + '/device/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ channel: payload }),
                    });
                    EventBus.emit('toast:show', { message: `Channel ${idx} saved`, type: 'success' });
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Failed to save channel', type: 'error' });
                }
                channelEditIndex = -1;
                await fetchChannels();
                renderChannels();
            });
            body.querySelector('[data-action="share-url"]')?.addEventListener('click', async () => {
                try {
                    const r = await fetch(API + '/device/channel-url');
                    if (r.ok) {
                        const d = await r.json();
                        const url = d.url || d.channel_url || '';
                        if (url) {
                            if (navigator.clipboard) {
                                await navigator.clipboard.writeText(url);
                                EventBus.emit('toast:show', { message: 'Channel URL copied to clipboard', type: 'success' });
                            } else {
                                prompt('Channel URL:', url);
                            }
                        }
                    }
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Failed to get channel URL', type: 'error' });
                }
            });
            body.querySelector('[data-action="refresh-channels"]')?.addEventListener('click', async () => {
                await fetchChannels();
                renderChannels();
            });
        }

        // =====================================================================
        //  CONFIG TAB
        // =====================================================================
        function renderConfig() {
            const di = deviceInfo;

            body.innerHTML = `
                <div class="msh-config-scroll">
                    <div class="msh-section-label">USER</div>
                    <div class="msh-config-grid">
                        ${_cfgInput('Long Name', 'cfg-long-name', di.long_name || '', 'text', 'Your node name')}
                        ${_cfgInput('Short Name', 'cfg-short-name', di.short_name || '', 'text', '4 chars max', 4)}
                        ${_cfgSelect('Role', 'cfg-role', di.role || 'CLIENT', DEVICE_ROLES)}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">LORA</div>
                    <div class="msh-config-grid">
                        ${_cfgSelect('Region', 'cfg-region', di.region || 'UNSET', REGIONS)}
                        ${_cfgSelect('Modem Preset', 'cfg-modem-preset', di.modem_preset || 'LONG_FAST', MODEM_PRESETS)}
                        ${!_isModemPresetRecommended(di.modem_preset) ? '<div class="msh-preset-warning" style="padding:2px 0 4px 108px">Bay Area Meshtastic recommends MEDIUM_FAST for this region</div>' : ''}
                        ${_cfgInput('TX Power (dBm)', 'cfg-tx-power', di.tx_power != null ? String(di.tx_power) : '', 'number', '0-30')}
                        ${_cfgInput('Hop Limit', 'cfg-hop-limit', di.hop_limit != null ? String(di.hop_limit) : '3', 'number', '1-7')}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">POSITION</div>
                    <div class="msh-config-grid">
                        ${_cfgToggle('Fixed Position', 'cfg-fixed-pos', di.fixed_position || false)}
                        ${_cfgInput('Latitude', 'cfg-lat', di.latitude != null ? String(di.latitude) : '', 'number', 'Decimal degrees')}
                        ${_cfgInput('Longitude', 'cfg-lon', di.longitude != null ? String(di.longitude) : '', 'number', 'Decimal degrees')}
                        ${_cfgInput('Altitude (m)', 'cfg-alt', di.altitude != null ? String(di.altitude) : '', 'number', 'Meters')}
                        ${_cfgInput('GPS Update Interval (s)', 'cfg-gps-interval', di.gps_update_interval != null ? String(di.gps_update_interval) : '', 'number', 'Seconds')}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">DISPLAY</div>
                    <div class="msh-config-grid">
                        ${_cfgInput('Screen On (s)', 'cfg-screen-on', di.screen_on_secs != null ? String(di.screen_on_secs) : '', 'number', 'Seconds')}
                        ${_cfgToggle('Flip Screen', 'cfg-flip-screen', di.flip_screen || false)}
                        ${_cfgToggle('Compass North Top', 'cfg-compass', di.compass_north_top || false)}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">POWER</div>
                    <div class="msh-config-grid">
                        ${_cfgToggle('Power Saving', 'cfg-power-saving', di.is_power_saving || false)}
                        ${_cfgInput('Shutdown After (s)', 'cfg-shutdown', di.shutdown_on_power_loss != null ? String(di.shutdown_on_power_loss) : '', 'number', 'Seconds, 0=off')}
                        ${_cfgInput('Min Wake (s)', 'cfg-min-wake', di.min_wake_secs != null ? String(di.min_wake_secs) : '', 'number', 'Seconds')}
                        ${_cfgInput('SDS (s)', 'cfg-sds', di.sds_secs != null ? String(di.sds_secs) : '', 'number', 'Super Deep Sleep seconds')}
                        ${_cfgInput('LS (s)', 'cfg-ls', di.ls_secs != null ? String(di.ls_secs) : '', 'number', 'Light Sleep seconds')}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">BLUETOOTH</div>
                    <div class="msh-config-grid">
                        ${_cfgToggle('BLE Enabled', 'cfg-ble-enabled', di.bluetooth_enabled !== false)}
                        ${_cfgInput('BLE PIN', 'cfg-ble-pin', di.bluetooth_pin != null ? String(di.bluetooth_pin) : '123456', 'number', '6 digits')}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">NETWORK / WIFI</div>
                    <div class="msh-config-grid">
                        ${_cfgToggle('WiFi Enabled', 'cfg-wifi-enabled', di.wifi_enabled || false)}
                        ${_cfgInput('WiFi SSID', 'cfg-wifi-ssid', di.wifi_ssid || '', 'text', 'Network name')}
                        ${_cfgInput('WiFi Password', 'cfg-wifi-pass', di.wifi_password || '', 'password', 'Password')}
                        ${_cfgInput('NTP Server', 'cfg-ntp', di.ntp_server || '', 'text', 'e.g. 0.pool.ntp.org')}
                    </div>

                    <div class="msh-section-label" style="margin-top:12px">SECURITY</div>
                    <div class="msh-config-grid">
                        ${_cfgToggle('Admin Channel Enabled', 'cfg-admin-ch', di.admin_channel_enabled || false)}
                        ${_cfgToggle('Managed Mode', 'cfg-managed', di.is_managed || false)}
                    </div>

                    <div class="msh-config-save-bar">
                        <button class="msh-btn msh-btn-save msh-btn-lg" data-action="save-config">SAVE ALL SETTINGS</button>
                        <button class="msh-btn" data-action="refresh-config">REFRESH</button>
                    </div>
                </div>
            `;

            body.querySelector('[data-action="save-config"]')?.addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'SAVING...';
                const payload = _gatherConfigValues(body);
                try {
                    const r = await fetch(API + '/device/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload),
                    });
                    if (r.ok) {
                        EventBus.emit('toast:show', { message: 'Config saved to device', type: 'success' });
                    } else {
                        EventBus.emit('toast:show', { message: 'Config save failed', type: 'error' });
                    }
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Config save failed', type: 'error' });
                }
                btn.disabled = false;
                btn.textContent = 'SAVE ALL SETTINGS';
                await fetchDeviceInfo();
            });
            body.querySelector('[data-action="refresh-config"]')?.addEventListener('click', async () => {
                await fetchDeviceInfo();
                renderConfig();
            });
        }

        function _gatherConfigValues(container) {
            const val = (id) => {
                const el = container.querySelector(`[data-cfg="${id}"]`);
                if (el === null) return undefined;
                if (el.type === 'checkbox') return el.checked;
                if (el.type === 'number') return el.value !== '' ? Number(el.value) : undefined;
                return el.value || undefined;
            };
            return {
                long_name: val('cfg-long-name'),
                short_name: val('cfg-short-name'),
                role: val('cfg-role'),
                region: val('cfg-region'),
                modem_preset: val('cfg-modem-preset'),
                tx_power: val('cfg-tx-power'),
                hop_limit: val('cfg-hop-limit'),
                fixed_position: val('cfg-fixed-pos'),
                latitude: val('cfg-lat'),
                longitude: val('cfg-lon'),
                altitude: val('cfg-alt'),
                gps_update_interval: val('cfg-gps-interval'),
                screen_on_secs: val('cfg-screen-on'),
                flip_screen: val('cfg-flip-screen'),
                compass_north_top: val('cfg-compass'),
                is_power_saving: val('cfg-power-saving'),
                shutdown_on_power_loss: val('cfg-shutdown'),
                min_wake_secs: val('cfg-min-wake'),
                sds_secs: val('cfg-sds'),
                ls_secs: val('cfg-ls'),
                bluetooth_enabled: val('cfg-ble-enabled'),
                bluetooth_pin: val('cfg-ble-pin'),
                wifi_enabled: val('cfg-wifi-enabled'),
                wifi_ssid: val('cfg-wifi-ssid'),
                wifi_password: val('cfg-wifi-pass'),
                ntp_server: val('cfg-ntp'),
                admin_channel_enabled: val('cfg-admin-ch'),
                is_managed: val('cfg-managed'),
            };
        }

        // =====================================================================
        //  MODULES TAB
        // =====================================================================
        function renderModules() {
            const mc = moduleConfig || {};

            body.innerHTML = `
                <div class="msh-config-scroll">
                    ${_moduleSection('MQTT', 'mqtt', [
                        { type: 'toggle', key: 'mqtt_enabled', label: 'Enabled', val: mc.mqtt_enabled || false },
                        { type: 'text', key: 'mqtt_address', label: 'Server Address', val: mc.mqtt_address || '', placeholder: 'mqtt.meshtastic.org' },
                        { type: 'text', key: 'mqtt_username', label: 'Username', val: mc.mqtt_username || '' },
                        { type: 'password', key: 'mqtt_password', label: 'Password', val: mc.mqtt_password || '' },
                        { type: 'text', key: 'mqtt_root', label: 'Root Topic', val: mc.mqtt_root || 'msh', placeholder: 'msh' },
                        { type: 'toggle', key: 'mqtt_encryption', label: 'Encryption Enabled', val: mc.mqtt_encryption !== false },
                        { type: 'toggle', key: 'mqtt_json', label: 'JSON Enabled', val: mc.mqtt_json || false },
                        { type: 'toggle', key: 'mqtt_tls', label: 'TLS Enabled', val: mc.mqtt_tls || false },
                        { type: 'toggle', key: 'mqtt_proxy_to_client', label: 'Proxy to Client', val: mc.mqtt_proxy_to_client || false },
                        { type: 'toggle', key: 'mqtt_map_reporting', label: 'Map Reporting', val: mc.mqtt_map_reporting || false },
                    ])}

                    ${_moduleSection('TELEMETRY', 'telemetry', [
                        { type: 'number', key: 'telem_device_interval', label: 'Device Update (s)', val: mc.telem_device_interval || '', placeholder: '900' },
                        { type: 'number', key: 'telem_env_interval', label: 'Environment Update (s)', val: mc.telem_env_interval || '', placeholder: '900' },
                        { type: 'number', key: 'telem_air_interval', label: 'Air Quality Update (s)', val: mc.telem_air_interval || '', placeholder: '900' },
                        { type: 'number', key: 'telem_power_interval', label: 'Power Update (s)', val: mc.telem_power_interval || '', placeholder: '900' },
                        { type: 'toggle', key: 'telem_display_on_screen', label: 'Show on Screen', val: mc.telem_display_on_screen || false },
                    ])}

                    ${_moduleSection('SERIAL', 'serial', [
                        { type: 'toggle', key: 'serial_enabled', label: 'Enabled', val: mc.serial_enabled || false },
                        { type: 'toggle', key: 'serial_echo', label: 'Echo', val: mc.serial_echo || false },
                        { type: 'number', key: 'serial_baud', label: 'Baud Rate', val: mc.serial_baud || '', placeholder: '38400' },
                        { type: 'number', key: 'serial_timeout', label: 'Timeout (ms)', val: mc.serial_timeout || '', placeholder: '250' },
                        { type: 'select', key: 'serial_mode', label: 'Mode', val: mc.serial_mode || 'DEFAULT', options: ['DEFAULT', 'SIMPLE', 'PROTO', 'TEXTMSG', 'NMEA', 'CALTOPO'] },
                    ])}

                    ${_moduleSection('RANGE TEST', 'rangetest', [
                        { type: 'toggle', key: 'range_test_enabled', label: 'Enabled', val: mc.range_test_enabled || false },
                        { type: 'number', key: 'range_test_sender', label: 'Send Interval (s)', val: mc.range_test_sender || '', placeholder: '0 = disabled' },
                        { type: 'toggle', key: 'range_test_save', label: 'Save to CSV', val: mc.range_test_save || false },
                    ])}

                    ${_moduleSection('STORE & FORWARD', 'storeforward', [
                        { type: 'toggle', key: 'store_forward_enabled', label: 'Enabled', val: mc.store_forward_enabled || false },
                        { type: 'toggle', key: 'store_forward_heartbeat', label: 'Heartbeat', val: mc.store_forward_heartbeat || false },
                        { type: 'number', key: 'store_forward_records', label: 'Max Records', val: mc.store_forward_records || '', placeholder: '0 = auto' },
                        { type: 'number', key: 'store_forward_history_return_max', label: 'History Return Max', val: mc.store_forward_history_return_max || '', placeholder: '25' },
                        { type: 'number', key: 'store_forward_history_return_window', label: 'History Window (s)', val: mc.store_forward_history_return_window || '', placeholder: '7200' },
                    ])}

                    ${_moduleSection('DETECTION SENSOR', 'detection', [
                        { type: 'toggle', key: 'detection_enabled', label: 'Enabled', val: mc.detection_enabled || false },
                        { type: 'text', key: 'detection_name', label: 'Name', val: mc.detection_name || '', placeholder: 'Sensor name' },
                        { type: 'number', key: 'detection_minimum_broadcast_secs', label: 'Min Broadcast (s)', val: mc.detection_minimum_broadcast_secs || '', placeholder: '45' },
                        { type: 'number', key: 'detection_state_broadcast_secs', label: 'State Broadcast (s)', val: mc.detection_state_broadcast_secs || '', placeholder: '3600' },
                        { type: 'toggle', key: 'detection_send_bell', label: 'Send Bell Char', val: mc.detection_send_bell || false },
                        { type: 'number', key: 'detection_monitor_pin', label: 'Monitor Pin (GPIO)', val: mc.detection_monitor_pin || '', placeholder: 'GPIO pin number' },
                    ])}

                    ${_moduleSection('CANNED MESSAGE', 'canned', [
                        { type: 'toggle', key: 'canned_enabled', label: 'Enabled', val: mc.canned_enabled || false },
                        { type: 'text', key: 'canned_messages', label: 'Messages (| separated)', val: mc.canned_messages || '', placeholder: 'Msg1|Msg2|Msg3' },
                        { type: 'toggle', key: 'canned_rotary1', label: 'Rotary Encoder', val: mc.canned_rotary1 || false },
                        { type: 'toggle', key: 'canned_updown1', label: 'Up/Down Buttons', val: mc.canned_updown1 || false },
                        { type: 'number', key: 'canned_input_pin_a', label: 'Input Pin A', val: mc.canned_input_pin_a || '', placeholder: 'GPIO' },
                        { type: 'number', key: 'canned_input_pin_b', label: 'Input Pin B', val: mc.canned_input_pin_b || '', placeholder: 'GPIO' },
                        { type: 'number', key: 'canned_input_pin_press', label: 'Input Pin Press', val: mc.canned_input_pin_press || '', placeholder: 'GPIO' },
                    ])}

                    ${_moduleSection('NEIGHBOR INFO', 'neighborinfo', [
                        { type: 'toggle', key: 'neighbor_info_enabled', label: 'Enabled', val: mc.neighbor_info_enabled || false },
                        { type: 'number', key: 'neighbor_info_interval', label: 'Update Interval (s)', val: mc.neighbor_info_interval || '', placeholder: '900' },
                    ])}

                    ${_moduleSection('PAXCOUNTER', 'paxcounter', [
                        { type: 'toggle', key: 'paxcounter_enabled', label: 'Enabled', val: mc.paxcounter_enabled || false },
                        { type: 'number', key: 'paxcounter_update_interval', label: 'Update Interval (s)', val: mc.paxcounter_update_interval || '', placeholder: '900' },
                    ])}

                    <div class="msh-config-save-bar">
                        <button class="msh-btn msh-btn-save msh-btn-lg" data-action="save-modules">SAVE ALL MODULES</button>
                        <button class="msh-btn" data-action="refresh-modules">REFRESH</button>
                    </div>
                </div>
            `;

            // Wire collapsible sections
            body.querySelectorAll('.msh-module-header').forEach(hdr => {
                hdr.addEventListener('click', () => {
                    const section = hdr.closest('.msh-module-section');
                    if (section) section.classList.toggle('msh-module-collapsed');
                });
            });

            body.querySelector('[data-action="save-modules"]')?.addEventListener('click', async (e) => {
                const btn = e.target;
                btn.disabled = true;
                btn.textContent = 'SAVING...';
                const payload = _gatherModuleValues(body);
                try {
                    const r = await fetch(API + '/device/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ modules: payload }),
                    });
                    if (r.ok) {
                        EventBus.emit('toast:show', { message: 'Module config saved', type: 'success' });
                    } else {
                        EventBus.emit('toast:show', { message: 'Module save failed', type: 'error' });
                    }
                } catch (_) {
                    EventBus.emit('toast:show', { message: 'Module save failed', type: 'error' });
                }
                btn.disabled = false;
                btn.textContent = 'SAVE ALL MODULES';
                await fetchModuleConfig();
            });
            body.querySelector('[data-action="refresh-modules"]')?.addEventListener('click', async () => {
                await fetchModuleConfig();
                renderModules();
            });
        }

        function _gatherModuleValues(container) {
            const result = {};
            container.querySelectorAll('[data-mod]').forEach(el => {
                const key = el.dataset.mod;
                if (el.type === 'checkbox') {
                    result[key] = el.checked;
                } else if (el.type === 'number') {
                    result[key] = el.value !== '' ? Number(el.value) : undefined;
                } else {
                    result[key] = el.value || undefined;
                }
            });
            return result;
        }

        // ── Config/Module HTML helpers ────────────────────────────
        function _cfgInput(label, id, value, type, placeholder, maxlength) {
            const ml = maxlength ? ` maxlength="${maxlength}"` : '';
            return `<div class="msh-cfg-edit-row">
                <label class="msh-cfg-lbl">${label}</label>
                <input class="msh-input msh-cfg-input" data-cfg="${id}" type="${type || 'text'}" value="${_esc(String(value))}" placeholder="${_esc(placeholder || '')}"${ml} />
            </div>`;
        }

        function _cfgSelect(label, id, value, options) {
            const opts = options.map(o =>
                `<option value="${_esc(o)}"${o === value ? ' selected' : ''}>${_esc(o)}</option>`
            ).join('');
            return `<div class="msh-cfg-edit-row">
                <label class="msh-cfg-lbl">${label}</label>
                <select class="msh-input msh-cfg-input" data-cfg="${id}">${opts}</select>
            </div>`;
        }

        function _cfgToggle(label, id, value) {
            return `<div class="msh-cfg-edit-row">
                <label class="msh-cfg-lbl">${label}</label>
                <label class="msh-toggle">
                    <input type="checkbox" data-cfg="${id}" ${value ? 'checked' : ''} />
                    <span class="msh-toggle-slider"></span>
                </label>
            </div>`;
        }

        function _moduleSection(title, sectionId, fields) {
            const fieldsHtml = fields.map(f => {
                if (f.type === 'toggle') {
                    return `<div class="msh-cfg-edit-row">
                        <label class="msh-cfg-lbl">${f.label}</label>
                        <label class="msh-toggle">
                            <input type="checkbox" data-mod="${f.key}" ${f.val ? 'checked' : ''} />
                            <span class="msh-toggle-slider"></span>
                        </label>
                    </div>`;
                }
                if (f.type === 'select') {
                    const opts = (f.options || []).map(o =>
                        `<option value="${_esc(o)}"${o === f.val ? ' selected' : ''}>${_esc(o)}</option>`
                    ).join('');
                    return `<div class="msh-cfg-edit-row">
                        <label class="msh-cfg-lbl">${f.label}</label>
                        <select class="msh-input msh-cfg-input" data-mod="${f.key}">${opts}</select>
                    </div>`;
                }
                return `<div class="msh-cfg-edit-row">
                    <label class="msh-cfg-lbl">${f.label}</label>
                    <input class="msh-input msh-cfg-input" data-mod="${f.key}" type="${f.type || 'text'}" value="${_esc(String(f.val))}" placeholder="${_esc(f.placeholder || '')}" />
                </div>`;
            }).join('');

            return `<div class="msh-module-section" data-section="${sectionId}">
                <div class="msh-module-header">
                    <span class="msh-module-arrow">\u25B6</span>
                    <span class="msh-module-title">${title}</span>
                </div>
                <div class="msh-module-body">
                    <div class="msh-config-grid">${fieldsHtml}</div>
                </div>
            </div>`;
        }

        // ── EventBus ────────────────────────────────────────────
        const unsubs = [
            EventBus.on('mesh:text', (d) => {
                if (d) { messages.push(d); if (activeTab === 'messages') renderMessages(); }
            }),
            EventBus.on('mesh:connected', () => { fetchAll(); fetchDeviceInfo(); fetchChannels(); fetchModuleConfig(); }),
            EventBus.on('mesh:disconnected', fetchAll),
        ];

        // ── Auto-refresh loop ───────────────────────────────────
        let refreshTick = 0;
        const timer = setInterval(() => {
            fetchAll();
            if (activeTab === 'messages') fetchMessages();
            // Refresh device info every 30s (6 ticks at 5s interval)
            refreshTick++;
            if (refreshTick % 6 === 0 && connected) {
                fetchDeviceInfo();
            }
        }, REFRESH_MS);

        // ── Init ─────────────────────────────────────────────────
        fetchMessages();
        initAutoDetect();

        // ── Cleanup ref ─────────────────────────────────────────
        panel._mshCleanup = { timer, unsubs };
    },

    unmount(bodyEl, panel) {
        if (panel._mshCleanup) {
            clearInterval(panel._mshCleanup.timer);
            panel._mshCleanup.unsubs.forEach(fn => { if (typeof fn === 'function') fn(); });
            panel._mshCleanup = null;
        }
    },
};

// ── Helpers ─────────────────────────────────────────────────────────
function _isModemPresetRecommended(preset) {
    if (!preset || preset === '--') return true; // unknown, don't warn
    // Modem preset enum: 4 = MEDIUM_FAST (string or numeric)
    return preset === 'MEDIUM_FAST' || preset === '4' || preset === 4;
}

function _age(seconds) {
    if (seconds === null || seconds === undefined || seconds < 0) return '--';
    if (seconds < 60) return seconds + 's';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h';
    return Math.floor(seconds / 86400) + 'd';
}

function _formatDist(meters) {
    if (meters == null) return '';
    if (meters < 1000) return Math.round(meters) + 'm';
    return (meters / 1000).toFixed(1) + 'km';
}

function _normalizeRole(role, index) {
    if (role === 'PRIMARY' || role === '1' || (index === 0 && role !== 'DISABLED')) return 'PRIMARY';
    if (role === 'SECONDARY' || role === '2') return 'SECONDARY';
    if (role === 'DISABLED' || role === '0' || role === '' || role == null) return 'DISABLED';
    return String(role).toUpperCase();
}

// ── Styles ───────────────────────────────────────────────────────────
function _injectStyles() {
    if (document.getElementById('msh-styles')) return;
    const s = document.createElement('style');
    s.id = 'msh-styles';
    s.textContent = `
        /* ── Connection bar ─────────────────────────────────────── */
        .msh-conn-bar { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #1a1a2e; background:#0a0a0f; flex-shrink:0; }
        .msh-dot { width:10px; height:10px; border-radius:50%; background:#444; flex-shrink:0; transition:background 0.3s; }
        .msh-dot-on { background:#05ffa1; box-shadow:0 0 8px #05ffa188; }
        .msh-conn-label { font-size:0.72rem; color:#888; font-weight:bold; letter-spacing:1px; }
        .msh-conn-device { font-size:0.72rem; color:#ccc; }
        .msh-conn-transport { font-size:0.65rem; color:#666; }
        .msh-port-select { background:#0e0e14; border:1px solid #1a1a2e; color:#ccc; font-family:inherit; font-size:0.7rem; padding:2px 4px; border-radius:3px; max-width:150px; }

        /* ── Tab bar ────────────────────────────────────────────── */
        .msh-tabs { display:flex; border-bottom:1px solid #1a1a2e; flex-shrink:0; background:#0e0e14; }
        .msh-tab { flex:1; padding:7px 2px; background:none; border:none; border-bottom:2px solid transparent; color:#666; font-family:inherit; font-size:0.65rem; cursor:pointer; letter-spacing:0.5px; transition:color 0.15s,border-color 0.15s; white-space:nowrap; }
        .msh-tab:hover { color:#aaa; }
        .msh-tab-active { color:#00f0ff; border-bottom-color:#00f0ff; }

        /* ── Body ───────────────────────────────────────────────── */
        .msh-body { flex:1; overflow-y:auto; min-height:0; display:flex; flex-direction:column; }

        /* ── Buttons ────────────────────────────────────────────── */
        .msh-btn { font-family:inherit; font-size:0.7rem; padding:4px 10px; background:rgba(0,240,255,0.06); border:1px solid rgba(0,240,255,0.2); color:#00f0ff; border-radius:3px; cursor:pointer; transition:background 0.15s; }
        .msh-btn:hover { background:rgba(0,240,255,0.15); }
        .msh-btn:disabled { opacity:0.4; cursor:not-allowed; }
        .msh-btn-sm { font-size:0.65rem; padding:2px 6px; }
        .msh-btn-lg { font-size:0.75rem; padding:6px 16px; }
        .msh-btn-connect { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .msh-btn-connect:hover { background:rgba(5,255,161,0.2); }
        .msh-btn-disconnect { background:rgba(255,42,109,0.08); border-color:rgba(255,42,109,0.2); color:#ff2a6d; }
        .msh-btn-disconnect:hover { background:rgba(255,42,109,0.15); }
        .msh-btn-send { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .msh-btn-save { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .msh-btn-save:hover { background:rgba(5,255,161,0.2); }
        .msh-btn-warn { background:rgba(255,42,109,0.08); border-color:rgba(255,42,109,0.2); color:#ff2a6d; }
        .msh-btn-warn:hover { background:rgba(255,42,109,0.15); }

        /* ── Stats grid ─────────────────────────────────────────── */
        .msh-stats { display:grid; grid-template-columns:1fr 1fr; gap:8px; padding:10px; }
        .msh-stat { text-align:center; }
        .msh-stat-val { font-size:1.4rem; font-weight:bold; }
        .msh-stat-lbl { font-size:0.65rem; color:#666; letter-spacing:1px; margin-top:2px; }

        /* ── Section labels ─────────────────────────────────────── */
        .msh-section-label { font-size:0.65rem; color:#00f0ff88; letter-spacing:2px; padding:6px 10px 2px; text-transform:uppercase; }

        /* ── Empty state ────────────────────────────────────────── */
        .msh-empty { color:#555; font-size:0.72rem; }

        /* ── Radio tab ──────────────────────────────────────────── */
        .msh-radio-status { display:flex; justify-content:center; padding:16px 10px 8px; }
        .msh-radio-indicator { display:flex; flex-direction:column; align-items:center; gap:8px; padding:16px 24px; border:1px solid #1a1a2e; border-radius:8px; }
        .msh-radio-dot-big { width:20px; height:20px; border-radius:50%; }
        .msh-radio-status-text { font-size:0.8rem; font-weight:bold; letter-spacing:2px; }
        .msh-radio-actions { display:flex; gap:6px; padding:12px 10px; flex-wrap:wrap; }
        .msh-radio-ports { margin-top:8px; }
        .msh-port-list { padding:0 10px; }
        .msh-port-row { display:flex; align-items:center; gap:8px; padding:6px 6px; border-bottom:1px solid #ffffff08; }
        .msh-port-name { font-size:0.75rem; color:#00f0ff; min-width:120px; }
        .msh-port-desc { font-size:0.65rem; color:#888; flex:1; }

        /* ── Node table ─────────────────────────────────────────── */
        .msh-node-header { display:flex; justify-content:space-between; padding:4px 10px; border-bottom:1px solid #1a1a2e; flex-shrink:0; }
        .msh-node-count { font-size:0.72rem; color:#888; }
        .msh-node-online { font-size:0.72rem; }
        .msh-table { width:100%; border-collapse:collapse; font-size:0.72rem; }
        .msh-th { padding:4px 6px; color:#888; border-bottom:1px solid #1a1a2e; cursor:pointer; user-select:none; white-space:nowrap; font-size:0.65rem; letter-spacing:0.5px; }
        .msh-th:hover { color:#00f0ff; }
        .msh-td { padding:3px 6px; color:#ccc; border-bottom:1px solid #ffffff06; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .msh-td-long { max-width:120px; }
        .msh-td-hw { font-size:0.65rem; color:#999; }
        .msh-tr:hover .msh-td { background:rgba(0,240,255,0.03); }

        /* ── Messages tab ───────────────────────────────────────── */
        .msh-msg-header { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #1a1a2e; flex-shrink:0; }
        .msh-channel-select { background:#0e0e14; border:1px solid #1a1a2e; color:#ccc; font-family:inherit; font-size:0.72rem; padding:3px 6px; border-radius:3px; }
        .msh-msg-count { font-size:0.65rem; color:#666; margin-left:auto; }
        .msh-chat-log { flex:1; overflow-y:auto; padding:6px 10px; min-height:0; }
        .msh-msg { margin-bottom:8px; }
        .msh-msg-self { text-align:right; }
        .msh-msg-meta { display:flex; align-items:center; gap:4px; margin-bottom:1px; }
        .msh-msg-self .msh-msg-meta { justify-content:flex-end; }
        .msh-msg-from { font-size:0.65rem; font-weight:bold; color:#00f0ff; }
        .msh-msg-self .msh-msg-from { color:#05ffa1; }
        .msh-msg-hops { font-size:0.6rem; color:#555; }
        .msh-msg-time { font-size:0.6rem; color:#555; }
        .msh-msg-delivery { font-size:0.55rem; color:#05ffa1; font-weight:bold; }
        .msh-msg-delivery-fail { color:#ff2a6d; }
        .msh-msg-text { color:#ccc; word-break:break-word; font-size:0.72rem; }
        .msh-msg-acked { }
        .msh-msg-nack .msh-msg-text { color:#888; }
        .msh-chat-input { display:flex; gap:4px; padding:6px 10px; border-top:1px solid #1a1a2e; align-items:center; flex-shrink:0; }
        .msh-input { flex:1; background:#0a0a0f; border:1px solid #1a1a2e; color:#ccc; padding:5px 8px; font-family:inherit; font-size:0.72rem; border-radius:3px; outline:none; }
        .msh-input:focus { border-color:#00f0ff66; }
        .msh-char-count { font-size:0.6rem; color:#888; min-width:24px; text-align:right; }

        /* ── Channels tab ───────────────────────────────────────── */
        .msh-channel-list { padding:4px 10px; }
        .msh-channel-slot { border:1px solid #1a1a2e; border-radius:4px; margin-bottom:4px; padding:6px 8px; background:#0e0e14; }
        .msh-channel-disabled { opacity:0.5; }
        .msh-channel-editing { border-color:#00f0ff44; }
        .msh-channel-slot-header { display:flex; align-items:center; gap:8px; }
        .msh-channel-idx { font-size:0.65rem; color:#555; min-width:14px; font-weight:bold; }
        .msh-channel-name { font-size:0.72rem; color:#ccc; flex:1; }
        .msh-channel-role { font-size:0.65rem; font-weight:bold; letter-spacing:0.5px; }
        .msh-channel-slot-detail { display:flex; align-items:center; gap:8px; margin-top:3px; padding-left:22px; }
        .msh-channel-psk { font-size:0.65rem; }
        .msh-channel-edit-form { padding:6px 0 4px 22px; display:flex; flex-direction:column; gap:4px; }
        .msh-channel-edit-actions { display:flex; gap:6px; margin-top:4px; }
        .msh-channel-actions { display:flex; gap:6px; padding:8px 10px; }
        .msh-edit-label { font-size:0.65rem; color:#888; margin-top:2px; }
        .msh-edit-input { max-width:200px; }

        /* ── Config & Module shared ─────────────────────────────── */
        .msh-config-scroll { flex:1; overflow-y:auto; min-height:0; padding-bottom:8px; }
        .msh-config-grid { padding:0 10px; }
        .msh-cfg-row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #ffffff06; font-size:0.72rem; align-items:center; }
        .msh-cfg-lbl { color:#888; font-size:0.65rem; min-width:100px; flex-shrink:0; }
        .msh-cfg-val { color:#ccc; font-size:0.72rem; text-align:right; }
        .msh-cfg-edit-row { display:flex; justify-content:space-between; align-items:center; padding:3px 0; border-bottom:1px solid #ffffff06; gap:8px; }
        .msh-cfg-input { max-width:180px; flex:0 0 180px; font-size:0.72rem; padding:3px 6px; }
        .msh-config-save-bar { display:flex; gap:8px; padding:12px 10px; border-top:1px solid #1a1a2e; margin-top:8px; }

        /* ── Toggle switch ──────────────────────────────────────── */
        .msh-toggle { position:relative; display:inline-block; width:32px; height:18px; flex-shrink:0; }
        .msh-toggle input { opacity:0; width:0; height:0; }
        .msh-toggle-slider { position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#333; transition:0.2s; border-radius:18px; }
        .msh-toggle-slider::before { content:""; position:absolute; height:14px; width:14px; left:2px; bottom:2px; background:#888; transition:0.2s; border-radius:50%; }
        .msh-toggle input:checked + .msh-toggle-slider { background:rgba(5,255,161,0.3); }
        .msh-toggle input:checked + .msh-toggle-slider::before { transform:translateX(14px); background:#05ffa1; }

        /* ── Module sections (collapsible) ──────────────────────── */
        .msh-module-section { border:1px solid #1a1a2e; border-radius:4px; margin:4px 10px; overflow:hidden; }
        .msh-module-header { display:flex; align-items:center; gap:6px; padding:6px 8px; background:#0e0e14; cursor:pointer; user-select:none; }
        .msh-module-header:hover { background:#12121a; }
        .msh-module-arrow { font-size:0.6rem; color:#666; transition:transform 0.2s; display:inline-block; }
        .msh-module-title { font-size:0.72rem; color:#00f0ff; letter-spacing:1px; font-weight:bold; }
        .msh-module-body { padding:4px 8px 8px; }
        .msh-module-collapsed .msh-module-body { display:none; }
        .msh-module-collapsed .msh-module-arrow { transform:rotate(0deg); }
        .msh-module-section:not(.msh-module-collapsed) .msh-module-arrow { transform:rotate(90deg); }

        /* ── Modem preset warning ──────────────────────────────── */
        .msh-cfg-warn { color:#fcee0a !important; }
        .msh-preset-warning { font-size:0.6rem; color:#fcee0a; padding:2px 10px; background:rgba(252,238,10,0.06); border-left:2px solid #fcee0a; margin:2px 10px 4px; }

        /* ── Message filter button ─────────────────────────────── */
        .msh-msg-filter-btn { font-size:0.6rem !important; letter-spacing:0.5px; }
        .msh-msg-filter-active { background:rgba(5,255,161,0.12); border-color:rgba(5,255,161,0.3); color:#05ffa1; }

        /* ── System messages (dimmed) ──────────────────────────── */
        .msh-msg-system { opacity:0.55; }
        .msh-msg-system .msh-msg-text { font-size:0.65rem; }
        .msh-msg-type-badge { font-size:0.55rem; color:#fcee0a; background:rgba(252,238,10,0.1); border:1px solid rgba(252,238,10,0.2); border-radius:2px; padding:0 3px; letter-spacing:0.5px; }
    `;
    document.head.appendChild(s);
}
