// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Amy Conversation Panel — Full inner monologue with timestamps,
// question input for tactical queries, cognitive layer activity display.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


function _ts() {
    const d = new Date();
    return d.toTimeString().slice(0, 8);
}

export const AmyConversationPanelDef = {
    id: 'amy-conversation',
    title: 'AMY MONOLOGUE',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 420, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'amy-conv-inner';
        el.innerHTML = `
            <div class="amy-conv-layers" data-bind="layers">
                <div class="amy-conv-layer" data-layer="reflex">
                    <span class="amy-conv-layer-name mono">L1 REFLEX</span>
                    <span class="amy-conv-layer-bar"><span class="amy-conv-layer-fill" data-bind="layer-reflex" style="width:0%"></span></span>
                </div>
                <div class="amy-conv-layer" data-layer="instinct">
                    <span class="amy-conv-layer-name mono">L2 INSTINCT</span>
                    <span class="amy-conv-layer-bar"><span class="amy-conv-layer-fill" data-bind="layer-instinct" style="width:0%"></span></span>
                </div>
                <div class="amy-conv-layer" data-layer="awareness">
                    <span class="amy-conv-layer-name mono">L3 AWARENESS</span>
                    <span class="amy-conv-layer-bar"><span class="amy-conv-layer-fill" data-bind="layer-awareness" style="width:0%"></span></span>
                </div>
                <div class="amy-conv-layer" data-layer="deliberation">
                    <span class="amy-conv-layer-name mono">L4 DELIBERATE</span>
                    <span class="amy-conv-layer-bar"><span class="amy-conv-layer-fill" data-bind="layer-deliberation" style="width:0%"></span></span>
                </div>
            </div>
            <div class="amy-conv-log" data-bind="log">
                <div class="amy-conv-entry mono" style="color:var(--text-dim)">Connecting to Amy's consciousness stream...</div>
            </div>
            <div class="amy-conv-input-row">
                <input type="text" class="amy-conv-input" placeholder="Ask Amy about the tactical situation..." spellcheck="false" data-bind="question-input">
                <button class="panel-action-btn panel-action-btn-primary" data-action="ask">ASK</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const logEl = bodyEl.querySelector('[data-bind="log"]');
        const inputEl = bodyEl.querySelector('[data-bind="question-input"]');
        const askBtn = bodyEl.querySelector('[data-action="ask"]');

        const layerFills = {
            reflex: bodyEl.querySelector('[data-bind="layer-reflex"]'),
            instinct: bodyEl.querySelector('[data-bind="layer-instinct"]'),
            awareness: bodyEl.querySelector('[data-bind="layer-awareness"]'),
            deliberation: bodyEl.querySelector('[data-bind="layer-deliberation"]'),
        };

        let thoughts = [];
        const MAX_THOUGHTS = 100;
        let eventSource = null;

        function addEntry(text, type = 'thought', timestamp = null) {
            const ts = timestamp || _ts();
            const entry = { text, type, ts };
            thoughts.push(entry);
            if (thoughts.length > MAX_THOUGHTS) thoughts.shift();

            if (logEl) {
                const div = document.createElement('div');
                div.className = `amy-conv-entry mono amy-conv-${type}`;

                const tsSpan = document.createElement('span');
                tsSpan.className = 'amy-conv-ts';
                tsSpan.textContent = ts;

                const textSpan = document.createElement('span');
                textSpan.className = 'amy-conv-text';
                textSpan.textContent = text;

                div.appendChild(tsSpan);
                div.appendChild(textSpan);
                logEl.appendChild(div);

                // Auto-scroll
                logEl.scrollTop = logEl.scrollHeight;

                // Limit DOM nodes
                while (logEl.children.length > MAX_THOUGHTS) {
                    logEl.removeChild(logEl.firstChild);
                }
            }
        }

        function updateLayers(layerData) {
            if (!layerData) return;
            for (const [name, fill] of Object.entries(layerFills)) {
                if (fill) {
                    const activity = layerData[name] || 0;
                    const pct = Math.min(100, Math.max(0, activity));
                    fill.style.width = `${pct}%`;

                    // Color based on activity
                    if (pct > 70) fill.style.background = 'var(--magenta)';
                    else if (pct > 30) fill.style.background = 'var(--cyan)';
                    else fill.style.background = 'var(--text-dim)';
                }
            }
        }

        // Connect to Amy's thought stream via SSE
        function connectSSE() {
            try {
                eventSource = new EventSource('/api/amy/thoughts');

                eventSource.onmessage = (event) => {
                    try {
                        const msg = JSON.parse(event.data);
                        // Events come as {type, data, timestamp} from the SSE bridge.
                        // The inner payload is in msg.data (object with text/thought fields).
                        const etype = msg.type || '';
                        const payload = msg.data || {};
                        const ts = msg.timestamp;

                        // Extract thought text from either flat or nested format
                        const thoughtText = payload.text || payload.thought
                            || msg.thought || msg.text;
                        if (thoughtText && (etype === 'thought' || etype === 'inner_monologue'
                            || etype === '' || etype === 'unknown')) {
                            addEntry(thoughtText, 'thought', ts);
                        }

                        // Amy announcements (war commentary)
                        if (etype === 'amy_announcement' && payload.text) {
                            const cat = payload.category || 'announce';
                            addEntry(payload.text, cat === 'elimination' ? 'action' : 'thought', ts);
                        }

                        // Layer activity updates
                        const layers = payload.layer_activity || msg.layer_activity;
                        if (layers) {
                            updateLayers(layers);
                        }

                        // Action results
                        const actionText = payload.action || msg.action;
                        if (actionText) {
                            addEntry(`ACTION: ${actionText}`, 'action', ts);
                        }
                    } catch (_) {
                        // Plain text thought
                        addEntry(event.data, 'thought');
                    }
                };

                eventSource.addEventListener('thought', (event) => {
                    addEntry(event.data, 'thought');
                });

                eventSource.addEventListener('action', (event) => {
                    addEntry(`ACTION: ${event.data}`, 'action');
                });

                eventSource.addEventListener('mood', (event) => {
                    addEntry(`MOOD: ${event.data}`, 'mood');
                });

                eventSource.onerror = () => {
                    // Reconnect after delay
                    if (eventSource) eventSource.close();
                    eventSource = null;
                    setTimeout(connectSSE, 5000);
                };
            } catch (_) {
                setTimeout(connectSSE, 5000);
            }
        }

        // Subscribe to store-based thought updates as fallback
        panel._unsubs.push(
            TritiumStore.on('amy.lastThought', (thought) => {
                if (thought) addEntry(thought, 'thought');
            }),
            TritiumStore.on('amy.state', (state) => {
                // Map state to rough layer activity
                const layers = { reflex: 10, instinct: 10, awareness: 10, deliberation: 10 };
                if (state === 'thinking') { layers.deliberation = 80; layers.awareness = 50; }
                else if (state === 'observing') { layers.awareness = 70; layers.instinct = 40; }
                else if (state === 'commanding') { layers.deliberation = 90; layers.awareness = 60; }
                else if (state === 'speaking') { layers.awareness = 50; layers.reflex = 60; }
                updateLayers(layers);
            })
        );

        // Ask Amy a question
        async function askQuestion() {
            const question = inputEl ? inputEl.value.trim() : '';
            if (!question) return;
            if (inputEl) inputEl.value = '';

            addEntry(`YOU: ${question}`, 'user-question');

            try {
                const resp = await fetch('/api/amy/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: question }),
                });

                if (resp.ok) {
                    const data = await resp.json();
                    const reply = data.reply || data.response || data.message || 'No response';
                    addEntry(`AMY: ${reply}`, 'amy-reply');
                } else {
                    addEntry('AMY: [communication error]', 'error');
                }
            } catch (_) {
                addEntry('AMY: [connection failed]', 'error');
            }
        }

        if (askBtn) askBtn.addEventListener('click', askQuestion);
        if (inputEl) {
            inputEl.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') askQuestion();
                e.stopPropagation();
            });
        }

        connectSSE();

        // Cleanup
        panel._unsubs.push(() => {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
