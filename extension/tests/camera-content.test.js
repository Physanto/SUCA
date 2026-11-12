/**
 * @file Pruebas de la cámara en la pestaña evaluada: conexión con el motor
 * (`content/camera.js`), zonas de la mirada (`content/camera/zones.js`) y
 * procedimiento de calibración (`content/calibration.js`).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeTimers, settle } = require('./fakes.js');

require('../config.generated.js');
require('../camera/strings.js');
require('../content/camera/zones.js');
require('../content/camera.js');
require('../content/calibration.js');

const { UX } = globalThis;

/** Elemento falso con lo que usan las zonas y el selector. */
class FakeElement {
  constructor(tag, attributes = {}, children = []) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attributes = attributes;
    this.id = attributes.id || '';
    this.children = children;
    this.parentElement = null;
    children.forEach((child) => (child.parentElement = this));
  }

  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }
}
const el = (tag, attributes, children) => new FakeElement(tag, attributes, children);
const escape = (value) => value;

test('assigns the nearest semantic region, and the 3 x 3 grid when there is none', () => {
  const { zoneOf } = UX.gazeZones;
  const searchBox = el('input');
  const link = el('a');
  const cardTitle = el('h3');
  const plain = el('p');
  el('body', {}, [
    el('header', {}, [el('form', { role: 'search' }, [searchBox]), el('nav', {}, [link])]),
    el('main', {}, [el('article', {}, [el('header', {}, [cardTitle])])]),
    el('div', {}, [plain]),
  ]);

  assert.equal(zoneOf(searchBox, 0, 0, 1200, 800), 'search');
  assert.equal(zoneOf(link, 0, 0, 1200, 800), 'nav');
  // Un header dentro de un artículo no es el encabezado de la página.
  assert.equal(zoneOf(cardTitle, 0, 0, 1200, 800), 'main');
  assert.equal(zoneOf(plain, 1100, 790, 1200, 800), 'grid_bottom_right');
  assert.equal(zoneOf(null, 600, 400, 1200, 800), 'grid_middle_center');
  assert.equal(zoneOf(el('div', { role: 'contentinfo' }), 0, 0, 1, 1), 'footer');
});

test('builds the same selector format as the event capture', () => {
  const { selectorOf } = UX.gazeZones;
  const second = el('button');
  el('body', {}, [el('div', { id: 'cart' }, [el('button'), second])]);

  assert.equal(selectorOf(second, escape), '#cart > button:nth-of-type(2)');
});

/** Plataforma falsa: cada `connect` crea una conexión que la prueba maneja como el motor. */
function fakePlatform() {
  const ports = [];
  return {
    ports,
    connect(name) {
      const port = {
        name,
        sent: [],
        listeners: [],
        disconnectListeners: [],
        open: true,
        post(message) {
          port.sent.push(message);
        },
        onMessage: (listener) => port.listeners.push(listener),
        onDisconnect: (listener) => port.disconnectListeners.push(listener),
        disconnect() {
          port.open = false;
        },
        // Lo que hace el motor:
        deliver: (message) => port.listeners.forEach((listener) => listener(message)),
        drop() {
          port.open = false;
          port.disconnectListeners.forEach((listener) => listener());
        },
        reply(action, value) {
          const request = port.sent.find((m) => m.kind === 'request' && m.action === action);
          port.deliver({ kind: 'reply', id: request.id, ok: true, ...value });
        },
      };
      ports.push(port);
      return port;
    },
  };
}

/** Página falsa de 1200 × 800 con scroll y un elemento en todos lados. */
function fakePage() {
  const target = el('button', { id: 'buy' });
  el('main', {}, [target]);
  return {
    innerWidth: 1200,
    innerHeight: 800,
    scrollX: 0,
    scrollY: 340,
    location: { origin: 'https://shop.local', pathname: '/cart', search: '?q=secret', hash: '#x' },
    document: { elementFromPoint: () => target },
  };
}

