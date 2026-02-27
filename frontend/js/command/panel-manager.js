// PanelManager -- floating, draggable, resizable panel system
// Creates panels dynamically from definitions. Panels use transform: translate()
// for GPU-accelerated positioning (no reflow, avoids MJPEG scroll-inflation bug).
//
// Usage:
//   import { PanelManager } from './panel-manager.js';
//   const pm = new PanelManager(document.getElementById('panel-container'));
//   pm.register({ id: 'amy', title: 'AMY', ... });
//   pm.open('amy');

import { EventBus } from './events.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SNAP_THRESHOLD = 8;        // px - gentle magnetic snap to edge
const MIN_PANEL_W = 200;
const MIN_PANEL_H = 120;
const HEADER_HEIGHT = 28;        // collapsed height when minimized
const STORAGE_KEY = 'tritium-panel-layout';

// ---------------------------------------------------------------------------
// Panel class
// ---------------------------------------------------------------------------

export class Panel {
    constructor(def, manager) {
        this.id = def.id;
        this.title = def.title;
        this.def = def;
        this.manager = manager;
        this.minimized = false;
        this._unsubs = [];

        // Position and size (pixels)
        this.x = def.defaultPosition?.x ?? 16;
        this.y = def.defaultPosition?.y ?? 16;
        this.w = def.defaultSize?.w ?? 300;
        this.h = def.defaultSize?.h ?? 250;

        // Create DOM
        this.el = this._createDOM();
        this._visible = true;
        this.bodyEl = this.el.querySelector('.panel-body');

        // Wire drag + resize
        this._bindDrag();
        this._bindResize();
        this._bindControls();

        // Apply initial position
        this._applyTransform();
        this._applySize();
    }

    _createDOM() {
        const el = document.createElement('div');
        el.className = 'panel';
        el.dataset.panelId = this.id;
        el.style.zIndex = this.manager._nextZ();
        el.innerHTML = `
            <div class="panel-header" data-drag-handle>
                <span class="panel-title mono">${_esc(this.title)}</span>
                <div class="panel-controls">
                    <button class="panel-btn panel-minimize" aria-label="Minimize" title="Minimize">&#x2500;</button>
                    <button class="panel-btn panel-close" aria-label="Close" title="Close">&times;</button>
                </div>
            </div>
            <div class="panel-body"></div>
            <div class="panel-resize-handle" data-resize-handle></div>
        `;
        return el;
    }

    mount() {
        // Create content via panel definition
        if (this.def.create) {
            const content = this.def.create(this);
            if (content instanceof HTMLElement) {
                this.bodyEl.appendChild(content);
            } else if (typeof content === 'string') {
                this.bodyEl.innerHTML = content;
            }
        }
        // Call mount hook
        if (this.def.mount) {
            this.def.mount(this.bodyEl, this);
        }
    }

    unmount() {
        if (this.def.unmount) {
            this.def.unmount(this.bodyEl);
        }
        for (const unsub of this._unsubs) unsub();
        this._unsubs.length = 0;
    }

    destroy() {
        this.unmount();
        this.el.remove();
    }

    hide() {
        this._visible = false;
        this.el.style.display = 'none';
    }

    show() {
        this._visible = true;
        this.el.style.display = '';
        this.bringToFront();
    }

    bringToFront() {
        this.el.style.zIndex = this.manager._nextZ();
    }

    minimize() {
        this.minimized = true;
        this.el.classList.add('panel-minimized');
        this.el.style.height = `${HEADER_HEIGHT}px`;
    }

    restore() {
        this.minimized = false;
        this.el.classList.remove('panel-minimized');
        this._applySize();
    }

    setPosition(x, y) {
        this.x = x;
        this.y = y;
        this._applyTransform();
    }

    setSize(w, h) {
        this.w = Math.max(MIN_PANEL_W, w);
        this.h = Math.max(MIN_PANEL_H, h);
        this._applySize();
    }

