// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * LODManager — Level of Detail system for city rendering.
 *
 * Organizes buildings into sectors (100m x 100m grid). Each sector has
 * geometry at multiple detail levels. Camera distance determines which
 * LOD is visible. Frustum culling hides sectors outside the camera view.
 *
 * LOD Levels:
 *   LoD2 (< 150m): Full geometry + windows + edges
 *   LoD1 (150-400m): Extruded box only, no windows
 *   LoD0 (> 400m): Footprint outline only (lines, no fill)
 *
 * Based on CityJSON LOD levels and Geo-Three tile hierarchies.
 */

const SECTOR_SIZE = 100;  // meters
const LOD2_DISTANCE = 150;
const LOD1_DISTANCE = 400;

export class LODManager {
    constructor() {
        this.sectors = new Map();  // "sx,sz" → Sector
        this._cameraX = 0;
        this._cameraZ = 0;
        this._lastUpdateFrame = 0;
        this._updateInterval = 10;  // update LOD every N frames
        this._frameCount = 0;
    }

    /**
     * Assign a building to its sector.
     * @param {Object} building — { polygon, height, ... }
     * @returns {string} sector key
     */
    assignSector(building) {
        const poly = building.polygon;
        if (!poly || poly.length < 3) return null;

        // Centroid
        let cx = 0, cz = 0;
        for (const [x, z] of poly) { cx += x; cz += z; }
        cx /= poly.length;
        cz /= poly.length;

        const sx = Math.floor(cx / SECTOR_SIZE);
        const sz = Math.floor(cz / SECTOR_SIZE);
        const key = `${sx},${sz}`;

        if (!this.sectors.has(key)) {
            this.sectors.set(key, {
                key,
                cx: (sx + 0.5) * SECTOR_SIZE,
                cz: (sz + 0.5) * SECTOR_SIZE,
                buildings: [],
                lod2Group: null,  // Full detail (Three.js Group)
                lod1Group: null,  // Medium detail
                lod0Group: null,  // Low detail
                currentLOD: -1,
                visible: true,
            });
        }

        this.sectors.get(key).buildings.push(building);
        return key;
    }

    /**
     * Build all sector geometry at all LOD levels.
     * Call after all buildings are assigned.
     *
     * @param {THREE} THREE
     * @param {Function} gameToThree — coordinate transform
     * @param {Object} materials — { building, buildingRoof, buildingEdge, buildingWindow, ... }
     * @param {Object} categoryMats — { residential, commercial, ... }
     * @returns {THREE.Group} root group containing all sectors
     */
    buildGeometry(THREE, gameToThree, materials, categoryMats) {
        const root = new THREE.Group();
        root.name = 'lod-buildings';

        for (const [key, sector] of this.sectors) {
            if (sector.buildings.length === 0) continue;

            // LoD2: Full detail (extrude + windows + edges)
            sector.lod2Group = this._buildLOD2(THREE, gameToThree, sector, materials, categoryMats);
            sector.lod2Group.visible = false;
            root.add(sector.lod2Group);

            // LoD1: Medium detail (extrude only, no windows/edges)
            // Default to LoD1 visible so buildings appear immediately before first LOD update
            sector.lod1Group = this._buildLOD1(THREE, gameToThree, sector, materials);
            sector.lod1Group.visible = true;
            sector.currentLOD = 1;
            root.add(sector.lod1Group);

            // LoD0: Low detail (footprint outlines only)
            sector.lod0Group = this._buildLOD0(THREE, gameToThree, sector, materials);
            sector.lod0Group.visible = false;
            root.add(sector.lod0Group);

            // currentLOD already set to 1 above (LoD1 visible by default)
        }

        return root;
    }

    /**
     * Update LOD visibility based on camera position.
     * Call every frame (internally throttled).
     *
     * @param {number} camX — camera X in game coords
     * @param {number} camZ — camera Z in game coords
     */
    updateLOD(camX, camZ) {
        this._frameCount++;
        if (this._frameCount % this._updateInterval !== 0) return;

        // Guard against NaN camera position
        if (!isFinite(camX) || !isFinite(camZ)) {
            console.warn(`[LODManager] Invalid camera position: (${camX}, ${camZ})`);
            return;
        }

        this._cameraX = camX;
        this._cameraZ = camZ;

        for (const [key, sector] of this.sectors) {
            const dx = sector.cx - camX;
            const dz = sector.cz - camZ;
            const dist = Math.sqrt(dx * dx + dz * dz);

            let targetLOD;
            if (dist < LOD2_DISTANCE) targetLOD = 2;
            else if (dist < LOD1_DISTANCE) targetLOD = 1;
            else targetLOD = 0;

            if (targetLOD !== sector.currentLOD) {
                // Switch LOD
                if (sector.lod2Group) sector.lod2Group.visible = (targetLOD === 2);
                if (sector.lod1Group) sector.lod1Group.visible = (targetLOD === 1);
                if (sector.lod0Group) sector.lod0Group.visible = (targetLOD === 0);
                sector.currentLOD = targetLOD;
            }
        }
    }

