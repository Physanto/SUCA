/**
 * @file Pruebas de `content/capture.js`: descriptor del elemento y eventos de
 * clic, con un DOM mínimo en memoria (Node no trae uno y la extensión no
 * tiene dependencias).
 */

const test = require('node:test');
const assert = require('node:assert/strict');

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

  querySelector(selector) {
    assert.equal(selector, EDITABLE);
    for (const child of this.children) {
      if (child.isEditable()) {
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
  return {
    title: 'Carrito',
    addEventListener(type, listener, capture) {
      assert.equal(capture, true, 'listeners must use the capture phase');
      listeners.set(type, listener);
    },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) {
        listeners.delete(type);
      }
    },
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

/** Inicia la captura con un contexto de sustitutos y devuelve lo necesario para probarla. */
function startCapture(session = { task_id: 3 }) {
  const document = createFakeDocument();
  globalThis.document = document;
  const added = [];
  registered.start({
    clock: { now: () => 1791380123456.2 },
    batcher: { add: (type, record) => added.push({ type, record }) },
    session: { get: () => session },
  });
  const click = (target, type = 'click', x = 845, y = 560) =>
    document.dispatch({ type, target, clientX: x, clientY: y });
  return { document, added, click, stop: () => registered.stop() };
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
  assert.deepEqual(document.listenerTypes(), ['click', 'contextmenu', 'dblclick']);

  registered.stop();

  assert.deepEqual(document.listenerTypes(), []);
  click(el('button'));
  assert.equal(added.length, 0);
});
