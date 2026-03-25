// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.

/**
 * MOBIL Lane Change Model — Minimizing Overall Braking Induced by Lane Changes.
 *
 * Evaluates whether a lane change is SAFE and BENEFICIAL using IDM accelerations.
 * - Safety: new follower in target lane can brake within comfortable limits
 * - Incentive: driver's gain outweighs weighted cost to others
 *
 * Works with the edge-based SimVehicle model where vehicles track:
 *   edge, u (position along edge), direction, laneIdx, speed
 *
 * Reference: Kesting, Treiber, Helbing (2007)
 * "General Lane-Changing Model MOBIL for Car-Following Models"
 */

import { idmAcceleration } from '/lib/sim/idm.js';

/** Default MOBIL parameters. */
export const MOBIL_DEFAULTS = {
    politeness: 0.3,    // 0=selfish, 1=altruistic
    threshold: 0.2,     // m/s² — minimum incentive to change
    bSafe: 4.0,         // m/s² — max safe deceleration for new follower
    minGap: 5.0,        // m — minimum gap required in target lane
};

/**
 * Find the nearest vehicle ahead and behind in a specific lane on a specific edge.
 *
 * @param {Object} car — the subject vehicle
 * @param {number} targetLane — lane index to search
 * @param {Array} nearbyVehicles — vehicles on the same edge
 * @returns {{ ahead: Object|null, aheadGap: number, behind: Object|null, behindGap: number }}
 */
export function findNeighborsInLane(car, targetLane, nearbyVehicles) {
    let aheadGap = Infinity, behindGap = Infinity;
    let ahead = null, behind = null;

    for (const other of nearbyVehicles) {
        if (other === car) continue;
        if (other.edge !== car.edge) continue;
        if (other.direction !== car.direction) continue;
        if (other.laneIdx !== targetLane) continue;

        const gap = (other.u - car.u) * car.direction;
        if (gap > 0 && gap < aheadGap) {
            aheadGap = gap;
            ahead = other;
        } else if (gap < 0 && -gap < behindGap) {
            behindGap = -gap;
            behind = other;
        }
    }

    // Subtract car lengths for bumper-to-bumper gaps
    if (ahead) {
        aheadGap = Math.max(0.1, aheadGap - (car.length || 4.5) / 2 - (ahead.length || 4.5) / 2);
    }
    if (behind) {
        behindGap = Math.max(0.1, behindGap - (car.length || 4.5) / 2 - (behind.length || 4.5) / 2);
    }

    return { ahead, aheadGap, behind, behindGap };
}

/**
 * Evaluate whether a lane change to targetLane is safe and beneficial.
 *
 * @param {Object} car — the vehicle considering a lane change
 * @param {number} targetLane — target lane index
 * @param {Array} nearbyVehicles — all vehicles on the same edge
 * @param {Object} [params] — MOBIL parameters
 * @returns {{ shouldChange: boolean, incentive: number, reason: string }}
 */
