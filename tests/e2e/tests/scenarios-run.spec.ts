import { test, expect } from '@playwright/test';

// Scenario runs need Ollama + more time
test.describe.configure({ timeout: 120_000 });

test.describe('Scenario Run API Lifecycle', () => {
  let runId: string;

  test('should start a run and return run_id', async ({ request }) => {
    const response = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('run_id');
    expect(data).toHaveProperty('status');
    expect(data.status).toBe('running');
    runId = data.run_id;
  });

  test('should show running status during execution', async ({ request }) => {
    // Start a fresh run
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const start = await startResp.json();
    runId = start.run_id;

    const statusResp = await request.get(`/api/scenarios/run/${runId}`);
    expect(statusResp.ok()).toBeTruthy();

    const data = await statusResp.json();
    // Could be running or already completed (empty_room is short)
    expect(['running', 'completed']).toContain(data.status);
  });

  test('should complete with score after polling', async ({ request }) => {
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const start = await startResp.json();
    runId = start.run_id;

    // Poll until completed
    let result: any;
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const resp = await request.get(`/api/scenarios/run/${runId}`);
      result = await resp.json();
      if (result.status === 'completed' || result.status === 'failed') break;
      await new Promise(r => setTimeout(r, 2000));
    }

    expect(result.status).toBe('completed');
    expect(result).toHaveProperty('actions');
    expect(result).toHaveProperty('score');
    expect(Array.isArray(result.actions)).toBeTruthy();

    // Score fields
    const score = result.score;
    expect(score).toHaveProperty('total_score');
    expect(score).toHaveProperty('matched');
    expect(score).toHaveProperty('detection_accuracy');
    expect(score).toHaveProperty('avg_response_latency');
  });

  test('should return 404 for nonexistent run', async ({ request }) => {
    const resp = await request.get('/api/scenarios/run/run-nonexistent999');
    expect(resp.status()).toBe(404);
  });
});

test.describe('Scenario Live Streams', () => {
  test('should return MJPEG Content-Type for video endpoint', async ({ request }) => {
    // Start a run first
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    const resp = await request.get(`/api/scenarios/run/${run_id}/video`);
    const contentType = resp.headers()['content-type'] || '';
    expect(contentType).toContain('multipart/x-mixed-replace');
  });

  test('should return SSE Content-Type for stream endpoint', async ({ request }) => {
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    const resp = await request.get(`/api/scenarios/run/${run_id}/stream`);
    const contentType = resp.headers()['content-type'] || '';
    expect(contentType).toContain('text/event-stream');
  });
});

test.describe('Scenario Rating', () => {
  test('should accept a rating for completed run', async ({ request }) => {
    // Start and wait for completion
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    // Poll until completed
    const deadline = Date.now() + 110_000;
    let result: any;
    while (Date.now() < deadline) {
      const resp = await request.get(`/api/scenarios/run/${run_id}`);
      result = await resp.json();
      if (result.status === 'completed' || result.status === 'failed') break;
      await new Promise(r => setTimeout(r, 2000));
    }

    // Rate
    const rateResp = await request.post(`/api/scenarios/run/${run_id}/rate`, {
      data: { rating: 4 },
    });
    expect(rateResp.ok()).toBeTruthy();
    const rateData = await rateResp.json();
    expect(rateData.rating).toBe(4);
  });
});

test.describe('Full Browser Scenario Run', () => {
  test('should run empty_room end-to-end in browser', async ({ page }) => {
    test.setTimeout(120_000);

    await page.goto('/');

    // Navigate to scenarios
    await page.keyboard.press('s');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);

    // Wait for scenarios list to load
    await page.waitForResponse(resp =>
      resp.url().includes('/api/scenarios') && !resp.url().includes('/cache') && resp.status() === 200
    );
    await expect(page.locator('.scenarios-item').first()).toBeVisible();

    // Find and click empty_room scenario
    const emptyRoom = page.locator('.scenarios-item', { hasText: 'EMPTY ROOM' });
    await expect(emptyRoom).toBeVisible();
    await emptyRoom.click();
    await expect(emptyRoom).toHaveClass(/active/);

    // Wait for scenario detail to load and RUN button to appear
    await expect(page.locator('#scenarios-run-btn')).toBeVisible({ timeout: 5000 });

    // Click RUN
    await page.locator('#scenarios-run-btn').click();

    // Badge should change to RUNNING (or STARTING briefly)
    await expect(page.locator('#scenarios-run-badge')).not.toContainText('IDLE', { timeout: 5000 });

    // Video feed should become visible
    const videoFeed = page.locator('#scenarios-video-feed');
    await expect(videoFeed).not.toHaveCSS('display', 'none', { timeout: 10000 });

    // Wait for completion — poll the badge
    await expect(page.locator('#scenarios-run-badge')).toContainText('COMPLETED', { timeout: 110_000 });

    // Score values should be populated (not "--")
    await expect(page.locator('#scenarios-score-total')).not.toContainText('--');

    // Star rating should become visible
    await expect(page.locator('#scenarios-rating')).toBeVisible();

    // Click a star and verify notification
    await page.locator('.scenarios-star').nth(3).click();  // 4th star = rating 4
    await expect(page.locator('.notification')).toBeVisible({ timeout: 3000 });
  });
});
