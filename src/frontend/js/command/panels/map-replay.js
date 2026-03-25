// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Map Replay Controls Panel
// Video-player-like interface for replaying tactical events on the map.
// Play/pause/speed/seek/loop controls. Shows events appearing chronologically
// with target movement trails.

import { TritiumStore } from '../store.js';
import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const SPEED_OPTIONS = [0.25, 0.5, 1, 2, 4, 8, 16];
const TRAIL_MAX_POINTS = 200;

export const MapReplayPanelDef = {
    id: 'map-replay',
    title: 'MAP REPLAY',
    defaultPosition: { x: null, y: 44 },
    defaultSize: { w: 420, h: 260 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'map-replay-panel';
        el.innerHTML = `
            <div class="mr-status-bar" style="display:flex;align-items:center;gap:6px;padding:4px 8px;border-bottom:1px solid var(--border, #1a1a2e);font-size:0.55rem;color:var(--text-ghost, #666)">
                <span class="mr-status-indicator" data-bind="status" style="width:6px;height:6px;border-radius:50%;background:#666;display:inline-block"></span>
                <span data-bind="status-text">STOPPED</span>
                <span style="flex:1"></span>
                <span data-bind="time-display" class="mono" style="color:var(--cyan, #00f0ff)">--:--:--</span>
            </div>

            <div class="mr-progress" style="padding:4px 8px">
                <div style="position:relative;height:16px;background:var(--surface-1, #0e0e14);border-radius:3px;cursor:pointer;border:1px solid var(--border, #1a1a2e)" data-bind="seekbar">
                    <div data-bind="progress-fill" style="position:absolute;left:0;top:0;height:100%;background:linear-gradient(90deg, #00f0ff33, #00f0ff);border-radius:3px;width:0%;transition:width 0.1s"></div>
                    <div data-bind="progress-cursor" style="position:absolute;top:-2px;width:3px;height:20px;background:#00f0ff;border-radius:1px;left:0%;transition:left 0.1s;box-shadow:0 0 4px #00f0ff"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.45rem;color:var(--text-ghost, #666);margin-top:2px">
                    <span data-bind="start-label" class="mono">00:00:00</span>
                    <span data-bind="duration-label" class="mono">0:00</span>
                    <span data-bind="end-label" class="mono">00:00:00</span>
                </div>
            </div>

            <div class="mr-controls" style="display:flex;align-items:center;justify-content:center;gap:8px;padding:6px 8px">
                <button data-action="step-back" title="Step back" style="background:none;border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 6px;cursor:pointer;border-radius:3px;font-size:0.6rem;font-family:var(--font-mono)">|&lt;</button>
                <button data-action="play-pause" title="Play/Pause" style="background:var(--cyan, #00f0ff);border:none;color:#0a0a0f;padding:4px 14px;cursor:pointer;border-radius:3px;font-size:0.7rem;font-weight:bold;font-family:var(--font-mono)">PLAY</button>
                <button data-action="stop" title="Stop" style="background:none;border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 8px;cursor:pointer;border-radius:3px;font-size:0.6rem;font-family:var(--font-mono)">STOP</button>
                <button data-action="step-fwd" title="Step forward" style="background:none;border:1px solid var(--border, #1a1a2e);color:var(--text, #ccc);padding:2px 6px;cursor:pointer;border-radius:3px;font-size:0.6rem;font-family:var(--font-mono)">&gt;|</button>
            </div>

            <div class="mr-speed-row" style="display:flex;align-items:center;justify-content:center;gap:4px;padding:2px 8px;font-size:0.5rem">
                <span style="color:var(--text-ghost, #666);margin-right:4px">SPEED:</span>
                ${SPEED_OPTIONS.map(s => `<button data-speed="${s}" style="background:${s === 1 ? 'var(--cyan, #00f0ff)' : 'var(--surface-1, #0e0e14)'};border:1px solid var(--border, #1a1a2e);color:${s === 1 ? '#0a0a0f' : 'var(--text, #ccc)'};padding:1px 5px;cursor:pointer;border-radius:2px;font-size:0.5rem;font-family:var(--font-mono)">${s}x</button>`).join('')}
            </div>

            <div class="mr-options" style="display:flex;align-items:center;gap:10px;padding:4px 8px;border-top:1px solid var(--border, #1a1a2e);font-size:0.5rem">
                <label style="color:var(--text-ghost, #666);display:flex;align-items:center;gap:3px;cursor:pointer">
                    <input type="checkbox" data-bind="loop" style="margin:0;accent-color:#00f0ff"> LOOP
                </label>
                <label style="color:var(--text-ghost, #666);display:flex;align-items:center;gap:3px;cursor:pointer">
                    <input type="checkbox" data-bind="trails" checked style="margin:0;accent-color:#05ffa1"> TRAILS
                </label>
                <span style="flex:1"></span>
                <span data-bind="event-count" style="color:var(--text-ghost, #666)" class="mono">0 events</span>
                <span data-bind="target-count" style="color:var(--green, #05ffa1)" class="mono">0 targets</span>
            </div>

            <div class="mr-event-feed" style="max-height:80px;overflow-y:auto;padding:2px 8px;font-size:0.45rem;border-top:1px solid var(--border, #1a1a2e)">
                <div data-bind="event-log" style="color:var(--text-ghost, #666)">No events loaded</div>
            </div>
        `;
        return el;
    },

    init(panel) {
        const el = panel.element;
        if (!el) return;

        // State
        const state = {
            playing: false,
            speed: 1,
            loop: false,
            trails: true,
            progress: 0,
            startTime: 0,
            endTime: 0,
            currentTime: 0,
            eventSource: null,
            events: [],
            snapshots: [],
        };

        panel._replayState = state;

        // Bind controls
        const playBtn = el.querySelector('[data-action="play-pause"]');
        const stopBtn = el.querySelector('[data-action="stop"]');
        const stepBackBtn = el.querySelector('[data-action="step-back"]');
        const stepFwdBtn = el.querySelector('[data-action="step-fwd"]');
        const seekbar = el.querySelector('[data-bind="seekbar"]');
        const loopCheck = el.querySelector('[data-bind="loop"]');
        const trailsCheck = el.querySelector('[data-bind="trails"]');

        if (playBtn) playBtn.addEventListener('click', () => togglePlayback(state, el));
        if (stopBtn) stopBtn.addEventListener('click', () => stopPlayback(state, el));
        if (stepBackBtn) stepBackBtn.addEventListener('click', () => stepPlayback(state, el, -1));
        if (stepFwdBtn) stepFwdBtn.addEventListener('click', () => stepPlayback(state, el, 1));

        if (seekbar) {
            seekbar.addEventListener('click', (e) => {
                const rect = seekbar.getBoundingClientRect();
                const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                seekToPercent(state, el, pct);
            });
        }

        if (loopCheck) loopCheck.addEventListener('change', () => { state.loop = loopCheck.checked; });
        if (trailsCheck) trailsCheck.addEventListener('change', () => {
            state.trails = trailsCheck.checked;
            EventBus.emit('replay:trails', { enabled: state.trails });
        });

        // Speed buttons
        el.querySelectorAll('[data-speed]').forEach(btn => {
            btn.addEventListener('click', () => {
                state.speed = parseFloat(btn.dataset.speed);
                updateSpeedButtons(el, state.speed);
                if (state.playing) {
                    // Restart with new speed
                    stopSSE(state);
                    startSSE(state, el);
                }
            });
        });

        // Listen for external replay requests
        EventBus.on('replay:start', (data) => {
            if (data && data.start && data.end) {
                state.startTime = data.start;
                state.endTime = data.end;
                updateTimeLabels(el, state);
                startPlayback(state, el);
            }
        });

        // Fetch available time range on init
        fetchTimeRange(state, el);
    },

    destroy(panel) {
        if (panel._replayState) {
            stopSSE(panel._replayState);
        }
    }
};

