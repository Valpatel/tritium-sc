// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// MQTT Message Inspector Panel
// Shows live MQTT messages flowing through the system.
// Filter by topic pattern. Useful for debugging and understanding data flow.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const MAX_MESSAGES = 500;
const DISPLAY_LIMIT = 100;

// Topic category styling
const TOPIC_COLORS = {
    heartbeat: '#05ffa1',
    sighting:  '#00f0ff',
    status:    '#fcee0a',
    cmd:       '#ff2a6d',
    chat:      '#9d4edd',
    detection: '#ff8c00',
    telemetry: '#05ffa1',
    frame:     '#666',
    alert:     '#ff2a6d',
    default:   '#888',
};

function getTopicColor(topic) {
    for (const [key, color] of Object.entries(TOPIC_COLORS)) {
        if (topic.includes(key)) return color;
    }
    return TOPIC_COLORS.default;
}

function formatPayload(payload) {
    if (!payload) return '';
    if (typeof payload === 'string') {
        try {
            const obj = JSON.parse(payload);
            return JSON.stringify(obj, null, 2);
        } catch {
            return payload;
        }
    }
    if (typeof payload === 'object') {
        return JSON.stringify(payload, null, 2);
    }
    return String(payload);
}

function truncatePayload(payload, maxLen) {
    if (!payload) return '';
    const str = typeof payload === 'string' ? payload : JSON.stringify(payload);
    if (str.length <= maxLen) return str;
    return str.substring(0, maxLen) + '...';
}