/** Módulo de cámara con sus dependencias falsas, ya iniciado. */
function startCamera({ gazeHz = 30, faceHz = 15, taskId = 3 } = {}) {
  const platform = fakePlatform();
  const timers = createFakeTimers();
  const link = UX.createCameraLink({ platform, timers });
  const records = [];
  const sent = [];
  const zones = { zoneOf: UX.gazeZones.zoneOf, selectorOf: (e) => UX.gazeZones.selectorOf(e, escape) };
  const module = UX.createCameraModule({ link, zones, page: fakePage() });
  module.start({
    config: { camera: { gaze_hz: gazeHz, face_hz: faceHz } },
    contracts: UX.contracts,
    batcher: { add: (type, record) => records.push({ type, record }) },
    session: { get: () => ({ task_id: taskId }) },
    messages: { types: { TAB_IDENTIFY: 'tab.identify' }, send: async (type) => sent.push(type) },
  });
  const of = (type) => records.filter((r) => r.type === type).map((r) => r.record);
  return { platform, timers, link, module, records, sent, of };
}

/** Cuadro del motor. */
const frame = (t, gaze, face = true) => ({
  kind: 'frame',
  t,
  face_detected: face,
  values: face ? { brow_down_left: 0.123456 } : null,
  head_yaw: face ? 4.567 : null,
  head_pitch: face ? -1.234 : null,
  gaze,
});

test('records gaze with scroll, element and zone, and face samples at their own rate', () => {
  const { platform, of } = startCamera();
  const [port] = platform.ports;
  port.deliver({ kind: 'hello', status: 'active', calibrated: true });

  port.deliver(frame(1000, { x: 600.04, y: 400 }));
  port.deliver(frame(1033, null, false));
  port.deliver(frame(1066, { x: 1300, y: 100 }));

  assert.equal(port.name, 'camera');
  assert.deepEqual(of('gaze'), [
    { t: 1000, x: 600, y: 400, scroll_x: 0, scroll_y: 340, element_selector: '#buy', zone: 'main', valid: true },
    { t: 1033, x: null, y: null, scroll_x: 0, scroll_y: 340, element_selector: null, zone: null, valid: false },
    // Fuera de la ventana (por ejemplo, el panel lateral): se guarda el punto, sin zona.
    { t: 1066, x: 1300, y: 100, scroll_x: 0, scroll_y: 340, element_selector: null, zone: null, valid: false },
  ]);
  // A 15 Hz, de tres cuadros a 30 Hz se registran el primero y el tercero.
  assert.deepEqual(of('face'), [
    { t: 1000, values: { brow_down_left: 0.1235 }, head_yaw: 4.57, head_pitch: -1.23, face_detected: true },
    { t: 1066, values: { brow_down_left: 0.1235 }, head_yaw: 4.57, head_pitch: -1.23, face_detected: true },
  ]);
});

test('does not record gaze while it is paused for the calibration', () => {
  const { platform, link, of } = startCamera();
  const [port] = platform.ports;
  link.pauseGaze(true);
  port.deliver(frame(1000, { x: 1, y: 1 }));
  link.pauseGaze(false);
  port.deliver(frame(1100, { x: 1, y: 1 }));

  assert.deepEqual(of('gaze').map((r) => r.t), [1100]);
  assert.equal(of('face').length, 2);
});

test('records camera gaps as events without the query or fragment of the address', () => {
  const { platform, of } = startCamera();
  platform.ports[0].deliver({ kind: 'gap', t: 1000, t_end: 2400, reason: 'navigation' });

  assert.deepEqual(of('events'), [
    {
      t: 1000,
      type: 'camera_gap',
      screen: { url: 'https://shop.local/cart', title: '' },
      task_id: 3,
      data: { t_end: 2400, reason: 'navigation' },
    },
  ]);
});

test('records the gap left by an engine that Chrome closed and the worker replaced', async () => {
  const { platform, timers, of } = startCamera();
  const warnings = [];
  const originalWarn = console.warn;
  console.warn = (message) => warnings.push(message);
  try {
    platform.ports[0].deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: 100 });
    platform.ports[0].deliver(frame(1000, { x: 10, y: 10 }));
    platform.ports[0].drop();
    await timers.advance(1000);
    platform.ports[1].deliver({ kind: 'hello', status: 'active', calibrated: false, started_at: 1500 });
    platform.ports[1].deliver(frame(2600, null));
    platform.ports[1].deliver(frame(2700, null));
  } finally {
    console.warn = originalWarn;
  }

  assert.deepEqual(of('events').map((e) => [e.t, e.data]), [[1000, { t_end: 2600, reason: 'error' }]]);
  assert.equal(warnings.length, 1);
});

