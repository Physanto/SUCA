/**
 * @file Pantalla de inicio de sesión (`/login`).
 *
 * Usa la validación nativa del navegador (campos obligatorios y formato del
 * correo) y una comprobación propia de las credenciales. Muestra la cuenta de
 * demostración para que el participante no escriba datos propios.
 */

import { DEMO_ACCOUNT } from '../data.js';
import { h, wait } from '../dom.js';
import { LATENCY } from '../timing.js';
import { isBusy, testDataNotice, withBusyButton } from '../ui.js';

/**
 * Ruta interna segura a la que volver después de iniciar sesión.
 *
 * @param {string|null} next - Valor del parámetro `next`.
 * @returns {string} La ruta, si es interna; si no, el inicio.
 */
export function safeNext(next) {
  return next && next.startsWith('/') && !next.startsWith('//') ? next : '/';
}

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ query: URLSearchParams }} route - Ruta actual.
 * @returns {object} Título y contenido, o una redirección si ya hay sesión.
 */
export function render(ctx, { query }) {
  const next = safeNext(query.get('next'));
  if (ctx.shop.get().user) return { redirect: next };

  const alert = h('div', { class: 'form-alert', role: 'alert' });
  const email = h('input', {
    id: 'email',
    name: 'email',
    type: 'email',
    autocomplete: 'username',
    required: true,
  });
  const password = h('input', {
    id: 'password',
    name: 'password',
    type: 'password',
    autocomplete: 'current-password',
    required: true,
  });
  const showPassword = h('input', {
    id: 'show-password',
    type: 'checkbox',
    on: {
      change: () => {
        password.type = showPassword.checked ? 'text' : 'password';
      },
    },
  });
  const submit = h('button', { type: 'submit', class: 'button button-primary button-block' }, 'Ingresar');

  const form = h(
    'form',
    { class: 'form login-form' },
    alert,
    h(
      'div',
      { class: 'field' },
      h('label', { for: 'email' }, 'Correo electrónico'),
      email,
    ),
    h(
      'div',
      { class: 'field' },
      h('label', { for: 'password' }, 'Contraseña'),
      password,
    ),
    h(
      'div',
      { class: 'field field-inline' },
      showPassword,
      h('label', { for: 'show-password' }, 'Mostrar contraseña'),
    ),
    submit,
    h('p', { class: 'form-links' }, h('a', { href: '/help#olvide-mi-contrasena' }, '¿Olvidaste tu contraseña?')),
  );

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (isBusy(submit)) return;
    alert.replaceChildren();
    const ok = await withBusyButton(submit, 'Ingresando…', async () => {
      await wait(LATENCY.login);
      return ctx.shop.login(email.value, password.value);
    });
    if (ok) {
      ctx.toast(`¡Hola, ${ctx.shop.get().user.name.split(' ')[0]}! Iniciaste sesión.`);
      ctx.navigate(next, { replace: true });
      return;
    }
    email.setAttribute('aria-invalid', 'true');
    password.setAttribute('aria-invalid', 'true');
    password.value = '';
    alert.replaceChildren(
      h(
        'p',
        null,
        'El correo o la contraseña no son correctos. Revisa los datos de la cuenta de demostración e inténtalo de nuevo.',
      ),
    );
    password.focus();
  });
  for (const field of [email, password]) {
    field.addEventListener('input', () => field.removeAttribute('aria-invalid'));
  }

  return {
    title: 'Iniciar sesión',
    node: h(
      'div',
      { class: 'auth-page' },
      h(
        'section',
        { class: 'card auth-card', 'aria-labelledby': 'login-title' },
        h('h1', { id: 'login-title', tabindex: -1 }, 'Iniciar sesión'),
        h('p', { class: 'muted' }, 'Ingresa para comprar y revisar tus pedidos.'),
        testDataNotice('Cuenta de demostración', [
          ['Correo', DEMO_ACCOUNT.email],
          ['Contraseña', DEMO_ACCOUNT.password],
        ]),
        form,
      ),
    ),
  };
}
