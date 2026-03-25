// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Data Export Scheduler Panel
// Configure automatic periodic exports:
//   - Hourly/daily targets CSV
//   - Daily dossier summary
//   - Weekly investigation reports
// Uses existing export APIs.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// Scheduled exports persisted in localStorage
const STORAGE_KEY = 'tritium-export-schedules';
let _schedules = [];
let _timers = {};  // scheduleId -> intervalId

function _loadSchedules() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        _schedules = raw ? JSON.parse(raw) : [];
    } catch (_) {
        _schedules = [];
    }
}

function _saveSchedules() {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(_schedules));
    } catch (_) {}
}

function _generateId() {
    return 'exp_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

export const ExportSchedulerPanelDef = {
    id: 'export-scheduler',
    title: 'EXPORT SCHEDULER',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 420, h: 440 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'export-sched-inner';
        el.innerHTML = `
            <div class="exps-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="exps-add">+ NEW SCHEDULE</button>
                <button class="panel-action-btn" data-action="exps-export-now">EXPORT NOW</button>
            </div>
            <ul class="panel-list exps-list" data-bind="exps-list">
                <li class="panel-empty">Loading schedules...</li>
            </ul>
            <div class="exps-form" data-bind="exps-form" hidden>
                <div class="exps-form-title mono" style="color:var(--cyan)">NEW EXPORT SCHEDULE</div>
                <div class="exps-form-row">
                    <label class="mono" style="font-size:0.55rem">NAME</label>
                    <input type="text" class="exps-input" placeholder="Daily Targets" data-bind="exps-name" spellcheck="false">
                </div>
                <div class="exps-form-row">
                    <label class="mono" style="font-size:0.55rem">TYPE</label>
                    <select class="exps-select" data-bind="exps-type">
                        <option value="targets_csv">Targets CSV</option>
                        <option value="targets_json">Targets JSON</option>
                        <option value="targets_geojson">Targets GeoJSON</option>
                        <option value="dossier_summary">Dossier Summary</option>
                        <option value="investigation_report">Investigation Report</option>
                    </select>
                </div>
                <div class="exps-form-row">
                    <label class="mono" style="font-size:0.55rem">INTERVAL</label>
                    <select class="exps-select" data-bind="exps-interval">
                        <option value="3600000">Hourly</option>
                        <option value="86400000">Daily</option>
                        <option value="604800000">Weekly</option>
                    </select>
                </div>
                <div class="exps-form-row">
                    <label class="mono" style="font-size:0.55rem">FORMAT</label>
                    <select class="exps-select" data-bind="exps-format">
                        <option value="csv">CSV</option>
                        <option value="json">JSON</option>
                        <option value="geojson">GeoJSON</option>
                    </select>
                </div>
                <div class="exps-form-actions">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="exps-save">SAVE</button>
                    <button class="panel-action-btn" data-action="exps-cancel">CANCEL</button>
                </div>
            </div>
            <div class="exps-history" data-bind="exps-history">
                <div class="exps-history-title mono" style="color:var(--text-dim);font-size:0.55rem">RECENT EXPORTS</div>
                <ul class="panel-list exps-history-list" data-bind="exps-history-list"></ul>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="exps-list"]');
        const formEl = bodyEl.querySelector('[data-bind="exps-form"]');
        const historyListEl = bodyEl.querySelector('[data-bind="exps-history-list"]');

        const nameInput = bodyEl.querySelector('[data-bind="exps-name"]');
        const typeSelect = bodyEl.querySelector('[data-bind="exps-type"]');
        const intervalSelect = bodyEl.querySelector('[data-bind="exps-interval"]');
        const formatSelect = bodyEl.querySelector('[data-bind="exps-format"]');

        const addBtn = bodyEl.querySelector('[data-action="exps-add"]');
        const exportNowBtn = bodyEl.querySelector('[data-action="exps-export-now"]');
        const saveBtn = bodyEl.querySelector('[data-action="exps-save"]');
        const cancelBtn = bodyEl.querySelector('[data-action="exps-cancel"]');

        let exportHistory = [];

        _loadSchedules();

        function renderList() {
            if (!listEl) return;
            if (_schedules.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No export schedules configured</li>';
                return;
            }

            const intervalLabels = {
                '3600000': 'Hourly',
                '86400000': 'Daily',
                '604800000': 'Weekly',
            };

            listEl.innerHTML = _schedules.map(s => {
                const intervalLabel = intervalLabels[String(s.interval_ms)] || `${Math.round(s.interval_ms / 60000)}min`;
                const running = _timers[s.id] ? 'ACTIVE' : 'PAUSED';
                const runColor = _timers[s.id] ? 'var(--green)' : 'var(--text-dim)';
                return `<li class="panel-list-item exps-item" data-schedule-id="${_esc(s.id)}">
                    <span class="panel-icon-badge" style="color:var(--cyan);border-color:var(--cyan)">E</span>
                    <span class="exps-item-info">
                        <span class="exps-item-name">${_esc(s.name)}</span>
                        <span class="mono" style="font-size:0.5rem;color:var(--text-dim)">${_esc(s.type)} | ${intervalLabel} | ${s.format}</span>
                    </span>
                    <span class="mono" style="font-size:0.5rem;color:${runColor}">${running}</span>
                    <button class="panel-btn exps-toggle" data-action="toggle" data-id="${_esc(s.id)}" title="Toggle schedule">${_timers[s.id] ? '||' : '>'}</button>
                    <button class="panel-btn exps-run" data-action="run-now" data-id="${_esc(s.id)}" title="Run now">RUN</button>
                    <button class="panel-btn exps-delete" data-action="delete" data-id="${_esc(s.id)}" title="Delete">&times;</button>
                </li>`;
            }).join('');

            // Wire buttons
            listEl.querySelectorAll('[data-action="toggle"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleSchedule(btn.dataset.id);
                });
            });
            listEl.querySelectorAll('[data-action="run-now"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    runExport(btn.dataset.id);
                });
            });
            listEl.querySelectorAll('[data-action="delete"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteSchedule(btn.dataset.id);
                });
            });
        }

        function renderHistory() {
            if (!historyListEl) return;
            if (exportHistory.length === 0) {
                historyListEl.innerHTML = '<li class="panel-empty" style="font-size:0.55rem">No exports yet</li>';
                return;
            }
            historyListEl.innerHTML = exportHistory.slice(-10).reverse().map(h => {
                const statusColor = h.success ? 'var(--green)' : 'var(--magenta)';
                return `<li class="panel-list-item" style="font-size:0.55rem">
                    <span class="mono" style="color:${statusColor}">${h.success ? 'OK' : 'FAIL'}</span>
                    <span class="mono">${_esc(h.name)} (${h.format})</span>
                    <span class="mono" style="color:var(--text-dim)">${h.time}</span>
                </li>`;
            }).join('');
        }

        function showForm() {
            if (formEl) formEl.hidden = false;
            if (nameInput) nameInput.value = '';
        }

        function hideForm() {
            if (formEl) formEl.hidden = true;
        }

        function saveSchedule() {
            const schedule = {
                id: _generateId(),
                name: nameInput?.value.trim() || 'Untitled Export',
                type: typeSelect?.value || 'targets_csv',
                interval_ms: parseInt(intervalSelect?.value) || 86400000,
                format: formatSelect?.value || 'csv',
                enabled: true,
                created: new Date().toISOString(),
            };
            _schedules.push(schedule);
            _saveSchedules();
            hideForm();
            startSchedule(schedule);
            renderList();
        }

        function deleteSchedule(id) {
            stopSchedule(id);
            _schedules = _schedules.filter(s => s.id !== id);
            _saveSchedules();
            renderList();
        }

        function toggleSchedule(id) {
            if (_timers[id]) {
                stopSchedule(id);
            } else {
                const sched = _schedules.find(s => s.id === id);
                if (sched) startSchedule(sched);
            }
            renderList();
        }

        function startSchedule(sched) {
            if (_timers[sched.id]) return;
            _timers[sched.id] = setInterval(() => {
                runExport(sched.id);
            }, sched.interval_ms);
        }

        function stopSchedule(id) {
            if (_timers[id]) {
                clearInterval(_timers[id]);
                delete _timers[id];
            }
        }

        async function runExport(scheduleId) {
            const sched = _schedules.find(s => s.id === scheduleId);
            if (!sched) return;

            const exportType = sched.type;
            const format = sched.format;
            let url = '';
            let filename = '';

            const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);

            if (exportType.startsWith('targets_')) {
                url = `/api/targets/export?format=${format}`;
                filename = `targets_${ts}.${format}`;
            } else if (exportType === 'dossier_summary') {
                url = '/api/dossiers?limit=1000';
                filename = `dossiers_${ts}.json`;
            } else if (exportType === 'investigation_report') {
                url = '/api/dossiers?limit=1000';
                filename = `report_${ts}.json`;
            }

            try {
                const resp = await fetch(url);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(blobUrl);

                exportHistory.push({
                    name: sched.name, format, time: _ts(),
                    success: true, scheduleId,
                });
                renderHistory();

                EventBus.emit('toast:show', {
                    message: `Export complete: ${filename}`,
                    type: 'info',
                });
            } catch (e) {
                exportHistory.push({
                    name: sched.name, format, time: _ts(),
                    success: false, scheduleId,
                });
                renderHistory();

                EventBus.emit('toast:show', {
                    message: `Export failed: ${sched.name}`,
                    type: 'alert',
                });
            }
        }

        function _ts() {
            return new Date().toTimeString().slice(0, 8);
        }

        async function exportNow() {
            // Quick export: download current targets as CSV
            try {
                const resp = await fetch('/api/targets/export?format=csv');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const blob = await resp.blob();
                const ts = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
                const blobUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `targets_${ts}.csv`;
                a.click();
                URL.revokeObjectURL(blobUrl);

                EventBus.emit('toast:show', {
                    message: 'Targets exported as CSV',
                    type: 'info',
                });
            } catch (_) {
                EventBus.emit('toast:show', {
                    message: 'Export failed',
                    type: 'alert',
                });
            }
        }

        // Wire buttons
        if (addBtn) addBtn.addEventListener('click', showForm);
        if (cancelBtn) cancelBtn.addEventListener('click', hideForm);
        if (saveBtn) saveBtn.addEventListener('click', saveSchedule);
        if (exportNowBtn) exportNowBtn.addEventListener('click', exportNow);

        // Start any enabled schedules
        for (const sched of _schedules) {
            if (sched.enabled) startSchedule(sched);
        }

        // Cleanup all timers on unmount
        panel._unsubs.push(() => {
            for (const id of Object.keys(_timers)) {
                clearInterval(_timers[id]);
            }
            _timers = {};
        });

        renderList();
        renderHistory();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
