/**
 * @file Detalle de producto (`/product/:id`): imagen, precio, cantidad,
 * agregar al carrito, descripción y características.
 */

import { clampQuantity } from '../cart.js';
import { findCategory, findProduct, MAX_QUANTITY } from '../data.js';
import { h, wait } from '../dom.js';
import { LATENCY } from '../timing.js';
import { breadcrumbs, isBusy, price, productImage, rating, withBusyButton } from '../ui.js';

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
        h('div', { class: 'product-gallery' }, productImage(product, 'product-image-large')),
        h(
          'div',
          { class: 'product-info' },
          h('p', { class: 'product-card-category' }, category.name),
          h('h1', { tabindex: -1 }, product.name),
          rating(product),
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
    ),
  };
}
