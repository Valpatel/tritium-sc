// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * SimVehicle — a vehicle that drives on the road network using IDM physics.
 *
 * Each vehicle has a route (sequence of edges from Dijkstra), a position
 * along its current edge, and IDM parameters. It follows the car ahead,
 * stops at obstacles, and picks new routes when it reaches its destination.
 *
 * Pure data — no Three.js dependency. CitySimManager handles rendering.
 */

import { idmAcceleration, idmFreeFlow, idmStep, IDM_DEFAULTS, ROAD_SPEEDS } from '/lib/sim/idm.js';
import { decideLaneChange } from '/lib/sim/mobil.js';

let _nextId = 0;

export class SimVehicle {
    /**
     * @param {Object} edge — starting road edge
     * @param {number} u — starting position along edge (0..edge.length)
     * @param {Object} roadNetwork — RoadNetwork instance
     */
    constructor(edge, u, roadNetwork) {
        this.id = `car_${_nextId++}`;
        this.edge = edge;
        this.u = u;                     // distance along current edge
        this.speed = 0;
        this.acc = 0;
        this.heading = 0;
        this.x = 0;
        this.z = 0;
        this.alive = true;
        this.roadNetwork = roadNetwork;

        // Vehicle subtype — affects mesh dimensions and IDM params
        this.subtype = _randomSubtype();
        const profile = VEHICLE_PROFILES[this.subtype];

        // IDM params — adjusted per subtype and road class
        this.idm = { ...IDM_DEFAULTS, ...profile.idm };
        this._setSpeedForRoad(edge);

        // Physical dimensions and mass
        this.length = profile.length;
        this.width = profile.width;
        this.height = profile.height;
        this.mass = profile.mass;

        // Intent — why this vehicle exists and where it's going
        this.purpose = 'random';    // 'commute' | 'delivery' | 'taxi' | 'patrol' | 'random'
        this.owner = null;          // NPC reference (for commute vehicles)
        this.destination = null;    // {x, z, buildingId} — where we're headed

        // Taxi state machine
        this.pickupTarget = null;   // NPC waiting for this taxi
        this.taxiState = 'idle';    // 'idle' | 'en_route_pickup' | 'carrying' | 'cruising'
        this.passenger = null;      // NPC being carried

        // Route: sequence of edges to follow
        this.route = [];
        this.routeIdx = 0;

        // Direction along current edge: +1 = from→to, -1 = to→from
        this.direction = 1;

        // Emergency vehicle state
        this.isEmergency = false;
        this.sirenActive = false;
        this.sirenPhase = 0;  // for flashing light animation

        // Parking state
        this.parked = false;
        this.parkTimer = 0;

        // Turn signal state
        this.turnSignal = 'none'; // 'none' | 'left' | 'right'

        // Lane tracking (MOBIL)
        this.laneIdx = Math.floor(Math.random() * (edge.lanesPerDir || 1));
        this.lateralOffset = 0;          // meters offset from edge centerline
        this._laneChangeState = null;    // { fromLane, toLane, t, duration }
        this._mobilTimer = Math.random() * 2; // stagger evaluations across vehicles

        // Node transition tracking (for Markov route prediction)
        this.lastNodeId = null;
        this._pendingTransition = null; // { from, to } — consumed by anomaly detector

        // Accident state
        this.inAccident = false;
        this.accidentTimer = 0;
        this._collisionCooldown = 0;  // frames until next collision check

        // Visual impact shake (decays over time)
        this.shakeIntensity = 0;  // 0 = no shake, > 0 = shaking

        // Rendering
        this.instanceIdx = -1;
        this.color = _randomCarColor();

        this._updatePosition();
    }

