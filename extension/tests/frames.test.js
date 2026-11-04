/**
 * @file Pruebas de `content/frames.js`: cuándo pide capturas la pestaña evaluada
 * y qué zonas pide tapar, con una página falsa y temporizadores falsos.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeTimers } = require('./fakes.js');

require('../config.generated.js');
require('../content/frames.js');

const { UX } = globalThis;

/** Campo falso: etiqueta, atributos, caja y los selectores `#id` que pide el estudio. */
function field(tag, attributes = {}, box = { left: 10, top: 20, width: 100, height: 30 }) {
  return {
    tagName: tag.toUpperCase(),
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    matches(selector) {
      if (!/^#[\w-]+$/.test(selector)) {
        throw new SyntaxError(`unsupported selector ${selector}`);
      }
      return attributes.id === selector.slice(1);
    },
    getBoundingClientRect: () => ({ ...box, right: box.left + box.width, bottom: box.top + box.height }),
  };
}

/** Página falsa con documento, dirección y observador de cambios. */
function createPage(fields = []) {
  const timers = createFakeTimers();
  const listeners = new Map();
  const observers = [];
  const page = {
    innerWidth: 1200,
    innerHeight: 700,
    location: { href: 'https://shop.local/' },
    setTimeout: timers.setTimeout,
    clearTimeout: timers.clearTimeout,
    MutationObserver: class {
      constructor(callback) {
        this.callback = callback;
        observers.push(this);
      }

      observe() {}

      disconnect() {
        this.disconnected = true;
      }
    },
    document: {
      documentElement: {},
      querySelectorAll: () => fields,
      addEventListener: (type, listener) => listeners.set(type, listener),
      removeEventListener: (type) => listeners.delete(type),
    },
  };
  return { page, timers, listeners, observers, fire: (type) => listeners.get(type)({ type }) };
}

/** Inicia el módulo sobre una página falsa y anota cada pedido de captura. */
function start({ fields = [], recorded = [] } = {}) {
  const world = createPage(fields);
  const sent = [];
  const handlers = new Map();
  const module = UX.createFramesModule({ page: world.page });
  module.start({
    clock: { now: world.timers.now },
    session: { get: () => ({ session_id: 7, recorded_fields: recorded }) },
    messages: {
      types: { FRAME_REQUEST: 'frame.request', FRAME_MASKS: 'frame.masks' },
      send: async (type, payload) => {
        sent.push({ type, payload, at: world.timers.now() });
      },
      on(type, handler) {
        handlers.set(type, handler);
        return () => handlers.delete(type);
      },
    },
  });
  return { ...world, module, sent, handlers };
}

test('asks for a frame once the page has loaded, and for another after a click', () => {
  const { timers, fire, sent, module } = start();

  timers.advanceSync(599);
  assert.equal(sent.length, 0);
  timers.advanceSync(1);
  assert.deepEqual(sent.map((item) => [item.type, item.at]), [['frame.request', 600]]);

  timers.advanceSync(1000);
  fire('click');
  timers.advanceSync(350);
  module.stop();

  assert.deepEqual(sent.map((item) => item.at), [600, 1950]);
  assert.equal(sent[1].payload.viewport_width, 1200);
});

test('never asks for two frames less than a second apart', () => {
  const { timers, fire, sent, module } = start();
  timers.advanceSync(600);

  fire('click');
  timers.advanceSync(3000);
  module.stop();

  assert.deepEqual(sent.map((item) => item.at), [600, 1600]);
});

test('a short scroll is captured once it stops', () => {
  const { timers, fire, sent, module } = start();
  timers.advanceSync(2000);

  fire('scroll');
  timers.advanceSync(200);
  fire('scroll');
  timers.advanceSync(1000);
  module.stop();

  assert.deepEqual(sent.map((item) => item.at), [600, 2500]);
});

test('a long scroll is captured every 1.5 s, not only when it stops', () => {
  const { timers, fire, sent, module } = start();
  timers.advanceSync(2000);

  // Scroll continuo de 2 s a 4,9 s: una captura a 1,5 s de empezar y otra a 1,5 s
  // de la anterior, que ya muestra la posición final.
  for (let elapsed = 0; elapsed < 3000; elapsed += 100) {
    fire('scroll');
    timers.advanceSync(100);
  }
  timers.advanceSync(2000);
  module.stop();

  assert.deepEqual(sent.map((item) => item.at), [600, 3500, 5000]);
});

test('asks for a frame when the address changes and when the page changed by itself', () => {
  const { page, timers, observers, sent, module } = start();
  timers.advanceSync(1000);

  page.location.href = 'https://shop.local/cart';
  timers.advanceSync(1000);
  observers[0].callback([]);
  timers.advanceSync(3000);
  module.stop();

  assert.deepEqual(sent.map((item) => item.at), [600, 1850, 3000]);
  assert.ok(observers[0].disconnected);
});

test('masks every visible typing field except the declared ones, and always secrets', () => {
  const fields = [
    field('input', { id: 'q', type: 'search' }, { left: 0, top: 0, width: 300, height: 40 }),
    field('input', { id: 'name', type: 'text' }, { left: 10.4, top: 20.6, width: 99.2, height: 30 }),
    field('input', { id: 'pass', type: 'password' }),
    field('input', { id: 'card', autocomplete: 'cc-number' }),
    field('textarea', { id: 'notes' }, { left: 10, top: 900, width: 100, height: 30 }),
    field('input', { id: 'accept', type: 'checkbox' }),
    field('input', { id: 'hidden-box', type: 'text' }, { left: 0, top: 0, width: 0, height: 0 }),
  ];
  const recorded = [
    { name: 'search', selector: '#q' },
    { name: 'pass', selector: '#pass' },
    { name: 'broken', selector: 'input[' },
  ];
  const { timers, sent, module } = start({ fields, recorded });

  timers.advanceSync(600);
  module.stop();

  assert.deepEqual(sent[0].payload.masks, [
    { x: 8, y: 18, w: 104, h: 34 },
    { x: 8, y: 18, w: 104, h: 34 },
    { x: 8, y: 18, w: 104, h: 34 },
  ]);
});

test('answers frame.masks with the zones measured at that moment', () => {
  const box = { left: 10, top: 20, width: 100, height: 30 };
  const name = field('input', { id: 'name', type: 'text' }, box);
  const { handlers, module } = start({ fields: [name] });

  const before = handlers.get('frame.masks')();
  box.top = 80;
  const after = handlers.get('frame.masks')();
  module.stop();

  assert.deepEqual(before, { viewport_width: 1200, masks: [{ x: 8, y: 18, w: 104, h: 34 }] });
  assert.deepEqual(after.masks, [{ x: 8, y: 78, w: 104, h: 34 }]);
});

test('stop drops the pending frame and removes every listener', () => {
  const { timers, listeners, handlers, sent, module } = start();

  module.stop();
  timers.advanceSync(5000);

  assert.equal(sent.length, 0);
  assert.equal(listeners.size, 0);
  assert.equal(handlers.size, 0);
  assert.equal(timers.pending(), 0);
});
