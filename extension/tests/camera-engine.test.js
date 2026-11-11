/**
 * @file Pruebas del motor de la cámara (`camera/engine.js`) con cuadros
 * sintéticos: entrega a la pestaña, calibración (puntos fijos, punto en
 * movimiento y comprobación de deriva), estado de la mirada e intervalos sin datos.
 *
 * El estimador es el combinado con un solo candidato, la ridge de apariencia,
 * alimentada con un vector que es directamente el punto mirado en centenas de
 * píxeles: así se sabe qué debe responder el motor.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../camera/numeric.js');
require('../camera/gaze-model.js');
require('../camera/gaze-estimator.js');
require('../camera/gaze-filter.js');
require('../camera/gaze-monitor.js');
require('../camera/engine.js');

const { UX } = globalThis;

/** Encuadre de un rostro centrado a 60 cm, como lo calcula `faceFraming`. */
const FRAMING = { x: 0.5, y: 0.45, width: 0.3, distance_cm: 60 };
/** Ventana de la calibración. */
const VIEWPORT = { width: 1000, height: 700 };

/**
 * Características de un cuadro que mira un punto: el vector de apariencia es el
 * punto en centenas de píxeles (con un poco de ruido determinista).
 */
function looking(x, y, { blink = 0.02, jitter = 0 } = {}) {
  return {
    appearance: [x / 100 + jitter, y / 100 - jitter],
    geometric: null,
    signals: { blink, open: 0.3, yaw: 0, pitch: 0, refined: 2 },
    record: { face_detected: true, head_yaw: 0 },
  };
}

/** Motor con un reloj manual, y lo que recibió cada pestaña conectada. */
function setup() {
  let now = 1000;
  const statuses = [];
  const engine = UX.createCameraEngine({
    clock: { now: () => now },
    estimator: UX.createGazeEstimator({ appearance: UX.createGazeModel() }),
    monitor: UX.createGazeMonitor({ blinkThreshold: 0.45, headMarginDeg: 12, offScreenMarginPx: 120 }),
    // Corte altísimo: el filtro deja pasar el punto tal cual y las cuentas son exactas.
    filter: UX.createOneEuroFilter({ minCutoff: 1e6, beta: 0 }),
    blinkThreshold: 0.45,
    onStatus: (status) => statuses.push(status),
    info: () => ({ delegate: 'GPU' }),
  });
  /** Conecta una pestaña falsa. */
  function connect() {
    const received = [];
    const link = engine.connect({ post: (message) => received.push(message) });
    const request = (action, payload = {}) => {
      link.receive({ kind: 'request', id: received.length, action, ...payload });
      return received[received.length - 1];
    };
    return { received, link, request, of: (kind) => received.filter((m) => m.kind === kind) };
  }
  /** Entrega un cuadro en el momento `t`. */
  function frame(t, { face = true, features = null } = {}) {
    now = t;
    engine.frame({
      t,
      processedAt: t + 20,
      face: face ? { values: { brow_down_left: 0.1 }, head_yaw: 1, head_pitch: 2, framing: FRAMING } : null,
      features,
    });
  }
  return { engine, connect, frame, statuses, setNow: (t) => (now = t) };
}

/** Calibra con cinco puntos fijos; devuelve el momento siguiente y la respuesta del ajuste. */
function calibrate({ connect, frame }, tab = connect(), { offset = { x: 0, y: 0 } } = {}) {
  tab.request('calibration.reset', { viewport: VIEWPORT });
  const targets = [
    [100, 100],
    [900, 100],
    [100, 600],
    [900, 600],
    [500, 350],
  ];
  let t = 2000;
  targets.forEach(([x, y], group) => {
    const start = t;
    for (let i = 0; i < 10; i += 1) {
      frame(t, { features: looking(x + offset.x, y + offset.y, { jitter: (i % 3) * 0.002 }) });
      t += 33;
    }
    tab.request('calibration.point', { x, y, t_start: start, t_end: t, group });
  });
  return { t, fit: tab.request('calibration.fit'), tab };
}

