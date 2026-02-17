import { test, expect } from '@playwright/test';

test.describe('TRITIUM-SC Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should load the dashboard', async ({ page }) => {
    // Check for TRITIUM branding
    await expect(page.locator('.logo-text')).toContainText('TRITIUM');

    // Check version
    await expect(page.locator('.logo-version')).toContainText('v0.1.0');
  });

  test('should display navigation tabs', async ({ page }) => {
    // Check for main navigation elements
    await expect(page.locator('#btn-grid')).toBeVisible();
    await expect(page.locator('#btn-player')).toBeVisible();
    await expect(page.locator('#btn-3d')).toBeVisible();
    await expect(page.locator('#btn-zones')).toBeVisible();
  });

  test('should show sidebar sections', async ({ page }) => {
    // Check sidebar sections
    await expect(page.locator('text=CHANNELS')).toBeVisible();
    await expect(page.locator('text=DATES')).toBeVisible();
    await expect(page.locator('text=ZONES')).toBeVisible();
    await expect(page.locator('text=RECENT EVENTS')).toBeVisible();
  });

  test('should show system time', async ({ page }) => {
    // System time should be visible
    await expect(page.locator('#system-time')).toBeVisible();
    await expect(page.locator('#system-time')).toContainText('UTC');
  });

  test('should show connection status', async ({ page }) => {
    // Connection status should be visible
    await expect(page.locator('#connection-text')).toBeVisible();
  });

  test('should switch between views', async ({ page }) => {
    // Click on 3D view
    await page.click('#btn-3d');
    await expect(page.locator('#view-3d')).not.toHaveClass(/hidden/);

    // Click on GRID view
    await page.click('#btn-grid');
    await expect(page.locator('#view-grid')).not.toHaveClass(/hidden/);

    // Click on ZONES view
    await page.click('#btn-zones');
    await expect(page.locator('#view-zones')).not.toHaveClass(/hidden/);
  });

  test('should load camera channels', async ({ page }) => {
    // Wait for channels API response or timeout gracefully
    await page.waitForResponse(
      resp => resp.url().includes('/api/cameras') && resp.status() === 200
    ).catch(() => { /* cameras endpoint may not exist in test env */ });

    // Channel list should exist
    await expect(page.locator('#channel-list')).toBeVisible();
  });

  test('should have command input', async ({ page }) => {
    // Command input should be visible
    const input = page.locator('#command-input');
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute('placeholder', /search/i);
  });
});

test.describe('View Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should switch to player view', async ({ page }) => {
    await page.click('#btn-player');
    await expect(page.locator('#view-player')).not.toHaveClass(/hidden/);
    await expect(page.locator('#main-player')).toBeVisible();
  });

  test('should switch to 3D view', async ({ page }) => {
    await page.click('#btn-3d');
    await expect(page.locator('#view-3d')).not.toHaveClass(/hidden/);
    await expect(page.locator('#three-canvas')).toBeVisible();
  });

  test('should switch to zones view', async ({ page }) => {
    await page.click('#btn-zones');
    await expect(page.locator('#view-zones')).not.toHaveClass(/hidden/);
  });
});

test.describe('3D Property View', () => {
  test('should render 3D canvas', async ({ page }) => {
    await page.goto('/');
    await page.click('#btn-3d');

    // Canvas should be visible
    const canvas = page.locator('#three-canvas');
    await expect(canvas).toBeVisible();

    // Wait for Three.js to initialize
    await page.waitForFunction(() => {
      const canvas = document.getElementById('three-canvas');
      return canvas && (canvas.getContext('webgl') || canvas.getContext('webgl2'));
    }, { timeout: 10000 });
  });
});

test.describe('Keyboard Shortcuts', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should switch to grid view with G key', async ({ page }) => {
    // First switch to another view
    await page.click('#btn-3d');

    // Press G to switch to grid
    await page.keyboard.press('g');
    await expect(page.locator('#view-grid')).not.toHaveClass(/hidden/);
  });

  test('should switch to 3D view with D key', async ({ page }) => {
    await page.keyboard.press('d');
    await expect(page.locator('#view-3d')).not.toHaveClass(/hidden/);
  });

  test('should switch to zones view with Z key', async ({ page }) => {
    await page.keyboard.press('z');
    await expect(page.locator('#view-zones')).not.toHaveClass(/hidden/);
  });

  test('should focus command input with / key', async ({ page }) => {
    await page.keyboard.press('/');
    await expect(page.locator('#command-input')).toBeFocused();
  });
});

test.describe('API Health', () => {
  test('should return healthy status', async ({ request }) => {
    const response = await request.get('/health');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.status).toBe('operational');
    expect(data.version).toBe('0.1.0');
    expect(data.system).toBe('TRITIUM-SC');
  });

  test('should return system status', async ({ request }) => {
    const response = await request.get('/api/status');
    expect(response.ok()).toBeTruthy();

    const data = await response.json();
    expect(data.name).toBeDefined();
    expect(data.version).toBe('0.1.0');
    expect(data.database).toBe('connected');
  });
});

test.describe('Grid Size Controls', () => {
  test('should have grid size selector', async ({ page }) => {
    await page.goto('/');

    const selector = page.locator('#grid-size');
    await expect(selector).toBeVisible();

    // Check options
    await expect(selector.locator('option')).toHaveCount(4);
  });

  test('should change grid layout', async ({ page }) => {
    await page.goto('/');

    // Change to 3x3 grid
    await page.selectOption('#grid-size', '9');

    const grid = page.locator('#video-grid');
    await expect(grid).toHaveClass(/grid-9/);
  });
});