function formatTime(unix) {
    if (!unix) return '--:--:--';
    const d = new Date(unix * 1000);
    return d.toLocaleTimeString('en-US', { hour12: false });
}

function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function updateTimeLabels(el, state) {
    const startLabel = el.querySelector('[data-bind="start-label"]');
    const endLabel = el.querySelector('[data-bind="end-label"]');
    const durationLabel = el.querySelector('[data-bind="duration-label"]');

    if (startLabel) startLabel.textContent = formatTime(state.startTime);
    if (endLabel) endLabel.textContent = formatTime(state.endTime);
    if (durationLabel) durationLabel.textContent = formatDuration(state.endTime - state.startTime);
}

function updateProgress(el, state, progress) {
    state.progress = progress;
    const pct = Math.round(progress * 100);
    const fill = el.querySelector('[data-bind="progress-fill"]');
    const cursor = el.querySelector('[data-bind="progress-cursor"]');
    if (fill) fill.style.width = pct + '%';
    if (cursor) cursor.style.left = pct + '%';

    // Current time
    const currentTime = state.startTime + (state.endTime - state.startTime) * progress;
    state.currentTime = currentTime;
    const timeDisplay = el.querySelector('[data-bind="time-display"]');
    if (timeDisplay) timeDisplay.textContent = formatTime(currentTime);
}

