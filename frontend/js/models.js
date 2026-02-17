/**
 * TRITIUM-SC 3D Unit Models
 * Procedural low-poly cyberpunk models for the War Room 3D renderer.
 *
 * All models built from Three.js geometry primitives with MeshStandardMaterial
 * and neon edge highlights.  No external GLTF files needed.
 *
 * Alliance color scheme:
 *   friendly  #05ffa1 (green) base, #00f0ff (cyan) accent/emissive
 *   hostile   #ff2a6d (magenta) base, dark-red pulse emissive
 *   neutral   #4488ff (blue), alpha 0.6
 *   unknown   #fcee0a (yellow), pulsing emissive
 *
 * Exported functions:
 *   createRoverModel(alliance)   -> THREE.Group
 *   createDroneModel(alliance)   -> THREE.Group
 *   createTurretModel(alliance)  -> THREE.Group
 *   createPersonModel(alliance)  -> THREE.Group
 *   createVehicleModel(alliance) -> THREE.Group
 *   createCameraModel()          -> THREE.Group
 *   createSensorModel()          -> THREE.Group
 *   createSelectionRing()        -> THREE.Group
 *   createBatteryBar(level)      -> THREE.Group
 *   createNameLabel(text, color) -> THREE.Sprite
 *   createThreatRing(level)      -> THREE.Group
 *   getModelForType(assetType, alliance) -> THREE.Group
 */

// ================================================================
// PALETTE
// ================================================================

const MODEL_COLORS = {
    friendly:      0x05ffa1,
    friendlyAccent: 0x00f0ff,
    hostile:       0xff2a6d,
    hostileAccent: 0x660011,
    neutral:       0x4488ff,
    neutralAccent: 0x2244aa,
    unknown:       0xfcee0a,
    unknownAccent: 0x997700,
    cyan:          0x00f0ff,
    dark:          0x12121a,
    metal:         0x334455,
    black:         0x111111,
};

function _allianceColors(alliance) {
    const a = (alliance || 'unknown').toLowerCase();
    switch (a) {
        case 'friendly': return { base: MODEL_COLORS.friendly, accent: MODEL_COLORS.friendlyAccent, emissive: MODEL_COLORS.friendlyAccent, opacity: 1.0 };
        case 'hostile':  return { base: MODEL_COLORS.hostile,  accent: MODEL_COLORS.hostileAccent,  emissive: MODEL_COLORS.hostile, opacity: 1.0 };
        case 'neutral':  return { base: MODEL_COLORS.neutral,  accent: MODEL_COLORS.neutralAccent,  emissive: MODEL_COLORS.neutral, opacity: 0.6 };
        default:         return { base: MODEL_COLORS.unknown,  accent: MODEL_COLORS.unknownAccent,  emissive: MODEL_COLORS.unknown, opacity: 1.0 };
    }
}

// ================================================================
// MATERIAL HELPERS
// ================================================================

function _bodyMat(color, emissive, opacity) {
    return new THREE.MeshStandardMaterial({
        color: color,
        emissive: emissive || 0x000000,
        emissiveIntensity: emissive ? 0.25 : 0,
        roughness: 0.45,
        metalness: 0.55,
        transparent: opacity < 1.0,
        opacity: opacity,
    });
}

function _edgeMat(color, opacity) {
    return new THREE.LineBasicMaterial({
        color: color,
        transparent: true,
        opacity: opacity !== undefined ? opacity : 0.7,
    });
}

function _glowMat(color) {
    return new THREE.MeshBasicMaterial({
        color: color,
        transparent: true,
        opacity: 0.85,
    });
}

function _addNeonEdges(group, geometry, color, position, rotation) {
    const edgeGeo = new THREE.EdgesGeometry(geometry);
    const edges = new THREE.LineSegments(edgeGeo, _edgeMat(color, 0.6));
    if (position) edges.position.copy(position);
    if (rotation) edges.rotation.copy(rotation);
    group.add(edges);
    return edges;
}

// ================================================================
// ROVER — wheeled ground unit with turret
// ================================================================

