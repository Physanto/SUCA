/**
 * @file Centro de ayuda (`/help`): preguntas frecuentes en secciones
 * desplegables y datos de contacto ficticios.
 *
 * Cada pregunta tiene un ancla (`/help#olvide-mi-contrasena`); si la URL la
 * trae, esa pregunta se abre.
 */

import { FREE_SHIPPING_FROM, SHIPPING_COST } from '../data.js';
import { h } from '../dom.js';
import { money } from '../format.js';

/** Preguntas frecuentes: ancla, pregunta y respuesta. */
const QUESTIONS = [
  [
    'costo-del-envio',
    '¿Cuánto cuesta el envío?',
    `El envío cuesta ${money(SHIPPING_COST)} y es gratis en compras desde ${money(FREE_SHIPPING_FROM)}.`,
  ],
  ['tiempo-de-entrega', '¿Cuánto tarda en llegar mi pedido?', 'Entre 2 y 4 días hábiles en las ciudades principales.'],
  [
    'medios-de-pago',
    '¿Qué medios de pago aceptan?',
    'Tarjetas de crédito y débito, y transferencia bancaria por PSE.',
  ],
  [
    'devoluciones',
    '¿Puedo devolver un producto?',
    'Sí, tienes 30 días para devolver un producto sin usar y en su empaque original.',
  ],
  [
    'olvide-mi-contrasena',
    '¿Olvidaste tu contraseña?',
    'Escríbenos a ayuda@ceiba.test desde el correo de tu cuenta y te ayudaremos a recuperarla.',
  ],
];

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ hash: string }} route - Ruta actual; `hash` es el ancla sin `#`.
 * @returns {object} Título y contenido.
 */
export function render(ctx, { hash }) {
  // Un enlace a otra pregunta desde esta misma pantalla (por ejemplo, en el
  // pie) solo cambia el fragmento: se abre la pregunta sin redibujar.
  const openFromHash = () => {
    const target = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
    if (target instanceof HTMLDetailsElement) target.open = true;
  };
  window.addEventListener('hashchange', openFromHash);
  return {
    title: 'Ayuda',
    cleanup: () => window.removeEventListener('hashchange', openFromHash),
    node: h(
      'section',
      { class: 'help', 'aria-labelledby': 'help-title' },
      h('h1', { id: 'help-title', tabindex: -1 }, 'Centro de ayuda'),
      h('p', { class: 'muted' }, 'Respuestas a las preguntas más frecuentes.'),
      h(
        'div',
        { class: 'faq' },
        QUESTIONS.map(([id, question, answer]) =>
          h('details', { id, open: id === hash }, h('summary', null, question), h('p', null, answer)),
        ),
      ),
      h(
        'section',
        { class: 'card', 'aria-labelledby': 'contact-title' },
        h('h2', { id: 'contact-title' }, '¿Necesitas más ayuda?'),
        h('p', null, 'Escríbenos a ayuda@ceiba.test. Respondemos de lunes a sábado, de 8 a. m. a 6 p. m.'),
      ),
    ),
  };
}
