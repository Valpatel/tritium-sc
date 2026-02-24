/**
 * Unit-types package entry point.
 *
 * Importing this module registers every built-in unit type with the
 * registry. Consumers only need:
 *
 *     import { getType, resolveTypeId } from './unit-types/index.js';
 */

// Import each type (self-registers via registerType)
import './rover.js';
import './drone.js';
import './turret.js';
import './tank.js';
import './hostile-person.js';
import './neutral-person.js';
import './sensor.js';
import './camera.js';

// Re-export registry API
export {
    registerType,
    getType,
    allTypes,
    getIconLetter,
    getVisionRadius,
    getVisionProfile,
    resolveTypeId,
} from './registry.js';
