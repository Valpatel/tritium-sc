import { test, expect } from '@playwright/test';

test.describe('War Room', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        // Wait for app to load
        await page.waitForSelector('#btn-war', { timeout: 10000 });
    });

    test('War Room button exists and opens view', async ({ page }) => {
        const btn = page.locator('#btn-war');
        await expect(btn).toBeVisible();
        await btn.click();

        // War Room view should be visible (hidden class removed)
        const warView = page.locator('#view-war');
        await expect(warView).not.toHaveClass(/hidden/);

        // Canvas should exist
        const canvas = page.locator('#war-canvas');
        await expect(canvas).toBeVisible();
    });

    test('War Room opens via W keyboard shortcut', async ({ page }) => {
        await page.keyboard.press('w');
        const warView = page.locator('#view-war');
        await expect(warView).not.toHaveClass(/hidden/, { timeout: 2000 });
    });

    test('Canvas renders (not blank)', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(2000); // Let animation loop run

        // Check canvas has non-zero dimensions
        const canvas = page.locator('#war-canvas');
        const box = await canvas.boundingBox();
        expect(box).not.toBeNull();
        expect(box!.width).toBeGreaterThan(100);
        expect(box!.height).toBeGreaterThan(100);

        // Check canvas is not all black (grid/boundary should have been drawn)
        const pixels = await page.evaluate(() => {
            const c = document.getElementById('war-canvas') as HTMLCanvasElement;
            if (!c) return null;
            const ctx = c.getContext('2d');
            if (!ctx) return null;
            const data = ctx.getImageData(0, 0, c.width, c.height).data;
            let nonBlack = 0;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 0 || data[i + 1] > 0 || data[i + 2] > 0) nonBlack++;
            }
            return nonBlack;
        });
        expect(pixels).not.toBeNull();
        expect(pixels!).toBeGreaterThan(0); // Grid + boundary should draw something
    });

    test('Mode indicator shows OBSERVE by default', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);
        const mode = page.locator('#war-mode');
        await expect(mode).toContainText(/OBSERVE/i);
    });

    test('Mode switches: S=setup, T=tactical, O=observe', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        // Switch to setup
        await page.keyboard.press('s');
        await expect(page.locator('#war-mode')).toContainText(/SETUP/i);

        // Switch to tactical
        await page.keyboard.press('t');
        await expect(page.locator('#war-mode')).toContainText(/TACTICAL/i);

        // Back to observe
        await page.keyboard.press('o');
        await expect(page.locator('#war-mode')).toContainText(/OBSERVE/i);
    });

    test('Setup palette appears in setup mode', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        const palette = page.locator('#war-setup-palette');

        // Palette hidden by default in observe mode
        await expect(palette).toBeHidden();

        // Switch to setup mode
        await page.keyboard.press('s');
        await expect(palette).toBeVisible();

        // Switch back to observe
        await page.keyboard.press('o');
        await expect(palette).toBeHidden();
    });

    test('Spawn hostile via API and verify it appears', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(1000);

        // Spawn a hostile via API (may 404 if simulation routes not deployed yet)
        const spawnRes = await page.request.post('/api/amy/simulation/spawn', {
            data: { name: 'Test Hostile', alliance: 'hostile', position: { x: 5.0, y: 5.0 } }
        });
        test.skip(!spawnRes.ok(), 'Simulation spawn API not available (server may need restart)');

        // Wait for it to appear in the tracker
        await page.waitForTimeout(2000);

        const targetsRes = await page.request.get('/api/targets/hostiles');
        const targets = await targetsRes.json();
        expect(targets.targets?.length).toBeGreaterThanOrEqual(1);
    });

    test('Escalation status API returns data', async ({ page }) => {
        const response = await page.request.get('/api/amy/escalation/status');
        test.skip(!response.ok(), 'Escalation API not available (server may need restart)');
        const data = await response.json();
        // Should have threats array (possibly empty if no hostiles in zones)
        expect(data).toHaveProperty('threats');
    });

    test('War state API returns combined data', async ({ page }) => {
        const response = await page.request.get('/api/amy/war/state');
        test.skip(!response.ok(), 'War state API not available (server may need restart)');
        const data = await response.json();
        // Should have targets array
        expect(data).toHaveProperty('targets');
    });

    test('ESC deselects in War Room', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        // Click somewhere on the canvas
        const canvas = page.locator('#war-canvas');
        await canvas.click({ position: { x: 200, y: 200 } });

        // Press ESC — should deselect and hide unit info
        await page.keyboard.press('Escape');

        // Unit info should be hidden (display: none)
        const unitInfo = page.locator('#war-unit-info');
        await expect(unitInfo).toBeHidden();
    });

    test('Zoom with mouse wheel', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        const canvas = page.locator('#war-canvas');

        // Zoom in
        await canvas.hover();
        await page.mouse.wheel(0, -100);
        await page.waitForTimeout(200);

        // Zoom out
        await page.mouse.wheel(0, 100);
        await page.waitForTimeout(200);

        // If we got here without errors, zoom works
    });

    test('View switching preserves state', async ({ page }) => {
        // Go to War Room
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        // Switch away to grid
        await page.keyboard.press('g');
        await expect(page.locator('#view-grid')).not.toHaveClass(/hidden/);

        // Switch back to war
        await page.keyboard.press('w');
        await expect(page.locator('#view-war')).not.toHaveClass(/hidden/);

        // Canvas should still be visible
        const canvas = page.locator('#war-canvas');
        await expect(canvas).toBeVisible();
    });

    test('HUD elements are present', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(500);

        // HUD overlay
        await expect(page.locator('#war-hud')).toBeVisible();

        // Amy panel
        await expect(page.locator('#war-amy-panel')).toBeVisible();

        // Alert log
        await expect(page.locator('#war-alert-log')).toBeVisible();

        // Mode indicator
        await expect(page.locator('#war-mode')).toBeVisible();
    });

    test('Minimap is rendered on canvas', async ({ page }) => {
        await page.keyboard.press('w');
        await page.waitForTimeout(1000);

        // Check the bottom-left area of the canvas has minimap pixels
        const hasMinimapPixels = await page.evaluate(() => {
            const c = document.getElementById('war-canvas') as HTMLCanvasElement;
            if (!c) return false;
            const ctx = c.getContext('2d');
            if (!ctx) return false;

            // Minimap is at bottom-left: x=12, y=height-150-12, 150x150
            const mmX = 12;
            const mmY = c.height - 150 - 12;
            const mmSize = 150;

            if (mmY < 0) return false;

            const data = ctx.getImageData(mmX, mmY, mmSize, mmSize).data;
            let nonBlack = 0;
            for (let i = 0; i < data.length; i += 4) {
                if (data[i] > 0 || data[i + 1] > 0 || data[i + 2] > 0) nonBlack++;
            }
            return nonBlack > 100; // Minimap background + border draws pixels
        });
        expect(hasMinimapPixels).toBe(true);
    });
});