test('greets each tab with the current state and forwards analysed frames', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();

  frame(1100);
  frame(1133, { face: false });

  // `started_at` es el momento en que se creó el motor: identifica a este motor ante la pestaña.
  assert.deepEqual(tab.received[0], { kind: 'hello', status: 'active', calibrated: false, started_at: 1000 });
  const common = { gaze: null, gaze_confidence: 0, features: null };
  assert.deepEqual(tab.of('frame'), [
    { kind: 'frame', t: 1100, face_detected: true, values: { brow_down_left: 0.1 }, head_yaw: 1, head_pitch: 2, framing: FRAMING, gaze_state: 'no_face', ...common },
    { kind: 'frame', t: 1133, face_detected: false, values: null, head_yaw: null, head_pitch: null, framing: null, gaze_state: 'no_face', ...common },
  ]);
});

test('reports status changes to the tabs and to the panel, once per change', () => {
  const { engine, connect, statuses } = setup();
  const tab = connect();

  engine.setStatus('no_permission');
  engine.setStatus('no_permission');
  engine.setStatus('active');

  assert.deepEqual(statuses, ['no_permission', 'active']);
  assert.deepEqual(tab.of('status').map((m) => m.status), ['no_permission', 'active']);
});

test('trains the estimator with the frames of each calibration point and then estimates gaze', () => {
  const world = setup();
  world.engine.setStatus('active');

  const { t, fit, tab } = calibrate(world);
  world.frame(t + 50, { features: looking(500, 350) });

  assert.equal(fit.ok, true);
  assert.equal(fit.estimator, 'appearance');
  assert.equal(world.engine.stats().calibrated, true);
  const last = tab.of('frame').at(-1);
  assert.ok(Math.hypot(last.gaze.x - 500, last.gaze.y - 350) < 25, `gaze ${last.gaze.x}, ${last.gaze.y}`);
  assert.equal(last.gaze_state, 'on_screen');
  // El cuadro lleva sus características para el lote gaze_features, con el punto antes del filtro.
  assert.equal(last.features.face_detected, true);
  assert.ok(Math.abs(last.features.raw_x - last.gaze.x) < 1e-6);

  tab.request('calibration.reset', { viewport: VIEWPORT });
  assert.equal(world.engine.stats().calibrated, false);
});

test('a calibration point leaves out blinks, frames without eyes and gazes far from the rest', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();
  tab.request('calibration.reset', { viewport: VIEWPORT });
  frame(1000, { face: false });
  frame(1033, { features: looking(1, 2, { blink: 0.9 }) });
  frame(1066, { features: looking(1, 2) });

  assert.equal(tab.request('calibration.point', { x: 1, y: 1, t_start: 900, t_end: 1100, group: 0 }).samples, 1);
});

test('measures the camera delay with the moving point and adds its path to the training', () => {
  const world = setup();
  world.engine.setStatus('active');
  const { t: start, tab } = calibrate(world);
  // Punto que cruza la pantalla en 4 s; el ojo de cada cuadro miraba el punto de 70 ms antes.
  const path = [];
  const position = (t) => ({ x: 100 + ((t - start) / 4000) * 800, y: 350 + 200 * Math.sin((t - start) / 600) });
  for (let t = start; t <= start + 4000; t += 16) {
    path.push({ t, ...position(t) });
  }
  for (let t = start; t <= start + 4000; t += 33) {
    const seen = position(t - 70);
    world.frame(t, { features: looking(seen.x, seen.y) });
  }

  const pursuit = tab.request('calibration.pursuit', { points: path, t_start: start, t_end: start + 4000 });
  const fit = tab.request('calibration.fit');

  assert.ok(pursuit.samples > 80);
  assert.equal(fit.camera_delay_ms, 70);
  assert.equal(fit.groups, 5 + 4);
});

