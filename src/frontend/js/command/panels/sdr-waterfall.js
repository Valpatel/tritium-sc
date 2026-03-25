// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// SDR Spectrum Waterfall Panel — dual-view spectrum analyzer with live
// spectrum plot (top) and scrolling waterfall display (bottom).
// Backend API: /api/sdr/spectrum/sweeps (raw FFT data), /api/sdr/status,
//              /api/sdr/signals, /api/sdr/configure, /api/sdr/demo/start|stop

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// -- Color helpers -----------------------------------------------------------

const WATERFALL_COLORS = [
    [0, 0, 0],        // -120 dBm  (no signal)
    [0, 0, 80],       // -100 dBm  (faint)
    [0, 60, 160],     // -90 dBm   (noise floor)
    [0, 180, 220],    // -75 dBm   (weak)
    [0, 255, 161],    // -60 dBm   (moderate)
    [252, 238, 10],   // -45 dBm   (strong)
    [255, 42, 109],   // -30 dBm   (very strong)
    [255, 255, 255],  // -10 dBm   (overload)
];

// Map a dBm value to an [r,g,b] color via the gradient above.
function dbmToColor(dbm) {
    const minDbm = -120;
    const maxDbm = -10;
    const t = Math.max(0, Math.min(1, (dbm - minDbm) / (maxDbm - minDbm)));
    const idx = t * (WATERFALL_COLORS.length - 1);
    const lo = Math.floor(idx);
    const hi = Math.min(lo + 1, WATERFALL_COLORS.length - 1);
    const f = idx - lo;
    return [
        Math.round(WATERFALL_COLORS[lo][0] + (WATERFALL_COLORS[hi][0] - WATERFALL_COLORS[lo][0]) * f),
        Math.round(WATERFALL_COLORS[lo][1] + (WATERFALL_COLORS[hi][1] - WATERFALL_COLORS[lo][1]) * f),
        Math.round(WATERFALL_COLORS[lo][2] + (WATERFALL_COLORS[hi][2] - WATERFALL_COLORS[lo][2]) * f),
    ];
}

// -- Frequency formatting ----------------------------------------------------

function fmtFreqMHz(hz) {
    return (hz / 1e6).toFixed(3);
}

function fmtPower(dbm) {
    return dbm.toFixed(1);
}


// -- Known signal identification --------------------------------------------

const KNOWN_BANDS = [
    { start: 2400, end: 2500, label: 'WiFi/BLE', color: '#00f0ff' },
    { start: 433.05, end: 434.79, label: 'ISM 433', color: '#05ffa1' },
    { start: 868.0, end: 868.6, label: 'ISM 868', color: '#05ffa1' },
    { start: 902.0, end: 928.0, label: 'ISM 915', color: '#05ffa1' },
    { start: 314.0, end: 316.0, label: 'TPMS 315', color: '#fcee0a' },
    { start: 1088.0, end: 1092.0, label: 'ADS-B', color: '#ff2a6d' },
    { start: 137.0, end: 138.0, label: 'NOAA SAT', color: '#8b5cf6' },
    { start: 462.0, end: 468.0, label: 'FRS/GMRS', color: '#f97316' },
];

function identifySignal(freqMHz) {
    for (const band of KNOWN_BANDS) {
        if (freqMHz >= band.start && freqMHz <= band.end) {
            return band;
        }
    }
    return null;
}


// -- Bandwidth options -------------------------------------------------------

const BW_OPTIONS = [
    { label: '1 MHz', value: 1e6 },
    { label: '2 MHz', value: 2e6 },
    { label: '5 MHz', value: 5e6 },
    { label: '10 MHz', value: 10e6 },
    { label: '20 MHz', value: 20e6 },
];


// ============================================================================
// Panel Definition
// ============================================================================

