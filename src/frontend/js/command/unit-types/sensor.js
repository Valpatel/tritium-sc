// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
import { UnitType } from './base.js';
import { registerType } from './registry.js';

class Sensor extends UnitType {
    static typeId = 'sensor';
    static displayName = 'Sensor';
    static iconLetter = 'S';
    static visionRadius = 30;
    static cotType = 'a-f-G-E-S-E';
    static ambientRadius = 20;

    /** Small circle with FOV cone indicator. */
    static draw(ctx, scale, color) {
        const r = 6 * scale;
        const coneLen = 12 * scale;
        const coneAngle = Math.PI / 4; // 45 degree half-angle

        // FOV cone
        ctx.fillStyle = color.replace(')', ', 0.15)').replace('#', 'rgba(');
        // Use manual color to avoid parsing issues
        if (color === '#05ffa1') ctx.fillStyle = 'rgba(5, 255, 161, 0.15)';
        else if (color === '#ff2a6d') ctx.fillStyle = 'rgba(255, 42, 109, 0.15)';
        else if (color === '#00a0ff') ctx.fillStyle = 'rgba(0, 160, 255, 0.15)';
        else ctx.fillStyle = 'rgba(252, 238, 10, 0.15)';
        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.lineTo(Math.sin(coneAngle) * coneLen, -Math.cos(coneAngle) * coneLen);
        ctx.arc(0, 0, coneLen, -Math.PI / 2 - coneAngle, -Math.PI / 2 + coneAngle);
        ctx.closePath();
        ctx.fill();

        // Body circle
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.fill();

        // Lens dot
        ctx.fillStyle = '#0a0a0f';
        ctx.beginPath();
        ctx.arc(0, -r * 0.3, 2 * scale, 0, Math.PI * 2);
        ctx.fill();
    }
}

registerType(Sensor);
export default Sensor;
