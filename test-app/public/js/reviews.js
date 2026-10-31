/**
 * @file Opiniones de clientes, ficticias. Cada producto muestra siempre las
 * mismas, elegidas de una lista fija según su identificador, para que todas
 * las sesiones vean la misma página.
 */

/**
 * @typedef {object} Review
 * @property {string} author - Nombre corto, ficticio.
 * @property {number} stars - Calificación, de 1 a 5.
 * @property {string} title - Título de la opinión.
 * @property {string} text - Texto de la opinión.
 */

/** @type {ReadonlyArray<Readonly<Review>>} */
const POOL = Object.freeze(
  [
    { author: 'Laura M.', stars: 5, title: 'Muy buena compra', text: 'Llegó antes de lo esperado y bien empacado. Hace lo que promete.' },
    { author: 'Andrés P.', stars: 4, title: 'Cumple', text: 'Buena relación calidad-precio. Le quito una estrella porque el manual es muy corto.' },
    { author: 'Camila R.', stars: 5, title: 'Lo recomiendo', text: 'Lo uso todos los días desde hace un mes y funciona perfecto.' },
    { author: 'Jorge L.', stars: 3, title: 'Está bien', text: 'Es lo que esperaba por el precio, ni más ni menos.' },
    { author: 'Valentina S.', stars: 4, title: 'Buen producto', text: 'Se ve mejor que en las fotos. La entrega tardó un día más de lo indicado.' },
    { author: 'Felipe G.', stars: 5, title: 'Excelente', text: 'Segunda vez que lo compro, esta vez para regalar.' },
  ].map((review) => Object.freeze(review)),
);

/** Opiniones que se muestran por producto. */
const PER_PRODUCT = 3;

/**
 * Opiniones de un producto.
 *
 * @param {{ id: number }} product - Producto.
 * @returns {Review[]} Tres opiniones, siempre las mismas para el mismo producto.
 */
export function reviewsFor(product) {
  const start = product.id % POOL.length;
  return Array.from({ length: PER_PRODUCT }, (_, index) => POOL[(start + index) % POOL.length]);
}
