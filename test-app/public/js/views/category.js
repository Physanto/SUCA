/**
 * @file Listados del catálogo: todos los productos (`/products`), una
 * categoría (`/category/:slug`) y ofertas (`/offers`).
 */

import { findCategory, PRODUCTS } from '../data.js';
import { h, wait } from '../dom.js';
import { LATENCY } from '../timing.js';
import { breadcrumbs } from '../ui.js';
import { productListing } from './listing.js';

/**
 * Dibuja todos los productos del catálogo.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ query: URLSearchParams }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido.
 */
export async function renderAll(ctx, { query }) {
  await wait(LATENCY.page);
  return {
    title: 'Todos los productos',
    node: page(ctx, query, 'Todos los productos', PRODUCTS, [
      ['Inicio', '/'],
      ['Todos los productos', null],
    ]),
  };
}

/**
 * Dibuja el listado de una categoría.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ params: { slug: string }, query: URLSearchParams }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido, o `notFound` si la categoría no existe.
 */
export async function render(ctx, { params, query }) {
  const category = findCategory(params.slug);
  if (!category) return { notFound: true };
  await wait(LATENCY.page);
  const products = PRODUCTS.filter((product) => product.category === category.slug);
  return {
    title: category.name,
    node: page(ctx, query, category.name, products, [
      ['Inicio', '/'],
      [category.name, null],
    ]),
  };
}

/**
 * Dibuja la página de ofertas: productos con descuento, del mayor al menor.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ query: URLSearchParams }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido.
 */
export async function renderOffers(ctx, { query }) {
  await wait(LATENCY.page);
  const discount = (product) => 1 - product.price / product.listPrice;
  const products = PRODUCTS.filter((product) => product.listPrice).sort(
    (a, b) => discount(b) - discount(a),
  );
  return {
    title: 'Ofertas',
    node: page(ctx, query, 'Ofertas', products, [
      ['Inicio', '/'],
      ['Ofertas', null],
    ]),
  };
}

/**
 * Estructura común de un listado del catálogo.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {URLSearchParams} query - Consulta de la URL.
 * @param {string} title - Título visible.
 * @param {ReadonlyArray<import('../data.js').Product>} products - Productos.
 * @param {Array<[string, string|null]>} trail - Migas de pan.
 * @returns {HTMLElement} Sección del listado.
 */
function page(ctx, query, title, products, trail) {
  return h(
    'section',
    { class: 'listing', 'aria-labelledby': 'listing-title' },
    breadcrumbs(trail),
    h('h1', { id: 'listing-title', tabindex: -1 }, title),
    productListing(ctx, {
      products,
      query,
      empty: () => h('p', { class: 'empty-state' }, 'No hay productos con descuento en esta lista.'),
    }),
  );
}
