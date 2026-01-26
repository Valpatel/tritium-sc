/**
 * TRITIUM-SC Zones Management
 * Manages zone view, zone list, and zone events
 */

// Global zone editor instance
let zoneEditor = null;
let currentZones = [];
let selectedZoneId = null;
let selectedCameraForZones = null;

/**
 * Initialize zones view when switching to it
 */
async function initZonesView() {
    await loadAllZones();
    updateSidebarZoneList();
    updateZoneListPanel();
}

/**
 * Load all zones from API
 */
async function loadAllZones() {
    try {
        const response = await fetch('/api/zones/');
        if (response.ok) {
            currentZones = await response.json();
        }
    } catch (e) {
        console.error('Failed to load zones:', e);
        currentZones = [];
    }
}

/**
 * Update sidebar zone list
 */
function updateSidebarZoneList() {
    const list = document.getElementById('sidebar-zone-list');
    if (!list) return;

    if (currentZones.length === 0) {
        list.innerHTML = '<li class="text-muted" style="padding: var(--space-xs);">No zones defined</li>';
        return;
    }

    // Group zones by camera
    const byCamera = {};
    for (const zone of currentZones) {
        if (!byCamera[zone.camera_id]) {
            byCamera[zone.camera_id] = [];
        }
        byCamera[zone.camera_id].push(zone);
    }

    let html = '';
    for (const [cameraId, zones] of Object.entries(byCamera)) {
        html += `<li class="tree-item">
            <span class="tree-icon text-cyan">CH${cameraId}</span>
            <ul class="tree-list" style="padding-left: var(--space-md);">`;

        for (const zone of zones) {
            const color = getZoneTypeColor(zone.zone_type);
            const eventBadge = zone.total_events > 0
                ? `<span class="badge" style="background: var(--magenta); font-size: 0.6rem; padding: 2px 4px; margin-left: 4px;">${zone.total_events}</span>`
                : '';

            html += `<li class="tree-item" onclick="selectZone('${zone.zone_id}')" style="cursor: pointer;">
                <span style="color: ${color};">&#9632;</span>
                ${zone.name}${eventBadge}
            </li>`;
        }

        html += '</ul></li>';
    }

    list.innerHTML = html;
}

/**
 * Update main zone list panel
 */
function updateZoneListPanel() {
    const list = document.getElementById('zone-list');
    if (!list) return;

    // Filter by selected camera if any
    const zones = selectedCameraForZones
        ? currentZones.filter(z => z.camera_id === selectedCameraForZones)
        : currentZones;

    if (zones.length === 0) {
        list.innerHTML = `<div class="text-muted" style="padding: var(--space-sm);">
            ${selectedCameraForZones ? 'No zones for this camera' : 'No zones defined. Select a camera and click DRAW.'}
        </div>`;
        return;
    }

    let html = '';
    for (const zone of zones) {
        const color = getZoneTypeColor(zone.zone_type);
        const isSelected = zone.zone_id === selectedZoneId;
        const bgStyle = isSelected ? 'background: rgba(0, 240, 255, 0.1); border-left: 3px solid var(--cyan);' : '';

        html += `<div class="zone-item" onclick="selectZone('${zone.zone_id}')"
                      style="padding: var(--space-sm); margin-bottom: var(--space-xs); cursor: pointer; ${bgStyle}">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <span style="color: ${color}; font-weight: bold;">${zone.name}</span>
                <span class="badge" style="background: ${color}; color: #0a0a0f; font-size: 0.6rem; padding: 2px 6px;">
                    ${zone.zone_type.toUpperCase()}
                </span>
            </div>
            <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 4px;">
                ${zone.total_events} events
                ${zone.monitored_object ? ` | Monitoring: ${zone.monitored_object}` : ''}
            </div>
            ${zone.last_event_at ? `<div style="font-size: 0.65rem; color: var(--text-muted);">
                Last: ${new Date(zone.last_event_at).toLocaleString()}
            </div>` : ''}
        </div>`;
    }

    list.innerHTML = html;
}

/**
 * Select a zone and show its events
 */
async function selectZone(zoneId) {
    selectedZoneId = zoneId;
    updateZoneListPanel();
    await loadZoneEvents(zoneId);

    // Highlight zone on canvas if editor exists
    if (zoneEditor) {
        const zone = currentZones.find(z => z.zone_id === zoneId);
        if (zone) {
            zoneEditor.selectedZone = zone;
            zoneEditor.render();
            zoneEditor.showZoneInfo(zone);
        }
    }
}

