/**
 * @file Pruebas de `content/capture.js`: descriptor del elemento y eventos de
 * clic, con un DOM mínimo en memoria (Node no trae uno y la extensión no
 * tiene dependencias).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeTimers, createFakeWorld, settle } = require('./fakes.js');

const EDITABLE = '[contenteditable]:not([contenteditable="false"])';
const TEXT_INPUT_ROLES = ['textbox', 'searchbox', 'combobox', 'spinbutton'];
const TEXT_INPUT = TEXT_INPUT_ROLES.map((role) => `[role="${role}"]`).join(',');
const LISTBOX = '[role="listbox"]';
const TEXT_ENTRY_TYPES = ['text', 'search', 'email', 'url', 'tel', 'number', 'password'];
const TYPING_INPUT = ['input:not([type])', ...TEXT_ENTRY_TYPES.map((type) => `input[type="${type}"]`), 'textarea'].join(',');

/** Elemento falso con lo justo que usa la captura: árbol, atributos, texto y caja. */
class FakeElement {
  constructor(tag, attributes = {}, { text = '', children = [], box = {} } = {}) {
    this.nodeType = 1;
    this.tagName = tag.toUpperCase();
    this.attributes = { ...attributes };
    this.id = attributes.id || '';
    this.ownText = text;
    this.children = children;
    this.parentElement = null;
    this.box = { x: 0, y: 0, width: 10, height: 10, ...box };
    children.forEach((child) => {
      child.parentElement = this;
    });
  }

  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }

  /** Visible salvo que la prueba lo oculte con `hidden = true`. */
  checkVisibility() {
    return !this.hidden;
  }

  hasAttribute(name) {
    return name in this.attributes;
  }

  getBoundingClientRect() {
    return this.box;
  }

  get textContent() {
    return [this.ownText, ...this.children.map((child) => child.textContent)].join(' ');
  }

  get innerText() {
    return this.textContent;
  }

  /** Zona editable: `contenteditable` presente y distinto de "false". */
  isEditable() {
    return this.hasAttribute('contenteditable') && this.getAttribute('contenteditable') !== 'false';
  }

  /** Solo entiende los selectores que usa la captura: zonas editables, cuadros de texto por rol y `textarea`. */
  matches(selector) {
    const matchers = {
      [EDITABLE]: (node) => node.isEditable(),
      [TEXT_INPUT]: (node) => TEXT_INPUT_ROLES.includes(node.getAttribute('role')),
      textarea: (node) => node.tagName === 'TEXTAREA',
      [LISTBOX]: (node) => node.getAttribute('role') === 'listbox',
      [TYPING_INPUT]: (node) =>
        node.tagName === 'TEXTAREA' ||
        (node.tagName === 'INPUT' && TEXT_ENTRY_TYPES.includes(node.getAttribute('type') || 'text')),
    };
    assert.ok(selector in matchers, `unexpected selector ${selector}`);
    return matchers[selector](this);
  }

  /** Si `node` es este elemento o está dentro de él. */
  contains(node) {
    for (let current = node; current; current = current.parentElement) {
      if (current === this) {
        return true;
      }
    }
    return false;
  }

  closest(selector) {
    for (let node = this; node; node = node.parentElement) {
      if (node.matches(selector)) {
        return node;
      }
    }
    return null;
  }

  querySelector(selector) {
    for (const child of this.children) {
      if (child.matches(selector)) {
        return child;
      }
      const found = child.querySelector(selector);
      if (found) {
        return found;
      }
    }
    return null;
  }
}

/** Atajo para armar elementos. */
const el = (tag, attributes, options) => new FakeElement(tag, attributes, options);

/** Documento falso: guarda los oyentes y permite dispararles eventos. */
function createFakeDocument() {
  const listeners = new Map();
  const passive = new Map();
  const ids = {};
  const registered = [];
  const tokens = (element, attribute) => (element.getAttribute(attribute) || '').split(/\s+/).filter(Boolean);
  /** Solo entiende las consultas que usa la captura para reconocer listas de sugerencias. */
  const queryAll = (selector) => {
    let match = /^\[aria-controls~="(.+)"\], \[aria-owns~="(.+)"\]$/.exec(selector);
    if (match) {
      assert.equal(match[1], match[2]);
      return registered.filter((node) => tokens(node, 'aria-controls').includes(match[1]) || tokens(node, 'aria-owns').includes(match[1]));
    }
    if (selector === '[aria-activedescendant]') {
      return registered.filter((node) => node.hasAttribute('aria-activedescendant'));
    }
    match = /^\[aria-labelledby~="(.+)"\]$/.exec(selector);
    assert.ok(match, `unexpected document query ${selector}`);
    return registered.filter((node) => tokens(node, 'aria-labelledby').includes(match[1]));
  };
  return {
    title: 'Carrito',
    activeElement: null,
    ids,
    /** Registra un árbol de elementos como si estuviera en la página. */
    add(...trees) {
      const visit = (node) => {
        registered.push(node);
        if (node.id) {
          ids[node.id] = ids[node.id] || node;
        }
        node.children.forEach(visit);
      };
      trees.forEach(visit);
    },
    getElementById: (id) => ids[id] || null,
    querySelector: (selector) => queryAll(selector)[0] || null,
    querySelectorAll: (selector) => queryAll(selector),
    documentElement: { tagName: 'HTML' },
    addEventListener(type, listener, options) {
      const capture = typeof options === 'object' ? options.capture : options;
      assert.equal(capture, true, 'listeners must use the capture phase');
      passive.set(type, typeof options === 'object' && options.passive === true);
      listeners.set(type, listener);
    },
    removeEventListener(type, listener, options) {
      const capture = typeof options === 'object' ? options.capture : options;
      assert.equal(capture, true, 'listeners must be removed with the same phase');
      if (listeners.get(type) === listener) {
        listeners.delete(type);
      }
    },
    isPassive: (type) => passive.get(type),
    dispatch(event) {
      const listener = listeners.get(event.type);
      if (listener) {
        listener(event);
      }
    },
    listenerTypes: () => [...listeners.keys()].sort(),
  };
}

// El módulo se registra al cargarse: se captura con un registro de pruebas.
let registered = null;
globalThis.UX = { modules: { register: (module) => (registered = module) } };
require('../config.generated.js');
require('../common/session.js');
const { UX } = globalThis;

/** MutationObserver falso: guarda su función para que la prueba dispare cambios. */
class FakeMutationObserver {
  constructor(callback) {
    this.callback = callback;
    this.options = null;
    this.connected = false;
    FakeMutationObserver.instances.push(this);
  }

  observe(target, options) {
    this.options = options;
    this.connected = true;
  }

  disconnect() {
    this.connected = false;
  }

  /** Cambios que el navegador aún no había entregado (la prueba los pone en `queued`). */
  takeRecords() {
    const queued = this.queued || [];
    this.queued = [];
    return queued;
  }

  /** Entrega `count` cambios a la función del módulo, como haría el navegador. */
  emit(count) {
    this.callback(Array.from({ length: count }, () => ({})));
  }
}
FakeMutationObserver.instances = [];
globalThis.MutationObserver = FakeMutationObserver;
globalThis.Element = FakeElement;
globalThis.CSS = { escape: (value) => value };
globalThis.location = { href: 'https://shop.local/cart' };
require('../content/capture.js');

const CAPTURE_CONFIG = { mousemove_hz: 50, scroll_hz: 10, click_response_wait_ms: 1500 };

/**
 * Inicia la captura con un contexto de sustitutos y devuelve lo necesario para probarla.
 *
 * Los temporizadores falsos se instalan solo mientras corre `start`, que es cuando
 * el módulo los toma; así no se altera el resto de la prueba.
 *
 * @param {object|null} [session] - Estado de la sesión que ve el módulo.
 * @param {object} [options] - Opciones.
 * @param {object} [options.config] - Sección `capture` de la configuración.
 * @param {boolean} [options.fakeClock] - Si el reloj sigue a los temporizadores falsos.
 */
function startCapture(
  session = { task_id: 3 },
  { config = CAPTURE_CONFIG, fakeClock = false, liveSession = null } = {},
) {
  const document = createFakeDocument();
  globalThis.document = document;
  globalThis.location = { href: 'https://shop.local/cart' };
  const pageListeners = new Map();
  globalThis.addEventListener = (type, listener) => pageListeners.set(type, listener);
  globalThis.removeEventListener = (type, listener) => {
    if (pageListeners.get(type) === listener) {
      pageListeners.delete(type);
    }
  };
  const timers = createFakeTimers();
  const added = [];
  const flushes = [];
  FakeMutationObserver.instances = [];
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = timers.setTimeout;
  globalThis.clearTimeout = timers.clearTimeout;
  try {
    registered.start({
      clock: { now: fakeClock ? timers.now : () => 1791380123456.2 },
      // `at` es el momento en que se entregó el registro, distinto de `record.t`
      // cuando el muestreador retrasó un valor pendiente.
      batcher: {
        add: (type, record) => added.push({ type, record, at: timers.now() }),
        flush: async () => flushes.push(timers.now()),
      },
      session: liveSession || { get: () => session },
      config: { capture: config },
      contracts: UX.contracts,
    });
  } finally {
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
  }
  // Al iniciar se registra la pantalla inicial; las pruebas de otros eventos la dejan aparte.
  const initial = added.splice(0);
  const click = (target, type = 'click', x = 845, y = 560) =>
    document.dispatch({ type, target, clientX: x, clientY: y });
  const pageHide = () => pageListeners.get('pagehide')({ type: 'pagehide' });
  return {
    document,
    added,
    initial,
    click,
    timers,
    flushes,
    pageHide,
    pageListeners,
    stop: () => registered.stop(),
  };
}

