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
    let editFailure = null, failNextEditRetry = false, recoveredEdits = 0;
    let failNextDispatch = false, rejectNextEdit = false;
    const editHeaders = [];
    function finishEdit() {
      packageData.decisions[pendingEdit.target] = pendingEdit.decision;
      pendingEdit = null; editFailure = null; status = 'blocked';
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
        if (rejectNextEdit) {
          rejectNextEdit = false;
          return send(422, { error: { message: 'This decision was not recorded.' } });
        }
        if (receipts.has(key)) {
          if (failNextEditRetry) { failNextEditRetry = false; return route.abort(); }
          if (pendingEdit && editFailure) { editFailure = null; recoveredEdits += 1; }
          return send(202, { ...receipts.get(key), replayed: true });
        }
        pendingEdit = edit; status = 'edit_requested';
        const receipt = { job_id: 'job-1', edit_id: edit.edit_id, status, payload: null, replayed: false };
        receipts.set(key, receipt);
        if (loseEditResponse) { loseEditResponse = false; return route.abort(); }
        if (failNextDispatch) {
          failNextDispatch = false;
          return send(503, { error: { message: 'Worker dispatch is temporarily unavailable.' } });
        }
        return send(202, receipt);
      }
      if (url.endsWith('/package')) return send(200, { status, failure: status === 'failed' ? { code: 'routing_failed', message: 'Routing failed.', retryable: true } : editFailure, payload: ['queued', 'running', 'failed'].includes(status) ? null : packageData });
      return send(200, { job_id: 'job-1', status, source_snapshot_id: 'snapshot-1', model_mode: modelMode, failure: editFailure });
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
    await page.getByRole('button', { name: 'Retry edit', exact: true }).click();
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    assert.equal(editHeaders[0], editHeaders[1]);
    assert.equal(editHeaders[0], edits[0].edit_id);
    assert.deepEqual(edits[0], edits[1]);
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
    const failedEditIndex = edits.length - 1;
    const publishedBeforeFailure = JSON.stringify(packageData);
    const creationAttemptsBeforeRecovery = attempts.length;
    editFailure = { code: 'resume_failed', message: 'Temporary model failure while applying your edit.', retryable: true };
    await page.getByRole('alert').filter({ hasText: editFailure.message }).waitFor();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Retry routing', exact: true }).count(), 0);
    assert.equal(await lines.getByRole('button', { name: 'Accept', exact: true }).isDisabled(), true);
    assert.equal(await orders.getByRole('button', { name: 'Reject', exact: true }).isDisabled(), true);
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByText('Not reviewed', { exact: true }).waitFor();
    await page.reload();
    await page.getByRole('alert').filter({ hasText: editFailure.message }).waitFor();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).waitFor();
    failNextEditRetry = true;
    await page.getByRole('button', { name: 'Retry edit', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Unable to connect' }).waitFor();
    assert.deepEqual(edits.at(-1), edits[failedEditIndex]);
    assert.equal(editHeaders.at(-1), editHeaders[failedEditIndex]);
    assert.equal(recoveredEdits, 0);
    assert.equal(JSON.stringify(packageData), publishedBeforeFailure);
    // A failed retry must not discard the saved request. Refresh and try again.
    await page.reload();
    await page.getByRole('alert').filter({ hasText: editFailure.message }).waitFor();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).click();
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    assert.deepEqual(edits.at(-1), edits[failedEditIndex]);
    assert.equal(editHeaders.at(-1), editHeaders[failedEditIndex]);
    assert.equal(recoveredEdits, 1);
    assert.equal(receipts.size, 2); // Retries preserve the same two recorded edits.
    assert.equal(attempts.length, creationAttemptsBeforeRecovery); // Recovery resumes this job.
    assert.equal(JSON.stringify(packageData), publishedBeforeFailure);
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByText('Not reviewed', { exact: true }).waitFor();
    finishEdit();
    await page.waitForFunction(() => document.querySelector('section[aria-label="fact_lines"]').textContent.includes('Decision: accept'));
    await page.reload();
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByText('accept', { exact: true }).waitFor();
    await orders.getByRole('button', { name: 'Reject', exact: true }).click();
    await page.getByText('Edit already submitted; replay confirmed.', { exact: true }).waitFor();
    assert.equal(edits[0].edit_id, edits.at(-1).edit_id);
    assert.equal(editHeaders[0], editHeaders.at(-1));
    await lines.getByText('accept', { exact: true }).waitFor(); // Old receipt must not replace current package.

    // A dispatch failure can leave a recorded edit queued with no worker failure.
    // Its uncertain request must remain retryable after refresh as well.
    const receiptsBeforeDispatch = receipts.size;
    const publishedBeforeDispatch = JSON.stringify(packageData);
    failNextDispatch = true;
    await orders.getByRole('button', { name: 'Accept', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'Worker dispatch is temporarily unavailable.' }).waitFor();
    const dispatchEditIndex = edits.length - 1;
    assert.equal(status, 'edit_requested');
    assert.equal(editFailure, null);
    assert.equal(receipts.size, receiptsBeforeDispatch + 1);
    await page.reload();
    await page.getByText('Edit requested', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).waitFor();
    assert.equal(await orders.getByRole('button', { name: 'Accept', exact: true }).isDisabled(), true);
    await orders.getByText('reject', { exact: true }).waitFor();
    await lines.getByText('accept', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).click();
    await page.getByRole('button', { name: 'Retry edit', exact: true }).waitFor({ state: 'hidden' });
    await page.getByText('Your edit is pending.', { exact: false }).waitFor();
    assert.deepEqual(edits.at(-1), edits[dispatchEditIndex]);
    assert.equal(editHeaders.at(-1), editHeaders[dispatchEditIndex]);
    assert.equal(receipts.size, receiptsBeforeDispatch + 1);
    assert.equal(attempts.length, creationAttemptsBeforeRecovery);
    assert.equal(JSON.stringify(packageData), publishedBeforeDispatch);
    finishEdit();
    await orders.getByText('accept', { exact: true }).waitFor();

    // A definite validation rejection does not leave an uncertain edit or lock
    // the page into replaying a request that the server never accepted.
    const receiptsBeforeRejection = receipts.size;
    rejectNextEdit = true;
    await lines.getByRole('button', { name: 'Reject', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: 'This decision was not recorded.' }).waitFor();
    assert.equal(receipts.size, receiptsBeforeRejection);
    assert.equal(await lines.getByRole('button', { name: 'Reject', exact: true }).isEnabled(), true);
    assert.equal(await page.getByRole('button', { name: 'Retry edit', exact: true }).count(), 0);
    await page.reload();
    await lines.getByText('accept', { exact: true }).waitFor();
    assert.equal(await lines.getByRole('button', { name: 'Reject', exact: true }).isEnabled(), true);
    assert.equal(await page.getByRole('button', { name: 'Retry edit', exact: true }).count(), 0);
    modelMode = 'live'; status = 'failed';
    await page.reload();
    await page.getByRole('button', { name: 'Retry routing', exact: true }).waitFor();
    await page.getByText('live', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('Routing browser smoke passed: login, creation/edit network retries, lifecycle colors, failed-edit recovery across refresh and retry failure, queued dispatch failure recovery, validation rejection, unchanged published decisions until completion, idempotent replay, live mode, failure state. HTTP fixtures only.');
  } finally { if (browser) await browser.close(); await server.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
