/**
 * @file Pruebas del service worker completo, cargado con un `chrome` falso:
 * envío de lotes, mediación entre el panel y la pestaña evaluada, cierre de la
 * sesión después de sus lotes, recuperación de la cola y capturas.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeChrome, loadWorker, settle } = require('./fakes.js');

const SESSION = { session_id: 7, mode: 'guided', study_id: 1, tab_id: 42, task_id: null };
const EVENT = { t: 1791380123456.2, type: 'click', x: 1, y: 2 };

/** Pasa a JSON y vuelta, para comparar objetos creados en el contexto del worker. */
const plain = (value) => JSON.parse(JSON.stringify(value));

/** Carga un worker con una sesión activa en la pestaña 42. */
async function setup(options) {
  const fake = createFakeChrome(options);
  fake.areas.session.set('session', SESSION);
  const worker = loadWorker(fake);
  await settle();
  return { fake, worker };
}

test('lets content scripts read the session and opens the panel from the icon', async () => {
  const { fake } = await setup();

  assert.deepEqual(plain(fake.calls.accessLevel), { accessLevel: 'TRUSTED_AND_UNTRUSTED_CONTEXTS' });
  assert.deepEqual(plain(fake.calls.panelBehavior), { openPanelOnActionClick: true });
});

test('tells a content script the id of its tab', async () => {
  const { fake } = await setup();

  assert.deepEqual(plain(await fake.fromTab(42, 'tab.identify')), { tab_id: 42 });
});

test('queues a batch, answers once it is saved and sends it with the contract version', async () => {
  const { fake, worker } = await setup();

  const answer = await fake.fromTab(42, 'batch', {
    session_id: 7,
    type: 'events',
    records: [EVENT],
  });
  await settle();

  assert.deepEqual(plain(answer), { queued: true });
  assert.equal(fake.requests.length, 1);
  assert.equal(fake.requests[0].path, '/sessions/7/batches');
  assert.deepEqual(fake.requests[0].body, {
    contract_version: worker.UX.contracts.version,
    type: 'events',
    records: [EVENT],
  });
  assert.deepEqual(fake.areas.local.get('send_queue'), []);
});

test('rejects a batch without session', async () => {
  const { fake } = await setup();

  await assert.rejects(fake.fromTab(42, 'batch', { type: 'events', records: [] }), /session_id/);
});

test('forwards panel messages only to the evaluated tab', async () => {
  const { fake } = await setup();
  const evaluated = [];
  const other = [];
  fake.onTabMessage(42, (message) => {
    evaluated.push(message);
  });
  fake.onTabMessage(43, (message) => {
    other.push(message);
  });

  await fake.fromPanel('task.started', { task_id: 3, end_condition: null });

  assert.deepEqual(evaluated, [{ type: 'task.started', payload: { task_id: 3, end_condition: null } }]);
  assert.deepEqual(other, []);
});

test('ignores panel-only messages that come from a tab', async () => {
  const { fake } = await setup();
  const evaluated = [];
  fake.onTabMessage(42, (message) => {
    evaluated.push(message);
  });

  assert.equal(await fake.fromTab(43, 'session.started', { session_id: 7 }), undefined);
  assert.deepEqual(evaluated, []);
});

test('closes the session on the server after the last batches of the tab', async () => {
  const { fake } = await setup();
  fake.onTabMessage(42, async (message) => {
    if (message.type === 'session.closed') {
      // Al recibir el cierre, la pestaña vacía su acumulador antes de responder.
      await fake.fromTab(42, 'batch', { session_id: 7, type: 'events', records: [EVENT] });
      return { ok: true, value: { flushed: true } };
    }
    return undefined;
  });

  const answer = await fake.fromPanel('session.closed', { session_id: 7 });
  await settle();

  assert.deepEqual(plain(answer), { closing: true });
  assert.deepEqual(
    fake.requests.map((request) => request.path),
    ['/sessions/7/batches', '/sessions/7/close'],
  );
});

test('closes the session even if the evaluated tab is gone', async () => {
  const { fake } = await setup();

  await fake.fromPanel('session.closed', { session_id: 7 });
  await settle();

  assert.deepEqual(
    fake.requests.map((request) => request.path),
    ['/sessions/7/close'],
  );
});

test('recovers the saved queue when it wakes up', async () => {
  const fake = createFakeChrome();
  fake.areas.local.set('send_queue', [
    { id: 1, kind: 'batch', session_id: 7, body: { type: 'events' }, attempts: 1, not_before: 0 },
    { id: 2, kind: 'close', session_id: 7, attempts: 0, not_before: 0 },
  ]);

  loadWorker(fake);
  await settle();

  assert.deepEqual(
    fake.requests.map((request) => request.path),
    ['/sessions/7/batches', '/sessions/7/close'],
  );
});

test('drops batches the server rejects and keeps sending the rest', async () => {
  const { fake } = await setup({
    server: (path, request) =>
      request.body && request.body.type === 'gaze'
        ? { status: 422, body: { detail: 'batch does not match its contract', errors: [] } }
        : { status: 200, body: {} },
  });

  await fake.fromTab(42, 'batch', { session_id: 7, type: 'gaze', records: [{ t: 1 }] });
  await fake.fromTab(42, 'batch', { session_id: 7, type: 'events', records: [EVENT] });
  await settle();

  assert.deepEqual(
    fake.requests.map((request) => request.body.type),
    ['gaze', 'events'],
  );
  assert.deepEqual(fake.areas.local.get('send_queue'), []);
});

test('keeps a batch saved while the server is down', async () => {
  const { fake } = await setup({ server: () => ({ status: 503, body: { detail: 'down' } }) });

  await fake.fromTab(42, 'batch', { session_id: 7, type: 'events', records: [EVENT] });
  await settle();

  const [saved] = fake.areas.local.get('send_queue');
  assert.equal(saved.kind, 'batch');
  assert.equal(saved.attempts, 1);
});

test('captures the evaluated tab and sends it to the server', async () => {
  const { fake } = await setup({
    server: (path) =>
      path === '/captures'
        ? { status: 201, body: { capture_id: 1, file_path: 'captures/1/a.png' } }
        : { status: 200, body: {} },
  });
  const screen = { url: 'https://shop.local/cart', title: 'Carrito' };

  const answer = await fake.fromPanel('screen_capture.request', { study_id: 1, screen });

  assert.deepEqual(plain(answer), { capture_id: 1, file_path: 'captures/1/a.png' });
  assert.deepEqual(plain(fake.calls.captured), [{ windowId: 142, options: { format: 'png' } }]);
  assert.deepEqual(fake.requests[0].body, {
    study_id: 1,
    screen,
    image: 'data:image/png;base64,iVBORw0KGgo=',
  });
});
