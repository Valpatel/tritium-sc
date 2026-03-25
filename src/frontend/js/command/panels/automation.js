// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Automation Rules Panel — CRUD for if-then automation rules.
// Backend API: /api/automation/rules (GET/POST/PUT/DELETE)
// Supports triggers, conditions (9 operators), and actions (6 types).

import { EventBus } from '/lib/events.js';
import { _esc } from '/lib/utils.js';

const TRIGGER_EXAMPLES = [
    'ble:new_device', 'ble:suspicious_device', 'ble:*',
    'geofence:enter', 'geofence:exit', 'geofence:*',
    'rf_motion:detected', 'camera:detection', '*',
];

const OPERATORS = [
    { value: 'eq', label: '==' },
    { value: 'neq', label: '!=' },
    { value: 'gt', label: '>' },
    { value: 'lt', label: '<' },
    { value: 'gte', label: '>=' },
    { value: 'lte', label: '<=' },
    { value: 'contains', label: 'contains' },
    { value: 'regex', label: 'regex' },
    { value: 'exists', label: 'exists' },
];

const ACTION_TYPES = [
    { value: 'alert', label: 'Alert' },
    { value: 'command', label: 'Command' },
    { value: 'tag', label: 'Tag' },
    { value: 'escalate', label: 'Escalate' },
    { value: 'notify', label: 'Notify' },
    { value: 'log', label: 'Log' },
];

