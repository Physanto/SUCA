/**
 * @file Operaciones del carrito. Son funciones puras: reciben el carrito y
 * devuelven uno nuevo, sin modificar el original.
 */

import { FREE_SHIPPING_FROM, MAX_QUANTITY, SHIPPING_COST } from './data.js';

/**
 * @typedef {object} CartItem
 * @property {number} productId - Identificador del producto.
 * @property {number} quantity - Unidades, de 1 a `MAX_QUANTITY`.
 */

/**
 * Limita una cantidad al rango permitido.
 *
 * @param {number} quantity - Cantidad pedida.
 * @returns {number} Entre 1 y `MAX_QUANTITY`.
 */
export function clampQuantity(quantity) {
  if (!Number.isFinite(quantity)) return 1;
  return Math.min(MAX_QUANTITY, Math.max(1, Math.round(quantity)));
}

/**
 * Agrega unidades de un producto; si ya estaba, suma a las que tenía.
 *
 * @param {ReadonlyArray<CartItem>} cart - Carrito actual.
 * @param {number} productId - Producto que se agrega.
 * @param {number} quantity - Unidades que se agregan.
 * @returns {CartItem[]} Carrito nuevo.
 */
export function addItem(cart, productId, quantity) {
  const existing = cart.find((item) => item.productId === productId);
  if (!existing) return [...cart, { productId, quantity: clampQuantity(quantity) }];
  return setQuantity(cart, productId, existing.quantity + quantity);
}

/**
 * Cambia las unidades de un producto del carrito.
 *
 * @param {ReadonlyArray<CartItem>} cart - Carrito actual.
 * @param {number} productId - Producto que cambia.
 * @param {number} quantity - Unidades nuevas.
 * @returns {CartItem[]} Carrito nuevo.
 */
export function setQuantity(cart, productId, quantity) {
  return cart.map((item) =>
    item.productId === productId ? { ...item, quantity: clampQuantity(quantity) } : item,
  );
}

/**
 * Quita un producto del carrito.
 *
 * @param {ReadonlyArray<CartItem>} cart - Carrito actual.
 * @param {number} productId - Producto que se quita.
 * @returns {CartItem[]} Carrito nuevo.
 */
export function removeItem(cart, productId) {
  return cart.filter((item) => item.productId !== productId);
}

/**
 * Cuenta las unidades del carrito.
 *
 * @param {ReadonlyArray<CartItem>} cart - Carrito.
 * @returns {number} Suma de las unidades.
 */
export function countUnits(cart) {
  return cart.reduce((total, item) => total + item.quantity, 0);
}

/**
 * Une cada elemento del carrito con su producto y su subtotal.
 *
 * @param {ReadonlyArray<CartItem>} cart - Carrito.
 * @param {(id: number) => (import('./data.js').Product|undefined)} find - Busca un producto.
 * @returns {Array<{ product: import('./data.js').Product, quantity: number, subtotal: number }>}
 *   Líneas del carrito; se omiten productos que ya no existen.
 */
export function cartLines(cart, find) {
  return cart.flatMap((item) => {
    const product = find(item.productId);
    if (!product) return [];
    return [{ product, quantity: item.quantity, subtotal: product.price * item.quantity }];
  });
}

/**
 * Calcula los totales de un pedido.
 *
 * @param {ReadonlyArray<{ subtotal: number }>} lines - Líneas del carrito.
 * @returns {{ subtotal: number, shipping: number, total: number }} Totales en pesos.
 */
export function totals(lines) {
  const subtotal = lines.reduce((sum, line) => sum + line.subtotal, 0);
  const shipping = subtotal === 0 || subtotal >= FREE_SHIPPING_FROM ? 0 : SHIPPING_COST;
  return { subtotal, shipping, total: subtotal + shipping };
}
