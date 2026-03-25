// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Behavioral Intelligence Panel — pattern visualization, co-presence
// relationships, anomaly feed, and alert management.
// Backend API: /api/patterns/ (GET patterns, relationships, anomalies, alerts)

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const SEVERITY_COLORS = {
    critical: '#ff2a6d',
    high: '#ff6b35',
    medium: '#fcee0a',
    low: '#05ffa1',
    info: '#00f0ff',
};

export const BehavioralIntelligencePanelDef = {
    id: 'behavioral-intelligence',
    title: 'BEHAVIORAL INTEL',
    defaultPosition: { x: 8, y: 400 },
    defaultSize: { w: 380, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'behavior-panel-inner';
        el.innerHTML = `
            <div class="behavior-tabs" style="display:flex;gap:2px;padding:2px 4px;border-bottom:1px solid var(--border-dim)">
                <button class="panel-action-btn panel-action-btn-primary behavior-tab" data-tab="patterns">PATTERNS</button>
                <button class="panel-action-btn behavior-tab" data-tab="relationships">RELATIONS</button>
                <button class="panel-action-btn behavior-tab" data-tab="anomalies">ANOMALIES</button>
                <button class="panel-action-btn behavior-tab" data-tab="alerts">ALERTS</button>
            </div>
            <div class="behavior-stats" data-bind="stats" style="font-size:0.45rem;color:var(--text-ghost);padding:2px 4px"></div>
            <div class="behavior-content" data-bind="content" style="flex:1;overflow-y:auto;padding:4px"></div>
            <div class="behavior-heatmap" data-bind="heatmap" style="display:none;padding:4px"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="content"]');
        const statsEl = bodyEl.querySelector('[data-bind="stats"]');
        const heatmapEl = bodyEl.querySelector('[data-bind="heatmap"]');
        const tabs = bodyEl.querySelectorAll('.behavior-tab');

        let activeTab = 'patterns';
        let patterns = [];
        let relationships = [];
        let anomalies = [];
        let alerts = [];
        let stats = {};
        let selectedTarget = null;

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeTab = tab.dataset.tab;
                tabs.forEach(t => t.classList.remove('panel-action-btn-primary'));
                tab.classList.add('panel-action-btn-primary');
                heatmapEl.style.display = 'none';
                render();
            });
        });

        function render() {
            switch (activeTab) {
                case 'patterns': renderPatterns(); break;
                case 'relationships': renderRelationships(); break;
                case 'anomalies': renderAnomalies(); break;
                case 'alerts': renderAlerts(); break;
            }
            renderStats();
        }

        function renderStats() {
            if (!statsEl) return;
            statsEl.textContent = [
                `${stats.detected_patterns || 0} patterns`,
                `${stats.co_presence_relationships || 0} relations`,
                `${stats.total_anomalies || 0} anomalies`,
                `${stats.active_alerts || 0} alerts`,
            ].join(' | ');
        }

        function renderPatterns() {
            if (!contentEl) return;
            if (!patterns.length) {
                contentEl.innerHTML = '<div class="panel-empty">No patterns detected yet. Patterns emerge as targets are tracked over time.</div>';
                return;
            }
            contentEl.innerHTML = patterns.map(p => `
                <div class="behavior-card" style="border:1px solid var(--border-dim);margin-bottom:4px;padding:6px;border-radius:3px;cursor:pointer"
                     data-target="${_esc(p.target_id)}" data-pattern="${_esc(p.pattern_id)}">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:var(--cyan);font-size:0.5rem;font-weight:bold">${_esc(p.pattern_type.toUpperCase())}</span>
                        <span class="behavior-badge" style="background:${p.status === 'established' ? 'var(--green)' : 'var(--yellow)'};
                            color:#000;padding:1px 4px;font-size:0.4rem;border-radius:2px">${_esc(p.status)}</span>
                    </div>
                    <div style="color:var(--text-dim);font-size:0.45rem;margin-top:2px">
                        Target: <span style="color:var(--text-bright)">${_esc(p.target_id)}</span>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:2px;font-size:0.4rem;color:var(--text-ghost)">
                        <span>Conf: ${(p.confidence * 100).toFixed(0)}%</span>
                        <span>Obs: ${p.observation_count}</span>
                        <span>${_esc(p.frequency)}</span>
                    </div>
                    ${p.schedule ? `<div style="font-size:0.4rem;color:var(--text-ghost);margin-top:2px">
                        Schedule: ${p.schedule.hour_start}:${String(p.schedule.minute_start).padStart(2,'0')}-${p.schedule.hour_end}:${String(p.schedule.minute_end).padStart(2,'0')}
                    </div>` : ''}
                </div>
            `).join('');

            // Click to show heatmap
            contentEl.querySelectorAll('.behavior-card').forEach(card => {
                card.addEventListener('click', () => {
                    const tid = card.dataset.target;
                    if (tid) loadHeatmap(tid);
                });
            });
        }

        function renderRelationships() {
            if (!contentEl) return;
            if (!relationships.length) {
                contentEl.innerHTML = '<div class="panel-empty">No co-presence relationships detected yet. Relationships emerge when devices consistently appear together.</div>';
                return;
            }
            contentEl.innerHTML = relationships.map(r => {
                const confColor = r.confidence >= 0.8 ? 'var(--green)' : r.confidence >= 0.5 ? 'var(--yellow)' : 'var(--text-dim)';
                return `
                <div class="behavior-card" style="border:1px solid var(--border-dim);margin-bottom:4px;padding:6px;border-radius:3px">
                    <div style="display:flex;align-items:center;gap:6px">
                        <span style="color:var(--cyan);font-size:0.45rem">${_esc(r.target_a)}</span>
                        <span style="color:var(--magenta);font-size:0.5rem">&harr;</span>
                        <span style="color:var(--cyan);font-size:0.45rem">${_esc(r.target_b)}</span>
                    </div>
                    <div style="display:flex;gap:8px;margin-top:3px;font-size:0.4rem">
                        <span style="color:${confColor}">Confidence: ${(r.confidence * 100).toFixed(0)}%</span>
                        <span style="color:var(--text-ghost)">Temporal: ${(r.temporal_correlation * 100).toFixed(0)}%</span>
                        <span style="color:var(--text-ghost)">Co-seen: ${r.co_occurrence_count}x</span>
                    </div>
                    <div style="margin-top:3px;font-size:0.4rem;color:var(--text-ghost)">
                        Type: <span style="color:var(--green)">${_esc(r.relationship_type)}</span>
                        ${r.graph_edge_created ? '<span style="color:var(--green);margin-left:4px">[GRAPH]</span>' : ''}
                    </div>
                </div>`;
            }).join('');
        }

        function renderAnomalies() {
            if (!contentEl) return;
            if (!anomalies.length) {
                contentEl.innerHTML = '<div class="panel-empty">No anomalies detected. Anomalies appear when established patterns are broken.</div>';
                return;
            }
            contentEl.innerHTML = anomalies.map(a => {
                const scoreColor = a.deviation_score >= 0.7 ? '#ff2a6d' : a.deviation_score >= 0.4 ? '#fcee0a' : '#05ffa1';
                return `
                <div class="behavior-card" style="border:1px solid ${a.acknowledged ? 'var(--border-dim)' : scoreColor};margin-bottom:4px;padding:6px;border-radius:3px;
                    ${a.acknowledged ? 'opacity:0.6' : ''}">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:${scoreColor};font-size:0.5rem;font-weight:bold">${_esc(a.deviation_type.toUpperCase())}</span>
                        <span style="font-size:0.4rem;color:${scoreColor}">${(a.deviation_score * 100).toFixed(0)}% deviation</span>
                    </div>
                    <div style="color:var(--text-dim);font-size:0.45rem;margin-top:2px">
                        Target: <span style="color:var(--cyan)">${_esc(a.target_id)}</span>
                    </div>
                    <div style="font-size:0.4rem;color:var(--text-ghost);margin-top:2px">
                        Expected: ${_esc(a.expected_behavior)}
                    </div>
                    <div style="font-size:0.4rem;color:var(--text-bright);margin-top:1px">
                        Actual: ${_esc(a.actual_behavior)}
                    </div>
                    <div style="display:flex;gap:4px;margin-top:3px">
                        ${!a.acknowledged ? `<button class="panel-action-btn" data-action="ack" data-id="${_esc(a.anomaly_id)}" style="font-size:0.38rem">ACK</button>` : '<span style="font-size:0.38rem;color:var(--text-ghost)">ACKNOWLEDGED</span>'}
                        ${!a.alert_generated ? `<button class="panel-action-btn" data-action="create-alert" data-pattern="${_esc(a.pattern_id)}" data-target="${_esc(a.target_id)}" style="font-size:0.38rem">CREATE ALERT</button>` : ''}
                    </div>
                </div>`;
            }).join('');

            // Wire buttons
            contentEl.querySelectorAll('[data-action="ack"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const id = btn.dataset.id;
                    try {
                        await fetch(`/api/patterns/anomalies/${encodeURIComponent(id)}/acknowledge`, { method: 'POST' });
                        await loadAnomalies();
                        render();
                    } catch (err) { console.error('ACK failed:', err); }
                });
            });

            contentEl.querySelectorAll('[data-action="create-alert"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const patternId = btn.dataset.pattern;
                    const targetId = btn.dataset.target;
                    try {
                        await fetch('/api/patterns/alerts', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                pattern_id: patternId,
                                target_id: targetId,
                                name: `Alert: ${patternId}`,
                                severity: 'medium',
                            }),
                        });
                        await loadAlerts();
                        render();
                    } catch (err) { console.error('Create alert failed:', err); }
                });
            });
        }

        function renderAlerts() {
            if (!contentEl) return;
            if (!alerts.length) {
                contentEl.innerHTML = '<div class="panel-empty">No alert rules configured. Create alerts from detected patterns or anomalies.</div>';
                return;
            }
            contentEl.innerHTML = alerts.map(a => {
                const sColor = SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.info;
                return `
                <div class="behavior-card" style="border:1px solid ${a.enabled ? sColor : 'var(--border-dim)'};margin-bottom:4px;padding:6px;border-radius:3px;
                    ${a.enabled ? '' : 'opacity:0.5'}">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:${sColor};font-size:0.5rem;font-weight:bold">${_esc(a.name)}</span>
                        <span style="font-size:0.4rem;color:var(--text-ghost)">fired ${a.fire_count}x</span>
                    </div>
                    <div style="font-size:0.4rem;color:var(--text-ghost);margin-top:2px">
                        Pattern: ${_esc(a.pattern_id)} | Target: ${_esc(a.target_id)}
                    </div>
                    <div style="font-size:0.4rem;color:var(--text-ghost);margin-top:1px">
                        Threshold: ${(a.deviation_threshold * 100).toFixed(0)}% | Cooldown: ${(a.cooldown_seconds / 60).toFixed(0)}min
                    </div>
                    <div style="display:flex;gap:4px;margin-top:3px">
                        <button class="panel-action-btn" data-action="toggle" data-id="${_esc(a.alert_id)}" data-enabled="${a.enabled}" style="font-size:0.38rem">
                            ${a.enabled ? 'DISABLE' : 'ENABLE'}
                        </button>
                        <button class="panel-action-btn" data-action="delete-alert" data-id="${_esc(a.alert_id)}" style="font-size:0.38rem;color:#ff2a6d">DELETE</button>
                    </div>
                </div>`;
            }).join('');

            // Wire alert buttons
            contentEl.querySelectorAll('[data-action="toggle"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const id = btn.dataset.id;
                    const enabled = btn.dataset.enabled === 'true';
                    try {
                        await fetch(`/api/patterns/alerts/${encodeURIComponent(id)}`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ enabled: !enabled }),
                        });
                        await loadAlerts();
                        render();
                    } catch (err) { console.error('Toggle alert failed:', err); }
                });
            });

            contentEl.querySelectorAll('[data-action="delete-alert"]').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    e.stopPropagation();
                    const id = btn.dataset.id;
                    try {
                        await fetch(`/api/patterns/alerts/${encodeURIComponent(id)}`, { method: 'DELETE' });
                        await loadAlerts();
                        render();
                    } catch (err) { console.error('Delete alert failed:', err); }
                });
            });
        }

        // -- Heatmap rendering --

        function renderHeatmap(data) {
            if (!heatmapEl || !data) return;
            heatmapEl.style.display = 'block';

            const matrix = data.heatmap || [];
            const maxVal = Math.max(1, ...matrix.flat());

            let html = `<div style="font-size:0.45rem;color:var(--cyan);margin-bottom:4px;font-weight:bold">
                ACTIVITY HEATMAP: ${_esc(data.target_id)} (${data.total_sightings} sightings)
                <button class="panel-action-btn" data-action="close-heatmap" style="float:right;font-size:0.38rem">CLOSE</button>
            </div>`;
            html += '<div style="display:grid;grid-template-columns:40px repeat(24,1fr);gap:1px;font-size:0.35rem">';

            // Header row
            html += '<div></div>';
            for (let h = 0; h < 24; h++) {
                html += `<div style="text-align:center;color:var(--text-ghost)">${h}</div>`;
            }

            // Data rows
            for (let d = 0; d < 7; d++) {
                html += `<div style="color:var(--text-dim);line-height:14px">${DAYS[d]}</div>`;
                for (let h = 0; h < 24; h++) {
                    const val = (matrix[d] && matrix[d][h]) || 0;
                    const intensity = val / maxVal;
                    const bg = intensity === 0 ? 'transparent'
                        : intensity < 0.3 ? 'rgba(0,240,255,0.15)'
                        : intensity < 0.6 ? 'rgba(0,240,255,0.35)'
                        : intensity < 0.8 ? 'rgba(0,240,255,0.6)'
                        : 'rgba(0,240,255,0.9)';
                    html += `<div style="background:${bg};height:14px;border-radius:1px" title="${DAYS[d]} ${h}:00 - ${val} sightings"></div>`;
                }
            }
            html += '</div>';
            heatmapEl.innerHTML = html;

            heatmapEl.querySelector('[data-action="close-heatmap"]')?.addEventListener('click', () => {
                heatmapEl.style.display = 'none';
            });
        }

        // -- Data loading --

        async function loadPatterns() {
            try {
                const resp = await fetch('/api/patterns/');
                if (resp.ok) {
                    const data = await resp.json();
                    patterns = data.patterns || [];
                }
            } catch (err) { console.error('Load patterns failed:', err); }
        }

        async function loadRelationships() {
            try {
                const resp = await fetch('/api/patterns/relationships');
                if (resp.ok) {
                    const data = await resp.json();
                    relationships = data.relationships || [];
                }
            } catch (err) { console.error('Load relationships failed:', err); }
        }

        async function loadAnomalies() {
            try {
                const resp = await fetch('/api/patterns/anomalies?limit=50');
                if (resp.ok) {
                    const data = await resp.json();
                    anomalies = data.anomalies || [];
                }
            } catch (err) { console.error('Load anomalies failed:', err); }
        }

        async function loadAlerts() {
            try {
                const resp = await fetch('/api/patterns/alerts');
                if (resp.ok) {
                    const data = await resp.json();
                    alerts = data.alerts || [];
                }
            } catch (err) { console.error('Load alerts failed:', err); }
        }

        async function loadStats() {
            try {
                const resp = await fetch('/api/patterns/stats');
                if (resp.ok) {
                    stats = await resp.json();
                }
            } catch (err) { console.error('Load stats failed:', err); }
        }

        async function loadHeatmap(targetId) {
            try {
                const resp = await fetch(`/api/patterns/target/${encodeURIComponent(targetId)}/heatmap`);
                if (resp.ok) {
                    const data = await resp.json();
                    renderHeatmap(data);
                }
            } catch (err) { console.error('Load heatmap failed:', err); }
        }

        async function loadAll() {
            await Promise.all([
                loadPatterns(),
                loadRelationships(),
                loadAnomalies(),
                loadAlerts(),
                loadStats(),
            ]);
            render();
        }

        // Initial load
        loadAll();

        // Refresh every 15 seconds
        const interval = setInterval(loadAll, 15000);

        // Listen for behavioral events
        const unsub = EventBus.on('behavior:pattern_detected', () => loadPatterns().then(render));
        const unsub2 = EventBus.on('behavior:anomaly_detected', () => loadAnomalies().then(render));
        const unsub3 = EventBus.on('behavior:alert_fired', () => {
            loadAlerts().then(render);
            loadAnomalies().then(render);
        });

        panel._behaviorCleanup = () => {
            clearInterval(interval);
            unsub?.();
            unsub2?.();
            unsub3?.();
        };
    },

    destroy(panel) {
        panel._behaviorCleanup?.();
    },
};
