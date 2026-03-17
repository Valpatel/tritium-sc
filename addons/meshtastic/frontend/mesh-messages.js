// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Meshtastic Addon — Mesh Chat panel
// Message input, scrolling log, sender/time/text display
// Sends via POST /api/addons/meshtastic/send

import { EventBus } from '/static/js/command/events.js';
import { _esc } from '/static/js/command/panel-utils.js';

const API_BASE = '/api/addons/meshtastic';
const MAX_MESSAGES = 200;
const MSG_CHAR_LIMIT = 228;

export const MeshMessagesPanelDef = {
    id: 'mesh-messages',
    title: 'MESH CHAT',
    defaultPosition: { x: 360, y: 510 },
    defaultSize: { w: 340, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mesh-messages-panel';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;';
        el.innerHTML = `
            <div class="mesh-msg-header" style="padding:4px 8px;display:flex;align-items:center;gap:6px;border-bottom:1px solid var(--border,#1a1a2e);">
                <span class="panel-dot panel-dot-neutral" data-bind="status-dot"></span>
                <span class="mono" style="font-size:0.7rem;color:var(--text-dim,#888)" data-bind="msg-count">0 messages</span>
            </div>
            <div class="mesh-msg-log" data-bind="messages"
                 style="flex:1;overflow-y:auto;padding:4px 8px;font-size:0.72rem;min-height:0;">
            </div>
            <div class="mesh-msg-input-area"
                 style="padding:6px 8px;border-top:1px solid var(--border,#1a1a2e);display:flex;gap:4px;align-items:center;">
                <input type="text" class="panel-filter" data-bind="input"
                       maxlength="${MSG_CHAR_LIMIT}"
                       placeholder="Type a message..."
                       autocomplete="off"
                       style="flex:1;font-size:0.72rem;" />
                <span class="mono" data-bind="char-count"
                      style="font-size:0.6rem;color:var(--text-dim,#888);min-width:24px;text-align:right;">${MSG_CHAR_LIMIT}</span>
                <button class="panel-action-btn panel-action-btn-primary" data-action="send"
                        style="font-size:0.7rem;padding:3px 10px;">SEND</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const messagesEl = bodyEl.querySelector('[data-bind="messages"]');
        const inputEl = bodyEl.querySelector('[data-bind="input"]');
        const charCountEl = bodyEl.querySelector('[data-bind="char-count"]');
        const sendBtn = bodyEl.querySelector('[data-action="send"]');
        const msgCountEl = bodyEl.querySelector('[data-bind="msg-count"]');
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');

        let messages = [];

        function renderMessages() {
            if (msgCountEl) {
                msgCountEl.textContent = messages.length + ' message' + (messages.length !== 1 ? 's' : '');
            }
            if (!messagesEl) return;

            if (messages.length === 0) {
                messagesEl.innerHTML = `
                    <div class="panel-empty" style="text-align:center;padding:30px 10px;font-size:0.7rem;">
                        No messages yet.<br/>Connect a Meshtastic device to send and receive.
                    </div>`;
                return;
            }

            // Show last N messages
            const visible = messages.slice(-100);
            messagesEl.innerHTML = visible.map(m => {
                const sender = _esc(m.from_short || m.from_name || m.from_id || m.from || 'Unknown');
                const text = _esc(m.text || '');
                const time = m.timestamp
                    ? new Date(typeof m.timestamp === 'number' ? m.timestamp * 1000 : m.timestamp)
                        .toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    : '';
                const isSelf = m.is_self || false;

                return `<div class="mesh-msg-entry" style="margin-bottom:4px;${isSelf ? 'text-align:right;' : ''}">
                    <span class="mono" style="color:${isSelf ? 'var(--green,#05ffa1)' : 'var(--cyan,#00f0ff)'};font-size:0.65rem;font-weight:bold;">${sender}</span>
                    <span class="mono" style="color:var(--text-dim,#888);font-size:0.55rem;margin-left:4px;">${time}</span>
                    <div style="color:var(--text,#ccc);margin-top:1px;word-break:break-word;">${text}</div>
                </div>`;
            }).join('');

            // Scroll to bottom
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        async function sendMessage() {
            if (!inputEl) return;
            const text = (inputEl.value || '').trim();
            if (!text) return;

            inputEl.value = '';
            if (charCountEl) charCountEl.textContent = String(MSG_CHAR_LIMIT);

            // Optimistic add to local list
            const localMsg = {
                from: 'You',
                from_short: 'You',
                text,
                timestamp: Math.floor(Date.now() / 1000),
                is_self: true,
            };
            messages.push(localMsg);
            if (messages.length > MAX_MESSAGES) messages = messages.slice(-MAX_MESSAGES);
            renderMessages();

            try {
                await fetch(API_BASE + '/send', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text }),
                });
            } catch (_) {
                // Message send failed silently -- already shown in UI
            }
        }

        // Input events
        if (inputEl) {
            inputEl.addEventListener('input', () => {
                if (!charCountEl) return;
                const remaining = MSG_CHAR_LIMIT - (inputEl.value || '').length;
                charCountEl.textContent = String(remaining);
                charCountEl.style.color = remaining < 20
                    ? 'var(--magenta, #ff2a6d)'
                    : 'var(--text-dim, #888)';
            });

            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    e.stopPropagation();
                    sendMessage();
                }
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', sendMessage);
        }

        // EventBus: receive incoming messages
        panel._unsubs.push(
            EventBus.on('mesh:text', (data) => {
                if (!data) return;
                messages.push(data);
                if (messages.length > MAX_MESSAGES) messages = messages.slice(-MAX_MESSAGES);
                renderMessages();
            }),

            EventBus.on('mesh:connected', () => {
                if (statusDot) statusDot.className = 'panel-dot panel-dot-green';
            }),

            EventBus.on('mesh:disconnected', () => {
                if (statusDot) statusDot.className = 'panel-dot panel-dot-neutral';
            }),
        );

        // Initial render
        renderMessages();
    },

    unmount(bodyEl, panel) {
        // _unsubs cleaned up by panel base class
    },
};
