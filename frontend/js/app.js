/**
 * TRITIUM - Main Application
 * Security Camera Intelligence Platform
 */

// Application State
const state = {
    channels: [],
    selectedChannel: null,
    selectedDate: null,
    videos: [],
    selectedVideo: null,
    currentView: 'grid',
    websocket: null,
    connected: false,
};

// DOM Elements
const elements = {
    channelList: document.getElementById('channel-list'),
    dateList: document.getElementById('date-list'),
    eventList: document.getElementById('event-list'),
    videoGrid: document.getElementById('video-grid'),
    videoList: document.getElementById('video-list'),
    systemTime: document.getElementById('system-time'),
    connectionDot: document.getElementById('connection-dot'),
    connectionText: document.getElementById('connection-text'),
    notifications: document.getElementById('notifications'),
    commandInput: document.getElementById('command-input'),
};

// Initialize application
document.addEventListener('DOMContentLoaded', () => {
    console.log('%c[TRITIUM] Initializing...', 'color: #00f0ff; font-weight: bold;');

    updateSystemTime();
    setInterval(updateSystemTime, 1000);

    initWebSocket();
    loadChannels();
    initKeyboardShortcuts();
    initCommandInput();

    showNotification('SYSTEM', 'TRITIUM v0.1.0 initialized', 'info');
});

// System Time
function updateSystemTime() {
    const now = new Date();
    const utc = now.toISOString().substr(11, 8);
    elements.systemTime.textContent = `${utc} UTC`;
}

