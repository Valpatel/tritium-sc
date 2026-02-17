/**
 * TritiumEditorPlugin - Registers all tritium-sc editor functionality
 *
 * Wires the general-purpose Graphlings editor with:
 * - Tritium battlespace level format
 * - Tritium security assets (cameras, robots, drones, structures, etc.)
 * - Playtest handler (pushes to grid.js 3D view)
 * - Level browser tabs (My Properties, Current Property)
 *
 * Usage:
 *   const editor = createTritiumEditor(document.body, TRITIUM);
 *   editor.init();
 *   editor.show();
 */

function initTritiumEditor(editor, tritiumApp) {
    // --- Register tritium level format ---
    if (editor.levelSerializer && typeof getTritiumLevelFormat === 'function') {
        editor.levelSerializer.setFormat(getTritiumLevelFormat());
    }

    // --- Register tritium assets ---
    if (editor.assetRegistry && typeof registerTritiumAssets === 'function') {
        registerTritiumAssets(editor.assetRegistry);
    }

    // --- Register general procedural assets (nature, props, barriers) ---
    if (editor.assetRegistry && typeof registerProceduralAssets === 'function') {
        registerProceduralAssets(editor.assetRegistry);
    }

    // --- Playtest handler: push to grid.js 3D view ---
    editor.setPlaytestHandler(function(action, data) {
        if (action === 'start') {
            // Serialize camera/asset positions for grid.js
            const cameraPositions = {};
            const assetPositions = [];

            if (data && data.objects) {
                data.objects.forEach(obj => {
                    const type = obj.type || obj.properties?.assetId || '';

                    // Camera assets → push to grid.js camera positions
                    if (type.includes('camera') || type.includes('ptz') || type.includes('dome')) {
                        const channel = obj.properties?.channel || obj.properties?.params?.channel || 1;
                        cameraPositions['ch' + channel] = {
                            x: obj.position?.x || 0,
                            y: obj.position?.y || 0,
                            z: obj.position?.z || 0,
                            fov: obj.properties?.params?.fov || 60,
                            range: obj.properties?.params?.range || 15
                        };
                    }

                    // All assets → position list for 3D overlay
                    assetPositions.push({
                        type: type,
                        name: obj.name || type,
                        position: obj.position || { x: 0, y: 0, z: 0 },
                        rotation: obj.rotation || { x: 0, y: 0, z: 0 }
                    });
                });
            }

            // Push to localStorage where grid.js reads (line 28)
            try {
                localStorage.setItem('tritium_camera_positions', JSON.stringify(cameraPositions));
                localStorage.setItem('tritium_editor_assets', JSON.stringify(assetPositions));
            } catch (e) {
                console.warn('[TritiumEditor] Failed to push positions:', e);
            }

            // Switch to 3D tab if available
            if (tritiumApp && typeof tritiumApp.switchView === 'function') {
                editor.hide();
                tritiumApp.switchView('3d');
                // Trigger grid reload
                if (typeof initThreeJS === 'function') {
                    initThreeJS();
                }
            }
        } else if (action === 'stop') {
            editor.show();
        }
    });

    // --- Level load handler ---
    editor.setLevelLoadHandler(function(levelId, tabId) {
        if (tabId === 'current_property') {
            return _loadCurrentPropertyData(tritiumApp);
        }

        if (tabId === 'saved') {
            return _loadSavedProperty(levelId);
        }

        return null;
    });

    // --- Level browser provider ---
    editor.setLevelBrowserProvider(function(action, params) {
        if (action === 'getTabs') {
            return [
                { id: 'saved', label: 'My Properties' },
                { id: 'current_property', label: 'Current Property' }
            ];
        }

        if (action === 'getItems') {
            const tabId = params && params.tabId;

            if (tabId === 'saved') {
                return _getSavedProperties();
            }

            if (tabId === 'current_property') {
                return [{
                    id: 'live_property',
                    name: 'Current Property',
                    subtitle: 'Live camera data from NVR',
                    thumbnail: null,
                    isBuiltIn: true
                }];
            }

            return [];
        }

        if (action === 'load') {
            const levelId = params && params.levelId;
            const tabId = params && params.tabId;

            if (tabId === 'current_property') {
                return _loadCurrentPropertyData(tritiumApp);
            }

            if (tabId === 'saved') {
                return _loadSavedProperty(levelId);
            }

            return null;
        }

        if (action === 'delete') {
            const levelId = params && params.levelId;
            return _deleteSavedProperty(levelId);
        }

        return null;
    });

    // Make editor available globally
    window.tritiumEditor = editor;

    return editor;
}

