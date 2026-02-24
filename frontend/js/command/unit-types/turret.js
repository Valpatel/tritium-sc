import { UnitType } from './base.js';
import { registerType } from './registry.js';

class Turret extends UnitType {
    static typeId = 'turret';
    static displayName = 'Turret';
    static iconLetter = 'T';
    static visionRadius = 50;
    static cotType = 'a-f-G-E-W-D';
    static ambientRadius = 8;
    static coneRange = 40;
    static coneAngle = 90;

    /** Pentagon base with barrel extending in heading direction. */
    static draw(ctx, scale, color, heading) {
        const baseR = 8 * scale;
        const barrelLen = 12 * scale;
        const barrelW = 3 * scale;

        // Pentagon base
        ctx.fillStyle = color;
        ctx.beginPath();
        for (let i = 0; i < 5; i++) {
            const a = (i / 5) * Math.PI * 2 - Math.PI / 2;
            const px = Math.cos(a) * baseR;
            const py = Math.sin(a) * baseR;
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fill();

        // Barrel (extends from center toward top, which is heading direction after rotation)
        ctx.fillStyle = color;
        ctx.fillRect(-barrelW / 2, -baseR, barrelW, -barrelLen);

        // Barrel tip
        ctx.beginPath();
        ctx.arc(0, -baseR - barrelLen, barrelW / 2 + 1, 0, Math.PI * 2);
        ctx.fill();
    }
}

registerType(Turret);
export default Turret;