test('asks the worker to check the engine when an engine that greeted goes away', async () => {
  const { platform, timers, sent } = startCamera();
  // Motor que todavía no existe: la conexión se corta sin saludo y no se pregunta.
  platform.ports[0].drop();
  await timers.advance(1000);
  assert.deepEqual(sent, []);

  platform.ports[1].deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: 100 });
  platform.ports[1].drop();

  assert.deepEqual(sent, ['tab.identify']);
});

test('the same engine greeting again after a reconnection is not a restart', async () => {
  const { platform, timers, of } = startCamera();
  platform.ports[0].deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: 100 });
  platform.ports[0].deliver(frame(1000, { x: 10, y: 10 }));
  platform.ports[0].drop();
  await timers.advance(1000);
  platform.ports[1].deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: 100 });
  platform.ports[1].deliver(frame(2600, { x: 10, y: 10 }));

  assert.deepEqual(of('events'), []);
});

test('on stop, a replaced engine that never sent data leaves a gap with no end', async () => {
  const { platform, timers, module, of } = startCamera();
  platform.ports[0].deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: 100 });
  platform.ports[0].deliver(frame(1000, { x: 10, y: 10 }));
  platform.ports[0].drop();
  await timers.advance(1000);
  platform.ports[1].deliver({ kind: 'hello', status: 'starting', calibrated: false, started_at: 1500 });

  const stopping = module.stop();
  await settle();
  platform.ports[1].reply('flush', { gap: null });
  await stopping;

  assert.deepEqual(of('events').map((e) => [e.t, e.data]), [[1000, { t_end: null, reason: 'error' }]]);
});

test('face samples keep only the contract values, as numbers between 0 and 1', () => {
  const { platform, of } = startCamera();
  const values = { brow_down_left: 1.2, jaw_open_typo: 0.5, eye_blink_left: 'x', image: [1, 2, 3] };
  platform.ports[0].deliver({ ...frame(1000, null), values });
  platform.ports[0].deliver({ ...frame(1100, null), values: { not_in_contract: 0.3 } });

  assert.deepEqual(of('face'), [
    { t: 1000, values: { brow_down_left: 1 }, head_yaw: 4.57, head_pitch: -1.23, face_detected: true },
    { t: 1100, values: null, head_yaw: null, head_pitch: null, face_detected: false },
  ]);
});

test('reconnects when the engine is not there yet', async () => {
  const { platform, timers, link } = startCamera();
  platform.ports[0].drop();
  assert.equal(link.status(), 'unknown');

  await timers.advance(1000);

  assert.equal(platform.ports.length, 2);
  platform.ports[1].deliver({ kind: 'hello', status: 'no_permission', calibrated: false });
  assert.equal(link.status(), 'no_permission');
});

test('matches replies to requests and fails pending ones when the engine goes away', async () => {
  const { platform, link } = startCamera();
  const [port] = platform.ports;

  const stats = link.request('stats');
  port.reply('stats', { hz: 29.5 });
  const lost = link.request('calibration.fit');
  port.drop();

  assert.equal((await stats).hz, 29.5);
  await assert.rejects(lost, /disconnected/);
  await assert.rejects(link.request('stats'), /not connected/);
});

test('on stop, records the gap still open with no end and closes the connection', async () => {
  const { platform, module, of } = startCamera();
  const [port] = platform.ports;

  const stopping = module.stop();
  await settle();
  port.reply('flush', { gap: { t: 500, t_end: null, reason: 'no_permission' } });
  await stopping;

  assert.deepEqual(of('events').map((e) => e.data), [{ t_end: null, reason: 'no_permission' }]);
  assert.equal(port.open, false);
});

test('on stop, gives up on a busy engine before the module stop limit', async () => {
  const { platform, timers, module, records } = startCamera();
  const [port] = platform.ports;
  let stopped = false;

  const stopping = module.stop().then(() => (stopped = true));
  await settle();
  // `modules.js` espera 2 s cada `stop()`: la cámara tiene que terminar antes.
  await timers.advance(1499);
  assert.equal(stopped, false);
  await timers.advance(1);
  await stopping;

  assert.equal(stopped, true);
  assert.deepEqual(records, []);
  assert.equal(port.open, false);
});

