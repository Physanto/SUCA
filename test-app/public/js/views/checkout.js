/**
 * @file Compra en varios pasos: envío (`/checkout/shipping`), pago
 * (`/checkout/payment`) y confirmación (`/order/:id/confirmation`).
 *
 * Los datos de envío vienen de la cuenta, así el participante no escribe datos
 * propios; puede cambiarlos para el pedido. El pago usa la tarjeta de prueba
 * que se muestra en la pantalla.
 */

import { cartLines, totals } from '../cart.js';
import { BANKS, findProduct, TEST_CARD } from '../data.js';
import { formValues, h, showFieldErrors, wait } from '../dom.js';
import { cityField, textField } from '../fields.js';
import { money } from '../format.js';
import { LATENCY } from '../timing.js';
import { validatePayment, validateShipping } from '../validation.js';
import { checkoutSteps, isBusy, orderSummary, testDataNotice, withBusyButton } from '../ui.js';

/**
 * Líneas y totales del carrito actual.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {{ lines: ReturnType<typeof cartLines>, sums: ReturnType<typeof totals> }} Pedido.
 */
function currentOrder(ctx) {
  const lines = cartLines(ctx.shop.get().cart, findProduct);
  return { lines, sums: totals(lines) };
}

/**
 * Paso 1: datos de envío.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido, o una redirección al carrito si está vacío.
 */
export function renderShipping(ctx) {
  const state = ctx.shop.get();
  if (state.cart.length === 0) return { redirect: '/cart' };
  const saved = state.shipping ?? {
    name: state.user.name,
    street: state.address.street,
    city: state.address.city,
    phone: state.phone,
    notes: state.address.details,
  };
  const { lines, sums } = currentOrder(ctx);
  const alert = h('div', { class: 'form-alert', role: 'alert' });
  const form = h(
    'form',
    { class: 'form', novalidate: true },
    alert,
    textField({ id: 'ship-name', name: 'name', label: 'Nombre de quien recibe', value: saved.name, attrs: { autocomplete: 'name' } }),
    textField({ id: 'ship-street', name: 'street', label: 'Dirección', value: saved.street, attrs: { autocomplete: 'street-address' } }),
    cityField('ship-city', saved.city),
    textField({ id: 'ship-phone', name: 'phone', label: 'Teléfono de contacto', value: saved.phone, attrs: { type: 'tel', autocomplete: 'tel', inputmode: 'tel' } }),
    h(
      'div',
      { class: 'field' },
      h('label', { for: 'ship-notes' }, 'Indicaciones para la entrega (opcional)'),
      h('textarea', { id: 'ship-notes', name: 'notes', rows: 3, value: saved.notes }),
    ),
    h(
      'div',
      { class: 'form-actions' },
      h('button', { type: 'submit', class: 'button button-primary' }, 'Continuar al pago'),
      h('a', { href: '/cart', class: 'button button-secondary' }, 'Volver al carrito'),
    ),
  );

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const values = formValues(form);
    const errors = validateShipping(values);
    showFieldErrors(form, errors);
    if (Object.keys(errors).length > 0) {
      alert.replaceChildren(h('p', null, 'Revisa los campos marcados para continuar.'));
      return;
    }
    alert.replaceChildren();
    ctx.shop.saveShipping({
      name: values.name.trim(),
      street: values.street.trim(),
      city: values.city,
      phone: values.phone.trim(),
      notes: values.notes.trim(),
    });
    ctx.navigate('/checkout/payment');
  });

  return {
    title: 'Envío',
    node: checkoutPage(
      1,
      'Datos de envío',
      [h('p', { class: 'muted' }, 'Usamos los datos de tu cuenta. Puedes cambiarlos solo para este pedido.'), form],
      orderSummary(lines, sums),
    ),
  };
}

/**
 * Paso 2: pago con tarjeta o transferencia.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @returns {object} Título y contenido, o una redirección si falta un paso anterior.
 */