// WebSocket Connection
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/live`;

    console.log(`%c[WS] Connecting to ${wsUrl}`, 'color: #fcee0a;');

    try {
        state.websocket = new WebSocket(wsUrl);

        state.websocket.onopen = () => {
            console.log('%c[WS] Connected', 'color: #05ffa1;');
            state.connected = true;
            updateConnectionStatus(true);
        };

        state.websocket.onclose = () => {
            console.log('%c[WS] Disconnected', 'color: #ff2a6d;');
            state.connected = false;
            updateConnectionStatus(false);
            // Reconnect after 5 seconds
            setTimeout(initWebSocket, 5000);
        };

        state.websocket.onerror = (error) => {
            console.error('[WS] Error:', error);
            updateConnectionStatus(false);
        };

        state.websocket.onmessage = (event) => {
            handleWebSocketMessage(JSON.parse(event.data));
        };
    } catch (error) {
        console.error('[WS] Failed to connect:', error);
        updateConnectionStatus(false);
    }
}

function updateConnectionStatus(connected) {
    elements.connectionDot.classList.toggle('disconnected', !connected);
    elements.connectionText.textContent = connected ? 'UPLINK ACTIVE' : 'DISCONNECTED';
}

function handleWebSocketMessage(message) {
    console.log('[WS] Message:', message);

    switch (message.type) {
        case 'connected':
            showNotification('UPLINK', message.message, 'success');
            break;
        case 'event':
            handleEvent(message.data);
            break;
        case 'alert':
            handleAlert(message.data);
            break;
        case 'camera_status':
            updateCameraStatus(message.camera_id, message.status);
            break;
        case 'asset_update':
            handleAssetUpdate(message.data);
            break;
        case 'task_update':
            handleTaskUpdate(message.data);
            break;
        case 'detection':
            handleNewDetection(message.data);
            break;
        case 'amy_sim_telemetry':
            if (typeof updateSimTarget === 'function') {
                updateSimTarget(message.data);
            }
            if (typeof updateBattlespacePanel === 'function') {
                updateBattlespacePanel();
            }
            if (typeof warHandleSimTelemetry === 'function') {
                warHandleSimTelemetry(message.data);
            }
            break;
        case 'amy_sim_telemetry_batch':
            if (message.data && Array.isArray(message.data)) {
                for (const targetData of message.data) {
                    if (typeof updateSimTarget === 'function') {
                        updateSimTarget(targetData);
                    }
                    if (typeof warHandleSimTelemetry === 'function') {
                        warHandleSimTelemetry(targetData);
                    }
                }
                if (typeof updateBattlespacePanel === 'function') {
                    updateBattlespacePanel();
                }
            }
            break;
        case 'amy_amy_dispatch':
            if (message.data && typeof addDispatchArrow === 'function') {
                addDispatchArrow(message.data.target_id, message.data.destination);
            }
            if (message.data && typeof warHandleDispatch === 'function') {
                warHandleDispatch(message.data);
            }
            showNotification('DISPATCH', `${message.data.name || message.data.target_id} dispatched`, 'info');
            break;
        case 'amy_amy_alert':
            if (message.data) {
                showNotification('ALERT', message.data.message || 'Simulation alert', 'error');
            }
            break;
        case 'amy_zone_violation':
            if (message.data && typeof warHandleZoneViolation === 'function') {
                warHandleZoneViolation(message.data);
            }
            showNotification('ZONE', message.data?.zone_name || 'Zone violation', 'error');
            break;
        case 'amy_threat_escalation':
            if (message.data && typeof warHandleThreatEscalation === 'function') {
                warHandleThreatEscalation(message.data);
            }
            showNotification('THREAT', `${message.data?.target_id?.slice(0,8) || '?'}: ${message.data?.old_level} -> ${message.data?.new_level}`, 'error');
            break;
        case 'amy_threat_deescalation':
            if (message.data && typeof warHandleThreatEscalation === 'function') {
                warHandleThreatEscalation(message.data);
            }
            break;
        case 'amy_target_neutralized':
            if (message.data && typeof warHandleTargetNeutralized === 'function') {
                warHandleTargetNeutralized(message.data);
            }
            showNotification('NEUTRALIZED', `${message.data?.hostile_name || 'Hostile'} intercepted by ${message.data?.interceptor_name || 'unit'}`, 'success');
            break;
        case 'amy_auto_dispatch_speech':
            if (message.data) {
                showNotification('DISPATCH', message.data.text || 'Auto dispatch', 'info');
                if (typeof warHandleAmySpeech === 'function') {
                    warHandleAmySpeech(message.data);
                }
            }
            break;
        case 'amy_thought':
            if (message.data && typeof warHandleAmyThought === 'function') {
                warHandleAmyThought(message.data);
            }
            break;
        case 'amy_state_change':
            if (message.data && typeof warHandleAmyThought === 'function') {
                // Update war room Amy panel state
                if (typeof warState !== 'undefined') {
                    warState.amyState = message.data.state || warState.amyState;
                }
            }
            break;
        case 'amy_mode_change':
            if (message.data && typeof warHandleModeChange === 'function') {
                warHandleModeChange(message.data);
            }
            break;
        default:
            // amy_* events are delivered via the dedicated SSE stream
            // in amy.js (connectAmyThoughts) — not forwarded here to
            // avoid duplicate entries in the sensorium panel.
            break;
    }
}

/**
 * Handle real-time asset updates
 */
function handleAssetUpdate(data) {
    console.log('[ASSET]', data);
    // Update assets view if open
    if (state.currentView === 'assets' && typeof loadAssets !== 'undefined') {
        loadAssets();
    }
    // Update 3D view markers
    if (state.currentView === '3d' && typeof loadAssetsIn3D !== 'undefined') {
        loadAssetsIn3D();
    }
}

/**
 * Handle task status updates
 */
function handleTaskUpdate(data) {
    console.log('[TASK]', data);
    const status = data.status || 'unknown';
    const taskType = data.task_type || 'TASK';
    const assetId = data.asset_id || 'UNIT';

    if (status === 'completed') {
        showNotification('TASK COMPLETE', `${assetId}: ${taskType} finished`, 'success');
        playSound('complete');
    } else if (status === 'failed') {
        showNotification('TASK FAILED', `${assetId}: ${taskType} failed`, 'error');
        playSound('alert');
    } else if (status === 'active') {
        showNotification('TASK STARTED', `${assetId}: ${taskType} initiated`, 'info');
    }

    // Refresh assets if view is open
    if (state.currentView === 'assets' && typeof loadAssets !== 'undefined') {
        loadAssets();
    }
}

/**
 * Handle new detection (person/vehicle)
 */
function handleNewDetection(data) {
    console.log('[DETECTION]', data);
    const type = data.target_type || 'object';
    const channel = data.channel || '?';
    const label = data.label || '';

    // Only notify for labeled/high-confidence detections
    if (data.confidence > 0.8 || label) {
        const displayLabel = label || type.toUpperCase();
        showNotification('DETECTION', `CH${channel}: ${displayLabel}`, 'info');
    }

    // Add to event list
    addEventToList({
        timestamp: data.timestamp || new Date().toISOString(),
        type: type,
    });

    // Update 3D view if open
    if (state.currentView === '3d' && typeof loadDetectionsIn3D !== 'undefined') {
        loadDetectionsIn3D();
    }
}

/**
 * Play notification sounds
 */
function playSound(type) {
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);

        if (type === 'alert') {
            oscillator.frequency.value = 880;
            oscillator.type = 'square';
            gainNode.gain.value = 0.1;
        } else if (type === 'complete') {
            oscillator.frequency.value = 660;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.08;
        } else {
            oscillator.frequency.value = 440;
            oscillator.type = 'sine';
            gainNode.gain.value = 0.05;
        }

        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.15);
    } catch (e) {
        // Audio not available
    }
}

// API Functions
async function apiGet(endpoint) {
    try {
        const response = await fetch(`/api${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`[API] GET ${endpoint} failed:`, error);
        throw error;
    }
}