/** Descriptor del último clic sobre `target`. */
function describeByClick(target) {
  const { added, click } = startCapture();
  click(target);
  registered.stop();
  return added[0].record.element;
}

test('registers a module named capture', () => {
  assert.equal(registered.name, 'capture');
});

test('records click, dblclick and contextmenu as events with the full record', () => {
  const { added, click } = startCapture();
  const button = el('button', { id: 'btn-pay' }, { text: 'Ir a pagar' });
  for (const type of ['click', 'dblclick', 'contextmenu']) {
    click(button, type);
  }
  registered.stop();

  assert.deepEqual(
    added.map((entry) => [entry.type, entry.record.type]),
    [['events', 'click'], ['events', 'dblclick'], ['events', 'contextmenu']],
  );
  const [{ record }] = added;
  assert.equal(record.t, 1791380123456.2);
  assert.equal(record.x, 845);
  assert.equal(record.y, 560);
  assert.deepEqual(record.screen, { url: 'https://shop.local/cart', title: 'Carrito' });
  assert.equal(record.task_id, 3);
  assert.deepEqual(record.data, {});
  assert.deepEqual(Object.keys(record).sort(), ['data', 'element', 'screen', 't', 'task_id', 'type', 'x', 'y']);
});

test('describes the nearest interactive element when the click lands inside it', () => {
  const span = el('span', {}, { text: 'Pagar' });
  const icon = el('i', {}, { children: [] });
  const button = el('button', { id: 'btn-pay' }, { children: [icon, span], box: { x: 820, y: 540, width: 140, height: 40 } });
  el('body', {}, { children: [button] });

  const descriptor = describeByClick(span);

  assert.equal(descriptor.tag, 'button');
  assert.equal(descriptor.id, 'btn-pay');
  assert.equal(descriptor.role, 'button');
  assert.equal(descriptor.text, 'Pagar');
  assert.deepEqual(descriptor.box, { x: 820, y: 540, w: 140, h: 40 });
  assert.equal(descriptor.interactive, true);
});

test('describes the exact target when nothing interactive contains it', () => {
  const paragraph = el('p', {}, { text: 'Texto' });
  el('body', {}, { children: [el('div', {}, { children: [paragraph] })] });

  const descriptor = describeByClick(paragraph);

  assert.equal(descriptor.tag, 'p');
  assert.equal(descriptor.role, null);
  assert.equal(descriptor.interactive, false);
});

test('treats an element with an onclick handler or an interactive role as interactive', () => {
  assert.equal(describeByClick(el('div', { onclick: '' }, { text: 'x' })).interactive, true);
  assert.equal(describeByClick(el('div', { role: 'tab' }, { text: 'x' })).role, 'tab');
  assert.equal(describeByClick(el('div', { role: 'tab' }, { text: 'x' })).interactive, true);
});

test('resolves the implicit role of common tags', () => {
  const role = (tag, attributes) => describeByClick(el(tag, attributes)).role;
  assert.equal(role('a', { href: '/x' }), 'link');
  assert.equal(role('a', {}), null);
  assert.equal(role('h2', {}), 'heading');
  assert.equal(role('nav', {}), 'navigation');
  assert.equal(role('ul', {}), 'list');
  assert.equal(role('select', {}), 'combobox');
  assert.equal(role('input', { type: 'checkbox' }), 'checkbox');
  assert.equal(role('input', { type: 'password' }), 'textbox');
  assert.equal(role('input', { type: 'submit' }), 'button');
  assert.equal(role('input', { type: 'hidden' }), null);
  assert.equal(role('button', { role: 'link' }), 'link');
});

test('an anchor without href and a hidden input are not interactive', () => {
  assert.equal(describeByClick(el('a', {}, { text: 'x' })).interactive, false);
  assert.equal(describeByClick(el('input', { type: 'hidden' })).interactive, false);
  assert.equal(describeByClick(el('a', { href: '/x' }, { text: 'x' })).interactive, true);
});

test('collapses whitespace and trims the text to 50 characters', () => {
  const long = el('button', {}, { text: `  Ir   a\n pagar ${'x'.repeat(80)}` });
  const { text } = describeByClick(long);
  assert.equal(text.length, 50);
  assert.ok(text.startsWith('Ir a pagar xxx'));
  assert.equal(describeByClick(el('button', {}, { text: '   ' })).text, null);
});

test('never takes text from form fields, even when they hold typed content', () => {
  const secret = 'hunter2-secreto';
  for (const [tag, attributes] of [
    ['input', { type: 'password', id: 'password', value: secret }],
    ['input', { type: 'text', value: secret }],
    ['textarea', {}],
    ['select', {}],
  ]) {
    const field = el(tag, attributes, { text: secret });
    const { added, click } = startCapture();
    click(field);
    registered.stop();

    assert.equal(added[0].record.element.text, null, `${tag} text must be null`);
    assert.ok(!JSON.stringify(added[0].record).includes(secret));
  }
});

test('never takes text from editable zones or from elements that contain one', () => {
  const secret = 'lo-que-escribi';
  const editor = el('div', { contenteditable: 'true' }, { text: secret });
  const inside = el('p', {}, { text: secret });
  el('div', { contenteditable: '' }, { children: [inside] });
  const container = el('div', { onclick: '' }, { text: 'Resumen', children: [el('div', { contenteditable: 'true' }, { text: secret })] });
  const readonly = el('button', { contenteditable: 'false' }, { text: 'Solo lectura' });

  assert.equal(describeByClick(editor).text, null);
  assert.equal(describeByClick(inside).text, null);
  assert.equal(describeByClick(container).text, null);
  assert.equal(describeByClick(readonly).text, 'Solo lectura');
});

test('builds the selector from the id or from the path with nth-of-type', () => {
  const first = el('li', {}, { text: 'a' });
  const second = el('li', {}, { text: 'b' });
  const list = el('ul', {}, { children: [first, second] });
  const body = el('body', {}, { children: [list] });
  el('html', {}, { children: [body] });

  assert.equal(describeByClick(second).selector, 'body > ul > li:nth-of-type(2)');
  assert.equal(describeByClick(el('button', { id: 'btn-pay' })).selector, '#btn-pay');
});

test('describes an element the site already detached from the document', () => {
  assert.equal(describeByClick(el('button')).selector, 'button');
});

test('marks the record with the active task, or null when there is none', () => {
  for (const [session, expected] of [[{ task_id: 5 }, 5], [{ task_id: null }, null], [null, null]]) {
    const { added, click } = startCapture(session);
    click(el('button'));
    registered.stop();
    assert.equal(added[0].record.task_id, expected);
  }
});

test('records element null when the target is not an element', () => {
  const { added, click } = startCapture();
  click({ nodeType: 9 });
  registered.stop();
  assert.equal(added[0].record.element, null);
});

test('listens in the capture phase and stop removes every listener', () => {
  const { document, added, click } = startCapture();
  assert.deepEqual(document.listenerTypes(), [
    'click', 'contextmenu', 'dblclick', 'focusin', 'focusout', 'input', 'invalid', 'mousemove', 'scroll', 'selectionchange', 'submit',
  ]);

  registered.stop();

  assert.deepEqual(document.listenerTypes(), []);
  click(el('button'));
  assert.equal(added.length, 0);
});

/** Dispara un movimiento del cursor. */
const move = (document, x, y) => document.dispatch({ type: 'mousemove', clientX: x, clientY: y });

/** Dispara un scroll de la página en la posición dada. */
function scrollTo(document, x, y, target = document) {
  globalThis.scrollX = x;
  globalThis.scrollY = y;
  document.dispatch({ type: 'scroll', target });
}

test('records the first mousemove at once and only the last one of a burst when the interval ends', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  move(document, 10, 10);
  await timers.advance(5);
  move(document, 20, 20);
  await timers.advance(5);
  move(document, 30, 30);
  assert.equal(added.length, 1);

  await timers.advance(10);

  assert.equal(added.length, 2);
  assert.deepEqual(added.map((entry) => [entry.record.x, entry.record.y]), [[10, 10], [30, 30]]);
  registered.stop();
});