    _clampToBounds() {
        const container = this.manager.container;
        if (!container) return;
        const cw = container.clientWidth;
        const ch = container.clientHeight;
        if (cw === 0 || ch === 0) return; // container not laid out yet

        // Clamp width/height to container
        if (this.w > cw) this.w = cw;
        if (this.h > ch) this.h = ch;

        // Clamp bottom edge: panel must not extend past container bottom
        if (this.y + this.h > ch) this.h = ch - this.y;

        // Allow panels to move freely within the panel container.
        // The container is inset below the command bar, so y=0 is the top
        // of the game area. Panels must not go above y=0 (into the command bar)
        // or below the container. At least MIN_GRAB px must remain on-screen
        // horizontally so the header stays reachable.
        const MIN_GRAB = 40; // px of header that must remain on-screen
        if (this.x + this.w < MIN_GRAB) this.x = MIN_GRAB - this.w;
        if (this.x > cw - MIN_GRAB) this.x = cw - MIN_GRAB;
        if (this.y < 0) this.y = 0;   // Cannot go above container (into command bar)
        if (this.y + HEADER_HEIGHT > ch) this.y = ch - HEADER_HEIGHT;

        this._applyTransform();
        this._applySize();
    }

    _applyTransform() {
        this.el.style.transform = `translate(${Math.round(this.x)}px, ${Math.round(this.y)}px)`;
    }

    _applySize() {
        this.el.style.width = `${this.w}px`;
        if (!this.minimized) {
            this.el.style.height = `${this.h}px`;
        }
    }

    // ------ Drag ------

    _bindDrag() {
        const handle = this.el.querySelector('[data-drag-handle]');
        if (!handle) return;

        let startX, startY, startPanelX, startPanelY;

        const onMouseDown = (e) => {
            if (e.target.closest('.panel-btn')) return; // Don't drag from buttons
            e.preventDefault();
            this.bringToFront();
            startX = e.clientX;
            startY = e.clientY;
            startPanelX = this.x;
            startPanelY = this.y;
            this.el.classList.add('panel-dragging');
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        };

        const onMouseMove = (e) => {
            let newX = startPanelX + (e.clientX - startX);
            let newY = startPanelY + (e.clientY - startY);

            // Gentle magnetic snap -- only nudge to edge when very close
            const container = this.manager.container;
            const cw = container.clientWidth;
            const ch = container.clientHeight;

            if (newX >= 0 && newX < SNAP_THRESHOLD) newX = 0;
            if (newY >= 0 && newY < SNAP_THRESHOLD) newY = 0;
            if (newX + this.w > cw - SNAP_THRESHOLD && newX + this.w <= cw) newX = cw - this.w;
            if (newY + this.h > ch - SNAP_THRESHOLD && newY + this.h <= ch) newY = ch - this.h;

            // Keep header grabbable: at least MIN_GRAB px on-screen horizontally.
            // Panels cannot go above y=0 (into the command bar area).
            const MIN_GRAB = 40;
            if (newX + this.w < MIN_GRAB) newX = MIN_GRAB - this.w;
            if (newX > cw - MIN_GRAB) newX = cw - MIN_GRAB;
            if (newY < 0) newY = 0;    // Cannot go above container (into command bar)
            if (newY + HEADER_HEIGHT > ch) newY = ch - HEADER_HEIGHT;

            this.x = newX;
            this.y = newY;
            this._applyTransform();
        };

        const onMouseUp = () => {
            this.el.classList.remove('panel-dragging');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            this.manager.saveLayout();
        };

        handle.addEventListener('mousedown', onMouseDown);
    }

    // ------ Resize ------