async function apiPost(endpoint, data) {
    try {
        const response = await fetch(`/api${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`[API] POST ${endpoint} failed:`, error);
        throw error;
    }
}

// Channel Management
async function loadChannels() {
    try {
        // Fetch both recorded channels and registered cameras
        const [recordedChannels, registeredCameras, discoveryStatus] = await Promise.all([
            apiGet('/videos/channels').catch(() => []),
            apiGet('/cameras').catch(() => []),
            apiGet('/discovery/status').catch(() => ({ status: 'unknown' })),
        ]);

        // Merge data: recorded channels + registered cameras
        const channelMap = new Map();

        // Add recorded channels
        for (const ch of recordedChannels) {
            channelMap.set(ch.channel, {
                ...ch,
                hasRecordings: true,
                registered: false,
                online: false,
            });
        }

        // Merge registered cameras
        for (const cam of registeredCameras) {
            if (channelMap.has(cam.channel)) {
                const existing = channelMap.get(cam.channel);
                existing.registered = true;
                existing.online = cam.enabled;
                existing.name = cam.name;
                existing.rtsp_url = cam.rtsp_url;
            } else {
                channelMap.set(cam.channel, {
                    channel: cam.channel,
                    name: cam.name,
                    total_videos: 0,
                    hasRecordings: false,
                    registered: true,
                    online: cam.enabled,
                    rtsp_url: cam.rtsp_url,
                });
            }
        }

        state.channels = Array.from(channelMap.values()).sort((a, b) => a.channel - b.channel);
        state.nvrStatus = discoveryStatus;

        renderChannelList();

        if (state.channels.length === 0) {
            showEmptyState('No channels found. Click "Scan NVR" to discover cameras.');
        } else {
            // Auto-select first channel with recordings
            const firstWithRecordings = state.channels.find(c => c.hasRecordings);
            if (firstWithRecordings) {
                selectChannel(firstWithRecordings.channel);
            }
        }

        // Update NVR status display
        updateNvrStatus(discoveryStatus);

        // Reload 3D view if initialized
        if (typeof reloadThreeJS !== 'undefined') {
            reloadThreeJS();
        }

    } catch (error) {
        showNotification('ERROR', 'Failed to load channels', 'error');
        showEmptyState('Failed to connect to API');
    }
}

function updateNvrStatus(status) {
    const statusEl = document.getElementById('nvr-status');
    if (!statusEl) return;

    if (status.status === 'connected') {
        statusEl.innerHTML = `<span class="status status-online">NVR: ${status.online}/${status.total_channels}</span>`;
    } else if (status.status === 'not_configured') {
        statusEl.innerHTML = `<span class="status status-warning">NVR: Not configured</span>`;
    } else {
        statusEl.innerHTML = `<span class="status status-offline">NVR: Offline</span>`;
    }
}

async function scanNvr() {
    const scanBtn = document.querySelector('[onclick="scanNvr()"]');
    if (scanBtn) {
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<span class="spinner"></span> SCAN';
    }

    showNotification('SCANNING', 'Discovering cameras from NVR...', 'info');
    try {
        const result = await apiPost('/discovery/register', {});
        showNotification('DISCOVERY', `Added ${result.added}, updated ${result.updated} cameras`, 'success');
        await loadChannels();
    } catch (error) {
        showNotification('ERROR', 'NVR scan failed', 'error');
    } finally {
        if (scanBtn) {
            scanBtn.disabled = false;
            scanBtn.textContent = 'SCAN';
        }
    }
}

function renderChannelList() {
    elements.channelList.innerHTML = state.channels.map(ch => {
        const statusClass = ch.online ? 'online' : (ch.hasRecordings ? 'syncing' : 'offline');
        const label = ch.name || `CH${String(ch.channel).padStart(2, '0')}`;
        const meta = ch.hasRecordings ? `${ch.total_videos} files` : (ch.online ? 'LIVE' : 'offline');

        return `
            <li class="channel-item ${state.selectedChannel === ch.channel ? 'active' : ''}"
                onclick="selectChannel(${ch.channel})" data-channel="${ch.channel}">
                <span class="channel-name">
                    <span class="channel-status ${statusClass}"></span>
                    ${label}
                </span>
                <span class="channel-meta">${meta}</span>
            </li>
        `;
    }).join('');
}

async function selectChannel(channel) {
    state.selectedChannel = channel;
    state.selectedDate = null;
    state.videos = [];

    renderChannelList();

    try {
        const dates = await apiGet(`/videos/channels/${channel}/dates`);
        renderDateList(dates);

        if (dates.length > 0) {
            // Auto-select most recent date
            selectDate(dates[0].date);
        }
    } catch (error) {
        showNotification('ERROR', 'Failed to load dates', 'error');
    }

    // If in zones view, initialize zone editor for this channel
    if (state.currentView === 'zones' && typeof initZoneEditorForCamera !== 'undefined') {
        initZoneEditorForCamera(channel);
    }
}

function renderDateList(dates) {
    elements.dateList.innerHTML = dates.map(d => `
        <li class="date-item ${state.selectedDate === d.date ? 'active' : ''}"
            onclick="selectDate('${d.date}')">
            <span>${d.date}</span>
            <span class="date-count">${d.video_count}</span>
        </li>
    `).join('');
}

async function selectDate(date) {
    state.selectedDate = date;
    document.getElementById('timeline-date').textContent = date;

    // Update date list highlighting
    document.querySelectorAll('.date-item').forEach(el => {
        el.classList.toggle('active', el.textContent.includes(date));
    });

    try {
        state.videos = await apiGet(`/videos/channels/${state.selectedChannel}/dates/${date}`);
        renderVideoList();
        updateDayTimeline();

        // Switch to list view when date selected
        switchView('list');
    } catch (error) {
        showNotification('ERROR', 'Failed to load videos', 'error');
    }
}

function renderVideoList() {
    if (state.videos.length === 0) {
        elements.videoList.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📼</div>
                <div class="empty-state-title">NO RECORDINGS</div>
                <div class="empty-state-message">No video files found for this date.</div>
            </div>
        `;
        return;
    }

    elements.videoList.innerHTML = state.videos.map((video, index) => {
        const thumbnailUrl = `/api/videos/thumbnail/${state.selectedChannel}/${state.selectedDate}/${video.filename}`;
        return `
            <div class="video-list-item ${state.selectedVideo === index ? 'active' : ''}"
                 onclick="playVideo(${index})">
                <div class="video-thumbnail">
                    <img src="${thumbnailUrl}" alt="${video.filename}" loading="lazy"
                         onerror="this.onerror=null; this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 160 90%22><rect fill=%22%231a1a2e%22 width=%22160%22 height=%2290%22/><text x=%2280%22 y=%2245%22 text-anchor=%22middle%22 fill=%22%2300f0ff%22 font-size=%2212%22>📹</text></svg>';">
                    <span class="video-time-overlay">${video.timestamp ? formatTime(video.timestamp) : '--:--'}</span>
                </div>
                <div class="video-info">
                    <div class="video-filename">${video.filename}</div>
                    <div class="video-meta">
                        <span>${formatFileSize(video.size)}</span>
                        <span>${video.timestamp ? new Date(video.timestamp).toLocaleTimeString() : ''}</span>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function updateDayTimeline() {
    const timeline = document.getElementById('day-timeline');
    timeline.innerHTML = '';

    state.videos.forEach(video => {
        if (video.timestamp) {
            const date = new Date(video.timestamp);
            const hour = date.getHours();
            const minute = date.getMinutes();
            const position = ((hour * 60 + minute) / (24 * 60)) * 100;

            const segment = document.createElement('div');
            segment.className = 'timeline-segment';
            segment.style.left = `${position}%`;
            segment.style.width = '2px';
            segment.title = video.filename;
            segment.onclick = () => {
                const index = state.videos.indexOf(video);
                if (index !== -1) playVideo(index);
            };

            timeline.appendChild(segment);
        }
    });
}

// Video Playback
function playVideo(index) {
    state.selectedVideo = index;
    const video = state.videos[index];

    if (!video) return;

    const videoUrl = `/api/videos/stream/${state.selectedChannel}/${state.selectedDate}/${video.filename}`;
    const player = document.getElementById('main-player');

    player.src = videoUrl;
    player.load();
    player.play().catch(e => console.log('Autoplay blocked:', e));

    // Update list highlighting
    document.querySelectorAll('.video-list-item').forEach((el, i) => {
        el.classList.toggle('active', i === index);
    });

    switchView('player');
    showNotification('PLAYING', video.filename, 'info');

    // Load detection data for annotation overlay
    // CRITICAL: Enables reviewing footage with bounding boxes visible
    if (typeof loadVideoDetections === 'function') {
        loadVideoDetections(state.selectedChannel, state.selectedDate, video.filename);
    }
}

// View Management
function switchView(view) {
    state.currentView = view;

    // Update buttons
    document.querySelectorAll('.view-controls .btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `btn-${view}`);
    });

    // Show/hide views
    document.querySelectorAll('.view-content').forEach(el => {
        el.classList.add('hidden');
    });

    const viewEl = document.getElementById(`view-${view}`);
    if (viewEl) {
        viewEl.classList.remove('hidden');
    }

    // Initialize 3D view if needed
    if (view === '3d' && typeof initThreeJS !== 'undefined') {
        initThreeJS();
    }

    // Initialize zones view if needed
    if (view === 'zones' && typeof initZonesView !== 'undefined') {
        initZonesView();
        // If a channel is selected, initialize zone editor for it
        if (state.selectedChannel && typeof initZoneEditorForCamera !== 'undefined') {
            initZoneEditorForCamera(state.selectedChannel);
        }
    }

    // Initialize targets view if needed
    if (view === 'targets' && typeof initTargetsView !== 'undefined') {
        initTargetsView();
    }

    // Initialize assets view if needed
    if (view === 'assets' && typeof initAssetsView !== 'undefined') {
        initAssetsView();
    }

    // Initialize analytics view if needed
    if (view === 'analytics' && typeof initAnalyticsView !== 'undefined') {
        initAnalyticsView();
    }

    // Initialize Amy view if needed
    if (view === 'amy' && typeof initAmyView !== 'undefined') {
        initAmyView();
    }

    // Initialize Scenarios view if needed
    if (view === 'scenarios' && typeof initScenariosView !== 'undefined') {
        initScenariosView();
    }

    // Initialize War Room view if needed
    if (view === 'war' && typeof initWarView !== 'undefined') {
        initWarView();
    }

    // Destroy War Room view when leaving
    if (view !== 'war' && typeof destroyWarView !== 'undefined') {
        destroyWarView();
    }

    // Notify input manager of view change
    if (typeof tritiumInput !== 'undefined' && tritiumInput.setView) {
        tritiumInput.setView(view);
    }
}

function showEmptyState(message) {
    const emptyEl = document.getElementById('view-empty');
    emptyEl.querySelector('.empty-state-message').textContent = message;
    switchView('empty');
}

// Notifications
function showNotification(title, message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification ${type === 'error' ? 'alert' : ''}`;
    notification.innerHTML = `
        <div class="notification-title text-${type === 'error' ? 'magenta' : type === 'success' ? 'green' : 'cyan'}">${title}</div>
        <div class="notification-message">${message}</div>
    `;

    elements.notifications.appendChild(notification);

    // Remove after 5 seconds
    setTimeout(() => {
        notification.style.opacity = '0';
        notification.style.transform = 'translateX(100%)';
        setTimeout(() => notification.remove(), 300);
    }, 5000);
}

// Section Toggle
function toggleSection(section) {
    const toggle = document.getElementById(`${section}-toggle`);
    if (toggle) {
        toggle.classList.toggle('collapsed');
    }

    // Map section names to list IDs
    const listIdMap = {
        'channels': 'channel-list',
        'dates': 'date-list',
        'events': 'event-list',
        'sidebar-zones': 'sidebar-zone-list',
    };

    const listId = listIdMap[section];
    if (listId) {
        const list = document.getElementById(listId);
        if (list) {
            list.classList.toggle('hidden');
        }
    }
}

// Command Input
function initCommandInput() {
    elements.commandInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const command = e.target.value.trim();
            if (command) {
                executeCommand(command);
                e.target.value = '';
            }
        }
    });
}