    /**
     * Update vehicle for one timestep.
     * @param {number} dt
     * @param {Array<SimVehicle>} nearbyVehicles — vehicles on same/adjacent edges
     */
    tick(dt, nearbyVehicles) {
        if (!this.alive) return;

        // Parked vehicles don't move — check if they should unpark based on time
        if (this.parked) {
            this.parkTimer -= dt;
            // Time-based parking: commute vehicles stay parked until rush hour
            if (this.purpose === 'commute' && this._simHour !== undefined) {
                if (this._isWeekend) return; // commuters don't drive on weekends
                const h = this._simHour;
                const isMorningRush = h >= 7 && h < 9;
                const isEveningRush = h >= 16.5 && h < 18.5;
                if (!isMorningRush && !isEveningRush) {
                    return; // stay parked outside rush hours
                }
            }
            if (this.parkTimer <= 0) {
                this.parked = false;
                this._planNewRoute();
            }
            return;
        }

        // Accident: vehicles are stopped, count down clearance timer
        if (this.inAccident) {
            this.accidentTimer -= dt;
            if (this.accidentTimer <= 0) {
                this.inAccident = false;
                this.accidentTimer = 0;
                this._planNewRoute();
            }
            return;
        }

        // Collision cooldown and shake decay
        if (this._collisionCooldown > 0) this._collisionCooldown -= dt;
        if (this.shakeIntensity > 0) this.shakeIntensity *= Math.exp(-dt * 8);  // fast decay

        // Siren animation
        if (this.isEmergency && this.sirenActive) {
            this.sirenPhase += dt * 6;  // Flash frequency
        }

        // Find leader (closest vehicle ahead on same edge and lane)
        let leaderGap = Infinity;
        let leaderSpeed = this.idm.v0;
        const effectiveLane = this._laneChangeState ? this._laneChangeState.toLane : this.laneIdx;

        for (const other of nearbyVehicles) {
            if (other === this || other.edge !== this.edge) continue;
            if (other.direction !== this.direction) continue;
            if (other.laneIdx !== effectiveLane) continue;

            const gap = (other.u - this.u) * this.direction;
            if (gap > 0 && gap < leaderGap) {
                leaderGap = gap - (this.length + other.length) / 2;
                leaderSpeed = other.speed;
            }
        }

        // Check red light virtual obstacle (emergency vehicles ignore red lights)
        if (this._redLightActive && this._redLightGap > 0 && !this.isEmergency) {
            if (this._redLightGap < leaderGap) {
                leaderGap = this._redLightGap;
                leaderSpeed = 0;
            }
        }

        // MOBIL lane change evaluation (every ~2 seconds, only on multi-lane roads)
        if (this.edge.lanesPerDir > 1 && !this._laneChangeState) {
            this._mobilTimer -= dt;
            if (this._mobilTimer <= 0) {
                this._mobilTimer = 1.5 + Math.random();  // re-evaluate in 1.5-2.5s
                const decision = decideLaneChange(this, nearbyVehicles);
                if (decision.targetLane !== null) {
                    this._laneChangeState = {
                        fromLane: this.laneIdx,
                        toLane: decision.targetLane,
                        t: 0,
                        duration: 2.0,
                    };
                    this.turnSignal = decision.direction;
                }
            }
        }

        // Animate lane change
        if (this._laneChangeState) {
            const lcs = this._laneChangeState;
            lcs.t += dt / lcs.duration;
            if (lcs.t >= 1) {
                this.laneIdx = lcs.toLane;
                this._laneChangeState = null;
                this.turnSignal = 'none';
            }
        }

        // Apply weather speed modifier (set by CitySimManager)
        const weatherMult = this._weatherSpeedMult || 1.0;
        const weatherIdm = weatherMult < 1.0
            ? { ...this.idm, v0: this.idm.v0 * weatherMult }
            : this.idm;

        // Compute acceleration — use same-lane leader only
        if (leaderGap < Infinity && leaderGap > 0) {
            this.acc = idmAcceleration(this.speed, leaderGap, leaderSpeed, weatherIdm);
        } else {
            this.acc = idmFreeFlow(this.speed, weatherIdm);
        }

        // Approach edge end — brake if no next edge planned
        const remaining = this.direction > 0
            ? this.edge.length - this.u
            : this.u;

        if (remaining < 20 && this.route.length === this.routeIdx) {
            // Current edge is last in route — plan a new one
            this._planNewRoute();
        }

        // Turn signal: activate within 20m of edge end if next edge exists
        if (remaining < 20 && this.routeIdx + 1 < this.route.length) {
            const nextStep = this.route[this.routeIdx + 1];
            if (nextStep && nextStep.edge) {
                const nextEdge = nextStep.edge;
                // Current edge heading
                const curDx = this.edge.bx - this.edge.ax;
                const curDz = this.edge.bz - this.edge.az;
                const curAngle = Math.atan2(curDx, curDz);
                // Next edge heading
                const nDx = nextEdge.bx - nextEdge.ax;
                const nDz = nextEdge.bz - nextEdge.az;
                const nAngle = Math.atan2(nDx, nDz);
                // Angle difference, normalized to [-PI, PI]
                let dAngle = nAngle - curAngle;
                while (dAngle > Math.PI) dAngle -= 2 * Math.PI;
                while (dAngle < -Math.PI) dAngle += 2 * Math.PI;
                if (dAngle > 0.3) this.turnSignal = 'right';
                else if (dAngle < -0.3) this.turnSignal = 'left';
                else this.turnSignal = 'none';
            } else {
                this.turnSignal = 'none';
            }
        } else {
            this.turnSignal = 'none';
        }

        if (remaining < 5 && remaining > 0) {
            // Approaching edge end — slow down for transition
            const brakeAcc = -(this.speed * this.speed) / (2 * Math.max(remaining, 0.5));
            this.acc = Math.min(this.acc, Math.max(brakeAcc, -4));
        }

        // IDM step
        const { v, ds } = idmStep(this.speed, this.acc, dt);
        this.speed = v;
        this.u += ds * this.direction;

        // Edge transition
        if (this.direction > 0 && this.u >= this.edge.length) {
            this._advanceToNextEdge();
        } else if (this.direction < 0 && this.u <= 0) {
            this._advanceToNextEdge();
        }

        this._updatePosition();
    }