export const SdrWaterfallPanelDef = {
    id: 'sdr-waterfall',
    title: 'SDR SPECTRUM',
    defaultPosition: { x: 16, y: 16 },
    defaultSize: { w: 720, h: 560 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'sdr-wf-inner';
        el.style.cssText = 'display:flex;flex-direction:column;height:100%;overflow:hidden;font-size:0.48rem;color:#aaa;';
        el.innerHTML = `
            <div class="sdr-wf-header" style="display:flex;align-items:center;gap:6px;padding:2px 4px;flex-shrink:0;border-bottom:1px solid #1a1a2e">
                <span class="sdr-wf-status-dot" data-bind="status-dot" style="width:8px;height:8px;border-radius:50%;background:#555;flex-shrink:0"></span>
                <span class="mono" data-bind="status-text" style="color:#888;font-size:0.42rem">OFFLINE</span>
                <span class="mono" data-bind="freq-label" style="color:#00f0ff;margin-left:auto;font-size:0.42rem">--</span>
            </div>

            <div class="sdr-wf-controls" style="display:flex;align-items:center;gap:4px;padding:3px 4px;flex-shrink:0;flex-wrap:wrap;border-bottom:1px solid #1a1a2e">
                <label style="color:#888;font-size:0.4rem">CENTER</label>
                <input type="number" data-bind="center-freq" value="433.92" step="0.1" style="width:70px;background:#0e0e14;border:1px solid #1a1a2e;color:#00f0ff;font-family:inherit;font-size:0.44rem;padding:1px 3px;border-radius:2px" title="Center frequency (MHz)">
                <span style="color:#555;font-size:0.4rem">MHz</span>

                <label style="color:#888;font-size:0.4rem;margin-left:6px">BW</label>
                <select data-bind="bandwidth" style="background:#0e0e14;border:1px solid #1a1a2e;color:#05ffa1;font-family:inherit;font-size:0.42rem;padding:1px 2px;border-radius:2px">
                    ${BW_OPTIONS.map(bw => `<option value="${bw.value}" ${bw.value === 2e6 ? 'selected' : ''}>${bw.label}</option>`).join('')}
                </select>

                <label style="color:#888;font-size:0.4rem;margin-left:6px">GAIN</label>
                <input type="range" data-bind="gain" min="0" max="60" value="40" style="width:50px;accent-color:#00f0ff" title="Gain (dB)">
                <span data-bind="gain-label" class="mono" style="color:#888;font-size:0.4rem;width:26px">40dB</span>

                <button class="panel-action-btn panel-action-btn-primary" data-action="scan" style="margin-left:auto;font-size:0.42rem;padding:1px 6px">START</button>
            </div>

            <div class="sdr-wf-body" style="display:flex;flex:1;min-height:0;overflow:hidden">
                <div class="sdr-wf-viz" style="flex:1;min-width:0;display:flex;flex-direction:column;overflow:hidden">
                    <canvas data-bind="spectrum-canvas" style="width:100%;flex:1;min-height:0"></canvas>
                    <canvas data-bind="waterfall-canvas" style="width:100%;flex:1;min-height:0"></canvas>
                </div>

                <div class="sdr-wf-sidebar" style="width:160px;flex-shrink:0;overflow-y:auto;border-left:1px solid #1a1a2e;padding:3px">
                    <div style="color:#888;font-size:0.42rem;border-bottom:1px solid #1a1a2e;padding-bottom:2px;margin-bottom:3px">DETECTED SIGNALS</div>
                    <ul class="sdr-wf-signal-list" data-bind="signal-list" style="list-style:none;margin:0;padding:0;font-size:0.42rem">
                        <li style="color:#555">No signals</li>
                    </ul>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusText = bodyEl.querySelector('[data-bind="status-text"]');
        const freqLabel = bodyEl.querySelector('[data-bind="freq-label"]');
        const centerFreqInput = bodyEl.querySelector('[data-bind="center-freq"]');
        const bandwidthSelect = bodyEl.querySelector('[data-bind="bandwidth"]');
        const gainSlider = bodyEl.querySelector('[data-bind="gain"]');
        const gainLabel = bodyEl.querySelector('[data-bind="gain-label"]');
        const scanBtn = bodyEl.querySelector('[data-action="scan"]');
        const spectrumCanvas = bodyEl.querySelector('[data-bind="spectrum-canvas"]');
        const waterfallCanvas = bodyEl.querySelector('[data-bind="waterfall-canvas"]');
        const signalList = bodyEl.querySelector('[data-bind="signal-list"]');

        const specCtx = spectrumCanvas.getContext('2d');
        const wfCtx = waterfallCanvas.getContext('2d');

        let scanning = false;
        let pollTimer = null;
        let currentSweep = null;           // Latest sweep data
        let waterfallRows = [];            // Array of {power_dbm[], freq_start_hz, freq_end_hz}
        const MAX_WF_ROWS = 200;
        let detectedSignals = [];          // [{freq_mhz, power_dbm, band_label, duration_s}]

        // -- Gain slider feedback --
        gainSlider.addEventListener('input', () => {
            gainLabel.textContent = `${gainSlider.value}dB`;
        });

        // -- Scan toggle --
        scanBtn.addEventListener('click', async () => {
            if (scanning) {
                stopScan();
            } else {
                await startScan();
            }
        });

        async function startScan() {
            scanning = true;
            scanBtn.textContent = 'STOP';
            scanBtn.classList.add('panel-action-btn-primary');
            statusDot.style.background = '#05ffa1';
            statusText.textContent = 'SCANNING';

            // Apply configuration
            const config = {
                center_freq_hz: parseFloat(centerFreqInput.value) * 1e6,
                bandwidth_hz: parseFloat(bandwidthSelect.value),
                gain_db: parseFloat(gainSlider.value),
            };
            try {
                await fetch('/api/sdr/configure', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(config),
                });
            } catch (_) { /* best effort */ }

            // Start demo if no real SDR
            try {
                await fetch('/api/sdr/demo/start', { method: 'POST' });
            } catch (_) { /* ignore */ }

            // Begin polling
            pollTimer = setInterval(fetchSpectrum, 500);
            fetchSpectrum();
        }

        function stopScan() {
            scanning = false;
            scanBtn.textContent = 'START';
            statusDot.style.background = '#555';
            statusText.textContent = 'STOPPED';
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        }

        // -- Fetch spectrum data --
        async function fetchSpectrum() {
            try {
                const resp = await fetch('/api/sdr/spectrum/sweeps?limit=1');
                if (resp.status === 404) {
                    // Plugin not loaded -- use fallback demo data
                    handleSweep(generateFallbackSweep());
                    return;
                }
                if (!resp.ok) return;
                const data = await resp.json();
                if (data.sweeps && data.sweeps.length > 0) {
                    handleSweep(data.sweeps[0]);
                }
            } catch (_) {
                // If server unreachable, show fallback
                if (scanning) {
                    handleSweep(generateFallbackSweep());
                }
            }
        }

        // Generate a fallback sweep when no backend is available (demo mode)
        function generateFallbackSweep() {
            const centerMHz = parseFloat(centerFreqInput.value) || 433.92;
            const bwHz = parseFloat(bandwidthSelect.value) || 2e6;
            const bwMHz = bwHz / 1e6;
            const numBins = 512;
            const freqStart = (centerMHz - bwMHz / 2) * 1e6;
            const freqEnd = (centerMHz + bwMHz / 2) * 1e6;

            const power = [];
            for (let i = 0; i < numBins; i++) {
                // Noise floor ~ -90 dBm with variation
                let p = -90 + (Math.random() * 6 - 3);
                // Add a few random peaks
                const binFreqMHz = (freqStart + (freqEnd - freqStart) * (i / numBins)) / 1e6;
                const distFromCenter = Math.abs(binFreqMHz - centerMHz);
                if (distFromCenter < 0.05) {
                    p = Math.max(p, -40 + Math.random() * 10);
                }
                if (Math.random() < 0.01) {
                    p = Math.max(p, -55 + Math.random() * 15);
                }
                power.push(p);
            }
            return {
                freq_start_hz: freqStart,
                freq_end_hz: freqEnd,
                center_freq_hz: centerMHz * 1e6,
                bandwidth_hz: bwHz,
                bin_count: numBins,
                power_dbm: power,
                timestamp: Date.now() / 1000,
            };
        }

        function handleSweep(sweep) {
            currentSweep = sweep;

            // Update header
            const centerMHz = sweep.center_freq_hz / 1e6;
            const bwMHz = sweep.bandwidth_hz / 1e6;
            freqLabel.textContent = `${fmtFreqMHz(sweep.center_freq_hz)} MHz | ${bwMHz.toFixed(1)} MHz BW`;

            // Add to waterfall history
            waterfallRows.unshift(sweep);
            if (waterfallRows.length > MAX_WF_ROWS) waterfallRows.length = MAX_WF_ROWS;

            // Detect peaks
            detectPeaks(sweep);

            // Render both canvases
            renderSpectrum();
            renderWaterfall();
            renderSignalList();
        }

        // -- Peak detection --
        function detectPeaks(sweep) {
            const bins = sweep.power_dbm;
            if (!bins || bins.length === 0) return;

            const noiseFloor = computeNoiseFloor(bins);
            const threshold = noiseFloor + 10; // 10 dB above noise
            const peaks = [];

            for (let i = 2; i < bins.length - 2; i++) {
                if (bins[i] > threshold &&
                    bins[i] >= bins[i - 1] && bins[i] >= bins[i + 1] &&
                    bins[i] >= bins[i - 2] && bins[i] >= bins[i + 2]) {
                    const freqHz = sweep.freq_start_hz + (sweep.freq_end_hz - sweep.freq_start_hz) * (i / bins.length);
                    const freqMHz = freqHz / 1e6;
                    const band = identifySignal(freqMHz);
                    peaks.push({
                        freq_mhz: freqMHz,
                        power_dbm: bins[i],
                        band_label: band ? band.label : 'Unknown',
                        band_color: band ? band.color : '#888',
                        bin_index: i,
                    });
                }
            }

            // Keep top 12 peaks by power
            peaks.sort((a, b) => b.power_dbm - a.power_dbm);
            detectedSignals = peaks.slice(0, 12);
        }

        function computeNoiseFloor(bins) {
            // Median of all bins is a good noise floor estimate
            const sorted = [...bins].sort((a, b) => a - b);
            return sorted[Math.floor(sorted.length * 0.5)];
        }

        // -- Spectrum plot rendering (top canvas) --
        function renderSpectrum() {
            if (!currentSweep) return;

            const canvas = spectrumCanvas;
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;

            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            const ctx = specCtx;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            const w = rect.width;
            const h = rect.height;
            const bins = currentSweep.power_dbm;
            const numBins = bins.length;

            // Margins
            const ml = 36, mr = 6, mt = 6, mb = 16;
            const pw = w - ml - mr;
            const ph = h - mt - mb;

            // Background
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            // dBm range
            const minDbm = -120;
            const maxDbm = -10;
            const noiseFloor = computeNoiseFloor(bins);

            // Grid lines
            ctx.strokeStyle = '#1a1a2e';
            ctx.lineWidth = 0.5;
            ctx.font = '9px monospace';
            ctx.fillStyle = '#555';
            ctx.textAlign = 'right';

            for (let db = -110; db <= -10; db += 20) {
                const y = mt + ph * (1 - (db - minDbm) / (maxDbm - minDbm));
                ctx.beginPath();
                ctx.moveTo(ml, y);
                ctx.lineTo(ml + pw, y);
                ctx.stroke();
                ctx.fillText(`${db}`, ml - 3, y + 3);
            }

            // Frequency axis labels
            ctx.textAlign = 'center';
            ctx.fillStyle = '#555';
            const freqStartMHz = currentSweep.freq_start_hz / 1e6;
            const freqEndMHz = currentSweep.freq_end_hz / 1e6;
            for (let i = 0; i <= 4; i++) {
                const freqMHz = freqStartMHz + (freqEndMHz - freqStartMHz) * (i / 4);
                const x = ml + pw * (i / 4);
                ctx.fillText(`${freqMHz.toFixed(2)}`, x, h - 2);
            }

            // Noise floor line
            const nfY = mt + ph * (1 - (noiseFloor - minDbm) / (maxDbm - minDbm));
            ctx.strokeStyle = '#333';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.beginPath();
            ctx.moveTo(ml, nfY);
            ctx.lineTo(ml + pw, nfY);
            ctx.stroke();
            ctx.setLineDash([]);

            // Spectrum trace (cyan line)
            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 1.5;
            ctx.shadowColor = '#00f0ff';
            ctx.shadowBlur = 4;
            ctx.beginPath();
            for (let i = 0; i < numBins; i++) {
                const x = ml + (i / (numBins - 1)) * pw;
                const y = mt + ph * (1 - (bins[i] - minDbm) / (maxDbm - minDbm));
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Fill under curve
            ctx.fillStyle = 'rgba(0, 240, 255, 0.06)';
            ctx.beginPath();
            for (let i = 0; i < numBins; i++) {
                const x = ml + (i / (numBins - 1)) * pw;
                const y = mt + ph * (1 - (bins[i] - minDbm) / (maxDbm - minDbm));
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.lineTo(ml + pw, mt + ph);
            ctx.lineTo(ml, mt + ph);
            ctx.closePath();
            ctx.fill();

            // Peak markers
            ctx.font = '8px monospace';
            for (const sig of detectedSignals.slice(0, 6)) {
                const binX = ml + (sig.bin_index / (numBins - 1)) * pw;
                const binY = mt + ph * (1 - (sig.power_dbm - minDbm) / (maxDbm - minDbm));

                // Triangle marker
                ctx.fillStyle = sig.band_color;
                ctx.beginPath();
                ctx.moveTo(binX, binY - 6);
                ctx.lineTo(binX - 3, binY - 1);
                ctx.lineTo(binX + 3, binY - 1);
                ctx.closePath();
                ctx.fill();

                // Label
                ctx.fillStyle = sig.band_color;
                ctx.textAlign = 'center';
                ctx.fillText(`${sig.freq_mhz.toFixed(2)}`, binX, binY - 8);
            }
        }

        // -- Waterfall rendering (bottom canvas) --
        function renderWaterfall() {
            if (waterfallRows.length === 0) return;

            const canvas = waterfallCanvas;
            const dpr = window.devicePixelRatio || 1;
            const rect = canvas.getBoundingClientRect();
            if (rect.width === 0 || rect.height === 0) return;

            canvas.width = rect.width * dpr;
            canvas.height = rect.height * dpr;
            const ctx = wfCtx;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

            const w = rect.width;
            const h = rect.height;

            // Background
            ctx.fillStyle = '#0a0a0f';
            ctx.fillRect(0, 0, w, h);

            const ml = 36, mr = 6;
            const pw = w - ml - mr;

            // Each row gets a proportional height
            const rowH = Math.max(1, h / MAX_WF_ROWS);
            const numRows = Math.min(waterfallRows.length, Math.ceil(h / rowH));

            for (let r = 0; r < numRows; r++) {
                const sweep = waterfallRows[r];
                const bins = sweep.power_dbm;
                const numBins = bins.length;
                const y = r * rowH;

                // Use ImageData for efficient pixel-level rendering
                const imgWidth = Math.ceil(pw);
                if (imgWidth <= 0) continue;

                const imgData = ctx.createImageData(imgWidth, Math.max(1, Math.ceil(rowH)));
                const pixels = imgData.data;

                for (let px = 0; px < imgWidth; px++) {
                    const binIdx = Math.floor((px / imgWidth) * numBins);
                    const clampedIdx = Math.min(binIdx, numBins - 1);
                    const [cr, cg, cb] = dbmToColor(bins[clampedIdx]);

                    // Fill all rows in this strip
                    const rowCount = Math.max(1, Math.ceil(rowH));
                    for (let ry = 0; ry < rowCount; ry++) {
                        const offset = (ry * imgWidth + px) * 4;
                        pixels[offset] = cr;
                        pixels[offset + 1] = cg;
                        pixels[offset + 2] = cb;
                        pixels[offset + 3] = 255;
                    }
                }

                ctx.putImageData(imgData, ml, Math.floor(y));
            }

            // Time axis labels on left
            ctx.font = '8px monospace';
            ctx.fillStyle = '#555';
            ctx.textAlign = 'right';
            for (let i = 0; i < numRows; i += Math.max(1, Math.floor(numRows / 6))) {
                const sweep = waterfallRows[i];
                if (!sweep) continue;
                const y = i * rowH + rowH / 2 + 3;
                const t = new Date(sweep.timestamp * 1000);
                const label = `${t.getMinutes().toString().padStart(2, '0')}:${t.getSeconds().toString().padStart(2, '0')}`;
                ctx.fillText(label, ml - 3, y);
            }

            // Frequency axis at bottom
            const freqStartMHz = waterfallRows[0].freq_start_hz / 1e6;
            const freqEndMHz = waterfallRows[0].freq_end_hz / 1e6;
            ctx.textAlign = 'center';
            for (let i = 0; i <= 4; i++) {
                const freqMHz = freqStartMHz + (freqEndMHz - freqStartMHz) * (i / 4);
                const x = ml + pw * (i / 4);
                ctx.fillText(`${freqMHz.toFixed(2)}`, x, h - 2);
            }
        }

        // -- Signal list sidebar --
        function renderSignalList() {
            if (!signalList) return;
            if (detectedSignals.length === 0) {
                signalList.innerHTML = '<li style="color:#555">No signals</li>';
                return;
            }

            let html = '';
            for (const sig of detectedSignals) {
                html += `<li style="padding:2px 0;border-bottom:1px solid #1a1a2e">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span class="mono" style="color:${_esc(sig.band_color)}">${_esc(sig.freq_mhz.toFixed(3))} MHz</span>
                        <span class="mono" style="color:#888">${_esc(fmtPower(sig.power_dbm))} dBm</span>
                    </div>
                    <div style="color:#555;font-size:0.38rem">${_esc(sig.band_label)}</div>
                </li>`;
            }
            signalList.innerHTML = html;
        }

        // -- Fetch status periodically --
        async function fetchStatus() {
            try {
                const resp = await fetch('/api/sdr/status');
                if (!resp.ok) return;
                const data = await resp.json();
                const devices = data.connected_devices || [];
                const active = data.active_receivers || 0;
                const isDemo = data.demo_mode || false;

                if (devices.length > 0 || isDemo) {
                    statusDot.style.background = '#05ffa1';
                    const devLabel = isDemo ? 'DEMO' : `${devices.length} SDR${devices.length > 1 ? 's' : ''}`;
                    statusText.textContent = `${devLabel} | ${active} RX | ${data.ism_devices_tracked || 0} ISM | ${data.adsb_aircraft_tracked || 0} ADS-B`;
                } else if (!scanning) {
                    statusDot.style.background = '#555';
                    statusText.textContent = 'NO SDR CONNECTED';
                }
            } catch (_) {
                if (!scanning) {
                    statusDot.style.background = '#555';
                    statusText.textContent = 'OFFLINE';
                }
            }
        }

        // -- Initial fetch + periodic status --
        fetchStatus();
        const statusTimer = setInterval(fetchStatus, 5000);
        panel._unsubs.push(() => clearInterval(statusTimer));
        panel._unsubs.push(() => {
            if (pollTimer) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        });

        // Handle resize -- re-render canvases
        panel.def.onResize = () => {
            if (currentSweep) {
                renderSpectrum();
                renderWaterfall();
            }
        };
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
