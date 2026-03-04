// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
import { UnitType } from './base.js';
import { registerType } from './registry.js';

class Drone extends UnitType {
    static typeId = 'drone';
    static displayName = 'Drone';
    static iconLetter = 'D';
    static visionRadius = 60;
    static cotType = 'a-f-A-M-F-Q';
    static ambientRadius = 20;
    static coneRange = 45;
    static coneAngle = 45;
    static coneSweeps = true;
    static coneSweepRPM = 2;

    /** X-shape with 4 rotor circles at tips. */
    static draw(ctx, scale, color) {
        const armLen = 10 * scale;
        const rotorR = 4 * scale;
        const bodyR = 4 * scale;

        // Arms (X shape)
        ctx.strokeStyle = color;
        ctx.lineWidth = 2 * scale;
        ctx.beginPath();
        ctx.moveTo(-armLen, -armLen);
        ctx.lineTo(armLen, armLen);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(armLen, -armLen);
        ctx.lineTo(-armLen, armLen);
        ctx.stroke();

        // Center body
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, bodyR, 0, Math.PI * 2);
        ctx.fill();

        // 4 rotors at arm tips (spinning animation)
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        const spin = now * 0.01;
        const tips = [
            [-armLen, -armLen],
            [armLen, -armLen],
            [-armLen, armLen],
            [armLen, armLen],
        ];
        for (let i = 0; i < tips.length; i++) {
            ctx.fillStyle = color;
            ctx.globalAlpha = 0.7;
            ctx.beginPath();
            ctx.arc(tips[i][0], tips[i][1], rotorR, 0, Math.PI * 2);
            ctx.fill();
            // Rotor blade lines
            ctx.strokeStyle = color;
            ctx.lineWidth = 1 * scale;
            const bladeAngle = spin + i * Math.PI / 4;
            ctx.beginPath();
            ctx.moveTo(tips[i][0] - Math.cos(bladeAngle) * rotorR, tips[i][1] - Math.sin(bladeAngle) * rotorR);
            ctx.lineTo(tips[i][0] + Math.cos(bladeAngle) * rotorR, tips[i][1] + Math.sin(bladeAngle) * rotorR);
            ctx.stroke();
        }
        ctx.globalAlpha = 1.0;
    }
}

registerType(Drone);
export default Drone;
