// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// ConnectionBar -- shared connection status bar component for addon panels.
// Shows connection state, device name, and signal strength.

/**
 * Connection status bar for addon panels.
 *
 * Usage:
 *   const bar = new ConnectionBar(container);
 *   bar.setConnected(true, 'HackRF-001');
 *   bar.setSignal(3);
 */
class ConnectionBar {
    /**
     * @param {HTMLElement} container - DOM element to render into
     * @param {Object} [options]
     * @param {string} [options.label] - Override label text
     */
    constructor(container, options = {}) {
        this.container = container;
        this._connected = false;
        this._deviceName = '';
        this._signal = 0;
        this._statusText = '';
        this._statusType = 'info';
        this._label = options.label || '';
        this._root = null;
        this._dotEl = null;
        this._labelEl = null;
        this._signalEl = null;
        this._statusEl = null;

        this.render();
    }

    /**
     * Set connection state.
     * @param {boolean} connected
     * @param {string} [deviceName]
     */
    setConnected(connected, deviceName = '') {
        this._connected = !!connected;
        this._deviceName = deviceName;
        this._update();
    }

    /**
     * Set signal strength level (0-4 bars).
     * @param {number} level - 0 to 4
     */
    setSignal(level) {
        this._signal = Math.max(0, Math.min(4, Math.round(level)));
        this._update();
    }

    /**
     * Set status text with type coloring.
     * @param {string} text
     * @param {string} [type] - 'info', 'warn', 'error'
     */
    setStatus(text, type = 'info') {
        this._statusText = text;
        this._statusType = type;
        this._update();
    }

    /**
     * Build the component DOM.
     */
    render() {
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const root = document.createElement('div');
        root.classList.add('conn-bar');

        // Connection dot
        const dot = document.createElement('span');
        dot.classList.add('conn-bar-dot');
        root.appendChild(dot);
        this._dotEl = dot;

        // Label (CONNECTED / DISCONNECTED or custom)
        const label = document.createElement('span');
        label.classList.add('conn-bar-label');
        root.appendChild(label);
        this._labelEl = label;

        // Signal bars
        const signal = document.createElement('span');
        signal.classList.add('conn-bar-signal');
        root.appendChild(signal);
        this._signalEl = signal;

        // Status text
        const status = document.createElement('span');
        status.classList.add('conn-bar-status');
        root.appendChild(status);
        this._statusEl = status;

        this._root = root;
        this.container.appendChild(root);
        this._update();
    }

    /**
     * Remove DOM elements.
     */
    destroy() {
        if (this._root && this._root.parentNode) {
            this._root.parentNode.removeChild(this._root);
        }
        this._root = null;
    }

    /**
     * Update visual state from internal values.
     */
    _update() {
        if (!this._root) return;

        // Dot
        if (this._dotEl) {
            this._dotEl.className = 'conn-bar-dot';
            this._dotEl.classList.add(this._connected ? 'connected' : 'disconnected');
            this._dotEl.textContent = this._connected ? '\u25CF' : '\u25CB';
        }

        // Label
        if (this._labelEl) {
            const name = this._deviceName ? ` ${this._deviceName}` : '';
            this._labelEl.textContent = this._label || (this._connected ? `CONNECTED${name}` : 'DISCONNECTED');
        }

        // Signal bars
        if (this._signalEl) {
            if (this._connected && this._signal > 0) {
                const bars = [];
                for (let i = 1; i <= 4; i++) {
                    bars.push(i <= this._signal ? '\u2588' : '\u2591');
                }
                this._signalEl.textContent = bars.join('');
                this._signalEl.style.display = '';
            } else {
                this._signalEl.textContent = '';
                this._signalEl.style.display = 'none';
            }
        }

        // Status text
        if (this._statusEl) {
            this._statusEl.textContent = this._statusText;
            this._statusEl.className = 'conn-bar-status';
            if (this._statusType === 'warn') {
                this._statusEl.classList.add('status-warn');
            } else if (this._statusType === 'error') {
                this._statusEl.classList.add('status-error');
            }
        }
    }
}

export { ConnectionBar };