test('a drift check measures the error, corrects it and keeps correcting the gaze afterwards', () => {
  const world = setup();
  world.engine.setStatus('active');
  const { t, tab } = calibrate(world);
  // La persona se corrió: mira donde el modelo cree que está 40 px más a la derecha y 30 más abajo.
  const drifted = (x, y) => looking(x + 40, y + 30);
  const points = [];
  let now = t;
  for (const [x, y] of [
    [500, 350],
    [200, 200],
  ]) {
    const tStart = now;
    for (let i = 0; i < 15; i += 1) {
      world.frame(now, { features: drifted(x, y) });
      now += 33;
    }
    points.push({ x, y, t_start: tStart, t_end: now });
  }

  const check = tab.request('calibration.drift', { points, correct: true, min_error_px: 10 });
  world.frame(now + 33, { features: drifted(700, 500) });

  assert.equal(check.corrected, true);
  // Los 50 px de la deriva, más el error propio del modelo de la prueba.
  assert.ok(check.error_px > 40 && check.error_px < 70, `error ${check.error_px}`);
  assert.ok(Math.abs(check.correction.x + 40) < 12 && Math.abs(check.correction.y + 30) < 12);
  const { gaze } = tab.of('frame').at(-1);
  assert.ok(Math.hypot(gaze.x - 700, gaze.y - 500) < 20, `corrected gaze ${gaze.x}, ${gaze.y}`);

  const small = tab.request('calibration.drift', { points, correct: true, min_error_px: 1000 });
  assert.equal(small.corrected, false);
});

test('looking far below the window is off the screen and gives no gaze point', () => {
  const world = setup();
  world.engine.setStatus('active');
  const { t, tab } = calibrate(world);

  world.frame(t, { features: looking(500, 1400) });
  world.frame(t + 33, { features: looking(500, 350, { blink: 0.8 }) });
  world.frame(t + 66, { features: looking(500, 350) });

  const [away, blink, back] = tab.of('frame').slice(-3);
  assert.deepEqual([away.gaze_state, away.gaze], ['off_screen', null]);
  assert.ok(away.features.raw_y > 1300);
  assert.deepEqual([blink.gaze_state, blink.gaze], ['blink', null]);
  assert.equal(back.gaze_state, 'low_confidence');
  assert.ok(back.gaze !== null);
});

test('answers unknown requests with an error', () => {
  const { connect } = setup();
  const reply = connect().request('format.disk');
  assert.deepEqual([reply.ok, reply.error], [false, 'unknown camera request: format.disk']);
});

test('reports a navigation gap from the last frame before the page left to the first frame after', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const first = connect();
  frame(1000);
  first.link.disconnect();
  frame(1500); // Sin pestaña conectada: no se entrega y no cierra el hueco.

  const second = connect();
  frame(2400);

  assert.deepEqual(second.of('gap'), [{ kind: 'gap', t: 1000, t_end: 2400, reason: 'navigation' }]);
  assert.deepEqual(first.of('gap'), []);
});

test('reports a gap while the camera has no permission, from the last frame to the recovery', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();
  frame(1000);

  engine.setStatus('no_permission');
  engine.setStatus('active');
  frame(9000);

  assert.deepEqual(tab.of('gap'), [{ kind: 'gap', t: 1000, t_end: 9000, reason: 'no_permission' }]);
});

test('skips gaps shorter than a normal processing delay', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const first = connect();
  frame(1000);
  first.link.disconnect();
  const second = connect();
  frame(1100);

  assert.deepEqual(second.of('gap'), []);
});

test('hands an open gap with no end to the tab when the session closes', () => {
  const { engine, connect, setNow } = setup();
  setNow(500);
  const tab = connect();

  engine.setStatus('error');
  const reply = tab.request('flush');

  assert.deepEqual(reply.gap, { t: 500, t_end: null, reason: 'error' });
  assert.equal(tab.request('flush').gap, null);
});

test('reports frame rate, processing delay and face ratio', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  connect();
  frame(1000);
  frame(1050);
  frame(1100, { face: false });

  const stats = engine.stats();

  assert.equal(stats.delegate, 'GPU');
  assert.equal(stats.hz, 20);
  assert.equal(stats.delay_ms, 20);
  assert.ok(Math.abs(stats.face_ratio - 2 / 3) < 1e-9);
});
