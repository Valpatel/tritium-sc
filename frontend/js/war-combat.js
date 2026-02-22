/**
 * TRITIUM-SC War Room — Combat Rendering
 * Projectiles, hit effects, elimination explosions, health bars, weapon ranges, elimination streaks
 *
 * All rendering is done on Canvas 2D via worldToScreen() from war.js.
 * State is kept module-local; war.js calls our update/draw functions each frame.
 */

// ============================================================
// Projectile system
// ============================================================

const _projectiles = []; // active in-flight projectiles

const PROJECTILE_STYLES = {
    nerf_dart: { color: '#ffa500', trailColor: '#ffcc00', radius: 5, trailLen: 8, speed: 25 },
    nerf_rocket: { color: '#ff2a6d', trailColor: '#ff6040', radius: 7, trailLen: 8, speed: 15 },
    water_balloon: { color: '#00a0ff', trailColor: '#40c0ff', radius: 8, trailLen: 6, speed: 12 },
    default: { color: '#fcee0a', trailColor: '#ffee80', radius: 5, trailLen: 8, speed: 20 },
};

function warCombatAddProjectile(data) {
    if (!data) return;
    const style = PROJECTILE_STYLES[data.projectile_type] || PROJECTILE_STYLES.default;
    const sx = data.source_pos ? data.source_pos.x : 0;
    const sy = data.source_pos ? data.source_pos.y : 0;
    const tx = data.target_pos ? data.target_pos.x : 0;
    const ty = data.target_pos ? data.target_pos.y : 0;

    _projectiles.push({
        id: data.id || Date.now(),
        sx, sy, tx, ty,
        x: sx, y: sy,
        type: data.projectile_type || 'default',
        style,
        startTime: Date.now(),
        trail: [{ x: sx, y: sy }],
        speed: data.speed || style.speed,
    });

    // Muzzle flash at firing position
    _screenEffects.push({
        type: 'muzzle_flash',
        x: sx,
        y: sy,
        startTime: Date.now(),
        duration: 100, // 0.1s
    });
}

function warCombatUpdateProjectiles(dt) {
    const now = Date.now();
    for (let i = _projectiles.length - 1; i >= 0; i--) {
        const p = _projectiles[i];
        // Timeout after 2 seconds
        if (now - p.startTime > 2000) {
            _projectiles.splice(i, 1);
            continue;
        }
        // Lerp toward target
        const dx = p.tx - p.x;
        const dy = p.ty - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 0.3) {
            // Arrived
            _projectiles.splice(i, 1);
            continue;
        }
        const step = p.speed * dt;
        const ratio = Math.min(step / dist, 1);
        p.x += dx * ratio;
        p.y += dy * ratio;

        // Record trail
        p.trail.push({ x: p.x, y: p.y });
        if (p.trail.length > p.style.trailLen) {
            p.trail.shift();
        }
    }
}

