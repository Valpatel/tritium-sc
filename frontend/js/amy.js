/**
 * AMY - AI Commander Dashboard
 * Cyberpunk consciousness interface for TRITIUM-SC
 */

// Amy dashboard state
const amyState = {
    eventSource: null,
    connected: false,
    thoughts: [],
    maxThoughts: 200,
    mood: 'neutral',
    state: 'idle',
    autoChat: false,
    nodes: {},
    videoNode: null,
};

/**
 * Initialize the Amy view — called when switching to the AMY tab.
 */
function initAmyView() {
    // Only init once
    if (document.getElementById('amy-initialized')) return;

    const container = document.getElementById('view-amy');
    if (!container) return;

    container.innerHTML = buildAmyHTML();

    // Mark as initialized
    const marker = document.createElement('div');
    marker.id = 'amy-initialized';
    marker.style.display = 'none';
    container.appendChild(marker);

    // Start SSE thoughts stream
    connectAmyThoughts();

    // Load initial status
    fetchAmyStatus();

    // Periodically refresh status
    setInterval(fetchAmyStatus, 5000);
}

/**
 * Build the Amy dashboard HTML.
 */
function buildAmyHTML() {
    return `
    <div class="amy-dashboard">
        <!-- Top Row: Video + Status -->
        <div class="amy-top-row">
            <!-- Video Feed -->
            <div class="amy-panel amy-video-panel">
                <div class="amy-panel-header">
                    <span class="amy-panel-title">PRIMARY OPTICS</span>
                    <div class="amy-optics-tabs">
                        <button class="amy-optics-tab active" data-tab="live" onclick="amySwitchOpticsTab('live')">LIVE</button>
                        <button class="amy-optics-tab" data-tab="gallery" onclick="amySwitchOpticsTab('gallery')">GALLERY</button>
                    </div>
                    <span class="amy-video-node" id="amy-video-node">--</span>
                </div>
                <div class="amy-video-container" id="amy-video-container" data-active-tab="live">
                    <div class="amy-optics-live" id="amy-optics-live">
                        <div class="amy-no-feed" id="amy-no-feed">
                            <div class="amy-no-feed-icon">&#x25C9;</div>
                            <div>NO CAMERA CONNECTED</div>
                            <div class="amy-no-feed-sub">Waiting for sensor node...</div>
                        </div>
                        <img id="amy-video-feed" class="amy-video-feed" style="display:none;"
                             alt="Amy camera feed">
                    </div>
                    <div class="amy-optics-gallery" id="amy-optics-gallery" style="display:none;">
                        <div class="amy-gallery-grid" id="amy-gallery-grid">
                            <div class="amy-gallery-empty">No photos saved yet</div>
                        </div>
                    </div>
                </div>
                <!-- Lightbox -->
                <div class="amy-lightbox" id="amy-lightbox" style="display:none;" onclick="amyCloseLightbox()">
                    <img id="amy-lightbox-img" class="amy-lightbox-img" alt="Photo">
                    <div class="amy-lightbox-caption" id="amy-lightbox-caption"></div>
                </div>
            </div>

            <!-- Status Panel -->
            <div class="amy-panel amy-status-panel">
                <div class="amy-panel-header">
                    <span class="amy-panel-title">COMMANDER STATUS</span>
                    <span class="amy-state-badge" id="amy-state-badge">OFFLINE</span>
                </div>
                <div class="amy-status-grid">
                    <div class="amy-stat">
                        <div class="amy-stat-label">STATE</div>
                        <div class="amy-stat-value" id="amy-stat-state">--</div>
                    </div>
                    <div class="amy-stat">
                        <div class="amy-stat-label">MOOD</div>
                        <div class="amy-stat-value" id="amy-stat-mood">--</div>
                    </div>
                    <div class="amy-stat">
                        <div class="amy-stat-label">THINKING</div>
                        <div class="amy-stat-value" id="amy-stat-thinking">--</div>
                    </div>
                    <div class="amy-stat">
                        <div class="amy-stat-label">NODES</div>
                        <div class="amy-stat-value" id="amy-stat-nodes">0</div>
                    </div>
                    <div class="amy-stat">
                        <div class="amy-stat-label">PAN</div>
                        <div class="amy-stat-value" id="amy-stat-pan">--</div>
                    </div>
                    <div class="amy-stat">
                        <div class="amy-stat-label">TILT</div>
                        <div class="amy-stat-value" id="amy-stat-tilt">--</div>
                    </div>
                </div>

                <!-- Sensor Nodes -->
                <div class="amy-nodes-section">
                    <div class="amy-section-label">SENSOR NODES</div>
                    <div id="amy-nodes-list" class="amy-nodes-list">
                        <span class="text-muted">No nodes detected</span>
                    </div>
                </div>

                <!-- Quick Commands -->
                <div class="amy-commands-section">
                    <div class="amy-section-label">COMMANDS</div>
                    <div class="amy-command-grid">
                        <button class="btn btn-cyber amy-cmd" onclick="amySendCommand('scan()')">SCAN</button>
                        <button class="btn btn-cyber amy-cmd" onclick="amySendCommand('observe()')">OBSERVE</button>
                        <button class="btn btn-cyber amy-cmd" onclick="amySendCommand('attend()')">ATTEND</button>
                        <button class="btn btn-cyber amy-cmd" onclick="amySendCommand('idle()')">IDLE</button>
                        <button class="btn btn-cyber amy-cmd" onclick="amyToggleAutoChat()" id="amy-btn-autochat">AUTO-CHAT</button>
                        <button class="btn btn-cyber amy-cmd" onclick="amySendCommand('nod()')">NOD</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Bottom Row: Thoughts + Sensorium + Chat -->
        <div class="amy-bottom-row">
            <!-- Thoughts Stream -->
            <div class="amy-panel amy-thoughts-panel">
                <div class="amy-panel-header">
                    <span class="amy-panel-title">INNER THOUGHTS</span>
                    <span class="amy-thought-count" id="amy-thought-count">0</span>
                </div>
                <div class="amy-thoughts-stream" id="amy-thoughts-stream">
                    <div class="amy-thought-placeholder">Waiting for consciousness stream...</div>
                </div>
            </div>

            <!-- Sensorium + Chat -->
            <div class="amy-panel amy-sense-chat-panel">
                <!-- Sensorium -->
                <div class="amy-sensorium-section">
                    <div class="amy-panel-header">
                        <span class="amy-panel-title">SENSORIUM</span>
                        <span class="amy-people-count" id="amy-people-count">0 present</span>
                    </div>
                    <div class="amy-sensorium-text" id="amy-sensorium-text">
                        <span class="text-muted">No sensory data...</span>
                    </div>
                </div>

                <!-- Chat -->
                <div class="amy-chat-section">
                    <div class="amy-panel-header">
                        <span class="amy-panel-title">TALK TO AMY</span>
                    </div>
                    <div class="amy-chat-log" id="amy-chat-log"></div>
                    <div class="amy-chat-input-row">
                        <input type="text" id="amy-chat-input" class="input amy-chat-input"
                               placeholder="Say something to Amy..."
                               onkeydown="if(event.key==='Enter')amySendChat()">
                        <button class="btn btn-cyber" onclick="amySendChat()">SEND</button>
                    </div>
                </div>
            </div>
        </div>

        <!-- Battlespace Panel -->
        <div class="amy-panel" style="margin-top: 8px;">
            <div class="amy-panel-header">
                <span class="amy-panel-title">BATTLESPACE</span>
                <span class="text-muted" id="amy-bs-summary" style="font-size: 0.7rem;">0 targets tracked</span>
            </div>
            <div style="padding: 8px;">
                <div style="display: flex; gap: 8px; margin-bottom: 8px;">
                    <button class="btn btn-cyber" onclick="spawnSimTarget('hostile')"
                            style="flex:1; font-size: 0.7rem; color: #ff2a6d; border-color: #ff2a6d;">SPAWN HOSTILE</button>
                    <button class="btn btn-cyber" onclick="spawnSimTarget('friendly')"
                            style="flex:1; font-size: 0.7rem; color: #05ffa1; border-color: #05ffa1;">SPAWN FRIENDLY</button>
                </div>
                <div id="amy-bs-targets" style="max-height: 180px; overflow-y: auto; font-size: 0.75rem; font-family: 'JetBrains Mono', monospace;">
                    <span class="text-muted">No simulation targets</span>
                </div>
                <div style="margin-top: 8px; border-top: 1px solid rgba(0,240,255,0.15); padding-top: 8px;">
                    <div style="font-size: 0.7rem; color: var(--cyan); margin-bottom: 4px;">DISPATCH LOG</div>
                    <div id="amy-dispatch-log" style="max-height: 120px; overflow-y: auto; font-size: 0.7rem; font-family: 'JetBrains Mono', monospace;">
                        <span class="text-muted">No dispatch events yet</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    `;
}

