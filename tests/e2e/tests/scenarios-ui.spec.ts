import { test, expect } from '@playwright/test';

test.describe('Scenarios View Activation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should switch to scenarios via button click', async ({ page }) => {
    await page.click('#btn-scenarios');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);
    await expect(page.locator('#btn-scenarios')).toHaveClass(/active/);
  });

  test('should switch to scenarios via S keyboard shortcut', async ({ page }) => {
    await page.keyboard.press('s');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);
  });

  test('should hide other views when scenarios is active', async ({ page }) => {
    await page.click('#btn-scenarios');

    const otherViews = ['grid', 'player', '3d', 'zones', 'targets', 'assets', 'analytics', 'amy'];
    for (const view of otherViews) {
      await expect(page.locator(`#view-${view}`)).toHaveClass(/hidden/);
    }
  });
});

test.describe('Scenarios Panel Structure', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-scenarios');
    // Wait for scenarios to initialize (dynamic HTML injection)
    await expect(page.locator('#scenarios-initialized')).toBeAttached();
  });

  test('should have scenario library panel', async ({ page }) => {
    await expect(page.locator('.scenarios-library-panel')).toBeVisible();
    await expect(page.locator('.scenarios-library-panel .scenarios-panel-title')).toContainText('SCENARIO LIBRARY');
  });

  test('should have synthetic camera panel', async ({ page }) => {
    await expect(page.locator('.scenarios-run-panel')).toBeVisible();
    await expect(page.locator('.scenarios-run-panel .scenarios-panel-title')).toContainText('SYNTHETIC CAMERA');
  });

  test('should have live feed panel', async ({ page }) => {
    await expect(page.locator('.scenarios-timeline-panel')).toBeVisible();
    await expect(page.locator('.scenarios-timeline-panel .scenarios-panel-title')).toContainText('LIVE FEED');
  });

  test('should have evaluation panel', async ({ page }) => {
    await expect(page.locator('.scenarios-score-panel')).toBeVisible();
    await expect(page.locator('.scenarios-score-panel .scenarios-panel-title')).toContainText('EVALUATION');
  });

  test('should display scenario count badge', async ({ page }) => {
    await expect(page.locator('#scenarios-count')).toBeVisible();
  });

  test('should display cache status badge', async ({ page }) => {
    await expect(page.locator('#scenarios-cache-badge')).toBeVisible();
  });

  test('should have voice select dropdown', async ({ page }) => {
    await expect(page.locator('#scenarios-voice-select')).toBeVisible();
  });

  test('should have TTS toggle checkbox', async ({ page }) => {
    await expect(page.locator('#scenarios-tts-check')).toBeAttached();
  });

  test('should show run badge with IDLE status initially', async ({ page }) => {
    await expect(page.locator('#scenarios-run-badge')).toContainText('IDLE');
  });
});

test.describe('Scenario Library List', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-scenarios');
    // Wait for scenarios to load from API
    await page.waitForResponse(resp =>
      resp.url().includes('/api/scenarios') && resp.status() === 200
    );
    await expect(page.locator('.scenarios-item').first()).toBeVisible();
  });

  test('should list available scenarios', async ({ page }) => {
    const items = page.locator('.scenarios-item');
    expect(await items.count()).toBeGreaterThanOrEqual(12);
  });

  test('should display scenario name', async ({ page }) => {
    const firstName = page.locator('.scenarios-item-name').first();
    await expect(firstName).toBeVisible();
    const text = await firstName.textContent();
    expect(text!.length).toBeGreaterThan(0);
  });

  test('should display scenario description', async ({ page }) => {
    const firstDesc = page.locator('.scenarios-item-desc').first();
    await expect(firstDesc).toBeVisible();
  });

  test('should display event count and duration', async ({ page }) => {
    const firstMeta = page.locator('.scenarios-item-meta').first();
    await expect(firstMeta).toBeVisible();
    const text = await firstMeta.textContent();
    expect(text).toContain('events');
    expect(text).toContain('s');
  });

  test('should highlight clicked scenario', async ({ page }) => {
    const firstItem = page.locator('.scenarios-item').first();
    await firstItem.click();
    await expect(firstItem).toHaveClass(/active/);
  });

  test('should show RUN button after selecting scenario', async ({ page }) => {
    await page.locator('.scenarios-item').first().click();
    // Wait for scenario detail to load
    await page.waitForResponse(resp =>
      resp.url().match(/\/api\/scenarios\/\w+/) !== null && resp.status() === 200
    );
    await expect(page.locator('#scenarios-run-btn')).toBeVisible();
    await expect(page.locator('#scenarios-run-btn')).toContainText('RUN');
  });

  test('should show scenario count matching list length', async ({ page }) => {
    const items = page.locator('.scenarios-item');
    const count = await items.count();
    await expect(page.locator('#scenarios-count')).toContainText(String(count));
  });

  test('should show score badges with correct classes', async ({ page }) => {
    const scoreBadges = page.locator('.scenarios-item-score');
    const count = await scoreBadges.count();
    for (let i = 0; i < count; i++) {
      const badge = scoreBadges.nth(i);
      const classes = await badge.getAttribute('class');
      // Each badge should have one of the score classes
      expect(classes).toMatch(/scenarios-score-(good|ok|bad|none)/);
    }
  });
});

