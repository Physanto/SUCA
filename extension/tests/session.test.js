/**
 * @file Pruebas de `UX.session`: estado compartido entre contextos en `storage.session`.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/session.js');
const { createFakeWorld, settle } = require('./fakes.js');

const { UX } = globalThis;
const modes = UX.contracts.enums.session_mode;
const INFO = { session_id: 7, mode: 'guided', study_id: 1, tab_id: 42 };

/** Crea el estado de la sesión de un contexto nuevo en el mismo mundo. */
const sessionIn = (world) => UX.createSession({ platform: world.platform(), modes });

test('starts with no active session', async () => {
  const session = sessionIn(createFakeWorld());

  await session.ready;

  assert.equal(session.get(), null);
});

test('start writes the state with no active task', async () => {
  const world = createFakeWorld();
  const panel = sessionIn(world);

  await panel.start(INFO);

  assert.deepEqual(panel.get(), { ...INFO, recorded_fields: [], task_id: null });
  assert.deepEqual(world.areas.session.get('session'), { ...INFO, recorded_fields: [], task_id: null });
  assert.ok(Object.isFrozen(panel.get()));
});

test('other contexts see the changes and their subscribers are notified once', async () => {
  const world = createFakeWorld();
  const panel = sessionIn(world);
  const content = sessionIn(world);
  await content.ready;
  const seen = [];
  content.subscribe((state) => seen.push(state && state.task_id));

  await panel.start(INFO);
  await settle();
  await panel.update({ task_id: 3 });
  await settle();
  await panel.clear();
  await settle();

  assert.deepEqual(seen, [null, 3, null]);
  assert.equal(content.get(), null);
});

test('a context created later loads the saved state', async () => {
  const world = createFakeWorld();
  await sessionIn(world).start(INFO);

  const late = sessionIn(world);
  await late.ready;

  assert.equal(late.get().session_id, 7);
});

test('reload reads a state whose change notice has not arrived yet', async () => {
  const world = createFakeWorld();
  const worker = sessionIn(world);
  await worker.ready;

  await sessionIn(world).start(INFO);

  assert.equal(worker.get(), null);
  assert.equal((await worker.reload()).tab_id, 42);
});

test('the state must match the contract', async () => {
  const panel = sessionIn(createFakeWorld());

  await assert.rejects(panel.start({ ...INFO, mode: 'demo' }), /unknown session mode/);
  await assert.rejects(panel.start({ ...INFO, tab_id: '42' }), /tab_id must be an integer/);
  await assert.rejects(panel.start({ ...INFO, participant: 'P07' }), /unknown session field/);
  await assert.rejects(panel.start({ ...INFO, recorded_fields: ['#q'] }), /recorded_fields must be a list/);
});

test('start keeps the fields whose text the study records', async () => {
  const panel = sessionIn(createFakeWorld());
  const fields = [{ name: 'search', selector: '#q' }];

  await panel.start({ ...INFO, recorded_fields: fields });
  await panel.update({ task_id: 3 });

  assert.deepEqual(panel.get().recorded_fields, fields);
});

test('updating without an active session fails', async () => {
  const panel = sessionIn(createFakeWorld());

  await assert.rejects(panel.update({ task_id: 3 }), /no active session/);
});
