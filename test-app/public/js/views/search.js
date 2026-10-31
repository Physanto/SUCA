/**
 * @file Resultados de búsqueda (`/search?q=…`).
 */

import { CATEGORIES, PRODUCTS } from '../data.js';
import { h, wait } from '../dom.js';
import { searchProducts } from '../search.js';
import { LATENCY } from '../timing.js';
import { productListing } from './listing.js';

/**
 * Dibuja la pantalla.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ query: URLSearchParams }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido.
 */
export async function render(ctx, { query }) {
  const text = (query.get('q') ?? '').trim();
  await wait(LATENCY.page);
  // Problema 8 (`strict_search`): sin tolerancia a errores de escritura ni a prefijos.
  const found = searchProducts(PRODUCTS, text, { tolerant: !ctx.problems.has('strict_search') });
  const heading = text ? `Resultados para “${text}”` : 'Buscar productos';
  return {
    title: 'Resultados',
    node: h(
      'section',
      { class: 'results', 'aria-labelledby': 'results-title' },
      h('h1', { id: 'results-title', tabindex: -1 }, heading),
      found.length > 0
        ? productListing(ctx, {
            products: found,
            query,
            empty: () =>
              h('p', { class: 'empty-state' }, 'Ningún resultado tiene descuento. Quita el filtro para verlos todos.'),
          })
        : emptyResults(text),
    ),
  };
}

/**
 * Mensaje cuando la búsqueda no encuentra nada, con sugerencias para seguir.
 *
 * @param {string} text - Texto buscado.
 * @returns {HTMLElement} Bloque de sugerencias.
 */
function emptyResults(text) {
  return h(
    'div',
    { class: 'empty-state' },
    h(
      'p',
      null,
      text
        ? `No encontramos productos para “${text}”.`
        : 'Escribe en el buscador qué producto quieres encontrar.',
    ),
    h(
      'ul',
      null,
      h('li', null, 'Revisa que las palabras estén bien escritas.'),
      h('li', null, 'Usa palabras más generales, por ejemplo “audífonos”.'),
    ),
    h('p', null, 'También puedes explorar por categoría:'),
    h(
      'ul',
      { class: 'category-list' },
      CATEGORIES.map((category) =>
        h(
          'li',
          null,
          h('a', { href: `/category/${category.slug}`, class: 'category-tile' }, category.name),
        ),
      ),
    ),
  );
}
