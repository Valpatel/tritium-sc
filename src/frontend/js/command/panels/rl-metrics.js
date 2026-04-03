// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// RL Metrics Panel — shows RL model accuracy trends, feature importance,
// prediction distribution, and training data growth. Fetches from
// /api/intelligence/rl-metrics endpoint.

export const RlMetricsPanelDef = {
    id: 'rl-metrics',
    title: 'RL METRICS',
    defaultPosition: { x: 300, y: 80 },
    defaultSize: { w: 520, h: 580 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;font-size:12px;color:#c0c0c0;">
                <div style="display:flex;gap:4px;margin-bottom:8px;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                    <button class="panel-action-btn" data-action="retrain" style="font-size:0.42rem">RETRAIN MODEL</button>
                    <span data-bind="status-badge" style="margin-left:auto;padding:2px 8px;border-radius:2px;font-size:10px;text-transform:uppercase;letter-spacing:1px;background:#1a1a2e;color:#666;">--</span>
                </div>

                <!-- Overview Stats -->
                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Overview</div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px;">
                    <div class="rl-stat-box">
                        <div class="rl-stat-label">Accuracy</div>
                        <div data-bind="overall-accuracy" class="rl-stat-value">--</div>
                    </div>
                    <div class="rl-stat-box">
                        <div class="rl-stat-label">Trainings</div>
                        <div data-bind="total-trainings" class="rl-stat-value">0</div>
                    </div>
                    <div class="rl-stat-box">
                        <div class="rl-stat-label">Predictions</div>
                        <div data-bind="total-predictions" class="rl-stat-value">0</div>
                    </div>
                    <div class="rl-stat-box">
                        <div class="rl-stat-label">Correct Rate</div>
                        <div data-bind="correct-rate" class="rl-stat-value">--</div>
                    </div>
                </div>

                <!-- Accuracy Trend Chart (Canvas) -->
                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Accuracy Trend</div>
                <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;margin-bottom:10px;">
                    <canvas data-bind="accuracy-chart" width="480" height="100" style="width:100%;height:100px;display:block;"></canvas>
                </div>

                <!-- Feature Importance -->
                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Feature Importance</div>
                <div data-bind="feature-bars" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;margin-bottom:10px;max-height:140px;overflow-y:auto;"></div>

                <!-- Prediction Distribution -->
                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Prediction Distribution</div>
                <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:4px;margin-bottom:10px;">
                    <canvas data-bind="pred-chart" width="480" height="80" style="width:100%;height:80px;display:block;"></canvas>
                </div>

                <!-- Model Details -->
                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Model Details</div>
                <div data-bind="model-details" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;font-size:11px;font-family:monospace;max-height:100px;overflow-y:auto;color:#888;"></div>
            </div>

            <style>
                .rl-stat-box {
                    background: #0e0e14;
                    border: 1px solid #1a1a2e;
                    padding: 6px;
                    text-align: center;
                }
                .rl-stat-label {
                    font-size: 10px;
                    color: #666;
                    text-transform: uppercase;
                    letter-spacing: 0.5px;
                }
                .rl-stat-value {
                    font-size: 16px;
                    color: #05ffa1;
                    margin-top: 2px;
                    font-family: monospace;
                }
                .rl-feat-bar {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 2px 0;
                }
                .rl-feat-name {
                    width: 140px;
                    font-size: 10px;
                    color: #aaa;
                    text-align: right;
                    flex-shrink: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .rl-feat-fill {
                    height: 10px;
                    background: #00f0ff;
                    border-radius: 1px;
                    transition: width 0.3s;
                }
                .rl-feat-val {
                    font-size: 10px;
                    color: #666;
                    width: 40px;
                    flex-shrink: 0;
                }
            </style>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        let refreshTimer = null;

        function _set(bind, val) {
            const el = bodyEl.querySelector(`[data-bind="${bind}"]`);
            if (el) el.textContent = String(val);
        }

        function drawAccuracyChart(canvas, trendData) {
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            if (!trendData || trendData.length === 0) {
                ctx.fillStyle = '#333';
                ctx.font = '11px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('No training data yet', w / 2, h / 2);
                return;
            }

            // Grid lines
            ctx.strokeStyle = '#1a1a2e';
            ctx.lineWidth = 1;
            for (let i = 0; i <= 4; i++) {
                const y = Math.round(h * i / 4) + 0.5;
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(w, y);
                ctx.stroke();
            }

            // Y-axis labels
            ctx.fillStyle = '#555';
            ctx.font = '9px monospace';
            ctx.textAlign = 'left';
            ctx.fillText('100%', 2, 10);
            ctx.fillText('50%', 2, h / 2 + 4);
            ctx.fillText('0%', 2, h - 2);

            // Plot accuracy trend
            const points = trendData;
            const xStep = (w - 40) / Math.max(1, points.length - 1);

            // Line
            ctx.strokeStyle = '#00f0ff';
            ctx.lineWidth = 2;
            ctx.beginPath();
            for (let i = 0; i < points.length; i++) {
                const x = 40 + i * xStep;
                const y = h - (points[i].accuracy * h);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();

            // Points
            ctx.fillStyle = '#00f0ff';
            for (let i = 0; i < points.length; i++) {
                const x = 40 + i * xStep;
                const y = h - (points[i].accuracy * h);
                ctx.beginPath();
                ctx.arc(x, y, 3, 0, Math.PI * 2);
                ctx.fill();
            }

            // Latest accuracy label
            if (points.length > 0) {
                const last = points[points.length - 1];
                const lx = 40 + (points.length - 1) * xStep;
                const ly = h - (last.accuracy * h);
                ctx.fillStyle = '#05ffa1';
                ctx.font = '10px monospace';
                ctx.textAlign = 'right';
                ctx.fillText((last.accuracy * 100).toFixed(1) + '%', lx - 4, ly - 6);
            }
        }

        function drawPredDistChart(canvas, distData) {
            const ctx = canvas.getContext('2d');
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);

            if (!distData || distData.total === 0) {
                ctx.fillStyle = '#333';
                ctx.font = '11px monospace';
                ctx.textAlign = 'center';
                ctx.fillText('No predictions yet', w / 2, h / 2);
                return;
            }

            const histogram = distData.probability_histogram || [];
            if (histogram.length === 0) return;

            const maxVal = Math.max(...histogram, 1);
            const barW = (w - 20) / histogram.length;

            // Bars
            for (let i = 0; i < histogram.length; i++) {
                const barH = (histogram[i] / maxVal) * (h - 20);
                const x = 10 + i * barW;
                const y = h - 10 - barH;

                // Color gradient from magenta (low prob) to cyan (high prob)
                const t = i / (histogram.length - 1);
                const r = Math.round(255 * (1 - t));
                const g = Math.round(42 + 198 * t);
                const b = Math.round(109 + 146 * t);
                ctx.fillStyle = `rgb(${r},${g},${b})`;
                ctx.fillRect(x + 1, y, barW - 2, barH);
            }

            // X-axis labels
            ctx.fillStyle = '#555';
            ctx.font = '8px monospace';
            ctx.textAlign = 'center';
            for (let i = 0; i < histogram.length; i += 2) {
                const x = 10 + (i + 0.5) * barW;
                ctx.fillText((i / 10).toFixed(1), x, h - 1);
            }

            // Class balance label
            const cc = distData.class_counts || {};
            ctx.fillStyle = '#888';
            ctx.font = '9px monospace';
            ctx.textAlign = 'right';
            ctx.fillText(`class0=${cc[0] || 0} class1=${cc[1] || 0} mean=${(distData.mean_probability || 0).toFixed(3)}`, w - 4, 10);
        }

        function renderFeatureBars(container, featureImportance) {
            if (!featureImportance || Object.keys(featureImportance).length === 0) {
                container.innerHTML = '<div style="color:#555;font-size:11px;text-align:center;padding:8px;">No feature importance data</div>';
                return;
            }

            const entries = Object.entries(featureImportance);
            const maxVal = Math.max(...entries.map(([, v]) => Math.abs(v)), 0.01);

            container.innerHTML = entries.map(([name, val]) => {
                const pct = Math.round((Math.abs(val) / maxVal) * 100);
                const color = val >= 0 ? '#00f0ff' : '#ff2a6d';
                return `<div class="rl-feat-bar">
                    <div class="rl-feat-name" title="${name}">${name}</div>
                    <div style="flex:1;background:#12121a;height:10px;border-radius:1px;">
                        <div class="rl-feat-fill" style="width:${pct}%;background:${color};"></div>
                    </div>
                    <div class="rl-feat-val">${val.toFixed(4)}</div>
                </div>`;
            }).join('');
        }

        async function refresh() {
            try {
                const resp = await fetch('/api/intelligence/rl-metrics?model=correlation&max_points=50');
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();

                // Status badge
                const badge = bodyEl.querySelector('[data-bind="status-badge"]');
                if (badge) {
                    badge.textContent = data.status || 'unknown';
                    badge.style.color = data.available ? '#05ffa1' : '#ff2a6d';
                    badge.style.borderColor = data.available ? '#05ffa133' : '#ff2a6d33';
                }

                // Overview stats
                const acc = data.overall_accuracy || 0;
                _set('overall-accuracy', acc > 0 ? (acc * 100).toFixed(1) + '%' : '--');
                _set('total-trainings', data.total_trainings || 0);
                _set('total-predictions', data.total_predictions || 0);

                const dist = data.prediction_distribution || {};
                const cr = dist.correct_rate || 0;
                _set('correct-rate', cr > 0 ? (cr * 100).toFixed(1) + '%' : '--');

                // Accuracy trend chart
                const accCanvas = bodyEl.querySelector('[data-bind="accuracy-chart"]');
                if (accCanvas) {
                    const trend = data.accuracy_trend || [];
                    // If no model-specific trend, pull from models_detail
                    let trendData = trend;
                    if (trendData.length === 0 && data.models_detail) {
                        const corrDetail = data.models_detail.correlation;
                        if (corrDetail && corrDetail.accuracy_trend) {
                            trendData = corrDetail.accuracy_trend;
                        }
                    }
                    drawAccuracyChart(accCanvas, trendData);
                }

                // Feature importance bars
                const featBars = bodyEl.querySelector('[data-bind="feature-bars"]');
                if (featBars) {
                    let fi = data.feature_importance || {};
                    if (Object.keys(fi).length === 0 && data.models_detail) {
                        const corrDetail = data.models_detail.correlation;
                        if (corrDetail && corrDetail.feature_importance) {
                            fi = corrDetail.feature_importance;
                        }
                    }
                    renderFeatureBars(featBars, fi);
                }

                // Prediction distribution chart
                const predCanvas = bodyEl.querySelector('[data-bind="pred-chart"]');
                if (predCanvas) {
                    drawPredDistChart(predCanvas, dist);
                }

                // Model details
                const details = bodyEl.querySelector('[data-bind="model-details"]');
                if (details && data.learner) {
                    const lr = data.learner;
                    const lines = [
                        `trained: ${lr.trained}`,
                        `accuracy: ${lr.accuracy > 0 ? (lr.accuracy * 100).toFixed(1) + '%' : 'n/a'}`,
                        `training_count: ${lr.training_count}`,
                        `sklearn: ${lr.sklearn_available}`,
                        `features: ${(lr.feature_names || []).length}`,
                    ];
                    if (lr.best_params && Object.keys(lr.best_params).length > 0) {
                        lines.push(`params: ${JSON.stringify(lr.best_params)}`);
                    }
                    // Models from RL metrics
                    if (data.models) {
                        for (const [name, model] of Object.entries(data.models)) {
                            lines.push(`--- ${name} ---`);
                            lines.push(`  last_accuracy: ${(model.last_accuracy * 100).toFixed(1)}%`);
                            lines.push(`  trainings: ${model.total_trainings}`);
                            lines.push(`  predictions: ${model.total_predictions}`);
                            lines.push(`  pred_accuracy: ${(model.prediction_accuracy * 100).toFixed(1)}%`);
                        }
                    }
                    details.textContent = lines.join('\n');
                } else if (details) {
                    details.textContent = data.available ? 'Learner data unavailable' : 'RL system not active';
                }
            } catch (err) {
                console.warn('RL metrics fetch failed:', err);
                _set('overall-accuracy', 'ERR');
            }
        }

        bodyEl.addEventListener('click', async (e) => {
            const action = e.target.dataset?.action;
            if (action === 'refresh') {
                refresh();
            } else if (action === 'retrain') {
                e.target.disabled = true;
                e.target.textContent = 'TRAINING...';
                try {
                    const resp = await fetch('/api/intelligence/retrain', { method: 'POST' });
                    const data = await resp.json();
                    if (data.success) {
                        e.target.textContent = 'DONE';
                        setTimeout(() => { e.target.textContent = 'RETRAIN MODEL'; }, 2000);
                    } else {
                        e.target.textContent = 'FAILED';
                        setTimeout(() => { e.target.textContent = 'RETRAIN MODEL'; }, 2000);
                    }
                } catch (err) {
                    e.target.textContent = 'ERROR';
                    setTimeout(() => { e.target.textContent = 'RETRAIN MODEL'; }, 2000);
                }
                e.target.disabled = false;
                refresh();
            }
        });

        // Initial fetch + auto-refresh every 30s
        refresh();
        refreshTimer = setInterval(refresh, 30000);
    },

    destroy(bodyEl) {
        // cleanup handled by panel manager
    },
};