function updateStatus(el, text, color) {
    const indicator = el.querySelector('[data-bind="status"]');
    const statusText = el.querySelector('[data-bind="status-text"]');
    if (indicator) indicator.style.background = color || '#666';
    if (statusText) statusText.textContent = text;
}

function updateSpeedButtons(el, activeSpeed) {
    el.querySelectorAll('[data-speed]').forEach(btn => {
        const s = parseFloat(btn.dataset.speed);
        if (s === activeSpeed) {
            btn.style.background = 'var(--cyan, #00f0ff)';
            btn.style.color = '#0a0a0f';
        } else {
            btn.style.background = 'var(--surface-1, #0e0e14)';
            btn.style.color = 'var(--text, #ccc)';
        }
    });
}

function updateCounts(el, eventCount, targetCount) {
    const ec = el.querySelector('[data-bind="event-count"]');
    const tc = el.querySelector('[data-bind="target-count"]');
    if (ec) ec.textContent = `${eventCount} events`;
    if (tc) tc.textContent = `${targetCount} targets`;
}

function appendEventLog(el, event) {
    const log = el.querySelector('[data-bind="event-log"]');
    if (!log) return;

    const line = document.createElement('div');
    line.style.cssText = 'padding:1px 0;border-bottom:1px solid #1a1a2e11';
    const ts = formatTime(event.timestamp);
    const type = event.type || 'event';
    const color = type === 'alert' ? '#ff2a6d' : type === 'sighting' ? '#05ffa1' : '#00f0ff';
    line.innerHTML = `<span class="mono" style="color:var(--text-ghost)">${_esc(ts)}</span> <span style="color:${color}">${_esc(type)}</span>`;
    log.appendChild(line);

    // Keep feed trimmed
    while (log.children.length > 50) {
        log.removeChild(log.firstChild);
    }

    log.scrollTop = log.scrollHeight;
}

async function fetchTimeRange(state, el) {
    try {
        const resp = await fetch('/api/playback/range');
        if (resp.ok) {
            const data = await resp.json();
            if (data.start && data.end && data.start !== data.end) {
                state.startTime = data.start;
                state.endTime = data.end;
                updateTimeLabels(el, state);
                updateStatus(el, `${data.snapshot_count} snapshots available`, '#05ffa1');
            } else {
                updateStatus(el, 'No playback data', '#666');
            }
        }
    } catch (err) {
        updateStatus(el, 'Connection error', '#ff2a6d');
    }
}

function togglePlayback(state, el) {
    if (state.playing) {
        pausePlayback(state, el);
    } else {
        startPlayback(state, el);
    }
}

function startPlayback(state, el) {
    if (!state.startTime || !state.endTime) {
        updateStatus(el, 'No time range set', '#fcee0a');
        return;
    }

    state.playing = true;
    const playBtn = el.querySelector('[data-action="play-pause"]');
    if (playBtn) {
        playBtn.textContent = 'PAUSE';
        playBtn.style.background = 'var(--magenta, #ff2a6d)';
    }
    updateStatus(el, 'PLAYING', '#05ffa1');

    // Clear event log
    const log = el.querySelector('[data-bind="event-log"]');
    if (log) log.innerHTML = '';

    startSSE(state, el);
}

function pausePlayback(state, el) {
    state.playing = false;
    stopSSE(state);

    const playBtn = el.querySelector('[data-action="play-pause"]');
    if (playBtn) {
        playBtn.textContent = 'PLAY';
        playBtn.style.background = 'var(--cyan, #00f0ff)';
    }
    updateStatus(el, 'PAUSED', '#fcee0a');
}

