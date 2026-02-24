/**
 * Unit-type registry.
 *
 * Each type file calls registerType() at import time so that the
 * registry is populated as soon as index.js is loaded.
 */

const _types = new Map();

/** Register a UnitType subclass by its static typeId. */
export function registerType(TypeClass) {
    _types.set(TypeClass.typeId, TypeClass);
}

/** Look up a registered type class (or null). */
export function getType(typeId) {
    return _types.get(typeId) || null;
}

/** Return an array of all registered type classes. */
export function allTypes() {
    return [..._types.values()];
}

/** Return the icon letter for a typeId, or '?' if unknown. */
export function getIconLetter(typeId) {
    let t = getType(typeId);
    if (!t) {
        // Fallback: resolve fuzzy type name to a registered type
        const resolved = resolveTypeId(typeId);
        if (resolved !== typeId) t = getType(resolved);
    }
    return t ? t.iconLetter : '?';
}

/** Return the vision radius for a typeId, or 25 as the default. */
export function getVisionRadius(typeId) {
    let t = getType(typeId);
    if (!t) {
        const resolved = resolveTypeId(typeId);
        if (resolved !== typeId) t = getType(resolved);
    }
    return t ? t.visionRadius : 25;
}

/** Return the full vision profile for a typeId. */
export function getVisionProfile(typeId) {
    let t = getType(typeId);
    if (!t) {
        const resolved = resolveTypeId(typeId);
        if (resolved !== typeId) t = getType(resolved);
    }
    if (t) {
        return {
            ambient: t.ambientRadius,
            coneRange: t.coneRange,
            coneAngle: t.coneAngle,
            coneSweeps: t.coneSweeps,
            coneSweepRPM: t.coneSweepRPM,
        };
    }
    return { ambient: 10, coneRange: 0, coneAngle: 0, coneSweeps: false, coneSweepRPM: 0 };
}

/** Return the CoT type code for a typeId, or 'a-u-G' (unknown ground) as the default. */
export function getCotType(typeId) {
    let t = getType(typeId);
    if (!t) {
        const resolved = resolveTypeId(typeId);
        if (resolved !== typeId) t = getType(resolved);
    }
    return t ? t.cotType : 'a-u-G';
}

/**
 * Fuzzy-match a raw type string (+ optional alliance) to a registered
 * typeId.  Returns the canonical typeId or the raw string unchanged if
 * no match is found.
 */
export function resolveTypeId(rawType, alliance) {
    // Direct match first
    if (_types.has(rawType)) return rawType;

    // Fuzzy matching
    if (rawType.includes('turret') || rawType.includes('sentry')) return 'turret';
    if (rawType.includes('drone')) return 'drone';
    if (rawType.includes('rover') || rawType.includes('interceptor') || rawType.includes('patrol')) return 'rover';
    if (rawType.includes('tank') || rawType.includes('truck')) return 'tank';
    if (rawType === 'apc') return 'tank';
    if (rawType === 'hostile_vehicle' || rawType === 'vehicle') return 'tank';
    if (rawType === 'hostile_leader') return 'hostile_person';
    if (rawType.includes('camera') || rawType.includes('sensor')) return 'sensor';
    if (rawType === 'person' && alliance === 'hostile') return 'hostile_person';
    if (rawType === 'person' && alliance === 'neutral') return 'neutral_person';
    if (rawType === 'hostile_kid') return 'hostile_person';
    if (rawType === 'animal') return 'neutral_person';
    if (rawType === 'mesh_radio' || rawType === 'meshtastic') return 'sensor';

    return rawType;
}
