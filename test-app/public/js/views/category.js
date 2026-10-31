/**
 * @file Listado de una categoría (`/category/:slug`) y página de ofertas
 * (`/offers`).
 */

import { findCategory, PRODUCTS } from '../data.js';
import { h, wait } from '../dom.js';
import { productCount } from '../format.js';
import { LATENCY } from '../timing.js';
import { breadcrumbs, productGrid } from '../ui.js';

/**
 * Dibuja el listado de una categoría.
 *
 * @param {object} ctx - Contexto de la aplicación.
 * @param {{ params: { slug: string } }} route - Ruta actual.
 * @returns {Promise<object>} Título y contenido, o `notFound` si la categoría no existe.
 */
export async function render(ctx, { params }) {
  const category = findCategory(params.slug);
  if (!category) return { notFound: true };
  await wait(LATENCY.page);
  const products = PRODUCTS.filter((product) => product.category === category.slug);
  return {
    title: category.name,
    node: listing(category.name, products, [
      ['Inicio', '/'],
      [category.name, null],
    ]),
  };
}

/**
 * Dibuja la página de ofertas: productos con descuento, del mayor al menor.
 *
 * @returns {Promise<object>} Título y contenido.
 */
export async function renderOffers() {
  await wait(LATENCY.page);
  const discount = (product) => 1 - product.price / product.listPrice;
  const products = PRODUCTS.filter((product) => product.listPrice).sort(
    (a, b) => discount(b) - discount(a),
  );
  return {
    title: 'Ofertas',
    node: listing('Ofertas', products, [
      ['Inicio', '/'],
      ['Ofertas', null],
    ]),
  };
}

/**
 * Estructura común de un listado.
 *
 * @param {string} title - Título visible.
 * @param {ReadonlyArray<import('../data.js').Product>} products - Productos.
 * @param {Array<[string, string|null]>} trail - Migas de pan.
 * @returns {HTMLElement} Sección del listado.
 */
function listing(title, products, trail) {
  return h(
    'section',
    { class: 'listing', 'aria-labelledby': 'listing-title' },
    breadcrumbs(trail),
    h('h1', { id: 'listing-title', tabindex: -1 }, title),
    h('p', { class: 'muted' }, productCount(products.length)),
    productGrid(products),
  );
}
