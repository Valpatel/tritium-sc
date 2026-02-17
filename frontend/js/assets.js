/**
 * TRITIUM-SC Asset Management
 * Autonomous unit control and tasking interface
 */

// State
let assetState = {
    assets: [],
    selectedAsset: null,
    mapCanvas: null,
    mapCtx: null,
    telemetryInterval: null,
    simTargets: {},
    dispatchArrows: [],
    simAnimating: false,
};

// Asset type icons
const ASSET_ICONS = {
    ground: '🚗',
    aerial: '🚁',
    fixed: '📡',
};

// Status colors
const STATUS_COLORS = {
    standby: 'var(--cyan)',
    active: 'var(--green)',
    tasked: 'var(--yellow)',
    returning: 'var(--cyan)',
    maintenance: 'var(--magenta)',
    offline: '#666',
    stopped: 'var(--magenta)',
};

/**
 * Initialize assets view
 */
async function initAssetsView() {
    await loadAssets();
    initTacticalMap();
    startTelemetryUpdates();
}

/**
 * Load all assets from API
 */
async function loadAssets() {
    try {
        const response = await fetch('/api/assets');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        assetState.assets = await response.json();
        renderAssetList();
        updateAssetSummary();

    } catch (e) {
        console.error('Failed to load assets:', e);
        showNotification('ERROR', 'Failed to load assets', 'error');
    }
}

/**
 * Render asset list
 */
