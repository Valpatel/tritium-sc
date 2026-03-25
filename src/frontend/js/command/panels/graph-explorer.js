// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Graph Explorer Panel — force-directed entity relationship visualization
// Canvas 2D rendering, no external libraries. Nodes colored by entity type,
// edges labeled by relationship. Click to select, double-click to expand,
// drag to rearrange, scroll to zoom, right-drag to pan.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NODE_COLORS = {
    device:  '#00f0ff',  // cyan
    person:  '#05ffa1',  // green
    vehicle: '#ff2a6d',  // magenta
    mesh:    '#fcee0a',  // yellow
    unknown: '#888888',
};

const EDGE_CONFIDENCE_COLORS = [
    { min: 0.0, max: 0.3, color: '#555555' },
    { min: 0.3, max: 0.6, color: '#888888' },
    { min: 0.6, max: 0.8, color: '#bbbbbb' },
    { min: 0.8, max: 1.0, color: '#00f0ff' },
];

const PHYSICS = {
    repulsion:     5000,    // Coulomb constant (node-node repulsion)
    springK:       0.005,   // Hooke spring constant (edge attraction)
    springLength:  120,     // Rest length of edge springs
    gravity:       0.02,    // Pull toward center
    friction:      0.85,    // Velocity damping per frame
    maxVelocity:   8,       // Clamp velocity magnitude
    stabilizeAt:   0.05,    // Total kinetic energy below which we pause sim
};

const NODE_RADIUS = 18;
const SELECTED_RING = 4;
const LABEL_FONT = '11px monospace';
const EDGE_LABEL_FONT = '9px monospace';
const LEGEND_FONT = '10px monospace';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------


function edgeConfidenceColor(confidence) {
    const c = Math.max(0, Math.min(1, confidence || 0));
    for (const band of EDGE_CONFIDENCE_COLORS) {
        if (c >= band.min && c < band.max) return band.color;
    }
    return EDGE_CONFIDENCE_COLORS[EDGE_CONFIDENCE_COLORS.length - 1].color;
}

function dist(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
}

function clamp(v, min, max) {
    return Math.max(min, Math.min(max, v));
}

// ---------------------------------------------------------------------------
// Graph data model
// ---------------------------------------------------------------------------

class GraphNode {
    constructor(id, label, entityType, data) {
        this.id = id;
        this.label = label || id;
        this.entityType = entityType || 'unknown';
        this.data = data || {};
        // Physics
        this.x = 0;
        this.y = 0;
        this.vx = 0;
        this.vy = 0;
        this.pinned = false;
    }
}

class GraphEdge {
    constructor(sourceId, targetId, label, confidence) {
        this.sourceId = sourceId;
        this.targetId = targetId;
        this.label = label || '';
        this.confidence = confidence ?? 0.5;
    }
}

// ---------------------------------------------------------------------------
// Force-directed graph simulation + renderer
// ---------------------------------------------------------------------------

class ForceGraph {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.nodes = new Map();   // id -> GraphNode
        this.edges = [];          // GraphEdge[]
        this.expandedIds = new Set();

        // View transform (pan + zoom)
        this.offsetX = 0;
        this.offsetY = 0;
        this.zoom = 1;

        // Interaction state
        this.selectedId = null;
        this.hoveredId = null;
        this.dragNode = null;
        this.isPanning = false;
        this.panStart = null;
        this.panOffsetStart = null;
        this.running = false;
        this.frameId = null;
        this.iterCount = 0;

        // Callbacks
        this.onNodeSelect = null;    // (node) => void
        this.onNodeExpand = null;    // (node) => void