// --- API calls ---

async function fetchAmyStatus() {
    try {
        const resp = await fetch('/api/amy/status');
        if (!resp.ok) {
            updateAmyOffline();
            return;
        }
        const data = await resp.json();
        updateAmyStatus(data);
    } catch {
        updateAmyOffline();
    }

    // Check for active scenario video first, fall back to node video
    const scenarioActive = await checkScenarioVideo();
    if (!scenarioActive) {
        startAmyVideo(amyState.nodes);
    }
}

async function checkScenarioVideo() {
    try {
        const resp = await fetch('/api/scenarios/active');
        if (!resp.ok) return false;
        const data = await resp.json();
        if (data.run_id) {
            const key = `scenario:${data.run_id}`;
            if (amyState.videoNode === key) return true;
            amyState.videoNode = key;
            const feed = document.getElementById('amy-video-feed');
            const noFeed = document.getElementById('amy-no-feed');
            const nodeLabel = document.getElementById('amy-video-node');
            if (feed) {
                feed.src = `/api/scenarios/run/${data.run_id}/video`;
                feed.style.display = 'block';
            }
            if (noFeed) noFeed.style.display = 'none';
            if (nodeLabel) nodeLabel.textContent = 'SCENARIO';
            return true;
        }
    } catch { /* ignore - scenarios API may not exist */ }
    // Scenario ended - clear so node video can take over
    if (amyState.videoNode && amyState.videoNode.startsWith('scenario:')) {
        amyState.videoNode = null;
    }
    return false;
}

