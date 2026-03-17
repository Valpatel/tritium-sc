// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// HACKRF SDR — Full-featured HackRF One management panel.
// Tabs: RADIO | SPECTRUM | SIGNALS | CONFIG | FIRMWARE
// Polls device status on open; auto-refreshes sweep data while running.

import { _esc } from '/static/js/command/panel-utils.js';

const API = '/api/addons/hackrf';
const REFRESH_MS = 3000;
const SWEEP_REFRESH_MS = 500;

// ── Tab definitions ────────────────────────────────────────────────
const TABS = [
    { id: 'radio',    label: 'RADIO',    tip: 'Device info, quick actions, presets' },
    { id: 'spectrum', label: 'SPECTRUM', tip: 'Frequency sweep and waterfall display' },
    { id: 'signals',  label: 'SIGNALS',  tip: 'Detected signals above threshold' },
    { id: 'config',   label: 'CONFIG',   tip: 'Gain, sample rate, antenna settings' },
    { id: 'firmware', label: 'FIRMWARE', tip: 'Firmware version and flashing' },
];

// ── Frequency presets ──────────────────────────────────────────────
const PRESETS = [
    { label: 'FM Radio',    startMhz: 88,    endMhz: 108,  color: '#05ffa1' },
    { label: 'ISM 433MHz',  startMhz: 430,   endMhz: 440,  color: '#b060ff' },
    { label: 'ISM 915MHz',  startMhz: 902,   endMhz: 928,  color: '#00f0ff' },
    { label: 'WiFi 2.4GHz', startMhz: 2400,  endMhz: 2500, color: '#fcee0a' },
    { label: 'ADS-B 1090',  startMhz: 1085,  endMhz: 1095, color: '#ff2a6d' },
];

// ── Signal table columns ───────────────────────────────────────────
const SIG_COLS = [
    { key: 'freq_mhz',   label: 'FREQ (MHz)', width: '100px', align: 'right' },
    { key: 'power_dbm',  label: 'POWER (dBm)', width: '90px',  align: 'right' },
    { key: 'first_seen', label: 'FIRST SEEN',  width: '90px',  align: 'right' },
    { key: 'last_seen',  label: 'LAST SEEN',   width: '90px',  align: 'right' },
    { key: 'duration_s', label: 'DURATION',    width: '70px',  align: 'right' },
];

