/**
 * @file Cuenta del cliente: resumen con datos, dirección y pedidos
 * (`/account`), datos personales (`/account/profile`), dirección de envío
 * (`/account/address`) y detalle de un pedido (`/account/orders/:id`).
 */

import { cartLines, countUnits, totals } from '../cart.js';
import { findProduct } from '../data.js';
import { formValues, h, showFieldErrors, wait } from '../dom.js';
import { cityField, textField } from '../fields.js';
import { money, productCount } from '../format.js';
import { LATENCY } from '../timing.js';
import { breadcrumbs, isBusy, orderSummary, withBusyButton } from '../ui.js';
import { validateAddress, validateProfile } from '../validation.js';

/** Formato de la fecha de un pedido. */
const DATE = new Intl.DateTimeFormat('es-CO', { dateStyle: 'long' });

/**
 * Dibuja el resumen de la cuenta.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido.
 */
export function renderAccount(ctx) {
  const { user, address, phone, orders } = ctx.shop.get();
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
          h('p', { class: 'muted' }, phone),
          h('a', { href: '/account/profile', class: 'account-link' }, 'Editar datos personales'),
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
          h('td', null, h('a', { href: `/account/orders/${order.id}` }, `N.º ${order.id}`)),
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
  const { form, status } = accountForm({
    fields: [
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
    ],
    validate: validateAddress,
    save: (values) =>
      ctx.shop.updateAddress({
        street: values.street.trim(),
        city: values.city,
        details: values.details.trim(),
      }),
    success: 'Dirección actualizada',
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

/**
 * Formulario de la cuenta con validación, botón con estado de carga y un
 * mensaje de éxito que se lee en voz alta (`role="status"`).
 *
 * @param {object} options - Partes del formulario.
 * @param {Node[]} options.fields - Campos.
 * @param {(values: Object<string, string>) => Object<string, string>} options.validate - Validación.
 * @param {(values: Object<string, string>) => void} options.save - Guarda los valores válidos.
 * @param {string} options.success - Mensaje al guardar.
 * @returns {{ form: HTMLFormElement, status: HTMLElement }} Formulario y zona del mensaje.
 */
function accountForm({ fields, validate, save, success }) {
  const status = h('div', { class: 'status-area', role: 'status' });
  const submit = h('button', { type: 'submit', class: 'button button-primary' }, 'Guardar');
  const form = h(
    'form',
    { class: 'form', novalidate: true },
    fields,
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
    const errors = validate(values);
    showFieldErrors(form, errors);
    if (Object.keys(errors).length > 0) return;
    await withBusyButton(submit, 'Guardando…', () => wait(LATENCY.saveAddress));
    save(values);
    status.replaceChildren(h('p', { class: 'notice notice-success' }, success));
  });
  return { form, status };
}

/**
 * Dibuja la edición de los datos personales.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido.
 */
export function renderProfile(ctx) {
  const { user, phone } = ctx.shop.get();
  const { form, status } = accountForm({
    fields: [
      textField({ id: 'profile-name', name: 'name', label: 'Nombre completo', value: user.name, attrs: { autocomplete: 'name' } }),
      textField({
        id: 'profile-phone',
        name: 'phone',
        label: 'Teléfono',
        value: phone,
        attrs: { type: 'tel', autocomplete: 'tel', inputmode: 'tel' },
      }),
      h(
        'div',
        { class: 'field' },
        h('p', { class: 'field-label' }, 'Correo electrónico'),
        h('p', null, user.email),
        h('p', { class: 'field-hint' }, 'El correo identifica tu cuenta y no se puede cambiar.'),
      ),
    ],
    validate: validateProfile,
    save: (values) => ctx.shop.updateProfile({ name: values.name.trim(), phone: values.phone.trim() }),
    success: 'Datos actualizados',
  });
  return {
    title: 'Datos personales',
    node: h(
      'div',
      { class: 'account-page narrow' },
      breadcrumbs([
        ['Mi cuenta', '/account'],
        ['Datos personales', null],
      ]),
      h('h1', { tabindex: -1 }, 'Datos personales'),
      status,
      form,
    ),
  };
}

/**
 * Dibuja el detalle de un pedido.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ params: { id: string } }} route - Ruta actual.
 * @returns {object} Título y contenido, o `notFound` si el pedido no existe.
 */
export function renderOrder(ctx, { params }) {
  const order = ctx.shop.get().orders.find((item) => String(item.id) === params.id);
  if (!order) return { notFound: true };
  const lines = cartLines(order.items, findProduct);
  return {
    title: `Pedido ${order.id}`,
    node: h(
      'div',
      { class: 'account-page' },
      breadcrumbs([
        ['Mi cuenta', '/account'],
        [`Pedido ${order.id}`, null],
      ]),
      h('h1', { tabindex: -1 }, `Pedido N.º ${order.id}`),
      h(
        'div',
        { class: 'checkout-layout' },
        h(
          'dl',
          { class: 'details' },
          h('dt', null, 'Fecha'),
          h('dd', null, DATE.format(order.placedAt)),
          h('dt', null, 'Estado'),
          h('dd', null, 'En preparación · llega en 2 a 4 días hábiles'),
          h('dt', null, 'Envío'),
          h('dd', null, `${order.shipping.name}, ${order.shipping.street}, ${order.shipping.city}`),
          h('dt', null, 'Pago'),
          h('dd', null, order.payment.label),
        ),
        orderSummary(lines, totals(lines)),
      ),
    ),
  };
}
