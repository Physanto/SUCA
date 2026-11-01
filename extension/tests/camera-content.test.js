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
  const zones = { zoneOf: UX.gazeZones.zoneOf, selectorOf: (e) => UX.gazeZones.selectorOf(e, escape) };
  const module = UX.createCameraModule({ link, zones, page: fakePage() });
  module.start({
    config: { camera: { gaze_hz: gazeHz, face_hz: faceHz } },
    batcher: { add: (type, record) => records.push({ type, record }) },
    session: { get: () => ({ task_id: taskId }) },
  });
  const of = (type) => records.filter((r) => r.type === type).map((r) => r.record);
  return { platform, timers, link, module, records, of };
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

/** Capa falsa: hace clic en cada punto y elige el botón que la prueba indique. */
function fakeUi({ answers = [], onPoint = () => {} } = {}) {
  const shown = [];
  let clickAt = 10000;
  return {
    shown,
    viewport: () => ({ width: 1000, height: 600 }),
    intro: async (type) => {
      shown.push(['intro', type]);
      return answers.length ? answers.shift() : 'start';
    },
    point: async (x, y, mode) => {
      shown.push(['point', mode, x, y]);
      onPoint(x, y, mode);
      clickAt += 2000;
      return { clickedAt: clickAt };
    },
    hold: async () => {},
    message: async (text, buttons) => {
      shown.push(['message', text, buttons]);
      if (buttons.length === 0) {
        return null;
      }
      return answers.length ? answers.shift() : buttons[0];
    },
  };
}

/** Conexión falsa con el motor para la calibración. */
function fakeLink({ status = 'active', fitOk = true, gazeError = 20 } = {}) {
  const requests = [];
  const listeners = new Set();
  let target = null;
  return {
    requests,
    status: () => status,
    request: async (action, payload) => {
      requests.push([action, payload]);
      if (action === 'calibration.fit') {
        return { ok: fitOk };
      }
      if (action === 'stats') {
        return { delay_ms: 41.6 };
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
        listeners.forEach((l) => l({ gaze: gazeError === null ? null : { x: target.x + gazeError, y: target.y } }));
      }
    },
  };
}

const CAMERA = { viewing_distance_cm: 60, css_px_per_cm: 37.8, calibration_max_error_deg: 5 };
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

test('initial calibration trains on 9 clicked points, validates on 5 others and reports the error', async () => {
  const link = fakeLink();
  const ui = fakeUi({ onPoint: (x, y) => link.lookAt(x, y) });
  const results = [];

  const record = await procedure(link, ui, results).run('initial', CAMERA);

  const points = link.requests.filter(([action]) => action === 'calibration.point');
  assert.equal(link.requests[0][0], 'calibration.reset');
  assert.equal(points.length, 9);
  assert.deepEqual(
    new Set(points.map(([, p]) => `${p.x},${p.y}`)).size,
    9,
    'every calibration point is different',
  );
  assert.deepEqual(points[0][1].t_end - points[0][1].t_start, 1400);
  assert.equal(ui.shown.filter(([kind, mode]) => kind === 'point' && mode === 'look').length, 5);
  assert.deepEqual(record, {
    t: 777,
    type: 'initial',
    error_px: 20,
    error_deg: Math.round(UX.calibrationMath.pxToDeg(20, CAMERA) * 100) / 100,
    accepted: true,
    camera_delay_ms: 42,
  });
  assert.deepEqual(results, [record]);
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
  assert.deepEqual(link.requests.map(([action]) => action), ['stats']);
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
  assert.equal(batches[0][0], 'calibration');
  assert.deepEqual(sent, [['calibration.result', { error_px: 20, error_deg: batches[0][1].error_deg, accepted: true }]]);
  module.stop();
  assert.equal(handlers['calibration.request'], undefined);
});
