// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * CitySimManager — orchestrates city simulation in the SC Command Center.
 *
 * Fetches city-data, builds RoadNetwork, spawns vehicles with IDM physics,
 * and manages rendering via InstancedMesh. Called from map3d render loop.
 *
 * Usage:
 *   const mgr = new CitySimManager();
 *   await mgr.loadCityData(lat, lng, radius);
 *   mgr.spawnVehicles(100);
 *   mgr.tick(dt);  // every frame
 *   mgr.updateRendering(THREE, gameToThree);  // every frame
 */

import { RoadNetwork } from '/lib/sim/road-network.js';
import { ROAD_SPEEDS } from '/lib/sim/idm.js';
import { EventBus } from '/lib/events.js';
import { SimVehicle } from '/lib/sim/vehicle.js';
import { TrafficControllerManager } from '/lib/sim/traffic-controller.js';
import { SimPedestrian, PED_COLORS } from '/lib/sim/pedestrian.js';
import { SensorBridge } from './sensor-bridge.js';
import { CityWeather } from '/lib/sim/weather.js';
import { AnomalyDetector } from './anomaly-detector.js';
import { SpatialGrid } from '/lib/sim/spatial-grid.js';
import { AmbientSoundBridge } from './ambient-sound.js';
import { loadScenario as _loadScenario, getScenarioById } from './scenario-loader.js';
import { RLHooks } from './rl-hooks.js';
import { buildIdentity } from '/lib/sim/identity.js';
import { ProtestManager } from './protest-manager.js';
import { EventDirector } from './event-director.js';

export class CitySimManager {
    constructor() {
        this.roadNetwork = null;
        this.cityData = null;
        this.loaded = false;
        this.loading = false;
        this.running = false;

        // Traffic controllers
        this.trafficMgr = null;

        // Vehicles
        this.vehicles = [];
        this.maxVehicles = 200;

        // Pedestrians
        this.pedestrians = [];
        this.maxPedestrians = 100;
        this.simHour = 7; // 7am
        this.simDay = 0;  // 0=Monday, 5=Saturday, 6=Sunday
        this.timeScale = 60; // 1 real second = 1 sim minute

        // Weather and time
        this.weather = new CityWeather();

        // Anomaly detection
        this.anomalyDetector = new AnomalyDetector();

        // Spatial grid for O(1) proximity queries
        this._spatialGrid = new SpatialGrid(20);

        // RL hooks for traffic signal optimization
        this.rlHooks = null;  // Initialized after trafficMgr is ready

        // Sensor bridge — enabled by default so sim entities feed the target tracker
        this.sensorBridge = new SensorBridge();
        this.sensorBridge.enabled = true;

        // Building occupancy tracking
        this.buildingOccupancy = new Map(); // buildingId → Set<npcId>

        // Protest/riot engine
        this.protestManager = new ProtestManager();

        // Event director — schedules city-wide events
        this.eventDirector = new EventDirector();
        this.eventDirector.bind(this);

        // Ambient sound events
        this.ambientSound = new AmbientSoundBridge();

        // Congestion tracking — avgSpeed per edge, updated every 2s
        this._congestionMap = new Map(); // edgeId → {totalSpeed, count, avgSpeed, ratio}
        this._congestionTimer = 0;

        // Telemetry sender — POST positions to backend every 500ms
        this._telemetryTimer = 0;

        // Rendering state
        this._carMesh = null;
        this._pedMesh = null;
        this._signalMesh = null;
        this._carCount = 0;
        this._dummy = null;
        this._color = null;
    }

