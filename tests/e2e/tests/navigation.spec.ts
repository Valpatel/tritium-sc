import { test, expect } from '@playwright/test';

const allViews = [
  { name: 'grid', button: '#btn-grid', view: '#view-grid' },
  { name: 'player', button: '#btn-player', view: '#view-player' },
  { name: '3d', button: '#btn-3d', view: '#view-3d' },
  { name: 'zones', button: '#btn-zones', view: '#view-zones' },
  { name: 'targets', button: '#btn-targets', view: '#view-targets' },
  { name: 'assets', button: '#btn-assets', view: '#view-assets' },
  { name: 'analytics', button: '#btn-analytics', view: '#view-analytics' },
  { name: 'amy', button: '#btn-amy', view: '#view-amy' },
  { name: 'scenarios', button: '#btn-scenarios', view: '#view-scenarios' },
];

const keyboardMap: Record<string, string> = {
  'grid': 'g',
  'player': 'p',
  '3d': 'd',
  'zones': 'z',
  'targets': 't',
  'assets': 'a',
  'analytics': 'n',
  'amy': 'y',
  'scenarios': 's',
};

test.describe('Button Navigation — All Views', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  for (const { name, button, view } of allViews) {
    test(`should switch to ${name} view via button`, async ({ page }) => {
      await page.click(button);
      await expect(page.locator(view)).not.toHaveClass(/hidden/);
      await expect(page.locator(button)).toHaveClass(/active/);

      // All other views should be hidden
      for (const other of allViews) {
        if (other.name !== name) {
          await expect(page.locator(other.view)).toHaveClass(/hidden/);
        }
      }
    });
  }
});

test.describe('Keyboard Navigation — All Shortcuts', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  for (const { name, button, view } of allViews) {
    const key = keyboardMap[name];

    test(`should switch to ${name} view via '${key}' key`, async ({ page }) => {
      // First switch to a different view to ensure we're actually navigating
      if (name !== '3d') {
        await page.keyboard.press('d');
        await expect(page.locator('#view-3d')).not.toHaveClass(/hidden/);
      } else {
        await page.keyboard.press('z');
        await expect(page.locator('#view-zones')).not.toHaveClass(/hidden/);
      }

      // Now press the target key
      await page.keyboard.press(key);
      await expect(page.locator(view)).not.toHaveClass(/hidden/);
      await expect(page.locator(button)).toHaveClass(/active/);
    });
  }
});

test.describe('Round-trip Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should re-initialize scenarios after round-trip', async ({ page }) => {
    // Go to scenarios
    await page.keyboard.press('s');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);
    await expect(page.locator('#scenarios-initialized')).toBeAttached();

    // Switch away
    await page.keyboard.press('g');
    await expect(page.locator('#view-grid')).not.toHaveClass(/hidden/);
    await expect(page.locator('#view-scenarios')).toHaveClass(/hidden/);

    // Switch back
    await page.keyboard.press('s');
    await expect(page.locator('#view-scenarios')).not.toHaveClass(/hidden/);
    // Scenarios dashboard should still be present
    await expect(page.locator('.scenarios-dashboard')).toBeVisible();
  });

  test('should re-initialize amy after round-trip', async ({ page }) => {
    await page.keyboard.press('y');
    await expect(page.locator('#view-amy')).not.toHaveClass(/hidden/);

    await page.keyboard.press('g');
    await expect(page.locator('#view-grid')).not.toHaveClass(/hidden/);

    await page.keyboard.press('y');
    await expect(page.locator('#view-amy')).not.toHaveClass(/hidden/);
  });

  test('should maintain button active state through navigation', async ({ page }) => {
    for (const { name, button } of allViews) {
      await page.keyboard.press(keyboardMap[name]);
      await expect(page.locator(button)).toHaveClass(/active/);

      // All other buttons should not have active
      for (const other of allViews) {
        if (other.name !== name) {
          await expect(page.locator(other.button)).not.toHaveClass(/active/);
        }
      }
    }
  });
});

test.describe('Accessibility — Keyboard Focus', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should tab through view buttons with visible focus', async ({ page }) => {
    // Tab into the nav area — find a focusable button
    await page.keyboard.press('Tab');
    // Keep tabbing until we hit a btn-* element
    for (let i = 0; i < 20; i++) {
      const focused = await page.evaluate(() => document.activeElement?.id || '');
      if (focused.startsWith('btn-')) {
        // Found a view button — test passes
        return;
      }
      await page.keyboard.press('Tab');
    }
    // If we never found a btn-* element, that's a fail
    const finalFocused = await page.evaluate(() => document.activeElement?.id || '');
    expect(finalFocused).toMatch(/^btn-/);
  });

  test('should activate view button with Enter key', async ({ page }) => {
    // Focus the zones button directly
    await page.focus('#btn-zones');
    await page.keyboard.press('Enter');
    await expect(page.locator('#view-zones')).not.toHaveClass(/hidden/);
  });

  test('should blur command input on Escape after / focuses it', async ({ page }) => {
    await page.keyboard.press('/');
    await expect(page.locator('#command-input')).toBeFocused();

    await page.keyboard.press('Escape');
    // Command input should no longer be focused
    const stillFocused = await page.evaluate(() => document.activeElement?.id === 'command-input');
    expect(stillFocused).toBe(false);
  });
});