    /**
     * Get LOD statistics.
     */
    getStats() {
        let lod0 = 0, lod1 = 0, lod2 = 0, hidden = 0;
        for (const [, sector] of this.sectors) {
            if (sector.currentLOD === 2) lod2++;
            else if (sector.currentLOD === 1) lod1++;
            else if (sector.currentLOD === 0) lod0++;
            else hidden++;
        }
        return { sectors: this.sectors.size, lod0, lod1, lod2, hidden };
    }

    // --- Internal LOD builders ---

    _buildLOD2(THREE, gameToThree, sector, materials, categoryMats) {
        const group = new THREE.Group();
        group.name = `lod2-${sector.key}`;

        const windowTransforms = [];  // Collected for InstancedMesh batching
        const bldgHash = (id) => ((id * 2654435761) >>> 0) % 1000 / 1000;

        for (const bldg of sector.buildings) {
            const poly = bldg.polygon;
            const height = bldg.height || 8;
            const category = bldg.category || 'residential';
            const wallMat = categoryMats[category] || materials.building;
            const hash = bldgHash(bldg.id || 0);

            const shape = new THREE.Shape();
            for (let i = 0; i < poly.length; i++) {
                const [gx, gy] = poly[i];
                if (i === 0) shape.moveTo(gx, gy);
                else shape.lineTo(gx, gy);
            }
            shape.closePath();

            // Extruded walls
            const extGeo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
            const wallMesh = new THREE.Mesh(extGeo, wallMat);
            wallMesh.rotation.x = -Math.PI / 2;
            wallMesh.castShadow = true;
            wallMesh.receiveShadow = true;
            group.add(wallMesh);

            // Roof — gabled for small residential, flat for commercial/tall
            const roofShape = bldg.roof_shape || '';
            const isGabled = (roofShape === 'gabled' || roofShape === 'hipped') ||
                (category === 'residential' && height < 12 && !roofShape && hash < 0.7);

            if (isGabled && poly.length >= 4) {
                // Gabled roof: triangular prism along longest axis
                // Find bounding box to determine ridge direction
                let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
                for (const [px, pz] of poly) {
                    minX = Math.min(minX, px); maxX = Math.max(maxX, px);
                    minZ = Math.min(minZ, pz); maxZ = Math.max(maxZ, pz);
                }
                const bw = maxX - minX, bd = maxZ - minZ;
                const ridgeHeight = Math.min(3, Math.max(1.5, Math.min(bw, bd) * 0.3));
                const ridgeAlongX = bw > bd;

                // Simple gable: two triangular faces + two rectangular slopes
                const roofGeo = new THREE.BufferGeometry();
                const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2;
                const tp00 = gameToThree(minX, minZ);
                const tp10 = gameToThree(maxX, minZ);
                const tp01 = gameToThree(minX, maxZ);
                const tp11 = gameToThree(maxX, maxZ);

                let ridgePts;
                if (ridgeAlongX) {
                    // Ridge runs along X axis
                    const tpR0 = gameToThree(minX, cz);
                    const tpR1 = gameToThree(maxX, cz);
                    ridgePts = [
                        // South slope
                        tp00.x, height, tp00.z, tp10.x, height, tp10.z, tpR1.x, height + ridgeHeight, tpR1.z,
                        tp00.x, height, tp00.z, tpR1.x, height + ridgeHeight, tpR1.z, tpR0.x, height + ridgeHeight, tpR0.z,
                        // North slope
                        tp01.x, height, tp01.z, tpR0.x, height + ridgeHeight, tpR0.z, tpR1.x, height + ridgeHeight, tpR1.z,
                        tp01.x, height, tp01.z, tpR1.x, height + ridgeHeight, tpR1.z, tp11.x, height, tp11.z,
                    ];
                } else {
                    // Ridge runs along Z axis
                    const tpR0 = gameToThree(cx, minZ);
                    const tpR1 = gameToThree(cx, maxZ);
                    ridgePts = [
                        tp00.x, height, tp00.z, tpR0.x, height + ridgeHeight, tpR0.z, tpR1.x, height + ridgeHeight, tpR1.z,
                        tp00.x, height, tp00.z, tpR1.x, height + ridgeHeight, tpR1.z, tp01.x, height, tp01.z,
                        tp10.x, height, tp10.z, tpR1.x, height + ridgeHeight, tpR1.z, tpR0.x, height + ridgeHeight, tpR0.z,
                        tp10.x, height, tp10.z, tp11.x, height, tp11.z, tpR1.x, height + ridgeHeight, tpR1.z,
                    ];
                }

                roofGeo.setAttribute('position', new THREE.Float32BufferAttribute(ridgePts, 3));
                roofGeo.computeVertexNormals();
                const roofMat = materials.buildingRoof.clone();
                roofMat.color.setHex(0x3a2020);  // Dark brownish for gabled
                const roofMesh = new THREE.Mesh(roofGeo, roofMat);
                roofMesh.receiveShadow = true;
                group.add(roofMesh);
            } else {
                // Flat roof (default)
                const roofGeo = new THREE.ShapeGeometry(shape);
                const roofMesh = new THREE.Mesh(roofGeo, materials.buildingRoof);
                roofMesh.rotation.x = -Math.PI / 2;
                roofMesh.position.y = height;
                roofMesh.receiveShadow = true;
                group.add(roofMesh);
            }

            // Edge outlines
            const outlineGround = [], outlineRoof = [];
            for (const [gx, gy] of poly) {
                const tp = gameToThree(gx, gy);
                outlineGround.push(new THREE.Vector3(tp.x, 0.15, tp.z));
                outlineRoof.push(new THREE.Vector3(tp.x, height, tp.z));
            }
            if (outlineGround.length > 0) {
                outlineGround.push(outlineGround[0].clone());
                outlineRoof.push(outlineRoof[0].clone());
            }
            group.add(new THREE.Line(
                new THREE.BufferGeometry().setFromPoints(outlineGround), materials.buildingEdge));
            group.add(new THREE.Line(
                new THREE.BufferGeometry().setFromPoints(outlineRoof), materials.buildingEdge));

            // Collect window transforms for batching via InstancedMesh
            if (height > 4 && category !== 'utility' && materials.buildingWindow) {
                const floors = Math.floor(height / 3);
                for (let ei = 0; ei < poly.length; ei++) {
                    const [ax, ay] = poly[ei];
                    const [bx, by] = poly[(ei + 1) % poly.length];
                    const wallLen = Math.sqrt((bx - ax) ** 2 + (by - ay) ** 2);
                    if (wallLen < 3) continue;

                    const dx = (bx - ax) / wallLen;
                    const dy = (by - ay) / wallLen;
                    const nx = -dy, ny = dx;
                    const winSpacing = category === 'commercial' ? 2.5 : 3.5;
                    const numWins = Math.max(1, Math.floor((wallLen - 2) / winSpacing));

                    for (let f = 0; f < floors; f++) {
                        const wy = f * 3 + 2;
                        if (wy > height - 1.5) break;
                        for (let w = 0; w < numWins; w++) {
                            const wHash = bldgHash((bldg.id || 0) + ei * 100 + f * 10 + w);
                            if (wHash > 0.65) continue;

                            const t = (w + 1) / (numWins + 1);
                            const wx = ax + dx * wallLen * t + nx * 0.05;
                            const wz = ay + dy * wallLen * t + ny * 0.05;
                            const tp = gameToThree(wx, wz);
                            const rotY = Math.atan2(nx, -ny);

                            windowTransforms.push({ x: tp.x, y: wy, z: tp.z, rotY });
                        }
                    }
                }
            }
        }

        // Batch all windows into a single InstancedMesh
        if (windowTransforms.length > 0 && materials.buildingWindow) {
            const winGeo = new THREE.PlaneGeometry(1.0, 1.2);
            const winInstanced = new THREE.InstancedMesh(winGeo, materials.buildingWindow, windowTransforms.length);
            const dummy = new THREE.Object3D();
            for (let i = 0; i < windowTransforms.length; i++) {
                const wt = windowTransforms[i];
                dummy.position.set(wt.x, wt.y, wt.z);
                dummy.rotation.set(0, wt.rotY, 0);
                dummy.updateMatrix();
                winInstanced.setMatrixAt(i, dummy.matrix);
            }
            winInstanced.instanceMatrix.needsUpdate = true;
            group.add(winInstanced);
        }

        return group;
    }

