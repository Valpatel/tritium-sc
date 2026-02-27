/**
 * TRITIUM Command Center -- Mesh Radio Map Layer
 *
 * Dedicated draw layer for mesh radio nodes on the tactical map.
 * Draws protocol-specific icons (M=Meshtastic, C=MeshCore, W=Web)
 * and dotted links between nearby nodes.
 *
 * Exports: meshDrawNodes, meshGetIconForProtocol, meshShouldDrawLink,
 *          meshState, MESH_PROTOCOL_ICONS, MESH_NODE_COLOR, MESH_LINK_COLOR,
 *          MESH_LINK_RANGE
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
const MESH_LINK_RANGE = 500;             // meters — max link draw distance

// ============================================================
// Module state
// ============================================================

const meshState = {
    visible: true,
};

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
// Draw function
// ============================================================

/**
 * Draw mesh radio nodes and links on the tactical map canvas.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {function} worldToScreen - (wx, wy) => { x, y }
 * @param {Array} meshTargets - array of mesh_radio targets with
 *   { target_id, x, y, asset_type, metadata: { mesh_protocol } }
 * @param {boolean} visible - whether the layer is visible
 */
function meshDrawNodes(ctx, worldToScreen, meshTargets, visible) {
    if (!visible || !meshTargets || meshTargets.length === 0) return;

    ctx.save();

    // Draw links between nearby nodes (dotted lines, dim)
    ctx.strokeStyle = MESH_LINK_COLOR;
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 6]);

    for (let i = 0; i < meshTargets.length; i++) {
        for (let j = i + 1; j < meshTargets.length; j++) {
            const a = meshTargets[i];
            const b = meshTargets[j];
            if (meshShouldDrawLink(a, b, MESH_LINK_RANGE)) {
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

    // Draw each node
    for (let i = 0; i < meshTargets.length; i++) {
        const node = meshTargets[i];
        const protocol = (node.metadata && node.metadata.mesh_protocol) || 'web';
        const icon = meshGetIconForProtocol(protocol);
        const sp = worldToScreen(node.x, node.y);

        // Outer circle
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.globalAlpha = 0.3;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, 8, 0, Math.PI * 2);
        ctx.fill();

        // Inner icon letter
        ctx.globalAlpha = 1.0;
        ctx.fillStyle = MESH_NODE_COLOR;
        ctx.font = 'bold 10px "JetBrains Mono", monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(icon, sp.x, sp.y);
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
        meshDrawNodes,
        meshGetIconForProtocol,
        meshShouldDrawLink,
        meshState,
    };
}
