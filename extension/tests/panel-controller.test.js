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
require('../panel/strings.js');
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
      createReference: async (body) => {
        calls.push({ createReference: body });
        return { reference_id: 31 };
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
    session_id: 12, mode: 'free', study_id: 1, tab_id: 42, recorded_fields: [], task_id: null,
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

test('the session keeps the fields whose text the study records', async () => {
  const fields = [{ name: 'search', selector: '#q' }];
  const { controller, session } = setup({
    api: { listStudies: async () => [{ ...STUDIES[0], recorded_fields: fields }] },
  });
  await controller.init();

  await controller.startSession(FORM);

  assert.deepEqual(session.get().recorded_fields, fields);
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

test('the free mode does not load tasks', async () => {
  const { controller, calls } = setup();
  await controller.init();
  await controller.startSession(FORM);

  assert.equal(controller.getState().guided, null);
  assert.equal(controller.getState().reference, null);
  assert.equal(calls.some((call) => call.listTasks !== undefined), false);
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

test('the free session remembers when it started, and forgets it on close', async () => {
  const { controller, clock } = setup();
  await controller.init();
  assert.equal(controller.getState().startedAt, null);
  clock.time = 1791380100000;

  await controller.startSession(FORM);
  assert.equal(controller.getState().startedAt, 1791380100000);

  await controller.closeSession();
  assert.equal(controller.getState().startedAt, null);
});

test('does not know when a session started if the panel opens during it', async () => {
  const { controller, world } = setup();
  world.areas.session.set('session', {
    session_id: 12,
    mode: 'free',
    study_id: 1,
    tab_id: 42,
    task_id: null,
  });

  await controller.init();

  assert.equal(controller.getState().phase, 'active');
  assert.equal(controller.getState().startedAt, null);
});

test('what the panel still holds is sent before the session is closed', async () => {
  const { controller, calls } = await startGuided();
  await controller.startTask();
  calls.length = 0;
  await controller.endTask('done');

  await controller.closeSession();

  assert.deepEqual(
    calls.map((call) => (typeof call === 'string' ? call : call.add || call.send)),
    ['tasks', 'flush', 'session.closed'],
  );
});

test('formats the elapsed time as mm:ss and h:mm:ss', () => {
  const { elapsedTime } = UX.strings;

  assert.equal(elapsedTime(0), '00:00');
  assert.equal(elapsedTime(999), '00:00');
  assert.equal(elapsedTime(65000), '01:05');
  assert.equal(elapsedTime(59 * 60000 + 59999), '59:59');
  assert.equal(elapsedTime(3600000), '1:00:00');
  assert.equal(elapsedTime(3723000), '1:02:03');
  assert.equal(elapsedTime(-500), '00:00');
});

/** Inicia una sesión de referencia con las tareas cargadas. */
async function startReference(options) {
  const result = setup(options);
  await result.controller.init();
  await result.controller.startSession({ ...FORM, mode: 'reference' });
  return result;
}

test('reference mode loads the tasks of the study and records nothing yet', async () => {
  const { controller, calls } = await startReference();

  const { reference, guided } = controller.getState();
  assert.equal(guided, null);
  assert.deepEqual(calls.filter((call) => call.listTasks !== undefined), [{ listTasks: 1 }]);
  assert.equal(reference.loaded, true);
  assert.deepEqual(reference.tasks, TASKS);
  assert.equal(reference.recording, null);
  assert.deepEqual(reference.saved, []);
});

test('starting a recording marks the task in the session and tells the tab without an end condition', async () => {
  const { controller, calls, world, clock } = await startReference();
  calls.length = 0;
  clock.time = 1791380005000;

  await controller.startRecording(8);

  assert.equal(world.areas.session.get('session').task_id, 8);
  assert.deepEqual(calls, [{ send: 'task.started', payload: { task_id: 8, end_condition: null } }]);
  assert.deepEqual(controller.getState().reference.recording, { task_id: 8, t_start: 1791380005000 });
});

test('stopping saves the task record, flushes, and only then creates the draft reference', async () => {
  const { controller, calls, world, clock } = await startReference();
  clock.time = 1791380005000;
  await controller.startRecording(7);
  clock.time = 1791380047000;
  calls.length = 0;

  await controller.stopRecording();

  assert.deepEqual(calls, [
    {
      add: 'tasks',
      record: { task_id: 7, t_start: 1791380005000, t_end: 1791380047000, ended_by: 'done' },
    },
    'flush',
    { createReference: { task_id: 7, source_session_id: 12 } },
  ]);
  assert.equal(world.areas.session.get('session').task_id, null);
  const state = controller.getState();
  assert.equal(state.reference.recording, null);
  assert.equal(state.reference.unsaved, null);
  assert.deepEqual(state.reference.saved, [{ task_id: 7, reference_id: 31 }]);
  assert.deepEqual(state.notice, { code: 'reference_saved', task_id: 7, reference_id: 31 });
});

test('a task already saved in this session cannot be recorded again', async () => {
  const { controller, calls } = await startReference();
  await controller.startRecording(7);
  await controller.stopRecording();
  calls.length = 0;

  await controller.startRecording(7);

  assert.deepEqual(calls, []);
  assert.equal(controller.getState().reference.recording, null);
  // Otra tarea sí.
  await controller.startRecording(8);
  assert.equal(controller.getState().reference.recording.task_id, 8);
});

test('only one task is recorded at a time, and unknown tasks are ignored', async () => {
  const { controller, calls } = await startReference();
  await controller.startRecording(7);
  calls.length = 0;

  await controller.startRecording(8);
  assert.deepEqual(calls, []);
  assert.equal(controller.getState().reference.recording.task_id, 7);

  await controller.stopRecording();
  await controller.startRecording(999);
  assert.equal(controller.getState().reference.recording, null);
});

test('a second press does not repeat the start, the record or the reference', async () => {
  const { controller, calls } = await startReference();
  calls.length = 0;

  await Promise.all([controller.startRecording(7), controller.startRecording(7)]);
  assert.equal(calls.filter((call) => call.send === 'task.started').length, 1);

  await Promise.all([controller.stopRecording(), controller.stopRecording()]);
  assert.equal(calls.filter((call) => call.add === 'tasks').length, 1);
  assert.equal(calls.filter((call) => call.createReference !== undefined).length, 1);
});

test('a reference that could not be saved is kept for a retry', async () => {
  let fail = true;
  const { controller, calls } = await startReference({
    api: {
      createReference: async (body) => {
        calls.push({ createReference: body });
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return { reference_id: 40 };
      },
    },
  });
  await controller.startRecording(7);

  await controller.stopRecording();

  let state = controller.getState();
  assert.equal(state.error.code, 'server_unreachable');
  assert.equal(state.reference.unsaved, 7);
  assert.deepEqual(state.reference.saved, []);
  // Mientras espera el reintento no se graba otra tarea.
  await controller.startRecording(8);
  assert.equal(controller.getState().reference.recording, null);

  fail = false;
  calls.length = 0;
  await controller.retrySave();

  state = controller.getState();
  assert.equal(state.error, null);
  assert.equal(state.reference.unsaved, null);
  assert.deepEqual(state.reference.saved, [{ task_id: 7, reference_id: 40 }]);
  // El registro de la tarea ya salió: el reintento solo repite el guardado.
  assert.equal(calls.some((call) => call.add === 'tasks'), false);
});

test('retrying does nothing when no recording is waiting to be saved', async () => {
  const { controller, calls } = await startReference();
  calls.length = 0;

  await controller.retrySave();

  assert.deepEqual(calls, []);
});

test('the server refusing the reference is reported with its fields', async () => {
  const { controller } = await startReference({
    api: {
      createReference: async () => {
        throw new UX.ApiError({
          status: 422,
          detail: 'task of another study',
          errors: [{ record: null, field: 'task_id', message: 'does not belong' }],
        });
      },
    },
  });
  await controller.startRecording(7);

  await controller.stopRecording();

  assert.equal(controller.getState().error.code, 'invalid_request');
  assert.equal(controller.getState().reference.unsaved, 7);
});

test('stopping or retrying does nothing without a recording or outside reference mode', async () => {
  const guided = await startGuided();
  guided.calls.length = 0;
  await guided.controller.stopRecording();
  await guided.controller.startRecording(7);
  await guided.controller.retrySave();
  assert.deepEqual(guided.calls, []);

  const reference = await startReference();
  reference.calls.length = 0;
  await reference.controller.stopRecording();
  assert.deepEqual(reference.calls, []);
});

test('the guided buttons and the reference recording do not mix', async () => {
  const reference = await startReference();
  reference.calls.length = 0;
  await reference.controller.startTask();
  await reference.controller.endTask('done');
  assert.deepEqual(reference.calls, []);

  const guided = await startGuided();
  guided.calls.length = 0;
  await guided.controller.startRecording(7);
  assert.deepEqual(guided.calls, []);
});

test('a task list that cannot be loaded in reference mode can be loaded again', async () => {
  let fail = true;
  const { controller } = await startReference({
    api: {
      listTasks: async () => {
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return TASKS;
      },
    },
  });
  assert.equal(controller.getState().reference.loaded, false);

  fail = false;
  await controller.retry();

  assert.equal(controller.getState().reference.loaded, true);
  assert.equal(controller.getState().error, null);
});

test('reopening the panel in the middle of a recording resumes it', async () => {
  const { controller, world, clock } = setup();
  world.areas.session.set('session', {
    session_id: 12,
    mode: 'reference',
    study_id: 1,
    tab_id: 42,
    task_id: 8,
  });
  clock.time = 1791380090000;

  await controller.init();

  assert.deepEqual(controller.getState().reference.recording, { task_id: 8, t_start: 1791380090000 });
});

test('closing the session while recording saves no reference', async () => {
  const { controller, calls } = await startReference();
  await controller.startRecording(7);
  calls.length = 0;

  await controller.closeSession();

  assert.equal(calls.some((call) => call.createReference !== undefined), false);
  assert.equal(calls.some((call) => call.add === 'tasks'), false);
  assert.equal(controller.getState().reference, null);
});

test('two retries at once save the reference only once', async () => {
  let fail = true;
  const { controller, calls } = await startReference({
    api: {
      createReference: async (body) => {
        calls.push({ createReference: body });
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return { reference_id: 40 };
      },
    },
  });
  await controller.startRecording(7);
  await controller.stopRecording();
  fail = false;
  calls.length = 0;

  await Promise.all([controller.retrySave(), controller.retrySave()]);

  assert.equal(calls.filter((call) => call.createReference !== undefined).length, 1);
  assert.deepEqual(controller.getState().reference.saved, [{ task_id: 7, reference_id: 40 }]);
});

const CAPTURED = { capture_id: 5, file_path: 'captures/1/a.png' };

test('capturing sends the screen of the evaluated tab and remembers the capture', async () => {
  const { controller, calls } = await startReference({ replies: { 'screen_capture.request': CAPTURED } });
  calls.length = 0;

  await controller.captureScreen();

  assert.deepEqual(calls, [
    {
      send: 'screen_capture.request',
      payload: { study_id: 1, screen: { url: TAB.url, title: TAB.title } },
    },
  ]);
  const { reference, notice, error } = controller.getState();
  assert.deepEqual(reference.captures, [{ capture_id: 5, url: TAB.url }]);
  assert.equal(reference.capturing, false);
  assert.deepEqual(notice, { code: 'capture_saved', capture_id: 5 });
  assert.equal(error, null);
});

test('the url of a capture loses credentials and sensitive values, and its title', async () => {
  const cases = [
    ['https://user:CANARIO@shop.local/x?token=CANARIO&view=cart', 'https://shop.local/x?token=redacted&view=cart'],
    ['https://shop.local/buscar?q=CANARIO&page=2', 'https://shop.local/buscar?q=redacted&page=2'],
    ['https://shop.local/cb#access_token=CANARIO&state=ok', 'https://shop.local/cb#access_token=redacted&state=ok'],
    ['https://shop.local/#/buscar?q=CANARIO&page=2', 'https://shop.local/#/buscar?q=redacted&page=2'],
    ['https://shop.local/?%71=CANARIO', 'https://shop.local/?%71=redacted'],
  ];
  for (const [url, expected] of cases) {
    const { controller, calls } = await startReference({
      tab: { ...TAB, url, title: 'Resultados de CANARIO' },
      replies: { 'screen_capture.request': CAPTURED },
    });
    calls.length = 0;

    await controller.captureScreen();

    assert.deepEqual(calls[0].payload.screen, { url: expected, title: '' }, url);
  }
  // Sin nada que tachar, el título se conserva.
  const { controller, calls } = await startReference({
    tab: { ...TAB, url: 'https://shop.local/cart', title: 'Carrito' },
    replies: { 'screen_capture.request': CAPTURED },
  });
  calls.length = 0;
  await controller.captureScreen();
  assert.deepEqual(calls[0].payload.screen, { url: 'https://shop.local/cart', title: 'Carrito' });
});

test('a tab without title sends an empty one', async () => {
  const { controller, calls } = await startReference({
    tab: { ...TAB, title: undefined },
    replies: { 'screen_capture.request': CAPTURED },
  });
  calls.length = 0;

  await controller.captureScreen();

  assert.equal(calls[0].payload.screen.title, '');
});

test('nothing is captured when the active tab is not the evaluated web page', async () => {
  for (const change of [{ id: 99 }, { url: 'chrome://extensions/' }, { url: undefined }]) {
    // La sesión empieza en la pestaña evaluada y después el evaluador cambia de pestaña.
    const tab = { ...TAB };
    const { controller, calls } = await startReference({ tab });
    Object.assign(tab, change);
    calls.length = 0;

    await controller.captureScreen();

    assert.deepEqual(calls, []);
    const state = controller.getState();
    assert.equal(state.error.code, 'capture_wrong_tab');
    assert.equal(state.reference.capturing, false);
    assert.deepEqual(state.reference.captures, []);
  }
});

test('a capture the worker could not save is reported and can be repeated', async () => {
  const replies = { 'screen_capture.request': new Error('server unreachable') };
  const { controller } = await startReference({ replies });
  await controller.captureScreen();

  let state = controller.getState();
  assert.deepEqual(state.error, { code: 'capture_failed', fields: [], detail: 'server unreachable' });
  assert.equal(state.reference.capturing, false);
  assert.deepEqual(state.reference.captures, []);
  assert.equal(state.notice, null);

  replies['screen_capture.request'] = CAPTURED;
  await controller.captureScreen();
  state = controller.getState();
  assert.equal(state.error, null);
  assert.equal(state.reference.captures.length, 1);
});

test('a second press while capturing does not send another capture', async () => {
  const { controller, calls } = await startReference({ replies: { 'screen_capture.request': CAPTURED } });
  calls.length = 0;

  await Promise.all([controller.captureScreen(), controller.captureScreen()]);

  assert.equal(calls.filter((call) => call.send === 'screen_capture.request').length, 1);
  assert.equal(controller.getState().reference.captures.length, 1);
});

test('capturing is only for reference sessions', async () => {
  const free = setup({ replies: { 'screen_capture.request': CAPTURED } });
  await free.controller.init();
  await free.controller.startSession(FORM);
  const guided = await startGuided({ replies: { 'screen_capture.request': CAPTURED } });
  const idle = setup();
  await idle.controller.init();

  for (const { controller, calls } of [free, guided, idle]) {
    calls.length = 0;
    await controller.captureScreen();
    assert.equal(calls.some((call) => call.send === 'screen_capture.request'), false);
  }
});

test('capturing does not disturb a recording in progress', async () => {
  const { controller } = await startReference({ replies: { 'screen_capture.request': CAPTURED } });
  await controller.startRecording(7);

  await controller.captureScreen();

  const { reference } = controller.getState();
  assert.equal(reference.recording.task_id, 7);
  assert.equal(reference.captures.length, 1);
});

test('closing the session while a capture is pending leaves a clean idle state', async () => {
  let release;
  const { controller } = await startReference({
    replies: {
      'screen_capture.request': new Promise((resolve) => {
        release = resolve;
      }),
    },
  });
  const pending = controller.captureScreen();
  await controller.closeSession();
  release(CAPTURED);
  await pending;

  assert.equal(controller.getState().reference, null);
  assert.equal(controller.getState().notice.code, 'session_closed');
});

/** Inicia una sesión guiada y termina todas sus tareas, para que aparezca el SUS. */
async function startFinishedGuided(options) {
  const result = await startGuided(options);
  for (const task of TASKS) {
    await result.controller.startTask();
    await result.controller.endTask('done');
  }
  return result;
}

const SUS_ANSWERS = [4, 2, 5, 1, 4, 2, 5, 1, 4, 2];

/** Contesta las 10 preguntas con `answers`. */
function answerAll(controller, answers = SUS_ANSWERS) {
  answers.forEach((value, index) => controller.answerSus(index + 1, value));
}

test('the SUS questions and instructions are the validated Spanish text, word for word', () => {
  assert.deepEqual(UX.strings.susQuestions, [
    'Me gustaría usar esta herramienta frecuentemente.',
    'Considero que esta herramienta es innecesariamente compleja',
    'Considero que la herramienta es fácil de usar.',
    'Considero necesario el apoyo de personal experto para poder utilizar esta herramienta',
    'Considero que las funciones de la herramienta están bien integradas',
    'Considero que la herramienta presenta muchas contradicciones',
    'Imagino que la mayoría de las personas aprenderían a usar esta herramienta rápidamente',
    'Considero que el uso de esta herramienta es tedioso',
    'Me sentí muy confiado al usar la herramienta',
    'Necesité saber bastantes cosas antes de poder empezar a usar esta herramienta',
  ]);
  assert.equal(
    UX.strings.susInstructions,
    'Por favor seleccione de cada uno de los enunciados la opción que mejor describa su experiencia con la herramienta electrónica. Un puntaje de 1 significa que usted se encuentra totalmente en desacuerdo con el enunciado, mientras que un puntaje en 5 significa que está totalmente de acuerdo, un puntaje de 3 significaría que usted se encuentra neutral con el enunciado.',
  );
});

test('the SUS starts empty with the guided session and is not answerable before the tasks end', async () => {
  const { controller } = await startGuided();

  assert.deepEqual(controller.getState().guided.sus, {
    answers: Array(10).fill(null),
    saving: false,
    saved: false,
  });
  answerAll(controller);
  assert.deepEqual(controller.getState().guided.sus.answers, Array(10).fill(null));

  await controller.startTask();
  await controller.endTask('done');
  controller.answerSus(1, 5);
  assert.equal(controller.getState().guided.sus.answers[0], null);
});

test('a study without tasks has no SUS to answer', async () => {
  const { controller } = await startGuided({ api: { listTasks: async () => [] } });

  controller.answerSus(1, 5);

  assert.equal(controller.getState().guided.sus.answers[0], null);
});

test('after the last task the answers are stored one by one and can be changed', async () => {
  const { controller } = await startFinishedGuided();

  controller.answerSus(3, 5);
  controller.answerSus(10, 1);
  controller.answerSus(3, 2);

  const { answers } = controller.getState().guided.sus;
  assert.equal(answers[2], 2);
  assert.equal(answers[9], 1);
  assert.equal(answers.filter((answer) => answer !== null).length, 2);
});

test('answers outside the contract are ignored', async () => {
  const { controller } = await startFinishedGuided();

  for (const [item, value] of [[1, 0], [1, 6], [1, 2.5], [1, '3'], [1, NaN], [0, 3], [11, 3], [1.5, 3], ['1', 3]]) {
    controller.answerSus(item, value);
  }

  assert.deepEqual(controller.getState().guided.sus.answers, Array(10).fill(null));
});

test('the SUS is only sent with the ten answers, in order, to the session', async () => {
  const { controller, calls } = await startFinishedGuided({
    api: {
      saveSus: async (sessionId, body) => {
        calls.push({ saveSus: sessionId, body });
        return { score: 80 };
      },
    },
  });
  calls.length = 0;
  for (let item = 1; item <= 9; item += 1) {
    controller.answerSus(item, SUS_ANSWERS[item - 1]);
  }

  await controller.submitSus();
  assert.deepEqual(calls, []);

  controller.answerSus(10, SUS_ANSWERS[9]);
  await controller.submitSus();

  assert.deepEqual(calls, [{ saveSus: 12, body: { answers: SUS_ANSWERS } }]);
  const { sus } = controller.getState().guided;
  assert.equal(sus.saved, true);
  assert.equal(sus.saving, false);
  assert.equal(controller.getState().error, null);
});

test('a second press does not send the SUS twice', async () => {
  const { controller, calls } = await startFinishedGuided({
    api: {
      saveSus: async (sessionId, body) => {
        calls.push({ saveSus: sessionId, body });
        return { score: 80 };
      },
    },
  });
  answerAll(controller);
  calls.length = 0;

  await Promise.all([controller.submitSus(), controller.submitSus()]);

  assert.equal(calls.filter((call) => call.saveSus !== undefined).length, 1);
});

test('answers cannot change while sending or once saved, and nothing is sent again', async () => {
  const { controller, calls } = await startFinishedGuided({
    api: {
      saveSus: async (sessionId, body) => {
        calls.push({ saveSus: sessionId, body });
        return { score: 80 };
      },
    },
  });
  answerAll(controller);
  const sending = controller.submitSus();
  controller.answerSus(1, 1);
  await sending;
  controller.answerSus(1, 1);
  await controller.submitSus();

  assert.deepEqual(controller.getState().guided.sus.answers, SUS_ANSWERS);
  assert.equal(calls.filter((call) => call.saveSus !== undefined).length, 1);
});

test('a SUS that could not be sent keeps the answers and can be sent again', async () => {
  let fail = true;
  const { controller, calls } = await startFinishedGuided({
    api: {
      saveSus: async (sessionId, body) => {
        calls.push({ saveSus: sessionId, body });
        if (fail) {
          throw new UX.ApiError({ status: 0, detail: 'server unreachable', errors: [] });
        }
        return { score: 80 };
      },
    },
  });
  answerAll(controller);

  await controller.submitSus();

  let state = controller.getState();
  assert.equal(state.error.code, 'server_unreachable');
  assert.deepEqual(state.guided.sus, { answers: SUS_ANSWERS, saving: false, saved: false });

  fail = false;
  await controller.submitSus();

  state = controller.getState();
  assert.equal(state.error, null);
  assert.equal(state.guided.sus.saved, true);
  assert.equal(calls.filter((call) => call.saveSus !== undefined).length, 2);
});

test('the server refusing the SUS is reported and the answers are kept', async () => {
  const { controller } = await startFinishedGuided({
    api: {
      saveSus: async () => {
        throw new UX.ApiError({ status: 409, detail: 'session is closed', errors: [] });
      },
    },
  });
  answerAll(controller);

  await controller.submitSus();

  assert.equal(controller.getState().error.code, 'unexpected');
  assert.equal(controller.getState().guided.sus.saved, false);
  assert.deepEqual(controller.getState().guided.sus.answers, SUS_ANSWERS);
});

test('the SUS belongs to guided sessions only', async () => {
  const free = setup();
  await free.controller.init();
  await free.controller.startSession(FORM);
  const reference = await startReference();

  for (const { controller, calls } of [free, reference]) {
    calls.length = 0;
    answerAll(controller);
    await controller.submitSus();
    assert.deepEqual(calls, []);
  }
});

test('closing the session while the SUS is being sent leaves a clean idle state', async () => {
  let release;
  const { controller } = await startFinishedGuided({
    api: {
      saveSus: () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    },
  });
  answerAll(controller);
  const pending = controller.submitSus();
  await controller.closeSession();
  release({ score: 80 });
  await pending;

  assert.equal(controller.getState().guided, null);
  assert.equal(controller.getState().notice.code, 'session_closed');
});

test('the session can be closed without answering the SUS', async () => {
  const { controller, calls } = await startFinishedGuided();
  calls.length = 0;

  await controller.closeSession();

  assert.equal(controller.getState().phase, 'idle');
  assert.equal(calls.some((call) => call.saveSus !== undefined), false);
});