function createRoverModel(alliance) {
    const g = new THREE.Group();
    const c = _allianceColors(alliance);

    // Chassis — slightly tapered box
    const chassisGeo = new THREE.BoxGeometry(1.5, 0.55, 1.0);
    const chassis = new THREE.Mesh(chassisGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    chassis.position.y = 0.45;
    chassis.castShadow = true;
    g.add(chassis);
    _addNeonEdges(g, chassisGeo, c.accent, chassis.position);

    // Front wedge / bumper
    const wedgeGeo = new THREE.BoxGeometry(1.3, 0.3, 0.3);
    const wedge = new THREE.Mesh(wedgeGeo, _bodyMat(MODEL_COLORS.metal, c.emissive, c.opacity));
    wedge.position.set(0, 0.35, 0.6);
    wedge.rotation.x = -0.15;
    g.add(wedge);

    // Turret base
    const turretBaseGeo = new THREE.CylinderGeometry(0.3, 0.35, 0.25, 8);
    const turretBase = new THREE.Mesh(turretBaseGeo, _bodyMat(MODEL_COLORS.metal, c.emissive, c.opacity));
    turretBase.position.set(0, 0.85, -0.05);
    g.add(turretBase);

    // Turret barrel
    const barrelGeo = new THREE.CylinderGeometry(0.06, 0.08, 0.7, 8);
    const barrel = new THREE.Mesh(barrelGeo, _bodyMat(MODEL_COLORS.black, 0, 1));
    barrel.rotation.x = Math.PI / 2;
    barrel.position.set(0, 0.9, 0.4);
    g.add(barrel);

    // Barrel tip glow
    const tipGeo = new THREE.SphereGeometry(0.07, 6, 6);
    const tip = new THREE.Mesh(tipGeo, _glowMat(c.accent));
    tip.position.set(0, 0.9, 0.75);
    g.add(tip);

    // Antenna
    const antennaGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.5, 4);
    const antenna = new THREE.Mesh(antennaGeo, _bodyMat(MODEL_COLORS.metal, 0, 1));
    antenna.position.set(-0.5, 1.0, -0.35);
    g.add(antenna);
    const antTip = new THREE.Mesh(new THREE.SphereGeometry(0.04, 4, 4), _glowMat(c.accent));
    antTip.position.set(-0.5, 1.25, -0.35);
    g.add(antTip);

    // Wheels (4)
    const wheelGeo = new THREE.CylinderGeometry(0.18, 0.18, 0.12, 10);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.9 });
    const wheelPositions = [
        [-0.75, 0.18, 0.35],
        [ 0.75, 0.18, 0.35],
        [-0.75, 0.18, -0.35],
        [ 0.75, 0.18, -0.35],
    ];
    wheelPositions.forEach(([x, y, z]) => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x, y, z);
        g.add(wheel);
    });

    // Side neon strips
    for (const side of [-1, 1]) {
        const stripGeo = new THREE.BoxGeometry(0.03, 0.03, 0.85);
        const strip = new THREE.Mesh(stripGeo, _glowMat(c.base));
        strip.position.set(side * 0.76, 0.38, 0);
        g.add(strip);
    }

    g.userData.unitType = 'rover';
    return g;
}

// ================================================================
// DRONE — hovering disc with 4 rotors
// ================================================================

