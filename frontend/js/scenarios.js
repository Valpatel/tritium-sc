/**
 * SCENARIOS — Synthetic World Testing Dashboard
 * Run, evaluate, and rate Amy's behavioral scenarios.
 * Live MJPEG video feed + SSE event stream + browser TTS.
 */

const scenarioState = {
    scenarios: [],
    selectedScenario: null,
    activeRun: null,
    eventSource: null,
    ttsEnabled: true,
    ttsVoice: null,
    usePiperTts: false,
    piperVoices: [],
    _currentAudio: null,
};

/**
 * Initialize the Scenarios view.
 */
function initScenariosView() {
    if (document.getElementById('scenarios-initialized')) return;

    const container = document.getElementById('view-scenarios');
    if (!container) return;

    container.innerHTML = buildScenariosHTML();

    const marker = document.createElement('div');
    marker.id = 'scenarios-initialized';
    marker.style.display = 'none';
    container.appendChild(marker);

    // Pick a TTS voice
    _pickTtsVoice();
    if (typeof speechSynthesis !== 'undefined') {
        speechSynthesis.onvoiceschanged = _pickTtsVoice;
    }

    loadScenarios();
}

async function _pickTtsVoice() {
    // Try server-side Piper TTS first
    try {
        const resp = await fetch('/api/tts/voices');
        if (resp.ok) {
            const data = await resp.json();
            if (data.piper_available && data.voices.length > 0) {
                scenarioState.usePiperTts = true;
                scenarioState.piperVoices = data.voices;
                scenarioState.ttsVoice = data.voices[0].id;
                _populatePiperVoicePicker(data.voices);
                return;
            }
        }
    } catch { /* Piper unavailable — fall through to browser TTS */ }

    // Fall back to browser speechSynthesis
    scenarioState.usePiperTts = false;
    if (typeof speechSynthesis === 'undefined') return;
    const voices = speechSynthesis.getVoices();
    if (!voices.length) return;

    const good = voices.filter(v => v.lang === 'en-US' || v.lang === 'en-GB');
    scenarioState.ttsVoice =
        good.find(v => v.name.includes('Google') && v.lang === 'en-US') ||
        good.find(v => v.name.includes('Google')) ||
        good.find(v => v.lang === 'en-US') ||
        good.find(v => v.lang === 'en-GB') ||
        voices.find(v => v.lang === 'en-US') ||
        voices[0] || null;

    _populateVoicePicker(voices);
}

function _populatePiperVoicePicker(voices) {
    const sel = document.getElementById('scenarios-voice-select');
    if (!sel) return;

    // Clear existing options except the placeholder
    while (sel.options.length > 1) sel.remove(1);

    voices.forEach((v) => {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.textContent = `${v.name} (${v.language}, ${v.quality}) [Piper]`;
        if (scenarioState.ttsVoice === v.id) opt.selected = true;
        sel.appendChild(opt);
    });

    sel.onchange = () => {
        scenarioState.ttsVoice = sel.value;
        speakText('Voice changed.');
    };
}

function _populateVoicePicker(voices) {
    const sel = document.getElementById('scenarios-voice-select');
    if (!sel || sel.options.length > 1) return;

    const enVoices = voices.filter(v => v.lang.startsWith('en'));
    enVoices.forEach((v, i) => {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = `${v.name} (${v.lang})`;
        opt.dataset.voiceName = v.name;
        if (scenarioState.ttsVoice && v.name === scenarioState.ttsVoice.name) {
            opt.selected = true;
        }
        sel.appendChild(opt);
    });

    sel.onchange = () => {
        const idx = parseInt(sel.value);
        if (!isNaN(idx) && enVoices[idx]) {
            scenarioState.ttsVoice = enVoices[idx];
            speakText('Voice changed.');
        }
    };
}

