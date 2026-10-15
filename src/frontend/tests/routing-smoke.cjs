// Browser boundary smoke with HTTP fixtures; not a real model/database integration.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const root = path.resolve(__dirname, '..');
(async () => {
  const { createServer } = await import(pathToFileURL(path.join(root, 'node_modules/vite/dist/node/index.js')).href);
  const server = await createServer({ root, server: { host: '127.0.0.1', port: 0 } });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ ...(process.env.CHROME_BIN ? { executablePath: process.env.CHROME_BIN } : {}), headless: true });
    const page = await browser.newPage();
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    let user = null, status = 'queued', attempts = [], edits = [], failFirst = true;
    let modelMode = 'fake', pendingEdit = null, loseEditResponse = true;
    const editHeaders = [];
    function finishEdit() {
      packageData.decisions[pendingEdit.target] = pendingEdit.decision;
      pendingEdit = null; status = 'blocked';
    }
    const packageData = {
      contract_version: '1',
      model_draft: { revision: 1, unresolved: [], tables: ['fact_orders', 'fact_lines'].map(id => ({ id, name: id, key: ['id'], rationale: 'Preserve order grain.', attributes: [{ id: 'id', type: 'text', confidence: 0.9 }] })) },
      mapping_draft: { revision: 1, mappings: ['fact_orders', 'fact_lines'].map(id => ({ target: `${id}.id`, sources: ['orders.id'], confidence: 0.9, rationale: 'Identifier match.' })), unresolved: [] },
      is_new: { fact_orders: true, fact_lines: false }, decisions: {},
      findings: [{ code: 'ambiguous_date', severity: 'blocker', target: 'fact_orders', message: 'Confirm date format.' }, { code: 'invalid_source_reference', severity: 'blocker', target: 'fact_orders', message: 'Source field not found.' }],
      coverage: [{ resource_id: 'orders', field_path: 'id', disposition: 'represented', reason: 'Mapped to key.' }],
    };
    const receipts = new Map();
    await page.route('**/api/**', async route => {
      const req = route.request(), url = new URL(req.url()).pathname;
      const send = (code, body) => route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(body) });
      if (url.endsWith('/auth/me')) return send(user ? 200 : 401, user ? { user } : { error: { code: 'unauthorized' } });
      if (url.endsWith('/auth/login')) { user = { id: 'demo-user', username: 'demo', email: 'demo', role: 'Administrator' }; return send(200, { user }); }
      if (url.endsWith('/jobs') && req.method() === 'POST') {
        attempts.push({ key: req.headers()['idempotency-key'], body: req.postDataJSON() });
        if (failFirst) { failFirst = false; return route.abort(); }
        return send(202, { job_id: 'job-1', status });
      }
      if (url.endsWith('/edits')) {
        const edit = req.postDataJSON(); edits.push(edit);
        const key = req.headers()['idempotency-key']; editHeaders.push(key);
        if (!key) return send(400, { error: { message: 'Idempotency-Key required.' } });
        if (receipts.has(key)) return send(202, { ...receipts.get(key), replayed: true });
        pendingEdit = edit; status = 'edit_requested';
        const receipt = { job_id: 'job-1', edit_id: edit.edit_id, status, payload: null, replayed: false };
        receipts.set(key, receipt);
        if (loseEditResponse) { loseEditResponse = false; return route.abort(); }
        return send(202, receipt);
      }
      if (url.endsWith('/package')) return send(200, { status, failure: status === 'failed' ? { code: 'routing_failed', message: 'Routing failed.', retryable: true } : null, payload: ['queued', 'running', 'failed'].includes(status) ? null : packageData });
      return send(200, { job_id: 'job-1', status, source_snapshot_id: 'snapshot-1', model_mode: modelMode, failure: null });
    });
    await page.goto(server.resolvedUrls.local[0]);
    await page.locator('input[type=email]').fill('demo');
    await page.locator('input[type=password]').fill('test');
    await page.getByRole('button', { name: 'Sign In', exact: true }).click();
    await page.getByRole('button', { name: 'Discover', exact: true }).first().click();
    await page.getByLabel('Source snapshot ID').fill('snapshot-1');
    await page.getByRole('button', { name: 'Find where this data belongs' }).click();
    await page.getByRole('alert').filter({ hasText: 'Unable to connect' }).waitFor();
    await page.getByRole('button', { name: 'Find where this data belongs' }).click();
    await page.getByText('Routing is queued.', { exact: false }).waitFor();
    assert.equal(attempts.length, 2); assert.equal(attempts[0].key, attempts[1].key);
    assert.equal(attempts[1].body.source_snapshot_id, 'snapshot-1');
    const queuedColor = await page.getByText('Queued', { exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
    status = 'running';
    await page.getByText('Routing is running.', { exact: false }).waitFor();
    status = 'awaiting_review';
    const waiting = page.getByText('Awaiting review', { exact: true });
    await waiting.waitFor();
    const waitingColor = await waiting.evaluate(el => getComputedStyle(el).backgroundColor);
    status = 'blocked';
    await page.reload();
    await page.getByText('Blocked', { exact: true }).waitFor();
    const blockedColor = await page.getByText('Blocked', { exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
    await page.getByRole('heading', { name: 'Proposed tables (2)' }).waitFor();
    await page.getByText('blocker · ambiguous_date', { exact: true }).waitFor();
    await page.getByText('blocker · invalid_source_reference', { exact: true }).waitFor();
    const orders = page.getByRole('region', { name: 'fact_orders', exact: true });
    const lines = page.getByRole('region', { name: 'fact_lines', exact: true });
    assert.match(await orders.innerText(), /New table/); assert.match(await lines.innerText(), /Reuse table/);
    assert.match(await orders.innerText(), /90%/);
    await orders.getByRole('button', { name: 'Reject', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Unable to connect' }).waitFor();
    await orders.getByRole('button', { name: 'Reject', exact: true }).click();
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    assert.equal(editHeaders[0], editHeaders[1]);
    assert.equal(editHeaders[0], edits[0].edit_id);
    const pendingColor = await page.getByText('Edit requested', { exact: true }).evaluate(el => getComputedStyle(el).backgroundColor);
    assert.equal(new Set([queuedColor, waitingColor, blockedColor, pendingColor]).size, 4);
    assert.equal(await orders.getByRole('button', { name: 'Accept', exact: true }).isDisabled(), true);
    await page.reload();
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    await orders.getByText('Not reviewed', { exact: true }).waitFor();
    finishEdit();
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByRole('button', { name: 'Accept', exact: true }).click();
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    finishEdit();
    await page.waitForFunction(() => document.querySelector('section[aria-label="fact_lines"]').textContent.includes('Decision: accept'));
    await page.reload();
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByText('accept', { exact: true }).waitFor();
    await orders.getByRole('button', { name: 'Reject', exact: true }).click();
    await page.getByText('Edit already submitted; replay confirmed.', { exact: true }).waitFor();
    assert.equal(edits[0].edit_id, edits[3].edit_id);
    assert.equal(editHeaders[0], editHeaders[3]);
    await lines.getByText('accept', { exact: true }).waitFor(); // Old receipt must not replace current package.
    modelMode = 'live'; status = 'failed';
    await page.reload();
    await page.getByRole('button', { name: 'Retry routing', exact: true }).waitFor();
    await page.getByText('live', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('Routing browser smoke passed: login, creation/edit network retries, lifecycle colors, pending edits, disabled controls, refresh, async completion, replay, live mode, failure state. HTTP fixtures only.');
  } finally { if (browser) await browser.close(); await server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
