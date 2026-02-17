/**
 * TritiumAssets - Tritium-SC security assets for the Graphlings editor
 *
 * Registers cameras, robots, drones, structures, streets, zones,
 * sensors, and patrol paths with cyberpunk neon aesthetics.
 *
 * Color palette from grid.js: cyan #00f0ff, magenta #ff2a6d, green #05ffa1, yellow #fcee0a
 *
 * Usage:
 *   registerTritiumAssets(registry);
 */

// Tritium cyberpunk palette
const TRITIUM_COLORS = {
    cyan: 0x00f0ff,
    magenta: 0xff2a6d,
    green: 0x05ffa1,
    yellow: 0xfcee0a,
    void: 0x0a0a0f,
    dark: 0x12121a,
    gray: 0x1a1a2e,
    metal: 0x334455,
    concrete: 0x555566,
    asphalt: 0x222233,
    fence: 0x444455,
    glass: 0x88ccff
};

// ================================================================
// ASSET SCHEMAS
// ================================================================

const CAMERA_SCHEMAS = {
    security_camera: {
        category: 'cameras', name: 'Security Camera',
        params: {
            fov: { default: 60, min: 30, max: 120, step: 10 },
            range: { default: 15, min: 5, max: 40, step: 5 },
            height: { default: 3, min: 2, max: 8, step: 0.5 },
            channel: { default: 1, min: 1, max: 16, step: 1 }
        }
    },
    ptz_camera: {
        category: 'cameras', name: 'PTZ Camera',
        params: {
            fov: { default: 45, min: 10, max: 90, step: 5 },
            range: { default: 25, min: 10, max: 60, step: 5 },
            height: { default: 4, min: 2, max: 10, step: 0.5 },
            channel: { default: 1, min: 1, max: 16, step: 1 }
        }
    },
    dome_camera: {
        category: 'cameras', name: 'Dome Camera',
        params: {
            fov: { default: 360, min: 180, max: 360, step: 30 },
            range: { default: 10, min: 5, max: 25, step: 5 },
            height: { default: 3, min: 2, max: 6, step: 0.5 },
            channel: { default: 1, min: 1, max: 16, step: 1 }
        }
    }
};

const ROBOT_SCHEMAS = {
    patrol_rover: {
        category: 'robots', name: 'Patrol Rover',
        params: {
            size: { default: 1, min: 0.5, max: 2, step: 0.25 },
            sensorRange: { default: 10, min: 5, max: 25, step: 5 },
            speed: { default: 'medium', options: ['slow', 'medium', 'fast'] }
        }
    },
    interceptor_bot: {
        category: 'robots', name: 'Interceptor Bot',
        params: {
            size: { default: 0.8, min: 0.5, max: 1.5, step: 0.25 },
            sensorRange: { default: 15, min: 5, max: 30, step: 5 },
            speed: { default: 'fast', options: ['medium', 'fast', 'sprint'] }
        }
    },
    sentry_turret: {
        category: 'robots', name: 'Sentry Turret',
        params: {
            range: { default: 20, min: 10, max: 40, step: 5 },
            arc: { default: 180, min: 90, max: 360, step: 30 }
        }
    }
};

const DRONE_SCHEMAS = {
    recon_drone: {
        category: 'drones', name: 'Recon Drone',
        params: {
            wingspan: { default: 0.6, min: 0.3, max: 1.2, step: 0.1 },
            altitude: { default: 15, min: 5, max: 40, step: 5 },
            cameraType: { default: 'standard', options: ['standard', 'thermal', 'night_vision'] }
        }
    },
    heavy_drone: {
        category: 'drones', name: 'Heavy Drone',
        params: {
            wingspan: { default: 1.0, min: 0.6, max: 1.8, step: 0.2 },
            altitude: { default: 20, min: 10, max: 50, step: 5 },
            cameraType: { default: 'thermal', options: ['standard', 'thermal', 'night_vision', 'lidar'] }
        }
    },
    scout_drone: {
        category: 'drones', name: 'Scout Drone',
        params: {
            wingspan: { default: 0.3, min: 0.2, max: 0.6, step: 0.05 },
            altitude: { default: 8, min: 3, max: 20, step: 2 },
            cameraType: { default: 'night_vision', options: ['standard', 'night_vision'] }
        }
    }
};

const STRUCTURE_SCHEMAS = {
    tritium_house: {
        category: 'structures', name: 'House',
        params: {
            width: { default: 12, min: 6, max: 25, step: 1 },
            depth: { default: 10, min: 6, max: 20, step: 1 },
            height: { default: 6, min: 3, max: 12, step: 1 }
        }
    },
    tritium_garage: {
        category: 'structures', name: 'Garage',
        params: {
            width: { default: 6, min: 4, max: 10, step: 1 },
            depth: { default: 7, min: 5, max: 10, step: 1 },
            height: { default: 3, min: 2.5, max: 5, step: 0.5 }
        }
    },
    tritium_shed: {
        category: 'structures', name: 'Shed',
        params: {
            width: { default: 3, min: 2, max: 6, step: 0.5 },
            depth: { default: 3, min: 2, max: 6, step: 0.5 },
            height: { default: 2.5, min: 2, max: 4, step: 0.5 }
        }
    },
    tritium_fence: {
        category: 'structures', name: 'Fence',
        params: {
            length: { default: 10, min: 2, max: 30, step: 1 },
            height: { default: 2, min: 1, max: 4, step: 0.5 }
        }
    },
    tritium_wall: {
        category: 'structures', name: 'Wall',
        params: {
            length: { default: 8, min: 2, max: 20, step: 1 },
            height: { default: 3, min: 1.5, max: 6, step: 0.5 },
            thickness: { default: 0.3, min: 0.15, max: 0.6, step: 0.05 }
        }
    },
    tritium_gate: {
        category: 'structures', name: 'Gate',
        params: {
            width: { default: 4, min: 2, max: 8, step: 0.5 },
            height: { default: 2, min: 1.5, max: 4, step: 0.5 }
        }
    }
};

