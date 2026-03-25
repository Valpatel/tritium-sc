// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * Simulation Modes tab — the launcher for all simulation types.
 *
 * This replaces the old "Game" concept. Simulation modes include:
 * - CITY SIM: Living city with traffic, NPCs, daily routines
 * - BATTLE: 10-wave combat exercise with projectile physics
 * - PROTEST/RIOT: Civil unrest scenario (Epstein model)
 * - CUSTOM: LLM-generated scenarios or user-defined
 *
 * Each mode configures the simulation engine differently.
 * Protest/riot is a sub-mode of city sim, not a separate system.
 */

import { EventBus } from '../../events.js';

EventBus.emit('panel:register-tab', {
    container: 'simulation-container',
    id: 'modes-tab',
    title: 'MODES',
    create(el) {
        el.innerHTML = `
            <div style="padding:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:#ccc">
                <div style="color:#00f0ff;margin-bottom:10px;font-size:12px">SIMULATION MODES</div>

                <div class="sm-mode" data-mode="city-sim">
                    <div class="sm-mode-title">CITY SIM</div>
                    <div class="sm-mode-desc">Living city — traffic, NPCs, daily routines, events</div>
                    <div class="sm-mode-actions">
                        <button class="sm-btn" data-action="start-city">START</button>
                        <button class="sm-btn sm-sub" data-action="dramatic-day">DRAMATIC DAY</button>
                    </div>
                </div>

                <div class="sm-mode" data-mode="battle">
                    <div class="sm-mode-title" style="color:#ff2a6d">BATTLE</div>
                    <div class="sm-mode-desc">10-wave combat exercise — hostiles, projectiles, kill streaks</div>
                    <div class="sm-mode-actions">
                        <button class="sm-btn" style="color:#ff2a6d;border-color:#ff2a6d" data-action="start-battle">START BATTLE</button>
                    </div>
                </div>

                <div class="sm-mode" data-mode="protest">
                    <div class="sm-mode-title" style="color:#ff8844">PROTEST / RIOT</div>
                    <div class="sm-mode-desc">Civil unrest — Epstein model, 8 escalation phases, police response</div>
                    <div class="sm-mode-actions">
                        <button class="sm-btn" style="color:#ff8844;border-color:#ff8844" data-action="start-protest">TRIGGER PROTEST</button>
                    </div>
                    <div class="sm-mode-note">Requires City Sim running. Protest is a city sim event.</div>
                </div>

                <div class="sm-mode" data-mode="custom">
                    <div class="sm-mode-title" style="color:#05ffa1">CUSTOM SCENARIO</div>
                    <div class="sm-mode-desc">Load a saved scenario or generate one with LLM</div>
                    <div class="sm-mode-actions">
                        <select class="sm-select" data-bind="scenario-select">
                            <option value="">-- Select Scenario --</option>
                        </select>
                        <button class="sm-btn" style="color:#05ffa1;border-color:#05ffa1" data-action="load-scenario">LOAD</button>
                    </div>
                </div>
            </div>
            <style>
                .sm-mode{background:#0d0d1a;border:1px solid #1a1a2e;border-radius:3px;padding:8px;margin-bottom:8px}
                .sm-mode-title{color:#00f0ff;font-size:11px;margin-bottom:4px}
                .sm-mode-desc{color:#555;font-size:10px;margin-bottom:6px}
                .sm-mode-note{color:#333;font-size:9px;margin-top:4px;font-style:italic}
                .sm-mode-actions{display:flex;gap:4px;align-items:center}
                .sm-btn{background:#0a0a12;border:1px solid #00f0ff;color:#00f0ff;padding:3px 10px;font-family:inherit;font-size:10px;cursor:pointer;border-radius:2px}
                .sm-btn:hover{filter:brightness(1.3)}
                .sm-btn.sm-sub{color:#888;border-color:#333}
                .sm-select{background:#0a0a12;border:1px solid #1a1a2e;color:#ccc;padding:2px 6px;font-family:inherit;font-size:10px;flex:1}
            </style>
        `;

        // Wire buttons
        el.querySelector('[data-action="start-city"]').addEventListener('click', () => {
            EventBus.emit('city-sim:toggle');
        });
        el.querySelector('[data-action="dramatic-day"]').addEventListener('click', () => {
            EventBus.emit('city-sim:load-scenario', 'dramatic_day');
        });
        el.querySelector('[data-action="start-battle"]').addEventListener('click', () => {
            EventBus.emit('game:start');
        });
        el.querySelector('[data-action="start-protest"]').addEventListener('click', () => {
            EventBus.emit('city-sim:start-protest', {
                plazaCenter: { x: 0, z: 0 },
                participantCount: 50,
                legitimacy: 0.25,
            });
        });
        el.querySelector('[data-action="load-scenario"]').addEventListener('click', () => {
            const select = el.querySelector('[data-bind="scenario-select"]');
            if (select.value) EventBus.emit('city-sim:load-scenario', select.value);
        });

        // Populate scenario dropdown
        fetch('/api/city-sim/scenarios').then(r => r.json()).then(d => {
            const select = el.querySelector('[data-bind="scenario-select"]');
            for (const s of (d.scenarios || [])) {
                const opt = document.createElement('option');
                opt.value = s.id;
                opt.textContent = `${s.name} (${s.vehicles || '?'} cars)`;
                select.appendChild(opt);
            }
        }).catch(() => {});
    },
});
