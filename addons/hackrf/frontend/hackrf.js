// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// HACKRF SDR — Full-featured HackRF One management panel.
// Tabs: RADIO | SPECTRUM | SIGNALS | DEVICES | AIRCRAFT | CONFIG | FIRMWARE
// Polls device status on open; auto-refreshes sweep data while running.

import { _esc } from '/static/js/command/panel-utils.js';

const API = '/api/addons/hackrf';
const REFRESH_MS = 5000;          // Status poll (not spectrum)
const SWEEP_REFRESH_MS = 250;     // Spectrum data poll (fast for smooth waterfall)

// ── Tab definitions ────────────────────────────────────────────────
const TABS = [
    { id: 'radio',    label: 'RADIO',    tip: 'Device info, quick actions, presets' },
    { id: 'spectrum', label: 'SPECTRUM', tip: 'Frequency sweep and waterfall display' },
    { id: 'signals',  label: 'SIGNALS',  tip: 'Detected signals above threshold' },
    { id: 'devices',  label: 'DEVICES',  tip: 'ISM band devices detected by rtl_433' },
    { id: 'aircraft', label: 'AIRCRAFT', tip: 'ADS-B aircraft tracking' },
    { id: 'config',   label: 'CONFIG',   tip: 'Gain, sample rate, antenna settings' },
    { id: 'firmware', label: 'FIRMWARE', tip: 'Firmware version and flashing' },
];

