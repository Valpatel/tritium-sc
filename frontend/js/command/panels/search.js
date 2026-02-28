// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Search / Intel Panel
// People and vehicle identification, recurring individual detection,
// suspicion scoring, visual similarity search, text search via CLIP.
// Uses /api/search/* endpoints.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

export const SearchPanelDef = {
    id: 'search',
    title: 'INTEL',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 360, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'search-panel-inner';
        el.innerHTML = `
            <div class="search-tabs" role="tablist">
                <button class="search-tab active" data-tab="people" role="tab">PEOPLE</button>
                <button class="search-tab" data-tab="vehicles" role="tab">VEHICLES</button>
                <button class="search-tab" data-tab="flagged" role="tab">FLAGGED</button>
                <button class="search-tab" data-tab="trends" role="tab">TRENDS</button>
            </div>
            <div class="search-query-bar">
                <input type="text" class="search-input" data-bind="search-input" placeholder="Search by description..." aria-label="Text search">
                <button class="panel-action-btn panel-action-btn-primary" data-action="text-search">SEARCH</button>
            </div>
            <div class="search-tab-content" data-bind="tab-content">
                <div class="search-tab-pane" data-pane="people" style="display:block">
                    <div class="search-stats" data-bind="people-stats"></div>
                    <ul class="panel-list search-results" data-bind="people-list" role="listbox" aria-label="Detected people">
                        <li class="panel-empty"><span class="panel-spinner"></span> Scanning for people...</li>
                    </ul>
                </div>
                <div class="search-tab-pane" data-pane="vehicles" style="display:none">
                    <div class="search-stats" data-bind="vehicle-stats"></div>
                    <ul class="panel-list search-results" data-bind="vehicle-list" role="listbox" aria-label="Detected vehicles">
                        <li class="panel-empty"><span class="panel-spinner"></span> Scanning for vehicles...</li>
                    </ul>
                </div>
                <div class="search-tab-pane" data-pane="flagged" style="display:none">
                    <ul class="panel-list search-results" data-bind="flagged-list" role="listbox" aria-label="Flagged individuals">
                        <li class="panel-empty"><span class="panel-spinner"></span> Loading flagged targets...</li>
                    </ul>
                </div>
                <div class="search-tab-pane" data-pane="trends" style="display:none">
                    <div class="search-trends" data-bind="trends-content"></div>
                </div>
            </div>
            <div class="search-detail" data-bind="detail" style="display:none"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const tabs = bodyEl.querySelectorAll('.search-tab');
        const panes = bodyEl.querySelectorAll('.search-tab-pane');
        const searchInput = bodyEl.querySelector('[data-bind="search-input"]');
        const searchBtn = bodyEl.querySelector('[data-action="text-search"]');
        const peopleList = bodyEl.querySelector('[data-bind="people-list"]');
        const vehicleList = bodyEl.querySelector('[data-bind="vehicle-list"]');
        const flaggedList = bodyEl.querySelector('[data-bind="flagged-list"]');
        const trendsContent = bodyEl.querySelector('[data-bind="trends-content"]');
        const peopleStats = bodyEl.querySelector('[data-bind="people-stats"]');
        const vehicleStats = bodyEl.querySelector('[data-bind="vehicle-stats"]');
        const detailEl = bodyEl.querySelector('[data-bind="detail"]');

        let currentTab = 'people';

        // Tab switching
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                const tabName = tab.dataset.tab;
                currentTab = tabName;
                panes.forEach(p => {
                    p.style.display = p.dataset.pane === tabName ? 'block' : 'none';
                });
                if (detailEl) detailEl.style.display = 'none';
            });
        });

        function renderTargetItem(item, type) {
            const tid = item.thumbnail_id || '';
            const label = item.label || '';
            const score = item.suspicion_score;
            const appearances = item.total_appearances || item.merged_count || 0;
            const dotClass = score !== undefined
                ? (score >= 70 ? 'panel-dot-hostile' : score >= 40 ? 'panel-dot-amber' : 'panel-dot-green')
                : 'panel-dot-neutral';

            return `<li class="panel-list-item search-result-item" data-tid="${_esc(tid)}" data-type="${type}" role="option">
                <div class="search-thumb-wrap">
                    <img class="search-thumb" src="/api/search/thumbnail/${_esc(tid)}" alt="" loading="lazy" onerror="this.style.display='none'">
                </div>
                <span class="panel-dot ${dotClass}"></span>
                <div class="search-item-info">
                    <span class="search-item-label">${_esc(label || item.target_type || type)}</span>
                    <span class="search-item-meta mono">${appearances > 0 ? appearances + ' sightings' : ''}${score !== undefined ? ' | risk ' + score : ''}</span>
                </div>
                <button class="panel-btn search-flag-btn" data-action="flag" data-tid="${_esc(tid)}" title="Flag suspicious">&excl;</button>
            </li>`;
        }

        function renderSearchResults(listEl, items, type) {
            if (!listEl) return;
            if (!items || items.length === 0) {
                listEl.innerHTML = `<li class="panel-empty">No ${type} found</li>`;
                return;
            }

            listEl.innerHTML = items.map(item => renderTargetItem(item, type)).join('');

            // Click handlers
            listEl.querySelectorAll('.search-result-item').forEach(el => {
                el.addEventListener('click', (e) => {
                    if (e.target.closest('[data-action="flag"]')) return;
                    showDetail(el.dataset.tid);
                });
            });

            listEl.querySelectorAll('[data-action="flag"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    flagSuspicious(btn.dataset.tid);
                });
            });
        }

        async function fetchPeople() {
            try {
                const resp = await fetch('/api/search/people?limit=50');
                if (!resp.ok) { renderSearchResults(peopleList, [], 'people'); return; }
                const data = await resp.json();
                const items = data.items || [];
                renderSearchResults(peopleList, items, 'person');
                if (peopleStats) {
                    peopleStats.innerHTML = `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">DETECTED</span>
                            <span class="panel-stat-value">${data.total || 0}</span>
                        </div>`;
                }
            } catch (_) {
                renderSearchResults(peopleList, [], 'people');
            }
        }

        async function fetchVehicles() {
            try {
                const resp = await fetch('/api/search/vehicles?limit=50');
                if (!resp.ok) { renderSearchResults(vehicleList, [], 'vehicles'); return; }
                const data = await resp.json();
                const items = data.items || [];
                renderSearchResults(vehicleList, items, 'vehicle');
                if (vehicleStats) {
                    vehicleStats.innerHTML = `
                        <div class="panel-stat-row">
                            <span class="panel-stat-label">DETECTED</span>
                            <span class="panel-stat-value">${data.total || 0}</span>
                        </div>`;
                }
            } catch (_) {
                renderSearchResults(vehicleList, [], 'vehicles');
            }
        }

        async function fetchFlagged() {
            try {
                const resp = await fetch('/api/search/flagged');
                if (!resp.ok) { renderSearchResults(flaggedList, [], 'flagged'); return; }
                const data = await resp.json();
                renderSearchResults(flaggedList, data.individuals || [], 'flagged');
            } catch (_) {
                renderSearchResults(flaggedList, [], 'flagged');
            }
        }

        async function fetchTrends() {
            if (!trendsContent) return;
            try {
                const resp = await fetch('/api/search/trends?days=7');
                if (!resp.ok) {
                    trendsContent.innerHTML = '<div class="panel-empty">No trend data</div>';
                    return;
                }
                const data = await resp.json();
                const hours = data.hourly_distribution || [];
                const maxH = Math.max(...hours, 1);

                trendsContent.innerHTML = `
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">PEOPLE (7d)</span>
                        <span class="panel-stat-value">${data.total_people || 0}</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">VEHICLES (7d)</span>
                        <span class="panel-stat-value">${data.total_vehicles || 0}</span>
                    </div>
                    <div class="panel-stat-row">
                        <span class="panel-stat-label">PEAK HOUR</span>
                        <span class="panel-stat-value">${data.peak_hour !== null ? data.peak_hour + ':00' : '--'}</span>
                    </div>
                    <div class="panel-section-label">HOURLY ACTIVITY</div>
                    <div class="search-hourly-chart">
                        ${hours.map((h, i) => `<div class="search-hour-bar" style="height:${Math.round((h / maxH) * 100)}%" title="${i}:00 — ${h} detections"></div>`).join('')}
                    </div>
                    <div class="search-hour-labels">
                        <span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>
                    </div>
                `;
            } catch (_) {
                trendsContent.innerHTML = '<div class="panel-empty">Trends unavailable</div>';
            }
        }

        async function showDetail(tid) {
            if (!detailEl || !tid) return;
            detailEl.style.display = '';
            detailEl.innerHTML = '<div class="panel-empty">Loading...</div>';

            try {
                // Fetch target detail, sightings, similar, and label in parallel
                const [targetResp, sightingsResp, similarResp, labelResp] = await Promise.all([
                    fetch(`/api/search/target/${encodeURIComponent(tid)}`),
                    fetch(`/api/search/sightings?thumbnail_id=${encodeURIComponent(tid)}&limit=10`).catch(() => null),
                    fetch(`/api/search/similar?thumbnail_id=${encodeURIComponent(tid)}&limit=4`).catch(() => null),
                    fetch(`/api/search/label?thumbnail_id=${encodeURIComponent(tid)}`).catch(() => null),
                ]);
                if (!targetResp.ok) { detailEl.style.display = 'none'; return; }
                const item = await targetResp.json();

                // Parse sightings
                let sightings = [];
                if (sightingsResp && sightingsResp.ok) {
                    const sData = await sightingsResp.json();
                    sightings = sData.sightings || sData.appearances || [];
                }

                // Parse similar
                let similar = item.similar_targets || [];
                if (similarResp && similarResp.ok) {
                    const simData = await similarResp.json();
                    similar = simData.results || simData.similar || similar;
                }

                // Parse label
                let currentLabel = item.label || '';
                if (labelResp && labelResp.ok) {
                    const labelData = await labelResp.json();
                    currentLabel = labelData.label || currentLabel;
                }

                detailEl.innerHTML = `
                    <div class="search-detail-header">
                        <div class="panel-section-label">TARGET DETAIL</div>
                        <button class="panel-btn" data-action="close-detail">&times;</button>
                    </div>
                    <div class="search-detail-body">
                        <div class="search-detail-thumb">
                            <img src="/api/search/thumbnail/${_esc(tid)}" alt="" onerror="this.style.display='none'">
                        </div>
                        <div class="panel-stat-row"><span class="panel-stat-label">TYPE</span><span class="panel-stat-value">${_esc(item.target_type || '--')}</span></div>
                        <div class="panel-stat-row"><span class="panel-stat-label">CONFIDENCE</span><span class="panel-stat-value">${item.confidence ? (item.confidence * 100).toFixed(0) + '%' : '--'}</span></div>
                        ${item.merged_count ? `<div class="panel-stat-row"><span class="panel-stat-label">MERGED</span><span class="panel-stat-value">${item.merged_count} identities</span></div>` : ''}
                        <div class="search-label-row">
                            <span class="panel-stat-label">LABEL</span>
                            <input type="text" class="search-label-input mono" data-bind="label-input"
                                   value="${_esc(currentLabel)}" placeholder="Name or tag..." spellcheck="false">
                            <button class="panel-action-btn" data-action="save-label" title="Save label">SAVE</button>
                        </div>
                        ${similar.length > 0 ? `
                            <div class="panel-section-label">SIMILAR TARGETS</div>
                            <div class="search-similar-row">
                                ${similar.slice(0, 4).map(s => {
                                    const url = s.thumbnail_url || `/api/search/thumbnail/${_esc(s.thumbnail_id || '')}`;
                                    const pct = s.similarity ? (s.similarity * 100).toFixed(0) + '%' : '';
                                    return `<div class="search-similar-item">
                                        <img class="search-similar-thumb" src="${_esc(url)}" title="${pct} match" loading="lazy" onerror="this.style.display='none'">
                                        <span class="mono" style="font-size:0.35rem;color:var(--text-ghost)">${pct}</span>
                                    </div>`;
                                }).join('')}
                            </div>
                        ` : ''}
                        ${sightings.length > 0 ? `
                            <div class="panel-section-label">SIGHTING TIMELINE</div>
                            <div class="search-sightings" data-bind="sightings">
                                ${sightings.slice(0, 10).map(s => {
                                    const time = s.timestamp ? new Date(s.timestamp).toLocaleString().substring(0, 16) : '';
                                    const camera = s.camera || s.source || '';
                                    return `<div class="search-sighting-entry">
                                        <span class="search-sighting-time mono">${_esc(time)}</span>
                                        <span class="search-sighting-cam mono" style="color:var(--text-ghost)">${_esc(camera)}</span>
                                    </div>`;
                                }).join('')}
                            </div>
                        ` : ''}
                        <div class="search-detail-actions">
                            <button class="panel-action-btn" data-action="merge-target" title="Merge with another">MERGE</button>
                            <button class="panel-action-btn" data-action="feedback-correct" title="Mark as correct">&#10003; CORRECT</button>
                            <button class="panel-action-btn" data-action="feedback-wrong" title="Mark as wrong">&#10007; WRONG</button>
                        </div>
                    </div>
                `;

                // Close detail
                detailEl.querySelector('[data-action="close-detail"]')?.addEventListener('click', () => {
                    detailEl.style.display = 'none';
                });

                // Save label (stalker detection safety feature)
                detailEl.querySelector('[data-action="save-label"]')?.addEventListener('click', async () => {
                    const labelInput = detailEl.querySelector('[data-bind="label-input"]');
                    if (!labelInput) return;
                    const newLabel = labelInput.value.trim();
                    try {
                        await fetch('/api/search/label', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ thumbnail_id: tid, label: newLabel }),
                        });
                        EventBus.emit('toast:show', { message: `Label saved: ${newLabel || '(cleared)'}`, type: 'info' });
                    } catch (_) {
                        EventBus.emit('toast:show', { message: 'Failed to save label', type: 'alert' });
                    }
                });

                // Merge action
                detailEl.querySelector('[data-action="merge-target"]')?.addEventListener('click', async () => {
                    const otherTid = prompt('Enter thumbnail ID to merge with:');
                    if (!otherTid) return;
                    try {
                        await fetch('/api/search/merge', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ source_id: tid, target_id: otherTid.trim() }),
                        });
                        EventBus.emit('toast:show', { message: 'Targets merged', type: 'info' });
                        fetchPeople();
                    } catch (_) {
                        EventBus.emit('toast:show', { message: 'Merge failed', type: 'alert' });
                    }
                });

                // Feedback actions
                detailEl.querySelector('[data-action="feedback-correct"]')?.addEventListener('click', async () => {
                    try {
                        await fetch('/api/search/feedback', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ thumbnail_id: tid, correct: true }),
                        });
                        EventBus.emit('toast:show', { message: 'Marked as correct', type: 'info' });
                    } catch (_) {}
                });
                detailEl.querySelector('[data-action="feedback-wrong"]')?.addEventListener('click', async () => {
                    try {
                        await fetch('/api/search/feedback', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ thumbnail_id: tid, correct: false }),
                        });
                        EventBus.emit('toast:show', { message: 'Marked as incorrect', type: 'info' });
                    } catch (_) {}
                });
            } catch (_) {
                detailEl.style.display = 'none';
            }
        }

        async function flagSuspicious(tid) {
            try {
                await fetch('/api/search/flag-suspicious', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ thumbnail_id: tid, reason: 'Flagged from UI' }),
                });
                EventBus.emit('toast:show', { message: 'Target flagged', type: 'alert' });
                fetchFlagged();
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to flag target', type: 'alert' });
            }
        }

        async function textSearch() {
            const query = searchInput?.value?.trim();
            if (!query) return;

            const targetList = currentTab === 'vehicles' ? vehicleList : peopleList;
            if (targetList) targetList.innerHTML = '<li class="panel-empty">Searching...</li>';

            try {
                const resp = await fetch(`/api/search/text-search?q=${encodeURIComponent(query)}&limit=30`);
                if (!resp.ok) {
                    if (targetList) targetList.innerHTML = '<li class="panel-empty">Search unavailable (CLIP not loaded)</li>';
                    return;
                }
                const data = await resp.json();
                renderSearchResults(targetList, data.results || [], 'search');
            } catch (_) {
                if (targetList) targetList.innerHTML = '<li class="panel-empty">Search failed</li>';
            }
        }

        // Text search
        if (searchBtn) searchBtn.addEventListener('click', textSearch);
        if (searchInput) searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') textSearch();
            e.stopPropagation(); // prevent panel shortcuts
        });

        // Initial fetch
        fetchPeople();
        fetchVehicles();
        fetchFlagged();
        fetchTrends();

        // Auto-refresh every 60s
        const refreshInterval = setInterval(() => {
            fetchPeople();
            fetchVehicles();
            fetchFlagged();
        }, 60000);
        panel._unsubs.push(() => clearInterval(refreshInterval));
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
