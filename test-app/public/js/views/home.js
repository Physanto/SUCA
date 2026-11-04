/**
 * @file Página de inicio (`/`): portada, categorías y productos destacados.
 */

import { CATEGORIES, FEATURED_PRODUCTS, FREE_SHIPPING_FROM, PRODUCTS } from '../data.js';
import { h, wait } from '../dom.js';
import { money } from '../format.js';
import { LATENCY } from '../timing.js';
import { productGrid } from '../ui.js';

/**
 * Dibuja la pantalla.
 *
 * @returns {Promise<object>} Título y contenido.
 */
export async function render() {
  await wait(LATENCY.page);
  const featured = FEATURED_PRODUCTS.map((id) => PRODUCTS.find((product) => product.id === id));
  return {
    title: 'Inicio',
    node: h(
      'div',
      { class: 'home' },
      h(
        'section',
        { class: 'hero' },
        h('h1', { tabindex: -1 }, 'Tecnología y hogar, a un clic'),
        h(
          'p',
          null,
          `Envío gratis en compras desde ${money(FREE_SHIPPING_FROM)} a las principales ciudades del país.`,
        ),
        h('a', { href: '/offers', class: 'button button-primary' }, 'Ver ofertas'),
      ),
      h(
        'section',
        { 'aria-labelledby': 'categories-title' },
        h('h2', { id: 'categories-title' }, 'Categorías'),
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
      ),
      h(
        'section',
        { 'aria-labelledby': 'featured-title' },
        h('h2', { id: 'featured-title' }, 'Destacados'),
        productGrid(featured),
        h(
          'p',
          { class: 'section-more' },
          h('a', { href: '/products', class: 'button button-secondary' }, 'Ver todos los productos'),
        ),
      ),
    ),
  };
}
