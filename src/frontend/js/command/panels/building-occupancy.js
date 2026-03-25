// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Building Occupancy Panel
// Shows target count per room/zone in floor plans.
// "Conference Room: 3 people, 5 devices"
// Auto-refreshes from /api/floorplans/{id}/occupancy

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const REFRESH_INTERVAL = 5000; // ms

export const BuildingOccupancyPanelDef = {
    id: 'building-occupancy',
    title: 'BUILDING OCCUPANCY',
    defaultPosition: { x: 8, y: 400 },
    defaultSize: { w: 320, h: 420 },

    render(container) {
        container.innerHTML = `
            <div class="building-occupancy-panel" style="display:flex;flex-direction:column;height:100%;font-family:'Courier New',monospace;">
                <div class="occ-controls" style="padding:6px 8px;border-bottom:1px solid #1a1a2e;display:flex;gap:8px;align-items:center;">
                    <select id="occ-plan-select" style="flex:1;background:#0e0e14;color:#00f0ff;border:1px solid #1a1a2e;padding:4px 6px;font-size:11px;font-family:inherit;">
                        <option value="">-- Select Floor Plan --</option>
                    </select>
                    <button id="occ-refresh-btn" style="background:#1a1a2e;color:#00f0ff;border:1px solid #00f0ff33;padding:4px 8px;cursor:pointer;font-size:10px;font-family:inherit;">
                        REFRESH
                    </button>
                </div>
                <div class="occ-summary" id="occ-summary" style="padding:6px 8px;border-bottom:1px solid #1a1a2e;font-size:11px;color:#888;"></div>
                <div class="occ-rooms" id="occ-rooms" style="flex:1;overflow-y:auto;padding:4px 0;"></div>
            </div>
        `;

        const planSelect = container.querySelector('#occ-plan-select');
        const refreshBtn = container.querySelector('#occ-refresh-btn');
        const summaryEl = container.querySelector('#occ-summary');
        const roomsEl = container.querySelector('#occ-rooms');

        let selectedPlanId = '';
        let refreshTimer = null;

        // Load floor plan list
        async function loadPlans() {
            try {
                const resp = await fetch('/api/floorplans');
                if (!resp.ok) return;
                const data = await resp.json();
                const plans = data.floorplans || [];

                planSelect.innerHTML = '<option value="">-- Select Floor Plan --</option>';
                plans.forEach(p => {
                    const opt = document.createElement('option');
                    opt.value = p.plan_id;
                    opt.textContent = `${_esc(p.name)} (${_esc(p.building || 'N/A')}, Floor ${p.floor_level || 0})`;
                    planSelect.appendChild(opt);
                });

                if (plans.length === 1) {
                    planSelect.value = plans[0].plan_id;
                    selectedPlanId = plans[0].plan_id;
                    loadOccupancy();
                }
            } catch (err) {
                summaryEl.textContent = 'Failed to load floor plans';
            }
        }

        // Load occupancy data
        async function loadOccupancy() {
            if (!selectedPlanId) {
                summaryEl.textContent = 'Select a floor plan above';
                roomsEl.innerHTML = '';
                return;
            }

            try {
                const resp = await fetch(`/api/floorplans/${encodeURIComponent(selectedPlanId)}/occupancy`);
                if (!resp.ok) {
                    summaryEl.textContent = 'Failed to load occupancy';
                    return;
                }
                const data = await resp.json();
                const occ = data.occupancy || {};
                renderOccupancy(occ);
            } catch (err) {
                summaryEl.textContent = 'Error: ' + err.message;
            }
        }

        function renderOccupancy(occ) {
            // Summary bar
            const building = occ.building || 'Unknown';
            const floor = occ.floor_level || 0;
            summaryEl.innerHTML = `
                <div style="display:flex;justify-content:space-between;">
                    <span style="color:#00f0ff;">${_esc(building)} &mdash; Floor ${floor}</span>
                    <span>
                        <span style="color:#05ffa1;">${occ.total_persons || 0}</span> people &middot;
                        <span style="color:#fcee0a;">${occ.total_devices || 0}</span> devices
                    </span>
                </div>
            `;

            // Room cards
            const rooms = occ.rooms || [];
            if (rooms.length === 0) {
                roomsEl.innerHTML = '<div style="padding:12px 8px;color:#555;font-size:11px;">No rooms defined in this floor plan</div>';
                return;
            }

            roomsEl.innerHTML = rooms.map(room => {
                const ratio = room.capacity ? (room.person_count / room.capacity) : null;
                let ratioColor = '#555';
                let ratioText = '';
                if (ratio !== null) {
                    if (ratio >= 1.0) {
                        ratioColor = '#ff2a6d';
                        ratioText = 'FULL';
                    } else if (ratio >= 0.75) {
                        ratioColor = '#fcee0a';
                        ratioText = `${Math.round(ratio * 100)}%`;
                    } else {
                        ratioColor = '#05ffa1';
                        ratioText = `${Math.round(ratio * 100)}%`;
                    }
                }

                const typeIcon = getRoomTypeIcon(room.room_type);
                const total = room.person_count + room.device_count;

                return `
                    <div class="occ-room-card" style="
                        margin:2px 8px;padding:8px 10px;
                        background:#0e0e14;border:1px solid #1a1a2e;
                        border-left:3px solid ${total > 0 ? '#00f0ff' : '#1a1a2e'};
                        font-size:11px;
                    ">
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <span style="color:${total > 0 ? '#00f0ff' : '#555'};">
                                ${typeIcon} ${_esc(room.room_name)}
                            </span>
                            ${ratioText ? `<span style="color:${ratioColor};font-size:10px;">${ratioText}</span>` : ''}
                        </div>
                        <div style="margin-top:4px;color:#888;">
                            <span style="color:#05ffa1;">${room.person_count}</span> people &middot;
                            <span style="color:#fcee0a;">${room.device_count}</span> devices
                            ${room.capacity ? ` &middot; cap: ${room.capacity}` : ''}
                        </div>
                        ${room.target_ids && room.target_ids.length > 0 ? `
                            <div style="margin-top:3px;font-size:9px;color:#444;word-break:break-all;">
                                ${room.target_ids.slice(0, 5).map(t => _esc(t)).join(', ')}
                                ${room.target_ids.length > 5 ? ` +${room.target_ids.length - 5} more` : ''}
                            </div>
                        ` : ''}
                    </div>
                `;
            }).join('');
        }

        function getRoomTypeIcon(type) {
            const icons = {
                office: '[OFC]',
                conference: '[CNF]',
                hallway: '[HWY]',
                bathroom: '[BTH]',
                kitchen: '[KIT]',
                lobby: '[LBY]',
                storage: '[STR]',
                server_room: '[SRV]',
                stairwell: '[STW]',
                elevator: '[ELV]',
                open_area: '[OPN]',
                restricted: '[RST]',
            };
            return icons[type] || '[---]';
        }

        // Event handlers
        planSelect.addEventListener('change', () => {
            selectedPlanId = planSelect.value;
            loadOccupancy();
        });

        refreshBtn.addEventListener('click', loadOccupancy);

        // Auto-refresh
        refreshTimer = setInterval(() => {
            if (selectedPlanId) loadOccupancy();
        }, REFRESH_INTERVAL);

        // Listen for localization events via WebSocket
        EventBus.on('floorplan.target_localized', () => {
            if (selectedPlanId) loadOccupancy();
        });

        // Initial load
        loadPlans();

        // Cleanup
        return () => {
            if (refreshTimer) clearInterval(refreshTimer);
        };
    }
};