function executeCommand(command) {
    console.log('[CMD]', command);

    // Parse command
    if (command.startsWith('search:')) {
        const query = command.substring(7).trim();
        showNotification('SEARCH', `Searching for: "${query}"`, 'info');
        // Search functionality will be added in Phase 8
    } else {
        showNotification('UNKNOWN', `Command not recognized: ${command}`, 'error');
    }
}

// Keyboard Shortcuts
function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Don't trigger if typing in input
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        // War Room captures s/t/o keys for mode switching
        if (state.currentView === 'war' && ['s', 't', 'o'].includes(e.key)) return;

        switch (e.key) {
            case '1':
                document.getElementById('grid-size').value = '1';
                updateGridSize(1);
                break;
            case '2':
                document.getElementById('grid-size').value = '4';
                updateGridSize(4);
                break;
            case '3':
                document.getElementById('grid-size').value = '9';
                updateGridSize(9);
                break;
            case 'g':
                switchView('grid');
                break;
            case 'p':
                switchView('player');
                break;
            case 'd':
                switchView('3d');
                break;
            case 'z':
                switchView('zones');
                break;
            case 't':
                switchView('targets');
                break;
            case 'a':
                switchView('assets');
                break;
            case 'n':
                switchView('analytics');
                break;
            case 'y':
                switchView('amy');
                break;
            case 'w':
                switchView('war');
                break;
            case 's':
                switchView('scenarios');
                break;
            case '/':
                e.preventDefault();
                elements.commandInput.focus();
                break;
            case 'Escape':
                elements.commandInput.blur();
                closeAllModals();
                break;
            case '?':
                e.preventDefault();
                showKeyboardHelp();
                break;
        }
    });
}