    _buildLOD1(THREE, gameToThree, sector, materials) {
        const group = new THREE.Group();
        group.name = `lod1-${sector.key}`;

        for (const bldg of sector.buildings) {
            const poly = bldg.polygon;
            const height = bldg.height || 8;

            const shape = new THREE.Shape();
            for (let i = 0; i < poly.length; i++) {
                const [gx, gy] = poly[i];
                if (i === 0) shape.moveTo(gx, gy);
                else shape.lineTo(gx, gy);
            }
            shape.closePath();

            // Simple extrusion only — no windows, no edges
            const extGeo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
            const mesh = new THREE.Mesh(extGeo, materials.building);
            mesh.rotation.x = -Math.PI / 2;
            group.add(mesh);
        }

        return group;
    }

    _buildLOD0(THREE, gameToThree, sector, materials) {
        const group = new THREE.Group();
        group.name = `lod0-${sector.key}`;

        // Footprint outlines only — very cheap
        for (const bldg of sector.buildings) {
            const poly = bldg.polygon;
            if (poly.length < 3) continue;

            const pts = poly.map(([gx, gy]) => {
                const tp = gameToThree(gx, gy);
                return new THREE.Vector3(tp.x, 0.2, tp.z);
            });
            pts.push(pts[0].clone());

            const geo = new THREE.BufferGeometry().setFromPoints(pts);
            group.add(new THREE.Line(geo, materials.buildingEdge));
        }

        return group;
    }
}
