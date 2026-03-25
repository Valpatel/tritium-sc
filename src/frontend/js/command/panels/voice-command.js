// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Voice Command Panel
// Provides a microphone button for browser SpeechRecognition and text input
// for issuing voice commands to the system.

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';


// ============================================================
// SpeechRecognition wrapper
// ============================================================

class VoiceRecognizer {
    constructor(onResult, onError) {
        this._recognition = null;
        this._onResult = onResult;
        this._onError = onError;
        this._listening = false;
        this._init();
    }

    _init() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            return;
        }

        this._recognition = new SpeechRecognition();
        this._recognition.continuous = false;
        this._recognition.interimResults = false;
        this._recognition.lang = 'en-US';

        this._recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            this._listening = false;
            if (this._onResult) this._onResult(transcript);
        };

        this._recognition.onerror = (event) => {
            this._listening = false;
            if (this._onError) this._onError(event.error);
        };

        this._recognition.onend = () => {
            this._listening = false;
        };
    }

    get available() {
        return this._recognition !== null;
    }

    get listening() {
        return this._listening;
    }

    start() {
        if (!this._recognition || this._listening) return;
        try {
            this._recognition.start();
            this._listening = true;
        } catch (e) {
            this._listening = false;
        }
    }

    stop() {
        if (!this._recognition || !this._listening) return;
        this._recognition.stop();
        this._listening = false;
    }
}


// ============================================================
// Command dispatch
// ============================================================

async function sendCommand(text) {
    try {
        const resp = await fetch('/api/voice/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, source: 'panel' }),
        });
        return await resp.json();
    } catch (err) {
        return { status: 'error', detail: err.message };
    }
}


// ============================================================
// Panel Definition
// ============================================================

export const VoiceCommandPanelDef = {
    id: 'voice-command',
    title: 'VOICE COMMAND',
    defaultPosition: { x: null, y: null },
    defaultSize: { w: 320, h: 260 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'voice-command-panel-inner';
        el.innerHTML = `
            <div class="voice-command-input-row">
                <input type="text" class="voice-command-input" placeholder="Type a command..." autocomplete="off" />
                <button class="voice-mic-btn" title="Press to speak">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="1" width="6" height="12" rx="3"/>
                        <path d="M5 10v2a7 7 0 0 0 14 0v-2"/>
                        <line x1="12" y1="19" x2="12" y2="23"/>
                        <line x1="8" y1="23" x2="16" y2="23"/>
                    </svg>
                </button>
            </div>
            <div class="voice-command-status mono" data-bind="voice-status">Ready</div>
            <ul class="voice-command-history panel-list" data-bind="voice-history" role="list" aria-label="Command history">
                <li class="panel-empty">No commands yet</li>
            </ul>
        `;

        const input = el.querySelector('.voice-command-input');
        const micBtn = el.querySelector('.voice-mic-btn');
        const statusEl = el.querySelector('[data-bind="voice-status"]');
        const historyEl = el.querySelector('[data-bind="voice-history"]');
        const history = [];

        // Voice recognizer
        const recognizer = new VoiceRecognizer(
            (transcript) => {
                input.value = transcript;
                statusEl.textContent = `Heard: "${transcript}"`;
                submitCommand(transcript);
                micBtn.classList.remove('listening');
            },
            (error) => {
                statusEl.textContent = `Speech error: ${error}`;
                micBtn.classList.remove('listening');
            }
        );

        if (!recognizer.available) {
            micBtn.title = 'Speech recognition not available in this browser';
            micBtn.style.opacity = '0.3';
        }

        // Mic button
        micBtn.addEventListener('click', () => {
            if (recognizer.listening) {
                recognizer.stop();
                micBtn.classList.remove('listening');
                statusEl.textContent = 'Ready';
            } else {
                recognizer.start();
                micBtn.classList.add('listening');
                statusEl.textContent = 'Listening...';
            }
        });

        // Text input submit
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && input.value.trim()) {
                submitCommand(input.value.trim());
                input.value = '';
            }
        });

        async function submitCommand(text) {
            statusEl.textContent = `Sending: "${text}"`;
            const result = await sendCommand(text);

            // Add to history
            history.unshift({ text, result, time: new Date() });
            if (history.length > 20) history.pop();
            renderHistory();

            // Show result
            const detail = result.detail || result.action || 'Done';
            statusEl.textContent = detail;

            // Emit event for other panels to react
            EventBus.emit('voice:command', { text, result });
        }

        function renderHistory() {
            if (history.length === 0) {
                historyEl.innerHTML = '<li class="panel-empty">No commands yet</li>';
                return;
            }
            historyEl.innerHTML = history.map(h => {
                const statusIcon = h.result.status === 'ok' ? '>' : '!';
                const time = h.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                return `<li class="voice-history-item">
                    <span class="voice-history-icon">${_esc(statusIcon)}</span>
                    <span class="voice-history-text">${_esc(h.text)}</span>
                    <span class="voice-history-time mono">${_esc(time)}</span>
                </li>`;
            }).join('');
        }

        return el;
    },

    destroy(panel) {
        // No cleanup needed
    },
};
