/**
 * @file Pruebas de `UX.messages`: tipos del contrato, envío, suscripción y respuestas.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/messages.js');
const { createFakeWorld } = require('./fakes.js');

const { UX } = globalThis;
const messageTypes = UX.contracts.enums.message_type;

/** Crea un panel y un worker conectados. */
function panelAndWorker() {
  const world = createFakeWorld();
  return {
    world,
    panel: UX.createMessages({ platform: world.platform(), messageTypes }),
    worker: UX.createMessages({ platform: world.platform(), messageTypes }),
  };
}

test('types are constants taken from the contract', () => {
  const { panel } = panelAndWorker();

  assert.equal(panel.types.SESSION_STARTED, 'session.started');
  assert.equal(panel.types.SCREEN_CAPTURE_REQUEST, 'screen_capture.request');
  assert.deepEqual(Object.values(panel.types).sort(), [...messageTypes].sort());
  assert.ok(Object.isFrozen(panel.types));
});

test('unknown types fail immediately', async () => {
  const { panel } = panelAndWorker();

  await assert.rejects(panel.send('session.begun', {}), /unknown message type: session.begun/);
  assert.throws(() => panel.on('rageclick', () => {}), /unknown message type/);
});

test('subscribers receive the payload and the sender', async () => {
  const { panel, worker } = panelAndWorker();
  const received = [];
  worker.on(worker.types.SESSION_CLOSED, (payload, sender) => {
    received.push({ payload, sender });
  });

  const answer = await panel.send(panel.types.SESSION_CLOSED, { session_id: 7 });

  assert.equal(answer, undefined);
  assert.deepEqual(received, [{ payload: { session_id: 7 }, sender: { tabId: null } }]);
});

test('the first value returned by a subscriber is the response', async () => {
  const { panel, worker } = panelAndWorker();
  worker.on(worker.types.TAB_IDENTIFY, () => undefined);
  worker.on(worker.types.TAB_IDENTIFY, async () => ({ tab_id: 4 }));

  assert.deepEqual(await panel.send(panel.types.TAB_IDENTIFY), { tab_id: 4 });
});

test('a failing subscriber rejects the sender with its message', async () => {
  const { panel, worker } = panelAndWorker();
  worker.on(worker.types.BATCH, async () => {
    throw new Error('queue is full');
  });

  await assert.rejects(panel.send(panel.types.BATCH, {}), /queue is full/);
});

test('unsubscribing stops the deliveries', async () => {
  const { panel, worker } = panelAndWorker();
  let calls = 0;
  const unsubscribe = worker.on(worker.types.CAMERA_STATUS, () => {
    calls += 1;
  });

  await panel.send(panel.types.CAMERA_STATUS, { status: 'active' });
  unsubscribe();
  await panel.send(panel.types.CAMERA_STATUS, { status: 'error' });

  assert.equal(calls, 1);
});

test('sendToTab reaches only the content scripts of that tab', async () => {
  const world = createFakeWorld();
  const worker = UX.createMessages({ platform: world.platform(), messageTypes });
  const evaluated = UX.createMessages({ platform: world.platform({ tabId: 1 }), messageTypes });
  const other = UX.createMessages({ platform: world.platform({ tabId: 2 }), messageTypes });
  const seen = [];
  evaluated.on(evaluated.types.TASK_STARTED, (payload) => seen.push(['evaluated', payload.task_id]));
  other.on(other.types.TASK_STARTED, (payload) => seen.push(['other', payload.task_id]));

  await worker.sendToTab(1, worker.types.TASK_STARTED, { task_id: 3, end_condition: null });

  assert.deepEqual(seen, [['evaluated', 3]]);
});

test('sending without any receiver rejects', async () => {
  const world = createFakeWorld();
  const lonely = UX.createMessages({ platform: world.platform({ tabId: 1 }), messageTypes });

  await assert.rejects(lonely.send(lonely.types.BATCH, {}), /Receiving end does not exist/);
});