    /**
     * Plan route to destination, or pick a random one.
     * If this.destination is set, route toward it. Otherwise random.
     */
    _planNewRoute() {
        const currentNodeId = this.direction > 0 ? this.edge.to : this.edge.from;
        const rn = this.roadNetwork;
        const nodeIds = Object.keys(rn.nodes);
        if (nodeIds.length < 2) return;

        // If we have a destination, route toward it
        if (this.destination) {
            const destNode = rn.nearestNode(this.destination.x, this.destination.z);
            if (destNode) {
                const path = rn.findPath(currentNodeId, destNode.id || destNode.nodeId);
                if (path.length >= 1) {
                    this.route = path;
                    this.routeIdx = 0;
                    return;
                }
            }
        }

        // Delivery vehicles: cycle between commercial and residential areas
        if (this.purpose === 'delivery' && this._deliveryTargets?.length) {
            this._deliveryIdx = ((this._deliveryIdx || 0) + 1) % this._deliveryTargets.length;
            const target = this._deliveryTargets[this._deliveryIdx];
            const destNode = rn.nearestNode(target.x, target.z);
            if (destNode) {
                const path = rn.findPath(currentNodeId, destNode.id || destNode.nodeId);
                if (path.length >= 1) {
                    this.route = path;
                    this.routeIdx = 0;
                    return;
                }
            }
        }

        // Patrol vehicles: pick a random intersection to visit
        if (this.purpose === 'patrol') {
            // Prefer 3+ way intersections for patrol routes
            const intersections = nodeIds.filter(id => rn.nodes[id].degree >= 3);
            const pool = intersections.length > 3 ? intersections : nodeIds;
            for (let attempt = 0; attempt < 5; attempt++) {
                const destId = pool[Math.floor(Math.random() * pool.length)];
                if (destId === currentNodeId) continue;
                const path = rn.findPath(currentNodeId, destId);
                if (path.length >= 2) {
                    this.route = path;
                    this.routeIdx = 0;
                    return;
                }
            }
        }

        // Fallback: random destination
        for (let attempt = 0; attempt < 10; attempt++) {
            const destId = nodeIds[Math.floor(Math.random() * nodeIds.length)];
            if (destId === currentNodeId) continue;

            const path = rn.findPath(currentNodeId, destId);
            if (path.length >= 2) {
                this.route = path;
                this.routeIdx = 0;
                return;
            }
        }
    }

