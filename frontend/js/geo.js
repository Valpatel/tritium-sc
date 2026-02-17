/**
 * TRITIUM-SC Geo Engine
 * Coordinate transforms (latlng <-> game coords), satellite tile loader,
 * building footprint loader.
 *
 * Map center (geocoded address) = game origin (0, 0).
 * 1 game unit = 1 meter. North = +Y, East = +X.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const METERS_PER_DEG_LAT = 111320;
const TILE_SIZE = 256;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _geoState = {
    initialized: false,
    centerLat: 0,
    centerLng: 0,
    metersPerDegLng: 0,
};

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

/**
 * Initialize the geo engine with a center coordinate.
 * All game coordinates are relative to this point.
 * @param {number} centerLat - Center latitude
 * @param {number} centerLng - Center longitude
 */
function initGeo(centerLat, centerLng) {
    _geoState.centerLat = centerLat;
    _geoState.centerLng = centerLng;
    _geoState.metersPerDegLng = METERS_PER_DEG_LAT * Math.cos(centerLat * Math.PI / 180);
    _geoState.initialized = true;
}

/**
 * Initialize geo from an address string via the geocoding API.
 * @param {string} address
 * @returns {Promise<{lat: number, lng: number, display_name: string, bbox: number[]}>}
 */
async function initGeoFromAddress(address) {
    const resp = await fetch('/api/geo/geocode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Geocoding failed: HTTP ${resp.status}`);
    }
    const data = await resp.json();
    initGeo(data.lat, data.lng);
    return data;
}

// ---------------------------------------------------------------------------
// Coordinate transforms
// ---------------------------------------------------------------------------

/**
 * Convert lat/lng to game coordinates (meters from center).
 * @param {number} lat
 * @param {number} lng
 * @returns {{x: number, y: number}}
 */
function latlngToGame(lat, lng) {
    const y = (lat - _geoState.centerLat) * METERS_PER_DEG_LAT;
    const x = (lng - _geoState.centerLng) * _geoState.metersPerDegLng;
    return { x, y };
}

/**
 * Convert game coordinates (meters from center) to lat/lng.
 * @param {number} x - East offset in meters
 * @param {number} y - North offset in meters
 * @returns {{lat: number, lng: number}}
 */
function gameToLatlng(x, y) {
    const lat = _geoState.centerLat + y / METERS_PER_DEG_LAT;
    const lng = _geoState.centerLng + x / _geoState.metersPerDegLng;
    return { lat, lng };
}

/**
 * Compute the slippy-map tile coordinates for a given lat/lng and zoom level.
 * Uses the standard Web Mercator tile scheme.
 * @param {number} lat
 * @param {number} lng
 * @param {number} zoom
 * @returns {{x: number, y: number, z: number}}
 */
