/**
 * @file Centro de ayuda (`/help`): preguntas frecuentes en secciones
 * desplegables y datos de contacto ficticios.
 */

import { FREE_SHIPPING_FROM, SHIPPING_COST } from '../data.js';
import { h } from '../dom.js';
import { money } from '../format.js';

/** Preguntas frecuentes: pregunta y respuesta. */
const QUESTIONS = [
  [
    '¿Cuánto cuesta el envío?',
    `El envío cuesta ${money(SHIPPING_COST)} y es gratis en compras desde ${money(FREE_SHIPPING_FROM)}.`,
  ],
  ['¿Cuánto tarda en llegar mi pedido?', 'Entre 2 y 4 días hábiles en las ciudades principales.'],
  [
    '¿Qué medios de pago aceptan?',
    'Tarjetas de crédito y débito, y transferencia bancaria por PSE.',
  ],
  [
    '¿Puedo devolver un producto?',
    'Sí, tienes 30 días para devolver un producto sin usar y en su empaque original.',
  ],
  [
    '¿Olvidaste tu contraseña?',
    'Escríbenos a ayuda@ceiba.test desde el correo de tu cuenta y te ayudaremos a recuperarla.',
  ],
];

/**
 * Dibuja la pantalla.
 *
 * @returns {object} Título y contenido.
 */
export function render() {
  return {
    title: 'Ayuda',
    node: h(
      'section',
      { class: 'help', 'aria-labelledby': 'help-title' },
      h('h1', { id: 'help-title', tabindex: -1 }, 'Centro de ayuda'),
      h('p', { class: 'muted' }, 'Respuestas a las preguntas más frecuentes.'),
      h(
        'div',
        { class: 'faq' },
        QUESTIONS.map(([question, answer]) =>
          h('details', null, h('summary', null, question), h('p', null, answer)),
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
