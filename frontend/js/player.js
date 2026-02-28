// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM - Video Player
 * Enhanced video playback with timeline and controls
 *
 * CRITICAL FEATURE: Annotation overlay for reviewing detections
 * Allows toggling bounding boxes on/off during playback
 */

// Player state
const playerState = {
    playing: false,
    currentTime: 0,
    duration: 0,
    volume: 1,
    muted: false,
    playbackRate: 1,
    // Annotation overlay state
    showAnnotations: true,
    detections: [],  // Frame-by-frame detection data
    currentVideoInfo: null,  // {channel, date, filename, fps}
};

// DOM elements
const playerElements = {
    video: null,
    playBtn: null,
    timeline: null,
    timelineProgress: null,
    currentTimeDisplay: null,
    durationDisplay: null,
};

/**
 * Initialize player
 */
document.addEventListener('DOMContentLoaded', () => {
    playerElements.video = document.getElementById('main-player');
    playerElements.playBtn = document.getElementById('play-btn');
    playerElements.timeline = document.getElementById('timeline');
    playerElements.timelineProgress = document.getElementById('timeline-progress');
    playerElements.currentTimeDisplay = document.getElementById('current-time');
    playerElements.durationDisplay = document.getElementById('duration');

    if (playerElements.video) {
        initPlayerEvents();
    }
});

/**
 * Initialize player event listeners
 */
function initPlayerEvents() {
    const video = playerElements.video;

    // Video events
    video.addEventListener('loadedmetadata', () => {
        playerState.duration = video.duration;
        playerElements.durationDisplay.textContent = formatDuration(video.duration);
    });

    video.addEventListener('timeupdate', onVideoTimeUpdate);

    video.addEventListener('play', () => {
        playerState.playing = true;
        updatePlayButton();
    });

    video.addEventListener('pause', () => {
        playerState.playing = false;
        updatePlayButton();
    });

    video.addEventListener('ended', () => {
        playerState.playing = false;
        updatePlayButton();
        playNextVideo();
    });

    // Timeline click
    playerElements.timeline.addEventListener('click', (e) => {
        seekTo(e);
    });

    // Keyboard shortcuts for player
    document.addEventListener('keydown', handlePlayerKeyboard);
}

/**
 * Toggle play/pause
 */
function togglePlay() {
    const video = playerElements.video;

    if (video.paused) {
        video.play().catch(e => console.log('Play failed:', e));
    } else {
        video.pause();
    }
}

/**
 * Seek to position on timeline
 */
function seekTo(event) {
    const video = playerElements.video;
    const timeline = playerElements.timeline;
    const rect = timeline.getBoundingClientRect();
    const percent = (event.clientX - rect.left) / rect.width;
    const seekTime = percent * video.duration;

    video.currentTime = seekTime;
}

/**
 * Update play button icon
 */
function updatePlayButton() {
    if (playerElements.playBtn) {
        playerElements.playBtn.textContent = playerState.playing ? '⏸' : '▶';
    }
}

/**
 * Update timeline progress bar
 */
function updateProgress() {
    const video = playerElements.video;
    if (!video.duration) return;

    const percent = (video.currentTime / video.duration) * 100;
    playerElements.timelineProgress.style.width = `${percent}%`;
}

/**
 * Update time display
 */
function updateTimeDisplay() {
    playerElements.currentTimeDisplay.textContent = formatDuration(playerState.currentTime);
}

/**
 * Format duration as HH:MM:SS
 */
function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '00:00:00';

    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);

    return [
        hrs.toString().padStart(2, '0'),
        mins.toString().padStart(2, '0'),
        secs.toString().padStart(2, '0'),
    ].join(':');
}

/**
 * Play next video in list
 */
function playNextVideo() {
    const state = TRITIUM.state;
    if (state.selectedVideo !== null && state.selectedVideo < state.videos.length - 1) {
        TRITIUM.playVideo(state.selectedVideo + 1);
    }
}

/**
 * Play previous video in list
 */
function playPreviousVideo() {
    const state = TRITIUM.state;
    if (state.selectedVideo !== null && state.selectedVideo > 0) {
        TRITIUM.playVideo(state.selectedVideo - 1);
    }
}

/**
 * Set playback rate
 */
function setPlaybackRate(rate) {
    playerState.playbackRate = rate;
    playerElements.video.playbackRate = rate;
    TRITIUM.showNotification('SPEED', `${rate}x`, 'info');
}

