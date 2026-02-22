// Amy Commander Panel
// Portrait, state, mood, latest thought, CHAT and ATTEND buttons.
// Subscribes to: amy.state, amy.mood, amy.lastThought, amy.speaking

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const AmyPanelDef = {
    id: 'amy',
    title: 'AMY COMMANDER',
    defaultPosition: { x: 8, y: null },   // y calculated in mount (bottom-left)
    defaultSize: { w: 320, h: 200 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'amy-panel-inner';
        el.innerHTML = `
            <div class="amy-p-row">
                <div class="amy-p-portrait" data-state="idle">
                    <div class="amy-p-avatar">
                        <svg width="32" height="32" viewBox="0 0 40 40" fill="none">
                            <circle cx="20" cy="14" r="8" stroke="currentColor" stroke-width="1.5"/>
                            <path d="M6 36c0-7.7 6.3-14 14-14s14 6.3 14 14" stroke="currentColor" stroke-width="1.5"/>
                        </svg>
                    </div>
                    <div class="amy-p-speaking-ring"></div>
                </div>
                <div class="amy-p-info">
                    <div class="amy-p-name-row">
                        <span class="amy-p-name">AMY</span>
                        <span class="amy-p-state mono" data-bind="state">IDLE</span>
                    </div>
                    <div class="amy-p-mood mono" data-bind="mood">
                        <span class="panel-dot panel-dot-neutral"></span>
                        <span data-bind="mood-label">CALM</span>
                    </div>
                </div>
            </div>
            <div class="amy-p-thought" data-bind="thought">Awaiting initialization...</div>
            <div class="amy-p-actions">
                <button class="panel-action-btn panel-action-btn-primary" data-action="chat">CHAT</button>
                <button class="panel-action-btn" data-action="attend">ATTEND</button>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at bottom-left if no saved layout
        if (panel.def.defaultPosition.y === null) {
            // Force reflow so container dimensions are finalized
            void panel.manager.container.offsetHeight;
            const ch = panel.manager.container.clientHeight || 700;
            panel.y = Math.max(0, ch - panel.h - 28); // 28px above status bar
            panel._applyTransform();
        }

        const stateEl = bodyEl.querySelector('[data-bind="state"]');
        const moodLabel = bodyEl.querySelector('[data-bind="mood-label"]');
        const thoughtEl = bodyEl.querySelector('[data-bind="thought"]');
        const portrait = bodyEl.querySelector('.amy-p-portrait');

        // Store subscriptions
        panel._unsubs.push(
            TritiumStore.on('amy.state', (state) => {
                if (stateEl) stateEl.textContent = (state || 'IDLE').toUpperCase();
                if (portrait) portrait.dataset.state = state || 'idle';
            }),

            TritiumStore.on('amy.mood', (mood) => {
                if (moodLabel) moodLabel.textContent = (mood || 'CALM').toUpperCase();
            }),

            TritiumStore.on('amy.lastThought', (thought) => {
                if (thoughtEl) thoughtEl.textContent = thought || '';
            }),

            TritiumStore.on('amy.speaking', (speaking) => {
                if (portrait) {
                    portrait.dataset.state = speaking ? 'speaking' : (TritiumStore.amy.state || 'idle');
                }
            })
        );

        // Apply current state
        if (stateEl) stateEl.textContent = (TritiumStore.amy.state || 'IDLE').toUpperCase();
        if (moodLabel) moodLabel.textContent = (TritiumStore.amy.mood || 'CALM').toUpperCase();
        if (thoughtEl && TritiumStore.amy.lastThought) {
            thoughtEl.textContent = TritiumStore.amy.lastThought;
        }

        // Button handlers
        bodyEl.querySelector('[data-action="chat"]')?.addEventListener('click', () => {
            EventBus.emit('chat:open');
            // Toggle the chat overlay
            const overlay = document.getElementById('chat-overlay');
            if (overlay) overlay.hidden = false;
            document.getElementById('chat-input')?.focus();
        });

        bodyEl.querySelector('[data-action="attend"]')?.addEventListener('click', async () => {
            try {
                await fetch('/api/amy/command', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ action: 'attend' }),
                });
            } catch (_) { /* silent */ }
        });

        // Fetch initial Amy status
        fetch('/api/amy/status').then(r => r.ok ? r.json() : null).then(data => {
            if (!data) return;
            if (data.state) TritiumStore.set('amy.state', data.state);
            if (data.mood) TritiumStore.set('amy.mood', data.mood);
            if (data.last_thought) TritiumStore.set('amy.lastThought', data.last_thought);
        }).catch(() => {});
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