function updateAmyStatus(data) {
    amyState.state = data.state || 'unknown';
    amyState.mood = data.mood || 'neutral';
    amyState.autoChat = data.auto_chat || false;
    amyState.nodes = data.nodes || {};

    const stateEl = document.getElementById('amy-stat-state');
    const moodEl = document.getElementById('amy-stat-mood');
    const thinkEl = document.getElementById('amy-stat-thinking');
    const nodesEl = document.getElementById('amy-stat-nodes');
    const badgeEl = document.getElementById('amy-state-badge');

    if (stateEl) stateEl.textContent = amyState.state.toUpperCase();
    if (moodEl) {
        moodEl.textContent = amyState.mood.toUpperCase();
        moodEl.className = 'amy-stat-value amy-mood-' + amyState.mood;
    }
    if (thinkEl) thinkEl.textContent = data.thinking_suppressed ? 'SUPPRESSED' : 'ACTIVE';
    if (nodesEl) nodesEl.textContent = Object.keys(amyState.nodes).length;

    if (badgeEl) {
        badgeEl.textContent = amyState.state.toUpperCase();
        badgeEl.className = 'amy-state-badge amy-state-' + amyState.state;
    }

    // Update pose (PAN/TILT)
    const panEl = document.getElementById('amy-stat-pan');
    const tiltEl = document.getElementById('amy-stat-tilt');
    if (data.pose && panEl && tiltEl) {
        if (data.pose.calibrated) {
            panEl.textContent = data.pose.pan_deg !== null ? `${data.pose.pan_deg}°` : '--';
            tiltEl.textContent = data.pose.tilt_deg !== null ? `${data.pose.tilt_deg}°` : '--';
        } else {
            panEl.textContent = data.pose.pan !== null ? `${Math.round(data.pose.pan * 100)}%` : 'CAL';
            tiltEl.textContent = data.pose.tilt !== null ? `${Math.round(data.pose.tilt * 100)}%` : 'CAL';
        }
        panEl.className = 'amy-stat-value' + (data.pose.pan !== null && (data.pose.pan < 0.05 || data.pose.pan > 0.95) ? ' amy-pose-limit' : '');
        tiltEl.className = 'amy-stat-value' + (data.pose.tilt !== null && (data.pose.tilt < 0.05 || data.pose.tilt > 0.95) ? ' amy-pose-limit' : '');
    } else if (panEl && tiltEl) {
        panEl.textContent = '--';
        tiltEl.textContent = '--';
    }

    // Update auto-chat button
    const acBtn = document.getElementById('amy-btn-autochat');
    if (acBtn) {
        acBtn.classList.toggle('active', amyState.autoChat);
    }

    // Update nodes list
    renderAmyNodes(amyState.nodes);

}