/**
 * Skip forward/backward
 */
function skip(seconds) {
    const video = playerElements.video;
    video.currentTime = Math.max(0, Math.min(video.duration, video.currentTime + seconds));
}

/**
 * Toggle fullscreen
 */
function toggleFullscreen() {
    const playerWrapper = document.querySelector('.player-wrapper');

    if (document.fullscreenElement) {
        document.exitFullscreen();
    } else {
        playerWrapper.requestFullscreen().catch(e => {
            console.log('Fullscreen failed:', e);
        });
    }
}

/**
 * Handle keyboard shortcuts for player
 */
function handlePlayerKeyboard(e) {
    // Only handle if player view is active
    if (TRITIUM.state.currentView !== 'player') return;

    // Don't handle if typing in input
    if (e.target.tagName === 'INPUT') return;

    switch (e.key) {
        case ' ':
        case 'k':
            e.preventDefault();
            togglePlay();
            break;

        case 'ArrowLeft':
            e.preventDefault();
            skip(-10);
            break;

        case 'ArrowRight':
            e.preventDefault();
            skip(10);
            break;

        case 'ArrowUp':
            e.preventDefault();
            adjustVolume(0.1);
            break;

        case 'ArrowDown':
            e.preventDefault();
            adjustVolume(-0.1);
            break;

        case 'j':
            skip(-10);
            break;

        case 'l':
            skip(10);
            break;

        case 'm':
            toggleMute();
            break;

        case 'f':
            toggleFullscreen();
            break;

        case 'a':
            // Toggle annotation overlay (detection bounding boxes)
            toggleAnnotations();
            break;

        case 'n':
            playNextVideo();
            break;

        case 'b':
            playPreviousVideo();
            break;

        case '>':
            if (e.shiftKey) {
                setPlaybackRate(Math.min(2, playerState.playbackRate + 0.25));
            }
            break;

        case '<':
            if (e.shiftKey) {
                setPlaybackRate(Math.max(0.25, playerState.playbackRate - 0.25));
            }
            break;

        case '0':
        case '1':
        case '2':
        case '3':
        case '4':
        case '5':
        case '6':
        case '7':
        case '8':
        case '9':
            // Seek to percentage of video
            const percent = parseInt(e.key) / 10;
            playerElements.video.currentTime = playerState.duration * percent;
            break;
    }
}

/**
 * Adjust volume
 */
function adjustVolume(delta) {
    const video = playerElements.video;
    video.volume = Math.max(0, Math.min(1, video.volume + delta));
    playerState.volume = video.volume;
    TRITIUM.showNotification('VOLUME', `${Math.round(video.volume * 100)}%`, 'info');
}

/**
 * Toggle mute
 */
function toggleMute() {
    const video = playerElements.video;
    video.muted = !video.muted;
    playerState.muted = video.muted;
    TRITIUM.showNotification('AUDIO', video.muted ? 'MUTED' : 'UNMUTED', 'info');
}

/**
 * Add event markers to timeline
 */
function addTimelineEvent(time, type) {
    const duration = playerState.duration;
    if (!duration) return;

    const percent = (time / duration) * 100;
    const marker = document.createElement('div');
    marker.className = 'timeline-event';
    marker.style.left = `${percent}%`;
    marker.title = `${type} at ${formatDuration(time)}`;

    document.getElementById('timeline-events').appendChild(marker);
}

/**
 * Clear timeline events
 */
function clearTimelineEvents() {
    document.getElementById('timeline-events').innerHTML = '';
}

// =============================================================================
// ANNOTATION OVERLAY - Detection bounding boxes on video
// =============================================================================

/**
 * Load detection data for current video
 */
async function loadVideoDetections(channel, date, filename) {
    try {
        const response = await fetch(`/api/videos/detections/${channel}/${date}/${filename}`);
        if (!response.ok) {
            console.log('[PLAYER] No detections available for this video');
            playerState.detections = [];
            updateAnnotationButton(false, true);  // No detections, show analyze option
            return;
        }

        const data = await response.json();
        playerState.detections = data.detections || [];
        playerState.currentVideoInfo = {
            channel,
            date,
            filename,
            fps: data.fps || 30,
        };

        console.log(`[PLAYER] Loaded ${playerState.detections.length} detections for annotation overlay`);

        // Update button state based on detection availability
        if (playerState.detections.length === 0) {
            updateAnnotationButton(false, true);  // No detections, show analyze option
        } else {
            updateAnnotationButton(true, false);  // Has detections
        }

        // Mark detection points on timeline
        updateTimelineWithDetections();

    } catch (e) {
        console.log('[PLAYER] Could not load detections:', e.message);
        playerState.detections = [];
        updateAnnotationButton(false, true);
    }
}

