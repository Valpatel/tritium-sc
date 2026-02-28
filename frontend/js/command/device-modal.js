// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Device Control Modal System
 *
 * Standard interface for clicking any device on the map and controlling it
 * through a type-specific panel. Every device type implements the DeviceControl
 * contract: { type, title, render, bind, update, destroy }.
 *
 * Usage:
 *   import { DeviceModalManager, DeviceControlRegistry, DeviceAPI } from './device-modal.js';
 *   DeviceModalManager.open('rover-01', 'rover', deviceData);
 *   DeviceModalManager.close();
 *
 * Exports: DeviceModalManager, DeviceControlRegistry, DeviceAPI
 */

// ============================================================
// Device API -- sends commands to backend
// ============================================================

const DeviceAPI = {
    dispatch(unitId, x, y) {
        return fetch('/api/amy/simulation/dispatch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ unit_id: unitId, target: { x, y } }),
        });
    },

    recall(unitId) {
        return this.sendCommand(unitId, 'recall()');
    },

    patrol(unitId, waypoints) {
        const wpStr = waypoints.map(w => `{${w.x},${w.y}}`).join(',');
        return this.sendCommand(unitId, `patrol(${wpStr})`);
    },

    fire(unitId, targetX, targetY) {
        return this.sendCommand(unitId, `fire_nerf()`);
    },

    aim(unitId, pan, tilt) {
        return this.sendCommand(unitId, `motor.aim(${pan},${tilt})`);
    },

    stop(unitId) {
        return this.sendCommand(unitId, 'stop()');
    },

    sendCommand(unitId, luaString) {
        return fetch('/api/amy/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: luaString, target_id: unitId }),
        });
    },

    sendDeviceCommand(deviceId, topicSuffix, payload) {
        return fetch(`/api/devices/${deviceId}/command`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic_suffix: topicSuffix, payload }),
        });
    },
};

// ============================================================
// Helper: escape HTML
// ============================================================