// ── Panel definition ───────────────────────────────────────────────
export const HackRFPanelDef = {
    id: 'hackrf',
    title: 'HACKRF SDR',
    defaultPosition: { x: 80, y: 60 },
    defaultSize: { w: 640, h: 700 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'hrf-panel';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;font-family:var(--font-mono,"JetBrains Mono",monospace);';

        const tabHtml = TABS.map((t, i) =>
            `<button class="hrf-tab${i === 0 ? ' hrf-tab-active' : ''}" data-tab="${t.id}" title="${t.tip}">${t.label}</button>`
        ).join('');

        el.innerHTML = `
            <div class="hrf-conn-bar">
                <span class="hrf-dot" data-bind="dot"></span>
                <span class="hrf-conn-label" data-bind="conn-label">DISCONNECTED</span>
                <span style="flex:1"></span>
                <span class="hrf-conn-device" data-bind="conn-device"></span>
                <span class="hrf-conn-fw" data-bind="conn-fw"></span>
            </div>
            <div class="hrf-tabs">${tabHtml}</div>
            <div class="hrf-body" data-bind="body"></div>
        `;

        return el;
    },

    mount(bodyEl, panel) {
        const dot = bodyEl.querySelector('[data-bind="dot"]');
        const connLabel = bodyEl.querySelector('[data-bind="conn-label"]');
        const connDevice = bodyEl.querySelector('[data-bind="conn-device"]');
        const connFw = bodyEl.querySelector('[data-bind="conn-fw"]');
        const tabContainer = bodyEl.querySelector('.hrf-tabs');
        const body = bodyEl.querySelector('[data-bind="body"]');

        let activeTab = 'radio';
        let connected = false;
        let deviceInfo = {};
        let deviceStatus = {};
        let sweepRunning = false;
        let sweepData = null;       // { freqs: [], powers: [] }
        let signals = [];
        let signalThreshold = -50;
        let signalSortKey = 'power_dbm';
        let signalSortDir = -1;
        let configData = {};
        let firmwareInfo = {};
        let sweepStartMhz = 88;
        let sweepEndMhz = 108;
        let sweepBinWidth = '500kHz';

        _injectStyles();

        // ── Tab switching ──────────────────────────────────────────
        tabContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.hrf-tab');
            if (btn === null) return;
            activeTab = btn.dataset.tab;
            tabContainer.querySelectorAll('.hrf-tab').forEach(t =>
                t.classList.toggle('hrf-tab-active', t.dataset.tab === activeTab)
            );
            renderBody();
        });

        // ── Connection state ───────────────────────────────────────
        function updateConnection(info, status) {
            if (info) deviceInfo = info;
            if (status) deviceStatus = status;
            connected = (deviceStatus.connected === true) || (deviceInfo.serial_number != null && deviceInfo.serial_number !== '');
            dot.className = connected ? 'hrf-dot hrf-dot-on' : 'hrf-dot';
            dot.title = connected ? 'HackRF One connected' : 'No HackRF detected';
            connLabel.textContent = connected ? 'CONNECTED' : 'DISCONNECTED';
            connLabel.style.color = connected ? '#05ffa1' : '#888';
            connDevice.textContent = connected ? 'HackRF One' + (deviceInfo.serial_number ? ' [' + _esc(deviceInfo.serial_number.substring(0, 8)) + '...]' : '') : '';
            connFw.textContent = connected && deviceInfo.firmware_version ? 'FW ' + _esc(deviceInfo.firmware_version) : '';
        }

        // ── Data fetching ──────────────────────────────────────────
        async function fetchStatus() {
            try {
                const r = await fetch(API + '/status');
                if (r.ok) {
                    const d = await r.json();
                    deviceStatus = d;
                    updateConnection(null, d);
                }
            } catch (_) { /* network error */ }
        }

        async function fetchInfo() {
            try {
                const r = await fetch(API + '/info');
                if (r.ok) {
                    const d = await r.json();
                    deviceInfo = d;
                    updateConnection(d, null);
                }
            } catch (_) { /* network error */ }
        }

        async function fetchSweepData() {
            try {
                const r = await fetch(API + '/sweep/data');
                if (r.ok) {
                    const d = await r.json();
                    sweepData = d;
                    sweepRunning = d.running || false;
                    if (d.signals) signals = d.signals;
                    if (activeTab === 'spectrum' || activeTab === 'signals') renderBody();
                }
            } catch (_) { /* network error */ }
        }

        async function fetchFirmware() {
            try {
                const r = await fetch(API + '/firmware');
                if (r.ok) firmwareInfo = await r.json();
            } catch (_) { /* network error */ }
        }

        async function fetchAll() {
            await Promise.all([fetchStatus(), fetchInfo()]);
            renderBody();
        }

        // ── Actions ────────────────────────────────────────────────
        async function startSweep(startMhz, endMhz, binWidth) {
            try {
                const r = await fetch(API + '/sweep/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ freq_start: startMhz, freq_end: endMhz, bin_width: binWidth }),
                });
                if (r.ok) {
                    sweepRunning = true;
                    renderBody();
                }
            } catch (_) { /* network error */ }
        }

        async function stopSweep() {
            try {
                const r = await fetch(API + '/sweep/stop', { method: 'POST' });
                if (r.ok) {
                    sweepRunning = false;
                    renderBody();
                }
            } catch (_) { /* network error */ }
        }

        async function flashFirmware(filePath) {
            try {
                const r = await fetch(API + '/flash', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ firmware_path: filePath }),
                });
                if (r.ok) {
                    const d = await r.json();
                    return d;
                }
            } catch (_) { /* network error */ }
            return null;
        }

        // ── Render dispatcher ──────────────────────────────────────
        function renderBody() {
            switch (activeTab) {
                case 'radio':    renderRadio(); break;
                case 'spectrum': renderSpectrum(); break;
                case 'signals':  renderSignals(); break;
                case 'config':   renderConfig(); break;
                case 'firmware': renderFirmware(); break;
            }
        }

        // ── RADIO tab ──────────────────────────────────────────────
        function renderRadio() {
            const info = deviceInfo || {};
            const st = deviceStatus || {};
            const activity = st.activity || 'idle';
            const actColor = activity === 'idle' ? '#888' : activity === 'sweeping' ? '#b060ff' : '#05ffa1';

            body.innerHTML = `
                <div class="hrf-radio-status">
                    <div class="hrf-radio-indicator" style="border-color:${actColor}44">
                        <div class="hrf-radio-dot-big" style="background:${actColor};box-shadow:0 0 12px ${actColor}88"></div>
                        <div class="hrf-radio-status-text" style="color:${actColor}">${_esc(activity.toUpperCase())}</div>
                    </div>
                </div>

                <div class="hrf-section-label">DEVICE INFO</div>
                <div class="hrf-info-grid">
                    ${_infoRow('Serial', info.serial_number || '--')}
                    ${_infoRow('Firmware', info.firmware_version || '--')}
                    ${_infoRow('Board ID', info.board_id != null ? String(info.board_id) : '--')}
                    ${_infoRow('Part ID', info.part_id || '--')}
                    ${_infoRow('HW Revision', info.hardware_revision || '--')}
                </div>

                <div class="hrf-section-label">QUICK ACTIONS</div>
                <div class="hrf-radio-actions">
                    <button class="hrf-btn hrf-btn-action" data-action="sweep-fm">SWEEP FM BAND</button>
                    <button class="hrf-btn hrf-btn-action" data-action="sweep-ism">SWEEP ISM BAND</button>
                    <button class="hrf-btn" data-action="refresh-info">REFRESH</button>
                </div>

                <div class="hrf-section-label">PRESETS</div>
                <div class="hrf-radio-actions">
                    ${PRESETS.map(p => `<button class="hrf-btn hrf-btn-preset" data-preset-start="${p.startMhz}" data-preset-end="${p.endMhz}" style="border-color:${p.color}44;color:${p.color}">${_esc(p.label)}</button>`).join('')}
                </div>
            `;

            // Bind quick actions
            body.querySelector('[data-action="sweep-fm"]')?.addEventListener('click', () => {
                sweepStartMhz = 88; sweepEndMhz = 108;
                activeTab = 'spectrum';
                tabContainer.querySelectorAll('.hrf-tab').forEach(t => t.classList.toggle('hrf-tab-active', t.dataset.tab === 'spectrum'));
                startSweep(88, 108, sweepBinWidth);
            });
            body.querySelector('[data-action="sweep-ism"]')?.addEventListener('click', () => {
                sweepStartMhz = 430; sweepEndMhz = 440;
                activeTab = 'spectrum';
                tabContainer.querySelectorAll('.hrf-tab').forEach(t => t.classList.toggle('hrf-tab-active', t.dataset.tab === 'spectrum'));
                startSweep(430, 440, sweepBinWidth);
            });
            body.querySelector('[data-action="refresh-info"]')?.addEventListener('click', () => fetchAll());

            body.querySelectorAll('[data-preset-start]').forEach(btn => {
                btn.addEventListener('click', () => {
                    sweepStartMhz = parseInt(btn.dataset.presetStart, 10);
                    sweepEndMhz = parseInt(btn.dataset.presetEnd, 10);
                    activeTab = 'spectrum';
                    tabContainer.querySelectorAll('.hrf-tab').forEach(t => t.classList.toggle('hrf-tab-active', t.dataset.tab === 'spectrum'));
                    startSweep(sweepStartMhz, sweepEndMhz, sweepBinWidth);
                });
            });
        }

        // ── SPECTRUM tab ───────────────────────────────────────────
        function renderSpectrum() {
            body.innerHTML = `
                <div class="hrf-spectrum-controls">
                    <div class="hrf-spectrum-row">
                        <label class="hrf-lbl">START (MHz)</label>
                        <input class="hrf-input hrf-input-sm" type="number" data-bind="freq-start" value="${sweepStartMhz}" min="1" max="6000" step="1">
                        <label class="hrf-lbl">END (MHz)</label>
                        <input class="hrf-input hrf-input-sm" type="number" data-bind="freq-end" value="${sweepEndMhz}" min="1" max="6000" step="1">
                        <label class="hrf-lbl">BIN</label>
                        <select class="hrf-select" data-bind="bin-width">
                            <option value="100kHz"${sweepBinWidth === '100kHz' ? ' selected' : ''}>100 kHz</option>
                            <option value="500kHz"${sweepBinWidth === '500kHz' ? ' selected' : ''}>500 kHz</option>
                            <option value="1MHz"${sweepBinWidth === '1MHz' ? ' selected' : ''}>1 MHz</option>
                        </select>
                    </div>
                    <div class="hrf-spectrum-row" style="gap:8px">
                        <button class="hrf-btn hrf-btn-start" data-action="start-sweep" ${sweepRunning ? 'disabled' : ''}>START SWEEP</button>
                        <button class="hrf-btn hrf-btn-stop" data-action="stop-sweep" ${sweepRunning ? '' : 'disabled'}>STOP SWEEP</button>
                        ${sweepRunning ? '<span class="hrf-sweep-live"><span class="hrf-live-dot"></span> LIVE</span>' : ''}
                    </div>
                </div>

                <div class="hrf-section-label">SPECTRUM DISPLAY</div>
                <div class="hrf-spectrum-canvas-wrap">
                    <canvas data-bind="spectrum-canvas" width="600" height="200"></canvas>
                </div>

                <div class="hrf-section-label">PEAK SIGNALS</div>
                <div class="hrf-peak-list" data-bind="peak-list"></div>
            `;

            const freqStartInput = body.querySelector('[data-bind="freq-start"]');
            const freqEndInput = body.querySelector('[data-bind="freq-end"]');
            const binSelect = body.querySelector('[data-bind="bin-width"]');
            const canvas = body.querySelector('[data-bind="spectrum-canvas"]');
            const peakList = body.querySelector('[data-bind="peak-list"]');

            freqStartInput.addEventListener('change', () => { sweepStartMhz = parseInt(freqStartInput.value, 10) || 88; });
            freqEndInput.addEventListener('change', () => { sweepEndMhz = parseInt(freqEndInput.value, 10) || 108; });
            binSelect.addEventListener('change', () => { sweepBinWidth = binSelect.value; });

            body.querySelector('[data-action="start-sweep"]')?.addEventListener('click', () => {
                startSweep(sweepStartMhz, sweepEndMhz, sweepBinWidth);
            });
            body.querySelector('[data-action="stop-sweep"]')?.addEventListener('click', () => {
                stopSweep();
            });

            // Draw spectrum
            _drawSpectrum(canvas, sweepData);
            _renderPeaks(peakList, sweepData);
        }

        function _drawSpectrum(canvas, data) {
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;

            // Clear
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            // Grid lines
            ctx.strokeStyle = '#1a1a2e';
            ctx.lineWidth = 1;
            for (let y = 0; y < h; y += 40) {
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
            }
            for (let x = 0; x < w; x += 60) {
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            }

            if (data == null || data.freqs == null || data.freqs.length === 0) {
                ctx.fillStyle = '#555';
                ctx.font = '11px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('No sweep data -- start a sweep to visualize', w / 2, h / 2);
                return;
            }

            const freqs = data.freqs;
            const powers = data.powers;
            const n = freqs.length;
            if (n === 0) return;

            // Find power range for scaling
            let minP = -100, maxP = -20;
            for (let i = 0; i < n; i++) {
                if (powers[i] < minP) minP = powers[i];
                if (powers[i] > maxP) maxP = powers[i];
            }
            if (maxP - minP < 10) { minP = maxP - 40; }

            const barW = Math.max(1, Math.floor(w / n));

            for (let i = 0; i < n; i++) {
                const pNorm = Math.max(0, Math.min(1, (powers[i] - minP) / (maxP - minP)));
                const barH = Math.max(1, pNorm * (h - 20));
                const x = (i / n) * w;

                // Color: green (weak) -> yellow -> red (strong)
                let r, g, b;
                if (pNorm < 0.5) {
                    r = Math.round(pNorm * 2 * 252);
                    g = Math.round(5 + (1 - pNorm * 2) * 250);
                    b = Math.round(pNorm * 2 * 10);
                } else {
                    r = Math.round(255);
                    g = Math.round((1 - (pNorm - 0.5) * 2) * 238);
                    b = Math.round((pNorm - 0.5) * 2 * 109);
                }

                ctx.fillStyle = `rgb(${r},${g},${b})`;
                ctx.fillRect(x, h - barH, barW + 0.5, barH);
            }

            // Axis labels
            ctx.fillStyle = '#888';
            ctx.font = '9px monospace';
            ctx.textAlign = 'left';
            ctx.fillText(freqs[0].toFixed(1) + ' MHz', 4, h - 4);
            ctx.textAlign = 'right';
            ctx.fillText(freqs[n - 1].toFixed(1) + ' MHz', w - 4, h - 4);
            ctx.textAlign = 'left';
            ctx.fillText(maxP.toFixed(0) + ' dBm', 4, 12);
            ctx.fillText(minP.toFixed(0) + ' dBm', 4, h - 14);
        }

        function _renderPeaks(container, data) {
            if (data == null || data.freqs == null || data.freqs.length === 0) {
                container.innerHTML = '<div style="padding:8px 10px;color:#555;font-size:0.72rem">No data</div>';
                return;
            }

            // Find top 10 peaks
            const indexed = data.powers.map((p, i) => ({ freq: data.freqs[i], power: p }));
            indexed.sort((a, b) => b.power - a.power);
            const peaks = indexed.slice(0, 10);

            container.innerHTML = peaks.map(pk =>
                `<div class="hrf-peak-row">
                    <span class="hrf-peak-freq">${pk.freq.toFixed(3)} MHz</span>
                    <span class="hrf-peak-bar-wrap"><span class="hrf-peak-bar" style="width:${_powerPct(pk.power, data)}%"></span></span>
                    <span class="hrf-peak-power">${pk.power.toFixed(1)} dBm</span>
                </div>`
            ).join('');
        }

        function _powerPct(power, data) {
            if (data == null || data.powers == null || data.powers.length === 0) return 0;
            let minP = -100, maxP = -20;
            for (let i = 0; i < data.powers.length; i++) {
                if (data.powers[i] < minP) minP = data.powers[i];
                if (data.powers[i] > maxP) maxP = data.powers[i];
            }
            if (maxP - minP < 1) return 50;
            return Math.max(2, Math.min(100, ((power - minP) / (maxP - minP)) * 100));
        }

        // ── SIGNALS tab ────────────────────────────────────────────
        function renderSignals() {
            const filtered = (signals || []).filter(s => s.power_dbm >= signalThreshold);
            filtered.sort((a, b) => {
                const av = a[signalSortKey]; const bv = b[signalSortKey];
                if (av == null && bv == null) return 0;
                if (av == null) return 1;
                if (bv == null) return -1;
                return (av < bv ? -1 : av > bv ? 1 : 0) * signalSortDir;
            });

            body.innerHTML = `
                <div class="hrf-signals-header">
                    <span class="hrf-signal-count">${filtered.length} signal${filtered.length !== 1 ? 's' : ''} above threshold</span>
                    <span style="flex:1"></span>
                    <label class="hrf-lbl" style="font-size:0.65rem">THRESHOLD</label>
                    <input class="hrf-input hrf-input-sm" type="range" data-bind="threshold" min="-80" max="-30" value="${signalThreshold}" style="width:100px">
                    <span class="hrf-threshold-val" data-bind="threshold-val">${signalThreshold} dBm</span>
                </div>
                <div class="hrf-signal-table-wrap">
                    <table class="hrf-table">
                        <thead>
                            <tr>${SIG_COLS.map(c =>
                                `<th class="hrf-th" data-sort="${c.key}" style="width:${c.width};text-align:${c.align || 'left'}">${c.label}${signalSortKey === c.key ? (signalSortDir > 0 ? ' &#9650;' : ' &#9660;') : ''}</th>`
                            ).join('')}</tr>
                        </thead>
                        <tbody>
                            ${filtered.length === 0
                                ? '<tr><td colspan="5" class="hrf-td" style="text-align:center;color:#555;padding:20px">No signals detected</td></tr>'
                                : filtered.map(s => `<tr class="hrf-tr">
                                    <td class="hrf-td" style="text-align:right;color:#b060ff;font-weight:bold">${(s.freq_mhz || 0).toFixed(3)}</td>
                                    <td class="hrf-td" style="text-align:right;color:${_sigColor(s.power_dbm)}">${(s.power_dbm || 0).toFixed(1)}</td>
                                    <td class="hrf-td" style="text-align:right">${_esc(_timeStr(s.first_seen))}</td>
                                    <td class="hrf-td" style="text-align:right">${_esc(_timeStr(s.last_seen))}</td>
                                    <td class="hrf-td" style="text-align:right">${_esc(_durationStr(s.duration_s))}</td>
                                </tr>`).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            // Threshold slider
            const slider = body.querySelector('[data-bind="threshold"]');
            const valLabel = body.querySelector('[data-bind="threshold-val"]');
            slider?.addEventListener('input', () => {
                signalThreshold = parseInt(slider.value, 10);
                valLabel.textContent = signalThreshold + ' dBm';
                renderSignals();
            });

            // Column sorting
            body.querySelectorAll('.hrf-th[data-sort]').forEach(th => {
                th.addEventListener('click', () => {
                    const key = th.dataset.sort;
                    if (signalSortKey === key) signalSortDir *= -1;
                    else { signalSortKey = key; signalSortDir = -1; }
                    renderSignals();
                });
            });
        }

        function _sigColor(dbm) {
            if (dbm >= -30) return '#ff2a6d';
            if (dbm >= -50) return '#fcee0a';
            return '#05ffa1';
        }

        function _timeStr(ts) {
            if (ts == null) return '--';
            try {
                const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            } catch (_) { return '--'; }
        }

        function _durationStr(secs) {
            if (secs == null || secs < 0) return '--';
            if (secs < 60) return Math.round(secs) + 's';
            if (secs < 3600) return Math.floor(secs / 60) + 'm ' + Math.round(secs % 60) + 's';
            return Math.floor(secs / 3600) + 'h ' + Math.floor((secs % 3600) / 60) + 'm';
        }

        // ── CONFIG tab ─────────────────────────────────────────────
        function renderConfig() {
            const cfg = configData || {};

            body.innerHTML = `
                <div class="hrf-config-scroll">
                    <div class="hrf-section-label">DEVICE SETTINGS</div>
                    <div class="hrf-config-grid">
                        ${_cfgSlider('LNA Gain', 'lna_gain', cfg.lna_gain != null ? cfg.lna_gain : 16, 0, 40, 8, 'dB')}
                        ${_cfgSlider('VGA Gain', 'vga_gain', cfg.vga_gain != null ? cfg.vga_gain : 20, 0, 62, 2, 'dB')}
                        ${_cfgSlider('TX VGA Gain', 'tx_vga_gain', cfg.tx_vga_gain != null ? cfg.tx_vga_gain : 0, 0, 47, 1, 'dB')}
                    </div>

                    <div class="hrf-section-label">SAMPLE RATE</div>
                    <div class="hrf-config-grid">
                        <div class="hrf-cfg-row">
                            <span class="hrf-cfg-lbl">Sample Rate</span>
                            <select class="hrf-select" data-cfg="sample_rate">
                                ${[2, 4, 8, 10, 12.5, 16, 20].map(sr =>
                                    `<option value="${sr}"${cfg.sample_rate === sr ? ' selected' : ''}>${sr} MHz</option>`
                                ).join('')}
                            </select>
                        </div>
                    </div>

                    <div class="hrf-section-label">ANTENNA / BIAS TEE</div>
                    <div class="hrf-config-grid">
                        <div class="hrf-cfg-row">
                            <span class="hrf-cfg-lbl">Antenna Port</span>
                            <select class="hrf-select" data-cfg="antenna_port">
                                <option value="0"${cfg.antenna_port === 0 ? ' selected' : ''}>Port 0 (default)</option>
                                <option value="1"${cfg.antenna_port === 1 ? ' selected' : ''}>Port 1</option>
                            </select>
                        </div>
                        <div class="hrf-cfg-row">
                            <span class="hrf-cfg-lbl">Bias Tee</span>
                            <label class="hrf-toggle">
                                <input type="checkbox" data-cfg="bias_tee" ${cfg.bias_tee ? 'checked' : ''}>
                                <span class="hrf-toggle-slider"></span>
                            </label>
                        </div>
                    </div>

                    <div class="hrf-config-save-bar">
                        <button class="hrf-btn hrf-btn-save" data-action="save-config">SAVE CONFIGURATION</button>
                        <button class="hrf-btn" data-action="reset-config">RESET DEFAULTS</button>
                    </div>
                </div>
            `;

            // Bind slider events
            body.querySelectorAll('.hrf-cfg-slider').forEach(slider => {
                const valSpan = slider.parentElement.querySelector('.hrf-cfg-slider-val');
                slider.addEventListener('input', () => {
                    if (valSpan) valSpan.textContent = slider.value + ' ' + (slider.dataset.unit || '');
                });
            });

            body.querySelector('[data-action="save-config"]')?.addEventListener('click', async () => {
                const newCfg = {};
                body.querySelectorAll('[data-cfg]').forEach(el => {
                    const key = el.dataset.cfg;
                    if (el.type === 'checkbox') newCfg[key] = el.checked;
                    else if (el.type === 'range') newCfg[key] = parseFloat(el.value);
                    else newCfg[key] = isNaN(parseFloat(el.value)) ? el.value : parseFloat(el.value);
                });
                configData = Object.assign(configData, newCfg);
                try {
                    await fetch(API + '/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(newCfg),
                    });
                } catch (_) { /* network error */ }
            });

            body.querySelector('[data-action="reset-config"]')?.addEventListener('click', () => {
                configData = { lna_gain: 16, vga_gain: 20, tx_vga_gain: 0, sample_rate: 20, antenna_port: 0, bias_tee: false };
                renderConfig();
            });
        }

        function _cfgSlider(label, key, value, min, max, step, unit) {
            return `
                <div class="hrf-cfg-row">
                    <span class="hrf-cfg-lbl">${_esc(label)}</span>
                    <div style="display:flex;align-items:center;gap:8px;flex:1;justify-content:flex-end">
                        <input class="hrf-cfg-slider" data-cfg="${key}" data-unit="${_esc(unit)}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" style="width:140px">
                        <span class="hrf-cfg-slider-val" style="min-width:50px;text-align:right;font-size:0.72rem;color:#ccc">${value} ${_esc(unit)}</span>
                    </div>
                </div>
            `;
        }

        // ── FIRMWARE tab ───────────────────────────────────────────
        function renderFirmware() {
            const fw = firmwareInfo || {};
            const info = deviceInfo || {};

            body.innerHTML = `
                <div class="hrf-section-label">CURRENT FIRMWARE</div>
                <div class="hrf-info-grid">
                    ${_infoRow('Version', info.firmware_version || fw.firmware_version || '--')}
                    ${_infoRow('API Version', fw.api_version || '--')}
                    ${_infoRow('Board ID', info.board_id != null ? String(info.board_id) : '--')}
                </div>

                <div class="hrf-section-label">DEVICE HEALTH</div>
                <div class="hrf-info-grid">
                    ${_infoRow('USB Status', connected ? 'Connected' : 'Not connected')}
                    ${_infoRow('CPLD Status', fw.cpld_status || '--')}
                    ${_infoRow('Clock Source', fw.clock_source || 'Internal')}
                </div>

                <div class="hrf-section-label">FLASH FIRMWARE</div>
                <div style="padding:8px 10px">
                    <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px">
                        <input class="hrf-input" type="text" data-bind="fw-path" placeholder="/path/to/hackrf_one_usb.bin" style="flex:1">
                        <button class="hrf-btn hrf-btn-warn" data-action="flash-fw" ${connected ? '' : 'disabled'}>FLASH FIRMWARE</button>
                    </div>
                    <div class="hrf-flash-status" data-bind="flash-status" style="font-size:0.65rem;color:#888"></div>
                    <div style="font-size:0.6rem;color:#555;margin-top:8px">
                        Warning: Flashing firmware will temporarily disconnect the device.
                        Ensure the firmware binary is compatible with your HackRF hardware revision.
                    </div>
                </div>
            `;

            body.querySelector('[data-action="flash-fw"]')?.addEventListener('click', async () => {
                const pathInput = body.querySelector('[data-bind="fw-path"]');
                const statusEl = body.querySelector('[data-bind="flash-status"]');
                const fwPath = pathInput?.value?.trim();
                if (fwPath === undefined || fwPath === '') {
                    if (statusEl) statusEl.textContent = 'Please enter a firmware file path.';
                    return;
                }
                if (statusEl) { statusEl.textContent = 'Flashing...'; statusEl.style.color = '#fcee0a'; }
                const result = await flashFirmware(fwPath);
                if (result && result.success) {
                    if (statusEl) { statusEl.textContent = 'Flash complete. Device will reconnect.'; statusEl.style.color = '#05ffa1'; }
                    setTimeout(() => fetchAll(), 3000);
                } else {
                    const msg = (result && result.error) ? result.error : 'Flash failed.';
                    if (statusEl) { statusEl.textContent = msg; statusEl.style.color = '#ff2a6d'; }
                }
            });

            fetchFirmware();
        }

        // ── Shared helpers ─────────────────────────────────────────
        function _infoRow(label, value) {
            return `<div class="hrf-info-row"><span class="hrf-info-lbl">${_esc(label)}</span><span class="hrf-info-val">${_esc(String(value))}</span></div>`;
        }

        // ── Polling ────────────────────────────────────────────────
        const statusTimer = setInterval(() => {
            fetchStatus();
            if (sweepRunning) fetchSweepData();
        }, REFRESH_MS);

        let sweepTimer = setInterval(() => {
            if (sweepRunning && activeTab === 'spectrum') fetchSweepData();
        }, SWEEP_REFRESH_MS);

        // Initial load
        fetchAll();
        renderBody();

        // Save cleanup
        panel._hrfCleanup = {
            timers: [statusTimer, sweepTimer],
        };
    },

    unmount(bodyEl, panel) {
        if (panel._hrfCleanup) {
            (panel._hrfCleanup.timers || []).forEach(t => clearInterval(t));
            panel._hrfCleanup = null;
        }
    },
};

// ── Styles ─────────────────────────────────────────────────────────
function _injectStyles() {
    if (document.getElementById('hrf-styles')) return;
    const s = document.createElement('style');
    s.id = 'hrf-styles';
    s.textContent = `
        /* ── Spinner ────────────────────────────────────────────── */
        @keyframes hrf-spin { to { transform:rotate(360deg); } }
        .hrf-spinner { width:16px; height:16px; border:2px solid #333; border-top-color:#b060ff; border-radius:50%; animation:hrf-spin 0.8s linear infinite; flex-shrink:0; }

        /* ── Live dot pulse ─────────────────────────────────────── */
        @keyframes hrf-pulse { 0%,100% { opacity:1; } 50% { opacity:0.3; } }
        .hrf-live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:#ff2a6d; animation:hrf-pulse 1s ease-in-out infinite; margin-right:4px; }
        .hrf-sweep-live { font-size:0.65rem; color:#ff2a6d; font-weight:bold; letter-spacing:1px; display:flex; align-items:center; }

        /* ── Connection bar ─────────────────────────────────────── */
        .hrf-conn-bar { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #1a1a2e; background:#0a0a0f; flex-shrink:0; }
        .hrf-dot { width:10px; height:10px; border-radius:50%; background:#444; flex-shrink:0; transition:background 0.3s; cursor:help; }
        .hrf-dot-on { background:#05ffa1; box-shadow:0 0 8px #05ffa188; }
        .hrf-conn-label { font-size:0.72rem; color:#888; font-weight:bold; letter-spacing:1px; }
        .hrf-conn-device { font-size:0.72rem; color:#ccc; }
        .hrf-conn-fw { font-size:0.65rem; color:#b060ff; }

        /* ── Tab bar ────────────────────────────────────────────── */
        .hrf-tabs { display:flex; border-bottom:1px solid #1a1a2e; flex-shrink:0; background:#0e0e14; }
        .hrf-tab { flex:1; padding:7px 2px; background:none; border:none; border-bottom:2px solid transparent; color:#666; font-family:inherit; font-size:0.65rem; cursor:pointer; letter-spacing:0.5px; transition:color 0.15s,border-color 0.15s,background 0.15s; white-space:nowrap; }
        .hrf-tab:hover { color:#aaa; background:rgba(176,96,255,0.04); }
        .hrf-tab-active { color:#b060ff; border-bottom-color:#b060ff; }

        /* ── Body ───────────────────────────────────────────────── */
        .hrf-body { flex:1; overflow-y:auto; min-height:0; display:flex; flex-direction:column; }

        /* ── Buttons ────────────────────────────────────────────── */
        .hrf-btn { font-family:inherit; font-size:0.7rem; padding:4px 10px; background:rgba(176,96,255,0.06); border:1px solid rgba(176,96,255,0.2); color:#b060ff; border-radius:3px; cursor:pointer; transition:background 0.15s,filter 0.15s,box-shadow 0.15s; }
        .hrf-btn:hover { background:rgba(176,96,255,0.15); filter:brightness(1.2); box-shadow:0 0 6px rgba(176,96,255,0.15); }
        .hrf-btn:disabled { opacity:0.4; cursor:not-allowed; filter:none; box-shadow:none; }
        .hrf-btn-action { background:rgba(0,240,255,0.06); border-color:rgba(0,240,255,0.2); color:#00f0ff; }
        .hrf-btn-action:hover { background:rgba(0,240,255,0.15); }
        .hrf-btn-preset { font-size:0.65rem; padding:3px 8px; }
        .hrf-btn-start { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .hrf-btn-start:hover { background:rgba(5,255,161,0.2); }
        .hrf-btn-stop { background:rgba(255,42,109,0.08); border-color:rgba(255,42,109,0.2); color:#ff2a6d; }
        .hrf-btn-stop:hover { background:rgba(255,42,109,0.15); }
        .hrf-btn-save { background:rgba(5,255,161,0.1); border-color:rgba(5,255,161,0.3); color:#05ffa1; }
        .hrf-btn-save:hover { background:rgba(5,255,161,0.2); }
        .hrf-btn-warn { background:rgba(255,42,109,0.08); border-color:rgba(255,42,109,0.2); color:#ff2a6d; }
        .hrf-btn-warn:hover { background:rgba(255,42,109,0.15); }

        /* ── Section labels ─────────────────────────────────────── */
        .hrf-section-label { font-size:0.65rem; color:#b060ff88; letter-spacing:2px; padding:6px 10px 2px; text-transform:uppercase; }

        /* ── Radio tab ──────────────────────────────────────────── */
        .hrf-radio-status { display:flex; justify-content:center; padding:16px 10px 8px; }
        .hrf-radio-indicator { display:flex; flex-direction:column; align-items:center; gap:8px; padding:16px 24px; border:1px solid #1a1a2e; border-radius:8px; }
        .hrf-radio-dot-big { width:20px; height:20px; border-radius:50%; }
        .hrf-radio-status-text { font-size:0.8rem; font-weight:bold; letter-spacing:2px; }
        .hrf-radio-actions { display:flex; gap:6px; padding:8px 10px; flex-wrap:wrap; }

        /* ── Info grid ──────────────────────────────────────────── */
        .hrf-info-grid { padding:0 10px; }
        .hrf-info-row { display:flex; justify-content:space-between; padding:3px 0; border-bottom:1px solid #ffffff06; font-size:0.72rem; }
        .hrf-info-lbl { color:#888; font-size:0.65rem; min-width:100px; }
        .hrf-info-val { color:#ccc; text-align:right; }

        /* ── Spectrum tab ───────────────────────────────────────── */
        .hrf-spectrum-controls { padding:8px 10px; border-bottom:1px solid #1a1a2e; }
        .hrf-spectrum-row { display:flex; align-items:center; gap:6px; margin-bottom:6px; flex-wrap:wrap; }
        .hrf-spectrum-canvas-wrap { padding:8px 10px; background:#0a0a0f; }
        .hrf-spectrum-canvas-wrap canvas { width:100%; border:1px solid #1a1a2e; border-radius:2px; }

        /* ── Peak list ──────────────────────────────────────────── */
        .hrf-peak-list { padding:4px 10px; max-height:150px; overflow-y:auto; }
        .hrf-peak-row { display:flex; align-items:center; gap:8px; padding:3px 0; border-bottom:1px solid #ffffff06; font-size:0.72rem; }
        .hrf-peak-freq { color:#b060ff; min-width:110px; font-weight:bold; }
        .hrf-peak-bar-wrap { flex:1; height:6px; background:#1a1a2e; border-radius:3px; overflow:hidden; }
        .hrf-peak-bar { height:100%; background:linear-gradient(90deg,#05ffa1,#fcee0a,#ff2a6d); border-radius:3px; transition:width 0.3s; }
        .hrf-peak-power { color:#ccc; min-width:70px; text-align:right; font-size:0.65rem; }

        /* ── Signals tab ────────────────────────────────────────── */
        .hrf-signals-header { display:flex; align-items:center; gap:8px; padding:6px 10px; border-bottom:1px solid #1a1a2e; flex-shrink:0; }
        .hrf-signal-count { font-size:0.72rem; color:#888; }
        .hrf-threshold-val { font-size:0.65rem; color:#b060ff; min-width:55px; text-align:right; }
        .hrf-signal-table-wrap { flex:1; overflow-y:auto; min-height:0; }

        /* ── Table ──────────────────────────────────────────────── */
        .hrf-table { width:100%; border-collapse:collapse; font-size:0.72rem; }
        .hrf-th { padding:4px 6px; color:#888; border-bottom:1px solid #1a1a2e; cursor:pointer; user-select:none; white-space:nowrap; font-size:0.65rem; letter-spacing:0.5px; }
        .hrf-th:hover { color:#b060ff; }
        .hrf-td { padding:3px 6px; color:#ccc; border-bottom:1px solid #ffffff06; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .hrf-tr:hover .hrf-td { background:rgba(176,96,255,0.03); }

        /* ── Config tab ─────────────────────────────────────────── */
        .hrf-config-scroll { flex:1; overflow-y:auto; min-height:0; padding-bottom:8px; }
        .hrf-config-grid { padding:0 10px; }
        .hrf-cfg-row { display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid #ffffff06; font-size:0.72rem; align-items:center; transition:background 0.15s; }
        .hrf-cfg-row:hover { background:rgba(176,96,255,0.02); }
        .hrf-cfg-lbl { color:#888; font-size:0.65rem; min-width:100px; flex-shrink:0; }
        .hrf-cfg-slider { accent-color:#b060ff; }
        .hrf-config-save-bar { display:flex; gap:8px; padding:12px 10px; border-top:1px solid #1a1a2e; margin-top:8px; }

        /* ── Inputs ─────────────────────────────────────────────── */
        .hrf-input { background:#0a0a0f; border:1px solid #1a1a2e; color:#ccc; padding:5px 8px; font-family:inherit; font-size:0.72rem; border-radius:3px; outline:none; }
        .hrf-input:focus { border-color:#b060ff66; }
        .hrf-input-sm { width:70px; padding:3px 6px; font-size:0.7rem; }
        .hrf-select { background:#0e0e14; border:1px solid #1a1a2e; color:#ccc; font-family:inherit; font-size:0.7rem; padding:3px 6px; border-radius:3px; }
        .hrf-lbl { font-size:0.65rem; color:#888; }

        /* ── Toggle switch ──────────────────────────────────────── */
        .hrf-toggle { position:relative; display:inline-block; width:32px; height:18px; flex-shrink:0; }
        .hrf-toggle input { opacity:0; width:0; height:0; }
        .hrf-toggle-slider { position:absolute; cursor:pointer; top:0; left:0; right:0; bottom:0; background:#333; transition:0.2s; border-radius:18px; }
        .hrf-toggle-slider::before { content:""; position:absolute; height:14px; width:14px; left:2px; bottom:2px; background:#888; transition:0.2s; border-radius:50%; }
        .hrf-toggle input:checked + .hrf-toggle-slider { background:rgba(176,96,255,0.3); }
        .hrf-toggle input:checked + .hrf-toggle-slider::before { transform:translateX(14px); background:#b060ff; }
    `;
    document.head.appendChild(s);
}