function tileForLatlng(lat, lng, zoom) {
    const n = Math.pow(2, zoom);
    const x = Math.floor((lng + 180) / 360 * n);
    const latRad = lat * Math.PI / 180;
    const y = Math.floor((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n);
    return { x, y, z: zoom };
}

/**
 * Get the lat/lng bounds of a tile.
 * @param {number} x - Tile X
 * @param {number} y - Tile Y
 * @param {number} z - Zoom level
 * @returns {{north: number, south: number, west: number, east: number}}
 */
function tileBounds(x, y, z) {
    const n = Math.pow(2, z);
    const west = x / n * 360 - 180;
    const east = (x + 1) / n * 360 - 180;
    const north = Math.atan(Math.sinh(Math.PI * (1 - 2 * y / n))) * 180 / Math.PI;
    const south = Math.atan(Math.sinh(Math.PI * (1 - 2 * (y + 1) / n))) * 180 / Math.PI;
    return { north, south, west, east };
}

// ---------------------------------------------------------------------------
// Satellite tile loader
// ---------------------------------------------------------------------------

/**
 * Load satellite tiles covering a circular area around center.
 * @param {number} centerLat
 * @param {number} centerLng
 * @param {number} radiusMeters - Radius to cover
 * @param {number} [zoom=19] - Tile zoom level (19 = ~0.3m/pixel)
 * @returns {Promise<Array<{image: HTMLImageElement, bounds: {minX: number, minY: number, maxX: number, maxY: number}}>>}
 */
async function loadSatelliteTiles(centerLat, centerLng, radiusMeters, zoom = 19) {
    if (!_geoState.initialized) {
        initGeo(centerLat, centerLng);
    }

    // Find tile range covering the area
    const degLatOffset = radiusMeters / METERS_PER_DEG_LAT;
    const metersPerDegLng = METERS_PER_DEG_LAT * Math.cos(centerLat * Math.PI / 180);
    const degLngOffset = radiusMeters / metersPerDegLng;

    const nw = tileForLatlng(centerLat + degLatOffset, centerLng - degLngOffset, zoom);
    const se = tileForLatlng(centerLat - degLatOffset, centerLng + degLngOffset, zoom);

    const minTileX = nw.x;
    const maxTileX = se.x;
    const minTileY = nw.y;
    const maxTileY = se.y;

    const tiles = [];

    for (let tx = minTileX; tx <= maxTileX; tx++) {
        for (let ty = minTileY; ty <= maxTileY; ty++) {
            tiles.push(_loadTile(tx, ty, zoom));
        }
    }

    return Promise.all(tiles);
}

/**
 * Load a single tile, returning image + game-coord bounds.
 * @private
 */
function _loadTile(tx, ty, zoom) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = () => {
            const bounds = tileBounds(tx, ty, zoom);
            const nw = latlngToGame(bounds.north, bounds.west);
            const se = latlngToGame(bounds.south, bounds.east);
            resolve({
                image: img,
                bounds: {
                    minX: nw.x,
                    maxX: se.x,
                    minY: se.y,  // south = lower y
                    maxY: nw.y,  // north = higher y
                },
                tileX: tx,
                tileY: ty,
                zoom,
            });
        };
        img.onerror = () => reject(new Error(`Failed to load tile ${zoom}/${tx}/${ty}`));
        img.src = `/api/geo/tile/${zoom}/${tx}/${ty}`;
    });
}

// ---------------------------------------------------------------------------
// Building footprint loader
// ---------------------------------------------------------------------------

/**
 * Load building footprints and convert to game coordinates.
 * @param {number} centerLat
 * @param {number} centerLng
 * @param {number} [radius=200] - Search radius in meters
 * @returns {Promise<Array<{polygon: Array<{x: number, y: number}>, height: number, tags: object}>>}
 */
async function loadBuildings(centerLat, centerLng, radius = 200) {
    if (!_geoState.initialized) {
        initGeo(centerLat, centerLng);
    }

    const resp = await fetch(`/api/geo/buildings?lat=${centerLat}&lng=${centerLng}&radius=${radius}`);
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Building fetch failed: HTTP ${resp.status}`);
    }

    const buildings = await resp.json();

    return buildings.map(b => {
        const polygon = b.polygon.map(([lat, lng]) => latlngToGame(lat, lng));
        const height = _estimateBuildingHeight(b.tags);
        return { polygon, height, tags: b.tags };
    });
}

/**
 * Estimate building height from OSM tags.
 * @private
 */
function _estimateBuildingHeight(tags) {
    // Explicit height tag (meters)
    if (tags.height) {
        const h = parseFloat(tags.height);
        if (!isNaN(h)) return h;
    }
    // building:levels tag (~3m per level)
    if (tags['building:levels']) {
        const levels = parseInt(tags['building:levels'], 10);
        if (!isNaN(levels)) return levels * 3;
    }
    // Defaults by type
    const type = tags.building || '';
    if (type === 'garage' || type === 'garages' || type === 'shed') return 3;
    if (type === 'house' || type === 'residential' || type === 'detached') return 7;
    if (type === 'apartments' || type === 'commercial') return 12;
    if (type === 'industrial' || type === 'warehouse') return 8;
    return 6;  // generic default
}

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

/**
 * Get the current geo state for debugging.
 * @returns {object}
 */
function getGeoState() {
    return { ..._geoState };
}

/**
 * Meters per pixel at a given zoom level and latitude.
 * @param {number} zoom
 * @param {number} lat
 * @returns {number}
 */
function metersPerPixel(zoom, lat) {
    return 156543.03392 * Math.cos(lat * Math.PI / 180) / Math.pow(2, zoom);
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

window.geo = {
    METERS_PER_DEG_LAT,
    TILE_SIZE,
    initGeo,
    initGeoFromAddress,
    latlngToGame,
    gameToLatlng,
    tileForLatlng,
    tileBounds,
    loadSatelliteTiles,
    loadBuildings,
    getGeoState,
    metersPerPixel,
};
