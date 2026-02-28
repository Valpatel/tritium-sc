// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM-SC Video Player tests
 * Tests player state, formatting, playback controls, volume, muting,
 * timeline events, annotation overlay, detection filtering, keyboard
 * handling, and all exported window.* functions.
 * Run: node tests/js/test_player.js
 */

const fs = require('fs');
const vm = require('vm');

// Simple test runner
let passed = 0, failed = 0;
function assert(cond, msg) {
    if (!cond) { console.error('FAIL:', msg); failed++; }
    else { console.log('PASS:', msg); passed++; }
}
function assertEqual(a, b, msg) {
    assert(a === b, msg + ` (got ${JSON.stringify(a)}, expected ${JSON.stringify(b)})`);
}
function assertClose(a, b, eps, msg) {
    assert(Math.abs(a - b) < (eps || 0.001), msg + ` (got ${a}, expected ${b})`);
}

// ============================================================
// DOM + browser mocks
// ============================================================

const _elements = {};
const _createdElements = [];
let _notifications = [];
let _playVideoCalls = [];

function createMockElement(tag) {
    const children = [];
    const classSet = new Set();
    const eventListeners = {};
    const dataset = {};
    const style = {};
    let _innerHTML = '';
    let _textContent = '';

    const el = {
        tagName: (tag || 'DIV').toUpperCase(),
        className: '',
        id: '',
        get innerHTML() { return _innerHTML; },
        set innerHTML(val) { _innerHTML = val; },
        get textContent() { return _textContent; },
        set textContent(val) { _textContent = String(val); },
        style,
        dataset,
        children,
        childNodes: children,
        parentNode: null,
        hidden: false,
        value: '',
        disabled: false,
        title: '',
        onclick: null,
        // Video-specific properties
        paused: true,
        currentTime: 0,
        duration: 120,
        volume: 1,
        muted: false,
        playbackRate: 1,
        videoWidth: 1920,
        videoHeight: 1080,
        get classList() {
            return {
                add(cls) { classSet.add(cls); },
                remove(cls) { classSet.delete(cls); },
                contains(cls) { return classSet.has(cls); },
                toggle(cls, force) {
                    if (force === undefined) {
                        if (classSet.has(cls)) classSet.delete(cls);
                        else classSet.add(cls);
                    } else if (force) classSet.add(cls);
                    else classSet.delete(cls);
                },
            };
        },
        _classSet: classSet,
        appendChild(child) {
            children.push(child);
            if (child && typeof child === 'object') child.parentNode = el;
            return child;
        },
        remove() {},
        focus() {},
        play() { el.paused = false; return Promise.resolve(); },
        pause() { el.paused = true; },
        addEventListener(evt, fn) {
            if (!eventListeners[evt]) eventListeners[evt] = [];
            eventListeners[evt].push(fn);
        },
        removeEventListener(evt, fn) {
            if (eventListeners[evt]) {
                eventListeners[evt] = eventListeners[evt].filter(f => f !== fn);
            }
        },
        querySelector(sel) {
            if (sel === '.player-wrapper') {
                const wrapper = createMockElement('div');
                wrapper.requestFullscreen = () => Promise.resolve();
                return wrapper;
            }
            return createMockElement('div');
        },
        querySelectorAll(sel) { return []; },
        closest(sel) {
            if (sel === '.player-wrapper') {
                const wrapper = createMockElement('div');
                wrapper.requestFullscreen = () => Promise.resolve();
                return wrapper;
            }
            return null;
        },
        getBoundingClientRect() {
            return { left: 0, top: 0, right: 800, bottom: 40, width: 800, height: 40 };
        },
        getContext(type) {
            return {
                clearRect() {},
                strokeRect() {},
                fillRect() {},
                fillText() {},
                measureText(text) { return { width: text.length * 7 }; },
                strokeStyle: '',
                fillStyle: '',
                lineWidth: 1,
                font: '',
            };
        },
        requestFullscreen() { return Promise.resolve(); },
        _eventListeners: eventListeners,
    };
    return el;
}

// Pre-create the elements that getElementById will return
_elements['main-player'] = createMockElement('video');
_elements['play-btn'] = createMockElement('button');
_elements['timeline'] = createMockElement('div');
_elements['timeline-progress'] = createMockElement('div');
_elements['current-time'] = createMockElement('span');
_elements['duration'] = createMockElement('span');
_elements['timeline-events'] = createMockElement('div');
_elements['btn-toggle-annotations'] = createMockElement('button');
_elements['annotation-overlay'] = null; // Initially no overlay

