// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

    const logs = [];
    page.on('console', msg => logs.push('[' + msg.type() + '] ' + msg.text()));
    page.on('pageerror', err => logs.push('[ERROR] ' + err.message));

    await page.goto('http://localhost:8000', { waitUntil: 'networkidle', timeout: 15000 });
    await page.keyboard.press('w');
    await page.waitForTimeout(3000);

    await page.screenshot({ path: '/tmp/tritium-war-fix.png', fullPage: false });
    console.log('Screenshot saved');

    for (const log of logs) {
        if (log.includes('WAR') || log.includes('THREE') || log.includes('Error') || log.includes('error')) {
            console.log(log);
        }
    }

    const info = await page.evaluate(() => {
        const war3dCanvas = document.getElementById('war-3d-canvas');
        const war2dCanvas = document.getElementById('war-canvas');
        const viewWar = document.getElementById('view-war');
        const r = {};
        if (viewWar) r.view_war = { w: viewWar.clientWidth, h: viewWar.clientHeight, hidden: viewWar.classList.contains('hidden') };
        if (war3dCanvas) r.war_3d_canvas = { w: war3dCanvas.clientWidth, h: war3dCanvas.clientHeight, display: war3dCanvas.style.display };
        if (war2dCanvas) r.war_2d_canvas = { w: war2dCanvas.clientWidth, h: war2dCanvas.clientHeight, display: war2dCanvas.style.display };
        r.use3D = (typeof warState === 'object') ? warState.use3D : 'warState not defined';
        r.war3d_init = (typeof war3d === 'object') ? war3d.initialized : 'war3d not defined';
        if (typeof assetState === 'object') r.targets_count = Object.keys(assetState.simTargets || {}).length;
        return r;
    });
    console.log('State:', JSON.stringify(info, null, 2));

    await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