        this._bindEvents();
    }

    // -- Data manipulation --

    addNode(id, label, entityType, data) {
        if (this.nodes.has(id)) return this.nodes.get(id);
        const node = new GraphNode(id, label, entityType, data);
        // Random initial position within visible area
        const spread = 200;
        node.x = (Math.random() - 0.5) * spread;
        node.y = (Math.random() - 0.5) * spread;
        this.nodes.set(id, node);
        this.iterCount = 0; // restart stabilization
        return node;
    }

    addEdge(sourceId, targetId, label, confidence) {
        // Avoid duplicates
        const exists = this.edges.some(
            e => (e.sourceId === sourceId && e.targetId === targetId) ||
                 (e.sourceId === targetId && e.targetId === sourceId && e.label === label)
        );
        if (exists) return;
        this.edges.push(new GraphEdge(sourceId, targetId, label, confidence));
        this.iterCount = 0;
    }

    clear() {
        this.nodes.clear();
        this.edges.length = 0;
        this.expandedIds.clear();
        this.selectedId = null;
        this.hoveredId = null;
        this.iterCount = 0;
    }

    // -- Physics --

    step() {
        const nodes = [...this.nodes.values()];
        const n = nodes.length;
        if (n === 0) return;

        // Reset forces
        for (const node of nodes) {
            node.fx = 0;
            node.fy = 0;
        }

        // Node-node repulsion (Coulomb)
        for (let i = 0; i < n; i++) {
            for (let j = i + 1; j < n; j++) {
                const a = nodes[i];
                const b = nodes[j];
                let dx = a.x - b.x;
                let dy = a.y - b.y;
                let d = Math.sqrt(dx * dx + dy * dy) || 1;
                if (d < 1) d = 1;
                const force = PHYSICS.repulsion / (d * d);
                const fx = (dx / d) * force;
                const fy = (dy / d) * force;
                a.fx += fx;
                a.fy += fy;
                b.fx -= fx;
                b.fy -= fy;
            }
        }

        // Edge spring attraction (Hooke)
        for (const edge of this.edges) {
            const a = this.nodes.get(edge.sourceId);
            const b = this.nodes.get(edge.targetId);
            if (!a || !b) continue;
            let dx = b.x - a.x;
            let dy = b.y - a.y;
            let d = Math.sqrt(dx * dx + dy * dy) || 1;
            const displacement = d - PHYSICS.springLength;
            const force = PHYSICS.springK * displacement;
            const fx = (dx / d) * force;
            const fy = (dy / d) * force;
            a.fx += fx;
            a.fy += fy;
            b.fx -= fx;
            b.fy -= fy;
        }

        // Center gravity
        for (const node of nodes) {
            node.fx -= node.x * PHYSICS.gravity;
            node.fy -= node.y * PHYSICS.gravity;
        }

        // Integrate velocity and position
        let totalKE = 0;
        for (const node of nodes) {
            if (node.pinned) {
                node.vx = 0;
                node.vy = 0;
                continue;
            }
            node.vx = (node.vx + node.fx) * PHYSICS.friction;
            node.vy = (node.vy + node.fy) * PHYSICS.friction;
            // Clamp velocity
            const speed = Math.sqrt(node.vx * node.vx + node.vy * node.vy);
            if (speed > PHYSICS.maxVelocity) {
                node.vx = (node.vx / speed) * PHYSICS.maxVelocity;
                node.vy = (node.vy / speed) * PHYSICS.maxVelocity;
            }
            node.x += node.vx;
            node.y += node.vy;
            totalKE += node.vx * node.vx + node.vy * node.vy;
        }

        this.iterCount++;
        return totalKE;
    }

    // -- Rendering --

    draw() {
        const { ctx, canvas } = this;
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);
        ctx.fillStyle = '#0a0a0f';
        ctx.fillRect(0, 0, w, h);

        ctx.save();
        ctx.translate(w / 2 + this.offsetX, h / 2 + this.offsetY);
        ctx.scale(this.zoom, this.zoom);

        // Draw edges
        for (const edge of this.edges) {
            const a = this.nodes.get(edge.sourceId);
            const b = this.nodes.get(edge.targetId);
            if (!a || !b) continue;
            this._drawEdge(ctx, a, b, edge);
        }

        // Draw nodes
        for (const node of this.nodes.values()) {
            this._drawNode(ctx, node);
        }

        ctx.restore();

        // Draw legend (fixed position, not affected by zoom/pan)
        this._drawLegend(ctx, w, h);
    }

    _drawNode(ctx, node) {
        const r = NODE_RADIUS;
        const color = NODE_COLORS[node.entityType] || NODE_COLORS.unknown;
        const isSelected = node.id === this.selectedId;
        const isHovered = node.id === this.hoveredId;

        // Glow for selected
        if (isSelected) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, r + SELECTED_RING, 0, Math.PI * 2);
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.shadowColor = color;
            ctx.shadowBlur = 12;
            ctx.stroke();
            ctx.shadowBlur = 0;
        }

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        ctx.fillStyle = isHovered ? color : _darken(color, 0.4);
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = isSelected ? 2.5 : 1.5;
        ctx.stroke();

        // Expanded indicator (small diamond)
        if (this.expandedIds.has(node.id)) {
            ctx.beginPath();
            ctx.moveTo(node.x, node.y - r - 6);
            ctx.lineTo(node.x + 4, node.y - r - 2);
            ctx.lineTo(node.x, node.y - r + 2);
            ctx.lineTo(node.x - 4, node.y - r - 2);
            ctx.closePath();
            ctx.fillStyle = color;
            ctx.fill();
        }

        // Label below node
        ctx.font = LABEL_FONT;
        ctx.fillStyle = '#cccccc';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        const label = node.label.length > 16 ? node.label.slice(0, 14) + '..' : node.label;
        ctx.fillText(label, node.x, node.y + r + 4);
    }

    _drawEdge(ctx, a, b, edge) {
        const color = edgeConfidenceColor(edge.confidence);

        // Line thickness varies with confidence
        const lineWidth = 0.5 + edge.confidence * 2.0;

        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.globalAlpha = 0.4 + edge.confidence * 0.4;
        ctx.stroke();
        ctx.globalAlpha = 1.0;

        // Arrowhead (directional edge indicator)
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.sqrt(dx * dx + dy * dy) || 1;
        const nx = dx / len;
        const ny = dy / len;
        const arrowX = b.x - nx * NODE_RADIUS;
        const arrowY = b.y - ny * NODE_RADIUS;
        const arrowSize = 6 + edge.confidence * 3;
        ctx.beginPath();
        ctx.moveTo(arrowX, arrowY);
        ctx.lineTo(
            arrowX - arrowSize * nx + arrowSize * 0.4 * ny,
            arrowY - arrowSize * ny - arrowSize * 0.4 * nx,
        );
        ctx.lineTo(
            arrowX - arrowSize * nx - arrowSize * 0.4 * ny,
            arrowY - arrowSize * ny + arrowSize * 0.4 * nx,
        );
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.7;
        ctx.fill();
        ctx.globalAlpha = 1.0;

        // Edge label at midpoint: relationship type + confidence score
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;

        // Offset label perpendicular to edge to avoid overlap with line
        const perpX = -ny * 10;
        const perpY = nx * 10;
        const labelX = mx + perpX;
        const labelY = my + perpY;

        // Build label text: TYPE (NN%)
        const confPct = Math.round(edge.confidence * 100);
        let labelText = '';
        if (edge.label) {
            // Format relationship type: CARRIES, DETECTED_WITH, etc.
            const relType = edge.label.toUpperCase().replace(/[_ ]/g, '_');
            labelText = `${relType} (${confPct}%)`;
        } else {
            labelText = `${confPct}%`;
        }

        ctx.font = EDGE_LABEL_FONT;
        // Background pill for readability
        const tw = ctx.measureText(labelText).width + 8;
        const th = 14;
        ctx.fillStyle = '#0a0a0f';
        ctx.globalAlpha = 0.85;
        // Rounded rect background
        const rx = labelX - tw / 2;
        const ry = labelY - th / 2;
        const radius = 3;
        ctx.beginPath();
        ctx.moveTo(rx + radius, ry);
        ctx.lineTo(rx + tw - radius, ry);
        ctx.quadraticCurveTo(rx + tw, ry, rx + tw, ry + radius);
        ctx.lineTo(rx + tw, ry + th - radius);
        ctx.quadraticCurveTo(rx + tw, ry + th, rx + tw - radius, ry + th);
        ctx.lineTo(rx + radius, ry + th);
        ctx.quadraticCurveTo(rx, ry + th, rx, ry + th - radius);
        ctx.lineTo(rx, ry + radius);
        ctx.quadraticCurveTo(rx, ry, rx + radius, ry);
        ctx.closePath();
        ctx.fill();

        // Border matching edge color
        ctx.strokeStyle = color;
        ctx.lineWidth = 0.5;
        ctx.globalAlpha = 0.5;
        ctx.stroke();

        // Label text
        ctx.globalAlpha = 1.0;
        ctx.fillStyle = color;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(labelText, labelX, labelY);
    }

    _drawLegend(ctx, w, h) {
        const x0 = 8;
        const lineH = 16;

        // Collect unique relationship types from edges
        const relTypes = new Set();
        for (const edge of this.edges) {
            if (edge.label) relTypes.add(edge.label.toUpperCase().replace(/[_ ]/g, '_'));
        }

        // Calculate legend height
        const entityCount = Object.keys(NODE_COLORS).length - 1; // minus 'unknown'
        const relCount = relTypes.size;
        const confBands = EDGE_CONFIDENCE_COLORS.length;
        const legendH = 24 + entityCount * lineH + (relCount > 0 ? 20 + relCount * lineH : 0) + 20 + confBands * lineH + 8;
        const y0 = h - legendH;

        ctx.font = LEGEND_FONT;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';

        // Background
        ctx.fillStyle = '#0a0a0f';
        ctx.globalAlpha = 0.8;
        ctx.fillRect(x0, y0 - 4, 150, legendH + 4);
        ctx.globalAlpha = 1.0;

        // -- Entity types --
        ctx.fillStyle = '#666';
        ctx.fillText('ENTITY TYPES', x0 + 4, y0 + 4);

        let row = 0;
        for (const [type, color] of Object.entries(NODE_COLORS)) {
            if (type === 'unknown') continue;
            const y = y0 + 18 + row * lineH;
            ctx.beginPath();
            ctx.arc(x0 + 12, y, 5, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();
            ctx.fillStyle = '#aaa';
            ctx.fillText(type.toUpperCase(), x0 + 22, y);
            row++;
        }

        let yOffset = y0 + 18 + row * lineH;

        // -- Relationship types (dynamic from current graph) --
        if (relTypes.size > 0) {
            yOffset += 6;
            ctx.fillStyle = '#666';
            ctx.fillText('RELATIONSHIPS', x0 + 4, yOffset);
            yOffset += 14;

            const relColors = ['#00f0ff', '#ff2a6d', '#05ffa1', '#fcee0a', '#bb88ff'];
            let ri = 0;
            for (const relType of relTypes) {
                const rc = relColors[ri % relColors.length];
                // Draw line sample
                ctx.beginPath();
                ctx.moveTo(x0 + 4, yOffset);
                ctx.lineTo(x0 + 18, yOffset);
                ctx.strokeStyle = rc;
                ctx.lineWidth = 1.5;
                ctx.stroke();
                // Arrow head
                ctx.beginPath();
                ctx.moveTo(x0 + 18, yOffset);
                ctx.lineTo(x0 + 14, yOffset - 3);
                ctx.lineTo(x0 + 14, yOffset + 3);
                ctx.closePath();
                ctx.fillStyle = rc;
                ctx.fill();
                // Label
                ctx.fillStyle = '#aaa';
                ctx.fillText(relType, x0 + 22, yOffset);
                yOffset += lineH;
                ri++;
            }
        }

        // -- Confidence bands --
        yOffset += 6;
        ctx.fillStyle = '#666';
        ctx.fillText('CONFIDENCE', x0 + 4, yOffset);
        yOffset += 14;

        for (const band of EDGE_CONFIDENCE_COLORS) {
            ctx.beginPath();
            ctx.moveTo(x0 + 4, yOffset);
            ctx.lineTo(x0 + 18, yOffset);
            ctx.strokeStyle = band.color;
            ctx.lineWidth = 2;
            ctx.stroke();
            const lo = Math.round(band.min * 100);
            const hi = Math.round(band.max * 100);
            ctx.fillStyle = '#aaa';
            ctx.fillText(`${lo}-${hi}%`, x0 + 22, yOffset);
            yOffset += lineH;
        }
    }

    // -- Coordinate transforms --

    screenToWorld(sx, sy) {
        const w = this.canvas.width;
        const h = this.canvas.height;
        return {
            x: (sx - w / 2 - this.offsetX) / this.zoom,
            y: (sy - h / 2 - this.offsetY) / this.zoom,
        };
    }

    nodeAtScreen(sx, sy) {
        const world = this.screenToWorld(sx, sy);
        for (const node of this.nodes.values()) {
            if (dist(world, node) <= NODE_RADIUS) return node;
        }
        return null;
    }

    // -- Event handling --

    _bindEvents() {
        let lastClick = 0;
        let lastClickNode = null;

        this.canvas.addEventListener('mousedown', (e) => {
            e.preventDefault();
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;
            const node = this.nodeAtScreen(sx, sy);

            if (e.button === 0 && node) {
                // Check double-click
                const now = Date.now();
                if (lastClickNode === node && now - lastClick < 350) {
                    // Double-click: expand
                    if (this.onNodeExpand) this.onNodeExpand(node);
                    lastClick = 0;
                    lastClickNode = null;
                    return;
                }
                lastClick = now;
                lastClickNode = node;

                // Start drag
                this.dragNode = node;
                node.pinned = true;
                this.selectedId = node.id;
                if (this.onNodeSelect) this.onNodeSelect(node);
            } else {
                // Pan
                this.isPanning = true;
                this.panStart = { x: e.clientX, y: e.clientY };
                this.panOffsetStart = { x: this.offsetX, y: this.offsetY };
                if (!node) {
                    this.selectedId = null;
                    if (this.onNodeSelect) this.onNodeSelect(null);
                }
            }
        });

        this.canvas.addEventListener('mousemove', (e) => {
            const rect = this.canvas.getBoundingClientRect();
            const sx = e.clientX - rect.left;
            const sy = e.clientY - rect.top;

            if (this.dragNode) {
                const world = this.screenToWorld(sx, sy);
                this.dragNode.x = world.x;
                this.dragNode.y = world.y;
                this.iterCount = 0; // keep simulation active while dragging
            } else if (this.isPanning) {
                this.offsetX = this.panOffsetStart.x + (e.clientX - this.panStart.x);
                this.offsetY = this.panOffsetStart.y + (e.clientY - this.panStart.y);
            } else {
                const node = this.nodeAtScreen(sx, sy);
                this.hoveredId = node ? node.id : null;
                this.canvas.style.cursor = node ? 'pointer' : 'default';
            }
        });

        const mouseUp = () => {
            if (this.dragNode) {
                this.dragNode.pinned = false;
                this.dragNode = null;
            }
            this.isPanning = false;
            this.panStart = null;
        };
        this.canvas.addEventListener('mouseup', mouseUp);
        document.addEventListener('mouseup', mouseUp);

        this.canvas.addEventListener('wheel', (e) => {
            e.preventDefault();
            const factor = e.deltaY < 0 ? 1.1 : 0.9;
            this.zoom = clamp(this.zoom * factor, 0.15, 5);
        }, { passive: false });
    }

    // -- Animation loop --

    start() {
        if (this.running) return;
        this.running = true;
        this.iterCount = 0;
        const tick = () => {
            if (!this.running) return;
            // Resize canvas to container
            const parent = this.canvas.parentElement;
            if (parent) {
                const dpr = 1; // keep 1:1 for perf
                const pw = parent.clientWidth;
                const ph = parent.clientHeight;
                if (this.canvas.width !== pw || this.canvas.height !== ph) {
                    this.canvas.width = pw;
                    this.canvas.height = ph;
                }
            }
            // Run physics (skip if stabilized and no drag)
            if (this.nodes.size > 0) {
                const ke = this.step();
                if (ke !== undefined && ke < PHYSICS.stabilizeAt && this.iterCount > 100 && !this.dragNode) {
                    // Stabilized -- still draw but skip physics next frame
                } else {
                    this.iterCount = Math.min(this.iterCount, 200);
                }
            }
            this.draw();
            this.frameId = requestAnimationFrame(tick);
        };
        this.frameId = requestAnimationFrame(tick);
    }

    stop() {
        this.running = false;
        if (this.frameId) {
            cancelAnimationFrame(this.frameId);
            this.frameId = null;
        }
    }

    // -- Resize callback --

    resize() {
        // Canvas resize handled in tick loop
    }
}

