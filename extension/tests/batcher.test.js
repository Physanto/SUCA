/**
 * @file Pruebas de `UX.batcher`: acumulación por sesión y tipo, entrega por
 * tiempo y por tamaño, y reintento sin pérdidas.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/batcher.js');
const { createFakeTimers, settle } = require('./fakes.js');

const { UX } = globalThis;
const SENDING = { interval_ms: 2000, max_batch_records: 3 };
const RECORD = { t: 1791380123456.2, type: 'mousemove', x: 1, y: 2 };

/** Crea un acumulador con sustitutos y devuelve también lo que entregó. */
function setup({ fail = () => false } = {}) {
  const delivered = [];
  const timers = createFakeTimers();
  const state = { current: { session_id: 7, mode: 'free', study_id: 1, tab_id: 1, task_id: null } };
  let hide = null;
  const messages = {
    types: { BATCH: 'batch' },
    async send(type, payload) {
      if (fail(payload)) {
        throw new Error('worker unavailable');
      }
      delivered.push({ type, payload });
      return { queued: true };
    },
  };
  const batcher = UX.createBatcher({
    messages,
    session: { get: () => state.current },
    sending: SENDING,
    batchTypes: UX.contracts.enums.batch_type,
    timers,
    onPageHide: (callback) => {
      hide = callback;
    },
  });
  return { batcher, delivered, timers, state, hide: () => hide() };
}

test('delivers what was accumulated after the interval', async () => {
  const { batcher, delivered, timers } = setup();
  batcher.add('events', RECORD);
  batcher.add('events', { ...RECORD, x: 5 });

  await timers.advance(1999);
  assert.equal(delivered.length, 0);
  await timers.advance(1);

  assert.deepEqual(delivered, [
    {
      type: 'batch',
      payload: { session_id: 7, type: 'events', records: [RECORD, { ...RECORD, x: 5 }] },
    },
  ]);
  assert.equal(batcher.size(), 0);
});

test('delivers early when a batch reaches the maximum size', async () => {
  const { batcher, delivered } = setup();

  for (let i = 0; i < SENDING.max_batch_records; i += 1) {
    batcher.add('gaze', { t: i });
  }
  await settle();

  assert.equal(delivered.length, 1);
  assert.equal(delivered[0].payload.records.length, SENDING.max_batch_records);
});

test('each batch type travels in its own batch', async () => {
  const { batcher, delivered, timers } = setup();
  batcher.add('events', RECORD);
  batcher.add('face', { t: 1, face_detected: false });

  await timers.advance(SENDING.interval_ms);

  assert.deepEqual(delivered.map((item) => item.payload.type).sort(), ['events', 'face']);
});

test('records of different sessions are not mixed', async () => {
  const { batcher, delivered, state } = setup();
  batcher.add('events', RECORD);
  state.current = { ...state.current, session_id: 8 };
  batcher.add('events', RECORD);

  await batcher.flush();

  assert.deepEqual(delivered.map((item) => item.payload.session_id).sort(), [7, 8]);
});

test('records are copied when added', async () => {
  const { batcher, delivered } = setup();
  const record = { ...RECORD };
  batcher.add('events', record);
  record.x = 999;

  await batcher.flush();

  assert.equal(delivered[0].payload.records[0].x, RECORD.x);
});

test('records added without an active session are discarded', async () => {
  const { batcher, delivered, state } = setup();
  state.current = null;

  assert.equal(batcher.add('events', RECORD), false);
  await batcher.flush();

  assert.equal(delivered.length, 0);
});

test('a failed delivery keeps the records and retries them before newer ones', async () => {
  let failing = true;
  const { batcher, delivered, timers } = setup({ fail: () => failing });
  batcher.add('events', { t: 1 });

  await timers.advance(SENDING.interval_ms);
  assert.equal(delivered.length, 0);
  assert.equal(batcher.size(), 1);

  failing = false;
  batcher.add('events', { t: 2 });
  await timers.advance(SENDING.interval_ms);

  assert.deepEqual(
    delivered.map((item) => item.payload.records.map((record) => record.t)),
    [[1, 2]],
  );
});

test('flush delivers everything at once and reports whether it succeeded', async () => {
  const ok = setup();
  ok.batcher.add('events', RECORD);
  assert.equal(await ok.batcher.flush(), true);
  assert.equal(ok.delivered.length, 1);

  const broken = setup({ fail: () => true });
  broken.batcher.add('events', RECORD);
  assert.equal(await broken.batcher.flush(), false);
  assert.equal(broken.batcher.size(), 1);
});

test('hiding the page delivers what was accumulated', async () => {
  const { batcher, delivered, hide } = setup();
  batcher.add('events', RECORD);

  hide();
  await settle();

  assert.equal(delivered.length, 1);
});

test('unknown batch types fail immediately', () => {
  const { batcher } = setup();

  assert.throws(() => batcher.add('clicks', RECORD), /unknown batch type: clicks/);
});