test.describe('Video Container Stability', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-scenarios');
    await expect(page.locator('#scenarios-initialized')).toBeAttached();
  });

  test('should use position:relative not flex centering', async ({ page }) => {
    const container = page.locator('.scenarios-video-container');
    await expect(container).toBeVisible();
    const position = await container.evaluate(el => getComputedStyle(el).position);
    expect(position).toBe('relative');
  });

  test('should have video feed with absolute positioning', async ({ page }) => {
    const feed = page.locator('.scenarios-video-feed');
    const position = await feed.evaluate(el => getComputedStyle(el).position);
    expect(position).toBe('absolute');
  });

  test('should show NO FEED overlay when no run active', async ({ page }) => {
    const overlay = page.locator('#scenarios-video-overlay');
    await expect(overlay).toBeVisible();
    await expect(overlay).toContainText('NO FEED');
  });

  test('should have stable container dimensions', async ({ page }) => {
    const container = page.locator('#scenarios-video-container');
    const box1 = await container.boundingBox();
    expect(box1).not.toBeNull();

    // Wait for layout to stabilize
    await page.waitForFunction(() => document.readyState === 'complete');
    const box2 = await container.boundingBox();
    expect(box2).not.toBeNull();
    expect(box2!.width).toBe(box1!.width);
    expect(box2!.height).toBe(box1!.height);
  });
});

test.describe('Evaluation Panel', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-scenarios');
    await expect(page.locator('#scenarios-initialized')).toBeAttached();
  });

  test('should have SCORE stat box', async ({ page }) => {
    await expect(page.locator('text=SCORE').first()).toBeVisible();
    await expect(page.locator('#scenarios-score-total')).toContainText('--');
  });

  test('should have MATCHED stat box', async ({ page }) => {
    await expect(page.locator('text=MATCHED').first()).toBeVisible();
    await expect(page.locator('#scenarios-score-matched')).toContainText('--');
  });

  test('should have DETECTION stat box', async ({ page }) => {
    await expect(page.locator('text=DETECTION').first()).toBeVisible();
    await expect(page.locator('#scenarios-score-detection')).toContainText('--');
  });

  test('should have LATENCY stat box', async ({ page }) => {
    await expect(page.locator('text=LATENCY').first()).toBeVisible();
    await expect(page.locator('#scenarios-score-latency')).toContainText('--');
  });

  test('should hide star rating when no run completed', async ({ page }) => {
    const rating = page.locator('#scenarios-rating');
    await expect(rating).toBeHidden();
  });

  test('should have five star buttons', async ({ page }) => {
    const stars = page.locator('.scenarios-star');
    await expect(stars).toHaveCount(5);
  });
});

test.describe('Controls Hint', () => {
  test('should be visible and within viewport', async ({ page }) => {
    await page.goto('/');
    const hint = page.locator('.controls-hint');
    await expect(hint).toBeVisible();

    const box = await hint.boundingBox();
    const viewport = page.viewportSize();
    expect(box).not.toBeNull();
    expect(viewport).not.toBeNull();

    // Hint should be fully within viewport
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
  });

  test('should not overflow at 1024x768 viewport', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto('/');

    const hint = page.locator('.controls-hint');
    await expect(hint).toBeVisible();

    const box = await hint.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x + box!.width).toBeLessThanOrEqual(1024);
  });
});
