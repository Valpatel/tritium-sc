// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// ADS-B Aircraft Table Panel — sortable table of tracked aircraft with
// squawk highlighting, auto-refresh, and click-to-center map interaction.
// Backend API: GET /api/sdr/adsb -> { tracks: [...], count: N }

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// ============================================================
// Constants
// ============================================================

const CYAN = '#00f0ff';
const GREEN = '#05ffa1';
const RED = '#ff2a6d';
const YELLOW = '#fcee0a';
const MAGENTA = '#ff2a6d';
const DIM = '#1a1a2e';
const TEXT_DIM = '#888';
const BG = '#0a0a0f';

const FETCH_INTERVAL_MS = 2000;

// Emergency squawk codes with colors
const SQUAWK_ALERTS = {
    '7500': { label: 'HIJACK', color: RED },
    '7600': { label: 'RADIO FAIL', color: YELLOW },
    '7700': { label: 'EMERGENCY', color: MAGENTA },
};

// Sortable columns
const COLUMNS = [
    { key: 'callsign',    label: 'CALLSIGN',  width: '80px',  align: 'left' },
    { key: 'icao_hex',    label: 'ICAO',       width: '64px',  align: 'left' },
    { key: 'altitude_ft', label: 'ALT (ft)',   width: '68px',  align: 'right' },
    { key: 'speed_kts',   label: 'SPD (kts)',  width: '64px',  align: 'right' },
    { key: 'heading',     label: 'HDG',        width: '44px',  align: 'right' },
    { key: 'lat',         label: 'LAT',        width: '72px',  align: 'right' },
    { key: 'lng',         label: 'LNG',        width: '76px',  align: 'right' },
    { key: 'squawk',      label: 'SQUAWK',     width: '60px',  align: 'center' },
    { key: 'vertical_rate', label: 'VS',       width: '50px',  align: 'right' },
];

// ============================================================
// Helpers
// ============================================================

function fmtAlt(ft) {
    if (ft === undefined || ft === null || ft === 0) return '--';
    return ft.toLocaleString();
}

function fmtSpeed(kts) {
    if (kts === undefined || kts === null || kts === 0) return '--';
    return kts.toFixed(0);
}

function fmtHeading(deg) {
    if (deg === undefined || deg === null) return '--';
    return deg.toFixed(0) + '\u00b0';
}

function fmtCoord(val, decimals) {
    if (val === undefined || val === null || val === 0) return '--';
    return val.toFixed(decimals || 4);
}

function fmtVS(rate) {
    if (rate === undefined || rate === null || rate === 0) return '--';
    const prefix = rate > 0 ? '+' : '';
    return prefix + rate.toFixed(0);
}

function altColor(ft) {
    if (ft <= 0) return GREEN;
    if (ft < 5000) return GREEN;
    if (ft < 15000) return CYAN;
    if (ft < 30000) return YELLOW;
    return MAGENTA;
}

function sortTracks(tracks, sortKey, sortAsc) {
    return [...tracks].sort((a, b) => {
        let va = a[sortKey];
        let vb = b[sortKey];
        // String comparison for callsign, icao, squawk
        if (typeof va === 'string' && typeof vb === 'string') {
            const cmp = va.localeCompare(vb);
            return sortAsc ? cmp : -cmp;
        }
        // Numeric comparison
        va = va || 0;
        vb = vb || 0;
        return sortAsc ? va - vb : vb - va;
    });
}


// ============================================================
// Panel Definition
// ============================================================

