// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
import { UnitType } from './base.js';
import { registerType } from './registry.js';
import Sensor from './sensor.js';

class Camera extends UnitType {
    static typeId = 'camera';
    static displayName = 'Camera';
    static iconLetter = 'C';
    static visionRadius = 30;
    static cotType = 'a-f-G-E-S-E';
    static ambientRadius = 5;
    static coneRange = 30;
    static coneAngle = 60;
    static coneSweeps = true;
    static coneSweepRPM = 1;

    /** Reuses Sensor draw -- same FOV cone + body + lens. */
    static draw(ctx, scale, color) {
        Sensor.draw(ctx, scale, color);
    }
}

registerType(Camera);
export default Camera;