function updateAmyOffline() {
    const badgeEl = document.getElementById('amy-state-badge');
    if (badgeEl) {
        badgeEl.textContent = 'OFFLINE';
        badgeEl.className = 'amy-state-badge amy-state-offline';
    }
}

function renderAmyNodes(nodes) {
    const container = document.getElementById('amy-nodes-list');
    if (!container) return;

    if (!nodes || Object.keys(nodes).length === 0) {
        container.innerHTML = '<span class="text-muted">No nodes detected</span>';
        return;
    }

    container.innerHTML = Object.entries(nodes).map(([id, n]) => {
        const caps = [];
        if (n.camera) caps.push('CAM');
        if (n.ptz) caps.push('PTZ');
        if (n.mic) caps.push('MIC');
        if (n.speaker) caps.push('SPK');
        return `<div class="amy-node-item">
            <span class="amy-node-id">${id}</span>
            <span class="amy-node-name">${n.name}</span>
            <span class="amy-node-caps">${caps.join(' ')}</span>
        </div>`;
    }).join('');
}

function startAmyVideo(nodes) {
    if (!nodes) return;

    // Find first camera node
    const camNode = Object.entries(nodes).find(([, n]) => n.camera);
    if (!camNode) return;

    const [nodeId] = camNode;
    if (amyState.videoNode === nodeId) return; // Already streaming
    amyState.videoNode = nodeId;

    const feed = document.getElementById('amy-video-feed');
    const noFeed = document.getElementById('amy-no-feed');
    const nodeLabel = document.getElementById('amy-video-node');

    if (feed) {
        feed.src = `/api/amy/nodes/${nodeId}/video`;
        feed.style.display = 'block';
    }
    if (noFeed) noFeed.style.display = 'none';
    if (nodeLabel) nodeLabel.textContent = nodeId.toUpperCase();
}

// --- SSE Thoughts Stream ---

function connectAmyThoughts() {
    if (amyState.eventSource) {
        amyState.eventSource.close();
    }

    const es = new EventSource('/api/amy/thoughts');
    amyState.eventSource = es;

    es.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleAmyThought(msg);
        } catch { /* ignore parse errors */ }
    };

    es.onerror = () => {
        amyState.connected = false;
        // Reconnect after delay
        setTimeout(() => {
            if (document.getElementById('amy-initialized')) {
                connectAmyThoughts();
            }
        }, 5000);
    };

    es.onopen = () => {
        amyState.connected = true;
    };
}