/**
 * Load events for a specific zone
 */
async function loadZoneEvents(zoneId) {
    const eventsList = document.getElementById('zone-events-list');
    const eventCount = document.getElementById('zone-event-count');

    if (!eventsList) return;

    try {
        // Get zone summary for richer data
        const summaryResponse = await fetch(`/api/zones/${zoneId}/summary`);
        const summary = summaryResponse.ok ? await summaryResponse.json() : null;

        // Get recent events
        const eventsResponse = await fetch(`/api/zones/${zoneId}/events?limit=20`);
        if (!eventsResponse.ok) {
            eventsList.innerHTML = '<div class="text-muted">Failed to load events</div>';
            return;
        }

        const events = await eventsResponse.json();
        eventCount.textContent = `${summary?.total_events || events.length} events`;

        if (events.length === 0) {
            eventsList.innerHTML = '<div class="text-muted">No events recorded for this zone</div>';
            return;
        }

        // Show summary stats
        let html = '';

        if (summary) {
            html += `<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--space-sm); margin-bottom: var(--space-md);">
                <div class="panel" style="padding: var(--space-xs); text-align: center;">
                    <div class="text-cyan" style="font-size: 1.2rem; font-weight: bold;">${summary.total_events}</div>
                    <div style="font-size: 0.65rem;">TOTAL</div>
                </div>
                <div class="panel" style="padding: var(--space-xs); text-align: center;">
                    <div class="text-magenta" style="font-size: 1.2rem; font-weight: bold;">${summary.peak_hour !== null ? summary.peak_hour + ':00' : '-'}</div>
                    <div style="font-size: 0.65rem;">PEAK HOUR</div>
                </div>
                <div class="panel" style="padding: var(--space-xs); text-align: center;">
                    <div class="text-green" style="font-size: 1.2rem; font-weight: bold;">${Object.keys(summary.events_by_type || {}).length}</div>
                    <div style="font-size: 0.65rem;">TARGET TYPES</div>
                </div>
            </div>`;

            // Target type breakdown
            if (summary.events_by_type && Object.keys(summary.events_by_type).length > 0) {
                html += '<div style="margin-bottom: var(--space-sm);">';
                for (const [type, count] of Object.entries(summary.events_by_type)) {
                    const pct = Math.round((count / summary.total_events) * 100);
                    html += `<div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                        <span>${type}</span>
                        <span class="text-cyan">${count} (${pct}%)</span>
                    </div>`;
                }
                html += '</div>';
            }
        }

        // Recent events list
        html += '<div style="font-weight: bold; margin-bottom: var(--space-xs);">Recent Events:</div>';
        for (const event of events) {
            const time = new Date(event.timestamp).toLocaleString();
            const targetColor = event.target_type === 'person' ? 'var(--cyan)' : 'var(--magenta)';

            html += `<div class="event-item" style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid rgba(255,255,255,0.1);">
                <span style="color: ${targetColor};">${event.target_type || 'unknown'}</span>
                <span class="text-muted">${time}</span>
            </div>`;
        }

        eventsList.innerHTML = html;

    } catch (e) {
        console.error('Failed to load zone events:', e);
        eventsList.innerHTML = '<div class="text-muted">Error loading events</div>';
    }
}

/**
 * Start zone drawing mode
 */
function startZoneDrawing() {
    if (!selectedCameraForZones) {
        showNotification('WARNING', 'Select a camera first', 'warning');
        return;
    }

    if (!zoneEditor) {
        showNotification('ERROR', 'Zone editor not initialized', 'error');
        return;
    }

    zoneEditor.startDrawing();
    document.getElementById('btn-draw-zone').textContent = 'DRAWING...';
    document.getElementById('btn-draw-zone').disabled = true;
}

/**
 * Initialize zone editor for a camera
 */
