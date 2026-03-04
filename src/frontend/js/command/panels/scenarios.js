// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Scenario Runner Panel
// Behavioral testing from the UI. Lists scenarios, shows run history,
// launches test runs with live progress.
// Uses /api/scenarios endpoints.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const ScenariosPanelDef = {
    id: 'scenarios',
    title: 'SCENARIOS',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 320, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'scenarios-panel-inner';
        el.innerHTML = `
            <div class="scn-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="run-all" title="Run all scenarios">RUN ALL</button>
            </div>
            <div class="scn-stats" data-bind="stats"></div>
            <ul class="panel-list scn-list" data-bind="scenario-list" role="listbox" aria-label="Behavioral scenarios">
                <li class="panel-empty">Loading scenarios...</li>
            </ul>
            <div class="scn-run-progress" data-bind="run-progress" style="display:none">
                <div class="panel-section-label">RUNNING</div>
                <div class="scn-progress-bar">
                    <div class="panel-bar">
                        <div class="panel-bar-fill" data-bind="progress-fill" style="width:0%;background:var(--cyan)"></div>
                        <span class="panel-bar-label" data-bind="progress-label">0%</span>
                    </div>
                </div>
                <div class="mono scn-progress-status" data-bind="progress-status" style="font-size:0.5rem;color:var(--text-dim);margin-top:4px"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="scenario-list"]');
        const statsEl = bodyEl.querySelector('[data-bind="stats"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const runAllBtn = bodyEl.querySelector('[data-action="run-all"]');
        const progressEl = bodyEl.querySelector('[data-bind="run-progress"]');
        const progressFill = bodyEl.querySelector('[data-bind="progress-fill"]');
        const progressLabel = bodyEl.querySelector('[data-bind="progress-label"]');
        const progressStatus = bodyEl.querySelector('[data-bind="progress-status"]');

        let scenarios = [];
        let running = false;

        function renderStats() {
            if (!statsEl) return;
            fetch('/api/scenarios/stats').then(r => r.ok ? r.json() : null).then(data => {
                if (!data) {
                    statsEl.innerHTML = '';
                    return;
                }
                const total = data.total_scenarios || 0;
                const runs = data.total_runs || 0;
                const mean = data.mean_score !== undefined ? (data.mean_score * 100).toFixed(1) : '--';
                statsEl.innerHTML = `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">SCENARIOS</span>
                        <span class="panel-stat-value">${total}</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">TOTAL RUNS</span>
                        <span class="panel-stat-value">${runs}</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">MEAN SCORE</span>
                        <span class="panel-stat-value" style="color:${parseFloat(mean) > 80 ? 'var(--green)' : 'var(--amber)'}">${mean}%</span>
                    </div>
                `;
            }).catch(() => {});
        }

        function renderScenarios() {
            if (!listEl) return;
            if (scenarios.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No scenarios found</li>';
                return;
            }

            listEl.innerHTML = scenarios.map(s => {
                const name = s.name || s;
                const dotClass = s.last_score !== undefined
                    ? (s.last_score >= 0.8 ? 'panel-dot-green' : s.last_score >= 0.5 ? 'panel-dot-amber' : 'panel-dot-red')
                    : 'panel-dot-neutral';
                const scoreText = s.last_score !== undefined ? `${(s.last_score * 100).toFixed(0)}%` : '--';
                return `<li class="panel-list-item scn-item" data-scenario="${_esc(typeof s === 'string' ? s : s.name)}" role="option">
                    <span class="panel-dot ${dotClass}"></span>
                    <span class="scn-item-name" style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${_esc(typeof s === 'string' ? s : s.name)}</span>
                    <span class="mono" style="font-size:0.5rem;color:var(--text-dim)">${scoreText}</span>
                    <button class="panel-action-btn scn-run-btn" data-action="run-one" data-scenario="${_esc(typeof s === 'string' ? s : s.name)}" title="Run">&#9654;</button>
                </li>`;
            }).join('');

            listEl.querySelectorAll('[data-action="run-one"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    runScenario(btn.dataset.scenario);
                });
            });
        }

        async function fetchScenarios() {
            try {
                const resp = await fetch('/api/scenarios');
                if (!resp.ok) {
                    scenarios = [];
                    renderScenarios();
                    return;
                }
                const data = await resp.json();
                scenarios = Array.isArray(data) ? data : (data.scenarios || []);
                renderScenarios();
            } catch (_) {
                scenarios = [];
                renderScenarios();
            }
            renderStats();
        }

        async function runScenario(name) {
            if (running) return;
            running = true;
            if (progressEl) progressEl.style.display = '';
            if (progressStatus) progressStatus.textContent = `Running: ${name}...`;
            if (progressFill) progressFill.style.width = '50%';
            if (progressLabel) progressLabel.textContent = '...';

            try {
                const resp = await fetch('/api/scenarios/run', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name }),
                });
                const data = await resp.json();
                const score = data.score !== undefined ? (data.score * 100).toFixed(0) : '--';
                if (progressFill) progressFill.style.width = '100%';
                if (progressLabel) progressLabel.textContent = `${score}%`;
                if (progressStatus) progressStatus.textContent = `${name}: ${score}% (${data.verdict || 'done'})`;
                EventBus.emit('toast:show', {
                    message: `Scenario "${name}": ${score}%`,
                    type: parseFloat(score) >= 80 ? 'info' : 'alert',
                });
            } catch (e) {
                if (progressStatus) progressStatus.textContent = `Failed: ${e.message}`;
                EventBus.emit('toast:show', { message: `Scenario failed: ${name}`, type: 'alert' });
            }

            running = false;
            fetchScenarios();
            setTimeout(() => {
                if (progressEl) progressEl.style.display = 'none';
            }, 5000);
        }

        async function runAll() {
            if (running) return;
            running = true;
            if (runAllBtn) {
                runAllBtn.disabled = true;
                runAllBtn.textContent = 'RUNNING...';
            }
            if (progressEl) progressEl.style.display = '';

            const total = scenarios.length;
            let completed = 0;

            for (const s of scenarios) {
                const name = typeof s === 'string' ? s : s.name;
                if (progressStatus) progressStatus.textContent = `Running: ${name} (${completed + 1}/${total})`;
                const pct = Math.round((completed / total) * 100);
                if (progressFill) progressFill.style.width = `${pct}%`;
                if (progressLabel) progressLabel.textContent = `${pct}%`;

                try {
                    await fetch('/api/scenarios/run', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name }),
                    });
                } catch (_) {}
                completed++;
            }

            if (progressFill) progressFill.style.width = '100%';
            if (progressLabel) progressLabel.textContent = '100%';
            if (progressStatus) progressStatus.textContent = `All ${total} scenarios complete`;

            running = false;
            if (runAllBtn) {
                runAllBtn.disabled = false;
                runAllBtn.textContent = 'RUN ALL';
            }
            fetchScenarios();
            setTimeout(() => {
                if (progressEl) progressEl.style.display = 'none';
            }, 5000);
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchScenarios);
        if (runAllBtn) runAllBtn.addEventListener('click', runAll);

        fetchScenarios();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
