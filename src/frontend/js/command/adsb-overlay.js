// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 -- see LICENSE for details.
// ADS-B Aircraft Overlay — renders aircraft markers on the MapLibre tactical map.
// Fetches from /api/sdr/adsb every 2 seconds and shows:
//   - Airplane icon rotated to heading
//   - Callsign label
//   - Altitude in flight level format (FL350, FL120, etc.)
//   - Color by altitude (green=low, yellow=mid, red=high)
//   - Trail of recent positions
//   - Emergency squawk highlighting
//
// UX Loop: Loop 1 (First Boot) — sensor overlay enrichment
// API: GET /api/sdr/adsb -> { tracks: [...], count: N }

import { EventBus } from '/lib/events.js';

// ============================================================
// Constants
// ============================================================

const FETCH_INTERVAL_MS = 2000;
const TRAIL_MAX_POINTS = 20;

// Altitude color stops (feet -> color)
// Green (low/ground) -> cyan (mid) -> magenta (high altitude)
const ALT_COLORS = [
    { alt: 0,     color: '#05ffa1' },   // ground — green
    { alt: 5000,  color: '#05ffa1' },   // low — green
    { alt: 15000, color: '#00f0ff' },   // mid — cyan
    { alt: 30000, color: '#00f0ff' },   // high-mid — cyan
    { alt: 45000, color: '#ff2a6d' },   // very high — magenta
];

const EMERGENCY_COLOR = '#ff0000';

// SVG airplane icon pointing UP (north). CSS rotation aligns to heading.
const AIRPLANE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="20" height="20">
  <path d="M12 2 L14 8 L21 10 L14 12 L14 18 L17 20 L17 21 L12 19 L7 21 L7 20 L10 18 L10 12 L3 10 L10 8 Z"
        fill="currentColor" stroke="rgba(0,0,0,0.6)" stroke-width="0.5"/>
