// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
import { UnitType } from './base.js';
import { registerType } from './registry.js';

class HostilePerson extends UnitType {
    static typeId = 'hostile_person';
    static displayName = 'Hostile';
    static iconLetter = 'H';
    static visionRadius = 20;
    static cotType = 'a-h-G-U-C-I';
    static ambientRadius = 12;

    /** Filled diamond, red, with pulsing glow. */
    static draw(ctx, scale) {
        const s = 8 * scale;
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        const pulse = 0.6 + 0.4 * Math.sin(now * 0.005);

        // Pulsing glow
        ctx.fillStyle = `rgba(255, 42, 109, ${pulse * 0.3})`;
        ctx.beginPath();
        ctx.moveTo(0, -s * 1.4);
        ctx.lineTo(s * 1.4, 0);
        ctx.lineTo(0, s * 1.4);
        ctx.lineTo(-s * 1.4, 0);
        ctx.closePath();
        ctx.fill();

        // Diamond body
        ctx.fillStyle = '#ff2a6d';
        ctx.beginPath();
        ctx.moveTo(0, -s);
        ctx.lineTo(s, 0);
        ctx.lineTo(0, s);
        ctx.lineTo(-s, 0);
        ctx.closePath();
        ctx.fill();

        // Inner mark
        ctx.strokeStyle = '#0a0a0f';
        ctx.lineWidth = 1.5 * scale;
        ctx.beginPath();
        ctx.moveTo(0, -s * 0.4);
        ctx.lineTo(0, s * 0.4);
        ctx.stroke();
    }
}

registerType(HostilePerson);
export default HostilePerson;
