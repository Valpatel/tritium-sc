import { UnitType } from './base.js';
import { registerType } from './registry.js';

class NeutralPerson extends UnitType {
    static typeId = 'neutral_person';
    static displayName = 'Person';
    static iconLetter = 'P';
    static visionRadius = 15;
    static cotType = 'a-n-G-U-C';
    static ambientRadius = 10;

    /** Small circle with simple figure silhouette. */
    static draw(ctx, scale) {
        const r = 5 * scale;

        // Body circle
        ctx.fillStyle = '#00a0ff';
        ctx.beginPath();
        ctx.arc(0, 0, r, 0, Math.PI * 2);
        ctx.fill();

        // Head (smaller circle above)
        ctx.fillStyle = '#00a0ff';
        ctx.beginPath();
        ctx.arc(0, -r * 1.5, r * 0.5, 0, Math.PI * 2);
        ctx.fill();

        // Walking legs animation
        const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
        const legSwing = Math.sin(now * 0.006) * 3 * scale;
        ctx.strokeStyle = '#00a0ff';
        ctx.lineWidth = 1.5 * scale;
        ctx.beginPath();
        ctx.moveTo(0, r * 0.5);
        ctx.lineTo(legSwing, r * 1.5);
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(0, r * 0.5);
        ctx.lineTo(-legSwing, r * 1.5);
        ctx.stroke();
    }
}

registerType(NeutralPerson);
export default NeutralPerson;