</svg>`;


// ============================================================
// State
// ============================================================

let _enabled = false;
let _pollTimer = null;
let _markers = {};         // icao_hex -> { marker, el, labelEl }
let _trails = {};          // icao_hex -> [{ lat, lng, ts }]
let _trailSources = {};    // icao_hex -> source name (MapLibre GeoJSON source)
let _trailLayers = {};     // icao_hex -> layer id

// ============================================================
// Helpers
// ============================================================

function _altitudeColor(altFt) {
    if (altFt <= ALT_COLORS[0].alt) return ALT_COLORS[0].color;
    for (let i = 1; i < ALT_COLORS.length; i++) {
        if (altFt <= ALT_COLORS[i].alt) {
            const prev = ALT_COLORS[i - 1];
            const curr = ALT_COLORS[i];
            const t = (altFt - prev.alt) / (curr.alt - prev.alt);
            return _lerpColor(prev.color, curr.color, t);
        }
    }
    return ALT_COLORS[ALT_COLORS.length - 1].color;
}

function _lerpColor(c1, c2, t) {
    const r1 = parseInt(c1.slice(1, 3), 16);
    const g1 = parseInt(c1.slice(3, 5), 16);
    const b1 = parseInt(c1.slice(5, 7), 16);
    const r2 = parseInt(c2.slice(1, 3), 16);
    const g2 = parseInt(c2.slice(3, 5), 16);
    const b2 = parseInt(c2.slice(5, 7), 16);
    const r = Math.round(r1 + (r2 - r1) * t);
    const g = Math.round(g1 + (g2 - g1) * t);
    const b = Math.round(b1 + (b2 - b1) * t);
    return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

function _flightLevel(altFt) {
    if (altFt < 1000) return `${altFt}ft`;
    return `FL${Math.round(altFt / 100)}`;
}

function _escText(s) {
    const d = document.createElement('span');
    d.textContent = s;
    return d.innerHTML;
}


// ============================================================
// Marker management
// ============================================================

function _createMarkerEl(track) {
    const color = track.is_emergency ? EMERGENCY_COLOR : _altitudeColor(track.altitude_ft);

    const el = document.createElement('div');
    el.className = 'adsb-aircraft-marker';
    el.style.cssText = `
        position: relative;
        cursor: pointer;
        pointer-events: auto;
        filter: drop-shadow(0 0 4px ${color});
    `;

    // Icon container (rotated to heading)
    const icon = document.createElement('div');
    icon.className = 'adsb-icon';
    icon.style.cssText = `
        width: 20px;
        height: 20px;
        color: ${color};
        transform: rotate(${track.heading || 0}deg);
        transition: transform 1.5s ease-out;
    `;
    icon.innerHTML = AIRPLANE_SVG;

    // Label below icon
    const label = document.createElement('div');
    label.className = 'adsb-label';
    label.style.cssText = `
        position: absolute;
        top: 22px;
        left: 50%;
        transform: translateX(-50%);
        white-space: nowrap;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        font-size: 9px;
        line-height: 1.1;
        text-align: center;
        color: ${color};
        text-shadow: 0 0 3px rgba(0,0,0,0.9), 0 0 6px ${color}40;
        pointer-events: none;
    `;
    const callsign = track.callsign || track.icao_hex;
    const fl = _flightLevel(track.altitude_ft);
    label.innerHTML = `${_escText(callsign)}<br>${fl}`;

    el.appendChild(icon);
    el.appendChild(label);

    // Click handler -- emit event for target inspection
    el.addEventListener('click', (e) => {
        e.stopPropagation();
        EventBus.emit('adsb:select', {
            icao_hex: track.icao_hex,
            callsign: track.callsign,
            lat: track.lat,
            lng: track.lng,
            altitude_ft: track.altitude_ft,
            speed_kts: track.speed_kts,
            heading: track.heading,
            squawk: track.squawk,
        });
    });

    return { el, icon, label };
}

function _updateMarkerEl(entry, track) {
    const color = track.is_emergency ? EMERGENCY_COLOR : _altitudeColor(track.altitude_ft);

    // Update icon rotation and color
    entry.icon.style.transform = `rotate(${track.heading || 0}deg)`;
    entry.icon.style.color = color;

    // Update label
    const callsign = track.callsign || track.icao_hex;
    const fl = _flightLevel(track.altitude_ft);
    entry.label.innerHTML = `${_escText(callsign)}<br>${fl}`;
    entry.label.style.color = color;

    // Update glow
    entry.el.style.filter = `drop-shadow(0 0 4px ${color})`;

    // Emergency pulse
    if (track.is_emergency) {
        entry.el.classList.add('adsb-emergency');
    } else {
        entry.el.classList.remove('adsb-emergency');
    }
}


// ============================================================
// Trail management (MapLibre GeoJSON lines)
// ============================================================

function _updateTrail(icao, lat, lng) {
    if (!_trails[icao]) {
        _trails[icao] = [];
    }
    const trail = _trails[icao];
    trail.push({ lat, lng, ts: Date.now() });
    if (trail.length > TRAIL_MAX_POINTS) {
        trail.shift();
    }
}

function _renderTrails(map) {
    // Build GeoJSON for each aircraft trail
    for (const [icao, trail] of Object.entries(_trails)) {
        if (trail.length < 2) continue;

        const coordinates = trail.map(p => [p.lng, p.lat]);
        const geojson = {
            type: 'Feature',
            geometry: {
                type: 'LineString',
                coordinates,
            },
        };

        const sourceId = `adsb-trail-${icao}`;
        const layerId = `adsb-trail-layer-${icao}`;

        if (map.getSource(sourceId)) {
            map.getSource(sourceId).setData(geojson);
        } else {
            map.addSource(sourceId, { type: 'geojson', data: geojson });

            // Determine color from latest track data
            const marker = _markers[icao];
            const color = marker ? (marker.el.style.filter.match(/#[0-9a-f]{6}/i) || ['#00f0ff'])[0] : '#00f0ff';

            map.addLayer({
                id: layerId,
                type: 'line',
                source: sourceId,
                paint: {
                    'line-color': color,
                    'line-width': 1.5,
                    'line-opacity': 0.4,
                    'line-dasharray': [2, 3],
                },
            });
            _trailSources[icao] = sourceId;
            _trailLayers[icao] = layerId;
        }
    }
}

function _removeTrail(map, icao) {
    const layerId = _trailLayers[icao];
    const sourceId = _trailSources[icao];
    if (layerId && map.getLayer(layerId)) {
        map.removeLayer(layerId);
    }
    if (sourceId && map.getSource(sourceId)) {
        map.removeSource(sourceId);
    }
    delete _trailLayers[icao];
    delete _trailSources[icao];
    delete _trails[icao];
}


// ============================================================
// Data fetching
// ============================================================

async function _fetchAndRender() {
    const mapState = window._mapState;
    if (!mapState || !mapState.map || !_enabled) return;
    const map = mapState.map;

    let tracks = [];
    try {
        const resp = await fetch('/api/sdr/adsb');
        if (!resp.ok) return;
        const data = await resp.json();
        tracks = data.tracks || [];
    } catch (_) {
        return;
    }

    const seenIcao = new Set();

    for (const track of tracks) {
        if (!track.lat || !track.lng) continue;
        const icao = track.icao_hex;
        seenIcao.add(icao);

        // Update trail
        _updateTrail(icao, track.lat, track.lng);

        if (_markers[icao]) {
            // Update existing marker
            _markers[icao].marker.setLngLat([track.lng, track.lat]);
            _updateMarkerEl(_markers[icao], track);
        } else {
            // Create new marker
            const { el, icon, label } = _createMarkerEl(track);
            const marker = new maplibregl.Marker({ element: el, anchor: 'center' })
                .setLngLat([track.lng, track.lat])
                .addTo(map);
            _markers[icao] = { marker, el, icon, label };
        }
    }

    // Remove stale markers
    for (const icao of Object.keys(_markers)) {
        if (!seenIcao.has(icao)) {
            _markers[icao].marker.remove();
            delete _markers[icao];
            _removeTrail(map, icao);
        }
    }

    // Render trail lines
    _renderTrails(map);

    // Emit count for status displays
    EventBus.emit('adsb:count', { count: tracks.length });
}


// ============================================================
// Public API
// ============================================================

/**
 * Start the ADS-B overlay. Begins polling /api/sdr/adsb every 2 seconds
 * and rendering aircraft markers on the tactical map.
 */
export function startAdsbOverlay() {
    if (_enabled) return;
    _enabled = true;
    _fetchAndRender();
    _pollTimer = setInterval(_fetchAndRender, FETCH_INTERVAL_MS);
    console.log('[ADSB] Aircraft overlay started');
}

/**
 * Stop the ADS-B overlay and remove all markers/trails.
 */
export function stopAdsbOverlay() {
    _enabled = false;
    if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
    }

    const map = window._mapState && window._mapState.map;

    // Remove all markers
    for (const icao of Object.keys(_markers)) {
        _markers[icao].marker.remove();
        if (map) _removeTrail(map, icao);
    }
    _markers = {};
    _trails = {};
    console.log('[ADSB] Aircraft overlay stopped');
}

/**
 * Toggle the ADS-B overlay on/off.
 * @returns {boolean} Whether the overlay is now enabled.
 */
export function toggleAdsbOverlay() {
    if (_enabled) {
        stopAdsbOverlay();
    } else {
        startAdsbOverlay();
    }
    return _enabled;
}

/**
 * Check if the ADS-B overlay is currently active.
 * @returns {boolean}
 */
export function isAdsbOverlayActive() {
    return _enabled;
}