export function renderPayment(ctx) {
  const state = ctx.shop.get();
  if (state.cart.length === 0) return { redirect: '/cart' };
  if (!state.shipping) return { redirect: '/checkout/shipping' };
  const { lines, sums } = currentOrder(ctx);
  const { shipping } = state;
  const alert = h('div', { class: 'form-alert', role: 'alert' });
  // Problema 4 (`form_clears_on_error`): el número solo se acepta sin espacios
  // (solo lo dice el placeholder) y un error borra todos los datos de la tarjeta.
  const clears = ctx.problems.has('form_clears_on_error');
  // Problema 6 (`ambiguous_error`): el vencimiento solo se acepta como MM/AAAA
  // (solo lo dice el placeholder) y los errores se informan con un mensaje
  // genérico, sin decir qué campo falla.
  const ambiguous = ctx.problems.has('ambiguous_error');

  const methodError = h('p', { class: 'field-error', id: 'pay-method-error', hidden: true }, 'Elige un método de pago.');
  const radio = (id, value, label) =>
    h(
      'div',
      { class: 'choice' },
      h('input', { id, type: 'radio', name: 'method', value }),
      h('label', { for: id }, label),
    );
  const methods = h(
    'fieldset',
    { class: 'fieldset', 'aria-describedby': 'pay-method-error' },
    h('legend', null, 'Método de pago'),
    radio('pay-card', 'card', 'Tarjeta de crédito o débito'),
    radio('pay-pse', 'pse', 'Transferencia bancaria (PSE)'),
    methodError,
  );

  const cardSection = h(
    'div',
    { class: 'method-details', hidden: true },
    testDataNotice('Tarjeta de prueba', [
      ['Número', TEST_CARD.number],
      ['Nombre', TEST_CARD.name],
      ['Vencimiento', TEST_CARD.expiry],
      ['Código de seguridad', TEST_CARD.cvc],
    ]),
    textField({
      id: 'card-number',
      name: 'number',
      label: 'Número de la tarjeta',
      attrs: {
        autocomplete: 'cc-number',
        inputmode: 'numeric',
        placeholder: clears ? 'Solo números, sin espacios' : null,
      },
    }),
    textField({ id: 'card-name', name: 'name', label: 'Nombre como aparece en la tarjeta', attrs: { autocomplete: 'cc-name' } }),
    h(
      'div',
      { class: 'field-row' },
      textField({
        id: 'card-expiry',
        name: 'expiry',
        label: 'Vencimiento',
        hint: ambiguous ? undefined : 'MM/AA',
        attrs: { autocomplete: 'cc-exp', inputmode: 'numeric', placeholder: ambiguous ? 'MM/AAAA' : null },
      }),
      textField({ id: 'card-cvc', name: 'cvc', label: 'Código de seguridad', hint: '3 o 4 dígitos', attrs: { autocomplete: 'cc-csc', inputmode: 'numeric' } }),
    ),
  );
  const pseSection = h(
    'div',
    { class: 'method-details', hidden: true },
    h(
      'div',
      { class: 'field' },
      h('label', { for: 'pse-bank' }, 'Banco'),
      h(
        'select',
        { id: 'pse-bank', name: 'bank' },
        h('option', { value: '' }, 'Elige tu banco'),
        BANKS.map((bank) => h('option', { value: bank }, bank)),
      ),
    ),
    h('p', { class: 'muted' }, 'Al pagar, autorizas la transferencia con tu banco.'),
  );

  const submit = h('button', { type: 'submit', class: 'button button-primary button-large' }, `Pagar ${money(sums.total)}`);
  const form = h(
    'form',
    { class: 'form', novalidate: true },
    alert,
    methods,
    cardSection,
    pseSection,
    h('div', { class: 'form-actions' }, submit),
  );

  form.addEventListener('change', (event) => {
    if (!(event.target instanceof HTMLInputElement) || event.target.name !== 'method') return;
    cardSection.hidden = event.target.value !== 'card';
    pseSection.hidden = event.target.value !== 'pse';
    methodError.hidden = true;
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    const values = formValues(form);
    const errors = validatePayment({ ...values, method: values.method ?? '' }, ctx.now(), {
      digitsOnlyNumber: clears,
      fullYearExpiry: ambiguous,
    });
    methodError.hidden = !errors.method;
    // Solo se marcan los campos de la sección visible.
    const visible = Object.fromEntries(Object.entries(errors).filter(([key]) => key !== 'method'));
    const fieldsFailed = Object.keys(visible).length > 0;
    if (clears && fieldsFailed) {
      for (const field of cardSection.querySelectorAll('input')) field.value = '';
    }
    if (ambiguous && fieldsFailed) {
      showFieldErrors(form, {});
      alert.replaceChildren(
        h('p', null, 'No pudimos procesar el pago. Revisa los datos e inténtalo de nuevo. (Código E-102)'),
      );
      form.querySelector('.method-details:not([hidden]) :is(input, select)')?.focus();
      return;
    }
    showFieldErrors(form, visible);
    if (Object.keys(errors).length > 0) {
      alert.replaceChildren(h('p', null, 'Revisa los datos de pago marcados.'));
      if (errors.method) form.querySelector('#pay-card').focus();
      return;
    }
    alert.replaceChildren();
    const label = values.method === 'card' ? 'Tarjeta terminada en ' + values.number.replace(/\D/g, '').slice(-4) : `PSE · ${values.bank}`;
    await withBusyButton(submit, 'Procesando pago…', () => wait(LATENCY.payment));
    const order = ctx.shop.placeOrder({ method: values.method, label }, sums.total);
    ctx.navigate(`/order/${order.id}/confirmation`, { replace: true });
  });

  return {
    title: 'Pago',
    node: checkoutPage(
      2,
      'Pago',
      [
        h(
          'p',
          { class: 'shipping-recap' },
          `Enviar a ${shipping.name}: ${shipping.street}, ${shipping.city}. `,
          h('a', { href: '/checkout/shipping' }, 'Cambiar datos de envío'),
        ),
        form,
      ],
      orderSummary(lines, sums),
    ),
  };
}

