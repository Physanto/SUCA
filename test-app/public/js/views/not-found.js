/**
 * @file Página para rutas, productos o pedidos que no existen.
 */

import { h } from '../dom.js';

/**
 * Dibuja la pantalla.
 *
 * @returns {object} Título y contenido.
 */
export function render() {
  return {
    title: 'Página no encontrada',
    node: h(
      'section',
      { class: 'empty-state narrow' },
      h('h1', { tabindex: -1 }, 'No encontramos esta página'),
      h('p', null, 'Puede que el enlace esté mal escrito o que la página ya no exista.'),
      h('a', { href: '/', class: 'button button-primary' }, 'Ir al inicio'),
    ),
  };
}