function buildScenariosHTML() {
    return `
    <div class="scenarios-dashboard">
        <!-- Top: Scenario List + Video -->
        <div class="scenarios-top-row">
            <!-- Left: Scenario Library -->
            <div class="scenarios-panel scenarios-library-panel">
                <div class="scenarios-panel-header">
                    <span class="scenarios-panel-title">SCENARIO LIBRARY</span>
                    <span class="scenarios-cache-badge" id="scenarios-cache-badge" title="Image cache status">--</span>
                    <span class="scenarios-count" id="scenarios-count">0</span>
                </div>
                <div class="scenarios-list" id="scenarios-list">
                    <div class="text-muted" style="padding: 12px;">Loading scenarios...</div>
                </div>
            </div>

            <!-- Right: Live Video + Run Controls -->
            <div class="scenarios-panel scenarios-run-panel">
                <div class="scenarios-panel-header">
                    <span class="scenarios-panel-title">SYNTHETIC CAMERA</span>
                    <span class="scenarios-run-badge" id="scenarios-run-badge">IDLE</span>
                </div>
                <div class="scenarios-run-area" id="scenarios-run-area">
                    <div class="scenarios-video-container" id="scenarios-video-container">
                        <img id="scenarios-video-feed" class="scenarios-video-feed"
                             alt="Synthetic camera feed" />
                        <div class="scenarios-video-overlay" id="scenarios-video-overlay">
                            <div style="font-size: 1.5rem; color: var(--cyan);">&#x25CE;</div>
                            <div>NO FEED</div>
                            <div class="text-muted" style="font-size: 0.7rem; margin-top: 4px;">
                                Select a scenario and click RUN
                            </div>
                        </div>
                        <div class="scenarios-speech-bubble" id="scenarios-speech-bubble"></div>
                    </div>
                    <div class="scenarios-run-controls" id="scenarios-run-controls">
                        <div id="scenarios-run-info" class="scenarios-run-info"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Bottom: Live Timeline + Scoring -->
        <div class="scenarios-bottom-row">
            <!-- Left: Live Action Feed -->
            <div class="scenarios-panel scenarios-timeline-panel">
                <div class="scenarios-panel-header">
                    <span class="scenarios-panel-title">LIVE FEED</span>
                    <span class="scenarios-action-count" id="scenarios-action-count">0 actions</span>
                    <select id="scenarios-voice-select" class="scenarios-voice-select"
                            title="Choose Amy's voice">
                        <option value="" disabled>Voice...</option>
                    </select>
                    <label class="scenarios-tts-toggle" title="Toggle Amy's voice">
                        <input type="checkbox" id="scenarios-tts-check" checked
                               onchange="scenarioState.ttsEnabled = this.checked" />
                        <span class="scenarios-tts-label">TTS</span>
                    </label>
                </div>
                <div class="scenarios-timeline" id="scenarios-timeline">
                    <div class="text-muted" style="padding: 12px;">Run a scenario to see live events...</div>
                </div>
            </div>

            <!-- Right: Scoring + Rating -->
            <div class="scenarios-panel scenarios-score-panel">
                <div class="scenarios-panel-header">
                    <span class="scenarios-panel-title">EVALUATION</span>
                </div>
                <div class="scenarios-score-area" id="scenarios-score-area">
                    <div class="scenarios-score-grid">
                        <div class="scenarios-stat">
                            <div class="scenarios-stat-label">SCORE</div>
                            <div class="scenarios-stat-value" id="scenarios-score-total">--</div>
                        </div>
                        <div class="scenarios-stat">
                            <div class="scenarios-stat-label">MATCHED</div>
                            <div class="scenarios-stat-value" id="scenarios-score-matched">--</div>
                        </div>
                        <div class="scenarios-stat">
                            <div class="scenarios-stat-label">DETECTION</div>
                            <div class="scenarios-stat-value" id="scenarios-score-detection">--</div>
                        </div>
                        <div class="scenarios-stat">
                            <div class="scenarios-stat-label">LATENCY</div>
                            <div class="scenarios-stat-value" id="scenarios-score-latency">--</div>
                        </div>
                    </div>
                    <div class="scenarios-rating" id="scenarios-rating" style="display: none;">
                        <div class="scenarios-rating-label">HUMAN RATING</div>
                        <div class="scenarios-stars" id="scenarios-stars">
                            <button class="scenarios-star" onclick="rateScenario(1)">&#9733;</button>
                            <button class="scenarios-star" onclick="rateScenario(2)">&#9733;</button>
                            <button class="scenarios-star" onclick="rateScenario(3)">&#9733;</button>
                            <button class="scenarios-star" onclick="rateScenario(4)">&#9733;</button>
                            <button class="scenarios-star" onclick="rateScenario(5)">&#9733;</button>
                        </div>
                    </div>
                    <div class="scenarios-score-details" id="scenarios-score-details"></div>
                </div>
            </div>
        </div>
    </div>
    `;
}

