/**
 * TRITIUM-SC Target Gallery
 * Browse and manage detected people and vehicles
 */

// State
let targetState = {
    type: 'people',  // 'people' or 'vehicles'
    targets: [],
    page: 1,
    pageSize: 50,
    hasMore: false,
    selectedTarget: null,
    selectedSightings: null,
    filters: {
        channel: '',
        date: '',
    }
};

/**
 * Initialize targets view
 */
async function initTargetsView() {
    // Populate channel filter
    await populateChannelFilter();

    // Load targets
    await loadTargets();
}

/**
 * Populate channel filter dropdown
 */
async function populateChannelFilter() {
    const select = document.getElementById('target-channel-filter');
    if (!select) return;

    try {
        const response = await fetch('/api/cameras');
        if (response.ok) {
            const cameras = await response.json();
            select.innerHTML = '<option value="">All Channels</option>';
            cameras.forEach(cam => {
                select.innerHTML += `<option value="${cam.channel}">CH${cam.channel} - ${cam.name || 'Camera ' + cam.channel}</option>`;
            });
        }
    } catch (e) {
        console.error('Failed to load cameras for filter:', e);
    }
}

/**
 * Set target type (people or vehicles)
 */
function setTargetType(type) {
    targetState.type = type;
    targetState.page = 1;
    targetState.targets = [];

    // Update tab buttons
    document.getElementById('btn-target-people').classList.toggle('active', type === 'people');
    document.getElementById('btn-target-vehicles').classList.toggle('active', type === 'vehicles');

    loadTargets();
}

/**
 * Load targets from API
 */
async function loadTargets() {
    const gallery = document.getElementById('target-gallery');
    const emptyState = document.getElementById('targets-empty');
    const loadMoreBtn = document.getElementById('target-load-more');
    const countEl = document.getElementById('target-count');

    // Get filter values
    const channelFilter = document.getElementById('target-channel-filter')?.value || '';
    const dateFilter = document.getElementById('target-date-filter')?.value || '';

    targetState.filters.channel = channelFilter;
    targetState.filters.date = dateFilter;

    // Build URL
    const endpoint = targetState.type === 'people' ? '/api/search/people' : '/api/search/vehicles';
    const params = new URLSearchParams({
        page: targetState.page,
        page_size: targetState.pageSize,
    });

    if (channelFilter) params.append('channel', channelFilter);
    if (dateFilter) params.append('date', dateFilter);

    try {
        const response = await fetch(`${endpoint}?${params}`);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        // Handle both array response and paginated response
        const items = Array.isArray(data) ? data : (data.items || data.results || []);
        const total = data.total || items.length;

        if (targetState.page === 1) {
            targetState.targets = items;
        } else {
            targetState.targets = [...targetState.targets, ...items];
        }

        targetState.hasMore = targetState.targets.length < total;

        // Update count
        countEl.textContent = total;

        // Render gallery
        renderTargetGallery();

        // Show/hide load more
        loadMoreBtn.style.display = targetState.hasMore ? 'block' : 'none';

        // Show/hide empty state
        emptyState.style.display = targetState.targets.length === 0 ? 'flex' : 'none';

    } catch (e) {
        console.error('Failed to load targets:', e);
        showNotification('ERROR', 'Failed to load targets: ' + e.message, 'error');
        emptyState.style.display = 'flex';
    }
}

/**
 * Load more targets (pagination)
 */
function loadMoreTargets() {
    targetState.page++;
    loadTargets();
}

/**
 * Render target gallery
 */