export function evaluateLaneChange(car, targetLane, nearbyVehicles, params = MOBIL_DEFAULTS) {
    const { politeness, threshold, bSafe, minGap } = params;
    const idmP = car.idm;

    // Current lane neighbors
    const cur = findNeighborsInLane(car, car.laneIdx, nearbyVehicles);

    // My current acceleration
    const a_c = idmAcceleration(
        car.speed,
        cur.aheadGap,
        cur.ahead ? cur.ahead.speed : car.speed,
        idmP
    );

    // Target lane neighbors
    const tgt = findNeighborsInLane(car, targetLane, nearbyVehicles);

    // Gap check
    if (tgt.aheadGap < minGap || tgt.behindGap < minGap) {
        return { shouldChange: false, incentive: -Infinity, reason: 'insufficient_gap' };
    }

    // My acceleration in target lane
    const a_c_prime = idmAcceleration(
        car.speed,
        tgt.aheadGap,
        tgt.ahead ? tgt.ahead.speed : car.speed,
        idmP
    );

    // New follower in target lane
    const newFollower = tgt.behind;
    if (newFollower) {
        const nfIdm = newFollower.idm || idmP;

        // New follower's current acceleration (before lane change)
        // Gap from new follower to the car that was ahead of it (which is ahead of our insertion point)
        const nfCurrentGap = tgt.behindGap + (car.length || 4.5) +
            (tgt.aheadGap < Infinity ? tgt.aheadGap : 100);
        const a_n = idmAcceleration(
            newFollower.speed,
            nfCurrentGap,
            tgt.ahead ? tgt.ahead.speed : newFollower.speed,
            nfIdm
        );

        // New follower's acceleration after we insert (gap is now to us)
        const a_n_prime = idmAcceleration(
            newFollower.speed,
            tgt.behindGap,
            car.speed,
            nfIdm
        );

        // Safety criterion
        if (a_n_prime < -bSafe) {
            return { shouldChange: false, incentive: -Infinity, reason: 'unsafe_new_follower' };
        }

        // Old follower in current lane
        let a_o = 0, a_o_prime = 0;
        const oldFollower = cur.behind;
        if (oldFollower) {
            const ofIdm = oldFollower.idm || idmP;
            a_o = idmAcceleration(
                oldFollower.speed,
                cur.behindGap,
                car.speed,
                ofIdm
            );
            // After we leave, old follower's leader becomes our current leader
            const newGapForOld = cur.behindGap + (car.length || 4.5) + cur.aheadGap;
            a_o_prime = idmAcceleration(
                oldFollower.speed,
                newGapForOld,
                cur.ahead ? cur.ahead.speed : oldFollower.speed,
                ofIdm
            );
        }

        // Incentive criterion
        const myAdvantage = a_c_prime - a_c;
        const othersDisadvantage = (a_n - a_n_prime) + (a_o - a_o_prime);
        const incentive = myAdvantage - politeness * othersDisadvantage;

        return {
            shouldChange: incentive > threshold,
            incentive,
            reason: incentive > threshold ? 'beneficial' : 'insufficient_incentive',
        };
    }

    // No new follower — empty lane, only check my advantage
    const incentive = a_c_prime - a_c;
    return {
        shouldChange: incentive > threshold,
        incentive,
        reason: incentive > threshold ? 'beneficial_empty_lane' : 'insufficient_incentive',
    };
}

/**
 * Decide best lane change direction for a vehicle.
 * Checks both adjacent lanes in the same travel direction.
 *
 * @param {Object} car — the vehicle (needs edge.lanesPerDir, laneIdx, direction)
 * @param {Array} nearbyVehicles — vehicles on the same edge
 * @param {Object} [params] — MOBIL parameters
 * @returns {{ direction: 'left'|'right'|null, targetLane: number|null, incentive: number }}
 */
export function decideLaneChange(car, nearbyVehicles, params = MOBIL_DEFAULTS) {
    const numLanes = car.edge.lanesPerDir || 1;
    if (numLanes <= 1) {
        return { direction: null, targetLane: null, incentive: -Infinity };
    }

    const currentLane = car.laneIdx;
    let bestDirection = null;
    let bestLane = null;
    let bestIncentive = -Infinity;

    // Check left (lower lane index = more toward center)
    if (currentLane > 0) {
        const result = evaluateLaneChange(car, currentLane - 1, nearbyVehicles, params);
        if (result.shouldChange && result.incentive > bestIncentive) {
            bestDirection = 'left';
            bestLane = currentLane - 1;
            bestIncentive = result.incentive;
        }
    }

    // Check right (higher lane index = more toward edge)
    if (currentLane < numLanes - 1) {
        const result = evaluateLaneChange(car, currentLane + 1, nearbyVehicles, params);
        if (result.shouldChange && result.incentive > bestIncentive) {
            bestDirection = 'right';
            bestLane = currentLane + 1;
            bestIncentive = result.incentive;
        }
    }

    return { direction: bestDirection, targetLane: bestLane, incentive: bestIncentive };
}