// --- API calls ---

async function loadScenarios() {
    try {
        const resp = await fetch('/api/scenarios');
        if (!resp.ok) return;
        scenarioState.scenarios = await resp.json();
        renderScenarioList();
    } catch {
        console.error('[SCENARIOS] Failed to load scenarios');
    }

    // Check image cache status
    try {
        const resp = await fetch('/api/scenarios/cache');
        if (resp.ok) {
            const cache = await resp.json();
            const badge = document.getElementById('scenarios-cache-badge');
            if (badge) {
                if (cache.has_cache) {
                    badge.textContent = `HD ${cache.backgrounds}bg ${cache.people}ppl`;
                    badge.classList.add('scenarios-cache-ready');
                } else {
                    badge.textContent = 'NO IMAGES';
                    badge.classList.add('scenarios-cache-missing');
                    badge.title = 'Run: .venv/bin/python3 -m amy.scenarios.pregen';
                }
            }
        }
    } catch { /* ignore */ }
}

function renderScenarioList() {
    const list = document.getElementById('scenarios-list');
    const count = document.getElementById('scenarios-count');
    if (!list) return;

    if (count) count.textContent = scenarioState.scenarios.length;

    if (scenarioState.scenarios.length === 0) {
        list.innerHTML = '<div class="text-muted" style="padding: 12px;">No scenarios found</div>';
        return;
    }

    list.innerHTML = scenarioState.scenarios.map(s => {
        const score = s.latest_score;
        let scoreClass = 'scenarios-score-none';
        let scoreText = '--';
        if (score !== null && score !== undefined) {
            scoreText = Math.round(score * 100) + '%';
            scoreClass = score > 0.8 ? 'scenarios-score-good' : score > 0.5 ? 'scenarios-score-ok' : 'scenarios-score-bad';
        }
        const selected = scenarioState.selectedScenario === s.name ? 'active' : '';
        return `
            <div class="scenarios-item ${selected}" onclick="selectScenario('${s.name}')">
                <div class="scenarios-item-top">
                    <span class="scenarios-item-name">${s.name.replace(/_/g, ' ').toUpperCase()}</span>
                    <span class="scenarios-item-score ${scoreClass}">${scoreText}</span>
                </div>
                <div class="scenarios-item-desc">${s.description || ''}</div>
                <div class="scenarios-item-meta">
                    <span>${s.event_count || 0} events</span>
                    <span>${s.expected_count || 0} checks</span>
                    <span>${s.duration || 0}s</span>
                    <span>${s.run_count || 0} runs</span>
                </div>
            </div>
        `;
    }).join('');
}

