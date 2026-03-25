// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Amy commander tab — wraps the existing Amy panel as a tab in the Commander container.
// This is the first commander addon. Other commanders (Sentinel, headless) would
// register their own tabs into the same container.

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'commander-container',
    id: 'amy-tab',
    title: 'AMY',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#ff2a6d;margin-bottom:8px;font-size:12px">AMY — AI COMMANDER</div>
                <div class="ac-row"><span class="ac-l">STATUS</span><span class="ac-v" data-bind="status">--</span></div>
                <div class="ac-row"><span class="ac-l">MOOD</span><span class="ac-v" data-bind="mood">--</span></div>
                <div class="ac-row"><span class="ac-l">THOUGHT</span><span class="ac-v" data-bind="thought" style="color:#888;font-size:10px">--</span></div>
                <hr style="border-color:#1a1a2e;margin:8px 0">
                <div style="color:#888;margin-bottom:6px;font-size:10px">QUICK CHAT</div>
                <div style="display:flex;gap:4px">
                    <input type="text" class="ac-input" placeholder="Message Amy..." data-bind="chatInput">
                    <button class="ac-btn" data-action="send" style="color:#ff2a6d;border-color:#ff2a6d">SEND</button>
                </div>
                <div class="ac-response" data-bind="response" style="margin-top:8px;font-size:10px;color:#666;max-height:100px;overflow-y:auto"></div>
            </div>
            <style>
                .ac-row{display:flex;justify-content:space-between;padding:2px 0}
                .ac-l{color:#666}.ac-v{color:#ff2a6d}
                .ac-input{background:#0a0a12;border:1px solid #1a1a2e;color:#ccc;padding:3px 6px;font-family:inherit;font-size:10px;flex:1}
                .ac-btn{background:#0a0a12;border:1px solid;padding:3px 8px;font-family:inherit;font-size:10px;cursor:pointer}
            </style>
        `;

        // Wire chat
        const input = el.querySelector('[data-bind="chatInput"]');
        const response = el.querySelector('[data-bind="response"]');
        el.querySelector('[data-action="send"]').addEventListener('click', () => {
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            response.innerHTML = '<span style="color:#888">Thinking...</span>';
            fetch('/api/amy/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text }),
            }).then(r => r.json()).then(d => {
                response.innerHTML = `<span style="color:#ff2a6d">${d.response || d.text || 'No response'}</span>`;
            }).catch(e => {
                response.innerHTML = `<span style="color:#666">${e.message}</span>`;
            });
        });

        // Poll Amy status
        const bind = (key, val) => { const e = el.querySelector(`[data-bind="${key}"]`); if (e) e.textContent = val; };
        el._interval = setInterval(() => {
            fetch('/api/amy/status').then(r => r.json()).then(d => {
                bind('status', d.state || 'unknown');
                bind('mood', d.mood || '--');
                bind('thought', d.last_thought?.text?.substring(0, 80) || '--');
                const statusEl = el.querySelector('[data-bind="status"]');
                if (statusEl) statusEl.style.color = d.state === 'active' ? '#05ffa1' : '#666';
            }).catch(() => bind('status', 'offline'));
        }, 3000);
    },
});