/** Capa falsa: hace clic en cada punto y elige el botón que la prueba indique. */
function fakeUi({ answers = [], onPoint = () => {} } = {}) {
  const shown = [];
  let clickAt = 10000;
  return {
    shown,
    viewport: () => ({ width: 1000, height: 600 }),
    intro: async (type, framing = null) => {
      shown.push(['intro', type, framing === null ? 'no framing' : 'framing']);
      return answers.length && ['start', 'startAnyway', 'cancel'].includes(answers[0]) ? answers.shift() : 'start';
    },
    point: async (x, y, mode) => {
      shown.push(['point', mode, x, y]);
      onPoint(x, y, mode);
      clickAt += 2000;
      return { clickedAt: clickAt };
    },
    hold: async () => {},
    // El punto en movimiento recorre tres posiciones, cada una anotada con su momento.
    pursuit: async (positionAt, durationMs) => {
      shown.push(['pursuit', durationMs]);
      const points = [0, 33, 66].map((elapsed) => ({ t: 50000 + elapsed, ...positionAt(elapsed) }));
      return { points, tStart: 50000, tEnd: 50000 + durationMs };
    },
    message: async (text, buttons) => {
      shown.push(['message', text, buttons]);
      if (buttons.length === 0) {
        return null;
      }
      // Cada respuesta va al primer mensaje que la ofrece; los demás toman su primer botón.
      return answers.length && buttons.includes(answers[0]) ? answers.shift() : buttons[0];
    },
  };
}

/** Conexión falsa con el motor para la calibración. */
function fakeLink({
  status = 'active',
  fitOk = true,
  gazeError = 20,
  distance = null,
  drift = { ok: true, samples: 30, error_px: 80, corrected: true, correction: { x: -60.04, y: 52.96 } },
} = {}) {
  const requests = [];
  const listeners = new Set();
  let target = null;
  return {
    requests,
    // `status` puede ser una función, para simular una cámara que termina de arrancar.
    status: () => (typeof status === 'function' ? status() : status),
    request: async (action, payload) => {
      requests.push([action, payload]);
      if (action === 'calibration.fit') {
        return fitOk ? { ok: true, estimator: 'geometric', camera_delay_ms: 70 } : { ok: false };
      }
      if (action === 'stats') {
        return { delay_ms: 41.6, estimator: 'geometric' };
      }
      if (action === 'calibration.drift') {
        return drift;
      }
      return { ok: true };
    },
    onFrame(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    lookAt(x, y) {
      target = { x, y };
    },
    // Durante la medición llegan cuadros con un error fijo respecto del punto.
    emit(n) {
      for (let i = 0; i < n; i += 1) {
        const framing = distance === null ? null : { x: 0.5, y: 0.5, width: 0.3, distance_cm: distance };
        listeners.forEach((l) =>
          l({ gaze: gazeError === null ? null : { x: target.x + gazeError, y: target.y }, framing }),
        );
      }
    },
  };
}

const CAMERA = {
  viewing_distance_cm: 60,
  css_px_per_cm: 37.8,
  min_distance_cm: 35,
  max_distance_cm: 75,
  calibration_max_error_deg: 5,
  drift_correction: true,
  drift_correction_min_error_deg: 1,
};
const strings = UX.cameraStrings.calibration;

/** Procedimiento con espera falsa: cada espera de medición emite cuadros. */
function procedure(link, ui, results = []) {
  return UX.createCalibrationProcedure({
    link,
    ui,
    strings,
    clock: { now: () => 777 },
    wait: async (ms) => {
      if (ms === 1000) {
        link.emit(5);
      }
    },
    onResult: (record) => results.push(record),
    random: () => 0,
  });
}

test('converts pixels to degrees of visual angle at the configured distance', () => {
  // 37.8 px/cm: 378 px son 10 cm; a 60 cm, atan(10/60) ≈ 9.46°.
  assert.ok(Math.abs(UX.calibrationMath.pxToDeg(378, CAMERA) - 9.4623) < 1e-3);
});

test('initial calibration trains on 13 clicked points, a moving point and head movement, then validates on 9', async () => {
  const link = fakeLink();
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });
  const results = [];
  const targets = [];
  const run = UX.createCalibrationProcedure({
    link,
    ui,
    strings,
    clock: { now: () => 777 },
    wait: async (ms) => ms === 1000 && link.emit(5),
    onResult: (record) => results.push(record),
    onTarget: (record) => targets.push(record),
    random: () => 0,
  });

  const record = await run.run('initial', CAMERA);

  const actions = link.requests.map(([action]) => action);
  const points = link.requests.filter(([action, p]) => action === 'calibration.point' && p.phase === 'points');
  // El motor recibe la pantalla de este equipo junto con la ventana.
  assert.deepEqual(link.requests[0], ['calibration.reset', { viewport: { width: 1000, height: 600 }, css_px_per_cm: 37.8 }]);
  assert.equal(points.length, 13);
  assert.equal(new Set(points.map(([, p]) => `${p.x},${p.y}`)).size, 13, 'every calibration point is different');
  assert.equal(points[0][1].t_end - points[0][1].t_start, 1100);
  // Después de los puntos: el punto en movimiento, la cabeza y el ajuste, en ese orden.
  assert.deepEqual(actions.slice(14), ['calibration.pursuit', 'calibration.point', 'calibration.fit']);
  assert.equal(link.requests[14][1].points.length, 3);
  assert.equal(link.requests[15][1].phase, 'head');
  // 8 puntos de validación y el del regreso del teclado, todos sin clic.
  assert.equal(ui.shown.filter(([kind, mode]) => kind === 'point' && mode === 'look').length, 1 + 9);
  const deg = (px) => Math.round(UX.calibrationMath.pxToDeg(px, CAMERA) * 100) / 100;
  assert.deepEqual(record, {
    t: 777,
    type: 'initial',
    error_px: 20,
    error_deg: deg(20),
    accepted: true,
    // Sin encuadre en los cuadros no hay distancia medida: el error usa la de la configuración.
    viewing_distance_cm: null,
    css_px_per_cm: 37.8,
    // Las muestras de cada punto son idénticas: no hay temblor.
    precision_deg: 0,
    return_error_deg: deg(20),
    estimator: 'geometric',
    camera_delay_ms: 70,
  });
  assert.deepEqual(results, [record]);
  assert.deepEqual(
    targets.map((target) => target.phase),
    [...Array(13).fill('points'), 'pursuit', 'head', ...Array(8).fill('validation'), 'look_away'],
  );
  assert.ok(targets.every((target) => target.calibration_type === 'initial' && target.viewport_width === 1000));
});