function renderTargetGallery() {
    const gallery = document.getElementById('target-gallery');
    const emptyState = document.getElementById('targets-empty');

    if (targetState.targets.length === 0) {
        gallery.innerHTML = '';
        gallery.appendChild(emptyState);
        return;
    }

    let html = '';

    for (const target of targetState.targets) {
        const thumbnailUrl = target.thumbnail_url || `/api/search/thumbnail/${target.thumbnail_id}`;
        const timestamp = target.timestamp ? new Date(target.timestamp).toLocaleString() : 'Unknown';
        const channel = target.channel || '?';
        const confidence = target.confidence ? Math.round(target.confidence * 100) : '?';
        const label = target.label || '';
        const mergedCount = target.merged_count || 0;

        // Escape the thumbnail_id for safe attribute use
        const safeId = target.thumbnail_id.replace(/"/g, '&quot;').replace(/'/g, '&#39;');

        html += `
            <div class="target-card" data-target-id="${safeId}">
                <div class="target-card-image">
                    <img src="${thumbnailUrl}" alt="Target" loading="lazy"
                         onerror="this.onerror=null; this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%231a1a2e%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%2300f0ff%22 font-size=%2230%22>?</text></svg>';">
                    ${mergedCount > 1 ? `<span class="target-badge">${mergedCount}</span>` : ''}
                    ${label ? `<span class="target-label">${escapeHtml(label)}</span>` : ''}
                </div>
                <div class="target-card-info">
                    <div class="target-card-meta">
                        <span class="text-cyan">CH${channel}</span>
                        <span class="text-muted">${confidence}%</span>
                    </div>
                    <div class="target-card-time text-muted">${timestamp}</div>
                </div>
            </div>
        `;
    }

    gallery.innerHTML = html;

    // Add event listeners using delegation
    gallery.querySelectorAll('.target-card').forEach(card => {
        card.addEventListener('click', () => {
            const targetId = card.dataset.targetId;
            if (targetId) selectTarget(targetId);
        });
    });
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Select a target to view details
 */
async function selectTarget(thumbnailId) {
    const target = targetState.targets.find(t => t.thumbnail_id === thumbnailId);
    if (!target) return;

    targetState.selectedTarget = target;

    // Highlight selected card
    document.querySelectorAll('.target-card').forEach(card => {
        card.classList.toggle('selected', card.dataset.id === thumbnailId);
    });

    // Show detail panel
    const panel = document.getElementById('target-detail-panel');
    const img = document.getElementById('target-detail-img');
    const title = document.getElementById('target-detail-title');
    const info = document.getElementById('target-detail-info');

    const thumbnailUrl = target.thumbnail_url || `/api/search/thumbnail/${target.thumbnail_id}`;
    img.src = thumbnailUrl;

    title.textContent = target.label || (targetState.type === 'people' ? 'Person' : 'Vehicle');

    const timestamp = target.timestamp ? new Date(target.timestamp).toLocaleString() : 'Unknown';

    info.innerHTML = `
        <div><strong>ID:</strong> <span class="text-muted">${target.thumbnail_id}</span></div>
        <div><strong>Channel:</strong> CH${target.channel || '?'}</div>
        <div><strong>Timestamp:</strong> ${timestamp}</div>
        <div><strong>Confidence:</strong> ${target.confidence ? Math.round(target.confidence * 100) + '%' : 'Unknown'}</div>
        ${target.merged_count > 1 ? `<div><strong>Appearances:</strong> ${target.merged_count}</div>` : ''}
        ${target.video_path ? `<div><strong>Video:</strong> <a href="#" onclick="playTargetVideo('${target.video_path}', ${target.frame_number || 0})" class="text-cyan">${target.video_path.split('/').pop()}</a></div>` : ''}
        <div style="margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
            <button class="btn btn-cyber btn-sm" onclick="viewTargetHistory('${thumbnailId}')">
                <span>📊</span> HISTORY
            </button>
            <button class="btn btn-sm" style="background: var(--yellow); color: #000;" onclick="dispatchAssetToTarget('${thumbnailId}', 'track')">
                <span>🎯</span> TRACK
            </button>
            <button class="btn btn-sm" style="background: var(--magenta);" onclick="dispatchAssetToTarget('${thumbnailId}', 'engage')">
                <span>⚡</span> ENGAGE
            </button>
        </div>
    `;

    panel.style.display = 'block';

    // Load sightings in background
    loadTargetSightings(thumbnailId);
}

/**
 * Load target sightings/history
 */
async function loadTargetSightings(thumbnailId) {
    try {
        const response = await fetch(`/api/search/sightings/${thumbnailId}`);
        if (!response.ok) return;

        const data = await response.json();
        targetState.selectedSightings = data;

        // Update panel with sighting info
        const info = document.getElementById('target-detail-info');
        if (data.total_sightings > 1) {
            const firstSeen = data.first_seen ? new Date(data.first_seen).toLocaleDateString() : '?';
            const lastSeen = data.last_seen ? new Date(data.last_seen).toLocaleDateString() : '?';

            info.innerHTML += `
                <div class="target-sightings-summary" style="margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(0,240,255,0.2);">
                    <div class="text-cyan" style="font-weight: bold; margin-bottom: 8px;">SIGHTING HISTORY</div>
                    <div><strong>Total sightings:</strong> <span class="text-yellow">${data.total_sightings}</span></div>
                    <div><strong>First seen:</strong> ${firstSeen}</div>
                    <div><strong>Last seen:</strong> ${lastSeen}</div>
                    <div><strong>Cameras:</strong> ${Object.keys(data.by_channel).map(c => `CH${c}`).join(', ')}</div>
                </div>
            `;
        }
    } catch (e) {
        console.error('Failed to load sightings:', e);
    }
}

/**
 * Close target detail panel
 */
function closeTargetDetail() {
    document.getElementById('target-detail-panel').style.display = 'none';
    targetState.selectedTarget = null;

    document.querySelectorAll('.target-card').forEach(card => {
        card.classList.remove('selected');
    });
}

/**
 * Label a target
 */
async function labelTarget() {
    if (!targetState.selectedTarget) return;

    const label = prompt('Enter label for this target:', targetState.selectedTarget.label || '');
    if (label === null) return;  // Cancelled

    try {
        const response = await fetch('/api/search/label', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                thumbnail_id: targetState.selectedTarget.thumbnail_id,
                label: label,
            }),
        });

        if (response.ok) {
            targetState.selectedTarget.label = label;
            showNotification('LABELED', `Target labeled as "${label}"`, 'success');
            renderTargetGallery();
            selectTarget(targetState.selectedTarget.thumbnail_id);
        } else {
            throw new Error('Failed to label');
        }
    } catch (e) {
        showNotification('ERROR', 'Failed to label target', 'error');
    }
}

