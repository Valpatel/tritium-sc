// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Mesh Radio Map Layer
 *
 * Dedicated draw layer for Meshtastic mesh radio nodes on the tactical map.
 * Draws protocol-specific icons (M=Meshtastic, C=MeshCore, W=Web),
 * dotted links between communicating nodes, and LoRa coverage circles.
 *
 * Fetches live node data from /api/meshtastic/nodes?has_gps=true with
 * 30-second auto-refresh. Sub-layers: nodes, links, coverage.
 *
 * Exports: meshDrawNodes, meshGetIconForProtocol, meshShouldDrawLink,
 *          meshState, meshFetchNodes, meshGetNodeCount,
 *          MESH_PROTOCOL_ICONS, MESH_NODE_COLOR, MESH_LINK_COLOR,
 *          MESH_LINK_RANGE, MESH_COVERAGE_RADIUS
 */

// ============================================================
// Constants
// ============================================================

const MESH_PROTOCOL_ICONS = {
    meshtastic: 'M',
    meshcore: 'C',
    web: 'W',
};

const MESH_NODE_COLOR = '#00d4aa';      // teal-green for mesh nodes
const MESH_LINK_COLOR = 'rgba(0, 212, 170, 0.25)';
const MESH_LINK_RANGE = 500;             // meters -- max link draw distance
const MESH_COVERAGE_RADIUS = 10000;      // meters -- ~10km LoRa range per node

// Link quality color scale (SNR-based)
const MESH_LINK_QUALITY = {
    excellent: 'rgba(5, 255, 161, 0.5)',   // green -- SNR > 5
    good:      'rgba(0, 212, 170, 0.35)',  // teal -- SNR 0..5
    fair:      'rgba(252, 238, 10, 0.3)',  // yellow -- SNR -5..0
    poor:      'rgba(255, 42, 109, 0.25)', // magenta -- SNR < -5
};

// ============================================================
// Module state
// ============================================================

const meshState = {
    visible: true,
    showNodes: true,
    showLinks: true,
    showCoverage: false,
    opacity: 1.0,
    // Fetched API nodes (GPS-enabled Meshtastic nodes)
    apiNodes: [],
    apiNodeCount: 0,
    apiTotalCount: 0,
    lastFetch: 0,
    fetchInterval: null,
};

// ============================================================
// API fetch
// ============================================================

/**
 * Fetch Meshtastic nodes with GPS from the API.
 * Updates meshState.apiNodes and meshState.apiNodeCount.
 * @returns {Promise<void>}
 */
function meshFetchNodes() {
    return fetch('/api/meshtastic/nodes?has_gps=true&sort_by=snr')
        .then(function(r) { return r.ok ? r.json() : { nodes: [], count: 0, total: 0 }; })
        .then(function(data) {
            meshState.apiNodes = data.nodes || [];
            meshState.apiNodeCount = data.count || 0;
            meshState.apiTotalCount = data.total || 0;
            meshState.lastFetch = Date.now();
        })
        .catch(function() {
            // Silently fail -- API may not be available
        });
}

/**
 * Start 30-second auto-refresh of mesh node data.
 */
function meshStartAutoRefresh() {
    if (meshState.fetchInterval) return;
    meshFetchNodes();
    meshState.fetchInterval = setInterval(meshFetchNodes, 30000);
}

/**
 * Stop auto-refresh.
 */
function meshStopAutoRefresh() {
    if (meshState.fetchInterval) {
        clearInterval(meshState.fetchInterval);
        meshState.fetchInterval = null;
    }
}

/**
 * Get current GPS node count for display in layer toggle label.
 * @returns {number}
 */
function meshGetNodeCount() {
    return meshState.apiNodeCount;
}

// ============================================================
// Icon resolution
// ============================================================

/**
 * Return the single-character icon for a mesh protocol.
 * Falls back to '?' for unknown protocols.
 * @param {string} protocol
 * @returns {string}
 */
function meshGetIconForProtocol(protocol) {
    return MESH_PROTOCOL_ICONS[protocol] || '?';
}

// ============================================================
// Link distance check
// ============================================================

/**
 * Check if two nodes are within range to draw a link.
 * @param {{ x: number, y: number }} a
 * @param {{ x: number, y: number }} b
 * @param {number} range
 * @returns {boolean}
 */
function meshShouldDrawLink(a, b, range) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return (dx * dx + dy * dy) <= range * range;
}

// ============================================================
// Link quality
// ============================================================

/**
 * Get link color based on average SNR of two nodes.
 * @param {object} a - node with optional snr field
 * @param {object} b - node with optional snr field
 * @returns {string} CSS color
 */
function meshGetLinkColor(a, b) {
    const snrA = (a.metadata && a.metadata.snr) || a.snr;
    const snrB = (b.metadata && b.metadata.snr) || b.snr;
    if (snrA === undefined && snrB === undefined) return MESH_LINK_COLOR;
    const avgSnr = (snrA !== undefined && snrB !== undefined)
        ? (snrA + snrB) / 2
        : (snrA !== undefined ? snrA : snrB);
    if (avgSnr > 5) return MESH_LINK_QUALITY.excellent;
    if (avgSnr > 0) return MESH_LINK_QUALITY.good;
    if (avgSnr > -5) return MESH_LINK_QUALITY.fair;
    return MESH_LINK_QUALITY.poor;
}

/**
 * Get node icon radius based on SNR quality.
 * Better SNR = larger icon (6..12px range).
 * @param {object} node
 * @returns {number} radius in pixels
 */
function meshGetNodeRadius(node) {
    const snr = (node.metadata && node.metadata.snr) || node.snr;
    if (snr === undefined) return 8;
    // Clamp SNR to -20..+20 range, map to 6..12
    const clamped = Math.max(-20, Math.min(20, snr));
    return 6 + ((clamped + 20) / 40) * 6;
}

