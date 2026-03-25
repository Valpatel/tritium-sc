// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * RL Hooks — reinforcement learning interface for city simulation.
 *
 * Provides an observation/action/reward API that external RL agents
 * can use to learn traffic signal control policies.
 *
 * Observation: per-intersection vehicle counts, queue lengths, wait times
 * Action: set signal phase for each intersection
 * Reward: negative total wait time (minimize delay)
 *
 * Can be driven by:
 * - Python RL agent via WebSocket (future)
 * - llama-server for LLM-based control (experimental)
 * - Built-in greedy/adaptive heuristics
 */

export class RLHooks {
    /**
     * @param {Object} trafficMgr — TrafficControllerManager
     * @param {Object} roadNetwork — RoadNetwork
     */
    constructor(trafficMgr, roadNetwork) {
        this.trafficMgr = trafficMgr;
        this.roadNetwork = roadNetwork;
        this.enabled = false;
        this._episodeReward = 0;
        this._stepCount = 0;
        this._lastObservation = null;
    }

    /**
     * Get current observation for all controlled intersections.
     * @param {Array} vehicles — current vehicle list
     * @returns {Object} observation per intersection
     */
    getObservation(vehicles) {
        if (!this.trafficMgr) return {};

        const obs = {};
        for (const nodeId in this.trafficMgr.controllers) {
            const ctrl = this.trafficMgr.controllers[nodeId];
            const node = ctrl.node;

            // Count vehicles approaching this intersection (within 50m)
            let approaching = 0;
            let stopped = 0;
            let totalWait = 0;

            for (const car of vehicles) {
                if (!car.edge) continue;
                const approachNode = car.direction > 0 ? car.edge.to : car.edge.from;
                if (approachNode !== nodeId) continue;

                const remaining = car.direction > 0
                    ? car.edge.length - car.u
                    : car.u;

                if (remaining < 50) {
                    approaching++;
                    if (car.speed < 0.5) {
                        stopped++;
                        totalWait += 1;  // accumulate wait seconds
                    }
                }
            }

            obs[nodeId] = {
                approaching,
                stopped,
                totalWait,
                currentPhase: ctrl.currentPhase,
                phaseTimer: Math.round(ctrl.phaseTimer * 10) / 10,
                edgeCount: ctrl.edges.length,
                x: node.x,
                z: node.z,
            };
        }

        this._lastObservation = obs;
        return obs;
    }

    /**
     * Apply an action — set signal phase for an intersection.
     * @param {string} nodeId — intersection node ID
     * @param {number} phaseIndex — phase to switch to (0-based)
     * @returns {boolean} whether action was applied
     */
    setPhase(nodeId, phaseIndex) {
        if (!this.trafficMgr) return false;
        const ctrl = this.trafficMgr.controllers[nodeId];
        if (!ctrl) return false;
        if (phaseIndex < 0 || phaseIndex >= ctrl.phases.length) return false;

        ctrl.currentPhase = phaseIndex;
        ctrl.phaseTimer = 0;
        return true;
    }

    /**
     * Compute reward for the current step.
     * Reward = negative total vehicles stopped (minimize delay).
     * @param {Array} vehicles
     * @returns {number} reward (higher is better)
     */
    computeReward(vehicles) {
        let totalStopped = 0;
        for (const car of vehicles) {
            if (car.speed < 0.5 && !car.parked) totalStopped++;
        }
        const reward = -totalStopped;
        this._episodeReward += reward;
        this._stepCount++;
        return reward;
    }

    /**
     * Reset episode tracking.
     */
    resetEpisode() {
        this._episodeReward = 0;
        this._stepCount = 0;
    }

    /**
     * Get episode statistics.
     */
    getEpisodeStats() {
        return {
            totalReward: this._episodeReward,
            steps: this._stepCount,
            avgReward: this._stepCount > 0 ? this._episodeReward / this._stepCount : 0,
            intersections: this.trafficMgr
                ? Object.keys(this.trafficMgr.controllers).length
                : 0,
        };
    }

    /**
     * Simple greedy heuristic: switch to phase with most approaching vehicles.
     * Useful as a baseline to compare against learned policies.
     * @param {Array} vehicles
     */
    greedyStep(vehicles) {
        if (!this.trafficMgr) return;

        for (const nodeId in this.trafficMgr.controllers) {
            const ctrl = this.trafficMgr.controllers[nodeId];

            // Count approaching vehicles per edge group
            const edgeCounts = new Map();
            for (const car of vehicles) {
                if (!car.edge) continue;
                const approachNode = car.direction > 0 ? car.edge.to : car.edge.from;
                if (approachNode !== nodeId) continue;
                const remaining = car.direction > 0 ? car.edge.length - car.u : car.u;
                if (remaining < 30) {
                    edgeCounts.set(car.edge.id, (edgeCounts.get(car.edge.id) || 0) + 1);
                }
            }

            // Find phase with most approaching vehicles
            let bestPhase = 0;
            let bestCount = 0;
            for (let i = 0; i < ctrl.phases.length; i++) {
                const phase = ctrl.phases[i];
                if (phase.type !== 'green') continue;
                let count = 0;
                for (const edgeId of phase.greenEdges) {
                    count += edgeCounts.get(edgeId) || 0;
                }
                if (count > bestCount) {
                    bestCount = count;
                    bestPhase = i;
                }
            }

            // Only switch if significantly more vehicles waiting
            if (bestCount > 3 && ctrl.currentPhase !== bestPhase) {
                ctrl.currentPhase = bestPhase;
                ctrl.phaseTimer = 0;
            }
        }
    }
}