// Video element setup
_elements['main-player'].duration = 120;
_elements['main-player'].currentTime = 0;
_elements['main-player'].paused = true;
_elements['main-player'].videoWidth = 1920;
_elements['main-player'].videoHeight = 1080;

// Give the video a closest() method that returns a wrapper
_elements['main-player'].closest = (sel) => {
    if (sel === '.player-wrapper') {
        const wrapper = createMockElement('div');
        wrapper.requestFullscreen = () => Promise.resolve();
        return wrapper;
    }
    return null;
};

let _domContentLoadedHandler = null;
let _keydownHandler = null;

const sandbox = {
    Math, Date, console, Map, Set, Array, Object, Number, String, Boolean,
    Infinity, NaN, undefined, parseInt, parseFloat, isNaN, isFinite, JSON,
    Promise, setTimeout, clearTimeout, setInterval, clearInterval, Error,
    RegExp, Symbol,
    document: {
        createElement(tag) {
            const el = createMockElement(tag);
            _createdElements.push(el);
            return el;
        },
        getElementById(id) {
            return _elements[id] || null;
        },
        querySelector(sel) {
            if (sel === '.player-wrapper') {
                const wrapper = createMockElement('div');
                wrapper.requestFullscreen = () => Promise.resolve();
                return wrapper;
            }
            return null;
        },
        addEventListener(evt, fn) {
            if (evt === 'DOMContentLoaded') _domContentLoadedHandler = fn;
            if (evt === 'keydown') _keydownHandler = fn;
        },
        removeEventListener() {},
        fullscreenElement: null,
        exitFullscreen() { return Promise.resolve(); },
    },
    window: {},
    TRITIUM: {
        state: {
            currentView: 'player',
            selectedVideo: 0,
            selectedChannel: 'ch01',
            selectedDate: '2026-01-15',
            videos: [
                { filename: 'vid001.mp4' },
                { filename: 'vid002.mp4' },
                { filename: 'vid003.mp4' },
            ],
        },
        showNotification(title, msg, type) {
            _notifications.push({ title, msg, type });
        },
        playVideo(idx) {
            _playVideoCalls.push(idx);
        },
    },
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    performance: { now: () => Date.now() },
};

const ctx = vm.createContext(sandbox);

// Load player.js
const code = fs.readFileSync(__dirname + '/../../frontend/js/player.js', 'utf8');
vm.runInContext(code, ctx);

// Trigger DOMContentLoaded to initialize player
if (_domContentLoadedHandler) {
    _domContentLoadedHandler();
}

// Extract exports from window
const {
    togglePlay,
    seekTo,
    playNextVideo,
    playPreviousVideo,
    setPlaybackRate,
    toggleFullscreen,
    addTimelineEvent,
    clearTimelineEvents,
    skip,
    adjustVolume,
    toggleMute,
    loadVideoDetections,
    toggleAnnotations,
    renderAnnotationOverlay,
    analyzeCurrentVideo,
} = ctx.window;

// Access internal state (exposed as module globals within the sandbox)
const playerState = ctx.playerState;
const playerElements = ctx.playerElements;
const formatDuration = ctx.formatDuration;
const getCurrentFrameDetections = ctx.getCurrentFrameDetections;
const updatePlayButton = ctx.updatePlayButton;
const updateProgress = ctx.updateProgress;
const updateTimeDisplay = ctx.updateTimeDisplay;
const onVideoTimeUpdate = ctx.onVideoTimeUpdate;
const handlePlayerKeyboard = ctx.handlePlayerKeyboard;
const updateAnnotationButton = ctx.updateAnnotationButton;
const createAnnotationOverlay = ctx.createAnnotationOverlay;
const hideAnnotationOverlay = ctx.hideAnnotationOverlay;
const updateTimelineWithDetections = ctx.updateTimelineWithDetections;

// ============================================================
// Helper: reset state between groups
// ============================================================
function resetState() {
    playerState.playing = false;
    playerState.currentTime = 0;
    playerState.duration = 120;
    playerState.volume = 1;
    playerState.muted = false;
    playerState.playbackRate = 1;
    playerState.showAnnotations = true;
    playerState.detections = [];
    playerState.currentVideoInfo = null;
    _notifications = [];
    _playVideoCalls = [];
    _elements['main-player'].paused = true;
    _elements['main-player'].currentTime = 0;
    _elements['main-player'].duration = 120;
    _elements['main-player'].volume = 1;
    _elements['main-player'].muted = false;
    _elements['main-player'].playbackRate = 1;
    _elements['timeline-events'].innerHTML = '';
    sandbox.TRITIUM.state.selectedVideo = 0;
    sandbox.TRITIUM.state.currentView = 'player';
}

