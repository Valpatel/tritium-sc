// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Collaboration Hub Panel — unified view of workspaces, operators, drawings, chat.
//
// Wires all /api/collaboration/* endpoints into a single operational panel:
// - Active workspaces with join/leave/create
// - Online operators
// - Shared map drawings count
// - Operator chat (inline)
// - Recent collaboration activity feed

import { EventBus } from '/lib/events.js';
import { _esc, _timeAgo } from '/lib/utils.js';

const POLL_MS = 6000;
const CHAT_POLL_MS = 4000;
const MAX_CHAT_DISPLAY = 40;

const OPERATOR_ID = 'op_' + Math.random().toString(36).slice(2, 8);
const OPERATOR_NAME = 'Operator';

// ---- Collaboration API helpers ----

async function fetchWorkspaces() {
    try {
        const r = await fetch('/api/collaboration/workspaces');
        if (!r.ok) return [];
        const data = await r.json();
        return data.workspaces || [];
    } catch { return []; }
}

async function createWorkspace(investigationId, title) {
    try {
        const r = await fetch('/api/collaboration/workspaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                investigation_id: investigationId,
                title: title,
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function joinWorkspace(workspaceId) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function leaveWorkspace(workspaceId) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}/leave`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function deleteWorkspace(workspaceId) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}`, { method: 'DELETE' });
        return r.ok;
    } catch { return false; }
}

async function changeWorkspaceStatus(workspaceId, newStatus) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                new_status: newStatus,
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function addEntityToWorkspace(workspaceId, entityId) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}/entity`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                entity_id: entityId,
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function annotateWorkspace(workspaceId, entityId, note) {
    try {
        const r = await fetch(`/api/collaboration/workspaces/${workspaceId}/annotate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                entity_id: entityId,
                note: note,
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function fetchDrawings() {
    try {
        const r = await fetch('/api/collaboration/drawings');
        if (!r.ok) return [];
        const data = await r.json();
        return data.drawings || [];
    } catch { return []; }
}

async function fetchChatHistory(channel, since) {
    try {
        let url = `/api/collaboration/chat?channel=${encodeURIComponent(channel)}&limit=50`;
        if (since) url += `&since=${since}`;
        const r = await fetch(url);
        if (!r.ok) return [];
        const data = await r.json();
        return data.messages || [];
    } catch { return []; }
}

async function sendChatMessage(content, channel) {
    try {
        const r = await fetch('/api/collaboration/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                operator_id: OPERATOR_ID,
                operator_name: OPERATOR_NAME,
                content: content,
                channel: channel || 'general',
                message_type: 'text',
            }),
        });
        return r.ok ? await r.json() : null;
    } catch { return null; }
}

async function fetchChatChannels() {
    try {
        const r = await fetch('/api/collaboration/chat/channels');
        if (!r.ok) return [];
        const data = await r.json();
        return data.channels || [];
    } catch { return []; }
}

// ---- Status colors ----
const STATUS_COLORS = {
    open: '#05ffa1',
    in_progress: '#00f0ff',
    review: '#fcee0a',
    closed: '#888',
    archived: '#555',
};

function _formatTs(ts) {
    if (!ts) return '--';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
}

// ---- Panel Definition ----