export const AdsbTablePanelDef = {
    id: 'adsb-table',
    title: 'ADS-B AIRCRAFT',
    defaultPosition: { x: 80, y: 80 },
    defaultSize: { w: 680, h: 420 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'adsb-table-inner';
        el.style.cssText = `display:flex;flex-direction:column;height:100%;background:${BG};overflow:hidden;font-family:monospace;`;

        el.innerHTML = `
            <div class="adsb-table-header" style="display:flex;align-items:center;justify-content:space-between;padding:4px 8px;border-bottom:1px solid ${DIM};flex-shrink:0;font-size:11px;">
                <div style="display:flex;gap:12px;align-items:center;">
                    <span data-bind="status-dot" style="width:8px;height:8px;border-radius:50%;background:#555;flex-shrink:0"></span>
                    <span data-bind="status" style="color:${GREEN};font-weight:bold;">STANDBY</span>
                    <span style="color:${TEXT_DIM};">AIRCRAFT:</span>
                    <span data-bind="count" style="color:${CYAN};">0</span>
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <span data-bind="emergency" style="color:${RED};font-weight:bold;display:none;"></span>
                    <span style="color:${TEXT_DIM};font-size:10px;">UPDATED:</span>
                    <span data-bind="updated" style="color:${TEXT_DIM};font-size:10px;">--</span>
                </div>
            </div>

            <div class="adsb-table-wrap" style="flex:1;min-height:0;overflow:auto;">
                <table style="width:100%;border-collapse:collapse;font-size:10px;">
                    <thead>
                        <tr data-bind="thead-row" style="position:sticky;top:0;background:${BG};z-index:1;">
                        </tr>
                    </thead>
                    <tbody data-bind="tbody">
                    </tbody>
                </table>
            </div>

            <div data-bind="empty-state" style="display:none;flex:1;min-height:0;align-items:center;justify-content:center;flex-direction:column;gap:12px;padding:20px;">
                <div style="font-size:32px;color:#334;user-select:none;">&#9992;</div>
                <div style="color:${TEXT_DIM};font-size:12px;text-align:center;max-width:300px;">
                    NO ADS-B RECEIVER CONNECTED
                </div>
                <div style="color:#555;font-size:10px;text-align:center;max-width:300px;">
                    Start dump1090 to track aircraft, or enable SDR demo mode via<br>
                    <span style="color:${CYAN};">POST /api/sdr/demo/start</span>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const statusDot = bodyEl.querySelector('[data-bind="status-dot"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const countEl = bodyEl.querySelector('[data-bind="count"]');
        const emergencyEl = bodyEl.querySelector('[data-bind="emergency"]');
        const updatedEl = bodyEl.querySelector('[data-bind="updated"]');
        const theadRow = bodyEl.querySelector('[data-bind="thead-row"]');
        const tbody = bodyEl.querySelector('[data-bind="tbody"]');
        const tableWrap = bodyEl.querySelector('.adsb-table-wrap');
        const emptyState = bodyEl.querySelector('[data-bind="empty-state"]');

        let tracks = [];
        let sortKey = 'altitude_ft';
        let sortAsc = false;
        let selectedIcao = null;
        let fetchTimerId = null;
        let destroyed = false;

        // -- Build header columns --
        function buildHeader() {
            theadRow.innerHTML = '';
            for (const col of COLUMNS) {
                const th = document.createElement('th');
                th.style.cssText = `padding:3px 6px;text-align:${col.align};color:${TEXT_DIM};border-bottom:1px solid ${DIM};cursor:pointer;white-space:nowrap;user-select:none;font-weight:normal;`;
                th.title = `Sort by ${col.label}`;

                const arrow = sortKey === col.key ? (sortAsc ? ' \u25b2' : ' \u25bc') : '';
                th.textContent = col.label + arrow;

                if (sortKey === col.key) {
                    th.style.color = CYAN;
                }

                th.addEventListener('click', () => {
                    if (sortKey === col.key) {
                        sortAsc = !sortAsc;
                    } else {
                        sortKey = col.key;
                        sortAsc = true;
                    }
                    buildHeader();
                    renderTable();
                });
                theadRow.appendChild(th);
            }
        }

        // -- Render table body --
        function renderTable() {
            if (tracks.length === 0) {
                tableWrap.style.display = 'none';
                emptyState.style.display = 'flex';
                return;
            }
            tableWrap.style.display = '';
            emptyState.style.display = 'none';

            const sorted = sortTracks(tracks, sortKey, sortAsc);
            let html = '';

            for (const t of sorted) {
                const isEmergency = t.is_emergency || false;
                const squawkAlert = SQUAWK_ALERTS[t.squawk];
                const isSelected = t.icao_hex === selectedIcao;

                // Row background
                let rowBg = 'transparent';
                if (isEmergency && squawkAlert) {
                    rowBg = squawkAlert.color === RED ? 'rgba(255,42,109,0.12)' :
                            squawkAlert.color === YELLOW ? 'rgba(252,238,10,0.08)' :
                            'rgba(255,42,109,0.12)';
                }
                if (isSelected) {
                    rowBg = 'rgba(0,240,255,0.1)';
                }

                const rowStyle = `background:${rowBg};cursor:pointer;border-bottom:1px solid #0e0e14;`;
                const hoverAttr = `onmouseover="this.style.background='rgba(0,240,255,0.06)'" onmouseout="this.style.background='${rowBg}'"`;

                html += `<tr data-icao="${_esc(t.icao_hex)}" style="${rowStyle}" ${hoverAttr}>`;

                // Callsign
                const callsign = t.callsign || t.icao_hex;
                html += `<td style="padding:3px 6px;color:${CYAN};white-space:nowrap;">${_esc(callsign)}</td>`;

                // ICAO
                html += `<td style="padding:3px 6px;color:${TEXT_DIM};white-space:nowrap;">${_esc(t.icao_hex)}</td>`;

                // Altitude
                const ac = altColor(t.altitude_ft || 0);
                html += `<td style="padding:3px 6px;text-align:right;color:${ac};white-space:nowrap;">${fmtAlt(t.altitude_ft)}</td>`;

                // Speed
                html += `<td style="padding:3px 6px;text-align:right;color:#ccc;white-space:nowrap;">${fmtSpeed(t.speed_kts)}</td>`;

                // Heading
                html += `<td style="padding:3px 6px;text-align:right;color:#ccc;white-space:nowrap;">${fmtHeading(t.heading)}</td>`;

                // Lat
                html += `<td style="padding:3px 6px;text-align:right;color:#aaa;white-space:nowrap;">${fmtCoord(t.lat, 4)}</td>`;

                // Lng
                html += `<td style="padding:3px 6px;text-align:right;color:#aaa;white-space:nowrap;">${fmtCoord(t.lng, 4)}</td>`;

                // Squawk
                let squawkHtml;
                if (squawkAlert) {
                    squawkHtml = `<span style="color:${squawkAlert.color};font-weight:bold;padding:1px 4px;border:1px solid ${squawkAlert.color};border-radius:2px;">${_esc(t.squawk)} ${squawkAlert.label}</span>`;
                } else {
                    squawkHtml = `<span style="color:${TEXT_DIM};">${_esc(t.squawk || '--')}</span>`;
                }
                html += `<td style="padding:3px 6px;text-align:center;white-space:nowrap;">${squawkHtml}</td>`;

                // Vertical rate
                const vsColor = (t.vertical_rate || 0) > 0 ? GREEN : (t.vertical_rate || 0) < 0 ? YELLOW : TEXT_DIM;
                html += `<td style="padding:3px 6px;text-align:right;color:${vsColor};white-space:nowrap;">${fmtVS(t.vertical_rate)}</td>`;

                html += '</tr>';
            }

            tbody.innerHTML = html;

            // Attach click handlers
            const rows = tbody.querySelectorAll('tr[data-icao]');
            rows.forEach(row => {
                row.addEventListener('click', () => {
                    const icao = row.getAttribute('data-icao');
                    const track = tracks.find(t => t.icao_hex === icao);
                    if (track && track.lat && track.lng) {
                        selectedIcao = icao;
                        EventBus.emit('map:flyTo', {
                            lat: track.lat,
                            lng: track.lng,
                            zoom: 12,
                            label: track.callsign || track.icao_hex,
                        });
                        renderTable();
                    }
                });
            });
        }

        // -- Data fetch --
        async function fetchTracks() {
            if (destroyed) return;
            try {
                const res = await fetch('/api/sdr/adsb');
                if (res.ok) {
                    const data = await res.json();
                    tracks = data.tracks || [];

                    // Update header info
                    if (countEl) countEl.textContent = tracks.length;
                    if (updatedEl) updatedEl.textContent = new Date().toLocaleTimeString();

                    if (tracks.length > 0) {
                        statusDot.style.background = GREEN;
                        statusEl.textContent = 'TRACKING';
                        statusEl.style.color = GREEN;
                    } else {
                        statusDot.style.background = YELLOW;
                        statusEl.textContent = 'NO AIRCRAFT';
                        statusEl.style.color = YELLOW;
                    }

                    // Check for emergencies
                    const emergencies = tracks.filter(t => t.is_emergency);
                    if (emergencies.length > 0) {
                        emergencyEl.style.display = '';
                        const labels = emergencies.map(t => {
                            const alert = SQUAWK_ALERTS[t.squawk];
                            return `${t.callsign || t.icao_hex}: ${alert ? alert.label : t.squawk}`;
                        });
                        emergencyEl.textContent = 'ALERT: ' + labels.join(', ');
                    } else {
                        emergencyEl.style.display = 'none';
                    }

                    renderTable();
                } else {
                    statusDot.style.background = YELLOW;
                    statusEl.textContent = 'STANDBY';
                    statusEl.style.color = YELLOW;
                }
            } catch (_err) {
                statusDot.style.background = '#555';
                statusEl.textContent = 'OFFLINE';
                statusEl.style.color = TEXT_DIM;
                tracks = [];
                renderTable();
            }
        }

        // -- Initialize --
        buildHeader();
        fetchTracks();
        fetchTimerId = setInterval(fetchTracks, FETCH_INTERVAL_MS);

        // -- Cleanup --
        panel._unsubs.push(() => {
            destroyed = true;
            if (fetchTimerId) clearInterval(fetchTimerId);
        });

        // Listen for ADS-B events from websocket
        const unsub = EventBus.on('adsb:tracks_updated', () => {
            fetchTracks();
        });
        if (unsub) panel._unsubs.push(unsub);
    },

    unmount(bodyEl) {
        // Cleanup handled by panel._unsubs
    },

    onResize() {
        // Table auto-adjusts
    },
};
