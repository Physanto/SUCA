/**
 * @file Pruebas de `content/layout.js`: qué regiones y elementos registra la
 * disposición de la pantalla, y cómo arma su árbol, con un documento falso.
 */

const test = require('node:test');
const assert = require('node:assert/strict');

require('../content/camera/zones.js');
require('../content/layout.js');

const { UX } = globalThis;

/**
 * Nodo falso con etiqueta, atributos, caja, posición CSS y padre.
 *
 * @param {string} tag - Etiqueta.
 * @param {object} [options] - Atributos, caja `{left, top, width, height}`, `position`,
 *   `visibility`, padre y texto propio.
 * @returns {object} Nodo.
 */
function node(tag, { attributes = {}, box = { left: 0, top: 0, width: 100, height: 40 }, position = 'static', visibility = 'visible', parent = null, text = null } = {}) {
  return {
    nodeType: 1,
    childNodes: text === null ? [] : [{ nodeType: 3, nodeValue: text }],
    tagName: tag.toUpperCase(),
    id: attributes.id || '',
    parentElement: parent,
    style: { position, visibility },
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    hasAttribute: (name) => name in attributes,
    getBoundingClientRect: () => ({ ...box, right: box.left + box.width, bottom: box.top + box.height }),
  };
}

/** Página falsa que devuelve los mismos nodos para cada consulta, como `querySelectorAll`. */
function page(nodes, { scrollY = 0 } = {}) {
  return {
    innerWidth: 1000,
    innerHeight: 600,
    scrollX: 0,
    scrollY,
    getComputedStyle: (element) => element.style,
    document: { querySelectorAll: () => nodes },
  };
}

/** Medidor con criterios simples: interactivos son `a`, `button` e `input`. */
function meter(options = {}) {
  return UX.createLayoutMeter({
    regionOf: UX.gazeZones.regionOf,
    selectorOf: (element) => (element.id ? `#${element.id}` : element.tagName.toLowerCase()),
    roleOf: (element, tag) => element.getAttribute('role') || (tag === 'a' ? 'link' : tag === 'button' ? 'button' : null),
    isInteractive: (element) => ['A', 'BUTTON', 'INPUT'].includes(element.tagName),
    screen: () => ({ url: 'https://shop.local/cart', title: 'Carrito' }),
    ...options,
  });
}

test('records the visible semantic regions and whether they are fixed', () => {
  const header = node('header', { box: { left: 0, top: 0, width: 1000, height: 60 }, position: 'fixed' });
  const main = node('main', { box: { left: 0, top: -200, width: 1000, height: 2000 } });
  const banner = node('div', { attributes: { role: 'banner' }, box: { left: 0, top: 700, width: 1000, height: 50 } });
  const plainDiv = node('div');

  const record = meter().measure(page([header, main, banner, plainDiv], { scrollY: 200 }), 123);

  assert.deepEqual(record.regions, [
    { zone: 'header', box: { x: 0, y: 0, w: 1000, h: 60 }, fixed: true },
    { zone: 'main', box: { x: 0, y: -200, w: 1000, h: 2000 }, fixed: false },
  ]);
  assert.equal(record.scroll_y, 200);
  assert.deepEqual([record.t, record.viewport_width, record.viewport_height], [123, 1000, 600]);
  assert.deepEqual(record.screen, { url: 'https://shop.local/cart', title: 'Carrito' });
});

test('a header inside a section is not the page header', () => {
  const article = node('article');
  const localHeader = node('header', { parent: article });

  const record = meter().measure(page([localHeader]), 1);

  assert.deepEqual(record.regions, []);
});

test('records visible interactive elements with selector, role and box, never their text', () => {
  const nav = node('nav', { position: 'sticky' });
  const link = node('a', { attributes: { id: 'home', href: '/' }, box: { left: 10.04, top: 5.06, width: 80, height: 30 }, parent: nav });
  const hidden = node('button', { attributes: { id: 'ghost' }, visibility: 'hidden' });
  const outside = node('button', { attributes: { id: 'below' }, box: { left: 0, top: 900, width: 50, height: 20 } });
  const empty = node('button', { attributes: { id: 'zero' }, box: { left: 0, top: 0, width: 0, height: 0 } });
  const paragraph = node('p');

  const record = meter().measure(page([link, hidden, outside, empty, paragraph]), 1);

  assert.deepEqual(record.elements.filter((element) => element.interactive), [
    {
      selector: '#home',
      tag: 'a',
      role: 'link',
      box: { x: 10, y: 5.1, w: 80, h: 30 },
      fixed: true,
      interactive: true,
      parent: null,
    },
  ]);
  assert.equal(record.truncated, false);
  assert.ok(!('text' in record.elements[0]));
});