/**
 * Update annotation button state
 */
function updateAnnotationButton(hasDetections, showAnalyzeOption) {
    const btn = document.getElementById('btn-toggle-annotations');
    if (!btn) return;

    if (hasDetections) {
        btn.textContent = '◻ DETECTIONS';
        btn.onclick = toggleAnnotations;
        btn.classList.add('active');
        btn.title = 'Toggle detection boxes (A)';
    } else if (showAnalyzeOption) {
        btn.textContent = '⟳ ANALYZE';
        btn.onclick = analyzeCurrentVideo;
        btn.classList.remove('active');
        btn.title = 'Run AI analysis on this video';
    }
}

/**
 * Trigger on-demand analysis for current video
 */
async function analyzeCurrentVideo() {
    if (!playerState.currentVideoInfo) {
        const state = TRITIUM.state;
        if (!state.selectedChannel || !state.selectedDate || !state.videos[state.selectedVideo]) {
            TRITIUM.showNotification('ERROR', 'No video selected', 'error');
            return;
        }
        playerState.currentVideoInfo = {
            channel: state.selectedChannel,
            date: state.selectedDate,
            filename: state.videos[state.selectedVideo].filename,
        };
    }

    const { channel, date, filename } = playerState.currentVideoInfo;

    TRITIUM.showNotification('ANALYZING', 'Running AI detection...', 'info');

    const btn = document.getElementById('btn-toggle-annotations');
    if (btn) {
        btn.textContent = '⏳ ANALYZING...';
        btn.disabled = true;
    }

    try {
        const response = await fetch(`/api/videos/analyze/${channel}/${date}/${filename}`, {
            method: 'POST',
        });

        if (!response.ok) {
            throw new Error('Analysis failed');
        }

        const result = await response.json();
        TRITIUM.showNotification('COMPLETE', `Found ${result.detection_count} detections`, 'success');

        // Reload detections
        await loadVideoDetections(channel, date, filename);

    } catch (e) {
        TRITIUM.showNotification('ERROR', 'Analysis failed: ' + e.message, 'error');
        updateAnnotationButton(false, true);
    } finally {
        if (btn) {
            btn.disabled = false;
        }
    }
}

/**
 * Update timeline with detection markers
 */
function updateTimelineWithDetections() {
    clearTimelineEvents();

    if (!playerState.detections.length || !playerState.duration) return;

    // Group detections by approximate time (every 5 seconds)
    const groups = {};
    for (const det of playerState.detections) {
        const timeKey = Math.floor(det.time_ms / 5000) * 5;
        if (!groups[timeKey]) {
            groups[timeKey] = { person: 0, vehicle: 0 };
        }
        if (det.class_name === 'person') {
            groups[timeKey].person++;
        } else if (['car', 'truck', 'bus', 'motorcycle'].includes(det.class_name)) {
            groups[timeKey].vehicle++;
        }
    }

    // Add markers for each group
    for (const [timeKey, counts] of Object.entries(groups)) {
        const timeSec = parseInt(timeKey);
        const type = counts.person > 0 ? 'person' : 'vehicle';
        addTimelineEvent(timeSec, type);
    }
}

/**
 * Get detections for current frame
 */
function getCurrentFrameDetections() {
    if (!playerState.detections.length || !playerState.currentVideoInfo) {
        return [];
    }

    const currentTimeMs = playerState.currentTime * 1000;
    const fps = playerState.currentVideoInfo.fps || 30;
    const frameTolerance = 1000 / fps;  // One frame worth of time

    return playerState.detections.filter(det => {
        return Math.abs(det.time_ms - currentTimeMs) < frameTolerance * 2;
    });
}

/**
 * Render annotation overlay on video
 */