const STREET_SCHEMAS = {
    road_straight: {
        category: 'streets', name: 'Road Straight',
        params: {
            length: { default: 20, min: 5, max: 50, step: 5 },
            width: { default: 6, min: 4, max: 10, step: 1 },
            lanes: { default: 2, min: 1, max: 4, step: 1 }
        }
    },
    road_curve: {
        category: 'streets', name: 'Road Curve',
        params: {
            radius: { default: 10, min: 5, max: 25, step: 5 },
            width: { default: 6, min: 4, max: 10, step: 1 },
            angle: { default: 90, min: 30, max: 180, step: 15 }
        }
    },
    road_tjunction: {
        category: 'streets', name: 'T-Junction',
        params: {
            width: { default: 6, min: 4, max: 10, step: 1 }
        }
    },
    sidewalk: {
        category: 'streets', name: 'Sidewalk',
        params: {
            length: { default: 10, min: 2, max: 30, step: 2 },
            width: { default: 2, min: 1, max: 4, step: 0.5 }
        }
    },
    driveway: {
        category: 'streets', name: 'Driveway',
        params: {
            length: { default: 8, min: 4, max: 15, step: 1 },
            width: { default: 3, min: 2, max: 5, step: 0.5 }
        }
    }
};

const ZONE_SCHEMAS = {
    activity_zone: {
        category: 'zones', name: 'Activity Zone', isMarker: true,
        params: {
            width: { default: 8, min: 2, max: 30, step: 1 },
            depth: { default: 8, min: 2, max: 30, step: 1 },
            height: { default: 4, min: 1, max: 10, step: 0.5 }
        }
    },
    entry_exit_zone: {
        category: 'zones', name: 'Entry/Exit Zone', isMarker: true,
        params: {
            width: { default: 4, min: 2, max: 12, step: 1 },
            depth: { default: 4, min: 2, max: 12, step: 1 },
            height: { default: 3, min: 1, max: 8, step: 0.5 }
        }
    },
    tripwire: {
        category: 'zones', name: 'Tripwire', isMarker: true,
        params: {
            length: { default: 10, min: 2, max: 30, step: 1 },
            height: { default: 0.5, min: 0.1, max: 2, step: 0.1 }
        }
    },
    restricted_area: {
        category: 'zones', name: 'Restricted Area', isMarker: true,
        params: {
            width: { default: 12, min: 4, max: 40, step: 2 },
            depth: { default: 12, min: 4, max: 40, step: 2 },
            height: { default: 5, min: 2, max: 15, step: 1 }
        }
    }
};

const SENSOR_SCHEMAS = {
    motion_sensor: {
        category: 'sensors', name: 'Motion Sensor', isMarker: true,
        params: {
            range: { default: 8, min: 3, max: 20, step: 1 },
            arc: { default: 120, min: 45, max: 360, step: 15 }
        }
    },
    microphone_sensor: {
        category: 'sensors', name: 'Microphone', isMarker: true,
        params: {
            range: { default: 15, min: 5, max: 30, step: 5 }
        }
    },
    speaker: {
        category: 'sensors', name: 'Speaker',
        params: {
            volume: { default: 'medium', options: ['low', 'medium', 'high'] }
        }
    },
    floodlight: {
        category: 'sensors', name: 'Floodlight',
        params: {
            range: { default: 15, min: 5, max: 30, step: 5 },
            arc: { default: 90, min: 30, max: 180, step: 15 },
            brightness: { default: 'high', options: ['low', 'medium', 'high'] }
        }
    }
};

const PATH_SCHEMAS = {
    patrol_waypoint: {
        category: 'paths', name: 'Patrol Waypoint', isMarker: true,
        params: {
            waitTime: { default: 5, min: 0, max: 60, step: 5 },
            lookDirection: { default: 0, min: 0, max: 360, step: 15 }
        }
    },
    observation_point: {
        category: 'paths', name: 'Observation Point', isMarker: true,
        params: {
            dwellTime: { default: 15, min: 5, max: 120, step: 5 },
            priority: { default: 'normal', options: ['low', 'normal', 'high', 'critical'] }
        }
    }
};

// ================================================================
// GENERATORS: CAMERAS
// ================================================================

function genSecurityCamera(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.6, metalness: 0.4 });
    const lensMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.3, metalness: 0.7 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan });

    // Mount arm
    const arm = new THREE.Mesh(new THREE.BoxGeometry(0.15, p.height, 0.15), bodyMat);
    arm.position.y = p.height / 2;
    g.add(arm);

    // Camera body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.5, 1.2), bodyMat);
    body.position.set(0, p.height, 0.3);
    g.add(body);

    // Lens
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.2, 0.3, 12), lensMat);
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0, p.height, 0.95);
    g.add(lens);

    // Status LED
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), neonMat);
    led.position.set(0.3, p.height + 0.2, 0.3);
    g.add(led);

    // FOV cone (transparent)
    const fovRad = (p.fov / 2) * Math.PI / 180;
    const coneRadius = Math.tan(fovRad) * p.range;
    const coneGeo = new THREE.ConeGeometry(coneRadius, p.range, 16, 1, true);
    const coneMat = new THREE.MeshBasicMaterial({
        color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.08,
        side: THREE.DoubleSide, depthWrite: false
    });
    const cone = new THREE.Mesh(coneGeo, coneMat);
    cone.rotation.x = -Math.PI / 2;
    cone.position.set(0, p.height, 0.95 + p.range / 2);
    g.add(cone);

    return g;
}