    _bindResize() {
        const handle = this.el.querySelector('[data-resize-handle]');
        if (!handle) return;

        let startX, startY, startW, startH;

        const onMouseDown = (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.bringToFront();
            startX = e.clientX;
            startY = e.clientY;
            startW = this.w;
            startH = this.h;
            this.el.classList.add('panel-resizing');
            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        };

        const onMouseMove = (e) => {
            const newW = Math.max(MIN_PANEL_W, startW + (e.clientX - startX));
            const newH = Math.max(MIN_PANEL_H, startH + (e.clientY - startY));
            this.w = newW;
            this.h = newH;
            this._applySize();
            this._clampToBounds();
            if (this.def.onResize) {
                this.def.onResize(this.w, this.h);
            }
        };

        const onMouseUp = () => {
            this.el.classList.remove('panel-resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            this.manager.saveLayout();
        };

        handle.addEventListener('mousedown', onMouseDown);
    }

    // ------ Controls ------

    _bindControls() {
        this.el.querySelector('.panel-minimize')?.addEventListener('click', () => {
            if (this.minimized) this.restore();
            else this.minimize();
        });

        this.el.querySelector('.panel-close')?.addEventListener('click', () => {
            this.manager.close(this.id);
        });

        // Click anywhere on panel to bring to front
        this.el.addEventListener('mousedown', () => {
            this.bringToFront();
        });
    }

    // ------ Serialization ------

    serialize() {
        return {
            id: this.id,
            x: this.x,
            y: this.y,
            w: this.w,
            h: this.h,
            minimized: this.minimized,
            visible: this._visible,
        };
    }

    deserialize(data) {
        if (data.x !== undefined) this.x = data.x;
        if (data.y !== undefined) this.y = data.y;
        if (data.w !== undefined) this.w = Math.max(MIN_PANEL_W, data.w);
        if (data.h !== undefined) this.h = Math.max(MIN_PANEL_H, data.h);
        this._applyTransform();
        this._applySize();
        if (data.minimized) this.minimize();
        this._clampToBounds();
    }
}

// ---------------------------------------------------------------------------
// PanelManager
// ---------------------------------------------------------------------------

export class PanelManager {
    constructor(container) {
        this.container = container;
        this._registry = new Map();   // id -> panel definition
        this._panels = new Map();     // id -> Panel instance
        this._zCounter = 100;
        this._resizeHandler = null;
        this._initResize();
    }

    _initResize() {
        let timer;
        this._resizeHandler = () => {
            clearTimeout(timer);
            timer = setTimeout(() => this._clampAllPanels(), 150);
        };
        window.addEventListener('resize', this._resizeHandler);
    }

    _clampAllPanels() {
        for (const panel of this._panels.values()) {
            panel._clampToBounds();
        }
    }

    /**
     * Register a panel definition. Does not open it.
     * @param {Object} def - { id, title, defaultPosition, defaultSize, create, mount, unmount, onResize }
     */
    register(def) {
        if (!def.id || !def.title) {
            console.error('[PanelManager] Panel definition requires id and title');
            return;
        }
        this._registry.set(def.id, def);
    }

    /**
     * Open a panel (create it if not already open).
     * @param {string} id
     * @returns {Panel|null}
     */
    open(id) {
        if (this._panels.has(id)) {
            const panel = this._panels.get(id);
            panel.show();
            if (panel.minimized) panel.restore();
            return panel;
        }

        const def = this._registry.get(id);
        if (!def) {
            console.error(`[PanelManager] Unknown panel: ${id}`);
            return null;
        }

        const panel = new Panel(def, this);
        this._panels.set(id, panel);
        this.container.appendChild(panel.el);
        panel.mount();
        panel._clampToBounds();

        EventBus.emit('panel:opened', { id });
        return panel;
    }

    /**
     * Close a panel (hide it, preserving state for reopen).
     * @param {string} id
     */
    close(id) {
        const panel = this._panels.get(id);
        if (!panel) return;

        panel.hide();
        this.saveLayout();
        EventBus.emit('panel:closed', { id });
    }

    /**
     * Toggle a panel open/closed.
     * @param {string} id
     */
    toggle(id) {
        if (this._panels.has(id)) {
            const panel = this._panels.get(id);
            if (panel._visible) {
                this.close(id);
            } else {
                this.open(id);
            }
        } else {
            this.open(id);
        }
    }