function handleAmyThought(msg) {
    const type = msg.type || 'unknown';
    const data = msg.data || {};
    const ts = msg.timestamp || new Date().toISOString();

    // Add to thoughts array
    amyState.thoughts.push({ type, data, ts });
    if (amyState.thoughts.length > amyState.maxThoughts) {
        amyState.thoughts.shift();
    }

    // Render in thoughts stream
    const stream = document.getElementById('amy-thoughts-stream');
    if (!stream) return;

    // Remove placeholder
    const ph = stream.querySelector('.amy-thought-placeholder');
    if (ph) ph.remove();

    const el = document.createElement('div');
    el.className = `amy-thought amy-thought-${type}`;

    const time = new Date(ts).toLocaleTimeString('en-US', { hour12: false });
    const label = type.replace(/_/g, ' ').toUpperCase();

    let content = '';
    if (type === 'thought') {
        content = data.text || data.content || JSON.stringify(data);
    } else if (type === 'speech') {
        content = data.text || '';
    } else if (type === 'transcript') {
        content = `[${data.speaker || '?'}] ${data.text || ''}`;
    } else if (type === 'observation') {
        content = data.summary || data.text || JSON.stringify(data);
    } else if (type === 'action') {
        content = data.action || data.lua || JSON.stringify(data);
    } else if (type === 'deep_look') {
        content = (data.description || '').substring(0, 120);
    } else {
        content = data.text || data.message || JSON.stringify(data).substring(0, 100);
    }

    el.innerHTML = `<span class="amy-thought-time">${time}</span>`
        + `<span class="amy-thought-label">${label}</span>`
        + `<span class="amy-thought-text">${escapeHtml(content)}</span>`;

    stream.appendChild(el);
    stream.scrollTop = stream.scrollHeight;

    // Update count
    const countEl = document.getElementById('amy-thought-count');
    if (countEl) countEl.textContent = amyState.thoughts.length;

    // If it's speech from Amy, add to chat log
    if (type === 'speech' && data.text) {
        appendChatMessage('amy', data.text);
    }
    // If it's a transcript, add to chat log
    if (type === 'transcript' && data.text) {
        appendChatMessage(data.speaker || 'user', data.text);
    }

    // Dispatch/alert events -> dispatch log
    if (type === 'dispatch' || type === 'amy_dispatch') {
        addDispatchLogEntry('dispatch', data);
    }
    if (type === 'alert' || type === 'amy_alert') {
        addDispatchLogEntry('alert', data);
    }

    // Update sensorium on observations
    if (type === 'observation' || type === 'deep_look') {
        fetchSensorium();
    }
}

// --- WebSocket Amy events (forwarded from app.js) ---

function handleAmyEvent(type, data, timestamp) {
    // Strip the amy_ prefix
    const eventType = type.replace(/^amy_/, '');
    handleAmyThought({ type: eventType, data: data || {}, timestamp });
}

// --- Sensorium ---

async function fetchSensorium() {
    try {
        const resp = await fetch('/api/amy/sensorium');
        if (!resp.ok) return;
        const data = await resp.json();
        updateSensorium(data);
    } catch { /* ignore */ }
}

function updateSensorium(data) {
    const textEl = document.getElementById('amy-sensorium-text');
    const peopleEl = document.getElementById('amy-people-count');

    if (textEl) {
        const narrative = data.narrative || data.summary || 'No sensory data...';
        textEl.textContent = narrative;
    }
    if (peopleEl) {
        const count = data.people_present || 0;
        peopleEl.textContent = `${count} present`;
    }
}

// --- Chat ---

function appendChatMessage(speaker, text) {
    const log = document.getElementById('amy-chat-log');
    if (!log) return;

    const el = document.createElement('div');
    el.className = `amy-chat-msg amy-chat-${speaker === 'amy' ? 'amy' : 'user'}`;
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });
    el.innerHTML = `<span class="amy-chat-speaker">${speaker === 'amy' ? 'AMY' : 'YOU'}</span>`
        + `<span class="amy-chat-time">${time}</span>`
        + `<span class="amy-chat-text">${escapeHtml(text)}</span>`;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
}