function genPTZCamera(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3a, roughness: 0.5, metalness: 0.5 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan });

    // Pole mount
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, p.height, 8), bodyMat);
    pole.position.y = p.height / 2;
    g.add(pole);

    // PTZ housing (sphere)
    const housing = new THREE.Mesh(new THREE.SphereGeometry(0.4, 12, 12), bodyMat);
    housing.position.y = p.height;
    g.add(housing);

    // Lens assembly
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.18, 0.5, 10), new THREE.MeshStandardMaterial({ color: 0x111111, metalness: 0.8 }));
    lens.rotation.x = Math.PI / 2;
    lens.position.set(0, p.height, 0.45);
    g.add(lens);

    // Neon ring
    const ring = new THREE.Mesh(
        new THREE.TorusGeometry(0.42, 0.02, 8, 24),
        neonMat
    );
    ring.position.y = p.height;
    ring.rotation.x = Math.PI / 2;
    g.add(ring);

    // FOV cone
    const fovRad = (p.fov / 2) * Math.PI / 180;
    const coneRadius = Math.tan(fovRad) * p.range;
    const cone = new THREE.Mesh(
        new THREE.ConeGeometry(coneRadius, p.range, 16, 1, true),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green, transparent: true, opacity: 0.06, side: THREE.DoubleSide, depthWrite: false })
    );
    cone.rotation.x = -Math.PI / 2;
    cone.position.set(0, p.height, p.range / 2 + 0.5);
    g.add(cone);

    return g;
}

function genDomeCamera(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.5, metalness: 0.4 });
    const domeMat = new THREE.MeshStandardMaterial({ color: 0x111122, transparent: true, opacity: 0.7, roughness: 0.2, metalness: 0.6 });

    // Mount
    const mount = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, p.height, 8), bodyMat);
    mount.position.y = p.height / 2;
    g.add(mount);

    // Base plate
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.1, 16), bodyMat);
    base.position.y = p.height;
    g.add(base);

    // Dome
    const dome = new THREE.Mesh(
        new THREE.SphereGeometry(0.4, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2),
        domeMat
    );
    dome.position.y = p.height + 0.05;
    dome.rotation.x = Math.PI;
    g.add(dome);

    // Range indicator (circle on ground)
    const rangeRing = new THREE.Mesh(
        new THREE.RingGeometry(p.range - 0.2, p.range, 32),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false })
    );
    rangeRing.rotation.x = -Math.PI / 2;
    rangeRing.position.y = 0.05;
    g.add(rangeRing);

    return g;
}

// ================================================================
// GENERATORS: ROBOTS
// ================================================================

function genPatrolRover(p) {
    const g = new THREE.Group();
    const s = p.size;
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.dark, roughness: 0.6, metalness: 0.4 });
    const accentMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.5, metalness: 0.5 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan });

    // Chassis
    const chassis = new THREE.Mesh(new THREE.BoxGeometry(1.6 * s, 0.5 * s, 2.4 * s), bodyMat);
    chassis.position.y = 0.5 * s;
    chassis.castShadow = true;
    g.add(chassis);

    // Sensor dome
    const dome = new THREE.Mesh(new THREE.SphereGeometry(0.35 * s, 12, 8, 0, Math.PI * 2, 0, Math.PI / 2), accentMat);
    dome.position.y = 0.8 * s;
    g.add(dome);

    // Antenna
    const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.02 * s, 0.02 * s, 0.6 * s, 6), accentMat);
    antenna.position.set(-0.5 * s, 1.1 * s, -0.5 * s);
    g.add(antenna);
    const antennaTip = new THREE.Mesh(new THREE.SphereGeometry(0.04 * s, 6, 6), neonMat);
    antennaTip.position.set(-0.5 * s, 1.4 * s, -0.5 * s);
    g.add(antennaTip);

    // Wheels (4)
    const wheelGeo = new THREE.CylinderGeometry(0.25 * s, 0.25 * s, 0.15 * s, 12);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.9 });
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(([x, z]) => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x * 0.8 * s, 0.25 * s, z * 0.9 * s);
        g.add(wheel);
    });

    // Neon edge highlights
    const edgeGeo = new THREE.EdgesGeometry(new THREE.BoxGeometry(1.6 * s, 0.5 * s, 2.4 * s));
    const edgeLine = new THREE.LineSegments(edgeGeo, new THREE.LineBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.5 }));
    edgeLine.position.y = 0.5 * s;
    g.add(edgeLine);

    // Sensor range indicator
    const rangeRing = new THREE.Mesh(
        new THREE.RingGeometry(p.sensorRange - 0.3, p.sensorRange, 32),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false })
    );
    rangeRing.rotation.x = -Math.PI / 2;
    rangeRing.position.y = 0.05;
    g.add(rangeRing);

    return g;
}

function genInterceptorBot(p) {
    const g = new THREE.Group();
    const s = p.size;
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x1a1a2e, roughness: 0.5, metalness: 0.5 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.magenta });

    // Sleek body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.8 * s, 0.4 * s, 1.8 * s), bodyMat);
    body.position.y = 0.35 * s;
    g.add(body);

    // Front wedge
    const wedge = new THREE.Mesh(new THREE.BoxGeometry(0.7 * s, 0.3 * s, 0.6 * s), bodyMat);
    wedge.rotation.x = -0.2;
    wedge.position.set(0, 0.3 * s, 1.1 * s);
    g.add(wedge);

    // Sensor eye
    const eye = new THREE.Mesh(new THREE.SphereGeometry(0.1 * s, 8, 8), neonMat);
    eye.position.set(0, 0.4 * s, 1.3 * s);
    g.add(eye);

    // Wheels (4 small)
    const wheelGeo = new THREE.CylinderGeometry(0.15 * s, 0.15 * s, 0.1 * s, 10);
    const wheelMat = new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.9 });
    [[-1, -1], [-1, 1], [1, -1], [1, 1]].forEach(([x, z]) => {
        const wheel = new THREE.Mesh(wheelGeo, wheelMat);
        wheel.rotation.z = Math.PI / 2;
        wheel.position.set(x * 0.45 * s, 0.15 * s, z * 0.7 * s);
        g.add(wheel);
    });

    // Neon strips
    for (const side of [-1, 1]) {
        const strip = new THREE.Mesh(
            new THREE.BoxGeometry(0.02 * s, 0.02 * s, 1.6 * s),
            neonMat
        );
        strip.position.set(side * 0.41 * s, 0.35 * s, 0);
        g.add(strip);
    }

    return g;
}

