// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
// Tests for federation panel definition

import { describe, it, expect, vi, beforeEach } from 'vitest';

// Stub browser globals
globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || {
    createElement: (tag) => {
        const el = {
            tagName: tag,
            className: '', style: {}, innerHTML: '', textContent: '',
            children: [],
            addEventListener: vi.fn(),
            querySelector: (sel) => {
                // Simple stub that returns a mock element
                return { textContent: '', value: '', style: { display: '' } };
            },
            querySelectorAll: () => [],
            appendChild: vi.fn(),
            dataset: {},
        };
        return el;
    },
    getElementById: () => null,
};

globalThis.fetch = vi.fn(() => Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ sites: [], total_sites: 0 }),
}));

// Mock EventBus
vi.mock('../../../src/frontend/js/command/events.js', () => ({
    EventBus: {
        on: vi.fn(),
        off: vi.fn(),
        emit: vi.fn(),
    },
}));

// Mock panel-utils
vi.mock('../../../src/frontend/js/command/panel-utils.js', () => ({
    _esc: (s) => String(s || ''),
    _timeAgo: (ts) => 'just now',
}));

describe('FederationPanelDef', () => {
    let FederationPanelDef;

    beforeEach(async () => {
        vi.resetModules();
        vi.clearAllMocks();
        const mod = await import('../../../src/frontend/js/command/panels/federation.js');
        FederationPanelDef = mod.FederationPanelDef;
    });

    it('should have correct panel identity', () => {
        expect(FederationPanelDef.id).toBe('federation');
        expect(FederationPanelDef.title).toBe('FEDERATION SITES');
    });

    it('should have default size', () => {
        expect(FederationPanelDef.defaultSize.w).toBe(520);
        expect(FederationPanelDef.defaultSize.h).toBe(480);
    });

    it('should create panel element', () => {
        const panel = {};
        const el = FederationPanelDef.create(panel);
        expect(el).toBeDefined();
        expect(el.className).toBe('fed-panel-inner');
    });

    it('should have destroy method', () => {
        expect(typeof FederationPanelDef.destroy).toBe('function');
    });

    it('should cleanup timer on destroy', () => {
        const panel = {};
        FederationPanelDef.create(panel);
        expect(panel._fedCleanup).toBeDefined();
        // Should not throw
        FederationPanelDef.destroy(panel);
    });
});
