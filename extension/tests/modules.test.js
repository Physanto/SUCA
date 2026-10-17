/**
 * @file Pruebas de `UX.modules`: registro de módulos y su ciclo de vida.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../common/modules.js');
const { createFakeTimers } = require('./fakes.js');

const { UX } = globalThis;

/** Crea un registro que anota los errores y usa temporizadores manuales. */
function setup() {
  const errors = [];
  const timers = createFakeTimers();
  const modules = UX.createModules({
    logger: { error: (...args) => errors.push(args.map(String).join(' ')) },
    timers,
  });
  return { modules, errors, timers };
}

/** Módulo de prueba que anota cuándo se inicia y se detiene. */
function probe(name, calls, { start, stop } = {}) {
  return {
    name,
    start(ctx) {
      calls.push(`${name}.start`);
      return start && start(ctx);
    },
    stop() {
      calls.push(`${name}.stop`);
      return stop && stop();
    },
  };
}

const never = () => new Promise(() => {});

test('registers modules and lists their names in order', () => {
  const { modules } = setup();

  modules.register(probe('capture', []));
  modules.register(probe('camera', []));

  assert.deepEqual(modules.names(), ['capture', 'camera']);
});

test('rejects modules without a name, without start or stop, or with a repeated name', () => {
  const { modules } = setup();
  modules.register(probe('capture', []));

  assert.throws(() => modules.register({ start() {}, stop() {} }), /name/);
  assert.throws(() => modules.register({ name: 'x', start() {} }), /start\(ctx\) and stop\(\)/);
  assert.throws(() => modules.register(probe('capture', [])), /already registered: capture/);
});

test('starts every module with the same context', async () => {
  const { modules } = setup();
  const seen = [];
  modules.register({ name: 'a', start: (ctx) => seen.push(ctx), stop() {} });
  modules.register({ name: 'b', start: (ctx) => seen.push(ctx), stop() {} });
  const ctx = { clock: {} };

  const result = await modules.startAll(ctx);

  assert.deepEqual(result, { started: ['a', 'b'], failed: [] });
  assert.equal(seen[0], ctx);
  assert.equal(seen[1], ctx);
  assert.equal(modules.isRunning(), true);
});

test('a module that fails to start is logged and does not stop the others', async () => {
  const { modules, errors } = setup();
  const calls = [];
  modules.register(probe('broken', calls, { start: () => { throw new Error('boom'); } }));
  modules.register(probe('rejecting', calls, { start: () => Promise.reject(new Error('no camera')) }));
  modules.register(probe('fine', calls));

  const result = await modules.startAll({});

  assert.deepEqual(result, { started: ['fine'], failed: ['broken', 'rejecting'] });
  assert.ok(calls.includes('fine.start'));
  assert.ok(errors.some((line) => line.includes('module broken failed to start') && line.includes('boom')));
  assert.ok(errors.some((line) => line.includes('module rejecting failed to start')));
});

test('modules start at the same time, so a slow one does not delay the others', () => {
  const { modules } = setup();
  const calls = [];
  modules.register(probe('slow', calls, { start: never }));
  modules.register(probe('fast', calls));

  modules.startAll({});

  assert.deepEqual(calls, ['slow.start', 'fast.start']);
});

test('starting twice starts each module once and returns the first result', async () => {
  const { modules } = setup();
  const calls = [];
  modules.register(probe('capture', calls));

  const first = await modules.startAll({});
  const second = await modules.startAll({});

  assert.deepEqual(calls, ['capture.start']);
  assert.deepEqual(second, first);
});

test('stops every module and can start them again', async () => {
  const { modules } = setup();
  const calls = [];
  modules.register(probe('a', calls));
  modules.register(probe('b', calls));
  await modules.startAll({});

  const result = await modules.stopAll();
  await modules.startAll({});

  assert.deepEqual(result, { stopped: ['a', 'b'], failed: [] });
  assert.deepEqual(calls, ['a.start', 'b.start', 'a.stop', 'b.stop', 'a.start', 'b.start']);
});

test('stopping without starting does nothing', async () => {
  const { modules } = setup();
  const calls = [];
  modules.register(probe('a', calls));

  assert.deepEqual(await modules.stopAll(), { stopped: [], failed: [] });
  assert.deepEqual(calls, []);
  assert.equal(modules.isRunning(), false);
});

test('a module that fails to stop is logged and the others still stop', async () => {
  const { modules, errors } = setup();
  const calls = [];
  modules.register(probe('broken', calls, { stop: () => { throw new Error('stuck'); } }));
  modules.register(probe('fine', calls));
  await modules.startAll({});

  const result = await modules.stopAll();

  assert.deepEqual(result, { stopped: ['fine'], failed: ['broken'] });
  assert.ok(calls.includes('fine.stop'));
  assert.ok(errors.some((line) => line.includes('module broken failed to stop')));
});

test('a stop that never finishes is abandoned after the timeout', async () => {
  const { modules, errors, timers } = setup();
  modules.register(probe('hung', [], { stop: never }));
  modules.register(probe('fine', []));
  await modules.startAll({});

  const stopping = modules.stopAll();
  await timers.advance(2000);

  assert.deepEqual(await stopping, { stopped: ['fine'], failed: ['hung'] });
  assert.ok(errors.some((line) => line.includes('module hung did not stop within 2000 ms')));
  assert.equal(timers.pending(), 0);
});

test('modules can be stopped while a start is still in progress', async () => {
  const { modules } = setup();
  const calls = [];
  modules.register(probe('camera', calls, { start: never }));
  modules.startAll({});

  const result = await modules.stopAll();

  assert.deepEqual(result, { stopped: ['camera'], failed: [] });
  assert.deepEqual(calls, ['camera.start', 'camera.stop']);
});