function genSentryTurret(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.5, metalness: 0.5 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.magenta });

    // Base
    const base = new THREE.Mesh(new THREE.CylinderGeometry(0.6, 0.8, 0.4, 12), bodyMat);
    base.position.y = 0.2;
    g.add(base);

    // Swivel mount
    const swivel = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.4, 0.5, 10), bodyMat);
    swivel.position.y = 0.65;
    g.add(swivel);

    // Barrel
    const barrel = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.1, 1.5, 8), new THREE.MeshStandardMaterial({ color: 0x222222, metalness: 0.7 }));
    barrel.rotation.x = Math.PI / 2;
    barrel.position.set(0, 0.7, 0.9);
    g.add(barrel);

    // Sensor (top)
    const sensor = new THREE.Mesh(new THREE.SphereGeometry(0.12, 8, 8), neonMat);
    sensor.position.set(0, 1, 0.2);
    g.add(sensor);

    // Arc indicator
    const arcRad = (p.arc / 2) * Math.PI / 180;
    const arcGeo = new THREE.RingGeometry(p.range * 0.8, p.range, 32, 1, -arcRad, arcRad * 2);
    const arcMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.magenta, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false });
    const arcMesh = new THREE.Mesh(arcGeo, arcMat);
    arcMesh.rotation.x = -Math.PI / 2;
    arcMesh.position.y = 0.05;
    g.add(arcMesh);

    return g;
}

// ================================================================
// GENERATORS: DRONES
// ================================================================

function genReconDrone(p) {
    const g = new THREE.Group();
    const s = p.wingspan;
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3a, roughness: 0.5, metalness: 0.5 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green });

    // Cross frame
    const arm1 = new THREE.Mesh(new THREE.BoxGeometry(s * 2, 0.05, 0.08), frameMat);
    arm1.position.y = p.altitude;
    g.add(arm1);
    const arm2 = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.05, s * 2), frameMat);
    arm2.position.y = p.altitude;
    g.add(arm2);

    // Center body
    const center = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.1, 0.2), frameMat);
    center.position.y = p.altitude;
    g.add(center);

    // Rotors (4)
    const rotorMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.3 });
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([x, z]) => {
        const rotor = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.35, s * 0.35, 0.02, 12), rotorMat);
        rotor.position.set(x * s, p.altitude + 0.05, z * s);
        g.add(rotor);
        // Motor hub
        const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, 0.06, 8), frameMat);
        hub.position.set(x * s, p.altitude + 0.05, z * s);
        g.add(hub);
    });

    // Camera gimbal
    const gimbal = new THREE.Mesh(new THREE.SphereGeometry(0.06, 8, 8), new THREE.MeshStandardMaterial({ color: 0x111111 }));
    gimbal.position.set(0, p.altitude - 0.08, 0);
    g.add(gimbal);

    // Neon status light
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.03, 6, 6), neonMat);
    led.position.set(0, p.altitude + 0.08, 0.12);
    g.add(led);

    // Altitude line (dashed to ground)
    const linePoints = [new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, p.altitude - 0.1, 0)];
    const lineGeo = new THREE.BufferGeometry().setFromPoints(linePoints);
    const lineMat = new THREE.LineBasicMaterial({ color: TRITIUM_COLORS.green, transparent: true, opacity: 0.2 });
    g.add(new THREE.Line(lineGeo, lineMat));

    return g;
}

function genHeavyDrone(p) {
    const g = new THREE.Group();
    const s = p.wingspan;
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x1a1a2a, roughness: 0.4, metalness: 0.6 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow });

    // Hexa frame (6 arms)
    for (let i = 0; i < 6; i++) {
        const angle = (i * Math.PI * 2) / 6;
        const arm = new THREE.Mesh(new THREE.BoxGeometry(s, 0.06, 0.1), frameMat);
        arm.position.set(Math.cos(angle) * s * 0.5, p.altitude, Math.sin(angle) * s * 0.5);
        arm.rotation.y = angle;
        g.add(arm);

        // Rotor
        const rotor = new THREE.Mesh(
            new THREE.CylinderGeometry(s * 0.3, s * 0.3, 0.02, 12),
            new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.25 })
        );
        rotor.position.set(Math.cos(angle) * s, p.altitude + 0.05, Math.sin(angle) * s);
        g.add(rotor);
    }

    // Center body
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.15, 0.4), frameMat);
    body.position.y = p.altitude;
    g.add(body);

    // Camera rig
    const gimbal = new THREE.Mesh(new THREE.BoxGeometry(0.15, 0.1, 0.15), new THREE.MeshStandardMaterial({ color: 0x111111 }));
    gimbal.position.set(0, p.altitude - 0.15, 0);
    g.add(gimbal);

    // Status lights
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.04, 6, 6), neonMat);
    led.position.set(0, p.altitude + 0.1, 0.22);
    g.add(led);

    // Altitude line
    const lineGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0, 0), new THREE.Vector3(0, p.altitude - 0.2, 0)
    ]);
    g.add(new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: TRITIUM_COLORS.yellow, transparent: true, opacity: 0.15 })));

    return g;
}