// ---------------------------------------------------------------------------
// Color utility
// ---------------------------------------------------------------------------

function _darken(hex, amount) {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    const f = 1 - amount;
    return `rgb(${Math.round(r * f)}, ${Math.round(g * f)}, ${Math.round(b * f)})`;
}

// ---------------------------------------------------------------------------
// Panel definition
// ---------------------------------------------------------------------------

export const GraphExplorerPanelDef = {
    id: 'graph-explorer',
    title: 'GRAPH EXPLORER',
    defaultPosition: { x: 40, y: 40 },
    defaultSize: { w: 720, h: 520 },

    _graph: null,
    _propsEl: null,
    _searchInput: null,
    _statusEl: null,

    create(panel) {
        const el = document.createElement('div');
        el.className = 'graph-explorer-root';
        el.innerHTML = `
            <div class="ge-toolbar">
                <input type="text" class="ge-search-input" data-bind="ge-search"
                       placeholder="Entity ID or name..." spellcheck="false">
                <button class="ge-btn mono" data-action="ge-search-go">SEARCH</button>
                <button class="ge-btn mono" data-action="ge-show-all">ALL CORRELATIONS</button>
                <button class="ge-btn mono" data-action="ge-clear">CLEAR</button>
                <span class="ge-status mono" data-bind="ge-status">0 nodes</span>
            </div>
            <div class="ge-body">
                <div class="ge-canvas-wrap">
                    <canvas class="ge-canvas"></canvas>
                </div>
                <div class="ge-props-panel" data-bind="ge-props">
                    <div class="ge-props-title mono">PROPERTIES</div>
                    <div class="ge-props-content" data-bind="ge-props-content">
                        <span class="ge-props-empty">Click a node to inspect</span>
                    </div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const canvasEl = bodyEl.querySelector('.ge-canvas');
        const propsContent = bodyEl.querySelector('[data-bind="ge-props-content"]');
        const searchInput = bodyEl.querySelector('[data-bind="ge-search"]');
        const statusEl = bodyEl.querySelector('[data-bind="ge-status"]');
        const searchBtn = bodyEl.querySelector('[data-action="ge-search-go"]');
        const showAllBtn = bodyEl.querySelector('[data-action="ge-show-all"]');
        const clearBtn = bodyEl.querySelector('[data-action="ge-clear"]');

        const graph = new ForceGraph(canvasEl);
        this._graph = graph;
        this._propsEl = propsContent;
        this._searchInput = searchInput;
        this._statusEl = statusEl;

        // Node select -> show properties
        graph.onNodeSelect = (node) => {
            if (!node) {
                propsContent.innerHTML = '<span class="ge-props-empty">Click a node to inspect</span>';
                return;
            }
            this._renderProps(propsContent, node);
        };

        // Node expand -> fetch connected entities
        graph.onNodeExpand = async (node) => {
            if (graph.expandedIds.has(node.id)) return;
            graph.expandedIds.add(node.id);
            await this._fetchAndExpand(graph, node);
            this._updateStatus();
        };

        // Search
        const doSearch = async () => {
            const query = searchInput.value.trim();
            if (!query) return;
            await this._searchAndSeed(graph, query);
            this._updateStatus();
        };

        searchBtn.addEventListener('click', doSearch);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doSearch();
        });

        // Show all correlations
        showAllBtn.addEventListener('click', async () => {
            await this._loadAllCorrelations(graph);
            this._updateStatus();
        });

        // Clear
        clearBtn.addEventListener('click', () => {
            graph.clear();
            propsContent.innerHTML = '<span class="ge-props-empty">Click a node to inspect</span>';
            this._updateStatus();
        });

        graph.start();
        this._updateStatus();
    },

    unmount(bodyEl) {
        if (this._graph) {
            this._graph.stop();
            this._graph = null;
        }
    },

    onResize(w, h) {
        // Canvas resize handled in animation loop
    },

    // -- Internal helpers --

    _updateStatus() {
        if (!this._statusEl || !this._graph) return;
        const nn = this._graph.nodes.size;
        const ne = this._graph.edges.length;
        this._statusEl.textContent = `${nn} node${nn !== 1 ? 's' : ''}, ${ne} edge${ne !== 1 ? 's' : ''}`;
    },

    _renderProps(el, node) {
        const color = NODE_COLORS[node.entityType] || NODE_COLORS.unknown;
        const data = node.data || {};
        let propsHtml = '';
        for (const [k, v] of Object.entries(data)) {
            if (k === 'id' || k === 'relationships') continue;
            const val = typeof v === 'object' ? JSON.stringify(v) : String(v);
            propsHtml += `<div class="ge-prop-row">
                <span class="ge-prop-key mono">${_esc(k)}</span>
                <span class="ge-prop-val">${_esc(val)}</span>
            </div>`;
        }
        if (!propsHtml) {
            propsHtml = '<div class="ge-prop-row"><span class="ge-prop-val">No additional data</span></div>';
        }
        el.innerHTML = `
            <div class="ge-prop-header">
                <span class="ge-prop-badge" style="background:${color}">${_esc((node.entityType || 'UNK').toUpperCase().slice(0, 3))}</span>
                <span class="ge-prop-name mono">${_esc(node.label)}</span>
            </div>
            <div class="ge-prop-id mono">${_esc(node.id)}</div>
            ${propsHtml}
            <button class="ge-btn ge-expand-btn mono" data-action="ge-expand-selected">EXPAND</button>
        `;
        // Wire expand button
        const expandBtn = el.querySelector('[data-action="ge-expand-selected"]');
        if (expandBtn && this._graph) {
            expandBtn.addEventListener('click', async () => {
                if (!this._graph.expandedIds.has(node.id)) {
                    this._graph.expandedIds.add(node.id);
                    await this._fetchAndExpand(this._graph, node);
                    this._updateStatus();
                }
            });
        }
    },

    async _searchAndSeed(graph, query) {
        try {
            // Try dossier search first
            const res = await fetch(`/api/dossiers/search?q=${encodeURIComponent(query)}&limit=10`);
            if (res.ok) {
                const data = await res.json();
                const dossiers = data.dossiers || data.results || data || [];
                const list = Array.isArray(dossiers) ? dossiers : [];
                if (list.length > 0) {
                    for (const d of list) {
                        this._addDossierNode(graph, d);
                    }
                    return;
                }
            }
        } catch (_) { /* API may not exist */ }

        try {
            // Try fetching a single dossier by ID
            const res2 = await fetch(`/api/dossiers/${encodeURIComponent(query)}`);
            if (res2.ok) {
                const d = await res2.json();
                this._addDossierNode(graph, d);
                return;
            }
        } catch (_) { /* fallback */ }

        // If nothing found, add a placeholder node
        graph.addNode(query, query, 'unknown', { note: 'Not found in dossiers' });
    },

    _addDossierNode(graph, dossier) {
        const id = dossier.id || dossier.entity_id || dossier.dossier_id || String(Math.random());
        const label = dossier.name || dossier.label || dossier.entity_id || id;
        const type = dossier.entity_type || 'unknown';
        graph.addNode(id, label, type, dossier);

        // If dossier has relationships, add connected nodes and edges
        const rels = dossier.relationships || dossier.connections || [];
        for (const rel of rels) {
            const targetId = rel.target_id || rel.entity_id || rel.id;
            if (!targetId) continue;
            const targetLabel = rel.name || rel.label || targetId;
            const targetType = rel.entity_type || 'unknown';
            graph.addNode(targetId, targetLabel, targetType, rel);
            graph.addEdge(id, targetId, rel.type || rel.relationship || '', rel.confidence ?? 0.5);
        }
    },

    async _fetchAndExpand(graph, node) {
        try {
            const res = await fetch(`/api/dossiers/${encodeURIComponent(node.id)}`);
            if (res.ok) {
                const d = await res.json();
                this._addDossierNode(graph, d);
                return;
            }
        } catch (_) { /* skip */ }

        try {
            const res2 = await fetch(`/api/investigations/${encodeURIComponent(node.id)}/expand`);
            if (res2.ok) {
                const data = await res2.json();
                const entities = data.entities || data.nodes || [];
                const edges = data.edges || data.relationships || [];
                for (const ent of entities) {
                    const eid = ent.id || ent.entity_id;
                    if (!eid) continue;
                    graph.addNode(eid, ent.name || ent.label || eid, ent.entity_type || 'unknown', ent);
                }
                for (const edge of edges) {
                    const src = edge.source_id || edge.from;
                    const tgt = edge.target_id || edge.to;
                    if (src && tgt) {
                        graph.addEdge(src, tgt, edge.type || edge.label || '', edge.confidence ?? 0.5);
                    }
                }
            }
        } catch (_) { /* skip */ }
    },

    /**
     * Load ALL active target correlations at once and display them
     * as a unified graph. Each correlated pair becomes two nodes
     * connected by an edge with the correlation confidence and reason.
     * Also pulls in target metadata from /api/targets for richer labels.
     */
    async _loadAllCorrelations(graph) {
        graph.clear();

        // Fetch all correlations
        let correlations = [];
        try {
            const res = await fetch('/api/correlations');
            if (res.ok) {
                const data = await res.json();
                correlations = data.correlations || [];
            }
        } catch (_) { /* skip */ }

        if (correlations.length === 0) {
            // No correlations — show a placeholder
            graph.addNode('_empty', 'No correlations found', 'unknown', {
                note: 'No active target correlations. Start a demo or wait for sensor data.',
            });
            return;
        }

        // Collect unique target IDs
        const targetIds = new Set();
        for (const corr of correlations) {
            if (corr.primary_id) targetIds.add(corr.primary_id);
            if (corr.secondary_id) targetIds.add(corr.secondary_id);
        }

        // Try to fetch target metadata for richer node labels
        let targetMeta = {};
        try {
            const res = await fetch('/api/targets');
            if (res.ok) {
                const data = await res.json();
                const targets = data.targets || data || [];
                if (Array.isArray(targets)) {
                    for (const t of targets) {
                        const tid = t.target_id || t.id;
                        if (tid) targetMeta[tid] = t;
                    }
                }
            }
        } catch (_) { /* skip */ }

        // Also try dossier data for entity types
        let dossierMeta = {};
        try {
            const res = await fetch('/api/dossiers?limit=200');
            if (res.ok) {
                const data = await res.json();
                const dossiers = data.dossiers || data.results || [];
                if (Array.isArray(dossiers)) {
                    for (const d of dossiers) {
                        const did = d.id || d.entity_id || d.dossier_id;
                        if (did) dossierMeta[did] = d;
                    }
                }
            }
        } catch (_) { /* skip */ }

        // Add nodes for each unique target
        for (const tid of targetIds) {
            const meta = targetMeta[tid] || {};
            const dossier = dossierMeta[tid] || {};
            const label = meta.name || dossier.name || dossier.label || _shortenId(tid);
            const entityType = _classifyTargetType(tid, meta, dossier);
            graph.addNode(tid, label, entityType, {
                ...meta,
                ...dossier,
                target_id: tid,
            });
        }

        // Add edges for each correlation
        for (const corr of correlations) {
            if (!corr.primary_id || !corr.secondary_id) continue;
            const label = corr.reason || _buildStrategyLabel(corr.strategies);
            graph.addEdge(
                corr.primary_id,
                corr.secondary_id,
                label,
                corr.confidence || 0.5,
            );
        }
    },
};

/**
 * Shorten a target ID for display (e.g. "ble_AA:BB:CC:DD:EE:FF" -> "ble_AA:BB..FF")
 */
function _shortenId(id) {
    if (!id) return 'unknown';
    if (id.length <= 16) return id;
    return id.slice(0, 10) + '..' + id.slice(-4);
}

/**
 * Classify target type from ID prefix and metadata.
 */
function _classifyTargetType(id, meta, dossier) {
    const etype = dossier.entity_type || meta.entity_type || meta.classification || '';
    if (etype) {
        if (etype.includes('person') || etype.includes('human')) return 'person';
        if (etype.includes('vehicle') || etype.includes('car') || etype.includes('truck')) return 'vehicle';
        if (etype.includes('mesh') || etype.includes('radio')) return 'mesh';
        if (etype.includes('device') || etype.includes('ble') || etype.includes('wifi')) return 'device';
    }
    // Fallback: classify by ID prefix
    if (id.startsWith('ble_') || id.startsWith('wifi_')) return 'device';
    if (id.startsWith('det_person') || id.startsWith('det_human')) return 'person';
    if (id.startsWith('det_car') || id.startsWith('det_truck') || id.startsWith('det_vehicle')) return 'vehicle';
    if (id.startsWith('mesh_')) return 'mesh';
    return 'unknown';
}

/**
 * Build a short label from strategy scores for an edge.
 */
function _buildStrategyLabel(strategies) {
    if (!strategies || strategies.length === 0) return '';
    // Use the highest-scoring strategy as the label
    let best = strategies[0];
    for (const s of strategies) {
        if (s.score > best.score) best = s;
    }
    return best.name || '';
}