// ============================================================
// 1. Exports exist
// ============================================================
console.log('\n--- Exports ---');

assert(typeof togglePlay === 'function', 'togglePlay exported');
assert(typeof seekTo === 'function', 'seekTo exported');
assert(typeof playNextVideo === 'function', 'playNextVideo exported');
assert(typeof playPreviousVideo === 'function', 'playPreviousVideo exported');
assert(typeof setPlaybackRate === 'function', 'setPlaybackRate exported');
assert(typeof toggleFullscreen === 'function', 'toggleFullscreen exported');
assert(typeof addTimelineEvent === 'function', 'addTimelineEvent exported');
assert(typeof clearTimelineEvents === 'function', 'clearTimelineEvents exported');
assert(typeof skip === 'function', 'skip exported');
assert(typeof adjustVolume === 'function', 'adjustVolume exported');
assert(typeof toggleMute === 'function', 'toggleMute exported');
assert(typeof loadVideoDetections === 'function', 'loadVideoDetections exported');
assert(typeof toggleAnnotations === 'function', 'toggleAnnotations exported');
assert(typeof renderAnnotationOverlay === 'function', 'renderAnnotationOverlay exported');
assert(typeof analyzeCurrentVideo === 'function', 'analyzeCurrentVideo exported');

// ============================================================
// 2. Initial player state
// ============================================================
console.log('\n--- Initial state ---');

resetState();
assertEqual(playerState.playing, false, 'initial playing is false');
assertEqual(playerState.currentTime, 0, 'initial currentTime is 0');
assertEqual(playerState.duration, 120, 'initial duration');
assertEqual(playerState.volume, 1, 'initial volume is 1');
assertEqual(playerState.muted, false, 'initial muted is false');
assertEqual(playerState.playbackRate, 1, 'initial playbackRate is 1');
assertEqual(playerState.showAnnotations, true, 'initial showAnnotations is true');
assert(Array.isArray(playerState.detections), 'detections is an array');
assertEqual(playerState.detections.length, 0, 'detections starts empty');
assertEqual(playerState.currentVideoInfo, null, 'currentVideoInfo starts null');

// ============================================================
// 3. Player elements wired after DOMContentLoaded
// ============================================================
console.log('\n--- Player elements wired ---');

assert(playerElements.video !== null, 'video element wired');
assert(playerElements.playBtn !== null, 'playBtn element wired');
assert(playerElements.timeline !== null, 'timeline element wired');
assert(playerElements.timelineProgress !== null, 'timelineProgress element wired');
assert(playerElements.currentTimeDisplay !== null, 'currentTimeDisplay element wired');
assert(playerElements.durationDisplay !== null, 'durationDisplay element wired');

// ============================================================
// 4. formatDuration
// ============================================================
console.log('\n--- formatDuration ---');

assertEqual(formatDuration(0), '00:00:00', 'formatDuration(0)');
assertEqual(formatDuration(1), '00:00:01', 'formatDuration(1)');
assertEqual(formatDuration(59), '00:00:59', 'formatDuration(59)');
assertEqual(formatDuration(60), '00:01:00', 'formatDuration(60)');
assertEqual(formatDuration(61), '00:01:01', 'formatDuration(61)');
assertEqual(formatDuration(3599), '00:59:59', 'formatDuration(3599)');
assertEqual(formatDuration(3600), '01:00:00', 'formatDuration(3600)');
assertEqual(formatDuration(3661), '01:01:01', 'formatDuration(3661)');
assertEqual(formatDuration(86399), '23:59:59', 'formatDuration(86399)');
// Edge cases
assertEqual(formatDuration(null), '00:00:00', 'formatDuration(null)');
assertEqual(formatDuration(undefined), '00:00:00', 'formatDuration(undefined)');
assertEqual(formatDuration(NaN), '00:00:00', 'formatDuration(NaN)');
assertEqual(formatDuration(1.7), '00:00:01', 'formatDuration fractional floors');
assertEqual(formatDuration(59.9), '00:00:59', 'formatDuration 59.9 floors to 59');

// ============================================================
// 5. togglePlay
// ============================================================
console.log('\n--- togglePlay ---');

resetState();
assert(_elements['main-player'].paused === true, 'video starts paused');
togglePlay();
assertEqual(_elements['main-player'].paused, false, 'togglePlay unpauses');
togglePlay();
assertEqual(_elements['main-player'].paused, true, 'togglePlay pauses again');

// ============================================================
// 6. updatePlayButton
// ============================================================
console.log('\n--- updatePlayButton ---');

