/**
 * @file Prueba de punta a punta del panel lateral: una sesión guiada completa y una
 * sesión de referencia, con las piezas reales (`UX.createPanelController`, `UX.session`
 * y `UX.batcher`) y solo el servidor, el worker y la pestaña simulados. Comprueba el
 * orden de todo lo que sale: mensajes, lotes y llamadas al servidor.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../config.generated.js');
require('../common/messages.js');
require('../common/session.js');
require('../common/batcher.js');
require('../common/api.js');
require('../panel/controller.js');
require('../panel/strings.js');
const { createFakeWorld, createFakeTimers } = require('./fakes.js');

const { UX } = globalThis;
const { enums } = UX.contracts;
const TAB = { id: 42, url: 'http://127.0.0.1:8766/', title: 'Página de prueba', width: 1200, height: 700 };
const STUDIES = [{ id: 1, name: 'Tienda de ejemplo', system_under_test: 'App', description: null }];
const CONDITION = { type: 'url_pattern', pattern: '/second-page.html' };
const TASKS = [
  { id: 1, position: 1, instruction: 'Abre la segunda página.', references: [{ id: 1, end_condition: CONDITION }] },
  { id: 2, position: 2, instruction: 'Busca el teclado.', references: [] },
  { id: 3, position: 3, instruction: 'Completa la compra.', references: [] },
];
const FORM = { study_id: 1, participant_id: 'P40', version: 'V0' };
const T0 = 1791380000000;
const SUS_ANSWERS = [4, 2, 5, 1, 4, 2, 5, 1, 4, 2];

/**
 * Arma el panel con sus piezas reales. `log` guarda, en orden, todo lo que sale hacia
 * el worker, la pestaña y el servidor.
 */
function compose({ camera } = {}) {
  const world = createFakeWorld();
  const log = [];
  const handlers = new Map();
  const clock = { time: T0, now: () => clock.time };
  const messageTypes = enums.message_type;
  const session = UX.createSession({ platform: world.platform(), modes: enums.session_mode });
  const messages = {
    types: UX.createMessages({ platform: { onMessage() {} }, messageTypes }).types,
    on(type, handler) {
      handlers.set(type, handler);
      return () => handlers.delete(type);
    },
    async send(type, payload) {
      log.push({ message: type, payload });
      return type === 'screen_capture.request' ? { capture_id: 5, file_path: 'captures/1/a.png' } : undefined;
    },
  };
  const batcher = UX.createBatcher({
    messages,
    session,
    sending: { interval_ms: 2000, max_batch_records: 500 },
    batchTypes: enums.batch_type,
    timers: createFakeTimers(),
    onPageHide() {},
  });
  const api = {
    listStudies: async () => STUDIES,
    createSession: async (body) => {
      log.push({ api: 'createSession', body });
      return { session_id: 12, started_at: T0 };
    },
    listTasks: async () => TASKS,
    saveSus: async (sessionId, body) => {
      log.push({ api: 'saveSus', sessionId, body });
      return { score: 80 };
    },
    createReference: async (body) => {
      log.push({ api: 'createReference', body });
      return { reference_id: 31 };
    },
  };
  const controller = UX.createPanelController({
    api,
    session,
    messages,
    batcher,
    clock,
    platform: { activeTab: async () => TAB },
    environment: { screen: { width: 1920, height: 1080 }, devicePixelRatio: 1, chromeVersion: async () => '146.0.0.0' },
    camera,
  });
  return { controller, batcher, log, handlers, clock, world };
}

/** Lo que salió, en orden y sin los detalles de cada registro: para ver la secuencia. */
function sequence(log) {
  return log.map((entry) =>
    entry.api ? `api:${entry.api}` : entry.message === 'batch' ? `batch:${entry.payload.type}` : entry.message,
  );
}

/** Lotes de un tipo que salieron hacia el worker. */
function batches(log, type) {
  return log.filter((entry) => entry.message === 'batch' && entry.payload.type === type);
}

