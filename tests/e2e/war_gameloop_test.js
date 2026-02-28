// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const OUTDIR = '/tmp/tritium-test-gameloop';

(async () => {
    fs.mkdirSync(OUTDIR, { recursive: true });

    const browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

    const logs = [];
    page.on('console', msg => logs.push('[' + msg.type() + '] ' + msg.text()));
    page.on('pageerror', err => logs.push('[PAGE_ERROR] ' + err.message));

    console.log('Step 1: Loading TRITIUM-SC...');
    await page.goto('http://localhost:8000', { waitUntil: 'networkidle', timeout: 15000 });

    console.log('Step 2: Switching to War Room...');
    await page.keyboard.press('w');
    await page.waitForTimeout(3000);

    // Screenshot: War Room initial state
    await page.screenshot({ path: path.join(OUTDIR, '01-war-room-initial.png') });
    console.log('  Screenshot: 01-war-room-initial.png');

    // Check initial state
    let state = await page.evaluate(() => {
        const btn = document.getElementById('war-begin-btn');
        return {
            use3D: typeof warState === 'object' ? warState.use3D : false,
            begin_visible: btn ? btn.style.display : 'missing',
            targets: typeof assetState === 'object' ? Object.keys(assetState.simTargets || {}).length : 0,
        };
    });
    console.log('  State:', JSON.stringify(state));

    if (state.begin_visible !== 'block') {
        console.log('ERROR: BEGIN WAR button not visible, aborting game test');
        await browser.close();
        process.exit(1);
    }

    console.log('Step 3: Clicking BEGIN WAR...');
    await page.click('#war-begin-btn');
    await page.waitForTimeout(1000);
    await page.screenshot({ path: path.join(OUTDIR, '02-countdown.png') });
    console.log('  Screenshot: 02-countdown.png');

    // Wait for countdown
    console.log('Step 4: Waiting through countdown (5s)...');
    await page.waitForTimeout(6000);
    await page.screenshot({ path: path.join(OUTDIR, '03-wave-start.png') });
    console.log('  Screenshot: 03-wave-start.png');

    // Check game state
    state = await page.evaluate(() => {
        const scoreEl = document.getElementById('war-score');
        return {
            hud_game_state: typeof _hudState === 'object' ? _hudState.gameState : 'unknown',
            score_visible: scoreEl ? scoreEl.style.display : 'missing',
            targets: typeof assetState === 'object' ? Object.keys(assetState.simTargets || {}).length : 0,
        };
    });
    console.log('  Game state:', JSON.stringify(state));

    // Watch the battle for 30 seconds, taking screenshots every 10s
    for (let i = 0; i < 3; i++) {
        console.log(`Step 5.${i}: Watching battle (${(i+1)*10}s)...`);
        await page.waitForTimeout(10000);
        await page.screenshot({ path: path.join(OUTDIR, `04-battle-${(i+1)*10}s.png`) });
        console.log(`  Screenshot: 04-battle-${(i+1)*10}s.png`);

        state = await page.evaluate(() => {
            return {
                game_state: typeof _hudState === 'object' ? _hudState.gameState : 'unknown',
                score: typeof _hudState === 'object' ? _hudState.score : 0,
                kills: typeof _hudState === 'object' ? _hudState.kills : 0,
                wave: typeof _hudState === 'object' ? _hudState.wave : 0,
                targets: typeof assetState === 'object' ? Object.keys(assetState.simTargets || {}).length : 0,
            };
        });
        console.log(`  State: ${JSON.stringify(state)}`);
    }

    // Print any errors
    const errors = logs.filter(l => l.includes('ERROR') || l.includes('error'));
    if (errors.length > 0) {
        console.log('\nConsole errors:');
        for (const e of errors) console.log('  ' + e);
    }

    console.log('\nGame loop test complete. Screenshots in ' + OUTDIR);
    await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