test('reschedules a timer that fires a little early instead of delivering too soon', async () => {
  const timers = createFakeTimers();
  const added = [];
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  const document = createFakeDocument();
  globalThis.document = document;
  // Un reloj que va 1 ms por delante de los temporizadores: el aviso llega "antes".
  let skew = 0;
  globalThis.setTimeout = timers.setTimeout;
  globalThis.clearTimeout = timers.clearTimeout;
  try {
    registered.start({
      clock: { now: () => timers.now() + skew },
      batcher: { add: (type, record) => added.push(record) },
      session: { get: () => null },
      config: { capture: CAPTURE_CONFIG },
      contracts: UX.contracts,
    });
  } finally {
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
  }
  added.length = 0;

  move(document, 1, 1);
  move(document, 2, 2);
  skew = -1;
  await timers.advance(20);
  assert.equal(added.length, 1);
  skew = 0;
  await timers.advance(1);

  assert.equal(added.length, 2);
  assert.ok(added[1].t - added[0].t >= 20);
  registered.stop();
});

test('records mousemove with coordinates, no element and the active task', () => {
  const { document, added } = startCapture({ task_id: 4 });

  move(document, 700, 410);
  registered.stop();

  const [{ type, record }] = added;
  assert.equal(type, 'events');
  assert.deepEqual(record, {
    t: 1791380123456.2,
    type: 'mousemove',
    x: 700,
    y: 410,
    data: {},
    screen: { url: 'https://shop.local/cart', title: 'Carrito' },
    task_id: 4,
  });
});

test('never delivers mousemove records closer than the configured interval', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  // Medio segundo de eventos cada 5 ms (200 Hz): a 50 Hz caben unos 25 registros.
  for (let ms = 0; ms < 500; ms += 5) {
    move(document, ms, ms);
    await timers.advance(5);
  }
  await timers.advance(100);
  registered.stop();

  // Se comprueba la hora del registro (`t`), que es la que llega a la base.
  const gaps = added.slice(1).map((entry, i) => entry.record.t - added[i].record.t);
  assert.ok(gaps.every((gap) => gap >= 20), `gaps were ${gaps}`);
  assert.ok(added.length >= 24 && added.length <= 26, `${added.length} records in half a second`);
});

test('reads the sampling rates from the configuration', async () => {
  const config = { ...CAPTURE_CONFIG, mousemove_hz: 10, scroll_hz: 2 };
  const { document, added, timers } = startCapture(undefined, { config, fakeClock: true });

  move(document, 1, 1);
  await timers.advance(50);
  move(document, 2, 2);
  await timers.advance(49);
  assert.equal(added.length, 1);
  await timers.advance(1);
  assert.equal(added.length, 2);

  scrollTo(document, 0, 100);
  await timers.advance(300);
  scrollTo(document, 0, 200);
  await timers.advance(199);
  assert.equal(added.filter((entry) => entry.record.type === 'scroll').length, 1);
  await timers.advance(1);
  assert.equal(added.filter((entry) => entry.record.type === 'scroll').length, 2);
  registered.stop();
});

test('records scroll with the page position in data and no pointer coordinates', () => {
  const { document, added } = startCapture({ task_id: null });

  scrollTo(document, 12, 480);
  registered.stop();

  assert.deepEqual(added[0].record, {
    t: 1791380123456.2,
    type: 'scroll',
    data: { scroll_x: 12, scroll_y: 480 },
    screen: { url: 'https://shop.local/cart', title: 'Carrito' },
    task_id: null,
  });
});

test('keeps the final scroll position of a burst and never records a negative one', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  scrollTo(document, 0, 100);
  await timers.advance(30);
  scrollTo(document, 0, -40);
  await timers.advance(30);
  scrollTo(document, 0, 300);
  await timers.advance(100);
  registered.stop();

  assert.deepEqual(added.map((entry) => entry.record.data.scroll_y), [100, 300]);
  scrollTo(document, -5, -5);
});

test('ignores the scroll of elements inside the page', () => {
  const { document, added } = startCapture();

  scrollTo(document, 0, 50, el('div'));
  registered.stop();

  assert.equal(added.length, 0);
});

test('listens to mousemove and scroll in passive mode', () => {
  const { document } = startCapture();
  assert.equal(document.isPassive('mousemove'), true);
  assert.equal(document.isPassive('scroll'), true);
  assert.equal(document.isPassive('click'), false);
  registered.stop();
});

test('stop discards the pending records and their timers', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  move(document, 1, 1);
  move(document, 2, 2);
  scrollTo(document, 0, 10);
  scrollTo(document, 0, 20);
  assert.equal(timers.pending(), 3);
  registered.stop();

  assert.equal(timers.pending(), 0);
  await timers.advance(500);
  assert.equal(added.length, 2);
});

test('refuses to start with a sampling rate that is not a positive number', () => {
  for (const config of [{ scroll_hz: 10 }, { mousemove_hz: 0, scroll_hz: 10 }, { mousemove_hz: 50, scroll_hz: 'a' }]) {
    const document = createFakeDocument();
    globalThis.document = document;
    const context = {
      clock: { now: () => 0 },
      batcher: { add() {} },
      session: { get: () => null },
      config: { capture: config },
    };

    assert.throws(() => registered.start(context), /positive number/);
    assert.deepEqual(document.listenerTypes(), []);
    registered.stop();
  }
});

/** Simula una selección del navegador con el texto dado, anclada en `anchor`. */
function selectText(text, anchor = el('p', {}, { text }), focus = anchor) {
  globalThis.getSelection = () => ({
    rangeCount: text === '' ? 0 : 1,
    anchorNode: { nodeType: 3, parentElement: anchor },
    focusNode: { nodeType: 3, parentElement: focus },
    toString: () => text,
  });
}

/** Avisa que la selección cambió, como hace el navegador. */
const selectionChanged = (document) => document.dispatch({ type: 'selectionchange' });

test('records one selection with only its length once the selection stops changing for 300 ms', async () => {
  const { document, added, timers } = startCapture({ task_id: 6 }, { fakeClock: true });

  selectText('Con');
  selectionChanged(document);
  await timers.advance(100);
  selectText('Contar clics');
  selectionChanged(document);
  await timers.advance(299);
  assert.equal(added.length, 0);
  await timers.advance(1);
  registered.stop();

  assert.equal(added.length, 1);
  assert.deepEqual(added[0].record, {
    t: 400,
    type: 'selection',
    data: { length: 12 },
    screen: { url: 'https://shop.local/cart', title: 'Carrito' },
    task_id: 6,
  });
});

test('never puts the selected text in the record', async () => {
  const secret = 'texto-seleccionado-privado';
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  selectText(secret);
  selectionChanged(document);
  await timers.advance(300);
  registered.stop();

  assert.equal(added[0].record.data.length, secret.length);
  assert.ok(!JSON.stringify(added).includes(secret));
  assert.ok(!('x' in added[0].record) && !('element' in added[0].record));
});

test('does not record an empty selection', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  selectText('');
  selectionChanged(document);
  await timers.advance(300);
  registered.stop();

  assert.equal(added.length, 0);
});

test('does not record a selection made inside a form field or an editable zone', async () => {
  const cases = [
    { active: el('input', { type: 'password' }), anchor: undefined },
    { active: el('textarea'), anchor: undefined },
    { active: el('div', { contenteditable: 'true' }), anchor: undefined },
    { active: null, anchor: el('div', { contenteditable: 'true' }) },
  ];
  for (const { active, anchor } of cases) {
    const { document, added, timers } = startCapture(undefined, { fakeClock: true });
    document.activeElement = active;

    selectText('lo que escribi', anchor);
    selectionChanged(document);
    await timers.advance(300);
    registered.stop();

    assert.equal(added.length, 0);
  }
});

test('stop cancels a pending selection', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  selectText('algo');
  selectionChanged(document);
  assert.equal(timers.pending(), 2);
  registered.stop();

  assert.equal(timers.pending(), 0);
  await timers.advance(500);
  assert.equal(added.length, 0);
});

/** Campo falso que lanza un error si alguien intenta leer lo que contiene. */
function secretField(tag, attributes = {}) {
  const field = el(tag, attributes);
  Object.defineProperty(field, 'value', {
    get() {
      throw new Error('the value of a field must never be read');
    },
  });
  return field;
}

/** Evento de campo cuyos datos de entrada lanzan un error si se leen. */
function guardedEvent(type, target) {
  const event = { type, target };
  for (const name of ['data', 'inputType', 'value']) {
    Object.defineProperty(event, name, {
      get() {
        throw new Error(`event.${name} must never be read`);
      },
    });
  }
  return event;
}

