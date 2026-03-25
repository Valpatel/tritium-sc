// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Edge Intelligence Panel — shows per-edge-node ML metrics and pipeline health.
// Backend API: /api/intelligence/edge-metrics
// Polls every 10 seconds for updated metrics.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


export const EdgeIntelligencePanelDef = {
    id: 'edge-intelligence',
    title: 'EDGE INTELLIGENCE',
    defaultPosition: { x: 8, y: 460 },
    defaultSize: { w: 320, h: 400 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'edge-intel-panel-inner';
        el.innerHTML = `
            <div class="ei-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="prune">PRUNE STALE</button>
            </div>
            <div class="ei-summary" data-bind="summary" style="padding:2px 4px;font-size:0.48rem;color:#00f0ff"></div>
            <div class="ei-tab-bar" style="display:flex;gap:2px;margin:4px 0">
                <button class="panel-action-btn panel-action-btn-primary ei-tab" data-tab="nodes" style="flex:1;font-size:0.45rem">NODES</button>
                <button class="panel-action-btn ei-tab" data-tab="pipeline" style="flex:1;font-size:0.45rem">PIPELINE</button>
                <button class="panel-action-btn ei-tab" data-tab="feedback" style="flex:1;font-size:0.45rem">FEEDBACK</button>
            </div>
            <ul class="panel-list ei-list" data-bind="list" role="listbox" aria-label="Edge intelligence metrics">
                <li class="panel-empty">Loading...</li>
            </ul>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const summaryEl = bodyEl.querySelector('[data-bind="summary"]');
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const pruneBtn = bodyEl.querySelector('[data-action="prune"]');
        const tabs = bodyEl.querySelectorAll('.ei-tab');

        let activeTab = 'nodes';
        let metricsData = null;
        let pollTimer = null;

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                activeTab = tab.dataset.tab;
                tabs.forEach(t => t.classList.toggle('panel-action-btn-primary', t.dataset.tab === activeTab));
                renderTab();
            });
        });

        function renderTab() {
            if (activeTab === 'nodes') renderNodes();
            else if (activeTab === 'pipeline') renderPipeline();
            else if (activeTab === 'feedback') renderFeedback();
        }

        function renderNodes() {
            if (!listEl || !metricsData) return;
            const nodes = metricsData.nodes || {};
            const nodeIds = Object.keys(nodes);

            if (nodeIds.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No edge nodes reporting features</li>';
                return;
            }

            listEl.innerHTML = nodeIds.map(nodeId => {
                const n = nodes[nodeId];
                const devCount = n.total_devices_seen || 0;
                const classified = n.devices_classified || 0;
                const vectors = n.feature_vectors || 0;
                const rate = devCount > 0 ? ((classified / devCount) * 100).toFixed(0) : '0';
                const barWidth = Math.min(100, parseInt(rate));
                const barColor = barWidth > 70 ? '#05ffa1' : barWidth > 30 ? '#fcee0a' : '#ff2a6d';

                return `<li class="panel-list-item" style="padding:4px;border-bottom:1px solid #1a1a2e">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:#00f0ff;font-size:0.5rem;font-family:monospace">${_esc(nodeId)}</span>
                        <span style="color:#05ffa1;font-size:0.45rem">${devCount} devs</span>
                    </div>
                    <div style="margin-top:2px;display:flex;gap:8px;font-size:0.42rem;color:#888">
                        <span>Vectors: ${vectors}</span>
                        <span>Classified: ${classified}</span>
                        <span>Rate: ${rate}%</span>
                    </div>
                    <div style="margin-top:2px;height:3px;background:#0e0e14;border-radius:1px">
                        <div style="height:100%;width:${barWidth}%;background:${barColor};border-radius:1px;transition:width 0.3s"></div>
                    </div>
                </li>`;
            }).join('');
        }

        function renderPipeline() {
            if (!listEl || !metricsData) return;
            const agg = metricsData.aggregator_stats || {};
            const fb = metricsData.feedback_stats || {};

            const items = [
                { label: 'Tracked Devices', value: agg.device_count || 0, color: '#00f0ff' },
                { label: 'Total Feature Vectors', value: agg.total_vectors || 0, color: '#05ffa1' },
                { label: 'Unique Edge Nodes', value: agg.unique_nodes || 0, color: '#fcee0a' },
                { label: 'Avg Vectors/Device', value: (agg.avg_vectors_per_device || 0).toFixed(1), color: '#ff2a6d' },
                { label: 'Feedback Sent', value: agg.feedback_sent || 0, color: '#05ffa1' },
                { label: 'MQTT Connected', value: fb.mqtt_connected ? 'YES' : 'NO',
                  color: fb.mqtt_connected ? '#05ffa1' : '#ff2a6d' },
            ];

            listEl.innerHTML = items.map(item => `
                <li class="panel-list-item" style="padding:3px 4px;display:flex;justify-content:space-between;border-bottom:1px solid #1a1a2e">
                    <span style="font-size:0.45rem;color:#888">${_esc(item.label)}</span>
                    <span style="font-size:0.48rem;color:${item.color};font-family:monospace">${item.value}</span>
                </li>
            `).join('');
        }

        function renderFeedback() {
            if (!listEl || !metricsData) return;
            const fb = metricsData.feedback_stats || {};

            const items = [
                { label: 'Devices Classified', value: fb.devices_classified || 0, color: '#00f0ff' },
                { label: 'Devices Consistent', value: fb.devices_consistent || 0, color: '#05ffa1' },
                { label: 'Consistency Rate', value: ((fb.consistency_rate || 0) * 100).toFixed(1) + '%',
                  color: (fb.consistency_rate || 0) > 0.8 ? '#05ffa1' : '#fcee0a' },
                { label: 'Total Feedback Sent', value: fb.total_feedback_sent || 0, color: '#05ffa1' },
                { label: 'Inconsistencies', value: fb.total_inconsistencies || 0,
                  color: (fb.total_inconsistencies || 0) > 0 ? '#ff2a6d' : '#05ffa1' },
            ];

            listEl.innerHTML = items.map(item => `
                <li class="panel-list-item" style="padding:3px 4px;display:flex;justify-content:space-between;border-bottom:1px solid #1a1a2e">
                    <span style="font-size:0.45rem;color:#888">${_esc(item.label)}</span>
                    <span style="font-size:0.48rem;color:${item.color};font-family:monospace">${item.value}</span>
                </li>
            `).join('');
        }

        async function fetchMetrics() {
            try {
                const res = await fetch('/api/intelligence/edge-metrics');
                if (!res.ok) return;
                metricsData = await res.json();

                // Update summary
                if (summaryEl && metricsData) {
                    const agg = metricsData.aggregator_stats || {};
                    const fb = metricsData.feedback_stats || {};
                    const nodeCount = Object.keys(metricsData.nodes || {}).length;
                    summaryEl.textContent =
                        `${nodeCount} nodes | ${agg.device_count || 0} devices | ` +
                        `${agg.total_vectors || 0} vectors | ` +
                        `${((fb.consistency_rate || 0) * 100).toFixed(0)}% consistent`;
                }

                renderTab();
            } catch (e) {
                if (listEl) listEl.innerHTML = '<li class="panel-empty">Failed to load metrics</li>';
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchMetrics);
        if (pruneBtn) pruneBtn.addEventListener('click', async () => {
            try {
                // Prune is done server-side automatically, but we can trigger a refresh
                await fetchMetrics();
            } catch (e) { /* ignore */ }
        });

        // Initial load + polling
        fetchMetrics();
        pollTimer = setInterval(fetchMetrics, 10000);

        // Return cleanup
        return () => {
            if (pollTimer) clearInterval(pollTimer);
        };
    },

    unmount(bodyEl) {
        // Cleanup handled by mount return
    },
};