    /**
     * Transition to the next edge in the route.
     */
    _advanceToNextEdge() {
        this.routeIdx++;
        if (this.routeIdx < this.route.length) {
            const step = this.route[this.routeIdx];
            const nextEdge = step.edge;
            const nextNodeId = step.nodeId;

            // Record node transition for Markov route prediction
            const arrivalNodeId = this.direction > 0 ? this.edge.to : this.edge.from;
            if (this.lastNodeId !== null) {
                this._pendingTransition = { from: this.lastNodeId, to: arrivalNodeId };
            }
            this.lastNodeId = arrivalNodeId;

            // Determine direction on new edge — nextNodeId is the destination node
            // If we arrived at nextEdge.from, we must go forward (from→to)
            // If we arrived at nextEdge.to, we must go backward (to→from)
            if (nextEdge.from === nextNodeId) {
                this.direction = 1;
                this.u = 0;
            } else if (nextEdge.to === nextNodeId) {
                this.direction = -1;
                this.u = nextEdge.length;
            } else {
                // Edge doesn't connect — reverse direction as fallback
                console.warn(`[Vehicle] Edge ${nextEdge.id} doesn't connect to node ${nextNodeId}`);
                this.direction *= -1;
                this.u = Math.max(0, Math.min(this.u, this.edge.length));
                return;
            }

            this.edge = nextEdge;
            this._setSpeedForRoad(nextEdge);
            // Pick a lane on the new edge, cancel any in-progress lane change
            this.laneIdx = Math.min(this.laneIdx, (nextEdge.lanesPerDir || 1) - 1);
            this._laneChangeState = null;
        } else {
            // Route complete — park based on purpose
            if (!this.isEmergency) {
                const h = this._simHour || 12;
                let shouldPark = false;
                let parkDuration = 60 + Math.random() * 300;

                if (this.purpose === 'commute') {
                    // Commute: park at work during day, at home during night
                    if (h >= 8 && h < 17) {
                        shouldPark = true;
                        parkDuration = (17 - h) * 3600 / 60; // park until ~5pm (in sim seconds at 60x)
                    } else if (h >= 19 || h < 6) {
                        shouldPark = true;
                        parkDuration = 600 + Math.random() * 300; // park overnight
                    }
                } else if (this.purpose === 'delivery') {
                    // Delivery: short stops at each destination
                    shouldPark = true;
                    parkDuration = 30 + Math.random() * 60;  // 30s-90s dwell
                } else if (this.purpose === 'taxi') {
                    // Taxis: don't park unless no fares
                    shouldPark = this.taxiState === 'idle' && Math.random() < 0.1;
                    parkDuration = 30 + Math.random() * 60;
                } else {
                    shouldPark = Math.random() < 0.3;
                }

                if (shouldPark) {
                    this.parked = true;
                    this.parkTimer = parkDuration;
                    this.speed = 0;
                    this.acc = 0;
                    return;
                }
            }

            this._planNewRoute();
            if (this.route.length > 0) {
                this._advanceToNextEdge();
            } else {
                // Can't find a route — just reverse
                this.direction *= -1;
                this.u = Math.max(0, Math.min(this.u, this.edge.length));
            }
        }
    }

    /**
     * Set desired speed based on road class.
     */
    _setSpeedForRoad(edge) {
        const baseSpeed = edge.speedLimit || ROAD_SPEEDS[edge.roadClass] || 10;
        // Add ±10% variation per vehicle
        this.idm.v0 = baseSpeed * (0.9 + Math.random() * 0.2);
    }

