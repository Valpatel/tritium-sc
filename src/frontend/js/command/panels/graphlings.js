// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Graphlings Observer Panel
// Live thought stream, deployed agents, emotions, action history.
// Connects to SSE /api/graphlings/thoughts for real-time updates.

import { TritiumStore } from '../store.js';
import { _esc } from '/lib/utils.js';


// Emotion to CSS class mapping
const EMOTION_COLORS = {
    happy: 'gl-emotion-happy',
    curious: 'gl-emotion-curious',
    scared: 'gl-emotion-scared',
    sad: 'gl-emotion-sad',
    angry: 'gl-emotion-angry',
    calm: 'gl-emotion-calm',
    excited: 'gl-emotion-excited',
};

export const GraphlingsPanelDef = {
    id: 'graphlings',
    title: 'GRAPHLINGS',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 340, h: 360 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'gl-panel-inner';
        el.innerHTML = `
            <div class="gl-status-bar">
                <span class="gl-status-label mono">AGENTS</span>
                <span class="gl-status-count mono" data-bind="agent-count">0</span>
                <span class="gl-status-dot" data-bind="connection"></span>
            </div>
            <div class="gl-agents-list" data-bind="agents"></div>
            <div class="gl-divider"></div>
            <div class="gl-thought-header">
                <span class="gl-thought-title mono">THOUGHT STREAM</span>
                <button class="gl-clear-btn mono" data-action="clear">CLR</button>
            </div>
            <div class="gl-thought-stream" data-bind="thoughts"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const agentsEl = bodyEl.querySelector('[data-bind="agents"]');
        const thoughtsEl = bodyEl.querySelector('[data-bind="thoughts"]');
        const countEl = bodyEl.querySelector('[data-bind="agent-count"]');
        const connDot = bodyEl.querySelector('[data-bind="connection"]');

        // Track thoughts
        const maxThoughts = 50;
        let thoughts = [];

        // SSE connection for live thought stream
        let eventSource = null;

        function connectSSE() {
            if (eventSource) eventSource.close();
            eventSource = new EventSource('/api/graphlings/thoughts');

            eventSource.onopen = () => {
                if (connDot) connDot.className = 'gl-status-dot gl-dot-connected';
            };

            eventSource.onmessage = (event) => {
                try {
                    const thought = JSON.parse(event.data);
                    addThought(thought);
                } catch (_) {}
            };

            eventSource.onerror = () => {
                if (connDot) connDot.className = 'gl-status-dot gl-dot-disconnected';
            };
        }

        function addThought(thought) {
            thoughts.push(thought);
            if (thoughts.length > maxThoughts) thoughts.shift();
            renderThoughts();
        }

        function renderThoughts() {
            if (!thoughtsEl) return;
            const html = thoughts.map(t => {
                const soul_id = _esc(t.soul_id || '');
                const text = _esc(t.thought || '');
                const emotion = t.emotion || '';
                const action = _esc(t.action || '');
                const emotionClass = EMOTION_COLORS[emotion] || 'gl-emotion-calm';
                const time = t.timestamp ? new Date(t.timestamp * 1000).toLocaleTimeString() : '';

                return `<div class="gl-thought-entry">
                    <div class="gl-thought-meta">
                        <span class="gl-thought-soul mono">${soul_id}</span>
                        <span class="gl-thought-emotion ${emotionClass}">${_esc(emotion)}</span>
                        <span class="gl-thought-time mono">${time}</span>
                    </div>
                    <div class="gl-thought-text">${text}</div>
                    ${action ? `<div class="gl-thought-action mono">&gt; ${action}</div>` : ''}
                </div>`;
            }).reverse().join('');
            thoughtsEl.innerHTML = html;
        }

        // Fetch initial status
        function fetchStatus() {
            fetch('/api/graphlings/status')
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data) return;
                    if (countEl) countEl.textContent = data.deployed_count || 0;
                    renderAgents(data.deployed || []);
                })
                .catch(() => {});

            fetch('/api/graphlings/agents')
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data || !data.agents) return;
                    // Remote agents displayed separately
                })
                .catch(() => {});
        }

        function renderAgents(agentIds) {
            if (!agentsEl) return;
            if (agentIds.length === 0) {
                agentsEl.innerHTML = '<div class="gl-no-agents mono">No agents deployed</div>';
                return;
            }
            agentsEl.innerHTML = agentIds.map(id => `
                <div class="gl-agent-row">
                    <span class="gl-agent-dot"></span>
                    <span class="gl-agent-id mono">${_esc(id)}</span>
                </div>
            `).join('');
        }

        // Clear button
        bodyEl.querySelector('[data-action="clear"]')?.addEventListener('click', () => {
            thoughts = [];
            renderThoughts();
        });

        // Start SSE + polling
        connectSSE();
        fetchStatus();
        const statusInterval = setInterval(fetchStatus, 5000);

        // Register cleanup via standard _unsubs pattern
        panel._unsubs.push(() => {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            clearInterval(statusInterval);
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