function stopPlayback(state, el) {
    state.playing = false;
    stopSSE(state);
    updateProgress(el, state, 0);

    const playBtn = el.querySelector('[data-action="play-pause"]');
    if (playBtn) {
        playBtn.textContent = 'PLAY';
        playBtn.style.background = 'var(--cyan, #00f0ff)';
    }
    updateStatus(el, 'STOPPED', '#666');
    updateCounts(el, 0, 0);

    EventBus.emit('replay:stop', {});
}

function stepPlayback(state, el, direction) {
    // Seek by 5% of total duration
    const step = 0.05 * direction;
    const newProgress = Math.max(0, Math.min(1, state.progress + step));
    const newTime = state.startTime + (state.endTime - state.startTime) * newProgress;

    updateProgress(el, state, newProgress);

    // Fetch state at this timestamp
    fetch(`/api/playback/state?timestamp=${newTime}`)
        .then(r => r.json())
        .then(data => {
            EventBus.emit('replay:frame', {
                timestamp: newTime,
                targets: data.targets || [],
                events: data.events || [],
            });
        })
        .catch(() => {});
}

function seekToPercent(state, el, pct) {
    const newTime = state.startTime + (state.endTime - state.startTime) * pct;
    updateProgress(el, state, pct);

    if (state.playing) {
        stopSSE(state);
        // Restart SSE from new position
        state.startTime = newTime;
        startSSE(state, el);
    } else {
        fetch(`/api/playback/state?timestamp=${newTime}`)
            .then(r => r.json())
            .then(data => {
                EventBus.emit('replay:frame', {
                    timestamp: newTime,
                    targets: data.targets || [],
                    events: data.events || [],
                });
            })
            .catch(() => {});
    }
}

function startSSE(state, el) {
    stopSSE(state);

    const url = `/api/playback/replay?start=${state.startTime}&end=${state.endTime}&speed=${state.speed}`;
    const es = new EventSource(url);
    state.eventSource = es;

    let totalTargets = new Set();

    es.onmessage = (e) => {
        try {
            const data = JSON.parse(e.data);

            if (data.error) {
                updateStatus(el, data.error, '#ff2a6d');
                return;
            }

            // Update progress
            if (data.progress !== undefined) {
                updateProgress(el, state, data.progress);
            }

            // Track targets
            if (data.targets) {
                data.targets.forEach(t => {
                    const tid = t.target_id || t.id || '';
                    if (tid) totalTargets.add(tid);
                });
            }

            // Update counts
            const eventCount = data.index !== undefined ? data.index + 1 : 0;
            updateCounts(el, eventCount, totalTargets.size);

            // Log significant events
            if (data.events && data.events.length > 0) {
                data.events.forEach(ev => appendEventLog(el, ev));
            }

            // Emit frame to map
            EventBus.emit('replay:frame', {
                timestamp: data.timestamp,
                targets: data.targets || [],
                events: data.events || [],
                progress: data.progress || 0,
                trails: state.trails,
            });

        } catch (err) {
            // ignore parse errors
        }
    };

    es.addEventListener('done', () => {
        stopSSE(state);

        if (state.loop && state.playing) {
            // Restart from beginning
            updateProgress(el, state, 0);
            startSSE(state, el);
        } else {
            state.playing = false;
            const playBtn = el.querySelector('[data-action="play-pause"]');
            if (playBtn) {
                playBtn.textContent = 'PLAY';
                playBtn.style.background = 'var(--cyan, #00f0ff)';
            }
            updateStatus(el, 'COMPLETE', '#05ffa1');
        }
    });

    es.onerror = () => {
        stopSSE(state);
        state.playing = false;
        updateStatus(el, 'CONNECTION LOST', '#ff2a6d');

        const playBtn = el.querySelector('[data-action="play-pause"]');
        if (playBtn) {
            playBtn.textContent = 'PLAY';
            playBtn.style.background = 'var(--cyan, #00f0ff)';
        }
    };
}

function stopSSE(state) {
    if (state.eventSource) {
        state.eventSource.close();
        state.eventSource = null;
    }
}