test('records focus_in and focus_out only for form fields, describing the field itself', () => {
  const { document, added } = startCapture();
  const name = el('input', { id: 'name', type: 'text' });
  const editor = el('div', { contenteditable: 'true' });
  // Un campo dentro de un enlace: se describe el campo, no el interactivo más cercano.
  el('a', { href: '/x' }, { children: [editor] });

  document.dispatch({ type: 'focusin', target: name });
  document.dispatch({ type: 'focusout', target: name });
  document.dispatch({ type: 'focusin', target: editor });
  document.dispatch({ type: 'focusin', target: el('button') });
  document.dispatch({ type: 'focusin', target: el('input', { type: 'hidden' }) });
  document.dispatch({ type: 'focusin', target: { nodeType: 9 } });
  registered.stop();

  assert.deepEqual(added.map((entry) => entry.record.type), ['focus_in', 'focus_out', 'focus_in']);
  assert.equal(added[0].record.element.id, 'name');
  assert.equal(added[0].record.element.text, null);
  assert.deepEqual(added[0].record.data, {});
  assert.equal(added[2].record.element.tag, 'div');
});

test('never reads or records what the participant typed in any kind of field', () => {
  const fields = [
    secretField('input', { type: 'text' }),
    secretField('input', { type: 'password', id: 'password' }),
    secretField('textarea'),
    secretField('select'),
    secretField('div', { contenteditable: 'true' }),
  ];
  const { document, added } = startCapture(undefined, { fakeClock: true });

  for (const field of fields) {
    document.dispatch(guardedEvent('focusin', field));
    document.dispatch(guardedEvent('input', field));
    document.dispatch(guardedEvent('focusout', field));
  }
  registered.stop();

  assert.equal(added.length, 15);
  assert.deepEqual(
    [...new Set(added.map((entry) => entry.record.type))].sort(),
    ['field_change', 'focus_in', 'focus_out'],
  );
  for (const { record } of added) {
    assert.equal(record.element.text, null);
    assert.deepEqual(record.data, {});
  }
});

test('records at most one field_change per second for each field', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  const name = el('input', { id: 'name' });
  const email = el('input', { id: 'email' });
  const changes = () => added.filter((entry) => entry.record.type === 'field_change');

  document.dispatch({ type: 'input', target: name });
  await timers.advance(300);
  document.dispatch({ type: 'input', target: name });
  document.dispatch({ type: 'input', target: email });
  assert.deepEqual(changes().map((entry) => entry.record.element.id), ['name', 'email']);

  await timers.advance(699);
  document.dispatch({ type: 'input', target: name });
  assert.equal(changes().length, 2);
  await timers.advance(1);
  document.dispatch({ type: 'input', target: name });
  registered.stop();

  assert.equal(changes().length, 3);
  assert.equal(changes()[2].record.element.id, 'name');
});

test('records form_submit with the form as the element and no text from textareas', () => {
  const { document, added } = startCapture({ task_id: 2 });
  const plain = el('form', { id: 'signup-form' }, { text: 'Registro' });
  const withTextarea = el('form', { id: 'comment-form' }, { children: [el('textarea', {}, { text: 'borrador guardado' })] });

  document.dispatch({ type: 'submit', target: plain });
  document.dispatch({ type: 'submit', target: withTextarea });
  document.dispatch({ type: 'submit', target: { nodeType: 9 } });
  registered.stop();

  assert.equal(added.length, 2);
  assert.deepEqual(added.map((entry) => entry.record.type), ['form_submit', 'form_submit']);
  assert.equal(added[0].record.element.tag, 'form');
  assert.equal(added[0].record.element.role, 'form');
  assert.equal(added[0].record.element.text, null);
  assert.equal(added[1].record.element.text, null);
  assert.equal(added[0].record.task_id, 2);
  assert.deepEqual(added[0].record.data, {});
});

/** Campo con un estado de validación nativo falso. */
function invalidField(validity, attributes = { type: 'text', id: 'name' }) {
  const field = el('input', attributes);
  field.validity = validity;
  return field;
}

const errors = (added) =>
  added.filter((entry) => entry.record.type === 'validation_error').map((entry) => entry.record.data.error_type);

test('records one native validation_error per invalid field with the type from the contract', () => {
  const { document, added } = startCapture({ task_id: 3 });
  const field = invalidField({ valueMissing: true });

  document.dispatch({ type: 'invalid', target: field });
  registered.stop();

  assert.equal(added.length, 1);
  assert.equal(added[0].record.type, 'validation_error');
  assert.deepEqual(added[0].record.data, { error_type: 'value_missing' });
  assert.equal(added[0].record.element.id, 'name');
  assert.equal(added[0].record.element.text, null);
  assert.equal(added[0].record.task_id, 3);
});

test('maps every native validity flag to its contract type, in the order of the contract', () => {
  const { enums } = UX.contracts;
  const native = enums.validation_error_type.filter((type) => !['aria_invalid', 'visible_message'].includes(type));
  assert.ok(native.length >= 10);
  const { document, added } = startCapture();

  for (const type of native) {
    const flag = type.replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
    document.dispatch({ type: 'invalid', target: invalidField({ [flag]: true }) });
  }
  // Con varios problemas a la vez se registra el primero de la enumeración.
  document.dispatch({ type: 'invalid', target: invalidField({ customError: true, tooShort: true }) });
  registered.stop();

  assert.deepEqual(errors(added), [...native, 'too_short']);
});

test('ignores an invalid event with no problem flag or from a non-element', () => {
  const { document, added } = startCapture();

  document.dispatch({ type: 'invalid', target: invalidField({}) });
  document.dispatch({ type: 'invalid', target: { nodeType: 9 } });
  registered.stop();

  assert.equal(added.length, 0);
});

test('observes only the aria-invalid attribute of the whole document', () => {
  const { stop } = startCapture();
  const [observer] = FakeMutationObserver.instances;

  assert.equal(observer.connected, true);
  assert.deepEqual(observer.options, { attributes: true, attributeFilter: ['aria-invalid'], subtree: true });
  stop();
  assert.equal(observer.connected, false);
});

test('records aria_invalid once when a field becomes invalid and again only after it was fixed', () => {
  const { added, stop } = startCapture();
  const [observer] = FakeMutationObserver.instances;
  const field = el('input', { type: 'text', id: 'email', 'aria-invalid': 'true' });

  observer.callback([{ target: field }]);
  observer.callback([{ target: field }]);
  field.attributes['aria-invalid'] = 'false';
  observer.callback([{ target: field }]);
  field.attributes['aria-invalid'] = 'true';
  observer.callback([{ target: field }]);
  stop();

  assert.deepEqual(errors(added), ['aria_invalid', 'aria_invalid']);
  assert.equal(added[0].record.element.id, 'email');
});

test('records visible_message after leaving a field whose error message is shown', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  const message = el('span', { id: 'email-error' }, { text: 'Escribe un correo válido' });
  document.ids['email-error'] = message;
  const field = el('input', { type: 'email', id: 'email', 'aria-errormessage': 'email-error' });

  document.dispatch({ type: 'focusout', target: field });
  await timers.advance(199);
  assert.deepEqual(errors(added), []);
  await timers.advance(1);
  assert.deepEqual(errors(added), ['visible_message']);

  // Mientras el mensaje siga ahí no se repite; si desaparece y vuelve, sí.
  document.dispatch({ type: 'focusout', target: field });
  await timers.advance(200);
  assert.deepEqual(errors(added), ['visible_message']);
  message.hidden = true;
  document.dispatch({ type: 'focusout', target: field });
  await timers.advance(200);
  message.hidden = false;
  document.dispatch({ type: 'focusout', target: field });
  await timers.advance(200);
  registered.stop();

  assert.deepEqual(errors(added), ['visible_message', 'visible_message']);
});

test('uses aria-describedby only for messages that look like errors, and ignores hidden or empty ones', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  const check = async (describedBy) => {
    document.dispatch({ type: 'focusout', target: el('input', { type: 'text', 'aria-describedby': describedBy }) });
    await timers.advance(200);
  };
  document.ids.help = el('span', { id: 'help' }, { text: 'Mínimo 8 caracteres' });
  document.ids.alert = el('span', { id: 'alert', role: 'alert' }, { text: 'Campo obligatorio' });
  document.ids['pw-error'] = el('span', { id: 'pw-error' }, { text: 'Muy corta' });
  document.ids['empty-error'] = el('span', { id: 'empty-error' });
  document.ids['hidden-error'] = el('span', { id: 'hidden-error' }, { text: 'Oculto' });
  document.ids['hidden-error'].hidden = true;

  await check('help');
  await check('empty-error');
  await check('hidden-error');
  await check('missing-id');
  assert.deepEqual(errors(added), []);
  await check('alert');
  await check('pw-error');
  registered.stop();

  assert.deepEqual(errors(added), ['visible_message', 'visible_message']);
});

test('records no error for a field left with no aria-invalid and no message', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  document.dispatch({ type: 'focusout', target: el('input', { type: 'text' }) });
  await timers.advance(300);
  registered.stop();

  assert.deepEqual(errors(added), []);
});

test('stop cancels the checks that were waiting after leaving a field', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  document.ids['e-error'] = el('span', { id: 'e-error' }, { text: 'Error' });

  document.dispatch({ type: 'focusout', target: el('input', { type: 'text', 'aria-errormessage': 'e-error' }) });
  assert.equal(timers.pending(), 2);
  registered.stop();

  assert.equal(timers.pending(), 0);
  await timers.advance(500);
  assert.deepEqual(errors(added), []);
});

