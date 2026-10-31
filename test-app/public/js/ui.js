/**
 * @file Piezas de interfaz que comparten varias pantallas: tarjetas de
 * producto, precios, calificaciones, resumen del pedido, pasos de la compra,
 * botones con estado de carga y avisos de datos de prueba.
 */

import { findCategory } from './data.js';
import { h } from './dom.js';
import { money } from './format.js';

/**
 * Imagen ilustrativa de un producto.
 *
 * @param {import('./data.js').Product} product - Producto.
 * @param {string} [className] - Clase adicional.
 * @returns {HTMLImageElement} Imagen decorativa (el nombre ya está en el texto).
 */
export function productImage(product, className = '') {
  return h('img', {
    class: `product-image ${className}`.trim(),
    src: `/images/${product.image}.svg`,
    alt: '',
    width: 320,
    height: 240,
    loading: 'lazy',
  });
}

/**
 * Precio con el precio anterior tachado si hay descuento.
 *
 * @param {import('./data.js').Product} product - Producto.
 * @returns {HTMLElement} Bloque del precio.
 */
export function price(product) {
  return h(
    'p',
    { class: 'price' },
    h('span', { class: 'price-current' }, money(product.price)),
    product.listPrice
      ? [
          ' ',
          h('s', { class: 'price-before' }, money(product.listPrice)),
          ' ',
          h(
            'span',
            { class: 'price-discount' },
            `-${Math.round((1 - product.price / product.listPrice) * 100)} %`,
          ),
        ]
      : null,
  );
}

/**
 * Calificación con estrellas y número de opiniones.
 *
 * @param {import('./data.js').Product} product - Producto.
 * @returns {HTMLElement} Bloque de la calificación.
 */
export function rating(product) {
  const stars = Math.round(product.rating);
  return h(
    'p',
    { class: 'rating' },
    h('span', { class: 'stars', 'aria-hidden': 'true' }, '★'.repeat(stars) + '☆'.repeat(5 - stars)),
    ` ${product.rating.toLocaleString('es-CO')} (${product.reviews} opiniones)`,
  );
}

/**
 * Tarjeta de producto para listados y resultados.
 *
 * @param {import('./data.js').Product} product - Producto.
 * @returns {HTMLElement} Tarjeta con un enlace al detalle en el nombre.
 */
export function productCard(product) {
  const category = findCategory(product.category);
  return h(
    'article',
    { class: 'product-card' },
    productImage(product),
    h('p', { class: 'product-card-category' }, category ? category.name : ''),
    h('h3', { class: 'product-card-title' }, h('a', { href: `/product/${product.id}` }, product.name)),
    rating(product),
    price(product),
  );
}

/**
 * Lista de tarjetas de producto.
 *
 * @param {ReadonlyArray<import('./data.js').Product>} products - Productos.
 * @returns {HTMLElement} Lista.
 */
export function productGrid(products) {
  return h(
    'ul',
    { class: 'product-grid' },
    products.map((product) => h('li', null, productCard(product))),
  );
}

/**
 * Resumen del pedido: una línea por producto (`Nombre × 2`) y los totales.
 *
 * @param {ReturnType<import('./cart.js').cartLines>} lines - Líneas del carrito.
 * @param {ReturnType<import('./cart.js').totals>} sums - Totales.
 * @param {...Node} footer - Contenido al final del resumen (por ejemplo, un botón).
 * @returns {HTMLElement} Resumen.
 */
export function orderSummary(lines, sums, ...footer) {
  return h(
    'section',
    { class: 'summary', 'aria-labelledby': 'summary-title' },
    h('h2', { id: 'summary-title' }, 'Resumen del pedido'),
    h(
      'ul',
      { class: 'summary-lines' },
      lines.map((line) =>
        h(
          'li',
          null,
          h('span', null, `${line.product.name} × ${line.quantity}`),
          h('span', null, money(line.subtotal)),
        ),
      ),
    ),
    h(
      'dl',
      { class: 'summary-totals' },
      h('dt', null, 'Subtotal'),
      h('dd', null, money(sums.subtotal)),
      h('dt', null, 'Envío'),
      h('dd', null, sums.shipping === 0 ? 'Gratis' : money(sums.shipping)),
      h('dt', { class: 'summary-total' }, 'Total'),
      h('dd', { class: 'summary-total' }, money(sums.total)),
    ),
    footer,
  );
}

