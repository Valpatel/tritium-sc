// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Panel Utilities -- shared helpers used across all panel modules.
// Canonical source: tritium-lib/web/utils.js
// This file is kept for backward compatibility with test sandboxes that
// load it via fs.readFileSync. New code should import from '/lib/utils.js'.

/**
 * HTML-escape a string to prevent XSS when inserting into innerHTML.
 * @param {string} text
 * @returns {string} Escaped HTML string
 */
export function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

/**
 * Format a Unix timestamp (seconds) as a human-readable relative time.
 * @param {number} ts Unix timestamp in seconds
 * @returns {string} e.g. "just now", "5s ago", "3m ago", "2h ago", "1d ago"
 */
export function _timeAgo(ts) {
    if (!ts) return 'never';
    const secs = Math.floor(Date.now() / 1000 - ts);
    if (secs < 5) return 'just now';
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
    if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
    return `${Math.floor(secs / 86400)}d ago`;
}

/**
 * Create a colored badge HTML string.
 * @param {string} label Badge text
 * @param {string} color CSS color value
 * @param {object} [opts] Optional: { title, style }
 * @returns {string} HTML string for a badge span
 */
export function _badge(label, color, opts) {
    const title = (opts && opts.title) ? ` title="${_esc(opts.title)}"` : '';
    const extra = (opts && opts.style) ? `;${opts.style}` : '';
    return `<span class="panel-badge" style="background:${color};color:#0a0a0f;padding:1px 5px;border-radius:3px;font-size:0.5rem;font-weight:bold${extra}"${title}>${_esc(label)}</span>`;
}

/**
 * Create a colored status dot HTML string.
 * @param {string} status One of: "online", "stale", "offline", or any other value
 * @returns {string} HTML string for a small colored dot
 */
export function _statusDot(status) {
    const colors = {
        online: 'var(--green, #05ffa1)',
        stale: 'var(--yellow, #fcee0a)',
        offline: 'var(--magenta, #ff2a6d)',
    };
    const color = colors[status] || 'var(--text-dim, #888)';
    return `<span class="panel-status-dot" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${color};margin-right:4px" title="${(status || 'unknown').toUpperCase()}"></span>`;
}

/**
 * Fetch JSON from an API endpoint with error handling.
 * @param {string} url API URL
 * @param {object} [opts] Fetch options (method, body, headers)
 * @returns {Promise<any>} Parsed JSON response
 * @throws {Error} On HTTP error or network failure
 */
export async function _fetchJson(url, opts) {
    const resp = await fetch(url, opts);
    if (!resp.ok) {
        const text = await resp.text().catch(() => '');
        throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
    }
    return resp.json();
}