test('never takes text from elements with a text input role, such as custom text boxes', () => {
  const widget = el('div', { role: 'textbox', 'aria-invalid': 'true' }, { text: 'lo que escribio' });
  assert.equal(describeByClick(widget).text, null);
  assert.equal(describeByClick(el('div', { role: 'combobox' }, { text: 'valor' })).text, null);
  assert.equal(describeByClick(el('div', { role: 'button' }, { text: 'Pagar' })).text, 'Pagar');
});

/** Los registros `click_response` entregados, solo sus datos. */
const responses = (added) =>
  added.filter((entry) => entry.record.type === 'click_response').map((entry) => entry.record.data);

/** Observadores creados por los clics (el primero es el de `aria-invalid`). */
const clickObservers = () => FakeMutationObserver.instances.slice(1);

test('records a click_response joined to its click by click_t when the page changes', async () => {
  const { added, click, timers } = startCapture({ task_id: 9 }, { fakeClock: true });

  await timers.advance(40);
  click(el('button'));
  const [observer] = clickObservers();
  assert.deepEqual(observer.options, { childList: true, attributes: true, characterData: true, subtree: true });
  await timers.advance(100);
  observer.emit(3);
  await timers.advance(300);
  observer.emit(2);
  await timers.advance(1099);
  assert.deepEqual(responses(added), []);
  await timers.advance(1);
  registered.stop();

  assert.deepEqual(responses(added), [{ click_t: 40, mutation_count: 5, navigated: false }]);
  const response = added.find((entry) => entry.record.type === 'click_response').record;
  assert.equal(response.t, 1540);
  assert.equal(response.task_id, 9);
  assert.ok(!('x' in response) && !('element' in response));
  assert.equal(added[0].record.t, responses(added)[0].click_t);
  assert.equal(observer.connected, false);
});

test('records nothing for a click the page does not respond to, and disconnects the observer', async () => {
  const { added, click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('button'));
  const [observer] = clickObservers();
  assert.equal(observer.connected, true);
  await timers.advance(1500);
  registered.stop();

  assert.equal(added.length, 1);
  assert.deepEqual(responses(added), []);
  assert.equal(observer.connected, false);
  assert.equal(timers.pending(), 0);
});

test('does not count changes that happen after the wait', async () => {
  const { added, click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('button'));
  const [observer] = clickObservers();
  await timers.advance(1500);
  observer.emit(4);
  await timers.advance(100);
  registered.stop();

  assert.deepEqual(responses(added), []);
});

test('counts the changes the observer had not delivered yet when the wait ends', async () => {
  const { added, click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('button'));
  clickObservers()[0].queued = [{}, {}];
  await timers.advance(1500);
  registered.stop();

  assert.deepEqual(responses(added), [{ click_t: 0, mutation_count: 2, navigated: false }]);
});

test('records navigated when the address changes without the page changing', async () => {
  const { added, click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('a', { href: '#formulario' }));
  globalThis.location.href = 'https://shop.local/cart#formulario';
  await timers.advance(1500);
  registered.stop();

  assert.deepEqual(responses(added), [{ click_t: 0, mutation_count: 0, navigated: true }]);
});

test('records navigated at once, and flushes the batcher, when the page unloads during the wait', async () => {
  const { added, click, timers, flushes, pageHide } = startCapture(undefined, { fakeClock: true });

  click(el('a', { href: '/otra' }));
  await timers.advance(200);
  clickObservers()[0].emit(1);
  pageHide();

  assert.deepEqual(responses(added), [{ click_t: 0, mutation_count: 1, navigated: true }]);
  assert.deepEqual(flushes, [200]);
  assert.equal(timers.pending(), 1);
  await timers.advance(2000);
  assert.equal(responses(added).length, 1);
  registered.stop();
});

test('does not flush on page hide when no click is waiting', () => {
  const { flushes, pageHide } = startCapture();

  pageHide();

  assert.deepEqual(flushes, []);
  registered.stop();
});

test('only a simple click is watched, not dblclick or contextmenu', async () => {
  const { click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('button'), 'dblclick');
  click(el('button'), 'contextmenu');

  assert.equal(clickObservers().length, 0);
  assert.equal(timers.pending(), 1);
  registered.stop();
});

test('joins each click_response to its own click when clicks come one after another', async () => {
  const { added, click, timers } = startCapture(undefined, { fakeClock: true });

  click(el('button'));
  await timers.advance(100);
  click(el('button'));
  await timers.advance(100);
  click(el('button'));
  const [first, second, third] = clickObservers();
  second.emit(7);
  third.emit(1);
  await timers.advance(1500);
  registered.stop();

  assert.deepEqual(responses(added).map((data) => [data.click_t, data.mutation_count]), [[100, 7], [200, 1]]);
  assert.equal(first.connected, false);
});

test('stop disconnects the observers, cancels the waits and unhooks pagehide', async () => {
  const { added, click, timers, pageListeners } = startCapture(undefined, { fakeClock: true });

  click(el('button'));
  click(el('button'));
  clickObservers().forEach((observer) => observer.emit(2));
  assert.equal(timers.pending(), 3);
  registered.stop();

  assert.ok(clickObservers().every((observer) => !observer.connected));
  assert.equal(timers.pending(), 0);
  assert.equal(pageListeners.size, 0);
  await timers.advance(3000);
  assert.deepEqual(responses(added), []);
});

test('reads the wait from the configuration and refuses to start without a positive one', async () => {
  const config = { ...CAPTURE_CONFIG, click_response_wait_ms: 300 };
  const { added, click, timers } = startCapture(undefined, { config, fakeClock: true });

  click(el('button'));
  clickObservers()[0].emit(1);
  await timers.advance(299);
  assert.equal(responses(added).length, 0);
  await timers.advance(1);
  assert.equal(responses(added).length, 1);
  registered.stop();

  for (const wait of [undefined, 0, 'a']) {
    globalThis.document = createFakeDocument();
    const context = {
      clock: { now: () => 0 },
      batcher: { add() {}, flush: async () => {} },
      session: { get: () => null },
      config: { capture: { ...CAPTURE_CONFIG, click_response_wait_ms: wait } },
      contracts: UX.contracts,
    };
    assert.throws(() => registered.start(context), /click_response_wait_ms must be a positive number/);
    registered.stop();
  }
});

/** Los registros `screen_change` entregados, con la pantalla que llevan. */
const screens = (added) =>
  added.filter((entry) => entry.record.type === 'screen_change').map((entry) => entry.record.screen);

test('records the current screen when the capture starts', () => {
  const { initial } = startCapture({ task_id: 5 });
  registered.stop();

  assert.equal(initial.length, 1);
  assert.deepEqual(initial[0].record, {
    t: 1791380123456.2,
    type: 'screen_change',
    data: {},
    screen: { url: 'https://shop.local/cart', title: 'Carrito' },
    task_id: 5,
  });
});

test('records a screen change within 250 ms of the address changing, with the title of that moment', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  await timers.advance(100);
  globalThis.location.href = 'https://shop.local/checkout';
  document.title = 'Pago';
  await timers.advance(149);
  assert.deepEqual(screens(added), []);
  await timers.advance(1);
  registered.stop();

  assert.deepEqual(screens(added), [{ url: 'https://shop.local/checkout', title: 'Pago' }]);
  assert.deepEqual(added[0].record.data, {});
  assert.ok(!('x' in added[0].record) && !('element' in added[0].record));
});

test('records nothing while the address stays the same, even if the title changes', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  document.title = 'Otro título';
  await timers.advance(1000);
  registered.stop();

  assert.deepEqual(screens(added), []);
});

test('counts a change of the hash as a screen change', async () => {
  const { added, timers } = startCapture(undefined, { fakeClock: true });

  globalThis.location.href = 'https://shop.local/cart#resumen';
  await timers.advance(250);
  registered.stop();

  assert.deepEqual(screens(added).map((screen) => screen.url), ['https://shop.local/cart#resumen']);
});

test('popstate and hashchange are checked after a short pause, without waiting for the next poll', async () => {
  for (const type of ['popstate', 'hashchange']) {
    const { document, added, timers, pageListeners } = startCapture(undefined, { fakeClock: true });

    await timers.advance(10);
    globalThis.location.href = `https://shop.local/${type}`;
    document.title = type;
    pageListeners.get(type)({ type });
    await timers.advance(49);
    assert.deepEqual(screens(added), []);
    await timers.advance(1);
    registered.stop();

    assert.deepEqual(screens(added), [{ url: `https://shop.local/${type}`, title: type }]);
  }
});

