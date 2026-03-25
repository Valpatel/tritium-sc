// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Testing Dashboard Panel
// Shows test pass/fail/skip counts with trend arrows, module breakdown,
// untested modules, and coverage gaps. Polls /api/testing/report.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


function _arrow(delta) {
    if (delta === undefined || delta === null) return '';
    if (delta > 0) return `<span style="color:var(--green)">+${delta}</span>`;
    if (delta < 0) return `<span style="color:var(--magenta)">${delta}</span>`;
    return '<span style="color:var(--text-ghost)">0</span>';
}

function _pct(passed, total) {
    if (!total) return 'N/A';
    return `${Math.round(100 * passed / total)}%`;
}

function _barColor(pct) {
    if (pct >= 90) return 'var(--green)';
    if (pct >= 70) return 'var(--amber, #fcee0a)';
    return 'var(--magenta)';
}

export const TestingPanelDef = {
    id: 'testing',
    title: 'TESTING',
    defaultPosition: { x: 340, y: 8 },
    defaultSize: { w: 420, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'testing-panel-inner';
        el.innerHTML = `
            <div class="sys-tabs" role="tablist">
                <button class="sys-tab active" data-tab="overview" role="tab">OVERVIEW</button>
                <button class="sys-tab" data-tab="modules" role="tab">MODULES</button>
                <button class="sys-tab" data-tab="gaps" role="tab">GAPS</button>
            </div>
            <div class="sys-tab-content">
                <div class="sys-tab-pane" data-pane="overview" style="display:block">
                    <div class="testing-toolbar">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="run-tests">RUN TESTS</button>
                        <button class="panel-action-btn" data-action="refresh-report">REFRESH</button>
                    </div>
                    <div class="testing-status" data-bind="test-status"></div>
                    <div class="testing-summary" data-bind="test-summary">
                        <div class="panel-empty">No report available. Click RUN TESTS.</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="modules" style="display:none">
                    <div class="testing-modules" data-bind="test-modules">
                        <div class="panel-empty">No module data available</div>
                    </div>
                </div>
                <div class="sys-tab-pane" data-pane="gaps" style="display:none">
                    <div class="testing-gaps" data-bind="test-gaps">
                        <div class="panel-empty">No coverage data available</div>
                    </div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const tabs = bodyEl.querySelectorAll('.sys-tab');
        const panes = bodyEl.querySelectorAll('.sys-tab-pane');
        const summaryEl = bodyEl.querySelector('[data-bind="test-summary"]');
        const modulesEl = bodyEl.querySelector('[data-bind="test-modules"]');
        const gapsEl = bodyEl.querySelector('[data-bind="test-gaps"]');
        const statusEl = bodyEl.querySelector('[data-bind="test-status"]');

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const tabName = tab.dataset.tab;
                panes.forEach(p => {
                    p.style.display = p.dataset.pane === tabName ? 'block' : 'none';
                });
            });
        });

        function renderSummary(report) {
            if (!summaryEl) return;
            if (!report || !report.totals) {
                summaryEl.innerHTML = '<div class="panel-empty">No report available. Click RUN TESTS.</div>';
                return;
            }

            const t = report.totals;
            const trend = report.trend || {};
            const passRate = t.total > 0 ? Math.round(100 * t.passed / t.total) : 0;
            const barCol = _barColor(passRate);

            let html = `
                <div class="testing-cards">
                    <div class="testing-card">
                        <div class="panel-stat-label">TOTAL</div>
                        <div class="testing-big-number" style="color:var(--cyan)">${t.total}</div>
                        <div class="testing-trend">${_arrow(trend.total_delta)}</div>
                    </div>
                    <div class="testing-card">
                        <div class="panel-stat-label">PASSED</div>
                        <div class="testing-big-number" style="color:var(--green)">${t.passed}</div>
                        <div class="testing-trend">${_arrow(trend.passed_delta)}</div>
                    </div>
                    <div class="testing-card">
                        <div class="panel-stat-label">FAILED</div>
                        <div class="testing-big-number" style="color:var(--magenta)">${t.failed}</div>
                        <div class="testing-trend">${_arrow(trend.failed_delta)}</div>
                    </div>
                    <div class="testing-card">
                        <div class="panel-stat-label">SKIPPED</div>
                        <div class="testing-big-number" style="color:var(--text-ghost)">${t.skipped}</div>
                    </div>
                </div>

                <div class="sys-metric-bar" style="margin-top:8px">
                    <span class="panel-stat-label">PASS RATE</span>
                    <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${passRate}%;background:${barCol}"></div></div>
                    <span class="mono" style="font-size:0.5rem;min-width:32px;text-align:right;color:${barCol}">${passRate}%</span>
                </div>
            `;

            // Per-project summary
            const projects = report.projects || {};
            for (const [name, proj] of Object.entries(projects)) {
                const pRate = proj.total > 0 ? Math.round(100 * proj.passed / proj.total) : 0;
                const pCol = _barColor(pRate);
                html += `
                    <div class="panel-section-label" style="margin-top:10px">${_esc(name.toUpperCase())}</div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">Tests</span>
                        <span class="panel-stat-value mono">${proj.total} (${proj.passed}P / ${proj.failed}F / ${proj.skipped}S)</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">Duration</span>
                        <span class="panel-stat-value mono">${proj.duration_s}s</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">Density</span>
                        <span class="panel-stat-value mono">${proj.density} tests/src</span>
                    </div>
                    <div class="sys-metric-bar">
                        <span class="panel-stat-label">Pass</span>
                        <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${pRate}%;background:${pCol}"></div></div>
                        <span class="mono" style="font-size:0.5rem;min-width:28px;text-align:right;color:${pCol}">${pRate}%</span>
                    </div>
                `;
            }

            // Timestamp
            html += `<div class="panel-stat-row" style="margin-top:8px">
                <span class="panel-stat-label">GENERATED</span>
                <span class="panel-stat-value mono" style="font-size:0.45rem;color:var(--text-ghost)">${_esc(report.timestamp || '')}</span>
            </div>`;

            if (trend.duration_delta !== undefined) {
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">DURATION DELTA</span>
                    <span class="panel-stat-value mono">${_arrow(trend.duration_delta)}s</span>
                </div>`;
            }

            summaryEl.innerHTML = html;
        }

        function renderModules(report) {
            if (!modulesEl) return;
            const projects = report?.projects || {};
            let html = '';

            for (const [projName, proj] of Object.entries(projects)) {
                const modules = proj.by_module || {};
                const entries = Object.entries(modules).sort((a, b) => {
                    // Sort failures first
                    return (b[1].failed || 0) - (a[1].failed || 0);
                });

                if (entries.length === 0) continue;

                html += `<div class="panel-section-label">${_esc(projName.toUpperCase())}</div>`;
                for (const [mod, counts] of entries) {
                    const total = (counts.passed || 0) + (counts.failed || 0) + (counts.skipped || 0);
                    const hasFail = (counts.failed || 0) > 0;
                    const dotClass = hasFail ? 'panel-dot-amber' : 'panel-dot-green';
                    html += `<div class="panel-stat-row">
                        <span class="panel-dot ${dotClass}"></span>
                        <span class="panel-stat-label" style="flex:1;font-size:0.5rem;overflow:hidden;text-overflow:ellipsis" title="${_esc(mod)}">${_esc(mod)}</span>
                        <span class="mono" style="font-size:0.45rem;color:var(--green)">${counts.passed || 0}P</span>
                        <span class="mono" style="font-size:0.45rem;color:${hasFail ? 'var(--magenta)' : 'var(--text-ghost)'};margin-left:4px">${counts.failed || 0}F</span>
                    </div>`;
                }
            }

            modulesEl.innerHTML = html || '<div class="panel-empty">No module data</div>';
        }

        function renderGaps(report) {
            if (!gapsEl) return;
            const projects = report?.projects || {};
            let html = '';

            for (const [projName, proj] of Object.entries(projects)) {
                const untested = proj.untested_modules || [];
                const srcCount = proj.source_files || 0;
                const testCount = proj.test_files || 0;
                const density = proj.density || 0;

                html += `<div class="panel-section-label">${_esc(projName.toUpperCase())}</div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">Source Files</span>
                    <span class="panel-stat-value mono">${srcCount}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">Test Files</span>
                    <span class="panel-stat-value mono">${testCount}</span>
                </div>`;
                html += `<div class="panel-stat-row">
                    <span class="panel-stat-label">Test Density</span>
                    <span class="panel-stat-value mono" style="color:${density >= 0.8 ? 'var(--green)' : density >= 0.5 ? 'var(--amber, #fcee0a)' : 'var(--magenta)'}">${density}</span>
                </div>`;

                // Coverage bar
                const covPct = srcCount > 0 ? Math.round(100 * (srcCount - untested.length) / srcCount) : 0;
                const covCol = _barColor(covPct);
                html += `<div class="sys-metric-bar">
                    <span class="panel-stat-label">Coverage</span>
                    <div class="panel-bar" style="flex:1"><div class="panel-bar-fill" style="width:${covPct}%;background:${covCol}"></div></div>
                    <span class="mono" style="font-size:0.5rem;min-width:28px;text-align:right;color:${covCol}">${covPct}%</span>
                </div>`;

                if (untested.length > 0) {
                    html += `<div class="panel-section-label" style="margin-top:6px;color:var(--magenta)">UNTESTED (${untested.length})</div>`;
                    for (const mod of untested.slice(0, 30)) {
                        html += `<div class="panel-stat-row" style="padding:2px 0">
                            <span class="panel-dot panel-dot-amber"></span>
                            <span class="mono" style="font-size:0.45rem;color:var(--text-ghost)">${_esc(mod)}</span>
                        </div>`;
                    }
                    if (untested.length > 30) {
                        html += `<div class="panel-stat-row" style="padding:2px 0">
                            <span class="mono" style="font-size:0.45rem;color:var(--text-ghost)">... +${untested.length - 30} more</span>
                        </div>`;
                    }
                } else {
                    html += `<div class="panel-stat-row" style="color:var(--green)">All source modules have tests</div>`;
                }
            }

            gapsEl.innerHTML = html || '<div class="panel-empty">No coverage data</div>';
        }

        function renderAll(report) {
            renderSummary(report);
            renderModules(report);
            renderGaps(report);
        }

        async function fetchReport() {
            try {
                const resp = await fetch('/api/testing/report');
                if (!resp.ok) {
                    renderAll(null);
                    return;
                }
                const data = await resp.json();
                renderAll(data);
            } catch (_) {
                renderAll(null);
            }
        }

        async function runTests() {
            if (statusEl) {
                statusEl.innerHTML = '<div class="panel-stat-row"><span class="panel-stat-label" style="color:var(--cyan)">Running tests...</span></div>';
            }
            const runBtn = bodyEl.querySelector('[data-action="run-tests"]');
            if (runBtn) runBtn.disabled = true;

            try {
                const resp = await fetch('/api/testing/run', { method: 'POST' });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    if (statusEl) statusEl.innerHTML = `<div class="panel-stat-row"><span style="color:var(--magenta)">${_esc(err.error || 'Run failed')}</span></div>`;
                    EventBus.emit('toast:show', { message: 'Test run failed', type: 'alert' });
                    return;
                }
                const data = await resp.json();
                if (statusEl) statusEl.innerHTML = '';
                renderAll(data);
                const total = data.totals?.total || 0;
                const failed = data.totals?.failed || 0;
                const msg = failed > 0 ? `Tests done: ${failed} failed / ${total} total` : `Tests done: all ${total} passed`;
                const type = failed > 0 ? 'alert' : 'info';
                EventBus.emit('toast:show', { message: msg, type });
            } catch (err) {
                if (statusEl) statusEl.innerHTML = `<div class="panel-stat-row"><span style="color:var(--magenta)">Error: ${_esc(String(err))}</span></div>`;
            } finally {
                if (runBtn) runBtn.disabled = false;
            }
        }

        // Wire buttons
        bodyEl.querySelector('[data-action="run-tests"]')?.addEventListener('click', runTests);
        bodyEl.querySelector('[data-action="refresh-report"]')?.addEventListener('click', fetchReport);

        // Initial load
        fetchReport();
    },

    unmount(bodyEl) {
        // No intervals to clean up
    },
};
