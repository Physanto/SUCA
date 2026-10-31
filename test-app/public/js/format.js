/**
 * @file Formatos de presentación: dinero, cantidades y textos de búsqueda.
 */

const MONEY = new Intl.NumberFormat('es-CO', {
  style: 'currency',
  currency: 'COP',
  maximumFractionDigits: 0,
});

/**
 * Da formato de pesos colombianos a un valor.
 *
 * @param {number} value - Valor en pesos.
 * @returns {string} Por ejemplo, `$ 179.900`.
 */
export function money(value) {
  // Intl separa el símbolo con un espacio duro; se cambia por uno normal para
  // que el texto se copie y se compare igual que se ve.
  return MONEY.format(value).replace(/\s/g, ' ');
}

/**
 * Escribe una cantidad de productos con su sustantivo.
 *
 * @param {number} count - Número de productos.
 * @returns {string} Por ejemplo, `1 producto` o `2 productos`.
 */
export function productCount(count) {
  return `${count} ${count === 1 ? 'producto' : 'productos'}`;
}

/**
 * Normaliza un texto para compararlo: minúsculas, sin tildes y sin signos.
 *
 * @param {string} text - Texto original.
 * @returns {string} Palabras separadas por un espacio.
 */
export function normalizeText(text) {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9ñ]+/g, ' ')
    .trim();
}