test('records one screen change per different address and none for a repeated one', async () => {
  const { added, timers, pageListeners } = startCapture(undefined, { fakeClock: true });

  globalThis.location.href = 'https://shop.local/a';
  await timers.advance(250);
  pageListeners.get('popstate')({ type: 'popstate' });
  await timers.advance(300);
  globalThis.location.href = 'https://shop.local/b';
  await timers.advance(250);
  globalThis.location.href = 'https://shop.local/cart';
  await timers.advance(250);
  registered.stop();

  assert.deepEqual(screens(added).map((screen) => screen.url), [
    'https://shop.local/a',
    'https://shop.local/b',
    'https://shop.local/cart',
  ]);
});

test('uses the active task and stop cancels the checks and unhooks popstate and hashchange', async () => {
  const { added, timers, pageListeners } = startCapture({ task_id: 8 }, { fakeClock: true });
  assert.deepEqual([...pageListeners.keys()].sort(), ['hashchange', 'pagehide', 'popstate']);

  globalThis.location.href = 'https://shop.local/a';
  await timers.advance(750);
  assert.equal(added[0].record.task_id, 8);
  registered.stop();

  assert.equal(pageListeners.size, 0);
  assert.equal(timers.pending(), 0);
  globalThis.location.href = 'https://shop.local/b';
  await timers.advance(1000);
  assert.equal(screens(added).length, 1);
});

/**
 * Provoca un registro de cada tipo de evento de la captura.
 *
 * @param {object|null} state - Estado de la sesión que ve el módulo (se puede mutar en la prueba).
 * @returns {Promise<object[]>} Todos los registros entregados, incluida la pantalla inicial.
 */
async function exerciseEveryEvent(state) {
  const { document, added, initial, click, timers, pageListeners } = startCapture(state, { fakeClock: true });
  const field = el('input', { type: 'text', id: 'name' });
  field.validity = { valueMissing: true };

  click(el('button'), 'click');
  click(el('button'), 'dblclick');
  click(el('button'), 'contextmenu');
  clickObservers().forEach((observer) => observer.emit(1));
  move(document, 10, 10);
  scrollTo(document, 0, 120);
  selectText('texto');
  selectionChanged(document);
  document.dispatch({ type: 'focusin', target: field });
  document.dispatch({ type: 'input', target: field });
  document.dispatch({ type: 'submit', target: el('form') });
  document.dispatch({ type: 'invalid', target: field });
  FakeMutationObserver.instances[0].callback([{ target: el('input', { 'aria-invalid': 'true' }) }]);
  document.ids.err = el('span', { id: 'err' }, { text: 'Error' });
  document.dispatch({ type: 'focusout', target: el('input', { type: 'text', 'aria-errormessage': 'err' }) });
  globalThis.location.href = 'https://shop.local/other';
  pageListeners.get('popstate')({ type: 'popstate' });
  await timers.advance(2000);
  registered.stop();
  return [...initial, ...added].map((entry) => entry.record);
}

test('marks a record of every event type with the active task, or null when there is none', async () => {
  const expected = UX.contracts.enums.event_type.filter((type) => type !== 'camera_gap');

  for (const [state, taskId] of [[{ task_id: 7 }, 7], [{ task_id: null }, null], [null, null]]) {
    const records = await exerciseEveryEvent(state);

    assert.deepEqual([...new Set(records.map((record) => record.type))].sort(), [...expected].sort());
    for (const record of records) {
      assert.equal(record.task_id, taskId, `${record.type} must carry task_id ${taskId}`);
    }
    // Los dos tipos de validación diferida se registraron además de la nativa.
    const kinds = records.filter((record) => record.type === 'validation_error').map((record) => record.data.error_type);
    assert.deepEqual(kinds.sort(), ['aria_invalid', 'value_missing', 'visible_message']);
  }
});

test('the response to a click keeps the task of the click even if the task ends before it is delivered', async () => {
  const state = { task_id: 3 };
  const { added, click, timers } = startCapture(state, { fakeClock: true });

  click(el('button', { id: 'confirm' }));
  clickObservers()[0].emit(2);
  await timers.advance(300);
  state.task_id = null;
  await timers.advance(1200);
  click(el('button'));
  registered.stop();

  const click1 = added.find((entry) => entry.record.type === 'click').record;
  const response = added.find((entry) => entry.record.type === 'click_response').record;
  assert.equal(click1.task_id, 3);
  assert.equal(response.task_id, 3);
  assert.equal(response.data.click_t, click1.t);
  assert.equal(added.filter((entry) => entry.record.type === 'click').at(-1).record.task_id, null);
});

test('delayed records keep the task of the moment they were caused by', async () => {
  const state = { task_id: 3 };
  const { document, added, timers } = startCapture(state, { fakeClock: true });
  const typeOf = (type) => added.filter((entry) => entry.record.type === type).map((entry) => entry.record.task_id);

  // Cursor y scroll: el segundo valor espera su turno y la tarea cambia mientras tanto.
  move(document, 1, 1);
  scrollTo(document, 0, 10);
  await timers.advance(5);
  move(document, 2, 2);
  scrollTo(document, 0, 20);
  state.task_id = 4;
  await timers.advance(100);
  // Selección: la tarea cambia durante la espera de 300 ms.
  state.task_id = 5;
  selectText('abc');
  selectionChanged(document);
  state.task_id = 6;
  await timers.advance(300);
  // Mensaje de error visible: la tarea cambia durante la espera de 200 ms.
  document.ids.err = el('span', { id: 'err' }, { text: 'Error' });
  state.task_id = 8;
  document.dispatch({ type: 'focusout', target: el('input', { type: 'text', 'aria-errormessage': 'err' }) });
  state.task_id = 9;
  await timers.advance(200);
  registered.stop();

  assert.deepEqual(typeOf('mousemove'), [3, 3]);
  assert.deepEqual(typeOf('scroll'), [3, 3]);
  assert.deepEqual(typeOf('selection'), [5]);
  assert.deepEqual(typeOf('validation_error'), [8]);
});

test('sees the task the panel sets through the real session state, without restarting the capture', async () => {
  const modes = UX.contracts.enums.session_mode;
  const world = createFakeWorld();
  const panel = UX.createSession({ platform: world.platform(), modes });
  const tab = UX.createSession({ platform: world.platform({ tabId: 42 }), modes });
  await panel.start({ session_id: 7, mode: 'guided', study_id: 1, tab_id: 42 });
  await tab.reload();
  const { added, click } = startCapture(undefined, { liveSession: { get: tab.get } });
  const lastTask = () => added.at(-1).record.task_id;

  click(el('button'));
  assert.equal(lastTask(), null);
  await panel.update({ task_id: 3 });
  await settle();
  click(el('button'));
  assert.equal(lastTask(), 3);
  await panel.update({ task_id: null });
  await settle();
  click(el('button'));
  assert.equal(lastTask(), null);
  registered.stop();
});

test('records text only for interactive elements, never for containers, paragraphs or headings', () => {
  assert.equal(describeByClick(el('button', {}, { text: 'Pagar' })).text, 'Pagar');
  assert.equal(describeByClick(el('a', { href: '/x' }, { text: 'Ir al carrito' })).text, 'Ir al carrito');
  assert.equal(describeByClick(el('div', { role: 'tab' }, { text: 'Resumen' })).text, 'Resumen');
  for (const tag of ['div', 'p', 'h2', 'main', 'section', 'span', 'form', 'li']) {
    assert.equal(describeByClick(el(tag, {}, { text: 'mensaje que escribi hace un momento' })).text, null, tag);
  }
});

test('never takes text from, or records a selection inside, a custom text box or anything holding one', async () => {
  const secret = 'CANARIO-EDITOR-1';
  const inner = el('button', {}, { text: secret });
  const editor = el('div', { role: 'textbox' }, { children: [inner] });
  const toolbar = el('button', { id: 'wrap' }, { text: secret, children: [el('div', { role: 'searchbox' })] });

  assert.equal(describeByClick(inner).text, null);
  assert.equal(describeByClick(editor).text, null);
  assert.equal(describeByClick(toolbar).text, null);

  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  selectText(secret, inner);
  selectionChanged(document);
  await timers.advance(300);
  registered.stop();
  assert.equal(added.length, 0);
});

test('redacts the value of sensitive url parameters in every record and keeps the rest', () => {
  const cases = [
    ['https://shop.local/buscar?q=CANARIO&view=cart', 'https://shop.local/buscar?q=redacted&view=cart'],
    ['https://shop.local/?Q=Hola&Query=x&page=2', 'https://shop.local/?Q=redacted&Query=redacted&page=2'],
    ['https://shop.local/?%71=hola&id=3', 'https://shop.local/?%71=redacted&id=3'],
    ['https://shop.local/?view=cart&id=1', 'https://shop.local/?view=cart&id=1'],
    ['https://shop.local/?q&flag=1', 'https://shop.local/?q&flag=1'],
    ['https://shop.local/?q=#top', 'https://shop.local/?q=redacted#top'],
    ['https://shop.local/cb#access_token=CANARIO&state=ok', 'https://shop.local/cb#access_token=redacted&state=ok'],
    ['https://shop.local/#/buscar?q=CANARIO&page=2', 'https://shop.local/#/buscar?q=redacted&page=2'],
    ['https://shop.local/#/ruta', 'https://shop.local/#/ruta'],
    ['https://shop.local/#seccion', 'https://shop.local/#seccion'],
    ['https://user:CANARIO@shop.local/x?token=CANARIO', 'https://shop.local/x?token=redacted'],
    ['https://shop.local/?%E0%A4%A=1&q=x', 'https://shop.local/?%E0%A4%A=1&q=redacted'],
  ];
  for (const [href, expected] of cases) {
    const { document, added, click, initial } = startCapture();
    globalThis.location.href = href;
    click(el('button'));
    move(document, 1, 1);
    registered.stop();

    assert.equal(added[0].record.screen.url, expected, href);
    assert.equal(added[1].record.screen.url, expected, href);
    assert.ok(!JSON.stringify([...initial, ...added]).includes('CANARIO'), href);
  }
});