/**
 * Find similar targets
 */
async function findSimilar() {
    if (!targetState.selectedTarget) return;

    try {
        const response = await fetch(`/api/search/similar/${targetState.selectedTarget.thumbnail_id}?limit=20`);
        if (!response.ok) throw new Error('Failed to find similar');

        const similar = await response.json();

        if (similar.length === 0) {
            showNotification('INFO', 'No similar targets found', 'info');
            return;
        }

        // Replace gallery with similar results
        targetState.targets = similar;
        targetState.hasMore = false;
        renderTargetGallery();

        document.getElementById('target-count').textContent = similar.length;
        document.getElementById('target-load-more').style.display = 'none';

        showNotification('SIMILAR', `Found ${similar.length} similar targets`, 'success');

    } catch (e) {
        showNotification('ERROR', 'Failed to find similar targets', 'error');
    }
}

/**
 * Play video at target's frame
 */
function playTargetVideo(videoPath, frameNumber) {
    // Parse video path to get channel, date, filename
    // Expected format: channel_XX/YYYY-MM-DD/filename.mp4 or similar
    const parts = videoPath.split('/');
    if (parts.length >= 3) {
        const filename = parts[parts.length - 1];
        const date = parts[parts.length - 2];
        const channelDir = parts[parts.length - 3];
        const channelMatch = channelDir.match(/\d+/);

        if (channelMatch) {
            const channel = parseInt(channelMatch[0]);
            // Switch to player view and load video
            if (window.TRITIUM) {
                window.TRITIUM.selectChannel(channel);
                // Try to play video after a short delay
                setTimeout(() => {
                    window.TRITIUM.switchView('player');
                    const player = document.getElementById('main-player');
                    const videoUrl = `/api/videos/stream/${channel}/${date}/${filename}`;
                    player.src = videoUrl;
                    player.load();
                    player.play().catch(e => console.log('Autoplay blocked'));

                    // Seek to frame if possible
                    if (frameNumber && player.duration) {
                        // Estimate time from frame (assume 30fps)
                        player.currentTime = frameNumber / 30;
                    }
                }, 500);
            }
        }
    }

    closeTargetDetail();
}