function createDroneModel(alliance) {
    const g = new THREE.Group();
    const c = _allianceColors(alliance);

    // Central body — flattened octahedron
    const bodyGeo = new THREE.OctahedronGeometry(0.35, 0);
    const body = new THREE.Mesh(bodyGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    body.scale.set(1, 0.4, 1);
    body.position.y = 0;
    body.castShadow = true;
    g.add(body);
    // Edges on the scaled body
    const bodyEdges = new THREE.EdgesGeometry(bodyGeo);
    const bodyEdgeLines = new THREE.LineSegments(bodyEdges, _edgeMat(c.accent, 0.7));
    bodyEdgeLines.scale.set(1, 0.4, 1);
    g.add(bodyEdgeLines);

    // Arms (4 radial)
    const armLen = 0.55;
    const armAngles = [0, Math.PI / 2, Math.PI, Math.PI * 1.5];
    armAngles.forEach(angle => {
        const armGeo = new THREE.BoxGeometry(armLen, 0.04, 0.06);
        const arm = new THREE.Mesh(armGeo, _bodyMat(MODEL_COLORS.metal, 0, c.opacity));
        const ax = Math.cos(angle) * armLen * 0.5;
        const az = Math.sin(angle) * armLen * 0.5;
        arm.position.set(ax, 0, az);
        arm.rotation.y = -angle;
        g.add(arm);

        // Rotor disc (transparent spinning disc)
        const rotorGeo = new THREE.CylinderGeometry(0.22, 0.22, 0.015, 12);
        const rotorMat = new THREE.MeshBasicMaterial({
            color: c.accent, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false,
        });
        const rotor = new THREE.Mesh(rotorGeo, rotorMat);
        rotor.position.set(Math.cos(angle) * armLen, 0.04, Math.sin(angle) * armLen);
        rotor.userData.isRotor = true;
        g.add(rotor);

        // Motor hub
        const hubGeo = new THREE.CylinderGeometry(0.03, 0.03, 0.05, 6);
        const hub = new THREE.Mesh(hubGeo, _bodyMat(MODEL_COLORS.metal, 0, 1));
        hub.position.set(Math.cos(angle) * armLen, 0.03, Math.sin(angle) * armLen);
        g.add(hub);

        // LED on each arm tip
        const led = new THREE.Mesh(new THREE.SphereGeometry(0.025, 4, 4), _glowMat(c.base));
        led.position.set(Math.cos(angle) * (armLen + 0.05), 0, Math.sin(angle) * (armLen + 0.05));
        g.add(led);
    });

    // Camera gimbal underneath
    const gimbalGeo = new THREE.SphereGeometry(0.06, 6, 6);
    const gimbal = new THREE.Mesh(gimbalGeo, _bodyMat(MODEL_COLORS.black, 0, 1));
    gimbal.position.set(0, -0.12, 0);
    g.add(gimbal);

    // Front indicator
    const frontLed = new THREE.Mesh(new THREE.SphereGeometry(0.035, 4, 4), _glowMat(c.accent));
    frontLed.position.set(0, 0, 0.38);
    g.add(frontLed);

    g.userData.unitType = 'drone';
    g.userData.hoverY = 4.0; // default hover height
    return g;
}

// ================================================================
// TURRET — hexagonal base with gun barrel
// ================================================================

function createTurretModel(alliance) {
    const g = new THREE.Group();
    const c = _allianceColors(alliance);

    // Hexagonal base
    const baseGeo = new THREE.CylinderGeometry(0.6, 0.7, 0.35, 6);
    const base = new THREE.Mesh(baseGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    base.position.y = 0.175;
    base.castShadow = true;
    g.add(base);
    _addNeonEdges(g, baseGeo, c.accent, base.position);

    // Pedestal
    const pedestalGeo = new THREE.CylinderGeometry(0.25, 0.3, 0.4, 8);
    const pedestal = new THREE.Mesh(pedestalGeo, _bodyMat(MODEL_COLORS.metal, 0, c.opacity));
    pedestal.position.y = 0.55;
    g.add(pedestal);

    // Gun head (rotating part)
    const headGeo = new THREE.BoxGeometry(0.5, 0.25, 0.35);
    const head = new THREE.Mesh(headGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    head.position.set(0, 0.87, 0);
    g.add(head);
    _addNeonEdges(g, headGeo, c.accent, head.position);

    // Twin barrels
    for (const offset of [-0.1, 0.1]) {
        const barrelGeo = new THREE.CylinderGeometry(0.04, 0.055, 0.9, 8);
        const barrel = new THREE.Mesh(barrelGeo, _bodyMat(MODEL_COLORS.black, 0, 1));
        barrel.rotation.x = Math.PI / 2;
        barrel.position.set(offset, 0.87, 0.6);
        g.add(barrel);
    }

    // Barrel tip glow
    for (const offset of [-0.1, 0.1]) {
        const tip = new THREE.Mesh(new THREE.SphereGeometry(0.05, 4, 4), _glowMat(c.base));
        tip.position.set(offset, 0.87, 1.05);
        g.add(tip);
    }

    // Sensor eye on top
    const sensorGeo = new THREE.SphereGeometry(0.08, 8, 6);
    const sensor = new THREE.Mesh(sensorGeo, _glowMat(c.accent));
    sensor.position.set(0, 1.05, 0.1);
    g.add(sensor);

    // Neon ring around base
    const ringGeo = new THREE.TorusGeometry(0.65, 0.015, 4, 6);
    const ring = new THREE.Mesh(ringGeo, _glowMat(c.base));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.02;
    g.add(ring);

    g.userData.unitType = 'turret';
    return g;
}

// ================================================================
// PERSON — capsule body with head
// ================================================================

function createPersonModel(alliance) {
    const g = new THREE.Group();
    const c = _allianceColors(alliance);

    // Torso — capsule approximated with cylinder + hemispheres
    const torsoGeo = new THREE.CylinderGeometry(0.18, 0.2, 0.7, 8);
    const torso = new THREE.Mesh(torsoGeo, _bodyMat(c.base, c.emissive, c.opacity));
    torso.position.y = 0.75;
    torso.castShadow = true;
    g.add(torso);

    // Shoulder cap (hemisphere)
    const shoulderGeo = new THREE.SphereGeometry(0.18, 8, 4, 0, Math.PI * 2, 0, Math.PI / 2);
    const shoulder = new THREE.Mesh(shoulderGeo, _bodyMat(c.base, c.emissive, c.opacity));
    shoulder.position.y = 1.1;
    g.add(shoulder);

    // Head
    const headGeo = new THREE.SphereGeometry(0.14, 8, 6);
    const head = new THREE.Mesh(headGeo, _bodyMat(c.base, c.emissive, c.opacity));
    head.position.y = 1.38;
    g.add(head);

    // Visor (face plate)
    const visorGeo = new THREE.BoxGeometry(0.22, 0.06, 0.08);
    const visor = new THREE.Mesh(visorGeo, _glowMat(c.accent));
    visor.position.set(0, 1.38, 0.12);
    g.add(visor);

    // Legs (two thin cylinders)
    for (const side of [-1, 1]) {
        const legGeo = new THREE.CylinderGeometry(0.07, 0.08, 0.5, 6);
        const leg = new THREE.Mesh(legGeo, _bodyMat(MODEL_COLORS.dark, 0, c.opacity));
        leg.position.set(side * 0.1, 0.25, 0);
        g.add(leg);
    }

    // Arms (two thin cylinders at sides)
    for (const side of [-1, 1]) {
        const armGeo = new THREE.CylinderGeometry(0.05, 0.06, 0.45, 6);
        const arm = new THREE.Mesh(armGeo, _bodyMat(c.base, c.emissive, c.opacity));
        arm.position.set(side * 0.26, 0.75, 0);
        arm.rotation.z = side * 0.1;
        arm.userData.isArm = true;
        g.add(arm);
    }

    // Neon outline on torso
    const torsoEdges = new THREE.EdgesGeometry(torsoGeo);
    const torsoLines = new THREE.LineSegments(torsoEdges, _edgeMat(c.accent, 0.4));
    torsoLines.position.copy(torso.position);
    g.add(torsoLines);

    // Ground shadow ring
    const shadowGeo = new THREE.RingGeometry(0.15, 0.25, 16);
    const shadowMat = new THREE.MeshBasicMaterial({
        color: c.base, transparent: true, opacity: 0.15, side: THREE.DoubleSide, depthWrite: false,
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.01;
    g.add(shadow);

    g.userData.unitType = 'person';
    return g;
}

// ================================================================
// VEHICLE — box body with wheels, windshield
// ================================================================

function createVehicleModel(alliance) {
    const g = new THREE.Group();
    const c = _allianceColors(alliance);

    // Main body
    const bodyGeo = new THREE.BoxGeometry(1.5, 0.7, 2.5);
    const body = new THREE.Mesh(bodyGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    body.position.y = 0.65;
    body.castShadow = true;
    g.add(body);
    _addNeonEdges(g, bodyGeo, c.accent, body.position);

    // Cabin (slightly narrower and higher)
    const cabinGeo = new THREE.BoxGeometry(1.3, 0.5, 1.2);
    const cabin = new THREE.Mesh(cabinGeo, _bodyMat(MODEL_COLORS.dark, c.emissive, c.opacity));
    cabin.position.set(0, 1.25, -0.2);
    g.add(cabin);
    _addNeonEdges(g, cabinGeo, c.accent, cabin.position);

    // Windshield (angled transparent plane)
    const windshieldGeo = new THREE.PlaneGeometry(1.2, 0.45);
    const windshieldMat = new THREE.MeshBasicMaterial({
        color: c.accent, transparent: true, opacity: 0.2, side: THREE.DoubleSide, depthWrite: false,
    });
    const windshield = new THREE.Mesh(windshieldGeo, windshieldMat);
    windshield.position.set(0, 1.22, 0.45);
    windshield.rotation.x = 0.3;
    g.add(windshield);

    // Headlights
    for (const side of [-0.55, 0.55]) {
        const headlight = new THREE.Mesh(new THREE.SphereGeometry(0.08, 6, 6), _glowMat(c.accent));
        headlight.position.set(side, 0.65, 1.27);
        g.add(headlight);
    }

    // Wheels (4)
    const wheelGeo = new THREE.CylinderGeometry(0.22, 0.22, 0.15, 10);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x1a1a1a, roughness: 0.9 });
    const wheelPos = [
        [-0.75, 0.22, 0.8],
        [ 0.75, 0.22, 0.8],
        [-0.75, 0.22, -0.8],
        [ 0.75, 0.22, -0.8],
    ];
    wheelPos.forEach(([x, y, z]) => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x, y, z);
        g.add(wheel);
    });

    // Rear lights
    for (const side of [-0.55, 0.55]) {
        const taillight = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.03), _glowMat(MODEL_COLORS.hostile));
        taillight.position.set(side, 0.65, -1.27);
        g.add(taillight);
    }

    // Bottom neon strip
    const stripGeo = new THREE.BoxGeometry(1.4, 0.02, 2.4);
    const strip = new THREE.Mesh(stripGeo, _glowMat(c.base));
    strip.position.y = 0.31;
    g.add(strip);

    g.userData.unitType = 'vehicle';
    return g;
}

