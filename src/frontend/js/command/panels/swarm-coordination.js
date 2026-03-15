// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// SPDX-License-Identifier: AGPL-3.0

/**
 * Swarm Coordination Panel — visualize and control multi-robot formations.
 *
 * Shows formation shapes (line, wedge, circle, diamond) with unit positions
 * and formation center. Animates unit movement along patrol routes.
 * Integrates with the map via overlay rendering.
 */

const FORMATION_COLORS = {
    line: '#00f0ff',
    wedge: '#ff2a6d',
    circle: '#05ffa1',
    diamond: '#fcee0a',
    column: '#00f0ff',
    staggered: '#ff2a6d',
};

const MEMBER_RADIUS = 6;
const CENTER_RADIUS = 4;

export const SwarmCoordinationPanelDef = {
    id: 'swarm-coordination',
    title: 'SWARM COORDINATION',
    defaultPosition: { x: 300, y: 80 },
    defaultSize: { w: 440, h: 460 },

    create(panel) {
        const el = document.createElement('div');
        el.innerHTML = `
            <div style="display:flex;flex-direction:column;gap:8px;padding:8px;">
                <div style="display:flex;gap:4px;align-items:center;">
                    <button class="panel-action-btn panel-action-btn-primary" data-action="create" style="font-size:0.42rem">+ NEW</button>
                    <button class="panel-action-btn" data-action="refresh" style="font-size:0.42rem">REFRESH</button>
                </div>
                <div data-bind="swarm-list" style="max-height:120px;overflow-y:auto;"></div>
                <canvas data-bind="canvas" width="400" height="250"
                    style="background:#0a0a0f;border:1px solid #1a1a2e;border-radius:4px;width:100%;"></canvas>
                <div style="display:flex;gap:4px;flex-wrap:wrap;">
                    <button class="panel-action-btn" data-cmd="hold" style="font-size:0.42rem">HOLD</button>
                    <button class="panel-action-btn" data-cmd="advance" style="font-size:0.42rem">ADVANCE</button>
                    <button class="panel-action-btn" data-cmd="patrol" style="font-size:0.42rem">PATROL</button>
                    <button class="panel-action-btn" data-cmd="spread" style="font-size:0.42rem">SPREAD</button>
                    <button class="panel-action-btn" data-cmd="converge" style="font-size:0.42rem">CONVERGE</button>
                    <select data-bind="formation-select" style="background:#12121a;color:#00f0ff;border:1px solid #1a1a2e;padding:2px 4px;font-size:11px;">
                        <option value="line">LINE</option>
                        <option value="wedge">WEDGE</option>
                        <option value="circle">CIRCLE</option>
                        <option value="diamond">DIAMOND</option>
                        <option value="column">COLUMN</option>
                    </select>
                </div>
            </div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        let swarms = [];
        let selectedSwarmId = null;
        const canvasEl = bodyEl.querySelector('[data-bind="canvas"]');
        const ctx = canvasEl ? canvasEl.getContext('2d') : null;
        const listEl = bodyEl.querySelector('[data-bind="swarm-list"]');

        async function fetchSwarms() {
            try {
                const resp = await fetch('/api/swarm/swarms');
                if (!resp.ok) return;
                const data = await resp.json();
                swarms = data.swarms || [];
            } catch (e) {
                console.warn('Swarm fetch error:', e);
            }
        }

        async function createSwarm(name, formation, spacing) {
            try {
                await fetch('/api/swarm/swarms', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, formation, spacing }),
                });
                await fetchSwarms();
                render();
            } catch (e) { console.warn('Swarm create error:', e); }
        }

        async function issueCommand(swarmId, command, waypoints, formation) {
            try {
                const body = { command };
                if (waypoints) body.waypoints = waypoints;
                if (formation) body.formation = formation;
                await fetch(`/api/swarm/swarms/${swarmId}/command`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                await fetchSwarms();
                render();
            } catch (e) { console.warn('Swarm command error:', e); }
        }

        function drawFormation(swarm) {
            if (!ctx || !canvasEl) return;
            const color = FORMATION_COLORS[swarm.formation_type] || '#00f0ff';
            const members = swarm.members || [];
            const cx = canvasEl.width / 2;
            const cy = canvasEl.height / 2;
            const scale = 8;

            ctx.strokeStyle = color;
            ctx.lineWidth = 1;
            ctx.globalAlpha = 0.3;

            if (swarm.formation_type === 'circle' && members.length > 2) {
                const radius = swarm.spacing * Math.max(1, members.length) / (2 * Math.PI) * scale;
                ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.stroke();
            } else if (swarm.formation_type === 'diamond' && members.length >= 4) {
                const s = swarm.spacing * scale;
                ctx.beginPath(); ctx.moveTo(cx, cy - s); ctx.lineTo(cx + s, cy); ctx.lineTo(cx, cy + s); ctx.lineTo(cx - s, cy); ctx.closePath(); ctx.stroke();
            }

            ctx.globalAlpha = 1.0;
            ctx.fillStyle = '#ffffff';
            ctx.beginPath(); ctx.arc(cx, cy, CENTER_RADIUS, 0, Math.PI * 2); ctx.fill();

            const headRad = (swarm.heading || 0) * Math.PI / 180;
            ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx + Math.cos(headRad) * 20, cy - Math.sin(headRad) * 20); ctx.stroke();

            members.forEach((member) => {
                const dx = (member.position_x - swarm.center_x) * scale;
                const dy = -(member.position_y - swarm.center_y) * scale;
                const mx = cx + dx, my = cy + dy;
                const memberColor = member.status === 'active' ? color : member.status === 'disabled' ? '#666' : '#ff6600';
                ctx.fillStyle = memberColor; ctx.beginPath(); ctx.arc(mx, my, MEMBER_RADIUS, 0, Math.PI * 2); ctx.fill();
                ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1; ctx.stroke();
                ctx.fillStyle = '#cccccc'; ctx.font = '9px monospace'; ctx.textAlign = 'center';
                ctx.fillText(member.role || 'unit', mx, my + MEMBER_RADIUS + 12);
                const icon = member.asset_type === 'drone' ? 'D' : member.asset_type === 'turret' ? 'T' : 'R';
                ctx.fillStyle = '#000000'; ctx.font = 'bold 8px monospace'; ctx.fillText(icon, mx, my + 3);
            });

            const waypoints = swarm.waypoints || [];
            if (waypoints.length > 0) {
                ctx.strokeStyle = '#fcee0a'; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
                ctx.beginPath(); ctx.moveTo(cx, cy);
                waypoints.forEach(wp => { ctx.lineTo(cx + (wp[0] - swarm.center_x) * scale, cy - (wp[1] - swarm.center_y) * scale); });
                ctx.stroke(); ctx.setLineDash([]);
                waypoints.forEach((wp, i) => {
                    const wpx = cx + (wp[0] - swarm.center_x) * scale;
                    const wpy = cy - (wp[1] - swarm.center_y) * scale;
                    ctx.fillStyle = i === swarm.current_waypoint_idx ? '#fcee0a' : '#666';
                    ctx.beginPath(); ctx.arc(wpx, wpy, 3, 0, Math.PI * 2); ctx.fill();
                });
            }
        }

        function renderCanvas() {
            if (!ctx || !canvasEl) return;
            ctx.clearRect(0, 0, canvasEl.width, canvasEl.height);
            ctx.strokeStyle = '#1a1a2e'; ctx.lineWidth = 1;
            for (let x = 0; x < canvasEl.width; x += 20) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvasEl.height); ctx.stroke(); }
            for (let y = 0; y < canvasEl.height; y += 20) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvasEl.width, y); ctx.stroke(); }
            const swarm = selectedSwarmId ? swarms.find(s => s.swarm_id === selectedSwarmId) : swarms[0];
            if (swarm) drawFormation(swarm);
            else { ctx.fillStyle = '#666'; ctx.font = '12px monospace'; ctx.textAlign = 'center'; ctx.fillText('No swarms configured', canvasEl.width / 2, canvasEl.height / 2); }
        }

        function buildSwarmList() {
            if (!listEl) return;
            if (swarms.length === 0) { listEl.innerHTML = '<div style="color:#555;padding:8px;text-align:center;">No swarms. Create one to begin.</div>'; return; }
            listEl.innerHTML = swarms.map(s => `
                <div class="swarm-item" data-swarm-id="${s.swarm_id}" style="padding:4px 8px;margin:2px 0;cursor:pointer;border:1px solid ${s.swarm_id === selectedSwarmId ? '#00f0ff' : '#1a1a2e'};border-radius:3px;background:${s.swarm_id === selectedSwarmId ? 'rgba(0,240,255,0.05)' : 'transparent'};">
                    <div style="display:flex;justify-content:space-between;">
                        <span style="color:#ccc;font-size:12px;">${s.name}</span>
                        <span style="color:${FORMATION_COLORS[s.formation_type] || '#00f0ff'};font-size:11px;">${s.formation_type.toUpperCase()}</span>
                    </div>
                    <div style="color:#888;font-size:10px;">${s.active_members}/${s.member_count} units | CMD: ${s.command}</div>
                </div>
            `).join('');
            listEl.querySelectorAll('.swarm-item').forEach(el => {
                el.addEventListener('click', () => { selectedSwarmId = el.dataset.swarmId; render(); });
            });
        }

        function render() { buildSwarmList(); renderCanvas(); }

        bodyEl.addEventListener('click', (e) => {
            const action = e.target.dataset?.action;
            const cmd = e.target.dataset?.cmd;
            if (action === 'create') {
                const name = prompt('Swarm name:', 'Alpha Squad');
                if (name) createSwarm(name, 'line', 5.0);
            } else if (action === 'refresh') {
                fetchSwarms().then(render);
            } else if (cmd && selectedSwarmId) {
                issueCommand(selectedSwarmId, cmd);
            }
        });

        const formSelect = bodyEl.querySelector('[data-bind="formation-select"]');
        if (formSelect) {
            formSelect.addEventListener('change', (e) => {
                if (selectedSwarmId) issueCommand(selectedSwarmId, null, null, e.target.value);
            });
        }

        fetchSwarms().then(() => {
            if (swarms.length > 0 && !selectedSwarmId) selectedSwarmId = swarms[0].swarm_id;
            render();
        });

        panel._swarmTimer = setInterval(() => { fetchSwarms().then(render); }, 2000);
    },

    unmount(bodyEl, panel) {
        if (panel._swarmTimer) { clearInterval(panel._swarmTimer); panel._swarmTimer = null; }
    },
};