resetState();
playerState.playing = true;
updatePlayButton();
assertEqual(_elements['play-btn'].textContent, '\u23F8', 'play button shows pause icon when playing');

playerState.playing = false;
updatePlayButton();
assertEqual(_elements['play-btn'].textContent, '\u25B6', 'play button shows play icon when paused');

// ============================================================
// 7. skip
// ============================================================
console.log('\n--- skip ---');

resetState();
_elements['main-player'].currentTime = 30;
skip(10);
assertEqual(_elements['main-player'].currentTime, 40, 'skip(10) forwards 10s');

_elements['main-player'].currentTime = 5;
skip(-10);
assertEqual(_elements['main-player'].currentTime, 0, 'skip(-10) clamps to 0');

_elements['main-player'].currentTime = 115;
skip(10);
assertEqual(_elements['main-player'].currentTime, 120, 'skip(10) clamps to duration');

_elements['main-player'].currentTime = 60;
skip(0);
assertEqual(_elements['main-player'].currentTime, 60, 'skip(0) stays same');

_elements['main-player'].currentTime = 50;
skip(-50);
assertEqual(_elements['main-player'].currentTime, 0, 'skip exactly to 0');

// ============================================================
// 8. adjustVolume
// ============================================================
console.log('\n--- adjustVolume ---');

resetState();
_elements['main-player'].volume = 0.5;
adjustVolume(0.1);
assertClose(_elements['main-player'].volume, 0.6, 0.01, 'adjustVolume +0.1');
assertEqual(playerState.volume, _elements['main-player'].volume, 'playerState.volume synced');

_elements['main-player'].volume = 0.95;
adjustVolume(0.1);
assertClose(_elements['main-player'].volume, 1.0, 0.01, 'adjustVolume clamps to 1');

_elements['main-player'].volume = 0.05;
adjustVolume(-0.1);
assertClose(_elements['main-player'].volume, 0.0, 0.01, 'adjustVolume clamps to 0');

// Check notification was sent
assert(_notifications.length > 0, 'adjustVolume sends notification');
assertEqual(_notifications[_notifications.length - 1].title, 'VOLUME', 'notification title is VOLUME');

// ============================================================
// 9. toggleMute
// ============================================================
console.log('\n--- toggleMute ---');

resetState();
assertEqual(_elements['main-player'].muted, false, 'starts unmuted');
toggleMute();
assertEqual(_elements['main-player'].muted, true, 'toggleMute mutes');
assertEqual(playerState.muted, true, 'playerState.muted synced');
assert(_notifications.some(n => n.msg === 'MUTED'), 'mute notification sent');

toggleMute();
assertEqual(_elements['main-player'].muted, false, 'toggleMute unmutes');
assertEqual(playerState.muted, false, 'playerState.muted synced back');
assert(_notifications.some(n => n.msg === 'UNMUTED'), 'unmute notification sent');

// ============================================================
// 10. setPlaybackRate
// ============================================================
console.log('\n--- setPlaybackRate ---');

resetState();
setPlaybackRate(2);
assertEqual(playerState.playbackRate, 2, 'playerState.playbackRate set to 2');
assertEqual(_elements['main-player'].playbackRate, 2, 'video.playbackRate set to 2');
assert(_notifications.some(n => n.title === 'SPEED' && n.msg === '2x'), 'speed notification sent');

setPlaybackRate(0.5);
assertEqual(playerState.playbackRate, 0.5, 'playbackRate set to 0.5');
assert(_notifications.some(n => n.msg === '0.5x'), 'half speed notification');

// ============================================================
// 11. seekTo
// ============================================================
console.log('\n--- seekTo ---');

resetState();
// Simulate a click at 50% of the timeline
const fakeEvent = { clientX: 400 };
seekTo(fakeEvent);
// rect.left=0, rect.width=800, so percent = 400/800 = 0.5, seekTime = 0.5 * 120 = 60
assertEqual(_elements['main-player'].currentTime, 60, 'seekTo 50% of 120s = 60s');

// Click at 0%
seekTo({ clientX: 0 });
assertEqual(_elements['main-player'].currentTime, 0, 'seekTo 0% = 0s');

// Click at 100%
seekTo({ clientX: 800 });
assertEqual(_elements['main-player'].currentTime, 120, 'seekTo 100% = 120s');

// ============================================================
// 12. playNextVideo / playPreviousVideo
// ============================================================
console.log('\n--- playNextVideo / playPreviousVideo ---');

resetState();
sandbox.TRITIUM.state.selectedVideo = 0;
playNextVideo();
assertEqual(_playVideoCalls[_playVideoCalls.length - 1], 1, 'playNextVideo goes to index 1');