async function amySendChat() {
    const input = document.getElementById('amy-chat-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    input.value = '';

    // Don't appendChatMessage locally — the SSE transcript event
    // from the backend will add it (single source of truth).

    try {
        await fetch('/api/amy/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text }),
        });
    } catch (e) {
        appendChatMessage('system', 'Failed to send: ' + e.message);
    }
}

// --- Commands ---

async function amySendCommand(action) {
    try {
        await fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action }),
        });
    } catch (e) {
        console.error('[AMY] Command failed:', e);
    }
}

async function amyToggleAutoChat() {
    try {
        const resp = await fetch('/api/amy/auto-chat', { method: 'POST' });
        if (resp.ok) {
            const data = await resp.json();
            amyState.autoChat = data.auto_chat;
            const btn = document.getElementById('amy-btn-autochat');
            if (btn) btn.classList.toggle('active', amyState.autoChat);
        }
    } catch { /* ignore */ }
}

// --- Optics Tabs ---

function amySwitchOpticsTab(tab) {
    const tabs = document.querySelectorAll('.amy-optics-tab');
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === tab));

    const liveEl = document.getElementById('amy-optics-live');
    const galleryEl = document.getElementById('amy-optics-gallery');
    const container = document.getElementById('amy-video-container');

    if (tab === 'live') {
        if (liveEl) liveEl.style.display = '';
        if (galleryEl) galleryEl.style.display = 'none';
    } else {
        if (liveEl) liveEl.style.display = 'none';
        if (galleryEl) galleryEl.style.display = '';
        fetchAmyPhotos();
    }
    if (container) container.dataset.activeTab = tab;
}

async function fetchAmyPhotos() {
    const grid = document.getElementById('amy-gallery-grid');
    if (!grid) return;
    try {
        const resp = await fetch('/api/amy/photos');
        if (!resp.ok) return;
        const data = await resp.json();
        const photos = data.photos || [];
        if (photos.length === 0) {
            grid.innerHTML = '<div class="amy-gallery-empty">No photos saved yet</div>';
            return;
        }
        grid.innerHTML = photos.map(p => `
            <div class="amy-gallery-item" onclick="amyOpenLightbox('${p.filename}', '${escapeHtml(p.reason)}')">
                <img src="/api/amy/photos/${p.filename}" alt="${escapeHtml(p.reason)}" loading="lazy">
                <div class="amy-gallery-meta">
                    <span class="amy-gallery-time">${p.time || ''}</span>
                    <span class="amy-gallery-reason">${escapeHtml(p.reason)}</span>
                </div>
            </div>
        `).join('');
    } catch { /* ignore */ }
}

function amyOpenLightbox(filename, reason) {
    const lb = document.getElementById('amy-lightbox');
    const img = document.getElementById('amy-lightbox-img');
    const cap = document.getElementById('amy-lightbox-caption');
    if (!lb || !img) return;
    img.src = `/api/amy/photos/${filename}`;
    if (cap) cap.textContent = reason || filename;
    lb.style.display = 'flex';
}

function amyCloseLightbox() {
    const lb = document.getElementById('amy-lightbox');
    if (lb) lb.style.display = 'none';
}

// --- Battlespace ---

/**
 * Refresh the battlespace target list from current simTargets data
 */