export const CollaborationHubPanelDef = {
    id: 'collaboration-hub',
    title: 'COLLABORATION',
    defaultPosition: { x: 60, y: 60 },
    defaultSize: { w: 440, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'collab-hub-root';
        el.innerHTML = `
            <div class="collab-tabs">
                <button class="collab-tab collab-tab-active" data-tab="overview">OVERVIEW</button>
                <button class="collab-tab" data-tab="workspaces">WORKSPACES</button>
                <button class="collab-tab" data-tab="chat">CHAT</button>
                <button class="collab-tab" data-tab="drawings">DRAWINGS</button>
            </div>
            <div class="collab-tab-content" data-bind="tab-content">
                <div class="collab-loading">Loading collaboration data...</div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        let activeTab = 'overview';
        let workspaces = [];
        let drawings = [];
        let chatMessages = [];
        let chatChannels = [];
        let activeChannel = 'general';
        let lastChatTs = 0;

        const tabContent = bodyEl.querySelector('[data-bind="tab-content"]');
        const tabs = bodyEl.querySelectorAll('.collab-tab');

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeTab = tab.dataset.tab;
                tabs.forEach(t => t.classList.toggle('collab-tab-active', t.dataset.tab === activeTab));
                renderActiveTab();
            });
        });

        // ---- Overview tab ----
        function renderOverview() {
            const opCount = new Set(workspaces.flatMap(w => w.active_operators || [])).size;
            const wsCount = workspaces.length;
            const drawCount = drawings.length;
            const recentEvents = workspaces
                .flatMap(w => (w.recent_events || []).map(e => ({ ...e, workspace_title: w.title })))
                .sort((a, b) => (b.timestamp || 0) - (a.timestamp || 0))
                .slice(0, 15);

            tabContent.innerHTML = `
                <div class="collab-overview">
                    <div class="collab-stats-row">
                        <div class="collab-stat">
                            <div class="collab-stat-val" style="color:#00f0ff">${wsCount}</div>
                            <div class="collab-stat-label">Workspaces</div>
                        </div>
                        <div class="collab-stat">
                            <div class="collab-stat-val" style="color:#05ffa1">${opCount}</div>
                            <div class="collab-stat-label">Operators</div>
                        </div>
                        <div class="collab-stat">
                            <div class="collab-stat-val" style="color:#fcee0a">${drawCount}</div>
                            <div class="collab-stat-label">Drawings</div>
                        </div>
                        <div class="collab-stat">
                            <div class="collab-stat-val" style="color:#ff2a6d">${chatChannels.length}</div>
                            <div class="collab-stat-label">Channels</div>
                        </div>
                    </div>
                    <div class="collab-section-title">RECENT ACTIVITY</div>
                    <div class="collab-activity-feed">
                        ${recentEvents.length === 0 ? '<div class="collab-empty">No recent collaboration activity</div>' :
                            recentEvents.map(e => `
                                <div class="collab-event-row">
                                    <span class="collab-event-time">${_formatTs(e.timestamp)}</span>
                                    <span class="collab-event-type" style="color:${_eventColor(e.event_type)}">${_esc(e.event_type)}</span>
                                    <span class="collab-event-detail">${_esc(e.operator_name || e.operator_id || '')} ${_eventDetail(e)}</span>
                                </div>
                            `).join('')}
                    </div>
                </div>
            `;
        }

        function _eventColor(type) {
            const colors = {
                workspace_created: '#05ffa1',
                operator_joined: '#00f0ff',
                operator_left: '#888',
                entity_added: '#fcee0a',
                annotation_added: '#ff2a6d',
                status_changed: '#9d4edd',
            };
            return colors[type] || '#888';
        }

        function _eventDetail(e) {
            if (e.event_type === 'entity_added') return `added entity ${_esc(e.entity_id || '')}`;
            if (e.event_type === 'annotation_added') return `annotated ${_esc(e.entity_id || '')}`;
            if (e.event_type === 'status_changed') return `changed status to ${_esc(e.new_status || '')}`;
            if (e.event_type === 'operator_joined') return 'joined workspace';
            if (e.event_type === 'operator_left') return 'left workspace';
            return '';
        }

        // ---- Workspaces tab ----
        function renderWorkspaces() {
            tabContent.innerHTML = `
                <div class="collab-ws-toolbar">
                    <button class="collab-btn collab-btn-primary" data-action="create-ws">+ NEW WORKSPACE</button>
                </div>
                <div class="collab-ws-list">
                    ${workspaces.length === 0 ? '<div class="collab-empty">No active workspaces</div>' :
                        workspaces.map(w => {
                            const isMember = (w.active_operators || []).includes(OPERATOR_ID);
                            const statusColor = STATUS_COLORS[w.status] || STATUS_COLORS.open;
                            return `
                            <div class="collab-ws-card" data-ws-id="${_esc(w.workspace_id)}">
                                <div class="collab-ws-header">
                                    <span class="collab-ws-title">${_esc(w.title)}</span>
                                    <span class="collab-ws-ops">${(w.active_operators || []).length} ops</span>
                                </div>
                                <div class="collab-ws-meta">
                                    <span class="collab-ws-id mono">${_esc(w.workspace_id)}</span>
                                    <span class="collab-ws-version">v${w.version || 0}</span>
                                </div>
                                <div class="collab-ws-actions">
                                    ${isMember
                                        ? `<button class="collab-btn collab-btn-danger" data-action="leave-ws" data-ws="${_esc(w.workspace_id)}">LEAVE</button>`
                                        : `<button class="collab-btn collab-btn-primary" data-action="join-ws" data-ws="${_esc(w.workspace_id)}">JOIN</button>`
                                    }
                                    <select class="collab-status-select" data-action="status-ws" data-ws="${_esc(w.workspace_id)}">
                                        ${['open', 'in_progress', 'review', 'closed', 'archived'].map(s =>
                                            `<option value="${s}" ${(w.status || 'open') === s ? 'selected' : ''}>${s.toUpperCase()}</option>`
                                        ).join('')}
                                    </select>
                                    <button class="collab-btn collab-btn-danger" data-action="delete-ws" data-ws="${_esc(w.workspace_id)}" title="Delete">X</button>
                                </div>
                                ${(w.recent_events || []).length > 0 ? `
                                    <div class="collab-ws-events">
                                        ${(w.recent_events || []).slice(-3).map(e => `
                                            <div class="collab-ws-event-mini">
                                                <span style="color:${_eventColor(e.event_type)}">${_esc(e.event_type)}</span>
                                                <span>${_esc(e.operator_name || e.operator_id || '')}</span>
                                            </div>
                                        `).join('')}
                                    </div>
                                ` : ''}
                            </div>`;
                        }).join('')}
                </div>
            `;

            // Wire workspace actions
            tabContent.querySelector('[data-action="create-ws"]')?.addEventListener('click', async () => {
                const title = prompt('Workspace title:');
                if (!title) return;
                const invId = 'inv_' + Date.now().toString(36);
                const ws = await createWorkspace(invId, title);
                if (ws) { await refreshAll(); renderActiveTab(); }
            });

            tabContent.querySelectorAll('[data-action="join-ws"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    await joinWorkspace(btn.dataset.ws);
                    await refreshAll();
                    renderActiveTab();
                });
            });

            tabContent.querySelectorAll('[data-action="leave-ws"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    await leaveWorkspace(btn.dataset.ws);
                    await refreshAll();
                    renderActiveTab();
                });
            });

            tabContent.querySelectorAll('[data-action="delete-ws"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if (!confirm('Delete this workspace?')) return;
                    await deleteWorkspace(btn.dataset.ws);
                    await refreshAll();
                    renderActiveTab();
                });
            });

            tabContent.querySelectorAll('[data-action="status-ws"]').forEach(sel => {
                sel.addEventListener('change', async () => {
                    await changeWorkspaceStatus(sel.dataset.ws, sel.value);
                    await refreshAll();
                    renderActiveTab();
                });
            });

            // Stop keyboard events from propagating from inputs
            tabContent.querySelectorAll('input, select').forEach(el => {
                el.addEventListener('keydown', e => e.stopPropagation());
            });
        }

        // ---- Chat tab ----
        function renderChat() {
            tabContent.innerHTML = `
                <div class="collab-chat-header">
                    <select class="collab-channel-select" data-bind="channel">
                        <option value="general">general</option>
                        ${chatChannels.filter(c => c.channel !== 'general').map(c =>
                            `<option value="${_esc(c.channel)}" ${c.channel === activeChannel ? 'selected' : ''}>${_esc(c.channel)} (${c.message_count})</option>`
                        ).join('')}
                    </select>
                    <span class="collab-chat-count">${chatMessages.length} msgs</span>
                </div>
                <div class="collab-chat-messages" data-bind="messages">
                    ${chatMessages.length === 0 ? '<div class="collab-empty">No messages yet</div>' :
                        chatMessages.slice(-MAX_CHAT_DISPLAY).map(m => `
                            <div class="collab-chat-msg ${m.message_type === 'alert' ? 'collab-chat-alert' : ''}">
                                <span class="collab-chat-time">${_formatTs(m.timestamp)}</span>
                                <span class="collab-chat-sender">${_esc(m.operator_name || m.operator_id)}</span>
                                <span class="collab-chat-text">${_esc(m.content)}</span>
                            </div>
                        `).join('')}
                </div>
                <div class="collab-chat-input-row">
                    <input type="text" class="collab-chat-input" data-bind="chat-input" placeholder="Type a message..." spellcheck="false">
                    <button class="collab-btn collab-btn-primary" data-action="send-chat">SEND</button>
                </div>
            `;

            const msgContainer = tabContent.querySelector('[data-bind="messages"]');
            if (msgContainer) msgContainer.scrollTop = msgContainer.scrollHeight;

            const channelSelect = tabContent.querySelector('[data-bind="channel"]');
            if (channelSelect) {
                channelSelect.value = activeChannel;
                channelSelect.addEventListener('change', async () => {
                    activeChannel = channelSelect.value;
                    lastChatTs = 0;
                    chatMessages = await fetchChatHistory(activeChannel);
                    renderChat();
                });
            }

            const chatInput = tabContent.querySelector('[data-bind="chat-input"]');
            const sendBtn = tabContent.querySelector('[data-action="send-chat"]');

            async function doSend() {
                if (!chatInput) return;
                const text = chatInput.value.trim();
                if (!text) return;
                chatInput.value = '';
                const msg = await sendChatMessage(text, activeChannel);
                if (msg) {
                    chatMessages.push(msg);
                    renderChat();
                }
            }

            if (sendBtn) sendBtn.addEventListener('click', doSend);
            if (chatInput) {
                chatInput.addEventListener('keydown', (e) => {
                    e.stopPropagation();
                    if (e.key === 'Enter') doSend();
                });
            }

            // Stop keyboard propagation
            tabContent.querySelectorAll('input, select').forEach(el => {
                el.addEventListener('keydown', e => e.stopPropagation());
            });
        }

        // ---- Drawings tab ----
        function renderDrawings() {
            const byType = {};
            for (const d of drawings) {
                const t = d.drawing_type || 'unknown';
                byType[t] = (byType[t] || 0) + 1;
            }

            tabContent.innerHTML = `
                <div class="collab-draw-toolbar">
                    <button class="collab-btn collab-btn-danger" data-action="clear-drawings">CLEAR ALL</button>
                    <span class="collab-draw-total">${drawings.length} drawings on map</span>
                </div>
                <div class="collab-draw-summary">
                    ${Object.entries(byType).map(([t, c]) => `
                        <div class="collab-draw-type-row">
                            <span class="collab-draw-type-name">${_esc(t)}</span>
                            <span class="collab-draw-type-count">${c}</span>
                        </div>
                    `).join('') || '<div class="collab-empty">No drawings</div>'}
                </div>
                <div class="collab-draw-list">
                    ${drawings.slice(0, 30).map(d => `
                        <div class="collab-draw-item">
                            <span class="collab-draw-item-type" style="color:${_esc(d.color || '#00f0ff')}">${_esc(d.drawing_type)}</span>
                            <span class="collab-draw-item-label">${_esc(d.label || d.text || '')}</span>
                            <span class="collab-draw-item-op">${_esc(d.operator_name || d.operator_id || '')}</span>
                            <span class="collab-draw-item-time">${_timeAgo(d.created_at)}</span>
                            <button class="collab-draw-delete" data-action="delete-drawing" data-id="${_esc(d.drawing_id)}" title="Delete">X</button>
                        </div>
                    `).join('')}
                </div>
            `;

            tabContent.querySelector('[data-action="clear-drawings"]')?.addEventListener('click', async () => {
                if (!confirm('Clear all map drawings?')) return;
                try {
                    await fetch('/api/collaboration/drawings', { method: 'DELETE' });
                    drawings = [];
                    renderDrawings();
                } catch {}
            });

            tabContent.querySelectorAll('[data-action="delete-drawing"]').forEach(btn => {
                btn.addEventListener('click', async () => {
                    try {
                        await fetch(`/api/collaboration/drawings/${btn.dataset.id}`, { method: 'DELETE' });
                        drawings = drawings.filter(d => d.drawing_id !== btn.dataset.id);
                        renderDrawings();
                    } catch {}
                });
            });
        }

        // ---- Tab router ----
        function renderActiveTab() {
            if (activeTab === 'overview') renderOverview();
            else if (activeTab === 'workspaces') renderWorkspaces();
            else if (activeTab === 'chat') renderChat();
            else if (activeTab === 'drawings') renderDrawings();
        }

        // ---- Data refresh ----
        async function refreshAll() {
            [workspaces, drawings, chatChannels] = await Promise.all([
                fetchWorkspaces(),
                fetchDrawings(),
                fetchChatChannels(),
            ]);
        }

        async function refreshChat() {
            const newMsgs = await fetchChatHistory(activeChannel, lastChatTs);
            if (newMsgs.length > 0) {
                for (const m of newMsgs) {
                    if (!chatMessages.find(x => x.message_id === m.message_id)) {
                        chatMessages.push(m);
                    }
                }
                lastChatTs = Math.max(...chatMessages.map(m => m.timestamp || 0));
                if (activeTab === 'chat') renderChat();
            }
        }

        // Initial load
        (async () => {
            await refreshAll();
            chatMessages = await fetchChatHistory(activeChannel);
            if (chatMessages.length > 0) {
                lastChatTs = Math.max(...chatMessages.map(m => m.timestamp || 0));
            }
            renderActiveTab();
        })();

        // Polling
        const pollTimer = setInterval(async () => {
            await refreshAll();
            if (activeTab !== 'chat') renderActiveTab();
        }, POLL_MS);

        const chatPollTimer = setInterval(refreshChat, CHAT_POLL_MS);

        // WebSocket events
        const wsHandler = (data) => {
            if (activeTab === 'overview' || activeTab === 'workspaces') {
                refreshAll().then(renderActiveTab);
            }
        };
        const chatHandler = (data) => {
            if (data && data.data) {
                const m = data.data;
                if (!chatMessages.find(x => x.message_id === m.message_id)) {
                    chatMessages.push(m);
                    if (m.timestamp) lastChatTs = Math.max(lastChatTs, m.timestamp);
                    if (activeTab === 'chat') renderChat();
                }
            }
        };
        const drawHandler = () => {
            fetchDrawings().then(d => { drawings = d; if (activeTab === 'drawings') renderDrawings(); });
        };

        EventBus.on('ws:workspace_event', wsHandler);
        EventBus.on('ws:operator_chat', chatHandler);
        EventBus.on('ws:map_drawing', drawHandler);

        panel._unsubs = panel._unsubs || [];
        panel._unsubs.push(() => clearInterval(pollTimer));
        panel._unsubs.push(() => clearInterval(chatPollTimer));
        panel._unsubs.push(() => EventBus.off('ws:workspace_event', wsHandler));
        panel._unsubs.push(() => EventBus.off('ws:operator_chat', chatHandler));
        panel._unsubs.push(() => EventBus.off('ws:map_drawing', drawHandler));
    },

    unmount(bodyEl, panel) {
        // _unsubs cleaned by Panel base class
    },
};

// ---- Styles ----
const style = document.createElement('style');
style.textContent = `
.collab-hub-root {
    display: flex;
    flex-direction: column;
    height: 100%;
    overflow: hidden;
}

.collab-tabs {
    display: flex;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
    flex-shrink: 0;
}

.collab-tab {
    flex: 1;
    padding: 6px 4px;
    background: none;
    border: none;
    color: #888;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.5rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
}

.collab-tab:hover { color: #ccc; }
.collab-tab-active { color: #00f0ff; border-bottom-color: #00f0ff; }

.collab-tab-content {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
    padding: 8px;
}

.collab-loading, .collab-empty {
    padding: 20px;
    text-align: center;
    color: rgba(224, 224, 224, 0.3);
    font-size: 0.65rem;
}

/* Stats row */
.collab-stats-row {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
}

.collab-stat {
    flex: 1;
    text-align: center;
    padding: 8px 4px;
    background: rgba(0, 240, 255, 0.04);
    border: 1px solid rgba(0, 240, 255, 0.1);
    border-radius: 3px;
}

.collab-stat-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 1.2rem;
    font-weight: 700;
}

.collab-stat-label {
    font-size: 0.45rem;
    color: #888;
    letter-spacing: 0.1em;
    margin-top: 2px;
}

.collab-section-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.5rem;
    font-weight: 700;
    color: #00f0ff;
    letter-spacing: 0.08em;
    margin-bottom: 6px;
    border-bottom: 1px solid rgba(0, 240, 255, 0.15);
    padding-bottom: 2px;
}

/* Activity feed */
.collab-activity-feed {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.collab-event-row {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px;
    font-size: 0.6rem;
    border-bottom: 1px solid rgba(0, 240, 255, 0.04);
}

.collab-event-time {
    color: #555;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.5rem;
    min-width: 40px;
}

.collab-event-type {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.45rem;
    font-weight: 700;
    min-width: 90px;
}

.collab-event-detail {
    color: #aaa;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

/* Buttons */
.collab-btn {
    padding: 4px 10px;
    border: 1px solid #333;
    background: rgba(255, 255, 255, 0.05);
    color: #ccc;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.5rem;
    font-weight: 700;
    cursor: pointer;
    border-radius: 2px;
    transition: background 0.15s;
}

.collab-btn:hover { background: rgba(255, 255, 255, 0.1); }
.collab-btn-primary { border-color: #00f0ff; color: #00f0ff; }
.collab-btn-primary:hover { background: rgba(0, 240, 255, 0.15); }
.collab-btn-danger { border-color: #ff2a6d; color: #ff2a6d; }
.collab-btn-danger:hover { background: rgba(255, 42, 109, 0.15); }

/* Workspace cards */
.collab-ws-toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
}

.collab-ws-list {
    display: flex;
    flex-direction: column;
    gap: 6px;
}

.collab-ws-card {
    background: rgba(0, 240, 255, 0.03);
    border: 1px solid rgba(0, 240, 255, 0.1);
    border-radius: 3px;
    padding: 8px;
}

.collab-ws-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
}

.collab-ws-title {
    font-weight: 700;
    color: #e0e0e0;
    font-size: 0.7rem;
}

.collab-ws-ops {
    font-size: 0.5rem;
    color: #05ffa1;
    font-family: 'JetBrains Mono', monospace;
}

.collab-ws-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.45rem;
    color: #666;
    margin-bottom: 6px;
}

.collab-ws-actions {
    display: flex;
    gap: 4px;
    align-items: center;
}

.collab-status-select {
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 2px 4px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.45rem;
    border-radius: 2px;
    cursor: pointer;
}

.collab-ws-events {
    margin-top: 6px;
    padding-top: 4px;
    border-top: 1px solid rgba(0, 240, 255, 0.06);
}

.collab-ws-event-mini {
    font-size: 0.45rem;
    color: #888;
    display: flex;
    gap: 6px;
}

/* Chat */
.collab-chat-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
}

.collab-channel-select {
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 3px 6px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.55rem;
    border-radius: 2px;
}

.collab-chat-count {
    font-size: 0.5rem;
    color: #666;
    font-family: 'JetBrains Mono', monospace;
}

.collab-chat-messages {
    flex: 1;
    overflow-y: auto;
    max-height: 300px;
    display: flex;
    flex-direction: column;
    gap: 2px;
    margin-bottom: 6px;
    padding: 4px;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(0, 240, 255, 0.06);
    border-radius: 3px;
}

.collab-chat-msg {
    display: flex;
    gap: 6px;
    font-size: 0.6rem;
    padding: 2px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.collab-chat-alert {
    background: rgba(255, 42, 109, 0.08);
    border-left: 2px solid #ff2a6d;
    padding-left: 4px;
}

.collab-chat-time {
    color: #555;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.5rem;
    min-width: 36px;
}

.collab-chat-sender {
    color: #00f0ff;
    font-weight: 700;
    font-size: 0.55rem;
    min-width: 60px;
    max-width: 80px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.collab-chat-text {
    color: #e0e0e0;
    flex: 1;
    word-break: break-word;
}

.collab-chat-input-row {
    display: flex;
    gap: 4px;
}

.collab-chat-input {
    flex: 1;
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    color: #e0e0e0;
    padding: 5px 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.6rem;
    border-radius: 2px;
    outline: none;
}

.collab-chat-input:focus {
    border-color: #00f0ff;
    box-shadow: 0 0 4px rgba(0, 240, 255, 0.2);
}

/* Drawings */
.collab-draw-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
}

.collab-draw-total {
    font-size: 0.55rem;
    color: #888;
    font-family: 'JetBrains Mono', monospace;
}

.collab-draw-summary {
    margin-bottom: 8px;
}

.collab-draw-type-row {
    display: flex;
    justify-content: space-between;
    padding: 3px 6px;
    font-size: 0.6rem;
    border-bottom: 1px solid rgba(0, 240, 255, 0.04);
}

.collab-draw-type-name {
    color: #aaa;
}

.collab-draw-type-count {
    color: #00f0ff;
    font-family: 'JetBrains Mono', monospace;
    font-weight: 700;
}

.collab-draw-list {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.collab-draw-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 3px 4px;
    font-size: 0.55rem;
    border-bottom: 1px solid rgba(0, 240, 255, 0.04);
}

.collab-draw-item-type {
    font-weight: 700;
    min-width: 60px;
}

.collab-draw-item-label {
    flex: 1;
    color: #aaa;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.collab-draw-item-op {
    color: #666;
    font-size: 0.5rem;
}

.collab-draw-item-time {
    color: #555;
    font-size: 0.45rem;
    font-family: 'JetBrains Mono', monospace;
}

.collab-draw-delete {
    background: none;
    border: 1px solid rgba(255, 42, 109, 0.3);
    color: #ff2a6d;
    cursor: pointer;
    font-size: 0.5rem;
    padding: 1px 4px;
    border-radius: 2px;
}

.collab-draw-delete:hover {
    background: rgba(255, 42, 109, 0.15);
}

/* Scrollbar */
.collab-tab-content::-webkit-scrollbar,
.collab-chat-messages::-webkit-scrollbar {
    width: 4px;
}
.collab-tab-content::-webkit-scrollbar-track,
.collab-chat-messages::-webkit-scrollbar-track {
    background: transparent;
}
.collab-tab-content::-webkit-scrollbar-thumb,
.collab-chat-messages::-webkit-scrollbar-thumb {
    background: rgba(0, 240, 255, 0.2);
    border-radius: 2px;
}
`;
document.head.appendChild(style);
