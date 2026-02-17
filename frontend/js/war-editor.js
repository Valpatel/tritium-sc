/**
 * TRITIUM-SC War Room Editor
 * SETUP mode editor for placing cameras, sensors, robots on the tactical map.
 *
 * Architecture
 * -----------
 * This module extends war.js SETUP mode with rich placement, rotation,
 * FOV/radius visualization, asset configuration, and layout save/load.
 * It reads/writes warState from war.js and draws on the same Canvas 2D.
 *
 * Data flow:
 *   - Palette click -> editorState.placing (ghost follows mouse)
 *   - Canvas click -> placeAsset() -> POST /api/amy/simulation/spawn
 *   - Placed assets stored in editorState.placedAssets (local registry)
 *   - Save: serialize to TritiumLevelFormat JSON -> POST /api/amy/layouts
 *   - Load: GET /api/amy/layouts/{name} -> spawn each object
 *
 * Integration:
 *   - war.js calls warEditorEnter() / warEditorExit() on mode change
 *   - war.js render loop calls warEditorDraw(ctx) each frame
 *   - war.js key handler calls warEditorKey(e) for editor-specific keys
 *   - war.js mouse handlers call warEditorMouse*(e) for placement
 *
 * Sections:
 *   - Editor state & asset definitions
 *   - Ghost rendering (placement preview)
 *   - Placed asset rendering (FOV cones, radius circles)
 *   - Placement logic
 *   - Asset interaction (select, configure, delete)
 *   - Palette UI
 *   - Save / Load
 *   - Global exports
 */

// ============================================================
// Editor state
// ============================================================

const editorState = {
    // Currently placing
    placing: null,        // { type, category, def } or null
    ghostRotation: 0,     // degrees, 0=north, increments of 45
    ghostWorldPos: null,  // { x, y } world coords under mouse

    // Placed assets (local registry, mirrors sim engine)
    placedAssets: {},     // target_id -> { type, category, position, rotation, config, def }

    // Selected placed asset
    selectedAsset: null,  // target_id or null
    hoveredAsset: null,   // target_id or null

    // Config panel
    configPanelVisible: false,

    // Layout management
    currentLayoutName: '',

    // UI elements
    paletteEl: null,
    configPanelEl: null,
    layoutPanelEl: null,
    initialized: false,
};

// ============================================================
// Asset definitions with influence visualization
// ============================================================

