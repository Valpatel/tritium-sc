// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// Training Data Dashboard — shows model status, training stats,
// accuracy over time, recent feedback entries, and retrain button.

export const TrainingDashboardPanelDef = {
    id: 'training-dashboard',
    title: 'ML TRAINING',
    defaultPosition: { x: 260, y: 70 },
    defaultSize: { w: 440, h: 500 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="padding:8px;font-size:12px;color:#c0c0c0;">
                <div style="display:flex;gap:4px;margin-bottom:8px;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="retrain" style="font-size:0.42rem">RETRAIN</button>
                    <button class="panel-action-btn" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                </div>

                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Model Status</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;margin-bottom:10px;">
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Status</div>
                        <div data-bind="model-trained" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Accuracy</div>
                        <div data-bind="model-accuracy" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Training Examples</div>
                        <div data-bind="model-count" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Last Trained</div>
                        <div data-bind="model-last-trained" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">sklearn</div>
                        <div data-bind="sklearn-status" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                </div>

                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Training Data</div>
                <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:6px;margin-bottom:10px;">
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Correlation Decisions</div>
                        <div data-bind="corr-total" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Confirmed</div>
                        <div data-bind="corr-confirmed" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Classifications</div>
                        <div data-bind="class-total" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Feedback</div>
                        <div data-bind="feedback-total" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                    <div style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;">
                        <div style="font-size:10px;color:#666;text-transform:uppercase;">Feedback Accuracy</div>
                        <div data-bind="feedback-accuracy" style="font-size:14px;color:#05ffa1;margin-top:2px;">--</div>
                    </div>
                </div>

                <div style="color:#ff2a6d;font-size:11px;text-transform:uppercase;margin-bottom:4px;letter-spacing:1px;">Retrain Log</div>
                <div data-bind="retrain-log" style="background:#0e0e14;border:1px solid #1a1a2e;padding:6px;max-height:160px;overflow-y:auto;font-size:11px;font-family:monospace;"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const logEl = bodyEl.querySelector('[data-bind="retrain-log"]');

        function addLogEntry(message, type) {
            const entry = document.createElement('div');
            entry.style.cssText = `padding:2px 0;border-bottom:1px solid #12121a;color:${type === 'success' ? '#05ffa1' : type === 'error' ? '#ff2a6d' : '#00f0ff'};`;
            const ts = new Date().toLocaleTimeString();
            entry.textContent = `[${ts}] ${message}`;
            logEl.prepend(entry);
            while (logEl.children.length > 50) logEl.removeChild(logEl.lastChild);
        }

        async function refreshStatus() {
            try {
                const resp = await fetch('/api/intelligence/model/status');
                const data = await resp.json();

                const trainedEl = bodyEl.querySelector('[data-bind="model-trained"]');
                trainedEl.textContent = data.trained ? 'TRAINED' : 'NOT TRAINED';
                trainedEl.style.color = data.trained ? '#05ffa1' : '#ff2a6d';

                _set(bodyEl, 'model-accuracy', data.accuracy > 0 ? (data.accuracy * 100).toFixed(1) + '%' : '--');
                _set(bodyEl, 'model-count', data.training_count > 0 ? data.training_count.toString() : '0');
                _set(bodyEl, 'model-last-trained', data.last_trained_iso || 'never');

                const sklearnEl = bodyEl.querySelector('[data-bind="sklearn-status"]');
                sklearnEl.textContent = data.sklearn_available ? 'YES' : 'NO';
                sklearnEl.style.color = data.sklearn_available ? '#05ffa1' : '#fcee0a';

                const stats = data.training_data_stats || {};
                const corr = stats.correlation || {};
                const cls = stats.classification || {};
                const fb = stats.feedback || {};
                _set(bodyEl, 'corr-total', (corr.total || 0).toString());
                _set(bodyEl, 'corr-confirmed', (corr.confirmed || 0).toString());
                _set(bodyEl, 'class-total', (cls.total || 0).toString());
                _set(bodyEl, 'feedback-total', (fb.total || 0).toString());
                _set(bodyEl, 'feedback-accuracy', fb.accuracy > 0 ? (fb.accuracy * 100).toFixed(1) + '%' : '--');
            } catch (err) {
                console.warn('Failed to fetch training status:', err);
            }
        }

        bodyEl.addEventListener('click', async (e) => {
            const action = e.target.dataset?.action;
            if (action === 'refresh') {
                refreshStatus();
            } else if (action === 'retrain') {
                addLogEntry('Triggering model retrain...', 'info');
                e.target.disabled = true;
                e.target.textContent = 'TRAINING...';
                try {
                    const resp = await fetch('/api/intelligence/retrain', { method: 'POST' });
                    const data = await resp.json();
                    if (data.success) {
                        addLogEntry(`Retrain complete: accuracy=${(data.accuracy * 100).toFixed(1)}% n=${data.training_count}`, 'success');
                    } else {
                        addLogEntry(`Retrain failed: ${data.error || 'unknown error'}`, 'error');
                    }
                } catch (err) {
                    addLogEntry(`Retrain error: ${err.message}`, 'error');
                }
                e.target.disabled = false;
                e.target.textContent = 'RETRAIN';
                refreshStatus();
            }
        });

        refreshStatus();
    },
};

function _set(root, bind, val) {
    const el = root.querySelector(`[data-bind="${bind}"]`);
    if (el) el.textContent = String(val);
}
