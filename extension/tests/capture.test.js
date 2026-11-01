/**
 * @file Pruebas de `content/capture.js`: descriptor del elemento y eventos de
 * clic, con un DOM mínimo en memoria (Node no trae uno y la extensión no
 * tiene dependencias).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

const { createFakeTimers } = require('./fakes.js');

const EDITABLE = '[contenteditable]:not([contenteditable="false"])';

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

  closest(selector) {
    assert.equal(selector, EDITABLE);
    for (let node = this; node; node = node.parentElement) {
      if (node.isEditable()) {
        return node;
      }
    }
    return null;
  }

  /** Solo entiende los dos selectores que usa la captura: zonas editables y `textarea`. */
  querySelector(selector) {
    const matchers = { [EDITABLE]: (node) => node.isEditable(), textarea: (node) => node.tagName === 'TEXTAREA' };
    assert.ok(selector in matchers, `unexpected selector ${selector}`);
    for (const child of this.children) {
      if (matchers[selector](child)) {
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
  return {
    title: 'Carrito',
    activeElement: null,
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
function startCapture(session = { task_id: 3 }, { config = CAPTURE_CONFIG, fakeClock = false } = {}) {
  const document = createFakeDocument();
  globalThis.document = document;
  const timers = createFakeTimers();
  const added = [];
  const real = { setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout };
  globalThis.setTimeout = timers.setTimeout;
  globalThis.clearTimeout = timers.clearTimeout;
  try {
    registered.start({
      clock: { now: fakeClock ? timers.now : () => 1791380123456.2 },
      // `at` es el momento en que se entregó el registro, distinto de `record.t`
      // cuando el muestreador retrasó un valor pendiente.
      batcher: { add: (type, record) => added.push({ type, record, at: timers.now() }) },
      session: { get: () => session },
      config: { capture: config },
    });
  } finally {
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
  }
  const click = (target, type = 'click', x = 845, y = 560) =>
    document.dispatch({ type, target, clientX: x, clientY: y });
  return { document, added, click, timers, stop: () => registered.stop() };
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
  const readonly = el('div', { contenteditable: 'false' }, { text: 'Solo lectura' });

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
    'click', 'contextmenu', 'dblclick', 'focusin', 'focusout', 'input', 'mousemove', 'scroll', 'selectionchange', 'submit',
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
    });
  } finally {
    globalThis.setTimeout = real.setTimeout;
    globalThis.clearTimeout = real.clearTimeout;
  }

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
  const config = { mousemove_hz: 10, scroll_hz: 2 };
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
  assert.equal(timers.pending(), 2);
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
function selectText(text, anchor = el('p', {}, { text })) {
  globalThis.getSelection = () => ({
    rangeCount: text === '' ? 0 : 1,
    anchorNode: { nodeType: 3, parentElement: anchor },
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
  assert.equal(timers.pending(), 1);
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
  assert.equal(added[0].record.element.text, 'Registro');
  assert.equal(added[1].record.element.text, null);
  assert.equal(added[0].record.task_id, 2);
  assert.deepEqual(added[0].record.data, {});
});