// ============================================================
// Draw functions
// ============================================================

/**
 * Draw LoRa coverage circles for each mesh node.
 * Large translucent circles (~10km radius) showing estimated range.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen
 * @param {Array} meshTargets
 * @param {number} metersToPixels - conversion factor for coverage radius
 */
function meshDrawCoverage(ctx, worldToScreen, meshTargets, metersToPixels) {
    if (!meshState.showCoverage || !meshTargets || meshTargets.length === 0) return;

    ctx.save();
    ctx.globalAlpha = 0.06 * meshState.opacity;

    const radiusPx = MESH_COVERAGE_RADIUS * (metersToPixels || 0.01);

    for (let i = 0; i < meshTargets.length; i++) {
        const node = meshTargets[i];
        const sp = worldToScreen(node.x, node.y);

        // Gradient fill for coverage circle
        const gradient = ctx.createRadialGradient(sp.x, sp.y, 0, sp.x, sp.y, radiusPx);
        gradient.addColorStop(0, 'rgba(0, 212, 170, 0.4)');
        gradient.addColorStop(0.5, 'rgba(0, 212, 170, 0.15)');
        gradient.addColorStop(1, 'rgba(0, 212, 170, 0)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radiusPx, 0, Math.PI * 2);
        ctx.fill();

        // Dashed outline
        ctx.strokeStyle = 'rgba(0, 212, 170, 0.15)';
        ctx.lineWidth = 1;
        ctx.setLineDash([8, 12]);
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radiusPx, 0, Math.PI * 2);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    ctx.restore();
}

/**
 * Draw links between mesh nodes that have communicated recently.
 * Lines colored by link quality (SNR-based).
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen
 * @param {Array} meshTargets
 */
function meshDrawLinks(ctx, worldToScreen, meshTargets) {
    if (!meshState.showLinks || !meshTargets || meshTargets.length === 0) return;

    ctx.save();
    ctx.globalAlpha = meshState.opacity;
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 6]);

    for (let i = 0; i < meshTargets.length; i++) {
        for (let j = i + 1; j < meshTargets.length; j++) {
            const a = meshTargets[i];
            const b = meshTargets[j];
            if (meshShouldDrawLink(a, b, MESH_LINK_RANGE)) {
                ctx.strokeStyle = meshGetLinkColor(a, b);
                const sa = worldToScreen(a.x, a.y);
                const sb = worldToScreen(b.x, b.y);
                ctx.beginPath();
                ctx.moveTo(sa.x, sa.y);
                ctx.lineTo(sb.x, sb.y);
                ctx.stroke();
            }
        }
    }

    ctx.setLineDash([]);
    ctx.restore();
}

/**
 * Draw mesh radio nodes on the tactical map canvas.
 * Green radio icons with node name labels, sized by SNR quality.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen - (wx, wy) => { x, y }
 * @param {Array} meshTargets - array of mesh_radio targets with
 *   { target_id, x, y, asset_type, metadata: { mesh_protocol, snr }, name }
 * @param {boolean} visible - whether the master layer is visible
 * @param {number} [metersToPixels] - optional conversion for coverage circles
 */
function meshDrawNodes(ctx, worldToScreen, meshTargets, visible, metersToPixels) {
    if (!visible || !meshTargets || meshTargets.length === 0) return;

    // Draw coverage circles first (behind everything)
    meshDrawCoverage(ctx, worldToScreen, meshTargets, metersToPixels);

    // Draw links
    meshDrawLinks(ctx, worldToScreen, meshTargets);

    // Draw nodes
    if (!meshState.showNodes) return;

    ctx.save();
    ctx.globalAlpha = meshState.opacity;

    for (let i = 0; i < meshTargets.length; i++) {
        const node = meshTargets[i];
        const protocol = (node.metadata && node.metadata.mesh_protocol) || 'meshtastic';
        const icon = meshGetIconForProtocol(protocol);
        const sp = worldToScreen(node.x, node.y);
        const radius = meshGetNodeRadius(node);

        // Outer glow circle
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.globalAlpha = 0.2 * meshState.opacity;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius + 4, 0, Math.PI * 2);
        ctx.fill();

        // Main circle
        ctx.globalAlpha = 0.4 * meshState.opacity;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.fill();

        // Inner icon letter
        ctx.globalAlpha = 1.0 * meshState.opacity;
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.font = 'bold ' + Math.max(8, Math.round(radius * 1.1)) + 'px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(icon, sp.x, sp.y);

        // Node name label (below icon)
        const name = node.name || (node.metadata && node.metadata.short_name) || '';
        if (name) {
            ctx.globalAlpha = 0.7 * meshState.opacity;
            ctx.fillStyle = MESH_NODE_COLOR;
            ctx.font = '9px "JetBrains Mono", monospace';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'top';
            ctx.fillText(name, sp.x, sp.y + radius + 3);
        }
    }

    ctx.restore();
}

// ============================================================
// Exports (CommonJS for Node.js test runner, also global for browser)
// ============================================================

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        MESH_PROTOCOL_ICONS,
        MESH_NODE_COLOR,
        MESH_LINK_COLOR,
        MESH_LINK_RANGE,
        MESH_COVERAGE_RADIUS,
        MESH_LINK_QUALITY,
        meshDrawNodes,
        meshDrawCoverage,
        meshDrawLinks,
        meshGetIconForProtocol,
        meshShouldDrawLink,
        meshGetLinkColor,
        meshGetNodeRadius,
        meshGetNodeCount,
        meshFetchNodes,
        meshStartAutoRefresh,
        meshStopAutoRefresh,
        meshState,
    };
}