sandbox.TRITIUM.state.selectedVideo = 1;
playNextVideo();
assertEqual(_playVideoCalls[_playVideoCalls.length - 1], 2, 'playNextVideo goes to index 2');

// At last video, should not advance
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = 2;
playNextVideo();
assertEqual(_playVideoCalls.length, 0, 'playNextVideo at end does nothing');

// Previous
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = 2;
playPreviousVideo();
assertEqual(_playVideoCalls[_playVideoCalls.length - 1], 1, 'playPreviousVideo goes to index 1');

sandbox.TRITIUM.state.selectedVideo = 1;
playPreviousVideo();
assertEqual(_playVideoCalls[_playVideoCalls.length - 1], 0, 'playPreviousVideo goes to index 0');

// At first video, should not go back
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = 0;
playPreviousVideo();
assertEqual(_playVideoCalls.length, 0, 'playPreviousVideo at start does nothing');

// Null selectedVideo edge case
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = null;
playNextVideo();
assertEqual(_playVideoCalls.length, 0, 'playNextVideo with null selectedVideo does nothing');
playPreviousVideo();
assertEqual(_playVideoCalls.length, 0, 'playPreviousVideo with null selectedVideo does nothing');

// ============================================================
// 13. updateProgress
// ============================================================
console.log('\n--- updateProgress ---');

resetState();
_elements['main-player'].currentTime = 60;
_elements['main-player'].duration = 120;
updateProgress();
assertEqual(_elements['timeline-progress'].style.width, '50%', 'progress at 50%');

_elements['main-player'].currentTime = 0;
updateProgress();
assertEqual(_elements['timeline-progress'].style.width, '0%', 'progress at 0%');

_elements['main-player'].currentTime = 120;
updateProgress();
assertEqual(_elements['timeline-progress'].style.width, '100%', 'progress at 100%');

// No duration: should return early
_elements['main-player'].duration = 0;
_elements['timeline-progress'].style.width = 'unchanged';
updateProgress();
assertEqual(_elements['timeline-progress'].style.width, 'unchanged', 'updateProgress with zero duration returns early');

// ============================================================
// 14. updateTimeDisplay
// ============================================================
console.log('\n--- updateTimeDisplay ---');

resetState();
playerState.currentTime = 65;
updateTimeDisplay();
assertEqual(_elements['current-time'].textContent, '00:01:05', 'time display shows 00:01:05 for 65s');

playerState.currentTime = 0;
updateTimeDisplay();
assertEqual(_elements['current-time'].textContent, '00:00:00', 'time display shows 00:00:00 for 0s');

// ============================================================
// 15. addTimelineEvent / clearTimelineEvents
// ============================================================
console.log('\n--- addTimelineEvent / clearTimelineEvents ---');

resetState();
playerState.duration = 100;
addTimelineEvent(50, 'person');
assertEqual(_elements['timeline-events'].children.length, 1, 'one marker added');
assertEqual(_elements['timeline-events'].children[0].style.left, '50%', 'marker at 50%');
assert(_elements['timeline-events'].children[0].className === 'timeline-event', 'marker has timeline-event class');
assert(_elements['timeline-events'].children[0].title.includes('person'), 'marker title includes type');

addTimelineEvent(25, 'vehicle');
assertEqual(_elements['timeline-events'].children.length, 2, 'two markers added');
assertEqual(_elements['timeline-events'].children[1].style.left, '25%', 'second marker at 25%');

clearTimelineEvents();
assertEqual(_elements['timeline-events'].innerHTML, '', 'clearTimelineEvents empties container');

// Edge case: no duration, addTimelineEvent returns early
resetState();
playerState.duration = 0;
addTimelineEvent(10, 'test');
assertEqual(_elements['timeline-events'].children.length, 0, 'addTimelineEvent with no duration does nothing');

// ============================================================
// 16. getCurrentFrameDetections
// ============================================================
console.log('\n--- getCurrentFrameDetections ---');

resetState();
playerState.currentVideoInfo = { channel: 'ch01', date: '2026-01-15', filename: 'v.mp4', fps: 30 };
playerState.detections = [
    { time_ms: 1000, class_name: 'person', confidence: 0.9, bbox: [10, 20, 50, 80] },
    { time_ms: 1030, class_name: 'car', confidence: 0.8, bbox: [100, 200, 300, 400] },
    { time_ms: 5000, class_name: 'person', confidence: 0.7, bbox: [10, 20, 50, 80] },
];
playerState.currentTime = 1.0; // 1000ms
const dets = getCurrentFrameDetections();
assertEqual(dets.length, 2, 'getCurrentFrameDetections returns 2 detections near 1000ms');