// ================================================================
// CAMERA — small housing with lens and FOV cone
// ================================================================

function createCameraModel() {
    const g = new THREE.Group();
    const c = _allianceColors('friendly');

    // Mount pole
    const poleGeo = new THREE.CylinderGeometry(0.04, 0.06, 2.0, 6);
    const pole = new THREE.Mesh(poleGeo, _bodyMat(MODEL_COLORS.metal, 0, 1));
    pole.position.y = 1.0;
    g.add(pole);

    // Camera housing
    const housingGeo = new THREE.BoxGeometry(0.35, 0.2, 0.25);
    const housing = new THREE.Mesh(housingGeo, _bodyMat(MODEL_COLORS.metal, 0, 1));
    housing.position.set(0, 2.1, 0.08);
    housing.castShadow = true;
    g.add(housing);
    _addNeonEdges(g, housingGeo, MODEL_COLORS.cyan, housing.position);

    // Lens
    const lensGeo = new THREE.CylinderGeometry(0.06, 0.08, 0.15, 10);
    const lens = new THREE.Mesh(lensGeo, _bodyMat(MODEL_COLORS.black, MODEL_COLORS.cyan, 1));
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0, 2.1, 0.28);
    g.add(lens);

    // Lens glow ring
    const lensRing = new THREE.Mesh(
        new THREE.TorusGeometry(0.08, 0.01, 4, 10),
        _glowMat(MODEL_COLORS.cyan)
    );
    lensRing.position.set(0, 2.1, 0.36);
    g.add(lensRing);

    // Status LED
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.03, 4, 4), _glowMat(MODEL_COLORS.friendly));
    led.position.set(0.14, 2.18, 0.08);
    g.add(led);

    // FOV cone (semi-transparent)
    const fovRange = 8;
    const fovRad = (30) * Math.PI / 180;
    const coneR = Math.tan(fovRad) * fovRange;
    const coneGeo = new THREE.ConeGeometry(coneR, fovRange, 12, 1, true);
    const coneMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.04,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.rotation.x = -Math.PI / 2;
    cone.position.set(0, 2.1, 0.36 + fovRange / 2);
    g.add(cone);

    g.userData.unitType = 'camera';
    return g;
}

