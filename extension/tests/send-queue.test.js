/**
 * @file Pruebas de la cola de envío: orden estricto, guardado antes de enviar,
 * reintentos con espera creciente y descarte de errores permanentes.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../common/send-queue.js');
const { createFakeTimers, settle } = require('./fakes.js');

const { UX } = globalThis;

/** Error del servidor como los que lanza `UX.api`. */
const serverError = (status) =>
  Object.assign(new Error(`${status}`), { permanent: status >= 400 && status < 500 });

/** Crea una cola con un servidor simulado que responde con `respond(job)`. */
function setup({ respond = () => undefined, saved } = {}) {
  const timers = createFakeTimers();
  const sent = [];
  const persisted = [];
  const dropped = [];
  const queue = UX.createSendQueue({
    async send(job) {
      sent.push(job.kind === 'close' ? `close:${job.session_id}` : job.body);
      const error = respond(job);
      if (error) {
        throw error;
      }
    },
    async persist(jobs) {
      persisted.push(jobs.map((job) => job.id));
    },
    retryInitialMs: 1000,
    retryMaxMs: 4000,
    now: timers.now,
    timers,
    onDrop: (job, error) => dropped.push([job.id, error.message]),
  });
  queue.load(saved);
  return { queue, timers, sent, persisted, dropped };
}

test('sends jobs in order and empties the queue', async () => {
  const { queue, sent } = setup();

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'a' });
  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'b' });
  await queue.enqueue({ kind: 'close', session_id: 7 });
  await settle();

  assert.deepEqual(sent, ['a', 'b', 'close:7']);
  assert.equal(queue.size(), 0);
});

test('a job is saved before it is sent', async () => {
  let savedBeforeSending = null;
  const persisted = [];
  const queue = UX.createSendQueue({
    async send() {
      savedBeforeSending = persisted.at(-1);
    },
    async persist(jobs) {
      persisted.push(jobs.map((job) => job.body));
    },
    retryInitialMs: 1000,
    retryMaxMs: 4000,
  });

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'a' });
  await settle();

  assert.deepEqual(savedBeforeSending, ['a']);
  assert.deepEqual(persisted.at(-1), []);
});

test('transient failures wait twice as long each time, up to the maximum', async () => {
  let failures = 4;
  const { queue, timers, sent } = setup({
    respond: () => (failures-- > 0 ? serverError(503) : undefined),
  });

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'a' });
  await settle();
  const attemptsAt = [];
  for (const wait of [1000, 2000, 4000, 4000]) {
    await timers.advance(wait - 1);
    attemptsAt.push(sent.length);
    await timers.advance(1);
  }

  assert.deepEqual(attemptsAt, [1, 2, 3, 4]);
  assert.equal(sent.length, 5);
  assert.equal(queue.size(), 0);
});

test('a job waiting to retry blocks the ones behind it, so a close never overtakes its batches', async () => {
  let down = true;
  const { queue, timers, sent } = setup({
    respond: () => (down ? serverError(0) : undefined),
  });

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'last batch' });
  await queue.enqueue({ kind: 'close', session_id: 7 });
  await settle();
  assert.deepEqual(sent, ['last batch']);

  down = false;
  await timers.advance(1000);

  assert.deepEqual(sent, ['last batch', 'last batch', 'close:7']);
});

test('permanent failures are dropped and the queue goes on', async () => {
  const { queue, sent, dropped } = setup({
    respond: (job) => (job.body === 'bad' ? serverError(422) : undefined),
  });

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'bad' });
  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'good' });
  await settle();

  assert.deepEqual(sent, ['bad', 'good']);
  assert.deepEqual(dropped, [[1, '422']]);
  assert.equal(queue.size(), 0);
});

test('a saved queue is recovered and its ids continue', async () => {
  const saved = [{ id: 5, kind: 'batch', session_id: 7, body: 'from before', attempts: 2, not_before: 0 }];
  const { queue, sent } = setup({ saved });

  await queue.drain();
  await queue.enqueue({ kind: 'close', session_id: 7 });
  await settle();

  assert.deepEqual(sent, ['from before', 'close:7']);
});

test('jobs added while sending are sent too', async () => {
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  const sent = [];
  const queue = UX.createSendQueue({
    async send(job) {
      sent.push(job.body);
      if (job.body === 'a') {
        await gate;
      }
    },
    persist: async () => {},
    retryInitialMs: 1000,
    retryMaxMs: 4000,
  });

  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'a' });
  await queue.enqueue({ kind: 'batch', session_id: 7, body: 'b' });
  release();
  await settle();

  assert.deepEqual(sent, ['a', 'b']);
});
