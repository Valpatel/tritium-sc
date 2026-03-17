// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// DeviceSelector -- shared dropdown component for addon panels.
// Any addon with a /devices API endpoint can use this to let the
// operator switch between registered devices.

/**
 * Status dot characters and CSS classes for each device state.
 */
const STATUS_MAP = {
    connected:    { dot: '\u25CF', cls: 'connected' },
    connecting:   { dot: '\u25CF', cls: 'connecting' },
    disconnected: { dot: '\u25CB', cls: 'disconnected' },
    error:        { dot: '\u25CF', cls: 'error' },
};

function statusFor(state) {
    return STATUS_MAP[state] || STATUS_MAP.disconnected;
}

/**
 * Build a concise info string from device metadata.
 * Joins non-empty values of model, hardware_rev, and firmware_version.
 */
function deviceInfoText(dev) {
    const parts = [];
    if (dev.model) parts.push(dev.model);
    if (dev.hardware_rev) parts.push(dev.hardware_rev);
    if (dev.firmware_version) parts.push('v' + dev.firmware_version);
    return parts.join(' | ');
}

class DeviceSelector {
    /**
     * @param {Object} options
     * @param {string}      options.addonId      - addon identifier (e.g. "hackrf")
     * @param {HTMLElement}  options.container    - DOM element to render into
     * @param {Function}     options.onSelect     - callback(deviceId) on selection change
     * @param {string}      [options.apiBase]     - base URL, defaults to /api/addons/<addonId>
     * @param {number}      [options.pollInterval]- ms between refreshes, defaults to 5000
     */
    constructor(options) {
        this.addonId = options.addonId;
        this.container = options.container;
        this.onSelect = options.onSelect || (() => {});
        this.apiBase = options.apiBase || `/api/addons/${this.addonId}`;
        this.pollInterval = options.pollInterval != null ? options.pollInterval : 5000;

        this._pollTimer = null;
        this._devices = [];
        this._selectedId = null;

        // DOM references (set by render())
        this._root = null;
        this._dropdown = null;
        this._dot = null;
        this._info = null;

        this.render();
        this.refresh();
        this._startPolling();
    }

    // ----------------------------------------------------------------
    // Public API
    // ----------------------------------------------------------------

    /** Returns the currently selected device ID, or null. */
    getSelectedDeviceId() {
        return this._selectedId;
    }

    /** Fetch device list from the addon API and update the dropdown. */
    async refresh() {
        try {
            const resp = await (this._fetch || fetch)(`${this.apiBase}/devices`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            this._devices = Array.isArray(data) ? data : (data.devices || []);
        } catch (_err) {
            // On error keep existing list; status area shows stale data.
            if (this._devices.length === 0) {
                this._devices = [];
            }
        }
        this._updateDropdown();
    }

    /** Build the component DOM inside the container. */
    render() {
        const root = document.createElement('div');
        root.classList.add('device-selector');

        // Label
        const label = document.createElement('div');
        label.classList.add('device-selector-label');
        label.textContent = 'DEVICE';
        root.appendChild(label);

        // Dropdown
        const select = document.createElement('select');
        select.classList.add('device-selector-dropdown');
        select.addEventListener('change', () => this._onDropdownChange());
        root.appendChild(select);

        // Status line
        const statusDiv = document.createElement('div');
        statusDiv.classList.add('device-selector-status');

        const dot = document.createElement('span');
        dot.classList.add('device-dot', 'disconnected');
        statusDiv.appendChild(dot);

        const info = document.createElement('span');
        info.classList.add('device-info');
        statusDiv.appendChild(info);

        root.appendChild(statusDiv);

        // Store references
        this._root = root;
        this._dropdown = select;
        this._dot = dot;
        this._info = info;

        // Clear container and mount
        while (this.container.firstChild) {
            this.container.removeChild(this.container.firstChild);
        }
        this.container.appendChild(root);
    }

    /** Tear down polling and remove DOM. */
    destroy() {
        this._stopPolling();
        if (this._root && this._root.parentNode) {
            this._root.parentNode.removeChild(this._root);
        }
        this._root = null;
        this._dropdown = null;
        this._dot = null;
        this._info = null;
    }

    // ----------------------------------------------------------------
    // Internal
    // ----------------------------------------------------------------

    _startPolling() {
        if (this.pollInterval > 0 && !this._pollTimer) {
            this._pollTimer = setInterval(() => this.refresh(), this.pollInterval);
        }
    }

    _stopPolling() {
        if (this._pollTimer) {
            clearInterval(this._pollTimer);
            this._pollTimer = null;
        }
    }

    _onDropdownChange() {
        const newId = this._dropdown ? this._dropdown.value : null;
        this._selectedId = newId || null;
        this._updateStatus();
        this.onSelect(this._selectedId);
    }

    /** Rebuild <option> elements from this._devices, preserving selection. */
    _updateDropdown() {
        if (!this._dropdown) return;

        const prevSelected = this._selectedId;

        // Clear existing options
        while (this._dropdown.firstChild) {
            this._dropdown.removeChild(this._dropdown.firstChild);
        }

        if (this._devices.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '-- no devices --';
            this._dropdown.appendChild(opt);
            this._selectedId = null;
            this._updateStatus();
            return;
        }

        for (const dev of this._devices) {
            const id = dev.device_id || dev.id || '';
            const state = dev.status || dev.state || 'disconnected';
            const st = statusFor(state);
            const opt = document.createElement('option');
            opt.value = id;
            opt.textContent = `${id} ${st.dot} ${state.toUpperCase()}`;
            this._dropdown.appendChild(opt);
        }

        // Restore previous selection if still present
        const ids = this._devices.map(d => d.device_id || d.id || '');
        if (prevSelected && ids.includes(prevSelected)) {
            this._dropdown.value = prevSelected;
            this._selectedId = prevSelected;
        } else {
            // Auto-select first device
            this._selectedId = ids[0] || null;
            if (this._selectedId) {
                this._dropdown.value = this._selectedId;
            }
        }

        this._updateStatus();
    }

    /** Update the status dot and info text for the selected device. */
    _updateStatus() {
        if (!this._dot || !this._info) return;

        const dev = this._devices.find(
            d => (d.device_id || d.id) === this._selectedId
        );

        if (!dev) {
            // Remove all status classes, show disconnected
            for (const key of Object.keys(STATUS_MAP)) {
                this._dot.classList.remove(key);
            }
            this._dot.classList.add('disconnected');
            this._info.textContent = '';
            return;
        }

        const state = dev.status || dev.state || 'disconnected';
        const st = statusFor(state);

        for (const key of Object.keys(STATUS_MAP)) {
            this._dot.classList.remove(key);
        }
        this._dot.classList.add(st.cls);
        this._info.textContent = deviceInfoText(dev);
    }
}

export { DeviceSelector, STATUS_MAP, statusFor, deviceInfoText };