function renderAssetList() {
    const list = document.getElementById('asset-list');
    if (!list) return;

    if (assetState.assets.length === 0) {
        list.innerHTML = `
            <div class="empty-state" style="padding: var(--space-md); text-align: center;">
                <div style="font-size: 2rem; margin-bottom: var(--space-sm);">🤖</div>
                <div class="text-muted">No assets registered</div>
                <div style="font-size: 0.75rem; margin-top: var(--space-sm);">
                    Click "+ REGISTER" to add an operational unit
                </div>
            </div>
        `;
        return;
    }

    list.innerHTML = assetState.assets.map(asset => {
        const icon = ASSET_ICONS[asset.asset_type] || '🔹';
        const statusColor = STATUS_COLORS[asset.status] || '#666';
        const isSelected = assetState.selectedAsset?.asset_id === asset.asset_id;
        const batteryIcon = getBatteryIcon(asset.battery_level);

        return `
            <div class="asset-card ${isSelected ? 'selected' : ''}"
                 onclick="selectAsset('${asset.asset_id}')"
                 data-asset-id="${asset.asset_id}">
                <div class="asset-card-header">
                    <span class="asset-icon">${icon}</span>
                    <span class="asset-name">${asset.name}</span>
                    <span class="asset-status" style="background: ${statusColor};">${asset.status.toUpperCase()}</span>
                </div>
                <div class="asset-card-body">
                    <div class="asset-id">${asset.asset_id}</div>
                    <div class="asset-class">${asset.asset_class.toUpperCase()}</div>
                </div>
                <div class="asset-card-footer">
                    <span>${batteryIcon} ${asset.battery_level ?? '--'}%</span>
                    ${asset.current_task ? `<span class="text-yellow">${asset.current_task.task_type}</span>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

/**
 * Get battery icon based on level
 */
function getBatteryIcon(level) {
    if (level === null || level === undefined) return '🔋';
    if (level > 75) return '🔋';
    if (level > 50) return '🔋';
    if (level > 25) return '🪫';
    return '🪫';
}

/**
 * Update asset summary counts
 */
function updateAssetSummary() {
    const total = assetState.assets.length;
    const active = assetState.assets.filter(a => ['active', 'tasked'].includes(a.status)).length;
    const offline = assetState.assets.filter(a => a.status === 'offline').length;

    document.getElementById('asset-total').textContent = total;
    document.getElementById('asset-active').textContent = active;
    document.getElementById('asset-offline').textContent = offline;
}

/**
 * Select an asset
 */
async function selectAsset(assetId) {
    const asset = assetState.assets.find(a => a.asset_id === assetId);
    if (!asset) return;

    assetState.selectedAsset = asset;
    renderAssetList();
    updateAssetDetail(asset);
    drawTacticalMap();
}

/**
 * Update asset detail panel
 */
function updateAssetDetail(asset) {
    // Header
    document.getElementById('asset-detail-name').textContent = asset.name;
    const statusEl = document.getElementById('asset-detail-status');
    statusEl.textContent = asset.status.toUpperCase();
    statusEl.style.background = STATUS_COLORS[asset.status] || '#666';

    // Show actions
    document.getElementById('asset-detail-actions').style.display = 'flex';

    // Stats
    document.getElementById('asset-battery').textContent = `${asset.battery_level ?? '--'}%`;
    document.getElementById('asset-ammo').textContent = `${asset.ammo_level ?? '--'}%`;
    document.getElementById('asset-position').textContent =
        asset.position_x !== null ? `${asset.position_x.toFixed(1)}, ${asset.position_y.toFixed(1)}` : '--';
    document.getElementById('asset-heading').textContent =
        asset.heading !== null ? `${Math.round(asset.heading)}°` : '--';

    // Current task
    const taskEl = document.getElementById('asset-current-task');
    if (asset.current_task) {
        taskEl.textContent = `${asset.current_task.task_type.toUpperCase()} - ${asset.current_task.status}`;
        taskEl.className = 'text-yellow';
    } else {
        taskEl.textContent = 'No active task';
        taskEl.className = 'text-muted';
    }

    // Enable task buttons based on capabilities
    const capabilities = asset.capabilities || [];
    document.querySelectorAll('.task-btn[data-task]').forEach(btn => {
        const task = btn.dataset.task;
        btn.disabled = !capabilities.includes(task) && task !== 'recall';
        btn.style.opacity = btn.disabled ? '0.4' : '1';
    });

    // Update camera feed if available
    const cameraFeed = document.getElementById('asset-camera-feed');
    if (asset.camera_url) {
        cameraFeed.innerHTML = `<img src="${asset.camera_url}" style="max-width: 100%; max-height: 100%; object-fit: contain;" alt="Asset camera">`;
    } else {
        cameraFeed.innerHTML = '<span class="text-muted">No feed available</span>';
    }
}

/**
 * Initialize tactical map canvas
 */
function initTacticalMap() {
    const canvas = document.getElementById('asset-map-canvas');
    if (!canvas) return;

    assetState.mapCanvas = canvas;
    assetState.mapCtx = canvas.getContext('2d');

    // Set canvas size
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;

    drawTacticalMap();

    // Handle resize
    window.addEventListener('resize', () => {
        const rect = canvas.parentElement.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
        drawTacticalMap();
    });
}

/**
 * Draw tactical map
 */
function drawTacticalMap() {
    const ctx = assetState.mapCtx;
    const canvas = assetState.mapCanvas;
    if (!ctx || !canvas) return;

    const w = canvas.width;
    const h = canvas.height;

    // Clear
    ctx.fillStyle = '#0a0a0f';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = '#1a1a2e';
    ctx.lineWidth = 1;
    const gridSize = 30;
    for (let x = 0; x < w; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, h);
        ctx.stroke();
    }
    for (let y = 0; y < h; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
    }

    // Property representation (center)
    const propW = w * 0.3;
    const propH = h * 0.4;
    const propX = (w - propW) / 2;
    const propY = (h - propH) / 2;

    ctx.fillStyle = '#1a1a2e';
    ctx.fillRect(propX, propY, propW, propH);
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.strokeRect(propX, propY, propW, propH);

    // Label
    ctx.fillStyle = '#00f0ff';
    ctx.font = '12px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText('PROPERTY', w / 2, h / 2);

    // Draw all assets
    for (const asset of assetState.assets) {
        if (asset.position_x === null || asset.position_y === null) continue;

        // Convert property coords (-15 to 15) to canvas coords
        const x = ((asset.position_x + 15) / 30) * w;
        const y = ((asset.position_y + 15) / 30) * h;

        const isSelected = assetState.selectedAsset?.asset_id === asset.asset_id;
        const color = STATUS_COLORS[asset.status] || '#00f0ff';

        // Draw asset
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(x, y, isSelected ? 10 : 7, 0, Math.PI * 2);
        ctx.fill();

        // Heading indicator
        if (asset.heading !== null) {
            const rad = (asset.heading - 90) * Math.PI / 180;
            const len = isSelected ? 20 : 15;
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(x, y);
            ctx.lineTo(x + Math.cos(rad) * len, y + Math.sin(rad) * len);
            ctx.stroke();
        }

        // Label
        ctx.fillStyle = '#fff';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(asset.asset_id, x, y - 15);
    }

    // Draw simulation targets
    for (const [tid, t] of Object.entries(assetState.simTargets)) {
        if (t.x === undefined || t.y === undefined) continue;

        // Lerp toward target position for smooth animation
        if (t._dispX === undefined) { t._dispX = t.x; t._dispY = t.y; }
        t._dispX += (t.x - t._dispX) * 0.15;
        t._dispY += (t.y - t._dispY) * 0.15;

        // Convert sim coords (-30 to 30) to canvas coords
        const sx = ((t._dispX + 30) / 60) * w;
        const sy = ((t._dispY + 30) / 60) * h;

        const alliance = (t.alliance || 'unknown').toLowerCase();

        // Draw waypoint patrol paths
        if (t.waypoints && t.waypoints.length > 1) {
            ctx.strokeStyle = 'rgba(0, 240, 255, 0.2)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 6]);
            ctx.beginPath();
            for (let i = 0; i < t.waypoints.length; i++) {
                const wp = t.waypoints[i];
                const wpx = ((wp.x + 30) / 60) * w;
                const wpy = ((wp.y + 30) / 60) * h;
                if (i === 0) ctx.moveTo(wpx, wpy);
                else ctx.lineTo(wpx, wpy);
            }
            ctx.closePath();
            ctx.stroke();
            ctx.setLineDash([]);
        }

        // Shape by alliance
        if (alliance === 'friendly') {
            ctx.fillStyle = '#05ffa1';
            ctx.beginPath();
            ctx.arc(sx, sy, 8, 0, Math.PI * 2);
            ctx.fill();
        } else if (alliance === 'hostile') {
            ctx.fillStyle = '#ff2a6d';
            ctx.beginPath();
            // Diamond shape
            ctx.moveTo(sx, sy - 8);
            ctx.lineTo(sx + 8, sy);
            ctx.lineTo(sx, sy + 8);
            ctx.lineTo(sx - 8, sy);
            ctx.closePath();
            ctx.fill();
        } else {
            ctx.fillStyle = '#fcee0a';
            ctx.fillRect(sx - 4, sy - 4, 8, 8);
        }

        // Heading indicator
        if (t.heading !== undefined && t.heading !== null) {
            const rad = (t.heading - 90) * Math.PI / 180;
            ctx.strokeStyle = alliance === 'friendly' ? '#05ffa1'
                : alliance === 'hostile' ? '#ff2a6d' : '#fcee0a';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sx, sy);
            ctx.lineTo(sx + Math.cos(rad) * 14, sy + Math.sin(rad) * 14);
            ctx.stroke();
        }

        // Name label
        ctx.fillStyle = '#fff';
        ctx.font = '10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.fillText(t.name || tid, sx, sy - 14);

        // Battery bar for friendlies
        if (alliance === 'friendly' && t.battery !== undefined) {
            const barW = 20;
            const barH = 4;
            const bx = sx - barW / 2;
            const by = sy + 12;
            // Background
            ctx.fillStyle = 'rgba(255,255,255,0.15)';
            ctx.fillRect(bx, by, barW, barH);
            // Fill with green-to-red gradient
            const level = Math.max(0, Math.min(1, t.battery));
            const r = Math.round(255 * (1 - level));
            const g = Math.round(255 * level);
            ctx.fillStyle = `rgb(${r}, ${g}, 0)`;
            ctx.fillRect(bx, by, barW * level, barH);
        }
    }

    // Draw dispatch arrows
    const now = Date.now();
    assetState.dispatchArrows = assetState.dispatchArrows.filter(a => now - a.time < 3000);
    for (const arrow of assetState.dispatchArrows) {
        const alpha = Math.max(0, 1 - (now - arrow.time) / 3000);
        drawDispatchArrow(ctx, w, h, arrow.fromX, arrow.fromY, arrow.toX, arrow.toY, alpha);
    }

    // Highlight selected asset's home
    if (assetState.selectedAsset && assetState.selectedAsset.home_x !== null && assetState.selectedAsset.home_x !== undefined) {
        const homeX = assetState.selectedAsset.home_x ?? 0;
        const homeY = assetState.selectedAsset.home_y ?? 0;
        const hx = ((homeX + 15) / 30) * w;
        const hy = ((homeY + 15) / 30) * h;

        ctx.strokeStyle = '#05ffa1';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(hx - 8, hy - 8, 16, 16);
        ctx.setLineDash([]);

        ctx.fillStyle = '#05ffa1';
        ctx.font = '8px "JetBrains Mono", monospace';
        ctx.fillText('HOME', hx, hy + 20);
    }
}

/**
 * Draw a dispatch arrow (magenta) from source to destination in sim coords
 */
function drawDispatchArrow(ctx, w, h, fromX, fromY, toX, toY, alpha) {
    const x1 = ((fromX + 30) / 60) * w;
    const y1 = ((fromY + 30) / 60) * h;
    const x2 = ((toX + 30) / 60) * w;
    const y2 = ((toY + 30) / 60) * h;

    ctx.strokeStyle = `rgba(255, 42, 109, ${alpha})`;
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Arrowhead
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const headLen = 10;
    ctx.fillStyle = `rgba(255, 42, 109, ${alpha})`;
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - headLen * Math.cos(angle - 0.4), y2 - headLen * Math.sin(angle - 0.4));
    ctx.lineTo(x2 - headLen * Math.cos(angle + 0.4), y2 - headLen * Math.sin(angle + 0.4));
    ctx.closePath();
    ctx.fill();
}