test('a complete guided session records the start and end of each task, how it ended and the SUS', async () => {
  const { controller, log, handlers, clock, world } = await (async () => {
    const parts = compose();
    await parts.controller.init();
    return parts;
  })();

  // Inicio.
  await controller.startSession({ ...FORM, mode: 'guided' });
  assert.deepEqual(world.areas.session.get('session'), {
    session_id: 12,
    mode: 'guided',
    study_id: 1,
    tab_id: 42,
    recorded_fields: [],
    task_id: null,
  });

  // Tarea 1: la termina la pestaña al cumplirse la condición de su referencia.
  clock.time = T0 + 1000;
  await controller.startTask();
  assert.equal(world.areas.session.get('session').task_id, 1);
  clock.time = T0 + 6000;
  await handlers.get('task.completed')({ task_id: 1, ended_by: 'reference' });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(world.areas.session.get('session').task_id, null);

  // Tarea 2: termina con el botón; tarea 3: el participante se rinde.
  clock.time = T0 + 7000;
  await controller.startTask();
  clock.time = T0 + 12000;
  await controller.endTask('done');
  clock.time = T0 + 13000;
  await controller.startTask();
  clock.time = T0 + 20000;
  await controller.endTask('gave_up');

  // SUS y cierre.
  assert.equal(controller.getState().guided.index, TASKS.length);
  SUS_ANSWERS.forEach((value, index) => controller.answerSus(index + 1, value));
  await controller.submitSus();
  await controller.closeSession();

  assert.deepEqual(sequence(log), [
    'api:createSession',
    'session.started',
    'task.started',
    'task.started',
    'task.started',
    'api:saveSus',
    'batch:tasks',
    'session.closed',
  ]);
  assert.deepEqual(log.filter((entry) => entry.message === 'task.started').map((entry) => entry.payload), [
    { task_id: 1, end_condition: CONDITION },
    { task_id: 2, end_condition: null },
    { task_id: 3, end_condition: null },
  ]);
  assert.deepEqual(log.find((entry) => entry.api === 'saveSus'), {
    api: 'saveSus',
    sessionId: 12,
    body: { answers: SUS_ANSWERS },
  });
  const [tasks] = batches(log, 'tasks');
  assert.equal(tasks.payload.session_id, 12);
  assert.deepEqual(tasks.payload.records, [
    { task_id: 1, t_start: T0 + 1000, t_end: T0 + 6000, ended_by: 'reference' },
    { task_id: 2, t_start: T0 + 7000, t_end: T0 + 12000, ended_by: 'done' },
    { task_id: 3, t_start: T0 + 13000, t_end: T0 + 20000, ended_by: 'gave_up' },
  ]);
  assert.equal(world.areas.session.get('session'), undefined);
  assert.equal(controller.getState().phase, 'idle');
});

test('between tasks the panel asks for a drift check, once there is an initial calibration', async () => {
  const { controller, log, handlers } = compose({ camera: { drift_check_between_tasks: true } });
  await controller.init();
  await controller.startSession({ ...FORM, mode: 'guided' });
  const checks = () => log.filter((entry) => entry.message === 'calibration.request').map((entry) => entry.payload.type);

  // Sin calibración inicial no hay nada que comprobar.
  await controller.startTask();
  await controller.endTask('done');
  assert.deepEqual(checks(), []);

  await controller.requestCalibration('initial');
  handlers.get('calibration.result')({ error_px: 90, error_deg: 2.1, accepted: true });
  await controller.startTask();
  await controller.endTask('done');
  assert.deepEqual(checks(), ['initial', 'drift_check']);
  assert.equal(controller.getState().calibration.pending, 'drift_check');
  handlers.get('calibration.result')({ error_px: 40, error_deg: 0.9, accepted: true });
  assert.deepEqual(controller.getState().calibration.drift_check, { error_px: 40, error_deg: 0.9, accepted: true });

  // Tras la última tarea viene el SUS: no hace falta comprobar.
  await controller.startTask();
  await controller.endTask('done');
  assert.deepEqual(checks(), ['initial', 'drift_check']);
});

test('a reference session leaves its recording flushed before the draft reference is created', async () => {
  const { controller, batcher, log, clock, world } = compose();
  await controller.init();
  await controller.startSession({ ...FORM, mode: 'reference' });

  clock.time = T0 + 1000;
  await controller.startRecording(2);
  // Lo que la captura de interacción entrega mientras se graba, marcado con la tarea.
  assert.equal(world.areas.session.get('session').task_id, 2);
  batcher.add('events', { t: T0 + 2000, type: 'click', task_id: 2 });
  await controller.captureScreen();
  clock.time = T0 + 9000;
  await controller.stopRecording();
  await controller.closeSession();

  assert.deepEqual(sequence(log), [
    'api:createSession',
    'session.started',
    'task.started',
    'screen_capture.request',
    'batch:events',
    'batch:tasks',
    'api:createReference',
    'session.closed',
  ]);
  assert.deepEqual(log.find((entry) => entry.api === 'createReference').body, {
    task_id: 2,
    source_session_id: 12,
  });
  assert.deepEqual(batches(log, 'tasks')[0].payload.records, [
    { task_id: 2, t_start: T0 + 1000, t_end: T0 + 9000, ended_by: 'done' },
  ]);
  assert.deepEqual(log.find((entry) => entry.message === 'screen_capture.request').payload, {
    study_id: 1,
    screen: { url: TAB.url, title: TAB.title },
  });
});
