/**
 * TritiumLevelFormat - Tritium-SC battlespace layout format for the LevelSerializer plugin system
 *
 * A tritium-sc "level" = a battlespace layout for a residential property with
 * security cameras, robots, drones, monitoring zones, and patrol paths.
 *
 * Usage:
 *   const format = getTritiumLevelFormat();
 *   levelSerializer.setFormat(format);
 */

function getTritiumLevelFormat() {
    return {
        createEmpty: () => ({
            id: 'battlespace_' + Date.now(),
            name: 'Untitled Property',
            subtitle: '',
            // Property dimensions (meters)
            dimensions: {
                width: 60,
                depth: 60
            },
            // Main structure
            structures: {
                housePosition: { x: 0, z: 0 },
                houseWidth: 12,
                houseDepth: 10,
                houseHeight: 6,
                hasGarage: true,
                garagePosition: 'left',
                fenceHeight: 2,
                fenceSetback: 25
            },
            // Environment
            environment: {
                timeOfDay: 'night',
                ambientIntensity: 0.2,
                fogDensity: 0.005,
                streetLights: true,
                moonPhase: 'full'
            },
            // Amy AI commander configuration
            amy: {
                responseProtocol: 'alert',
                escalationDelay: 30,
                perimeterSensitivity: 'medium',
                enableVoice: true,
                enableAutonomous: false
            },
            objects: []
        }),

        serializeObject: (obj) => ({
            id: obj.id,
            type: obj.type,
            position: { x: obj.mesh.position.x, y: obj.mesh.position.y, z: obj.mesh.position.z },
            rotation: { x: obj.mesh.rotation.x, y: obj.mesh.rotation.y, z: obj.mesh.rotation.z },
            scale: { x: obj.mesh.scale.x, y: obj.mesh.scale.y, z: obj.mesh.scale.z },
            properties: obj.properties || {}
        }),

        deserializeObject: (data) => data,

        levelSettingsSchema: {
            sections: [
                {
                    title: 'Property Info',
                    fields: [
                        { key: 'name', label: 'Name', type: 'text', default: 'Untitled Property' },
                        { key: 'subtitle', label: 'Description', type: 'text', default: '' }
                    ]
                },
                {
                    title: 'Dimensions',
                    fields: [
                        { key: 'dimensions.width', label: 'Width (m)', type: 'number', min: 20, max: 200, step: 5, default: 60 },
                        { key: 'dimensions.depth', label: 'Depth (m)', type: 'number', min: 20, max: 200, step: 5, default: 60 }
                    ]
                },
                {
                    title: 'Main Structure',
                    fields: [
                        { key: 'structures.houseWidth', label: 'House Width (m)', type: 'number', min: 6, max: 30, step: 1, default: 12 },
                        { key: 'structures.houseDepth', label: 'House Depth (m)', type: 'number', min: 6, max: 25, step: 1, default: 10 },
                        { key: 'structures.houseHeight', label: 'House Height (m)', type: 'number', min: 3, max: 15, step: 1, default: 6 },
                        { key: 'structures.hasGarage', label: 'Garage', type: 'checkbox', default: true, checkboxLabel: 'Include garage' },
                        { key: 'structures.garagePosition', label: 'Garage Side', type: 'select', options: [
                            { value: 'left', label: 'Left' },
                            { value: 'right', label: 'Right' }
                        ], default: 'left' },
                        { key: 'structures.fenceHeight', label: 'Fence Height (m)', type: 'range', min: 0, max: 4, step: 0.5, default: 2, display: (v) => v.toFixed(1) + 'm' },
                        { key: 'structures.fenceSetback', label: 'Fence Setback (m)', type: 'number', min: 5, max: 50, step: 5, default: 25 }
                    ]
                },
                {
                    title: 'Environment',
                    fields: [
                        { key: 'environment.timeOfDay', label: 'Time of Day', type: 'select', options: [
                            { value: 'dawn', label: 'Dawn' },
                            { value: 'day', label: 'Day' },
                            { value: 'dusk', label: 'Dusk' },
                            { value: 'night', label: 'Night' },
                            { value: 'midnight', label: 'Midnight' }
                        ], default: 'night' },
                        { key: 'environment.ambientIntensity', label: 'Ambient Light', type: 'range', min: 0, max: 1, step: 0.05, default: 0.2, display: (v) => Math.round(v * 100) + '%' },
                        { key: 'environment.fogDensity', label: 'Fog Density', type: 'range', min: 0, max: 0.05, step: 0.001, default: 0.005, display: (v) => (v * 100).toFixed(1) + '%' },
                        { key: 'environment.streetLights', label: 'Street Lights', type: 'checkbox', default: true, checkboxLabel: 'Enable street lights' },
                        { key: 'environment.moonPhase', label: 'Moon Phase', type: 'select', options: [
                            { value: 'new', label: 'New Moon' },
                            { value: 'quarter', label: 'Quarter' },
                            { value: 'half', label: 'Half' },
                            { value: 'gibbous', label: 'Gibbous' },
                            { value: 'full', label: 'Full Moon' }
                        ], default: 'full' }
                    ]
                },
                {
                    title: 'Amy Configuration',
                    fields: [
                        { key: 'amy.responseProtocol', label: 'Response Protocol', type: 'select', options: [
                            { value: 'observe', label: 'Observe Only' },
                            { value: 'alert', label: 'Alert & Track' },
                            { value: 'engage', label: 'Active Engage' }
                        ], default: 'alert' },
                        { key: 'amy.escalationDelay', label: 'Escalation Delay (s)', type: 'number', min: 5, max: 120, step: 5, default: 30 },
                        { key: 'amy.perimeterSensitivity', label: 'Perimeter Sensitivity', type: 'select', options: [
                            { value: 'low', label: 'Low' },
                            { value: 'medium', label: 'Medium' },
                            { value: 'high', label: 'High' },
                            { value: 'maximum', label: 'Maximum' }
                        ], default: 'medium' },
                        { key: 'amy.enableVoice', label: 'Voice Alerts', type: 'checkbox', default: true, checkboxLabel: 'Enable Amy voice' },
                        { key: 'amy.enableAutonomous', label: 'Autonomous Mode', type: 'checkbox', default: false, checkboxLabel: 'Allow autonomous response' }
                    ]
                }
            ]
        }
    };
}

// Dual export pattern
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { getTritiumLevelFormat };
} else {
    window.TritiumLevelFormat = { getTritiumLevelFormat };
}