test('a drift check clicks three points, lets the engine correct and records the correction', async () => {
  const link = fakeLink();
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });
  const targets = [];
  const run = UX.createCalibrationProcedure({
    link,
    ui,
    strings,
    clock: { now: () => 777 },
    wait: async () => {},
    onTarget: (record) => targets.push(record),
    random: () => 0,
  });

  const record = await run.run('drift_check', CAMERA);

  const [, drift] = link.requests.find(([action]) => action === 'calibration.drift');
  assert.equal(drift.points.length, 3);
  assert.deepEqual([drift.points[0].x, drift.points[0].y], [500, 300]);
  assert.equal(drift.correct, true);
  // 1° a 60 cm con 37,8 px/cm.
  assert.ok(Math.abs(drift.min_error_px - UX.calibrationMath.degToPx(1, CAMERA)) < 1e-9);
  assert.deepEqual(record, {
    t: 777,
    type: 'drift_check',
    error_px: 80,
    error_deg: Math.round(UX.calibrationMath.pxToDeg(80, CAMERA) * 100) / 100,
    accepted: true,
    viewing_distance_cm: null,
    css_px_per_cm: 37.8,
    precision_deg: null,
    return_error_deg: null,
    estimator: 'geometric',
    corrected: true,
    correction_x_px: -60,
    correction_y_px: 53,
  });
  assert.deepEqual(targets.map((target) => [target.calibration_type, target.phase]), Array(3).fill(['drift_check', 'drift_check']));
  assert.ok(ui.shown.some(([kind, text]) => kind === 'message' && text.startsWith(strings.driftCorrected)));
});

test('a drift check without a trained model gives no result', async () => {
  const link = fakeLink({ drift: { ok: true, samples: 0, error_px: null, corrected: false, correction: { x: 0, y: 0 } } });

  assert.equal(await procedure(link, fakeUi()).run('drift_check', CAMERA), null);
});

test('the moving point starts at the center and stays inside the window', () => {
  const viewport = { width: 1000, height: 600 };
  assert.deepEqual(UX.calibrationMath.pursuitAt(0, viewport), { x: 500, y: 300 });
  for (let t = 0; t <= 12000; t += 50) {
    const p = UX.calibrationMath.pursuitAt(t, viewport);
    assert.ok(p.x >= 99.999 && p.x <= 900.001 && p.y >= 59.999 && p.y <= 540.001);
  }
});