function updateBattlespacePanel() {
    const targets = (typeof assetState !== 'undefined') ? assetState.simTargets : {};
    const entries = Object.entries(targets);
    const total = entries.length;
    const friendly = entries.filter(([, t]) => (t.alliance || '').toLowerCase() === 'friendly').length;
    const hostile = entries.filter(([, t]) => (t.alliance || '').toLowerCase() === 'hostile').length;

    const summaryEl = document.getElementById('amy-bs-summary');
    if (summaryEl) {
        summaryEl.textContent = `${total} targets tracked (${friendly} friendly, ${hostile} hostile)`;
    }

    const listEl = document.getElementById('amy-bs-targets');
    if (!listEl) return;

    if (total === 0) {
        listEl.innerHTML = '<span class="text-muted">No simulation targets</span>';
        return;
    }

    listEl.innerHTML = entries.map(([tid, t]) => {
        const alliance = (t.alliance || 'unknown').toLowerCase();
        const color = alliance === 'friendly' ? '#05ffa1'
            : alliance === 'hostile' ? '#ff2a6d' : '#fcee0a';
        const posStr = (t.x !== undefined && t.y !== undefined)
            ? `(${t.x.toFixed(1)}, ${t.y.toFixed(1)})` : '--';
        const batteryStr = (t.battery !== undefined) ? `${Math.round(t.battery * 100)}%` : '';

        return `<div style="display: flex; align-items: center; gap: 8px; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.05);">
            <span style="color: ${color}; font-weight: bold; min-width: 10px;">&#x25CF;</span>
            <span style="flex: 1; color: ${color};">${escapeHtml(t.name || tid)}</span>
            <span class="text-muted">${posStr}</span>
            ${batteryStr ? `<span style="color: #05ffa1;">${batteryStr}</span>` : ''}
            <button onclick="removeSimTarget('${tid}')" class="btn btn-cyber"
                    style="padding: 1px 6px; font-size: 0.65rem; color: #ff2a6d; border-color: rgba(255,42,109,0.3);">X</button>
        </div>`;
    }).join('');
}

/**
 * Spawn a simulation target
 */
async function spawnSimTarget(alliance) {
    try {
        const resp = await fetch('/api/amy/simulation/spawn', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ alliance }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        const data = await resp.json();
        showNotification('SPAWN', `${alliance.toUpperCase()} target spawned: ${data.name || data.target_id}`, 'success');
    } catch (e) {
        showNotification('ERROR', 'Spawn failed: ' + e.message, 'error');
    }
}

/**
 * Remove a simulation target
 */
async function removeSimTarget(targetId) {
    try {
        const resp = await fetch(`/api/amy/simulation/targets/${targetId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        // Remove locally for immediate feedback
        if (typeof assetState !== 'undefined') {
            delete assetState.simTargets[targetId];
        }
        updateBattlespacePanel();
        showNotification('REMOVED', `Target ${targetId} destroyed`, 'info');
    } catch (e) {
        showNotification('ERROR', 'Remove failed: ' + e.message, 'error');
    }
}

function addDispatchLogEntry(type, data) {
    const log = document.getElementById('amy-dispatch-log');
    if (!log) return;

    // Clear placeholder
    const placeholder = log.querySelector('.text-muted');
    if (placeholder && placeholder.textContent.includes('No dispatch')) placeholder.remove();

    const el = document.createElement('div');
    el.style.cssText = 'padding: 2px 0; border-bottom: 1px solid rgba(255,255,255,0.03);';
    const time = new Date().toLocaleTimeString('en-US', { hour12: false });

    if (type === 'dispatch') {
        const name = data.name || data.target_id || '?';
        const dest = data.destination ? `(${data.destination.x.toFixed(1)}, ${data.destination.y.toFixed(1)})` : '?';
        el.innerHTML = `<span style="color: var(--text-muted);">${time}</span> <span style="color: #05ffa1;">DISPATCH</span> ${escapeHtml(name)} → ${dest}`;
    } else if (type === 'alert') {
        const tid = data.target_id || '?';
        const msg = data.message || '';
        el.innerHTML = `<span style="color: var(--text-muted);">${time}</span> <span style="color: #fcee0a;">ALERT</span> ${escapeHtml(tid)}: ${escapeHtml(msg)}`;
    }

    log.appendChild(el);
    // Keep last 20
    while (log.children.length > 20) {
        log.removeChild(log.firstChild);
    }
    log.scrollTop = log.scrollHeight;
}

window.addDispatchLogEntry = addDispatchLogEntry;
window.updateBattlespacePanel = updateBattlespacePanel;
window.spawnSimTarget = spawnSimTarget;
window.removeSimTarget = removeSimTarget;

// --- Utilities ---

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