/**
 * Paso 3: confirmación del pedido.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ params: { id: string } }} route - Ruta actual.
 * @returns {object} Título y contenido, o `notFound` si el pedido no existe.
 */
export function renderConfirmation(ctx, { params }) {
  const order = ctx.shop.get().orders.find((item) => String(item.id) === params.id);
  if (!order) return { notFound: true };
  const lines = cartLines(order.items, findProduct);
  return {
    title: 'Pedido confirmado',
    node: checkoutPage(
      3,
      'Pedido confirmado',
      [
        h(
          'div',
          { class: 'notice notice-success' },
          h('p', null, `Tu número de pedido es ${order.id}. Te enviamos el detalle a ${ctx.shop.get().user.email}.`),
          h('p', null, 'Llega en 2 a 4 días hábiles.'),
        ),
        h(
          'dl',
          { class: 'details' },
          h('dt', null, 'Envío'),
          h('dd', null, `${order.shipping.name}, ${order.shipping.street}, ${order.shipping.city}`),
          h('dt', null, 'Pago'),
          h('dd', null, order.payment.label),
        ),
        h(
          'div',
          { class: 'form-actions' },
          h('a', { href: '/', class: 'button button-primary' }, 'Seguir comprando'),
          h('a', { href: '/account#pedidos', class: 'button button-secondary' }, 'Ver mis pedidos'),
        ),
      ],
      orderSummary(lines, totals(lines)),
    ),
  };
}

/**
 * Estructura común de los pasos de la compra.
 *
 * @param {number} step - Paso actual (1 a 3).
 * @param {string} title - Título visible.
 * @param {Node[]} main - Contenido principal.
 * @param {Node} aside - Resumen del pedido.
 * @returns {HTMLElement} Página del paso.
 */
function checkoutPage(step, title, main, aside) {
  return h(
    'div',
    { class: 'checkout' },
    checkoutSteps(step),
    h(
      'div',
      { class: 'checkout-layout' },
      h('section', { class: 'checkout-main' }, h('h1', { tabindex: -1 }, title), main),
      h('aside', { class: 'checkout-aside' }, aside),
    ),
  );
}