/**
 * Update a simulation target from WebSocket telemetry data
 */
function updateSimTarget(data) {
    if (!data || !data.target_id) return;

    // Flatten nested position to top-level x/y (SimulationTarget.to_dict()
    // sends {position: {x, y}} but assets.js/amy.js expect top-level t.x/t.y)
    const posX = data.position ? data.position.x : data.x;
    const posY = data.position ? data.position.y : data.y;

    const existing = assetState.simTargets[data.target_id];
    assetState.simTargets[data.target_id] = {
        ...existing,
        ...data,
        x: posX,
        y: posY,
        name: data.name || (existing && existing.name) || data.target_id,
        // Preserve display position for lerp
        _dispX: existing ? existing._dispX : posX,
        _dispY: existing ? existing._dispY : posY,
    };

    startSimAnimation();
    drawTacticalMap();
}

/**
 * Add a dispatch arrow to the tactical map
 */
function addDispatchArrow(targetId, destination) {
    const target = assetState.simTargets[targetId];
    if (!target) return;

    assetState.dispatchArrows.push({
        fromX: target.x || 0,
        fromY: target.y || 0,
        toX: destination.x,
        toY: destination.y,
        time: Date.now(),
    });

    startSimAnimation();
}

/**
 * Start animation loop for smooth sim target rendering
 */
