// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Notification Preferences Panel
// Configure which notification types are enabled and their severity thresholds.
// Uses NotificationRule from tritium-lib via the /api/notifications/preferences API.

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

const SEVERITY_OPTIONS = ['debug', 'info', 'warning', 'error', 'critical'];
const SEVERITY_COLORS = {
    debug:    '#888',
    info:     '#00f0ff',
    warning:  '#fcee0a',
    error:    '#ff6b35',
    critical: '#ff2a6d',
};

export const NotificationPrefsPanelDef = {
    id: 'notification-prefs',
    title: 'NOTIFICATION PREFERENCES',
    defaultPosition: { x: 200, y: 80 },
    defaultSize: { w: 380, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'notif-prefs-panel-inner';
        el.innerHTML = `
            <div class="panel-section-label" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <span>NOTIFICATION TYPES</span>
                <button class="panel-action-btn" data-action="reset" title="Reset to defaults">RESET</button>
            </div>
            <div data-bind="prefs-list" style="overflow-y:auto;max-height:420px"></div>
            <div data-bind="status" style="font-size:0.55rem;color:var(--text-ghost);margin-top:4px;text-align:center"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="prefs-list"]');
        const statusEl = bodyEl.querySelector('[data-bind="status"]');
        const resetBtn = bodyEl.querySelector('[data-action="reset"]');

        let prefs = {};

        function render() {
            if (!listEl) return;
            const types = Object.keys(prefs).sort();
            if (types.length === 0) {
                listEl.innerHTML = '<div style="color:var(--text-ghost);font-size:0.6rem;padding:8px">Loading preferences...</div>';
                return;
            }

            listEl.innerHTML = types.map(ntype => {
                const p = prefs[ntype];
                const label = _esc(p.label || ntype);
                const enabled = p.enabled !== false;
                const severity = p.severity || 'info';
                const sevColor = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;

                const sevOptions = SEVERITY_OPTIONS.map(s =>
                    `<option value="${s}" ${s === severity ? 'selected' : ''} style="color:${SEVERITY_COLORS[s]}">${s.toUpperCase()}</option>`
                ).join('');

                return `<div class="notif-pref-row" data-ntype="${_esc(ntype)}" style="
                    display:flex;align-items:center;gap:8px;padding:6px 8px;
                    border-bottom:1px solid rgba(0,240,255,0.1);
                    opacity:${enabled ? '1' : '0.5'}">
                    <label style="flex:0 0 auto;cursor:pointer" title="Enable/disable">
                        <input type="checkbox" class="notif-pref-toggle" ${enabled ? 'checked' : ''}
                               style="accent-color:#00f0ff;cursor:pointer">
                    </label>
                    <div style="flex:1;min-width:0">
                        <div style="font-size:0.65rem;font-weight:bold;color:var(--text-primary)">${label}</div>
                        <div style="font-size:0.5rem;color:var(--text-ghost)">${_esc(ntype)}</div>
                    </div>
                    <select class="notif-pref-severity" style="
                        background:var(--surface-0);color:${sevColor};border:1px solid rgba(0,240,255,0.3);
                        font-size:0.55rem;padding:2px 4px;border-radius:2px;cursor:pointer">
                        ${sevOptions}
                    </select>
                </div>`;
            }).join('');
        }

        async function loadPrefs() {
            try {
                const resp = await fetch('/api/notifications/preferences');
                if (resp.ok) {
                    prefs = await resp.json();
                    render();
                }
            } catch (e) {
                if (statusEl) statusEl.textContent = 'Failed to load preferences';
            }
        }

        async function updatePref(ntype, updates) {
            try {
                const body = {};
                body[ntype] = updates;
                const resp = await fetch('/api/notifications/preferences', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                if (resp.ok) {
                    const data = await resp.json();
                    prefs = data.preferences || prefs;
                    if (statusEl) {
                        statusEl.textContent = 'Updated: ' + ntype;
                        setTimeout(() => { statusEl.textContent = ''; }, 2000);
                    }
                }
            } catch (e) {
                if (statusEl) statusEl.textContent = 'Update failed: ' + e.message;
            }
        }

        // Event delegation for toggles and severity changes
        if (listEl) {
            listEl.addEventListener('change', (e) => {
                const row = e.target.closest('[data-ntype]');
                if (!row) return;
                const ntype = row.dataset.ntype;

                if (e.target.classList.contains('notif-pref-toggle')) {
                    const enabled = e.target.checked;
                    if (prefs[ntype]) prefs[ntype].enabled = enabled;
                    row.style.opacity = enabled ? '1' : '0.5';
                    updatePref(ntype, { enabled });
                }

                if (e.target.classList.contains('notif-pref-severity')) {
                    const severity = e.target.value;
                    if (prefs[ntype]) prefs[ntype].severity = severity;
                    e.target.style.color = SEVERITY_COLORS[severity] || SEVERITY_COLORS.info;
                    updatePref(ntype, { severity });
                }
            });
        }

        // Reset button
        if (resetBtn) {
            resetBtn.addEventListener('click', async () => {
                try {
                    const resp = await fetch('/api/notifications/preferences/reset', { method: 'POST' });
                    if (resp.ok) {
                        const data = await resp.json();
                        prefs = data.preferences || {};
                        render();
                        if (statusEl) statusEl.textContent = 'Preferences reset to defaults';
                    }
                } catch (e) {
                    if (statusEl) statusEl.textContent = 'Reset failed';
                }
            });
        }

        loadPrefs();
    },

    unmount(bodyEl) {
        // Cleaned up by Panel base class
    },
};
