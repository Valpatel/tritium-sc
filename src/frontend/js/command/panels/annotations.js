// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * Map Annotations Panel — place text labels, arrows, circles, and freehand
 * drawings on the tactical map. Annotations persist via REST API.
 *
 * Used for briefings, operational planning, and marking areas of interest.
 */

import { EventBus } from '/lib/events.js';
import { TritiumStore } from '../store.js';

let _panel = null;
let _annotations = [];
let _activeLayer = 'default';
let _drawMode = null;  // null | 'text' | 'arrow' | 'circle' | 'freehand' | 'rectangle'
let _currentColor = '#00f0ff';
let _freehandPoints = [];

const ANNOTATION_COLORS = [
    '#00f0ff', '#ff2a6d', '#05ffa1', '#fcee0a',
    '#ff9800', '#ffffff', '#ff00ff', '#00a0ff',
];

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

async function _fetchAnnotations() {
    try {
        const res = await fetch(`/api/annotations?layer=${encodeURIComponent(_activeLayer)}`);
        if (res.ok) {
            const data = await res.json();
            _annotations = data.annotations || [];
            EventBus.emit('annotations:updated', _annotations);
        }
    } catch (e) {
        console.warn('[ANNOTATIONS] fetch failed:', e);
    }
}

async function _createAnnotation(ann) {
    try {
        const res = await fetch('/api/annotations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(ann),
        });
        if (res.ok) {
            const created = await res.json();
            _annotations.push(created);
            EventBus.emit('annotations:updated', _annotations);
            return created;
        }
    } catch (e) {
        console.warn('[ANNOTATIONS] create failed:', e);
    }
    return null;
}

async function _deleteAnnotation(id) {
    try {
        await fetch(`/api/annotations/${id}`, { method: 'DELETE' });
        _annotations = _annotations.filter(a => a.id !== id);
        EventBus.emit('annotations:updated', _annotations);
    } catch (e) {
        console.warn('[ANNOTATIONS] delete failed:', e);
    }
}

async function _clearLayer() {
    try {
        await fetch(`/api/annotations?layer=${encodeURIComponent(_activeLayer)}`, { method: 'DELETE' });
        _annotations = [];
        EventBus.emit('annotations:updated', _annotations);
    } catch (e) {
        console.warn('[ANNOTATIONS] clear failed:', e);
    }
}

// ---------------------------------------------------------------------------
// Drawing mode
// ---------------------------------------------------------------------------

function setDrawMode(mode) {
    _drawMode = mode;
    TritiumStore.set('annotations.drawMode', mode);
    EventBus.emit('annotations:mode', mode);
    _renderTools();
}

function getDrawMode() {
    return _drawMode;
}

function handleMapClick(lngLat) {
    if (!_drawMode) return false;

    if (_drawMode === 'text') {
        const text = prompt('Annotation text:');
        if (text) {
            _createAnnotation({
                type: 'text',
                lat: lngLat.lat,
                lng: lngLat.lng,
                text: text,
                color: _currentColor,
                layer: _activeLayer,
            });
        }
        setDrawMode(null);
        return true;
    }

    if (_drawMode === 'circle') {
        const radiusStr = prompt('Circle radius (meters):', '50');
        const radius = parseFloat(radiusStr);
        if (radius > 0) {
            _createAnnotation({
                type: 'circle',
                lat: lngLat.lat,
                lng: lngLat.lng,
                radius_m: radius,
                color: _currentColor,
                fill: true,
                layer: _activeLayer,
            });
        }
        setDrawMode(null);
        return true;
    }

    if (_drawMode === 'arrow') {
        if (!_panel._arrowStart) {
            _panel._arrowStart = { lat: lngLat.lat, lng: lngLat.lng };
            _renderTools();
            return true;
        } else {
            _createAnnotation({
                type: 'arrow',
                lat: _panel._arrowStart.lat,
                lng: _panel._arrowStart.lng,
                end_lat: lngLat.lat,
                end_lng: lngLat.lng,
                color: _currentColor,
                layer: _activeLayer,
            });
            _panel._arrowStart = null;
            setDrawMode(null);
            return true;
        }
    }

    if (_drawMode === 'freehand') {
        _freehandPoints.push([lngLat.lat, lngLat.lng]);
        return true;
    }

    return false;
}

function finishFreehand() {
    if (_freehandPoints.length >= 2) {
        _createAnnotation({
            type: 'freehand',
            lat: _freehandPoints[0][0],
            lng: _freehandPoints[0][1],
            points: _freehandPoints,
            color: _currentColor,
            layer: _activeLayer,
        });
    }
    _freehandPoints = [];
    setDrawMode(null);
}

