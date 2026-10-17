const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const root = path.resolve(__dirname, '..');
  const { createServer } = await import(pathToFileURL(path.join(root, 'node_modules/vite/dist/node/index.js')).href);
  const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 } });
  await server.listen();
  let browser;
  try {
    browser = await chromium.launch({ ...(process.env.CHROME_BIN ? { executablePath: process.env.CHROME_BIN } : {}), headless: true });
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/auth/**', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({
        user: { id: 'demo-user', username: 'test@example.com', email: 'test@example.com', role: 'Administrator', organizationId: 'test-org' },
      }),
    }));
    await page.route('**/api/sources/uploads/csrf', route => route.fulfill({
      contentType: 'application/json', body: JSON.stringify({ csrfToken: 'test-token' }),
    }));
    let mode = 'success', requests = 0, saved = [];
    const source = { sourceId: 'src-test', batchId: 'batch-test', filename: 'orders.csv', environment: 'test',
      format: 'csv', sizeBytes: 20, uploadedAt: '2026-10-17T12:00:00Z',
      collections: [{ collectionId: 'col-test', name: 'orders', rowCount: 1, warnings: ["Column 2: 'id' renamed to 'id_2'."] }] };
    await page.route('**/api/sources', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ sources: saved }) }));
    await page.route('**/api/sources/uploads', async route => {
      requests++;
      assert.equal(route.request().headers()['x-csrf-token'], 'test-token');
      assert.match(route.request().headers()['content-type'], /multipart\/form-data; boundary=/);
      assert.match(route.request().postDataBuffer().toString(), /filename="orders.csv"/);
      if (mode === 'error') return route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: 'Collection orders, row 2: expected 2 columns, got 3.' }) });
      if (mode === 'network') return route.abort();
      saved = [source];
      return route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify({
        status: 'imported', persisted: true, source,
      }) });
    });
    await page.goto(server.resolvedUrls.local[0]);
    await page.getByRole('button', { name: 'Upload File', exact: true }).click();
    const validate = page.getByRole('button', { name: 'Import File', exact: true });
    assert.equal(await validate.isDisabled(), true);
    const input = page.locator('#source-file');
    await input.setInputFiles({ name: 'bad.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('bad') });
    await page.getByRole('alert').getByText('Choose a CSV, TSV, XLSX, XLS, JSON, or NDJSON file.').waitFor();
    assert.equal(requests, 0);
    await input.setInputFiles({ name: 'too-big.csv', mimeType: 'text/csv', buffer: Buffer.alloc(25_000_001) });
    await page.getByRole('alert').getByText(/File exceeds/).waitFor();
    assert.equal(requests, 0);
    const file = { name: 'orders.csv', mimeType: 'text/csv', buffer: Buffer.from('id,id\n1,2') };
    await input.setInputFiles(file);
    await validate.click();
    await page.getByText(/Import complete/).waitFor();
    await page.getByText('1 header correction(s)').click();
    await page.getByText("Column 2: 'id' renamed to 'id_2'.", { exact: true }).waitFor();
    await page.getByRole('heading', { name: 'Data Sources', exact: true }).waitFor();
    mode = 'error';
    await input.setInputFiles(file);
    assert.equal(await page.getByText(/Import complete/).count(), 0);
    await validate.click();
    await page.getByRole('alert').getByText(/expected 2 columns/).waitFor();
    mode = 'network';
    await validate.click();
    await page.getByRole('alert').getByText(/Import completion could not be confirmed/).waitFor();
    mode = 'success';
    await validate.click();
    await page.getByText(/Import complete/).waitFor();
    await page.screenshot({ path: path.join(root, '.tmp-upload-validation.png'), fullPage: true });
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    assert.equal(await page.getByText(/Import complete/).count(), 0);
    await page.reload();
    await page.getByRole('cell', { name: 'orders.csv', exact: true }).waitFor();
    assert.equal(await page.getByRole('cell', { name: 'orders.csv', exact: true }).count(), 1);
    assert.deepEqual(errors, []);
    console.log('Upload import UI smoke passed: multipart/CSRF, local limits, success, corrections, server errors, network retry, persistent list reload, no duplicate row, no navigation.');
  } finally {
    await browser?.close();
    await server.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