test('still records a screen change when only a redacted parameter changes', async () => {
  const { added, timers } = startCapture(undefined, { fakeClock: true });

  globalThis.location.href = 'https://shop.local/buscar?q=primera';
  await timers.advance(250);
  globalThis.location.href = 'https://shop.local/buscar?q=segunda';
  await timers.advance(250);
  registered.stop();

  assert.deepEqual(screens(added).map((screen) => screen.url), [
    'https://shop.local/buscar?q=redacted',
    'https://shop.local/buscar?q=redacted',
  ]);
});

/** Un campo de cada clase, con su contenido y con un valor que no se debe poder leer. */
function privacyFixture(canary) {
  const guard = (node) =>
    Object.defineProperty(node, 'value', {
      get() {
        throw new Error('the value of a field must never be read');
      },
    });
  const named = (tag, attributes, text) => guard(el(tag, attributes, { text: `${canary} ${text}` }));
  const textbox = el('div', { role: 'textbox' }, { children: [el('span', {}, { text: `${canary} editor` })] });
  const plain = named('input', { type: 'text', id: 'name' }, 'nombre');
  const password = named('input', { type: 'password', id: 'password' }, 'clave');
  const area = named('textarea', { id: 'comments' }, 'comentario');
  const select = named('select', { id: 'country' }, 'pais');
  const editable = named('div', { contenteditable: 'true', id: 'rich' }, 'enriquecido');
  const hidden = named('input', { type: 'hidden', id: 'csrf' }, 'oculto');
  const label = el('label', {}, { text: `${canary} etiqueta`, children: [guard(el('input', { type: 'text', id: 'wrapped' }))] });
  const preview = el('div', { id: 'preview' }, { text: `${canary} vista previa` });
  const form = el('form', { id: 'f' }, { text: canary, children: [plain, password, area, select, editable, hidden, label, textbox] });
  // Autocompletado: la sugerencia repite lo escrito y la lista está fuera del campo (ARIA 1.2).
  const search = el('input', { type: 'search', id: 'buscador', role: 'combobox', 'aria-controls': 'sugerencias' });
  const suggestion = el('li', { role: 'option', id: 'sugerencia-1' }, { text: `${canary} sugerencia` });
  const list = el('ul', { role: 'listbox', id: 'sugerencias' }, { children: [suggestion] });
  return {
    form,
    fields: [plain, password, area, select, editable, hidden, label.children[0], textbox, search],
    extras: [preview, form, label, suggestion],
    page: [form, search, list],
  };
}

test('no event type ever lets a typed value reach a record, whatever the field', async () => {
  const canary = 'CANARIO-ESCRITO-731';
  const { form, fields, extras, page } = privacyFixture(canary);
  const { document, added, initial, click, timers, pageListeners } = startCapture(undefined, { fakeClock: true });
  document.add(...page);
  globalThis.location.href = `https://shop.local/buscar?q=${canary}&view=cart#access_token=${canary}`;

  for (const field of [...fields, ...extras]) {
    field.validity = { valueMissing: true, customError: true };
    click(field, 'click');
    click(field, 'dblclick');
    click(field, 'contextmenu');
    document.dispatch(guardedEvent('focusin', field));
    document.dispatch(guardedEvent('input', field));
    document.dispatch(guardedEvent('focusout', field));
    document.dispatch(guardedEvent('invalid', field));
    document.activeElement = field;
    selectText(`${canary} seleccionado`, field);
    selectionChanged(document);
    await timers.advance(1000);
    document.activeElement = null;
    FakeMutationObserver.instances[0].callback([{ target: field }]);
  }
  document.dispatch(guardedEvent('submit', form));
  pageListeners.get('popstate')({ type: 'popstate' });
  await timers.advance(2000);
  registered.stop();

  const records = [...initial, ...added].map((entry) => entry.record);
  assert.ok(records.length > 40, `only ${records.length} records were produced`);
  const everything = JSON.stringify(records);
  assert.ok(!everything.includes(canary), 'a typed value reached a record');
  assert.ok(!everything.includes('CANARIO'));
});

test('never takes text from an interactive element that holds a textarea with a saved draft', () => {
  const draft = 'CANARIO-BORRADOR-9';
  const holder = el('div', { onclick: '' }, { text: 'Comentar', children: [el('textarea', {}, { text: draft })] });

  assert.equal(describeByClick(holder).text, null);
  assert.equal(describeByClick(el('button', {}, { text: 'Comentar' })).text, 'Comentar');
});

test('does not record a selection that starts or ends inside a field, a custom text box or an editable zone', async () => {
  const outside = el('h2', {}, { text: 'Titulo' });
  const inside = [el('div', { role: 'textbox' }), el('div', { contenteditable: 'true' }), el('textarea')];

  for (const field of inside) {
    for (const [anchor, focus] of [[outside, field], [field, outside]]) {
      const { document, added, timers } = startCapture(undefined, { fakeClock: true });

      selectText('CANARIO-ARRASTRE texto de la pagina', anchor, focus);
      selectionChanged(document);
      await timers.advance(300);
      registered.stop();

      assert.equal(added.length, 0);
    }
  }
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });
  selectText('texto normal', outside, el('p'));
  selectionChanged(document);
  await timers.advance(300);
  registered.stop();
  assert.equal(added.length, 1);
});

test('empties the title when the url had to be redacted, and keeps it otherwise', async () => {
  const { document, added, click, timers } = startCapture(undefined, { fakeClock: true });
  document.title = 'Resultados de CANARIO-TITULO-5';

  globalThis.location.href = 'https://shop.local/buscar?q=CANARIO-TITULO-5';
  click(el('button'));
  move(document, 1, 1);
  await timers.advance(250);
  globalThis.location.href = 'https://shop.local/carrito?view=cart';
  document.title = 'Carrito';
  click(el('button'));
  await timers.advance(250);
  registered.stop();

  const titles = added.map((entry) => entry.record.screen.title);
  assert.deepEqual(titles.slice(0, 3), ['', '', '']);
  assert.ok(titles.slice(3).every((title) => title === 'Carrito'), titles.join('|'));
  assert.deepEqual(screens(added)[0], { url: 'https://shop.local/buscar?q=redacted', title: '' });
  assert.ok(!JSON.stringify(added).includes('CANARIO'));
});

test('does not read the text of an interactive element holding a huge amount of text', () => {
  const huge = el('a', { href: '/x' }, { text: 'palabra '.repeat(200) });
  const large = el('a', { href: '/x' }, { text: `Título ${'x'.repeat(980)}` });

  assert.equal(describeByClick(huge).text, null);
  assert.equal(describeByClick(large).text.length, 50);
  assert.ok(describeByClick(large).text.startsWith('Título xxx'));
});

/** Cambia la dirección de la página y, si se da, su título. */
function navigateTo(document, href, title) {
  globalThis.location.href = href;
  if (title !== undefined) {
    document.title = title;
  }
}

test('waits for the title of a single-page app and records the screen change with the final title and the detection time', async () => {
  const { document, added, timers } = startCapture({ task_id: 4 }, { fakeClock: true });

  await timers.advance(120);
  navigateTo(document, 'https://shop.local/instalacion');
  await timers.advance(130); // la revisión de las 250 ms detecta el cambio
  assert.deepEqual(screens(added), []);
  await timers.advance(100);
  document.title = 'Instalación'; // la página actualiza el título un instante después de la dirección
  await timers.advance(50);
  registered.stop();

  assert.deepEqual(screens(added), [{ url: 'https://shop.local/instalacion', title: 'Instalación' }]);
  const record = added[0].record;
  assert.equal(record.t, 250);
  assert.equal(record.task_id, 4);
  assert.equal(added[0].at, 400); // la siguiente revisión del título, cada 50 ms desde la detección
});

test('records at once when the title already changed together with the address', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  navigateTo(document, 'https://shop.local/carrito', 'Carrito de compras');
  await timers.advance(250);

  assert.deepEqual(screens(added), [{ url: 'https://shop.local/carrito', title: 'Carrito de compras' }]);
  assert.equal(added[0].at, 250);
  registered.stop();
});

