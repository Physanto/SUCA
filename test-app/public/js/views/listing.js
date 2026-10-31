/**
 * @file Listado de productos con orden, filtro de descuento y "Cargar más",
 * compartido por búsqueda, categorías, ofertas y todos los productos.
 *
 * Ordenar o filtrar cambia la lista sin cambiar de pantalla: la consulta de
 * la URL se reemplaza (`?sort=price_asc`) para que recargar o compartir el
 * enlace conserve la elección, sin agregar entradas al historial.
 */

import { h, wait } from '../dom.js';
import { productCount } from '../format.js';
import { arrange, listingOptions, PAGE_SIZE, SORTS, withListingOptions } from '../listing.js';
import { LATENCY } from '../timing.js';
import { isBusy, productCard, withBusyButton } from '../ui.js';

/**
 * Crea el listado.
 *
 * @param {object} ctx - Contexto de la aplicación (usa `replaceQuery`).
 * @param {object} options - Datos del listado.
 * @param {ReadonlyArray<import('../data.js').Product>} options.products - Productos en su
 *   orden de llegada (relevancia).
 * @param {URLSearchParams} options.query - Consulta actual de la URL.
 * @param {() => Node} [options.empty] - Contenido cuando el filtro no deja productos.
 * @returns {HTMLElement} Controles, lista y botón para cargar más.
 */
export function productListing(ctx, { products, query, empty }) {
  let options = listingOptions(query);
  let currentQuery = query;
  let shown = PAGE_SIZE;

  const sort = h(
    'select',
    { id: 'sort', name: 'sort', value: options.sort },
    SORTS.map((item) => h('option', { value: item.value }, item.label)),
  );
  const discount = h('input', { id: 'discount-only', type: 'checkbox', checked: options.discountOnly });
  const count = h('p', { class: 'listing-count muted', role: 'status' });
  const list = h('ul', { class: 'product-grid' });
  const more = h('button', { type: 'button', class: 'button button-secondary' }, 'Cargar más productos');
  const footer = h('div', { class: 'listing-more' });

  /** Dibuja los productos visibles y el botón para cargar más. */
  const draw = () => {
    const arranged = arrange(products, options);
    const visible = arranged.slice(0, shown);
    count.textContent =
      arranged.length > visible.length
        ? `Mostrando ${visible.length} de ${productCount(arranged.length)}`
        : productCount(arranged.length);
    list.replaceChildren(...visible.map((product) => h('li', null, productCard(product))));
    list.hidden = arranged.length === 0;
    // replaceChildren convertiría un null en el texto "null": se filtran los vacíos.
    footer.replaceChildren(
      ...[arranged.length === 0 && empty ? empty() : null, arranged.length > visible.length ? more : null].filter(
        Boolean,
      ),
    );
  };

  /** Aplica el orden y el filtro elegidos y los guarda en la URL. */
  const apply = () => {
    options = { sort: sort.value, discountOnly: discount.checked };
    currentQuery = withListingOptions(currentQuery, options);
    ctx.replaceQuery(currentQuery);
    shown = PAGE_SIZE;
    draw();
  };
  sort.addEventListener('change', apply);
  discount.addEventListener('change', apply);
  more.addEventListener('click', async () => {
    if (isBusy(more)) return;
    const firstNew = shown;
    await withBusyButton(more, 'Cargando…', () => wait(LATENCY.page));
    shown += PAGE_SIZE;
    draw();
    // El foco pasa al primer producto nuevo, para seguir desde ahí con el teclado.
    list.children[firstNew]?.querySelector('a')?.focus();
  });
  draw();

  return h(
    'div',
    { class: 'listing-body' },
    h(
      'div',
      { class: 'listing-controls' },
      count,
      h(
        'div',
        { class: 'listing-filters' },
        h('div', { class: 'field field-inline' }, discount, h('label', { for: 'discount-only' }, 'Solo con descuento')),
        h('div', { class: 'field field-inline' }, h('label', { for: 'sort' }, 'Ordenar por'), sort),
      ),
    ),
    list,
    footer,
  );
}