export const AutomationPanelDef = {
    id: 'automation',
    title: 'AUTOMATION',
    defaultPosition: { x: 8, y: 400 },
    defaultSize: { w: 340, h: 480 },

    create(panel) {
        const el = document.createElement('div');
        el.className = 'automation-panel-inner';
        el.innerHTML = `
            <div class="auto-toolbar">
                <button class="panel-action-btn panel-action-btn-primary" data-action="refresh">REFRESH</button>
                <button class="panel-action-btn" data-action="new-rule">+ NEW RULE</button>
            </div>
            <div class="auto-stats" data-bind="stats" style="font-size:0.45rem;color:var(--text-ghost);padding:2px 4px"></div>
            <ul class="panel-list auto-rule-list" data-bind="rule-list" role="listbox" aria-label="Automation rules">
                <li class="panel-empty">Loading rules...</li>
            </ul>
            <div class="auto-editor" data-bind="editor" style="display:none"></div>
        `;
        return el;
    },

    mount(bodyEl, panel) {
        const ruleListEl = bodyEl.querySelector('[data-bind="rule-list"]');
        const editorEl = bodyEl.querySelector('[data-bind="editor"]');
        const statsEl = bodyEl.querySelector('[data-bind="stats"]');
        const refreshBtn = bodyEl.querySelector('[data-action="refresh"]');
        const newRuleBtn = bodyEl.querySelector('[data-action="new-rule"]');

        let rules = [];
        let editingRule = null; // null = list view, object = editing

        function renderStats() {
            if (!statsEl) return;
            const enabled = rules.filter(r => r.enabled).length;
            const total = rules.length;
            const totalFired = rules.reduce((s, r) => s + (r.fire_count || 0), 0);
            statsEl.textContent = `${enabled}/${total} enabled | ${totalFired} total fires`;
        }

        function renderRules() {
            if (!ruleListEl) return;
            if (rules.length === 0) {
                ruleListEl.innerHTML = '<li class="panel-empty">No automation rules defined</li>';
                renderStats();
                return;
            }

            ruleListEl.innerHTML = rules.map(r => {
                const dot = r.enabled ? '#05ffa1' : '#666';
                const condCount = (r.conditions || []).length;
                const actCount = (r.actions || []).length;
                const lastFired = r.last_fired > 0
                    ? new Date(r.last_fired * 1000).toLocaleTimeString().substring(0, 8)
                    : 'never';
                return `<li class="panel-list-item auto-rule-item" data-rule-id="${_esc(r.rule_id)}" role="option">
                    <span class="panel-dot" style="background:${dot}"></span>
                    <span style="flex:1;min-width:0">
                        <span style="color:var(--text-main)">${_esc(r.name || 'Unnamed')}</span><br>
                        <span class="mono" style="font-size:0.42rem;color:var(--text-ghost)">
                            ${_esc(r.trigger)} | ${condCount} cond | ${actCount} act | fired ${r.fire_count || 0}x (${lastFired})
                        </span>
                    </span>
                    <button class="panel-btn" data-action="toggle" data-rule-id="${_esc(r.rule_id)}" title="${r.enabled ? 'Disable' : 'Enable'}" style="font-size:0.45rem;padding:1px 4px">${r.enabled ? 'ON' : 'OFF'}</button>
                    <button class="panel-btn" data-action="edit" data-rule-id="${_esc(r.rule_id)}" title="Edit rule" style="font-size:0.45rem;padding:1px 4px">EDIT</button>
                    <button class="panel-btn" data-action="delete" data-rule-id="${_esc(r.rule_id)}" title="Delete rule" style="font-size:0.45rem;padding:1px 4px">&times;</button>
                </li>`;
            }).join('');

            // Wire handlers
            ruleListEl.querySelectorAll('[data-action="toggle"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    toggleRule(btn.dataset.ruleId);
                });
            });
            ruleListEl.querySelectorAll('[data-action="edit"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const rule = rules.find(r => r.rule_id === btn.dataset.ruleId);
                    if (rule) openEditor(rule);
                });
            });
            ruleListEl.querySelectorAll('[data-action="delete"]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    deleteRule(btn.dataset.ruleId);
                });
            });

            renderStats();
        }

        function openEditor(rule) {
            editingRule = rule ? { ...rule } : {
                name: '',
                trigger: '',
                conditions: [],
                actions: [],
                enabled: true,
                cooldown_seconds: 0,
                description: '',
            };
            ruleListEl.style.display = 'none';
            editorEl.style.display = '';
            renderEditor();
        }

        function closeEditor() {
            editingRule = null;
            editorEl.style.display = 'none';
            ruleListEl.style.display = '';
        }

        function renderEditor() {
            if (!editorEl || !editingRule) return;
            const r = editingRule;
            const isNew = !r.rule_id;
            const triggerOptions = TRIGGER_EXAMPLES.map(t =>
                `<option value="${_esc(t)}"${t === r.trigger ? ' selected' : ''}>${_esc(t)}</option>`
            ).join('');

            let conditionsHtml = (r.conditions || []).map((c, i) => {
                const opOptions = OPERATORS.map(o =>
                    `<option value="${o.value}"${o.value === c.operator ? ' selected' : ''}>${o.label}</option>`
                ).join('');
                return `<div class="auto-condition-row" data-idx="${i}">
                    <input type="text" class="auto-input" data-field="cond-field-${i}" value="${_esc(c.field)}" placeholder="field" style="width:70px">
                    <select class="auto-input" data-field="cond-op-${i}">${opOptions}</select>
                    <input type="text" class="auto-input" data-field="cond-val-${i}" value="${_esc(c.value != null ? String(c.value) : '')}" placeholder="value" style="width:60px">
                    <button class="panel-btn" data-action="rm-cond" data-idx="${i}" style="font-size:0.45rem">&times;</button>
                </div>`;
            }).join('');

            let actionsHtml = (r.actions || []).map((a, i) => {
                const typeOptions = ACTION_TYPES.map(t =>
                    `<option value="${t.value}"${t.value === a.action_type ? ' selected' : ''}>${t.label}</option>`
                ).join('');
                const paramsStr = JSON.stringify(a.params || {});
                return `<div class="auto-action-row" data-idx="${i}">
                    <select class="auto-input" data-field="act-type-${i}">${typeOptions}</select>
                    <input type="text" class="auto-input" data-field="act-params-${i}" value='${_esc(paramsStr)}' placeholder='{"key":"val"}' style="flex:1">
                    <button class="panel-btn" data-action="rm-act" data-idx="${i}" style="font-size:0.45rem">&times;</button>
                </div>`;
            }).join('');

            editorEl.innerHTML = `
                <div style="padding:4px;font-size:0.5rem">
                    <div class="auto-form-row">
                        <label>Name</label>
                        <input type="text" class="auto-input" data-field="name" value="${_esc(r.name)}" placeholder="Rule name">
                    </div>
                    <div class="auto-form-row">
                        <label>Trigger</label>
                        <input type="text" class="auto-input" data-field="trigger" value="${_esc(r.trigger)}" placeholder="e.g. ble:new_device" list="auto-trigger-list">
                        <datalist id="auto-trigger-list">${triggerOptions}</datalist>
                    </div>
                    <div class="auto-form-row">
                        <label>Description</label>
                        <input type="text" class="auto-input" data-field="description" value="${_esc(r.description)}" placeholder="What does this rule do?">
                    </div>
                    <div class="auto-form-row">
                        <label>Cooldown (s)</label>
                        <input type="number" class="auto-input" data-field="cooldown" value="${r.cooldown_seconds || 0}" min="0" step="1" style="width:60px">
                    </div>
                    <div class="auto-form-row">
                        <label style="display:flex;align-items:center;gap:4px">
                            <input type="checkbox" data-field="enabled" ${r.enabled ? 'checked' : ''}> Enabled
                        </label>
                    </div>
                    <div class="panel-section-label" style="margin-top:6px">CONDITIONS</div>
                    <div class="auto-conditions">${conditionsHtml || '<div class="panel-empty" style="font-size:0.42rem">No conditions (always matches)</div>'}</div>
                    <button class="panel-action-btn" data-action="add-cond" style="font-size:0.42rem;margin:2px 0">+ CONDITION</button>

                    <div class="panel-section-label" style="margin-top:6px">ACTIONS</div>
                    <div class="auto-actions">${actionsHtml || '<div class="panel-empty" style="font-size:0.42rem">No actions</div>'}</div>
                    <button class="panel-action-btn" data-action="add-act" style="font-size:0.42rem;margin:2px 0">+ ACTION</button>

                    <div style="display:flex;gap:4px;margin-top:8px">
                        <button class="panel-action-btn panel-action-btn-primary" data-action="save">${isNew ? 'CREATE' : 'SAVE'}</button>
                        <button class="panel-action-btn" data-action="cancel">CANCEL</button>
                        ${!isNew ? `<button class="panel-action-btn" data-action="test-rule">TEST</button>` : ''}
                    </div>
                </div>
            `;

            // Wire editor events
            editorEl.querySelector('[data-action="cancel"]')?.addEventListener('click', closeEditor);
            editorEl.querySelector('[data-action="save"]')?.addEventListener('click', () => saveRule());
            editorEl.querySelector('[data-action="test-rule"]')?.addEventListener('click', () => testRule());
            editorEl.querySelector('[data-action="add-cond"]')?.addEventListener('click', () => {
                editingRule.conditions = editingRule.conditions || [];
                editingRule.conditions.push({ field: '', operator: 'eq', value: '' });
                renderEditor();
            });
            editorEl.querySelector('[data-action="add-act"]')?.addEventListener('click', () => {
                editingRule.actions = editingRule.actions || [];
                editingRule.actions.push({ action_type: 'alert', params: {} });
                renderEditor();
            });
            editorEl.querySelectorAll('[data-action="rm-cond"]').forEach(btn => {
                btn.addEventListener('click', () => {
                    editingRule.conditions.splice(parseInt(btn.dataset.idx), 1);
                    renderEditor();
                });
            });
            editorEl.querySelectorAll('[data-action="rm-act"]').forEach(btn => {
                btn.addEventListener('click', () => {
                    editingRule.actions.splice(parseInt(btn.dataset.idx), 1);
                    renderEditor();
                });
            });
        }

        function collectEditorData() {
            if (!editingRule) return null;
            const r = editingRule;
            r.name = editorEl.querySelector('[data-field="name"]')?.value || '';
            r.trigger = editorEl.querySelector('[data-field="trigger"]')?.value || '';
            r.description = editorEl.querySelector('[data-field="description"]')?.value || '';
            r.cooldown_seconds = parseFloat(editorEl.querySelector('[data-field="cooldown"]')?.value || '0');
            r.enabled = editorEl.querySelector('[data-field="enabled"]')?.checked ?? true;

            // Collect conditions
            r.conditions = [];
            const condCount = editorEl.querySelectorAll('.auto-condition-row').length;
            for (let i = 0; i < condCount; i++) {
                const field = editorEl.querySelector(`[data-field="cond-field-${i}"]`)?.value || '';
                const operator = editorEl.querySelector(`[data-field="cond-op-${i}"]`)?.value || 'eq';
                const value = editorEl.querySelector(`[data-field="cond-val-${i}"]`)?.value || '';
                if (field) r.conditions.push({ field, operator, value });
            }

            // Collect actions
            r.actions = [];
            const actCount = editorEl.querySelectorAll('.auto-action-row').length;
            for (let i = 0; i < actCount; i++) {
                const action_type = editorEl.querySelector(`[data-field="act-type-${i}"]`)?.value || 'alert';
                const paramsStr = editorEl.querySelector(`[data-field="act-params-${i}"]`)?.value || '{}';
                let params = {};
                try { params = JSON.parse(paramsStr); } catch (_) { /* keep empty */ }
                r.actions.push({ action_type, params });
            }

            return r;
        }

        async function saveRule() {
            const r = collectEditorData();
            if (!r) return;
            if (!r.name) {
                EventBus.emit('toast:show', { message: 'Rule name is required', type: 'alert' });
                return;
            }

            const isNew = !r.rule_id;
            const url = isNew ? '/api/automation/rules' : `/api/automation/rules/${r.rule_id}`;
            const method = isNew ? 'POST' : 'PUT';

            try {
                const resp = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: r.name,
                        trigger: r.trigger,
                        conditions: r.conditions,
                        actions: r.actions,
                        enabled: r.enabled,
                        cooldown_seconds: r.cooldown_seconds,
                        description: r.description,
                    }),
                });
                if (resp.ok) {
                    EventBus.emit('toast:show', { message: `Rule ${isNew ? 'created' : 'updated'}`, type: 'info' });
                    closeEditor();
                    fetchRules();
                } else {
                    const err = await resp.json().catch(() => ({}));
                    EventBus.emit('toast:show', { message: `Failed: ${err.detail || resp.statusText}`, type: 'alert' });
                }
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Network error saving rule', type: 'alert' });
            }
        }

        async function testRule() {
            const r = collectEditorData();
            if (!r || !r.rule_id) return;
            try {
                const resp = await fetch(`/api/automation/rules/${r.rule_id}/test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ event_type: r.trigger, data: {} }),
                });
                const result = await resp.json();
                const msg = result.matched
                    ? `Rule MATCHED (${result.executed ? 'executed' : 'dry-run'})`
                    : `Rule did NOT match: ${result.reason || 'no match'}`;
                EventBus.emit('toast:show', { message: msg, type: result.matched ? 'info' : 'alert' });
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Test failed', type: 'alert' });
            }
        }

        async function toggleRule(ruleId) {
            const rule = rules.find(r => r.rule_id === ruleId);
            if (!rule) return;
            const action = rule.enabled ? 'disable' : 'enable';
            try {
                await fetch(`/api/automation/rules/${ruleId}/${action}`, { method: 'POST' });
                fetchRules();
            } catch (_) {
                EventBus.emit('toast:show', { message: `Failed to ${action} rule`, type: 'alert' });
            }
        }

        async function deleteRule(ruleId) {
            try {
                await fetch(`/api/automation/rules/${ruleId}`, { method: 'DELETE' });
                EventBus.emit('toast:show', { message: 'Rule deleted', type: 'info' });
                fetchRules();
            } catch (_) {
                EventBus.emit('toast:show', { message: 'Failed to delete rule', type: 'alert' });
            }
        }

        async function fetchRules() {
            try {
                const resp = await fetch('/api/automation/rules');
                if (!resp.ok) { rules = []; renderRules(); return; }
                const data = await resp.json();
                rules = data.rules || [];
                renderRules();
            } catch (_) {
                rules = [];
                renderRules();
            }
        }

        if (refreshBtn) refreshBtn.addEventListener('click', fetchRules);
        if (newRuleBtn) newRuleBtn.addEventListener('click', () => openEditor(null));

        const refreshInterval = setInterval(fetchRules, 30000);
        panel._unsubs.push(() => clearInterval(refreshInterval));

        fetchRules();
    },

    unmount(bodyEl) {
        // _unsubs cleaned up by Panel base class
    },
};
