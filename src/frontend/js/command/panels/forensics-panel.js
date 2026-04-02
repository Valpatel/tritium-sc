// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Forensics Panel — forensic reconstruction and incident report generation.
// Lists existing reconstructions, creates new ones with time range + bounds,
// shows reconstruction details (events, timeline, involved targets),
// and generates incident reports.
// Backend: POST /api/forensics/reconstruct, GET /api/forensics, GET /api/forensics/{id}, POST /api/forensics/report
// Auto-refreshes reconstruction list every 15 seconds.

import { _esc } from '/lib/utils.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const REFRESH_MS = 15000;

const CYAN = '#00f0ff';
const MAGENTA = '#ff2a6d';
const GREEN = '#05ffa1';
const YELLOW = '#fcee0a';
const DIM = '#666';
const SURFACE = '#0e0e14';
const BORDER = '#1a1a2e';

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------

async function _fetchReconstructions() {
    try {
        const resp = await fetch('/api/forensics');
        if (!resp.ok) return { reconstructions: [], count: 0 };
        return await resp.json();
    } catch {
        return { reconstructions: [], count: 0 };
    }
}

async function _fetchReconstruction(reconId) {
    try {
        const resp = await fetch(`/api/forensics/${encodeURIComponent(reconId)}`);
        if (!resp.ok) return null;
        return await resp.json();
    } catch {
        return null;
    }
}

async function _createReconstruction(start, end, bounds, maxEvents) {
    try {
        const body = { start, end, max_events: maxEvents || 10000 };
        if (bounds) body.bounds = bounds;
        const resp = await fetch('/api/forensics/reconstruct', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) return { error: `HTTP ${resp.status}` };
        return await resp.json();
    } catch (e) {
        return { error: e.message };
    }
}