export const MqttInspectorPanelDef = {
    id: 'mqtt-inspector',
    title: 'MQTT INSPECTOR',
    defaultPosition: { x: 16, y: null },
    defaultSize: { w: 420, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'mqtt-inspector-panel';
        el.innerHTML = `
            <div class="mi-toolbar" style="display:flex;align-items:center;gap:4px;padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e);flex-wrap:wrap">
                <input type="text" class="mi-filter-input" placeholder="Filter topic (e.g. tritium/*/sighting)" data-bind="filter"
                    style="flex:1;min-width:120px;background:var(--surface-1, #0e0e14);border:1px solid var(--border, #1a1a2e);
                    color:var(--text, #ccc);padding:2px 6px;font-size:0.6rem;font-family:var(--font-mono);
                    border-radius:3px;outline:none">
                <label style="font-size:0.5rem;color:var(--text-ghost, #666);display:flex;align-items:center;gap:2px;cursor:pointer">
                    <input type="checkbox" data-bind="pause" style="margin:0;accent-color:#ff2a6d"> PAUSE
                </label>
                <button class="panel-action-btn mi-clear-btn" data-bind="clear"
                    style="font-size:0.45rem;padding:1px 6px;background:transparent;border:1px solid var(--border, #1a1a2e);
                    color:var(--text-ghost, #666);cursor:pointer;border-radius:2px">CLEAR</button>
                <span class="mi-stats mono" data-bind="stats" style="font-size:0.45rem;color:var(--text-ghost, #666)">0 msgs</span>
            </div>
            <div class="mi-topic-bar" style="display:flex;gap:3px;padding:3px 8px;border-bottom:1px solid var(--border, #1a1a2e);flex-wrap:wrap">
                <button class="mi-topic-btn" data-topic-filter="all" style="font-size:0.4rem;padding:1px 4px;background:rgba(0,240,255,0.1);border:1px solid rgba(0,240,255,0.3);color:#00f0ff;cursor:pointer;border-radius:2px">ALL</button>
                <button class="mi-topic-btn" data-topic-filter="heartbeat" style="font-size:0.4rem;padding:1px 4px;background:transparent;border:1px solid var(--border, #1a1a2e);color:#05ffa1;cursor:pointer;border-radius:2px">HEARTBEAT</button>
                <button class="mi-topic-btn" data-topic-filter="sighting" style="font-size:0.4rem;padding:1px 4px;background:transparent;border:1px solid var(--border, #1a1a2e);color:#00f0ff;cursor:pointer;border-radius:2px">SIGHTING</button>
                <button class="mi-topic-btn" data-topic-filter="telemetry" style="font-size:0.4rem;padding:1px 4px;background:transparent;border:1px solid var(--border, #1a1a2e);color:#05ffa1;cursor:pointer;border-radius:2px">TELEMETRY</button>
                <button class="mi-topic-btn" data-topic-filter="cmd" style="font-size:0.4rem;padding:1px 4px;background:transparent;border:1px solid var(--border, #1a1a2e);color:#ff2a6d;cursor:pointer;border-radius:2px">COMMAND</button>
                <button class="mi-topic-btn" data-topic-filter="status" style="font-size:0.4rem;padding:1px 4px;background:transparent;border:1px solid var(--border, #1a1a2e);color:#fcee0a;cursor:pointer;border-radius:2px">STATUS</button>
            </div>
            <div class="mi-message-list" data-bind="messages" style="flex:1;overflow-y:auto;font-size:0.55rem;font-family:var(--font-mono)">
                <div class="panel-empty" style="padding:16px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">
                    No MQTT messages yet. Connect to broker to see live traffic.
                </div>
            </div>
            <div class="mi-detail" data-bind="detail" style="display:none;border-top:1px solid var(--border, #1a1a2e);
                max-height:180px;overflow-y:auto;padding:6px 8px;background:var(--surface-1, #0e0e14)">
                <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                    <span class="mono" style="font-size:0.45rem;color:var(--text-ghost, #666)">MESSAGE DETAIL</span>
                    <button data-bind="close-detail" style="background:none;border:none;color:var(--text-ghost, #666);cursor:pointer;font-size:0.6rem">&times;</button>
                </div>
                <pre class="mi-detail-content" data-bind="detail-content"
                    style="margin:0;font-size:0.5rem;color:#05ffa1;white-space:pre-wrap;word-break:break-all"></pre>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at bottom-left
        if (panel.def.defaultPosition.y === null) {
            const ch = panel.manager.container.clientHeight || 600;
            panel.y = ch - panel.h - 8;
            panel._applyTransform();
        }

        const messagesEl = bodyEl.querySelector('[data-bind="messages"]');
        const statsEl = bodyEl.querySelector('[data-bind="stats"]');
        const filterInput = bodyEl.querySelector('[data-bind="filter"]');
        const pauseCheckbox = bodyEl.querySelector('[data-bind="pause"]');
        const clearBtn = bodyEl.querySelector('[data-bind="clear"]');
        const detailEl = bodyEl.querySelector('[data-bind="detail"]');
        const detailContent = bodyEl.querySelector('[data-bind="detail-content"]');
        const closeDetail = bodyEl.querySelector('[data-bind="close-detail"]');

        let messages = [];
        let filterText = '';
        let topicFilter = 'all';
        let paused = false;
        let totalCount = 0;

        // Topic filter buttons
        bodyEl.querySelectorAll('.mi-topic-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                topicFilter = btn.dataset.topicFilter;
                bodyEl.querySelectorAll('.mi-topic-btn').forEach(b => {
                    b.style.background = b.dataset.topicFilter === topicFilter
                        ? 'rgba(0,240,255,0.1)' : 'transparent';
                    b.style.borderColor = b.dataset.topicFilter === topicFilter
                        ? 'rgba(0,240,255,0.3)' : 'var(--border, #1a1a2e)';
                });
                renderMessages();
            });
        });

        if (filterInput) {
            filterInput.addEventListener('input', () => {
                filterText = filterInput.value.toLowerCase();
                renderMessages();
            });
        }

        if (pauseCheckbox) {
            pauseCheckbox.addEventListener('change', () => {
                paused = pauseCheckbox.checked;
            });
        }

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                messages = [];
                totalCount = 0;
                renderMessages();
            });
        }

        if (closeDetail) {
            closeDetail.addEventListener('click', () => {
                detailEl.style.display = 'none';
            });
        }

        function addMessage(topic, payload) {
            if (paused) return;
            totalCount++;
            messages.unshift({
                topic: topic,
                payload: payload,
                time: new Date(),
                id: totalCount,
            });
            if (messages.length > MAX_MESSAGES) {
                messages.length = MAX_MESSAGES;
            }
            renderMessages();
        }

        function matchesFilters(msg) {
            // Topic category filter
            if (topicFilter !== 'all' && !msg.topic.includes(topicFilter)) return false;
            // Text filter (topic or payload)
            if (filterText) {
                const payloadStr = typeof msg.payload === 'string' ? msg.payload : JSON.stringify(msg.payload || '');
                if (!msg.topic.toLowerCase().includes(filterText) &&
                    !payloadStr.toLowerCase().includes(filterText)) return false;
            }
            return true;
        }

        function renderMessages() {
            const filtered = messages.filter(matchesFilters);
            if (statsEl) statsEl.textContent = `${filtered.length}/${totalCount} msgs`;

            if (filtered.length === 0) {
                messagesEl.innerHTML = '<div class="panel-empty" style="padding:16px;text-align:center;color:var(--text-ghost, #666);font-size:0.6rem">No matching messages</div>';
                return;
            }

            const display = filtered.slice(0, DISPLAY_LIMIT);
            messagesEl.innerHTML = display.map(msg => {
                const color = getTopicColor(msg.topic);
                const time = msg.time.toLocaleTimeString().substr(0, 8);
                const preview = truncatePayload(msg.payload, 80);
                // Extract last part of topic for compact display
                const parts = msg.topic.split('/');
                const shortTopic = parts.length > 2 ? parts.slice(-2).join('/') : msg.topic;
                return `<div class="mi-msg" data-msg-id="${msg.id}" style="padding:3px 8px;border-bottom:1px solid rgba(255,255,255,0.03);cursor:pointer;transition:background 0.1s"
                    onmouseenter="this.style.background='rgba(0,240,255,0.05)'" onmouseleave="this.style.background=''">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:${color};font-size:0.5rem;font-weight:500" title="${_esc(msg.topic)}">${_esc(shortTopic)}</span>
                        <span style="color:var(--text-ghost, #555);font-size:0.4rem">${time}</span>
                    </div>
                    <div style="color:var(--text, #999);font-size:0.45rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:0.7">
                        ${_esc(preview)}
                    </div>
                </div>`;
            }).join('');

            // Click to show detail
            messagesEl.querySelectorAll('.mi-msg').forEach(el => {
                el.addEventListener('click', () => {
                    const id = parseInt(el.dataset.msgId);
                    const msg = messages.find(m => m.id === id);
                    if (msg && detailEl && detailContent) {
                        detailEl.style.display = '';
                        detailContent.textContent = `TOPIC: ${msg.topic}\nTIME:  ${msg.time.toISOString()}\n\n${formatPayload(msg.payload)}`;
                    }
                });
            });
        }

        // Subscribe to MQTT messages through EventBus
        const subs = [
            EventBus.on('mqtt:message', (data) => {
                addMessage(data.topic || 'unknown', data.payload || data);
            }),
            // Also capture WebSocket messages that originated from MQTT
            EventBus.on('ws:raw_message', (data) => {
                if (data && data.mqtt_topic) {
                    addMessage(data.mqtt_topic, data);
                }
            }),
            // Heartbeat messages
            EventBus.on('device:heartbeat', (d) => {
                addMessage(`tritium/${d.device_id || 'unknown'}/heartbeat`, d);
            }),
            // BLE sightings
            EventBus.on('ble:target_update', (d) => {
                addMessage(`tritium/${d.node_id || 'node'}/sighting`, d);
            }),
            // Mesh messages
            EventBus.on('mesh:message', (d) => {
                addMessage(`tritium/mesh/${d.from || 'unknown'}/chat`, d);
            }),
            // Status messages
            EventBus.on('device:status', (d) => {
                addMessage(`tritium/${d.device_id || 'unknown'}/status`, d);
            }),
        ];

        panel._unsubs.push(...subs);

        // Fetch MQTT bridge stats
        fetch('/api/health').then(r => r.ok ? r.json() : null).then(data => {
            if (data && data.mqtt) {
                addMessage('system/mqtt/stats', data.mqtt);
            }
        }).catch(() => {});

        renderMessages();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
