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
