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
const TASKS = [
  {
    id: 7,
    position: 1,
    instruction: 'Busca una camiseta y agrégala al carrito.',
    references: [
      { id: 9, end_condition: { type: 'url_pattern', pattern: '/cart' } },
      { id: 4, end_condition: { type: 'visible_text', text: 'Carrito' } },
    ],
  },
  { id: 8, position: 2, instruction: 'Completa la compra.', references: [] },
];
const FORM = { study_id: 1, participant_id: 'P07', version: 'V0', mode: 'free' };
const types = UX.createMessages({ platform: { onMessage() {} }, messageTypes: enums.message_type }).types;

/**
 * Arma un controlador con sustitutos. `replies` define qué responde cada
 * mensaje (un valor, o un `Error` para rechazar).
 */
function setup({ api = {}, tab = TAB, replies = {} } = {}) {
  const world = createFakeWorld();
  const calls = [];
  const handlers = new Map();
  const clock = { time: 1791380000000, now: () => clock.time };
  const session = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  const controller = UX.createPanelController({
    api: {
      listStudies: async () => STUDIES,
      createSession: async (body) => {
        calls.push({ createSession: body });
        return { session_id: 12, started_at: 1791380123456 };
      },
      listTasks: async (studyId) => {
        calls.push({ listTasks: studyId });
        return TASKS;
      },
      ...api,
    },
    session,
    messages: {
      types,
      on(type, handler) {
        handlers.set(type, handler);
        return () => handlers.delete(type);
      },
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
      add: (type, record) => {
        calls.push({ add: type, record });
        return true;
      },
    },
    clock,
    platform: { activeTab: async () => tab },
    environment: {
      screen: { width: 1920, height: 1080 },
      devicePixelRatio: 1.25,
      chromeVersion: async () => '146.0.7680.153',
    },
  });
  return { world, session, controller, calls, clock, handlers };
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

/** Inicia una sesión guiada y deja el panel con la primera tarea lista. */
async function startGuided(options) {
  const result = setup(options);
  await result.controller.init();
  await result.controller.startSession({ ...FORM, mode: 'guided' });
  return result;
}

test('guided mode loads the tasks of the study and waits for the first one', async () => {
  const { controller, calls } = await startGuided();

  const { guided } = controller.getState();
  assert.deepEqual(calls.filter((call) => call.listTasks !== undefined), [{ listTasks: 1 }]);
  assert.equal(guided.loaded, true);
  assert.deepEqual(guided.tasks, TASKS);
  assert.equal(guided.index, 0);
  assert.equal(guided.current, null);
});

test('free and reference modes do not load tasks', async () => {
  for (const mode of ['free', 'reference']) {
    const { controller, calls } = setup();
    await controller.init();
    await controller.startSession({ ...FORM, mode });

    assert.equal(controller.getState().guided, null);
    assert.equal(calls.some((call) => call.listTasks !== undefined), false);
  }
});

test('starting a task saves it in the session and tells the tab its end condition', async () => {
  const { controller, calls, world, clock } = await startGuided();
  calls.length = 0;
  clock.time = 1791380005000;

  await controller.startTask();

  assert.equal(world.areas.session.get('session').task_id, 7);
  // De las dos referencias confirmadas se usa la de menor id.
  assert.deepEqual(calls, [
    {
      send: 'task.started',
      payload: { task_id: 7, end_condition: { type: 'visible_text', text: 'Carrito' } },
    },
  ]);
  assert.deepEqual(controller.getState().guided.current, { task_id: 7, t_start: 1791380005000 });
});

test('a task without a confirmed reference starts with a null end condition', async () => {
  const { controller, calls } = await startGuided();
  await controller.startTask();
  await controller.endTask('done');
  calls.length = 0;

  await controller.startTask();

  assert.deepEqual(calls, [{ send: 'task.started', payload: { task_id: 8, end_condition: null } }]);
});

test('Terminé records the task with its times and moves to the next one', async () => {
  const { controller, calls, world, clock } = await startGuided();
  clock.time = 1791380005000;
  await controller.startTask();
  clock.time = 1791380042500;
  calls.length = 0;

  await controller.endTask('done');

  assert.deepEqual(calls, [
    {
      add: 'tasks',
      record: { task_id: 7, t_start: 1791380005000, t_end: 1791380042500, ended_by: 'done' },
    },
  ]);
  assert.equal(world.areas.session.get('session').task_id, null);
  const { guided } = controller.getState();
  assert.equal(guided.index, 1);
  assert.equal(guided.current, null);
});

test('No pude records gave_up, and the last task leaves the list finished', async () => {
  const { controller, calls } = await startGuided();
  await controller.startTask();
  await controller.endTask('done');
  await controller.startTask();
  calls.length = 0;

  await controller.endTask('gave_up');

  assert.equal(calls[0].record.task_id, 8);
  assert.equal(calls[0].record.ended_by, 'gave_up');
  const { guided } = controller.getState();
  assert.equal(guided.index, guided.tasks.length);
  // Ya no hay tarea que empezar.
  calls.length = 0;
  await controller.startTask();
  assert.deepEqual(calls, []);
});

test('a second press does not repeat the start or the end of a task', async () => {
  const { controller, calls } = await startGuided();
  calls.length = 0;

  await Promise.all([controller.startTask(), controller.startTask()]);
  assert.equal(calls.filter((call) => call.send === 'task.started').length, 1);

  await Promise.all([controller.endTask('done'), controller.endTask('done')]);
  assert.equal(calls.filter((call) => call.add === 'tasks').length, 1);
});

test('only the buttons can end a task here, not the reference', async () => {
  const { controller } = await startGuided();
  await controller.startTask();

  await assert.rejects(() => controller.endTask('reference'), /cannot end a task/);
  assert.notEqual(controller.getState().guided.current, null);
});

test('starting or ending does nothing without a task to act on', async () => {
  const free = setup();
  await free.controller.init();
  await free.controller.startSession(FORM);
  free.calls.length = 0;
  await free.controller.startTask();
  await free.controller.endTask('done');
  assert.deepEqual(free.calls, []);

  const guided = await startGuided();
  guided.calls.length = 0;
  await guided.controller.endTask('done');
  assert.deepEqual(guided.calls, []);
});

test('a task list that cannot be loaded is reported and can be loaded again', async () => {
  let fail = true;
  const { controller } = await startGuided({
    api: {
      listTasks: async () => {
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return TASKS;
      },
    },
  });
  assert.equal(controller.getState().error.code, 'server_unreachable');
  assert.equal(controller.getState().guided.loaded, false);

  fail = false;
  await controller.retry();

  assert.equal(controller.getState().error, null);
  assert.equal(controller.getState().guided.loaded, true);
});

test('keeps the task going when the tab does not answer task.started', async () => {
  const { controller, session } = await startGuided({
    replies: { [types.TASK_STARTED]: new Error('no receiver') },
  });

  await controller.startTask();

  assert.equal(session.get().task_id, 7);
  assert.notEqual(controller.getState().guided.current, null);
  assert.equal(controller.getState().tabStatus, 'pending');
});

test('reopening the panel in the middle of a task resumes that task', async () => {
  const { controller, world, clock } = setup();
  world.areas.session.set('session', {
    session_id: 12,
    mode: 'guided',
    study_id: 1,
    tab_id: 42,
    task_id: 8,
  });
  clock.time = 1791380090000;

  await controller.init();

  const { guided } = controller.getState();
  assert.equal(guided.index, 1);
  assert.deepEqual(guided.current, { task_id: 8, t_start: 1791380090000 });
});

test('closing the session in the middle of a task does not record that task', async () => {
  const { controller, calls } = await startGuided();
  await controller.startTask();
  calls.length = 0;

  await controller.closeSession();

  assert.equal(calls.some((call) => call.add === 'tasks'), false);
  assert.equal(controller.getState().guided, null);
  assert.equal(controller.getState().phase, 'idle');
});

test('the end of a task is never before its start', async () => {
  const { controller, calls, clock } = await startGuided();
  clock.time = 1791380005000;
  await controller.startTask();
  clock.time = 1791380004000;
  calls.length = 0;

  await controller.endTask('done');

  assert.equal(calls[0].record.t_end, 1791380005000);
});

test('task.completed from the tab ends the task by reference and moves on', async () => {
  const { controller, calls, handlers, clock, world } = await startGuided();
  clock.time = 1791380005000;
  await controller.startTask();
  clock.time = 1791380012000;
  calls.length = 0;

  await handlers.get(types.TASK_COMPLETED)({ task_id: 7, ended_by: 'reference' });

  assert.deepEqual(calls, [
    {
      add: 'tasks',
      record: { task_id: 7, t_start: 1791380005000, t_end: 1791380012000, ended_by: 'reference' },
    },
  ]);
  assert.equal(world.areas.session.get('session').task_id, null);
  assert.equal(controller.getState().guided.index, 1);
});

test('task.completed is ignored for another task, for another end, or when nothing runs', async () => {
  const { controller, calls, handlers } = await startGuided();
  const completed = handlers.get(types.TASK_COMPLETED);
  calls.length = 0;

  await completed({ task_id: 7, ended_by: 'reference' });
  await controller.startTask();
  await completed({ task_id: 8, ended_by: 'reference' });
  await completed({ task_id: 7, ended_by: 'done' });

  assert.equal(calls.some((call) => call.add === 'tasks'), false);
  assert.equal(controller.getState().guided.current.task_id, 7);
});

test('a button press and task.completed together record the task once', async () => {
  const { controller, calls, handlers } = await startGuided();
  await controller.startTask();
  calls.length = 0;

  await Promise.all([
    controller.endTask('done'),
    handlers.get(types.TASK_COMPLETED)({ task_id: 7, ended_by: 'reference' }),
  ]);

  assert.equal(calls.filter((call) => call.add === 'tasks').length, 1);
  assert.equal(controller.getState().guided.index, 1);
});

/** Inicia una sesión libre con el panel listo para recibir mensajes de la cámara. */
async function startFree(options) {
  const result = setup(options);
  await result.controller.init();
  await result.controller.startSession(FORM);
  result.camera = (status) => result.handlers.get(types.CAMERA_STATUS)({ status });
  result.calibrated = (payload) => result.handlers.get(types.CALIBRATION_RESULT)(payload);
  return result;
}

test('shows no camera information until the camera reports', async () => {
  const { controller } = await startFree();

  assert.equal(controller.getState().camera, null);
  assert.deepEqual(controller.getState().calibration, { pending: null, initial: null, final: null });
});

test('follows the camera status and the session goes on without a camera', async () => {
  const { controller, camera, calls } = await startFree();

  for (const status of ['active', 'no_permission', 'error']) {
    camera(status);
    assert.equal(controller.getState().camera, status);
  }
  calls.length = 0;
  await controller.closeSession();
  assert.equal(controller.getState().phase, 'idle');
  assert.equal(calls.some((call) => call.send === 'session.closed'), true);
});

test('requests the initial calibration and shows its result', async () => {
  const { controller, camera, calibrated, calls } = await startFree();
  camera('active');
  calls.length = 0;

  await controller.requestCalibration('initial');
  assert.deepEqual(calls, [{ send: 'calibration.request', payload: { type: 'initial' } }]);
  assert.equal(controller.getState().calibration.pending, 'initial');

  calibrated({ error_px: 112.5, error_deg: 2.8, accepted: true });
  assert.deepEqual(controller.getState().calibration.initial, {
    error_px: 112.5,
    error_deg: 2.8,
    accepted: true,
  });
  assert.equal(controller.getState().calibration.final, null);
});

test('keeps the initial result when the final calibration is requested', async () => {
  const { controller, calibrated } = await startFree();
  await controller.requestCalibration('initial');
  calibrated({ error_px: 90, error_deg: 2.1, accepted: true });

  await controller.requestCalibration('final');
  calibrated({ error_px: 300, error_deg: 7.5, accepted: false });

  const { calibration } = controller.getState();
  assert.equal(calibration.initial.accepted, true);
  assert.deepEqual(calibration.final, { error_px: 300, error_deg: 7.5, accepted: false });
});

test('a repeated calibration replaces the earlier result of its type', async () => {
  const { controller, calibrated } = await startFree();
  await controller.requestCalibration('initial');
  calibrated({ error_px: 400, error_deg: 9, accepted: false });

  calibrated({ error_px: 100, error_deg: 2.5, accepted: true });
  assert.equal(controller.getState().calibration.initial.accepted, true);

  await controller.requestCalibration('initial');
  assert.equal(controller.getState().calibration.initial, null);
});

test('ignores a calibration result that nobody asked for', async () => {
  const { controller, calibrated } = await startFree();

  calibrated({ error_px: 100, error_deg: 2.5, accepted: true });

  assert.deepEqual(controller.getState().calibration, { pending: null, initial: null, final: null });
});

test('does not ask for a calibration when the camera is known not to work', async () => {
  for (const status of ['no_permission', 'error']) {
    const { controller, camera, calls } = await startFree();
    camera(status);
    calls.length = 0;

    await controller.requestCalibration('initial');

    assert.deepEqual(calls, []);
    assert.equal(controller.getState().calibration.pending, null);
  }
});

test('asks for the calibration while the camera has not reported yet', async () => {
  const { controller, calls } = await startFree();
  calls.length = 0;

  await controller.requestCalibration('final');

  assert.equal(calls.length, 1);
});

test('reports a tab that does not answer the calibration and keeps the session', async () => {
  const { controller } = await startFree({
    replies: { [types.CALIBRATION_REQUEST]: new Error('no receiver') },
  });

  await controller.requestCalibration('initial');

  const state = controller.getState();
  assert.equal(state.error.code, 'calibration_unavailable');
  assert.equal(state.calibration.pending, null);
  assert.equal(state.phase, 'active');
});

test('rejects an unknown calibration type and does nothing without a session', async () => {
  const { controller, calls } = setup();
  await controller.init();

  await assert.rejects(() => controller.requestCalibration('middle'), /unknown calibration type/);
  await controller.requestCalibration('initial');

  assert.deepEqual(calls, []);
});

test('closing the session forgets the camera and the calibration', async () => {
  const { controller, camera, calibrated } = await startFree();
  camera('active');
  await controller.requestCalibration('initial');
  calibrated({ error_px: 100, error_deg: 2.5, accepted: true });

  await controller.closeSession();

  const state = controller.getState();
  assert.equal(state.camera, null);
  assert.deepEqual(state.calibration, { pending: null, initial: null, final: null });
});

test('ignores camera messages that arrive while there is no session', async () => {
  const { controller, handlers } = setup();
  await controller.init();

  handlers.get(types.CAMERA_STATUS)({ status: 'active' });

  assert.equal(controller.getState().camera, null);
});
