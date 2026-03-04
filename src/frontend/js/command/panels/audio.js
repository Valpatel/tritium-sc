// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Audio Controls Panel
// Sound effects browser, volume control, mute toggle.
// Lists effects from /api/audio/effects, click to preview.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const CATEGORIES = ['all', 'combat', 'ambient', 'ui', 'voice', 'alert'];

export const AudioPanelDef = {
    id: 'audio',
    title: 'AUDIO',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 280, h: 320 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'audio-panel-inner';
        el.innerHTML = `
            <div class="audio-master">
                <div class="panel-stat-row">
                    <span class="panel-stat-label">MASTER</span>
                    <input type="range" class="audio-volume-slider" data-bind="master-vol"
                           min="0" max="100" value="80" />
                    <span class="panel-stat-value mono" data-bind="master-vol-label">80%</span>
                </div>
                <div class="audio-mute-row">
                    <button class="panel-action-btn" data-action="mute" data-bind="mute-btn">MUTE</button>
                    <button class="panel-action-btn" data-action="stop-all">STOP ALL</button>
                </div>
            </div>
            <div class="panel-section-label mono">SOUND EFFECTS</div>
            <div class="audio-filter-row">
                ${CATEGORIES.map(cat =>
                    `<button class="audio-cat-btn mono${cat === 'all' ? ' active' : ''}" data-cat="${cat}">${cat.toUpperCase()}</button>`
                ).join('')}
            </div>
            <ul class="panel-list audio-effects-list" data-bind="effects-list" role="listbox" aria-label="Sound effects">
                <li class="panel-empty">Loading effects...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const effectsListEl = bodyEl.querySelector('[data-bind="effects-list"]');
        const masterVolSlider = bodyEl.querySelector('[data-bind="master-vol"]');
        const masterVolLabel = bodyEl.querySelector('[data-bind="master-vol-label"]');
        const muteBtn = bodyEl.querySelector('[data-action="mute"]');
        const stopAllBtn = bodyEl.querySelector('[data-action="stop-all"]');

        let allEffects = [];
        let activeCategory = 'all';
        let muted = false;
        let masterVolume = 0.8;
        let _audioCtx = null;
        let _playingNodes = [];

        function getAudioCtx() {
            if (!_audioCtx) {
                _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }
            return _audioCtx;
        }

        // --- Category filter ---
        bodyEl.querySelectorAll('.audio-cat-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                activeCategory = btn.dataset.cat;
                bodyEl.querySelectorAll('.audio-cat-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                renderEffects();
            });
        });

        // --- Volume slider ---
        if (masterVolSlider) {
            masterVolSlider.addEventListener('input', () => {
                masterVolume = parseInt(masterVolSlider.value, 10) / 100;
                if (masterVolLabel) masterVolLabel.textContent = `${Math.round(masterVolume * 100)}%`;
                // Update global audio manager if available
                if (window._tritiumAudio && typeof window._tritiumAudio.setVolume === 'function') {
                    window._tritiumAudio.setVolume(masterVolume);
                }
            });
        }

        // --- Mute button ---
        if (muteBtn) {
            muteBtn.addEventListener('click', () => {
                muted = !muted;
                muteBtn.textContent = muted ? 'UNMUTE' : 'MUTE';
                muteBtn.classList.toggle('panel-action-btn-primary', muted);
                if (window._tritiumAudio && typeof window._tritiumAudio.setMuted === 'function') {
                    window._tritiumAudio.setMuted(muted);
                }
            });
        }

        // --- Stop all ---
        if (stopAllBtn) {
            stopAllBtn.addEventListener('click', () => {
                for (const node of _playingNodes) {
                    try { node.stop(); } catch (_) {}
                }
                _playingNodes.length = 0;
            });
        }

        // --- Effects list ---
        function renderEffects() {
            if (!effectsListEl) return;

            const filtered = activeCategory === 'all'
                ? allEffects
                : allEffects.filter(e => e.category === activeCategory);

            if (filtered.length === 0) {
                effectsListEl.innerHTML = '<li class="panel-empty">No effects in this category</li>';
                return;
            }

            effectsListEl.innerHTML = filtered.map(e => {
                const dur = e.duration ? `${e.duration.toFixed(1)}s` : '';
                return `<li class="panel-list-item audio-effect-item" data-effect="${_esc(e.name)}" role="option">
                    <span class="panel-icon-badge" style="color:var(--green);border-color:var(--green)">&#9835;</span>
                    <span class="audio-effect-info">
                        <span class="audio-effect-name">${_esc(e.name)}</span>
                        <span class="audio-effect-meta mono" style="font-size:0.45rem;color:var(--text-dim)">${_esc(e.category || '')} ${dur}</span>
                    </span>
                    <button class="panel-action-btn audio-play-btn" data-action="play" data-effect="${_esc(e.name)}" title="Play">&#9654;</button>
                </li>`;
            }).join('');

            // Play handlers
            effectsListEl.querySelectorAll('[data-action="play"]').forEach(btn => {
                btn.addEventListener('click', (ev) => {
                    ev.stopPropagation();
                    playEffect(btn.dataset.effect);
                });
            });

            // Click row to play
            effectsListEl.querySelectorAll('.audio-effect-item').forEach(item => {
                item.addEventListener('click', () => {
                    playEffect(item.dataset.effect);
                });
            });
        }

        async function playEffect(name) {
            if (muted) return;
            try {
                const resp = await fetch(`/api/audio/effects/${encodeURIComponent(name)}`);
                if (!resp.ok) return;
                const buf = await resp.arrayBuffer();
                const ctx = getAudioCtx();
                const audioBuf = await ctx.decodeAudioData(buf);
                const source = ctx.createBufferSource();
                const gain = ctx.createGain();
                gain.gain.value = masterVolume;
                source.buffer = audioBuf;
                source.connect(gain);
                gain.connect(ctx.destination);
                source.start();
                _playingNodes.push(source);
                source.onended = () => {
                    const idx = _playingNodes.indexOf(source);
                    if (idx !== -1) _playingNodes.splice(idx, 1);
                };
            } catch (e) {
                console.warn('[Audio] Play failed:', e);
            }
        }

        async function fetchEffects() {
            try {
                const resp = await fetch('/api/audio/effects');
                if (!resp.ok) {
                    allEffects = [];
                    renderEffects();
                    return;
                }
                const data = await resp.json();
                allEffects = Array.isArray(data) ? data : (data.effects || []);
                renderEffects();
            } catch (_) {
                allEffects = [];
                renderEffects();
            }
        }

        // Cleanup audio context on unmount
        panel._unsubs.push(() => {
            for (const node of _playingNodes) {
                try { node.stop(); } catch (_) {}
            }
            _playingNodes.length = 0;
            if (_audioCtx) {
                _audioCtx.close().catch(() => {});
                _audioCtx = null;
            }
        });

        // Initial fetch
        fetchEffects();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
