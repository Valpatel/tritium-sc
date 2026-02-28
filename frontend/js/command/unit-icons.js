// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
/**
 * TRITIUM Command Center -- Procedural Unit Icons
 *
 * Each unit type gets a distinct Canvas 2D icon rendered procedurally.
 * All icons rotate with heading, scale with zoom, and support selection
 * rings and health bars.
 *
 * Exports: drawUnit(), UNIT_TYPES, ALLIANCE_COLORS, getVisionRadius()
 */

// ============================================================
// Constants
// ============================================================

const ALLIANCE_COLORS = {
    friendly: '#05ffa1',
    hostile:  '#ff2a6d',
    neutral:  '#00a0ff',
    unknown:  '#fcee0a',
};

const UNIT_TYPES = [
    'rover', 'drone', 'turret', 'hostile_person', 'neutral_person',
    'tank', 'sensor', 'camera',
];

// Vision radius per type (world meters)
const VISION_RADII = {
    rover:   40,
    drone:   60,
    turret:  50,
    camera:  30,
    sensor:  30,
    neutral_person: 15,
    hostile_person: 20,
    tank:    45,
    default: 25,
};

// ============================================================
// Vision radius lookup
// ============================================================

function getVisionRadius(type) {
    return VISION_RADII[type] || VISION_RADII.default;
}

// ============================================================
// Main draw function
// ============================================================

/**
 * Draw a unit icon on the canvas.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {string} type - rover, drone, turret, hostile_person, neutral_person, tank, sensor, camera
 * @param {string} alliance - friendly, hostile, neutral, unknown
 * @param {number} heading - degrees, 0=north, clockwise
 * @param {number} screenX - screen X position (CSS pixels)
 * @param {number} screenY - screen Y position (CSS pixels)
 * @param {number} scale - zoom-derived scale (1.0 = base size)
 * @param {boolean} selected - draw pulsing selection ring
 * @param {number} health - 0.0 to 1.0 (0 = neutralized)
 */
function drawUnit(ctx, type, alliance, heading, screenX, screenY, scale, selected, health) {
    const color = ALLIANCE_COLORS[alliance] || ALLIANCE_COLORS.unknown;
    const rad = heading !== undefined && heading !== null
        ? (90 - heading) * Math.PI / 180
        : Math.PI / 2; // default pointing up
    const isNeutralized = health <= 0;

    ctx.save();
    ctx.translate(screenX, screenY);

    // Fade neutralized units
    if (isNeutralized) {
        ctx.globalAlpha = 0.35;
    }

    // Rotate to heading
    ctx.save();
    ctx.rotate(-rad + Math.PI / 2);

    // Draw type-specific shape
    switch (type) {
        case 'rover':
            _drawRover(ctx, scale, color);
            break;
        case 'drone':
            _drawDrone(ctx, scale, color);
            break;
        case 'turret':
            _drawTurret(ctx, scale, color, heading);
            break;
        case 'hostile_person':
            _drawHostilePerson(ctx, scale);
            break;
        case 'neutral_person':
            _drawNeutralPerson(ctx, scale);
            break;
        case 'tank':
            _drawTank(ctx, scale, color);
            break;
        case 'sensor':
        case 'camera':
            _drawSensor(ctx, scale, color);
            break;
        default:
            // Fallback: simple square
            _drawFallback(ctx, scale, color);
            break;
    }

    ctx.restore(); // undo rotation

    // Heading indicator arrow (drawn after rotation undo, points in heading direction)
    if (!isNeutralized && heading !== undefined && heading !== null) {
        _drawHeadingArrow(ctx, rad, scale, color);
    }

    // Neutralized X overlay
    if (isNeutralized) {
        _drawNeutralizedX(ctx, scale);
    }

    ctx.globalAlpha = 1.0;

    // Selection ring (drawn outside rotation, in screen space)
    if (selected) {
        _drawSelectionRing(ctx, scale);
    }

    // Health bar (only if damaged, not neutralized)
    if (health < 1.0 && !isNeutralized) {
        _drawHealthBar(ctx, scale, health);
    }

    ctx.restore(); // undo translate
}