function renderAnnotationOverlay() {
    if (!playerState.showAnnotations) {
        hideAnnotationOverlay();
        return;
    }

    const detections = getCurrentFrameDetections();
    let overlay = document.getElementById('annotation-overlay');

    // Create overlay canvas if it doesn't exist
    if (!overlay) {
        overlay = createAnnotationOverlay();
    }

    if (!overlay) return;

    const video = playerElements.video;
    const ctx = overlay.getContext('2d');

    // Clear previous frame
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    if (detections.length === 0) return;

    // Calculate scale factors
    const scaleX = overlay.width / video.videoWidth;
    const scaleY = overlay.height / video.videoHeight;

    // Draw each detection
    for (const det of detections) {
        const [x1, y1, x2, y2] = det.bbox;
        const x = x1 * scaleX;
        const y = y1 * scaleY;
        const w = (x2 - x1) * scaleX;
        const h = (y2 - y1) * scaleY;

        // Color based on class
        const color = det.class_name === 'person' ? '#ff2a6d' : '#fcee0a';

        // Draw bounding box
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.strokeRect(x, y, w, h);

        // Draw label background
        const label = `${det.class_name} ${Math.round(det.confidence * 100)}%`;
        ctx.font = '12px JetBrains Mono, monospace';
        const textWidth = ctx.measureText(label).width;

        ctx.fillStyle = color;
        ctx.fillRect(x, y - 18, textWidth + 8, 18);

        // Draw label text
        ctx.fillStyle = '#000';
        ctx.fillText(label, x + 4, y - 5);

        // Draw track ID if available
        if (det.track_id) {
            ctx.fillStyle = color;
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.fillText(`ID:${det.track_id}`, x + 2, y + h - 4);
        }
    }
}

/**
 * Create the annotation overlay canvas
 */
function createAnnotationOverlay() {
    const video = playerElements.video;
    if (!video) return null;

    const wrapper = video.closest('.player-wrapper');
    if (!wrapper) return null;

    // Create canvas
    const canvas = document.createElement('canvas');
    canvas.id = 'annotation-overlay';
    canvas.style.cssText = `
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        pointer-events: none;
        z-index: 10;
    `;

    // Match video dimensions
    canvas.width = video.videoWidth || 1920;
    canvas.height = video.videoHeight || 1080;

    wrapper.style.position = 'relative';
    wrapper.appendChild(canvas);

    return canvas;
}

/**
 * Hide/remove annotation overlay
 */
function hideAnnotationOverlay() {
    const overlay = document.getElementById('annotation-overlay');
    if (overlay) {
        const ctx = overlay.getContext('2d');
        ctx.clearRect(0, 0, overlay.width, overlay.height);
    }
}

/**
 * Toggle annotation visibility
 */
function toggleAnnotations() {
    playerState.showAnnotations = !playerState.showAnnotations;

    if (playerState.showAnnotations) {
        renderAnnotationOverlay();
        TRITIUM.showNotification('ANNOTATIONS', 'Detections visible', 'info');
    } else {
        hideAnnotationOverlay();
        TRITIUM.showNotification('ANNOTATIONS', 'Detections hidden', 'info');
    }

    // Update toggle button state
    const btn = document.getElementById('btn-toggle-annotations');
    if (btn) {
        btn.classList.toggle('active', playerState.showAnnotations);
    }
}

/**
 * Update annotation overlay on video time update
 */
function onVideoTimeUpdate() {
    playerState.currentTime = playerElements.video.currentTime;
    updateTimeDisplay();
    updateProgress();

    // Render annotations for current frame
    if (playerState.showAnnotations && playerState.detections.length > 0) {
        renderAnnotationOverlay();
    }
}

// Export functions
window.togglePlay = togglePlay;
window.seekTo = seekTo;
window.playNextVideo = playNextVideo;
window.playPreviousVideo = playPreviousVideo;
window.setPlaybackRate = setPlaybackRate;
window.toggleFullscreen = toggleFullscreen;
window.addTimelineEvent = addTimelineEvent;
window.clearTimelineEvents = clearTimelineEvents;
window.skip = skip;
window.adjustVolume = adjustVolume;
window.toggleMute = toggleMute;
// Annotation overlay exports
window.loadVideoDetections = loadVideoDetections;
window.toggleAnnotations = toggleAnnotations;
window.renderAnnotationOverlay = renderAnnotationOverlay;
window.analyzeCurrentVideo = analyzeCurrentVideo;