async function _generateReport(reconstructionId, title, createdBy) {
    try {
        const resp = await fetch('/api/forensics/report', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                reconstruction_id: reconstructionId,
                title: title || '',
                created_by: createdBy || 'operator',
            }),
        });
        if (!resp.ok) return { error: `HTTP ${resp.status}` };
        return await resp.json();
    } catch (e) {
        return { error: e.message };
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function _formatTimestamp(ts) {
    if (!ts) return '--';
    try {
        const d = new Date(ts * 1000);
        return d.toLocaleString();
    } catch {
        return String(ts);
    }
}

function _formatDuration(seconds) {
    if (!seconds && seconds !== 0) return '--';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function _statCard(label, value, color) {
    return `<div style="background:${SURFACE};border:1px solid ${BORDER};padding:6px;text-align:center;">
        <div style="font-size:9px;color:${DIM};text-transform:uppercase;letter-spacing:0.5px;">${_esc(label)}</div>
        <div style="font-size:16px;color:${color};margin-top:2px;font-family:monospace;">${_esc(String(value))}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Reconstruction list render
// ---------------------------------------------------------------------------

function _reconstructionList(reconstructions) {
    if (!reconstructions || reconstructions.length === 0) {
        return `<div style="color:#555;padding:12px;text-align:center;font-size:10px;">No reconstructions. Use the form above to create one.</div>`;
    }

    return reconstructions.map(r => {
        const id = r.id || r.reconstruction_id || '--';
        const start = _formatTimestamp(r.start);
        const end = _formatTimestamp(r.end);
        const eventCount = r.event_count || r.total_events || 0;
        const targetCount = r.target_count || r.total_targets || 0;
        const status = (r.status || 'complete').toUpperCase();
        const statusColor = status === 'COMPLETE' ? GREEN : status === 'ERROR' ? MAGENTA : YELLOW;

        return `<div class="forensics-recon-item" data-recon-id="${_esc(id)}"
                     style="border:1px solid ${BORDER};padding:6px;margin-bottom:4px;cursor:pointer;border-left:3px solid ${statusColor};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span class="mono" style="color:${CYAN};font-size:11px;">${_esc(id.substring(0, 12))}</span>
                <span style="color:${statusColor};font-size:9px;border:1px solid ${statusColor};padding:1px 4px;border-radius:2px;">${status}</span>
            </div>
            <div style="display:flex;gap:12px;margin-top:3px;font-size:9px;color:#888;">
                <span>${_esc(start)} - ${_esc(end)}</span>
            </div>
            <div style="display:flex;gap:12px;margin-top:2px;font-size:9px;">
                <span style="color:${CYAN};">${eventCount} events</span>
                <span style="color:${GREEN};">${targetCount} targets</span>
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Reconstruction detail render
// ---------------------------------------------------------------------------

function _reconstructionDetail(recon) {
    if (!recon) return `<div style="color:#555;padding:12px;text-align:center;">Select a reconstruction to view details.</div>`;
    if (recon.error) return `<div style="color:${MAGENTA};padding:12px;text-align:center;">${_esc(recon.error)}</div>`;

    const id = recon.id || recon.reconstruction_id || '--';
    const events = recon.events || [];
    const targets = recon.targets || recon.involved_targets || [];
    const timeline = recon.timeline || [];
    const duration = recon.duration_s || 0;

    const statsRow = `<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;">
        ${_statCard('Events', events.length, CYAN)}
        ${_statCard('Targets', targets.length, GREEN)}
        ${_statCard('Duration', _formatDuration(duration), YELLOW)}
        ${_statCard('ID', id.substring(0, 8), DIM)}
    </div>`;

    // Timeline section
    let timelineHtml = '';
    if (timeline.length > 0) {
        const timelineItems = timeline.slice(0, 30).map(t => {
            const ts = _formatTimestamp(t.timestamp || t.time);
            const evtType = (t.event_type || t.type || 'event').toUpperCase();
            const desc = t.description || t.summary || '';
            const typeColor = evtType.includes('HOSTILE') ? MAGENTA : evtType.includes('ALERT') ? YELLOW : CYAN;
            return `<div style="display:flex;gap:6px;padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03);font-size:9px;">
                <span style="color:#555;min-width:80px;">${_esc(ts)}</span>
                <span style="color:${typeColor};min-width:70px;">${_esc(evtType)}</span>
                <span style="color:#999;flex:1;">${_esc(desc)}</span>
            </div>`;
        }).join('');
        timelineHtml = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;margin-top:6px;">
            <div style="font-size:10px;color:${CYAN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">TIMELINE (${timeline.length})</div>
            <div style="max-height:150px;overflow-y:auto;">${timelineItems}</div>
        </div>`;
    }

    // Targets section
    let targetsHtml = '';
    if (targets.length > 0) {
        const targetItems = targets.slice(0, 20).map(t => {
            const tid = typeof t === 'string' ? t : (t.target_id || t.id || '--');
            const name = typeof t === 'string' ? '' : (t.name || '');
            const alliance = typeof t === 'string' ? '' : (t.alliance || '');
            const allianceColor = alliance === 'hostile' ? MAGENTA : alliance === 'friendly' ? GREEN : DIM;
            return `<div style="display:flex;gap:6px;padding:2px 4px;border-bottom:1px solid rgba(255,255,255,0.03);font-size:10px;">
                <span class="mono" style="color:${CYAN};min-width:100px;">${_esc(tid)}</span>
                <span style="color:#999;flex:1;">${_esc(name)}</span>
                <span style="color:${allianceColor};font-size:9px;">${_esc(alliance)}</span>
            </div>`;
        }).join('');
        targetsHtml = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;margin-top:6px;">
            <div style="font-size:10px;color:${GREEN};margin-bottom:4px;text-transform:uppercase;letter-spacing:0.5px;">INVOLVED TARGETS (${targets.length})</div>
            <div style="max-height:120px;overflow-y:auto;">${targetItems}</div>
        </div>`;
    }

    // Report generation button
    const reportBtn = `<div style="border-top:1px solid rgba(0,240,255,0.15);padding-top:6px;margin-top:8px;display:flex;gap:6px;align-items:center;">
        <button class="panel-action-btn panel-action-btn-primary" data-action="gen-report" data-recon-id="${_esc(id)}" style="font-size:0.42rem;">GENERATE REPORT</button>
        <button class="panel-action-btn" data-action="back-to-list" style="font-size:0.42rem;">BACK</button>
        <span data-bind="report-status" style="font-size:9px;color:#555;margin-left:auto;"></span>
    </div>`;

    return statsRow + timelineHtml + targetsHtml + reportBtn;
}

// ---------------------------------------------------------------------------
// Report render
// ---------------------------------------------------------------------------

function _reportView(report) {
    if (!report) return '';
    if (report.error) return `<div style="color:${MAGENTA};padding:8px;">${_esc(report.error)}</div>`;

    const title = report.title || 'Incident Report';
    const createdBy = report.created_by || 'operator';
    const createdAt = _formatTimestamp(report.created_at);
    const classification = (report.classification || 'unclassified').toUpperCase();
    const findings = report.findings || [];
    const recommendations = report.recommendations || [];

    let findingsHtml = '';
    if (findings.length > 0) {
        findingsHtml = `<div style="margin-top:6px;">
            <div style="font-size:10px;color:${YELLOW};margin-bottom:3px;">FINDINGS</div>
            ${findings.map(f => `<div style="font-size:9px;color:#999;padding:2px 0;border-left:2px solid ${YELLOW};padding-left:6px;margin-bottom:2px;">${_esc(typeof f === 'string' ? f : f.text || f.description || JSON.stringify(f))}</div>`).join('')}
        </div>`;
    }

    let recsHtml = '';
    if (recommendations.length > 0) {
        recsHtml = `<div style="margin-top:6px;">
            <div style="font-size:10px;color:${GREEN};margin-bottom:3px;">RECOMMENDATIONS</div>
            ${recommendations.map(r => `<div style="font-size:9px;color:#999;padding:2px 0;border-left:2px solid ${GREEN};padding-left:6px;margin-bottom:2px;">${_esc(typeof r === 'string' ? r : r.text || r.description || JSON.stringify(r))}</div>`).join('')}
        </div>`;
    }

    return `<div style="border:1px solid ${BORDER};padding:8px;margin-top:6px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
            <span style="color:${CYAN};font-size:12px;font-weight:bold;">${_esc(title)}</span>
            <span style="color:${DIM};font-size:9px;border:1px solid ${DIM};padding:1px 4px;border-radius:2px;">${classification}</span>
        </div>
        <div style="font-size:9px;color:#555;margin-bottom:6px;">By ${_esc(createdBy)} | ${_esc(createdAt)}</div>
        ${findingsHtml}
        ${recsHtml}
    </div>`;
}

// ---------------------------------------------------------------------------
// Panel Definition
// ---------------------------------------------------------------------------

export const ForensicsPanelDef = {
    id: 'forensics',
    title: 'FORENSICS',
    defaultPosition: { x: 300, y: 100 },
    defaultSize: { w: 520, h: 600 },

    create(_panel) {
        const el = document.createElement('div');
        el.className = 'forensics-panel';
        el.style.cssText = 'padding:8px;overflow-y:auto;height:100%;';

        el.innerHTML = `
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
                <span style="color:${CYAN};font-size:12px;font-weight:bold;">FORENSIC RECONSTRUCTION</span>
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh-forensics" style="font-size:0.42rem;margin-left:auto;">REFRESH</button>
                <span data-bind="forensics-timestamp" style="font-size:10px;color:#555;font-family:monospace;">--</span>
            </div>

            <div style="border:1px solid ${BORDER};padding:8px;margin-bottom:8px;">
                <div style="font-size:10px;color:${MAGENTA};margin-bottom:6px;text-transform:uppercase;letter-spacing:0.5px;">NEW RECONSTRUCTION</div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                    <div>
                        <label style="font-size:9px;color:#888;display:block;margin-bottom:2px;">START</label>
                        <input type="datetime-local" data-bind="recon-start"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#ccc;padding:3px 6px;font-size:10px;font-family:monospace;">
                    </div>
                    <div>
                        <label style="font-size:9px;color:#888;display:block;margin-bottom:2px;">END</label>
                        <input type="datetime-local" data-bind="recon-end"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#ccc;padding:3px 6px;font-size:10px;font-family:monospace;">
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr;gap:4px;margin-top:6px;">
                    <div>
                        <label style="font-size:8px;color:#555;">N</label>
                        <input type="number" step="0.001" data-bind="recon-north" placeholder="N"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#888;padding:2px 4px;font-size:9px;">
                    </div>
                    <div>
                        <label style="font-size:8px;color:#555;">S</label>
                        <input type="number" step="0.001" data-bind="recon-south" placeholder="S"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#888;padding:2px 4px;font-size:9px;">
                    </div>
                    <div>
                        <label style="font-size:8px;color:#555;">E</label>
                        <input type="number" step="0.001" data-bind="recon-east" placeholder="E"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#888;padding:2px 4px;font-size:9px;">
                    </div>
                    <div>
                        <label style="font-size:8px;color:#555;">W</label>
                        <input type="number" step="0.001" data-bind="recon-west" placeholder="W"
                               style="width:100%;background:#0a0a0f;border:1px solid ${BORDER};color:#888;padding:2px 4px;font-size:9px;">
                    </div>
                    <div style="display:flex;align-items:flex-end;">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="create-recon" style="font-size:0.42rem;width:100%;">RECONSTRUCT</button>
                    </div>
                </div>
                <div data-bind="create-status" style="font-size:9px;color:#555;margin-top:4px;"></div>
            </div>

            <div data-bind="forensics-content">
                <div style="color:#555;padding:16px;text-align:center;">Loading forensic reconstructions...</div>
            </div>

            <div data-bind="forensics-detail" style="display:none;">
            </div>

            <div data-bind="forensics-report" style="display:none;">
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const contentEl = bodyEl.querySelector('[data-bind="forensics-content"]');
        const detailEl = bodyEl.querySelector('[data-bind="forensics-detail"]');
        const reportEl = bodyEl.querySelector('[data-bind="forensics-report"]');
        const timestampEl = bodyEl.querySelector('[data-bind="forensics-timestamp"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh-forensics"]');
        const createBtn = bodyEl.querySelector('[data-action="create-recon"]');
        const createStatusEl = bodyEl.querySelector('[data-bind="create-status"]');

        const startInput = bodyEl.querySelector('[data-bind="recon-start"]');
        const endInput = bodyEl.querySelector('[data-bind="recon-end"]');
        const northInput = bodyEl.querySelector('[data-bind="recon-north"]');
        const southInput = bodyEl.querySelector('[data-bind="recon-south"]');
        const eastInput = bodyEl.querySelector('[data-bind="recon-east"]');
        const westInput = bodyEl.querySelector('[data-bind="recon-west"]');

        let timer = null;
        let currentView = 'list'; // 'list' | 'detail'

        // Set default time range: last 1 hour
        if (startInput) {
            const now = new Date();
            const oneHourAgo = new Date(now.getTime() - 3600000);
            startInput.value = oneHourAgo.toISOString().slice(0, 16);
            endInput.value = now.toISOString().slice(0, 16);
        }

        async function refreshList() {
            try {
                const data = await _fetchReconstructions();
                if (contentEl && currentView === 'list') {
                    contentEl.innerHTML = _reconstructionList(data.reconstructions || []);

                    // Wire click handlers on reconstruction items
                    contentEl.querySelectorAll('.forensics-recon-item').forEach(item => {
                        item.addEventListener('click', () => {
                            const reconId = item.dataset.reconId;
                            if (reconId) showDetail(reconId);
                        });
                    });
                }
                if (timestampEl) timestampEl.textContent = new Date().toLocaleTimeString();
            } catch (err) {
                if (contentEl) contentEl.innerHTML = `<div style="color:${MAGENTA};padding:12px;text-align:center;">Failed to load reconstructions</div>`;
            }
        }

        async function showDetail(reconId) {
            currentView = 'detail';
            if (contentEl) contentEl.style.display = 'none';
            if (detailEl) {
                detailEl.style.display = 'block';
                detailEl.innerHTML = `<div style="color:#555;padding:8px;text-align:center;">Loading reconstruction ${_esc(reconId)}...</div>`;

                const recon = await _fetchReconstruction(reconId);
                detailEl.innerHTML = _reconstructionDetail(recon);

                // Wire report button
                const reportBtn = detailEl.querySelector('[data-action="gen-report"]');
                if (reportBtn) {
                    reportBtn.addEventListener('click', async () => {
                        const rid = reportBtn.dataset.reconId;
                        const statusEl = detailEl.querySelector('[data-bind="report-status"]');
                        if (statusEl) statusEl.textContent = 'Generating...';
                        if (statusEl) statusEl.style.color = YELLOW;

                        const report = await _generateReport(rid, '', 'operator');
                        if (reportEl) {
                            reportEl.style.display = 'block';
                            reportEl.innerHTML = _reportView(report);
                        }
                        if (statusEl) {
                            statusEl.textContent = report.error ? 'Failed' : 'Report generated';
                            statusEl.style.color = report.error ? MAGENTA : GREEN;
                        }
                    });
                }

                // Wire back button
                const backBtn = detailEl.querySelector('[data-action="back-to-list"]');
                if (backBtn) {
                    backBtn.addEventListener('click', () => {
                        currentView = 'list';
                        if (detailEl) detailEl.style.display = 'none';
                        if (reportEl) { reportEl.style.display = 'none'; reportEl.innerHTML = ''; }
                        if (contentEl) contentEl.style.display = 'block';
                        refreshList();
                    });
                }
            }
        }

        // Create reconstruction handler
        if (createBtn) {
            createBtn.addEventListener('click', async () => {
                const startVal = startInput ? startInput.value : '';
                const endVal = endInput ? endInput.value : '';

                if (!startVal || !endVal) {
                    if (createStatusEl) { createStatusEl.textContent = 'Start and end times are required'; createStatusEl.style.color = MAGENTA; }
                    return;
                }

                const startTs = new Date(startVal).getTime() / 1000;
                const endTs = new Date(endVal).getTime() / 1000;

                if (endTs <= startTs) {
                    if (createStatusEl) { createStatusEl.textContent = 'End must be after start'; createStatusEl.style.color = MAGENTA; }
                    return;
                }

                // Optional bounds
                let bounds = null;
                const n = northInput ? parseFloat(northInput.value) : NaN;
                const s = southInput ? parseFloat(southInput.value) : NaN;
                const e = eastInput ? parseFloat(eastInput.value) : NaN;
                const w = westInput ? parseFloat(westInput.value) : NaN;
                if (!isNaN(n) && !isNaN(s) && !isNaN(e) && !isNaN(w)) {
                    bounds = { north: n, south: s, east: e, west: w };
                }

                if (createStatusEl) { createStatusEl.textContent = 'Reconstructing...'; createStatusEl.style.color = YELLOW; }

                const result = await _createReconstruction(startTs, endTs, bounds, 10000);
                if (result.error) {
                    if (createStatusEl) { createStatusEl.textContent = `Error: ${result.error}`; createStatusEl.style.color = MAGENTA; }
                } else {
                    if (createStatusEl) { createStatusEl.textContent = 'Reconstruction complete'; createStatusEl.style.color = GREEN; }
                    refreshList();
                }
            });
        }

        if (refreshBtn) refreshBtn.addEventListener('click', refreshList);

        refreshList();
        timer = setInterval(refreshList, REFRESH_MS);
        panel._forensicsTimer = timer;
    },

    unmount(_bodyEl, panel) {
        if (panel && panel._forensicsTimer) {
            clearInterval(panel._forensicsTimer);
            panel._forensicsTimer = null;
        }
    },
};
