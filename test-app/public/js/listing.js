/**
 * @file Orden, filtro y páginas de los listados de productos. Funciones puras:
 * no modifican la lista que reciben.
 */

/** Productos que se muestran de entrada y en cada "Cargar más". */
export const PAGE_SIZE = 8;

/**
 * Órdenes disponibles: valor en la URL (`?sort=`), texto visible y comparación.
 * `relevance` conserva el orden de llegada (el de la búsqueda o el catálogo).
 */
export const SORTS = Object.freeze([
  { value: 'relevance', label: 'Más relevantes', compare: null },
  { value: 'price_asc', label: 'Menor precio', compare: (a, b) => a.price - b.price },
  { value: 'price_desc', label: 'Mayor precio', compare: (a, b) => b.price - a.price },
  { value: 'rating', label: 'Mejor calificados', compare: (a, b) => b.rating - a.rating },
]);

/**
 * @typedef {object} ListingOptions
 * @property {string} sort - Valor de `SORTS`.
 * @property {boolean} discountOnly - Solo productos con descuento.
 */

/**
 * Lee las opciones del listado de la consulta de la URL. Los valores
 * desconocidos se ignoran.
 *
 * @param {URLSearchParams} query - Consulta de la URL.
 * @returns {ListingOptions} Opciones del listado.
 */
export function listingOptions(query) {
  const sort = query.get('sort');
  return {
    sort: SORTS.some((item) => item.value === sort) ? sort : 'relevance',
    discountOnly: query.get('discount') === '1',
  };
}

/**
 * Escribe las opciones del listado en una consulta, conservando los demás
 * parámetros (por ejemplo, `q` de la búsqueda). Las opciones por defecto no se escriben.
 *
 * @param {URLSearchParams} query - Consulta actual.
 * @param {ListingOptions} options - Opciones elegidas.
 * @returns {URLSearchParams} Consulta nueva.
 */
export function withListingOptions(query, options) {
  const next = new URLSearchParams(query);
  if (options.sort === 'relevance') next.delete('sort');
  else next.set('sort', options.sort);
  if (options.discountOnly) next.set('discount', '1');
  else next.delete('discount');
  return next;
}

/**
 * Ordena y filtra una lista de productos.
 *
 * @param {ReadonlyArray<import('./data.js').Product>} products - Productos en su orden de llegada.
 * @param {ListingOptions} options - Orden y filtro.
 * @returns {import('./data.js').Product[]} Lista nueva; a igual valor, conserva el orden de llegada.
 */
export function arrange(products, { sort, discountOnly }) {
  const kept = discountOnly ? products.filter((product) => product.listPrice) : [...products];
  const { compare } = SORTS.find((item) => item.value === sort) ?? SORTS[0];
  // Array.prototype.sort es estable: los empates quedan en el orden de llegada.
  return compare ? kept.sort(compare) : kept;
}
