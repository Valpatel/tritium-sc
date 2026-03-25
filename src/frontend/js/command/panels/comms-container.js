// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Communications Container — tabbed panel for all messaging and relay systems.
 *
 * Built-in tabs: Overview
 * Addon tabs: Meshtastic (LoRa mesh), TAK (Cursor on Target), MQTT, Telegram, Slack, Signal, etc.
 *
 * This container is the natural home for any addon that relays messages,
 * bridges chat systems, or provides communication channels. Each comms
 * addon registers a tab via EventBus.
 */

import { createTabbedContainer } from './tabbed-container.js';

export const CommsContainerDef = createTabbedContainer(
    'comms-container',
    'COMMUNICATIONS',
    [
        {
            id: 'comms-overview-tab',
            title: 'OVERVIEW',
            create(el) {
                el.innerHTML = `
                    <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                        <div style="color:#05ffa1;margin-bottom:8px;font-size:12px">COMMUNICATIONS</div>
                        <p style="color:#666;font-size:10px;margin-bottom:12px">
                            Short and long range comms, chat bridges, and relay systems.<br>
                            Each communication addon registers its own tab here.
                        </p>
                        <div style="color:#888;margin-bottom:6px">CHANNELS</div>
                        <div class="co-row"><span class="co-l">MESHTASTIC</span><span class="co-v co-status" data-ch="mesh">--</span></div>
                        <div class="co-row"><span class="co-l">TAK/CoT</span><span class="co-v co-status" data-ch="tak">--</span></div>
                        <div class="co-row"><span class="co-l">MQTT</span><span class="co-v co-status" data-ch="mqtt">--</span></div>
                        <div class="co-row"><span class="co-l">FEDERATION</span><span class="co-v co-status" data-ch="fed">--</span></div>
                        <hr style="border-color:#1a1a2e;margin:10px 0">
                        <div style="color:#444;font-size:9px">
                            Addons can contribute tabs for: Telegram, Slack, Signal, Discord,
                            Matrix, IRC, SMS gateway, satellite, HF radio, and more.
                        </div>
                    </div>
                    <style>
                        .co-row{display:flex;justify-content:space-between;padding:3px 0}
                        .co-l{color:#888}.co-v{color:#05ffa1}
                        .co-status{font-size:10px}
                    </style>
                `;

                // Poll plugin health for channel status
                el._interval = setInterval(() => {
                    fetch('/api/plugins').then(r => r.json()).then(plugins => {
                        const status = (name) => {
                            const p = (plugins || []).find(pl => pl.name?.toLowerCase().includes(name));
                            return p ? (p.healthy ? '<span style="color:#05ffa1">ONLINE</span>' : '<span style="color:#ff2a6d">OFFLINE</span>') : '<span style="color:#333">NOT LOADED</span>';
                        };
                        const set = (ch, html) => { const e = el.querySelector(`[data-ch="${ch}"]`); if (e) e.innerHTML = html; };
                        set('mesh', status('meshtastic'));
                        set('tak', status('tak'));
                        set('mqtt', status('mqtt'));
                        set('fed', status('federation'));
                    }).catch(() => {});
                }, 5000);
            },
            unmount(el) { if (el._interval) { clearInterval(el._interval); el._interval = null; } },
        },
    ],
    {
        category: 'communications',
        defaultSize: { w: 320, h: 400 },
        defaultPosition: { x: 50, y: 110 },
    }
);
