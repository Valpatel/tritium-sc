// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * COMMANDER Container — single active commander slot.
 *
 * Only ONE commander is loaded at a time. The container shows whichever
 * commander plugin is active (Amy, Sentinel, headless, etc.). When you
 * swap commanders, the old tabs are removed and the new commander's tabs
 * register in their place.
 *
 * The active commander plugin registers its tabs via:
 *   EventBus.emit('panel:register-tab', { container: 'commander-container', ... })
 *
 * Amy is the default/starter commander. Others can replace her.
 */

import { createTabbedContainer } from './tabbed-container.js';

// Load the active commander's tabs — Amy is the default
// When a different commander loads, it registers its own tabs
// and the old ones are replaced (handled by the plugin lifecycle)
import './tabs/commander-amy-tab.js';

export const CommanderContainerDef = createTabbedContainer(
    'commander-container',
    'COMMANDER',
    [
        {
            id: 'commander-status',
            title: 'STATUS',
            create(el) {
                el.innerHTML = `
                    <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                        <div style="color:#ff2a6d;margin-bottom:8px;font-size:12px">ACTIVE COMMANDER</div>
                        <div class="cs-row"><span class="cs-l">NAME</span><span class="cs-v" data-bind="name">--</span></div>
                        <div class="cs-row"><span class="cs-l">STATUS</span><span class="cs-v" data-bind="status">--</span></div>
                        <div class="cs-row"><span class="cs-l">MODEL</span><span class="cs-v" data-bind="model">--</span></div>
                        <div class="cs-row"><span class="cs-l">UPTIME</span><span class="cs-v" data-bind="uptime">--</span></div>
                        <hr style="border-color:#1a1a2e;margin:8px 0">
                        <div style="color:#888;margin-bottom:6px;font-size:10px">LATEST THOUGHT</div>
                        <div class="cs-thought" data-bind="thought" style="color:#555;font-size:10px;font-style:italic;max-height:60px;overflow-y:auto">--</div>
                        <hr style="border-color:#1a1a2e;margin:8px 0">
                        <div style="color:#444;font-size:9px">
                            The commander is a swappable plugin slot.<br>
                            Amy is the default. Other commanders can be loaded<br>
                            to change personality, AI model, and decision style.
                        </div>
                    </div>
                    <style>
                        .cs-row{display:flex;justify-content:space-between;padding:2px 0}
                        .cs-l{color:#666}.cs-v{color:#ff2a6d}
                    </style>
                `;

                const bind = (key, val) => {
                    const e = el.querySelector('[data-bind="' + key + '"]');
                    if (e) e.textContent = val;
                };

                el._interval = setInterval(() => {
                    fetch('/api/amy/status').then(r => r.json()).then(d => {
                        bind('name', d.name || 'Commander');
                        bind('status', d.state || 'unknown');
                        bind('model', d.model || '--');
                        bind('uptime', d.uptime ? Math.floor(d.uptime / 60) + 'm' : '--');
                        bind('thought', d.last_thought?.text?.substring(0, 120) || '--');
                        const statusEl = el.querySelector('[data-bind="status"]');
                        if (statusEl) statusEl.style.color = d.state === 'active' ? '#05ffa1' : '#666';
                    }).catch(() => {
                        bind('name', 'No Commander');
                        bind('status', 'offline');
                    });
                }, 3000);
            },
            unmount(el) { if (el._interval) { clearInterval(el._interval); el._interval = null; } },
        },
    ],
    {
        category: 'commander',
        defaultSize: { w: 320, h: 420 },
        defaultPosition: { x: 30, y: 90 },
    }
);