    /**
     * Update world x,z position from edge waypoints, with lateral lane offset.
     * Follows the full road geometry (curves, bends) instead of straight-line interpolation.
     */
    _updatePosition() {
        const edge = this.edge;
        const wps = edge.waypoints;
        let cx, cz, segDx, segDz;

        if (wps && wps.length > 2) {
            // Walk along waypoint polyline to find position at distance u
            let remaining = Math.max(0, Math.min(this.u, edge.length));
            if (this.direction < 0) remaining = edge.length - remaining;

            // Walk segments to find which one we're on
            let i = 0;
            for (; i < wps.length - 1; i++) {
                const sdx = wps[i + 1][0] - wps[i][0];
                const sdz = wps[i + 1][1] - wps[i][1];
                const segLen = Math.sqrt(sdx * sdx + sdz * sdz);
                if (remaining <= segLen || i === wps.length - 2) {
                    // We're on this segment
                    const t = segLen > 0.01 ? Math.min(1, remaining / segLen) : 0;
                    cx = wps[i][0] + t * sdx;
                    cz = wps[i][1] + t * sdz;
                    segDx = sdx;
                    segDz = sdz;
                    break;
                }
                remaining -= segLen;
            }

            // Fallback if somehow we didn't break
            if (cx === undefined) {
                cx = wps[wps.length - 1][0];
                cz = wps[wps.length - 1][1];
                segDx = wps[wps.length - 1][0] - wps[wps.length - 2][0];
                segDz = wps[wps.length - 1][1] - wps[wps.length - 2][1];
            }
        } else {
            // Only 2 points — simple linear interpolation (straight road)
            const t = Math.max(0, Math.min(1, this.u / edge.length));
            cx = edge.ax + t * (edge.bx - edge.ax);
            cz = edge.az + t * (edge.bz - edge.az);
            segDx = edge.bx - edge.ax;
            segDz = edge.bz - edge.az;
        }

        // Heading from current segment direction
        this.heading = Math.atan2(segDx, segDz);
        if (this.direction < 0) this.heading += Math.PI;

        // Lateral offset for lane position
        const numLanes = edge.lanesPerDir || 1;
        if (numLanes > 1) {
            const lw = edge.laneWidth || 3;
            let effectiveLane = this.laneIdx;
            if (this._laneChangeState) {
                const s = this._laneChangeState;
                const smoothT = 0.5 - 0.5 * Math.cos(s.t * Math.PI);
                effectiveLane = s.fromLane + (s.toLane - s.fromLane) * smoothT;
            }
            const laneCenter = (effectiveLane - (numLanes - 1) / 2) * lw;
            const len = Math.sqrt(segDx * segDx + segDz * segDz) || 1;
            const perpX = -segDz / len * this.direction;
            const perpZ = segDx / len * this.direction;
            cx += perpX * laneCenter;
            cz += perpZ * laneCenter;
            this.lateralOffset = laneCenter;
        }

        this.x = cx;
        this.z = cz;
    }

    /**
     * Apply momentum-based collision with another vehicle.
     * Uses 1D inelastic collision along the line connecting the two vehicles.
     * Heavier vehicles push lighter ones more. Both get damaged.
     *
     * @param {SimVehicle} other
     * @param {number} overlap — penetration distance (negative gap)
     */
    applyCollision(other, overlap) {
        const m1 = this.mass;
        const m2 = other.mass;
        const totalMass = m1 + m2;

        // Relative velocity along collision axis
        const dx = other.x - this.x;
        const dz = other.z - this.z;
        const dist = Math.sqrt(dx * dx + dz * dz) || 1;
        const nx = dx / dist;
        const nz = dz / dist;

        // Project velocities onto collision normal
        const vx1 = this.speed * Math.sin(this.heading);
        const vz1 = this.speed * Math.cos(this.heading);
        const vx2 = other.speed * Math.sin(other.heading);
        const vz2 = other.speed * Math.cos(other.heading);

        const v1n = vx1 * nx + vz1 * nz;
        const v2n = vx2 * nx + vz2 * nz;

        // Only collide if approaching (relative velocity is negative)
        const relativeVelocity = v1n - v2n;
        if (relativeVelocity <= 0) return false;

        // Coefficient of restitution (0 = perfectly inelastic, 1 = elastic)
        // Low speed → nearly inelastic (bumper touch), high speed → more elastic (bounce)
        const impactSpeed = Math.abs(relativeVelocity);
        const restitution = Math.min(0.3, impactSpeed * 0.02);

        // Post-collision velocities along normal (1D collision formula)
        const v1nPost = (m1 * v1n + m2 * v2n + m2 * restitution * (v2n - v1n)) / totalMass;
        const v2nPost = (m1 * v1n + m2 * v2n + m1 * restitution * (v1n - v2n)) / totalMass;

        // Apply new speeds (magnitude only — heading stays)
        this.speed = Math.max(0, Math.abs(v1nPost));
        other.speed = Math.max(0, Math.abs(v2nPost));

        // Damage based on impact energy: E = 0.5 * m_reduced * Δv²
        const reducedMass = (m1 * m2) / totalMass;
        const impactEnergy = 0.5 * reducedMass * relativeVelocity * relativeVelocity;

        // Threshold for "accident" — sustained damage requiring stop
        // Low-speed bumps (< ~2 m/s approach) are just speed adjustments
        if (impactEnergy > 5000) {
            // Serious collision — vehicles stop and flash
            this.inAccident = true;
            this.speed = 0;
            this.acc = 0;
            // Heavier vehicles recover faster
            this.accidentTimer = 10 + (30 * m2 / totalMass) + Math.random() * 10;

            other.inAccident = true;
            other.speed = 0;
            other.acc = 0;
            other.accidentTimer = 10 + (30 * m1 / totalMass) + Math.random() * 10;
        }

        // Set collision cooldown to prevent repeated bumps
        this._collisionCooldown = 1.0;
        other._collisionCooldown = 1.0;

        // Visual shake — intensity proportional to impact speed and inverse of mass
        this.shakeIntensity = Math.min(2.0, impactSpeed * (m2 / totalMass) * 0.3);
        other.shakeIntensity = Math.min(2.0, impactSpeed * (m1 / totalMass) * 0.3);

        // Separate overlapping vehicles
        if (overlap > 0) {
            const pushFactor1 = m2 / totalMass;
            const pushFactor2 = m1 / totalMass;
            const separation = overlap * 0.6;  // partially separate each frame

            // Push vehicles apart based on mass ratio
            this.u -= separation * pushFactor1 * this.direction;
            other.u += separation * pushFactor2 * other.direction;
            this.u = Math.max(0, Math.min(this.edge.length, this.u));
            other.u = Math.max(0, Math.min(other.edge.length, other.u));
            this._updatePosition();
            other._updatePosition();
        }

        return true;
    }

