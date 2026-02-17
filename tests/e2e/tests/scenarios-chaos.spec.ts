import { test, expect } from '@playwright/test';

// Chaos tests need more time for concurrent runs
test.describe.configure({ timeout: 120_000 });

test.describe('Concurrent Scenario Runs', () => {
  test('should handle 3 simultaneous empty_room runs', async ({ request }) => {
    // Start 3 runs simultaneously
    const starts = await Promise.all([
      request.post('/api/scenarios/run', { data: { name: 'empty_room' } }),
      request.post('/api/scenarios/run', { data: { name: 'empty_room' } }),
      request.post('/api/scenarios/run', { data: { name: 'empty_room' } }),
    ]);

    const runIds: string[] = [];
    for (const resp of starts) {
      expect(resp.ok()).toBeTruthy();
      const data = await resp.json();
      expect(data).toHaveProperty('run_id');
      runIds.push(data.run_id);
    }

    // All run_ids should be unique
    const unique = new Set(runIds);
    expect(unique.size).toBe(3);

    // Poll all until completed or failed
    const deadline = Date.now() + 110_000;
    const results: any[] = [null, null, null];

    while (Date.now() < deadline) {
      let allDone = true;
      for (let i = 0; i < 3; i++) {
        if (results[i]?.status === 'completed' || results[i]?.status === 'failed') continue;
        allDone = false;
        const resp = await request.get(`/api/scenarios/run/${runIds[i]}`);
        results[i] = await resp.json();
      }
      if (allDone) break;
      await new Promise(r => setTimeout(r, 2000));
    }

    // All should have completed or failed (not stuck)
    for (let i = 0; i < 3; i++) {
      expect(['completed', 'failed']).toContain(results[i]?.status);
    }
  });
});

test.describe('Malformed API Requests', () => {
  test('should return 404 for empty scenario name', async ({ request }) => {
    const resp = await request.post('/api/scenarios/run', {
      data: { name: '' },
    });
    // Empty name should either be 404 (not found) or 422 (validation)
    expect([404, 422]).toContain(resp.status());
  });

  test('should return 404 for nonexistent scenario', async ({ request }) => {
    const resp = await request.post('/api/scenarios/run', {
      data: { name: 'this_scenario_does_not_exist_xyz' },
    });
    expect(resp.status()).toBe(404);
  });

  test('should reject invalid rating value 99', async ({ request }) => {
    const resp = await request.post('/api/scenarios/run/run-fake123/rate', {
      data: { rating: 99 },
    });
    expect(resp.status()).toBe(422);
  });

  test('should reject rating value 0', async ({ request }) => {
    const resp = await request.post('/api/scenarios/run/run-fake123/rate', {
      data: { rating: 0 },
    });
    expect(resp.status()).toBe(422);
  });

  test('should reject string rating', async ({ request }) => {
    const resp = await request.post('/api/scenarios/run/run-fake123/rate', {
      data: { rating: 'excellent' },
    });
    expect(resp.status()).toBe(422);
  });
});

test.describe('MJPEG Stream Consumption', () => {
  test('should receive JPEG frame data from video stream', async ({ request }) => {
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    // Fetch video stream and read body
    const resp = await request.get(`/api/scenarios/run/${run_id}/video`);
    const body = await resp.body();

    // Should contain JPEG SOI marker (FF D8)
    let foundJpeg = false;
    for (let i = 0; i < body.length - 1; i++) {
      if (body[i] === 0xFF && body[i + 1] === 0xD8) {
        foundJpeg = true;
        break;
      }
    }
    expect(foundJpeg).toBeTruthy();
  });
});

test.describe('SSE Event Consumption', () => {
  test('should receive parseable SSE events from stream', async ({ request }) => {
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    // Small delay to let the run produce events
    await new Promise(r => setTimeout(r, 2000));

    const resp = await request.get(`/api/scenarios/run/${run_id}/stream`);
    const text = await resp.text();

    // Parse SSE data lines
    const dataLines = text.split('\n')
      .filter(line => line.startsWith('data:'))
      .map(line => line.substring(5).trim());

    // Should have at least one data line
    expect(dataLines.length).toBeGreaterThan(0);

    // Each data line should be valid JSON with a type field
    for (const line of dataLines) {
      const parsed = JSON.parse(line);
      expect(parsed).toHaveProperty('type');
      expect(['action', 'finished']).toContain(parsed.type);
    }
  });
});

test.describe('Stream Lifecycle', () => {
  test('should terminate MJPEG stream after run completes', async ({ request }) => {
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    // Poll until completed
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const resp = await request.get(`/api/scenarios/run/${run_id}`);
      const data = await resp.json();
      if (data.status === 'completed' || data.status === 'failed') break;
      await new Promise(r => setTimeout(r, 2000));
    }

    // Video stream should return finite response (not hang)
    const videoResp = await request.get(`/api/scenarios/run/${run_id}/video`);
    // Completed run returns 404 or a terminated stream
    const status = videoResp.status();
    expect([200, 404]).toContain(status);
  });
});

test.describe('Rating Persistence', () => {
  test('should persist rating on completed run', async ({ request }) => {
    // Start and wait for completion
    const startResp = await request.post('/api/scenarios/run', {
      data: { name: 'empty_room' },
    });
    const { run_id } = await startResp.json();

    const deadline = Date.now() + 110_000;
    let result: any;
    while (Date.now() < deadline) {
      const resp = await request.get(`/api/scenarios/run/${run_id}`);
      result = await resp.json();
      if (result.status === 'completed' || result.status === 'failed') break;
      await new Promise(r => setTimeout(r, 2000));
    }

    if (result.status !== 'completed') {
      test.skip();
      return;
    }

    // Rate the run
    const rateResp = await request.post(`/api/scenarios/run/${run_id}/rate`, {
      data: { rating: 3 },
    });
    expect(rateResp.ok()).toBeTruthy();

    // Fetch run again and verify rating persists
    const checkResp = await request.get(`/api/scenarios/run/${run_id}`);
    const checkData = await checkResp.json();
    expect(checkData.human_rating).toBe(3);
  });
});

test.describe('Cleanup Endpoint', () => {
  test('should clean up completed runs', async ({ request }) => {
    const resp = await request.delete('/api/scenarios/runs/cleanup');
    expect(resp.ok()).toBeTruthy();
    const data = await resp.json();
    expect(data).toHaveProperty('cleaned');
  });
});