test('the recorded moving point keeps one position per camera frame at screen refresh rate', () => {
  // A 60 Hz la pantalla dibuja cada ~16,7 ms, menos que la separación pedida:
  // antes se comparaba con el punto anterior y solo quedaba el primero.
  const path = Array.from({ length: 721 }, (_, i) => ({ t: 1000 + i * 16.7, x: i, y: 2 * i }));
  const kept = UX.calibrationMath.thinPath(path, 33);

  assert.ok(kept.length >= 350 && kept.length <= 362);
  assert.equal(kept[0], path[0]);
  assert.equal(kept[kept.length - 1], path[path.length - 1]);
  for (let i = 1; i < kept.length - 1; i += 1) {
    assert.ok(kept[i].t - kept[i - 1].t >= 32);
  }
});

test('thinning keeps every point when they are already far apart and handles an empty path', () => {
  const path = [0, 40, 80].map((t) => ({ t, x: t, y: t }));

  assert.deepEqual(UX.calibrationMath.thinPath(path, 33), path);
  assert.deepEqual(UX.calibrationMath.thinPath([], 33), []);
});

test('precision is the RMS distance between consecutive samples of each point', () => {
  const series = [
    [
      { x: 0, y: 0 },
      { x: 3, y: 4 },
    ],
    [{ x: 100, y: 100 }],
    [
      { x: 0, y: 0 },
      { x: 0, y: 0 },
    ],
  ];
  // Dos pares: distancias 5 y 0 → raíz de (25 + 0) / 2.
  assert.ok(Math.abs(UX.calibrationMath.precisionPx(series) - Math.sqrt(12.5)) < 1e-9);
  assert.equal(UX.calibrationMath.precisionPx([[{ x: 1, y: 1 }]]), null);
});

test('the error in degrees uses the distance measured during the validation, and records it', async () => {
  const link = fakeLink({ distance: 50 });
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });

  const record = await procedure(link, ui).run('initial', CAMERA);

  assert.equal(record.viewing_distance_cm, 50);
  assert.equal(record.error_deg, Math.round(UX.calibrationMath.pxToDeg(20, CAMERA, 50) * 100) / 100);
  assert.ok(record.error_deg > UX.calibrationMath.pxToDeg(20, CAMERA), 'closer means a wider angle');
});

test('the framing is checked before the initial calibration but not before the final one', async () => {
  const link = fakeLink();
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });

  await procedure(link, ui).run('initial', CAMERA);
  await procedure(link, ui).run('final', CAMERA);

  assert.deepEqual(
    ui.shown.filter(([kind]) => kind === 'intro'),
    [['intro', 'initial', 'framing'], ['intro', 'final', 'no framing']],
  );
});

test('starting anyway calibrates as usual, and cancelling the introduction records nothing', async () => {
  const anyway = fakeLink();
  const record = await procedure(
    anyway,
    fakeUi({ answers: ['startAnyway'], onPoint: (x, y) => anyway.lookAt(x, y) }),
  ).run('initial', CAMERA);
  const cancelled = await procedure(fakeLink(), fakeUi({ answers: ['cancel'] })).run('initial', CAMERA);

  assert.equal(record.type, 'initial');
  assert.equal(cancelled, null);
});

/** Cuadros de un segundo con el mismo rostro, como los envía el motor. */
function framingFrames({ x = 0.5, y = 0.5, distance = 60, yaw = 0, faceEvery = 1, count = 30 } = {}) {
  return Array.from({ length: count }, (_, i) => {
    const face = i % faceEvery === 0;
    return {
      t: 1000 + i * 33,
      face_detected: face,
      head_yaw: face ? yaw : null,
      framing: face ? { x, y, width: 0.25, distance_cm: distance } : null,
    };
  });
}

test('the framing is right with the face seen, within the accepted distances, centered and facing the screen', () => {
  const { assessFraming } = UX.calibrationMath;

  const result = assessFraming(framingFrames({ distance: 63, x: 0.55, y: 0.62, yaw: -8 }), CAMERA);

  assert.equal(result.ok, true);
  assert.deepEqual(
    [result.face, result.distance, result.horizontal, result.vertical, result.frontal, result.distance_cm],
    [true, 'ok', 'ok', 'ok', true, 63],
  );
  // La figura se dibuja como en un espejo.
  assert.equal(result.x, 0.45);
});

