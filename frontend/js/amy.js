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
                    <span class="amy-video-node" id="amy-video-node">--</span>
                </div>
                <div class="amy-video-container" id="amy-video-container">
                    <div class="amy-no-feed" id="amy-no-feed">
                        <div class="amy-no-feed-icon">&#x25C9;</div>
                        <div>NO CAMERA CONNECTED</div>
                        <div class="amy-no-feed-sub">Waiting for sensor node...</div>
                    </div>
                    <img id="amy-video-feed" class="amy-video-feed" style="display:none;"
                         alt="Amy camera feed">
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

    // Update auto-chat button
    const acBtn = document.getElementById('amy-btn-autochat');
    if (acBtn) {
        acBtn.classList.toggle('active', amyState.autoChat);
    }

    // Update nodes list
    renderAmyNodes(amyState.nodes);

    // Start video if camera available
    startAmyVideo(amyState.nodes);
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
    appendChatMessage('user', text);

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

// --- Utilities ---

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