function genScoutDrone(p) {
    const g = new THREE.Group();
    const s = p.wingspan;
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x222233, roughness: 0.5, metalness: 0.4 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green });

    // Tiny cross frame
    const arm1 = new THREE.Mesh(new THREE.BoxGeometry(s * 1.6, 0.03, 0.04), frameMat);
    arm1.position.y = p.altitude;
    g.add(arm1);
    const arm2 = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.03, s * 1.6), frameMat);
    arm2.position.y = p.altitude;
    g.add(arm2);

    // Rotors
    const rotorMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green, transparent: true, opacity: 0.3 });
    [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([x, z]) => {
        const rotor = new THREE.Mesh(new THREE.CylinderGeometry(s * 0.3, s * 0.3, 0.01, 10), rotorMat);
        rotor.position.set(x * s * 0.8, p.altitude + 0.03, z * s * 0.8);
        g.add(rotor);
    });

    // Camera
    const cam = new THREE.Mesh(new THREE.SphereGeometry(0.04, 6, 6), new THREE.MeshStandardMaterial({ color: 0x111111 }));
    cam.position.set(0, p.altitude - 0.04, 0);
    g.add(cam);

    // LED
    const led = new THREE.Mesh(new THREE.SphereGeometry(0.02, 4, 4), neonMat);
    led.position.set(0, p.altitude + 0.04, s * 0.6);
    g.add(led);

    return g;
}

// ================================================================
// GENERATORS: STRUCTURES (grid.js wireframe pattern)
// ================================================================

function genTritiumStructure(p, color) {
    const g = new THREE.Group();
    const w = p.width || p.length || 10;
    const d = p.depth || p.length || 10;
    const h = p.height || 3;

    // Solid dark fill
    const fillMat = new THREE.MeshBasicMaterial({
        color: TRITIUM_COLORS.dark, transparent: true, opacity: 0.7
    });
    const boxGeo = new THREE.BoxGeometry(w, h, d);
    const fill = new THREE.Mesh(boxGeo, fillMat);
    fill.position.y = h / 2;
    fill.castShadow = true;
    fill.receiveShadow = true;
    g.add(fill);

    // Neon wireframe edges (grid.js pattern)
    const edgeGeo = new THREE.EdgesGeometry(boxGeo);
    const edgeMat = new THREE.LineBasicMaterial({
        color: color || TRITIUM_COLORS.cyan,
        transparent: true,
        opacity: 0.5
    });
    const edges = new THREE.LineSegments(edgeGeo, edgeMat);
    edges.position.y = h / 2;
    g.add(edges);

    return g;
}

function genTritiumFence(p) {
    const g = new THREE.Group();
    const posts = Math.max(2, Math.ceil(p.length / 2));
    const postMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.fence, roughness: 0.7 });

    for (let i = 0; i < posts; i++) {
        const x = (i / (posts - 1) - 0.5) * p.length;
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.08, p.height, 0.08), postMat);
        post.position.set(x, p.height / 2, 0);
        g.add(post);
    }

    // Horizontal rails
    for (let r = 0; r < 3; r++) {
        const rail = new THREE.Mesh(
            new THREE.BoxGeometry(p.length, 0.04, 0.04),
            postMat
        );
        rail.position.y = p.height * (0.25 + r * 0.25);
        g.add(rail);
    }

    // Neon top wire
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.6 });
    const topWire = new THREE.Mesh(new THREE.BoxGeometry(p.length, 0.02, 0.02), neonMat);
    topWire.position.y = p.height;
    g.add(topWire);

    return g;
}

function genTritiumGate(p) {
    const g = new THREE.Group();
    const gateMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.6, metalness: 0.4 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.green });

    // Posts
    for (const side of [-1, 1]) {
        const post = new THREE.Mesh(new THREE.BoxGeometry(0.2, p.height + 0.5, 0.2), gateMat);
        post.position.set(side * p.width / 2, (p.height + 0.5) / 2, 0);
        g.add(post);
    }

    // Gate panels (two halves)
    for (const side of [-1, 1]) {
        const panel = new THREE.Mesh(
            new THREE.BoxGeometry(p.width / 2 - 0.15, p.height - 0.2, 0.05),
            new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.dark, transparent: true, opacity: 0.5 })
        );
        panel.position.set(side * p.width / 4, p.height / 2, 0);
        g.add(panel);
    }

    // Neon top bar
    const topBar = new THREE.Mesh(new THREE.BoxGeometry(p.width + 0.4, 0.05, 0.05), neonMat);
    topBar.position.y = p.height + 0.5;
    g.add(topBar);

    return g;
}

// ================================================================
// GENERATORS: STREETS
// ================================================================

function genRoadStraight(p) {
    const g = new THREE.Group();
    // Road surface
    const roadMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.asphalt, roughness: 0.9 });
    const road = new THREE.Mesh(new THREE.PlaneGeometry(p.width, p.length), roadMat);
    road.rotation.x = -Math.PI / 2;
    road.position.y = 0.01;
    road.receiveShadow = true;
    g.add(road);

    // Lane markings
    const lineMat = new THREE.MeshBasicMaterial({ color: 0xffff00, transparent: true, opacity: 0.7 });
    if (p.lanes >= 2) {
        // Center line (dashed)
        const dashCount = Math.floor(p.length / 3);
        for (let i = 0; i < dashCount; i++) {
            const dash = new THREE.Mesh(new THREE.PlaneGeometry(0.15, 1.5), lineMat);
            dash.rotation.x = -Math.PI / 2;
            dash.position.set(0, 0.02, (i - dashCount / 2 + 0.5) * 3);
            g.add(dash);
        }
    }

    // Edge lines (solid white)
    const edgeLineMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.5 });
    for (const side of [-1, 1]) {
        const edgeLine = new THREE.Mesh(new THREE.PlaneGeometry(0.12, p.length), edgeLineMat);
        edgeLine.rotation.x = -Math.PI / 2;
        edgeLine.position.set(side * (p.width / 2 - 0.1), 0.02, 0);
        g.add(edgeLine);
    }

    return g;
}

