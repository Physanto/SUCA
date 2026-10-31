/**
 * @file Detalle de producto (`/product/:id`): imagen ampliable, precio,
 * cantidad, agregar al carrito, características, opiniones (con el ancla
 * `#resenas`) y productos relacionados.
 */

import { clampQuantity } from '../cart.js';
import { findCategory, findProduct, MAX_QUANTITY, PRODUCTS } from '../data.js';
import { h, wait } from '../dom.js';
import { reviewsFor } from '../reviews.js';
import { LATENCY } from '../timing.js';
import {
  breadcrumbs,
  isBusy,
  price,
  productGrid,
  productImage,
  rating,
  withBusyButton,
} from '../ui.js';

/** Productos relacionados que se muestran. */
const RELATED_COUNT = 4;

/**
 * Imagen del producto con un botón que la abre ampliada en un diálogo modal.
 * El diálogo se cierra con su botón, con Escape o con un clic fuera de él.
 *
 * @param {import('../data.js').Product} product - Producto.
 * @returns {HTMLElement} Galería con el botón y el diálogo.
 */
function gallery(product) {
  const close = h('button', { type: 'button', class: 'button button-secondary' }, 'Cerrar');
  const dialog = h(
    'dialog',
    { class: 'image-dialog', 'aria-labelledby': 'image-dialog-title' },
    h('h2', { id: 'image-dialog-title' }, product.name),
    productImage(product, 'product-image-zoom'),
    h('div', { class: 'form-actions' }, close),
  );
  const open = h('button', { type: 'button', class: 'button button-secondary zoom-button' }, 'Ampliar imagen');
  open.addEventListener('click', () => dialog.showModal());
  close.addEventListener('click', () => dialog.close());
  // Un clic en el fondo oscuro llega al propio diálogo, fuera de su contenido.
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  return h('div', { class: 'product-gallery' }, productImage(product, 'product-image-large'), open, dialog);
}

/**
 * Sección de opiniones de clientes.
 *
 * @param {import('../data.js').Product} product - Producto.
 * @returns {HTMLElement} Sección con `id="resenas"`, destino del enlace de la calificación.
 */
function reviewsSection(product) {
  const reviews = reviewsFor(product);
  return h(
    'section',
    { id: 'resenas', class: 'reviews', 'aria-labelledby': 'reviews-title' },
    h('h2', { id: 'reviews-title' }, 'Opiniones de clientes'),
    rating(product),
    h('p', { class: 'muted' }, `Mostrando las ${reviews.length} opiniones más recientes.`),
    h(
      'ul',
      { class: 'review-list' },
      reviews.map((review) =>
        h(
          'li',
          { class: 'card' },
          h(
            'p',
            { class: 'review-stars', 'aria-label': `${review.stars} de 5 estrellas` },
            '★'.repeat(review.stars) + '☆'.repeat(5 - review.stars),
          ),
          h('h3', null, review.title),
          h('p', null, review.text),
          h('p', { class: 'muted' }, review.author),
        ),
      ),
    ),
  );
}

/**
 * Selector de cantidad con botones para restar y sumar.
 *
 * Los botones se deshabilitan en los límites (1 y el máximo), así nunca hay
 * un clic que no haga nada.
 *
 * @returns {{ node: HTMLElement, value: () => number }} Selector y lectura del valor.
 */
function quantityPicker() {
  const input = h('input', {
    id: 'quantity',
    name: 'quantity',
    type: 'number',
    inputmode: 'numeric',
    min: 1,
    max: MAX_QUANTITY,
    value: '1',
  });
  const minus = h('button', { type: 'button', class: 'stepper-button', 'aria-label': 'Disminuir cantidad' }, '−');
  const plus = h('button', { type: 'button', class: 'stepper-button', 'aria-label': 'Aumentar cantidad' }, '+');

  /** Escribe una cantidad válida y actualiza los botones. */
  const set = (quantity) => {
    const value = clampQuantity(quantity);
    input.value = String(value);
    minus.disabled = value <= 1;
    plus.disabled = value >= MAX_QUANTITY;
  };
  minus.addEventListener('click', () => set(Number(input.value) - 1));
  plus.addEventListener('click', () => set(Number(input.value) + 1));
  input.addEventListener('change', () => set(Number(input.value)));
  set(1);

  return {
    node: h(
      'div',
      { class: 'field' },
      h('label', { for: 'quantity' }, 'Cantidad'),
      h('div', { class: 'stepper' }, minus, input, plus),
    ),
    value: () => clampQuantity(Number(input.value)),
  };
}

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ params: { id: string } }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido, o `notFound`.
 */
export async function render(ctx, { params }) {
  const product = /^\d+$/.test(params.id) ? findProduct(Number(params.id)) : undefined;
  if (!product) return { notFound: true };
  await wait(LATENCY.page);
  const category = findCategory(product.category);
  const quantity = quantityPicker();
  const addButton = h('button', { type: 'button', class: 'button button-primary button-large' }, 'Agregar al carrito');

  addButton.addEventListener('click', async () => {
    if (isBusy(addButton)) return;
    const units = quantity.value();
    await withBusyButton(addButton, 'Agregando…', () => wait(LATENCY.addToCart));
    ctx.shop.addToCart(product.id, units);
    ctx.toast(`Agregaste ${units} ${units === 1 ? 'unidad' : 'unidades'} de ${product.name} al carrito.`);
    ctx.navigate('/cart');
  });

  return {
    title: product.name,
    node: h(
      'article',
      { class: 'product-page' },
      breadcrumbs([
        ['Inicio', '/'],
        [category.name, `/category/${category.slug}`],
        [product.name, null],
      ]),
      h(
        'div',
        { class: 'product-layout' },
        gallery(product),
        h(
          'div',
          { class: 'product-info' },
          h('p', { class: 'product-card-category' }, category.name),
          h('h1', { tabindex: -1 }, product.name),
          h(
            'div',
            { class: 'rating-row' },
            rating(product),
            h('a', { href: '#resenas' }, 'Ver opiniones'),
          ),
          price(product),
          h('p', { class: 'stock' }, 'Disponible · Llega en 2 a 4 días hábiles'),
          h('p', null, product.summary),
          quantity.node,
          addButton,
        ),
      ),
      h(
        'section',
        { class: 'product-specs', 'aria-labelledby': 'specs-title' },
        h('h2', { id: 'specs-title' }, 'Características'),
        h(
          'table',
          { class: 'specs-table' },
          h(
            'tbody',
            null,
            product.specs.map(([name, value]) =>
              h('tr', null, h('th', { scope: 'row' }, name), h('td', null, value)),
            ),
          ),
        ),
      ),
      reviewsSection(product),
      h(
        'section',
        { class: 'related', 'aria-labelledby': 'related-title' },
        h('h2', { id: 'related-title' }, 'También te puede interesar'),
        productGrid(
          PRODUCTS.filter((item) => item.category === product.category && item.id !== product.id).slice(
            0,
            RELATED_COUNT,
          ),
        ),
      ),
    ),
  };
}