const EDITOR_ASSETS = {
    // --- SENSORS ---
    camera: {
        category: 'sensors', label: 'Camera', icon: 'CAM',
        color: '#00f0ff',
        influence: { type: 'fov', fov: 60, range: 15 },
        config: {
            fov: { label: 'FOV', min: 30, max: 120, step: 10, default: 60 },
            range: { label: 'Range', min: 5, max: 40, step: 5, default: 15 },
        },
        simType: 'camera', simAlliance: 'friendly',
    },
    ptz_camera: {
        category: 'sensors', label: 'PTZ Camera', icon: 'PTZ',
        color: '#05ffa1',
        influence: { type: 'fov', fov: 45, range: 25 },
        config: {
            fov: { label: 'FOV', min: 10, max: 90, step: 5, default: 45 },
            range: { label: 'Range', min: 10, max: 60, step: 5, default: 25 },
        },
        simType: 'ptz_camera', simAlliance: 'friendly',
    },
    dome_camera: {
        category: 'sensors', label: 'Dome Camera', icon: 'DME',
        color: '#00f0ff',
        influence: { type: 'radius', radius: 10 },
        config: {
            radius: { label: 'Range', min: 5, max: 25, step: 5, default: 10 },
        },
        simType: 'dome_camera', simAlliance: 'friendly',
    },
    motion_sensor: {
        category: 'sensors', label: 'Motion Sensor', icon: 'MOT',
        color: '#fcee0a',
        influence: { type: 'arc', arc: 120, range: 8 },
        config: {
            arc: { label: 'Arc', min: 45, max: 360, step: 15, default: 120 },
            range: { label: 'Range', min: 3, max: 20, step: 1, default: 8 },
        },
        simType: 'motion_sensor', simAlliance: 'friendly',
    },
    microphone_sensor: {
        category: 'sensors', label: 'Microphone', icon: 'MIC',
        color: '#fcee0a',
        influence: { type: 'radius', radius: 15 },
        config: {
            radius: { label: 'Range', min: 5, max: 30, step: 5, default: 15 },
        },
        simType: 'microphone_sensor', simAlliance: 'friendly',
    },

    // --- ROBOTS ---
    patrol_rover: {
        category: 'robots', label: 'Patrol Rover', icon: 'ROV',
        color: '#05ffa1',
        influence: { type: 'radius', radius: 10 },
        config: {
            sensorRange: { label: 'Sensor Range', min: 5, max: 25, step: 5, default: 10 },
        },
        simType: 'patrol_rover', simAlliance: 'friendly',
    },
    interceptor_bot: {
        category: 'robots', label: 'Interceptor Bot', icon: 'INT',
        color: '#05ffa1',
        influence: { type: 'radius', radius: 15 },
        config: {
            sensorRange: { label: 'Sensor Range', min: 5, max: 30, step: 5, default: 15 },
        },
        simType: 'interceptor_bot', simAlliance: 'friendly',
    },
    recon_drone: {
        category: 'robots', label: 'Recon Drone', icon: 'RDR',
        color: '#05ffa1',
        influence: { type: 'radius', radius: 12 },
        config: {
            altitude: { label: 'Altitude', min: 5, max: 40, step: 5, default: 15 },
        },
        simType: 'recon_drone', simAlliance: 'friendly',
    },
    heavy_drone: {
        category: 'robots', label: 'Heavy Drone', icon: 'HDR',
        color: '#05ffa1',
        influence: { type: 'radius', radius: 18 },
        config: {
            altitude: { label: 'Altitude', min: 10, max: 50, step: 5, default: 20 },
        },
        simType: 'heavy_drone', simAlliance: 'friendly',
    },

    // --- INFRASTRUCTURE ---
    sentry_turret: {
        category: 'infrastructure', label: 'Sentry Turret', icon: 'TRT',
        color: '#ff2a6d',
        influence: { type: 'arc', arc: 180, range: 20 },
        config: {
            arc: { label: 'Arc', min: 90, max: 360, step: 30, default: 180 },
            range: { label: 'Range', min: 10, max: 40, step: 5, default: 20 },
        },
        simType: 'sentry_turret', simAlliance: 'friendly',
    },
    speaker: {
        category: 'infrastructure', label: 'Speaker', icon: 'SPK',
        color: '#00f0ff',
        influence: { type: 'radius', radius: 12 },
        config: {},
        simType: 'speaker', simAlliance: 'friendly',
    },
    floodlight: {
        category: 'infrastructure', label: 'Floodlight', icon: 'FLD',
        color: '#fcee0a',
        influence: { type: 'fov', fov: 90, range: 15 },
        config: {
            arc: { label: 'Arc', min: 30, max: 180, step: 15, default: 90 },
            range: { label: 'Range', min: 5, max: 30, step: 5, default: 15 },
        },
        simType: 'floodlight', simAlliance: 'friendly',
    },
};

// Category display order
const EDITOR_CATEGORIES = [
    { key: 'sensors', label: 'SENSORS', color: '#00f0ff' },
    { key: 'robots', label: 'ROBOTS', color: '#05ffa1' },
    { key: 'infrastructure', label: 'INFRASTRUCTURE', color: '#ff2a6d' },
];

// ============================================================
// Enter / Exit
// ============================================================

function warEditorEnter() {
    if (!editorState.initialized) {
        _buildEditorPalette();
        _buildConfigPanel();
        _buildLayoutPanel();
        editorState.initialized = true;
    }
    _showEditorPalette(true);
    _showLayoutPanel(true);
    // Sync existing sim targets into placedAssets
    _syncFromSimTargets();
}

function warEditorExit() {
    editorState.placing = null;
    editorState.selectedAsset = null;
    editorState.hoveredAsset = null;
    editorState.configPanelVisible = false;
    _showEditorPalette(false);
    _showConfigPanel(false);
    _showLayoutPanel(false);
}

// ============================================================
// Draw (called each frame from war.js render loop)
// ============================================================

