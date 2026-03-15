// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Fusion Dashboard — cross-sensor correlation pipeline health.
// Shows BLE+camera fusions/hour, strategy performance, operator accuracy,
// active correlations, and strategy weight visualization.

export const FusionDashboardPanelDef = {
    id: 'fusion-dashboard',
    title: 'FUSION PIPELINE',
    defaultPosition: { x: 240, y: 60 },
    defaultSize: { w: 460, h: 520 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'fusion-dashboard';
        el.innerHTML = `
            <div style="padding:8px;">
                <div style="display:flex;gap:4px;margin-bottom:8px;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                </div>
                <div class="fusion-overview" style="display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px;">
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Fusions/Hour</div>
                        <div data-bind="hourly-rate" style="font-size:16px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Active</div>
                        <div data-bind="active" style="font-size:16px;color:#00f0ff;margin-top:2px;">--</div>
                    </div>
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Total</div>
                        <div data-bind="total" style="font-size:16px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Confirm Rate</div>
                        <div data-bind="confirm-rate" style="font-size:16px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Pending</div>
                        <div data-bind="pending" style="font-size:16px;color:#fcee0a;margin-top:2px;">--</div>
                    </div>
                    <div class="stat-card" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;text-align:center;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Window</div>
                        <div data-bind="window" style="font-size:16px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                </div>
                <div style="margin-bottom:8px;">
                    <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;">Source Pair Fusions</div>
                    <div data-bind="pairs" style="font-size:11px;"></div>
                </div>
                <div style="margin-bottom:8px;">
                    <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;">Strategy Performance</div>
                    <div data-bind="strategies" style="font-size:11px;overflow-x:auto;"></div>
                </div>
                <div>
                    <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;">Weight Recommendations</div>
                    <div data-bind="weights" style="font-size:11px;"></div>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        async function refresh() {
            try {
                const [statusRes, weightsRes] = await Promise.all([
                    fetch('/api/fusion/status'),
                    fetch('/api/fusion/weights'),
                ]);
                const status = await statusRes.json();
                const weights = await weightsRes.json();

                _set(bodyEl, 'hourly-rate', _fmt(status.hourly_rate, 1));
                _set(bodyEl, 'active', status.active_correlations ?? '--');
                _set(bodyEl, 'total', status.total_fusions ?? 0);
                _set(bodyEl, 'confirm-rate',
                    status.confirmation_rate != null
                        ? (status.confirmation_rate * 100).toFixed(1) + '%' : '--');
                _set(bodyEl, 'pending', status.total_pending_feedback ?? 0);
                _set(bodyEl, 'window', status.window_fusions ?? 0);

                const pairsEl = bodyEl.querySelector('[data-bind="pairs"]');
                if (pairsEl && status.source_pairs) _renderPairs(pairsEl, status.source_pairs);

                const stratEl = bodyEl.querySelector('[data-bind="strategies"]');
                if (stratEl && status.strategies) _renderStrategies(stratEl, status.strategies, weights.current_weights || {});

                const weightEl = bodyEl.querySelector('[data-bind="weights"]');
                if (weightEl && weights.recommendations) _renderWeights(weightEl, weights.recommendations, weights.current_weights || {});
            } catch (err) {
                console.warn('Fusion dashboard refresh error:', err);
            }
        }

        bodyEl.addEventListener('click', (e) => {
            if (e.target.dataset?.action === 'refresh') refresh();
        });

        refresh();
        panel._fusionTimer = setInterval(refresh, 10000);
    },

    unmount(bodyEl, panel) {
        if (panel._fusionTimer) {
            clearInterval(panel._fusionTimer);
            panel._fusionTimer = null;
        }
    },
};

function _set(root, bind, val) {
    const el = root.querySelector(`[data-bind="${bind}"]`);
    if (el) el.textContent = String(val);
}

function _fmt(n, dec) {
    if (n == null) return '--';
    return Number(n).toFixed(dec);
}

function _renderPairs(container, pairs) {
    const entries = Object.entries(pairs);
    if (!entries.length) { container.innerHTML = '<div style="color:#555">No fusions recorded</div>'; return; }
    const maxCount = Math.max(...entries.map(e => e[1]));
    container.innerHTML = entries.map(([pair, count]) => {
        const pct = maxCount > 0 ? (count / maxCount * 100) : 0;
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:100px;font-size:11px;">${pair}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;">
                <div style="width:${pct}%;height:100%;background:#00f0ff;border-radius:2px;"></div>
            </div>
            <span style="color:#aaa;font-size:11px;min-width:30px;text-align:right;">${count}</span>
        </div>`;
    }).join('');
}

function _renderStrategies(container, strategies, currentWeights) {
    if (!strategies.length) { container.innerHTML = '<div style="color:#555">No strategy data</div>'; return; }
    let html = '<table style="width:100%;border-collapse:collapse;font-size:11px;"><thead><tr>';
    html += '<th style="text-align:left;color:#888;padding:2px 4px;">Strategy</th>';
    html += '<th style="text-align:right;color:#888;padding:2px 4px;">Evals</th>';
    html += '<th style="text-align:right;color:#888;padding:2px 4px;">Accuracy</th>';
    html += '<th style="text-align:right;color:#888;padding:2px 4px;">Weight</th>';
    html += '</tr></thead><tbody>';
    strategies.forEach(s => {
        const accColor = s.accuracy >= 0.8 ? '#05ffa1' : s.accuracy >= 0.5 ? '#fcee0a' : '#ff2a6d';
        const weight = currentWeights[s.name];
        html += `<tr><td style="color:#ccc;padding:2px 4px;">${s.name}</td>
            <td style="text-align:right;color:#aaa;padding:2px 4px;">${s.evaluations}</td>
            <td style="text-align:right;color:${accColor};padding:2px 4px;">${(s.accuracy * 100).toFixed(1)}%</td>
            <td style="text-align:right;color:#aaa;padding:2px 4px;">${weight != null ? weight.toFixed(2) : '--'}</td></tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function _renderWeights(container, recommendations, current) {
    const entries = Object.entries(recommendations);
    if (!entries.length) { container.innerHTML = '<div style="color:#555">Need more feedback</div>'; return; }
    container.innerHTML = entries.map(([name, weight]) => {
        const curW = current[name];
        const delta = curW != null ? weight - curW : 0;
        const deltaStr = delta !== 0 ? (delta > 0 ? '+' : '') + delta.toFixed(3) : '';
        const deltaColor = delta > 0.02 ? '#05ffa1' : delta < -0.02 ? '#ff2a6d' : '#888';
        return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;">
            <span style="color:#888;min-width:100px;font-size:11px;">${name}</span>
            <div style="flex:1;height:8px;background:#12121a;border-radius:2px;overflow:hidden;position:relative;">
                <div style="width:${weight * 100}%;height:100%;background:#05ffa1;border-radius:2px;"></div>
                ${curW != null ? `<div style="position:absolute;top:0;left:${curW * 100}%;width:2px;height:100%;background:#fff;"></div>` : ''}
            </div>
            <span style="color:#aaa;font-size:11px;min-width:40px;text-align:right;">${(weight * 100).toFixed(1)}%</span>
            <span style="color:${deltaColor};font-size:10px;min-width:40px;">${deltaStr}</span>
        </div>`;
    }).join('');
}