    /**
     * Apply collision with a pedestrian.
     * Pedestrians have ~80kg mass — vehicles barely slow down but pedestrians
     * get knocked away.
     *
     * @param {Object} ped — SimPedestrian
     */
    applyPedestrianCollision(ped) {
        const pedMass = 80;
        const totalMass = this.mass + pedMass;
        const impactSpeed = this.speed;

        // Vehicle barely slows down (huge mass ratio)
        this.speed *= (this.mass - pedMass * 0.1) / totalMass;
        this.speed = Math.max(0, this.speed);

        // Pedestrian gets knocked back
        const knockDir = Math.atan2(ped.x - this.x, ped.z - this.z);
        const knockForce = impactSpeed * (this.mass / totalMass);
        ped.x += Math.sin(knockDir) * knockForce * 0.3;
        ped.z += Math.cos(knockDir) * knockForce * 0.3;
        ped.speed = 0;

        // Pedestrian falls down (stunned)
        ped.stunTimer = 3 + Math.random() * 5;

        // Vehicle might stop if driver is shocked (random chance scales with speed)
        if (impactSpeed > 5 && Math.random() < 0.7) {
            this.inAccident = true;
            this.speed = 0;
            this.accidentTimer = 5 + Math.random() * 10;
        }

        return knockForce;
    }
}

// Vehicle subtypes with physical profiles
const VEHICLE_PROFILES = {
    sedan: { length: 4.5, width: 1.8, height: 1.4, mass: 1400, idm: { v0: 12, a: 1.4, b: 2.0, T: 1.5 } },
    suv: { length: 5.0, width: 2.0, height: 1.7, mass: 2000, idm: { v0: 11, a: 1.2, b: 2.0, T: 1.6 } },
    truck: { length: 7.0, width: 2.5, height: 2.5, mass: 5000, idm: { v0: 9, a: 0.8, b: 1.5, T: 2.0 } },
    motorcycle: { length: 2.2, width: 0.8, height: 1.2, mass: 250, idm: { v0: 14, a: 2.5, b: 3.0, T: 1.0 } },
    van: { length: 5.5, width: 2.0, height: 2.0, mass: 2500, idm: { v0: 10, a: 1.0, b: 1.8, T: 1.7 } },
};

const _SUBTYPES = ['sedan', 'sedan', 'sedan', 'suv', 'suv', 'truck', 'motorcycle', 'van'];
function _randomSubtype() {
    return _SUBTYPES[Math.floor(Math.random() * _SUBTYPES.length)];
}

// Car colors — cyberpunk palette
const _CAR_COLORS = [
    0xeeeeee, 0xcccccc, 0xaaaaaa,             // light grays (visible on dark roads)
    0xf0f0f0, 0xdddddd,                       // white/silver
    0x3355cc, 0x2244aa,                        // blue
    0xcc3333, 0xaa2222,                        // red
    0x228833,                                  // green
    0x111111,                                  // black (rare)
    0xffcc44,                                  // yellow/gold
    0x44cccc,                                  // cyan/teal
];

function _randomCarColor() {
    return _CAR_COLORS[Math.floor(Math.random() * _CAR_COLORS.length)];
}