// ================================================================
// SENSOR — dome with detection radius disc
// ================================================================

function createSensorModel() {
    const g = new THREE.Group();

    // Small post
    const postGeo = new THREE.CylinderGeometry(0.03, 0.04, 0.6, 6);
    const post = new THREE.Mesh(postGeo, _bodyMat(MODEL_COLORS.metal, 0, 1));
    post.position.y = 0.3;
    g.add(post);

    // Dome body
    const domeGeo = new THREE.SphereGeometry(0.15, 10, 6, 0, Math.PI * 2, 0, Math.PI / 2);
    const dome = new THREE.Mesh(domeGeo, _bodyMat(MODEL_COLORS.metal, MODEL_COLORS.cyan, 1));
    dome.position.y = 0.6;
    dome.castShadow = true;
    g.add(dome);

    // Base plate
    const basePlateGeo = new THREE.CylinderGeometry(0.18, 0.18, 0.04, 10);
    const basePlate = new THREE.Mesh(basePlateGeo, _bodyMat(MODEL_COLORS.dark, 0, 1));
    basePlate.position.y = 0.58;
    g.add(basePlate);

    // Neon ring around dome
    const domeRing = new THREE.Mesh(
        new THREE.TorusGeometry(0.16, 0.01, 4, 10),
        _glowMat(MODEL_COLORS.cyan)
    );
    domeRing.rotation.x = Math.PI / 2;
    domeRing.position.y = 0.6;
    g.add(domeRing);

    // Detection radius disc on ground
    const detectionRadius = 6;
    const discGeo = new THREE.RingGeometry(detectionRadius - 0.15, detectionRadius, 32);
    const discMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.08,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const disc = new THREE.Mesh(discGeo, discMat);
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.02;
    g.add(disc);

    // Inner fill disc
    const fillGeo = new THREE.CircleGeometry(detectionRadius - 0.15, 32);
    const fillMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.02,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const fill = new THREE.Mesh(fillGeo, fillMat);
    fill.rotation.x = -Math.PI / 2;
    fill.position.y = 0.01;
    g.add(fill);

    g.userData.unitType = 'sensor';
    return g;
}

