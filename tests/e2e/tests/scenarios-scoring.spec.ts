import { test, expect } from '@playwright/test';

// Scoring tests run actual scenarios — need more time
test.describe.configure({ timeout: 120_000 });

/**
 * Helper: start a run and poll until completed.
 * Returns the full result object or null on failure.
 */
async function runAndWait(request: any, scenarioName: string, timeoutMs = 110_000): Promise<any> {
  const startResp = await request.post('/api/scenarios/run', {
    data: { name: scenarioName },
  });
  if (!startResp.ok()) return null;

  const { run_id } = await startResp.json();
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const resp = await request.get(`/api/scenarios/run/${run_id}`);
    const data = await resp.json();
    if (data.status === 'completed' || data.status === 'failed') return data;
    await new Promise(r => setTimeout(r, 2000));
  }
  return null;
}

test.describe('Score Structure — empty_room', () => {
  let result: any;

  test.beforeAll(async ({ request }) => {
    result = await runAndWait(request, 'empty_room');
  });

  test('should complete the run', () => {
    expect(result).not.toBeNull();
    expect(result.status).toBe('completed');
  });

  test('should have all required score fields', () => {
    expect(result.status).toBe('completed');
    const score = result.score;
    expect(score).toHaveProperty('total_score');
    expect(score).toHaveProperty('matched');
    expect(score).toHaveProperty('total_expected');
    expect(score).toHaveProperty('details');
    expect(score).toHaveProperty('detection_accuracy');
    expect(score).toHaveProperty('avg_response_latency');
  });

  test('total_score should be 0.0 to 1.0', () => {
    expect(result.status).toBe('completed');
    expect(result.score.total_score).toBeGreaterThanOrEqual(0.0);
    expect(result.score.total_score).toBeLessThanOrEqual(1.0);
  });

  test('detection_accuracy should be 0.0 to 1.0', () => {
    expect(result.status).toBe('completed');
    expect(result.score.detection_accuracy).toBeGreaterThanOrEqual(0.0);
    expect(result.score.detection_accuracy).toBeLessThanOrEqual(1.0);
  });

  test('avg_response_latency should be non-negative', () => {
    expect(result.status).toBe('completed');
    expect(result.score.avg_response_latency).toBeGreaterThanOrEqual(0);
  });

  test('matched should not exceed total_expected', () => {
    expect(result.status).toBe('completed');
    expect(result.score.matched).toBeLessThanOrEqual(result.score.total_expected);
  });

  test('details array length should equal total_expected', () => {
    expect(result.status).toBe('completed');
    expect(Array.isArray(result.score.details)).toBeTruthy();
    expect(result.score.details.length).toBe(result.score.total_expected);
  });

  test('each detail should have expected and matched fields', () => {
    expect(result.status).toBe('completed');
    for (const detail of result.score.details) {
      expect(detail).toHaveProperty('expected');
      expect(detail).toHaveProperty('matched');
    }
  });

  test('actions array should exist and be an array', () => {
    expect(result.status).toBe('completed');
    expect(Array.isArray(result.actions)).toBeTruthy();
  });
});

test.describe('Export Includes Score Data', () => {
  test('should include score in export results', async ({ request }) => {
    const resp = await request.get('/api/scenarios/export?scenario=empty_room');
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    // Export returns an array of results
    if (Array.isArray(data) && data.length > 0) {
      const entry = data[0];
      expect(entry).toHaveProperty('score');
      expect(entry.score).toHaveProperty('total_score');
    }
  });
});