function genRoadCurve(p) {
    const g = new THREE.Group();
    const segments = 16;
    const angleRad = (p.angle * Math.PI) / 180;
    const roadMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.asphalt, roughness: 0.9 });

    // Arc surface
    const shape = new THREE.Shape();
    const innerR = p.radius - p.width / 2;
    const outerR = p.radius + p.width / 2;
    for (let i = 0; i <= segments; i++) {
        const a = (i / segments) * angleRad;
        const x = Math.cos(a) * outerR;
        const z = Math.sin(a) * outerR;
        if (i === 0) shape.moveTo(x, z);
        else shape.lineTo(x, z);
    }
    for (let i = segments; i >= 0; i--) {
        const a = (i / segments) * angleRad;
        shape.lineTo(Math.cos(a) * innerR, Math.sin(a) * innerR);
    }
    shape.closePath();

    const geo = new THREE.ShapeGeometry(shape);
    geo.rotateX(-Math.PI / 2);
    const mesh = new THREE.Mesh(geo, roadMat);
    mesh.position.y = 0.01;
    mesh.receiveShadow = true;
    g.add(mesh);

    return g;
}

function genTJunction(p) {
    const g = new THREE.Group();
    const roadMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.asphalt, roughness: 0.9 });

    // Main road
    const main = new THREE.Mesh(new THREE.PlaneGeometry(p.width * 3, p.width), roadMat);
    main.rotation.x = -Math.PI / 2;
    main.position.y = 0.01;
    g.add(main);

    // Branch
    const branch = new THREE.Mesh(new THREE.PlaneGeometry(p.width, p.width * 1.5), roadMat);
    branch.rotation.x = -Math.PI / 2;
    branch.position.set(0, 0.01, p.width * 1.25);
    g.add(branch);

    return g;
}

function genSidewalk(p) {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.concrete, roughness: 0.85 });
    const sidewalk = new THREE.Mesh(new THREE.BoxGeometry(p.width, 0.15, p.length), mat);
    sidewalk.position.y = 0.075;
    sidewalk.receiveShadow = true;
    g.add(sidewalk);
    return g;
}

function genDriveway(p) {
    const g = new THREE.Group();
    const mat = new THREE.MeshStandardMaterial({ color: 0x15151f, roughness: 0.85 });
    const drive = new THREE.Mesh(new THREE.PlaneGeometry(p.width, p.length), mat);
    drive.rotation.x = -Math.PI / 2;
    drive.position.y = 0.01;
    drive.receiveShadow = true;
    g.add(drive);
    return g;
}

// ================================================================
// GENERATORS: ZONES
// ================================================================

function genZoneBox(p) {
    const g = new THREE.Group();
    const w = p.width || p.length || 8;
    const d = p.depth || p.length || 8;
    const h = p.height || 4;

    // Transparent fill
    const fillMat = new THREE.MeshBasicMaterial({
        color: TRITIUM_COLORS.green, transparent: true, opacity: 0.08,
        side: THREE.DoubleSide, depthWrite: false
    });
    const boxGeo = new THREE.BoxGeometry(w, h, d);
    const fill = new THREE.Mesh(boxGeo, fillMat);
    fill.position.y = h / 2;
    g.add(fill);

    // Wireframe edges
    const edgeGeo = new THREE.EdgesGeometry(boxGeo);
    const edgeMat = new THREE.LineBasicMaterial({ color: TRITIUM_COLORS.green, transparent: true, opacity: 0.4 });
    const edges = new THREE.LineSegments(edgeGeo, edgeMat);
    edges.position.y = h / 2;
    g.add(edges);

    return g;
}

function genEntryExitZone(p) {
    const g = genZoneBox(p);
    // Override color to magenta
    g.children.forEach(child => {
        if (child.material) {
            child.material.color.setHex(TRITIUM_COLORS.magenta);
        }
    });
    return g;
}

function genTripwire(p) {
    const g = new THREE.Group();
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.magenta });

    // Line beam
    const beam = new THREE.Mesh(new THREE.BoxGeometry(p.length, 0.02, 0.02), neonMat);
    beam.position.y = p.height;
    g.add(beam);

    // End posts
    for (const side of [-1, 1]) {
        const post = new THREE.Mesh(
            new THREE.CylinderGeometry(0.04, 0.04, p.height + 0.3, 8),
            new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal })
        );
        post.position.set(side * p.length / 2, (p.height + 0.3) / 2, 0);
        g.add(post);
    }

    // Ground line indicator
    const groundLine = new THREE.Mesh(
        new THREE.PlaneGeometry(p.length, 0.3),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.magenta, transparent: true, opacity: 0.15, side: THREE.DoubleSide })
    );
    groundLine.rotation.x = -Math.PI / 2;
    groundLine.position.y = 0.02;
    g.add(groundLine);

    return g;
}

function genRestrictedArea(p) {
    const g = genZoneBox(p);
    // Override to red
    g.children.forEach(child => {
        if (child.material) {
            child.material.color.setHex(0xff0000);
        }
    });
    return g;
}

// ================================================================
// GENERATORS: SENSORS
// ================================================================