// ================================================================
// SELECTION RING — cyan pulsing ring for selected units
// ================================================================

function createSelectionRing() {
    const g = new THREE.Group();

    // Outer ring
    const outerGeo = new THREE.TorusGeometry(1.0, 0.03, 4, 32);
    const outerMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.8,
    });
    const outer = new THREE.Mesh(outerGeo, outerMat);
    outer.rotation.x = Math.PI / 2;
    outer.position.y = 0.05;
    g.add(outer);

    // Inner ring (thinner, slightly smaller)
    const innerGeo = new THREE.TorusGeometry(0.85, 0.015, 4, 32);
    const innerMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.4,
    });
    const inner = new THREE.Mesh(innerGeo, innerMat);
    inner.rotation.x = Math.PI / 2;
    inner.position.y = 0.04;
    g.add(inner);

    // Ground glow disc
    const discGeo = new THREE.CircleGeometry(0.95, 32);
    const discMat = new THREE.MeshBasicMaterial({
        color: MODEL_COLORS.cyan, transparent: true, opacity: 0.06,
        side: THREE.DoubleSide, depthWrite: false,
    });
    const disc = new THREE.Mesh(discGeo, discMat);
    disc.rotation.x = -Math.PI / 2;
    disc.position.y = 0.02;
    g.add(disc);

    g.userData.isSelectionRing = true;
    return g;
}

// ================================================================
// BATTERY BAR — thin colored bar
// ================================================================

function createBatteryBar(level) {
    const g = new THREE.Group();
    const barWidth = 1.0;
    const barHeight = 0.06;

    // Background
    const bgGeo = new THREE.PlaneGeometry(barWidth, barHeight);
    const bgMat = new THREE.MeshBasicMaterial({
        color: 0x222222, transparent: true, opacity: 0.6, side: THREE.DoubleSide, depthWrite: false,
    });
    const bg = new THREE.Mesh(bgGeo, bgMat);
    g.add(bg);

    // Fill
    const fillWidth = barWidth * Math.max(0, Math.min(1, level));
    if (fillWidth > 0.001) {
        const fillGeo = new THREE.PlaneGeometry(fillWidth, barHeight);
        // Color gradient: green->yellow->red
        let fillColor;
        if (level > 0.5) {
            fillColor = MODEL_COLORS.friendly; // green
        } else if (level > 0.2) {
            fillColor = MODEL_COLORS.unknown; // yellow
        } else {
            fillColor = MODEL_COLORS.hostile; // red
        }
        const fillMat = new THREE.MeshBasicMaterial({
            color: fillColor, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false,
        });
        const fill = new THREE.Mesh(fillGeo, fillMat);
        fill.position.x = (fillWidth - barWidth) / 2;
        g.add(fill);
    }

    g.userData.isBatteryBar = true;
    return g;
}