    /**
     * Get an open panel instance.
     * @param {string} id
     * @returns {Panel|undefined}
     */
    getPanel(id) {
        return this._panels.get(id);
    }

    /**
     * Check if a panel is currently open.
     * @param {string} id
     * @returns {boolean}
     */
    isOpen(id) {
        const panel = this._panels.get(id);
        return panel ? panel._visible : false;
    }

    /**
     * Get list of all registered panel IDs.
     * @returns {string[]}
     */
    registeredIds() {
        return [...this._registry.keys()];
    }

    /**
     * Get info about all registered panels (for toolbars/menus).
     * @returns {Array<{id: string, title: string, isOpen: boolean}>}
     */
    getRegisteredPanels() {
        return [...this._registry.entries()].map(([id, def]) => ({
            id,
            title: def.title,
            isOpen: this.isOpen(id),
        }));
    }

    /**
     * Get next z-index (increments global counter).
     * @returns {number}
     */
    _nextZ() {
        return ++this._zCounter;
    }

    // ------ Layout persistence ------

    /**
     * Save current panel positions/sizes to localStorage.
     */
    saveLayout() {
        const layout = {};
        for (const [id, panel] of this._panels) {
            layout[id] = panel.serialize();
        }
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
        } catch (_) {
            // localStorage might be full or unavailable
        }
    }

    /**
     * Load layout from localStorage and apply to open panels.
     * Opens panels that were saved as open.
     */
    loadLayout() {
        let layout;
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return false;
            layout = JSON.parse(raw);
        } catch (_) {
            return false;
        }

        for (const [id, data] of Object.entries(layout)) {
            if (this._registry.has(id)) {
                const panel = this.open(id);
                if (panel) {
                    panel.deserialize(data);
                    if (data.visible === false) {
                        panel.hide();
                    }
                }
            }
        }
        return true;
    }

    /**
     * Apply a named preset layout.
     * @param {string} preset - 'commander' | 'observer' | 'tactical'
     */
    applyPreset(preset) {
        // Destroy all current panels (full reset for preset)
        for (const id of [...this._panels.keys()]) {
            const panel = this._panels.get(id);
            if (panel) {
                panel.destroy();
            }
        }
        this._panels.clear();

        const presets = this._getPresets();
        const config = presets[preset];
        if (!config) return;

        for (const [id, pos] of Object.entries(config)) {
            if (this._registry.has(id)) {
                const panel = this.open(id);
                if (panel) {
                    panel.setPosition(pos.x, pos.y);
                    panel.setSize(pos.w, pos.h);
                    panel._clampToBounds();
                }
            }
        }

        this.saveLayout();
    }

    _getPresets() {
        // Container dimensions for relative positioning
        const cw = this.container.clientWidth || 1200;
        const ch = this.container.clientHeight || 700;

        return {
            commander: {
                amy:     { x: 8,        y: ch - 210, w: 320, h: 200 },
                units:   { x: 8,        y: 8,        w: 260, h: ch - 230 },
                alerts:  { x: cw - 296, y: 8,        w: 280, h: 320 },
                minimap: { x: cw - 236, y: ch - 236, w: 220, h: 220 },
            },
            observer: {
                alerts:  { x: cw - 296, y: 8,        w: 280, h: 300 },
                minimap: { x: cw - 236, y: ch - 236, w: 220, h: 220 },
            },
            tactical: {
                units:   { x: 8,        y: 8,        w: 260, h: ch - 230 },
                alerts:  { x: cw - 296, y: 8,        w: 280, h: 300 },
                minimap: { x: cw - 236, y: ch - 236, w: 220, h: 220 },
            },
        };
    }

    /**
     * Destroy all panels and clean up.
     */
    destroyAll() {
        for (const [id, panel] of this._panels) {
            panel.destroy();
        }
        this._panels.clear();
        if (this._resizeHandler) {
            window.removeEventListener('resize', this._resizeHandler);
            this._resizeHandler = null;
        }
    }
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}
