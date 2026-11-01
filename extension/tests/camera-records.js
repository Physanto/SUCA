/**
 * @file Genera, con el código real de la cámara de la pestaña, un ejemplo de cada
 * registro que produce (`gaze`, `face`, `calibration` y eventos `camera_gap`) y lo
 * escribe como JSON en la salida estándar.
 *
 * No es una prueba de `node --test`: la usa `tests/contracts/test_camera_records.py`
 * para validar esos registros con el validador de contratos de Python, que es el
 * único que entiende los esquemas completos.
 *
 * Los cuadros incluyen datos que el motor no debería enviar (nombres fuera del
 * contrato, una lista de píxeles): ninguno debe llegar a un registro.
 */

'use strict';

require('../config.generated.js');
require('../camera/strings.js');
require('../content/camera/zones.js');
require('../content/camera.js');
require('../content/calibration.js');

const { UX } = globalThis;

/** Momento realista, en milisegundos desde 1970, como `UX.clock.now()`. */
const T0 = 1791380000000;

/** Elemento falso con lo que usan la zona y el selector. */
function element(tag, attributes = {}, children = []) {
  const node = {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    id: attributes.id || '',
    parentElement: null,
    children,
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
  };
  children.forEach((child) => (child.parentElement = node));
  return node;
}

/** Conexión falsa con el motor: la generación hace de motor. */
function fakePlatform() {
  const ports = [];
  return {
    ports,
    connect(name) {
      const port = {
        name,
        listeners: [],
        disconnectListeners: [],
        post() {},
        onMessage: (listener) => port.listeners.push(listener),
        onDisconnect: (listener) => port.disconnectListeners.push(listener),
        disconnect() {},
        deliver: (message) => port.listeners.forEach((listener) => listener(message)),
        drop: () => port.disconnectListeners.forEach((listener) => listener()),
      };
      ports.push(port);
      return port;
    },
  };
}

/** Temporizadores inmediatos: la reconexión ocurre en cuanto se pide. */
const timers = { setTimeout: (fn) => (fn(), 0), clearTimeout: () => {} };

/** Registros de `gaze`, `face` y `events` de una sesión con cuadros variados. */
function cameraRecords() {
  const records = [];
  const platform = fakePlatform();
  const link = UX.createCameraLink({ platform, timers });
  const button = element('button', { id: 'buy' });
  element('main', {}, [button]);
  const loose = element('div');
  element('body', {}, [loose]);
  const page = {
    innerWidth: 1200,
    innerHeight: 800,
    scrollX: 0,
    scrollY: 340.25,
    location: { origin: 'https://shop.local', pathname: '/cart', search: '?q=secreto', hash: '#token=x' },
    document: { elementFromPoint: (x) => (x < 600 ? button : loose) },
  };
  const zones = { zoneOf: UX.gazeZones.zoneOf, selectorOf: (node) => UX.gazeZones.selectorOf(node, (v) => v) };
  const module = UX.createCameraModule({ link, zones, page });
  module.start({
    config: UX.config,
    contracts: UX.contracts,
    batcher: { add: (type, record) => records.push({ type, record }) },
    session: { get: () => ({ task_id: 3 }) },
  });
  const frame = (dt, gaze, values) => ({
    kind: 'frame',
    t: T0 + dt,
    face_detected: values !== null,
    values,
    head_yaw: values === null ? null : 12.3456,
    head_pitch: values === null ? null : -4.321,
    gaze,
    pixels: [255, 0, 0, 255],
  });
  const face = { brow_down_left: 0.4, eye_blink_left: 1.3, not_a_contract_value: 0.2, image: 'data:,x' };

  let port = platform.ports[0];
  port.deliver({ kind: 'hello', status: 'active', calibrated: true, started_at: T0 - 5000 });
  port.deliver(frame(0, { x: 100.04, y: 200 }, face));
  port.deliver(frame(100, { x: 900, y: 790 }, face));
  port.deliver(frame(200, { x: -40, y: 100 }, face));
  port.deliver(frame(300, null, null));
  port.deliver({ kind: 'gap', t: T0 + 400, t_end: T0 + 1900, reason: 'navigation' });
  // Chrome cierra el motor y el worker crea otro: la pestaña registra el hueco.
  port.drop();
  port = platform.ports[1];
  port.deliver({ kind: 'hello', status: 'active', calibrated: false, started_at: T0 + 2000 });
  port.deliver(frame(3000, null, face));
  return records;
}

/** Registros `calibration` de una calibración inicial con un error fijo. */
async function calibrationRecords() {
  const records = [];
  const listeners = new Set();
  let target = { x: 0, y: 0 };
  const link = {
    status: () => 'active',
    request: async (action) => (action === 'calibration.fit' ? { ok: true } : { ok: true }),
    onFrame(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
  let clickAt = T0;
  const ui = {
    viewport: () => ({ width: 1200, height: 800 }),
    intro: async () => 'start',
    point: async (x, y) => {
      target = { x, y };
      clickAt += 2000;
      return { clickedAt: clickAt };
    },
    hold: async () => {},
    message: async (text, buttons) => (buttons.length ? buttons[0] : null),
  };
  const procedure = UX.createCalibrationProcedure({
    link,
    ui,
    strings: UX.cameraStrings.calibration,
    clock: { now: () => T0 + 60000 },
    wait: async (ms) => {
      if (ms === 1000) {
        for (let i = 0; i < 5; i += 1) {
          listeners.forEach((listener) => listener({ gaze: { x: target.x + 37.3, y: target.y - 12 } }));
        }
      }
    },
    onResult: (record) => records.push({ type: 'calibration', record }),
    random: () => 0.5,
  });
  await procedure.run('initial', UX.config.camera);
  return records;
}

(async () => {
  const all = [...cameraRecords(), ...(await calibrationRecords())];
  const byType = {};
  for (const { type, record } of all) {
    (byType[type] = byType[type] || []).push(record);
  }
  process.stdout.write(JSON.stringify({ contract_version: UX.contracts.version, batches: byType }));
})();
