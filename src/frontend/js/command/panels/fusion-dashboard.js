// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Fusion Dashboard — cross-sensor correlation pipeline health.
// Shows BLE+camera fusions/hour, strategy performance, operator accuracy,
// active correlations, and strategy weight visualization.

export function createFusionDashboard() {
    const panel = document.createElement('div');
    panel.className = 'panel fusion-dashboard';
    panel.innerHTML = `
        <div class="panel-header">
            <h3>Fusion Pipeline Health</h3>
            <div class="panel-controls">
                <button class="btn-refresh" title="Refresh metrics">REFRESH</button>
            </div>
        </div>
        <div class="fusion-content">
            <div class="fusion-overview">
                <div class="stat-card">
                    <span class="stat-label">Fusions/Hour</span>
                    <span class="stat-value fusion-hourly-rate">--</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Active Correlations</span>
                    <span class="stat-value fusion-active">--</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Total Fusions</span>
                    <span class="stat-value fusion-total">--</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Confirmation Rate</span>
                    <span class="stat-value fusion-confirm-rate">--</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Pending Feedback</span>
                    <span class="stat-value fusion-pending">--</span>
                </div>
                <div class="stat-card">
                    <span class="stat-label">Window Fusions</span>
                    <span class="stat-value fusion-window">--</span>
                </div>
            </div>

            <div class="fusion-section">
                <h4>Source Pair Fusions</h4>
                <div class="source-pairs-chart"></div>
            </div>

            <div class="fusion-section">
                <h4>Strategy Performance</h4>
                <div class="strategy-table-wrap">
                    <table class="strategy-table">
                        <thead>
                            <tr>
                                <th>Strategy</th>
                                <th>Evaluations</th>
                                <th>Contributed</th>
                                <th>Accuracy</th>
                                <th>Avg Score</th>
                                <th>Weight</th>
                            </tr>
                        </thead>
                        <tbody class="strategy-tbody"></tbody>
                    </table>
                </div>
            </div>

            <div class="fusion-section">
                <h4>Weight Recommendations</h4>
                <div class="weight-bars"></div>
            </div>
        </div>
    `;

    let refreshTimer = null;

    async function refresh() {
        try {
            const [statusRes, weightsRes] = await Promise.all([
                fetch('/api/fusion/status'),
                fetch('/api/fusion/weights'),
            ]);
            const status = await statusRes.json();
            const weights = await weightsRes.json();

            // Overview stats
            _setText(panel, '.fusion-hourly-rate', _fmt(status.hourly_rate, 1));
            _setText(panel, '.fusion-active', status.active_correlations ?? '--');
            _setText(panel, '.fusion-total', status.total_fusions ?? 0);
            _setText(panel, '.fusion-confirm-rate',
                status.confirmation_rate != null
                    ? (status.confirmation_rate * 100).toFixed(1) + '%' : '--');
            _setText(panel, '.fusion-pending', status.total_pending_feedback ?? 0);
            _setText(panel, '.fusion-window', status.window_fusions ?? 0);

            // Source pairs chart
            const pairsEl = panel.querySelector('.source-pairs-chart');
            if (pairsEl && status.source_pairs) {
                _renderPairs(pairsEl, status.source_pairs);
            }

            // Strategy table
            const tbody = panel.querySelector('.strategy-tbody');
            if (tbody && status.strategies) {
                _renderStrategies(tbody, status.strategies,
                    weights.current_weights || {});
            }

            // Weight recommendations
            const weightBars = panel.querySelector('.weight-bars');
            if (weightBars && weights.recommendations) {
                _renderWeights(weightBars, weights.recommendations,
                    weights.current_weights || {});
            }
        } catch (err) {
            console.warn('Fusion dashboard refresh error:', err);
        }
    }

    function _setText(root, sel, val) {
        const el = root.querySelector(sel);
        if (el) el.textContent = val;
    }

    function _fmt(n, dec) {
        if (n == null) return '--';
        return Number(n).toFixed(dec);
    }

    function _renderPairs(container, pairs) {
        const entries = Object.entries(pairs);
        if (!entries.length) {
            container.innerHTML = '<div class="empty-state">No fusions recorded</div>';
            return;
        }
        const maxCount = Math.max(...entries.map(e => e[1]));
        container.innerHTML = entries.map(([pair, count]) => {
            const pct = maxCount > 0 ? (count / maxCount * 100) : 0;
            return `
                <div class="pair-bar">
                    <span class="pair-label">${pair}</span>
                    <div class="bar-track">
                        <div class="bar-fill" style="width:${pct}%"></div>
                    </div>
                    <span class="pair-count">${count}</span>
                </div>`;
        }).join('');
    }

    function _renderStrategies(tbody, strategies, currentWeights) {
        if (!strategies.length) {
            tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No strategy data</td></tr>';
            return;
        }
        tbody.innerHTML = strategies.map(s => {
            const accClass = s.accuracy >= 0.8 ? 'good' :
                s.accuracy >= 0.5 ? 'warn' : 'bad';
            const weight = currentWeights[s.name];
            return `
                <tr>
                    <td class="strategy-name">${s.name}</td>
                    <td>${s.evaluations}</td>
                    <td>${s.contributed}</td>
                    <td class="accuracy ${accClass}">${(s.accuracy * 100).toFixed(1)}%</td>
                    <td>${s.avg_score.toFixed(3)}</td>
                    <td>${weight != null ? weight.toFixed(2) : '--'}</td>
                </tr>`;
        }).join('');
    }

    function _renderWeights(container, recommendations, current) {
        const entries = Object.entries(recommendations);
        if (!entries.length) {
            container.innerHTML = '<div class="empty-state">Need more feedback for recommendations</div>';
            return;
        }
        container.innerHTML = entries.map(([name, weight]) => {
            const curW = current[name];
            const delta = curW != null ? weight - curW : 0;
            const deltaClass = delta > 0.02 ? 'increase' : delta < -0.02 ? 'decrease' : '';
            const deltaStr = delta !== 0 ? (delta > 0 ? '+' : '') + delta.toFixed(3) : '';
            return `
                <div class="weight-row">
                    <span class="weight-name">${name}</span>
                    <div class="bar-track">
                        <div class="bar-fill recommended" style="width:${weight * 100}%"></div>
                        ${curW != null ? `<div class="bar-marker" style="left:${curW * 100}%" title="current: ${curW.toFixed(2)}"></div>` : ''}
                    </div>
                    <span class="weight-value">${(weight * 100).toFixed(1)}%</span>
                    <span class="weight-delta ${deltaClass}">${deltaStr}</span>
                </div>`;
        }).join('');
    }

    // Setup
    const refreshBtn = panel.querySelector('.btn-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refresh);
    }

    // Auto-refresh every 10s
    refresh();
    refreshTimer = setInterval(refresh, 10000);

    // Cleanup on remove
    const observer = new MutationObserver(() => {
        if (!panel.isConnected) {
            clearInterval(refreshTimer);
            observer.disconnect();
        }
    });
    observer.observe(document.body, { childList: true, subtree: true });

    return panel;
}
