// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
const { chromium } = require("playwright");

const ADDRESS = "1 Dr Carlton B Goodlett Pl, San Francisco, CA";
const BASE = "http://localhost:8000";

async function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async () => {
  const browser = await chromium.launch({
    headless: false,
    args: ['--enable-webgl', '--ignore-gpu-blocklist', '--use-gl=angle']
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });

  // Collect all console messages
  const logs = [];
  const errors = [];
  page.on("console", msg => {
    logs.push(msg.type() + ": " + msg.text());
    if (msg.type() === "error") errors.push(msg.text());
  });
  page.on("pageerror", err => errors.push("PAGEERROR: " + err.message));

  console.log("=== STEP 1: Load page ===");
  await page.goto(BASE);
  await sleep(3000);

  console.log("=== STEP 2: Open War Room (press W) ===");
  await page.keyboard.press("w");
  await sleep(3000);

  // Check what loaded
  const step2 = await page.evaluate(() => {
    return {
      currentView: window.state ? window.state.currentView : "unknown",
      warState: !!window.warState,
      use3D: window.warState ? window.warState.use3D : "n/a",
      THREE: typeof THREE !== "undefined",
      initWar3D: typeof initWar3D !== "undefined",
      geo: typeof geo !== "undefined",
      TritiumModels: typeof TritiumModels !== "undefined",
      targets: window.assetState ? Object.keys(window.assetState.simTargets || {}).length : 0,
      canvasExists: !!document.getElementById("war-canvas"),
      addressBarExists: !!document.querySelector(".war-address-bar"),
      modeSelectorExists: !!document.querySelector(".war-mode-selector"),
    };
  });
  console.log("Step 2 status:", JSON.stringify(step2, null, 2));

  console.log("\n=== STEP 3: Enter address ===");
  // Find and fill the address input
  const addressInput = await page.$(".war-address-bar input, #war-address-input, input[placeholder*='address' i]");
  if (addressInput) {
    await addressInput.click();
    await addressInput.fill(ADDRESS);
    await page.keyboard.press("Enter");
    console.log("Address submitted, waiting for tiles...");
    await sleep(8000);
  } else {
    console.log("ERROR: No address input found!");
    // Try to find any input in the war view
    const inputs = await page.$$("input");
    console.log("Found " + inputs.length + " inputs on page");
    for (const inp of inputs.slice(0, 5)) {
      const ph = await inp.getAttribute("placeholder");
      const id = await inp.getAttribute("id");
      const cls = await inp.getAttribute("class");
      console.log("  input: id=" + id + " class=" + cls + " placeholder=" + ph);
    }
  }

  await page.screenshot({ path: "/tmp/game-step3-address.png" });
  console.log("Screenshot: /tmp/game-step3-address.png");

  console.log("\n=== STEP 4: Check map state after address ===");
  const step4 = await page.evaluate(() => {
    return {
      geoExists: !!window.geo,
      geoCenter: window.geo ? (window.geo._center || "not set") : "no geo",
      targets: window.assetState ? Object.keys(window.assetState.simTargets || {}).length : 0,
      use3D: window.warState ? window.warState.use3D : "n/a",
    };
  });
  console.log("Step 4 status:", JSON.stringify(step4, null, 2));

  console.log("\n=== STEP 5: Spawn targets via API ===");
  // Spawn friendly rover
  await page.evaluate(async () => {
    await fetch("/api/amy/simulation/spawn", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: "Rover Alpha", asset_type: "rover", alliance: "friendly", position: {x: 10, y: 10}})
    });
    await fetch("/api/amy/simulation/spawn", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: "Drone Beta", asset_type: "drone", alliance: "friendly", position: {x: -10, y: 15}})
    });
    await fetch("/api/amy/simulation/spawn", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: "Intruder North", asset_type: "person", alliance: "hostile", position: {x: -20, y: 25}})
    });
    await fetch("/api/amy/simulation/spawn", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({name: "Suspect Car", asset_type: "vehicle", alliance: "unknown", position: {x: 25, y: -10}})
    });
  });
  console.log("4 targets spawned");
  await sleep(3000);

  const step5 = await page.evaluate(() => {
    const targets = window.assetState ? window.assetState.simTargets || {} : {};
    return {
      count: Object.keys(targets).length,
      names: Object.values(targets).map(t => t.name + " (" + t.alliance + ")").slice(0, 10)
    };
  });
  console.log("Step 5 targets:", JSON.stringify(step5, null, 2));

  await page.screenshot({ path: "/tmp/game-step5-targets.png" });
  console.log("Screenshot: /tmp/game-step5-targets.png");

  console.log("\n=== STEP 6: Wait for escalation (hostile should trigger) ===");
  await sleep(10000);

  const step6 = await page.evaluate(async () => {
    const esc = await fetch("/api/amy/escalation/status").then(r => r.ok ? r.json() : {error: r.status});
    return esc;
  });
  console.log("Escalation status:", JSON.stringify(step6, null, 2));

  await page.screenshot({ path: "/tmp/game-step6-escalation.png" });
  console.log("Screenshot: /tmp/game-step6-escalation.png");

  console.log("\n=== STEP 7: Try dispatch (select rover, right-click to dispatch) ===");
  // Click on the canvas center area
  const canvas = await page.$("#war-canvas, canvas");
  if (canvas) {
    const box = await canvas.boundingBox();
    if (box) {
      // Click center to select
      await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
      await sleep(500);
      // Right-click to dispatch nearby
      await page.mouse.click(box.x + box.width / 2 + 100, box.y + box.height / 2 - 50, { button: "right" });
      await sleep(1000);
    }
  }

  await page.screenshot({ path: "/tmp/game-step7-dispatch.png" });
  console.log("Screenshot: /tmp/game-step7-dispatch.png");

  console.log("\n=== STEP 8: Wait for game to play out (20s) ===");
  await sleep(20000);

  const step8 = await page.evaluate(async () => {
    const targets = window.assetState ? window.assetState.simTargets || {} : {};
    const status = {};
    for (const [id, t] of Object.entries(targets)) {
      status[t.name] = { alliance: t.alliance, status: t.status, x: Math.round(t.x || 0), y: Math.round(t.y || 0) };
    }
    const warState = window.warState || {};
    return {
      targets: status,
      score: { kills: warState.kills || 0, breaches: warState.breaches || 0, dispatches: warState.dispatches || 0 },
      mode: warState.gameMode || "unknown"
    };
  });
  console.log("Final game state:", JSON.stringify(step8, null, 2));

  await page.screenshot({ path: "/tmp/game-step8-final.png" });
  console.log("Screenshot: /tmp/game-step8-final.png");

  console.log("\n=== ERRORS ===");
  console.log("Total errors:", errors.length);
  errors.forEach(e => console.log("  ERROR: " + e));

  console.log("\n=== CONSOLE HIGHLIGHTS ===");
  logs.filter(l => l.includes("war") || l.includes("geo") || l.includes("3d") || l.includes("Error") || l.includes("error"))
    .slice(0, 20)
    .forEach(l => console.log("  " + l));

  await browser.close();
  console.log("\nDone.");
})();
