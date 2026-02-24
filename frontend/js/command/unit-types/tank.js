import { UnitType } from './base.js';
import { registerType } from './registry.js';

class Tank extends UnitType {
    static typeId = 'tank';
    static displayName = 'Tank';
    static iconLetter = 'K';
    static visionRadius = 45;
    static cotType = 'a-f-G-E-V-A-T';
    static ambientRadius = 15;
    static coneRange = 35;
    static coneAngle = 90;

    /** Larger rounded rectangle with turret barrel. */
    static draw(ctx, scale, color) {
        const w = 32 * scale;
        const h = 20 * scale;
        const r = 4 * scale;
        const barrelLen = 16 * scale;
        const barrelW = 4 * scale;

        // Tracks (darker rectangles on sides)
        ctx.fillStyle = 'rgba(0, 0, 0, 0.4)';
        ctx.fillRect(-w / 2 - 2 * scale, -h / 2, 4 * scale, h);
        ctx.fillRect(w / 2 - 2 * scale, -h / 2, 4 * scale, h);

        // Hull (rounded rect)
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

        // Turret circle
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(0, 0, 6 * scale, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.3)';
        ctx.lineWidth = 1;
        ctx.stroke();

        // Barrel
        ctx.fillStyle = color;
        ctx.fillRect(-barrelW / 2, -6 * scale, barrelW, -barrelLen);
    }
}

registerType(Tank);
export default Tank;
