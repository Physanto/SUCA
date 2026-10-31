/**
 * @file Tiempos de respuesta simulados de la tienda, en milisegundos.
 *
 * En la tienda sin problemas todo responde en menos de un segundo y medio y
 * con un indicador de carga visible desde el primer instante, como recomienda
 * cualquier guía de usabilidad. Los problemas sembrados que hacen esperar más
 * definen sus propios tiempos.
 */

export const LATENCY = Object.freeze({
  /** Carga de una pantalla con datos (producto, búsqueda, categoría). */
  page: 300,
  /** Agregar al carrito. */
  addToCart: 450,
  /** Iniciar sesión. */
  login: 700,
  /** Procesar el pago. */
  payment: 1100,
  /** Guardar la dirección. */
  saveAddress: 500,
});

/**
 * Esperas de los problemas sembrados: más largas que el tiempo que la
 * captura observa la página tras un clic (1,5 s), y sin ninguna señal visible.
 */
export const PROBLEM_DELAY = Object.freeze({
  /** Problema 2: agregar al carrito. */
  addToCart: 3000,
  /** Problema 7: iniciar sesión. */
  login: 4000,
});

/** Cuánto tiempo se ve un aviso emergente. */
export const TOAST_MS = 4000;