function warCombatDrawProjectiles(ctx, worldToScreen) {
    for (const p of _projectiles) {
        const s = p.style;
        // Trail (8 segments, brighter, wider)
        for (let i = 0; i < p.trail.length; i++) {
            const t = p.trail[i];
            const sp = worldToScreen(t.x, t.y);
            const alpha = (i + 1) / p.trail.length;
            const alphaVals = [0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.85, 1.0];
            const a = alphaVals[Math.min(i, alphaVals.length - 1)] || alpha;
            ctx.fillStyle = s.trailColor;
            ctx.globalAlpha = a * 0.8;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, s.radius * (0.3 + 0.7 * alpha), 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.globalAlpha = 1.0;

        // Head (larger glow)
        const head = worldToScreen(p.x, p.y);
        ctx.fillStyle = s.color;
        ctx.shadowColor = s.color;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(head.x, head.y, s.radius, 0, Math.PI * 2);
        ctx.fill();
        // Bright core
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(head.x, head.y, s.radius * 0.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        // Water balloon wobble
        if (p.type === 'water_balloon') {
            const wobble = Math.sin(Date.now() * 0.02) * 2;
            ctx.fillStyle = 'rgba(0, 160, 255, 0.3)';
            ctx.beginPath();
            ctx.arc(head.x + wobble, head.y - wobble, s.radius + 2, 0, Math.PI * 2);
            ctx.fill();
        }
    }
}

// ============================================================
// Particle effects system
// ============================================================

const _particles = [];
const _screenEffects = []; // full-screen effects (flashes, elimination streak text)

function _spawnParticles(worldX, worldY, count, color, life, speedRange, sizeRange) {
    for (let i = 0; i < count; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = speedRange[0] + Math.random() * (speedRange[1] - speedRange[0]);
        _particles.push({
            x: worldX,
            y: worldY,
            vx: Math.cos(angle) * speed,
            vy: Math.sin(angle) * speed,
            life,
            maxLife: life,
            color,
            size: sizeRange[0] + Math.random() * (sizeRange[1] - sizeRange[0]),
        });
    }
}

function warCombatAddHitEffect(data) {
    if (!data) return;
    const x = data.position ? data.position.x : 0;
    const y = data.position ? data.position.y : 0;

    // 8 orange particles, fast spread, 0.5s life
    _spawnParticles(x, y, 8, '#ffa500', 0.5, [5, 15], [2, 4]);
    // 4 white sparks
    _spawnParticles(x, y, 4, '#ffffff', 0.3, [8, 20], [1, 2]);
}

function warCombatAddEliminationEffect(data) {
    if (!data) return;
    const x = data.position ? data.position.x : 0;
    const y = data.position ? data.position.y : 0;

    // 29 particles total: 15 red + 8 orange + 6 yellow (larger, with gravity)
    _spawnParticles(x, y, 15, '#ff2a6d', 1.2, [3, 22], [3, 8]);
    _spawnParticles(x, y, 8, '#ffa500', 1.0, [5, 25], [2, 7]);
    _spawnParticles(x, y, 6, '#fcee0a', 0.8, [10, 30], [2, 5]);

    // Expanding ring
    _screenEffects.push({
        type: 'elimination_ring',
        x, y,
        startTime: Date.now(),
        duration: 1200,
    });

    // Floating "ELIMINATED" text
    _screenEffects.push({
        type: 'float_text',
        x, y,
        text: 'ELIMINATED',
        color: '#ff2a6d',
        startTime: Date.now(),
        duration: 1500,
        fontSize: 14,
    });

    // Screen border flash
    _screenEffects.push({
        type: 'screen_flash',
        color: 'rgba(255, 42, 109, 0.15)',
        startTime: Date.now(),
        duration: 300,
    });

    // Screen shake
    _screenEffects.push({
        type: 'screen_shake',
        intensity: 3, // pixels
        startTime: Date.now(),
        duration: 200,
    });
}

function warCombatUpdateEffects(dt) {
    const now = Date.now();

    // Update particles
    for (let i = _particles.length - 1; i >= 0; i--) {
        const p = _particles[i];
        p.life -= dt;
        if (p.life <= 0) {
            _particles.splice(i, 1);
            continue;
        }
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        // Gravity (particles arc downward in world space)
        p.vy -= 15 * dt;
        // Friction
        p.vx *= 0.96;
        p.vy *= 0.96;
    }

    // Prune expired screen effects
    for (let i = _screenEffects.length - 1; i >= 0; i--) {
        if (now - _screenEffects[i].startTime > _screenEffects[i].duration) {
            _screenEffects.splice(i, 1);
        }
    }
}

function warCombatDrawEffects(ctx, worldToScreen, canvasW, canvasH) {
    const now = Date.now();

    // Draw particles
    for (const p of _particles) {
        const sp = worldToScreen(p.x, p.y);
        const lifeRatio = p.life / p.maxLife;
        ctx.globalAlpha = lifeRatio;
        ctx.fillStyle = p.color;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, p.size * lifeRatio, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.globalAlpha = 1.0;

    // Draw screen effects
    for (const e of _screenEffects) {
        const age = (now - e.startTime) / e.duration;

        if (e.type === 'elimination_ring') {
            const sp = worldToScreen(e.x, e.y);
            const radius = age * 60;
            const alpha = Math.max(0, 1 - age);
            ctx.strokeStyle = `rgba(255, 42, 109, ${alpha})`;
            ctx.lineWidth = Math.max(1, 4 * (1 - age));
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
            ctx.stroke();

            // Inner glow ring
            if (age < 0.5) {
                ctx.strokeStyle = `rgba(255, 165, 0, ${(0.5 - age) * 2})`;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, radius * 0.6, 0, Math.PI * 2);
                ctx.stroke();
            }
        }

        if (e.type === 'float_text') {
            const sp = worldToScreen(e.x, e.y);
            const alpha = Math.max(0, 1 - age);
            const yOffset = age * 40;
            ctx.fillStyle = e.color;
            ctx.globalAlpha = alpha;
            ctx.font = `bold ${e.fontSize}px "Orbitron", monospace`;
            ctx.textAlign = 'center';
            ctx.shadowColor = e.color;
            ctx.shadowBlur = 10;
            ctx.fillText(e.text, sp.x, sp.y - yOffset);
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1.0;
        }

        if (e.type === 'screen_flash') {
            const alpha = Math.max(0, 1 - age);
            ctx.fillStyle = e.color;
            ctx.globalAlpha = alpha;
            ctx.fillRect(0, 0, canvasW, canvasH);
            ctx.globalAlpha = 1.0;
        }

        if (e.type === 'elimination_streak' || e.type === 'kill_streak') {
            const alpha = age < 0.2 ? age / 0.2 : Math.max(0, 1 - (age - 0.2) / 0.8);
            const scale = 1 + Math.sin(age * Math.PI) * 0.1;
            ctx.save();
            ctx.translate(canvasW / 2, canvasH * 0.3);
            ctx.scale(scale, scale);
            ctx.fillStyle = e.color;
            ctx.globalAlpha = alpha;
            ctx.font = `bold ${e.fontSize || 36}px "Orbitron", monospace`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.shadowColor = e.color;
            ctx.shadowBlur = 20;
            ctx.fillText(e.text, 0, 0);
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1.0;
            ctx.restore();

            // Screen border glow
            if (age < 0.5) {
                const borderAlpha = (0.5 - age) * 0.4;
                ctx.strokeStyle = e.borderColor || e.color;
                ctx.globalAlpha = borderAlpha;
                ctx.lineWidth = 4;
                ctx.strokeRect(2, 2, canvasW - 4, canvasH - 4);
                ctx.globalAlpha = 1.0;
            }
        }

        if (e.type === 'muzzle_flash') {
            const sp = worldToScreen(e.x, e.y);
            const flashAlpha = Math.max(0, 1 - age);
            const flashRadius = 6 + (1 - age) * 4;
            // White-yellow flash
            ctx.fillStyle = '#ffffff';
            ctx.globalAlpha = flashAlpha;
            ctx.shadowColor = '#ffee00';
            ctx.shadowBlur = 15;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, flashRadius, 0, Math.PI * 2);
            ctx.fill();
            // Yellow outer glow
            ctx.fillStyle = '#ffee00';
            ctx.globalAlpha = flashAlpha * 0.5;
            ctx.beginPath();
            ctx.arc(sp.x, sp.y, flashRadius * 1.8, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
            ctx.globalAlpha = 1.0;
        }

        if (e.type === 'screen_shake') {
            // Screen shake is applied as a canvas translate offset
            // The actual offset is read by warCombatGetScreenShake()
            // so map.js can apply it during rendering
        }
    }
}

/**
 * Returns the current screen shake offset { x, y } for the camera to apply.
 * Called by the map renderer each frame.
 */
function warCombatGetScreenShake() {
    const now = Date.now();
    let shakeX = 0, shakeY = 0;
    for (const e of _screenEffects) {
        if (e.type === 'screen_shake') {
            const age = (now - e.startTime) / e.duration;
            if (age < 1) {
                const decay = 1 - age;
                const intensity = e.intensity * decay;
                shakeX += (Math.random() * 2 - 1) * intensity;
                shakeY += (Math.random() * 2 - 1) * intensity;
            }
        }
    }
    return { x: shakeX, y: shakeY };
}

// ============================================================
// Health bars
// ============================================================

function warCombatDrawHealthBar(ctx, screenX, screenY, health, maxHealth, alliance, radius) {
    if (health >= maxHealth) return; // no bar for full health

    const barW = Math.max(20, radius * 3);
    const barH = 4;
    const bx = screenX - barW / 2;
    const by = screenY + radius + 6;

    // Background
    ctx.fillStyle = 'rgba(30, 30, 40, 0.8)';
    ctx.fillRect(bx - 1, by - 1, barW + 2, barH + 2);

    // Fill color based on health ratio
    const ratio = Math.max(0, Math.min(1, health / maxHealth));
    let fillColor;
    if (ratio > 0.6) fillColor = '#05ffa1';
    else if (ratio > 0.3) fillColor = '#fcee0a';
    else fillColor = '#ff2a6d';

    ctx.fillStyle = fillColor;
    ctx.fillRect(bx, by, barW * ratio, barH);

    // Border in alliance color
    const allianceColors = { friendly: '#05ffa1', hostile: '#ff2a6d', neutral: '#00a0ff', unknown: '#fcee0a' };
    ctx.strokeStyle = allianceColors[alliance] || '#fcee0a';
    ctx.lineWidth = 1;
    ctx.strokeRect(bx - 1, by - 1, barW + 2, barH + 2);
}

// ============================================================
// Weapon range indicators
// ============================================================

function warCombatDrawWeaponRange(ctx, worldToScreen, target, zoom) {
    if (!target || !target.position) return;
    const range = target.weapon_range || 8; // default 8 world units
    const sp = worldToScreen(target.position.x, target.position.y);
    const sr = range * zoom;

    ctx.strokeStyle = 'rgba(0, 240, 255, 0.2)';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 6]);
    ctx.beginPath();
    ctx.arc(sp.x, sp.y, sr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    // Range label
    ctx.fillStyle = 'rgba(0, 240, 255, 0.25)';
    ctx.font = '8px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${range}m`, sp.x, sp.y - sr - 4);
}

// ============================================================
// Elimination streak effects
// ============================================================

const STREAK_NAMES = {
    3: 'KILLING SPREE',
    5: 'RAMPAGE',
    7: 'DOMINATING',
    10: 'GODLIKE',
};

function warCombatAddEliminationStreakEffect(data) {
    if (!data) return;
    const streak = data.streak || 0;
    const name = data.streak_name || STREAK_NAMES[streak] || `${streak}x STREAK`;
    const isFriendly = (data.alliance || '').toLowerCase() === 'friendly';

    _screenEffects.push({
        type: 'elimination_streak',
        text: name,
        color: isFriendly ? '#00f0ff' : '#ff2a6d',
        borderColor: isFriendly ? 'rgba(0, 240, 255, 0.5)' : 'rgba(255, 42, 109, 0.5)',
        fontSize: streak >= 10 ? 48 : 36,
        startTime: Date.now(),
        duration: 2500,
    });

    // Screen flash
    _screenEffects.push({
        type: 'screen_flash',
        color: isFriendly ? 'rgba(0, 240, 255, 0.1)' : 'rgba(255, 42, 109, 0.1)',
        startTime: Date.now(),
        duration: 400,
    });
}

// ============================================================
// Improved target shapes
// ============================================================

function warCombatDrawTargetShape(ctx, sp, radius, target, alliance, zoom) {
    const type = (target.asset_type || '').toLowerCase();
    const heading = target.heading;
    const isEliminated = (target.status || '').toLowerCase() === 'eliminated'
        || (target.status || '').toLowerCase() === 'neutralized';

    if (isEliminated) {
        ctx.globalAlpha = 0.3;
    }

    if (alliance === 'hostile') {
        // Hostile: red diamond with "weapon" line
        _drawDiamond(ctx, sp.x, sp.y, radius, '#ff2a6d');
        // Small "nerf gun" indicator line
        if (heading !== undefined && heading !== null) {
            const rad = (90 - heading) * Math.PI / 180;
            const gunLen = radius * 1.5;
            ctx.strokeStyle = '#ff6060';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(sp.x + Math.cos(rad) * gunLen, sp.y - Math.sin(rad) * gunLen);
            ctx.stroke();
            // Gun tip dot
            ctx.fillStyle = '#ff4040';
            ctx.beginPath();
            ctx.arc(sp.x + Math.cos(rad) * gunLen, sp.y - Math.sin(rad) * gunLen, 2, 0, Math.PI * 2);
            ctx.fill();
        }
    } else if (type.includes('turret') || type.includes('sentry')) {
        // Turret: green square with rotation line
        _drawSquare(ctx, sp.x, sp.y, radius, '#05ffa1');
        if (heading !== undefined && heading !== null) {
            const rad = (90 - heading) * Math.PI / 180;
            const aimLen = radius * 2.5;
            ctx.strokeStyle = '#05ffa1';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(sp.x + Math.cos(rad) * aimLen, sp.y - Math.sin(rad) * aimLen);
            ctx.stroke();
        }
        // Weapon cooldown arc
        if (target.last_fired && target.weapon_cooldown) {
            const elapsed = (Date.now() - target.last_fired) / 1000;
            const fraction = Math.min(1, elapsed / target.weapon_cooldown);
            if (fraction < 1) {
                ctx.strokeStyle = 'rgba(5, 255, 161, 0.4)';
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.arc(sp.x, sp.y, radius * 1.8, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * fraction);
                ctx.stroke();
            }
        }
    } else if (type.includes('drone')) {
        // Drone: triangle pointing in heading direction, slightly transparent
        ctx.globalAlpha = isEliminated ? 0.2 : 0.75;
        _drawTriangle(ctx, sp.x, sp.y, radius, heading, '#05ffa1');
        ctx.globalAlpha = isEliminated ? 0.3 : 1.0;
        // Spinning rotors
        if (!isEliminated) {
            const rotorAngle = Date.now() * 0.008;
            const rotorDist = radius * 0.8;
            for (let i = 0; i < 4; i++) {
                const a = rotorAngle + i * Math.PI / 2;
                ctx.fillStyle = 'rgba(5, 255, 161, 0.7)';
                ctx.beginPath();
                ctx.arc(sp.x + Math.cos(a) * rotorDist, sp.y + Math.sin(a) * rotorDist, 2, 0, Math.PI * 2);
                ctx.fill();
            }
        }
    } else if (type.includes('mesh_radio') || type.includes('meshtastic')) {
        // Mesh radio: cyan antenna icon
        const color = '#00f0ff';
        // Antenna mast
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(sp.x, sp.y + radius * 0.6);
        ctx.lineTo(sp.x, sp.y - radius * 1.0);
        ctx.stroke();
        // Antenna tip dot
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y - radius * 1.0, 2.5, 0, Math.PI * 2);
        ctx.fill();
        // Radio waves (two arcs)
        ctx.strokeStyle = 'rgba(0, 240, 255, 0.5)';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y - radius * 0.5, radius * 0.6, -Math.PI * 0.7, -Math.PI * 0.3);
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(sp.x, sp.y - radius * 0.5, radius * 1.0, -Math.PI * 0.7, -Math.PI * 0.3);
        ctx.stroke();
        // Base
        ctx.fillStyle = 'rgba(0, 240, 255, 0.4)';
        ctx.fillRect(sp.x - radius * 0.4, sp.y + radius * 0.4, radius * 0.8, radius * 0.3);
    } else if (type.includes('truck') || type.includes('vehicle')) {
        // Truck: larger green rectangle
        _drawRect(ctx, sp.x, sp.y, radius * 1.6, radius * 1.0, heading, '#05ffa1');
    } else if (type.includes('rover') || type.includes('interceptor') || type.includes('patrol')) {
        // Rover: green circle with thick outline
        ctx.fillStyle = 'rgba(5, 255, 161, 0.6)';
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#05ffa1';
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.stroke();
        // Heading
        if (heading !== undefined && heading !== null) {
            const rad = (90 - heading) * Math.PI / 180;
            ctx.strokeStyle = '#05ffa1';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(sp.x + Math.cos(rad) * radius * 2, sp.y - Math.sin(rad) * radius * 2);
            ctx.stroke();
        }
    } else if (alliance === 'neutral') {
        // Non-combatant: blue/gray, smaller, semi-transparent
        ctx.globalAlpha = isEliminated ? 0.15 : 0.45;
        ctx.fillStyle = '#6080a0';
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius * 0.7, 0, Math.PI * 2);
        ctx.fill();
        ctx.globalAlpha = isEliminated ? 0.3 : 1.0;
        return; // no health bar for non-combatants
    } else if (alliance === 'friendly') {
        // Generic friendly: green circle
        ctx.fillStyle = '#05ffa1';
        ctx.beginPath();
        ctx.arc(sp.x, sp.y, radius, 0, Math.PI * 2);
        ctx.fill();
        // Heading
        if (heading !== undefined && heading !== null) {
            const rad = (90 - heading) * Math.PI / 180;
            ctx.strokeStyle = '#05ffa1';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(sp.x, sp.y);
            ctx.lineTo(sp.x + Math.cos(rad) * radius * 2.2, sp.y - Math.sin(rad) * radius * 2.2);
            ctx.stroke();
        }
    } else {
        // Unknown: yellow square
        ctx.fillStyle = '#fcee0a';
        const half = radius * 0.8;
        ctx.fillRect(sp.x - half, sp.y - half, half * 2, half * 2);
    }

    // Eliminated overlay: X mark and fade-out
    if (isEliminated) {
        const xSize = radius * 1.2;
        ctx.strokeStyle = '#ff2a6d';
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(sp.x - xSize, sp.y - xSize);
        ctx.lineTo(sp.x + xSize, sp.y + xSize);
        ctx.moveTo(sp.x + xSize, sp.y - xSize);
        ctx.lineTo(sp.x - xSize, sp.y + xSize);
        ctx.stroke();
        ctx.globalAlpha = 1.0;
    }
}

