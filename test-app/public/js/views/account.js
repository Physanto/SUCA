/**
 * @file Cuenta del cliente: resumen con datos, dirección y pedidos
 * (`/account`) y edición de la dirección de envío (`/account/address`).
 */

import { cartLines, countUnits } from '../cart.js';
import { findProduct } from '../data.js';
import { formValues, h, showFieldErrors, wait } from '../dom.js';
import { cityField, textField } from '../fields.js';
import { money, productCount } from '../format.js';
import { LATENCY } from '../timing.js';
import { breadcrumbs, isBusy, withBusyButton } from '../ui.js';
import { validateAddress } from '../validation.js';

/** Formato de la fecha de un pedido. */
const DATE = new Intl.DateTimeFormat('es-CO', { dateStyle: 'long' });

/**
 * Dibuja el resumen de la cuenta.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido.
 */
export function renderAccount(ctx) {
  const { user, address, orders } = ctx.shop.get();
  return {
    title: 'Mi cuenta',
    node: h(
      'div',
      { class: 'account-page' },
      h('h1', { tabindex: -1 }, 'Mi cuenta'),
      h(
        'div',
        { class: 'account-grid' },
        h(
          'section',
          { class: 'card', 'aria-labelledby': 'personal-title' },
          h('h2', { id: 'personal-title' }, 'Datos personales'),
          h('p', null, user.name),
          h('p', { class: 'muted' }, user.email),
        ),
        h(
          'section',
          { class: 'card', 'aria-labelledby': 'address-title' },
          h('h2', { id: 'address-title' }, 'Dirección de envío'),
          h('p', null, address.street),
          h('p', { class: 'muted' }, [address.city, address.details].filter(Boolean).join(' · ')),
          h('a', { href: '/account/address', class: 'account-link' }, 'Cambiar dirección de envío'),
        ),
      ),
      h(
        'section',
        { id: 'pedidos', class: 'orders', 'aria-labelledby': 'orders-title' },
        h('h2', { id: 'orders-title' }, 'Mis pedidos'),
        orders.length === 0
          ? h('p', { class: 'muted' }, 'Aún no tienes pedidos.')
          : ordersTable(orders),
      ),
    ),
  };
}

/**
 * Tabla de pedidos.
 *
 * @param {ReadonlyArray<import('../shop.js').Order>} orders - Pedidos.
 * @returns {HTMLTableElement} Tabla.
 */
function ordersTable(orders) {
  return h(
    'table',
    { class: 'orders-table' },
    h(
      'thead',
      null,
      h(
        'tr',
        null,
        h('th', { scope: 'col' }, 'Pedido'),
        h('th', { scope: 'col' }, 'Fecha'),
        h('th', { scope: 'col' }, 'Productos'),
        h('th', { scope: 'col' }, 'Total'),
        h('th', { scope: 'col' }, 'Estado'),
      ),
    ),
    h(
      'tbody',
      null,
      orders.map((order) =>
        h(
          'tr',
          null,
          h('td', null, String(order.id)),
          h('td', null, DATE.format(order.placedAt)),
          h(
            'td',
            null,
            cartLines(order.items, findProduct)
              .map((line) => line.product.name)
              .join(', '),
            h('span', { class: 'muted' }, ` (${productCount(countUnits(order.items))})`),
          ),
          h('td', null, money(order.total)),
          h('td', null, 'En preparación'),
        ),
      ),
    ),
  );
}

/**
 * Dibuja la edición de la dirección de envío.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido.
 */
export function renderAddress(ctx) {
  const { address } = ctx.shop.get();
  const status = h('div', { class: 'status-area', role: 'status' });
  const submit = h('button', { type: 'submit', class: 'button button-primary' }, 'Guardar');
  const form = h(
    'form',
    { class: 'form', novalidate: true },
    textField({
      id: 'street',
      name: 'street',
      label: 'Dirección',
      value: address.street,
      hint: 'Por ejemplo: Calle 10 # 20-30',
      attrs: { autocomplete: 'street-address' },
    }),
    cityField('city', address.city),
    textField({
      id: 'details',
      name: 'details',
      label: 'Apartamento, oficina o referencia (opcional)',
      value: address.details,
    }),
    h(
      'div',
      { class: 'form-actions' },
      submit,
      h('a', { href: '/account', class: 'button button-secondary' }, 'Volver a mi cuenta'),
    ),
  );

  form.addEventListener('input', () => status.replaceChildren());
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    status.replaceChildren();
    const values = formValues(form);
    const errors = validateAddress(values);
    showFieldErrors(form, errors);
    if (Object.keys(errors).length > 0) return;
    await withBusyButton(submit, 'Guardando…', () => wait(LATENCY.saveAddress));
    ctx.shop.updateAddress({
      street: values.street.trim(),
      city: values.city,
      details: values.details.trim(),
    });
    status.replaceChildren(
      h('p', { class: 'notice notice-success' }, 'Dirección actualizada'),
    );
  });

  return {
    title: 'Dirección de envío',
    node: h(
      'div',
      { class: 'account-page narrow' },
      breadcrumbs([
        ['Mi cuenta', '/account'],
        ['Dirección de envío', null],
      ]),
      h('h1', { tabindex: -1 }, 'Dirección de envío'),
      h('p', { class: 'muted' }, 'Usamos esta dirección para tus próximos pedidos.'),
      status,
      form,
    ),
  };
}
