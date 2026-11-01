/**
 * @file Pruebas del motor de la cámara (`camera/engine.js`) con cuadros
 * sintéticos: entrega a la pestaña, calibración, estado e intervalos sin datos.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../camera/gaze-model.js');
require('../camera/engine.js');

const { UX } = globalThis;

/** Motor con un reloj manual, y lo que recibió cada pestaña conectada. */
function setup() {
  let now = 1000;
  const statuses = [];
  const engine = UX.createCameraEngine({
    clock: { now: () => now },
    gazeModel: UX.createGazeModel(),
    smoother: UX.createSmoother(1),
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
      face: face ? { values: { brow_down_left: 0.1 }, head_yaw: 1, head_pitch: 2 } : null,
      features,
    });
  }
  return { engine, connect, frame, statuses, setNow: (t) => (now = t) };
}

test('greets each tab with the current state and forwards analysed frames', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();

  frame(1100);
  frame(1133, { face: false });

  // `started_at` es el momento en que se creó el motor: identifica a este motor ante la pestaña.
  assert.deepEqual(tab.received[0], { kind: 'hello', status: 'active', calibrated: false, started_at: 1000 });
  assert.deepEqual(tab.of('frame'), [
    { kind: 'frame', t: 1100, face_detected: true, values: { brow_down_left: 0.1 }, head_yaw: 1, head_pitch: 2, gaze: null },
    { kind: 'frame', t: 1133, face_detected: false, values: null, head_yaw: null, head_pitch: null, gaze: null },
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

test('trains the gaze model with the frames of each calibration point and then estimates gaze', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();
  const targets = [
    [100, 100],
    [600, 100],
    [100, 500],
    [600, 500],
    [350, 300],
  ];
  let t = 2000;
  targets.forEach(([x, y], group) => {
    const start = t;
    for (let i = 0; i < 10; i += 1) {
      frame(t, { features: [x / 100 + i * 0.001, y / 100 - i * 0.001] });
      t += 33;
    }
    const reply = tab.request('calibration.point', { x, y, t_start: start, t_end: t, group });
    assert.deepEqual([reply.ok, reply.samples], [true, 10]);
  });

  const fit = tab.request('calibration.fit');
  frame(t + 50, { features: [3.5, 3] });

  assert.equal(fit.ok, true);
  assert.equal(engine.stats().calibrated, true);
  const { gaze } = tab.of('frame').at(-1);
  assert.ok(Math.hypot(gaze.x - 350, gaze.y - 300) < 25, `gaze ${gaze.x}, ${gaze.y}`);

  tab.request('calibration.reset');
  assert.equal(engine.stats().calibrated, false);
});

test('ignores frames without eye features when collecting a calibration point', () => {
  const { engine, connect, frame } = setup();
  engine.setStatus('active');
  const tab = connect();
  frame(1000, { face: false });
  frame(1033, { features: [1, 2] });

  assert.equal(tab.request('calibration.point', { x: 1, y: 1, t_start: 900, t_end: 1100, group: 0 }).samples, 1);
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