function genMotionSensor(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.5, metalness: 0.4 });
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow });

    // Housing
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.2, 0.15), bodyMat);
    body.position.y = 2;
    g.add(body);

    // Lens
    const lens = new THREE.Mesh(new THREE.SphereGeometry(0.08, 8, 6, 0, Math.PI), neonMat);
    lens.rotation.y = Math.PI;
    lens.position.set(0, 2, 0.08);
    g.add(lens);

    // Range indicator arc
    const arcRad = (p.arc / 2) * Math.PI / 180;
    const arcGeo = new THREE.RingGeometry(p.range * 0.8, p.range, 24, 1, -arcRad, arcRad * 2);
    const arcMesh = new THREE.Mesh(arcGeo,
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false })
    );
    arcMesh.rotation.x = -Math.PI / 2;
    arcMesh.position.y = 0.05;
    g.add(arcMesh);

    return g;
}

function genMicrophone(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.6 });

    // Body
    const body = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.3, 10), bodyMat);
    body.position.y = 2;
    g.add(body);

    // Mesh cap
    const cap = new THREE.Mesh(
        new THREE.SphereGeometry(0.1, 8, 4, 0, Math.PI * 2, 0, Math.PI / 2),
        new THREE.MeshStandardMaterial({ color: 0x333333, wireframe: true })
    );
    cap.position.y = 2.15;
    g.add(cap);

    // Range ring
    const ring = new THREE.Mesh(
        new THREE.RingGeometry(p.range - 0.2, p.range, 32),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow, transparent: true, opacity: 0.06, side: THREE.DoubleSide, depthWrite: false })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.05;
    g.add(ring);

    return g;
}

function genSpeaker(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x2a2a3a, roughness: 0.6 });

    // Box
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.4, 0.3, 0.2), bodyMat);
    body.position.y = 2.5;
    g.add(body);

    // Cone
    const cone = new THREE.Mesh(
        new THREE.CylinderGeometry(0.05, 0.12, 0.1, 12),
        new THREE.MeshStandardMaterial({ color: 0x111111 })
    );
    cone.rotation.x = Math.PI / 2;
    cone.position.set(0, 2.5, 0.15);
    g.add(cone);

    return g;
}

function genFloodlight(p) {
    const g = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: TRITIUM_COLORS.metal, roughness: 0.6, metalness: 0.3 });

    // Pole
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 3, 8), bodyMat);
    pole.position.y = 1.5;
    g.add(pole);

    // Housing
    const housing = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.3, 0.2), bodyMat);
    housing.position.set(0, 3.1, 0.1);
    g.add(housing);

    // Light surface
    const lightMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow });
    const lightSurface = new THREE.Mesh(new THREE.PlaneGeometry(0.4, 0.2), lightMat);
    lightSurface.position.set(0, 3.1, 0.21);
    g.add(lightSurface);

    // Light cone
    const arcRad = (p.arc / 2) * Math.PI / 180;
    const coneR = Math.tan(arcRad) * p.range;
    const cone = new THREE.Mesh(
        new THREE.ConeGeometry(coneR, p.range, 12, 1, true),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.yellow, transparent: true, opacity: 0.04, side: THREE.DoubleSide, depthWrite: false })
    );
    cone.rotation.x = -Math.PI / 2;
    cone.position.set(0, 3.1, p.range / 2 + 0.3);
    g.add(cone);

    return g;
}

// ================================================================
// GENERATORS: PATHS
// ================================================================

function genPatrolWaypoint(p) {
    const g = new THREE.Group();
    const neonMat = new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan });

    // Sphere marker
    const sphere = new THREE.Mesh(new THREE.SphereGeometry(0.5, 12, 12), neonMat);
    sphere.position.y = 0.5;
    g.add(sphere);

    // Ground ring
    const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.8, 1, 24),
        new THREE.MeshBasicMaterial({ color: TRITIUM_COLORS.cyan, transparent: true, opacity: 0.3, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.05;
    g.add(ring);

    // Direction arrow
    const dir = (p.lookDirection * Math.PI) / 180;
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.2, 0.6, 6), neonMat);
    arrow.position.set(Math.sin(dir) * 1.2, 0.3, Math.cos(dir) * 1.2);
    arrow.rotation.y = -dir;
    arrow.rotation.x = Math.PI / 2;
    g.add(arrow);

    return g;
}

function genObservationPoint(p) {
    const g = new THREE.Group();
    const color = p.priority === 'critical' ? TRITIUM_COLORS.magenta :
                  p.priority === 'high' ? TRITIUM_COLORS.yellow :
                  TRITIUM_COLORS.cyan;
    const neonMat = new THREE.MeshBasicMaterial({ color });

    // Diamond marker
    const diamond = new THREE.Mesh(new THREE.OctahedronGeometry(0.5, 0), neonMat);
    diamond.position.y = 1;
    g.add(diamond);

    // Ground ring
    const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.6, 0.8, 24),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.3, side: THREE.DoubleSide })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.05;
    g.add(ring);

    // Vertical indicator
    const beam = new THREE.Mesh(
        new THREE.CylinderGeometry(0.02, 0.02, 3, 6),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.3 })
    );
    beam.position.y = 1.5;
    g.add(beam);

    return g;
}

// ================================================================
// CATEGORY ICONS (SVG)
// ================================================================