playerState.currentTime = 5.0; // 5000ms
const dets2 = getCurrentFrameDetections();
assertEqual(dets2.length, 1, 'getCurrentFrameDetections returns 1 detection near 5000ms');

// No detections
playerState.detections = [];
const dets3 = getCurrentFrameDetections();
assertEqual(dets3.length, 0, 'getCurrentFrameDetections returns empty with no detections');

// No video info
playerState.detections = [{ time_ms: 1000 }];
playerState.currentVideoInfo = null;
const dets4 = getCurrentFrameDetections();
assertEqual(dets4.length, 0, 'getCurrentFrameDetections returns empty with no video info');

// ============================================================
// 17. toggleAnnotations
// ============================================================
console.log('\n--- toggleAnnotations ---');

resetState();
playerState.showAnnotations = true;
_notifications = [];
toggleAnnotations();
assertEqual(playerState.showAnnotations, false, 'toggleAnnotations flips to false');
assert(_notifications.some(n => n.msg === 'Detections hidden'), 'hidden notification sent');

_notifications = [];
toggleAnnotations();
assertEqual(playerState.showAnnotations, true, 'toggleAnnotations flips back to true');
assert(_notifications.some(n => n.msg === 'Detections visible'), 'visible notification sent');

// ============================================================
// 18. updateAnnotationButton
// ============================================================
console.log('\n--- updateAnnotationButton ---');

resetState();
const btn = _elements['btn-toggle-annotations'];

// Has detections
updateAnnotationButton(true, false);
assertEqual(btn.textContent, '\u25FB DETECTIONS', 'button shows DETECTIONS when has detections');
assert(btn._classSet.has('active'), 'button has active class');
assertEqual(btn.title, 'Toggle detection boxes (A)', 'button title for detections');

// Show analyze option
updateAnnotationButton(false, true);
assertEqual(btn.textContent, '\u27F3 ANALYZE', 'button shows ANALYZE when no detections');
assert(!btn._classSet.has('active'), 'button active class removed');
assertEqual(btn.title, 'Run AI analysis on this video', 'button title for analyze');

// ============================================================
// 19. onVideoTimeUpdate
// ============================================================
console.log('\n--- onVideoTimeUpdate ---');

resetState();
_elements['main-player'].currentTime = 42;
_elements['main-player'].duration = 120;
onVideoTimeUpdate();
assertEqual(playerState.currentTime, 42, 'onVideoTimeUpdate syncs currentTime');
assertEqual(_elements['current-time'].textContent, '00:00:42', 'time display updated');
assertEqual(_elements['timeline-progress'].style.width, '35%', 'progress updated to 35%');

// ============================================================
// 20. handlePlayerKeyboard - space/k togglePlay
// ============================================================
console.log('\n--- handlePlayerKeyboard ---');

resetState();
sandbox.TRITIUM.state.currentView = 'player';

// Space bar toggles play
_elements['main-player'].paused = true;
let prevented = false;
handlePlayerKeyboard({ key: ' ', target: { tagName: 'DIV' }, preventDefault() { prevented = true; } });
assertEqual(_elements['main-player'].paused, false, 'space toggles play');
assert(prevented, 'space prevents default');

// 'k' toggles play
handlePlayerKeyboard({ key: 'k', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].paused, true, 'k toggles pause');