function warEditorDraw(ctx) {
    if (typeof warState === 'undefined') return;
    if (warState.mode !== 'setup') return;

    _drawPlacedAssetOverlays(ctx);
    _drawGhost(ctx);
    _drawSelectedHighlight(ctx);
}

function _drawPlacedAssetOverlays(ctx) {
    for (const [tid, asset] of Object.entries(editorState.placedAssets)) {
        const def = asset.def;
        if (!def || !def.influence) continue;

        const sp = worldToScreen(asset.position.x, asset.position.y);
        const rot = asset.rotation || 0;
        const config = asset.config || {};
        const isHovered = editorState.hoveredAsset === tid;
        const isSelected = editorState.selectedAsset === tid;
        const alpha = isSelected ? 0.20 : (isHovered ? 0.15 : 0.08);

        _drawInfluence(ctx, sp, rot, def, config, alpha);
    }
}

function _drawInfluence(ctx, screenPos, rotation, def, config, alpha) {
    const inf = def.influence;
    const zoom = warState.cam.zoom;
    const color = def.color || '#00f0ff';

    if (inf.type === 'fov') {
        const fov = config.fov || inf.fov;
        const range = config.range || inf.range;
        const halfFov = (fov / 2) * Math.PI / 180;
        const screenRange = range * zoom;
        // rotation: 0=north(+y), clockwise in degrees
        // canvas: 0=right, counter-clockwise, Y inverted
        const centerAngle = -(rotation - 90) * Math.PI / 180;

        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.arc(screenPos.x, screenPos.y, screenRange, centerAngle - halfFov, centerAngle + halfFov);
        ctx.closePath();
        ctx.fill();

        // Edge lines
        ctx.strokeStyle = color;
        ctx.globalAlpha = alpha * 2;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.lineTo(
            screenPos.x + Math.cos(centerAngle - halfFov) * screenRange,
            screenPos.y + Math.sin(centerAngle - halfFov) * screenRange
        );
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.lineTo(
            screenPos.x + Math.cos(centerAngle + halfFov) * screenRange,
            screenPos.y + Math.sin(centerAngle + halfFov) * screenRange
        );
        ctx.stroke();
        ctx.globalAlpha = 1.0;

    } else if (inf.type === 'radius') {
        const radius = config.radius || config.sensorRange || inf.radius;
        const screenRadius = radius * zoom;

        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.arc(screenPos.x, screenPos.y, screenRadius, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = color;
        ctx.globalAlpha = alpha * 2;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.arc(screenPos.x, screenPos.y, screenRadius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.globalAlpha = 1.0;

    } else if (inf.type === 'arc') {
        const arc = config.arc || inf.arc;
        const range = config.range || inf.range;
        const halfArc = (arc / 2) * Math.PI / 180;
        const screenRange = range * zoom;
        const centerAngle = -(rotation - 90) * Math.PI / 180;

        ctx.fillStyle = color;
        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.arc(screenPos.x, screenPos.y, screenRange, centerAngle - halfArc, centerAngle + halfArc);
        ctx.closePath();
        ctx.fill();

        ctx.strokeStyle = color;
        ctx.globalAlpha = alpha * 2;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.lineTo(
            screenPos.x + Math.cos(centerAngle - halfArc) * screenRange,
            screenPos.y + Math.sin(centerAngle - halfArc) * screenRange
        );
        ctx.moveTo(screenPos.x, screenPos.y);
        ctx.lineTo(
            screenPos.x + Math.cos(centerAngle + halfArc) * screenRange,
            screenPos.y + Math.sin(centerAngle + halfArc) * screenRange
        );
        ctx.stroke();
        ctx.globalAlpha = 1.0;
    }
}

function _drawGhost(ctx) {
    if (!editorState.placing || !editorState.ghostWorldPos) return;

    const def = editorState.placing.def;
    const wp = editorState.ghostWorldPos;
    const sp = worldToScreen(wp.x, wp.y);
    const rot = editorState.ghostRotation;
    const color = def.color || '#fcee0a';
    const zoom = warState.cam.zoom;

    // Draw influence area (semi-transparent)
    _drawInfluence(ctx, sp, rot, def, {}, 0.10);

    // Draw asset icon
    const iconRadius = 8 * Math.min(zoom, 3);
    ctx.globalAlpha = 0.7;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, iconRadius, 0, Math.PI * 2);
    ctx.fill();

    // Direction indicator (line from center showing rotation)
    const dirAngle = -(rot - 90) * Math.PI / 180;
    const dirLen = iconRadius * 2.5;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sp.x, sp.y);
    ctx.lineTo(sp.x + Math.cos(dirAngle) * dirLen, sp.y + Math.sin(dirAngle) * dirLen);
    ctx.stroke();

    // Label
    ctx.fillStyle = color;
    ctx.font = `bold ${Math.max(9, 10 * Math.min(zoom, 2))}px "JetBrains Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(def.label.toUpperCase(), sp.x, sp.y - iconRadius - 6);

    // Rotation hint
    ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
    ctx.font = `${Math.max(7, 8 * Math.min(zoom, 2))}px "JetBrains Mono", monospace`;
    ctx.fillText(`${rot}\u00B0  [R]otate`, sp.x, sp.y + iconRadius + 14);

    ctx.globalAlpha = 1.0;
}

function _drawSelectedHighlight(ctx) {
    if (!editorState.selectedAsset) return;
    const asset = editorState.placedAssets[editorState.selectedAsset];
    if (!asset) return;

    const sp = worldToScreen(asset.position.x, asset.position.y);
    const zoom = warState.cam.zoom;
    const radius = 12 * Math.min(zoom, 3);

    // Animated selection ring
    const time = Date.now() / 1000;
    const pulse = 1 + 0.15 * Math.sin(time * 3);

    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.shadowColor = '#00f0ff';
    ctx.shadowBlur = 10;
    ctx.setLineDash([6, 4]);
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, radius * pulse, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;

    // Direction arrow
    const rot = asset.rotation || 0;
    const dirAngle = -(rot - 90) * Math.PI / 180;
    const arrowLen = radius * 2;
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(sp.x, sp.y);
    ctx.lineTo(sp.x + Math.cos(dirAngle) * arrowLen, sp.y + Math.sin(dirAngle) * arrowLen);
    ctx.stroke();

    // Arrowhead
    const tipX = sp.x + Math.cos(dirAngle) * arrowLen;
    const tipY = sp.y + Math.sin(dirAngle) * arrowLen;
    const headLen = 8;
    ctx.fillStyle = '#00f0ff';
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - headLen * Math.cos(dirAngle - 0.4), tipY - headLen * Math.sin(dirAngle - 0.4));
    ctx.lineTo(tipX - headLen * Math.cos(dirAngle + 0.4), tipY - headLen * Math.sin(dirAngle + 0.4));
    ctx.closePath();
    ctx.fill();
}

// ============================================================
// Mouse events (called from war.js)
// ============================================================

function warEditorMouseMove(sx, sy) {
    if (warState.mode !== 'setup') return;
    editorState.ghostWorldPos = screenToWorld(sx, sy);

    // Hover detection for placed assets
    editorState.hoveredAsset = _hitTestPlacedAsset(sx, sy);

    // Cursor
    if (warState.canvas) {
        if (editorState.placing) {
            warState.canvas.style.cursor = 'cell';
        } else if (editorState.hoveredAsset) {
            warState.canvas.style.cursor = 'pointer';
        }
    }
}

function warEditorMouseDown(sx, sy, button, shiftKey) {
    if (warState.mode !== 'setup') return false;

    if (button === 0 && editorState.placing) {
        // Place the asset
        const wp = screenToWorld(sx, sy);
        _doPlaceAsset(editorState.placing, wp.x, wp.y, editorState.ghostRotation);
        return true; // consumed
    }

    if (button === 0 && !editorState.placing) {
        // Select placed asset
        const hit = _hitTestPlacedAsset(sx, sy);
        if (hit) {
            editorState.selectedAsset = hit;
            _showConfigPanel(true);
            _updateConfigPanel();
            return true;
        } else {
            editorState.selectedAsset = null;
            _showConfigPanel(false);
        }
    }

    if (button === 2 && editorState.placing) {
        // Cancel placement
        editorState.placing = null;
        _updatePaletteSelection();
        return true;
    }

    return false;
}

function _hitTestPlacedAsset(sx, sy) {
    const hitRadius = 16;
    let closest = null;
    let closestDist = Infinity;

    for (const [tid, asset] of Object.entries(editorState.placedAssets)) {
        const sp = worldToScreen(asset.position.x, asset.position.y);
        const dx = sp.x - sx;
        const dy = sp.y - sy;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < hitRadius && dist < closestDist) {
            closestDist = dist;
            closest = tid;
        }
    }
    return closest;
}

// ============================================================
// Keyboard (called from war.js)
// ============================================================

function warEditorKey(e) {
    if (warState.mode !== 'setup') return false;

    switch (e.key) {
        case 'r':
        case 'R':
            if (editorState.placing) {
                editorState.ghostRotation = (editorState.ghostRotation + 45) % 360;
                return true;
            }
            if (editorState.selectedAsset) {
                const asset = editorState.placedAssets[editorState.selectedAsset];
                if (asset) {
                    asset.rotation = ((asset.rotation || 0) + 45) % 360;
                    return true;
                }
            }
            break;
        case 'Delete':
        case 'Backspace':
            if (editorState.selectedAsset) {
                _deleteAsset(editorState.selectedAsset);
                return true;
            }
            break;
        case 'Escape':
            if (editorState.placing) {
                editorState.placing = null;
                _updatePaletteSelection();
                return true;
            }
            if (editorState.selectedAsset) {
                editorState.selectedAsset = null;
                _showConfigPanel(false);
                return true;
            }
            break;
    }
    return false;
}

// ============================================================
// Placement
// ============================================================

function _doPlaceAsset(placing, worldX, worldY, rotation) {
    const def = placing.def;
    const name = `${placing.type}-${Date.now().toString(36).slice(-4)}`;

    // Spawn via simulation API
    fetch('/api/amy/simulation/spawn', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            name: name,
            asset_type: def.simType || placing.type,
            alliance: def.simAlliance || 'friendly',
            position: { x: worldX, y: worldY },
        }),
    }).then(res => {
        if (!res.ok) throw new Error('Spawn failed');
        return res.json();
    }).then(data => {
        const tid = data.target && data.target.target_id;
        if (tid) {
            editorState.placedAssets[tid] = {
                type: placing.type,
                category: placing.category,
                position: { x: worldX, y: worldY },
                rotation: rotation,
                config: _getDefaultConfig(def),
                def: def,
                name: name,
            };
        }
        // Sound + alert
        if (typeof warPlaySound === 'function') warPlaySound('place');
        if (typeof warAddAlert === 'function') {
            warAddAlert(`Placed ${def.label} at (${worldX.toFixed(1)}, ${worldY.toFixed(1)})`, 'info');
        }
    }).catch(err => {
        console.error('[WAR-EDITOR] Spawn failed:', err);
        if (typeof warAddAlert === 'function') warAddAlert('Spawn failed', 'hostile');
    });
}

function _deleteAsset(tid) {
    fetch(`/api/amy/simulation/targets/${tid}`, { method: 'DELETE' })
        .then(res => {
            if (res.ok) {
                const asset = editorState.placedAssets[tid];
                const label = asset ? asset.def.label : tid;
                delete editorState.placedAssets[tid];
                if (editorState.selectedAsset === tid) {
                    editorState.selectedAsset = null;
                    _showConfigPanel(false);
                }
                if (typeof warAddAlert === 'function') warAddAlert(`Removed ${label}`, 'info');
            }
        })
        .catch(err => console.error('[WAR-EDITOR] Remove failed:', err));
}

function _getDefaultConfig(def) {
    const config = {};
    if (def.config) {
        for (const [key, spec] of Object.entries(def.config)) {
            config[key] = spec.default;
        }
    }
    return config;
}

// ============================================================
// Sync from sim targets (on enter)
// ============================================================

function _syncFromSimTargets() {
    const targets = (typeof getTargets === 'function') ? getTargets() : {};
    for (const [tid, t] of Object.entries(targets)) {
        if (editorState.placedAssets[tid]) continue;
        const alliance = (t.alliance || '').toLowerCase();
        if (alliance !== 'friendly') continue;

        // Try to match to an editor asset definition
        const assetType = t.asset_type || '';
        const def = EDITOR_ASSETS[assetType];
        if (!def) continue;

        const pos = (typeof getTargetPosition === 'function') ? getTargetPosition(t) : { x: 0, y: 0 };
        editorState.placedAssets[tid] = {
            type: assetType,
            category: def.category,
            position: { x: pos.x, y: pos.y },
            rotation: t.heading || 0,
            config: _getDefaultConfig(def),
            def: def,
            name: t.name || assetType,
        };
    }
}

// ============================================================
// Palette UI
// ============================================================

function _buildEditorPalette() {
    const container = document.getElementById('war-setup-palette');
    if (!container) return;
    editorState.paletteEl = container;

    let html = '<div class="editor-palette-header">DEPLOY ASSETS</div>';

    for (const cat of EDITOR_CATEGORIES) {
        const items = Object.entries(EDITOR_ASSETS).filter(([, d]) => d.category === cat.key);
        if (items.length === 0) continue;

        html += `<div class="palette-category">`;
        html += `<div class="palette-category-title" style="color: ${cat.color};">${cat.label}</div>`;

        for (const [type, def] of items) {
            html += `<div class="palette-item" data-editor-type="${type}" onclick="warEditorSelectPalette('${type}')">`;
            html += `<span class="palette-item-icon" style="color: ${def.color};">${def.icon}</span>`;
            html += `<span class="palette-item-label">${def.label}</span>`;
            if (def.influence) {
                const desc = _influenceDesc(def);
                html += `<span class="palette-item-desc">${desc}</span>`;
            }
            html += `</div>`;
        }
        html += '</div>';
    }

    // Layout controls at bottom
    html += '<div class="editor-palette-divider"></div>';
    html += '<div class="editor-palette-actions">';
    html += '<button class="editor-btn" onclick="warEditorSaveLayout()">SAVE LAYOUT</button>';
    html += '<button class="editor-btn" onclick="warEditorLoadLayoutMenu()">LOAD LAYOUT</button>';
    html += '</div>';

    container.innerHTML = html;
}

function _influenceDesc(def) {
    const inf = def.influence;
    if (inf.type === 'fov') return `${inf.fov}\u00B0 / ${inf.range}m`;
    if (inf.type === 'radius') return `${inf.radius}m`;
    if (inf.type === 'arc') return `${inf.arc}\u00B0 / ${inf.range}m`;
    return '';
}

function warEditorSelectPalette(type) {
    const def = EDITOR_ASSETS[type];
    if (!def) return;

    if (editorState.placing && editorState.placing.type === type) {
        // Toggle off
        editorState.placing = null;
    } else {
        editorState.placing = { type, category: def.category, def };
        editorState.ghostRotation = 0;
        editorState.selectedAsset = null;
        _showConfigPanel(false);
    }
    _updatePaletteSelection();
}

function _updatePaletteSelection() {
    if (!editorState.paletteEl) return;
    const items = editorState.paletteEl.querySelectorAll('.palette-item');
    items.forEach(item => {
        const isActive = editorState.placing && item.dataset.editorType === editorState.placing.type;
        item.classList.toggle('selected', isActive);
    });
}

function _showEditorPalette(show) {
    const el = editorState.paletteEl || document.getElementById('war-setup-palette');
    if (el) el.style.display = show ? 'block' : 'none';
}

// ============================================================
// Config panel
// ============================================================

function _buildConfigPanel() {
    // Create config panel element if it doesn't exist
    let panel = document.getElementById('war-editor-config');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'war-editor-config';
        panel.style.cssText = 'position: absolute; bottom: 12px; left: 12px; width: 240px; pointer-events: auto; display: none;';
        const hud = document.getElementById('war-hud');
        if (hud) hud.appendChild(panel);
    }
    editorState.configPanelEl = panel;
}

function _showConfigPanel(show) {
    if (editorState.configPanelEl) {
        editorState.configPanelEl.style.display = show ? 'block' : 'none';
        editorState.configPanelVisible = show;
    }
}

function _updateConfigPanel() {
    if (!editorState.configPanelEl || !editorState.selectedAsset) return;
    const asset = editorState.placedAssets[editorState.selectedAsset];
    if (!asset) return;

    const def = asset.def;
    const config = asset.config || {};
    const tid = editorState.selectedAsset;

    let html = `<div class="editor-config-header" style="color: ${def.color};">${def.label.toUpperCase()}</div>`;
    html += `<div class="editor-config-row"><span class="editor-config-label">ID:</span> <span class="editor-config-value">${tid.slice(0, 8)}</span></div>`;
    html += `<div class="editor-config-row"><span class="editor-config-label">POS:</span> <span class="editor-config-value">(${asset.position.x.toFixed(1)}, ${asset.position.y.toFixed(1)})</span></div>`;
    html += `<div class="editor-config-row"><span class="editor-config-label">ROT:</span> <span class="editor-config-value">${asset.rotation || 0}\u00B0</span></div>`;

    if (def.config) {
        for (const [key, spec] of Object.entries(def.config)) {
            const val = config[key] !== undefined ? config[key] : spec.default;
            html += `<div class="editor-config-row">`;
            html += `<span class="editor-config-label">${spec.label}:</span>`;
            html += `<input type="range" class="editor-config-slider" `;
            html += `min="${spec.min}" max="${spec.max}" step="${spec.step}" value="${val}" `;
            html += `oninput="warEditorConfigChange('${tid}', '${key}', this.value)" />`;
            html += `<span class="editor-config-value" id="editor-cfg-${key}">${val}</span>`;
            html += `</div>`;
        }
    }

    html += '<div class="editor-config-actions">';
    html += `<button class="editor-btn editor-btn-danger" onclick="warEditorDeleteSelected()">DELETE</button>`;
    html += '</div>';

    editorState.configPanelEl.innerHTML = html;
}

function warEditorConfigChange(tid, key, value) {
    const asset = editorState.placedAssets[tid];
    if (!asset) return;
    asset.config[key] = parseFloat(value);
    // Update display
    const el = document.getElementById(`editor-cfg-${key}`);
    if (el) el.textContent = value;
}

function warEditorDeleteSelected() {
    if (editorState.selectedAsset) {
        _deleteAsset(editorState.selectedAsset);
    }
}

// ============================================================
// Layout panel (save/load)
// ============================================================

function _buildLayoutPanel() {
    let panel = document.getElementById('war-editor-layouts');
    if (!panel) {
        panel = document.createElement('div');
        panel.id = 'war-editor-layouts';
        panel.style.cssText = 'position: absolute; top: 60px; left: 250px; width: 240px; pointer-events: auto; display: none;';
        const hud = document.getElementById('war-hud');
        if (hud) hud.appendChild(panel);
    }
    editorState.layoutPanelEl = panel;
}

function _showLayoutPanel(show) {
    // Layout panel only shows when explicitly opened via load menu
}

function warEditorSaveLayout() {
    const name = editorState.currentLayoutName || `layout-${Date.now().toString(36)}`;

    // Build TritiumLevelFormat JSON
    const layout = _serializeLayout(name);

    fetch('/api/amy/layouts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name, data: layout }),
    }).then(res => {
        if (!res.ok) throw new Error('Save failed');
        return res.json();
    }).then(data => {
        editorState.currentLayoutName = data.name || name;
        if (typeof warAddAlert === 'function') warAddAlert(`Layout saved: ${editorState.currentLayoutName}`, 'info');
        if (typeof showNotification === 'function') showNotification('SAVED', `Layout: ${editorState.currentLayoutName}`, 'success');
    }).catch(err => {
        console.error('[WAR-EDITOR] Save failed:', err);
        if (typeof warAddAlert === 'function') warAddAlert('Layout save failed', 'hostile');
    });
}

function warEditorLoadLayoutMenu() {
    const panel = editorState.layoutPanelEl;
    if (!panel) return;

    panel.style.display = 'block';
    panel.innerHTML = '<div class="editor-config-header">LOAD LAYOUT</div><div style="color: rgba(255,255,255,0.5); font-size: 0.7rem;">Loading...</div>';

    fetch('/api/amy/layouts')
        .then(r => r.json())
        .then(data => {
            const layouts = data.layouts || [];
            if (layouts.length === 0) {
                panel.innerHTML = '<div class="editor-config-header">LOAD LAYOUT</div><div style="color: rgba(255,255,255,0.5); font-size: 0.7rem; padding: 4px 0;">No saved layouts</div>';
                panel.innerHTML += '<button class="editor-btn" onclick="warEditorCloseLayoutMenu()" style="margin-top: 8px;">CLOSE</button>';
                return;
            }
            let html = '<div class="editor-config-header">LOAD LAYOUT</div>';
            for (const name of layouts) {
                html += `<div class="palette-item" onclick="warEditorLoadLayout('${_escapeHtml(name)}')">${_escapeHtml(name)}</div>`;
            }
            html += '<button class="editor-btn" onclick="warEditorCloseLayoutMenu()" style="margin-top: 8px;">CLOSE</button>';
            panel.innerHTML = html;
        })
        .catch(() => {
            panel.innerHTML = '<div class="editor-config-header">LOAD LAYOUT</div><div style="color: #ff2a6d; font-size: 0.7rem;">Failed to load layouts</div>';
        });
}

function warEditorCloseLayoutMenu() {
    if (editorState.layoutPanelEl) {
        editorState.layoutPanelEl.style.display = 'none';
    }
}

function warEditorLoadLayout(name) {
    warEditorCloseLayoutMenu();

    fetch(`/api/amy/layouts/${encodeURIComponent(name)}`)
        .then(r => {
            if (!r.ok) throw new Error('Load failed');
            return r.json();
        })
        .then(result => {
            const layoutData = result.data;
            if (!layoutData) throw new Error('No layout data');

            // Load into simulation engine
            return fetch('/api/amy/simulation/load-layout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ data: layoutData, name: name }),
            }).then(r => r.json()).then(data => {
                editorState.currentLayoutName = name;
                if (typeof warAddAlert === 'function') {
                    warAddAlert(`Loaded layout: ${name} (${data.targets_created || 0} targets)`, 'info');
                }
                // Re-sync placed assets from sim
                setTimeout(() => _syncFromSimTargets(), 500);
            });
        })
        .catch(err => {
            console.error('[WAR-EDITOR] Load failed:', err);
            if (typeof warAddAlert === 'function') warAddAlert(`Load failed: ${name}`, 'hostile');
        });
}

// ============================================================
// Serialization
// ============================================================

function _serializeLayout(name) {
    const objects = [];

    for (const [tid, asset] of Object.entries(editorState.placedAssets)) {
        objects.push({
            id: tid,
            type: asset.type,
            name: asset.name || asset.type,
            position: {
                x: asset.position.x,
                y: 0,   // height (ground level for most)
                z: asset.position.y,  // TritiumLevelFormat uses x,z for ground plane
            },
            rotation: {
                x: 0,
                y: (asset.rotation || 0) * Math.PI / 180,
                z: 0,
            },
            scale: { x: 1, y: 1, z: 1 },
            properties: {
                ...asset.config,
                name: asset.name || asset.type,
            },
        });
    }

    return {
        id: `battlespace_${Date.now()}`,
        name: name,
        subtitle: '',
        dimensions: {
            width: warState.mapMax - warState.mapMin,
            depth: warState.mapMax - warState.mapMin,
        },
        structures: {
            housePosition: { x: 0, z: 0 },
            houseWidth: 12,
            houseDepth: 10,
            houseHeight: 6,
        },
        environment: {
            timeOfDay: 'night',
            ambientIntensity: 0.2,
        },
        amy: {
            responseProtocol: 'alert',
            escalationDelay: 30,
        },
        objects: objects,
    };
}

// ============================================================
// Utility
// ============================================================

function _escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================================
// Global exports
// ============================================================

window.warEditorEnter = warEditorEnter;
window.warEditorExit = warEditorExit;
window.warEditorDraw = warEditorDraw;
window.warEditorMouseMove = warEditorMouseMove;
window.warEditorMouseDown = warEditorMouseDown;
window.warEditorKey = warEditorKey;
window.warEditorSelectPalette = warEditorSelectPalette;
window.warEditorConfigChange = warEditorConfigChange;
window.warEditorDeleteSelected = warEditorDeleteSelected;
window.warEditorSaveLayout = warEditorSaveLayout;
window.warEditorLoadLayoutMenu = warEditorLoadLayoutMenu;
window.warEditorLoadLayout = warEditorLoadLayout;
window.warEditorCloseLayoutMenu = warEditorCloseLayoutMenu;
window.editorState = editorState;
window.EDITOR_ASSETS = EDITOR_ASSETS;