    /**
     * Load city data and build road network.
     */
    async loadCityData(lat, lng, radius = 300) {
        if (this.loading) return false;
        this.loading = true;

        try {
            // Try OSM city-data with 8s timeout, fall back to procedural demo-city
            let resp;
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 8000);
            try {
                resp = await fetch(`/api/geo/city-data?lat=${lat}&lng=${lng}&radius=${radius}`, { signal: controller.signal });
                clearTimeout(timeout);
            } catch (e) {
                clearTimeout(timeout);
                if (e.name === 'AbortError') {
                    console.warn('[CitySimManager] OSM fetch timed out, using procedural city');
                }
                // Fallback to procedural city
                resp = await fetch(`/api/city-sim/demo-city?radius=${radius}&seed=${Math.floor(lat * 1000)}`);
            }
            if (!resp.ok) {
                console.warn(`[CitySimManager] city-data fetch failed: ${resp.status}`);
                return false;
            }
            this.cityData = await resp.json();

            this.roadNetwork = new RoadNetwork();
            this.roadNetwork.buildFromOSM(this.cityData.roads || []);

            const stats = this.roadNetwork.stats();
            console.log(
                `[CitySimManager] Road network: ${stats.nodes} nodes, ${stats.edges} edges, ` +
                `${stats.totalLengthM}m total`
            );

            // Initialize traffic controllers at intersections (default: adaptive)
            this.trafficMgr = new TrafficControllerManager();
            this.trafficMgr.initFromNetwork(this.roadNetwork);
            this.trafficMgr.setMode('adaptive');

            // Initialize RL hooks for traffic signal optimization
            this.rlHooks = new RLHooks(this.trafficMgr, this.roadNetwork);

            // Classify buildings by type for NPC/vehicle assignment
            this._classifyBuildings();

            this.loaded = true;
            return true;
        } catch (e) {
            console.error('[CitySimManager] Load failed:', e);
            return false;
        } finally {
            this.loading = false;
        }
    }

    /**
     * Spawn N vehicles on random road edges.
     */
    spawnVehicles(count) {
        if (!this.roadNetwork || this.roadNetwork.edges.length === 0) return 0;

        const toSpawn = Math.min(count, this.maxVehicles - this.vehicles.length);
        let spawned = 0;

        // Track occupied positions per edge to avoid spawning on top of each other
        const edgeOccupancy = new Map(); // edgeId → [u positions]
        for (const v of this.vehicles) {
            if (!v.edge) continue;
            if (!edgeOccupancy.has(v.edge.id)) edgeOccupancy.set(v.edge.id, []);
            edgeOccupancy.get(v.edge.id).push(v.u);
        }

        for (let i = 0; i < toSpawn; i++) {
            const edge = this.roadNetwork.randomEdge();
            if (!edge) continue;

            // Find a clear spot on this edge (at least 8m from any other vehicle)
            const occupied = edgeOccupancy.get(edge.id) || [];
            let u = Math.random() * edge.length * 0.8 + edge.length * 0.1;
            let clear = true;
            for (const ou of occupied) {
                if (Math.abs(u - ou) < 8) { clear = false; break; }
            }
            // If overlapping, try a few more positions
            if (!clear) {
                for (let attempt = 0; attempt < 5; attempt++) {
                    u = Math.random() * edge.length * 0.8 + edge.length * 0.1;
                    clear = true;
                    for (const ou of occupied) {
                        if (Math.abs(u - ou) < 8) { clear = false; break; }
                    }
                    if (clear) break;
                }
                if (!clear) continue; // Skip this edge, too crowded
            }

            const car = new SimVehicle(edge, u, this.roadNetwork);

            // Assign vehicle purpose and identity
            const identity = buildIdentity(car.id, 'vehicle');
            car._identity = identity;

            // Distribute purposes: 50% commute, 10% delivery, 10% taxi, 5% patrol, 25% random
            const purposeRoll = Math.random();
            if (purposeRoll < 0.50 && this._buildingsByType) {
                car.purpose = 'commute';
                // Pick home and work buildings
                const homes = this._buildingsByType.residential;
                const works = this._buildingsByType.commercial;
                if (homes.length > 0 && works.length > 0) {
                    const home = homes[i % homes.length];
                    const work = works[i % works.length];
                    car.destination = { x: work.x, z: work.z, buildingId: work.buildingId };
                    car._homePos = { x: home.x, z: home.z };
                    car._workPos = { x: work.x, z: work.z };
                }
            } else if (purposeRoll < 0.60 && this._buildingsByType) {
                car.purpose = 'delivery';
                const homes = this._buildingsByType.residential;
                const works = this._buildingsByType.commercial;
                car._deliveryTargets = [
                    works[Math.floor(Math.random() * works.length)],
                    homes[Math.floor(Math.random() * homes.length)],
                    works[Math.floor(Math.random() * works.length)],
                    homes[Math.floor(Math.random() * homes.length)],
                ];
                car._deliveryIdx = 0;
                car.color = 0xffcc44; // yellow for delivery
            } else if (purposeRoll < 0.70) {
                car.purpose = 'taxi';
                car.color = 0xfcee0a; // bright yellow for taxi
            } else if (purposeRoll < 0.75) {
                car.purpose = 'patrol';
                car.color = 0x4488ff; // blue for police patrol
            } else {
                car.purpose = 'random';
            }

            car._planNewRoute();
            this.vehicles.push(car);
            if (!edgeOccupancy.has(edge.id)) edgeOccupancy.set(edge.id, []);
            edgeOccupancy.get(edge.id).push(u);
            spawned++;
        }

        if (spawned > 0) {
            this.running = true;
            const purposes = {};
            for (const v of this.vehicles) {
                purposes[v.purpose] = (purposes[v.purpose] || 0) + 1;
            }
            console.log(`[CitySimManager] Spawned ${spawned} vehicles (total: ${this.vehicles.length}). Purposes: ${JSON.stringify(purposes)}`);
            EventBus.emit('city-sim:vehicles-spawned', { count: spawned, total: this.vehicles.length });
        }
        return spawned;
    }

    /**
     * Spawn an emergency vehicle (ambulance/fire/police).
     */
    spawnEmergency() {
        if (!this.roadNetwork || this.roadNetwork.edges.length === 0) return null;
        const edge = this.roadNetwork.randomEdge();
        if (!edge) return null;

        const car = new SimVehicle(edge, 0, this.roadNetwork);
        car.isEmergency = true;
        car.sirenActive = true;
        car.color = 0xff2a6d;
        car.idm.v0 = 20;
        car.idm.a = 2.5;
        car.idm.T = 1.0;
        car._planNewRoute();
        this.vehicles.push(car);
        this.running = true;

        EventBus.emit('city-sim:emergency-spawned', { id: car.id });
        console.log(`[CitySimManager] Emergency vehicle spawned: ${car.id}`);
        return car;
    }

    /**
     * Spawn N pedestrians at random building entries, with identity and role.
     */
    spawnPedestrians(count) {
        const buildings = this.cityData?.buildings || [];
        if (buildings.length < 2) return 0;

        // Classify buildings by type for home/work assignment
        if (!this._buildingsByType) this._classifyBuildings();

        const residential = this._buildingsByType.residential;
        const workplaces = this._buildingsByType.commercial;
        const allEntries = [...residential, ...workplaces];
        if (allEntries.length < 2) return 0;

        const toSpawn = Math.min(count, this.maxPedestrians - this.pedestrians.length);
        let spawned = 0;
        const startIdx = this.pedestrians.length;

        for (let i = 0; i < toSpawn; i++) {
            const pedIdx = startIdx + i;

            // Build deterministic identity from ID
            const identity = buildIdentity(`ped_${pedIdx}`, 'person');

            // Assign home (residential) and work (commercial) buildings
            const homeEntry = residential[pedIdx % residential.length];
            const workEntry = workplaces[pedIdx % workplaces.length];

            const ped = new SimPedestrian(homeEntry.x, homeEntry.z, homeEntry, workEntry, {
                name: identity.fullName,
                homeBuildingId: homeEntry.buildingId,
                workBuildingId: workEntry.buildingId,
                // Personality is randomized per NPC but seeded by identity
                hardship: parseFloat('0.' + identity.shortId.slice(0, 2)) + Math.random() * 0.3,
                riskAversion: parseFloat('0.' + identity.shortId.slice(2, 4)) + Math.random() * 0.3,
                sociability: parseFloat('0.' + identity.shortId.slice(4, 6)) + Math.random() * 0.3,
            });

            this.pedestrians.push(ped);
            spawned++;
        }

        if (spawned > 0) {
            // Log a sample for verification
            const sample = this.pedestrians[startIdx];
            console.log(
                `[CitySimManager] Spawned ${spawned} pedestrians (total: ${this.pedestrians.length}). ` +
                `Sample: ${sample.name} (${sample.role}) home=Bldg#${sample.homeBuildingId}, work=Bldg#${sample.workBuildingId}`
            );
        }
        return spawned;
    }

    /**
     * Remove all vehicles and pedestrians, stop simulation.
     */
    clearVehicles() {
        this.vehicles = [];
        this.pedestrians = [];
        this.running = false;
        if (this._carMesh) {
            this._carMesh.count = 0;
            this._carMesh.instanceMatrix.needsUpdate = true;
            // Clear GPU color buffer to prevent memory leak
            if (this._carMesh.instanceColor?.array) {
                this._carMesh.instanceColor.array.fill(0);
                this._carMesh.instanceColor.needsUpdate = true;
            }
        }
        if (this._pedMesh) {
            this._pedMesh.count = 0;
            this._pedMesh.instanceMatrix.needsUpdate = true;
            // Clear GPU color buffer
            if (this._pedMesh.instanceColor?.array) {
                this._pedMesh.instanceColor.array.fill(0);
                this._pedMesh.instanceColor.needsUpdate = true;
            }
        }
    }

    /**
     * Simulation tick — uses fixed timestep for physics stability.
     * Accumulates render dt and steps at 10Hz (0.1s intervals).
     * Render interpolation keeps visuals smooth between physics steps.
     *
     * @param {number} dt — render frame delta time in seconds
     */
    tick(dt) {
        if (!this.running || (!this.vehicles.length && !this.pedestrians.length)) return;

        const realDt = Math.min(dt, 0.5); // cap at 0.5s to prevent huge jumps

        // Fixed timestep accumulator (10Hz physics)
        const FIXED_DT = 0.1;
        this._accumulator = (this._accumulator || 0) + Math.min(dt, 2.0);

        // Step physics at fixed rate (max 15 steps per frame to catch up on throttled ticks)
        let steps = 0;
        while (this._accumulator >= FIXED_DT && steps < 15) {
            this._tickPhysics(FIXED_DT);
            this._accumulator -= FIXED_DT;
            steps++;
        }

        // Advance sim time using real dt (not capped by physics steps)
        // This ensures time/events progress even when physics is throttled
        if (steps === 0 && realDt > 0.05) {
            // No physics steps this frame but time still passes
            this.simHour += (realDt * this.timeScale) / 3600;
            if (this.simHour >= 24) {
                this.simHour -= 24;
                this.simDay = (this.simDay || 0) + 1;
            }
            // Tick event-driven systems with real dt
            if (this.protestManager.active) {
                this.protestManager.tick(realDt, this.pedestrians, this.vehicles);
            }
            this.eventDirector.tick(realDt, this.simHour);
        }
    }

    /**
     * Internal physics step at fixed timestep.
     * @param {number} dt — fixed timestep (0.1s)
     */
    _tickPhysics(dt) {
        const clampedDt = dt;

        // Update queue counts and tick traffic controllers
        if (this.trafficMgr) {
            this.trafficMgr.updateQueues(this.vehicles);
            this.trafficMgr.tick(clampedDt);
        }

        // Rebuild spatial grid for O(1) proximity queries
        this._spatialGrid.clear();
        for (const car of this.vehicles) {
            if (!car.parked) this._spatialGrid.insert(car);
        }
        for (const ped of this.pedestrians) {
            if (!ped.inBuilding) this._spatialGrid.insert(ped);
        }

        // Tick vehicles with traffic awareness
        for (const car of this.vehicles) {
            // Check if approaching a red light
            if (this.trafficMgr && car.edge) {
                const approachNode = car.direction > 0 ? car.edge.to : car.edge.from;
                const remaining = car.direction > 0 ? car.edge.length - car.u : car.u;

                if (remaining < 25 && remaining > 2) {
                    if (!this.trafficMgr.isGreen(approachNode, car.edge.id)) {
                        // Red light: add virtual obstacle at stop line
                        car._redLightGap = remaining - 3;  // stop 3m before intersection
                        car._redLightActive = true;
                    } else {
                        car._redLightActive = false;
                    }
                } else {
                    car._redLightActive = false;
                }
            }

            // Pass weather speed modifier, sim hour, weekend flag, and nearby vehicles
            car._weatherSpeedMult = this.weather.speedMultiplier;
            car._simHour = this.simHour;
            car._isWeekend = (this.simDay % 7) >= 5;
            const nearbyVehicles = this._spatialGrid.getNearby(car.x, car.z);
            car.tick(clampedDt, nearbyVehicles);
        }

        // Collision detection — momentum-based physics with real mass
        const _checked = new Set();
        for (const car of this.vehicles) {
            if (!car.alive || car.parked || car.inAccident || car._collisionCooldown > 0) continue;
            const nearby = this._spatialGrid.getNearby(car.x, car.z);

            // Vehicle-vehicle collisions
            for (const other of nearby) {
                if (other === car || !other.alive || other.parked || other.inAccident || other._collisionCooldown > 0) continue;
                if (!other.edge || !car.edge) continue;

                // Deduplicate pair check
                const pairKey = car.id < other.id ? `${car.id}|${other.id}` : `${other.id}|${car.id}`;
                if (_checked.has(pairKey)) continue;
                _checked.add(pairKey);

                // Skip if this isn't a vehicle (might be a pedestrian in spatial grid)
                if (!other.mass) continue;

                // Distance between vehicle centers
                const dx = car.x - other.x;
                const dz = car.z - other.z;
                const dist = Math.sqrt(dx * dx + dz * dz);

                // Contact distance based on actual vehicle dimensions
                const minSafe = (car.length + other.length) / 2;
                const overlap = minSafe - dist;

                if (overlap > 0) {
                    // Apply momentum-based collision response
                    const collided = car.applyCollision(other, overlap);
                    if (collided) {
                        const impactSpeed = Math.abs(car.speed + other.speed);
                        const severity = impactSpeed > 10 ? 'CRASH' : impactSpeed > 5 ? 'collision' : 'bump';
                        // Only log serious collisions to console (bumps are too frequent)
                        if (severity !== 'bump') {
                            console.log(`[CitySimManager] ${severity}: ${car.id} <-> ${other.id} at ${impactSpeed.toFixed(1)}m/s`);
                        }
                        // Auto-dispatch emergency for serious crashes
                        if (severity === 'CRASH') {
                            this._dispatchEmergencyToScene((car.x + other.x) / 2, (car.z + other.z) / 2);
                        }

                        // Only emit events for collisions and crashes (not minor bumps)
                        if (severity !== 'bump') {
                        EventBus.emit('city-sim:collision', {
                            vehicle1: car.id,
                            vehicle2: other.id,
                            x: (car.x + other.x) / 2,
                            z: (car.z + other.z) / 2,
                            severity,
                            impactSpeed,
                            mass1: car.mass,
                            mass2: other.mass,
                        });
                        } // end severity !== 'bump'
                    }
                }
            }

            // Vehicle-pedestrian collisions
            for (const entity of nearby) {
                if (!entity.id?.startsWith('ped_') || entity.inBuilding || entity.stunTimer > 0) continue;
                const dx = car.x - entity.x;
                const dz = car.z - entity.z;
                const dist = Math.sqrt(dx * dx + dz * dz);

                if (dist < (car.width / 2 + 0.4)) {
                    const knockForce = car.applyPedestrianCollision(entity);
                    console.log(`[CitySimManager] Vehicle-pedestrian: ${car.id} hit ${entity.id} (force=${knockForce.toFixed(1)})`);
                    EventBus.emit('city-sim:ped-collision', {
                        vehicleId: car.id,
                        pedId: entity.id,
                        x: entity.x,
                        z: entity.z,
                        force: knockForce,
                    });
                }
            }
        }

        // Advance simulation time (1 real second = timeScale sim seconds)
        this.simHour += (clampedDt * this.timeScale) / 3600;
        if (this.simHour >= 24) {
            this.simHour -= 24;
            this.simDay = (this.simDay || 0) + 1;
        }

        // Tick pedestrians with spatial grid for O(1) nearby queries
        for (const ped of this.pedestrians) {
            const nearby = this._spatialGrid.getNearby(ped.x, ped.z);
            const nearbyPeds = nearby.filter(e => e.id?.startsWith('ped_'));
            const nearbyVehicles = nearby.filter(e => !e.id?.startsWith('ped_') && !e.parked);
            ped.tick(clampedDt, this.simHour, nearbyPeds, nearbyVehicles);
        }

        // Taxi dispatch — match waiting NPCs to idle taxis
        this._tickTaxis(clampedDt);

        // Spontaneous micro-gatherings (check once per sim hour)
        this._gatheringTimer = (this._gatheringTimer || 0) + clampedDt;
        if (this._gatheringTimer > 360) { // every ~6 min real time at 60x
            this._gatheringTimer = 0;
            this._trySpawnGathering();
        }

        // Event director — check scheduled/random events
        this.eventDirector.tick(clampedDt, this.simHour);

        // Protest engine tick
        if (this.protestManager?.active) {
            this.protestManager.tick(clampedDt, this.pedestrians, this.vehicles);
        }

        // Weather and time-of-day
        this.weather.update(this.simHour, clampedDt);

        // Anomaly detection
        if (this.anomalyDetector.enabled) {
            const newAnomalies = this.anomalyDetector.tick(
                clampedDt, this.simHour, this.vehicles, this.pedestrians, this.roadNetwork
            );
            if (newAnomalies.length > 0) {
                // Rate-limit anomaly alerts — max 1 per 30 seconds
                const now = Date.now();
                if (!this._lastAnomalyAlert || now - this._lastAnomalyAlert > 30000) {
                    this._lastAnomalyAlert = now;
                    const topAnomaly = newAnomalies[0];
                    console.log(`[CitySimManager] ${newAnomalies.length} anomalies detected`);
                    EventBus.emit('city-sim:anomaly', topAnomaly);
                    EventBus.emit('alert:new', {
                        id: topAnomaly.id,
                        type: 'city_sim_anomaly',
                        level: topAnomaly.confidence > 0.8 ? 'warning' : 'info',
                        title: `City Sim: ${topAnomaly.type}`,
                        message: topAnomaly.description,
                        position: { x: topAnomaly.x, z: topAnomaly.z },
                        timestamp: topAnomaly.timestamp,
                        source: 'city_sim',
                    });
                }
            }
        }

        // Sensor bridge — generate synthetic BLE/WiFi sightings from sim entities
        if (this.sensorBridge.enabled) {
            const { sightings, detections } = this.sensorBridge.tick(clampedDt, this.vehicles, this.pedestrians);
            if (sightings.length > 0 || detections.length > 0) {
                EventBus.emit('sim:sighting_batch', { sightings, detections });
            }
        }

        // Congestion tracking — recompute every 2 seconds
        this._congestionTimer += clampedDt;
        if (this._congestionTimer >= 2.0) {
            this._congestionTimer = 0;
            this._updateCongestion();
        }

        // Ambient sound events
        this.ambientSound.tick(clampedDt, this.vehicles, this.pedestrians, this.weather);

        // Telemetry sender — POST entity positions to backend every 500ms
        this._telemetryTimer += clampedDt;
        if (this._telemetryTimer >= 0.5) {
            this._telemetryTimer = 0;
            this._sendTelemetry();
        }
    }

    /**
     * POST vehicle and pedestrian positions to /api/city-sim/telemetry.
     * Fire-and-forget — errors are silently ignored.
     */
    _sendTelemetry() {
        const vehicles = [];
        for (const car of this.vehicles) {
            if (car.parked) continue;
            vehicles.push({
                id: car.id,
                x: car.x,
                z: car.z,
                speed: car.speed,
                heading: car.heading,
                type: car._identity?.vehicleDesc || car.subtype || 'sedan',
                purpose: car.purpose || 'random',
            });
        }

        const pedestrians = [];
        for (const ped of this.pedestrians) {
            if (ped.inBuilding || !ped.visible) continue;
            pedestrians.push({
                id: ped.id,
                x: ped.x,
                z: ped.z,
                speed: ped.speed,
                heading: ped.heading,
            });
        }

        if (vehicles.length === 0 && pedestrians.length === 0) return;

        fetch('/api/city-sim/telemetry', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ vehicles, pedestrians }),
        }).catch(() => {});
    }

    /**
     * Compute per-edge congestion from current vehicle speeds.
     */
    _updateCongestion() {
        // Accumulate speeds per edge
        const edgeData = new Map();
        for (const car of this.vehicles) {
            if (!car.edge || car.parked) continue;
            const eid = car.edge.id;
            if (!edgeData.has(eid)) {
                edgeData.set(eid, { totalSpeed: 0, count: 0, speedLimit: car.edge.speedLimit || ROAD_SPEEDS[car.edge.roadClass] || 10 });
            }
            const d = edgeData.get(eid);
            d.totalSpeed += car.speed;
            d.count++;
        }

        // Compute ratio for each edge with vehicles
        this._congestionMap.clear();
        for (const [eid, d] of edgeData) {
            const avgSpeed = d.totalSpeed / d.count;
            const ratio = Math.min(avgSpeed / d.speedLimit, 1.0);
            this._congestionMap.set(eid, { avgSpeed, count: d.count, ratio });
        }
    }

    /**
     * Get congestion data for external use (panels, overlays).
     * @returns {Map<string, {avgSpeed: number, count: number, ratio: number}>}
     */
    getCongestionData() {
        return this._congestionMap;
    }

    /**
     * Initialize InstancedMesh for vehicle rendering.
     * Call once after Three.js is available.
     *
     * @param {THREE} THREE
     * @param {THREE.Scene} scene
     */
    initRendering(THREE, scene) {
        if (this._carMesh) return;

        // Simple car body: box
        const geo = new THREE.BoxGeometry(1.8, 1.2, 4.0);
        const mat = new THREE.MeshStandardMaterial({
            color: 0x888888,
            roughness: 0.6,
            metalness: 0.3,
        });

        this._carMesh = new THREE.InstancedMesh(geo, mat, this.maxVehicles);
        this._carMesh.count = 0;
        this._carMesh.castShadow = true;
        this._carMesh.frustumCulled = false;
        this._carMesh.name = 'city-sim-vehicles';

        // Pre-allocate instance colors
        const colors = new Float32Array(this.maxVehicles * 3);
        this._carMesh.instanceColor = new THREE.InstancedBufferAttribute(colors, 3);

        scene.add(this._carMesh);

        this._dummy = new THREE.Object3D();
        this._color = new THREE.Color();

        // Pedestrian mesh: capsule (cylinder + hemisphere)
        const pedGeo = new THREE.CylinderGeometry(0.25, 0.25, 1.4, 6);
        const pedMat = new THREE.MeshStandardMaterial({
            color: 0x44aa66,
            roughness: 0.7,
        });
        this._pedMesh = new THREE.InstancedMesh(pedGeo, pedMat, this.maxPedestrians);
        this._pedMesh.count = 0;
        this._pedMesh.castShadow = true;
        this._pedMesh.frustumCulled = false;
        this._pedMesh.name = 'city-sim-pedestrians';

        const pedColors = new Float32Array(this.maxPedestrians * 3);
        this._pedMesh.instanceColor = new THREE.InstancedBufferAttribute(pedColors, 3);
        scene.add(this._pedMesh);

        // Vehicle headlight cones (2 per vehicle, visible at night)
        const hlGeo = new THREE.ConeGeometry(1.5, 8, 6);
        hlGeo.rotateX(Math.PI / 2);  // Point forward
        hlGeo.translate(0, 0, 5);     // Offset ahead of car
        const hlMat = new THREE.MeshBasicMaterial({
            color: 0xffffaa,
            transparent: true,
            opacity: 0,  // Start invisible, controlled by weather
            depthWrite: false,
            side: THREE.DoubleSide,
        });
        this._hlMesh = new THREE.InstancedMesh(hlGeo, hlMat, this.maxVehicles * 2);
        this._hlMesh.count = 0;
        this._hlMesh.frustumCulled = false;
        this._hlMesh.name = 'city-sim-headlights';
        scene.add(this._hlMesh);

        // Brake light indicators (2 small red spheres at rear)
        const blGeo = new THREE.SphereGeometry(0.15, 4, 3);
        const blMat = new THREE.MeshBasicMaterial({
            color: 0xff0000,
            transparent: true,
            opacity: 0,
        });
        this._blMesh = new THREE.InstancedMesh(blGeo, blMat, this.maxVehicles * 2);
        this._blMesh.count = 0;
        this._blMesh.frustumCulled = false;
        this._blMesh.name = 'city-sim-brakelights';
        scene.add(this._blMesh);

        // Turn signal indicators (amber spheres)
        const tsGeo = new THREE.SphereGeometry(0.12, 4, 3);
        const tsMat = new THREE.MeshBasicMaterial({
            color: 0xffaa00,
            transparent: true,
            opacity: 0,
        });
        this._tsMesh = new THREE.InstancedMesh(tsGeo, tsMat, this.maxVehicles);
        this._tsMesh.count = 0;
        this._tsMesh.frustumCulled = false;
        this._tsMesh.name = 'city-sim-turnsignals';
        scene.add(this._tsMesh);

        // Traffic signal indicators — one sphere per signal approach
        if (this.trafficMgr) {
            const signalCount = Object.values(this.trafficMgr.controllers)
                .reduce((s, c) => s + c.edges.length, 0);
            if (signalCount > 0) {
                const sigGeo = new THREE.SphereGeometry(0.4, 6, 4);
                const sigMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
                this._signalMesh = new THREE.InstancedMesh(sigGeo, sigMat, signalCount);
                this._signalMesh.count = signalCount;
                this._signalMesh.frustumCulled = false;
                this._signalMesh.name = 'city-sim-signals';

                const sigColors = new Float32Array(signalCount * 3);
                this._signalMesh.instanceColor = new THREE.InstancedBufferAttribute(sigColors, 3);
                scene.add(this._signalMesh);

                // Store signal info for per-frame color updates
                this._signalInfos = [];
                for (const nodeId in this.trafficMgr.controllers) {
                    const ctrl = this.trafficMgr.controllers[nodeId];
                    for (const edge of ctrl.edges) {
                        this._signalInfos.push({ nodeId, edgeId: edge.id, node: ctrl.node });
                    }
                }
            }
        }

        console.log(`[CitySimManager] Rendering initialized (${this.maxVehicles} vehicles, ${this.maxPedestrians} pedestrians)`);
    }

    /**
     * Update InstancedMesh transforms from vehicle positions.
     * Call every frame after tick().
     *
     * @param {Function} gameToThree — coordinate transform (gx, gz) → {x, y}
     *   where x=east, y=north in Three.js scene coords (refMatrix handles Mercator conversion)
     */
    updateRendering(gameToThree) {
        if (!this._carMesh || !this._dummy) return;

        const count = Math.min(this.vehicles.length, this.maxVehicles);
        if (this.vehicles.length > this.maxVehicles) {
            console.warn(`[CitySimManager] Vehicle overflow: ${this.vehicles.length} vehicles exceed max ${this.maxVehicles}. ${this.vehicles.length - this.maxVehicles} won't render.`);
        }
        this._carMesh.count = count;

        for (let i = 0; i < count; i++) {
            const car = this.vehicles[i];
            const tp = gameToThree(car.x, car.z);

            // Scale by vehicle subtype dimensions
            const sx = (car.width || 1.8) / 1.8;
            const sy = (car.height || 1.2) / 1.2;
            const sz = (car.length || 4.0) / 4.0;

            // Collision shake — random displacement that decays quickly
            let shakeX = 0, shakeZ = 0, shakeRot = 0;
            if (car.shakeIntensity > 0.05) {
                const t = Date.now() * 0.03;
                shakeX = Math.sin(t * 7.3) * car.shakeIntensity * 0.3;
                shakeZ = Math.cos(t * 5.7) * car.shakeIntensity * 0.3;
                shakeRot = Math.sin(t * 11.1) * car.shakeIntensity * 0.1;
            }

            this._dummy.position.set(tp.x + shakeX, tp.y + shakeZ, (car.height || 1.2) / 2);
            this._dummy.rotation.set(0, 0, -car.heading + shakeRot);
            this._dummy.scale.set(sx, sy, sz);
            this._dummy.updateMatrix();
            this._carMesh.setMatrixAt(i, this._dummy.matrix);

            // Set per-instance color — emergency vehicles flash red/blue, accidents flash red/yellow
            if (car.inAccident) {
                const flash = Math.sin(Date.now() * 0.006) > 0 ? 0xff0000 : 0xfcee0a;
                this._color.setHex(flash);
            } else if (car.isEmergency && car.sirenActive) {
                const flash = Math.sin(car.sirenPhase) > 0 ? 0xff0000 : 0x0000ff;
                this._color.setHex(flash);
            } else if (car.parked) {
                this._color.setHex(0x333333);  // Dim parked vehicles
            } else {
                this._color.setHex(car.color);
            }
            this._carMesh.setColorAt(i, this._color);
        }

        if (count > 0) {
            this._carMesh.instanceMatrix.needsUpdate = true;
            if (this._carMesh.instanceColor) {
                this._carMesh.instanceColor.needsUpdate = true;
            }
        }

        // Headlight cones (positioned at front of each vehicle)
        if (this._hlMesh && this.weather?.headlightsOn) {
            this._hlMesh.material.opacity = 0.06;
            let hlCount = 0;
            for (let i = 0; i < count; i++) {
                const car = this.vehicles[i];
                const tp = gameToThree(car.x, car.z);
                // Left headlight
                this._dummy.position.set(tp.x - 0.5 * Math.cos(car.heading), tp.y + 0.5 * Math.sin(car.heading), 0.5);
                this._dummy.rotation.set(0, 0, -car.heading);
                this._dummy.scale.set(0.3, 0.3, 0.3);
                this._dummy.updateMatrix();
                this._hlMesh.setMatrixAt(hlCount++, this._dummy.matrix);
                // Right headlight
                this._dummy.position.set(tp.x + 0.5 * Math.cos(car.heading), tp.y - 0.5 * Math.sin(car.heading), 0.5);
                this._dummy.updateMatrix();
                this._hlMesh.setMatrixAt(hlCount++, this._dummy.matrix);
            }
            this._hlMesh.count = hlCount;
            this._hlMesh.instanceMatrix.needsUpdate = true;
        } else if (this._hlMesh) {
            this._hlMesh.material.opacity = 0;
            this._hlMesh.count = 0;
        }

        // Brake lights (red glow when decelerating)
        if (this._blMesh) {
            let blCount = 0;
            for (let i = 0; i < count; i++) {
                const car = this.vehicles[i];
                if (car.acc >= -0.5) continue;  // Only show when braking
                const tp = gameToThree(car.x, car.z);
                const sinH = Math.sin(car.heading);
                const cosH = Math.cos(car.heading);
                // Left brake light (rear)
                this._dummy.position.set(tp.x + 0.5 * cosH + 2 * sinH, tp.y - 0.5 * sinH + 2 * cosH, 0.5);
                this._dummy.scale.set(1, 1, 1);
                this._dummy.updateMatrix();
                this._blMesh.setMatrixAt(blCount++, this._dummy.matrix);
                // Right brake light
                this._dummy.position.set(tp.x - 0.5 * cosH + 2 * sinH, tp.y + 0.5 * sinH + 2 * cosH, 0.5);
                this._dummy.updateMatrix();
                this._blMesh.setMatrixAt(blCount++, this._dummy.matrix);
            }
            this._blMesh.count = blCount;
            this._blMesh.material.opacity = blCount > 0 ? 0.8 : 0;
            if (blCount > 0) this._blMesh.instanceMatrix.needsUpdate = true;
        }

        // Turn signals (amber sphere on turning side)
        if (this._tsMesh) {
            let tsCount = 0;
            for (let i = 0; i < count; i++) {
                const car = this.vehicles[i];
                if (car.turnSignal === 'none') continue;
                const tp = gameToThree(car.x, car.z);
                const sinH = Math.sin(car.heading);
                const cosH = Math.cos(car.heading);
                // Place on the side of the turn, at rear of vehicle
                const side = car.turnSignal === 'left' ? 1 : -1;
                this._dummy.position.set(
                    tp.x + side * 0.7 * cosH + 1.8 * sinH,
                    tp.y - side * 0.7 * sinH + 1.8 * cosH,
                    0.6
                );
                this._dummy.scale.set(1, 1, 1);
                this._dummy.updateMatrix();
                this._tsMesh.setMatrixAt(tsCount++, this._dummy.matrix);
            }
            this._tsMesh.count = tsCount;
            this._tsMesh.material.opacity = tsCount > 0 ? 0.9 : 0;
            if (tsCount > 0) this._tsMesh.instanceMatrix.needsUpdate = true;
        }

        // Update pedestrians
        if (this._pedMesh) {
            let pedCount = 0;
            for (let i = 0; i < this.pedestrians.length && pedCount < this.maxPedestrians; i++) {
                const ped = this.pedestrians[i];
                if (!ped.visible || ped.inBuilding) continue;

                const tp = gameToThree(ped.x, ped.z);
                const bob = Math.sin(ped.bobPhase) * 0.03;
                this._dummy.position.set(tp.x, tp.y, 0.7 + bob);
                this._dummy.rotation.set(0, 0, -ped.heading);
                this._dummy.scale.set(1, 1, 1);
                this._dummy.updateMatrix();
                this._pedMesh.setMatrixAt(pedCount, this._dummy.matrix);

                this._color.setHex(ped.color);
                this._pedMesh.setColorAt(pedCount, this._color);
                pedCount++;
            }
            this._pedMesh.count = pedCount;
            if (pedCount > 0) {
                this._pedMesh.instanceMatrix.needsUpdate = true;
                if (this._pedMesh.instanceColor) this._pedMesh.instanceColor.needsUpdate = true;
            }
        }

        // Traffic signal colors
        if (this._signalMesh && this._signalInfos && this.trafficMgr) {
            const SIGNAL_COLORS = { green: 0x00ff00, yellow: 0xffff00, red: 0xff0000 };
            for (let i = 0; i < this._signalInfos.length; i++) {
                const info = this._signalInfos[i];
                const tp = gameToThree(info.node.x, info.node.z);

                // Position signal at intersection, slightly offset per edge
                const offset = (i % 4) * 1.5 - 2.25;  // Spread around intersection
                this._dummy.position.set(tp.x + offset * 0.3, tp.y + offset * 0.3, 5.5);
                this._dummy.scale.set(1, 1, 1);
                this._dummy.updateMatrix();
                this._signalMesh.setMatrixAt(i, this._dummy.matrix);

                // Color by signal state
                const color = this.trafficMgr.getSignalColor(info.nodeId, info.edgeId);
                this._color.setHex(SIGNAL_COLORS[color] || 0xff0000);
                this._signalMesh.setColorAt(i, this._color);
            }
            this._signalMesh.instanceMatrix.needsUpdate = true;
            if (this._signalMesh.instanceColor) this._signalMesh.instanceColor.needsUpdate = true;
        }
    }

    /**
     * Find shortest route between two points.
     */
    findRoute(fromX, fromZ, toX, toZ) {
        if (!this.roadNetwork) return [];
        const fromNode = this.roadNetwork.nearestNode(fromX, fromZ);
        const toNode = this.roadNetwork.nearestNode(toX, toZ);
        if (!fromNode || !toNode) return [];
        const path = this.roadNetwork.findPath(fromNode.nodeId, toNode.nodeId);
        if (!path.length) return [];
        const waypoints = [{ x: fromX, z: fromZ }];
        for (const step of path) {
            const n = this.roadNetwork.nodes[step.nodeId];
            waypoints.push({ x: n.x, z: n.z });
        }
        waypoints.push({ x: toX, z: toZ });
        return waypoints;
    }

    /**
     * Load a scenario by ID or object. Clears existing entities and applies config.
     */
    loadScenario(scenario) {
        const s = typeof scenario === 'string' ? getScenarioById(scenario) : scenario;
        if (!s) {
            console.warn(`[CitySimManager] Unknown scenario: ${scenario}`);
            return false;
        }
        return _loadScenario(this, s);
    }

    /**
     * Get simulation stats.
     */
    /**
     * Try to spawn a spontaneous micro-gathering at a park or commercial area.
     */
    _trySpawnGathering() {
        if (Math.random() > 0.15) return; // 15% chance per check
        if (!this._buildingsByType?.park?.length && !this._buildingsByType?.commercial?.length) return;

        // Pick a gathering location
        const parks = this._buildingsByType.park || [];
        const commercial = this._buildingsByType.commercial || [];
        const locations = [...parks, ...commercial.slice(0, 3)];
        if (locations.length === 0) return;

        const loc = locations[Math.floor(Math.random() * locations.length)];

        // Find 3-6 NPCs with high sociability who are outside and not already overridden
        const candidates = this.pedestrians.filter(p =>
            !p.inBuilding && p.alive && !p.overrideGoal && (p.personality?.sociability || 0) > 0.5
        );
        if (candidates.length < 3) return;

        const count = 3 + Math.floor(Math.random() * 4); // 3-6
        const selected = candidates.slice(0, count);

        // Send them to the gathering location
        for (const ped of selected) {
            ped.overrideGoal = {
                action: 'go_to',
                target: { x: loc.x + (Math.random() - 0.5) * 15, z: loc.z + (Math.random() - 0.5) * 15 },
                speed: 1.2,
                source: 'gathering',
                _expiresAt: this.simHour + 0.5, // gathering lasts ~30 sim minutes
            };
        }

        console.log(`[CitySimManager] Micro-gathering: ${count} NPCs heading to (${loc.x.toFixed(0)}, ${loc.z.toFixed(0)})`);
    }

    /**
     * Record an NPC entering a building.
     */
    npcEnterBuilding(npcId, buildingId) {
        if (!buildingId) return;
        if (!this.buildingOccupancy.has(buildingId)) {
            this.buildingOccupancy.set(buildingId, new Set());
        }
        this.buildingOccupancy.get(buildingId).add(npcId);
    }

    /**
     * Record an NPC exiting a building.
     */
    npcExitBuilding(npcId, buildingId) {
        if (!buildingId) return;
        this.buildingOccupancy.get(buildingId)?.delete(npcId);
    }

    /**
     * Get building occupancy stats.
     */
    getBuildingOccupancyStats() {
        let totalOccupied = 0;
        let peakCount = 0;
        let peakBuildingId = null;
        for (const [bid, occupants] of this.buildingOccupancy) {
            if (occupants.size > 0) totalOccupied++;
            if (occupants.size > peakCount) {
                peakCount = occupants.size;
                peakBuildingId = bid;
            }
        }
        return { totalOccupied, peakCount, peakBuildingId, totalNpcsInBuildings: this.pedestrians.filter(p => p.inBuilding).length };
    }

    /**
     * Dispatch an emergency vehicle to a crash/incident scene.
     */
    _dispatchEmergencyToScene(sceneX, sceneZ) {
        if (!this.roadNetwork) return;
        const edge = this.roadNetwork.randomEdge();
        if (!edge) return;

        const car = new SimVehicle(edge, 0, this.roadNetwork);
        car.isEmergency = true;
        car.sirenActive = true;
        car.color = 0xff2a6d;
        car.idm.v0 = 20;
        car.idm.a = 2.5;
        car.idm.T = 1.0;
        car.purpose = 'emergency';
        car.destination = { x: sceneX, z: sceneZ };
        car._planNewRoute();
        this.vehicles.push(car);

        console.log(`[CitySimManager] Emergency dispatched to (${sceneX.toFixed(0)}, ${sceneZ.toFixed(0)})`);
        EventBus.emit('alert:new', {
            id: `emergency_dispatch_${Date.now()}`,
            type: 'city_sim_emergency',
            level: 'warning',
            title: 'Emergency Response',
            message: `Ambulance dispatched to accident scene at (${sceneX.toFixed(0)}, ${sceneZ.toFixed(0)})`,
            position: { x: sceneX, z: sceneZ },
            source: 'city_sim',
            timestamp: Date.now(),
        });
    }

    /**
     * Taxi dispatch — match waiting NPCs to idle taxi vehicles.
     * NPCs with transportPref='rideshare' who are outside and commuting will request rides.
     */
    _tickTaxis(dt) {
        const taxis = this.vehicles.filter(v => v.purpose === 'taxi');
        if (taxis.length === 0) return;

        // Find idle taxis
        const idleTaxis = taxis.filter(v => v.taxiState === 'idle' && !v.parked && !v.inAccident);

        // Check each taxi's state
        for (const taxi of taxis) {
            if (taxi.taxiState === 'en_route_pickup' && taxi.pickupTarget) {
                // Check if we've reached the pickup NPC
                const ped = taxi.pickupTarget;
                const dx = taxi.x - ped.x;
                const dz = taxi.z - ped.z;
                if (dx * dx + dz * dz < 100) { // within 10m
                    // Pick up passenger
                    taxi.passenger = ped;
                    taxi.taxiState = 'carrying';
                    ped.inBuilding = true; // hide the NPC (they're in the car)
                    ped.visible = false;
                    ped.overrideGoal = { action: 'stay', speed: 0, source: 'taxi' };

                    // Navigate to passenger's destination
                    const dest = ped.workEntry || ped.homeEntry;
                    taxi.destination = { x: dest.x, z: dest.z };
                    taxi._planNewRoute();
                    taxi.color = 0x00ff44; // green while carrying
                }
            } else if (taxi.taxiState === 'carrying' && taxi.passenger) {
                // Check if we've reached the destination
                if (taxi.parked || (taxi.route.length > 0 && taxi.routeIdx >= taxi.route.length - 1)) {
                    // Drop off passenger
                    const ped = taxi.passenger;
                    ped.x = taxi.x;
                    ped.z = taxi.z;
                    ped.inBuilding = false;
                    ped.visible = true;
                    ped.overrideGoal = null;

                    taxi.passenger = null;
                    taxi.pickupTarget = null;
                    taxi.taxiState = 'idle';
                    taxi.destination = null;
                    taxi.color = 0xfcee0a; // back to yellow
                    taxi._planNewRoute(); // cruise around
                }
            }
        }

        // Match waiting NPCs to idle taxis (simple nearest-match)
        if (idleTaxis.length === 0) return;

        for (const ped of this.pedestrians) {
            if (idleTaxis.length === 0) break;
            if (ped.inBuilding || !ped.alive || ped.stunTimer > 0) continue;
            if (ped.transportPref !== 'rideshare') continue;
            if (ped.overrideGoal?.source === 'taxi') continue; // already has a ride
            if (ped.activity !== 'commuting') continue; // only during commute

            // Find nearest idle taxi
            let bestTaxi = null;
            let bestDist = Infinity;
            for (const taxi of idleTaxis) {
                const dx = taxi.x - ped.x;
                const dz = taxi.z - ped.z;
                const dist = dx * dx + dz * dz;
                if (dist < bestDist) {
                    bestDist = dist;
                    bestTaxi = taxi;
                }
            }

            if (bestTaxi) {
                // Dispatch taxi to pick up NPC
                bestTaxi.pickupTarget = ped;
                bestTaxi.taxiState = 'en_route_pickup';
                bestTaxi.destination = { x: ped.x, z: ped.z };
                bestTaxi._planNewRoute();
                bestTaxi.color = 0xff8800; // orange while en route to pickup

                // NPC waits for taxi
                ped.overrideGoal = { action: 'stay', speed: 0, source: 'taxi_wait' };
                ped.color = 0xfcee0a; // yellow while waiting

                // Remove from idle pool
                const idx = idleTaxis.indexOf(bestTaxi);
                if (idx >= 0) idleTaxis.splice(idx, 1);
            }
        }
    }

    /**
     * Classify city-data buildings by type for NPC/vehicle assignment.
     */
    _classifyBuildings() {
        const buildings = this.cityData?.buildings || [];
        this._buildingsByType = { residential: [], commercial: [], industrial: [], park: [] };
        for (let i = 0; i < buildings.length; i++) {
            const b = buildings[i];
            const cat = b.category || b.type || 'residential';
            const cx = b.polygon.reduce((s, p) => s + p[0], 0) / b.polygon.length;
            const cz = b.polygon.reduce((s, p) => s + p[1], 0) / b.polygon.length;
            const entry = { x: cx, z: cz, buildingId: b.id, buildingIdx: i };
            if (cat === 'residential' || cat === 'apartments') {
                this._buildingsByType.residential.push(entry);
            } else if (cat === 'commercial' || cat === 'retail') {
                this._buildingsByType.commercial.push(entry);
            } else if (cat === 'industrial') {
                this._buildingsByType.industrial.push(entry);
            } else {
                this._buildingsByType.residential.push(entry);
            }
        }
        for (const lu of (this.cityData?.landuse || [])) {
            if (lu.type === 'park' && lu.polygon?.length >= 3) {
                const cx = lu.polygon.reduce((s, p) => s + p[0], 0) / lu.polygon.length;
                const cz = lu.polygon.reduce((s, p) => s + p[1], 0) / lu.polygon.length;
                this._buildingsByType.park.push({ x: cx, z: cz, buildingId: lu.id });
            }
        }
        if (this._buildingsByType.commercial.length === 0) {
            this._buildingsByType.commercial = this._buildingsByType.residential;
        }
        console.log(`[CitySimManager] Buildings classified: ${this._buildingsByType.residential.length} residential, ${this._buildingsByType.commercial.length} commercial, ${this._buildingsByType.industrial.length} industrial, ${this._buildingsByType.park.length} parks`);
    }

    getStats() {
        if (!this.roadNetwork) return null;
        const networkStats = this.roadNetwork.stats();
        let avgSpeed = 0;
        if (this.vehicles.length > 0) {
            avgSpeed = this.vehicles.reduce((s, v) => s + v.speed, 0) / this.vehicles.length;
        }
        const activePeds = this.pedestrians.filter(p => !p.inBuilding).length;
        const inBuildingPeds = this.pedestrians.filter(p => p.inBuilding).length;

        return {
            ...networkStats,
            vehicles: this.vehicles.length,
            pedestrians: this.pedestrians.length,
            pedestriansActive: activePeds,
            pedestriansInBuilding: inBuildingPeds,
            avgSpeedMs: Math.round(avgSpeed * 10) / 10,
            avgSpeedKmh: Math.round(avgSpeed * 3.6),
            simHour: Math.round(this.simHour * 10) / 10,
            simDay: this.simDay || 0,
            dayOfWeek: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][(this.simDay || 0) % 7],
            isWeekend: ((this.simDay || 0) % 7) >= 5,
            running: this.running,
            trafficControllers: this.trafficMgr ? Object.keys(this.trafficMgr.controllers).length : 0,
            weather: this.weather.weather,
            timeOfDay: this.weather.toString(),
            timeScale: this.timeScale,
            isNight: this.weather.isNight,
            anomalies: this.anomalyDetector.getStats(),
            rl: this.rlHooks?.getEpisodeStats() || null,
            protest: this.protestManager?.getDebugInfo() || null,
            buildingOccupancy: this.getBuildingOccupancyStats(),
            buildings: this.cityData?.stats?.buildings || 0,
            trees: this.cityData?.stats?.trees || 0,
        };
    }

    /**
     * Compute per-edge congestion data.
     * Returns Map<edgeId, { avgSpeed, vehicleCount, ratio }>
     * ratio: 1.0 = free flow, 0.0 = gridlock
     */
    getCongestionMap() {
        if (!this.roadNetwork) return new Map();
        const ROAD_SPEEDS = { motorway: 30, trunk: 25, primary: 18, secondary: 15, tertiary: 13, residential: 10, service: 5 };
        const congestion = new Map();

        // Aggregate speed per edge
        for (const car of this.vehicles) {
            if (!car.edge || car.parked) continue;
            const eid = car.edge.id;
            if (!congestion.has(eid)) {
                const limit = car.edge.speedLimit || ROAD_SPEEDS[car.edge.roadClass] || 10;
                congestion.set(eid, { totalSpeed: 0, count: 0, limit });
            }
            const c = congestion.get(eid);
            c.totalSpeed += car.speed;
            c.count++;
        }

        // Compute ratio
        for (const [eid, c] of congestion) {
            c.avgSpeed = c.count > 0 ? c.totalSpeed / c.count : c.limit;
            c.ratio = Math.min(1.0, c.avgSpeed / Math.max(c.limit, 1));
        }

        return congestion;
    }

    /**
     * Build debug overlay for road graph.
     */
    buildDebugOverlay(THREE, gameToThree) {
        if (!this.roadNetwork) return null;

        const group = new THREE.Group();
        group.name = 'road-graph-debug';

        const nodeCount = Object.keys(this.roadNetwork.nodes).length;
        if (nodeCount > 0) {
            const dotGeo = new THREE.SphereGeometry(1.0, 6, 4);
            const dotMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff, transparent: true, opacity: 0.8 });
            const dotMesh = new THREE.InstancedMesh(dotGeo, dotMat, nodeCount);
            dotMesh.count = nodeCount;

            const dummy = new THREE.Object3D();
            let i = 0;
            for (const nodeId in this.roadNetwork.nodes) {
                const n = this.roadNetwork.nodes[nodeId];
                const tp = gameToThree(n.x, n.z);
                const s = n.degree >= 3 ? 1.5 : 0.8;
                dummy.position.set(tp.x, tp.y, 0.5);
                dummy.scale.set(s, s, s);
                dummy.updateMatrix();
                dotMesh.setMatrixAt(i++, dummy.matrix);
            }
            dotMesh.instanceMatrix.needsUpdate = true;
            group.add(dotMesh);
        }

        const edgeColors = {
            motorway: 0xff4444, trunk: 0xff8844, primary: 0xffcc44,
            secondary: 0x44ff44, tertiary: 0x44ffcc, residential: 0x4488ff,
            service: 0x8844ff,
        };

        for (const edge of this.roadNetwork.edges) {
            const color = edgeColors[edge.roadClass] || 0x888888;
            const pts = (edge.waypoints || [[edge.ax, edge.az], [edge.bx, edge.bz]]).map(([gx, gz]) => {
                const tp = gameToThree(gx, gz);
                return new THREE.Vector3(tp.x, tp.y, 0.3);
            });
            if (pts.length < 2) continue;

            const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
            const lineMat = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.5 });
            group.add(new THREE.Line(lineGeo, lineMat));
        }

        return group;
    }
}
