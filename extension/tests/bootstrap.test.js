/**
 * @file Pruebas de `content/bootstrap.js`: los módulos arrancan y se detienen
 * con la sesión, solo en la pestaña evaluada.
 *
 * Cada prueba arma un mundo en memoria con tres contextos: el panel (escribe
 * la sesión), el worker (responde `tab.identify` y reenvía a la pestaña) y la
 * pestaña con sus content scripts.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/clock.js');
require('../common/messages.js');
require('../common/session.js');
require('../common/modules.js');
require('../content/bootstrap.js');
const { createFakeWorld, settle } = require('./fakes.js');

const { UX } = globalThis;
const { enums } = UX.contracts;
const SESSION = { session_id: 7, mode: 'free', study_id: 1, tab_id: 42 };

/** Pasa a JSON y vuelta, para comparar respuestas que cruzaron contextos. */
const plain = (value) => JSON.parse(JSON.stringify(value));

/** Arma el panel y el worker de un mundo nuevo. */
function createExtension() {
  const world = createFakeWorld();
  const panel = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  const worker = UX.createMessages({ platform: world.platform(), messageTypes: enums.message_type });
  worker.on(worker.types.TAB_IDENTIFY, (payload, sender) => ({ tab_id: sender.tabId }));
  return { world, panel, worker };
}

/** Carga los content scripts de una pestaña con módulos de prueba. */
function loadTab(world, tabId, moduleList) {
  const platform = world.platform({ tabId });
  const calls = [];
  const modules = UX.createModules({ logger: { error() {} } });
  for (const module of moduleList(calls)) {
    modules.register(module);
  }
  const batcher = {
    add() {},
    flush: async () => {
      calls.push('flush');
      return true;
    },
  };
  const session = UX.createSession({ platform, modes: enums.session_mode });
  const bootstrap = UX.createBootstrap({
    modules,
    messages: UX.createMessages({ platform, messageTypes: enums.message_type }),
    session,
    batcher,
    clock: UX.clock,
    config: UX.config,
    contracts: UX.contracts,
  });
  return { bootstrap, calls, modules, session };
}

/** Módulo que anota sus llamadas y lo que veía de la sesión al iniciar. */
const probe = (name, calls, start) => ({
  name,
  start(ctx) {
    calls.push(`${name}.start`);
    calls.push({ sessionAtStart: ctx.session.get() });
    if (start) {
      start(ctx);
    }
  },
  stop() {
    calls.push(`${name}.stop`);
  },
});

test('does not start the modules when there is no active session', async () => {
  const { world } = createExtension();
  const tab = loadTab(world, 42, (calls) => [probe('capture', calls)]);

  assert.equal(await tab.bootstrap.ready, false);
  assert.deepEqual(tab.calls, []);
});

test('starts the modules on page load when the session belongs to this tab', async () => {
  const { world, panel } = createExtension();
  await panel.start(SESSION);

  const tab = loadTab(world, 42, (calls) => [probe('capture', calls)]);

  assert.equal(await tab.bootstrap.ready, true);
  assert.equal(tab.calls[0], 'capture.start');
  assert.equal(tab.modules.isRunning(), true);
});

test('does not start the modules in another tab', async () => {
  const { world, panel } = createExtension();
  await panel.start(SESSION);

  const other = loadTab(world, 7, (calls) => [probe('capture', calls)]);

  assert.equal(await other.bootstrap.ready, false);
  assert.deepEqual(other.calls, []);
});

test('starts the modules on session.started and replies with the result', async () => {
  const { world, panel, worker } = createExtension();
  const tab = loadTab(world, 42, (calls) => [
    probe('capture', calls),
    probe('camera', calls, () => {
      throw new Error('no camera');
    }),
  ]);
  await tab.bootstrap.ready;

  // Como el panel: escribe el estado y en seguida avisa, sin esperar el aviso de cambio.
  await panel.start(SESSION);
  const reply = await worker.sendToTab(42, worker.types.SESSION_STARTED, {
    session_id: 7,
    mode: 'free',
    study_id: 1,
  });

  assert.deepEqual(plain(reply), { started: ['capture'], failed: ['camera'] });
  // Al iniciar, el módulo ya ve la sesión: el acumulador no descartaría registros.
  assert.equal(tab.calls[1].sessionAtStart.session_id, 7);
});

test('on session.closed stops the modules, flushes the batcher and then replies', async () => {
  const { world, panel, worker } = createExtension();
  await panel.start(SESSION);
  const tab = loadTab(world, 42, (calls) => [probe('capture', calls)]);
  await tab.bootstrap.ready;

  const reply = await worker.sendToTab(42, worker.types.SESSION_CLOSED, { session_id: 7 });

  assert.deepEqual(plain(reply), { flushed: true });
  assert.deepEqual(tab.calls.slice(-2), ['capture.stop', 'flush']);
  assert.equal(tab.modules.isRunning(), false);
});

test('stops the modules when the session is cleared without session.closed', async () => {
  const { world, panel } = createExtension();
  await panel.start(SESSION);
  const tab = loadTab(world, 42, (calls) => [probe('capture', calls)]);
  await tab.bootstrap.ready;

  await panel.clear();
  await settle();

  assert.deepEqual(tab.calls.slice(-2), ['capture.stop', 'flush']);
});

test('gives the modules a frozen context with a read-only session', async () => {
  const { world, panel } = createExtension();
  await panel.start(SESSION);
  let context = null;
  const tab = loadTab(world, 42, (calls) => [
    probe('capture', calls, (ctx) => {
      context = ctx;
    }),
  ]);
  await tab.bootstrap.ready;

  assert.deepEqual(Object.keys(context).sort(), [
    'batcher', 'clock', 'config', 'contracts', 'messages', 'session',
  ]);
  assert.deepEqual(Object.keys(context.session).sort(), ['get', 'subscribe']);
  assert.ok(Object.isFrozen(context));
  assert.equal(context.config, UX.config);
  assert.equal(context.contracts, UX.contracts);
});