async function selectScenario(name) {
    scenarioState.selectedScenario = name;
    renderScenarioList();

    try {
        const resp = await fetch(`/api/scenarios/${name}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const scenario = data.scenario;

        const info = document.getElementById('scenarios-run-info');
        if (info) {
            info.innerHTML = `
                <h3 class="text-cyan" style="margin: 0 0 6px 0; font-size: 0.9rem;">
                    ${scenario.name.replace(/_/g, ' ').toUpperCase()}
                </h3>
                <p class="text-muted" style="margin: 0 0 8px 0; font-size: 0.75rem;">
                    ${scenario.description || ''}
                </p>
                <div class="scenarios-meta-grid">
                    <div><span class="text-muted">Duration:</span> ${scenario.duration}s</div>
                    <div><span class="text-muted">Scale:</span> ${scenario.time_scale}x</div>
                    <div><span class="text-muted">People:</span> ${(scenario.people || []).length}</div>
                    <div><span class="text-muted">Events:</span> ${(scenario.events || []).length}</div>
                </div>
                <div style="margin-top: 10px;">
                    <button class="btn btn-cyber" onclick="runScenario('${scenario.name}')"
                            id="scenarios-run-btn" style="padding: 6px 20px;">
                        &#x25B6; RUN
                    </button>
                </div>
                ${data.results && data.results.length > 0 ? `
                    <div style="margin-top: 10px; border-top: 1px solid rgba(0, 240, 255, 0.15); padding-top: 8px;">
                        <div class="text-muted" style="font-size: 0.65rem; margin-bottom: 4px;">RECENT RUNS</div>
                        ${data.results.slice(0, 3).map(r => `
                            <div class="scenarios-history-item" onclick="loadRunResult('${r.run_id}')">
                                <span>${r.run_id}</span>
                                <span class="${r.score.total_score > 0.8 ? 'text-green' : r.score.total_score > 0.5 ? 'text-yellow' : 'text-magenta'}">
                                    ${Math.round(r.score.total_score * 100)}%
                                </span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            `;
        }
    } catch (e) {
        console.error('[SCENARIOS] Failed to load scenario:', e);
    }
}

// --- Run + Live Streaming ---

async function runScenario(name) {
    const btn = document.getElementById('scenarios-run-btn');
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'STARTING...';
    }

    const badge = document.getElementById('scenarios-run-badge');
    if (badge) {
        badge.textContent = 'STARTING';
        badge.className = 'scenarios-run-badge scenarios-run-active';
    }

    // Clear previous
    clearTimeline();
    clearScore();
    stopVideoFeed();
    stopEventStream();

    try {
        const resp = await fetch('/api/scenarios/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        scenarioState.activeRun = data.run_id;

        if (badge) {
            badge.textContent = 'RUNNING';
        }
        if (btn) {
            btn.textContent = 'RUNNING...';
        }

        // Start live video feed
        startVideoFeed(data.run_id);

        // Start live event stream
        startEventStream(data.run_id);

        if (typeof showNotification !== 'undefined') {
            showNotification('SCENARIO', `Running: ${name}`, 'info');
        }
    } catch (e) {
        if (btn) {
            btn.disabled = false;
            btn.textContent = 'RUN';
        }
        if (badge) {
            badge.textContent = 'FAILED';
            badge.className = 'scenarios-run-badge scenarios-run-failed';
        }
        console.error('[SCENARIOS] Run failed:', e);
    }
}

// --- Video Feed ---

function startVideoFeed(runId) {
    const img = document.getElementById('scenarios-video-feed');
    const overlay = document.getElementById('scenarios-video-overlay');
    if (!img) return;

    img.src = `/api/scenarios/run/${runId}/video`;
    img.style.display = 'block';
    if (overlay) overlay.style.display = 'none';

    img.onerror = () => {
        // Feed ended — show last frame or overlay
        setTimeout(() => {
            if (scenarioState.activeRun === runId) {
                // Keep the last frame visible
            }
        }, 500);
    };
}

function stopVideoFeed() {
    const img = document.getElementById('scenarios-video-feed');
    const overlay = document.getElementById('scenarios-video-overlay');
    if (img) {
        img.src = '';
        img.style.display = 'none';
    }
    if (overlay) overlay.style.display = 'flex';
}

// --- SSE Event Stream ---

function startEventStream(runId) {
    stopEventStream();

    const es = new EventSource(`/api/scenarios/run/${runId}/stream`);
    scenarioState.eventSource = es;

    es.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'action') {
                handleLiveAction(msg.data);
            } else if (msg.type === 'finished') {
                stopEventStream();
                // Fetch final result
                pollRunStatus(runId);
            }
        } catch { /* ignore parse errors */ }
    };

    es.onerror = () => {
        // SSE closed — check run status
        stopEventStream();
        pollRunStatus(runId);
    };
}

function stopEventStream() {
    if (scenarioState.eventSource) {
        scenarioState.eventSource.close();
        scenarioState.eventSource = null;
    }
}

function handleLiveAction(action) {
    // Add to timeline
    appendTimelineAction(action);

    // Speech bubble + TTS
    if (action.action_type === 'say' && action.category === 'speech') {
        showSpeechBubble(action.text);
        speakText(action.text);
    }

    // Thought overlay
    if (action.action_type === 'think') {
        showThoughtOverlay(action.text);
    }

    // Detection flash
    if (action.category === 'detection') {
        flashDetection(action.text);
    }
}

// --- Speech Bubble (overlaid on video) ---

function showSpeechBubble(text) {
    const bubble = document.getElementById('scenarios-speech-bubble');
    if (!bubble) return;

    bubble.textContent = text.length > 120 ? text.substring(0, 117) + '...' : text;
    bubble.classList.add('visible');

    clearTimeout(bubble._hideTimer);
    bubble._hideTimer = setTimeout(() => {
        bubble.classList.remove('visible');
    }, Math.max(4000, text.length * 60));
}

function showThoughtOverlay(text) {
    const container = document.getElementById('scenarios-video-container');
    if (!container) return;

    // Remove previous thought
    const prev = container.querySelector('.scenarios-thought-flash');
    if (prev) prev.remove();

    const el = document.createElement('div');
    el.className = 'scenarios-thought-flash';
    el.textContent = text.length > 80 ? text.substring(0, 77) + '...' : text;
    container.appendChild(el);

    setTimeout(() => el.remove(), 3000);
}

function flashDetection(text) {
    const container = document.getElementById('scenarios-video-container');
    if (!container) return;

    container.classList.add('scenarios-detect-flash');
    setTimeout(() => container.classList.remove('scenarios-detect-flash'), 600);
}

// --- TTS (Piper server-side with browser fallback) ---

function speakText(text) {
    if (!scenarioState.ttsEnabled) return;

    if (scenarioState.usePiperTts) {
        _speakPiper(text);
    } else {
        _speakBrowser(text);
    }
}

async function _speakPiper(text) {
    // Cancel previous audio
    if (scenarioState._currentAudio) {
        scenarioState._currentAudio.pause();
        scenarioState._currentAudio = null;
    }

    try {
        const resp = await fetch('/api/tts/synthesize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text: text,
                voice: scenarioState.ttsVoice || undefined,
            }),
        });

        if (!resp.ok) {
            _speakBrowser(text);
            return;
        }

        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const audio = new Audio(url);
        scenarioState._currentAudio = audio;
        audio.onended = () => {
            URL.revokeObjectURL(url);
            if (scenarioState._currentAudio === audio) {
                scenarioState._currentAudio = null;
            }
        };
        audio.play().catch(() => _speakBrowser(text));
    } catch {
        _speakBrowser(text);
    }
}

function _speakBrowser(text) {
    if (typeof speechSynthesis === 'undefined') return;

    speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.1;
    utterance.volume = 0.8;
    if (scenarioState.ttsVoice && typeof scenarioState.ttsVoice === 'object') {
        utterance.voice = scenarioState.ttsVoice;
    }
    speechSynthesis.speak(utterance);
}

// --- Live Timeline ---

function clearTimeline() {
    const el = document.getElementById('scenarios-timeline');
    const countEl = document.getElementById('scenarios-action-count');
    if (el) el.innerHTML = '<div class="text-muted" style="padding: 12px;">Waiting for events...</div>';
    if (countEl) countEl.textContent = '0 actions';
    scenarioState._actionCount = 0;
}

function appendTimelineAction(a) {
    const el = document.getElementById('scenarios-timeline');
    const countEl = document.getElementById('scenarios-action-count');
    if (!el) return;

    // Clear placeholder on first action
    if (!scenarioState._actionCount) {
        el.innerHTML = '';
    }
    scenarioState._actionCount = (scenarioState._actionCount || 0) + 1;
    if (countEl) countEl.textContent = scenarioState._actionCount + ' actions';

    const catClass = 'scenarios-cat-' + (a.category || 'event');
    const time = a.timestamp !== undefined ? a.timestamp.toFixed(1) + 's' : '--';
    const text = a.text || '';

    const row = document.createElement('div');
    row.className = 'scenarios-action ' + catClass;
    row.innerHTML = `
        <span class="scenarios-action-time">${time}</span>
        <span class="scenarios-action-type">${a.action_type || a.category || '?'}</span>
        <span class="scenarios-action-text">${escapeHtmlScenarios(text.substring(0, 120))}</span>
    `;
    el.appendChild(row);

    // Auto-scroll to latest
    el.scrollTop = el.scrollHeight;
}

function renderTimeline(actions) {
    const el = document.getElementById('scenarios-timeline');
    const countEl = document.getElementById('scenarios-action-count');
    if (!el) return;

    if (countEl) countEl.textContent = `${actions.length} actions`;

    if (actions.length === 0) {
        el.innerHTML = '<div class="text-muted" style="padding: 12px;">No actions recorded</div>';
        return;
    }

    el.innerHTML = actions.map(a => {
        const catClass = 'scenarios-cat-' + (a.category || 'event');
        const time = a.timestamp !== undefined ? a.timestamp.toFixed(1) + 's' : '--';
        const text = a.text || '';
        return `
            <div class="scenarios-action ${catClass}">
                <span class="scenarios-action-time">${time}</span>
                <span class="scenarios-action-type">${a.action_type || a.category || '?'}</span>
                <span class="scenarios-action-text">${escapeHtmlScenarios(text.substring(0, 120))}</span>
            </div>
        `;
    }).join('');
}

// --- Scoring ---

function clearScore() {
    ['scenarios-score-total', 'scenarios-score-matched', 'scenarios-score-detection', 'scenarios-score-latency'].forEach(id => {
        const el = document.getElementById(id);
        if (el) { el.textContent = '--'; el.className = 'scenarios-stat-value'; }
    });
    const rating = document.getElementById('scenarios-rating');
    if (rating) rating.style.display = 'none';
    const details = document.getElementById('scenarios-score-details');
    if (details) details.innerHTML = '';
}

function renderScore(score, runId) {
    const totalEl = document.getElementById('scenarios-score-total');
    const matchEl = document.getElementById('scenarios-score-matched');
    const detEl = document.getElementById('scenarios-score-detection');
    const latEl = document.getElementById('scenarios-score-latency');

    if (totalEl) {
        const pct = Math.round((score.total_score || 0) * 100);
        totalEl.textContent = pct + '%';
        totalEl.className = 'scenarios-stat-value ' + (pct > 80 ? 'text-green' : pct > 50 ? 'text-yellow' : 'text-magenta');
    }
    if (matchEl) matchEl.textContent = `${score.matched || 0}/${score.total_expected || 0}`;
    if (detEl) detEl.textContent = Math.round((score.detection_accuracy || 0) * 100) + '%';
    if (latEl) latEl.textContent = (score.avg_response_latency || 0).toFixed(1) + 's';

    // Show rating
    const ratingEl = document.getElementById('scenarios-rating');
    if (ratingEl && runId) {
        ratingEl.style.display = 'block';
        ratingEl.dataset.runId = runId;
    }

    // Score details
    const detailsEl = document.getElementById('scenarios-score-details');
    if (detailsEl && score.details) {
        detailsEl.innerHTML = score.details.map(d => {
            const icon = d.matched ? '<span class="text-green">&#x2713;</span>' : '<span class="text-magenta">&#x2717;</span>';
            const info = d.matched
                ? `${escapeHtmlScenarios((d.action_text || d.expected).substring(0, 60))} @ ${(d.timestamp || 0).toFixed(1)}s`
                : escapeHtmlScenarios(d.reason || 'Not matched');
            return `<div class="scenarios-detail-row">${icon} <span class="text-muted">${d.expected}</span> ${info}</div>`;
        }).join('');
    }

    // Behavioral profile
    if (score.behavioral) {
        renderBehavioral(score.behavioral);
    }
}

function renderBehavioral(profile) {
    const container = document.getElementById('scenarios-score-area');
    if (!container) return;

    // Remove previous behavioral panel if present
    const prev = container.querySelector('.behavioral-profile');
    if (prev) prev.remove();

    const metrics = [
        { key: 'verbosity', label: 'Verbosity' },
        { key: 'lexical_diversity', label: 'Lex Diversity' },
        { key: 'think_speak_balance', label: 'Think/Speak' },
        { key: 'responsiveness', label: 'Response' },
        { key: 'initiative', label: 'Initiative' },
        { key: 'emotional_coherence', label: 'Emotion' },
        { key: 'safety', label: 'Safety' },
    ];

    const composite = profile.composite_score || 0;
    const compositeColor = composite > 0.7 ? 'text-green' : composite > 0.4 ? 'text-yellow' : 'text-magenta';

    const bars = metrics.map(m => {
        const val = profile[m.key] || 0;
        const pct = Math.round(val * 100);
        const colorClass = pct >= 70 ? 'beh-green' : pct >= 40 ? 'beh-yellow' : 'beh-magenta';
        return `
            <div class="behavioral-meter">
                <span class="behavioral-meter-label">${m.label}</span>
                <div class="behavioral-meter-bar">
                    <div class="behavioral-meter-fill ${colorClass}" style="width: ${pct}%"></div>
                </div>
                <span class="behavioral-meter-value">${pct}%</span>
            </div>
        `;
    }).join('');

    const panel = document.createElement('div');
    panel.className = 'behavioral-profile';
    panel.innerHTML = `
        <div class="behavioral-header">BEHAVIORAL PROFILE</div>
        <div class="behavioral-composite">
            <div class="behavioral-composite-value ${compositeColor}">${Math.round(composite * 100)}%</div>
            <div class="behavioral-composite-label">Composite Score</div>
        </div>
        ${bars}
        <div class="behavioral-counts">
            ${profile.speech_count || 0} speech | ${profile.thought_count || 0} thoughts | ${profile.goal_count || 0} goals | ${profile.user_utterance_count || 0} user msgs
        </div>
    `;
    container.appendChild(panel);

async function pollRunStatus(runId) {
    const poll = async () => {
        try {
            const resp = await fetch(`/api/scenarios/run/${runId}`);
            if (!resp.ok) return;
            const data = await resp.json();

            if (data.status === 'completed') {
                displayRunResult(data);
                return;
            }
            if (data.status === 'failed') {
                displayRunError(data.error || 'Unknown error');
                return;
            }
            // Still running — poll again
            setTimeout(poll, 2000);
        } catch {
            setTimeout(poll, 3000);
        }
    };
    poll();
}

function displayRunResult(result) {
    const btn = document.getElementById('scenarios-run-btn');
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'RUN';
    }

    const badge = document.getElementById('scenarios-run-badge');
    if (badge) {
        badge.textContent = 'COMPLETED';
        badge.className = 'scenarios-run-badge scenarios-run-complete';
    }

    // Full timeline (may have more actions than SSE delivered)
    renderTimeline(result.actions || []);

    // Score
    renderScore(result.score || {}, result.run_id);

    if (typeof showNotification !== 'undefined') {
        const pct = Math.round((result.score?.total_score || 0) * 100);
        showNotification('SCENARIO', `Complete: ${pct}% score`, pct > 80 ? 'success' : 'info');
    }

    // Refresh scenario list to update scores
    loadScenarios();
}

function displayRunError(error) {
    const btn = document.getElementById('scenarios-run-btn');
    if (btn) {
        btn.disabled = false;
        btn.textContent = 'RUN';
    }

    const badge = document.getElementById('scenarios-run-badge');
    if (badge) {
        badge.textContent = 'FAILED';
        badge.className = 'scenarios-run-badge scenarios-run-failed';
    }

    stopVideoFeed();

    if (typeof showNotification !== 'undefined') {
        showNotification('SCENARIO', `Failed: ${error}`, 'error');
    }
}

async function loadRunResult(runId) {
    try {
        const resp = await fetch(`/api/scenarios/run/${runId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.status === 'completed') {
            displayRunResult(data);
        }
    } catch { /* ignore */ }
}

// --- Rating ---

async function rateScenario(rating) {
    const ratingEl = document.getElementById('scenarios-rating');
    const runId = ratingEl?.dataset?.runId;
    if (!runId) return;

    const stars = document.querySelectorAll('.scenarios-star');
    stars.forEach((star, i) => {
        star.classList.toggle('active', i < rating);
    });

    try {
        await fetch(`/api/scenarios/run/${runId}/rate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rating }),
        });
        if (typeof showNotification !== 'undefined') {
            showNotification('RATED', `${rating}/5 stars`, 'success');
        }
    } catch { /* ignore */ }
}

// --- Utilities ---

function escapeHtmlScenarios(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