/**
 * Dispatch an asset to track/engage target
 */
async function dispatchAssetToTarget(thumbnailId, taskType) {
    const target = targetState.selectedTarget;
    if (!target) return;

    // Fetch available assets
    try {
        const response = await fetch('/api/assets');
        if (!response.ok) {
            showNotification('ERROR', 'Failed to load assets', 'error');
            return;
        }

        const assets = await response.json();
        const availableAssets = assets.filter(a =>
            ['standby', 'active'].includes(a.status) &&
            a.capabilities?.includes(taskType)
        );

        if (availableAssets.length === 0) {
            showNotification('NO ASSETS', 'No available assets with ' + taskType + ' capability', 'warning');
            return;
        }

        // Show asset selection modal
        showAssetSelectionModal(availableAssets, taskType, target);

    } catch (e) {
        console.error('Failed to dispatch asset:', e);
        showNotification('ERROR', 'Failed to dispatch: ' + e.message, 'error');
    }
}

/**
 * Show modal for selecting which asset to dispatch
 */
function showAssetSelectionModal(assets, taskType, target) {
    // Remove existing modal
    const existingModal = document.getElementById('asset-dispatch-modal');
    if (existingModal) existingModal.remove();

    const thumbnailUrl = target.thumbnail_url || `/api/search/thumbnail/${target.thumbnail_id}`;
    const taskColors = {
        track: 'var(--yellow)',
        engage: 'var(--magenta)',
        investigate: 'var(--cyan)',
    };

    const modal = document.createElement('div');
    modal.id = 'asset-dispatch-modal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-content neon-box" style="max-width: 500px;">
            <div class="modal-header">
                <h3 style="color: ${taskColors[taskType] || 'var(--cyan)'}">${taskType.toUpperCase()} TARGET</h3>
                <button onclick="closeAssetDispatchModal()" class="btn btn-sm">&times;</button>
            </div>
            <div class="modal-body">
                <div style="display: flex; gap: 16px; margin-bottom: 16px;">
                    <img src="${thumbnailUrl}" style="width: 100px; height: 100px; object-fit: contain; border: 1px solid var(--cyan);">
                    <div>
                        <div class="text-cyan">${target.label || (targetState.type === 'people' ? 'PERSON' : 'VEHICLE')}</div>
                        <div class="text-muted" style="font-size: 0.75rem;">${target.thumbnail_id}</div>
                        <div style="margin-top: 8px;">CH${target.channel || '?'}</div>
                    </div>
                </div>
                <div style="color: var(--text-muted); margin-bottom: 8px;">SELECT ASSET TO DEPLOY:</div>
                <div class="asset-select-list">
                    ${assets.map(asset => `
                        <div class="asset-select-item" onclick="confirmAssetDispatch('${asset.asset_id}', '${taskType}', '${target.thumbnail_id}')">
                            <span class="asset-select-icon">${asset.asset_type === 'aerial' ? '🚁' : asset.asset_type === 'fixed' ? '📡' : '🚗'}</span>
                            <div class="asset-select-info">
                                <div class="asset-select-name">${asset.name}</div>
                                <div class="asset-select-meta">${asset.asset_id} • ${asset.asset_class}</div>
                            </div>
                            <div class="asset-select-status" style="color: ${asset.status === 'standby' ? 'var(--cyan)' : 'var(--green)'}">
                                ${asset.status.toUpperCase()}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `;

    document.body.appendChild(modal);
}

/**
 * Close asset dispatch modal
 */
function closeAssetDispatchModal() {
    const modal = document.getElementById('asset-dispatch-modal');
    if (modal) modal.remove();
}

/**
 * Confirm and execute asset dispatch
 */
async function confirmAssetDispatch(assetId, taskType, targetId) {
    closeAssetDispatchModal();

    try {
        // First, assign the task
        const taskResponse = await fetch(`/api/assets/${assetId}/task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                task_type: taskType,
                target_type: targetState.type === 'people' ? 'person' : 'vehicle',
                target_id: targetId,
                priority: taskType === 'engage' ? 1 : 3,
            }),
        });

        if (!taskResponse.ok) {
            const error = await taskResponse.json();
            throw new Error(error.detail || 'Failed to assign task');
        }

        const task = await taskResponse.json();

        // Start the task
        await fetch(`/api/assets/${assetId}/task/${task.task_id}/start`, { method: 'POST' });

        showNotification('DISPATCHED', `${assetId} tasked to ${taskType.toUpperCase()} target`, 'success');

        // Show asset view
        if (confirm('View asset status?')) {
            window.TRITIUM?.switchView('assets');
        }

    } catch (e) {
        showNotification('ERROR', e.message, 'error');
    }
}

/**
 * View detailed target history
 */
async function viewTargetHistory(thumbnailId) {
    try {
        const response = await fetch(`/api/search/sightings/${thumbnailId}`);
        if (!response.ok) throw new Error('Failed to load history');

        const data = await response.json();

        // Create history modal
        const existingModal = document.getElementById('target-history-modal');
        if (existingModal) existingModal.remove();

        const modal = document.createElement('div');
        modal.id = 'target-history-modal';
        modal.className = 'modal-overlay';

        // Build hourly chart
        const maxHour = Math.max(...data.by_hour);
        const hourBars = data.by_hour.map((count, hour) => {
            const height = maxHour > 0 ? (count / maxHour * 100) : 0;
            return `<div class="hour-bar" style="height: ${Math.max(height, 2)}%;" title="${hour}:00 - ${count}"></div>`;
        }).join('');

        // Build daily list
        const dailyList = Object.entries(data.by_day).slice(0, 14).map(([day, count]) => `
            <div class="history-day-item">
                <span>${day}</span>
                <span class="text-cyan">${count} sightings</span>
            </div>
        `).join('');

        modal.innerHTML = `
            <div class="modal-content neon-box" style="max-width: 600px; max-height: 80vh; overflow-y: auto;">
                <div class="modal-header">
                    <h3 class="text-cyan">TARGET HISTORY</h3>
                    <button onclick="document.getElementById('target-history-modal').remove()" class="btn btn-sm">&times;</button>
                </div>
                <div class="modal-body">
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 24px;">
                        <div class="stat-box">
                            <div class="stat-label">TOTAL SIGHTINGS</div>
                            <div class="stat-value text-yellow">${data.total_sightings}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">FIRST SEEN</div>
                            <div class="stat-value" style="font-size: 0.9rem;">${data.first_seen ? new Date(data.first_seen).toLocaleDateString() : '--'}</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-label">LAST SEEN</div>
                            <div class="stat-value" style="font-size: 0.9rem;">${data.last_seen ? new Date(data.last_seen).toLocaleDateString() : '--'}</div>
                        </div>
                    </div>

                    <div style="margin-bottom: 24px;">
                        <div class="text-muted" style="margin-bottom: 8px;">ACTIVITY BY HOUR</div>
                        <div class="hour-chart" style="display: flex; gap: 2px; height: 60px; align-items: flex-end; background: rgba(0,0,0,0.3); padding: 4px; border-radius: 4px;">
                            ${hourBars}
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.6rem; color: var(--text-muted); margin-top: 4px;">
                            <span>00:00</span>
                            <span>06:00</span>
                            <span>12:00</span>
                            <span>18:00</span>
                            <span>24:00</span>
                        </div>
                    </div>

                    <div style="margin-bottom: 24px;">
                        <div class="text-muted" style="margin-bottom: 8px;">CAMERAS</div>
                        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                            ${Object.entries(data.by_channel).map(([ch, count]) => `
                                <span class="channel-badge">CH${ch}: ${count}</span>
                            `).join('')}
                        </div>
                    </div>

                    <div>
                        <div class="text-muted" style="margin-bottom: 8px;">RECENT DAYS</div>
                        <div class="history-days-list">
                            ${dailyList || '<div class="text-muted">No history available</div>'}
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.appendChild(modal);

    } catch (e) {
        showNotification('ERROR', 'Failed to load history', 'error');
    }
}

// Note: View switching is handled by app.js which calls initTargetsView()

// Add CSS for target cards
const style = document.createElement('style');
style.textContent = `
.target-card {
    background: rgba(26, 26, 46, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;
    overflow: hidden;
}

.target-card:hover {
    border-color: var(--cyan);
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 240, 255, 0.2);
}

.target-card.selected {
    border-color: var(--magenta);
    box-shadow: 0 0 12px rgba(255, 42, 109, 0.4);
}

.target-card-image {
    position: relative;
    width: 100%;
    aspect-ratio: 1;
    background: #0a0a0f;
    display: flex;
    align-items: center;
    justify-content: center;
}

.target-card-image img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}

.target-badge {
    position: absolute;
    top: 4px;
    right: 4px;
    background: var(--magenta);
    color: white;
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 10px;
    font-weight: bold;
}

.target-label {
    position: absolute;
    bottom: 4px;
    left: 4px;
    right: 4px;
    background: rgba(0, 240, 255, 0.9);
    color: #0a0a0f;
    font-size: 0.7rem;
    padding: 2px 4px;
    border-radius: 2px;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.target-card-info {
    padding: 8px;
}

.target-card-meta {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    margin-bottom: 4px;
}

.target-card-time {
    font-size: 0.65rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

#target-detail-panel {
    border-top: 1px solid rgba(0, 240, 255, 0.3);
}

#target-detail-img {
    border: 1px solid rgba(0, 240, 255, 0.3);
}

/* Modal styles */
.modal-overlay {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.85);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.modal-content {
    background: var(--void);
    border: 1px solid var(--cyan);
    max-width: 90vw;
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: var(--space-md);
    border-bottom: 1px solid rgba(0, 240, 255, 0.2);
}

.modal-header h3 {
    margin: 0;
}

.modal-body {
    padding: var(--space-md);
}

/* Asset selection */
.asset-select-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.asset-select-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    background: rgba(26, 26, 46, 0.6);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
}

.asset-select-item:hover {
    border-color: var(--cyan);
    background: rgba(0, 240, 255, 0.1);
}

.asset-select-icon {
    font-size: 1.5rem;
}

.asset-select-info {
    flex: 1;
}

.asset-select-name {
    color: var(--cyan);
    font-weight: bold;
}

.asset-select-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
}

.asset-select-status {
    font-size: 0.7rem;
    font-weight: bold;
}

/* History modal */
.hour-bar {
    flex: 1;
    background: var(--cyan);
    min-height: 2px;
    border-radius: 2px 2px 0 0;
}

.channel-badge {
    background: rgba(0, 240, 255, 0.2);
    color: var(--cyan);
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 0.75rem;
}

.history-day-item {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid rgba(0, 240, 255, 0.1);
}

.stat-box {
    background: rgba(10, 10, 15, 0.8);
    border: 1px solid rgba(0, 240, 255, 0.2);
    padding: var(--space-sm);
    text-align: center;
    border-radius: 4px;
}

.stat-label {
    font-size: 0.65rem;
    color: var(--text-muted);
    margin-bottom: 4px;
}

.stat-value {
    font-size: 1.1rem;
    font-weight: bold;
    color: var(--cyan);
}

.btn-sm {
    padding: 4px 8px;
    font-size: 0.75rem;
}
`;
document.head.appendChild(style);

// Expose functions globally
window.setTargetType = setTargetType;
window.loadTargets = loadTargets;
window.loadMoreTargets = loadMoreTargets;
window.selectTarget = selectTarget;
window.closeTargetDetail = closeTargetDetail;
window.labelTarget = labelTarget;
window.findSimilar = findSimilar;
window.playTargetVideo = playTargetVideo;
window.initTargetsView = initTargetsView;
window.dispatchAssetToTarget = dispatchAssetToTarget;
window.closeAssetDispatchModal = closeAssetDispatchModal;
window.confirmAssetDispatch = confirmAssetDispatch;
window.viewTargetHistory = viewTargetHistory;