const TRITIUM_CATEGORY_ICONS = {
    cameras: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,9A3,3 0 0,1 15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9Z"/></svg>',
    robots: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12,2A2,2 0 0,1 14,4C14,4.74 13.6,5.39 13,5.73V7H14A7,7 0 0,1 21,14H22A1,1 0 0,1 23,15V18A1,1 0 0,1 22,19H21V20A2,2 0 0,1 19,22H5A2,2 0 0,1 3,20V19H2A1,1 0 0,1 1,18V15A1,1 0 0,1 2,14H3A7,7 0 0,1 10,7H11V5.73C10.4,5.39 10,4.74 10,4A2,2 0 0,1 12,2M7.5,13A2.5,2.5 0 0,0 5,15.5A2.5,2.5 0 0,0 7.5,18A2.5,2.5 0 0,0 10,15.5A2.5,2.5 0 0,0 7.5,13M16.5,13A2.5,2.5 0 0,0 14,15.5A2.5,2.5 0 0,0 16.5,18A2.5,2.5 0 0,0 19,15.5A2.5,2.5 0 0,0 16.5,13Z"/></svg>',
    drones: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M22,11L20,9V5A2,2 0 0,0 18,3H14L12,1L10,3H6A2,2 0 0,0 4,5V9L2,11L4,13V17A2,2 0 0,0 6,19H10L12,21L14,19H18A2,2 0 0,0 20,17V13L22,11M12,17A5,5 0 0,1 7,12A5,5 0 0,1 12,7A5,5 0 0,1 17,12A5,5 0 0,1 12,17Z"/></svg>',
    structures: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12,3L2,12H5V20H19V12H22L12,3Z"/></svg>',
    streets: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M11,16H13V20H11V16M11,10H13V14H11V10M11,4H13V8H11V4M4,22H8V2H4V22M16,2V22H20V2H16Z"/></svg>',
    zones: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12,3L1,9L5,11.18V17.18L12,21L19,17.18V11.18L21,10.09V17H23V9L12,3M18.82,9L12,12.72L5.18,9L12,5.28L18.82,9Z"/></svg>',
    sensors: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M12,2C6.48,2 2,6.48 2,12C2,17.52 6.48,22 12,22C17.52,22 22,17.52 22,12C22,6.48 17.52,2 12,2M12,20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,20 12,20M15,12A3,3 0 0,1 12,15A3,3 0 0,1 9,12A3,3 0 0,1 12,9A3,3 0 0,1 15,12Z"/></svg>',
    paths: '<svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M14,3V5H17.59L7.76,14.83L9.17,16.24L19,6.41V10H21V3M19,19H5V5H12V3H5A2,2 0 0,0 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V12H19V19Z"/></svg>'
};

// ================================================================
// REGISTRATION FUNCTION
// ================================================================

function registerTritiumAssets(registry) {
    // Register categories
    registry.registerCategory('cameras', { name: 'Cameras', icon: TRITIUM_CATEGORY_ICONS.cameras, order: 1 });
    registry.registerCategory('robots', { name: 'Robots', icon: TRITIUM_CATEGORY_ICONS.robots, order: 2 });
    registry.registerCategory('drones', { name: 'Drones', icon: TRITIUM_CATEGORY_ICONS.drones, order: 3 });
    registry.registerCategory('structures', { name: 'Structures', icon: TRITIUM_CATEGORY_ICONS.structures, order: 4 });
    registry.registerCategory('streets', { name: 'Streets', icon: TRITIUM_CATEGORY_ICONS.streets, order: 5 });
    registry.registerCategory('zones', { name: 'Zones', icon: TRITIUM_CATEGORY_ICONS.zones, order: 6 });
    registry.registerCategory('sensors', { name: 'Sensors', icon: TRITIUM_CATEGORY_ICONS.sensors, order: 7 });
    registry.registerCategory('paths', { name: 'Paths', icon: TRITIUM_CATEGORY_ICONS.paths, order: 8 });

    // Generator lookup
    const generators = {
        // Cameras
        security_camera: genSecurityCamera,
        ptz_camera: genPTZCamera,
        dome_camera: genDomeCamera,
        // Robots
        patrol_rover: genPatrolRover,
        interceptor_bot: genInterceptorBot,
        sentry_turret: genSentryTurret,
        // Drones
        recon_drone: genReconDrone,
        heavy_drone: genHeavyDrone,
        scout_drone: genScoutDrone,
        // Streets
        road_straight: genRoadStraight,
        road_curve: genRoadCurve,
        road_tjunction: genTJunction,
        sidewalk: genSidewalk,
        driveway: genDriveway,
        // Zones
        activity_zone: genZoneBox,
        entry_exit_zone: genEntryExitZone,
        tripwire: genTripwire,
        restricted_area: genRestrictedArea,
        // Sensors
        motion_sensor: genMotionSensor,
        microphone_sensor: genMicrophone,
        speaker: genSpeaker,
        floodlight: genFloodlight,
        // Paths
        patrol_waypoint: genPatrolWaypoint,
        observation_point: genObservationPoint
    };

    // Structure generators (share genTritiumStructure)
    const structureGenerators = {
        tritium_house: (p) => genTritiumStructure(p, TRITIUM_COLORS.cyan),
        tritium_garage: (p) => genTritiumStructure(p, TRITIUM_COLORS.cyan),
        tritium_shed: (p) => genTritiumStructure(p, TRITIUM_COLORS.gray),
        tritium_wall: (p) => genTritiumStructure({ width: p.length, depth: p.thickness, height: p.height }, TRITIUM_COLORS.cyan)
    };

    // Register all schemas
    const allSchemas = {
        ...CAMERA_SCHEMAS,
        ...ROBOT_SCHEMAS,
        ...DRONE_SCHEMAS,
        ...STRUCTURE_SCHEMAS,
        ...STREET_SCHEMAS,
        ...ZONE_SCHEMAS,
        ...SENSOR_SCHEMAS,
        ...PATH_SCHEMAS
    };

    for (const [id, schema] of Object.entries(allSchemas)) {
        const gen = structureGenerators[id] || generators[id];
        if (gen) {
            registry.registerAsset(id, schema, (params) => gen(params));
        }
    }

    // Fence and gate have separate generators
    registry.registerAsset('tritium_fence', STRUCTURE_SCHEMAS.tritium_fence, (params) => genTritiumFence(params));
    registry.registerAsset('tritium_gate', STRUCTURE_SCHEMAS.tritium_gate, (params) => genTritiumGate(params));
}

// Dual export pattern
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { registerTritiumAssets, TRITIUM_COLORS };
} else {
    window.TritiumAssets = { registerTritiumAssets, TRITIUM_COLORS };
}