function startSimAnimation() {
    if (assetState.simAnimating) return;
    assetState.simAnimating = true;

    function animate() {
        const hasTargets = Object.keys(assetState.simTargets).length > 0;
        const hasArrows = assetState.dispatchArrows.length > 0;

        if (!hasTargets && !hasArrows) {
            assetState.simAnimating = false;
            return;
        }

        drawTacticalMap();
        requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
}

/**
 * Start telemetry updates
 */
function startTelemetryUpdates() {
    if (assetState.telemetryInterval) {
        clearInterval(assetState.telemetryInterval);
    }

    assetState.telemetryInterval = setInterval(async () => {
        await loadAssets();
        if (assetState.selectedAsset) {
            const updated = assetState.assets.find(a => a.asset_id === assetState.selectedAsset.asset_id);
            if (updated) {
                assetState.selectedAsset = updated;
                updateAssetDetail(updated);
            }
        }
        drawTacticalMap();
    }, 5000);
}

/**
 * Assign task to selected asset
 */
async function assignTask(taskType) {
    if (!assetState.selectedAsset) {
        showNotification('WARNING', 'Select an asset first', 'warning');
        return;
    }

    const asset = assetState.selectedAsset;

    // Build task payload based on type
    let payload = { task_type: taskType };

    if (taskType === 'patrol') {
        // Default patrol waypoints (perimeter)
        payload.waypoints = [
            [-10, -10], [10, -10], [10, 10], [-10, 10]
        ];
    } else if (taskType === 'track' || taskType === 'engage') {
        // Would normally prompt for target selection
        const targetId = prompt('Enter target ID to track/engage:');
        if (!targetId) return;
        payload.target_type = 'person';
        payload.target_id = targetId;
    } else if (taskType === 'loiter' || taskType === 'investigate') {
        // Use current position or prompt
        payload.waypoints = [[asset.position_x || 0, asset.position_y || 0]];
    }

    try {
        const response = await fetch(`/api/assets/${asset.asset_id}/task`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to assign task');
        }

        const task = await response.json();
        showNotification('TASK ASSIGNED', `${taskType.toUpperCase()} -> ${asset.asset_id}`, 'success');

        // Start the task
        await fetch(`/api/assets/${asset.asset_id}/task/${task.task_id}/start`, { method: 'POST' });

        await loadAssets();
        selectAsset(asset.asset_id);

    } catch (e) {
        showNotification('ERROR', e.message, 'error');
    }
}

/**
 * Cancel current task
 */
async function cancelCurrentTask() {
    if (!assetState.selectedAsset?.current_task) {
        showNotification('INFO', 'No active task to cancel', 'info');
        return;
    }

    const asset = assetState.selectedAsset;
    const task = asset.current_task;

    try {
        await fetch(`/api/assets/${asset.asset_id}/task/${task.task_id}/cancel`, { method: 'POST' });
        showNotification('CANCELLED', `Task ${task.task_id} cancelled`, 'info');
        await loadAssets();
        selectAsset(asset.asset_id);
    } catch (e) {
        showNotification('ERROR', 'Failed to cancel task', 'error');
    }
}

/**
 * Recall asset to home
 */
async function recallAsset() {
    if (!assetState.selectedAsset) return;
    await assignTask('recall');
}

/**
 * Emergency stop
 */
async function emergencyStop() {
    if (!assetState.selectedAsset) return;

    try {
        const response = await fetch(`/api/assets/${assetState.selectedAsset.asset_id}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: 'emergency_stop' }),
        });
        if (!response.ok) throw new Error('Command failed');
        showNotification('E-STOP', `${assetState.selectedAsset.asset_id} stopped`, 'error');
        await loadAssets();
        selectAsset(assetState.selectedAsset.asset_id);
    } catch (e) {
        showNotification('ERROR', 'Failed to stop asset', 'error');
    }
}

/**
 * Show add asset modal
 */
function showAddAssetModal() {
    const assetId = prompt('Asset ID (e.g., UNIT-01):');
    if (!assetId || !assetId.trim()) {
        showNotification('CANCELLED', 'Asset ID is required', 'warning');
        return;
    }

    // Validate asset ID format
    const cleanId = assetId.trim().toUpperCase().replace(/[^A-Z0-9-]/g, '');
    if (cleanId.length < 3) {
        showNotification('INVALID', 'Asset ID must be at least 3 characters', 'error');
        return;
    }

    const name = prompt('Asset name (e.g., Perimeter Guardian Alpha):');
    if (!name || !name.trim()) {
        showNotification('CANCELLED', 'Asset name is required', 'warning');
        return;
    }

    const assetType = prompt('Asset type (ground, aerial, fixed):') || 'ground';
    const validTypes = ['ground', 'aerial', 'fixed'];
    const cleanType = assetType.trim().toLowerCase();
    if (!validTypes.includes(cleanType)) {
        showNotification('INVALID', 'Asset type must be: ground, aerial, or fixed', 'error');
        return;
    }

    const assetClass = prompt('Asset class (patrol, interceptor, observation, transport):') || 'patrol';
    const validClasses = ['patrol', 'interceptor', 'observation', 'transport'];
    const cleanClass = assetClass.trim().toLowerCase();
    if (!validClasses.includes(cleanClass)) {
        showNotification('INVALID', 'Asset class must be: patrol, interceptor, observation, or transport', 'error');
        return;
    }

    registerAsset(cleanId, name.trim(), cleanType, cleanClass);
}

/**
 * Register a new asset
 */
async function registerAsset(assetId, name, assetType, assetClass) {
    try {
        const response = await fetch('/api/assets', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                asset_id: assetId,
                name: name,
                asset_type: assetType,
                asset_class: assetClass,
                capabilities: ['patrol', 'loiter', 'recall', 'investigate'],
            }),
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Registration failed');
        }

        showNotification('REGISTERED', `Asset ${assetId} online`, 'success');
        await loadAssets();

    } catch (e) {
        showNotification('ERROR', e.message, 'error');
    }
}

// Note: View switching is handled by app.js which calls initAssetsView()

// Add CSS
const assetStyles = document.createElement('style');
assetStyles.textContent = `
.asset-card {
    background: rgba(26, 26, 46, 0.6);
    border: 1px solid rgba(0, 240, 255, 0.2);
    border-radius: 4px;
    padding: var(--space-sm);
    margin-bottom: var(--space-sm);
    cursor: pointer;
    transition: all 0.2s ease;
}

.asset-card:hover {
    border-color: var(--cyan);
    background: rgba(0, 240, 255, 0.05);
}

.asset-card.selected {
    border-color: var(--magenta);
    background: rgba(255, 42, 109, 0.1);
}

.asset-card-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
}

.asset-icon {
    font-size: 1.2rem;
}

.asset-name {
    flex: 1;
    font-weight: bold;
    color: var(--cyan);
}

.asset-status {
    font-size: 0.6rem;
    padding: 2px 6px;
    border-radius: 2px;
    text-transform: uppercase;
}

.asset-card-body {
    display: flex;
    justify-content: space-between;
    font-size: 0.75rem;
    margin-bottom: 4px;
}

.asset-id {
    color: var(--text-muted);
    font-family: 'JetBrains Mono', monospace;
}

.asset-class {
    color: var(--cyan);
    font-size: 0.65rem;
}

.asset-card-footer {
    display: flex;
    justify-content: space-between;
    font-size: 0.7rem;
    color: var(--text-muted);
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

.task-btn {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: var(--space-sm) !important;
    font-size: 0.7rem !important;
}

.task-btn span {
    font-size: 1.2rem;
}

.task-btn:disabled {
    cursor: not-allowed;
}

#asset-map-canvas {
    background: #0a0a0f;
}
`;
document.head.appendChild(assetStyles);

// Expose functions
window.initAssetsView = initAssetsView;
window.selectAsset = selectAsset;
window.assignTask = assignTask;
window.cancelCurrentTask = cancelCurrentTask;
window.recallAsset = recallAsset;
window.emergencyStop = emergencyStop;
window.showAddAssetModal = showAddAssetModal;
window.updateSimTarget = updateSimTarget;
window.addDispatchArrow = addDispatchArrow;
window.assetState = assetState;