// ================================================================
// NAME LABEL — canvas-rendered text sprite (billboard)
// ================================================================

function createNameLabel(text, color) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const fontSize = 28;
    const padding = 12;

    ctx.font = `bold ${fontSize}px "JetBrains Mono", monospace`;
    const textWidth = ctx.measureText(text).width;

    canvas.width = textWidth + padding * 2;
    canvas.height = fontSize + padding * 2;

    // Background pill
    ctx.fillStyle = 'rgba(10, 10, 20, 0.75)';
    const radius = 6;
    const w = canvas.width;
    const h = canvas.height;
    ctx.beginPath();
    ctx.moveTo(radius, 0);
    ctx.lineTo(w - radius, 0);
    ctx.quadraticCurveTo(w, 0, w, radius);
    ctx.lineTo(w, h - radius);
    ctx.quadraticCurveTo(w, h, w - radius, h);
    ctx.lineTo(radius, h);
    ctx.quadraticCurveTo(0, h, 0, h - radius);
    ctx.lineTo(0, radius);
    ctx.quadraticCurveTo(0, 0, radius, 0);
    ctx.closePath();
    ctx.fill();

    // Border
    const hexColor = typeof color === 'number'
        ? '#' + color.toString(16).padStart(6, '0')
        : (color || '#00f0ff');
    ctx.strokeStyle = hexColor;
    ctx.lineWidth = 2;
    ctx.stroke();

    // Text
    ctx.fillStyle = hexColor;
    ctx.font = `bold ${fontSize}px "JetBrains Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, w / 2, h / 2);

    const texture = new THREE.CanvasTexture(canvas);
    texture.minFilter = THREE.LinearFilter;

    const spriteMat = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        depthTest: false,
        depthWrite: false,
    });
    const sprite = new THREE.Sprite(spriteMat);

    // Scale the sprite to be readable
    const aspect = canvas.width / canvas.height;
    sprite.scale.set(aspect * 0.8, 0.8, 1);

    sprite.userData.isNameLabel = true;
    return sprite;
}

// ================================================================
// THREAT RING — animated ring (yellow/orange/red by level)
// ================================================================

function createThreatRing(level) {
    const g = new THREE.Group();

    let color;
    let ringRadius;
    switch ((level || '').toLowerCase()) {
        case 'hostile':
            color = MODEL_COLORS.hostile;
            ringRadius = 1.5;
            break;
        case 'suspicious':
            color = 0xff9800; // orange
            ringRadius = 1.3;
            break;
        default: // 'unknown' or other
            color = MODEL_COLORS.unknown;
            ringRadius = 1.1;
            break;
    }

    // Threat ring (partial arc for animated look)
    const ringGeo = new THREE.TorusGeometry(ringRadius, 0.025, 4, 24, Math.PI * 1.5);
    const ringMat = new THREE.MeshBasicMaterial({
        color: color, transparent: true, opacity: 0.6,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.03;
    g.add(ring);

    // Second arc (offset)
    const ring2Geo = new THREE.TorusGeometry(ringRadius + 0.08, 0.015, 4, 24, Math.PI * 0.8);
    const ring2Mat = new THREE.MeshBasicMaterial({
        color: color, transparent: true, opacity: 0.3,
    });
    const ring2 = new THREE.Mesh(ring2Geo, ring2Mat);
    ring2.rotation.x = Math.PI / 2;
    ring2.rotation.z = Math.PI;
    ring2.position.y = 0.03;
    g.add(ring2);

    g.userData.isThreatRing = true;
    g.userData.threatLevel = level;
    return g;
}

// ================================================================
// ANIMATION HELPERS
// ================================================================

/**
 * Call each frame to animate unit models.
 * @param {THREE.Group} model - the model group
 * @param {number} dt - delta time in seconds
 * @param {number} elapsed - total elapsed seconds
 * @param {object} state - { speed, heading, selected, battery, alliance }
 */
function animateModel(model, dt, elapsed, state) {
    if (!model || !model.userData) return;
    const type = model.userData.unitType;
    const speed = state.speed || 0;

    switch (type) {
        case 'rover':
            // Rotate wheels based on speed
            model.children.forEach(child => {
                if (child.geometry && child.geometry.type === 'CylinderGeometry'
                    && Math.abs(child.position.y - 0.18) < 0.1) {
                    child.rotation.x += speed * dt * 3;
                }
            });
            break;

        case 'drone':
            // Rotor spin
            model.children.forEach(child => {
                if (child.userData && child.userData.isRotor) {
                    child.rotation.y += dt * 15;
                }
            });
            // Gentle hover bob
            if (model.parent) {
                // Applied externally by the renderer to the container position.y
            }
            break;

        case 'turret':
            // Slow scan rotation of the head (if no target)
            // Head is a box mesh near y=0.87
            // Handled externally by pointing the turret group toward nearest hostile
            break;

        case 'person':
            // Arm swing when moving
            if (speed > 0.1) {
                model.children.forEach(child => {
                    if (child.userData && child.userData.isArm) {
                        const side = child.position.x > 0 ? 1 : -1;
                        child.rotation.x = Math.sin(elapsed * 4) * 0.3 * side;
                    }
                });
            }
            break;

        case 'vehicle':
            // Rotate wheels based on speed
            model.children.forEach(child => {
                if (child.geometry && child.geometry.type === 'CylinderGeometry'
                    && Math.abs(child.position.y - 0.22) < 0.1) {
                    child.rotation.x += speed * dt * 3;
                }
            });
            break;
    }
}

/**
 * Animate selection ring (pulsing scale + rotation).
 */
function animateSelectionRing(ring, elapsed) {
    if (!ring) return;
    const pulse = 1.0 + Math.sin(elapsed * 3) * 0.08;
    ring.scale.set(pulse, 1, pulse);
    ring.rotation.y = elapsed * 0.5;
    // Pulse opacity on outer ring
    if (ring.children[0] && ring.children[0].material) {
        ring.children[0].material.opacity = 0.6 + Math.sin(elapsed * 4) * 0.2;
    }
}

/**
 * Animate threat ring (rotation).
 */
function animateThreatRing(ring, elapsed) {
    if (!ring) return;
    ring.rotation.y = elapsed * 1.5;
    // Pulse inner arcs
    if (ring.children[1] && ring.children[1].material) {
        ring.children[1].material.opacity = 0.2 + Math.sin(elapsed * 2) * 0.15;
    }
}

// ================================================================
// TYPE MAPPING — returns the right model for an asset_type string
// ================================================================

function getModelForType(assetType, alliance) {
    const t = (assetType || '').toLowerCase();

    if (t.includes('rover') || t.includes('interceptor') || t === 'ground') {
        return createRoverModel(alliance);
    }
    if (t.includes('drone') || t.includes('aerial') || t.includes('scout')) {
        return createDroneModel(alliance);
    }
    if (t.includes('turret') || t.includes('sentry')) {
        return createTurretModel(alliance);
    }
    if (t.includes('person') || t.includes('intruder') || t.includes('human')) {
        return createPersonModel(alliance);
    }
    if (t.includes('vehicle') || t.includes('car') || t.includes('truck')) {
        return createVehicleModel(alliance);
    }
    if (t.includes('camera') || t.includes('ptz') || t.includes('dome')) {
        return createCameraModel();
    }
    if (t.includes('sensor') || t.includes('motion') || t.includes('microphone')) {
        return createSensorModel();
    }

    // Default: use alliance to pick a reasonable default
    const a = (alliance || 'unknown').toLowerCase();
    if (a === 'hostile') return createPersonModel(alliance);
    if (a === 'friendly') return createRoverModel(alliance);
    return createPersonModel(alliance);
}

// ================================================================
// GLOBAL EXPORTS
// ================================================================

window.TritiumModels = {
    createRoverModel,
    createDroneModel,
    createTurretModel,
    createPersonModel,
    createVehicleModel,
    createCameraModel,
    createSensorModel,
    createSelectionRing,
    createBatteryBar,
    createNameLabel,
    createThreatRing,
    getModelForType,
    animateModel,
    animateSelectionRing,
    animateThreatRing,
    MODEL_COLORS,
};