test('the framing says how to move: closer or farther, left or right, and where to tilt the camera', () => {
  const { assessFraming } = UX.calibrationMath;
  const judge = (options) => assessFraming(framingFrames(options), CAMERA);

  // Cada persona puede sentarse donde le sea cómodo dentro del rango.
  for (const distance of [35, 48, 60, 75]) {
    assert.equal(judge({ distance }).distance, 'ok', `${distance} cm`);
  }
  assert.equal(judge({ distance: 30 }).distance, 'near');
  assert.equal(judge({ distance: 82 }).distance, 'far');
  // Imagen sin espejar: una cara a la izquierda de la imagen está corrida hacia la derecha de la persona.
  assert.equal(judge({ x: 0.2 }).horizontal, 'left');
  assert.equal(judge({ x: 0.8 }).horizontal, 'right');
  assert.equal(judge({ y: 0.2 }).vertical, 'up');
  assert.equal(judge({ y: 0.85 }).vertical, 'down');
  assert.equal(judge({ yaw: 25 }).frontal, false);
  for (const options of [{ distance: 30 }, { x: 0.2 }, { y: 0.85 }, { yaw: 25 }]) {
    assert.equal(judge(options).ok, false, JSON.stringify(options));
  }
});

test('the framing needs the face in most recent frames, and ignores the vertical tilt of the head', () => {
  const { assessFraming } = UX.calibrationMath;

  assert.equal(assessFraming(framingFrames({ faceEvery: 2 }), CAMERA).face, false);
  assert.equal(assessFraming([], CAMERA).face, false);
  // El cabeceo no entra: en un portátil la persona mira un poco hacia abajo.
  const lookingDown = framingFrames().map((frame) => ({ ...frame, head_pitch: -20 }));
  assert.equal(assessFraming(lookingDown, CAMERA).ok, true);
});

test('a rejected calibration can be repeated and each attempt is reported', async () => {
  const link = fakeLink({ gazeError: 300 });
  const ui = fakeUi({ answers: ['start', 'repeat', 'continue'], onPoint: (x, y) => link.lookAt(x, y) });
  const results = [];

  const record = await procedure(link, ui, results).run('initial', CAMERA);

  assert.equal(results.length, 2);
  assert.equal(record.accepted, false);
  assert.equal(link.requests.filter(([action]) => action === 'calibration.reset').length, 2);
});

test('final calibration only validates, without retraining', async () => {
  const link = fakeLink();
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });

  const record = await procedure(link, ui).run('final', CAMERA);

  assert.equal(record.type, 'final');
  // Solo pregunta qué estimador está en uso: no reinicia ni entrena.
  assert.deepEqual(link.requests.map(([action]) => action), ['stats']);
  assert.equal(record.estimator, 'geometric');
  assert.equal(record.camera_delay_ms, null);
});

test('waits for a camera that is still starting before calibrating', async () => {
  let polls = 0;
  const link = fakeLink({ status: () => (polls < 3 ? 'starting' : 'active') });
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });
  const waits = [];
  const run = UX.createCalibrationProcedure({
    link,
    ui,
    strings,
    clock: { now: () => 777 },
    wait: async (ms) => {
      waits.push(ms);
      if (ms === 250) {
        polls += 1;
      }
      if (ms === 1000) {
        link.emit(5);
      }
    },
    random: () => 0,
  });

  const record = await run.run('initial', CAMERA);

  assert.equal(record.accepted, true);
  assert.deepEqual(ui.shown[0], ['message', strings.cameraStarting, []]);
  assert.deepEqual(waits.slice(0, 3), [250, 250, 250]);
});

test('gives up on a camera that does not finish starting', async () => {
  const ui = fakeUi();
  let waited = 0;
  const run = UX.createCalibrationProcedure({
    link: fakeLink({ status: 'starting' }),
    ui,
    strings,
    clock: { now: () => 777 },
    wait: async (ms) => {
      waited += ms;
    },
  });

  assert.equal(await run.run('initial', CAMERA), null);
  assert.equal(waited, 20000);
  assert.deepEqual(ui.shown.map(([, text]) => text), [strings.cameraStarting, strings.cameraUnavailable]);
});