function _esc(s) {
    if (typeof s !== 'string') return String(s || '');
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function _pct(val, max) {
    if (!max || max <= 0) return 0;
    return Math.round((val / max) * 100);
}

function _healthColor(pct) {
    if (pct > 60) return '#05ffa1';
    if (pct > 30) return '#fcee0a';
    return '#ff2a6d';
}

function _batteryStr(bat) {
    if (bat === null || bat === undefined) return '--';
    return Math.round(bat * 100) + '%';
}

// ============================================================
// Built-in Device Controls
// ============================================================

const RoverControl = {
    type: 'rover',
    title: 'ROBOT CONTROL',

    render(device) {
        const hpPct = _pct(device.health, device.maxHealth);
        const hpColor = _healthColor(hpPct);
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${_esc(device.type || 'rover')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value dc-status-${device.status || 'idle'}">${(device.status || 'idle').toUpperCase()}</span></div>
                <div class="dc-stat-row"><span class="dc-label">POSITION</span><span class="dc-value">(${(device.position?.x || 0).toFixed(1)}, ${(device.position?.y || 0).toFixed(1)})</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEADING</span><span class="dc-value">${Math.round(device.heading || 0)}&deg;</span></div>
                <div class="dc-stat-row"><span class="dc-label">SPEED</span><span class="dc-value">${(device.speed || 0).toFixed(1)} m/s</span></div>
                <div class="dc-stat-row"><span class="dc-label">BATTERY</span><span class="dc-value">${_batteryStr(device.battery)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEALTH</span><span class="dc-value" style="color:${hpColor}">${Math.round(device.health || 0)}/${device.maxHealth || 0}</span></div>
                <div class="dc-health-bar"><div class="dc-health-fill" style="width:${hpPct}%;background:${hpColor}"></div></div>
            </div>
            <div class="dc-actions">
                <div class="dc-section-label">MOVEMENT</div>
                <div class="dc-btn-row">
                    <button class="dc-btn dc-btn-dispatch" data-cmd="dispatch">DISPATCH</button>
                    <button class="dc-btn dc-btn-patrol" data-cmd="patrol">PATROL</button>
                    <button class="dc-btn dc-btn-recall" data-cmd="recall">RECALL</button>
                    <button class="dc-btn dc-btn-stop" data-cmd="stop">STOP</button>
                </div>
                <div class="dc-section-label">TURRET</div>
                <div class="dc-btn-row">
                    <button class="dc-btn dc-btn-fire" data-cmd="fire">FIRE</button>
                    <button class="dc-btn dc-btn-aim" data-cmd="aim">AIM</button>
                </div>
                <div class="dc-section-label">COMMAND</div>
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input" type="text" placeholder="Lua command...">
                    <button class="dc-btn dc-btn-send" data-cmd="send">SEND</button>
                </div>
                <div class="dc-cmd-status"></div>
            </div>
        `;
    },

    bind(container, device, api) {
        // Wire button clicks
        const buttons = container.querySelectorAll ? container.querySelectorAll('.dc-btn') : [];
        for (const btn of buttons) {
            if (!btn.dataset) continue;
            const cmd = btn.dataset.cmd || btn.getAttribute('data-cmd');
            if (!cmd) continue;
            btn.addEventListener('click', () => {
                switch (cmd) {
                    case 'dispatch':
                        if (typeof EventBus !== 'undefined') {
                            EventBus.emit('device:dispatch_mode', { deviceId: device.id });
                        }
                        break;
                    case 'patrol':
                        if (typeof EventBus !== 'undefined') {
                            EventBus.emit('device:patrol_mode', { deviceId: device.id });
                        }
                        break;
                    case 'recall':
                        api.recall(device.id);
                        break;
                    case 'stop':
                        api.stop(device.id);
                        break;
                    case 'fire':
                        api.fire(device.id);
                        break;
                    case 'aim':
                        if (typeof EventBus !== 'undefined') {
                            EventBus.emit('device:aim_mode', { deviceId: device.id });
                        }
                        break;
                    case 'send': {
                        const input = container.querySelector('.dc-cmd-input');
                        const status = container.querySelector('.dc-cmd-status');
                        if (input && input.value && input.value.trim()) {
                            api.sendCommand(device.id, input.value.trim())
                                .then(r => {
                                    if (status) status.textContent = r.ok ? 'Sent' : 'Failed';
                                    if (r.ok) input.value = '';
                                })
                                .catch(() => {
                                    if (status) status.textContent = 'Error';
                                });
                        }
                        break;
                    }
                }
            });
        }

        // Enter key on input
        const input = container.querySelector('.dc-cmd-input');
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const sendBtn = container.querySelector('[data-cmd="send"]');
                    if (sendBtn && sendBtn.click) sendBtn.click();
                }
            });
        }
    },

    update(container, device) {
        // Live telemetry update — update stat values in place
    },

    destroy(container) {
        // Cleanup
    },
};

const DroneControl = {
    type: 'drone',
    title: 'DRONE CONTROL',

    render(device) {
        const hpPct = _pct(device.health, device.maxHealth);
        const hpColor = _healthColor(hpPct);
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${_esc(device.type || 'drone')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value">${(device.status || 'idle').toUpperCase()}</span></div>
                <div class="dc-stat-row"><span class="dc-label">ALTITUDE</span><span class="dc-value">${(device.altitude || 0).toFixed(1)}m</span></div>
                <div class="dc-stat-row"><span class="dc-label">POSITION</span><span class="dc-value">(${(device.position?.x || 0).toFixed(1)}, ${(device.position?.y || 0).toFixed(1)})</span></div>
                <div class="dc-stat-row"><span class="dc-label">BATTERY</span><span class="dc-value">${_batteryStr(device.battery)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEALTH</span><span class="dc-value" style="color:${hpColor}">${Math.round(device.health || 0)}/${device.maxHealth || 0}</span></div>
                <div class="dc-health-bar"><div class="dc-health-fill" style="width:${hpPct}%;background:${hpColor}"></div></div>
            </div>
            <div class="dc-actions">
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="dispatch">DISPATCH</button>
                    <button class="dc-btn" data-cmd="patrol">PATROL</button>
                    <button class="dc-btn" data-cmd="recall">RECALL</button>
                    <button class="dc-btn" data-cmd="stop">STOP</button>
                </div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="fire">FIRE</button>
                </div>
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input" type="text" placeholder="Lua command...">
                    <button class="dc-btn dc-btn-send" data-cmd="send">SEND</button>
                </div>
                <div class="dc-cmd-status"></div>
            </div>
        `;
    },

    bind: RoverControl.bind,
    update: RoverControl.update,
    destroy: RoverControl.destroy,
};

const TurretControl = {
    type: 'turret',
    title: 'TURRET CONTROL',

    render(device) {
        const hpPct = _pct(device.health, device.maxHealth);
        const hpColor = _healthColor(hpPct);
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${_esc(device.type || 'turret')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value">${(device.status || 'idle').toUpperCase()}</span></div>
                <div class="dc-stat-row"><span class="dc-label">WEAPON RANGE</span><span class="dc-value">${device.weaponRange || 0}m</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEALTH</span><span class="dc-value" style="color:${hpColor}">${Math.round(device.health || 0)}/${device.maxHealth || 0}</span></div>
                <div class="dc-health-bar"><div class="dc-health-fill" style="width:${hpPct}%;background:${hpColor}"></div></div>
            </div>
            <div class="dc-actions">
                <div class="dc-section-label">TARGETING</div>
                <div class="dc-slider-row">
                    <label class="dc-label">PAN</label>
                    <input class="dc-slider" type="range" min="-180" max="180" value="0" data-axis="pan">
                    <span class="dc-slider-val">0&deg;</span>
                </div>
                <div class="dc-slider-row">
                    <label class="dc-label">TILT</label>
                    <input class="dc-slider" type="range" min="-30" max="90" value="0" data-axis="tilt">
                    <span class="dc-slider-val">0&deg;</span>
                </div>
                <div class="dc-btn-row">
                    <button class="dc-btn dc-btn-fire" data-cmd="fire">FIRE</button>
                    <button class="dc-btn" data-cmd="stop">STOP</button>
                </div>
                <div class="dc-section-label">MODE</div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="auto">AUTO TARGET</button>
                    <button class="dc-btn" data-cmd="manual">MANUAL</button>
                </div>
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input" type="text" placeholder="Lua command...">
                    <button class="dc-btn dc-btn-send" data-cmd="send">SEND</button>
                </div>
                <div class="dc-cmd-status"></div>
            </div>
        `;
    },

    bind(container, device, api) {
        // PTZ sliders
        const sliders = container.querySelectorAll ? container.querySelectorAll('.dc-slider') : [];
        for (const slider of sliders) {
            slider.addEventListener('input', () => {
                const axis = slider.dataset.axis || slider.getAttribute('data-axis');
                const valDisplay = slider.parentElement?.querySelector('.dc-slider-val');
                if (valDisplay) valDisplay.textContent = slider.value + '\u00B0';
            });
        }

        // Buttons
        RoverControl.bind(container, device, api);
    },

    update: RoverControl.update,
    destroy: RoverControl.destroy,
};

const SensorControl = {
    type: 'sensor',
    title: 'SENSOR CONTROL',

    render(device) {
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${_esc(device.type || 'sensor')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value">${(device.status || 'idle').toUpperCase()}</span></div>
                <div class="dc-stat-row"><span class="dc-label">POSITION</span><span class="dc-value">(${(device.position?.x || 0).toFixed(1)}, ${(device.position?.y || 0).toFixed(1)})</span></div>
            </div>
            <div class="dc-actions">
                <div class="dc-section-label">CONTROL</div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="enable">ENABLE</button>
                    <button class="dc-btn" data-cmd="disable">DISABLE</button>
                    <button class="dc-btn" data-cmd="test">TEST TRIGGER</button>
                </div>
            </div>
        `;
    },

    bind(container, device, api) {
        const buttons = container.querySelectorAll ? container.querySelectorAll('.dc-btn') : [];
        for (const btn of buttons) {
            const cmd = btn.dataset?.cmd || btn.getAttribute?.('data-cmd');
            if (!cmd) continue;
            btn.addEventListener('click', () => {
                switch (cmd) {
                    case 'enable':
                        api.sendDeviceCommand(device.id, 'command', { command: 'enable' });
                        break;
                    case 'disable':
                        api.sendDeviceCommand(device.id, 'command', { command: 'disable' });
                        break;
                    case 'test':
                        api.sendDeviceCommand(device.id, 'command', { command: 'test_trigger' });
                        break;
                }
            });
        }
    },

    update(container, device) {},
    destroy(container) {},
};

const MeshRadioControl = {
    type: 'mesh_radio',
    title: 'MESH RADIO',

    render(device) {
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">PROTOCOL</span><span class="dc-value">${_esc(device.meshProtocol || 'unknown')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">BATTERY</span><span class="dc-value">${_batteryStr(device.battery)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">SNR</span><span class="dc-value">${device.snr || '--'} dB</span></div>
                <div class="dc-stat-row"><span class="dc-label">RSSI</span><span class="dc-value">${device.rssi || '--'} dBm</span></div>
                <div class="dc-stat-row"><span class="dc-label">HOPS</span><span class="dc-value">${device.hops || 0}</span></div>
            </div>
            <div class="dc-actions">
                <div class="dc-section-label">MESSAGE (${228} char max)</div>
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input dc-mesh-text" type="text" placeholder="Send text..." maxlength="228">
                    <button class="dc-btn dc-btn-send" data-cmd="send_text">SEND</button>
                </div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="center">CENTER ON MAP</button>
                </div>
            </div>
        `;
    },

    bind(container, device, api) {
        const buttons = container.querySelectorAll ? container.querySelectorAll('.dc-btn') : [];
        for (const btn of buttons) {
            const cmd = btn.dataset?.cmd || btn.getAttribute?.('data-cmd');
            if (!cmd) continue;
            btn.addEventListener('click', () => {
                switch (cmd) {
                    case 'send_text': {
                        const input = container.querySelector('.dc-mesh-text');
                        if (input && input.value && input.value.trim()) {
                            api.sendDeviceCommand(device.id, 'text', { text: input.value.trim() });
                            input.value = '';
                        }
                        break;
                    }
                    case 'center':
                        if (typeof EventBus !== 'undefined') {
                            EventBus.emit('mesh:center-on-node', { id: device.id });
                        }
                        break;
                }
            });
        }
    },

    update(container, device) {},
    destroy(container) {},
};

const CameraControl = {
    type: 'camera',
    title: 'CAMERA CONTROL',

    render(device) {
        const hasPtz = device.hasPtz || false;
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${hasPtz ? 'PTZ CAMERA' : 'FIXED CAMERA'}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value">${(device.status || 'idle').toUpperCase()}</span></div>
            </div>
            <div class="dc-actions">
                <div class="dc-section-label">STREAM</div>
                <div class="dc-stream">
                    <img class="dc-stream-img" src="/api/amy/nodes/${_esc(device.id)}/video" alt="Camera Feed" width="200" height="150">
                </div>
                ${hasPtz ? `
                <div class="dc-section-label">PTZ</div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="ptz_left">LEFT</button>
                    <button class="dc-btn" data-cmd="ptz_up">UP</button>
                    <button class="dc-btn" data-cmd="ptz_down">DOWN</button>
                    <button class="dc-btn" data-cmd="ptz_right">RIGHT</button>
                </div>
                ` : ''}
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="snapshot">SNAPSHOT</button>
                    <button class="dc-btn" data-cmd="camera_off">OFF</button>
                </div>
            </div>
        `;
    },

    bind(container, device, api) {
        const buttons = container.querySelectorAll ? container.querySelectorAll('.dc-btn') : [];
        for (const btn of buttons) {
            const cmd = btn.dataset?.cmd || btn.getAttribute?.('data-cmd');
            if (!cmd) continue;
            btn.addEventListener('click', () => {
                switch (cmd) {
                    case 'ptz_left':
                        api.sendCommand(device.id, 'motor.aim(-10,0)');
                        break;
                    case 'ptz_right':
                        api.sendCommand(device.id, 'motor.aim(10,0)');
                        break;
                    case 'ptz_up':
                        api.sendCommand(device.id, 'motor.aim(0,10)');
                        break;
                    case 'ptz_down':
                        api.sendCommand(device.id, 'motor.aim(0,-10)');
                        break;
                    case 'snapshot':
                        // Download snapshot
                        if (typeof window !== 'undefined') {
                            window.open(`/api/amy/nodes/${device.id}/snapshot`, '_blank');
                        }
                        break;
                    case 'camera_off':
                        api.sendDeviceCommand(device.id, 'command', { command: 'camera_off' });
                        break;
                }
            });
        }
    },

    update(container, device) {},
    destroy(container) {},
};

// NPC Intelligence Control (neutral pedestrians, vehicles, animals)
const NPCControl = {
    type: 'npc',
    title: 'NPC INTEL',
    _pollInterval: null,

    render(device) {
        const pos = device.position || { x: 0, y: 0 };
        const fsm = (device.fsm_state || device.fsmState || 'unknown').toUpperCase();
        const alliance = (device.alliance || 'neutral').toUpperCase();
        const assetType = (device.asset_type || device.type || 'unknown').toUpperCase();
        const hp = device.health !== undefined ? Math.round(device.health) : '--';
        const maxHp = device.max_health || device.maxHealth || 100;
        const hpPct = device.health !== undefined ? _pct(device.health, maxHp) : 0;

        // Current thought
        const thought = device.thoughtText || null;
        const emotion = device.thoughtEmotion || 'neutral';
        const emotionColor = { curious: '#00f0ff', afraid: '#fcee0a', angry: '#ff2a6d', happy: '#05ffa1', neutral: '#888888' }[emotion] || '#888888';

        // Thought history
        const history = device.thoughtHistory || [];

        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name || device.id)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${assetType}</span></div>
                <div class="dc-stat-row"><span class="dc-label">ALLIANCE</span><span class="dc-value">${alliance}</span></div>
                <div class="dc-stat-row"><span class="dc-label">FSM STATE</span><span class="dc-value">${fsm}</span></div>
                <div class="dc-stat-row"><span class="dc-label">POSITION</span><span class="dc-value">(${(pos.x || 0).toFixed(1)}, ${(pos.y || 0).toFixed(1)})</span></div>
                <div class="dc-stat-row"><span class="dc-label">SPEED</span><span class="dc-value">${(device.speed || 0).toFixed(1)} m/s</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEADING</span><span class="dc-value">${device.heading !== undefined ? Math.round(device.heading) + '\u00B0' : '--'}</span></div>
                <div class="dc-stat-row"><span class="dc-label">HEALTH</span><span class="dc-value">${hp}/${Math.round(maxHp)} (${hpPct}%)</span></div>
            </div>

            <div class="dc-section-label">CURRENT THOUGHT</div>
            <div class="dc-npc-thought">
                ${thought
                    ? `<span class="dc-npc-emotion" style="background:${emotionColor}">${_esc(emotion)}</span> <q>${_esc(thought)}</q>`
                    : '<span style="color:var(--text-ghost)">No active thought</span>'}
            </div>

            ${history.length > 0 ? `
            <div class="dc-section-label">THOUGHT HISTORY</div>
            <div class="dc-npc-history">
                ${history.slice().reverse().map(h => {
                    const c = { curious: '#00f0ff', afraid: '#fcee0a', angry: '#ff2a6d', happy: '#05ffa1', neutral: '#888888' }[h.emotion] || '#888888';
                    const ago = Math.round((Date.now() - h.time) / 1000);
                    return `<div class="dc-npc-history-item"><span class="dc-npc-emotion" style="background:${c}">${_esc(h.emotion)}</span> <q>${_esc(h.text)}</q> <span class="dc-npc-ago">${ago}s ago</span></div>`;
                }).join('')}
            </div>` : ''}

            <div class="dc-section-label" style="margin-top:8px">PERSONALITY</div>
            <div class="dc-npc-personality"></div>

            <div class="dc-section-label">BRAIN STATE</div>
            <div class="dc-npc-brain"></div>

            <div class="dc-actions">
                <div class="dc-section-label">CONTROLS</div>
                <div class="dc-btn-row">
                    <button class="dc-btn" data-cmd="take_control">TAKE CONTROL</button>
                    <button class="dc-btn" data-cmd="release_control">RELEASE</button>
                </div>
                <div class="dc-section-label" style="margin-top:6px">SET THOUGHT</div>
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input dc-npc-thought-input" type="text" placeholder="What are they thinking...">
                    <select class="dc-npc-emotion-select">
                        <option value="neutral">neutral</option>
                        <option value="curious">curious</option>
                        <option value="afraid">afraid</option>
                        <option value="angry">angry</option>
                        <option value="happy">happy</option>
                    </select>
                    <button class="dc-btn dc-btn-send" data-cmd="set_thought">SET</button>
                </div>
                <div class="dc-cmd-status"></div>
            </div>
        `;
    },

    bind(container, device, api) {
        const deviceId = device.id;

        // Fetch full detail from API
        if (typeof fetch !== 'undefined') {
            fetch(`/api/npc/${encodeURIComponent(deviceId)}`)
                .then(r => r.ok ? r.json() : null)
                .then(data => {
                    if (!data) return;
                    // Fill personality bars
                    const pEl = container.querySelector('.dc-npc-personality');
                    if (pEl && data.personality) {
                        const p = data.personality;
                        pEl.innerHTML = ['curiosity', 'caution', 'sociability', 'aggression'].map(trait => {
                            const val = Math.round((p[trait] || 0) * 100);
                            return `<div class="dc-stat-row"><span class="dc-label">${trait.toUpperCase()}</span><span class="dc-value"><span style="display:inline-block;width:60px;height:6px;background:var(--surface-3);border-radius:3px;overflow:hidden"><span style="display:block;height:100%;width:${val}%;background:var(--cyan)"></span></span> ${val}%</span></div>`;
                        }).join('');
                    }
                    // Fill brain state
                    const bEl = container.querySelector('.dc-npc-brain');
                    if (bEl && data.brain_state) {
                        const bs = data.brain_state;
                        bEl.innerHTML = `
                            <div class="dc-stat-row"><span class="dc-label">DANGER</span><span class="dc-value">${(bs.danger_level || 0).toFixed(2)}</span></div>
                            <div class="dc-stat-row"><span class="dc-label">INTEREST</span><span class="dc-value">${(bs.interest_level || 0).toFixed(2)}</span></div>
                            <div class="dc-stat-row"><span class="dc-label">BOUND</span><span class="dc-value">${bs.is_bound ? 'YES' : 'NO'}</span></div>
                        `;
                    } else if (bEl) {
                        bEl.innerHTML = '<span style="color:var(--text-ghost)">No brain attached</span>';
                    }
                })
                .catch(() => {});
        }

        // Button handlers
        const buttons = container.querySelectorAll ? container.querySelectorAll('.dc-btn') : [];
        for (const btn of buttons) {
            const cmd = btn.dataset?.cmd || btn.getAttribute?.('data-cmd');
            if (!cmd) continue;
            btn.addEventListener('click', () => {
                const status = container.querySelector('.dc-cmd-status');
                switch (cmd) {
                    case 'take_control':
                        fetch(`/api/npc/${encodeURIComponent(deviceId)}/control`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ controller_id: 'operator' }),
                        }).then(r => {
                            if (status) status.textContent = r.ok ? 'Control acquired' : 'Failed';
                        }).catch(() => { if (status) status.textContent = 'Error'; });
                        break;
                    case 'release_control':
                        fetch(`/api/npc/${encodeURIComponent(deviceId)}/control`, {
                            method: 'DELETE',
                        }).then(r => {
                            if (status) status.textContent = r.ok ? 'Released' : 'Failed';
                        }).catch(() => { if (status) status.textContent = 'Error'; });
                        break;
                    case 'set_thought': {
                        const input = container.querySelector('.dc-npc-thought-input');
                        const emotionSel = container.querySelector('.dc-npc-emotion-select');
                        const text = input && input.value ? input.value.trim() : '';
                        if (!text) return;
                        const emotion = emotionSel ? emotionSel.value : 'neutral';
                        fetch(`/api/npc/${encodeURIComponent(deviceId)}/thought`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ text, emotion, duration: 5.0 }),
                        }).then(r => {
                            if (r.ok && input) input.value = '';
                            if (status) status.textContent = r.ok ? 'Thought set' : 'Failed';
                        }).catch(() => { if (status) status.textContent = 'Error'; });
                        break;
                    }
                }
            });
        }
    },

    update(container, device) {},
    destroy(container) {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    },
};

// Fallback for unknown device types
const GenericControl = {
    type: '_generic',
    title: 'DEVICE',

    render(device) {
        return `
            <div class="dc-stats">
                <div class="dc-stat-row"><span class="dc-label">NAME</span><span class="dc-value">${_esc(device.name || device.id)}</span></div>
                <div class="dc-stat-row"><span class="dc-label">TYPE</span><span class="dc-value">${_esc(device.type || 'unknown')}</span></div>
                <div class="dc-stat-row"><span class="dc-label">STATUS</span><span class="dc-value">${(device.status || 'unknown').toUpperCase()}</span></div>
                <div class="dc-stat-row"><span class="dc-label">POSITION</span><span class="dc-value">(${(device.position?.x || 0).toFixed(1)}, ${(device.position?.y || 0).toFixed(1)})</span></div>
            </div>
            <div class="dc-actions">
                <div class="dc-cmd-row">
                    <input class="dc-cmd-input" type="text" placeholder="Lua command...">
                    <button class="dc-btn dc-btn-send" data-cmd="send">SEND</button>
                </div>
                <div class="dc-cmd-status"></div>
            </div>
        `;
    },

    bind: RoverControl.bind,
    update(container, device) {},
    destroy(container) {},
};

// ============================================================
// DeviceControlRegistry
// ============================================================

const DeviceControlRegistry = {
    _controls: new Map(),

    register(type, control) {
        this._controls.set(type, control);
    },

    get(type) {
        // Direct match
        if (this._controls.has(type)) return this._controls.get(type);

        // Alias matching
        const aliases = {
            'scout_drone': 'drone',
            'heavy_turret': 'turret',
            'missile_turret': 'turret',
            'tank': 'rover',
            'apc': 'rover',
            'swarm_drone': 'drone',
            'person': 'sensor',
            'pir': 'sensor',
            'microwave': 'sensor',
            'acoustic': 'sensor',
            'tripwire': 'sensor',
            'meshtastic': 'mesh_radio',
            'meshcore': 'mesh_radio',
            'ip_camera': 'camera',
            'ptz_camera': 'camera',
            'synthetic_camera': 'camera',
        };

        if (aliases[type] && this._controls.has(aliases[type])) {
            return this._controls.get(aliases[type]);
        }

        // Fallback: generic
        return GenericControl;
    },

    getRegisteredTypes() {
        return Array.from(this._controls.keys());
    },
};

// Register built-in controls
DeviceControlRegistry.register('rover', RoverControl);
DeviceControlRegistry.register('drone', DroneControl);
DeviceControlRegistry.register('turret', TurretControl);
DeviceControlRegistry.register('sensor', SensorControl);
DeviceControlRegistry.register('mesh_radio', MeshRadioControl);
DeviceControlRegistry.register('camera', CameraControl);
DeviceControlRegistry.register('npc', NPCControl);

// ============================================================
// DeviceModalManager
// ============================================================

const DeviceModalManager = {
    _overlay: null,
    _currentDeviceId: null,
    _currentControl: null,
    _bodyEl: null,

    open(deviceId, deviceType, deviceData) {
        // Close existing if any
        if (this._overlay) this.close();

        const control = DeviceControlRegistry.get(deviceType);
        if (!control) return;

        this._currentDeviceId = deviceId;
        this._currentControl = control;

        // Create overlay
        if (typeof document !== 'undefined') {
            this._overlay = document.createElement('div');
            this._overlay.className = 'cc-modal-overlay active';

            const modal = document.createElement('div');
            modal.className = 'cc-modal dc-modal';

            // Header
            const header = document.createElement('div');
            header.className = 'cc-modal__header';
            header.innerHTML = `
                <span class="cc-modal__title">${_esc(control.title || 'DEVICE')}: ${_esc(deviceData.name || deviceId)}</span>
                <button class="cc-modal__close">[ESC]</button>
            `;
            modal.appendChild(header);

            // Body
            this._bodyEl = document.createElement('div');
            this._bodyEl.className = 'cc-modal__body';
            this._bodyEl.innerHTML = control.render(deviceData);
            modal.appendChild(this._bodyEl);

            this._overlay.appendChild(modal);
            document.body.appendChild(this._overlay);

            // Bind controls
            control.bind(this._bodyEl, deviceData, DeviceAPI);

            // Close handlers
            const closeBtn = header.querySelector('.cc-modal__close');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => this.close());
            }

            // Click overlay to close
            this._overlay.addEventListener('click', (e) => {
                if (e.target === this._overlay) this.close();
            });

            // ESC key to close
            this._escHandler = (e) => {
                if (e.key === 'Escape') this.close();
            };
            if (typeof document !== 'undefined' && document.addEventListener) {
                document.addEventListener('keydown', this._escHandler);
            }
        } else {
            // Headless mode (tests) — just track state
            this._overlay = { className: 'active' };
        }

        // Emit event
        if (typeof EventBus !== 'undefined') {
            EventBus.emit('device:modal_opened', { deviceId, deviceType });
        }
    },

    close() {
        if (this._currentControl && this._bodyEl) {
            this._currentControl.destroy(this._bodyEl);
        }

        if (this._overlay && typeof document !== 'undefined' && document.body) {
            try {
                if (document.body.contains(this._overlay)) {
                    document.body.removeChild(this._overlay);
                }
            } catch (e) { /* ignore removal errors */ }
        }

        if (this._escHandler && typeof document !== 'undefined' && document.removeEventListener) {
            document.removeEventListener('keydown', this._escHandler);
        }

        const wasOpen = this._overlay !== null;
        this._overlay = null;
        this._currentDeviceId = null;
        this._currentControl = null;
        this._bodyEl = null;
        this._escHandler = null;

        if (wasOpen && typeof EventBus !== 'undefined') {
            EventBus.emit('device:modal_closed', {});
        }
    },

    isOpen() {
        return this._overlay !== null;
    },

    getCurrentDeviceId() {
        return this._currentDeviceId;
    },

    update(deviceData) {
        if (this._currentControl && this._bodyEl) {
            this._currentControl.update(this._bodyEl, deviceData);
        }
    },
};

// ============================================================
// Exports
// ============================================================

export { DeviceModalManager, DeviceControlRegistry, DeviceAPI };