// Shape helpers
function _drawDiamond(ctx, x, y, r, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y - r);
    ctx.lineTo(x + r, y);
    ctx.lineTo(x, y + r);
    ctx.lineTo(x - r, y);
    ctx.closePath();
    ctx.fill();
}

function _drawSquare(ctx, x, y, r, color) {
    ctx.fillStyle = color;
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x - r, y - r, r * 2, r * 2);
}

function _drawTriangle(ctx, x, y, r, heading, color) {
    const rad = heading !== undefined && heading !== null
        ? (90 - heading) * Math.PI / 180
        : Math.PI / 2; // default pointing up
    ctx.fillStyle = color;
    ctx.beginPath();
    // Point in heading direction
    ctx.moveTo(x + Math.cos(rad) * r * 1.3, y - Math.sin(rad) * r * 1.3);
    ctx.lineTo(x + Math.cos(rad + 2.4) * r, y - Math.sin(rad + 2.4) * r);
    ctx.lineTo(x + Math.cos(rad - 2.4) * r, y - Math.sin(rad - 2.4) * r);
    ctx.closePath();
    ctx.fill();
}

function _drawRect(ctx, x, y, w, h, heading, color) {
    const rad = heading !== undefined && heading !== null
        ? (90 - heading) * Math.PI / 180
        : Math.PI / 2;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(-rad + Math.PI / 2);
    ctx.fillStyle = color;
    ctx.fillRect(-w / 2, -h / 2, w, h);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(-w / 2, -h / 2, w, h);
    ctx.restore();
}

// ============================================================
// Reset (called on Play Again)
// ============================================================

function warCombatReset() {
    _projectiles.length = 0;
    _particles.length = 0;
    _screenEffects.length = 0;
}

// ============================================================
// Expose globally
// ============================================================

window.warCombatAddProjectile = warCombatAddProjectile;
window.warCombatUpdateProjectiles = warCombatUpdateProjectiles;
window.warCombatDrawProjectiles = warCombatDrawProjectiles;
window.warCombatAddHitEffect = warCombatAddHitEffect;
window.warCombatAddEliminationEffect = warCombatAddEliminationEffect;
window.warCombatUpdateEffects = warCombatUpdateEffects;
window.warCombatDrawEffects = warCombatDrawEffects;
window.warCombatDrawHealthBar = warCombatDrawHealthBar;
window.warCombatDrawWeaponRange = warCombatDrawWeaponRange;
window.warCombatAddEliminationStreakEffect = warCombatAddEliminationStreakEffect;
window.warCombatDrawTargetShape = warCombatDrawTargetShape;
window.warCombatGetScreenShake = warCombatGetScreenShake;
window.warCombatReset = warCombatReset;