// ---------------------------------------------------------------------------
// Panel rendering
// ---------------------------------------------------------------------------

function _renderTools() {
    if (!_panel) return;
    const toolbar = _panel.querySelector('.annotation-toolbar');
    if (!toolbar) return;

    const modes = [
        { id: 'text', icon: 'T', label: 'Text' },
        { id: 'arrow', icon: '\u2192', label: 'Arrow' },
        { id: 'circle', icon: '\u25CB', label: 'Circle' },
        { id: 'freehand', icon: '\u270E', label: 'Draw' },
    ];

    toolbar.innerHTML = modes.map(m => `
        <button class="ann-tool ${_drawMode === m.id ? 'active' : ''}"
                data-mode="${m.id}" title="${m.label}">
            <span class="ann-tool-icon">${m.icon}</span>
        </button>
    `).join('') + `
        <span class="ann-color-swatch" style="background:${_currentColor}" title="Color"></span>
        <button class="ann-tool" data-action="clear" title="Clear layer">
            <span class="ann-tool-icon">\u2715</span>
        </button>
    `;

    // Status line
    const status = _panel.querySelector('.annotation-status');
    if (status) {
        if (_drawMode === 'arrow' && _panel._arrowStart) {
            status.textContent = 'Click end point for arrow';
        } else if (_drawMode === 'freehand' && _freehandPoints.length > 0) {
            status.textContent = `Drawing... ${_freehandPoints.length} points (Esc to finish)`;
        } else if (_drawMode) {
            status.textContent = `Click map to place ${_drawMode}`;
        } else {
            status.textContent = `${_annotations.length} annotations on layer: ${_activeLayer}`;
        }
    }

    // Bind events
    toolbar.querySelectorAll('.ann-tool[data-mode]').forEach(btn => {
        btn.onclick = () => {
            const mode = btn.dataset.mode;
            setDrawMode(_drawMode === mode ? null : mode);
        };
    });
    toolbar.querySelectorAll('.ann-tool[data-action="clear"]').forEach(btn => {
        btn.onclick = () => {
            if (confirm('Clear all annotations on this layer?')) _clearLayer();
        };
    });
    const swatch = toolbar.querySelector('.ann-color-swatch');
    if (swatch) {
        swatch.onclick = () => {
            const idx = ANNOTATION_COLORS.indexOf(_currentColor);
            _currentColor = ANNOTATION_COLORS[(idx + 1) % ANNOTATION_COLORS.length];
            swatch.style.background = _currentColor;
        };
    }
}

function _renderList() {
    if (!_panel) return;
    const list = _panel.querySelector('.annotation-list');
    if (!list) return;

    if (_annotations.length === 0) {
        list.innerHTML = '<div class="ann-empty">No annotations on this layer</div>';
        return;
    }

    list.innerHTML = _annotations.map(a => `
        <div class="ann-item" data-id="${a.id}">
            <span class="ann-item-type" style="color:${a.color}">${a.type}</span>
            <span class="ann-item-text">${a.text || a.label || a.type}</span>
            <button class="ann-item-delete" data-id="${a.id}" title="Delete">\u2715</button>
        </div>
    `).join('');

    list.querySelectorAll('.ann-item-delete').forEach(btn => {
        btn.onclick = (e) => {
            e.stopPropagation();
            _deleteAnnotation(btn.dataset.id);
        };
    });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export function initAnnotationsPanel(container) {
    _panel = document.createElement('div');
    _panel.className = 'panel-content annotations-panel';
    _panel.innerHTML = `
        <div class="panel-header">MAP ANNOTATIONS</div>
        <div class="annotation-toolbar"></div>
        <div class="annotation-status"></div>
        <div class="annotation-list"></div>
    `;
    _panel._arrowStart = null;
    container.appendChild(_panel);

    _fetchAnnotations();
    _renderTools();

    EventBus.on('annotations:updated', () => {
        _renderList();
        _renderTools();
    });

    // Periodic refresh
    setInterval(_fetchAnnotations, 10000);

    return _panel;
}

export function destroyAnnotationsPanel() {
    if (_panel && _panel.parentNode) {
        _panel.parentNode.removeChild(_panel);
    }
    _panel = null;
}

export function getAnnotations() {
    return _annotations;
}

export { setDrawMode, getDrawMode, handleMapClick, finishFreehand };

// PanelDef for PanelManager registration
export const AnnotationsPanelDef = {
    id: 'annotations',
    title: 'ANNOTATIONS',
    label: 'ANNOTATIONS',
    icon: '\u270F',
    group: 'map',
    init(container) { return initAnnotationsPanel(container); },
    destroy() { destroyAnnotationsPanel(); },
};
