// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// StatusBar -- shared bottom status bar component for addon panels.
// Shows status text, measurement count, and uptime.

/**
 * Bottom status bar for addon panels.
 *
 * Usage:
 *   const bar = new StatusBar(container);
 *   bar.setText('Scanning...');
 *   bar.setMeasurements(1024);
 *   bar.setUptime(3600);
 */
class StatusBar {
    /**
     * @param {HTMLElement} container - DOM element to render into
     */
    constructor(container) {
        this.container = container;
        this._text = '';
        this._measurements = 0;
        this._uptime = 0;
        this._root = null;
        this._textEl = null;
        this._measureEl = null;
        this._uptimeEl = null;

        this.render();
    }

    /**
     * Set status text.
     * @param {string} text
     */
    setText(text) {
        this._text = text;
        if (this._textEl) {
            this._textEl.textContent = text;
        }
    }

    /**
     * Set measurement count.
     * @param {number} count
     */
    setMeasurements(count) {
        this._measurements = count;
        if (this._measureEl) {
            this._measureEl.textContent = `${count.toLocaleString()} samples`;
        }
    }

    /**
     * Set uptime in seconds.
     * @param {number} seconds
     */
    setUptime(seconds) {
        this._uptime = seconds;
        if (this._uptimeEl) {
            this._uptimeEl.textContent = StatusBar.formatUptime(seconds);
        }
    }

    /**
     * Format seconds into HH:MM:SS string.
     * @param {number} sec
     * @returns {string}
     */
    static formatUptime(sec) {
        const h = Math.floor(sec / 3600);
        const m = Math.floor((sec % 3600) / 60);
        const s = Math.floor(sec % 60);
        const pad = (n) => String(n).padStart(2, '0');
        return `${pad(h)}:${pad(m)}:${pad(s)}`;
    }

    /**
     * Build the component DOM.
     */
    render() {
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }

        const root = document.createElement('div');
        root.classList.add('status-bar');

        const textSpan = document.createElement('span');
        textSpan.classList.add('status-bar-text');
        textSpan.textContent = this._text;
        root.appendChild(textSpan);
        this._textEl = textSpan;

        const measureSpan = document.createElement('span');
        measureSpan.classList.add('status-bar-measurements');
        measureSpan.textContent = this._measurements > 0
            ? `${this._measurements.toLocaleString()} samples` : '';
        root.appendChild(measureSpan);
        this._measureEl = measureSpan;

        const uptimeSpan = document.createElement('span');
        uptimeSpan.classList.add('status-bar-uptime');
        uptimeSpan.textContent = this._uptime > 0
            ? StatusBar.formatUptime(this._uptime) : '';
        root.appendChild(uptimeSpan);
        this._uptimeEl = uptimeSpan;

        this._root = root;
        this.container.appendChild(root);
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
}

export { StatusBar };