test('records after at most 500 ms when the title never changes, keeping the detection time', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  navigateTo(document, 'https://shop.local/otra');
  await timers.advance(250);
  await timers.advance(499);
  assert.deepEqual(screens(added), []);
  await timers.advance(1);
  registered.stop();

  assert.deepEqual(screens(added), [{ url: 'https://shop.local/otra', title: 'Carrito' }]);
  assert.equal(added[0].record.t, 250);
  assert.equal(added[0].at, 750);
});

test('records the older pending screen when a new address arrives, in order and with its own address', async () => {
  const { document, added, timers } = startCapture(undefined, { fakeClock: true });

  navigateTo(document, 'https://shop.local/a');
  await timers.advance(250);
  await timers.advance(100);
  navigateTo(document, 'https://shop.local/b', 'Pantalla B');
  await timers.advance(150);
  registered.stop();

  assert.deepEqual(screens(added).map((screen) => screen.url), ['https://shop.local/a', 'https://shop.local/b']);
  assert.equal(screens(added)[1].title, 'Pantalla B');
  assert.deepEqual(added.map((entry) => entry.record.t), [250, 500]);
});

test('does not lose a screen change that is waiting for its title when the capture stops or the page unloads', async () => {
  for (const finish of ['stop', 'pagehide']) {
    const { document, added, timers, pageHide, flushes } = startCapture({ task_id: 6 }, { fakeClock: true });

    navigateTo(document, 'https://shop.local/ultima');
    await timers.advance(250);
    assert.deepEqual(screens(added), []);
    if (finish === 'stop') {
      registered.stop();
    } else {
      pageHide();
      assert.deepEqual(flushes, [250]);
      registered.stop();
    }

    assert.deepEqual(screens(added).map((screen) => screen.url), ['https://shop.local/ultima'], finish);
    assert.equal(added[0].record.task_id, 6);
    assert.equal(timers.pending(), 0);
  }
});

test('the title wait applies to popstate and redacts the address like any other record', async () => {
  const { document, added, timers, pageListeners } = startCapture(undefined, { fakeClock: true });

  navigateTo(document, 'https://shop.local/buscar?q=CANARIO-5', 'Resultados de CANARIO-5');
  pageListeners.get('popstate')({ type: 'popstate' });
  await timers.advance(50);
  registered.stop();

  assert.deepEqual(screens(added), [{ url: 'https://shop.local/buscar?q=redacted', title: '' }]);
  assert.ok(!JSON.stringify(added).includes('CANARIO'));
});

/** Un buscador con su lista de sugerencias; `link` dice cómo se enlazan. */
function suggestionsPage(document, link, { optionText = 'zapatos deportivos' } = {}) {
  const option = el('li', { role: 'option', id: 'op-1' }, { text: optionText });
  const other = el('li', { role: 'option', id: 'op-2' }, { text: 'zapatillas' });
  const list = el('ul', { role: 'listbox', id: 'sugerencias' }, { children: [option, other] });
  const attributes = { type: 'search', id: 'q' };
  if (link === 'controls') {
    attributes['aria-controls'] = 'sugerencias';
  } else if (link === 'owns') {
    attributes['aria-owns'] = 'sugerencias';
  } else if (link === 'owns-among-others') {
    attributes['aria-owns'] = 'otra-lista sugerencias tercera';
  } else if (link === 'active') {
    attributes['aria-activedescendant'] = 'op-1';
  }
  const input = el('input', attributes);
  document.add(input, list);
  return { input, list, option, other };
}

test('records no text for a suggestion of a list that a field controls or owns by id', () => {
  for (const link of ['controls', 'owns', 'owns-among-others']) {
    const { document, added, click } = startCapture();
    const { option, other } = suggestionsPage(document, link);

    click(option);
    click(other);
    registered.stop();

    const clicks = added.filter((entry) => entry.record.type === 'click').map((entry) => entry.record.element);
    assert.deepEqual(clicks.map((element) => [element.role, element.interactive, element.text]), [['option', true, null], ['option', true, null]], link);
    assert.ok(!JSON.stringify(added).includes('zapat'), link);
  }
});

test('records no text for the suggestions when a field names one of them as its active descendant', () => {
  const { document, added, click } = startCapture();
  const { option, other, list } = suggestionsPage(document, 'active');

  click(other);
  registered.stop();

  assert.equal(added[0].record.element.text, null);
  assert.ok(list.contains(option));
});

test('records no text for suggestions that share their label with a text field, even when several lists repeat one id', () => {
  const { document, added, click } = startCapture();
  const field = el('input', { type: 'text', id: 'docsearch-input', 'aria-labelledby': 'docsearch-label', 'aria-controls': 'no-existe-1 no-existe-2' });
  const lists = [0, 1, 2].map((group) =>
    el('ul', { role: 'listbox', id: 'docsearch-list', 'aria-labelledby': 'docsearch-label' }, {
      children: [el('li', { role: 'option', id: `docsearch-hits${group}-item-0` }, { text: `useState ${group}` })],
    }),
  );
  document.add(el('label', { id: 'docsearch-label' }), field, ...lists);

  lists.forEach((list) => click(list.children[0]));
  registered.stop();

  assert.deepEqual(added.map((entry) => entry.record.element.text), [null, null, null]);
});

test('keeps the text of the options of a list that no field controls, describes or labels', () => {
  const { document, added, click } = startCapture();
  const colombia = el('li', { role: 'option', id: 'co' }, { text: 'Colombia' });
  const countries = el('ul', { role: 'listbox', id: 'paises', 'aria-labelledby': 'pais-etiqueta' }, { children: [colombia, el('li', { role: 'option' }, { text: 'México' })] });
  // Elementos que NO convierten la lista en sugerencias: otra lista, un campo ajeno, y no de texto con la misma etiqueta.
  const unrelated = el('input', { type: 'text', id: 'otro', 'aria-controls': 'otra-lista', 'aria-owns': 'tercera', 'aria-activedescendant': 'en-otra-parte' });
  const checkbox = el('input', { type: 'checkbox', id: 'acepto', 'aria-labelledby': 'pais-etiqueta' });
  const elsewhere = el('li', { role: 'option', id: 'en-otra-parte' }, { text: 'Otra cosa' });
  document.add(el('span', { id: 'pais-etiqueta' }), countries, unrelated, checkbox, el('ul', { role: 'listbox', id: 'otra-lista' }, { children: [elsewhere] }));

  click(colombia);
  registered.stop();

  assert.equal(added[0].record.element.text, 'Colombia');
});

test('keeps the text of an option when the list has no id and nothing points to it', () => {
  const { document, added, click } = startCapture();
  const option = el('li', { role: 'option' }, { text: 'Rojo' });
  document.add(el('ul', { role: 'listbox' }, { children: [option] }));

  click(option);
  registered.stop();

  assert.equal(added[0].record.element.text, 'Rojo');
});

test('keeps the option text of select lists linked from a button, a select-only combobox or the list itself', () => {
  const cases = {
    // Patrón de ARIA para listas: la propia lista lleva `aria-activedescendant`.
    'own active descendant': (option) => [
      el('ul', { role: 'listbox', id: 'paises', tabindex: '0', 'aria-activedescendant': 'co' }, { children: [option] }),
    ],
    // Botón que abre la lista para elegir.
    'button controls': (option) => [
      el('button', { id: 'abrir', 'aria-haspopup': 'listbox', 'aria-controls': 'paises' }, { text: 'País' }),
      el('ul', { role: 'listbox', id: 'paises' }, { children: [option] }),
    ],
    // `combobox` de solo selección (sin campo de texto), con la misma etiqueta que la lista.
    'select-only combobox': (option) => [
      el('span', { id: 'pais-etiqueta' }),
      el('div', { role: 'combobox', id: 'selector', 'aria-controls': 'paises', 'aria-labelledby': 'pais-etiqueta', 'aria-activedescendant': 'co' }),
      el('ul', { role: 'listbox', id: 'paises', 'aria-labelledby': 'pais-etiqueta' }, { children: [option] }),
    ],
  };
  for (const [name, build] of Object.entries(cases)) {
    const { document, added, click } = startCapture();
    const option = el('li', { role: 'option', id: 'co' }, { text: 'Colombia' });
    document.add(...build(option));

    click(option);
    registered.stop();

    assert.equal(added[0].record.element.text, 'Colombia', name);
  }
});

test('records no text for suggestions of a combobox that wraps a text field (ARIA 1.1)', () => {
  const { document, added, click } = startCapture();
  const option = el('li', { role: 'option', id: 'op-1' }, { text: 'zapatos deportivos' });
  const wrapper = el('div', { role: 'combobox', 'aria-owns': 'sugerencias' }, { children: [el('input', { type: 'text', id: 'q' })] });
  document.add(wrapper, el('ul', { role: 'listbox', id: 'sugerencias' }, { children: [option] }));

  click(option);
  registered.stop();

  assert.equal(added[0].record.element.text, null);
});
