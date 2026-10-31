/**
 * @file Campos de formulario con su etiqueta, ayuda y lugar para el error,
 * compartidos por la compra y la cuenta.
 */

import { CITIES } from './data.js';
import { h } from './dom.js';

/**
 * Campo de texto con su etiqueta, ayuda opcional y lugar para el error.
 *
 * @param {object} options - Datos del campo.
 * @param {string} options.id - Id del campo (también enlaza la etiqueta).
 * @param {string} options.name - Nombre en el formulario.
 * @param {string} options.label - Etiqueta visible.
 * @param {string} [options.value] - Valor inicial.
 * @param {string} [options.hint] - Ayuda bajo la etiqueta.
 * @param {object} [options.attrs] - Atributos adicionales del campo.
 * @returns {HTMLElement} Bloque del campo.
 */
export function textField({ id, name, label, value = '', hint, attrs = {} }) {
  const hintId = hint ? `${id}-hint` : null;
  return h(
    'div',
    { class: 'field' },
    h('label', { for: id }, label),
    hint ? h('p', { class: 'field-hint', id: hintId }, hint) : null,
    h('input', { id, name, type: 'text', value, 'aria-describedby': hintId, ...attrs }),
  );
}

/**
 * Lista desplegable de ciudades.
 *
 * @param {string} id - Id del campo.
 * @param {string} value - Ciudad elegida.
 * @returns {HTMLElement} Bloque del campo.
 */
export function cityField(id, value) {
  return h(
    'div',
    { class: 'field' },
    h('label', { for: id }, 'Ciudad'),
    h(
      'select',
      { id, name: 'city', value },
      h('option', { value: '' }, 'Elige una ciudad'),
      CITIES.map((city) => h('option', { value: city }, city)),
    ),
  );
}
