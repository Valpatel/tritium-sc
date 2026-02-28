// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

    const logs = [];
    page.on('console', msg => logs.push('[' + msg.type() + '] ' + msg.text()));
    page.on('pageerror', err => logs.push('[PAGE_ERROR] ' + err.message));

    await page.goto('http://localhost:8000', { waitUntil: 'networkidle', timeout: 15000 });
    await page.keyboard.press('w');
    await page.waitForTimeout(4000);

    await page.screenshot({ path: '/tmp/tritium-war-full.png', fullPage: false });
    console.log('Screenshot saved: /tmp/tritium-war-full.png');

    // Check state
    const info = await page.evaluate(() => {
        const r = {};
        const war3dCanvas = document.getElementById('war-3d-canvas');
        const viewWar = document.getElementById('view-war');
        const beginBtn = document.getElementById('war-begin-btn');

        r.view_visible = viewWar && !viewWar.classList.contains('hidden');
        r.canvas_3d = war3dCanvas ? { w: war3dCanvas.clientWidth, h: war3dCanvas.clientHeight } : null;
        r.use3D = (typeof warState === 'object') ? warState.use3D : false;
        r.war3d_init = (typeof war3d === 'object') ? war3d.initialized : false;
        r.begin_btn_visible = beginBtn ? beginBtn.style.display : 'not found';
        r.targets_count = (typeof assetState === 'object') ? Object.keys(assetState.simTargets || {}).length : 0;
        r.mode = (typeof warState === 'object') ? warState.mode : 'unknown';

        // Check HUD elements
        r.hud_mode = document.getElementById('war-mode') ? document.getElementById('war-mode').textContent : 'missing';
        r.hud_amy_panel = document.getElementById('war-amy-panel') ? document.getElementById('war-amy-panel').innerHTML.length : 0;
        r.hud_alert_log = document.getElementById('war-alert-log') ? document.getElementById('war-alert-log').innerHTML.length : 0;

        return r;
    });
    console.log('State:', JSON.stringify(info, null, 2));

    // Print relevant console errors
    for (const log of logs) {
        if (log.includes('Error') || log.includes('error') || log.includes('WAR')) {
            console.log(log);
        }
    }

    await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