/**
 * Close all open modals
 */
function closeAllModals() {
    const modals = document.querySelectorAll('.modal-overlay');
    modals.forEach(m => m.remove());

    // Close target detail
    if (typeof closeTargetDetail === 'function') closeTargetDetail();

    // Close detection context menu
    if (typeof closeDetectionContextMenu === 'function') closeDetectionContextMenu();
}

/**
 * Show keyboard shortcuts help
 */
function showKeyboardHelp() {
    // Remove existing
    const existing = document.getElementById('keyboard-help-modal');
    if (existing) {
        existing.remove();
        return;
    }

    const modal = document.createElement('div');
    modal.id = 'keyboard-help-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-content neon-box" style="max-width: 400px;">
            <div class="modal-header">
                <h3 class="text-cyan">KEYBOARD SHORTCUTS</h3>
                <button onclick="document.getElementById('keyboard-help-modal').remove()" class="btn btn-sm">&times;</button>
            </div>
            <div class="modal-body" style="display: grid; gap: 8px;">
                <div class="shortcut-section">
                    <div class="text-muted" style="margin-bottom: 4px; font-size: 0.7rem;">VIEWS</div>
                    <div class="shortcut-row"><kbd>G</kbd> Grid View</div>
                    <div class="shortcut-row"><kbd>P</kbd> Player View</div>
                    <div class="shortcut-row"><kbd>D</kbd> 3D Property View</div>
                    <div class="shortcut-row"><kbd>Z</kbd> Zones View</div>
                    <div class="shortcut-row"><kbd>T</kbd> Targets Gallery</div>
                    <div class="shortcut-row"><kbd>A</kbd> Assets Control</div>
                    <div class="shortcut-row"><kbd>N</kbd> Analytics</div>
                    <div class="shortcut-row"><kbd>Y</kbd> Amy Commander</div>
                    <div class="shortcut-row"><kbd>W</kbd> War Room</div>
                    <div class="shortcut-row"><kbd>S</kbd> Scenarios</div>
                </div>
                <div class="shortcut-section" style="margin-top: 8px;">
                    <div class="text-muted" style="margin-bottom: 4px; font-size: 0.7rem;">GRID SIZE</div>
                    <div class="shortcut-row"><kbd>1</kbd> Single Camera</div>
                    <div class="shortcut-row"><kbd>2</kbd> 2x2 Grid</div>
                    <div class="shortcut-row"><kbd>3</kbd> 3x3 Grid</div>
                </div>
                <div class="shortcut-section" style="margin-top: 8px;">
                    <div class="text-muted" style="margin-bottom: 4px; font-size: 0.7rem;">WAR ROOM</div>
                    <div class="shortcut-row"><kbd>O/T/S</kbd> Observe / Tactical / Setup</div>
                    <div class="shortcut-row"><kbd>R-Click</kbd> Dispatch Selected</div>
                    <div class="shortcut-row"><kbd>Tab</kbd> Cycle Targets</div>
                    <div class="shortcut-row"><kbd>Space</kbd> Center on Selection</div>
                </div>
                <div class="shortcut-section" style="margin-top: 8px;">
                    <div class="text-muted" style="margin-bottom: 4px; font-size: 0.7rem;">OTHER</div>
                    <div class="shortcut-row"><kbd>/</kbd> Focus Search</div>
                    <div class="shortcut-row"><kbd>ESC</kbd> Close/Cancel</div>
                    <div class="shortcut-row"><kbd>?</kbd> This Help</div>
                </div>
            </div>
        </div>
    `;

    // Add styles
    const style = document.createElement('style');
    style.id = 'keyboard-help-style';
    style.textContent = `
        .shortcut-row {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 4px 0;
        }
        .shortcut-row kbd {
            background: rgba(0, 240, 255, 0.15);
            border: 1px solid rgba(0, 240, 255, 0.3);
            border-radius: 4px;
            padding: 2px 8px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.8rem;
            color: var(--cyan);
            min-width: 30px;
            text-align: center;
        }
    `;

    if (!document.getElementById('keyboard-help-style')) {
        document.head.appendChild(style);
    }

    document.body.appendChild(modal);

    // Close on click outside
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });
}

// Grid Size
document.getElementById('grid-size').addEventListener('change', (e) => {
    updateGridSize(parseInt(e.target.value));
});

function updateGridSize(size) {
    const grid = document.getElementById('video-grid');
    grid.className = `video-grid grid-${size}`;
}

// Event Handlers
function handleEvent(data) {
    console.log('[EVENT]', data);
    // Add to event list
    addEventToList(data);
}

function handleAlert(data) {
    console.log('[ALERT]', data);
    showNotification('ALERT', data.message || 'Detection alert', 'error');
    // Play alert sound (optional)
    playAlertSound();
}

function addEventToList(event) {
    const li = document.createElement('li');
    li.textContent = `${formatTime(event.timestamp)} ${event.type}`;
    elements.eventList.insertBefore(li, elements.eventList.firstChild);

    // Keep only last 10 events
    while (elements.eventList.children.length > 10) {
        elements.eventList.removeChild(elements.eventList.lastChild);
    }
}

function updateCameraStatus(cameraId, status) {
    console.log(`[CAMERA ${cameraId}] Status: ${status}`);
    // Update channel status in list
    const channelItem = document.querySelector(`.channel-item[data-channel="${cameraId}"]`);
    if (channelItem) {
        const statusDot = channelItem.querySelector('.channel-status');
        statusDot.className = `channel-status ${status}`;
    }
}

// Utility Functions
function formatTime(timestamp) {
    if (!timestamp) return '--:--';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour12: false });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function playAlertSound() {
    // Optional: Play a beep sound for alerts
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();

        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);

        oscillator.frequency.value = 440;
        oscillator.type = 'sine';
        gainNode.gain.value = 0.1;

        oscillator.start();
        oscillator.stop(audioContext.currentTime + 0.2);
    } catch (e) {
        // Audio not available
    }
}

// Export for other modules
window.TRITIUM = {
    state,
    selectChannel,
    selectDate,
    playVideo,
    switchView,
    showNotification,
};

// Also expose showNotification globally for easy access
window.showNotification = showNotification;

// Expose switchView globally for input system
window.switchView = switchView;

/**
 * Update gamepad indicator visibility
 */
function updateGamepadIndicator(connected) {
    const indicator = document.getElementById('gamepad-indicator');
    if (indicator) {
        indicator.classList.toggle('connected', connected);
        indicator.classList.toggle('disconnected', !connected);
        const text = indicator.querySelector('.text');
        if (text) {
            text.textContent = connected ? 'Gamepad Connected' : 'Gamepad Disconnected';
        }
    }
}

window.updateGamepadIndicator = updateGamepadIndicator;
