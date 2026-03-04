// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * UnitType base class.
 *
 * Each concrete type overrides the static fields and draw() method.
 * draw() receives a canvas context already translated/rotated to the
 * unit's position and heading -- implementations only need to paint the
 * shape around (0, 0).
 */
export class UnitType {
    static typeId = '';
    static displayName = '';
    static iconLetter = '?';
    static visionRadius = 25;
    static ambientRadius = 10;
    static coneRange = 0;
    static coneAngle = 0;
    static coneSweeps = false;
    static coneSweepRPM = 0;
    static cotType = 'a-u-G';

    /** Fallback draw -- simple filled square. */
    static draw(ctx, scale, color) {
        const s = 8 * scale;
        ctx.fillStyle = color;
        ctx.fillRect(-s, -s, s * 2, s * 2);
    }
}
