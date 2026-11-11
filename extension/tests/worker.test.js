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

test('treats the panel opened as a tab like the side panel', async () => {
  const { fake } = await setup();
  const evaluated = [];
  fake.onTabMessage(42, (message) => {
    evaluated.push(message);
    // Como responde `UX.messages` en el content script.
    return { ok: true, value: { started: ['capture'], failed: [] } };
  });

  // Una página de la extensión en una pestaña también trae `sender.tab`.
  const reply = await fake.sendToWorker(
    { type: 'session.started', payload: { session_id: 7, mode: 'guided', study_id: 1 } },
    { tab: { id: 99 }, url: 'chrome-extension://fake-extension/panel/panel.html' },
  );

  assert.deepEqual(plain(reply), { started: ['capture'], failed: [] });
  assert.equal(evaluated.length, 1);
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

const MASKED_JPEG = `data:image/jpeg;base64,${Buffer.from('MASKED').toString('base64')}`;
const FRAME = { viewport_width: 1200, masks: [{ x: 10, y: 20, w: 100, h: 30 }] };

/** Hace que la pestaña 42 responda `frame.masks` con estas zonas (o falle con `null`). */
function answerMasks(fake, masks = []) {
  fake.onTabMessage(42, (message) =>
    message.type === 'frame.masks'
      ? masks === null
        ? { ok: false, error: 'module stopped' }
        : { ok: true, value: { viewport_width: 1200, masks } }
      : undefined,
  );
}

test('records a frame of the evaluated tab with the fields of both measurements masked', async () => {
  const { fake } = await setup();
  // La página cambió entre el pedido y la captura: el campo bajó 60 px.
  answerMasks(fake, [{ x: 10, y: 80, w: 100, h: 30 }]);

  assert.equal(await fake.fromTab(42, 'frame.request', FRAME), undefined);
  await settle();

  assert.deepEqual(plain(fake.calls.captured), [{ windowId: 142, options: { format: 'jpeg', quality: 60 } }]);
  // La imagen tiene el doble de ancho que la ventana: las zonas se escalan.
  assert.deepEqual(plain(fake.calls.masked), [
    { x: 20, y: 40, w: 200, h: 60 },
    { x: 20, y: 160, w: 200, h: 60 },
  ]);
  assert.equal(fake.requests.length, 1);
  assert.equal(fake.requests[0].path, '/sessions/7/frames');
  assert.equal(fake.requests[0].body.image, MASKED_JPEG);
  assert.equal(typeof fake.requests[0].body.t, 'number');
});

test('a frame without masks is sent as captured', async () => {
  const { fake } = await setup();
  answerMasks(fake, []);

  await fake.fromTab(42, 'frame.request', { viewport_width: 1200, masks: [] });
  await settle();

  assert.equal(fake.requests[0].body.image, 'data:image/jpeg;base64,/9j/4AAQ');
});

test('ignores frames from other tabs, of an inactive evaluated tab or too close to the last one', async () => {
  const other = await setup();
  await other.fake.fromTab(43, 'frame.request', FRAME);
  await settle();
  assert.equal(other.fake.calls.captured.length, 0);

  const inactive = await setup({ inactiveTabs: [42] });
  await inactive.fake.fromTab(42, 'frame.request', FRAME);
  await settle();
  assert.equal(inactive.fake.calls.captured.length, 0);
  assert.equal(inactive.fake.requests.length, 0);

  const { fake } = await setup();
  answerMasks(fake);
  await fake.fromTab(42, 'frame.request', FRAME);
  await fake.fromTab(42, 'frame.request', FRAME);
  await settle();
  assert.equal(fake.requests.length, 1);
});

test('a frame is never sent when the tab cannot measure the masks again', async () => {
  const { fake } = await setup();
  answerMasks(fake, null);

  await fake.fromTab(42, 'frame.request', FRAME);
  await settle();

  assert.equal(fake.calls.captured.length, 1);
  assert.equal(fake.requests.length, 0);
});

test('a frame that cannot be masked is never sent', async () => {
  const { fake, worker } = await setup();
  answerMasks(fake);
  worker.UX.maskFrame = async () => {
    throw new Error('canvas failed');
  };

  await fake.fromTab(42, 'frame.request', FRAME);
  await settle();

  assert.equal(fake.calls.captured.length, 1);
  assert.equal(fake.requests.length, 0);
});

test('opens the camera engine before starting the modules of the evaluated tab', async () => {
  const { fake } = await setup();
  let engineOpenWhenStarted = null;
  fake.onTabMessage(42, () => {
    engineOpenWhenStarted = fake.offscreenUrl();
    return { ok: true, value: { started: ['camera'], failed: [] } };
  });

  await fake.fromPanel('session.started', { session_id: 7, mode: 'guided', study_id: 1 });

  assert.equal(engineOpenWhenStarted, 'chrome-extension://fake-extension/camera/engine.html');
  assert.deepEqual(plain(fake.calls.offscreen[0].reasons), ['USER_MEDIA']);
});

test('reopens the camera engine when the evaluated tab loads a page, and only for that tab', async () => {
  const { fake } = await setup();

  await fake.fromTab(43, 'tab.identify');
  await settle();
  assert.equal(fake.offscreenUrl(), null);

  await fake.fromTab(42, 'tab.identify');
  await fake.fromTab(42, 'tab.identify');
  await settle();
  assert.equal(fake.offscreenUrl(), 'chrome-extension://fake-extension/camera/engine.html');
  assert.equal(fake.calls.offscreen.length, 1, 'a second page load must not create a second engine');
});

test('closes the camera engine after the evaluated tab confirms the close', async () => {
  const { fake } = await setup();
  const order = [];
  fake.onTabMessage(42, (message) => {
    if (message.type === 'session.closed') {
      order.push(`tab closed, engine ${fake.offscreenUrl() ? 'open' : 'closed'}`);
      return { ok: true, value: { flushed: true } };
    }
    return { ok: true, value: { started: [], failed: [] } };
  });
  await fake.fromPanel('session.started', { session_id: 7, mode: 'guided', study_id: 1 });

  await fake.fromPanel('session.closed', { session_id: 7 });

  // La pestaña pide al motor el último intervalo sin datos antes de que se cierre.
  assert.deepEqual(order, ['tab closed, engine open']);
  assert.equal(fake.offscreenUrl(), null);
});

test('closes the camera engine when the session state is cleared', async () => {
  const { fake } = await setup();
  await fake.fromTab(42, 'tab.identify');
  await settle();

  await fake.chrome.storage.session.remove('session');
  await settle();

  assert.equal(fake.offscreenUrl(), null);
});

test('opens the camera permission page once per session when the engine has no permission', async () => {
  const { fake } = await setup();

  await fake.fromPanel('camera.status', { status: 'no_permission' });
  await fake.fromPanel('camera.status', { status: 'no_permission' });
  await fake.fromPanel('camera.status', { status: 'active' });
  await settle();

  assert.deepEqual(fake.calls.openedTabs, ['chrome-extension://fake-extension/camera/permission.html']);
});

test('asks for the camera permission on first install but not on updates', async () => {
  const { fake } = await setup();

  fake.install('update');
  fake.install('install');
  await settle();

  assert.deepEqual(fake.calls.openedTabs, ['chrome-extension://fake-extension/camera/permission.html']);
});