/**
 * Pasos de la compra con el actual resaltado.
 *
 * @param {number} current - Paso actual: 1 envío, 2 pago, 3 confirmación.
 * @returns {HTMLElement} Lista ordenada de pasos.
 */
export function checkoutSteps(current) {
  const steps = ['Envío', 'Pago', 'Confirmación'];
  return h(
    'ol',
    { class: 'steps', 'aria-label': 'Pasos de la compra' },
    steps.map((label, index) =>
      h(
        'li',
        {
          class: index + 1 < current ? 'done' : index + 1 === current ? 'current' : null,
          'aria-current': index + 1 === current ? 'step' : null,
        },
        label,
      ),
    ),
  );
}

/**
 * Aviso con datos de prueba para que nadie escriba datos propios. El título
 * debe decir qué hacer con ellos ("usa esta cuenta…"), no solo qué son.
 *
 * @param {string} title - Título del aviso.
 * @param {Array<[string, string]>} rows - Etiqueta y valor de cada dato.
 * @returns {HTMLElement} Aviso.
 */
export function testDataNotice(title, rows) {
  return h(
    'aside',
    { class: 'notice notice-info', 'aria-label': title },
    h('p', { class: 'notice-title' }, title),
    h(
      'dl',
      { class: 'notice-data' },
      rows.map(([label, value]) => [h('dt', null, label), h('dd', null, value)]),
    ),
  );
}

/**
 * Pone un botón en estado de carga mientras dura una tarea, con un texto que
 * dice qué está pasando, y lo devuelve a su estado al terminar.
 *
 * Se usa `aria-disabled` y no `disabled`: el botón sigue recibiendo el foco y
 * los clics (que se ignoran), así no desaparece para el lector de pantalla.
 *
 * @param {HTMLButtonElement} button - Botón.
 * @param {string} busyText - Texto mientras carga, por ejemplo `Agregando…`.
 * @param {() => Promise<T>} task - Tarea asíncrona.
 * @returns {Promise<T>} Resultado de la tarea.
 * @template T
 */
export async function withBusyButton(button, busyText, task) {
  const label = button.textContent;
  button.setAttribute('aria-disabled', 'true');
  button.setAttribute('aria-busy', 'true');
  button.classList.add('is-busy');
  button.replaceChildren(h('span', { class: 'spinner', 'aria-hidden': 'true' }), busyText);
  try {
    return await task();
  } finally {
    if (button.isConnected) {
      button.removeAttribute('aria-disabled');
      button.removeAttribute('aria-busy');
      button.classList.remove('is-busy');
      button.textContent = label;
    }
  }
}

/**
 * Indica si un botón está ocupado y debe ignorar los clics.
 *
 * @param {Element} button - Botón.
 * @returns {boolean} Si tiene `aria-disabled="true"`.
 */
export function isBusy(button) {
  return button.getAttribute('aria-disabled') === 'true';
}

/**
 * Bloque de "cargando" para el contenido principal.
 *
 * @returns {HTMLElement} Indicador de carga.
 */
export function loadingBlock() {
  return h(
    'div',
    { class: 'loading', role: 'status' },
    h('span', { class: 'spinner', 'aria-hidden': 'true' }),
    'Cargando…',
  );
}

/**
 * Ruta de migas de pan.
 *
 * @param {Array<[string, string|null]>} items - Texto y enlace de cada nivel;
 *   el último (la página actual) va sin enlace.
 * @returns {HTMLElement} Navegación de migas.
 */
export function breadcrumbs(items) {
  return h(
    'nav',
    { class: 'breadcrumbs', 'aria-label': 'Ruta de navegación' },
    h(
      'ol',
      null,
      items.map(([label, href]) =>
        h('li', null, href ? h('a', { href }, label) : h('span', { 'aria-current': 'page' }, label)),
      ),
    ),
  );
}