// ============================================================
// Type-specific shapes
// ============================================================

/** Rover: Rounded rectangle body with 4 wheel circles */
function _drawRover(ctx, scale, color) {
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

/** Drone: X-shape with 4 rotor circles at tips */
function _drawDrone(ctx, scale, color) {
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

/** Turret: Pentagon base with barrel extending in heading direction */
function _drawTurret(ctx, scale, color, heading) {
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

/** Hostile person: Filled diamond, red, with pulsing glow */
function _drawHostilePerson(ctx, scale) {
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

/** Neutral person: Small circle with simple figure silhouette */
function _drawNeutralPerson(ctx, scale) {
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

/** Tank: Larger rounded rectangle with turret barrel */
function _drawTank(ctx, scale, color) {
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

/** Sensor/Camera: Small circle with FOV cone indicator */
function _drawSensor(ctx, scale, color) {
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

/** Fallback: simple filled square */
function _drawFallback(ctx, scale, color) {
    const s = 8 * scale;
    ctx.fillStyle = color;
    ctx.fillRect(-s, -s, s * 2, s * 2);
}

// ============================================================
// Decorations (selection ring, health bar, heading arrow, X overlay)
// ============================================================

/** Pulsing cyan selection ring */
function _drawSelectionRing(ctx, scale) {
    const r = 16 * scale;
    const now = typeof performance !== 'undefined' ? performance.now() : Date.now();
    const pulse = 0.5 + 0.5 * Math.sin(now * 0.005);

    // Inner ring
    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(0, 0, r, 0, Math.PI * 2);
    ctx.stroke();

    // Pulsing outer ring
    ctx.strokeStyle = `rgba(0, 240, 255, ${0.15 + pulse * 0.25})`;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(0, 0, r + 3 + pulse * 3, 0, Math.PI * 2);
    ctx.stroke();
}

/** Health bar below unit (green -> yellow -> red gradient) */
function _drawHealthBar(ctx, scale, health) {
    const barW = 24 * scale;
    const barH = 3;
    const bx = -barW / 2;
    const by = 12 * scale;

    // Background
    ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
    ctx.fillRect(bx, by, barW, barH);

    // Health fill color
    let r, g;
    if (health > 0.5) {
        const t = (health - 0.5) * 2;
        r = Math.round(255 * (1 - t));
        g = 255;
    } else {
        const t = health * 2;
        r = 255;
        g = Math.round(255 * t);
    }
    ctx.fillStyle = `rgb(${r}, ${g}, 0)`;
    ctx.fillRect(bx, by, barW * health, barH);
}

/** Small heading arrow */
function _drawHeadingArrow(ctx, rad, scale, color) {
    const arrowLen = 14 * scale;
    const arrowW = 3 * scale;
    const tipX = Math.cos(rad) * arrowLen;
    const tipY = -Math.sin(rad) * arrowLen;

    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(0, 0);
    ctx.lineTo(tipX, tipY);
    ctx.stroke();

    // Arrowhead
    const headLen = 4 * scale;
    const angle = Math.atan2(-tipY, tipX);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - headLen * Math.cos(angle - 0.5), tipY + headLen * Math.sin(angle - 0.5));
    ctx.lineTo(tipX - headLen * Math.cos(angle + 0.5), tipY + headLen * Math.sin(angle + 0.5));
    ctx.closePath();
    ctx.fill();
}

/** X overlay for neutralized units */
function _drawNeutralizedX(ctx, scale) {
    const s = 10 * scale;
    ctx.strokeStyle = '#ff2a6d';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-s, -s);
    ctx.lineTo(s, s);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(s, -s);
    ctx.lineTo(-s, s);
    ctx.stroke();
}

// ============================================================
// Exports
// ============================================================

export { drawUnit, UNIT_TYPES, ALLIANCE_COLORS, getVisionRadius };
