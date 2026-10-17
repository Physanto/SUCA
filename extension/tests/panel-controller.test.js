/**
 * @file Pruebas de la lógica del panel lateral (`panel/controller.js`):
 * estudios, inicio y cierre de la sesión, sin DOM.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/messages.js');
require('../common/session.js');
require('../common/api.js');
require('../panel/controller.js');
const { createFakeWorld, settle } = require('./fakes.js');

const { UX } = globalThis;
const { enums } = UX.contracts;
const STUDIES = [{ id: 1, name: 'Tienda de ejemplo', system_under_test: 'App', description: null }];
const TAB = { id: 42, url: 'http://127.0.0.1:8766/', title: 'Página de prueba', width: 1200, height: 700 };
const FORM = { study_id: 1, participant_id: 'P07', version: 'V0', mode: 'free' };
const types = UX.createMessages({ platform: { onMessage() {} }, messageTypes: enums.message_type }).types;

/**
 * Arma un controlador con sustitutos. `replies` define qué responde cada
 * mensaje (un valor, o un `Error` para rechazar).
 */
function setup({ api = {}, tab = TAB, replies = {} } = {}) {
  const world = createFakeWorld();
  const calls = [];
  const session = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  const controller = UX.createPanelController({
    api: {
      listStudies: async () => STUDIES,
      createSession: async (body) => {
        calls.push({ createSession: body });
        return { session_id: 12, started_at: 1791380123456 };
      },
      ...api,
    },
    session,
    messages: {
      types,
      async send(type, payload) {
        calls.push({ send: type, payload });
        const reply = replies[type];
        if (reply instanceof Error) {
          throw reply;
        }
        return reply;
      },
    },
    batcher: {
      flush: async () => {
        calls.push('flush');
        return true;
      },
    },
    platform: { activeTab: async () => tab },
    environment: {
      screen: { width: 1920, height: 1080 },
      devicePixelRatio: 1.25,
      chromeVersion: async () => '146.0.7680.153',
    },
  });
  return { world, session, controller, calls };
}

test('loads the studies and waits for a new session', async () => {
  const { controller } = setup();

  await controller.init();

  assert.equal(controller.getState().phase, 'idle');
  assert.deepEqual(controller.getState().studies, STUDIES);
  assert.equal(controller.getState().error, null);
});

test('reports an unreachable server and can try again', async () => {
  let fail = true;
  const { controller } = setup({
    api: {
      listStudies: async () => {
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return STUDIES;
      },
    },
  });

  await controller.init();
  assert.equal(controller.getState().error.code, 'server_unreachable');

  fail = false;
  await controller.loadStudies();
  assert.equal(controller.getState().error, null);
  assert.deepEqual(controller.getState().studies, STUDIES);
});

test('does not start on a tab that cannot be evaluated', async () => {
  const { controller, calls, session } = setup({ tab: { ...TAB, url: 'chrome://newtab/' } });
  await controller.init();

  await controller.startSession(FORM);

  assert.equal(controller.getState().phase, 'idle');
  assert.equal(controller.getState().error.code, 'tab_not_evaluable');
  assert.deepEqual(calls, []);
  assert.equal(session.get(), null);
});

test('creates the session for the active tab, saves the state and tells the tab', async () => {
  const { controller, calls, world } = setup({
    replies: { [types.SESSION_STARTED]: { started: ['capture', 'camera'], failed: ['camera'] } },
  });
  await controller.init();

  await controller.startSession(FORM);

  assert.deepEqual(calls[0].createSession, {
    ...FORM,
    screen_info: {
      window_width: 1200,
      window_height: 700,
      screen_width: 1920,
      screen_height: 1080,
      device_pixel_ratio: 1.25,
      chrome_version: '146.0.7680.153',
    },
  });
  assert.deepEqual(world.areas.session.get('session'), {
    session_id: 12, mode: 'free', study_id: 1, tab_id: 42, task_id: null,
  });
  assert.deepEqual(calls[1], {
    send: 'session.started',
    payload: { session_id: 12, mode: 'free', study_id: 1 },
  });
  const state = controller.getState();
  assert.equal(state.phase, 'active');
  assert.equal(state.tabStatus, 'capturing');
  assert.deepEqual(state.failedModules, ['camera']);
  assert.deepEqual(state.tab, { title: 'Página de prueba', url: 'http://127.0.0.1:8766/' });
});

test('keeps the session active when the tab does not answer yet', async () => {
  const { controller } = setup({
    replies: { [types.SESSION_STARTED]: new Error('Receiving end does not exist.') },
  });
  await controller.init();

  await controller.startSession(FORM);

  assert.equal(controller.getState().phase, 'active');
  assert.equal(controller.getState().tabStatus, 'pending');
});

test('does not report capture when nobody confirms the start', async () => {
  const { controller } = setup({ replies: { [types.SESSION_STARTED]: undefined } });
  await controller.init();

  await controller.startSession(FORM);

  assert.equal(controller.getState().tabStatus, 'pending');
});

test('shows the fields that the server rejected and starts nothing', async () => {
  const { controller, session } = setup({
    api: {
      createSession: async () => {
        throw new UX.ApiError({
          status: 422,
          detail: 'session request does not match its contract',
          errors: [{ record: null, field: 'participant_id', message: 'does not match' }],
        });
      },
    },
  });
  await controller.init();

  await controller.startSession({ ...FORM, participant_id: 'Ana María' });

  assert.equal(controller.getState().phase, 'idle');
  assert.equal(controller.getState().error.code, 'invalid_request');
  assert.deepEqual(controller.getState().error.fields, ['participant_id']);
  assert.equal(session.get(), null);
});

test('closes in order: flush its batcher, send session.closed, clear the state', async () => {
  const { controller, calls, session } = setup({
    replies: { [types.SESSION_CLOSED]: { closing: true } },
  });
  await controller.init();
  await controller.startSession(FORM);
  calls.length = 0;

  await controller.closeSession();

  assert.deepEqual(calls, ['flush', { send: 'session.closed', payload: { session_id: 12 } }]);
  assert.equal(session.get(), null);
  assert.equal(controller.getState().phase, 'idle');
  assert.deepEqual(controller.getState().notice, { code: 'session_closed', session_id: 12 });
});

test('keeps the session active if the close could not be sent', async () => {
  const { controller, session } = setup({
    replies: { [types.SESSION_CLOSED]: new Error('worker unavailable') },
  });
  await controller.init();
  await controller.startSession(FORM);

  await controller.closeSession();

  assert.equal(controller.getState().phase, 'active');
  assert.equal(controller.getState().error.code, 'unexpected');
  assert.notEqual(session.get(), null);
});

test('shows the session in progress when the panel opens during one', async () => {
  const { controller, world } = setup();
  const other = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  await other.start({ session_id: 5, mode: 'guided', study_id: 1, tab_id: 42 });

  await controller.init();

  assert.equal(controller.getState().phase, 'active');
  assert.equal(controller.getState().session.session_id, 5);
  assert.equal(controller.getState().tabStatus, 'unknown');
});

test('follows a session that another panel closes', async () => {
  const { controller, world } = setup();
  const other = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  await other.start({ session_id: 5, mode: 'free', study_id: 1, tab_id: 42 });
  await controller.init();

  await other.clear();
  await settle();

  assert.equal(controller.getState().phase, 'idle');
  assert.equal(controller.getState().session, null);
});
