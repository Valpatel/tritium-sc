// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * WeatherVFX — particle systems for rain/snow and instanced street lights.
 *
 * Rain: instanced cylinder geometry falling from sky, recycling at ground.
 * Street lights: instanced pole + glowing sphere, emissive at night.
 */

const MAX_RAIN_DROPS = 2000;
const MAX_STREET_LIGHTS = 200;
const RAIN_AREA = 200;     // meters radius
const RAIN_HEIGHT = 40;    // drop from this height

export class WeatherVFX {
    constructor() {
        this._rainMesh = null;
        this._lightPoleMesh = null;
        this._lightGlowMesh = null;
        this._rainDrops = [];
        this._lightPositions = [];
        this._initialized = false;
        this._dummy = null;
        this._rainVisible = false;
        this._lightsOn = false;
    }

    /**
     * Initialize VFX meshes and add to scene.
     * @param {THREE} THREE
     * @param {THREE.Scene} scene
     * @param {Array<{x, z}>} streetLightPositions — positions from OSM or road intersections
     */
    init(THREE, scene, streetLightPositions = []) {
        if (this._initialized) return;
        this._dummy = new THREE.Object3D();

        // Rain particles — thin vertical cylinders
        const rainGeo = new THREE.CylinderGeometry(0.02, 0.02, 0.8, 3);
        const rainMat = new THREE.MeshBasicMaterial({
            color: 0x8888cc,
            transparent: true,
            opacity: 0.4,
        });
        this._rainMesh = new THREE.InstancedMesh(rainGeo, rainMat, MAX_RAIN_DROPS);
        this._rainMesh.count = MAX_RAIN_DROPS;
        this._rainMesh.visible = false;
        this._rainMesh.frustumCulled = false;
        scene.add(this._rainMesh);

        // Initialize rain drop positions
        for (let i = 0; i < MAX_RAIN_DROPS; i++) {
            this._rainDrops.push({
                x: (Math.random() - 0.5) * RAIN_AREA * 2,
                y: Math.random() * RAIN_HEIGHT,
                z: (Math.random() - 0.5) * RAIN_AREA * 2,
                speed: 15 + Math.random() * 10,  // 15-25 m/s fall speed
            });
        }

        // Street light poles
        if (streetLightPositions.length > 0) {
            const poleGeo = new THREE.CylinderGeometry(0.08, 0.1, 5.0, 4);
            const poleMat = new THREE.MeshStandardMaterial({ color: 0x444444, roughness: 0.8 });
            const maxLights = Math.min(streetLightPositions.length, MAX_STREET_LIGHTS);

            this._lightPoleMesh = new THREE.InstancedMesh(poleGeo, poleMat, maxLights);
            this._lightPoleMesh.count = maxLights;
            this._lightPoleMesh.castShadow = true;

            const glowGeo = new THREE.SphereGeometry(0.3, 6, 4);
            const glowMat = new THREE.MeshBasicMaterial({
                color: 0xffdd88,
                transparent: true,
                opacity: 0,
            });
            this._lightGlowMesh = new THREE.InstancedMesh(glowGeo, glowMat, maxLights);
            this._lightGlowMesh.count = maxLights;

            for (let i = 0; i < maxLights; i++) {
                const pos = streetLightPositions[i];
                // Pole
                this._dummy.position.set(pos.x, 2.5, pos.z);
                this._dummy.updateMatrix();
                this._lightPoleMesh.setMatrixAt(i, this._dummy.matrix);
                // Glow sphere on top
                this._dummy.position.set(pos.x, 5.2, pos.z);
                this._dummy.updateMatrix();
                this._lightGlowMesh.setMatrixAt(i, this._dummy.matrix);
            }

            this._lightPoleMesh.instanceMatrix.needsUpdate = true;
            this._lightGlowMesh.instanceMatrix.needsUpdate = true;
            scene.add(this._lightPoleMesh);
            scene.add(this._lightGlowMesh);

            this._lightPositions = streetLightPositions.slice(0, maxLights);
        }

        this._initialized = true;
    }

    /**
     * Update VFX state based on weather.
     * @param {number} dt
     * @param {CityWeather} weather
     * @param {number} camX — camera X for rain centering
     * @param {number} camZ — camera Z for rain centering
     */
    update(dt, weather, camX, camZ) {
        if (!this._initialized) return;

        // Rain visibility
        const shouldRain = weather.weather === 'rain';
        if (shouldRain !== this._rainVisible) {
            this._rainMesh.visible = shouldRain;
            this._rainVisible = shouldRain;
        }

        // Animate rain drops
        if (this._rainVisible) {
            for (let i = 0; i < MAX_RAIN_DROPS; i++) {
                const drop = this._rainDrops[i];
                drop.y -= drop.speed * dt;

                // Recycle at ground level
                if (drop.y < 0) {
                    drop.y = RAIN_HEIGHT;
                    drop.x = camX + (Math.random() - 0.5) * RAIN_AREA * 2;
                    drop.z = camZ + (Math.random() - 0.5) * RAIN_AREA * 2;
                }

                this._dummy.position.set(drop.x, drop.y, drop.z);
                this._dummy.updateMatrix();
                this._rainMesh.setMatrixAt(i, this._dummy.matrix);
            }
            this._rainMesh.instanceMatrix.needsUpdate = true;
        }

        // Street lights — glow at night
        if (this._lightGlowMesh) {
            const shouldGlow = weather.streetLightsOn;
            if (shouldGlow !== this._lightsOn) {
                this._lightGlowMesh.material.opacity = shouldGlow ? 0.9 : 0;
                this._lightGlowMesh.material.emissive?.setHex?.(shouldGlow ? 0xffdd44 : 0x000000);
                this._lightsOn = shouldGlow;
            }
        }
    }

    /**
     * Generate street light positions from road intersections.
     * @param {Object} roadNetwork
     * @param {Function} gameToThree — coordinate transform
     * @returns {Array<{x, z}>} positions in Three.js coords
     */
    static generateLightPositions(roadNetwork, gameToThree) {
        if (!roadNetwork) return [];
        const positions = [];

        // Place lights at intersections with degree >= 2
        for (const nodeId in roadNetwork.nodes) {
            const node = roadNetwork.nodes[nodeId];
            if (node.degree >= 2) {
                const tp = gameToThree(node.x, node.z);
                positions.push({ x: tp.x, z: tp.z });
            }
        }

        return positions;
    }
}
