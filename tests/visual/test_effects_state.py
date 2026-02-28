# Created by Matthew Valancy
# Copyright 2026 Valpatel Software LLC
# Licensed under AGPL-3.0 — see LICENSE for details.
"""Quick diagnostic: check Three.js effects state after injecting combat events."""

import time
import json
from playwright.sync_api import sync_playwright


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto("http://localhost:8000", wait_until="networkidle")
        time.sleep(3)

        # Reset
        page.evaluate("() => fetch('/api/game/reset', {method:'POST'}).then(r=>r.json())")
        time.sleep(1)

        # Check _mapState BEFORE
        state = page.evaluate("""() => {
            const s = window._mapState || {};
            return {
                hasMap: !!s.map,
                hasThreeScene: !!s.threeScene,
                hasThreeRoot: !!s.threeRoot,
                threeRootChildren: s.threeRoot ? s.threeRoot.children.length : 0,
                unitMeshCount: s.unitMeshes ? Object.keys(s.unitMeshes).length : 0,
                effectsCount: s.effects ? s.effects.length : 0,
                effectsActive: s.effectsActive || false,
                hasRefMatrix: !!s._refMatrix,
                ms: s._ms || 'N/A',
            };
        }""")
        print("State BEFORE effects:", json.dumps(state, indent=2))

        # Inject a combat:elimination at (0, 50)
        page.evaluate("""() => {
            window.EventBus.emit('combat:elimination', {
                target_id: 'test',
                target_name: 'Test Target',
                interceptor_name: 'Debug',
                position: { x: 0, y: 50 },
                method: 'heavy_cannon'
            });
        }""")
        time.sleep(0.1)

        # Check state AFTER
        state2 = page.evaluate("""() => {
            const s = window._mapState || {};
            const effects = s.effects || [];
            const info = [];
            for (const fx of effects) {
                const meshPositions = fx.meshes ? fx.meshes.map(m => ({
                    x: m.position.x.toFixed(2),
                    y: m.position.y.toFixed(2),
                    z: m.position.z.toFixed(2),
                    visible: m.visible,
                    opacity: m.material ? m.material.opacity : 'N/A'
                })) : [];
                info.push({
                    type: fx.type,
                    duration: fx.duration,
                    meshCount: fx.meshes ? fx.meshes.length : 0,
                    meshPositions,
                    age: Math.round(performance.now() - fx.startTime)
                });
            }
            return {
                effectsCount: effects.length,
                effectsActive: s.effectsActive || false,
                threeRootChildren: s.threeRoot ? s.threeRoot.children.length : 0,
                effects: info,
            };
        }""")
        print("State AFTER effects:", json.dumps(state2, indent=2))

        # Also inject a projectile and check
        page.evaluate("""() => {
            window.EventBus.emit('combat:projectile', {
                source_id: 'fake',
                source_pos: { x: -50, y: 0 },
                target_id: 'fake2',
                target_pos: { x: 50, y: 0 },
                projectile_type: 'nerf_dart',
                damage: 10
            });
        }""")
        time.sleep(0.05)

        state3 = page.evaluate("""() => {
            const s = window._mapState || {};
            const effects = s.effects || [];
            const info = [];
            for (const fx of effects) {
                const meshPositions = fx.meshes ? fx.meshes.map(m => ({
                    x: m.position.x.toFixed(2),
                    y: m.position.y.toFixed(2),
                    z: m.position.z.toFixed(2),
                })) : [];
                info.push({
                    type: fx.type,
                    meshCount: fx.meshes ? fx.meshes.length : 0,
                    firstMeshPos: meshPositions[0] || null,
                    source: fx.source ? {x: fx.source.x.toFixed(2), y: fx.source.y.toFixed(2)} : null,
                    target: fx.target ? {x: fx.target.x.toFixed(2), y: fx.target.y.toFixed(2)} : null,
                });
            }
            return {
                effectsCount: effects.length,
                threeRootChildren: s.threeRoot ? s.threeRoot.children.length : 0,
                effects: info,
            };
        }""")
        print("State AFTER projectile:", json.dumps(state3, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
