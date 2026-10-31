/**
 * @file Estado de la tienda (sesión, carrito, dirección y pedidos) y las
 * acciones que lo cambian.
 *
 * El estado se guarda en el almacenamiento del navegador, así recargar la
 * página no lo pierde, como en un sitio real. `reset` lo devuelve al inicio
 * (entre un participante y otro). Las vistas se suscriben para redibujarse.
 */

import { addItem, removeItem, setQuantity } from './cart.js';
import { DEMO_ACCOUNT, FIRST_ORDER_ID } from './data.js';
import { normalizeText } from './format.js';

/** Clave del estado en el almacenamiento. */
export const STORE_KEY = 'ceiba.store';

/** Versión del formato guardado; si cambia, se descarta el estado anterior. */
const STORE_VERSION = 1;

/**
 * @typedef {object} Order
 * @property {number} id - Número del pedido.
 * @property {import('./cart.js').CartItem[]} items - Productos y unidades.
 * @property {{ name: string, street: string, city: string, phone: string, notes: string }} shipping
 *   - Datos de envío.
 * @property {{ method: string, label: string }} payment - Método de pago.
 * @property {number} total - Total pagado.
 * @property {number} placedAt - Momento del pedido (ms desde 1970).
 */

/**
 * @typedef {object} ShopState
 * @property {{ name: string, email: string }|null} user - Sesión iniciada, o `null`.
 * @property {import('./cart.js').CartItem[]} cart - Carrito.
 * @property {{ street: string, city: string, details: string }} address - Dirección guardada.
 * @property {string} phone - Teléfono guardado.
 * @property {object|null} shipping - Datos de envío del pedido en curso.
 * @property {Order[]} orders - Pedidos hechos, del más reciente al más antiguo.
 * @property {number} nextOrderId - Número del siguiente pedido.
 */

/**
 * Estado inicial: sin sesión, carrito vacío y la dirección de la cuenta de
 * demostración.
 *
 * @returns {ShopState} Estado nuevo.
 */
export function initialState() {
  return {
    user: null,
    cart: [],
    address: { ...DEMO_ACCOUNT.address },
    phone: DEMO_ACCOUNT.phone,
    shipping: null,
    orders: [],
    nextOrderId: FIRST_ORDER_ID,
  };
}

/**
 * Comprueba las credenciales de la cuenta de demostración. El correo no
 * distingue mayúsculas ni espacios alrededor; la contraseña sí.
 *
 * @param {string} email - Correo escrito.
 * @param {string} password - Contraseña escrita.
 * @returns {boolean} Si coinciden con la cuenta de demostración.
 */
export function checkCredentials(email, password) {
  return (
    normalizeText(email) === normalizeText(DEMO_ACCOUNT.email) &&
    password === DEMO_ACCOUNT.password
  );
}

/**
 * Crea la tienda sobre un almacenamiento.
 *
 * @param {Storage} storage - Almacenamiento del navegador (o un sustituto).
 * @param {{ now?: () => number }} [options] - Reloj, para las pruebas.
 * @returns {object} Tienda con `get`, `subscribe` y las acciones.
 */
export function createShop(storage, { now = () => Date.now() } = {}) {
  let state = load();
  const listeners = new Set();

  /** Lee el estado guardado; si no hay uno válido, empieza de cero. */
  function load() {
    try {
      const saved = JSON.parse(storage.getItem(STORE_KEY) ?? 'null');
      if (saved && saved.version === STORE_VERSION) return { ...initialState(), ...saved.state };
    } catch {
      // Un valor corrupto se descarta.
    }
    return initialState();
  }

  /** Reemplaza el estado, lo guarda y avisa a los suscriptores. */
  function commit(next) {
    state = next;
    storage.setItem(STORE_KEY, JSON.stringify({ version: STORE_VERSION, state }));
    for (const listener of [...listeners]) listener(state);
  }

  return {
    /**
     * Devuelve el estado actual (no se debe modificar).
     *
     * @returns {ShopState} Estado actual.
     */
    get: () => state,

    /**
     * Avisa de cada cambio del estado.
     *
     * @param {(state: ShopState) => void} listener - Función que recibe el estado nuevo.
     * @returns {() => void} Función que cancela la suscripción.
     */
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    /**
     * Inicia sesión si las credenciales son las de la cuenta de demostración.
     *
     * @param {string} email - Correo escrito.
     * @param {string} password - Contraseña escrita.
     * @returns {boolean} Si se inició la sesión.
     */
    login(email, password) {
      if (!checkCredentials(email, password)) return false;
      commit({ ...state, user: { name: DEMO_ACCOUNT.name, email: DEMO_ACCOUNT.email } });
      return true;
    },

    /** Cierra la sesión; conserva el carrito, como la mayoría de las tiendas. */
    logout() {
      commit({ ...state, user: null, shipping: null });
    },

    /**
     * Agrega unidades de un producto al carrito.
     *
     * @param {number} productId - Producto.
     * @param {number} quantity - Unidades.
     */
    addToCart(productId, quantity) {
      commit({ ...state, cart: addItem(state.cart, productId, quantity) });
    },

    /**
     * Cambia las unidades de un producto del carrito.
     *
     * @param {number} productId - Producto.
     * @param {number} quantity - Unidades nuevas.
     */
    setQuantity(productId, quantity) {
      commit({ ...state, cart: setQuantity(state.cart, productId, quantity) });
    },

    /**
     * Quita un producto del carrito.
     *
     * @param {number} productId - Producto.
     */
    removeFromCart(productId) {
      commit({ ...state, cart: removeItem(state.cart, productId) });
    },

    /**
     * Guarda los datos de envío del pedido en curso.
     *
     * @param {Order['shipping']} shipping - Datos de envío ya validados.
     */
    saveShipping(shipping) {
      commit({ ...state, shipping: { ...shipping } });
    },

    /**
     * Crea el pedido con el carrito y el envío guardado, y vacía el carrito.
     *
     * @param {{ method: string, label: string }} payment - Método de pago.
     * @param {number} total - Total del pedido.
     * @returns {Order} Pedido creado.
     */
    placeOrder(payment, total) {
      const order = {
        id: state.nextOrderId,
        items: state.cart.map((item) => ({ ...item })),
        shipping: { ...state.shipping },
        payment: { ...payment },
        total,
        placedAt: now(),
      };
      commit({
        ...state,
        cart: [],
        shipping: null,
        orders: [order, ...state.orders],
        nextOrderId: state.nextOrderId + 1,
      });
      return order;
    },

    /**
     * Cambia la dirección de envío guardada en la cuenta.
     *
     * @param {{ street: string, city: string, details: string }} address - Dirección validada.
     */
    updateAddress(address) {
      commit({ ...state, address: { ...address } });
    },

    /** Vuelve al estado inicial: sin sesión, sin carrito y sin pedidos. */
    reset() {
      commit(initialState());
    },
  };
}
