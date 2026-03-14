// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Operator Activity Panel — shows real-time who is doing what
//
// Displays operator actions: logins, target updates, investigations,
// cursor movements. Polls /api/operator-activity for recent entries.

import { EventBus } from '../events.js';

const POLL_INTERVAL_MS = 5000;
const MAX_ENTRIES = 50;

let _container = null;
let _pollTimer = null;
let _entries = [];

const ROLE_COLORS = {
    admin: '#fcee0a',
    commander: '#ff2a6d',
    analyst: '#00f0ff',
    operator: '#05ffa1',
    observer: '#8888aa',
};

function _roleColor(role) {
    return ROLE_COLORS[role] || '#888';
}

function _formatTs(ts) {
    if (!ts) return '??:??';
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function _renderEntry(entry) {
    const color = _roleColor(entry.role);
    const time = _formatTs(entry.timestamp);
    const action = entry.action || '';
    const detail = entry.detail || '';
    const username = entry.username || 'unknown';

    return `<div class="op-activity-entry" style="border-left: 3px solid ${color}; padding: 4px 8px; margin: 2px 0;">
        <span style="color: #555; font-size: 11px;">${time}</span>
        <span style="color: ${color}; font-weight: bold; margin: 0 4px;">${username}</span>
        <span style="color: #aaa;">${action}</span>
        ${detail ? `<div style="color: #777; font-size: 11px; padding-left: 8px;">${detail}</div>` : ''}
    </div>`;
}

function _render() {
    if (!_container) return;
    if (_entries.length === 0) {
        _container.innerHTML = '<div style="color: #555; padding: 20px; text-align: center;">No operator activity yet</div>';
        return;
    }
    _container.innerHTML = _entries.map(_renderEntry).join('');
}

async function _poll() {
    try {
        const resp = await fetch('/api/operator-activity?limit=50');
        if (!resp.ok) return;
        const data = await resp.json();
        _entries = data.activities || [];
        _render();
    } catch (e) {
        // silent
    }
}

export function initOperatorActivityPanel(container) {
    _container = container;
    _container.innerHTML = '<div style="color: #555; padding: 20px; text-align: center;">Loading operator activity...</div>';

    // Initial fetch
    _poll();

    // Poll for updates
    _pollTimer = setInterval(_poll, POLL_INTERVAL_MS);

    // Listen for real-time cursor events
    EventBus.on('operator:cursor', (cursor) => {
        // Could add cursor movement to activity feed if desired
    });

    return { destroy };
}

export function destroy() {
    if (_pollTimer) {
        clearInterval(_pollTimer);
        _pollTimer = null;
    }
    _container = null;
    _entries = [];
}