test('records the content people look at without interacting, never its text', () => {
  const title = node('h1', { attributes: { id: 'title' }, box: { left: 0, top: 0, width: 400, height: 50 } });
  const error = node('div', { attributes: { id: 'error', role: 'alert' } });
  const live = node('div', { attributes: { id: 'live', 'aria-live': 'polite' } });
  const textBlock = node('div', { attributes: { id: 'price' }, text: ' $ 120.000 ' });
  const wrapper = node('div', { attributes: { id: 'wrapper' }, text: '   ' });
  const tiny = node('img', { attributes: { id: 'pixel' }, box: { left: 0, top: 0, width: 1, height: 1 } });

  const record = meter().measure(page([title, error, live, textBlock, wrapper, tiny]), 1);

  assert.deepEqual(
    record.elements.map((element) => [element.selector, element.tag, element.interactive]),
    [
      ['#title', 'h1', false],
      ['#error', 'div', false],
      ['#live', 'div', false],
      ['#price', 'div', false],
    ],
  );
  assert.ok(record.elements.every((element) => !('text' in element)));
});

test('what is inside a button, a link or an image is not recorded apart', () => {
  const button = node('button', { attributes: { id: 'buy' } });
  const icon = node('svg', { attributes: { id: 'icon' }, parent: button });
  const label = node('span', { attributes: { id: 'label' }, parent: button, text: 'Comprar' });
  const picture = node('svg', { attributes: { id: 'chart' } });
  const path = node('g', { attributes: { id: 'bars', role: 'img' }, parent: picture });

  const record = meter().measure(page([button, icon, label, picture, path]), 1);

  assert.deepEqual(record.elements.map((element) => element.selector), ['#buy', '#chart']);
});

test('each element points to its nearest recorded ancestor', () => {
  const card = node('article', { attributes: { id: 'card' }, box: { left: 0, top: 0, width: 300, height: 200 } });
  const plain = node('div', { attributes: { id: 'plain' }, parent: card });
  const heading = node('h2', { attributes: { id: 'name' }, parent: plain });
  const link = node('a', { attributes: { id: 'more', href: '/p/1' }, parent: plain });
  const loose = node('p', { attributes: { id: 'loose' } });

  const record = meter().measure(page([card, plain, heading, link, loose]), 1);
  const bySelector = Object.fromEntries(record.elements.map((element, index) => [element.selector, index]));

  assert.deepEqual(
    record.elements.map((element) => [element.selector, element.parent]),
    [
      ['#more', bySelector['#card']],
      ['#card', null],
      ['#name', bySelector['#card']],
      ['#loose', null],
    ],
  );
});

test('content has its own maximum, apart from the interactive elements', () => {
  const buttons = [1, 2].map((n) => node('button', { attributes: { id: `b${n}` } }));
  const paragraphs = [1, 2, 3].map((n) => node('p', { attributes: { id: `p${n}` } }));

  const record = meter({ maxContent: 2 }).measure(page([...buttons, ...paragraphs]), 1);

  assert.deepEqual(record.elements.map((element) => element.selector), ['#b1', '#b2', '#p1', '#p2']);
  assert.equal(record.truncated, true);
});

test('stops at the maximum number of elements and says so', () => {
  const buttons = [1, 2, 3].map((n) => node('button', { attributes: { id: `b${n}` } }));

  const record = meter({ maxElements: 2 }).measure(page(buttons), 1);

  assert.deepEqual(record.elements.map((element) => element.selector), ['#b1', '#b2']);
  assert.equal(record.truncated, true);
});

test('the fixed position of an ancestor is looked up once per measurement', () => {
  const header = node('header', { position: 'fixed' });
  const links = [1, 2, 3].map((n) => node('a', { attributes: { id: `l${n}` }, parent: header }));
  const lookups = new Map();
  const counting = page([header, ...links]);
  counting.getComputedStyle = (element) => {
    lookups.set(element, (lookups.get(element) || 0) + 1);
    return element.style;
  };

  const record = meter().measure(counting, 1);

  assert.ok(record.elements.every((element) => element.fixed));
  // El encabezado se consulta para su caja como región y luego una sola vez para su posición.
  assert.ok(lookups.get(header) <= 3);
});
