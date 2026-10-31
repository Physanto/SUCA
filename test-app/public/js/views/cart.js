/**
 * @file Carrito (`/cart`): productos, cantidades, totales y el paso a la compra.
 *
 * Se redibuja con cada cambio del carrito y devuelve el foco al mismo control,
 * para que quien usa el teclado no lo pierda.
 */

import { cartLines, countUnits, totals } from '../cart.js';
import { FREE_SHIPPING_FROM, findProduct, MAX_QUANTITY } from '../data.js';
import { h } from '../dom.js';
import { money, productCount } from '../format.js';
import { orderSummary, productImage } from '../ui.js';

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título, contenido y la función que cancela la suscripción.
 */
export function render(ctx) {
  const container = h('div', { class: 'cart-page' });

  /** Dibuja el contenido con el estado actual, conservando el control enfocado. */
  const draw = () => {
    const focused = document.activeElement;
    const focusKey = focused && container.contains(focused) ? focused.getAttribute('aria-label') : null;
    container.replaceChildren(...content(ctx));
    if (focusKey) {
      const target = [...container.querySelectorAll('[aria-label]')].find(
        (element) => element.getAttribute('aria-label') === focusKey && !element.disabled,
      );
      (target ?? container.querySelector('h1')).focus();
    }
  };
  draw();
  const unsubscribe = ctx.shop.subscribe(draw);
  return { title: 'Carrito', node: container, cleanup: unsubscribe };
}

/**
 * Contenido del carrito según el estado.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {Node[]} Nodos del contenido.
 */
function content(ctx) {
  const { cart } = ctx.shop.get();
  const heading = h('h1', { tabindex: -1 }, 'Carrito');
  if (cart.length === 0) {
    return [
      heading,
      h(
        'div',
        { class: 'empty-state' },
        h('p', null, 'Tu carrito está vacío.'),
        h('a', { href: '/', class: 'button button-primary' }, 'Explorar productos'),
      ),
    ];
  }
  const lines = cartLines(cart, findProduct);
  const sums = totals(lines);
  const missing = FREE_SHIPPING_FROM - sums.subtotal;
  return [
    heading,
    h('p', { class: 'muted' }, `Tienes ${productCount(countUnits(cart))} en tu carrito.`),
    h(
      'div',
      { class: 'cart-layout' },
      h(
        'table',
        { class: 'cart-table' },
        h('caption', { class: 'visually-hidden' }, 'Productos en tu carrito'),
        h(
          'thead',
          null,
          h(
            'tr',
            null,
            h('th', { scope: 'col' }, 'Producto'),
            h('th', { scope: 'col' }, 'Precio'),
            h('th', { scope: 'col' }, 'Cantidad'),
            h('th', { scope: 'col' }, 'Subtotal'),
            h('th', { scope: 'col' }, h('span', { class: 'visually-hidden' }, 'Acciones')),
          ),
        ),
        h('tbody', null, lines.map((line) => cartRow(ctx, line))),
      ),
      orderSummary(
        lines,
        sums,
        missing > 0
          ? h('p', { class: 'summary-note' }, `Agrega ${money(missing)} más y el envío es gratis.`)
          : h('p', { class: 'summary-note' }, 'Tu pedido tiene envío gratis.'),
        h('a', { href: '/checkout/shipping', class: 'button button-primary button-block' }, 'Ir a pagar'),
        h('a', { href: '/', class: 'button button-secondary button-block' }, 'Seguir comprando'),
      ),
    ),
  ];
}

/**
 * Fila de un producto del carrito.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {ReturnType<typeof cartLines>[number]} line - Línea del carrito.
 * @returns {HTMLTableRowElement} Fila.
 */
function cartRow(ctx, { product, quantity, subtotal }) {
  const { id, name } = product;
  return h(
    'tr',
    null,
    h(
      'td',
      { class: 'cart-product' },
      productImage(product, 'cart-thumb'),
      h('a', { href: `/product/${id}` }, name),
    ),
    h('td', null, money(product.price)),
    h(
      'td',
      null,
      h(
        'div',
        { class: 'stepper stepper-small' },
        h(
          'button',
          {
            type: 'button',
            class: 'stepper-button',
            'aria-label': `Disminuir cantidad de ${name}`,
            disabled: quantity <= 1,
            on: { click: () => ctx.shop.setQuantity(id, quantity - 1) },
          },
          '−',
        ),
        h('output', { class: 'stepper-value', 'aria-live': 'polite' }, String(quantity)),
        h(
          'button',
          {
            type: 'button',
            class: 'stepper-button',
            'aria-label': `Aumentar cantidad de ${name}`,
            disabled: quantity >= MAX_QUANTITY,
            on: { click: () => ctx.shop.setQuantity(id, quantity + 1) },
          },
          '+',
        ),
      ),
    ),
    h('td', null, money(subtotal)),
    h(
      'td',
      null,
      h(
        'button',
        {
          type: 'button',
          class: 'link-button',
          'aria-label': `Eliminar ${name}`,
          on: {
            click: () => {
              ctx.shop.removeFromCart(id);
              ctx.toast(`Quitaste ${name} del carrito.`);
            },
          },
        },
        'Eliminar',
      ),
    ),
  );
}
