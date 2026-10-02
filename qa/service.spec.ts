import { expect, test } from '@playwright/test';

test('creates a job through the browser UI', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Service Observability Lab' })).toBeVisible();

  await page.getByTestId('job-title').fill('Verify observability pipeline');
  await page.getByTestId('create-job').click();

  const row = page.getByTestId('job-row').filter({ hasText: 'Verify observability pipeline' });
  await expect(row).toBeVisible();
  await row.getByRole('combobox').selectOption('completed');
  await expect(row.getByRole('combobox')).toHaveValue('completed');
});

test('health and metrics endpoints are available', async ({ request }) => {
  const health = await request.get('/health');
  expect(health.ok()).toBeTruthy();
  expect((await health.json()).status).toBe('ok');

  const metrics = await request.get('/metrics');
  expect(metrics.ok()).toBeTruthy();
  expect(await metrics.text()).toContain('service_lab_http_requests_total');
});

test('a lost creation response can be retried without a duplicate', async ({ page, request }) => {
  const title = `Lost response ${Date.now()}`;
  let loseResponse = true;
  const keys: string[] = [];
  await page.route('**/api/jobs', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    keys.push(route.request().headers()['idempotency-key']);
    if (loseResponse) {
      loseResponse = false;
      const response = await route.fetch(); // Server commits, but browser never receives it.
      expect(response.status()).toBe(201);
      await route.abort('failed');
    } else await route.continue();
  });
  await page.goto('/');
  await page.getByTestId('job-title').fill(title);
  await page.getByTestId('create-job').click();
  await expect(page.locator('#create-message')).toContainText('Could not confirm');
  await expect(page.getByTestId('job-title')).toHaveValue(title);
  await page.getByTestId('create-job').click();
  await expect(page.locator('#create-message')).toContainText('No duplicate created');
  expect(keys.length).toBe(2);
  expect(keys[0]).toBe(keys[1]);
  const jobs = await (await request.get('/api/jobs')).json();
  expect(jobs.filter((job: {title: string}) => job.title === title)).toHaveLength(1);
});

test('job titles render as text at mobile widths', async ({ page }) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/');
  const title = '<img src=x onerror="document.body.dataset.injected=1">';
  await page.getByTestId('job-title').fill(title);
  await page.getByTestId('create-job').click();
  const row = page.getByTestId('job-row').filter({hasText:title});
  await expect(row).toHaveCount(1);
  await expect(row.locator('img')).toHaveCount(0);
  expect(await page.locator('body').getAttribute('data-injected')).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});
