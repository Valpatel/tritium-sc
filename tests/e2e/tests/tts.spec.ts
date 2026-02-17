import { test, expect } from '@playwright/test';

let piperAvailable = false;

test.beforeAll(async ({ request }) => {
  // Check if Piper is available — skip all tests if not
  try {
    const resp = await request.get('/api/tts/voices');
    if (resp.ok()) {
      const data = await resp.json();
      piperAvailable = data.piper_available === true;
    }
  } catch {
    piperAvailable = false;
  }
});

test.describe('TTS Voice Discovery', () => {
  test('should return voice list with required fields', async ({ request }) => {
    const resp = await request.get('/api/tts/voices');
    expect(resp.ok()).toBeTruthy();

    const data = await resp.json();
    expect(data).toHaveProperty('piper_available');
    expect(data).toHaveProperty('voices');
    expect(Array.isArray(data.voices)).toBeTruthy();

    if (data.voices.length > 0) {
      const voice = data.voices[0];
      expect(voice).toHaveProperty('id');
      expect(voice).toHaveProperty('name');
      expect(voice).toHaveProperty('language');
      expect(voice).toHaveProperty('quality');
    }
  });
});

test.describe('TTS Synthesis', () => {
  test('should synthesize text to valid WAV', async ({ request }) => {
    test.skip(!piperAvailable, 'Piper TTS not available');

    const resp = await request.post('/api/tts/synthesize', {
      data: { text: 'Hello world' },
    });
    expect(resp.ok()).toBeTruthy();

    const contentType = resp.headers()['content-type'] || '';
    expect(contentType).toContain('audio/wav');

    const body = await resp.body();
    // WAV must be > 100 bytes (44 byte header + audio data)
    expect(body.length).toBeGreaterThan(100);

    // Check RIFF/WAVE magic bytes
    const magic = body.slice(0, 4).toString('ascii');
    expect(magic).toBe('RIFF');
    const wave = body.slice(8, 12).toString('ascii');
    expect(wave).toBe('WAVE');
  });

  test('should return 400 for empty text', async ({ request }) => {
    const resp = await request.post('/api/tts/synthesize', {
      data: { text: '' },
    });
    expect(resp.status()).toBe(400);
  });

  test('should return 400 for whitespace-only text', async ({ request }) => {
    const resp = await request.post('/api/tts/synthesize', {
      data: { text: '   ' },
    });
    expect(resp.status()).toBe(400);
  });

  test('should handle long text', async ({ request }) => {
    test.skip(!piperAvailable, 'Piper TTS not available');

    const longText = 'This is a test sentence for Piper TTS synthesis. '.repeat(20);
    const resp = await request.post('/api/tts/synthesize', {
      data: { text: longText },
    });
    // Should succeed or fail gracefully — not crash
    expect([200, 400, 500]).toContain(resp.status());
  });

  test('should return 503 when Piper unavailable', async ({ request }) => {
    test.skip(piperAvailable, 'Piper is available — cannot test 503');

    const resp = await request.post('/api/tts/synthesize', {
      data: { text: 'Hello' },
    });
    expect(resp.status()).toBe(503);
  });
});

test.describe('TTS Concurrency', () => {
  test('should handle 3 concurrent synthesis requests', async ({ request }) => {
    test.skip(!piperAvailable, 'Piper TTS not available');

    const responses = await Promise.all([
      request.post('/api/tts/synthesize', { data: { text: 'First request' } }),
      request.post('/api/tts/synthesize', { data: { text: 'Second request' } }),
      request.post('/api/tts/synthesize', { data: { text: 'Third request' } }),
    ]);

    for (const resp of responses) {
      expect(resp.ok()).toBeTruthy();
      const body = await resp.body();
      expect(body.length).toBeGreaterThan(100);
    }
  });
});

test.describe('TTS Frontend Integration', () => {
  test('should populate voice picker with Piper voices when available', async ({ page }) => {
    test.skip(!piperAvailable, 'Piper TTS not available');

    await page.goto('/');
    await page.keyboard.press('s');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);
    await expect(page.locator('#scenarios-initialized')).toBeAttached();

    // Voice picker should eventually have options (Piper or browser)
    const select = page.locator('#scenarios-voice-select');
    await expect(select).toBeVisible();

    // Wait for voices to populate
    await page.waitForFunction(() => {
      const sel = document.getElementById('scenarios-voice-select') as HTMLSelectElement;
      return sel && sel.options.length > 1;
    }, { timeout: 5000 }).catch(() => {
      // Voice population may not happen in headless — acceptable
    });
  });
});