test('gives no result when the camera is not active, the face is lost or it is cancelled', async () => {
  const inactive = fakeUi();
  assert.equal(await procedure(fakeLink({ status: 'no_permission' }), inactive).run('initial', CAMERA), null);
  assert.deepEqual(inactive.shown, [['message', strings.cameraUnavailable, ['continue']]]);

  const noFace = fakeLink({ fitOk: false });
  const noFaceUi = fakeUi({ answers: ['start', 'cancel'], onPoint: (x, y) => noFace.lookAt(x, y) });
  assert.equal(await procedure(noFace, noFaceUi).run('initial', CAMERA), null);
  assert.ok(noFaceUi.shown.some(([, text]) => text === strings.noFace));

  const noGaze = fakeLink({ gazeError: null });
  const noGazeUi = fakeUi({ answers: ['start', 'cancel'], onPoint: (x, y) => noGaze.lookAt(x, y) });
  assert.equal(await procedure(noGaze, noGazeUi).run('final', CAMERA), null);
  assert.ok(noGazeUi.shown.some(([, text]) => text === strings.notCalibrated));

  assert.equal(await procedure(fakeLink(), fakeUi({ answers: ['cancel'] })).run('initial', CAMERA), null);
});

test('the calibration module runs on request, reports the result and pauses gaze meanwhile', async () => {
  const link = fakeLink();
  const pauses = [];
  link.pauseGaze = (value) => pauses.push(value);
  const ui = { ...fakeUi({ onPoint: (x, y) => link.lookAt(x, y) }), open() {}, close() {} };
  const handlers = {};
  const sent = [];
  const batches = [];
  const module = UX.createCalibrationModule({
    link,
    strings,
    createUi: () => ui,
    wait: async (ms) => {
      if (ms === 1000) {
        link.emit(5);
      }
    },
  });
  module.start({
    clock: { now: () => 1 },
    config: { camera: CAMERA },
    contracts: UX.contracts,
    batcher: { add: (type, record) => batches.push([type, record]) },
    messages: {
      types: { CALIBRATION_REQUEST: 'calibration.request', CALIBRATION_RESULT: 'calibration.result' },
      on: (type, handler) => {
        handlers[type] = handler;
        return () => delete handlers[type];
      },
      send: async (type, payload) => sent.push([type, payload]),
    },
  });

  assert.equal(handlers['calibration.request']({ type: 'initial' }), undefined);
  await settle(20);

  assert.deepEqual(pauses, [true, false]);
  const calibration = batches.filter(([type]) => type === 'calibration');
  assert.equal(calibration.length, 1);
  assert.equal(batches.filter(([type]) => type === 'gaze_target').length, 13 + 2 + 9);
  assert.deepEqual(sent, [['calibration.result', { error_px: 20, error_deg: calibration[0][1].error_deg, accepted: true }]]);
  module.stop();
  assert.equal(handlers['calibration.request'], undefined);
});

test('a calibration interrupted by the end of the session reports nothing afterwards', async () => {
  const link = fakeLink();
  const pauses = [];
  link.pauseGaze = (value) => pauses.push(value);
  let closes = 0;
  const ui = { ...fakeUi({ onPoint: (x, y) => link.lookAt(x, y) }), open() {}, close: () => (closes += 1) };
  const handlers = {};
  const sent = [];
  const batches = [];
  let module = null;
  module = UX.createCalibrationModule({
    link,
    strings,
    createUi: () => ui,
    wait: async (ms) => {
      if (ms === 1000) {
        link.emit(5);
        // La sesión se cierra en medio de la validación.
        module.stop();
      }
    },
  });
  module.start({
    clock: { now: () => 1 },
    config: { camera: CAMERA },
    contracts: UX.contracts,
    batcher: { add: (type, record) => batches.push([type, record]) },
    messages: {
      types: { CALIBRATION_REQUEST: 'calibration.request', CALIBRATION_RESULT: 'calibration.result' },
      on: (type, handler) => {
        handlers[type] = handler;
        return () => delete handlers[type];
      },
      send: async (type, payload) => sent.push([type, payload]),
    },
  });

  handlers['calibration.request']({ type: 'final' });
  await settle(20);

  assert.deepEqual(batches, []);
  assert.deepEqual(sent, []);
  // `stop` cerró la capa y reanudó la mirada una sola vez; el intento no las vuelve a tocar.
  assert.deepEqual(pauses, [true, false]);
  assert.equal(closes, 1);
});

test('the intro of the initial calibration says which screen and distances it assumes', () => {
  const local = strings.screenSummary({ ...CAMERA, screen_setup: 'local' });
  const fallback = strings.screenSummary({ ...CAMERA, screen_setup: 'config' });

  assert.match(local, /37\.8 píxeles por centímetro/);
  assert.match(local, /de 35 a 75 cm/);
  assert.match(local, /Ajustada en este equipo/);
  assert.match(fallback, /Opciones/);
});