// ArrowLeft skips -10
_elements['main-player'].currentTime = 30;
handlePlayerKeyboard({ key: 'ArrowLeft', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 20, 'ArrowLeft skips -10');

// ArrowRight skips +10
handlePlayerKeyboard({ key: 'ArrowRight', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 30, 'ArrowRight skips +10');

// 'j' skips -10
_elements['main-player'].currentTime = 50;
handlePlayerKeyboard({ key: 'j', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 40, 'j skips -10');

// 'l' skips +10
handlePlayerKeyboard({ key: 'l', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 50, 'l skips +10');

// 'm' toggles mute
_elements['main-player'].muted = false;
handlePlayerKeyboard({ key: 'm', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].muted, true, 'm toggles mute');

// ArrowUp adjusts volume up
_elements['main-player'].volume = 0.5;
handlePlayerKeyboard({ key: 'ArrowUp', target: { tagName: 'DIV' }, preventDefault() {} });
assertClose(_elements['main-player'].volume, 0.6, 0.01, 'ArrowUp increases volume');

// ArrowDown adjusts volume down
handlePlayerKeyboard({ key: 'ArrowDown', target: { tagName: 'DIV' }, preventDefault() {} });
assertClose(_elements['main-player'].volume, 0.5, 0.01, 'ArrowDown decreases volume');

// Number keys seek to percentage
playerState.duration = 120;
handlePlayerKeyboard({ key: '5', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 60, 'key 5 seeks to 50%');

handlePlayerKeyboard({ key: '0', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].currentTime, 0, 'key 0 seeks to 0%');

handlePlayerKeyboard({ key: '9', target: { tagName: 'DIV' }, preventDefault() {} });
assertClose(_elements['main-player'].currentTime, 108, 0.01, 'key 9 seeks to 90%');

// '>' increases playback rate
playerState.playbackRate = 1;
handlePlayerKeyboard({ key: '>', shiftKey: true, target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(playerState.playbackRate, 1.25, '> increases playback rate');

// '<' decreases playback rate
handlePlayerKeyboard({ key: '<', shiftKey: true, target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(playerState.playbackRate, 1.0, '< decreases playback rate');

// Clamp max playback rate
playerState.playbackRate = 2;
_elements['main-player'].playbackRate = 2;
handlePlayerKeyboard({ key: '>', shiftKey: true, target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(playerState.playbackRate, 2, '> does not exceed 2x');

// Clamp min playback rate
playerState.playbackRate = 0.25;
_elements['main-player'].playbackRate = 0.25;
handlePlayerKeyboard({ key: '<', shiftKey: true, target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(playerState.playbackRate, 0.25, '< does not go below 0.25x');

// 'n' plays next video
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = 0;
handlePlayerKeyboard({ key: 'n', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_playVideoCalls.length, 1, 'n plays next video');
assertEqual(_playVideoCalls[0], 1, 'n advances to index 1');

// 'b' plays previous video
_playVideoCalls = [];
sandbox.TRITIUM.state.selectedVideo = 2;
handlePlayerKeyboard({ key: 'b', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_playVideoCalls.length, 1, 'b plays previous video');
assertEqual(_playVideoCalls[0], 1, 'b goes back to index 1');

// ============================================================
// 21. handlePlayerKeyboard - guard: not player view
// ============================================================
console.log('\n--- handlePlayerKeyboard guards ---');

resetState();
sandbox.TRITIUM.state.currentView = 'map';
_elements['main-player'].paused = true;
handlePlayerKeyboard({ key: ' ', target: { tagName: 'DIV' }, preventDefault() {} });
assertEqual(_elements['main-player'].paused, true, 'keyboard ignored when not player view');

// Guard: typing in input
sandbox.TRITIUM.state.currentView = 'player';
_elements['main-player'].paused = true;
handlePlayerKeyboard({ key: ' ', target: { tagName: 'INPUT' }, preventDefault() {} });
assertEqual(_elements['main-player'].paused, true, 'keyboard ignored when target is INPUT');

// ============================================================
// 22. updateTimelineWithDetections
// ============================================================
console.log('\n--- updateTimelineWithDetections ---');

resetState();
playerState.duration = 100;
playerState.detections = [
    { time_ms: 2000, class_name: 'person', confidence: 0.9, bbox: [0, 0, 10, 10] },
    { time_ms: 2500, class_name: 'person', confidence: 0.8, bbox: [0, 0, 10, 10] },
    { time_ms: 7000, class_name: 'car', confidence: 0.7, bbox: [0, 0, 10, 10] },
    { time_ms: 50000, class_name: 'truck', confidence: 0.6, bbox: [0, 0, 10, 10] },
];
updateTimelineWithDetections();
// Grouping: 2000ms/5000=0 -> key 0, 2500ms/5000=0 -> key 0, 7000ms/5000=1 -> key 5, 50000ms/5000=10 -> key 50
// So 3 groups: key 0 (persons), key 5 (car=vehicle), key 50 (truck=vehicle)
assert(_elements['timeline-events'].children.length >= 2, 'detection markers added to timeline');

// Empty detections
resetState();
playerState.duration = 100;
playerState.detections = [];
updateTimelineWithDetections();
assertEqual(_elements['timeline-events'].innerHTML, '', 'no markers when no detections');

// No duration
resetState();
playerState.duration = 0;
playerState.detections = [{ time_ms: 1000, class_name: 'person' }];
updateTimelineWithDetections();
// Should return early, timeline-events cleared then nothing added
assertEqual(_elements['timeline-events'].children.length, 0, 'no markers when no duration');

// ============================================================
// 23. hideAnnotationOverlay
// ============================================================
console.log('\n--- hideAnnotationOverlay ---');

resetState();
// When no overlay exists, should not throw
hideAnnotationOverlay(); // should not throw
assert(true, 'hideAnnotationOverlay with no overlay does not throw');

// ============================================================
// 24. createAnnotationOverlay
// ============================================================
console.log('\n--- createAnnotationOverlay ---');

resetState();
const overlay = createAnnotationOverlay();
// Video has a closest() returning a wrapper, so canvas should be created
assert(overlay !== null, 'createAnnotationOverlay returns a canvas');
if (overlay) {
    assertEqual(overlay.id, 'annotation-overlay', 'overlay has correct id');
    // video dimensions are 1920x1080
    assertEqual(overlay.width, 1920, 'overlay width matches video');
    assertEqual(overlay.height, 1080, 'overlay height matches video');
}

// With no video
const origVideo = playerElements.video;
playerElements.video = null;
const overlayNull = createAnnotationOverlay();
assertEqual(overlayNull, null, 'createAnnotationOverlay returns null with no video');
playerElements.video = origVideo;

// ============================================================
// 25. renderAnnotationOverlay
// ============================================================
console.log('\n--- renderAnnotationOverlay ---');

resetState();
// With showAnnotations off, it calls hideAnnotationOverlay (no throw)
playerState.showAnnotations = false;
renderAnnotationOverlay(); // should not throw
assert(true, 'renderAnnotationOverlay with annotations off does not throw');

// With showAnnotations on but no detections, should render empty
playerState.showAnnotations = true;
playerState.detections = [];
renderAnnotationOverlay();
assert(true, 'renderAnnotationOverlay with empty detections does not throw');

// ============================================================
// 26. loadVideoDetections (async)
// ============================================================
console.log('\n--- loadVideoDetections (async) ---');

// Mock fetch for detections
const origFetch = sandbox.fetch;

// Test successful load with detections
sandbox.fetch = (url) => {
    return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
            detections: [
                { time_ms: 1000, class_name: 'person', confidence: 0.9, bbox: [10, 20, 50, 80] },
                { time_ms: 2000, class_name: 'car', confidence: 0.8, bbox: [100, 200, 300, 400] },
            ],
            fps: 25,
        }),
    });
};

let asyncTests = 0;
const asyncTotal = 7;

resetState();
playerState.duration = 100;
loadVideoDetections('ch01', '2026-01-15', 'test.mp4').then(() => {
    assertEqual(playerState.detections.length, 2, 'loadVideoDetections loaded 2 detections');
    asyncTests++;
    assertEqual(playerState.currentVideoInfo.fps, 25, 'loadVideoDetections set fps');
    asyncTests++;
    assertEqual(playerState.currentVideoInfo.channel, 'ch01', 'loadVideoDetections set channel');
    asyncTests++;

    // Test 404 response (no detections)
    sandbox.fetch = () => Promise.resolve({ ok: false });
    return loadVideoDetections('ch01', '2026-01-15', 'missing.mp4');
}).then(() => {
    assertEqual(playerState.detections.length, 0, 'loadVideoDetections clears on 404');
    asyncTests++;

    // Test fetch error
    sandbox.fetch = () => Promise.reject(new Error('network fail'));
    return loadVideoDetections('ch01', '2026-01-15', 'error.mp4');
}).then(() => {
    assertEqual(playerState.detections.length, 0, 'loadVideoDetections clears on fetch error');
    asyncTests++;

    // Test response with no detections array
    sandbox.fetch = () => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ fps: 30 }),
    });
    return loadVideoDetections('ch01', '2026-01-15', 'empty.mp4');
}).then(() => {
    assertEqual(playerState.detections.length, 0, 'loadVideoDetections handles missing detections array');
    asyncTests++;

    // Test default fps
    sandbox.fetch = () => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ detections: [{ time_ms: 0 }] }),
    });
    return loadVideoDetections('ch01', '2026-01-15', 'nofps.mp4');
}).then(() => {
    assertEqual(playerState.currentVideoInfo.fps, 30, 'loadVideoDetections defaults to 30 fps');
    asyncTests++;

    // Restore fetch
    sandbox.fetch = origFetch;

    // Print async test summary
    console.log(`\nAsync tests completed: ${asyncTests}/${asyncTotal}`);

    // ============================================================
    // Summary
    // ============================================================
    console.log('\n========================================');
    console.log(`  TOTAL: ${passed} passed, ${failed} failed`);
    console.log('========================================');

    if (failed > 0) process.exit(1);
}).catch(err => {
    console.error('Async test error:', err);
    sandbox.fetch = origFetch;
    process.exit(1);
});
