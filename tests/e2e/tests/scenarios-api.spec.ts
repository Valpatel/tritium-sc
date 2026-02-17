import { test, expect } from '@playwright/test';

test.describe('Scenarios Listing API', () => {
  test('should return array of scenarios', async ({ request }) => {
    const response = await request.get('/api/scenarios');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
    expect(data.length).toBeGreaterThanOrEqual(4);
  });

  test('should include required fields on each scenario', async ({ request }) => {
    const response = await request.get('/api/scenarios');
    const data = await response.json();

    for (const scenario of data) {
      expect(scenario).toHaveProperty('name');
      expect(scenario).toHaveProperty('description');
      expect(scenario).toHaveProperty('duration');
      expect(scenario).toHaveProperty('event_count');
      expect(scenario).toHaveProperty('expected_count');
      expect(scenario).toHaveProperty('run_count');
    }
  });

  test('should include known scenarios', async ({ request }) => {
    const response = await request.get('/api/scenarios');
    const data = await response.json();
    const names = data.map((s: any) => s.name);

    expect(names).toContain('intruder_basic');
    expect(names).toContain('empty_room');
  });

  test('should have numeric durations', async ({ request }) => {
    const response = await request.get('/api/scenarios');
    const data = await response.json();

    for (const scenario of data) {
      expect(typeof scenario.duration).toBe('number');
      expect(scenario.duration).toBeGreaterThan(0);
    }
  });
});

test.describe('Scenario Details API', () => {
  test('should return scenario with events and expected arrays', async ({ request }) => {
    const response = await request.get('/api/scenarios/intruder_basic');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('scenario');
    expect(data).toHaveProperty('results');
    expect(data.scenario).toHaveProperty('events');
    expect(data.scenario).toHaveProperty('expected');
    expect(Array.isArray(data.scenario.events)).toBeTruthy();
    expect(Array.isArray(data.scenario.expected)).toBeTruthy();
  });

  test('should return scenario metadata', async ({ request }) => {
    const response = await request.get('/api/scenarios/intruder_basic');
    const data = await response.json();
    const s = data.scenario;

    expect(s).toHaveProperty('name');
    expect(s).toHaveProperty('description');
    expect(s).toHaveProperty('duration');
    expect(s.name).toBe('intruder_basic');
  });

  test('should return 404 for nonexistent scenario', async ({ request }) => {
    const response = await request.get('/api/scenarios/nonexistent_scenario_xyz');
    expect(response.status()).toBe(404);
  });

  test('should return results array (possibly empty)', async ({ request }) => {
    const response = await request.get('/api/scenarios/empty_room');
    const data = await response.json();
    expect(Array.isArray(data.results)).toBeTruthy();
  });
});

test.describe('Scenarios Cache API', () => {
  test('should return cache status', async ({ request }) => {
    const response = await request.get('/api/scenarios/cache');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data).toHaveProperty('has_cache');
    expect(data).toHaveProperty('backgrounds');
    expect(data).toHaveProperty('people');
    expect(typeof data.has_cache).toBe('boolean');
    expect(typeof data.backgrounds).toBe('number');
    expect(typeof data.people).toBe('number');
  });
});

test.describe('Scenarios Stats & Export API', () => {
  test('should return stats object', async ({ request }) => {
    const response = await request.get('/api/scenarios/stats');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(typeof data).toBe('object');
  });

  test('should return export array', async ({ request }) => {
    const response = await request.get('/api/scenarios/export');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(Array.isArray(data)).toBeTruthy();
  });
});
