// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
import { UnitType } from './base.js';
import { registerType } from './registry.js';

class Rover extends UnitType {
    static typeId = 'rover';
    static displayName = 'Patrol Rover';
    static iconLetter = 'R';
    static visionRadius = 40;
    static cotType = 'a-f-G-E-V-A-L';
    static ambientRadius = 12;
    static coneRange = 30;
    static coneAngle = 120;

    /** Rounded rectangle body with 4 wheel circles. */
    static draw(ctx, scale, color) {
        const w = 24 * scale;
        const h = 16 * scale;
        const r = 3 * scale;

        // Body (rounded rect)
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(-w / 2 + r, -h / 2);
        ctx.lineTo(w / 2 - r, -h / 2);
        ctx.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
        ctx.lineTo(w / 2, h / 2 - r);
        ctx.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
        ctx.lineTo(-w / 2 + r, h / 2);
        ctx.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
        ctx.lineTo(-w / 2, -h / 2 + r);
        ctx.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
        ctx.closePath();
        ctx.fill();

        // 4 wheels
        const wheelR = 3 * scale;
        const wheelOffX = w / 2 - 1 * scale;
        const wheelOffY = h / 2 + 1 * scale;
        ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
        const wheelPositions = [
            [-wheelOffX, -wheelOffY],
            [wheelOffX, -wheelOffY],
            [-wheelOffX, wheelOffY],
            [wheelOffX, wheelOffY],
        ];
        for (const [wx, wy] of wheelPositions) {
            ctx.beginPath();
            ctx.arc(wx, wy, wheelR, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}

registerType(Rover);
export default Rover;