// ================================================================
// LEVEL BROWSER HELPERS
// ================================================================

function _getSavedProperties() {
    const levels = [];
    for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key && key.startsWith('tritium_property_')) {
            try {
                const data = JSON.parse(localStorage.getItem(key));
                levels.push({
                    id: key,
                    name: data.name || 'Untitled Property',
                    subtitle: data.subtitle || '',
                    thumbnail: data._thumbnail || null,
                    modifiedAt: data._modifiedAt || 0
                });
            } catch (e) {
                // Skip corrupt entries
            }
        }
    }
    levels.sort((a, b) => (b.modifiedAt || 0) - (a.modifiedAt || 0));
    return levels;
}

function _loadSavedProperty(levelId) {
    try {
        const data = localStorage.getItem(levelId);
        if (data) return JSON.parse(data);
    } catch (e) {
        console.error('[TritiumEditor] Failed to load saved property:', e);
    }
    return null;
}

function _deleteSavedProperty(levelId) {
    try {
        localStorage.removeItem(levelId);
        return true;
    } catch (e) {
        console.error('[TritiumEditor] Failed to delete property:', e);
        return false;
    }
}

function _loadCurrentPropertyData(tritiumApp) {
    // Pull live camera data from TRITIUM.state.channels
    const level = getTritiumLevelFormat().createEmpty();
    level.name = 'Live Property';
    level.subtitle = 'Generated from active camera feeds';

    if (tritiumApp && tritiumApp.state && tritiumApp.state.channels) {
        const channels = tritiumApp.state.channels;
        level.objects = channels.map((ch, idx) => {
            // Load stored camera positions if available
            const positions = JSON.parse(localStorage.getItem('tritium_camera_positions') || '{}');
            const posKey = 'ch' + ch.channel;
            const pos = positions[posKey] || { x: (idx % 4 - 1.5) * 8, y: 3, z: Math.floor(idx / 4) * 8 - 10 };

            return {
                id: 'cam_ch' + ch.channel,
                type: 'security_camera',
                position: { x: pos.x, y: 0, z: pos.z },
                rotation: { x: 0, y: 0, z: 0 },
                scale: { x: 1, y: 1, z: 1 },
                properties: {
                    assetId: 'security_camera',
                    params: {
                        fov: 60,
                        range: 15,
                        height: pos.y || 3,
                        channel: ch.channel
                    },
                    channelName: ch.name || ('Channel ' + ch.channel),
                    isLive: true
                }
            };
        });
    }

    return level;
}

// ================================================================
// CONVENIENCE: Create a fully-configured tritium editor
// ================================================================

function createTritiumEditor(container, tritiumApp) {
    const registry = new AssetRegistry();
    const serializer = new LevelSerializer();

    const editor = new EditorCore({
        appName: 'TRITIUM Battlespace Editor',
        container: container || document.body,
        assetRegistry: registry,
        levelSerializer: serializer,
        autoSaveKey: 'tritium_editor_autosave'
    });

    initTritiumEditor(editor, tritiumApp);

    return editor;
}

// Dual export pattern
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { initTritiumEditor, createTritiumEditor };
} else {
    window.TritiumEditorPlugin = { initTritiumEditor, createTritiumEditor };
}