// ── Frequency presets ──────────────────────────────────────────────
const PRESETS = [
    { label: 'FULL SWEEP',    startMhz: 1,     endMhz: 6000, color: '#888', desc: 'Complete 1MHz-6GHz scan' },
    { label: 'VHF Low',       startMhz: 30,    endMhz: 88,   color: '#ff8800', desc: 'Emergency, business, government' },
    { label: 'FM Radio',      startMhz: 88,    endMhz: 108,  color: '#05ffa1', desc: 'Commercial FM broadcast' },
    { label: 'Aircraft VHF',  startMhz: 108,   endMhz: 137,  color: '#00d4ff', desc: 'Air traffic control, ACARS' },
    { label: 'VHF Marine',    startMhz: 156,   endMhz: 163,  color: '#0088ff', desc: 'Marine radio, channel 16' },
    { label: 'NOAA Weather',  startMhz: 162,   endMhz: 163,  color: '#00ccff', desc: 'NOAA weather broadcasts' },
    { label: 'TPMS 315MHz',   startMhz: 314,   endMhz: 316,  color: '#ff2a6d', desc: 'Tire pressure sensors (US)' },
    { label: 'ISM 433MHz',    startMhz: 430,   endMhz: 440,  color: '#b060ff', desc: 'TPMS EU, remotes, weather stations' },
    { label: 'UHF TV',        startMhz: 470,   endMhz: 698,  color: '#886600', desc: 'Digital TV broadcasts' },
    { label: 'Cellular 700',  startMhz: 698,   endMhz: 806,  color: '#ff8844', desc: 'LTE Band 12/13/17' },
    { label: 'Cellular 850',  startMhz: 824,   endMhz: 894,  color: '#ff6622', desc: 'LTE Band 5/26' },
    { label: 'LoRa/ISM 915',  startMhz: 902,   endMhz: 928,  color: '#00f0ff', desc: 'Meshtastic, LoRaWAN, Zigbee' },
    { label: 'ADS-B 1090',    startMhz: 1085,  endMhz: 1095, color: '#ff2a6d', desc: 'Aircraft transponders' },
    { label: 'GPS L1',        startMhz: 1574,  endMhz: 1576, color: '#05ffa1', desc: 'GPS navigation signal' },
    { label: 'Cellular 1900', startMhz: 1850,  endMhz: 1990, color: '#ff4400', desc: 'PCS/LTE Band 2/25' },
    { label: 'WiFi 2.4GHz',   startMhz: 2400,  endMhz: 2500, color: '#fcee0a', desc: 'WiFi, Bluetooth, Zigbee, microwave' },
    { label: 'WiFi 5GHz',     startMhz: 5100,  endMhz: 5900, color: '#ffcc00', desc: 'WiFi 5GHz channels' },
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
            <div class="hrf-status-bar" data-bind="status-bar">
                <span class="hrf-status-activity" data-bind="activity">IDLE</span>
                <span class="hrf-status-detail" data-bind="detail"></span>
                <span style="flex:1"></span>
                <span class="hrf-status-stats" data-bind="stats"></span>
            </div>
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
        const statusActivity = bodyEl.querySelector('[data-bind="activity"]');
        const statusDetail = bodyEl.querySelector('[data-bind="detail"]');
        const statusStats = bodyEl.querySelector('[data-bind="stats"]');
        const commandLog = [];  // Recent commands/events for status bar

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
        let waterfallHistory = [];  // array of power arrays, newest first
        const WATERFALL_MAX_ROWS = 60;

        // DEVICES tab state
        let rtl433Devices = [];
        let rtl433Running = false;
        let rtl433Freq = '433.92';
        let devicesTimer = null;

        // AIRCRAFT tab state
        let adsbAircraft = [];
        let adsbRunning = false;
        let aircraftTimer = null;

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

        // ── Status bar update ────────────────────────────────────
        function _updateStatusBar() {
            if (!statusActivity) return;
            const sweep = deviceStatus.sweep || {};
            const recv = deviceStatus.receiver || {};

            if (sweepRunning || sweep.running) {
                statusActivity.textContent = 'SWEEPING';
                statusActivity.className = 'hrf-status-activity sweep';
                const freq = `${sweep.freq_start_mhz || '?'}-${sweep.freq_end_mhz || '?'} MHz`;
                statusDetail.textContent = `${freq} | bin ${(sweep.bin_width || 0) / 1000}kHz | ${sweep.sweep_count || 0} sweeps`;
                statusStats.textContent = `${(sweep.measurement_count || 0).toLocaleString()} measurements`;
            } else if (recv.running) {
                statusActivity.textContent = 'RECEIVING';
                statusActivity.className = 'hrf-status-activity sweep';
                statusDetail.textContent = `${recv.freq_mhz || '?'} MHz | ${recv.sample_rate / 1e6 || '?'} Msps`;
                statusStats.textContent = `LNA:${recv.lna_gain}dB VGA:${recv.vga_gain}dB`;
            } else if (connected) {
                statusActivity.textContent = 'IDLE';
                statusActivity.className = 'hrf-status-activity idle';
                statusDetail.textContent = commandLog.length > 0 ? commandLog[commandLog.length - 1] : 'Ready — select a preset or start a sweep';
                statusStats.textContent = deviceInfo.serial ? `SN:${deviceInfo.serial.slice(-8)}` : '';
            } else {
                statusActivity.textContent = 'OFFLINE';
                statusActivity.className = 'hrf-status-activity error';
                statusDetail.textContent = 'HackRF not detected';
                statusStats.textContent = '';
            }
        }

        function _logCommand(msg) {
            const ts = new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
            commandLog.push(`[${ts}] ${msg}`);
            if (commandLog.length > 50) commandLog.shift();
            _updateStatusBar();
        }

        // ── Data fetching ──────────────────────────────────────────
        async function fetchStatus() {
            try {
                const r = await fetch(API + '/status');
                if (r.ok) {
                    const d = await r.json();
                    deviceStatus = d;
                    updateConnection(null, d);
                    // Sync sweepRunning from backend status
                    const backendSweeping = d.sweep && (d.sweep.running || d.sweep.sweep_count > 0);
                    if (backendSweeping && !sweepRunning) {
                        sweepRunning = true;  // Backend started a sweep we didn't know about
                    }
                    _updateStatusBar();
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
                const r = await fetch(API + '/sweep/data?max_points=600');
                if (r.ok) {
                    const d = await r.json();
                    // Transform API format {data: [{freq_hz, power_dbm}]} to canvas format {freqs, powers}
                    const rawData = d.data || d.points || [];
                    const freqs = rawData.map(p => p.freq_hz || p.freq || 0);
                    const powers = rawData.map(p => p.power_dbm || p.power || -100);
                    sweepData = { freqs, powers, count: rawData.length, status: d.status || {} };
                    // Trust data presence over status flag — backend status can lag
                    const statusRunning = (d.status && d.status.running) || d.running || false;
                    const hasNewData = rawData.length > 0;
                    sweepRunning = statusRunning || hasNewData;
                    if (d.signals) signals = d.signals;
                    // Push new row into waterfall history
                    if (powers.length > 0) {
                        waterfallHistory.unshift(powers.slice());
                        if (waterfallHistory.length > WATERFALL_MAX_ROWS) {
                            waterfallHistory.length = WATERFALL_MAX_ROWS;
                        }
                    }
                    if (activeTab === 'spectrum') {
                        // Update canvases in-place without full re-render
                        const specCanvas = body.querySelector('[data-bind="spectrum-canvas"]');
                        const wfCanvas = body.querySelector('[data-bind="waterfall-canvas"]');
                        const peakList = body.querySelector('[data-bind="peak-list"]');
                        if (specCanvas) _drawSpectrum(specCanvas, sweepData);
                        if (wfCanvas) _drawWaterfall(wfCanvas, waterfallHistory);
                        if (peakList) _renderPeaks(peakList, sweepData);
                    } else if (activeTab === 'signals') {
                        renderBody();
                    }
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
            _logCommand(`Starting sweep ${startMhz}-${endMhz} MHz, bin ${binWidth/1000}kHz`);
            try {
                const r = await fetch(API + '/sweep/start', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ freq_start: startMhz, freq_end: endMhz, bin_width: binWidth }),
                });
                if (r.ok) {
                    sweepRunning = true;
                    _logCommand(`Sweep running: ${startMhz}-${endMhz} MHz`);
                    renderBody();
                    // Force immediate data fetch after a short delay
                    setTimeout(() => fetchSweepData(), 1000);
                    setTimeout(() => fetchSweepData(), 2000);
                    setTimeout(() => fetchSweepData(), 3000);
                } else {
                    _logCommand(`Sweep start failed: HTTP ${r.status}`);
                }
            } catch (e) { _logCommand(`Sweep start error: ${e.message}`); }
        }

        async function stopSweep() {
            _logCommand('Stopping sweep...');
            try {
                const r = await fetch(API + '/sweep/stop', { method: 'POST' });
                if (r.ok) {
                    const d = await r.json();
                    sweepRunning = false;
                    _logCommand(`Sweep stopped: ${d.sweep_count || 0} sweeps completed`);
                    renderBody();
                }
            } catch (e) { _logCommand(`Stop error: ${e.message}`); }
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
            // Clear tab-specific timers when switching away
            if (activeTab !== 'devices' && devicesTimer) { clearInterval(devicesTimer); devicesTimer = null; }
            if (activeTab !== 'aircraft' && aircraftTimer) { clearInterval(aircraftTimer); aircraftTimer = null; }
            switch (activeTab) {
                case 'radio':    renderRadio(); break;
                case 'spectrum': renderSpectrum(); break;
                case 'signals':  renderSignals(); break;
                case 'devices':  renderDevices(); break;
                case 'aircraft': renderAircraft(); break;
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
                    ${PRESETS.map(p => `<button class="hrf-btn hrf-btn-preset" data-preset-start="${p.startMhz}" data-preset-end="${p.endMhz}" style="border-color:${p.color}44;color:${p.color}" title="${_esc(p.desc)}">${_esc(p.label)}</button>`).join('')}
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

                <div class="hrf-section-label">SPECTRUM DISPLAY <span class="hrf-spectrum-readout" data-bind="crosshair-readout" style="float:right;color:#b060ff;font-size:0.7rem"></span></div>
                <div class="hrf-spectrum-canvas-wrap" style="position:relative;cursor:crosshair">
                    <canvas data-bind="spectrum-canvas" width="600" height="200" style="display:block"></canvas>
                    <canvas data-bind="crosshair-canvas" width="600" height="200" style="position:absolute;top:0;left:0;pointer-events:none"></canvas>
                </div>

                <div class="hrf-section-label">WATERFALL</div>
                <div class="hrf-spectrum-canvas-wrap" style="position:relative">
                    <canvas data-bind="waterfall-canvas" width="600" height="150" style="display:block"></canvas>
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

            const waterfallCanvas = body.querySelector('[data-bind="waterfall-canvas"]');
            const crosshairCanvas = body.querySelector('[data-bind="crosshair-canvas"]');
            const readout = body.querySelector('[data-bind="crosshair-readout"]');

            // Interactive crosshair on spectrum canvas
            const canvasWrap = canvas?.parentElement;
            if (canvasWrap && crosshairCanvas) {
                canvasWrap.addEventListener('mousemove', (e) => {
                    const rect = canvas.getBoundingClientRect();
                    const x = e.clientX - rect.left;
                    const y = e.clientY - rect.top;
                    const w = canvas.width;
                    const h = canvas.height;

                    // Draw crosshair on overlay canvas
                    const ctx = crosshairCanvas.getContext('2d');
                    ctx.clearRect(0, 0, w, h);
                    ctx.strokeStyle = 'rgba(176, 96, 255, 0.6)';
                    ctx.lineWidth = 1;
                    ctx.setLineDash([4, 4]);
                    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
                    ctx.setLineDash([]);

                    // Calculate frequency and power at cursor
                    if (sweepData && sweepData.freqs && sweepData.freqs.length > 0) {
                        const idx = Math.floor((x / w) * sweepData.freqs.length);
                        const freq = sweepData.freqs[Math.min(idx, sweepData.freqs.length - 1)];
                        const power = sweepData.powers[Math.min(idx, sweepData.powers.length - 1)];
                        const freqMhz = (freq / 1e6).toFixed(2);
                        const powerStr = power.toFixed(1);
                        if (readout) readout.textContent = `${freqMhz} MHz | ${powerStr} dBm`;

                        // Draw value label at cursor
                        ctx.fillStyle = 'rgba(10,10,15,0.85)';
                        ctx.fillRect(x + 8, y - 20, 110, 18);
                        ctx.fillStyle = '#b060ff';
                        ctx.font = '10px monospace';
                        ctx.fillText(`${freqMhz} MHz ${powerStr}dB`, x + 12, y - 7);
                    }
                });
                canvasWrap.addEventListener('mouseleave', () => {
                    crosshairCanvas.getContext('2d').clearRect(0, 0, crosshairCanvas.width, crosshairCanvas.height);
                    if (readout) readout.textContent = '';
                });
            }

            // Initial draw
            if (sweepData && sweepData.powers && sweepData.powers.length > 0) {
                waterfallHistory.unshift(sweepData.powers.slice());
                if (waterfallHistory.length > WATERFALL_MAX_ROWS) {
                    waterfallHistory.length = WATERFALL_MAX_ROWS;
                }
            }
            _drawSpectrum(canvas, sweepData);
            _drawWaterfall(waterfallCanvas, waterfallHistory);
            _renderPeaks(peakList, sweepData);
        }

        function _drawSpectrum(canvas, data) {
            if (!canvas) return;
            const ctx = canvas.getContext('2d');

            // Scale canvas to container width for responsive layout
            const container = canvas.parentElement;
            if (container) {
                const cw = container.clientWidth || 600;
                if (canvas.width !== cw) { canvas.width = cw; }
                // Also resize crosshair canvas
                const crosshair = container.querySelector('[data-bind="crosshair-canvas"]');
                if (crosshair && crosshair.width !== cw) crosshair.width = cw;
            }

            const w = canvas.width;
            const h = canvas.height;
            const MARGIN_LEFT = 40;  // Y-axis labels
            const MARGIN_BOTTOM = 18;  // X-axis labels
            const plotW = w - MARGIN_LEFT;
            const plotH = h - MARGIN_BOTTOM;

            // Clear
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            if (data == null || data.freqs == null || data.freqs.length === 0) {
                ctx.fillStyle = '#555';
                ctx.font = '12px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('No sweep data — click START SWEEP or a preset', w / 2, h / 2);
                return;
            }

            const freqs = data.freqs;
            const powers = data.powers;
            const n = freqs.length;
            if (n === 0) return;

            const freqMin = freqs[0];
            const freqMax = freqs[n - 1];
            let minP = -90, maxP = -10;
            for (let i = 0; i < n; i++) {
                if (powers[i] > maxP) maxP = powers[i];
            }
            if (maxP < -60) maxP = -30;
            const powerRange = maxP - minP;

            // Grid + Y-axis labels (power in dBm)
            ctx.strokeStyle = '#1a1a2e';
            ctx.lineWidth = 1;
            ctx.font = '9px monospace';
            ctx.fillStyle = '#555';
            ctx.textAlign = 'right';
            for (let db = minP; db <= maxP; db += 10) {
                const y = plotH - ((db - minP) / powerRange) * plotH;
                ctx.beginPath(); ctx.moveTo(MARGIN_LEFT, y); ctx.lineTo(w, y); ctx.stroke();
                ctx.fillText(db + '', MARGIN_LEFT - 3, y + 3);
            }

            // X-axis labels (frequency in MHz)
            ctx.textAlign = 'center';
            const freqSpan = (freqMax - freqMin) / 1e6;
            const tickCount = Math.min(10, Math.max(3, Math.floor(plotW / 60)));
            for (let i = 0; i <= tickCount; i++) {
                const frac = i / tickCount;
                const x = MARGIN_LEFT + frac * plotW;
                const freq = freqMin + frac * (freqMax - freqMin);
                ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, plotH); ctx.stroke();
                ctx.fillText((freq / 1e6).toFixed(freqSpan > 100 ? 0 : 1), x, h - 3);
            }

            // Spectrum fill (gradient bars)
            const barW = Math.max(1, plotW / n);
            for (let i = 0; i < n; i++) {
                const pNorm = Math.max(0, Math.min(1, (powers[i] - minP) / powerRange));
                const barH = Math.max(1, pNorm * plotH);
                const x = MARGIN_LEFT + (i / n) * plotW;

                // Smooth gradient: dark blue → green → yellow → red
                let r, g, b;
                if (pNorm < 0.33) {
                    const t = pNorm / 0.33;
                    r = 0; g = Math.round(t * 200); b = Math.round(80 - t * 80);
                } else if (pNorm < 0.66) {
                    const t = (pNorm - 0.33) / 0.33;
                    r = Math.round(t * 252); g = Math.round(200 + t * 38); b = 0;
                } else {
                    const t = (pNorm - 0.66) / 0.34;
                    r = 255; g = Math.round(238 - t * 196); b = Math.round(t * 109);
                }

                ctx.fillStyle = `rgb(${r},${g},${b})`;
                ctx.fillRect(x, plotH - barH, barW + 0.5, barH);
            }

            // Axis labels
            ctx.fillStyle = '#666';
            ctx.font = '9px monospace';
            ctx.textAlign = 'left';
            ctx.fillText('dBm', 2, 10);
            ctx.textAlign = 'right';
            ctx.fillText('MHz', w - 2, h - 3);

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

        // ── Waterfall helpers ──────────────────────────────────────
        function _powerColor(norm) {
            // Blue (weak) -> Green -> Yellow -> Red (strong)
            if (norm < 0.25) {
                const t = norm / 0.25;
                const r = 0;
                const g = Math.round(t * 200);
                const b = Math.round(80 + (1 - t) * 175);
                return `rgb(${r},${g},${b})`;
            } else if (norm < 0.5) {
                const t = (norm - 0.25) / 0.25;
                const r = Math.round(t * 100);
                const g = Math.round(200 + t * 55);
                const b = Math.round(80 * (1 - t));
                return `rgb(${r},${g},${b})`;
            } else if (norm < 0.75) {
                const t = (norm - 0.5) / 0.25;
                const r = Math.round(100 + t * 152);
                const g = Math.round(255 - t * 17);
                const b = Math.round(t * 10);
                return `rgb(${r},${g},${b})`;
            } else {
                const t = (norm - 0.75) / 0.25;
                const r = 255;
                const g = Math.round(238 - t * 238);
                const b = Math.round(10 + t * 99);
                return `rgb(${r},${g},${b})`;
            }
        }

        function _drawWaterfall(canvas, history) {
            if (canvas == null) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;

            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            const rows = history.length;
            if (rows === 0) {
                ctx.fillStyle = '#555';
                ctx.font = '11px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('Waterfall history builds as sweep runs', w / 2, h / 2);
                return;
            }

            const cols = history[0].length;
            if (cols === 0) return;
            const cellW = w / cols;
            const cellH = h / Math.min(rows, WATERFALL_MAX_ROWS);

            for (let row = 0; row < rows; row++) {
                const rowData = history[row];
                for (let col = 0; col < rowData.length; col++) {
                    const power = rowData[col]; // dBm value
                    const norm = Math.max(0, Math.min(1, (power + 80) / 60)); // -80 to -20 dBm range
                    ctx.fillStyle = _powerColor(norm);
                    ctx.fillRect(col * cellW, row * cellH, cellW + 1, cellH + 1);
                }
            }
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

        // ── DEVICES tab (rtl_433) ─────────────────────────────────
        function renderDevices() {
            const now = Date.now() / 1000;
            const tpmsDevices = rtl433Devices.filter(d => (d.protocol || '').toLowerCase().includes('tpms') || (d.model || '').toLowerCase().includes('tpms'));
            const otherDevices = rtl433Devices.filter(d => tpmsDevices.indexOf(d) === -1);

            body.innerHTML = `
                <div class="hrf-devices-controls">
                    <div class="hrf-spectrum-row" style="gap:8px">
                        <button class="hrf-btn hrf-btn-start" data-action="rtl433-start" ${rtl433Running ? 'disabled' : ''}>START MONITORING</button>
                        <button class="hrf-btn hrf-btn-stop" data-action="rtl433-stop" ${rtl433Running ? '' : 'disabled'}>STOP MONITORING</button>
                        ${rtl433Running ? '<span class="hrf-sweep-live"><span class="hrf-live-dot"></span> MONITORING</span>' : ''}
                        <span style="flex:1"></span>
                        <label class="hrf-lbl">FREQ</label>
                        <select class="hrf-select" data-bind="rtl433-freq">
                            <option value="315"${rtl433Freq === '315' ? ' selected' : ''}>315 MHz (US)</option>
                            <option value="433.92"${rtl433Freq === '433.92' ? ' selected' : ''}>433.92 MHz (EU)</option>
                        </select>
                    </div>
                    <div style="font-size:0.65rem;color:#888;padding:2px 0">${rtl433Devices.length} device${rtl433Devices.length !== 1 ? 's' : ''} detected</div>
                </div>

                <div class="hrf-section-label">DECODED DEVICES</div>
                <div class="hrf-signal-table-wrap">
                    <table class="hrf-table">
                        <thead>
                            <tr>
                                <th class="hrf-th" style="width:90px">PROTOCOL</th>
                                <th class="hrf-th" style="width:80px">DEVICE ID</th>
                                <th class="hrf-th" style="width:120px">MODEL</th>
                                <th class="hrf-th">LAST DATA</th>
                                <th class="hrf-th" style="width:80px;text-align:right">LAST SEEN</th>
                                <th class="hrf-th" style="width:50px;text-align:right">EVENTS</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${otherDevices.length === 0
                                ? '<tr><td colspan="6" class="hrf-td" style="text-align:center;color:#555;padding:20px">No devices detected -- start monitoring to scan ISM band</td></tr>'
                                : otherDevices.map(d => {
                                    const age = now - (d.last_seen || 0);
                                    const recencyColor = age < 10 ? '#05ffa1' : age < 60 ? '#fcee0a' : '#555';
                                    return `<tr class="hrf-tr">
                                        <td class="hrf-td" style="color:#b060ff">${_esc(d.protocol || '--')}</td>
                                        <td class="hrf-td" style="color:#00f0ff">${_esc(String(d.device_id != null ? d.device_id : '--'))}</td>
                                        <td class="hrf-td">${_esc(d.model || '--')}</td>
                                        <td class="hrf-td" style="font-size:0.65rem;max-width:180px;overflow:hidden;text-overflow:ellipsis">${_esc(_deviceDataStr(d))}</td>
                                        <td class="hrf-td" style="text-align:right;color:${recencyColor}">${_esc(_agoStr(age))}</td>
                                        <td class="hrf-td" style="text-align:right">${d.event_count || 1}</td>
                                    </tr>`;
                                }).join('')}
                        </tbody>
                    </table>
                </div>

                ${tpmsDevices.length > 0 ? `
                    <div class="hrf-section-label">TPMS SENSORS</div>
                    <div class="hrf-tpms-grid">
                        ${tpmsDevices.map(d => {
                            const pressure = d.pressure_kPa != null ? (d.pressure_kPa * 0.145038).toFixed(1) + ' PSI' : d.pressure_PSI != null ? d.pressure_PSI.toFixed(1) + ' PSI' : '--';
                            const temp = d.temperature_C != null ? d.temperature_C.toFixed(0) + ' C' : '--';
                            const age = now - (d.last_seen || 0);
                            const recencyColor = age < 10 ? '#05ffa1' : age < 60 ? '#fcee0a' : '#555';
                            return `<div class="hrf-tpms-card">
                                <div class="hrf-tpms-id" style="color:#00f0ff">${_esc(String(d.device_id != null ? d.device_id : '--'))}</div>
                                <div class="hrf-tpms-pressure">${_esc(pressure)}</div>
                                <div class="hrf-tpms-temp">${_esc(temp)}</div>
                                <div class="hrf-tpms-age" style="color:${recencyColor}">${_esc(_agoStr(age))}</div>
                            </div>`;
                        }).join('')}
                    </div>
                ` : ''}
            `;

            body.querySelector('[data-bind="rtl433-freq"]')?.addEventListener('change', (e) => {
                rtl433Freq = e.target.value;
            });

            body.querySelector('[data-action="rtl433-start"]')?.addEventListener('click', async () => {
                try {
                    const r = await fetch(API + '/rtl433/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ frequency: parseFloat(rtl433Freq) }),
                    });
                    if (r.ok) { rtl433Running = true; renderDevices(); }
                } catch (_) { /* network error */ }
            });

            body.querySelector('[data-action="rtl433-stop"]')?.addEventListener('click', async () => {
                try {
                    const r = await fetch(API + '/rtl433/stop', { method: 'POST' });
                    if (r.ok) { rtl433Running = false; renderDevices(); }
                } catch (_) { /* network error */ }
            });

            // Start auto-refresh for devices tab
            if (devicesTimer == null) {
                devicesTimer = setInterval(async () => {
                    if (activeTab !== 'devices') return;
                    try {
                        const r = await fetch(API + '/rtl433/devices');
                        if (r.ok) {
                            const d = await r.json();
                            rtl433Devices = d.devices || d || [];
                            if (d.running != null) rtl433Running = d.running;
                            renderDevices();
                        }
                    } catch (_) { /* network error */ }
                }, REFRESH_MS);
            }
        }

        function _deviceDataStr(d) {
            const parts = [];
            if (d.temperature_C != null) parts.push('T:' + d.temperature_C.toFixed(1) + 'C');
            if (d.humidity != null) parts.push('H:' + d.humidity + '%');
            if (d.battery_ok != null) parts.push('bat:' + (d.battery_ok ? 'OK' : 'LOW'));
            if (d.pressure_kPa != null) parts.push('P:' + d.pressure_kPa.toFixed(1) + 'kPa');
            if (d.wind_avg_km_h != null) parts.push('wind:' + d.wind_avg_km_h.toFixed(1) + 'km/h');
            if (d.rain_mm != null) parts.push('rain:' + d.rain_mm.toFixed(1) + 'mm');
            if (d.last_data) return d.last_data;
            return parts.length > 0 ? parts.join(', ') : '--';
        }

        function _agoStr(seconds) {
            if (seconds == null || seconds < 0) return '--';
            if (seconds < 5) return 'now';
            if (seconds < 60) return Math.round(seconds) + 's ago';
            if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
            return Math.floor(seconds / 3600) + 'h ago';
        }

        // ── AIRCRAFT tab (ADS-B) ─────────────────────────────────
        function renderAircraft() {
            const now = Date.now() / 1000;

            body.innerHTML = `
                <div class="hrf-devices-controls">
                    <div class="hrf-spectrum-row" style="gap:8px">
                        <button class="hrf-btn hrf-btn-start" data-action="adsb-start" ${adsbRunning ? 'disabled' : ''}>START ADS-B</button>
                        <button class="hrf-btn hrf-btn-stop" data-action="adsb-stop" ${adsbRunning ? '' : 'disabled'}>STOP ADS-B</button>
                        ${adsbRunning ? '<span class="hrf-sweep-live"><span class="hrf-live-dot"></span> TRACKING</span>' : ''}
                        <span style="flex:1"></span>
                        <span class="hrf-aircraft-count" style="font-size:0.72rem;color:#00f0ff;font-weight:bold">${adsbAircraft.length} aircraft</span>
                    </div>
                </div>

                <div class="hrf-section-label">TRACKED AIRCRAFT</div>
                <div class="hrf-signal-table-wrap">
                    <table class="hrf-table">
                        <thead>
                            <tr>
                                <th class="hrf-th" style="width:70px">ICAO</th>
                                <th class="hrf-th" style="width:80px">CALLSIGN</th>
                                <th class="hrf-th" style="width:70px;text-align:right">ALT (ft)</th>
                                <th class="hrf-th" style="width:70px;text-align:right">SPD (kt)</th>
                                <th class="hrf-th" style="width:50px;text-align:right">HDG</th>
                                <th class="hrf-th" style="width:70px;text-align:right">LAT</th>
                                <th class="hrf-th" style="width:70px;text-align:right">LNG</th>
                                <th class="hrf-th" style="width:60px;text-align:right">SEEN</th>
                                <th class="hrf-th" style="width:40px"></th>
                            </tr>
                        </thead>
                        <tbody>
                            ${adsbAircraft.length === 0
                                ? '<tr><td colspan="9" class="hrf-td" style="text-align:center;color:#555;padding:20px">No aircraft detected -- start ADS-B decoder (1090 MHz)</td></tr>'
                                : adsbAircraft.map(ac => {
                                    const alt = ac.altitude != null ? ac.altitude : null;
                                    const altColor = alt == null ? '#555' : alt < 5000 ? '#05ffa1' : alt < 20000 ? '#fcee0a' : '#ff2a6d';
                                    const age = now - (ac.last_seen || 0);
                                    const hasPos = ac.lat != null && ac.lng != null;
                                    return `<tr class="hrf-tr">
                                        <td class="hrf-td" style="color:#b060ff;font-weight:bold">${_esc(ac.icao || '--')}</td>
                                        <td class="hrf-td" style="color:#00f0ff">${_esc(ac.callsign || '--')}</td>
                                        <td class="hrf-td" style="text-align:right;color:${altColor}">${alt != null ? alt.toLocaleString() : '--'}</td>
                                        <td class="hrf-td" style="text-align:right">${ac.speed != null ? ac.speed.toFixed(0) : '--'}</td>
                                        <td class="hrf-td" style="text-align:right">${ac.heading != null ? ac.heading.toFixed(0) + '\u00B0' : '--'}</td>
                                        <td class="hrf-td" style="text-align:right;font-size:0.65rem">${ac.lat != null ? ac.lat.toFixed(4) : '--'}</td>
                                        <td class="hrf-td" style="text-align:right;font-size:0.65rem">${ac.lng != null ? ac.lng.toFixed(4) : '--'}</td>
                                        <td class="hrf-td" style="text-align:right;color:${age < 10 ? '#05ffa1' : age < 60 ? '#fcee0a' : '#555'}">${_esc(_agoStr(age))}</td>
                                        <td class="hrf-td">${hasPos ? '<button class="hrf-btn hrf-btn-flyto" data-flyto-lat="' + ac.lat + '" data-flyto-lng="' + ac.lng + '" title="Fly to aircraft on map">FLY TO</button>' : ''}</td>
                                    </tr>`;
                                }).join('')}
                        </tbody>
                    </table>
                </div>
            `;

            body.querySelector('[data-action="adsb-start"]')?.addEventListener('click', async () => {
                try {
                    const r = await fetch(API + '/adsb/start', { method: 'POST' });
                    if (r.ok) { adsbRunning = true; renderAircraft(); }
                } catch (_) { /* network error */ }
            });

            body.querySelector('[data-action="adsb-stop"]')?.addEventListener('click', async () => {
                try {
                    const r = await fetch(API + '/adsb/stop', { method: 'POST' });
                    if (r.ok) { adsbRunning = false; renderAircraft(); }
                } catch (_) { /* network error */ }
            });

            // Fly-to buttons
            body.querySelectorAll('[data-flyto-lat]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const lat = parseFloat(btn.dataset.flytoLat);
                    const lng = parseFloat(btn.dataset.flytoLng);
                    if (isFinite(lat) && isFinite(lng)) {
                        document.dispatchEvent(new CustomEvent('map:fly-to', { detail: { lat, lng, zoom: 12 } }));
                    }
                });
            });

            // Start auto-refresh for aircraft tab
            if (aircraftTimer == null) {
                aircraftTimer = setInterval(async () => {
                    if (activeTab !== 'aircraft') return;
                    try {
                        const r = await fetch(API + '/adsb/aircraft');
                        if (r.ok) {
                            const d = await r.json();
                            adsbAircraft = d.aircraft || d || [];
                            if (d.running != null) adsbRunning = d.running;
                            renderAircraft();
                        }
                    } catch (_) { /* network error */ }
                }, 2000);
            }
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
            tabTimers: () => {
                if (devicesTimer) { clearInterval(devicesTimer); devicesTimer = null; }
                if (aircraftTimer) { clearInterval(aircraftTimer); aircraftTimer = null; }
            },
        };
    },

    unmount(bodyEl, panel) {
        if (panel._hrfCleanup) {
            (panel._hrfCleanup.timers || []).forEach(t => clearInterval(t));
            if (typeof panel._hrfCleanup.tabTimers === 'function') panel._hrfCleanup.tabTimers();
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

        /* ── Status bar (persistent bottom) ────────────────────── */
        .hrf-status-bar { display:flex; align-items:center; gap:8px; padding:4px 10px; border-top:1px solid #1a1a2e; background:#08080d; flex-shrink:0; font-size:0.65rem; }
        .hrf-status-activity { font-weight:bold; letter-spacing:1px; color:#b060ff; }
        .hrf-status-activity.sweep { color:#05ffa1; }
        .hrf-status-activity.idle { color:#666; }
        .hrf-status-activity.error { color:#ff2a6d; }
        .hrf-status-detail { color:#888; }
        .hrf-status-stats { color:#555; }

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

        /* ── Devices tab ───────────────────────────────────────── */
        .hrf-devices-controls { padding:8px 10px; border-bottom:1px solid #1a1a2e; }
        .hrf-tpms-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:8px; padding:8px 10px; }
        .hrf-tpms-card { background:#0e0e14; border:1px solid #1a1a2e; border-radius:4px; padding:10px; text-align:center; }
        .hrf-tpms-id { font-size:0.65rem; font-weight:bold; margin-bottom:4px; }
        .hrf-tpms-pressure { font-size:1rem; font-weight:bold; color:#fcee0a; }
        .hrf-tpms-temp { font-size:0.72rem; color:#888; margin-top:2px; }
        .hrf-tpms-age { font-size:0.6rem; margin-top:4px; }

        /* ── Aircraft tab / Fly-to button ──────────────────────── */
        .hrf-btn-flyto { font-size:0.55rem; padding:1px 5px; background:rgba(0,240,255,0.08); border:1px solid rgba(0,240,255,0.2); color:#00f0ff; border-radius:2px; cursor:pointer; }
        .hrf-btn-flyto:hover { background:rgba(0,240,255,0.2); }
    `;
    document.head.appendChild(s);
}