async function initZoneEditorForCamera(cameraId) {
    selectedCameraForZones = cameraId;

    // Hide empty state
    document.getElementById('zone-empty-state').style.display = 'none';

    // Get a preview frame from the camera
    const container = document.getElementById('zone-editor-container');
    const img = document.getElementById('zone-background-image');

    // Try to load a preview image
    try {
        // Get most recent date for this channel
        const datesResponse = await fetch(`/api/videos/channels/${cameraId}/dates`);
        if (datesResponse.ok) {
            const dates = await datesResponse.json();
            if (dates.length > 0) {
                const mostRecentDate = dates[0].date;
                // Get videos for that date
                const videosResponse = await fetch(`/api/videos/channels/${cameraId}/dates/${mostRecentDate}`);
                if (videosResponse.ok) {
                    const videos = await videosResponse.json();
                    if (videos.length > 0) {
                        // Use video thumbnail as background
                        const thumbnailUrl = `/api/videos/thumbnail/${cameraId}/${mostRecentDate}/${videos[0].filename}`;
                        img.src = thumbnailUrl;
                        img.style.display = 'block';
                        img.onload = () => {
                            // Initialize zone editor once image loads
                            if (zoneEditor) {
                                zoneEditor.destroy();
                            }
                            zoneEditor = new ZoneEditor('zone-editor-container', cameraId);
                            window.zoneEditor = zoneEditor;
                        };
                        img.onerror = () => {
                            // Still initialize editor with a placeholder
                            console.warn('Could not load thumbnail, using placeholder');
                            img.style.display = 'none';
                            initZoneEditorWithPlaceholder(cameraId);
                        };
                        return;
                    }
                }
            }
        }
        // No videos found, init with placeholder
        initZoneEditorWithPlaceholder(cameraId);
    } catch (e) {
        console.error('Failed to load camera preview:', e);
        initZoneEditorWithPlaceholder(cameraId);
    }

    // Update zone list for this camera
    updateZoneListPanel();

    // Reset draw button
    document.getElementById('btn-draw-zone').textContent = '+ DRAW';
    document.getElementById('btn-draw-zone').disabled = false;
}

/**
 * Initialize zone editor with a placeholder background
 */
function initZoneEditorWithPlaceholder(cameraId) {
    const container = document.getElementById('zone-editor-container');
    const img = document.getElementById('zone-background-image');

    // Show a placeholder grid pattern
    img.src = 'data:image/svg+xml,' + encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080" viewBox="0 0 1920 1080">
            <defs>
                <pattern id="grid" width="100" height="100" patternUnits="userSpaceOnUse">
                    <path d="M 100 0 L 0 0 0 100" fill="none" stroke="#1a1a2e" stroke-width="1"/>
                </pattern>
            </defs>
            <rect width="100%" height="100%" fill="#0a0a0f"/>
            <rect width="100%" height="100%" fill="url(#grid)"/>
            <text x="960" y="540" text-anchor="middle" fill="#00f0ff" font-family="monospace" font-size="24">CH${cameraId} - ZONE EDITOR</text>
            <text x="960" y="580" text-anchor="middle" fill="#555" font-family="monospace" font-size="14">No preview available - draw zones on grid</text>
        </svg>
    `);
    img.style.display = 'block';

    if (zoneEditor) {
        zoneEditor.destroy();
    }
    zoneEditor = new ZoneEditor('zone-editor-container', cameraId);
    window.zoneEditor = zoneEditor;

    updateZoneListPanel();
    document.getElementById('btn-draw-zone').textContent = '+ DRAW';
    document.getElementById('btn-draw-zone').disabled = false;
}

/**
 * Get color for zone type
 */
function getZoneTypeColor(zoneType) {
    const colors = {
        activity: 'var(--cyan)',
        entry_exit: 'var(--green)',
        object_monitor: 'var(--yellow)',
        tripwire: 'var(--magenta)',
    };
    return colors[zoneType] || 'var(--cyan)';
}

// Note: View switching is handled by app.js which calls initZonesView() and initZoneEditorForCamera()

/**
 * Hook into camera selection for zones
 */
function onCameraSelectedForZones(cameraId) {
    if (document.getElementById('view-zones').classList.contains('hidden')) {
        return; // Not in zones view
    }
    initZoneEditorForCamera(cameraId);
}

// Initialize zones when DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Load zones for sidebar
    loadAllZones().then(updateSidebarZoneList);
});

// Expose global functions
window.startZoneDrawing = startZoneDrawing;
window.selectZone = selectZone;
window.initZoneEditorForCamera = initZoneEditorForCamera;
window.zoneEditor = null; // Will be set by ZoneEditor constructor
