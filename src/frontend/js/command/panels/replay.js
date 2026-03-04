// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Replay Panel
// VCR-style battle replay with timeline scrubber, transport controls,
// speed selector, wave jump, and event log.
// Feeds replay frames back into TritiumStore so the map re-renders them.

import { TritiumStore } from '../store.js';
import { EventBus } from '../events.js';

/**
 * Format seconds as M:SS.
 * @param {number} seconds
 * @returns {string}
 */
function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds || 0));
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec < 10 ? '0' : ''}${sec}`;
}

/**
 * Format an event type string for display.
 * Replaces underscores with spaces and title-cases.
 * @param {string} eventType
 * @returns {string}
 */
function formatEventType(eventType) {
    if (!eventType) return '';
    return eventType.replace(/_/g, ' ').toUpperCase();
}

/**
 * Build a one-line summary for a replay event.
 * @param {Object} evt - { event_type, data, timestamp }
 * @returns {string}
 */
function formatEventSummary(evt) {
    if (!evt) return '';
    const t = evt.event_type || '';
    const d = evt.data || {};
    switch (t) {
        case 'target_eliminated':
            return `${d.target_name || d.target_id || '?'} eliminated`;
        case 'projectile_fired':
            return `${d.source_name || d.source_id || '?'} fired`;
        case 'projectile_hit':
            return `Hit on ${d.target_name || d.target_id || '?'}`;
        case 'wave_start':
            return `Wave ${d.wave_number || '?'} started`;
        case 'wave_complete':
            return `Wave ${d.wave_number || '?'} complete`;
        case 'game_over':
            return `Game over: ${d.result || '?'}`;
        default:
            return formatEventType(t);
    }
}

// Expose helpers on window for testing
if (typeof window !== 'undefined') {
    window.ReplayHelpers = {
        formatTime,
        formatEventType,
        formatEventSummary,
    };
}

export const ReplayPanelDef = {
    id: 'replay',
    title: 'REPLAY',
    defaultPosition: { x: 8, y: null },  // y calculated (bottom-left)
    defaultSize: { w: 420, h: 260 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'replay-panel-inner';
        el.innerHTML = `
            <div class="replay-status-bar" data-section="status">
                <span class="replay-mode-badge mono" data-bind="mode">LIVE</span>
                <span class="replay-time mono" data-bind="time">0:00 / 0:00</span>
            </div>
            <div class="replay-timeline" data-section="timeline">
                <div class="replay-timeline-bar" data-element="timeline-bar">
                    <div class="replay-timeline-fill" data-element="timeline-fill"></div>
                    <div class="replay-playhead" data-element="playhead"></div>
                    <div class="replay-wave-markers" data-element="wave-markers"></div>
                </div>
            </div>
            <div class="replay-transport" data-section="transport">
                <button class="replay-transport-btn mono" data-action="rewind" title="Rewind to start">|&lt;&lt;</button>
                <button class="replay-transport-btn mono" data-action="step-back" title="Step back">&lt;&lt;</button>
                <button class="replay-transport-btn replay-transport-btn--play mono" data-action="play-pause" title="Play / Pause">PLAY</button>
                <button class="replay-transport-btn mono" data-action="step-forward" title="Step forward">&gt;&gt;</button>
                <button class="replay-transport-btn mono" data-action="jump-end" title="Jump to end">&gt;&gt;|</button>
            </div>
            <div class="replay-speed" data-section="speed">
                <button class="replay-speed-btn mono" data-speed="0.25">0.25x</button>
                <button class="replay-speed-btn mono" data-speed="0.5">0.5x</button>
                <button class="replay-speed-btn replay-speed-btn--active mono" data-speed="1">1x</button>
                <button class="replay-speed-btn mono" data-speed="2">2x</button>
                <button class="replay-speed-btn mono" data-speed="4">4x</button>
            </div>
            <div class="replay-waves" data-section="waves"></div>
            <div class="replay-event-log" data-section="event-log">
                <div class="replay-event-log-label mono">EVENTS</div>
                <div class="replay-event-list" data-element="event-list"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        // Position at bottom-left if no saved layout
        if (panel.def.defaultPosition.y === null) {
            const ch = panel.manager.container.clientHeight || 800;
            panel.y = ch - panel.h - 40;
            panel._applyTransform();
        }

        const modeBadge = bodyEl.querySelector('[data-bind="mode"]');
        const timeDisplay = bodyEl.querySelector('[data-bind="time"]');
        const timelineBar = bodyEl.querySelector('[data-element="timeline-bar"]');
        const timelineFill = bodyEl.querySelector('[data-element="timeline-fill"]');
        const playhead = bodyEl.querySelector('[data-element="playhead"]');
        const waveMarkers = bodyEl.querySelector('[data-element="wave-markers"]');
        const playPauseBtn = bodyEl.querySelector('[data-action="play-pause"]');
        const rewindBtn = bodyEl.querySelector('[data-action="rewind"]');
        const stepBackBtn = bodyEl.querySelector('[data-action="step-back"]');
        const stepForwardBtn = bodyEl.querySelector('[data-action="step-forward"]');
        const jumpEndBtn = bodyEl.querySelector('[data-action="jump-end"]');
        const speedBtns = bodyEl.querySelectorAll('.replay-speed-btn');
        const wavesContainer = bodyEl.querySelector('[data-section="waves"]');
        const eventList = bodyEl.querySelector('[data-element="event-list"]');

        // Internal state
        let _replayMode = false;
        let _playing = false;
        let _speed = 1;
        let _progress = 0;
        let _currentTime = 0;
        let _duration = 0;
        let _pollTimer = null;
        let _replayData = null;
        let _timeline = null;

        function setReplayMode(active) {
            _replayMode = active;
            if (modeBadge) {
                modeBadge.textContent = active ? 'REPLAY' : 'LIVE';
                modeBadge.classList.toggle('replay-mode-badge--replay', active);
                modeBadge.classList.toggle('replay-mode-badge--live', !active);
            }
            // Notify store so other panels can react
            TritiumStore.set('replay.active', active);
        }

        function updateTimeDisplay() {
            if (timeDisplay) {
                timeDisplay.textContent = `${formatTime(_currentTime)} / ${formatTime(_duration)}`;
            }
            if (timelineFill) {
                timelineFill.style.width = `${(_progress * 100).toFixed(1)}%`;
            }
            if (playhead) {
                playhead.style.left = `${(_progress * 100).toFixed(1)}%`;
            }
        }

        function updatePlayButton() {
            if (playPauseBtn) {
                playPauseBtn.textContent = _playing ? 'PAUSE' : 'PLAY';
            }
        }

        function updateSpeedButtons(speed) {
            if (speedBtns && speedBtns.length > 0) {
                speedBtns.forEach(btn => {
                    const btnSpeed = parseFloat(btn.getAttribute('data-speed'));
                    btn.classList.toggle('replay-speed-btn--active', btnSpeed === speed);
                });
            }
        }

        /**
         * Apply a replay frame to TritiumStore so the map re-renders.
         * @param {Object} frame - { targets: [...], timestamp }
         */
        function applyFrameToStore(frame) {
            if (!frame || !frame.targets) return;
            // Collect current frame target IDs
            const frameIds = new Set();
            for (const t of frame.targets) {
                frameIds.add(t.target_id);
                TritiumStore.updateUnit(t.target_id, {
                    name: t.name || t.target_id,
                    type: t.asset_type || 'unknown',
                    alliance: t.alliance || 'unknown',
                    position: t.position || { x: 0, y: 0 },
                    heading: t.heading || 0,
                    health: t.health,
                    maxHealth: t.max_health,
                    status: t.status || 'active',
                    fsmState: t.fsm_state,
                    fsm_state: t.fsm_state,
                    visible: t.visible,
                    radio_detected: t.radio_detected,
                    morale: t.morale,
                });
            }
            // Mark units not in this frame as eliminated (not removed).
            // On backward seek, units eliminated in later frames won't be in
            // the current snapshot.  Removing them loses them permanently;
            // marking them "eliminated" preserves them for future forward seeks.
            TritiumStore.units.forEach((u, id) => {
                if (!frameIds.has(id)) {
                    TritiumStore.updateUnit(id, { status: 'eliminated', health: 0 });
                }
            });
        }

        /**
         * Render events near current playback time in the event log.
         */
        function renderEventsAtTime(currentTime) {
            if (!eventList || !_timeline) return;
            if (!_replayData || !_replayData.frames || _replayData.frames.length === 0) {
                eventList.innerHTML = '<div class="replay-event-empty mono">No events</div>';
                return;
            }
            // Find events within a 2-second window around current time
            const startTime = _replayData.metadata.start_time || 0;
            const absTime = startTime + currentTime;
            const window_s = 2.0;
            const nearby = _timeline.filter(e =>
                Math.abs(e.timestamp - absTime) <= window_s
            );

            if (nearby.length === 0) {
                eventList.innerHTML = '<div class="replay-event-empty mono">--</div>';
                return;
            }

            eventList.innerHTML = nearby.slice(0, 8).map(e => {
                const relTime = Math.max(0, e.timestamp - startTime);
                return `<div class="replay-event-item">` +
                    `<span class="replay-event-time mono">${formatTime(relTime)}</span>` +
                    `<span class="replay-event-text mono">${formatEventSummary(e)}</span>` +
                    `</div>`;
            }).join('');
        }

        /**
         * Build wave jump buttons from timeline data.
         */
        function buildWaveButtons() {
            if (!wavesContainer || !_timeline) return;
            const waveEvents = _timeline.filter(e => e.event_type === 'wave_start');
            if (waveEvents.length === 0) {
                wavesContainer.innerHTML = '';
                return;
            }
            wavesContainer.innerHTML = '<span class="replay-waves-label mono">WAVES</span>' +
                waveEvents.map(e => {
                    const wNum = e.data.wave_number || 0;
                    return `<button class="replay-wave-btn mono" data-wave="${wNum}">W${wNum}</button>`;
                }).join('');

            // Wire wave button clicks
            const waveBtns = wavesContainer.querySelectorAll('.replay-wave-btn');
            if (waveBtns && waveBtns.length > 0) {
                waveBtns.forEach(btn => {
                    btn.addEventListener('click', async () => {
                        const wave = parseInt(btn.getAttribute('data-wave'), 10);
                        if (isNaN(wave)) return;
                        try {
                            await fetch('/api/game/replay/seek-wave', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ wave }),
                            });
                            pollState();
                        } catch (e) {
                            console.error('[REPLAY] Seek wave failed:', e);
                        }
                    });
                });
            }

            // Place wave markers on the timeline
            if (waveMarkers && _duration > 0 && _replayData) {
                const startTime = _replayData.metadata.start_time || 0;
                waveMarkers.innerHTML = waveEvents.map(e => {
                    const relTime = Math.max(0, e.timestamp - startTime);
                    const pct = (relTime / _duration) * 100;
                    return `<div class="replay-wave-marker" style="left:${pct.toFixed(1)}%" title="Wave ${e.data.wave_number || '?'}"></div>`;
                }).join('');
            }
        }

        /**
         * Apply state from the spectator API response.
         */
        function applyState(state) {
            if (!state) return;
            _playing = state.playing;
            _speed = state.speed;
            _progress = state.progress;
            _currentTime = state.current_time;
            _duration = state.duration;
            updateTimeDisplay();
            updatePlayButton();
            updateSpeedButtons(_speed);
            renderEventsAtTime(_currentTime);
        }

        /**
         * Poll spectator state and current frame from the backend.
         */
        async function pollState() {
            try {
                const resp = await fetch('/api/game/replay/frame');
                if (!resp.ok) return;
                const data = await resp.json();
                applyState(data.state);
                if (data.frame && _replayMode) {
                    applyFrameToStore(data.frame);
                }
            } catch (e) {
                // Network error, ignore
            }
        }

        /**
         * Load replay data and timeline from the backend.
         */
        async function loadReplayData() {
            try {
                const [replayResp, timelineResp] = await Promise.all([
                    fetch('/api/game/replay'),
                    fetch('/api/game/replay/timeline'),
                ]);
                if (replayResp.ok) _replayData = await replayResp.json();
                if (timelineResp.ok) _timeline = await timelineResp.json();
                buildWaveButtons();
            } catch (e) {
                console.error('[REPLAY] Failed to load replay data:', e);
            }
        }

        /**
         * Enter replay mode: load data, start polling.
         */
        async function enterReplayMode() {
            setReplayMode(true);
            await loadReplayData();
            // Start polling for state updates at 4Hz during playback
            if (_pollTimer) clearInterval(_pollTimer);
            _pollTimer = setInterval(() => {
                if (_playing) pollState();
            }, 250);
        }

        /**
         * Exit replay mode: stop polling, stop playback.
         */
        async function exitReplayMode() {
            if (_pollTimer) {
                clearInterval(_pollTimer);
                _pollTimer = null;
            }
            try {
                await fetch('/api/game/replay/stop', { method: 'POST' });
            } catch (e) {
                // ignore
            }
            _playing = false;
            _progress = 0;
            _currentTime = 0;
            updateTimeDisplay();
            updatePlayButton();
            setReplayMode(false);
        }

        // -- Wire transport buttons --

        if (playPauseBtn) {
            playPauseBtn.addEventListener('click', async () => {
                if (!_replayMode) {
                    await enterReplayMode();
                }
                try {
                    const endpoint = _playing ? '/api/game/replay/pause' : '/api/game/replay/play';
                    const resp = await fetch(endpoint, { method: 'POST' });
                    if (resp.ok) {
                        const state = await resp.json();
                        applyState(state);
                    }
                } catch (e) {
                    console.error('[REPLAY] Play/pause failed:', e);
                }
            });
        }

        if (rewindBtn) {
            rewindBtn.addEventListener('click', async () => {
                if (!_replayMode) await enterReplayMode();
                try {
                    await fetch('/api/game/replay/stop', { method: 'POST' });
                    await fetch('/api/game/replay/seek', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ time: 0 }),
                    });
                    const resp = await fetch('/api/game/replay/state');
                    if (resp.ok) applyState(await resp.json());
                    pollState();
                } catch (e) {
                    console.error('[REPLAY] Rewind failed:', e);
                }
            });
        }

        if (stepBackBtn) {
            stepBackBtn.addEventListener('click', async () => {
                if (!_replayMode) await enterReplayMode();
                try {
                    const resp = await fetch('/api/game/replay/step-backward', { method: 'POST' });
                    if (resp.ok) applyState(await resp.json());
                    pollState();
                } catch (e) {
                    console.error('[REPLAY] Step back failed:', e);
                }
            });
        }

        if (stepForwardBtn) {
            stepForwardBtn.addEventListener('click', async () => {
                if (!_replayMode) await enterReplayMode();
                try {
                    const resp = await fetch('/api/game/replay/step-forward', { method: 'POST' });
                    if (resp.ok) applyState(await resp.json());
                    pollState();
                } catch (e) {
                    console.error('[REPLAY] Step forward failed:', e);
                }
            });
        }

        if (jumpEndBtn) {
            jumpEndBtn.addEventListener('click', async () => {
                if (!_replayMode) await enterReplayMode();
                try {
                    await fetch('/api/game/replay/seek', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ time: _duration }),
                    });
                    const resp = await fetch('/api/game/replay/state');
                    if (resp.ok) applyState(await resp.json());
                    pollState();
                } catch (e) {
                    console.error('[REPLAY] Jump to end failed:', e);
                }
            });
        }

        // -- Wire speed buttons --
        if (speedBtns && speedBtns.length > 0) {
            speedBtns.forEach(btn => {
                btn.addEventListener('click', async () => {
                    const speed = parseFloat(btn.getAttribute('data-speed'));
                    if (isNaN(speed)) return;
                    try {
                        const resp = await fetch('/api/game/replay/speed', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ speed }),
                        });
                        if (resp.ok) applyState(await resp.json());
                    } catch (e) {
                        console.error('[REPLAY] Set speed failed:', e);
                    }
                });
            });
        }

        // -- Wire timeline click-to-seek --
        if (timelineBar) {
            timelineBar.addEventListener('click', async (e) => {
                if (!_replayMode) await enterReplayMode();
                const rect = timelineBar.getBoundingClientRect();
                const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                const seekTime = pct * _duration;
                try {
                    await fetch('/api/game/replay/seek', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ time: seekTime }),
                    });
                    pollState();
                } catch (err) {
                    console.error('[REPLAY] Seek failed:', err);
                }
            });
        }

        // -- Listen for game_over to auto-offer replay --
        panel._unsubs.push(
            TritiumStore.on('game.phase', (phase) => {
                if (phase === 'victory' || phase === 'defeat') {
                    // Reload replay data when a game ends
                    loadReplayData();
                }
            })
        );

        // Cleanup poll timer on unmount
        panel._unsubs.push(() => {
            if (_pollTimer) {
                clearInterval(_pollTimer);
                _pollTimer = null;
            }
        });
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class (includes clearInterval)
        TritiumStore.set('replay.active', false);
    },
};
