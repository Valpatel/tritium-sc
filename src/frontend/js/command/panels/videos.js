// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Video Playback Panel
// Browse NVR channels, dates, and video files. Stream MP4 with
// detection annotation overlay. Uses /api/videos/* endpoints.

import { EventBus } from '../events.js';

function _esc(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = String(text);
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (!bytes) return '--';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

export const VideosPanelDef = {
    id: 'videos',
    title: 'RECORDINGS',
    defaultPosition: { x: 8, y: 8 },
    defaultSize: { w: 340, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'videos-panel-inner';
        el.innerHTML = `
            <div class="vid-nav" data-bind="nav">
                <div class="vid-toolbar">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                    <button class="panel-action-btn" data-action="back" style="display:none">&larr; BACK</button>
                </div>
                <div class="vid-breadcrumb mono" data-bind="breadcrumb" style="font-size:0.45rem;color:var(--text-ghost);padding:2px 0"></div>
            </div>
            <ul class="panel-list vid-list" data-bind="list" role="listbox" aria-label="Video recordings">
                <li class="panel-empty">Loading channels...</li>
            </ul>
            <div class="vid-player" data-bind="player" style="display:none">
                <div class="vid-player-header">
                    <span class="mono vid-player-name" data-bind="player-name" style="font-size:0.5rem;color:var(--text-dim)"></span>
                    <button class="panel-btn" data-action="close-player">&times;</button>
                </div>
                <div class="vid-player-container">
                    <video class="vid-video" data-bind="video" controls preload="metadata"></video>
                </div>
                <div class="vid-player-info" data-bind="player-info"></div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const listEl = bodyEl.querySelector('[data-bind="list"]');
        const breadcrumbEl = bodyEl.querySelector('[data-bind="breadcrumb"]');
        const playerEl = bodyEl.querySelector('[data-bind="player"]');
        const videoEl = bodyEl.querySelector('[data-bind="video"]');
        const playerName = bodyEl.querySelector('[data-bind="player-name"]');
        const playerInfo = bodyEl.querySelector('[data-bind="player-info"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const backBtn = bodyEl.querySelector('[data-action="back"]');
        const closePlayerBtn = bodyEl.querySelector('[data-action="close-player"]');

        // Navigation state
        let level = 'channels'; // channels -> dates -> videos
        let currentChannel = null;
        let currentDate = null;

        function updateBreadcrumb() {
            if (!breadcrumbEl) return;
            const parts = ['CHANNELS'];
            if (currentChannel !== null) parts.push(`CH ${currentChannel}`);
            if (currentDate) parts.push(currentDate);
            breadcrumbEl.textContent = parts.join(' > ');
            if (backBtn) backBtn.style.display = level === 'channels' ? 'none' : '';
        }

        function renderChannels(channels) {
            if (!listEl) return;
            if (!channels || channels.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No recording channels found</li>';
                return;
            }

            listEl.innerHTML = channels.map(ch => `
                <li class="panel-list-item vid-item" data-channel="${ch.channel}" role="option">
                    <span class="panel-dot panel-dot-green"></span>
                    <div class="vid-item-info">
                        <span class="vid-item-name">${_esc(ch.name)}</span>
                        <span class="vid-item-meta mono">${ch.date_count} dates, ${ch.total_videos} videos</span>
                    </div>
                </li>
            `).join('');

            listEl.querySelectorAll('.vid-item').forEach(item => {
                item.addEventListener('click', () => {
                    currentChannel = parseInt(item.dataset.channel, 10);
                    level = 'dates';
                    updateBreadcrumb();
                    fetchDates(currentChannel);
                });
            });
        }

        function renderDates(dates) {
            if (!listEl) return;
            if (!dates || dates.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No recordings for this channel</li>';
                return;
            }

            listEl.innerHTML = dates.map(d => `
                <li class="panel-list-item vid-item" data-date="${_esc(d.date)}" role="option">
                    <span class="panel-dot panel-dot-neutral"></span>
                    <div class="vid-item-info">
                        <span class="vid-item-name">${_esc(d.date)}</span>
                        <span class="vid-item-meta mono">${d.video_count} clips</span>
                    </div>
                </li>
            `).join('');

            listEl.querySelectorAll('.vid-item').forEach(item => {
                item.addEventListener('click', () => {
                    currentDate = item.dataset.date;
                    level = 'videos';
                    updateBreadcrumb();
                    fetchVideos(currentChannel, currentDate);
                });
            });
        }

        function renderVideos(videos) {
            if (!listEl) return;
            if (!videos || videos.length === 0) {
                listEl.innerHTML = '<li class="panel-empty">No videos for this date</li>';
                return;
            }

            listEl.innerHTML = videos.map(v => {
                const time = v.timestamp ? new Date(v.timestamp).toLocaleTimeString().substring(0, 5) : '';
                return `<li class="panel-list-item vid-item vid-file-item" data-filename="${_esc(v.filename)}" role="option">
                    <span class="panel-dot panel-dot-neutral"></span>
                    <div class="vid-item-info">
                        <span class="vid-item-name">${_esc(v.filename)}</span>
                        <span class="vid-item-meta mono">${time} | ${formatBytes(v.size)}</span>
                    </div>
                    <button class="panel-btn vid-play-btn" data-action="play" data-filename="${_esc(v.filename)}" title="Play">&#9654;</button>
                </li>`;
            }).join('');

            listEl.querySelectorAll('[data-action="play"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    playVideo(btn.dataset.filename);
                });
            });

            listEl.querySelectorAll('.vid-file-item').forEach(item => {
                item.addEventListener('click', () => {
                    playVideo(item.dataset.filename);
                });
            });
        }

        function playVideo(filename) {
            if (!videoEl || !playerEl) return;
            const url = `/api/videos/stream/${currentChannel}/${currentDate}/${encodeURIComponent(filename)}`;
            videoEl.src = url;
            if (playerName) playerName.textContent = filename;
            playerEl.style.display = '';
            videoEl.play().catch(() => {});

            // Show info
            if (playerInfo) {
                playerInfo.innerHTML = `
                    <div class="panel-stat-row"><span class="panel-stat-label">CHANNEL</span><span class="panel-stat-value">${currentChannel}</span></div>
                    <div class="panel-stat-row"><span class="panel-stat-label">DATE</span><span class="panel-stat-value">${_esc(currentDate)}</span></div>
                `;
            }
        }

        function closePlayer() {
            if (videoEl) { videoEl.pause(); videoEl.src = ''; }
            if (playerEl) playerEl.style.display = 'none';
        }

        async function fetchChannels() {
            level = 'channels';
            currentChannel = null;
            currentDate = null;
            updateBreadcrumb();
            if (listEl) listEl.innerHTML = '<li class="panel-empty">Loading channels...</li>';

            try {
                const resp = await fetch('/api/videos/channels');
                if (!resp.ok) { renderChannels([]); return; }
                const data = await resp.json();
                renderChannels(Array.isArray(data) ? data : []);
            } catch (_) {
                renderChannels([]);
            }
        }

        async function fetchDates(channel) {
            if (listEl) listEl.innerHTML = '<li class="panel-empty">Loading dates...</li>';
            try {
                const resp = await fetch(`/api/videos/channels/${channel}/dates`);
                if (!resp.ok) { renderDates([]); return; }
                const data = await resp.json();
                renderDates(Array.isArray(data) ? data : []);
            } catch (_) {
                renderDates([]);
            }
        }

        async function fetchVideos(channel, date) {
            if (listEl) listEl.innerHTML = '<li class="panel-empty">Loading videos...</li>';
            try {
                const resp = await fetch(`/api/videos/channels/${channel}/dates/${date}`);
                if (!resp.ok) { renderVideos([]); return; }
                const data = await resp.json();
                renderVideos(Array.isArray(data) ? data : []);
            } catch (_) {
                renderVideos([]);
            }
        }

        function goBack() {
            closePlayer();
            if (level === 'videos') {
                level = 'dates';
                currentDate = null;
                updateBreadcrumb();
                fetchDates(currentChannel);
            } else if (level === 'dates') {
                fetchChannels();
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', () => {
            closePlayer();
            if (level === 'channels') fetchChannels();
            else if (level === 'dates') fetchDates(currentChannel);
            else if (level === 'videos') fetchVideos(currentChannel, currentDate);
        });
        if (backBtn) backBtn.addEventListener('click', goBack);
        if (closePlayerBtn) closePlayerBtn.addEventListener('click', closePlayer);

        fetchChannels();
    },

    unmount(bodyEl) {
        const videoEl = bodyEl.querySelector('[data-bind="video"]');
        if (videoEl) { videoEl.pause(); videoEl.src = ''; }
    },
};
